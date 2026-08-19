"""Voice-clone endpoints — POST/GET/DELETE /v1/voices.

Contract: docs/pocket-tts-v3-api-spec.md sections 2.1-2.3. HTTP concerns
only — voice validation/encoding/storage live in service.py (VoiceRegistry)
and voice_storage.py.
"""

from __future__ import annotations

import asyncio
import re
import tempfile
import time
from datetime import UTC, datetime
from pathlib import Path

from fastapi import APIRouter, Depends, File, Form, Request, UploadFile
from fastapi.responses import JSONResponse, Response

from comadre.api import verify_ready
from comadre.config import Settings
from comadre.exceptions import (
    GenerationError,
    InvalidRequestError,
    VoiceNotFoundError,
    VoiceUnreadableError,
    VoiceUploadError,
    VoiceUploadTooLargeError,
)
from comadre.keys.auth import verify_api_key
from comadre.logging import get_logger
from comadre.rate_limit import check_rate_limit, check_speech_per_ip_rate_limit
from comadre.service import VoiceInfo, VoiceRegistry

logger = get_logger("request")

voices_router = APIRouter()

# display_name: up to 64 chars; letters, digits, spaces, - _ and apostrophe.
_DISPLAY_NAME_RE = re.compile(r"^[A-Za-z0-9 _'\-]{0,64}$")
_VOICE_PREFIX = "pocket/"
_CLONE_TIMEOUT_SECONDS = 120.0


def _iso_utc_or_none(dt: datetime | None) -> str | None:
    """RFC 3339 UTC timestamp (Z suffix) or None."""
    if dt is None:
        return None
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=UTC)
    return dt.astimezone(UTC).isoformat().replace("+00:00", "Z")


def _voice_list_json(voices: list[VoiceInfo]) -> dict[str, object]:
    return {
        "voices": [
            {
                "voice": v.voice,
                "display_name": v.display_name,
                "persisted": v.persisted,
                "created_at": _iso_utc_or_none(v.created_at),
                "expires_at": _iso_utc_or_none(v.expires_at),
            }
            for v in voices
        ]
    }


def _validate_display_name(display_name: str | None) -> str | None:
    """Validate the optional display_name form field (spec table 2.1)."""
    if display_name is None:
        return None
    value = display_name.strip()
    if not value:
        return None
    if not _DISPLAY_NAME_RE.match(value):
        raise InvalidRequestError(
            message="Invalid display_name: use up to 64 alphanumeric chars",
            hint=(
                "display_name allows letters, digits, spaces, hyphens,"
                " underscores and apostrophes."
            ),
        )
    return value


def _audio_checks(path: Path, settings: Settings) -> tuple[float, int]:
    """Validate the uploaded audio file (empty/format/duration/readable)."""
    import soundfile as sf

    if path.stat().st_size == 0:
        raise VoiceUploadError("empty_file")
    try:
        info = sf.info(str(path))
    except sf.LibsndfileError as exc:
        raise VoiceUploadError("unsupported_format") from exc
    if info.samplerate <= 0:
        raise VoiceUnreadableError()
    duration = float(info.frames / info.samplerate)
    if duration < settings.voice_ref_min_seconds:
        raise VoiceUploadError("too_short")
    if duration > settings.voice_ref_max_seconds:
        raise VoiceUploadError("too_long")
    try:
        data, _sr = sf.read(str(path), frames=1)
    except RuntimeError as exc:
        raise VoiceUnreadableError() from exc
    if data.size == 0:
        raise VoiceUnreadableError()
    return duration, info.samplerate


