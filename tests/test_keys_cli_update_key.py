"""End-to-end CLI tests for ``comadre-keys update-key`` (Story 1.6)."""

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


def _seed_customer_and_key(
    db_path: str,
    *,
    billing_mode: str = "manual",
    rate_limit_rpm: int = 60,
    price_monthly: float = 149.0,
    status: str = "active",
    paid_until: str | None = None,
    notes: str = "",
    key_hash: str = "a" * 64,
    key_prefix: str = "Pq_abc12",
) -> tuple[str, str]:
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        cid = generate_customer_id()
        insert_customer(
            conn,
            CustomerRecord(
                id=cid,
                name="Helena Ribeiro",
                email="helena@clinica.com",
                tax_id_kind="cpf",
                tax_id_encrypted=b"gAAAAA-ciphertext",
                notes="",
                registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                deleted_at=None,
            ),
            actor="cli:tester",
        )
        kid = generate_key_id()
        insert_api_key(
            conn,
            ApiKeyRecord(
                id=kid,
                customer_id=cid,
                key_hash=key_hash,
                key_prefix=key_prefix,
                rate_limit_rpm=rate_limit_rpm,
                status=status,  # type: ignore[arg-type]
                billing_mode=billing_mode,  # type: ignore[arg-type]
                price_monthly=price_monthly,
                paid_until=paid_until,
                created_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                last_used_at=None,
                notes=notes,
            ),
            actor="cli:tester",
        )
        return cid, kid
    finally:
        conn.close()


def _fetch_api_key(db_path: str, kid: str) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, customer_id, key_hash, key_prefix, rate_limit_rpm, "
            "status, billing_mode, price_monthly, paid_until, created_at, "
            "last_used_at, notes FROM api_key WHERE id = ?",
            (kid,),
        ).fetchone()
        assert row is not None
        return dict(row)
    finally:
        conn.close()


def _latest_update_audit(db_path: str) -> dict[str, object] | None:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT actor, action, target_type, target_id, details_json "
            "FROM audit_log WHERE action = 'update_key' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _count_update_audits(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'update_key'"
            ).fetchone()[0]
        )
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# AC1..AC4 — happy paths.
# ---------------------------------------------------------------------------


