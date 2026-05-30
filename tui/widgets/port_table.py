"""NetSentry TUI — Port table widget (left pane).

Extends ``textual.widgets.DataTable`` to display listening/active
sockets with colour-coded rows.
"""
from __future__ import annotations

import os
import sys
from typing import Dict, List, Optional

from textual.widgets import DataTable

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.models import Alert, SocketEntry
from shared import KNOWN_SAFE_PORTS

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

    def on_mount(self) -> None:
        self.cursor_type = "row"
        self.show_header = True
        self.zebra_stripes = True

    # ── Populate data ─────────────────────────────────────────
    def update_data(self, entries: List[SocketEntry], alerts: List[Alert]) -> None:
        """Clear and repopulate the table from *entries*."""
        # Build a quick lookup of port→alert-level
        alert_map: Dict[int, str] = {}
        for a in alerts:
            alert_map.setdefault(a.port, a.level)

        self.clear()
        self._row_pids.clear()
        self._row_entries.clear()

        if not self.columns:
            self.add_columns("Process", "PID", "Proto", "Address:Port", "State", "Alert")

        for entry in entries:
            addr = f"{entry.local_ip}:{entry.local_port}" if entry.state == "LISTEN" else \
                   f"{entry.local_ip}:{entry.local_port} → {entry.remote_ip}:{entry.remote_port}"
            pid_str = str(entry.pid) if entry.pid is not None else "—"
            proc_str = entry.process_name or "unknown"

            alert_level = alert_map.get(entry.local_port, "")
            alert_str = alert_level if alert_level else ""

            # Determine row colour
            colour = self._row_colour(entry, alert_level)

            row_key = f"{entry.proto}-{entry.inode}"
            self.add_row(
                f"[{colour}]{proc_str}[/]",
                f"[{colour}]{pid_str}[/]",
                f"[{colour}]{entry.proto}[/]",
                f"[{colour}]{addr}[/]",
                f"[{colour}]{entry.state}[/]",
                f"[{colour}]{alert_str}[/]",
                key=row_key,
            )
            self._row_pids[row_key] = entry.pid
            self._row_entries[row_key] = entry

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
