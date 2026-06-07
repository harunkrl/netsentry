"""KPortWatch — Tests for the refactored daemon package.

Tests are organised by the component they target:
  - DaemonController (orchestrator) lifecycle & integration tests
  - CommandHandler (socket commands)
  - DataCollector (data gathering)
  - SnapshotBuilder (risk scores, snapshot assembly, publishing)
  - NotificationManager (desktop notifications)
"""
from __future__ import annotations

import os
import signal
import time
from unittest.mock import Mock, patch

import pytest
from backend.daemon.commands import CommandHandler
from backend.daemon.collector import CollectedData, DataCollector
from backend.daemon.notifications import NotificationManager
from backend.daemon.snapshot import SnapshotBuilder
from backend.daemon.controller import DaemonController
from backend.models import Alert, AlertLevel, InterfaceStats, SocketEntry
from shared.config import AppConfig


# ── Shared Fixtures ───────────────────────────────────────────────


@pytest.fixture
def mock_args():
    """Return a mock args object with interval attribute."""
    args = Mock()
    args.interval = None
    return args


@pytest.fixture
def mock_config():
    """Return a mock AppConfig with minimal configuration."""
    cfg = AppConfig()
    cfg.poll_interval = 2.0
    cfg.alert_poll_interval = 1.0
    cfg.idle_poll_interval = 10.0
    cfg.idle_threshold_secs = 300.0
    cfg.notifications_enabled = True
    cfg.notification_rate_limit = 10
    cfg.notification_rate_window = 60.0
    cfg.alert_ttl = 3600.0
    cfg.geoip_enabled = False
    cfg.update_enabled = False
    cfg.data_file = "/tmp/test-kportwatch-data.json"
    cfg.socket_path = "/tmp/test-kportwatch.sock"
    cfg.baseline_file = "/tmp/test-baseline.json"
    cfg.heartbeat_file = "/tmp/test-heartbeat.json"
    cfg.history_retention_days = 30
    cfg.baseline_duration = 300.0
    return cfg


@pytest.fixture
def controller(mock_args, mock_config):
    """Return a DaemonController instance with mocked _init_components."""
    with patch.object(DaemonController, "_init_components"):
        ctrl = DaemonController(mock_args)
        ctrl.cfg = mock_config
        ctrl.alert_engine = Mock()
        ctrl.alert_engine.malicious_ports = set()
        ctrl.alert_engine.known_safe = {}
        ctrl.alert_engine.port_blacklist = set()
        ctrl.history = Mock()
        ctrl.socket_server = Mock()
        ctrl.running = True
        yield ctrl


@pytest.fixture
def command_handler():
    """Return a fresh CommandHandler instance."""
    return CommandHandler()


@pytest.fixture
def sample_alert():
    """Return a sample Alert for testing notifications."""
    return Alert(
        level=AlertLevel.WARNING,
        port=8080,
        proto="tcp",
        process_name="nginx",
        pid=1234,
        message="Unknown privileged port 8080 detected",
        timestamp=time.time(),
    )


@pytest.fixture
def critical_alert():
    """Return a CRITICAL level alert for testing notifications."""
    return Alert(
        level=AlertLevel.CRITICAL,
        port=4444,
        proto="tcp",
        process_name="ncat",
        pid=5678,
        message="Known malicious port 4444 detected",
        timestamp=time.time(),
    )


@pytest.fixture
def sample_listening_entries():
    """Return sample listening socket entries."""
    return [
        SocketEntry(
            proto="tcp",
            local_ip="0.0.0.0",
            local_port=22,
            remote_ip="0.0.0.0",
            remote_port=0,
            state="LISTEN",
            state_code="0A",
            uid=0,
            inode=12345,
            pid=1,
            process_name="sshd",
            cmdline="/usr/sbin/sshd -D",
        ),
        SocketEntry(
            proto="tcp",
            local_ip="0.0.0.0",
            local_port=80,
            remote_ip="0.0.0.0",
            remote_port=0,
            state="LISTEN",
            state_code="0A",
            uid=0,
            inode=67890,
            pid=2,
            process_name="nginx",
            cmdline="/usr/sbin/nginx",
        ),
    ]


# ══════════════════════════════════════════════════════════════════
#  DaemonController Tests (orchestrator)
# ══════════════════════════════════════════════════════════════════


class TestInitialization:
    def test_default_initialization(self, mock_args):
        """Test that DaemonController initializes with correct defaults."""
        with patch.object(DaemonController, "_init_components"):
            ctrl = DaemonController(mock_args)
            assert ctrl.running is True
            assert ctrl.interval == 2.0
            assert ctrl._last_snapshot_hash is None
            assert ctrl._last_change_time > 0
            assert ctrl._error_count == 0
            assert ctrl._prev_baseline == frozenset()

    def test_protected_pids_constant(self):
        """Test that PROTECTED_PIDS includes system PIDs."""
        assert {0, 1, 2} == CommandHandler.PROTECTED_PIDS

    def test_max_kill_rate_constant(self):
        """Test that _MAX_KILL_RATE is set correctly."""
        assert CommandHandler._MAX_KILL_RATE == 5


# ── Adaptive Interval (stays in orchestrator) ──────────────────


