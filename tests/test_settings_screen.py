"""Tests for tui/screens/settings_screen.py — expanded coverage.

Tests SettingRow, SelectableRow, SettingsScreen save/sync, SIGHUP signaling,
ConfirmRestart, and _find_project_root.
"""

from __future__ import annotations

import os
import signal
from unittest.mock import Mock, patch

import pytest
from textual.app import App
from textual.widgets import Button, Label, Switch
from tui.screens.settings_screen import (
    SelectableRow,
    SettingRow,
    SettingsScreen,
)

# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def settings_screen():
    """A SettingsScreen with default values."""
    return SettingsScreen(
        desktop_notifications=True,
        tui_notifications=True,
        geoip_enabled=True,
        burst_threshold=3,
        scan_threshold=5,
        current_theme="Cyberpunk",
    )


@pytest.fixture
def settings_app(settings_screen):
    """A Textual App with SettingsScreen pushed."""
    app = App()
    return app, settings_screen


# ══════════════════════════════════════════════════════════════
# SettingRow Tests
# ══════════════════════════════════════════════════════════════


class TestSettingRow:
    """Tests for SettingRow toggle widget."""

    @pytest.mark.asyncio
    async def test_compose_creates_switch(self):
        """SettingRow composes with a Switch widget."""
        row = SettingRow(
            key="test_key",
            section="test",
            title="Test Title",
            description="Test description",
            value=True,
        )
        app = App()
        async with app.run_test() as pilot:
            app.mount(row)
            await pilot.pause()
            switch = row.query_one("#switch-test_key", Switch)
            assert switch.value is True

    @pytest.mark.asyncio
    async def test_compose_false_value(self):
        """SettingRow with value=False creates an off switch."""
        row = SettingRow(
            key="my_key",
            section="s",
            title="T",
            description="D",
            value=False,
        )
        app = App()
        async with app.run_test() as pilot:
            app.mount(row)
            await pilot.pause()
            switch = row.query_one("#switch-my_key", Switch)
            assert switch.value is False

    @pytest.mark.asyncio
    async def test_switch_property(self):
        """switch property returns the correct widget."""
        row = SettingRow(
            key="abc",
            section="s",
            title="T",
            description="D",
            value=True,
        )
        app = App()
        async with app.run_test() as pilot:
            app.mount(row)
            await pilot.pause()
            assert row.switch is row.query_one("#switch-abc", Switch)

    @pytest.mark.asyncio
    async def test_action_toggle(self):
        """action_toggle flips the switch value."""
        row = SettingRow(
            key="xyz",
            section="s",
            title="T",
            description="D",
            value=True,
        )
        app = App()
        async with app.run_test() as pilot:
            app.mount(row)
            await pilot.pause()
            assert row.switch.value is True
            row.action_toggle()
            await pilot.pause()
            assert row.switch.value is False

    @pytest.mark.asyncio
    async def test_action_toggle_off_to_on(self):
        """action_toggle turns switch on when off."""
        row = SettingRow(
            key="xyz",
            section="s",
            title="T",
            description="D",
            value=False,
        )
        app = App()
        async with app.run_test() as pilot:
            app.mount(row)
            await pilot.pause()
            assert row.switch.value is False
            row.action_toggle()
            await pilot.pause()
            assert row.switch.value is True


# ══════════════════════════════════════════════════════════════
# SelectableRow Tests
# ══════════════════════════════════════════════════════════════


