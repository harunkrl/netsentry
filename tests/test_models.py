"""KPortWatch — Tests for backend.models (SocketEntry, Alert, Snapshot)."""
import json
import time

import pytest

from backend.models import Alert, InterfaceStats, SocketEntry, Snapshot
from shared import AlertLevel


# ── SocketEntry ────────────────────────────────────────────────

class TestSocketEntry:
    def test_creation(self):
        """SocketEntry stores all fields correctly."""
        entry = SocketEntry(
            proto="tcp",
            local_ip="127.0.0.1",
            local_port=80,
            remote_ip="0.0.0.0",
            remote_port=0,
            state="LISTEN",
            state_code="0A",
            uid=0,
            inode=12345,
        )
        assert entry.proto == "tcp"
        assert entry.local_port == 80
        assert entry.pid is None
        assert entry.process_name is None
        assert entry.cmdline is None

    def test_from_dict_basic(self):
        """from_dict creates a SocketEntry from a flat dict."""
        d = {
            "proto": "tcp",
            "local_ip": "0.0.0.0",
            "local_port": 22,
            "remote_ip": "0.0.0.0",
            "remote_port": 0,
            "state": "LISTEN",
            "state_code": "0A",
            "uid": 1000,
            "inode": 54321,
            "pid": 1234,
            "process_name": "sshd",
            "cmdline": "/usr/sbin/sshd -D",
        }
        entry = SocketEntry.from_dict(d)
        assert entry.proto == "tcp"
        assert entry.local_port == 22
        assert entry.pid == 1234
        assert entry.cmdline == "/usr/sbin/sshd -D"

    def test_from_dict_extra_keys_ignored(self):
        """Extra keys in the dict should be silently ignored."""
        d = {
            "proto": "tcp",
            "local_ip": "0.0.0.0",
            "local_port": 22,
            "remote_ip": "0.0.0.0",
            "remote_port": 0,
            "state": "LISTEN",
            "state_code": "0A",
            "uid": 0,
            "inode": 99999,
            "extra_field": "should be ignored",
            "another_extra": 42,
        }
        entry = SocketEntry.from_dict(d)
        assert entry.local_port == 22
        assert not hasattr(entry, "extra_field")

    def test_from_dict_missing_optional_fields(self):
        """Missing optional fields (pid, process_name, cmdline) default to None."""
        d = {
            "proto": "udp",
            "local_ip": "0.0.0.0",
            "local_port": 53,
            "remote_ip": "0.0.0.0",
            "remote_port": 0,
            "state": "UNCONN",
            "state_code": "07",
            "uid": 0,
            "inode": 11111,
        }
        entry = SocketEntry.from_dict(d)
        assert entry.pid is None
        assert entry.process_name is None
        assert entry.cmdline is None

    def test_geo_fields_default_to_none(self):
        """GeoIP fields default to None when not provided."""
        entry = SocketEntry(
            proto="tcp", local_ip="0.0.0.0", local_port=80,
            remote_ip="0.0.0.0", remote_port=0, state="LISTEN",
            state_code="0A", uid=0, inode=12345,
        )
        assert entry.remote_country is None
        assert entry.remote_country_code is None
        assert entry.remote_city is None
        assert entry.remote_lat is None
        assert entry.remote_lon is None

    def test_geo_fields_from_dict(self):
        """GeoIP fields are correctly deserialized from dict."""
        d = {
            "proto": "tcp", "local_ip": "192.168.1.10", "local_port": 54321,
            "remote_ip": "8.8.8.8", "remote_port": 443, "state": "ESTABLISHED",
            "state_code": "01", "uid": 1000, "inode": 99999,
            "remote_country": "United States",
            "remote_country_code": "US",
            "remote_city": "Mountain View",
            "remote_lat": 37.386,
            "remote_lon": -122.084,
        }
        entry = SocketEntry.from_dict(d)
        assert entry.remote_country == "United States"
        assert entry.remote_country_code == "US"
        assert entry.remote_city == "Mountain View"
        assert entry.remote_lat == 37.386
        assert entry.remote_lon == -122.084

    def test_geo_fields_in_to_dict(self, sample_geo_entry):
        """GeoIP fields are included in asdict() serialization."""
        from dataclasses import asdict
        d = asdict(sample_geo_entry)
        assert d["remote_country"] == "United States"
        assert d["remote_country_code"] == "US"
        assert d["remote_city"] == "Mountain View"
        assert d["remote_lat"] == 37.386
        assert d["remote_lon"] == -122.084


