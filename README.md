# panos-bootstrap-update

Applies a small set of baseline `deviceconfig system` settings to one or more
Palo Alto firewalls over the PAN-OS XML API, commits, and logs the result per
device.

Per firewall the script will:

1. Generate an API key using a shared username and password.
2. Enable the DHCP client options: `send-hostname`, `send-client-id`,
   `accept-dhcp-domain`, `accept-dhcp-hostname`.
3. Set `ipv6-enable` to `no`.
4. Commit, then poll the commit job until it finishes.
5. Log the outcome and move on to the next device in the inventory.

A failure on one device is logged and does not stop the run. Failed devices are
written to a CSV report with the step that failed and the reason.

## Prerequisites

- Python 3.8 or newer
- The `requests` library: `pip install requests`
- HTTPS (TCP/443) reachability from the host running the script to each
  firewall's management interface
- An admin account that exists on **every** firewall in the list, with the same
  password, and with XML API access permitted
- The management interface must allow HTTPS in its interface management profile

## Inventory

Devices are read from a text file, one management IP per line. Blank lines and
anything after `#` are ignored, and duplicate entries are skipped.
`device_inventory.txt` is an example of the format:

```
# One firewall management IP per line. Lines starting with # are ignored.
10.10.10.1
10.10.20.1
```

By default the script reads `devices.txt` from the current directory. Either
copy the example to `devices.txt` and add your devices, or pass any inventory
file as the first argument to run a specific batch (see [Running](#running)).

`devices.txt` and failure reports are excluded from git so device IPs are not
committed. Do not commit real IPs to `device_inventory.txt`.

## Configuration

Credentials and tuning are set at the top of `panos_bootstrap_update.py`.

| Setting | Purpose |
| --- | --- |
| `DEFAULT_INVENTORY` | Inventory file used when no argument is given |
| `USERNAME` / `PASSWORD` | Shared admin credentials — both default to `CHANGE_ME` |
| `VERIFY_TLS` | `False` by default, for firewalls using self-signed certificates |
| `TIMEOUT` | Per-request timeout in seconds |
| `COMMIT_POLL` | Seconds between commit job status checks |
| `COMMIT_TIMEOUT` | Abandon a commit job after this many seconds |
| `LOG_FILE` | Log file name, relative to the current directory, or a full path |

Example:

```python
USERNAME = "yourusername"
PASSWORD = "yourpassword"
```

The script exits immediately if the credentials are still set to `CHANGE_ME`.

## Running

```bash
pip install requests
python3 panos_bootstrap_update.py                          # uses devices.txt
python3 panos_bootstrap_update.py device_inventory.txt     # uses a specific inventory file
```

Exit code is `0` if every device succeeded, `1` if any failed.

## Output

Progress, including commit job status updates, is written to the terminal and
appended to `panos_bootstrap_update.log` in the directory the script is run
from. The log is appended to on every run, so earlier runs are kept. Each line
is timestamped and prefixed with the firewall IP:

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

A failed device is logged with the step it failed at and the reason:

```
2026-01-14 09:12:16,002 ERROR   10.10.20.1: FAILED at step 'login' - API error (HTTP 403): Invalid Credential
```

The run ends with a summary of success and failure counts and the IPs of any
failed devices.

### Failure report

If any device fails, a CSV named `failed_devices_<YYYYMMDD_HHMMSS>.csv` is
written to the current directory:

```
ip,step,reason
10.10.20.1,login,API error (HTTP 403): Invalid Credential
10.10.30.1,login,connection error: ... timed out
10.10.40.1,set dhcp-client,API error (HTTP 200): <message from firewall>
10.10.50.1,commit,commit job 7 finished with result FAIL: <validation details>
```

Steps are `login`, `set dhcp-client`, `disable ipv6` and `commit`. The reason
is the connection error or the error message returned by the firewall.

To retry after fixing the issues, pass the report straight back in as the
inventory:

```bash
python3 panos_bootstrap_update.py failed_devices_20260114_091216.csv
```

Re-running against a device that already succeeded is safe; it applies the
same values again.

## Notes

- Devices are processed one at a time, so a large batch takes roughly the sum of
  each device's commit time. Size batches to fit the change window.
- Requests are sent as HTTP POST, so the password and API key do not appear in
  the firewall's URI logs.
- Each device gets a single login attempt per run, so the script will not lock
  out the account through repeated retries.
- The commit is a full commit of all pending changes on the device. If someone
  has uncommitted work in the candidate config, it will be committed too. Check
  before running against production.
- Certificate verification is disabled by default. Set `VERIFY_TLS = True` where
  the firewalls present a trusted certificate.
- Credentials are stored in plain text in the script. Do not commit real
  credentials, and consider switching to `getpass.getpass()` or environment
  variables for shared use.
