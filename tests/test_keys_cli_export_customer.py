"""End-to-end CLI tests for ``comadre-keys export-customer`` (Story 4.1)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from datetime import UTC, datetime
from pathlib import Path

import pytest
import yaml
from cryptography.fernet import Fernet
from pydantic import SecretStr
from typer.testing import CliRunner

from comadre.keys.cli.app import app
from comadre.keys.crypto import encrypt_tax_id
from comadre.keys.db import (
    _apply_migrations,
    generate_customer_id,
    generate_key_id,
    get_connection,
    insert_api_key,
    insert_customer,
)
from comadre.keys.models import ApiKeyRecord, CustomerRecord

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


def _seed_customer_with_cpf(
    db_path: str,
    encryption_key: str,
    *,
    canonical_cpf: str = "12345678909",
    name: str = "Marcos Silva",
    email: str = "marcos@example.com",
    notes: str = "owner of a bot",
) -> str:
    """Seed one customer with a real encrypted CPF. Returns the customer id."""
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        cid = generate_customer_id()
        ciphertext = encrypt_tax_id(canonical_cpf, SecretStr(encryption_key))
        insert_customer(
            conn,
            CustomerRecord(
                id=cid,
                name=name,
                email=email,
                tax_id_kind="cpf",
                tax_id_encrypted=ciphertext,
                notes=notes,
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
    billing_mode: str = "manual",
    price_monthly: float = 149.0,
    paid_until: str | None = None,
    created_at: datetime | None = None,
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
                billing_mode=billing_mode,  # type: ignore[arg-type]
                price_monthly=price_monthly,
                paid_until=paid_until,
                created_at=created_at or datetime(2026, 3, 20, 10, 0, 0, tzinfo=UTC),
                last_used_at=None,
                notes="",
            ),
            actor="cli:tester",
        )
        return kid
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# AC1 / AC2 — JSON and YAML happy path.
# ---------------------------------------------------------------------------


class TestExportCustomerHappyPath:
    def test_json_default_emits_payload_in_ac1_order(self, env: dict[str, str]) -> None:
        cid = _seed_customer_with_cpf(env["db_path"], env["key"])
        _seed_key(env["db_path"], cid, key_prefix="Pq_abc12", key_hash="a" * 64)
        _seed_key(
            env["db_path"],
            cid,
            key_prefix="Pq_def34",
            key_hash="b" * 64,
            created_at=datetime(2026, 3, 21, 10, 0, 0, tzinfo=UTC),
        )

        _clear_buffers()
        result = runner.invoke(app, ["export-customer", cid])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert stderr == ""

        payload = json.loads(stdout)
        assert list(payload.keys()) == [
            "id",
            "name",
            "email",
            "tax_id_kind",
            "tax_id",
            "registered_at",
            "notes",
            "keys",
        ]
        assert payload["id"] == cid
        assert payload["name"] == "Marcos Silva"
        assert payload["email"] == "marcos@example.com"
        assert payload["tax_id_kind"] == "cpf"
        assert payload["tax_id"] == "123.456.789-09"
        assert payload["registered_at"] == "2026-03-12T14:22:05Z"
        assert payload["notes"] == "owner of a bot"
        assert len(payload["keys"]) == 2
        for key in payload["keys"]:
            assert list(key.keys()) == [
                "key_prefix",
                "status",
                "billing_mode",
                "created_at",
            ]

    def test_yaml_preserves_order_and_round_trips(self, env: dict[str, str]) -> None:
        cid = _seed_customer_with_cpf(env["db_path"], env["key"])
        _seed_key(env["db_path"], cid)

        _clear_buffers()
        result = runner.invoke(app, ["export-customer", cid, "--format", "yaml"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr

        parsed = yaml.safe_load(stdout)
        assert parsed["id"] == cid
        assert parsed["tax_id"] == "123.456.789-09"
        assert list(parsed.keys()) == [
            "id",
            "name",
            "email",
            "tax_id_kind",
            "tax_id",
            "registered_at",
            "notes",
            "keys",
        ]

    def test_zero_keys_renders_empty_list(self, env: dict[str, str]) -> None:
        cid = _seed_customer_with_cpf(env["db_path"], env["key"])
        _clear_buffers()
        result = runner.invoke(app, ["export-customer", cid])
        stdout, _ = _buffers()
        assert result.exit_code == 0
        payload = json.loads(stdout)
        assert payload["keys"] == []

    def test_cnpj_customer_exports_formatted_tax_id(self, env: dict[str, str]) -> None:
        conn = get_connection(env["db_path"])
        try:
            _apply_migrations(conn)
            cid = generate_customer_id()
            ciphertext = encrypt_tax_id("12345678000195", SecretStr(env["key"]))
            insert_customer(
                conn,
                CustomerRecord(
                    id=cid,
                    name="Acme LTDA",
                    email="billing@acme.com",
                    tax_id_kind="cnpj",
                    tax_id_encrypted=ciphertext,
                    notes="",
                    registered_at=datetime(2026, 3, 12, 14, 22, 5, tzinfo=UTC),
                    deleted_at=None,
                ),
                actor="cli:tester",
            )
        finally:
            conn.close()

        _clear_buffers()
        result = runner.invoke(app, ["export-customer", cid])
        stdout, _ = _buffers()
        assert result.exit_code == 0
        payload = json.loads(stdout)
        assert payload["tax_id_kind"] == "cnpj"
        assert payload["tax_id"] == "12.345.678/0001-95"


# ---------------------------------------------------------------------------
# AC4 / AC5 — not-found cases.
# ---------------------------------------------------------------------------


class TestExportCustomerNotFound:
    def test_unknown_id_exits_3(self, env: dict[str, str]) -> None:
        # Force migrations to run so the not-found path is exercised on an
        # initialized DB.
        _seed_customer_with_cpf(env["db_path"], env["key"])
        _clear_buffers()
        missing = "cust_01hg7zzzzzzzzzzzzzzzzzzzzz"
        result = runner.invoke(app, ["export-customer", missing])
        stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Not found" in stderr
        assert missing in stderr
        assert stdout == ""

    def test_tombstoned_customer_exits_3(self, env: dict[str, str]) -> None:
        cid = _seed_customer_with_cpf(env["db_path"], env["key"])
        # Tombstone the row directly.
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
        result = runner.invoke(app, ["export-customer", cid])
        _, stderr = _buffers()
        assert result.exit_code == 3
        assert "Not found" in stderr


# ---------------------------------------------------------------------------
# AC6 — format validation.
# ---------------------------------------------------------------------------


class TestExportCustomerFormatValidation:
    def test_unknown_format_exits_2(self, env: dict[str, str]) -> None:
        cid = _seed_customer_with_cpf(env["db_path"], env["key"])
        _clear_buffers()
        result = runner.invoke(app, ["export-customer", cid, "--format", "csv"])
        _, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --format must be json or yaml" in stderr
        assert "json, yaml" in stderr

    def test_bad_customer_id_shape_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No DB needs to exist — shape check runs before the connection.
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "nope.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )
        _clear_buffers()
        result = runner.invoke(app, ["export-customer", "not-a-cust-id"])
        _, stderr = _buffers()
        assert result.exit_code == 2
        assert "invalid customer id" in stderr
        assert not (tmp_path / "nope.db").exists()


# ---------------------------------------------------------------------------
# AC17 — configuration / db error mapping.
# ---------------------------------------------------------------------------


class TestExportCustomerConfigErrors:
    def test_missing_encryption_key_exits_6(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        _clear_buffers()
        # Use a syntactically-valid id so we hit the encryption-key check.
        cid = "cust_01hg7xyzxyzxyzxyzxyzxyzxyz"
        result = runner.invoke(app, ["export-customer", cid])
        _, stderr = _buffers()
        assert result.exit_code == 6
        assert "KEY_REGISTRY_ENCRYPTION_KEY" in stderr

    def test_db_open_error_exits_5(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC17 — a `sqlite3.Error` on DB open maps to exit 5 with "Database error"."""
        _seed_customer_with_cpf(env["db_path"], env["key"])
        # Monkeypatch the connection helper imported into the customers module
        # so it raises a concrete sqlite3 error. Must patch the call-site symbol
        # (re-bound via `from ... import get_connection`) rather than the source
        # module, so the CLI body sees the stub.
        import comadre.keys.cli.commands.customers as customers_mod

        def _boom(_: str) -> sqlite3.Connection:
            raise sqlite3.OperationalError("unable to open database file")

        monkeypatch.setattr(customers_mod, "get_connection", _boom)

        _clear_buffers()
        cid = "cust_01hg7xyzxyzxyzxyzxyzxyzxyz"
        result = runner.invoke(app, ["export-customer", cid])
        _, stderr = _buffers()
        assert result.exit_code == 5
        assert "Database error" in stderr
        assert "unable to open database file" in stderr

    def test_corrupted_ciphertext_exits_5(self, env: dict[str, str]) -> None:
        cid = _seed_customer_with_cpf(env["db_path"], env["key"])
        # Manually corrupt the ciphertext blob.
        raw = sqlite3.connect(env["db_path"])
        try:
            raw.execute(
                "UPDATE customer SET tax_id_encrypted = ? WHERE id = ?",
                (b"gAAAAAAcorrupted-bytes-not-a-token", cid),
            )
            raw.commit()
        finally:
            raw.close()

        _clear_buffers()
        result = runner.invoke(app, ["export-customer", cid])
        _, stderr = _buffers()
        assert result.exit_code == 5
        assert "tax-ID ciphertext failed to decrypt" in stderr
        # The raw ciphertext bytes must not be echoed in the error.
        assert "gAAAAAAcorrupted" not in stderr


