"""KPortWatch TUI — Process tree screen.

Displays a hierarchical tree of all running processes, with
network-active processes highlighted. Built on Textual's Tree widget.

Keyboard shortcuts:
  Enter — expand/collapse selected node
  k     — kill selected process
  /     — filter by process name/cmdline
  Esc   — close screen
"""
from __future__ import annotations

import asyncio
import contextlib
import logging
import os
import signal
import time

from backend.models import ProcessInfo
from backend.parsers.process_tree import get_tree_roots
from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.containers import Horizontal, Vertical
from textual.screen import ModalScreen, Screen
from textual.widgets import Button, Footer, Header, Input, Label, Static, Tree

from tui.data.provider import DataProvider

log = logging.getLogger(__name__)


class ProcessTreeScreen(Screen):
    """Full-screen process tree view with expand/collapse and filtering."""

    BINDINGS = [
        Binding("escape", "close", "Back", show=True),
        Binding("k", "kill", "Kill", show=True),
        Binding("slash", "search", "Search", show=True),
        Binding("f", "search", "Filter", show=False),
    ]

    CSS = """
    ProcessTreeScreen {
        layout: vertical;
    }
    #tree-info {
        height: auto;
        padding: 0 1;
        background: $surface;
    }
    #search-input.hidden {
        display: none;
    }
    #process-tree {
        height: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        self.provider: DataProvider | None = None  # resolved in on_mount
        self._processes: dict[int, ProcessInfo] = {}
        self._filter_text: str = ""
        # O7: Preserve expand/collapse state across refreshes
        self._expanded_pids: set[int] = set()
        # PID → TreeNode mapping for in-place label updates
        self._pid_to_node: dict[int, object] = {}
        # Two-tier hashing: structure (PIDs, parent-child) vs display (state, network)
        self._last_structure_hash: int | None = None
        self._last_display_hash: int | None = None
        self._last_filter: str = ""

    # ── Layout ────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Input(
            placeholder="Filter processes (Esc to close)...",
            id="search-input",
            classes="hidden",
        )
        tree = Tree("Processes", id="process-tree")
        # Disable Textual's auto_expand — it uses toggle() which collapses
        # nodes that are already expanded programmatically via _restore_expand_state.
        # We handle expand/collapse state ourselves via on_tree_node_expanded/collapsed.
        tree.auto_expand = False
        yield tree
        yield Static(id="tree-info")
        yield Footer()

    def on_mount(self) -> None:
        # Resolve data provider after widget is mounted (self.app is available)
        from tui.utils.provider import get_app_provider
        self.provider = get_app_provider(self.app)

        self.refresh_data()
        # O17: Auto-refresh every 2s like other screens
        self._refresh_handle = self.set_interval(2.0, self.refresh_data)

    def on_unmount(self) -> None:
        """Stop the refresh interval when screen is closed."""
        if hasattr(self, '_refresh_handle') and self._refresh_handle:
            self._refresh_handle.stop()

    # ── Data refresh ──────────────────────────────────────────
    @work(exclusive=True)
    async def refresh_data(self) -> None:
        """Fetch latest snapshot and update the process tree.

        Uses two-tier hashing to avoid unnecessary tree rebuilds:
        - Structure hash (PIDs, parent-child): triggers full rebuild
        - Display hash (state, network, cmdline): triggers in-place label update
        This prevents the tree from collapsing on every refresh.
        """
        snapshot = await __import__("asyncio").to_thread(self.provider.fetch)
        if snapshot is None:
            try:
                info = self.query_one("#tree-info", Static)
                info.update("[dim]Waiting for daemon data...[/]")
            except Exception:
                pass
            return

        # Parse processes from flat dict
        processes: dict[int, ProcessInfo] = {}
        raw = getattr(snapshot, "processes", {}) or {}
        for _pid_str, data in raw.items():
            try:
                info = ProcessInfo.from_dict(data)
                processes[info.pid] = info
            except Exception:
                continue

        self._processes = processes

        # Two-tier update strategy to prevent tree collapse
        structure_hash = self._compute_structure_hash(processes)
        display_hash = self._compute_display_hash(processes)
        filter_changed = self._filter_text != self._last_filter

        if structure_hash == self._last_structure_hash and not filter_changed:
            if display_hash == self._last_display_hash:
                return  # Nothing changed at all
            # Only display data changed — update labels in-place, no rebuild
            self._update_labels_in_place()
            self._last_display_hash = display_hash
            return

        # Structure or filter changed — full rebuild
        self._last_structure_hash = structure_hash
        self._last_display_hash = display_hash
        self._last_filter = self._filter_text
        self._rebuild_tree()

    def _compute_structure_hash(self, processes: dict[int, ProcessInfo]) -> int:
        """Hash of PIDs and parent-child relationships only.

        Changes when processes appear/disappear or parent relationships change.
        Triggers a full tree rebuild when this changes.
        """
        try:
            items = tuple(
                (pid, tuple(sorted(p.children)))
                for pid, p in sorted(processes.items())
            )
            return hash(items)
        except Exception:
            return hash(time.time())

    def _compute_display_hash(self, processes: dict[int, ProcessInfo]) -> int:
        """Hash of display-relevant data: state, network flag, cmdline.

        Changes when a process state flips (S↔R) or network status changes.
        Triggers an in-place label update only — no tree rebuild.
        """
        try:
            items = tuple(
                (pid, p.has_network, p.name, p.state, p.cmdline)
                for pid, p in sorted(processes.items())
            )
            return hash(items)
        except Exception:
            return hash(time.time())

    # ── Label building ────────────────────────────────────────
    @staticmethod
    def _make_node_label(info: ProcessInfo) -> str:
        """Build the display label for a process node."""
        state_colors = {
            "S": "dim",    # sleeping — dim
            "R": "bold",   # running — bold
            "Z": "red",    # zombie — red
            "T": "yellow", # stopped — yellow
            "D": "yellow", # disk sleep — yellow
        }
        state_style = state_colors.get(info.state, "")

        net_marker = "[green]*[/] " if info.has_network else "  "
        cmdline_short = (info.cmdline[:40] + "…") if len(info.cmdline) > 40 else info.cmdline

        label = (
            f"{net_marker}"
            f"[{state_style}]{info.name}[/] "
            f"[dim](PID {info.pid})[/]"
        )
        if cmdline_short and cmdline_short != info.name:
            label += f" [dim]{cmdline_short}[/]"
        return label

    def _update_labels_in_place(self) -> None:
        """Update node labels without clearing the tree.

        Called when only display data changed (state, network, cmdline)
        but the tree structure (PIDs, parent-child) is the same.
        This avoids the visual collapse caused by tree.clear().
        """
        for pid, node in self._pid_to_node.items():
            info = self._processes.get(pid)
            if info is None:
                continue
            with contextlib.suppress(Exception):
                node.set_label(self._make_node_label(info))

    # ── Tree rendering ────────────────────────────────────────
    def _rebuild_tree(self) -> None:
        """Rebuild the Tree widget from current process data.

        O7: Preserves expand/collapse state across refreshes by
        saving and restoring which nodes are expanded.
        """
        try:
            # O7: Save current expanded state before rebuilding
            self._save_expand_state()

            tree = self.query_one("#process-tree", Tree)

            # Save the currently focused node's PID to prevent scroll jumps
            focused_pid = None
            if getattr(tree, "cursor_node", None) and getattr(tree.cursor_node, "data", None):
                focused_pid = tree.cursor_node.data

            self._pid_to_node.clear()
            tree.clear()

            if not self._processes:
                tree.root.add_leaf("[dim]No process data — daemon running?[/]")
                tree.root.expand()
                return

            roots = get_tree_roots(self._processes)

            for root_pid in roots:
                self._add_node(tree.root, root_pid)

            tree.root.expand()
            # Auto-expand first level
            for child in tree.root.children:
                child.expand()

            # O7: Restore previously expanded nodes
            self._restore_expand_state(tree)

            # Restore cursor to prevent view jumping to top
            if focused_pid is not None:
                def _find_and_focus(node):
                    if getattr(node, "data", None) == focused_pid:
                        import contextlib

                        with contextlib.suppress(Exception):
                            tree.cursor_line = node.line
                        return True
                    return any(_find_and_focus(child) for child in getattr(node, 'children', []))
                _find_and_focus(tree.root)

            # Update info bar
            total = len(self._processes)
            network = sum(1 for p in self._processes.values() if p.has_network)
            info = self.query_one("#tree-info", Static)
            info.update(
                f"[bold]{total}[/] processes  |  "
                f"[green]{network} with network[/]  |  "
                f"[dim]<k> kill  <Esc> back[/]"
            )
        except Exception as e:
            log.error("Failed to rebuild tree: %s", e, exc_info=True)

    def _add_node(self, parent, pid: int) -> None:
        """Recursively add a process and its children to the tree."""
        info = self._processes.get(pid)
        if info is None:
            return

        # Apply filter
        if self._filter_text and not self._descendant_matches(pid, self._filter_text):
            searchable = f"{info.name} {info.cmdline} {info.pid}".lower()
            if self._filter_text not in searchable:
                return

        label = self._make_node_label(info)

        # Add node — use add if has children, add_leaf if leaf
        children = [c for c in info.children if c in self._processes]
        if children:
            node = parent.add(label, data=pid)
            self._pid_to_node[pid] = node
            for child_pid in children:
                self._add_node(node, child_pid)
        else:
            node = parent.add_leaf(label, data=pid)
            self._pid_to_node[pid] = node

    def _descendant_matches(self, pid: int, text: str) -> bool:
        """Check if any descendant of pid matches the filter text."""
        info = self._processes.get(pid)
        if info is None:
            return False
        for child_pid in info.children:
            child = self._processes.get(child_pid)
            if child:
                searchable = f"{child.name} {child.cmdline} {child.pid}".lower()
                if text in searchable:
                    return True
                if self._descendant_matches(child_pid, text):
                    return True
        return False

    # ── Search/filter ─────────────────────────────────────────
    def on_input_changed(self, event: Input.Changed) -> None:
        """Live-filter the tree as user types."""
        if event.input.id == "search-input":
            self._filter_text = event.value.lower().strip()
            # Invalidate hashes so next refresh will rebuild with new filter
            self._last_structure_hash = None
            self._last_display_hash = None
            self._rebuild_tree()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            self._hide_search()

    # ── Actions ───────────────────────────────────────────────
    def action_close(self) -> None:
        self.app.pop_screen()

    def action_kill(self) -> None:
        """Kill the process currently selected in the tree (with confirmation)."""
        tree = self.query_one("#process-tree", Tree)
        node = tree.get_node_at_line(tree.cursor_line)
        if node is None or node.data is None:
            self.app.notify("No process selected", severity="warning")
            return

        pid = node.data
        info = self._processes.get(pid)
        name = info.name if info else f"PID {pid}"

        # Ask for confirmation before killing
        self.app.push_screen(ProcessKillConfirm(pid, name))

    def action_search(self) -> None:
        """Show the search bar."""
        try:
            search_input = self.query_one("#search-input", Input)
            search_input.remove_class("hidden")
            search_input.focus()
        except Exception:
            pass

    def _hide_search(self) -> None:
        try:
            search_input = self.query_one("#search-input", Input)
            search_input.add_class("hidden")
        except Exception:
            pass

    # ── Tree interaction ──────────────────────────────────────
    def on_tree_node_selected(self, event: Tree.NodeSelected) -> None:
        """Toggle expand/collapse on node selection (Enter or click).

        We handle this manually because auto_expand is disabled to prevent
        Textual's internal toggle from collapsing programmatically expanded nodes.
        """
        node = event.node
        if node.allow_expand:
            node.toggle()

    # ── O7: Expand state persistence ─────────────────────────
    def _save_expand_state(self) -> None:
        """Save which PIDs are currently expanded in the tree.

        Uses cumulative set: does NOT clear, so expand state from manual
        user interactions (on_tree_node_expanded) is preserved even if
        the DOM query fails.
        """
        try:
            tree = self.query_one("#process-tree", Tree)
            # Also collect from current DOM state (handles auto-expanded nodes)
            newly_expanded: set[int] = set()
            self._collect_expanded_into(tree.root, newly_expanded)
            # Merge: keep previously saved + add newly discovered
            self._expanded_pids |= newly_expanded
        except Exception as e:
            log.debug("_save_expand_state DOM query failed: %s", e)

    def _collect_expanded_into(self, node, result: set) -> None:
        """Recursively collect data (PID) of expanded nodes into result set."""
        if not node.is_root and node.is_expanded and node.data is not None:
            result.add(node.data)
        for child in getattr(node, 'children', []):
            self._collect_expanded_into(child, result)

    def on_tree_node_expanded(self, event: Tree.NodeExpanded) -> None:
        """Track user-initiated node expansion to preserve across rebuilds."""
        node = event.node
        if not node.is_root and node.data is not None:
            self._expanded_pids.add(node.data)

    def on_tree_node_collapsed(self, event: Tree.NodeCollapsed) -> None:
        """Track user-initiated node collapse to update saved state."""
        node = event.node
        if not node.is_root and node.data is not None:
            self._expanded_pids.discard(node.data)

    def _restore_expand_state(self, tree: Tree) -> None:
        """Expand nodes whose PID was expanded before the rebuild."""
        if not self._expanded_pids:
            return
        try:
            self._expand_matching(tree.root)
        except Exception as e:
            log.warning("_restore_expand_state failed: %s", e)

    def _expand_matching(self, node) -> None:
        """Recursively expand nodes matching saved PIDs."""
        if not node.is_root and node.data is not None and node.data in self._expanded_pids:
            node.expand()
        for child in getattr(node, 'children', []):
            self._expand_matching(child)


class ProcessKillConfirm(ModalScreen[bool]):
    """Simple kill confirmation dialog for ProcessTreeScreen."""

    CSS = """
    ProcessKillConfirm {
        align: center middle;
    }
    #kill-dialog {
        width: 56;
        max-width: 80;
        height: auto;
        border: round $error;
        background: $surface;
        padding: 1 2;
    }
    #kill-dialog Label {
        margin: 0 0 1 0;
    }
    #kill-buttons {
        height: auto;
        margin: 1 0 0 0;
    }
    #kill-buttons Button {
        margin: 0 1;
    }
    """

    BINDINGS = [
        Binding("escape", "cancel", "Cancel", show=False),
    ]

    def __init__(self, pid: int, name: str) -> None:
        super().__init__()
        self._pid = pid
        self._name = name

    def compose(self) -> ComposeResult:
        with Vertical(id="kill-dialog"):
            yield Label("[bold red]⚠  Kill Process[/]")
            yield Static(f"  Process : [bold]{self._name}[/]")
            yield Static(f"  PID     : [bold]{self._pid}[/]")
            yield Label("")
            with Horizontal(id="kill-buttons"):
                yield Button("SIGTERM (graceful)", variant="warning", id="btn-sigterm")
                yield Button("SIGKILL (force)", variant="error", id="btn-sigkill")
                yield Button("Cancel", variant="default", id="btn-cancel")

    def action_cancel(self) -> None:
        self.dismiss(False)

    def on_button_pressed(self, event: Button.Pressed) -> None:
        btn_id = event.button.id

        if btn_id == "btn-cancel":
            self.dismiss(False)
            return

        # Disable buttons to prevent double-click
        for btn in self.query(Button):
            btn.disabled = True

        if btn_id == "btn-sigterm":
            self.app.run_worker(self._do_kill_sigterm, exclusive=True)
        elif btn_id == "btn-sigkill":
            self.app.run_worker(self._do_kill_sigkill, exclusive=True)

    # ── Async kill workers (non-blocking) ─────────────────────
    async def _do_kill_sigterm(self) -> None:
        """Run SIGTERM in a thread to avoid blocking the TUI."""
        def _kill() -> tuple[bool, str]:
            try:
                os.kill(self._pid, signal.SIGTERM)
                return True, f"Sent SIGTERM to {self._name} (PID {self._pid})"
            except ProcessLookupError:
                return False, f"Process {self._name} (PID {self._pid}) not found"
            except PermissionError:
                return False, f"Permission denied for PID {self._pid}"
            except OSError as e:
                return False, f"Error: {e}"

        success, msg = await asyncio.to_thread(_kill)
        self.app.notify(msg, severity="information" if success else "error")
        self._safe_dismiss(success)

    async def _do_kill_sigkill(self) -> None:
        """Run SIGKILL in a thread to avoid blocking the TUI."""
        def _kill() -> tuple[bool, str]:
            try:
                os.kill(self._pid, signal.SIGKILL)
                return True, f"Force-killed {self._name} (PID {self._pid})"
            except ProcessLookupError:
                return False, f"Process {self._name} (PID {self._pid}) not found"
            except PermissionError:
                return False, f"Permission denied for PID {self._pid}"
            except OSError as e:
                return False, f"Error: {e}"

        success, msg = await asyncio.to_thread(_kill)
        self.app.notify(msg, severity="information" if success else "error")
        self._safe_dismiss(success)

    def _safe_dismiss(self, result: bool) -> None:
        """Dismiss the modal, guarding against the screen already being popped."""
        import contextlib
        with contextlib.suppress(Exception):
            self.dismiss(result)
