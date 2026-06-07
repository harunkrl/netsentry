"""KPortWatch — Data collection layer.

Gathers socket entries, resolves PIDs, builds process trees, enriches
connections with rDNS/GeoIP data, and collects interface traffic stats.

Fully self-contained: owns its own ``_prev_traffic`` delta state.
Only external dependency is the config object injected at construction.
"""
from __future__ import annotations

import logging
import time
from dataclasses import dataclass, field

from shared.network import is_private_ip

from backend.kportwatch_daemon import classify_entries
from backend.models import InterfaceStats
from backend.parsers import geoip as geoip_mod
from backend.parsers.inode_map import build_inode_to_pid_map, build_uid_process_map
from backend.parsers.net_dev import parse_proc_net_dev
from backend.parsers.proc_net import parse_all_proc
from backend.parsers.process_tree import build_process_tree
from backend.parsers.rdns import get_hostname

# psutil-based collectors (preferred, with /proc fallback)
try:
    import psutil as _psutil  # noqa: F401 — checked at runtime

    _HAS_PSUTIL = True
    from backend.collectors.psutil_collector import (
        collect_connections as _psutil_connections,
    )
    from backend.collectors.psutil_collector import (
        collect_network_pids as _psutil_network_pids,
    )
    from backend.collectors.psutil_collector import (
        collect_process_tree as _psutil_process_tree,
    )
    from backend.collectors.psutil_collector import (
        collect_traffic as _psutil_traffic,
    )
except ImportError:
    _HAS_PSUTIL = False
    _psutil_connections = None
    _psutil_network_pids = None
    _psutil_process_tree = None
    _psutil_traffic = None

logger = logging.getLogger(__name__)


# ── Data types ────────────────────────────────────────────────


@dataclass(frozen=True)
class CollectedData:
    """Structured result of a single collection cycle."""

    listening: list = field(default_factory=list)
    established: list = field(default_factory=list)
    process_tree: dict = field(default_factory=dict)
    traffic: dict = field(default_factory=dict)


# ── Collector ─────────────────────────────────────────────────


class DataCollector:
    """Collect network data from psutil or /proc, enrich, and return
    a :class:`CollectedData` snapshot each cycle.
    """

    def __init__(self, cfg) -> None:
        self._cfg = cfg
        self._prev_traffic: dict[str, tuple[float, InterfaceStats]] = {}

    def reconfigure(self, cfg) -> None:
        """Apply a new config (e.g. after SIGHUP)."""
        self._cfg = cfg

    # ── Public API ────────────────────────────────────────────

    def collect(self) -> CollectedData:
        """Run a full collection cycle and return structured results."""
        entries, inode_map = self._collect_entries()
        process_tree = self._build_tree(inode_map)
        listening, established = classify_entries(entries)
        self._enrich_connections(established)
        traffic = self._collect_traffic()
        return CollectedData(
            listening=listening,
            established=established,
            process_tree=process_tree,
            traffic=traffic,
        )

    # ── Private helpers ───────────────────────────────────────

    def _collect_entries(self) -> tuple[list, dict | None]:
        """Collect socket entries. Returns (entries, inode_map_or_None)."""
        inode_map = None
        if _HAS_PSUTIL:
            entries = _psutil_connections()
            logger.debug("Collected %d socket entries via psutil", len(entries))
        else:
            entries = parse_all_proc()
            logger.debug("Parsed %d socket entries via /proc", len(entries))

        # Resolve PIDs (only needed for /proc path or missing PIDs)
        if not _HAS_PSUTIL or any(e.pid is None for e in entries):
            inode_map = build_inode_to_pid_map()
            uid_map = build_uid_process_map()
            for entry in entries:
                if entry.pid is None:
                    info = inode_map.get(entry.inode)
                    if info:
                        pid, proc_name, cmdline = info
                        entry.pid = pid
                        entry.process_name = proc_name
                        entry.cmdline = cmdline
                    elif entry.uid in uid_map:
                        username, proc_name, cmdline = uid_map[entry.uid]
                        entry.process_name = f"{proc_name} ({username})"
                        entry.cmdline = cmdline

        return entries, inode_map

    def _build_tree(self, inode_map: dict | None) -> dict:
        """Build process tree, reusing inode_map if available."""
        if _HAS_PSUTIL:
            network_pids = _psutil_network_pids()
            return _psutil_process_tree(network_pids)
        if inode_map is None:
            inode_map = build_inode_to_pid_map()
        return build_process_tree(inode_map)

    def _enrich_connections(self, established: list) -> None:
        """rDNS + GeoIP enrichment for remote IPs."""
        for e in established:
            if e.remote_ip and not is_private_ip(e.remote_ip):
                e.remote_hostname = get_hostname(e.remote_ip)

        if not self._cfg.geoip_enabled:
            return

        unique_ips = {
            e.remote_ip
            for e in established
            if e.remote_ip and not is_private_ip(e.remote_ip)
        }
        if not unique_ips:
            return

        geo_results = geoip_mod.lookup_batch(list(unique_ips))
        for e in established:
            geo = geo_results.get(e.remote_ip)
            if geo:
                e.remote_country = geo.get("country")
                e.remote_country_code = geo.get("countryCode")
                e.remote_city = geo.get("city")
                e.remote_lat = geo.get("lat")
                e.remote_lon = geo.get("lon")
                e.remote_isp = geo.get("isp")
                e.remote_org = geo.get("org")

    def _collect_traffic(self) -> dict[str, InterfaceStats]:
        """Collect interface stats with rate computation."""
        now_ts = time.time()
        raw = _psutil_traffic() if _HAS_PSUTIL else parse_proc_net_dev()
        traffic: dict[str, InterfaceStats] = {}
        for stats in raw:
            if stats.interface in self._prev_traffic:
                prev_ts, prev_stats = self._prev_traffic[stats.interface]
                elapsed = now_ts - prev_ts
                if elapsed > 0:
                    stats.rx_rate = max(
                        0, (stats.rx_bytes - prev_stats.rx_bytes) / elapsed
                    )
                    stats.tx_rate = max(
                        0, (stats.tx_bytes - prev_stats.tx_bytes) / elapsed
                    )
            traffic[stats.interface] = stats

        # Store for next cycle
        self._prev_traffic = {
            name: (
                now_ts,
                InterfaceStats(
                    interface=s.interface,
                    rx_bytes=s.rx_bytes,
                    tx_bytes=s.tx_bytes,
                    rx_packets=s.rx_packets,
                    tx_packets=s.tx_packets,
                    rx_errors=s.rx_errors,
                    tx_errors=s.tx_errors,
                    rx_drops=s.rx_drops,
                    tx_drops=s.tx_drops,
                ),
            )
            for name, s in traffic.items()
        }
        return traffic
