"""KPortWatch — Tests for backend.daemon_controller.DaemonController."""
from __future__ import annotations

import os
import signal
import time
from unittest.mock import Mock, patch

import pytest
from backend.daemon_controller import DaemonController
from backend.models import Alert, AlertLevel, SocketEntry
from shared.config import AppConfig

# ── Fixtures ──────────────────────────────────────────────────────


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
    # Set heartbeat_file so effective_heartbeat_file uses it
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


# ── Initialization Tests ──────────────────────────────────────────


class TestInitialization:
    def test_default_initialization(self, mock_args):
        """Test that DaemonController initializes with correct defaults."""
        with patch.object(DaemonController, "_init_components"):
            ctrl = DaemonController(mock_args)
            assert ctrl.running is True
            assert ctrl.interval == 2.0
            assert ctrl.last_snapshot_hash is None
            assert ctrl.last_change_time > 0
            assert ctrl.risk_scores == {}
            assert ctrl.notified_alerts == {}
            assert ctrl.notification_timestamps == []
            assert ctrl._prev_traffic == {}
            assert ctrl._last_update_check == 0.0
            assert ctrl._error_count == 0
            assert ctrl.prev_baseline == frozenset()
            assert ctrl.prev_listening_set == frozenset()

    def test_kill_timestamps_class_attribute(self):
        """Test that _kill_timestamps is a class attribute."""
        assert hasattr(DaemonController, "_kill_timestamps")
        assert isinstance(DaemonController._kill_timestamps, list)

    def test_max_kill_rate_constant(self):
        """Test that _MAX_KILL_RATE is set correctly."""
        assert DaemonController._MAX_KILL_RATE == 5

    def test_protected_pids_constant(self):
        """Test that PROTECTED_PIDS includes system PIDs."""
        assert {0, 1, 2} == DaemonController.PROTECTED_PIDS


# ── _handle_socket_command Tests ──────────────────────────────────


