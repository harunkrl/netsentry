# Search Bar Redesign: Context-Aware Ephemeral Filtering

**Date:** 2026-06-07
**Status:** Approved

## Problem

1. `/` and `f` keys both open the same search bar — redundant.
2. Typing in the search bar filters **both** `PortTable` and `ConnectionLog` simultaneously. Users need to filter each panel independently.
3. When the search bar (`Input` widget) has focus, `Esc` is captured by Textual's Input and never reaches the Screen bindings. The only way to leave the search bar is `Tab`.
4. The same `Esc` issue exists on the connection map screen.

## Design

### 1. Remove `f` binding

- Remove `Binding("f", "filter_toggle", "Filter", show=True)` from `MainScreen.BINDINGS`.
- Keep only `Binding("slash", "search", "Search", show=True)`.
- Update help screen shortcut table accordingly.

### 2. Context-aware filtering

When `/` is pressed, the search bar filters whichever panel currently has focus:

- If `PortTable` is focused → search filters PortTable only.
- If `ConnectionLog` is focused → search filters ConnectionLog only.
- The filter target is **locked** when the search bar opens. Changing focus while the bar is open does not switch the target.

**Implementation:** `MainScreen._show_search()` inspects `self.focused` before opening the bar. It stores the target widget ID in `self._filter_target: str` (e.g. `"port-table"` or `"connection-log"`). The placeholder text updates accordingly: `"Filter PortTable..."` or `"Filter ConnectionLog..."`.

`on_input_changed` reads `_filter_target` and only calls `set_filter()` on the target widget. The non-target widget is unaffected.

### 3. Ephemeral search bar lifecycle

| Event | Action |
|-------|--------|
| `/` pressed | Store focus target, show bar, focus Input, set placeholder |
| `Enter` pressed (while Input focused) | Hide bar, **preserve filter**, restore focus to target panel |
| `Esc` pressed (while Input focused) | Hide bar, **clear filter**, restore focus to target panel |

**Esc fix:** Override `on_key()` in `MainScreen` to intercept `Escape` when the search Input has focus. This bypasses Textual's default Input key handling. The handler calls `_hide_search()`, clears the filter on the target widget, and restores focus.

The same `on_key()` override is applied to `ConnectionMapScreen`.

### 4. Status bar indicator

When a filter is active, the status bar shows:

```
Filter: 'nginx' → PortTable (5 shown)
```

This makes it visible which panel is being filtered and how many results match.

### 5. Focus management

- `_show_search()` saves the current focused widget reference in `self._focus_before_search`.
- `_hide_search()` restores focus to that widget.
- On `on_screen_resume()`, focus returns to PortTable (existing behavior, unchanged).

## Files Changed

| File | Change |
|------|--------|
| `tui/screens/main_screen.py` | Remove `f` binding; add `_filter_target`, `_focus_before_search` state; update `_show_search`/`_hide_search`/`on_input_changed`; add `on_key` for Esc |
| `tui/screens/connection_map_screen.py` | Add `on_key` Esc handler for search Input |
| `tui/screens/help_screen.py` | Update shortcut table: remove `f`, clarify `/` is context-aware |

## Out of Scope

- Changing how `Ctrl+F` quick-filter cycling works on ConnectionLog (separate mechanism, works fine).
- Adding a "filter both" mode — the user can clear and re-search the other panel.
- Touch/mouse interaction changes.
