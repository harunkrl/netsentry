"""KPortWatch TUI — Kill confirmation modal screen.

Presents a dialog with process details and three action buttons:
SIGTERM (graceful), SIGKILL (force), Cancel.

K8: Handles PermissionError and ProcessLookupError gracefully.
K12: Escape key binding to close the modal.
K11: Kill operations run in background threads to avoid blocking.
"""
from __future__ import annotations

import asyncio
import os
import signal as sig
from typing import Optional

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import ModalScreen
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label, Static

from backend.models import SocketEntry


class KillConfirmScreen(ModalScreen[Optional[tuple[bool, str]]]):
    """Modal dialog asking the user to confirm process termination.

    Supports Escape to close, and proper error handling for kill
    operations (PermissionError, ProcessLookupError).
    """

    CSS = """
    KillConfirmScreen {
        align: center middle;
    }
    #kill-dialog {
        width: 64;
        max-width: 80;
        height: auto;
        border: round $primary;
        background: $surface;
        padding: 1 2;
    }
    #kill-dialog Label {
        margin: 0 0 1 0;
    }
    #kill-buttons {
        height: auto;
        margin: 1 0 0 0;
    }
    #kill-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(
        self,
        entry: SocketEntry,
        provider,   # DataProvider — avoid circular import
        name: str | None = None,
        id: str | None = None,
        classes: str | None = None,
    ) -> None:
        super().__init__(name=name, id=id, classes=classes)
        self.entry = entry
        self.provider = provider

    def compose(self) -> ComposeResult:
        proc = self.entry.process_name or "unknown"
        pid = self.entry.pid or "—"
        addr = f"{self.entry.local_ip}:{self.entry.local_port}"
        proto = self.entry.proto.upper()
        cmdline = self.entry.cmdline or "—"

        with Vertical(id="kill-dialog"):
            yield Label("[bold red]⚠  Kill Process[/]")
            yield Static(f"  Process : [bold]{proc}[/]")
            yield Static(f"  PID     : [bold]{pid}[/]")
            yield Static(f"  Port    : [bold]{addr}[/]")
            yield Static(f"  Proto   : [bold]{proto}[/]")
            yield Static(f"  Cmdline : [dim]{cmdline}[/]")
            yield Label("")
            with Horizontal(id="kill-buttons"):
                yield Button("SIGTERM (graceful)", variant="warning", id="btn-sigterm")
                yield Button("SIGKILL (force)", variant="error", id="btn-sigkill")
                yield Button("Cancel", variant="default", id="btn-cancel")

    # ── Actions ───────────────────────────────────────────────
    def action_cancel(self) -> None:
        """Close the modal without taking action (Escape key)."""
        self.dismiss(None)

    # ── Button handlers ───────────────────────────────────────
    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id

        if btn_id == "btn-cancel":
            self.dismiss(None)
            return

        if self.entry.pid is None:
            self.dismiss((False, "No PID associated with this entry"))
            return

        # Disable all buttons to prevent double-click
        self._set_buttons_enabled(False)

        if btn_id == "btn-sigterm":
            self.app.run_worker(self._do_kill_graceful, exclusive=True)
        elif btn_id == "btn-sigkill":
            self.app.run_worker(self._do_kill_force, exclusive=True)

    def _set_buttons_enabled(self, enabled: bool) -> None:
        """Enable or disable all action buttons."""
        for btn in self.query(Button):
            btn.disabled = not enabled

    # ── Async kill workers (non-blocking) ─────────────────────
    async def _do_kill_graceful(self) -> None:
        """Run SIGTERM→SIGKILL escalation in a thread to avoid blocking the TUI."""
        success, msg = await asyncio.to_thread(self.provider.kill_process, self.entry.pid)
        self._safe_dismiss((success, msg))

    async def _do_kill_force(self) -> None:
        """Run SIGKILL in a thread to avoid blocking the TUI.

        Handles PermissionError and ProcessLookupError gracefully (K8).
        """
        def _kill() -> tuple[bool, str]:
            try:
                os.kill(self.entry.pid, sig.SIGKILL)
                return True, f"Process {self.entry.pid} force-killed (SIGKILL)"
            except ProcessLookupError:
                return False, f"Process {self.entry.pid} not found — may have already terminated"
            except PermissionError:
                return False, f"Permission denied — cannot kill PID {self.entry.pid}. Try running with elevated privileges."
            except OSError as e:
                return False, f"Failed to kill PID {self.entry.pid}: {e}"

        success, msg = await asyncio.to_thread(_kill)
        self._safe_dismiss((success, msg))

    def _safe_dismiss(self, result: Optional[tuple[bool, str]]) -> None:
        """Dismiss the modal, guarding against the screen already being popped.

        If the user quit while the kill worker was running, the screen may
        no longer be on the stack. Catching ScreenError prevents a crash.
        """
        try:
            self.dismiss(result)
        except Exception:
            pass  # Screen already removed from stack