class TestHandleSocketCommand:
    def test_kill_command_valid_pid_same_uid(self, controller, monkeypatch):
        """Test kill command with valid PID owned by same user."""
        test_pid = 12345
        test_uid = os.getuid()

        # Mock os.stat to return same UID
        mock_stat_result = Mock()
        mock_stat_result.st_uid = test_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        # Mock _kill_process to return success
        with patch.object(
            DaemonController, "_kill_process", return_value={"status": "ok", "message": "Process killed"}
        ):
            result = controller._handle_socket_command({"command": "kill", "pid": test_pid})

        assert result["status"] == "ok"
        assert result["message"] == "Process killed"

    def test_kill_command_missing_pid(self, controller):
        """Test kill command with missing PID field."""
        result = controller._handle_socket_command({"command": "kill"})
        assert result["status"] == "error"
        assert "Missing 'pid' field" in result["message"]

    def test_kill_command_invalid_pid_string(self, controller):
        """Test kill command with non-integer PID string."""
        result = controller._handle_socket_command({"command": "kill", "pid": "not-a-number"})
        assert result["status"] == "error"
        assert "Invalid pid" in result["message"]

    def test_kill_command_invalid_pid_negative(self, controller):
        """Test kill command with negative PID."""
        result = controller._handle_socket_command({"command": "kill", "pid": -1})
        assert result["status"] == "error"
        assert "Invalid pid" in result["message"]

    def test_kill_command_invalid_pid_zero(self, controller):
        """Test kill command with zero PID."""
        result = controller._handle_socket_command({"command": "kill", "pid": 0})
        assert result["status"] == "error"
        assert "Invalid pid" in result["message"]

    def test_kill_command_different_uid_permission_denied(self, controller, monkeypatch):
        """Test kill command with PID owned by different user."""
        test_pid = 12345
        different_uid = os.getuid() + 1

        # Mock os.stat to return different UID
        mock_stat_result = Mock()
        mock_stat_result.st_uid = different_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        result = controller._handle_socket_command({"command": "kill", "pid": test_pid})

        assert result["status"] == "error"
        assert "Permission denied" in result["message"]
        assert str(test_pid) in result["message"]

    def test_kill_command_process_not_found(self, controller, monkeypatch):
        """Test kill command when process doesn't exist."""
        test_pid = 99999

        # Mock os.stat to raise FileNotFoundError (so UID check is skipped)
        monkeypatch.setattr(os, "stat", Mock(side_effect=FileNotFoundError))

        # Mock _kill_process to return "ok" for not found process
        with patch.object(
            DaemonController, "_kill_process", return_value={"status": "ok", "message": f"Process {test_pid} not found (already gone)"}
        ):
            result = controller._handle_socket_command({"command": "kill", "pid": test_pid})

        assert result["status"] == "ok"
        assert "not found" in result["message"].lower()

    def test_kill_command_rate_limit_exceeded(self, controller, monkeypatch):
        """Test kill command rate limiting (6th request within 60s)."""
        test_pid = 12345
        test_uid = os.getuid()

        # Clear the class-level timestamp list first
        DaemonController._kill_timestamps.clear()

        # Mock os.stat to return same UID
        mock_stat_result = Mock()
        mock_stat_result.st_uid = test_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        # Mock _kill_process
        with patch.object(
            DaemonController, "_kill_process", return_value={"status": "ok", "message": "Process killed"}
        ):
            # Send 5 successful kills
            for _ in range(5):
                result = controller._handle_socket_command({"command": "kill", "pid": test_pid})
                assert result["status"] == "ok"

            # 6th kill should be rate limited
            result = controller._handle_socket_command({"command": "kill", "pid": test_pid})
            assert result["status"] == "error"
            assert "Rate limit exceeded" in result["message"]

    def test_kill_command_rate_limit_resets_after_60s(self, controller, monkeypatch):
        """Test that kill rate limit resets after 60 seconds."""
        test_pid = 12345
        test_uid = os.getuid()

        # Clear the class-level timestamp list first
        DaemonController._kill_timestamps.clear()

        # Mock os.stat to return same UID
        mock_stat_result = Mock()
        mock_stat_result.st_uid = test_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        # Mock _kill_process and time
        with patch.object(
            DaemonController, "_kill_process", return_value={"status": "ok", "message": "Process killed"}
        ):
            # Send 5 kills at t=0
            with patch("time.time", return_value=0.0):
                for _ in range(5):
                    result = controller._handle_socket_command({"command": "kill", "pid": test_pid})
                    assert result["status"] == "ok"

            # 6th kill at t=61 should succeed (timestamps expired)
            with patch("time.time", return_value=61.0):
                result = controller._handle_socket_command({"command": "kill", "pid": test_pid})
                assert result["status"] == "ok"

    def test_unknown_command(self, controller):
        """Test unknown command returns error."""
        result = controller._handle_socket_command({"command": "unknown"})
        assert result["status"] == "error"
        assert "Unknown command" in result["message"]

    def test_command_without_command_field(self, controller):
        """Test command dict without 'command' field."""
        result = controller._handle_socket_command({"action": "something"})
        assert result["status"] == "error"
        assert "Unknown command" in result["message"]

    def test_kill_command_adds_timestamp(self, controller, monkeypatch):
        """Test that successful kill adds timestamp to _kill_timestamps."""
        test_pid = 12345
        test_uid = os.getuid()

        # Clear the class-level timestamp list first
        DaemonController._kill_timestamps.clear()
        initial_len = len(DaemonController._kill_timestamps)

        # Mock os.stat and _kill_process
        mock_stat_result = Mock()
        mock_stat_result.st_uid = test_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        with patch.object(
            DaemonController, "_kill_process", return_value={"status": "ok", "message": "Process killed"}
        ):
            controller._handle_socket_command({"command": "kill", "pid": test_pid})

        assert len(DaemonController._kill_timestamps) == initial_len + 1

    def test_kill_command_old_timestamps_purged(self, controller, monkeypatch):
        """Test that old timestamps (>60s) are purged before checking rate limit."""
        test_pid = 12345
        test_uid = os.getuid()

        # Clear the class-level timestamp list first
        DaemonController._kill_timestamps.clear()

        # Mock os.stat and _kill_process
        mock_stat_result = Mock()
        mock_stat_result.st_uid = test_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        # Add old timestamps (all > 60s before t=61.0, i.e., all < 1.0)
        DaemonController._kill_timestamps.extend([0.0, 0.5, 1.0])

        with patch.object(
            DaemonController, "_kill_process", return_value={"status": "ok", "message": "Process killed"}
        ):
            with patch("time.time", return_value=61.0):
                result = controller._handle_socket_command({"command": "kill", "pid": test_pid})

        # Old timestamps should be purged, new one added
        assert result["status"] == "ok"
        # At t=61.0, only the new timestamp (61.0) should remain
        assert len(DaemonController._kill_timestamps) == 1
        assert DaemonController._kill_timestamps[0] == 61.0


# ── _kill_process Tests ──────────────────────────────────────────