class TestAdaptiveInterval:
    def test_default_interval_no_changes(self, controller, sample_listening_entries):
        """Test default interval when no changes and no alerts."""
        controller._last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in sample_listening_entries)
        )
        controller._last_change_time = time.time() - 50

        interval = controller._adaptive_interval(sample_listening_entries, [])

        assert interval == controller.cfg.poll_interval

    def test_alert_interval_when_alerts_present(self, controller, sample_listening_entries, sample_alert):
        """Test that alert_poll_interval is used when alerts are present."""
        interval = controller._adaptive_interval(sample_listening_entries, [sample_alert])

        assert interval == controller.cfg.alert_poll_interval

    def test_idle_interval_when_no_changes_for_threshold(self, controller, sample_listening_entries):
        """Test that idle_poll_interval is used when idle threshold exceeded."""
        controller._last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in sample_listening_entries)
        )
        controller._last_change_time = time.time() - 400

        interval = controller._adaptive_interval(sample_listening_entries, [])

        assert interval == controller.cfg.idle_poll_interval

    def test_updates_hash_on_change(self, controller, sample_listening_entries):
        """Test that _last_snapshot_hash is updated when listening ports change."""
        initial_entries = [sample_listening_entries[0]]
        controller._last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in initial_entries)
        )

        controller._adaptive_interval(sample_listening_entries, [])

        new_hash = hash(frozenset((e.local_port, e.proto, e.state) for e in sample_listening_entries))
        assert controller._last_snapshot_hash == new_hash
        assert controller._last_snapshot_hash != hash(
            frozenset((e.local_port, e.proto, e.state) for e in initial_entries)
        )

    def test_updates_change_time_on_change(self, controller, sample_listening_entries):
        """Test that _last_change_time is updated when listening ports change."""
        controller._last_snapshot_hash = 12345
        controller._last_change_time = time.time() - 1000

        with patch("time.time", return_value=12345.0):
            controller._adaptive_interval(sample_listening_entries, [])

        assert controller._last_change_time == 12345.0

    def test_empty_listening_uses_default_interval(self, controller):
        """Test that empty listening list uses default interval."""
        interval = controller._adaptive_interval([], [])

        assert interval == controller.cfg.poll_interval

    def test_multiple_alerts_still_uses_alert_interval(self, controller, sample_listening_entries):
        """Test that multiple alerts still use alert_poll_interval."""
        alerts = [
            Alert(level=AlertLevel.WARNING, port=8000, proto="tcp", process_name="app1", pid=1000, message="Alert 1"),
            Alert(level=AlertLevel.CRITICAL, port=9000, proto="tcp", process_name="app2", pid=2000, message="Alert 2"),
        ]

        interval = controller._adaptive_interval(sample_listening_entries, alerts)

        assert interval == controller.cfg.alert_poll_interval

    def test_exactly_at_idle_threshold(self, controller, sample_listening_entries):
        """Test behavior exactly at idle threshold boundary."""
        controller._last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in sample_listening_entries)
        )
        controller._last_change_time = time.time() - controller.cfg.idle_threshold_secs + 0.001

        interval = controller._adaptive_interval(sample_listening_entries, [])

        assert interval == controller.cfg.poll_interval

    def test_just_over_idle_threshold(self, controller, sample_listening_entries):
        """Test behavior just over idle threshold."""
        controller._last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in sample_listening_entries)
        )
        controller._last_change_time = time.time() - (controller.cfg.idle_threshold_secs + 1)

        interval = controller._adaptive_interval(sample_listening_entries, [])

        assert interval == controller.cfg.idle_poll_interval

    def test_state_change_included_in_hash(self, controller):
        """Test that socket state is included in hash calculation."""
        entry1 = SocketEntry(
            proto="tcp", local_ip="0.0.0.0", local_port=80, remote_ip="0.0.0.0", remote_port=0,
            state="LISTEN", state_code="0A", uid=0, inode=100, pid=1, process_name="nginx",
        )
        entry2 = SocketEntry(
            proto="tcp", local_ip="0.0.0.0", local_port=80, remote_ip="0.0.0.0", remote_port=0,
            state="ESTABLISHED", state_code="01", uid=0, inode=101, pid=1, process_name="nginx",
        )

        controller._last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in [entry1])
        )

        controller._adaptive_interval([entry2], [])

        assert controller._last_snapshot_hash != hash(
            frozenset((e.local_port, e.proto, e.state) for e in [entry1])
        )


# ── Error Counting (stays in orchestrator) ─────────────────────


class TestErrorCounting:
    def test_error_count_initial_zero(self, mock_args):
        with patch.object(DaemonController, "_init_components"):
            ctrl = DaemonController(mock_args)
            assert ctrl._error_count == 0

    def test_error_count_resets_on_success(self, controller):
        controller._error_count = 5
        controller._error_count = 0
        assert controller._error_count == 0

    def test_error_count_increments_on_error(self, controller):
        controller._error_count = 2
        controller._error_count += 1
        assert controller._error_count == 3

    def test_error_count_stops_at_threshold(self, controller):
        controller._error_count = 10
        assert controller._error_count >= 10

    def test_error_count_below_threshold_continues(self, controller):
        controller._error_count = 9
        assert controller._error_count < 10

    def test_consecutive_errors_increment(self, controller):
        for _i in range(5):
            controller._error_count += 1
        assert controller._error_count == 5

    def test_error_count_tracks_consecutive_failures(self, controller):
        controller._error_count = 0
        for _ in range(3):
            controller._error_count += 1
        assert controller._error_count == 3
        controller._error_count = 0
        assert controller._error_count == 0
        controller._error_count += 1
        assert controller._error_count == 1

    def test_error_count_threshold_prevents_infinite_loop(self, controller):
        for _ in range(10):
            controller._error_count += 1
        assert controller._error_count == 10
        controller.running = False
        assert controller.running is False

    def test_error_count_not_incremented_directly(self, controller):
        initial_count = controller._error_count
        controller._error_count += 1
        assert controller._error_count == initial_count + 1


# ── Cleanup (stays in orchestrator) ────────────────────────────


class TestCleanup:
    def test_cleanup_closes_history(self, controller):
        controller._cleanup()
        controller.history.close.assert_called_once()

    def test_cleanup_with_none_history(self, controller):
        controller.history = None
        controller._cleanup()

    def test_cleanup_saves_baseline(self, controller):
        controller.cfg = Mock()
        controller.cfg.baseline_file = "/tmp/test-baseline.json"
        controller.alert_engine = Mock()
        controller.socket_server = None
        controller._cleanup()
        controller.alert_engine.save_baseline.assert_called_once_with(controller.cfg.baseline_file)

    def test_cleanup_stops_socket_server(self, controller):
        controller.socket_server = Mock()
        controller.history = Mock()
        controller.alert_engine = None
        controller._cleanup()
        controller.socket_server.stop.assert_called_once()

    def test_cleanup_with_none_socket_server(self, controller):
        controller.socket_server = None
        controller.history = Mock()
        controller.alert_engine = None
        controller._cleanup()

    def test_cleanup_with_none_alert_engine(self, controller):
        controller.alert_engine = None
        controller.socket_server = None
        controller.history = Mock()
        controller._cleanup()

    def test_cleanup_unlinks_pid_file(self, controller, tmp_path):
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345")
        controller.history = Mock()
        controller.socket_server = None
        controller.alert_engine = None

        with patch("backend.daemon.controller.PID_FILE", str(pid_file)):
            controller._cleanup()

        assert not pid_file.exists()

    def test_cleanup_handles_missing_pid_file(self, controller):
        controller.history = Mock()
        controller.socket_server = None
        controller.alert_engine = None

        with patch("backend.daemon.controller.PID_FILE", "/tmp/nonexistent-kportwatch.pid"):
            controller._cleanup()

    def test_cleanup_flushes_geoip_cache_when_enabled(self, controller):
        controller.cfg = Mock()
        controller.cfg.geoip_enabled = True
        controller.alert_engine = None
        controller.socket_server = None
        controller.history = Mock()

        with patch("backend.daemon.controller.geoip_mod") as mock_geoip:
            controller._cleanup()
            mock_geoip.flush_cache.assert_called_once()

    def test_cleanup_skips_geoip_flush_when_disabled(self, controller):
        controller.cfg = Mock()
        controller.cfg.geoip_enabled = False
        controller.alert_engine = None
        controller.socket_server = None
        controller.history = Mock()

        with patch("backend.daemon.controller.geoip_mod") as mock_geoip:
            controller._cleanup()
            mock_geoip.flush_cache.assert_not_called()

    def test_cleanup_does_not_suppress_all_exceptions(self, controller):
        controller.history = Mock()
        controller.history.close.side_effect = Exception("History close error")
        controller.socket_server = None
        controller.alert_engine = None
        controller.cfg = Mock()
        controller.cfg.geoip_enabled = False

        with pytest.raises(Exception, match="History close error"):
            controller._cleanup()
        controller.history.close.assert_called_once()


