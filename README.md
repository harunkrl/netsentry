# NetSentry 🔒

**Local Network Security & Port Monitor** for KDE Plasma 6.6 on Arch Linux (EndeavourOS / Wayland)

A hybrid architecture combining a lightweight Plasma 6 panel widget for real-time passive alerting with a powerful Terminal User Interface (TUI) for deep network inspection.

---

## Architecture

```
  KERNEL (/proc/net/tcp, /proc/*/fd/*)
      │
      ▼
  BACKEND DAEMON (Python)
  • Parses /proc/net/{tcp,udp}{,6} directly
  • Maps socket inodes → PIDs via /proc/*/fd/
  • Alert engine with baseline learning
  • Writes JSON snapshot → /tmp/netsentry-data.json
      │                    │
      ▼                    ▼
  PLASMA WIDGET (QML)   TUI (Textual)
  • Shield icon + badge  • Split-pane layout
  • Port summary popup   • Real-time connection stream
  • Launch TUI button    • Kill process (SIGTERM/SIGKILL)
```

## Quick Start

```bash
# 1. Clone and install
cd ~
git clone <repo-url> NetSentry
cd NetSentry
chmod +x install.sh
./install.sh

# 2. Start the daemon (background)
.venv/bin/python3 backend/netsentry-daemon.py &

# 3. Add widget to panel
# Right-click panel → Add Widgets → search "NetSentry"

# 4. Launch TUI directly
.venv/bin/python3 tui/netsentry_tui.py
```

## Requirements

| Dependency | Version | Notes |
|-----------|---------|-------|
| KDE Plasma | 6.6+ | Wayland or X11 |
| Python | 3.10+ | 3.14 tested |
| Textual | 1.0+ | `pip install textual` |
| Rich | 13.0+ | `pip install rich` |
| Qt | 6.x | Comes with Plasma 6 |

## Components

### Backend Daemon (`backend/`)

- **`netsentry-daemon.py`** — Main daemon loop with adaptive polling (2s normal, 1s alert, 10s idle)
- **`parsers/proc_net.py`** — Parses `/proc/net/{tcp,udp}{,6}` into structured `SocketEntry` objects
- **`parsers/inode_map.py`** — Maps socket inodes to PIDs via `/proc/[pid]/fd/` scanning
- **`alert_engine.py`** — Baseline learning (5 min) + malicious port detection + anomaly alerts
- **`writers/json_file.py`** — Atomic JSON file writer (write → rename)

### Plasma Widget (`widget/`)

- **CompactRepresentation** — Panel icon: dynamic shield (security-high/medium/low) + port count badge
- **FullRepresentation** — Popup: listening ports table with alert indicators + "Launch Analyzer" button
- **ConfigGeneral** — Settings: polling interval, alert threshold, known-safe ports

### TUI Application (`tui/`)

- **Main Screen** — Horizontal split: PortTable (left) + ConnectionLog (right) + StatusBar (bottom)
- **Key bindings**: `q` quit, `k` kill process, `r` refresh
- **Kill Confirm** — Modal dialog with SIGTERM/SIGKILL options

## Configuration

Widget settings are accessible via right-click → Configure:

| Setting | Default | Description |
|---------|---------|-------------|
| `pollInterval` | 2.0 | Seconds between data refreshes |
| `alertThreshold` | WARNING | Minimum level to show alerts |
| `knownSafePorts` | 22,80,443,631,5353 | Comma-separated safe port list |
| `tuiCommand` | `python3 ~/NetSentry/tui/netsentry_tui.py` | Command to launch TUI |

## Security Model

- **No root required** for basic operation — `/proc/net/tcp` is world-readable
- **PID resolution** works for user-owned processes without privileges
- **System processes** (root-owned) show as "unknown (system)" without privilege escalation
- **Optional Polkit helper** (`polkit/com.netsentry.helper.policy`) for full PID visibility
- **Kill operations** require appropriate permissions (same-user processes only by default)

## Known Malicious Ports

The alert engine detects these by default: 4444, 5555, 31337, 12345, 12346, 6666-6669, 27374, 33270, 65000

## Auto-Start with systemd

```ini
# ~/.config/systemd/user/netsentry.service
[Unit]
Description=NetSentry Network Monitor Daemon
After=network.target

[Service]
Type=simple
ExecStart=/home/USER/NetSentry/.venv/bin/python3 /home/USER/NetSentry/backend/netsentry-daemon.py
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
```

```bash
systemctl --user daemon-reload
systemctl --user enable --now netsentry
```

## License

GPL-3.0
