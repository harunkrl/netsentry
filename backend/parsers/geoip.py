"""KPortWatch — GeoIP lookup with persistent JSON cache and ip-api.com fallback.

Provides geographic information (country, city, lat/lon) for remote IP
addresses. Uses an in-memory LRU cache backed by a persistent JSON file
for offline capability.

Architecture mirrors ``backend.parsers.rdns`` — module-level state,
OrderedDict LRU cache, thread-pool background lookups, lock-based safety.

ip-api.com free tier: 45 requests/minute (HTTP, no key required).
"""
from __future__ import annotations

import contextlib
import ipaddress
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

logger = logging.getLogger("kportwatch.geoip")

# ── Module-level state ──────────────────────────────────────────
_memory_cache: OrderedDict[str, dict] = OrderedDict()
_pending_lookups: set[str] = set()
_lock = threading.Lock()
_executor = ThreadPoolExecutor(max_workers=2)

# ── Configurable parameters (set via init()) ────────────────────
_api_url: str = "http://ip-api.com/json/"
_cache_file: str = ""
_cache_max_entries: int = 4096
_cache_ttl_days: int = 7
_timeout: float = 5.0
_batch_size: int = 10
_initialized: bool = False

# ── Rate-limit tracking ────────────────────────────────────────
_last_request_time: float = 0.0
_min_request_interval: float = 1.5  # 45 req/min ≈ 1.33s, use 1.5s for safety
_lookups_since_save: int = 0
_SAVE_EVERY: int = 10  # persist cache to disk every N successful lookups


# ── Private IP detection ───────────────────────────────────────

def _is_private_ip(ip: str) -> bool:
    """Return True for loopback, private, link-local, and reserved IPs."""
    try:
        addr = ipaddress.ip_address(ip)
        return (
            addr.is_loopback
            or addr.is_private
            or addr.is_link_local
            or addr.is_reserved
            or addr.is_unspecified
            or addr.is_multicast
        )
    except ValueError:
        return True  # unparseable → skip


# ── Persistent cache I/O ───────────────────────────────────────

_REQUIRED_KEYS = frozenset({"country", "countryCode", "lat", "lon", "cached_at"})


def _load_cache() -> None:
    """Load persistent JSON cache from disk into _memory_cache."""
    if not _cache_file:
        return
    try:
        with open(_cache_file, encoding="utf-8") as fh:
            data = json.load(fh)
    except FileNotFoundError:
        logger.debug("GeoIP cache file not found: %s", _cache_file)
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
        if not _REQUIRED_KEYS.issubset(entry.keys()):
            skipped += 1
            continue
        _memory_cache[ip_str] = entry
        loaded += 1

    if skipped:
        logger.debug("GeoIP cache: skipped %d invalid entries", skipped)
    logger.info("GeoIP cache: loaded %d entries from %s", loaded, _cache_file)


def _save_cache() -> None:
    """Atomically write _memory_cache to disk (tmp + os.rename)."""
    if not _cache_file:
        return
    try:
        cache_dir = os.path.dirname(_cache_file)
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
                json.dump(dict(_memory_cache), fh, ensure_ascii=False, indent=None)
            os.replace(tmp_path, _cache_file)
            logger.debug("GeoIP cache saved (%d entries)", len(_memory_cache))
        except Exception:
            # Clean up temp file on failure
            with contextlib.suppress(OSError):
                os.unlink(tmp_path)
            raise
    except Exception as exc:
        logger.warning("Failed to save GeoIP cache: %s", exc)


# ── Initialisation ─────────────────────────────────────────────

