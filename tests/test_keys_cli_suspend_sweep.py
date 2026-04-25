"""End-to-end CLI tests for ``comadre-keys suspend-sweep`` (Story 3.3).

Lean by design (test-suite review 2026-04-25): one happy path that
proves the cron-mode sweep flips expired keys to suspended.
"""

from __future__ import annotations

import sqlite3
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


def _seed(env: dict[str, str], paid_until: str) -> str:
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
                key_prefix="EXPIRED1",
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
    return kid


def test_suspend_sweep_flips_expired_keys_to_suspended(env: dict[str, str]) -> None:
    """``paid_until < today`` → flips to suspended; one cron_suspend audit row."""
    kid = _seed(env, paid_until="2026-04-10")  # past

    result = runner.invoke(app, ["suspend-sweep"])
    _, stderr = _buffers()
    assert result.exit_code == 0, stderr

    conn = sqlite3.connect(env["db_path"])
    try:
        row = conn.execute("SELECT status FROM api_key WHERE id = ?", (kid,)).fetchone()
        assert row[0] == "suspended"
        cron_audits = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'cron_suspend'"
        ).fetchone()[0]
        assert cron_audits >= 1
    finally:
        conn.close()


def test_suspend_sweep_dry_run_does_not_mutate(env: dict[str, str]) -> None:
    """``--dry-run`` previews without writing."""
    kid = _seed(env, paid_until="2026-04-10")
    result = runner.invoke(app, ["suspend-sweep", "--dry-run"])
    assert result.exit_code == 0
    conn = sqlite3.connect(env["db_path"])
    try:
        row = conn.execute("SELECT status FROM api_key WHERE id = ?", (kid,)).fetchone()
        assert row[0] == "active"
    finally:
        conn.close()
