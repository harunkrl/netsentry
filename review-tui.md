# NetSentry TUI — Code Review

**Reviewer:** automated review agent  
**Date:** 2026-05-30  
**Textual version:** 8.2.7  
**Import test:** ✅ `from tui.netsentry_tui import NetSentryTUI` passes

---

## Summary

The TUI is well-structured with clean separation between screens, widgets, data, and styles. The overall architecture follows Textual conventions correctly. There is **one critical bug** in `port_table.py` (wrong DataTable API call), **one significant UX issue** (blocking `time.sleep` in the event loop during kill), and several minor issues. Files generally score 7–9/10.

---

## File-by-file Review

### 1. `tui/netsentry_tui.py` — App Entry Point  
**Rating: 9/10**

| Aspect | Assessment |
|--------|-----------|
| Textual API | ✅ Correct: `App`, `CSS_PATH`, `BINDINGS`, `on_mount` → `push_screen` |
| sys.path handling | ✅ Project root inserted once, guarded against duplicates |
| CSS_PATH resolution | ✅ Uses `os.path.join(os.path.dirname(__file__), ...)` — absolute via `__file__` |
| Entry point | ✅ Standard `if __name__` guard |
| Duplicate bindings | ⚠️ `Binding("q", "quit")` is defined here AND in `MainScreen` — both fire on `q`. Not harmful (both call `app.exit()`) but redundant. Remove from App or Screen, not both. |

**No code changes needed.**

---

### 2. `tui/screens/main_screen.py` — Main Layout  
**Rating: 8/10**

| Aspect | Assessment |
|--------|-----------|
| compose() pattern | ✅ Correct: yields Header, Horizontal container, StatusBar, Footer |
| set_interval | ✅ Returns `Timer`, stored in `_refresh_handle` |
| on_unmount cleanup | ✅ Calls `_refresh_handle.stop()` |
| query_one usage | ✅ Correct with explicit widget type parameter |
| Error swallowing | ⚠️ Bare `except Exception: pass` in `refresh_data` for each widget — silently hides widget-mount timing issues AND real bugs. Should at least log. |
| action_quit | ⚠️ `self.app.exit()` works but `self.app.exit()` from a Screen is fine. No issue. |
| Provider instantiation | ✅ Created once in `__init__`, shared with KillConfirmScreen |
| CSS | ✅ Inline CSS is valid Textual CSS |

**Issues:**

1. **Silent error swallowing in `refresh_data`** (lines ~62–75) — If a widget has a real error, it will be invisible. At minimum, log it:

```python
# BEFORE (line ~63)
        try:
            port_table = self.query_one("#port-table", PortTable)
            port_table.update_data(snapshot.listening, snapshot.alerts)
        except Exception:
            pass

# AFTER
        try:
            port_table = self.query_one("#port-table", PortTable)
            port_table.update_data(snapshot.listening, snapshot.alerts)
        except Exception:
            import logging
            logging.getLogger("netsentry").debug("port_table update failed", exc_info=True)
```

Same pattern for the other two try/except blocks.

---

### 3. `tui/screens/kill_confirm.py` — Kill Modal  
**Rating: 7/10**

| Aspect | Assessment |
|--------|-----------|
| ModalScreen usage | ✅ Correct: `ModalScreen[Optional[tuple[bool, str]]]` |
| compose() | ✅ Vertical + Horizontal containers, Buttons with IDs |
| dismiss() pattern | ✅ Returns `None` for cancel, `tuple[bool, str]` for results |
| Error handling | ✅ Catches `ProcessLookupError`, `PermissionError` for SIGKILL |
| Inline CSS | ✅ Valid Textual CSS |
| Dead code: unused `import sys, os` | ⚠️ `sys` and `os` (for `os.path`) imported but only `os.kill` is used. The sys.path.insert at module level is redundant since `netsentry_tui.py` already handles it. Not harmful but unnecessary. |

**Issues:**

1. **SIGKILL bypasses DataProvider** (lines ~75–84) — The SIGTERM path goes through `self.provider.kill_process()` which has graceful-then-force logic. But SIGKILL calls `os.kill(pid, sig.SIGKILL)` directly, bypassing the provider's validation. While functional, this duplicates error handling and breaks the provider abstraction.

