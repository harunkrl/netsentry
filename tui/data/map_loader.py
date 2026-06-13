"""KPortWatch TUI — World map data loader.

Loads the Braille ASCII world map from an external data file with
LRU caching to avoid repeated disk I/O.
"""

from __future__ import annotations

import logging
from functools import lru_cache
from pathlib import Path

log = logging.getLogger(__name__)

_MAPS_DIR = Path(__file__).resolve().parent  # tui/data/


@lru_cache(maxsize=1)
def load_world_map() -> list[str]:
    """Load world map lines from ``tui/data/worldmap.txt``.

    Returns a list of equal-length Braille character strings.
    Result is cached — the file is only read once per process.
    """
    map_file = _MAPS_DIR / "worldmap.txt"
    text = map_file.read_text(encoding="utf-8")
    lines = text.splitlines()
    # Strip trailing blank lines but preserve content rows
    while lines and lines[-1].strip() == "":
        lines.pop()
    log.debug("Loaded world map: %d rows from %s", len(lines), map_file)
    return lines