# ── Integration Tests (orchestrator-level) ─────────────────────


class TestIntegration:
    def test_full_command_flow_valid_kill(self, controller, monkeypatch):
        """Test full flow of valid kill command via CommandHandler."""
        handler = CommandHandler()
        test_pid = 12345
        test_uid = os.getuid()

        mock_stat_result = Mock()
        mock_stat_result.st_uid = test_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        with patch.object(CommandHandler, "_kill_process", return_value={"status": "ok", "message": "SIGTERM"}):
            result = handler.handle_command({"command": "kill", "pid": test_pid})

        assert result["status"] == "ok"

    def test_notification_flow_with_multiple_alerts(self, mock_config):
        """Test notification flow with multiple alert types."""
        nm = NotificationManager(mock_config)
        alerts = [
            Alert(level=AlertLevel.INFO, port=8000, proto="tcp", process_name="app1", pid=1000, message="Info"),
            Alert(level=AlertLevel.WARNING, port=9000, proto="tcp", process_name="app2", pid=2000, message="Warning"),
            Alert(level=AlertLevel.CRITICAL, port=4444, proto="tcp", process_name="app3", pid=3000, message="Critical"),
        ]

        with patch("subprocess.Popen") as mock_popen:
            nm.handle(alerts)

        assert mock_popen.call_count == 2

    def test_adaptive_interval_flow_active_to_idle(self, controller, sample_listening_entries):
        """Test interval flow from active to idle state."""
        controller._last_change_time = time.time() - 10
        controller._last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in sample_listening_entries)
        )

        interval1 = controller._adaptive_interval(sample_listening_entries, [])
        assert interval1 == controller.cfg.poll_interval

        controller._last_change_time = time.time() - 400
        interval2 = controller._adaptive_interval(sample_listening_entries, [])
        assert interval2 == controller.cfg.idle_poll_interval

    def test_error_recovery_flow(self, controller):
        assert controller._error_count == 0
        for _ in range(3):
            controller._error_count += 1
        assert controller._error_count == 3
        controller._error_count = 0
        assert controller._error_count == 0
        controller._error_count += 1
        assert controller._error_count == 1


# ══════════════════════════════════════════════════════════════════
#  CommandHandler Tests
# ══════════════════════════════════════════════════════════════════


class TestHandleSocketCommand:
    def test_kill_command_valid_pid_same_uid(self, command_handler, monkeypatch):
        test_pid = 12345
        test_uid = os.getuid()
        mock_stat_result = Mock()
        mock_stat_result.st_uid = test_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        with patch.object(CommandHandler, "_kill_process", return_value={"status": "ok", "message": "Process killed"}):
            result = command_handler.handle_command({"command": "kill", "pid": test_pid})

        assert result["status"] == "ok"

    def test_kill_command_missing_pid(self, command_handler):
        result = command_handler.handle_command({"command": "kill"})
        assert result["status"] == "error"
        assert "Missing 'pid' field" in result["message"]

    def test_kill_command_invalid_pid_string(self, command_handler):
        result = command_handler.handle_command({"command": "kill", "pid": "not-a-number"})
        assert result["status"] == "error"
        assert "Invalid pid" in result["message"]

    def test_kill_command_invalid_pid_negative(self, command_handler):
        result = command_handler.handle_command({"command": "kill", "pid": -1})
        assert result["status"] == "error"
        assert "Invalid pid" in result["message"]

    def test_kill_command_invalid_pid_zero(self, command_handler):
        result = command_handler.handle_command({"command": "kill", "pid": 0})
        assert result["status"] == "error"
        assert "Invalid pid" in result["message"]

    def test_kill_command_different_uid_permission_denied(self, command_handler, monkeypatch):
        test_pid = 12345
        different_uid = os.getuid() + 1
        mock_stat_result = Mock()
        mock_stat_result.st_uid = different_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        result = command_handler.handle_command({"command": "kill", "pid": test_pid})

        assert result["status"] == "error"
        assert "Permission denied" in result["message"]

    def test_kill_command_process_not_found(self, command_handler, monkeypatch):
        test_pid = 99999
        monkeypatch.setattr(os, "stat", Mock(side_effect=FileNotFoundError))

        with patch.object(CommandHandler, "_kill_process", return_value={"status": "ok", "message": f"Process {test_pid} not found (already gone)"}):
            result = command_handler.handle_command({"command": "kill", "pid": test_pid})

        assert result["status"] == "ok"

    def test_kill_command_rate_limit_exceeded(self, command_handler, monkeypatch):
        test_pid = 12345
        test_uid = os.getuid()
        mock_stat_result = Mock()
        mock_stat_result.st_uid = test_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        with patch.object(CommandHandler, "_kill_process", return_value={"status": "ok", "message": "Process killed"}):
            for _ in range(5):
                result = command_handler.handle_command({"command": "kill", "pid": test_pid})
                assert result["status"] == "ok"

            result = command_handler.handle_command({"command": "kill", "pid": test_pid})
            assert result["status"] == "error"
            assert "Rate limit exceeded" in result["message"]

    def test_kill_command_rate_limit_resets_after_60s(self, command_handler, monkeypatch):
        test_pid = 12345
        test_uid = os.getuid()
        mock_stat_result = Mock()
        mock_stat_result.st_uid = test_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        with patch.object(CommandHandler, "_kill_process", return_value={"status": "ok", "message": "Process killed"}):
            with patch("time.time", return_value=0.0):
                for _ in range(5):
                    result = command_handler.handle_command({"command": "kill", "pid": test_pid})
                    assert result["status"] == "ok"

            with patch("time.time", return_value=61.0):
                result = command_handler.handle_command({"command": "kill", "pid": test_pid})
                assert result["status"] == "ok"

    def test_unknown_command(self, command_handler):
        result = command_handler.handle_command({"command": "unknown"})
        assert result["status"] == "error"
        assert "Unknown command" in result["message"]

    def test_command_without_command_field(self, command_handler):
        result = command_handler.handle_command({"action": "something"})
        assert result["status"] == "error"
        assert "Unknown command" in result["message"]

    def test_kill_command_adds_timestamp(self, command_handler, monkeypatch):
        test_pid = 12345
        test_uid = os.getuid()
        initial_len = len(command_handler._kill_timestamps)
        mock_stat_result = Mock()
        mock_stat_result.st_uid = test_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        with patch.object(CommandHandler, "_kill_process", return_value={"status": "ok", "message": "Process killed"}):
            command_handler.handle_command({"command": "kill", "pid": test_pid})

        assert len(command_handler._kill_timestamps) == initial_len + 1

    def test_kill_command_old_timestamps_purged(self, command_handler, monkeypatch):
        test_pid = 12345
        test_uid = os.getuid()
        command_handler._kill_timestamps.clear()
        mock_stat_result = Mock()
        mock_stat_result.st_uid = test_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        command_handler._kill_timestamps.extend([0.0, 0.5, 1.0])

        with patch.object(CommandHandler, "_kill_process", return_value={"status": "ok", "message": "Process killed"}):
            with patch("time.time", return_value=61.0):
                result = command_handler.handle_command({"command": "kill", "pid": test_pid})

        assert result["status"] == "ok"
        assert len(command_handler._kill_timestamps) == 1
        assert command_handler._kill_timestamps[0] == 61.0


