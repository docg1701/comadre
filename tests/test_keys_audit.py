"""Tests for ``comadre.keys.audit`` — actor + log_event security guards.

Lean by design (test-suite review 2026-04-25): kept the security
contract (forbidden-keys guard catches PII at top level + nested) and
the caller-owned transaction invariant.
"""

from __future__ import annotations

import re
import sqlite3

import pytest

from comadre.keys.audit import get_cli_actor, log_event


@pytest.fixture()
def conn() -> sqlite3.Connection:
    c = sqlite3.connect(":memory:")
    c.row_factory = sqlite3.Row
    c.execute(
        "CREATE TABLE audit_log ("
        "id INTEGER PRIMARY KEY AUTOINCREMENT, "
        "occurred_at TEXT NOT NULL, "
        "actor TEXT NOT NULL, "
        "action TEXT NOT NULL, "
        "target_type TEXT, "
        "target_id TEXT, "
        "details_json TEXT)"
    )
    c.commit()
    return c


def test_get_cli_actor_always_returns_cli_prefixed_string() -> None:
    """``cli:<user>`` is the contract; never empty, never 'cli:None'."""
    actor = get_cli_actor()
    assert actor.startswith("cli:")
    assert actor not in {"cli:", "cli:None"}


def test_log_event_writes_iso_utc_row_with_sorted_details(
    conn: sqlite3.Connection,
) -> None:
    """Happy path: ISO-UTC stamp, sorted JSON keys, all columns wired."""
    log_event(
        conn,
        actor="cli:alice",
        action="create_customer",
        target_type="customer",
        target_id="cust_abc",
        details={"zeta": 1, "alpha": 2, "tax_id_kind": "cpf"},
    )
    row = conn.execute("SELECT * FROM audit_log").fetchone()
    assert row["actor"] == "cli:alice"
    assert row["action"] == "create_customer"
    assert row["target_id"] == "cust_abc"
    # ISO UTC + Z.
    assert re.match(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", row["occurred_at"])
    # Keys sorted alphabetically (deterministic for grep + diff).
    assert row["details_json"] == '{"alpha": 2, "tax_id_kind": "cpf", "zeta": 1}'


@pytest.mark.parametrize(
    "forbidden",
    ["cpf", "CPF", "cnpj", "tax_id", "name", "email", "key_plaintext", "Authorization"],
)
def test_log_event_forbidden_keys_raise_value_error(
    conn: sqlite3.Connection, forbidden: str
) -> None:
    """LGPD: forbidden keys at any nesting level → ValueError. Case-
    insensitive. Uses ValueError (not assert) so guard survives ``-O``."""
    # Top-level.
    with pytest.raises(ValueError, match="forbidden personal data"):
        log_event(
            conn,
            actor="cli:x",
            action="x",
            target_type=None,
            target_id=None,
            details={forbidden: "secret"},
        )
    # Nested.
    with pytest.raises(ValueError, match="forbidden personal data"):
        log_event(
            conn,
            actor="cli:x",
            action="x",
            target_type=None,
            target_id=None,
            details={"outer": {"inner": {forbidden: "secret"}}},
        )


def test_log_event_does_not_commit_caller_owns_the_transaction(
    conn: sqlite3.Connection,
) -> None:
    """log_event must NOT commit. Callers compose it inside ``with conn:``
    blocks for atomic multi-row writes — auto-commit would break that."""
    conn.isolation_level = "DEFERRED"
    log_event(
        conn,
        actor="cli:x",
        action="x",
        target_type=None,
        target_id=None,
        details=None,
    )
    conn.rollback()
    assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0


def test_log_event_details_none_writes_null_not_empty_string(
    conn: sqlite3.Connection,
) -> None:
    """``details=None`` must land as SQL NULL, not the string ``"null"``."""
    log_event(
        conn,
        actor="cli:x",
        action="x",
        target_type=None,
        target_id=None,
        details=None,
    )
    row = conn.execute("SELECT details_json FROM audit_log").fetchone()
    assert row["details_json"] is None
