"""Rate limiting via slowapi, X-Forwarded-For aware."""

from __future__ import annotations

from slowapi import Limiter
from starlette.requests import Request


def get_client_ip(request: Request) -> str:
    """Return the real client IP, trusting X-Forwarded-For from Caddy.

    Comadre runs behind Caddy on a Docker bridge network, so
    ``request.client.host`` is the Caddy container IP, not the real client.
    Caddy injects X-Forwarded-For on every reverse-proxy request; its
    leftmost entry is the original client. Fall back to ``request.client.host``
    when the header is absent (unit tests, direct local runs without a proxy).
    """
    forwarded = request.headers.get("x-forwarded-for")
    if forwarded:
        return forwarded.split(",")[0].strip()
    if request.client is not None:
        return request.client.host
    return "127.0.0.1"


limiter = Limiter(key_func=get_client_ip)
