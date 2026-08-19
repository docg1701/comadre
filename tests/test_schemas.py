"""Tests for request/response schemas.

v3: single 1000-char limit (no per-engine validator) + the new voice
response models.
"""

import pytest
from pydantic import ValidationError

from comadre.schemas import (
    ResponseFormat,
    SpeechRequest,
    VoiceCreateResponse,
    VoiceListItem,
    VoiceListResponse,
)


def test_speech_request_defaults_round_trip() -> None:
    req = SpeechRequest(input="Hello world")
    assert (req.input, req.voice, req.response_format, req.speed, req.raw) == (
        "Hello world",
        None,
        ResponseFormat.ogg,
        1.0,
        False,
    )


def test_single_1000_char_limit() -> None:
    """v3: one limit for every voice — 1000 chars."""
    SpeechRequest(input="a" * 1000, voice="pocket/rafael")  # boundary OK
    SpeechRequest(input="a" * 1000, voice="pocket/u_01J2K4M6N8P0Q2R4S6")
    with pytest.raises(ValidationError):
        SpeechRequest(input="a" * 1001, voice="pocket/rafael")


def test_speed_bounds() -> None:
    """speed stays 0.25-4.0 (applied via ffmpeg atempo in v3)."""
    SpeechRequest(input="oi", speed=0.25)
    SpeechRequest(input="oi", speed=4.0)
    with pytest.raises(ValidationError):
        SpeechRequest(input="oi", speed=0.24)
    with pytest.raises(ValidationError):
        SpeechRequest(input="oi", speed=4.1)


def test_voice_list_models() -> None:
    """VoiceListItem / VoiceListResponse validate the spec 2.2 shape."""
    item = VoiceListItem(
        voice="pocket/u_01J2K4M6N8P0Q2R4S6",
        display_name="Minha voz",
        persisted=True,
        created_at=None,
        expires_at=None,
    )
    assert item.voice.startswith("pocket/")
    resp = VoiceListResponse(voices=[item])
    assert resp.voices[0].display_name == "Minha voz"


def test_voice_create_response_model() -> None:
    """VoiceCreateResponse validates the spec 2.1 shape."""
    resp = VoiceCreateResponse(
        voice="pocket/u_01J2K4M6N8P0Q2R4S6",
        display_name=None,
        persisted=False,
        duration_s=8.4,
        sample_rate=24000,
        expires_at=None,
    )
    assert resp.sample_rate == 24000
