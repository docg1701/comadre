"""Request and response schemas for Comadre API."""

from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, Field


class ResponseFormat(StrEnum):
    """Supported audio output formats."""

    ogg = "ogg"
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


class VoiceListItem(BaseModel):
    """One voice in the GET /v1/voices listing."""

    voice: str
    display_name: str | None
    persisted: bool
    created_at: datetime | None
    expires_at: datetime | None


class VoiceListResponse(BaseModel):
    """Response body for GET /v1/voices."""

    voices: list[VoiceListItem]


class VoiceCreateResponse(BaseModel):
    """Response body for POST /v1/voices (API spec section 2.1)."""

    voice: str
    display_name: str | None
    persisted: bool
    duration_s: float
    sample_rate: int
    expires_at: datetime | None
