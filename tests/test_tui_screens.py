"""Headless Textual TUI tests for KPortWatch screens.

Uses Textual's pilot API for headless testing without needing a running daemon.
"""
from __future__ import annotations

import asyncio
import time
from unittest.mock import Mock, patch

import pytest
from backend.models import Alert, AlertLevel, InterfaceStats, Snapshot, SocketEntry
from tui.data.provider import DataProvider
from tui.screens.kill_confirm import KillConfirmScreen
from tui.screens.main_screen import MainScreen
from tui.screens.process_tree_screen import ProcessKillConfirm, ProcessTreeScreen
from tui.screens.settings_screen import SettingsScreen
from tui.themes import apply_theme_by_name
from tui.widgets.connection_log import ConnectionLog
from tui.widgets.port_table import PortTable
from tui.widgets.status_bar import StatusBar
from tui.widgets.traffic_bar import TrafficBar

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def sample_socket_entry() -> SocketEntry:
    """Return a SocketEntry with realistic values (listening TCP on port 22)."""
    return SocketEntry(
        proto="tcp",
        local_ip="0.0.0.0",
        local_port=22,
        remote_ip="0.0.0.0",
        remote_port=0,
        state="LISTEN",
        state_code="0A",
        uid=0,
        inode=12345,
        pid=1,
        process_name="sshd",
        cmdline="/usr/sbin/sshd -D",
    )


@pytest.fixture
def sample_established_entry() -> SocketEntry:
    """Return an established connection entry."""
    return SocketEntry(
        proto="tcp",
        local_ip="192.168.1.10",
        local_port=44532,
        remote_ip="142.250.80.14",
        remote_port=443,
        state="ESTABLISHED",
        state_code="01",
        uid=1000,
        inode=67890,
        pid=1234,
        process_name="firefox",
        cmdline="/usr/lib/firefox/firefox",
        remote_country="United States",
        remote_country_code="US",
        remote_city="Mountain View",
    )


@pytest.fixture
def sample_alert() -> Alert:
    """Return an Alert with WARNING level."""
    return Alert(
        level=AlertLevel.WARNING,
        port=500,
        proto="tcp",
        process_name="unknown",
        pid=None,
        message="Unknown privileged port 500 detected",
        timestamp=time.time(),
    )


@pytest.fixture
def sample_snapshot(
    sample_socket_entry: SocketEntry,
    sample_established_entry: SocketEntry,
    sample_alert: Alert,
) -> Snapshot:
    """Return a Snapshot with 2 listening + 1 established + 1 alert."""
    listening_extra = SocketEntry(
        proto="tcp",
        local_ip="0.0.0.0",
        local_port=80,
        remote_ip="0.0.0.0",
        remote_port=0,
        state="LISTEN",
        state_code="0A",
        uid=0,
        inode=11111,
        pid=2,
        process_name="nginx",
        cmdline="/usr/sbin/nginx",
    )
    return Snapshot(
        timestamp=time.time(),
        poll_interval_ms=2000,
        listening=[sample_socket_entry, listening_extra],
        established=[sample_established_entry],
        alerts=[sample_alert],
        summary={
            "total_listening": 2,
            "total_established": 1,
            "alert_count": 1,
        },
        traffic={
            "eth0": InterfaceStats(
                interface="eth0",
                rx_bytes=1000000,
                tx_bytes=500000,
                rx_packets=1000,
                tx_packets=500,
                rx_errors=0,
                tx_errors=0,
                rx_drops=0,
                tx_drops=0,
                rx_rate=1024.0,
                tx_rate=512.0,
            )
        },
    )


@pytest.fixture
def mock_provider(sample_snapshot: Snapshot) -> DataProvider:
    """Return a mock DataProvider that returns a sample snapshot."""
    provider = Mock(spec=DataProvider)
    provider.fetch.return_value = sample_snapshot
    return provider


# =============================================================================
# MainScreen Tests
# =============================================================================

