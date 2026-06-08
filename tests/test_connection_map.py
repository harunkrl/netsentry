"""Tests for tui/screens/connection_map_screen.py.

Tests cover pure functions (_is_private_ip, _lat_lon_to_grid, _render_map,
_get_base_grid) and Textual headless tests for ConnectionMapScreen.
"""
from __future__ import annotations

import asyncio
import time
from dataclasses import asdict
from unittest.mock import Mock, patch

import pytest
from backend.models import AlertLevel, InterfaceStats, Snapshot, SocketEntry
from textual.app import App
from textual.widgets import DataTable, Input, Static

from tui.screens.connection_map_screen import (
    ConnectionMapScreen,
    _get_base_grid,
    _is_private_ip,
    _lat_lon_to_grid,
    _render_map,
    _SORT_COLUMNS,
    _SORT_LABELS,
    _WORLD_MAP,
    _MAP_ROWS,
    _MAP_COLS,
)


# ── Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def geo_established_entries() -> list[SocketEntry]:
    """Multiple established connections with different GeoIP data."""
    return [
        SocketEntry(
            proto="tcp", local_ip="192.168.1.10", local_port=44532,
            remote_ip="142.250.80.14", remote_port=443,
            state="ESTABLISHED", state_code="01", uid=1000, inode=67890,
            pid=1234, process_name="firefox",
            remote_country="United States", remote_country_code="US",
            remote_city="Mountain View", remote_lat=37.386, remote_lon=-122.084,
        ),
        SocketEntry(
            proto="tcp", local_ip="192.168.1.10", local_port=54321,
            remote_ip="93.184.216.34", remote_port=80,
            state="ESTABLISHED", state_code="01", uid=1000, inode=67891,
            pid=1234, process_name="firefox",
            remote_country="United Kingdom", remote_country_code="GB",
            remote_city="London", remote_lat=51.507, remote_lon=-0.128,
        ),
        SocketEntry(
            proto="tcp", local_ip="192.168.1.10", local_port=54322,
            remote_ip="103.224.182.210", remote_port=443,
            state="ESTABLISHED", state_code="01", uid=1000, inode=67892,
            pid=5678, process_name="thunderbird",
            remote_country="Australia", remote_country_code="AU",
            remote_city="Sydney", remote_lat=-33.868, remote_lon=151.209,
        ),
    ]


@pytest.fixture
def geo_snapshot(geo_established_entries) -> Snapshot:
    """Snapshot with GeoIP-populated established connections."""
    return Snapshot(
        timestamp=time.time(),
        established=geo_established_entries,
        geo_stats={
            "countries_count": 3,
            "unique_ips_per_country": {"US": 1, "GB": 1, "AU": 1},
            "top_countries": [["United States", 1], ["United Kingdom", 1], ["Australia", 1]],
        },
        summary={"total_listening": 0, "total_established": 3, "alert_count": 0},
    )


@pytest.fixture
def mock_provider(geo_snapshot: Snapshot) -> Mock:
    """Mock DataProvider returning geo_snapshot."""
    provider = Mock()
    provider.fetch.return_value = geo_snapshot
    return provider


@pytest.fixture
def empty_provider() -> Mock:
    """Mock DataProvider returning None (daemon down)."""
    provider = Mock()
    provider.fetch.return_value = None
    return provider


def _make_geo_app(provider: Mock) -> App:
    """Create a minimal Textual App with a mock data_provider."""
    app = App()
    app.data_provider = provider
    return app


# ══════════════════════════════════════════════════════════════
# Pure Function Tests
# ══════════════════════════════════════════════════════════════


class TestIsPrivateIp:
    """Tests for _is_private_ip()."""

    def test_loopback(self):
        assert _is_private_ip("127.0.0.1") is True

    def test_private_class_a(self):
        assert _is_private_ip("10.0.0.1") is True

    def test_private_class_b(self):
        assert _is_private_ip("172.16.0.1") is True

    def test_private_class_c(self):
        assert _is_private_ip("192.168.1.1") is True

    def test_link_local(self):
        assert _is_private_ip("169.254.0.1") is True

    def test_public_ip(self):
        assert _is_private_ip("142.250.80.14") is False

    def test_another_public_ip(self):
        assert _is_private_ip("8.8.8.8") is False

    def test_invalid_ip(self):
        assert _is_private_ip("not-an-ip") is True

    def test_empty_string(self):
        assert _is_private_ip("") is True

    def test_ipv6_loopback(self):
        assert _is_private_ip("::1") is True

    def test_ipv6_link_local(self):
        assert _is_private_ip("fe80::1") is True


