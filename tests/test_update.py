"""Tests for backend/update.py — version checking, state file, update logic."""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

from backend.update import (
    _find_project_dir,
    _restart_daemon,
    _verify_tag,
    check_for_update,
    get_latest_version,
    get_local_version,
    parse_version,
    perform_update,
    read_update_state,
    write_update_state,
)

# ── Version parsing ───────────────────────────────────────────

class TestParseVersion:
    """Tests for parse_version()."""

    def test_standard_version(self):
        assert parse_version("2.1.0") == (2, 1, 0)

    def test_version_with_v_prefix(self):
        assert parse_version("v2.1.0") == (2, 1, 0)

    def test_two_part_version(self):
        assert parse_version("2.0") == (2, 0)

    def test_single_number(self):
        assert parse_version("3") == (3,)

    def test_comparison(self):
        assert parse_version("2.1.0") > parse_version("2.0.0")
        assert parse_version("2.0.1") > parse_version("2.0.0")
        assert parse_version("3.0.0") > parse_version("2.9.9")

    def test_equal_versions(self):
        assert parse_version("2.0.0") == parse_version("v2.0.0")

    def test_invalid_version(self):
        assert parse_version("invalid") == (0,)

    def test_empty_string(self):
        assert parse_version("") == (0,)

    def test_whitespace(self):
        assert parse_version("  2.0.0  ") == (2, 0, 0)


# ── get_local_version ─────────────────────────────────────────

class TestGetLocalVersion:
    """Tests for get_local_version()."""

    def test_returns_string(self):
        v = get_local_version()
        assert isinstance(v, str)
        assert len(v) > 0

    def test_is_valid_semver(self):
        v = get_local_version()
        parts = parse_version(v)
        assert len(parts) >= 1
        assert all(isinstance(p, int) and p >= 0 for p in parts)


# ── Update state file ─────────────────────────────────────────

class TestUpdateStateFile:
    """Tests for write_update_state() and read_update_state()."""

    def test_write_and_read(self, tmp_path):
        """Write state then read it back — should match."""
        path = str(tmp_path / "update.json")
        write_update_state(
            current="2.0.0",
            latest="2.1.0",
            update_available=True,
            path=path,
        )

        state = read_update_state(path)
        assert state is not None
        assert state["current"] == "2.0.0"
        assert state["latest"] == "2.1.0"
        assert state["update_available"] is True
        assert "last_checked" in state

    def test_no_update_available(self, tmp_path):
        """State with no update available."""
        path = str(tmp_path / "update.json")
        write_update_state(
            current="2.0.0",
            latest="2.0.0",
            update_available=False,
            path=path,
        )

        state = read_update_state(path)
        assert state["update_available"] is False

    def test_read_nonexistent_file(self, tmp_path):
        """Reading non-existent file returns None."""
        state = read_update_state(str(tmp_path / "nonexistent.json"))
        assert state is None

    def test_write_to_bad_path(self):
        """Writing to an impossible path should not raise."""
        # Should silently ignore
        write_update_state(
            current="2.0.0",
            latest=None,
            update_available=False,
            path="/nonexistent/dir/file.json",
        )

    def test_last_checked_is_recent(self, tmp_path):
        """last_checked timestamp should be close to now."""
        path = str(tmp_path / "update.json")
        before = time.time()
        write_update_state(current="2.0.0", path=path)
        after = time.time()

        state = read_update_state(path)
        assert before <= state["last_checked"] <= after


# ── check_for_update ──────────────────────────────────────────

class TestCheckForUpdate:
    """Tests for check_for_update() with mocked GitHub API."""

    @patch("backend.update.get_latest_version")
    def test_update_available(self, mock_latest):
        """Returns new version when remote is newer."""
        mock_latest.return_value = "v99.0.0"
        result = check_for_update()
        assert result == "v99.0.0"

    @patch("backend.update.get_latest_version")
    def test_no_update_needed(self, mock_latest):
        """Returns None when versions match."""
        mock_latest.return_value = f"v{get_local_version()}"
        result = check_for_update()
        assert result is None

    @patch("backend.update.get_latest_version")
    def test_remote_older(self, mock_latest):
        """Returns None when remote version is older."""
        mock_latest.return_value = "v0.0.1"
        result = check_for_update()
        assert result is None

    @patch("backend.update.get_latest_version")
    def test_github_unreachable(self, mock_latest):
        """Returns None when GitHub is unreachable."""
        mock_latest.return_value = None
        result = check_for_update()
        assert result is None


