"""KPortWatch — Shared package.

Re-exports all constants from :pymod:`shared.constants` so that
``from shared import DATA_FILE`` works transparently.
"""
from shared.constants import *  # noqa: F401,F403
from shared.constants import (  # explicit re-exports for type-checkers
    AlertLevel,
    APP_NAME,
    APP_VERSION,
    BASELINE_DIR,
    BASELINE_FILE,
    DATA_FILE,
    GITHUB_REPO,
    KNOWN_SAFE_PORTS,
    MALICIOUS_PORTS,
    PID_FILE,
    PRIVILEGED_PORT_MAX,
    PROC_PATHS,
    PROC_TCP,
    PROC_TCP6,
    PROC_UDP,
    PROC_UDP6,
    PROC_NET_DEV,
    SOCKET_PATH,
    TCP_STATES,
    ALERT_POLL_INTERVAL,
    DEFAULT_POLL_INTERVAL,
    IDLE_POLL_INTERVAL,
    IDLE_THRESHOLD_SECS,
    UPDATE_STATE_FILE,
    GEOIP_CACHE_DIR,
    GEOIP_CACHE_FILE,
)
