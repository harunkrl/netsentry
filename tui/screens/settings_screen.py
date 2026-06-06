"""NetSentry TUI — Settings screen.

Professional settings panel with toggle switches. Changes auto-save
to ``~/.config/netsentry/config.toml`` on every toggle.
Fully keyboard-navigable: Tab between rows, Enter/Space to toggle.
"""
from __future__ import annotations

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.containers import Vertical, VerticalScroll, Horizontal
from textual.widgets import Label, Switch, Static, Button

from shared.config import save_config_setting


class SettingRow(Horizontal):
    """A single toggleable setting row — focusable for keyboard navigation.

    Press Enter or Space to toggle the switch when the row is focused.
    """

    CSS = """
    SettingRow {
        height: auto;
        min-height: 5;
        padding: 1 3;
        border-bottom: solid #1a3a2a 80%;
        focusable: true;
    }
    SettingRow:focus {
        background: #0a2a1a;
        border: thick #00ff99 60%;
    }
    SettingRow:hover {
        background: #0a2a1a;
    }

    .setting-info {
        width: 1fr;
        padding: 1 0;
    }

    .setting-title {
        color: #00ff99;
        text-style: bold;
    }

    .setting-desc {
        color: #6a6a7a;
        margin-top: 1;
    }

    .setting-switch-container {
        width: auto;
        align: center middle;
        padding: 0 1;
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


class SettingsScreen(ModalScreen[None]):
    """Modal settings screen with NetSentry's dark-green theme.

    Manages both daemon-level (desktop) and TUI-level (toast) notification
    preferences.  Changes are persisted to config.toml instantly.
    """

    CSS = """
    SettingsScreen {
        align: center middle;
    }

    #settings-dialog {
        width: 76;
        max-width: 92%;
        height: auto;
        max-height: 85%;
        background: #0d0d0d;
        border: thick #00ff99;
        padding: 0;
    }

    #settings-header {
        dock: top;
        height: 3;
        padding: 0 3;
        background: #00ff99;
        color: #000;
        text-style: bold;
        content-align: center middle;
    }

    .settings-section-label {
        dock: top;
        height: 1;
        padding: 1 3 0 3;
        color: #008855;
        text-style: bold;
    }

    #settings-body {
        height: auto;
        max-height: 22;
        padding: 0 1;
    }

    #settings-footer {
        dock: bottom;
        height: 3;
        padding: 0 2;
        color: #6a6a8a;
        align: center middle;
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
        **kwargs,
    ) -> None:
        super().__init__(**kwargs)
        self._desktop_notifications = desktop_notifications
        self._tui_notifications = tui_notifications

    def compose(self) -> ComposeResult:
        with Vertical(id="settings-dialog"):
            yield Static("SETTINGS", id="settings-header")

            yield Label("Desktop Notifications", classes="settings-section-label")
            with VerticalScroll(id="settings-body"):
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

            yield Label("TUI Notifications", classes="settings-section-label")
            with VerticalScroll(id="settings-body-tui"):
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
        """Send SIGHUP to the daemon so it reloads config.toml."""
        import os
        import signal
        from shared.constants import PID_FILE
        try:
            if os.path.isfile(PID_FILE):
                with open(PID_FILE) as f:
                    pid = int(f.read().strip())
                os.kill(pid, signal.SIGHUP)
        except (OSError, ValueError, ProcessLookupError):
            pass  # daemon may not be running

    def on_button_pressed(self, event: Button.Pressed) -> None:
        """Handle button presses."""
        if event.button.id == "btn-restart-daemon":
            self._restart_daemon()

    def _restart_daemon(self) -> None:
        """Restart the daemon and show feedback."""
        import subprocess
        import sys

        btn = self.query_one("#btn-restart-daemon", Button)
        btn.label = "Restarting..."
        btn.disabled = True

        try:
            result = subprocess.run(
                [sys.executable, "-m", "backend.netsentryctl", "restart"],
                cwd=self._find_project_root(),
                capture_output=True,
                text=True,
                timeout=15,
            )
            if result.returncode == 0:
                self.app.notify("Daemon restarted successfully", severity="information")
                btn.label = "✓ Restarted"
            else:
                self.app.notify(f"Restart failed: {result.stderr.strip()}", severity="error")
                btn.label = "Restart Daemon"
                btn.disabled = False
        except subprocess.TimeoutExpired:
            self.app.notify("Restart timed out", severity="error")
            btn.label = "Restart Daemon"
            btn.disabled = False
        except Exception as e:
            self.app.notify(f"Error: {e}", severity="error")
            btn.label = "Restart Daemon"
            btn.disabled = False

    @staticmethod
    def _find_project_root() -> str:
        import os
        d = os.path.dirname(os.path.abspath(__file__))
        while d != "/":
            if os.path.isfile(os.path.join(d, "pyproject.toml")):
                return d
            d = os.path.dirname(d)
        return os.getcwd()

    def action_close(self) -> None:
        self.dismiss(None)
