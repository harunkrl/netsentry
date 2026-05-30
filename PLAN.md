# NetSentry — Implementation Plan

## Goal
Build a hybrid local network security monitor for KDE Plasma 6.6 (Arch Linux / EndeavourOS, Wayland) consisting of a panel Plasmoid for real-time passive alerting and a Python Textual TUI for deep inspection, connected via a shared JSON data source produced by a lightweight backend daemon.

---

## Data Flow Architecture

```
┌──────────────────────────────────────────────────────────────────┐
│                        KERNEL                                    │
│  /proc/net/tcp  /proc/net/tcp6  /proc/net/udp  /proc/net/udp6  │
│  /proc/[pid]/fd/*   /proc/[pid]/cmdline   /proc/[pid]/status   │
└────────┬────────────────────────────────────────────────────────┘
         │  read (no root needed for own processes)
         ▼
┌──────────────────────────────────────────────────────────────────┐
│            BACKEND DAEMON (netsentry-daemon.py)                  │
│  • /proc/net/tcp parsing → structured socket entries            │
│  • Inode → PID mapping via /proc/[pid]/fd/ scanning             │
│  • Alert engine (baseline + malicious port detection)            │
│  • Adaptive polling (2s default, 1s alert, 10s idle)            │
│  • Writes JSON snapshot → /tmp/netsentry-data.json               │
│  • Optional: Unix socket at $XDG_RUNTIME_DIR/netsentry.sock      │
└────────┬──────────────────────────┬─────────────────────────────┘
         │ file poll                │ unix socket
         ▼                          ▼
┌──────────────────────┐  ┌────────────────────────────────────────┐
│   PLASMOID (QML)     │  │   TUI (Python Textual)                 │
│  • CompactRep:       │  │  • Split pane:                         │
│    shield icon +     │  │    Left = DataTable (ports)             │
│    port count badge  │  │    Right = RichLog (connections)        │
│  • FullRep:          │  │  • Key bindings: q/k/r/f//             │
│    port summary      │  │  • Kill confirmation dialog             │
│    table + launch    │  │  • Auto-refresh via set_interval(2s)   │
│    TUI button        │  │                                        │
│  • DataSource exec   │  │                                        │
│    polls JSON file   │  │                                        │
└──────────────────────┘  └────────────────────────────────────────┘
```

**Privilege escalation path (for system-wide PID visibility):**
```
User runs: sudo setcap cap_net_admin+ep /usr/local/bin/netsentry-helper
—or— sudoers NOPASSWD rule for ss -tulnp (simpler alternative)
—or— polkit .policy file (desktop-native approach)
```

---

## Project File Structure (Final)

```
~/NetSentry/
├── widget/                                    ← Plasma 6 Plasmoid
│   ├── metadata.json                          ← Plugin metadata (Plasma 6 format)
│   └── contents/
│       ├── ui/
│       │   ├── main.qml                       ← Root PlasmoidItem + DataSource
│       │   ├── CompactRepresentation.qml      ← Panel tray: icon + badge
│       │   ├── FullRepresentation.qml         ← Popup: port table + launch button
│       │   └── config/
│       │       └── ConfigGeneral.qml          ← Settings UI: interval, whitelist
│       ├── config/
│       │   ├── config.qml                     ← Config category registration
│       │   └── main.xml                       ← Config key schema (KConfigXT)
│       └── scripts/
│           └── launch-tui.sh                  ← Konsole launch wrapper
│
├── backend/                                   ← Data gathering engine
│   ├── netsentry-daemon.py                    ← Main daemon entry point
│   ├── parsers/
│   │   ├── __init__.py
│   │   ├── proc_net.py                        ← /proc/net/tcp,udp parsers
│   │   └── inode_map.py                       ← Inode→PID mapping via /proc/*/fd/
│   ├── models.py                              ← Dataclasses: SocketEntry, Alert, Snapshot
│   ├── alert_engine.py                        ← Baseline + suspicious port detection
│   └── writers/
│       ├── __init__.py
│       ├── json_file.py                       ← JSON file writer (/tmp/netsentry-data.json)
│       └── unix_socket.py                     ← Unix domain socket server (future)
│
├── tui/                                       ← Terminal User Interface
│   ├── netsentry_tui.py                       ← Textual App entry point
│   ├── screens/
│   │   ├── __init__.py
│   │   ├── main_screen.py                     ← Split-pane main layout
│   │   └── kill_confirm.py                    ← SIGTERM/SIGKILL confirmation modal
│   ├── widgets/
│   │   ├── __init__.py
│   │   ├── port_table.py                      ← Left pane: DataTable of listening ports
│   │   ├── connection_log.py                  ← Right pane: RichLog of active connections
│   │   └── status_bar.py                      ← Bottom bar: alert count + refresh timer
│   ├── data/
│   │   ├── __init__.py
│   │   └── provider.py                        ← JSON file reader / socket client
│   └── styles.tcss                            ← Textual CSS dark security theme
│
├── shared/                                    ← Shared constants
│   ├── __init__.py
│   └── constants.py                           ← Paths, default ports, alert levels
│
├── polkit/
│   └── com.netsentry.helper.policy            ← Polkit policy for privileged helper
│
├── install.sh                                 ← One-shot installation script
└── README.md                                  ← Documentation
```

