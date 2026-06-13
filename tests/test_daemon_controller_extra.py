"""Additional tests for backend/daemon/controller.py.

Tests cover: _init_components, _handle_sighup, _handle_shutdown_signal,
_sleep_remaining, and run() loop behavior - previously uncovered lines.
"""

from __future__ import annotations

import signal
import time
from unittest.mock import Mock, patch

import pytest
from backend.daemon.collector import CollectedData
from backend.daemon.controller import DaemonController
from backend.models import SocketEntry
from shared.config import AppConfig

# ── Fixtures ───────────────────────────────────────────────────


@pytest.fixture
def mock_args():
    args = Mock()
    args.interval = None
    return args


@pytest.fixture
def mock_config():
    cfg = AppConfig()
    cfg.poll_interval = 2.0
    cfg.alert_poll_interval = 1.0
    cfg.idle_poll_interval = 10.0
    cfg.idle_threshold_secs = 300.0
    cfg.notifications_enabled = True
    cfg.geoip_enabled = False
    cfg.update_enabled = False
    cfg.data_file = "/tmp/test-data.json"
    cfg.socket_path = "/tmp/test.sock"
    cfg.baseline_file = "/tmp/test-baseline.json"
    cfg.heartbeat_file = "/tmp/test-heartbeat.json"
    cfg.history_retention_days = 30
    cfg.baseline_duration = 300.0
    cfg.dns_cache_size = 200
    cfg.dns_max_pending = 30
    cfg.known_safe_ports = {22: "sshd", 80: "nginx"}
    cfg.malicious_ports = [4444]
    cfg.burst_threshold = 3
    cfg.privileged_port_max = 1024
    cfg.custom_rules = []
    cfg.port_whitelist = []
    cfg.port_blacklist = []
    cfg.ip_blacklist = []
    cfg.geoip_api_url = "https://example.com"
    cfg.geoip_cache_file = "/tmp/geoip.json"
    cfg.geoip_cache_max_entries = 100
    cfg.geoip_cache_ttl_days = 30
    cfg.geoip_batch_size = 10
    cfg.geoip_timeout = 5
    cfg.config_path = "/tmp/test-config.toml"
    cfg.notification_rate_limit = 10
    cfg.notification_rate_window = 60.0
    cfg.alert_ttl = 3600.0
    return cfg


def _make_controller(mock_args, mock_config):
    """Create a controller with _init_components patched out, then inject mocks."""
    with patch.object(DaemonController, "_init_components"):
        ctrl = DaemonController(mock_args)
    ctrl.cfg = mock_config
    ctrl.alert_engine = Mock()
    ctrl.alert_engine.malicious_ports = set()
    ctrl.alert_engine.known_safe = {}
    ctrl.alert_engine.port_blacklist = set()
    ctrl.alert_engine.is_baseline_complete.return_value = False
    ctrl.alert_engine.get_baseline_ports.return_value = frozenset()
    ctrl.history = Mock()
    ctrl.socket_server = Mock()
    ctrl.collector = Mock()
    ctrl.notification_manager = Mock()
    ctrl.snapshot_builder = Mock()
    ctrl.command_handler = Mock()
    ctrl.updater = Mock()
    ctrl.running = True
    return ctrl


# ══════════════════════════════════════════════════════════════
# _init_components Tests
# ══════════════════════════════════════════════════════════════


