# Implementation Plan: Context-Aware Ephemeral Search Bar

**Spec:** `docs/superpowers/specs/2026-06-07-search-bar-redesign.md`

## Step 1: Remove `f` binding from MainScreen

**File:** `tui/screens/main_screen.py`

- Remove `Binding("f", "filter_toggle", "Filter", show=True)` from `BINDINGS`
- Remove `action_filter_toggle()` method entirely

## Step 2: Add filter target state to MainScreen

**File:** `tui/screens/main_screen.py`

- Add instance variables in `__init__`:
  - `self._filter_target: str = ""` — widget ID being filtered (`"port-table"` or `"connection-log"`)
  - `self._focus_before_search: object = None` — widget to restore focus to

## Step 3: Update `_show_search()` for context-aware targeting

**File:** `tui/screens/main_screen.py`

- In `_show_search()`:
  1. Inspect `self.focused` to determine target panel
  2. Default to `"port-table"` if focus isn't on a panel
  3. Store target in `self._filter_target`
  4. Store focused widget in `self._focus_before_search`
  5. Set placeholder dynamically: `"Filter PortTable..."` or `"Filter ConnectionLog..."`
  6. Show bar and focus Input

## Step 4: Update `on_input_changed()` for targeted filtering

**File:** `tui/screens/main_screen.py`

- Change `on_input_changed()` to read `self._filter_target`
- Only call `set_filter()` on the target widget, leave the other untouched
- Update status bar: `Filter: '{query}' → PortTable (5 shown)`

## Step 5: Update `_hide_search()` to accept `preserve_filter` parameter

**File:** `tui/screens/main_screen.py`

- Add `preserve_filter: bool = False` parameter
- If `preserve_filter=False`: clear filter on target widget, clear Input value
- If `preserve_filter=True`: keep filter active, just hide bar
- Restore focus to `self._focus_before_search`
- Reset `self._filter_target = ""`

## Step 6: Update `on_input_submitted()` — Enter preserves filter

**File:** `tui/screens/main_screen.py`

- Call `self._hide_search(preserve_filter=True)` on Enter

## Step 7: Add `on_key()` for Esc handling in MainScreen

**File:** `tui/screens/main_screen.py`

- Override `on_key()` to intercept `Escape` when search Input has focus
- Call `self._hide_search(preserve_filter=False)` (clear filter)
- This bypasses Textual Input's key capture

## Step 8: Update `action_clear_filter()` for context-aware cleanup

**File:** `tui/screens/main_screen.py`

- Read `self._filter_target` to know which widget to clear
- Clear only the target widget's filter
- Clear status bar filter info
- Hide search bar

## Step 9: Fix Esc in ConnectionMapScreen

**File:** `tui/screens/connection_map_screen.py`

- Remove `Binding("f", "search", "Filter", show=False)` from `BINDINGS` (redundant with `/`)
- Add `on_key()` override to intercept `Escape` when geo-search Input has focus
- Call `self._hide_search()` on Esc

## Step 10: Update help screen

**File:** `tui/screens/help_screen.py`

- Remove `f     — filter` entry from shortcuts
- Update `/     — filter...` entry to say `/     — filter focused panel (PortTable or ConnectionLog)`

## Verification

After all steps:
1. Launch TUI → PortTable focused by default
2. Press `/` → bar appears with placeholder `"Filter PortTable..."`
3. Type text → only PortTable filters, ConnectionLog unchanged
4. Press `Enter` → bar hides, filter stays on PortTable
5. Press `Tab` to focus ConnectionLog
6. Press `/` → bar appears with placeholder `"Filter ConnectionLog..."`
7. Type text → only ConnectionLog filters, PortTable filter still active
8. Press `Esc` → bar hides, ConnectionLog filter clears, PortTable filter unchanged
9. On map screen, press `/` → bar appears, `Esc` closes it
10. `f` key does nothing on both screens
