"""KPortWatch — GeoIP lookup with persistent JSON cache and ip-api.com fallback.

Provides geographic information (country, city, lat/lon) for remote IP
addresses. Uses an in-memory LRU cache backed by a persistent JSON file
for offline capability.

Architecture mirrors ``backend.parsers.rdns`` — module-level state,
OrderedDict LRU cache, thread-pool background lookups, lock-based safety.

Uses ipwho.is as primary API (HTTPS, no key required, 10 000 req/month).
Falls back to ip-api.com (HTTP, 45 req/min) if ipwho.is fails.
"""

from __future__ import annotations

import contextlib
import json
import logging
import os
import tempfile
import threading
import time
from collections import OrderedDict
from concurrent.futures import ThreadPoolExecutor
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

from shared.network import is_private_ip

logger = logging.getLogger("kportwatch.geoip")


# ── Service class ──────────────────────────────────────────────────────────


class GeoIpService:
    """Encapsulates GeoIP lookup functionality with thread-safe state.

    Uses an in-memory LRU cache backed by a persistent JSON file.
    Performs background lookups using a thread pool executor.
    """

    # Primary: ipwho.is (HTTPS, free, no key)
    # Fallback: ip-api.com (HTTP, free, 45 req/min)
    _DEFAULT_API_URL = "https://ipwho.is/"
    _FALLBACK_URL = "http://ip-api.com/json/"

    # Default configuration values
    _DEFAULT_CACHE_MAX_ENTRIES = 4096
    _DEFAULT_CACHE_TTL_DAYS = 7
    _DEFAULT_TIMEOUT = 5.0
    _DEFAULT_BATCH_SIZE = 10
    _DEFAULT_MIN_REQUEST_INTERVAL = 1.5  # conservative spacing (~40 req/min)

    # Required keys for cache entries
    _REQUIRED_KEYS = frozenset({"country", "countryCode", "lat", "lon", "cached_at"})

    # Save cache to disk every N successful lookups
    _SAVE_EVERY = 10

    def __init__(self) -> None:
        """Initialize the GeoIP service with default configuration."""
        # ── Mutable state ─────────────────────────────────────────
        self._memory_cache: OrderedDict[str, dict] = OrderedDict()
        self._pending_lookups: set[str] = set()
        self._lock = threading.Lock()
        self._executor = ThreadPoolExecutor(max_workers=2)

        # ── Configurable parameters ────────────────────────────────
        self._api_url: str = self._DEFAULT_API_URL
        self._fallback_url: str = self._FALLBACK_URL
        self._cache_file: str = ""
        self._cache_max_entries: int = self._DEFAULT_CACHE_MAX_ENTRIES
        self._cache_ttl_days: int = self._DEFAULT_CACHE_TTL_DAYS
        self._timeout: float = self._DEFAULT_TIMEOUT
        self._batch_size: int = self._DEFAULT_BATCH_SIZE

        # ── Initialization state ───────────────────────────────────
        self._initialized: bool = False

        # ── Rate-limit tracking ────────────────────────────────────
        self._last_request_time: float = 0.0
        self._min_request_interval: float = self._DEFAULT_MIN_REQUEST_INTERVAL
        self._lookups_since_save: int = 0

    # ── Public API (module-level wrappers delegate to these) ─────

    def init(self, config_dict: dict | None = None) -> None:
        """Configure the GeoIP service and load persistent cache.

        Called once from the daemon at startup.
        """
        if config_dict is None:
            config_dict = {}

        self._api_url = config_dict.get("geoip_api_url", self._api_url)

        # Validate API URL scheme — only HTTPS allowed to prevent SSRF
        from urllib.parse import urlparse as _urlparse

        parsed = _urlparse(self._api_url)
        if parsed.scheme != "https":
            logger.warning(
                "GeoIP API URL '%s' does not use HTTPS — forcing https://ipwho.is/",
                self._api_url,
            )
            self._api_url = self._DEFAULT_API_URL
        elif parsed.hostname in ("localhost", "127.0.0.1", "::1", "0.0.0.0"):
            logger.warning("GeoIP API URL points to localhost — forcing https://ipwho.is/")
            self._api_url = self._DEFAULT_API_URL

        self._cache_file = os.path.expanduser(
            config_dict.get("geoip_cache_file", self._cache_file or "")
        )
        self._cache_max_entries = max(
            1, config_dict.get("geoip_cache_max_entries", self._cache_max_entries)
        )
        self._cache_ttl_days = max(1, config_dict.get("geoip_cache_ttl_days", self._cache_ttl_days))
        self._timeout = max(0.1, config_dict.get("geoip_timeout", self._timeout))
        self._batch_size = max(1, config_dict.get("geoip_batch_size", self._batch_size))

        self._load_cache()
        self._initialized = True
        logger.info("GeoIP module initialised (cache: %d entries)", len(self._memory_cache))

    def shutdown(self) -> None:
        """Gracefully shut down the thread pool executor."""
        self._executor.shutdown(wait=False)

    def flush_cache(self) -> None:
        """Persist in-memory cache to disk. Call on daemon shutdown."""
        with self._lock:
            self._save_cache()

    def get_geoip(self, ip: str) -> dict | None:
        """Look up geographic info for an IP address.

        Returns cached result immediately, or None if not yet available.
        Triggers a background lookup on cache miss.
        """
        if is_private_ip(ip):
            return None

        with self._lock:
            if ip in self._memory_cache:
                entry = self._memory_cache[ip]
                # Check TTL
                age_days = (time.time() - entry.get("cached_at", 0)) / 86400
                if age_days <= self._cache_ttl_days:
                    self._memory_cache.move_to_end(ip)
                    return entry
                # Expired — remove and re-lookup
                del self._memory_cache[ip]

            if ip in self._pending_lookups:
                return None  # already being looked up

            if len(self._pending_lookups) < self._batch_size * 2:
                self._pending_lookups.add(ip)
                self._executor.submit(self._do_lookup, ip)

        return None

    def lookup_batch(self, ips: list[str]) -> dict[str, dict | None]:
        """Look up geographic info for a batch of IPs.

        Returns a dict mapping each IP to its geo info (or None if
        not yet available). Triggers background lookups for uncached IPs.
        """
        results: dict[str, dict | None] = {}

        for ip in ips:
            if is_private_ip(ip):
                continue
            results[ip] = self.get_geoip(ip)

        return results

    # ── Internal methods ─────────────────────────────────────────

    def _load_cache(self) -> None:
        """Load persistent JSON cache from disk into _memory_cache."""
        if not self._cache_file:
            return
        try:
            with open(self._cache_file, encoding="utf-8") as fh:
                data = json.load(fh)
        except FileNotFoundError:
            logger.debug("GeoIP cache file not found: %s", self._cache_file)
            return
        except (json.JSONDecodeError, OSError) as exc:
            logger.warning("Failed to read GeoIP cache: %s", exc)
            return

        if not isinstance(data, dict):
            logger.warning("GeoIP cache has unexpected format, ignoring")
            return

        loaded = 0
        skipped = 0
        for ip_str, entry in data.items():
            if not isinstance(entry, dict):
                skipped += 1
                continue
            # Validate required keys
            if not self._REQUIRED_KEYS.issubset(entry.keys()):
                skipped += 1
                continue
            self._memory_cache[ip_str] = entry
            loaded += 1

        if skipped:
            logger.debug("GeoIP cache: skipped %d invalid entries", skipped)
        logger.info("GeoIP cache: loaded %d entries from %s", loaded, self._cache_file)

    def _save_cache(self) -> None:
        """Atomically write _memory_cache to disk (tmp + os.rename)."""
        if not self._cache_file:
            return
        try:
            cache_dir = os.path.dirname(self._cache_file)
            if cache_dir:
                os.makedirs(cache_dir, exist_ok=True)

            # Atomic write: write to temp file, then rename
            fd, tmp_path = tempfile.mkstemp(
                dir=cache_dir or None,
                prefix=".geoip-cache-",
                suffix=".tmp",
            )
            try:
                with os.fdopen(fd, "w", encoding="utf-8") as fh:
                    json.dump(dict(self._memory_cache), fh, ensure_ascii=False, indent=None)
                os.replace(tmp_path, self._cache_file)
                logger.debug("GeoIP cache saved (%d entries)", len(self._memory_cache))
            except Exception:
                # Clean up temp file on failure
                with contextlib.suppress(OSError):
                    os.unlink(tmp_path)
                raise
        except Exception as exc:
            logger.warning("Failed to save GeoIP cache: %s", exc)

    def _do_lookup(self, ip: str) -> None:
        """Perform a single GeoIP lookup (runs in thread pool).

        Tries ipwho.is (HTTPS) first, falls back to ip-api.com (HTTP).
        """
        # Rate-limit: ensure minimum interval between API requests
        # Entire check + sleep under lock to prevent concurrent requests
        with self._lock:
            elapsed = time.monotonic() - self._last_request_time
            if elapsed < self._min_request_interval:
                time.sleep(self._min_request_interval - elapsed)
            self._last_request_time = time.monotonic()

        geo_info: dict | None = None

        # ── Primary: ipwho.is (HTTPS) ──
        url = f"{self._api_url}{ip}"
        try:
            req = Request(url, headers={"User-Agent": "KPortWatch/2.1"})
            with urlopen(req, timeout=self._timeout) as resp:
                body = json.loads(resp.read().decode("utf-8"))

            if body.get("success", False) is not False:
                geo_info = {
                    "country": body.get("country", ""),
                    "countryCode": body.get("country_code", ""),
                    "city": body.get("city", ""),
                    "lat": body.get("latitude", 0.0),
                    "lon": body.get("longitude", 0.0),
                    "isp": body.get("connection", {}).get("isp", ""),
                    "org": body.get("connection", {}).get("org", ""),
                    "cached_at": time.time(),
                }
            else:
                reason = body.get("message", "unknown")
                logger.debug("GeoIP (ipwho.is) lookup failed for %s: %s", ip, reason)
        except (HTTPError, URLError, OSError, json.JSONDecodeError) as exc:
            logger.debug("GeoIP (ipwho.is) error for %s: %s", ip, exc)
        except Exception as exc:
            logger.debug("GeoIP (ipwho.is) unexpected error for %s: %s", ip, exc)

        # ── Fallback: ip-api.com (HTTP) ──
        if geo_info is None:
            url = f"{self._fallback_url}{ip}?fields=status,message,country,countryCode,city,lat,lon,isp,org"
            try:
                req = Request(url, headers={"User-Agent": "KPortWatch/2.1"})
                with urlopen(req, timeout=self._timeout) as resp:
                    body = json.loads(resp.read().decode("utf-8"))

                if body.get("status") == "success":
                    geo_info = {
                        "country": body.get("country", ""),
                        "countryCode": body.get("countryCode", ""),
                        "city": body.get("city", ""),
                        "lat": body.get("lat", 0.0),
                        "lon": body.get("lon", 0.0),
                        "isp": body.get("isp", ""),
                        "org": body.get("org", ""),
                        "cached_at": time.time(),
                    }
                else:
                    reason = body.get("message", "unknown")
                    logger.debug("GeoIP (ip-api.com fallback) failed for %s: %s", ip, reason)
            except HTTPError as exc:
                if exc.code == 429:
                    logger.warning("GeoIP rate-limited by provider (HTTP 429)")
                else:
                    logger.debug("GeoIP (ip-api.com fallback) HTTP error for %s: %s", ip, exc)
            except (URLError, OSError, json.JSONDecodeError) as exc:
                logger.debug("GeoIP (ip-api.com fallback) error for %s: %s", ip, exc)
            except Exception as exc:
                logger.debug("GeoIP (ip-api.com fallback) unexpected error for %s: %s", ip, exc)

        # Store result in cache
        with self._lock:
            self._last_request_time = time.monotonic()
            if geo_info is not None:
                self._memory_cache[ip] = geo_info
                # Evict oldest entries if over limit
                while len(self._memory_cache) > self._cache_max_entries:
                    self._memory_cache.popitem(last=False)
                self._lookups_since_save += 1
            # Remove from pending set regardless of success/failure
            self._pending_lookups.discard(ip)

            # Periodically persist to disk
            if geo_info is not None and self._lookups_since_save >= self._SAVE_EVERY:
                self._lookups_since_save = 0
                self._save_cache()


