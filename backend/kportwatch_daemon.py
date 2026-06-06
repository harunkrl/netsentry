#!/usr/bin/env python3
"""KPortWatch — Main backend daemon.

Gathers network socket data from /proc, runs alert analysis,
and writes JSON snapshots for the Plasma widget and TUI.

Usage:
    python3 kportwatch-daemon.py --foreground --verbose
    python3 kportwatch-daemon.py --interval 5
"""
from __future__ import annotations

import argparse
import fcntl
import logging
import os
import signal
import sys
import time
from dataclasses import asdict

from shared import (
    DEFAULT_POLL_INTERVAL,
    PID_FILE,
    AlertLevel,
)
from shared.config import apply_cli_overrides, load_config

from backend.models import InterfaceStats, Snapshot, SocketEntry
from backend.parsers.inode_map import build_inode_to_pid_map, build_uid_process_map
from backend.parsers.net_dev import parse_proc_net_dev
from backend.parsers.proc_net import parse_all_proc
from backend.parsers.process_tree import build_process_tree

# psutil-based collectors (preferred, with /proc fallback)
try:
    import psutil as _psutil  # noqa: F401 — checked at runtime
    _HAS_PSUTIL = True
except ImportError:
    _HAS_PSUTIL = False

import contextlib
import subprocess

from backend.alert_engine import AlertEngine
from backend.collectors.psutil_collector import (
    collect_connections as _psutil_connections,
)
from backend.collectors.psutil_collector import (
    collect_network_pids as _psutil_network_pids,
)
from backend.collectors.psutil_collector import (
    collect_process_tree as _psutil_process_tree,
)
from backend.collectors.psutil_collector import (
    collect_traffic as _psutil_traffic,
)
from backend.history import HistoryRecorder
from backend.parsers import geoip as geoip_mod
from backend.parsers.rdns import get_hostname
from backend.risk_score import calculate_risk_score
from backend.update import check_for_update, get_local_version, write_update_state
from backend.writers.json_file import write_snapshot, write_widget_snapshot
from backend.writers.unix_socket import UnixSocketServer

logger = logging.getLogger("kportwatch")


def _write_heartbeat(path: str) -> None:
    """Write a tiny JSON file with current timestamp for health checks."""
    try:
        import json as _json
        data = _json.dumps({"ts": time.time()}).encode()
        tmp = path + ".tmp"
        with open(tmp, "wb") as fh:
            fh.write(data)
        os.replace(tmp, path)
    except OSError:
        pass  # heartbeat is best-effort


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(
        description="KPortWatch backend daemon — network security monitor",
    )
    parser.add_argument(
        "--interval", "-i",
        type=float,
        default=DEFAULT_POLL_INTERVAL,
        help=f"Poll interval in seconds (default: {DEFAULT_POLL_INTERVAL})",
    )
    parser.add_argument(
        "--verbose", "-v",
        action="store_true",
        help="Enable verbose (DEBUG) logging",
    )
    parser.add_argument(
        "--foreground", "-f",
        action="store_true",
        help="Run in foreground (don't daemonize)",
    )
    parser.add_argument(
        "--config", "-c",
        type=str,
        default=None,
        help="Path to config file (default: ~/.config/kportwatch/config.toml)",
    )
    return parser.parse_args()


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def merge_inode_map(entries: list[SocketEntry]) -> None:
    """Resolve PIDs for socket entries by scanning /proc fd symlinks."""
    inode_map = build_inode_to_pid_map()
    uid_map = build_uid_process_map()
    for entry in entries:
        info = inode_map.get(entry.inode)
        if info:
            pid, proc_name, cmdline = info
            entry.pid = pid
            entry.process_name = proc_name
            entry.cmdline = cmdline
        elif entry.uid in uid_map:
            username, proc_name, cmdline = uid_map[entry.uid]
            entry.process_name = f"{proc_name} ({username})"
            entry.cmdline = cmdline


