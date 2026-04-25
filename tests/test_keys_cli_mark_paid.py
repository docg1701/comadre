"""End-to-end CLI tests for ``comadre-keys mark-paid`` (Story 3.1).

Lean by design (test-suite review 2026-04-25): one happy path that
proves the audit + state contract; one not-found / invalid-state.
"""

from __future__ import annotations

import sqlite3
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
from tests._keys_cli_helpers import buffers as _buffers

runner = CliRunner()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    key = Fernet.generate_key().decode()
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", key)
    return {"db_path": str(db_path), "key": key}


def _seed(
    env: dict[str, str], *, status: str = "active", billing_mode: str = "manual"
) -> str:
    conn = get_connection(env["db_path"])
    try:
        _apply_migrations(conn)
        cid = generate_customer_id()
        insert_customer(
            conn,
            CustomerRecord(
                id=cid,
                name="Helena",
                email="h@x.com",
                tax_id_kind="cpf",
                tax_id_encrypted=b"ct",
                notes="",
                registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                deleted_at=None,
            ),
            actor="cli:tester",
        )
        insert_api_key(
            conn,
            ApiKeyRecord(
                id=generate_key_id(),
                customer_id=cid,
                key_hash="a" * 64,
                key_prefix="Pq_abc12",
                rate_limit_rpm=60,
                status=status,  # type: ignore[arg-type]
                billing_mode=billing_mode,  # type: ignore[arg-type]
                price_monthly=149.0 if billing_mode == "manual" else 0.0,
                paid_until=None,
                created_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                last_used_at=None,
                notes="",
            ),
            actor="cli:tester",
        )
    finally:
        conn.close()
    return "Pq_abc12"


def test_mark_paid_extends_paid_until_and_audits(env: dict[str, str]) -> None:
    """Happy path: paid_until updated; audit row written with the new date."""
    prefix = _seed(env)
    result = runner.invoke(app, ["mark-paid", prefix, "--until", "2026-06-05"])
    _, stderr = _buffers()
    assert result.exit_code == 0, stderr

    conn = sqlite3.connect(env["db_path"])
    try:
        row = conn.execute(
            "SELECT paid_until FROM api_key WHERE key_prefix = ?", (prefix,)
        ).fetchone()
        assert row[0] == "2026-06-05"
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'mark_paid'"
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_mark_paid_missing_key_exits_3(env: dict[str, str]) -> None:
    """Missing key prefix exits 3."""
    result = runner.invoke(app, ["mark-paid", "NOPENOPE", "--until", "2026-06-05"])
    assert result.exit_code == 3
