"""Request and response schemas for CUMADRE API."""

from enum import StrEnum

from pydantic import BaseModel, Field, model_validator


class ResponseFormat(StrEnum):
    """Supported audio output formats."""

    ogg = "ogg"
    wav = "wav"


class Destination(StrEnum):
    """Target messaging platform for audio optimization."""

    whatsapp = "whatsapp"
    telegram = "telegram"
    messenger = "messenger"
    instagram = "instagram"


_KOKORO_VOICES = frozenset({"santa", "dora", "alex"})
_QWEN_VOICES = frozenset({"clone", "qwen-female", "qwen-male"})
_KOKORO_CHAR_LIMIT = 500
_QWEN_CHAR_LIMIT = 300


class SpeechRequest(BaseModel):
    """Request body for the /v1/audio/speech endpoint."""

    input: str = Field(min_length=1, max_length=_KOKORO_CHAR_LIMIT)
    voice: str | None = None
    response_format: ResponseFormat = ResponseFormat.ogg
    speed: float = Field(default=1.0, ge=0.25, le=4.0)
    destination: Destination = Destination.whatsapp

    @model_validator(mode="after")
    def _validate_char_limit(self) -> "SpeechRequest":
        if self.voice is None:
            return self
        if self.voice in _KOKORO_VOICES and len(self.input) > _KOKORO_CHAR_LIMIT:
            msg = (
                f"Input exceeds {_KOKORO_CHAR_LIMIT} character limit"
                f" for Kokoro engine (voice '{self.voice}')"
            )
            raise ValueError(msg)
        if self.voice in _QWEN_VOICES and len(self.input) > _QWEN_CHAR_LIMIT:
            msg = (
                f"Input exceeds {_QWEN_CHAR_LIMIT} character limit"
                f" for Qwen3 engine (voice '{self.voice}')"
            )
            raise ValueError(msg)
        return self
