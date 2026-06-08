"""KPortWatch — Thin daemon orchestrator.

Coordinates the main daemon loop by delegating to decoupled components:

- :class:`DataCollector`      — socket entries, process tree, traffic, enrichment
- :class:`NotificationManager` — desktop notifications with rate limiting
- :class:`SnapshotBuilder`    — risk scores, snapshot assembly, publishing
- :class:`CommandHandler`     — Unix socket command processing
- :class:`UpdateChecker`      — periodic version checking

The orchestrator owns only the **lifecycle** state (``running``, ``interval``,
baseline bookkeeping, error counter) and the **adaptive interval** logic.
All other mutable state lives inside the respective components.
"""
from __future__ import annotations

import contextlib
import logging
import os
import signal
import time

# sd_notify support — graceful no-op when not running under systemd
try:
    from systemd.daemon import notify as _sd_notify
except ImportError:
    _sd_notify = lambda *a, **kw: None  # type: ignore[assignment]

from shared import PID_FILE
from shared.config import apply_cli_overrides, load_config

from backend.alert_engine import AlertEngine
from backend.daemon.collector import DataCollector
from backend.daemon.commands import CommandHandler
from backend.daemon.notifications import NotificationManager
from backend.daemon.snapshot import SnapshotBuilder
from backend.daemon.updater import UpdateChecker
from backend.history import HistoryRecorder
from backend.parsers import geoip as geoip_mod
from backend.writers.unix_socket import UnixSocketServer

logger = logging.getLogger(__name__)


