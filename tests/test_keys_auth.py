"""Tests for ``comadre.keys.auth.verify_api_key_registry`` (SECURITY-CRITICAL).

Lean by design (test-suite review 2026-04-25): this is the auth path
on every ``POST /v1/audio/speech``. Every test here defends a security
property that no integration test reliably catches:

* F18 cache-hit equalisation (timing-attack defense)
* DB miss runs constant-time dummy compare (enumeration defense)
* Status branches: suspended / revoked / expired / complimentary
* DB error fails closed (KeyRegistryError, not 200)
* Log records carry no plaintext / hash / customer name (PII)
* Non-ASCII tokens → 401, not 500
"""

from __future__ import annotations

import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr

from comadre.config import RegistrySettings
from comadre.exceptions import (
    ApiKeyNotFoundError,
    ApiKeyRevokedError,
    ApiKeySuspendedError,
    KeyRegistryError,
)
from comadre.keys import auth as auth_module
from comadre.keys.auth import verify_api_key_registry
from comadre.keys.cache import AuthCache
from comadre.keys.db import (
    _apply_migrations,
    generate_customer_id,
    generate_key_id,
    get_connection,
)
from comadre.keys.tokens import generate_api_key_plaintext, hash_api_key

CONTACT_HINT = "Contact Ana on WhatsApp: +55 11 90000-0000"


def _settings() -> RegistrySettings:
    return RegistrySettings(
        operator_contact_hint=CONTACT_HINT,
        key_registry_encryption_key=SecretStr(Fernet.generate_key().decode()),
    )


def _seed_key(
    conn: sqlite3.Connection,
    *,
    plaintext: str | None = None,
    status: str = "active",
    billing_mode: str = "manual",
    paid_until: str | None = "2099-12-31",
    customer_name: str = "Helena",
) -> tuple[str, str, str]:
    plaintext = plaintext or generate_api_key_plaintext()
    cid = generate_customer_id()
    kid = generate_key_id()
    conn.execute(
        "INSERT INTO customer (id, name, email, tax_id_kind, tax_id_encrypted, "
        "notes, registered_at, deleted_at) VALUES "
        "(?, ?, 'h@x.com', 'cpf', ?, '', '2026-04-16T12:00:00Z', NULL)",
        (cid, customer_name, b"ct"),
    )
    conn.execute(
        "INSERT INTO api_key (id, customer_id, key_hash, key_prefix, "
        "rate_limit_rpm, status, billing_mode, price_monthly, paid_until, "
        "created_at, last_used_at, notes) VALUES "
        "(?, ?, ?, ?, 60, ?, ?, ?, ?, '2026-04-16T12:00:00Z', NULL, '')",
        (
            kid,
            cid,
            hash_api_key(plaintext),
            plaintext[len("cmdr_live_") : len("cmdr_live_") + 8],
            status,
            billing_mode,
            0.0 if billing_mode == "complimentary" else 149.0,
            paid_until,
        ),
    )
    conn.commit()
    return plaintext, kid, cid


def _make_request(
    conn: sqlite3.Connection, cache: AuthCache, settings: RegistrySettings
) -> Any:
    request = MagicMock()
    request.app.state.settings = settings
    request.app.state.auth_cache = cache
    request.app.state.registry_db = conn
    request.state = MagicMock()
    return request


class _CapturingHandler(logging.Handler):
    def __init__(self) -> None:
        super().__init__(level=logging.DEBUG)
        self.records: list[logging.LogRecord] = []

    def emit(self, record: logging.LogRecord) -> None:
        self.records.append(record)


@pytest.fixture()
def auth_log_handler() -> Any:
    handler = _CapturingHandler()
    logger = logging.getLogger("keys.auth")
    logger.addHandler(handler)
    try:
        yield handler
    finally:
        logger.removeHandler(handler)


async def test_cache_miss_db_hit_caches_payload_and_sets_request_state(
    tmp_path: Path,
) -> None:
    """First lookup: DB miss → DB hit → payload cached → request.state set."""
    conn = get_connection(tmp_path / "registry.db")
    try:
        _apply_migrations(conn)
        plaintext, kid, _cid = _seed_key(conn)
        cache = AuthCache()
        request = _make_request(conn, cache, _settings())

        await verify_api_key_registry(request, token=plaintext)

        assert cache.snapshot()["entries"] == 1
        cached = cache.get(hash_api_key(plaintext))
        assert cached is not None
        assert cached.key_id == kid
        assert request.state.auth_payload == cached
    finally:
        conn.close()


async def test_cache_hit_runs_equalisation_select_against_dummy(
    tmp_path: Path,
) -> None:
    """F18: cache hit MUST run the same indexed SELECT as a miss (against
    a never-matching dummy hash) so timing distinguishability is removed.
    A cache-residency oracle for active keys would be a known-key probe.
    """
    conn = get_connection(tmp_path / "registry.db")
    try:
        _apply_migrations(conn)
        plaintext, _, _ = _seed_key(conn)
        cache = AuthCache()
        # Pre-populate cache to take the hit path.
        request = _make_request(conn, cache, _settings())
        await verify_api_key_registry(request, token=plaintext)

        # Second call hits the cache. Trace SQL.
        statements: list[str] = []
        conn.set_trace_callback(statements.append)
        try:
            await verify_api_key_registry(request, token=plaintext)
        finally:
            conn.set_trace_callback(None)

        select_stmts = [
            s for s in statements if s.upper().lstrip().startswith("SELECT")
        ]
        assert len(select_stmts) == 1, statements
    finally:
        conn.close()


