"""KPortWatch — Tests for backend.writers.json_file (atomic JSON I/O)."""
import json
import os

import pytest

from backend.models import Snapshot, SocketEntry, Alert
from backend.writers.json_file import read_snapshot, write_snapshot, write_widget_snapshot
from shared import AlertLevel


def _make_sample_snapshot() -> Snapshot:
    """Create a minimal Snapshot for I/O tests."""
    return Snapshot(
        timestamp=1700000000.0,
        poll_interval_ms=2000,
        listening=[
            SocketEntry(
                proto="tcp",
                local_ip="127.0.0.1",
                local_port=80,
                remote_ip="0.0.0.0",
                remote_port=0,
                state="LISTEN",
                state_code="0A",
                uid=0,
                inode=12345,
                pid=1,
                process_name="nginx",
                cmdline="/usr/sbin/nginx",
            )
        ],
        established=[],
        alerts=[
            Alert(
                level=AlertLevel.CRITICAL,
                port=4444,
                proto="tcp",
                process_name="evil",
                pid=999,
                message="Malicious port",
                timestamp=1700000000.0,
            )
        ],
        summary={"total_listening": 1, "total_established": 0, "alert_count": 1},
    )


# ── Roundtrip ──────────────────────────────────────────────────

class TestWriteReadRoundtrip:
    def test_write_then_read_roundtrip(self, tmp_data_file):
        """write_snapshot followed by read_snapshot returns an equivalent Snapshot."""
        original = _make_sample_snapshot()
        write_snapshot(original, path=str(tmp_data_file))
        restored = read_snapshot(path=str(tmp_data_file))

        assert restored is not None
        assert restored.timestamp == original.timestamp
        assert restored.poll_interval_ms == original.poll_interval_ms
        assert len(restored.listening) == len(original.listening)
        assert restored.listening[0].local_port == 80
        assert restored.listening[0].proto == "tcp"
        assert len(restored.alerts) == 1
        assert restored.alerts[0].port == 4444
        assert restored.alerts[0].level == AlertLevel.CRITICAL
        assert restored.summary == original.summary

    def test_roundtrip_preserves_all_fields(self, tmp_data_file):
        """Every field in the Snapshot survives the write/read cycle."""
        original = _make_sample_snapshot()
        write_snapshot(original, path=str(tmp_data_file))
        restored = read_snapshot(path=str(tmp_data_file))

        orig_dict = original.to_dict()
        restored_dict = restored.to_dict()
        assert orig_dict == restored_dict


# ── Error handling ─────────────────────────────────────────────

class TestReadErrors:
    def test_read_missing_file_returns_none(self, tmp_path):
        """Reading a non-existent file returns None."""
        missing = str(tmp_path / "does_not_exist.json")
        assert read_snapshot(path=missing) is None

    def test_read_invalid_json_returns_none(self, tmp_path):
        """Reading a file with invalid JSON returns None (not an exception)."""
        bad_file = tmp_path / "bad.json"
        bad_file.write_text("this is not json {{{")
        assert read_snapshot(path=str(bad_file)) is None

    def test_read_empty_file_returns_none(self, tmp_path):
        """Reading an empty file returns None."""
        empty_file = tmp_path / "empty.json"
        empty_file.write_text("")
        assert read_snapshot(path=str(empty_file)) is None


# ── Atomicity ──────────────────────────────────────────────────

class TestAtomicWrite:
    def test_tmp_file_cleaned_up_after_write(self, tmp_data_file):
        """After a successful write, the .tmp file should not remain."""
        snapshot = _make_sample_snapshot()
        write_snapshot(snapshot, path=str(tmp_data_file))

        tmp_path = str(tmp_data_file) + ".tmp"
        assert not os.path.exists(tmp_path), ".tmp file should be cleaned up"

    def test_target_file_exists_after_write(self, tmp_data_file):
        """The target file should exist after a successful write."""
        snapshot = _make_sample_snapshot()
        write_snapshot(snapshot, path=str(tmp_data_file))

        assert os.path.exists(str(tmp_data_file))

    def test_file_content_is_valid_json(self, tmp_data_file):
        """The written file content should be valid JSON."""
        snapshot = _make_sample_snapshot()
        write_snapshot(snapshot, path=str(tmp_data_file))

        with open(str(tmp_data_file), "r") as f:
            content = f.read()
        parsed = json.loads(content)
        assert isinstance(parsed, dict)
        assert "timestamp" in parsed


