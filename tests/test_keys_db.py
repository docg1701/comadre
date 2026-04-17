"""Tests for comadre.keys.db — connection, migrations, insert."""

from __future__ import annotations

import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path

import pytest

from comadre.keys.db import (
    _SCHEMA_VERSION,
    _apply_migrations,
    generate_customer_id,
    generate_key_id,
    get_connection,
    get_customer,
    insert_api_key,
    insert_customer,
)
from comadre.keys.models import ApiKeyRecord, CustomerRecord


def _make_record(cid: str = "cust_01abcdef") -> CustomerRecord:
    return CustomerRecord(
        id=cid,
        name="Helena Ribeiro",
        email="helena@clinica.com",
        tax_id_kind="cpf",
        tax_id_encrypted=b"gAAAAA-ciphertext-blob-1234567890abcdef",
        notes="",
        registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
        deleted_at=None,
    )


class TestGenerateCustomerId:
    def test_format_prefix(self) -> None:
        cid = generate_customer_id()
        assert cid.startswith("cust_")

    def test_lowercase_ulid(self) -> None:
        cid = generate_customer_id()
        body = cid.removeprefix("cust_")
        assert body == body.lower()
        assert len(body) == 26

    def test_uniqueness(self) -> None:
        ids = {generate_customer_id() for _ in range(100)}
        assert len(ids) == 100


