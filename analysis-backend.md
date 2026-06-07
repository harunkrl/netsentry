# KPortWatch — Backend Architecture & Security Review

**Date:** 2026-06-07  
**Scope:** `backend/` directory and all subdirectories (`collectors/`, `parsers/`, `writers/`)  
**Reviewer:** Automated architecture & security audit

---

## Summary

The KPortWatch backend is a Linux network security monitor that parses `/proc/net/*`, runs alert analysis, and publishes JSON snapshots over a Unix domain socket. The codebase is generally well-structured with good separation of concerns. However, several security and architectural issues were identified, ranging from a critical process-killing authorization gap to moderate threading and resource management concerns.

| Severity | Count |
|----------|-------|
| CRITICAL | 2 |
| HIGH | 5 |
| MEDIUM | 9 |
| LOW | 7 |
| INFO | 6 |

---

## 1. Security Issues

### SEC-1: CRITICAL — Kill command lacks authorization/authentication

**File:** `backend/daemon_controller.py`, lines 173–230  
**File:** `backend/writers/unix_socket.py`, line 39

The daemon exposes a `kill` command over a Unix domain socket at `$XDG_RUNTIME_DIR/kportwatch.sock` (mode `0o600`). Any local user process that can reach this socket can request the daemon to kill **any** PID (except 0, 1, 2). There is:

- No capability check (can the requesting user normally signal this process?)
- No uid/policy enforcement
- No audit logging of kill attempts
- The socket permission `0o600` only restricts to the **same user** — but within the same user session, any compromised or malicious process can instruct the daemon to kill arbitrary user processes.

The daemon typically runs with elevated privileges (it reads `/proc/net/tcp` which may require root, and uses `psutil.net_connections()`). A local attacker exploiting a vulnerability in any user-space application could use this socket to kill security tools or other protective processes belonging to the same user.

**Recommendation:** Add authorization checks (compare requesting process UID via `SO_PEERCRED` against target process UID), rate limiting, and audit logging.

---

### SEC-2: CRITICAL — Auto-update performs unsigned code execution

**File:** `backend/update.py`, lines 138–199

`perform_update()` executes `git pull origin main` followed by `pip install -e .`. While GPG tag verification exists, it is explicitly advisory ("does NOT block the update"). This means:

- An MITM or compromised GitHub account could inject malicious code
- `git pull` is performed over HTTPS but without commit signature verification
- `pip install -e .` executes arbitrary code from `setup.py`/`pyproject.toml`
- No hash pinning or reproducible build verification

The function `_restart_daemon()` at line 264 also runs `systemctl --user restart`, which restarts the daemon — causing the newly installed (potentially malicious) code to run with whatever privileges the daemon has.

**Recommendation:** Make GPG tag verification mandatory, add commit signature verification, and require explicit user confirmation before applying updates.

---

### SEC-3: HIGH — Unix socket race condition on startup

**File:** `backend/writers/unix_socket.py`, lines 34–36

```python
if os.path.exists(SOCKET_PATH):
    with contextlib.suppress(OSError):
        os.unlink(SOCKET_PATH)
```

Between the `os.path.exists()` check and the `os.unlink()` call, another process could create a file at `SOCKET_PATH` (TOCTOU race). While the `bind()` call would fail, the unlink of a file that is not the expected socket is a minor concern. The `0o600` mode on the socket is correct (owner-only access) when `XDG_RUNTIME_DIR` is used (which is `0700` by default).

**Recommendation:** Use `os.unlink()` unconditionally (suppress `FileNotFoundError` only) or use `socket.bind()` directly and handle `AddressInUseError`.

---

### SEC-4: HIGH — PID file created with default umask permissions

**File:** `backend/kportwatch_daemon.py`, lines 192–200

```python
pid_fd = open(PID_FILE, "w")
fcntl.flock(pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
pid_fd.write(str(os.getpid()))
```

The PID file is created in `$XDG_RUNTIME_DIR` (typically `/run/user/$UID`, mode `0700`), so this is mitigated by the directory permissions. However, if `XDG_RUNTIME_DIR` is not set, it falls back to `/tmp` (`constants.py` line 16), where the PID file would be world-readable with default umask permissions. This leaks the daemon PID to all local users.

**Recommendation:** Set explicit file mode (`0o600`) on the PID file, or refuse to start when `XDG_RUNTIME_DIR` is unset.

---

### SEC-5: HIGH — `notify-send` subprocess with no input sanitization

**File:** `backend/daemon_controller.py`, lines 446–455

