"""End-to-end CLI tests for ``comadre-keys update-customer`` (Story 1.5)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Callable, Iterator
from datetime import date
from io import StringIO
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from rich.console import Console
from typer.testing import CliRunner

import comadre.keys.cli.commands.customers as customers_cmd
import comadre.keys.cli.output as output_mod
from comadre.config import get_settings
from comadre.keys.cli.app import app

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
    monkeypatch.setenv("API_KEY", "test-api-key")
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
    env: dict[str, str],
    *,
    name: str = "Helena Ribeiro",
    email: str = "helena@clinica.com",
    cpf: str = "123.456.789-09",
    notes: str | None = None,
) -> str:
    args = [
        "create-customer",
        "--name",
        name,
        "--email",
        email,
        "--cpf",
        cpf,
    ]
    if notes is not None:
        args.extend(["--notes", notes])
    _clear_buffers()
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    stdout, _stderr = _buffers()
    match = re.search(r"cust_[0-9a-z]{26}", stdout)
    assert match is not None, stdout
    _clear_buffers()
    return match.group(0)


def _count(env: dict[str, str], table: str) -> int:
    conn = sqlite3.connect(env["db_path"])
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def _fetch_customer(env: dict[str, str], cid: str) -> dict[str, object]:
    conn = sqlite3.connect(env["db_path"])
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT email, notes, deleted_at FROM customer WHERE id = ?",
            (cid,),
        ).fetchone()
        assert row is not None
        return {
            "email": row["email"],
            "notes": row["notes"] or "",
            "deleted_at": row["deleted_at"],
        }
    finally:
        conn.close()


def _latest_update_audit(env: dict[str, str]) -> dict[str, object] | None:
    conn = sqlite3.connect(env["db_path"])
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT actor, action, target_type, target_id, details_json "
            "FROM audit_log WHERE action = 'update_customer' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        if row is None:
            return None
        return dict(row)
    finally:
        conn.close()


def _count_update_audits(env: dict[str, str]) -> int:
    conn = sqlite3.connect(env["db_path"])
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'update_customer'"
            ).fetchone()[0]
        )
    finally:
        conn.close()


@pytest.fixture()
def freeze_today(
    monkeypatch: pytest.MonkeyPatch,
) -> Callable[[date], None]:
    """Return a closure that freezes ``_resolve_today_in_tz`` on demand."""

    def _factory(frozen: date) -> None:
        monkeypatch.setattr(customers_cmd, "_resolve_today_in_tz", lambda _tz: frozen)

    return _factory


# ---------------------------------------------------------------------------
# AC1 — email-only happy path.
# ---------------------------------------------------------------------------


class TestUpdateCustomerEmailOnly:
    def test_email_only(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
    ) -> None:
        freeze_today(date(2026, 4, 20))
        cid = _seed_customer(env, notes="5 bots, WhatsApp booking")
        before = _fetch_customer(env, cid)

        result = runner.invoke(
            app, ["update-customer", cid, "--email", "helena@novaclinica.com"]
        )
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr

        after = _fetch_customer(env, cid)
        assert after["email"] == "helena@novaclinica.com"
        assert after["notes"] == before["notes"]
        assert after["deleted_at"] is None

        assert f"Updated: {cid} (Helena Ribeiro) \u2014 email changed" in stdout
        # Single-line output — no Panel border characters on stdout.
        assert "\u256d" not in stdout and "\u2570" not in stdout

        audit = _latest_update_audit(env)
        assert audit is not None
        assert audit["action"] == "update_customer"
        assert audit["target_type"] == "customer"
        assert audit["target_id"] == cid
        assert audit["details_json"] == '{"fields": ["email"]}'


# ---------------------------------------------------------------------------
# AC2 — note append paths.
# ---------------------------------------------------------------------------


class TestUpdateCustomerAddNote:
    def test_stamps_date(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
    ) -> None:
        freeze_today(date(2026, 4, 20))
        cid = _seed_customer(env, notes="5 bots")

        result = runner.invoke(
            app,
            ["update-customer", cid, "--add-note", "paga tarde"],
        )
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr

        after = _fetch_customer(env, cid)
        assert after["notes"] == "5 bots\n[2026-04-20] paga tarde"
        assert after["email"] == "helena@clinica.com"

        assert f"Updated: {cid} (Helena Ribeiro) \u2014 note added" in stdout

        audit = _latest_update_audit(env)
        assert audit is not None
        assert audit["details_json"] == '{"fields": ["notes"]}'

    def test_second_append_stacks(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
    ) -> None:
        cid = _seed_customer(env, notes="5 bots")

        freeze_today(date(2026, 4, 20))
        r1 = runner.invoke(app, ["update-customer", cid, "--add-note", "paga tarde"])
        assert r1.exit_code == 0
        _clear_buffers()

        freeze_today(date(2026, 5, 12))
        r2 = runner.invoke(
            app,
            ["update-customer", cid, "--add-note", "upgraded 60→120rpm"],
        )
        assert r2.exit_code == 0

        after = _fetch_customer(env, cid)
        assert after["notes"] == (
            "5 bots\n[2026-04-20] paga tarde\n[2026-05-12] upgraded 60→120rpm"
        )
        assert _count_update_audits(env) == 2

    def test_on_empty_notes_no_leading_newline(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
    ) -> None:
        freeze_today(date(2026, 4, 20))
        cid = _seed_customer(env)
        # Force the seed's notes column back to "" in case create-customer
        # default changes in a future refactor.
        conn = sqlite3.connect(env["db_path"])
        try:
            conn.execute("UPDATE customer SET notes = '' WHERE id = ?", (cid,))
            conn.commit()
        finally:
            conn.close()

        result = runner.invoke(app, ["update-customer", cid, "--add-note", "first"])
        assert result.exit_code == 0

        after = _fetch_customer(env, cid)
        assert after["notes"] == "[2026-04-20] first"


# ---------------------------------------------------------------------------
# AC3 — combined email + note in one transaction.
# ---------------------------------------------------------------------------


class TestUpdateCustomerBothFlags:
    def test_both_flags(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
    ) -> None:
        freeze_today(date(2026, 4, 20))
        cid = _seed_customer(env, notes="seed")

        result = runner.invoke(
            app,
            [
                "update-customer",
                cid,
                "--email",
                "new@example.com",
                "--add-note",
                "bumped tier",
            ],
        )
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr

        after = _fetch_customer(env, cid)
        assert after["email"] == "new@example.com"
        assert after["notes"] == "seed\n[2026-04-20] bumped tier"

        audit = _latest_update_audit(env)
        assert audit is not None
        assert audit["details_json"] == '{"fields": ["email", "notes"]}'
        assert _count_update_audits(env) == 1

        assert (
            f"Updated: {cid} (Helena Ribeiro) \u2014 email changed, note added"
            in stdout
        )

    def test_rolls_back_when_log_event_fails(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        freeze_today(date(2026, 4, 20))
        cid = _seed_customer(env, notes="seed")
        before = _fetch_customer(env, cid)
        audit_before = _count_update_audits(env)

        import comadre.keys.audit as audit_module

        original_log_event = audit_module.log_event

        def _boom(*args: object, **kwargs: object) -> None:
            action = kwargs.get("action")
            if action == "update_customer":
                raise sqlite3.IntegrityError("forced audit failure")
            return original_log_event(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(audit_module, "log_event", _boom)

        result = runner.invoke(
            app,
            [
                "update-customer",
                cid,
                "--email",
                "rollback@example.com",
                "--add-note",
                "should-roll-back",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 5, stderr
        assert "Database error" in stderr

        after = _fetch_customer(env, cid)
        assert after["email"] == before["email"]
        assert after["notes"] == before["notes"]
        assert _count_update_audits(env) == audit_before

    def test_runtime_error_from_helper_maps_to_exit_5(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Simulates the defensive "row vanished after commit" branch in
        # ``update_customer`` (concurrent tombstone between commit and
        # post-commit re-read). Before the patch, ``RuntimeError`` escaped
        # the CLI's ``except sqlite3.Error`` and Typer/Click mapped it to
        # exit 1. Now it must surface as a structured Database error at
        # exit 5 per UX-DR10.
        import comadre.keys.cli.commands.customers as customers_cmd

        freeze_today(date(2026, 4, 20))
        cid = _seed_customer(env, notes="seed")

        def _boom(*_args: object, **_kwargs: object) -> None:
            raise RuntimeError(
                f"update_customer: row vanished after commit for {cid!r}"
            )

        monkeypatch.setattr(customers_cmd, "update_customer", _boom)

        _clear_buffers()
        result = runner.invoke(app, ["update-customer", cid, "--add-note", "anything"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 5, stderr
        assert "Database error" in stderr
        assert "row vanished" in stderr


# ---------------------------------------------------------------------------
# AC4 — missing / tombstoned customer → exit 3.
# ---------------------------------------------------------------------------


class TestUpdateCustomerNotFound:
    def test_missing_exits_3(self, env: dict[str, str]) -> None:
        # Ensure the DB file exists first (migrations applied) so we can
        # compare audit-row counts before/after.
        cid_real = _seed_customer(env)
        audit_before = _count_update_audits(env)
        missing = "cust_01nonexistent0000000000000"

        _clear_buffers()
        result = runner.invoke(app, ["update-customer", missing, "--add-note", "x"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert f"Customer not found: {missing}" in stderr
        assert "list-customers" in stderr

        assert _count_update_audits(env) == audit_before
        # The real customer is untouched.
        after = _fetch_customer(env, cid_real)
        assert after["email"] == "helena@clinica.com"

    def test_tombstone_treated_as_missing(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
    ) -> None:
        freeze_today(date(2026, 4, 20))
        cid = _seed_customer(env, notes="pre-tombstone")
        conn = sqlite3.connect(env["db_path"])
        try:
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-18T00:00:00Z", cid),
            )
            conn.commit()
        finally:
            conn.close()
        audit_before = _count_update_audits(env)

        _clear_buffers()
        result = runner.invoke(app, ["update-customer", cid, "--add-note", "attempt"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert f"Customer not found: {cid}" in stderr
        assert _count_update_audits(env) == audit_before

        after = _fetch_customer(env, cid)
        assert after["email"] == "helena@clinica.com"
        assert after["notes"] == "pre-tombstone"
        assert after["deleted_at"] == "2026-04-18T00:00:00Z"


# ---------------------------------------------------------------------------
# AC5 — usage errors (all exit 2 with DB untouched).
# ---------------------------------------------------------------------------


class TestUpdateCustomerUsageErrors:
    def test_without_flags_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Bare-minimum env — we want to prove the check runs before DB open.
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )

        result = runner.invoke(app, ["update-customer", "cust_does_not_matter"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert (
            "Usage error: at least one of --email or --add-note is required" in stderr
        )
        assert not (tmp_path / "registry.db").exists()

    def test_empty_email_exits_2(self, env: dict[str, str]) -> None:
        cid = _seed_customer(env)
        _clear_buffers()
        result = runner.invoke(app, ["update-customer", cid, "--email", ""])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: invalid email" in stderr

    def test_malformed_email_exits_2(self, env: dict[str, str]) -> None:
        cid = _seed_customer(env)
        _clear_buffers()
        result = runner.invoke(app, ["update-customer", cid, "--email", "not-an-email"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: invalid email" in stderr

    def test_whitespace_note_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )

        result = runner.invoke(app, ["update-customer", "cust_x", "--add-note", "   "])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --add-note must be non-empty" in stderr
        # Note-shape check fires before DB open.
        assert not (tmp_path / "registry.db").exists()

    def test_empty_note_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )

        result = runner.invoke(app, ["update-customer", "cust_x", "--add-note", ""])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --add-note must be non-empty" in stderr

    def test_nul_byte_note_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )

        result = runner.invoke(
            app, ["update-customer", "cust_x", "--add-note", "ok\x00danger"]
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --add-note contains illegal characters" in stderr
        assert "NUL" in stderr
        assert not (tmp_path / "registry.db").exists()

    def test_newline_note_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )

        result = runner.invoke(
            app,
            [
                "update-customer",
                "cust_x",
                "--add-note",
                "ok\n[2099-01-01] fake entry",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --add-note must be a single line" in stderr
        # Newline check fires before DB open — forgery vector never reaches
        # the storage layer.
        assert not (tmp_path / "registry.db").exists()

    def test_carriage_return_note_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )

        result = runner.invoke(app, ["update-customer", "cust_x", "--add-note", "a\rb"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --add-note must be a single line" in stderr
        assert not (tmp_path / "registry.db").exists()

    def test_note_strips_outer_not_inner(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
    ) -> None:
        freeze_today(date(2026, 4, 20))
        cid = _seed_customer(env, notes="")
        conn = sqlite3.connect(env["db_path"])
        try:
            conn.execute("UPDATE customer SET notes = '' WHERE id = ?", (cid,))
            conn.commit()
        finally:
            conn.close()

        result = runner.invoke(
            app,
            ["update-customer", cid, "--add-note", "  spaced  inside  "],
        )
        assert result.exit_code == 0
        after = _fetch_customer(env, cid)
        assert after["notes"] == "[2026-04-20] spaced  inside"

    def test_both_flags_note_invalid_no_email_change(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
    ) -> None:
        freeze_today(date(2026, 4, 20))
        cid = _seed_customer(env, notes="seed")
        before = _fetch_customer(env, cid)
        audit_before = _count_update_audits(env)

        _clear_buffers()
        result = runner.invoke(
            app,
            [
                "update-customer",
                cid,
                "--email",
                "ok@example.com",
                "--add-note",
                "   ",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --add-note must be non-empty" in stderr

        after = _fetch_customer(env, cid)
        assert after["email"] == before["email"]
        assert after["notes"] == before["notes"]
        assert _count_update_audits(env) == audit_before


# ---------------------------------------------------------------------------
# AC6 — read-after-write: `show` reflects changes.
# ---------------------------------------------------------------------------


class TestUpdateCustomerReadAfterWrite:
    def test_show_reflects_changes(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
    ) -> None:
        freeze_today(date(2026, 4, 20))
        cid = _seed_customer(env, notes="seed")

        r_upd = runner.invoke(
            app,
            [
                "update-customer",
                cid,
                "--email",
                "after@example.com",
                "--add-note",
                "follow-up",
            ],
        )
        assert r_upd.exit_code == 0
        _clear_buffers()

        r_show = runner.invoke(app, ["show", cid])
        stdout, _stderr = _buffers()
        assert r_show.exit_code == 0
        assert "after@example.com" in stdout
        assert "[2026-04-20] follow-up" in stdout


# ---------------------------------------------------------------------------
# AC7 — help surface (realistic examples, no DB access).
# ---------------------------------------------------------------------------


class TestUpdateCustomerHelp:
    def test_help_has_realistic_examples(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KEY_REGISTRY_DB_PATH", raising=False)
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)

        result = runner.invoke(app, ["update-customer", "--help"])
        assert result.exit_code == 0
        ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        cleaned = ansi.sub("", result.stdout)
        for glyph in ("\u2502", "\u256d", "\u256e", "\u2570", "\u256f", "\u2500"):
            cleaned = cleaned.replace(glyph, " ")
        flat = re.sub(r"\s+", " ", cleaned)

        assert "cust_01j8xr" in flat
        assert "helena@novaclinica.com" in flat
        assert "paga tarde" in flat
        assert "--email" in flat
        assert "--add-note" in flat
        assert "comadre-keys update-customer cust_01j8xr3e4c5m7kn9p2qt8vwy" in flat

    def test_help_does_not_touch_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KEY_REGISTRY_DB_PATH", raising=False)
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)

        result = runner.invoke(app, ["update-customer", "--help"])
        assert result.exit_code == 0
        assert not (tmp_path / "registry.db").exists()


# ---------------------------------------------------------------------------
# AC8 — log + audit sanitization.
# ---------------------------------------------------------------------------


class TestUpdateCustomerSanitization:
    def test_log_has_no_pii(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
    ) -> None:
        from comadre.logging import get_logger

        freeze_today(date(2026, 4, 20))
        cid = _seed_customer(env, notes="seed")

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
            result = runner.invoke(
                app,
                [
                    "update-customer",
                    cid,
                    "--email",
                    "secret@example.com",
                    "--add-note",
                    "sensitive-operator-note",
                ],
            )
        finally:
            logger.removeHandler(handler)

        assert result.exit_code == 0
        updated = [r for r in records if "Updated customer" in r.getMessage()]
        assert updated, "Expected an 'Updated customer' INFO record"
        joined = "\n".join(r.getMessage() for r in updated)
        assert "Updated customer | id=" + cid in joined
        assert "fields=email,notes" in joined
        assert "secret@example.com" not in joined
        assert "sensitive-operator-note" not in joined
        assert "Helena Ribeiro" not in joined

    def test_audit_details_json_no_pii(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
    ) -> None:
        freeze_today(date(2026, 4, 20))
        cid = _seed_customer(env, notes="seed")

        result = runner.invoke(
            app,
            [
                "update-customer",
                cid,
                "--email",
                "secret-target@example.com",
                "--add-note",
                "sensitive-note-body",
            ],
        )
        assert result.exit_code == 0

        audit = _latest_update_audit(env)
        assert audit is not None
        serialized = str(audit)
        assert "secret-target@example.com" not in serialized
        assert "sensitive-note-body" not in serialized
        parsed = json.loads(str(audit["details_json"]))
        assert parsed == {"fields": ["email", "notes"]}


# ---------------------------------------------------------------------------
# AC9 — same-value email still audits.
# ---------------------------------------------------------------------------


class TestUpdateCustomerSameEmail:
    def test_same_email_still_audits(self, env: dict[str, str]) -> None:
        cid = _seed_customer(env, email="a@b.com", notes="seed")
        before_count = _count_update_audits(env)

        _clear_buffers()
        result = runner.invoke(app, ["update-customer", cid, "--email", "a@b.com"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert f"Updated: {cid} (Helena Ribeiro) \u2014 email changed" in stdout

        assert _count_update_audits(env) == before_count + 1
        audit = _latest_update_audit(env)
        assert audit is not None
        assert audit["details_json"] == '{"fields": ["email"]}'


# ---------------------------------------------------------------------------
# Regression: list-customers row count unchanged after an update.
# ---------------------------------------------------------------------------


class TestUpdateCustomerListContract:
    def test_counts_unchanged(
        self,
        env: dict[str, str],
        freeze_today: Callable[[date], None],
    ) -> None:
        freeze_today(date(2026, 4, 20))
        cid_a = _seed_customer(
            env, name="Helena Ribeiro", email="a@clinica.com", cpf="123.456.789-09"
        )
        _seed_customer(
            env, name="Marcos Santos", email="b@padaria.com", cpf="111.444.777-35"
        )
        before = _count(env, "customer")
        key_count = _count(env, "api_key")

        r = runner.invoke(
            app,
            [
                "update-customer",
                cid_a,
                "--email",
                "new-a@clinica.com",
                "--add-note",
                "bump",
            ],
        )
        assert r.exit_code == 0

        assert _count(env, "customer") == before
        assert _count(env, "api_key") == key_count


# ---------------------------------------------------------------------------
# Regression: audit blocklist still intercepts forbidden top-level keys.
# ---------------------------------------------------------------------------


class TestUpdateCustomerAuditBlocklist:
    def test_blocklist_intercepts_forbidden_details(self, env: dict[str, str]) -> None:
        from comadre.keys.audit import log_event
        from comadre.keys.db import _apply_migrations, get_connection

        conn = get_connection(env["db_path"])
        try:
            _apply_migrations(conn)
            with pytest.raises(ValueError, match="forbidden"), conn:
                log_event(
                    conn,
                    actor="cli:tester",
                    action="update_customer",
                    target_type="customer",
                    target_id="cust_whatever",
                    details={"email": "secret@example.com"},
                )
        finally:
            conn.close()
