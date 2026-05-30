#!/usr/bin/env python3
"""NetSentry TUI — Terminal User Interface entry point.

Launch with:  python3 tui/netsentry_tui.py
"""
from __future__ import annotations

import os
import sys

# Ensure the project root is on sys.path so that ``shared``, ``backend``,
# and ``tui`` are all importable regardless of cwd.
# Only needed when running this file directly (``python tui/netsentry_tui.py``).
# When installed as a package (``pip install .``), this is unnecessary.
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

from textual.app import App, ComposeResult
from textual.binding import Binding

from tui.screens.main_screen import MainScreen


class NetSentryTUI(App):
    """Textual application for network security monitoring."""

    TITLE = "NetSentry — Network Security Analyzer"
    CSS_PATH = os.path.join(os.path.dirname(__file__), "styles.tcss")

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    def on_mount(self) -> None:
        self.push_screen(MainScreen())


# ── Entry point ───────────────────────────────────────────────
def main() -> None:
    """Package entry point for ``netsentry-tui``."""
    app = NetSentryTUI()
    app.run()


if __name__ == "__main__":
    main()