The `notify-send` call passes alert messages directly as command-line arguments. While `subprocess.Popen` is used with a list (not shell=True, avoiding shell injection), extremely long or specially crafted alert messages could still cause issues with `notify-send` argument processing. The alert messages are constructed from port numbers and process names sourced from `/proc`, which could contain unusual characters.

**Recommendation:** Truncate alert messages to a reasonable length (e.g., 200 chars) and strip control characters before passing to `notify-send`.

---

### SEC-6: HIGH — Configurable GeoIP API URL enables SSRF-like attacks

**File:** `backend/parsers/geoip.py`, lines 78–79  
**File:** `backend/daemon_controller.py` (passes `cfg.geoip_api_url` to `geoip_mod.init()`)

The GeoIP API URL is fully configurable via `config.toml` and is used directly in `urllib.request.Request()`. A malicious config file could set this to internal network addresses, enabling the daemon to be used as an SSRF vector:

```python
url = f"{_api_url}{ip}"
req = Request(url, ...)
with urlopen(req, timeout=_timeout) as resp:
```

Since the daemon may run with elevated privileges, this could be used to probe internal services.

**Recommendation:** Validate the API URL scheme (require `https://`) and optionally restrict to known hosts.

---

### SEC-7: MEDIUM — Baseline file loaded without integrity verification

**File:** `backend/alert_engine.py`, lines 102–122

`load_baseline()` reads JSON from disk and accepts it as the baseline port set. A local attacker who can write to `~/.config/kportwatch/baseline.json` could add malicious ports to the baseline, causing the alert engine to silently accept them as "known good." The file is at `~/.config/kportwatch/baseline.json` with default umask permissions (typically `0o644`, world-readable and writable only by owner).

**Recommendation:** Set restrictive permissions (`0o600`) on the baseline file after writing, and consider adding a simple HMAC for integrity.

---

### SEC-8: MEDIUM — `ip_blacklist` uses `fnmatch` for IP matching

**File:** `backend/alert_engine.py`, lines 82–88

IP blacklist patterns are matched using `fnmatch`, which uses glob-style matching. This could lead to unexpected behavior — for example, the pattern `"10.*"` would match `"10.0.0.1"` but the pattern `"10.0.0.*"` would also match `"10.0.0.1.example.com"` if such a string were somehow injected. More importantly, `fnmatch` operates on string representations, not CIDR blocks, making proper IP range matching impossible.

**Recommendation:** Use `ipaddress` module for IP/CIDR matching instead of `fnmatch`.

---

### SEC-9: MEDIUM — History files store data with default permissions

**File:** `backend/history.py`, lines 53–59

History JSONL files are created in `~/.config/kportwatch/history/` with default umask permissions. These files contain information about network connections, alerts, and processes running on the system — potentially sensitive data visible to other users on multi-user systems.

**Recommendation:** Create history directory with `0o700` mode and files with `0o600`.

---

### SEC-10: MEDIUM — `send_command` response size bound is generous

**File:** `backend/writers/unix_socket.py`, line 209

The `send_command()` function has a 10MB response limit:
```python
max_size = 10 * 1024 * 1024  # 10MB safety limit
```

For a command interface that returns simple status dicts, this is excessively large. A malicious or compromised daemon could send up to 10MB of data to a client.

**Recommendation:** Reduce to a more reasonable limit (e.g., 64KB) for command responses.

---

## 2. Architecture Problems

### ARCH-1: MEDIUM — Module-level mutable global state in `parsers/geoip.py` and `parsers/rdns.py`

**Files:** `backend/parsers/geoip.py` (lines 30–46), `backend/parsers/rdns.py` (lines 16–19)

Both modules use extensive module-level mutable state (`_memory_cache`, `_pending_lookups`, `_lock`, `_executor`, etc.). This:
- Makes unit testing difficult (state leaks between tests)
- Prevents multiple independent instances
- Creates hidden coupling (any code importing these modules shares the same state)

**Recommendation:** Refactor into classes with instance state, keeping module-level convenience functions as thin wrappers.

---

### ARCH-2: MEDIUM — Singleton config pattern with global mutation

**File:** `backend/shared/config.py`, line 141

```python
_current_config: AppConfig | None = None
```

The configuration uses a module-level global singleton that is mutated by `load_config()` and `apply_cli_overrides()`. The `DaemonController._handle_sighup()` method calls `load_config()` again, replacing the singleton. This is not thread-safe — if a daemon cycle is reading `self.cfg` while SIGHUP replaces it, partially updated config could be observed.

**Recommendation:** Use a lock or make `AppConfig` immutable after construction, swapping the reference atomically.

---

### ARCH-3: MEDIUM — Duplicate `_write_heartbeat` function

