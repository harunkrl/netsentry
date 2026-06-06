import logging
import socket
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("kportwatch.rdns")

_MAX_CACHE_SIZE = 1024
_MAX_PENDING = 256

_rdns_cache: OrderedDict[str, str] = OrderedDict()
_pending_lookups: set[str] = set()
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=4)


def get_hostname(ip: str) -> str | None:
    """Get hostname for IP from cache, or trigger a background lookup."""
    with _lock:
        if ip in _rdns_cache:
            # Move to end (most recently used)
            _rdns_cache.move_to_end(ip)
            val = _rdns_cache[ip]
            return val if val else None

        if ip not in _pending_lookups and len(_pending_lookups) < _MAX_PENDING:
            _pending_lookups.add(ip)
            _executor.submit(_do_lookup, ip)

    return None


def _do_lookup(ip: str):
    try:
        hostname, _ = socket.getnameinfo((ip, 0), 0)
        with _lock:
            if hostname != ip:
                _rdns_cache[ip] = hostname
            else:
                _rdns_cache[ip] = ""  # empty string = no hostname found
            # Evict oldest entries if over limit
            while len(_rdns_cache) > _MAX_CACHE_SIZE:
                _rdns_cache.popitem(last=False)
    except Exception as e:
        logger.debug("Failed to resolve %s: %s", ip, e)
        with _lock:
            _rdns_cache[ip] = ""
            while len(_rdns_cache) > _MAX_CACHE_SIZE:
                _rdns_cache.popitem(last=False)
    finally:
        with _lock:
            _pending_lookups.discard(ip)
