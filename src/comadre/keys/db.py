"""SQLite connection management and CRUD for the key registry.

All queries use parameterized `?` placeholders — never f-strings or
`.format()`. WAL journal mode and `foreign_keys=ON` are enabled at connect
time. File permissions (0600) and parent-directory permissions (0700) are
enforced on creation.

Migration sentinel: a `schema_version` table records the highest applied
version. The runner checks `sqlite_master` first (no `CREATE TABLE IF NOT
EXISTS` in the v001 SQL — that SQL runs only on fresh DBs).
"""

from __future__ import annotations

import contextlib
import importlib.resources
import sqlite3
import stat
from datetime import UTC, datetime
from pathlib import Path
from typing import cast

from ulid import ULID

from comadre.keys.models import (
    ApiKeyListRow,
    ApiKeyRecord,
    BillingMode,
    CustomerListRow,
    CustomerRecord,
    CustomerStatus,
    TaxIdKind,
)

_SCHEMA_VERSION = 1


def _utcnow_iso() -> str:
    """Return current UTC time as ISO 8601 seconds (Z suffix, no microseconds)."""
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def generate_customer_id() -> str:
    """Return a fresh `cust_<26-char-lowercase-ULID>` identifier."""
    return f"cust_{str(ULID()).lower()}"


def generate_key_id() -> str:
    """Return a fresh `key_<26-char-lowercase-ULID>` identifier."""
    return f"key_{str(ULID()).lower()}"


def _chmod_0600(target: Path) -> None:
    """Set mode 0600 on `target` if it exists and differs."""
    if not target.exists():
        return
    if stat.S_IMODE(target.stat().st_mode) != 0o600:
        target.chmod(0o600)


def get_connection(path: str | Path) -> sqlite3.Connection:
    """Open a SQLite connection with WAL + foreign_keys enforced.

    - Parent directory is created with mode 0700 (operator-only).
    - File is chmod'd to 0600 once SQLite has created it. WAL sidecars
      (`*.db-wal`, `*.db-shm`) are chmod'd 0600 as well — they contain the
      same unflushed ciphertext and audit data as the main file.
    - `busy_timeout=5000` tolerates concurrent CLI invocations holding the
      write lock instead of failing immediately with SQLITE_BUSY.
    - `row_factory = sqlite3.Row` so callers can use name-based access.
    """
    db_path = Path(path)
    parent = db_path.parent
    if not parent.exists():
        parent.mkdir(mode=0o700, parents=True, exist_ok=True)
    else:
        # Best-effort tightening on an existing parent that may have been
        # created with broader defaults. Ignored on bind mounts / shared dirs.
        with contextlib.suppress(PermissionError):
            parent.chmod(0o700)

    conn = sqlite3.connect(db_path, detect_types=sqlite3.PARSE_DECLTYPES)
    try:
        conn.execute("PRAGMA busy_timeout = 5000")
        conn.execute("PRAGMA journal_mode = WAL")
        conn.execute("PRAGMA foreign_keys = ON")
        conn.row_factory = sqlite3.Row
        _chmod_0600(db_path)
        _chmod_0600(db_path.with_name(db_path.name + "-wal"))
        _chmod_0600(db_path.with_name(db_path.name + "-shm"))
    except Exception:
        conn.close()
        raise
    return conn


def _apply_migrations(conn: sqlite3.Connection) -> None:
    """Apply pending migrations. Idempotent."""
    cursor = conn.execute(
        "SELECT name FROM sqlite_master "
        "WHERE type = 'table' AND name = 'schema_version'"
    )
    has_version_table = cursor.fetchone() is not None
    current: int = 0
    if has_version_table:
        row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        # SELECT MAX on empty table returns (None,)
        current = int(row[0]) if row and row[0] is not None else 0

    if current > _SCHEMA_VERSION:
        raise RuntimeError(
            f"Key registry schema version {current} is newer than this binary "
            f"supports (max {_SCHEMA_VERSION}). Upgrade comadre before running."
        )
    if current == _SCHEMA_VERSION:
        return

    sql = (
        importlib.resources.files("comadre.keys.migrations")
        .joinpath("v001_initial.sql")
        .read_text(encoding="utf-8")
    )
    with conn:
        # executescript handles multi-statement DDL safely, including statements
        # whose bodies contain semicolons (triggers, CHECK clauses with strings).
        conn.executescript(sql)
        conn.execute(
            "INSERT INTO schema_version (version, applied_at) VALUES (?, ?)",
            (_SCHEMA_VERSION, _utcnow_iso()),
        )


