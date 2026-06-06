"""Tests for tui.widgets — Widget unit tests (D10).

Covers port table, connection log, status bar, traffic bar, and
their key behaviours: filtering, sorting, memory limits, sparklines,
and display formatting.
"""
from __future__ import annotations

import pytest
from backend.models import Alert, InterfaceStats, SocketEntry
from shared import AlertLevel
from tui.themes import (
    ALERT_COLOURS,
    DEFAULT_THEME,
    KPW_THEMES,
    STATE_COLOURS,
    THEME_DISPLAY_NAMES,
    alert_colour,
    display_name_to_key,
    get_theme_names,
    key_to_display_name,
    state_colour,
)
from tui.widgets.connection_log import ConnectionLog
from tui.widgets.port_table import (
    PortTable,
    _shorten_ipv6,
    _smart_truncate_addr,
)
from tui.widgets.status_bar import StatusBar
from tui.widgets.traffic_bar import (
    TrafficBar,
    _human_bytes,
    _mini_sparkline,
)

# ── Fixtures ──────────────────────────────────────────────────

@pytest.fixture
def entry_tcp_listen() -> SocketEntry:
    return SocketEntry(
        proto="tcp", local_ip="0.0.0.0", local_port=22,
        remote_ip="0.0.0.0", remote_port=0, state="LISTEN",
        state_code="0A", uid=0, inode=100,
        process_name="sshd", pid=1,
    )


@pytest.fixture
def entry_tcp_established() -> SocketEntry:
    return SocketEntry(
        proto="tcp", local_ip="192.168.1.10", local_port=443,
        remote_ip="10.0.0.1", remote_port=54321, state="ESTABLISHED",
        state_code="01", uid=1000, inode=200,
        process_name="firefox", pid=42,
        cmdline="/usr/bin/firefox --new-window",
    )


@pytest.fixture
def entry_ipv6() -> SocketEntry:
    return SocketEntry(
        proto="tcp6", local_ip="0000:0000:0000:0000:0000:0000:0000:0001",
        local_port=8080, remote_ip="::", remote_port=0, state="LISTEN",
        state_code="0A", uid=0, inode=300,
        process_name="python3", pid=99,
    )


@pytest.fixture
def alert_critical() -> Alert:
    return Alert(
        level=AlertLevel.CRITICAL, port=4444, proto="tcp",
        process_name="malware", pid=666,
        message="Malicious port",
    )


@pytest.fixture
def alert_warning() -> Alert:
    return Alert(
        level=AlertLevel.WARNING, port=8080, proto="tcp",
        process_name="python3", pid=99,
        message="Unusual port",
    )


# ── IPv6 shortening ───────────────────────────────────────────

class TestIPv6Shortening:
    def test_ipv4_unchanged(self):
        assert _shorten_ipv6("192.168.1.1") == "192.168.1.1"

    def test_loopback_shortened(self):
        result = _shorten_ipv6("0000:0000:0000:0000:0000:0000:0000:0001")
        assert "::" in result
        assert "1" in result

    def test_already_short(self):
        assert _shorten_ipv6("::1") == "::1"

    def test_all_zeros(self):
        result = _shorten_ipv6("0000:0000:0000:0000:0000:0000:0000:0000")
        assert result == "::"

    def test_no_compressible(self):
        addr = "2001:0db8:0001:0002:0003:0004:0005:0006"
        result = _shorten_ipv6(addr)
        # No consecutive zero groups → nothing to compress
        assert "::" not in result

    def test_full_address_compress(self):
        addr = "2001:0db8:0000:0000:0000:ff00:0042:8329"
        result = _shorten_ipv6(addr)
        assert "::" in result

    def test_bracket_stripping(self):
        result = _shorten_ipv6("[::1]")
        assert "[" not in result


# ── Smart address truncation ──────────────────────────────────

class TestSmartTruncateAddr:
    def test_listen_format(self, entry_tcp_listen: SocketEntry):
        result = _smart_truncate_addr(entry_tcp_listen)
        assert ":22" in result
        assert "→" not in result

    def test_established_format(self, entry_tcp_established: SocketEntry):
        result = _smart_truncate_addr(entry_tcp_established)
        assert "→" in result
        assert ":443" in result
        assert ":54321" in result

    def test_ipv6_shortened(self, entry_ipv6: SocketEntry):
        result = _smart_truncate_addr(entry_ipv6)
        assert "::" in result


