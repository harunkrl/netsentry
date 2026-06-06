"""KPortWatch — Parse /proc/net/dev into InterfaceStats list.

/proc/net/dev format (whitespace-separated, 16 counters per line):

  Inter-|   Receive                                                |  Transmit
   face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed
      lo:   97937    1151    0    0    0     0          0         0    97937    1151    0    0    0     0       0          0
   wlan0: 1493759338 1197161    0    0    0     0          0         0 201984858  354400    0   39    0     0       0          0

Each data line: "iface: rx_bytes rx_packets rx_errs rx_drop rx_fifo rx_frame rx_compressed rx_multicast tx_bytes tx_packets tx_errs tx_drop tx_fifo tx_colls tx_carrier tx_compressed"
"""
from __future__ import annotations

from backend.models import InterfaceStats

# ── Internal helpers ───────────────────────────────────────────

def _parse_line(line: str) -> InterfaceStats | None:
    """Parse a single /proc/net/dev data line into InterfaceStats.

    Returns None for malformed lines or loopback interface.
    """
    if ":" not in line:
        return None

    iface, _, counters = line.partition(":")
    iface = iface.strip()

    # Skip loopback — it carries no real network traffic
    if iface == "lo":
        return None

    parts = counters.split()
    if len(parts) < 16:
        return None

    try:
        return InterfaceStats(
            interface=iface,
            rx_bytes=int(parts[0]),
            rx_packets=int(parts[1]),
            rx_errors=int(parts[2]),
            rx_drops=int(parts[3]),
            # parts[4] = rx_fifo, parts[5] = rx_frame,
            # parts[6] = rx_compressed, parts[7] = rx_multicast
            tx_bytes=int(parts[8]),
            tx_packets=int(parts[9]),
            tx_errors=int(parts[10]),
            tx_drops=int(parts[11]),
            # parts[12] = tx_fifo, parts[13] = tx_colls,
            # parts[14] = tx_carrier, parts[15] = tx_compressed
        )
    except (ValueError, IndexError):
        return None


# ── Public API ─────────────────────────────────────────────────

def parse_proc_net_dev(path: str = "/proc/net/dev") -> list[InterfaceStats]:
    """Parse /proc/net/dev into a list of InterfaceStats.

    Skips the 2 header lines and the loopback interface.

    Args:
        path: Path to the /proc/net/dev file.

    Returns:
        List of InterfaceStats objects, one per non-loopback interface.
    """
    entries: list[InterfaceStats] = []
    try:
        with open(path) as fh:
            lines = fh.readlines()
    except (FileNotFoundError, PermissionError, OSError):
        return entries

    # Skip 2 header lines (Inter-| and face |)
    for line in lines[2:]:
        line = line.strip()
        if not line:
            continue
        stats = _parse_line(line)
        if stats is not None:
            entries.append(stats)

    return entries
