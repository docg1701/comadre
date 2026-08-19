"""End-to-end CLI tests for ``comadre-keys delete-customer`` (Story 4.1).

Lean by design (test-suite review 2026-04-25): LGPD purge contract is
the survivor — customer + keys hard-deleted, tombstone written, audit
emitted with no PII.
"""

from __future__ import annotations

import json
import sqlite3

from comadre.keys.cli.app import app
from tests._keys_cli_helpers import buffers, clear_buffers, runner, seed_by_prefix


def test_delete_customer_hard_purges_rows_writes_audit_no_pii(
    env: dict[str, str],
) -> None:
    """LGPD purge: customer scrubbed (PII zeroed) + tombstone stamped +
    api_key rows deleted + audit row written with no email/name in details."""
    cid, _kid, _ = seed_by_prefix(env["db_path"], customer_email="helena@clinica.com")
    result = runner.invoke(app, ["delete-customer", cid, "--hard", "--yes"])
    _, stderr = buffers()
    assert result.exit_code == 0, stderr

    conn = sqlite3.connect(env["db_path"])
    try:
        row = conn.execute(
            "SELECT name, email, deleted_at FROM customer WHERE id = ?", (cid,)
        ).fetchone()
        assert row[0] == ""
        assert row[1] == ""
        assert row[2] is not None
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM api_key WHERE customer_id = ?", (cid,)
            ).fetchone()[0]
            == 0
        )
        audit = conn.execute(
            "SELECT details_json FROM audit_log WHERE action = 'delete_customer'"
        ).fetchone()
        details = json.loads(audit[0])
        assert "email" not in details
        assert "name" not in details
        assert details.get("keys_purged") == 1
    finally:
        conn.close()


def test_delete_customer_not_found_exits_3(env: dict[str, str]) -> None:
    result = runner.invoke(
        app, ["delete-customer", "cust_00000000000000000000000000", "--hard", "--yes"]
    )
    assert result.exit_code == 3
    clear_buffers()


def test_delete_customer_hard_purges_voice_clones_and_audits_count(
    env: dict[str, str],
    tmp_path,
    monkeypatch,
) -> None:
    """v3 LGPD: hard-delete purges the customer stored voice clones
    (files deleted), leaves other voices intact, and records
    voices_deleted in the audit row."""
    from ulid import ULID

    from comadre import voice_storage

    cid, _kid, _ = seed_by_prefix(env["db_path"], customer_email="helena@clinica.com")
    monkeypatch.setenv("VOICES_DIR", str(tmp_path))
    pocket_dir = tmp_path / "pocket"
    pocket_dir.mkdir()

    for _ in range(2):
        name = f"u_{ULID()}"
        (pocket_dir / f"{name}.wav").write_bytes(b"x")
        voice_storage.write_meta(pocket_dir, name, customer_id=cid)
    other = f"u_{ULID()}"
    (pocket_dir / f"{other}.wav").write_bytes(b"x")
    voice_storage.write_meta(pocket_dir, other, customer_id="cust_other")
    (pocket_dir / "operadora.wav").write_bytes(b"x")

    result = runner.invoke(app, ["delete-customer", cid, "--hard", "--yes"])
    _, stderr = buffers()
    assert result.exit_code == 0, stderr
    assert voice_storage.count_by_customer(pocket_dir, cid) == 0
    assert voice_storage.count_by_customer(pocket_dir, "cust_other") == 1
    assert (pocket_dir / "operadora.wav").is_file()

    conn = sqlite3.connect(env["db_path"])
    try:
        audit = conn.execute(
            "SELECT details_json FROM audit_log WHERE action = 'delete_customer'"
        ).fetchone()
        details = json.loads(audit[0])
        assert details.get("voices_deleted") == 2
    finally:
        conn.close()
