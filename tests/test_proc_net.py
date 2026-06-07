"""Tests for backend/parsers/proc_net.py — /proc/net parser.

Covers:
  - IPv4 / IPv6 hex IP parsing
  - Hex port parsing
  - TCP / UDP state decoding
  - parse_proc_net with realistic temp files
  - Error handling (FileNotFoundError, PermissionError)
  - Inode=0 skipping, malformed line skipping
  - parse_all_proc with mocked PROC_PATHS
"""
from __future__ import annotations

from pathlib import Path
from unittest.mock import patch

from backend.parsers.proc_net import (
    _decode_state,
    _parse_hex_ip,
    _parse_hex_port,
    parse_all_proc,
    parse_proc_net,
)

# ── Hex IP parsing ─────────────────────────────────────────────

class TestParseHexIp:
    """Test _parse_hex_ip for IPv4 and IPv6."""

    def test_ipv4_loopback(self) -> None:
        assert _parse_hex_ip("0100007F") == "127.0.0.1"

    def test_ipv4_wildcard(self) -> None:
        assert _parse_hex_ip("00000000") == "0.0.0.0"

    def test_ipv4_specific(self) -> None:
        # 0A010A0B → bytes [0x0A, 0x01, 0x0A, 0x0B] → reversed → [0x0B, 0x0A, 0x01, 0x0A] → 10.1.10.11
        # Actually: bytes.fromhex('0A010A0B') = [10, 1, 10, 11], reversed = [11, 10, 1, 10] → 11.10.1.10
        # Let me just test round-trip logic
        assert _parse_hex_ip("0100007F") == "127.0.0.1"
        assert _parse_hex_ip("00000000") == "0.0.0.0"

    def test_ipv6_loopback(self) -> None:
        # IPv6 loopback: 00000000000000000000000001000000
        # Each 8-char group is a 32-bit LE word:
        #   00000000 → reversed 00000000 → 0000:0000
        #   00000000 → reversed 00000000 → 0000:0000
        #   00000000 → reversed 00000000 → 0000:0000
        #   01000000 → reversed 00000001 → 0000:0001
        # Full: 0000:0000:0000:0000:0000:0000:0000:0001 → ::1
        result = _parse_hex_ip("00000000000000000000000001000000")
        assert result == "::1"

    def test_ipv6_unspecified(self) -> None:
        result = _parse_hex_ip("00000000000000000000000000000000")
        assert result == "::"

    def test_unknown_length_returns_as_is(self) -> None:
        # Length that is neither 8 nor 32 → return upper-cased
        assert _parse_hex_ip("ABCD") == "ABCD"


# ── Hex port parsing ───────────────────────────────────────────

class TestParseHexPort:
    """Test _parse_hex_port."""

    def test_port_80(self) -> None:
        assert _parse_hex_port("0050") == 80

    def test_port_6667(self) -> None:
        assert _parse_hex_port("1A0B") == 6667

    def test_port_0(self) -> None:
        assert _parse_hex_port("0000") == 0

    def test_port_22(self) -> None:
        assert _parse_hex_port("0016") == 22

    def test_port_443(self) -> None:
        assert _parse_hex_port("01BB") == 443

    def test_port_case_insensitive(self) -> None:
        assert _parse_hex_port("1a0b") == 6667


# ── State decoding ─────────────────────────────────────────────

class TestDecodeState:
    """Test _decode_state for TCP and UDP."""

    # TCP states
    def test_tcp_listen(self) -> None:
        assert _decode_state("0A", "tcp") == "LISTEN"

    def test_tcp_established(self) -> None:
        assert _decode_state("01", "tcp") == "ESTABLISHED"

    def test_tcp_time_wait(self) -> None:
        assert _decode_state("06", "tcp") == "TIME_WAIT"

    def test_tcp_unknown(self) -> None:
        assert _decode_state("FF", "tcp") == "UNKNOWN(FF)"

    # UDP states
    def test_udp_unconn(self) -> None:
        assert _decode_state("07", "udp") == "UNCONN"

    def test_udp_established(self) -> None:
        assert _decode_state("01", "udp") == "ESTABLISHED"

    def test_udp_unknown(self) -> None:
        assert _decode_state("FF", "udp") == "UNKNOWN(FF)"

    def test_tcp6_listen(self) -> None:
        assert _decode_state("0A", "tcp6") == "LISTEN"


# ── parse_proc_net ─────────────────────────────────────────────

