"""Tests for ``comadre.keys.db`` — schema, rollback, encryption rotation.

Lean by design (test-suite review 2026-04-25): the per-function unit
tests of every CRUD helper were deleted because their behavior is
exercised end-to-end by the CLI integration tests for the verbs that
call them. What remains are the cases that ONLY a DB-layer test can
cover: schema/migration shape, transaction rollback semantics under
forced failure, encryption-rotation atomicity, and the hot auth-path
index.
"""

from __future__ import annotations

import json
import sqlite3
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

import pytest
from cryptography.fernet import Fernet, InvalidToken
from pydantic import SecretStr

from comadre.keys.crypto import decrypt_tax_id, encrypt_tax_id
from comadre.keys.db import (
    _SCHEMA_VERSION,
    _apply_migrations,
    delete_customer_hard,
    get_connection,
    insert_customer,
    lookup_key_auth,
    rotate_encryption_keys,
)
from comadre.keys.models import CustomerRecord, TaxIdKind
from comadre.keys.tokens import hash_api_key
from tests._keys_fixtures import seed_customer_and_key


def _make_record(cid: str = "cust_01abcdef") -> CustomerRecord:
    return CustomerRecord(
        id=cid,
        name="Helena Ribeiro",
        email="helena@clinica.com",
        tax_id_kind="cpf",
        tax_id_encrypted=b"ciphertext",
        notes="",
        registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
        deleted_at=None,
    )


def _seed_active_customer(
    conn: sqlite3.Connection,
    *,
    cid: str,
    canonical: str,
    tax_id_kind: str,
    key: SecretStr,
) -> None:
    insert_customer(
        conn,
        CustomerRecord(
            id=cid,
            name="Ana",
            email=f"{cid}@x.com",
            tax_id_kind=cast(TaxIdKind, tax_id_kind),
            tax_id_encrypted=encrypt_tax_id(canonical, key),
            notes="",
            registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
            deleted_at=None,
        ),
        actor="cli:tester",
    )


def test_migrations_create_schema_with_indexes(tmp_path: Path) -> None:
    """Fresh DB → all tables + every required index + schema_version row per file."""
    conn = get_connection(tmp_path / "registry.db")
    try:
        _apply_migrations(conn)

        tables = {
            row[0]
            for row in conn.execute("SELECT name FROM sqlite_master WHERE type='table'")
        }
        assert {"customer", "api_key", "audit_log", "schema_version"} <= tables

        indexes = {
            row[0]
            for row in conn.execute(
                "SELECT name FROM sqlite_master WHERE type='index' "
                "AND name NOT LIKE 'sqlite_%'"
            )
        }
        assert {
            "idx_api_key_hash",
            "idx_api_key_customer",
            "idx_api_key_sweep",
            "idx_audit_occurred",
        } <= indexes

        rows = conn.execute(
            "SELECT version FROM schema_version ORDER BY version"
        ).fetchall()
        assert len(rows) == _SCHEMA_VERSION
        assert rows[-1]["version"] == _SCHEMA_VERSION

        # Idempotency: re-running must not error or duplicate rows.
        _apply_migrations(conn)
        assert (
            conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
            == _SCHEMA_VERSION
        )
    finally:
        conn.close()


def test_v002_rate_limit_check_constraint_rejects_out_of_range(
    tmp_path: Path,
) -> None:
    """v002 — defense-in-depth against direct SQL edits / malformed restores.

    The CLI already caps ``rate_limit_rpm`` to 1..10000; the CHECK constraint
    is the second line of defence so a hand-edited ``.db`` file or a backup
    restored under a forked schema cannot plant a rogue value.
    """
    conn = get_connection(tmp_path / "registry.db")
    try:
        _apply_migrations(conn)
        conn.execute(
            "INSERT INTO customer "
            "(id, name, email, tax_id_kind, tax_id_encrypted, registered_at) "
            "VALUES ('cust_x', 'X', 'x@x.com', 'cpf', x'00', "
            "'2026-04-25T00:00:00Z')"
        )
        conn.commit()
        for bad_rpm in (0, 10001):
            with pytest.raises(sqlite3.IntegrityError, match="CHECK"):
                conn.execute(
                    "INSERT INTO api_key "
                    "(id, customer_id, key_hash, key_prefix, rate_limit_rpm, "
                    "status, billing_mode, created_at) VALUES "
                    "(?, 'cust_x', ?, 'p', ?, 'active', 'manual', "
                    "'2026-04-25T00:00:00Z')",
                    (f"key_{bad_rpm}", f"h{bad_rpm}", bad_rpm),
                )
    finally:
        conn.close()


def test_insert_customer_rolls_back_when_audit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """Audit-log INSERT failure must roll back the customer INSERT."""
    conn = get_connection(tmp_path / "registry.db")
    try:
        _apply_migrations(conn)

        import comadre.keys.audit as audit_module

        def _boom(*_args: object, **_kw: object) -> None:
            raise sqlite3.IntegrityError("forced")

        monkeypatch.setattr(audit_module, "log_event", _boom)

        with pytest.raises(sqlite3.IntegrityError):
            insert_customer(conn, _make_record(), actor="cli:tester")

        assert conn.execute("SELECT COUNT(*) FROM customer").fetchone()[0] == 0
    finally:
        conn.close()