def insert_customer(
    conn: sqlite3.Connection,
    record: CustomerRecord,
    *,
    actor: str,
) -> None:
    """Insert a customer and its audit row in a single transaction.

    Callers must NOT open a surrounding `with conn:` — this function opens
    the transaction itself so the customer and audit writes either both
    commit or both roll back.
    """
    from comadre.keys.audit import log_event

    registered_at_iso = record.registered_at.astimezone(UTC).strftime(
        "%Y-%m-%dT%H:%M:%SZ"
    )
    deleted_at_iso = (
        record.deleted_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if record.deleted_at is not None
        else None
    )
    with conn:
        conn.execute(
            "INSERT INTO customer ("
            "id, name, email, tax_id_kind, tax_id_encrypted, notes, "
            "registered_at, deleted_at"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.name,
                record.email,
                record.tax_id_kind,
                record.tax_id_encrypted,
                record.notes,
                registered_at_iso,
                deleted_at_iso,
            ),
        )
        log_event(
            conn,
            actor=actor,
            action="create_customer",
            target_type="customer",
            target_id=record.id,
            details={"tax_id_kind": record.tax_id_kind},
        )


def get_customer(
    conn: sqlite3.Connection,
    customer_id: str,
) -> CustomerRecord | None:
    """Return the customer row matching `customer_id`, or None.

    Tombstoned customers (`deleted_at IS NOT NULL`) are treated as missing
    — this matches Story 1.2 AC3 (LGPD tombstone is opaque to the CLI).
    """
    row = conn.execute(
        "SELECT id, name, email, tax_id_kind, tax_id_encrypted, notes, "
        "registered_at, deleted_at FROM customer "
        "WHERE id = ? AND deleted_at IS NULL",
        (customer_id,),
    ).fetchone()
    if row is None:
        return None
    return CustomerRecord(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        tax_id_kind=row["tax_id_kind"],
        tax_id_encrypted=bytes(row["tax_id_encrypted"]),
        notes=row["notes"] or "",
        registered_at=datetime.fromisoformat(
            row["registered_at"].replace("Z", "+00:00")
        ),
        deleted_at=None,
    )


def list_customers(
    conn: sqlite3.Connection,
    *,
    include_deleted: bool,
) -> list[CustomerListRow]:
    """Return customer rows sorted by ``registered_at ASC``.

    Tombstoned customers (``deleted_at IS NOT NULL``) are filtered out
    unless ``include_deleted`` is True. The ``key_count`` column is
    computed via a single ``LEFT JOIN api_key`` — no N+1 per-row counts.
    """
    cursor = conn.execute(
        "SELECT "
        "c.id, c.name, c.email, c.tax_id_kind, c.notes, "
        "c.registered_at, c.deleted_at, "
        "COUNT(k.id) AS key_count "
        "FROM customer AS c "
        "LEFT JOIN api_key AS k ON k.customer_id = c.id "
        "WHERE (? OR c.deleted_at IS NULL) "
        "GROUP BY c.id "
        "ORDER BY c.registered_at ASC",
        (1 if include_deleted else 0,),
    )
    rows: list[CustomerListRow] = []
    for row in cursor:
        rows.append(
            CustomerListRow(
                id=row["id"],
                name=row["name"],
                email=row["email"],
                tax_id_kind=cast(TaxIdKind, row["tax_id_kind"]),
                key_count=int(row["key_count"]),
                registered_at=row["registered_at"],
                deleted_at=row["deleted_at"],
                notes=row["notes"] or "",
            )
        )
    return rows


