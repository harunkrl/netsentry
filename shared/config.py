"""KPortWatch — Configuration loader.

Loads settings from a TOML config file, falling back to defaults
from ``shared.constants``.  CLI arguments take highest priority.

Priority (low → high):
  1. Hardcoded defaults in shared/constants.py
  2. ~/.config/kportwatch/config.toml (user config)
  3. CLI arguments

Usage::

    from shared.config import load_config, get_config

    load_config()                  # call once at startup
    cfg = get_config()             # access anywhere
    interval = cfg.poll_interval   # merged value
"""
from __future__ import annotations

import logging
import os
import tomllib  # Python 3.11+
from dataclasses import dataclass, field
from fnmatch import fnmatch
from pathlib import Path
from typing import Dict, FrozenSet, List, Optional

from shared.constants import (
    ALERT_POLL_INTERVAL,
    BASELINE_DIR,
    BASELINE_FILE,
    DATA_FILE,
    DEFAULT_POLL_INTERVAL,
    GEOIP_CACHE_FILE,
    IDLE_POLL_INTERVAL,
    IDLE_THRESHOLD_SECS,
    KNOWN_SAFE_PORTS,
    MALICIOUS_PORTS,
    PID_FILE,
    PRIVILEGED_PORT_MAX,
    SOCKET_PATH,
)

logger = logging.getLogger("kportwatch.config")

# ── Default config file location ──────────────────────────────────
CONFIG_DIR: str = os.path.expanduser("~/.config/kportwatch")
CONFIG_FILE: str = os.path.join(CONFIG_DIR, "config.toml")

# ── Config dataclass ──────────────────────────────────────────────

@dataclass
class CustomRule:
    """A user-defined alert rule from config.toml."""
    # Match conditions (all must be True — AND logic)
    port: Optional[int] = None              # exact port match
    port_pattern: Optional[str] = None      # glob pattern e.g. "808*"
    remote_ip: Optional[str] = None         # glob pattern e.g. "192.168.1.*"
    process_name: Optional[str] = None      # glob pattern e.g. "python*"
    proto: Optional[str] = None             # "tcp" or "udp"
    # Alert properties
    level: str = "WARNING"
    message: str = "Custom rule triggered"

    def matches(self, entry) -> bool:
        """Check if a SocketEntry matches all conditions."""
        from backend.models import SocketEntry
        if not isinstance(entry, SocketEntry):
            return False
        if self.port is not None and entry.local_port != self.port:
            return False
        if self.port_pattern is not None and not fnmatch(str(entry.local_port), self.port_pattern):
            return False
        if self.remote_ip is not None:
            ip = entry.remote_ip or ""
            if not fnmatch(ip, self.remote_ip):
                return False
        if self.process_name is not None:
            name = entry.process_name or ""
            if not fnmatch(name, self.process_name):
                return False
        if self.proto is not None and entry.proto != self.proto:
            return False
        return True


@dataclass
class AppConfig:
    """Merged application configuration."""
    # Polling
    poll_interval: float = DEFAULT_POLL_INTERVAL
    alert_poll_interval: float = ALERT_POLL_INTERVAL
    idle_poll_interval: float = IDLE_POLL_INTERVAL
    idle_threshold_secs: float = IDLE_THRESHOLD_SECS

    # Paths
    data_file: str = DATA_FILE
    socket_path: str = SOCKET_PATH
    baseline_file: str = BASELINE_FILE
    pid_file: str = PID_FILE

    # Alert engine
    baseline_duration: float = 300.0
    burst_threshold: int = 3
    malicious_ports: FrozenSet[int] = field(default_factory=lambda: MALICIOUS_PORTS)
    known_safe_ports: Dict[int, str] = field(default_factory=lambda: dict(KNOWN_SAFE_PORTS))
    privileged_port_max: int = PRIVILEGED_PORT_MAX

    # Custom rules
    custom_rules: List[CustomRule] = field(default_factory=list)

    # Whitelist / Blacklist
    port_whitelist: FrozenSet[int] = field(default_factory=frozenset)   # never alert on these
    port_blacklist: FrozenSet[int] = field(default_factory=frozenset)   # always CRITICAL on these
    ip_blacklist: List[str] = field(default_factory=list)               # glob patterns for IPs

    # DNS / rDNS
    dns_cache_size: int = 1024
    dns_max_pending: int = 256

    # Notifications
    notifications_enabled: bool = True
    notification_min_level: str = "WARNING"  # INFO, WARNING, CRITICAL
    alert_ttl: float = 3600.0  # re-notify after this many seconds
    notification_rate_limit: int = 10        # max notifications per window
    notification_rate_window: float = 60.0   # seconds for rate window

    # Daemon health
    heartbeat_file: str = ""  # empty = auto-derive from data_file

    # Auto-update
    update_enabled: bool = True
    update_check_interval: float = 86400.0  # 24 hours
    update_auto_apply: bool = False          # just notify, don't auto-apply

    # GeoIP
    geoip_enabled: bool = True
    geoip_api_url: str = "http://ip-api.com/json/"
    geoip_cache_file: str = GEOIP_CACHE_FILE
    geoip_cache_max_entries: int = 4096
    geoip_cache_ttl_days: int = 7
    geoip_batch_size: int = 10
    geoip_timeout: float = 5.0

    # TUI preferences
    tui_notifications_enabled: bool = True

    # History
    history_retention_days: int = 30  # prune files older than this

    # Source tracking
    config_path: Optional[str] = None  # None = defaults only

    @property
    def effective_heartbeat_file(self) -> str:
        if self.heartbeat_file:
            return self.heartbeat_file
        # Default: same dir as data_file, different name
        import os
        return os.path.join(os.path.dirname(self.data_file), "kportwatch-heartbeat.json")


