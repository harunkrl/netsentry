"""KPortWatch TUI — Connection map screen.

Displays outbound connections on an ASCII world map with a sortable
country/IP detail table.  GeoIP data is provided by the daemon via
the JSON snapshot (populated by backend.parsers.geoip).

Keyboard shortcuts:
  m     — toggle ASCII world map on/off
  /     — filter by country / IP / process
  s     — cycle sort column
  Esc   — close screen
"""

from __future__ import annotations

import asyncio
import logging
from collections import defaultdict

from backend.models import SocketEntry
from shared.network import is_private_ip
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import DataTable, Footer, Header, Input, Static

from tui.data.map_loader import load_world_map
from tui.data.provider import DataProvider
from tui.utils.clipboard import safe_copy_to_clipboard

log = logging.getLogger(__name__)

# ── Sort columns ────────────────────────────────────────────────
_SORT_COLUMNS = ["country", "city", "ip", "port", "process", "count"]
_SORT_LABELS = ["Country", "City", "IP", "Port", "Process", "Count"]


# ── ASCII World Map — loaded from external file ───────────
_WORLD_MAP: list[str] = load_world_map()
_MAP_ROWS = len(_WORLD_MAP)
_MAP_COLS = len(_WORLD_MAP[0]) if _WORLD_MAP else 0


def _lat_lon_to_grid(lat: float, lon: float) -> tuple[int, int]:
    """Convert lat/lon to (row, col) on the ASCII map grid."""
    # Equirectangular projection
    row = int((90 - lat) / 180 * (_MAP_ROWS - 1))
    col = int((lon + 180) / 360 * (_MAP_COLS - 1))
    return (
        max(0, min(_MAP_ROWS - 1, row)),
        max(0, min(_MAP_COLS - 1, col)),
    )


_BASE_GRID: list[list[str]] | None = None


def _get_base_grid() -> list[list[str]]:
    """Return a cached mutable copy of the base world map grid."""
    global _BASE_GRID
    if _BASE_GRID is None:
        _BASE_GRID = [list(row) for row in _WORLD_MAP]
    return [row[:] for row in _BASE_GRID]


def _render_map(
    connections: list[dict],
    home_lat: float | None = None,
    home_lon: float | None = None,
) -> str:
    """Render the ASCII world map with connection markers."""
    # Build mutable grid from cached base
    grid = _get_base_grid()

    # Aggregate connections per grid cell
    # O6: Skip (0, 0) coordinates — Null Island fix
    cell_counts: dict[tuple[int, int], int] = defaultdict(int)
    for conn in connections:
        lat = conn.get("lat")
        lon = conn.get("lon")
        # Skip entries with no real geo data (0,0 = Null Island)
        if lat is not None and lon is not None and not (lat == 0 and lon == 0):
            r, c = _lat_lon_to_grid(lat, lon)
            cell_counts[(r, c)] += 1

    # Place markers
    for (r, c), count in cell_counts.items():
        if count <= 1:
            ch = "●"
        elif count <= 3:
            ch = "◎"
        else:
            ch = "◉"
        grid[r][c] = ch

    # Place home marker
    if home_lat is not None and home_lon is not None:
        hr, hc = _lat_lon_to_grid(home_lat, home_lon)
        grid[hr][hc] = "✚"

    # Build string with Rich markup for markers
    lines: list[str] = []
    for _r_idx, row in enumerate(grid):
        line_chars: list[str] = []
        for _c_idx, ch in enumerate(row):
            if ch == "●":
                line_chars.append("[green]●[/]")
            elif ch == "◎":
                line_chars.append("[yellow]◎[/]")
            elif ch == "◉":
                line_chars.append("[bold red]◉[/]")
            elif ch == "✚":
                line_chars.append("[cyan]✚[/]")
            else:
                line_chars.append(ch)
        lines.append("".join(line_chars))

    # Legend
    legend = "[dim]([/][green]●[/][dim]=1 conn  [/][yellow]◎[/][dim]=2-3  [/][bold red]◉[/][dim]=4+  [/][cyan]✚[/][dim]=you)[/]"

    return "\n".join(lines) + "\n" + legend


# ── Screen ──────────────────────────────────────────────────────


