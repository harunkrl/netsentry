"""Tests for /proc/net/dev parser and InterfaceStats model."""
from __future__ import annotations

import json
from dataclasses import asdict

from backend.models import InterfaceStats, Snapshot
from backend.parsers.net_dev import parse_proc_net_dev

# ── Parser tests ───────────────────────────────────────────────

class TestParseProcNetDev:
    """Tests for parse_proc_net_dev()."""

    def test_parse_valid_content(
        self,
        tmp_path,
        proc_net_dev_content,
    ):
        """Parse realistic /proc/net/dev content — should return 2 interfaces (skip lo)."""
        dev_file = tmp_path / "dev"
        dev_file.write_text(proc_net_dev_content)

        result = parse_proc_net_dev(str(dev_file))
        assert len(result) == 2

        # wlan0
        wlan = result[0]
        assert wlan.interface == "wlan0"
        assert wlan.rx_bytes == 1493759338
        assert wlan.tx_bytes == 201984858
        assert wlan.rx_packets == 1197161
        assert wlan.tx_packets == 354400
        assert wlan.rx_errors == 0
        assert wlan.tx_errors == 0
        assert wlan.rx_drops == 0
        assert wlan.tx_drops == 39
        assert wlan.rx_rate == 0.0  # not computed by parser
        assert wlan.tx_rate == 0.0

        # eth0
        eth = result[1]
        assert eth.interface == "eth0"
        assert eth.rx_bytes == 500000000
        assert eth.tx_bytes == 300000000
        assert eth.rx_errors == 1
        assert eth.tx_errors == 3
        assert eth.rx_drops == 2
        assert eth.tx_drops == 4

    def test_skip_loopback(
        self,
        tmp_path,
        proc_net_dev_content,
    ):
        """Loopback interface (lo) should be excluded."""
        dev_file = tmp_path / "dev"
        dev_file.write_text(proc_net_dev_content)

        result = parse_proc_net_dev(str(dev_file))
        names = [s.interface for s in result]
        assert "lo" not in names
        assert "wlan0" in names
        assert "eth0" in names

    def test_missing_file(self, tmp_path):
        """Non-existent file should return empty list."""
        result = parse_proc_net_dev(str(tmp_path / "nonexistent"))
        assert result == []

    def test_empty_file(self, tmp_path):
        """Empty file should return empty list."""
        dev_file = tmp_path / "dev"
        dev_file.write_text("")
        result = parse_proc_net_dev(str(dev_file))
        assert result == []

    def test_header_only(self, tmp_path):
        """File with only headers (no data lines) should return empty list."""
        dev_file = tmp_path / "dev"
        dev_file.write_text(
            "Inter-|   Receive                                                |  Transmit\n"
            " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
        )
        result = parse_proc_net_dev(str(dev_file))
        assert result == []

    def test_malformed_line_skipped(self, tmp_path):
        """Lines with fewer than 16 counters should be skipped."""
        dev_file = tmp_path / "dev"
        dev_file.write_text(
            "Inter-|   Receive                                                |  Transmit\n"
            " face |bytes    packets errs drop fifo frame compressed multicast|bytes    packets errs drop fifo colls carrier compressed\n"
            "  bad0: 100 200\n"  # only 2 counters — malformed
            "  eth0: 1000 2000 0 0 0 0 0 0 500 1000 0 0 0 0 0 0\n"
        )
        result = parse_proc_net_dev(str(dev_file))
        assert len(result) == 1
        assert result[0].interface == "eth0"


# ── Model tests ────────────────────────────────────────────────

class TestInterfaceStats:
    """Tests for InterfaceStats dataclass."""

    def test_from_dict(self, sample_interface_stats):
        """InterfaceStats.from_dict should reconstruct correctly."""
        d = asdict(sample_interface_stats)
        restored = InterfaceStats.from_dict(d)
        assert restored == sample_interface_stats

    def test_from_dict_ignores_extra_keys(self, sample_interface_stats):
        """Extra keys in dict should be silently ignored."""
        d = asdict(sample_interface_stats)
        d["extra_field"] = "ignored"
        restored = InterfaceStats.from_dict(d)
        assert restored == sample_interface_stats

    def test_default_rates(self):
        """Newly created InterfaceStats should have zero rates."""
        stats = InterfaceStats(
            interface="eth0",
            rx_bytes=100, tx_bytes=200,
            rx_packets=10, tx_packets=20,
            rx_errors=0, tx_errors=0,
            rx_drops=0, tx_drops=0,
        )
        assert stats.rx_rate == 0.0
        assert stats.tx_rate == 0.0


class TestSnapshotTraffic:
    """Tests for Snapshot serialization with traffic data."""

    def test_snapshot_with_traffic(self, sample_snapshot, sample_interface_stats):
        """Snapshot.to_dict / from_dict should preserve traffic data."""
        sample_snapshot.traffic = {"wlan0": sample_interface_stats}

        d = sample_snapshot.to_dict()
        assert "traffic" in d
        assert "wlan0" in d["traffic"]
        assert d["traffic"]["wlan0"]["rx_bytes"] == 1493759338
        assert d["traffic"]["wlan0"]["rx_rate"] == 1024.0

        # Round-trip
        json_str = sample_snapshot.to_json()
        restored = Snapshot.from_json(json_str)
        assert "wlan0" in restored.traffic
        assert restored.traffic["wlan0"].rx_bytes == 1493759338
        assert restored.traffic["wlan0"].rx_rate == 1024.0

    def test_snapshot_without_traffic(self, sample_snapshot):
        """Snapshot with empty traffic dict should serialize/deserialize correctly."""
        sample_snapshot.traffic = {}

        d = sample_snapshot.to_dict()
        assert d["traffic"] == {}

        restored = Snapshot.from_dict(d)
        assert restored.traffic == {}

    def test_snapshot_json_round_trip(self, sample_snapshot, sample_interface_stats):
        """Full JSON round-trip: to_json → from_json should preserve all traffic data."""
        eth_stats = InterfaceStats(
            interface="eth0",
            rx_bytes=500000000, tx_bytes=300000000,
            rx_packets=800000, tx_packets=600000,
            rx_errors=1, tx_errors=3,
            rx_drops=2, tx_drops=4,
            rx_rate=5000.0, tx_rate=3000.0,
        )
        sample_snapshot.traffic = {
            "wlan0": sample_interface_stats,
            "eth0": eth_stats,
        }

        raw = sample_snapshot.to_json()
        parsed = json.loads(raw)
        assert len(parsed["traffic"]) == 2

        restored = Snapshot.from_json(raw)
        assert len(restored.traffic) == 2
        assert restored.traffic["eth0"].rx_rate == 5000.0
        assert restored.traffic["wlan0"].tx_rate == 512.0


