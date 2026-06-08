#!/usr/bin/env python3
"""Sync version from pyproject.toml to widget/metadata.json.

Run: python scripts/sync-version.py
Called automatically during build if using hatch/pip.
"""
from __future__ import annotations

import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
PYPROJECT = ROOT / "pyproject.toml"
METADATA = ROOT / "widget" / "metadata.json"


def get_pyproject_version() -> str:
    """Read version from pyproject.toml."""
    import tomllib
    with open(PYPROJECT, "rb") as f:
        data = tomllib.load(f)
    return data["project"]["version"]


def get_metadata_version() -> str:
    """Read version from metadata.json."""
    with open(METADATA) as f:
        data = json.load(f)
    return data["KPlugin"]["Version"]


def sync_version() -> bool:
    """Sync pyproject.toml version → metadata.json. Returns True if changed."""
    pyproject_ver = get_pyproject_version()
    metadata_ver = get_metadata_version()

    if pyproject_ver == metadata_ver:
        print(f"✓ Versions in sync: {pyproject_ver}")
        return False

    with open(METADATA) as f:
        data = json.load(f)

    data["KPlugin"]["Version"] = pyproject_ver

    with open(METADATA, "w") as f:
        json.dump(data, f, indent=4)
        f.write("\n")

    print(f"✓ Updated metadata.json: {metadata_ver} → {pyproject_ver}")
    return True


if __name__ == "__main__":
    try:
        changed = sync_version()
        sys.exit(0 if not changed else 0)
    except Exception as e:
        print(f"✗ Error: {e}", file=sys.stderr)
        sys.exit(1)
