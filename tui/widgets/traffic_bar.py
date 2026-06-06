"""NetSentry TUI — Traffic statistics bar widget.

Displays per-interface network traffic rates (RX/TX) with sparkline
history graphs in a compact horizontal bar.  Data comes from the
Snapshot's traffic dict, populated by the daemon from /proc/net/dev.

O14: Sparkline history for RX/TX rates (last 20 samples).
O10: Interface IP address display.
O15: IEC binary prefixes (KiB/MiB/GiB).
"""
from __future__ import annotations

from collections import deque
from typing import Dict

from textual.widgets import Static

from backend.models import InterfaceStats

# Maximum sparkline data points
_MAX_HISTORY = 20


def _get_interface_ip(iface: str) -> str:
    """Get the IPv4 address for a network interface."""
    try:
        import socket, struct, fcntl
        s = socket.socket(socket.AF_INET, socket.SOCK_DGRAM)
        try:
            result = fcntl.ioctl(
                s.fileno(), 0x8915,  # SIOCGIFADDR
                struct.pack('256s', iface.encode()[:15]),
            )
            return socket.inet_ntoa(result[20:24])
        finally:
            s.close()
    except Exception:
        return ""


def _human_bytes(n: float) -> str:
    """Convert bytes to human-readable string (IEC binary prefixes)."""
    if n < 1024:
        return f"{n:.0f} B"
    if n < 1024 * 1024:
        return f"{n / 1024:.1f} KiB"
    if n < 1024 * 1024 * 1024:
        return f"{n / (1024 * 1024):.1f} MiB"
    return f"{n / (1024 * 1024 * 1024):.1f} GiB"


def _mini_sparkline(data: deque[float], color: str) -> str:
    """Render a tiny text-mode sparkline from recent data points.

    Uses Unicode block characters for smooth visualisation.
    Returns a Rich markup string.
    """
    if len(data) < 2:
        return ""

    values = list(data)
    max_val = max(values) if max(values) > 0 else 1

    # Unicode block chars for 8 levels of brightness
    blocks = "▁▂▃▄▅▆▇█"
    chars = []
    for v in values:
        idx = min(int((v / max_val) * (len(blocks) - 1)), len(blocks) - 1)
        chars.append(blocks[idx])

    return f"[{color}]{'' . join(chars)}[/]"


class TrafficBar(Static):
    """Compact bar showing per-interface traffic rates, totals, and sparkline.

    O14: Maintains a ``deque`` of the last 20 RX/TX rate samples per
    interface and renders a tiny sparkline graph using Unicode block chars.
    """

    def __init__(self, **kwargs) -> None:
        super().__init__(**kwargs)
        # O14: Per-interface rate history for sparklines
        self._rx_history: Dict[str, deque[float]] = {}
        self._tx_history: Dict[str, deque[float]] = {}

    def on_mount(self) -> None:
        self.update("[dim]Traffic: waiting for data...[/]")

    def update_data(self, traffic: Dict[str, InterfaceStats]) -> None:
        """Refresh the traffic bar with new interface stats."""
        if not traffic:
            self.update("[dim]Traffic: no interfaces[/]")
            return

        segments: list[str] = []

        for name, stats in sorted(traffic.items()):
            rx_rate = _human_bytes(stats.rx_rate)
            tx_rate = _human_bytes(stats.tx_rate)
            rx_total = _human_bytes(stats.rx_bytes)
            tx_total = _human_bytes(stats.tx_bytes)

            # O10: Interface IP
            ip = _get_interface_ip(name)
            ip_tag = f" ({ip})" if ip else ""

            # O14: Append to history deque
            if name not in self._rx_history:
                self._rx_history[name] = deque(maxlen=_MAX_HISTORY)
                self._tx_history[name] = deque(maxlen=_MAX_HISTORY)
            self._rx_history[name].append(stats.rx_rate)
            self._tx_history[name].append(stats.tx_rate)

            # O14: Render sparklines
            rx_spark = _mini_sparkline(self._rx_history[name], "green")
            tx_spark = _mini_sparkline(self._tx_history[name], "cyan")

            spark_part = ""
            if rx_spark:
                spark_part = f"  {rx_spark} {tx_spark}"

            segments.append(
                f"[bold]{name}{ip_tag}[/]  "
                f"[green]↓ {rx_rate}/s[/]  "
                f"[cyan]↑ {tx_rate}/s[/]  "
                f"[dim]Total: ↓ {rx_total}  ↑ {tx_total}[/]"
                f"{spark_part}"
            )

        self.update("  |  ".join(segments))
