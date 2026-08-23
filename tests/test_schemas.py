"""Tests for request/response schemas — v3 single 1000-char limit."""

import pytest
from pydantic import ValidationError

from comadre.schemas import ResponseFormat, SpeechRequest


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