class DaemonController:
    """Orchestrates the daemon's main loop.

    This is a **thin orchestrator** — it coordinates component interactions
    and owns only lifecycle state.  All domain-specific mutable state is
    encapsulated within the components themselves.
    """

    def __init__(self, args) -> None:
        self.args = args
        self.cfg = None

        # Lifecycle state — owned exclusively by the orchestrator
        self.running: bool = True
        self.interval: float = 2.0
        self._last_snapshot_hash: int | None = None
        self._last_change_time: float = time.time()
        self._prev_baseline: frozenset = frozenset()
        self._error_count: int = 0

        # Components (initialised in _init_components)
        self.alert_engine: AlertEngine | None = None
        self.history: HistoryRecorder | None = None
        self.socket_server: UnixSocketServer | None = None
        self.collector: DataCollector | None = None
        self.notification_manager: NotificationManager | None = None
        self.snapshot_builder: SnapshotBuilder | None = None
        self.command_handler: CommandHandler | None = None
        self.updater: UpdateChecker | None = None

    # ── Initialisation ────────────────────────────────────────

    def _init_components(self) -> None:
        """Load config and create all components via constructor injection."""
        self.cfg = load_config()
        self.cfg = apply_cli_overrides(self.cfg, self.args)
        self.interval = self.cfg.poll_interval
        _sd_notify("READY=1")  # notify systemd that daemon is ready

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

        # Alert engine
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

        # Command handler + Unix socket server
        self.command_handler = CommandHandler()
        self.socket_server = UnixSocketServer()
        self.socket_server.set_command_handler(self.command_handler.handle_command)
        self.socket_server.start()

        # Data collector
        self.collector = DataCollector(cfg=self.cfg)

        # Notification manager
        self.notification_manager = NotificationManager(cfg=self.cfg)

        # Snapshot builder
        self.snapshot_builder = SnapshotBuilder(
            alert_engine=self.alert_engine,
            history=self.history,
            socket_server=self.socket_server,
            cfg=self.cfg,
        )

        # Update checker
        self.updater = UpdateChecker(cfg=self.cfg)

        # Signal handlers
        with contextlib.suppress(AttributeError):
            signal.signal(signal.SIGHUP, self._handle_sighup)
        signal.signal(signal.SIGTERM, self._handle_shutdown_signal)
        signal.signal(signal.SIGINT, self._handle_shutdown_signal)

    # ── Signal handlers ───────────────────────────────────────

    def _handle_sighup(self, signum, frame) -> None:
        """SIGHUP: reload config + propagate to components + reset baseline."""
        logger.info("Received SIGHUP, reloading configuration and resetting baseline...")
        self.cfg = load_config(self.cfg.config_path)
        self.cfg = apply_cli_overrides(self.cfg, self.args)
        self.interval = self.cfg.poll_interval

        # Propagate new config to all components that use it
        self.collector.reconfigure(self.cfg)
        self.notification_manager.reconfigure(self.cfg)
        self.snapshot_builder.reconfigure(self.cfg)
        self.updater.reconfigure(self.cfg)

        self.alert_engine.reset_baseline()
        logger.info(
            "Configuration reloaded — notifications_enabled=%s, poll_interval=%.1fs",
            self.cfg.notifications_enabled,
            self.cfg.poll_interval,
        )

    def _handle_shutdown_signal(self, signum, _frame) -> None:
        """SIGTERM/SIGINT: graceful shutdown."""
        logger.info("Received signal %s — shutting down", signum)
        self.running = False

    # ── Adaptive interval (owned by orchestrator) ─────────────

    def _adaptive_interval(self, listening: list, alerts: list) -> float:
        """Compute the next poll interval based on activity."""
        if alerts:
            return self.cfg.alert_poll_interval

        current_hash = hash(
            frozenset((e.local_port, e.proto, e.state) for e in listening)
        )
        if current_hash != self._last_snapshot_hash:
            self._last_snapshot_hash = current_hash
            self._last_change_time = time.time()

        if (time.time() - self._last_change_time) > self.cfg.idle_threshold_secs:
            return self.cfg.idle_poll_interval
        return self.cfg.poll_interval

    # ── Sleep helper ──────────────────────────────────────────

    def _sleep_remaining(self, cycle_start: float) -> None:
        """Interruptible sleep for the remaining interval."""
        elapsed = time.time() - cycle_start
        sleep_time = max(0.0, self.interval - elapsed)
        if sleep_time > 0 and self.running:
            end_time = time.time() + sleep_time
            while self.running and time.time() < end_time:
                time.sleep(min(0.5, end_time - time.time()))

    # ── Cleanup ───────────────────────────────────────────────

    def _cleanup(self) -> None:
        """Graceful shutdown cleanup."""
        logger.info("Shutting down — cleaning up resources")
        if self.history:
            self.history.close()

        # Shut down async subsystems
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
        """Main daemon entry point — thin orchestrator loop."""
        self._init_components()

        while self.running:
            cycle_start = time.time()
            try:
                collected = self.collector.collect()

                alerts = self.alert_engine.analyze(collected.listening)

                # Baseline persistence
                if self.alert_engine.is_baseline_complete():
                    current_baseline = self.alert_engine.get_baseline_ports()
                    if current_baseline != self._prev_baseline:
                        self.alert_engine.save_baseline()
                        self._prev_baseline = current_baseline

                self.snapshot_builder.build_and_publish(
                    listening=collected.listening,
                    established=collected.established,
                    alerts=alerts,
                    traffic=collected.traffic,
                    process_tree=collected.process_tree,
                    interval_ms=int(self.interval * 1000),
                )

                self.notification_manager.handle(alerts)
                self.interval = self._adaptive_interval(
                    collected.listening, alerts
                )
                self._error_count = 0
                _sd_notify("WATCHDOG=1")  # heartbeat for systemd

            except Exception:
                self._error_count += 1
                logger.exception(
                    "Error in daemon cycle (consecutive: %d)", self._error_count
                )
                self.interval = self.cfg.poll_interval
                if self._error_count >= 10:
                    logger.critical(
                        "Too many consecutive errors (%d) — stopping daemon",
                        self._error_count,
                    )
                    self.running = False

            self.updater.check()
            self._sleep_remaining(cycle_start)

        self._cleanup()
