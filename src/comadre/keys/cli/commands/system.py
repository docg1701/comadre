"""`comadre-keys cache-status` — read-only auth-cache observability.

Story 2.3 (FR45). Single command today; Story 3.4 (``health``) and
Story 4.2 (``rotate-encryption-key``) will land additional subcommands
here — creating the module early means those stories add handlers, not
bootstrap.

Exit-code contract (UX-DR10, matches sibling command modules):
  0 — success (including "no running API instance", which is a valid
      operational state and not an error)
  2 — usage error (bad ``--format``)
  6 — permission / configuration error (missing encryption key or
      invalid ``BILLING_TIMEZONE``)
"""

from __future__ import annotations

from typing import Any
from zoneinfo import ZoneInfo, ZoneInfoNotFoundError

import typer
from pydantic import ValidationError

from comadre.config import get_settings
from comadre.counters import (
    WINDOW_SECONDS,
    aggregate_cache_status,
    read_all_snapshots,
)
from comadre.keys.cli._errors import first_error_msg, is_missing_encryption_key
from comadre.keys.cli.output import (
    CACHE_STATUS_BOUND_MESSAGE,
    LIST_FORMAT_CHOICES,
    render_cache_status,
    render_error,
    stdout_console,
)
from comadre.logging import get_logger

_logger = get_logger("keys.cli")

app = typer.Typer(help="System observability commands.", no_args_is_help=True)

_MISSING_KEY_HINT = (
    "Generate one with: python -c 'from cryptography.fernet import "
    "Fernet; print(Fernet.generate_key().decode())' and add it to "
    ".env. Restart the service if monetization is enabled there too."
)

_CACHE_TTL_SECONDS = WINDOW_SECONDS


@app.command("cache-status")
def cache_status_cmd(
    format: str = typer.Option(
        "table",
        "--format",
        help=(
            "Output format: table (default, human-readable) or json. "
            "Example: --format json."
        ),
    ),
) -> None:
    """Report the auth-cache propagation bound + optional live telemetry.

    Example: comadre-keys cache-status --format json
    """
    # 1. Literal flag validation.
    if format not in LIST_FORMAT_CHOICES:
        render_error(
            "Usage error: --format must be table or json",
            "Valid values: table, json.",
        )
        raise typer.Exit(code=2)

    # 2. Settings + tz validation (exit 6). Even though this command does
    # not touch the DB, the encryption-key presence check keeps the error
    # surface consistent across every ``comadre-keys`` verb — operators
    # don't have to remember which commands require which env vars.
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
        ZoneInfo(settings.billing_timezone)
    except (ZoneInfoNotFoundError, ValueError):
        render_error(
            "Configuration error: BILLING_TIMEZONE is not a valid IANA timezone",
            f"Set BILLING_TIMEZONE to a valid zone (e.g., America/Sao_Paulo). "
            f"Got: {settings.billing_timezone}",
        )
        raise typer.Exit(code=6) from None

    # 3. Read every per-replica snapshot and aggregate. ``read_all_snapshots``
    # globs ``{db_path}.counters.*.json`` so a multi-replica deployment
    # produces a single unified view rather than showing whichever replica
    # wrote last. An absent-file and a parse-error both degrade to "this
    # replica not reporting" without raising.
    snapshots = read_all_snapshots(settings.key_registry_db_path)
    status = aggregate_cache_status(snapshots)

    _logger.info(
        "Cache-status inspected | replicas=%d | entries=%s | freshest_age_s=%s",
        status.replicas if status is not None else 0,
        status.entries if status is not None else None,
        status.snapshot_age_seconds if status is not None else None,
    )

    # 4. Render branch. JSON always carries ``ttl_seconds`` + the verbatim
    # propagation_bound_message (AC9, AC10); table defers to the helper.
    if format == "json":
        payload: dict[str, Any] = {
            "ttl_seconds": _CACHE_TTL_SECONDS,
            "propagation_bound_message": CACHE_STATUS_BOUND_MESSAGE,
            "snapshot_available": status is not None,
        }
        if status is not None:
            payload.update(
                {
                    "replicas": status.replicas,
                    "snapshot_age_seconds": status.snapshot_age_seconds,
                    "entries": status.entries,
                    "maxsize_per_replica": status.maxsize_per_replica,
                    "hits": status.hits,
                    "misses": status.misses,
                    "hit_rate": status.hit_rate,
                    "process_uptime_seconds": status.process_uptime_seconds,
                }
            )
        stdout_console().print_json(data=payload)
        return

    render_cache_status(status)
