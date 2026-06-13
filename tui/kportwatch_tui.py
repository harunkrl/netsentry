#!/usr/bin/env python3
"""KPortWatch TUI — Terminal User Interface entry point.

Launch with:  python3 tui/kportwatch_tui.py
"""

from __future__ import annotations

import os
import sys
import warnings
from pathlib import Path

# Ensure the project root is on sys.path
_PROJECT_ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if _PROJECT_ROOT not in sys.path:
    sys.path.insert(0, _PROJECT_ROOT)

warnings.filterwarnings(
    "ignore",
    message=r"coroutine '.*set_title.*' was never awaited",
    category=RuntimeWarning,
)

from shared.config import get_config, load_config  # noqa: E402
from shared.constants import APP_VERSION as VERSION  # noqa: E402
from textual.app import App  # noqa: E402
from textual.binding import Binding  # noqa: E402

from tui.data.provider import DataProvider  # noqa: E402
from tui.screens.main_screen import MainScreen  # noqa: E402
from tui.themes import (  # noqa: E402
    DEFAULT_THEME,
    KPW_THEMES,
    THEME_DISPLAY_MAP,
    apply_theme,
    current_theme_key,
    key_to_display_name,
    register_kpw_themes,
)

_TCSS_DIR = Path(__file__).parent / "styles.tcss"


class KPortWatchTUI(App):
    """Textual application for network security monitoring."""

    TITLE = f"KPortWatch {VERSION} — Network Security Analyzer"

    CSS_PATH = _TCSS_DIR

    BINDINGS = [
        Binding("q", "quit", "Quit", show=True),
        Binding("ctrl+c", "quit", "Quit", show=False),
    ]

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        cfg = load_config()
        self.notifications_enabled: bool = cfg.tui_notifications_enabled
        self.data_provider = DataProvider()
        # Resolve saved theme key — may be old key name
        self._theme_name: str = self._resolve_theme_key(getattr(cfg, "color_theme", DEFAULT_THEME))

    @staticmethod
    def _resolve_theme_key(key: str) -> str:
        """Resolve a theme key, handling old names gracefully."""
        # Old → new mapping
        legacy_map = {
            "dark": "cyberpunk",
            "nord": "nord",
            "solarized": "solarized-dark",
            "light": "kpw-light",
        }
        return (
            legacy_map.get(key, key)
            if key not in KPW_THEMES and key not in THEME_DISPLAY_MAP.values()
            else key
        )

    def on_mount(self) -> None:
        """Register custom themes and apply the persisted theme."""
        register_kpw_themes(self)
        apply_theme(self, self._theme_name)
        self.push_screen(MainScreen(provider=self.data_provider))

    @property
    def theme_name(self) -> str:
        return current_theme_key(self)

    def notify(self, message: str = "", *, severity: str = "information", **kwargs) -> None:
        if not self.notifications_enabled:
            return
        super().notify(message, severity=severity, **kwargs)

    def action_open_settings(self) -> None:
        from tui.screens.settings_screen import SettingsScreen

        cfg = get_config()
        theme_display = key_to_display_name(current_theme_key(self))
        self.push_screen(
            SettingsScreen(
                desktop_notifications=cfg.notifications_enabled,
                tui_notifications=self.notifications_enabled,
                geoip_enabled=getattr(cfg, "geoip_enabled", True),
                burst_threshold=getattr(cfg, "burst_threshold", 3),
                scan_threshold=getattr(cfg, "scan_threshold", 5),
                current_theme=theme_display,
            )
        )


def main() -> None:
    app = KPortWatchTUI()
    app.run()


if __name__ == "__main__":
    main()
