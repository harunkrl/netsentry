"""NetSentry — Alert engine with baseline learning.

Alert rules:
  1. Port in MALICIOUS_PORTS              → CRITICAL
  2. Port < 1024, not known-safe, not baseline → WARNING
  3. New listening port not in baseline   → INFO
  4. Process with no cmdline              → WARNING
  5. 3+ new ports in one cycle            → WARNING
"""
from __future__ import annotations

import json
import os
import sys
import time
from typing import Dict, List, Optional, Set

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from shared import (
    AlertLevel,
    BASELINE_DIR,
    BASELINE_FILE,
    KNOWN_SAFE_PORTS,
    MALICIOUS_PORTS,
    PRIVILEGED_PORT_MAX,
)
from backend.models import Alert, SocketEntry


class AlertEngine:
    """Generates security alerts based on socket entries and a learned baseline."""

    def __init__(
        self,
        known_safe_ports: Optional[Dict[int, str]] = None,
        baseline_duration: float = 300.0,
    ) -> None:
        self.known_safe: Dict[int, str] = dict(known_safe_ports or KNOWN_SAFE_PORTS)
        self.baseline_duration = baseline_duration
        self._baseline_ports: Set[int] = set()
        self._baseline_start: Optional[float] = None
        self._baseline_stable = False
        self._last_ports: Set[int] = set()

    # ── Baseline management ────────────────────────────────────

    def update_baseline(self, entries: List[SocketEntry]) -> None:
        """Learn listening ports during the baseline period (first N seconds).

        Once the baseline period completes and ports haven't changed for a
        full cycle, the baseline is considered stable.
        """
        now = time.time()
        current_ports = {e.local_port for e in entries}

        if self._baseline_start is None:
            self._baseline_start = now

        # Only accumulate during the learning phase
        # Once stable, do NOT add new ports — otherwise Rules 2,3,5
        # would never fire because every port is already "baseline"
        if not self._baseline_stable:
            self._baseline_ports.update(current_ports)

        elapsed = now - self._baseline_start
        if elapsed >= self.baseline_duration:
            # Check stability — no new ports in this cycle vs last
            if current_ports == self._last_ports:
                self._baseline_stable = True
            self._last_ports = current_ports

    def is_baseline_complete(self) -> bool:
        """Return True once the baseline learning period has finished."""
        return self._baseline_stable

    def save_baseline(self, path: Optional[str] = None) -> None:
        """Persist the baseline port set to disk."""
        path = path or BASELINE_FILE
        os.makedirs(os.path.dirname(path), exist_ok=True)
        data = {
            "ports": sorted(self._baseline_ports),
            "timestamp": time.time(),
        }
        tmp = path + ".tmp"
        with open(tmp, "w") as fh:
            json.dump(data, fh, indent=2)
        os.replace(tmp, path)

    def load_baseline(self, path: Optional[str] = None) -> bool:
        """Load a previously saved baseline. Returns True on success."""
        path = path or BASELINE_FILE
        try:
            with open(path, "r") as fh:
                data = json.load(fh)
            self._baseline_ports = set(data.get("ports", []))
            self._baseline_stable = True
            self._baseline_start = data.get("timestamp", time.time())
            return True
        except (FileNotFoundError, json.JSONDecodeError, OSError):
            return False

    # ── Analysis ───────────────────────────────────────────────

    def analyze(self, entries: List[SocketEntry]) -> List[Alert]:
        """Run all alert rules against the provided listening socket entries.

        Also feeds the entries into baseline learning.
        """
        self.update_baseline(entries)

        alerts: List[Alert] = []
        now = time.time()

        current_ports: Set[int] = set()
        new_ports: List[SocketEntry] = []

        for entry in entries:
            port = entry.local_port
            current_ports.add(port)

            is_known_safe = port in self.known_safe
            is_baseline = port in self._baseline_ports

            # Rule 1: Malicious port
            if port in MALICIOUS_PORTS:
                alerts.append(Alert(
                    level=AlertLevel.CRITICAL,
                    port=port,
                    proto=entry.proto,
                    process_name=entry.process_name,
                    pid=entry.pid,
                    message=f"Known malicious port {port} detected ({entry.process_name or 'unknown'})",
                    timestamp=now,
                ))
                continue  # no need for further rules

            # Rule 4: Process with no cmdline
            if entry.cmdline is None or entry.cmdline == "":
                alerts.append(Alert(
                    level=AlertLevel.WARNING,
                    port=port,
                    proto=entry.proto,
                    process_name=entry.process_name,
                    pid=entry.pid,
                    message=f"Process on port {port} has no cmdline ({entry.process_name or 'unknown'}, pid={entry.pid})",
                    timestamp=now,
                ))

            # Rule 2: Privileged port not known-safe and not in baseline
            if port <= PRIVILEGED_PORT_MAX and not is_known_safe and not is_baseline:
                alerts.append(Alert(
                    level=AlertLevel.WARNING,
                    port=port,
                    proto=entry.proto,
                    process_name=entry.process_name,
                    pid=entry.pid,
                    message=f"Unknown privileged port {port} detected",
                    timestamp=now,
                ))
                continue

            # Rule 3: New listening port not in baseline
            if self._baseline_stable and not is_baseline:
                new_ports.append(entry)
                alerts.append(Alert(
                    level=AlertLevel.INFO,
                    port=port,
                    proto=entry.proto,
                    process_name=entry.process_name,
                    pid=entry.pid,
                    message=f"New listening port {port} not in baseline",
                    timestamp=now,
                ))

        # Rule 5: Burst — 3+ new ports in one cycle
        if self._baseline_stable and len(new_ports) >= 3:
            port_list = ", ".join(str(e.local_port) for e in new_ports[:10])
            alerts.append(Alert(
                level=AlertLevel.WARNING,
                port=0,
                proto="*",
                process_name=None,
                pid=None,
                message=f"Burst: {len(new_ports)} new ports in one cycle ({port_list})",
                timestamp=now,
            ))

        return alerts
