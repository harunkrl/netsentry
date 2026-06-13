"""KPortWatch — Config persistence (save_config_setting, save_tui_setting)."""

from __future__ import annotations

import fcntl
import logging
import os
import re

logger = logging.getLogger("kportwatch.config")

CONFIG_DIR: str = os.path.expanduser("~/.config/kportwatch")
CONFIG_FILE: str = os.path.join(CONFIG_DIR, "config.toml")


def save_config_setting(section: str, key: str, value: object) -> None:
    """Persist a single setting to the config file under the given section.

    Thread-safe: uses fcntl file locking to prevent concurrent write corruption.
    Reads the existing config, updates the named section, and writes back.
    Creates the file/section if they don't exist.
    """
    path = CONFIG_FILE
    raw = ""
    try:
        os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    except OSError:
        return

    try:
        fd = os.open(path, os.O_RDWR | os.O_CREAT, 0o644)
        with open(fd, "r+") as fh:
            fcntl.flock(fh, fcntl.LOCK_EX)
            try:
                fh.seek(0)
                raw = fh.read()

                section_tag = f"[{section}]"
                line = f"{key} = {'true' if value is True else 'false' if value is False else repr(value)}\n"

                if section_tag in raw:
                    section_start = raw.index(section_tag) + len(section_tag)
                    next_section = re.search(r"\n(?=\[)", raw[section_start:])
                    section_end = section_start + next_section.start() if next_section else len(raw)
                    section_block = raw[section_start:section_end]

                    pattern = rf"({re.escape(key)}\s*=\s*[^\n]+)"
                    if re.search(pattern, section_block):
                        new_section_block = re.sub(
                            pattern,
                            f"{key} = {'true' if value is True else 'false' if value is False else repr(value)}",
                            section_block,
                            count=1,
                        )
                        raw = raw[:section_start] + new_section_block + raw[section_end:]
                    else:
                        raw = raw.replace(section_tag, f"{section_tag}\n{line}", 1)
                else:
                    raw = raw.rstrip() + "\n\n" + section_tag + "\n" + line

                fh.seek(0)
                fh.write(raw)
                fh.truncate()
            finally:
                fcntl.flock(fh, fcntl.LOCK_UN)
    except OSError:
        logger.debug("Failed to save config setting to %s", path, exc_info=True)


def save_tui_setting(key: str, value: object) -> None:
    """Shorthand for ``save_config_setting('tui', key, value)``."""
    save_config_setting("tui", key, value)
