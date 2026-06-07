# Test Coverage & CI/CD Review — KPortWatch

**Date:** 2026-06-07  
**Reviewer:** Automated review subagent  
**Scope:** `tests/`, `.github/`, `conftest.py`, `pyproject.toml`  

---

## Executive Summary

The test suite contains **474 passing tests** across 22 test modules, which is a solid foundation. However, **overall coverage is 41.1%** — well below the configured 75% threshold. The TUI screens, CLI entry points, and several backend orchestration modules have near-zero coverage. The CI pipeline has quality gates but uses `|| true` on security scans, effectively making them advisory-only. No type checking, no QML tests, no TUI integration tests exist.

---

## 1. Test Coverage Gaps

### 1.1 Backend Module Coverage Map

| Module | Covered | Coverage | Notes |
|--------|---------|----------|-------|
| `backend/models.py` | ✅ | 100% | Excellent — `test_models.py` |
| `backend/alert_engine.py` | ✅ | ~95%+ | Excellent — `test_alert_engine.py` (62 tests) |
| `backend/risk_score.py` | ✅ | 100% | Excellent — `test_risk_score.py` |
| `backend/writers/json_file.py` | ✅ | 100% | Excellent — `test_json_file.py` |
| `backend/parsers/proc_net.py` | ✅ | 97% | Excellent — `test_proc_net.py` |
| `backend/parsers/geoip.py` | ✅ | 94% | Good — `test_geoip.py` |
| `backend/parsers/rdns.py` | ✅ | 89% | Good — `test_rdns.py` |
| `backend/parsers/net_dev.py` | ✅ | 87% | Good — `test_net_dev.py` |
| `backend/parsers/process_tree.py` | ✅ | 86% | Good — `test_process_tree.py` |
| `backend/writers/unix_socket.py` | ✅ | 86% | Good — `test_unix_socket.py` |
| `shared/constants.py` | ✅ | 100% | Trivial |
| `shared/network.py` | ✅ | 100% | Tested indirectly via `test_geoip.py` and `test_tui_utils.py` |
| `shared/fs_utils.py` | ✅ | 83% | Tested via `test_tui_utils.py` and `test_inode_map.py` |
| `shared/config.py` | ✅ | 82% | Good — `test_config.py` (55+ tests) |
| `backend/collectors/psutil_collector.py` | ⚠️ | N/A | `test_psutil_collector.py` tests real host, not mocked |
| `tui/data/provider.py` | ⚠️ | 82% | `test_provider.py` covers fetch/kill |
| `backend/kportwatch_daemon.py` | ⚠️ | Partial | `test_daemon.py` covers helpers only |
| `backend/parsers/inode_map.py` | ⚠️ | 52% | `test_inode_map.py` — single test function |
| `backend/history.py` | ⚠️ | ~70%+ | `test_history.py` — covers recorder and export |
| `backend/update.py` | ❌ | 42% | `test_update.py` tests parsing/mocking, but CLI `main()` untested |
| `backend/export.py` | ❌ | 0% | No dedicated test file — CLI entry point only |
| `backend/kportwatch_client.py` | ❌ | 0% | No test file — socket streaming client |
| `backend/kportwatchctl.py` | ❌ | 0% | No test file — CLI control tool |
| `backend/daemon_controller.py` | ❌ | 0% | No test file — main daemon orchestration class |

### 1.2 TUI Module Coverage

| Module | Coverage | Notes |
|--------|----------|-------|
| `tui/kportwatch_tui.py` | **0%** | App entry point — no test |
| `tui/screens/main_screen.py` | **0%** | Main screen with 432 lines — no test |
| `tui/screens/detail_screen.py` | **0%** | Detail screen — no test |
| `tui/screens/help_screen.py` | **0%** | Help screen — no test |
| `tui/screens/kill_confirm.py` | **0%** | Kill confirmation — no test |
| `tui/screens/process_tree_screen.py` | **0%** | Process tree screen — no test |
| `tui/screens/connection_map_screen.py` | **0%** | Connection map — no test |
| `tui/screens/settings_screen.py` | **23%** | Only constructor/constants tested |
| `tui/widgets/connection_log.py` | **41%** | Only config/severity tested |
| `tui/widgets/port_table.py` | **47%** | Only styling/filter tested |
| `tui/widgets/traffic_bar.py` | **48%** | Only helpers tested |
| `tui/widgets/status_bar.py` | **35%** | Only state setters tested |
| `tui/themes.py` | **62%** | Theme mapping tested |
| `tui/utils/clipboard.py` | **25%** | Only import tested |
| `tui/utils/provider.py` | **0%** | TUI event provider — no test |

