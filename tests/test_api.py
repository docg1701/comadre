"""Tests for speech endpoint HTTP behavior."""

from __future__ import annotations

from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient

from comadre.exceptions import VoiceNotFoundError


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
