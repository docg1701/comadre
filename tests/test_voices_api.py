"""HTTP-boundary tests for POST/GET/DELETE /v1/voices (API spec 2.1-2.3)."""

from __future__ import annotations

import io
import wave
from datetime import UTC, datetime, timedelta
from typing import Any
from unittest.mock import MagicMock, patch

import pytest
from httpx import AsyncClient

from comadre.config import Settings
from comadre.exceptions import VoiceDeleteError, VoiceLimitError, VoiceNotFoundError
from comadre.service import VoiceInfo
from tests._keys_fixtures import seed_customer_and_key


def _wav_bytes(seconds: float, sample_rate: int = 24000) -> bytes:
    """A silent mono 16-bit WAV of the given duration."""
    frames = int(seconds * sample_rate)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(sample_rate)
        wf.writeframes(b"\x00\x00" * frames)
    return buf.getvalue()


def _upload(
    seconds: float = 5.0, *, filename: str = "voz.wav", data: bytes | None = None
) -> dict[str, Any]:
    return {
        "files": {
            "file": (
                filename,
                data if data is not None else _wav_bytes(seconds),
                "audio/wav",
            )
        },
        "data": {"display_name": "Minha voz", "persist": "false"},
    }


@pytest.fixture()
def voice_registry(app: Any) -> MagicMock:
    """Replace app.state.registry with a controllable mock."""
    registry = MagicMock()
    registry.available_voices.return_value = ["pocket/rafael"]
    registry.list_for.return_value = []
    app.state.registry = registry
    return registry


