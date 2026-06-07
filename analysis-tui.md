# KPortWatch TUI — Code Quality & UX Review

**Date:** 2026-06-07  
**Scope:** `tui/` directory — all widgets, screens, data, utils, themes  
**Reviewer:** Automated static analysis

---

## Summary

The TUI codebase is well-structured overall. It follows Textual framework conventions, has good separation of concerns between screens/widgets/data, uses diff-based updates to prevent flickering, and includes thoughtful UX features like responsive status bar, auto-scroll detection, and expand-state persistence. However, there are several issues ranging from a bug (duplicate decorator) to UX gaps and performance concerns.

| Severity | Count |
|----------|-------|
| CRITICAL | 1 |
| HIGH | 4 |
| MEDIUM | 9 |
| LOW | 7 |
| INFO | 5 |

---

## CRITICAL

### C1. Duplicate `@staticmethod` decorator — `_build_alert_map` has no effect

**File:** `tui/widgets/port_table.py`, lines 351–352

```python
@staticmethod
@staticmethod
def _build_alert_map(alerts: list) -> dict[int, str]:
```

A double `@staticmethod` decorator is a bug. In CPython, the second `@staticmethod` wrapping the first produces a `staticmethod` object that is **not callable** — it lacks `__call__`. This means `_build_alert_map(...)` will raise `TypeError: 'staticmethod' object is not callable` at runtime whenever `_apply_diff_update()` or `_rebuild_table()` is called with non-empty alert data.

**Impact:** Any snapshot with alerts will crash the port table update path. The `except Exception` handler in `_apply_diff_update` catches it and falls back to `_rebuild_table`, which calls `_build_alert_map` again, triggering the same error, which is caught by its own `except Exception`. The net result: **the port table silently fails to render any data when alerts exist**.

**Fix:** Remove the duplicate decorator (line 351 or 352).

---

## HIGH

### H1. `action_export` blocks the TUI event loop with synchronous I/O

**File:** `tui/screens/main_screen.py`, lines 268–278

```python
def action_export(self) -> None:
    snapshot = self.provider.fetch()   # ← blocking disk I/O on main thread
    if snapshot:
        self._do_export(snapshot)      # ← then spawns background thread
```

The initial `self.provider.fetch()` call is synchronous file I/O (reads the entire JSON snapshot from disk) and runs on the main Textual event loop. If the data file is large or the filesystem is slow (NFS, eCryptfs), this causes a visible TUI freeze. Only the export write (`_do_export`) correctly uses `@work(thread=True)`.

**Fix:** Move the `fetch()` call into the background worker or use `asyncio.to_thread()`.

### H2. ProcessKillConfirm runs `os.kill` synchronously on the main thread

**File:** `tui/screens/process_tree_screen.py`, lines 353–367

```python
def on_button_pressed(self, event: Button.Pressed) -> None:
    ...
    if btn_id == "btn-sigterm":
        os.kill(self._pid, signal.SIGTERM)   # ← main thread
    elif btn_id == "btn-sigkill":
        os.kill(self._pid, signal.SIGKILL)   # ← main thread
```

Unlike `KillConfirmScreen` in `kill_confirm.py` (which correctly uses `asyncio.to_thread`), `ProcessKillConfirm` calls `os.kill()` directly on the main thread. While `os.kill` itself is fast, it violates the pattern established elsewhere and could block briefly if the kernel stall occurs. More importantly, it doesn't use the `DataProvider.kill_process()` method that includes the graceful SIGTERM→wait→SIGKILL escalation with proper error handling.

**Fix:** Use `asyncio.to_thread(self.provider.kill_process, pid)` or replicate the escalation pattern.

### H3. No error recovery when `DataProvider.fetch()` returns `None` initially

**File:** `tui/screens/main_screen.py`, lines 140–160

When the daemon hasn't written its first snapshot yet (e.g., TUI started before daemon), `fetch()` returns `None`. The `_consecutive_failures` counter increments, but the port table remains stuck showing `"Waiting for data..."` and the connection log is empty. There is no user-visible indication that the daemon needs to be started, other than after 3 failures the status bar shows "DAEMON OFFLINE".