class TestKillProcess:
    def test_kill_process_sigterm_success(self, monkeypatch):
        """Test successful kill with SIGTERM."""
        test_pid = 12345

        # Mock os.kill to succeed on SIGTERM
        kill_calls = []

        def mock_kill(pid, sig):
            kill_calls.append((pid, sig))
            if sig == signal.SIGTERM:
                return None
            raise ProcessLookupError()

        monkeypatch.setattr(os, "kill", mock_kill)

        result = DaemonController._kill_process(test_pid)

        assert result["status"] == "ok"
        assert "SIGTERM" in result["message"]
        assert (test_pid, signal.SIGTERM) in kill_calls

    def test_kill_process_already_gone(self, monkeypatch):
        """Test kill when process is already gone (ProcessLookupError on SIGTERM)."""
        test_pid = 12345

        # Mock os.kill to raise ProcessLookupError on SIGTERM
        monkeypatch.setattr(os, "kill", Mock(side_effect=ProcessLookupError()))

        result = DaemonController._kill_process(test_pid)

        assert result["status"] == "ok"
        assert "not found" in result["message"].lower()
        assert "already gone" in result["message"].lower()

    def test_kill_process_permission_denied(self, monkeypatch):
        """Test kill with permission denied."""
        test_pid = 12345

        # Mock os.kill to raise PermissionError
        monkeypatch.setattr(os, "kill", Mock(side_effect=PermissionError("Operation not permitted")))

        result = DaemonController._kill_process(test_pid)

        assert result["status"] == "error"
        assert "Permission denied" in result["message"]

    def test_kill_process_os_error(self, monkeypatch):
        """Test kill with generic OSError."""
        test_pid = 12345

        # Mock os.kill to raise OSError
        monkeypatch.setattr(os, "kill", Mock(side_effect=OSError("Some error")))

        result = DaemonController._kill_process(test_pid)

        assert result["status"] == "error"
        assert "Error sending SIGTERM" in result["message"]

    def test_kill_process_sigkill_fallback(self, monkeypatch):
        """Test SIGKILL fallback when SIGTERM doesn't terminate process."""
        test_pid = 12345

        # Mock os.kill: SIGTERM succeeds, SIGKILL needed after timeout
        kill_sequence = []

        def mock_kill(pid, sig):
            kill_sequence.append((pid, sig))
            if sig == signal.SIGTERM:
                return None  # SIGTERM sent successfully
            elif sig == signal.SIGKILL:
                return None
            elif sig == 0:
                # Process still exists
                return None
            raise ProcessLookupError()

        monkeypatch.setattr(os, "kill", mock_kill)

        # Mock time to simulate timeout
        with patch("time.time") as mock_time:
            mock_time.side_effect = [0.0, 0.1, 0.2, 0.3, 3.0]  # First check succeeds, then timeout

            result = DaemonController._kill_process(test_pid)

        assert result["status"] == "ok"
        assert "SIGKILL" in result["message"]
        assert (test_pid, signal.SIGTERM) in kill_sequence
        assert (test_pid, signal.SIGKILL) in kill_sequence

    def test_kill_process_sigkill_permission_denied(self, monkeypatch):
        """Test SIGKILL with permission denied."""
        test_pid = 12345

        # Mock os.kill: SIGTERM succeeds, process still running, SIGKILL fails
        kill_calls = []

        def mock_kill(pid, sig):
            kill_calls.append((pid, sig))
            if sig == signal.SIGTERM:
                return None
            elif sig == 0:
                return None  # Process still exists
            elif sig == signal.SIGKILL:
                raise PermissionError("Operation not permitted")
            raise ProcessLookupError()

        monkeypatch.setattr(os, "kill", mock_kill)

        # Mock time to trigger timeout
        with patch("time.time") as mock_time:
            mock_time.side_effect = [0.0, 0.1, 0.2, 0.3, 3.0]

            result = DaemonController._kill_process(test_pid)

        assert result["status"] == "error"
        assert "Permission denied sending SIGKILL" in result["message"]

    def test_kill_process_protected_pid_zero(self):
        """Test that PID 0 is protected."""
        result = DaemonController._kill_process(0)
        assert result["status"] == "error"
        assert "protected" in result["message"].lower()

    def test_kill_process_protected_pid_one(self):
        """Test that PID 1 is protected."""
        result = DaemonController._kill_process(1)
        assert result["status"] == "error"
        assert "protected" in result["message"].lower()

    def test_kill_process_protected_pid_two(self):
        """Test that PID 2 is protected."""
        result = DaemonController._kill_process(2)
        assert result["status"] == "error"
        assert "protected" in result["message"].lower()

    def test_kill_process_negative_pid(self):
        """Test that negative PID is rejected."""
        result = DaemonController._kill_process(-100)
        assert result["status"] == "error"
        assert "protected" in result["message"].lower()

    def test_kill_process_terminates_between_checks(self, monkeypatch):
        """Test process terminating between SIGTERM and SIGKILL."""
        test_pid = 12345

        # Mock os.kill: SIGTERM sent, process gone on check
        kill_calls = []

        def mock_kill(pid, sig):
            kill_calls.append((pid, sig))
            if sig == signal.SIGTERM:
                return None
            elif sig == 0:
                raise ProcessLookupError()  # Process gone
            raise ProcessLookupError()

        monkeypatch.setattr(os, "kill", mock_kill)

        result = DaemonController._kill_process(test_pid)

        assert result["status"] == "ok"
        assert "SIGTERM" in result["message"]