class TestKillProcess:
    def test_kill_process_sigterm_success(self, monkeypatch):
        test_pid = 12345
        kill_calls = []

        def mock_kill(pid, sig):
            kill_calls.append((pid, sig))
            if sig == signal.SIGTERM:
                return None
            raise ProcessLookupError()

        monkeypatch.setattr(os, "kill", mock_kill)
        result = CommandHandler._kill_process(test_pid)

        assert result["status"] == "ok"
        assert "SIGTERM" in result["message"]
        assert (test_pid, signal.SIGTERM) in kill_calls

    def test_kill_process_already_gone(self, monkeypatch):
        test_pid = 12345
        monkeypatch.setattr(os, "kill", Mock(side_effect=ProcessLookupError()))
        result = CommandHandler._kill_process(test_pid)
        assert result["status"] == "ok"
        assert "not found" in result["message"].lower()
        assert "already gone" in result["message"].lower()

    def test_kill_process_permission_denied(self, monkeypatch):
        test_pid = 12345
        monkeypatch.setattr(os, "kill", Mock(side_effect=PermissionError("Operation not permitted")))
        result = CommandHandler._kill_process(test_pid)
        assert result["status"] == "error"
        assert "Permission denied" in result["message"]

    def test_kill_process_os_error(self, monkeypatch):
        test_pid = 12345
        monkeypatch.setattr(os, "kill", Mock(side_effect=OSError("Some error")))
        result = CommandHandler._kill_process(test_pid)
        assert result["status"] == "error"
        assert "Error sending SIGTERM" in result["message"]

    def test_kill_process_sigkill_fallback(self, monkeypatch):
        test_pid = 12345
        kill_sequence = []

        def mock_kill(pid, sig):
            kill_sequence.append((pid, sig))
            if sig == signal.SIGTERM:
                return None
            elif sig == signal.SIGKILL:
                return None
            elif sig == 0:
                return None
            raise ProcessLookupError()

        monkeypatch.setattr(os, "kill", mock_kill)

        with patch("time.time") as mock_time:
            mock_time.side_effect = [0.0, 0.1, 0.2, 0.3, 3.0]
            result = CommandHandler._kill_process(test_pid)

        assert result["status"] == "ok"
        assert "SIGKILL" in result["message"]
        assert (test_pid, signal.SIGTERM) in kill_sequence
        assert (test_pid, signal.SIGKILL) in kill_sequence

    def test_kill_process_sigkill_permission_denied(self, monkeypatch):
        test_pid = 12345
        kill_calls = []

        def mock_kill(pid, sig):
            kill_calls.append((pid, sig))
            if sig == signal.SIGTERM:
                return None
            elif sig == 0:
                return None
            elif sig == signal.SIGKILL:
                raise PermissionError("Operation not permitted")
            raise ProcessLookupError()

        monkeypatch.setattr(os, "kill", mock_kill)

        with patch("time.time") as mock_time:
            mock_time.side_effect = [0.0, 0.1, 0.2, 0.3, 3.0]
            result = CommandHandler._kill_process(test_pid)

        assert result["status"] == "error"
        assert "Permission denied sending SIGKILL" in result["message"]

    def test_kill_process_protected_pid_zero(self):
        result = CommandHandler._kill_process(0)
        assert result["status"] == "error"
        assert "protected" in result["message"].lower()

    def test_kill_process_protected_pid_one(self):
        result = CommandHandler._kill_process(1)
        assert result["status"] == "error"
        assert "protected" in result["message"].lower()

    def test_kill_process_protected_pid_two(self):
        result = CommandHandler._kill_process(2)
        assert result["status"] == "error"
        assert "protected" in result["message"].lower()

    def test_kill_process_negative_pid(self):
        result = CommandHandler._kill_process(-100)
        assert result["status"] == "error"
        assert "protected" in result["message"].lower()

    def test_kill_process_terminates_between_checks(self, monkeypatch):
        test_pid = 12345
        kill_calls = []

        def mock_kill(pid, sig):
            kill_calls.append((pid, sig))
            if sig == signal.SIGTERM:
                return None
            elif sig == 0:
                raise ProcessLookupError()
            raise ProcessLookupError()

        monkeypatch.setattr(os, "kill", mock_kill)
        result = CommandHandler._kill_process(test_pid)
        assert result["status"] == "ok"
        assert "SIGTERM" in result["message"]


# ══════════════════════════════════════════════════════════════════
#  NotificationManager Tests
# ══════════════════════════════════════════════════════════════════