# ── Alert ──────────────────────────────────────────────────────

class TestAlert:
    def test_creation(self):
        """Alert stores all fields correctly."""
        alert = Alert(
            level=AlertLevel.CRITICAL,
            port=4444,
            proto="tcp",
            process_name="evil",
            pid=666,
            message="Malicious port detected",
            timestamp=1700000000.0,
        )
        assert alert.level == AlertLevel.CRITICAL
        assert alert.port == 4444
        assert alert.message == "Malicious port detected"
        assert alert.timestamp == 1700000000.0

    def test_from_dict(self):
        """from_dict creates an Alert from a flat dict."""
        d = {
            "level": "WARNING",
            "port": 999,
            "proto": "tcp",
            "process_name": "unknown",
            "pid": 100,
            "message": "Unknown privileged port",
            "timestamp": 1700000000.0,
        }
        alert = Alert.from_dict(d)
        assert alert.level == "WARNING"
        assert alert.port == 999
        assert alert.message == "Unknown privileged port"

    def test_from_dict_extra_keys_ignored(self):
        """Extra keys should be silently ignored."""
        d = {
            "level": "INFO",
            "port": 8080,
            "proto": "tcp",
            "process_name": None,
            "pid": None,
            "message": "New port",
            "timestamp": 1700000000.0,
            "extra": "ignored",
        }
        alert = Alert.from_dict(d)
        assert alert.port == 8080

    def test_default_timestamp(self):
        """Alert without explicit timestamp gets one from time.time()."""
        before = time.time()
        alert = Alert(
            level="INFO",
            port=1,
            proto="tcp",
            process_name=None,
            pid=None,
            message="test",
        )
        after = time.time()
        assert before <= alert.timestamp <= after


# ── Snapshot ───────────────────────────────────────────────────

