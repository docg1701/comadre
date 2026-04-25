"""End-to-end CLI tests for ``comadre-keys export-customer`` (Story 4.1).

Lean by design (test-suite review 2026-04-25): one happy path that
verifies LGPD export shape (decrypted tax_id present + ciphertext NEVER
on stdout), one not-found.
"""

from __future__ import annotations

import json
import re
from datetime import UTC, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from typer.testing import CliRunner

from comadre.keys.cli.app import app
from comadre.keys.crypto import encrypt_tax_id
from comadre.keys.db import (
    _apply_migrations,
    generate_customer_id,
    get_connection,
    insert_customer,
)
from comadre.keys.models import CustomerRecord
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


def _seed_customer(env: dict[str, str]) -> str:
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
                tax_id_encrypted=encrypt_tax_id("12345678909", SecretStr(env["key"])),
                notes="",
                registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                deleted_at=None,
            ),
            actor="cli:tester",
        )
    finally:
        conn.close()
    return cid


def test_export_customer_emits_decrypted_tax_id_no_ciphertext_in_stdout(
    env: dict[str, str],
) -> None:
    """LGPD: export decrypts tax_id; the ciphertext blob must NEVER appear
    on stdout (anywhere)."""
    cid = _seed_customer(env)

    result = runner.invoke(app, ["export-customer", cid])
    stdout, _ = _buffers()
    assert result.exit_code == 0
    parsed = json.loads(stdout)
    assert parsed["id"] == cid
    assert parsed["tax_id"] == "123.456.789-09"  # decrypted, formatted
    # Ciphertext fingerprints absent.
    assert "gAAAAA" not in stdout
    assert "tax_id_encrypted" not in parsed
    # No base64 blob.
    assert not re.search(r"[A-Za-z0-9+/=_-]{60,}", stdout)


def test_export_customer_not_found_exits_3(env: dict[str, str]) -> None:
    # Use a shape-valid but unseeded customer id (26 lowercase alphanumeric).
    result = runner.invoke(app, ["export-customer", "cust_00000000000000000000000000"])
    assert result.exit_code == 3
    _clear_buffers()
