# NetSentry Plasma 6 Widget — Code Review

**Reviewer:** automated review subagent  
**Date:** 2026-05-30  
**Plasma version on system:** 6.6.5 / Qt 6.11.1 / Kirigami 6.26.0  
**Reference plasmoid:** org.kde.netspeedWidget (working Plasma 6 widget)

---

## Summary

The widget is **structurally sound** and follows the established Plasma 6 plasmoid patterns closely (PlasmoidItem, versionless QML imports, KPackageStructure array format, plasma5support DataSource). There are several issues ranging from a **blocker** (QML runtime error on `Kirigami.AbstractListItem`) to **minor UX polish** items. Overall, the code is well-organized and readable.

---

## File-by-File Review

---

### 1. `widget/metadata.json` — Rating: 8/10

**Correct:**
- `KPackageStructure` is a JSON array `["Plasma/Applet"]` — matches Plasma 6 format (confirmed identical to the reference netspeedWidget).
- `X-Plasma-API-Minimum-Version: "6.0"` — correct for Plasma 6.
- No stale `X-Plasma-DBusActivationService` or `ServiceTypes` keys (which were Plasma 5 patterns).
- `Id` uses reverse-DNS format `com.netsentry.plasmoid`.

**Note:**
- `EnabledByDefault` is not required but harmless. The reference plasmoid omits it. Fine to keep.
- The `X-Plasma-MainScript` key is technically deprecated in Plasma 6 (it's inferred from the package structure) but is still widely used and accepted. No action needed.

---

### 2. `widget/contents/config/main.xml` — Rating: 6/10

**Correct:**
- Standard KConfigXT XML schema. Matches the reference plasmoid's structure exactly.
- `<kcfgfile name=""/>` correctly present (empty = plasmoid-specific config).

**Blocker — `pollInterval` typed as `Double` but used with `SpinBox` (int-only):**
- `SpinBox.value` in `QtQuick.Controls` is always `int`. The `cfg_pollInterval` alias binds to `pollIntervalSpin.value`, which truncates to integer on save. The KConfigXT type `Double` will still deserialize `2.0`, but the user can only ever set integer values through the UI, and if they manually set `1.5` in the config file, the SpinBox will show `1`.
- **Fix:** Change the KConfigXT type to `Int` (since stepSize is 1 anyway), OR use a `SpinBox` with `property real realValue` and bind `cfg_pollInterval` to that instead.

**Recommendation — change to Int:**
```xml
<entry name="pollInterval" type="Int">
    <default>2</default>
</entry>
```
And in `main.qml`, change `property double pollInterval` to `property int pollInterval`.

---

### 3. `widget/contents/config/config.qml` — Rating: 8/10

**Correct:**
- Uses `import org.kde.plasma.configuration 2.0` — this is the legacy versioned import. Some Plasma 6 built-in widgets use versionless (`import org.kde.plasma.configuration`), but the reference netspeedWidget also uses `2.0` and works fine. The Plasma engine resolves both.

**Note:**
- Consider removing the version number to be forward-compatible: `import org.kde.plasma.configuration`. Not a blocker — the versioned import works today.

---

### 4. `widget/contents/ui/main.qml` — Rating: 7/10

**Correct:**
- Versionless imports: `import QtQuick`, `import org.kde.plasma.plasmoid` — correct for Plasma 6 / Qt6.
- `PlasmoidItem` root type — correct (replaces the old `Item` + `Plasmoid.compactRepresentation` pattern).
- `Plasma5Support.DataSource` with `engine: 'executable'` — matches the reference netspeedWidget exactly.
- `onNewData` uses arrow function `(sourceName, data) =>` — correct Qt6/QML syntax.
- `Plasmoid.title`, `Plasmoid.toolTipMainText`, `Plasmoid.toolTipSubText` — confirmed valid attached properties in Plasma 6 (used by system widgets).

**Blocker — Security: command injection in `connectedSources`:**
```qml
connectedSources: ["cat /tmp/netsentry-data.json"]
```
The `executable` engine runs the source string as a shell command. Since this is a hardcoded literal with no user input, there's **no injection risk here**. The path `/tmp/netsentry-data.json` is a fixed daemon output path. ✅ Safe.

**Security — `launchTUI()` uses `nohup konsole -e bash ... &`:**
```qml
"nohup konsole -e bash ~/NetSentry/widget/contents/scripts/launch-tui.sh &"
```
The command is constructed from the hardcoded script path, not from `tuiCommand` config. This is safe from injection. However:
- **Wayland concern:** `nohup ... &` backgrounding with `konsole -e` works on Wayland (Konsole 26.04 tested present). The `nohup` is unnecessary here since the `executable` engine already runs in a subprocess, and Konsole detaches itself. The `nohup/&` pattern could cause zombie processes or double-fork issues.
- **Fix:** Remove `nohup` and `&`:
```qml
function launchTUI() {
    execSource.connectedSources = [
        "konsole -e bash ~/NetSentry/widget/contents/scripts/launch-tui.sh"
    ]
}
```

**Note — `tuiCommand` config property is declared but never used:**
```qml
property string tuiCommand: plasmoid.configuration.tuiCommand
```
The `launchTUI()` function hardcodes the command instead of using `tuiCommand`. Either use it or remove the property:
```qml
function launchTUI() {
    execSource.connectedSources = ["konsole -e bash " + tuiCommand]
}
```
Wait — but that would allow arbitrary command execution from config. Better to keep it hardcoded to the script and remove `tuiCommand`, or use `tuiCommand` only as the argument to `launch-tui.sh` which wraps it safely.

**Note — `execSource` cleanup:**
```qml
onNewData: (sourceName, data) => {
    connectedSources = []
}
```
Setting `connectedSources = []` inside `onNewData` is the correct pattern to run-once. ✅

**Note — Missing error handling for daemon not running:**
When the daemon is not running, `cat /tmp/netsentry-data.json` will return exit code 1. The code checks `data['exit code'] === 0` and silently skips — good. But the user sees no feedback in main.qml. The `FullRepresentation` handles this via the empty-state label ("Waiting for data…") — that's fine. ✅

---

### 5. `widget/contents/ui/CompactRepresentation.qml` — Rating: 8/10

**Correct:**
- Versionless imports for Plasma 6.
- `Kirigami.Icon` — proper Plasma 6 icon component.
- `anchors.fill: parent` — correct for compact representation.
- Badge text with color-coding based on `threatLevel`.
- `MouseArea` with `root.expanded = !root.expanded` — correct toggle pattern.

**Note — Using raw `Text` instead of `Label`:**
```qml
Text {
    id: badge
    ...
    color: root.threatLevel === "critical" ? "#e03030" : ...
```
`Text` works fine, but `Label` from `QtQuick.Controls` would automatically pick up Kirigami theme fonts. For a small badge overlay this is acceptable, but consider `Label` for consistency.

**Note — Badge may clip in small panels:**
```qml
font.pixelSize: Math.min(parent.width, parent.height) * 0.35
```
In a very narrow panel (e.g., 22px icons), this gives ~7.7px text which is readable but tight. The badge is anchored to `top`/`right` with 2px margin — fine.

**Note — Hardcoded hex colors:**
The colors `#e03030`, `#e0c030` are hardcoded. In a light theme, these work as accent colors. For a dark theme they also work (red/yellow on dark). Acceptable for a security indicator where semantic color matters more than theme adherence.

---

### 6. `widget/contents/ui/FullRepresentation.qml` — Rating: 5/10

**Correct:**
- Overall layout with `ColumnLayout`, header, `ListView`, footer button — well-structured.
- Empty state with helpful text about starting the daemon. ✅
- `Kirigami.Separator` usage. ✅
- Alert-matching logic in delegate. ✅

**Blocker — `Kirigami.AbstractListItem` does not exist in Kirigami 6:**
```qml
delegate: Kirigami.AbstractListItem {
```
In Kirigami 6.x, `AbstractListItem` has been removed or renamed. The available delegate types are:
- `Kirigami.ListItem` (new in Kirigami 2.20+)
- `Kirigami.BasicListItem`
- `Kirigami.CheckableListItem`
- Plain `ItemDelegate` from `QtQuick.Controls`

Using `Kirigami.AbstractListItem` will cause a **QML runtime error** and the delegate will fail to instantiate, resulting in an empty list or a crash.

**Fix:** Replace with `ItemDelegate` or a plain `Item`:
```qml
delegate: ItemDelegate {
    id: listItem
    width: portListView.width
    height: Kirigami.Units.gridUnit * 1.5
    background: Item { }  // transparent background

    readonly property var entry: modelData
    // ... rest of delegate
}
```
Or simply use a plain `Item` since you don't need click handling:
```qml
delegate: Item {
    id: listItem
    width: portListView.width
    height: Kirigami.Units.gridUnit * 1.5
    readonly property var entry: modelData
    // ...
}
```

**Note — Missing `Label` import:**
`Label` from `QtQuick.Controls` is used but `import QtQuick.Controls` is present. ✅ Fine.

**Note — Missing `i18n()` calls for process name fallback:**
```qml
text: entry.process_name || i18n("unknown")
```
`i18n()` in a ListView delegate is fine in Plasma plasmoids — it's provided by the Plasma QML engine. ✅

**Note — Potential NPE with `entry.local_port`:**
If a `SocketEntry` has `local_port: null` (from a malformed entry), `String(null)` returns `"null"`. The `?` guard handles this: `entry.local_port ? String(entry.local_port) : "-"`. ✅

**Note — ListView with JS array model:**
```qml
model: fullRoot.listeningPorts
```
Binding a JS array as a model to `ListView` works in QML. Each item is accessed via `modelData`. This is correct. ✅

**Note — Alert matching is O(n*m) per delegate:**
Each delegate iterates `root.alertList` to find a matching alert. With typical data (< 100 ports, < 10 alerts) this is fine. For very large port lists (> 1000), this could cause frame drops during scrolling. Low priority.

---

### 7. `widget/contents/ui/config/ConfigGeneral.qml` — Rating: 7/10

**Correct:**
- `Kirigami.FormLayout` with `Kirigami.FormData.label` — standard Plasma config pattern. Matches reference.
- `cfg_` aliases for config properties — correct KConfigXT binding convention.
- `SpinBox`, `CheckBox`, `ComboBox`, `TextField` — all standard controls.

**Blocker — `cfg_alertThreshold` bound to `currentIndex` (int) instead of string value:**
```qml
property alias cfg_alertThreshold: alertThresholdCombo.currentIndex
```
`cfg_alertThreshold` should be a `string` (matching the `String` type in `main.xml`). But it's aliased to `currentIndex` which is an `int`. When the config system reads the stored string `"WARNING"` and tries to set `cfg_alertThreshold`, it will fail or produce incorrect behavior because the alias expects an int.

**Fix:** Use a proper string property:
```qml
property string cfg_alertThreshold: "WARNING"

ComboBox {
    id: alertThresholdCombo
    Kirigami.FormData.label: i18n("Alert threshold:")
    textRole: "label"
    model: [
        { label: i18n("INFO"), value: "INFO" },
        { label: i18n("WARNING"), value: "WARNING" },
        { label: i18n("CRITICAL"), value: "CRITICAL" }
    ]

    Component.onCompleted: {
        for (var i = 0; i < model.length; i++) {
            if (model[i].value === cfg_alertThreshold) {
                currentIndex = i
                break
            }
        }
    }

    onActivated: {
        cfg_alertThreshold = model[currentIndex].value
    }
}
```
Remove the alias line and add `property string cfg_alertThreshold: "WARNING"`.

**Note — `pollIntervalSpin.realValue` declared but unused:**
```qml
property double realValue: value
```
This property is declared on the SpinBox but never referenced. Since the config type should be changed to `Int` (see main.xml review), this can be removed entirely.

**Note — `showPortCount` config declared but not used in QML:**
The `cfg_showPortCount` checkbox exists in config, and `main.xml` has the entry, but no QML file reads `plasmoid.configuration.showPortCount`. The badge in `CompactRepresentation.qml` is always visible when `listeningCount > 0`. Either wire it up or remove the config option.

---

### 8. `widget/contents/scripts/launch-tui.sh` — Rating: 7/10

**Correct:**
- Bash syntax valid (`bash -n` passes).
- Activates venv if present.
- Sets `PYTHONPATH` for project imports.
- Uses `exec` to replace the shell process.

**Note — `$USER` in hardcoded path:**
```bash
VENV_DIR="/home/$USER/NetSentry/.venv"
```
`$USER` is the current user. If the plasmoid is installed system-wide or for a different user, this path will be wrong. Better to use `$HOME`:
```bash
VENV_DIR="$HOME/NetSentry/.venv"
```
Although in practice, `$USER` and `$HOME` are almost always consistent. Low priority.

**Note — `PYTHONPATH` pollution:**
```bash
export PYTHONPATH="/home/$USER/NetSentry:$PYTHONPATH"
```
If `$PYTHONPATH` is unset, this produces a trailing colon (`/home/user/NetSentry:`), which adds `.` (CWD) to the search path. Minor but could cause unexpected imports. Fix:
```bash
export PYTHONPATH="/home/$USER/NetSentry${PYTHONPATH:+:$PYTHONPATH}"
```

**Note — Wayland compatibility:**
The script is launched via `konsole -e bash <script>`. This works on Wayland (tested: Konsole 26.04.1 on Wayland session). ✅ No X11-specific code in the script.

---

## Cross-Cutting Concerns

### Plasma 6 Compatibility: ✅ Mostly Good
| Aspect | Status | Notes |
|--------|--------|-------|
| Versionless QML imports | ✅ Correct | `import QtQuick`, `import org.kde.plasma.plasmoid` |
| `PlasmoidItem` root | ✅ Correct | Replaces old `Item` + attached pattern |
| `Plasma5Support.DataSource` | ✅ Correct | Matches reference plasmoid |
| `KPackageStructure` format | ✅ Correct | Array `["Plasma/Applet"]` |
| `config.qml` versioned import | ⚠️ Minor | `2.0` works but versionless is preferred |
| `Kirigami.AbstractListItem` | ❌ Broken | Does not exist in Kirigami 6 |

### Security: ✅ No Injection Issues
- `connectedSources` uses hardcoded command `cat /tmp/netsentry-data.json` — no user-controlled input.
- `launchTUI()` runs a hardcoded script path — safe.
- `tuiCommand` config exists but is not wired into command execution — safe by accident (not by design). Consider removing it if unused.

### Edge Cases
| Scenario | Behavior | Rating |
|----------|----------|--------|
| Daemon not running | `cat` returns exit 1, silently skipped. FullRepresentation shows "Waiting for data…" | ✅ Good |
| Empty JSON `{}` | `parsed.summary` is undefined → `root.listeningCount = 0`, `listening` defaults to `[]` | ✅ Good |
| Malformed JSON | Caught by `try/catch`, logged to console. Widget keeps previous data. | ✅ Good |
| Very large port lists (>500) | `ListView` with JS array model, O(n*m) alert matching per delegate. May lag. | ⚠️ Acceptable |
| File `/tmp/netsentry-data.json` doesn't exist | `cat` exits 1, handled silently | ✅ Good |
| Atomic write race (daemon writing while widget reads) | Daemon uses `os.replace()` for atomic rename. `cat` reads the old or new file atomically. | ✅ Good |

### UX
- Compact icon changes based on threat level — good visual feedback.
- Badge shows listening port count — useful at a glance.
- FullRepresentation has clear column headers and color-coded alert indicators.
- "Launch Advanced Network Analyzer" button is discoverable.
- **Missing:** No way to tell when the last update occurred. Consider adding a "Last updated: HH:MM:SS" label.

---

## Issue Summary

| # | Severity | File | Issue | Fix |
|---|----------|------|-------|-----|
| 1 | **Blocker** | `FullRepresentation.qml:39` | `Kirigami.AbstractListItem` does not exist in Kirigami 6 — causes runtime error | Replace with `Item` or `ItemDelegate` |
| 2 | **Blocker** | `ConfigGeneral.qml:5` | `cfg_alertThreshold` aliased to `currentIndex` (int) but config type is `String` — config won't load/save correctly | Use `property string cfg_alertThreshold` + `onActivated` handler |
| 3 | **Major** | `main.xml:7` / `main.qml:15` | `pollInterval` typed as `Double` but SpinBox only provides `int` — type mismatch | Change to `Int` in main.xml, `property int` in main.qml |
| 4 | **Major** | `main.qml:53` | `nohup konsole -e bash ... &` unnecessary and may cause zombie processes | Use `konsole -e bash ...` without nohup/& |
| 5 | **Minor** | `main.qml:17` | `tuiCommand` config property declared but never used in `launchTUI()` | Either use it or remove it |
| 6 | **Minor** | `CompactRepresentation.qml` | Uses `Text` instead of `Label` — won't follow theme font | Use `Label` from QtQuick.Controls |
| 7 | **Minor** | `ConfigGeneral.qml` | `cfg_showPortCount` config exists but is not read anywhere | Wire up in CompactRepresentation or remove |
| 8 | **Minor** | `launch-tui.sh:4` | `$USER` instead of `$HOME` — less portable | Use `$HOME` |
| 9 | **Trivial** | `launch-tui.sh:6` | `$PYTHONPATH` trailing colon if unset | Use `${PYTHONPATH:+:$PYTHONPATH}` |
| 10 | **Trivial** | `config.qml:1` | Versioned import `2.0` works but versionless is Plasma 6 style | Remove version |

---

## Recommended Code Fixes

### Fix 1: FullRepresentation.qml — Replace AbstractListItem

```diff
-            delegate: Kirigami.AbstractListItem {
+            delegate: Item {
                 id: listItem
                 width: portListView.width
                 height: Kirigami.Units.gridUnit * 1.5
```

### Fix 2: ConfigGeneral.qml — Fix alertThreshold binding

```diff
-    property alias cfg_alertThreshold: alertThresholdCombo.currentIndex
+    property string cfg_alertThreshold: "WARNING"

     ComboBox {
         id: alertThresholdCombo
@@ ...
         Component.onCompleted: {
             for (var i = 0; i < model.length; i++) {
-                if (model[i].value === plasmoid.configuration.alertThreshold) {
+                if (model[i].value === cfg_alertThreshold) {
                     currentIndex = i
                     break
                 }
             }
         }
 
-        onCurrentIndexChanged: {
-            _selectedValue = model[currentIndex].value
+        onActivated: {
+            cfg_alertThreshold = model[currentIndex].value
         }
     }
```

Also remove the unused `_selectedValue` property.

### Fix 3: main.xml — Change pollInterval to Int

```diff
-        <entry name="pollInterval" type="Double">
-            <default>2.0</default>
+        <entry name="pollInterval" type="Int">
+            <default>2</default>
```

### Fix 4: main.qml — Fix pollInterval type and nohup

```diff
-    property double pollInterval: plasmoid.configuration.pollInterval
+    property int pollInterval: plasmoid.configuration.pollInterval
```

```diff
     function launchTUI() {
         execSource.connectedSources = [
-            "nohup konsole -e bash ~/NetSentry/widget/contents/scripts/launch-tui.sh &"
+            "konsole -e bash ~/NetSentry/widget/contents/scripts/launch-tui.sh"
         ]
     }
```

### Fix 5: CompactRepresentation.qml — Use Label

```diff
-    Text {
+    Label {
         id: badge
```

Add `import QtQuick.Controls` if not already present (it's not in the current file).

---

## Final Ratings

| File | Score | Summary |
|------|-------|---------|
| `metadata.json` | **8/10** | Clean Plasma 6 metadata, matches reference |
| `config/main.xml` | **6/10** | Double/Int mismatch on pollInterval |
| `config/config.qml` | **8/10** | Works, minor versioned import |
| `ui/main.qml` | **7/10** | Solid structure, nohup unnecessary, tuiCommand unused |
| `CompactRepresentation.qml` | **8/10** | Good icon/badge, minor Text→Label |
| `FullRepresentation.qml` | **5/10** | AbstractListItem blocker, otherwise well-designed |
| `ConfigGeneral.qml` | **5/10** | alertThreshold binding broken, unused properties |
| `launch-tui.sh` | **7/10** | Works, minor $USER/$HOME and PYTHONPATH issues |

**Overall widget score: 6.5/10** — Good foundation, 2 blockers to fix before it will run correctly in Plasma 6.
