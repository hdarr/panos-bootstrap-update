# panos-bootstrap

Applies a small set of baseline `deviceconfig system` settings to one or more
Palo Alto firewalls over the PAN-OS XML API, commits, and logs the result per
device.

Per firewall the script will:

1. Generate an API key using a shared username and password.
2. Enable the DHCP client options: `send-hostname`, `send-client-id`,
   `accept-dhcp-domain`, `accept-dhcp-hostname`.
3. Set `ipv6-enable` to `no`.
4. Commit, then poll the commit job until it finishes.
5. Log the outcome and move on to the next IP in the list.

A failure on one device is logged and does not stop the run.

## Prerequisites

- Python 3.8 or newer
- The `requests` library: `pip install requests`
- HTTPS (TCP/443) reachability from the host running the script to each
  firewall's management interface
- An admin account that exists on **every** firewall in the list, with the same
  password, and with XML API access permitted
- The management interface must allow HTTPS in its interface management profile

## Configuration

Everything is set at the top of `panos_bootstrap.py`.

| Setting | Purpose |
| --- | --- |
| `FIREWALL_IPS` | List of management IPs to configure |
| `USERNAME` / `PASSWORD` | Shared admin credentials — both default to `CHANGE_ME` |
| `VERIFY_TLS` | `False` by default, for firewalls using self-signed certificates |
| `TIMEOUT` | Per-request timeout in seconds |
| `COMMIT_POLL` | Seconds between commit job status checks |
| `COMMIT_TIMEOUT` | Abandon a commit job after this many seconds |
| `LOG_FILE` | Log file name |

Example:

```python
FIREWALL_IPS = [
    "10.10.10.1",
    "10.10.20.1",
]

USERNAME = "yourusername"
PASSWORD = "yourpassword"
```

The script exits immediately if the credentials are still set to `CHANGE_ME`.

## Running

```bash
pip install requests
python3 panos_bootstrap.py
```

Exit code is `0` if every device succeeded, `1` if any failed.

## Output

Progress is written to the terminal and appended to `panos_bootstrap.log` in
the directory the script is run from. Each line is timestamped and prefixed
with the firewall IP:

```
2026-01-14 09:12:03,114 INFO    === 10.10.10.1 ===
2026-01-14 09:12:03,115 INFO    10.10.10.1: requesting API key as user 'yourusername'
2026-01-14 09:12:03,842 INFO    10.10.10.1: API key retrieved
2026-01-14 09:12:04,201 INFO    10.10.10.1: setting dhcp-client options
2026-01-14 09:12:04,655 INFO    10.10.10.1: disabling IPv6
2026-01-14 09:12:04,989 INFO    10.10.10.1: committing
2026-01-14 09:12:05,430 INFO    10.10.10.1: commit job 42 queued
2026-01-14 09:12:15,688 INFO    10.10.10.1: job 42 FIN 100%
2026-01-14 09:12:15,689 INFO    10.10.10.1: commit completed OK
2026-01-14 09:12:15,690 INFO    10.10.10.1: SUCCESS
```

A summary line at the end gives the success and failure counts, followed by the
IPs of any devices that failed.

## Notes

- Requests are sent as HTTP POST, so the password and API key do not appear in
  the firewall's URI logs.
- The commit is a full commit of all pending changes on the device. If someone
  has uncommitted work in the candidate config, it will be committed too. Check
  before running against production.
- Certificate verification is disabled by default. Set `VERIFY_TLS = True` where
  the firewalls present a trusted certificate.
- Credentials are stored in plain text in the script. Do not commit real
  credentials, and consider switching to `getpass.getpass()` or environment
  variables for shared use.
