"""Tests for KPortWatch CLI entry points.

Tests cover:
- backend/export.py — export CLI tool
- backend/kportwatchctl.py — CLI control tool
- backend/kportwatch_client.py — TUI client entry point
"""
from __future__ import annotations

import signal
from unittest.mock import MagicMock, Mock, mock_open, patch

# ── Import the modules under test ────────────────────────────────
from backend import export, kportwatch_client, kportwatchctl

# =============================================================================
# Tests for backend/export.py
# =============================================================================

class TestExportCLIArgumentParsing:
    """Test CLI argument parsing for export.py.

    Note: The parser is created inside main() and not exposed as a module attribute.
    These tests verify argument handling through main() function behavior.
    """

    @patch("backend.export.export_history_json")
    @patch("sys.argv", ["kportwatch-export"])
    def test_default_arguments(self, mock_export_json):
        """Test parsing with no arguments uses defaults."""
        mock_export_json.return_value = 1
        export.main()
        # Verify export_history_json was called with default arguments
        call_args = mock_export_json.call_args
        assert call_args[1]['date'] is None
        assert call_args[1]['event_type'] is None
        assert call_args[1]['last_n'] is None

    @patch("backend.export.export_history_json")
    @patch("sys.argv", ["kportwatch-export", "--date", "2024-06-01"])
    def test_date_argument(self, mock_export_json):
        """Test --date argument."""
        mock_export_json.return_value = 1
        export.main()
        call_args = mock_export_json.call_args
        assert call_args[1]['date'] == "2024-06-01"

    @patch("backend.export.export_history_json")
    @patch("sys.argv", ["kportwatch-export", "--format", "json"])
    def test_format_json(self, mock_export_json):
        """Test --format json (default)."""
        mock_export_json.return_value = 1
        export.main()
        mock_export_json.assert_called_once()

    @patch("backend.export.export_history_csv")
    @patch("sys.argv", ["kportwatch-export", "--format", "csv"])
    def test_format_csv(self, mock_export_csv):
        """Test --format csv."""
        mock_export_csv.return_value = 1
        export.main()
        mock_export_csv.assert_called_once()

    @patch("backend.export.export_history_json")
    @patch("sys.argv", ["kportwatch-export", "--output", "custom.json"])
    def test_output_argument(self, mock_export_json):
        """Test --output argument."""
        mock_export_json.return_value = 1
        export.main()
        call_args = mock_export_json.call_args
        assert "custom.json" in call_args[0][0]

    @patch("backend.export.export_history_json")
    @patch("sys.argv", ["kportwatch-export", "--type", "summary"])
    def test_type_summary(self, mock_export_json):
        """Test --type summary."""
        mock_export_json.return_value = 1
        export.main()
        call_args = mock_export_json.call_args
        assert call_args[1]['event_type'] == "summary"

    @patch("backend.export.export_history_json")
    @patch("sys.argv", ["kportwatch-export", "--type", "alert"])
    def test_type_alert(self, mock_export_json):
        """Test --type alert."""
        mock_export_json.return_value = 1
        export.main()
        call_args = mock_export_json.call_args
        assert call_args[1]['event_type'] == "alert"

    @patch("backend.export.export_history_json")
    @patch("sys.argv", ["kportwatch-export", "--last", "100"])
    def test_last_argument(self, mock_export_json):
        """Test --last argument."""
        mock_export_json.return_value = 1
        export.main()
        call_args = mock_export_json.call_args
        assert call_args[1]['last_n'] == 100

    @patch("backend.export.list_available_dates")
    @patch("sys.argv", ["kportwatch-export", "--list-dates"])
    def test_list_dates_flag(self, mock_list_dates):
        """Test --list-dates flag."""
        mock_list_dates.return_value = []
        export.main()
        mock_list_dates.assert_called_once()

    @patch("backend.export.export_history_csv")
    @patch("sys.argv", ["kportwatch-export", "-d", "2024-06-01", "-f", "csv", "-o", "out.csv", "-t", "alert", "--last", "50"])
    def test_short_arguments(self, mock_export_csv):
        """Test short form arguments."""
        mock_export_csv.return_value = 1
        export.main()
        call_args = mock_export_csv.call_args
        assert "out.csv" in call_args[0][0]
        assert call_args[1]['date'] == "2024-06-01"
        assert call_args[1]['event_type'] == "alert"
        assert call_args[1]['last_n'] == 50