However, once the daemon starts, the next successful fetch resets `_consecutive_failures` but never clears the "DAEMON OFFLINE" message from the status bar if it was shown — the status bar is only updated with new data in `refresh_data()` on success, which does overwrite it. This is acceptable but the initial state could be more helpful.

**Note:** This is a UX concern, not a crash bug. A brief "waiting for daemon" notification on first load would improve the experience.

### H4. `_should_show_entry` quick-filter `"warning"` includes `ESTABLISHED` — semantically confusing

**File:** `tui/widgets/connection_log.py`, lines 159–164

```python
if self._quick_filter == "warning":
    return e.state in ("ESTABLISHED", "SYN_SENT", "SYN_RECV")
if self._quick_filter == "critical":
    return e.state in ("ESTABLISHED",)
```

The "warning" quick-filter shows `ESTABLISHED` connections, but `ESTABLISHED` is classified as `INFO` severity by `_severity_for_state()`. The label says "Only WARNING+" but shows INFO-level states. The "critical" filter shows only `ESTABLISHED`, which is actually an INFO state — not typically what users expect "critical" to mean.

This creates an inconsistency between the quick-filter system and the severity filter system. Users applying both filters simultaneously get contradictory results.

**Fix:** Align quick-filter categories with severity categories, or rename the labels to be more descriptive (e.g., "Active connections" instead of "WARNING+").

---

## MEDIUM

### M1. `ConnectionLog._trim_seen()` uses arbitrary eviction — not truly LRU

**File:** `tui/widgets/connection_log.py`, lines 213–217

```python
def _trim_seen(self) -> None:
    if len(self._seen_keys) > _MAX_SEEN:
        excess = len(self._seen_keys) - _MAX_SEEN
        to_remove = list(self._seen_keys)[:excess]  # ← set ordering is arbitrary
        self._seen_keys -= set(to_remove)
```

The comment says "LRU eviction" but `set` ordering is arbitrary in Python (implementation-defined, not insertion order). This means old entries are not reliably evicted — it could remove recently-added keys instead. The `self._seen_keys_deque` field (initialized in `__init__`) is never used at all, suggesting the LRU implementation was started but never completed.

**Fix:** Use `OrderedDict` or the existing `_seen_keys_deque` to implement proper LRU tracking.

### M2. `_mini_sparkline` has a string concatenation bug

**File:** `tui/widgets/traffic_bar.py`, line 41

```python
return f"[{color}]{'' . join(chars)}[/]"
```

There's a spurious space between `''` and `.join(chars)`. While Python parses this correctly (`'' .join(...)` is valid), it's likely unintentional and could be confusing.

**Fix:** Change to `''.join(chars)`.

### M3. `TrafficBar.update_data` performs blocking `ioctl` call for every interface on every refresh

**File:** `tui/widgets/traffic_bar.py`, lines 63–72 and 90

`_get_interface_ip()` uses `fcntl.ioctl(SIOCGIFADDR)` — a blocking syscall. This is called for every interface in every `update_data()` call, which runs every 2 seconds on the main thread. If a network interface is in a transitional state (e.g., VPN connecting), `ioctl` can block for up to several seconds.

**Fix:** Cache IP addresses with a longer TTL (they rarely change), or run IP resolution in a background worker.

### M4. `connection_map_screen.py` — large world map string embedded in source

**File:** `tui/screens/connection_map_screen.py`, lines 39–59

The `_WORLD_MAP` list contains 21 strings of ~180 characters each, using Braille Unicode characters. This is ~4KB of data embedded directly in the Python source. Every time the module is imported, this entire structure is loaded into memory. While not a huge issue, it makes the file hard to read and diffs noisy.

The `_render_map` function does O(n×m) work per render (iterating all grid cells to apply Rich markup), which runs every 2 seconds via `set_interval`.

**Fix:** Consider loading the map from a separate data file or caching the rendered output when connections haven't changed.

### M5. `_render_map` creates a deep copy of the base grid on every call

**File:** `tui/screens/connection_map_screen.py`, `_get_base_grid()` and `_render_map()`

```python
def _get_base_grid() -> list[list[str]]:
    ...
    return [row[:] for row in _BASE_GRID]  # deep copy every time
```