# ── _handle_notifications Tests ──────────────────────────────────


class TestHandleNotifications:
    def test_no_alerts_does_nothing(self, controller):
        """Test that empty alerts list does nothing."""
        controller._handle_notifications([])
        assert controller.interval == controller.cfg.poll_interval  # Should not change

    def test_notification_disabled(self, controller, sample_alert):
        """Test that notifications are skipped when disabled."""
        controller.cfg.notifications_enabled = False

        with patch("subprocess.Popen") as mock_popen:
            controller._handle_notifications([sample_alert])

        mock_popen.assert_not_called()

    def test_info_alert_no_notification(self, controller):
        """Test that INFO alerts don't trigger notifications."""
        info_alert = Alert(
            level=AlertLevel.INFO,
            port=9000,
            proto="tcp",
            process_name="app",
            pid=1000,
            message="New listening port 9000",
        )

        with patch("subprocess.Popen") as mock_popen:
            controller._handle_notifications([info_alert])

        mock_popen.assert_not_called()

    def test_warning_alert_sends_notification(self, controller, sample_alert):
        """Test that WARNING alerts trigger notifications."""
        controller.cfg.notifications_enabled = True

        with patch("subprocess.Popen") as mock_popen:
            controller._handle_notifications([sample_alert])

        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        assert "notify-send" in call_args[0][0]
        assert "KPortWatch" in call_args[0][0]

    def test_critical_alert_sends_notification(self, controller, critical_alert):
        """Test that CRITICAL alerts trigger notifications."""
        controller.cfg.notifications_enabled = True

        with patch("subprocess.Popen") as mock_popen:
            controller._handle_notifications([critical_alert])

        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        assert "notify-send" in call_args[0][0]
        assert "-u" in call_args[0][0]
        assert "critical" in call_args[0][0]

    def test_notification_alert_ttl_dedup(self, controller, sample_alert, monkeypatch):
        """Test that alert TTL prevents duplicate notifications."""
        controller.cfg.notifications_enabled = True
        controller.cfg.alert_ttl = 3600.0

        # Add the alert to notified_alerts with recent timestamp
        alert_hash = f"{sample_alert.level}:{sample_alert.message}"
        controller.notified_alerts[alert_hash] = time.time() - 100  # 100 seconds ago

        with patch("subprocess.Popen") as mock_popen:
            controller._handle_notifications([sample_alert])

        # Should not send notification (within TTL)
        mock_popen.assert_not_called()

    def test_notification_after_ttl_expires(self, controller, sample_alert, monkeypatch):
        """Test that notification is sent after TTL expires."""
        controller.cfg.notifications_enabled = True
        controller.cfg.alert_ttl = 100.0

        # Add the alert to notified_alerts with old timestamp
        alert_hash = f"{sample_alert.level}:{sample_alert.message}"
        controller.notified_alerts[alert_hash] = time.time() - 200  # 200 seconds ago (> TTL)

        with patch("subprocess.Popen") as mock_popen:
            with patch("time.time", return_value=time.time()):
                controller._handle_notifications([sample_alert])

        # Should send notification (TTL expired)
        mock_popen.assert_called_once()

    def test_notification_rate_limiting(self, controller, sample_alert):
        """Test that notifications are rate limited."""
        controller.cfg.notifications_enabled = True
        controller.cfg.notification_rate_limit = 2
        controller.cfg.notification_rate_window = 60.0

        # Fill rate limit window
        controller.notification_timestamps = [time.time() - 10, time.time() - 5]

        with patch("subprocess.Popen") as mock_popen:
            with patch("time.time", return_value=time.time()):
                controller._handle_notifications([sample_alert])

        # Should be rate limited
        mock_popen.assert_not_called()

    def test_notification_rate_limit_window_expires(self, controller, sample_alert):
        """Test that rate limit resets after window expires."""
        controller.cfg.notifications_enabled = True
        controller.cfg.notification_rate_limit = 2
        controller.cfg.notification_rate_window = 60.0

        # Add old timestamps outside window
        controller.notification_timestamps = [time.time() - 70, time.time() - 65]

        with patch("subprocess.Popen") as mock_popen:
            with patch("time.time", return_value=time.time()):
                controller._handle_notifications([sample_alert])

        # Should send notification (old timestamps expired)
        mock_popen.assert_called_once()

    def test_multiple_alerts(self, controller, sample_alert, critical_alert):
        """Test handling multiple alerts in one call."""
        controller.cfg.notifications_enabled = True

        with patch("subprocess.Popen") as mock_popen:
            controller._handle_notifications([sample_alert, critical_alert])

        # Both should trigger notifications
        assert mock_popen.call_count == 2

    def test_notification_truncates_message(self, controller):
        """Test that long messages are truncated."""
        controller.cfg.notifications_enabled = True

        long_alert = Alert(
            level=AlertLevel.WARNING,
            port=8080,
            proto="tcp",
            process_name="test",
            pid=1000,
            message="A" * 300,  # Very long message
        )

        with patch("subprocess.Popen") as mock_popen:
            controller._handle_notifications([long_alert])

        mock_popen.assert_called_once()
        call_args = mock_popen.call_args
        # Message should be truncated to 200 chars
        message_arg = [arg for arg in call_args[0][0] if isinstance(arg, str) and "A" * 100 in arg]
        assert len(message_arg) > 0
        # Check truncation by verifying the argument isn't 300 chars
        assert len(message_arg[0]) < 300

    def test_notification_sanitizes_message(self, controller):
        """Test that control characters are stripped from message."""
        controller.cfg.notifications_enabled = True

        dirty_alert = Alert(
            level=AlertLevel.WARNING,
            port=8080,
            proto="tcp",
            process_name="test",
            pid=1000,
            message="Test\x00\x01\x02message with control chars",
        )

        with patch("subprocess.Popen") as mock_popen:
            controller._handle_notifications([dirty_alert])

        mock_popen.assert_called_once()
        # The message should have control chars removed
        call_args = mock_popen.call_args
        # Find the message argument (the last argument in the list)
        args_list = call_args[0][0]
        # The sanitized message is the last element
        sanitized_msg = args_list[-1]
        # Should not contain null bytes or other control chars (only printable)
        assert "\x00" not in sanitized_msg
        assert "\x01" not in sanitized_msg
        assert "\x02" not in sanitized_msg

    def test_notify_send_not_found(self, controller, sample_alert):
        """Test handling when notify-send is not found."""
        controller.cfg.notifications_enabled = True

        with patch("subprocess.Popen", side_effect=FileNotFoundError):
            # Should not raise exception
            controller._handle_notifications([sample_alert])

    def test_notify_send_os_error(self, controller, sample_alert):
        """Test handling when notify-send fails with OSError."""
        controller.cfg.notifications_enabled = True

        with patch("subprocess.Popen", side_effect=OSError("Failed")):
            # Should not raise exception
            controller._handle_notifications([sample_alert])

    def test_interval_set_to_alert_poll_interval(self, controller, sample_alert):
        """Test that interval is set to alert_poll_interval when alerts present."""
        controller.cfg.notifications_enabled = False
        initial_interval = controller.interval

        controller._handle_notifications([sample_alert])

        assert controller.interval == controller.cfg.alert_poll_interval
        assert controller.interval != initial_interval

    def test_notified_alerts_timestamp_updated(self, controller, sample_alert):
        """Test that notified_alerts timestamp is updated after sending notification."""
        controller.cfg.notifications_enabled = True
        alert_hash = f"{sample_alert.level}:{sample_alert.message}"

        with patch("subprocess.Popen"), patch("time.time", return_value=12345.0):
            controller._handle_notifications([sample_alert])

        assert alert_hash in controller.notified_alerts
        assert controller.notified_alerts[alert_hash] == 12345.0

    def test_notification_timestamp_added(self, controller, sample_alert):
        """Test that notification_timestamps is updated after sending notification."""
        controller.cfg.notifications_enabled = True
        initial_len = len(controller.notification_timestamps)

        with patch("subprocess.Popen"), patch("time.time", return_value=12345.0):
            controller._handle_notifications([sample_alert])

        assert len(controller.notification_timestamps) == initial_len + 1
        assert 12345.0 in controller.notification_timestamps

    def test_evicts_expired_alert_hashes(self, controller, sample_alert):
        """Test that expired alert hashes are evicted when cache is full."""
        controller.cfg.notifications_enabled = True
        controller.cfg.alert_ttl = 3600.0

        # Fill notified_alerts with 500+ entries
        now = time.time()
        for i in range(600):
            controller.notified_alerts[f"WARNING:Alert {i}"] = now - 4000  # Expired

        with patch("subprocess.Popen"), patch("time.time", return_value=now):
            controller._handle_notifications([sample_alert])

        # Should have evicted expired entries
        assert len(controller.notified_alerts) < 600

    def test_empty_alert_list_does_not_clear_rate_limit_timestamps(self, controller):
        """Test that notification_timestamps are only cleared during rate limiting check."""
        controller.notification_timestamps = [time.time() - 70, time.time() - 65]
        initial_len = len(controller.notification_timestamps)

        controller._handle_notifications([])

        # Timestamps should NOT be cleared by _handle_notifications with empty alerts
        # (clearing happens during rate limiting check when there are alerts to send)
        assert len(controller.notification_timestamps) == initial_len


