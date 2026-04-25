"""End-to-end CLI tests for ``comadre-keys show`` (Story 1.4).

Lean by design (test-suite review 2026-04-25): kept only the
behavioural contracts a downstream user depends on — full panel labels
on a happy show, LGPD ciphertext non-leak, audit-tail flag, JSON shape,
and the not-found error envelope. Per-status / per-billing-mode label
tests, boundary spam on ``--audit-tail``, and write-side smoke tests
were deleted; they are exercised by the verb integrations they cite.
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
    assert match is not None, stdout
    _clear_buffers()
    return match.group(0)


def _issue_key(env: dict[str, str], customer_id: str) -> tuple[str, str]:
    _clear_buffers()
    result = runner.invoke(
        app,
        [
            "issue-key",
            "--customer",
            customer_id,
            "--rpm",
            "60",
            "--billing-mode",
            "manual",
            "--price",
            "149.0",
        ],
    )
    assert result.exit_code == 0, result.output
    _clear_buffers()
    conn = sqlite3.connect(env["db_path"])
    try:
        row = conn.execute(
            "SELECT id, key_prefix FROM api_key WHERE customer_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (customer_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return str(row[0]), str(row[1])


def _freeze_today(monkeypatch: pytest.MonkeyPatch, today: date) -> None:
    monkeypatch.setattr(_clock, "resolve_today_in_tz", lambda _tz: today)


def test_show_key_renders_full_detail_panel(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """Happy path: every contractual label + business value present, no audit
    section unless ``--audit-tail`` requested."""
    from datetime import UTC, datetime

    customer_id = _seed_customer(env)
    _, key_prefix = _issue_key(env, customer_id)
    _freeze_today(monkeypatch, datetime.now(UTC).date())

    result = runner.invoke(app, ["show", key_prefix])
    stdout, stderr = _buffers()
    assert result.exit_code == 0, stderr

    for label in (
        "Prefix:",
        "Customer:",
        "Status:",
        "RPM:",
        "Price:",
        "Billing:",
        "Paid Until:",
        "Created:",
        "Last Used:",
        "Age:",
        "Notes:",
    ):
        assert label in stdout
    assert f"Key: {key_prefix}" in stdout
    assert "active" in stdout
    assert "60/min" in stdout
    assert "R$ 149,00/month" in stdout
    assert "today" in stdout
    assert "—" in stdout  # em-dash for null Paid Until
    # No audit section when --audit-tail is absent.
    assert "events:" not in stdout


def test_show_customer_does_not_leak_ciphertext(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """LGPD: tax_id_encrypted must NEVER reach stdout/stderr."""
    _freeze_today(monkeypatch, date(2026, 4, 16))
    customer_id = _seed_customer(env)
    result = runner.invoke(app, ["show", customer_id])
    stdout, stderr = _buffers()
    assert result.exit_code == 0
    combined = stdout + stderr
    assert "gAAAAA" not in combined
    # No base64-shaped long run (Fernet token / encoded blob hint).
    assert not re.search(r"[A-Za-z0-9+/=_-]{60,}", combined)


def test_show_audit_tail_renders_newest_first_with_details(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """``--audit-tail N`` surfaces the per-key event log, newest first,
    rendering details_json verbatim."""
    _freeze_today(monkeypatch, date(2026, 4, 16))
    customer_id = _seed_customer(env)
    key_id, key_prefix = _issue_key(env, customer_id)
    conn = sqlite3.connect(env["db_path"])
    try:
        conn.execute(
            "INSERT INTO audit_log "
            "(occurred_at, actor, action, target_type, target_id, details_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (
                "2099-04-16T09:15:00Z",
                "cli:ricardo",
                "update_key",
                "api_key",
                key_id,
                '{"notes": "bumped rpm"}',
            ),
        )
        conn.commit()
    finally:
        conn.close()

    result = runner.invoke(app, ["show", key_prefix, "--audit-tail", "20"])
    stdout, stderr = _buffers()
    assert result.exit_code == 0, stderr
    assert "UPDATE_KEY" in stdout
    assert "ISSUE_KEY" in stdout
    # Newest first.
    assert stdout.index("UPDATE_KEY") < stdout.index("ISSUE_KEY")
    # Details column rendered verbatim.
    assert '{"notes": "bumped rpm"}' in stdout


def test_show_format_json_emits_fixed_key_order(
    env: dict[str, str], monkeypatch: pytest.MonkeyPatch
) -> None:
    """AC8 — JSON shape is a machine contract: customer and key targets
    each have a fixed key order. A regression to ``dict(sorted(...))`` is
    caught here."""
    _freeze_today(monkeypatch, date(2026, 4, 16))
    customer_id = _seed_customer(env)
    key_id, key_prefix = _issue_key(env, customer_id)

    # Customer target
    result = runner.invoke(app, ["show", customer_id, "--format", "json"])
    stdout, _ = _buffers()
    assert result.exit_code == 0
    parsed = json.loads(stdout)
    assert parsed["target_type"] == "customer"
    assert list(parsed["target"].keys()) == [
        "id",
        "name",
        "email",
        "tax_id_kind",
        "key_count",
        "registered_at",
        "notes",
    ]
    _clear_buffers()

    # Key target — also asserts no key_hash leak.
    result = runner.invoke(app, ["show", key_prefix, "--format", "json"])
    stdout, _ = _buffers()
    assert result.exit_code == 0
    parsed = json.loads(stdout)
    assert parsed["target_type"] == "api_key"
    target = parsed["target"]
    assert list(target.keys()) == [
        "id",
        "customer_id",
        "customer_name",
        "key_prefix",
        "status",
        "billing_mode",
        "rate_limit_rpm",
        "price_monthly",
        "paid_until",
        "created_at",
        "last_used_at",
        "age_days",
        "notes",
    ]
    assert "key_hash" not in target
    assert target["id"] == key_id


def test_show_not_found_exits_3(env: dict[str, str]) -> None:
    """Unknown prefix, unknown customer-id, and tombstoned customer all
    return the same 'not found' envelope at exit 3."""
    # Unknown free-form operand.
    result = runner.invoke(app, ["show", "NOPENOPE"])
    _, stderr = _buffers()
    assert result.exit_code == 3
    assert "Not found: no customer or key matches 'NOPENOPE'" in stderr
    _clear_buffers()

    # Tombstoned customer is treated as missing.
    customer_id = _seed_customer(env)
    conn = sqlite3.connect(env["db_path"])
    try:
        conn.execute(
            "UPDATE customer SET deleted_at = ? WHERE id = ?",
            ("2026-04-20T00:00:00Z", customer_id),
        )
        conn.commit()
    finally:
        conn.close()
    result = runner.invoke(app, ["show", customer_id])
    _, stderr = _buffers()
    assert result.exit_code == 3
    assert "Not found" in stderr
