"""End-to-end CLI tests for ``comadre-keys rotate-encryption-key`` (Story 4.2).

Covers AC1 (--yes), AC2 (interactive y/n/Enter), AC3 (bad Fernet shape —
pre-DB), AC4 (InvalidToken rollback), AC5 (tombstone skip), AC6 (empty
DB), AC7 (missing OLD key), AC8 (PII-austere log + new-key on success
only), AC9 (no --format), AC11 (--help text), AC12 (forbidden keys on
the audit payload — exercised indirectly via the DB test's round-trip).
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from pydantic import SecretStr
from rich.console import Console
from typer.testing import CliRunner

import comadre.keys.cli.commands.system as system_cmd
import comadre.keys.cli.output as output_mod
from comadre.config import get_settings
from comadre.keys.cli.app import app
from comadre.keys.crypto import decrypt_tax_id, encrypt_tax_id
from comadre.keys.db import (
    _apply_migrations,
    delete_customer_hard,
    generate_customer_id,
    get_connection,
    insert_customer,
)
from comadre.keys.models import CustomerRecord

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


def _buffers() -> tuple[str, str]:
    stdout_file = output_mod._stdout_console.file  # type: ignore[union-attr]
    stderr_file = output_mod._stderr_console.file  # type: ignore[union-attr]
    return stdout_file.getvalue(), stderr_file.getvalue()


def _clear_buffers() -> None:
    for attr in ("_stdout_console", "_stderr_console"):
        console = getattr(output_mod, attr)
        console.file.seek(0)  # type: ignore[union-attr]
        console.file.truncate()  # type: ignore[union-attr]


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    key = Fernet.generate_key().decode()
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", key)
    return {"db_path": str(db_path), "key": key}


def _seed_active_customer(
    db_path: str,
    *,
    cid: str,
    name: str,
    canonical: str,
    tax_id_kind: str,
    key: str,
) -> None:
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        insert_customer(
            conn,
            CustomerRecord(
                id=cid,
                name=name,
                email=f"{cid}@x.com",
                tax_id_kind=tax_id_kind,  # type: ignore[arg-type]
                tax_id_encrypted=encrypt_tax_id(canonical, SecretStr(key)),
                notes="",
                registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                deleted_at=None,
            ),
            actor="cli:tester",
        )
    finally:
        conn.close()


def _seed_tombstoned_customer(db_path: str, key: str) -> str:
    """Create + immediately hard-delete a customer — yields the tombstone shape."""
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        cid = generate_customer_id()
        insert_customer(
            conn,
            CustomerRecord(
                id=cid,
                name="Tombstoned",
                email="t@x.com",
                tax_id_kind="cpf",
                tax_id_encrypted=encrypt_tax_id("12345678909", SecretStr(key)),
                notes="",
                registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                deleted_at=None,
            ),
            actor="cli:tester",
        )
        delete_customer_hard(conn, cid, actor="cli:tester")
        return cid
    finally:
        conn.close()


def _read_ciphertexts(db_path: str) -> dict[str, bytes]:
    raw = sqlite3.connect(db_path)
    try:
        raw.row_factory = sqlite3.Row
        rows = raw.execute("SELECT id, tax_id_encrypted FROM customer").fetchall()
        return {row["id"]: bytes(row["tax_id_encrypted"]) for row in rows}
    finally:
        raw.close()


def _audit_rotate_rows(db_path: str) -> list[sqlite3.Row]:
    raw = sqlite3.connect(db_path)
    try:
        raw.row_factory = sqlite3.Row
        return list(
            raw.execute(
                "SELECT id, action, target_type, target_id, actor, "
                "occurred_at, details_json "
                "FROM audit_log WHERE action = 'rotate_encryption_key' "
                "ORDER BY id ASC"
            ).fetchall()
        )
    finally:
        raw.close()


# ---------------------------------------------------------------------------
# AC1 / AC2 — happy paths (--yes + interactive y / n / Enter).
# ---------------------------------------------------------------------------


class TestRotateEncryptionKeyHappyPath:
    def test_yes_flag_rotates_every_active_row(self, env: dict[str, str]) -> None:
        old_key = env["key"]
        new_key = Fernet.generate_key().decode()
        _seed_active_customer(
            env["db_path"],
            cid="cust_01aaaaaaaaaaaaaaa",
            name="Ana",
            canonical="12345678909",
            tax_id_kind="cpf",
            key=old_key,
        )
        _seed_active_customer(
            env["db_path"],
            cid="cust_01bbbbbbbbbbbbbbb",
            name="Acme",
            canonical="12345678000195",
            tax_id_kind="cnpj",
            key=old_key,
        )
        _seed_active_customer(
            env["db_path"],
            cid="cust_01ccccccccccccccc",
            name="Zeta",
            canonical="12ABC345XY0189",
            tax_id_kind="cnpj",
            key=old_key,
        )

        _clear_buffers()
        result = runner.invoke(
            app, ["rotate-encryption-key", "--new-key", new_key, "--yes"]
        )
        stdout, stderr = _buffers()
        assert result.exit_code == 0
        assert (
            f"Encryption key rotated. Update KEY_REGISTRY_ENCRYPTION_KEY in "
            f".env to: {new_key}" in stdout
        )
        assert "Continue?" not in stderr  # --yes skips the prompt.

        # Every row now decrypts under the new key.
        ciphers = _read_ciphertexts(env["db_path"])
        for cid, canonical in (
            ("cust_01aaaaaaaaaaaaaaa", "12345678909"),
            ("cust_01bbbbbbbbbbbbbbb", "12345678000195"),
            ("cust_01ccccccccccccccc", "12ABC345XY0189"),
        ):
            assert decrypt_tax_id(ciphers[cid], SecretStr(new_key)) == canonical

        # Audit row present, shape correct.
        audit = _audit_rotate_rows(env["db_path"])
        assert len(audit) == 1
        row = audit[0]
        assert row["target_type"] == "registry"
        assert row["target_id"] is None
        details = json.loads(str(row["details_json"]))
        assert details == {"rows_re_encrypted": 3}

    def test_interactive_y_runs_rotation(self, env: dict[str, str]) -> None:
        old_key = env["key"]
        new_key = Fernet.generate_key().decode()
        _seed_active_customer(
            env["db_path"],
            cid="cust_01interactivey1",
            name="Ana",
            canonical="12345678909",
            tax_id_kind="cpf",
            key=old_key,
        )
        _seed_active_customer(
            env["db_path"],
            cid="cust_01interactivey2",
            name="Bob",
            canonical="98765432100",
            tax_id_kind="cpf",
            key=old_key,
        )

        _clear_buffers()
        result = runner.invoke(
            app, ["rotate-encryption-key", "--new-key", new_key], input="y\n"
        )
        stdout, _ = _buffers()
        assert result.exit_code == 0
        assert (
            "This will re-encrypt 2 active customer tax ID(s) with the "
            "new key. Continue?"
        ) in result.stderr
        assert f"Update KEY_REGISTRY_ENCRYPTION_KEY in .env to: {new_key}" in stdout

    def test_interactive_n_aborts_without_mutation(self, env: dict[str, str]) -> None:
        old_key = env["key"]
        new_key = Fernet.generate_key().decode()
        _seed_active_customer(
            env["db_path"],
            cid="cust_01abortntest001",
            name="Ana",
            canonical="12345678909",
            tax_id_kind="cpf",
            key=old_key,
        )

        pre = _read_ciphertexts(env["db_path"])

        _clear_buffers()
        result = runner.invoke(
            app, ["rotate-encryption-key", "--new-key", new_key], input="n\n"
        )
        _, stderr = _buffers()
        assert result.exit_code == 2
        assert "Aborted." in stderr

        # DB unchanged.
        assert _read_ciphertexts(env["db_path"]) == pre
        # No rotate audit row.
        assert _audit_rotate_rows(env["db_path"]) == []

    def test_enter_without_typing_aborts(self, env: dict[str, str]) -> None:
        old_key = env["key"]
        new_key = Fernet.generate_key().decode()
        _seed_active_customer(
            env["db_path"],
            cid="cust_01enterabort01",
            name="Ana",
            canonical="12345678909",
            tax_id_kind="cpf",
            key=old_key,
        )

        _clear_buffers()
        result = runner.invoke(
            app, ["rotate-encryption-key", "--new-key", new_key], input="\n"
        )
        assert result.exit_code == 2
        # DB unchanged — no rotate audit row.
        assert _audit_rotate_rows(env["db_path"]) == []


# ---------------------------------------------------------------------------
# AC3 — bad Fernet shape rejected pre-DB.
# ---------------------------------------------------------------------------


class TestRotateEncryptionKeyFernetShape:
    def test_bad_fernet_exits_4_without_opening_db(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """``get_connection`` must never be called when the shape check fails."""

        def _boom(_path: Any) -> None:
            raise AssertionError("get_connection was called despite invalid --new-key")

        monkeypatch.setattr(system_cmd, "get_connection", _boom)

        _clear_buffers()
        result = runner.invoke(
            app,
            ["rotate-encryption-key", "--new-key", "NOT-A-VALID-FERNET", "--yes"],
        )
        _, stderr = _buffers()
        assert result.exit_code == 4
        assert "Invalid encryption key: --new-key is not a valid Fernet key" in stderr
        assert "Generate a fresh Fernet key" in stderr
        # NFR16: the operator's invalid value is NOT echoed back in the error.
        assert "NOT-A-VALID-FERNET" not in stderr

    def test_truncated_fernet_exits_4(self, env: dict[str, str]) -> None:
        _clear_buffers()
        result = runner.invoke(
            app, ["rotate-encryption-key", "--new-key", "short", "--yes"]
        )
        assert result.exit_code == 4


# ---------------------------------------------------------------------------
# AC4 — InvalidToken mid-rotation rolls back atomically.
# ---------------------------------------------------------------------------


class TestRotateEncryptionKeyInvalidToken:
    def test_corrupted_ciphertext_rolls_back_every_row(
        self, env: dict[str, str]
    ) -> None:
        old_key = env["key"]
        new_key = Fernet.generate_key().decode()
        # One good, one corrupted.
        _seed_active_customer(
            env["db_path"],
            cid="cust_01goodrollback",
            name="Ana",
            canonical="12345678909",
            tax_id_kind="cpf",
            key=old_key,
        )
        _seed_active_customer(
            env["db_path"],
            cid="cust_01badrollback1",
            name="Bob",
            canonical="98765432100",
            tax_id_kind="cpf",
            key=old_key,
        )
        # Corrupt the second row's ciphertext so decrypt fails mid-loop.
        raw = sqlite3.connect(env["db_path"])
        try:
            raw.execute(
                "UPDATE customer SET tax_id_encrypted = ? WHERE id = ?",
                (b"corrupted-non-fernet-bytes", "cust_01badrollback1"),
            )
            raw.commit()
        finally:
            raw.close()

        pre = _read_ciphertexts(env["db_path"])

        _clear_buffers()
        result = runner.invoke(
            app, ["rotate-encryption-key", "--new-key", new_key, "--yes"]
        )
        _, stderr = _buffers()
        assert result.exit_code == 5
        assert (
            "Database error: tax-ID ciphertext failed to decrypt during rotation"
            in stderr
        )
        assert "current KEY_REGISTRY_ENCRYPTION_KEY value cannot decrypt" in stderr

        # Every row's ciphertext is byte-identical to pre-rotation.
        assert _read_ciphertexts(env["db_path"]) == pre
        # No rotate audit row (the whole txn rolled back).
        assert _audit_rotate_rows(env["db_path"]) == []


# ---------------------------------------------------------------------------
# AC5 — tombstoned rows are silently skipped.
# ---------------------------------------------------------------------------


class TestRotateEncryptionKeyTombstones:
    def test_tombstoned_rows_are_skipped(self, env: dict[str, str]) -> None:
        old_key = env["key"]
        new_key = Fernet.generate_key().decode()
        _seed_active_customer(
            env["db_path"],
            cid="cust_01activewtomb1",
            name="Ana",
            canonical="12345678909",
            tax_id_kind="cpf",
            key=old_key,
        )
        _seed_active_customer(
            env["db_path"],
            cid="cust_01activewtomb2",
            name="Bob",
            canonical="98765432100",
            tax_id_kind="cpf",
            key=old_key,
        )
        tomb_cid = _seed_tombstoned_customer(env["db_path"], old_key)
        pre = _read_ciphertexts(env["db_path"])
        assert pre[tomb_cid] == b""

        _clear_buffers()
        result = runner.invoke(
            app, ["rotate-encryption-key", "--new-key", new_key], input="y\n"
        )
        _buffers()
        assert result.exit_code == 0
        # Prompt quotes the active-only count.
        assert (
            "This will re-encrypt 2 active customer tax ID(s) with the new key."
            in result.stderr
        )
        # Tombstoned row unchanged.
        post = _read_ciphertexts(env["db_path"])
        assert post[tomb_cid] == b""
        # Active rows re-encrypted.
        for cid, canonical in (
            ("cust_01activewtomb1", "12345678909"),
            ("cust_01activewtomb2", "98765432100"),
        ):
            assert decrypt_tax_id(post[cid], SecretStr(new_key)) == canonical
        # Audit row reflects active count only.
        audit = _audit_rotate_rows(env["db_path"])
        details = json.loads(str(audit[0]["details_json"]))
        assert details == {"rows_re_encrypted": 2}


# ---------------------------------------------------------------------------
# AC6 — empty DB succeeds with rows_re_encrypted=0.
# ---------------------------------------------------------------------------


class TestRotateEncryptionKeyEmpty:
    def test_empty_db_succeeds_with_zero_count(self, env: dict[str, str]) -> None:
        new_key = Fernet.generate_key().decode()
        _clear_buffers()
        # Force migrations to run so the DB file exists with schema.
        conn = get_connection(env["db_path"])
        try:
            _apply_migrations(conn)
        finally:
            conn.close()

        result = runner.invoke(
            app, ["rotate-encryption-key", "--new-key", new_key, "--yes"]
        )
        stdout, _ = _buffers()
        assert result.exit_code == 0
        assert f"Update KEY_REGISTRY_ENCRYPTION_KEY in .env to: {new_key}" in stdout

        audit = _audit_rotate_rows(env["db_path"])
        assert len(audit) == 1
        details = json.loads(str(audit[0]["details_json"]))
        assert details == {"rows_re_encrypted": 0}


# ---------------------------------------------------------------------------
# AC7 — missing OLD key exits 6.
# ---------------------------------------------------------------------------


class TestRotateEncryptionKeyMissingConfig:
    def test_missing_encryption_key_exits_6(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        new_key = Fernet.generate_key().decode()
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        _clear_buffers()
        result = runner.invoke(
            app, ["rotate-encryption-key", "--new-key", new_key, "--yes"]
        )
        _, stderr = _buffers()
        assert result.exit_code == 6
        assert "KEY_REGISTRY_ENCRYPTION_KEY" in stderr


# ---------------------------------------------------------------------------
# AC4 / AC exit 5 — DB errors surface as exit 5.
# ---------------------------------------------------------------------------


class TestRotateEncryptionKeyDbErrors:
    def test_db_unreachable_exits_5(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        new_key = Fernet.generate_key().decode()

        def _raise_sqlite(_path: Any) -> None:
            raise sqlite3.OperationalError("simulated unreachable DB")

        monkeypatch.setattr(system_cmd, "get_connection", _raise_sqlite)

        _clear_buffers()
        result = runner.invoke(
            app, ["rotate-encryption-key", "--new-key", new_key, "--yes"]
        )
        _, stderr = _buffers()
        assert result.exit_code == 5
        assert "Database error" in stderr


# ---------------------------------------------------------------------------
# AC8 — PII-austere INFO log; new-key appears only on the success line.
# ---------------------------------------------------------------------------


class TestRotateEncryptionKeyLogging:
    def test_log_has_no_pii_or_key_material(self, env: dict[str, str]) -> None:
        from comadre.logging import get_logger

        old_key = env["key"]
        new_key = Fernet.generate_key().decode()
        _seed_active_customer(
            env["db_path"],
            cid="cust_01loggingtest1",
            name="Ana Silva",
            canonical="12345678909",
            tax_id_kind="cpf",
            key=old_key,
        )

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
                ["rotate-encryption-key", "--new-key", new_key, "--yes"],
            )
        finally:
            logger.removeHandler(handler)

        stdout, stderr = _buffers()
        assert result.exit_code == 0

        log_text = "\n".join(r.getMessage() for r in records)
        assert "Encryption key rotated" in log_text
        assert "rows_re_encrypted=1" in log_text

        # PII / key material must never appear in logs.
        forbidden_in_log = [
            old_key,
            new_key,
            "gAAAAA",
            "12345678909",
            "123.456.789-09",
            "Ana Silva",
        ]
        for needle in forbidden_in_log:
            assert needle not in log_text, f"PII/key material {needle!r} leaked to logs"
        # 11-/14-digit runs banned.
        assert not re.search(r"\b\d{11,14}\b", log_text)

        # New key MAY appear on stdout (the success line) exactly once.
        assert stdout.count(new_key) == 1
        # New key MUST NOT appear on stderr (no prompts, no error panels).
        assert new_key not in stderr

        # The audit row's details_json carries the new-key NOWHERE.
        audit = _audit_rotate_rows(env["db_path"])
        assert new_key not in str(audit[0]["details_json"])
        assert old_key not in str(audit[0]["details_json"])


# ---------------------------------------------------------------------------
# AC9 / AC11 — flag + help surface.
# ---------------------------------------------------------------------------


class TestRotateEncryptionKeyFlags:
    def test_format_flag_is_not_accepted(self, env: dict[str, str]) -> None:
        new_key = Fernet.generate_key().decode()
        _clear_buffers()
        result = runner.invoke(
            app,
            [
                "rotate-encryption-key",
                "--new-key",
                new_key,
                "--yes",
                "--format",
                "json",
            ],
        )
        assert result.exit_code == 2

    def test_help_includes_example(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KEY_REGISTRY_DB_PATH", raising=False)
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        result = runner.invoke(app, ["rotate-encryption-key", "--help"])
        assert result.exit_code == 0
        ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        cleaned = ansi.sub("", result.stdout)
        for glyph in ("\u2502", "\u256d", "\u256e", "\u2570", "\u256f", "\u2500"):
            cleaned = cleaned.replace(glyph, " ")
        flat = re.sub(r"\s+", " ", cleaned)
        assert "--new-key" in flat
        assert "--yes" in flat
        assert "gAAAAA" in flat
