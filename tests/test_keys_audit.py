"""Tests for comadre.keys.audit."""

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


ISO_UTC_RE = re.compile(r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$")


class TestGetCliActor:
    def test_returns_cli_prefixed_string(self) -> None:
        actor = get_cli_actor()
        assert actor.startswith("cli:")

    def test_fallback_to_unknown(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("os.getlogin", lambda: (_ for _ in ()).throw(OSError))
        monkeypatch.setattr("getpass.getuser", lambda: (_ for _ in ()).throw(OSError))
        assert get_cli_actor() == "cli:unknown"

    def test_never_returns_none_like(self) -> None:
        actor = get_cli_actor()
        assert actor not in {"cli:", "cli:None"}


class TestLogEvent:
    def test_insert_happy_path(self, conn: sqlite3.Connection) -> None:
        log_event(
            conn,
            actor="cli:alice",
            action="create_customer",
            target_type="customer",
            target_id="cust_abc",
            details={"tax_id_kind": "cpf"},
        )
        row = conn.execute("SELECT * FROM audit_log").fetchone()
        assert row["actor"] == "cli:alice"
        assert row["action"] == "create_customer"
        assert row["target_type"] == "customer"
        assert row["target_id"] == "cust_abc"
        assert row["details_json"] == '{"tax_id_kind": "cpf"}'
        assert ISO_UTC_RE.match(row["occurred_at"])

    def test_details_none_writes_null(self, conn: sqlite3.Connection) -> None:
        conn.row_factory = sqlite3.Row
        log_event(
            conn,
            actor="cli:alice",
            action="system_event",
            target_type=None,
            target_id=None,
            details=None,
        )
        row = conn.execute("SELECT details_json FROM audit_log").fetchone()
        assert row["details_json"] is None

    @pytest.mark.parametrize(
        "forbidden",
        [
            "cpf",
            "CPF",  # case-insensitivity guard
            "cnpj",
            "tax_id",
            "Tax_Id",
            "name",
            "email",
            "Email",
            "key_plaintext",
            "Authorization",
            "authorization",
        ],
    )
    def test_forbidden_keys_raise(
        self, conn: sqlite3.Connection, forbidden: str
    ) -> None:
        # ValueError (not AssertionError) so the guard survives `python -O`.
        with pytest.raises(ValueError, match="forbidden personal data"):
            log_event(
                conn,
                actor="cli:alice",
                action="create_customer",
                target_type="customer",
                target_id="cust_abc",
                details={forbidden: "sensitive"},
            )

    def test_forbidden_keys_raise_when_nested(self, conn: sqlite3.Connection) -> None:
        """A forbidden key buried inside a nested dict must still be rejected."""
        with pytest.raises(ValueError, match="forbidden personal data"):
            log_event(
                conn,
                actor="cli:alice",
                action="create_customer",
                target_type="customer",
                target_id="cust_abc",
                details={"metadata": {"nested": {"cpf": "12345678909"}}},
            )

    def test_details_are_sorted(self, conn: sqlite3.Connection) -> None:
        log_event(
            conn,
            actor="cli:alice",
            action="something",
            target_type=None,
            target_id=None,
            details={"zeta": 1, "alpha": 2},
        )
        row = conn.execute("SELECT details_json FROM audit_log").fetchone()
        assert row["details_json"] == '{"alpha": 2, "zeta": 1}'

    def test_no_inner_transaction(self, conn: sqlite3.Connection) -> None:
        """log_event must not commit on its own — callers own the transaction."""
        conn.isolation_level = "DEFERRED"  # ensures no implicit commit from INSERT
        log_event(
            conn,
            actor="cli:alice",
            action="x",
            target_type=None,
            target_id=None,
            details=None,
        )
        conn.rollback()
        count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        assert count == 0

    def test_mark_paid_details_shape_roundtrips(self, conn: sqlite3.Connection) -> None:
        """Story 3.1 — the new ``mark_paid`` details_json shape passes the guard.

        ``{"paid_until": "...", "reactivated": <bool>}`` contains no forbidden
        keys and should round-trip unchanged. Sort-keys ordering places
        ``paid_until`` before ``reactivated`` alphabetically.
        """
        log_event(
            conn,
            actor="cli:alice",
            action="mark_paid",
            target_type="api_key",
            target_id="key_01abcde",
            details={"paid_until": "2026-06-05", "reactivated": False},
        )
        row = conn.execute("SELECT details_json FROM audit_log").fetchone()
        assert (
            row["details_json"] == '{"paid_until": "2026-06-05", "reactivated": false}'
        )

        log_event(
            conn,
            actor="cli:alice",
            action="mark_paid",
            target_type="api_key",
            target_id="key_01abcde",
            details={"paid_until": "2026-06-05", "reactivated": True},
        )
        rows = conn.execute(
            "SELECT details_json FROM audit_log ORDER BY id DESC LIMIT 1"
        ).fetchone()
        assert (
            rows["details_json"] == '{"paid_until": "2026-06-05", "reactivated": true}'
        )
