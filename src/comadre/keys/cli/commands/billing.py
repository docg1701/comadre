"""`comadre-keys mark-paid` / `suspend` / `reactivate` (Story 3.1).

Exit-code contract (UX-DR10):
  0 — success (also: ``mark-paid`` on a complimentary key — informational,
      no mutation; see AC5 rationale)
  2 — usage error (bad ``--until`` shape, customer-ID passed as key arg)
  3 — not-found / terminal state (key missing, ambiguous prefix,
      already-active / already-suspended / revoked)
  5 — database error (``sqlite3.Error``, ``RuntimeError`` from helper)
  6 — permission / configuration error (missing encryption key,
      invalid IANA timezone)
"""

from __future__ import annotations

import contextlib
import sqlite3
from datetime import date

import typer

from comadre.keys.audit import get_cli_actor
from comadre.keys.cli._clock import resolve_today_in_tz as _resolve_today_in_tz
from comadre.keys.cli.commands.keys import (
    _truncate_ident,
    load_settings_and_tz,
    resolve_key_target,
)
from comadre.keys.cli.output import render_confirmation, render_error
from comadre.keys.db import (
    _apply_migrations,
    get_connection,
    mark_key_paid,
    reactivate_key,
    suspend_key,
)
from comadre.logging import get_logger

_logger = get_logger("keys.cli")

app = typer.Typer(help="Billing verbs for API keys.", no_args_is_help=True)

# Hints for the three new verbs. Kept here (not in keys.py) because they are
# verb-specific phrasing; the shared identifier hints (``_KEY_NOT_FOUND_HINT``
# etc.) live in keys.py and are imported above.
_MARK_PAID_UNTIL_HINT = (
    "Example: --until 2026-06-05. Alternate ISO forms (e.g. 20260605) are "
    "accepted and normalized."
)
_MARK_PAID_REVOKED_HINT = (
    "Revoked keys are terminal. Issue a new key via issue-key if the customer returns."
)
_MARK_PAID_COMPLIMENTARY_HINT = (
    "Complimentary keys are bundled externally — no payment tracking "
    "applies. Use update-key to change rate limits."
)
_SUSPEND_ALREADY_HINT = "Run 'comadre-keys show <prefix>' to inspect current status."
_SUSPEND_REVOKED_HINT = (
    "Revoked keys are terminal. Issue a new key via issue-key if the customer returns."
)
_REACTIVATE_ALREADY_HINT = "Run 'comadre-keys show <prefix>' to inspect current status."
_REACTIVATE_REVOKED_HINT = (
    "Revoked keys cannot be reactivated. Issue a new key via issue-key if "
    "the customer returns."
)


def _parse_until(raw: str) -> date:
    """Parse ``--until`` and exit 2 on any shape violation.

    Accepts any form ``date.fromisoformat`` parses (``2026-06-05``,
    ``20260605``, etc.) and the caller re-emits ``.isoformat()`` so the
    stored ``paid_until`` is always the canonical ``YYYY-MM-DD`` form —
    non-canonical forms would silently break the lexicographic
    ``paid_until < ?`` comparison in the cron sweep.

    Past dates are accepted — retroactive payment logging is a legitimate
    operator workflow (Story 3.1 AC8). The cron sweep will re-suspend the
    row on the next run if the date is in the past.
    """
    trimmed = raw.strip()
    if not trimmed:
        render_error(
            "Usage error: --until must be an ISO date (YYYY-MM-DD)",
            _MARK_PAID_UNTIL_HINT,
        )
        raise typer.Exit(code=2)
    try:
        return date.fromisoformat(trimmed)
    except ValueError:
        render_error(
            "Usage error: --until must be an ISO date (YYYY-MM-DD)",
            _MARK_PAID_UNTIL_HINT,
        )
        raise typer.Exit(code=2) from None