# ── Module-level singleton ───────────────────────────────────────────────────

_default_service = GeoIpService()


# ── Module-level attribute proxies for backward compatibility ─────────────
# Tests and callers access geoip_mod._initialized, geoip_mod._api_url, etc.
# These properties delegate to the singleton service instance.


def __getattr__(name: str):
    """Proxy module-level attribute reads to the default service instance."""
    if name.startswith("_") and hasattr(_default_service, name):
        return getattr(_default_service, name)
    raise AttributeError(f"module {__name__!r} has no attribute {name!r}")


# ── Module-level public API (backward-compatible wrappers) ───────────────────


def init(config_dict: dict | None = None) -> None:
    """Configure the GeoIP module and load persistent cache.

    Called once from the daemon at startup.
    """
    _default_service.init(config_dict)


def shutdown() -> None:
    """Gracefully shut down the thread pool executor."""
    _default_service.shutdown()


def flush_cache() -> None:
    """Persist in-memory cache to disk. Call on daemon shutdown."""
    _default_service.flush_cache()


def get_geoip(ip: str) -> dict | None:
    """Look up geographic info for an IP address.

    Returns cached result immediately, or None if not yet available.
    Triggers a background lookup on cache miss.
    """
    return _default_service.get_geoip(ip)


def lookup_batch(ips: list[str]) -> dict[str, dict | None]:
    """Look up geographic info for a batch of IPs.

    Returns a dict mapping each IP to its geo info (or None if
    not yet available). Triggers background lookups for uncached IPs.
    """
    return _default_service.lookup_batch(ips)


# ── Internal access (for tests) ────────────────────────────────
#
# NOTE: Module-level attributes like ``_memory_cache``, ``_initialized``,
# ``_api_url`` … are resolved on demand by the module-level ``__getattr__``
# proxy defined above, which delegates to ``_default_service``. We do *not*
# bind them as module attributes at import time: doing so would snapshot
# immutable values (str/int/bool) at import and leave them stale after a
# later ``init()`` call, because ``__getattr__`` only fires for attributes
# that are *absent* from ``sys.modules[__name__].__dict__``.
#
# Test code accesses the singleton directly via ``geoip_mod._default_service``.


# Expose internal methods for test access
def _do_lookup(ip: str) -> None:
    """Internal method exposed for test access."""
    _default_service._do_lookup(ip)


def _save_cache() -> None:
    """Internal method exposed for test access."""
    _default_service._save_cache()


def _load_cache() -> None:
    """Internal method exposed for test access."""
    _default_service._load_cache()


def _get_default_service() -> GeoIpService:
    """Get the default service instance (for test access)."""
    return _default_service
