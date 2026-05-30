"""NetSentry — Atomic JSON file writer for Snapshot data.

Writes to a temporary file then atomically renames, preventing
partial reads by consumers (widget / TUI).
"""
from __future__ import annotations

import os
from typing import Optional

from shared import DATA_FILE
from backend.models import Snapshot


def write_snapshot(snapshot: Snapshot, path: str = DATA_FILE) -> None:
    """Atomically write a Snapshot to a JSON file.

    Writes to a .tmp file first, then os.rename() for atomicity.
    """
    path = str(path)  # Accept pathlib.Path objects
    tmp_path = path + ".tmp"
    # Ensure parent directory exists
    parent = os.path.dirname(path)
    if parent:
        os.makedirs(parent, exist_ok=True)
    try:
        with open(tmp_path, "w") as fh:
            fh.write(snapshot.to_json())
        os.replace(tmp_path, path)
    except OSError:
        # Clean up tmp on failure
        try:
            os.unlink(tmp_path)
        except OSError:
            pass
        raise


def read_snapshot(path: str = DATA_FILE) -> Optional[Snapshot]:
    """Read and parse a Snapshot from a JSON file.

    Returns None if the file doesn't exist or is invalid.
    """
    try:
        with open(str(path), "r") as fh:
            raw = fh.read()
        return Snapshot.from_json(raw)
    except (FileNotFoundError, OSError, ValueError):
        return None
