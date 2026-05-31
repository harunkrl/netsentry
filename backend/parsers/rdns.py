import socket
import threading
import logging
from typing import Dict, Optional
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("netsentry.rdns")

_rdns_cache: Dict[str, str] = {}
_pending_lookups: set[str] = set()
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=4)

def get_hostname(ip: str) -> Optional[str]:
    """Get hostname for IP from cache, or trigger a background lookup."""
    with _lock:
        if ip in _rdns_cache:
            return _rdns_cache[ip]
        
        if ip not in _pending_lookups:
            _pending_lookups.add(ip)
            # Run lookup in background to avoid blocking the daemon loop
            _executor.submit(_do_lookup, ip)
    
    return None

def _do_lookup(ip: str):
    try:
        hostname, _, _ = socket.getnameinfo((ip, 0), 0)
        # Only store if it resolved to a real name, not just the IP back
        with _lock:
            if len(_rdns_cache) > 1024:
                # Naive eviction: clear cache if too big
                _rdns_cache.clear()
            if hostname != ip:
                _rdns_cache[ip] = hostname
            else:
                _rdns_cache[ip] = "" # empty string means no hostname found
    except Exception as e:
        logger.debug("Failed to resolve %s: %s", ip, e)
        with _lock:
            _rdns_cache[ip] = ""
    finally:
        with _lock:
            _pending_lookups.discard(ip)
