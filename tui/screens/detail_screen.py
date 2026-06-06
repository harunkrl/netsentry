"""NetSentry TUI — Detail screen.

Shows structured key-value view of a single connection entry with
full detail including geo, risk, and alert information.

K3 fix: Replaces raw dict (Pretty) with a structured key-value layout.
D3: Added ``c`` binding to copy connection info to clipboard.
D8: Only Escape closes the screen (not any key).
"""
from __future__ import annotations

import time
from datetime import datetime

from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.containers import VerticalScroll, Vertical
from textual.widgets import Header, Footer, Label, Static, Rule

from backend.models import SocketEntry


import time as _time_mod


def _format_duration(seconds: float) -> str:
    """Ö1: Format elapsed seconds as human-readable duration."""
    if seconds < 0:
        return "—"
    days = int(seconds // 86400)
    hours = int((seconds % 86400) // 3600)
    mins = int((seconds % 3600) // 60)
    secs = int(seconds % 60)
    parts = []
    if days:
        parts.append(f"{days}d")
    if hours:
        parts.append(f"{hours}h")
    if mins:
        parts.append(f"{mins}m")
    parts.append(f"{secs}s")
    return " ".join(parts)


def _format_time(ts: float) -> str:
    """Format epoch timestamp as HH:MM:SS."""
    from datetime import datetime
    return datetime.fromtimestamp(ts).strftime("%H:%M:%S")


class DetailScreen(Screen):
    """Screen displaying full details of a specific connection.

    Shows a structured key-value layout instead of a raw dict dump.
    Supports Escape to close and ``c`` to copy connection info.
    """

    BINDINGS = [
        Binding("escape", "app.pop_screen", "Back", show=True),
        Binding("c", "copy_info", "Copy", show=True),
    ]

    CSS = """
    DetailScreen {
        layout: vertical;
    }
    #detail-container {
        margin: 1 2;
        padding: 1 2;
        border: round #008855;
        background: $panel-bg;
    }
    .detail-section-title {
        color: #00ff99;
        text-style: bold;
        margin: 1 0 0 0;
    }
    #detail-footer {
        dock: bottom;
        height: 1;
        padding: 0 2;
        color: #6a6a7a;
    }
    """

    def __init__(self, entry: SocketEntry, **kwargs) -> None:
        super().__init__(**kwargs)
        self.entry = entry

    def compose(self) -> ComposeResult:
        """Structured detail layout with sections for Connection, Network, Geo, Security."""
        entry = self.entry

        yield Header(show_clock=True)
        with VerticalScroll(id="detail-container"):
            proc = entry.process_name or "unknown"
            pid = str(entry.pid) if entry.pid else "—"
            cmdline = entry.cmdline or "—"

            yield Static("[bold #00ff99]CONNECTION DETAILS[/]")
            yield Rule()

            yield from self._make_kv_rows([
                ("Process", proc),
                ("PID", pid),
                ("Cmdline", cmdline),
                ("User ID", str(entry.uid)),
            ])

            yield Static("")
            yield Static("[bold #00ff99]NETWORK[/]")
            yield Rule()

            remote_display = f"{entry.remote_ip}:{entry.remote_port}"
            if entry.remote_hostname:
                remote_display += f"  ({entry.remote_hostname})"

            yield from self._make_kv_rows([
                ("Protocol", entry.proto.upper()),
                ("Local", f"{entry.local_ip}:{entry.local_port}"),
                ("Remote", remote_display),
                ("State", entry.state),
                ("Inode", str(entry.inode)),
            ])

            # Ö1: Connection duration
            first_seen = getattr(entry, "first_seen", None)
            if first_seen and first_seen > 0:
                elapsed = time.time() - first_seen
                dur = _format_duration(elapsed)
                yield Static("")
                yield Static("[bold #00ff99]DURATION[/]")
                yield Rule()
                yield from self._make_kv_rows([
                    ("First Seen", f"{_format_time(first_seen)}"),
                    ("Duration", f"[bold]{dur}[/]"),
                ])

            # Geo information — use SocketEntry's direct geo fields + live lookup
            geo_country = entry.remote_country or ""
            geo_city = entry.remote_city or ""
            geo_org = entry.remote_org or entry.remote_isp or ""
            geo_code = entry.remote_country_code or ""
            geo_lat = entry.remote_lat
            geo_lon = entry.remote_lon

            # If no geo data on the entry, try a live lookup
            if not geo_country and entry.remote_ip:
                try:
                    from backend.parsers.geoip import get_geoip
                    geo = get_geoip(entry.remote_ip)
                    if geo:
                        geo_country = geo.get("country", "")
                        geo_city = geo.get("city", "")
                        geo_org = geo.get("org", "") or geo.get("isp", "")
                        geo_code = geo.get("countryCode", "")
                        geo_lat = geo.get("lat")
                        geo_lon = geo.get("lon")
                except Exception:
                    pass

            if any([geo_country, geo_city, geo_org]):
                yield Static("")
                yield Static("[bold #00ff99]GEOLOCATION[/]")
                yield Rule()
                geo_rows = []
                if geo_country:
                    flag = f"  ({geo_code})" if geo_code else ""
                    geo_rows.append(("Country", f"{geo_country}{flag}"))
                if geo_city:
                    geo_rows.append(("City", geo_city))
                if geo_org:
                    geo_rows.append(("Organization", geo_org))
                if geo_lat is not None and geo_lon is not None:
                    geo_rows.append(("Coordinates", f"{geo_lat:.4f}, {geo_lon:.4f}"))
                yield from self._make_kv_rows(geo_rows)

            # Risk / Alert info
            risk_score = getattr(entry, "risk_score", None)
            alert_details = getattr(entry, "alert_details", None)
            if risk_score is not None or alert_details:
                yield Static("")
                yield Static("[bold #00ff99]SECURITY[/]")
                yield Rule()
                sec_rows = []
                if risk_score is not None:
                    try:
                        rs = float(risk_score)
                    except (ValueError, TypeError):
                        rs = 0.0
                    if rs >= 0.7:
                        color = "bold red"
                    elif rs >= 0.4:
                        color = "bold yellow"
                    else:
                        color = "bold green"
                    # Ö3: Mini risk bar visualization
                    bar_filled = int(rs * 20)
                    bar_empty = 20 - bar_filled
                    bar_visual = f"[{color}]{'█' * bar_filled}{'░' * bar_empty}[/]"
                    sec_rows.append(("Risk Score", f"[{color}]{rs:.2f}[/]  {bar_visual}"))
                if alert_details:
                    sec_rows.append(("Alert", str(alert_details)))
                yield from self._make_kv_rows(sec_rows)

        with Vertical(id="detail-footer"):
            yield Label("[dim][Esc] Back  [c] Copy connection info[/]")
        yield Footer()

    @staticmethod
    def _make_kv_rows(pairs: list[tuple[str, str]]) -> ComposeResult:
        """Yield Static widgets for key-value pairs."""
        for key, value in pairs:
            yield Static(
                f"  [bold #00cc88]{key:<14}[/]  {value}"
            )

    def action_copy_info(self) -> None:
        """Copy connection details to the clipboard."""
        e = self.entry
        proc = e.process_name or "unknown"
        pid = e.pid or "—"
        lines = [
            f"Process: {proc}",
            f"PID: {pid}",
            f"Protocol: {e.proto.upper()}",
            f"Local: {e.local_ip}:{e.local_port}",
            f"Remote: {e.remote_ip}:{e.remote_port}",
            f"State: {e.state}",
        ]
        if e.remote_hostname:
            lines.append(f"Hostname: {e.remote_hostname}")
        if e.cmdline:
            lines.append(f"Cmdline: {e.cmdline}")
        text = "\n".join(lines)
        try:
            self.app.copy_to_clipboard(text)
            self.app.notify("Connection info copied to clipboard", severity="information")
        except Exception:
            self.app.notify("Clipboard unavailable — install xclip or xsel", severity="warning")
