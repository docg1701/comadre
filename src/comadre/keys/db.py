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
from collections.abc import Sequence
from dataclasses import dataclass
from datetime import UTC, date, datetime
from pathlib import Path
from typing import Literal, cast

from ulid import ULID

from comadre.keys.models import (
    ApiKeyListRow,
    ApiKeyRecord,
    AuditEventRow,
    AuthPayload,
    BillingMode,
    CustomerDetailRow,
    CustomerListRow,
    CustomerRecord,
    CustomerStatus,
    KeyDetailRow,
    TaxIdKind,
)

ShowTargetKind = Literal["customer", "key_single", "key_ambiguous", "not_found"]
UpdatedField = Literal["email", "notes"]
UpdateKeyField = Literal["notes", "price", "rpm"]


@dataclass(frozen=True, slots=True)
class UpdateCustomerResult:
    """Return payload from ``update_customer``.

    Carries the refreshed ``CustomerDetailRow`` so the CLI can feed it to
    the ConfirmationLine renderer without a follow-up ``get_customer_detail``
    round-trip. ``updated_fields`` is a sorted, de-duplicated tuple of the
    columns the caller actually touched — used for both the audit payload
    and the human suffix.
    """

    customer: CustomerDetailRow
    updated_fields: tuple[UpdatedField, ...]


@dataclass(frozen=True, slots=True)
class KeyFieldDeltas:
    """Old/new snapshot of the numeric fields ``update_api_key`` touched.

    ``None`` on either side means the field was not in the update set; the
    CLI omits the clause from the ConfirmationLine. Carrying both old and
    new lets the renderer assemble the ``60→120`` arrow form without a
    second DB read.
    """

    rpm_old: int | None
    rpm_new: int | None
    price_old: float | None
    price_new: float | None


@dataclass(frozen=True, slots=True)
class UpdateKeyResult:
    """Return payload from ``update_api_key``.

    ``changes`` captures the pre-/post-mutation numeric values so the
    ConfirmationLine can render the arrow form (``rpm: 60→120``). ``notes``
    replacement does not populate ``changes`` — the renderer emits the
    fixed ``notes updated`` clause instead.
    """

    key: KeyDetailRow
    updated_fields: tuple[UpdateKeyField, ...]
    changes: KeyFieldDeltas


@dataclass(frozen=True, slots=True)
class RotateKeyResult:
    """Return payload from ``rotate_api_key`` — carries the fresh record.

    The ``record`` field carries the in-memory ``ApiKeyRecord`` assembled
    from the pre-UPDATE SELECT + the freshly-computed hash / prefix — the
    helper skips a second DB read because every field of the refreshed
    row is already known inside the transaction. ``old_prefix`` feeds the
    audit-tail delta and the structured log line.
    """

    record: ApiKeyRecord
    customer_name: str
    old_prefix: str


@dataclass(frozen=True, slots=True)
class RevokeKeyResult:
    """Return payload from ``revoke_api_key``.

    The refreshed ``KeyDetailRow`` carries the new ``status='revoked'``
    state so the CLI can render the ConfirmationLine + any follow-up
    ``show``-style surface without a second round-trip. ``reason`` is
    echoed back on the operator's console (``FR37`` covers logs/audit,
    not terminal display).
    """

    key: KeyDetailRow
    customer_name: str
    reason: str


@dataclass(frozen=True, slots=True)
class ShowTarget:
    """Discriminated result of ``resolve_show_target``.

    ``kind`` is the branch tag; ``value`` carries the matching payload. A
    caller does ``if result.kind == "customer": ...`` instead of sniffing
    string shapes or payload types.
    """

    kind: ShowTargetKind
    value: CustomerDetailRow | KeyDetailRow | list[KeyDetailRow] | None


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