class TestInitComponents:
    """Tests for _init_components."""

    def test_init_creates_all_components(self, mock_args, mock_config):
        """All components are initialised."""
        with (
            patch("backend.daemon.controller.load_config", return_value=mock_config),
            patch("backend.daemon.controller.apply_cli_overrides", return_value=mock_config),
            patch("backend.parsers.rdns"),
            patch("backend.daemon.controller.AlertEngine") as mock_ae,
            patch("backend.daemon.controller.HistoryRecorder"),
            patch("backend.daemon.controller.CommandHandler"),
            patch("backend.daemon.controller.UnixSocketServer"),
            patch("backend.daemon.controller.DataCollector"),
            patch("backend.daemon.controller.NotificationManager"),
            patch("backend.daemon.controller.SnapshotBuilder"),
            patch("backend.daemon.controller.UpdateChecker"),
            patch("backend.daemon.controller.geoip_mod"),
            patch("signal.signal"),
        ):
            mock_ae.return_value.load_baseline.return_value = False

            ctrl = DaemonController(mock_args)
            ctrl._init_components()

            assert ctrl.cfg is not None
            assert ctrl.alert_engine is not None
            assert ctrl.history is not None
            assert ctrl.socket_server is not None
            assert ctrl.collector is not None
            assert ctrl.notification_manager is not None
            assert ctrl.snapshot_builder is not None
            assert ctrl.command_handler is not None
            assert ctrl.updater is not None

    def test_init_loads_config(self, mock_args, mock_config):
        """load_config is called during init."""
        with (
            patch("backend.daemon.controller.load_config", return_value=mock_config) as mock_load,
            patch("backend.daemon.controller.apply_cli_overrides", return_value=mock_config),
            patch("backend.parsers.rdns"),
            patch("backend.daemon.controller.AlertEngine") as mock_ae,
            patch("backend.daemon.controller.HistoryRecorder"),
            patch("backend.daemon.controller.CommandHandler"),
            patch("backend.daemon.controller.UnixSocketServer"),
            patch("backend.daemon.controller.DataCollector"),
            patch("backend.daemon.controller.NotificationManager"),
            patch("backend.daemon.controller.SnapshotBuilder"),
            patch("backend.daemon.controller.UpdateChecker"),
            patch("backend.daemon.controller.geoip_mod"),
            patch("signal.signal"),
        ):
            mock_ae.return_value.load_baseline.return_value = False
            ctrl = DaemonController(mock_args)
            ctrl._init_components()

            mock_load.assert_called_once()

    def test_init_configures_dns(self, mock_args, mock_config):
        """DNS cache is configured during init."""
        with (
            patch("backend.daemon.controller.load_config", return_value=mock_config),
            patch("backend.daemon.controller.apply_cli_overrides", return_value=mock_config),
            patch("backend.parsers.rdns") as mock_rdns,
            patch("backend.daemon.controller.AlertEngine") as mock_ae,
            patch("backend.daemon.controller.HistoryRecorder"),
            patch("backend.daemon.controller.CommandHandler"),
            patch("backend.daemon.controller.UnixSocketServer"),
            patch("backend.daemon.controller.DataCollector"),
            patch("backend.daemon.controller.NotificationManager"),
            patch("backend.daemon.controller.SnapshotBuilder"),
            patch("backend.daemon.controller.UpdateChecker"),
            patch("backend.daemon.controller.geoip_mod"),
            patch("signal.signal"),
        ):
            mock_ae.return_value.load_baseline.return_value = False
            ctrl = DaemonController(mock_args)
            ctrl._init_components()

            mock_rdns.configure.assert_called_once_with(
                max_cache_size=mock_config.dns_cache_size,
                max_pending=mock_config.dns_max_pending,
            )

    def test_init_geoip_enabled(self, mock_args, mock_config):
        """GeoIP module is initialized when enabled."""
        mock_config.geoip_enabled = True

        with (
            patch("backend.daemon.controller.load_config", return_value=mock_config),
            patch("backend.daemon.controller.apply_cli_overrides", return_value=mock_config),
            patch("backend.parsers.rdns"),
            patch("backend.daemon.controller.AlertEngine") as mock_ae,
            patch("backend.daemon.controller.HistoryRecorder"),
            patch("backend.daemon.controller.CommandHandler"),
            patch("backend.daemon.controller.UnixSocketServer"),
            patch("backend.daemon.controller.DataCollector"),
            patch("backend.daemon.controller.NotificationManager"),
            patch("backend.daemon.controller.SnapshotBuilder"),
            patch("backend.daemon.controller.UpdateChecker"),
            patch("backend.daemon.controller.geoip_mod") as mock_geoip,
            patch("signal.signal"),
        ):
            mock_ae.return_value.load_baseline.return_value = False
            ctrl = DaemonController(mock_args)
            ctrl._init_components()

            mock_geoip.init.assert_called_once()

    def test_init_geoip_disabled(self, mock_args, mock_config):
        """GeoIP module is NOT initialized when disabled."""
        mock_config.geoip_enabled = False

        with (
            patch("backend.daemon.controller.load_config", return_value=mock_config),
            patch("backend.daemon.controller.apply_cli_overrides", return_value=mock_config),
            patch("backend.parsers.rdns"),
            patch("backend.daemon.controller.AlertEngine") as mock_ae,
            patch("backend.daemon.controller.HistoryRecorder"),
            patch("backend.daemon.controller.CommandHandler"),
            patch("backend.daemon.controller.UnixSocketServer"),
            patch("backend.daemon.controller.DataCollector"),
            patch("backend.daemon.controller.NotificationManager"),
            patch("backend.daemon.controller.SnapshotBuilder"),
            patch("backend.daemon.controller.UpdateChecker"),
            patch("backend.daemon.controller.geoip_mod") as mock_geoip,
            patch("signal.signal"),
        ):
            mock_ae.return_value.load_baseline.return_value = False
            ctrl = DaemonController(mock_args)
            ctrl._init_components()

            mock_geoip.init.assert_not_called()

    def test_init_loads_baseline(self, mock_args, mock_config):
        """AlertEngine.load_baseline is called during init."""
        with (
            patch("backend.daemon.controller.load_config", return_value=mock_config),
            patch("backend.daemon.controller.apply_cli_overrides", return_value=mock_config),
            patch("backend.parsers.rdns"),
            patch("backend.daemon.controller.AlertEngine") as mock_ae,
            patch("backend.daemon.controller.HistoryRecorder"),
            patch("backend.daemon.controller.CommandHandler"),
            patch("backend.daemon.controller.UnixSocketServer"),
            patch("backend.daemon.controller.DataCollector"),
            patch("backend.daemon.controller.NotificationManager"),
            patch("backend.daemon.controller.SnapshotBuilder"),
            patch("backend.daemon.controller.UpdateChecker"),
            patch("backend.daemon.controller.geoip_mod"),
            patch("signal.signal"),
        ):
            mock_ae.return_value.load_baseline.return_value = True
            ctrl = DaemonController(mock_args)
            ctrl._init_components()

            mock_ae.return_value.load_baseline.assert_called_once_with(mock_config.baseline_file)

    def test_init_registers_signal_handlers(self, mock_args, mock_config):
        """Signal handlers are registered during init."""
        with (
            patch("backend.daemon.controller.load_config", return_value=mock_config),
            patch("backend.daemon.controller.apply_cli_overrides", return_value=mock_config),
            patch("backend.parsers.rdns"),
            patch("backend.daemon.controller.AlertEngine") as mock_ae,
            patch("backend.daemon.controller.HistoryRecorder"),
            patch("backend.daemon.controller.CommandHandler"),
            patch("backend.daemon.controller.UnixSocketServer"),
            patch("backend.daemon.controller.DataCollector"),
            patch("backend.daemon.controller.NotificationManager"),
            patch("backend.daemon.controller.SnapshotBuilder"),
            patch("backend.daemon.controller.UpdateChecker"),
            patch("backend.daemon.controller.geoip_mod"),
            patch("signal.signal") as mock_signal,
        ):
            mock_ae.return_value.load_baseline.return_value = False
            ctrl = DaemonController(mock_args)
            ctrl._init_components()

            # SIGTERM and SIGINT should be registered
            sig_args = [c[0][0] for c in mock_signal.call_args_list]
            assert signal.SIGTERM in sig_args
            assert signal.SIGINT in sig_args

    def test_init_interval_from_config(self, mock_args, mock_config):
        """Interval is set from config during init."""
        mock_config.poll_interval = 3.5

        with (
            patch("backend.daemon.controller.load_config", return_value=mock_config),
            patch("backend.daemon.controller.apply_cli_overrides", return_value=mock_config),
            patch("backend.parsers.rdns"),
            patch("backend.daemon.controller.AlertEngine") as mock_ae,
            patch("backend.daemon.controller.HistoryRecorder"),
            patch("backend.daemon.controller.CommandHandler"),
            patch("backend.daemon.controller.UnixSocketServer"),
            patch("backend.daemon.controller.DataCollector"),
            patch("backend.daemon.controller.NotificationManager"),
            patch("backend.daemon.controller.SnapshotBuilder"),
            patch("backend.daemon.controller.UpdateChecker"),
            patch("backend.daemon.controller.geoip_mod"),
            patch("signal.signal"),
        ):
            mock_ae.return_value.load_baseline.return_value = False
            ctrl = DaemonController(mock_args)
            ctrl._init_components()

            assert ctrl.interval == 3.5


