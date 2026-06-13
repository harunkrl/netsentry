"""Tests for backend.history — History recorder and export."""

from __future__ import annotations

import json
from datetime import datetime
from pathlib import Path

import pytest
from backend.history import (
    HistoryRecorder,
    export_history_csv,
    export_history_json,
    list_available_dates,
    read_history,
)
from backend.models import Alert, Snapshot, SocketEntry
from shared import AlertLevel

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture
def history_dir(tmp_path: Path) -> Path:
    return tmp_path / "history"


@pytest.fixture
def recorder(history_dir: Path) -> HistoryRecorder:
    return HistoryRecorder(history_dir=str(history_dir))


@pytest.fixture
def sample_snapshot() -> Snapshot:
    entry = SocketEntry(
        proto="tcp",
        local_ip="0.0.0.0",
        local_port=22,
        remote_ip="0.0.0.0",
        remote_port=0,
        state="LISTEN",
        state_code="0A",
        uid=0,
        inode=12345,
    )
    return Snapshot(
        listening=[entry],
        summary={"total_listening": 1, "total_established": 0, "alert_count": 0},
    )


@pytest.fixture
def sample_alert() -> Alert:
    return Alert(
        level=AlertLevel.CRITICAL,
        port=4444,
        proto="tcp",
        process_name="suspicious",
        pid=999,
        message="Malicious port detected",
        timestamp=1700000000.0,
    )


# ── HistoryRecorder tests ─────────────────────────────────────────


class TestHistoryRecorder:
    def test_creates_directory(self, recorder: HistoryRecorder, history_dir: Path):
        recorder._get_file_path()
        assert history_dir.exists()

    def test_creates_daily_file(self, recorder: HistoryRecorder, history_dir: Path):
        path = recorder._get_file_path()
        today = datetime.now().strftime("%Y-%m-%d")
        assert today in path
        assert path.endswith(".jsonl")

    def test_record_summary(
        self, recorder: HistoryRecorder, history_dir: Path, sample_snapshot: Snapshot
    ):
        recorder.record_summary(sample_snapshot)
        entries = read_history(str(history_dir))
        assert len(entries) == 1
        assert entries[0]["type"] == "summary"
        assert entries[0]["listening"] == 1

    def test_record_alert(self, recorder: HistoryRecorder, history_dir: Path, sample_alert: Alert):
        recorder.record_alert(sample_alert)
        entries = read_history(str(history_dir), event_type="alert")
        assert len(entries) == 1
        assert entries[0]["type"] == "alert"
        assert entries[0]["level"] == "CRITICAL"
        assert entries[0]["port"] == 4444

    def test_multiple_entries(
        self,
        recorder: HistoryRecorder,
        history_dir: Path,
        sample_snapshot: Snapshot,
        sample_alert: Alert,
    ):
        recorder.record_summary(sample_snapshot)
        recorder.record_alert(sample_alert)
        recorder.record_summary(sample_snapshot)
        entries = read_history(str(history_dir))
        assert len(entries) == 3

    def test_file_rotates_on_date_change(
        self, recorder: HistoryRecorder, history_dir: Path, sample_snapshot: Snapshot
    ):
        # Simulate today
        recorder._current_date = "2099-01-01"
        recorder._current_file = str(history_dir / "2099-01-01.jsonl")
        recorder.record_summary(sample_snapshot)

        # Now trigger date change
        recorder._current_date = None
        path = recorder._get_file_path()
        assert "2099-01-01" not in path


# ── read_history tests ────────────────────────────────────────────


class TestReadHistory:
    def test_read_nonexistent_date(self, history_dir: Path):
        entries = read_history(str(history_dir), date="2099-12-31")
        assert entries == []

    def test_filter_by_type(
        self,
        recorder: HistoryRecorder,
        history_dir: Path,
        sample_snapshot: Snapshot,
        sample_alert: Alert,
    ):
        recorder.record_summary(sample_snapshot)
        recorder.record_alert(sample_alert)

        summaries = read_history(str(history_dir), event_type="summary")
        alerts = read_history(str(history_dir), event_type="alert")
        assert len(summaries) == 1
        assert len(alerts) == 1

    def test_last_n_filter(
        self, recorder: HistoryRecorder, history_dir: Path, sample_snapshot: Snapshot
    ):
        for _ in range(5):
            recorder.record_summary(sample_snapshot)
        entries = read_history(str(history_dir), last_n=3)
        assert len(entries) == 3


# ── list_available_dates tests ────────────────────────────────────


class TestListDates:
    def test_empty_dir(self, history_dir: Path):
        dates = list_available_dates(str(history_dir))
        assert dates == []

    def test_lists_dates(
        self, recorder: HistoryRecorder, history_dir: Path, sample_snapshot: Snapshot
    ):
        recorder.record_summary(sample_snapshot)
        dates = list_available_dates(str(history_dir))
        assert len(dates) == 1
        today = datetime.now().strftime("%Y-%m-%d")
        assert dates[0] == today


# ── Export tests ───────────────────────────────────────────────────


class TestExport:
    def test_export_json(
        self,
        recorder: HistoryRecorder,
        history_dir: Path,
        tmp_path: Path,
        sample_snapshot: Snapshot,
        sample_alert: Alert,
    ):
        recorder.record_summary(sample_snapshot)
        recorder.record_alert(sample_alert)

        out = str(tmp_path / "export.json")
        count = export_history_json(out, str(history_dir))
        assert count == 2

        with open(out) as f:
            data = json.load(f)
        assert len(data) == 2

    def test_export_csv(
        self,
        recorder: HistoryRecorder,
        history_dir: Path,
        tmp_path: Path,
        sample_snapshot: Snapshot,
    ):
        recorder.record_summary(sample_snapshot)
        recorder.record_summary(sample_snapshot)

        out = str(tmp_path / "export.csv")
        count = export_history_csv(out, str(history_dir))
        assert count == 2

        with open(out) as f:
            lines = f.readlines()
        assert len(lines) == 3  # header + 2 rows

    def test_export_empty(self, tmp_path: Path, history_dir: Path):
        out = str(tmp_path / "empty.json")
        count = export_history_json(out, str(history_dir), date="2099-12-31")
        assert count == 0
