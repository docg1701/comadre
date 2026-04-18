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


class TestDocsDisabled:
    """Verify OpenAPI documentation endpoints are disabled in production."""

    async def test_docs_returns_404(self, client: AsyncClient) -> None:
        response = await client.get("/docs")
        assert response.status_code == 404

    async def test_redoc_returns_404(self, client: AsyncClient) -> None:
        response = await client.get("/redoc")
        assert response.status_code == 404

    async def test_openapi_json_returns_404(self, client: AsyncClient) -> None:
        response = await client.get("/openapi.json")
        assert response.status_code == 404


_SPEECH_BODY: dict[str, str] = {
    "input": "olá mundo",
    "voice": "kokoro/pm_santa",
    "response_format": "ogg",
}


class TestMonetizationEnabledAuth:
    """End-to-end auth contract with ``MONETIZATION_ENABLED=true``.

    These tests exercise the registry-backed auth path through a real
    ``httpx.AsyncClient`` + ``AsyncTransport`` wrapping the FastAPI app.
    The matching legacy-mode tests continue to live in
    ``TestSpeechSuccess`` / ``TestAuthentication`` and stay unmodified
    (AC11 regression-gate).
    """

    @pytest.fixture(autouse=True)
    def _freeze_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Pin today to 2026-04-17 so billing branches are deterministic."""
        from comadre.keys import auth as auth_module

        monkeypatch.setattr(
            auth_module, "_today_in_billing_tz", lambda _s: date(2026, 4, 17)
        )

    async def test_valid_active_key_returns_200(
        self, app_monetized: Any, client_monetized: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(app_monetized.state.registry_db)
        response = await client_monetized.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == 200
        assert response.headers["content-type"] == "audio/ogg"
        assert response.content == b"fake-audio-bytes"

    async def test_suspended_key_returns_401_with_operator_hint(
        self, app_monetized: Any, client_monetized: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(
            app_monetized.state.registry_db, status="suspended"
        )
        response = await client_monetized.post(
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
        self, app_monetized: Any, client_monetized: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(
            app_monetized.state.registry_db, status="revoked"
        )
        response = await client_monetized.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["message"] == "Your API key has been revoked"
        assert "Contact Ana" in body["error"]["hint"]

    async def test_unknown_key_returns_401_legacy_envelope(
        self, client_monetized: AsyncClient
    ) -> None:
        response = await client_monetized.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": "Bearer cmdr_live_nonexistent_token"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["message"] == "Invalid or missing API key"
        assert body["error"]["type"] == "authentication_error"
        assert "Bearer" in body["error"]["hint"]

    async def test_malformed_authorization_returns_401_legacy_envelope(
        self, client_monetized: AsyncClient
    ) -> None:
        for header in ("", "Basic xyz", "Bearer", "BearerXYZ"):
            response = await client_monetized.post(
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
        self, app_monetized: Any, client_monetized: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(
            app_monetized.state.registry_db, paid_until="2020-01-01"
        )
        response = await client_monetized.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == 401
        body = response.json()
        assert body["error"]["message"] == "Your API key has been suspended"

    async def test_complimentary_null_paid_until_returns_200(
        self, app_monetized: Any, client_monetized: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(
            app_monetized.state.registry_db,
            billing_mode="complimentary",
            paid_until=None,
        )
        response = await client_monetized.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert response.status_code == 200

    async def test_response_headers_match_legacy_mode(
        self,
        app_monetized: Any,
        client_monetized: AsyncClient,
    ) -> None:
        """AC18: registry-mode and legacy-mode responses carry the same
        set of HTTP headers for a successful /v1/audio/speech.

        Legacy-mode comparison rebuilds a standalone app in-place rather
        than pulling the ``client`` fixture, because the ``app_monetized``
        fixture's ``monkeypatch.setenv("MONETIZATION_ENABLED", "true")``
        pollutes the ``mock_settings``-derived ``client`` fixture when
        both are requested in the same test.
        """
        import asyncio as _asyncio
        import time as _time

        from httpx import ASGITransport as _ASGITransport
        from httpx import AsyncClient as _AsyncClient
        from pydantic import SecretStr as _SecretStr

        from comadre.config import Settings as _Settings
        from comadre.main import create_app as _create_app

        legacy_settings = _Settings(
            api_key=_SecretStr("test-key-12345"),
            monetization_enabled=False,
        )
        legacy_app = _create_app()
        legacy_app.state.settings = legacy_settings
        legacy_app.state.router = app_monetized.state.router
        legacy_app.state.ready = True
        legacy_app.state.queue_lock = _asyncio.Lock()
        legacy_app.state.queue_depth = 0
        legacy_app.state.start_time = _time.monotonic()

        plaintext, _kid, _cid = seed_customer_and_key(app_monetized.state.registry_db)
        async with _AsyncClient(
            transport=_ASGITransport(app=legacy_app),
            base_url="http://test",
        ) as legacy_client:
            legacy = await legacy_client.post(
                "/v1/audio/speech",
                json=_SPEECH_BODY,
                headers={"Authorization": "Bearer test-key-12345"},
            )
        registry = await client_monetized.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert legacy.status_code == 200, legacy.json()
        assert registry.status_code == 200
        assert sorted(legacy.headers.items()) == sorted(registry.headers.items())
        assert legacy.content == registry.content

    async def test_no_audit_log_row_on_any_auth_outcome(
        self, app_monetized: Any, client_monetized: AsyncClient
    ) -> None:
        conn: sqlite3.Connection = app_monetized.state.registry_db
        plaintext_ok, _kid, _cid = seed_customer_and_key(conn)
        plaintext_susp, _, _ = seed_customer_and_key(
            conn, customer_email="x@y.com", status="suspended"
        )

        before = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]

        await client_monetized.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext_ok}"},
        )
        await client_monetized.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext_susp}"},
        )
        await client_monetized.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": "Bearer unknown-token"},
        )

        after = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        assert after == before

    async def test_last_used_at_not_written_on_success(
        self, app_monetized: Any, client_monetized: AsyncClient
    ) -> None:
        conn: sqlite3.Connection = app_monetized.state.registry_db
        plaintext, kid, _cid = seed_customer_and_key(conn)
        before = conn.execute(
            "SELECT last_used_at FROM api_key WHERE id = ?", (kid,)
        ).fetchone()["last_used_at"]

        response = await client_monetized.post(
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
        self, app_monetized: Any, client_monetized: AsyncClient
    ) -> None:
        conn: sqlite3.Connection = app_monetized.state.registry_db
        plaintext, _kid, _cid = seed_customer_and_key(conn)

        # Warm the cache.
        r1 = await client_monetized.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": f"Bearer {plaintext}"},
        )
        assert r1.status_code == 200

        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        try:
            r2 = await client_monetized.post(
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
        app_monetized: Any,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC9: sqlite3 error in lookup path yields 500 KeyRegistryError envelope."""
        from comadre.keys import auth as auth_module

        def _boom(_conn: Any, _key_hash: str) -> Any:
            raise sqlite3.OperationalError("disk I/O error")

        monkeypatch.setattr(auth_module, "lookup_key_auth", _boom)

        async with AsyncClient(
            transport=ASGITransport(app=app_monetized, raise_app_exceptions=False),
            base_url="http://test",
        ) as client:
            response = await client.post(
                "/v1/audio/speech",
                json=_SPEECH_BODY,
                headers={"Authorization": "Bearer cmdr_live_anything_here"},
            )
        assert response.status_code == 500
        body = response.json()
        assert body["error"]["message"] == (
            "Key registry database unreachable or corrupt"
        )
        assert body["error"]["type"] == "server_error"
        assert "KEY_REGISTRY_DB_PATH" in body["error"]["hint"]

        # Cache must not retain the failed lookup.
        snapshot = app_monetized.state.auth_cache.snapshot()
        assert snapshot["entries"] == 0

    async def test_access_log_does_not_leak_secrets(
        self,
        app_monetized: Any,
        client_monetized: AsyncClient,
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
            app_monetized.state.registry_db, customer_name="Helena Probe Sentinel"
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
            response = await client_monetized.post(
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
        self, app_monetized: Any, client_monetized: AsyncClient
    ) -> None:
        """AC14: not-found and suspended 401 envelopes diverge for callers
        who already proved possession of a real key (suspended branch). An
        attacker probing unknown tokens sees only the not-found envelope,
        which is byte-identical to the legacy ``AuthenticationError``
        envelope (covered by the unknown-key test above).
        """
        plaintext_susp, _kid, _cid = seed_customer_and_key(
            app_monetized.state.registry_db, status="suspended"
        )

        unknown = await client_monetized.post(
            "/v1/audio/speech",
            json=_SPEECH_BODY,
            headers={"Authorization": "Bearer cmdr_live_definitely_unknown"},
        )
        suspended = await client_monetized.post(
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
        self, client_monetized: AsyncClient
    ) -> None:
        """Non-ASCII tokens cannot match any stored hash and must yield the
        enumeration-resistant 401 envelope, NOT a 500. Regression for the
        ``hash_api_key`` ``encode("ascii")`` UnicodeEncodeError path.

        httpx rejects non-ASCII string header values client-side, but raw
        HTTP allows obs-text bytes (RFC 7230 §3.2.4) which Starlette decodes
        as latin-1. Pass the header as ``bytes`` to bypass httpx's encoding
        check and reproduce what a hostile client would send on the wire.
        """
        response = await client_monetized.post(
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


class TestMonetizationHealthEndpoint:
    """AC12 + AC13: /health with registry-mode auth."""

    @pytest.fixture(autouse=True)
    def _freeze_clock(self, monkeypatch: pytest.MonkeyPatch) -> None:
        from comadre.keys import auth as auth_module

        monkeypatch.setattr(
            auth_module, "_today_in_billing_tz", lambda _s: date(2026, 4, 17)
        )

    async def test_authenticated_health_has_full_detail(
        self, app_monetized: Any, client_monetized: AsyncClient
    ) -> None:
        plaintext, _kid, _cid = seed_customer_and_key(app_monetized.state.registry_db)
        response = await client_monetized.get(
            "/health", headers={"Authorization": f"Bearer {plaintext}"}
        )
        assert response.status_code == 200
        body = response.json()
        for key in ("engines", "queue_depth", "uptime_seconds", "memory_mb", "version"):
            assert key in body

    async def test_unknown_key_returns_minimal_health(
        self, client_monetized: AsyncClient
    ) -> None:
        response = await client_monetized.get(
            "/health", headers={"Authorization": "Bearer unknown"}
        )
        assert response.status_code == 200
        body = response.json()
        assert set(body.keys()) == {"status", "voices"}