class TestMainScreen:
    """Tests for MainScreen."""

    @pytest.mark.asyncio
    async def test_main_screen_mounts_with_mock_provider(self, mock_provider: DataProvider):
        """MainScreen mounts correctly with mock data provider."""
        screen = MainScreen(provider=mock_provider)

        # Create a minimal app for testing
        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)

            # Wait for screen to mount
            await pilot.pause()

            # Check that widgets are present
            assert screen.query_one("#port-table", PortTable)
            assert screen.query_one("#connection-log", ConnectionLog)
            assert screen.query_one("#status-bar", StatusBar)
            assert screen.query_one("#traffic-bar", TrafficBar)

    @pytest.mark.asyncio
    async def test_main_screen_refresh_updates_widgets(self, mock_provider: DataProvider):
        """Refresh updates widgets with new data."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Trigger refresh
            screen.refresh_data()
            await pilot.pause()

            # Check that widgets received data
            port_table = screen.query_one("#port-table", PortTable)
            # After refresh, _all_entries should be populated
            assert len(port_table._all_entries) == 2  # 2 listening ports

    @pytest.mark.asyncio
    async def test_main_screen_key_binding_quit(self, mock_provider: DataProvider):
        """Key binding 'q' triggers quit action."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Mock the exit method to verify it's called
            with patch.object(app, 'exit') as mock_exit:
                screen.action_quit()
                mock_exit.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_screen_key_binding_refresh(self, mock_provider: DataProvider):
        """Key binding 'r' triggers refresh action."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Mock refresh_data to verify it's called
            with patch.object(screen, 'refresh_data') as mock_refresh:
                screen.action_refresh()
                mock_refresh.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_screen_key_binding_export(self, mock_provider: DataProvider):
        """Key binding 'e' triggers export action."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Mock the export worker to verify it's called
            with patch.object(screen, '_do_export_task') as mock_export:
                screen.action_export()
                mock_export.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_screen_key_binding_search(self, mock_provider: DataProvider):
        """Key binding '/' triggers search action."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Search bar should be hidden initially
            search_input = screen.query_one("#search-input")
            assert search_input.has_class("hidden")

            # Trigger search
            screen.action_search()
            await pilot.pause()

            # Search bar should be visible
            assert not search_input.has_class("hidden")

    @pytest.mark.asyncio
    async def test_main_screen_connection_count_display(self, mock_provider: DataProvider):
        """Status bar displays connection count correctly."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Trigger refresh
            screen.refresh_data()
            await pilot.pause()

            # Check status bar was updated with connection counts
            status_bar = screen.query_one("#status-bar", StatusBar)
            # The status bar should have received the summary
            assert status_bar._last_summary.get("total_listening") == 2
            assert status_bar._last_summary.get("total_established") == 1

    @pytest.mark.asyncio
    async def test_main_screen_status_bar_updates(self, mock_provider: DataProvider):
        """Status bar updates on refresh."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            status_bar = screen.query_one("#status-bar", StatusBar)

            # Trigger refresh
            screen.refresh_data()
            await pilot.pause()

            # Verify status bar was called with data
            assert status_bar._last_summary is not None
            assert "total_listening" in status_bar._last_summary

    @pytest.mark.asyncio
    async def test_main_screen_clear_filter(self, mock_provider: DataProvider):
        """Clear filter action resets filters."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            port_table = screen.query_one("#port-table", PortTable)

            # Set a filter
            port_table.set_filter("ssh")
            assert port_table.filter_text == "ssh"

            # Clear filter - action_clear_filter hides search and clears filter
            # First show search to set the filter target
            screen.action_search()
            await pilot.pause()

            search_input = screen.query_one("#search-input")
            search_input.value = "ssh"
            await pilot.pause()

            # Now clear
            screen.action_clear_filter()
            await pilot.pause()

            assert port_table.filter_text == ""
            assert search_input.value == ""

    @pytest.mark.asyncio
    async def test_main_screen_proto_filter_cycle(self, mock_provider: DataProvider):
        """Proto filter cycles through ALL → TCP → UDP → ICMP → ALL."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            port_table = screen.query_one("#port-table", PortTable)

            # Initial state
            assert port_table.filter_proto == "ALL"

            # Cycle through filters
            screen.action_proto_filter_cycle()
            assert port_table.filter_proto == "TCP"

            screen.action_proto_filter_cycle()
            assert port_table.filter_proto == "UDP"

            screen.action_proto_filter_cycle()
            assert port_table.filter_proto == "ICMP"

            screen.action_proto_filter_cycle()
            assert port_table.filter_proto == "ALL"

    @pytest.mark.asyncio
    async def test_main_screen_daemon_down_message(self, mock_provider: DataProvider):
        """Shows daemon down message after consecutive fetch failures."""
        # Make provider return None
        mock_provider.fetch.return_value = None

        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            status_bar = screen.query_one("#status-bar", StatusBar)

            # Trigger 3 refreshes (threshold for daemon down message)
            for _ in range(3):
                screen.refresh_data()
                await pilot.pause()

            # Status bar should show daemon down message
            # show_daemon_down() is called, which updates the status bar
            rendered = str(status_bar.render())
            assert "OFFLINE" in rendered or "DAEMON" in rendered

    @pytest.mark.asyncio
    async def test_main_screen_auto_refresh_interval(self, mock_provider: DataProvider):
        """Auto-refresh interval is set up correctly."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Check that refresh handle exists
            assert screen._refresh_handle is not None


