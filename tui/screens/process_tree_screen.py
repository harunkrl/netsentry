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

import logging
import os
import signal
import time
from dataclasses import asdict
from typing import Dict, Optional

from textual import work
from textual.app import ComposeResult
from textual.binding import Binding
from textual.screen import Screen
from textual.widgets import Header, Footer, Tree, Static, Input
from textual.containers import Vertical

from backend.models import ProcessInfo, Snapshot
from backend.parsers.process_tree import get_tree_roots
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
    #search-bar {
        height: auto;
        display: none;
        margin: 0 1;
    }
    #search-input {
        width: 100%;
    }
    #process-tree {
        height: 1fr;
    }
    """

    def __init__(self) -> None:
        super().__init__()
        # Y15: Use singleton provider from app if available
        app = self.app
        self.provider = getattr(app, 'data_provider', None) or DataProvider()
        self._processes: Dict[int, ProcessInfo] = {}
        self._filter_text: str = ""
        # O7: Preserve expand/collapse state across refreshes
        self._expanded_pids: set[int] = set()
        # Track last rebuild data hash to skip unnecessary rebuilds
        self._last_data_hash: Optional[int] = None
        self._last_filter: str = ""

    # ── Layout ────────────────────────────────────────────────
    def compose(self) -> ComposeResult:
        yield Header(show_clock=True)
        yield Input(
            placeholder="Filter processes (Esc to close)...",
            id="search-input",
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
        self.refresh_data()
        # O17: Auto-refresh every 2s like other screens
        self._refresh_handle = self.set_interval(2.0, self.refresh_data)

    # ── Data refresh ──────────────────────────────────────────
    @work(exclusive=True)
    async def refresh_data(self) -> None:
        """Fetch latest snapshot and rebuild the process tree."""
        snapshot = await __import__("asyncio").to_thread(self.provider.fetch)
        if snapshot is None:
            try:
                info = self.query_one("#tree-info", Static)
                info.update("[dim]Waiting for daemon data...[/]")
            except Exception:
                pass
            return

        # Parse processes from flat dict
        processes: Dict[int, ProcessInfo] = {}
        raw = getattr(snapshot, "processes", {}) or {}
        for pid_str, data in raw.items():
            try:
                info = ProcessInfo.from_dict(data)
                processes[info.pid] = info
            except Exception:
                continue

        self._processes = processes
        # Skip rebuild if data and filter haven't changed
        current_hash = self._compute_data_hash(processes)
        if current_hash == self._last_data_hash and self._filter_text == self._last_filter:
            return
        self._last_data_hash = current_hash
        self._last_filter = self._filter_text
        self._rebuild_tree()

    def _compute_data_hash(self, processes: Dict[int, ProcessInfo]) -> int:
        """Compute a lightweight hash of process data to detect changes."""
        try:
            # Hash based on PIDs, parent relationships, and network state
            items = tuple(
                (pid, tuple(sorted(p.children)), p.has_network, p.name, p.state)
                for pid, p in sorted(processes.items())
            )
            return hash(items)
        except Exception:
            return object()  # Always trigger rebuild on error

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
                        try:
                            # Use cursor_line, cursor_node has no setter
                            tree.cursor_line = node.line
                        except Exception:
                            pass
                        return True
                    for child in getattr(node, 'children', []):
                        if _find_and_focus(child):
                            return True
                    return False
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
        if self._filter_text:
            searchable = f"{info.name} {info.cmdline} {info.pid}".lower()
            # Also check children — keep node if any descendant matches
            if not self._descendant_matches(pid, self._filter_text):
                if self._filter_text not in searchable:
                    return

        # Build label
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

        # Add node — use add_leaf if no children, add if has children
        children = [c for c in info.children if c in self._processes]
        if children:
            node = parent.add(label, data=pid)
            for child_pid in children:
                self._add_node(node, child_pid)
        else:
            parent.add_leaf(label, data=pid)

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
            # Invalidate hash so next refresh will rebuild with new filter
            self._last_data_hash = None
            self._rebuild_tree()

    def on_input_submitted(self, event: Input.Submitted) -> None:
        if event.input.id == "search-input":
            self._hide_search()

    # ── Actions ───────────────────────────────────────────────
    def action_close(self) -> None:
        self.app.pop_screen()

    def action_kill(self) -> None:
        """Kill the process currently selected in the tree."""
        tree = self.query_one("#process-tree", Tree)
        node = tree.get_node_at_line(tree.cursor_line)
        if node is None or node.data is None:
            self.app.notify("No process selected", severity="warning")
            return

        pid = node.data
        info = self._processes.get(pid)
        name = info.name if info else f"PID {pid}"

        try:
            os.kill(pid, signal.SIGTERM)
            self.app.notify(f"Sent SIGTERM to {name} (PID {pid})", severity="information")
            # Refresh after a brief delay
            self.set_timer(1.0, self.refresh_data)
        except ProcessLookupError:
            self.app.notify(f"Process {name} (PID {pid}) not found", severity="error")
        except PermissionError:
            self.app.notify(f"Permission denied for PID {pid}", severity="error")
        except OSError as e:
            self.app.notify(f"Error: {e}", severity="error")

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
