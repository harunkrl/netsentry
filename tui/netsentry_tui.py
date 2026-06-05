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

from shared.config import load_config, get_config
from tui.screens.main_screen import MainScreen


class NetSentryTUI(App):
    """Textual application for network security monitoring."""

    TITLE = "NetSentry — Network Security Analyzer"
    CSS_PATH = os.path.join(os.path.dirname(__file__), "styles.tcss")

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # Load persisted config (always load fresh on startup)
        cfg = load_config()
        self.notifications_enabled: bool = cfg.tui_notifications_enabled

    def on_mount(self) -> None:
        self.push_screen(MainScreen())

    def notify(self, message: str = "", *, severity: str = "information", **kwargs) -> None:
        """Override to respect the notifications toggle."""
        if not self.notifications_enabled:
            return
        super().notify(message, severity=severity, **kwargs)

    def action_open_settings(self) -> None:
        """Open the settings screen."""
        from tui.screens.settings_screen import SettingsScreen
        from shared.config import get_config
        cfg = get_config()
        self.push_screen(SettingsScreen(
            desktop_notifications=cfg.notifications_enabled,
            tui_notifications=self.notifications_enabled,
        ))


# ── Entry point ───────────────────────────────────────────────
def main() -> None:
    """Package entry point for ``netsentry-tui``."""
    app = NetSentryTUI()
    app.run()


if __name__ == "__main__":
    main()