class TestLatLonToGrid:
    """Tests for _lat_lon_to_grid()."""

    def test_top_left_corner(self):
        """90°N, 180°W should map to row 0."""
        row, col = _lat_lon_to_grid(90, -180)
        assert row == 0
        assert col == 0

    def test_bottom_right_corner(self):
        """90°S, 180°E should map to last row."""
        row, col = _lat_lon_to_grid(-90, 180)
        assert row == _MAP_ROWS - 1
        assert col == _MAP_COLS - 1

    def test_equator_prime_meridian(self):
        """0°, 0° should map roughly to the center."""
        row, col = _lat_lon_to_grid(0, 0)
        assert _MAP_ROWS // 2 - 1 <= row <= _MAP_ROWS // 2 + 1
        assert _MAP_COLS // 2 - 1 <= col <= _MAP_COLS // 2 + 1

    def test_clamping_above_max(self):
        """lat=100 should clamp to row 0."""
        row, col = _lat_lon_to_grid(100, 0)
        assert row == 0

    def test_clamping_below_min(self):
        """lat=-100 should clamp to last row."""
        row, col = _lat_lon_to_grid(-100, 0)
        assert row == _MAP_ROWS - 1

    def test_lon_clamping(self):
        """lon=200 should clamp to last col."""
        row, col = _lat_lon_to_grid(0, 200)
        assert col == _MAP_COLS - 1

    def test_san_francisco(self):
        """San Francisco ~37.7°N, 122.4°W."""
        row, col = _lat_lon_to_grid(37.7, -122.4)
        assert 0 <= row < _MAP_ROWS
        assert 0 <= col < _MAP_COLS

    def test_sydney_australia(self):
        """Sydney ~-33.9°N, 151.2°E."""
        row, col = _lat_lon_to_grid(-33.9, 151.2)
        assert 0 <= row < _MAP_ROWS
        assert 0 <= col < _MAP_COLS


class TestGetBaseGrid:
    """Tests for _get_base_grid()."""

    def test_returns_list_of_lists(self):
        grid = _get_base_grid()
        assert isinstance(grid, list)
        for row in grid:
            assert isinstance(row, list)

    def test_dimensions_match_world_map(self):
        grid = _get_base_grid()
        assert len(grid) == _MAP_ROWS
        for row in grid:
            assert len(row) == _MAP_COLS

    def test_returns_mutable_copy(self):
        """Each call returns a new copy — mutations don't affect the base."""
        grid1 = _get_base_grid()
        grid2 = _get_base_grid()
        assert grid1 is not grid2
        grid1[0][0] = "X"
        assert grid2[0][0] != "X"


class TestRenderMap:
    """Tests for _render_map()."""

    def test_empty_connections_renders_clean_map(self):
        """No connections → clean map with legend."""
        result = _render_map([])
        assert isinstance(result, str)
        assert len(result) > 0
        # Should contain the legend
        assert "conn" in result or "●" in result

    def test_single_connection_shows_marker(self):
        """Single connection at valid coordinates."""
        connections = [{"lat": 37.386, "lon": -122.084}]
        result = _render_map(connections)
        # Should contain single-connection marker
        assert "●" in result

    def test_multiple_connections_same_cell_shows_cluster(self):
        """4+ connections at same grid cell → ◉ marker."""
        connections = [{"lat": 37.386, "lon": -122.084}] * 5
        result = _render_map(connections)
        assert "◉" in result

    def test_two_to_three_connections_shows_medium_marker(self):
        """2-3 connections at same cell → ◎ marker."""
        connections = [{"lat": 37.386, "lon": -122.084}] * 2
        result = _render_map(connections)
        assert "◎" in result

    def test_home_location_marker(self):
        """Home location should show ✚ marker."""
        result = _render_map([], home_lat=41.0, home_lon=29.0)
        assert "✚" in result

    def test_null_island_skipped(self):
        """(0, 0) coordinates should be skipped (Null Island fix)."""
        connections = [{"lat": 0, "lon": 0}]
        result = _render_map(connections)
        # No connection markers should appear (only legend)
        lines = result.split("\n")
        # Map lines should not contain ● or ◎ or ◉
        map_lines = lines[:-1]  # Last line is legend
        for line in map_lines:
            assert "●" not in line
            assert "◎" not in line
            assert "◉" not in line

    def test_none_coordinates_skipped(self):
        """Connections with None lat/lon should be skipped."""
        connections = [
            {"lat": None, "lon": None},
            {"lat": 37.386, "lon": None},
            {"lat": None, "lon": -122.084},
        ]
        result = _render_map(connections)
        # No markers should appear on map
        lines = result.split("\n")
        map_lines = lines[:-1]
        for line in map_lines:
            assert "●" not in line

    def test_legend_present(self):
        """Rendered map should always include legend."""
        result = _render_map([])
        assert "you" in result or "✚" in result

    def test_rich_markup_in_output(self):
        """Output should contain Rich markup for colored markers."""
        connections = [{"lat": 37.386, "lon": -122.084}]
        result = _render_map(connections)
        assert "[green]" in result

    def test_multiple_unique_locations(self):
        """Multiple connections at different locations."""
        connections = [
            {"lat": 37.386, "lon": -122.084},  # US
            {"lat": 51.507, "lon": -0.128},      # UK
            {"lat": -33.868, "lon": 151.209},    # AU
        ]
        result = _render_map(connections)
        # Should have markers in output
        assert "●" in result

    def test_connections_with_extra_fields(self):
        """Extra dict fields (ip, port, etc.) should not break rendering."""
        connections = [
            {"lat": 37.386, "lon": -122.084, "ip": "1.2.3.4", "port": 443},
        ]
        result = _render_map(connections)
        assert "●" in result


