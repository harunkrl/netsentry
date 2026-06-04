"""NetSentry TUI — Status bar widget (bottom bar).

Displays a one-line summary: daemon health, security icon, counts, and key hints.
Uses ASCII-friendly symbols instead of emoji for terminal compatibility.
"""
from __future__ import annotations

import json
import os
import time
from typing import Dict, List, Optional

from textual.widgets import Static

from shared.constants import DATA_FILE


def _check_daemon_alive() -> bool:
    """Check if daemon is alive by reading the heartbeat file."""
    hb_path = os.path.join(os.path.dirname(DATA_FILE), "netsentry-heartbeat.json")
    try:
        with open(hb_path, "r") as fh:
            data = json.load(fh)
        ts = data.get("ts", 0)
        return (time.time() - ts) < 15.0  # alive if heartbeat < 15s old
    except (FileNotFoundError, json.JSONDecodeError, OSError, KeyError):
        return False


class StatusBar(Static):
    """Bottom status bar with daemon health, alert summary and keyboard hints."""

    def on_mount(self) -> None:
        self.update("[dim]... Waiting for data ...[/]")

    def show_daemon_down(self) -> None:
        """Show a warning that the daemon is not reachable."""
        self.update(
            "[bold red]x DAEMON OFFLINE[/]  |  "
            "[dim]Start: netsentry-daemon --foreground[/]  |  "
            "[q]uit [r]efresh"
        )

    def update_display(
        self,
        summary: Dict[str, int],
        alerts: List,
        daemon_alive: Optional[bool] = None,
    ) -> None:
        """Refresh the status bar content."""
        # Daemon health check
        if daemon_alive is None:
            daemon_alive = _check_daemon_alive()

        if not daemon_alive:
            daemon_indicator = "[bold red]x[/]"
        else:
            daemon_indicator = "[green]o[/]"

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
            f"{daemon_indicator} daemon  |  "
            f"{icon} {status}  |  "
            f"{listening} listening  |  "
            f"{established} established  |  "
            f"{alert_count} alerts  |  "
            f"[dim][q]uit [k]ill [r]efresh[/]"
        )