# ── Singleton ─────────────────────────────────────────────────────

_current_config: Optional[AppConfig] = None


def get_config() -> AppConfig:
    """Return the current configuration.  Must call ``load_config()`` first."""
    if _current_config is None:
        return AppConfig()
    return _current_config


# ── TOML loader ───────────────────────────────────────────────────

def _read_toml(path: str) -> dict:
    """Read a TOML file, returning an empty dict on any error."""
    try:
        with open(path, "rb") as fh:
            return tomllib.load(fh)
    except FileNotFoundError:
        logger.debug("Config file not found: %s — using defaults", path)
    except Exception as e:
        logger.warning("Failed to read config file %s: %s", path, e)
    return {}


def _parse_port_list(raw) -> Optional[FrozenSet[int]]:
    """Parse a TOML port list into a frozenset of validated port ints."""
    if raw is None:
        return None
    if not isinstance(raw, (list, tuple)):
        return None
    ports = set()
    for p in raw:
        if isinstance(p, int) and 0 <= p <= 65535:
            ports.add(p)
    return frozenset(ports)


def _parse_safe_ports(raw) -> Optional[Dict[int, str]]:
    """Parse a TOML safe-ports table into {port: service_name}."""
    if raw is None:
        return None
    if not isinstance(raw, dict):
        return None
    result: Dict[int, str] = {}
    for key, val in raw.items():
        try:
            port = int(key)
            if 0 <= port <= 65535:
                result[port] = str(val)
        except (ValueError, TypeError):
            continue
    return result if result else None