def init(config_dict: dict | None = None) -> None:
    """Configure the GeoIP module and load persistent cache.

    Called once from the daemon at startup.
    """
    global _api_url, _cache_file, _cache_max_entries, _cache_ttl_days
    global _timeout, _batch_size, _initialized

    if config_dict is None:
        config_dict = {}

    _api_url = config_dict.get("geoip_api_url", _api_url)
    _cache_file = os.path.expanduser(
        config_dict.get("geoip_cache_file", _cache_file or "")
    )
    _cache_max_entries = max(1, config_dict.get("geoip_cache_max_entries", _cache_max_entries))
    _cache_ttl_days = max(1, config_dict.get("geoip_cache_ttl_days", _cache_ttl_days))
    _timeout = max(0.1, config_dict.get("geoip_timeout", _timeout))
    _batch_size = max(1, config_dict.get("geoip_batch_size", _batch_size))

    _load_cache()
    _initialized = True
    logger.info("GeoIP module initialised (cache: %d entries)", len(_memory_cache))


def flush_cache() -> None:
    """Persist in-memory cache to disk. Call on daemon shutdown."""
    with _lock:
        _save_cache()


# ── Background lookup ──────────────────────────────────────────

def _do_lookup(ip: str) -> None:
    """Perform a single GeoIP lookup via ip-api.com (runs in thread pool)."""
    global _last_request_time, _lookups_since_save

    # Rate-limit: ensure minimum interval between API requests
    with _lock:
        last = _last_request_time
    elapsed = time.monotonic() - last
    if elapsed < _min_request_interval:
        time.sleep(_min_request_interval - elapsed)

    url = f"{_api_url}{ip}?fields=status,message,country,countryCode,city,lat,lon,isp,org"

    geo_info: dict | None = None
    try:
        req = Request(url, headers={"User-Agent": "KPortWatch/2.1"})
        with urlopen(req, timeout=_timeout) as resp:
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
            logger.debug("GeoIP lookup failed for %s: %s", ip, reason)
    except HTTPError as exc:
        if exc.code == 429:
            logger.warning("GeoIP rate-limited by ip-api.com (429)")
        else:
            logger.debug("GeoIP HTTP error for %s: %s", ip, exc)
    except (URLError, OSError, json.JSONDecodeError) as exc:
        logger.debug("GeoIP lookup error for %s: %s", ip, exc)
    except Exception as exc:
        logger.debug("GeoIP unexpected error for %s: %s", ip, exc)

    # Store result in cache
    with _lock:
        _last_request_time = time.monotonic()
        if geo_info is not None:
            _memory_cache[ip] = geo_info
            # Evict oldest entries if over limit
            while len(_memory_cache) > _cache_max_entries:
                _memory_cache.popitem(last=False)
            _lookups_since_save += 1
        # Remove from pending set regardless of success/failure
        _pending_lookups.discard(ip)

        # Periodically persist to disk
        if geo_info is not None and _lookups_since_save >= _SAVE_EVERY:
            _lookups_since_save = 0
            _save_cache()


# ── Public API ─────────────────────────────────────────────────

def get_geoip(ip: str) -> dict | None:
    """Look up geographic info for an IP address.

    Returns cached result immediately, or None if not yet available.
    Triggers a background lookup on cache miss.
    """
    if _is_private_ip(ip):
        return None

    with _lock:
        if ip in _memory_cache:
            entry = _memory_cache[ip]
            # Check TTL
            age_days = (time.time() - entry.get("cached_at", 0)) / 86400
            if age_days <= _cache_ttl_days:
                _memory_cache.move_to_end(ip)
                return entry
            # Expired — remove and re-lookup
            del _memory_cache[ip]

        if ip in _pending_lookups:
            return None  # already being looked up

        if len(_pending_lookups) < _batch_size * 2:
            _pending_lookups.add(ip)
            _executor.submit(_do_lookup, ip)

    return None


def lookup_batch(ips: list[str]) -> dict[str, dict | None]:
    """Look up geographic info for a batch of IPs.

    Returns a dict mapping each IP to its geo info (or None if
    not yet available). Triggers background lookups for uncached IPs.
    """
    results: dict[str, dict | None] = {}

    for ip in ips:
        if _is_private_ip(ip):
            continue
        results[ip] = get_geoip(ip)

    return results