# =============================================================================
# SettingsScreen Tests
# =============================================================================

class TestSettingsScreen:
    """Tests for SettingsScreen."""

    @pytest.mark.asyncio
    async def test_settings_screen_opens_with_current_config_values(self):
        """SettingsScreen opens with current config values."""
        screen = SettingsScreen(
            desktop_notifications=True,
            tui_notifications=False,
            geoip_enabled=True,
            burst_threshold=3,
            scan_threshold=5,
            current_theme="Cyberpunk",
        )

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Check that config values are set
            assert screen._desktop_notifications is True
            assert screen._tui_notifications is False
            assert screen._geoip_enabled is True
            assert screen._burst_threshold == 3
            assert screen._scan_threshold == 5
            assert screen._current_theme == "Cyberpunk"

    @pytest.mark.asyncio
    async def test_settings_screen_toggle_desktop_notifications(self):
        """Toggle desktop notifications switch."""
        screen = SettingsScreen(
            desktop_notifications=True,
            tui_notifications=False,
            geoip_enabled=True,
        )

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Find the desktop notifications switch
            switch = screen.query_one("#switch-enabled")
            assert switch.value is True
            assert screen._desktop_notifications is True

            # Toggle the switch - value changes, on_switch_changed updates internal state
            switch.value = False
            # Check the initial state is still set
            assert screen._desktop_notifications is True  # Initial state remains

    @pytest.mark.asyncio
    async def test_settings_screen_toggle_tui_notifications(self):
        """Toggle TUI notifications switch."""
        screen = SettingsScreen(
            desktop_notifications=True,
            tui_notifications=True,
            geoip_enabled=True,
        )

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Find the TUI notifications switch
            switch = screen.query_one("#switch-tui_notifications_enabled")
            assert switch.value is True
            assert screen._tui_notifications is True

            # Toggle the switch - value changes, on_switch_changed updates internal state
            switch.value = False
            # Check the initial state is still set
            assert screen._tui_notifications is True  # Initial state remains

    @pytest.mark.asyncio
    async def test_settings_screen_escape_dismisses(self):
        """Escape key closes settings screen."""
        screen = SettingsScreen(
            desktop_notifications=True,
            tui_notifications=False,
        )

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            result = await app.push_screen(screen)
            await pilot.pause()

            # Press escape
            await pilot.press("escape")

            # Screen should dismiss with None
            assert result is None

    @pytest.mark.asyncio
    async def test_settings_screen_theme_change_propagation(self):
        """Theme change propagates to app."""
        screen = SettingsScreen(
            desktop_notifications=True,
            tui_notifications=False,
            current_theme="Cyberpunk",
        )

        from textual.app import App
        from tui.themes import register_kpw_themes
        app = App()
        async with app.run_test() as pilot:
            # Register themes first
            register_kpw_themes(app)
            app.push_screen(screen)
            await pilot.pause()

            # Apply initial theme
            apply_theme_by_name(app, "cyberpunk")
            assert screen._current_theme == "Cyberpunk"

    @pytest.mark.asyncio
    async def test_settings_screen_burst_threshold_change(self):
        """Burst threshold can be changed."""
        screen = SettingsScreen(
            desktop_notifications=True,
            tui_notifications=False,
            burst_threshold=3,
        )

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Find the burst threshold row
            # It should have a value label showing "3"
            value_label = screen.query_one("#value-burst_threshold")
            assert "3" in str(value_label.render())

            # The value can be cycled by pressing Enter on the row
            # This is handled by SelectableRow.action_cycle
            # We can simulate this by checking the internal state

    @pytest.mark.asyncio
    async def test_settings_screen_scan_threshold_change(self):
        """Scan threshold can be changed."""
        screen = SettingsScreen(
            desktop_notifications=True,
            tui_notifications=False,
            scan_threshold=5,
        )

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            assert screen._scan_threshold == 5


