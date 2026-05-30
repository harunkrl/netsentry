import socket
import threading
import logging
from typing import Dict, Optional

logger = logging.getLogger("netsentry.rdns")

_rdns_cache: Dict[str, str] = {}
_pending_lookups: set[str] = set()

def get_hostname(ip: str) -> Optional[str]:
    """Get hostname for IP from cache, or trigger a background lookup."""
    if ip in _rdns_cache:
        return _rdns_cache[ip]
    
    if ip not in _pending_lookups:
        _pending_lookups.add(ip)
        # Run lookup in background to avoid blocking the daemon loop
        threading.Thread(target=_do_lookup, args=(ip,), daemon=True).start()
    
    return None

def _do_lookup(ip: str):
    try:
        hostname, _, _ = socket.getnameinfo((ip, 0), 0)
        # Only store if it resolved to a real name, not just the IP back
        if hostname != ip:
            _rdns_cache[ip] = hostname
        else:
            _rdns_cache[ip] = "" # empty string means no hostname found
    except Exception as e:
        logger.debug("Failed to resolve %s: %s", ip, e)
        _rdns_cache[ip] = ""
    finally:
        _pending_lookups.discard(ip)
