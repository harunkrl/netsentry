# Cross-Cutting Concerns & Infrastructure Review — KPortWatch

**Date:** 2026-06-07  
**Reviewer:** Automated cross-cutting analysis  
**Scope:** install.sh, uninstall.sh, systemd/, polkit/, widget/, shared/, contrib/, pyproject.toml, .gitignore, README.md, CHANGELOG.md, LICENSE, CI workflows

---

## Summary

The project is well-structured with clear separation of concerns. Shell scripts use proper error handling, the systemd service has meaningful sandboxing, the QML widget implements a sophisticated reconciliation pattern, and the shared module provides a clean API. Below are findings grouped by category with severity ratings.

---

## 1. Installation Scripts

### 1.1 install.sh

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **MEDIUM** | Version fallback is stale | `install.sh:10` | `KPW_VERSION` falls back to `"2.1.0"` if `pyproject.toml` parsing fails. While currently correct, this is a maintenance trap — the hardcoded fallback will silently serve the wrong version after the next release. Consider removing the fallback or adding a warning. |
| **LOW** | No trap-based cleanup on failure | `install.sh` (global) | Uses `set -euo pipefail` which is excellent, but lacks a `trap cleanup EXIT` to undo partial installations. If step 6 (systemd) fails, steps 1–5 (venv, widget copy, symlinks) are left in place. For a user-facing installer this is acceptable since re-running is safe (idempotent), but partial failures can leave an inconsistent state. |
| **INFO** | Idempotency is generally good | `install.sh` (global) | `cp -r` overwrites, `ln -sf` forces, `systemctl enable --now` is idempotent. The venv creation is gated by `[ ! -d .venv ]`. Well done. |
| **INFO** | Privilege escalation is graceful | `install.sh:100–113` | Polkit install correctly tries write access first, falls back to `sudo`, then prints manual instructions. No forced `sudo`. |
| **LOW** | kpackagetool6 stderr swallowed | `install.sh:82–84` | Both `--install` and `--upgrade` failures are silently consumed by `\|\| true`. If registration fails for a reason other than "already installed", the user gets a false "✅ Registered" message. |
| **INFO** | Good dependency checks | `install.sh:17–26` | Checks for `python3` existence and version ≥ 3.11 before proceeding. |

