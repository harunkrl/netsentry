"""KPortWatch TUI — Connection log widget (right pane).

Extends ``textual.widgets.RichLog`` to display active connections
with colour-coded, timestamped entries.

Uses incremental updates: only new/closed connections are logged,
preserving scrollback history.

Memory is bounded: ``max_lines`` limits the RichLog buffer and
``_seen_keys`` is capped at ``_MAX_SEEN`` entries (LRU-style).
"""
from __future__ import annotations

from collections import deque
from datetime import datetime

from backend.models import SocketEntry
from textual.widgets import RichLog

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

# Quick-filter modes (cycled with Ctrl+F)
FILTER_MODES = ["all", "new", "warning", "critical"]

# Severity levels for log filtering
SEVERITY_LEVELS = ["ALL", "INFO", "WARNING", "ERROR"]

# Maximum number of seen-key entries to prevent unbounded memory growth
_MAX_SEEN = 10_000


class ConnectionLog(RichLog):
    """Real-time log of network connections, auto-scrolling.

    Tracks seen connections by a composite key (proto+inode) and
    only appends new arrivals or removals instead of rewriting
    the entire log on every refresh.

    Memory is bounded by ``max_lines`` (default 5000) and a cap
    on the ``_seen_keys`` set.
    """

    def __init__(self, **kwargs) -> None:
        # K5: Limit RichLog buffer to prevent unbounded memory growth
        super().__init__(max_lines=5000, **kwargs)
        self._seen_keys_deque: deque[str] = deque(maxlen=_MAX_SEEN)
        self._filter_text: str = ""
        self._plain_lines: list[str] = []
        self._quick_filter: str = "all"
        self._severity_filter: str = "ALL"
        self._last_entries: list[SocketEntry] = []
        self._seen_keys: set[str] = set()

    def on_mount(self) -> None:
        self.auto_scroll = True
        self.highlight = True
        self.markup = True
        # O9: Track whether user has scrolled up manually
        self._user_scrolled_up = False

    def on_scroll(self, event) -> None:
        """O9: Detect when user scrolls up — pause auto-scroll."""
        try:
            max_scroll = self.max_scroll_y
            if max_scroll > 0 and (max_scroll - self.scroll_y) > 3:
                self._user_scrolled_up = True
            else:
                self._user_scrolled_up = False
                self.auto_scroll = True
        except Exception:
            pass

    def _check_should_auto_scroll(self) -> bool:
        """O9: Only auto-scroll if user hasn't scrolled up."""
        return not self._user_scrolled_up

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

    @property
    def severity_label(self) -> str:
        """Human-readable label for current severity filter."""
        return self._severity_filter

    def set_severity_filter(self, level: str) -> None:
        """Set severity filter level (ALL/INFO/WARNING/ERROR).

        Maps severity to connection state categories:
          - ALL: show everything
          - INFO: normal states (LISTEN, ESTABLISHED, etc.)
          - WARNING: transitional states (SYN_SENT, SYN_RECV, FIN_WAIT, TIME_WAIT, CLOSE_WAIT)
          - ERROR: problematic states (CLOSING, LAST_ACK, CLOSE)
        When WARNING or ERROR is selected, also includes all higher-severity entries.
        """
        level = level.upper().strip()
        if level not in SEVERITY_LEVELS:
            level = "ALL"
        if self._severity_filter != level:
            self._severity_filter = level
            self.clear()
            self._seen_keys.clear()
            self._plain_lines.clear()
            if self._last_entries:
                self._seen_keys.clear()
                self.update_data(self._last_entries, is_first_call=True)

    def _severity_for_state(self, state: str) -> str:
        """Map a TCP state to a severity level."""
        warning_states = {"SYN_SENT", "SYN_RECV", "FIN_WAIT1", "FIN_WAIT2",
                          "TIME_WAIT", "CLOSE_WAIT"}
        error_states = {"CLOSING", "LAST_ACK", "CLOSE"}
        if state in error_states:
            return "ERROR"
        if state in warning_states:
            return "WARNING"
        return "INFO"

    def _passes_severity_filter(self, e: SocketEntry) -> bool:
        """Check if an entry passes the severity filter."""
        if self._severity_filter == "ALL":
            return True
        severity = self._severity_for_state(e.state)
        level_order = {"INFO": 0, "WARNING": 1, "ERROR": 2}
        min_level = level_order.get(self._severity_filter, 0)
        entry_level = level_order.get(severity, 0)
        return entry_level >= min_level

    def cycle_quick_filter(self) -> str:
        """Cycle to the next quick-filter mode. Returns the new mode name."""
        idx = FILTER_MODES.index(self._quick_filter)
        self._quick_filter = FILTER_MODES[(idx + 1) % len(FILTER_MODES)]
        # Rebuild log from scratch with new filter
        self.clear()
        self._seen_keys.clear()
        self._plain_lines.clear()
        if self._last_entries:
            # O18 fix: Apply filters even on first call of rebuild
            self._seen_keys.clear()
            self.update_data(self._last_entries, is_first_call=True)
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
            key = f"{e.proto}-{e.inode}"
            return key not in self._seen_keys
        if self._quick_filter == "warning":
            return e.state in ("ESTABLISHED", "SYN_SENT", "SYN_RECV")
        if self._quick_filter == "critical":
            return e.state in ("ESTABLISHED",)
        return True

    def _passes_text_filter(self, e: SocketEntry) -> bool:
        """Check if an entry passes the text filter."""
        if not self._filter_text:
            return True
        proc = (e.process_name or "").lower()
        remote = (e.remote_hostname or e.remote_ip or "").lower()
        return (self._filter_text in proc
                or self._filter_text in remote
                or self._filter_text in str(e.local_port))

    def update_data(self, entries: list[SocketEntry], *, is_first_call: bool = False) -> None:
        """Incrementally log new and closed connections.

        On the first call (empty ``_seen_keys``), writes a header + all
        entries **with filters applied** (O18 fix).  On subsequent calls,
        only writes NEW connections (not in previous set).
        """
        current_keys: set[str] = set()
        new_entries: list[SocketEntry] = []

        # Store for quick-filter rebuilds
        self._last_entries = entries

        for e in entries:
            # Apply text filter
            if not self._passes_text_filter(e):
                continue

            # Apply severity filter
            if not self._passes_severity_filter(e):
                continue

            # Apply quick-filter
            if not self._should_show_entry(e):
                continue

            key = f"{e.proto}-{e.inode}"
            current_keys.add(key)
            if key not in self._seen_keys:
                new_entries.append(e)

        # First call — show header + all connections (filters already applied)
        if not self._seen_keys or is_first_call:
            self.clear()
            self._plain_lines.clear()
            if entries:
                now = datetime.now().strftime("%H:%M:%S")
                header = f"--- {now} ---"
                self.auto_scroll = True
                self._user_scrolled_up = False
                self.write(f"[bold white]{header}[/]")
                self._plain_lines.append(header)
                # Write all filtered entries
                for e in entries:
                    if (self._passes_text_filter(e) and self._passes_severity_filter(e)
                            and self._should_show_entry(e)):
                        self._write_entry(e)
            self._seen_keys = current_keys
            self._trim_seen()
            return

        # Subsequent calls — only log new connections
        if new_entries:
            self.auto_scroll = self._check_should_auto_scroll()
            now = datetime.now().strftime("%H:%M:%S")
            line = f"+ {now} — {len(new_entries)} new connection(s)"
            self.write(f"[bold green]{line}[/]")
            self._plain_lines.append(line)
            for e in new_entries:
                self._write_entry(e)

        # Log closed connections
        closed = self._seen_keys - current_keys
        if closed:
            self.auto_scroll = self._check_should_auto_scroll()
            now = datetime.now().strftime("%H:%M:%S")
            line = f"- {now} — {len(closed)} connection(s) closed"
            self.write(f"[dim red]{line}[/]")
            self._plain_lines.append(line)

        self._seen_keys = current_keys
        self._trim_seen()

    def _trim_seen(self) -> None:
        """Trim _seen_keys if it exceeds the max size (LRU eviction)."""
        if len(self._seen_keys) > _MAX_SEEN:
            excess = len(self._seen_keys) - _MAX_SEEN
            # Remove oldest keys (arbitrary but bounded)
            to_remove = list(self._seen_keys)[:excess]
            self._seen_keys -= set(to_remove)

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
