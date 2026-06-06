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

# Quick-filter modes (cycled with 'f' key)
FILTER_MODES = ["all", "new", "warning", "critical"]


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
        self._plain_lines: list[str] = []
        self._quick_filter: str = "all"  # "all" | "new" | "warning" | "critical"
        self._last_entries: List[SocketEntry] = []

    @property
    def quick_filter_label(self) -> str:
        """Human-readable label for current quick-filter mode."""
        labels = {
            "all": "Showing all",
            "new": "Only new",
            "warning": "Only WARNING+",
            "critical": "Only CRITICAL",
        }
        return labels.get(self._quick_filter, "Showing all")

    def cycle_quick_filter(self) -> str:
        """Cycle to the next quick-filter mode. Returns the new mode name."""
        idx = FILTER_MODES.index(self._quick_filter)
        self._quick_filter = FILTER_MODES[(idx + 1) % len(FILTER_MODES)]
        # Rebuild log from scratch with new filter
        self.clear()
        self._seen_keys.clear()
        self._plain_lines.clear()
        if self._last_entries:
            self.update_data(self._last_entries)
        return self._quick_filter

    def set_filter(self, text: str) -> None:
        """Apply a filter. Clears the log so that only matching connections will be reprinted."""
        new_filter = text.lower()
        if self._filter_text != new_filter:
            self._filter_text = new_filter
            self.clear()
            self._seen_keys.clear()
            self._plain_lines.clear()

    def get_plain_text(self) -> str:
        """Return all log content as plain text (no Rich markup)."""
        return "\n".join(self._plain_lines)

    def _should_show_entry(self, e: SocketEntry) -> bool:
        """Check if an entry passes the current quick-filter."""
        if self._quick_filter == "all":
            return True
        if self._quick_filter == "new":
            # Only show entries not in the previous snapshot
            key = f"{e.proto}-{e.inode}"
            return key not in self._seen_keys
        # warning / critical — show based on connection characteristics
        # High-remote-port or unusual states are "warning-like"
        if self._quick_filter == "warning":
            return e.state in ("ESTABLISHED", "SYN_SENT", "SYN_RECV")
        if self._quick_filter == "critical":
            return e.state in ("ESTABLISHED",)
        return True

    def update_data(self, entries: List[SocketEntry]) -> None:
        """Incrementally log new and closed connections.

        On the first call (empty _seen_keys), writes a header + all entries.
        On subsequent calls, only writes NEW connections (not in previous set).
        """
        current_keys: Set[str] = set()
        new_entries: List[SocketEntry] = []

        # Store for quick-filter rebuilds
        self._last_entries = entries

        for e in entries:
            # Task 3.6: ConnectionLog filtering
            if self._filter_text:
                proc = (e.process_name or "").lower()
                remote = (e.remote_hostname or e.remote_ip or "").lower()
                if self._filter_text not in proc and self._filter_text not in remote and self._filter_text not in str(e.local_port):
                    continue

            # Apply quick-filter
            if not self._should_show_entry(e):
                continue

            key = f"{e.proto}-{e.inode}"
            current_keys.add(key)
            if key not in self._seen_keys:
                new_entries.append(e)

        # First call — show header + all connections
        if not self._seen_keys:
            self.clear()
            self._plain_lines.clear()
            if entries:
                now = datetime.now().strftime("%H:%M:%S")
                header = f"--- {now} ---"
                self.write(f"[bold white]{header}[/]")
                self._plain_lines.append(header)
                for e in entries:
                    self._write_entry(e)
            self._seen_keys = current_keys
            return

        # Subsequent calls — only log new connections
        if new_entries:
            now = datetime.now().strftime("%H:%M:%S")
            line = f"+ {now} — {len(new_entries)} new connection(s)"
            self.write(f"[bold green]{line}[/]")
            self._plain_lines.append(line)
            for e in new_entries:
                self._write_entry(e)

        # Log closed connections
        closed = self._seen_keys - current_keys
        if closed:
            now = datetime.now().strftime("%H:%M:%S")
            line = f"- {now} — {len(closed)} connection(s) closed"
            self.write(f"[dim red]{line}[/]")
            self._plain_lines.append(line)

        self._seen_keys = current_keys

    def _write_entry(self, e: SocketEntry) -> None:
        """Write a single connection entry to the log."""
        style, label = _STATE_COLOURS.get(e.state, ("white", e.state))
        proc = e.process_name or "unknown"

        remote_host = e.remote_hostname if e.remote_hostname else e.remote_ip
        remote = f"{remote_host}:{e.remote_port}" if e.remote_port else remote_host

        # Append ISP info if available
        isp = e.remote_isp or e.remote_org or ""
        isp_tag = f" [{isp}]" if isp else ""

        plain = (
            f"  {label:>14}  "
            f"{e.local_ip}:{e.local_port} → "
            f"{remote}{isp_tag}  "
            f"({proc})"
        )
        self._plain_lines.append(plain)
        self.write(
            f"  [{style}]{label:>14}[/]  "
            f"{e.local_ip}:{e.local_port} → "
            f"[bold]{remote}[/][dim]{isp_tag}[/]  "
            f"({proc})"
        )