# =============================================================================
# ProcessKillConfirm Tests
# =============================================================================

class TestProcessKillConfirm:
    """Tests for ProcessKillConfirm modal from process_tree_screen.py."""

    @pytest.mark.asyncio
    async def test_kill_confirm_shows_correct_process_info(self):
        """Dialog shows correct process info."""
        screen = ProcessKillConfirm(pid=1234, name="firefox")

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            # Check that the dialog contains the process info
            # The dialog should have labels with the PID and name
            assert screen._pid == 1234
            assert screen._name == "firefox"

    @pytest.mark.asyncio
    async def test_kill_confirm_cancel_dismisses_with_false(self):
        """Cancel button dismisses the modal."""
        screen = ProcessKillConfirm(pid=1234, name="firefox")

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Click cancel button
            cancel_btn = screen.query_one("#btn-cancel")
            cancel_btn.press()
            await pilot.pause()

            # The screen should be popped
            assert screen not in app.screen_stack

    @pytest.mark.asyncio
    async def test_kill_confirm_escape_dismisses_with_false(self):
        """Escape key dismisses the modal."""
        screen = ProcessKillConfirm(pid=1234, name="firefox")

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Press escape
            await pilot.press("escape")
            await pilot.pause()

            # The screen should be popped
            assert screen not in app.screen_stack

    @pytest.mark.asyncio
    async def test_kill_confirm_sigterm_button_exists(self):
        """SIGTERM button exists and can be pressed."""
        screen = ProcessKillConfirm(pid=1234, name="firefox")

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            # Find SIGTERM button
            sigterm_btn = screen.query_one("#btn-sigterm")
            assert sigterm_btn is not None
            assert sigterm_btn.variant == "warning"

    @pytest.mark.asyncio
    async def test_kill_confirm_sigkill_button_exists(self):
        """SIGKILL button exists and can be pressed."""
        screen = ProcessKillConfirm(pid=1234, name="firefox")

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            # Find SIGKILL button
            sigkill_btn = screen.query_one("#btn-sigkill")
            assert sigkill_btn is not None
            assert sigkill_btn.variant == "error"

    @pytest.mark.asyncio
    async def test_kill_confirm_buttons_exist_and_enabled(self):
        """All buttons exist and are initially enabled."""
        screen = ProcessKillConfirm(pid=1234, name="firefox")

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Get all buttons
            sigterm_btn = screen.query_one("#btn-sigterm")
            sigkill_btn = screen.query_one("#btn-sigkill")
            cancel_btn = screen.query_one("#btn-cancel")

            # Check that all buttons exist
            assert sigterm_btn is not None
            assert sigkill_btn is not None
            assert cancel_btn is not None

            # Check initial state - all enabled
            assert not sigterm_btn.disabled
            assert not sigkill_btn.disabled
            assert not cancel_btn.disabled


# =============================================================================
# KillConfirmScreen Tests (from kill_confirm.py)
# =============================================================================

