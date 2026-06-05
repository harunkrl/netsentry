#!/usr/bin/env python3
"""NetSentry Control — Manage the NetSentry daemon.

Subcommands:
    status    Show daemon status
    restart   Restart the daemon
    stop      Stop the daemon
    reload    Reload config (SIGHUP)
"""
from __future__ import annotations

import argparse
import os
import signal
import subprocess
import sys
import time

from shared.constants import PID_FILE, SOCKET_PATH


def _read_pid() -> int | None:
    """Read the daemon PID from the PID file."""
    try:
        with open(PID_FILE) as f:
            return int(f.read().strip())
    except (FileNotFoundError, ValueError):
        return None


def _is_alive(pid: int) -> bool:
    """Check if a process with the given PID exists."""
    try:
        os.kill(pid, 0)  # signal 0 = existence check
        return True
    except ProcessLookupError:
        return False
    except PermissionError:
        return True  # exists but we can't signal it


def _wait_for(pid: int | None, timeout: float = 5.0, alive: bool = True) -> bool:
    """Wait for a process to appear (alive=True) or disappear (alive=False)."""
    deadline = time.monotonic() + timeout
    while time.monotonic() < deadline:
        is_alive = _is_alive(pid) if pid else False
        if is_alive == alive:
            return True
        time.sleep(0.2)
    return False


def cmd_status(_args: argparse.Namespace) -> int:
    """Show daemon status."""
    pid = _read_pid()
    if pid is None:
        print("❌ Daemon is not running (no PID file)")
        return 1

    if not _is_alive(pid):
        print(f"❌ Daemon is not running (stale PID file: {pid})")
        return 1

    # Check socket
    socket_ok = os.path.exists(SOCKET_PATH)

    lines = [
        f"✅ Daemon is running (PID {pid})",
        f"   PID file:  {PID_FILE}",
        f"   Socket:    {SOCKET_PATH} {'✅' if socket_ok else '❌ not found'}",
    ]
    print("\n".join(lines))
    return 0


def cmd_stop(_args: argparse.Namespace) -> int:
    """Stop the daemon."""
    pid = _read_pid()
    if pid is None:
        print("❌ Daemon is not running")
        return 1

    if not _is_alive(pid):
        print("❌ Daemon is not running (stale PID file)")
        _cleanup_pidfile()
        return 1

    print(f"Stopping daemon (PID {pid})...")
    try:
        os.kill(pid, signal.SIGTERM)
    except ProcessLookupError:
        print("❌ Process already gone")
        _cleanup_pidfile()
        return 1

    if _wait_for(pid, timeout=5.0, alive=False):
        _cleanup_pidfile()
        print("✅ Daemon stopped")
        return 0
    else:
        print("⚠️  Daemon did not stop within 5s — sending SIGKILL")
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            pass
        _cleanup_pidfile()
        return 0


def cmd_restart(args: argparse.Namespace) -> int:
    """Restart the daemon."""
    pid = _read_pid()

    # Stop if running
    if pid is not None and _is_alive(pid):
        print(f"Stopping daemon (PID {pid})...")
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            pass
        if _wait_for(pid, timeout=5.0, alive=False):
            print("Daemon stopped")
        else:
            print("⚠️  Force killing daemon...")
            try:
                os.kill(pid, signal.SIGKILL)
            except ProcessLookupError:
                pass
    else:
        print("Daemon not running, starting fresh...")

    _cleanup_pidfile()

    # Start daemon (use the same Python interpreter)
    python = sys.executable
    cmd = [python, "-m", "backend.netsentry_daemon", "--foreground"]
    if args.verbose:
        cmd.append("--verbose")
    if args.config:
        cmd.extend(["--config", args.config])

    print(f"Starting daemon...")
    try:
        proc = subprocess.Popen(
            cmd,
            cwd=_find_project_root(),
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            start_new_session=True,
        )
    except Exception as e:
        print(f"❌ Failed to start daemon: {e}")
        return 1

    # Wait for PID file
    if _wait_for(None, timeout=5.0):
        new_pid = _read_pid()
        print(f"✅ Daemon restarted (PID {new_pid})")
        return 0
    else:
        # The process may have written its own PID, check proc.pid
        if proc.poll() is None:
            print(f"✅ Daemon started (PID {proc.pid})")
            return 0
        else:
            print(f"❌ Daemon failed to start (exit code {proc.returncode})")
            return 1


def cmd_reload(_args: argparse.Namespace) -> int:
    """Reload daemon config (SIGHUP)."""
    pid = _read_pid()
    if pid is None:
        print("❌ Daemon is not running")
        return 1

    if not _is_alive(pid):
        print("❌ Daemon is not running (stale PID file)")
        _cleanup_pidfile()
        return 1

    try:
        os.kill(pid, signal.SIGHUP)
        print(f"✅ SIGHUP sent to daemon (PID {pid}) — config reloaded")
        return 0
    except ProcessLookupError:
        print("❌ Process gone")
        _cleanup_pidfile()
        return 1


def _cleanup_pidfile() -> None:
    """Remove PID file and stale socket."""
    for path in (PID_FILE, SOCKET_PATH):
        try:
            os.unlink(path)
        except FileNotFoundError:
            pass


def _find_project_root() -> str:
    """Find the NetSentry project root directory."""
    # Walk up from this file's location
    d = os.path.dirname(os.path.abspath(__file__))
    while d != "/":
        if os.path.isfile(os.path.join(d, "pyproject.toml")):
            return d
        d = os.path.dirname(d)
    return os.getcwd()


def main() -> int:
    parser = argparse.ArgumentParser(
        prog="netsentryctl",
        description="NetSentry daemon control utility",
    )
    parser.set_defaults(func=lambda _: parser.print_help())

    sub = parser.add_subparsers(title="commands")

    p_status = sub.add_parser("status", help="Show daemon status")
    p_status.set_defaults(func=cmd_status)

    p_stop = sub.add_parser("stop", help="Stop the daemon")
    p_stop.set_defaults(func=cmd_stop)

    p_restart = sub.add_parser("restart", help="Restart the daemon")
    p_restart.add_argument("--verbose", "-v", action="store_true", help="Verbose daemon output")
    p_restart.add_argument("--config", "-c", type=str, default=None, help="Config file path")
    p_restart.set_defaults(func=cmd_restart)

    p_reload = sub.add_parser("reload", help="Reload daemon config (SIGHUP)")
    p_reload.set_defaults(func=cmd_reload)

    args = parser.parse_args()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