**Files:** `backend/kportwatch_daemon.py` (lines 28–38), `backend/daemon_controller.py` (imported but has its own version)

The `kportwatch_daemon.py` defines `_write_heartbeat()` with JSON format, while `daemon_controller.py` also defines its own `_write_heartbeat()` with plain timestamp format. The daemon loop in `main()` delegates to `DaemonController`, so the version in `kportwatch_daemon.py` is dead code, but the two implementations are inconsistent.

**Recommendation:** Remove the duplicate in `kportwatch_daemon.py` and use the one in `daemon_controller.py` consistently.

---

### ARCH-4: LOW — `DaemonController` has many responsibilities

**File:** `backend/daemon_controller.py`

At ~540 lines, `DaemonController` handles: component initialization, signal handling, socket command processing, process killing, data collection, process tree building, connection enrichment, traffic collection, risk scoring, snapshot building, publishing, notifications, adaptive polling, update checking, and cleanup. While the methods are well-separated, the class is approaching "god object" territory.

**Recommendation:** Consider extracting notification handling and update checking into separate classes.

---

### ARCH-5: LOW — `kportwatch_daemon.py` is mostly a thin wrapper

**File:** `backend/kportwatch_daemon.py`

After the refactor to `DaemonController`, the daemon file primarily contains `main()` with argument parsing, daemonization, PID file management, and `daemon_loop()` which just delegates to `DaemonController`. Functions like `merge_inode_map()`, `classify_entries()`, `compute_traffic_deltas()` are imported by `daemon_controller.py` but also defined here — creating unnecessary coupling.

**Recommendation:** Move utility functions (`classify_entries`, etc.) to a shared module and simplify `kportwatch_daemon.py` to just entry-point logic.

---

## 3. Concurrency & Threading Issues

### CONC-1: HIGH — GeoIP rate limiter uses monotonic time inconsistently

**File:** `backend/parsers/geoip.py`, lines 168–174

```python
with _lock:
    last = _last_request_time
elapsed = time.monotonic() - last
if elapsed < _min_request_interval:
    time.sleep(_min_request_interval - elapsed)
```

The rate-limit check reads `_last_request_time` under the lock but sleeps outside the lock. During the sleep, another thread could also read the same `_last_request_time` and sleep for the same duration, defeating the rate limit. After waking, both threads would proceed with their API requests in rapid succession.

**Recommendation:** Perform the sleep inside the lock (or use a condition variable / semaphore for proper rate limiting).

---

### CONC-2: MEDIUM — `_do_lookup` in rdns.py does cache eviction under lock after exception

**File:** `backend/parsers/rdns.py`, lines 48–65

In `_do_lookup()`, the `except Exception` handler stores an empty string in the cache and does LRU eviction under the lock. The `finally` block also acquires the lock to remove the IP from `_pending_lookups`. While technically correct, the `except` and `finally` blocks both acquire the same lock, creating two separate critical sections where a single one would suffice. This creates a small window where another thread could observe intermediate state.

**Recommendation:** Combine the `except` and `finally` logic into a single `with _lock:` block.

---

### CONC-3: MEDIUM — `UnixSocketServer.broadcast()` removes dead clients from list while iterating

**File:** `backend/writers/unix_socket.py`, lines 114–125

```python
dead_clients = []
with self._clients_lock:
    for client in self.clients:
        try:
            client.sendall(data)
        except OSError:
            dead_clients.append(client)
    for client in dead_clients:
        self.clients.remove(client)
```

While the lock prevents concurrent modification from other methods, the `.remove()` call uses identity comparison on list elements and is O(n). With many broadcast clients, this is quadratic. More importantly, if a client's `sendall` blocks (slow consumer), it blocks the entire broadcast under the lock, preventing new clients from being added.

**Recommendation:** Use `select`/`poll` for non-blocking sends, or use a write queue per client with separate send threads.

---

### CONC-4: LOW — Thread pool executors never fully shut down

**Files:** `backend/parsers/geoip.py` (line 33), `backend/parsers/rdns.py` (line 22)

Both modules call `_executor.shutdown(wait=False)` in their `shutdown()` functions. This means pending tasks are abandoned without waiting for completion. During daemon shutdown, this could leave in-flight DNS/GeoIP lookups in an indeterminate state — the thread pool threads are daemon threads, so they'll be killed when the process exits, but any shared state mutations they were performing may be incomplete.

**Recommendation:** Use `shutdown(wait=True)` with a timeout, or cancel pending futures before shutdown.

---

## 4. Resource Management

### RES-1: MEDIUM — `notified_alerts` dict grows unbounded before eviction

