"""End-to-end CLI tests for `comadre-keys list-customers` (Story 1.3)."""

from __future__ import annotations

import json
import re
import sqlite3
from io import StringIO
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from rich.console import Console
from typer.testing import CliRunner

import comadre.keys.cli.output as output_mod
from comadre.keys.cli.app import app

# F41 — autouse fixtures (`_clear_settings_cache`,
# `_reset_cli_consoles_to_buffers`) now live in tests/conftest.py
# and apply to every test. Helpers (``_buffers`` / ``_clear_buffers``)
# live in tests/_keys_cli_helpers.py.
from tests._keys_cli_helpers import buffers as _buffers
from tests._keys_cli_helpers import clear_buffers as _clear_buffers

runner = CliRunner()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    key = Fernet.generate_key().decode()
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", key)
    return {"db_path": str(db_path), "key": key}


def _seed_customer(
    env: dict[str, str],
    *,
    name: str = "Helena Ribeiro",
    email: str = "helena@clinica.com",
    cpf: str = "123.456.789-09",
) -> str:
    """Run create-customer end-to-end and return the new ``cust_...`` id."""
    _clear_buffers()
    result = runner.invoke(
        app,
        [
            "create-customer",
            "--name",
            name,
            "--email",
            email,
            "--cpf",
            cpf,
        ],
    )
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


