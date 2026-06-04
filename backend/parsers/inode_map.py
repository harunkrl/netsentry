"""NetSentry — Map socket inodes to PIDs via /proc/[pid]/fd/ scanning.

For each numeric /proc/<pid>/ directory, readlink each fd entry.
If the link target is 'socket:[<inode>]', record the mapping.

Returns: {inode: (pid, process_name, cmdline)}
"""
from __future__ import annotations

import os
from typing import Dict, Tuple, Optional


def _read_file_safe(path: str) -> Optional[str]:
    """Read a small /proc file, returning None on any error."""
    try:
        with open(path, "r") as fh:
            return fh.read().strip()
    except (PermissionError, FileNotFoundError, ProcessLookupError, OSError):
        return None


def build_inode_to_pid_map() -> Dict[int, Tuple[int, str, str]]:
    """Scan /proc to build a mapping from socket inode to owning process.

    Returns:
        Dictionary mapping inode → (pid, process_name, cmdline).
        Only processes readable by the current user are included.
    """
    inode_map: Dict[int, Tuple[int, str, str]] = {}

    try:
        proc_entries = os.listdir("/proc")
    except OSError:
        return inode_map

    for entry in proc_entries:
        if not entry.isdigit():
            continue
        pid = int(entry)

        # Read short process name from /proc/{pid}/comm
        comm = _read_file_safe(f"/proc/{pid}/comm") or ""

        # Read full cmdline from /proc/{pid}/cmdline (null-byte separated)
        cmdline_raw = _read_file_safe(f"/proc/{pid}/cmdline")
        if cmdline_raw:
            # cmdline uses null bytes as separators; replace with spaces
            cmdline = cmdline_raw.replace("\x00", " ").strip()
        else:
            cmdline = ""

        # Use comm as fallback process name if cmdline is empty
        process_name = comm if comm else ""

        # Scan /proc/{pid}/fd/ for socket links
        fd_dir = f"/proc/{pid}/fd"
        try:
            fds = os.listdir(fd_dir)
        except (PermissionError, FileNotFoundError, ProcessLookupError, OSError):
            continue

        for fd_name in fds:
            fd_path = os.path.join(fd_dir, fd_name)
            try:
                link_target = os.readlink(fd_path)
            except (PermissionError, FileNotFoundError, ProcessLookupError, OSError):
                continue

            if link_target.startswith("socket:["):
                # Extract inode number from 'socket:[12345]'
                inode_str = link_target[8:-1]  # strip 'socket:[' and ']'
                try:
                    inode = int(inode_str)
                except ValueError:
                    continue
                inode_map[inode] = (pid, process_name, cmdline)

    return inode_map