**File:** `backend/daemon_controller.py`, lines 462–469

```python
if len(self.notified_alerts) > 500:
    now_ts = time.time()
    expired = [k for k, v in self.notified_alerts.items() if (now_ts - v) > self.cfg.alert_ttl]
    for k in expired:
        del self.notified_alerts[k]
```

Eviction only triggers when the dict exceeds 500 entries. If `alert_ttl` is very long (or if many unique alerts fire within the TTL period), the dict could grow significantly between evictions. The eviction itself is O(n) and happens inside the main loop.

**Recommendation:** Use an LRU cache (e.g., `functools.lru_cache` or `OrderedDict`) with a fixed size limit.

---

### RES-2: MEDIUM — `HistoryRecorder` file handle held open indefinitely

**File:** `backend/history.py`, line 49

The `_fh` file handle is opened once per day and held open until `close()` is called. If the daemon runs for days without restart, the file handle persists. The `_append()` method silently swallows `OSError`:

```python
except OSError:
    pass  # history is best-effort
```

If the filesystem becomes full or the file is deleted externally, the handle becomes invalid and all subsequent writes silently fail.

**Recommendation:** Reopen the file handle periodically (e.g., every N writes) and validate it's still usable.

---

### RES-3: LOW — PID file descriptor held open for lock but never explicitly closed

**File:** `backend/kportwatch_daemon.py`, lines 192–199

```python
pid_fd = open(PID_FILE, "w")
fcntl.flock(pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
```

The PID file descriptor is held open for the advisory lock but is never stored in a named variable accessible to the cleanup path. `DaemonController._cleanup()` unlinks the PID file but doesn't close the file descriptor, relying on process exit to release the flock. This is a minor issue since the process is shutting down anyway, but it means the lock is held until the Python garbage collector collects the file object.

**Recommendation:** Store `pid_fd` as a module-level or instance variable and close it explicitly in cleanup.

---

### RES-4: LOW — File descriptor limit in daemonization

**File:** `backend/kportwatch_daemon.py`, line 176

```python
for fd in range(3, min(max_fd, 256)):  # Cap at 256 to avoid slowness
```

The `_daemonize()` function caps FD closure at 256 to "avoid slowness." If the process has open file descriptors above 256 before daemonizing, they will leak into the daemon. This is a tradeoff between speed and correctness.

**Recommendation:** Use `/proc/self/fd/` to enumerate only actually-open file descriptors instead of iterating the full range.

---

## 5. Error Handling

### ERR-1: MEDIUM — Broad `except Exception` in main daemon loop catches and continues

**File:** `backend/daemon_controller.py`, lines 574–576

```python
except Exception:
    logger.exception("Error in daemon cycle")
    self.interval = self.cfg.poll_interval
```

While logging the exception is good, catching all `Exception` subclasses in the main loop means programming errors (e.g., `TypeError`, `AttributeError`) are silently swallowed and the daemon continues running in a potentially inconsistent state. If `self.cfg` is somehow `None` (due to a failed `_init_components`), accessing `self.cfg.poll_interval` in the except handler would raise another exception.

**Recommendation:** Be more specific about which exceptions to catch, or add a maximum error count before shutting down.

---

### ERR-2: MEDIUM — `_handle_command` error details leaked to client

**File:** `backend/writers/unix_socket.py`, lines 100–104

```python
except Exception as e:
    logger.error("Command handler error: %s", e)
    response = {"status": "error", "message": str(e)}
```

Exception messages from the command handler are sent directly to the client over the socket. These messages could contain internal implementation details, file paths, or stack trace fragments that aid an attacker.

**Recommendation:** Return generic error messages to the client and log detailed errors server-side only.

---

### ERR-3: LOW — `collect_traffic()` in `psutil_collector.py` catches bare `Exception`

**File:** `backend/collectors/psutil_collector.py`, lines 147–149

```python
except Exception:
    return []
```

This catches all exceptions including `KeyboardInterrupt` (actually no — `KeyboardInterrupt` is `BaseException`, not `Exception`). Still, it silently swallows any psutil error, returning an empty list. If psutil consistently fails, traffic monitoring would silently stop working with no indication.

**Recommendation:** Log the exception and catch only psutil-specific exceptions.

---

### ERR-4: LOW — `_cleanup()` suppresses exceptions from rdns/geoip shutdown

**File:** `backend/daemon_controller.py`, lines 524–528

```python
try:
    from backend.parsers import rdns as _rdns_mod
    _rdns_mod.shutdown()
    geoip_mod.shutdown()
except Exception:
    pass
```

