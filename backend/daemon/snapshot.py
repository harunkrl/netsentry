"""KPortWatch — Snapshot builder.

Computes risk scores, assembles a :class:`Snapshot`, and publishes it
(write JSON, broadcast over socket, record history, heartbeat).

Owns its own ``_risk_scores`` and ``_prev_listening_set`` state.
External dependencies (alert_engine, history, socket_server, cfg) are
injected at construction.  ``interval_ms`` is passed per-call because
it is owned by the orchestrator.
"""
from __future__ import annotations

import logging
import time
from dataclasses import asdict

from backend.models import InterfaceStats, Snapshot
from backend.risk_score import calculate_risk_score
from backend.writers.json_file import write_snapshot, write_widget_snapshot

logger = logging.getLogger(__name__)


def _write_heartbeat(path: str) -> None:
    """Write a timestamp to the heartbeat file."""
    try:
        with open(path, "w") as f:
            f.write(str(int(time.time() * 1000)))
    except OSError:
        pass


class SnapshotBuilder:
    """Build a :class:`Snapshot` from collected data and publish it."""

    def __init__(self, alert_engine, history, socket_server, cfg) -> None:
        self._alert_engine = alert_engine
        self._history = history
        self._socket_server = socket_server
        self._cfg = cfg

        # Private state — risk score cache
        self._risk_scores: dict = {}
        self._prev_listening_set: frozenset = frozenset()

    def reconfigure(self, cfg) -> None:
        """Apply a new config (e.g. after SIGHUP)."""
        self._cfg = cfg

    # ── Public API ────────────────────────────────────────────

    def build_and_publish(
        self,
        listening: list,
        established: list,
        alerts: list,
        traffic: dict[str, InterfaceStats],
        process_tree: dict,
        interval_ms: int,
    ) -> Snapshot:
        """Compute risk scores, build snapshot, publish to all sinks."""
        risk_scores = self._compute_risk_scores(listening)
        snapshot = self._build_snapshot(
            listening, established, alerts, traffic, process_tree,
            risk_scores, interval_ms,
        )
        self._publish(snapshot, alerts)
        return snapshot

    # ── Private helpers ───────────────────────────────────────

    def _compute_risk_scores(self, listening: list) -> dict:
        """Recalculate risk scores only when listening set changes."""
        current_set = frozenset((e.local_port, e.proto) for e in listening)
        if current_set != self._prev_listening_set:
            self._risk_scores = {
                e.local_port: calculate_risk_score(
                    e,
                    malicious_ports=self._alert_engine.malicious_ports,
                    known_safe_ports=self._alert_engine.known_safe,
                    baseline_ports=(
                        self._alert_engine.get_baseline_ports()
                        if self._alert_engine.is_baseline_complete()
                        else None
                    ),
                    port_blacklist=self._alert_engine.port_blacklist,
                )
                for e in listening
            }
            self._prev_listening_set = current_set
        return self._risk_scores

    def _build_snapshot(
        self,
        listening: list,
        established: list,
        alerts: list,
        traffic: dict[str, InterfaceStats],
        process_tree: dict,
        risk_scores: dict,
        interval_ms: int,
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
            poll_interval_ms=interval_ms,
            listening=listening,
            established=established,
            alerts=alerts,
            traffic=traffic,
            processes={
                str(pid): asdict(info) for pid, info in process_tree.items()
            },
            summary={
                "total_listening": len(listening),
                "total_established": len(established),
                "alert_count": len(alerts),
                "risk_scores": {str(k): v for k, v in risk_scores.items()},
            },
            geo_stats={
                "countries_count": len(country_ips),
                "unique_ips_per_country": {
                    cc: len(ips) for cc, ips in country_ips.items()
                },
                "top_countries": [
                    (cc, len(ips)) for cc, ips in top_countries
                ],
            },
        )

    def _publish(self, snapshot: Snapshot, alerts: list) -> None:
        """Write snapshot, broadcast, record history."""
        snapshot_json = snapshot.to_json()
        write_snapshot(snapshot_json)
        write_widget_snapshot(snapshot)
        if self._socket_server:
            self._socket_server.broadcast(snapshot_json)

        _write_heartbeat(self._cfg.effective_heartbeat_file)

        self._history.record_summary(snapshot)
        for alert in alerts:
            self._history.record_alert(alert)

        logger.debug(
            "Snapshot: %d listening, %d established, %d alerts",
            len(snapshot.listening),
            len(snapshot.established),
            len(alerts),
        )
