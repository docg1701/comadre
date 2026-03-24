"""Tests for the custom exception hierarchy."""

from cumadre.exceptions import (
    CumadreError,
    GenerationError,
    InvalidRequestError,
    VoiceNotFoundError,
)


class TestCumadreError:
    def test_message_attribute(self) -> None:
        err = CumadreError(
            "something broke",
            status_code=500,
            error_type="server_error",
            hint="try again",
        )
        assert err.message == "something broke"
        assert str(err) == "something broke"

    def test_status_code(self) -> None:
        err = CumadreError(
            "bad", status_code=418, error_type="teapot", hint="brew coffee"
        )
        assert err.status_code == 418

    def test_error_type(self) -> None:
        err = CumadreError("bad", status_code=400, error_type="custom_type", hint="")
        assert err.error_type == "custom_type"

    def test_hint(self) -> None:
        err = CumadreError("bad", status_code=400, error_type="t", hint="helpful hint")
        assert err.hint == "helpful hint"

    def test_is_exception(self) -> None:
        err = CumadreError("x", status_code=500, error_type="e", hint="h")
        assert isinstance(err, Exception)


class TestVoiceNotFoundError:
    def test_status_code(self) -> None:
        err = VoiceNotFoundError(voice="ghost", available=["alice", "bob"])
        assert err.status_code == 404

    def test_error_type(self) -> None:
        err = VoiceNotFoundError(voice="ghost", available=[])
        assert err.error_type == "not_found_error"

    def test_message_contains_voice_name(self) -> None:
        err = VoiceNotFoundError(voice="ghost", available=["alice"])
        assert "ghost" in err.message

    def test_hint_contains_available_voices(self) -> None:
        err = VoiceNotFoundError(voice="ghost", available=["alice", "bob"])
        assert "alice" in err.hint
        assert "bob" in err.hint

    def test_voice_attribute(self) -> None:
        err = VoiceNotFoundError(voice="ghost", available=["alice"])
        assert err.voice == "ghost"

    def test_available_attribute(self) -> None:
        err = VoiceNotFoundError(voice="ghost", available=["alice", "bob"])
        assert err.available == ["alice", "bob"]

    def test_is_cumadre_error(self) -> None:
        err = VoiceNotFoundError(voice="x", available=[])
        assert isinstance(err, CumadreError)


class TestInvalidRequestError:
    def test_status_code(self) -> None:
        err = InvalidRequestError(message="too long", hint="shorten it")
        assert err.status_code == 400

    def test_error_type(self) -> None:
        err = InvalidRequestError(message="too long", hint="shorten it")
        assert err.error_type == "invalid_request_error"

    def test_message(self) -> None:
        err = InvalidRequestError(message="text too long", hint="shorten")
        assert err.message == "text too long"

    def test_hint(self) -> None:
        err = InvalidRequestError(message="bad", hint="fix this")
        assert err.hint == "fix this"

    def test_is_cumadre_error(self) -> None:
        err = InvalidRequestError(message="x", hint="h")
        assert isinstance(err, CumadreError)


class TestGenerationError:
    def test_status_code(self) -> None:
        err = GenerationError("model crashed")
        assert err.status_code == 500

    def test_error_type(self) -> None:
        err = GenerationError("model crashed")
        assert err.error_type == "server_error"

    def test_message(self) -> None:
        err = GenerationError("model crashed")
        assert err.message == "model crashed"

    def test_hint_is_standard(self) -> None:
        err = GenerationError("anything")
        assert "server logs" in err.hint.lower() or "traceback" in err.hint.lower()

    def test_is_cumadre_error(self) -> None:
        err = GenerationError("x")
        assert isinstance(err, CumadreError)