### 1.3 Widget (QML) Coverage

**Severity: LOW**  
The `widget/` directory contains KDE Plasma plasmoid files (`metadata.json`, QML, config). There are no QML tests. The CI does run `qmllint` for syntax checking, which is a reasonable minimum. Full QML testing would require a KDE runtime environment.

### 1.4 Integration Tests

**Severity: HIGH** — see finding F-H01 below.

---

## 2. Findings

### F-C01: Coverage threshold is never enforced (CRITICAL)
**Files:** `.github/workflows/ci.yml:26`, `pyproject.toml:62`  
The CI runs `--cov-fail-under=75` but actual coverage is **41.1%**. The CI is currently **failing** on coverage grounds (verified: `FAIL Required test coverage of 75.0% not reached. Total coverage: 41.10%`). Either:
- The threshold should be lowered to a realistic value (e.g., 45%), or
- Coverage needs to be improved significantly.

The CI pipeline will block all PRs until this is resolved.

### F-C02: No tests for `DaemonController` — the core orchestration class (CRITICAL)
**File:** `backend/daemon_controller.py` (0% coverage)  
This 400+ line class is the heart of the daemon — it orchestrates collection, alert analysis, enrichment, snapshot building, publishing, notifications, adaptive polling, and update checks. None of this logic is tested. Key untested paths:
- `_init_components()` — config loading + alert engine setup
- `_collect_entries()` — psutil vs /proc fallback
- `_enrich_connections()` — rDNS + GeoIP integration
- `_build_snapshot()` — snapshot assembly
- `_publish()` — write + broadcast
- `_handle_notifications()` — rate limiting + dedup
- `_adaptive_interval()` — idle/alert/normal switching
- `_handle_socket_command()` — kill process via socket
- `_handle_sighup()` — config reload
- `_cleanup()` — graceful shutdown

### F-H01: TUI screens have 0% test coverage (HIGH)
**Files:** `tui/screens/*.py`  
All 6 Textual screens (main, detail, help, kill_confirm, process_tree, connection_map) have **0% coverage**. The `test_tui_widgets.py` file tests widget helper methods in isolation but never mounts a Textual `App` or `Screen`. The manual test scripts (`manual_tree_cursor.py`, `manual_tree_rebuild.py`) are interactive debugging tools, not automated tests.

Textual provides `app.run_headless()` and `pytest-asyncio` for testing screens. No such tests exist.

### F-H02: CLI entry points untested (HIGH)
**Files:** `backend/export.py`, `backend/kportwatch_client.py`, `backend/kportwatchctl.py`  
- `kportwatch-export` (`backend/export.py`): 0% coverage, no test file
- `kportwatch-client` (`backend/kportwatch_client.py`): 0% coverage, no test file  
- `kportwatchctl` (`backend/kportwatchctl.py`): 0% coverage, no test file (265 lines of subprocess management, signal handling, PID management)

These are user-facing commands that should have at least argument parsing and error-handling tests.

### F-H03: `test_psutil_collector.py` tests live system state, not mocked (HIGH)
**File:** `tests/test_psutil_collector.py`  
All tests call the actual `psutil` API against the host system. While this provides integration value, it means:
- Tests are **environment-dependent** — they skip in minimal CI environments
- Results are **non-deterministic** — different hosts return different data
- Edge cases (no interfaces, permission errors, no connections) are untested

Recommendation: Add a parallel set of mocked tests for deterministic edge case coverage.

### F-H04: Security scans have `|| true` — failures silently ignored (HIGH)
**File:** `.github/workflows/ci.yml:49-53`  
```yaml
- name: Security scan (bandit)
  run: |
    pip install bandit
    bandit -r backend shared -ll -ii || true

- name: Dependency audit
  run: |
    pip install pip-audit
    pip-audit || true
```
Both Bandit and pip-audit will never fail the CI build. The `-ll -ii` flags already limit Bandit to medium/high severity, and yet failures are suppressed. These should either:
- Remove `|| true` and treat findings as blockers, or
- Document this as an intentional advisory-only gate

