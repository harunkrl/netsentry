"""KPortWatch — psutil-based collectors (replaces /proc parsing).

Drop-in replacements for the manual /proc parsers:
  - collect_connections()  ← parse_all_proc() + inode_map enrichment
  - collect_traffic()      ← parse_proc_net_dev()
  - collect_process_tree() ← build_process_tree()

Uses psutil (cross-platform, maintained) instead of manual /proc parsing.
~50 lines of actual logic vs ~560 lines of /proc parsers.
"""
from __future__ import annotations

import socket as _socket

import psutil

from backend.models import InterfaceStats, ProcessInfo, SocketEntry

# ── TCP state mapping (psutil → our labels) ────────────────────

_TCP_STATE_MAP = {
    psutil.CONN_ESTABLISHED: "ESTABLISHED",
    psutil.CONN_SYN_SENT: "SYN_SENT",
    psutil.CONN_SYN_RECV: "SYN_RECV",
    psutil.CONN_FIN_WAIT1: "FIN_WAIT1",
    psutil.CONN_FIN_WAIT2: "FIN_WAIT2",
    psutil.CONN_TIME_WAIT: "TIME_WAIT",
    psutil.CONN_CLOSE: "CLOSE",
    psutil.CONN_CLOSE_WAIT: "CLOSE_WAIT",
    psutil.CONN_LAST_ACK: "LAST_ACK",
    psutil.CONN_LISTEN: "LISTEN",
    psutil.CONN_CLOSING: "CLOSING",
    psutil.CONN_NONE: "NONE",
}

# Map psutil proto families to our proto strings
_PROTO_MAP = {
    _socket.SOCK_STREAM: "tcp",
    _socket.SOCK_DGRAM: "udp",
}


def _proto_label(conn: psutil._common.sconn) -> str:
    """Derive proto string like 'tcp' or 'tcp6' from a psutil connection."""
    base = _PROTO_MAP.get(conn.type, "tcp")  # default tcp for unknown
    if conn.family.name.endswith("V6"):
        return base + "6"
    return base


def _state_label(conn: psutil._common.sconn) -> tuple[str, str]:
    """Return (human_readable_state, hex_code) from psutil status."""
    label = _TCP_STATE_MAP.get(conn.status, conn.status or "UNKNOWN")
    # For UDP sockets, psutil returns NONE — treat as UNCONN
    if conn.type == _socket.SOCK_DGRAM and (conn.status == "NONE" or conn.status is None):
        label = "UNCONN"
    # Hex code approximation (for backward compat, not critical for psutil path)
    code = "00"
    for hex_val, name in {
        "0A": "LISTEN", "06": "TIME_WAIT", "01": "ESTABLISHED",
        "07": "UNCONN", "02": "SYN_SENT", "03": "SYN_RECV",
    }.items():
        if label == name:
            code = hex_val
            break
    return label, code


# ── Connection collection ──────────────────────────────────────

def collect_connections() -> list[SocketEntry]:
    """Collect all network connections using psutil.net_connections().

    Replaces parse_all_proc() + inode_map enrichment from proc_net.py
    and inode_map.py combined.

    Returns:
        List of SocketEntry with pid, process_name, and cmdline populated.
    """
    entries: list[SocketEntry] = []
    try:
        connections = psutil.net_connections(kind="inet")
    except psutil.AccessDenied:
        return entries

    for conn in connections:
        if conn.laddr is None and conn.raddr is None:
            continue

        proto = _proto_label(conn)
        state, state_code = _state_label(conn)

        # psutil returns 0 for laddr/raddr on unconnected sockets
        local_ip = conn.laddr.ip if conn.laddr else "0.0.0.0"
        local_port = conn.laddr.port if conn.laddr else 0
        remote_ip = conn.raddr.ip if conn.raddr else "0.0.0.0"
        remote_port = conn.raddr.port if conn.raddr else 0

        # Get process info if available
        pid = conn.pid
        process_name = None
        cmdline = None
        uid = -1

        if pid:
            try:
                proc = psutil.Process(pid)
                process_name = proc.name()
                cmdline = " ".join(proc.cmdline())
                try:
                    uids = proc.uids()
                    uid = uids.real if uids else -1
                except (psutil.AccessDenied, AttributeError):
                    pass
            except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
                pid = None

        entries.append(SocketEntry(
            proto=proto,
            local_ip=local_ip,
            local_port=local_port,
            remote_ip=remote_ip,
            remote_port=remote_port,
            state=state,
            state_code=state_code,
            uid=uid,
            inode=0,  # psutil doesn't expose inode — not needed for widget/TUI
            pid=pid,
            process_name=process_name,
            cmdline=cmdline,
        ))

    return entries


