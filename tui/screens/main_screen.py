"""KPortWatch TUI — Main screen.

Combines all widgets in a horizontal split layout with auto-refresh,
search/filter bar, and keyboard-driven interaction.
"""
from __future__ import annotations

import asyncio
import logging

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Vertical
from textual.screen import Screen
from textual.widgets import Footer, Header, Input

from tui.data.provider import DataProvider
from tui.screens.kill_confirm import KillConfirmScreen
from tui.widgets.connection_log import ConnectionLog
from tui.widgets.port_table import PortTable
from tui.widgets.status_bar import StatusBar
from tui.widgets.traffic_bar import TrafficBar

log = logging.getLogger(__name__)

# After this many consecutive fetch failures, show "daemon down" message
_DAEMON_DOWN_THRESHOLD = 3


class MainScreen(Screen):
    """Split-pane main screen: port table + connection log + status bar."""

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("k", "kill", "Kill", show=True),
        Binding("r", "refresh", "Refresh", show=True),
        Binding("t", "tree", "Procs", show=True),
        Binding("m", "geo_map", "Map", show=True),
        Binding("s", "settings", "Settings", show=True),
        Binding("slash", "search", "Search", show=True),
        Binding("ctrl+f", "log_filter_cycle", "LogFilter", show=False),
        Binding("ctrl+p", "proto_filter_cycle", "Proto", show=False),
        Binding("e", "export", "Export", show=True),
        Binding("c", "copy_row", "Copy", show=True),
        Binding("question_mark", "help", "Help", show=True),
        Binding("escape", "clear_filter", "Clear", show=False),
    ]

    CSS = """
    MainScreen {
        layout: vertical;
    }
    #main-panes {
        height: 1fr;
    }
    #search-input {
        width: 100%;
    }
    /* Uses global .hidden from styles.tcss */
    #traffic-bar {
        height: auto;
        padding: 0 1;
        background: $surface;
    }
    """

    def __init__(self, provider: DataProvider | None = None, **kwargs) -> None:
        super().__init__(**kwargs)
        # Y15: Use singleton provider from app, or create new one
        self.provider = provider or DataProvider()
        self._refresh_handle = None
        self._consecutive_failures: int = 0
        self._search_visible: bool = False
        self._filter_target: str = ""  # "port-table" or "connection-log"
        self._focus_before_search = None

    # ── Layout ────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(id="header-bar", show_clock=True)
        with Vertical():
            yield Input(
                placeholder="Search: type to filter rows (Esc to close)...",
                id="search-input",
                classes="hidden",
            )
            with Vertical(id="main-panes"):
                yield PortTable(id="port-table")
                yield ConnectionLog(id="connection-log")
            yield TrafficBar(id="traffic-bar")
        yield StatusBar(id="status-bar")
        yield Footer()

    # ── Auto-refresh ──────────────────────────────────────────
    def on_mount(self) -> None:
        # Delay first refresh by one frame so layout settles first
        self.set_timer(0.1, self._first_refresh)
        self._refresh_handle = self.set_interval(2.0, self.refresh_data)
        # Focus the port table on startup
        self.query_one("#port-table", PortTable).focus()

    def _first_refresh(self) -> None:
        self.refresh_data()

    def on_resize(self, event) -> None:
        """Re-render status bar when terminal is resized (fullscreen, F11, etc.)."""
        # Defer by one frame so the layout engine has settled and
        # StatusBar has its new size before we read self.size.width.
        self.set_timer(0.05, self._deferred_statusbar_rerender)

    def _deferred_statusbar_rerender(self) -> None:
        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            status_bar.rerender()
        except Exception:
            pass

    def on_screen_resume(self) -> None:
        """Restore focus to port table when returning from a sub-screen."""
        self.query_one("#port-table", PortTable).focus()

    def on_unmount(self) -> None:
        if self._refresh_handle is not None:
            self._refresh_handle.stop()

    # ── Search bar events ─────────────────────────────────────
    def on_input_changed(self, event: Input.Changed) -> None:
        """Live-filter the focused panel as the user types."""
        if event.input.id == "search-input":
            try:
                query = event.value
                status_bar = self.query_one("#status-bar", StatusBar)

                if self._filter_target == "connection-log":
                    conn_log = self.query_one("#connection-log", ConnectionLog)
                    conn_log.set_filter(query)
                    if query.strip():
                        status_bar.set_filter_info(f"Filter: '{query}' → ConnectionLog")
                    else:
                        status_bar.set_filter_info("")
                else:
                    port_table = self.query_one("#port-table", PortTable)
                    port_table.set_filter(query)
                    if query.strip():
                        visible = len(port_table._row_entries)
                        status_bar.set_filter_info(f"Filter: '{query}' → PortTable ({visible} shown)")
                    else:
                        status_bar.set_filter_info("")
            except Exception:
                pass

    def on_input_submitted(self, event: Input.Submitted) -> None:
        """Close search bar on Enter — preserve filter."""
        if event.input.id == "search-input":
            self._hide_search(preserve_filter=True)

    def on_key(self, event) -> None:
        """Intercept Escape/Tab when search Input has focus."""
        if not self._search_visible:
            return
        if event.key == "escape":
            self._hide_search(preserve_filter=False)
            event.stop()
        elif event.key == "tab":
            self._hide_search(preserve_filter=True)

    # ── Data refresh ──────────────────────────────────────────
    @work(exclusive=True)
    async def refresh_data(self) -> None:
        """Fetch the latest snapshot and push data into widgets."""
        snapshot = await asyncio.to_thread(self.provider.fetch)
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

        # Save which widget currently has focus before updating
        focused = self.focused

        try:
            port_table = self.query_one("#port-table", PortTable)
            listening = getattr(snapshot, "listening", []) or []
            alerts = getattr(snapshot, "alerts", []) or []
            port_table.update_data(listening, alerts)
        except Exception:
            log.debug("Widget update failed: port_table", exc_info=True)

        try:
            conn_log = self.query_one("#connection-log", ConnectionLog)
            established = getattr(snapshot, "established", []) or []
            conn_log.update_data(established)
        except Exception:
            log.debug("Widget update failed: connection_log", exc_info=True)

        try:
            status_bar = self.query_one("#status-bar", StatusBar)
            # Use desktop_notifications from config, not TUI toast
            from shared.config import get_config
            cfg = get_config()
            status_bar.set_notification_state(cfg.notifications_enabled)
            summary = getattr(snapshot, "summary", {}) or {}
            alerts = getattr(snapshot, "alerts", []) or []
            status_bar.update_display(summary, alerts, current_screen="Dashboard")
        except Exception:
            log.debug("Widget update failed: status_bar", exc_info=True)

        try:
            traffic_bar = self.query_one("#traffic-bar", TrafficBar)
            traffic = getattr(snapshot, "traffic", {}) or {}
            traffic_bar.update_data(traffic)
        except Exception:
            log.debug("Widget update failed: traffic_bar", exc_info=True)

        # Restore focus if it was stolen during the update cycle
        if focused and self.focused is not focused:
            focused.focus()

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

    def action_export(self) -> None:
        """Export current snapshot to JSON.

        O3: Shows file path in notification after successful export.
        """
        snapshot = self.provider.fetch()
        if snapshot:
            try:
                import os
                from datetime import datetime
                ts = datetime.now().strftime("%Y%m%d_%H%M%S")
                path = os.path.expanduser(f"~/kportwatch_export_{ts}.json")
                with open(path, "w") as f:
                    f.write(snapshot.to_json())
                self.app.notify(f"Exported to {path}", severity="information")
            except Exception as e:
                self.app.notify(f"Export failed: {e}", severity="error")

    def action_help(self) -> None:
        """Show the help screen."""
        from tui.screens.help_screen import HelpScreen
        self.app.push_screen(HelpScreen())

    def action_settings(self) -> None:
        """Open the settings screen."""
        self.app.action_open_settings()

    def action_tree(self) -> None:
        """Open the process tree view."""
        from tui.screens.process_tree_screen import ProcessTreeScreen
        self.app.push_screen(ProcessTreeScreen())

    def action_geo_map(self) -> None:
        """Open the connection map view."""
        from tui.screens.connection_map_screen import ConnectionMapScreen
        self.app.push_screen(ConnectionMapScreen())

    def on_data_table_row_selected(self, event) -> None:
        """Show detail screen when a row is selected (Enter)."""
        port_table = self.query_one("#port-table", PortTable)
        entry = port_table.get_selected_entry()
        if entry:
            from tui.screens.detail_screen import DetailScreen
            self.app.push_screen(DetailScreen(entry))

    def action_refresh(self) -> None:
        """Force an immediate data refresh."""
        self.refresh_data()
        self.app.notify("Data refreshed", severity="information")

    def action_search(self) -> None:
        """Show the search bar and focus it."""
        self._show_search()



    def action_clear_filter(self) -> None:
        """Clear the search filter and hide the bar."""
        self._hide_search(preserve_filter=False)

    def action_log_filter_cycle(self) -> None:
        """Cycle the connection log quick-filter mode."""
        try:
            conn_log = self.query_one("#connection-log", ConnectionLog)
            conn_log.cycle_quick_filter()
            label = conn_log.quick_filter_label
            self.app.notify(f"Log filter: {label}", severity="information")
        except Exception:
            pass

    def action_proto_filter_cycle(self) -> None:
        """Cycle the port table protocol filter: ALL → TCP → UDP → ICMP → ALL."""
        try:
            port_table = self.query_one("#port-table", PortTable)
            proto_cycle = ["ALL", "TCP", "UDP", "ICMP"]
            current = port_table.filter_proto
            idx = proto_cycle.index(current) if current in proto_cycle else -1
            next_proto = proto_cycle[(idx + 1) % len(proto_cycle)]
            port_table.set_proto_filter(next_proto)
            self.app.notify(f"Protocol: {next_proto}", severity="information")
        except Exception:
            pass

    # ── Search bar helpers ────────────────────────────────────
    def _show_search(self) -> None:
        # Determine filter target from current focus
        focused = self.focused
        if focused is not None and getattr(focused, "id", None) == "connection-log":
            target = "connection-log"
            placeholder = "Filter ConnectionLog..."
        else:
            target = "port-table"
            placeholder = "Filter PortTable..."

        self._filter_target = target
        self._focus_before_search = focused
        self._search_visible = True

        try:
            search_input = self.query_one("#search-input", Input)
            search_input.placeholder = placeholder
            search_input.remove_class("hidden")
            search_input.focus()
        except Exception:
            pass

    def _hide_search(self, preserve_filter: bool = False) -> None:
        self._search_visible = False
        try:
            search_input = self.query_one("#search-input", Input)
            search_input.add_class("hidden")

            if not preserve_filter:
                search_input.value = ""
                # Clear filter on the target widget only
                if self._filter_target == "connection-log":
                    conn_log = self.query_one("#connection-log", ConnectionLog)
                    conn_log.set_filter("")
                elif self._filter_target == "port-table":
                    port_table = self.query_one("#port-table", PortTable)
                    port_table.clear_filter()

                try:
                    status_bar = self.query_one("#status-bar", StatusBar)
                    status_bar.set_filter_info("")
                except Exception:
                    pass
        except Exception:
            pass

        # Restore focus to the widget that was focused before search
        if self._focus_before_search is not None:
            try:
                self._focus_before_search.focus()
            except Exception:
                pass

        self._filter_target = ""
        self._focus_before_search = None

    def action_copy_row(self) -> None:
        """Copy the selected row's info to the system clipboard.

        Context-aware: copies from PortTable or ConnectionLog depending
        on which widget currently has focus.

        Y10: Wraps clipboard calls in try/except to handle Wayland/SSH/headless failures.
        """
        focused = self.focused
        try:
            if focused is not None and focused.id == "connection-log":
                conn_log = self.query_one("#connection-log", ConnectionLog)
                text = conn_log.get_plain_text()
                if text.strip():
                    self._safe_clipboard(text)
                else:
                    self.app.notify("Nothing to copy", severity="warning")
                return
        except Exception:
            pass

        # Default: copy from PortTable
        table = self.query_one(PortTable)
        try:
            if table.row_count > 0:
                cell_key = table.coordinate_to_cell_key((table.cursor_row, 0))
                entry = table._row_entries.get(cell_key.row_key.value)
                if entry:
                    addr = (f"{entry.local_ip}:{entry.local_port}" if entry.state == "LISTEN"
                            else f"{entry.local_ip}:{entry.local_port} -> {entry.remote_ip}:{entry.remote_port}")
                    text = f"{entry.process_name or 'unknown'} (PID: {entry.pid or '-'}) | {entry.proto} {addr} | State: {entry.state}"
                    self._safe_clipboard(text)
        except Exception as e:
            self.app.notify(f"Copy failed: {e}", severity="error")

    def _safe_clipboard(self, text: str) -> None:
        """Copy to clipboard with error handling for Wayland/SSH/headless envs."""
        try:
            self.app.copy_to_clipboard(text)
            self.app.notify("Copied to clipboard", severity="information")
        except Exception:
            self.app.notify(
                "Clipboard unavailable — install xclip, xsel, or wl-copy",
                severity="warning",
            )
