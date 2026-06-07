"""KPortWatch — Desktop notification manager.

Sends desktop notifications (notify-send) with rate limiting and
deduplication.  Fully self-contained: owns its own ``_notified_alerts``
and ``_notification_timestamps`` state.

Only external dependency is the config object injected at construction.

**Important:** This class does NOT modify the poll interval.  Interval
decisions belong exclusively to the orchestrator (``DaemonController``).
"""
from __future__ import annotations

import logging
import subprocess
import time

from shared import AlertLevel

logger = logging.getLogger(__name__)


class NotificationManager:
    """Dispatch desktop notifications with rate-limiting and dedup."""

    def __init__(self, cfg) -> None:
        self._cfg = cfg
        self._notified_alerts: dict[str, float] = {}
        self._notification_timestamps: list[float] = []

    def reconfigure(self, cfg) -> None:
        """Apply a new config (e.g. after SIGHUP)."""
        self._cfg = cfg

    # ── Public API ────────────────────────────────────────────

    def handle(self, alerts: list) -> None:
        """Process alerts, send desktop notifications where appropriate.

        Rate limiting and dedup are applied per the daemon config.
        Expired notification hashes are evicted at the end of each cycle
        to prevent unbounded growth.
        """
        if not alerts:
            return

        for a in alerts:
            logger.info("ALERT [%s] %s", a.level, a.message)

            if not self._cfg.notifications_enabled:
                continue
            if a.level not in (AlertLevel.WARNING, AlertLevel.CRITICAL):
                continue

            alert_hash = f"{a.level}:{a.message}"
            last_notified = self._notified_alerts.get(alert_hash, 0)
            if (time.time() - last_notified) <= self._cfg.alert_ttl:
                continue

            # Rate limiting
            now_ts = time.time()
            self._notification_timestamps[:] = [
                t
                for t in self._notification_timestamps
                if (now_ts - t) < self._cfg.notification_rate_window
            ]
            if len(self._notification_timestamps) >= self._cfg.notification_rate_limit:
                logger.debug(
                    "Notification rate limited — skipping %s alert", a.level
                )
                continue

            self._send_notification(a)
            self._notified_alerts[alert_hash] = time.time()
            self._notification_timestamps.append(time.time())

        # Evict expired alert hashes (every cycle to prevent unbounded growth)
        now_ts = time.time()
        expired = [
            k
            for k, v in self._notified_alerts.items()
            if (now_ts - v) > self._cfg.alert_ttl
        ]
        for k in expired:
            del self._notified_alerts[k]

    # ── Private helpers ───────────────────────────────────────

    def _send_notification(self, alert) -> None:
        """Send a single desktop notification via notify-send."""
        try:
            icon = (
                "dialog-error"
                if alert.level == AlertLevel.CRITICAL
                else "dialog-warning"
            )
            # Sanitize alert message: truncate and strip control characters
            safe_msg = "".join(
                c for c in alert.message[:200] if c.isprintable() or c in "\n\t"
            )
            subprocess.Popen(
                [
                    "notify-send",
                    "-a",
                    "KPortWatch",
                    "-u",
                    "critical" if alert.level == AlertLevel.CRITICAL else "normal",
                    "-i",
                    icon,
                    f"KPortWatch: {alert.level}",
                    safe_msg,
                ],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )
        except FileNotFoundError:
            logger.debug("notify-send not found — skipping notification")
        except OSError as e:
            logger.warning("Failed to send notification: %s", e)
