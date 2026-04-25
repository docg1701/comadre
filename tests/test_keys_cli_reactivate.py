"""End-to-end CLI tests for ``comadre-keys reactivate`` (Story 3.1)."""

from __future__ import annotations

import logging
import re
import sqlite3
import time
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from comadre.keys.cli.app import app
from comadre.keys.db import (
    _apply_migrations,
    generate_customer_id,
    generate_key_id,
    get_connection,
    insert_api_key,
    insert_customer,
)
from comadre.keys.models import ApiKeyRecord, CustomerRecord

# F41 — autouse fixtures (`_clear_settings_cache`,
# `_reset_cli_consoles_to_buffers`) now live in tests/conftest.py
# and apply to every test. Helpers (``_buffers`` / ``_clear_buffers``)
# live in tests/_keys_cli_helpers.py.
from tests._keys_cli_helpers import buffers as _buffers
from tests._keys_cli_helpers import clear_buffers as _clear_buffers

runner = CliRunner()

_PII_FORBIDDEN_RE = re.compile(
    r"cmdr_live_|[0-9a-f]{64}|[0-9]{11,14}|@[a-z0-9.-]+\.[a-z]{2,}",
    re.IGNORECASE,
)


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    key = Fernet.generate_key().decode()
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", key)
    return {"db_path": str(db_path), "key": key}


def _seed_customer_and_key(
    db_path: str,
    *,
    billing_mode: str = "manual",
    status: str = "suspended",
    paid_until: str | None = None,
    key_hash: str = "a" * 64,
    key_prefix: str = "Pq_abc12",
    customer_name: str = "Pedro Lopes",
) -> tuple[str, str]:
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        cid = generate_customer_id()
        insert_customer(
            conn,
            CustomerRecord(
                id=cid,
                name=customer_name,
                email="pedro@clinica.com",
                tax_id_kind="cpf",
                tax_id_encrypted=b"gAAAAA-ciphertext",
                notes="",
                registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                deleted_at=None,
            ),
            actor="cli:tester",
        )
        kid = generate_key_id()
        insert_api_key(
            conn,
            ApiKeyRecord(
                id=kid,
                customer_id=cid,
                key_hash=key_hash,
                key_prefix=key_prefix,
                rate_limit_rpm=60,
                status=status,  # type: ignore[arg-type]
                billing_mode=billing_mode,  # type: ignore[arg-type]
                price_monthly=149.0 if billing_mode == "manual" else 0.0,
                paid_until=paid_until,
                created_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                last_used_at=None,
                notes="",
            ),
            actor="cli:tester",
        )
        return cid, kid
    finally:
        conn.close()


def _fetch_api_key(db_path: str, kid: str) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, customer_id, key_hash, key_prefix, rate_limit_rpm, "
            "status, billing_mode, price_monthly, paid_until, created_at, "
            "last_used_at, notes FROM api_key WHERE id = ?",
            (kid,),
        ).fetchone()
        assert row is not None
        return dict(row)
    finally:
        conn.close()


def _latest_reactivate_audit(db_path: str) -> dict[str, object] | None:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT actor, action, target_type, target_id, details_json "
            "FROM audit_log WHERE action = 'reactivate_key' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _count_reactivate_audits(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'reactivate_key'"
            ).fetchone()[0]
        )
    finally:
        conn.close()


def _sentinel_mtime_ns(db_path: str) -> int:
    sentinel = Path(db_path + ".invalidate")
    if not sentinel.exists():
        return 0
    return sentinel.stat().st_mtime_ns


def _advance_sentinel_past(db_path: str) -> int:
    import os

    sentinel = Path(db_path + ".invalidate")
    sentinel.touch(exist_ok=True)
    past = time.time() - 2.0
    os.utime(sentinel, (past, past))
    return sentinel.stat().st_mtime_ns


# ---------------------------------------------------------------------------
# AC13 — happy path + paid_until preservation (load-bearing FR20 invariant).
# ---------------------------------------------------------------------------