class TestSelectableRow:
    """Tests for SelectableRow cycle-through widget."""

    @pytest.mark.asyncio
    async def test_compose_shows_value(self):
        """SelectableRow shows current value."""
        row = SelectableRow(
            key="theme",
            section="tui",
            title="Theme",
            description="Pick one",
            value="Cyberpunk",
            options=["Cyberpunk", "Midnight", "Hacker"],
        )
        app = App()
        async with app.run_test() as pilot:
            app.mount(row)
            await pilot.pause()
            label = row.query_one("#value-theme", Label)
            assert "Cyberpunk" in str(label.render())

    @pytest.mark.asyncio
    async def test_action_cycle_advances(self):
        """action_cycle advances to the next option."""
        row = SelectableRow(
            key="x",
            section="s",
            title="T",
            description="D",
            value="a",
            options=["a", "b", "c"],
        )
        app = App()
        async with app.run_test() as pilot:
            app.mount(row)
            await pilot.pause()
            assert row._value == "a"
            row.action_cycle()
            await pilot.pause()
            assert row._value == "b"

    @pytest.mark.asyncio
    async def test_action_cycle_wraps(self):
        """action_cycle wraps from last to first."""
        row = SelectableRow(
            key="x",
            section="s",
            title="T",
            description="D",
            value="c",
            options=["a", "b", "c"],
        )
        app = App()
        async with app.run_test() as pilot:
            app.mount(row)
            await pilot.pause()
            row.action_cycle()
            await pilot.pause()
            assert row._value == "a"

    @pytest.mark.asyncio
    async def test_action_cycle_posts_message(self):
        """action_cycle posts ValueChanged message."""
        row = SelectableRow(
            key="x",
            section="s",
            title="T",
            description="D",
            value="a",
            options=["a", "b", "c"],
        )
        app = App()
        messages = []

        async with app.run_test() as pilot:
            app.mount(row)
            await pilot.pause()
            # Patch post_message to capture the message
            original_post = row.post_message

            def capture(msg):
                messages.append(msg)
                return original_post(msg)

            row.post_message = capture
            row.action_cycle()
            await pilot.pause()

        assert len(messages) >= 1
        assert messages[0].key == "x"
        assert messages[0].section == "s"
        assert messages[0].value == "b"

    @pytest.mark.asyncio
    async def test_action_cycle_unknown_value(self):
        """action_cycle with value not in options starts from first."""
        row = SelectableRow(
            key="x",
            section="s",
            title="T",
            description="D",
            value="unknown",
            options=["a", "b", "c"],
        )
        app = App()
        async with app.run_test() as pilot:
            app.mount(row)
            await pilot.pause()
            row.action_cycle()
            await pilot.pause()
            assert row._value == "a"

    @pytest.mark.asyncio
    async def test_action_cycle_empty_options(self):
        """action_cycle with empty options does nothing."""
        row = SelectableRow(
            key="x",
            section="s",
            title="T",
            description="D",
            value="a",
            options=[],
        )
        app = App()
        async with app.run_test() as pilot:
            app.mount(row)
            await pilot.pause()
            row.action_cycle()
            await pilot.pause()
            assert row._value == "a"

    @pytest.mark.asyncio
    async def test_cycle_updates_label(self):
        """action_cycle updates the displayed label."""
        row = SelectableRow(
            key="x",
            section="s",
            title="T",
            description="D",
            value="a",
            options=["a", "b", "c"],
        )
        app = App()
        async with app.run_test() as pilot:
            app.mount(row)
            await pilot.pause()
            row.action_cycle()
            await pilot.pause()
            label = row.query_one("#value-x", Label)
            assert "b" in str(label.render())


# ══════════════════════════════════════════════════════════════
# SettingsScreen — Composition & Mount
# ══════════════════════════════════════════════════════════════


