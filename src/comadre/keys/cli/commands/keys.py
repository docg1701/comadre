"""`comadre-keys issue-key` (and future API-key subcommands).

Exit-code contract (UX-DR10):
  0 — success
  2 — usage error (missing/illegal flags, bad billing-mode combo)
  3 — not-found (customer missing or tombstoned)
  5 — database error (sqlite3.Error, hash collision)
  6 — permission / configuration error (missing encryption key,
      invalid IANA timezone)
"""

from __future__ import annotations

import contextlib
import math
import sqlite3
from datetime import UTC, date, datetime
from typing import cast
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer
from pydantic import ValidationError

from comadre.config import get_settings
from comadre.keys.audit import get_cli_actor
from comadre.keys.billing import ManualBillingProvider, days_until, first_charge_date
from comadre.keys.cli._errors import first_error_msg, is_missing_encryption_key
from comadre.keys.cli.output import render_error, render_key_panel
from comadre.keys.db import (
    _apply_migrations,
    generate_key_id,
    get_connection,
    get_customer,
    insert_api_key,
)
from comadre.keys.models import ApiKeyCreate, ApiKeyRecord, BillingMode, IssuedKey
from comadre.keys.tokens import (
    generate_api_key_plaintext,
    hash_api_key,
    key_prefix_from_plaintext,
)
from comadre.logging import get_logger

_logger = get_logger("keys.cli")

app = typer.Typer(help="API key registry commands.", no_args_is_help=True)

_VALID_BILLING_MODES = ("manual", "complimentary")

_MISSING_KEY_HINT = (
    "Generate one with: python -c 'from cryptography.fernet import "
    "Fernet; print(Fernet.generate_key().decode())' and add it to "
    ".env. Restart the service if monetization is enabled there too."
)


def _resolve_today_in_tz(tz: ZoneInfo) -> date:
    """Return today's date resolved in ``tz``. Thin seam for tests to freeze."""
    return datetime.now(tz).date()