---

## Tasks

### Phase 1: Foundation (shared data layer)

#### Task 1: Create `shared/constants.py`
- **File**: `~/NetSentry/shared/__init__.py` + `~/NetSentry/shared/constants.py`
- **Purpose**: Single source of truth for all paths, default config values, known malicious ports, and alert severity levels.
- **Key contents**:
  - `DATA_FILE = "/tmp/netsentry-data.json"` — JSON snapshot path
  - `SOCKET_PATH = f"/run/user/{os.getuid()}/netsentry.sock"` — Unix socket path
  - `DEFAULT_POLL_INTERVAL = 2.0` — seconds
  - `ALERT_POLL_INTERVAL = 1.0`, `IDLE_POLL_INTERVAL = 10.0`
  - `MALICIOUS_PORTS = {4444, 5555, 31337, 12345, 6666, 6667, 6668, 6669}` — known malware ports
  - `PRIVILEGED_PORTS = range(1, 1024)` — system port range
  - `AlertLevel = enum("INFO", "WARNING", "CRITICAL")`
  - `KNOWN_SAFE_PORTS = {22: "sshd", 80: "httpd", 443: "https", 631: "cups", 5353: "avahi"}` — default whitelist
  - `PROC_TCP = "/proc/net/tcp"`, `PROC_TCP6 = "/proc/net/tcp6"`, etc.
- **Complexity**: S
- **Acceptance**: File imports without error, constants are referenced by all other modules.

---

#### Task 2: Create `backend/models.py`
- **File**: `~/NetSentry/backend/models.py`
- **Purpose**: Dataclass definitions for all structured data in the system.
- **Key contents**:
  ```python
  @dataclass
  class SocketEntry:
      proto: str              # "tcp" | "udp"
      local_ip: str           # "0.0.0.0"
      local_port: int         # 22
      remote_ip: str          # "0.0.0.0" or external
      remote_port: int        # 0 or external
      state: str              # "LISTEN" | "ESTABLISHED" | "TIME_WAIT" etc.
      state_code: str         # "0A" (hex from /proc)
      uid: int
      inode: int
      pid: Optional[int]
      process_name: Optional[str]
      cmdline: Optional[str]

  @dataclass
  class Alert:
      level: AlertLevel       # INFO | WARNING | CRITICAL
      port: int
      proto: str
      process_name: Optional[str]
      pid: Optional[int]
      message: str
      timestamp: float

  @dataclass
  class Snapshot:
      timestamp: float
      poll_interval_ms: int
      listening: List[SocketEntry]
      established: List[SocketEntry]
      alerts: List[Alert]
      summary: Dict[str, int]  # total_listening, total_established, alert_count
  ```
- **Complexity**: S
- **Acceptance**: All dataclasses instantiate correctly. `Snapshot.to_json()` and `Snapshot.from_json()` methods work.

---

### Phase 2: Backend Data Gathering

#### Task 3: Create `backend/parsers/proc_net.py`
- **File**: `~/NetSentry/backend/parsers/__init__.py` + `~/NetSentry/backend/parsers/proc_net.py`
- **Purpose**: Parse `/proc/net/tcp`, `/proc/net/tcp6`, `/proc/net/udp`, `/proc/net/udp6` into `List[SocketEntry]`.
- **Key functions**:
  - `parse_proc_net(path: str, proto: str) -> List[SocketEntry]`
  - `_parse_hex_ip(hex_str: str) -> str` — Convert hex IP from /proc to dotted notation (handle IPv4 and IPv6)
  - `_parse_hex_port(hex_str: str) -> int` — Convert hex port
  - `_decode_state(state_hex: str) -> str` — Map TCP state codes (0A=LISTEN, 06=TIME_WAIT, 01=ESTABLISHED, 07=CLOSE, etc.)
- **Implementation notes**:
  - Each line format: `sl  local_address rem_address st tx_queue rx_queue tr tm->when retrnsmt   uid  timeout inode`
  - Skip header line (starts with "sl")
  - IPv6 addresses are 32-char hex (4 words of 8 hex chars, little-endian per word)
  - UDP state "07" = UNCONN (unconnected)
