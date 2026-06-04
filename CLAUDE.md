# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Overview

NetSentry is a hybrid network security monitor for KDE Plasma 6 on Arch Linux. Three components work together: a Python backend daemon (parses `/proc/net/`), a Textual TUI analyzer, and a Plasma 6 plasmoid widget.

## Build & Run Commands

```bash
# Install (editable, dev deps)
pip install -e ".[dev]"

# Run daemon (foreground)
netsentry-daemon --foreground

# Run TUI
netsentry

# Run client (unix socket stream)
netsentry-client

# Run tests
pytest
pytest tests/test_proc_net.py          # single test file
pytest tests/test_alert_engine.py -k "test_malicious"  # single test

# Install system-wide (widget + systemd service + symlinks)
./install.sh

# Uninstall
./uninstall.sh
```

## Architecture

### Data Flow
`/proc/net/{tcp,udp}{,6}` → **parsers/proc_net.py** → `SocketEntry` list → **inode_map.py** (enriches with PID) → **alert_engine.py** (baseline + rules) → **Snapshot** → two outputs:
1. **writers/json_file.py** — atomic JSON to `$XDG_RUNTIME_DIR/netsentry-data.json` (consumed by widget + TUI)
2. **writers/unix_socket.py** — unix domain socket at `$XDG_RUNTIME_DIR/netsentry.sock` (consumed by `netsentry-client`)

### Key Abstractions (backend/models.py)
- **`SocketEntry`** — one network socket (proto, IPs, ports, state, inode, PID, process)
- **`Alert`** — security alert (level, port, message) with `AlertLevel` enum (INFO/WARNING/CRITICAL)
- **`Snapshot`** — complete state at a point in time (listening + established sockets, alerts, summary)

### Alert Rules (backend/alert_engine.py)
- Malicious ports (4444, 5555, 31337, etc.) → CRITICAL
- Unknown privileged ports (<1024) → WARNING
- Burst detection (3+ new ports) → WARNING
- First 5 minutes: baseline learning of normal ports

### Package Layout
- `backend/` — daemon, parsers, alert engine, writers
- `tui/` — Textual app with screens/ and widgets/ subdirs
- `shared/` — constants, AlertLevel enum, paths, malicious port set
- `widget/` — QML/Kirigami Plasma 6 plasmoid
- `tests/` — pytest suite (conftest.py has shared fixtures)

### IPC
Widget reads JSON file on a polling timer. TUI reads same JSON. Unix socket provides streaming for `netsentry-client`. No DBus.

### Widget
QML-based, uses `Plasma5Support.DataSource` for polling. Config via KConfigXT (`widget/contents/config/main.xml`).

## Conventions
- Python 3.10+ (uses `match`, `X | Y` union syntax)
- Backend daemon is stdlib-only (no external deps); TUI uses textual + rich
- Atomic writes: JSON snapshot uses write-to-temp + `os.rename()` to prevent partial reads
- Polling intervals: 2s normal, 1s alert, 10s idle (constants in `shared/constants.py`)
- Tests use `conftest.py` for mock `/proc/net/` fixtures