class TestFirstRunEmpty:
    """AC2 — first-run hint on a fresh DB."""

    def test_empty_db_prints_first_run_hint(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["list-customers"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert stderr == ""
        assert "No customers registered yet." in stdout
        assert "To get started: comadre-keys create-customer" in stdout.replace(
            "\n", " "
        )
        # Exact hint flags (accept any whitespace because rich may soft-wrap).
        flat = re.sub(r"\s+", " ", stdout)
        assert '--name "Name"' in flat
        assert '--email "email@example.com"' in flat
        assert '--cpf "000.000.000-00"' in flat
        # No DB writes.
        if Path(env["db_path"]).exists():
            assert _count(env, "customer") == 0
            assert _count(env, "audit_log") == 0


class TestPopulatedTable:
    """AC1 — populated happy path + LEFT JOIN key_count."""

    def test_populated_table_contents(self, env: dict[str, str]) -> None:
        c1 = _seed_customer(env, name="Alpha", email="alpha@a.com")
        c2 = _seed_customer(
            env,
            name="Bravo",
            email="bravo@b.com",
            cpf="111.444.777-35",
        )
        c3 = _seed_customer(
            env, name="Charlie", email="charlie@c.com", cpf="529.982.247-25"
        )
        # Issue two keys against c1, one against c2, zero against c3.
        for _ in range(2):
            result = runner.invoke(
                app,
                ["issue-key", "--customer", c1, "--rpm", "60", "--price", "149"],
            )
            assert result.exit_code == 0
            _clear_buffers()
        result = runner.invoke(
            app,
            ["issue-key", "--customer", c2, "--rpm", "60", "--price", "149"],
        )
        assert result.exit_code == 0
        _clear_buffers()

        result = runner.invoke(app, ["list-customers"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        for cid in (c1, c2, c3):
            assert cid in stdout
        assert "Alpha" in stdout
        assert "Bravo" in stdout
        assert "Charlie" in stdout
        # Key counts are rendered inside the customer's row. Rich separates
        # cells with the box-drawing character │ (U+2502). Splitting on that
        # yields the true column cells; anchoring on the customer name keeps
        # the assertion robust against digits from ULIDs or timestamps.
        expected_counts = {"Alpha": "2", "Bravo": "1", "Charlie": "0"}
        for name, count in expected_counts.items():
            row = next((line for line in stdout.splitlines() if name in line), None)
            assert row is not None, f"row for {name} not rendered"
            cells = [cell.strip() for cell in row.split("\u2502")]
            assert count in cells, f"expected key_count {count} for {name} in {cells!r}"
        assert "3 customers found." in stdout
        # Trailer comes out exactly once.
        assert stdout.count("customers found.") == 1


class TestDeletedFlag:
    """AC3 — tombstone handling."""

    def test_deleted_flag_includes_tombstones(self, env: dict[str, str]) -> None:
        alive = _seed_customer(env, name="Alive", email="alive@a.com")
        dead = _seed_customer(
            env,
            name="Dead",
            email="dead@d.com",
            cpf="111.444.777-35",
        )
        conn = sqlite3.connect(env["db_path"])
        try:
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-17T12:00:00Z", dead),
            )
            conn.commit()
        finally:
            conn.close()

        # Default: no tombstones.
        result = runner.invoke(app, ["list-customers"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert alive in stdout
        assert dead not in stdout
        assert "Customers (including purged)" not in stdout
        _clear_buffers()

        # --deleted: tombstones included.
        result = runner.invoke(app, ["list-customers", "--deleted"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert alive in stdout
        assert dead in stdout
        assert "Customers (including purged)" in stdout
        assert "2 customers found." in stdout

    def test_all_tombstoned_shows_purged_hint(self, env: dict[str, str]) -> None:
        cid = _seed_customer(env)
        conn = sqlite3.connect(env["db_path"])
        try:
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-17T12:00:00Z", cid),
            )
            conn.commit()
        finally:
            conn.close()

        result = runner.invoke(app, ["list-customers"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "No active customers." in stdout
        assert "--deleted" in stdout
        # First-run hint must NOT fire — the operator has used the system.
        assert "No customers registered yet." not in stdout


class TestFormatJson:
    """AC4 — machine-readable output."""

    def test_empty_is_empty_array(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["list-customers", "--format", "json"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert json.loads(stdout) == []
        # No hint text leaking into JSON mode.
        assert "To get started" not in stdout
        assert "No customers" not in stdout

    def test_populated_shape(self, env: dict[str, str]) -> None:
        c1 = _seed_customer(env, name="Alpha", email="a@a.com")
        _seed_customer(env, name="Bravo", email="b@b.com", cpf="111.444.777-35")
        result = runner.invoke(
            app,
            ["issue-key", "--customer", c1, "--rpm", "60", "--price", "149"],
        )
        assert result.exit_code == 0
        _clear_buffers()

        result = runner.invoke(app, ["list-customers", "--format", "json"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        data = json.loads(stdout)
        assert isinstance(data, list)
        assert len(data) == 2
        for entry in data:
            assert set(entry.keys()) == {
                "id",
                "name",
                "email",
                "tax_id_kind",
                "key_count",
                "registered_at",
                "deleted_at",
                "notes",
            }
            assert "tax_id_encrypted" not in entry
            assert entry["deleted_at"] is None
        # Key count matches.
        by_name = {e["name"]: e for e in data}
        assert by_name["Alpha"]["key_count"] == 1
        assert by_name["Bravo"]["key_count"] == 0

    def test_deleted_flag_in_json(self, env: dict[str, str]) -> None:
        alive = _seed_customer(env, name="Alive", email="alive@a.com")
        dead = _seed_customer(
            env,
            name="Dead",
            email="dead@d.com",
            cpf="111.444.777-35",
        )
        conn = sqlite3.connect(env["db_path"])
        try:
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-17T12:00:00Z", dead),
            )
            conn.commit()
        finally:
            conn.close()

        result = runner.invoke(
            app,
            ["list-customers", "--deleted", "--format", "json"],
        )
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        data = json.loads(stdout)
        assert len(data) == 2
        by_id = {e["id"]: e for e in data}
        assert by_id[alive]["deleted_at"] is None
        assert by_id[dead]["deleted_at"] == "2026-04-17T12:00:00Z"

    def test_format_invalid_exits_2(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["list-customers", "--format", "yaml"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--format must be table or json" in stderr


class TestReadOnly:
    """AC9 — list commands never mutate the DB."""

    def test_no_audit_or_table_writes(self, env: dict[str, str]) -> None:
        cid = _seed_customer(env)
        result = runner.invoke(
            app,
            ["issue-key", "--customer", cid, "--rpm", "60", "--price", "149"],
        )
        assert result.exit_code == 0
        _clear_buffers()

        before = {
            "customer": _count(env, "customer"),
            "api_key": _count(env, "api_key"),
            "audit_log": _count(env, "audit_log"),
        }
        for args in (
            ["list-customers"],
            ["list-customers", "--deleted"],
            ["list-customers", "--format", "json"],
            ["list-customers", "--deleted", "--format", "json"],
        ):
            result = runner.invoke(app, args)
            assert result.exit_code == 0, result.output
            _clear_buffers()

        after = {
            "customer": _count(env, "customer"),
            "api_key": _count(env, "api_key"),
            "audit_log": _count(env, "audit_log"),
        }
        assert before == after


class TestHelpSurface:
    """AC10 — realistic examples in --help, no DB touch."""

    def test_help_lists_realistic_examples(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KEY_REGISTRY_DB_PATH", raising=False)
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        result = runner.invoke(app, ["list-customers", "--help"])
        assert result.exit_code == 0
        # Strip ANSI + Panel border glyphs before collapsing whitespace so
        # wrapped help lines read as a single contiguous run (see
        # test_keys_cli_list_keys.TestHelpSurface for the same rationale).
        ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        cleaned = ansi.sub("", result.stdout)
        for glyph in ("\u2502", "\u256d", "\u256e", "\u2570", "\u256f", "\u2500"):
            cleaned = cleaned.replace(glyph, " ")
        flat = re.sub(r"\s+", " ", cleaned)
        assert "--deleted" in flat
        assert "purged customers" in flat
        assert "--format" in flat
        assert "--format json" in flat
        # DB file never created during --help.
        assert not (tmp_path / "registry.db").exists()


class TestNoColorAnsi:
    """AC10 — NO_COLOR honoured."""

    def test_no_ansi_escapes_with_no_color(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        # Re-wire the console so rich picks up NO_COLOR (consoles cache at construct).
        buf = StringIO()
        output_mod._stdout_console = Console(file=buf, force_terminal=False, width=120)
        _seed_customer(env)
        _clear_buffers()
        result = runner.invoke(app, ["list-customers"])
        stdout = output_mod._stdout_console.file.getvalue()  # type: ignore[union-attr]
        assert result.exit_code == 0
        assert "\x1b[" not in stdout