Every `_render_map` call creates a full mutable copy of the 21×180 grid, modifies it, then builds a string with Rich markup for every cell. This runs every 2 seconds. The grid copy + string building is O(3780) per call.

**Fix:** Cache the rendered string and only re-render when connection markers change.

### M6. `settings_screen.py` defines `ConfirmRestart` class inside a method — creates new class on every button press

**File:** `tui/screens/settings_screen.py`, lines 397–433

The `ConfirmRestart` modal screen class is defined inside `on_button_pressed()`. Every time the restart button is pressed, Python creates a new class object. While functionally correct, this is an anti-pattern that can cause issues with Textual's CSS resolution (the class name `ConfirmRestart` is resolved at runtime, and the CSS is defined as a class attribute on a new class each time).

**Fix:** Move `ConfirmRestart` to module level.

### M7. `_find_project_root()` walks the filesystem on every daemon restart

**File:** `tui/screens/settings_screen.py`, lines 476–482

```python
@staticmethod
def _find_project_root() -> str:
    d = os.path.dirname(os.path.abspath(__file__))
    while d != "/":
        if os.path.isfile(os.path.join(d, "pyproject.toml")):
            return d
        d = os.path.dirname(d)
    return os.getcwd()
```

This walks up the directory tree calling `os.path.isfile` on every level. It runs inside `_restart_daemon()` which is already in a background thread, so it doesn't block the TUI, but it's called every time the restart button is pressed.

**Fix:** Cache the result or compute it once at module load.

### M8. Screens don't clean up `_refresh_handle` consistently

**Files:**
- `tui/screens/main_screen.py` — `on_unmount()` stops the handle ✓
- `tui/screens/process_tree_screen.py` — `on_unmount()` stops the handle ✓
- `tui/screens/connection_map_screen.py` — `on_unmount()` stops the handle ✓

All three screens stop their interval handles on unmount, which is correct. However, `MainScreen` uses `self._refresh_handle = self.set_interval(2.0, self.refresh_data)` and then calls `self._refresh_handle.stop()` in `on_unmount()`. If `set_interval` fails or the handle is `None`, `stop()` would raise. The `on_unmount()` checks for `None` but only in `MainScreen` — the other screens check with `hasattr`.

**Severity:** Low risk since these are guard-railed, but the inconsistency is a maintenance concern.

### M9. `Snapshot` model is missing `@dataclass` decorator

**File:** `backend/models.py`, line 104

```python
class Snapshot:
    """Complete network state snapshot written to JSON."""
    timestamp: float = field(default_factory=time.time)
```

`Snapshot` uses `field()` and type annotations as if it were a dataclass, but it's missing the `@dataclass` decorator. This means `Snapshot.timestamp`, `Snapshot.listening`, etc. are **class-level attributes**, not instance-level. All instances share the same `list` and `dict` defaults (e.g., `listening`, `summary`), which is the classic Python mutable-default-argument bug.

However, `from_dict()` and `from_json()` always create new instances with explicit values, so the shared defaults are typically overwritten. The risk is if someone creates `Snapshot()` with no arguments and then mutates `listening` — it would affect all other default-constructed instances.

**Fix:** Add `@dataclass` decorator to `Snapshot`.

---

## LOW

### L1. `ConnectionLog._seen_keys_deque` is initialized but never used

**File:** `tui/widgets/connection_log.py`, line 72

```python
self._seen_keys_deque: deque[str] = deque(maxlen=_MAX_SEEN)
```

This field is never referenced anywhere in the code. It appears to be a leftover from an incomplete LRU implementation (see M1).

### L2. `State colour maps duplicated between `connection_log.py` and `themes.py`

**Files:**
- `tui/widgets/connection_log.py`, `_STATE_COLOURS` dict (line 27)
- `tui/themes.py`, `STATE_COLOURS` dict (line 72)

Both define state-to-colour mappings with slightly different structures. `connection_log.py` uses `(style, label)` tuples while `themes.py` uses just style strings. This creates maintenance burden — adding a new state requires updating both.

**Fix:** Have `connection_log.py` import from `themes.py` and add the label mapping there.

### L3. `kportwatch_tui.py` suppresses a RuntimeWarning globally

**File:** `tui/kportwatch_tui.py`, lines 15–19

