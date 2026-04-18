"""In-memory TTL cache for auth payloads with cross-process invalidation.

Wraps ``cachetools.TTLCache`` so downstream code depends on this module
(and this module alone) for cache behaviour. A future swap (LRU, ARC,
per-replica vs shared) touches this file only.

The cache stores ``AuthPayload`` keyed by SHA-256 hex digest of the bearer
token — the same hash used for the DB lookup. No plaintext, no personal
data ever enters the cache.

Cross-process invalidation via a filesystem sentinel — the CLI process
(``comadre-keys update-key``, ``rotate-key``, ``revoke-key``) touches
``{registry_db_path}.invalidate`` on every mutation. The API checks the
sentinel's mtime on every cache read; if it advanced since the last
check, the whole cache is flushed. A revoked key stops authenticating on
the very next request — no 60-second TTL window.
"""

from __future__ import annotations

from pathlib import Path
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
        invalidation_sentinel: Path | None = None,
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
        self._sentinel = invalidation_sentinel
        self._sentinel_mtime_ns = self._read_sentinel_mtime()

    def _read_sentinel_mtime(self) -> int:
        """Return the sentinel file's mtime in ns, or 0 if absent."""
        if self._sentinel is None:
            return 0
        try:
            return self._sentinel.stat().st_mtime_ns
        except FileNotFoundError:
            return 0

    def _flush_if_invalidated(self) -> None:
        """Flush the cache if a CLI mutation advanced the sentinel mtime.

        Uses ``>`` rather than ``!=`` so clock-rollback (NTP step-back,
        container clock drift) doesn't trigger spurious cache flushes.
        Same-tick collisions on coarse-mtime filesystems (FAT32, some
        overlay FS) are a known limitation tracked in deferred-work.
        """
        if self._sentinel is None:
            return
        current = self._read_sentinel_mtime()
        if current > self._sentinel_mtime_ns:
            self._cache.clear()
            self._sentinel_mtime_ns = current

    def get(self, key_hash: str) -> AuthPayload | None:
        self._flush_if_invalidated()
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
        """
        return {
            "entries": len(self._cache),
            "maxsize": self.maxsize,
            "ttl_seconds": self.ttl,
            "hits": self._hits,
            "misses": self._misses,
        }