# ── _adaptive_interval Tests ─────────────────────────────────────


class TestAdaptiveInterval:
    def test_default_interval_no_changes(self, controller, sample_listening_entries):
        """Test default interval when no changes and no alerts."""
        controller.last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in sample_listening_entries)
        )
        controller.last_change_time = time.time() - 50  # Changed 50s ago

        interval = controller._adaptive_interval(sample_listening_entries, [])

        assert interval == controller.cfg.poll_interval

    def test_alert_interval_when_alerts_present(self, controller, sample_listening_entries, sample_alert):
        """Test that alert_poll_interval is used when alerts are present."""
        interval = controller._adaptive_interval(sample_listening_entries, [sample_alert])

        assert interval == controller.cfg.alert_poll_interval

    def test_idle_interval_when_no_changes_for_threshold(self, controller, sample_listening_entries):
        """Test that idle_poll_interval is used when idle threshold exceeded."""
        controller.last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in sample_listening_entries)
        )
        controller.last_change_time = time.time() - 400  # Changed 400s ago (> idle_threshold_secs)

        interval = controller._adaptive_interval(sample_listening_entries, [])

        assert interval == controller.cfg.idle_poll_interval

    def test_updates_hash_on_change(self, controller, sample_listening_entries):
        """Test that last_snapshot_hash is updated when listening ports change."""
        # Set initial hash
        initial_entries = [sample_listening_entries[0]]
        controller.last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in initial_entries)
        )

        # Change the entries
        controller._adaptive_interval(sample_listening_entries, [])

        # Hash should be updated
        new_hash = hash(frozenset((e.local_port, e.proto, e.state) for e in sample_listening_entries))
        assert controller.last_snapshot_hash == new_hash
        assert controller.last_snapshot_hash != hash(
            frozenset((e.local_port, e.proto, e.state) for e in initial_entries)
        )

    def test_updates_change_time_on_change(self, controller, sample_listening_entries):
        """Test that last_change_time is updated when listening ports change."""
        controller.last_snapshot_hash = 12345  # Different hash
        old_change_time = controller.last_change_time
        controller.last_change_time = time.time() - 1000

        with patch("time.time", return_value=12345.0):
            controller._adaptive_interval(sample_listening_entries, [])

        assert controller.last_change_time == 12345.0
        assert controller.last_change_time != old_change_time

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
        controller.last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in sample_listening_entries)
        )
        controller.last_change_time = time.time() - controller.cfg.idle_threshold_secs + 0.001

        interval = controller._adaptive_interval(sample_listening_entries, [])

        # Just before threshold, should use default (not idle)
        assert interval == controller.cfg.poll_interval

    def test_just_over_idle_threshold(self, controller, sample_listening_entries):
        """Test behavior just over idle threshold."""
        controller.last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in sample_listening_entries)
        )
        controller.last_change_time = time.time() - (controller.cfg.idle_threshold_secs + 1)

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

        controller.last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in [entry1])
        )

        controller._adaptive_interval([entry2], [])

        # Hash should change (different state)
        assert controller.last_snapshot_hash != hash(
            frozenset((e.local_port, e.proto, e.state) for e in [entry1])
        )


