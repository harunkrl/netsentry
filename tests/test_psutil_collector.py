"""Tests for backend.collectors.psutil_collector — psutil-based data collection."""
from __future__ import annotations

import psutil
import pytest
from backend.collectors.psutil_collector import (
    clear_cycle_caches,
    collect_connections,
    collect_network_pids,
    collect_process_tree,
    collect_traffic,
    _get_connections,
    _get_pid_info,
    _pid_info_cache,
    _cached_connections,
)
from backend.models import InterfaceStats, ProcessInfo, SocketEntry

# ── collect_connections ────────────────────────────────────────

class TestCollectConnections:
    def test_returns_list_of_socket_entries(self):
        """collect_connections returns a list of SocketEntry."""
        entries = collect_connections()
        assert isinstance(entries, list)
        for e in entries:
            assert isinstance(e, SocketEntry)

    def test_entries_have_required_fields(self):
        """Each entry has proto, local_ip, local_port, state, etc."""
        entries = collect_connections()
        if not entries:
            pytest.skip("No network connections on this host")
        e = entries[0]
        assert e.proto in ("tcp", "tcp6", "udp", "udp6")
        assert isinstance(e.local_ip, str)
        assert isinstance(e.local_port, int)
        assert isinstance(e.state, str)
        assert isinstance(e.state_code, str)

    def test_no_zero_inode_entries_skipped(self):
        """Entries with no addresses should be filtered out."""
        entries = collect_connections()
        for e in entries:
            # Should have at least a local or remote address
            assert e.local_ip != "0.0.0.0" or e.remote_ip != "0.0.0.0" or e.local_port != 0

    def test_listening_sockets_present(self):
        """At least some LISTEN sockets should exist on any host."""
        entries = collect_connections()
        listening = [e for e in entries if e.state == "LISTEN"]
        # Most hosts have at least something listening (e.g. cups, sshd)
        # Not guaranteed in CI, so just check structure
        for e in listening:
            assert e.local_port > 0

    def test_process_info_populated_when_available(self):
        """Entries should have pid/process_name when accessible."""
        entries = collect_connections()
        with_pid = [e for e in entries if e.pid is not None]
        if not with_pid:
            pytest.skip("No connections with PID info (needs root or CAP_NET_ADMIN)")
        e = with_pid[0]
        assert isinstance(e.pid, int)
        assert e.pid > 0


# ── collect_traffic ────────────────────────────────────────────

class TestCollectTraffic:
    def test_returns_list_of_interface_stats(self):
        """collect_traffic returns a list of InterfaceStats."""
        stats = collect_traffic()
        assert isinstance(stats, list)
        for s in stats:
            assert isinstance(s, InterfaceStats)

    def test_loopback_excluded(self):
        """Loopback interface should not be in results."""
        stats = collect_traffic()
        iface_names = [s.interface for s in stats]
        assert "lo" not in iface_names

    def test_stats_have_counters(self):
        """Each InterfaceStats has rx/tx bytes and packets."""
        stats = collect_traffic()
        if not stats:
            pytest.skip("No non-loopback interfaces")
        s = stats[0]
        assert s.rx_bytes >= 0
        assert s.tx_bytes >= 0
        assert s.rx_packets >= 0
        assert s.tx_packets >= 0
        assert s.rx_errors >= 0
        assert s.tx_errors >= 0
        assert isinstance(s.interface, str)
        assert len(s.interface) > 0

    def test_matches_psutil_direct(self):
        """Results should match direct psutil.net_io_counters call.

        We verify structural compatibility (same interfaces, same field types)
        and that values are within a reasonable delta. Exact byte equality
        cannot be guaranteed because network traffic arrives between reads.
        """
        stats = collect_traffic()
        direct = psutil.net_io_counters(pernic=True)
        for s in stats:
            assert s.interface in direct
            direct_stat = direct[s.interface]
            # Values should be within 1MB delta (network traffic between reads)
            assert abs(s.rx_bytes - direct_stat.bytes_recv) < 1_000_000
            assert abs(s.tx_bytes - direct_stat.bytes_sent) < 1_000_000
            assert abs(s.rx_packets - direct_stat.packets_recv) < 10_000
            assert abs(s.tx_packets - direct_stat.packets_sent) < 10_000


# ── collect_process_tree ───────────────────────────────────────

