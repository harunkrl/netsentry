#!/usr/bin/env python3
"""NetSentry — Main backend daemon.

Gathers network socket data from /proc, runs alert analysis,
and writes JSON snapshots for the Plasma widget and TUI.

Usage:
    python3 netsentry-daemon.py --foreground --verbose
    python3 netsentry-daemon.py --interval 5
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
from typing import List

from shared import (
    ALERT_POLL_INTERVAL,
    BASELINE_FILE,
    DATA_FILE,
    DEFAULT_POLL_INTERVAL,
    IDLE_POLL_INTERVAL,
    IDLE_THRESHOLD_SECS,
    KNOWN_SAFE_PORTS,
    PID_FILE,
)
from backend.models import Snapshot, SocketEntry
from backend.parsers.proc_net import parse_all_proc
from backend.parsers.inode_map import build_inode_to_pid_map
from backend.alert_engine import AlertEngine
from backend.writers.json_file import write_snapshot

logger = logging.getLogger("netsentry")


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="NetSentry backend daemon — network security monitor",
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
    return parser.parse_args()


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def merge_inode_map(entries: List[SocketEntry]) -> None:
    """Resolve PIDs for socket entries by scanning /proc fd symlinks."""
    inode_map = build_inode_to_pid_map()
    for entry in entries:
        info = inode_map.get(entry.inode)
        if info:
            pid, proc_name, cmdline = info
            entry.pid = pid
            entry.process_name = proc_name
            entry.cmdline = cmdline


def classify_entries(
    entries: List[SocketEntry],
) -> tuple[List[SocketEntry], List[SocketEntry]]:
    """Split entries into listening and established lists.

    Listening: state is LISTEN or UNCONN (UDP listening).
    Everything else goes to established.
    """
    listening: List[SocketEntry] = []
    established: List[SocketEntry] = []
    for e in entries:
        if e.state in ("LISTEN", "UNCONN"):
            listening.append(e)
        else:
            established.append(e)
    return listening, established


def daemon_loop(args: argparse.Namespace) -> None:
    """Main daemon loop."""
    alert_engine = AlertEngine(known_safe_ports=KNOWN_SAFE_PORTS)

    # Try loading a previously saved baseline
    if alert_engine.load_baseline():
        logger.info("Loaded saved baseline from %s", BASELINE_FILE)
    else:
        logger.info("No saved baseline — will learn for %.0f seconds",
                     alert_engine.baseline_duration)

    running = True
    last_snapshot_hash: str = ""
    last_change_time = time.time()
    prev_baseline: frozenset = frozenset()
    notified_alerts: set = set()

    # Start Unix Socket Server
    from backend.writers.unix_socket import UnixSocketServer
    socket_server = UnixSocketServer()
    socket_server.start()

    def handle_signal(signum: int, _frame) -> None:
        nonlocal running
        logger.info("Received signal %s — shutting down", signum)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    interval = args.interval

    while running:
        cycle_start = time.time()

        try:
            # 1. Parse /proc/net files
            entries = parse_all_proc()
            logger.debug("Parsed %d socket entries", len(entries))

            # 2. Resolve PIDs
            merge_inode_map(entries)

            # 3. Classify listening vs established
            listening, established = classify_entries(entries)

            # 3.5 GeoIP / rDNS lookup for remote IPs
            from backend.parsers.rdns import get_hostname
            for e in established:
                # ignore local IPs
                if e.remote_ip and not e.remote_ip.startswith(("127.", "::1", "0.0.0.0", "::")):
                    e.remote_hostname = get_hostname(e.remote_ip)

            # 4. Run alert analysis on listening sockets
            alerts = alert_engine.analyze(listening)

            # 5. Save baseline if it just completed or changed
            if alert_engine.is_baseline_complete():
                current_baseline = frozenset(alert_engine._baseline_ports)
                if current_baseline != prev_baseline:
                    alert_engine.save_baseline()
                    prev_baseline = current_baseline

            # 6. Build snapshot
            snapshot = Snapshot(
                timestamp=time.time(),
                poll_interval_ms=int(interval * 1000),
                listening=listening,
                established=established,
                alerts=alerts,
                summary={
                    "total_listening": len(listening),
                    "total_established": len(established),
                    "alert_count": len(alerts),
                },
            )

            # 7. Write snapshot atomically and broadcast over socket
            write_snapshot(snapshot)
            if socket_server:
                socket_server.broadcast(snapshot.to_json())
            
            logger.debug(
                "Snapshot: %d listening, %d established, %d alerts",
                len(listening), len(established), len(alerts),
            )

            # 8. Adaptive sleep interval
            current_hash = str(sorted(
                (e.local_port, e.proto, e.state) for e in listening
            ))
            if current_hash != last_snapshot_hash:
                last_snapshot_hash = current_hash
                last_change_time = time.time()

            if alerts:
                interval = ALERT_POLL_INTERVAL
                for a in alerts:
                    logger.info("ALERT [%s] %s", a.level, a.message)
                    
                    # Desktop notification for WARNING and CRITICAL
                    if a.level in (AlertLevel.WARNING, AlertLevel.CRITICAL):
                        alert_hash = f"{a.level}:{a.message}"
                        # Only notify once per specific alert to avoid spam
                        if alert_hash not in notified_alerts:
                            try:
                                import subprocess
                                icon = "dialog-error" if a.level == AlertLevel.CRITICAL else "dialog-warning"
                                subprocess.Popen([
                                    "notify-send",
                                    "-a", "NetSentry",
                                    "-u", "critical" if a.level == AlertLevel.CRITICAL else "normal",
                                    "-i", icon,
                                    f"NetSentry: {a.level}",
                                    a.message
                                ])
                                notified_alerts.add(alert_hash)
                            except Exception as e:
                                logger.error("Failed to send notification: %s", e)
                                
            elif (time.time() - last_change_time) > IDLE_THRESHOLD_SECS:
                interval = IDLE_POLL_INTERVAL
            else:
                interval = args.interval

        except Exception:
            logger.exception("Error in daemon cycle")
            interval = args.interval

        # Sleep remaining interval
        elapsed = time.time() - cycle_start
        sleep_time = max(0.0, interval - elapsed)
        if sleep_time > 0 and running:
            # Interruptible sleep — check running flag every 0.5s
            end_time = time.time() + sleep_time
            while running and time.time() < end_time:
                time.sleep(min(0.5, end_time - time.time()))

    # Save baseline on clean exit
    alert_engine.save_baseline()
    if socket_server:
        socket_server.stop()

    # Clean up PID file
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass

    logger.info("NetSentry daemon stopped")


def _daemonize() -> None:
    """Double-fork daemonization with proper cleanup."""
    import logging

    # First fork
    pid = os.fork()
    if pid > 0:
        print(f"NetSentry daemon started with PID {pid}")
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
        try:
            os.close(fd)
        except OSError:
            pass

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

    # Write PID file so tools can find the daemon
    try:
        with open(PID_FILE, "w") as f:
            f.write(str(os.getpid()))
    except OSError:
        pass  # Best effort


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    if not args.foreground:
        _daemonize()

    daemon_loop(args)


if __name__ == "__main__":
    main()
