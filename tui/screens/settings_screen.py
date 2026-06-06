"""KPortWatch TUI — Settings screen.

Professional settings panel with toggle switches. Changes auto-save
to ``~/.config/kportwatch/config.toml`` on every toggle.
Fully keyboard-navigable: Tab between rows, Enter/Space to toggle.

K2: Fixed text truncation — descriptions use word-wrap with sufficient width.
K9: Restart daemon runs in background thread — TUI no longer freezes.
K10: Uses standard ``.hidden`` CSS class consistently.
"""
from __future__ import annotations

import asyncio

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.containers import Vertical, Horizontal, Container
from textual.widgets import Label, Switch, Static, Button, TabbedContent, TabPane

from shared.config import save_config_setting

# Available themes (must match tui/themes.py)
AVAILABLE_THEMES = ["Cyberpunk", "Midnight", "Hacker"]


class SettingRow(Container):
    """A single toggleable setting row — focusable for keyboard navigation.

    Press Enter or Space to toggle the switch when the row is focused.
    """

    CSS = """
    SettingRow {
        layout: grid;
        grid-size: 2;
        grid-columns: 1fr 16;
        height: auto;
        padding: 1 2;
        border-bottom: solid #1a3a2a 80%;
    }
    SettingRow:focus {
        background: #0a2a1a;
        border: thick #00ff99 60%;
    }
    SettingRow:hover {
        background: #0a2a1a;
    }

    SettingRow > .setting-info {
        height: auto;
    }

    SettingRow > .setting-info > .setting-title {
        color: #00ff99;
        text-style: bold;
    }

    SettingRow > .setting-info > .setting-desc {
        color: #6a6a7a;
        margin-top: 1;
        text-wrap: wrap;
        width: 100%;
    }

    SettingRow > .setting-switch-container {
        height: 100%;
        padding: 0;
        content-align: right middle;
    }
    """

    BINDINGS = [
        Binding("enter", "toggle", "Toggle", show=False),
        Binding("space", "toggle", "Toggle", show=False),
    ]

    def __init__(
        self,
        key: str,
        section: str,
        title: str,
        description: str,
        value: bool,
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.key = key
        self.section = section
        self._title = title
        self._description = description
        self._value = value

    def compose(self) -> ComposeResult:
        with Vertical(classes="setting-info"):
            yield Label(self._title, classes="setting-title")
            yield Label(self._description, classes="setting-desc")
        with Vertical(classes="setting-switch-container"):
            yield Switch(value=self._value, id=f"switch-{self.key}")

    @property
    def switch(self) -> Switch:
        return self.query_one(f"#switch-{self.key}", Switch)

    def action_toggle(self) -> None:
        """Toggle the switch when Enter/Space is pressed on the row."""
        self.switch.toggle()


class SelectableRow(Container):
    """A selectable setting row with cycle-through values (e.g., theme selector).

    Press Enter or Space to cycle to the next value when the row is focused.
    """

    CSS = """
    SelectableRow {
        layout: grid;
        grid-size: 2;
        grid-columns: 1fr 20;
        height: auto;
        padding: 1 2;
        border-bottom: solid #1a3a2a 80%;
    }
    SelectableRow:focus {
        background: #0a2a1a;
        border: thick #00ff99 60%;
    }
    SelectableRow:hover {
        background: #0a2a1a;
    }

    SelectableRow > .setting-info {
        height: auto;
    }

    SelectableRow > .setting-info > .setting-title {
        color: #00ff99;
        text-style: bold;
    }

    SelectableRow > .setting-info > .setting-desc {
        color: #6a6a7a;
        margin-top: 1;
        text-wrap: wrap;
        width: 100%;
    }

    SelectableRow > .setting-value-container {
        height: 100%;
        padding: 0;
        content-align: right middle;
    }

    SelectableRow > .setting-value-container > .value-label {
        color: #00ff99;
        text-style: bold;
        background: #0a2a1a;
        padding: 0 2;
    }
    """

    BINDINGS = [
        Binding("enter", "cycle", "Cycle", show=False),
        Binding("space", "cycle", "Cycle", show=False),
    ]

    def __init__(
        self,
        key: str,
        section: str,
        title: str,
        description: str,
        value: str,
        options: list[str],
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self.key = key
        self.section = section
        self._title = title
        self._description = description
        self._value = value
        self._options = options

    def compose(self) -> ComposeResult:
        with Vertical(classes="setting-info"):
            yield Label(self._title, classes="setting-title")
            yield Label(self._description, classes="setting-desc")
        with Vertical(classes="setting-value-container"):
            yield Label(self._value, id=f"value-{self.key}", classes="value-label")

    def action_cycle(self) -> None:
        """Cycle to the next value."""
        if self._options:
            idx = self._options.index(self._value) if self._value in self._options else -1
            self._value = self._options[(idx + 1) % len(self._options)]
            self.query_one(f"#value-{self.key}", Label).update(self._value)
            # Notify parent
            self.post_message(self.ValueChanged(self.key, self.section, self._value))

    class ValueChanged:
        """Message sent when a selectable row's value changes."""
        def __init__(self, key: str, section: str, value: str):
            self.key = key
            self.section = section
            self.value = value


class SettingsScreen(ModalScreen[None]):
    """Modal settings screen with KPortWatch's dark-green theme.

    Manages daemon-level and TUI-level notification preferences, plus
    key daemon configuration knobs.  Changes are persisted to config.toml instantly.
    """

    CSS = """
    SettingsScreen {
        align: center middle;
    }

    #settings-dialog {
        width: 76;
        height: 28;
        max-width: 95%;
        max-height: 90%;
        background: #0d0d0d;
        border: round #008855;
        padding: 0;
    }

    #settings-header {
        height: 3;
        padding: 0 2;
        background: #008855;
        color: #000;
        text-style: bold;
        content-align: center middle;
    }

    #settings-body {
        height: 1fr;
        padding: 1 2;
    }



    #settings-footer {
        height: 3;
        padding: 0 2;
        color: #6a6a8a;
        align: center middle;
        border-top: solid #1a3a2a;
    }

    #settings-footer-text {
        width: 1fr;
        content-align: center middle;
    }

    .settings-action-btn {
        margin: 0 1;
        min-width: 18;
    }

    #settings-body ScrollBar {
        color: #00ff99;
    }
    #settings-body ScrollBar > .scrollbar--thumb {
        background: #008855;
    }
    """

    BINDINGS = [
        Binding("escape", "close", "Back", show=False),
        Binding("s", "close", "Back", show=False),
        Binding("q", "close", "Back", show=False),
    ]

    def __init__(
        self,
        desktop_notifications: bool,
        tui_notifications: bool,
        geoip_enabled: bool = True,
        burst_threshold: int = 3,
        scan_threshold: int = 5,
        current_theme: str = "Cyberpunk",
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._desktop_notifications = desktop_notifications
        self._tui_notifications = tui_notifications
        self._geoip_enabled = geoip_enabled
        self._burst_threshold = burst_threshold
        self._scan_threshold = scan_threshold
        self._current_theme = current_theme

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            yield Static("SETTINGS", id="settings-header")

            with Vertical(id="settings-body"):
                with TabbedContent(initial="tab-notifications"):
                    # Notifications Tab
                    with TabPane("Notifications", id="tab-notifications"):
                        yield SettingRow(
                            key="enabled",
                            section="notifications",
                            title="Alert Desktop Notifications",
                            description=(
                                "Show desktop notifications for daemon alerts "
                                "(notify-send). Applies to WARNING and CRITICAL alerts."
                            ),
                            value=self._desktop_notifications,
                        )
                        yield SettingRow(
                            key="tui_notifications_enabled",
                            section="tui",
                            title="Toast Notifications",
                            description=(
                                "Show pop-up notifications inside the TUI. "
                                "When disabled, all toast messages are suppressed."
                            ),
                            value=self._tui_notifications,
                        )

                    # Daemon Tab
                    with TabPane("Daemon", id="tab-daemon"):
                        yield SettingRow(
                            key="geoip_enabled",
                            section="geoip",
                            title="GeoIP Lookup",
                            description=(
                                "Resolve remote IP geolocation (country, city, org). "
                                "Disabling reduces network requests and latency."
                            ),
                            value=self._geoip_enabled,
                        )
                        yield SettingRow(
                            key="burst_threshold",
                            section="alerts",
                            title="Burst Alert Threshold",
                            description=(
                                f"Number of rapid connections to trigger a burst alert. "
                                f"Current: {self._burst_threshold}. Toggle to reset to default (3)."
                            ),
                            value=self._burst_threshold <= 3,
                        )

                    # Security Tab
                    with TabPane("Security", id="tab-security"):
                        yield SettingRow(
                            key="scan_threshold",
                            section="security",
                            title="Port Scan Detection",
                            description=(
                                f"Number of unique ports from one IP to flag as port scan. "
                                f"Current: {self._scan_threshold}. Toggle between 5 (sensitive) and 10 (relaxed)."
                            ),
                            value=self._scan_threshold <= 5,
                        )

                    # Appearance Tab
                    with TabPane("Appearance", id="tab-appearance"):
                        yield SelectableRow(
                            key="theme",
                            section="tui",
                            title="Color Theme",
                            description=(
                                "Select the TUI color scheme. Changes apply immediately. "
                                "Options: Cyberpunk (green neon), Midnight (cool blue), Hacker (classic green)."
                            ),
                            value=self._current_theme,
                            options=AVAILABLE_THEMES,
                        )

            yield Horizontal(
                Static("[dim]Tab: navigate  |  Enter/Space: toggle  |  Esc: close[/]", id="settings-footer-text"),
                Button("Restart Daemon", variant="warning", id="btn-restart-daemon", classes="settings-action-btn"),
                id="settings-footer",
            )

    def on_mount(self) -> None:
        """Auto-focus the first setting row on open."""
        try:
            self.query_one(SettingRow).focus()
        except Exception:
            pass

    def on_switch_changed(self, event: Switch.Changed) -> None:
        """Auto-save on every toggle change."""
        switch_id = event.switch.id or ""

        if switch_id == "switch-enabled":
            self._desktop_notifications = event.value
            self._save_and_sync(
                section="notifications",
                key="enabled",
                value=event.value,
            )

        elif switch_id == "switch-tui_notifications_enabled":
            self._tui_notifications = event.value
            self._save_and_sync(
                section="tui",
                key="tui_notifications_enabled",
                value=event.value,
            )
            # Update app-level flag immediately
            app = self.app
            if hasattr(app, "notifications_enabled"):
                app.notifications_enabled = event.value
            # Update status bar
            try:
                from tui.widgets.status_bar import StatusBar
                bar = app.query_one(StatusBar)
                bar.set_notification_state(event.value)
            except Exception:
                pass

        elif switch_id == "switch-geoip_enabled":
            self._geoip_enabled = event.value
            self._save_and_sync(
                section="geoip",
                key="geoip_enabled",
                value=event.value,
            )

        elif switch_id == "switch-burst_threshold":
            new_val = 3 if event.value else 5
            self._burst_threshold = new_val
            self._save_and_sync(
                section="alerts",
                key="burst_threshold",
                value=new_val,
            )

        elif switch_id == "switch-scan_threshold":
            new_val = 5 if event.value else 10
            self._scan_threshold = new_val
            self._save_and_sync(
                section="security",
                key="scan_threshold",
                value=new_val,
            )



    def _save_and_sync(self, section: str, key: str, value: bool) -> None:
        """Save to config.toml and reload daemon config if needed."""
        try:
            save_config_setting(section, key, value)
            self.app.notify("Setting saved", severity="information")
        except Exception:
            self.app.notify("Failed to save setting", severity="error")
            return

        # Reload config singleton so subsequent get_config() calls are fresh
        try:
            from shared.config import load_config
            load_config()
        except Exception:
            pass

        # Signal daemon to reload config (SIGHUP)
        if section != "tui":
            self._signal_daemon_reload()

    def _signal_daemon_reload(self) -> None:
        """Send SIGHUP to the daemon so it reloads config.toml.

        Tries the PID file first; falls back to finding daemon processes
        via ``/proc`` if the PID file is missing or empty.
        """
        import os
        import signal
        from shared.constants import PID_FILE

        sent = False

        # Attempt 1: PID file
        try:
            if os.path.isfile(PID_FILE):
                with open(PID_FILE) as f:
                    pid_str = f.read().strip()
                if pid_str:
                    os.kill(int(pid_str), signal.SIGHUP)
                    sent = True
        except (OSError, ValueError, ProcessLookupError):
            pass

        # Attempt 2: Find daemon PIDs via /proc (fallback)
        if not sent:
            try:
                import subprocess
                result = subprocess.run(
                    ["pgrep", "-f", "backend.kportwatch_daemon"],
                    capture_output=True, text=True, timeout=3,
                )
                if result.returncode == 0:
                    for line in result.stdout.strip().split("\n"):
                        line = line.strip()
                        if line.isdigit():
                            try:
                                os.kill(int(line), signal.SIGHUP)
                                sent = True
                            except (OSError, ProcessLookupError):
                                pass
            except Exception:
                pass

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-restart-daemon":
            # O13: Show confirmation before restarting daemon
            from textual.screen import ModalScreen
            from textual.widgets import Button as Btn
            from textual.containers import Vertical, Horizontal

            class ConfirmRestart(ModalScreen[bool]):
                CSS = """
                ConfirmRestart { align: center middle; }
                #confirm-box {
                    width: 50; height: auto;
                    border: round $warning;
                    background: $surface;
                    padding: 1 2;
                }
                """
                BINDINGS = [Binding("escape", "dismiss_false", show=False)]

                def compose(self) -> ComposeResult:
                    with Vertical(id="confirm-box"):
                        yield Label("[bold yellow]Restart Daemon?[/]")
                        yield Label("This will briefly interrupt monitoring.")
                        with Horizontal():
                            yield Btn("Yes, Restart", variant="warning", id="btn-yes")
                            yield Btn("Cancel", variant="default", id="btn-no")

                def on_button_pressed(self, event: Btn.Pressed) -> None:
                    self.dismiss(event.button.id == "btn-yes")

                def action_dismiss_false(self) -> None:
                    self.dismiss(False)

            def _on_confirm(restart: bool) -> None:
                if restart:
                    self._restart_daemon()

            self.app.push_screen(ConfirmRestart(), _on_confirm)

    @work(thread=True, exclusive=True)
    def _restart_daemon(self) -> None:
        """Restart the daemon in a background thread.

        K9 fix: Uses ``@work(thread=True)`` so the TUI stays responsive
        during the restart operation (previously blocked for up to 15s).
        """
        import subprocess
        import sys

        # Update button label on the main thread
        self.app.call_from_thread(self._set_restart_button_state, "Restarting...", disabled=True)

        try:
            result = subprocess.run(
                [sys.executable, "-m", "backend.kportwatchctl", "restart"],
                cwd=self._find_project_root(),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                self.app.call_from_thread(
                    self.app.notify, "Daemon restarted successfully", "information"
                )
                self.app.call_from_thread(self._set_restart_button_state, "✓ Restarted", disabled=False)
            else:
                self.app.call_from_thread(
                    self.app.notify, f"Restart failed: {result.stderr.strip()}", "error"
                )
                self.app.call_from_thread(self._set_restart_button_state, "Restart Daemon", disabled=False)
        except subprocess.TimeoutExpired:
            self.app.call_from_thread(
                self.app.notify, "Restart timed out", "error"
            )
            self.app.call_from_thread(self._set_restart_button_state, "Restart Daemon", disabled=False)
        except Exception as e:
            self.app.call_from_thread(
                self.app.notify, f"Error: {e}", "error"
            )
            self.app.call_from_thread(self._set_restart_button_state, "Restart Daemon", disabled=False)

    def _set_restart_button_state(self, label: str, *, disabled: bool) -> None:
        """Update the restart button label and disabled state (must run on main thread)."""
        try:
            btn = self.query_one("#btn-restart-daemon", Button)
            btn.label = label
            btn.disabled = disabled
        except Exception:
            pass

    @staticmethod
    def _find_project_root() -> str:
        import os
        d = os.path.dirname(os.path.abspath(__file__))
        while d != "/":
            if os.path.isfile(os.path.join(d, "pyproject.toml")):
                return d
            d = os.path.dirname(d)
        return os.getcwd()

    def on_selectable_row_value_changed(self, event: SelectableRow.ValueChanged) -> None:
        """Handle selectable row value changes (e.g., theme selector)."""
        if event.key == "theme":
            self._current_theme = event.value
            # Apply theme immediately
            try:
                from tui.themes import apply_theme_by_name
                apply_theme_by_name(self.app, event.value)
            except Exception:
                pass
            self._save_and_sync(
                section="tui",
                key="theme",
                value=event.value,
            )

    def action_close(self) -> None:
        self.dismiss(None)
