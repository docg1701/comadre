"""HTTP-boundary tests for ``/v1/audio/speech`` (and ``/health`` 405).

Lean by design (test-suite review 2026-04-25): the contract is the
status code + JSON envelope shape + audit invariants. Per-flag
parametrize, per-status branch tests, and engine-call mock-asserts
were collapsed into combined integration tests. Rate-limit + counters
+ snapshot-lifespan tests live in ``test_counters.py``.
"""

from __future__ import annotations

import sqlite3
from datetime import date
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from comadre.exceptions import VoiceNotFoundError
from tests._keys_fixtures import seed_customer_and_key

_SPEECH_BODY: dict[str, str] = {
    "input": "olá mundo",
    "voice": "kokoro/pm_santa",
    "response_format": "ogg",
}


@pytest.fixture(autouse=True)
def _freeze_clock(monkeypatch: pytest.MonkeyPatch) -> None:
    """Pin auth's ``today`` so ``paid_until=2099-12-31`` seed rows stay active."""
    from comadre.keys import auth as auth_module

    monkeypatch.setattr(
        auth_module, "_today_in_billing_tz", lambda _s: date(2026, 4, 17)
    )


async def test_speech_happy_path_ogg_and_wav(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """OGG default + WAV variant — content-type, content-disposition, body bytes."""
    for fmt, ctype in (("ogg", "audio/ogg"), ("wav", "audio/wav")):
        response = await client.post(
            "/v1/audio/speech",
            json={"input": "Hello", "voice": "kokoro/pm_santa", "response_format": fmt},
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == ctype
        assert (
            response.headers["content-disposition"]
            == f'attachment; filename="speech.{fmt}"'
        )
        assert response.content == b"fake-audio-bytes"


async def test_speech_405_envelope_on_get_and_post_health(
    client: AsyncClient,
) -> None:
    """405 returns the project's error envelope, not the FastAPI default."""
    response = await client.get("/v1/audio/speech")
    assert response.status_code == 405
    assert response.json()["error"]["type"] == "method_not_allowed_error"
    assert "GET" in response.json()["error"]["message"]
    assert "Allow" in response.headers

    response = await client.post("/health", json={})
    assert response.status_code == 405
    assert response.json()["error"]["type"] == "method_not_allowed_error"


async def test_speech_validation_400_envelope(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """Pydantic validation failures (missing/empty input) → 400, not 422."""
    for bad_body in (
        {"voice": "kokoro/pm_santa"},
        {"input": "", "voice": "kokoro/pm_santa"},
    ):
        response = await client.post(
            "/v1/audio/speech", json=bad_body, headers=auth_headers
        )
        assert response.status_code == 400
        assert response.json()["error"]["type"] == "invalid_request_error"


async def test_speech_validation_messages_are_field_specific(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    """B20 — empty input vs oversized vs missing field surface distinct
    error messages, not the legacy generic ``Invalid request body``.
    Operators reading the API response should see *which* field failed
    *why* without parsing pydantic's raw error envelope."""
    cases = [
        (
            {"input": "", "voice": "kokoro/pm_santa"},
            "must not be empty",
        ),
        (
            {"input": "x" * 10_000, "voice": "kokoro/pm_santa"},
            "exceeds the allowed length",
        ),
        (
            {"voice": "kokoro/pm_santa"},
            "is required",
        ),
    ]
    for body, expected_fragment in cases:
        response = await client.post(
            "/v1/audio/speech", json=body, headers=auth_headers
        )
        assert response.status_code == 400, body
        message = response.json()["error"]["message"]
        assert expected_fragment in message, (body, message)


async def test_speech_unknown_voice_returns_404(
    client: AsyncClient, auth_headers: dict[str, str], mock_router: MagicMock
) -> None:
    mock_router.generate_speech.side_effect = VoiceNotFoundError(
        "nonexistent", available=["kokoro/pm_santa"]
    )
    response = await client.post(
        "/v1/audio/speech",
        json={"input": "x", "voice": "nonexistent"},
        headers=auth_headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "not_found_error"


async def test_speech_warmup_503_takes_priority_over_auth(app: Any) -> None:
    """503 from ``ready=False`` fires before 401, by dependency order."""
    app.state.ready = False
    async with AsyncClient(
        transport=ASGITransport(app=app), base_url="http://test"
    ) as warmup_client:
        response = await warmup_client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": "Bearer wrong-key"},
        )
    assert response.status_code == 503
    assert response.json()["error"]["type"] == "service_unavailable"
    assert response.headers["retry-after"] == "30"


async def test_registry_auth_active_and_complimentary_keys_authenticate(
    app: Any, client: AsyncClient
) -> None:
    """Active manual key + complimentary key both authenticate."""
    for kwargs in (
        {},
        {
            "customer_email": "comp@x.com",
            "billing_mode": "complimentary",
            "paid_until": None,
        },
    ):
        pt, _, _ = seed_customer_and_key(app.state.registry_db, **kwargs)  # type: ignore[arg-type]
        response = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {pt}"},
        )
        assert response.status_code == 200, kwargs


async def test_registry_auth_suspended_revoked_expired_all_401_with_hint(
    app: Any, client: AsyncClient
) -> None:
    """Suspended / revoked / expired-paid-until keys all 401 with the
    operator-contact hint piped through the envelope."""
    cases = [
        ({"status": "suspended"}, "suspended"),
        ({"status": "revoked"}, "revoked"),
        ({"paid_until": "2020-01-01"}, "suspended"),  # expired manual
    ]
    for kwargs, expected_phrase in cases:
        pt, _, _ = seed_customer_and_key(
            app.state.registry_db,
            customer_email=f"x{expected_phrase}@x.com",
            **kwargs,  # type: ignore[arg-type]
        )
        response = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {pt}"},
        )
        assert response.status_code == 401, expected_phrase
        body = response.json()
        assert expected_phrase in body["error"]["message"].lower()
        assert "Contact Ana" in body["error"]["hint"]


async def test_registry_auth_unknown_or_malformed_401_envelope(
    client: AsyncClient,
) -> None:
    """Unknown bearer + malformed Authorization headers → 401 with the
    enumeration-resistant envelope (same shape regardless of cause)."""
    for header in (
        "Bearer cmdr_live_" + "a" * 43,  # unknown valid-shape
        "",
        "Basic xyz",
        "Bearer",
        "BearerXYZ",
    ):
        response = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": header} if header else {},
        )
        assert response.status_code == 401, header
        body = response.json()
        assert body["error"]["type"] == "authentication_error"
        if "cmdr_live_" in header:
            assert body["error"]["message"] == "Invalid or missing API key"


async def test_no_audit_log_writes_on_any_speech_outcome(
    app: Any, client: AsyncClient
) -> None:
    """Auth path NEVER writes to audit_log. The audit table is reserved
    for CLI mutations; the runtime hot path stays read-only."""
    conn: sqlite3.Connection = app.state.registry_db
    pt_ok, _, _ = seed_customer_and_key(conn)
    pt_susp, _, _ = seed_customer_and_key(
        conn, customer_email="x@y.com", status="suspended"
    )
    before = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    for headers in (
        {"Authorization": f"Bearer {pt_ok}"},
        {"Authorization": f"Bearer {pt_susp}"},
        {"Authorization": "Bearer unknown-token"},
    ):
        await client.post("/v1/audio/speech", json=_SPEECH_BODY, headers=headers)
    after = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
    assert after == before


async def test_rate_limit_429_envelope_and_independent_per_key(
    app: Any, client: AsyncClient, mock_router: MagicMock
) -> None:
    """Rate-limit contract: rpm=2 admits 2 requests then 429 with envelope
    + retry-after + X-RateLimit-* headers; engine NOT invoked on 429.
    Two keys for the same customer bucket independently on key_id."""
    pt_a, _, _ = seed_customer_and_key(
        app.state.registry_db, customer_email="a@x.com", rate_limit_rpm=2
    )
    pt_b, _, _ = seed_customer_and_key(
        app.state.registry_db, customer_email="b@x.com", rate_limit_rpm=2
    )
    headers_a = {"Authorization": f"Bearer {pt_a}"}
    mock_router.generate_speech.reset_mock()

    for _ in range(2):
        r = await client.post("/v1/audio/speech", json=_SPEECH_BODY, headers=headers_a)
        assert r.status_code == 200
        assert r.headers["x-ratelimit-limit"] == "2"

    trip = await client.post("/v1/audio/speech", json=_SPEECH_BODY, headers=headers_a)
    assert trip.status_code == 429
    body = trip.json()
    assert body["error"]["type"] == "rate_limit_error"
    assert body["error"]["message"] == "Rate limit exceeded"
    assert 1 <= int(trip.headers["retry-after"]) <= 60
    assert trip.headers["x-ratelimit-remaining"] == "0"
    # Engine called rpm times only — 429 short-circuits before TTS.
    assert mock_router.generate_speech.call_count == 2

    # Key B in independent bucket — gets full budget.
    r = await client.post(
        "/v1/audio/speech",
        json=_SPEECH_BODY,
        headers={"Authorization": f"Bearer {pt_b}"},
    )
    assert r.status_code == 200
