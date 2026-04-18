"""In-memory TTL cache for auth payloads.

Wraps ``cachetools.TTLCache`` so downstream code depends on this module
(and this module alone) for cache behaviour. A future swap (LRU, ARC,
per-replica vs shared) touches this file only.

The cache stores ``AuthPayload`` keyed by SHA-256 hex digest of the bearer
token — the same hash used for the DB lookup. No plaintext, no personal
data ever enters the cache.
"""

from __future__ import annotations

from typing import Any, cast

from cachetools import TTLCache

from comadre.keys.models import AuthPayload

AUTH_CACHE_DEFAULT_MAXSIZE = 4096
AUTH_CACHE_DEFAULT_TTL_SECONDS = 60


class AuthCache:
    """TTL cache for ``AuthPayload`` values keyed by token hash.

    ``cachetools.TTLCache`` is not thread-safe on its own. The asyncio
    event loop is single-threaded so we don't need thread-safety today,
    but keeping this wrapper means any lock migration touches one module,
    not every caller.

    ``hits`` / ``misses`` counters are process-local telemetry for Story
    2.3's ``comadre-keys cache-status`` surface.
    """

    def __init__(
        self,
        *,
        maxsize: int = AUTH_CACHE_DEFAULT_MAXSIZE,
        ttl: int = AUTH_CACHE_DEFAULT_TTL_SECONDS,
        timer: Any = None,
    ) -> None:
        if timer is None:
            self._cache: TTLCache[str, AuthPayload] = TTLCache(maxsize=maxsize, ttl=ttl)
        else:
            self._cache = TTLCache(maxsize=maxsize, ttl=ttl, timer=timer)
        self._hits = 0
        self._misses = 0
        self.maxsize = maxsize
        self.ttl = ttl

    def get(self, key_hash: str) -> AuthPayload | None:
        payload = cast("AuthPayload | None", self._cache.get(key_hash))
        if payload is None:
            self._misses += 1
        else:
            self._hits += 1
        return payload

    def set(self, key_hash: str, payload: AuthPayload) -> None:
        self._cache[key_hash] = payload

    def clear(self) -> None:
        self._cache.clear()

    def snapshot(self) -> dict[str, Any]:
        """Return a read-only snapshot for telemetry.

        Story 2.3 reads this via ``comadre-keys cache-status --format json``.
        Story 2.1 exposes the fields but does not wire the CLI.
        """
        return {
            "entries": len(self._cache),
            "maxsize": self.maxsize,
            "ttl_seconds": self.ttl,
            "hits": self._hits,
            "misses": self._misses,
        }
