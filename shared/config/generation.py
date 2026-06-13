"""KPortWatch — Example config generation."""

from __future__ import annotations

import logging
import os

logger = logging.getLogger("kportwatch.config")

_EXAMPLE_CONFIG = """\
# KPortWatch Configuration
# Place at ~/.config/kportwatch/config.toml
# All values are optional — defaults are used when omitted.

[polling]
# Normal polling interval in seconds
interval = 2.0
# Faster polling when alerts are active
alert_interval = 1.0
# Slower polling when idle (no changes)
idle_interval = 10.0
# Seconds of no changes before switching to idle
idle_threshold_secs = 300.0

[alerts]
# Seconds to learn baseline ports on first run
baseline_duration = 300.0
# Number of new ports in one cycle to trigger burst alert
burst_threshold = 3
# Privileged port boundary (< this value)
privileged_port_max = 1023
# Known malicious C2/backdoor ports
malicious_ports = [4444, 5555, 31337, 12345, 12346, 6666, 6667, 6668, 6669, 27374, 33270, 33567, 65000]
# Ports considered safe — {port: "service_name"}
[alerts.known_safe_ports]
22 = "sshd"
80 = "httpd"
443 = "https"
631 = "cups"
5353 = "avahi"
1716 = "kdeconnectd"

# ── Security ───────────────────────────────────────────
# [security]
# Number of connection events in the scan window that triggers a
# "port scan detected" alert.
# scan_threshold = 5

# ── Custom alert rules ──────────────────────────────────────────
# Each rule has a "match" table and alert properties.
# All match conditions use AND logic (all must be true).
# Supported match fields: port (int), port_pattern (glob),
#   remote_ip (glob), process_name (glob), proto ("tcp"/"udp")
#
# [[custom_rules]]
# match = { port = 8080 }
# level = "WARNING"
# message = "Unauthorized dev server on port 8080"
#
# [[custom_rules]]
# match = { remote_ip = "192.168.1.*" }
# level = "CRITICAL"
# message = "Suspicious internal connection detected"
#
# [[custom_rules]]
# match = { process_name = "ncat*" }
# level = "CRITICAL"
# message = "Ncat process detected — possible reverse shell"

# ── Whitelist (never alert on these) ─────────────────────────────
# [whitelist]
# ports = [8080, 9090]

# ── Blacklist (always CRITICAL) ──────────────────────────────────
# [blacklist]
# ports = [4444, 5555]
# ips = ["10.0.0.*", "192.168.100.*"]

[dns]
# Maximum cached hostname entries
cache_size = 1024
# Maximum concurrent pending DNS lookups
max_pending = 256

[notifications]
# Enable desktop notifications via notify-send
enabled = true
# Minimum alert level to trigger notification: "INFO", "WARNING", "CRITICAL"
min_level = "WARNING"
# Seconds before the same alert can re-notify
alert_ttl = 3600.0
# Max notifications per rate_window seconds (rate limiting)
rate_limit = 10
rate_window = 60.0

[paths]
# JSON snapshot file (read by widget and TUI)
# data_file = "/run/user/1000/kportwatch-data.json"
# Unix domain socket (for streaming client)
# socket_path = "/run/user/1000/kportwatch.sock"
# Baseline file (learned ports)
# baseline_file = "~/.config/kportwatch/baseline.json"

[geoip]
# Enable GeoIP lookup for outbound connections
enabled = true
# ipwho.is endpoint (HTTPS, free, no key required)
# api_url = "https://ipwho.is/"
# Persistent cache file for offline lookups
# cache_file = "~/.local/share/kportwatch/geoip-cache.json"
# Maximum cached IP entries (LRU eviction)
cache_max_entries = 4096
# Days before cached entry is considered stale
cache_ttl_days = 7
# Max IPs to look up per daemon cycle
batch_size = 10
# HTTP request timeout in seconds
timeout = 5.0

[tui]
# TUI toast notifications (the pop-up messages in the terminal)
# Toggle at runtime with the 'n' key — saved persistently here.
notifications_enabled = true
# Color theme key: cyberpunk, kpw-light, nord (cycled with 'T' key)
color_theme = "cyberpunk"
"""


def generate_example_config(path: str) -> None:
    """Write an example config file with all options and comments."""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(_EXAMPLE_CONFIG)
    logger.info("Generated example config at %s", path)