@app.command("mark-paid")
def mark_paid_cmd(
    key_prefix: str = typer.Argument(
        ...,
        metavar="KEY_PREFIX",
        help=(
            "8-char key prefix, key_<ulid>, or pasted cmdr_live_<plaintext>. "
            'Example: "Pq_abc12".'
        ),
    ),
    until: str = typer.Option(
        ...,
        "--until",
        help=(
            "Extend paid_until to this ISO date (YYYY-MM-DD). Past dates "
            "are accepted (retroactive logging). "
            "Example: --until 2026-06-05."
        ),
    ),
) -> None:
    """Confirm payment for a key and extend its validity (auto-reactivates).

    Example: comadre-keys mark-paid Pq_abc12 --until 2026-06-05
    """
    # 1. --until shape + canonicalization (exit 2).
    until_date = _parse_until(until)
    until_iso = until_date.isoformat()

    # 2. Settings + TZ (exit 6).
    loaded = load_settings_and_tz()
    if loaded is None:
        raise typer.Exit(code=6)
    settings, billing_tz = loaded
    today = _resolve_today_in_tz(billing_tz)

    # 3. Open DB + migrations (exit 5).
    try:
        conn = get_connection(settings.key_registry_db_path)  # type: ignore[attr-defined]
    except sqlite3.Error as exc:
        render_error("Database error", str(exc))
        raise typer.Exit(code=5) from None

    try:
        try:
            _apply_migrations(conn)
        except sqlite3.Error as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None

        # 4. Resolve prefix → KeyDetailRow (exit 3 / 2 on non-key branches).
        key_row = resolve_key_target(conn, key_prefix, today=today)

        # 5. Complimentary short-circuit (exit 0, informational) — AC5.
        if key_row.billing_mode == "complimentary":
            render_confirmation(
                f"Key {key_row.key_prefix} is complimentary — "
                "no payment tracking required."
            )
            return

        # 6. Helper dispatch.
        try:
            result = mark_key_paid(
                conn,
                key_row.id,
                paid_until=until_iso,
                actor=get_cli_actor(),
                today=today,
            )
        except ValueError as exc:
            msg = str(exc)
            if msg == "cannot mark-paid a revoked key":
                render_error(
                    f"Key is revoked: {_truncate_ident(key_prefix)}",
                    _MARK_PAID_REVOKED_HINT,
                )
                raise typer.Exit(code=3) from None
            if msg == "cannot mark-paid a complimentary key":
                # Defense-in-depth — step 5 catches this first in the CLI.
                render_error(
                    f"Key is complimentary: {_truncate_ident(key_prefix)}",
                    _MARK_PAID_COMPLIMENTARY_HINT,
                )
                raise typer.Exit(code=3) from None
            raise
        except sqlite3.Error as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None
        except RuntimeError as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    # ``result`` is not None — resolve_key_target already confirmed the row.
    # Explicit check (not ``assert``) so ``python -O`` cannot strip it and
    # leave a bare ``AttributeError`` traceback on an impossible race.
    if result is None:
        render_error(
            "Database error",
            "Key vanished between resolve and mark-paid; retry the command.",
        )
        raise typer.Exit(code=5)

    # 7. Structured INFO log — no customer name / email / CPF / CNPJ / plaintext.
    with contextlib.suppress(Exception):
        _logger.info(
            "Marked paid | id=%s | paid_until=%s | reactivated=%s",
            result.key.id,
            until_iso,
            result.reactivated,
        )

    # 8. ConfirmationLine (UX-DR7). U+2192 arrow, optional "(reactivated)".
    suffix = " (reactivated)" if result.reactivated else ""
    render_confirmation(
        f"Marked paid: {result.key.key_prefix} "
        f"({result.key.customer_name}) \u2192 paid until {until_iso}{suffix}"
    )