# ══════════════════════════════════════════════════════════════
# Textual Headless Screen Tests
# ══════════════════════════════════════════════════════════════


class TestConnectionMapScreenMount:
    """Tests for ConnectionMapScreen mounting and composition."""

    @pytest.mark.asyncio
    async def test_screen_mounts_with_widgets(self, mock_provider):
        """Screen mounts with all expected widgets."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            assert screen.query_one("#map-header", Static) is not None
            assert screen.query_one("#world-map", Static) is not None
            assert screen.query_one("#geo-table", DataTable) is not None
            assert screen.query_one("#geo-search-input", Input) is not None

    @pytest.mark.asyncio
    async def test_table_has_correct_columns(self, mock_provider):
        """DataTable has #, Country, City, IP, Port, Process, Count columns."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            table = screen.query_one("#geo-table", DataTable)
            # DataTable columns are tracked internally; verify header count
            assert len(table.columns) >= 7

    @pytest.mark.asyncio
    async def test_search_input_initially_hidden(self, mock_provider):
        """Search input is initially hidden and disabled."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            search = screen.query_one("#geo-search-input", Input)
            assert search.disabled is True
            assert search.has_class("hidden")

    @pytest.mark.asyncio
    async def test_map_visible_by_default(self, mock_provider):
        """Map widget is visible by default."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            assert screen._map_visible is True


