"""KPortWatch — Alert engine with baseline learning.

Built-in alert rules:
  0. Port in blacklist                    → CRITICAL
  1. Port in MALICIOUS_PORTS              → CRITICAL
  2. Port < 1024, not known-safe, not baseline → WARNING
  3. New listening port not in baseline   → INFO
  4. Process with no cmdline              → WARNING
  5. N+ new ports in one cycle            → WARNING
  6. Custom user rules (from config)      → user-defined level
"""
from __future__ import annotations

import hashlib
import json
import logging
import time
from pathlib import Path

log = logging.getLogger(__name__)

from shared import (
    BASELINE_FILE,
    KNOWN_SAFE_PORTS,
    MALICIOUS_PORTS,
    PRIVILEGED_PORT_MAX,
    AlertLevel,
)
from shared.config import CustomRule
from shared.fs_utils import atomic_write

from backend.models import Alert, SocketEntry


class AlertEngine:
    """Generates security alerts based on socket entries and a learned baseline."""

    def __init__(
        self,
        known_safe_ports: dict[int, str] | None = None,
        baseline_duration: float = 300.0,
        malicious_ports: set[int] | None = None,
        burst_threshold: int = 3,
        privileged_port_max: int = PRIVILEGED_PORT_MAX,
        custom_rules: list[CustomRule] | None = None,
        port_whitelist: set[int] | None = None,
        port_blacklist: set[int] | None = None,
        ip_blacklist: list[str] | None = None,
    ) -> None:
        self.known_safe: dict[int, str] = dict(known_safe_ports or KNOWN_SAFE_PORTS)
        self.baseline_duration = baseline_duration
        self.malicious_ports: set[int] = set(malicious_ports or MALICIOUS_PORTS)
        self.burst_threshold = burst_threshold
        self.privileged_port_max = privileged_port_max
        self.custom_rules: list[CustomRule] = list(custom_rules or [])
        self.port_whitelist: set[int] = set(port_whitelist or set())
        self.port_blacklist: set[int] = set(port_blacklist or set())
        self.ip_blacklist: list[str] = list(ip_blacklist or [])
        self._baseline_ports: set[int] = set()
        self._baseline_start: float | None = None
        self._baseline_stable = False
        self._last_ports: set[int] | None = None

    def reset_baseline(self) -> None:
        """Reset the baseline to start learning again."""
        self._baseline_ports.clear()
        self._baseline_start = None
        self._baseline_stable = False
        self._last_ports = None

    # ── Baseline management ────────────────────────────────────

    def update_baseline(self, entries: list[SocketEntry]) -> None:
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
            # Treat _last_ports=None as "first measurement" — always stable match
            if self._last_ports is None or current_ports == self._last_ports:
                self._baseline_stable = True
            self._last_ports = current_ports

    def is_baseline_complete(self) -> bool:
        """Return True once the baseline learning period has finished."""
        return self._baseline_stable

    def get_baseline_ports(self) -> frozenset[int]:
        """Return the learned baseline port set (read-only)."""
        return frozenset(self._baseline_ports)

    def save_baseline(self, path: str | None = None) -> None:
        """Persist the baseline port set to disk with SHA-256 checksum."""
        path = path or BASELINE_FILE
        payload = json.dumps({
            "ports": sorted(self._baseline_ports),
            "timestamp": time.time(),
        }, indent=2)
        atomic_write(path, payload)

        # Write integrity checksum
        checksum = hashlib.sha256(payload.encode()).hexdigest()
        checksum_path = path + ".sha256"
        try:
            atomic_write(checksum_path, checksum)
        except OSError:
            log.warning("Failed to write baseline checksum to %s", checksum_path)

    def load_baseline(self, path: str | None = None) -> bool:
        """Load a previously saved baseline. Returns True on success.

        Validates SHA-256 checksum if a .sha256 file exists.  A mismatch
        causes the baseline to be rebuilt from scratch.
        """
        path = path or BASELINE_FILE
        try:
            raw = Path(path).read_bytes()

            # Integrity check
            checksum_path = path + ".sha256"
            checksum_file = Path(checksum_path)
            if checksum_file.exists():
                expected = checksum_file.read_text().strip()
                actual = hashlib.sha256(raw).hexdigest()
                if actual != expected:
                    log.warning(
                        "Baseline checksum mismatch (%s) — rebuilding baseline",
                        path,
                    )
                    return False

            data = json.loads(raw)

            # Validate schema: must have "ports" as a list of ints
            ports = data.get("ports")
            if not isinstance(ports, list):
                return False
            validated_ports: set[int] = set()
            for p in ports:
                if isinstance(p, int) and 0 <= p <= 65535:
                    validated_ports.add(p)

            self._baseline_ports = validated_ports
            self._baseline_stable = True
            self._baseline_start = data.get("timestamp", time.time())
            return True
        except (FileNotFoundError, json.JSONDecodeError, OSError, TypeError):
            return False

    # ── Analysis ───────────────────────────────────────────────

    def analyze(self, entries: list[SocketEntry]) -> list[Alert]:
        """Run all alert rules against the provided listening socket entries.

        Also feeds the entries into baseline learning.
        """
        self.update_baseline(entries)

        alerts: list[Alert] = []
        now = time.time()

        current_ports: set[int] = set()
        new_ports: list[SocketEntry] = []

        for entry in entries:
            port = entry.local_port
            current_ports.add(port)

            is_known_safe = port in self.known_safe
            is_baseline = port in self._baseline_ports

            # Skip whitelisted ports entirely
            if port in self.port_whitelist:
                continue

            # Rule 0: Blacklisted port → always CRITICAL
            if port in self.port_blacklist:
                alerts.append(Alert(
                    level=AlertLevel.CRITICAL,
                    port=port,
                    proto=entry.proto,
                    process_name=entry.process_name,
                    pid=entry.pid,
                    message=f"Blacklisted port {port} detected ({entry.process_name or 'unknown'})",
                    timestamp=now,
                ))
                continue

            # Rule 0b: Blacklisted IP → always CRITICAL
            if entry.remote_ip and self.ip_blacklist:
                from fnmatch import fnmatch
                for pattern in self.ip_blacklist:
                    if fnmatch(entry.remote_ip, pattern):
                        alerts.append(Alert(
                            level=AlertLevel.CRITICAL,
                            port=port,
                            proto=entry.proto,
                            process_name=entry.process_name,
                            pid=entry.pid,
                            message=f"Blacklisted IP {entry.remote_ip} connected on port {port}",
                            timestamp=now,
                        ))
                        break

            # Rule 1: Malicious port
            if port in self.malicious_ports:
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
            if port <= self.privileged_port_max and not is_known_safe and not is_baseline:
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

        # Rule 5: Burst — N+ new ports in one cycle
        if self._baseline_stable and len(new_ports) >= self.burst_threshold:
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

        # Rule 6: Custom user rules
        for rule in self.custom_rules:
            for entry in entries:
                if rule.matches(entry):
                    level = AlertLevel(rule.level)
                    alerts.append(Alert(
                        level=level,
                        port=entry.local_port,
                        proto=entry.proto,
                        process_name=entry.process_name,
                        pid=entry.pid,
                        message=rule.message,
                        timestamp=now,
                    ))

        return alerts
