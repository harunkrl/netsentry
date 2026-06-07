"""KPortWatch — Build process tree from /proc/[pid]/stat.

Scans all numeric /proc/<pid> directories, reads stat/comm/cmdline/status,
and constructs parent-child relationships using PPID.

Usage::

    from backend.parsers.process_tree import build_process_tree, get_tree_roots

    processes = build_process_tree(inode_map)
    roots = get_tree_roots(processes)

/proc/[pid]/stat format (relevant fields):
    Field 1:  pid
    Field 2:  (comm) — may contain spaces/parens, use last ')'
    Field 3:  state — single char (S, R, Z, T, D, ...)
    Field 4:  ppid — parent PID

/proc/[pid]/status contains Uid line for UID extraction.
"""
from __future__ import annotations

import os

from shared.fs_utils import read_file_safe

from backend.models import ProcessInfo


def _parse_stat(path: str) -> tuple[int, str, str, int] | None:
    """Parse /proc/[pid]/stat → (pid, name, state, ppid).

    The comm field is wrapped in parens and may contain spaces.
    We use the last ')' to split correctly.

    Returns None on any parse error.
    """
    raw = read_file_safe(path)
    if not raw:
        return None

    try:
        # Split at last ')' to handle comm with spaces/parens
        end_comm = raw.rfind(")")
        if end_comm < 0:
            return None

        start_comm = raw.find("(")
        if start_comm < 0:
            return None

        pid_str = raw[:start_comm].strip()
        pid = int(pid_str)
        name = raw[start_comm + 1:end_comm]

        # After ')': state ppid ...
        rest = raw[end_comm + 2:].split()
        if len(rest) < 2:
            return None

        state = rest[0]
        ppid = int(rest[1])

        return (pid, name, state, ppid)
    except (ValueError, IndexError):
        return None


def _read_uid(pid: int) -> int:
    """Read UID from /proc/[pid]/status. Returns -1 on error."""
    raw = read_file_safe(f"/proc/{pid}/status")
    if not raw:
        return -1
    for line in raw.splitlines():
        if line.startswith("Uid:"):
            parts = line.split()
            if len(parts) >= 2:
                try:
                    return int(parts[1])  # real UID
                except ValueError:
                    pass
    return -1


# ── Public API ─────────────────────────────────────────────────

def build_process_tree(
    inode_map: dict[int, tuple[int, str, str]] | None = None,
) -> dict[int, ProcessInfo]:
    """Scan /proc to build a process tree.

    Args:
        inode_map: Optional inode→(pid, name, cmdline) mapping from
                   ``build_inode_to_pid_map()``. Used to flag processes
                   with ``has_network=True``.

    Returns:
        Dict of {pid: ProcessInfo} with children lists populated.
    """
    # Build set of PIDs that own sockets
    network_pids: set[int] = set()
    if inode_map:
        for _inode, (pid, _name, _cmdline) in inode_map.items():
            network_pids.add(pid)

    processes: dict[int, ProcessInfo] = {}

    try:
        proc_entries = os.listdir("/proc")
    except OSError:
        return processes

    for entry in proc_entries:
        if not entry.isdigit():
            continue
        pid = int(entry)

        parsed = _parse_stat(f"/proc/{pid}/stat")
        if parsed is None:
            continue

        _, name, state, ppid = parsed

        # Read full cmdline
        cmdline_raw = read_file_safe(f"/proc/{pid}/cmdline")
        cmdline = cmdline_raw.replace("\x00", " ").strip() if cmdline_raw else ""

        # Read UID
        uid = _read_uid(pid)

        processes[pid] = ProcessInfo(
            pid=pid,
            ppid=ppid,
            name=name,
            cmdline=cmdline,
            state=state,
            uid=uid,
            has_network=pid in network_pids,
        )

    # Build children lists
    for pid, info in processes.items():
        ppid = info.ppid
        if ppid in processes:
            processes[ppid].children.append(pid)

    return processes


def get_tree_roots(processes: dict[int, ProcessInfo]) -> list[int]:
    """Return PIDs that are roots of the process tree.

    A root is a process whose PPID is 0 or not present in the dict.
    Results are sorted by PID.
    """
    roots: list[int] = []
    for pid, info in processes.items():
        if info.ppid == 0 or info.ppid not in processes:
            roots.append(pid)
    return sorted(roots)
