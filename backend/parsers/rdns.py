"""KPortWatch — Reverse DNS lookup with LRU cache and background resolution.

Provides hostname resolution for remote IP addresses. Uses an in-memory
LRU cache and a thread pool for background DNS lookups.

Backward-compatible API: all module-level functions delegate to a singleton
ReverseDnsService instance.
"""
from __future__ import annotations

import logging
import socket
import threading
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor

logger = logging.getLogger("kportwatch.rdns")

# ── Module-level state (for backward compatibility and test mocking) ──
# These are kept as module-level variables so tests can patch them directly.
_rdns_cache: OrderedDict[str, str] = OrderedDict()
_pending_lookups: set[str] = set()
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=4)
_MAX_CACHE_SIZE = 1024
_MAX_PENDING = 256


class ReverseDnsService:
    """Reverse DNS lookup service with LRU cache and background lookups.

    Encapsulates all state and behavior for DNS hostname resolution,
    including cache management, pending lookups tracking, and thread pool
    coordination.

    For backward compatibility, the service operates on module-level state
    variables that can be accessed and mocked by tests.
    """

    # ── Instance state ─────────────────────────────────────────────
    def __init__(self) -> None:
        """Initialize the reverse DNS service.

        Uses module-level state for backward compatibility.
        """
        # Note: We don't store module-level variables as instance attributes
        # so that test patches to the module-level variables are reflected.

    # ── Configuration ─────────────────────────────────────────────
    def configure(self, *, max_cache_size: int | None = None, max_pending: int | None = None) -> None:
        """Update service configuration for cache and concurrency limits.

        Args:
            max_cache_size: New maximum cache size (None to keep current).
            max_pending: New maximum pending lookups (None to keep current).
        """
        global _MAX_CACHE_SIZE, _MAX_PENDING
        if max_cache_size is not None:
            _MAX_CACHE_SIZE = max_cache_size
        if max_pending is not None:
            _MAX_PENDING = max_pending

    # ── Lifecycle ─────────────────────────────────────────────────
    def shutdown(self) -> None:
        """Gracefully shut down the thread pool executor."""
        _executor.shutdown(wait=False)

    # ── Public API ────────────────────────────────────────────────
    def get_hostname(self, ip: str) -> str | None:
        """Get hostname for IP from cache, or trigger a background lookup.

        Args:
            ip: IP address to resolve.

        Returns:
            Cached hostname if available, None otherwise.
        """
        with _lock:
            if ip in _rdns_cache:
                # Move to end (most recently used)
                _rdns_cache.move_to_end(ip)
                val = _rdns_cache[ip]
                return val if val else None

            if ip not in _pending_lookups and len(_pending_lookups) < _MAX_PENDING:
                _pending_lookups.add(ip)
                _executor.submit(self._do_lookup, ip)

        return None

    # ── Internal lookup implementation ─────────────────────────────
    def _do_lookup(self, ip: str) -> None:
        """Perform the actual DNS lookup.

        Runs in a thread pool worker. Results are cached in _rdns_cache.
        Empty string is cached to indicate "no hostname found" to avoid
        repeated failed lookups.
        """
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


# ── Module-level singleton ─────────────────────────────────────────

_default_service = ReverseDnsService()


# ── Module-level backward-compatible API ────────────────────────────

def configure(*, max_cache_size: int | None = None, max_pending: int | None = None) -> None:
    """Update module-level configuration for cache and concurrency limits.

    Delegates to the singleton ReverseDnsService.

    Args:
        max_cache_size: New maximum cache size (None to keep current).
        max_pending: New maximum pending lookups (None to keep current).
    """
    _default_service.configure(max_cache_size=max_cache_size, max_pending=max_pending)


def shutdown() -> None:
    """Gracefully shut down the thread pool executor.

    Delegates to the singleton ReverseDnsService.
    """
    _default_service.shutdown()


def get_hostname(ip: str) -> str | None:
    """Get hostname for IP from cache, or trigger a background lookup.

    Delegates to the singleton ReverseDnsService.

    Args:
        ip: IP address to resolve.

    Returns:
        Cached hostname if available, None otherwise.
    """
    return _default_service.get_hostname(ip)


# ── Test helper: module-level function for _do_lookup ───────────────

def _do_lookup(ip: str) -> None:
    """Module-level wrapper for _do_lookup (for test mocking)."""
    _default_service._do_lookup(ip)


# ── Test helper: reset singleton for tests ───────────────────────────

def _reset_for_test() -> None:
    """Reset the singleton service and module state (for test fixtures)."""
    global _default_service, _rdns_cache, _pending_lookups, _lock, _executor
    global _MAX_CACHE_SIZE, _MAX_PENDING

    # Clear existing state
    _rdns_cache.clear()
    _pending_lookups.clear()

    # Re-create executor if shut down
    try:
        if _executor is None or _executor._shutdown:
            _executor = ThreadPoolExecutor(max_workers=4)
    except (AttributeError, RuntimeError):
        _executor = ThreadPoolExecutor(max_workers=4)

    # Reset config
    _MAX_CACHE_SIZE = 1024
    _MAX_PENDING = 256

    # Re-create singleton
    _default_service = ReverseDnsService()
