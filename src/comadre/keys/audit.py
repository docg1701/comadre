"""Append-only audit log writer.

`log_event` writes a single `audit_log` row using the caller-supplied
connection. Callers MUST open the surrounding transaction (e.g., via
`insert_customer`) so the business mutation and its audit row either both
commit or both roll back.

FR30 defense-in-depth: `details` must not carry personal data. A blocklist
raises `ValueError` if a forbidden key slips through — never `assert`, which
Python strips under `-O` / `PYTHONOPTIMIZE=1`. The check is case-insensitive
and walks nested dicts so `{"meta": {"CPF": "..."}}` still fails.
"""

from __future__ import annotations

import getpass
import json
import os
import sqlite3
from collections.abc import Mapping
from datetime import UTC, datetime

_FORBIDDEN_DETAIL_KEYS = frozenset(
    {
        "cpf",
        "cnpj",
        "tax_id",
        "name",
        "email",
        "key_plaintext",
        "authorization",
    }
)


def _assert_no_forbidden_keys(payload: Mapping[str, object]) -> None:
    for key, value in payload.items():
        if key.lower() in _FORBIDDEN_DETAIL_KEYS:
            raise ValueError(
                f"audit details contain forbidden personal data key: {key!r}"
            )
        if isinstance(value, Mapping):
            _assert_no_forbidden_keys(value)


def _utcnow_iso() -> str:
    return datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%SZ")


def get_cli_actor() -> str:
    """Return `cli:<username>` with fallbacks to getpass then `cli:unknown`."""
    try:
        username = os.getlogin()
    except OSError:
        username = ""
    if not username:
        try:
            username = getpass.getuser()
        except (OSError, KeyError):
            username = ""
    return f"cli:{username or 'unknown'}"


def log_event(
    conn: sqlite3.Connection,
    *,
    actor: str,
    action: str,
    target_type: str | None,
    target_id: str | None,
    details: dict[str, object] | None = None,
    occurred_at: str | None = None,
) -> None:
    """Append one row to `audit_log` using the caller's transaction.

    `details` is serialized with `sort_keys=True` for deterministic test
    assertions. Forbidden keys (case-insensitive, including nested dicts)
    raise `ValueError` — callers should never pass them.

    `occurred_at` lets callers pin the timestamp string rather than letting
    the helper sample the clock. The suspension sweep (Story 3.3) pins it so
    the returned `completed_at` has byte-identity with the summary row's
    `occurred_at` (AC3). All other call sites pass `None` and accept the
    helper's `_utcnow_iso()` default.
    """
    details_json: str | None
    if details is None:
        details_json = None
    else:
        _assert_no_forbidden_keys(details)
        details_json = json.dumps(details, ensure_ascii=False, sort_keys=True)

    conn.execute(
        "INSERT INTO audit_log ("
        "occurred_at, actor, action, target_type, target_id, details_json"
        ") VALUES (?, ?, ?, ?, ?, ?)",
        (
            occurred_at if occurred_at is not None else _utcnow_iso(),
            actor,
            action,
            target_type,
            target_id,
            details_json,
        ),
    )
