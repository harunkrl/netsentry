from textual.app import ComposeResult
from textual.screen import Screen
from textual.containers import VerticalScroll
from textual.widgets import Header, Footer, Label, Static

from backend.models import SocketEntry

class DetailScreen(Screen):
    """Screen displaying full details of a specific connection."""

    BINDINGS = [("escape", "app.pop_screen", "Back")]

    def __init__(self, entry: SocketEntry, **kwargs) -> None:
        super().__init__(**kwargs)
        self.entry = entry

    def compose(self) -> ComposeResult:
        yield Header()
        with VerticalScroll():
            proc = self.entry.process_name or "unknown"
            pid = self.entry.pid if self.entry.pid else "—"
            cmdline = self.entry.cmdline or "—"
            
            yield Label(f"[bold]Process:[/] {proc} (PID: {pid})")
            yield Label(f"[bold]Command Line:[/] {cmdline}")
            yield Label(f"[bold]User ID:[/] {self.entry.uid}")
            yield Label(f"[bold]Protocol:[/] {self.entry.proto.upper()}")
            yield Label(f"[bold]State:[/] {self.entry.state}")
            yield Label(f"[bold]Local:[/] {self.entry.local_ip}:{self.entry.local_port}")
            yield Label(f"[bold]Remote:[/] {self.entry.remote_ip}:{self.entry.remote_port}")
            if self.entry.remote_hostname:
                yield Label(f"[bold]Hostname:[/] {self.entry.remote_hostname}")
            yield Label(f"[bold]Inode:[/] {self.entry.inode}")
        yield Footer()
