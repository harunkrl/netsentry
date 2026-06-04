"""NetSentry — Shared constants and configuration.

All project-wide constants live here. Import via ``shared`` package::

    from shared import DATA_FILE, AlertLevel, MALICIOUS_PORTS
"""
import os
from enum import StrEnum

# ── Paths ──────────────────────────────────────────────────────
# Use XDG_RUNTIME_DIR (typically /run/user/$UID, mode 0700) for data files.
# Falls back to /tmp only if XDG_RUNTIME_DIR is not set.
_RUNTIME_DIR: str = os.environ.get("XDG_RUNTIME_DIR", "/tmp")
DATA_FILE: str = os.path.join(_RUNTIME_DIR, "netsentry-data.json")
SOCKET_PATH: str = os.path.join(_RUNTIME_DIR, "netsentry.sock")
BASELINE_DIR: str = os.path.expanduser("~/.config/netsentry")
BASELINE_FILE: str = os.path.join(BASELINE_DIR, "baseline.json")
PID_FILE: str = os.path.join(_RUNTIME_DIR, "netsentry.pid")

# ── /proc paths ────────────────────────────────────────────────
PROC_TCP: str = "/proc/net/tcp"
PROC_TCP6: str = "/proc/net/tcp6"
PROC_UDP: str = "/proc/net/udp"
PROC_UDP6: str = "/proc/net/udp6"
PROC_PATHS: list[str] = [PROC_TCP, PROC_TCP6, PROC_UDP, PROC_UDP6]
PROC_NET_DEV: str = "/proc/net/dev"

# ── Polling intervals (seconds) ───────────────────────────────
DEFAULT_POLL_INTERVAL: float = 2.0
ALERT_POLL_INTERVAL: float = 1.0
IDLE_POLL_INTERVAL: float = 10.0
IDLE_THRESHOLD_SECS: float = 300.0  # 5 min no changes → idle

# ── Alert levels ───────────────────────────────────────────────
class AlertLevel(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

# ── Known malicious ports (common malware C2 / backdoor ports) ─
MALICIOUS_PORTS: frozenset[int] = frozenset({
    4444,   # Metasploit default
    5555,   # Common backdoor
    31337,  # Back Orifice
    12345,  # NetBus
    12346,  # NetBus
    6666,   # IRC botnet
    6667,   # IRC botnet
    6668,   # IRC botnet
    6669,   # IRC botnet
    27374,  # SubSeven
    33270,  # Trinity
    33567,  # Backdoor
    65000,  # DevPoint
})

# ── Privileged port range ──────────────────────────────────────
PRIVILEGED_PORT_MAX: int = 1023

# ── Default known-safe ports {port: service_name} ─────────────
KNOWN_SAFE_PORTS: dict[int, str] = {
    22:    "sshd",
    80:    "httpd",
    443:   "https",
    631:   "cups",
    5353:  "avahi",
    1716:  "kdeconnectd",
    4500:  "kdeconnect",
    17600: "kdeconnect",
    17601: "kdeconnect",
}

# ── TCP state codes from /proc/net/tcp ─────────────────────────
TCP_STATES: dict[str, str] = {
    "01": "ESTABLISHED",
    "02": "SYN_SENT",
    "03": "SYN_RECV",
    "04": "FIN_WAIT1",
    "05": "FIN_WAIT2",
    "06": "TIME_WAIT",
    "07": "CLOSE",
    "08": "CLOSE_WAIT",
    "09": "LAST_ACK",
    "0A": "LISTEN",
    "0B": "CLOSING",
    "0C": "NEW_SYN_RECV",  # SYN cookie reply (kernel ≥ 4.4)
}

# ── App metadata ───────────────────────────────────────────────
APP_NAME: str = "NetSentry"
APP_VERSION: str = "2.0.0"

# ── Update paths ──────────────────────────────────────────────
UPDATE_STATE_FILE: str = os.path.join(_RUNTIME_DIR, "netsentry-update.json")
GITHUB_REPO: str = "harunkrl/netsentry"
