# NetSentry Backend Code Review

**Reviewer**: Automated review subagent  
**Date**: 2026-05-30  
**Scope**: Backend modules — `shared/`, `backend/`  
**Method**: Source inspection + live `/proc` validation on Arch Linux  

---

## Summary

| File | Rating | Verdict |
|------|:------:|---------|
| `shared/__init__.py` | **7/10** | Functional; minor quality issues |
| `backend/models.py` | **8/10** | Clean data models; `sys.path` hack |
| `backend/parsers/proc_net.py` | **9/10** | Correct parsing; one missing TCP state |
| `backend/parsers/inode_map.py` | **8/10** | Sound logic; could cache process info |
| `backend/alert_engine.py` | **5/10** | **Critical baseline contamination bug** — Rules 2, 3, 5 are dead code |
| `backend/writers/json_file.py` | **9/10** | Correct atomic write; clean error handling |
| `backend/netsentry-daemon.py` | **7/10** | Functional daemon; unnecessary baseline saves; missing `backend/__init__.py` |

---

## Correctness Findings

### 🔴 BLOCKER: Baseline contamination in `alert_engine.py` (Rules 2, 3, 5 are dead code)

**File**: `backend/alert_engine.py`, method `analyze()`, line ~108

**Root cause**: `analyze()` calls `update_baseline()` which unconditionally executes `self._baseline_ports.update(current_ports)` (line ~75). This adds ALL current ports to the baseline set *before* the per-entry rule evaluation loop runs. By the time Rule 2 and Rule 3 check `is_baseline`, every port in the current cycle is already in the baseline set, so these rules **never fire**.

**Evidence** (live test):
```python
engine = AlertEngine()
engine._baseline_stable = True
engine._baseline_ports = {22, 80}  # baseline only has 22, 80

# 5 new ports not in baseline
entries = [SocketEntry(..., local_port=9001), ..., SocketEntry(..., local_port=9005)]
alerts = engine.analyze(entries)
# Result: 0 alerts — expected at least 5 INFO (Rule 3) + 1 WARNING burst (Rule 5)
```

**Impact**: 
- Rule 2 (unknown privileged port) → never triggers
- Rule 3 (new listening port) → never triggers  
- Rule 5 (burst detection) → never triggers
- Only Rule 1 (malicious port) and Rule 4 (no cmdline) work correctly

**Fix**: After baseline is stable, do NOT accumulate new ports into `_baseline_ports`. The accumulation should only happen during the learning phase:

```python
def update_baseline(self, entries: List[SocketEntry]) -> None:
    """Learn listening ports during the baseline period (first N seconds)."""
    now = time.time()
    current_ports = {e.local_port for e in entries}

    if self._baseline_start is None:
        self._baseline_start = now

    # Only accumulate during the baseline learning window
    if not self._baseline_stable:
        self._baseline_ports.update(current_ports)

    elapsed = now - self._baseline_start
    if elapsed >= self.baseline_duration:
        if current_ports == self._last_ports:
            self._baseline_stable = True
        self._last_ports = current_ports
```

---

### 🟡 NOTE: Missing TCP state `0C` (NEW_SYN_RECV) in `shared/__init__.py`

**File**: `shared/__init__.py`, `TCP_STATES` dict (line ~67)

**Details**: The Linux kernel defines TCP state `0C` = `NEW_SYN_RECV` (since kernel 4.4, used for TCP SYN cookies). If a socket is in this state, the parser returns `UNKNOWN(0C)` instead of the proper name. Unlikely to appear in normal `/proc/net/tcp` output (only during SYN flood conditions), but incomplete.

**Fix**: Add the missing state:
```python
TCP_STATES: dict[str, str] = {
    ...
    "0B": "CLOSING",
    "0C": "NEW_SYN_RECV",  # SYN cookie reply (kernel ≥ 4.4)
}
```

---

### 🟡 NOTE: Duplicate port key in `KNOWN_SAFE_PORTS`

**File**: `shared/__init__.py`, lines ~52–63