### F-M01: No type checking in CI (MEDIUM)
**File:** `.github/workflows/ci.yml`  
The CI runs ruff lint + format checks but has **no type checker** (mypy, ty, pyright). The codebase uses type annotations extensively (`from __future__ import annotations`, type hints on dataclasses), so a type checker would catch real bugs. Not listed in `[project.optional-dependencies] dev` either.

### F-M02: `test_inode_map.py` is a single flat function — low coverage (MEDIUM)
**File:** `tests/test_inode_map.py`  
The entire file is one test function (`testread_file_safe` + `test_build_inode_to_pid_map`) testing only the happy path. Missing tests:
- Permission errors on `/proc/[pid]/fd`
- Processes disappearing mid-scan (race condition)
- Large number of processes (performance)
- Edge case: process with thousands of FDs

### F-M03: No test for `backend/update.py` main() CLI entry point (MEDIUM)
**File:** `tests/test_update.py`  
Tests cover `parse_version`, `check_for_update`, `get_latest_version`, and state file I/O. But the `main()` CLI function (lines 226–326) which handles argument parsing and interactive mode is untested.

### F-M04: Release pipeline lacks matrix testing (MEDIUM)
**File:** `.github/workflows/release.yml`  
The release workflow only tests on Python 3.12, while the CI tests 3.11, 3.12, and 3.13. A release should be tested across all supported versions. The release also doesn't run lint or security checks.

### F-M05: CI has no pip/dependency caching (MEDIUM)
**File:** `.github/workflows/ci.yml`  
Every CI run reinstalls all dependencies from scratch. Adding `pip` cache via `actions/cache` or `setup-python` cache option would reduce CI time significantly:
```yaml
- uses: actions/setup-python@v5
  with:
    python-version: ${{ matrix.python-version }}
    cache: pip
```

### F-M06: No OS matrix testing (MEDIUM)
**File:** `.github/workflows/ci.yml`  
CI only runs on `ubuntu-latest`. The project reads from `/proc/net/*`, which is Linux-specific, so this is acceptable. However, the `kportwatchctl.py` tool uses `pgrep` and `systemctl --user` which may behave differently across distributions. No distro matrix (Ubuntu, Fedora, Arch) is tested.

### F-M07: Coverage reporting not uploaded to Codecov/Coveralls (MEDIUM)
**File:** `.github/workflows/ci.yml`  
Coverage is only reported as terminal output. No `coverage.xml` artifact is generated or uploaded to a coverage service. This makes it hard to track coverage trends over time.

### F-M08: `test_daemon_lifecycle.py` is not a true daemon integration test (MEDIUM)
**File:** `tests/test_daemon_lifecycle.py`  
Despite the name, this test mocks `subprocess.run` to simulate systemctl. It never actually starts or stops the KPortWatch daemon. The tests verify the mock's behavior, not the actual daemon lifecycle. While this avoids needing systemd in CI, it means daemon startup/shutdown logic is untested.

### F-L01: Manual test scripts in `tests/` directory (LOW)
**Files:** `tests/manual_tree_cursor.py`, `tests/manual_tree_rebuild.py`  
These are interactive debugging scripts (using `app.run(headless=True)` + manual exit) that aren't proper pytest tests. They pollute the test directory and aren't collected by pytest (no `test_` prefix on classes/functions), but they could confuse contributors.

### F-L02: No property-based testing (LOW)
The test suite is entirely example-based. Modules like `alert_engine.py`, `risk_score.py`, and `proc_net.py` would benefit from property-based testing (e.g., Hypothesis) to verify invariants like:
- Alert level is always one of {CRITICAL, WARNING, INFO}
- Risk score is always in [0, 100]
- Parsed port is always in [0, 65535]
- Round-trip serialization invariants

### F-L03: No performance/regression tests (LOW)
No tests measure execution time or memory usage. The GeoIP cache LRU eviction, connection log bounded memory (`max_lines=5000`), and rdns cache have edge cases around memory that could be verified with performance tests.

### F-L04: `pytest-asyncio` is a dependency but no async tests exist (LOW)
**File:** `pyproject.toml:39`  
`pytest-asyncio` is installed but no test file uses `async def test_*` or `@pytest.mark.asyncio`. The TUI is async (Textual) but tests only test synchronous helper methods.

