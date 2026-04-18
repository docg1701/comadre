"""Tests for ``comadre.keys.auth.verify_api_key_registry``."""

from __future__ import annotations

import logging
import sqlite3
from datetime import date
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from pydantic import SecretStr

from comadre.config import Settings
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
from comadre.keys.models import AuthPayload
from comadre.keys.tokens import generate_api_key_plaintext, hash_api_key

CONTACT_HINT = "Contact Ana on WhatsApp: +55 11 90000-0000"


def _settings(**overrides: Any) -> Settings:
    from cryptography.fernet import Fernet

    defaults: dict[str, Any] = {
        "api_key": SecretStr("sentinel-never-used"),
        "monetization_enabled": True,
        "operator_contact_hint": CONTACT_HINT,
        "key_registry_encryption_key": SecretStr(Fernet.generate_key().decode()),
    }
    defaults.update(overrides)
    return Settings(**defaults)


def _seed_key(
    conn: sqlite3.Connection,
    *,
    plaintext: str | None = None,
    status: str = "active",
    billing_mode: str = "manual",
    rate_limit_rpm: int = 60,
    paid_until: str | None = "2099-12-31",
    customer_name: str = "Helena",
) -> tuple[str, str, str]:
    """Seed a customer + key row, returning (plaintext, key_id, customer_id)."""
    plaintext = plaintext or generate_api_key_plaintext()
    cid = generate_customer_id()
    kid = generate_key_id()
    conn.execute(
        "INSERT INTO customer ("
        "id, name, email, tax_id_kind, tax_id_encrypted, notes, "
        "registered_at, deleted_at) VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            cid,
            customer_name,
            "h@example.com",
            "cpf",
            b"ciphertext",
            "",
            "2026-04-16T12:00:00Z",
            None,
        ),
    )
    conn.execute(
        "INSERT INTO api_key ("
        "id, customer_id, key_hash, key_prefix, rate_limit_rpm, status, "
        "billing_mode, price_monthly, paid_until, created_at, last_used_at, "
        "notes) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            kid,
            cid,
            hash_api_key(plaintext),
            plaintext[len("cmdr_live_") : len("cmdr_live_") + 8],
            rate_limit_rpm,
            status,
            billing_mode,
            0.0 if billing_mode == "complimentary" else 149.0,
            paid_until,
            "2026-04-16T12:00:00Z",
            None,
            "",
        ),
    )
    conn.commit()
    return plaintext, kid, cid


def _make_request(
    conn: sqlite3.Connection, cache: AuthCache, settings: Settings
) -> Any:
    """Return a mock Request whose ``.app.state`` carries the three state fields."""
    request = MagicMock()
    request.app.state.settings = settings
    request.app.state.auth_cache = cache
    request.app.state.registry_db = conn
    # ``.state`` gets attributes set on it — use a plain MagicMock so
    # ``request.state.auth_payload = payload`` simply records the assignment.
    request.state = MagicMock()
    return request


class _CapturingHandler(logging.Handler):
    """Drain ``keys.auth`` records into a list for assertion.

    The module's logger has ``propagate=False`` (stderr-only structured
    logging per Story 1.3), so pytest's ``caplog`` fixture — which attaches
    to the root logger — never sees the records. This handler lives on the
    ``keys.auth`` logger directly for the lifetime of a single test.
    """

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


