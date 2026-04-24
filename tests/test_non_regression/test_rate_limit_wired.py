"""FR50 non-regression — rate-limit gate wiring on /v1/audio/speech
(Story 4.5e).

Asserts the failure modes that would reintroduce the edfcb33-class
bug (rate-limit infrastructure wired but not actually enforced on
request):

1. ``Depends(check_rate_limit)`` removed from the route declaration.
2. 3rd request at ``rate_limit_rpm=2`` does not return 429.
3. ``/health`` remains UN-rate-limited (CLAUDE.md design decision).
4. The route's dependency is the canonical ``check_rate_limit`` object,
   not a same-named stub.

Uses the repo-level ASGI TestClient fixtures (``app``, ``client``) from
``tests/conftest.py`` — NOT the docker fixtures from this package's
``conftest.py``. Runs in-process; no docker required.
"""

from __future__ import annotations

from datetime import date
from typing import Any

import pytest
from fastapi.routing import APIRoute
from httpx import AsyncClient

from comadre.keys import auth as auth_module
from comadre.rate_limit import check_rate_limit
from tests._keys_fixtures import seed_customer_and_key

_SPEECH_PATH: str = "/v1/audio/speech"
_HEALTH_PATH: str = "/health"
_TEST_RPM: int = 2  # small value keeps the 3rd-request 429 trip fast
_BURST_ATTEMPTS: int = 5  # /health probe — prove 429 never happens
_SPEECH_BODY: dict[str, str] = {
    "input": "olá mundo",
    "voice": "kokoro/pm_santa",
    "response_format": "ogg",
}


@pytest.mark.non_regression
def test_check_rate_limit_dependency_registered_on_speech_route() -> None:
    """FR50 regression guard: ``Depends(check_rate_limit)`` must still be in
    the ``dependencies=[...]`` list on the ``POST /v1/audio/speech`` route.

    Catches the edfcb33-class bug: rate-limit infrastructure wired but not
    actually enforced on request. If the ``Depends(check_rate_limit)``
    entry is dropped from the route declaration, ``check_rate_limit``
    never runs, and every authenticated request bypasses the gate
    silently.
    """
    from comadre.main import create_app

    app = create_app()
    speech_routes = [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path == _SPEECH_PATH and "POST" in r.methods
    ]
    assert len(speech_routes) == 1, (
        f"Expected exactly one POST {_SPEECH_PATH} route, found "
        f"{len(speech_routes)}. Route declaration at src/comadre/api.py "
        f"may have been reshaped — FR50 wiring invariant broken."
    )
    route = speech_routes[0]
    declared_calls = [d.dependency for d in (route.dependencies or [])]
    resolved_calls = [d.call for d in route.dependant.dependencies]
    assert check_rate_limit in declared_calls, (
        f"POST {_SPEECH_PATH} route has dependencies=[...] but "
        f"`check_rate_limit` is NOT among them. Declared: "
        f"{[getattr(c, '__name__', repr(c)) for c in declared_calls]}. "
        f"The edfcb33-class bug has regressed: the rate-limit gate is "
        f"silently inert. Restore `Depends(check_rate_limit)` in "
        f"`src/comadre/api.py`'s `api_router.post('/v1/audio/speech', "
        f"dependencies=[...])`."
    )
    assert check_rate_limit in resolved_calls, (
        f"POST {_SPEECH_PATH} route's resolved dependency tree does not "
        f"include `check_rate_limit`. Resolved: "
        f"{[getattr(c, '__name__', repr(c)) for c in resolved_calls]}. "
        f"This indicates `check_rate_limit` was declared but FastAPI "
        f"failed to resolve it (import error? signature change?) — "
        f"investigate `src/comadre/rate_limit.py::check_rate_limit`."
    )


