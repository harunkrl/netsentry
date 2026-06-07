"""KPortWatch — Shared network utilities.

Consolidates network-related helpers used across backend modules:
  - is_private_ip: comprehensive private/loopback/reserved IP check
"""
from __future__ import annotations

import ipaddress


def is_private_ip(ip: str) -> bool:
    """Return True for loopback, private, link-local, and reserved IPs.

    Covers all RFC 1918 ranges (10.x, 172.16–31.x, 192.168.x),
    loopback (127.x, ::1), link-local (169.254.x, fe80::),
    and other reserved addresses.

    Uses ``ipaddress`` stdlib for correctness — no string prefix checks.
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
        return True  # treat unparseable IPs as private (skip enrichment)
