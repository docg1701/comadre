"""Tests for the ComadreError hierarchy + handler.

Lean by design (test-suite review 2026-04-25): per-class
status_code/error_type/hint/is_comadre_error checks were pure
attribute-readback tautologies. What survives are properties no class
constructor enforces — anti-enumeration envelope identity, format-string
safety, and the handler's JSON envelope shape.
"""

from __future__ import annotations

import json

from starlette.requests import Request

from comadre.exceptions import (
    ApiKeyNotFoundError,
    ApiKeyRevokedError,
    ApiKeySuspendedError,
    AuthenticationError,
    InvalidRequestError,
    InvalidTaxIdError,
    VoiceNotFoundError,
    comadre_error_handler,
)


def _mock_request() -> Request:
    return Request({"type": "http", "method": "POST", "path": "/v1/audio/speech"})


def _response_json(resp: object) -> dict[str, object]:
    body = getattr(resp, "body", b"")
    return json.loads(body if isinstance(body, bytes) else bytes(body))


def test_api_key_not_found_envelope_is_byte_identical_to_authentication_error() -> None:
    """FR26 anti-enumeration: a DB-miss MUST NOT be distinguishable
    from a malformed bearer at the HTTP layer."""
    not_found = ApiKeyNotFoundError()
    legacy = AuthenticationError()
    assert not_found.message == legacy.message
    assert not_found.error_type == legacy.error_type
    assert not_found.hint == legacy.hint
    assert not_found.status_code == legacy.status_code


def test_suspended_revoked_hints_interpolate_operator_contact_safely() -> None:
    """The hint format has ``{operator_contact_hint}`` as the ONLY
    placeholder — operator-supplied braces (e.g. ``Contact {admin}!``)
    must remain literal, not get interpreted by str.format()."""
    suspended = ApiKeySuspendedError(operator_contact_hint="Contact {admin}!")
    revoked = ApiKeyRevokedError(operator_contact_hint="Contact {admin}!")
    for err in (suspended, revoked):
        assert err.hint.endswith("Contact {admin}!")
        assert "{admin}" in err.hint
        assert "{operator_contact_hint}" not in err.hint


def test_voice_not_found_hint_lists_available_voices() -> None:
    """The 404 helps the user recover by listing what IS available."""
    err = VoiceNotFoundError(voice="ghost", available=["alice", "bob"])
    assert err.status_code == 404
    assert "ghost" in err.message
    assert "alice" in err.hint
    assert "bob" in err.hint


def test_invalid_tax_id_error_carries_kind_and_400_status() -> None:
    err = InvalidTaxIdError("cpf")
    assert err.status_code == 400
    assert "cpf" in err.message.lower()


async def test_comadre_error_handler_renders_full_envelope() -> None:
    """The handler maps any ComadreError to ``{"error": {message, type, hint}}``
    with the exception's status_code. One representative test covers all
    subclass dispatching."""
    exc = VoiceNotFoundError(voice="ghost", available=["santa"])
    resp = await comadre_error_handler(_mock_request(), exc)
    assert resp.status_code == 404
    body = _response_json(resp)
    error = body["error"]
    assert isinstance(error, dict)
    assert "message" in error
    assert "type" in error
    assert "hint" in error
    assert error["type"] == "not_found_error"


async def test_comadre_error_handler_passes_invalid_request_400() -> None:
    """A different status_code branch — confirm the dispatch is not
    hard-coded to 404 from the previous test."""
    exc = InvalidRequestError(message="too long", hint="shorten it")
    resp = await comadre_error_handler(_mock_request(), exc)
    assert resp.status_code == 400
    body = _response_json(resp)
    assert body["error"]["type"] == "invalid_request_error"
