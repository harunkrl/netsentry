"""Tests for tui.data.provider — TUI data provider and process killer."""
from __future__ import annotations

import json
import os
import signal
import time
from pathlib import Path
from unittest.mock import patch, MagicMock

import pytest

from backend.models import Snapshot, SocketEntry, Alert
from shared import AlertLevel
from tui.data.provider import DataProvider


# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def data_file(tmp_path: Path) -> Path:
    return tmp_path / "test-data.json"


@pytest.fixture
def provider(data_file: Path) -> DataProvider:
    return DataProvider(data_path=str(data_file))


@pytest.fixture
def sample_json() -> str:
    entry = SocketEntry(
        proto="tcp", local_ip="0.0.0.0", local_port=22,
        remote_ip="0.0.0.0", remote_port=0, state="LISTEN",
        state_code="0A", uid=0, inode=12345,
    )
    snapshot = Snapshot(
        listening=[entry],
        established=[],
        alerts=[],
        summary={"total_listening": 1, "total_established": 0, "alert_count": 0},
    )
    return snapshot.to_json()


# ── Fetch tests ───────────────────────────────────────────────────

class TestFetch:
    def test_fetch_returns_snapshot(self, provider: DataProvider, data_file: Path, sample_json: str):
        data_file.write_text(sample_json)
        result = provider.fetch()
        assert result is not None
        assert isinstance(result, Snapshot)
        assert len(result.listening) == 1
        assert result.listening[0].local_port == 22

    def test_fetch_missing_file_returns_none(self, provider: DataProvider):
        result = provider.fetch()
        assert result is None

    def test_fetch_invalid_json_returns_none(self, provider: DataProvider, data_file: Path):
        data_file.write_text("not json")
        result = provider.fetch()
        assert result is None

    def test_fetch_empty_file_returns_none(self, provider: DataProvider, data_file: Path):
        data_file.write_text("")
        result = provider.fetch()
        assert result is None

    def test_fetch_partial_json_returns_none(self, provider: DataProvider, data_file: Path):
        data_file.write_text('{"timestamp": 123, "listening": [')
        result = provider.fetch()
        assert result is None

    @patch("builtins.open", side_effect=PermissionError("denied"))
    def test_fetch_permission_error_returns_none(self, mock_open, provider: DataProvider):
        result = provider.fetch()
        assert result is None

    def test_fetch_roundtrip_preserves_alerts(self, provider: DataProvider, data_file: Path):
        alert = Alert(
            level=AlertLevel.CRITICAL, port=4444, proto="tcp",
            process_name="suspicious", pid=999,
            message="Malicious port detected",
        )
        snapshot = Snapshot(alerts=[alert])
        data_file.write_text(snapshot.to_json())
        result = provider.fetch()
        assert result is not None
        assert len(result.alerts) == 1
        assert result.alerts[0].level == AlertLevel.CRITICAL
        assert result.alerts[0].port == 4444


# ── Kill process tests ────────────────────────────────────────────

class TestKillProcess:
    def test_invalid_pid_zero(self, provider: DataProvider):
        ok, msg = provider.kill_process(0)
        assert ok is False
        assert "Invalid" in msg

    def test_invalid_pid_negative(self, provider: DataProvider):
        ok, msg = provider.kill_process(-1)
        assert ok is False
        assert "Invalid" in msg

    @patch("os.kill", side_effect=ProcessLookupError("not found"))
    def test_process_not_found(self, mock_kill, provider: DataProvider):
        ok, msg = provider.kill_process(99999)
        assert ok is False
        assert "not found" in msg

    @patch("os.kill", side_effect=PermissionError("denied"))
    def test_permission_denied_check(self, mock_kill, provider: DataProvider):
        ok, msg = provider.kill_process(1)
        assert ok is False
        assert "Permission denied" in msg

    @patch("os.kill")
    def test_sigterm_succeeds_immediately(self, mock_kill, provider: DataProvider):
        """If process exits after SIGTERM, should succeed without SIGKILL."""
        call_count = {"n": 0}

        def mock_kill_fn(pid, sig):
            call_count["n"] += 1
            if sig == signal.SIGTERM:
                pass  # send SIGTERM ok
            elif sig == 0:
                # First check: process exists. Second check: gone.
                if call_count["n"] > 2:
                    raise ProcessLookupError

        mock_kill.side_effect = mock_kill_fn
        # Speed up the sleep
        with patch("time.sleep"):
            ok, msg = provider.kill_process(1234)
        assert ok is True
        assert "SIGTERM" in msg

    @patch("os.kill")
    def test_sigterm_then_sigkill(self, mock_kill, provider: DataProvider):
        """If SIGTERM doesn't kill, SIGKILL should be tried."""
        call_count = {"n": 0}

        def mock_kill_fn(pid, sig):
            call_count["n"] += 1
            if sig == signal.SIGKILL:
                # After SIGKILL, process is gone
                pass
            elif sig == 0 and call_count["n"] > 22:
                # After SIGKILL + final check, process gone
                raise ProcessLookupError

        mock_kill.side_effect = mock_kill_fn
        with patch("time.sleep"):
            ok, msg = provider.kill_process(1234)
        assert ok is True
        assert "SIGKILL" in msg

    @patch("os.kill")
    def test_kill_permission_denied_on_sigterm(self, mock_kill, provider: DataProvider):
        """If SIGTERM raises PermissionError, should return failure."""
        def mock_kill_fn(pid, sig):
            if sig == signal.SIGTERM:
                raise PermissionError
            elif sig == signal.SIGKILL:
                raise PermissionError

        mock_kill.side_effect = mock_kill_fn
        with patch("time.sleep"):
            ok, msg = provider.kill_process(1234)
        assert ok is False
        assert "Permission denied" in msg

    @patch("os.kill")
    def test_process_already_terminated(self, mock_kill, provider: DataProvider):
        """If process disappears between check and SIGTERM."""
        def mock_kill_fn(pid, sig):
            if sig == signal.SIGTERM:
                raise ProcessLookupError

        mock_kill.side_effect = mock_kill_fn
        ok, msg = provider.kill_process(1234)
        assert ok is True
        assert "already terminated" in msg
