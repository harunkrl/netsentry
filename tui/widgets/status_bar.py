"""NetSentry TUI — Status bar widget (bottom bar).

Displays a one-line summary: security icon, counts, and key hints.
Uses ASCII-friendly symbols instead of emoji for terminal compatibility.
"""
from __future__ import annotations

from typing import Dict, List

from textual.widgets import Static


class StatusBar(Static):
    """Bottom status bar with alert summary and keyboard hints."""

    def on_mount(self) -> None:
        self.update("[dim]... Waiting for data ...[/]")

    def show_daemon_down(self) -> None:
        """Show a warning that the daemon is not reachable."""
        self.update(
            "[bold yellow]![/yellow][/bold]  "
            "[bold red]Daemon not running[/]  |  "
            "[dim]Start with: netsentry-daemon --foreground[/]  |  "
            "[q]uit [r]efresh"
        )

    def update_display(self, summary: Dict[str, int], alerts: List) -> None:
        """Refresh the status bar content."""
        listening = summary.get("total_listening", 0)
        established = summary.get("total_established", 0)
        alert_count = summary.get("alert_count", len(alerts))

        # Icon based on alert severity (ASCII-friendly)
        if alert_count == 0:
            icon = "[green]*[/]"
            status = "Secure"
        else:
            has_critical = any(
                getattr(a, "level", "") == "CRITICAL" for a in alerts
            )
            if has_critical:
                icon = "[bold red]![/]"
                status = "[bold red]CRITICAL[/]"
            else:
                icon = "[yellow]?[/]"
                status = "[yellow]Warning[/]"

        self.update(
            f"{icon} {status}  |  "
            f"{listening} listening  |  "
            f"{established} established  |  "
            f"{alert_count} alerts  |  "
            f"[dim][q]uit [k]ill [r]efresh[/]"
        )
