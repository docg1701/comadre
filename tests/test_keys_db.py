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
    count_tombstones,
    generate_customer_id,
    generate_key_id,
    get_connection,
    get_customer,
    insert_api_key,
    insert_customer,
    is_first_run,
    is_first_run_for_keys,
    list_api_keys,
    list_customers,
)
from comadre.keys.models import (
    ApiKeyRecord,
    BillingMode,
    CustomerRecord,
    CustomerStatus,
)


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


def _seed_customer_with_time(
    conn: sqlite3.Connection,
    *,
    name: str,
    registered_at: str,
    email: str | None = None,
    tax_id_kind: str = "cpf",
) -> str:
    """Seed a customer with a caller-controlled ``registered_at`` timestamp."""
    cid = generate_customer_id()
    conn.execute(
        "INSERT INTO customer ("
        "id, name, email, tax_id_kind, tax_id_encrypted, notes, "
        "registered_at, deleted_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            cid,
            name,
            email or f"{name.replace(' ', '.').lower()}@example.com",
            tax_id_kind,
            b"ciphertext",
            "",
            registered_at,
            None,
        ),
    )
    conn.commit()
    return cid


def _seed_api_key(
    conn: sqlite3.Connection,
    *,
    customer_id: str,
    key_hash: str,
    key_prefix: str = "ABCDEFGH",
    status: str = "active",
    billing_mode: str = "manual",
    rate_limit_rpm: int = 60,
    price_monthly: float = 149.0,
    paid_until: str | None = None,
    created_at: str = "2026-04-16T12:00:00Z",
) -> str:
    key_id = generate_key_id()
    conn.execute(
        "INSERT INTO api_key ("
        "id, customer_id, key_hash, key_prefix, rate_limit_rpm, status, "
        "billing_mode, price_monthly, paid_until, created_at, last_used_at, "
        "notes"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            key_id,
            customer_id,
            key_hash,
            key_prefix,
            rate_limit_rpm,
            status,
            billing_mode,
            price_monthly,
            paid_until,
            created_at,
            None,
            "",
        ),
    )
    conn.commit()
    return key_id


def _count_rows(conn: sqlite3.Connection, table: str) -> int:
    return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])


