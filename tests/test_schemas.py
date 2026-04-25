"""Tests for request/response schemas.

Lean by design (test-suite review 2026-04-25): pydantic Field-constraint
tests collapsed (testing-the-framework); kept the custom model_validator
(qwen/ prefix → 300-char limit, fallback to global 500).
"""

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


def test_qwen_voice_enforces_300_char_limit() -> None:
    """Custom model_validator: qwen/ prefix shrinks the global 500 limit to 300."""
    SpeechRequest(input="a" * 300, voice="qwen/galvani")  # boundary OK
    with pytest.raises(ValidationError, match="300 character limit"):
        SpeechRequest(input="a" * 301, voice="qwen/galvani")


def test_non_qwen_voice_falls_back_to_global_500_char_limit() -> None:
    """Unknown / kokoro / None prefix → pydantic's global max_length=500 applies."""
    SpeechRequest(input="a" * 500, voice="kokoro/pm_santa")
    SpeechRequest(input="a" * 500, voice="unknown/voice")
    with pytest.raises(ValidationError):
        SpeechRequest(input="a" * 501, voice="kokoro/pm_santa")
