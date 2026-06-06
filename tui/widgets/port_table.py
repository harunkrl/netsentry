"""KPortWatch TUI — Port table widget (left pane).

Extends ``textual.widgets.DataTable`` to display listening/active
sockets with colour-coded rows, sortable columns, and search/filter.

Uses diff-based updates to avoid flickering, scroll reset, and
selection loss on every refresh cycle.
"""
from __future__ import annotations

import contextlib
import logging

from backend.models import Alert, SocketEntry
from shared import KNOWN_SAFE_PORTS
from textual.widgets import DataTable

log = logging.getLogger(__name__)

# Column indices
_COL_PROCESS = 0
_COL_PID = 1
_COL_PROTO = 2
_COL_ADDR = 3
_COL_STATE = 4
_COL_ALERT = 5
_COL_CMDLINE = 6

# Rich colour names used for row classification
_ROW_COLOURS = {
    "safe": "green",
    "info": "yellow",
    "critical": "red bold",
    "warning": "yellow",
    "default": "white",
}

# Background styles for row-level highlighting
_ROW_BG = {
    "critical": "on dark_red",
    "warning": "on #3a3200",
    "safe": "",
    "info": "",
    "default": "",
}


def _smart_truncate_addr(entry: SocketEntry) -> str:
    """Format the address:port column with smart IPv6 shortening.

    Uses RFC 5952 ``::`` notation for IPv6 to avoid aggressive truncation.
    """
    if entry.state == "LISTEN":
        ip = _shorten_ipv6(entry.local_ip)
        return f"{ip}:{entry.local_port}"
    else:
        local = _shorten_ipv6(entry.local_ip)
        remote = _shorten_ipv6(entry.remote_ip)
        return f"{local}:{entry.local_port} → {remote}:{entry.remote_port}"


def _shorten_ipv6(addr: str) -> str:
    """Shorten an IPv6 address using ``::`` notation (RFC 5952).

    Replaces the longest run of consecutive ``:0`` / ``:0000`` groups
    with ``::``.  Returns the address unchanged if it is IPv4 or does
    not contain ``:``.
    """
    if ":" not in addr:
        return addr  # IPv4 — no shortening needed

    # Remove bracket notation if present
    addr = addr.strip("[]")

    parts = addr.split(":")
    # Find the longest consecutive run of empty / "0" segments
    best_start, best_len = -1, 0
    cur_start, cur_len = -1, 0
    for i, p in enumerate(parts):
        if p in ("", "0", "0000"):
            if cur_start == -1:
                cur_start = i
            cur_len += 1
        else:
            if cur_len > best_len:
                best_start = cur_start
                best_len = cur_len
            cur_start, cur_len = -1, 0
    if cur_len > best_len:
        best_start = cur_start
        best_len = cur_len

    if best_len < 2:
        # Nothing worth compressing
        return addr

    head = ":".join(parts[:best_start])
    tail = ":".join(parts[best_start + best_len:])

    if head and tail:
        return f"{head}::{tail}"
    elif head:
        return f"{head}::"
    elif tail:
        return f"::{tail}"
    else:
        return "::"