class TestGetConnection:
    def test_creates_parent_directory(self, tmp_path: Path) -> None:
        db_path = tmp_path / "nested" / "dir" / "registry.db"
        conn = get_connection(db_path)
        try:
            assert db_path.parent.exists()
            mode = stat.S_IMODE(db_path.parent.stat().st_mode)
            assert mode == 0o700
        finally:
            conn.close()

    def test_sets_file_permissions_0600(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            mode = stat.S_IMODE(db_path.stat().st_mode)
            assert mode == 0o600
        finally:
            conn.close()

    def test_enables_wal_mode(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"
        finally:
            conn.close()

    def test_enables_foreign_keys(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            result = conn.execute("PRAGMA foreign_keys").fetchone()[0]
            assert result == 1
        finally:
            conn.close()

    def test_row_factory_is_row(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            assert conn.row_factory is sqlite3.Row
        finally:
            conn.close()


class TestApplyMigrations:
    def test_fresh_db_creates_all_tables(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            tables = {
                row[0]
                for row in conn.execute(
                    "SELECT name FROM sqlite_master WHERE type='table'"
                )
            }
            assert {"customer", "api_key", "audit_log", "schema_version"} <= tables
        finally:
            conn.close()

    def test_fresh_db_records_schema_version(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            rows = conn.execute(
                "SELECT version, applied_at FROM schema_version"
            ).fetchall()
            assert len(rows) == 1
            assert rows[0]["version"] == _SCHEMA_VERSION
            assert rows[0]["applied_at"].endswith("Z")
        finally:
            conn.close()

    def test_rerun_is_noop(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            # Second run must not error (even though the v001 DDL has no
            # IF NOT EXISTS — the version sentinel prevents re-execution).
            _apply_migrations(conn)
            rows = conn.execute("SELECT COUNT(*) FROM schema_version").fetchone()[0]
            assert rows == 1
        finally:
            conn.close()

    def test_creates_expected_indexes(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
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
        finally:
            conn.close()


class TestInsertCustomer:
    def test_happy_path(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            rec = _make_record()
            insert_customer(conn, rec, actor="cli:tester")

            row = conn.execute(
                "SELECT * FROM customer WHERE id = ?", (rec.id,)
            ).fetchone()
            assert row is not None
            assert row["name"] == rec.name
            assert row["email"] == rec.email
            assert row["tax_id_kind"] == "cpf"
            assert bytes(row["tax_id_encrypted"]) == rec.tax_id_encrypted
            assert row["notes"] == ""
            assert row["registered_at"] == "2026-04-16T12:00:00Z"
            assert row["deleted_at"] is None

            audit_row = conn.execute(
                "SELECT * FROM audit_log WHERE target_id = ?", (rec.id,)
            ).fetchone()
            assert audit_row is not None
            assert audit_row["actor"] == "cli:tester"
            assert audit_row["action"] == "create_customer"
            assert audit_row["target_type"] == "customer"
            assert audit_row["details_json"] == '{"tax_id_kind": "cpf"}'
        finally:
            conn.close()

    def test_audit_failure_rolls_back_customer(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            rec = _make_record()

            def _boom(*_args: object, **_kw: object) -> None:
                raise sqlite3.IntegrityError("forced failure")

            import comadre.keys.audit as audit_module

            monkeypatch.setattr(audit_module, "log_event", _boom)

            with pytest.raises(sqlite3.IntegrityError):
                insert_customer(conn, rec, actor="cli:tester")

            count = conn.execute("SELECT COUNT(*) FROM customer").fetchone()[0]
            assert count == 0
        finally:
            conn.close()

    def test_parameterized_sql_no_injection(self, tmp_path: Path) -> None:
        """Inject SQL-ish content into the name; it must be stored verbatim."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            evil = "Helena'); DROP TABLE customer;--"
            rec = CustomerRecord(
                id="cust_evil",
                name=evil,
                email="e@e.com",
                tax_id_kind="cpf",
                tax_id_encrypted=b"ct",
                notes="",
                registered_at=datetime(2026, 4, 16, tzinfo=UTC),
                deleted_at=None,
            )
            insert_customer(conn, rec, actor="cli:tester")
            row = conn.execute(
                "SELECT name FROM customer WHERE id = ?", (rec.id,)
            ).fetchone()
            assert row["name"] == evil
            # customer table still exists
            conn.execute("SELECT 1 FROM customer")
        finally:
            conn.close()


class TestGenerateKeyId:
    def test_format_prefix(self) -> None:
        kid = generate_key_id()
        assert kid.startswith("key_")

    def test_total_length(self) -> None:
        # key_ (4) + 26 ULID chars = 30
        assert len(generate_key_id()) == 30

    def test_lowercase_ulid_body(self) -> None:
        kid = generate_key_id()
        body = kid.removeprefix("key_")
        assert body == body.lower()
        assert len(body) == 26

    def test_uniqueness(self) -> None:
        ids = {generate_key_id() for _ in range(100)}
        assert len(ids) == 100


def _seed_customer(conn: sqlite3.Connection) -> str:
    cid = generate_customer_id()
    insert_customer(
        conn,
        CustomerRecord(
            id=cid,
            name="Helena Ribeiro",
            email="helena@clinica.com",
            tax_id_kind="cpf",
            tax_id_encrypted=b"gAAAAA-ciphertext-blob",
            notes="",
            registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
            deleted_at=None,
        ),
        actor="cli:tester",
    )
    return cid


class TestGetCustomer:
    def test_returns_record_when_present(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)

            rec = get_customer(conn, cid)
            assert rec is not None
            assert rec.id == cid
            assert rec.name == "Helena Ribeiro"
            assert rec.email == "helena@clinica.com"
            assert rec.tax_id_kind == "cpf"
        finally:
            conn.close()

    def test_returns_none_for_missing_id(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            assert get_customer(conn, "cust_doesnotexist") is None
        finally:
            conn.close()

    def test_treats_tombstone_as_missing(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-17T00:00:00Z", cid),
            )
            conn.commit()
            assert get_customer(conn, cid) is None
        finally:
            conn.close()


def _api_key_record(customer_id: str, *, key_id: str = "key_01abc") -> ApiKeyRecord:
    return ApiKeyRecord(
        id=key_id,
        customer_id=customer_id,
        key_hash="a" * 64,
        key_prefix="ABCDEFGH",
        rate_limit_rpm=60,
        status="active",
        billing_mode="manual",
        price_monthly=149.0,
        paid_until=None,
        created_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
        last_used_at=None,
        notes="",
    )


class TestInsertApiKey:
    def test_creates_row_and_audit(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            key_id = generate_key_id()
            rec = _api_key_record(cid, key_id=key_id)
            insert_api_key(conn, rec, actor="cli:tester")

            row = conn.execute(
                "SELECT * FROM api_key WHERE id = ?", (rec.id,)
            ).fetchone()
            assert row is not None
            assert row["customer_id"] == cid
            assert row["key_hash"] == "a" * 64
            assert row["key_prefix"] == "ABCDEFGH"
            assert row["rate_limit_rpm"] == 60
            assert row["status"] == "active"
            assert row["billing_mode"] == "manual"
            assert row["price_monthly"] == 149.0
            assert row["paid_until"] is None
            assert row["created_at"] == "2026-04-16T12:00:00Z"
            assert row["last_used_at"] is None
            assert row["notes"] == ""

            audit = conn.execute(
                "SELECT * FROM audit_log WHERE target_id = ?", (rec.id,)
            ).fetchone()
            assert audit is not None
            assert audit["action"] == "issue_key"
            assert audit["target_type"] == "api_key"
            assert audit["actor"] == "cli:tester"
            assert audit["details_json"] == (
                '{"billing_mode": "manual", "rate_limit_rpm": 60}'
            )
        finally:
            conn.close()

    def test_rolls_back_when_audit_fails(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            rec = _api_key_record(cid)

            def _boom(*_args: object, **_kw: object) -> None:
                raise ValueError("forced audit failure")

            import comadre.keys.audit as audit_module

            monkeypatch.setattr(audit_module, "log_event", _boom)

            with pytest.raises(ValueError):
                insert_api_key(conn, rec, actor="cli:tester")

            count = conn.execute("SELECT COUNT(*) FROM api_key").fetchone()[0]
            assert count == 0
        finally:
            conn.close()

    def test_respects_foreign_key_constraint(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            rec = _api_key_record("cust_01jnoexistence000000000000")
            with pytest.raises(sqlite3.IntegrityError):
                insert_api_key(conn, rec, actor="cli:tester")
            assert conn.execute("SELECT COUNT(*) FROM api_key").fetchone()[0] == 0
        finally:
            conn.close()

    def test_duplicate_hash_raises(self, tmp_path: Path) -> None:
        """AC6 — UNIQUE index on key_hash causes IntegrityError on collision."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            first = _api_key_record(cid, key_id=generate_key_id())
            insert_api_key(conn, first, actor="cli:tester")

            # Same key_hash, different id → UNIQUE violation.
            dup = ApiKeyRecord(
                id=generate_key_id(),
                customer_id=cid,
                key_hash=first.key_hash,
                key_prefix="ZZZZZZZZ",
                rate_limit_rpm=120,
                status="active",
                billing_mode="manual",
                price_monthly=200.0,
                paid_until=None,
                created_at=datetime(2026, 4, 16, 12, 0, 1, tzinfo=UTC),
                last_used_at=None,
                notes="",
            )
            with pytest.raises(sqlite3.IntegrityError):
                insert_api_key(conn, dup, actor="cli:tester")
        finally:
            conn.close()

    def test_complimentary_stores_zero_price(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            rec = ApiKeyRecord(
                id=generate_key_id(),
                customer_id=cid,
                key_hash="b" * 64,
                key_prefix="COMP1234",
                rate_limit_rpm=120,
                status="active",
                billing_mode="complimentary",
                price_monthly=0.0,
                paid_until=None,
                created_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                last_used_at=None,
                notes="infra bundle",
            )
            insert_api_key(conn, rec, actor="cli:tester")
            row = conn.execute(
                "SELECT billing_mode, price_monthly, notes FROM api_key WHERE id = ?",
                (rec.id,),
            ).fetchone()
            assert row["billing_mode"] == "complimentary"
            assert row["price_monthly"] == 0.0
            assert row["notes"] == "infra bundle"

            audit = conn.execute(
                "SELECT details_json FROM audit_log WHERE target_id = ?",
                (rec.id,),
            ).fetchone()
            assert audit["details_json"] == (
                '{"billing_mode": "complimentary", "rate_limit_rpm": 120}'
            )
        finally:
            conn.close()
