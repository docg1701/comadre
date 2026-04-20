"""End-to-end CLI tests for ``comadre-keys delete-customer`` (Story 4.1)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from rich.console import Console
from typer.testing import CliRunner

import comadre.keys.cli.output as output_mod
from comadre.config import get_settings
from comadre.keys.cli.app import app
from comadre.keys.db import (
    _apply_migrations,
    generate_customer_id,
    generate_key_id,
    get_connection,
    insert_api_key,
    insert_customer,
)
from comadre.keys.models import ApiKeyRecord, CustomerRecord

runner = CliRunner()


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> Iterator[None]:
    get_settings.cache_clear()
    yield
    get_settings.cache_clear()


@pytest.fixture(autouse=True)
def _reset_consoles_to_buffers() -> Iterator[tuple[StringIO, StringIO]]:
    stdout_buf = StringIO()
    stderr_buf = StringIO()
    output_mod._reset_for_tests()
    output_mod._stdout_console = Console(
        file=stdout_buf, force_terminal=False, no_color=True, width=120
    )
    output_mod._stderr_console = Console(
        file=stderr_buf, force_terminal=False, no_color=True, width=120
    )
    yield stdout_buf, stderr_buf
    output_mod._reset_for_tests()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    key = Fernet.generate_key().decode()
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", key)
    return {"db_path": str(db_path), "key": key}


def _buffers() -> tuple[str, str]:
    stdout_file = output_mod._stdout_console.file  # type: ignore[union-attr]
    stderr_file = output_mod._stderr_console.file  # type: ignore[union-attr]
    return stdout_file.getvalue(), stderr_file.getvalue()


def _clear_buffers() -> None:
    for attr in ("_stdout_console", "_stderr_console"):
        console = getattr(output_mod, attr)
        console.file.seek(0)  # type: ignore[union-attr]
        console.file.truncate()  # type: ignore[union-attr]


def _seed_customer(
    db_path: str,
    *,
    name: str = "Marcos Silva",
    email: str = "marcos@example.com",
) -> str:
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        cid = generate_customer_id()
        insert_customer(
            conn,
            CustomerRecord(
                id=cid,
                name=name,
                email=email,
                tax_id_kind="cpf",
                tax_id_encrypted=b"gAAAAA-ciphertext",
                notes="",
                registered_at=datetime(2026, 3, 12, 14, 22, 5, tzinfo=UTC),
                deleted_at=None,
            ),
            actor="cli:tester",
        )
        return cid
    finally:
        conn.close()


def _seed_key(
    db_path: str,
    cid: str,
    *,
    key_prefix: str = "Pq_abc12",
    key_hash: str = "a" * 64,
    status: str = "active",
) -> str:
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        kid = generate_key_id()
        insert_api_key(
            conn,
            ApiKeyRecord(
                id=kid,
                customer_id=cid,
                key_hash=key_hash,
                key_prefix=key_prefix,
                rate_limit_rpm=60,
                status=status,  # type: ignore[arg-type]
                billing_mode="manual",
                price_monthly=149.0,
                paid_until=None,
                created_at=datetime(2026, 3, 20, 10, 0, 0, tzinfo=UTC),
                last_used_at=None,
                notes="",
            ),
            actor="cli:tester",
        )
        return kid
    finally:
        conn.close()


def _customer_row(db_path: str, cid: str) -> sqlite3.Row | None:
    raw = sqlite3.connect(db_path)
    try:
        raw.row_factory = sqlite3.Row
        return raw.execute(
            "SELECT id, name, email, tax_id_encrypted, notes, deleted_at "
            "FROM customer WHERE id = ?",
            (cid,),
        ).fetchone()
    finally:
        raw.close()


def _api_key_count(db_path: str, cid: str) -> int:
    raw = sqlite3.connect(db_path)
    try:
        return int(
            raw.execute(
                "SELECT COUNT(*) FROM api_key WHERE customer_id = ?", (cid,)
            ).fetchone()[0]
        )
    finally:
        raw.close()


def _audit_rows(db_path: str, target_id: str) -> list[sqlite3.Row]:
    raw = sqlite3.connect(db_path)
    try:
        raw.row_factory = sqlite3.Row
        return list(
            raw.execute(
                "SELECT id, action, target_type, target_id, actor, details_json "
                "FROM audit_log WHERE target_id = ? ORDER BY id ASC",
                (target_id,),
            ).fetchall()
        )
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# AC7 / AC11 — happy paths with interactive confirmation / --yes.
# ---------------------------------------------------------------------------


class TestDeleteCustomerHappyPath:
    def test_interactive_y_purges(self, env: dict[str, str]) -> None:
        cid = _seed_customer(env["db_path"])
        _seed_key(env["db_path"], cid, key_prefix="Pq_abc12", key_hash="a" * 64)
        _seed_key(env["db_path"], cid, key_prefix="Pq_def34", key_hash="b" * 64)

        _clear_buffers()
        result = runner.invoke(
            app,
            ["delete-customer", cid, "--hard"],
            input="y\n",
        )
        stdout, _ = _buffers()
        assert result.exit_code == 0
        # Prompt text on stderr (child-level, via typer.confirm err=True).
        prompt = (
            "This will permanently delete customer Marcos Silva and all "
            "associated keys (2 key(s))."
        )
        assert prompt in result.stderr
        # ConfirmationLine on stdout.
        assert f"Deleted: {cid} (Marcos Silva) \u2014 2 keys purged" in stdout

        # DB state: customer tombstoned, keys gone, audit row present.
        row = _customer_row(env["db_path"], cid)
        assert row is not None
        assert row["name"] == ""
        assert row["email"] == ""
        assert row["tax_id_encrypted"] == b""
        assert row["notes"] == ""
        assert row["deleted_at"] is not None

        assert _api_key_count(env["db_path"], cid) == 0

        audit = _audit_rows(env["db_path"], cid)
        delete_rows = [r for r in audit if r["action"] == "delete_customer"]
        assert len(delete_rows) == 1
        details = json.loads(str(delete_rows[0]["details_json"]))
        assert details == {"keys_purged": 2, "tax_id_kind": "cpf"}

    def test_yes_flag_skips_prompt(self, env: dict[str, str]) -> None:
        cid = _seed_customer(env["db_path"])
        _seed_key(env["db_path"], cid)
        _clear_buffers()
        result = runner.invoke(app, ["delete-customer", cid, "--hard", "--yes"])
        stdout, _ = _buffers()
        assert result.exit_code == 0
        assert f"Deleted: {cid}" in stdout
        assert "1 keys purged" in stdout
        # No prompt text leaked anywhere.
        assert "This will permanently delete" not in result.stderr
        assert _api_key_count(env["db_path"], cid) == 0

    def test_zero_keys_still_tombstones(self, env: dict[str, str]) -> None:
        cid = _seed_customer(env["db_path"])
        _clear_buffers()
        result = runner.invoke(app, ["delete-customer", cid, "--hard", "--yes"])
        stdout, _ = _buffers()
        assert result.exit_code == 0
        assert "0 keys purged" in stdout
        row = _customer_row(env["db_path"], cid)
        assert row is not None
        assert row["deleted_at"] is not None

        audit = _audit_rows(env["db_path"], cid)
        delete_rows = [r for r in audit if r["action"] == "delete_customer"]
        details = json.loads(str(delete_rows[0]["details_json"]))
        assert details == {"keys_purged": 0, "tax_id_kind": "cpf"}


# ---------------------------------------------------------------------------
# AC8 — interactive abort.
# ---------------------------------------------------------------------------


class TestDeleteCustomerAbort:
    def test_interactive_n_aborts_without_mutation(self, env: dict[str, str]) -> None:
        cid = _seed_customer(env["db_path"])
        _seed_key(env["db_path"], cid)
        before_keys = _api_key_count(env["db_path"], cid)

        _clear_buffers()
        result = runner.invoke(app, ["delete-customer", cid, "--hard"], input="n\n")
        _, stderr = _buffers()
        assert result.exit_code == 2
        assert "Aborted." in stderr

        row = _customer_row(env["db_path"], cid)
        assert row is not None
        assert row["name"] == "Marcos Silva"
        assert row["deleted_at"] is None
        assert _api_key_count(env["db_path"], cid) == before_keys

        # No delete_customer audit row added.
        audit = _audit_rows(env["db_path"], cid)
        assert [r for r in audit if r["action"] == "delete_customer"] == []

    def test_enter_without_typing_aborts(self, env: dict[str, str]) -> None:
        cid = _seed_customer(env["db_path"])
        _clear_buffers()
        result = runner.invoke(app, ["delete-customer", cid, "--hard"], input="\n")
        assert result.exit_code == 2
        row = _customer_row(env["db_path"], cid)
        assert row is not None
        assert row["deleted_at"] is None


# ---------------------------------------------------------------------------
# AC10 — --hard required.
# ---------------------------------------------------------------------------


class TestDeleteCustomerHardRequired:
    def test_missing_hard_flag_exits_2_before_any_db_work(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "registry.db"
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )
        cid = "cust_01hg7xyzxyzxyzxyzxyzxyzxyz"

        _clear_buffers()
        result = runner.invoke(app, ["delete-customer", cid])
        _, stderr = _buffers()
        assert result.exit_code == 2
        assert "--hard is required" in stderr
        # Pre-DB validation: the DB file was never created.
        assert not db_path.exists()

    def test_bad_customer_id_shape_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "nope.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )
        _clear_buffers()
        result = runner.invoke(
            app, ["delete-customer", "notavalidid", "--hard", "--yes"]
        )
        _, stderr = _buffers()
        assert result.exit_code == 2
        assert "invalid customer id" in stderr


# ---------------------------------------------------------------------------
# AC12 / AC13 — not-found before prompt; tombstoned opaque.
# ---------------------------------------------------------------------------


class TestDeleteCustomerNotFound:
    def test_missing_customer_exits_3_before_prompt(self, env: dict[str, str]) -> None:
        _seed_customer(env["db_path"])  # initializes DB
        missing = "cust_01hg7zzzzzzzzzzzzzzzzzzzzz"
        _clear_buffers()
        result = runner.invoke(app, ["delete-customer", missing, "--hard"])
        stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "not found" in stderr.lower()
        # No prompt text should appear on any stream.
        assert "This will permanently delete" not in stderr
        assert "This will permanently delete" not in stdout

    def test_tombstoned_customer_exits_3(self, env: dict[str, str]) -> None:
        cid = _seed_customer(env["db_path"])
        raw = sqlite3.connect(env["db_path"])
        try:
            raw.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-20T00:00:00Z", cid),
            )
            raw.commit()
        finally:
            raw.close()

        _clear_buffers()
        result = runner.invoke(app, ["delete-customer", cid, "--hard", "--yes"])
        _, stderr = _buffers()
        assert result.exit_code == 3
        assert "not found" in stderr.lower()

        # No second delete_customer audit row.
        audit = _audit_rows(env["db_path"], cid)
        delete_rows = [r for r in audit if r["action"] == "delete_customer"]
        assert delete_rows == []


# ---------------------------------------------------------------------------
# AC14 / AC19 — audit retention + list-customers --deleted visibility.
# ---------------------------------------------------------------------------


class TestDeleteCustomerAuditAndListing:
    def test_preexisting_audit_rows_survive(self, env: dict[str, str]) -> None:
        cid = _seed_customer(env["db_path"])
        kid = _seed_key(env["db_path"], cid)

        # Baseline audit rows exist (create_customer, issue_key).
        before = _audit_rows(env["db_path"], cid)
        before_key_audit = _audit_rows(env["db_path"], kid)
        assert any(r["action"] == "create_customer" for r in before)
        assert any(r["action"] == "issue_key" for r in before_key_audit)

        runner.invoke(app, ["delete-customer", cid, "--hard", "--yes"])

        after = _audit_rows(env["db_path"], cid)
        after_key_audit = _audit_rows(env["db_path"], kid)
        # Previous rows are still there.
        action_names_after = {r["action"] for r in after}
        assert "create_customer" in action_names_after
        assert "delete_customer" in action_names_after
        # The key's issue_key audit row remains even though the api_key row
        # itself was DELETEd — FR38 retention.
        assert any(r["action"] == "issue_key" for r in after_key_audit)

    def test_list_customers_deleted_surfaces_tombstone(
        self, env: dict[str, str]
    ) -> None:
        cid = _seed_customer(env["db_path"])
        runner.invoke(app, ["delete-customer", cid, "--hard", "--yes"])
        _clear_buffers()
        result = runner.invoke(app, ["list-customers", "--deleted", "--format", "json"])
        stdout, _ = _buffers()
        assert result.exit_code == 0
        payload = json.loads(stdout)
        matching = [r for r in payload if r["id"] == cid]
        assert len(matching) == 1
        assert matching[0]["name"] == ""
        assert matching[0]["email"] == ""
        assert matching[0]["key_count"] == 0

    def test_list_customers_without_deleted_omits_tombstone(
        self, env: dict[str, str]
    ) -> None:
        cid = _seed_customer(env["db_path"])
        runner.invoke(app, ["delete-customer", cid, "--hard", "--yes"])
        _clear_buffers()
        result = runner.invoke(app, ["list-customers", "--format", "json"])
        stdout, _ = _buffers()
        assert result.exit_code == 0
        payload = json.loads(stdout)
        assert all(r["id"] != cid for r in payload)


# ---------------------------------------------------------------------------
# AC15 — PII-austere INFO log.
# ---------------------------------------------------------------------------


class TestDeleteCustomerLogging:
    def test_log_contains_no_pii(self, env: dict[str, str]) -> None:
        from comadre.logging import get_logger

        cid = _seed_customer(env["db_path"])
        _seed_key(env["db_path"], cid)

        logger = get_logger("keys.cli")
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture(level=logging.INFO)
        logger.addHandler(handler)
        try:
            _clear_buffers()
            records.clear()
            result = runner.invoke(app, ["delete-customer", cid, "--hard", "--yes"])
        finally:
            logger.removeHandler(handler)

        assert result.exit_code == 0
        joined = "\n".join(r.getMessage() for r in records)
        assert "Customer purged" in joined
        assert f"id={cid}" in joined
        assert "keys_purged=1" in joined
        # PII must NOT appear.
        assert "Marcos Silva" not in joined
        assert "marcos@example.com" not in joined


# ---------------------------------------------------------------------------
# AC20 — --help surface.
# ---------------------------------------------------------------------------


class TestDeleteCustomerHelp:
    def test_help_includes_example(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KEY_REGISTRY_DB_PATH", raising=False)
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        result = runner.invoke(app, ["delete-customer", "--help"])
        assert result.exit_code == 0
        ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        cleaned = ansi.sub("", result.stdout)
        for glyph in ("\u2502", "\u256d", "\u256e", "\u2570", "\u256f", "\u2500"):
            cleaned = cleaned.replace(glyph, " ")
        flat = re.sub(r"\s+", " ", cleaned)
        assert "cust_01j8xr3e4c5m7kn9p2qt8vwy" in flat
        assert "--hard" in flat
        assert "--yes" in flat

    def test_format_flag_is_not_accepted(self, env: dict[str, str]) -> None:
        cid = _seed_customer(env["db_path"])
        _clear_buffers()
        result = runner.invoke(
            app,
            ["delete-customer", cid, "--hard", "--yes", "--format", "json"],
        )
        # Typer rejects unknown --format option with exit code 2.
        assert result.exit_code == 2
