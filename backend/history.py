"""KPortWatch — History recorder.

Appends per-cycle summaries and alerts to daily JSONL files so the user
can inspect trends, export data, and review past events.

Files:
    ~/.config/kportwatch/history/YYYY-MM-DD.jsonl

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
from datetime import datetime

from shared.constants import BASELINE_DIR

HISTORY_DIR: str = os.path.join(BASELINE_DIR, "history")
DEFAULT_RETENTION_DAYS: int = 30


class HistoryRecorder:
    """Writes per-cycle history entries to daily JSONL files."""

    def __init__(
        self,
        history_dir: str | None = None,
        retention_days: int = DEFAULT_RETENTION_DAYS,
    ) -> None:
        self.history_dir = history_dir or HISTORY_DIR
        self.retention_days = retention_days
        self._current_file: str | None = None
        self._current_date: str | None = None
        self._fh = None  # persistent file handle

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
            # Close previous file handle if open
            if self._fh is not None and not self._fh.closed:
                self._fh.close()
            self._current_date = today
            self._current_file = os.path.join(self.history_dir, f"{today}.jsonl")
            os.makedirs(self.history_dir, exist_ok=True)
            # Prune old files once per day at rotation
            self._prune_old_files()
            # Open new file handle
            self._fh = open(self._current_file, "a")  # noqa: SIM115
        return self._current_file

    def _ensure_fh(self):
        """Ensure the file handle is open and valid."""
        if self._fh is None or self._fh.closed:
            self._get_file_path()
        return self._fh

    def _append(self, data: dict) -> None:
        """Append a JSON line to today's file using persistent handle."""
        self._get_file_path()
        try:
            fh = self._ensure_fh()
            fh.write(json.dumps(data, ensure_ascii=False) + "\n")
            fh.flush()
        except OSError:
            pass  # history is best-effort

    def close(self) -> None:
        """Close the persistent file handle."""
        if self._fh is not None and not self._fh.closed:
            self._fh.close()

    def record_summary(self, snapshot) -> None:
        """Record a lightweight cycle summary from a Snapshot."""
        self._append(
            {
                "type": "summary",
                "ts": snapshot.timestamp,
                "listening": snapshot.summary.get("total_listening", 0),
                "established": snapshot.summary.get("total_established", 0),
                "alerts": snapshot.summary.get("alert_count", 0),
            }
        )

    def record_alert(self, alert) -> None:
        """Record a single alert event."""
        self._append(
            {
                "type": "alert",
                "ts": alert.timestamp,
                "level": str(alert.level),
                "port": alert.port,
                "proto": alert.proto,
                "process": alert.process_name,
                "pid": alert.pid,
                "message": alert.message,
            }
        )


def read_history(
    history_dir: str | None = None,
    date: str | None = None,
    event_type: str | None = None,
    last_n: int | None = None,
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
        with open(path) as fh:
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


def list_available_dates(history_dir: str | None = None) -> list[str]:
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
    history_dir: str | None = None,
    date: str | None = None,
    event_type: str | None = None,
    last_n: int | None = None,
) -> int:
    """Export history entries to a CSV file.

    Args:
        last_n: If set, only export the last N entries.

    Returns the number of rows written.
    """
    entries = read_history(history_dir, date, event_type)
    if not entries:
        return 0
    if last_n is not None and last_n > 0:
        entries = entries[-last_n:]

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
    history_dir: str | None = None,
    date: str | None = None,
    event_type: str | None = None,
    last_n: int | None = None,
) -> int:
    """Export history entries to a JSON file.

    Args:
        last_n: If set, only export the last N entries.

    Returns the number of entries written.
    """
    entries = read_history(history_dir, date, event_type)
    if not entries:
        return 0
    if last_n is not None and last_n > 0:
        entries = entries[-last_n:]

    with open(output_path, "w") as fh:
        json.dump(entries, fh, indent=2, ensure_ascii=False)

    return len(entries)
