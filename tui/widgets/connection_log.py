"""NetSentry TUI — Connection log widget (right pane).

Extends ``textual.widgets.RichLog`` to display active connections
with colour-coded, timestamped entries.
"""
from __future__ import annotations

import os
import sys
from datetime import datetime
from typing import List

from rich.text import Text
from textual.widgets import RichLog

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.models import SocketEntry

# Map states → (rich style name, display label)
_STATE_COLOURS: dict[str, tuple[str, str]] = {
    "ESTABLISHED": ("bold green", "ESTABLISHED"),
    "LISTEN":      ("bold cyan",   "LISTEN"),
    "TIME_WAIT":   ("dim",         "TIME_WAIT"),
    "CLOSE_WAIT":  ("dim red",     "CLOSE_WAIT"),
    "SYN_SENT":    ("cyan",        "SYN_SENT"),
    "SYN_RECV":    ("cyan",        "SYN_RECV"),
    "FIN_WAIT1":   ("dim yellow",  "FIN_WAIT1"),
    "FIN_WAIT2":   ("dim yellow",  "FIN_WAIT2"),
    "CLOSING":     ("dim red",     "CLOSING"),
    "LAST_ACK":    ("dim red",     "LAST_ACK"),
    "CLOSE":       ("dim",         "CLOSE"),
    "UNCONN":      ("dim",         "UNCONN"),
}


class ConnectionLog(RichLog):
    """Real-time log of network connections, auto-scrolling."""

    def on_mount(self) -> None:
        self.auto_scroll = True
        self.highlight = True
        self.markup = True

    def update_data(self, entries: List[SocketEntry]) -> None:
        """Write a batch of connection entries to the log.

        Clears previous entries to prevent unbounded memory growth,
        then emits a timestamped header followed by one line per
        connection.
        """
        self.clear()

        if not entries:
            return

        now = datetime.now().strftime("%H:%M:%S")
        self.write(f"[bold white]──── {now} ────[/]")

        for e in entries:
            style, label = _STATE_COLOURS.get(e.state, ("white", e.state))
            proc = e.process_name or "unknown"
            line = (
                f"[{style}]{label:>14}[/]  "
                f"{e.local_ip}:{e.local_port} → "
                f"{e.remote_ip}:{e.remote_port}  "
                f"({proc})"
            )
            self.write(line)