@pytest.mark.non_regression
async def test_speech_endpoint_emits_429_after_rate_limit(
    app: Any, client: AsyncClient, monkeypatch: pytest.MonkeyPatch
) -> None:
    """FR50 regression guard: exceeding ``rate_limit_rpm`` on
    ``/v1/audio/speech`` returns HTTP 429 with the project envelope.

    The most direct assertion of the FR50 intent: a functioning
    rate-limit gate returns 429 when the limit is exceeded. If the
    route-inspection and state-inspection tests both pass but THIS test
    fails, something subtler is broken — e.g., the ``check_rate_limit``
    body was changed to always allow, or ``MovingWindowRateLimiter.hit``
    was monkey-patched incorrectly in a refactor.
    """
    monkeypatch.setattr(
        auth_module, "_today_in_billing_tz", lambda _s: date(2026, 4, 17)
    )
    plaintext, _kid, _cid = seed_customer_and_key(
        app.state.registry_db, rate_limit_rpm=_TEST_RPM
    )
    headers = {"Authorization": f"Bearer {plaintext}"}

    # Consume the budget exactly.
    for attempt in range(_TEST_RPM):
        r = await client.post(_SPEECH_PATH, json=_SPEECH_BODY, headers=headers)
        assert r.status_code == 200, (
            f"Attempt {attempt + 1}/{_TEST_RPM} to {_SPEECH_PATH} at "
            f"rate_limit_rpm={_TEST_RPM} returned {r.status_code} — "
            f"expected 200. The under-limit path should NEVER 429. "
            f"Body: {r.text[:200]!r}"
        )

    # One more request trips the gate.
    trip = await client.post(_SPEECH_PATH, json=_SPEECH_BODY, headers=headers)
    assert trip.status_code == 429, (
        f"{_TEST_RPM + 1}th request to {_SPEECH_PATH} at "
        f"rate_limit_rpm={_TEST_RPM} returned {trip.status_code}, "
        f"expected 429. The rate-limit gate is silently permitting "
        f"over-budget requests — edfcb33-class regression: FR50 gate "
        f"failed. Body: {trip.text[:200]!r}"
    )
    lowered_headers = {name.lower() for name in trip.headers}
    assert "retry-after" in lowered_headers, (
        f"429 response missing `Retry-After` header. Headers: "
        f"{dict(trip.headers)}. Clients cannot back off cleanly; the "
        f"response shape regressed from the 2.2 contract."
    )
    retry_after = int(trip.headers["retry-after"])
    # Upper bound 61, not 60: `check_rate_limit` uses
    # `math.ceil(reset_time - now)` on a 60s window — float drift of
    # 60.0000001s legitimately ceils to 61 without any regression.
    assert 1 <= retry_after <= 61, (
        f"`Retry-After` on 429 is {retry_after!r}, expected an integer "
        f"in [1, 61] for a 1-minute window. The limiter's window math "
        f"may have regressed."
    )
    body = trip.json()
    assert body == {
        "error": {
            "message": "Rate limit exceeded",
            "type": "rate_limit_error",
            "hint": f"Too many requests. Try again in {retry_after} seconds.",
        }
    }, (
        f"429 envelope drifted from the `{{error:{{message,type,hint}}}}` "
        f"shape. Got: {body!r}. The uniform-error-envelope contract is "
        f"a separate non-regression concern (4.5f), but this assertion "
        f"also catches drift here so a 429 with an OK body does not "
        f"pass."
    )
    assert trip.headers.get("x-ratelimit-limit") == str(_TEST_RPM), (
        f"X-RateLimit-Limit header on 429 is "
        f"{trip.headers.get('x-ratelimit-limit')!r}, expected "
        f"{str(_TEST_RPM)!r}. The 2.2 contract guarantees all three "
        f"X-RateLimit-* headers on both allow AND deny paths."
    )
    assert trip.headers.get("x-ratelimit-remaining") == "0", (
        f"X-RateLimit-Remaining header on 429 is "
        f"{trip.headers.get('x-ratelimit-remaining')!r}, expected "
        f"'0'. Deny path must report zero remaining budget."
    )
    reset_raw = trip.headers.get("x-ratelimit-reset")
    assert reset_raw is not None and int(reset_raw) > 0, (
        f"X-RateLimit-Reset header on 429 is {reset_raw!r}, expected a "
        f"positive integer epoch. The 2.2 contract clamps this to a "
        f"future epoch; a missing or non-positive value is a regression."
    )


@pytest.mark.non_regression
async def test_health_endpoint_is_not_rate_limited(
    app: Any, client: AsyncClient
) -> None:
    """FR50 (re-interpreted): ``/health`` is UN-rate-limited by design.

    CLAUDE.md §Architecture: *"``/health`` is not rate-limited at the
    app layer."* This test pins that design decision. If a future PR
    adds ``Depends(check_rate_limit)`` to ``/health``, bursting it with
    zero auth header would 429 instead of returning the
    minimal-for-unauth body, which is a design regression (operators
    rely on un-throttled probes for liveness checks).
    """
    statuses: list[int] = []
    for _ in range(_BURST_ATTEMPTS):
        r = await client.get(_HEALTH_PATH)
        statuses.append(r.status_code)
    assert 429 not in statuses, (
        f"`/health` returned 429 within a {_BURST_ATTEMPTS}-request "
        f"burst: statuses={statuses}. This indicates a rate-limit gate "
        f"was added to `/health` — contradicting the CLAUDE.md design "
        f"decision 'health is not rate-limited at the app layer.' "
        f"Operators rely on un-throttled probes for liveness checks; "
        f"rate-limiting `/health` is a design regression, not a fix."
    )
    for status in statuses:
        assert status in {200, 503}, (
            f"`/health` returned an unexpected status {status} in the "
            f"burst. Expected 200 (ready) or 503 (warming_up). Statuses "
            f"observed: {statuses}."
        )


@pytest.mark.non_regression
def test_check_rate_limit_identity_on_speech_route() -> None:
    """FR50 regression guard: the dependency callable is precisely
    ``comadre.rate_limit.check_rate_limit`` — not a stub, not a shim.

    Catches the subtle refactor "rename ``check_rate_limit`` and leave
    the old symbol as a no-op" — the dependency list stays non-empty,
    ``check_rate_limit in declared_calls`` still passes if the OLD
    symbol is kept around as a no-op, but the NEW symbol is the one the
    route actually uses. This test pins identity: the object named
    ``check_rate_limit`` in ``comadre.rate_limit`` is the same object
    referenced by the route.
    """
    from comadre.main import create_app
    from comadre.rate_limit import check_rate_limit as canonical

    app = create_app()
    speech_routes = [
        r
        for r in app.routes
        if isinstance(r, APIRoute) and r.path == _SPEECH_PATH and "POST" in r.methods
    ]
    assert len(speech_routes) == 1, (
        f"Expected exactly one POST {_SPEECH_PATH} route, found "
        f"{len(speech_routes)}. Route declaration at src/comadre/api.py "
        f"may have been reshaped — FR50 wiring invariant broken."
    )
    route = speech_routes[0]
    resolved = [d.call for d in route.dependant.dependencies]
    # ``is`` not ``==`` — identity, not equality.
    resolved_labels = [
        (getattr(c, "__module__", "?"), getattr(c, "__name__", repr(c)))
        for c in resolved
    ]
    assert any(d is canonical for d in resolved), (
        f"POST {_SPEECH_PATH} route's dependency is NOT the canonical "
        f"`comadre.rate_limit.check_rate_limit` object. Resolved "
        f"callables: {resolved_labels}. A refactor may have introduced "
        f"a shim/stub that keeps the dependency list populated but "
        f"silently permits everything — edfcb33-class regression via a "
        f"subtler mechanism."
    )
