"""Tests for backend/update.py — version checking, state file, update logic."""
from __future__ import annotations

import json
import time
from unittest.mock import MagicMock, patch

from backend.update import (
    check_for_update,
    get_latest_version,
    get_local_version,
    parse_version,
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