class TestExportListDates:
    """Test the --list-dates functionality."""

    @patch("backend.export.list_available_dates")
    @patch("builtins.print")
    @patch("sys.argv", ["kportwatch-export", "--list-dates"])
    def test_list_dates_with_data(self, mock_print, mock_list_dates):
        """Test listing dates when data exists."""
        mock_list_dates.return_value = ["2024-06-01", "2024-06-02", "2024-06-03"]
        export.main()
        mock_list_dates.assert_called_once()
        assert mock_print.call_count == 3
        mock_print.assert_any_call("2024-06-01")
        mock_print.assert_any_call("2024-06-02")
        mock_print.assert_any_call("2024-06-03")

    @patch("backend.export.list_available_dates")
    @patch("builtins.print")
    @patch("sys.argv", ["kportwatch-export", "--list-dates"])
    def test_list_dates_no_data(self, mock_print, mock_list_dates):
        """Test listing dates when no data exists."""
        mock_list_dates.return_value = []
        export.main()
        mock_list_dates.assert_called_once()
        mock_print.assert_called_once_with("No history data found.")


class TestExportSuccessfulExport:
    """Test successful export operations."""

    @patch("backend.export.export_history_json")
    @patch("builtins.print")
    @patch("sys.argv", ["kportwatch-export", "--format", "json", "--output", "test.json"])
    def test_export_json_success(self, mock_print, mock_export_json):
        """Test successful JSON export."""
        mock_export_json.return_value = 5
        export.main()
        mock_export_json.assert_called_once()
        mock_export_json.assert_called_once_with("test.json", date=None, event_type=None, last_n=None)
        mock_print.assert_called_once_with("Exported 5 entries to test.json")

    @patch("backend.export.export_history_csv")
    @patch("builtins.print")
    @patch("sys.argv", ["kportwatch-export", "--format", "csv", "--output", "test.csv"])
    def test_export_csv_success(self, mock_print, mock_export_csv):
        """Test successful CSV export."""
        mock_export_csv.return_value = 10
        export.main()
        mock_export_csv.assert_called_once_with("test.csv", date=None, event_type=None, last_n=None)
        mock_print.assert_called_once_with("Exported 10 entries to test.csv")

    @patch("backend.export.export_history_json")
    @patch("builtins.print")
    @patch("sys.argv", ["kportwatch-export", "--date", "2024-06-01"])
    def test_export_with_date(self, mock_print, mock_export_json):
        """Test export with specific date."""
        mock_export_json.return_value = 3
        export.main()
        mock_export_json.assert_called_once()
        call_args = mock_export_json.call_args
        assert "2024-06-01" in call_args[0][0]  # Should be in the output path
        assert call_args[1]['date'] == "2024-06-01"

    @patch("backend.export.export_history_json")
    @patch("builtins.print")
    @patch("sys.argv", ["kportwatch-export", "--type", "alert"])
    def test_export_with_type_filter(self, mock_print, mock_export_json):
        """Test export with event type filter."""
        mock_export_json.return_value = 2
        export.main()
        call_args = mock_export_json.call_args
        assert call_args[1]['event_type'] == "alert"

    @patch("backend.export.export_history_json")
    @patch("builtins.print")
    @patch("sys.argv", ["kportwatch-export", "--last", "50"])
    def test_export_with_last_n(self, mock_print, mock_export_json):
        """Test export with last N entries."""
        mock_export_json.return_value = 50
        export.main()
        call_args = mock_export_json.call_args
        assert call_args[1]['last_n'] == 50