# ── Human bytes ───────────────────────────────────────────────

class TestHumanBytes:
    def test_bytes(self):
        assert _human_bytes(512) == "512 B"

    def test_kibibytes(self):
        result = _human_bytes(1536)
        assert "KiB" in result

    def test_mebibytes(self):
        result = _human_bytes(5 * 1024 * 1024)
        assert "MiB" in result

    def test_gibibytes(self):
        result = _human_bytes(3 * 1024 * 1024 * 1024)
        assert "GiB" in result

    def test_zero(self):
        assert _human_bytes(0) == "0 B"


# ── Mini sparkline ────────────────────────────────────────────

class TestMiniSparkline:
    def test_empty_data(self):
        from collections import deque
        assert _mini_sparkline(deque(maxlen=20), "green") == ""

    def test_single_point(self):
        from collections import deque
        d = deque([5.0], maxlen=20)
        assert _mini_sparkline(d, "green") == ""

    def test_multiple_points(self):
        from collections import deque
        d = deque([1.0, 5.0, 10.0, 3.0], maxlen=20)
        result = _mini_sparkline(d, "cyan")
        assert "cyan" in result
        assert len(result) > 0
        # Should contain block characters
        assert any(c in result for c in "▁▂▃▄▅▆▇█")

    def test_all_zeros(self):
        from collections import deque
        d = deque([0.0, 0.0, 0.0], maxlen=20)
        result = _mini_sparkline(d, "green")
        assert "▁" in result


# ── Connection Log ────────────────────────────────────────────

class TestConnectionLog:
    def test_memory_bounds(self):
        """K5: Connection log should have max_lines set."""
        log = ConnectionLog()
        assert log.max_lines == 5000

    def test_seen_keys_max(self):
        """K5: _seen_keys should be bounded by _MAX_SEEN."""
        from tui.widgets.connection_log import _MAX_SEEN
        assert _MAX_SEEN == 10_000

    def test_filter_modes(self):
        """Filter should cycle through defined modes."""
        log = ConnectionLog()
        assert log._quick_filter == "all"
        log.cycle_quick_filter()
        assert log._quick_filter == "new"
        log.cycle_quick_filter()
        assert log._quick_filter == "warning"
        log.cycle_quick_filter()
        assert log._quick_filter == "critical"
        log.cycle_quick_filter()
        assert log._quick_filter == "all"

    def test_set_filter(self):
        log = ConnectionLog()
        log.set_filter("firefox")
        assert log._filter_text == "firefox"

    def test_clear_filter(self):
        log = ConnectionLog()
        log.set_filter("test")
        log.set_filter("")
        assert log._filter_text == ""


# ── Port Table ────────────────────────────────────────────────

class TestPortTable:
    def test_row_colour_safe(self, entry_tcp_listen: SocketEntry):
        colour = PortTable._row_colour(entry_tcp_listen, "")
        assert colour == "green"  # Port 22 is in KNOWN_SAFE_PORTS

    def test_row_colour_critical(self, entry_tcp_established: SocketEntry):
        colour = PortTable._row_colour(entry_tcp_established, "CRITICAL")
        assert "red" in colour

    def test_row_colour_warning(self, entry_tcp_established: SocketEntry):
        colour = PortTable._row_colour(entry_tcp_established, "WARNING")
        assert "yellow" in colour

    def test_row_bg_critical(self, entry_tcp_established: SocketEntry):
        bg = PortTable._row_bg(entry_tcp_established, "CRITICAL")
        assert "dark_red" in bg

    def test_row_bg_normal(self, entry_tcp_established: SocketEntry):
        bg = PortTable._row_bg(entry_tcp_established, "")
        assert bg == ""

    def test_full_style(self, entry_tcp_established: SocketEntry):
        style = PortTable._full_style(entry_tcp_established, "CRITICAL")
        assert "red" in style
        assert "dark_red" in style

    def test_full_style_no_bg(self, entry_tcp_established: SocketEntry):
        style = PortTable._full_style(entry_tcp_established, "")
        assert "dark_red" not in style

    def test_sort_column_init(self):
        table = PortTable()
        assert table.sort_column == -1
        assert table.sort_reverse is False