```python
warnings.filterwarnings(
    "ignore",
    message=r"coroutine '.*set_title.*' was never awaited",
    category=RuntimeWarning,
)
```

This suppresses a potentially important warning globally. The root cause (unawaited `set_title` coroutine) should be investigated and fixed rather than silenced.

### L4. Tab key behavior conflicts between search bar and Textual's default focus cycling

**File:** `tui/screens/main_screen.py`, lines 151–156

```python
def on_key(self, event) -> None:
    if not self._search_visible:
        return
    ...
    elif event.key == "tab":
        self._hide_search(preserve_filter=True)
```

When the search bar is visible, Tab closes it instead of cycling focus. This overrides Textual's built-in Tab focus cycling, which might surprise users expecting standard Tab behavior. The help screen says "Tab: Switch focus between port table and connection log" which doesn't match this behavior when search is open.

### L5. Help screen references `h` key but MainScreen doesn't bind it

**File:** `tui/screens/help_screen.py`, HELP_MD

```markdown
| `?` or `h` | Show this help screen |
```

But `MainScreen.BINDINGS` only binds `question_mark` to help, not `h`. Pressing `h` on the main screen does nothing. Either add the binding or update the help text.

**File:** `tui/screens/main_screen.py`, BINDINGS list — missing `Binding("h", "help", "Help", show=False)`.

### L6. Empty `__init__.py` files could re-export public API

**Files:** `tui/__init__.py`, `tui/data/__init__.py`, `tui/utils/__init__.py`, `tui/widgets/__init__.py`, `tui/screens/__init__.py`

All contain only docstrings. This means imports like `from tui.widgets import PortTable` don't work — you need `from tui.widgets.port_table import PortTable`. Adding re-exports to `__init__.py` would improve the public API.

### L7. `_human_bytes(0)` returns `"0 B"` but `_mini_sparkline` with all zeros renders `▁▁▁`

**File:** `tui/widgets/traffic_bar.py`

When all traffic rates are zero, the sparkline shows `▁▁▁` (flat line at minimum) rather than being hidden. This is technically correct but could be confusing — it looks like there's data when there isn't. The sparkline is already gated on `len(data) < 2` returning empty, but 2+ zero values still render.

---

## INFO

### I1. Architecture is well-structured

The separation into `screens/` (page-level), `widgets/` (reusable components), `data/` (backend bridge), and `utils/` (helpers) is clean and follows Textual best practices. Screens compose widgets, widgets don't know about screens, and data flows through `DataProvider`.

### I2. Diff-based updates prevent flickering

`PortTable._apply_diff_update()` carefully preserves scroll position, cursor selection, and only updates changed rows. This is a significant UX improvement over clear-and-rebuild and follows Textual best practices.

### I3. Auto-scroll detection in ConnectionLog is thoughtful

The `on_scroll` → `_user_scrolled_up` → `_check_should_auto_scroll` chain correctly pauses auto-scroll when the user scrolls up to read history, and resumes when they scroll back to the bottom.

### I4. Two-tier hashing in ProcessTreeScreen prevents unnecessary rebuilds

The `structure_hash` vs `display_hash` approach is well-designed — it only rebuilds the full tree when the process hierarchy changes, and does lightweight label updates otherwise.

### I5. Test coverage is reasonable for widget logic

`test_tui_widgets.py` covers filtering, sorting, colour mapping, memory bounds, severity filtering, and port scan detection with 60+ test methods. The tests are pure-unit (no Textual app required) for the logic portions.

---

## Detailed Findings by Category

### 1. Textual Framework Best Practices

| Practice | Status | Notes |
|----------|--------|-------|
| Widget lifecycle | ✅ Good | `on_mount`/`on_unmount` properly manage timers |
| Message handling | ✅ Good | Uses `@on` pattern via `on_data_table_header_selected`, `on_switch_changed`, etc. |
| Reactive state | ⚠️ Mixed | No `reactive()` or `var()` used — all state is plain attributes. This is fine for the current use case but means Textual won't auto-update on changes. |
| Worker usage | ✅ Good | `@work(exclusive=True)` on refresh prevents overlapping refreshes; `asyncio.to_thread` for blocking I/O |
| CSS/styling | ✅ Good | TCSS file uses Textual CSS variables; inline CSS only in screen-specific styles |
| Timer management | ✅ Good | All screens stop intervals in `on_unmount()` |