def list_api_keys(
    conn: sqlite3.Connection,
    *,
    status: CustomerStatus | None = None,
    billing_mode: BillingMode | None = None,
    customer_id: str | None = None,
    paid_until_lte: str | None = None,
) -> list[ApiKeyListRow]:
    """Return api_key rows with optional filters, sorted by ``created_at ASC``.

    Each non-None filter contributes one ``?`` placeholder to the WHERE
    clause; the predicate literals themselves are hard-coded so operator
    input never lands in SQL text. The ``paid_until`` filter matches both
    NULL and ``paid_until <= ?`` rows (NULL treated as "not yet billed"
    so the operator's "who owes me?" query catches trial-window keys).
    """
    predicates: list[str] = []
    params: list[object] = []
    if status is not None:
        predicates.append("k.status = ?")
        params.append(status)
    if billing_mode is not None:
        predicates.append("k.billing_mode = ?")
        params.append(billing_mode)
    if customer_id is not None:
        predicates.append("k.customer_id = ?")
        params.append(customer_id)
    if paid_until_lte is not None:
        predicates.append("(k.paid_until IS NULL OR k.paid_until <= ?)")
        params.append(paid_until_lte)
    where_clause = ("WHERE " + " AND ".join(predicates)) if predicates else ""
    sql = (
        "SELECT k.id, k.customer_id, c.name AS customer_name, "
        "k.key_prefix, k.status, k.billing_mode, k.rate_limit_rpm, "
        "k.price_monthly, k.paid_until, k.created_at, k.last_used_at "
        "FROM api_key AS k JOIN customer AS c ON c.id = k.customer_id "
        f"{where_clause} "
        "ORDER BY k.created_at ASC"
    )
    cursor = conn.execute(sql, params)
    rows: list[ApiKeyListRow] = []
    for row in cursor:
        rows.append(
            ApiKeyListRow(
                id=row["id"],
                customer_id=row["customer_id"],
                customer_name=row["customer_name"],
                key_prefix=row["key_prefix"],
                status=cast(CustomerStatus, row["status"]),
                billing_mode=cast(BillingMode, row["billing_mode"]),
                rate_limit_rpm=int(row["rate_limit_rpm"]),
                price_monthly=float(row["price_monthly"]),
                paid_until=row["paid_until"],
                created_at=row["created_at"],
                last_used_at=row["last_used_at"],
            )
        )
    return rows


def is_first_run(conn: sqlite3.Connection) -> bool:
    """Return True when both ``customer`` and ``api_key`` are empty.

    Drives the UX-DR13 first-run-hint policy for ``list-customers``: the
    create-customer bootstrap hint only shows when the operator has
    never used the system at all. A tombstoned customer row counts as
    prior use, so purged-only DBs return False.
    """
    customers = conn.execute("SELECT COUNT(*) FROM customer").fetchone()[0]
    if customers:
        return False
    keys = conn.execute("SELECT COUNT(*) FROM api_key").fetchone()[0]
    return not keys


def is_first_run_for_keys(conn: sqlite3.Connection) -> bool:
    """Return True when the ``api_key`` table is empty.

    Drives the ``list-keys`` first-run-hint policy: the issue-key
    bootstrap hint fires whenever no keys have been issued yet,
    regardless of whether customers exist — AC7 treats both the
    "customers exist, zero keys" and "completely empty DB" cases
    as first-run for the keys workflow.
    """
    keys = conn.execute("SELECT COUNT(*) FROM api_key").fetchone()[0]
    return not keys


def count_tombstones(conn: sqlite3.Connection) -> int:
    """Return the count of tombstoned customers (``deleted_at IS NOT NULL``)."""
    row = conn.execute(
        "SELECT COUNT(*) FROM customer WHERE deleted_at IS NOT NULL"
    ).fetchone()
    return int(row[0])


def insert_api_key(
    conn: sqlite3.Connection,
    record: ApiKeyRecord,
    *,
    actor: str,
) -> None:
    """Insert an api_key row and its audit row in a single transaction.

    Callers must NOT open a surrounding `with conn:` — this function opens
    the transaction itself so the key insert and the audit row either both
    commit or both roll back (Story 1.2 AC8 invariant).

    `sqlite3.IntegrityError` from the `key_hash UNIQUE` constraint (AC6)
    propagates to the caller, which maps it to the hash-collision error.
    """
    from comadre.keys.audit import log_event

    created_at_iso = record.created_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
    last_used_at_iso = (
        record.last_used_at.astimezone(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")
        if record.last_used_at is not None
        else None
    )
    with conn:
        conn.execute(
            "INSERT INTO api_key ("
            "id, customer_id, key_hash, key_prefix, rate_limit_rpm, status, "
            "billing_mode, price_monthly, paid_until, created_at, last_used_at, "
            "notes"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                record.id,
                record.customer_id,
                record.key_hash,
                record.key_prefix,
                record.rate_limit_rpm,
                record.status,
                record.billing_mode,
                record.price_monthly,
                record.paid_until,
                created_at_iso,
                last_used_at_iso,
                record.notes,
            ),
        )
        log_event(
            conn,
            actor=actor,
            action="issue_key",
            target_type="api_key",
            target_id=record.id,
            details={
                "billing_mode": record.billing_mode,
                "rate_limit_rpm": record.rate_limit_rpm,
            },
        )