class TestCacheHitPath:
    async def test_cache_hit_short_circuits_db_lookup(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            plaintext, kid, cid = _seed_key(conn)
            settings = _settings()
            cache = AuthCache()
            payload = AuthPayload(
                customer_id=cid,
                key_id=kid,
                status="active",
                billing_mode="manual",
                rate_limit_rpm=60,
                paid_until="2099-12-31",
            )
            cache.set(hash_api_key(plaintext), payload)

            statements: list[str] = []
            conn.set_trace_callback(statements.append)
            try:
                request = _make_request(conn, cache, settings)
                await verify_api_key_registry(request, token=plaintext)
            finally:
                conn.set_trace_callback(None)

            assert statements == []
            assert request.state.auth_payload is payload
            assert cache.snapshot()["hits"] == 1
        finally:
            conn.close()


class TestCacheMissPath:
    async def test_cache_miss_db_hit_caches_payload_and_sets_request_state(
        self, tmp_path: Path
    ) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            plaintext, kid, cid = _seed_key(conn)
            settings = _settings()
            cache = AuthCache()
            request = _make_request(conn, cache, settings)

            await verify_api_key_registry(request, token=plaintext)

            snap = cache.snapshot()
            assert snap["entries"] == 1
            assert snap["misses"] == 1  # first get() missed
            cached = cache.get(hash_api_key(plaintext))
            assert cached is not None
            assert cached.customer_id == cid
            assert cached.key_id == kid
            assert cached.status == "active"
            assert request.state.auth_payload == cached
        finally:
            conn.close()


class TestDbMissPath:
    async def test_db_miss_runs_dummy_compare_and_raises_not_found(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            _seed_key(conn)  # different key present; token below won't match
            settings = _settings()
            cache = AuthCache()

            calls: list[tuple[str, str]] = []
            real_compare = auth_module.hmac.compare_digest

            def spy(a: Any, b: Any) -> bool:
                calls.append((a, b))
                return bool(real_compare(a, b))

            monkeypatch.setattr(auth_module.hmac, "compare_digest", spy)

            request = _make_request(conn, cache, settings)
            with pytest.raises(ApiKeyNotFoundError):
                await verify_api_key_registry(request, token="unknown-token-xyz")

            assert len(calls) == 1
            token_hash = hash_api_key("unknown-token-xyz")
            assert calls[0] == (token_hash, auth_module._DUMMY_HASH)
            # Miss MUST NOT cache anything.
            assert cache.snapshot()["entries"] == 0
        finally:
            conn.close()

    async def test_cache_write_skipped_on_db_miss(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            settings = _settings()
            cache = AuthCache()
            request = _make_request(conn, cache, settings)

            with pytest.raises(ApiKeyNotFoundError):
                await verify_api_key_registry(request, token="whatever")

            assert cache.snapshot()["entries"] == 0
        finally:
            conn.close()


class TestStatusBranches:
    async def test_suspended_status_raises_suspended_error(
        self, tmp_path: Path
    ) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            plaintext, _kid, _cid = _seed_key(conn, status="suspended")
            settings = _settings()
            cache = AuthCache()
            request = _make_request(conn, cache, settings)

            with pytest.raises(ApiKeySuspendedError) as exc_info:
                await verify_api_key_registry(request, token=plaintext)
            assert CONTACT_HINT in exc_info.value.hint
        finally:
            conn.close()

    async def test_cache_write_happens_for_suspended_payload(
        self, tmp_path: Path
    ) -> None:
        """AC4 tail: the lookup succeeded, so the payload is cached even
        though the request is denied."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            plaintext, _kid, _cid = _seed_key(conn, status="suspended")
            settings = _settings()
            cache = AuthCache()
            request = _make_request(conn, cache, settings)

            with pytest.raises(ApiKeySuspendedError):
                await verify_api_key_registry(request, token=plaintext)

            assert cache.snapshot()["entries"] == 1
            # Second call must deny from the cache (no further SQL).
            statements: list[str] = []
            conn.set_trace_callback(statements.append)
            try:
                with pytest.raises(ApiKeySuspendedError):
                    await verify_api_key_registry(request, token=plaintext)
            finally:
                conn.set_trace_callback(None)
            assert statements == []
        finally:
            conn.close()

    async def test_revoked_status_raises_revoked_error(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            plaintext, _kid, _cid = _seed_key(conn, status="revoked")
            settings = _settings()
            cache = AuthCache()
            request = _make_request(conn, cache, settings)

            with pytest.raises(ApiKeyRevokedError) as exc_info:
                await verify_api_key_registry(request, token=plaintext)
            assert CONTACT_HINT in exc_info.value.hint
        finally:
            conn.close()


class TestBillingBranches:
    async def test_manual_expired_paid_until_raises_suspended_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            plaintext, _kid, _cid = _seed_key(conn, paid_until="2020-01-01")
            settings = _settings()
            cache = AuthCache()
            request = _make_request(conn, cache, settings)

            monkeypatch.setattr(
                auth_module,
                "_today_in_billing_tz",
                lambda _s: date(2026, 4, 17),
            )

            with pytest.raises(ApiKeySuspendedError):
                await verify_api_key_registry(request, token=plaintext)

            # Row on disk is still status='active' — the auth path never
            # mutates the registry; the cron is the writer.
            row = conn.execute(
                "SELECT status FROM api_key WHERE key_hash = ?",
                (hash_api_key(plaintext),),
            ).fetchone()
            assert row["status"] == "active"
        finally:
            conn.close()

    async def test_complimentary_always_allowed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            plaintext, _kid, _cid = _seed_key(
                conn, billing_mode="complimentary", paid_until=None
            )
            settings = _settings()
            cache = AuthCache()
            request = _make_request(conn, cache, settings)

            monkeypatch.setattr(
                auth_module,
                "_today_in_billing_tz",
                lambda _s: date(2099, 1, 1),
            )

            await verify_api_key_registry(request, token=plaintext)
            assert request.state.auth_payload.billing_mode == "complimentary"
            assert request.state.auth_payload.paid_until is None
        finally:
            conn.close()

    async def test_manual_null_paid_until_fails_as_suspended(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """``ManualBillingProvider.is_payment_current`` returns False when
        ``billing_mode='manual'`` and ``paid_until is None`` — the auth path
        denies with suspended."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            plaintext, _kid, _cid = _seed_key(conn, paid_until=None)
            settings = _settings()
            cache = AuthCache()
            request = _make_request(conn, cache, settings)

            monkeypatch.setattr(
                auth_module,
                "_today_in_billing_tz",
                lambda _s: date(2026, 4, 17),
            )

            with pytest.raises(ApiKeySuspendedError):
                await verify_api_key_registry(request, token=plaintext)
        finally:
            conn.close()

    async def test_malformed_paid_until_fails_closed_as_suspended(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        auth_log_handler: _CapturingHandler,
    ) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            plaintext, kid, _cid = _seed_key(conn, paid_until="not-a-date")
            settings = _settings()
            cache = AuthCache()
            request = _make_request(conn, cache, settings)

            monkeypatch.setattr(
                auth_module,
                "_today_in_billing_tz",
                lambda _s: date(2026, 4, 17),
            )

            with pytest.raises(ApiKeySuspendedError):
                await verify_api_key_registry(request, token=plaintext)

            error_records = [
                r for r in auth_log_handler.records if r.levelno == logging.ERROR
            ]
            assert len(error_records) == 1
            msg = error_records[0].getMessage()
            assert "Malformed paid_until" in msg
            assert kid in msg
            assert plaintext not in msg
            assert hash_api_key(plaintext) not in msg
            assert "Helena" not in msg
        finally:
            conn.close()


class TestDatabaseErrorFailClosed:
    async def test_sqlite_error_raises_key_registry_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        auth_log_handler: _CapturingHandler,
    ) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            settings = _settings()
            cache = AuthCache()
            request = _make_request(conn, cache, settings)

            def boom(*_args: object, **_kwargs: object) -> object:
                raise sqlite3.OperationalError("database is closed")

            monkeypatch.setattr(auth_module, "lookup_key_auth", boom)

            with pytest.raises(KeyRegistryError):
                await verify_api_key_registry(request, token="whatever")

            assert cache.snapshot()["entries"] == 0
            error_records = [
                r for r in auth_log_handler.records if r.levelno == logging.ERROR
            ]
            assert len(error_records) == 1
            assert "unreachable or corrupt" in error_records[0].getMessage()
        finally:
            conn.close()


class TestLogSanitisation:
    async def test_no_plaintext_or_hash_in_log_records(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        auth_log_handler: _CapturingHandler,
    ) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            plaintext, _kid, _cid = _seed_key(
                conn, paid_until="not-a-date", customer_name="Helena Ribeiro"
            )
            settings = _settings()
            cache = AuthCache()
            request = _make_request(conn, cache, settings)
            monkeypatch.setattr(
                auth_module,
                "_today_in_billing_tz",
                lambda _s: date(2026, 4, 17),
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


class TestTodayInBillingTz:
    def test_returns_date_in_configured_zone(self) -> None:
        settings = _settings(billing_timezone="America/Sao_Paulo")
        today = auth_module._today_in_billing_tz(settings)
        assert isinstance(today, date)


class TestNonAsciiBearerToken:
    async def test_non_ascii_token_raises_not_found_not_500(
        self,
        tmp_path: Path,
        auth_log_handler: _CapturingHandler,
    ) -> None:
        """Non-ASCII tokens must not bubble UnicodeEncodeError as a 500."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            settings = _settings()
            cache = AuthCache()
            request = _make_request(conn, cache, settings)

            with pytest.raises(ApiKeyNotFoundError):
                await verify_api_key_registry(request, token="café_não_existe")

            assert cache.snapshot()["entries"] == 0
        finally:
            conn.close()


class TestZoneInfoFailureFailsClosed:
    async def test_unknown_billing_timezone_raises_key_registry_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
        auth_log_handler: _CapturingHandler,
    ) -> None:
        """Invalid ``BILLING_TIMEZONE`` (or missing tzdata) must fail closed
        with a 500-shaped ``KeyRegistryError``, not bubble a 500 trace.
        """
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            plaintext, _kid, _cid = _seed_key(conn)
            settings = _settings(billing_timezone="Atlantis/Lost_City")
            cache = AuthCache()
            request = _make_request(conn, cache, settings)

            with pytest.raises(KeyRegistryError):
                await verify_api_key_registry(request, token=plaintext)

            error_records = [
                r for r in auth_log_handler.records if r.levelno == logging.ERROR
            ]
            assert len(error_records) == 1
            msg = error_records[0].getMessage()
            assert "billing_timezone" in msg
            assert plaintext not in msg
            assert hash_api_key(plaintext) not in msg
        finally:
            conn.close()
