"""Tests for backend.kportwatch_daemon — daemon lifecycle and helpers."""
from __future__ import annotations

import json
import os
import time
from pathlib import Path
from unittest.mock import patch

import pytest
from backend.kportwatch_daemon import (
    classify_entries,
    merge_inode_map,
    parse_args,
    setup_logging,
)
from backend.models import SocketEntry

# ── Fixtures ──────────────────────────────────────────────────────

@pytest.fixture
def listening_tcp() -> SocketEntry:
    return SocketEntry(
        proto="tcp", local_ip="0.0.0.0", local_port=22,
        remote_ip="0.0.0.0", remote_port=0, state="LISTEN",
        state_code="0A", uid=0, inode=100,
    )


@pytest.fixture
def established_tcp() -> SocketEntry:
    return SocketEntry(
        proto="tcp", local_ip="192.168.1.10", local_port=44532,
        remote_ip="142.250.80.14", remote_port=443, state="ESTABLISHED",
        state_code="01", uid=1000, inode=200,
    )


@pytest.fixture
def unconn_udp() -> SocketEntry:
    return SocketEntry(
        proto="udp", local_ip="0.0.0.0", local_port=5353,
        remote_ip="0.0.0.0", remote_port=0, state="UNCONN",
        state_code="07", uid=0, inode=300,
    )


# ── classify_entries tests ────────────────────────────────────────

class TestClassifyEntries:
    def test_splits_listening_and_established(self, listening_tcp, established_tcp):
        listening, established = classify_entries([listening_tcp, established_tcp])
        assert len(listening) == 1
        assert len(established) == 1
        assert listening[0].local_port == 22
        assert established[0].local_port == 44532

    def test_udp_unconn_classified_as_listening(self, unconn_udp):
        listening, _established = classify_entries([unconn_udp])
        assert len(listening) == 1
        assert listening[0].proto == "udp"

    def test_empty_input(self):
        listening, established = classify_entries([])
        assert listening == []
        assert established == []

    def test_multiple_states(self, listening_tcp, established_tcp, unconn_udp):
        listening, established = classify_entries([
            listening_tcp, established_tcp, unconn_udp,
        ])
        assert len(listening) == 2  # LISTEN + UNCONN
        assert len(established) == 1

    def test_time_wait_goes_to_established(self):
        tw = SocketEntry(
            proto="tcp", local_ip="1.2.3.4", local_port=12345,
            remote_ip="5.6.7.8", remote_port=80, state="TIME_WAIT",
            state_code="06", uid=1000, inode=400,
        )
        listening, established = classify_entries([tw])
        assert len(established) == 1
        assert len(listening) == 0


# ── merge_inode_map tests ─────────────────────────────────────────

class TestMergeInodeMap:
    @patch("backend.kportwatch_daemon.build_uid_process_map")
    @patch("backend.kportwatch_daemon.build_inode_to_pid_map")
    def test_inode_map_enriches_entries(self, mock_build, mock_uid):
        mock_build.return_value = {
            100: (1, "sshd", "/usr/sbin/sshd -D"),
        }
        mock_uid.return_value = {}
        entry = SocketEntry(
            proto="tcp", local_ip="0.0.0.0", local_port=22,
            remote_ip="0.0.0.0", remote_port=0, state="LISTEN",
            state_code="0A", uid=0, inode=100,
        )
        merge_inode_map([entry])
        assert entry.pid == 1
        assert entry.process_name == "sshd"
        assert entry.cmdline == "/usr/sbin/sshd -D"

    @patch("backend.kportwatch_daemon.build_uid_process_map")
    @patch("backend.kportwatch_daemon.build_inode_to_pid_map")
    def test_inode_not_found_leaves_pid_none(self, mock_build, mock_uid):
        mock_build.return_value = {}
        mock_uid.return_value = {}  # no UID fallback either
        entry = SocketEntry(
            proto="tcp", local_ip="0.0.0.0", local_port=22,
            remote_ip="0.0.0.0", remote_port=0, state="LISTEN",
            state_code="0A", uid=0, inode=99999,
        )
        merge_inode_map([entry])
        assert entry.pid is None
        assert entry.process_name is None

    @patch("backend.kportwatch_daemon.build_uid_process_map")
    @patch("backend.kportwatch_daemon.build_inode_to_pid_map")
    def test_uid_fallback_resolves_process(self, mock_build, mock_uid):
        mock_build.return_value = {}  # inode not found
        mock_uid.return_value = {0: ("root", "sshd", "/usr/sbin/sshd -D")}
        entry = SocketEntry(
            proto="tcp", local_ip="0.0.0.0", local_port=22,
            remote_ip="0.0.0.0", remote_port=0, state="LISTEN",
            state_code="0A", uid=0, inode=99999,
        )
        merge_inode_map([entry])
        assert entry.pid is None
        assert entry.process_name == "sshd (root)"

    @patch("backend.kportwatch_daemon.build_uid_process_map")
    @patch("backend.kportwatch_daemon.build_inode_to_pid_map")
    def test_empty_entries_list(self, mock_build, mock_uid):
        mock_build.return_value = {100: (1, "test", "./test")}
        mock_uid.return_value = {}
        merge_inode_map([])  # should not crash
        mock_build.assert_called_once()


# ── parse_args tests ──────────────────────────────────────────────

