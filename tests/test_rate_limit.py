"""Tests for ``comadre.rate_limit``.

Covers the X-Forwarded-For aware ``get_client_ip`` helper (used by the
access-log middleware) and the ``check_rate_limit`` FastAPI dependency
(per-key bucket enforcement via the ``limits`` library). 2026-04-18
rewrite — slowapi was removed; no ``resolve_speech_rate_limit`` /
``get_rate_limit_key`` helpers anymore.
"""

from __future__ import annotations

from types import SimpleNamespace
from typing import Any

import pytest
from starlette.requests import Request

from comadre.exceptions import RateLimitError
from comadre.keys.models import AuthPayload
from comadre.rate_limit import RateLimiter, check_rate_limit, get_client_ip


def _build_request(
    headers: dict[str, str] | None = None,
    client_host: str | None = None,
    *,
    auth_payload: AuthPayload | None = None,
    rate_limiter: RateLimiter | None = None,
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
    if rate_limiter is not None:
        scope["app"] = SimpleNamespace(state=SimpleNamespace(rate_limiter=rate_limiter))
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
        # Hit the bucket once, then reset, then verify a fresh window.
        payload = _payload(rate_limit_rpm=1)
        req = _build_request(auth_payload=payload, rate_limiter=rl)
        await check_rate_limit(req)  # consumes the only slot
        await rl.reset()
        # After reset the same request should pass again.
        await check_rate_limit(req)


class TestCheckRateLimit:
    """Per-key rate-limit dependency — happy path, trip, and bucket isolation."""

    @pytest.fixture()
    async def rate_limiter(self) -> RateLimiter:
        rl = RateLimiter.build()
        return rl

    async def test_allows_up_to_rpm_requests(self, rate_limiter: RateLimiter) -> None:
        payload = _payload(rate_limit_rpm=3)
        req = _build_request(auth_payload=payload, rate_limiter=rate_limiter)
        for _ in range(3):
            await check_rate_limit(req)  # no exception

    async def test_trips_on_rpm_plus_one(self, rate_limiter: RateLimiter) -> None:
        payload = _payload(rate_limit_rpm=2)
        req = _build_request(auth_payload=payload, rate_limiter=rate_limiter)
        await check_rate_limit(req)
        await check_rate_limit(req)
        with pytest.raises(RateLimitError) as exc:
            await check_rate_limit(req)
        assert exc.value.status_code == 429
        assert exc.value.hint == "Too many requests. Try again in 60 seconds."

    async def test_different_keys_have_independent_buckets(
        self, rate_limiter: RateLimiter
    ) -> None:
        p_a = _payload(key_id="key_aaaa", rate_limit_rpm=1)
        p_b = _payload(key_id="key_bbbb", rate_limit_rpm=1)
        await check_rate_limit(
            _build_request(auth_payload=p_a, rate_limiter=rate_limiter)
        )
        # key_a is capped; key_b is independent and still has its slot.
        with pytest.raises(RateLimitError):
            await check_rate_limit(
                _build_request(auth_payload=p_a, rate_limiter=rate_limiter)
            )
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
        # IP changed but the same key's bucket is already capped.
        with pytest.raises(RateLimitError):
            await check_rate_limit(req_ip_b)
