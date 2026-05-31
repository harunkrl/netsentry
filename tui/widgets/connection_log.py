"""NetSentry TUI — Connection log widget (right pane).

Extends ``textual.widgets.RichLog`` to display active connections
with colour-coded, timestamped entries.

Uses incremental updates: only new/closed connections are logged,
preserving scrollback history.
"""
from __future__ import annotations

from datetime import datetime
from typing import List, Set

from rich.text import Text
from textual.widgets import RichLog

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
    """Real-time log of network connections, auto-scrolling.

    Tracks seen connections by a composite key (proto+inode) and
    only appends new arrivals or removals instead of rewriting
    the entire log on every refresh.
    """

    def on_mount(self) -> None:
        self.auto_scroll = True
        self.highlight = True
        self.markup = True
        self._seen_keys: Set[str] = set()
        self._filter_text: str = ""

    def set_filter(self, text: str) -> None:
        """Apply a filter. Clears the log so that only matching connections will be reprinted."""
        new_filter = text.lower()
        if self._filter_text != new_filter:
            self._filter_text = new_filter
            self.clear()
            self._seen_keys.clear()

    def update_data(self, entries: List[SocketEntry]) -> None:
        """Incrementally log new and closed connections.

        On the first call (empty _seen_keys), writes a header + all entries.
        On subsequent calls, only writes NEW connections (not in previous set).
        """
        current_keys: Set[str] = set()
        new_entries: List[SocketEntry] = []

        for e in entries:
            # Task 3.6: ConnectionLog filtering
            if self._filter_text:
                proc = (e.process_name or "").lower()
                remote = (e.remote_hostname or e.remote_ip or "").lower()
                if self._filter_text not in proc and self._filter_text not in remote and self._filter_text not in str(e.local_port):
                    continue

            key = f"{e.proto}-{e.inode}"
            current_keys.add(key)
            if key not in self._seen_keys:
                new_entries.append(e)

        # First call — show header + all connections
        if not self._seen_keys:
            self.clear()
            if entries:
                now = datetime.now().strftime("%H:%M:%S")
                self.write(f"[bold white]--- {now} ---[/]")
                for e in entries:
                    self._write_entry(e)
            self._seen_keys = current_keys
            return

        # Subsequent calls — only log new connections
        if new_entries:
            now = datetime.now().strftime("%H:%M:%S")
            self.write(f"[bold green]+ {now} — {len(new_entries)} new connection(s)[/]")
            for e in new_entries:
                self._write_entry(e)

        # Log closed connections
        closed = self._seen_keys - current_keys
        if closed:
            now = datetime.now().strftime("%H:%M:%S")
            self.write(f"[dim red]- {now} — {len(closed)} connection(s) closed[/]")

        self._seen_keys = current_keys

    def _write_entry(self, e: SocketEntry) -> None:
        """Write a single connection entry to the log."""
        style, label = _STATE_COLOURS.get(e.state, ("white", e.state))
        proc = e.process_name or "unknown"
        
        # Show hostname if available, else just IP
        remote_host = e.remote_hostname if e.remote_hostname else e.remote_ip
        remote = f"{remote_host}:{e.remote_port}" if e.remote_port else remote_host
        
        line = (
            f"  [{style}]{label:>14}[/]  "
            f"{e.local_ip}:{e.local_port} → "
            f"{remote}  "
            f"({proc})"
        )
        self.write(line)
