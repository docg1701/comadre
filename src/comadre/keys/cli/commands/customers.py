"""`comadre-keys create-customer` (and future customer subcommands).

Exit-code contract (UX-DR10):
  0 — success
  2 — usage error (Typer rejects / mutex violation / bad email)
  4 — validation error (tax-ID checksum)
  5 — database error (sqlite3.Error)
  6 — permission / configuration error (missing encryption key, etc.)
"""

from __future__ import annotations

import contextlib
import json
import sqlite3
from datetime import UTC, datetime
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer
from pydantic import EmailStr, TypeAdapter, ValidationError

from comadre.config import get_settings
from comadre.exceptions import InvalidTaxIdError
from comadre.keys.audit import get_cli_actor
from comadre.keys.cli._clock import resolve_today_in_tz as _resolve_today_in_tz
from comadre.keys.cli._errors import first_error_msg, is_missing_encryption_key
from comadre.keys.cli.output import (
    LIST_FORMAT_CHOICES,
    render_audit_tail,
    render_confirmation,
    render_customer_detail,
    render_customer_list,
    render_empty_state,
    render_error,
    render_json,
    render_key_detail,
    render_show_json,
)
from comadre.keys.crypto import (
    encrypt_tax_id,
    strip_tax_id,
    validate_cnpj,
    validate_cpf,
)
from comadre.keys.db import (
    UpdateCustomerResult,
    _apply_migrations,
    count_tombstones,
    generate_customer_id,
    get_connection,
    insert_customer,
    is_first_run,
    list_audit_events,
    list_customers,
    resolve_show_target,
    update_customer,
)
from comadre.keys.models import (
    AuditEventRow,
    CustomerDetailRow,
    CustomerListRow,
    CustomerRecord,
    KeyDetailRow,
    TaxIdKind,
)
from comadre.logging import get_logger

_logger = get_logger("keys.cli")

app = typer.Typer(help="Customer registry commands.", no_args_is_help=True)

_missing_key_hint = (
    "Generate one with: python -c 'from cryptography.fernet import "
    "Fernet; print(Fernet.generate_key().decode())' and add it to "
    ".env. Restart the service if monetization is enabled there too."
)