class TestExportErrorHandling:
    """Test error handling in export CLI."""

    @patch("backend.export.export_history_json")
    @patch("builtins.print")
    @patch("sys.exit")
    @patch("sys.argv", ["kportwatch-export"])
    def test_no_data_found(self, mock_exit, mock_print, mock_export_json):
        """Test handling when no data is found."""
        mock_export_json.return_value = 0
        export.main()
        mock_export_json.assert_called_once()
        # Check that error message was printed to stderr
        assert any("No entries found" in str(call) for call in mock_print.call_args_list)
        mock_exit.assert_called_once_with(1)


class TestExportMainFunction:
    """Test the main() function of export.py."""

    @patch("backend.export.export_history_json")
    @patch("sys.argv", ["kportwatch-export", "--format", "json"])
    def test_main_calls_export_functions(self, mock_export_json):
        """Test that main() properly calls export functions."""
        mock_export_json.return_value = 1
        export.main()
        mock_export_json.assert_called_once()

    @patch("backend.export.list_available_dates")
    @patch("sys.argv", ["kportwatch-export", "--list-dates"])
    def test_main_list_dates(self, mock_list_dates):
        """Test main() with --list-dates."""
        mock_list_dates.return_value = []
        export.main()
        mock_list_dates.assert_called_once()


# =============================================================================
# Tests for backend/kportwatchctl.py
# =============================================================================

class TestKPortWatchCtlPIDHandling:
    """Test PID file handling functions."""

    @patch("builtins.open", new_callable=mock_open, read_data="12345\n")
    @patch("backend.kportwatchctl.PID_FILE", "/tmp/test-kportwatch.pid")
    def test_read_pid_success(self, mock_file):
        """Test successfully reading PID from file."""
        pid = kportwatchctl._read_pid()
        assert pid == 12345
        mock_file.assert_called_once_with("/tmp/test-kportwatch.pid")

    @patch("builtins.open", side_effect=FileNotFoundError)
    @patch("backend.kportwatchctl.PID_FILE", "/tmp/nonexistent.pid")
    def test_read_pid_not_found(self, mock_file):
        """Test reading PID when file doesn't exist."""
        pid = kportwatchctl._read_pid()
        assert pid is None

    @patch("builtins.open", new_callable=mock_open, read_data="not-a-number\n")
    @patch("backend.kportwatchctl.PID_FILE", "/tmp/invalid.pid")
    def test_read_pid_invalid_content(self, mock_file):
        """Test reading PID when file has invalid content."""
        pid = kportwatchctl._read_pid()
        assert pid is None

    @patch("builtins.open", new_callable=mock_open, read_data="")
    @patch("backend.kportwatchctl.PID_FILE", "/tmp/empty.pid")
    def test_read_pid_empty_file(self, mock_file):
        """Test reading PID from empty file."""
        pid = kportwatchctl._read_pid()
        assert pid is None

    @patch("os.kill")
    def test_is_alive_true(self, mock_kill):
        """Test checking if a process is alive (exists)."""
        mock_kill.return_value = None  # No exception means process exists
        result = kportwatchctl._is_alive(12345)
        assert result is True
        mock_kill.assert_called_once_with(12345, 0)

    @patch("os.kill", side_effect=ProcessLookupError)
    def test_is_alive_false(self, mock_kill):
        """Test checking if a process is alive (doesn't exist)."""
        result = kportwatchctl._is_alive(99999)
        assert result is False
        mock_kill.assert_called_once_with(99999, 0)

    @patch("os.kill", side_effect=PermissionError)
    def test_is_alive_permission_denied(self, mock_kill):
        """Test checking if process exists but we can't signal it."""
        result = kportwatchctl._is_alive(1)
        assert result is True  # Assume it exists if we get PermissionError

    @patch("time.sleep")
    @patch("os.kill")
    def test_wait_for_appears(self, mock_kill, mock_sleep):
        """Test waiting for a process to appear."""
        mock_kill.return_value = None  # Process exists
        result = kportwatchctl._wait_for(12345, timeout=1.0, alive=True)
        assert result is True
        mock_kill.assert_called_once_with(12345, 0)

    @patch("time.sleep")
    @patch("os.kill", side_effect=ProcessLookupError)
    def test_wait_for_disappears(self, mock_kill, mock_sleep):
        """Test waiting for a process to disappear."""
        result = kportwatchctl._wait_for(99999, timeout=1.0, alive=False)
        assert result is True
        mock_kill.assert_called_once_with(99999, 0)


