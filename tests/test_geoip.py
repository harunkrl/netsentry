"""NetSentry — Tests for backend.parsers.geoip."""
from __future__ import annotations

import json
import os
import time
from unittest.mock import patch, MagicMock

import pytest

from backend.parsers import geoip as geoip_mod


# ── Fixtures ────────────────────────────────────────────────────

@pytest.fixture(autouse=True)
def _reset_geoip_module():
    """Reset all module-level state before each test."""
    geoip_mod._memory_cache.clear()
    geoip_mod._pending_lookups.clear()
    geoip_mod._initialized = False
    geoip_mod._lookups_since_save = 0
    geoip_mod._last_request_time = 0.0
    # Reset config to defaults
    geoip_mod._api_url = "http://ip-api.com/json/"
    geoip_mod._cache_file = ""
    geoip_mod._cache_max_entries = 4096
    geoip_mod._cache_ttl_days = 7
    geoip_mod._timeout = 5.0
    geoip_mod._batch_size = 10
    yield
    # Cleanup after test
    geoip_mod._memory_cache.clear()
    geoip_mod._pending_lookups.clear()


def _seed_cache(ip: str, country: str = "Turkey", country_code: str = "TR",
                city: str = "Istanbul", lat: float = 41.01, lon: float = 28.98,
                cached_at: float | None = None) -> dict:
    """Add an entry directly to the in-memory cache and return it."""
    entry = {
        "country": country,
        "countryCode": country_code,
        "city": city,
        "lat": lat,
        "lon": lon,
        "isp": "TestISP",
        "cached_at": cached_at or time.time(),
    }
    geoip_mod._memory_cache[ip] = entry
    return entry


# ── Private IP detection ───────────────────────────────────────

class TestPrivateIPDetection:
    def test_loopback_v4(self):
        assert geoip_mod._is_private_ip("127.0.0.1") is True

    def test_loopback_v6(self):
        assert geoip_mod._is_private_ip("::1") is True

    def test_private_10(self):
        assert geoip_mod._is_private_ip("10.0.0.1") is True

    def test_private_172_16(self):
        assert geoip_mod._is_private_ip("172.16.0.1") is True

    def test_private_172_31(self):
        assert geoip_mod._is_private_ip("172.31.255.255") is True

    def test_not_private_172_32(self):
        assert geoip_mod._is_private_ip("172.32.0.1") is False

    def test_private_192_168(self):
        assert geoip_mod._is_private_ip("192.168.1.1") is True

    def test_link_local_169(self):
        assert geoip_mod._is_private_ip("169.254.1.1") is True

    def test_link_local_v6(self):
        assert geoip_mod._is_private_ip("fe80::1") is True

    def test_unspecified_v4(self):
        assert geoip_mod._is_private_ip("0.0.0.0") is True

    def test_unspecified_v6(self):
        assert geoip_mod._is_private_ip("::") is True

    def test_multicast(self):
        assert geoip_mod._is_private_ip("224.0.0.1") is True

    def test_public_google_dns(self):
        assert geoip_mod._is_private_ip("8.8.8.8") is False

    def test_public_cloudflare(self):
        assert geoip_mod._is_private_ip("1.1.1.1") is False

    def test_public_random(self):
        assert geoip_mod._is_private_ip("142.250.80.14") is False

    def test_public_v6(self):
        assert geoip_mod._is_private_ip("2001:4860:4860::8888") is False

    def test_invalid_ip(self):
        assert geoip_mod._is_private_ip("not-an-ip") is True

    def test_empty_string(self):
        assert geoip_mod._is_private_ip("") is True


# ── Cache hit / miss / TTL ─────────────────────────────────────

class TestCacheHit:
    def test_cache_hit_returns_entry(self):
        entry = _seed_cache("8.8.8.8")
        result = geoip_mod.get_geoip("8.8.8.8")
        assert result is not None
        assert result["country"] == "Turkey"
        assert result["countryCode"] == "TR"

    def test_cache_miss_returns_none(self):
        result = geoip_mod.get_geoip("1.1.1.1")
        # Miss triggers background lookup, returns None immediately
        assert result is None

    def test_expired_ttl_triggers_relookup(self):
        # Seed with old timestamp
        old_time = time.time() - 8 * 86400  # 8 days ago
        _seed_cache("8.8.8.8", cached_at=old_time)
        result = geoip_mod.get_geoip("8.8.8.8")
        assert result is None  # expired → treated as miss

    def test_private_ip_returns_none(self):
        result = geoip_mod.get_geoip("192.168.1.1")
        assert result is None

    def test_pending_ip_returns_none(self):
        geoip_mod._pending_lookups.add("1.1.1.1")
        result = geoip_mod.get_geoip("1.1.1.1")
        assert result is None
        # Cleanup
        geoip_mod._pending_lookups.discard("1.1.1.1")


# ── Lookup trigger ─────────────────────────────────────────────

