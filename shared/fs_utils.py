"""KPortWatch — Shared filesystem utilities.

Consolidates patterns used across backend and TUI modules:
  - read_file_safe: safe /proc file reads
  - atomic_write: write-to-tmp + rename for crash safety
"""

from __future__ import annotations

import contextlib
import os
import tempfile


def read_file_safe(path: str) -> str | None:
    """Read a small file, returning None on any error.

    Safe for /proc files and other volatile paths where the file
    may disappear between listing and reading.
    """
    try:
        with open(path) as fh:
            return fh.read().strip()
    except (PermissionError, FileNotFoundError, ProcessLookupError, OSError):
        return None


def atomic_write(path: str, data: str, *, mode: int = 0o644) -> None:
    """Write *data* to *path* atomically via tmp-file + os.replace.

    Creates parent directories if needed.  Cleans up the temp file
    on failure.
    """
    dir_name = os.path.dirname(path)
    if dir_name:
        os.makedirs(dir_name, exist_ok=True)

    fd, tmp = tempfile.mkstemp(dir=dir_name or ".", suffix=".tmp")
    try:
        with os.fdopen(fd, "w") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        with contextlib.suppress(OSError):
            os.unlink(tmp)
        raise
