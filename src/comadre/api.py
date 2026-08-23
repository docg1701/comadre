"""Speech endpoint route handler for Comadre."""

from __future__ import annotations

import asyncio
import time
from pathlib import Path

from fastapi import APIRouter, Depends, Request, Response

from comadre.exceptions import (
    GenerationError,
    ServiceUnavailableError,
)
from comadre.keys.auth import verify_api_key
from comadre.logging import get_logger
from comadre.rate_limit import check_rate_limit, check_speech_per_ip_rate_limit
from comadre.schemas import ResponseFormat, SpeechRequest

logger = get_logger("request")

api_router = APIRouter()


async def verify_ready(request: Request) -> None:
    """Reject requests during startup warm-up."""
    if not getattr(request.app.state, "ready", False):
        raise ServiceUnavailableError(
            message="Service is warming up, engines not yet loaded",
            retry_seconds=30,
        )


@api_router.post(
    "/v1/audio/speech",
    dependencies=[
        Depends(verify_ready),
        # F20 — per-IP rate-limit gate runs BEFORE auth so denied-key
        # spammers cannot bypass the per-key bucket. Generous 600/min/IP
        # to keep NAT-shared legitimate users unaffected.
        Depends(check_speech_per_ip_rate_limit),
        Depends(verify_api_key),
        Depends(check_rate_limit),
    ],
)
async def generate_speech(
    request: Request,
    body: SpeechRequest,
) -> Response:
    """Generate speech audio from text input."""
    settings = request.app.state.settings
    engine = request.app.state.engine
    queue_lock = request.app.state.queue_lock

    # Resolve default voice (AC #4)
    voice = body.voice or settings.default_voice

    # Registry key id for ephemeral-clone resolution (set by verify_api_key).
    auth_payload = getattr(request.state, "auth_payload", None)
    key_id: str | None = getattr(auth_payload, "key_id", None)

    # Determine media type
    media_type = {
        ResponseFormat.ogg: "audio/ogg",
        ResponseFormat.mp3: "audio/mpeg",
        ResponseFormat.wav: "audio/wav",
    }[body.response_format]
    extension = body.response_format.value
    voice_slug = voice.removeprefix("pocket/").replace("/", "_")

    start = time.monotonic()

    # Acquire FIFO queue (AC #7)
    request.app.state.queue_depth += 1
    try:
        async with queue_lock:
            # Generate with timeout (AC #8)
            try:
                audio_bytes = await asyncio.wait_for(
                    asyncio.to_thread(
                        engine.generate_speech,
                        text=body.input,
                        voice_name=voice,
                        response_format=body.response_format.value,
                        noise_dir=Path(settings.noise_dir),
                        speed=body.speed,
                        raw=body.raw,
                        key_id=key_id,
                        temperature=body.temperature,
                        seed=body.seed,
                    ),
                    timeout=120.0,
                )
            except TimeoutError as exc:
                logger.warning(
                    "Generation timed out for voice=%s — orphaned thread"
                    " may still be running in the background",
                    voice,
                )
                raise GenerationError(
                    f"Speech generation timed out after 120 seconds for voice '{voice}'"
                ) from exc
    finally:
        request.app.state.queue_depth -= 1

    duration = time.monotonic() - start
    logger.info(
        "POST /v1/audio/speech voice=%s format=%s chars=%d duration=%.1fs",
        voice,
        extension,
        len(body.input),
        duration,
    )

    return Response(
        content=audio_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": (
                f'attachment; filename="comadre-{voice_slug}.{extension}"'
            ),
        },
    )
