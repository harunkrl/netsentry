"""NetSentry TUI — Kill confirmation modal screen.

Presents a dialog with process details and three action buttons:
SIGTERM (graceful), SIGKILL (force), Cancel.
"""
from __future__ import annotations

import asyncio
import os
import signal as sig
import sys
from typing import Optional

from textual.app import ComposeResult
from textual.screen import ModalScreen
from textual.containers import Horizontal, Vertical
from textual.widgets import Button, Label, Static

# Ensure project root is importable
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))

from backend.models import SocketEntry


class KillConfirmScreen(ModalScreen[Optional[tuple[bool, str]]]):
    """Modal dialog asking the user to confirm process termination."""

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

        with Vertical(id="kill-dialog"):
            yield Label("[bold red]⚠  Kill Process[/]")
            yield Static(f"  Process : [bold]{proc}[/]")
            yield Static(f"  PID     : [bold]{pid}[/]")
            yield Static(f"  Port    : [bold]{addr}[/]")
            yield Static(f"  Proto   : [bold]{proto}[/]")
            yield Label("")
            with Horizontal(id="kill-buttons"):
                yield Button("SIGTERM (graceful)", variant="warning", id="btn-sigterm")
                yield Button("SIGKILL (force)", variant="error", id="btn-sigkill")
                yield Button("Cancel", variant="default", id="btn-cancel")

    # ── Button handlers ───────────────────────────────────────
    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id

        if btn_id == "btn-cancel":
            self.dismiss(None)
            return

        if self.entry.pid is None:
            self.dismiss((False, "No PID associated with this entry"))
            return

        if btn_id == "btn-sigterm":
            self.app.run_worker(self._do_kill_graceful, exclusive=True)
        elif btn_id == "btn-sigkill":
            self.app.run_worker(self._do_kill_force, exclusive=True)

    # ── Async kill workers (non-blocking) ─────────────────────
    async def _do_kill_graceful(self) -> None:
        """Run SIGTERM→SIGKILL escalation in a thread to avoid blocking the TUI."""
        success, msg = await asyncio.to_thread(self.provider.kill_process, self.entry.pid)
        self.dismiss((success, msg))

    async def _do_kill_force(self) -> None:
        """Run SIGKILL in a thread to avoid blocking the TUI."""
        def _kill() -> tuple[bool, str]:
            try:
                os.kill(self.entry.pid, sig.SIGKILL)
                return True, f"Process {self.entry.pid} force-killed (SIGKILL)"
            except ProcessLookupError:
                return False, f"Process {self.entry.pid} not found"
            except PermissionError:
                return False, f"Permission denied — cannot kill PID {self.entry.pid}"
        success, msg = await asyncio.to_thread(_kill)
        self.dismiss((success, msg))