# ── Status Bar ────────────────────────────────────────────────

class TestStatusBar:
    def test_notification_state(self):
        bar = StatusBar()
        assert bar._desktop_notifications is True
        bar.set_notification_state(False)
        assert bar._desktop_notifications is False

    def test_filter_info(self):
        bar = StatusBar()
        assert bar._filter_info == ""
        bar.set_filter_info("Filter: 'ssh' (3 shown)")
        assert bar._filter_info == "Filter: 'ssh' (3 shown)"
        bar.set_filter_info("")
        assert bar._filter_info == ""


# ── Traffic Bar ───────────────────────────────────────────────

class TestTrafficBar:
    def test_history_initialization(self):
        bar = TrafficBar()
        assert bar._rx_history == {}
        assert bar._tx_history == {}

    def test_interface_stats_model(self):
        stats = InterfaceStats(
            interface="eth0",
            rx_bytes=1000, tx_bytes=500,
            rx_packets=10, tx_packets=5,
            rx_errors=0, tx_errors=0,
            rx_drops=0, tx_drops=0,
            rx_rate=100.0, tx_rate=50.0,
        )
        assert stats.rx_rate == 100.0
        assert stats.tx_rate == 50.0
        assert stats.rx_bytes == 1000
        assert stats.interface == "eth0"


# ── Theme System ──────────────────────────────────────────────

class TestThemeSystem:
    def test_themes_exist(self):
        """All 4 themes must be defined (2 custom + 2 built-in mapped)."""
        names = get_theme_names()
        assert "cyberpunk" in names
        assert "nord" in names
        assert "solarized-dark" in names
        assert "kpw-light" in names

    def test_default_theme_is_dark(self):
        assert DEFAULT_THEME == "cyberpunk"

    def test_current_theme_initial(self):
        assert DEFAULT_THEME == "cyberpunk"

    def test_theme_css_generated(self):
        """Custom themes must be properly defined."""
        assert len(KPW_THEMES) >= 2  # cyberpunk + kpw-light
        for name, theme in KPW_THEMES.items():
            assert theme.primary
            assert theme.foreground
            assert theme.name == name

    def test_theme_palette_keys(self):
        """Every custom theme must have required palette fields."""
        required = {"name", "primary", "foreground", "background", "surface"}
        for name, theme in KPW_THEMES.items():
            for field in required:
                assert getattr(theme, field), f"Theme {name} missing field: {field}"

    def test_alert_colour_mapping(self):
        assert alert_colour("CRITICAL") == "bold red"
        assert alert_colour("WARNING") == "bold yellow"
        assert alert_colour("INFO") == "cyan"
        assert alert_colour("unknown") == "white"  # default

    def test_state_colour_mapping(self):
        assert state_colour("ESTABLISHED") == "bold green"
        assert state_colour("LISTEN") == "bold cyan"
        assert state_colour("unknown") == "white"  # default

    def test_alert_colours_dict_complete(self):
        for level in ("CRITICAL", "WARNING", "INFO", "LOW"):
            assert level in ALERT_COLOURS

    def test_state_colours_dict_complete(self):
        for state in ("ESTABLISHED", "LISTEN", "TIME_WAIT", "CLOSE_WAIT",
                      "SYN_SENT", "CLOSING"):
            assert state in STATE_COLOURS

    def test_light_theme_differs_from_dark(self):
        dark_primary = KPW_THEMES["cyberpunk"].primary
        light_primary = KPW_THEMES["kpw-light"].primary
        assert dark_primary != light_primary

    def test_theme_display_map(self):
        """Theme display names map to internal keys."""
        assert display_name_to_key("Cyberpunk") == "cyberpunk"
        assert display_name_to_key("Midnight") == "nord"
        assert display_name_to_key("Hacker") == "solarized-dark"
        assert display_name_to_key("Unknown") == "cyberpunk"  # fallback

    def test_key_to_display_name(self):
        """Internal keys map to display names."""
        assert key_to_display_name("cyberpunk") == "Cyberpunk"
        assert key_to_display_name("nord") == "Midnight"
        assert key_to_display_name("solarized-dark") == "Hacker"
        assert key_to_display_name("nonexistent") == "Cyberpunk"  # fallback to first

    def test_theme_display_names_list(self):
        """Display names list has 4 entries (2 custom + 2 built-in)."""
        assert len(THEME_DISPLAY_NAMES) == 4
        assert "Cyberpunk" in THEME_DISPLAY_NAMES
        assert "Daylight" in THEME_DISPLAY_NAMES


