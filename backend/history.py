"""NetSentry — History recorder.

Appends per-cycle summaries and alerts to daily JSONL files so the user
can inspect trends, export data, and review past events.

Files:
    ~/.config/netsentry/history/YYYY-MM-DD.jsonl

Each line is a JSON object.  Two event types:
  - "summary": one per daemon cycle (port counts, alert counts)
  - "alert": one per alert fired (full alert details)

Automatic cleanup:
    Files older than ``history_retention_days`` (default 30) are pruned
    once per day when the recorder opens a new file (midnight rotation).

Usage::

    from backend.history import HistoryRecorder

    recorder = HistoryRecorder(retention_days=30)
    recorder.record_summary(snapshot)
    recorder.record_alert(alert)
"""
from __future__ import annotations

import json
import os
import time
from datetime import datetime
from pathlib import Path
from typing import Optional

from shared.constants import BASELINE_DIR

HISTORY_DIR: str = os.path.join(BASELINE_DIR, "history")
DEFAULT_RETENTION_DAYS: int = 30


class HistoryRecorder:
    """Writes per-cycle history entries to daily JSONL files."""

    def __init__(
        self,
        history_dir: Optional[str] = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        self.history_dir = history_dir or HISTORY_DIR
        self.retention_days = retention_days
        self._current_file: Optional[str] = None
        self._current_date: Optional[str] = None

    def _prune_old_files(self) -> None:
        """Delete history files older than retention_days."""
        cutoff = datetime.now().timestamp() - (self.retention_days * 86400)
        try:
            for f in os.listdir(self.history_dir):
                if not f.endswith(".jsonl"):
                    continue
                path = os.path.join(self.history_dir, f)
                try:
                    if os.path.getmtime(path) < cutoff:
                        os.unlink(path)
                except OSError:
                    pass
        except OSError:
            pass

    def _get_file_path(self) -> str:
        """Return today's JSONL file path, rotating at midnight."""
        today = datetime.now().strftime("%Y-%m-%d")
        if today != self._current_date:
            self._current_date = today
            self._current_file = os.path.join(self.history_dir, f"{today}.jsonl")
            os.makedirs(self.history_dir, exist_ok=True)
            # Prune old files once per day at rotation
            self._prune_old_files()
        return self._current_file

    def _append(self, data: dict) -> None:
        """Append a JSON line to today's file."""
        path = self._get_file_path()
        try:
            with open(path, "a") as fh:
                fh.write(json.dumps(data, ensure_ascii=False) + "\n")
        except OSError:
            pass  # history is best-effort

    def record_summary(self, snapshot) -> None:
        """Record a lightweight cycle summary from a Snapshot."""
        self._append({
            "type": "summary",
            "ts": snapshot.timestamp,
            "listening": snapshot.summary.get("total_listening", 0),
            "established": snapshot.summary.get("total_established", 0),
            "alerts": snapshot.summary.get("alert_count", 0),
        })

    def record_alert(self, alert) -> None:
        """Record a single alert event."""
        self._append({
            "type": "alert",
            "ts": alert.timestamp,
            "level": str(alert.level),
            "port": alert.port,
            "proto": alert.proto,
            "process": alert.process_name,
            "pid": alert.pid,
            "message": alert.message,
        })


def read_history(
    history_dir: Optional[str] = None,
    date: Optional[str] = None,
    event_type: Optional[str] = None,
    last_n: Optional[int] = None,
) -> list[dict]:
    """Read history entries from JSONL files.

    Args:
        history_dir: Override default history directory.
        date: Specific date "YYYY-MM-DD". None = today.
        event_type: Filter by "summary" or "alert". None = all.
        last_n: Return only the last N matching entries.
    """
    hdir = history_dir or HISTORY_DIR
    if date is None:
        date = datetime.now().strftime("%Y-%m-%d")

    path = os.path.join(hdir, f"{date}.jsonl")
    entries: list[dict] = []

    try:
        with open(path, "r") as fh:
            for line in fh:
                line = line.strip()
                if not line:
                    continue
                try:
                    entry = json.loads(line)
                except json.JSONDecodeError:
                    continue
                if event_type and entry.get("type") != event_type:
                    continue
                entries.append(entry)
    except FileNotFoundError:
        return []

    if last_n:
        entries = entries[-last_n:]

    return entries


def list_available_dates(history_dir: Optional[str] = None) -> list[str]:
    """Return sorted list of dates that have history files."""
    hdir = history_dir or HISTORY_DIR
    dates: list[str] = []
    try:
        for f in os.listdir(hdir):
            if f.endswith(".jsonl") and len(f) == 16:  # YYYY-MM-DD.jsonl = 16 chars
                dates.append(f.replace(".jsonl", ""))
    except OSError:
        pass
    return sorted(dates)


def export_history_csv(
    output_path: str,
    history_dir: Optional[str] = None,
    date: Optional[str] = None,
    event_type: Optional[str] = None,
) -> int:
    """Export history entries to a CSV file.

    Returns the number of rows written.
    """
    entries = read_history(history_dir, date, event_type)
    if not entries:
        return 0

    import csv
    # Collect all keys across entries for header
    all_keys: list[str] = []
    seen = set()
    for entry in entries:
        for k in entry:
            if k not in seen:
                all_keys.append(k)
                seen.add(k)

    with open(output_path, "w", newline="") as fh:
        writer = csv.DictWriter(fh, fieldnames=all_keys)
        writer.writeheader()
        for entry in entries:
            writer.writerow(entry)

    return len(entries)


def export_history_json(
    output_path: str,
    history_dir: Optional[str] = None,
    date: Optional[str] = None,
    event_type: Optional[str] = None,
) -> int:
    """Export history entries to a JSON file.

    Returns the number of entries written.
    """
    entries = read_history(history_dir, date, event_type)
    if not entries:
        return 0

    with open(output_path, "w") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)

    return len(entries)
