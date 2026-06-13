"""Tests for process tree builder and ProcessInfo model."""

from __future__ import annotations

from dataclasses import asdict
from unittest.mock import patch

import pytest
from backend.models import ProcessInfo, Snapshot
from backend.parsers.process_tree import (
    _parse_stat,
    build_process_tree,
    get_tree_roots,
)

# ── _parse_stat tests ──────────────────────────────────────────


class TestParseStat:
    """Tests for _parse_stat() helper."""

    def test_parse_systemd(self, tmp_path):
        """Parse a realistic /proc/1/stat line."""
        stat_file = tmp_path / "stat"
        stat_file.write_text("1 (systemd) S 0 1 1 0 -1 4194560 24566 0\n")
        result = _parse_stat(str(stat_file))
        assert result == (1, "systemd", "S", 0)

    def test_parse_comm_with_spaces(self, tmp_path):
        """Process names with spaces (e.g., 'Web Content') should be parsed correctly."""
        stat_file = tmp_path / "stat"
        stat_file.write_text("1234 (Web Content) S 3034 1234 1234 0\n")
        result = _parse_stat(str(stat_file))
        assert result == (1234, "Web Content", "S", 3034)

    def test_parse_comm_with_parens(self, tmp_path):
        """Process names with parens should use last ')' for split."""
        stat_file = tmp_path / "stat"
        stat_file.write_text("99 (a(b)c) R 1 99 99 0\n")
        result = _parse_stat(str(stat_file))
        assert result == (99, "a(b)c", "R", 1)

    def test_parse_missing_file(self, tmp_path):
        """Missing file returns None."""
        result = _parse_stat(str(tmp_path / "nonexistent"))
        assert result is None

    def test_parse_empty_file(self, tmp_path):
        """Empty file returns None."""
        stat_file = tmp_path / "stat"
        stat_file.write_text("")
        result = _parse_stat(str(stat_file))
        assert result is None

    def test_parse_malformed(self, tmp_path):
        """Line with no parentheses returns None."""
        stat_file = tmp_path / "stat"
        stat_file.write_text("123 no_parens S 1\n")
        result = _parse_stat(str(stat_file))
        assert result is None

    def test_parse_zombie(self, tmp_path):
        """Zombie state (Z) should be captured."""
        stat_file = tmp_path / "stat"
        stat_file.write_text("66 (zombie_proc) Z 1 66 66 0\n")
        result = _parse_stat(str(stat_file))
        assert result == (66, "zombie_proc", "Z", 1)


# ── build_process_tree tests ───────────────────────────────────


class TestBuildProcessTree:
    """Tests for build_process_tree()."""

    def test_basic_tree(self):
        """Build tree from mocked /proc — PID 1 and 2 should be parsed."""

        def fake_read(path):
            if "/1/stat" in path:
                return "1 (systemd) S 0 1 1 0 -1 4194560 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0"
            if "/2/stat" in path:
                return "2 (kthreadd) S 0 1 1 0 -1 4194560 0 0 0 0 0 0 0 0 0 0 0 0 2 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0"
            return None

        with (
            patch("backend.parsers.process_tree.read_file_safe", side_effect=fake_read),
            patch("os.listdir", return_value=["1", "2"]),
        ):
            tree = build_process_tree()

        assert 1 in tree
        assert 2 in tree
        assert tree[1].name == "systemd"
        assert tree[1].ppid == 0
        assert tree[2].ppid == 0

    def test_children_populated(self):
        """systemd should have children when tree has child processes."""

        def fake_read(path):
            if "/1/stat" in path:
                return "1 (systemd) S 0 1 1 0 -1 0 0 0 0 0 0 0 0 0 0 0 0 1 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0"
            if "/100/stat" in path:
                return "100 (child) S 1 1 1 0 -1 0 0 0 0 0 0 0 0 0 0 0 0 100 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0 0"
            return None

        with (
            patch("backend.parsers.process_tree.read_file_safe", side_effect=fake_read),
            patch("os.listdir", return_value=["1", "100"]),
        ):
            tree = build_process_tree()

        assert len(tree[1].children) > 0

    def test_has_network_flag(self):
        """Passing inode_map should set has_network on socket-owning processes."""
        # Find a PID that actually has sockets
        from backend.parsers.inode_map import build_inode_to_pid_map

        inode_map = build_inode_to_pid_map()
        if not inode_map:
            pytest.skip("No socket-owning processes found")

        tree = build_process_tree(inode_map)
        network_pids = [pid for pid, info in tree.items() if info.has_network]
        assert len(network_pids) > 0

    def test_no_network_without_inode_map(self):
        """Without inode_map, no processes should have has_network=True."""
        tree = build_process_tree()
        network_pids = [pid for pid, info in tree.items() if info.has_network]
        assert len(network_pids) == 0

    def test_all_pids_have_required_fields(self):
        """Every ProcessInfo should have non-None required fields."""
        tree = build_process_tree()
        for _pid, info in tree.items():
            assert isinstance(info.pid, int)
            assert isinstance(info.ppid, int)
            assert isinstance(info.name, str)
            assert isinstance(info.state, str)
            assert len(info.state) == 1
            assert isinstance(info.children, list)