def update_customer(
    conn: sqlite3.Connection,
    customer_id: str,
    *,
    new_email: str | None,
    add_note: str | None,
    actor: str,
    today: date,
) -> UpdateCustomerResult | None:
    """Apply the email/notes mutation inside a single transaction.

    Returns ``None`` when the customer is missing or tombstoned. Otherwise
    commits the mutation + an ``update_customer`` audit row and returns the
    refreshed detail row.

    Callers MUST NOT wrap this in ``with conn:`` — the function owns its
    transaction so the UPDATE and the audit write either both commit or
    both roll back (same contract as ``insert_customer`` / ``insert_api_key``).

    ``today`` is the operator-TZ date used to stamp the appended note
    (``[YYYY-MM-DD] text``). The caller resolves it via the existing
    ``cli._clock.resolve_today_in_tz`` seam so tests freeze the clock with
    ``monkeypatch`` instead of the helper touching ``date.today()`` directly.
    """
    from comadre.keys.audit import log_event

    updated: list[UpdatedField] = []
    with conn:
        row = conn.execute(
            "SELECT notes FROM customer WHERE id = ? AND deleted_at IS NULL",
            (customer_id,),
        ).fetchone()
        if row is None:
            return None

        existing_notes = row["notes"] or ""

        # Build the SET clause dynamically so only the touched columns are
        # rewritten. The predicate fragments are literal column-name strings
        # (``"email = ?"`` / ``"notes = ?"``) — operator input only lands in
        # the positional ``?`` bindings, never in SQL text.
        set_parts: list[str] = []
        params: list[object] = []
        if new_email is not None:
            set_parts.append("email = ?")
            params.append(new_email)
            updated.append("email")
        if add_note is not None:
            stamped = f"[{today.isoformat()}] {add_note}"
            new_notes = (
                stamped if not existing_notes else f"{existing_notes}\n{stamped}"
            )
            set_parts.append("notes = ?")
            params.append(new_notes)
            updated.append("notes")

        if not set_parts:
            # Defensive: the CLI layer rejects neither-flag before we get
            # here. If a future caller skips that check, we still don't
            # want to write a no-op audit row.
            return None

        params.append(customer_id)
        # Defense-in-depth: the SELECT above already filtered tombstones,
        # but re-applying ``deleted_at IS NULL`` to the UPDATE prevents a
        # mutation slipping through if a future caller restructures the
        # SELECT-then-UPDATE pair.
        sql = (
            f"UPDATE customer SET {', '.join(set_parts)} "
            "WHERE id = ? AND deleted_at IS NULL"
        )
        conn.execute(sql, params)

        fields_sorted: tuple[UpdatedField, ...] = tuple(sorted(set(updated)))
        log_event(
            conn,
            actor=actor,
            action="update_customer",
            target_type="customer",
            target_id=customer_id,
            details={"fields": list(fields_sorted)},
        )

    refreshed = get_customer_detail(conn, customer_id)
    if refreshed is None:
        # Shouldn't happen — the row existed inside the transaction and
        # nothing else in this process is racing it. Raise so the CLI
        # surfaces an exit-5 instead of misreading it as "tombstone".
        raise RuntimeError(
            f"update_customer: row vanished after commit for {customer_id!r}"
        )
    return UpdateCustomerResult(customer=refreshed, updated_fields=fields_sorted)


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


def get_customer_detail(
    conn: sqlite3.Connection,
    customer_id: str,
) -> CustomerDetailRow | None:
    """Return the active customer detail row (with ``key_count``) or None.

    Tombstoned customers (``deleted_at IS NOT NULL``) are treated as missing,
    matching ``get_customer``. The ``key_count`` column is produced by a
    single ``LEFT JOIN api_key`` — no N+1 follow-up count.
    """
    row = conn.execute(
        "SELECT "
        "c.id, c.name, c.email, c.tax_id_kind, c.notes, "
        "c.registered_at, "
        "COUNT(k.id) AS key_count "
        "FROM customer AS c "
        "LEFT JOIN api_key AS k ON k.customer_id = c.id "
        "WHERE c.id = ? AND c.deleted_at IS NULL "
        "GROUP BY c.id",
        (customer_id,),
    ).fetchone()
    if row is None:
        return None
    return CustomerDetailRow(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        tax_id_kind=cast(TaxIdKind, row["tax_id_kind"]),
        key_count=int(row["key_count"]),
        registered_at=row["registered_at"],
        notes=row["notes"] or "",
    )


