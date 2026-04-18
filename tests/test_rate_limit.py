"""Tests for ``comadre.rate_limit``.

Covers the X-Forwarded-For aware ``get_client_ip`` helper (used by the
access-log middleware) and the ``check_rate_limit`` FastAPI dependency
(per-key bucket enforcement via the ``limits`` library).
"""

from __future__ import annotations

import asyncio
from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from comadre.exceptions import KeyRegistryError, RateLimitError
from comadre.keys.models import AuthPayload
from comadre.rate_limit import RateLimiter, check_rate_limit, get_client_ip


def _build_request(
    headers: dict[str, str] | None = None,
    client_host: str | None = None,
    *,
    auth_payload: AuthPayload | None = None,
    rate_limiter: RateLimiter | None = None,
    with_rate_limiter_attr: bool = True,
) -> Request:
    """Build a minimal Starlette Request for unit-testing rate_limit helpers."""
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in (headers or {}).items()]
    scope: dict[str, Any] = {
        "type": "http",
        "method": "POST",
        "path": "/v1/audio/speech",
        "headers": raw_headers,
        "client": (client_host, 12345) if client_host else None,
    }
    state_kwargs: dict[str, Any] = {}
    if with_rate_limiter_attr:
        state_kwargs["rate_limiter"] = rate_limiter
    scope["app"] = SimpleNamespace(state=SimpleNamespace(**state_kwargs))
    request = Request(scope)
    if auth_payload is not None:
        request.state.auth_payload = auth_payload
    return request


def _payload(
    *,
    key_id: str = "key_01hf3abcdefghjkmnpqrstvwxy",
    rate_limit_rpm: int = 60,
) -> AuthPayload:
    return AuthPayload(
        customer_id="cust_01hf3abcdefghjkmnpqrstvwxy",
        key_id=key_id,
        status="active",
        billing_mode="manual",
        rate_limit_rpm=rate_limit_rpm,
        paid_until="2099-12-31",
    )


class TestGetClientIp:
    def test_x_forwarded_for_takes_precedence(self) -> None:
        req = _build_request(
            headers={"x-forwarded-for": "203.0.113.10"},
            client_host="10.0.0.1",
        )
        assert get_client_ip(req) == "203.0.113.10"

    def test_leftmost_ip_from_comma_list(self) -> None:
        req = _build_request(
            headers={"x-forwarded-for": "203.0.113.10, 10.0.0.1, 10.0.0.2"},
            client_host="10.0.0.1",
        )
        assert get_client_ip(req) == "203.0.113.10"

    def test_fallback_to_request_client(self) -> None:
        req = _build_request(headers={}, client_host="198.51.100.5")
        assert get_client_ip(req) == "198.51.100.5"

    def test_fallback_to_loopback_when_no_client(self) -> None:
        req = _build_request(headers={}, client_host=None)
        assert get_client_ip(req) == "127.0.0.1"

    def test_strips_whitespace_from_leftmost(self) -> None:
        req = _build_request(
            headers={"x-forwarded-for": "  203.0.113.10  "},
            client_host=None,
        )
        assert get_client_ip(req) == "203.0.113.10"


class TestRateLimiterBuild:
    """Smoke tests for ``RateLimiter.build`` — verify the bundle wiring."""

    async def test_build_returns_working_limiter(self) -> None:
        rl = RateLimiter.build()
        assert rl.storage is not None
        assert rl.strategy is not None

    async def test_reset_clears_buckets(self) -> None:
        rl = RateLimiter.build()
        payload = _payload(rate_limit_rpm=1)
        # Separate Request objects — ``request.state`` is not reusable
        # between calls because the second call would find stale
        # ``rate_limit_headers`` from the first.
        req1 = _build_request(auth_payload=payload, rate_limiter=rl)
        await check_rate_limit(req1)  # consumes the only slot
        await rl.reset()
        req2 = _build_request(auth_payload=payload, rate_limiter=rl)
        await check_rate_limit(req2)  # same key passes after reset