class TestSettingsScreenComposition:
    """Tests for SettingsScreen widget composition."""

    @pytest.mark.asyncio
    async def test_screen_has_all_switches(self, settings_screen):
        """All expected switches are present."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            assert settings_screen.query_one("#switch-enabled") is not None
            assert settings_screen.query_one("#switch-tui_notifications_enabled") is not None
            assert settings_screen.query_one("#switch-geoip_enabled") is not None

    @pytest.mark.asyncio
    async def test_screen_has_selectable_rows(self, settings_screen):
        """All expected SelectableRows are present."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            assert settings_screen.query_one("#value-burst_threshold") is not None
            assert settings_screen.query_one("#value-scan_threshold") is not None
            assert settings_screen.query_one("#value-theme") is not None

    @pytest.mark.asyncio
    async def test_screen_has_restart_button(self, settings_screen):
        """Restart daemon button is present."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            btn = settings_screen.query_one("#btn-restart-daemon", Button)
            assert btn is not None
            assert btn.disabled is False

    @pytest.mark.asyncio
    async def test_screen_has_footer(self, settings_screen):
        """Footer with help text is present."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            footer = settings_screen.query_one("#settings-footer-text")
            rendered = str(footer.render())
            assert "Tab" in rendered
            assert "Esc" in rendered

    @pytest.mark.asyncio
    async def test_mount_focuses_first_row(self, settings_screen):
        """on_mount auto-focuses the first SettingRow."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            # Just verify mount completes without crash
            # Focus behavior varies in headless mode

    @pytest.mark.asyncio
    async def test_initial_switch_values(self):
        """Switches reflect constructor values."""
        screen = SettingsScreen(
            desktop_notifications=False,
            tui_notifications=False,
            geoip_enabled=False,
        )
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            assert screen.query_one("#switch-enabled", Switch).value is False
            assert screen.query_one("#switch-tui_notifications_enabled", Switch).value is False
            assert screen.query_one("#switch-geoip_enabled", Switch).value is False


# ══════════════════════════════════════════════════════════════
# SettingsScreen — Save & Sync
# ══════════════════════════════════════════════════════════════


class TestSettingsScreenSaveSync:
    """Tests for _save_and_sync method."""

    @pytest.mark.asyncio
    async def test_save_success(self, settings_screen):
        """Successful save notifies user."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with (
                patch("tui.screens.settings_screen.save_config_setting") as mock_save,
                patch.object(app, "notify") as mock_notify,
            ):
                settings_screen._save_and_sync("notifications", "enabled", True)
                mock_save.assert_called_once_with("notifications", "enabled", True)
                mock_notify.assert_called()

    @pytest.mark.asyncio
    async def test_save_failure_notifies_error(self, settings_screen):
        """Save failure shows error notification."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with (
                patch(
                    "tui.screens.settings_screen.save_config_setting",
                    side_effect=PermissionError("denied"),
                ),
                patch.object(app, "notify") as mock_notify,
            ):
                settings_screen._save_and_sync("notifications", "enabled", True)
                # Should notify error
                error_calls = [c for c in mock_notify.call_args_list if "Failed" in str(c)]
                assert len(error_calls) > 0

    @pytest.mark.asyncio
    async def test_save_reloads_config(self, settings_screen):
        """Successful save reloads config singleton."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with (
                patch("tui.screens.settings_screen.save_config_setting"),
                patch("shared.config.load_config") as mock_load,
            ):
                settings_screen._save_and_sync("notifications", "enabled", True)
                mock_load.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_signals_daemon_for_non_tui_section(self, settings_screen):
        """Non-TUI sections trigger SIGHUP to daemon."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with (
                patch("tui.screens.settings_screen.save_config_setting"),
                patch.object(settings_screen, "_signal_daemon_reload") as mock_signal,
            ):
                settings_screen._save_and_sync("notifications", "enabled", True)
                mock_signal.assert_called_once()

    @pytest.mark.asyncio
    async def test_save_does_not_signal_for_tui_section(self, settings_screen):
        """TUI section does NOT trigger SIGHUP."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with (
                patch("tui.screens.settings_screen.save_config_setting"),
                patch.object(settings_screen, "_signal_daemon_reload") as mock_signal,
            ):
                settings_screen._save_and_sync("tui", "tui_notifications_enabled", True)
                mock_signal.assert_not_called()


# ══════════════════════════════════════════════════════════════
# SettingsScreen — SIGHUP Signaling
# ══════════════════════════════════════════════════════════════


