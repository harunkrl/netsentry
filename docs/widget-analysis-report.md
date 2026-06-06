# KPortWatch Widget Analysis Report

## Scope

All files under `widget/` — the KDE Plasma 6 plasmoid that provides real-time network monitoring in the panel.

---

## 🔴 Bugs / Correctness Issues

### 1. Hardcoded TUI launch path in `main.qml`
**File:** `main.qml` line ~`launchTUI()`  
**Severity:** High  

```js
var defaultCmd = "konsole -e bash -c 'source ~/Projects/KPortWatch/.venv/bin/activate && exec kportwatch-tui'"
```

This is an absolute path to your personal dev directory. After a proper install (`pip install -e .` + symlinks in `~/.local/bin`), the user already has `kportwatch-tui` on PATH. The default should just be `kportwatch-tui`. The current path breaks on any machine where the project isn't at `~/Projects/KPortWatch`.

### 2. `alertThreshold` config not bound to ComboBox correctly
**File:** `ConfigGeneral.qml`  
**Severity:** Medium  

`cfg_alertThreshold` is declared as a plain `property string` — not aliased from a config widget like the others. The `ComboBox.onActivated` sets `cfg_alertThreshold` correctly, but `Component.onCompleted` doesn't read from `plasmoid.configuration.alertThreshold` — it compares against the property itself. If the saved config differs from the default `"WARNING"`, the ComboBox may show the wrong initial selection on dialog open.

### 3. Kill dialog sends only SIGTERM via raw shell command
**File:** `FullRepresentation.qml` + `main.qml`  
**Severity:** Medium  

```js
onAccepted: { killExecSource.connectedSources = ["kill -15 " + targetPid] }
```

- No confirmation that the process actually died
- No SIGKILL fallback if SIGTERM fails (unlike `DataProvider.kill_process` in the TUI which tries SIGTERM → wait → SIGKILL)
- PID injection is safe here since `targetPid` comes from model data (integer), but `kill -15` as a raw shell command via `connectedSources` means the DataSource engine spawns a shell process for every kill attempt

### 4. `fontScale` applied to `int` property causes fractional truncation
**File:** `FullRepresentation.qml`  
**Severity:** Low  

```js
readonly property int sf: Kirigami.Theme.smallFont.pixelSize * (root.fontScale / 100.0)
readonly property int df: Kirigami.Theme.defaultFont.pixelSize * (root.fontScale / 100.0)
```

Both are declared `int`, but the multiplication produces a float. Fractional values are silently truncated. Should be `property real` or use `Math.round()`.

### 5. `connectedSources` lifecycle race in `dataSource`
**File:** `main.qml`  
**Severity:** Low  

```js
onNewData: (sourceName, data) => {
    connectedSources = []   // ← disconnects immediately
    ...
}
```

`execQuery()` checks `if (connectedSources.length === 0)` before reconnecting. If `onNewData` clears `connectedSources` while the timer is mid-fire, there's a brief window where no source is connected and the next `execQuery()` must re-add it. This works but is fragile — a missed trigger means stale data until the next timer tick.

---

## 🟡 Architecture / Design Issues

### 6. Data fetching via `cat` + JSON parse — no streaming or socket
**Severity:** Medium (architectural)  

The widget reads the data file by shelling out to `cat` every `pollInterval` seconds:

```js
property string _cmd: "sh -c 'cat ${XDG_RUNTIME_DIR:-/tmp}/kportwatch-data.json 2>/dev/null'"
```

The backend already has a Unix socket (`kportwatch.sock`) and a `write_snapshot` that does atomic file writes. The widget ignores the socket entirely and instead:
- Spawns a **new shell process** every 2 seconds
- Reads the **entire JSON** file into memory
- Parses the **full snapshot** every cycle (including `established`, `traffic`, `processes`, `geo_stats` — none of which the widget uses)

**Impact:** Unnecessary CPU/memory overhead on the panel process. For a widget that only displays `listening` ports and `alerts`, parsing the full snapshot is wasteful.

### 7. Model diffing algorithm is complex and fragile
**File:** `main.qml` (the `onNewData` handler)  
**Severity:** Medium  

The 30-line block that diffs `connectionsModel` against `newListening` does:
1. Build `currentKeys` from existing model
2. Build `newKeys` from incoming data
3. Update existing / append new entries
4. Remove stale entries
5. Reorder entries to match the sorted incoming order

This is essentially a list reconciliation algorithm written in inline JS inside a data handler. Any bug here causes duplicate rows, missing entries, or ghost items. It should be extracted into a dedicated function with clear documentation.

### 8. No error boundary around JSON parse
**File:** `main.qml`  
**Severity:** Low  

```js
try {
    var parsed = JSON.parse(data.stdout)
    ...
} catch(e) { console.log("KPortWatch parse error: " + e) }
```

The catch logs but doesn't reset state. If the daemon writes a truncated file mid-write (despite atomic writes, `cat` could race), `snapshotData` retains the last good parse but `listeningCount`, `alertCount`, etc. might be stale. No visual feedback that data is stale after a parse error.

### 9. No connection to `kportwatchctl` for actions
**Severity:** Low  