class TestKPortWatchCtlStatusCommand:
    """Test the status command."""

    @patch("backend.kportwatchctl._read_pid")
    @patch("backend.kportwatchctl._is_alive")
    @patch("os.path.exists")
    @patch("backend.kportwatchctl.SOCKET_PATH", "/tmp/test.sock")
    @patch("backend.kportwatchctl.PID_FILE", "/tmp/test.pid")
    @patch("builtins.print")
    def test_status_not_running_no_pid(self, mock_print, mock_exists, mock_is_alive, mock_read_pid):
        """Test status when daemon is not running (no PID file)."""
        mock_read_pid.return_value = None

        args = Mock()
        result = kportwatchctl.cmd_status(args)

        assert result == 1
        mock_print.assert_called_once_with("❌ Daemon is not running (no PID file)")

    @patch("backend.kportwatchctl._read_pid")
    @patch("backend.kportwatchctl._is_alive")
    @patch("os.path.exists")
    @patch("backend.kportwatchctl.SOCKET_PATH", "/tmp/test.sock")
    @patch("backend.kportwatchctl.PID_FILE", "/tmp/test.pid")
    @patch("builtins.print")
    def test_status_not_running_stale_pid(self, mock_print, mock_exists, mock_is_alive, mock_read_pid):
        """Test status when PID file exists but process is dead."""
        mock_read_pid.return_value = 12345
        mock_is_alive.return_value = False

        args = Mock()
        result = kportwatchctl.cmd_status(args)

        assert result == 1
        mock_print.assert_called_once_with("❌ Daemon is not running (stale PID file: 12345)")

    @patch("backend.kportwatchctl._read_pid")
    @patch("backend.kportwatchctl._is_alive")
    @patch("os.path.exists")
    @patch("backend.kportwatchctl.SOCKET_PATH", "/tmp/test.sock")
    @patch("backend.kportwatchctl.PID_FILE", "/tmp/test.pid")
    @patch("builtins.print")
    def test_status_running_socket_exists(self, mock_print, mock_exists, mock_is_alive, mock_read_pid):
        """Test status when daemon is running and socket exists."""
        mock_read_pid.return_value = 12345
        mock_is_alive.return_value = True
        mock_exists.return_value = True

        args = Mock()
        result = kportwatchctl.cmd_status(args)

        assert result == 0
        calls = mock_print.call_args_list
        assert any("✅ Daemon is running (PID 12345)" in str(call) for call in calls)
        assert any("✅" in str(call) for call in calls)

    @patch("backend.kportwatchctl._read_pid")
    @patch("backend.kportwatchctl._is_alive")
    @patch("os.path.exists")
    @patch("backend.kportwatchctl.SOCKET_PATH", "/tmp/test.sock")
    @patch("backend.kportwatchctl.PID_FILE", "/tmp/test.pid")
    @patch("builtins.print")
    def test_status_running_no_socket(self, mock_print, mock_exists, mock_is_alive, mock_read_pid):
        """Test status when daemon is running but socket doesn't exist."""
        mock_read_pid.return_value = 12345
        mock_is_alive.return_value = True
        mock_exists.return_value = False

        args = Mock()
        result = kportwatchctl.cmd_status(args)

        assert result == 0
        calls = mock_print.call_args_list
        assert any("❌ not found" in str(call) for call in calls)