# ══════════════════════════════════════════════════════════════
# Signal Handler Tests
# ══════════════════════════════════════════════════════════════


class TestSignalHandlers:
    """Tests for _handle_sighup and _handle_shutdown_signal."""

    def test_sighup_reloads_config(self, mock_args, mock_config):
        """SIGHUP reloads configuration."""
        ctrl = _make_controller(mock_args, mock_config)

        with (
            patch("backend.daemon.controller.load_config", return_value=mock_config) as mock_load,
            patch("backend.daemon.controller.apply_cli_overrides", return_value=mock_config),
        ):
            ctrl._handle_sighup(signal.SIGHUP, None)
            mock_load.assert_called_once_with(mock_config.config_path)

    def test_sighup_updates_interval(self, mock_args, mock_config):
        """SIGHUP updates the poll interval from reloaded config."""
        ctrl = _make_controller(mock_args, mock_config)

        new_config = mock_config
        new_config.poll_interval = 5.0

        with (
            patch("backend.daemon.controller.load_config", return_value=new_config),
            patch("backend.daemon.controller.apply_cli_overrides", return_value=new_config),
        ):
            ctrl._handle_sighup(signal.SIGHUP, None)
            assert ctrl.interval == 5.0

    def test_sighup_reconfigures_components(self, mock_args, mock_config):
        """SIGHUP propagates new config to all components."""
        ctrl = _make_controller(mock_args, mock_config)

        with (
            patch("backend.daemon.controller.load_config", return_value=mock_config),
            patch("backend.daemon.controller.apply_cli_overrides", return_value=mock_config),
        ):
            ctrl._handle_sighup(signal.SIGHUP, None)

            ctrl.collector.reconfigure.assert_called_once_with(mock_config)
            ctrl.notification_manager.reconfigure.assert_called_once_with(mock_config)
            ctrl.snapshot_builder.reconfigure.assert_called_once_with(mock_config)
            ctrl.updater.reconfigure.assert_called_once_with(mock_config)

    def test_sighup_resets_baseline(self, mock_args, mock_config):
        """SIGHUP resets the alert engine baseline."""
        ctrl = _make_controller(mock_args, mock_config)

        with (
            patch("backend.daemon.controller.load_config", return_value=mock_config),
            patch("backend.daemon.controller.apply_cli_overrides", return_value=mock_config),
        ):
            ctrl._handle_sighup(signal.SIGHUP, None)
            ctrl.alert_engine.reset_baseline.assert_called_once()

    def test_shutdown_sets_running_false(self, mock_args, mock_config):
        """SIGTERM sets running to False."""
        ctrl = _make_controller(mock_args, mock_config)
        assert ctrl.running is True
        ctrl._handle_shutdown_signal(signal.SIGTERM, None)
        assert ctrl.running is False

    def test_sigint_sets_running_false(self, mock_args, mock_config):
        """SIGINT sets running to False."""
        ctrl = _make_controller(mock_args, mock_config)
        ctrl._handle_shutdown_signal(signal.SIGINT, None)
        assert ctrl.running is False