2. **Duplicate CSS rules** — The `KillConfirmScreen` has CSS both inline (`CSS = "..."`) and in `styles.tcss`. The inline CSS takes precedence. The tcss file has `width: 60` while inline has `width: 64`. This is confusing but not broken.

3. **No validation that `entry.pid` is an `int`** — `entry.pid` is `Optional[int]`, so this is fine, but `os.kill` will raise `TypeError` if somehow a non-int sneaks through. The `if self.entry.pid is None` guard is sufficient.

---

### 4. `tui/widgets/port_table.py` — DataTable Widget  
**Rating: 6/10** ← Critical bug here

| Aspect | Assessment |
|--------|-----------|
| DataTable extension | ✅ Correct subclass pattern |
| cursor_type | ✅ `"row"` is valid |
| zebra_stripes | ✅ Valid |
| Color-coded rows | ✅ Good approach using Rich markup in cell values |
| Column setup | ✅ `if not self.columns` guard with `add_columns` |

**🚨 CRITICAL BUG — `get_row_at()` returns cell values, not row keys**

Lines 99–103 (`get_selected_entry`) and 110–114 (`get_selected_pid`):

```python
def get_selected_entry(self) -> Optional[SocketEntry]:
    try:
        coord = self.cursor_coordinate
        row_key = self.get_row_at(coord.row)  # ← BUG: returns list[CellType], NOT a row key
        return self._row_entries.get(row_key)  # ← Always returns None (dict lookup with a list)
    except Exception:
        return None
```

`DataTable.get_row_at(index)` returns `list[CellType]` (the cell values), **not** the row key string. The code then tries to look up this list in `self._row_entries` (a `dict[str, SocketEntry]`), which will always miss, returning `None`.

**Fix:** Use `coordinate_to_cell_key()` to get the actual row key:

```python
# BEFORE
    def get_selected_entry(self) -> Optional[SocketEntry]:
        try:
            coord = self.cursor_coordinate
            row_key = self.get_row_at(coord.row)
            return self._row_entries.get(row_key)
        except Exception:
            return None

    def get_selected_pid(self) -> Optional[int]:
        try:
            coord = self.cursor_coordinate
            row_key = self.get_row_at(coord.row)
            return self._row_pids.get(row_key)
        except Exception:
            return None

# AFTER
    def get_selected_entry(self) -> Optional[SocketEntry]:
        try:
            cell_key = self.coordinate_to_cell_key(self.cursor_coordinate)
            return self._row_entries.get(cell_key.row_key.value)
        except Exception:
            return None

    def get_selected_pid(self) -> Optional[int]:
        try:
            cell_key = self.coordinate_to_cell_key(self.cursor_coordinate)
            return self._row_pids.get(cell_key.row_key.value)
        except Exception:
            return None
```

> **Impact:** The `k` (kill) action will always show "No row selected" because `get_selected_entry()` always returns `None`. Kill functionality is completely broken.

**Other issues:**

1. **Misleading class-level dicts** (lines 22–23):
```python
class PortTable(DataTable):
    _row_pids: Dict[str, Optional[int]] = {}   # ← class-level, shadowed by __init__
    _row_entries: Dict[str, SocketEntry] = {}   # ← class-level, shadowed by __init__
```
These are dead code because `__init__` reassigns instance attributes. Should be removed to avoid confusion. If someone adds a `PortTable` without calling `__init__` (unlikely but possible), they'd share class-level state — a classic Python mutable-default bug.

2. **`alert_map.setdefault` only keeps first alert per port** (line 53): If multiple alerts fire for the same port, only the first alert's level is kept. Minor since alerts on the same port tend to have the same level, but worth noting.

---

### 5. `tui/widgets/connection_log.py` — Connection Log  
**Rating: 8/10**

| Aspect | Assessment |
|--------|-----------|
| RichLog usage | ✅ Correct extension |
| auto_scroll / markup | ✅ Set in `on_mount` |
| State colour map | ✅ Comprehensive, covers all TCP states |
| Timestamp formatting | ✅ Clean |

**Issues:**