# ── Advanced Filtering ────────────────────────────────────────

class TestAdvancedFiltering:
    def test_proto_filter_default(self):
        """PortTable defaults to ALL protocol filter."""
        table = PortTable()
        assert table.filter_proto == "ALL"

    def test_port_range_filter_default(self):
        """PortTable defaults to full port range."""
        table = PortTable()
        assert table.filter_port_min == 0
        assert table.filter_port_max == 65535

    def test_matches_filter_proto_tcp(self, entry_tcp_established: SocketEntry):
        """TCP entry matches TCP filter but not UDP."""
        table = PortTable()
        table.filter_proto = "TCP"
        assert table._matches_filter(entry_tcp_established, {}) is True
        table.filter_proto = "UDP"
        assert table._matches_filter(entry_tcp_established, {}) is False

    def test_matches_filter_port_range(self, entry_tcp_established: SocketEntry):
        """Entry with port 443 matches range 400-500 but not 500-600."""
        table = PortTable()
        table.filter_port_min = 400
        table.filter_port_max = 500
        assert table._matches_filter(entry_tcp_established, {}) is True
        table.filter_port_min = 500
        table.filter_port_max = 600
        assert table._matches_filter(entry_tcp_established, {}) is False

    def test_matches_filter_text_combined(self, entry_tcp_established: SocketEntry):
        """Text filter + proto filter work together."""
        table = PortTable()
        table.filter_proto = "TCP"
        table.filter_text = "firefox"
        assert table._matches_filter(entry_tcp_established, {}) is True
        table.filter_text = "ssh"
        assert table._matches_filter(entry_tcp_established, {}) is False

    def test_clear_filter_resets_all(self):
        """clear_filter resets text, proto, and port range."""
        table = PortTable()
        table.filter_text = "test"
        table.filter_proto = "TCP"
        table.filter_port_min = 80
        table.filter_port_max = 443
        table.clear_filter()
        assert table.filter_text == ""
        assert table.filter_proto == "ALL"
        assert table.filter_port_min == 0
        assert table.filter_port_max == 65535


# ── Port Scan Detection ───────────────────────────────────────

class TestPortScanDetection:
    def test_detect_port_scan_empty(self):
        """Empty table returns no suspects."""
        table = PortTable()
        results = table.detect_port_scan(threshold=5)
        assert results == []

    def test_detect_port_scan_with_data(self):
        """Multiple ports from same IP detected as scan."""
        table = PortTable()
        entries = []
        for port in [22, 80, 443, 8080, 3306, 5432]:
            entries.append(SocketEntry(
                proto="tcp", local_ip="192.168.1.10", local_port=port,
                remote_ip="10.0.0.1", remote_port=60000 + port,
                state="ESTABLISHED", state_code="01", uid=0, inode=port,
                process_name="scanner", pid=1,
            ))
        table._all_entries = entries
        results = table.detect_port_scan(threshold=5)
        assert len(results) == 1
        assert results[0]["remote_ip"] == "10.0.0.1"
        assert results[0]["port_count"] == 6

    def test_detect_port_scan_threshold(self):
        """Below threshold should not flag."""
        table = PortTable()
        entries = []
        for port in [22, 80, 443]:
            entries.append(SocketEntry(
                proto="tcp", local_ip="192.168.1.10", local_port=port,
                remote_ip="10.0.0.1", remote_port=60000 + port,
                state="ESTABLISHED", state_code="01", uid=0, inode=port,
                process_name="scanner", pid=1,
            ))
        table._all_entries = entries
        results = table.detect_port_scan(threshold=5)
        assert results == []

    def test_scan_suspects_property(self):
        """scan_suspects property delegates to detect_port_scan."""
        table = PortTable()
        assert table.scan_suspects == []


# ── Connection Log Severity Filtering ────────────────────────

