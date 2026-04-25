"""Tests for the ComadreError hierarchy + handler.

Lean by design (test-suite review 2026-04-25): per-class
status_code/error_type/hint readback was tautology. What survives:
anti-enumeration envelope identity, format-string safety, handler
JSON shape.
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


def test_api_key_not_found_envelope_is_byte_identical_to_authentication_error() -> None:
    """FR26 anti-enumeration: a DB-miss MUST NOT be distinguishable
    from a malformed bearer at the HTTP layer."""
    not_found = ApiKeyNotFoundError()
    legacy = AuthenticationError()
    for attr in ("message", "error_type", "hint", "status_code"):
        assert getattr(not_found, attr) == getattr(legacy, attr)


def test_suspended_revoked_hints_interpolate_operator_contact_safely() -> None:
    """The hint format has ``{operator_contact_hint}`` as the ONLY
    placeholder — operator-supplied braces (e.g. ``Contact {admin}!``)
    must remain literal, not get interpreted by str.format()."""
    for cls in (ApiKeySuspendedError, ApiKeyRevokedError):
        err = cls(operator_contact_hint="Contact {admin}!")
        assert err.hint.endswith("Contact {admin}!")
        assert "{admin}" in err.hint
        assert "{operator_contact_hint}" not in err.hint


def test_voice_not_found_lists_available_invalid_tax_id_carries_kind() -> None:
    """404 helps the user recover by listing what IS available;
    InvalidTaxIdError surfaces the kind it rejected."""
    err = VoiceNotFoundError(voice="ghost", available=["alice", "bob"])
    assert err.status_code == 404
    assert "ghost" in err.message
    assert "alice" in err.hint and "bob" in err.hint

    tax = InvalidTaxIdError("cpf")
    assert tax.status_code == 400
    assert "cpf" in tax.message.lower()


async def test_comadre_error_handler_maps_subclasses_to_correct_envelope() -> None:
    """The handler maps any ComadreError to ``{"error": {message, type, hint}}``
    with the exception's status_code. Two cases cover the dispatch path."""
    for exc, expected_status, expected_type in (
        (
            VoiceNotFoundError(voice="ghost", available=["santa"]),
            404,
            "not_found_error",
        ),
        (
            InvalidRequestError(message="too long", hint="shorten it"),
            400,
            "invalid_request_error",
        ),
    ):
        resp = await comadre_error_handler(_mock_request(), exc)
        assert resp.status_code == expected_status
        body = json.loads(
            resp.body if isinstance(resp.body, bytes) else bytes(resp.body)
        )
        error = body["error"]
        assert isinstance(error, dict)
        assert {"message", "type", "hint"} <= error.keys()
        assert error["type"] == expected_type