@app.command("suspend")
def suspend_cmd(
    key_prefix: str = typer.Argument(
        ...,
        metavar="KEY_PREFIX",
        help=(
            "8-char key prefix, key_<ulid>, or pasted cmdr_live_<plaintext>. "
            'Example: "Pq_abc12".'
        ),
    ),
) -> None:
    """Manually suspend an API key (out-of-cycle; for abuse or contract disputes).

    Example: comadre-keys suspend Pq_abc12
    """
    # 1. Settings + TZ (exit 6).
    loaded = load_settings_and_tz()
    if loaded is None:
        raise typer.Exit(code=6)
    settings, billing_tz = loaded
    today = _resolve_today_in_tz(billing_tz)

    # 2. Open DB + migrations (exit 5).
    try:
        conn = get_connection(settings.key_registry_db_path)  # type: ignore[attr-defined]
    except sqlite3.Error as exc:
        render_error("Database error", str(exc))
        raise typer.Exit(code=5) from None

    try:
        try:
            _apply_migrations(conn)
        except sqlite3.Error as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None

        # 3. Resolve prefix → KeyDetailRow.
        key_row = resolve_key_target(conn, key_prefix, today=today)

        # 4. Helper dispatch.
        try:
            result = suspend_key(
                conn,
                key_row.id,
                actor=get_cli_actor(),
                today=today,
            )
        except ValueError as exc:
            msg = str(exc)
            if msg == "cannot suspend a revoked key":
                render_error(
                    f"Key is revoked: {_truncate_ident(key_prefix)}",
                    _SUSPEND_REVOKED_HINT,
                )
                raise typer.Exit(code=3) from None
            if msg == "already suspended":
                render_error(
                    f"Key already suspended: {_truncate_ident(key_prefix)}",
                    _SUSPEND_ALREADY_HINT,
                )
                raise typer.Exit(code=3) from None
            raise
        except sqlite3.Error as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None
        except RuntimeError as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    # Explicit check (not ``assert``) so ``python -O`` cannot strip it.
    if result is None:
        render_error(
            "Database error",
            "Key vanished between resolve and suspend; retry the command.",
        )
        raise typer.Exit(code=5)

    # 5. Structured INFO log.
    with contextlib.suppress(Exception):
        _logger.info(
            "Suspended | id=%s | key_prefix=%s",
            result.key.id,
            result.key.key_prefix,
        )

    # 6. ConfirmationLine (UX-DR7) — bare form, no suffix.
    render_confirmation(
        f"Suspended: {result.key.key_prefix} ({result.key.customer_name})"
    )


@app.command("reactivate")
def reactivate_cmd(
    key_prefix: str = typer.Argument(
        ...,
        metavar="KEY_PREFIX",
        help=(
            "8-char key prefix, key_<ulid>, or pasted cmdr_live_<plaintext>. "
            'Example: "Pq_abc12".'
        ),
    ),
) -> None:
    """Reactivate a suspended key without extending billing (does NOT set paid_until).

    Example: comadre-keys reactivate Pq_abc12
    """
    # 1. Settings + TZ (exit 6).
    loaded = load_settings_and_tz()
    if loaded is None:
        raise typer.Exit(code=6)
    settings, billing_tz = loaded
    today = _resolve_today_in_tz(billing_tz)

    # 2. Open DB + migrations (exit 5).
    try:
        conn = get_connection(settings.key_registry_db_path)  # type: ignore[attr-defined]
    except sqlite3.Error as exc:
        render_error("Database error", str(exc))
        raise typer.Exit(code=5) from None

    try:
        try:
            _apply_migrations(conn)
        except sqlite3.Error as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None

        # 3. Resolve prefix → KeyDetailRow.
        key_row = resolve_key_target(conn, key_prefix, today=today)

        # 4. Helper dispatch.
        try:
            result = reactivate_key(
                conn,
                key_row.id,
                actor=get_cli_actor(),
                today=today,
            )
        except ValueError as exc:
            msg = str(exc)
            if msg == "cannot reactivate a revoked key":
                render_error(
                    f"Key is revoked: {_truncate_ident(key_prefix)}",
                    _REACTIVATE_REVOKED_HINT,
                )
                raise typer.Exit(code=3) from None
            if msg == "already active":
                render_error(
                    f"Key already active: {_truncate_ident(key_prefix)}",
                    _REACTIVATE_ALREADY_HINT,
                )
                raise typer.Exit(code=3) from None
            raise
        except sqlite3.Error as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None
        except RuntimeError as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()

    # Explicit check (not ``assert``) so ``python -O`` cannot strip it.
    if result is None:
        render_error(
            "Database error",
            "Key vanished between resolve and reactivate; retry the command.",
        )
        raise typer.Exit(code=5)

    # 5. Structured INFO log.
    with contextlib.suppress(Exception):
        _logger.info(
            "Reactivated | id=%s | key_prefix=%s",
            result.key.id,
            result.key.key_prefix,
        )

    # 6. ConfirmationLine (UX-DR7) — bare form.
    render_confirmation(
        f"Reactivated: {result.key.key_prefix} ({result.key.customer_name})"
    )
