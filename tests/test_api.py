"""Tests for speech endpoint HTTP behavior."""

from __future__ import annotations

import sqlite3
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from comadre.exceptions import VoiceNotFoundError
from tests._keys_fixtures import seed_customer_and_key


class TestSpeechSuccess:
    """Valid request returns 200 with audio content."""

    async def test_valid_request_returns_200_with_audio_ogg(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/v1/audio/speech",
            json={
                "input": "Hello world",
                "voice": "kokoro/pm_santa",
                "response_format": "ogg",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/ogg"
        assert response.content == b"fake-audio-bytes"

    async def test_content_disposition_header_ogg(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/v1/audio/speech",
            json={
                "input": "Hello world",
                "voice": "kokoro/pm_santa",
                "response_format": "ogg",
            },
            headers=auth_headers,
        )
        expected = 'attachment; filename="speech.ogg"'
        assert response.headers["content-disposition"] == expected

    async def test_wav_format_returns_audio_wav(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/v1/audio/speech",
            json={
                "input": "Hello world",
                "voice": "kokoro/pm_santa",
                "response_format": "wav",
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/wav"
        expected = 'attachment; filename="speech.wav"'
        assert response.headers["content-disposition"] == expected

    async def test_default_voice_uses_settings_default(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        mock_router: MagicMock,
    ) -> None:
        response = await client.post(
            "/v1/audio/speech",
            json={"input": "Hello world"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        # Default voice is "kokoro/pm_santa" from Settings defaults
        mock_router.generate_speech.assert_called_once()
        call_kwargs = mock_router.generate_speech.call_args
        assert call_kwargs.kwargs["voice_name"] == "kokoro/pm_santa"

    async def test_noise_dir_passed_to_router(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        mock_router: MagicMock,
    ) -> None:
        response = await client.post(
            "/v1/audio/speech",
            json={"input": "Hello world", "voice": "kokoro/pm_santa"},
            headers=auth_headers,
        )
        assert response.status_code == 200
        mock_router.generate_speech.assert_called_once()
        call_kwargs = mock_router.generate_speech.call_args
        assert call_kwargs.kwargs["noise_dir"] == Path("/app/noise")

    async def test_raw_parameter_passed_to_router(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        mock_router: MagicMock,
    ) -> None:
        response = await client.post(
            "/v1/audio/speech",
            json={
                "input": "Hello world",
                "voice": "kokoro/pm_santa",
                "raw": True,
            },
            headers=auth_headers,
        )
        assert response.status_code == 200
        call_kwargs = mock_router.generate_speech.call_args
        assert call_kwargs.kwargs["raw"] is True

    async def test_raw_defaults_to_false(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        mock_router: MagicMock,
    ) -> None:
        await client.post(
            "/v1/audio/speech",
            json={"input": "Hello world", "voice": "kokoro/pm_santa"},
            headers=auth_headers,
        )
        call_kwargs = mock_router.generate_speech.call_args
        assert call_kwargs.kwargs["raw"] is False


class TestMethodNotAllowed:
    """405 responses use the project's standard error envelope."""

    async def test_get_on_speech_returns_405_with_error_envelope(
        self, client: AsyncClient
    ) -> None:
        response = await client.get("/v1/audio/speech")
        assert response.status_code == 405
        body = response.json()
        assert "error" in body
        assert body["error"]["type"] == "method_not_allowed_error"
        assert "GET" in body["error"]["message"]
        assert "/v1/audio/speech" in body["error"]["message"]
        assert body["error"]["hint"]
        # Allow header preserved from Starlette
        assert "Allow" in response.headers

    async def test_put_on_speech_returns_405_with_error_envelope(
        self, client: AsyncClient
    ) -> None:
        response = await client.put(
            "/v1/audio/speech",
            json={"input": "x", "voice": "kokoro/pm_santa"},
        )
        assert response.status_code == 405
        body = response.json()
        assert body["error"]["type"] == "method_not_allowed_error"

    async def test_post_on_health_returns_405_with_error_envelope(
        self, client: AsyncClient
    ) -> None:
        response = await client.post("/health", json={})
        assert response.status_code == 405
        body = response.json()
        assert body["error"]["type"] == "method_not_allowed_error"
        assert "POST" in body["error"]["message"]
        assert "/health" in body["error"]["message"]


class TestSpeechAuth:
    """Missing or invalid auth returns 401."""

    async def test_missing_auth_header_returns_401(self, client: AsyncClient) -> None:
        response = await client.post(
            "/v1/audio/speech",
            json={"input": "Hello world", "voice": "kokoro/pm_santa"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["type"] == "authentication_error"

    async def test_invalid_bearer_token_returns_401(self, client: AsyncClient) -> None:
        response = await client.post(
            "/v1/audio/speech",
            json={"input": "Hello world", "voice": "kokoro/pm_santa"},
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["type"] == "authentication_error"


class TestSpeechValidation:
    """Malformed request returns 400."""

    async def test_missing_input_field_returns_400(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/v1/audio/speech",
            json={"voice": "kokoro/pm_santa"},
            headers=auth_headers,
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["type"] == "invalid_request_error"

    async def test_empty_input_field_returns_400(
        self, client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await client.post(
            "/v1/audio/speech",
            json={"input": "", "voice": "kokoro/pm_santa"},
            headers=auth_headers,
        )
        assert response.status_code == 400
        body = response.json()
        assert body["error"]["type"] == "invalid_request_error"


class TestSpeechNotFound:
    """Unknown voice returns 404."""

    async def test_unknown_voice_returns_404(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        mock_router: MagicMock,
    ) -> None:
        mock_router.generate_speech.side_effect = VoiceNotFoundError(
            voice="nonexistent", available=["alex", "dora", "santa"]
        )
        response = await client.post(
            "/v1/audio/speech",
            json={"input": "Hello world", "voice": "nonexistent"},
            headers=auth_headers,
        )
        assert response.status_code == 404
        body = response.json()
        assert body["error"]["type"] == "not_found_error"


class TestSpeechWarmUp:
    """Service warming up returns 503."""

    @pytest.fixture()
    def warmup_app(self, app: Any) -> Any:
        """Return an app where ready=False."""
        app.state.ready = False
        return app

    @pytest.fixture()
    async def warmup_client(self, warmup_app: Any) -> AsyncClient:
        from httpx import ASGITransport

        async with AsyncClient(
            transport=ASGITransport(app=warmup_app),
            base_url="http://test",
        ) as c:
            yield c  # type: ignore[misc]

    async def test_warming_up_returns_503_with_retry_after(
        self, warmup_client: AsyncClient, auth_headers: dict[str, str]
    ) -> None:
        response = await warmup_client.post(
            "/v1/audio/speech",
            json={"input": "Hello world", "voice": "kokoro/pm_santa"},
            headers=auth_headers,
        )
        assert response.status_code == 503
        body = response.json()
        assert body["error"]["type"] == "service_unavailable"
        assert response.headers["retry-after"] == "30"

    async def test_warmup_takes_priority_over_invalid_auth(
        self, warmup_client: AsyncClient
    ) -> None:
        """503 warm-up fires before 401 auth check (dependency ordering)."""
        response = await warmup_client.post(
            "/v1/audio/speech",
            json={"input": "Hello world", "voice": "kokoro/pm_santa"},
            headers={"Authorization": "Bearer wrong-key"},
        )
        assert response.status_code == 503
        body = response.json()
        assert body["error"]["type"] == "service_unavailable"


class TestSpeechTimeout:
    """Generation timeout returns 500 with server_error."""

    async def test_generation_timeout_returns_500(
        self,
        client: AsyncClient,
        auth_headers: dict[str, str],
        mock_router: MagicMock,
    ) -> None:
        mock_router.generate_speech.side_effect = TimeoutError("generation timed out")
        response = await client.post(
            "/v1/audio/speech",
            json={"input": "Hello world", "voice": "kokoro/pm_santa"},
            headers=auth_headers,
        )
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["type"] == "server_error"
        assert "timed out" in body["error"]["message"].lower()


class TestSpeechUnhandledException:
    """Unexpected exception returns 500 via unhandled_error_handler."""

    async def test_unexpected_error_returns_500_server_error(
        self,
        app: Any,
        auth_headers: dict[str, str],
        mock_router: MagicMock,
    ) -> None:
        mock_router.generate_speech.side_effect = RuntimeError("segfault in engine")
        # ASGITransport re-raises non-HTTP exceptions by default even
        # after the handler sends a response. Disable to capture it.
        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as c:
            response = await c.post(
                "/v1/audio/speech",
                json={"input": "Hello world", "voice": "kokoro/pm_santa"},
                headers=auth_headers,
            )
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["type"] == "server_error"


_SPEECH_BODY: dict[str, str] = {
    "input": "olá mundo",
    "voice": "kokoro/pm_santa",
    "response_format": "ogg",
}


class TestRegistryAuth:
    """End-to-end registry-backed auth contract (2026-04-18: sole auth path).

    These tests exercise the registry-backed auth path through a real
    ``httpx.AsyncClient`` + ``AsyncTransport`` wrapping the FastAPI app.
    """

    @pytest.fixture(autouse=True)
    def _freeze_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pin today to 2026-04-17 so billing branches are deterministic."""
        from comadre.keys import auth as auth_module

        monkeypatch.setattr(
            auth_module, "_today_in_billing_tz", lambda _s: date(2026, 4, 17)
        )

    async def test_valid_active_key_returns_200(
        self, app: Any, client: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(app.state.registry_db)
        response = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/ogg"
        assert response.content == b"fake-audio-bytes"

    async def test_suspended_key_returns_401_with_operator_hint(
        self, app: Any, client: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(
            app.state.registry_db, status="suspended"
        )
        response = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["message"] == "Your API key has been suspended"
        assert body["error"]["type"] == "authentication_error"
        assert "Contact Ana" in body["error"]["hint"]

    async def test_revoked_key_returns_401_with_operator_hint(
        self, app: Any, client: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(
            app.state.registry_db, status="revoked"
        )
        response = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["message"] == "Your API key has been revoked"
        assert "Contact Ana" in body["error"]["hint"]

    async def test_unknown_key_returns_401_envelope(self, client: AsyncClient) -> None:
        response = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": "Bearer cmdr_live_nonexistent_token"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["message"] == "Invalid or missing API key"
        assert body["error"]["type"] == "authentication_error"
        assert "Bearer" in body["error"]["hint"]

    async def test_malformed_authorization_returns_401_envelope(
        self, client: AsyncClient
    ) -> None:
        for header in ("", "Basic xyz", "Bearer", "BearerXYZ"):
            response = await client.post(
                "/v1/audio/speech",
                json=_SPEECH_BODY,
                headers={"Authorization": header} if header else {},
            )
            assert response.status_code == 401, header
            body = response.json()
            assert body["error"]["type"] == "authentication_error"
            assert body["error"]["message"] == (
                "Missing or malformed Authorization header"
            )

    async def test_expired_manual_paid_until_returns_401_suspended(
        self, app: Any, client: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(
            app.state.registry_db, paid_until="2020-01-01"
        )
        response = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["message"] == "Your API key has been suspended"

    async def test_complimentary_null_paid_until_returns_200(
        self, app: Any, client: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(
            app.state.registry_db,
            billing_mode="complimentary",
            paid_until=None,
        )
        response = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == 200

    async def test_no_audit_log_row_on_any_auth_outcome(
        self, app: Any, client: AsyncClient
    ) -> None:
        conn: sqlite3.Connection = app.state.registry_db
        plaintext_ok, _kid, _cid = seed_customer_and_key(conn)
        plaintext_susp, _, _ = seed_customer_and_key(
            conn, customer_email="x@y.com", status="suspended"
        )

        before = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]

        await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext_ok}"},
        )
        await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext_susp}"},
        )
        await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": "Bearer unknown-token"},
        )

        after = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        assert after == before

    async def test_last_used_at_not_written_on_success(
        self, app: Any, client: AsyncClient
    ) -> None:
        conn: sqlite3.Connection = app.state.registry_db
        plaintext, kid, _cid = seed_customer_and_key(conn)
        before = conn.execute(
            "SELECT last_used_at FROM api_key WHERE id = ?", (kid,)
        ).fetchone()["last_used_at"]

        response = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == 200

        after = conn.execute(
            "SELECT last_used_at FROM api_key WHERE id = ?", (kid,)
        ).fetchone()["last_used_at"]
        assert after == before  # both None

    async def test_cache_hit_on_repeat_request_avoids_sql(
        self, app: Any, client: AsyncClient
    ) -> None:
        conn: sqlite3.Connection = app.state.registry_db
        plaintext, _kid, _cid = seed_customer_and_key(conn)

        # Warm the cache.
        r1 = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert r1.status_code == 200

        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        try:
            r2 = await client.post(
                "/v1/audio/speech",
                json=_SPEECH_BODY,
                headers={"Authorization": f"Bearer {plaintext}"},
            )
        finally:
            conn.set_trace_callback(None)
        assert r2.status_code == 200
        assert statements == []  # zero SQL on cache-hit request

    async def test_db_error_returns_500_envelope(
        self,
        app: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC9: sqlite3 error in lookup path yields 500 KeyRegistryError envelope."""
        from comadre.keys import auth as auth_module

        def _boom(_conn: Any, _key_hash: str) -> Any:
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(auth_module, "lookup_key_auth", _boom)

        async with AsyncClient(
            transport=ASGITransport(app=app, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/audio/speech",
                json=_SPEECH_BODY,
                headers={"Authorization": f"Bearer cmdr_live_{'a' * 43}"},
            )
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["message"] == (
            "Key registry database unreachable or corrupt"
        )
        assert body["error"]["type"] == "server_error"
        assert "KEY_REGISTRY_DB_PATH" in body["error"]["hint"]

        # Cache must not retain the failed lookup.
        snapshot = app.state.auth_cache.snapshot()
        assert snapshot["entries"] == 0

    async def test_access_log_does_not_leak_secrets(
        self,
        app: Any,
        client: AsyncClient,
        caplog: pytest.LogCaptureFixture,
    ) -> None:
        """AC1: access-log line on the registry-mode hot path must NOT contain
        plaintext, the Authorization header value, the SHA-256 hash, or the
        seeded customer name. The 'access' logger has propagate=False, so
        attach a probe handler directly.
        """
        import logging
        import re

        from comadre.keys.tokens import hash_api_key

        plaintext, _kid, _cid = seed_customer_and_key(
            app.state.registry_db, customer_name="Helena Probe Sentinel"
        )
        token_hash = hash_api_key(plaintext)

        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        access_logger = logging.getLogger("access")
        handler = _Capture(level=logging.DEBUG)
        access_logger.addHandler(handler)
        try:
            response = await client.post(
                "/v1/audio/speech",
                json=_SPEECH_BODY,
                headers={"Authorization": f"Bearer {plaintext}"},
            )
        finally:
            access_logger.removeHandler(handler)

        assert response.status_code == 200
        assert records, "access logger emitted no record for the request"
        hex64 = re.compile(r"[0-9a-f]{64}")
        for record in records:
            rendered = record.getMessage()
            assert "cmdr_live_" not in rendered
            assert plaintext not in rendered
            assert token_hash not in rendered
            assert "Helena Probe Sentinel" not in rendered
            assert not hex64.search(rendered)

    async def test_anti_enumeration_envelopes_diverge(
        self, app: Any, client: AsyncClient
    ) -> None:
        """AC14: not-found and suspended 401 envelopes diverge for callers
        who already proved possession of a real key (suspended branch). An
        attacker probing unknown tokens sees only the not-found envelope,
        which is byte-identical to the legacy ``AuthenticationError``
        envelope (covered by the unknown-key test above).
        """
        plaintext_susp, _kid, _cid = seed_customer_and_key(
            app.state.registry_db, status="suspended"
        )

        unknown = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": "Bearer cmdr_live_definitely_unknown"},
        )
        suspended = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext_susp}"},
        )
        assert unknown.status_code == 401
        assert suspended.status_code == 401
        unknown_body = unknown.json()["error"]
        suspended_body = suspended.json()["error"]
        assert unknown_body["type"] == suspended_body["type"] == "authentication_error"
        assert unknown_body["message"] != suspended_body["message"]
        assert unknown_body["hint"] != suspended_body["hint"]
        assert "suspended" not in unknown_body["message"].lower()
        assert "suspended" not in unknown_body["hint"].lower()

    async def test_non_ascii_bearer_token_returns_401(
        self, client: AsyncClient
    ) -> None:
        """Non-ASCII tokens cannot match any stored hash and must yield the
        enumeration-resistant 401 envelope, NOT a 500. Regression for the
        ``hash_api_key`` ``encode("ascii")`` UnicodeEncodeError path.

        httpx rejects non-ASCII string header values client-side, but raw
        HTTP allows obs-text bytes (RFC 7230 §3.2.4) which Starlette decodes
        as latin-1. Pass the header as ``bytes`` to bypass httpx's encoding
        check and reproduce what a hostile client would send on the wire.
        """
        response = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={
                "Authorization": b"Bearer cmdr_live_caf\xe9_a\xe7\xfacar_n\xe3o_existe"
            },
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["message"] == "Invalid or missing API key"
        assert body["error"]["type"] == "authentication_error"


class TestPerKeyRateLimit:
    """``/v1/audio/speech`` per-key rate limit — end-to-end via ``AsyncClient``.

    Each test gets a fresh ``app`` fixture with a fresh ``RateLimiter``.
    """

    @pytest.fixture(autouse=True)
    def _freeze_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pin today so ``paid_until=2099-12-31`` seed rows stay active."""
        from comadre.keys import auth as auth_module

        monkeypatch.setattr(
            auth_module, "_today_in_billing_tz", lambda _s: date(2026, 4, 17)
        )

    async def test_per_key_limit_allows_exactly_rpm_requests(
        self, app: Any, client: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(
            app.state.registry_db, rate_limit_rpm=2
        )
        headers = {"Authorization": f"Bearer {plaintext}"}
        responses = []
        for _ in range(2):
            response = await client.post(
                "/v1/audio/speech", json=_SPEECH_BODY, headers=headers
            )
            assert response.status_code == 200, response.json()
            responses.append(response)
        # AC13 side-effect — allow path emits X-RateLimit-* headers so
        # clients see remaining budget without waiting for a 429.
        first, second = responses
        assert first.headers["x-ratelimit-limit"] == "2"
        assert first.headers["x-ratelimit-remaining"] == "1"
        assert int(first.headers["x-ratelimit-reset"]) > 0
        assert second.headers["x-ratelimit-limit"] == "2"
        assert second.headers["x-ratelimit-remaining"] == "0"
        assert int(second.headers["x-ratelimit-reset"]) > 0

    async def test_per_key_limit_trips_on_n_plus_one(
        self, app: Any, client: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(
            app.state.registry_db, rate_limit_rpm=2
        )
        headers = {"Authorization": f"Bearer {plaintext}"}
        for _ in range(2):
            r = await client.post(
                "/v1/audio/speech", json=_SPEECH_BODY, headers=headers
            )
            assert r.status_code == 200
        trip = await client.post("/v1/audio/speech", json=_SPEECH_BODY, headers=headers)
        assert trip.status_code == 429
        retry_after = int(trip.headers["retry-after"])
        assert 1 <= retry_after <= 60
        body = trip.json()
        assert body == {
            "error": {
                "message": "Rate limit exceeded",
                "type": "rate_limit_error",
                "hint": f"Too many requests. Try again in {retry_after} seconds.",
            }
        }
        # X-RateLimit-* headers emitted on deny to mirror the allow path.
        assert trip.headers["x-ratelimit-limit"] == "2"
        assert trip.headers["x-ratelimit-remaining"] == "0"
        assert int(trip.headers["x-ratelimit-reset"]) > 0

    async def test_tts_engine_not_invoked_on_429(
        self,
        app: Any,
        client: AsyncClient,
        mock_router: MagicMock,
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(
            app.state.registry_db, rate_limit_rpm=2
        )
        headers = {"Authorization": f"Bearer {plaintext}"}
        mock_router.generate_speech.reset_mock()
        for _ in range(3):
            await client.post("/v1/audio/speech", json=_SPEECH_BODY, headers=headers)
        # rpm=2, third request 429s → engine invoked exactly rpm times.
        assert mock_router.generate_speech.call_count == 2

    async def test_independent_buckets_per_key_same_customer(
        self, app: Any, client: AsyncClient
    ) -> None:
        """Two keys for the same customer bucket independently on key_id."""
        conn = app.state.registry_db
        plaintext_c1, _k1, cid = seed_customer_and_key(
            conn, customer_name="Carla Mendes", rate_limit_rpm=2
        )
        # Second key for the same customer — build an ApiKeyRecord and use the
        # DB-layer `insert_api_key` helper so the test stays schema-aware if
        # the api_key row ever grows a column.
        from datetime import UTC, datetime

        from comadre.keys.db import generate_key_id, insert_api_key
        from comadre.keys.models import ApiKeyRecord
        from comadre.keys.tokens import generate_api_key_plaintext, hash_api_key

        plaintext_c2 = generate_api_key_plaintext()
        record_c2 = ApiKeyRecord(
            id=generate_key_id(),
            customer_id=cid,
            key_hash=hash_api_key(plaintext_c2),
            key_prefix=plaintext_c2[len("cmdr_live_") : len("cmdr_live_") + 8],
            rate_limit_rpm=2,
            status="active",
            billing_mode="manual",
            price_monthly=149.0,
            paid_until="2099-12-31",
            created_at=datetime(2026, 4, 16, 12, 0, tzinfo=UTC),
            last_used_at=None,
            notes="",
        )
        insert_api_key(conn, record_c2, actor="cli:test")

        # K_C1 exhausts its bucket.
        for _ in range(2):
            r = await client.post(
                "/v1/audio/speech",
                json=_SPEECH_BODY,
                headers={"Authorization": f"Bearer {plaintext_c1}"},
            )
            assert r.status_code == 200
        trip = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext_c1}"},
        )
        assert trip.status_code == 429

        # K_C2 still has full budget — different key_id.
        for _ in range(2):
            r = await client.post(
                "/v1/audio/speech",
                json=_SPEECH_BODY,
                headers={"Authorization": f"Bearer {plaintext_c2}"},
            )
            assert r.status_code == 200, r.json()

    async def test_independent_buckets_across_customers(
        self, app: Any, client: AsyncClient
    ) -> None:
        """Two customers' keys bucket independently."""
        conn = app.state.registry_db
        plaintext_alice, _ka, _ca = seed_customer_and_key(
            conn,
            customer_name="Alice",
            customer_email="alice@example.com",
            rate_limit_rpm=2,
        )
        plaintext_bob, _kb, _cb = seed_customer_and_key(
            conn,
            customer_name="Bob",
            customer_email="bob@example.com",
            rate_limit_rpm=5,
        )
        # Alice to ceiling (2), Bob to ceiling (5) — all 7 allowed.
        for _ in range(2):
            r = await client.post(
                "/v1/audio/speech",
                json=_SPEECH_BODY,
                headers={"Authorization": f"Bearer {plaintext_alice}"},
            )
            assert r.status_code == 200
        for _ in range(5):
            r = await client.post(
                "/v1/audio/speech",
                json=_SPEECH_BODY,
                headers={"Authorization": f"Bearer {plaintext_bob}"},
            )
            assert r.status_code == 200, r.json()

        # Alice's 3rd trips; Bob's 6th trips; neither affects the other.
        alice_trip = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext_alice}"},
        )
        assert alice_trip.status_code == 429
        bob_trip = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext_bob}"},
        )
        assert bob_trip.status_code == 429

    async def test_same_key_two_ips_shares_bucket(
        self, app: Any, client: AsyncClient
    ) -> None:
        """Per-key bucket is global across IPs (bucket keyed by key_id, not IP)."""
        plaintext, _kid, _cid = seed_customer_and_key(
            app.state.registry_db, rate_limit_rpm=2
        )
        auth = {"Authorization": f"Bearer {plaintext}"}
        # IP-1 exhausts the key's bucket.
        for _ in range(2):
            r = await client.post(
                "/v1/audio/speech",
                json=_SPEECH_BODY,
                headers={**auth, "X-Forwarded-For": "203.0.113.10"},
            )
            assert r.status_code == 200
        # IP-2 hits the SAME bucket — trips.
        trip = await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={**auth, "X-Forwarded-For": "203.0.113.11"},
        )
        assert trip.status_code == 429

    async def test_access_log_clean_on_429(
        self,
        app: Any,
        client: AsyncClient,
    ) -> None:
        """429 access log must not leak plaintext / hash / key_id / name."""
        import logging
        import re

        from comadre.keys.tokens import hash_api_key

        plaintext, kid, _cid = seed_customer_and_key(
            app.state.registry_db,
            customer_name="Probe Customer",
            rate_limit_rpm=1,
        )
        token_hash = hash_api_key(plaintext)
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        access_logger = logging.getLogger("access")
        handler = _Capture(level=logging.DEBUG)
        access_logger.addHandler(handler)
        try:
            auth = {"Authorization": f"Bearer {plaintext}"}
            ok = await client.post("/v1/audio/speech", json=_SPEECH_BODY, headers=auth)
            assert ok.status_code == 200
            trip = await client.post(
                "/v1/audio/speech", json=_SPEECH_BODY, headers=auth
            )
            assert trip.status_code == 429
        finally:
            access_logger.removeHandler(handler)

        assert records, "access logger emitted no record"
        # At least one record must correspond to the 429 response.
        assert any("429" in rec.getMessage() for rec in records), (
            "no access-log record for the 429 response"
        )
        # SHA-256 digests are 64 lowercase-hex chars — catch any
        # accidental leak of a token hash shape even if it's not our
        # specific test key's hash.
        sha256_shape = re.compile(r"\b[0-9a-f]{64}\b")
        # ULIDs are 26 chars of Crockford-base32 — catches any leak of
        # `key_<ULID>` or `cust_<ULID>` beyond the specific IDs we seeded.
        ulid_id_shape = re.compile(r"\b(?:key|cust)_[0-9A-HJKMNP-TV-Z]{26}\b")
        for record in records:
            rendered = record.getMessage()
            assert plaintext not in rendered
            assert token_hash not in rendered
            assert "cmdr_live_" not in rendered
            assert "Probe Customer" not in rendered
            assert kid not in rendered
            assert not sha256_shape.search(rendered), (
                f"access log leaked a SHA-256-shaped string: {rendered!r}"
            )
            assert not ulid_id_shape.search(rendered), (
                f"access log leaked a key_/cust_ ULID: {rendered!r}"
            )


class TestRequestCounters:
    """Story 2.3 — per-key counters on the /v1/audio/speech hot path.

    The ``app`` fixture in ``conftest`` does not attach
    ``request_counters`` (production lifespan does). These tests attach a
    fresh ``RequestCounters`` per-case so we exercise the ``keys/auth.py``
    and ``rate_limit.py`` integration points end-to-end.
    """

    @pytest.fixture(autouse=True)
    def _freeze_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from comadre.keys import auth as auth_module

        monkeypatch.setattr(
            auth_module, "_today_in_billing_tz", lambda _s: date(2026, 4, 17)
        )

    @pytest.fixture()
    def _counters(self, app: Any) -> Any:
        from comadre.counters import RequestCounters

        rc = RequestCounters(snapshot_path=None)
        app.state.request_counters = rc
        return rc

    async def test_happy_path_increments_requests_and_auth(
        self, app: Any, client: AsyncClient, _counters: Any
    ) -> None:
        plaintext, kid, _cid = seed_customer_and_key(
            app.state.registry_db, rate_limit_rpm=60
        )
        headers = {"Authorization": f"Bearer {plaintext}"}
        r = await client.post("/v1/audio/speech", json=_SPEECH_BODY, headers=headers)
        assert r.status_code == 200
        bucket = _counters.per_key[kid]
        assert bucket.requests_total == 1
        assert bucket.auth_success == 1
        assert bucket.rate_limit_429 == 0

    async def test_429_increments_rate_limit_counter(
        self, app: Any, client: AsyncClient, _counters: Any
    ) -> None:
        plaintext, kid, _cid = seed_customer_and_key(
            app.state.registry_db, rate_limit_rpm=2
        )
        headers = {"Authorization": f"Bearer {plaintext}"}
        for _ in range(2):
            r = await client.post(
                "/v1/audio/speech", json=_SPEECH_BODY, headers=headers
            )
            assert r.status_code == 200
        trip = await client.post("/v1/audio/speech", json=_SPEECH_BODY, headers=headers)
        assert trip.status_code == 429
        bucket = _counters.per_key[kid]
        # AC2 — 3 requests total (auth fired thrice), 3 auth_success,
        # 1 rate_limit_429.
        assert bucket.requests_total == 3
        assert bucket.auth_success == 3
        assert bucket.rate_limit_429 == 1

    async def test_two_keys_land_in_separate_buckets(
        self, app: Any, client: AsyncClient, _counters: Any
    ) -> None:
        plaintext_a, kid_a, _cid_a = seed_customer_and_key(
            app.state.registry_db,
            customer_name="Alice",
            customer_email="alice@example.com",
            rate_limit_rpm=10,
        )
        plaintext_b, kid_b, _cid_b = seed_customer_and_key(
            app.state.registry_db,
            customer_name="Bob",
            customer_email="bob@example.com",
            rate_limit_rpm=10,
        )
        await client.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext_a}"},
        )
        for _ in range(2):
            await client.post(
                "/v1/audio/speech",
                json=_SPEECH_BODY,
                headers={"Authorization": f"Bearer {plaintext_b}"},
            )
        assert _counters.per_key[kid_a].requests_total == 1
        assert _counters.per_key[kid_b].requests_total == 2
        assert kid_a != kid_b

    async def test_429_log_line_carries_key_id(
        self, app: Any, client: AsyncClient, _counters: Any
    ) -> None:
        """AC6 — the structured 429 log must include ``key_id`` + ``customer_id``."""
        import logging

        plaintext, kid, cid = seed_customer_and_key(
            app.state.registry_db, rate_limit_rpm=1
        )
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        rate_limit_logger = logging.getLogger("rate_limit")
        handler = _Capture(level=logging.DEBUG)
        rate_limit_logger.addHandler(handler)
        try:
            headers = {"Authorization": f"Bearer {plaintext}"}
            await client.post("/v1/audio/speech", json=_SPEECH_BODY, headers=headers)
            trip = await client.post(
                "/v1/audio/speech", json=_SPEECH_BODY, headers=headers
            )
            assert trip.status_code == 429
        finally:
            rate_limit_logger.removeHandler(handler)

        # Find the 429 log line.
        rendered = [rec.getMessage() for rec in records]
        hit = next((msg for msg in rendered if "Rate-limit 429" in msg), None)
        assert hit is not None, f"no 429 log captured; got {rendered!r}"
        assert f"key_id={kid}" in hit
        assert f"customer_id={cid}" in hit
        # AC6 PII guards — no bearer plaintext, no hash, no customer name.
        assert plaintext not in hit
        assert "cmdr_live_" not in hit


class TestCountersSnapshotLifespan:
    """Story 2.3 — lifespan provisions the snapshot writer.

    Drives lifespan directly via ``__aenter__`` / ``__aexit__`` instead of
    an ``AsyncClient`` round-trip, mirroring the ``_run_lifespan`` pattern
    in ``tests/test_main_lifespan.py``. That path both (a) runs the full
    startup + shutdown sequence and (b) keeps the test hermetic to the
    HTTP transport layer.
    """

    @pytest.fixture()
    def _registry_env(self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
        from cryptography.fernet import Fernet

        from comadre.config import get_settings

        db_path = tmp_path / "registry.db"
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )
        monkeypatch.setenv("QWEN3_ENABLED", "false")
        monkeypatch.setenv("VOICES_DIR", str(tmp_path))
        monkeypatch.setenv("NOISE_DIR", str(tmp_path))
        get_settings.cache_clear()
        return db_path

    @pytest.fixture()
    def _stub_engines(self, monkeypatch: pytest.MonkeyPatch) -> None:
        import comadre.main as main_module

        class _StubKokoro:
            def load_model(self, **_: object) -> None: ...
            def warm_up(self) -> None: ...

        class _StubQwen:
            def load_model(self, **_: object) -> None: ...
            def warm_up(self, **_: object) -> None: ...

        class _StubRouter:
            def __init__(self, **_: object) -> None: ...
            def available_voices(self) -> list[str]:
                return ["kokoro/pm_santa"]

            def _parse_voice(self, _voice: str) -> None:
                return None

        monkeypatch.setattr(main_module, "KokoroEngine", _StubKokoro)
        monkeypatch.setattr(main_module, "QwenEngine", _StubQwen)
        monkeypatch.setattr(main_module, "EngineRouter", _StubRouter)
        monkeypatch.setattr(main_module, "ensure_kokoro_models", lambda **_: None)
        monkeypatch.setattr(main_module, "ensure_qwen3_models", lambda **_: None)

    async def test_lifespan_creates_snapshot_and_mode_0600(
        self,
        _stub_engines: None,
        _registry_env: Path,
    ) -> None:
        """AC7 + AC16 — snapshot exists, valid JSON, mode 0600 after shutdown.

        The writer loop starts with a 15s sleep (the production interval).
        Rather than race that sleep, we let ``stop_snapshot_writer`` fire
        its best-effort final snapshot during lifespan ``__aexit__`` — the
        same code path that produces the last-before-restart snapshot in
        production.
        """
        import stat as stat_mod

        from fastapi import FastAPI

        from comadre.counters import counters_snapshot_path, default_replica_id
        from comadre.main import lifespan

        snapshot_path = counters_snapshot_path(
            _registry_env, replica_id=default_replica_id()
        )
        app = FastAPI()
        cm = lifespan(app)
        await cm.__aenter__()
        assert not snapshot_path.exists()
        # Register some traffic so the final snapshot has content worth
        # asserting on.
        app.state.request_counters.incr_request("key_probe")
        await cm.__aexit__(None, None, None)

        # Post-shutdown: final snapshot exists with mode 0600 and valid JSON.
        assert snapshot_path.exists()
        mode = stat_mod.S_IMODE(snapshot_path.stat().st_mode)
        assert mode == 0o600
        data = __import__("json").loads(snapshot_path.read_text(encoding="utf-8"))
        assert data["schema_version"] == 1
        assert "auth_cache" in data
        assert "per_key" in data
        assert data["per_key"]["key_probe"]["requests_total"] == 1

    async def test_lifespan_shutdown_cancels_task_cleanly(
        self,
        _stub_engines: None,
        _registry_env: Path,
    ) -> None:
        """AC16 — shutdown cancels the task; no CancelledError leak."""
        from fastapi import FastAPI

        from comadre.main import lifespan

        app = FastAPI()
        cm = lifespan(app)
        await cm.__aenter__()
        task = app.state.request_counters._task
        assert task is not None
        await cm.__aexit__(None, None, None)
        assert task.done()
        assert task.cancelled() or task.exception() is None


class TestMonetizationHealthEndpoint:
    """AC12 + AC13: /health with registry-mode auth."""

    @pytest.fixture(autouse=True)
    def _freeze_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from comadre.keys import auth as auth_module

        monkeypatch.setattr(
            auth_module, "_today_in_billing_tz", lambda _s: date(2026, 4, 17)
        )

    async def test_authenticated_health_has_full_detail(
        self, app: Any, client: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(app.state.registry_db)
        response = await client.get(
            "/health", headers={"Authorization": f"Bearer {plaintext}"}
        )
        assert response.status_code == 200
        body = response.json()
        for key in ("engines", "queue_depth", "uptime_seconds", "memory_mb", "version"):
            assert key in body

    async def test_unknown_key_returns_minimal_health(
        self, client: AsyncClient
    ) -> None:
        response = await client.get(
            "/health", headers={"Authorization": "Bearer unknown"}
        )
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"status", "voices"}
