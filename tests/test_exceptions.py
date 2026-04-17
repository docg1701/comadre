"""Tests for the custom exception hierarchy."""

import json

from starlette.requests import Request

from comadre.exceptions import (
    AuthenticationError,
    ComadreError,
    GenerationError,
    InvalidRequestError,
    InvalidTaxIdError,
    KeyRegistryError,
    ServiceUnavailableError,
    VoiceNotFoundError,
    comadre_error_handler,
    register_exception_handlers,
    unhandled_error_handler,
)


class TestComadreError:
    def test_message_attribute(self) -> None:
        err = ComadreError(
            "something broke",
            status_code=500,
            error_type="server_error",
            hint="try again",
        )
        assert err.message == "something broke"
        assert str(err) == "something broke"

    def test_status_code(self) -> None:
        err = ComadreError(
            "bad", status_code=418, error_type="teapot", hint="brew coffee"
        )
        assert err.status_code == 418

    def test_error_type(self) -> None:
        err = ComadreError("bad", status_code=400, error_type="custom_type", hint="")
        assert err.error_type == "custom_type"

    def test_hint(self) -> None:
        err = ComadreError("bad", status_code=400, error_type="t", hint="helpful hint")
        assert err.hint == "helpful hint"

    def test_is_exception(self) -> None:
        err = ComadreError("x", status_code=500, error_type="e", hint="h")
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

    def test_is_comadre_error(self) -> None:
        err = VoiceNotFoundError(voice="x", available=[])
        assert isinstance(err, ComadreError)


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

    def test_is_comadre_error(self) -> None:
        err = InvalidRequestError(message="x", hint="h")
        assert isinstance(err, ComadreError)


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

    def test_is_comadre_error(self) -> None:
        err = GenerationError("x")
        assert isinstance(err, ComadreError)


class TestAuthenticationError:
    def test_status_code(self) -> None:
        err = AuthenticationError()
        assert err.status_code == 401

    def test_error_type(self) -> None:
        err = AuthenticationError()
        assert err.error_type == "authentication_error"

    def test_default_message(self) -> None:
        err = AuthenticationError()
        assert err.message == "Invalid or missing API key"

    def test_custom_message(self) -> None:
        err = AuthenticationError("Token expired")
        assert err.message == "Token expired"

    def test_hint_mentions_bearer_format(self) -> None:
        err = AuthenticationError()
        assert "Bearer" in err.hint
        assert "API_KEY" not in err.hint

    def test_is_comadre_error(self) -> None:
        err = AuthenticationError()
        assert isinstance(err, ComadreError)


class TestServiceUnavailableError:
    def test_status_code(self) -> None:
        err = ServiceUnavailableError()
        assert err.status_code == 503

    def test_error_type(self) -> None:
        err = ServiceUnavailableError()
        assert err.error_type == "service_unavailable"

    def test_default_message(self) -> None:
        err = ServiceUnavailableError()
        assert err.message == "Service is warming up"

    def test_custom_message(self) -> None:
        err = ServiceUnavailableError("Models loading")
        assert err.message == "Models loading"

    def test_default_retry_seconds(self) -> None:
        err = ServiceUnavailableError()
        assert err.retry_seconds == 30
        assert "30" in err.hint

    def test_custom_retry_seconds(self) -> None:
        err = ServiceUnavailableError(retry_seconds=60)
        assert err.retry_seconds == 60
        assert "60" in err.hint

    def test_hint_mentions_loading(self) -> None:
        err = ServiceUnavailableError()
        assert "loading models" in err.hint.lower()

    def test_is_comadre_error(self) -> None:
        err = ServiceUnavailableError()
        assert isinstance(err, ComadreError)


class TestInvalidTaxIdError:
    def test_cpf_status_code(self) -> None:
        err = InvalidTaxIdError("cpf")
        assert err.status_code == 400

    def test_cpf_error_type(self) -> None:
        err = InvalidTaxIdError("cpf")
        assert err.error_type == "invalid_request_error"

    def test_cpf_message_is_static(self) -> None:
        err = InvalidTaxIdError("cpf")
        assert err.message == "Invalid CPF: checksum verification failed"

    def test_cnpj_message_is_static(self) -> None:
        err = InvalidTaxIdError("cnpj")
        assert err.message == "Invalid CNPJ: checksum verification failed"

    def test_cpf_hint_is_static(self) -> None:
        err = InvalidTaxIdError("cpf")
        assert err.hint == "Verify the CPF digits and try again."

    def test_cnpj_hint_is_static(self) -> None:
        err = InvalidTaxIdError("cnpj")
        assert err.hint == "Verify the CNPJ digits and try again."

    def test_kind_attribute(self) -> None:
        err = InvalidTaxIdError("cpf")
        assert err.kind == "cpf"

    def test_is_comadre_error(self) -> None:
        err = InvalidTaxIdError("cnpj")
        assert isinstance(err, ComadreError)

    def test_has_no_value_attribute(self) -> None:
        """FR37/NFR16 anti-enumeration: no attribute stores the raw input."""
        err = InvalidTaxIdError("cpf")
        for forbidden_attr in ("value", "raw", "input", "digits", "tax_id"):
            assert not hasattr(err, forbidden_attr)

    def test_constructor_takes_no_value(self) -> None:
        """Compile-time guard: cannot pass raw CPF/CNPJ to the exception."""
        import inspect

        sig = inspect.signature(InvalidTaxIdError.__init__)
        params = set(sig.parameters.keys()) - {"self"}
        assert params == {"kind"}