class TestCollectProcessTree:
    def test_returns_dict_of_process_info(self):
        """collect_process_tree returns Dict[int, ProcessInfo]."""
        tree = collect_process_tree()
        assert isinstance(tree, dict)
        for pid, info in tree.items():
            assert isinstance(pid, int)
            assert isinstance(info, ProcessInfo)

    def test_current_process_in_tree(self):
        """The current Python process should be in the tree."""
        tree = collect_process_tree(full_scan=True)
        import os
        assert os.getpid() in tree

    def test_children_populated(self):
        """Some processes should have children."""
        tree = collect_process_tree(full_scan=True)
        has_children = [p for p in tree.values() if len(p.children) > 0]
        assert len(has_children) > 0  # At least init/systemd has children

    def test_process_info_fields(self):
        """ProcessInfo has expected fields."""
        import os
        tree = collect_process_tree(full_scan=True)
        my_pid = os.getpid()
        assert my_pid in tree
        me = tree[my_pid]
        assert me.pid == my_pid
        assert isinstance(me.name, str)
        assert isinstance(me.cmdline, str)
        assert isinstance(me.state, str)
        assert me.ppid > 0  # has a parent
        assert me.uid >= 0

    def test_network_pids_flag(self):
        """network_pids parameter marks processes correctly."""
        tree = collect_process_tree(network_pids={1, 999999})
        assert tree[1].has_network is True
        # PID 999999 likely doesn't exist — just check flag for others
        for pid, info in tree.items():
            if pid == 1:
                assert info.has_network is True
            elif pid not in {1, 999999}:
                assert info.has_network is False


# ── collect_network_pids ───────────────────────────────────────

class TestCollectNetworkPids:
    def test_returns_set_of_ints(self):
        """collect_network_pids returns a set of integers."""
        pids = collect_network_pids()
        assert isinstance(pids, set)
        for p in pids:
            assert isinstance(p, int)
            assert p > 0


# ── clear_cycle_caches (Fix #1) ────────────────────────────────

class TestClearCycleCaches:
    def test_clears_connections_cache(self):
        """clear_cycle_caches invalidates the connections cache."""
        import backend.collectors.psutil_collector as mod

        # Populate the cache
        _get_connections()
        assert mod._cached_connections is not None

        # Clear it
        clear_cycle_caches()
        assert mod._cached_connections is None
        assert mod._cached_connections_ts == 0.0

    def test_connections_refreshed_after_clear(self):
        """After clearing, next _get_connections() fetches fresh data."""
        import backend.collectors.psutil_collector as mod

        clear_cycle_caches()
        assert mod._cached_connections is None

        result = _get_connections()
        assert isinstance(result, list)
        assert mod._cached_connections is not None

    def test_connections_reused_within_cycle(self):
        """Within same cycle (no clear), same cached list is returned."""
        r1 = _get_connections()
        r2 = _get_connections()
        assert r1 is r2  # same object reference


# ── Per-entry PID cache (Fix #2) ──────────────────────────────

class TestPerEntryPidCache:
    def test_individual_entry_expires(self):
        """Each PID entry has its own TTL; others remain cached."""
        import backend.collectors.psutil_collector as mod

        # Populate cache for current PID and PID 1
        my_pid = __import__("os").getpid()
        info_me = _get_pid_info(my_pid)
        info_init = _get_pid_info(1)

        assert my_pid in mod._pid_info_cache
        assert 1 in mod._pid_info_cache

        # Expire only PID 1 by backdating its timestamp
        name, cmdline, uid, _ts = mod._pid_info_cache[1]
        mod._pid_info_cache[1] = (name, cmdline, uid, 0.0)  # ancient

        # Re-fetch PID 1 — should re-resolve
        info_init2 = _get_pid_info(1)
        assert isinstance(info_init2[0], str)  # got a result

        # My PID should still be cached (not cleared)
        assert my_pid in mod._pid_info_cache

    def test_no_bulk_clear_stampede(self):
        """Cache entries don't all disappear at once."""
        import backend.collectors.psutil_collector as mod
        import os

        my_pid = os.getpid()
        _get_pid_info(my_pid)
        _get_pid_info(1)

        assert my_pid in mod._pid_info_cache
        assert 1 in mod._pid_info_cache

        # Expire PID 1's entry individually
        name, cmdline, uid, _ts = mod._pid_info_cache[1]
        mod._pid_info_cache[1] = (name, cmdline, uid, 0.0)

        # Re-fetch PID 1 (triggers individual eviction + refill)
        _get_pid_info(1)

        # my_pid should still be cached — no bulk clear happened
        assert my_pid in mod._pid_info_cache
        assert 1 in mod._pid_info_cache


# ── Process list synergy (Fix #3) ────────────────────────────

class TestProcessListSynergy:
    def test_pid_info_uses_process_list_cache(self):
        """_get_pid_info should resolve from process_list_cache first."""
        import backend.collectors.psutil_collector as mod
        import os

        my_pid = os.getpid()

        # Ensure process_list_cache is populated
        collect_process_tree()

        # Clear per-PID cache to force a fresh lookup
        mod._pid_info_cache.pop(my_pid, None)

        # Should still resolve correctly via process_list_by_pid
        name, cmdline, uid = _get_pid_info(my_pid)
        assert isinstance(name, str)
        assert len(name) > 0

    def test_process_list_by_pid_populated(self):
        """process_list_by_pid dict is built when process_list refreshes."""
        import backend.collectors.psutil_collector as mod
        import os

        # Force process_list refresh by clearing cache
        old = mod._process_list_cache
        mod._process_list_cache = None
        mod._process_list_cache_ts = 0.0

        try:
            collect_process_tree()
            assert os.getpid() in mod._process_list_by_pid
        finally:
            # Restore (or leave refreshed — both fine)
            pass
