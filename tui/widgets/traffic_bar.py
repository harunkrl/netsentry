"""NetSentry TUI — Traffic statistics bar widget.

Displays per-interface network traffic rates (RX/TX) in a compact
horizontal bar. Data comes from the Snapshot's traffic dict, which
is populated by the daemon from /proc/net/dev.

Example rendering:
    wlan0  ↓ 2.4 MB/s  ↑ 340 KB/s  |  Total: ↓ 1.4 GB  ↑ 202 MB
"""
from __future__ import annotations

from typing import Dict

from textual.widgets import Static

from backend.models import InterfaceStats


def _human_bytes(n: float) -> str:
    """Convert bytes to a human-readable string (KB, MB, GB, etc.)."""
    if n < 1024:
        return f"{n:.0f} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MB"
    return f"{n / (1024 * 1024 * 1024):.1f} GB"


class TrafficBar(Static):
    """Compact bar showing per-interface traffic rates and cumulative totals."""

    def on_mount(self) -> None:
        self.update("[dim]Traffic: waiting for data...[/]")

    def update_data(self, traffic: Dict[str, InterfaceStats]) -> None:
        """Refresh the traffic bar with new interface stats.

        Args:
            traffic: Dict of {interface_name: InterfaceStats}.
        """
        if not traffic:
            self.update("[dim]Traffic: no interfaces[/]")
            return

        segments: list[str] = []
        for name, stats in sorted(traffic.items()):
            rx_rate = _human_bytes(stats.rx_rate)
            tx_rate = _human_bytes(stats.tx_rate)
            rx_total = _human_bytes(stats.rx_bytes)
            tx_total = _human_bytes(stats.tx_bytes)

            segments.append(
                f"[bold]{name}[/]  "
                f"[green]↓ {rx_rate}/s[/]  "
                f"[cyan]↑ {tx_rate}/s[/]  "
                f"[dim]Total: ↓ {rx_total}  ↑ {tx_total}[/]"
            )

        self.update("  |  ".join(segments))