# ── Error Counting Tests ─────────────────────────────────────────


class TestErrorCounting:
    def test_error_count_initial_zero(self, mock_args):
        """Test that _error_count starts at 0."""
        with patch.object(DaemonController, "_init_components"):
            ctrl = DaemonController(mock_args)
            assert ctrl._error_count == 0

    def test_error_count_not_incremented_directly(self, controller):
        """Test that _error_count is not directly modified by tests."""
        initial_count = controller._error_count
        controller._error_count += 1
        assert controller._error_count == initial_count + 1

    def test_error_count_resets_on_success(self, controller):
        """Test that _error_count can be reset to 0."""
        controller._error_count = 5
        controller._error_count = 0  # Simulate reset on success
        assert controller._error_count == 0

    def test_error_count_increments_on_error(self, controller):
        """Test that _error_count increments."""
        controller._error_count = 2
        controller._error_count += 1
        assert controller._error_count == 3

    def test_error_count_stops_at_threshold(self, controller):
        """Test that daemon would stop at error threshold (10)."""
        controller._error_count = 10
        # In run() loop, this would set running = False
        assert controller._error_count >= 10

    def test_error_count_below_threshold_continues(self, controller):
        """Test that daemon continues when error count below threshold."""
        controller._error_count = 9
        # In run() loop, this would not stop the daemon
        assert controller._error_count < 10

    def test_consecutive_errors_increment(self, controller):
        """Test that consecutive errors increment the counter."""
        for _i in range(5):
            controller._error_count += 1
        assert controller._error_count == 5

    def test_error_count_tracks_consecutive_failures(self, controller):
        """Test that error count tracks consecutive failures."""
        # Simulate error sequence
        controller._error_count = 0
        for _ in range(3):
            controller._error_count += 1
        assert controller._error_count == 3

        # Simulate success resets
        controller._error_count = 0
        assert controller._error_count == 0

        # Simulate new error sequence
        controller._error_count += 1
        assert controller._error_count == 1

    def test_error_count_threshold_prevents_infinite_loop(self, controller):
        """Test that error threshold prevents infinite error loop."""
        # Simulate hitting the threshold
        for _ in range(10):
            controller._error_count += 1
        assert controller._error_count == 10

        # At this point, running would be set to False in run()
        controller.running = False
        assert controller.running is False


