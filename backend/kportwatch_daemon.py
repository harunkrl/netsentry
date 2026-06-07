#!/usr/bin/env python3
"""KPortWatch — Main backend daemon.

Gathers network socket data from /proc, runs alert analysis,
and writes JSON snapshots for the Plasma widget and TUI.

Usage:
    python3 kportwatch-daemon.py --foreground --verbose
    python3 kportwatch-daemon.py --interval 5
"""
from __future__ import annotations

import argparse
import contextlib
import fcntl
import logging
import os
import sys
import time

from shared import DEFAULT_POLL_INTERVAL, PID_FILE
from shared.config import load_config

from backend.models import InterfaceStats, SocketEntry
from backend.parsers.inode_map import build_inode_to_pid_map, build_uid_process_map

logger = logging.getLogger("kportwatch")


def _write_heartbeat(path: str) -> None:
    """Write a tiny JSON file with current timestamp for health checks."""
    try:
        import json as _json
        data = _json.dumps({"ts": time.time()}).encode()
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        pass  # heartbeat is best-effort


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="KPortWatch backend daemon — network security monitor",
    )
    parser.add_argument(
        "--interval", "-i",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Poll interval in seconds (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    parser.add_argument(
        "--foreground", "-f",
        action="store_true",
        help="Run in foreground (don't daemonize)",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to config file (default: ~/.config/kportwatch/config.toml)",
    )
    return parser.parse_args()


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def merge_inode_map(entries: list[SocketEntry]) -> None:
    """Resolve PIDs for socket entries by scanning /proc fd symlinks."""
    inode_map = build_inode_to_pid_map()
    uid_map = build_uid_process_map()
    for entry in entries:
        info = inode_map.get(entry.inode)
        if info:
            pid, proc_name, cmdline = info
            entry.pid = pid
            entry.process_name = proc_name
            entry.cmdline = cmdline
        elif entry.uid in uid_map:
            username, proc_name, cmdline = uid_map[entry.uid]
            entry.process_name = f"{proc_name} ({username})"
            entry.cmdline = cmdline


def classify_entries(
    entries: list[SocketEntry],
) -> tuple[list[SocketEntry], list[SocketEntry]]:
    """Split entries into listening and established lists.

    Listening: state is LISTEN or UNCONN (UDP listening).
    Everything else goes to established.
    """
    listening: list[SocketEntry] = []
    established: list[SocketEntry] = []
    for e in entries:
        if e.state in ("LISTEN", "UNCONN"):
            listening.append(e)
        else:
            established.append(e)
    return listening, established


def compute_traffic_deltas(
    current: list[InterfaceStats],
    prev: dict[str, tuple[float, InterfaceStats]],
    now: float,
) -> dict[str, InterfaceStats]:
    """Compute per-second RX/TX rates from cumulative counters.

    Args:
        current: Freshly parsed interface stats.
        prev: Previous cycle's {iface: (timestamp, InterfaceStats)}.
        now: Current timestamp.

    Returns:
        Dict of {iface: InterfaceStats} with rx_rate/tx_rate filled.
    """
    result: dict[str, InterfaceStats] = {}
    for stats in current:
        if stats.interface in prev:
            prev_ts, prev_stats = prev[stats.interface]
            elapsed = now - prev_ts
            if elapsed > 0:
                stats.rx_rate = max(0, (stats.rx_bytes - prev_stats.rx_bytes) / elapsed)
                stats.tx_rate = max(0, (stats.tx_bytes - prev_stats.tx_bytes) / elapsed)
        result[stats.interface] = stats
    return result


def daemon_loop(args: argparse.Namespace) -> None:
    """Main daemon loop — delegates to DaemonController."""
    from backend.daemon_controller import DaemonController
    controller = DaemonController(args)
    controller.run()


def _daemonize() -> None:
    """Double-fork daemonization with proper cleanup."""
    import logging

    # First fork
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    # Create new session
    os.setsid()
    os.chdir("/")

    # Second fork
    pid2 = os.fork()
    if pid2 > 0:
        sys.exit(0)

    # Close inherited file descriptors (keep 0,1,2 for std streams)
    try:
        max_fd = os.sysconf("SC_OPEN_MAX")
    except (AttributeError, ValueError):
        max_fd = 1024
    for fd in range(3, min(max_fd, 256)):  # Cap at 256 to avoid slowness
        with contextlib.suppress(OSError):
            os.close(fd)

    # Redirect stdin/stdout/stderr to /dev/null
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)  # stdin
    os.dup2(devnull, 1)  # stdout
    os.dup2(devnull, 2)  # stderr
    if devnull > 2:
        os.close(devnull)

    # Reconfigure logging to use the new stderr (/dev/null)
    # This prevents log messages from leaking to the launching terminal
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root_logger.addHandler(handler)


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    # Load config before daemonizing (so errors show in terminal)
    load_config(args.config)

    if not args.foreground:
        _daemonize()

    # Prevent duplicate daemons and write PID file
    try:
        pid_fd = open(PID_FILE, "w")  # noqa: SIM115 — fd intentionally held open for lock
        fcntl.flock(pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pid_fd.write(str(os.getpid()))
        pid_fd.flush()
        os.fsync(pid_fd.fileno())
    except BlockingIOError:
        logger.error("Daemon is already running!")
        sys.exit(1)
    except OSError as e:
        logger.error("Failed to create PID file: %s", e)
        sys.exit(1)

    daemon_loop(args)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import pathlib
        import traceback
        crash_log = pathlib.Path.home() / ".local" / "share" / "kportwatch" / "crash.log"
        crash_log.parent.mkdir(parents=True, exist_ok=True)
        with open(crash_log, "a") as f:
            f.write(f"\n{'='*60}\nCrash at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            traceback.print_exc(file=f)
        raise