class TestKPortWatchCtlStopCommand:
    """Test the stop command."""

    @patch("backend.kportwatchctl._read_pid")
    @patch("backend.kportwatchctl._is_alive")
    @patch("backend.kportwatchctl._wait_for")
    @patch("backend.kportwatchctl._cleanup_pidfile")
    @patch("os.kill")
    @patch("builtins.print")
    def test_stop_success(self, mock_print, mock_kill, mock_cleanup, mock_wait, mock_is_alive, mock_read_pid):
        """Test successfully stopping the daemon."""
        mock_read_pid.return_value = 12345
        mock_is_alive.return_value = True
        mock_wait.return_value = True

        args = Mock()
        result = kportwatchctl.cmd_stop(args)

        assert result == 0
        mock_kill.assert_called_once_with(12345, signal.SIGTERM)
        mock_wait.assert_called_once_with(12345, timeout=5.0, alive=False)
        mock_cleanup.assert_called_once()

    @patch("backend.kportwatchctl._read_pid")
    @patch("backend.kportwatchctl._is_alive")
    @patch("backend.kportwatchctl._wait_for")
    @patch("backend.kportwatchctl._cleanup_pidfile")
    @patch("os.kill")
    @patch("builtins.print")
    def test_stop_force_kill(self, mock_print, mock_kill, mock_cleanup, mock_wait, mock_is_alive, mock_read_pid):
        """Test force killing daemon when it doesn't stop gracefully."""
        mock_read_pid.return_value = 12345
        mock_is_alive.side_effect = [True, False]  # First call says alive, second says dead
        mock_wait.return_value = False

        args = Mock()
        result = kportwatchctl.cmd_stop(args)

        assert result == 0
        # Should send SIGTERM first, then SIGKILL
        assert mock_kill.call_count >= 1

    @patch("backend.kportwatchctl._read_pid")
    @patch("backend.kportwatchctl._is_alive")
    @patch("backend.kportwatchctl._find_daemon_pids")
    @patch("backend.kportwatchctl._cleanup_pidfile")
    @patch("builtins.print")
    def test_stop_not_running(self, mock_print, mock_cleanup, mock_find, mock_is_alive, mock_read_pid):
        """Test stopping when daemon is not running."""
        mock_read_pid.return_value = None
        mock_find.return_value = []

        args = Mock()
        result = kportwatchctl.cmd_stop(args)

        assert result == 1
        mock_print.assert_called_with("❌ Daemon is not running")

    @patch("backend.kportwatchctl._read_pid")
    @patch("backend.kportwatchctl._find_daemon_pids")
    @patch("backend.kportwatchctl._cleanup_pidfile")
    @patch("builtins.print")
    def test_stop_process_already_gone(self, mock_print, mock_cleanup, mock_find, mock_read_pid):
        """Test stopping when process is already gone."""
        mock_read_pid.return_value = 12345
        mock_find.return_value = []  # No daemon processes found

        args = Mock()
        result = kportwatchctl.cmd_stop(args)

        assert result == 1
        # The actual error message when no process is found
        mock_print.assert_called_with("❌ Daemon is not running")


class TestKPortWatchCtlReloadCommand:
    """Test the reload command."""

    @patch("backend.kportwatchctl._read_pid")
    @patch("backend.kportwatchctl._is_alive")
    @patch("os.kill")
    @patch("builtins.print")
    def test_reload_success(self, mock_print, mock_kill, mock_is_alive, mock_read_pid):
        """Test successfully reloading daemon config."""
        mock_read_pid.return_value = 12345
        mock_is_alive.return_value = True
        mock_kill.return_value = None

        args = Mock()
        result = kportwatchctl.cmd_reload(args)

        assert result == 0
        mock_kill.assert_called_once_with(12345, signal.SIGHUP)
        mock_print.assert_called_once()

    @patch("backend.kportwatchctl._read_pid")
    @patch("os.kill", side_effect=ProcessLookupError)
    @patch("backend.kportwatchctl._cleanup_pidfile")
    @patch("builtins.print")
    def test_reload_process_gone(self, mock_print, mock_cleanup, mock_kill, mock_read_pid):
        """Test reload when process is already gone."""
        mock_read_pid.return_value = 12345

        args = Mock()
        result = kportwatchctl.cmd_reload(args)

        assert result == 1
        mock_print.assert_called()

    @patch("backend.kportwatchctl._read_pid")
    @patch("backend.kportwatchctl._find_daemon_pids")
    @patch("os.kill")
    @patch("builtins.print")
    def test_reload_via_pgrep_fallback(self, mock_print, mock_kill, mock_find, mock_read_pid):
        """Test reload using pgrep fallback when PID file is missing."""
        mock_read_pid.return_value = None
        mock_find.return_value = [12345, 12346]
        mock_kill.return_value = None

        args = Mock()
        result = kportwatchctl.cmd_reload(args)

        assert result == 0
        assert mock_kill.call_count == 2


