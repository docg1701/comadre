"""Tests for comadre.keys.db — connection, migrations, insert."""

from __future__ import annotations

import sqlite3
import stat
from datetime import UTC, date, datetime
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
    get_customer_detail,
    get_key_detail,
    get_key_detail_by_id,
    insert_api_key,
    insert_customer,
    is_first_run,
    is_first_run_for_keys,
    list_api_keys,
    list_audit_events,
    list_customers,
    resolve_show_target,
    update_customer,
)
from comadre.keys.models import (
    ApiKeyRecord,
    BillingMode,
    CustomerRecord,
    CustomerStatus,
    KeyDetailRow,
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


# ---------------------------------------------------------------------------
# Story 1.4 — detail + audit + resolver helpers
# ---------------------------------------------------------------------------

_FROZEN_TODAY = date(2026, 4, 16)


def _insert_audit(
    conn: sqlite3.Connection,
    *,
    occurred_at: str,
    actor: str,
    action: str,
    target_id: str,
    target_type: str = "api_key",
    details_json: str | None = None,
) -> int:
    """Seed a single ``audit_log`` row directly. Returns the autoincrement id."""
    cursor = conn.execute(
        "INSERT INTO audit_log "
        "(occurred_at, actor, action, target_type, target_id, details_json) "
        "VALUES (?, ?, ?, ?, ?, ?)",
        (occurred_at, actor, action, target_type, target_id, details_json),
    )
    conn.commit()
    return int(cursor.lastrowid or 0)


class TestGetCustomerDetail:
    def test_returns_row_with_key_count(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(conn, customer_id=cid, key_hash="a" * 64)
            _seed_api_key(
                conn, customer_id=cid, key_hash="b" * 64, key_prefix="KEY2AAAA"
            )
            detail = get_customer_detail(conn, cid)
            assert detail is not None
            assert detail.id == cid
            assert detail.name == "Helena Ribeiro"
            assert detail.email == "helena@clinica.com"
            assert detail.tax_id_kind == "cpf"
            assert detail.key_count == 2
            assert detail.registered_at == "2026-04-16T12:00:00Z"
            assert detail.notes == ""
        finally:
            conn.close()

    def test_returns_zero_key_count_via_left_join(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            detail = get_customer_detail(conn, cid)
            assert detail is not None
            assert detail.key_count == 0
        finally:
            conn.close()

    def test_returns_none_on_missing(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            assert get_customer_detail(conn, "cust_missing") is None
        finally:
            conn.close()

    def test_treats_tombstone_as_missing(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-20T00:00:00Z", cid),
            )
            conn.commit()
            assert get_customer_detail(conn, cid) is None
        finally:
            conn.close()


class TestGetKeyDetail:
    def test_single_row_returns_dataclass(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                key_prefix="EVb4xk8B",
                created_at="2026-04-06T12:00:00Z",
            )
            result = get_key_detail(conn, "EVb4xk8B", today=_FROZEN_TODAY)
            assert isinstance(result, KeyDetailRow)
            assert result.key_prefix == "EVb4xk8B"
            assert result.customer_id == cid
            assert result.customer_name == "Helena Ribeiro"
            assert result.status == "active"
            assert result.billing_mode == "manual"
            assert result.rate_limit_rpm == 60
            assert result.price_monthly == 149.0
            assert result.paid_until is None
            assert result.created_at == "2026-04-06T12:00:00Z"
            assert result.last_used_at is None
            assert result.age_days == 10
            assert result.notes == ""
        finally:
            conn.close()

    def test_none_when_missing(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            assert get_key_detail(conn, "NOPE0000", today=_FROZEN_TODAY) is None
        finally:
            conn.close()

    def test_ambiguous_returns_list(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                key_prefix="COLLIDE1",
            )
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="b" * 64,
                key_prefix="COLLIDE1",
            )
            result = get_key_detail(conn, "COLLIDE1", today=_FROZEN_TODAY)
            assert isinstance(result, list)
            assert len(result) == 2
            assert all(isinstance(r, KeyDetailRow) for r in result)
        finally:
            conn.close()

    def test_age_zero_renders_today(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                key_prefix="TODAY001",
                created_at="2026-04-16T09:00:00Z",
            )
            result = get_key_detail(conn, "TODAY001", today=_FROZEN_TODAY)
            assert isinstance(result, KeyDetailRow)
            assert result.age_days == 0
        finally:
            conn.close()


class TestGetKeyDetailById:
    def test_happy_path(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            kid = _seed_api_key(
                conn, customer_id=cid, key_hash="a" * 64, key_prefix="FULLKEY1"
            )
            result = get_key_detail_by_id(conn, kid, today=_FROZEN_TODAY)
            assert result is not None
            assert result.id == kid
            assert result.customer_name == "Helena Ribeiro"
        finally:
            conn.close()

    def test_none_when_missing(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            assert (
                get_key_detail_by_id(conn, "key_missing", today=_FROZEN_TODAY) is None
            )
        finally:
            conn.close()


def _seed_customer_raw(conn: sqlite3.Connection) -> str:
    """Seed a customer via raw INSERT (no audit row). Use for audit-scoped tests."""
    return _seed_customer_with_time(
        conn, name="Helena Ribeiro", registered_at="2026-04-16T12:00:00Z"
    )


class TestListAuditEvents:
    def test_newest_first_within_limit(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_raw(conn)
            _insert_audit(
                conn,
                occurred_at="2026-04-10T10:00:00Z",
                actor="cli:a",
                action="one",
                target_type="customer",
                target_id=cid,
            )
            _insert_audit(
                conn,
                occurred_at="2026-04-12T10:00:00Z",
                actor="cli:a",
                action="two",
                target_type="customer",
                target_id=cid,
            )
            _insert_audit(
                conn,
                occurred_at="2026-04-14T10:00:00Z",
                actor="cli:a",
                action="three",
                target_type="customer",
                target_id=cid,
            )
            events = list_audit_events(conn, [cid], limit=10)
            assert [e.action for e in events] == ["three", "two", "one"]
        finally:
            conn.close()

    def test_limit_truncates(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_raw(conn)
            for i in range(5):
                _insert_audit(
                    conn,
                    occurred_at=f"2026-04-1{i}T10:00:00Z",
                    actor="cli:a",
                    action=f"act_{i}",
                    target_type="customer",
                    target_id=cid,
                )
            events = list_audit_events(conn, [cid], limit=3)
            assert len(events) == 3
            assert [e.action for e in events] == ["act_4", "act_3", "act_2"]
        finally:
            conn.close()

    def test_filter_by_target_ids(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid_a = _seed_customer_raw(conn)
            conn.execute(
                "INSERT INTO customer ("
                "id, name, email, tax_id_kind, tax_id_encrypted, notes, "
                "registered_at, deleted_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    "cust_01otherxxxxxxxxxxxxxxxxxx",
                    "Other",
                    "other@x.com",
                    "cpf",
                    b"x",
                    "",
                    "2026-04-11T10:00:00Z",
                    None,
                ),
            )
            conn.commit()
            cid_b = "cust_01otherxxxxxxxxxxxxxxxxxx"
            _insert_audit(
                conn,
                occurred_at="2026-04-10T10:00:00Z",
                actor="cli:a",
                action="for_a",
                target_type="customer",
                target_id=cid_a,
            )
            _insert_audit(
                conn,
                occurred_at="2026-04-11T10:00:00Z",
                actor="cli:a",
                action="for_b",
                target_type="customer",
                target_id=cid_b,
            )
            events = list_audit_events(conn, [cid_a], limit=10)
            assert [e.action for e in events] == ["for_a"]
        finally:
            conn.close()

    def test_customer_plus_keys_union(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_raw(conn)
            kid = _seed_api_key(conn, customer_id=cid, key_hash="a" * 64)
            _insert_audit(
                conn,
                occurred_at="2026-04-10T10:00:00Z",
                actor="cli:a",
                action="create_customer",
                target_type="customer",
                target_id=cid,
            )
            _insert_audit(
                conn,
                occurred_at="2026-04-11T10:00:00Z",
                actor="cli:a",
                action="issue_key",
                target_type="api_key",
                target_id=kid,
            )
            _insert_audit(
                conn,
                occurred_at="2026-04-12T10:00:00Z",
                actor="cli:a",
                action="update_key",
                target_type="api_key",
                target_id=kid,
            )
            events = list_audit_events(conn, [cid, kid], limit=10)
            assert [e.action for e in events] == [
                "update_key",
                "issue_key",
                "create_customer",
            ]
        finally:
            conn.close()

    def test_tiebreak_by_id_desc_on_identical_timestamp(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_raw(conn)
            ts = "2026-04-10T10:00:00Z"
            id_a = _insert_audit(
                conn,
                occurred_at=ts,
                actor="cli:a",
                action="first",
                target_type="customer",
                target_id=cid,
            )
            id_b = _insert_audit(
                conn,
                occurred_at=ts,
                actor="cli:a",
                action="second",
                target_type="customer",
                target_id=cid,
            )
            events = list_audit_events(conn, [cid], limit=10)
            assert [e.id for e in events] == [id_b, id_a]
        finally:
            conn.close()

    def test_limit_validation_zero_raises(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            with pytest.raises(ValueError, match="1 and 1000"):
                list_audit_events(conn, ["cust_x"], limit=0)
        finally:
            conn.close()

    def test_limit_validation_too_large_raises(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            with pytest.raises(ValueError, match="1 and 1000"):
                list_audit_events(conn, ["cust_x"], limit=1001)
        finally:
            conn.close()

    def test_empty_target_ids_returns_empty(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            assert list_audit_events(conn, [], limit=10) == []
        finally:
            conn.close()

    def test_details_json_roundtrip(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_raw(conn)
            _insert_audit(
                conn,
                occurred_at="2026-04-10T10:00:00Z",
                actor="cli:a",
                action="create_customer",
                target_type="customer",
                target_id=cid,
                details_json='{"tax_id_kind": "cpf"}',
            )
            _insert_audit(
                conn,
                occurred_at="2026-04-11T10:00:00Z",
                actor="cli:a",
                action="no_details",
                target_type="customer",
                target_id=cid,
                details_json=None,
            )
            events = list_audit_events(conn, [cid], limit=10)
            assert events[0].details_json is None
            assert events[1].details_json == '{"tax_id_kind": "cpf"}'
        finally:
            conn.close()


class TestResolveShowTarget:
    def test_customer_happy_path(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            result = resolve_show_target(conn, cid, today=_FROZEN_TODAY)
            assert result.kind == "customer"
            assert result.value is not None
            assert getattr(result.value, "id", None) == cid
        finally:
            conn.close()

    def test_customer_not_found(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            result = resolve_show_target(
                conn,
                "cust_01missingxxxxxxxxxxxxxxxxx",
                today=_FROZEN_TODAY,
            )
            assert result.kind == "not_found"
            assert result.value is None
        finally:
            conn.close()

    def test_customer_tombstone_is_not_found(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-20T00:00:00Z", cid),
            )
            conn.commit()
            result = resolve_show_target(conn, cid, today=_FROZEN_TODAY)
            assert result.kind == "not_found"
        finally:
            conn.close()

    def test_key_prefix_happy_path(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(
                conn, customer_id=cid, key_hash="a" * 64, key_prefix="EVb4xk8B"
            )
            result = resolve_show_target(conn, "EVb4xk8B", today=_FROZEN_TODAY)
            assert result.kind == "key_single"
            assert isinstance(result.value, KeyDetailRow)
            assert result.value.key_prefix == "EVb4xk8B"
        finally:
            conn.close()

    def test_key_prefix_not_found(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            result = resolve_show_target(conn, "NOPE0000", today=_FROZEN_TODAY)
            assert result.kind == "not_found"
        finally:
            conn.close()

    def test_key_id_happy_path(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            kid = _seed_api_key(
                conn, customer_id=cid, key_hash="a" * 64, key_prefix="BYIDKEY1"
            )
            result = resolve_show_target(conn, kid, today=_FROZEN_TODAY)
            assert result.kind == "key_single"
            assert isinstance(result.value, KeyDetailRow)
            assert result.value.id == kid
        finally:
            conn.close()

    def test_key_id_not_found(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            result = resolve_show_target(
                conn,
                "key_01missingxxxxxxxxxxxxxxxxx",
                today=_FROZEN_TODAY,
            )
            assert result.kind == "not_found"
        finally:
            conn.close()

    def test_cmdr_live_prefix_convenience(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                key_prefix="EVb4xk8B",
            )
            # Simulated full plaintext: cmdr_live_<53 chars>
            fake_plaintext = "cmdr_live_EVb4xk8Bzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzzz"
            result = resolve_show_target(conn, fake_plaintext, today=_FROZEN_TODAY)
            assert result.kind == "key_single"
            assert isinstance(result.value, KeyDetailRow)
            assert result.value.key_prefix == "EVb4xk8B"
        finally:
            conn.close()

    def test_ambiguous_prefix(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(
                conn, customer_id=cid, key_hash="a" * 64, key_prefix="COLLIDE1"
            )
            _seed_api_key(
                conn, customer_id=cid, key_hash="b" * 64, key_prefix="COLLIDE1"
            )
            result = resolve_show_target(conn, "COLLIDE1", today=_FROZEN_TODAY)
            assert result.kind == "key_ambiguous"
            assert isinstance(result.value, list)
            assert len(result.value) == 2
        finally:
            conn.close()


class TestShowHelpersDoNotWrite:
    """AC9 regression guard — show-path helpers never mutate the DB."""

    def test_no_writes_across_show_helpers(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            kid = _seed_api_key(
                conn, customer_id=cid, key_hash="a" * 64, key_prefix="WRT00000"
            )
            _insert_audit(
                conn,
                occurred_at="2026-04-10T10:00:00Z",
                actor="cli:a",
                action="issue_key",
                target_type="api_key",
                target_id=kid,
            )
            before = {
                "customer": _count_rows(conn, "customer"),
                "api_key": _count_rows(conn, "api_key"),
                "audit_log": _count_rows(conn, "audit_log"),
            }

            get_customer_detail(conn, cid)
            get_customer_detail(conn, "cust_missing")
            get_key_detail(conn, "WRT00000", today=_FROZEN_TODAY)
            get_key_detail(conn, "NOPE0000", today=_FROZEN_TODAY)
            get_key_detail_by_id(conn, kid, today=_FROZEN_TODAY)
            list_audit_events(conn, [cid, kid], limit=10)
            resolve_show_target(conn, cid, today=_FROZEN_TODAY)
            resolve_show_target(conn, "WRT00000", today=_FROZEN_TODAY)
            resolve_show_target(conn, kid, today=_FROZEN_TODAY)
            resolve_show_target(
                conn, "cust_01nopexxxxxxxxxxxxxxxxxxxx", today=_FROZEN_TODAY
            )

            after = {
                "customer": _count_rows(conn, "customer"),
                "api_key": _count_rows(conn, "api_key"),
                "audit_log": _count_rows(conn, "audit_log"),
            }
            assert before == after
        finally:
            conn.close()


_UPDATE_FROZEN_TODAY = date(2026, 4, 20)


def _seed_customer_with_notes(
    conn: sqlite3.Connection,
    *,
    email: str = "helena@clinica.com",
    notes: str = "",
) -> str:
    """Seed a customer with a specific email/notes via ``insert_customer``."""
    cid = generate_customer_id()
    insert_customer(
        conn,
        CustomerRecord(
            id=cid,
            name="Helena Ribeiro",
            email=email,
            tax_id_kind="cpf",
            tax_id_encrypted=b"gAAAAA-ciphertext-blob",
            notes=notes,
            registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
            deleted_at=None,
        ),
        actor="cli:tester",
    )
    return cid


class TestUpdateCustomer:
    """Story 1.5 — unit coverage for the ``update_customer`` helper."""

    def test_email_only_changes_email_column(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_with_notes(conn, notes="seed notes")

            result = update_customer(
                conn,
                cid,
                new_email="new@example.com",
                add_note=None,
                actor="cli:tester",
                today=_UPDATE_FROZEN_TODAY,
            )

            assert result is not None
            assert result.updated_fields == ("email",)
            row = conn.execute(
                "SELECT email, notes FROM customer WHERE id = ?", (cid,)
            ).fetchone()
            assert row["email"] == "new@example.com"
            assert row["notes"] == "seed notes"

            audit = conn.execute(
                "SELECT action, target_type, target_id, details_json "
                "FROM audit_log WHERE action = 'update_customer'"
            ).fetchall()
            assert len(audit) == 1
            assert audit[0]["action"] == "update_customer"
            assert audit[0]["target_type"] == "customer"
            assert audit[0]["target_id"] == cid
            assert audit[0]["details_json"] == '{"fields": ["email"]}'
        finally:
            conn.close()

    def test_note_only_changes_notes_column(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_with_notes(conn, notes="seed")

            result = update_customer(
                conn,
                cid,
                new_email=None,
                add_note="new note",
                actor="cli:tester",
                today=_UPDATE_FROZEN_TODAY,
            )

            assert result is not None
            assert result.updated_fields == ("notes",)
            row = conn.execute(
                "SELECT email, notes FROM customer WHERE id = ?", (cid,)
            ).fetchone()
            assert row["email"] == "helena@clinica.com"
            assert row["notes"] == "seed\n[2026-04-20] new note"

            audit = conn.execute(
                "SELECT details_json FROM audit_log WHERE action = 'update_customer'"
            ).fetchone()
            assert audit["details_json"] == '{"fields": ["notes"]}'
        finally:
            conn.close()

    def test_note_on_empty_existing_no_leading_newline(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_with_notes(conn, notes="")

            update_customer(
                conn,
                cid,
                new_email=None,
                add_note="first",
                actor="cli:tester",
                today=_UPDATE_FROZEN_TODAY,
            )

            row = conn.execute(
                "SELECT notes FROM customer WHERE id = ?", (cid,)
            ).fetchone()
            assert row["notes"] == "[2026-04-20] first"
        finally:
            conn.close()

    def test_note_appends_second_entry(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_with_notes(conn, notes="")

            update_customer(
                conn,
                cid,
                new_email=None,
                add_note="first",
                actor="cli:tester",
                today=date(2026, 4, 20),
            )
            update_customer(
                conn,
                cid,
                new_email=None,
                add_note="second",
                actor="cli:tester",
                today=date(2026, 5, 12),
            )

            row = conn.execute(
                "SELECT notes FROM customer WHERE id = ?", (cid,)
            ).fetchone()
            assert row["notes"] == ("[2026-04-20] first\n[2026-05-12] second")
            audit_count = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'update_customer'"
            ).fetchone()[0]
            assert audit_count == 2
        finally:
            conn.close()

    def test_both_email_and_note_in_one_txn(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_with_notes(conn, notes="seed")

            result = update_customer(
                conn,
                cid,
                new_email="both@example.com",
                add_note="bumped",
                actor="cli:tester",
                today=_UPDATE_FROZEN_TODAY,
            )

            assert result is not None
            assert result.updated_fields == ("email", "notes")
            row = conn.execute(
                "SELECT email, notes FROM customer WHERE id = ?", (cid,)
            ).fetchone()
            assert row["email"] == "both@example.com"
            assert row["notes"] == "seed\n[2026-04-20] bumped"

            audit = conn.execute(
                "SELECT details_json FROM audit_log WHERE action = 'update_customer'"
            ).fetchall()
            assert len(audit) == 1
            assert audit[0]["details_json"] == '{"fields": ["email", "notes"]}'
        finally:
            conn.close()

    def test_missing_returns_none(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            result = update_customer(
                conn,
                "cust_01nonexistent0000000000000",
                new_email="x@e.com",
                add_note=None,
                actor="cli:tester",
                today=_UPDATE_FROZEN_TODAY,
            )
            assert result is None
            audit_count = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'update_customer'"
            ).fetchone()[0]
            assert audit_count == 0
        finally:
            conn.close()

    def test_tombstone_returns_none(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_with_notes(conn, notes="pre-tombstone")
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-18T00:00:00Z", cid),
            )
            conn.commit()

            result = update_customer(
                conn,
                cid,
                new_email="x@e.com",
                add_note="x",
                actor="cli:tester",
                today=_UPDATE_FROZEN_TODAY,
            )
            assert result is None

            row = conn.execute(
                "SELECT email, notes, deleted_at FROM customer WHERE id = ?",
                (cid,),
            ).fetchone()
            assert row["email"] == "helena@clinica.com"
            assert row["notes"] == "pre-tombstone"
            assert row["deleted_at"] == "2026-04-18T00:00:00Z"

            audit_count = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'update_customer'"
            ).fetchone()[0]
            assert audit_count == 0
        finally:
            conn.close()

    def test_rolls_back_when_audit_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_with_notes(conn, notes="seed")

            import comadre.keys.audit as audit_module

            def _boom(*_args: object, **_kw: object) -> None:
                raise sqlite3.IntegrityError("forced audit failure")

            monkeypatch.setattr(audit_module, "log_event", _boom)

            with pytest.raises(sqlite3.IntegrityError):
                update_customer(
                    conn,
                    cid,
                    new_email="rollback@example.com",
                    add_note="rollback",
                    actor="cli:tester",
                    today=_UPDATE_FROZEN_TODAY,
                )

            row = conn.execute(
                "SELECT email, notes FROM customer WHERE id = ?", (cid,)
            ).fetchone()
            assert row["email"] == "helena@clinica.com"
            assert row["notes"] == "seed"

            audit_count = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'update_customer'"
            ).fetchone()[0]
            assert audit_count == 0
        finally:
            conn.close()

    def test_same_email_value_still_audits(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_with_notes(conn, email="a@b.com", notes="seed")

            result = update_customer(
                conn,
                cid,
                new_email="a@b.com",
                add_note=None,
                actor="cli:tester",
                today=_UPDATE_FROZEN_TODAY,
            )

            assert result is not None
            assert result.updated_fields == ("email",)
            audit = conn.execute(
                "SELECT details_json FROM audit_log WHERE action = 'update_customer'"
            ).fetchone()
            assert audit["details_json"] == '{"fields": ["email"]}'
        finally:
            conn.close()

    def test_audit_details_does_not_leak_values(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_with_notes(conn, notes="seed")

            secret_email = "secret-operator-email@novaclinica.com"
            secret_note = "sensitive-operator-note"
            update_customer(
                conn,
                cid,
                new_email=secret_email,
                add_note=secret_note,
                actor="cli:tester",
                today=_UPDATE_FROZEN_TODAY,
            )

            row = conn.execute(
                "SELECT actor, action, target_type, target_id, details_json "
                "FROM audit_log WHERE action = 'update_customer'"
            ).fetchone()
            joined = " | ".join(
                str(row[col])
                for col in (
                    "actor",
                    "action",
                    "target_type",
                    "target_id",
                    "details_json",
                )
            )
            assert secret_email not in joined
            assert secret_note not in joined
            assert row["details_json"] == '{"fields": ["email", "notes"]}'
        finally:
            conn.close()

    def test_today_uses_caller_supplied_value(self, tmp_path: Path) -> None:
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer_with_notes(conn, notes="")

            update_customer(
                conn,
                cid,
                new_email=None,
                add_note="future",
                actor="cli:tester",
                today=date(2030, 1, 1),
            )

            row = conn.execute(
                "SELECT notes FROM customer WHERE id = ?", (cid,)
            ).fetchone()
            assert row["notes"] == "[2030-01-01] future"
        finally:
            conn.close()
