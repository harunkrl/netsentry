# Changelog

All notable changes to this project will be documented in this file.

## [2.1.0] - 2026-06-07

### Added
- **Backend**: psutil-based collectors replacing manual /proc parsing (~50 lines vs ~560 lines).
- **Backend**: GeoIP lookup with persistent JSON cache and ipwho.is (HTTPS) primary / ip-api.com fallback.
- **Backend**: Unix domain socket server for streaming client (kportwatchctl).
- **Backend**: Daemon controller with start/stop/restart/status via D-Bus.
- **Backend**: Auto-update checker with GitHub release tracking.
- **Backend**: Export CLI (`kportwatch-export`) with CSV/JSON output, date filter, `--last N` support.
- **Backend**: Baseline learning engine with SIGHUP reset.
- **Backend**: Alert engine with burst detection, malicious ports, custom rules, whitelist/blacklist.
- **Backend**: Thread-safe config management with fcntl file locking.
- **TUI**: 8 built-in themes (Cyberpunk, Midnight, Hacker, Daylight, Nord, etc.).
- **TUI**: Settings screen with auto-save to TOML config.
- **TUI**: Connection map screen with ASCII world map and GeoIP overlay.
- **TUI**: Process tree screen with kill confirmation dialog.
- **TUI**: Port scan detection with configurable threshold.
- **TUI**: Safe clipboard copy across Wayland/X11.
- **Widget**: Dark/light Plasma themes, traffic display, port badge, kill action.
- **Widget**: Key-based model reconciliation (no stale index bugs).
- **Widget**: Passive notification banner.
- **CI/CD**: GitHub Actions with pytest (75%+ coverage), ruff linting, bandit security audit.
- **CI/CD**: Dependabot for GitHub Actions and pip dependencies.
- **Systemd**: Hardened service unit with sandboxing directives.

### Changed
- GeoIP primary API switched from HTTP (ip-api.com) to HTTPS (ipwho.is).
- Removed `psutil._common.sconn` private type hints (forward-compat with future psutil).
- Config default `geoip_api_url` updated to `https://ipwho.is/`.

### Fixed
- Atomic file writes for data files (tmp + os.rename pattern).
- Widget model updates now use unique key-based reconciliation instead of index-based.

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
