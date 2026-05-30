"""NetSentry — Tests for backend.models (SocketEntry, Alert, Snapshot)."""
import json
import time

import pytest

from backend.models import Alert, SocketEntry, Snapshot
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