# ---------------------------------------------------------------------------
# AC15 / AC16 — INFO log PII hygiene + no ciphertext leak.
# ---------------------------------------------------------------------------


class TestExportCustomerLogging:
    def test_log_contains_no_pii(self, env: dict[str, str]) -> None:
        from comadre.logging import get_logger

        cid = _seed_customer_with_cpf(env["db_path"], env["key"])
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
            result = runner.invoke(app, ["export-customer", cid])
        finally:
            logger.removeHandler(handler)

        assert result.exit_code == 0
        joined = "\n".join(r.getMessage() for r in records)
        assert "Customer exported" in joined
        assert f"id={cid}" in joined
        assert "key_count=1" in joined
        assert "format=json" in joined
        # PII must NOT be present.
        assert "Marcos Silva" not in joined
        assert "marcos@example.com" not in joined
        assert "12345678909" not in joined
        assert "123.456.789-09" not in joined

    def test_stdout_omits_ciphertext_field_and_bytes(self, env: dict[str, str]) -> None:
        cid = _seed_customer_with_cpf(env["db_path"], env["key"])
        # Read the raw ciphertext from the DB.
        raw = sqlite3.connect(env["db_path"])
        try:
            row = raw.execute(
                "SELECT tax_id_encrypted FROM customer WHERE id = ?", (cid,)
            ).fetchone()
            assert row is not None
            ciphertext_bytes = bytes(row[0])
        finally:
            raw.close()

        _clear_buffers()
        result = runner.invoke(app, ["export-customer", cid])
        stdout, _ = _buffers()
        assert result.exit_code == 0
        # No ciphertext-field name leaked.
        assert "tax_id_encrypted" not in stdout
        assert "tax_id_cipher" not in stdout
        # No 8+ byte slice of the ciphertext leaks into stdout.
        assert len(ciphertext_bytes) >= 8
        for i in range(len(ciphertext_bytes) - 7):
            chunk = ciphertext_bytes[i : i + 8]
            try:
                as_str = chunk.decode("ascii")
            except UnicodeDecodeError:
                continue
            assert as_str not in stdout