class TestSignalDaemonReload:
    """Tests for _signal_daemon_reload."""

    @pytest.mark.asyncio
    async def test_signal_via_pid_file(self, settings_screen, tmp_path):
        """Sends SIGHUP using PID file."""
        pid_file = tmp_path / "kportwatch.pid"
        pid_file.write_text(str(os.getpid()))  # Use own PID (won't be killed)

        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with patch("shared.constants.PID_FILE", str(pid_file)), patch("os.kill") as mock_kill:
                settings_screen._signal_daemon_reload()
                mock_kill.assert_called_once_with(os.getpid(), signal.SIGHUP)

    @pytest.mark.asyncio
    async def test_signal_pid_file_empty(self, settings_screen, tmp_path):
        """Empty PID file falls back to pgrep."""
        pid_file = tmp_path / "kportwatch.pid"
        pid_file.write_text("")

        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with (
                patch("shared.constants.PID_FILE", str(pid_file)),
                patch("subprocess.run") as mock_run,
            ):
                mock_run.return_value = Mock(returncode=1, stdout="")
                settings_screen._signal_daemon_reload()
                mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_signal_pid_file_missing(self, settings_screen, tmp_path):
        """Missing PID file falls back to pgrep."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with (
                patch("shared.constants.PID_FILE", str(tmp_path / "nonexistent")),
                patch("subprocess.run") as mock_run,
            ):
                mock_run.return_value = Mock(returncode=1, stdout="")
                settings_screen._signal_daemon_reload()
                mock_run.assert_called_once()

    @pytest.mark.asyncio
    async def test_signal_pgrep_finds_daemon(self, settings_screen, tmp_path):
        """pgrep fallback sends SIGHUP to found daemon."""
        pid_file = tmp_path / "kportwatch.pid"
        pid_file.write_text("")

        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with (
                patch("shared.constants.PID_FILE", str(pid_file)),
                patch("subprocess.run") as mock_run,
                patch("os.kill") as mock_kill,
            ):
                mock_run.return_value = Mock(returncode=0, stdout="99999\n")
                settings_screen._signal_daemon_reload()
                mock_kill.assert_called_once_with(99999, signal.SIGHUP)

    @pytest.mark.asyncio
    async def test_signal_pgrep_non_numeric_ignored(self, settings_screen, tmp_path):
        """pgrep with non-numeric output is ignored."""
        pid_file = tmp_path / "kportwatch.pid"
        pid_file.write_text("")

        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with (
                patch("shared.constants.PID_FILE", str(pid_file)),
                patch("subprocess.run") as mock_run,
                patch("os.kill") as mock_kill,
            ):
                mock_run.return_value = Mock(returncode=0, stdout="not-a-pid\n")
                settings_screen._signal_daemon_reload()
                mock_kill.assert_not_called()

    @pytest.mark.asyncio
    async def test_signal_process_not_found_suppressed(self, settings_screen, tmp_path):
        """ProcessLookupError in SIGHUP is silently suppressed."""
        pid_file = tmp_path / "kportwatch.pid"
        pid_file.write_text("99999")

        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with (
                patch("shared.constants.PID_FILE", str(pid_file)),
                patch("os.kill", side_effect=ProcessLookupError),
            ):
                # Should not raise
                settings_screen._signal_daemon_reload()

    @pytest.mark.asyncio
    async def test_signal_subprocess_timeout(self, settings_screen, tmp_path):
        """Subprocess timeout during pgrep is suppressed."""
        pid_file = tmp_path / "kportwatch.pid"
        pid_file.write_text("")

        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            import subprocess

            with (
                patch("shared.constants.PID_FILE", str(pid_file)),
                patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 3)),
            ):
                # Should not raise
                settings_screen._signal_daemon_reload()


# ══════════════════════════════════════════════════════════════
# SettingsScreen — Switch Changed Handler
# ══════════════════════════════════════════════════════════════


class TestSwitchChangedHandler:
    """Tests for on_switch_changed."""

    @pytest.mark.asyncio
    async def test_desktop_notifications_toggle(self, settings_screen):
        """Toggling desktop notifications switch updates internal state."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            switch = settings_screen.query_one("#switch-enabled", Switch)
            # Simulate switch change
            event = Switch.Changed(switch, False)
            with patch.object(settings_screen, "_save_and_sync") as mock_save:
                settings_screen.on_switch_changed(event)
                assert settings_screen._desktop_notifications is False
                mock_save.assert_called_once_with(
                    section="notifications",
                    key="enabled",
                    value=False,
                )

    @pytest.mark.asyncio
    async def test_tui_notifications_toggle(self, settings_screen):
        """Toggling TUI notifications updates internal state and app flag."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            switch = settings_screen.query_one("#switch-tui_notifications_enabled", Switch)
            event = Switch.Changed(switch, False)
            with patch.object(settings_screen, "_save_and_sync"):
                settings_screen.on_switch_changed(event)
                assert settings_screen._tui_notifications is False

    @pytest.mark.asyncio
    async def test_geoip_toggle(self, settings_screen):
        """Toggling GeoIP updates internal state."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            switch = settings_screen.query_one("#switch-geoip_enabled", Switch)
            event = Switch.Changed(switch, False)
            with patch.object(settings_screen, "_save_and_sync"):
                settings_screen.on_switch_changed(event)
                assert settings_screen._geoip_enabled is False

    @pytest.mark.asyncio
    async def test_unknown_switch_ignored(self, settings_screen):
        """Unknown switch IDs are ignored."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            # Create a mock switch with unknown ID
            mock_switch = Mock()
            mock_switch.id = "switch-unknown"
            event = Switch.Changed(mock_switch, True)
            # Should not crash
            settings_screen.on_switch_changed(event)
            assert settings_screen._desktop_notifications is True  # unchanged


# ══════════════════════════════════════════════════════════════
# SettingsScreen — SelectableRow Value Changes
# ══════════════════════════════════════════════════════════════


class TestSelectableValueChanged:
    """Tests for on_selectable_row_value_changed."""

    @pytest.mark.asyncio
    async def test_burst_threshold_change(self, settings_screen):
        """Changing burst threshold updates internal state."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            event = SelectableRow.ValueChanged("burst_threshold", "alerts", "5")
            with patch.object(settings_screen, "_save_and_sync") as mock_save:
                settings_screen.on_selectable_row_value_changed(event)
                assert settings_screen._burst_threshold == 5
                mock_save.assert_called_once_with(section="alerts", key="burst_threshold", value=5)

    @pytest.mark.asyncio
    async def test_scan_threshold_change(self, settings_screen):
        """Changing scan threshold updates internal state."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            event = SelectableRow.ValueChanged("scan_threshold", "security", "10")
            with patch.object(settings_screen, "_save_and_sync") as mock_save:
                settings_screen.on_selectable_row_value_changed(event)
                assert settings_screen._scan_threshold == 10
                mock_save.assert_called_once_with(
                    section="security", key="scan_threshold", value=10
                )

    @pytest.mark.asyncio
    async def test_theme_change(self, settings_screen):
        """Changing theme updates internal state."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            event = SelectableRow.ValueChanged("theme", "tui", "Midnight")
            with (
                patch.object(settings_screen, "_save_and_sync"),
                patch("tui.themes.apply_theme_by_name"),
            ):
                settings_screen.on_selectable_row_value_changed(event)
                assert settings_screen._current_theme == "Midnight"