1. **Log grows unbounded** — `RichLog` accumulates entries indefinitely. With a 2-second refresh interval, after 1 hour there are ~1,800 timestamp headers + thousands of connection entries. Textual's `RichLog` holds everything in memory. Consider adding `self.clear()` at the start of `update_data()`, or using `self.max_lines` if available.

2. **Always writes even with empty data** — If `entries` is empty, it still writes the timestamp header. Not harmful but adds noise.

3. **Duplicate `sys`/`os` sys.path.insert** — Same redundancy as other files; the entry point handles this.

---

### 6. `tui/widgets/status_bar.py` — Status Bar  
**Rating: 9/10**

| Aspect | Assessment |
|--------|-----------|
| Static widget | ✅ Correct base class |
| update_display | ✅ Clean logic with icon selection |
| Edge cases | ✅ Handles `alert_count == 0`, checks for CRITICAL presence |
| Fallback string | ✅ `getattr(a, "level", "")` is defensive |

**Issues:**

1. **Emoji rendering** — `🔒`, `🔴`, `🟡` may not render correctly in all terminal fonts. This is a cosmetic issue, not a bug. Consider ASCII fallback: `[SECURE]`, `[CRITICAL]`, `[WARN]`.

---

### 7. `tui/data/provider.py` — Data Provider  
**Rating: 7/10**

| Aspect | Assessment |
|--------|-----------|
| Fetch logic | ✅ Handles missing file, bad JSON, permission errors |
| Snapshot.from_json | ✅ Delegates to model's robust deserialization |
| Kill validation | ✅ Checks `pid <= 0`, process existence, permissions |
| SIGTERM → SIGKILL escalation | ✅ Correct pattern with 2s timeout |

**Issues:**

1. **🚨 Blocking `time.sleep` in TUI event loop** — `kill_process()` sleeps up to 2.2 seconds total (20 × 0.1s + 0.2s). This is called synchronously from `KillConfirmScreen.on_button_pressed`, which runs inside Textual's async event loop. The entire TUI freezes for up to 2.2 seconds during process termination.

   **Fix:** Run the kill in a worker thread:
   ```python
   # In kill_confirm.py, replace the synchronous call with:
   def on_button_pressed(self, event: Button.Pressed) -> None:
       btn_id = event.button.id
       if btn_id == "btn-cancel":
           self.dismiss(None)
           return
       if self.entry.pid is None:
           self.dismiss((False, "No PID associated with this entry"))
           return
       if btn_id == "btn-sigterm":
           self.app.run_worker(self._do_kill_graceful, exclusive=True)
       elif btn_id == "btn-sigkill":
           self.app.run_worker(self._do_kill_force, exclusive=True)

   async def _do_kill_graceful(self) -> None:
       import asyncio
       success, msg = await asyncio.to_thread(self.provider.kill_process, self.entry.pid)
       self.dismiss((success, msg))

   async def _do_kill_force(self) -> None:
       import asyncio, signal as sig, os
       def _kill():
           try:
               os.kill(self.entry.pid, sig.SIGKILL)
               return True, f"Process {self.entry.pid} force-killed (SIGKILL)"
           except ProcessLookupError:
               return False, f"Process {self.entry.pid} not found"
           except PermissionError:
               return False, f"Permission denied — cannot kill PID {self.entry.pid}"
       success, msg = await asyncio.to_thread(_kill)
       self.dismiss((success, msg))
   ```

2. **Unused import** — `import subprocess` on line 11 is never used.

3. **Potential race: process exits between `os.kill(pid, 0)` check and `os.kill(pid, SIGTERM)`** — This is handled (the `except ProcessLookupError` after SIGTERM catches it), so it's fine.

---

### 8. `tui/styles.tcss` — CSS Theme  
**Rating: 7/10**

| Aspect | Assessment |
|--------|-----------|
| Textual CSS syntax | ✅ Valid |
| `$variable` usage | ✅ Uses `$surface`, `$text`, `$primary` — built-in Textual design variables |
| Selector syntax | ✅ ID selectors (`#port-table`), class selectors (`.alert-critical`) |
| Layout | ✅ `width: 1fr` / `width: 2fr` for horizontal split |

**Issues:**