# ══════════════════════════════════════════════════════════════
# Sleep Helper Tests
# ══════════════════════════════════════════════════════════════


class TestSleepRemaining:
    """Tests for _sleep_remaining."""

    def test_sleep_zero_when_elapsed_exceeds_interval(self, mock_args, mock_config):
        """No sleep when elapsed time exceeds the interval."""
        ctrl = _make_controller(mock_args, mock_config)
        ctrl.interval = 2.0

        with patch("time.time", return_value=100.0):  # cycle_start would be 97.0
            with patch("time.sleep") as mock_sleep:
                ctrl._sleep_remaining(97.0)  # 3 seconds elapsed > 2 second interval
                mock_sleep.assert_not_called()

    def test_sleep_when_time_remaining(self, mock_args, mock_config):
        """Sleeps for remaining time when elapsed < interval."""
        ctrl = _make_controller(mock_args, mock_config)
        ctrl.interval = 2.0

        # Simulate: cycle_start at t=100, current t=100.5 → 1.5s remaining
        call_num = [0]

        def fake_time():
            call_num[0] += 1
            if call_num[0] <= 3:
                return 100.5  # Before end_time (102.0)
            return 103.0  # After end_time

        with patch("time.time", side_effect=fake_time):
            with patch("time.sleep") as mock_sleep:
                ctrl._sleep_remaining(100.0)
                assert mock_sleep.called

    def test_no_sleep_when_not_running(self, mock_args, mock_config):
        """No sleep when running is False."""
        ctrl = _make_controller(mock_args, mock_config)
        ctrl.running = False
        ctrl.interval = 10.0

        with patch("time.sleep") as mock_sleep:
            ctrl._sleep_remaining(time.time())
            mock_sleep.assert_not_called()

    def test_interruptible_sleep(self, mock_args, mock_config):
        """Sleep checks self.running in loop."""
        ctrl = _make_controller(mock_args, mock_config)
        ctrl.interval = 5.0

        sleep_count = [0]

        def fake_sleep(dt):
            sleep_count[0] += 1
            if sleep_count[0] >= 1:
                ctrl.running = False

        with patch("time.time", return_value=100.0):
            with patch("time.sleep", side_effect=fake_sleep):
                ctrl._sleep_remaining(98.0)
                assert sleep_count[0] >= 1