def classify_entries(
    entries: list[SocketEntry],
) -> tuple[list[SocketEntry], list[SocketEntry]]:
    """Split entries into listening and established lists.

    Listening: state is LISTEN or UNCONN (UDP listening).
    Everything else goes to established.
    """
    listening: list[SocketEntry] = []
    established: list[SocketEntry] = []
    for e in entries:
        if e.state in ("LISTEN", "UNCONN"):
            listening.append(e)
        else:
            established.append(e)
    return listening, established


def compute_traffic_deltas(
    current: list[InterfaceStats],
    prev: dict[str, tuple[float, InterfaceStats]],
    now: float,
) -> dict[str, InterfaceStats]:
    """Compute per-second RX/TX rates from cumulative counters.

    Args:
        current: Freshly parsed interface stats.
        prev: Previous cycle's {iface: (timestamp, InterfaceStats)}.
        now: Current timestamp.

    Returns:
        Dict of {iface: InterfaceStats} with rx_rate/tx_rate filled.
    """
    result: dict[str, InterfaceStats] = {}
    for stats in current:
        if stats.interface in prev:
            prev_ts, prev_stats = prev[stats.interface]
            elapsed = now - prev_ts
            if elapsed > 0:
                stats.rx_rate = max(0, (stats.rx_bytes - prev_stats.rx_bytes) / elapsed)
                stats.tx_rate = max(0, (stats.tx_bytes - prev_stats.tx_bytes) / elapsed)
        result[stats.interface] = stats
    return result


