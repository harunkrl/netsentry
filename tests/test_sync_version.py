"""Tests for scripts/sync-version.py."""

from __future__ import annotations

import importlib.util
import json
from pathlib import Path
from unittest.mock import patch

# Load scripts/sync-version.py as a module (not a package)
_SCRIPT = Path("scripts/sync-version.py")
_spec = importlib.util.spec_from_file_location("sync_version", _SCRIPT)
_sync = importlib.util.module_from_spec(_spec)
_spec.loader.exec_module(_sync)


class TestSyncVersion:
    """Tests for version synchronization between pyproject.toml and metadata.json."""

    def test_versions_in_sync(self):
        """pyproject.toml and metadata.json have the same version."""
        assert _sync.get_pyproject_version() == _sync.get_metadata_version()

    def test_pyproject_version_format(self):
        """pyproject.toml version follows semver pattern."""
        ver = _sync.get_pyproject_version()
        parts = ver.split(".")
        assert len(parts) == 3
        for part in parts:
            assert part.isdigit()

    def test_sync_detects_mismatch(self, tmp_path):
        """sync_version detects version mismatch and updates metadata.json."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nversion = "3.0.0"\n')

        metadata = tmp_path / "metadata.json"
        metadata.write_text(json.dumps({"KPlugin": {"Version": "2.1.0", "Name": "Test"}}))

        with patch.object(_sync, "PYPROJECT", pyproject), patch.object(_sync, "METADATA", metadata):
            changed = _sync.sync_version()

        assert changed is True
        data = json.loads(metadata.read_text())
        assert data["KPlugin"]["Version"] == "3.0.0"

    def test_sync_no_change_when_matching(self, tmp_path):
        """sync_version returns False when versions match."""
        pyproject = tmp_path / "pyproject.toml"
        pyproject.write_text('[project]\nversion = "2.1.0"\n')

        metadata = tmp_path / "metadata.json"
        metadata.write_text(json.dumps({"KPlugin": {"Version": "2.1.0", "Name": "Test"}}))

        with patch.object(_sync, "PYPROJECT", pyproject), patch.object(_sync, "METADATA", metadata):
            changed = _sync.sync_version()

        assert changed is False