class TestNotificationManager:
    @pytest.fixture
    def nm(self, mock_config):
        return NotificationManager(mock_config)

    def test_no_alerts_does_nothing(self, nm):
        nm.handle([])

    def test_notification_disabled(self, mock_config, sample_alert):
        mock_config.notifications_enabled = False
        nm = NotificationManager(mock_config)
        with patch("subprocess.Popen") as mock_popen:
            nm.handle([sample_alert])
        mock_popen.assert_not_called()

    def test_info_alert_no_notification(self, nm):
        info_alert = Alert(
            level=AlertLevel.INFO, port=9000, proto="tcp", process_name="app",
            pid=1000, message="New listening port 9000",
        )
        with patch("subprocess.Popen") as mock_popen:
            nm.handle([info_alert])
        mock_popen.assert_not_called()

    def test_warning_alert_sends_notification(self, nm, sample_alert):
        with patch("subprocess.Popen") as mock_popen:
            nm.handle([sample_alert])
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        assert "notify-send" in call_args[0][0]
        assert "KPortWatch" in call_args[0][0]

    def test_critical_alert_sends_notification(self, nm, critical_alert):
        with patch("subprocess.Popen") as mock_popen:
            nm.handle([critical_alert])
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        assert "notify-send" in call_args[0][0]
        assert "-u" in call_args[0][0]
        assert "critical" in call_args[0][0]

    def test_notification_alert_ttl_dedup(self, nm, sample_alert):
        alert_hash = f"{sample_alert.level}:{sample_alert.message}"
        nm._notified_alerts[alert_hash] = time.time() - 100

        with patch("subprocess.Popen") as mock_popen:
            nm.handle([sample_alert])
        mock_popen.assert_not_called()

    def test_notification_after_ttl_expires(self, mock_config, sample_alert):
        mock_config.alert_ttl = 100.0
        nm = NotificationManager(mock_config)
        alert_hash = f"{sample_alert.level}:{sample_alert.message}"
        nm._notified_alerts[alert_hash] = time.time() - 200

        with patch("subprocess.Popen") as mock_popen:
            nm.handle([sample_alert])
        mock_popen.assert_called_once()

    def test_notification_rate_limiting(self, mock_config, sample_alert):
        mock_config.notification_rate_limit = 2
        mock_config.notification_rate_window = 60.0
        nm = NotificationManager(mock_config)
        nm._notification_timestamps = [time.time() - 10, time.time() - 5]

        with patch("subprocess.Popen") as mock_popen:
            nm.handle([sample_alert])
        mock_popen.assert_not_called()

    def test_notification_rate_limit_window_expires(self, mock_config, sample_alert):
        mock_config.notification_rate_limit = 2
        mock_config.notification_rate_window = 60.0
        nm = NotificationManager(mock_config)
        nm._notification_timestamps = [time.time() - 70, time.time() - 65]

        with patch("subprocess.Popen") as mock_popen:
            nm.handle([sample_alert])
        mock_popen.assert_called_once()

    def test_multiple_alerts(self, nm, sample_alert, critical_alert):
        with patch("subprocess.Popen") as mock_popen:
            nm.handle([sample_alert, critical_alert])
        assert mock_popen.call_count == 2

    def test_notification_truncates_message(self, nm):
        long_alert = Alert(
            level=AlertLevel.WARNING, port=8080, proto="tcp", process_name="test",
            pid=1000, message="A" * 300,
        )
        with patch("subprocess.Popen") as mock_popen:
            nm.handle([long_alert])
        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        message_arg = [arg for arg in call_args[0][0] if isinstance(arg, str) and "A" * 100 in arg]
        assert len(message_arg) > 0
        assert len(message_arg[0]) < 300

    def test_notification_sanitizes_message(self, nm):
        dirty_alert = Alert(
            level=AlertLevel.WARNING, port=8080, proto="tcp", process_name="test",
            pid=1000, message="Test\x00\x01\x02message with control chars",
        )
        with patch("subprocess.Popen") as mock_popen:
            nm.handle([dirty_alert])
        mock_popen.assert_called_once()
        args_list = mock_popen.call_args[0][0]
        sanitized_msg = args_list[-1]
        assert "\x00" not in sanitized_msg
        assert "\x01" not in sanitized_msg
        assert "\x02" not in sanitized_msg

    def test_notify_send_not_found(self, nm, sample_alert):
        with patch("subprocess.Popen", side_effect=FileNotFoundError):
            nm.handle([sample_alert])

    def test_notify_send_os_error(self, nm, sample_alert):
        with patch("subprocess.Popen", side_effect=OSError("Failed")):
            nm.handle([sample_alert])

    def test_notified_alerts_timestamp_updated(self, nm, sample_alert):
        alert_hash = f"{sample_alert.level}:{sample_alert.message}"
        with patch("subprocess.Popen"), patch("time.time", return_value=12345.0):
            nm.handle([sample_alert])
        assert alert_hash in nm._notified_alerts
        assert nm._notified_alerts[alert_hash] == 12345.0

    def test_notification_timestamp_added(self, nm, sample_alert):
        initial_len = len(nm._notification_timestamps)
        with patch("subprocess.Popen"), patch("time.time", return_value=12345.0):
            nm.handle([sample_alert])
        assert len(nm._notification_timestamps) == initial_len + 1
        assert 12345.0 in nm._notification_timestamps

    def test_evicts_expired_alert_hashes(self, mock_config, sample_alert):
        nm = NotificationManager(mock_config)
        now = time.time()
        for i in range(600):
            nm._notified_alerts[f"WARNING:Alert {i}"] = now - 4000

        with patch("subprocess.Popen"), patch("time.time", return_value=now):
            nm.handle([sample_alert])
        assert len(nm._notified_alerts) < 600

    def test_empty_alert_list_does_not_clear_rate_limit_timestamps(self, nm):
        nm._notification_timestamps = [time.time() - 70, time.time() - 65]
        initial_len = len(nm._notification_timestamps)
        nm.handle([])
        assert len(nm._notification_timestamps) == initial_len


# ══════════════════════════════════════════════════════════════════
#  DataCollector Tests
# ══════════════════════════════════════════════════════════════════