If `rdns.shutdown()` raises, `geoip_mod.shutdown()` is never called, potentially leaving the geoip thread pool running.

**Recommendation:** Wrap each shutdown call in its own try/except.

---

## 6. Code Quality

### QUAL-1: LOW — Magic number 256 for max pending DNS lookups

**File:** `backend/parsers/rdns.py`, line 17

```python
_MAX_PENDING = 256
```

While configurable via `configure()`, the default is a magic number. This should reference a constant from the shared config module.

---

### QUAL-2: LOW — Magic number 500 for alert eviction threshold

**File:** `backend/daemon_controller.py`, line 462

```python
if len(self.notified_alerts) > 500:
```

This eviction threshold is not configurable and not documented.

---

### QUAL-3: LOW — `ipwho.is` fallback API uses HTTP, not HTTPS

**File:** `backend/parsers/geoip.py`, line 80

```python
_fallback_url: str = "http://ip-api.com/json/"
```

The fallback GeoIP API uses plain HTTP. IP lookups sent to this endpoint are visible to network observers. The primary API (`ipwho.is`) correctly uses HTTPS.

**Recommendation:** ip-api.com does not offer HTTPS on the free tier — document this limitation or use a different fallback.

---

### QUAL-4: LOW — `_proto_label` defaults unknown types to "tcp"

**File:** `backend/collectors/psutil_collector.py`, line 51

```python
base = _PROTO_MAP.get(conn.type, "tcp")  # default tcp for unknown
```

Unknown socket types silently default to "tcp" instead of being logged or marked as "unknown."

---

### QUAL-5: INFO — Dead code in `kportwatch_daemon.py`

**File:** `backend/kportwatch_daemon.py`, lines 59–106

The functions `merge_inode_map()`, `classify_entries()`, and `compute_traffic_deltas()` are defined in `kportwatch_daemon.py` but `daemon_loop()` immediately delegates to `DaemonController`. `classify_entries()` IS imported and used by `daemon_controller.py`, but `merge_inode_map()` and `compute_traffic_deltas()` appear to be dead code.

---

### QUAL-6: INFO — Consistent use of dataclasses and type hints

Throughout the backend, dataclasses with type hints are used consistently (`models.py`, `config.py`). This is good practice and makes the codebase more maintainable.

---

### QUAL-7: INFO — Atomic file writes used correctly

`shared/fs_utils.py` provides `atomic_write()` which uses tmpfile + `os.replace()`. This is used consistently for snapshot writes, baseline files, and GeoIP cache. This is a good pattern that prevents partial/corrupt reads.

---

### QUAL-8: INFO — Good defense-in-depth for /proc parsing

`parsers/proc_net.py` validates line format, skips malformed lines, and handles all error cases gracefully. IP address parsing uses `ipaddress` stdlib for correctness.

---

## 7. Positive Observations

1. **No `eval()`/`exec()`/`pickle`/`yaml.load` usage** — the codebase avoids all dangerous deserialization.
2. **All subprocess calls use list form, not `shell=True`** — no shell injection vectors.
3. **Atomic file writes** are used consistently for data persistence.
4. **Good input validation** in `/proc` parsers — malformed lines are skipped.
5. **Protected PIDs** (0, 1, 2) cannot be killed via the socket command.
6. **Signal handling** is clean — SIGHUP for config reload, SIGTERM/SIGINT for shutdown.
7. **Clean data model** — dataclasses with proper serialization/deserialization.
8. **Good logging** — appropriate log levels and structured error reporting.

---

## 8. Prioritized Remediation Plan

| Priority | Finding | Effort |
|----------|---------|--------|
| P0 | SEC-1: Add authorization to kill command | Medium |
| P0 | SEC-2: Make GPG verification mandatory in auto-update | Small |
| P1 | SEC-4: PID file permissions when XDG_RUNTIME_DIR is unset | Small |
| P1 | SEC-6: Validate GeoIP API URL | Small |
| P1 | CONC-1: Fix GeoIP rate limiter thread safety | Medium |
| P1 | ERR-2: Don't leak exception details to socket clients | Small |
| P2 | SEC-3: Fix socket TOCTOU race | Small |
| P2 | SEC-7: Set restrictive baseline file permissions | Small |
| P2 | SEC-9: Restrict history file permissions | Small |
| P2 | RES-2: Periodically reopen history file handle | Medium |
| P2 | ERR-1: Limit broad exception catching in main loop | Small |
| P3 | ARCH-1: Refactor module-level state to classes | Large |
| P3 | ARCH-2: Thread-safe config singleton | Medium |
| P3 | CONC-3: Non-blocking broadcast | Medium |

---

*End of review.*
