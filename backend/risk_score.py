"""KPortWatch — Port risk scoring.

Calculates a 0-100 risk score for each listening port based on
multiple factors.  Higher score = more dangerous.

Factors (additive):
  +80   Port is in malicious_ports
  +60   Port is in port_blacklist
  +40   Port is privileged (<1024) and not known-safe
  +25   Port is not in baseline
  +15   Process has no cmdline
  +10   Port is not a well-known service port (>49151)

The score is capped at 100.

Usage::

    from backend.risk_score import calculate_risk_score

    score = calculate_risk_score(entry, engine)
    # score = {"score": 45, "factors": ["privileged", "not_baseline"]}
"""
from __future__ import annotations

from shared.constants import (
    KNOWN_SAFE_PORTS,
    MALICIOUS_PORTS,
    PRIVILEGED_PORT_MAX,
)

from backend.models import SocketEntry


def calculate_risk_score(
    entry: SocketEntry,
    *,
    malicious_ports: set[int] | None = None,
    known_safe_ports: dict[int, str] | None = None,
    baseline_ports: set[int] | None = None,
    port_blacklist: set[int] | None = None,
) -> dict:
    """Calculate risk score and contributing factors for a socket entry.

    Returns:
        {"score": int 0-100, "factors": list of contributing factor names}
    """
    mal_ports = malicious_ports or MALICIOUS_PORTS
    safe_ports = known_safe_ports or KNOWN_SAFE_PORTS
    baseline = baseline_ports or set()
    blacklist = port_blacklist or set()

    score = 0
    factors: list[str] = []

    # Malicious port
    if entry.local_port in mal_ports:
        score += 80
        factors.append("malicious_port")

    # Blacklisted port
    if entry.local_port in blacklist:
        score += 60
        factors.append("blacklisted")

    # Privileged and not known-safe
    if entry.local_port <= PRIVILEGED_PORT_MAX and entry.local_port not in safe_ports:
        score += 40
        factors.append("privileged_unknown")

    # Not in baseline
    if baseline and entry.local_port not in baseline:
        score += 25
        factors.append("not_in_baseline")

    # No cmdline
    if not entry.cmdline:
        score += 15
        factors.append("no_cmdline")

    # Ephemeral port range
    if entry.local_port > 49151:
        score += 10
        factors.append("ephemeral_port")

    return {
        "score": min(score, 100),
        "factors": factors,
    }


def score_entries(
    entries: list[SocketEntry],
    **kwargs,
) -> list[tuple[SocketEntry, dict]]:
    """Score a list of entries, returning (entry, score_dict) pairs sorted by risk."""
    scored = [(e, calculate_risk_score(e, **kwargs)) for e in entries]
    scored.sort(key=lambda x: x[1]["score"], reverse=True)
    return scored