class PortTable(DataTable):
    """DataTable of network sockets, colour-coded by alert severity.

    Uses diff-based updates: only changed/new/removed rows are
    mutated so that scroll position and cursor selection survive
    each refresh cycle.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._row_pids: dict[str, int | None] = {}
        self._row_entries: dict[str, SocketEntry] = {}
        self._last_row_key: str | None = None
        self._last_scroll_x: float = 0.0
        # D5: Filter/sort state (plain attributes for testability)
        self.filter_text: str = ""
        self.filter_proto: str = "ALL"
        self.filter_port_min: int = 0
        self.filter_port_max: int = 65535
        self.sort_column: int = -1
        self.sort_reverse: bool = False
        # Data storage
        self._all_entries: list[SocketEntry] = []
        self._all_alerts: list[Alert] = []
        # Previous row-key set for diff detection
        self._prev_keys: set[str] = set()

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.show_header = True
        self.zebra_stripes = True
        # Show initial empty state before first data fetch
        self.add_columns("Process", "PID", "Proto", "Address:Port", "State", "Alert", "Cmdline")
        self.add_row(
            "[dim]Waiting for data...[/]", "", "", "", "", "", "",
            key="_empty",
        )
        self._prev_keys = {"_empty"}

    # ── Sort & filter API ─────────────────────────────────────
    def set_filter(self, text: str) -> None:
        """Filter rows by a text search across all visible columns."""
        self.filter_text = text.lower().strip()
        self._rebuild_table()

    def set_proto_filter(self, proto: str) -> None:
        """Filter rows by protocol ('ALL', 'TCP', 'UDP', 'ICMP')."""
        self.filter_proto = proto.upper().strip()
        self._rebuild_table()

    def set_port_range_filter(self, port_min: int, port_max: int) -> None:
        """Filter rows to only show entries with local_port in [port_min, port_max]."""
        self.filter_port_min = max(0, port_min)
        self.filter_port_max = min(65535, port_max)
        self._rebuild_table()

    def clear_filter(self) -> None:
        """Remove any active filter."""
        self.filter_text = ""
        self.filter_proto = "ALL"
        self.filter_port_min = 0
        self.filter_port_max = 65535
        self._rebuild_table()

    def toggle_sort(self, column_index: int) -> None:
        """Cycle sort on a column: ascending → descending → none."""
        if self.sort_column == column_index:
            if not self.sort_reverse:
                self.sort_reverse = True
            else:
                # Third click: remove sort
                self.sort_column = -1
                self.sort_reverse = False
        else:
            self.sort_column = column_index
            self.sort_reverse = False
        self._rebuild_table()

    # ── Populate data (diff-based) ────────────────────────────
    def update_data(self, entries: list[SocketEntry], alerts: list[Alert]) -> None:
        """Store data and update the table using diff logic.

        Compares new keys against previous keys.  Rows that already
        exist are updated in-place; new rows are added; removed rows
        are deleted.  Scroll position and cursor are preserved.
        """
        # Save cursor position before update
        try:
            cell_key = self.coordinate_to_cell_key(self.cursor_coordinate)
            self._last_row_key = cell_key.row_key.value
        except Exception:
            self._last_row_key = None

        # Save horizontal scroll position
        self._last_scroll_x = self.scroll_x

        self._all_entries = entries
        self._all_alerts = alerts

        # If columns not yet added, do a full rebuild
        if not self.columns:
            self._rebuild_table()
            return

        self._apply_diff_update()

    def _apply_diff_update(self) -> None:
        """Incrementally update rows: add new, remove gone, update changed."""
        try:
            entries = self._all_entries or []
            alerts = self._all_alerts or []

            # Build alert lookup
            alert_map: dict[int, str] = {}
            for a in alerts:
                if hasattr(a, 'port') and hasattr(a, 'level'):
                    alert_map.setdefault(a.port, a.level)

            # Ensure columns exist
            if not self.columns:
                self.add_columns("Process", "PID", "Proto", "Address:Port", "State", "Alert", "Cmdline")

            # Build filtered + sorted row list
            rows: list[tuple[str, SocketEntry]] = []
            for entry in entries:
                if self.filter_text and not self._matches_filter(entry, alert_map):
                    continue
                row_key = f"{entry.proto}-{entry.inode}"
                rows.append((row_key, entry))

            if self.sort_column >= 0 and rows:
                rows = self._sort_rows(rows, alert_map)

            new_keys = {rk for rk, _ in rows}

            # Remove rows that no longer exist
            for old_key in list(self._prev_keys - new_keys):
                with contextlib.suppress(Exception):
                    self.remove_row(old_key)
                self._row_pids.pop(old_key, None)
                self._row_entries.pop(old_key, None)

            # Empty state
            if not rows and not self._row_entries:
                self.clear()
                self._row_pids.clear()
                self._row_entries.clear()
                self.add_row(
                    "[dim]No active connections — daemon running?[/]",
                    "", "", "", "", "", "",
                    key="_empty",
                )
                self._prev_keys = {"_empty"}
                return

            # Remove empty-state placeholder if real data arrived
            if "_empty" in self._prev_keys and rows:
                with contextlib.suppress(Exception):
                    self.remove_row("_empty")

            # Add/update rows
            for row_key, entry in rows:
                addr = _smart_truncate_addr(entry)
                pid_str = str(entry.pid) if entry.pid is not None else "—"
                proc_str = entry.process_name or "unknown"
                alert_level = alert_map.get(entry.local_port, "")
                alert_str = alert_level if alert_level else ""
                cmdline_str = (entry.cmdline[:50] + "…") if entry.cmdline and len(entry.cmdline) > 50 else (entry.cmdline or "—")
                colour = self._full_style(entry, alert_level)

                cell_values = (
                    f"[{colour}]{proc_str}[/]",
                    f"[{colour}]{pid_str}[/]",
                    f"[{colour}]{entry.proto}[/]",
                    f"[{colour}]{addr}[/]",
                    f"[{colour}]{entry.state}[/]",
                    f"[{colour}]{alert_str}[/]",
                    f"[dim]{cmdline_str}[/]",
                )

                if row_key in self._prev_keys:
                    # Update existing row cells
                    try:
                        for col_idx, val in enumerate(cell_values):
                            self.coordinate_to_cell_key(
                                (self._find_row_index(row_key), col_idx)
                            )
                            # Use update_cell_at for efficiency
                            rk = self._row_key_for(row_key)
                            if rk is not None:
                                self.update_cell_at(
                                    (self._find_row_index(row_key), col_idx),
                                    val,
                                )
                    except Exception:
                        # Fall back to remove + re-add
                        with contextlib.suppress(Exception):
                            self.remove_row(row_key)
                        self.add_row(*cell_values, key=row_key)
                else:
                    self.add_row(*cell_values, key=row_key)

                self._row_pids[row_key] = entry.pid
                self._row_entries[row_key] = entry

            self._prev_keys = new_keys

            # Restore cursor position
            if self._last_row_key and self._last_row_key in self._row_entries:
                try:
                    idx = self._find_row_index(self._last_row_key)
                    if idx is not None and self.has_focus:
                        self.move_cursor(row=idx, column=0, animate=False)
                except Exception:
                    pass

            # Restore horizontal scroll position
            if self._last_scroll_x:
                with contextlib.suppress(Exception):
                    self.scroll_x = self._last_scroll_x

        except Exception as e:
            log.error("Failed to diff-update table: %s", e, exc_info=True)
            # Fall back to full rebuild on error
            self._rebuild_table()

    def _find_row_index(self, row_key: str) -> int | None:
        """Find the row index for a given row key string."""
        try:
            for row_idx in range(self.row_count):
                ck = self.coordinate_to_cell_key((row_idx, 0))
                if ck.row_key.value == row_key:
                    return row_idx
        except Exception:
            pass
        return None

    def _row_key_for(self, row_key: str) -> object | None:
        """Get the DataTable RowKey for a row key string."""
        try:
            for row_idx in range(self.row_count):
                ck = self.coordinate_to_cell_key((row_idx, 0))
                if ck.row_key.value == row_key:
                    return ck.row_key
        except Exception:
            pass
        return None

    def _matches_filter(self, entry: SocketEntry, alert_map: dict[int, str]) -> bool:
        """Check if an entry matches ALL active filters (text + proto + port range)."""
        # 1) Protocol filter
        if self.filter_proto != "ALL" and entry.proto.upper() != self.filter_proto:
            return False

        # 2) Port range filter — check both local and remote ports
        local_in = self.filter_port_min <= entry.local_port <= self.filter_port_max
        remote_in = (entry.remote_port is not None and
                     self.filter_port_min <= entry.remote_port <= self.filter_port_max)
        if not local_in and not remote_in:
            return False

        # 3) Text filter
        if not self.filter_text:
            return True
        addr = (f"{entry.local_ip}:{entry.local_port}" if entry.state == "LISTEN"
                    else f"{entry.local_ip}:{entry.local_port} → {entry.remote_ip}:{entry.remote_port}")
        pid_str = str(entry.pid) if entry.pid is not None else "—"
        proc_str = entry.process_name or "unknown"
        alert_level = alert_map.get(entry.local_port, "")
        alert_str = alert_level if alert_level else ""

        searchable = " ".join([
            proc_str, pid_str, entry.proto, addr,
            entry.state, alert_str, entry.cmdline or "",
        ]).lower()
        return self.filter_text in searchable

    def _rebuild_table(self) -> None:
        """Full rebuild — clear and repopulate (used for filter/sort changes)."""
        try:
            entries = self._all_entries or []
            alerts = self._all_alerts or []

            # Build a quick lookup of port→alert-level
            alert_map: dict[int, str] = {}
            for a in alerts:
                if hasattr(a, 'port') and hasattr(a, 'level'):
                    alert_map.setdefault(a.port, a.level)

            self.clear()
            self._row_pids.clear()
            self._row_entries.clear()

            if not self.columns:
                self.add_columns("Process", "PID", "Proto", "Address:Port", "State", "Alert", "Cmdline")

            # Empty state placeholder
            if not entries:
                self.add_row(
                    "[dim]No active connections — daemon running?[/]",
                    "", "", "", "", "", "",
                    key="_empty",
                )
                self._prev_keys = {"_empty"}
                return

            # Build row data
            rows: list[tuple[str, SocketEntry]] = []
            for entry in entries:
                if self.filter_text and not self._matches_filter(entry, alert_map):
                    continue

                row_key = f"{entry.proto}-{entry.inode}"
                rows.append((row_key, entry))

            # Sort before adding
            if self.sort_column >= 0 and rows:
                rows = self._sort_rows(rows, alert_map)

            # Add to table
            for row_key, entry in rows:
                addr = _smart_truncate_addr(entry)
                pid_str = str(entry.pid) if entry.pid is not None else "—"
                proc_str = entry.process_name or "unknown"
                alert_level = alert_map.get(entry.local_port, "")
                alert_str = alert_level if alert_level else ""
                cmdline_str = (entry.cmdline[:50] + "…") if entry.cmdline and len(entry.cmdline) > 50 else (entry.cmdline or "—")
                colour = self._full_style(entry, alert_level)

                self.add_row(
                    f"[{colour}]{proc_str}[/]",
                    f"[{colour}]{pid_str}[/]",
                    f"[{colour}]{entry.proto}[/]",
                    f"[{colour}]{addr}[/]",
                    f"[{colour}]{entry.state}[/]",
                    f"[{colour}]{alert_str}[/]",
                    f"[dim]{cmdline_str}[/]",
                    key=row_key,
                )
                self._row_pids[row_key] = entry.pid
                self._row_entries[row_key] = entry

            self._prev_keys = {rk for rk, _ in rows}

            # Restore cursor position after repopulating
            if self._last_row_key and self._last_row_key in self._row_entries:
                try:
                    idx = self._find_row_index(self._last_row_key)
                    if idx is not None and self.has_focus:
                        self.move_cursor(row=idx, column=0, animate=False)
                except Exception:
                    pass

            # Restore horizontal scroll position
            if self._last_scroll_x:
                with contextlib.suppress(Exception):
                    self.scroll_x = self._last_scroll_x

        except Exception as e:
            log.error("Failed to rebuild table: %s", e, exc_info=True)

    def _sort_rows(self, rows: list[tuple[str, SocketEntry]], alert_map: dict[int, str]) -> list[tuple[str, SocketEntry]]:
        """Sort rows based on _sort_column."""
        col = self.sort_column

        def _sort_key(item: tuple[str, SocketEntry]) -> str:
            _, entry = item
            if col == _COL_PROCESS:
                return (entry.process_name or "zzz").lower()
            elif col == _COL_PID:
                return str(entry.pid or 999999).zfill(6)
            elif col == _COL_PROTO:
                return entry.proto
            elif col == _COL_ADDR:
                return f"{entry.local_port:05d}"
            elif col == _COL_STATE:
                return entry.state
            elif col == _COL_ALERT:
                return alert_map.get(entry.local_port, "zzz")
            elif col == _COL_CMDLINE:
                return (entry.cmdline or "zzz").lower()
            return ""

        return sorted(rows, key=_sort_key, reverse=self.sort_reverse)

    # ── Colour logic ──────────────────────────────────────────
    @staticmethod
    def _row_colour(entry: SocketEntry, alert_level: str) -> str:
        """Return Rich style string for the row based on alert level."""
        if alert_level == "CRITICAL":
            return _ROW_COLOURS["critical"]
        if alert_level == "WARNING":
            return _ROW_COLOURS["warning"]
        if entry.local_port in KNOWN_SAFE_PORTS:
            return _ROW_COLOURS["safe"]
        if alert_level == "INFO":
            return _ROW_COLOURS["info"]
        return _ROW_COLOURS["default"]

    @staticmethod
    def _row_bg(entry: SocketEntry, alert_level: str) -> str:
        """Return Rich background style for the row (subtle highlight)."""
        if alert_level == "CRITICAL":
            return _ROW_BG["critical"]
        if alert_level == "WARNING":
            return _ROW_BG["warning"]
        return ""

    @staticmethod
    def _full_style(entry: SocketEntry, alert_level: str) -> str:
        """Combined fg + bg style string for Rich markup."""
        fg = PortTable._row_colour(entry, alert_level)
        bg = PortTable._row_bg(entry, alert_level)
        if bg:
            return f"{fg} {bg}"
        return fg

    # ── Column header click → sort ────────────────────────────
    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Toggle sort when a column header is clicked."""
        self.toggle_sort(event.column_index)

    # ── Selection helpers ─────────────────────────────────────
    def get_selected_entry(self) -> SocketEntry | None:
        """Return the ``SocketEntry`` for the currently selected row."""
        try:
            cell_key = self.coordinate_to_cell_key(self.cursor_coordinate)
            return self._row_entries.get(cell_key.row_key.value)
        except Exception:
            return None

    def get_selected_pid(self) -> int | None:
        """Return the PID of the currently selected row, if any."""
        try:
            cell_key = self.coordinate_to_cell_key(self.cursor_coordinate)
            return self._row_pids.get(cell_key.row_key.value)
        except Exception:
            return None

    # ── Port scan detection ────────────────────────────────────
    def detect_port_scan(self, threshold: int | None = None) -> list[dict]:
        """Detect potential port scans based on unique ports per remote IP.

        Args:
            threshold: Number of unique ports from a single remote IP to
                       consider it a port scan. Reads from config if not provided.

        Returns:
            List of dicts with 'remote_ip', 'port_count', 'ports' keys.
        """
        if threshold is None:
            try:
                from shared.config import get_config
                cfg = get_config()
                threshold = getattr(cfg, 'scan_threshold', 5)
            except Exception:
                threshold = 5

        # Count unique ports per remote IP
        ip_ports: dict[str, set[int]] = {}
        for entry in self._all_entries:
            if entry.state != "LISTEN" and entry.remote_ip:
                ip_ports.setdefault(entry.remote_ip, set()).add(
                    entry.remote_port or 0
                )

        # Find IPs exceeding the threshold
        results: list[dict] = []
        for ip, ports in ip_ports.items():
            if len(ports) >= threshold:
                results.append({
                    "remote_ip": ip,
                    "port_count": len(ports),
                    "ports": sorted(ports),
                })

        # Sort by port count descending
        results.sort(key=lambda x: x["port_count"], reverse=True)
        return results

    @property
    def scan_suspects(self) -> list[dict]:
        """Convenience accessor for detected port scan suspects."""
        return self.detect_port_scan()
