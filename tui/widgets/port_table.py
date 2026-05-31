"""NetSentry TUI — Port table widget (left pane).

Extends ``textual.widgets.DataTable`` to display listening/active
sockets with colour-coded rows, sortable columns, and search/filter.
"""
from __future__ import annotations

from typing import Dict, List, Optional
import logging

from textual.widgets import DataTable

from backend.models import Alert, SocketEntry
from shared import KNOWN_SAFE_PORTS

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
    "critical": "red",
    "default": "white",
}


class PortTable(DataTable):
    """DataTable of network sockets, colour-coded by alert severity."""

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self._row_pids: Dict[str, Optional[int]] = {}
        self._row_entries: Dict[str, SocketEntry] = {}
        self._last_row_key: Optional[str] = None
        # Filter state
        self._filter_text: str = ""
        self._all_entries: List[SocketEntry] = []
        self._all_alerts: List[Alert] = []
        # Sort state
        self._sort_column: int = -1
        self._sort_reverse: bool = False

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.show_header = True
        self.zebra_stripes = True

    # ── Sort & filter API ─────────────────────────────────────
    def set_filter(self, text: str) -> None:
        """Filter rows by a text search across all visible columns."""
        self._filter_text = text.lower().strip()
        self._rebuild_table()

    def clear_filter(self) -> None:
        """Remove any active filter."""
        self._filter_text = ""
        self._rebuild_table()

    def toggle_sort(self, column_index: int) -> None:
        """Cycle sort on a column: ascending → descending → none."""
        if self._sort_column == column_index:
            if not self._sort_reverse:
                self._sort_reverse = True
            else:
                # Third click: remove sort
                self._sort_column = -1
                self._sort_reverse = False
        else:
            self._sort_column = column_index
            self._sort_reverse = False
        self._rebuild_table()

    # ── Populate data ─────────────────────────────────────────
    def update_data(self, entries: List[SocketEntry], alerts: List[Alert]) -> None:
        """Store data and rebuild the table.

        Preserves cursor position across refreshes so the user's
        selection is not lost every 2 seconds.
        """
        # Save cursor position before clearing
        try:
            cell_key = self.coordinate_to_cell_key(self.cursor_coordinate)
            self._last_row_key = cell_key.row_key.value
        except Exception:
            self._last_row_key = None

        self._all_entries = entries
        self._all_alerts = alerts
        self._rebuild_table()

    def _rebuild_table(self) -> None:
        """Clear and repopulate the table from stored data, applying filter & sort."""
        try:
            entries = self._all_entries or []
            alerts = self._all_alerts or []

            # Build a quick lookup of port→alert-level
            alert_map: Dict[int, str] = {}
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
                    "[dim]No listening ports — daemon running?[/]",
                    "", "", "", "", "", "",
                    key="_empty",
                )
                return

            # Build row data
            rows: List[tuple[str, SocketEntry]] = []
            for entry in entries:
                if self._filter_text:
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
                    if self._filter_text not in searchable:
                        continue

                row_key = f"{entry.proto}-{entry.inode}"
                rows.append((row_key, entry))

            # Sort before adding
            if self._sort_column >= 0 and rows:
                rows = self._sort_rows(rows, alert_map)

            # Add to table
            for row_key, entry in rows:
                addr = (f"{entry.local_ip}:{entry.local_port}" if entry.state == "LISTEN"
                        else f"{entry.local_ip}:{entry.local_port} → {entry.remote_ip}:{entry.remote_port}")
                pid_str = str(entry.pid) if entry.pid is not None else "—"
                proc_str = entry.process_name or "unknown"
                alert_level = alert_map.get(entry.local_port, "")
                alert_str = alert_level if alert_level else ""
                cmdline_str = (entry.cmdline[:50] + "…") if entry.cmdline and len(entry.cmdline) > 50 else (entry.cmdline or "—")
                colour = self._row_colour(entry, alert_level)

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

            # Restore cursor position after repopulating
            if self._last_row_key and self._last_row_key in self._row_entries:
                try:
                    for row_idx in range(self.row_count):
                        ck = self.coordinate_to_cell_key((row_idx, 0))
                        if ck.row_key.value == self._last_row_key:
                            self.move_cursor(row=row_idx, column=0)
                            break
                except Exception:
                    pass
        
        except Exception as e:
            log.error("Failed to rebuild table: %s", e, exc_info=True)

    def _sort_rows(self, rows: List[tuple[str, SocketEntry]], alert_map: Dict[int, str]) -> List[tuple[str, SocketEntry]]:
        """Sort rows based on _sort_column."""
        col = self._sort_column

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

        return sorted(rows, key=_sort_key, reverse=self._sort_reverse)

    # ── Colour logic ──────────────────────────────────────────
    @staticmethod
    def _row_colour(entry: SocketEntry, alert_level: str) -> str:
        if alert_level == "CRITICAL":
            return _ROW_COLOURS["critical"]
        if alert_level == "WARNING":
            return _ROW_COLOURS["info"]
        if entry.local_port in KNOWN_SAFE_PORTS:
            return _ROW_COLOURS["safe"]
        if alert_level == "INFO":
            return _ROW_COLOURS["info"]
        return _ROW_COLOURS["default"]

    # ── Column header click → sort ────────────────────────────
    def on_data_table_header_selected(self, event: DataTable.HeaderSelected) -> None:
        """Toggle sort when a column header is clicked."""
        self.toggle_sort(event.column_index)

    # ── Selection helpers ─────────────────────────────────────
    def get_selected_entry(self) -> Optional[SocketEntry]:
        """Return the ``SocketEntry`` for the currently selected row."""
        try:
            cell_key = self.coordinate_to_cell_key(self.cursor_coordinate)
            return self._row_entries.get(cell_key.row_key.value)
        except Exception:
            return None

    def get_selected_pid(self) -> Optional[int]:
        """Return the PID of the currently selected row, if any."""
        try:
            cell_key = self.coordinate_to_cell_key(self.cursor_coordinate)
            return self._row_pids.get(cell_key.row_key.value)
        except Exception:
            return None
