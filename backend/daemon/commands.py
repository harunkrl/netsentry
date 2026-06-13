"""KPortWatch — Socket command handler.

Handles commands arriving over the Unix domain socket (e.g. kill requests).
Fully self-contained: owns its own rate-limiting state and UID authorization
logic.  No shared mutable state with the orchestrator.
"""

from __future__ import annotations

import logging
import os
import signal
import time

logger = logging.getLogger(__name__)


class CommandHandler:
    """Process Unix-socket commands with rate limiting and UID authorization."""

    # System PIDs that should never be killed
    PROTECTED_PIDS = frozenset({0, 1, 2})

    _MAX_KILL_RATE: int = 5  # max kill commands per minute

    def __init__(self) -> None:
        self._kill_timestamps: list[float] = []

    # ── Public API ────────────────────────────────────────────

    def handle_command(self, cmd: dict) -> dict:
        """Route an incoming socket command.

        Kill commands are rate-limited and require UID authorization
        (the requesting user must own the target process).

        Parameters
        ----------
        cmd:
            Dict with at least a ``"command"`` key.

        Returns
        -------
        dict
            ``{"status": "ok"|"error", "message": ...}``
        """
        command = cmd.get("command", "")
        if command == "kill":
            return self._handle_kill(cmd)
        return {"status": "error", "message": f"Unknown command: {command}"}

    # ── Kill implementation ───────────────────────────────────

    def _handle_kill(self, cmd: dict) -> dict:
        """Validate, authorize and execute a kill command."""
        pid_raw = cmd.get("pid")
        if pid_raw is None:
            return {"status": "error", "message": "Missing 'pid' field"}
        try:
            pid = int(pid_raw)
        except (ValueError, TypeError):
            return {"status": "error", "message": f"Invalid pid: {pid_raw}"}
        if pid <= 0:
            return {"status": "error", "message": f"Invalid pid: {pid}"}

        # Rate limiting — max N kill commands per 60 s
        now_ts = time.time()
        self._kill_timestamps[:] = [t for t in self._kill_timestamps if (now_ts - t) < 60.0]
        if len(self._kill_timestamps) >= self._MAX_KILL_RATE:
            logger.warning("Kill rate limit exceeded for PID %d", pid)
            return {
                "status": "error",
                "message": "Rate limit exceeded — too many kill requests",
            }

        # UID authorization — only allow killing processes owned by the same user
        try:
            target_uid = os.stat(f"/proc/{pid}").st_uid
        except (FileNotFoundError, PermissionError, OSError):
            target_uid = None
        if target_uid is not None and target_uid != os.getuid():
            logger.warning(
                "Kill denied: PID %d (uid=%d) not owned by daemon user (uid=%d)",
                pid,
                target_uid,
                os.getuid(),
            )
            return {
                "status": "error",
                "message": f"Permission denied: PID {pid} is not owned by this user",
            }

        self._kill_timestamps.append(now_ts)
        logger.info("Kill authorized for PID %d by uid=%d", pid, os.getuid())
        return self._kill_process(pid)

    @staticmethod
    def _kill_process(pid: int) -> dict:
        """Kill a process by PID with SIGTERM → wait → SIGKILL fallback."""
        if pid in CommandHandler.PROTECTED_PIDS or pid <= 0:
            return {
                "status": "error",
                "message": f"PID {pid} is protected and cannot be killed",
            }
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return {"status": "ok", "message": f"Process {pid} not found (already gone)"}
        except PermissionError:
            return {"status": "error", "message": f"Permission denied killing PID {pid}"}
        except OSError as e:
            return {"status": "error", "message": f"Error sending SIGTERM to {pid}: {e}"}

        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                logger.info("Process %d terminated gracefully after SIGTERM", pid)
                return {
                    "status": "ok",
                    "message": f"Process {pid} terminated (SIGTERM)",
                }
            except PermissionError:
                break

        try:
            os.kill(pid, signal.SIGKILL)
            logger.info("Process %d killed with SIGKILL after timeout", pid)
            return {"status": "ok", "message": f"Process {pid} killed (SIGKILL)"}
        except ProcessLookupError:
            return {
                "status": "ok",
                "message": f"Process {pid} terminated between checks",
            }
        except PermissionError:
            return {
                "status": "error",
                "message": f"Permission denied sending SIGKILL to PID {pid}",
            }
        except OSError as e:
            return {
                "status": "error",
                "message": f"Error sending SIGKILL to {pid}: {e}",
            }