class TestReactivateSuspended:
    def test_suspended_becomes_active_paid_until_preserved(
        self, env: dict[str, str]
    ) -> None:
        """AC13 — paid_until MUST NOT be bumped; goodwill-without-payment path."""
        _cid, kid = _seed_customer_and_key(
            env["db_path"], status="suspended", paid_until="2026-04-05"
        )
        _clear_buffers()
        result = runner.invoke(app, ["reactivate", "Pq_abc12"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        after = _fetch_api_key(env["db_path"], kid)
        assert after["status"] == "active"
        # The load-bearing assertion.
        assert after["paid_until"] == "2026-04-05"
        assert "Reactivated: Pq_abc12 (Pedro Lopes)" in stdout
        audit = _latest_reactivate_audit(env["db_path"])
        assert audit is not None
        assert audit["action"] == "reactivate_key"
        assert audit["target_type"] == "api_key"
        assert audit["target_id"] == kid
        assert audit["details_json"] is None
        assert str(audit["actor"]).startswith("cli:")

    def test_sentinel_mtime_advances(self, env: dict[str, str]) -> None:
        _cid, _kid = _seed_customer_and_key(env["db_path"], status="suspended")
        before = _advance_sentinel_past(env["db_path"])
        _clear_buffers()
        result = runner.invoke(app, ["reactivate", "Pq_abc12"])
        assert result.exit_code == 0
        after = _sentinel_mtime_ns(env["db_path"])
        assert after > before


# ---------------------------------------------------------------------------
# AC14 / AC15 — terminal-state rejections.
# ---------------------------------------------------------------------------


class TestReactivateTerminalStates:
    def test_already_active_exits_3(self, env: dict[str, str]) -> None:
        _cid, kid = _seed_customer_and_key(env["db_path"], status="active")
        before = _fetch_api_key(env["db_path"], kid)
        _clear_buffers()
        result = runner.invoke(app, ["reactivate", "Pq_abc12"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Key already active: Pq_abc12" in stderr
        after = _fetch_api_key(env["db_path"], kid)
        assert after == before
        assert _count_reactivate_audits(env["db_path"]) == 0

    def test_revoked_exits_3(self, env: dict[str, str]) -> None:
        _cid, kid = _seed_customer_and_key(env["db_path"], status="revoked")
        before = _fetch_api_key(env["db_path"], kid)
        _clear_buffers()
        result = runner.invoke(app, ["reactivate", "Pq_abc12"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Key is revoked: Pq_abc12" in stderr
        after = _fetch_api_key(env["db_path"], kid)
        assert after == before
        assert _count_reactivate_audits(env["db_path"]) == 0


# ---------------------------------------------------------------------------
# AC16 / AC17 / AC18 — identifier resolution.
# ---------------------------------------------------------------------------


class TestReactivateIdentifierResolution:
    def test_customer_id_input_exits_2(self, env: dict[str, str]) -> None:
        cid, _kid = _seed_customer_and_key(env["db_path"])
        _clear_buffers()
        result = runner.invoke(app, ["reactivate", cid])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: key identifier required (got customer ID)" in stderr

    def test_missing_prefix_exits_3(self, env: dict[str, str]) -> None:
        _seed_customer_and_key(env["db_path"])
        _clear_buffers()
        result = runner.invoke(app, ["reactivate", "nokey123"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Key not found: nokey123" in stderr

    def test_ambiguous_prefix_exits_3(self, env: dict[str, str]) -> None:
        cid, _kid = _seed_customer_and_key(
            env["db_path"],
            status="suspended",
            key_prefix="Pq_abc12",
            key_hash="a" * 64,
        )
        conn = get_connection(env["db_path"])
        try:
            insert_api_key(
                conn,
                ApiKeyRecord(
                    id=generate_key_id(),
                    customer_id=cid,
                    key_hash="b" * 64,
                    key_prefix="Pq_abc12",
                    rate_limit_rpm=60,
                    status="suspended",
                    billing_mode="manual",
                    price_monthly=149.0,
                    paid_until=None,
                    created_at=datetime(2026, 4, 16, 13, 0, 0, tzinfo=UTC),
                    last_used_at=None,
                    notes="",
                ),
                actor="cli:tester",
            )
        finally:
            conn.close()

        _clear_buffers()
        result = runner.invoke(app, ["reactivate", "Pq_abc12"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Ambiguous prefix: multiple keys match 'Pq_abc12'" in stderr


# ---------------------------------------------------------------------------
# AC19 — PII-austere INFO logs.
# ---------------------------------------------------------------------------


class TestReactivateLogging:
    def test_info_log_has_no_customer_pii(self, env: dict[str, str]) -> None:
        from comadre.logging import get_logger

        _seed_customer_and_key(env["db_path"], status="suspended")
        logger = get_logger("keys.cli")
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture(level=logging.INFO)
        logger.addHandler(handler)
        try:
            _clear_buffers()
            records.clear()
            result = runner.invoke(app, ["reactivate", "Pq_abc12"])
        finally:
            logger.removeHandler(handler)

        assert result.exit_code == 0
        records_re = [r for r in records if "Reactivated" in r.getMessage()]
        assert records_re
        joined = "\n".join(r.getMessage() for r in records_re)
        assert "id=key_" in joined
        assert "key_prefix=Pq_abc12" in joined
        assert not _PII_FORBIDDEN_RE.search(joined), joined
        assert "Pedro Lopes" not in joined


# ---------------------------------------------------------------------------
# AC20 — flat help listing.
# ---------------------------------------------------------------------------


class TestReactivateHelp:
    def test_help_lists_command_flat(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "reactivate" in result.stdout
        assert "Reactivate a suspended key" in result.stdout