@app.command("issue-key")
def issue_key(
    customer: str = typer.Option(
        ...,
        "--customer",
        help=(
            "Customer ID from create-customer. "
            'Example: "cust_01j8xr3e4c5m7kn9p2qt8vwy".'
        ),
    ),
    rpm: int = typer.Option(
        ...,
        "--rpm",
        help="Per-key requests-per-minute limit. Example: 60.",
    ),
    billing_mode: str = typer.Option(
        "manual",
        "--billing-mode",
        help="manual (default) or complimentary. Example: --billing-mode manual.",
    ),
    price: float | None = typer.Option(
        None,
        "--price",
        help="Monthly price in BRL. Required for manual billing. Example: --price 149.",
    ),
    notes: str = typer.Option(
        "",
        "--notes",
        help=(
            "Free-form operator notes. "
            'Example: "bundled into infra package R$ 850/month".'
        ),
    ),
) -> None:
    """Issue an API key for a registered customer (one-shot plaintext display)."""
    # 1. billing-mode literal.
    if billing_mode not in _VALID_BILLING_MODES:
        render_error(
            "Usage error: --billing-mode must be manual or complimentary",
            "Valid values: manual, complimentary.",
        )
        raise typer.Exit(code=2)

    # 2. billing-mode / price combination.
    if billing_mode == "manual" and price is None:
        render_error(
            "Usage error: --price is required for manual billing mode",
            "Specify --price <R$ per month> or use --billing-mode complimentary.",
        )
        raise typer.Exit(code=2)
    if billing_mode == "complimentary" and price is not None:
        render_error(
            "Usage error: --price is not applicable to complimentary keys",
            (
                "Complimentary keys are bundled externally; omit --price or "
                "change --billing-mode to manual."
            ),
        )
        raise typer.Exit(code=2)
    if billing_mode == "manual":
        assert price is not None  # guarded above
        if not math.isfinite(price):
            render_error(
                "Usage error: --price must be a finite number",
                "Provide a positive --price in BRL, e.g. --price 149.",
            )
            raise typer.Exit(code=2)
        if price <= 0:
            # Zero / negative prices must route through complimentary mode.
            # That mode exists precisely for bundled customers where Comadre
            # is included in a larger package and no per-key charge applies.
            render_error(
                "Usage error: --price must be positive for manual billing mode",
                (
                    "Use --billing-mode complimentary for bundled / no-charge "
                    "customers, or provide a positive --price in BRL."
                ),
            )
            raise typer.Exit(code=2)
    effective_price = (
        0.0 if billing_mode == "complimentary" else float(cast(float, price))
    )

    # 3. rpm > 0 (Typer coerces to int but doesn't enforce positivity).
    if rpm <= 0:
        render_error(
            "Usage error: --rpm must be positive",
            "Specify --rpm <positive integer>.",
        )
        raise typer.Exit(code=2)

    # 4. Settings + encryption-key sanity.
    try:
        settings = get_settings()
    except ValidationError as exc:
        if is_missing_encryption_key(exc):
            render_error(
                "Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set",
                _MISSING_KEY_HINT,
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
            _MISSING_KEY_HINT,
        )
        raise typer.Exit(code=6)

    try:
        billing_tz = ZoneInfo(settings.billing_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        render_error(
            "Configuration error: BILLING_TIMEZONE is not a valid IANA timezone",
            f"Set BILLING_TIMEZONE to a valid zone (e.g., America/Sao_Paulo). "
            f"Got: {settings.billing_timezone}",
        )
        raise typer.Exit(code=6) from None

    # 5. Open DB, apply migrations, look up customer.
    #    Customer lookup runs BEFORE ApiKeyCreate validation so that
    #    syntactically invalid ids (e.g., ``cust_nope``) yield exit 3
    #    "Customer not found" rather than exit 2 "usage error" — the
    #    operator sees the actionable message (AC3).
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

        customer_record = get_customer(conn, customer)
        if customer_record is None:
            render_error(
                f"Customer not found: {customer}",
                "Run 'comadre-keys list-customers' to see registered customers.",
            )
            raise typer.Exit(code=3)

        # 6. ApiKeyCreate input validation — defensive. Customer id is a DB row
        # id at this point, so format-validation is redundant but cheap.
        try:
            ApiKeyCreate(
                customer_id=customer,
                rate_limit_rpm=rpm,
                billing_mode=billing_mode,
                price_monthly=effective_price,
                notes=notes,
            )
        except ValidationError as exc:
            render_error(
                "Usage error: invalid issue-key parameters",
                first_error_msg(exc),
            )
            raise typer.Exit(code=2) from None

        # 7. Generate plaintext + hash + prefix + id. Plaintext stays in this
        # local scope; the record and IssuedKey wrappers carry only hash/prefix
        # and the plaintext reference until render_key_panel returns.
        plaintext = generate_api_key_plaintext()
        key_hash_hex = hash_api_key(plaintext)
        key_prefix = key_prefix_from_plaintext(plaintext)
        key_id = generate_key_id()
        created_at = datetime.now(UTC).replace(microsecond=0)

        # 8. First-charge date (manual only).
        if billing_mode == "manual":
            today_local = _resolve_today_in_tz(billing_tz)
            fc_date = first_charge_date(
                today=today_local,
                billing_day=settings.billing_day,
                tz=settings.billing_timezone,
            )
            fc_iso: str | None = fc_date.isoformat()
            fc_days_free: int | None = days_until(fc_date, from_date=today_local)
        else:
            fc_iso = None
            fc_days_free = None

        record = ApiKeyRecord(
            id=key_id,
            customer_id=customer,
            key_hash=key_hash_hex,
            key_prefix=key_prefix,
            rate_limit_rpm=rpm,
            status="active",
            billing_mode=cast(BillingMode, billing_mode),
            price_monthly=effective_price,
            paid_until=None,
            created_at=created_at,
            last_used_at=None,
            notes=notes,
        )

        # 9. Insert + audit in one transaction.
        try:
            insert_api_key(conn, record, actor=get_cli_actor())
        except sqlite3.IntegrityError as exc:
            # Prefer sqlite_errorcode (stable since Python 3.11) over locale-
            # dependent message-text matching. Fall back to substring for
            # robustness against older SQLite builds.
            errorcode = getattr(exc, "sqlite_errorcode", None)
            args_msg = str(exc.args[0]) if exc.args else ""
            is_unique = errorcode == sqlite3.SQLITE_CONSTRAINT_UNIQUE or (
                "UNIQUE" in args_msg.upper()
            )
            if is_unique and "key_hash" in args_msg:
                render_error(
                    "Database error: key hash collision",
                    (
                        "Retry the command — this is vanishingly rare. "
                        "If it repeats, check disk integrity."
                    ),
                )
            else:
                render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None
        except ValueError as exc:
            # log_event's audit-blocklist guard raises ValueError when an
            # attempt to store personal data in audit details is detected.
            # The `with conn:` block in insert_api_key has already rolled
            # back the api_key row, so we only need to surface the error.
            render_error(
                "Audit error: refused to write audit record",
                str(exc),
            )
            raise typer.Exit(code=5) from None
        except sqlite3.Error as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None

        # 10. Billing hook (MVP no-op).
        ManualBillingProvider().on_key_issued(record)
    finally:
        # Suppress close errors post-commit — the row is already durable and
        # a surfaced close error would make a successful issuance look failed.
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    # 11. Structured INFO log — NEVER plaintext, NEVER hash, NEVER customer_name.
    _logger.info(
        "Key issued | id=%s | customer_id=%s | billing_mode=%s | rate_limit_rpm=%s",
        record.id,
        record.customer_id,
        record.billing_mode,
        record.rate_limit_rpm,
    )

    # 12. One-shot display. After render_key_panel returns, the local
    # plaintext variable goes out of scope at function end.
    issued = IssuedKey(
        plaintext=plaintext,
        record=record,
        customer_name=customer_record.name,
        first_charge_date=fc_iso,
        first_charge_days_free=fc_days_free,
    )
    render_key_panel(issued)