class TestDataCollector:
    @pytest.fixture
    def collector(self, mock_config):
        return DataCollector(mock_config)

    @patch("backend.daemon.collector._HAS_PSUTIL", False)
    def test_collect_entries_without_psutil(self, collector, monkeypatch):
        sample_entries = [
            SocketEntry(
                proto="tcp", local_ip="0.0.0.0", local_port=22, remote_ip="0.0.0.0",
                remote_port=0, state="LISTEN", state_code="0A", uid=0, inode=12345,
                pid=None, process_name=None,
            )
        ]

        with patch("backend.daemon.collector.parse_all_proc", return_value=sample_entries):
            with patch("backend.daemon.collector.build_inode_to_pid_map", return_value={
                12345: (1, "sshd", "/usr/sbin/sshd -D")
            }):
                with patch("backend.daemon.collector.build_uid_process_map", return_value={}):
                    entries, _inode_map = collector._collect_entries()

        assert len(entries) == 1
        assert entries[0].pid == 1
        assert entries[0].process_name == "sshd"

    @patch("backend.daemon.collector._HAS_PSUTIL", True)
    def test_collect_entries_with_psutil(self, collector):
        sample_entries = [
            SocketEntry(
                proto="tcp", local_ip="0.0.0.0", local_port=80, remote_ip="0.0.0.0",
                remote_port=0, state="LISTEN", state_code="0A", uid=0, inode=67890,
                pid=2, process_name="nginx", cmdline="/usr/sbin/nginx",
            )
        ]

        with patch("backend.daemon.collector._psutil_connections", return_value=sample_entries):
            entries, _inode_map = collector._collect_entries()

        assert len(entries) == 1
        assert entries[0].pid == 2
        assert _inode_map is None

    @patch("backend.daemon.collector._HAS_PSUTIL", True)
    def test_collect_entries_psutil_missing_pid(self, collector):
        sample_entries = [
            SocketEntry(
                proto="tcp", local_ip="0.0.0.0", local_port=443, remote_ip="0.0.0.0",
                remote_port=0, state="LISTEN", state_code="0A", uid=0, inode=11111,
                pid=None, process_name=None,
            )
        ]

        with patch("backend.daemon.collector._psutil_connections", return_value=sample_entries):
            with patch("backend.daemon.collector.build_inode_to_pid_map", return_value={
                11111: (3, "apache", "/usr/sbin/apache2")
            }):
                with patch("backend.daemon.collector.build_uid_process_map", return_value={}):
                    entries, _inode_map = collector._collect_entries()

        assert entries[0].pid == 3
        assert entries[0].process_name == "apache"

    @patch("backend.daemon.collector._HAS_PSUTIL", False)
    def test_collect_entries_resolves_via_uid(self, collector):
        sample_entries = [
            SocketEntry(
                proto="tcp", local_ip="0.0.0.0", local_port=53, remote_ip="0.0.0.0",
                remote_port=0, state="LISTEN", state_code="0A", uid=1000, inode=99999,
                pid=None, process_name=None,
            )
        ]

        with patch("backend.daemon.collector.parse_all_proc", return_value=sample_entries):
            with patch("backend.daemon.collector.build_inode_to_pid_map", return_value={}):
                with patch("backend.daemon.collector.build_uid_process_map", return_value={
                    1000: ("user", "dnsmasq", "/usr/sbin/dnsmasq")
                }):
                    entries, _inode_map = collector._collect_entries()

        assert entries[0].process_name == "dnsmasq (user)"

    @patch("backend.daemon.collector._HAS_PSUTIL", False)
    def test_collect_entries_empty(self, collector):
        with patch("backend.daemon.collector.parse_all_proc", return_value=[]):
            with patch("backend.daemon.collector.build_inode_to_pid_map", return_value={}):
                with patch("backend.daemon.collector.build_uid_process_map", return_value={}):
                    entries, _inode_map = collector._collect_entries()

        assert entries == []
        assert _inode_map is not None

    @patch("backend.daemon.collector._HAS_PSUTIL", True)
    def test_collect_entries_multiple(self, collector):
        sample_entries = [
            SocketEntry(
                proto="tcp", local_ip="0.0.0.0", local_port=22, remote_ip="0.0.0.0",
                remote_port=0, state="LISTEN", state_code="0A", uid=0, inode=100, pid=1,
                process_name="sshd", cmdline="/usr/sbin/sshd"
            ),
            SocketEntry(
                proto="tcp", local_ip="0.0.0.0", local_port=80, remote_ip="0.0.0.0",
                remote_port=0, state="LISTEN", state_code="0A", uid=0, inode=101, pid=2,
                process_name="nginx", cmdline="/usr/sbin/nginx"
            ),
        ]

        with patch("backend.daemon.collector._psutil_connections", return_value=sample_entries):
            entries, _inode_map = collector._collect_entries()

        assert len(entries) == 2
        assert _inode_map is None


# ══════════════════════════════════════════════════════════════════
#  SnapshotBuilder Tests
# ══════════════════════════════════════════════════════════════════


