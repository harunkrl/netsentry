"""NetSentry TUI — Main screen.

Combines all widgets in a horizontal split layout with auto-refresh.
"""
from __future__ import annotations

import os
import sys

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.containers import Horizontal
from textual.widgets import Header, Footer

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from tui.data.provider import DataProvider
from tui.widgets.port_table import PortTable
from tui.widgets.connection_log import ConnectionLog
from tui.widgets.status_bar import StatusBar
from tui.screens.kill_confirm import KillConfirmScreen


class MainScreen(Screen):
    """Split-pane main screen: port table + connection log + status bar."""

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("k", "kill", "Kill", show=True),
        Binding("r", "refresh", "Refresh", show=True),
    ]

    CSS = """
    MainScreen {
        layout: vertical;
    }
    #main-panes {
        height: 1fr;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.provider = DataProvider()
        self._refresh_handle = None

    # ── Layout ────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(id="header-bar", show_clock=True)
        with Horizontal(id="main-panes"):
            yield PortTable(id="port-table")
            yield ConnectionLog(id="connection-log")
        yield StatusBar(id="status-bar")
        yield Footer()

    # ── Auto-refresh ──────────────────────────────────────────
    def on_mount(self) -> None:
        self.refresh_data()
        self._refresh_handle = self.set_interval(2.0, self.refresh_data)

    def on_unmount(self) -> None:
        if self._refresh_handle is not None:
            self._refresh_handle.stop()

    # ── Data refresh ──────────────────────────────────────────
    def refresh_data(self) -> None:
        """Fetch the latest snapshot and push data into widgets."""
        snapshot = self.provider.fetch()
        if snapshot is None:
            return

        try:
            port_table = self.query_one("#port-table", PortTable)
            port_table.update_data(snapshot.listening, snapshot.alerts)
        except Exception:
            pass

        try:
            conn_log = self.query_one("#connection-log", ConnectionLog)
            conn_log.update_data(snapshot.established)
        except Exception:
            pass

        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.update_display(snapshot.summary, snapshot.alerts)
        except Exception:
            pass

    # ── Actions ───────────────────────────────────────────────
    def action_quit(self) -> None:
        self.app.exit()

    def action_kill(self) -> None:
        """Open kill-confirmation modal for the selected table row."""
        port_table = self.query_one("#port-table", PortTable)
        entry = port_table.get_selected_entry()

        if entry is None:
            self.app.notify("No row selected", severity="warning")
            return

        def on_result(result: tuple[bool, str] | None) -> None:
            if result is None:
                return  # cancelled
            success, msg = result
            if success:
                self.app.notify(msg, severity="information")
            else:
                self.app.notify(msg, severity="error")
            # Trigger an immediate refresh
            self.refresh_data()

        self.app.push_screen(
            KillConfirmScreen(entry, self.provider),
            on_result,
        )

    def action_refresh(self) -> None:
        """Force an immediate data refresh."""
        self.refresh_data()
        self.app.notify("Data refreshed", severity="information")