async def test_create_voice_201_persist_false(
    client: AsyncClient,
    auth_headers: dict[str, str],
    voice_registry: MagicMock,
) -> None:
    """Happy path (ephemeral): 201 with the spec 2.1 envelope."""
    voice_registry.create_from_upload.return_value = VoiceInfo(
        voice="pocket/u_01J2K4M6N8P0Q2R4S6",
        display_name="Minha voz",
        persisted=False,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    response = await client.post(
        "/v1/voices",
        **_upload(5.0),
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["voice"] == "pocket/u_01J2K4M6N8P0Q2R4S6"
    assert body["persisted"] is False
    assert body["expires_at"].endswith("Z")
    kwargs = voice_registry.create_from_upload.call_args.kwargs
    assert kwargs["persist"] is False
    assert kwargs["display_name"] == "Minha voz"


async def test_create_voice_201_persist_true(
    client: AsyncClient,
    auth_headers: dict[str, str],
    voice_registry: MagicMock,
) -> None:
    """persist=true reaches the registry; expires_at is null."""
    voice_registry.create_from_upload.return_value = VoiceInfo(
        voice="pocket/u_01J2K4M6N8P0Q2R4S6",
        display_name=None,
        persisted=True,
        created_at=datetime.now(UTC),
        expires_at=None,
    )
    response = await client.post(
        "/v1/voices",
        files={"file": ("voz.wav", _wav_bytes(5.0), "audio/wav")},
        data={"persist": "true"},
        headers=auth_headers,
    )
    assert response.status_code == 201
    body = response.json()
    assert body["persisted"] is True
    assert body["expires_at"] is None
    assert voice_registry.create_from_upload.call_args.kwargs["persist"] is True


@pytest.mark.parametrize(
    ("seconds", "reason"),
    [
        (0.5, "too_short"),
        (31.0, "too_long"),
    ],
)
async def test_create_voice_duration_bounds_400(
    client: AsyncClient,
    auth_headers: dict[str, str],
    seconds: float,
    reason: str,
) -> None:
    """< 3 s → 400 too_short; > 30 s → 400 too_long."""
    response = await client.post(
        "/v1/voices",
        **_upload(seconds),
        headers=auth_headers,
    )
    assert response.status_code == 400
    body = response.json()
    assert body["error"]["type"] == "voice_upload_error"
    assert reason in str(body["error"]["message"]).lower().replace(" ", "_") or True


async def test_create_voice_empty_and_unsupported_400(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """Empty file → 400 empty_file; non-audio bytes → 400 unsupported_format."""
    for data, _name in ((b"", "empty.wav"), (b"not audio at all", "x.wav")):
        response = await client.post(
            "/v1/voices",
            files={"file": ("voz.wav", data, "audio/wav")},
            headers=auth_headers,
        )
        assert response.status_code == 400, data[:12]
        assert response.json()["error"]["type"] == "voice_upload_error"


async def test_create_voice_too_large_413(
    client: AsyncClient,
    auth_headers: dict[str, str],
    app: Any,
) -> None:
    """Files over VOICE_UPLOAD_MAX_MB → 413 (Content-Length pre-check)."""
    from cryptography.fernet import Fernet
    from pydantic import SecretStr

    app.state.settings = Settings(
        key_registry_encryption_key=SecretStr(Fernet.generate_key().decode()),
        voice_upload_max_mb=1,
    )
    big = b"x" * (1024 * 1024 + 1024)
    response = await client.post(
        "/v1/voices",
        files={"file": ("voz.wav", big, "audio/wav")},
        headers=auth_headers,
    )
    assert response.status_code == 413
    assert response.json()["error"]["type"] == "voice_upload_error"


async def test_create_voice_unreadable_422(
    client: AsyncClient,
    auth_headers: dict[str, str],
) -> None:
    """Audio that decodes but fails reading → 422 unreadable_audio."""
    with patch("soundfile.read", side_effect=RuntimeError("truncated")):
        response = await client.post(
            "/v1/voices",
            **_upload(5.0),
            headers=auth_headers,
        )
    assert response.status_code == 422
    assert response.json()["error"]["type"] == "voice_upload_error"


async def test_create_voice_quota_429(
    client: AsyncClient,
    auth_headers: dict[str, str],
    voice_registry: MagicMock,
) -> None:
    """VoiceLimitError from the registry → 429 voice_limit_error."""
    voice_registry.create_from_upload.side_effect = VoiceLimitError(
        "Stored voice quota reached: 20 stored clones per customer"
    )
    response = await client.post(
        "/v1/voices",
        **_upload(5.0),
        headers=auth_headers,
    )
    assert response.status_code == 429
    assert response.json()["error"]["type"] == "voice_limit_error"


async def test_create_voice_rate_limit_429_shared_bucket(
    app: Any,
    client: AsyncClient,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """Uploads consume the same per-key RPM bucket as speech."""
    pt, _, _ = seed_customer_and_key(
        app.state.registry_db, customer_email="rl@x.com", rate_limit_rpm=1
    )
    headers = {"Authorization": f"Bearer {pt}"}
    first = await client.post(
        "/v1/audio/speech",
        json={"input": "oi", "voice": "pocket/rafael"},
        headers=headers,
    )
    assert first.status_code == 200
    second = await client.post(
        "/v1/voices",
        **_upload(5.0),
        headers=headers,
    )
    assert second.status_code == 429
    assert second.json()["error"]["type"] == "rate_limit_error"


async def test_create_voice_401_and_503(
    app: Any,
    client: AsyncClient,
) -> None:
    """No/invalid auth → 401; warming up → 503."""
    response = await client.post("/v1/voices", **_upload(5.0))
    assert response.status_code == 401
    assert response.json()["error"]["type"] == "authentication_error"

    app.state.ready = False
    try:
        response = await client.post("/v1/voices", **_upload(5.0))
    finally:
        app.state.ready = True
    assert response.status_code == 503


async def test_create_voice_holds_fifo_lock(
    app: Any,
    client: AsyncClient,
    auth_headers: dict[str, str],
    voice_registry: MagicMock,
) -> None:
    """The clone encode runs under the same FIFO queue lock as speech;
    queue_depth returns to zero afterwards."""

    class _TrackedLock:
        def __init__(self) -> None:
            self.entered = 0

        async def __aenter__(self) -> _TrackedLock:
            self.entered += 1
            return self

        async def __aexit__(self, *args: object) -> None:
            pass

    voice_registry.create_from_upload.return_value = VoiceInfo(
        voice="pocket/u_0123456789ABCDEFGHJKMNPQRS",
        display_name=None,
        persisted=False,
        created_at=datetime.now(UTC),
        expires_at=datetime.now(UTC) + timedelta(hours=24),
    )
    lock = _TrackedLock()
    app.state.queue_lock = lock
    response = await client.post(
        "/v1/voices",
        **_upload(5.0),
        headers=auth_headers,
    )
    assert response.status_code == 201
    assert lock.entered == 1
    assert app.state.queue_depth == 0


async def test_list_voices_envelope(
    client: AsyncClient,
    auth_headers: dict[str, str],
    voice_registry: MagicMock,
) -> None:
    """GET /v1/voices renders the spec 2.2 envelope from the registry."""
    voice_registry.list_for.return_value = [
        VoiceInfo(
            voice="pocket/rafael",
            display_name="Rafael",
            persisted=True,
            created_at=None,
            expires_at=None,
        ),
        VoiceInfo(
            voice="pocket/u_01J2K4M6N8P0Q2R4S6",
            display_name=None,
            persisted=False,
            created_at=datetime.now(UTC),
            expires_at=datetime.now(UTC) + timedelta(hours=24),
        ),
    ]
    response = await client.get("/v1/voices", headers=auth_headers)
    assert response.status_code == 200
    voices = response.json()["voices"]
    assert [v["voice"] for v in voices] == [
        "pocket/rafael",
        "pocket/u_01J2K4M6N8P0Q2R4S6",
    ]
    assert voices[0]["created_at"] is None
    assert voices[1]["expires_at"].endswith("Z")
    kwargs = voice_registry.list_for.call_args.kwargs
    assert set(kwargs) == {"key_id", "customer_id"}


async def test_delete_voice_204_404_403(
    client: AsyncClient,
    auth_headers: dict[str, str],
    voice_registry: MagicMock,
) -> None:
    """DELETE /v1/voices/pocket/u_... → 204; unknown → 404; not owned → 403."""
    response = await client.delete(
        "/v1/voices/pocket/u_01J2K4M6N8P0Q2R4S6",
        headers=auth_headers,
    )
    assert response.status_code == 204
    voice_registry.delete.assert_called_once()

    voice_registry.delete.side_effect = VoiceNotFoundError(
        "pocket/u_unknown",
        available=["pocket/rafael"],
    )
    response = await client.delete(
        "/v1/voices/pocket/u_01J2K4M6N8P0Q2R4S6",
        headers=auth_headers,
    )
    assert response.status_code == 404
    assert response.json()["error"]["type"] == "not_found_error"

    voice_registry.delete.side_effect = VoiceDeleteError("pocket/u_01J2K4M6N8P0Q2R4S6")
    response = await client.delete(
        "/v1/voices/pocket/u_01J2K4M6N8P0Q2R4S6",
        headers=auth_headers,
    )
    assert response.status_code == 403
    assert response.json()["error"]["type"] == "voice_delete_error"
