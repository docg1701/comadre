"""End-to-end CLI tests for ``comadre-keys update-key`` (Story 1.6).

Lean by design (test-suite review 2026-04-25): one happy path
exercising every flag in one txn, one not-found, one usage-error.
Per-flag isolated tests + boundary spam deleted.
"""

from __future__ import annotations

import json
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
    """Seed one active customer + key, return the key prefix."""
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
                tax_id_encrypted=b"ciphertext",
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
                key_hash="a" * 64,
                key_prefix="Pq_abc12",
                rate_limit_rpm=60,
                status=status,  # type: ignore[arg-type]
                billing_mode="manual",
                price_monthly=149.0,
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


def test_update_key_all_three_flags_in_one_txn(env: dict[str, str]) -> None:
    """--rpm + --price + --notes all land in one txn; audit lists all
    three field names."""
    prefix = _seed(env)
    result = runner.invoke(
        app,
        [
            "update-key",
            prefix,
            "--rpm",
            "120",
            "--price",
            "199.5",
            "--notes",
            "upgraded",
        ],
    )
    _, stderr = _buffers()
    assert result.exit_code == 0, stderr

    conn = sqlite3.connect(env["db_path"])
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute(
            "SELECT rate_limit_rpm, price_monthly, notes FROM api_key"
        ).fetchone()
        assert row["rate_limit_rpm"] == 120
        assert row["price_monthly"] == 199.5
        assert row["notes"] == "upgraded"

        audit = conn.execute(
            "SELECT details_json FROM audit_log "
            "WHERE action = 'update_key' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        details = json.loads(audit[0])
        assert set(details["fields"]) == {"rpm", "price", "notes"}
    finally:
        conn.close()


def test_update_key_revoked_or_missing_exits_3(env: dict[str, str]) -> None:
    """Revoked keys and unknown prefixes both exit 3."""
    revoked_prefix = _seed(env, status="revoked")
    result = runner.invoke(app, ["update-key", revoked_prefix, "--rpm", "120"])
    _, stderr = _buffers()
    assert result.exit_code == 3
    assert "revoked" in stderr.lower() or "not found" in stderr.lower()
    _clear_buffers()

    result = runner.invoke(app, ["update-key", "NOPENOPE", "--rpm", "120"])
    _, stderr = _buffers()
    assert result.exit_code == 3


def test_update_key_rejects_invalid_inputs(env: dict[str, str]) -> None:
    """No flags, --rpm out of range, --price negative all exit 2."""
    prefix = _seed(env)

    result = runner.invoke(app, ["update-key", prefix])
    assert result.exit_code == 2
    _clear_buffers()

    result = runner.invoke(app, ["update-key", prefix, "--rpm", "10001"])
    assert result.exit_code == 2
    _clear_buffers()

    result = runner.invoke(app, ["update-key", prefix, "--price", "-1"])
    assert result.exit_code == 2
