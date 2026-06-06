"""KPortWatch TUI — data provider.

Reads the JSON snapshot written by the backend daemon and provides
process-kill capability.

K6: Socket I/O uses timeout to prevent indefinite blocking.
K11: kill_process() is designed to be called via ``run_in_executor``
     or ``asyncio.to_thread`` to avoid blocking the TUI event loop.
"""
from __future__ import annotations

import json
import os
import signal
import time

from backend.models import Snapshot
from shared import DATA_FILE


class DataProvider:
    """Bridge between the TUI and the backend data source.

    All potentially blocking I/O operations include timeouts to
    prevent the TUI from freezing if the daemon is unresponsive.
    """

    def __init__(self, data_path: str = DATA_FILE) -> None:
        self.data_path = data_path

    # ── Fetch snapshot ────────────────────────────────────────
    def fetch(self) -> Snapshot | None:
        """Read the latest JSON snapshot from disk.

        Returns ``None`` when the file is missing, unreadable, or
        contains invalid JSON.
        """
        try:
            with open(self.data_path) as fh:
                raw = fh.read()
        except FileNotFoundError:
            return None
        except PermissionError:
            return None
        except OSError:
            return None

        try:
            return Snapshot.from_json(raw)
        except (json.JSONDecodeError, KeyError, TypeError):
            return None

    # ── Kill a process ────────────────────────────────────────
    def kill_process(self, pid: int) -> tuple[bool, str]:
        """Attempt to terminate *pid* gracefully, then forcibly.

        Returns ``(success, message)``.

        K8: Handles PermissionError and ProcessLookupError gracefully.
        K11: This method is blocking (up to ~2.2s) and should be called
             via ``asyncio.to_thread()`` from the TUI to avoid freezing.
        """
        if pid <= 0:
            return False, f"Invalid PID {pid}"

        # Check process exists first
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return False, f"Process {pid} not found — may have already terminated"
        except PermissionError:
            return False, (
                f"Permission denied — cannot signal PID {pid}. "
                "Try running with elevated privileges."
            )

        # SIGTERM
        try:
            os.kill(pid, signal.SIGTERM)
        except PermissionError:
            return False, f"Permission denied — cannot signal PID {pid}"
        except ProcessLookupError:
            return True, f"Process {pid} already terminated"

        # Wait up to 2 seconds for graceful exit
        for _ in range(20):
            time.sleep(0.1)
            try:
                os.kill(pid, 0)
            except ProcessLookupError:
                return True, f"Process {pid} terminated gracefully (SIGTERM)"
            except PermissionError:
                break  # still alive but we can't signal → fall through

        # SIGKILL
        try:
            os.kill(pid, signal.SIGKILL)
        except ProcessLookupError:
            return True, f"Process {pid} terminated gracefully (SIGTERM)"
        except PermissionError:
            return False, (
                f"Permission denied — cannot kill PID {pid}. "
                "Try running with elevated privileges."
            )

        # Brief wait to confirm
        time.sleep(0.2)
        try:
            os.kill(pid, 0)
        except ProcessLookupError:
            return True, f"Process {pid} killed (SIGKILL)"
        except PermissionError:
            pass

        return False, f"Failed to kill process {pid}"