def daemon_loop(args: argparse.Namespace) -> None:
    """Main daemon loop."""
    # Load config and apply CLI overrides
    cfg = load_config()
    cfg = apply_cli_overrides(cfg, args)

    # Propagate DNS cache limits to rdns module
    from backend.parsers import rdns
    rdns._MAX_CACHE_SIZE = cfg.dns_cache_size
    rdns._MAX_PENDING = cfg.dns_max_pending

    # Initialise GeoIP module
    if cfg.geoip_enabled:
        geoip_mod.init({
            "geoip_api_url": cfg.geoip_api_url,
            "geoip_cache_file": cfg.geoip_cache_file,
            "geoip_cache_max_entries": cfg.geoip_cache_max_entries,
            "geoip_cache_ttl_days": cfg.geoip_cache_ttl_days,
            "geoip_batch_size": cfg.geoip_batch_size,
            "geoip_timeout": cfg.geoip_timeout,
        })

    alert_engine = AlertEngine(
        known_safe_ports=cfg.known_safe_ports,
        baseline_duration=cfg.baseline_duration,
        malicious_ports=set(cfg.malicious_ports),
        burst_threshold=cfg.burst_threshold,
        privileged_port_max=cfg.privileged_port_max,
        custom_rules=cfg.custom_rules,
        port_whitelist=set(cfg.port_whitelist),
        port_blacklist=set(cfg.port_blacklist),
        ip_blacklist=list(cfg.ip_blacklist),
    )

    # Try loading a previously saved baseline
    if alert_engine.load_baseline(cfg.baseline_file):
        logger.info("Loaded saved baseline from %s", cfg.baseline_file)
    else:
        logger.info("No saved baseline — will learn for %.0f seconds",
                     alert_engine.baseline_duration)

    # SIGHUP handler: reload config + reset baseline
    def reload_config(signum, frame):
        nonlocal cfg
        logger.info("Received SIGHUP, reloading configuration and resetting baseline...")
        cfg = load_config(cfg.config_path)
        cfg = apply_cli_overrides(cfg, args)
        alert_engine.reset_baseline()
        logger.info(
            "Configuration reloaded — notifications_enabled=%s, poll_interval=%.1fs",
            cfg.notifications_enabled, cfg.poll_interval,
        )

    with contextlib.suppress(AttributeError):  # Windows compatibility
        signal.signal(signal.SIGHUP, reload_config)

    running = True
    last_snapshot_hash: str = ""
    last_change_time = time.time()
    prev_baseline: frozenset = frozenset()
    notified_alerts: dict[str, float] = {}  # alert_hash → timestamp
    notification_timestamps: list[float] = []  # for rate limiting
    _prev_traffic: dict[str, tuple[float, InterfaceStats]] = {}  # iface → (ts, stats)
    _last_update_check: float = 0.0

    # Start Unix Socket Server
    socket_server = UnixSocketServer()

    # ── Socket command handler ──────────────────────────────────
    def handle_socket_command(cmd: dict) -> dict:
        """Handle commands sent over the Unix socket (e.g. kill)."""
        command = cmd.get("command", "")

        if command == "kill":
            pid_raw = cmd.get("pid")
            if pid_raw is None:
                return {"status": "error", "message": "Missing 'pid' field"}
            try:
                pid = int(pid_raw)
            except (ValueError, TypeError):
                return {"status": "error", "message": f"Invalid pid: {pid_raw}"}
            if pid <= 0:
                return {"status": "error", "message": f"Invalid pid: {pid}"}
            return daemon_kill_process(pid)

        return {"status": "error", "message": f"Unknown command: {command}"}

    def daemon_kill_process(pid: int) -> dict:
        """Kill a process by PID with SIGTERM → wait → SIGKILL fallback."""
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return {"status": "ok", "message": f"Process {pid} not found (already gone)"}
        except PermissionError:
            return {"status": "error", "message": f"Permission denied killing PID {pid}"}
        except OSError as e:
            return {"status": "error", "message": f"Error sending SIGTERM to {pid}: {e}"}

        # Wait up to 2 seconds for graceful exit
        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                os.kill(pid, 0)  # Check if process still exists
                time.sleep(0.1)
            except ProcessLookupError:
                logger.info("Process %d terminated gracefully after SIGTERM", pid)
                return {"status": "ok", "message": f"Process {pid} terminated (SIGTERM)"}
            except PermissionError:
                # Process exists but we can't signal — might have changed user
                break

        # Process still alive — escalate to SIGKILL
        try:
            os.kill(pid, signal.SIGKILL)
            logger.info("Process %d killed with SIGKILL after timeout", pid)
            return {"status": "ok", "message": f"Process {pid} killed (SIGKILL)"}
        except ProcessLookupError:
            return {"status": "ok", "message": f"Process {pid} terminated between checks"}
        except PermissionError:
            return {"status": "error", "message": f"Permission denied sending SIGKILL to PID {pid}"}
        except OSError as e:
            return {"status": "error", "message": f"Error sending SIGKILL to {pid}: {e}"}

    socket_server.set_command_handler(handle_socket_command)
    socket_server.start()

    # Start history recorder
    history = HistoryRecorder(retention_days=cfg.history_retention_days)

    def handle_signal(signum: int, _frame) -> None:
        nonlocal running
        logger.info("Received signal %s — shutting down", signum)
        running = False

    signal.signal(signal.SIGTERM, handle_signal)
    signal.signal(signal.SIGINT, handle_signal)

    interval = args.interval

    while running:
        cycle_start = time.time()

        try:
            # 1. Collect network connections (psutil preferred, /proc fallback)
            if _HAS_PSUTIL:
                entries = _psutil_connections()
                logger.debug("Collected %d socket entries via psutil", len(entries))
            else:
                entries = parse_all_proc()
                logger.debug("Parsed %d socket entries via /proc", len(entries))

            # 1b. Resolve PIDs (only needed for /proc path — psutil already has them)
            if not _HAS_PSUTIL or any(e.pid is None for e in entries):
                inode_map = build_inode_to_pid_map()
                uid_map = build_uid_process_map()
                for entry in entries:
                    if entry.pid is None:
                        info = inode_map.get(entry.inode)
                        if info:
                            pid, proc_name, cmdline = info
                            entry.pid = pid
                            entry.process_name = proc_name
                            entry.cmdline = cmdline
                        elif entry.uid in uid_map:
                            username, proc_name, cmdline = uid_map[entry.uid]
                            entry.process_name = f"{proc_name} ({username})"
                            entry.cmdline = cmdline

            # 2. Build process tree
            if _HAS_PSUTIL:
                network_pids = _psutil_network_pids()
                process_tree = _psutil_process_tree(network_pids)
            else:
                inode_map_local = build_inode_to_pid_map()
                process_tree = build_process_tree(inode_map_local)

            # 3. Classify listening vs established
            listening, established = classify_entries(entries)

            # 3.5 GeoIP / rDNS lookup for remote IPs
            for e in established:
                # ignore local IPs
                if e.remote_ip and not e.remote_ip.startswith(("127.", "::1", "0.0.0.0", "::")):
                    e.remote_hostname = get_hostname(e.remote_ip)

            # 3.5b GeoIP lookup for remote IPs
            if cfg.geoip_enabled:
                unique_ips = set()
                for e in established:
                    if (e.remote_ip
                            and not e.remote_ip.startswith(("127.", "::1", "0.0.0.0", "::"))):
                        unique_ips.add(e.remote_ip)
                if unique_ips:
                    geo_results = geoip_mod.lookup_batch(list(unique_ips))
                    for e in established:
                        geo = geo_results.get(e.remote_ip)
                        if geo:
                            e.remote_country = geo.get("country")
                            e.remote_country_code = geo.get("countryCode")
                            e.remote_city = geo.get("city")
                            e.remote_lat = geo.get("lat")
                            e.remote_lon = geo.get("lon")
                            e.remote_isp = geo.get("isp")
                            e.remote_org = geo.get("org")

            # 3.6 Collect traffic statistics
            now_ts = time.time()
            raw_traffic = _psutil_traffic() if _HAS_PSUTIL else parse_proc_net_dev()
            traffic = compute_traffic_deltas(raw_traffic, _prev_traffic, now_ts)
            # Store current readings for next cycle's delta computation
            _prev_traffic = {
                name: (now_ts, InterfaceStats(
                    interface=stats.interface,
                    rx_bytes=stats.rx_bytes,
                    tx_bytes=stats.tx_bytes,
                    rx_packets=stats.rx_packets,
                    tx_packets=stats.tx_packets,
                    rx_errors=stats.rx_errors,
                    tx_errors=stats.tx_errors,
                    rx_drops=stats.rx_drops,
                    tx_drops=stats.tx_drops,
                ))
                for name, stats in traffic.items()
            }

            # 4. Run alert analysis on listening sockets
            alerts = alert_engine.analyze(listening)

            # 5. Save baseline if it just completed or changed
            if alert_engine.is_baseline_complete():
                current_baseline = frozenset(alert_engine._baseline_ports)
                if current_baseline != prev_baseline:
                    alert_engine.save_baseline()
                    prev_baseline = current_baseline

            # 6. Build snapshot
            risk_scores = {
                e.local_port: calculate_risk_score(
                    e,
                    malicious_ports=alert_engine.malicious_ports,
                    known_safe_ports=alert_engine.known_safe,
                    baseline_ports=alert_engine._baseline_ports if alert_engine.is_baseline_complete() else None,
                    port_blacklist=alert_engine.port_blacklist,
                )
                for e in listening
            }

            # 6b. Compute geo_stats from established connections
            country_ips: dict[str, set] = {}
            for e in established:
                cc = e.remote_country_code
                if cc and e.remote_ip:
                    country_ips.setdefault(cc, set()).add(e.remote_ip)
            top_countries = sorted(
                country_ips.items(), key=lambda x: len(x[1]), reverse=True
            )[:10]

            snapshot = Snapshot(
                timestamp=time.time(),
                poll_interval_ms=int(interval * 1000),
                listening=listening,
                established=established,
                alerts=alerts,
                traffic=traffic,
                processes={str(pid): asdict(info) for pid, info in process_tree.items()},
                summary={
                    "total_listening": len(listening),
                    "total_established": len(established),
                    "alert_count": len(alerts),
                    "risk_scores": {str(k): v for k, v in risk_scores.items()},
                },
                geo_stats={
                    "countries_count": len(country_ips),
                    "unique_ips_per_country": {cc: len(ips) for cc, ips in country_ips.items()},
                    "top_countries": [(cc, len(ips)) for cc, ips in top_countries],
                },
            )

            # 7. Write snapshot atomically and broadcast over socket
            snapshot_json = snapshot.to_json()
            write_snapshot(snapshot_json)
            write_widget_snapshot(snapshot)  # lightweight payload for widget
            if socket_server:
                socket_server.broadcast(snapshot_json)

            # 7b. Write heartbeat for daemon health monitoring
            _write_heartbeat(cfg.effective_heartbeat_file)

            # 7c. Record history
            history.record_summary(snapshot)
            for alert in alerts:
                history.record_alert(alert)

            logger.debug(
                "Snapshot: %d listening, %d established, %d alerts",
                len(listening), len(established), len(alerts),
            )

            # 8. Adaptive sleep interval
            current_hash = str(sorted(
                (e.local_port, e.proto, e.state) for e in listening
            ))
            if current_hash != last_snapshot_hash:
                last_snapshot_hash = current_hash
                last_change_time = time.time()

            if alerts:
                interval = cfg.alert_poll_interval
                for a in alerts:
                    logger.info("ALERT [%s] %s", a.level, a.message)

                    # Desktop notification for WARNING and CRITICAL
                    if cfg.notifications_enabled and a.level in (AlertLevel.WARNING, AlertLevel.CRITICAL):
                        alert_hash = f"{a.level}:{a.message}"
                        last_notified = notified_alerts.get(alert_hash, 0)
                        # Only notify if not recently notified (TTL-based dedup)
                        if (time.time() - last_notified) > cfg.alert_ttl:
                            # Rate limiting: max N notifications per window
                            now_ts = time.time()
                            notification_timestamps[:] = [
                                t for t in notification_timestamps
                                if (now_ts - t) < cfg.notification_rate_window
                            ]
                            if len(notification_timestamps) < cfg.notification_rate_limit:
                                try:
                                    icon = "dialog-error" if a.level == AlertLevel.CRITICAL else "dialog-warning"
                                    subprocess.Popen(
                                        [
                                            "notify-send",
                                            "-a", "KPortWatch",
                                            "-u", "critical" if a.level == AlertLevel.CRITICAL else "normal",
                                            "-i", icon,
                                            f"KPortWatch: {a.level}",
                                            a.message,
                                        ],
                                        stdout=subprocess.DEVNULL,
                                        stderr=subprocess.DEVNULL,
                                    )
                                    notified_alerts[alert_hash] = time.time()
                                    notification_timestamps.append(time.time())
                                except FileNotFoundError:
                                    logger.debug("notify-send not found — skipping notification")
                                except OSError as e:
                                    logger.warning("Failed to send notification: %s", e)
                            else:
                                logger.debug("Notification rate limited — skipping %s alert", a.level)

                    # Evict expired alert hashes to bound memory
                    if len(notified_alerts) > 500:
                        now_ts = time.time()
                        expired = [k for k, v in notified_alerts.items()
                                   if (now_ts - v) > cfg.alert_ttl]
                        for k in expired:
                            del notified_alerts[k]

            elif (time.time() - last_change_time) > cfg.idle_threshold_secs:
                interval = cfg.idle_poll_interval
            else:
                interval = args.interval

        except Exception:
            logger.exception("Error in daemon cycle")
            interval = args.interval

        # Periodic update check (once per update_check_interval)
        if cfg.update_enabled:
            now_check = time.time()
            if (now_check - _last_update_check) >= cfg.update_check_interval:
                _last_update_check = now_check
                try:
                    new_version = check_for_update()
                    write_update_state(
                        current=get_local_version(),
                        latest=new_version,
                        update_available=new_version is not None,
                    )
                    if new_version:
                        logger.info("Update available: %s → %s", get_local_version(), new_version)
                except Exception:
                    logger.debug("Update check failed", exc_info=True)

        # Sleep remaining interval
        elapsed = time.time() - cycle_start
        sleep_time = max(0.0, interval - elapsed)
        if sleep_time > 0 and running:
            # Interruptible sleep — check running flag every 0.5s
            end_time = time.time() + sleep_time
            while running and time.time() < end_time:
                time.sleep(min(0.5, end_time - time.time()))

    # Save baseline on clean exit
    alert_engine.save_baseline(cfg.baseline_file)
    # Flush GeoIP cache to disk
    if cfg.geoip_enabled:
        geoip_mod.flush_cache()
    if socket_server:
        socket_server.stop()

    # Clean up PID file
    with contextlib.suppress(OSError):
        os.unlink(PID_FILE)

    logger.info("KPortWatch daemon stopped")


