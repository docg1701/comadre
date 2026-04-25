"""End-to-end CLI tests for `comadre-keys create-customer`.

Covers all of Story 1.1's acceptance criteria via Typer's CliRunner. The
fixtures isolate environment state (Fernet key, DB path) per-test so no
DB file is shared between tests.
"""

from __future__ import annotations

import base64
import json
import re
import sqlite3
import stat
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from comadre.keys.cli.app import app

# F41 — autouse fixtures (`_clear_settings_cache`,
# `_reset_cli_consoles_to_buffers`) now live in tests/conftest.py and apply
# to every test. Helpers (``_buffers``) live in tests/_keys_cli_helpers.py.
from tests._keys_cli_helpers import buffers as _buffers

runner = CliRunner()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    key = Fernet.generate_key().decode()
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", key)
    return {"db_path": str(db_path), "key": key}


class TestCreateCustomerHappyPath:
    """AC1 + AC2 + AC6."""

    def test_cpf_happy_path(self, env: dict[str, str]) -> None:
        result = runner.invoke(
            app,
            [
                "create-customer",
                "--name",
                "Helena Ribeiro",
                "--email",
                "helena@clinica.com",
                "--cpf",
                "123.456.789-09",
            ],
        )
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "Customer created: cust_" in stdout
        assert "Helena Ribeiro" in stdout
        # Regression sentinel: render_* routes through our Console singletons
        # (redirected to buffers in the fixture). Anything reaching the real
        # stdout indicates a raw print()/typer.echo() slipped in.
        assert result.stdout == ""

        # DB row present, exactly 1 customer + 1 audit
        conn = sqlite3.connect(env["db_path"])
        conn.row_factory = sqlite3.Row
        try:
            customers = conn.execute(
                "SELECT id, tax_id_kind, notes, tax_id_encrypted, registered_at "
                "FROM customer"
            ).fetchall()
            assert len(customers) == 1
            row = customers[0]
            assert row["tax_id_kind"] == "cpf"
            # AC1 ciphertext invariant: Fernet tokens decode to bytes starting
            # with the version byte 0x80 — base64-encoded as "gAAAAA…".
            ciphertext = row["tax_id_encrypted"]
            assert isinstance(ciphertext, bytes)
            assert len(ciphertext) > 40
            assert base64.urlsafe_b64decode(ciphertext)[:1] == b"\x80"
            # AC1 registered_at format: ISO 8601 UTC, no microseconds, Z suffix.
            assert re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", row["registered_at"]
            )
            audits = conn.execute(
                "SELECT action, actor, target_type, details_json FROM audit_log"
            ).fetchall()
            assert len(audits) == 1
            assert audits[0]["action"] == "create_customer"
            assert audits[0]["target_type"] == "customer"
            assert json.loads(audits[0]["details_json"]) == {"tax_id_kind": "cpf"}
            # AC8 actor shape: must be `cli:<something>`, never empty or None.
            assert audits[0]["actor"].startswith("cli:")
            assert len(audits[0]["actor"]) > len("cli:")
        finally:
            conn.close()

    def test_cnpj_happy_path(self, env: dict[str, str]) -> None:
        result = runner.invoke(
            app,
            [
                "create-customer",
                "--name",
                "Empresa LTDA",
                "--email",
                "fin@empresa.com",
                "--cnpj",
                "12.345.678/0001-95",
            ],
        )
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "Customer created: cust_" in stdout
        assert "Empresa LTDA" in stdout

        conn = sqlite3.connect(env["db_path"])
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT tax_id_kind FROM customer").fetchone()
            assert row["tax_id_kind"] == "cnpj"
        finally:
            conn.close()