# ══════════════════════════════════════════════════════════════
# Run Loop Tests
# ══════════════════════════════════════════════════════════════


class TestRunLoop:
    """Tests for the main run() loop."""

    def test_run_calls_init_components(self, mock_args, mock_config):
        """run() calls _init_components first."""
        ctrl = _make_controller(mock_args, mock_config)

        # Make the loop run once then stop
        ctrl.collector.collect.side_effect = Exception("stop test")
        call_count = [0]

        def fake_sleep(cycle_start):
            call_count[0] += 1
            if call_count[0] >= 1:
                ctrl.running = False

        ctrl._sleep_remaining = fake_sleep

        with patch.object(ctrl, "_init_components") as mock_init, patch.object(ctrl, "_cleanup"):
            ctrl.run()
            mock_init.assert_called_once()

    def test_run_single_cycle(self, mock_args, mock_config):
        """run() executes at least one collection cycle."""
        ctrl = _make_controller(mock_args, mock_config)

        sample_data = CollectedData(
            listening=[
                SocketEntry(
                    proto="tcp",
                    local_ip="0.0.0.0",
                    local_port=22,
                    remote_ip="0.0.0.0",
                    remote_port=0,
                    state="LISTEN",
                    state_code="0A",
                    uid=0,
                    inode=1,
                )
            ],
            established=[],
            traffic={},
            process_tree={},
        )
        ctrl.collector.collect.return_value = sample_data
        ctrl.alert_engine.analyze.return_value = []

        # Run one cycle then stop
        cycle_count = [0]

        def stop_after_one(cycle_start):
            cycle_count[0] += 1
            ctrl.running = False

        ctrl._sleep_remaining = stop_after_one

        with patch.object(ctrl, "_init_components"), patch.object(ctrl, "_cleanup"):
            ctrl.run()

        assert cycle_count[0] >= 1
        ctrl.collector.collect.assert_called()
        ctrl.alert_engine.analyze.assert_called_once()
        ctrl.snapshot_builder.build_and_publish.assert_called_once()
        ctrl.notification_manager.handle.assert_called_once()
        ctrl.updater.check.assert_called()

    def test_run_calls_cleanup(self, mock_args, mock_config):
        """run() calls _cleanup on exit."""
        ctrl = _make_controller(mock_args, mock_config)
        ctrl.collector.collect.side_effect = Exception("stop")

        def stop_immediately(cycle_start):
            ctrl.running = False

        ctrl._sleep_remaining = stop_immediately

        with patch.object(ctrl, "_init_components"), patch.object(ctrl, "_cleanup") as mock_cleanup:
            ctrl.run()
            mock_cleanup.assert_called_once()

    def test_run_handles_collection_error(self, mock_args, mock_config):
        """run() handles errors from collector without crashing."""
        ctrl = _make_controller(mock_args, mock_config)

        call_count = [0]

        def bad_collect():
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("Collection failed")
            ctrl.running = False
            return CollectedData(listening=[], established=[], traffic={}, process_tree={})

        ctrl.collector.collect.side_effect = bad_collect
        ctrl.alert_engine.analyze.return_value = []

        def fake_sleep(cycle_start):
            pass

        ctrl._sleep_remaining = fake_sleep

        with patch.object(ctrl, "_init_components"), patch.object(ctrl, "_cleanup"):
            ctrl.run()

        # Error count incremented then reset
        assert ctrl._error_count == 0  # Reset on successful cycle

    def test_run_stops_after_10_errors(self, mock_args, mock_config):
        """run() stops after 10 consecutive errors."""
        ctrl = _make_controller(mock_args, mock_config)
        ctrl.collector.collect.side_effect = RuntimeError("persistent failure")

        def fake_sleep(cycle_start):
            pass

        ctrl._sleep_remaining = fake_sleep

        with patch.object(ctrl, "_init_components"), patch.object(ctrl, "_cleanup"):
            ctrl.run()

        assert ctrl.running is False
        assert ctrl._error_count >= 10

    def test_run_baseline_persistence(self, mock_args, mock_config):
        """run() saves baseline when it changes."""
        ctrl = _make_controller(mock_args, mock_config)

        sample_data = CollectedData(
            listening=[
                SocketEntry(
                    proto="tcp",
                    local_ip="0.0.0.0",
                    local_port=22,
                    remote_ip="0.0.0.0",
                    remote_port=0,
                    state="LISTEN",
                    state_code="0A",
                    uid=0,
                    inode=1,
                )
            ],
            established=[],
            traffic={},
            process_tree={},
        )
        ctrl.collector.collect.return_value = sample_data
        ctrl.alert_engine.analyze.return_value = []
        ctrl.alert_engine.is_baseline_complete.return_value = True
        ctrl.alert_engine.get_baseline_ports.return_value = frozenset({22})

        def stop_after_one(cycle_start):
            ctrl.running = False

        ctrl._sleep_remaining = stop_after_one

        with patch.object(ctrl, "_init_components"), patch.object(ctrl, "_cleanup"):
            ctrl.run()

        ctrl.alert_engine.save_baseline.assert_called()

    def test_run_baseline_no_save_when_unchanged(self, mock_args, mock_config):
        """run() does not save baseline when it hasn't changed."""
        ctrl = _make_controller(mock_args, mock_config)

        sample_data = CollectedData(
            listening=[],
            established=[],
            traffic={},
            process_tree={},
        )
        ctrl.collector.collect.return_value = sample_data
        ctrl.alert_engine.analyze.return_value = []
        ctrl.alert_engine.is_baseline_complete.return_value = True
        baseline = frozenset({22, 80})
        ctrl.alert_engine.get_baseline_ports.return_value = baseline
        ctrl._prev_baseline = baseline  # Same as current

        def stop_after_one(cycle_start):
            ctrl.running = False

        ctrl._sleep_remaining = stop_after_one

        with patch.object(ctrl, "_init_components"), patch.object(ctrl, "_cleanup"):
            ctrl.run()

        ctrl.alert_engine.save_baseline.assert_not_called()

    def test_run_error_count_resets_on_success(self, mock_args, mock_config):
        """Error count resets to 0 after a successful cycle."""
        ctrl = _make_controller(mock_args, mock_config)

        call_count = [0]

        def collect_with_error():
            call_count[0] += 1
            if call_count[0] == 1:
                raise RuntimeError("first fails")
            return CollectedData(listening=[], established=[], traffic={}, process_tree={})

        ctrl.collector.collect.side_effect = collect_with_error
        ctrl.alert_engine.analyze.return_value = []

        def stop_on_second(cycle_start):
            if call_count[0] >= 2:
                ctrl.running = False

        ctrl._sleep_remaining = stop_on_second

        with patch.object(ctrl, "_init_components"), patch.object(ctrl, "_cleanup"):
            ctrl.run()

        assert ctrl._error_count == 0

    def test_run_sends_correct_interval_ms(self, mock_args, mock_config):
        """run() passes correct interval_ms to build_and_publish."""
        mock_config.poll_interval = 3.0
        ctrl = _make_controller(mock_args, mock_config)
        ctrl.interval = 3.0

        sample_data = CollectedData(
            listening=[],
            established=[],
            traffic={},
            process_tree={},
        )
        ctrl.collector.collect.return_value = sample_data
        ctrl.alert_engine.analyze.return_value = []

        def stop_after_one(cycle_start):
            ctrl.running = False

        ctrl._sleep_remaining = stop_after_one

        with patch.object(ctrl, "_init_components"), patch.object(ctrl, "_cleanup"):
            ctrl.run()

        build_call = ctrl.snapshot_builder.build_and_publish.call_args
        assert build_call.kwargs["interval_ms"] == 3000


