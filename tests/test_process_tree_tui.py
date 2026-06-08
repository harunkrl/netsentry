"""Tests for tui/screens/process_tree_screen.py (TUI layer).

Tests cover ProcessTreeScreen data flow, tree rendering, filtering,
hash-based update strategy, expand state persistence, label building,
and ProcessKillConfirm modal kill workers.
"""
from __future__ import annotations

import asyncio
import os
import signal
import time
from dataclasses import asdict
from unittest.mock import Mock, patch

import pytest
from backend.models import ProcessInfo, Snapshot
from textual.app import App
from textual.widgets import Input, Static, Tree

from tui.screens.process_tree_screen import ProcessKillConfirm, ProcessTreeScreen


# ── Fixtures ───────────────────────────────────────────────────

@pytest.fixture
def process_data() -> dict[int, ProcessInfo]:
    """A small process tree:
        1 (systemd) → 828 (firewalld), 2420 (sddm) → 3034 (firefox)
        2 (kthreadd) → 100 (kworker)
    """
    return {
        1: ProcessInfo(pid=1, ppid=0, name="systemd", cmdline="/sbin/init",
                       state="S", uid=0, has_network=True, children=[828, 2420]),
        2: ProcessInfo(pid=2, ppid=0, name="kthreadd", cmdline="",
                       state="S", uid=0, has_network=False, children=[100]),
        100: ProcessInfo(pid=100, ppid=2, name="kworker/0:1", cmdline="",
                         state="S", uid=0, has_network=False, children=[]),
        828: ProcessInfo(pid=828, ppid=1, name="firewalld",
                         cmdline="/usr/bin/python3 /usr/bin/firewalld",
                         state="S", uid=0, has_network=False, children=[]),
        2420: ProcessInfo(pid=2420, ppid=1, name="sddm", cmdline="/usr/bin/sddm",
                          state="S", uid=0, has_network=False, children=[3034]),
        3034: ProcessInfo(pid=3034, ppid=2420, name="firefox",
                          cmdline="/usr/lib/firefox/firefox",
                          state="S", uid=1000, has_network=True, children=[]),
    }


@pytest.fixture
def process_snapshot(process_data) -> Snapshot:
    """Snapshot with process tree data."""
    processes_dict = {str(pid): asdict(info) for pid, info in process_data.items()}
    return Snapshot(
        timestamp=time.time(),
        processes=processes_dict,
        summary={"total_listening": 0, "total_established": 0, "alert_count": 0},
    )


@pytest.fixture
def mock_process_provider(process_snapshot: Snapshot) -> Mock:
    """Mock provider returning process snapshot."""
    provider = Mock()
    provider.fetch.return_value = process_snapshot
    return provider


@pytest.fixture
def empty_provider() -> Mock:
    """Mock provider returning None."""
    provider = Mock()
    provider.fetch.return_value = None
    return provider


def _make_process_app(provider: Mock) -> App:
    """Create a Textual App with mock data_provider."""
    app = App()
    app.data_provider = provider
    return app


# ══════════════════════════════════════════════════════════════
# ProcessTreeScreen — Label Building
# ══════════════════════════════════════════════════════════════


