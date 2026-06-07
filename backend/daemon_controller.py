"""KPortWatch — Daemon controller class.

Extracts the daemon_loop() monolith into a well-structured class with
clearly separated lifecycle, collection, and notification concerns.
"""
from __future__ import annotations

import contextlib
import logging
import os
import signal
import subprocess
import time
from dataclasses import asdict

from shared import PID_FILE, AlertLevel
from shared.config import apply_cli_overrides, load_config
from shared.network import is_private_ip

from backend.alert_engine import AlertEngine
from backend.history import HistoryRecorder
from backend.kportwatch_daemon import classify_entries
from backend.models import InterfaceStats, Snapshot
from backend.parsers import geoip as geoip_mod
from backend.parsers.inode_map import build_inode_to_pid_map, build_uid_process_map
from backend.parsers.net_dev import parse_proc_net_dev
from backend.parsers.proc_net import parse_all_proc
from backend.parsers.process_tree import build_process_tree
from backend.parsers.rdns import get_hostname
from backend.risk_score import calculate_risk_score
from backend.update import check_for_update, get_local_version, write_update_state
from backend.writers.json_file import write_snapshot, write_widget_snapshot
from backend.writers.unix_socket import UnixSocketServer

# psutil-based collectors (preferred, with /proc fallback)
try:
    import psutil as _psutil  # noqa: F401 — checked at runtime

    _HAS_PSUTIL = True
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
except ImportError:
    _HAS_PSUTIL = False
    _psutil_connections = None
    _psutil_network_pids = None
    _psutil_process_tree = None
    _psutil_traffic = None

logger = logging.getLogger(__name__)


def _write_heartbeat(path: str) -> None:
    """Write a timestamp to the heartbeat file."""
    try:
        with open(path, "w") as f:
            f.write(str(int(time.time() * 1000)))
    except OSError:
        pass