def load_config(path: Optional[str] = None) -> AppConfig:
    """Load configuration from TOML file, merging over defaults.

    Args:
        path: Explicit config file path.  Defaults to
              ``~/.config/kportwatch/config.toml``.

    Returns:
        The merged AppConfig instance (also stored as singleton).
    """
    global _current_config

    cfg_path = path or CONFIG_FILE
    data = _read_toml(cfg_path)

    # Start from defaults
    cfg = AppConfig()

    if data:
        cfg.config_path = cfg_path
        logger.info("Loaded config from %s", cfg_path)

        # ── Polling ────────────────────────────
        polling = data.get("polling", {})
        if "interval" in polling:
            v = polling["interval"]
            if isinstance(v, (int, float)) and v > 0:
                cfg.poll_interval = float(v)
        if "alert_interval" in polling:
            v = polling["alert_interval"]
            if isinstance(v, (int, float)) and v > 0:
                cfg.alert_poll_interval = float(v)
        if "idle_interval" in polling:
            v = polling["idle_interval"]
            if isinstance(v, (int, float)) and v > 0:
                cfg.idle_poll_interval = float(v)
        if "idle_threshold_secs" in polling:
            v = polling["idle_threshold_secs"]
            if isinstance(v, (int, float)) and v > 0:
                cfg.idle_threshold_secs = float(v)

        # ── Alert engine ────────────────────────
        alerts = data.get("alerts", {})
        if "baseline_duration" in alerts:
            v = alerts["baseline_duration"]
            if isinstance(v, (int, float)) and v > 0:
                cfg.baseline_duration = float(v)
        if "burst_threshold" in alerts:
            v = alerts["burst_threshold"]
            if isinstance(v, int) and v > 0:
                cfg.burst_threshold = v
        if "malicious_ports" in alerts:
            parsed = _parse_port_list(alerts["malicious_ports"])
            if parsed is not None:
                cfg.malicious_ports = parsed
        if "known_safe_ports" in alerts:
            parsed = _parse_safe_ports(alerts["known_safe_ports"])
            if parsed is not None:
                cfg.known_safe_ports = parsed
        if "privileged_port_max" in alerts:
            v = alerts["privileged_port_max"]
            if isinstance(v, int) and 0 <= v <= 65535:
                cfg.privileged_port_max = v

        # ── DNS ─────────────────────────────────
        dns = data.get("dns", {})
        if "cache_size" in dns:
            v = dns["cache_size"]
            if isinstance(v, int) and v > 0:
                cfg.dns_cache_size = v
        if "max_pending" in dns:
            v = dns["max_pending"]
            if isinstance(v, int) and v > 0:
                cfg.dns_max_pending = v

        # ── Notifications ───────────────────────
        notif = data.get("notifications", {})
        if "enabled" in notif:
            v = notif["enabled"]
            if isinstance(v, bool):
                cfg.notifications_enabled = v
        if "min_level" in notif:
            v = notif["min_level"]
            if isinstance(v, str) and v.upper() in ("INFO", "WARNING", "CRITICAL"):
                cfg.notification_min_level = v.upper()
        if "alert_ttl" in notif:
            v = notif["alert_ttl"]
            if isinstance(v, (int, float)) and v > 0:
                cfg.alert_ttl = float(v)
        if "rate_limit" in notif:
            v = notif["rate_limit"]
            if isinstance(v, int) and v > 0:
                cfg.notification_rate_limit = v
        if "rate_window" in notif:
            v = notif["rate_window"]
            if isinstance(v, (int, float)) and v > 0:
                cfg.notification_rate_window = float(v)

        # ── Custom rules ────────────────────────
        custom_rules_raw = data.get("custom_rules", [])
        if isinstance(custom_rules_raw, list):
            for raw_rule in custom_rules_raw:
                if not isinstance(raw_rule, dict):
                    continue
                match = raw_rule.get("match", {})
                level = raw_rule.get("level", "WARNING")
                if isinstance(level, str) and level.upper() in ("INFO", "WARNING", "CRITICAL"):
                    level = level.upper()
                else:
                    level = "WARNING"
                rule = CustomRule(
                    port=match.get("port") if isinstance(match.get("port"), int) else None,
                    port_pattern=match.get("port_pattern") if isinstance(match.get("port_pattern"), str) else None,
                    remote_ip=match.get("remote_ip") if isinstance(match.get("remote_ip"), str) else None,
                    process_name=match.get("process_name") if isinstance(match.get("process_name"), str) else None,
                    proto=match.get("proto") if isinstance(match.get("proto"), str) else None,
                    level=level,
                    message=raw_rule.get("message", "Custom rule triggered"),
                )
                cfg.custom_rules.append(rule)

        # ── Whitelist / Blacklist ────────────────
        wl = data.get("whitelist", {})
        if "ports" in wl:
            parsed = _parse_port_list(wl["ports"])
            if parsed is not None:
                cfg.port_whitelist = parsed

        bl = data.get("blacklist", {})
        if "ports" in bl:
            parsed = _parse_port_list(bl["ports"])
            if parsed is not None:
                cfg.port_blacklist = parsed
        if "ips" in bl:
            ips = bl["ips"]
            if isinstance(ips, list):
                cfg.ip_blacklist = [str(ip) for ip in ips if isinstance(ip, str)]

        # ── Paths ───────────────────────────────
        paths = data.get("paths", {})
        if "data_file" in paths:
            cfg.data_file = str(paths["data_file"])
        if "socket_path" in paths:
            cfg.socket_path = str(paths["socket_path"])
        if "baseline_file" in paths:
            cfg.baseline_file = str(paths["baseline_file"])

        # ── Auto-update ───────────────────────────
        update = data.get("update", {})
        if "enabled" in update:
            v = update["enabled"]
            if isinstance(v, bool):
                cfg.update_enabled = v
        if "check_interval" in update:
            v = update["check_interval"]
            if isinstance(v, (int, float)) and v > 0:
                cfg.update_check_interval = float(v)
        if "auto_apply" in update:
            v = update["auto_apply"]
            if isinstance(v, bool):
                cfg.update_auto_apply = v

        # ── GeoIP ──────────────────────────────
        geoip = data.get("geoip", {})
        if "enabled" in geoip:
            v = geoip["enabled"]
            if isinstance(v, bool):
                cfg.geoip_enabled = v
        if "api_url" in geoip:
            v = geoip["api_url"]
            if isinstance(v, str) and v:
                cfg.geoip_api_url = v
        if "cache_file" in geoip:
            cfg.geoip_cache_file = str(geoip["cache_file"])
        if "cache_max_entries" in geoip:
            v = geoip["cache_max_entries"]
            if isinstance(v, int) and v > 0:
                cfg.geoip_cache_max_entries = v
        if "cache_ttl_days" in geoip:
            v = geoip["cache_ttl_days"]
            if isinstance(v, int) and v > 0:
                cfg.geoip_cache_ttl_days = v
        if "batch_size" in geoip:
            v = geoip["batch_size"]
            if isinstance(v, int) and v > 0:
                cfg.geoip_batch_size = v
        if "timeout" in geoip:
            v = geoip["timeout"]
            if isinstance(v, (int, float)) and v > 0:
                cfg.geoip_timeout = float(v)

        # ── TUI preferences ─────────────────────
        tui = data.get("tui", {})
        if "notifications_enabled" in tui:
            v = tui["notifications_enabled"]
            if isinstance(v, bool):
                cfg.tui_notifications_enabled = v

        # ── History ────────────────────────────────
        hist = data.get("history", {})
        if "retention_days" in hist:
            v = hist["retention_days"]
            if isinstance(v, (int, float)) and int(v) >= 1:
                cfg.history_retention_days = int(v)

    _current_config = cfg
    return cfg