**Details**: Port `631` ("cups") appears twice in the `KNOWN_SAFE_PORTS` dict literal. Python silently discards the first occurrence. Functionally harmless (same value), but indicates copy-paste oversight.

**Fix**: Remove the duplicate entry:
```python
KNOWN_SAFE_PORTS: dict[int, str] = {
    22:    "sshd",
    80:    "httpd",
    443:   "https",
    631:   "cups",        # keep only one
    5353:  "avahi",
    1716:  "kdeconnectd",
    ...
}
```

---

### 🟢 Correct: IPv4 hex parsing

**File**: `backend/parsers/proc_net.py`, `_parse_hex_ip()`

**Verified against live `/proc` data**:
| Hex string | Parsed | Expected | Status |
|-----------|--------|----------|--------|
| `0100007F` | `127.0.0.1` | `127.0.0.1` | ✓ |
| `00000000` | `0.0.0.0` | `0.0.0.0` | ✓ |
| `FFFFFFFF` | `255.255.255.255` | `255.255.255.255` | ✓ |
| `0101A8C0` | `192.168.1.1` | `192.168.1.1` | ✓ |
| `3301A8C0` | `192.168.1.51` | `192.168.1.51` | ✓ |

The byte-reversal (`b[::-1]`) correctly handles little-endian storage.

### 🟢 Correct: IPv6 hex parsing

**Verified**:
| Hex string | Parsed | Expected | Status |
|-----------|--------|----------|--------|
| `00000000...0000` (32 zeros) | `::` | `::` | ✓ |
| `00000000000000000000000001000000` | `::1` | `::1` | ✓ |
| `0000000000000000FFFF00000100007F` | `::ffff:127.0.0.1` | `::ffff:127.0.0.1` | ✓ |

The per-32-bit-word byte swap correctly handles the kernel's storage format.

### 🟢 Correct: TCP state decoding

All 11 standard TCP states in `TCP_STATES` map correctly. Live data confirmed: `0A`→`LISTEN`, `01`→`ESTABLISHED`, `06`→`TIME_WAIT`.

### 🟢 Correct: UDP state handling

`_decode_state()` correctly maps `07`→`UNCONN` and `01`→`ESTABLISHED` for UDP protocols. Live data confirmed 8 UDP sockets all showing `UNCONN`.

### 🟢 Correct: Inode-to-PID mapping

**Verified**: 681–688 mappings found on the live system. All mapped PIDs verified to still exist in `/proc`. Exception handling for `PermissionError`, `FileNotFoundError`, and `OSError` all tested and working.

### 🟢 Correct: JSON roundtrip serialization

`Snapshot` → `to_json()` → `from_json()` produces structurally identical objects. All fields preserved including nested `SocketEntry` and `Alert` objects.

---

## Security Findings

### 🟢 No injection vectors

All data comes from `/proc` (read-only kernel filesystem). No user input is accepted anywhere in the backend. The JSON writer writes to a hardcoded path (`/tmp/netsentry-data.json`). No shell commands are executed.

### 🟢 Atomic file writes are correct

Both `write_snapshot()` and `save_baseline()` use the `tmp + os.replace()` pattern, which is atomic on Linux when source and destination are on the same filesystem. The `.tmp` file is cleaned up on write failure.

**Minor note**: No file permission is explicitly set. The JSON output files use the process's umask (typically `0644`). Since the data is written to `/tmp`, other local users could read it. The data contains no secrets (only port/PID info), so this is low risk.

### 🟢 No race conditions

Single-threaded daemon with no concurrent writers. The `os.replace()` call is atomic. Signal handler only sets a boolean flag (`running = False`).

### 🟢 Daemonization correctly redirects stdio

The double-fork pattern in `main()` properly closes `stdin` and redirects `stdout`/`stderr` to `/dev/null`.

---

## Error Handling Findings

### 🟢 `FileNotFoundError` handled everywhere