# ── get_tree_roots tests ───────────────────────────────────────


class TestGetTreeRoots:
    """Tests for get_tree_roots()."""

    def test_sample_tree_roots(self, sample_process_tree):
        """Roots should be PIDs with PPID=0 or PPID not in tree."""
        roots = get_tree_roots(sample_process_tree)
        assert roots == [1, 2]  # systemd and kthreadd

    def test_empty_tree(self):
        """Empty tree should return empty roots."""
        assert get_tree_roots({}) == []

    def test_single_root(self):
        """Single process with PPID=0."""
        tree = {
            42: ProcessInfo(pid=42, ppid=0, name="test", cmdline="", state="S", uid=0),
        }
        assert get_tree_roots(tree) == [42]

    def test_orphan_process(self):
        """Process whose PPID is not in tree should be a root."""
        tree = {
            100: ProcessInfo(pid=100, ppid=9999, name="orphan", cmdline="", state="S", uid=0),
        }
        roots = get_tree_roots(tree)
        assert roots == [100]

    def test_sorted_output(self):
        """Roots should be sorted by PID."""
        tree = {
            500: ProcessInfo(pid=500, ppid=0, name="c", cmdline="", state="S", uid=0),
            10: ProcessInfo(pid=10, ppid=0, name="a", cmdline="", state="S", uid=0),
            100: ProcessInfo(pid=100, ppid=0, name="b", cmdline="", state="S", uid=0),
        }
        assert get_tree_roots(tree) == [10, 100, 500]


# ── ProcessInfo model tests ────────────────────────────────────


class TestProcessInfo:
    """Tests for ProcessInfo dataclass."""

    def test_from_dict(self):
        """ProcessInfo.from_dict should reconstruct correctly."""
        d = {
            "pid": 1234,
            "ppid": 1,
            "name": "firefox",
            "cmdline": "/usr/lib/firefox/firefox",
            "state": "S",
            "uid": 1000,
            "has_network": True,
            "children": [5678, 5679],
        }
        info = ProcessInfo.from_dict(d)
        assert info.pid == 1234
        assert info.ppid == 1
        assert info.name == "firefox"
        assert info.has_network is True
        assert info.children == [5678, 5679]

    def test_from_dict_ignores_extra_keys(self):
        """Extra keys should be silently ignored."""
        d = {
            "pid": 1,
            "ppid": 0,
            "name": "init",
            "cmdline": "",
            "state": "S",
            "uid": 0,
            "extra": "ignored",
        }
        info = ProcessInfo.from_dict(d)
        assert info.pid == 1

    def test_defaults(self):
        """has_network and children should have correct defaults."""
        info = ProcessInfo(pid=1, ppid=0, name="test", cmdline="", state="S", uid=0)
        assert info.has_network is False
        assert info.children == []


# ── Snapshot serialization with processes ──────────────────────


class TestSnapshotProcesses:
    """Tests for Snapshot serialization with process tree data."""

    def test_snapshot_with_processes(self, sample_snapshot, sample_process_tree):
        """Snapshot.to_dict / from_dict should preserve processes."""
        sample_snapshot.processes = {
            str(pid): asdict(info) for pid, info in sample_process_tree.items()
        }

        d = sample_snapshot.to_dict()
        assert "processes" in d
        assert "1" in d["processes"]
        assert d["processes"]["1"]["name"] == "systemd"
        assert d["processes"]["3034"]["has_network"] is True

        # Round-trip
        raw = sample_snapshot.to_json()
        restored = Snapshot.from_json(raw)
        assert "1" in restored.processes
        assert restored.processes["1"]["name"] == "systemd"
        assert restored.processes["3034"]["children"] == []

    def test_snapshot_without_processes(self, sample_snapshot):
        """Snapshot with empty processes should serialize/deserialize correctly."""
        sample_snapshot.processes = {}
        d = sample_snapshot.to_dict()
        assert d["processes"] == {}

        restored = Snapshot.from_dict(d)
        assert restored.processes == {}