class TestConnectionMapScreenDataFlow:
    """Tests for data flow: snapshot → map + table rendering."""

    @pytest.mark.asyncio
    async def test_refresh_populates_connections(self, mock_provider, geo_snapshot):
        """refresh_data populates _connections from snapshot."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # refresh_data is called on mount, but give it time
            await pilot.pause()
            await pilot.pause()

            # _connections should be populated (3 entries from geo_snapshot)
            assert len(screen._connections) == 3

    @pytest.mark.asyncio
    async def test_refresh_updates_header(self, mock_provider):
        """Header is updated with connection count."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            header = screen.query_one("#map-header", Static)
            rendered = str(header.render())
            assert "3" in rendered  # 3 connections
            assert "Connection Map" in rendered

    @pytest.mark.asyncio
    async def test_refresh_updates_table_rows(self, mock_provider):
        """DataTable is populated with grouped rows."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            table = screen.query_one("#geo-table", DataTable)
            # 3 unique IPs = 3 rows
            assert table.row_count == 3

    @pytest.mark.asyncio
    async def test_refresh_with_daemon_down(self, empty_provider):
        """When provider returns None, shows waiting message."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(empty_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            header = screen.query_one("#map-header", Static)
            rendered = str(header.render())
            assert "Waiting" in rendered or "daemon" in rendered.lower()

    @pytest.mark.asyncio
    async def test_private_ips_filtered_out(self):
        """Private IP connections should not appear in _connections."""
        snapshot = Snapshot(
            established=[
                SocketEntry(
                    proto="tcp", local_ip="192.168.1.10", local_port=44532,
                    remote_ip="127.0.0.1", remote_port=8080,
                    state="ESTABLISHED", state_code="01", uid=1000, inode=1,
                ),
                SocketEntry(
                    proto="tcp", local_ip="192.168.1.10", local_port=44533,
                    remote_ip="192.168.1.1", remote_port=443,
                    state="ESTABLISHED", state_code="01", uid=1000, inode=2,
                ),
            ],
        )
        provider = Mock()
        provider.fetch.return_value = snapshot

        screen = ConnectionMapScreen()
        app = _make_geo_app(provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            # No public connections → _connections should be empty
            assert len(screen._connections) == 0


class TestConnectionMapScreenToggle:
    """Tests for map toggle and search actions."""

    @pytest.mark.asyncio
    async def test_toggle_map_hides_widget(self, mock_provider):
        """action_toggle_map hides the map widget."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            assert screen._map_visible is True

            screen.action_toggle_map()
            await pilot.pause()

            assert screen._map_visible is False
            map_widget = screen.query_one("#world-map", Static)
            assert map_widget.has_class("hidden")

    @pytest.mark.asyncio
    async def test_toggle_map_shows_again(self, mock_provider):
        """Toggling map twice shows it again."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            screen.action_toggle_map()
            await pilot.pause()
            assert screen._map_visible is False

            screen.action_toggle_map()
            await pilot.pause()
            assert screen._map_visible is True

    @pytest.mark.asyncio
    async def test_action_search_shows_input(self, mock_provider):
        """action_search shows the search input."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            screen.action_search()
            await pilot.pause()

            search = screen.query_one("#geo-search-input", Input)
            assert not search.disabled
            assert not search.has_class("hidden")

    @pytest.mark.asyncio
    async def test_hide_search_clears_filter(self, mock_provider):
        """_hide_search clears filter text and hides input."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Set some filter state
            screen._filter_text = "test"
            screen.action_search()
            await pilot.pause()

            screen._hide_search()
            await pilot.pause()

            search = screen.query_one("#geo-search-input", Input)
            assert search.disabled is True
            assert search.has_class("hidden")
            assert screen._filter_text == ""


class TestConnectionMapScreenSort:
    """Tests for sort cycling."""

    @pytest.mark.asyncio
    async def test_cycle_sort_increments(self, mock_provider):
        """action_cycle_sort advances sort index."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            assert screen._sort_index == 0

            screen.action_cycle_sort()
            assert screen._sort_index == 1

            screen.action_cycle_sort()
            assert screen._sort_index == 2

    @pytest.mark.asyncio
    async def test_cycle_sort_wraps_around(self, mock_provider):
        """Sort index wraps to 0 after reaching the end."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            # Cycle through all columns
            for _ in range(len(_SORT_COLUMNS)):
                screen.action_cycle_sort()

            # Should be back to 0 (not 1 — reverse toggles when wrapping)
            assert screen._sort_index == 0

    @pytest.mark.asyncio
    async def test_sort_columns_match_labels(self):
        """Every sort column should have a matching label."""
        assert len(_SORT_COLUMNS) == len(_SORT_LABELS)


class TestConnectionMapScreenFilter:
    """Tests for filter/search functionality."""

    @pytest.mark.asyncio
    async def test_filter_by_country(self, mock_provider):
        """Filtering by country reduces visible rows."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            table = screen.query_one("#geo-table", DataTable)
            assert table.row_count == 3

            # Filter for "united states"
            screen._filter_text = "united states"
            screen._update_table(screen._connections)

            assert table.row_count == 1

    @pytest.mark.asyncio
    async def test_filter_by_ip(self, mock_provider):
        """Filtering by IP reduces visible rows."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            screen._filter_text = "142.250"
            screen._update_table(screen._connections)

            table = screen.query_one("#geo-table", DataTable)
            assert table.row_count == 1

    @pytest.mark.asyncio
    async def test_filter_by_process(self, mock_provider):
        """Filtering by process name reduces visible rows."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            screen._filter_text = "thunderbird"
            screen._update_table(screen._connections)

            table = screen.query_one("#geo-table", DataTable)
            assert table.row_count == 1

    @pytest.mark.asyncio
    async def test_filter_no_match_shows_empty(self, mock_provider):
        """Filter with no matches shows empty table."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            screen._filter_text = "zzz_nonexistent"
            screen._update_table(screen._connections)

            table = screen.query_one("#geo-table", DataTable)
            assert table.row_count == 0

    @pytest.mark.asyncio
    async def test_clear_filter_shows_all(self, mock_provider):
        """Clearing filter shows all rows again."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            # Apply filter
            screen._filter_text = "firefox"
            screen._update_table(screen._connections)
            filtered_count = screen.query_one("#geo-table", DataTable).row_count
            assert filtered_count == 2  # 2 firefox entries

            # Clear filter
            screen._filter_text = ""
            screen._update_table(screen._connections)
            assert screen.query_one("#geo-table", DataTable).row_count == 3


class TestConnectionMapScreenActions:
    """Tests for screen actions (close, copy)."""

    @pytest.mark.asyncio
    async def test_action_close(self, mock_provider):
        """action_close pops the screen."""
        screen = ConnectionMapScreen()
        app = _make_geo_app(mock_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            with patch.object(app, 'pop_screen') as mock_pop:
                screen.action_close()
                mock_pop.assert_called_once()

    @pytest.mark.asyncio
    async def test_action_copy_no_selection(self, mock_provider):
        """Copy with empty table notifies user."""
        # Use a provider that returns empty snapshot so table has no rows
        empty_snap = Snapshot(established=[])
        empty_prov = Mock()
        empty_prov.fetch.return_value = empty_snap

        screen = ConnectionMapScreen()
        app = _make_geo_app(empty_prov)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            # With an empty table and no cursor row, copy should notify
            with patch.object(app, 'notify') as mock_notify:
                screen.action_copy_row()
                mock_notify.assert_called_once()


class TestConnectionMapScreenEdgeCases:
    """Tests for edge cases and error handling."""

    @pytest.mark.asyncio
    async def test_snapshot_with_empty_established(self):
        """Snapshot with empty established list → no connections."""
        snapshot = Snapshot(established=[])
        provider = Mock()
        provider.fetch.return_value = snapshot

        screen = ConnectionMapScreen()
        app = _make_geo_app(provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            assert len(screen._connections) == 0

    @pytest.mark.asyncio
    async def test_snapshot_with_none_established(self):
        """Snapshot with established=None → no connections."""
        snapshot = Snapshot()
        snapshot.established = None
        provider = Mock()
        provider.fetch.return_value = snapshot

        screen = ConnectionMapScreen()
        app = _make_geo_app(provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            assert len(screen._connections) == 0

    @pytest.mark.asyncio
    async def test_connection_without_remote_ip(self):
        """SocketEntry with empty remote_ip is filtered out."""
        snapshot = Snapshot(
            established=[
                SocketEntry(
                    proto="tcp", local_ip="0.0.0.0", local_port=22,
                    remote_ip="", remote_port=0,
                    state="LISTEN", state_code="0A", uid=0, inode=1,
                ),
            ],
        )
        provider = Mock()
        provider.fetch.return_value = snapshot

        screen = ConnectionMapScreen()
        app = _make_geo_app(provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            assert len(screen._connections) == 0

    @pytest.mark.asyncio
    async def test_multiple_connections_same_ip_grouped(self):
        """Multiple connections to same IP should be grouped into one row."""
        snapshot = Snapshot(
            established=[
                SocketEntry(
                    proto="tcp", local_ip="192.168.1.10", local_port=40001,
                    remote_ip="142.250.80.14", remote_port=443,
                    state="ESTABLISHED", state_code="01", uid=1000, inode=1,
                    pid=1234, process_name="firefox",
                    remote_country="United States", remote_country_code="US",
                    remote_city="Mountain View", remote_lat=37.386, remote_lon=-122.084,
                ),
                SocketEntry(
                    proto="tcp", local_ip="192.168.1.10", local_port=40002,
                    remote_ip="142.250.80.14", remote_port=80,
                    state="ESTABLISHED", state_code="01", uid=1000, inode=2,
                    pid=1234, process_name="firefox",
                    remote_country="United States", remote_country_code="US",
                    remote_city="Mountain View", remote_lat=37.386, remote_lon=-122.084,
                ),
            ],
            geo_stats={"countries_count": 1},
        )
        provider = Mock()
        provider.fetch.return_value = snapshot

        screen = ConnectionMapScreen()
        app = _make_geo_app(provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            # 2 connections to same IP → grouped into 1 row
            table = screen.query_one("#geo-table", DataTable)
            assert table.row_count == 1

    @pytest.mark.asyncio
    async def test_count_coloring_high(self):
        """4+ connections to same IP show bold red count."""
        entries = []
        for port in [443, 80, 8080, 22, 53]:
            entries.append(SocketEntry(
                proto="tcp", local_ip="192.168.1.10", local_port=40000 + port,
                remote_ip="142.250.80.14", remote_port=port,
                state="ESTABLISHED", state_code="01", uid=1000, inode=port,
                pid=1234, process_name="firefox",
                remote_country="United States", remote_country_code="US",
            ))
        snapshot = Snapshot(established=entries, geo_stats={"countries_count": 1})
        provider = Mock()
        provider.fetch.return_value = snapshot

        screen = ConnectionMapScreen()
        app = _make_geo_app(provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            table = screen.query_one("#geo-table", DataTable)
            assert table.row_count == 1
            row_data = table.get_row_at(0)
            # Count column should contain "5" with markup
            count_str = str(row_data[-1])
            assert "5" in count_str
