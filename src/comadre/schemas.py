"""Request schemas for Comadre API."""

from enum import StrEnum

from pydantic import BaseModel, Field


class ResponseFormat(StrEnum):
    """Supported audio output formats."""

    ogg = "ogg"
    mp3 = "mp3"
    wav = "wav"


_CHAR_LIMIT = 1000


class SpeechRequest(BaseModel):
    """Request body for the /v1/audio/speech endpoint."""

    input: str = Field(min_length=1, max_length=_CHAR_LIMIT)
    voice: str | None = None
    response_format: ResponseFormat = ResponseFormat.ogg
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    temperature: float | None = Field(
        default=None,
        ge=0.1,
        le=2.0,
        description=(
            "Sampling temperature override; lower sounds more consistent, "
            "higher more expressive. Omitted = engine default (0.7)."
        ),
    )
    seed: int | None = Field(
        default=None,
        ge=0,
        le=2**31 - 1,
        description=(
            "RNG seed for reproducible generation — same text, voice and "
            "seed produce identical prosody. Omitted = random."
        ),
    )
    raw: bool = Field(
        default=False,
        description="Skip audio post-processing (EQ, compression, noise mixing)",
    )
