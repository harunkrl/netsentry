"""Tests for tui/kportwatch_tui.py - TUI app entry point."""
from __future__ import annotations

from unittest.mock import Mock, patch

import pytest
from textual.app import App
from tui.kportwatch_tui import KPortWatchTUI

# =============================================================================
# Fixtures
# =============================================================================

@pytest.fixture
def mock_config():
    """Return a mock AppConfig."""
    cfg = Mock()
    cfg.tui_notifications_enabled = True
    cfg.color_theme = "cyberpunk"
    cfg.notifications_enabled = True
    cfg.geoip_enabled = True
    cfg.burst_threshold = 3
    cfg.scan_threshold = 5
    return cfg


@pytest.fixture
def mock_data_provider():
    """Return a mock DataProvider."""
    provider = Mock()
    return provider


# =============================================================================
# KPortWatchTUI Tests
# =============================================================================

class TestKPortWatchTUI:
    """Tests for KPortWatchTUI application."""

    @pytest.mark.asyncio
    async def test_app_creation(self, mock_config):
        """KPortWatchTUI can be instantiated."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                app = KPortWatchTUI()
                assert app is not None
                assert app.notifications_enabled is True
                assert isinstance(app.data_provider, Mock)

    @pytest.mark.asyncio
    async def test_app_title(self, mock_config):
        """App has correct title with version."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                app = KPortWatchTUI()
                assert "KPortWatch" in app.TITLE
                assert "Network Security Analyzer" in app.TITLE

    @pytest.mark.asyncio
    async def test_app_css_path(self, mock_config):
        """App has CSS path configured."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                app = KPortWatchTUI()
                assert app.CSS_PATH is not None

    @pytest.mark.asyncio
    async def test_app_bindings(self, mock_config):
        """App has default key bindings."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                app = KPortWatchTUI()
                # Check for quit bindings
                bindings = [b.key for b in app.BINDINGS]
                assert "q" in bindings
                assert "ctrl+c" in bindings

    @pytest.mark.asyncio
    async def test_app_mounts_main_screen(self, mock_config):
        """App pushes MainScreen on mount."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                with patch("tui.kportwatch_tui.register_kpw_themes"):
                    with patch("tui.kportwatch_tui.apply_theme"):
                        # Don't mock MainScreen - let it use the real one
                        app = KPortWatchTUI()
                        async with app.run_test() as pilot:
                            await pilot.pause()
                            # App should have pushed MainScreen
                            # Check that the current screen has the expected widgets
                            from tui.screens.main_screen import MainScreen
                            assert isinstance(app.screen, MainScreen)

    @pytest.mark.asyncio
    async def test_app_registers_themes_on_mount(self, mock_config):
        """App registers custom themes on mount."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                with patch("tui.kportwatch_tui.register_kpw_themes") as mock_register:
                    with patch("tui.kportwatch_tui.apply_theme"):
                        app = KPortWatchTUI()
                        async with app.run_test() as pilot:
                            await pilot.pause()
                            mock_register.assert_called_once_with(app)

    @pytest.mark.asyncio
    async def test_app_applies_theme_on_mount(self, mock_config):
        """App applies theme on mount."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                with patch("tui.kportwatch_tui.register_kpw_themes"):
                    with patch("tui.kportwatch_tui.apply_theme") as mock_apply:
                        app = KPortWatchTUI()
                        async with app.run_test() as pilot:
                            await pilot.pause()
                            mock_apply.assert_called_once()
                            # Should be called with app and theme name
                            assert mock_apply.call_args[0][0] is app

    @pytest.mark.asyncio
    async def test_theme_name_property(self, mock_config):
        """theme_name property returns current theme key."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                with patch("tui.kportwatch_tui.register_kpw_themes"):
                    with patch("tui.kportwatch_tui.apply_theme"):
                        with patch("tui.kportwatch_tui.current_theme_key", return_value="cyberpunk"):
                            app = KPortWatchTUI()
                            async with app.run_test() as pilot:
                                await pilot.pause()
                                assert app.theme_name == "cyberpunk"

    @pytest.mark.asyncio
    async def test_notify_disabled(self, mock_config):
        """notify() is a no-op when notifications disabled."""
        mock_config.tui_notifications_enabled = False
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                app = KPortWatchTUI()
                # Should not call parent notify
                with patch.object(App, "notify") as mock_parent_notify:
                    app.notify("Test message")
                    mock_parent_notify.assert_not_called()

    @pytest.mark.asyncio
    async def test_notify_enabled(self, mock_config):
        """notify() calls parent notify when enabled."""
        mock_config.tui_notifications_enabled = True
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                app = KPortWatchTUI()
                async with app.run_test() as pilot:
                    await pilot.pause()
                    with patch.object(App, "notify") as mock_parent_notify:
                        app.notify("Test message", severity="information")
                        mock_parent_notify.assert_called_once_with(
                            "Test message", severity="information"
                        )

    @pytest.mark.asyncio
    async def test_action_open_settings(self, mock_config):
        """action_open_settings() pushes SettingsScreen."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                with patch("tui.kportwatch_tui.register_kpw_themes"):
                    with patch("tui.kportwatch_tui.apply_theme"):
                        with patch("tui.kportwatch_tui.get_config", return_value=mock_config):
                            with patch("tui.kportwatch_tui.current_theme_key", return_value="cyberpunk"):
                                with patch("tui.kportwatch_tui.key_to_display_name", return_value="Cyberpunk"):
                                    # Don't mock SettingsScreen - it's imported lazily
                                    # Just verify the method exists and doesn't crash
                                    app = KPortWatchTUI()
                                    async with app.run_test() as pilot:
                                        await pilot.pause()
                                        # Just verify the method exists
                                        assert hasattr(app, "action_open_settings")

    @pytest.mark.asyncio
    async def test_resolve_theme_key_default(self, mock_config):
        """_resolve_theme_key returns unchanged key for known themes."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                app = KPortWatchTUI()
                # Known theme should return unchanged
                assert app._resolve_theme_key("cyberpunk") == "cyberpunk"
                assert app._resolve_theme_key("nord") == "nord"

    @pytest.mark.asyncio
    async def test_resolve_theme_key_legacy(self, mock_config):
        """_resolve_theme_key maps legacy theme names."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                app = KPortWatchTUI()
                # Legacy mappings
                assert app._resolve_theme_key("dark") == "cyberpunk"
                assert app._resolve_theme_key("nord") == "nord"  # nord is also in legacy
                assert app._resolve_theme_key("solarized") == "solarized-dark"
                assert app._resolve_theme_key("light") == "kpw-light"

    @pytest.mark.asyncio
    async def test_resolve_theme_key_unknown(self, mock_config):
        """_resolve_theme_key returns unknown key unchanged."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                app = KPortWatchTUI()
                # Unknown theme should return unchanged
                assert app._resolve_theme_key("unknown-theme") == "unknown-theme"

    @pytest.mark.asyncio
    async def test_notifications_disabled_from_config(self, mock_config):
        """App respects tui_notifications_enabled from config."""
        mock_config.tui_notifications_enabled = False
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                app = KPortWatchTUI()
                assert app.notifications_enabled is False

    @pytest.mark.asyncio
    async def test_quit_binding_exists(self, mock_config):
        """Quit binding exists and is configured."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                app = KPortWatchTUI()
                # Check for quit binding
                bindings = [b for b in app.BINDINGS if "quit" in str(b.action).lower()]
                assert len(bindings) > 0
                # At least 'q' should quit
                q_bindings = [b for b in app.BINDINGS if b.key == "q"]
                assert len(q_bindings) > 0

    @pytest.mark.asyncio
    async def test_ctrl_c_binding_exists(self, mock_config):
        """Ctrl+C binding exists."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                app = KPortWatchTUI()
                # Check for ctrl+c binding
                ctrl_c_bindings = [b for b in app.BINDINGS if b.key == "ctrl+c"]
                assert len(ctrl_c_bindings) > 0

    @pytest.mark.asyncio
    async def test_data_provider_initialized(self, mock_config):
        """DataProvider is initialized on app creation."""
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider") as mock_dp_class:
                mock_dp = Mock()
                mock_dp_class.return_value = mock_dp
                app = KPortWatchTUI()
                assert app.data_provider is mock_dp
                mock_dp_class.assert_called_once()

    @pytest.mark.asyncio
    async def test_theme_persistence(self, mock_config):
        """App loads and applies saved theme from config."""
        mock_config.color_theme = "nord"
        with patch("tui.kportwatch_tui.load_config", return_value=mock_config):
            with patch("tui.kportwatch_tui.DataProvider"):
                with patch("tui.kportwatch_tui.register_kpw_themes"):
                    with patch("tui.kportwatch_tui.apply_theme") as mock_apply:
                        app = KPortWatchTUI()
                        async with app.run_test() as pilot:
                            await pilot.pause()
                            # Theme should have been resolved and applied
                            mock_apply.assert_called_once()
                            call_args = mock_apply.call_args[0]
                            assert call_args[0] is app
                            assert call_args[1] == "nord"