# ── Traffic stats collection ───────────────────────────────────

def collect_traffic() -> list[InterfaceStats]:
    """Collect per-interface traffic stats using psutil.net_io_counters().

    Replaces parse_proc_net_dev().

    Returns:
        List of InterfaceStats, one per non-loopback interface.
    """
    try:
        counters = psutil.net_io_counters(pernic=True)
    except Exception:
        return []

    entries: list[InterfaceStats] = []
    for iface, stats in counters.items():
        if iface == "lo":
            continue
        entries.append(InterfaceStats(
            interface=iface,
            rx_bytes=stats.bytes_recv,
            tx_bytes=stats.bytes_sent,
            rx_packets=stats.packets_recv,
            tx_packets=stats.packets_sent,
            rx_errors=stats.errin,
            tx_errors=stats.errout,
            rx_drops=stats.dropin,
            tx_drops=stats.dropout,
        ))

    return entries


# ── Process tree collection ────────────────────────────────────

def collect_process_tree(
    network_pids: set[int] | None = None,
) -> dict[int, ProcessInfo]:
    """Build a process tree using psutil.process_iter().

    Replaces build_process_tree().

    Args:
        network_pids: Optional set of PIDs that own sockets.

    Returns:
        Dict of {pid: ProcessInfo} with children lists populated.
    """
    if network_pids is None:
        network_pids = set()

    processes: dict[int, ProcessInfo] = {}

    for proc in psutil.process_iter(["pid", "ppid", "name", "cmdline", "status", "uids"]):
        try:
            info = proc.info
            pid = info["pid"]
            ppid = info["ppid"] or 0
            name = info["name"] or ""
            cmdline_raw = info.get("cmdline") or []
            cmdline = " ".join(cmdline_raw)
            state_char = _status_to_char(info.get("status", ""))
            uid = -1
            try:
                uids = info.get("uids")
                if uids:
                    uid = uids.real
            except (AttributeError, TypeError):
                pass

            processes[pid] = ProcessInfo(
                pid=pid,
                ppid=ppid,
                name=name,
                cmdline=cmdline,
                state=state_char,
                uid=uid,
                has_network=pid in network_pids,
            )
        except (psutil.NoSuchProcess, psutil.AccessDenied, psutil.ZombieProcess):
            continue

    # Build children lists
    for pid, proc_info in processes.items():
        ppid = proc_info.ppid
        if ppid in processes:
            processes[ppid].children.append(pid)

    return processes


def collect_network_pids() -> set[int]:
    """Get set of PIDs that own network sockets."""
    pids: set[int] = set()
    try:
        for conn in psutil.net_connections(kind="inet"):
            if conn.pid:
                pids.add(conn.pid)
    except psutil.AccessDenied:
        pass
    return pids


def _status_to_char(status: str) -> str:
    """Convert psutil status string to single char for compatibility."""
    mapping = {
        "running": "R",
        "sleeping": "S",
        "disk-sleep": "D",
        "stopped": "T",
        "tracing-stop": "T",
        "zombie": "Z",
        "dead": "X",
        "wake-kill": "K",
        "waking": "W",
        "idle": "I",
        "locked": "L",
        "waiting": "W",
    }
    return mapping.get(status, "?")