1. **Duplicate/conflicting rules with inline CSS** — `KillConfirmScreen` and `#kill-dialog` are styled in both `styles.tcss` AND the inline `CSS` attribute of `KillConfirmScreen`. The inline CSS takes precedence. The `styles.tcss` rules for the modal are dead CSS:
   ```css
   /* In styles.tcss — DEAD because KillConfirmScreen.CSS overrides these */
   KillConfirmScreen { ... }
   #kill-dialog { width: 60; ... }
   ```
   **Recommendation:** Remove the modal-related rules from `styles.tcss` (keep them in the inline `CSS` only), OR move them to `styles.tcss` and remove the inline `CSS`. Pick one place.

2. **`#header-bar` CSS may conflict with Header widget's built-in styling** — The Header widget has its own default CSS with `dock: top`. Adding `height: 1` may clip the clock. The `show_clock=True` parameter adds a clock that may need more height.

3. **`.alert-critical`, `.alert-warning`, `.alert-info` classes are never applied** — These CSS classes are defined in `styles.tcss` but no widget ever adds them via `classes=`. The colour coding is done via Rich markup in cell values instead. These are dead CSS rules.

---

### 9. Supporting Files

| File | Status |
|------|--------|
| `tui/__init__.py` | ✅ Clean package marker |
| `tui/screens/__init__.py` | ✅ Clean |
| `tui/widgets/__init__.py` | ✅ Clean |
| `tui/data/__init__.py` | ✅ Clean |
| `backend/models.py` | ✅ Well-structured dataclasses with JSON roundtrip |
| `shared/__init__.py` | ⚠️ `KNOWN_SAFE_PORTS` has duplicate key `631: "cups"` (appears twice in dict literal — Python silently keeps the last one, so no runtime error, but it's a typo). |

---

## Cross-cutting Concerns

### Repetitive `sys.path` Manipulation
Every file except `netsentry_tui.py` and `status_bar.py` contains:
```python
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__)))))
```
The entry point (`netsentry_tui.py`) already handles this. These redundant insertions in every module are noise and should be removed. They work, but they're unnecessary and add maintenance burden.

### Thread Safety
- `DataProvider.fetch()` reads a file synchronously — fast enough at 2s intervals
- `DataProvider.kill_process()` blocks the event loop (see above)
- No shared mutable state between widgets (each has its own data dict) — ✅ safe

### Terminal Resize
- Textual handles resize natively — `1fr`/`2fr` layout adapts
- DataTable has `cursor_coordinate` that resets on `clear()` to `(0,0)` — safe
- RichLog auto-scroll handles resize

### Performance with 100+ Connections
- `clear()` + re-add all rows every 2 seconds — this is fine for DataTable (Textual handles virtual rendering)
- RichLog without `clear()` will accumulate — see connection_log issue above
- No O(n²) patterns detected

---

## Severity Summary

| Severity | Count | Details |
|----------|-------|---------|
| 🚨 Blocker | 1 | `port_table.py`: `get_row_at()` returns wrong type — kill feature is completely broken |
| ⚠️ Significant | 1 | `provider.py` + `kill_confirm.py`: `time.sleep` blocks TUI event loop for up to 2.2s |
| 📝 Minor | 8 | Unused imports, dead CSS, duplicate sys.path, unbounded RichLog, duplicate bindings, duplicate KNOWN_SAFE_PORTS key, dead class-level dicts, silent error swallowing |

---

## Recommended Fix Priority

1. **Fix `get_selected_entry` / `get_selected_pid`** in `port_table.py` — use `coordinate_to_cell_key()` 
2. **Move `kill_process` to a worker thread** to avoid blocking the event loop
3. **Remove unused `import subprocess`** from `provider.py`
4. **Remove redundant `sys.path` inserts** from all non-entry-point files
5. **Remove duplicate modal CSS** from either `styles.tcss` or inline `CSS`
6. **Remove dead alert CSS classes** from `styles.tcss` (or wire them up)
7. **Add `self.clear()`** at start of `ConnectionLog.update_data()` to prevent unbounded growth
8. **Remove duplicate `631` key** from `KNOWN_SAFE_PORTS` in `shared/__init__.py`
9. **Remove class-level mutable defaults** from `PortTable` (the `_row_pids`/`_row_entries` dicts)
10. **Add logging** to bare `except Exception: pass` blocks in `main_screen.py`
