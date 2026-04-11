"""Tests for the X-Forwarded-For aware client IP helper."""

from __future__ import annotations

from typing import Any

from starlette.requests import Request

from comadre.rate_limit import get_client_ip


def _build_request(headers: dict[str, str], client_host: str | None) -> Request:
    """Build a minimal Starlette Request for unit testing get_client_ip."""
    raw_headers = [(k.lower().encode(), v.encode()) for k, v in headers.items()]
    scope: dict[str, Any] = {
        "type": "http",
        "method": "GET",
        "path": "/",
        "headers": raw_headers,
        "client": (client_host, 12345) if client_host else None,
    }
    return Request(scope)


def test_xff_single_ip() -> None:
    request = _build_request(
        {"x-forwarded-for": "203.0.113.5"}, client_host="172.18.0.2"
    )
    assert get_client_ip(request) == "203.0.113.5"


def test_xff_chain_returns_leftmost() -> None:
    request = _build_request(
        {"x-forwarded-for": "203.0.113.5, 198.51.100.10, 192.0.2.1"},
        client_host="172.18.0.2",
    )
    assert get_client_ip(request) == "203.0.113.5"


def test_no_xff_falls_back_to_request_client() -> None:
    request = _build_request({}, client_host="127.0.0.1")
    assert get_client_ip(request) == "127.0.0.1"


def test_no_xff_no_client_returns_default() -> None:
    request = _build_request({}, client_host=None)
    assert get_client_ip(request) == "127.0.0.1"
