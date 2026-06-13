"""KPortWatch — Shared package.

Re-exports all constants from :pymod:`shared.constants` so that
``from shared import DATA_FILE`` works transparently.
"""

from shared.constants import *  # noqa: F403
from shared.constants import (  # noqa: F401 — explicit re-exports for type-checkers
    ALERT_POLL_INTERVAL,
    APP_NAME,
    APP_VERSION,
    BASELINE_DIR,
    BASELINE_FILE,
    DATA_FILE,
    DEFAULT_POLL_INTERVAL,
    GEOIP_CACHE_DIR,
    GEOIP_CACHE_FILE,
    GITHUB_REPO,
    IDLE_POLL_INTERVAL,
    IDLE_THRESHOLD_SECS,
    KNOWN_SAFE_PORTS,
    MALICIOUS_PORTS,
    PID_FILE,
    PRIVILEGED_PORT_MAX,
    PROC_NET_DEV,
    PROC_PATHS,
    PROC_TCP,
    PROC_TCP6,
    PROC_UDP,
    PROC_UDP6,
    SOCKET_PATH,
    TCP_STATES,
    UPDATE_STATE_FILE,
    WIDGET_DATA_FILE,
    AlertLevel,
)
