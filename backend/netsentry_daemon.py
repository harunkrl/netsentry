#!/usr/bin/env python3
"""NetSentry — Main backend daemon.

Gathers network socket data from /proc, runs alert analysis,
and writes JSON snapshots for the Plasma widget and TUI.

Usage:
    python3 netsentry-daemon.py --foreground --verbose
    python3 netsentry-daemon.py --interval 5
"""
from __future__ import annotations

import argparse
import logging
import os
import signal
import sys
import time
import fcntl
import atexit
from dataclasses import asdict
from typing import Dict, List, Tuple

from shared import (
    BASELINE_FILE,
    DATA_FILE,
    DEFAULT_POLL_INTERVAL,
    KNOWN_SAFE_PORTS,
    PID_FILE,
    AlertLevel,
)
from shared.config import load_config, get_config, apply_cli_overrides, AppConfig
from backend.models import InterfaceStats, Snapshot, SocketEntry
from backend.parsers.proc_net import parse_all_proc
from backend.parsers.net_dev import parse_proc_net_dev
from backend.parsers.inode_map import build_inode_to_pid_map
from backend.parsers.process_tree import build_process_tree
from backend.alert_engine import AlertEngine
from backend.writers.json_file import write_snapshot
from backend.parsers.rdns import get_hostname
from backend.parsers import geoip as geoip_mod
from backend.writers.unix_socket import UnixSocketServer
from backend.history import HistoryRecorder
from backend.risk_score import calculate_risk_score
from backend.update import check_for_update, write_update_state, get_local_version
import subprocess

logger = logging.getLogger("netsentry")


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
        description="NetSentry backend daemon — network security monitor",
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
        help="Path to config file (default: ~/.config/netsentry/config.toml)",
    )
    return parser.parse_args()


def setup_logging(verbose: bool) -> None:
    level = logging.DEBUG if verbose else logging.INFO
    logging.basicConfig(
        level=level,
        format="%(asctime)s [%(levelname)s] %(name)s: %(message)s",
        datefmt="%H:%M:%S",
    )


def merge_inode_map(entries: List[SocketEntry]) -> None:
    """Resolve PIDs for socket entries by scanning /proc fd symlinks."""
    inode_map = build_inode_to_pid_map()
    for entry in entries:
        info = inode_map.get(entry.inode)
        if info:
            pid, proc_name, cmdline = info
            entry.pid = pid
            entry.process_name = proc_name
            entry.cmdline = cmdline


def classify_entries(
    entries: List[SocketEntry],
) -> tuple[List[SocketEntry], List[SocketEntry]]:
    """Split entries into listening and established lists.

    Listening: state is LISTEN or UNCONN (UDP listening).
    Everything else goes to established.
    """
    listening: List[SocketEntry] = []
    established: List[SocketEntry] = []
    for e in entries:
        if e.state in ("LISTEN", "UNCONN"):
            listening.append(e)
        else:
            established.append(e)
    return listening, established


def compute_traffic_deltas(
    current: List[InterfaceStats],
    prev: Dict[str, Tuple[float, InterfaceStats]],
    now: float,
) -> Dict[str, InterfaceStats]:
    """Compute per-second RX/TX rates from cumulative counters.

    Args:
        current: Freshly parsed interface stats.
        prev: Previous cycle's {iface: (timestamp, InterfaceStats)}.
        now: Current timestamp.

    Returns:
        Dict of {iface: InterfaceStats} with rx_rate/tx_rate filled.
    """
    result: Dict[str, InterfaceStats] = {}
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
        logger.info("Configuration reloaded")

    try:
        signal.signal(signal.SIGHUP, reload_config)
    except AttributeError:
        pass # Windows compatibility

    running = True
    last_snapshot_hash: str = ""
    last_change_time = time.time()
    prev_baseline: frozenset = frozenset()
    notified_alerts: dict[str, float] = {}  # alert_hash → timestamp
    notification_timestamps: list[float] = []  # for rate limiting
    _prev_traffic: Dict[str, Tuple[float, InterfaceStats]] = {}  # iface → (ts, stats)
    _last_update_check: float = 0.0

    # Start Unix Socket Server
    socket_server = UnixSocketServer()
    socket_server.start()

    # Start history recorder
    history = HistoryRecorder()

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
            # 1. Parse /proc/net files
            entries = parse_all_proc()
            logger.debug("Parsed %d socket entries", len(entries))

            # 2. Resolve PIDs
            inode_map = build_inode_to_pid_map()
            for entry in entries:
                info = inode_map.get(entry.inode)
                if info:
                    pid, proc_name, cmdline = info
                    entry.pid = pid
                    entry.process_name = proc_name
                    entry.cmdline = cmdline

            # 2.5 Build process tree (reuses inode_map for has_network flag)
            process_tree = build_process_tree(inode_map)

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

            # 3.6 Parse /proc/net/dev for traffic statistics
            now_ts = time.time()
            raw_traffic = parse_proc_net_dev()
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
            country_ips: Dict[str, set] = {}
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
                    if a.level in (AlertLevel.WARNING, AlertLevel.CRITICAL):
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
                                            "-a", "NetSentry",
                                            "-u", "critical" if a.level == AlertLevel.CRITICAL else "normal",
                                            "-i", icon,
                                            f"NetSentry: {a.level}",
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
    try:
        os.unlink(PID_FILE)
    except OSError:
        pass

    logger.info("NetSentry daemon stopped")


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
        try:
            os.close(fd)
        except OSError:
            pass

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
        pid_fd = open(PID_FILE, "w")
        fcntl.flock(pid_fd, fcntl.LOCK_EX | fcntl.LOCK_NB)
        pid_fd.write(str(os.getpid()))
        pid_fd.flush()
    except BlockingIOError:
        logger.error("Daemon is already running!")
        sys.exit(1)
    except OSError as e:
        logger.error("Failed to create PID file: %s", e)
        sys.exit(1)

    daemon_loop(args)


if __name__ == "__main__":
    main()