def test_rotate_encryption_keys_happy_path_and_rollback(tmp_path: Path) -> None:
    """Story 4.2 atomicity: every active row re-encrypted under the new key,
    OR — on a wrong old key — every row left byte-identical and no audit.
    """
    old_key = SecretStr(Fernet.generate_key().decode())
    new_key = SecretStr(Fernet.generate_key().decode())

    # --- Happy path ---
    conn = get_connection(tmp_path / "happy.db")
    try:
        _apply_migrations(conn)
        seed = [
            ("cust_01aaaaaa", "12345678909", "cpf"),
            ("cust_01bbbbbb", "12345678000195", "cnpj"),
        ]
        for cid, canonical, kind in seed:
            _seed_active_customer(
                conn, cid=cid, canonical=canonical, tax_id_kind=kind, key=old_key
            )

        result = rotate_encryption_keys(
            conn, old_key=old_key, new_key=new_key, actor="cli:tester"
        )
        assert result.rows_re_encrypted == 2

        rows = {
            r["id"]: bytes(r["tax_id_encrypted"])
            for r in conn.execute(
                "SELECT id, tax_id_encrypted FROM customer WHERE deleted_at IS NULL"
            )
        }
        assert decrypt_tax_id(rows["cust_01aaaaaa"], new_key) == "12345678909"
        assert decrypt_tax_id(rows["cust_01bbbbbb"], new_key) == "12345678000195"
        with pytest.raises(InvalidToken):
            decrypt_tax_id(rows["cust_01aaaaaa"], old_key)

        audit = conn.execute(
            "SELECT details_json FROM audit_log WHERE action = 'rotate_encryption_key'"
        ).fetchall()
        assert len(audit) == 1
        assert json.loads(audit[0]["details_json"]) == {"rows_re_encrypted": 2}
    finally:
        conn.close()

    # --- Rollback path: wrong old key must leave state intact ---
    wrong_old_key = SecretStr(Fernet.generate_key().decode())
    conn = get_connection(tmp_path / "rollback.db")
    try:
        _apply_migrations(conn)
        for idx in range(3):
            _seed_active_customer(
                conn,
                cid=f"cust_01rb{idx:02d}xxxxxxx",
                canonical="12345678909",
                tax_id_kind="cpf",
                key=old_key,
            )

        pre = {
            r["id"]: bytes(r["tax_id_encrypted"])
            for r in conn.execute("SELECT id, tax_id_encrypted FROM customer")
        }

        with pytest.raises(InvalidToken):
            rotate_encryption_keys(
                conn,
                old_key=wrong_old_key,
                new_key=new_key,
                actor="cli:tester",
            )

        post = {
            r["id"]: bytes(r["tax_id_encrypted"])
            for r in conn.execute("SELECT id, tax_id_encrypted FROM customer")
        }
        assert post == pre
        assert (
            conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'rotate_encryption_key'"
            ).fetchone()[0]
            == 0
        )
    finally:
        conn.close()


def test_delete_customer_hard_rolls_back_when_audit_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    """LGPD purge atomicity: customer + key rows survive an audit failure."""
    conn = get_connection(tmp_path / "registry.db")
    try:
        _apply_migrations(conn)
        _, kid, cid = seed_customer_and_key(conn)

        import comadre.keys.audit as audit_module

        def _boom(*_args: object, **_kw: object) -> None:
            raise ValueError("forced")

        monkeypatch.setattr(audit_module, "log_event", _boom)

        with pytest.raises(ValueError):
            delete_customer_hard(conn, cid, actor="cli:tester")

        row = conn.execute(
            "SELECT name, deleted_at FROM customer WHERE id = ?", (cid,)
        ).fetchone()
        assert row["name"] == "Helena Ribeiro"
        assert row["deleted_at"] is None
        assert (
            conn.execute("SELECT id FROM api_key WHERE id = ?", (kid,)).fetchone()
            is not None
        )
    finally:
        conn.close()


def test_lookup_key_auth_uses_hash_index(tmp_path: Path) -> None:
    """Hot path on every ``POST /v1/audio/speech`` — must do an indexed
    seek on ``key_hash``, not a table scan. A regression here would
    quadratically degrade auth latency as the registry grows.
    """
    conn = get_connection(tmp_path / "registry.db")
    try:
        _apply_migrations(conn)
        plaintext, _, _ = seed_customer_and_key(conn)
        key_hash = hash_api_key(plaintext)

        plan = conn.execute(
            "EXPLAIN QUERY PLAN SELECT id, customer_id, status, billing_mode, "
            "rate_limit_rpm, paid_until FROM api_key WHERE key_hash = ? LIMIT 1",
            (key_hash,),
        ).fetchall()
        plan_text = " ".join(str(row["detail"]) for row in plan)
        assert "idx_api_key_hash" in plan_text

        # And the hot-path helper itself returns the row (smoke).
        payload = lookup_key_auth(conn, key_hash)
        assert payload is not None
        assert payload.status == "active"
    finally:
        conn.close()
