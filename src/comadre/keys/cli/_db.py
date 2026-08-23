"""Shared registry-connection lifecycle for ``comadre-keys`` commands.

Every verb opens the registry, applies migrations, runs, and closes.
This contextmanager centralises that sequence so each command keeps only
its own business error mapping: connection/migration failures render the
standard Database-error panel and exit 5; exceptions raised inside the
``with`` body propagate after the connection closes.
"""

from __future__ import annotations

import contextlib
import sqlite3
from collections.abc import Iterator
from typing import TYPE_CHECKING

import typer

from comadre.keys.cli.output import render_error
from comadre.keys.db import _apply_migrations, get_connection

if TYPE_CHECKING:
    from comadre.config import RegistrySettings


@contextlib.contextmanager
def open_registry(settings: RegistrySettings) -> Iterator[sqlite3.Connection]:
    """Yield an open, migrated registry connection; guarantee close."""
    try:
        conn = get_connection(settings.key_registry_db_path)
    except (sqlite3.Error, OSError, RuntimeError) as exc:
        render_error("Database error", str(exc))
        raise typer.Exit(code=5) from None
    try:
        try:
            _apply_migrations(conn)
        except (sqlite3.Error, OSError, RuntimeError) as exc:
            render_error("Database error", str(exc))
            raise typer.Exit(code=5) from None
        yield conn
    finally:
        with contextlib.suppress(sqlite3.Error):
            conn.close()
