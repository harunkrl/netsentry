"""KPortWatch — Atomic JSON file writer for Snapshot data.

Writes to a temporary file then atomically renames, preventing
partial reads by consumers (widget / TUI).
"""

from __future__ import annotations

import json

from shared import DATA_FILE, WIDGET_DATA_FILE
from shared.fs_utils import atomic_write

from backend.models import Snapshot

_dirs_created = set()


def write_snapshot(snapshot_data: Snapshot | str, path: str = DATA_FILE) -> None:
    """Atomically write a Snapshot to a JSON file."""
    path = str(path)  # Accept pathlib.Path objects
    data = snapshot_data if isinstance(snapshot_data, str) else snapshot_data.to_json()
    atomic_write(path, data)


def write_widget_snapshot(snapshot: Snapshot, path: str = WIDGET_DATA_FILE) -> None:
    """Atomically write a lightweight widget-only payload."""
    data = json.dumps(snapshot.to_widget_dict(), ensure_ascii=False)
    atomic_write(str(path), data)


def read_snapshot(path: str = DATA_FILE) -> Snapshot | None:
    """Read and parse a Snapshot from a JSON file.

    Returns None if the file doesn't exist or is invalid.
    """
    try:
        with open(str(path)) as fh:
            raw = fh.read()
        return Snapshot.from_json(raw)
    except (FileNotFoundError, OSError, ValueError):
        return None