class TestLookupTrigger:
    def test_uncached_ip_submits_background_lookup(self):
        with patch.object(geoip_mod._executor, "submit") as mock_submit:
            geoip_mod.get_geoip("1.1.1.1")
            mock_submit.assert_called_once_with(geoip_mod._do_lookup, "1.1.1.1")

    def test_pending_ip_not_resubmitted(self):
        geoip_mod._pending_lookups.add("1.1.1.1")
        with patch.object(geoip_mod._executor, "submit") as mock_submit:
            geoip_mod.get_geoip("1.1.1.1")
            mock_submit.assert_not_called()
        geoip_mod._pending_lookups.discard("1.1.1.1")


# ── Do lookup (API interaction) ────────────────────────────────

class TestDoLookup:
    def test_successful_lookup_stores_geo(self):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "success",
            "country": "United States",
            "countryCode": "US",
            "city": "Mountain View",
            "lat": 37.386,
            "lon": -122.084,
            "isp": "Google",
            "org": "Google LLC",
        }).encode()
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("backend.parsers.geoip.urlopen", return_value=mock_response):
            geoip_mod._do_lookup("8.8.8.8")

        assert "8.8.8.8" in geoip_mod._memory_cache
        entry = geoip_mod._memory_cache["8.8.8.8"]
        assert entry["country"] == "United States"
        assert entry["countryCode"] == "US"
        assert entry["city"] == "Mountain View"
        assert entry["lat"] == 37.386
        assert entry["lon"] == -122.084

    def test_api_failure_stores_nothing(self):
        from urllib.error import URLError
        with patch("backend.parsers.geoip.urlopen", side_effect=URLError("timeout")):
            geoip_mod._do_lookup("1.1.1.1")

        # Should not be in cache
        assert "1.1.1.1" not in geoip_mod._memory_cache
        # Should be removed from pending
        assert "1.1.1.1" not in geoip_mod._pending_lookups

    def test_api_429_rate_limit(self):
        from urllib.error import HTTPError
        error = HTTPError("url", 429, "Too Many Requests", {}, None)
        with patch("backend.parsers.geoip.urlopen", side_effect=error):
            geoip_mod._do_lookup("1.1.1.1")

        assert "1.1.1.1" not in geoip_mod._memory_cache

    def test_api_returns_fail_status(self):
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "fail",
            "message": "invalid query",
        }).encode()
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("backend.parsers.geoip.urlopen", return_value=mock_response):
            geoip_mod._do_lookup("0.0.0.0")

        assert "0.0.0.0" not in geoip_mod._memory_cache

    def test_pending_cleared_after_lookup(self):
        geoip_mod._pending_lookups.add("9.9.9.9")
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "success",
            "country": "Germany",
            "countryCode": "DE",
            "city": "Berlin",
            "lat": 52.52,
            "lon": 13.405,
            "isp": "Test",
            "org": "Test",
        }).encode()
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("backend.parsers.geoip.urlopen", return_value=mock_response):
            geoip_mod._do_lookup("9.9.9.9")

        assert "9.9.9.9" not in geoip_mod._pending_lookups


# ── LRU eviction ───────────────────────────────────────────────

class TestLRUEviction:
    def test_evicts_oldest_when_over_limit(self):
        geoip_mod._cache_max_entries = 3
        _seed_cache("1.1.1.1")
        _seed_cache("2.2.2.2")
        _seed_cache("3.3.3.3")
        assert len(geoip_mod._memory_cache) == 3

        # Adding one more should evict the oldest (1.1.1.1)
        mock_response = MagicMock()
        mock_response.read.return_value = json.dumps({
            "status": "success", "country": "X", "countryCode": "XX",
            "city": "Y", "lat": 0.0, "lon": 0.0, "isp": "", "org": "",
        }).encode()
        mock_response.__enter__ = lambda s: mock_response
        mock_response.__exit__ = MagicMock(return_value=False)

        with patch("backend.parsers.geoip.urlopen", return_value=mock_response):
            geoip_mod._pending_lookups.add("4.4.4.4")
            geoip_mod._do_lookup("4.4.4.4")

        assert len(geoip_mod._memory_cache) == 3
        assert "1.1.1.1" not in geoip_mod._memory_cache
        assert "4.4.4.4" in geoip_mod._memory_cache


# ── Persistent cache I/O ───────────────────────────────────────

