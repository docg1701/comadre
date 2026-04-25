"""End-to-end CLI tests for ``comadre-keys issue-key`` (Story 1.2).

Lean by design (test-suite review 2026-04-25): one happy path per
billing mode, one error envelope test, one customer-not-found.
Exhaustive boundary spam (--rpm 0, -1, > cap, NaN, negative price)
deleted; Click + pydantic test their own validation.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from comadre.keys.cli import _clock
from comadre.keys.cli.app import app
from tests._keys_cli_helpers import buffers as _buffers
from tests._keys_cli_helpers import clear_buffers as _clear_buffers

runner = CliRunner()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    key = Fernet.generate_key().decode()
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", key)
    monkeypatch.setattr(_clock, "resolve_today_in_tz", lambda _tz: date(2026, 4, 13))
    return {"db_path": str(db_path), "key": key}


def _seed_customer(env: dict[str, str]) -> str:
    _clear_buffers()
    result = runner.invoke(
        app,
        [
            "create-customer",
            "--name",
            "Helena Ribeiro",
            "--email",
            "helena@clinica.com",
            "--cpf",
            "123.456.789-09",
        ],
    )
    assert result.exit_code == 0, result.output
    stdout, _ = _buffers()
    match = re.search(r"cust_[0-9a-z]{26}", stdout)
    assert match is not None
    _clear_buffers()
    return match.group(0)


def test_issue_key_manual_happy_path(env: dict[str, str]) -> None:
    """Issue manual key → plaintext printed once + DB row + audit row.

    Asserts every contract a downstream operator depends on: plaintext
    line shape, copy warning, DB row business fields, audit details
    contain only metadata (no PII)."""
    customer_id = _seed_customer(env)

    result = runner.invoke(
        app,
        ["issue-key", "--customer", customer_id, "--rpm", "60", "--price", "149"],
    )
    stdout, stderr = _buffers()
    assert result.exit_code == 0, stderr
    assert stderr == ""
    match = re.search(r"cmdr_live_[A-Za-z0-9_-]{43}", stdout)
    assert match is not None
    plaintext = match.group(0)
    assert stdout.count(plaintext) == 1  # exactly once
    assert "copy now" in stdout
    assert "60/min" in stdout
    assert "R$ 149,00/month" in stdout

    # DB + audit assertions.
    conn = sqlite3.connect(env["db_path"])
    conn.row_factory = sqlite3.Row
    try:
        row = conn.execute("SELECT * FROM api_key").fetchone()
        assert row["customer_id"] == customer_id
        assert row["rate_limit_rpm"] == 60
        assert row["billing_mode"] == "manual"
        assert row["price_monthly"] == 149.0
        assert row["status"] == "active"
        assert re.fullmatch(r"[0-9a-f]{64}", row["key_hash"])
        # Hash never appears in stdout — only the plaintext does.
        assert row["key_hash"] not in stdout

        audit = conn.execute(
            "SELECT details_json FROM audit_log WHERE action = 'issue_key'"
        ).fetchone()
        assert json.loads(audit[0]) == {"billing_mode": "manual", "rate_limit_rpm": 60}
    finally:
        conn.close()


def test_issue_key_complimentary_happy_path(env: dict[str, str]) -> None:
    """Complimentary mode stores price=0 and skips first-charge calc."""
    customer_id = _seed_customer(env)

    result = runner.invoke(
        app,
        [
            "issue-key",
            "--customer",
            customer_id,
            "--rpm",
            "120",
            "--billing-mode",
            "complimentary",
        ],
    )
    stdout, _ = _buffers()
    assert result.exit_code == 0
    assert "complimentary" in stdout

    conn = sqlite3.connect(env["db_path"])
    try:
        row = conn.execute("SELECT billing_mode, price_monthly FROM api_key").fetchone()
        assert row[0] == "complimentary"
        assert row[1] == 0.0
    finally:
        conn.close()


def test_issue_key_customer_not_found_exits_3(env: dict[str, str]) -> None:
    """Missing customer → exit 3, no key written, no audit row."""
    result = runner.invoke(
        app,
        [
            "issue-key",
            "--customer",
            "cust_missingxxxxxxxxxxxxxxxx",
            "--rpm",
            "60",
            "--price",
            "149",
        ],
    )
    _, stderr = _buffers()
    assert result.exit_code == 3
    assert "Customer not found" in stderr

    conn = sqlite3.connect(env["db_path"])
    try:
        assert conn.execute("SELECT COUNT(*) FROM api_key").fetchone()[0] == 0
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'issue_key'"
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_issue_key_rejects_invalid_inputs(env: dict[str, str]) -> None:
    """Mode/price/rpm invariants exit 2: complimentary+price, manual
    no-price, --rpm out of range. Collapsed from 9 boundary tests."""
    customer_id = _seed_customer(env)

    # Manual without --price → exit 2.
    result = runner.invoke(app, ["issue-key", "--customer", customer_id, "--rpm", "60"])
    assert result.exit_code == 2
    _clear_buffers()

    # Complimentary with --price → exit 2.
    result = runner.invoke(
        app,
        [
            "issue-key",
            "--customer",
            customer_id,
            "--rpm",
            "60",
            "--billing-mode",
            "complimentary",
            "--price",
            "10",
        ],
    )
    assert result.exit_code == 2
    _clear_buffers()

    # --rpm above cap → exit 2.
    result = runner.invoke(
        app,
        ["issue-key", "--customer", customer_id, "--rpm", "10001", "--price", "149"],
    )
    assert result.exit_code == 2
