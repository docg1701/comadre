"""End-to-end CLI tests for ``comadre-keys update-customer`` (Story 1.5).

Lean by design (test-suite review 2026-04-25): kept the user-observable
contract (email/note happy path, error envelope, LGPD audit-has-no-PII).
Every isolated --add-note variant, every individual usage-error test,
and every help-text reflection test was deleted; the pydantic / Click /
Typer layers test their own validation.
"""

from __future__ import annotations

import json
import sqlite3
from collections.abc import Callable
from datetime import date

from comadre.keys.cli.app import app
from tests._keys_cli_helpers import (
    buffers,
    clear_buffers,
    create_customer_via_cli,
    runner,
)


def _fetch(db_path: str, cid: str) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT email, notes FROM customer WHERE id = ?", (cid,)
        ).fetchone()
        return {"email": row["email"], "notes": row["notes"] or ""}
    finally:
        conn.close()


def test_update_customer_email_and_note_in_one_txn(
    env: dict[str, str], freeze_today: Callable[[date], None]
) -> None:
    """Happy path: --email + --add-note land in one txn; audit details
    list both fields; subsequent --add-note appends timestamped."""
    freeze_today(date(2026, 4, 20))
    cid = create_customer_via_cli(notes="5 bots")

    result = runner.invoke(
        app,
        [
            "update-customer",
            cid,
            "--email",
            "helena@novaclinica.com",
            "--add-note",
            "paga tarde",
        ],
    )
    stdout, stderr = buffers()
    assert result.exit_code == 0, stderr
    after = _fetch(env["db_path"], cid)
    assert after["email"] == "helena@novaclinica.com"
    assert after["notes"] == "5 bots\n[2026-04-20] paga tarde"
    assert "Updated: " in stdout

    clear_buffers()
    freeze_today(date(2026, 5, 12))
    runner.invoke(app, ["update-customer", cid, "--add-note", "upgraded"])
    after2 = _fetch(env["db_path"], cid)
    assert after2["notes"].endswith("[2026-05-12] upgraded")

    conn = sqlite3.connect(env["db_path"])
    try:
        count = conn.execute(
            "SELECT COUNT(*) FROM audit_log WHERE action = 'update_customer'"
        ).fetchone()[0]
    finally:
        conn.close()
    assert count == 2


def test_update_customer_audit_details_carries_only_field_names(
    env: dict[str, str], freeze_today: Callable[[date], None]
) -> None:
    """LGPD: audit ``details_json`` MUST list only the changed field names,
    never the values (no email-before/after, no notes content)."""
    freeze_today(date(2026, 4, 20))
    cid = create_customer_via_cli()
    runner.invoke(
        app,
        [
            "update-customer",
            cid,
            "--email",
            "secret@hidden.com",
            "--add-note",
            "PII content here",
        ],
    )
    conn = sqlite3.connect(env["db_path"])
    try:
        row = conn.execute(
            "SELECT details_json FROM audit_log "
            "WHERE action = 'update_customer' ORDER BY id DESC LIMIT 1"
        ).fetchone()
    finally:
        conn.close()
    details = json.loads(row[0])
    assert details == {"fields": ["email", "notes"]}
    assert "secret@hidden.com" not in row[0]
    assert "PII content here" not in row[0]


def test_update_customer_not_found_exits_3(env: dict[str, str]) -> None:
    """Missing customer ID → exit 3 with 'Not found' envelope."""
    result = runner.invoke(
        app,
        ["update-customer", "cust_missingxxxxxxxxxxxxxxxx", "--email", "x@x.com"],
    )
    _, stderr = buffers()
    assert result.exit_code == 3
    assert "Customer not found" in stderr


def test_update_customer_rejects_invalid_inputs(env: dict[str, str]) -> None:
    """Usage errors (no flags, malformed email, control bytes in note) all
    exit 2 — collapsed from 9 separate tests since the CLI dispatches
    them through the same validator pipeline."""
    cid = create_customer_via_cli()
    for bad_args in (
        ["update-customer", cid],
        ["update-customer", cid, "--email", "not-email"],
        ["update-customer", cid, "--add-note", "bad\x00byte"],
    ):
        clear_buffers()
        result = runner.invoke(app, bad_args)
        assert result.exit_code == 2, bad_args