async def test_db_miss_runs_dummy_compare_and_does_not_cache(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Unknown token: ApiKeyNotFoundError + dummy compare runs (anti-enum)
    + cache stays empty (a miss MUST NOT pollute the cache)."""
    conn = get_connection(tmp_path / "registry.db")
    try:
        _apply_migrations(conn)
        _seed_key(conn)
        cache = AuthCache()

        calls: list[tuple[bytes, bytes]] = []
        real_compare = auth_module.hmac.compare_digest

        def spy(a: Any, b: Any) -> bool:
            calls.append((a, b))
            return bool(real_compare(a, b))

        monkeypatch.setattr(auth_module.hmac, "compare_digest", spy)

        request = _make_request(conn, cache, _settings())
        with pytest.raises(ApiKeyNotFoundError):
            await verify_api_key_registry(request, token="unknown-xyz")

        assert len(calls) == 1
        assert cache.snapshot()["entries"] == 0
    finally:
        conn.close()


async def test_status_and_billing_branches_raise_correct_errors(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Suspended → 401 suspended; revoked → 401 revoked; expired manual
    → 401 suspended; complimentary always allowed."""
    monkeypatch.setattr(
        auth_module, "_today_in_billing_tz", lambda _s: date(2026, 4, 17)
    )

    cases = [
        ({"status": "suspended"}, ApiKeySuspendedError),
        ({"status": "revoked"}, ApiKeyRevokedError),
        ({"paid_until": "2020-01-01"}, ApiKeySuspendedError),
    ]
    for kwargs, expected_exc in cases:
        conn = get_connection(tmp_path / f"r-{expected_exc.__name__}.db")
        try:
            _apply_migrations(conn)
            plaintext, _, _ = _seed_key(conn, **kwargs)  # type: ignore[arg-type]
            cache = AuthCache()
            request = _make_request(conn, cache, _settings())
            with pytest.raises(expected_exc):
                await verify_api_key_registry(request, token=plaintext)
        finally:
            conn.close()

    # Complimentary with NULL paid_until is always allowed.
    conn = get_connection(tmp_path / "comp.db")
    try:
        _apply_migrations(conn)
        plaintext, _, _ = _seed_key(conn, billing_mode="complimentary", paid_until=None)
        cache = AuthCache()
        request = _make_request(conn, cache, _settings())
        await verify_api_key_registry(request, token=plaintext)
        assert request.state.auth_payload is not None
    finally:
        conn.close()


async def test_db_error_fails_closed_with_key_registry_error(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_log_handler: _CapturingHandler,
) -> None:
    """A SQLite error must NOT leak as 200 — fail closed via KeyRegistryError.
    The error log line is the operator's only signal that the registry is sick."""
    conn = get_connection(tmp_path / "registry.db")
    try:
        _apply_migrations(conn)
        cache = AuthCache()
        request = _make_request(conn, cache, _settings())

        def boom(*_a: object, **_kw: object) -> object:
            raise sqlite3.OperationalError("database is closed")

        monkeypatch.setattr(auth_module, "lookup_key_auth", boom)

        with pytest.raises(KeyRegistryError):
            await verify_api_key_registry(request, token="any-token")

        error_records = [
            r for r in auth_log_handler.records if r.levelno == logging.ERROR
        ]
        assert len(error_records) >= 1
        assert "unreachable or corrupt" in error_records[0].getMessage()
    finally:
        conn.close()


async def test_log_records_carry_no_plaintext_hash_or_customer_name(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    auth_log_handler: _CapturingHandler,
) -> None:
    """LGPD + token discipline: log lines NEVER carry secret-shaped values."""
    conn = get_connection(tmp_path / "registry.db")
    try:
        _apply_migrations(conn)
        plaintext, _, _ = _seed_key(
            conn, paid_until="not-a-date", customer_name="Helena Ribeiro"
        )
        cache = AuthCache()
        request = _make_request(conn, cache, _settings())
        monkeypatch.setattr(
            auth_module, "_today_in_billing_tz", lambda _s: date(2026, 4, 17)
        )

        with pytest.raises(ApiKeySuspendedError):
            await verify_api_key_registry(request, token=plaintext)

        for record in auth_log_handler.records:
            body = record.getMessage()
            assert "cmdr_live_" not in body
            assert hash_api_key(plaintext) not in body
            assert "Helena Ribeiro" not in body
    finally:
        conn.close()


async def test_non_ascii_bearer_token_returns_not_found_not_500(
    tmp_path: Path,
) -> None:
    """Non-ASCII tokens must not bubble UnicodeEncodeError as a 500."""
    conn = get_connection(tmp_path / "registry.db")
    try:
        _apply_migrations(conn)
        cache = AuthCache()
        request = _make_request(conn, cache, _settings())
        with pytest.raises(ApiKeyNotFoundError):
            await verify_api_key_registry(request, token="café_não_existe")
        assert cache.snapshot()["entries"] == 0
    finally:
        conn.close()