class TestPersistentCache:
    def test_save_and_load(self, tmp_path):
        cache_file = str(tmp_path / "geoip-cache.json")
        geoip_mod._cache_file = cache_file

        _seed_cache("8.8.8.8", country="United States", country_code="US", city="Mountain View")
        _seed_cache("1.1.1.1", country="Australia", country_code="AU", city="Sydney")

        # Save
        geoip_mod._save_cache()
        assert os.path.exists(cache_file)

        # Clear memory and reload
        geoip_mod._memory_cache.clear()
        geoip_mod._load_cache()

        assert len(geoip_mod._memory_cache) == 2
        assert geoip_mod._memory_cache["8.8.8.8"]["country"] == "United States"
        assert geoip_mod._memory_cache["1.1.1.1"]["countryCode"] == "AU"

    def test_load_corrupt_file(self, tmp_path):
        cache_file = str(tmp_path / "geoip-cache.json")
        with open(cache_file, "w") as f:
            f.write("not valid json {{{")
        geoip_mod._cache_file = cache_file
        geoip_mod._load_cache()
        # Should not crash, cache remains empty
        assert len(geoip_mod._memory_cache) == 0

    def test_load_missing_file(self, tmp_path):
        geoip_mod._cache_file = str(tmp_path / "nonexistent.json")
        geoip_mod._load_cache()
        assert len(geoip_mod._memory_cache) == 0

    def test_load_invalid_format(self, tmp_path):
        cache_file = str(tmp_path / "geoip-cache.json")
        with open(cache_file, "w") as f:
            json.dump(["not", "a", "dict"], f)
        geoip_mod._cache_file = cache_file
        geoip_mod._load_cache()
        assert len(geoip_mod._memory_cache) == 0

    def test_load_skips_invalid_entries(self, tmp_path):
        cache_file = str(tmp_path / "geoip-cache.json")
        data = {
            "8.8.8.8": {
                "country": "US", "countryCode": "US", "city": "MV",
                "lat": 37.0, "lon": -122.0, "cached_at": time.time(),
            },
            "1.1.1.1": {"country": "AU"},  # missing required keys
            "bad": "not a dict",
        }
        with open(cache_file, "w") as f:
            json.dump(data, f)
        geoip_mod._cache_file = cache_file
        geoip_mod._load_cache()
        assert len(geoip_mod._memory_cache) == 1
        assert "8.8.8.8" in geoip_mod._memory_cache

    def test_atomic_write_no_partial_on_error(self, tmp_path):
        cache_file = str(tmp_path / "geoip-cache.json")
        geoip_mod._cache_file = cache_file
        _seed_cache("8.8.8.8")

        with patch("json.dump", side_effect=OSError("disk full")):
            geoip_mod._save_cache()

        # Original file should not exist (never created successfully)
        assert not os.path.exists(cache_file)

    def test_flush_cache_calls_save(self, tmp_path):
        cache_file = str(tmp_path / "geoip-cache.json")
        geoip_mod._cache_file = cache_file
        _seed_cache("8.8.8.8")
        geoip_mod.flush_cache()
        assert os.path.exists(cache_file)


# ── Batch lookup ────────────────────────────────────────────────

class TestBatchLookup:
    def test_batch_returns_cached_results(self):
        _seed_cache("8.8.8.8", country="United States")
        _seed_cache("1.1.1.1", country="Australia")

        results = geoip_mod.lookup_batch(["8.8.8.8", "1.1.1.1"])
        assert results["8.8.8.8"]["country"] == "United States"
        assert results["1.1.1.1"]["country"] == "Australia"

    def test_batch_skips_private_ips(self):
        results = geoip_mod.lookup_batch(["192.168.1.1", "10.0.0.1"])
        assert "192.168.1.1" not in results
        assert "10.0.0.1" not in results

    def test_batch_mixed_cached_and_uncached(self):
        _seed_cache("8.8.8.8", country="United States")

        with patch.object(geoip_mod._executor, "submit"):
            results = geoip_mod.lookup_batch(["8.8.8.8", "9.9.9.9"])

        assert results["8.8.8.8"]["country"] == "United States"
        assert results["9.9.9.9"] is None  # uncached

    def test_batch_empty_list(self):
        results = geoip_mod.lookup_batch([])
        assert results == {}


# ── Init ────────────────────────────────────────────────────────

class TestInit:
    def test_init_with_config(self, tmp_path):
        cache_file = str(tmp_path / "geoip-cache.json")
        geoip_mod.init({
            "geoip_api_url": "http://custom-api.example.com/",
            "geoip_cache_file": cache_file,
            "geoip_cache_max_entries": 500,
            "geoip_cache_ttl_days": 14,
            "geoip_batch_size": 5,
            "geoip_timeout": 3.0,
        })
        assert geoip_mod._api_url == "http://custom-api.example.com/"
        assert geoip_mod._cache_max_entries == 500
        assert geoip_mod._cache_ttl_days == 14
        assert geoip_mod._initialized is True

    def test_init_with_none_uses_defaults(self):
        geoip_mod.init(None)
        assert geoip_mod._initialized is True

    def test_init_loads_existing_cache(self, tmp_path):
        cache_file = str(tmp_path / "geoip-cache.json")
        data = {
            "8.8.8.8": {
                "country": "US", "countryCode": "US", "city": "MV",
                "lat": 37.0, "lon": -122.0, "cached_at": time.time(),
            },
        }
        with open(cache_file, "w") as f:
            json.dump(data, f)

        geoip_mod.init({"geoip_cache_file": cache_file})
        assert "8.8.8.8" in geoip_mod._memory_cache
