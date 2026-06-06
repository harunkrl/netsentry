# KPortWatch Widget — Architecture Improvements Session

## Project Context

KPortWatch is a KDE Plasma 6 network security monitor (v2.1.0) on Arch Linux / Wayland. It has three components:
- **Backend daemon** (`backend/`) — parses `/proc/net/*`, maps inodes→PIDs, GeoIP/rDNS, alert engine, traffic stats, process trees. Writes atomic JSON snapshots to `${XDG_RUNTIME_DIR}/kportwatch-data.json` and streams data via Unix socket at `${XDG_RUNTIME_DIR}/kportwatch.sock`.
- **TUI** (`tui/`) — Textual terminal analyzer with port table, connection log, traffic bar, connection map, process tree, settings.
- **Plasma widget** (`widget/`) — QML plasmoid for the panel. Shows listening ports, established connections, alerts, traffic stats in a popup with a shield icon + badge in the panel.

## Current Architecture: Widget ↔ Daemon

The widget reads data by shelling out to `cat` every 2 seconds via Plasma's `executable` DataSource engine:

```js
// widget/contents/ui/main.qml
property string _cmd: "sh -c 'cat ${XDG_RUNTIME_DIR:-/tmp}/kportwatch-data.json 2>/dev/null'"
```

It then parses the **entire** JSON snapshot, which contains:
- `listening` — listening sockets (used by widget ✅)
- `established` — established connections (used by widget ✅)
- `alerts` — security alerts (used by widget ✅)
- `summary` — counts (used by widget ✅)
- `traffic` — per-interface traffic stats (used by widget ✅)
- `processes` — full process tree data (NOT used by widget ❌ — can be 100KB+)
- `geo_stats` — country aggregates (NOT used by widget ❌)

The widget also kills processes directly via `kill -15` / `kill -9` shell commands, bypassing the daemon entirely:

```js
// widget/contents/ui/main.qml
function killProcess(pid) {
    killExecSource._pendingPid = pid
    killExecSource.connectedSources = ["sh -c 'kill -15 " + pid + " 2>/dev/null; sleep 1; kill -0 " + pid + " 2>/dev/null'"]
}
```

The project already has `kportwatchctl` (`backend/kportwatchctl.py`) — a CLI that communicates with the daemon via the Unix socket. The daemon has a command handler that could be extended.

## Task 1: Lighter Widget Data Payload (#6)

**Problem:** Every 2 seconds, the widget spawns a shell, reads the full snapshot JSON (which includes `processes` dict that can be very large), and parses it — only to use ~40% of the data.

**Goal:** Serve a widget-specific payload that omits unused fields (`processes`, `geo_stats`).

**Approaches to consider:**

### Option A: Separate widget data file
- Daemon writes a second file: `kportwatch-widget-data.json` containing only `{listening, established, alerts, summary, traffic}`
- Widget reads this lighter file instead
- Pros: Simple, no protocol changes. Cons: Double disk writes per cycle

### Option B: Socket command for widget payload
- Widget connects to the Unix socket and sends a command like `GET widget`
- Daemon responds with the filtered payload
- Pros: No file I/O, real-time. Cons: QML doesn't have native Unix socket support — would need a helper script or `socat` bridge

### Option C: Filter with `jq` or `python` in the `cat` command
- Change the widget's `_cmd` to pipe through `jq '{listening, established, alerts, summary, traffic}'`
- Pros: Zero daemon changes. Cons: Depends on `jq` being installed, still spawns a shell

**Key files:**
- `backend/writers/json_file.py` — `write_snapshot()` (atomic file writer)
- `backend/kportwatch_daemon.py` — main daemon loop, calls `write_snapshot()`
- `backend/models.py` — `Snapshot.to_dict()`, `Snapshot.to_json()` (serialization)
- `widget/contents/ui/main.qml` — `_cmd` property and `parseSnapshot()` function

## Task 2: Route Kill Through Daemon (#9)

**Problem:** Widget kills processes directly with `kill` signals. This bypasses:
- Permission checks the daemon could enforce
- Audit logging (daemon doesn't know about kills from the widget)
- SIGTERM→wait→SIGKILL logic (currently duplicated in QML and Python)

**Goal:** Widget sends kill requests through the daemon's Unix socket.

**Current kill flow (widget):**
```
Widget button → kill -15 <pid> shell command → (sleep 1) → kill -9 <pid> fallback
```

**Desired kill flow:**
```
Widget button → kportwatchctl kill <pid> → daemon Unix socket → daemon kills process → response
```

**Key files:**
- `backend/kportwatchctl.py` — existing CLI client, communicates via Unix socket
- `backend/kportwatch_daemon.py` — socket command handler
- `backend/kportwatch_client.py` — another client implementation
- `backend/writers/unix_socket.py` — Unix socket writer
- `widget/contents/ui/main.qml` — `killProcess()` function
- `widget/contents/ui/FullRepresentation.qml` — kill dialog

**Approach:** Add a `kill` command to `kportwatchctl` (or create a thin wrapper), then have the widget call `kportwatchctl kill <pid>` instead of raw `kill`. The daemon handles SIGTERM→wait→SIGKILL with proper error handling (already implemented in `tui/data/provider.py:DataProvider.kill_process()`).

## Constraints
- Python 3.10+, Qt 6, KDE Plasma 6.6, Wayland
- Widget is QML — cannot use Python Unix sockets directly, must go through `executable` DataSource (shell commands)
- Daemon runs as systemd user service
- All changes must pass the existing 413 tests
- Follow existing code patterns in the project