class TestSnapshotBuilder:
    @pytest.fixture
    def sb(self, mock_config):
        alert_engine = Mock()
        alert_engine.malicious_ports = set()
        alert_engine.known_safe = {}
        alert_engine.port_blacklist = set()
        alert_engine.is_baseline_complete.return_value = False
        history = Mock()
        socket_server = Mock()
        return SnapshotBuilder(
            alert_engine=alert_engine,
            history=history,
            socket_server=socket_server,
            cfg=mock_config,
        )

    def test_build_snapshot_basic(self, sb, sample_listening_entries):
        from backend.models import ProcessInfo
        sample_alerts = [
            Alert(level=AlertLevel.WARNING, port=8080, proto="tcp", process_name="unknown",
                  pid=None, message="Test alert", timestamp=time.time())
        ]
        sample_traffic = {
            "eth0": InterfaceStats(
                interface="eth0", rx_bytes=1000, tx_bytes=500, rx_packets=10, tx_packets=5,
                rx_errors=0, tx_errors=0, rx_drops=0, tx_drops=0, rx_rate=100.0, tx_rate=50.0,
            )
        }
        sample_process_tree = {
            1: ProcessInfo(pid=1, ppid=0, name="init", cmdline="/sbin/init", state="S", uid=0, children=[2])
        }
        sample_risk_scores = {22: 0.1, 80: 0.2}

        snapshot = sb._build_snapshot(
            listening=sample_listening_entries,
            established=[],
            alerts=sample_alerts,
            traffic=sample_traffic,
            process_tree=sample_process_tree,
            risk_scores=sample_risk_scores,
            interval_ms=2000,
        )

        assert snapshot.timestamp > 0
        assert snapshot.listening == sample_listening_entries
        assert snapshot.established == []
        assert snapshot.alerts == sample_alerts
        assert snapshot.traffic == sample_traffic
        assert "1" in snapshot.processes
        assert snapshot.summary["total_listening"] == 2
        assert snapshot.summary["alert_count"] == 1

    def test_build_snapshot_with_geo_stats(self, sb, sample_listening_entries):
        sample_established = [
            SocketEntry(
                proto="tcp", local_ip="192.168.1.10", local_port=44532, remote_ip="8.8.8.8",
                remote_port=443, state="ESTABLISHED", state_code="01", uid=1000, inode=67890,
                pid=1234, process_name="firefox", cmdline="/usr/lib/firefox/firefox",
                remote_country_code="US",
            ),
            SocketEntry(
                proto="tcp", local_ip="192.168.1.10", local_port=44533, remote_ip="1.1.1.1",
                remote_port=443, state="ESTABLISHED", state_code="01", uid=1000, inode=67891,
                pid=1234, process_name="firefox", cmdline="/usr/lib/firefox/firefox",
                remote_country_code="US",
            ),
        ]

        snapshot = sb._build_snapshot(
            listening=sample_listening_entries,
            established=sample_established,
            alerts=[],
            traffic={},
            process_tree={},
            risk_scores={},
            interval_ms=2000,
        )

        assert snapshot.geo_stats["countries_count"] == 1
        assert "US" in snapshot.geo_stats["unique_ips_per_country"]
        assert snapshot.geo_stats["unique_ips_per_country"]["US"] == 2

    def test_build_snapshot_empty_lists(self, sb):
        snapshot = sb._build_snapshot(
            listening=[], established=[], alerts=[], traffic={},
            process_tree={}, risk_scores={}, interval_ms=2000,
        )
        assert snapshot.listening == []
        assert snapshot.summary["total_listening"] == 0
        assert snapshot.geo_stats["countries_count"] == 0

    def test_build_snapshot_poll_interval_ms(self, sb, sample_listening_entries):
        snapshot = sb._build_snapshot(
            listening=sample_listening_entries, established=[], alerts=[],
            traffic={}, process_tree={}, risk_scores={}, interval_ms=2500,
        )
        assert snapshot.poll_interval_ms == 2500

    def test_build_snapshot_risk_scores_in_summary(self, sb, sample_listening_entries):
        sample_risk_scores = {22: 0.1, 80: 0.8, 443: 0.05}
        snapshot = sb._build_snapshot(
            listening=sample_listening_entries, established=[], alerts=[],
            traffic={}, process_tree={}, risk_scores=sample_risk_scores,
            interval_ms=2000,
        )
        assert snapshot.summary["risk_scores"] == {"22": 0.1, "80": 0.8, "443": 0.05}

    def test_build_snapshot_geo_without_country_code(self, sb, sample_listening_entries):
        sample_established = [
            SocketEntry(
                proto="tcp", local_ip="192.168.1.10", local_port=44532, remote_ip="192.168.1.1",
                remote_port=443, state="ESTABLISHED", state_code="01", uid=1000, inode=67890,
                pid=1234, process_name="app", cmdline="/app", remote_country_code=None,
            )
        ]
        snapshot = sb._build_snapshot(
            listening=sample_listening_entries, established=sample_established,
            alerts=[], traffic={}, process_tree={}, risk_scores={}, interval_ms=2000,
        )
        assert snapshot.geo_stats["countries_count"] == 0

    def test_build_snapshot_multiple_countries(self, sb, sample_listening_entries):
        sample_established = [
            SocketEntry(proto="tcp", local_ip="0.0.0.0", local_port=1, remote_ip="1.1.1.1",
                remote_port=443, state="ESTABLISHED", state_code="01", uid=0, inode=1, pid=1,
                process_name="test", cmdline="test", remote_country_code="US"),
            SocketEntry(proto="tcp", local_ip="0.0.0.0", local_port=2, remote_ip="2.2.2.2",
                remote_port=443, state="ESTABLISHED", state_code="01", uid=0, inode=2, pid=1,
                process_name="test", cmdline="test", remote_country_code="US"),
            SocketEntry(proto="tcp", local_ip="0.0.0.0", local_port=3, remote_ip="3.3.3.3",
                remote_port=443, state="ESTABLISHED", state_code="01", uid=0, inode=3, pid=1,
                process_name="test", cmdline="test", remote_country_code="DE"),
        ]
        snapshot = sb._build_snapshot(
            listening=sample_listening_entries, established=sample_established,
            alerts=[], traffic={}, process_tree={}, risk_scores={}, interval_ms=2000,
        )
        assert snapshot.geo_stats["countries_count"] == 2
        assert snapshot.geo_stats["unique_ips_per_country"]["US"] == 2
        assert snapshot.geo_stats["unique_ips_per_country"]["DE"] == 1

    def test_build_snapshot_top_countries_sorted(self, sb, sample_listening_entries):
        sample_established = [
            SocketEntry(proto="tcp", local_ip="0.0.0.0", local_port=i, remote_ip=f"{i}.{i}.{i}.{i}",
                remote_port=443, state="ESTABLISHED", state_code="01", uid=0, inode=i, pid=1,
                process_name="test", cmdline="test", remote_country_code="US")
            for i in range(1, 4)
        ] + [
            SocketEntry(proto="tcp", local_ip="0.0.0.0", local_port=i+10, remote_ip=f"{i+10}.{i+10}.{i+10}.{i+10}",
                remote_port=443, state="ESTABLISHED", state_code="01", uid=0, inode=i+10, pid=1,
                process_name="test", cmdline="test", remote_country_code="DE")
            for i in range(1, 3)
        ]
        snapshot = sb._build_snapshot(
            listening=sample_listening_entries, established=sample_established,
            alerts=[], traffic={}, process_tree={}, risk_scores={}, interval_ms=2000,
        )
        top = snapshot.geo_stats["top_countries"]
        assert top[0] == ("US", 3)
        assert top[1] == ("DE", 2)

    def test_build_snapshot_top_countries_limited(self, sb, sample_listening_entries):
        sample_established = [
            SocketEntry(proto="tcp", local_ip="0.0.0.0", local_port=i, remote_ip=f"{i}.{i}.{i}.{i}",
                remote_port=443, state="ESTABLISHED", state_code="01", uid=0, inode=i, pid=1,
                process_name="test", cmdline="test", remote_country_code=f"C{i:02d}")
            for i in range(12)
        ]
        snapshot = sb._build_snapshot(
            listening=sample_listening_entries, established=sample_established,
            alerts=[], traffic={}, process_tree={}, risk_scores={}, interval_ms=2000,
        )
        assert len(snapshot.geo_stats["top_countries"]) == 10
        assert snapshot.geo_stats["countries_count"] == 12