@app.command("create-customer")
def create_customer(
    name: str = typer.Option(
        ...,
        "--name",
        help='Customer full name. Example: "Helena Ribeiro".',
    ),
    email: str = typer.Option(
        ...,
        "--email",
        help='Customer email. Example: "helena@clinica.com".',
    ),
    cpf: str | None = typer.Option(
        None,
        "--cpf",
        help=(
            'CPF (with or without formatting). Example: "123.456.789-09". '
            "Mutually exclusive with --cnpj."
        ),
    ),
    cnpj: str | None = typer.Option(
        None,
        "--cnpj",
        help=('CNPJ. Example: "12.345.678/0001-95". Mutually exclusive with --cpf.'),
    ),
    notes: str = typer.Option(
        "",
        "--notes",
        help='Free-form notes. Example: "5 bots, WhatsApp booking".',
    ),
) -> None:
    """Register a new customer with CPF/CNPJ validation and at-rest encryption."""
    # 1. Mutex check for --cpf / --cnpj.
    if (cpf is None) == (cnpj is None):
        if cpf is not None:
            render_error(
                "Usage error: --cpf and --cnpj are mutually exclusive",
                "Provide exactly one of --cpf or --cnpj.",
            )
        else:
            render_error(
                "Usage error: exactly one of --cpf or --cnpj is required",
                "Provide exactly one of --cpf or --cnpj.",
            )
        raise typer.Exit(code=2)

    # 2. Load settings (trap missing/malformed encryption key or unreadable .env).
    try:
        settings = get_settings()
    except ValidationError as exc:
        if is_missing_encryption_key(exc):
            render_error(
                "Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set",
                _missing_key_hint,
            )
        else:
            render_error("Configuration error", first_error_msg(exc))
        raise typer.Exit(code=6) from None
    except (OSError, PermissionError) as exc:
        render_error("Configuration error: settings file unreadable", str(exc))
        raise typer.Exit(code=6) from None

    if settings.key_registry_encryption_key is None:
        render_error(
            "Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set",
            _missing_key_hint,
        )
        raise typer.Exit(code=6)

    # 3. Determine kind + digits + validate checksum.
    if cpf is not None:
        kind: TaxIdKind = "cpf"
        digits = strip_tax_id(cpf)
    else:
        kind = "cnpj"
        digits = strip_tax_id(cast(str, cnpj))

    try:
        if kind == "cpf":
            validate_cpf(digits)
        else:
            validate_cnpj(digits)
    except InvalidTaxIdError as exc:
        render_error(exc.message, exc.hint)
        raise typer.Exit(code=4) from None

    # 4. Validate name/email by constructing the pydantic model.
    from comadre.keys.models import CustomerCreate

    try:
        CustomerCreate(
            name=name,
            email=email,
            tax_id_kind=kind,
            tax_id_digits=digits,
            notes=notes,
        )
    except ValidationError as exc:
        render_error(
            "Usage error: invalid customer attributes",
            first_error_msg(exc),
        )
        raise typer.Exit(code=2) from None

    # 5. Encrypt tax ID.
    encrypted = encrypt_tax_id(digits, settings.key_registry_encryption_key)

    # 6. Open DB, apply migrations, insert customer + audit in one txn.
    record = CustomerRecord(
        id=generate_customer_id(),
        name=name,
        email=email,
        tax_id_kind=kind,
        tax_id_encrypted=encrypted,
        notes=notes,
        registered_at=datetime.now(UTC).replace(microsecond=0),
        deleted_at=None,
    )

    try:
        conn = get_connection(settings.key_registry_db_path)
        try:
            _apply_migrations(conn)
            insert_customer(conn, record, actor=get_cli_actor())
        finally:
            conn.close()
    except sqlite3.Error as exc:
        render_error("Database error", str(exc))
        raise typer.Exit(code=5) from None

    _logger.info(
        "Customer created | id=%s | tax_id_kind=%s", record.id, record.tax_id_kind
    )
    render_confirmation(f"Customer created: {record.id} ({record.name})")


_FIRST_RUN_CUSTOMER_HINT = (
    'To get started: comadre-keys create-customer --name "Name" '
    '--email "email@example.com" --cpf "000.000.000-00"'
)


def _customer_row_to_json(row: CustomerListRow) -> dict[str, object]:
    """Serialize a ``CustomerListRow`` to the AC4 JSON shape (fixed key order)."""
    return {
        "id": row.id,
        "name": row.name,
        "email": row.email,
        "tax_id_kind": row.tax_id_kind,
        "key_count": row.key_count,
        "registered_at": row.registered_at,
        "deleted_at": row.deleted_at,
        "notes": row.notes,
    }