def apply_cli_overrides(cfg: AppConfig, args) -> AppConfig:
    """Apply CLI argument overrides on top of the loaded config."""
    if hasattr(args, "interval") and args.interval is not None:
        # argparse already set it from --interval, but we need to ensure
        # it overrides the config file value
        cfg.poll_interval = args.interval
    return cfg


def generate_example_config(path: str) -> None:
    """Write an example config file with all options and comments."""
    example = """\
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
# ip-api.com endpoint (free tier: 45 req/min)
# api_url = "http://ip-api.com/json/"
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
"""
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, "w") as fh:
        fh.write(example)
    logger.info("Generated example config at %s", path)


def save_config_setting(section: str, key: str, value: object) -> None:
    """Persist a single setting to the config file under the given section.

    Reads the existing config, updates the named section, and writes back.
    Creates the file/section if they don't exist.
    """
    path = CONFIG_FILE
    raw = ""
    if os.path.isfile(path):
        try:
            with open(path, "r") as fh:
                raw = fh.read()
        except OSError:
            return

    section_tag = f"[{section}]"
    line = f"{key} = {'true' if value is True else 'false' if value is False else repr(value)}\n"

    if section_tag in raw:
        import re
        # Find the boundaries of the target section
        section_start = raw.index(section_tag) + len(section_tag)
        next_section = re.search(r"\n(?=\[)", raw[section_start:])
        section_end = section_start + next_section.start() if next_section else len(raw)
        section_block = raw[section_start:section_end]

        pattern = rf"({re.escape(key)}\s*=\s*[^\n]+)"
        if re.search(pattern, section_block):
            new_section_block = re.sub(
                pattern,
                f"{key} = {'true' if value is True else 'false' if value is False else repr(value)}",
                section_block,
                count=1,
            )
            raw = raw[:section_start] + new_section_block + raw[section_end:]
        else:
            raw = raw.replace(section_tag, f"{section_tag}\n{line}", 1)
    else:
        raw = raw.rstrip() + "\n\n" + section_tag + "\n" + line

    try:
        os.makedirs(os.path.dirname(path), exist_ok=True)
        with open(path, "w") as fh:
            fh.write(raw)
    except OSError:
        logger.debug("Failed to save config setting to %s", path, exc_info=True)


def save_tui_setting(key: str, value: object) -> None:
    """Shorthand for ``save_config_setting('tui', key, value)``."""
    save_config_setting("tui", key, value)
