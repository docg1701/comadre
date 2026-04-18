"""Tests for the ``AuthCache`` wrapper."""

from __future__ import annotations

from comadre.keys.cache import (
    AUTH_CACHE_DEFAULT_MAXSIZE,
    AUTH_CACHE_DEFAULT_TTL_SECONDS,
    AuthCache,
)
from comadre.keys.models import AuthPayload


def _payload(**overrides: object) -> AuthPayload:
    fields: dict[str, object] = {
        "customer_id": "cust_01abc",
        "key_id": "key_01abc",
        "status": "active",
        "billing_mode": "manual",
        "rate_limit_rpm": 60,
        "paid_until": "2099-12-31",
    }
    fields.update(overrides)
    return AuthPayload(**fields)  # type: ignore[arg-type]


class TestAuthCache:
    def test_defaults_match_architecture_constants(self) -> None:
        cache = AuthCache()
        assert cache.maxsize == AUTH_CACHE_DEFAULT_MAXSIZE == 4096
        assert cache.ttl == AUTH_CACHE_DEFAULT_TTL_SECONDS == 60

    def test_get_returns_none_on_miss_and_increments_miss_counter(self) -> None:
        cache = AuthCache()
        assert cache.get("deadbeef") is None
        snap = cache.snapshot()
        assert snap["misses"] == 1
        assert snap["hits"] == 0
        assert snap["entries"] == 0

    def test_set_then_get_returns_payload_and_increments_hit_counter(self) -> None:
        cache = AuthCache()
        payload = _payload()
        cache.set("deadbeef", payload)
        fetched = cache.get("deadbeef")
        assert fetched is payload
        snap = cache.snapshot()
        assert snap["entries"] == 1
        assert snap["hits"] == 1
        assert snap["misses"] == 0

    def test_ttl_expiration_purges_entry(self) -> None:
        clock = {"now": 0.0}

        def fake_timer() -> float:
            return clock["now"]

        cache = AuthCache(maxsize=32, ttl=60, timer=fake_timer)
        cache.set("h1", _payload())
        assert cache.get("h1") is not None

        clock["now"] = 61.0
        assert cache.get("h1") is None
        assert cache.snapshot()["entries"] == 0

    def test_clear_empties_cache_preserves_counters(self) -> None:
        cache = AuthCache()
        cache.set("h1", _payload())
        cache.get("h1")
        cache.get("unknown")
        cache.clear()
        snap = cache.snapshot()
        assert snap["entries"] == 0
        # Counters are process-local telemetry and survive a .clear() — Story
        # 2.3 reads cumulative hits/misses across cache lifetimes.
        assert snap["hits"] == 1
        assert snap["misses"] == 1

    def test_snapshot_shape(self) -> None:
        cache = AuthCache()
        snap = cache.snapshot()
        assert set(snap.keys()) == {
            "entries",
            "maxsize",
            "ttl_seconds",
            "hits",
            "misses",
        }
        # No keys/values leak.
        for forbidden in ("keys", "values", "items"):
            assert forbidden not in snap

    def test_overwrite_keeps_entries_count(self) -> None:
        cache = AuthCache()
        cache.set("h1", _payload())
        cache.set("h1", _payload(rate_limit_rpm=120))
        assert cache.snapshot()["entries"] == 1
        fetched = cache.get("h1")
        assert fetched is not None
        assert fetched.rate_limit_rpm == 120
