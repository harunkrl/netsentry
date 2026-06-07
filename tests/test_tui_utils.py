"""KPortWatch — TUI unit tests for formatting helpers and utilities."""
from __future__ import annotations

from tui.themes import THEME_DISPLAY_NAMES
from tui.widgets.traffic_bar import _human_bytes


class TestFormatBytes:
    """Tests for _human_bytes helper (traffic_bar.py)."""

    def test_zero(self) -> None:
        result = _human_bytes(0)
        assert isinstance(result, str)

    def test_bytes(self) -> None:
        assert _human_bytes(512) == "512 B"

    def test_kibibytes(self) -> None:
        result = _human_bytes(1536)
        assert "KiB" in result

    def test_mebibytes(self) -> None:
        result = _human_bytes(5 * 1024 * 1024)
        assert "MiB" in result


class TestThemes:
    """Tests for theme module."""

    def test_themes_available(self) -> None:
        assert len(THEME_DISPLAY_NAMES) >= 1

    def test_theme_names_are_strings(self) -> None:
        for name in THEME_DISPLAY_NAMES:
            assert isinstance(name, str)
            assert len(name) > 0


class TestNetworkUtil:
    """Tests for shared.network.is_private_ip."""

    def test_loopback_v4(self) -> None:
        from shared.network import is_private_ip
        assert is_private_ip("127.0.0.1") is True

    def test_loopback_v6(self) -> None:
        from shared.network import is_private_ip
        assert is_private_ip("::1") is True

    def test_private_10(self) -> None:
        from shared.network import is_private_ip
        assert is_private_ip("10.0.0.1") is True

    def test_private_172(self) -> None:
        from shared.network import is_private_ip
        assert is_private_ip("172.16.0.1") is True

    def test_private_192(self) -> None:
        from shared.network import is_private_ip
        assert is_private_ip("192.168.1.1") is True

    def test_public(self) -> None:
        from shared.network import is_private_ip
        assert is_private_ip("8.8.8.8") is False

    def test_invalid_ip(self) -> None:
        from shared.network import is_private_ip
        assert is_private_ip("not-an-ip") is True


class TestFsUtils:
    """Tests for shared.fs_utils."""

    def test_read_file_safe_nonexistent(self, tmp_path) -> None:
        from shared.fs_utils import read_file_safe
        assert read_file_safe(str(tmp_path / "nonexistent")) is None

    def test_read_file_safe_existing(self, tmp_path) -> None:
        from shared.fs_utils import read_file_safe
        f = tmp_path / "test.txt"
        f.write_text("  hello world  \n")
        assert read_file_safe(str(f)) == "hello world"

    def test_atomic_write(self, tmp_path) -> None:
        from shared.fs_utils import atomic_write
        target = tmp_path / "output.txt"
        atomic_write(str(target), "test content")
        assert target.read_text() == "test content"

    def test_atomic_write_creates_dirs(self, tmp_path) -> None:
        from shared.fs_utils import atomic_write
        target = tmp_path / "sub" / "dir" / "output.txt"
        atomic_write(str(target), "nested")
        assert target.read_text() == "nested"


class TestClipboardUtil:
    """Tests for tui.utils.clipboard module imports."""

    def test_import(self) -> None:
        from tui.utils.clipboard import safe_copy_to_clipboard
        assert callable(safe_copy_to_clipboard)