class ConnectionMapScreen(Screen):
    """Full-screen outbound connection map with ASCII world map and detail table."""

    BINDINGS = [
        Binding("escape", "close", "Back", show=True),
        Binding("m", "toggle_map", "Map", show=True),
        Binding("slash", "search", "Search", show=True),
        Binding("o", "cycle_sort", "Sort", show=True),
        Binding("c", "copy_row", "Copy", show=True),
    ]

    CSS = """
    ConnectionMapScreen {
        layout: vertical;
    }
    #map-header {
        height: auto;
        padding: 0 1;
        background: $surface;
        color: $primary;
    }
    #world-map {
        height: auto;
        max-height: 22;
        border: round $primary;
        background: $surface;
        padding: 0 1;
        overflow-x: auto;
    }
    #geo-search-bar {
        height: auto;
        display: none;
        margin: 0 1;
    }
    #geo-search-input {
        width: 100%;
    }
    /* Uses global .hidden from styles.tcss */
    #geo-table {
        height: 1fr;
        border: round $primary;
        padding: 0 1;
        background: $surface;
    }
    /* Map visibility uses .hidden from styles.tcss */
    """

    def __init__(self) -> None:
        super().__init__()
        self.provider: DataProvider | None = None  # resolved in on_mount
        self._filter_text: str = ""
        self._sort_index: int = 0
        self._sort_reverse: bool = False
        self._map_visible: bool = True
        self._connections: list[dict] = []
        self._geo_stats: dict = {}

    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Static(id="map-header")
        yield Static(id="world-map")
        yield Input(
            placeholder="Filter by country / IP / process (Esc to close)...",
            id="geo-search-input",
            classes="hidden",
            disabled=True,
        )
        yield DataTable(id="geo-table")
        yield Footer()

    def on_key(self, event) -> None:
        """Intercept Escape/Tab when geo-search Input has focus."""
        try:
            search_input = self.query_one("#geo-search-input", Input)
            if search_input.disabled:
                return
        except Exception:
            return
        if event.key == "escape":
            self._hide_search()
            event.stop()
        elif event.key == "tab":
            self._hide_search()

    def on_mount(self) -> None:
        # Resolve data provider after widget is mounted (self.app is available)
        from tui.utils.provider import get_app_provider

        self.provider = get_app_provider(self.app)

        table = self.query_one("#geo-table", DataTable)
        table.add_columns("#", "Country", "City", "IP", "Port", "Process", "Count")

        self.refresh_data()
        self._refresh_handle = self.set_interval(2.0, self.refresh_data)

        # Ensure the table, not the hidden search input, receives initial focus
        table.focus()

    def on_unmount(self) -> None:
        if hasattr(self, "_refresh_handle") and self._refresh_handle is not None:
            self._refresh_handle.stop()

    @work(exclusive=True)
    async def refresh_data(self) -> None:
        snapshot = await asyncio.to_thread(self.provider.fetch)
        if snapshot is None:
            try:
                header = self.query_one("#map-header", Static)
                header.update("[dim]Waiting for daemon data...[/]")
            except Exception:
                pass
            return

        # Save focus before updating widgets
        focused = self.focused

        established: list[SocketEntry] = getattr(snapshot, "established", []) or []
        geo_stats: dict = getattr(snapshot, "geo_stats", {}) or {}

        connections: list[dict] = []
        for e in established:
            if not e.remote_ip or is_private_ip(e.remote_ip):
                continue
            connections.append(
                {
                    "country": e.remote_country or "Unknown",
                    "country_code": e.remote_country_code or "",
                    "city": e.remote_city or "",
                    "ip": e.remote_ip,
                    "port": e.remote_port,
                    "process": e.process_name or "",
                    "lat": e.remote_lat,
                    "lon": e.remote_lon,
                }
            )

        self._connections = connections
        self._geo_stats = geo_stats
        self._update_map(connections, geo_stats)
        self._update_table(connections)

        # Restore focus if it was stolen during the update
        if focused and self.focused is not focused:
            focused.focus()

    def _update_map(self, connections: list[dict], geo_stats: dict) -> None:
        countries = geo_stats.get("countries_count", 0)
        unique_ips = len({c["ip"] for c in connections})
        total = len(connections)

        header = self.query_one("#map-header", Static)

        # FIX: Changed [s]ort to <o> sort to prevent Textual/Rich markup collisions.
        header.update(
            f"[bold]Connection Map[/]  |  "
            f"{total} connections  |  "
            f"{unique_ips} unique IPs  |  "
            f"{countries} countries  |  "
            f"[dim]</>/ filter  <o> sort  <m> map toggle  <Esc> back[/dim]"
        )

        if self._map_visible:
            map_widget = self.query_one("#world-map", Static)
            map_widget.update(_render_map(connections))

    def _update_table(self, connections: list[dict]) -> None:
        table = self.query_one("#geo-table", DataTable)
        table.clear()

        filtered = connections
        if self._filter_text:
            ft = self._filter_text
            filtered = [
                c
                for c in connections
                if ft in c["country"].lower()
                or ft in c["city"].lower()
                or ft in c["ip"].lower()
                or ft in c["process"].lower()
            ]

        grouped: dict[tuple[str, str], dict] = {}
        for c in filtered:
            key = (c.get("country_code", "") or c["country"], c["ip"])
            if key not in grouped:
                grouped[key] = {
                    "country": c["country"],
                    "country_code": c.get("country_code", ""),
                    "city": c["city"],
                    "ip": c["ip"],
                    "ports": set(),
                    "processes": set(),
                    "count": 0,
                }
            grouped[key]["ports"].add(str(c["port"]))
            grouped[key]["processes"].add(c["process"] or "?")
            grouped[key]["count"] += 1

        rows = list(grouped.values())

        sort_key = _SORT_COLUMNS[self._sort_index]
        reverse = self._sort_reverse

        def _sort_fn(row: dict) -> str | int:
            if sort_key == "country":
                return row["country"].lower()
            elif sort_key == "city":
                return row["city"].lower()
            elif sort_key == "ip":
                return row["ip"]
            elif sort_key == "port":
                ports = row["ports"]
                return min(ports) if ports else ""
            elif sort_key == "process":
                procs = row["processes"]
                return ", ".join(sorted(procs)).lower()
            elif sort_key == "count":
                return row["count"]
            return ""

        rows.sort(key=_sort_fn, reverse=reverse)

        for idx, row in enumerate(rows, 1):
            ports_str = ", ".join(sorted(row["ports"], key=lambda p: int(p)))
            procs_str = ", ".join(sorted(row["processes"]))
            count = row["count"]

            if count >= 4:
                count_str = f"[bold red]{count}[/]"
            elif count >= 2:
                count_str = f"[yellow]{count}[/]"
            else:
                count_str = str(count)

            table.add_row(
                str(idx),
                row["country"],
                row["city"] or "[dim]-[/]",
                row["ip"],
                ports_str,
                procs_str,
                count_str,
                key=row["ip"],
            )

    def on_input_changed(self, event: Input.Changed) -> None:
        if event.input.id == "geo-search-input":
            self._filter_text = event.value.lower().strip()
            self._update_table(self._connections)

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "geo-search-input":
            self._hide_search()

    def action_close(self) -> None:
        self.app.pop_screen()

    def action_toggle_map(self) -> None:
        self._map_visible = not self._map_visible
        try:
            map_widget = self.query_one("#world-map", Static)
            if self._map_visible:
                map_widget.remove_class("hidden")
                # O12 fix: Use cached geo_stats to avoid resetting counters
                self._update_map(self._connections, self._geo_stats)
            else:
                map_widget.add_class("hidden")
        except Exception:
            pass

    def action_search(self) -> None:
        try:
            search_input = self.query_one("#geo-search-input", Input)
            search_input.disabled = False
            search_input.remove_class("hidden")
            search_input.focus()
        except Exception:
            pass

    def _hide_search(self) -> None:
        """Hide search bar and clear filter (Y13 fix)."""
        try:
            search_input = self.query_one("#geo-search-input", Input)
            search_input.add_class("hidden")
            search_input.disabled = True
            # Clear filter when search is dismissed
            search_input.value = ""
        except Exception:
            pass
        self._filter_text = ""
        if self._connections:
            self._update_table(self._connections)

    def action_cycle_sort(self) -> None:
        self._sort_index = (self._sort_index + 1) % len(_SORT_COLUMNS)
        if self._sort_index == 0:
            self._sort_reverse = not self._sort_reverse

        label = _SORT_LABELS[self._sort_index]
        direction = "▼" if self._sort_reverse else "▲"

        # Update header to show sort indicator
        try:
            header = self.query_one("#map-header", Static)
            countries = self._geo_stats.get("countries_count", 0)
            unique_ips = len({c["ip"] for c in self._connections})
            total = len(self._connections)
            header.update(
                f"[bold]Connection Map[/]  |  "
                f"{total} connections  |  "
                f"{unique_ips} unique IPs  |  "
                f"{countries} countries  |  "
                f"Sort: [bold]{label}[/] {direction}  |  "
                f"[dim]</>/ filter  <o> sort  <m> map toggle  <Esc> back[/dim]"
            )
        except Exception:
            pass

        self.app.notify(f"Sort: {label} {direction}", severity="information")
        self._update_table(self._connections)

    def action_copy_row(self) -> None:
        """Copy the selected row's geo info to the system clipboard."""
        table = self.query_one("#geo-table", DataTable)
        try:
            if table.row_count > 0 and table.cursor_row is not None:
                row = table.get_row_at(table.cursor_row)
                parts = [str(c) for c in row]
                safe_copy_to_clipboard(self.app, " | ".join(parts))
            else:
                self.app.notify("No row selected", severity="warning")
        except Exception as e:
            self.app.notify(f"Copy failed: {e}", severity="error")