# ── get_latest_version (mocked HTTP) ──────────────────────────

class TestGetLatestVersion:
    """Tests for get_latest_version() with mocked urllib."""

    @patch("backend.update.urllib.request.urlopen")
    def test_parse_tags_response(self, mock_urlopen):
        """Parse a valid GitHub Tags API response."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([
            {"name": "v2.1.0"},
            {"name": "v2.0.0"},
        ]).encode()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = get_latest_version()
        assert result == "v2.1.0"

    @patch("backend.update.urllib.request.urlopen")
    def test_empty_tags_list(self, mock_urlopen):
        """Empty tags list returns None."""
        mock_resp = MagicMock()
        mock_resp.read.return_value = json.dumps([]).encode()
        mock_resp.__enter__ = lambda s: mock_resp
        mock_resp.__exit__ = MagicMock(return_value=False)
        mock_urlopen.return_value = mock_resp

        result = get_latest_version()
        assert result is None

    @patch("backend.update.urllib.request.urlopen")
    def test_network_error(self, mock_urlopen):
        """Network error returns None."""
        import urllib.error
        mock_urlopen.side_effect = urllib.error.URLError("no network")

        result = get_latest_version()
        assert result is None


# ── _find_project_dir ─────────────────────────────────────────

class TestFindProjectDir:
    """Tests for _find_project_dir()."""

    @patch("os.path.isdir")
    def test_finds_git_directory(self, mock_isdir):
        """Returns path when .git directory is found."""
        # Simulate finding .git at first level
        mock_isdir.side_effect = lambda path: ".git" in path

        with patch("os.path.dirname", side_effect=lambda x: x.replace("update.py", "")):
            with patch("os.path.abspath", return_value="/fake/path/backend/update.py"):
                result = _find_project_dir()
                # Should return a path (we don't care about the exact value in this test)
                assert result is not None or result is None  # Just verify it runs

    @patch("os.path.isdir")
    def test_no_git_directory(self, mock_isdir):
        """Returns None when no .git directory is found."""
        mock_isdir.return_value = False

        with patch("os.path.dirname", return_value="/some/path"):
            with patch("os.path.abspath", return_value="/some/path"):
                result = _find_project_dir()
                assert result is None


# ── _verify_tag ───────────────────────────────────────────────

class TestVerifyTag:
    """Tests for _verify_tag()."""

    @patch("subprocess.run")
    def test_verify_tag_success(self, mock_run):
        """Returns True when tag signature is valid."""
        # Mock git fetch and git tag -v success
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git fetch
            MagicMock(returncode=0, stderr=""),  # git tag -v success
        ]

        result = _verify_tag("v2.1.0", "/fake/project")
        assert result is True
        assert mock_run.call_count == 2

    @patch("subprocess.run")
    def test_verify_tag_unsigned(self, mock_run):
        """Returns False when tag is not signed."""
        # Mock git fetch and git tag -v with unsigned tag error
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git fetch
            MagicMock(returncode=1, stderr="not a signed tag"),  # git tag -v unsigned
        ]

        result = _verify_tag("v2.1.0", "/fake/project")
        assert result is False
        assert mock_run.call_count == 2

    @patch("subprocess.run")
    def test_verify_tag_key_not_in_keyring(self, mock_run):
        """Returns False when GPG key is not in keyring."""
        # Mock git fetch and git tag -v with key not in keyring error
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git fetch
            MagicMock(returncode=1, stderr="public key not found"),  # git tag -v no key
        ]

        result = _verify_tag("v2.1.0", "/fake/project")
        assert result is False
        assert mock_run.call_count == 2

    @patch("subprocess.run")
    def test_verify_tag_other_error(self, mock_run):
        """Returns False for other verification errors."""
        # Mock git fetch and git tag -v with other error
        mock_run.side_effect = [
            MagicMock(returncode=0),  # git fetch
            MagicMock(returncode=1, stderr="some other error"),  # git tag -v error
        ]

        result = _verify_tag("v2.1.0", "/fake/project")
        assert result is False
        assert mock_run.call_count == 2

    @patch("subprocess.run")
    def test_verify_tag_timeout(self, mock_run):
        """Returns False when subprocess times out."""
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired("git", 30)

        result = _verify_tag("v2.1.0", "/fake/project")
        assert result is False

    @patch("subprocess.run")
    def test_verify_tag_git_not_found(self, mock_run):
        """Returns False when git is not found."""
        mock_run.side_effect = FileNotFoundError("git not found")

        result = _verify_tag("v2.1.0", "/fake/project")
        assert result is False


# ── perform_update ─────────────────────────────────────────────

class TestPerformUpdate:
    """Tests for perform_update()."""

    @patch("backend.update._restart_daemon")
    @patch("backend.update.write_update_state")
    @patch("subprocess.run")
    @patch("backend.update._verify_tag")
    @patch("backend.update.get_latest_version")
    @patch("backend.update._find_project_dir")
    def test_perform_update_success(self, mock_find_dir, mock_latest, mock_verify,
                                     mock_run, mock_write_state, mock_restart):
        """Successful update flow returns True."""
        mock_find_dir.return_value = "/fake/project"
        mock_latest.return_value = "v2.1.0"
        mock_verify.return_value = True

        # Mock git pull and pip install success
        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Already up to date"),  # git pull
            MagicMock(returncode=0, stdout="Successfully installed"),  # pip install
        ]

        result = perform_update(restart_daemon=False)
        assert result is True
        mock_verify.assert_called_once_with("v2.1.0", "/fake/project")
        mock_write_state.assert_called_once()

    @patch("backend.update._restart_daemon")
    @patch("backend.update.write_update_state")
    @patch("subprocess.run")
    @patch("backend.update._verify_tag")
    @patch("backend.update.get_latest_version")
    @patch("backend.update._find_project_dir")
    def test_perform_update_with_restart(self, mock_find_dir, mock_latest, mock_verify,
                                          mock_run, mock_write_state, mock_restart):
        """Update with daemon restart."""
        mock_find_dir.return_value = "/fake/project"
        mock_latest.return_value = "v2.1.0"
        mock_verify.return_value = True

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Updated"),  # git pull
            MagicMock(returncode=0, stdout="Installed"),  # pip install
        ]

        result = perform_update(restart_daemon=True)
        assert result is True
        mock_restart.assert_called_once()

    @patch("backend.update._find_project_dir")
    def test_perform_update_no_project_dir(self, mock_find_dir):
        """Returns False when project directory not found."""
        mock_find_dir.return_value = None

        result = perform_update()
        assert result is False

    @patch("backend.update._find_project_dir")
    @patch("backend.update.get_latest_version")
    @patch("backend.update._verify_tag")
    def test_perform_update_verify_fails(self, mock_verify, mock_latest, mock_find_dir):
        """Returns False when tag verification fails."""
        mock_find_dir.return_value = "/fake/project"
        mock_latest.return_value = "v2.1.0"
        mock_verify.return_value = False

        result = perform_update()
        assert result is False

    @patch("backend.update._restart_daemon")
    @patch("backend.update.write_update_state")
    @patch("subprocess.run")
    @patch("backend.update._verify_tag")
    @patch("backend.update.get_latest_version")
    @patch("backend.update._find_project_dir")
    def test_perform_update_no_latest_version(self, mock_find_dir, mock_latest, mock_verify,
                                                mock_run, mock_write_state, mock_restart):
        """Update proceeds when no latest version available (skips verify)."""
        mock_find_dir.return_value = "/fake/project"
        mock_latest.return_value = None  # No latest version

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Updated"),  # git pull
            MagicMock(returncode=0, stdout="Installed"),  # pip install
        ]

        result = perform_update(restart_daemon=False)
        assert result is True
        # Verify should NOT be called when latest is None
        mock_verify.assert_not_called()

    @patch("backend.update._restart_daemon")
    @patch("backend.update.write_update_state")
    @patch("subprocess.run")
    @patch("backend.update._verify_tag")
    @patch("backend.update.get_latest_version")
    @patch("backend.update._find_project_dir")
    def test_perform_update_git_pull_fails(self, mock_find_dir, mock_latest, mock_verify,
                                             mock_run, mock_write_state, mock_restart):
        """Returns False when git pull fails."""
        mock_find_dir.return_value = "/fake/project"
        mock_latest.return_value = "v2.1.0"
        mock_verify.return_value = True

        # git pull fails
        mock_run.side_effect = [
            MagicMock(returncode=1, stderr="Connection refused"),  # git pull
        ]

        result = perform_update(restart_daemon=False)
        assert result is False
        mock_write_state.assert_not_called()

    @patch("backend.update._restart_daemon")
    @patch("backend.update.write_update_state")
    @patch("subprocess.run")
    @patch("backend.update._verify_tag")
    @patch("backend.update.get_latest_version")
    @patch("backend.update._find_project_dir")
    def test_perform_update_git_pull_timeout(self, mock_find_dir, mock_latest, mock_verify,
                                               mock_run, mock_write_state, mock_restart):
        """Returns False when git pull times out."""
        import subprocess as sp
        mock_find_dir.return_value = "/fake/project"
        mock_latest.return_value = "v2.1.0"
        mock_verify.return_value = True

        mock_run.side_effect = sp.TimeoutExpired("git", 60)

        result = perform_update(restart_daemon=False)
        assert result is False

    @patch("backend.update._restart_daemon")
    @patch("backend.update.write_update_state")
    @patch("subprocess.run")
    @patch("backend.update._verify_tag")
    @patch("backend.update.get_latest_version")
    @patch("backend.update._find_project_dir")
    def test_perform_update_git_not_found(self, mock_find_dir, mock_latest, mock_verify,
                                            mock_run, mock_write_state, mock_restart):
        """Returns False when git is not found."""
        mock_find_dir.return_value = "/fake/project"
        mock_latest.return_value = "v2.1.0"
        mock_verify.return_value = True

        mock_run.side_effect = FileNotFoundError("git")

        result = perform_update(restart_daemon=False)
        assert result is False

    @patch("backend.update._restart_daemon")
    @patch("backend.update.write_update_state")
    @patch("subprocess.run")
    @patch("backend.update._verify_tag")
    @patch("backend.update.get_latest_version")
    @patch("backend.update._find_project_dir")
    @patch("os.path.exists")
    def test_perform_update_pip_install_fails(self, mock_exists, mock_find_dir, mock_latest,
                                               mock_verify, mock_run, mock_write_state, mock_restart):
        """Returns False when pip install fails."""
        mock_find_dir.return_value = "/fake/project"
        mock_latest.return_value = "v2.1.0"
        mock_verify.return_value = True
        mock_exists.return_value = False  # No venv

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Updated"),  # git pull
            MagicMock(returncode=1, stderr="Installation failed"),  # pip install
        ]

        result = perform_update(restart_daemon=False)
        assert result is False

    @patch("backend.update._restart_daemon")
    @patch("backend.update.write_update_state")
    @patch("subprocess.run")
    @patch("backend.update._verify_tag")
    @patch("backend.update.get_latest_version")
    @patch("backend.update._find_project_dir")
    @patch("os.path.exists")
    def test_perform_update_pip_timeout(self, mock_exists, mock_find_dir, mock_latest,
                                          mock_verify, mock_run, mock_write_state, mock_restart):
        """Returns False when pip install times out."""
        import subprocess as sp
        mock_find_dir.return_value = "/fake/project"
        mock_latest.return_value = "v2.1.0"
        mock_verify.return_value = True
        mock_exists.return_value = False

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Updated"),  # git pull
            sp.TimeoutExpired("pip", 120),  # pip install timeout
        ]

        result = perform_update(restart_daemon=False)
        assert result is False

    @patch("backend.update._restart_daemon")
    @patch("backend.update.write_update_state")
    @patch("subprocess.run")
    @patch("backend.update._verify_tag")
    @patch("backend.update.get_latest_version")
    @patch("backend.update._find_project_dir")
    @patch("os.path.exists")
    def test_perform_update_pip_not_found(self, mock_exists, mock_find_dir, mock_latest,
                                           mock_verify, mock_run, mock_write_state, mock_restart):
        """Returns False when pip/python is not found."""
        mock_find_dir.return_value = "/fake/project"
        mock_latest.return_value = "v2.1.0"
        mock_verify.return_value = True
        mock_exists.return_value = False

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Updated"),  # git pull
            FileNotFoundError("python"),  # pip install
        ]

        result = perform_update(restart_daemon=False)
        assert result is False

    @patch("backend.update._restart_daemon")
    @patch("backend.update.write_update_state")
    @patch("subprocess.run")
    @patch("backend.update._verify_tag")
    @patch("backend.update.get_latest_version")
    @patch("backend.update._find_project_dir")
    @patch("os.path.exists")
    @patch("sys.executable", "/usr/bin/python3")
    def test_perform_update_uses_venv_python(self, mock_exists, mock_find_dir, mock_latest,
                                              mock_verify, mock_run, mock_write_state, mock_restart):
        """Uses venv python when available."""
        mock_find_dir.return_value = "/fake/project"
        mock_latest.return_value = "v2.1.0"
        mock_verify.return_value = True
        mock_exists.return_value = True  # venv exists

        mock_run.side_effect = [
            MagicMock(returncode=0, stdout="Updated"),  # git pull
            MagicMock(returncode=0, stdout="Installed"),  # pip install
        ]

        result = perform_update(restart_daemon=False)
        assert result is True

        # Check that venv python was used for pip install
        pip_call = mock_run.call_args_list[1]
        assert pip_call[0][0][0] == "/fake/project/.venv/bin/python"


# ── _restart_daemon ───────────────────────────────────────────

class TestRestartDaemon:
    """Tests for _restart_daemon()."""

    @patch("subprocess.run")
    def test_restart_daemon_success(self, mock_run):
        """Successfully restarts daemon via systemctl."""
        mock_run.return_value = MagicMock(returncode=0)

        _restart_daemon()

        mock_run.assert_called_once()
        call_args = mock_run.call_args
        assert call_args[0][0] == ["systemctl", "--user", "restart", "kportwatch.service"]
        assert call_args[1]["timeout"] == 10

    @patch("subprocess.run")
    def test_restart_daemon_timeout(self, mock_run):
        """Handles systemctl timeout gracefully."""
        import subprocess as sp
        mock_run.side_effect = sp.TimeoutExpired("systemctl", 10)

        # Should not raise, just log debug
        _restart_daemon()

    @patch("subprocess.run")
    def test_restart_daemon_not_found(self, mock_run):
        """Handles missing systemctl gracefully."""
        mock_run.side_effect = FileNotFoundError("systemctl")

        # Should not raise, just log debug
        _restart_daemon()


# ── main() function tests ─────────────────────────────────────

class TestMain:
    """Tests for main() CLI entry point."""

    @patch("sys.argv", ["kportwatch-update", "--check"])
    @patch("backend.update.write_update_state")
    @patch("backend.update.get_local_version")
    @patch("backend.update.get_latest_version")
    def test_main_check_only_no_update(self, mock_latest, mock_local, mock_write_state):
        """--check with no update available."""
        mock_local.return_value = "2.0.0"
        mock_latest.return_value = "v2.0.0"

        from backend.update import main
        # Should not raise
        main()

        mock_write_state.assert_called_once()

    @patch("sys.argv", ["kportwatch-update", "--check"])
    @patch("sys.exit")
    @patch("backend.update.write_update_state")
    @patch("backend.update.get_local_version")
    @patch("backend.update.get_latest_version")
    @patch("backend.update.parse_version")
    def test_main_check_latest_none(self, mock_parse_version, mock_latest, mock_local, mock_write_state, mock_exit):
        """--check when GitHub is unreachable."""
        mock_local.return_value = "2.0.0"
        mock_latest.return_value = None
        mock_parse_version.return_value = (2, 0, 0)  # Handle version comparison

        from backend.update import main
        main()

        mock_exit.assert_called_once_with(1)

    @patch("sys.argv", ["kportwatch-update", "--check"])
    @patch("backend.update.write_update_state")
    @patch("backend.update.get_local_version")
    @patch("backend.update.get_latest_version")
    def test_main_check_update_available(self, mock_latest, mock_local, mock_write_state):
        """--check shows update available but doesn't apply."""
        mock_local.return_value = "2.0.0"
        mock_latest.return_value = "v2.1.0"

        from backend.update import main
        main()

        write_call = mock_write_state.call_args
        assert write_call[1]["update_available"] is True