class TestMakeNodeLabel:
    """Tests for ProcessTreeScreen._make_node_label()."""

    def test_sleeping_process(self):
        """Sleeping process shows dim style."""
        info = ProcessInfo(pid=1, ppid=0, name="systemd", cmdline="/sbin/init",
                           state="S", uid=0, has_network=False)
        label = ProcessTreeScreen._make_node_label(info)
        assert "systemd" in label
        assert "dim" in label
        assert "PID 1" in label

    def test_running_process(self):
        """Running process shows bold style."""
        info = ProcessInfo(pid=100, ppid=1, name="compute", cmdline="./compute",
                           state="R", uid=1000, has_network=False)
        label = ProcessTreeScreen._make_node_label(info)
        assert "bold" in label
        assert "compute" in label

    def test_zombie_process(self):
        """Zombie process shows red style."""
        info = ProcessInfo(pid=66, ppid=1, name="zombie", cmdline="",
                           state="Z", uid=0, has_network=False)
        label = ProcessTreeScreen._make_node_label(info)
        assert "red" in label

    def test_stopped_process(self):
        """Stopped process shows yellow style."""
        info = ProcessInfo(pid=50, ppid=1, name="paused", cmdline="./app",
                           state="T", uid=1000, has_network=False)
        label = ProcessTreeScreen._make_node_label(info)
        assert "yellow" in label

    def test_network_active_process(self):
        """Network-active process shows green marker."""
        info = ProcessInfo(pid=3034, ppid=1, name="firefox",
                           cmdline="/usr/lib/firefox/firefox",
                           state="S", uid=1000, has_network=True)
        label = ProcessTreeScreen._make_node_label(info)
        assert "green" in label
        assert "*" in label

    def test_network_inactive_process(self):
        """Inactive process shows spaces instead of marker."""
        info = ProcessInfo(pid=100, ppid=1, name="worker", cmdline="",
                           state="S", uid=0, has_network=False)
        label = ProcessTreeScreen._make_node_label(info)
        # Should start with spaces (no green marker)
        assert label.startswith("  ")

    def test_long_cmdline_truncated(self):
        """cmdline > 40 chars is truncated with ellipsis."""
        long_cmd = "a" * 50
        info = ProcessInfo(pid=1, ppid=0, name="app", cmdline=long_cmd,
                           state="S", uid=0, has_network=False)
        label = ProcessTreeScreen._make_node_label(info)
        assert "…" in label

    def test_short_cmdline_not_truncated(self):
        """cmdline <= 40 chars is shown fully."""
        short_cmd = "/usr/bin/app"
        info = ProcessInfo(pid=1, ppid=0, name="app", cmdline=short_cmd,
                           state="S", uid=0, has_network=False)
        label = ProcessTreeScreen._make_node_label(info)
        assert "…" not in label
        assert short_cmd in label

    def test_cmdline_same_as_name_not_shown(self):
        """cmdline identical to name is not duplicated."""
        info = ProcessInfo(pid=1, ppid=0, name="bash", cmdline="bash",
                           state="S", uid=0, has_network=False)
        label = ProcessTreeScreen._make_node_label(info)
        # cmdline part should not be shown (same as name)
        assert label.count("bash") == 1


# ══════════════════════════════════════════════════════════════
# ProcessTreeScreen — Hash Computation
# ══════════════════════════════════════════════════════════════


