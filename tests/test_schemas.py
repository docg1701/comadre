"""Tests for request/response schemas."""

import pytest
from pydantic import ValidationError

from comadre.schemas import Destination, ResponseFormat, SpeechRequest


class TestSpeechRequestDefaults:
    def test_valid_with_defaults(self) -> None:
        req = SpeechRequest(input="Hello world")
        assert req.input == "Hello world"
        assert req.voice is None
        assert req.response_format == ResponseFormat.ogg
        assert req.speed == 1.0
        assert req.destination == Destination.whatsapp

    def test_valid_with_all_fields(self) -> None:
        req = SpeechRequest(
            input="Test",
            voice="kokoro/pm_santa",
            response_format="wav",
            speed=2.0,
            destination="telegram",
        )
        assert req.voice == "kokoro/pm_santa"
        assert req.response_format == ResponseFormat.wav
        assert req.speed == 2.0
        assert req.destination == Destination.telegram


class TestSpeechRequestInputValidation:
    def test_empty_input_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SpeechRequest(input="")

    def test_single_char_input_accepted(self) -> None:
        req = SpeechRequest(input="A")
        assert req.input == "A"

    def test_at_global_limit_passes(self) -> None:
        req = SpeechRequest(input="a" * 500)
        assert len(req.input) == 500

    def test_over_global_limit_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SpeechRequest(input="a" * 501)


class TestSpeechRequestEnumValidation:
    def test_invalid_response_format_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SpeechRequest(input="test", response_format="mp3")

    def test_invalid_destination_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SpeechRequest(input="test", destination="discord")

    def test_valid_ogg_format(self) -> None:
        req = SpeechRequest(input="test", response_format="ogg")
        assert req.response_format == ResponseFormat.ogg

    def test_valid_wav_format(self) -> None:
        req = SpeechRequest(input="test", response_format="wav")
        assert req.response_format == ResponseFormat.wav


class TestSpeechRequestSpeed:
    def test_speed_at_min(self) -> None:
        req = SpeechRequest(input="test", speed=0.25)
        assert req.speed == 0.25

    def test_speed_at_max(self) -> None:
        req = SpeechRequest(input="test", speed=4.0)
        assert req.speed == 4.0

    def test_speed_below_min_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SpeechRequest(input="test", speed=0.1)

    def test_speed_above_max_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SpeechRequest(input="test", speed=5.0)


class TestSpeechRequestVoiceFormat:
    def test_kokoro_voice_accepted(self) -> None:
        req = SpeechRequest(input="test", voice="kokoro/pm_santa")
        assert req.voice == "kokoro/pm_santa"

    def test_qwen_voice_accepted(self) -> None:
        req = SpeechRequest(input="test", voice="qwen/galvani")
        assert req.voice == "qwen/galvani"

    def test_none_voice_accepted(self) -> None:
        req = SpeechRequest(input="test")
        assert req.voice is None

    def test_any_string_accepted_at_schema_level(self) -> None:
        """Schema allows any string — engine routing validates format."""
        req = SpeechRequest(input="test", voice="anything")
        assert req.voice == "anything"


class TestSpeechRequestQwenCharLimit:
    def test_qwen_at_limit_passes(self) -> None:
        req = SpeechRequest(input="a" * 300, voice="qwen/galvani")
        assert len(req.input) == 300

    def test_qwen_over_limit_rejected(self) -> None:
        with pytest.raises(ValidationError, match="300 character limit"):
            SpeechRequest(input="a" * 301, voice="qwen/galvani")

    def test_kokoro_at_500_passes(self) -> None:
        req = SpeechRequest(input="a" * 500, voice="kokoro/pm_santa")
        assert len(req.input) == 500

    def test_kokoro_over_500_rejected(self) -> None:
        with pytest.raises(ValidationError):
            SpeechRequest(input="a" * 501, voice="kokoro/pm_santa")

    def test_non_qwen_prefix_uses_global_limit(self) -> None:
        """Unknown prefix uses the global 500-char limit."""
        req = SpeechRequest(input="a" * 500, voice="unknown/voice")
        assert len(req.input) == 500