@app.command("list-customers")
def list_customers_cmd(
    deleted: bool = typer.Option(
        False,
        "--deleted",
        help="Include purged customers (tombstoned by LGPD hard-delete).",
    ),
    format: str = typer.Option(
        "table",
        "--format",
        help=(
            "Output format: table (default, human-readable) or json. "
            "Example: --format json."
        ),
    ),
) -> None:
    """List registered customers with key counts and registration dates.

    Example: comadre-keys list-customers --deleted --format json
    """
    # 1. Validate --format upfront. Accepting unknown formats would silently
    # fall through to the table path; explicit rejection is UX-DR10.
    if format not in LIST_FORMAT_CHOICES:
        render_error(
            "Usage error: --format must be table or json",
            "Valid values: table, json.",
        )
        raise typer.Exit(code=2)

    # 2. Load settings — same exit-6 mapping as create-customer / issue-key.
    try:
        settings = get_settings()
    except ValidationError as exc:
        if is_missing_encryption_key(exc):
            render_error(
                "Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set",
                _missing_key_hint,
            )
        else:
            render_error("Configuration error", first_error_msg(exc))
        raise typer.Exit(code=6) from None
    except (OSError, PermissionError) as exc:
        render_error("Configuration error: settings file unreadable", str(exc))
        raise typer.Exit(code=6) from None

    if settings.key_registry_encryption_key is None:
        render_error(
            "Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set",
            _missing_key_hint,
        )
        raise typer.Exit(code=6)

    # 3. Open DB + apply migrations + read rows. Close in finally + suppress
    # (listings are pure reads — close errors here have nothing to protect).
    try:
        conn = get_connection(settings.key_registry_db_path)
    except sqlite3.Error as exc:
        render_error("Database error", str(exc))
        raise typer.Exit(code=5) from None

    try:
        try:
            _apply_migrations(conn)
        except sqlite3.Error as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None

        rows = list_customers(conn, include_deleted=deleted)
        first_run = is_first_run(conn) if not rows else False
        tombstone_total = count_tombstones(conn) if not deleted and not rows else 0
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    _logger.info("Listed customers | count=%d | include_deleted=%s", len(rows), deleted)

    # 4. Branch on --format. JSON path never emits hint text (AC4).
    if format == "json":
        render_json([_customer_row_to_json(r) for r in rows])
        return

    title = "Customers (including purged)" if deleted else "Customers"

    if rows:
        render_customer_list(title, rows)
        return

    # Empty branches, ordered by UX-DR13 priority.
    if first_run:
        render_empty_state(["No customers registered yet.", _FIRST_RUN_CUSTOMER_HINT])
        return

    if not deleted and tombstone_total > 0:
        render_empty_state(
            [
                "No active customers. Run 'comadre-keys list-customers "
                "--deleted' to see purged records."
            ]
        )
        return

    render_empty_state(["No customers found."])


# ---------------------------------------------------------------------------
# `show` — single-target detail view with optional audit tail (Story 1.4).
# ---------------------------------------------------------------------------

_SHOW_NOT_FOUND_HINT = (
    "Run 'comadre-keys list-customers' or 'comadre-keys list-keys' to see "
    "registered records."
)

_SHOW_AMBIGUOUS_HINT = (
    "Run 'comadre-keys list-keys' to see the full list, then use the key's "
    "customer id (cust_...) instead."
)


def _customer_detail_to_json(row: CustomerDetailRow) -> dict[str, object]:
    """Serialize a ``CustomerDetailRow`` to the AC8 JSON shape (fixed key order)."""
    return {
        "id": row.id,
        "name": row.name,
        "email": row.email,
        "tax_id_kind": row.tax_id_kind,
        "key_count": row.key_count,
        "registered_at": row.registered_at,
        "notes": row.notes,
    }


def _key_detail_to_json(row: KeyDetailRow) -> dict[str, object]:
    """Serialize a ``KeyDetailRow`` to the AC8 JSON shape (fixed key order)."""
    return {
        "id": row.id,
        "customer_id": row.customer_id,
        "customer_name": row.customer_name,
        "key_prefix": row.key_prefix,
        "status": row.status,
        "billing_mode": row.billing_mode,
        "rate_limit_rpm": row.rate_limit_rpm,
        "price_monthly": row.price_monthly,
        "paid_until": row.paid_until,
        "created_at": row.created_at,
        "last_used_at": row.last_used_at,
        "age_days": row.age_days,
        "notes": row.notes,
    }


def _audit_event_to_json(event: AuditEventRow) -> dict[str, object]:
    """Serialize an ``AuditEventRow`` to the AC8 event shape (fixed key order).

    ``details_json`` is re-parsed into a dict/list for consumer ergonomics —
    callers shouldn't have to double-decode the nested payload. Malformed
    rows (shouldn't happen in practice — every writer in the codebase uses
    ``json.dumps`` with ``sort_keys=True``) fall back to the raw string.
    """
    if event.details_json is None:
        details: object | None = None
    else:
        try:
            details = json.loads(event.details_json)
        except json.JSONDecodeError:
            details = event.details_json
    return {
        "id": event.id,
        "occurred_at": event.occurred_at,
        "actor": event.actor,
        "action": event.action,
        "target_type": event.target_type,
        "target_id": event.target_id,
        "details": details,
    }


