"""Tests for backend.parsers.rdns — DNS resolution with LRU cache."""

from __future__ import annotations

import threading
from unittest.mock import patch

import pytest
from backend.parsers import rdns

# ── Fixtures ──────────────────────────────────────────────────────


@pytest.fixture(autouse=True)
def _reset_rdns_state():
    """Clear global rdns state before and after each test."""
    with rdns._lock:
        rdns._rdns_cache.clear()
        rdns._pending_lookups.clear()
    yield
    with rdns._lock:
        rdns._rdns_cache.clear()
        rdns._pending_lookups.clear()
    # Re-init executor if shut down by another test
    from concurrent.futures import ThreadPoolExecutor

    try:
        if rdns._executor is None or rdns._executor._shutdown:
            rdns._executor = ThreadPoolExecutor(max_workers=1)
    except (AttributeError, RuntimeError):
        rdns._executor = ThreadPoolExecutor(max_workers=1)


def _seed_cache(entries: dict[str, str]) -> None:
    """Pre-populate the rdns cache."""
    with rdns._lock:
        for ip, hostname in entries.items():
            rdns._rdns_cache[ip] = hostname


# ── Cache hit tests ───────────────────────────────────────────────


class TestCacheHit:
    def test_cached_hostname_returned(self):
        _seed_cache({"1.2.3.4": "host.example.com"})
        result = rdns.get_hostname("1.2.3.4")
        assert result == "host.example.com"

    def test_cached_empty_string_returns_none(self):
        """Empty string in cache means 'no hostname found'."""
        _seed_cache({"1.2.3.4": ""})
        result = rdns.get_hostname("1.2.3.4")
        assert result is None

    def test_uncached_ip_returns_none(self):
        result = rdns.get_hostname("10.0.0.1")
        assert result is None

    def test_cache_hit_moves_to_end_lru(self):
        """Accessing a cached entry should move it to the end (most recent)."""
        _seed_cache(
            {
                "1.1.1.1": "one",
                "2.2.2.2": "two",
                "3.3.3.3": "three",
            }
        )
        # Access "1.1.1.1" — should move to end
        rdns.get_hostname("1.1.1.1")
        keys = list(rdns._rdns_cache.keys())
        assert keys[-1] == "1.1.1.1"


# ── Lookup trigger tests ──────────────────────────────────────────


class TestLookupTrigger:
    def test_uncached_ip_triggers_background_lookup(self):
        with patch("backend.parsers.rdns._executor") as mock_exec:
            rdns.get_hostname("10.0.0.1")
            mock_exec.submit.assert_called_once()
            # IP should be in pending set
            assert "10.0.0.1" in rdns._pending_lookups

    def test_pending_ip_not_double_submitted(self):
        with patch("backend.parsers.rdns._executor") as mock_exec:
            rdns._pending_lookups.add("10.0.0.1")
            rdns.get_hostname("10.0.0.1")
            mock_exec.submit.assert_not_called()

    def test_pending_limit_respected(self):
        """When pending set is full, new lookups should not be submitted."""
        # Fill pending set to max
        for i in range(rdns._MAX_PENDING):
            rdns._pending_lookups.add(f"10.0.0.{i}")

        with patch("backend.parsers.rdns._executor") as mock_exec:
            rdns.get_hostname("99.99.99.99")
            mock_exec.submit.assert_not_called()


# ── _do_lookup tests ──────────────────────────────────────────────


class TestDoLookup:
    def test_successful_lookup_stores_hostname(self):
        with patch("socket.getnameinfo", return_value=("host.example.com", "0")):
            rdns._do_lookup("1.2.3.4")
        assert rdns._rdns_cache["1.2.3.4"] == "host.example.com"

    def test_ip_returned_unchanged_stores_empty(self):
        """If DNS returns the IP itself, store empty string."""
        with patch("socket.getnameinfo", return_value=("1.2.3.4", "0")):
            rdns._do_lookup("1.2.3.4")
        assert rdns._rdns_cache["1.2.3.4"] == ""

    def test_failed_lookup_stores_empty(self):
        with patch("socket.getnameinfo", side_effect=Exception("DNS fail")):
            rdns._do_lookup("1.2.3.4")
        assert rdns._rdns_cache["1.2.3.4"] == ""

    def test_pending_cleared_after_lookup(self):
        rdns._pending_lookups.add("1.2.3.4")
        with patch("socket.getnameinfo", return_value=("host.example.com", "0")):
            rdns._do_lookup("1.2.3.4")
        assert "1.2.3.4" not in rdns._pending_lookups

    def test_pending_cleared_even_on_failure(self):
        rdns._pending_lookups.add("1.2.3.4")
        with patch("socket.getnameinfo", side_effect=Exception("fail")):
            rdns._do_lookup("1.2.3.4")
        assert "1.2.3.4" not in rdns._pending_lookups


# ── LRU eviction tests ────────────────────────────────────────────


class TestLRUEviction:
    def test_cache_evicts_when_over_limit(self):
        """When cache exceeds _MAX_CACHE_SIZE, oldest entries should be evicted."""
        # Fill cache to limit
        for i in range(rdns._MAX_CACHE_SIZE + 10):
            rdns._rdns_cache[f"10.0.{i // 256}.{i % 256}"] = f"host-{i}"

        # Now do a lookup that adds to cache (will trigger eviction)
        with patch("socket.getnameinfo", return_value=("new-host", "0")):
            rdns._do_lookup("99.99.99.99")

        assert len(rdns._rdns_cache) <= rdns._MAX_CACHE_SIZE
        # Newest entry should survive
        assert "99.99.99.99" in rdns._rdns_cache

    def test_eviction_on_failed_lookup(self):
        """Eviction should also happen when lookup fails."""
        for i in range(rdns._MAX_CACHE_SIZE + 5):
            rdns._rdns_cache[f"10.0.{i // 256}.{i % 256}"] = f"host-{i}"

        with patch("socket.getnameinfo", side_effect=Exception("fail")):
            rdns._do_lookup("99.99.99.99")

        assert len(rdns._rdns_cache) <= rdns._MAX_CACHE_SIZE


# ── Thread safety test ────────────────────────────────────────────


class TestThreadSafety:
    def test_concurrent_lookups_no_crash(self):
        """Multiple threads doing lookups simultaneously should not crash."""
        errors: list[str] = []

        def lookup_ip(ip: str):
            try:
                with patch("socket.getnameinfo", return_value=(f"host-{ip}", "0")):
                    rdns._do_lookup(ip)
            except Exception as e:
                errors.append(str(e))

        threads = [threading.Thread(target=lookup_ip, args=(f"10.0.0.{i}",)) for i in range(50)]
        for t in threads:
            t.start()
        for t in threads:
            t.join()

        assert not errors
        assert len(rdns._rdns_cache) == 50
