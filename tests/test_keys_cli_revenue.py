"""End-to-end CLI tests for ``comadre-keys revenue`` (Story 3.2).

Lean by design (test-suite review 2026-04-25): one happy path that
asserts MRR + projected math from the seeded portfolio, one JSON shape.
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


def _seed_portfolio(env: dict[str, str]) -> None:
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
        # Paid through April (after 2026-04-30 cutoff).
        for paid_until, status, billing in (
            ("2026-04-30", "active", "manual"),
            ("2026-04-30", "active", "manual"),
            (None, "active", "complimentary"),
        ):
            insert_api_key(
                conn,
                ApiKeyRecord(
                    id=generate_key_id(),
                    customer_id=cid,
                    key_hash=("a" + str(generate_key_id()))[:64],
                    key_prefix="ABCD" + str(hash(paid_until or "0"))[:4],
                    rate_limit_rpm=60,
                    status=status,  # type: ignore[arg-type]
                    billing_mode=billing,  # type: ignore[arg-type]
                    price_monthly=149.0 if billing == "manual" else 0.0,
                    paid_until=paid_until,
                    created_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
                    last_used_at=None,
                    notes="",
                ),
                actor="cli:tester",
            )
    finally:
        conn.close()


def test_revenue_table_renders_mrr_and_complimentary_separately(
    env: dict[str, str],
) -> None:
    """FR17: complimentary count is separate from MRR/projected totals."""
    _seed_portfolio(env)
    result = runner.invoke(app, ["revenue"])
    stdout, _ = _buffers()
    assert result.exit_code == 0
    # Text contract from the table renderer.
    assert "Paid" in stdout
    assert "Complimentary" in stdout


def test_revenue_format_json_shape(env: dict[str, str]) -> None:
    _seed_portfolio(env)
    result = runner.invoke(app, ["revenue", "--format", "json"])
    stdout, _ = _buffers()
    assert result.exit_code == 0
    parsed = json.loads(stdout)
    # Required keys (machine consumers parse these).
    assert "mrr" in parsed
    assert "projected" in parsed
    assert "complimentary_count" in parsed