def _row_to_key_detail(row: sqlite3.Row, *, today: date) -> KeyDetailRow:
    """Project a joined ``api_key + customer`` row to a ``KeyDetailRow``."""
    created_head = row["created_at"][:10]
    age_days = (today - date.fromisoformat(created_head)).days
    return KeyDetailRow(
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
        age_days=age_days,
        notes=row["notes"] or "",
    )


_KEY_DETAIL_SELECT = (
    "SELECT k.id, k.customer_id, c.name AS customer_name, "
    "k.key_prefix, k.status, k.billing_mode, k.rate_limit_rpm, "
    "k.price_monthly, k.paid_until, k.created_at, k.last_used_at, k.notes "
    "FROM api_key AS k JOIN customer AS c ON c.id = k.customer_id "
)


def get_key_detail(
    conn: sqlite3.Connection,
    key_prefix: str,
    *,
    today: date,
) -> KeyDetailRow | list[KeyDetailRow] | None:
    """Return a key's detail row by exact ``key_prefix`` match.

    Returns ``None`` when no rows match, a single ``KeyDetailRow`` when
    exactly one matches, and a ``list[KeyDetailRow]`` (length ≥ 2) on the
    vanishingly-rare collision. The distinction is a domain signal the
    caller branches on — not an internal detail to flatten away.
    """
    rows = conn.execute(
        _KEY_DETAIL_SELECT + "WHERE k.key_prefix = ?",
        (key_prefix,),
    ).fetchall()
    if not rows:
        return None
    if len(rows) == 1:
        return _row_to_key_detail(rows[0], today=today)
    return [_row_to_key_detail(r, today=today) for r in rows]


def get_key_detail_by_id(
    conn: sqlite3.Connection,
    key_id: str,
    *,
    today: date,
) -> KeyDetailRow | None:
    """Return a key's detail row by exact ``api_key.id`` match (or None)."""
    row = conn.execute(
        _KEY_DETAIL_SELECT + "WHERE k.id = ?",
        (key_id,),
    ).fetchone()
    if row is None:
        return None
    return _row_to_key_detail(row, today=today)


def lookup_key_auth(
    conn: sqlite3.Connection,
    key_hash: str,
) -> AuthPayload | None:
    """Return the minimal auth payload for ``key_hash``, or None on miss.

    Used by ``verify_api_key_registry``. Never writes (auth path is
    read-only). Uses the existing ``idx_api_key_hash`` UNIQUE index — the
    SELECT is O(1).
    """
    row = conn.execute(
        "SELECT id, customer_id, status, billing_mode, rate_limit_rpm, "
        "paid_until FROM api_key WHERE key_hash = ? LIMIT 1",
        (key_hash,),
    ).fetchone()
    if row is None:
        return None
    return AuthPayload(
        customer_id=row["customer_id"],
        key_id=row["id"],
        status=cast(CustomerStatus, row["status"]),
        billing_mode=cast(BillingMode, row["billing_mode"]),
        rate_limit_rpm=int(row["rate_limit_rpm"]),
        paid_until=row["paid_until"],
    )


def list_audit_events(
    conn: sqlite3.Connection,
    target_ids: Sequence[str],
    limit: int,
) -> list[AuditEventRow]:
    """Return the newest-first audit slice for ``target_ids`` capped at ``limit``.

    ``target_ids`` contains the customer id alone (key path) or the customer
    id plus its key ids (customer path) — see ``resolve_show_target`` and
    ``show_cmd`` for the scoping policy. Placeholders for the ``IN`` clause
    are produced programmatically from the sequence length; operator input
    only lands in positional ``?`` bindings, never in the SQL text.

    Raises ``ValueError`` when ``limit`` is outside ``[1, 1000]`` (defensive
    — the Typer layer validates too, but a bare helper should not trust its
    caller). Using ``raise`` rather than ``assert`` so ``-O`` mode keeps the
    check.
    """
    if not 1 <= limit <= 1000:
        raise ValueError(f"limit must be between 1 and 1000, got {limit}")
    if not target_ids:
        return []
    placeholders = ",".join("?" * len(target_ids))
    sql = (
        "SELECT id, occurred_at, actor, action, target_type, target_id, "
        "details_json FROM audit_log "
        f"WHERE target_id IN ({placeholders}) "
        "ORDER BY occurred_at DESC, id DESC LIMIT ?"
    )
    cursor = conn.execute(sql, (*target_ids, limit))
    return [
        AuditEventRow(
            id=int(r["id"]),
            occurred_at=r["occurred_at"],
            actor=r["actor"],
            action=r["action"],
            target_type=r["target_type"],
            target_id=r["target_id"],
            details_json=r["details_json"],
        )
        for r in cursor
    ]