### F-I01: Dependabot configured for both pip and GitHub Actions (INFO)
**File:** `.github/dependabot.yml`  
Good practice — weekly updates for both ecosystems with reasonable PR limits.

### F-I02: Conftest fixtures are well-structured (INFO)
**File:** `tests/conftest.py`  
Fixtures provide realistic, reusable test data (socket entries, snapshots, process trees, proc/net content strings). The use of `autouse=True` for singleton reset in `test_config.py` is a good pattern.

### F-I03: Test quality is generally high (INFO)
Tests follow a clear pattern:
- Organized into `TestXxx` classes by feature/rule
- Helper factories (`_make_entry`, `_seed_cache`) reduce duplication
- Good edge case coverage for parsers (malformed input, empty files, corrupt JSON)
- Proper use of `pytest.MonkeyPatch.context()` for time mocking
- Thread safety test for rdns cache (`TestThreadSafety`)

---

## 3. Coverage Statistics

```
Overall: 41.10% (2678 of 4547 lines uncovered)

Well-covered (>85%):
  - backend/models.py          100%
  - backend/risk_score.py      100%
  - backend/writers/json_file  100%
  - shared/constants.py        100%
  - shared/network.py          100%
  - backend/parsers/proc_net   97%
  - backend/parsers/geoip      94%
  - backend/alert_engine       ~95%+

Poorly covered (<50%):
  - backend/update.py           42%
  - backend/parsers/inode_map   52%
  - tui/widgets/status_bar      35%
  - tui/screens/settings        23%
  - tui/utils/clipboard         25%
  - tui/utils/provider           0%
  - tui/kportwatch_tui           0%
  - tui/screens/*                0% (all 6 screens)
  - backend/daemon_controller    0%
  - backend/export.py            0%
  - backend/kportwatch_client    0%
  - backend/kportwatchctl        0%
```

---

## 4. CI/CD Pipeline Summary

| Gate | Present | Enforced | Notes |
|------|---------|----------|-------|
| Lint (ruff check) | ✅ | ✅ | Ignores E501 |
| Format (ruff format) | ✅ | ✅ | Good |
| Tests (pytest) | ✅ | ✅ | 474 tests, all pass |
| Coverage (75%) | ✅ | ❌ | Fails at 41% — blocks CI |
| Security (bandit) | ✅ | ❌ | `|| true` suppresses |
| Dependency audit (pip-audit) | ✅ | ❌ | `|| true` suppresses |
| QML lint (qmllint) | ✅ | ❌ | `|| true` suppresses |
| Type checking | ❌ | N/A | Not configured |
| Matrix (Python versions) | ✅ | ✅ | 3.11, 3.12, 3.13 |
| Matrix (OS) | ❌ | N/A | Ubuntu only (acceptable) |
| Caching | ❌ | N/A | No pip caching |
| Build verification | ✅ | ✅ | Builds wheel + verifies imports |
| Release pipeline | ✅ | ✅ | Tag-triggered, builds wheel, GitHub Release |
| Coverage upload | ❌ | N/A | No Codecov/Coveralls |

---

## 5. Recommendations (Priority Order)

1. **[CRITICAL]** Fix the coverage threshold — either lower it to ~45% or add tests for `DaemonController`, CLI entry points, and at least the main TUI screen to reach 75%.

2. **[CRITICAL]** Add tests for `DaemonController` — this is the most important untested module. Mock the collection phases and test orchestration logic.

3. **[HIGH]** Add Textual headless tests for `MainScreen` — mount the app, verify widget composition, test user interactions (filter, kill, navigation).

4. **[HIGH]** Add tests for `kportwatchctl.py` commands — mock subprocess/os.kill and test status/stop/restart/reload/kill logic.

5. **[HIGH]** Remove `|| true` from security scans or add a separate non-blocking advisory job.

6. **[MEDIUM]** Add `mypy` or `ty` to dev dependencies and CI pipeline.

7. **[MEDIUM]** Enable pip caching in CI to reduce build times.

8. **[MEDIUM]** Add `coverage.xml` generation and upload to Codecov.

9. **[LOW]** Move manual test scripts from `tests/` to `contrib/` or `scripts/`.

10. **[LOW]** Consider Hypothesis for property-based testing of parsers and scoring.