@app.command("show")
def show_cmd(
    target: str = typer.Argument(
        ...,
        metavar="TARGET",
        help=(
            "Customer ID (cust_...) or 8-char key prefix. "
            'Example: "EVb4xk8B" or "cust_01j8xr3e4c5m7kn9p2qt8vwy".'
        ),
    ),
    audit_tail: int | None = typer.Option(
        None,
        "--audit-tail",
        help=(
            "Append the N most recent audit events. "
            "Example: --audit-tail 20. Range: 1..1000."
        ),
    ),
    format: str = typer.Option(
        "table",
        "--format",
        help=(
            "Output format: table (default, human-readable) or json. "
            "Example: --format json."
        ),
    ),
) -> None:
    """Show full context for a customer or API key (optionally with audit tail).

    Example: comadre-keys show EVb4xk8B --audit-tail 20
    """
    # 1. Literal flag validation.
    if format not in LIST_FORMAT_CHOICES:
        render_error(
            "Usage error: --format must be table or json",
            "Valid values: table, json.",
        )
        raise typer.Exit(code=2)
    if audit_tail is not None and not 1 <= audit_tail <= 1000:
        render_error(
            "Usage error: --audit-tail must be between 1 and 1000",
            "Provide a positive integer in the range 1..1000.",
        )
        raise typer.Exit(code=2)

    # 2. Settings + encryption-key sanity (exit 6 — same mapping as siblings).
    try:
        settings = get_settings()
    except ValidationError as exc:
        if is_missing_encryption_key(exc):
            render_error(
                "Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set",
                _missing_key_hint,
            )
        else:
            render_error("Configuration error", first_error_msg(exc))
        raise typer.Exit(code=6) from None
    except (OSError, PermissionError) as exc:
        render_error("Configuration error: settings file unreadable", str(exc))
        raise typer.Exit(code=6) from None

    if settings.key_registry_encryption_key is None:
        render_error(
            "Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set",
            _missing_key_hint,
        )
        raise typer.Exit(code=6)

    try:
        billing_tz = ZoneInfo(settings.billing_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        render_error(
            "Configuration error: BILLING_TIMEZONE is not a valid IANA timezone",
            (
                "Set BILLING_TIMEZONE to a valid zone (e.g., America/Sao_Paulo). "
                f"Got: {settings.billing_timezone}"
            ),
        )
        raise typer.Exit(code=6) from None

    today = _resolve_today_in_tz(billing_tz)

    # 3. Open DB + migrations + resolve target + fetch events.
    try:
        conn = get_connection(settings.key_registry_db_path)
    except sqlite3.Error as exc:
        render_error("Database error", str(exc))
        raise typer.Exit(code=5) from None

    result_kind: str = "not_found"
    events: list[AuditEventRow] | None = None
    try:
        try:
            _apply_migrations(conn)
        except sqlite3.Error as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None

        resolved = resolve_show_target(conn, target, today=today)
        result_kind = resolved.kind

        if resolved.kind == "not_found":
            render_error(
                f"Not found: no customer or key matches '{target}'",
                _SHOW_NOT_FOUND_HINT,
            )
            raise typer.Exit(code=3)
        if resolved.kind == "key_ambiguous":
            render_error(
                f"Ambiguous prefix: multiple keys match '{target}'",
                _SHOW_AMBIGUOUS_HINT,
            )
            raise typer.Exit(code=3)

        if audit_tail is not None:
            if resolved.kind == "customer":
                customer_row = cast(CustomerDetailRow, resolved.value)
                key_id_rows = conn.execute(
                    "SELECT id FROM api_key WHERE customer_id = ?",
                    (customer_row.id,),
                ).fetchall()
                target_ids = [customer_row.id, *[r["id"] for r in key_id_rows]]
            else:
                key_row = cast(KeyDetailRow, resolved.value)
                target_ids = [key_row.id]
            events = list_audit_events(conn, target_ids, limit=audit_tail)
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    # Redact pasted-plaintext targets before logging — the resolver accepts
    # `cmdr_live_<secret>` as a convenience for operators who paste the full
    # key, but the secret must never reach the structured log. Truncating to
    # the first 8 chars of the suffix mirrors the resolver's own lookup key.
    if target.startswith("cmdr_live_"):
        target_log = "cmdr_live_" + target.removeprefix("cmdr_live_")[:8] + "…"
    else:
        target_log = target
    _logger.info(
        "Showed detail | kind=%s | target=%s | audit_tail=%s",
        result_kind,
        target_log,
        audit_tail,
    )

    # 4. Render branch.
    events_payload: list[dict[str, object]] | None
    if events is None:
        events_payload = None
    else:
        events_payload = [_audit_event_to_json(e) for e in events]

    if format == "json":
        if resolved.kind == "customer":
            render_show_json(
                target_type="customer",
                target=_customer_detail_to_json(
                    cast(CustomerDetailRow, resolved.value)
                ),
                events=events_payload,
            )
        else:
            render_show_json(
                target_type="api_key",
                target=_key_detail_to_json(cast(KeyDetailRow, resolved.value)),
                events=events_payload,
            )
        return

    if resolved.kind == "customer":
        render_customer_detail(cast(CustomerDetailRow, resolved.value))
    else:
        render_key_detail(cast(KeyDetailRow, resolved.value))

    if events is not None:
        render_audit_tail(events)


# ---------------------------------------------------------------------------
# `update-customer` — email + append-note mutation (Story 1.5).
# ---------------------------------------------------------------------------

_EMAIL_ADAPTER = TypeAdapter(EmailStr)

_UPDATE_CUSTOMER_NEITHER_HINT = (
    'Provide --email NEW_EMAIL or --add-note "text" (or both).'
)
_UPDATE_CUSTOMER_NOTE_EMPTY_HINT = (
    "Provide note text with content. Whitespace-only notes are rejected."
)
_UPDATE_CUSTOMER_NOTE_NUL_HINT = "Note text must not contain NUL bytes."
_UPDATE_CUSTOMER_NOTE_NEWLINE_HINT = (
    "Note text must be a single line. Newlines would forge dated entries in "
    "the stored notes column."
)
_UPDATE_CUSTOMER_NOT_FOUND_HINT = (
    "Run 'comadre-keys list-customers' to see registered records."
)


def _update_confirmation_suffix(updated_fields: tuple[str, ...]) -> str:
    """Map ``updated_fields`` to the ConfirmationLine human suffix.

    Grammar is fixed: ``email changed`` / ``note added`` joined with
    ``, `` (comma-space) when both fire. Story 1.5 AC1/AC2/AC3.
    """
    parts: list[str] = []
    if "email" in updated_fields:
        parts.append("email changed")
    if "notes" in updated_fields:
        parts.append("note added")
    return ", ".join(parts)


@app.command("update-customer")
def update_customer_cmd(
    customer_id: str = typer.Argument(
        ...,
        metavar="CUSTOMER_ID",
        help=(
            "Customer ID from create-customer / list-customers. "
            "Example: cust_01j8xr3e4c5m7kn9p2qt8vwy."
        ),
    ),
    email: str | None = typer.Option(
        None,
        "--email",
        help=(
            "Replace the stored email address. "
            'Example: --email "helena@novaclinica.com".'
        ),
    ),
    add_note: str | None = typer.Option(
        None,
        "--add-note",
        help=(
            "Append a dated note to the customer record. "
            'Example: --add-note "paga tarde - lembrar dia 3".'
        ),
    ),
) -> None:
    """Update a customer's email and/or append a dated operator note.

    Example: comadre-keys update-customer cust_01j8xr3e4c5m7kn9p2qt8vwy
             --add-note "paga tarde - lembrar dia 3"
    """
    # 1. Neither-flag check — runs before any DB / settings work so the
    # cheapest usage mistake never opens a connection.
    if email is None and add_note is None:
        render_error(
            "Usage error: at least one of --email or --add-note is required",
            _UPDATE_CUSTOMER_NEITHER_HINT,
        )
        raise typer.Exit(code=2)

    # 2. Email shape check (if provided). Pre-strip before pydantic so
    # operators who copy-paste with trailing whitespace get the same
    # normalized storage as other commands.
    if email is not None:
        stripped_email = email.strip()
        try:
            email = _EMAIL_ADAPTER.validate_python(stripped_email)
        except ValidationError as exc:
            render_error("Usage error: invalid email", first_error_msg(exc))
            raise typer.Exit(code=2) from None

    # 3. Note shape check (if provided). Strip outer whitespace, reject
    # empty-after-strip, and reject NUL bytes (Story 1.1 deferred UX edge
    # picked up here — SQLite accepts NULs but they break later greps).
    if add_note is not None:
        if "\x00" in add_note:
            render_error(
                "Usage error: --add-note contains illegal characters",
                _UPDATE_CUSTOMER_NOTE_NUL_HINT,
            )
            raise typer.Exit(code=2)
        # Reject embedded newlines. The stored format is
        # ``[YYYY-MM-DD] text`` joined with ``\n`` separators, so any LF/CR
        # inside operator-supplied text would be indistinguishable from a
        # real stamped entry on later reads — a forgery vector.
        if "\n" in add_note or "\r" in add_note:
            render_error(
                "Usage error: --add-note must be a single line",
                _UPDATE_CUSTOMER_NOTE_NEWLINE_HINT,
            )
            raise typer.Exit(code=2)
        stripped_note = add_note.strip()
        if not stripped_note:
            render_error(
                "Usage error: --add-note must be non-empty",
                _UPDATE_CUSTOMER_NOTE_EMPTY_HINT,
            )
            raise typer.Exit(code=2)
        add_note = stripped_note

    # 4. Settings load — same exit-6 mapping as the sibling commands. The
    # encryption key isn't used here (no tax-ID operation), but we still
    # validate its presence so the operator gets a consistent configuration
    # error surface across all `comadre-keys` verbs.
    try:
        settings = get_settings()
    except ValidationError as exc:
        if is_missing_encryption_key(exc):
            render_error(
                "Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set",
                _missing_key_hint,
            )
        else:
            render_error("Configuration error", first_error_msg(exc))
        raise typer.Exit(code=6) from None
    except (OSError, PermissionError) as exc:
        render_error("Configuration error: settings file unreadable", str(exc))
        raise typer.Exit(code=6) from None

    if settings.key_registry_encryption_key is None:
        render_error(
            "Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set",
            _missing_key_hint,
        )
        raise typer.Exit(code=6)

    try:
        billing_tz = ZoneInfo(settings.billing_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        render_error(
            "Configuration error: BILLING_TIMEZONE is not a valid IANA timezone",
            (
                "Set BILLING_TIMEZONE to a valid zone (e.g., America/Sao_Paulo). "
                f"Got: {settings.billing_timezone}"
            ),
        )
        raise typer.Exit(code=6) from None

    today = _resolve_today_in_tz(billing_tz)

    # 5. Open DB + migrations + mutation. Close in finally + suppress.
    try:
        conn = get_connection(settings.key_registry_db_path)
    except sqlite3.Error as exc:
        render_error("Database error", str(exc))
        raise typer.Exit(code=5) from None

    result: UpdateCustomerResult | None
    try:
        try:
            _apply_migrations(conn)
        except sqlite3.Error as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None

        try:
            result = update_customer(
                conn,
                customer_id,
                new_email=email,
                add_note=add_note,
                actor=get_cli_actor(),
                today=today,
            )
        except sqlite3.Error as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None
        except RuntimeError as exc:
            # Defensive: ``update_customer`` raises ``RuntimeError`` when the
            # post-commit re-read returns ``None`` (a concurrent tombstone
            # between commit and re-read — "shouldn't happen" in the single-
            # writer CLI). Map to exit 5 so the operator sees the same
            # database-failure surface instead of an unhandled traceback.
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    if result is None:
        render_error(
            f"Customer not found: {customer_id}",
            _UPDATE_CUSTOMER_NOT_FOUND_HINT,
        )
        raise typer.Exit(code=3)

    _logger.info(
        "Updated customer | id=%s | fields=%s",
        customer_id,
        ",".join(result.updated_fields),
    )
    suffix = _update_confirmation_suffix(result.updated_fields)
    render_confirmation(
        f"Updated: {result.customer.id} ({result.customer.name}) \u2014 {suffix}"
    )
