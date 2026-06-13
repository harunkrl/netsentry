"""KPortWatch — Periodic update checker.

Self-contained: owns its own ``_last_update_check`` timestamp.
Only external dependency is the config object injected at construction.
"""

from __future__ import annotations

import logging
import time

from backend.update import check_for_update, get_local_version, write_update_state

logger = logging.getLogger(__name__)


class UpdateChecker:
    """Check for new KPortWatch versions at a configurable interval."""

    def __init__(self, cfg) -> None:
        self._cfg = cfg
        self._last_update_check: float = 0.0

    def reconfigure(self, cfg) -> None:
        """Apply a new config (e.g. after SIGHUP)."""
        self._cfg = cfg

    def check(self) -> None:
        """Check for updates if the configured interval has elapsed."""
        if not self._cfg.update_enabled:
            return
        now_ts = time.time()
        if (now_ts - self._last_update_check) < self._cfg.update_check_interval:
            return
        self._last_update_check = now_ts
        try:
            new_version = check_for_update()
            write_update_state(
                current=get_local_version(),
                latest=new_version,
                update_available=new_version is not None,
            )
            if new_version:
                logger.info("Update available: %s → %s", get_local_version(), new_version)
        except Exception:
            logger.debug("Update check failed", exc_info=True)
