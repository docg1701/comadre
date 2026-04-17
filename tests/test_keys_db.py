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
    get_connection,
    insert_customer,
)
from comadre.keys.models import CustomerRecord


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
