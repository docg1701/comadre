"""End-to-end CLI tests for ``comadre-keys mark-paid`` (Story 3.1).

Lean by design (test-suite review 2026-04-25): one happy path that
proves the audit + state contract; one not-found / invalid-state.
"""

from __future__ import annotations

import sqlite3

from comadre.keys.cli.app import app
from tests._keys_cli_helpers import buffers, runner, seed_by_prefix


def test_mark_paid_extends_paid_until_and_audits(env: dict[str, str]) -> None:
    """Happy path: paid_until updated; audit row written with the new date."""
    _, _, prefix = seed_by_prefix(env["db_path"])
    result = runner.invoke(app, ["mark-paid", prefix, "--until", "2026-06-05"])
    _, stderr = buffers()
    assert result.exit_code == 0, stderr

    conn = sqlite3.connect(env["db_path"])
    try:
        row = conn.execute(
            "SELECT paid_until FROM api_key WHERE key_prefix = ?", (prefix,)
        ).fetchone()
        assert row[0] == "2026-06-05"
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'mark_paid'"
            ).fetchone()[0]
            == 1
        )
    finally:
        conn.close()


def test_mark_paid_missing_key_exits_3(env: dict[str, str]) -> None:
    """Missing key prefix exits 3."""
    result = runner.invoke(app, ["mark-paid", "NOPENOPE", "--until", "2026-06-05"])
    assert result.exit_code == 3