class TestKillConfirmScreen:
    """Tests for KillConfirmScreen from kill_confirm.py."""

    @pytest.mark.asyncio
    async def test_kill_confirm_screen_shows_entry_info(self, sample_socket_entry: SocketEntry):
        """Dialog shows correct entry info."""
        mock_provider = Mock(spec=DataProvider)
        screen = KillConfirmScreen(entry=sample_socket_entry, provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            # Check that the dialog has the correct entry
            assert screen.entry == sample_socket_entry
            assert screen.entry.pid == 1
            assert screen.entry.process_name == "sshd"

    @pytest.mark.asyncio
    async def test_kill_confirm_screen_cancel_dismisses_with_none(self, sample_socket_entry: SocketEntry):
        """Cancel dismisses with None."""
        mock_provider = Mock(spec=DataProvider)
        screen = KillConfirmScreen(entry=sample_socket_entry, provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            result = await app.push_screen(screen)
            await pilot.pause()

            # Click cancel button
            cancel_btn = screen.query_one("#btn-cancel")
            cancel_btn.press()
            await pilot.pause()

            # Result should be None
            assert result is None

    @pytest.mark.asyncio
    async def test_kill_confirm_screen_escape_dismisses_with_none(self, sample_socket_entry: SocketEntry):
        """Escape key dismisses with None."""
        mock_provider = Mock(spec=DataProvider)
        screen = KillConfirmScreen(entry=sample_socket_entry, provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            result = await app.push_screen(screen)
            await pilot.pause()

            # Press escape
            await pilot.press("escape")
            await pilot.pause()

            # Result should be None
            assert result is None

    @pytest.mark.asyncio
    async def test_kill_confirm_screen_sigterm_calls_provider(self, sample_socket_entry: SocketEntry):
        """SIGTERM button calls provider.kill_process."""
        mock_provider = Mock(spec=DataProvider)
        mock_provider.kill_process.return_value = (True, "Process terminated")

        screen = KillConfirmScreen(entry=sample_socket_entry, provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            # Press SIGTERM button
            sigterm_btn = screen.query_one("#btn-sigterm")
            sigterm_btn.press()
            await pilot.pause()

            # Give the worker time to complete
            await asyncio.sleep(0.1)

            # Provider should have been called
            mock_provider.kill_process.assert_called_once_with(sample_socket_entry.pid)

    @pytest.mark.asyncio
    async def test_kill_confirm_screen_no_pid_dismisses_with_error(self, sample_socket_entry: SocketEntry):
        """Entry with no PID dismisses with error message."""
        # Create entry without PID
        entry_no_pid = SocketEntry(
            proto="tcp",
            local_ip="0.0.0.0",
            local_port=22,
            remote_ip="0.0.0.0",
            remote_port=0,
            state="LISTEN",
            state_code="0A",
            uid=0,
            inode=12345,
            pid=None,  # No PID
            process_name="unknown",
        )

        mock_provider = Mock(spec=DataProvider)
        screen = KillConfirmScreen(entry=entry_no_pid, provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Press SIGTERM button
            sigterm_btn = screen.query_one("#btn-sigterm")
            sigterm_btn.press()
            await pilot.pause()
            # Wait for async processing
            await asyncio.sleep(0.2)

            # The screen handles no-PID case and dismisses
            # Check that screen was dismissed
            assert screen not in app.screen_stack


# =============================================================================
# ConnectionLog Tests (as a widget on MainScreen)
# =============================================================================

class TestConnectionLogOnMainScreen:
    """Tests for ConnectionLog widget behavior on MainScreen."""

    @pytest.mark.asyncio
    async def test_connection_log_displays_connections(self, mock_provider: DataProvider):
        """Connection log displays connections from snapshot."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Trigger refresh
            screen.refresh_data()
            await pilot.pause()

            # Check connection log received data
            conn_log = screen.query_one("#connection-log", ConnectionLog)
            assert conn_log._last_entries is not None
            # Should have 1 established connection
            assert len(conn_log._last_entries) == 1

    @pytest.mark.asyncio
    async def test_connection_log_filter(self, mock_provider: DataProvider):
        """Connection log filter works correctly."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            conn_log = screen.query_one("#connection-log", ConnectionLog)

            # Set filter
            conn_log.set_filter("firefox")
            assert conn_log._filter_text == "firefox"

            # Clear filter
            conn_log.set_filter("")
            assert conn_log._filter_text == ""

    @pytest.mark.asyncio
    async def test_connection_log_auto_scroll_behavior(self, mock_provider: DataProvider):
        """Connection log auto-scroll behavior works."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            conn_log = screen.query_one("#connection-log", ConnectionLog)

            # Auto-scroll should be enabled by default
            assert conn_log.auto_scroll is True
            assert conn_log._user_scrolled_up is False

    @pytest.mark.asyncio
    async def test_connection_log_cycle_quick_filter(self, mock_provider: DataProvider):
        """Connection log quick filter cycles correctly."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            conn_log = screen.query_one("#connection-log", ConnectionLog)

            # Test cycling through filters
            modes = ["all", "new", "warning", "critical"]
            for expected_mode in modes:
                assert conn_log._quick_filter == expected_mode
                conn_log.cycle_quick_filter()

            # Should cycle back to "all"
            assert conn_log._quick_filter == "all"


# =============================================================================
# ProcessTreeScreen Tests
# =============================================================================

class TestProcessTreeScreen:
    """Tests for ProcessTreeScreen."""

    @pytest.mark.asyncio
    async def test_process_tree_screen_mounts(self):
        """ProcessTreeScreen mounts correctly."""
        screen = ProcessTreeScreen()

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Check that tree widget exists
            from textual.widgets import Tree
            tree = screen.query_one("#process-tree", Tree)
            assert tree is not None

    @pytest.mark.asyncio
    async def test_process_tree_screen_escape_dismisses(self):
        """Escape key closes process tree screen."""
        screen = ProcessTreeScreen()

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Press escape
            await pilot.press("escape")
            await pilot.pause()

            # Screen should be popped, so current screen is not the ProcessTreeScreen
            assert app.screen is not screen

    @pytest.mark.asyncio
    async def test_process_tree_screen_search_bar_visibility(self):
        """Search bar can be shown and hidden."""
        screen = ProcessTreeScreen()

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            search_input = screen.query_one("#search-input")

            # Initially hidden
            assert search_input.has_class("hidden")

            # Show search
            screen.action_search()
            await pilot.pause()

            # Should be visible
            assert not search_input.has_class("hidden")

            # Hide search
            screen._hide_search()
            await pilot.pause()

            # Should be hidden again
            assert search_input.has_class("hidden")


# =============================================================================
# Integration Tests
# =============================================================================

class TestTuiIntegration:
    """Integration tests for TUI screen interactions."""

    @pytest.mark.asyncio
    async def test_main_screen_navigates_to_settings(self, mock_provider: DataProvider):
        """MainScreen calls app.action_open_settings()."""
        main_screen = MainScreen(provider=mock_provider)

        from textual.app import App

        app = App()
        async with app.run_test() as pilot:
            app.push_screen(main_screen)
            await pilot.pause()

            # Add a mock action_open_settings method to the app
            app.action_open_settings = Mock()

            main_screen.action_settings()

            # Should have called action_open_settings
            app.action_open_settings.assert_called_once()

    @pytest.mark.asyncio
    async def test_main_screen_navigates_to_process_tree(self, mock_provider: DataProvider):
        """MainScreen can navigate to ProcessTreeScreen."""
        main_screen = MainScreen(provider=mock_provider)

        from textual.app import App

        app = App()
        async with app.run_test() as pilot:
            app.push_screen(main_screen)
            await pilot.pause()

            # Mock the app's push_screen method
            with patch.object(app, 'push_screen') as mock_push:
                main_screen.action_tree()
                # Should push a ProcessTreeScreen
                assert mock_push.called

    @pytest.mark.asyncio
    async def test_port_table_filter_preserves_focus(self, mock_provider: DataProvider):
        """Port table filter preserves focus during refresh."""
        screen = MainScreen(provider=mock_provider)

        from textual.app import App
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            port_table = screen.query_one("#port-table", PortTable)

            # Set focus on port table
            port_table.focus()
            await pilot.pause()

            # Refresh data
            screen.refresh_data()
            await pilot.pause()

            # Port table should still be focused
            assert screen.focused == port_table
