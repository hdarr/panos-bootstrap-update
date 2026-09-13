#!/usr/bin/env python3
"""PAN-OS XML API bulk configuration: generate an API key per firewall,
apply deviceconfig system settings, commit, and log the outcome."""

import logging
import sys
import time
import xml.etree.ElementTree as ET

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

FIREWALL_IPS = [
    "1.2.3.4",
    "5.6.7.8",
]

# Common credentials across all devices
USERNAME = "CHANGE_ME"
PASSWORD = "CHANGE_ME"

VERIFY_TLS = False
TIMEOUT = 30
COMMIT_POLL = 10          # seconds between job status checks
COMMIT_TIMEOUT = 600      # give up on a commit after this long
LOG_FILE = "panos_bootstrap.log"

SYSTEM_XPATH = "/config/devices/entry[@name='localhost.localdomain']/deviceconfig/system"

DHCP_CLIENT = (
    "<dhcp-client>"
    "<send-hostname>yes</send-hostname>"
    "<send-client-id>yes</send-client-id>"
    "<accept-dhcp-domain>yes</accept-dhcp-domain>"
    "<accept-dhcp-hostname>yes</accept-dhcp-hostname>"
    "</dhcp-client>"
)

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s %(levelname)-7s %(message)s",
    handlers=[logging.FileHandler(LOG_FILE), logging.StreamHandler(sys.stdout)],
)
log = logging.getLogger("panos")


def api(fw_ip, params, key=None):
    """POST to the XML API and raise on a non-success response."""
    data = dict(params)
    if key:
        data["key"] = key
    r = requests.post(f"https://{fw_ip}/api/", data=data,
                      verify=VERIFY_TLS, timeout=TIMEOUT)
    r.raise_for_status()
    root = ET.fromstring(r.text)
    if root.get("status") != "success":
        msg = " ".join(t.strip() for t in root.itertext() if t.strip())
        raise RuntimeError(f"API returned error: {msg or r.text}")
    return root


def get_api_key(fw_ip):
    root = api(fw_ip, {"type": "keygen", "user": USERNAME, "password": PASSWORD})
    key = root.findtext(".//key")
    if not key:
        raise RuntimeError("keygen succeeded but no key in response")
    return key


def set_config(fw_ip, key, xpath, element):
    return api(fw_ip, {"type": "config", "action": "set",
                       "xpath": xpath, "element": element}, key=key)


def commit(fw_ip, key):
    root = api(fw_ip, {"type": "commit", "cmd": "<commit></commit>"}, key=key)
    job = root.findtext(".//job")
    if not job:
        log.info("%s: nothing to commit (no pending changes)", fw_ip)
        return

    log.info("%s: commit job %s queued", fw_ip, job)
    deadline = time.time() + COMMIT_TIMEOUT
    while time.time() < deadline:
        time.sleep(COMMIT_POLL)
        j = api(fw_ip, {"type": "op",
                        "cmd": f"<show><jobs><id>{job}</id></jobs></show>"}, key=key)
        status = j.findtext(".//job/status")
        progress = j.findtext(".//job/progress")
        log.info("%s: job %s %s %s%%", fw_ip, job, status, progress)
        if status == "FIN":
            result = j.findtext(".//job/result")
            if result != "OK":
                details = " ".join(t.text.strip() for t in j.iter("line") if t.text)
                raise RuntimeError(f"commit finished with result {result} {details}")
            log.info("%s: commit completed OK", fw_ip)
            return
    raise RuntimeError(f"commit job {job} did not finish within {COMMIT_TIMEOUT}s")


def configure(fw_ip):
    log.info("%s: requesting API key as user '%s'", fw_ip, USERNAME)
    key = get_api_key(fw_ip)
    log.info("%s: API key retrieved", fw_ip)

    log.info("%s: setting dhcp-client options", fw_ip)
    set_config(fw_ip, key, f"{SYSTEM_XPATH}/type", DHCP_CLIENT)

    log.info("%s: disabling IPv6", fw_ip)
    set_config(fw_ip, key, SYSTEM_XPATH, "<ipv6-enable>no</ipv6-enable>")

    log.info("%s: committing", fw_ip)
    commit(fw_ip, key)


def main():
    if "CHANGE_ME" in (USERNAME, PASSWORD):
        sys.exit("Set USERNAME and PASSWORD before running.")

    succeeded, failed = [], []
    for fw_ip in FIREWALL_IPS:
        log.info("=== %s ===", fw_ip)
        try:
            configure(fw_ip)
            succeeded.append(fw_ip)
            log.info("%s: SUCCESS", fw_ip)
        except requests.exceptions.RequestException as e:
            failed.append(fw_ip)
            log.error("%s: FAILED - connection error: %s", fw_ip, e)
        except Exception as e:
            failed.append(fw_ip)
            log.error("%s: FAILED - %s", fw_ip, e)

    log.info("Summary: %d succeeded, %d failed (log: %s)",
             len(succeeded), len(failed), LOG_FILE)
    if failed:
        log.info("Failed devices: %s", ", ".join(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
