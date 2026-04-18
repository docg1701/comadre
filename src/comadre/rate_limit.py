"""Per-key rate limiting via the ``limits`` library.

2026-04-18 rewrite (FR27 retired, slowapi removed): ``/v1/audio/speech``
enforces one rate-limit bucket per API key, sourced from the registry
row's ``rate_limit_rpm`` column. No per-IP bucket in the application —
reverse-proxy (Caddy) handles any IP-level hygiene.

Flow:
    verify_api_key (dependency)  → sets request.state.auth_payload
    ↓
    check_rate_limit (dependency) → .hit() on key:<key_id> bucket
    ↓
    route handler                  → runs only if both pass

The limiter lives on ``app.state.rate_limiter`` (set in lifespan) so tests
can reset the storage between cases without touching a module-level
singleton.
"""

from __future__ import annotations

from dataclasses import dataclass

from limits import parse
from limits.aio.storage import MemoryStorage
from limits.aio.strategies import MovingWindowRateLimiter
from starlette.requests import Request

from comadre.exceptions import RateLimitError


@dataclass
class RateLimiter:
    """Bundle of the ``limits`` storage + strategy used by the app.

    Held on ``app.state.rate_limiter``. The storage is an in-memory
    sliding-window store; multi-replica deploys see per-replica windows
    (documented in ``docs/rate-limiting.md``).
    """

    storage: MemoryStorage
    strategy: MovingWindowRateLimiter

    @classmethod
    def build(cls) -> RateLimiter:
        storage = MemoryStorage()
        return cls(storage=storage, strategy=MovingWindowRateLimiter(storage))

    async def reset(self) -> None:
        """Clear all buckets. Used by the test suite between cases."""
        await self.storage.reset()


def get_client_ip(request: Request) -> str:
    """Return the real client IP, trusting X-Forwarded-For from Caddy.

    Comadre runs behind Caddy on a Docker bridge network, so
    ``request.client.host`` is the Caddy container IP, not the real client.
    Caddy injects X-Forwarded-For on every reverse-proxy request; its
    leftmost entry is the original client. Fall back to ``request.client.host``
    when the header is absent (unit tests, direct local runs without a proxy).

    Kept after the slowapi removal because the access-log middleware still
    emits the client IP — logs, not rate-limit, are the consumer.
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "127.0.0.1"


async def check_rate_limit(request: Request) -> None:
    """FastAPI dependency — enforce the per-key rate limit.

    Reads ``request.state.auth_payload`` (populated by ``verify_api_key``)
    and the ``RateLimiter`` on ``request.app.state.rate_limiter``. Raises
    ``RateLimitError`` on over-limit; returns ``None`` on allow.

    The bucket identifier is ``key:<key_id>`` — stable across ``rotate-key``
    (same ``key_id``, new plaintext), so a rotated key's new minute-window
    inherits the pre-rotation counts. Zero PII in the bucket key.

    Must be declared AFTER ``Depends(verify_api_key)`` so that
    ``request.state.auth_payload`` is guaranteed set when this runs.
    """
    payload = request.state.auth_payload
    limiter: RateLimiter = request.app.state.rate_limiter
    limit = parse(f"{payload.rate_limit_rpm}/minute")
    bucket = f"key:{payload.key_id}"
    allowed = await limiter.strategy.hit(limit, bucket)
    if not allowed:
        raise RateLimitError(retry_after=60)