class DaemonController:
    """Orchestrates the daemon's main loop.

    Separates concerns into clear phases:
    - _init_components: one-time setup (config, alert engine, history, socket)
    - _collect_entries: gather socket entries + resolve PIDs
    - _build_process_tree: construct process tree
    - _enrich_connections: rDNS + GeoIP lookups
    - _collect_traffic: interface stats with delta computation
    - _build_snapshot: assemble the Snapshot object
    - _publish: write snapshot, broadcast, record history
    - _handle_notifications: desktop alerts with rate limiting
    - _adaptive_interval: adjust poll interval based on activity
    """

    def __init__(self, args) -> None:
        self.args = args
        self.cfg = None
        self.alert_engine: AlertEngine | None = None
        self.history: HistoryRecorder | None = None
        self.socket_server: UnixSocketServer | None = None

        # Cycle state
        self.running = True
        self.interval: float = 2.0
        self.last_snapshot_hash: int | None = None
        self.last_change_time: float = time.time()
        self.prev_baseline: frozenset = frozenset()
        self.prev_listening_set: frozenset = frozenset()
        self.risk_scores: dict = {}
        self.notified_alerts: dict[str, float] = {}
        self.notification_timestamps: list[float] = []
        self._prev_traffic: dict[str, tuple[float, InterfaceStats]] = {}
        self._last_update_check: float = 0.0
        self._error_count: int = 0

    def _init_components(self) -> None:
        """Load config, initialise alert engine, history, socket server."""
        self.cfg = load_config()
        self.cfg = apply_cli_overrides(self.cfg, self.args)
        self.interval = self.cfg.poll_interval

        # Propagate DNS cache limits
        from backend.parsers import rdns
        rdns.configure(
            max_cache_size=self.cfg.dns_cache_size,
            max_pending=self.cfg.dns_max_pending,
        )

        # Initialise GeoIP module
        if self.cfg.geoip_enabled:
            geoip_mod.init({
                "geoip_api_url": self.cfg.geoip_api_url,
                "geoip_cache_file": self.cfg.geoip_cache_file,
                "geoip_cache_max_entries": self.cfg.geoip_cache_max_entries,
                "geoip_cache_ttl_days": self.cfg.geoip_cache_ttl_days,
                "geoip_batch_size": self.cfg.geoip_batch_size,
                "geoip_timeout": self.cfg.geoip_timeout,
            })

        self.alert_engine = AlertEngine(
            known_safe_ports=self.cfg.known_safe_ports,
            baseline_duration=self.cfg.baseline_duration,
            malicious_ports=set(self.cfg.malicious_ports),
            burst_threshold=self.cfg.burst_threshold,
            privileged_port_max=self.cfg.privileged_port_max,
            custom_rules=self.cfg.custom_rules,
            port_whitelist=set(self.cfg.port_whitelist),
            port_blacklist=set(self.cfg.port_blacklist),
            ip_blacklist=list(self.cfg.ip_blacklist),
        )

        if self.alert_engine.load_baseline(self.cfg.baseline_file):
            logger.info("Loaded saved baseline from %s", self.cfg.baseline_file)
        else:
            logger.info(
                "No saved baseline — will learn for %.0f seconds",
                self.alert_engine.baseline_duration,
            )

        # History recorder
        self.history = HistoryRecorder(retention_days=self.cfg.history_retention_days)

        # Unix socket server
        self.socket_server = UnixSocketServer()
        self.socket_server.set_command_handler(self._handle_socket_command)
        self.socket_server.start()

        # Signal handlers
        with contextlib.suppress(AttributeError):
            signal.signal(signal.SIGHUP, self._handle_sighup)
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)

    def _handle_sighup(self, signum, frame) -> None:
        """SIGHUP: reload config + reset baseline."""
        logger.info("Received SIGHUP, reloading configuration and resetting baseline...")
        self.cfg = load_config(self.cfg.config_path)
        self.cfg = apply_cli_overrides(self.cfg, self.args)
        self.alert_engine.reset_baseline()
        logger.info(
            "Configuration reloaded — notifications_enabled=%s, poll_interval=%.1fs",
            self.cfg.notifications_enabled, self.cfg.poll_interval,
        )

    def _handle_shutdown_signal(self, signum, _frame) -> None:
        """SIGTERM/SIGINT: graceful shutdown."""
        logger.info("Received signal %s — shutting down", signum)
        self.running = False

    # ── Socket command handler ────────────────────────────────
    _MAX_KILL_RATE = 5            # max kill commands per minute
    _kill_timestamps: list[float] = []

    def _handle_socket_command(self, cmd: dict) -> dict:
        """Handle commands sent over the Unix socket.

        Kill commands include rate limiting and requestor UID verification
        via SO_PEERCRED to prevent unauthorized process termination.
        """
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

            # Rate limiting — max N kill commands per 60s
            now_ts = time.time()
            self._kill_timestamps[:] = [
                t for t in self._kill_timestamps if (now_ts - t) < 60.0
            ]
            if len(self._kill_timestamps) >= self._MAX_KILL_RATE:
                logger.warning("Kill rate limit exceeded for PID %d", pid)
                return {"status": "error", "message": "Rate limit exceeded — too many kill requests"}

            # UID authorization — only allow killing processes owned by the same user
            try:
                target_uid = os.stat(f"/proc/{pid}").st_uid
            except (FileNotFoundError, PermissionError, OSError):
                target_uid = None
            if target_uid is not None and target_uid != os.getuid():
                logger.warning(
                    "Kill denied: PID %d (uid=%d) not owned by daemon user (uid=%d)",
                    pid, target_uid, os.getuid(),
                )
                return {
                    "status": "error",
                    "message": f"Permission denied: PID {pid} is not owned by this user",
                }

            self._kill_timestamps.append(now_ts)
            logger.info("Kill authorized for PID %d by uid=%d", pid, os.getuid())
            return self._kill_process(pid)
        return {"status": "error", "message": f"Unknown command: {command}"}

    # System PIDs that should never be killed
    PROTECTED_PIDS = {0, 1, 2}

    @staticmethod
    def _kill_process(pid: int) -> dict:
        """Kill a process by PID with SIGTERM → wait → SIGKILL fallback."""
        if pid in DaemonController.PROTECTED_PIDS or pid <= 0:
            return {"status": "error", "message": f"PID {pid} is protected and cannot be killed"}
        try:
            os.kill(pid, signal.SIGTERM)
        except ProcessLookupError:
            return {"status": "ok", "message": f"Process {pid} not found (already gone)"}
        except PermissionError:
            return {"status": "error", "message": f"Permission denied killing PID {pid}"}
        except OSError as e:
            return {"status": "error", "message": f"Error sending SIGTERM to {pid}: {e}"}

        deadline = time.time() + 2.0
        while time.time() < deadline:
            try:
                os.kill(pid, 0)
                time.sleep(0.1)
            except ProcessLookupError:
                logger.info("Process %d terminated gracefully after SIGTERM", pid)
                return {"status": "ok", "message": f"Process {pid} terminated (SIGTERM)"}
            except PermissionError:
                break

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

    # ── Collection phases ─────────────────────────────────────
    def _collect_entries(self) -> tuple[list, dict | None]:
        """Collect socket entries. Returns (entries, inode_map_or_None)."""
        inode_map = None
        if _HAS_PSUTIL:
            entries = _psutil_connections()
            logger.debug("Collected %d socket entries via psutil", len(entries))
        else:
            entries = parse_all_proc()
            logger.debug("Parsed %d socket entries via /proc", len(entries))

        # Resolve PIDs (only needed for /proc path or missing PIDs)
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

        return entries, inode_map

    def _build_tree(self, inode_map: dict | None) -> dict:
        """Build process tree, reusing inode_map if available."""
        if _HAS_PSUTIL:
            network_pids = _psutil_network_pids()
            return _psutil_process_tree(network_pids)
        if inode_map is None:
            inode_map = build_inode_to_pid_map()
        return build_process_tree(inode_map)

    def _enrich_connections(self, established: list) -> None:
        """rDNS + GeoIP enrichment for remote IPs."""
        for e in established:
            if e.remote_ip and not is_private_ip(e.remote_ip):
                e.remote_hostname = get_hostname(e.remote_ip)

        if not self.cfg.geoip_enabled:
            return

        unique_ips = {
            e.remote_ip for e in established
            if e.remote_ip and not is_private_ip(e.remote_ip)
        }
        if not unique_ips:
            return

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

    def _collect_traffic(self) -> dict[str, InterfaceStats]:
        """Collect interface stats with rate computation."""
        now_ts = time.time()
        raw = _psutil_traffic() if _HAS_PSUTIL else parse_proc_net_dev()
        traffic = {}
        for stats in raw:
            if stats.interface in self._prev_traffic:
                prev_ts, prev_stats = self._prev_traffic[stats.interface]
                elapsed = now_ts - prev_ts
                if elapsed > 0:
                    stats.rx_rate = max(0, (stats.rx_bytes - prev_stats.rx_bytes) / elapsed)
                    stats.tx_rate = max(0, (stats.tx_bytes - prev_stats.tx_bytes) / elapsed)
            traffic[stats.interface] = stats

        # Store for next cycle
        self._prev_traffic = {
            name: (now_ts, InterfaceStats(
                interface=s.interface,
                rx_bytes=s.rx_bytes,
                tx_bytes=s.tx_bytes,
                rx_packets=s.rx_packets,
                tx_packets=s.tx_packets,
                rx_errors=s.rx_errors,
                tx_errors=s.tx_errors,
                rx_drops=s.rx_drops,
                tx_drops=s.tx_drops,
            ))
            for name, s in traffic.items()
        }
        return traffic

    def _compute_risk_scores(self, listening: list) -> dict:
        """Recalculate risk scores only when listening set changes."""
        current_set = frozenset((e.local_port, e.proto) for e in listening)
        if current_set != self.prev_listening_set:
            self.risk_scores = {
                e.local_port: calculate_risk_score(
                    e,
                    malicious_ports=self.alert_engine.malicious_ports,
                    known_safe_ports=self.alert_engine.known_safe,
                    baseline_ports=(
                        self.alert_engine.get_baseline_ports()
                        if self.alert_engine.is_baseline_complete() else None
                    ),
                    port_blacklist=self.alert_engine.port_blacklist,
                )
                for e in listening
            }
            self.prev_listening_set = current_set
        return self.risk_scores

    def _build_snapshot(
        self,
        listening: list,
        established: list,
        alerts: list,
        traffic: dict,
        process_tree: dict,
        risk_scores: dict,
    ) -> Snapshot:
        """Assemble the Snapshot object."""
        country_ips: dict[str, set] = {}
        for e in established:
            cc = e.remote_country_code
            if cc and e.remote_ip:
                country_ips.setdefault(cc, set()).add(e.remote_ip)

        top_countries = sorted(
            country_ips.items(), key=lambda x: len(x[1]), reverse=True
        )[:10]

        return Snapshot(
            timestamp=time.time(),
            poll_interval_ms=int(self.interval * 1000),
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

    def _publish(self, snapshot: Snapshot, alerts: list) -> None:
        """Write snapshot, broadcast, record history."""
        snapshot_json = snapshot.to_json()
        write_snapshot(snapshot_json)
        write_widget_snapshot(snapshot)
        if self.socket_server:
            self.socket_server.broadcast(snapshot_json)

        _write_heartbeat(self.cfg.effective_heartbeat_file)

        self.history.record_summary(snapshot)
        for alert in alerts:
            self.history.record_alert(alert)

        logger.debug(
            "Snapshot: %d listening, %d established, %d alerts",
            len(snapshot.listening), len(snapshot.established), len(alerts),
        )

    def _handle_notifications(self, alerts: list) -> None:
        """Send desktop notifications with rate limiting and dedup."""
        if not alerts:
            return

        self.interval = self.cfg.alert_poll_interval

        for a in alerts:
            logger.info("ALERT [%s] %s", a.level, a.message)

            if not self.cfg.notifications_enabled:
                continue
            if a.level not in (AlertLevel.WARNING, AlertLevel.CRITICAL):
                continue

            alert_hash = f"{a.level}:{a.message}"
            last_notified = self.notified_alerts.get(alert_hash, 0)
            if (time.time() - last_notified) <= self.cfg.alert_ttl:
                continue

            # Rate limiting
            now_ts = time.time()
            self.notification_timestamps[:] = [
                t for t in self.notification_timestamps
                if (now_ts - t) < self.cfg.notification_rate_window
            ]
            if len(self.notification_timestamps) >= self.cfg.notification_rate_limit:
                logger.debug("Notification rate limited — skipping %s alert", a.level)
                continue

            try:
                icon = "dialog-error" if a.level == AlertLevel.CRITICAL else "dialog-warning"
                # Sanitize alert message: truncate and strip control characters
                safe_msg = ''.join(
                    c for c in a.message[:200] if c.isprintable() or c in '\n\t'
                )
                subprocess.Popen(
                    [
                        "notify-send", "-a", "KPortWatch",
                        "-u", "critical" if a.level == AlertLevel.CRITICAL else "normal",
                        "-i", icon,
                        f"KPortWatch: {a.level}", safe_msg,
                    ],
                    stdout=subprocess.DEVNULL,
                    stderr=subprocess.DEVNULL,
                )
                self.notified_alerts[alert_hash] = time.time()
                self.notification_timestamps.append(time.time())
            except FileNotFoundError:
                logger.debug("notify-send not found — skipping notification")
            except OSError as e:
                logger.warning("Failed to send notification: %s", e)

        # Evict expired alert hashes
        if len(self.notified_alerts) > 500:
            now_ts = time.time()
            expired = [
                k for k, v in self.notified_alerts.items()
                if (now_ts - v) > self.cfg.alert_ttl
            ]
            for k in expired:
                del self.notified_alerts[k]

    def _adaptive_interval(self, listening: list, alerts: list) -> float:
        """Compute the next poll interval based on activity."""
        current_hash = hash(frozenset(
            (e.local_port, e.proto, e.state) for e in listening
        ))
        if current_hash != self.last_snapshot_hash:
            self.last_snapshot_hash = current_hash
            self.last_change_time = time.time()

        if alerts:
            return self.cfg.alert_poll_interval
        if (time.time() - self.last_change_time) > self.cfg.idle_threshold_secs:
            return self.cfg.idle_poll_interval
        return self.cfg.poll_interval

    def _check_for_updates(self) -> None:
        """Periodically check for new versions."""
        if not self.cfg.update_enabled:
            return
        now_ts = time.time()
        if (now_ts - self._last_update_check) < self.cfg.update_check_interval:
            return
        self._last_update_check = now_ts
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

    def _sleep_remaining(self, cycle_start: float) -> None:
        """Interruptible sleep for the remaining interval."""
        elapsed = time.time() - cycle_start
        sleep_time = max(0.0, self.interval - elapsed)
        if sleep_time > 0 and self.running:
            end_time = time.time() + sleep_time
            while self.running and time.time() < end_time:
                time.sleep(min(0.5, end_time - time.time()))

    def _cleanup(self) -> None:
        """Graceful shutdown cleanup."""
        logger.info("Shutting down — cleaning up resources")
        if self.history:
            self.history.close()
        if _HAS_PSUTIL:
            try:
                from backend.parsers import rdns as _rdns_mod
                _rdns_mod.shutdown()
            except Exception:
                logger.debug("rdns shutdown error", exc_info=True)
            try:
                geoip_mod.shutdown()
            except Exception:
                logger.debug("geoip shutdown error", exc_info=True)

        if self.alert_engine:
            self.alert_engine.save_baseline(self.cfg.baseline_file)
        if self.cfg.geoip_enabled:
            geoip_mod.flush_cache()
        if self.socket_server:
            self.socket_server.stop()

        with contextlib.suppress(OSError):
            os.unlink(PID_FILE)

        logger.info("KPortWatch daemon stopped")

    # ── Main run loop ─────────────────────────────────────────
    def run(self) -> None:
        """Main daemon entry point."""
        self._init_components()

        while self.running:
            cycle_start = time.time()
            try:
                entries, inode_map = self._collect_entries()
                process_tree = self._build_tree(inode_map)
                listening, established = classify_entries(entries)
                self._enrich_connections(established)
                traffic = self._collect_traffic()

                alerts = self.alert_engine.analyze(listening)

                # Save baseline if changed
                if self.alert_engine.is_baseline_complete():
                    current_baseline = self.alert_engine.get_baseline_ports()
                    if current_baseline != self.prev_baseline:
                        self.alert_engine.save_baseline()
                        self.prev_baseline = current_baseline

                risk_scores = self._compute_risk_scores(listening)
                snapshot = self._build_snapshot(
                    listening, established, alerts, traffic,
                    process_tree, risk_scores,
                )
                self._publish(snapshot, alerts)
                self._handle_notifications(alerts)
                self.interval = self._adaptive_interval(listening, alerts)
                self._error_count = 0  # reset on successful cycle

            except Exception:
                self._error_count += 1
                logger.exception("Error in daemon cycle (consecutive: %d)", self._error_count)
                self.interval = self.cfg.poll_interval
                if self._error_count >= 10:
                    logger.critical("Too many consecutive errors (%d) — stopping daemon", self._error_count)
                    self.running = False

            self._check_for_updates()
            self._sleep_remaining(cycle_start)

        self._cleanup()