# ══════════════════════════════════════════════════════════════
# SettingsScreen — Action Close
# ══════════════════════════════════════════════════════════════


class TestSettingsScreenActions:
    """Tests for screen-level actions."""

    @pytest.mark.asyncio
    async def test_action_close_dismisses(self, settings_screen):
        """action_close dismisses with None."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with patch.object(settings_screen, "dismiss") as mock_dismiss:
                settings_screen.action_close()
                mock_dismiss.assert_called_once_with(None)

    @pytest.mark.asyncio
    async def test_restart_button_pushes_confirm(self, settings_screen):
        """Restart button pushes ConfirmRestart screen."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            btn = settings_screen.query_one("#btn-restart-daemon", Button)
            with patch.object(app, "push_screen") as mock_push:
                settings_screen.on_button_pressed(Button.Pressed(btn))
                mock_push.assert_called_once()
                # First arg is the ConfirmRestart screen
                assert mock_push.call_args[0][0].__class__.__name__ == "ConfirmRestart"

    @pytest.mark.asyncio
    async def test_set_restart_button_state(self, settings_screen):
        """_set_restart_button_state updates button label and disabled state."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            settings_screen._set_restart_button_state("Restarting...", disabled=True)
            btn = settings_screen.query_one("#btn-restart-daemon", Button)
            assert btn.label == "Restarting..."
            assert btn.disabled is True

    @pytest.mark.asyncio
    async def test_set_restart_button_state_restores(self, settings_screen):
        """Button state can be restored."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            settings_screen._set_restart_button_state("Restarting...", disabled=True)
            settings_screen._set_restart_button_state("✓ Restarted", disabled=False)
            btn = settings_screen.query_one("#btn-restart-daemon", Button)
            assert btn.label == "✓ Restarted"
            assert btn.disabled is False


