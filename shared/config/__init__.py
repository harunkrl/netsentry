"""KPortWatch — Configuration loader (decomposed).

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

The public API is identical to the old monolithic config.py.
All submodules are internal implementation details.
"""
from __future__ import annotations

import logging
import os
import threading as _threading
from dataclasses import dataclass, field

from shared.constants import (
    ALERT_POLL_INTERVAL,
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
from shared.config.rules import CustomRule
from shared.config.parsers import read_toml, parse_port_list, parse_safe_ports, parse_custom_rules
from shared.config.persistence import save_config_setting, save_tui_setting, CONFIG_DIR, CONFIG_FILE
from shared.config.generation import generate_example_config

logger = logging.getLogger("kportwatch.config")

__all__ = [
    "CustomRule",
    "AppConfig",
    "get_config",
    "load_config",
    "apply_cli_overrides",
    "generate_example_config",
    "save_config_setting",
    "save_tui_setting",
    "CONFIG_DIR",
    "CONFIG_FILE",
]


# ── Config dataclass ──────────────────────────────────────────────

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
    malicious_ports: frozenset[int] = field(default_factory=lambda: MALICIOUS_PORTS)
    known_safe_ports: dict[int, str] = field(default_factory=lambda: dict(KNOWN_SAFE_PORTS))
    privileged_port_max: int = PRIVILEGED_PORT_MAX

    # Custom rules
    custom_rules: list[CustomRule] = field(default_factory=list)

    # Whitelist / Blacklist
    port_whitelist: frozenset[int] = field(default_factory=frozenset)   # never alert on these
    port_blacklist: frozenset[int] = field(default_factory=frozenset)   # always CRITICAL on these
    ip_blacklist: list[str] = field(default_factory=list)               # glob patterns for IPs

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
    geoip_api_url: str = "https://ipwho.is/"
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
    config_path: str | None = None  # None = defaults only

    @property
    def effective_heartbeat_file(self) -> str:
        if self.heartbeat_file:
            return self.heartbeat_file
        return os.path.join(os.path.dirname(self.data_file), "kportwatch-heartbeat.json")


# ── Singleton (thread-safe) ────────────────────────────────────

_config_lock = _threading.Lock()
_current_config: AppConfig | None = None


def get_config() -> AppConfig:
    """Return the current configuration.  Must call ``load_config()`` first."""
    with _config_lock:
        if _current_config is None:
            return AppConfig()
        return _current_config


# ── Loader ───────────────────────────────────────────────────────────

def load_config(path: str | None = None) -> AppConfig:
    """Load configuration from TOML file, merging over defaults.

    Args:
        path: Explicit config file path.  Defaults to
              ``~/.config/kportwatch/config.toml``.

    Returns:
        The merged AppConfig instance (also stored as singleton).
    """
    global _current_config

    cfg_path = path or CONFIG_FILE
    data = read_toml(cfg_path)

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
            parsed = parse_port_list(alerts["malicious_ports"])
            if parsed is not None:
                cfg.malicious_ports = parsed
        if "known_safe_ports" in alerts:
            parsed = parse_safe_ports(alerts["known_safe_ports"])
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
        cfg.custom_rules = parse_custom_rules(data.get("custom_rules", []))

        # ── Whitelist / Blacklist ────────────────
        wl = data.get("whitelist", {})
        if "ports" in wl:
            parsed = parse_port_list(wl["ports"])
            if parsed is not None:
                cfg.port_whitelist = parsed

        bl = data.get("blacklist", {})
        if "ports" in bl:
            parsed = parse_port_list(bl["ports"])
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

    with _config_lock:
        _current_config = cfg
    return cfg


def apply_cli_overrides(cfg: AppConfig, args) -> AppConfig:
    """Apply CLI argument overrides on top of the loaded config."""
    if hasattr(args, "interval") and args.interval is not None:
        cfg.poll_interval = args.interval
    return cfg
