"""KPortWatch — Shared network utilities.

Consolidates network-related helpers used across backend modules:
  - is_private_ip: comprehensive private/loopback/reserved IP check
"""

from __future__ import annotations

import ipaddress
import logging

logger = logging.getLogger(__name__)


def is_private_ip(ip: str) -> bool:
    """Return True for loopback, private, link-local, and reserved IPs.

    Covers all RFC 1918 ranges (10.x, 172.16-31.x, 192.168.x),
    loopback (127.x, ::1), link-local (169.254.x, fe80::),
    and other reserved addresses.

    Uses ``ipaddress`` stdlib for correctness — no string prefix checks.

    Returns True for unparseable strings as well. This is a deliberate
    *fail-safe*: the only callers use this as a short-circuit to *skip*
    GeoIP/rDNS enrichment, so treating an invalid IP as "do not enrich"
    avoids sending garbage to an external API (SSRF/injection surface).
    It never gates alerting, kill, or visibility decisions.
    """
    try:
        addr = ipaddress.ip_address(ip)
        return (
            addr.is_loopback
            or addr.is_private
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_multicast
        )
    except ValueError:
        # Unparseable address: skip enrichment rather than risk sending it
        # to an external GeoIP endpoint. Logged for diagnosis.
        logger.debug("Treating unparseable IP %r as private (skipping enrichment)", ip)
        return True
