#!/usr/bin/env python3
"""PAN-OS XML API bulk configuration: generate an API key per firewall,
apply deviceconfig system settings, commit, and log the outcome."""

import csv
import logging
import sys
import time
import xml.etree.ElementTree as ET
from datetime import datetime

import requests
import urllib3

urllib3.disable_warnings(urllib3.exceptions.InsecureRequestWarning)

DEFAULT_INVENTORY = "devices.txt"

# Common credentials across all devices
USERNAME = "CHANGE_ME"
PASSWORD = "CHANGE_ME"

VERIFY_TLS = False
TIMEOUT = 30
COMMIT_POLL = 10          # seconds between job status checks
COMMIT_TIMEOUT = 600      # give up on a commit after this long
LOG_FILE = "panos_bootstrap_update.log"

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


def load_inventory(path):
    """One IP per line. Blank lines and # comments are ignored. A failed-devices
    CSV from a previous run is also accepted (first column, header skipped)."""
    devices = []
    with open(path, newline="") as f:
        for line in f:
            ip = line.split("#", 1)[0].split(",", 1)[0].strip()
            if ip and ip.lower() != "ip" and ip not in devices:
                devices.append(ip)
    return devices


def api(fw_ip, params, key=None):
    """POST to the XML API and raise on a non-success response."""
    data = dict(params)
    if key:
        data["key"] = key
    r = requests.post(f"https://{fw_ip}/api/", data=data,
                      verify=VERIFY_TLS, timeout=TIMEOUT)
    try:
        root = ET.fromstring(r.text)
    except ET.ParseError:
        r.raise_for_status()
        raise RuntimeError(f"unexpected non-XML response (HTTP {r.status_code})")
    if root.get("status") != "success":
        msg = " ".join(t.strip() for t in root.itertext() if t.strip())
        raise RuntimeError(f"API error (HTTP {r.status_code}): {msg or r.text}")
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
                raise RuntimeError(f"commit job {job} finished with result {result}: {details}")
            log.info("%s: commit completed OK", fw_ip)
            return
    raise RuntimeError(f"commit job {job} did not finish within {COMMIT_TIMEOUT}s")


def configure(fw_ip, progress):
    progress["step"] = "login"
    log.info("%s: requesting API key as user '%s'", fw_ip, USERNAME)
    key = get_api_key(fw_ip)
    log.info("%s: API key retrieved", fw_ip)

    progress["step"] = "set dhcp-client"
    log.info("%s: setting dhcp-client options", fw_ip)
    set_config(fw_ip, key, f"{SYSTEM_XPATH}/type", DHCP_CLIENT)

    progress["step"] = "disable ipv6"
    log.info("%s: disabling IPv6", fw_ip)
    set_config(fw_ip, key, SYSTEM_XPATH, "<ipv6-enable>no</ipv6-enable>")

    progress["step"] = "commit"
    log.info("%s: committing", fw_ip)
    commit(fw_ip, key)


def write_failures(failed):
    path = f"failed_devices_{datetime.now():%Y%m%d_%H%M%S}.csv"
    with open(path, "w", newline="") as f:
        writer = csv.writer(f)
        writer.writerow(["ip", "step", "reason"])
        writer.writerows(failed)
    return path


def main():
    if "CHANGE_ME" in (USERNAME, PASSWORD):
        sys.exit("Set USERNAME and PASSWORD before running.")

    inventory = sys.argv[1] if len(sys.argv) > 1 else DEFAULT_INVENTORY
    try:
        devices = load_inventory(inventory)
    except OSError as e:
        sys.exit(f"Cannot read inventory file: {e}")
    if not devices:
        sys.exit(f"No devices found in {inventory}")

    log.info("Loaded %d devices from %s", len(devices), inventory)
    succeeded, failed = [], []
    for fw_ip in devices:
        log.info("=== %s ===", fw_ip)
        progress = {"step": "start"}
        try:
            configure(fw_ip, progress)
            succeeded.append(fw_ip)
            log.info("%s: SUCCESS", fw_ip)
            continue
        except requests.exceptions.RequestException as e:
            reason = f"connection error: {e}"
        except Exception as e:
            reason = str(e)
        failed.append((fw_ip, progress["step"], reason))
        log.error("%s: FAILED at step '%s' - %s", fw_ip, progress["step"], reason)

    log.info("Summary: %d succeeded, %d failed (log: %s)",
             len(succeeded), len(failed), LOG_FILE)
    if failed:
        log.info("Failed devices: %s", ", ".join(ip for ip, _, _ in failed))
        log.info("Failure report: %s", write_failures(failed))
        sys.exit(1)


if __name__ == "__main__":
    main()