The widget has a `killExecSource` that runs raw `kill` commands, but the project already ships `kportwatchctl` — a CLI that can send commands to the daemon via the Unix socket. Using `kportwatchctl kill <pid>` would go through the daemon (which can do permission checks, audit logging, etc.) instead of the widget directly signaling processes.

---

## 🟢 UX / Polish Issues

### 10. CompactRepresentation: no minimum height
**File:** `CompactRepresentation.qml`  
**Severity:** Low  

Only `Layout.minimumWidth` is set. On a vertical panel, the widget may collapse to near-zero height. Should also set `Layout.minimumHeight`.

### 11. CompactRepresentation: MouseArea swallows all events
**File:** `CompactRepresentation.qml`  
**Severity:** Low  

The `MouseArea` covers the entire compact representation with `onClicked` to toggle expanded. This prevents:
- Middle-click (could be used for quick action)
- Scroll wheel (could cycle through ports or threat levels)

Consider using `Plasmoid.onContextualActionsAboutToShow` or other Plasma patterns.

### 12. FullRepresentation: sort indicator only on header, no visual feedback on sort change
**File:** `FullRepresentation.qml`  
**Severity:** Cosmetic  

Sort arrows (▲/▼) appear in the column header, but:
- No animation when sort changes
- The model diffing doesn't guarantee visual order matches after re-sort
- Sort state is lost when the popup is closed (it's only in root properties, not persisted)

### 13. FullRepresentation: Kill button always visible on every row
**File:** `FullRepresentation.qml`  
**Severity:** UX  

The kill button (`application-exit` icon) shows on every connection row, even for system processes the user can't kill. This is visually noisy and could lead to confusing "permission denied" errors. Consider:
- Only show kill button on hover
- Disable for PID 0, 1, or system processes (uid-based)

### 14. No loading/empty state animation
**File:** `FullRepresentation.qml`  
**Severity:** Cosmetic  

When `portListView.count === 0`, a static label shows. A subtle loading indicator (spinning icon or pulsing dot) while `fullRoot.hasData` is false would feel more responsive.

---

## 🔵 Missing Features / Gaps

### 15. Widget ignores `established` connections entirely
The snapshot contains `established` connections with GeoIP data, remote hostnames, etc. The widget only shows `listening` ports. An "Established" tab or toggle in the popup would leverage data already being collected.

### 16. Widget ignores `traffic` data
The daemon collects per-interface traffic stats (`rx_rate`, `tx_rate`). The widget could show a small sparkline or throughput indicator in the compact representation or popup footer.

### 17. Widget ignores `geo_stats` data
Country counts and top countries from GeoIP are in the snapshot but not displayed.

### 18. No desktop notification integration from widget
The daemon generates alerts with levels (INFO/WARNING/CRITICAL). The widget reads them for display in the popup, but doesn't trigger Plasma desktop notifications for new alerts. The daemon already has notification support, but widget-side notification (e.g., via `org.freedesktop.Notifications`) would be more visible.

### 19. Config has no "safe ports" whitelist
**File:** `ConfigGeneral.qml`  

The daemon has `KNOWN_SAFE_PORTS` in constants, and the alert engine uses it. But the widget config has no way for users to add/remove safe ports from the widget settings dialog. Users must edit the config file directly.

### 20. No "About" page or version display
The widget doesn't show its version (`metadata.json` has `"Version": "1.0.0"` which is also out of date — should be `2.1.0`). No standard KDE "About" page.

---

## Summary Table

| # | Issue | Severity | Category |
|---|-------|----------|----------|
| 1 | Hardcoded TUI path | 🔴 High | Bug |
| 2 | ComboBox config binding | 🟡 Medium | Bug |
| 3 | Kill: no SIGKILL fallback | 🟡 Medium | Bug |
| 4 | fontScale int truncation | 🟢 Low | Bug |
| 5 | connectedSources race | 🟢 Low | Bug |
| 6 | `cat` + full JSON parse overhead | 🟡 Medium | Architecture |
| 7 | Inline model diffing complexity | 🟡 Medium | Architecture |
| 8 | Parse error: no stale data feedback | 🟢 Low | Architecture |
| 9 | Bypasses `kportwatchctl` for kill | 🟢 Low | Architecture |
| 10 | No minimum height on compact | 🟢 Low | UX |
| 11 | MouseArea swallows events | 🟢 Low | UX |
| 12 | Sort state not persisted | 🟢 Low | UX |
| 13 | Kill button always visible | 🟢 Low | UX |
| 14 | No loading animation | 🟢 Low | UX |
| 15 | Ignores established connections | 🔵 Gap | Feature |
| 16 | Ignores traffic data | 🔵 Gap | Feature |
| 17 | Ignores geo_stats | 🔵 Gap | Feature |
| 18 | No widget-side notifications | 🔵 Gap | Feature |
| 19 | No safe ports config | 🔵 Gap | Feature |
| 20 | Version mismatch, no About page | 🔵 Gap | Feature |

**Priority recommendation:** Fix issues **#1** (hardcoded path), **#2** (config binding), and **#3** (kill fallback) first — they directly affect usability for anyone installing from the repo. Then tackle **#6** (data fetching overhead) and **#7** (model diffing) as architectural improvements.