class TestSnapshot:
    def test_creation_defaults(self):
        """Default Snapshot has empty lists and a summary dict."""
        snap = Snapshot()
        assert snap.listening == []
        assert snap.established == []
        assert snap.alerts == []
        assert snap.summary == {"total_listening": 0, "total_established": 0, "alert_count": 0}
        assert snap.poll_interval_ms == 2000

    def test_to_dict(self, sample_snapshot):
        """to_dict produces a serialisable dict with nested dataclasses."""
        d = sample_snapshot.to_dict()
        assert d["timestamp"] == sample_snapshot.timestamp
        assert d["poll_interval_ms"] == 2000
        assert len(d["listening"]) == 2
        assert d["listening"][0]["local_port"] == 22
        assert d["listening"][1]["local_port"] == 80
        assert len(d["alerts"]) == 1
        assert d["alerts"][0]["port"] == 500
        assert d["summary"]["total_listening"] == 2
        assert "geo_stats" in d

    def test_from_dict_roundtrip(self, sample_snapshot):
        """Snapshot → to_dict → from_dict produces an equivalent Snapshot."""
        d = sample_snapshot.to_dict()
        restored = Snapshot.from_dict(d)

        assert restored.timestamp == sample_snapshot.timestamp
        assert restored.poll_interval_ms == sample_snapshot.poll_interval_ms
        assert len(restored.listening) == 2
        assert restored.listening[0].local_port == 22
        assert restored.listening[1].local_port == 80
        assert len(restored.established) == 1
        assert len(restored.alerts) == 1
        assert restored.alerts[0].port == 500
        assert restored.alerts[0].level == AlertLevel.WARNING
        assert restored.summary == sample_snapshot.summary

    def test_to_json_roundtrip(self, sample_snapshot):
        """Snapshot → to_json → from_json produces an equivalent Snapshot."""
        json_str = sample_snapshot.to_json()
        restored = Snapshot.from_json(json_str)

        assert restored.timestamp == sample_snapshot.timestamp
        assert len(restored.listening) == 2
        assert restored.listening[0].local_port == 22
        assert len(restored.alerts) == 1
        assert restored.alerts[0].port == 500

    def test_from_dict_missing_optional_keys_uses_defaults(self):
        """from_dict with missing keys uses sensible defaults."""
        d = {"timestamp": 1700000000.0}
        snap = Snapshot.from_dict(d)
        assert snap.timestamp == 1700000000.0
        assert snap.poll_interval_ms == 2000
        assert snap.listening == []
        assert snap.established == []
        assert snap.alerts == []
        assert snap.summary == {}

    def test_from_dict_with_empty_dict(self):
        """from_dict with an empty dict should use all defaults."""
        snap = Snapshot.from_dict({})
        assert snap.poll_interval_ms == 2000
        assert snap.listening == []
        assert snap.alerts == []

    def test_from_json_invalid_raises_value_error(self):
        """from_json with invalid JSON should raise ValueError."""
        with pytest.raises(ValueError):
            Snapshot.from_json("not valid json {{{")

    def test_to_json_produces_valid_json(self, sample_snapshot):
        """to_json output is valid JSON that can be parsed back."""
        json_str = sample_snapshot.to_json()
        parsed = json.loads(json_str)
        assert isinstance(parsed, dict)
        assert "listening" in parsed
        assert "alerts" in parsed
        assert "timestamp" in parsed

    def test_snapshot_with_multiple_entries(self):
        """Snapshot correctly handles multiple entries in each list."""
        entries = [
            SocketEntry(proto="tcp", local_ip="0.0.0.0", local_port=p,
                        remote_ip="0.0.0.0", remote_port=0, state="LISTEN",
                        state_code="0A", uid=0, inode=10000 + p)
            for p in [22, 80, 443]
        ]
        alerts = [
            Alert(level="INFO", port=22, proto="tcp", process_name="sshd",
                  pid=1, message="New port"),
        ]
        snap = Snapshot(
            timestamp=1700000000.0,
            listening=entries,
            alerts=alerts,
            summary={"total_listening": 3, "total_established": 0, "alert_count": 1},
        )
        d = snap.to_dict()
        assert len(d["listening"]) == 3
        ports = [e["local_port"] for e in d["listening"]]
        assert ports == [22, 80, 443]

        restored = Snapshot.from_dict(d)
        assert len(restored.listening) == 3
        assert [e.local_port for e in restored.listening] == [22, 80, 443]

    def test_geo_stats_default(self):
        """Default Snapshot has empty geo_stats."""
        snap = Snapshot()
        assert snap.geo_stats["countries_count"] == 0
        assert snap.geo_stats["unique_ips_per_country"] == {}
        assert snap.geo_stats["top_countries"] == []

    def test_geo_stats_to_dict(self):
        """geo_stats is included in to_dict()."""
        snap = Snapshot(geo_stats={
            "countries_count": 2,
            "unique_ips_per_country": {"US": 3, "DE": 1},
            "top_countries": [("US", 3), ("DE", 1)],
        })
        d = snap.to_dict()
        assert d["geo_stats"]["countries_count"] == 2
        assert d["geo_stats"]["unique_ips_per_country"]["US"] == 3

    def test_geo_stats_from_dict_roundtrip(self):
        """geo_stats survives to_dict → from_dict roundtrip."""
        snap = Snapshot(geo_stats={
            "countries_count": 1,
            "unique_ips_per_country": {"TR": 5},
            "top_countries": [("TR", 5)],
        })
        d = snap.to_dict()
        restored = Snapshot.from_dict(d)
        assert restored.geo_stats["countries_count"] == 1
        assert restored.geo_stats["unique_ips_per_country"]["TR"] == 5

    def test_geo_stats_from_dict_missing_uses_empty(self):
        """Missing geo_stats in dict defaults to empty dict."""
        snap = Snapshot.from_dict({"timestamp": 1700000000.0})
        # geo_stats gets {} from from_dict, which differs from default factory
        assert isinstance(snap.geo_stats, dict)

    def test_geo_stats_from_dict_non_dict_uses_empty(self):
        """Non-dict geo_stats value falls back to empty dict."""
        snap = Snapshot.from_dict({"geo_stats": "not a dict"})
        assert isinstance(snap.geo_stats, dict)


