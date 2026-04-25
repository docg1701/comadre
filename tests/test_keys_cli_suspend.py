"""End-to-end CLI tests for ``comadre-keys suspend`` (Story 3.1).

Lean by design (test-suite review 2026-04-25): one happy path,
one already-suspended / not-found rejection.
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
from tests._keys_cli_helpers import clear_buffers as _clear_buffers

runner = CliRunner()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    key = Fernet.generate_key().decode()
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", key)
    return {"db_path": str(db_path), "key": key}


def _seed(env: dict[str, str], *, status: str = "active") -> str:
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
                billing_mode="manual",
                price_monthly=149.0,
                paid_until="2026-04-30",
                created_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                last_used_at=None,
                notes="",
            ),
            actor="cli:tester",
        )
    finally:
        conn.close()
    return "Pq_abc12"


def test_suspend_active_key_flips_status_and_audits(env: dict[str, str]) -> None:
    """Active → suspended; one audit row with action='suspend_key'."""
    prefix = _seed(env)
    result = runner.invoke(app, ["suspend", prefix])
    assert result.exit_code == 0

    conn = sqlite3.connect(env["db_path"])
    try:
        row = conn.execute("SELECT status FROM api_key").fetchone()
        assert row[0] == "suspended"
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'suspend_key'"
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_suspend_already_suspended_or_missing_exits_3(env: dict[str, str]) -> None:
    prefix = _seed(env, status="suspended")
    result = runner.invoke(app, ["suspend", prefix])
    assert result.exit_code != 0
    _clear_buffers()

    result = runner.invoke(app, ["suspend", "NOPENOPE"])
    assert result.exit_code == 3