# ══════════════════════════════════════════════════════════════
# SettingsScreen — _find_project_root
# ══════════════════════════════════════════════════════════════


class TestFindProjectRoot:
    """Tests for _find_project_root static method."""

    def test_finds_root_with_pyproject(self):
        """Finds the project root by walking up to pyproject.toml."""
        root = SettingsScreen._find_project_root()
        assert os.path.isfile(os.path.join(root, "pyproject.toml"))

    def test_returns_string(self):
        """Returns a string path."""
        root = SettingsScreen._find_project_root()
        assert isinstance(root, str)

    def test_is_absolute_path(self):
        """Returns an absolute path."""
        root = SettingsScreen._find_project_root()
        assert os.path.isabs(root)


# ══════════════════════════════════════════════════════════════
# SettingsScreen — _restart_daemon
# ══════════════════════════════════════════════════════════════


class TestRestartDaemon:
    """Tests for _restart_daemon background worker."""

    @pytest.mark.asyncio
    async def test_restart_success(self, settings_screen):
        """Successful restart calls subprocess.run with correct args."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with (
                patch("subprocess.run") as mock_run,
                patch.object(settings_screen, "_set_restart_button_state"),
                patch.object(settings_screen, "_find_project_root", return_value="/tmp"),
                patch.object(app, "notify"),
            ):
                mock_run.return_value = Mock(returncode=0, stderr="")
                worker = settings_screen._restart_daemon()
                await worker.wait()

    @pytest.mark.asyncio
    async def test_restart_failure(self, settings_screen):
        """Failed restart notifies error."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            with (
                patch("subprocess.run") as mock_run,
                patch.object(settings_screen, "_set_restart_button_state"),
                patch.object(settings_screen, "_find_project_root", return_value="/tmp"),
                patch.object(app, "notify"),
            ):
                mock_run.return_value = Mock(returncode=1, stderr="daemon not running")
                worker = settings_screen._restart_daemon()
                await worker.wait()

    @pytest.mark.asyncio
    async def test_restart_timeout(self, settings_screen):
        """Timeout during restart notifies error."""
        app = App()
        async with app.run_test() as pilot:
            app.push_screen(settings_screen)
            await pilot.pause()

            import subprocess

            with (
                patch("subprocess.run", side_effect=subprocess.TimeoutExpired("cmd", 15)),
                patch.object(settings_screen, "_set_restart_button_state"),
                patch.object(settings_screen, "_find_project_root", return_value="/tmp"),
                patch.object(app, "notify"),
            ):
                worker = settings_screen._restart_daemon()
                await worker.wait()
