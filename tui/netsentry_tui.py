#!/usr/bin/env python3
"""NetSentry TUI — Terminal User Interface entry point.

Launch with:  python3 tui/netsentry_tui.py
"""
from __future__ import annotations

import os
import sys
import warnings

# Ensure the project root is on sys.path so that ``shared``, ``backend``,
# and ``tui`` are all importable regardless of cwd.
# Only needed when running this file directly (``python tui/netsentry_tui.py``).
# When installed as a package (``pip install .``), this is unnecessary.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

# Suppress Textual v8.x internal RuntimeWarning:
# "coroutine 'Header._on_mount.<locals>.set_title' was never awaited"
# This is a Textual library bug, not ours — the Header widget registers an
# async callback via watch() but does not await it on unmount.
warnings.filterwarnings(
    "ignore",
    message=r"coroutine '.*set_title.*' was never awaited",
    category=RuntimeWarning,
)

from textual.app import App, ComposeResult
from textual.binding import Binding

from shared.config import load_config, get_config, save_tui_setting
from tui.screens.main_screen import MainScreen


class NetSentryTUI(App):
    """Textual application for network security monitoring."""

    TITLE = "NetSentry — Network Security Analyzer"
    CSS_PATH = os.path.join(os.path.dirname(__file__), "styles.tcss")

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("ctrl+c", "quit", "Quit", show=False),
        Binding("n", "toggle_notifications", "Notifs", show=True),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # Read persisted TUI preference from config
        try:
            cfg = get_config()
        except Exception:
            try:
                load_config()
                cfg = get_config()
            except Exception:
                cfg = None
        self.notifications_enabled: bool = (
            cfg.tui_notifications_enabled if cfg else True
        )

    def on_mount(self) -> None:
        self.push_screen(MainScreen())

    def notify(self, message: str = "", *, severity: str = "information", **kwargs) -> None:
        """Override to respect the notifications toggle."""
        if not self.notifications_enabled:
            return
        super().notify(message, severity=severity, **kwargs)

    def action_toggle_notifications(self) -> None:
        """Toggle TUI toast notifications on/off and persist to config."""
        self.notifications_enabled = not self.notifications_enabled
        state = "ON" if self.notifications_enabled else "OFF"

        # Bypass our own override to always show the toggle feedback
        super().notify(f"Notifications: {state}", severity="information")

        # Persist to config file
        try:
            save_tui_setting("notifications_enabled", self.notifications_enabled)
        except Exception:
            pass

        # Update status bar if available
        try:
            from tui.widgets.status_bar import StatusBar
            bar = self.query_one(StatusBar)
            bar.set_notification_state(self.notifications_enabled)
        except Exception:
            pass


# ── Entry point ───────────────────────────────────────────────
def main() -> None:
    """Package entry point for ``netsentry-tui``."""
    app = NetSentryTUI()
    app.run()


if __name__ == "__main__":
    main()
