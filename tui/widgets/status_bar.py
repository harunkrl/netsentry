"""KPortWatch TUI — Status bar widget (bottom bar).

Compact one-line status bar with daemon health, alert summary,
connection counts, and keyboard hints.

Responsive: adapts content to terminal width.  Shortcuts are
rendered without Rich bracket markup to avoid parsing confusion.
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional

from textual.widgets import Static

from shared.constants import DATA_FILE

# Heartbeat cache TTL (seconds)
_HB_CACHE_TTL = 8.0


def _check_daemon_alive() -> bool:
    """Check if daemon is alive by reading the heartbeat file."""
    hb_path = os.path.join(os.path.dirname(DATA_FILE), "kportwatch-heartbeat.json")
    try:
        with open(hb_path, "r") as fh:
            data = json.load(fh)
        ts = data.get("ts", 0)
        return (time.time() - ts) < 15.0
    except (FileNotFoundError, json.JSONDecodeError, OSError, KeyError):
        return False


class StatusBar(Static):
    """Bottom status bar — responsive, adapts to terminal width.

    Width tiers:
      - < 60 chars: daemon + counts only
      - 60-100: + shortcuts (compact)
      - > 100: full info
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._desktop_notifications: bool = True
        self._last_hb_check: float = 0.0
        self._last_hb_result: bool = False
        self._filter_info: str = ""
        # Cache last update args for responsive re-render
        self._last_summary: Dict[str, int] = {}
        self._last_alerts: List = []
        self._last_daemon_alive: Optional[bool] = None
        self._last_screen: str = ""

    def on_mount(self) -> None:
        self.update("... Waiting for data ...")

    def show_daemon_down(self) -> None:
        self.update(
            "\u2717 DAEMON OFFLINE  |  "
            "Start: kportwatch-daemon --foreground"
        )

    def rerender(self) -> None:
        """Re-render with cached data (called on terminal resize)."""
        if self._last_summary:
            try:
                self._build_line(
                    self._last_summary or {},
                    self._last_alerts or [],
                    self._last_daemon_alive,
                    self._last_screen or "",
                )
            except Exception:
                pass

    def set_notification_state(self, enabled: bool) -> None:
        """Update the desktop notification indicator."""
        self._desktop_notifications = enabled

    def set_filter_info(self, info: str) -> None:
        self._filter_info = info

    def _cached_daemon_check(self) -> bool:
        now = time.time()
        if (now - self._last_hb_check) < _HB_CACHE_TTL:
            return self._last_hb_result
        self._last_hb_check = now
        self._last_hb_result = _check_daemon_alive()
        return self._last_hb_result

    def update_display(
        self,
        summary: Dict[str, int],
        alerts: List,
        daemon_alive: Optional[bool] = None,
        current_screen: str = "",
    ) -> None:
        """Store data and render."""
        self._last_summary = summary
        self._last_alerts = alerts
        self._last_daemon_alive = daemon_alive
        self._last_screen = current_screen
        self._build_line(summary, alerts, daemon_alive, current_screen)

    def _build_line(
        self,
        summary: Dict[str, int],
        alerts: List,
        daemon_alive: Optional[bool],
        current_screen: str,
    ) -> None:
        """Build the status line, adapting to terminal width."""
        if daemon_alive is None:
            daemon_alive = self._cached_daemon_check()

        # ── Core segments (always shown) ──────────────────────
        if daemon_alive:
            daemon_seg = "\u2713 Connected"
        else:
            daemon_seg = "\u2717 OFFLINE"

        listening = summary.get("total_listening", 0)
        established = summary.get("total_established", 0)
        alert_count = summary.get("alert_count", len(alerts))

        if alert_count == 0:
            status_seg = "\u2022 Secure"
        else:
            has_critical = any(
                getattr(a, "level", "") == "CRITICAL" for a in alerts
            )
            if has_critical:
                status_seg = "\u2717 CRITICAL"
            else:
                status_seg = "\u26A0 Warning"

        # Desktop notifications indicator
        notif_seg = "notif \u2713" if self._desktop_notifications else "notif \u2717"

        # ── Build line based on width ─────────────────────────
        try:
            width = self.size.width
        except Exception:
            width = 80

        # Core part — always shown
        core = (
            f"{daemon_seg}  |  "
            f"{status_seg}  |  "
            f"{listening} listen  |  "
            f"{established} estab  |  "
            f"{alert_count} alerts"
        )

        if width < 60:
            # Minimal — just core
            self.update(core)
            return

        # Medium — add notif + filter
        medium = core
        medium += f"  |  {notif_seg}"
        if self._filter_info:
            medium += f"  |  {self._filter_info}"

        if width < 100:
            self.update(medium)
            return

        # Full — add screen indicator + compact shortcuts
        full = medium
        if current_screen:
            full += f"  |  {current_screen}"
        # Shortcuts without Rich bracket markup — plain text to avoid
        # Textual interpreting single letters as style names
        full += "  |  q:Quit k:Kill r:Refresh t:Tree m:Map s:Settings"
        self.update(full)