class TestKeyRegistryError:
    def test_status_code(self) -> None:
        err = KeyRegistryError()
        assert err.status_code == 500

    def test_error_type(self) -> None:
        err = KeyRegistryError()
        assert err.error_type == "server_error"

    def test_default_message(self) -> None:
        err = KeyRegistryError()
        assert err.message == "Key registry database unreachable or corrupt"

    def test_custom_message(self) -> None:
        err = KeyRegistryError("disk full")
        assert err.message == "disk full"

    def test_hint_mentions_path_and_mode(self) -> None:
        err = KeyRegistryError()
        assert "KEY_REGISTRY_DB_PATH" in err.hint
        assert "0600" in err.hint

    def test_is_comadre_error(self) -> None:
        err = KeyRegistryError()
        assert isinstance(err, ComadreError)


def _mock_request() -> Request:
    """Create a minimal mock Request for handler tests."""
    scope = {"type": "http", "method": "POST", "path": "/v1/audio/speech"}
    return Request(scope)


def _response_json(resp: object) -> dict[str, object]:
    """Extract JSON body from a JSONResponse."""
    body = getattr(resp, "body", b"")
    result: dict[str, object] = json.loads(
        body if isinstance(body, bytes) else bytes(body)
    )
    return result


class TestComadreErrorHandler:
    async def test_returns_correct_status_code(self) -> None:
        exc = VoiceNotFoundError(voice="ghost", available=["santa"])
        resp = await comadre_error_handler(_mock_request(), exc)
        assert resp.status_code == 404

    async def test_returns_json_with_error_key(self) -> None:
        exc = InvalidRequestError(message="too long", hint="shorten it")
        resp = await comadre_error_handler(_mock_request(), exc)
        body = _response_json(resp)
        assert "error" in body

    async def test_json_has_all_three_fields(self) -> None:
        exc = AuthenticationError()
        resp = await comadre_error_handler(_mock_request(), exc)
        error = _response_json(resp)["error"]
        assert isinstance(error, dict)
        assert "message" in error
        assert "type" in error
        assert "hint" in error

    async def test_json_values_match_exception(self) -> None:
        exc = GenerationError("model crashed")
        resp = await comadre_error_handler(_mock_request(), exc)
        error = _response_json(resp)["error"]
        assert isinstance(error, dict)
        assert error["message"] == "model crashed"
        assert error["type"] == "server_error"
        assert "server logs" in error["hint"].lower()

    async def test_service_unavailable_status(self) -> None:
        exc = ServiceUnavailableError()
        resp = await comadre_error_handler(_mock_request(), exc)
        assert resp.status_code == 503


class TestUnhandledErrorHandler:
    async def test_returns_500(self) -> None:
        exc = RuntimeError("unexpected boom")
        resp = await unhandled_error_handler(_mock_request(), exc)
        assert resp.status_code == 500

    async def test_returns_generic_message(self) -> None:
        exc = RuntimeError("secret internal detail")
        resp = await unhandled_error_handler(_mock_request(), exc)
        error = _response_json(resp)["error"]
        assert isinstance(error, dict)
        assert error["type"] == "server_error"
        assert "secret" not in error["message"]
        assert "secret" not in error["hint"]

    async def test_does_not_leak_traceback(self) -> None:
        exc = ValueError("sensitive data")
        resp = await unhandled_error_handler(_mock_request(), exc)
        body = _response_json(resp)
        assert "sensitive data" not in json.dumps(body)
        assert "Traceback" not in json.dumps(body)

    async def test_hint_references_logs(self) -> None:
        exc = RuntimeError("oops")
        resp = await unhandled_error_handler(_mock_request(), exc)
        error = _response_json(resp)["error"]
        assert isinstance(error, dict)
        assert "log" in str(error["hint"]).lower()


class TestRegisterExceptionHandlers:
    def test_registers_comadre_error_handler(self) -> None:
        from fastapi import FastAPI

        app = FastAPI()
        register_exception_handlers(app)
        assert ComadreError in app.exception_handlers

    def test_registers_unhandled_error_handler(self) -> None:
        from fastapi import FastAPI

        app = FastAPI()
        register_exception_handlers(app)
        assert Exception in app.exception_handlers