def resolve_show_target(
    conn: sqlite3.Connection,
    raw: str,
    *,
    today: date,
) -> ShowTarget:
    """Discriminate operator input into a ``ShowTarget``.

    Branching is shape-first: the ``cust_`` / ``key_`` / ``cmdr_live_``
    prefixes unambiguously tag the intent. The bare-prefix fallback accepts
    any 1..8 character input; shorter inputs simply miss the exact-match
    query (we do not ``LIKE`` — partial matches open an enumeration side
    channel and the operator has ``list-keys`` for discovery).
    """
    if raw.startswith("cust_"):
        detail = get_customer_detail(conn, raw)
        if detail is None:
            return ShowTarget(kind="not_found", value=None)
        return ShowTarget(kind="customer", value=detail)

    if raw.startswith("cmdr_live_"):
        # Convenience for an operator who pasted the full plaintext: strip
        # the advertised prefix and use the first 8 chars of the remainder
        # as the key_prefix candidate, then resolve through the same
        # bare-prefix lookup as the fallback branch below.
        candidate = raw.removeprefix("cmdr_live_")[:8]
        result = get_key_detail(conn, candidate, today=today)
        if result is None:
            return ShowTarget(kind="not_found", value=None)
        if isinstance(result, list):
            return ShowTarget(kind="key_ambiguous", value=result)
        return ShowTarget(kind="key_single", value=result)

    if raw.startswith("key_"):
        by_id = get_key_detail_by_id(conn, raw, today=today)
        if by_id is None:
            return ShowTarget(kind="not_found", value=None)
        return ShowTarget(kind="key_single", value=by_id)

    result = get_key_detail(conn, raw, today=today)
    if result is None:
        return ShowTarget(kind="not_found", value=None)
    if isinstance(result, list):
        return ShowTarget(kind="key_ambiguous", value=result)
    return ShowTarget(kind="key_single", value=result)


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