class TestListCustomers:
    def test_returns_rows_sorted_by_registered_at(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            c1 = _seed_customer_with_time(
                conn, name="Alpha", registered_at="2026-04-10T10:00:00Z"
            )
            c2 = _seed_customer_with_time(
                conn, name="Bravo", registered_at="2026-04-11T10:00:00Z"
            )
            c3 = _seed_customer_with_time(
                conn, name="Charlie", registered_at="2026-04-12T10:00:00Z"
            )
            rows = list_customers(conn, include_deleted=False)
            assert [r.id for r in rows] == [c1, c2, c3]
        finally:
            conn.close()

    def test_counts_keys_per_customer(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            c1 = _seed_customer_with_time(
                conn, name="WithKeys", registered_at="2026-04-10T10:00:00Z"
            )
            c2 = _seed_customer_with_time(
                conn, name="OneKey", registered_at="2026-04-11T10:00:00Z"
            )
            c3 = _seed_customer_with_time(
                conn, name="NoKeys", registered_at="2026-04-12T10:00:00Z"
            )
            _seed_api_key(
                conn, customer_id=c1, key_hash="a" * 64, key_prefix="KEY1AAAA"
            )
            _seed_api_key(
                conn,
                customer_id=c1,
                key_hash="b" * 64,
                key_prefix="KEY2AAAA",
                billing_mode="complimentary",
                price_monthly=0.0,
            )
            _seed_api_key(
                conn, customer_id=c2, key_hash="c" * 64, key_prefix="KEY3AAAA"
            )

            rows = list_customers(conn, include_deleted=False)
            by_id = {r.id: r for r in rows}
            assert by_id[c1].key_count == 2
            assert by_id[c2].key_count == 1
            assert by_id[c3].key_count == 0
        finally:
            conn.close()

    def test_excludes_tombstones_by_default(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            alive = _seed_customer_with_time(
                conn, name="Alive", registered_at="2026-04-10T10:00:00Z"
            )
            dead = _seed_customer_with_time(
                conn, name="Dead", registered_at="2026-04-11T10:00:00Z"
            )
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-15T00:00:00Z", dead),
            )
            conn.commit()

            rows = list_customers(conn, include_deleted=False)
            assert [r.id for r in rows] == [alive]

            rows_all = list_customers(conn, include_deleted=True)
            assert {r.id for r in rows_all} == {alive, dead}
            dead_row = next(r for r in rows_all if r.id == dead)
            assert dead_row.deleted_at == "2026-04-15T00:00:00Z"
        finally:
            conn.close()

    def test_empty_returns_empty_list(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            assert list_customers(conn, include_deleted=False) == []
            assert list_customers(conn, include_deleted=True) == []
        finally:
            conn.close()


class TestListApiKeys:
    def _seed_customers_and_keys(self, conn: sqlite3.Connection) -> dict[str, str]:
        """Populate two customers, assorted keys. Returns id map."""
        c_helena = _seed_customer_with_time(
            conn, name="Helena", registered_at="2026-04-10T10:00:00Z"
        )
        c_bruno = _seed_customer_with_time(
            conn, name="Bruno", registered_at="2026-04-11T10:00:00Z"
        )
        ids: dict[str, str] = {"helena": c_helena, "bruno": c_bruno}
        ids["k_active_manual"] = _seed_api_key(
            conn,
            customer_id=c_helena,
            key_hash="a" * 64,
            key_prefix="ACTMAN01",
            status="active",
            billing_mode="manual",
            paid_until=None,
            created_at="2026-04-12T10:00:00Z",
        )
        ids["k_suspended"] = _seed_api_key(
            conn,
            customer_id=c_helena,
            key_hash="b" * 64,
            key_prefix="SUSMAN02",
            status="suspended",
            billing_mode="manual",
            paid_until="2026-04-01",
            created_at="2026-04-13T10:00:00Z",
        )
        ids["k_revoked"] = _seed_api_key(
            conn,
            customer_id=c_bruno,
            key_hash="c" * 64,
            key_prefix="REVMAN03",
            status="revoked",
            billing_mode="manual",
            paid_until="2026-05-01",
            created_at="2026-04-14T10:00:00Z",
        )
        ids["k_complimentary"] = _seed_api_key(
            conn,
            customer_id=c_bruno,
            key_hash="d" * 64,
            key_prefix="COMPKY04",
            status="active",
            billing_mode="complimentary",
            price_monthly=0.0,
            paid_until=None,
            created_at="2026-04-15T10:00:00Z",
        )
        return ids

    def test_no_filters_returns_all_sorted(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            ids = self._seed_customers_and_keys(conn)
            rows = list_api_keys(conn)
            assert [r.id for r in rows] == [
                ids["k_active_manual"],
                ids["k_suspended"],
                ids["k_revoked"],
                ids["k_complimentary"],
            ]
        finally:
            conn.close()

    @pytest.mark.parametrize(
        "status,expected_key",
        [
            ("active", {"k_active_manual", "k_complimentary"}),
            ("suspended", {"k_suspended"}),
            ("revoked", {"k_revoked"}),
        ],
    )
    def test_filter_by_status(
        self, tmp_path: Path, status: CustomerStatus, expected_key: set[str]
    ) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            ids = self._seed_customers_and_keys(conn)
            rows = list_api_keys(conn, status=status)
            assert {r.id for r in rows} == {ids[k] for k in expected_key}
        finally:
            conn.close()

    @pytest.mark.parametrize(
        "billing_mode,expected_count",
        [
            ("manual", 3),
            ("complimentary", 1),
        ],
    )
    def test_filter_by_billing_mode(
        self, tmp_path: Path, billing_mode: BillingMode, expected_count: int
    ) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            self._seed_customers_and_keys(conn)
            rows = list_api_keys(conn, billing_mode=billing_mode)
            assert len(rows) == expected_count
        finally:
            conn.close()

    def test_filter_by_customer(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            ids = self._seed_customers_and_keys(conn)
            rows = list_api_keys(conn, customer_id=ids["helena"])
            assert {r.id for r in rows} == {
                ids["k_active_manual"],
                ids["k_suspended"],
            }
        finally:
            conn.close()

    def test_filter_by_paid_until_lte_includes_nulls(self, tmp_path: Path) -> None:
        """AC6 semantics — NULL paid_until is treated as eligible (unpaid)."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            ids = self._seed_customers_and_keys(conn)
            rows = list_api_keys(conn, paid_until_lte="2026-04-15")
            # k_active_manual has paid_until=None (included), k_suspended
            # paid_until=2026-04-01 (included), k_complimentary paid_until=None
            # (included); k_revoked paid_until=2026-05-01 is excluded.
            returned = {r.id for r in rows}
            assert ids["k_revoked"] not in returned
            assert ids["k_active_manual"] in returned
            assert ids["k_suspended"] in returned
            assert ids["k_complimentary"] in returned
        finally:
            conn.close()

    def test_filter_composition(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            ids = self._seed_customers_and_keys(conn)
            rows = list_api_keys(
                conn,
                status="active",
                billing_mode="manual",
                paid_until_lte="2026-04-15",
            )
            # Only k_active_manual matches active+manual+paid_until_lte.
            assert {r.id for r in rows} == {ids["k_active_manual"]}
        finally:
            conn.close()

    def test_joined_customer_name_is_correct(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            ids = self._seed_customers_and_keys(conn)
            rows = list_api_keys(conn)
            by_id = {r.id: r.customer_name for r in rows}
            assert by_id[ids["k_active_manual"]] == "Helena"
            assert by_id[ids["k_complimentary"]] == "Bruno"
        finally:
            conn.close()


class TestIsFirstRun:
    def test_true_on_empty_db(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            assert is_first_run(conn) is True
        finally:
            conn.close()

    def test_false_when_customer_exists(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            _seed_customer(conn)
            assert is_first_run(conn) is False
        finally:
            conn.close()

    def test_false_when_only_tombstones(self, tmp_path: Path) -> None:
        """Even after hard-delete, the DB has been used — hint is suppressed."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-15T00:00:00Z", cid),
            )
            conn.commit()
            assert is_first_run(conn) is False
        finally:
            conn.close()


class TestIsFirstRunForKeys:
    """AC7: list-keys fires its hint whenever api_key is empty, even if
    customers already exist. Distinct from is_first_run which also
    requires an empty customer table."""

    def test_true_on_empty_db(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            assert is_first_run_for_keys(conn) is True
        finally:
            conn.close()

    def test_true_when_customers_exist_but_no_keys(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            _seed_customer(conn)
            assert is_first_run_for_keys(conn) is True
        finally:
            conn.close()

    def test_false_when_api_key_rows_exist(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(conn, customer_id=cid, key_hash="a" * 64)
            assert is_first_run_for_keys(conn) is False
        finally:
            conn.close()


class TestCountTombstones:
    def test_returns_zero_on_fresh_db(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            assert count_tombstones(conn) == 0
        finally:
            conn.close()

    def test_counts_only_tombstoned_rows(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            alive = _seed_customer_with_time(
                conn, name="Alive", registered_at="2026-04-10T10:00:00Z"
            )
            dead = _seed_customer_with_time(
                conn, name="Dead", registered_at="2026-04-11T10:00:00Z"
            )
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-15T00:00:00Z", dead),
            )
            conn.commit()
            assert count_tombstones(conn) == 1
            _ = alive  # silence unused var
        finally:
            conn.close()


class TestListCommandsDoNotWrite:
    """AC9 regression guard — listings never mutate the DB."""

    def test_no_writes_across_all_helpers(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(conn, customer_id=cid, key_hash="f" * 64)

            before = {
                "customer": _count_rows(conn, "customer"),
                "api_key": _count_rows(conn, "api_key"),
                "audit_log": _count_rows(conn, "audit_log"),
            }

            list_customers(conn, include_deleted=False)
            list_customers(conn, include_deleted=True)
            list_api_keys(conn)
            list_api_keys(conn, status="active")
            list_api_keys(conn, billing_mode="manual")
            list_api_keys(conn, customer_id=cid)
            list_api_keys(conn, paid_until_lte="2026-04-15")
            is_first_run(conn)
            is_first_run_for_keys(conn)
            count_tombstones(conn)

            after = {
                "customer": _count_rows(conn, "customer"),
                "api_key": _count_rows(conn, "api_key"),
                "audit_log": _count_rows(conn, "audit_log"),
            }
            assert before == after
        finally:
            conn.close()