# ── Delta computation tests ────────────────────────────────────

class TestDeltaComputation:
    """Tests for traffic rate delta computation logic."""

    def test_basic_delta(self):
        """Rate should be (current - prev) / elapsed."""
        from backend.kportwatch_daemon import compute_traffic_deltas

        prev: dict[str, tuple[float, InterfaceStats]] = {
            "wlan0": (100.0, InterfaceStats(
                interface="wlan0",
                rx_bytes=1000000, tx_bytes=500000,
                rx_packets=1000, tx_packets=500,
                rx_errors=0, tx_errors=0,
                rx_drops=0, tx_drops=0,
            )),
        }

        current = [
            InterfaceStats(
                interface="wlan0",
                rx_bytes=2000000, tx_bytes=600000,
                rx_packets=2000, tx_packets=600,
                rx_errors=0, tx_errors=0,
                rx_drops=0, tx_drops=0,
            ),
        ]

        result = compute_traffic_deltas(current, prev, now=102.0)
        assert "wlan0" in result
        # rx: (2_000_000 - 1_000_000) / 2.0 = 500_000 bytes/sec
        assert result["wlan0"].rx_rate == 500000.0
        # tx: (600_000 - 500_000) / 2.0 = 50_000 bytes/sec
        assert result["wlan0"].tx_rate == 50000.0

    def test_no_previous_data(self):
        """With no previous data, rates should be 0."""
        from backend.kportwatch_daemon import compute_traffic_deltas

        current = [
            InterfaceStats(
                interface="eth0",
                rx_bytes=1000, tx_bytes=2000,
                rx_packets=10, tx_packets=20,
                rx_errors=0, tx_errors=0,
                rx_drops=0, tx_drops=0,
            ),
        ]

        result = compute_traffic_deltas(current, {}, now=100.0)
        assert result["eth0"].rx_rate == 0.0
        assert result["eth0"].tx_rate == 0.0

    def test_zero_elapsed(self):
        """Zero elapsed time should not cause division by zero (rates = 0)."""
        from backend.kportwatch_daemon import compute_traffic_deltas

        prev = {
            "eth0": (100.0, InterfaceStats(
                interface="eth0",
                rx_bytes=1000, tx_bytes=2000,
                rx_packets=10, tx_packets=20,
                rx_errors=0, tx_errors=0,
                rx_drops=0, tx_drops=0,
            )),
        }

        current = [
            InterfaceStats(
                interface="eth0",
                rx_bytes=2000, tx_bytes=3000,
                rx_packets=20, tx_packets=30,
                rx_errors=0, tx_errors=0,
                rx_drops=0, tx_drops=0,
            ),
        ]

        # Same timestamp — elapsed = 0
        result = compute_traffic_deltas(current, prev, now=100.0)
        # max(0, delta/0) — should be 0 because elapsed <= 0 guard
        assert result["eth0"].rx_rate == 0.0

    def test_multiple_interfaces(self):
        """Delta computation should work independently for each interface."""
        from backend.kportwatch_daemon import compute_traffic_deltas

        prev = {
            "wlan0": (100.0, InterfaceStats(
                interface="wlan0",
                rx_bytes=1000, tx_bytes=2000,
                rx_packets=10, tx_packets=20,
                rx_errors=0, tx_errors=0,
                rx_drops=0, tx_drops=0,
            )),
            "eth0": (100.0, InterfaceStats(
                interface="eth0",
                rx_bytes=5000, tx_bytes=6000,
                rx_packets=50, tx_packets=60,
                rx_errors=0, tx_errors=0,
                rx_drops=0, tx_drops=0,
            )),
        }

        current = [
            InterfaceStats(
                interface="wlan0",
                rx_bytes=3000, tx_bytes=4000,
                rx_packets=30, tx_packets=40,
                rx_errors=0, tx_errors=0,
                rx_drops=0, tx_drops=0,
            ),
            InterfaceStats(
                interface="eth0",
                rx_bytes=7000, tx_bytes=8000,
                rx_packets=70, tx_packets=80,
                rx_errors=0, tx_errors=0,
                rx_drops=0, tx_drops=0,
            ),
        ]

        result = compute_traffic_deltas(current, prev, now=102.0)
        # wlan0: (3000-1000)/2 = 1000, (4000-2000)/2 = 1000
        assert result["wlan0"].rx_rate == 1000.0
        assert result["wlan0"].tx_rate == 1000.0
        # eth0: (7000-5000)/2 = 1000, (8000-6000)/2 = 1000
        assert result["eth0"].rx_rate == 1000.0
        assert result["eth0"].tx_rate == 1000.0
