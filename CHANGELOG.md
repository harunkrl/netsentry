# Changelog

All notable changes to this project will be documented in this file.

## [1.0.0] - 2026-05-31

### Added
- **Widget**: Search and Sort functionality for the connections list.
- **Widget**: Alert Details Display via tooltips on hover.
- **Widget**: Context Menu for copying connection details (IP, Port, PID) and killing processes.
- **Widget**: Daemon-Down warning banner when backend stops responding.
- **TUI**: Split-pane layout with real-time `ConnectionLog` streaming.
- **TUI**: Live filtering of both PortTable and ConnectionLog via `/` shortcut.
- **TUI**: New `DetailScreen` for inspecting full socket details (Cmdline, UID, etc.).
- **TUI**: JSON Export functionality (`e` shortcut) to save snapshot data.
- **TUI**: Help screen (`?` shortcut) for keyboard navigation.
- **Backend**: SIGHUP signal handler to dynamically reset the learned baseline.
- **Backend**: Thread-safe caching and JSON writing.

### Changed
- **Widget**: Replaced static JS array with Qt `ListModel` for efficient diff-based rendering.
- **Widget**: Optimized O(1) alert lookup maps in the delegate.
- **Backend**: IPC now uses single-pass JSON serialization to reduce CPU overhead.
- **Backend**: Unbounded growth protections added to `notified_alerts` and `rdns_cache`.
- **Backend**: Systemd service now uses hardened security parameters (`ProtectSystem=strict`, etc.).

### Fixed
- Widget race conditions between `kill` action and TUI launching by decoupling DataSources.
- Fixed malformed snapshot crashes in the TUI by adding exception boundaries.
- Daemon duplication bug fixed using `fcntl` PID file locking.
