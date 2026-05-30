"""NetSentry — Parse /proc/net/{tcp,tcp6,udp,udp6} into SocketEntry list.

Line format (whitespace-separated):
  sl  local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt uid timeout inode ...

IPv4 addresses are 8-hex-char, big-endian (e.g. 0100007F → 127.0.0.1).
IPv6 addresses are 32-hex-char, stored as 4 × 32-bit words in little-endian.
"""
from __future__ import annotations

import ipaddress
import os
from typing import List

from shared import (
    PROC_TCP, PROC_TCP6, PROC_UDP, PROC_UDP6, TCP_STATES,
)
from backend.models import SocketEntry


# ── Internal helpers ───────────────────────────────────────────

def _parse_hex_ip(hex_str: str) -> str:
    """Convert hex IP from /proc/net to dotted-decimal or IPv6 string.

    IPv4: 8 hex chars, big-endian  →  e.g. '0100007F' → '127.0.0.1'
    IPv6: 32 hex chars, 4 little-endian 32-bit words.
    """
    hex_str = hex_str.upper()
    if len(hex_str) == 8:
        # IPv4 — stored as 4 bytes in host (little-endian) order
        b = bytes.fromhex(hex_str)
        addr = ipaddress.IPv4Address(b[::-1])
        return str(addr)
    if len(hex_str) == 32:
        # IPv6 — 4 groups of 8 hex chars, each group is a 32-bit LE word
        words = [hex_str[i:i+8] for i in range(0, 32, 8)]
        # Swap bytes in each 32-bit word (little-endian → network byte order)
        decoded_words = []
        for w in words:
            b = bytes.fromhex(w)
            swapped = b[::-1]  # reverse 4 bytes
            decoded_words.append(swapped.hex())
        full_hex = "".join(decoded_words)
        addr = ipaddress.IPv6Address(int(full_hex, 16))
        return str(addr)
    # Fallback — return as-is
    return hex_str


def _parse_hex_port(hex_str: str) -> int:
    """Convert hex port string to integer."""
    return int(hex_str, 16)


def _decode_state(state_hex: str, proto: str) -> str:
    """Map a /proc/net state hex code to a human-readable string.

    TCP: use TCP_STATES mapping.
    UDP: '07' means UNCONN (unconnected / listening), '01' = ESTABLISHED.
    """
    state_hex = state_hex.upper()
    if proto.startswith("tcp"):
        return TCP_STATES.get(state_hex, f"UNKNOWN({state_hex})")
    # UDP
    if state_hex == "07":
        return "UNCONN"
    if state_hex == "01":
        return "ESTABLISHED"
    return f"UNKNOWN({state_hex})"


# ── Public API ─────────────────────────────────────────────────

def parse_proc_net(path: str, proto: str) -> List[SocketEntry]:
    """Parse a single /proc/net/ file into a list of SocketEntry.

    Args:
        path: e.g. '/proc/net/tcp'
        proto: 'tcp', 'tcp6', 'udp', or 'udp6'

    Returns:
        List of SocketEntry objects.
    """
    entries: List[SocketEntry] = []
    try:
        with open(path, "r") as fh:
            lines = fh.readlines()
    except (FileNotFoundError, PermissionError, OSError):
        return entries

    for line in lines:
        line = line.strip()
        if not line or line.startswith("sl"):
            # Skip header line
            continue

        parts = line.split()
        if len(parts) < 10:
            # Malformed line — skip
            continue

        try:
            local_addr, local_port_hex = parts[1].split(":")
            remote_addr, remote_port_hex = parts[2].split(":")
            state_hex = parts[3]
            uid = int(parts[7])
            inode = int(parts[9])
        except (ValueError, IndexError):
            continue

        # Skip entries with inode 0 (they have no real socket)
        if inode == 0:
            continue

        local_ip = _parse_hex_ip(local_addr)
        local_port = _parse_hex_port(local_port_hex)
        remote_ip = _parse_hex_ip(remote_addr)
        remote_port = _parse_hex_port(remote_port_hex)
        state = _decode_state(state_hex, proto)

        entries.append(SocketEntry(
            proto=proto,
            local_ip=local_ip,
            local_port=local_port,
            remote_ip=remote_ip,
            remote_port=remote_port,
            state=state,
            state_code=state_hex,
            uid=uid,
            inode=inode,
        ))

    return entries


def parse_all_proc() -> List[SocketEntry]:
    """Parse all four /proc/net files (tcp, tcp6, udp, udp6).

    Returns combined list of SocketEntry objects.
    """
    all_entries: List[SocketEntry] = []
    for path, proto in [
        (PROC_TCP, "tcp"),
        (PROC_TCP6, "tcp6"),
        (PROC_UDP, "udp"),
        (PROC_UDP6, "udp6"),
    ]:
        all_entries.extend(parse_proc_net(path, proto))
    return all_entries