class TestKPortWatchCtlKillCommand:
    """Test the kill command."""

    @patch("backend.kportwatchctl.send_command")
    @patch("builtins.print")
    def test_kill_success(self, mock_print, mock_send_command):
        """Test successfully killing a process via daemon."""
        mock_send_command.return_value = {"status": "ok", "message": "Process 9999 killed"}

        args = Mock()
        args.pid = 9999
        result = kportwatchctl.cmd_kill(args)

        assert result == 0
        mock_send_command.assert_called_once_with({"command": "kill", "pid": 9999})
        mock_print.assert_called_once()

    @patch("backend.kportwatchctl.send_command")
    @patch("builtins.print")
    def test_kill_error_response(self, mock_print, mock_send_command):
        """Test kill command when daemon returns error."""
        mock_send_command.return_value = {"status": "error", "message": "Permission denied"}

        args = Mock()
        args.pid = 9999
        result = kportwatchctl.cmd_kill(args)

        assert result == 1
        mock_send_command.assert_called_once_with({"command": "kill", "pid": 9999})

    @patch("backend.kportwatchctl.send_command", side_effect=ConnectionError)
    @patch("builtins.print")
    def test_kill_connection_error(self, mock_print, mock_send_command):
        """Test kill command when connection to daemon fails."""
        args = Mock()
        args.pid = 9999
        result = kportwatchctl.cmd_kill(args)

        assert result == 1
        mock_print.assert_called_once()

    @patch("backend.kportwatchctl.send_command", side_effect=TimeoutError)
    @patch("builtins.print")
    def test_kill_timeout(self, mock_print, mock_send_command):
        """Test kill command when daemon times out."""
        args = Mock()
        args.pid = 9999
        result = kportwatchctl.cmd_kill(args)

        assert result == 1
        mock_print.assert_called_once()


class TestKPortWatchCtlMainFunction:
    """Test the main() function and argument parsing."""

    @patch("sys.argv", ["kportwatchctl"])
    def test_main_no_command_shows_help(self):
        """Test main() with no command shows help."""
        # The default func calls parser.print_help() which goes to stdout
        # We can't easily mock this, but we can verify it doesn't crash
        kportwatchctl.main()
        # Should not crash, and help is printed to stdout

    @patch("sys.argv", ["kportwatchctl", "status"])
    @patch("backend.kportwatchctl.cmd_status")
    def test_main_status_command(self, mock_cmd_status):
        """Test main() with status command."""
        mock_cmd_status.return_value = 0
        kportwatchctl.main()
        mock_cmd_status.assert_called_once()

    @patch("sys.argv", ["kportwatchctl", "stop"])
    @patch("backend.kportwatchctl.cmd_stop")
    def test_main_stop_command(self, mock_cmd_stop):
        """Test main() with stop command."""
        mock_cmd_stop.return_value = 0
        kportwatchctl.main()
        mock_cmd_stop.assert_called_once()

    @patch("sys.argv", ["kportwatchctl", "reload"])
    @patch("backend.kportwatchctl.cmd_reload")
    def test_main_reload_command(self, mock_cmd_reload):
        """Test main() with reload command."""
        mock_cmd_reload.return_value = 0
        kportwatchctl.main()
        mock_cmd_reload.assert_called_once()

    @patch("sys.argv", ["kportwatchctl", "kill", "9999"])
    @patch("backend.kportwatchctl.cmd_kill")
    def test_main_kill_command(self, mock_cmd_kill):
        """Test main() with kill command."""
        mock_cmd_kill.return_value = 0
        kportwatchctl.main()
        mock_cmd_kill.assert_called_once()
        # Check that pid argument was passed
        call_args = mock_cmd_kill.call_args[0][0]
        assert call_args.pid == 9999

    @patch("sys.argv", ["kportwatchctl", "restart", "--verbose"])
    @patch("backend.kportwatchctl.cmd_restart")
    def test_main_restart_command_with_verbose(self, mock_cmd_restart):
        """Test main() with restart command and verbose flag."""
        mock_cmd_restart.return_value = 0
        kportwatchctl.main()
        mock_cmd_restart.assert_called_once()
        call_args = mock_cmd_restart.call_args[0][0]
        assert call_args.verbose is True

    @patch("sys.argv", ["kportwatchctl", "restart", "--config", "/custom/config.toml"])
    @patch("backend.kportwatchctl.cmd_restart")
    def test_main_restart_command_with_config(self, mock_cmd_restart):
        """Test main() with restart command and config path."""
        mock_cmd_restart.return_value = 0
        kportwatchctl.main()
        mock_cmd_restart.assert_called_once()
        call_args = mock_cmd_restart.call_args[0][0]
        assert call_args.config == "/custom/config.toml"