class TestUpdateKeyHappy:
    def test_rpm_and_price_updates_both_columns(self, env: dict[str, str]) -> None:
        _cid, kid = _seed_customer_and_key(
            env["db_path"], rate_limit_rpm=60, price_monthly=149.0
        )
        _clear_buffers()

        result = runner.invoke(
            app, ["update-key", "Pq_abc12", "--rpm", "120", "--price", "199"]
        )
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr

        after = _fetch_api_key(env["db_path"], kid)
        assert after["rate_limit_rpm"] == 120
        assert after["price_monthly"] == 199.0

        # ConfirmationLine: arrow form + pt-BR currency.
        assert (
            "Updated: Pq_abc12 (Helena Ribeiro) \u2014 "
            "rpm: 60\u2192120, price: R$ 149,00\u2192R$ 199,00" in stdout
        )

        audit = _latest_update_audit(env["db_path"])
        assert audit is not None
        assert audit["action"] == "update_key"
        assert audit["target_type"] == "api_key"
        assert audit["target_id"] == kid
        assert json.loads(str(audit["details_json"])) == {"fields": ["price", "rpm"]}

    def test_rpm_only_updates_only_rpm(self, env: dict[str, str]) -> None:
        _cid, kid = _seed_customer_and_key(
            env["db_path"], rate_limit_rpm=60, price_monthly=149.0
        )
        before = _fetch_api_key(env["db_path"], kid)
        _clear_buffers()

        result = runner.invoke(app, ["update-key", "Pq_abc12", "--rpm", "120"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr

        after = _fetch_api_key(env["db_path"], kid)
        assert after["rate_limit_rpm"] == 120
        assert after["price_monthly"] == before["price_monthly"]
        assert "Updated: Pq_abc12 (Helena Ribeiro) \u2014 rpm: 60\u2192120" in stdout
        # No price clause on rpm-only.
        assert "price:" not in stdout
        audit = _latest_update_audit(env["db_path"])
        assert audit is not None
        assert json.loads(str(audit["details_json"])) == {"fields": ["rpm"]}

    def test_price_only_updates_only_price(self, env: dict[str, str]) -> None:
        _cid, kid = _seed_customer_and_key(
            env["db_path"], rate_limit_rpm=120, price_monthly=149.0
        )
        before = _fetch_api_key(env["db_path"], kid)
        _clear_buffers()

        result = runner.invoke(app, ["update-key", "Pq_abc12", "--price", "199"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr

        after = _fetch_api_key(env["db_path"], kid)
        assert after["price_monthly"] == 199.0
        assert after["rate_limit_rpm"] == before["rate_limit_rpm"]
        assert (
            "Updated: Pq_abc12 (Helena Ribeiro) \u2014 "
            "price: R$ 149,00\u2192R$ 199,00" in stdout
        )
        audit = _latest_update_audit(env["db_path"])
        assert audit is not None
        assert json.loads(str(audit["details_json"])) == {"fields": ["price"]}

    def test_notes_flag_replaces_existing_notes_not_append(
        self, env: dict[str, str]
    ) -> None:
        _cid, kid = _seed_customer_and_key(
            env["db_path"], notes="bundled into infra package"
        )
        _clear_buffers()

        result = runner.invoke(
            app,
            [
                "update-key",
                "Pq_abc12",
                "--notes",
                "upgraded 2026-05-12 from 60->120rpm",
            ],
        )
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr

        after = _fetch_api_key(env["db_path"], kid)
        # REPLACE semantics — old note is gone.
        assert after["notes"] == "upgraded 2026-05-12 from 60->120rpm"
        assert "Updated: Pq_abc12 (Helena Ribeiro) \u2014 notes updated" in stdout
        audit = _latest_update_audit(env["db_path"])
        assert audit is not None
        assert json.loads(str(audit["details_json"])) == {"fields": ["notes"]}

    def test_all_three_flags_in_one_txn(self, env: dict[str, str]) -> None:
        _cid, kid = _seed_customer_and_key(
            env["db_path"],
            rate_limit_rpm=60,
            price_monthly=149.0,
            notes="original",
        )
        _clear_buffers()

        result = runner.invoke(
            app,
            [
                "update-key",
                "Pq_abc12",
                "--rpm",
                "120",
                "--price",
                "199",
                "--notes",
                "upgraded 2026-05-12",
            ],
        )
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr

        after = _fetch_api_key(env["db_path"], kid)
        assert after["rate_limit_rpm"] == 120
        assert after["price_monthly"] == 199.0
        assert after["notes"] == "upgraded 2026-05-12"

        assert (
            "Updated: Pq_abc12 (Helena Ribeiro) \u2014 "
            "rpm: 60\u2192120, price: R$ 149,00\u2192R$ 199,00, notes updated" in stdout
        )
        assert _count_update_audits(env["db_path"]) == 1
        audit = _latest_update_audit(env["db_path"])
        assert audit is not None
        assert json.loads(str(audit["details_json"])) == {
            "fields": ["notes", "price", "rpm"]
        }

    def test_rolls_back_when_log_event_fails(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _cid, kid = _seed_customer_and_key(
            env["db_path"], rate_limit_rpm=60, price_monthly=149.0
        )
        before = _fetch_api_key(env["db_path"], kid)
        audit_before = _count_update_audits(env["db_path"])

        import comadre.keys.audit as audit_module

        original = audit_module.log_event

        def _boom(*args: object, **kwargs: object) -> None:
            if kwargs.get("action") == "update_key":
                raise sqlite3.IntegrityError("forced audit failure")
            return original(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(audit_module, "log_event", _boom)

        _clear_buffers()
        result = runner.invoke(
            app,
            [
                "update-key",
                "Pq_abc12",
                "--rpm",
                "120",
                "--price",
                "199",
                "--notes",
                "changed",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 5, stderr
        assert "Database error" in stderr

        after = _fetch_api_key(env["db_path"], kid)
        for col in ("rate_limit_rpm", "price_monthly", "notes"):
            assert after[col] == before[col], col
        assert _count_update_audits(env["db_path"]) == audit_before


# ---------------------------------------------------------------------------
# AC5 — usage errors.
# ---------------------------------------------------------------------------


class TestUpdateKeyUsageErrors:
    def test_without_flags_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )

        result = runner.invoke(app, ["update-key", "Pq_abc12"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert (
            "Usage error: at least one of --rpm, --price, or --notes is required"
            in stderr
        )
        # Usage check fires before DB open.
        assert not (tmp_path / "registry.db").exists()

    def test_complimentary_plus_price_exits_2(self, env: dict[str, str]) -> None:
        _seed_customer_and_key(
            env["db_path"],
            billing_mode="complimentary",
            price_monthly=0.0,
        )
        _clear_buffers()
        result = runner.invoke(app, ["update-key", "Pq_abc12", "--price", "199"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --price is not applicable to complimentary keys" in stderr

    def test_rpm_zero_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )
        result = runner.invoke(app, ["update-key", "Pq_abc12", "--rpm", "0"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --rpm must be between 1 and 10000" in stderr
        assert not (tmp_path / "registry.db").exists()

    def test_rpm_above_cap_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )
        result = runner.invoke(app, ["update-key", "Pq_abc12", "--rpm", "50000"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --rpm must be between 1 and 10000" in stderr

    def test_price_negative_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )
        result = runner.invoke(app, ["update-key", "Pq_abc12", "--price", "-5"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --price must be positive for manual billing mode" in stderr

    def test_price_nan_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )
        result = runner.invoke(app, ["update-key", "Pq_abc12", "--price", "nan"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --price must be a finite number" in stderr

    def test_notes_nul_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )
        result = runner.invoke(
            app, ["update-key", "Pq_abc12", "--notes", "ok\x00danger"]
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --notes contains illegal characters" in stderr
        assert "NUL" in stderr
        assert not (tmp_path / "registry.db").exists()

    def test_notes_newline_exits_2(
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
            ["update-key", "Pq_abc12", "--notes", "ok\nforge"],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --notes must be a single line" in stderr

    def test_notes_carriage_return_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )
        result = runner.invoke(app, ["update-key", "Pq_abc12", "--notes", "a\rb"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --notes must be a single line" in stderr

    def test_notes_oversize_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("API_KEY", "test-api-key")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )
        huge = "x" * 1025
        result = runner.invoke(app, ["update-key", "Pq_abc12", "--notes", huge])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --notes exceeds 1024 characters" in stderr


# ---------------------------------------------------------------------------
# AC6 — revoked key.
# ---------------------------------------------------------------------------


class TestUpdateKeyRevoked:
    def test_revoked_key_exits_3(self, env: dict[str, str]) -> None:
        _seed_customer_and_key(env["db_path"], status="revoked")
        _clear_buffers()
        result = runner.invoke(app, ["update-key", "Pq_abc12", "--rpm", "120"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Key is revoked: Pq_abc12" in stderr
        assert _count_update_audits(env["db_path"]) == 0


# ---------------------------------------------------------------------------
# AC7 — not-found / ambiguous / customer-id / truncation.
# ---------------------------------------------------------------------------


class TestUpdateKeyNotFound:
    def test_missing_key_exits_3(self, env: dict[str, str]) -> None:
        # Seed something so the DB exists (migrations applied).
        _seed_customer_and_key(env["db_path"])
        _clear_buffers()
        result = runner.invoke(app, ["update-key", "nokey123", "--rpm", "120"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Key not found: nokey123" in stderr
        assert "list-keys" in stderr

    def test_customer_id_exits_2(self, env: dict[str, str]) -> None:
        cid, _kid = _seed_customer_and_key(env["db_path"])
        _clear_buffers()
        result = runner.invoke(app, ["update-key", cid, "--rpm", "120"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: key identifier required (got customer ID)" in stderr

    def test_ambiguous_prefix_exits_3(self, env: dict[str, str]) -> None:
        cid, _kid = _seed_customer_and_key(
            env["db_path"], key_prefix="Pq_abc12", key_hash="a" * 64
        )
        conn = get_connection(env["db_path"])
        try:
            insert_api_key(
                conn,
                ApiKeyRecord(
                    id=generate_key_id(),
                    customer_id=cid,
                    key_hash="b" * 64,
                    key_prefix="Pq_abc12",
                    rate_limit_rpm=60,
                    status="active",
                    billing_mode="manual",
                    price_monthly=149.0,
                    paid_until=None,
                    created_at=datetime(2026, 4, 16, 13, 0, 0, tzinfo=UTC),
                    last_used_at=None,
                    notes="",
                ),
                actor="cli:tester",
            )
        finally:
            conn.close()

        _clear_buffers()
        result = runner.invoke(app, ["update-key", "Pq_abc12", "--rpm", "120"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Ambiguous prefix: multiple keys match 'Pq_abc12'" in stderr

    def test_error_title_truncates_long_operator_input(
        self, env: dict[str, str]
    ) -> None:
        _seed_customer_and_key(env["db_path"])
        _clear_buffers()
        huge = "x" * 5000
        result = runner.invoke(app, ["update-key", huge, "--rpm", "120"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        # Truncated to 80 chars + ellipsis.
        assert "\u2026" in stderr
        # The 81st raw char should NOT appear as a continuous 81-char run.
        assert "x" * 100 not in stderr


# ---------------------------------------------------------------------------
# AC17 — help surface.
# ---------------------------------------------------------------------------


class TestUpdateKeyHelp:
    def test_update_key_help_has_realistic_examples(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KEY_REGISTRY_DB_PATH", raising=False)
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)

        result = runner.invoke(app, ["update-key", "--help"])
        assert result.exit_code == 0

        ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        cleaned = ansi.sub("", result.stdout)
        for glyph in ("\u2502", "\u256d", "\u256e", "\u2570", "\u256f", "\u2500"):
            cleaned = cleaned.replace(glyph, " ")
        flat = re.sub(r"\s+", " ", cleaned)

        assert "Pq_abc12" in flat
        assert "120" in flat
        assert "199" in flat
        assert "comadre-keys update-key Pq_abc12 --rpm 120 --price 199" in flat

    def test_update_key_help_does_not_touch_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KEY_REGISTRY_DB_PATH", raising=False)
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        result = runner.invoke(app, ["update-key", "--help"])
        assert result.exit_code == 0
        assert not (tmp_path / "registry.db").exists()


# ---------------------------------------------------------------------------
# AC18 — log + audit sanitization.
# ---------------------------------------------------------------------------


class TestUpdateKeySanitization:
    def test_audit_details_json_via_json_loads_equality(
        self, env: dict[str, str]
    ) -> None:
        _seed_customer_and_key(env["db_path"])
        result = runner.invoke(
            app,
            [
                "update-key",
                "Pq_abc12",
                "--rpm",
                "120",
                "--price",
                "199",
                "--notes",
                "ops-note",
            ],
        )
        assert result.exit_code == 0
        audit = _latest_update_audit(env["db_path"])
        assert audit is not None
        parsed = json.loads(str(audit["details_json"]))
        assert parsed == {"fields": ["notes", "price", "rpm"]}

    def test_audit_details_has_no_pii_values(self, env: dict[str, str]) -> None:
        _seed_customer_and_key(env["db_path"])
        secret_note = "sensitive-operator-note-9999"
        result = runner.invoke(
            app,
            [
                "update-key",
                "Pq_abc12",
                "--rpm",
                "9999",
                "--price",
                "12345.67",
                "--notes",
                secret_note,
            ],
        )
        assert result.exit_code == 0
        audit = _latest_update_audit(env["db_path"])
        assert audit is not None
        serialized = str(audit)
        # Values not leaked into audit row.
        assert secret_note not in serialized
        assert "9999" not in serialized
        assert "12345.67" not in serialized
        assert "Helena Ribeiro" not in serialized

    def test_log_has_no_pii(self, env: dict[str, str]) -> None:
        from comadre.logging import get_logger

        _seed_customer_and_key(env["db_path"])
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
                    "update-key",
                    "Pq_abc12",
                    "--rpm",
                    "120",
                    "--price",
                    "199",
                    "--notes",
                    "sensitive",
                ],
            )
        finally:
            logger.removeHandler(handler)

        assert result.exit_code == 0
        updated = [r for r in records if "Updated key" in r.getMessage()]
        assert updated
        joined = "\n".join(r.getMessage() for r in updated)
        assert "fields=notes,price,rpm" in joined
        assert "199" not in joined
        assert "sensitive" not in joined
        assert "Helena Ribeiro" not in joined


# ---------------------------------------------------------------------------
# AC19 — read-after-write via `show`.
# ---------------------------------------------------------------------------


class TestUpdateKeyReadAfterWrite:
    def test_then_show_reflects_changes(self, env: dict[str, str]) -> None:
        _seed_customer_and_key(env["db_path"], rate_limit_rpm=60, price_monthly=149.0)
        r_upd = runner.invoke(
            app,
            [
                "update-key",
                "Pq_abc12",
                "--rpm",
                "120",
                "--price",
                "199",
                "--notes",
                "bumped",
            ],
        )
        assert r_upd.exit_code == 0
        _clear_buffers()
        r_show = runner.invoke(app, ["show", "Pq_abc12", "--format", "json"])
        stdout, _stderr = _buffers()
        assert r_show.exit_code == 0
        payload = json.loads(stdout)
        assert payload["target"]["rate_limit_rpm"] == 120
        assert payload["target"]["price_monthly"] == 199.0
        assert payload["target"]["notes"] == "bumped"


# ---------------------------------------------------------------------------
# Regression — issue-key still works after Story 1.6 commands landed.
# ---------------------------------------------------------------------------


class TestIssueKeyStillWorks:
    def test_issue_key_smoke(self, env: dict[str, str]) -> None:
        _cid, _kid = _seed_customer_and_key(env["db_path"])
        _clear_buffers()
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                _cid,
                "--rpm",
                "60",
                "--price",
                "149",
            ],
        )
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        # KeyPanel rendered — double-border + plaintext line.
        assert "API KEY (copy now" in stdout
