"""`comadre-keys create-customer` (and future customer subcommands).

Exit-code contract (UX-DR10):
  0 — success
  2 — usage error (Typer rejects / mutex violation / bad email)
  4 — validation error (tax-ID checksum)
  5 — database error (sqlite3.Error)
  6 — permission / configuration error (missing encryption key, etc.)
"""

from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import cast

import typer
from pydantic import ValidationError

from comadre.config import get_settings
from comadre.exceptions import InvalidTaxIdError
from comadre.keys.audit import get_cli_actor
from comadre.keys.cli._errors import first_error_msg, is_missing_encryption_key
from comadre.keys.cli.output import render_confirmation, render_error
from comadre.keys.crypto import (
    encrypt_tax_id,
    strip_tax_id,
    validate_cnpj,
    validate_cpf,
)
from comadre.keys.db import (
    _apply_migrations,
    generate_customer_id,
    get_connection,
    insert_customer,
)
from comadre.keys.models import CustomerRecord, TaxIdKind
from comadre.logging import get_logger

_logger = get_logger("keys.cli")

app = typer.Typer(help="Customer registry commands.", no_args_is_help=True)


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
    _missing_key_hint = (
        "Generate one with: python -c 'from cryptography.fernet import "
        "Fernet; print(Fernet.generate_key().decode())' and add it to "
        ".env. Restart the service if monetization is enabled there too."
    )
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