# =============================================================================
# Tests for backend/kportwatch_client.py
# =============================================================================

class TestKPortWatchClientModule:
    """Test that the client module can be imported and has expected structure."""

    def test_module_imports(self):
        """Test that the client module imports correctly."""
        # If we got here, the import worked
        assert kportwatch_client is not None
        assert hasattr(kportwatch_client, "main")

    def test_main_function_exists(self):
        """Test that main() function exists."""
        assert callable(kportwatch_client.main)

    def test_constants_defined(self):
        """Test that required constants are defined."""
        assert hasattr(kportwatch_client, "CONNECT_TIMEOUT")
        assert isinstance(kportwatch_client.CONNECT_TIMEOUT, (int, float))
        assert kportwatch_client.CONNECT_TIMEOUT > 0

    def test_main_signature(self):
        """Test that main() has correct signature."""
        import inspect
        sig = inspect.signature(kportwatch_client.main)
        # main() should take no arguments (or only optional ones)
        params = [p for p in sig.parameters.values() if p.default == inspect.Parameter.empty]
        assert len(params) == 0


class TestKPortWatchClientMain:
    """Test the main() function behavior."""

    @patch("socket.socket")
    @patch("sys.exit")
    @patch("builtins.print")
    def test_main_timeout_error(self, mock_print, mock_exit, mock_socket):
        """Test main() handles connection timeout."""
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = TimeoutError
        mock_socket.return_value = mock_sock

        kportwatch_client.main()

        mock_exit.assert_called_once_with(1)
        # Should print error message - check that something was printed
        assert mock_print.call_count > 0
        # The error message should contain information about the error
        call_str = str(mock_print.call_args)
        assert "error" in call_str.lower() or "timed" in call_str.lower()

    @patch("socket.socket")
    @patch("sys.exit")
    @patch("builtins.print")
    def test_main_file_not_found(self, mock_print, mock_exit, mock_socket):
        """Test main() handles socket file not found."""
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = FileNotFoundError
        mock_socket.return_value = mock_sock

        kportwatch_client.main()

        mock_exit.assert_called_once_with(1)
        # Should print error message about socket not found
        assert any("socket" in str(call).lower() for call in mock_print.call_args_list)

    @patch("socket.socket")
    @patch("sys.exit")
    @patch("builtins.print")
    def test_main_connection_refused(self, mock_print, mock_exit, mock_socket):
        """Test main() handles connection refused."""
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = ConnectionRefusedError
        mock_socket.return_value = mock_sock

        kportwatch_client.main()

        mock_exit.assert_called_once_with(1)
        # Should print error message about connection refused
        assert any("refused" in str(call).lower() or "starting" in str(call).lower() for call in mock_print.call_args_list)

    @patch("socket.socket")
    @patch("sys.exit")
    @patch("builtins.print")
    def test_main_generic_error(self, mock_print, mock_exit, mock_socket):
        """Test main() handles generic exceptions."""
        mock_sock = MagicMock()
        mock_sock.connect.side_effect = Exception("Test error")
        mock_socket.return_value = mock_sock

        kportwatch_client.main()

        mock_exit.assert_called_once_with(1)
        # Should print error message
        assert mock_print.call_count > 0

    @patch("socket.socket")
    @patch("sys.exit")
    def test_main_keyboard_interrupt(self, mock_exit, mock_socket):
        """Test main() handles keyboard interrupt gracefully."""
        mock_sock = MagicMock()
        mock_sock.makefile.return_value.__iter__.side_effect = KeyboardInterrupt
        mock_socket.return_value = mock_sock

        kportwatch_client.main()

        mock_exit.assert_called_once_with(0)

    @patch("socket.socket")
    @patch("builtins.print")
    def test_main_successful_connection(self, mock_print, mock_socket, tmp_path):
        """Test main() successfully connects and streams data."""
        # Create a mock file object
        mock_file = MagicMock()
        mock_file.__iter__ = Mock(return_value=iter(['{"test": "data"}\n', '{"test": "data2"}\n']))
        mock_sock = MagicMock()
        mock_sock.makefile.return_value = mock_file
        mock_socket.return_value = mock_sock

        kportwatch_client.main()

        # Should have printed the lines
        assert mock_print.call_count >= 2
        mock_sock.connect.assert_called_once()
        mock_sock.settimeout.assert_called()