def _daemonize() -> None:
    """Double-fork daemonization with proper cleanup."""
    import logging

    # First fork
    pid = os.fork()
    if pid > 0:
        sys.exit(0)

    # Create new session
    os.setsid()
    os.chdir("/")

    # Second fork
    pid2 = os.fork()
    if pid2 > 0:
        sys.exit(0)

    # Close inherited file descriptors (keep 0,1,2 for std streams)
    try:
        max_fd = os.sysconf("SC_OPEN_MAX")
    except (AttributeError, ValueError):
        max_fd = 1024
    for fd in range(3, min(max_fd, 256)):  # Cap at 256 to avoid slowness
        with contextlib.suppress(OSError):
            os.close(fd)

    # Redirect stdin/stdout/stderr to /dev/null
    devnull = os.open(os.devnull, os.O_RDWR)
    os.dup2(devnull, 0)  # stdin
    os.dup2(devnull, 1)  # stdout
    os.dup2(devnull, 2)  # stderr
    if devnull > 2:
        os.close(devnull)

    # Reconfigure logging to use the new stderr (/dev/null)
    # This prevents log messages from leaking to the launching terminal
    root_logger = logging.getLogger()
    for handler in root_logger.handlers[:]:
        root_logger.removeHandler(handler)
    handler = logging.StreamHandler(sys.stderr)
    handler.setFormatter(logging.Formatter("%(asctime)s %(levelname)s %(message)s"))
    root_logger.addHandler(handler)


def main() -> None:
    args = parse_args()
    setup_logging(args.verbose)

    # Load config before daemonizing (so errors show in terminal)
    load_config(args.config)

    if not args.foreground:
        _daemonize()

    # Prevent duplicate daemons and write PID file
    try:
        pid_fd = open(PID_FILE, "w")  # noqa: SIM115 — fd intentionally held open for lock
        fcntl.flock(pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pid_fd.write(str(os.getpid()))
        pid_fd.flush()
        os.fsync(pid_fd.fileno())
    except BlockingIOError:
        logger.error("Daemon is already running!")
        sys.exit(1)
    except OSError as e:
        logger.error("Failed to create PID file: %s", e)
        sys.exit(1)

    daemon_loop(args)


if __name__ == "__main__":
    try:
        main()
    except Exception:
        import pathlib
        import traceback
        crash_log = pathlib.Path.home() / ".local" / "share" / "kportwatch" / "crash.log"
        crash_log.parent.mkdir(parents=True, exist_ok=True)
        with open(crash_log, "a") as f:
            f.write(f"\n{'='*60}\nCrash at {time.strftime('%Y-%m-%d %H:%M:%S')}\n")
            traceback.print_exc(file=f)
        raise
