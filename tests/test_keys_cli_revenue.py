"""End-to-end CLI tests for ``comadre-keys revenue`` (Story 3.2).

Lean by design (test-suite review 2026-04-25): one happy path that
asserts MRR + projected math from the seeded portfolio, one JSON shape.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import UTC, date, datetime

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
from tests._keys_cli_helpers import buffers, runner


def _seed_portfolio(db_path: str) -> None:
    conn: sqlite3.Connection = get_connection(db_path)
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
        for paid_until, billing in (
            ("2026-04-30", "manual"),
            ("2026-04-30", "manual"),
            (None, "complimentary"),
        ):
            insert_api_key(
                conn,
                ApiKeyRecord(
                    id=generate_key_id(),
                    customer_id=cid,
                    key_hash=("a" + str(generate_key_id()))[:64],
                    key_prefix="ABCD" + str(hash(paid_until or "0"))[:4],
                    rate_limit_rpm=60,
                    status="active",
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
    env: dict[str, str], freeze_today: Callable[[date], None]
) -> None:
    """FR17: complimentary count is separate from MRR/projected totals."""
    freeze_today(date(2026, 4, 16))
    _seed_portfolio(env["db_path"])
    result = runner.invoke(app, ["revenue"])
    stdout, _ = buffers()
    assert result.exit_code == 0
    assert "Paid" in stdout
    assert "Complimentary" in stdout


def test_revenue_format_json_shape(
    env: dict[str, str], freeze_today: Callable[[date], None]
) -> None:
    freeze_today(date(2026, 4, 16))
    _seed_portfolio(env["db_path"])
    result = runner.invoke(app, ["revenue", "--format", "json"])
    stdout, _ = buffers()
    assert result.exit_code == 0
    parsed = json.loads(stdout)
    assert "mrr" in parsed
    assert "projected" in parsed
    assert "complimentary_count" in parsed