### 1.2 uninstall.sh

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **HIGH** | Missing `set -u` and `set -o pipefail` | `uninstall.sh:5` | Uses only `set -e`, missing `-u` (undefined variable protection) and `-o pipefail`. If a refactoring introduces an undefined variable, the script will silently proceed with empty values. `install.sh` correctly uses all three. |
| **MEDIUM** | Unquoted `$REPLY` in conditional | `uninstall.sh:36,38` | `$REPLY` from `read` is used in `[[ $REPLY =~ ^[Yy]$ ]]` without quotes. While `[[ ]]` is safe in bash (doesn't word-split), this is inconsistent with the script's quoting elsewhere and would fail under `set -u` if `read` somehow produced empty output. Same issue at line 80. |
| **LOW** | Indentation inconsistency | `uninstall.sh:80–86` | The Plasma restart section has inconsistent indentation (if-else block is at the same level as the outer `echo`). Cosmetic only. |
| **INFO** | Preserves source and venv | `uninstall.sh:93–94` | Correctly notes that the repo folder and `.venv` are intentionally not deleted. |

---

## 2. Systemd Service

**File:** `systemd/kportwatch.service`

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **MEDIUM** | `NoNewPrivileges=true` conflicts with `CapabilityBoundingSet` | `kportwatch.service:39,46` | `NoNewPrivileges=true` prevents the service from gaining new privileges, but `CapabilityBoundingSet=CAP_NET_ADMIN CAP_SYS_PTRACE` is set. The daemon runs as an unprivileged user and parses `/proc/net/` (world-readable), so it doesn't actually need these capabilities. The bounding set is misleading — the capabilities are never available to an unprivileged user process. These should either be removed or a comment added explaining the intent. |
| **MEDIUM** | No `WatchdogSec` configured | `kportwatch.service` (global) | No watchdog integration. If the daemon enters a deadlock or infinite loop, systemd won't detect or restart it. Adding `WatchdogSec=60` with `sd_notify` in the daemon would provide self-healing. |
| **LOW** | No resource limits | `kportwatch.service` (global) | Missing `MemoryMax`, `MemoryHigh`, `CPUQuota`, `LimitNOFILE`, `TasksMax`. While the daemon is lightweight, explicit limits prevent resource leaks from affecting the system. |
| **LOW** | `ProtectHome=read-only` may be overly broad | `kportwatch.service:36` | Makes all of `~` read-only except the explicit `ReadWritePaths`. This is good security practice but means any new file paths added to the daemon (e.g., new cache locations) must be explicitly listed here. |
| **INFO** | Security hardening is otherwise thorough | `kportwatch.service:35–47` | `ProtectSystem=strict`, `PrivateTmp=true`, `RestrictNamespaces=true`, `RestrictRealtime=true`, `SystemCallFilter=@system-service` are all present. Solid sandboxing. |
| **INFO** | `Restart=on-failure` with `RestartSec=5` | `kportwatch.service:33–34` | Appropriate restart policy for a monitoring daemon. |

---

## 3. Polkit Configuration

**File:** `polkit/com.kportwatch.helper.policy`

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **MEDIUM** | Action ID is `getports` but description covers kill too | `policy:10` | The action ID is `com.kportwatch.helper.getports` but the description says "Manage network socket information **and process termination**". The ID should better reflect the broader scope, or separate actions should be defined for read vs. kill operations (different auth levels). |
| **LOW** | `allow_gui=true` enabled | `policy:23` | `org.freedesktop.policykit.exec.allow_gui` is set to true. This allows the helper to display GUI dialogs. If the helper is purely CLI, this is unnecessary and slightly expands the attack surface. |
| **LOW** | Single action for both read and kill | `policy` (global) | A single polkit action covers both port reading and process termination. Best practice would separate these: read operations at `auth_self` and kill operations at `auth_admin`. |
| **INFO** | `auth_admin_keep` for active sessions | `policy:17` | Uses `auth_admin_keep` for active sessions, so authentication is cached. Reasonable for a desktop tool. |

---

## 4. Widget (QML/JS)

### 4.1 main.qml

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **HIGH** | `tuiCommand` injected into shell without sanitization | `main.qml:26,196–198` | The `launchTUI()` function passes `root.tuiCommand` directly to `tuiExecSource.connectedSources` which runs via the `executable` engine (shell). This value comes from `plasmoid.configuration.tuiCommand`, which is user-editable in the settings dialog (`ConfigGeneral.qml:18`). While this is a "configure your own command" feature, there is no validation that the command is safe. A malicious or malformed value could execute arbitrary shell commands. Compare with `killProcess()` which properly sanitizes PID input. |
| **LOW** | `safePortsSet` recalculated on every property change | `main.qml:16–23` | `safePortsSet` is a bound property that creates a new object and parses the comma-separated string on every evaluation. Since this triggers on every poll cycle (via property dependency chain), it creates unnecessary garbage. A `WorkerScript` or caching approach would be more efficient. In practice, the string rarely changes so impact is minimal. |
| **LOW** | `reconcileModel` is O(n²) worst case | `main.qml:173–203` | The reconciliation step 3 rebuilds `keyToIdx` on every move (`for (var m = 0; m < model.count; m++)`). For large connection lists this could be slow. In practice, connections rarely reorder between polls, so this is unlikely to matter. |
| **INFO** | Shell injection in `sendDesktopNotification` is properly mitigated | `main.qml:105–108` | Title and body are sanitized by stripping shell metacharacters and truncating length. Good defensive practice. |
| **INFO** | `killProcess` properly validates PID | `main.qml:218–220` | Strips non-numeric characters and validates positive integer before shell execution. |
| **INFO** | Sophisticated model reconciliation | `main.qml:155–203` | Three-step reconciliation (update-in-place, remove stale, reorder) is well-implemented and avoids the common QML bug of stale indices. |
| **INFO** | Desktop notification deduplication | `main.qml:145–165` | Alert hash comparison and per-port+level tracking prevents notification spam. Well designed. |

### 4.2 FullRepresentation.qml

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **LOW** | `formatDuration` called on every render | `FullRepresentation.qml:235` | `formatDuration(entry.first_seen)` is called inline in the delegate. Since `Date.now()` changes every second, this could cause unnecessary re-evaluation. However, since QML delegates only re-render when model data changes (not on timer ticks), this is acceptable. |
| **INFO** | Clean separation of listening/established delegates | `FullRepresentation.qml:133–230` | Two separate `RowLayout` blocks with `visible` toggling is the correct QML pattern for tab-dependent layouts. |

### 4.3 CompactRepresentation.qml

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **INFO** | Simple and well-structured | `CompactRepresentation.qml` (global) | Clean badge+icon layout with middle-click to launch TUI. No issues found. |

### 4.4 ConfigGeneral.qml

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **INFO** | Proper `cfg_` alias pattern | `ConfigGeneral.qml:9–19` | Uses Plasma's standard `cfg_` property aliases for bidirectional config binding. Correct implementation. |

---

## 5. Shared Module

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **LOW** | `__init__.py` uses wildcard import with `noqa: F403` | `shared/__init__.py:7` | `from shared.constants import *` with suppressed F403. The explicit re-exports on lines 9–41 mitigate the risk for type-checkers, but the wildcard import could pull in unexpected names if constants.py grows. Consider switching to explicit imports only. |
| **LOW** | Version defined in three places | `shared/constants.py:96`, `pyproject.toml:16`, `widget/metadata.json:17` | `APP_VERSION = "2.1.0"` in constants.py, `version = "2.1.0"` in pyproject.toml, and `"Version": "2.1.0"` in metadata.json. No single source of truth. A bump requires updating all three files manually. |
| **INFO** | Clean API surface | `shared/` (global) | The module exposes: constants (paths, defaults, enums), config loader (TOML + CLI override + save), filesystem utilities (atomic write, safe read), and network utility (is_private_ip). Well-scoped and documented. |
| **INFO** | `atomic_write` uses correct pattern | `shared/fs_utils.py:28–44` | `mkstemp` → write → `chmod` → `os.replace` with cleanup on failure. Proper crash safety. |
| **INFO** | Config save is thread-safe with `fcntl` locking | `shared/config.py:219–265` | `save_config_setting` uses `fcntl.LOCK_EX` to prevent concurrent write corruption. Good for multi-process scenarios (daemon + TUI). |

---

## 6. Documentation

### 6.1 README.md

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **MEDIUM** | Widget metadata has wrong GitHub URL | `widget/metadata.json:18` | `"Website": "https://github.com/kportwatch"` should be `"https://github.com/harunkrl/kportwatch"`. The current URL leads to a non-existent repository. The README and polkit policy correctly use `harunkrl/kportwatch`. |
| **LOW** | Duplicate "Project Structure" section | `README.md` (two locations) | The README contains two project structure sections — one under "📁 Project Structure" (line ~95) and another identical one later (line ~165). One should be removed. |
| **LOW** | Widget settings table references `knownSafePorts` | `README.md` config table | The table mentions `knownSafePorts` as a widget setting, but the actual config key in `main.xml:13` is `safePorts`. |
| **LOW** | `daemonEnabled` setting listed but not in config | `README.md` Widget Settings table | `daemonEnabled` is documented as a widget setting but doesn't exist in `widget/contents/config/main.xml`. The actual keys are: `pollInterval`, `showPortCount`, `alertThreshold`, `tuiCommand`, `popupWidth`, `popupHeight`, `iconSize`, `badgeSize`, `fontScale`, `safePorts`. |
| **INFO** | Comprehensive feature documentation | `README.md` (global) | Architecture diagram, keyboard shortcuts, config examples, security model, and limitations are all well-documented. |

### 6.2 CHANGELOG.md

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **LOW** | No `[Unreleased]` section | `CHANGELOG.md` (global) | Follows Keep a Changelog format but lacks an `[Unreleased]` section for tracking pending changes. |
| **INFO** | Well-structured entries | `CHANGELOG.md` (global) | Properly categorized into Added/Changed/Fixed with bullet points. Good detail level. |

### 6.3 LICENSE

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **LOW** | Copyright year may be stale | `LICENSE:3` | States `Copyright (c) 2024` but the changelog shows releases in 2026. Consider updating to `2024–2026` or using a range. |

### 6.4 Missing Documentation

| Severity | Finding | Details |
|----------|---------|---------|
| **LOW** | No architecture decision records (ADRs) | The README lists architecture decisions in a table, but there are no standalone ADR documents. For a project of this complexity, ADRs would help future contributors understand the "why" behind decisions. |
| **INFO** | CONTRIBUTING.md is explicitly excluded | `.gitignore` contains `CONTRIBUTING.md` with comment "Unnecessary docs for personal project". Acceptable for a personal project. |

---

## 7. Project Configuration

### 7.1 pyproject.toml

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **LOW** | No upper bounds on dependencies | `pyproject.toml:35–38` | `textual>=1.0`, `rich>=13.0`, `psutil>=5.9` have no upper bounds. While this avoids dependency hell, major version bumps of textual/rich could break the TUI. Consider at least `textual>=1.0,<3.0` or similar ranges. |
| **INFO** | Complete build configuration | `pyproject.toml` (global) | Proper setuptools config, entry points, pytest config with coverage thresholds (75%), ruff config with appropriate rule selection. |
| **INFO** | Dev dependencies are optional | `pyproject.toml:40–45` | `dev` extra correctly separates test/lint tools from runtime dependencies. |

### 7.2 .gitignore

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **INFO** | Covers analysis output files | `.gitignore:34–37` | `review-*.md`, `progress.md`, `kportwatch-review-*.md` are excluded. The output of this analysis (`analysis-crosscutting.md`) is **not** covered by `.gitignore`. You may want to add `analysis-*.md` to the ignore list. |
| **INFO** | Comprehensive coverage | `.gitignore` (global) | Covers Python artifacts, IDE files, OS files, runtime data, and dev-only artifacts. |

### 7.3 Missing Configuration Files

| Severity | Finding | Details |
|----------|---------|---------|
| **LOW** | No `.editorconfig` | Missing `.editorconfig` for consistent coding style across editors. The project uses ruff for formatting, but `.editorconfig` would handle non-Python files (shell, QML, TOML, XML). |

### 7.4 Version Management

| Severity | Finding | Details |
|----------|---------|---------|
| **MEDIUM** | Version triple-maintenance burden | Version `"2.1.0"` must be kept in sync across: `pyproject.toml:16`, `shared/constants.py:96`, and `widget/metadata.json:17`. No automated sync mechanism (e.g., `bump-my-version` or `setuptools_scm`). Risk of version drift between components. |

---

## 8. Dependencies

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **LOW** | No pinned dependency hashes | `pyproject.toml:35–38` | Runtime dependencies use open ranges (`>=`). For a desktop app this is acceptable, but a `requirements.lock` or `pip-tools` setup would improve reproducibility. |
| **INFO** | Minimal runtime dependencies | `pyproject.toml:35–38` | Only 3 runtime deps: `textual`, `rich`, `psutil`. The daemon core uses only stdlib (`/proc` parsing). Well-chosen dependency footprint. |
| **INFO** | Optional dependencies documented | `pyproject.toml:40–45` | Dev dependencies (`pytest`, `pytest-asyncio`, `pytest-cov`, `ruff`) are in the `[dev]` extra. |
| **INFO** | CI uses Dependabot | `.github/dependabot.yml` | Weekly checks for both pip and GitHub Actions dependencies. |

---

## 9. CI/CD

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **LOW** | Security scans allowed to fail | `.github/workflows/ci.yml:46,52` | Both `bandit` and `pip-audit` use `\|\| true`, so they never fail the build. This defeats the purpose of security scanning. Consider at least logging findings or using `--exit-zero` with a separate check for high-severity issues. |
| **LOW** | QML lint allowed to fail | `.github/workflows/ci.yml:56` | `qmllint` uses `\|\| true`. Understandable since qmllint may flag Plasma-specific imports, but should be tracked. |
| **INFO** | Multi-version Python testing | `.github/workflows/ci.yml:14` | Tests against 3.11, 3.12, and 3.13. Good forward-compatibility. |
| **INFO** | Release workflow is tag-triggered | `.github/workflows/release.yml` | Builds wheel + sdist, creates GitHub Release. Clean process. |

---

## 10. Contrib

| Severity | Finding | Location | Details |
|----------|---------|----------|---------|
| **MEDIUM** | Config example has stale GeoIP API references | `contrib/kportwatch-config-example.toml:71–72` | Comments reference `ip-api.com endpoint (free tier: 45 req/min)` and `api_url = "http://ip-api.com/json/"`, but the actual default in `shared/config.py` is `https://ipwho.is/`. The CHANGELOG 2.1.0 notes the switch but the example wasn't updated. Same stale comment exists in `shared/config.py:generate_example_config()` at the embedded template. |
| **INFO** | Example config is comprehensive | `contrib/kportwatch-config-example.toml` | Well-commented with all sections and example custom rules. |

---

## Consolidated Finding Count

| Severity | Count |
|----------|-------|
| CRITICAL | 0 |
| HIGH | 2 |
| MEDIUM | 6 |
| LOW | 19 |
| INFO | 28 |

---

## Prioritized Action Items

### HIGH (Should fix before next release)

1. **uninstall.sh: Add `set -u -o pipefail`** — Align with install.sh's safety flags. Single-line change.
2. **main.qml: Sanitize `tuiCommand` before shell execution** — Add input validation in `launchTUI()` or restrict to known-safe command patterns.

### MEDIUM (Should fix soon)

3. **Version management: Single source of truth** — Use a version extraction script or `bump-my-version` to sync across pyproject.toml, constants.py, and metadata.json.
4. **metadata.json: Fix GitHub URL** — Change `"Website": "https://github.com/kportwatch"` to `"https://github.com/harunkrl/kportwatch"`.
5. **Config example: Update GeoIP API references** — Replace ip-api.com references with ipwho.is in contrib example and `generate_example_config()`.
6. **systemd service: Review CapabilityBoundingSet** — Remove `CAP_NET_ADMIN CAP_SYS_PTRACE` since the daemon runs unprivileged and doesn't need them, or add a comment explaining the intent.
7. **systemd service: Add `WatchdogSec`** — Even a basic `WatchdogSec=120` without `sd_notify` would catch hard locks.
8. **Polkit: Separate read/kill actions** — Split into two actions with different auth levels for least-privilege.

### LOW (Nice to have)

9. Add `.editorconfig` for shell/QML/TOML consistency.
10. Remove duplicate "Project Structure" section from README.
11. Fix README widget settings table (`knownSafePorts` → `safePorts`, remove non-existent `daemonEnabled`).
12. Update LICENSE copyright year to `2024–2026`.
13. Add resource limits to systemd service (`MemoryMax=256M`).
14. Make CI security scans fail on HIGH findings.
15. Add `[Unreleased]` section to CHANGELOG.

---

*End of cross-cutting review.*