class TestCheckRateLimit:
    """Per-key rate-limit dependency — allow, trip, bucket isolation, headers."""

    @pytest.fixture()
    async def rate_limiter(self) -> RateLimiter:
        return RateLimiter.build()

    async def test_allows_up_to_rpm_requests(self, rate_limiter: RateLimiter) -> None:
        payload = _payload(rate_limit_rpm=3)
        req = _build_request(auth_payload=payload, rate_limiter=rate_limiter)
        for _ in range(3):
            await check_rate_limit(req)

    async def test_x_ratelimit_headers_on_allow(
        self, rate_limiter: RateLimiter
    ) -> None:
        payload = _payload(rate_limit_rpm=3)
        req = _build_request(auth_payload=payload, rate_limiter=rate_limiter)
        await check_rate_limit(req)
        # ``check_rate_limit`` stashes header values on ``request.state``
        # so the app's rate-limit-headers middleware can merge them onto
        # the outbound response — see ``apply_rate_limit_headers`` in
        # ``main.py`` for the integration-level channel.
        headers = req.state.rate_limit_headers
        assert headers["X-RateLimit-Limit"] == "3"
        assert headers["X-RateLimit-Remaining"] == "2"
        assert int(headers["X-RateLimit-Reset"]) > 0

    async def test_trips_on_rpm_plus_one(self, rate_limiter: RateLimiter) -> None:
        payload = _payload(rate_limit_rpm=2)
        req = _build_request(auth_payload=payload, rate_limiter=rate_limiter)
        await check_rate_limit(req)
        await check_rate_limit(req)
        with pytest.raises(RateLimitError) as exc:
            await check_rate_limit(req)
        assert exc.value.status_code == 429
        assert 1 <= exc.value.retry_after <= 60
        assert exc.value.limit == 2
        assert exc.value.remaining == 0
        assert exc.value.reset > 0
        assert exc.value.hint == (
            f"Too many requests. Try again in {exc.value.retry_after} seconds."
        )

    async def test_different_keys_have_independent_buckets(
        self, rate_limiter: RateLimiter
    ) -> None:
        p_a = _payload(key_id="key_aaaa", rate_limit_rpm=1)
        p_b = _payload(key_id="key_bbbb", rate_limit_rpm=1)
        await check_rate_limit(
            _build_request(auth_payload=p_a, rate_limiter=rate_limiter)
        )
        with pytest.raises(RateLimitError):
            await check_rate_limit(
                _build_request(auth_payload=p_a, rate_limiter=rate_limiter)
            )
        # key_b is independent and still has its slot.
        await check_rate_limit(
            _build_request(auth_payload=p_b, rate_limiter=rate_limiter)
        )

    async def test_same_key_from_two_ips_shares_bucket(
        self, rate_limiter: RateLimiter
    ) -> None:
        payload = _payload(rate_limit_rpm=1)
        req_ip_a = _build_request(
            headers={"x-forwarded-for": "203.0.113.10"},
            auth_payload=payload,
            rate_limiter=rate_limiter,
        )
        req_ip_b = _build_request(
            headers={"x-forwarded-for": "203.0.113.11"},
            auth_payload=payload,
            rate_limiter=rate_limiter,
        )
        await check_rate_limit(req_ip_a)
        with pytest.raises(RateLimitError):
            await check_rate_limit(req_ip_b)

    async def test_rotation_preserves_bucket(self, rate_limiter: RateLimiter) -> None:
        """``rotate-key`` swaps plaintext but keeps ``key_id`` — bucket persists.

        A rotated key in the same minute-window must inherit the pre-rotation
        counts. The production code guarantees this because the bucket is
        keyed on ``key_id`` and rotate changes only the plaintext/hash, not
        the id. This test exercises the invariant at the dependency level.
        """
        key_id = "key_rotation_target"
        # Pre-rotation payload exhausts the 2-request budget.
        pre = _payload(key_id=key_id, rate_limit_rpm=2)
        # Fresh ``Request`` each hit — reuse would overwrite
        # ``request.state.rate_limit_headers`` harmlessly but obscure intent.
        await check_rate_limit(
            _build_request(auth_payload=pre, rate_limiter=rate_limiter)
        )
        await check_rate_limit(
            _build_request(auth_payload=pre, rate_limiter=rate_limiter)
        )
        # Post-rotation payload has the same key_id but would be a fresh
        # AuthPayload instance in production (different plaintext hash, same
        # registry row). Bucket must be the same.
        post = _payload(key_id=key_id, rate_limit_rpm=2)
        req_post = _build_request(auth_payload=post, rate_limiter=rate_limiter)
        with pytest.raises(RateLimitError):
            await check_rate_limit(req_post)

    async def test_concurrent_hits_are_atomic(self, rate_limiter: RateLimiter) -> None:
        """Parallel ``.hit()`` calls must count exactly once each.

        A moving-window rate-limit's critical section is read-modify-write.
        With N+1 concurrent hits on an rpm=N bucket, exactly N must pass
        and exactly 1 must raise ``RateLimitError``.
        """
        rpm = 5
        payload = _payload(rate_limit_rpm=rpm)

        async def _hit() -> bool:
            req = _build_request(auth_payload=payload, rate_limiter=rate_limiter)
            try:
                await check_rate_limit(req)
            except RateLimitError:
                return False
            return True

        results = await asyncio.gather(*[_hit() for _ in range(rpm + 1)])
        assert sum(results) == rpm
        assert results.count(False) == 1


class TestCheckRateLimitGuards:
    """Guard rails for stateful misconfiguration."""

    async def test_missing_auth_payload_raises_key_registry_error(self) -> None:
        """Dependency ordering error surfaces as a diagnosable 500.

        If a route declares ``Depends(check_rate_limit)`` without a
        preceding ``Depends(verify_api_key)``, ``request.state.auth_payload``
        is absent. The old code crashed with ``AttributeError`` → opaque
        500. The hardened code raises ``KeyRegistryError`` with an
        actionable message.
        """
        rl = RateLimiter.build()
        req = _build_request(rate_limiter=rl)  # no auth_payload
        with pytest.raises(KeyRegistryError) as exc:
            await check_rate_limit(req)
        assert "auth_payload" in exc.value.message

    async def test_missing_rate_limiter_raises_key_registry_error(self) -> None:
        """Lifespan misconfiguration surfaces as a diagnosable 500."""
        payload = _payload()
        req = _build_request(auth_payload=payload, rate_limiter=None)
        with pytest.raises(KeyRegistryError) as exc:
            await check_rate_limit(req)
        assert "RateLimiter" in exc.value.message

    async def test_rpm_below_one_rejected(self) -> None:
        """Corrupted row with ``rate_limit_rpm=0`` produces a diagnosable 500.

        Defense in depth — the DB CHECK constraint enforces ``> 0``, so
        this state is unreachable via the CLI. A direct SQL edit or a
        malformed backup restore could produce it; without this guard
        ``parse("0/minute")`` would yield a permanent 429 with no operator
        signal.
        """
        rl = RateLimiter.build()
        payload = _payload(rate_limit_rpm=0)
        req = _build_request(auth_payload=payload, rate_limiter=rl)
        with pytest.raises(KeyRegistryError) as exc:
            await check_rate_limit(req)
        assert "rate_limit_rpm=0" in exc.value.message