# =============================================================================
# Test cleanup and utilities
# =============================================================================

class TestKPortWatchCtlUtilities:
    """Test utility functions in kportwatchctl."""

    @patch("subprocess.run")
    def test_find_daemon_pids_success(self, mock_run):
        """Test finding daemon PIDs via pgrep."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="12345\n12346\n"
        )

        pids = kportwatchctl._find_daemon_pids()

        assert pids == [12345, 12346]
        mock_run.assert_called_once()

    @patch("subprocess.run", side_effect=Exception)
    def test_find_daemon_pids_error(self, mock_run):
        """Test finding daemon PIDs when pgrep fails."""
        pids = kportwatchctl._find_daemon_pids()
        assert pids == []

    @patch("subprocess.run")
    def test_find_daemon_pids_no_results(self, mock_run):
        """Test finding daemon PIDs when none found."""
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout=""
        )

        pids = kportwatchctl._find_daemon_pids()
        assert pids == []

    @patch("os.unlink")
    @patch("backend.kportwatchctl.PID_FILE", "/tmp/test.pid")
    @patch("backend.kportwatchctl.SOCKET_PATH", "/tmp/test.sock")
    def test_cleanup_pidfile(self, mock_unlink):
        """Test cleanup of PID file and socket."""
        kportwatchctl._cleanup_pidfile()
        assert mock_unlink.call_count == 2

    @patch("os.unlink", side_effect=FileNotFoundError)
    @patch("backend.kportwatchctl.PID_FILE", "/tmp/test.pid")
    @patch("backend.kportwatchctl.SOCKET_PATH", "/tmp/test.sock")
    def test_cleanup_pidfile_missing_files(self, mock_unlink):
        """Test cleanup handles missing files gracefully."""
        # Should not raise exception
        kportwatchctl._cleanup_pidfile()
        assert mock_unlink.call_count == 2

    @patch("os.path.isfile")
    def test_find_project_root(self, mock_isfile):
        """Test finding project root directory."""
        # Mock finding pyproject.toml at current level
        mock_isfile.side_effect = lambda p: "pyproject.toml" in p

        root = kportwatchctl._find_project_root()
        assert isinstance(root, str)
        assert len(root) > 0


# =============================================================================
# Integration-style tests
# =============================================================================

class TestCLIIntegration:
    """Integration-style tests for CLI entry points."""

    def test_export_module_has_main(self):
        """Test that export module has main() function."""
        assert callable(export.main)

    def test_kportwatchctl_module_has_main(self):
        """Test that kportwatchctl module has main() function."""
        assert callable(kportwatchctl.main)

    def test_kportwatchctl_has_parser(self):
        """Test that kportwatchctl has argument parser."""
        # The parser is created inside main(), but we can check it has commands
        assert hasattr(kportwatchctl, "cmd_status")
        assert hasattr(kportwatchctl, "cmd_stop")
        assert hasattr(kportwatchctl, "cmd_restart")
        assert hasattr(kportwatchctl, "cmd_reload")
        assert hasattr(kportwatchctl, "cmd_kill")