class TestConnectionLogSeverity:
    def test_severity_filter_default(self):
        """Default severity filter is ALL."""
        log = ConnectionLog()
        assert log._severity_filter == "ALL"

    def test_severity_label(self):
        """Severity label returns current filter."""
        log = ConnectionLog()
        assert log.severity_label == "ALL"

    def test_severity_for_state(self):
        """State-to-severity mapping works correctly."""
        log = ConnectionLog()
        assert log._severity_for_state("ESTABLISHED") == "INFO"
        assert log._severity_for_state("LISTEN") == "INFO"
        assert log._severity_for_state("SYN_SENT") == "WARNING"
        assert log._severity_for_state("TIME_WAIT") == "WARNING"
        assert log._severity_for_state("CLOSE_WAIT") == "WARNING"
        assert log._severity_for_state("CLOSING") == "ERROR"
        assert log._severity_for_state("LAST_ACK") == "ERROR"
        assert log._severity_for_state("CLOSE") == "ERROR"

    def test_passes_severity_filter_all(self):
        """ALL filter passes everything."""
        log = ConnectionLog()
        entry = SocketEntry(
            proto="tcp", local_ip="1.2.3.4", local_port=80,
            remote_ip="5.6.7.8", remote_port=12345,
            state="CLOSING", state_code="01", uid=0, inode=1,
        )
        assert log._passes_severity_filter(entry) is True

    def test_passes_severity_filter_error(self):
        """ERROR filter only passes ERROR severity states."""
        log = ConnectionLog()
        log._severity_filter = "ERROR"
        error_entry = SocketEntry(
            proto="tcp", local_ip="1.2.3.4", local_port=80,
            remote_ip="5.6.7.8", remote_port=12345,
            state="CLOSING", state_code="01", uid=0, inode=1,
        )
        info_entry = SocketEntry(
            proto="tcp", local_ip="1.2.3.4", local_port=80,
            remote_ip="5.6.7.8", remote_port=12345,
            state="ESTABLISHED", state_code="01", uid=0, inode=2,
        )
        assert log._passes_severity_filter(error_entry) is True
        assert log._passes_severity_filter(info_entry) is False

    def test_passes_severity_filter_warning(self):
        """WARNING filter passes WARNING and ERROR states."""
        log = ConnectionLog()
        log._severity_filter = "WARNING"
        warn_entry = SocketEntry(
            proto="tcp", local_ip="1.2.3.4", local_port=80,
            remote_ip="5.6.7.8", remote_port=12345,
            state="TIME_WAIT", state_code="01", uid=0, inode=3,
        )
        info_entry = SocketEntry(
            proto="tcp", local_ip="1.2.3.4", local_port=80,
            remote_ip="5.6.7.8", remote_port=12345,
            state="ESTABLISHED", state_code="01", uid=0, inode=4,
        )
        assert log._passes_severity_filter(warn_entry) is True
        assert log._passes_severity_filter(info_entry) is False

    def test_set_severity_filter_invalid(self):
        """Invalid severity defaults to ALL."""
        log = ConnectionLog()
        log._last_entries = []  # prevent rebuild error
        log.set_severity_filter("INVALID")
        assert log._severity_filter == "ALL"


# ── Settings Screen ───────────────────────────────────────────

class TestSettingsScreen:
    def test_settings_screen_import(self):
        """Settings screen can be imported without error."""
        from tui.screens.settings_screen import SettingsScreen
        assert SettingsScreen is not None

    def test_available_themes(self):
        """AVAILABLE_THEMES has 3 entries matching theme display names."""
        from tui.screens.settings_screen import AVAILABLE_THEMES
        assert len(AVAILABLE_THEMES) == 3
        assert "Cyberpunk" in AVAILABLE_THEMES
        assert "Midnight" in AVAILABLE_THEMES
        assert "Hacker" in AVAILABLE_THEMES

    def test_settings_screen_constructor(self):
        """Settings screen constructor accepts all new parameters."""
        from tui.screens.settings_screen import SettingsScreen
        screen = SettingsScreen(
            desktop_notifications=True,
            tui_notifications=True,
            geoip_enabled=True,
            burst_threshold=3,
            scan_threshold=5,
            current_theme="Cyberpunk",
        )
        assert screen._scan_threshold == 5
        assert screen._current_theme == "Cyberpunk"
