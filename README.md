<div align="center">

# 🔒 NetSentry

**Local Network Security & Port Monitor**

*A hybrid system tray + terminal analyzer for KDE Plasma 6*

![KDE Plasma 6.6](https://img.shields.io/badge/Plasma-6.6-1d99f3?logo=kde)
![Python 3.10+](https://img.shields.io/badge/Python-3.10+-3776ab?logo=python)
![Qt 6](https://img.shields.io/badge/Qt-6.x-41cd52?logo=qt)
![License](https://img.shields.io/badge/License-GPL--3.0-blue)

</div>

---

## 🖼️ Overview

NetSentry is a **hybrid architecture** network security monitor designed for Arch Linux (EndeavourOS) running **KDE Plasma 6.6** on **Wayland**. It combines:

| Component | Purpose |
|-----------|---------|
| **Plasma 6 Widget** | Real-time passive alerting in your panel — shield icon + port count badge |
| **Terminal Analyzer (TUI)** | Deep inspection with split-pane layout, keyboard-driven navigation, and process kill support |
| **Backend Daemon** | Lightweight `/proc/net` parser with alert engine and baseline learning |

```
  ┌─────────────────────────────────────────────┐
  │               KERNEL (/proc)                │
  │   /proc/net/tcp  /proc/net/udp  /proc/*/fd  │
  └────────────────────┬────────────────────────┘
                       │
          ┌────────────▼────────────┐
          │     BACKEND DAEMON      │
          │  • Parse /proc/net/*    │
          │  • Inode → PID mapping  │
          │  • Alert engine         │
          │  • Adaptive polling     │
          └─────┬────────────┬──────┘
                │            │
    ┌───────────▼──┐   ┌────▼─────────────┐
    │   PLASMOID   │   │   TUI (Textual)  │
    │  🔒 Widget   │   │  ┌──────┬──────┐ │
    │  Shield icon │   │  │Ports │Stream│ │
    │  + badge     │   │  ├──────┴──────┤ │
    │  + popup     │   │  │ Status Bar   │ │
    └──────────────┘   │  └─────────────┘ │
                       └──────────────────┘
```

---

## ✨ Features

### Widget (Panel)
- 🛡️ Dynamic shield icon — changes color based on threat level (green/yellow/red)
- 🔢 Port count badge showing listening sockets at a glance
- 📋 Popup with listening ports table (Process, PID, Proto, Port)
- ⚠️ Alert indicators for suspicious activity
- 🚀 One-click launch of the advanced TUI analyzer
- ⚙️ Configurable polling interval, alert threshold, and safe ports whitelist

### TUI (Terminal Analyzer)
- ⌨️ Keyboard-driven navigation (`q`uit, `k`ill, `r`efresh)
- 📊 Split-pane layout — port table (left) + connection stream (right)
- 🎨 Color-coded entries — green (safe), yellow (info), red (critical alert)
- 💀 Kill process with confirmation dialog — SIGTERM (graceful) or SIGKILL (force)
- 🔄 Auto-refresh every 2 seconds

### Backend Daemon
- 📡 Parses `/proc/net/{tcp,udp}{,6}` directly — zero dependencies, fast
- 🔗 Maps socket inodes to PIDs via `/proc/[pid]/fd/` scanning
- 🧠 Baseline learning — learns your normal ports during first 5 minutes
- 🚨 Alert rules:
  - Known malicious ports (4444, 5555, 31337, etc.) → **CRITICAL**
  - Unknown privileged ports (<1024) → **WARNING**
  - New listening ports → **INFO**
  - Processes with no cmdline → **WARNING**
  - Burst detection (3+ new ports) → **WARNING**
- ⚡ Adaptive polling — 2s normal, 1s on alert, 10s when idle
- 💾 Atomic JSON writes — no partial reads

---

## 🚀 Quick Start

### Prerequisites
- KDE Plasma 6.6+ (Wayland or X11)
- Python 3.10+
- `textual` and `rich` Python packages (auto-installed by install script)

### Installation

```bash
# Clone
git clone https://github.com/harunkrl/netsentry.git
cd netsentry

# Install
chmod +x install.sh
./install.sh

# Start the daemon via systemd (auto-starts at boot)
systemctl --user daemon-reload
systemctl --user enable --now netsentry

# Or run manually in foreground
.venv/bin/python3 backend/netsentry_daemon.py --foreground

# Add widget to panel
# Right-click panel → Add Widgets → search "NetSentry"
```

### Run TUI Directly

```bash
~/NetSentry/.venv/bin/python3 ~/NetSentry/tui/netsentry_tui.py
```

---

## 📁 Project Structure

```
NetSentry/
├── shared/
│   └── constants.py              # Paths, alert levels, malicious ports
├── backend/
│   ├── models.py                 # SocketEntry, Alert, Snapshot dataclasses
│   ├── parsers/
│   │   ├── proc_net.py           # /proc/net/tcp,udp parser (IPv4+IPv6)
│   │   └── inode_map.py          # Socket inode → PID mapping
│   ├── alert_engine.py           # Baseline learning + alert rules
│   ├── writers/
│   │   └── json_file.py          # Atomic JSON snapshot writer
│   └── netsentry_daemon.py       # Main daemon loop
├── widget/
│   ├── metadata.json             # Plasma 6 plugin metadata
│   └── contents/
│       ├── ui/
│       │   ├── main.qml          # Root PlasmoidItem + DataSource
│       │   ├── CompactRepresentation.qml  # Panel icon + badge
│       │   ├── FullRepresentation.qml     # Popup port table
│       │   └── config/
│       │       └── ConfigGeneral.qml      # Settings UI
│       ├── config/
│       │   ├── config.qml
│       │   └── main.xml          # KConfigXT schema
│       └── scripts/
│           └── launch-tui.sh     # Konsole launch wrapper
├── tui/
│   ├── netsentry_tui.py          # Textual App entry point
│   ├── screens/
│   │   ├── main_screen.py        # Split-pane main layout
│   │   └── kill_confirm.py       # SIGTERM/SIGKILL modal
│   ├── widgets/
│   │   ├── port_table.py         # DataTable of listening ports
│   │   ├── connection_log.py     # RichLog of active connections
│   │   └── status_bar.py         # Bottom status bar
│   ├── data/
│   │   └── provider.py           # JSON reader + process killer
│   └── styles.tcss               # Dark security theme
├── polkit/
│   └── com.netsentry.helper.policy
├── install.sh
└── README.md
```

---

## ⚙️ Configuration

Widget settings accessible via **right-click → Configure**:

| Setting | Default | Description |
|---------|---------|-------------|
| `pollInterval` | 2 | Seconds between data refreshes |
| `alertThreshold` | WARNING | Minimum alert level to display |
| `knownSafePorts` | 22,80,443,631,5353 | Comma-separated safe port list |
| `tuiCommand` | `python3 ~/NetSentry/tui/netsentry_tui.py` | TUI launch command |
| `daemonEnabled` | true | Auto-start daemon |

### Auto-Start with systemd

```bash
# Create user service
cat > ~/.config/systemd/user/netsentry.service << 'EOF'
[Unit]
Description=NetSentry Network Monitor Daemon
After=network.target

[Service]
Type=simple
ExecStart=/home/YOUR_USER/NetSentry/.venv/bin/python3 /home/YOUR_USER/NetSentry/backend/netsentry_daemon.py --foreground
Restart=on-failure
RestartSec=5

[Install]
WantedBy=default.target
EOF

# Enable and start
systemctl --user daemon-reload
systemctl --user enable --now netsentry
```

---

## 🔐 Security Model

| Aspect | Details |
|--------|---------|
| **Root required?** | ❌ No — `/proc/net/tcp` is world-readable |
| **PID resolution** | Works for user-owned processes without privileges |
| **System processes** | Shown as "unknown (system)" — root-owned `/proc/*/fd/` requires privilege escalation |
| **Optional helper** | Polkit policy included for full PID visibility |
| **Kill operations** | Only works for same-user processes by default |
| **Data exposure** | JSON written to `/tmp/` — contains port/PID info only (no secrets) |
| **Command injection** | Widget uses hardcoded paths — no user input in shell commands |

### Privilege Escalation (Optional)

For full system-wide PID visibility, choose one:

```bash
# Option A: sudoers rule
echo "YOUR_USER ALL=(root) NOPASSWD: /usr/bin/ss -tulnp" | sudo tee /etc/sudoers.d/netsentry

# Option B: file capabilities on a helper binary
sudo setcap cap_net_admin+ep /usr/local/bin/netsentry-helper

# Option C: Polkit policy (included)
sudo cp polkit/com.netsentry.helper.policy /usr/share/polkit-1/actions/
```

---

## 🏗️ Architecture Decisions

| Decision | Rationale |
|----------|-----------|
| Parse `/proc/net/` directly instead of `ss` | Zero dependencies, world-readable, ~2ms per parse |
| Inode → PID via `/proc/*/fd/` scanning | No root needed for user processes, ~45ms per scan |
| Atomic JSON file (write→rename) | Prevents partial reads, works across all consumers |
| Textual for TUI | Modern Python TUI framework, Wayland-native, rich styling |
| `Plasma5Support.DataSource` for widget | Standard Plasma 6 pattern for polling external data |
| Adaptive polling intervals | Minimizes CPU when idle, maximizes responsiveness on alerts |

---

## ⚠️ Known Limitations

- Non-root users can only resolve PIDs for their own processes
- UDP "connections" are stateless — shown as UNCONN in the table
- `TIME_WAIT`, `CLOSE_WAIT` etc. are grouped under "established" (active)
- The `executable` DataEngine is deprecated in future Plasma versions (6.7+)
- Emoji in TUI status bar may not render in all terminal fonts

---

## 🛠️ Tech Stack

| Component | Technology |
|-----------|-----------|
| Widget | QML, Kirigami, Plasma 6 Plasma5Support |
| TUI | Python Textual, Rich |
| Backend | Python 3.10+ (stdlib only) |
| IPC | JSON file via atomic rename |
| Desktop | KDE Plasma 6.6, Qt 6, Wayland |

---

## 📄 License

This project is licensed under the **GPL-3.0** License.

---

<div align="center">

**Built with ❤️ for KDE Plasma 6 on Arch Linux**

</div>