class TestPublish:
    @pytest.fixture
    def sb(self, mock_config):
        alert_engine = Mock()
        alert_engine.malicious_ports = set()
        alert_engine.known_safe = {}
        alert_engine.port_blacklist = set()
        alert_engine.is_baseline_complete.return_value = False
        history = Mock()
        socket_server = Mock()
        return SnapshotBuilder(
            alert_engine=alert_engine,
            history=history,
            socket_server=socket_server,
            cfg=mock_config,
        )

    def _make_snapshot(self, sb, listening, alerts=None, traffic=None, process_tree=None, risk_scores=None):
        """Helper to build a snapshot for publish tests."""
        return sb._build_snapshot(
            listening=listening,
            established=[],
            alerts=alerts or [],
            traffic=traffic or {},
            process_tree=process_tree or {},
            risk_scores=risk_scores or {},
            interval_ms=2000,
        )

    @patch("backend.daemon.snapshot.write_snapshot")
    @patch("backend.daemon.snapshot.write_widget_snapshot")
    @patch("backend.daemon.snapshot._write_heartbeat")
    def test_publish_writes_snapshot(self, mock_hb, mock_widget, mock_write, sb, sample_listening_entries):
        snapshot = self._make_snapshot(sb, sample_listening_entries)
        sb._publish(snapshot, [])
        mock_write.assert_called_once()
        mock_widget.assert_called_once_with(snapshot)
        mock_hb.assert_called_once()

    @patch("backend.daemon.snapshot.write_snapshot")
    @patch("backend.daemon.snapshot.write_widget_snapshot")
    @patch("backend.daemon.snapshot._write_heartbeat")
    def test_publish_broadcasts_to_socket(self, mock_hb, mock_widget, mock_write, sb, sample_listening_entries):
        snapshot = self._make_snapshot(sb, sample_listening_entries)
        sb._publish(snapshot, [])
        sb._socket_server.broadcast.assert_called_once()
        call_arg = sb._socket_server.broadcast.call_args[0][0]
        assert isinstance(call_arg, str)

    @patch("backend.daemon.snapshot.write_snapshot")
    @patch("backend.daemon.snapshot.write_widget_snapshot")
    @patch("backend.daemon.snapshot._write_heartbeat")
    def test_publish_without_socket_server(self, mock_hb, mock_widget, mock_write, mock_config, sample_listening_entries):
        alert_engine = Mock()
        alert_engine.malicious_ports = set()
        alert_engine.known_safe = {}
        alert_engine.port_blacklist = set()
        alert_engine.is_baseline_complete.return_value = False
        sb_no_sock = SnapshotBuilder(
            alert_engine=alert_engine, history=Mock(),
            socket_server=None, cfg=mock_config,
        )
        snapshot = self._make_snapshot(sb_no_sock, sample_listening_entries)
        sb_no_sock._publish(snapshot, [])
        mock_write.assert_called_once()

    @patch("backend.daemon.snapshot.write_snapshot")
    @patch("backend.daemon.snapshot.write_widget_snapshot")
    @patch("backend.daemon.snapshot._write_heartbeat")
    def test_publish_records_history(self, mock_hb, mock_widget, mock_write, sb, sample_listening_entries):
        sample_alerts = [
            Alert(level=AlertLevel.WARNING, port=8080, proto="tcp", process_name="test",
                  pid=1000, message="Test alert", timestamp=time.time())
        ]
        snapshot = self._make_snapshot(sb, sample_listening_entries, alerts=sample_alerts)
        sb._publish(snapshot, sample_alerts)
        sb._history.record_summary.assert_called_once_with(snapshot)
        sb._history.record_alert.assert_called_once_with(sample_alerts[0])

    @patch("backend.daemon.snapshot.write_snapshot")
    @patch("backend.daemon.snapshot.write_widget_snapshot")
    @patch("backend.daemon.snapshot._write_heartbeat")
    def test_publish_with_no_history(self, mock_hb, mock_widget, mock_write, mock_config, sample_listening_entries):
        alert_engine = Mock()
        alert_engine.malicious_ports = set()
        alert_engine.known_safe = {}
        alert_engine.port_blacklist = set()
        alert_engine.is_baseline_complete.return_value = False
        sb_no_hist = SnapshotBuilder(
            alert_engine=alert_engine, history=None,
            socket_server=Mock(), cfg=mock_config,
        )
        snapshot = self._make_snapshot(sb_no_hist, sample_listening_entries)
        try:
            sb_no_hist._publish(snapshot, [])
        except AttributeError as e:
            assert "'NoneType' object has no attribute 'record_summary'" in str(e)
            mock_write.assert_called_once()

    @patch("backend.daemon.snapshot.write_snapshot")
    @patch("backend.daemon.snapshot.write_widget_snapshot")
    @patch("backend.daemon.snapshot._write_heartbeat")
    def test_publish_heartbeat_uses_effective_path(self, mock_hb, mock_widget, mock_write, sb, sample_listening_entries):
        snapshot = self._make_snapshot(sb, sample_listening_entries)
        sb._publish(snapshot, [])
        mock_hb.assert_called_once()
        call_arg = mock_hb.call_args[0][0]
        assert "/tmp/test" in call_arg or "heartbeat" in call_arg

    @patch("backend.daemon.snapshot.write_snapshot")
    @patch("backend.daemon.snapshot.write_widget_snapshot")
    @patch("backend.daemon.snapshot._write_heartbeat")
    def test_publish_with_multiple_alerts(self, mock_hb, mock_widget, mock_write, sb, sample_listening_entries):
        sample_alerts = [
            Alert(level=AlertLevel.WARNING, port=8080, proto="tcp", process_name="app1",
                  pid=1000, message="Alert 1", timestamp=time.time()),
            Alert(level=AlertLevel.CRITICAL, port=4444, proto="tcp", process_name="app2",
                  pid=2000, message="Alert 2", timestamp=time.time()),
        ]
        snapshot = self._make_snapshot(sb, sample_listening_entries, alerts=sample_alerts)
        sb._publish(snapshot, sample_alerts)
        assert sb._history.record_alert.call_count == 2

    @patch("backend.daemon.snapshot.write_snapshot")
    @patch("backend.daemon.snapshot.write_widget_snapshot")
    @patch("backend.daemon.snapshot._write_heartbeat")
    def test_publish_passes_snapshot_json_to_broadcast(self, mock_hb, mock_widget, mock_write, sb, sample_listening_entries):
        snapshot = self._make_snapshot(sb, sample_listening_entries)
        sb._publish(snapshot, [])
        broadcast_arg = sb._socket_server.broadcast.call_args[0][0]
        assert "KPortWatch" in broadcast_arg or "listening" in broadcast_arg or "summary" in broadcast_arg

    @patch("backend.daemon.snapshot.write_snapshot")
    @patch("backend.daemon.snapshot.write_widget_snapshot")
    @patch("backend.daemon.snapshot._write_heartbeat")
    def test_publish_records_summary_once(self, mock_hb, mock_widget, mock_write, sb, sample_listening_entries):
        snapshot = self._make_snapshot(sb, sample_listening_entries)
        sb._publish(snapshot, [])
        sb._history.record_summary.assert_called_once()