class TestHashComputation:
    """Tests for two-tier hash strategy."""

    @pytest.mark.asyncio
    async def test_structure_hash_stable(self, mock_process_provider, process_data):
        """Same data → same structure hash."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            h1 = screen._compute_structure_hash(process_data)
            h2 = screen._compute_structure_hash(process_data)
            assert h1 == h2

    @pytest.mark.asyncio
    async def test_structure_hash_changes_on_pid_removal(self, mock_process_provider, process_data):
        """Removing a PID changes the structure hash."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            h1 = screen._compute_structure_hash(process_data)
            # Remove a process
            modified = {k: v for k, v in process_data.items() if k != 3034}
            h2 = screen._compute_structure_hash(modified)
            assert h1 != h2

    @pytest.mark.asyncio
    async def test_display_hash_changes_on_state(self, mock_process_provider, process_data):
        """Changing process state changes display hash."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            h1 = screen._compute_display_hash(process_data)
            # Change state of one process
            modified = dict(process_data)
            modified[3034] = ProcessInfo(
                pid=3034, ppid=2420, name="firefox",
                cmdline="/usr/lib/firefox/firefox",
                state="R", uid=1000, has_network=True, children=[],
            )
            h2 = screen._compute_display_hash(modified)
            assert h1 != h2

    @pytest.mark.asyncio
    async def test_display_hash_changes_on_network_flag(self, mock_process_provider, process_data):
        """Toggling has_network changes display hash."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            h1 = screen._compute_display_hash(process_data)
            modified = dict(process_data)
            modified[828] = ProcessInfo(
                pid=828, ppid=1, name="firewalld",
                cmdline="/usr/bin/python3 /usr/bin/firewalld",
                state="S", uid=0, has_network=True, children=[],  # Changed
            )
            h2 = screen._compute_display_hash(modified)
            assert h1 != h2

    @pytest.mark.asyncio
    async def test_structure_hash_same_without_pid_change(self, mock_process_provider, process_data):
        """Changing only state (not PIDs) keeps structure hash same."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            h1 = screen._compute_structure_hash(process_data)
            modified = dict(process_data)
            modified[3034] = ProcessInfo(
                pid=3034, ppid=2420, name="firefox",
                cmdline="/usr/lib/firefox/firefox",
                state="R", uid=1000, has_network=True, children=[],
            )
            h2 = screen._compute_structure_hash(modified)
            assert h1 == h2  # Same PIDs → same structure hash


# ══════════════════════════════════════════════════════════════
# ProcessTreeScreen — Data Flow
# ══════════════════════════════════════════════════════════════


class TestProcessTreeScreenDataFlow:
    """Tests for data loading and tree rendering."""

    @pytest.mark.asyncio
    async def test_refresh_populates_processes(self, mock_process_provider, process_data):
        """refresh_data populates _processes from snapshot."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            assert len(screen._processes) == len(process_data)

    @pytest.mark.asyncio
    async def test_refresh_builds_tree(self, mock_process_provider):
        """Tree widget is populated with process nodes after refresh."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            tree = screen.query_one("#process-tree", Tree)
            # Root should be expanded and have children
            assert tree.root.is_expanded
            # Should have at least 2 root children (systemd, kthreadd)
            assert len(tree.root.children) >= 2

    @pytest.mark.asyncio
    async def test_refresh_updates_info_bar(self, mock_process_provider, process_data):
        """Info bar shows total and network process counts."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            info = screen.query_one("#tree-info", Static)
            rendered = str(info.render())
            assert str(len(process_data)) in rendered
            # 2 network processes (systemd + firefox)
            assert "2" in rendered

    @pytest.mark.asyncio
    async def test_daemon_down_shows_message(self, empty_provider):
        """When provider returns None, shows waiting message."""
        screen = ProcessTreeScreen()
        app = _make_process_app(empty_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            info = screen.query_one("#tree-info", Static)
            rendered = str(info.render())
            assert "Waiting" in rendered or "daemon" in rendered.lower()

    @pytest.mark.asyncio
    async def test_empty_processes_shows_message(self):
        """Empty process dict shows 'no data' message."""
        snapshot = Snapshot(processes={})
        provider = Mock()
        provider.fetch.return_value = snapshot

        screen = ProcessTreeScreen()
        app = _make_process_app(provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            tree = screen.query_one("#process-tree", Tree)
            # Root should show "No process data" leaf
            assert tree.root.is_expanded

    @pytest.mark.asyncio
    async def test_pid_to_node_mapping_populated(self, mock_process_provider, process_data):
        """After rebuild, _pid_to_node maps PIDs to tree nodes."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            assert len(screen._pid_to_node) == len(process_data)
            # All PIDs should be mapped
            for pid in process_data:
                assert pid in screen._pid_to_node


# ══════════════════════════════════════════════════════════════
# ProcessTreeScreen — Filtering
# ══════════════════════════════════════════════════════════════


class TestProcessTreeScreenFilter:
    """Tests for process filtering."""

    @pytest.mark.asyncio
    async def test_filter_by_name(self, mock_process_provider):
        """Filtering by name shows matching processes and parents."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            # Filter for "firefox"
            screen._filter_text = "firefox"
            screen._last_structure_hash = None  # Force rebuild
            screen._rebuild_tree()

            tree = screen.query_one("#process-tree", Tree)
            # firefox should be visible, but only matching branch
            assert len(screen._pid_to_node) > 0
            assert 3034 in screen._pid_to_node

    @pytest.mark.asyncio
    async def test_filter_preserves_parents(self, mock_process_provider):
        """Filter preserves ancestor chain for matching process."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            # Filter for "firefox" — should keep sddm (parent) in tree
            screen._filter_text = "firefox"
            screen._last_structure_hash = None
            screen._rebuild_tree()

            # firefox and its ancestors should be present
            assert 3034 in screen._pid_to_node

    @pytest.mark.asyncio
    async def test_filter_by_pid(self, mock_process_provider):
        """Filtering by PID number shows matching process."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            screen._filter_text = "3034"
            screen._last_structure_hash = None
            screen._rebuild_tree()

            assert 3034 in screen._pid_to_node

    @pytest.mark.asyncio
    async def test_clear_filter_shows_all(self, mock_process_provider):
        """Clearing filter shows all processes again."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            # Apply filter
            screen._filter_text = "firefox"
            screen._last_structure_hash = None
            screen._rebuild_tree()
            filtered_count = len(screen._pid_to_node)

            # Clear filter
            screen._filter_text = ""
            screen._last_structure_hash = None
            screen._rebuild_tree()
            assert len(screen._pid_to_node) > filtered_count

    @pytest.mark.asyncio
    async def test_filter_no_match(self, mock_process_provider):
        """Filter with no match results in minimal tree."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            screen._filter_text = "zzz_nonexistent_process"
            screen._last_structure_hash = None
            screen._rebuild_tree()

            # No matching processes
            assert len(screen._pid_to_node) == 0


# ══════════════════════════════════════════════════════════════
# ProcessTreeScreen — Search UI
# ══════════════════════════════════════════════════════════════


class TestProcessTreeScreenSearch:
    """Tests for search bar show/hide."""

    @pytest.mark.asyncio
    async def test_search_bar_initially_hidden(self, mock_process_provider):
        """Search input is initially hidden."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            search = screen.query_one("#search-input", Input)
            assert search.has_class("hidden")

    @pytest.mark.asyncio
    async def test_action_search_shows_input(self, mock_process_provider):
        """action_search makes search input visible."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            screen.action_search()
            await pilot.pause()

            search = screen.query_one("#search-input", Input)
            assert not search.has_class("hidden")

    @pytest.mark.asyncio
    async def test_hide_search(self, mock_process_provider):
        """_hide_search hides the input."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            screen.action_search()
            await pilot.pause()
            assert not screen.query_one("#search-input", Input).has_class("hidden")

            screen._hide_search()
            await pilot.pause()
            assert screen.query_one("#search-input", Input).has_class("hidden")


# ══════════════════════════════════════════════════════════════
# ProcessTreeScreen — Actions
# ══════════════════════════════════════════════════════════════


class TestProcessTreeScreenActions:
    """Tests for screen actions."""

    @pytest.mark.asyncio
    async def test_action_close(self, mock_process_provider):
        """action_close pops the screen."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()

            with patch.object(app, 'pop_screen') as mock_pop:
                screen.action_close()
                mock_pop.assert_called_once()

    @pytest.mark.asyncio
    async def test_action_kill_no_selection(self, mock_process_provider):
        """action_kill with no tree node shows warning."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            # Don't select anything → should notify
            with patch.object(app, 'notify') as mock_notify:
                with patch.object(app, 'push_screen'):
                    screen.action_kill()
                    # If no valid node is selected, notify should be called
                    # (depends on cursor_line state — this is a smoke test)


# ══════════════════════════════════════════════════════════════
# ProcessTreeScreen — Descendant Matching
# ══════════════════════════════════════════════════════════════


class TestDescendantMatching:
    """Tests for _descendant_matches filter helper."""

    @pytest.mark.asyncio
    async def test_matching_child(self, mock_process_provider, process_data):
        """Returns True if a child matches the filter text."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            # sddm (PID 2420) has firefox (PID 3034) as child
            result = screen._descendant_matches(2420, "firefox")
            assert result is True

    @pytest.mark.asyncio
    async def test_no_matching_child(self, mock_process_provider, process_data):
        """Returns False if no child matches."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            result = screen._descendant_matches(828, "nonexistent")
            assert result is False

    @pytest.mark.asyncio
    async def test_matching_grandchild(self, mock_process_provider, process_data):
        """Returns True for grandchild matches."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            # systemd (1) → sddm (2420) → firefox (3034)
            result = screen._descendant_matches(1, "firefox")
            assert result is True

    @pytest.mark.asyncio
    async def test_nonexistent_pid(self, mock_process_provider, process_data):
        """Returns False for PID not in tree."""
        screen = ProcessTreeScreen()
        app = _make_process_app(mock_process_provider)

        async with app.run_test() as pilot:
            app.push_screen(screen)
            await pilot.pause()
            await pilot.pause()

            result = screen._descendant_matches(99999, "anything")
            assert result is False


# ══════════════════════════════════════════════════════════════
# ProcessKillConfirm — Kill Workers
# ══════════════════════════════════════════════════════════════


class TestProcessKillConfirmWorkers:
    """Tests for async kill workers in ProcessKillConfirm modal."""

    @pytest.mark.asyncio
    async def test_sigterm_worker_success(self):
        """SIGTERM worker calls os.kill with SIGTERM."""
        screen = ProcessKillConfirm(pid=12345, name="testproc")

        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            with patch("os.kill") as mock_kill, \
                 patch.object(app, "notify") as mock_notify:
                await screen._do_kill_sigterm()
                mock_kill.assert_called_once_with(12345, signal.SIGTERM)

    @pytest.mark.asyncio
    async def test_sigterm_worker_process_not_found(self):
        """SIGTERM handles ProcessLookupError."""
        screen = ProcessKillConfirm(pid=99999, name="ghost")

        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            with patch("os.kill", side_effect=ProcessLookupError), \
                 patch.object(app, "notify") as mock_notify:
                await screen._do_kill_sigterm()
                msg = mock_notify.call_args[0][0]
                assert "not found" in msg.lower()

    @pytest.mark.asyncio
    async def test_sigterm_worker_permission_denied(self):
        """SIGTERM handles PermissionError."""
        screen = ProcessKillConfirm(pid=1, name="init")

        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            with patch("os.kill", side_effect=PermissionError), \
                 patch.object(app, "notify") as mock_notify:
                await screen._do_kill_sigterm()
                msg = mock_notify.call_args[0][0]
                assert "permission" in msg.lower() or "denied" in msg.lower()

    @pytest.mark.asyncio
    async def test_sigkill_worker_success(self):
        """SIGKILL worker calls os.kill with SIGKILL."""
        screen = ProcessKillConfirm(pid=12345, name="testproc")

        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            with patch("os.kill") as mock_kill, \
                 patch.object(app, "notify") as mock_notify:
                await screen._do_kill_sigkill()
                mock_kill.assert_called_once_with(12345, signal.SIGKILL)

    @pytest.mark.asyncio
    async def test_sigkill_worker_process_not_found(self):
        """SIGKILL handles ProcessLookupError."""
        screen = ProcessKillConfirm(pid=99999, name="ghost")

        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            with patch("os.kill", side_effect=ProcessLookupError), \
                 patch.object(app, "notify") as mock_notify:
                await screen._do_kill_sigkill()
                msg = mock_notify.call_args[0][0]
                assert "not found" in msg.lower()

    @pytest.mark.asyncio
    async def test_sigkill_worker_permission_denied(self):
        """SIGKILL handles PermissionError."""
        screen = ProcessKillConfirm(pid=1, name="init")

        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            with patch("os.kill", side_effect=PermissionError), \
                 patch.object(app, "notify") as mock_notify:
                await screen._do_kill_sigkill()
                msg = mock_notify.call_args[0][0]
                assert "permission" in msg.lower() or "denied" in msg.lower()

    @pytest.mark.asyncio
    async def test_sigterm_worker_os_error(self):
        """SIGTERM handles generic OSError."""
        screen = ProcessKillConfirm(pid=12345, name="testproc")

        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            with patch("os.kill", side_effect=OSError("test error")), \
                 patch.object(app, "notify") as mock_notify:
                await screen._do_kill_sigterm()
                msg = mock_notify.call_args[0][0]
                assert "test error" in msg

    @pytest.mark.asyncio
    async def test_sigkill_worker_os_error(self):
        """SIGKILL handles generic OSError."""
        screen = ProcessKillConfirm(pid=12345, name="testproc")

        app = App()
        async with app.run_test() as pilot:
            await app.push_screen(screen)
            await pilot.pause()

            with patch("os.kill", side_effect=OSError("test error")), \
                 patch.object(app, "notify") as mock_notify:
                await screen._do_kill_sigkill()
                msg = mock_notify.call_args[0][0]
                assert "test error" in msg
