"""NetSentry TUI — Main screen.

Combines all widgets in a horizontal split layout with auto-refresh,
search/filter bar, and keyboard-driven interaction.
"""
from __future__ import annotations

import logging

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.containers import Horizontal, Vertical
from textual.widgets import Header, Footer, Input

from tui.data.provider import DataProvider
from tui.widgets.port_table import PortTable
from tui.widgets.connection_log import ConnectionLog
from tui.widgets.status_bar import StatusBar
from tui.screens.kill_confirm import KillConfirmScreen

log = logging.getLogger(__name__)

# After this many consecutive fetch failures, show "daemon down" message
_DAEMON_DOWN_THRESHOLD = 3


class MainScreen(Screen):
    """Split-pane main screen: port table + connection log + status bar."""

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("k", "kill", "Kill", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("slash", "search", "Search", show=True),
        Binding("f", "filter_toggle", "Filter", show=True),
        Binding("escape", "clear_filter", "Clear", show=False),
    ]

    CSS = """
    MainScreen {
        layout: vertical;
    }
    #main-panes {
        height: 1fr;
    }
    #search-bar {
        height: auto;
        display: none;
        margin: 0 1;
    }
    #search-input {
        width: 100%;
    }
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        self.provider = DataProvider()
        self._refresh_handle = None
        self._consecutive_failures: int = 0
        self._search_visible: bool = False

    # ── Layout ────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(id="header-bar", show_clock=True)
        with Vertical():
            yield Input(
                placeholder="Search: type to filter rows (Esc to close)...",
                id="search-input",
            )
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

    # ── Search bar events ─────────────────────────────────────
    def on_input_changed(self, event: Input.Changed) -> None:
        """Live-filter the port table as the user types."""
        if event.input.id == "search-input":
            try:
                port_table = self.query_one("#port-table", PortTable)
                port_table.set_filter(event.value)
            except Exception:
                pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Close search bar on Enter."""
        if event.input.id == "search-input":
            self._hide_search()

    # ── Data refresh ──────────────────────────────────────────
    def refresh_data(self) -> None:
        """Fetch the latest snapshot and push data into widgets."""
        snapshot = self.provider.fetch()
        if snapshot is None:
            self._consecutive_failures += 1
            if self._consecutive_failures == _DAEMON_DOWN_THRESHOLD:
                try:
                    status_bar = self.query_one("#status-bar", StatusBar)
                    status_bar.show_daemon_down()
                except Exception:
                    pass
            return

        self._consecutive_failures = 0

        try:
            port_table = self.query_one("#port-table", PortTable)
            port_table.update_data(snapshot.listening, snapshot.alerts)
        except Exception:
            log.debug("Widget update failed: port_table", exc_info=True)

        try:
            conn_log = self.query_one("#connection-log", ConnectionLog)
            conn_log.update_data(snapshot.established)
        except Exception:
            log.debug("Widget update failed: connection_log", exc_info=True)

        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.update_display(snapshot.summary, snapshot.alerts)
        except Exception:
            log.debug("Widget update failed: status_bar", exc_info=True)

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
                return
            success, msg = result
            if success:
                self.app.notify(msg, severity="information")
            else:
                self.app.notify(msg, severity="error")
            self.refresh_data()

        self.app.push_screen(
            KillConfirmScreen(entry, self.provider),
            on_result,
        )

    def action_refresh(self) -> None:
        """Force an immediate data refresh."""
        self.refresh_data()
        self.app.notify("Data refreshed", severity="information")

    def action_search(self) -> None:
        """Show the search bar and focus it."""
        self._show_search()

    def action_filter_toggle(self) -> None:
        """Toggle the search/filter bar."""
        if self._search_visible:
            self._hide_search()
        else:
            self._show_search()

    def action_clear_filter(self) -> None:
        """Clear the search filter and hide the bar."""
        try:
            search_input = self.query_one("#search-input", Input)
            search_input.value = ""
        except Exception:
            pass
        try:
            port_table = self.query_one("#port-table", PortTable)
            port_table.clear_filter()
        except Exception:
            pass
        self._hide_search()

    # ── Search bar helpers ────────────────────────────────────
    def _show_search(self) -> None:
        self._search_visible = True
        try:
            search_input = self.query_one("#search-input", Input)
            search_input.remove_class("hidden")
            search_input.focus()
        except Exception:
            pass

    def _hide_search(self) -> None:
        self._search_visible = False
        try:
            search_input = self.query_one("#search-input", Input)
            search_input.add_class("hidden")
        except Exception:
            pass