# ── Widget payload ────────────────────────────────────────────

class TestWidgetPayload:
    """Tests for Snapshot.to_widget_dict() — the lightweight widget payload."""

    def test_widget_dict_has_expected_keys(self, sample_snapshot):
        """Widget payload contains exactly the keys the widget needs."""
        d = sample_snapshot.to_widget_dict()
        assert set(d.keys()) == {
            "timestamp", "poll_interval_ms",
            "listening", "established", "alerts", "summary", "traffic",
        }

    def test_widget_dict_omits_processes(self, sample_snapshot):
        """Widget payload must NOT contain the potentially large processes dict."""
        d = sample_snapshot.to_widget_dict()
        assert "processes" not in d

    def test_widget_dict_omits_geo_stats(self, sample_snapshot):
        """Widget payload must NOT contain geo_stats."""
        d = sample_snapshot.to_widget_dict()
        assert "geo_stats" not in d

    def test_widget_dict_listening_data(self, sample_snapshot):
        """Listening ports are fully serialized in widget payload."""
        d = sample_snapshot.to_widget_dict()
        assert len(d["listening"]) == 2
        assert d["listening"][0]["local_port"] == 22
        assert d["listening"][1]["local_port"] == 80

    def test_widget_dict_established_data(self, sample_snapshot):
        """Established connections are fully serialized in widget payload."""
        d = sample_snapshot.to_widget_dict()
        assert len(d["established"]) == 1
        assert d["established"][0]["remote_ip"] == "142.250.80.14"

    def test_widget_dict_alerts(self, sample_snapshot):
        """Alerts are included in widget payload."""
        d = sample_snapshot.to_widget_dict()
        assert len(d["alerts"]) == 1
        assert d["alerts"][0]["port"] == 500

    def test_widget_dict_summary(self, sample_snapshot):
        """Summary counts are included in widget payload."""
        d = sample_snapshot.to_widget_dict()
        assert d["summary"]["total_listening"] == 2
        assert d["summary"]["total_established"] == 1

    def test_widget_dict_smaller_than_full(self, sample_snapshot):
        """Widget payload should be smaller than the full snapshot."""
        import json
        full = len(json.dumps(sample_snapshot.to_dict()))
        widget = len(json.dumps(sample_snapshot.to_widget_dict()))
        assert widget < full

    def test_widget_dict_with_processes_data(self):
        """Widget payload omits processes even when snapshot has large process tree."""
        snap = Snapshot(
            processes={str(i): {"pid": i, "name": f"proc_{i}"} for i in range(100)},
            geo_stats={"countries_count": 50, "unique_ips_per_country": {"US": 100}},
        )
        d = snap.to_widget_dict()
        assert "processes" not in d
        assert "geo_stats" not in d
        assert len(d["listening"]) == 0  # defaults still work

    def test_widget_dict_with_traffic(self):
        """Traffic stats are included in widget payload."""
        snap = Snapshot(
            traffic={
                "wlan0": InterfaceStats(
                    interface="wlan0",
                    rx_bytes=1000, tx_bytes=500,
                    rx_packets=10, tx_packets=5,
                    rx_errors=0, tx_errors=0,
                    rx_drops=0, tx_drops=0,
                    rx_rate=100.0, tx_rate=50.0,
                ),
            },
        )
        d = snap.to_widget_dict()
        assert "wlan0" in d["traffic"]
        assert d["traffic"]["wlan0"]["rx_rate"] == 100.0
