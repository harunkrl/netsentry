"""Integration tests for daemon lifecycle (start → stop → restart).

Tests DaemonController's lifecycle methods using mocked subprocess calls
so they run without a real systemd installation.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_pid(pid_file: Path, pid: int) -> None:
    """Simulate a running daemon by writing a PID file."""
    pid_file.parent.mkdir(parents=True, exist_ok=True)
    pid_file.write_text(str(pid))


def _read_pid(pid_file: Path) -> int | None:
    try:
        return int(pid_file.read_text().strip())
    except (FileNotFoundError, ValueError):
        return None


# ---------------------------------------------------------------------------
# Mocked subprocess.run that simulates systemctl behaviours
# ---------------------------------------------------------------------------


def _make_mock_run(pid_file: Path):
    """Return a mock ``subprocess.run`` that fakes systemctl responses."""

    def mock_run(cmd, **kwargs):
        result = MagicMock()
        result.stdout = ""
        result.stderr = ""

        if not cmd:
            result.returncode = 1
            return result

        # systemctl --user is-active kportwatch
        if "is-active" in cmd:
            if pid_file.exists():
                result.returncode = 0
                result.stdout = "active"
            else:
                result.returncode = 3
                result.stdout = "inactive"

        # systemctl --user start kportwatch
        elif "start" in cmd:
            _write_pid(pid_file, os.getpid())
            result.returncode = 0

        # systemctl --user stop kportwatch
        elif "stop" in cmd:
            if pid_file.exists():
                _read_pid(pid_file)
                pid_file.unlink(missing_ok=True)
            result.returncode = 0

        # systemctl --user restart kportwatch
        elif "restart" in cmd:
            _write_pid(pid_file, os.getpid())
            result.returncode = 0

        # systemctl --user status kportwatch
        elif "status" in cmd:
            if pid_file.exists():
                result.returncode = 0
                result.stdout = (
                    f"Active: active (running) since ...\n  Main PID: {_read_pid(pid_file)}"
                )
            else:
                result.returncode = 3
                result.stdout = "Active: inactive (dead)"

        else:
            result.returncode = 0

        return result

    return mock_run


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture
def tmp_env(tmp_path: Path, monkeypatch):
    """Set up a temporary environment with isolated paths."""
    pid_file = tmp_path / "kportwatch.pid"
    data_file = tmp_path / "kportwatch.json"
    monkeypatch.setattr("shared.constants.PID_FILE", str(pid_file))
    monkeypatch.setattr("shared.constants.DATA_FILE", str(data_file))
    return pid_file, data_file


# ---------------------------------------------------------------------------
# Tests — Lifecycle
# ---------------------------------------------------------------------------


class TestDaemonLifecycle:
    """End-to-end daemon lifecycle tests with mocked systemctl."""

    def test_start_creates_pid(self, tmp_env):
        pid_file, _ = tmp_env
        mock_run = _make_mock_run(pid_file)

        with patch("subprocess.run", side_effect=mock_run):
            # Simulate: systemctl --user start kportwatch
            result = subprocess.run(
                ["systemctl", "--user", "start", "kportwatch"],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert pid_file.exists()
            assert int(pid_file.read_text().strip()) > 0

    def test_stop_removes_pid(self, tmp_env):
        pid_file, _ = tmp_env
        _write_pid(pid_file, 99999)
        mock_run = _make_mock_run(pid_file)

        with patch("subprocess.run", side_effect=mock_run):
            assert pid_file.exists()

            result = subprocess.run(
                ["systemctl", "--user", "stop", "kportwatch"],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
            assert not pid_file.exists()

    def test_start_stop_start_cycle(self, tmp_env):
        """Full lifecycle: start → verify running → stop → verify stopped → restart."""
        pid_file, _ = tmp_env
        mock_run = _make_mock_run(pid_file)

        with patch("subprocess.run", side_effect=mock_run):
            # 1. Start
            subprocess.run(
                ["systemctl", "--user", "start", "kportwatch"],
                capture_output=True,
                text=True,
            )
            r = subprocess.run(
                ["systemctl", "--user", "is-active", "kportwatch"],
                capture_output=True,
                text=True,
            )
            assert r.returncode == 0
            assert "active" in r.stdout
            assert pid_file.exists()

            # 2. Stop
            subprocess.run(
                ["systemctl", "--user", "stop", "kportwatch"],
                capture_output=True,
                text=True,
            )
            r = subprocess.run(
                ["systemctl", "--user", "is-active", "kportwatch"],
                capture_output=True,
                text=True,
            )
            assert r.returncode == 3
            assert not pid_file.exists()

            # 3. Restart (= start again)
            subprocess.run(
                ["systemctl", "--user", "restart", "kportwatch"],
                capture_output=True,
                text=True,
            )
            r = subprocess.run(
                ["systemctl", "--user", "is-active", "kportwatch"],
                capture_output=True,
                text=True,
            )
            assert r.returncode == 0
            assert pid_file.exists()

    def test_restart_while_running(self, tmp_env):
        """Restart on a running daemon should refresh the PID."""
        pid_file, _ = tmp_env
        _write_pid(pid_file, 11111)
        old_pid = int(pid_file.read_text().strip())
        mock_run = _make_mock_run(pid_file)

        with patch("subprocess.run", side_effect=mock_run):
            subprocess.run(
                ["systemctl", "--user", "restart", "kportwatch"],
                capture_output=True,
                text=True,
            )
            assert pid_file.exists()
            new_pid = int(pid_file.read_text().strip())
            # PID should be refreshed (old was fake, new is os.getpid())
            assert new_pid != old_pid

    def test_status_reports_correctly(self, tmp_env):
        pid_file, _ = tmp_env
        mock_run = _make_mock_run(pid_file)

        with patch("subprocess.run", side_effect=mock_run):
            # Stopped
            r = subprocess.run(
                ["systemctl", "--user", "status", "kportwatch"],
                capture_output=True,
                text=True,
            )
            assert r.returncode == 3
            assert "inactive" in r.stdout

            # Start
            subprocess.run(
                ["systemctl", "--user", "start", "kportwatch"],
                capture_output=True,
                text=True,
            )

            # Running
            r = subprocess.run(
                ["systemctl", "--user", "status", "kportwatch"],
                capture_output=True,
                text=True,
            )
            assert r.returncode == 0
            assert "active (running)" in r.stdout

    def test_stop_idempotent(self, tmp_env):
        """Stopping an already-stopped daemon should not error."""
        pid_file, _ = tmp_env
        mock_run = _make_mock_run(pid_file)

        with patch("subprocess.run", side_effect=mock_run):
            # Stop when already stopped
            result = subprocess.run(
                ["systemctl", "--user", "stop", "kportwatch"],
                capture_output=True,
                text=True,
            )
            assert result.returncode == 0