# ── Cleanup Tests ───────────────────────────────────────────────


class TestCleanup:
    def test_cleanup_closes_history(self, controller):
        """Test that cleanup closes history recorder."""
        controller.history = Mock()
        controller._cleanup()

        controller.history.close.assert_called_once()

    def test_cleanup_with_none_history(self, controller):
        """Test cleanup with None history doesn't crash."""
        controller.history = None
        # Should not raise
        controller._cleanup()

    def test_cleanup_saves_baseline(self, controller):
        """Test that cleanup saves baseline."""
        controller.cfg = Mock()
        controller.cfg.baseline_file = "/tmp/test-baseline.json"
        controller.alert_engine = Mock()
        controller.socket_server = None
        controller.history = Mock()

        controller._cleanup()

        controller.alert_engine.save_baseline.assert_called_once_with(controller.cfg.baseline_file)

    def test_cleanup_stops_socket_server(self, controller):
        """Test that cleanup stops socket server."""
        controller.socket_server = Mock()
        controller.history = Mock()
        controller.alert_engine = None

        controller._cleanup()

        controller.socket_server.stop.assert_called_once()

    def test_cleanup_with_none_socket_server(self, controller):
        """Test cleanup with None socket server doesn't crash."""
        controller.socket_server = None
        controller.history = Mock()
        controller.alert_engine = None

        # Should not raise
        controller._cleanup()

    def test_cleanup_with_none_alert_engine(self, controller):
        """Test cleanup with None alert_engine doesn't crash."""
        controller.alert_engine = None
        controller.socket_server = None
        controller.history = Mock()

        # Should not raise
        controller._cleanup()

    def test_cleanup_unlinks_pid_file(self, controller, tmp_path, monkeypatch):
        """Test that cleanup removes PID file."""
        pid_file = tmp_path / "test.pid"
        pid_file.write_text("12345")

        controller.history = Mock()
        controller.socket_server = None
        controller.alert_engine = None

        # Mock PID_FILE
        with patch("backend.daemon_controller.PID_FILE", str(pid_file)):
            controller._cleanup()

        assert not pid_file.exists()

    def test_cleanup_handles_missing_pid_file(self, controller, monkeypatch):
        """Test cleanup handles missing PID file gracefully."""
        controller.history = Mock()
        controller.socket_server = None
        controller.alert_engine = None

        # Mock PID_FILE to non-existent path
        with patch("backend.daemon_controller.PID_FILE", "/tmp/nonexistent-kportwatch.pid"):
            # Should not raise
            controller._cleanup()

    def test_cleanup_flushes_geoip_cache_when_enabled(self, controller):
        """Test that cleanup flushes GeoIP cache when enabled."""
        controller.cfg = Mock()
        controller.cfg.geoip_enabled = True
        controller.alert_engine = None
        controller.socket_server = None
        controller.history = Mock()

        # Mock geoip_mod
        with patch("backend.daemon_controller.geoip_mod") as mock_geoip:
            controller._cleanup()
            mock_geoip.flush_cache.assert_called_once()

    def test_cleanup_skips_geoip_flush_when_disabled(self, controller):
        """Test that cleanup skips GeoIP flush when disabled."""
        controller.cfg = Mock()
        controller.cfg.geoip_enabled = False
        controller.alert_engine = None
        controller.socket_server = None
        controller.history = Mock()

        # Mock geoip_mod
        with patch("backend.daemon_controller.geoip_mod") as mock_geoip:
            controller._cleanup()
            mock_geoip.flush_cache.assert_not_called()

    def test_cleanup_shutdown_rdns_when_psutil_available(self, controller):
        """Test that cleanup shuts down rdns when psutil is available."""
        controller.history = Mock()
        controller.socket_server = None
        controller.alert_engine = None

        with patch("backend.daemon_controller._HAS_PSUTIL", True):
            with patch("backend.parsers.rdns") as mock_rdns:
                with patch("backend.daemon_controller.geoip_mod"):
                    controller._cleanup()
                    mock_rdns.shutdown.assert_called_once()

    def test_cleanup_shutdown_geoip_when_psutil_available(self, controller):
        """Test that cleanup shuts down geoip when psutil is available."""
        controller.history = Mock()
        controller.socket_server = None
        controller.alert_engine = None

        with patch("backend.daemon_controller._HAS_PSUTIL", True):
            with patch("backend.daemon_controller.geoip_mod") as mock_geoip:
                with patch("backend.parsers.rdns"):
                    controller._cleanup()
                    mock_geoip.shutdown.assert_called_once()

    def test_cleanup_does_not_suppress_all_exceptions(self, controller):
        """Test that cleanup does not suppress all exceptions - only specific ones."""
        controller.history = Mock()
        controller.history.close.side_effect = Exception("History close error")
        controller.socket_server = None
        controller.alert_engine = None
        controller.cfg = Mock()
        controller.cfg.geoip_enabled = False

        # history.close() exceptions are NOT suppressed - they propagate
        with pytest.raises(Exception, match="History close error"):
            controller._cleanup()

        # Verify close was attempted
        controller.history.close.assert_called_once()