### 2. UX Issues

| Issue | Severity | Location |
|-------|----------|----------|
| Quick-filter labels don't match semantics | HIGH (H4) | `connection_log.py` |
| `h` key documented but not bound | LOW (L5) | `help_screen.py` / `main_screen.py` |
| Tab behavior inconsistency | LOW (L4) | `main_screen.py` |
| No initial loading state beyond "Waiting for data" | HIGH (H3) | `main_screen.py` |
| Port range filter advertised in help but not implemented in search | LOW | `help_screen.py` mentions `port:80-443` syntax but `set_filter()` doesn't parse it |

### 3. Data Flow & State Management

The data flow is: **Daemon → JSON file → DataProvider.fetch() → Screen.refresh_data() → Widget.update_data()**

| Concern | Status | Notes |
|---------|--------|-------|
| Backend down handling | ✅ Good | `_consecutive_failures` threshold + status bar message |
| Stale data | ✅ Good | `StatusBar._cached_daemon_check()` with 8s TTL on heartbeat |
| Thread safety | ⚠️ Mixed | `DataProvider.fetch()` reads a file that the daemon writes concurrently. No file locking. Could read partial JSON during a write. The `json.JSONDecodeError` catch handles this, but it means occasional silent data loss. |
| State sync | ✅ Good | Each screen independently fetches and pushes to widgets |

### 4. Performance

| Concern | Severity | Location |
|---------|----------|----------|
| Synchronous `fetch()` in `action_export` | HIGH (H1) | `main_screen.py:271` |
| `ioctl` per interface per refresh | MEDIUM (M3) | `traffic_bar.py` |
| Grid copy per map render | MEDIUM (M5) | `connection_map_screen.py` |
| `_apply_diff_update` O(n²) fallback | LOW | `port_table.py` — `_find_row_index` was O(n) before the index cache was added, now O(1). The fallback `remove + re-add` on update failure is fine. |
| 2-second refresh interval | INFO | Appropriate for network monitoring; not configurable from TUI |

### 5. Code Organization

| Concern | Status | Notes |
|---------|--------|-------|
| Screen/Widget boundary | ✅ Good | Screens orchestrate, widgets display |
| Utility organization | ✅ Good | `clipboard.py` and `provider.py` are focused single-purpose modules |
| Theme system | ✅ Good | Clean separation between Textual themes (TCSS vars) and Rich markup colours |
| Duplicated code | LOW (L2) | State colour maps duplicated |
| Inline class definition | MEDIUM (M6) | `ConfirmRestart` inside method |
| Dead code | LOW (L1) | `_seen_keys_deque` unused |

### 6. Error Handling in UI

| Scenario | Status | Notes |
|----------|--------|-------|
| Backend down | ✅ Good | 3-failure threshold → status bar message |
| Network errors (GeoIP) | ✅ Good | `try/except` in `DetailScreen.fetch_geo` |
| Permission denied (kill) | ✅ Good | Both kill screens handle `PermissionError` |
| Clipboard unavailable | ✅ Good | `safe_copy_to_clipboard` catches all exceptions |
| Invalid JSON from daemon | ✅ Good | `DataProvider.fetch()` catches `json.JSONDecodeError` |
| Crash recovery | ⚠️ Partial | Widget update failures are caught and logged, but there's no mechanism to detect/recover from a completely wedged state (e.g., if `set_interval` stops firing) |

---

## Recommendations (Priority Order)

1. **Fix C1 immediately** — Remove duplicate `@staticmethod` on `_build_alert_map`
2. **Fix H1** — Make `action_export` fully async
3. **Fix H4** — Align quick-filter categories with severity categories
4. **Fix H2** — Use async kill in `ProcessKillConfirm`
5. **Fix M9** — Add `@dataclass` to `Snapshot`
6. **Fix M1** — Implement proper LRU eviction or remove the unused deque
7. **Fix M6** — Move `ConfirmRestart` to module level
8. **Address M3** — Cache interface IPs
9. **Address M5** — Cache rendered map
10. **Add L5** — Bind `h` key to help action