class TestMutexFlags:
    """AC3."""

    def test_both_cpf_and_cnpj_rejected(self, env: dict[str, str]) -> None:
        result = runner.invoke(
            app,
            [
                "create-customer",
                "--name",
                "X",
                "--email",
                "x@x.com",
                "--cpf",
                "123.456.789-09",
                "--cnpj",
                "12.345.678/0001-95",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        # AC3 title + UX-DR6 hint both must render.
        assert "mutually exclusive" in stderr
        assert "Provide exactly one of --cpf or --cnpj." in stderr
        # No DB file was touched
        assert not Path(env["db_path"]).exists()

    def test_neither_cpf_nor_cnpj_rejected(self, env: dict[str, str]) -> None:
        result = runner.invoke(
            app,
            ["create-customer", "--name", "X", "--email", "x@x.com"],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "exactly one of --cpf or --cnpj is required" in stderr
        assert "Provide exactly one of --cpf or --cnpj." in stderr
        assert not Path(env["db_path"]).exists()

    def test_mutex_rejected_with_preexisting_db(self, env: dict[str, str]) -> None:
        """AC3: when the DB already exists, mutex rejection still writes nothing."""
        # Seed the DB via a successful run.
        seed = runner.invoke(
            app,
            [
                "create-customer",
                "--name",
                "Seed",
                "--email",
                "seed@x.com",
                "--cpf",
                "123.456.789-09",
            ],
        )
        assert seed.exit_code == 0
        conn = sqlite3.connect(env["db_path"])
        try:
            before = conn.execute("SELECT COUNT(*) FROM customer").fetchone()[0]
            before_audit = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        finally:
            conn.close()
        # Attempt a mutex-violating second invocation.
        result = runner.invoke(
            app,
            [
                "create-customer",
                "--name",
                "X",
                "--email",
                "x@x.com",
                "--cpf",
                "123.456.789-09",
                "--cnpj",
                "12.345.678/0001-95",
            ],
        )
        assert result.exit_code == 2
        conn = sqlite3.connect(env["db_path"])
        try:
            after = conn.execute("SELECT COUNT(*) FROM customer").fetchone()[0]
            after_audit = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        finally:
            conn.close()
        assert after == before
        assert after_audit == before_audit


class TestInvalidChecksum:
    """AC4 — anti-enumeration: rejected value NEVER echoed."""

    def test_invalid_cpf_rejected_no_echo(self, env: dict[str, str]) -> None:
        rejected = "111.111.111-11"
        digits_only = "11111111111"
        result = runner.invoke(
            app,
            [
                "create-customer",
                "--name",
                "X",
                "--email",
                "x@x.com",
                "--cpf",
                rejected,
            ],
        )
        stdout, stderr = _buffers()
        assert result.exit_code == 4
        assert "Invalid CPF: checksum verification failed" in stderr
        assert "Verify the CPF digits and try again." in stderr
        # CRITICAL: neither the masked input nor its canonical digits-only
        # form may appear — not in stdout, stderr, or the CliRunner output.
        for needle in (rejected, digits_only):
            assert needle not in stdout
            assert needle not in stderr
            assert needle not in result.stdout
        # No rows written.
        if Path(env["db_path"]).exists():
            conn = sqlite3.connect(env["db_path"])
            try:
                assert conn.execute("SELECT COUNT(*) FROM customer").fetchone()[0] == 0
                assert conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0] == 0
            finally:
                conn.close()

    def test_invalid_cnpj_rejected_no_echo(self, env: dict[str, str]) -> None:
        rejected = "11.111.111/1111-11"
        digits_only = "11111111111111"
        result = runner.invoke(
            app,
            [
                "create-customer",
                "--name",
                "X",
                "--email",
                "x@x.com",
                "--cnpj",
                rejected,
            ],
        )
        stdout, stderr = _buffers()
        assert result.exit_code == 4
        assert "Invalid CNPJ: checksum verification failed" in stderr
        assert "Verify the CNPJ digits and try again." in stderr
        # Symmetric anti-enumeration check with the CPF test above.
        for needle in (rejected, digits_only):
            assert needle not in stdout
            assert needle not in stderr
            assert needle not in result.stdout


class TestMissingEncryptionKey:
    """AC5."""

    def test_missing_key_reports_config_error(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        # Ensure pydantic-settings won't accidentally load a project .env
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            [
                "create-customer",
                "--name",
                "X",
                "--email",
                "x@x.com",
                "--cpf",
                "123.456.789-09",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 6
        assert "KEY_REGISTRY_ENCRYPTION_KEY" in stderr
        assert "Configuration error" in stderr

    def test_malformed_key_not_echoed(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        malformed = "not-a-valid-fernet-key"
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", malformed)
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.chdir(tmp_path)
        result = runner.invoke(
            app,
            [
                "create-customer",
                "--name",
                "X",
                "--email",
                "x@x.com",
                "--cpf",
                "123.456.789-09",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 6
        assert malformed not in stderr


class TestFirstRunBootstrap:
    """AC6."""

    def test_first_run_creates_db_with_0600(self, env: dict[str, str]) -> None:
        db_path = Path(env["db_path"])
        assert not db_path.exists()
        result = runner.invoke(
            app,
            [
                "create-customer",
                "--name",
                "X",
                "--email",
                "x@x.com",
                "--cpf",
                "123.456.789-09",
            ],
        )
        assert result.exit_code == 0
        assert db_path.exists()
        mode = stat.S_IMODE(db_path.stat().st_mode)
        assert mode == 0o600
        conn = sqlite3.connect(db_path)
        try:
            row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
            # F19 — schema bumped to v2; assert against the live constant
            # rather than a frozen literal so future migrations keep this
            # test honest.
            from comadre.keys.db import _SCHEMA_VERSION

            assert row[0] == _SCHEMA_VERSION
        finally:
            conn.close()


class TestIdempotentRerun:
    """AC7 — second run does not re-execute DDL."""

    def test_second_run_skips_migration(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # First run creates DB + schema v1.
        result = runner.invoke(
            app,
            [
                "create-customer",
                "--name",
                "A",
                "--email",
                "a@a.com",
                "--cpf",
                "123.456.789-09",
            ],
        )
        assert result.exit_code == 0

        # Second run must not re-read the migration SQL file.
        import comadre.keys.db as db_module

        real_files = db_module.importlib.resources.files

        def _guard(*_args: object, **_kw: object) -> object:
            raise AssertionError("migration SQL must not be re-read on re-run")

        monkeypatch.setattr(db_module.importlib.resources, "files", _guard)

        try:
            result2 = runner.invoke(
                app,
                [
                    "create-customer",
                    "--name",
                    "B",
                    "--email",
                    "b@b.com",
                    "--cnpj",
                    "12.345.678/0001-95",
                ],
            )
            assert result2.exit_code == 0
        finally:
            monkeypatch.setattr(db_module.importlib.resources, "files", real_files)

        # Schema version still at the same row count after the second run.
        conn = sqlite3.connect(env["db_path"])
        try:
            from comadre.keys.db import _SCHEMA_VERSION

            rows = conn.execute(
                "SELECT version FROM schema_version ORDER BY version"
            ).fetchall()
            assert [r[0] for r in rows] == list(range(1, _SCHEMA_VERSION + 1))
            count = conn.execute("SELECT COUNT(*) FROM customer").fetchone()[0]
            assert count == 2
        finally:
            conn.close()


class TestAuditLogNoPersonalData:
    """AC8 — FR30 invariant: details_json only carries non-personal metadata."""

    def test_audit_details_json_shape(self, env: dict[str, str]) -> None:
        result = runner.invoke(
            app,
            [
                "create-customer",
                "--name",
                "Helena",
                "--email",
                "helena@clinica.com",
                "--cpf",
                "123.456.789-09",
            ],
        )
        assert result.exit_code == 0
        conn = sqlite3.connect(env["db_path"])
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT details_json FROM audit_log").fetchone()
        finally:
            conn.close()
        details = row["details_json"]
        assert details == '{"tax_id_kind": "cpf"}'
        # No personal-data literals (name, email, CPF digits).
        for needle in (
            "Helena",
            "helena",
            "clinica.com",
            "12345",
            "45678",
            "78909",
        ):
            assert needle not in details, f"leak: {needle!r} in {details!r}"
        # No FORBIDDEN key names (per AC8). Keys are "name":, "email": etc. —
        # scan the parsed JSON, not substrings, to avoid tax_id_kind confusion.
        parsed = json.loads(details)
        forbidden_keys = {"cpf", "cnpj", "tax_id", "name", "email"}
        assert not (parsed.keys() & forbidden_keys)


class TestHelpSurfaces:
    """AC9."""

    def test_top_level_help_lists_create_customer(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "create-customer" in result.stdout

    def test_create_customer_help_shows_example_values(self) -> None:
        result = runner.invoke(app, ["create-customer", "--help"])
        assert result.exit_code == 0
        assert "Helena Ribeiro" in result.stdout
        assert "helena@clinica.com" in result.stdout
        assert "123.456.789-09" in result.stdout