- `parse_proc_net()`: returns empty list ✓
- `build_inode_to_pid_map()`: returns empty dict ✓
- `read_snapshot()`: returns `None` ✓
- `load_baseline()`: returns `False` ✓

### 🟢 `PermissionError` handled

- `/proc/[pid]/fd/` scanning: `try/except (PermissionError, ...)` on `os.listdir()` and `os.readlink()` ✓
- `_read_file_safe()`: catches `PermissionError` ✓
- `write_snapshot()`: `OSError` cleanup verified ✓

### 🟢 `ProcessLookupError` implicitly handled

Zombie processes: if a PID disappears between `os.listdir("/proc")` and reading its files, the file reads fail with `FileNotFoundError` which is caught. No `ProcessLookupError` is raised by the file-based approach.

### 🟢 Malformed `/proc` lines handled

Lines with fewer than 10 fields are skipped (`if len(parts) < 10`). Hex parsing errors caught by `try/except (ValueError, IndexError)`.

---

## Performance Findings

### 🟢 Inode mapper performance is adequate

**Measured**: ~45ms per call (681 inodes) on this system. At a 2-second poll interval, this is ~2.25% CPU utilization. Not a bottleneck.

### 🟢 No O(n²) patterns

The inode map is a dict (`O(1)` lookup per entry). Alert rules iterate entries once (`O(n)`). Classification is a single pass (`O(n)`).

### 🟡 NOTE: Baseline saved on every cycle

**File**: `backend/netsentry-daemon.py`, line ~143

The daemon calls `alert_engine.save_baseline()` on every cycle when baseline is complete. This writes a JSON file to `~/.config/netsentry/baseline.json` every 2 seconds even when nothing changed.

**Impact**: Unnecessary disk I/O. On SSDs this is negligible, but on spinning disks or eMMC it adds wear.

**Fix**: Track whether baseline has changed:
```python
# In daemon_loop(), before the cycle:
baseline_dirty = False

# After analyze():
if alert_engine.is_baseline_complete() and alert_engine._baseline_ports != prev_baseline:
    alert_engine.save_baseline()
    prev_baseline = set(alert_engine._baseline_ports)
```

### 🟢 No memory leaks

Each cycle creates new lists and dicts, and the old ones are garbage-collected. The `_baseline_ports` set grows only during the learning phase (bounded by total unique ports). The inode map is rebuilt fresh each cycle.

---

## Edge Case Findings

### 🟢 Empty `/proc` files

Tested: returns 0 entries without error.

### 🟢 IPv6 addresses

Tested against real `/proc/net/tcp6` data — parsed correctly.

### 🟢 UDP states

UDP `07` correctly mapped to `UNCONN`. All other UDP states mapped to `UNKNOWN(xx)`.

### 🟢 Zombie processes

If a PID disappears mid-scan, all file operations fail with caught exceptions. No crash.

### 🟢 High port counts

The parser processes each line independently. No scaling concerns.

### 🟢 inode=0 entries filtered

Socket entries with `inode == 0` (no real socket) are correctly skipped in `parse_proc_net()`.

### 🟡 NOTE: `classify_entries` lumps non-LISTEN/non-UNCONN into "established"

**File**: `backend/netsentry-daemon.py`, `classify_entries()`

All sockets not in `LISTEN` or `UNCONN` state go into the `established` list. This includes `TIME_WAIT`, `CLOSE_WAIT`, `FIN_WAIT1`, `FIN_WAIT2`, `SYN_SENT`, etc. These are not truly "established" connections. This is a semantic issue, not a bug — the field name `established` is misleading.

**Suggestion**: Rename to `active` or `other`, or add a `state` filter.

---

## Python Quality Findings

### 🟡 NOTE: Repeated `sys.path` manipulation in every module

**Files**: `models.py`, `proc_net.py`, `inode_map.py`, `alert_engine.py`, `json_file.py`

Each module independently inserts the project root into `sys.path` at import time:
```python
sys.path.insert(0, os.path.join(os.path.dirname(__file__), "..", ".."))
```