class TestParseArgs:
    def test_defaults(self):
        with patch("sys.argv", ["kportwatch-daemon"]):
            args = parse_args()
        assert args.foreground is False
        assert args.verbose is False
        assert args.interval is None  # None = use config file value

    def test_foreground_flag(self):
        with patch("sys.argv", ["kportwatch-daemon", "--foreground"]):
            args = parse_args()
        assert args.foreground is True

    def test_verbose_flag(self):
        with patch("sys.argv", ["kportwatch-daemon", "--verbose"]):
            args = parse_args()
        assert args.verbose is True

    def test_custom_interval(self):
        with patch("sys.argv", ["kportwatch-daemon", "--interval", "5"]):
            args = parse_args()
        assert args.interval == 5.0

    def test_short_flags(self):
        with patch("sys.argv", ["kportwatch-daemon", "-f", "-v", "-i", "3"]):
            args = parse_args()
        assert args.foreground is True
        assert args.verbose is True
        assert args.interval == 3.0


# ── setup_logging tests ───────────────────────────────────────────

class TestSetupLogging:
    def test_verbose_sets_debug(self):
        import logging
        # Remove existing handlers so basicConfig takes effect
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        original_level = root.level
        root.handlers.clear()
        try:
            setup_logging(verbose=True)
            assert root.level == logging.DEBUG
        finally:
            root.handlers = original_handlers
            root.setLevel(original_level)

    def test_normal_sets_info(self):
        import logging
        root = logging.getLogger()
        original_handlers = root.handlers[:]
        original_level = root.level
        root.handlers.clear()
        try:
            setup_logging(verbose=False)
            assert root.level == logging.INFO
        finally:
            root.handlers = original_handlers
            root.setLevel(original_level)


# ── Baseline save/load integration ────────────────────────────────

class TestBaselineIntegration:
    def test_baseline_file_created_on_save(self, tmp_path: Path):
        from backend.alert_engine import AlertEngine
        baseline_file = str(tmp_path / "baseline.json")
        engine = AlertEngine()
        engine._baseline_ports = {22, 80, 443}
        engine._baseline_stable = True
        engine.save_baseline(baseline_file)

        assert os.path.exists(baseline_file)
        with open(baseline_file) as f:
            data = json.load(f)
        assert sorted(data["ports"]) == [22, 80, 443]
        assert "timestamp" in data

    def test_baseline_roundtrip(self, tmp_path: Path):
        from backend.alert_engine import AlertEngine
        baseline_file = str(tmp_path / "baseline.json")

        # Save
        engine1 = AlertEngine()
        engine1._baseline_ports = {22, 80, 443, 5353}
        engine1._baseline_stable = True
        engine1.save_baseline(baseline_file)

        # Load
        engine2 = AlertEngine()
        assert engine2.load_baseline(baseline_file) is True
        assert engine2._baseline_ports == {22, 80, 443, 5353}
        assert engine2._baseline_stable is True

    def test_load_corrupt_baseline_returns_false(self, tmp_path: Path):
        from backend.alert_engine import AlertEngine
        baseline_file = str(tmp_path / "baseline.json")

        # Write corrupt data
        with open(baseline_file, "w") as f:
            f.write("{not valid json")

        engine = AlertEngine()
        assert engine.load_baseline(baseline_file) is False

    def test_load_baseline_with_non_int_ports_skipped(self, tmp_path: Path):
        from backend.alert_engine import AlertEngine
        baseline_file = str(tmp_path / "baseline.json")

        with open(baseline_file, "w") as f:
            json.dump({"ports": [22, "bad", 443, -1, 70000, 80]}, f)

        engine = AlertEngine()
        assert engine.load_baseline(baseline_file) is True
        # Only valid ports should be loaded
        assert engine._baseline_ports == {22, 443, 80}

    def test_load_baseline_missing_ports_key(self, tmp_path: Path):
        from backend.alert_engine import AlertEngine
        baseline_file = str(tmp_path / "baseline.json")

        with open(baseline_file, "w") as f:
            json.dump({"timestamp": 12345}, f)

        engine = AlertEngine()
        assert engine.load_baseline(baseline_file) is False

    def test_load_baseline_ports_not_list(self, tmp_path: Path):
        from backend.alert_engine import AlertEngine
        baseline_file = str(tmp_path / "baseline.json")

        with open(baseline_file, "w") as f:
            json.dump({"ports": "not a list"}, f)

        engine = AlertEngine()
        assert engine.load_baseline(baseline_file) is False


# ── Heartbeat tests ─────────────────────────────────────────────────

class TestHeartbeat:
    def test_write_heartbeat_creates_file(self, tmp_path: Path):
        from backend.kportwatch_daemon import _write_heartbeat
        hb_path = str(tmp_path / "heartbeat.json")
        _write_heartbeat(hb_path)
        assert os.path.exists(hb_path)

    def test_heartbeat_contains_timestamp(self, tmp_path: Path):
        from backend.kportwatch_daemon import _write_heartbeat
        hb_path = str(tmp_path / "heartbeat.json")
        _write_heartbeat(hb_path)
        with open(hb_path) as f:
            data = json.load(f)
        assert "ts" in data
        assert isinstance(data["ts"], float)
        assert data["ts"] > 0

    def test_heartbeat_updates_on_rewrite(self, tmp_path: Path):
        from backend.kportwatch_daemon import _write_heartbeat
        hb_path = str(tmp_path / "heartbeat.json")
        _write_heartbeat(hb_path)
        with open(hb_path) as f:
            ts1 = json.load(f)["ts"]

        time.sleep(0.05)
        _write_heartbeat(hb_path)
        with open(hb_path) as f:
            ts2 = json.load(f)["ts"]

        assert ts2 > ts1

    def test_heartbeat_no_error_on_bad_path(self):
        from backend.kportwatch_daemon import _write_heartbeat
        # Should not raise — heartbeat is best-effort
        _write_heartbeat("/nonexistent/dir/heartbeat.json")
