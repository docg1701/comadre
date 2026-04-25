"""End-to-end CLI tests for ``comadre-keys at-risk`` (Story 3.2).

Lean by design (test-suite review 2026-04-25): one happy path with
content assertion, one --format json shape.
"""

from __future__ import annotations

import json
from datetime import UTC, date, datetime
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from comadre.keys.cli import _clock
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
    monkeypatch.setattr(_clock, "resolve_today_in_tz", lambda _tz: date(2026, 4, 16))
    return {"db_path": str(db_path), "key": key}


def _seed_at_risk(env: dict[str, str]) -> None:
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
        # Two at-risk keys (paid_until within 5 days of 2026-04-16).
        for prefix, paid_until in (
            ("RISKY1AA", "2026-04-18"),
            ("RISKY2BB", "2026-04-20"),
        ):
            insert_api_key(
                conn,
                ApiKeyRecord(
                    id=generate_key_id(),
                    customer_id=cid,
                    key_hash=prefix.lower() * 8,
                    key_prefix=prefix,
                    rate_limit_rpm=60,
                    status="active",
                    billing_mode="manual",
                    price_monthly=149.0,
                    paid_until=paid_until,
                    created_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
                    last_used_at=None,
                    notes="",
                ),
                actor="cli:tester",
            )
    finally:
        conn.close()


def test_at_risk_table_lists_keys_within_window(env: dict[str, str]) -> None:
    _seed_at_risk(env)
    result = runner.invoke(app, ["at-risk", "--window", "5d"])
    stdout, _ = _buffers()
    assert result.exit_code == 0
    assert "RISKY1AA" in stdout
    assert "RISKY2BB" in stdout


def test_at_risk_format_json_emits_array(env: dict[str, str]) -> None:
    _seed_at_risk(env)
    result = runner.invoke(app, ["at-risk", "--window", "5d", "--format", "json"])
    stdout, _ = _buffers()
    assert result.exit_code == 0
    parsed = json.loads(stdout)
    # Array shape; both rows present.
    assert isinstance(parsed, (dict, list))
    text = json.dumps(parsed)
    assert "RISKY1AA" in text
    assert "RISKY2BB" in text
