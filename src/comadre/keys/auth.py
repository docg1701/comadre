"""Registry-backed API-key authentication path.

The sole entry point is ``verify_api_key_registry`` — called by
``comadre.api.verify_api_key`` when ``settings.monetization_enabled`` is
True. Sets ``request.state.auth_payload`` on success; raises a
``ComadreError`` subclass on any denial outcome.

The module's only runtime I/O is a single indexed SELECT against the key
registry on cache-miss. Zero external deps — the timing-equalisation dummy
compare is ``hmac.compare_digest`` from stdlib.
"""

from __future__ import annotations

import datetime as _dt
import hmac
import sqlite3
from datetime import date
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

from fastapi import Request

from comadre.config import Settings
from comadre.exceptions import (
    ApiKeyNotFoundError,
    ApiKeyRevokedError,
    ApiKeySuspendedError,
    KeyRegistryError,
)
from comadre.keys.billing import ManualBillingProvider
from comadre.keys.cache import AuthCache
from comadre.keys.db import lookup_key_auth
from comadre.keys.models import ApiKeyRecord, AuthPayload
from comadre.keys.tokens import hash_api_key
from comadre.logging import get_logger

_logger = get_logger("keys.auth")

# Pre-computed dummy hash for timing-equalisation. Constant per process.
_DUMMY_HASH = hash_api_key("__dummy_for_timing_equalisation__")

# Shared billing provider instance. MVP has exactly one implementation.
_billing = ManualBillingProvider()


def _today_in_billing_tz(settings: Settings) -> date:
    """Return today's date resolved in ``settings.billing_timezone``.

    Extracted as a single-caller seam so tests can monkey-patch
    ``comadre.keys.auth._today_in_billing_tz`` without touching
    ``date.today`` globally. Mirrors the CLI's ``_resolve_today_in_tz``
    pattern (which lives under ``keys/cli/`` and cannot be imported here
    per the architecture's import-boundary rule).
    """
    return _dt.datetime.now(ZoneInfo(settings.billing_timezone)).date()


async def verify_api_key_registry(request: Request, token: str) -> None:
    """Registry-mode auth. Sets ``request.state.auth_payload`` on pass.

    Never writes to ``audit_log``. Never updates ``last_used_at``. Fails
    closed on any SQLite error.
    """
    settings: Settings = request.app.state.settings
    cache: AuthCache = request.app.state.auth_cache
    conn = request.app.state.registry_db

    try:
        token_hash = hash_api_key(token)
    except UnicodeEncodeError:
        # Non-ASCII tokens cannot match any stored hash (issue-key never
        # produces non-ASCII plaintext). Run the dummy compare so the
        # rejection cost matches a real DB-miss, then reject with the
        # enumeration-resistant 401 envelope.
        hmac.compare_digest(_DUMMY_HASH, _DUMMY_HASH)
        raise ApiKeyNotFoundError() from None
    payload = cache.get(token_hash)

    if payload is None:
        try:
            payload = lookup_key_auth(conn, token_hash)
        except sqlite3.Error as exc:
            _logger.error("Key registry database unreachable or corrupt", exc_info=exc)
            raise KeyRegistryError() from exc
        if payload is None:
            # Timing-equalisation: match the compare_digest cost of a cache-hit.
            hmac.compare_digest(token_hash, _DUMMY_HASH)
            raise ApiKeyNotFoundError()
        cache.set(token_hash, payload)

    if payload.status == "suspended":
        raise ApiKeySuspendedError(settings.operator_contact_hint)
    if payload.status == "revoked":
        raise ApiKeyRevokedError(settings.operator_contact_hint)

    record = _payload_to_record(payload)
    try:
        paid = _billing.is_payment_current(record, today=_today_in_billing_tz(settings))
    except ValueError as exc:
        _logger.error(
            "Malformed paid_until in registry for key_id=%s; failing closed",
            payload.key_id,
            exc_info=exc,
        )
        raise ApiKeySuspendedError(settings.operator_contact_hint) from exc
    except ZoneInfoNotFoundError as exc:
        # Invalid ``BILLING_TIMEZONE`` or missing tzdata wheel on the host.
        # Operator-side misconfiguration; fail closed with a 500 so monitors
        # actually surface it (vs. leaking a 500 trace per request).
        _logger.error(
            "Cannot resolve billing_timezone=%r; failing closed",
            settings.billing_timezone,
            exc_info=exc,
        )
        raise KeyRegistryError() from exc
    if not paid:
        raise ApiKeySuspendedError(settings.operator_contact_hint)

    request.state.auth_payload = payload


def _payload_to_record(payload: AuthPayload) -> ApiKeyRecord:
    """Adapt ``AuthPayload`` to ``ApiKeyRecord`` for ``ManualBillingProvider``.

    Only ``billing_mode`` and ``paid_until`` are consumed by the provider;
    other fields carry placeholder values — this record never persists and
    never reaches a DB writer.
    """
    return ApiKeyRecord(
        id=payload.key_id,
        customer_id=payload.customer_id,
        key_hash="",
        key_prefix="",
        rate_limit_rpm=payload.rate_limit_rpm,
        status=payload.status,
        billing_mode=payload.billing_mode,
        price_monthly=0.0,
        paid_until=payload.paid_until,
        created_at=_dt.datetime(1970, 1, 1, tzinfo=_dt.UTC),
        last_used_at=None,
        notes="",
    )