- **Complexity**: M
- **Dependencies**: Task 1, Task 2
- **Acceptance**: `parse_proc_net("/proc/net/tcp", "tcp")` returns valid `SocketEntry` list. Test with real `/proc/net/tcp` data.

---

#### Task 4: Create `backend/parsers/inode_map.py`
- **File**: `~/NetSentry/backend/parsers/inode_map.py`
- **Purpose**: Map socket inodes to PIDs by scanning `/proc/[pid]/fd/`.
- **Key functions**:
  - `build_inode_to_pid_map() -> Dict[int, Tuple[int, str, str]]` — Returns `{inode: (pid, process_name, cmdline)}`
  - Implementation:
    1. Iterate `/proc/` entries, filter numeric (PIDs)
    2. For each PID, read `/proc/{pid}/fd/` directory
    3. For each fd, `os.readlink()` → if starts with `socket:[`, extract inode number
    4. Read `/proc/{pid}/cmdline` for process name (first arg, split null byte)
    5. Read `/proc/{pid}/comm` for short process name
  - Handle `PermissionError` (skip PIDs we can't read)
  - Handle `FileNotFoundError` (process disappeared between steps)
- **Complexity**: M
- **Dependencies**: Task 2
- **Acceptance**: Returns dict mapping inodes to (pid, name, cmdline). Works without root for user processes.

---

#### Task 5: Create `backend/alert_engine.py`
- **File**: `~/NetSentry/backend/alert_engine.py`
- **Purpose**: Baseline learning + suspicious port + malicious port alert generation.
- **Key class**: `AlertEngine`
  - `__init__(self, known_safe_ports: Dict[int, str], baseline_duration: float = 300.0)`
  - `update_baseline(snapshot: List[SocketEntry])` — During first 5 min, record all ports as baseline
  - `analyze(snapshot: List[SocketEntry]) -> List[Alert]` — Check against rules:
    1. Port in `MALICIOUS_PORTS` → CRITICAL
    2. Port < 1024, not in known_safe_ports, not in baseline → WARNING
    3. New listening port not in baseline → INFO
    4. Process with no cmdline or deleted binary → WARNING
    5. Sudden burst of 3+ new ports in one cycle → WARNING
  - `is_baseline_complete() -> bool`
  - `save_baseline(path: str)` / `load_baseline(path: str)` — Persist to `~/.config/netsentry/baseline.json`
- **Complexity**: M
- **Dependencies**: Task 1, Task 2
- **Acceptance**: Alerts fire correctly for known malicious ports. Baseline stabilizes after 5 min of no changes.

---

#### Task 6: Create `backend/writers/json_file.py`
- **File**: `~/NetSentry/backend/writers/__init__.py` + `~/NetSentry/backend/writers/json_file.py`
- **Purpose**: Write `Snapshot` to `/tmp/netsentry-data.json` atomically.
- **Key functions**:
  - `write_snapshot(snapshot: Snapshot, path: str = DATA_FILE)` — Atomically write JSON (write to `.tmp`, then `os.rename()`)
  - `read_snapshot(path: str = DATA_FILE) -> Optional[Snapshot]` — Read and parse JSON back
- **Implementation notes**:
  - Use atomic rename to prevent partial reads by the widget
  - JSON structure:
    ```json
    {
      "timestamp": 1717000000.123,
      "poll_interval_ms": 2000,
      "listening": [...],
      "established": [...],
      "alerts": [...],
      "summary": {"total_listening": 5, "total_established": 23, "alert_count": 0}
    }
    ```
- **Complexity**: S
- **Dependencies**: Task 1, Task 2
- **Acceptance**: Write + read roundtrip produces identical `Snapshot`.

---

#### Task 7: Create `backend/netsentry-daemon.py`
- **File**: `~/NetSentry/backend/netsentry-daemon.py`
- **Purpose**: Main daemon loop — gathers data, runs alerts, writes JSON.
- **Key logic**:
  ```
  1. Parse args: --interval, --verbose, --foreground
  2. Load or create baseline
  3. Loop:
     a. parse_proc_net() × 4 files → raw socket entries
     b. build_inode_to_pid_map() → pid resolution
     c. Merge inode map into socket entries
     d. Split into listening (state=LISTEN/UNCONN) vs established
     e. alert_engine.analyze(listening) → alerts
     f. Build Snapshot
     g. write_snapshot(snapshot)
     h. Adaptive sleep (2s normal, 1s if alerts, 10s if idle 5min no changes)
  ```
- **Complexity**: M
- **Dependencies**: Task 3, Task 4, Task 5, Task 6
- **Acceptance**: Daemon runs, `/tmp/netsentry-data.json` updates every ~2s. CPU usage < 1%. Handles `SIGTERM` gracefully. Works as `python3 netsentry-daemon.py` and as systemd user service.

---

### Phase 3: Plasma 6 Widget

#### Task 8: Fix `widget/metadata.json`
- **File**: `~/NetSentry/widget/metadata.json`
- **Changes**: The existing file needs updates to match the reference plasmoids on this system:
  - Add `"X-Plasma-ServiceTypes": ["Plasma/Applet"]` (required, currently uses `KPackageStructure` which should be changed to match reference pattern)
  - Actually, looking at netspeedWidget, it uses `KPackageStructure: ["Plasma/Applet"]` — keep this but also verify
  - The existing file has `KPackageStructure` as an array which matches the reference — **this is correct**
  - However, missing `EnabledByDefault: true`
  - Current file is mostly correct — only minor tweaks needed
- **Complexity**: S
- **Acceptance**: `plasmoidviewer -a ~/NetSentry/widget` loads without error.

---

#### Task 9: Create `widget/contents/config/main.xml`
- **File**: `~/NetSentry/widget/contents/config/main.xml`
- **Purpose**: KConfigXT schema for widget settings.
- **Key config entries**:
  ```xml
  <group name="General">
      <entry name="pollInterval" type="Double">
          <default>2.0</default>
      </entry>
      <entry name="showPortCount" type="Bool">
          <default>true</default>
      </entry>
      <entry name="alertThreshold" type="String">
          <default>WARNING</default>  <!-- INFO, WARNING, CRITICAL -->
      </entry>
      <entry name="knownSafePorts" type="String">
          <default>22,80,443,631,5353,631</default>
      </entry>
      <entry name="tuiCommand" type="String">
          <default>python3 ~/NetSentry/tui/netsentry_tui.py</default>
      </entry>
      <entry name="daemonEnabled" type="Bool">
          <default>true</default>
      </entry>
  </group>
  ```
- **Complexity**: S
- **Dependencies**: None
- **Acceptance**: Config keys accessible via `plasmoid.configuration.pollInterval` in QML.

---

#### Task 10: Create `widget/contents/config/config.qml`
- **File**: `~/NetSentry/widget/contents/config/config.qml`
- **Purpose**: Register config categories for the widget settings dialog.
- **Pattern** (from netspeedWidget reference):
  ```qml
  import org.kde.plasma.configuration 2.0
  ConfigModel {
      ConfigCategory {
          name: i18n('General')
          icon: 'preferences-system'
          source: 'config/ConfigGeneral.qml'
      }
  }
  ```
- **Complexity**: S
- **Acceptance**: Settings dialog opens from widget context menu.

---

#### Task 11: Create `widget/contents/ui/main.qml`
- **File**: `~/NetSentry/widget/contents/ui/main.qml`
- **Purpose**: Root `PlasmoidItem` element. Manages data polling via `PlasmaCore.DataSource` (executable engine), holds state properties, wires compact/full representations.
- **Key structure**:
  ```qml
  import QtQuick
  import org.kde.plasma.plasmoid
  import org.kde.plasma.plasma5support as Plasma5Support

  PlasmoidItem {
      id: root

      // Config properties
      property double pollInterval: plasmoid.configuration.pollInterval
      property string tuiCommand: plasmoid.configuration.tuiCommand

      // Data state
      property var snapshotData: null
      property int listeningCount: 0
      property int alertCount: 0
      property string threatLevel: "secure"  // "secure" | "warning" | "critical"
      property var alertList: []

      // ToolTip
      Plasmoid.title: i18n("NetSentry")
      Plasmoid.toolTipMainText: i18n("Network Monitor")
      Plasmoid.toolTipSubText: listeningCount + " listening ports, " + alertCount + " alerts"

      // Representations
      compactRepresentation: CompactRepresentation {}
      fullRepresentation: FullRepresentation {}

      // Data source: poll JSON file via cat command
      Plasma5Support.DataSource {
          id: dataSource
          engine: 'executable'
          connectedSources: ["cat /tmp/netsentry-data.json"]
          interval: pollInterval * 1000

          onNewData: (sourceName, data) => {
              if (data['exit code'] === 0 && data.stdout) {
                  try {
                      var parsed = JSON.parse(data.stdout)
                      root.snapshotData = parsed
                      root.listeningCount = parsed.summary.total_listening
                      root.alertCount = parsed.summary.alert_count
                      root.alertList = parsed.alerts

                      if (parsed.alerts.length > 0) {
                          var hasCritical = parsed.alerts.some(a => a.level === "CRITICAL")
                          root.threatLevel = hasCritical ? "critical" : "warning"
                      } else {
                          root.threatLevel = "secure"
                      }
                  } catch(e) {
                      console.log("NetSentry parse error: " + e)
                  }
              }
          }
      }

      // Launch TUI action
      function launchTUI() {
          execSource.connectedSources = [
              "nohup konsole -e bash ~/NetSentry/widget/contents/scripts/launch-tui.sh &"
          ]
      }

      Plasma5Support.DataSource {
          id: execSource
          engine: 'executable'
          connectedSources: []
          onNewData: (sourceName, data) => {
              connectedSources = []
          }
      }
  }
  ```
- **Complexity**: M
- **Dependencies**: Task 8, Task 9, Task 12, Task 13
- **Acceptance**: Widget loads in panel, polls JSON file every 2s, updates properties.

---

#### Task 12: Create `widget/contents/ui/CompactRepresentation.qml`
- **File**: `~/NetSentry/widget/contents/ui/CompactRepresentation.qml`
- **Purpose**: Panel tray icon — dynamic shield icon + port count badge.
- **Key visuals**:
  - Icon: `security-high` (green, secure) / `security-medium` (yellow, warning) / `security-low` (red, critical)
  - Badge: Number showing `listeningCount` (small text overlay)
  - Tooltip: Summary text
- **Pattern** (adapted from netspeedWidget's CompactRepresentation):
  ```qml
  import QtQuick
  import QtQuick.Layouts
  import org.kde.plasma.core as PlasmaCore
  import org.kde.kirigami as Kirigami

  Item {
      id: compactRoot
      anchors.fill: parent

      readonly property string shieldIcon: {
          if (root.threatLevel === "critical") return "security-low"
          if (root.threatLevel === "warning") return "security-medium"
          return "security-high"
      }

      Kirigami.Icon {
          id: shieldIconItem
          source: compactRoot.shieldIcon
          anchors.centerIn: parent
          width: parent.height * 0.7
          height: parent.height * 0.7
      }

      Text {
          id: badge
          anchors.top: parent.top
          anchors.right: parent.right
          text: root.listeningCount
          font.pixelSize: parent.height * 0.35
          font.bold: true
          color: root.threatLevel === "critical" ? "red" :
                 root.threatLevel === "warning" ? "yellow" :
                 Kirigami.Theme.textColor
      }
  }
  ```
- **Complexity**: S
- **Dependencies**: Task 11 (main.qml provides `root` context)
- **Acceptance**: Icon changes with threat level. Badge shows correct count.

---

#### Task 13: Create `widget/contents/ui/FullRepresentation.qml`
- **File**: `~/NetSentry/widget/contents/ui/FullRepresentation.qml`
- **Purpose**: Popup panel showing listening ports summary table + "Launch Advanced Network Analyzer" button.
- **Key layout** (Kirigami-based):
  - Header: "NetSentry — Network Security Monitor"
  - Listening ports list (ListView with ListModel, columns: Process, PID, Proto, Port)
  - Alert indicators (red/yellow/green dots next to entries with alerts)
  - Footer: Button "🚀 Launch Advanced Network Analyzer" → calls `root.launchTUI()`
  - Status text: "Last updated: ..." + refresh indicator
- **Complexity**: M
- **Dependencies**: Task 11 (main.qml provides `root.launchTUI()` and `root.snapshotData`)
- **Acceptance**: Popup shows port table populated from JSON data. Button launches Konsole with TUI.

---

#### Task 14: Create `widget/contents/ui/config/ConfigGeneral.qml`
- **File**: `~/NetSentry/widget/contents/ui/config/ConfigGeneral.qml`
- **Purpose**: Settings UI for polling interval, alert threshold, known-safe ports whitelist, TUI command.
- **Pattern**: Use `Kirigami.FormLayout` with spinboxes, text fields, and combo boxes bound to `plasmoid.configuration.*`.
- **Complexity**: S
- **Dependencies**: Task 9 (main.xml defines the config keys)
- **Acceptance**: Changes in settings dialog persist and take effect on widget reload.

---

#### Task 15: Create `widget/contents/scripts/launch-tui.sh`
- **File**: `~/NetSentry/widget/contents/scripts/launch-tui.sh`
- **Purpose**: Wrapper script to launch the TUI in Konsole. Handles path resolution.
- **Contents**:
  ```bash
  #!/usr/bin/env bash
  export PYTHONPATH="/home/$USER/NetSentry:$PYTHONPATH"
  exec python3 /home/$USER/NetSentry/tui/netsentry_tui.py
  ```
- **Complexity**: XS
- **Dependencies**: Task 7 (daemon must be running for data)
- **Acceptance**: `bash launch-tui.sh` launches TUI in current terminal. `konsole -e bash launch-tui.sh` launches in new Konsole window.

---

### Phase 4: TUI Application

#### Task 16: Create `tui/styles.tcss`
- **File**: `~/NetSentry/tui/styles.tcss`
- **Purpose**: Textual CSS dark security theme.
- **Key styling**:
  ```css
  Screen {
      background: $surface;
      color: $text;
  }

  #port-table {
      width: 1fr;
      border: round $primary;
      padding: 0 1;
  }

  #connection-log {
      width: 2fr;
      border: round $primary;
      padding: 0 1;
  }

  #status-bar {
      dock: bottom;
      height: 1;
      background: $primary;
      color: $text;
      content-align: center middle;
  }

  #header-bar {
      dock: top;
      height: 1;
      background: $primary;
      color: $text;
      content-align: center middle;
      text-style: bold;
  }
  ```
- **Complexity**: S
- **Dependencies**: None
- **Acceptance**: TUI loads with dark theme, no visual artifacts.

---

#### Task 17: Create `tui/data/provider.py`
- **File**: `~/NetSentry/tui/data/__init__.py` + `~/NetSentry/tui/data/provider.py`
- **Purpose**: Read JSON data from `/tmp/netsentry-data.json` and convert to `Snapshot`.
- **Key class**: `DataProvider`
  - `fetch() -> Optional[Snapshot]` — Read JSON file, parse to dataclass
  - `kill_process(pid: int) -> Tuple[bool, str]` — Send SIGTERM, wait 5s, SIGKILL if needed
  - Handle `PermissionError` gracefully (report "need root to kill this process")
- **Complexity**: S
- **Dependencies**: Task 2, Task 6
- **Acceptance**: `DataProvider().fetch()` returns valid Snapshot when daemon is running.

---

#### Task 18: Create `tui/widgets/port_table.py`
- **File**: `~/NetSentry/tui/widgets/__init__.py` + `~/NetSentry/tui/widgets/port_table.py`
- **Purpose**: Left pane — DataTable showing all listening ports.
- **Key features**:
  - Columns: Process Name, PID, Protocol, Local Address:Port, State, Alert
  - Sortable by column
  - Cursor-selectable (for kill action)
  - Color-coded rows: green (known safe), yellow (new/info), red (alert/critical)
- **Implementation**: Extend `textual.widgets.DataTable`
  - `update_data(entries: List[SocketEntry], alerts: List[Alert])` — Clear and re-populate
- **Complexity**: M
- **Dependencies**: Task 2
- **Acceptance**: Table populates with listening ports, rows are selectable.

---

#### Task 19: Create `tui/widgets/connection_log.py`
- **File**: `~/NetSentry/tui/widgets/connection_log.py`
- **Purpose**: Right pane — RichLog showing real-time active connections.
- **Key features**:
  - Color-coded connection entries (green=ESTABLISHED, dim=TIME_WAIT, etc.)
  - Auto-scroll to latest
  - Rich markup formatting: `[bold green]ESTABLISHED[/bold green] 192.168.1.10:44532 → 142.250.80.14:443 (firefox)`
  - Timestamp per entry
- **Complexity**: S
- **Dependencies**: Task 2
- **Acceptance**: Log shows formatted connection entries, auto-scrolls.

---

#### Task 20: Create `tui/widgets/status_bar.py`
- **File**: `~/NetSentry/tui/widgets/status_bar.py`
- **Purpose**: Bottom status bar showing alert count, refresh indicator, key hints.
- **Key display**: `🔒 Secure | 5 listening | 23 established | 0 alerts | [q]uit [k]ill [r]efresh`
- **Complexity**: S
- **Dependencies**: None
- **Acceptance**: Status bar updates with current counts.

---

#### Task 21: Create `tui/screens/kill_confirm.py`
- **File**: `~/NetSentry/tui/screens/__init__.py` + `~/NetSentry/tui/screens/kill_confirm.py`
- **Purpose**: Modal dialog for confirming process termination.
- **Key features**:
  - Shows process name, PID, port, and reason for kill
  - Buttons: "SIGTERM (graceful)" / "SIGKILL (force)" / "Cancel"
  - Returns result to parent screen
- **Pattern**: Extend `textual.screen ModalScreen`
- **Complexity**: M
- **Dependencies**: Task 17
- **Acceptance**: Dialog appears on `k` press. SIGTERM sends signal. Shows success/failure message.

---

#### Task 22: Create `tui/screens/main_screen.py`
- **File**: `~/NetSentry/tui/screens/main_screen.py`
- **Purpose**: Main TUI screen — horizontal split layout combining all widgets.
- **Key structure**:
  ```python
  class MainScreen(Screen):
      def compose(self) -> ComposeResult:
          yield Horizontal(
              PortTable(id="port-table"),
              ConnectionLog(id="connection-log"),
          )
          yield StatusBar(id="status-bar")

      def on_mount(self):
          self.set_interval(2.0, self.refresh_data)

      def refresh_data(self):
          snapshot = self.provider.fetch()
          if snapshot:
              self.query_one(PortTable).update_data(snapshot.listening, snapshot.alerts)
              self.query_one(ConnectionLog).update_data(snapshot.established)
              self.query_one(StatusBar).update(snapshot.summary, snapshot.alerts)
  ```
- **Key bindings**: `BINDINGS = [("q", "quit", "Quit"), ("k", "kill", "Kill"), ("r", "refresh", "Refresh")]`
- **Complexity**: M
- **Dependencies**: Task 18, Task 19, Task 20, Task 21
- **Acceptance**: Screen renders split layout. Data refreshes every 2s. Kill binding opens confirmation dialog.

---

#### Task 23: Create `tui/netsentry_tui.py`
- **File**: `~/NetSentry/tui/netsentry_tui.py`
- **Purpose**: Textual App entry point.
- **Key structure**:
  ```python
  class NetSentryTUI(App):
      TITLE = "NetSentry — Network Security Analyzer"
      CSS_PATH = "styles.tcss"
      BINDINGS = [("q", "quit", "Quit"), ("ctrl+c", "quit", "Quit")]

      def on_mount(self):
          self.push_screen(MainScreen())

  if __name__ == "__main__":
      app = NetSentryTUI()
      app.run()
  ```
- **Complexity**: S
- **Dependencies**: Task 22, Task 16
- **Acceptance**: `python3 netsentry_tui.py` launches full TUI with split layout, live data, and key bindings.

---

### Phase 5: Integration & Deployment

#### Task 24: Create `polkit/com.netsentry.helper.policy`
- **File**: `~/NetSentry/polkit/com.netsentry.helper.policy`
- **Purpose**: Polkit policy file for optional privileged helper (system-wide PID visibility).
- **Key contents**: Standard polkit XML with action `com.netsentry.helper.getports`, allow_any/auth_admin, allow_active=auth_admin_keep.
- **Complexity**: S
- **Dependencies**: None
- **Acceptance**: `pkexec` prompt appears when helper runs. Not needed for basic user-level monitoring.

---

#### Task 25: Create `install.sh`
- **File**: `~/NetSentry/install.sh`
- **Purpose**: One-shot installation script.
- **Key steps**:
  1. Check Python 3.10+ and pip
  2. Install Textual: `pip3 install textual rich`
  3. Create symlink: `ln -sf ~/NetSentry/widget ~/.local/share/plasma/plasmoids/com.netsentry.plasmoid`
  4. Create baseline config dir: `mkdir -p ~/.config/netsentry`
  5. Optionally: install polkit policy to `/usr/share/polkit-1/actions/`
  6. Restart plasma: `qdbus6 org.kde.plasmashell /PlasmaShell org.kde.PlasmaShell.evaluateScript "loadScript('main.qml')"` or just `plasmashell --replace &`
  7. Print instructions for adding widget to panel
- **Complexity**: S
- **Dependencies**: All previous tasks
- **Acceptance**: After running script, widget appears in widget picker and can be added to panel.

---

#### Task 26: Create `README.md`
- **File**: `~/NetSentry/README.md`
- **Purpose**: Full project documentation.
- **Sections**: Overview, Architecture, Requirements, Installation, Usage (Widget + TUI), Configuration, Security Model, Known Limitations, Development.
- **Complexity**: S
- **Dependencies**: All previous tasks
- **Acceptance**: README covers installation, usage, and architecture.

---

## Files Summary

| # | File | Purpose | Complexity | Depends on |
|---|------|---------|-----------|------------|
| 1 | `shared/constants.py` | Paths, defaults, malicious ports | S | — |
| 2 | `backend/models.py` | Dataclasses for all data | S | 1 |
| 3 | `backend/parsers/proc_net.py` | /proc/net/tcp parsing | M | 1, 2 |
| 4 | `backend/parsers/inode_map.py` | Inode→PID mapping | M | 2 |
| 5 | `backend/alert_engine.py` | Baseline + alert rules | M | 1, 2 |
| 6 | `backend/writers/json_file.py` | Atomic JSON file writer | S | 1, 2 |
| 7 | `backend/netsentry-daemon.py` | Main daemon loop | M | 3, 4, 5, 6 |
| 8 | `widget/metadata.json` | Fix existing metadata | S | — |
| 9 | `widget/contents/config/main.xml` | KConfigXT schema | S | — |
| 10 | `widget/contents/config/config.qml` | Config categories | S | — |
| 11 | `widget/contents/ui/main.qml` | Root PlasmoidItem + DataSource | M | 8, 9, 12, 13 |
| 12 | `widget/contents/ui/CompactRepresentation.qml` | Panel icon + badge | S | 11 |
| 13 | `widget/contents/ui/FullRepresentation.qml` | Popup port table + launch | M | 11 |
| 14 | `widget/contents/ui/config/ConfigGeneral.qml` | Settings UI | S | 9 |
| 15 | `widget/contents/scripts/launch-tui.sh` | Konsole launch wrapper | XS | 7 |
| 16 | `tui/styles.tcss` | Dark security theme | S | — |
| 17 | `tui/data/provider.py` | JSON reader + process killer | S | 2, 6 |
| 18 | `tui/widgets/port_table.py` | DataTable of listening ports | M | 2 |
| 19 | `tui/widgets/connection_log.py` | RichLog of connections | S | 2 |
| 20 | `tui/widgets/status_bar.py` | Bottom status bar | S | — |
| 21 | `tui/screens/kill_confirm.py` | Kill confirmation modal | M | 17 |
| 22 | `tui/screens/main_screen.py` | Main split-pane screen | M | 18, 19, 20, 21 |
| 23 | `tui/netsentry_tui.py` | TUI App entry point | S | 22, 16 |
| 24 | `polkit/com.netsentry.helper.policy` | Polkit policy | S | — |
| 25 | `install.sh` | Installation script | S | All |
| 26 | `README.md` | Documentation | S | All |

---

## Implementation Order (Respecting Dependencies)

```
Phase 1 (Foundation):     Tasks 1, 2
Phase 2 (Backend):        Tasks 3, 4, 5, 6 (parallel), then 7
Phase 3 (Widget):         Tasks 8, 9, 10 (parallel), then 11, then 12, 13, 14, 15
Phase 4 (TUI):            Task 16, 17 (parallel), then 18, 19, 20 (parallel), then 21, 22, 23
Phase 5 (Integration):    Tasks 24, 25, 26
```

**Worker agents can parallelize**:
- Tasks 3+4+5+6 can be implemented simultaneously (they only depend on 1+2)
- Tasks 18+19+20 can be implemented simultaneously (all independent widgets)
- Tasks 8+9+10 can be implemented simultaneously (independent widget config files)

---

## Testing Strategy

| Component | Test Method | Command |
|-----------|------------|---------|
| `/proc/net` parser | Unit test with sample data | `python3 -m pytest backend/tests/test_proc_net.py` |
| Inode mapper | Live test against real `/proc` | `python3 -c "from backend.parsers.inode_map import build_inode_to_pid_map; print(build_inode_to_pid_map())"` |
| Alert engine | Unit test with mock entries | `python3 -m pytest backend/tests/test_alert_engine.py` |
| JSON writer | Roundtrip test | `python3 -c "from backend.writers.json_file import *; ..."` |
| Daemon | Manual run + check output file | `python3 backend/netsentry-daemon.py --foreground` |
| Widget | `plasmoidviewer` | `plasmoidviewer -a ~/NetSentry/widget` |
| TUI | Manual run in Konsole | `python3 tui/netsentry_tui.py` |
| Full integration | Start daemon → add widget → verify data flow → launch TUI | End-to-end manual test |

---

## Risks

1. **DataSource exec engine deprecation**: Plasma 6 is gradually moving away from DataEngines. The `executable` engine works now but may be removed in Plasma 6.7+. **Mitigation**: Current approach works for Plasma 6.6; future migration path is D-Bus or a QProcess-based helper.

2. **`/proc/net/tcp` readability**: On standard desktop Linux this is world-readable. On hardened kernels or containers, it may be restricted. **Mitigation**: Fall back to `ss --json -tuln` if `/proc/net/tcp` is unreadable.

3. **QML JSON parsing**: The `Plasma5Support.DataSource` captures `stdout` as a string. Large JSON blobs (>10KB) may cause performance issues. **Mitigation**: Keep JSON output minimal (exclude established connections from widget payload if >100 entries; TUI gets full data).

4. **Wayland + `konsole -e`**: Under Wayland, launching Konsole from a plasmoid via `nohup konsole -e ...` should work since Konsole is a native Wayland app. **Mitigation**: Test on target system; if issues, use `kioclient exec` or D-Bus Konsole interface.

5. **PID visibility**: Non-root users can only see their own processes' `/proc/[pid]/fd/`. System services (sshd, cupsd) owned by root won't have PID resolution without privilege escalation. **Mitigation**: Show port + "unknown (system)" when PID can't be resolved. Provide Polkit helper for full visibility.

6. **Textual version**: Textual 1.x API is stable but ensure `pip install textual` installs ≥ 1.0. The Python 3.14 on this system is compatible.

7. **Atomic JSON writes**: Without atomic rename, the widget may read a partially-written JSON file. **Mitigation**: Write to `.tmp` file first, then `os.rename()` (atomic on same filesystem).

8. **Panel widget sizing**: The `CompactRepresentation` must work in both horizontal and vertical panels. **Mitigation**: Test Layout.minimumWidth/Height calculations against panel size, following the netspeedWidget pattern.
