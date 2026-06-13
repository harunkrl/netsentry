"""Tests for SnapshotBuilder — hash-diffing skip-write optimization.

Covers the performance optimization documented in snapshot.py's module
docstring: redundant atomic JSON file writes are skipped when the snapshot
*content* is unchanged, while socket broadcast, history, and heartbeat
always run. A forced write self-heals every ``_FORCE_WRITE_EVERY`` cycles.
"""

from __future__ import annotations

import time
from unittest.mock import Mock

import pytest
from backend.daemon import snapshot as snap_mod
from backend.daemon.snapshot import SnapshotBuilder
from backend.models import Snapshot

# ── Fixtures ────────────────────────────────────────────────────────────────


@pytest.fixture
def builder(monkeypatch, tmp_path):
    """A SnapshotBuilder with mocked sinks and counted file writes."""
    writes = {"data": 0, "widget": 0}

    def _fake_write_snapshot(_json, path=None):
        writes["data"] += 1

    def _fake_write_widget(_snap, path=None):
        writes["widget"] += 1

    monkeypatch.setattr(snap_mod, "write_snapshot", _fake_write_snapshot)
    monkeypatch.setattr(snap_mod, "write_widget_snapshot", _fake_write_widget)

    sock = Mock()
    sock.broadcast = Mock()

    history = Mock()
    cfg = Mock()
    cfg.effective_heartbeat_file = str(tmp_path / "hb.json")

    sb = SnapshotBuilder(Mock(), history, sock, cfg)
    return sb, writes, sock, history


def _snap(timestamp=None, interval_ms=2000):
    return Snapshot(
        timestamp=time.time() if timestamp is None else timestamp,
        poll_interval_ms=interval_ms,
    )


# ── Content hash ────────────────────────────────────────────────────────────


class TestContentHash:
    def test_identical_content_same_hash(self):
        # Different timestamps but otherwise identical -> same hash
        a = _snap(timestamp=1000.0)
        b = _snap(timestamp=2000.0)
        assert SnapshotBuilder._content_hash(a) == SnapshotBuilder._content_hash(b)

    def test_different_interval_same_hash(self):
        # poll_interval_ms is volatile too -> excluded
        a = _snap(timestamp=1.0, interval_ms=2000)
        b = _snap(timestamp=2.0, interval_ms=5000)
        assert SnapshotBuilder._content_hash(a) == SnapshotBuilder._content_hash(b)

    def test_different_content_different_hash(self):
        a = _snap(timestamp=1.0)
        b = _snap(timestamp=1.0)
        b.summary = {"total_listening": 99}
        assert SnapshotBuilder._content_hash(a) != SnapshotBuilder._content_hash(b)


# ── Skip-write optimization ────────────────────────────────────────────────


class TestSkipWriteOptimization:
    def test_first_publish_writes_files(self, builder):
        sb, writes, _sock, _history = builder
        sb._publish(_snap(), [])
        assert writes["data"] == 1
        assert writes["widget"] == 1

    def test_unchanged_content_skips_file_writes(self, builder):
        sb, writes, _sock, _history = builder
        for _ in range(5):
            sb._publish(_snap(), [])  # identical content (ignoring timestamp)
        assert writes["data"] == 1  # only the first publish wrote
        assert writes["widget"] == 1

    def test_broadcast_always_runs(self, builder):
        sb, _writes, sock, _history = builder
        for _ in range(5):
            sb._publish(_snap(), [])
        assert sock.broadcast.call_count == 5  # broadcast every cycle

    def test_history_always_records(self, builder):
        sb, _writes, _sock, history = builder
        for _ in range(3):
            sb._publish(_snap(), [])
        assert history.record_summary.call_count == 3

    def test_heartbeat_always_written(self, builder, tmp_path):
        sb, _writes, _sock, _history = builder
        import os

        hb = sb._cfg.effective_heartbeat_file
        sb._publish(_snap(), [])
        sb._publish(_snap(), [])
        # heartbeat file should exist after publish (written via _write_heartbeat)
        assert os.path.exists(hb)

    def test_changed_content_triggers_write(self, builder):
        sb, writes, _sock, _history = builder
        sb._publish(_snap(), [])
        # Now change content
        s = _snap()
        s.summary = {"total_listening": 42}
        sb._publish(s, [])
        assert writes["data"] == 2  # second write happened
        assert writes["widget"] == 2

    def test_force_write_every_n_cycles(self, builder):
        sb, writes, _sock, _history = builder
        from backend.daemon.snapshot import _FORCE_WRITE_EVERY

        # Publish _FORCE_WRITE_EVERY identical snapshots
        for _ in range(_FORCE_WRITE_EVERY):
            sb._publish(_snap(), [])
        # First publish (1) + forced write at cycle (_FORCE_WRITE_EVERY+1)
        # Within N cycles we expect: 1 initial write.
        assert writes["data"] >= 1
        # One more cycle should trigger the periodic forced rewrite
        sb._publish(_snap(), [])
        assert writes["data"] == 2  # forced rewrite kicked in
        assert writes["widget"] == 2


# ── build_and_publish integration ───────────────────────────────────────────


class TestBuildAndPublish:
    def test_publishes_snapshot(self, builder):
        sb, writes, sock, _history = builder
        snap = sb.build_and_publish(
            listening=[],
            established=[],
            alerts=[],
            traffic={},
            process_tree={},
            interval_ms=2000,
        )
        assert isinstance(snap, Snapshot)
        assert writes["data"] == 1
        assert sock.broadcast.called