def update_api_key(
    conn: sqlite3.Connection,
    key_id: str,
    *,
    new_rpm: int | None,
    new_price: float | None,
    new_notes: str | None,
    actor: str,
    today: date,
) -> UpdateKeyResult | None:
    """Apply the rpm/price/notes mutation inside a single transaction.

    Returns ``None`` when the row is missing. Raises ``ValueError`` when
    the row is revoked or when ``new_price`` is set on a complimentary
    key (the CLI maps the second case to an exit-2 usage error — the
    helper's ``ValueError`` is a defensive safety net behind the CLI's
    upstream mutex check).

    Callers MUST NOT wrap this in ``with conn:`` — the function owns its
    transaction so the UPDATE and audit write either both commit or both
    roll back. Same contract as ``insert_customer`` / ``insert_api_key`` /
    ``update_customer``.

    ``today`` is the operator-TZ date forwarded to ``get_key_detail_by_id``
    so the post-commit re-read is clock-seamed (tests freeze today via
    monkeypatch instead of the helper touching ``date.today()``).
    """
    from comadre.keys.audit import log_event

    updated: list[UpdateKeyField] = []
    old_rpm: int | None = None
    old_price: float | None = None
    with conn:
        row = conn.execute(
            "SELECT status, billing_mode, rate_limit_rpm, price_monthly "
            "FROM api_key WHERE id = ?",
            (key_id,),
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "revoked":
            raise ValueError("cannot update a revoked key")
        if row["billing_mode"] == "complimentary" and new_price is not None:
            raise ValueError("cannot set --price on a complimentary key")

        old_rpm = int(row["rate_limit_rpm"])
        old_price = float(row["price_monthly"])

        # Build the SET clause dynamically so only the touched columns are
        # rewritten. The predicate fragments are literal column-name strings
        # (``"rate_limit_rpm = ?"``) — operator input only lands in the
        # positional ``?`` bindings, never in SQL text.
        set_parts: list[str] = []
        params: list[object] = []
        if new_rpm is not None:
            set_parts.append("rate_limit_rpm = ?")
            params.append(new_rpm)
            updated.append("rpm")
        if new_price is not None:
            set_parts.append("price_monthly = ?")
            params.append(float(new_price))
            updated.append("price")
        if new_notes is not None:
            set_parts.append("notes = ?")
            params.append(new_notes)
            updated.append("notes")

        if not set_parts:
            # Programmer error: the CLI layer rejects neither-flag upfront.
            # Raise ``RuntimeError`` (maps to exit 5 at the CLI) so the
            # return value stays unambiguous — ``None`` means "row missing",
            # never "caller forgot to pass any field".
            raise RuntimeError(f"update_api_key: no fields to update for {key_id!r}")

        params.append(key_id)
        # Defense-in-depth: the SELECT filtered revoked rows, but re-applying
        # the predicate to the UPDATE prevents a mutation slipping through
        # if a future caller restructures the SELECT-then-UPDATE pair.
        sql = (
            f"UPDATE api_key SET {', '.join(set_parts)} "
            "WHERE id = ? AND status != 'revoked'"
        )
        conn.execute(sql, params)

        fields_sorted: tuple[UpdateKeyField, ...] = tuple(sorted(set(updated)))
        log_event(
            conn,
            actor=actor,
            action="update_key",
            target_type="api_key",
            target_id=key_id,
            details={"fields": list(fields_sorted)},
        )

    refreshed = get_key_detail_by_id(conn, key_id, today=today)
    if refreshed is None:
        raise RuntimeError(f"update_api_key: row vanished after commit for {key_id!r}")

    deltas = KeyFieldDeltas(
        rpm_old=old_rpm if new_rpm is not None else None,
        rpm_new=new_rpm if new_rpm is not None else None,
        price_old=old_price if new_price is not None else None,
        price_new=float(new_price) if new_price is not None else None,
    )
    return UpdateKeyResult(key=refreshed, updated_fields=fields_sorted, changes=deltas)


def rotate_api_key(
    conn: sqlite3.Connection,
    key_id: str,
    *,
    new_plaintext: str,
    actor: str,
) -> RotateKeyResult | None:
    """Rotate an API key's plaintext — new hash, new prefix, same ``id``.

    Returns ``None`` when the row is missing. Raises ``ValueError`` when
    the row is revoked (rotation is rejected; the CLI maps to exit 3).
    Propagates ``sqlite3.IntegrityError`` when the freshly-computed hash
    collides with an existing row's ``key_hash`` (AC12 — exit 5 with a
    retry hint at the CLI layer).

    Callers MUST NOT wrap this in ``with conn:``. The UPDATE and audit
    write either both commit or both roll back — if the audit write
    fails the old ``key_hash`` stays authoritative and no plaintext has
    been disclosed yet.

    No ``today`` parameter: the helper assembles the refreshed
    ``ApiKeyRecord`` from the pre-UPDATE SELECT row plus the new hash /
    prefix in-memory, skipping a second DB round-trip. The ``ApiKeyRecord``
    type has no date-derived fields (``age_days`` lives on ``KeyDetailRow``,
    which the rotate flow does not need — it renders a ``KeyPanel``).
    """
    from comadre.keys.audit import log_event
    from comadre.keys.tokens import hash_api_key, key_prefix_from_plaintext

    new_hash = hash_api_key(new_plaintext)
    new_prefix = key_prefix_from_plaintext(new_plaintext)

    with conn:
        row = conn.execute(
            "SELECT k.id, k.customer_id, k.key_prefix, k.rate_limit_rpm, "
            "k.status, k.billing_mode, k.price_monthly, k.paid_until, "
            "k.created_at, k.notes, c.name AS customer_name "
            "FROM api_key AS k JOIN customer AS c ON c.id = k.customer_id "
            "WHERE k.id = ?",
            (key_id,),
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "revoked":
            raise ValueError("cannot rotate a revoked key")

        old_prefix = row["key_prefix"]

        conn.execute(
            "UPDATE api_key SET key_hash = ?, key_prefix = ?, "
            "last_used_at = NULL WHERE id = ?",
            (new_hash, new_prefix, key_id),
        )
        log_event(
            conn,
            actor=actor,
            action="rotate_key",
            target_type="api_key",
            target_id=key_id,
            details={"key_prefix_old": old_prefix, "key_prefix_new": new_prefix},
        )

    created_at_dt = datetime.fromisoformat(row["created_at"])
    refreshed = ApiKeyRecord(
        id=row["id"],
        customer_id=row["customer_id"],
        key_hash=new_hash,
        key_prefix=new_prefix,
        rate_limit_rpm=int(row["rate_limit_rpm"]),
        status=cast("CustomerStatus", row["status"]),
        billing_mode=cast("BillingMode", row["billing_mode"]),
        price_monthly=float(row["price_monthly"]),
        paid_until=row["paid_until"],
        created_at=created_at_dt,
        last_used_at=None,
        notes=row["notes"] or "",
    )
    return RotateKeyResult(
        record=refreshed, customer_name=row["customer_name"], old_prefix=old_prefix
    )


def revoke_api_key(
    conn: sqlite3.Connection,
    key_id: str,
    *,
    reason: str,
    actor: str,
    today: date,
) -> RevokeKeyResult | None:
    """Mark the ``api_key`` row revoked inside a single transaction.

    Returns ``None`` when the row is missing. Raises ``ValueError`` when
    the row is already revoked (revocation is terminal; the CLI maps to
    exit 3).

    Callers MUST NOT wrap this in ``with conn:``. The UPDATE and audit
    write either both commit or both roll back.

    ``today`` is forwarded to ``get_key_detail_by_id`` so the post-commit
    re-read that populates the returned ``KeyDetailRow`` is clock-seamed.
    The signature deviates from the Story 1.6 code sketch (which omitted
    ``today``) because the re-read needs an operator-TZ date to compute
    ``age_days`` without touching ``date.today()`` — keeping tests
    clock-free matches the ``update_api_key`` and ``update_customer``
    precedent.

    ``reason`` is shape-validated here (NUL / LF / CR / strip-empty /
    1024-char cap) so the audit-row contract is enforced at every call-
    site — not only from the CLI. Raises ``ValueError`` for any violation.
    The CLI performs the same checks upfront (exit 2) so these are
    defense-in-depth for non-CLI callers.
    """
    from comadre.keys.audit import log_event

    if "\x00" in reason:
        raise ValueError("reason contains NUL byte")
    if "\n" in reason or "\r" in reason:
        raise ValueError("reason must be a single line")
    reason = reason.strip()
    if not reason:
        raise ValueError("reason must be non-empty")
    if len(reason) > 1024:
        raise ValueError("reason exceeds 1024 characters")

    with conn:
        row = conn.execute(
            "SELECT status FROM api_key WHERE id = ?",
            (key_id,),
        ).fetchone()
        if row is None:
            return None
        if row["status"] == "revoked":
            raise ValueError("already revoked")

        cursor = conn.execute(
            "UPDATE api_key SET status = 'revoked' "
            "WHERE id = ? AND status != 'revoked'",
            (key_id,),
        )
        # Guard against a concurrent revocation slipping between the SELECT
        # and UPDATE. Under the single-writer CLI this is effectively
        # unreachable, but the RuntimeError surfaces it as exit 5 rather
        # than silently succeeding on a no-op UPDATE.
        if cursor.rowcount != 1:
            raise RuntimeError(
                "revoke_api_key: update failed to match any row after SELECT "
                f"succeeded for {key_id!r}"
            )

        log_event(
            conn,
            actor=actor,
            action="revoke_key",
            target_type="api_key",
            target_id=key_id,
            details={"reason": reason},
        )

    refreshed = get_key_detail_by_id(conn, key_id, today=today)
    if refreshed is None:
        raise RuntimeError(f"revoke_api_key: row vanished after commit for {key_id!r}")
    return RevokeKeyResult(
        key=refreshed, customer_name=refreshed.customer_name, reason=reason
    )
