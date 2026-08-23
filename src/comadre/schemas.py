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
    raw: bool = Field(
        default=False,
        description="Skip audio post-processing (EQ, compression, noise mixing)",
    )