# ══════════════════════════════════════════════════════════════
# Cleanup Edge Cases
# ══════════════════════════════════════════════════════════════


class TestCleanupEdgeCases:
    """Additional cleanup tests for previously uncovered lines."""

    def test_cleanup_calls_rdns_shutdown(self, mock_args, mock_config):
        """Cleanup calls rdns.shutdown()."""
        ctrl = _make_controller(mock_args, mock_config)

        with patch("backend.parsers.rdns") as mock_rdns:
            ctrl._cleanup()
            mock_rdns.shutdown.assert_called_once()

    def test_cleanup_calls_geoip_shutdown(self, mock_args, mock_config):
        """Cleanup calls geoip_mod.shutdown()."""
        ctrl = _make_controller(mock_args, mock_config)

        with patch("backend.daemon.controller.geoip_mod") as mock_geoip:
            ctrl._cleanup()
            mock_geoip.shutdown.assert_called_once()

    def test_cleanup_rdns_error_suppressed(self, mock_args, mock_config):
        """rdns shutdown errors are suppressed."""
        ctrl = _make_controller(mock_args, mock_config)

        with patch("backend.parsers.rdns") as mock_rdns:
            mock_rdns.shutdown.side_effect = Exception("rdns error")
            # Should not raise
            ctrl._cleanup()

    def test_cleanup_geoip_error_suppressed(self, mock_args, mock_config):
        """geoip shutdown errors are suppressed."""
        ctrl = _make_controller(mock_args, mock_config)

        with patch("backend.daemon.controller.geoip_mod") as mock_geoip:
            mock_geoip.shutdown.side_effect = Exception("geoip error")
            # Should not raise
            ctrl._cleanup()