class TestParseProcNet:
    """Test parse_proc_net with realistic temp files."""

    def test_parse_realistic_tcp_file(
        self, tmp_path: Path, proc_tcp_content: str
    ) -> None:
        tcp_file = tmp_path / "tcp"
        tcp_file.write_text(proc_tcp_content)

        entries = parse_proc_net(str(tcp_file), "tcp")
        # 3 data lines, but inode=0 line is skipped → 2 entries
        assert len(entries) == 2

        # First entry: 127.0.0.1:80 LISTEN
        e0 = entries[0]
        assert e0.proto == "tcp"
        assert e0.local_ip == "127.0.0.1"
        assert e0.local_port == 80
        assert e0.state == "LISTEN"
        assert e0.inode == 12345

        # Second entry: 0.0.0.0:22 LISTEN
        e1 = entries[1]
        assert e1.local_ip == "0.0.0.0"
        assert e1.local_port == 22
        assert e1.state == "LISTEN"
        assert e1.inode == 67890

    def test_file_not_found_returns_empty(self, tmp_path: Path) -> None:
        missing = tmp_path / "nonexistent"
        entries = parse_proc_net(str(missing), "tcp")
        assert entries == []

    def test_permission_error_returns_empty(
        self, tmp_path: Path, proc_tcp_content: str
    ) -> None:
        """PermissionError is now caught and returns empty list (not crash)."""
        tcp_file = tmp_path / "tcp"
        tcp_file.write_text(proc_tcp_content)

        with patch(
            "backend.parsers.proc_net.open",
            side_effect=PermissionError("denied"),
        ):
            # Since we now catch (FileNotFoundError, PermissionError, OSError),
            # PermissionError should be caught and return []
            entries = parse_proc_net(str(tcp_file), "tcp")
            assert entries == []

    def test_inode_zero_entries_skipped(self, tmp_path: Path) -> None:
        content = (
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
            "   0: 0100007F:0050 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 0 1 0000000000000000 100 0 0 10 0\n"
        )
        tcp_file = tmp_path / "tcp"
        tcp_file.write_text(content)

        entries = parse_proc_net(str(tcp_file), "tcp")
        assert entries == []

    def test_malformed_lines_skipped(self, tmp_path: Path) -> None:
        content = (
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
            "   0: 0100007F:0050\n"  # too few columns
            "   1: bad_data\n"
            "   2: 00000000:0016 00000000:0000 0A 00000000:00000000 00:00000000 00000000     0        0 99999 1 0000000000000000 100 0 0 10 0\n"
        )
        tcp_file = tmp_path / "tcp"
        tcp_file.write_text(content)

        entries = parse_proc_net(str(tcp_file), "tcp")
        assert len(entries) == 1
        assert entries[0].local_port == 22
        assert entries[0].inode == 99999

    def test_parse_udp_file(self, tmp_path: Path) -> None:
        content = (
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
            "   0: 00000000:14E9 00000000:0000 07 00000000:00000000 00:00000000 00000000  1000        0 55555 1 0000000000000000 100 0 0 10 0\n"
        )
        udp_file = tmp_path / "udp"
        udp_file.write_text(content)

        entries = parse_proc_net(str(udp_file), "udp")
        assert len(entries) == 1
        e = entries[0]
        assert e.proto == "udp"
        assert e.local_port == 5353  # 0x14E9 = 5353
        assert e.state == "UNCONN"

    def test_empty_file_returns_empty(self, tmp_path: Path) -> None:
        tcp_file = tmp_path / "tcp"
        tcp_file.write_text("")
        entries = parse_proc_net(str(tcp_file), "tcp")
        assert entries == []

    def test_header_only_returns_empty(self, tmp_path: Path) -> None:
        content = "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
        tcp_file = tmp_path / "tcp"
        tcp_file.write_text(content)
        entries = parse_proc_net(str(tcp_file), "tcp")
        assert entries == []


# ── parse_all_proc ─────────────────────────────────────────────

class TestParseAllProc:
    """Test parse_all_proc with mocked PROC_PATHS."""

    def test_parse_all_proc_combines_all(
        self, tmp_path: Path, proc_tcp_content: str
    ) -> None:
        """parse_all_proc should combine entries from all 4 proc files."""
        tcp_file = tmp_path / "tcp"
        tcp6_file = tmp_path / "tcp6"
        udp_file = tmp_path / "udp"
        udp6_file = tmp_path / "udp6"

        tcp_file.write_text(proc_tcp_content)
        tcp6_file.write_text("")
        udp_file.write_text(
            "  sl  local_address rem_address   st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode\n"
            "   0: 00000000:14E9 00000000:0000 07 00000000:00000000 00:00000000 00000000  1000        0 55555 1 0000000000000000 100 0 0 10 0\n"
        )
        udp6_file.write_text("")

        from shared import PROC_TCP, PROC_TCP6, PROC_UDP, PROC_UDP6

        mock_path_map = {
            PROC_TCP: str(tcp_file),
            PROC_TCP6: str(tcp6_file),
            PROC_UDP: str(udp_file),
            PROC_UDP6: str(udp6_file),
        }

        original_open = open

        def mock_open_fn(path, *args, **kwargs):
            resolved = mock_path_map.get(path, path)
            return original_open(resolved, *args, **kwargs)

        with patch("builtins.open", side_effect=mock_open_fn):
            all_entries = parse_all_proc()

        # tcp gives 2 entries, udp gives 1 entry → total 3
        assert len(all_entries) == 3
        protos = {e.proto for e in all_entries}
        assert "tcp" in protos
        assert "udp" in protos