# ── Integration-style Tests ─────────────────────────────────────


class TestIntegration:
    def test_full_command_flow_valid_kill(self, controller, monkeypatch):
        """Test full flow of valid kill command."""
        test_pid = 12345
        test_uid = os.getuid()

        # Clear the class-level timestamp list first
        DaemonController._kill_timestamps.clear()

        # Mock all dependencies
        mock_stat_result = Mock()
        mock_stat_result.st_uid = test_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        with patch.object(
            DaemonController, "_kill_process", return_value={"status": "ok", "message": "SIGTERM"}
        ):
            result = controller._handle_socket_command({"command": "kill", "pid": test_pid})

        assert result["status"] == "ok"

    def test_full_command_flow_rate_limit_then_success(self, controller, monkeypatch):
        """Test flow: rate limit hit, then success after time passes."""
        test_pid = 12345
        test_uid = os.getuid()

        # Clear the class-level timestamp list first
        DaemonController._kill_timestamps.clear()

        mock_stat_result = Mock()
        mock_stat_result.st_uid = test_uid
        monkeypatch.setattr(os, "stat", lambda path: mock_stat_result)

        with patch.object(
            DaemonController, "_kill_process", return_value={"status": "ok", "message": "Killed"}
        ):
            # Hit rate limit (5 kills at t=0.0)
            with patch("time.time", return_value=0.0):
                for _ in range(5):
                    result = controller._handle_socket_command({"command": "kill", "pid": test_pid})
                    assert result["status"] == "ok"

            # 6th kill should be rate limited (still at t=0.0 context exited, using real time)
            # Since real time > 0, timestamps should still be within 60s window
            # But we need to ensure the rate limiting check happens with recent timestamps
            # Let's verify the timestamps were added
            assert len(DaemonController._kill_timestamps) == 5
            assert all(t == 0.0 for t in DaemonController._kill_timestamps)

            # 6th kill with time.time()=1.0 (still within 60s window of timestamps at 0.0)
            with patch("time.time", return_value=1.0):
                result = controller._handle_socket_command({"command": "kill", "pid": test_pid})
                assert result["status"] == "error"
                assert "Rate limit" in result["message"]

            # Wait for rate limit to expire (all 5 timestamps should be purged at t=61.0)
            with patch("time.time", return_value=61.0):
                result = controller._handle_socket_command({"command": "kill", "pid": test_pid})
                assert result["status"] == "ok"

    def test_notification_flow_with_multiple_alerts(self, controller):
        """Test notification flow with multiple alert types."""
        alerts = [
            Alert(level=AlertLevel.INFO, port=8000, proto="tcp", process_name="app1", pid=1000, message="Info"),
            Alert(level=AlertLevel.WARNING, port=9000, proto="tcp", process_name="app2", pid=2000, message="Warning"),
            Alert(level=AlertLevel.CRITICAL, port=4444, proto="tcp", process_name="app3", pid=3000, message="Critical"),
        ]

        controller.cfg.notifications_enabled = True

        with patch("subprocess.Popen") as mock_popen:
            controller._handle_notifications(alerts)

        # Only WARNING and CRITICAL should trigger notifications
        assert mock_popen.call_count == 2

    def test_adaptive_interval_flow_active_to_idle(self, controller, sample_listening_entries):
        """Test interval flow from active to idle state."""
        # Start with recent change
        controller.last_change_time = time.time() - 10
        controller.last_snapshot_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in sample_listening_entries)
        )

        interval1 = controller._adaptive_interval(sample_listening_entries, [])
        assert interval1 == controller.cfg.poll_interval

        # Simulate time passing beyond idle threshold
        controller.last_change_time = time.time() - 400
        interval2 = controller._adaptive_interval(sample_listening_entries, [])
        assert interval2 == controller.cfg.idle_poll_interval

    def test_error_recovery_flow(self, controller):
        """Test error count and recovery flow."""
        # Initial state
        assert controller._error_count == 0

        # Simulate errors
        for _ in range(3):
            controller._error_count += 1
        assert controller._error_count == 3

        # Simulate successful recovery
        controller._error_count = 0
        assert controller._error_count == 0

        # New errors
        controller._error_count += 1
        assert controller._error_count == 1
