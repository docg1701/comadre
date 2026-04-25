"""End-to-end CLI tests for ``comadre-keys delete-customer`` (Story 4.1).

Lean by design (test-suite review 2026-04-25): LGPD purge contract is
the survivor — customer + keys hard-deleted, tombstone written, audit
emitted with no PII.
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


def _seed_customer_with_key(env: dict[str, str]) -> tuple[str, str]:
    conn = get_connection(env["db_path"])
    try:
        _apply_migrations(conn)
        cid = generate_customer_id()
        insert_customer(
            conn,
            CustomerRecord(
                id=cid,
                name="Helena",
                email="helena@clinica.com",
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
                status="active",
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
    return cid, kid


def test_delete_customer_hard_purges_rows_writes_audit_no_pii(
    env: dict[str, str],
) -> None:
    """LGPD purge: customer scrubbed (PII zeroed) + tombstone stamped +
    api_key rows deleted + audit row written with no email/name in details."""
    cid, _kid = _seed_customer_with_key(env)
    result = runner.invoke(app, ["delete-customer", cid, "--hard", "--yes"])
    _, stderr = _buffers()
    assert result.exit_code == 0, stderr

    conn = sqlite3.connect(env["db_path"])
    try:
        # Customer row scrubbed + tombstone stamped.
        row = conn.execute(
            "SELECT name, email, deleted_at FROM customer WHERE id = ?", (cid,)
        ).fetchone()
        assert row[0] == ""
        assert row[1] == ""
        assert row[2] is not None
        # All keys gone.
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM api_key WHERE customer_id = ?", (cid,)
            ).fetchone()[0]
            == 0
        )
        # Delete-customer audit row with no PII in details.
        audit = conn.execute(
            "SELECT details_json FROM audit_log WHERE action = 'delete_customer'"
        ).fetchone()
        details = json.loads(audit[0])
        assert "email" not in details
        assert "name" not in details
        assert details.get("keys_purged") == 1
    finally:
        conn.close()


def test_delete_customer_not_found_exits_3(env: dict[str, str]) -> None:
    result = runner.invoke(
        app, ["delete-customer", "cust_00000000000000000000000000", "--hard", "--yes"]
    )
    assert result.exit_code == 3
    _clear_buffers()
