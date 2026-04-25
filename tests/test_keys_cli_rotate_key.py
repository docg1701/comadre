"""End-to-end CLI tests for ``comadre-keys rotate-key`` (Story 1.6).

Lean by design (test-suite review 2026-04-25): one happy path that
proves the security-critical contract (new plaintext, new hash, old
plaintext no longer matches), one already-revoked / not-found.
"""

from __future__ import annotations

import re
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
from comadre.keys.tokens import hash_api_key
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


def _seed(env: dict[str, str], *, status: str = "active") -> tuple[str, str]:
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
    return kid, "Pq_abc12"


def test_rotate_key_yes_flag_emits_new_plaintext_and_invalidates_old(
    env: dict[str, str],
) -> None:
    """Rotation: same key_id, new key_hash, new key_prefix; old hash no
    longer present. The plaintext is shown exactly once on stdout."""
    kid, prefix = _seed(env)
    old_hash = "a" * 64

    result = runner.invoke(app, ["rotate-key", prefix])
    stdout, _ = _buffers()
    assert result.exit_code == 0
    new_plaintext_match = re.search(r"cmdr_live_[A-Za-z0-9_-]{43}", stdout)
    assert new_plaintext_match is not None
    new_plaintext = new_plaintext_match.group(0)
    assert stdout.count(new_plaintext) == 1

    conn = sqlite3.connect(env["db_path"])
    try:
        row = conn.execute(
            "SELECT id, key_hash FROM api_key WHERE id = ?", (kid,)
        ).fetchone()
        assert row[0] == kid  # same key_id
        assert row[1] != old_hash
        assert row[1] == hash_api_key(new_plaintext)
    finally:
        conn.close()


def test_rotate_key_revoked_or_missing_exits_3(env: dict[str, str]) -> None:
    _, prefix = _seed(env, status="revoked")
    result = runner.invoke(app, ["rotate-key", prefix])
    assert result.exit_code == 3
    _clear_buffers()

    result = runner.invoke(app, ["rotate-key", "NOPENOPE"])
    assert result.exit_code == 3
