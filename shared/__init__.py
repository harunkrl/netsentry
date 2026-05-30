"""NetSentry — Shared constants and configuration."""
import os
from enum import StrEnum

# ── Paths ──────────────────────────────────────────────────────
DATA_FILE = "/tmp/netsentry-data.json"
SOCKET_PATH = f"/run/user/{os.getuid()}/netsentry.sock"
BASELINE_DIR = os.path.expanduser("~/.config/netsentry")
BASELINE_FILE = os.path.join(BASELINE_DIR, "baseline.json")

# ── /proc paths ────────────────────────────────────────────────
PROC_TCP = "/proc/net/tcp"
PROC_TCP6 = "/proc/net/tcp6"
PROC_UDP = "/proc/net/udp"
PROC_UDP6 = "/proc/net/udp6"
PROC_PATHS = [PROC_TCP, PROC_TCP6, PROC_UDP, PROC_UDP6]

# ── Polling intervals (seconds) ───────────────────────────────
DEFAULT_POLL_INTERVAL = 2.0
ALERT_POLL_INTERVAL = 1.0
IDLE_POLL_INTERVAL = 10.0
IDLE_THRESHOLD_SECS = 300.0  # 5 min no changes → idle

# ── Alert levels ───────────────────────────────────────────────
class AlertLevel(StrEnum):
    INFO = "INFO"
    WARNING = "WARNING"
    CRITICAL = "CRITICAL"

# ── Known malicious ports (common malware C2 / backdoor ports) ─
MALICIOUS_PORTS = frozenset({
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
PRIVILEGED_PORT_MAX = 1023

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
APP_NAME = "NetSentry"
APP_VERSION = "1.0.0"