# ── Parent directory creation ──────────────────────────────────

class TestParentDirCreation:
    def test_creates_parent_directories(self, tmp_path):
        """write_snapshot should create parent dirs if they don't exist."""
        nested_path = str(tmp_path / "subdir1" / "subdir2" / "data.json")
        snapshot = _make_sample_snapshot()
        write_snapshot(snapshot, path=nested_path)

        assert os.path.exists(nested_path)
        restored = read_snapshot(path=nested_path)
        assert restored is not None
        assert restored.timestamp == snapshot.timestamp

    def test_reads_from_nested_path(self, tmp_path):
        """read_snapshot can read from a nested path that was just written."""
        nested_path = str(tmp_path / "a" / "b" / "c" / "snapshot.json")
        snapshot = _make_sample_snapshot()
        write_snapshot(snapshot, path=nested_path)

        restored = read_snapshot(path=nested_path)
        assert restored.listening[0].local_port == 80


# ── Widget snapshot ───────────────────────────────────────────

class TestWriteWidgetSnapshot:
    def test_write_widget_snapshot_creates_file(self, tmp_path):
        """write_widget_snapshot creates a valid JSON file."""
        out = str(tmp_path / "widget-data.json")
        snap = _make_sample_snapshot()
        write_widget_snapshot(snap, path=out)
        assert os.path.exists(out)

    def test_widget_snapshot_is_valid_json(self, tmp_path):
        """Widget snapshot file contains valid JSON."""
        out = str(tmp_path / "widget-data.json")
        snap = _make_sample_snapshot()
        write_widget_snapshot(snap, path=out)
        with open(out) as f:
            data = json.load(f)
        assert isinstance(data, dict)

    def test_widget_snapshot_omits_processes(self, tmp_path):
        """Widget snapshot file must NOT contain processes."""
        out = str(tmp_path / "widget-data.json")
        snap = _make_sample_snapshot()
        snap.processes = {"1": {"pid": 1, "name": "big_proc_tree"}}
        write_widget_snapshot(snap, path=out)
        with open(out) as f:
            data = json.load(f)
        assert "processes" not in data

    def test_widget_snapshot_omits_geo_stats(self, tmp_path):
        """Widget snapshot file must NOT contain geo_stats."""
        out = str(tmp_path / "widget-data.json")
        snap = _make_sample_snapshot()
        snap.geo_stats = {"countries_count": 99}
        write_widget_snapshot(snap, path=out)
        with open(out) as f:
            data = json.load(f)
        assert "geo_stats" not in data

    def test_widget_snapshot_contains_used_keys(self, tmp_path):
        """Widget snapshot has all keys the widget actually uses."""
        out = str(tmp_path / "widget-data.json")
        snap = _make_sample_snapshot()
        write_widget_snapshot(snap, path=out)
        with open(out) as f:
            data = json.load(f)
        assert "listening" in data
        assert "established" in data
        assert "alerts" in data
        assert "summary" in data
        assert "traffic" in data
        assert data["summary"]["total_listening"] == 1
        assert len(data["alerts"]) == 1

    def test_widget_snapshot_is_atomic(self, tmp_path):
        """Widget snapshot uses atomic write (no leftover .tmp on success)."""
        out = str(tmp_path / "widget-data.json")
        snap = _make_sample_snapshot()
        write_widget_snapshot(snap, path=out)
        assert not os.path.exists(out + ".tmp")

    def test_widget_snapshot_creates_parent_dirs(self, tmp_path):
        """Widget snapshot creates nested parent directories."""
        out = str(tmp_path / "deep" / "nested" / "widget.json")
        snap = _make_sample_snapshot()
        write_widget_snapshot(snap, path=out)
        assert os.path.exists(out)

    def test_widget_snapshot_smaller_than_full(self, tmp_path):
        """Widget snapshot should be smaller than the full snapshot."""
        full_out = str(tmp_path / "full.json")
        widget_out = str(tmp_path / "widget.json")
        snap = _make_sample_snapshot()
        snap.processes = {str(i): {"pid": i} for i in range(50)}
        snap.geo_stats = {"countries_count": 10, "data": list(range(100))}
        write_snapshot(snap, path=full_out)
        write_widget_snapshot(snap, path=widget_out)
        full_size = os.path.getsize(full_out)
        widget_size = os.path.getsize(widget_out)
        assert widget_size < full_size