This is fragile and duplicated 5 times. A proper solution would be a `pyproject.toml` with `[project]` metadata and `pip install -e .`, or a single entry point that sets up the path once.

### 🟡 NOTE: Missing `backend/__init__.py`

The `backend/` directory has no `__init__.py`, while `backend/parsers/` and `backend/writers/` do. Python namespace packages make imports work, but this is inconsistent. Adding an empty `backend/__init__.py` would make it a regular package and prevent future import issues.

### 🟢 Type hints present

All public functions have type hints. `dataclass` fields are typed. `Optional` used correctly for nullable fields.

### 🟢 Docstrings present

All modules, classes, and public functions have docstrings.

### 🟢 Import organization

Imports are grouped logically: stdlib → third-party → local. In some files the `sys.path` manipulation sits between import groups, but this is a necessary consequence of the current approach.

### 🟡 NOTE: Hyphenated daemon filename

`netsentry-daemon.py` cannot be imported as a regular Python module (hyphens are invalid in identifiers). This is acceptable for a script entry point, but if any code needs to import from it (e.g., for unit testing), it would require `importlib`. The `classify_entries` and `merge_inode_map` helper functions should arguably live in a separate importable module.

---

## Detailed File Ratings

### `shared/__init__.py` — 7/10

**Strengths**: Clean constants, `StrEnum` for alert levels, `frozenset` for malicious ports, comprehensive known-safe ports list.

**Issues**: Duplicate key `631` in `KNOWN_SAFE_PORTS`, missing TCP state `0C`.

### `backend/models.py` — 8/10

**Strengths**: Clean dataclass design, proper `from_dict`/`to_dict` serialization with field filtering, `from_json`/`to_json` convenience methods.

**Issues**: `sys.path` hack at module level (line ~13), `sys` and `os` imported on same line as other stdlib modules.

### `backend/parsers/proc_net.py` — 9/10

**Strengths**: Correct hex parsing for both IPv4 and IPv6, proper error handling for malformed lines, clean separation of concerns, well-documented.

**Issues**: None significant. The fallback `return hex_str` in `_parse_hex_ip` for unexpected lengths is a minor concern (silent failure for corrupt data).

### `backend/parsers/inode_map.py` — 8/10

**Strengths**: Defensive error handling at every I/O point, correct socket link parsing, handles missing `/proc` entries gracefully.

**Issues**: No caching — rebuilds the entire map on every call. For a 2-second poll interval this is acceptable (45ms), but a incremental update could improve performance on systems with many processes.

### `backend/alert_engine.py` — 5/10

**Strengths**: Well-structured alert rules, baseline learning with persistence, proper save/load with atomic writes.

**Issues**: **Critical baseline contamination bug** (Rules 2, 3, 5 never fire). See BLOCKER above.

### `backend/writers/json_file.py` — 9/10

**Strengths**: Clean atomic write implementation, proper cleanup on failure, `read_snapshot` returns `None` gracefully.

**Issues**: None significant. Minimal and focused module.

### `backend/netsentry-daemon.py` — 7/10

**Strengths**: Standard double-fork daemonization, adaptive sleep with interruptible polling, clean signal handling, proper logging.

**Issues**: Saves baseline every cycle unnecessarily, no `backend/__init__.py`, hyphenated filename prevents normal import, broad `except Exception` catches programming errors silently.

---

## Recommended Fixes (Priority Order)

1. **🔴 Fix baseline contamination** in `alert_engine.py` — guard `update_baseline()` accumulation with `not self._baseline_stable` check. This is the only blocker.

2. **🟡 Add missing TCP state** `0C: "NEW_SYN_RECV"` to `shared/__init__.py`.

3. **🟡 Remove duplicate** port `631` from `KNOWN_SAFE_PORTS`.

4. **🟡 Add** `backend/__init__.py` (empty file) for package consistency.

5. **🟡 Optimize** baseline saves — only write when changed.

6. **🟡 Rename** `established` list to `active` or document that it contains all non-listening sockets.