# ---------------------------------------------------------------------------
# AC22 — YAML does not interpret rich markup.
# ---------------------------------------------------------------------------


class TestExportCustomerYamlMarkup:
    def test_bracketed_notes_pass_through_verbatim(self, env: dict[str, str]) -> None:
        cid = _seed_customer_with_cpf(
            env["db_path"],
            env["key"],
            notes="[urgent] owner",
        )
        _clear_buffers()
        result = runner.invoke(app, ["export-customer", cid, "--format", "yaml"])
        stdout, _ = _buffers()
        assert result.exit_code == 0
        # The literal bracketed text appears in the YAML output.
        assert "[urgent] owner" in stdout
        parsed = yaml.safe_load(stdout)
        assert parsed["notes"] == "[urgent] owner"


# ---------------------------------------------------------------------------
# AC20 — --help surface.
# ---------------------------------------------------------------------------


class TestExportCustomerHelp:
    def test_help_lists_both_formats(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KEY_REGISTRY_DB_PATH", raising=False)
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        result = runner.invoke(app, ["export-customer", "--help"])
        assert result.exit_code == 0
        ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        cleaned = ansi.sub("", result.stdout)
        for glyph in ("\u2502", "\u256d", "\u256e", "\u2570", "\u256f", "\u2500"):
            cleaned = cleaned.replace(glyph, " ")
        flat = re.sub(r"\s+", " ", cleaned)
        assert "cust_01j8xr3e4c5m7kn9p2qt8vwy" in flat
        assert "--format" in flat
        assert "yaml" in flat