@voices_router.post(
    "/v1/voices",
    dependencies=[
        Depends(verify_ready),
        Depends(check_speech_per_ip_rate_limit),
        Depends(verify_api_key),
        Depends(check_rate_limit),
    ],
)
async def create_voice(
    request: Request,
    file: UploadFile = File(...),  # noqa: B008 — FastAPI dependency convention
    display_name: str | None = Form(None),
    persist: bool = Form(False),
) -> JSONResponse:
    """Create a voice clone from an uploaded reference audio (spec 2.1)."""
    settings: Settings = request.app.state.settings
    registry: VoiceRegistry = request.app.state.registry
    queue_lock = request.app.state.queue_lock

    display = _validate_display_name(display_name)

    max_bytes = settings.voice_upload_max_mb * 1024 * 1024
    content_length = request.headers.get("content-length")
    if (
        content_length is not None
        and content_length.isdigit()
        and int(content_length) > max_bytes
    ):
        raise VoiceUploadTooLargeError(settings.voice_upload_max_mb)

    # Stream the upload to a temp file with a running size guard.
    with tempfile.NamedTemporaryFile(suffix=".audio", delete=False) as tmp:
        tmp_path = Path(tmp.name)
    try:
        total = 0
        with tmp_path.open("wb") as out:
            while True:
                chunk = await file.read(1024 * 1024)
                if not chunk:
                    break
                total += len(chunk)
                if total > max_bytes:
                    raise VoiceUploadTooLargeError(settings.voice_upload_max_mb)
                out.write(chunk)

        duration_s, sample_rate = await asyncio.to_thread(
            _audio_checks, tmp_path, settings
        )

        auth_payload = getattr(request.state, "auth_payload", None)
        key_id = getattr(auth_payload, "key_id", "")
        customer_id = getattr(auth_payload, "customer_id", "")

        # Clone encoding shares the per-replica FIFO lock with speech.
        start = time.monotonic()
        request.app.state.queue_depth += 1
        try:
            async with queue_lock:
                try:
                    info = await asyncio.wait_for(
                        asyncio.to_thread(
                            registry.create_from_upload,
                            tmp_path,
                            key_id=key_id,
                            customer_id=customer_id,
                            display_name=display,
                            persist=persist,
                        ),
                        timeout=_CLONE_TIMEOUT_SECONDS,
                    )
                except TimeoutError as exc:
                    logger.warning(
                        "Voice clone encoding timed out after 120s (key=%s)",
                        key_id,
                    )
                    raise GenerationError(
                        "Voice clone encoding timed out after 120 seconds"
                    ) from exc
        finally:
            request.app.state.queue_depth -= 1

        logger.info(
            "POST /v1/voices voice=%s persist=%s duration=%.1fs encode=%.1fs",
            info.voice,
            persist,
            duration_s,
            time.monotonic() - start,
        )
        return JSONResponse(
            status_code=201,
            content={
                "voice": info.voice,
                "display_name": info.display_name,
                "persisted": info.persisted,
                "duration_s": duration_s,
                "sample_rate": sample_rate,
                "expires_at": _iso_utc_or_none(info.expires_at),
            },
        )
    finally:
        await file.close()
        tmp_path.unlink(missing_ok=True)


@voices_router.get(
    "/v1/voices",
    dependencies=[
        Depends(verify_ready),
        Depends(check_speech_per_ip_rate_limit),
        Depends(verify_api_key),
        Depends(check_rate_limit),
    ],
)
async def list_voices(request: Request) -> JSONResponse:
    """List operator voices + the callers own clones (spec 2.2)."""
    registry: VoiceRegistry = request.app.state.registry
    auth_payload = getattr(request.state, "auth_payload", None)
    key_id = getattr(auth_payload, "key_id", "")
    customer_id = getattr(auth_payload, "customer_id", "")
    voices = registry.list_for(key_id=key_id, customer_id=customer_id)
    return JSONResponse(content=_voice_list_json(voices))


@voices_router.delete(
    "/v1/voices/{name:path}",
    dependencies=[
        Depends(verify_ready),
        Depends(check_speech_per_ip_rate_limit),
        Depends(verify_api_key),
        Depends(check_rate_limit),
    ],
)
async def delete_voice(request: Request, name: str) -> Response:
    """Delete a stored or ephemeral clone owned by the caller (spec 2.3)."""
    registry: VoiceRegistry = request.app.state.registry
    auth_payload = getattr(request.state, "auth_payload", None)
    key_id = getattr(auth_payload, "key_id", "")
    customer_id = getattr(auth_payload, "customer_id", "")

    if not name.startswith(_VOICE_PREFIX) or len(name) <= len(_VOICE_PREFIX):
        raise VoiceNotFoundError(voice=name, available=registry.available_voices())
    bare_name = name[len(_VOICE_PREFIX) :]
    registry.delete(bare_name, key_id=key_id, customer_id=customer_id)
    logger.info("DELETE /v1/voices/%s key=%s", bare_name, key_id)
    return Response(status_code=204)
