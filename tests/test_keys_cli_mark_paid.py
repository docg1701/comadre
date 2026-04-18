"""End-to-end CLI tests for ``comadre-keys mark-paid`` (Story 3.1)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
import time
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


# Story 2.3 PII-leak guard — any match in an INFO log line is a FR37 / NFR15 regression.
_PII_FORBIDDEN_RE = re.compile(
    r"cmdr_live_|[0-9a-f]{64}|[0-9]{11,14}|@[a-z0-9.-]+\.[a-z]{2,}",
    re.IGNORECASE,
)


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


def _seed_customer_and_key(
    db_path: str,
    *,
    billing_mode: str = "manual",
    status: str = "active",
    paid_until: str | None = None,
    key_hash: str = "a" * 64,
    key_prefix: str = "Pq_abc12",
    customer_name: str = "Pedro Lopes",
    customer_id: str | None = None,
) -> tuple[str, str]:
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        cid = customer_id or generate_customer_id()
        insert_customer(
            conn,
            CustomerRecord(
                id=cid,
                name=customer_name,
                email="pedro@clinica.com",
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
                rate_limit_rpm=60,
                status=status,  # type: ignore[arg-type]
                billing_mode=billing_mode,  # type: ignore[arg-type]
                price_monthly=149.0 if billing_mode == "manual" else 0.0,
                paid_until=paid_until,
                created_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                last_used_at=None,
                notes="",
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


def _latest_mark_paid_audit(db_path: str) -> dict[str, object] | None:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT actor, action, target_type, target_id, details_json "
            "FROM audit_log WHERE action = 'mark_paid' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _count_mark_paid_audits(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'mark_paid'"
            ).fetchone()[0]
        )
    finally:
        conn.close()


def _sentinel_mtime_ns(db_path: str) -> int:
    sentinel = Path(db_path + ".invalidate")
    if not sentinel.exists():
        return 0
    return sentinel.stat().st_mtime_ns


def _advance_sentinel_past(db_path: str) -> int:
    import os

    sentinel = Path(db_path + ".invalidate")
    sentinel.touch(exist_ok=True)
    past = time.time() - 2.0
    os.utime(sentinel, (past, past))
    return sentinel.stat().st_mtime_ns


# ---------------------------------------------------------------------------
# AC1 / AC2 / AC8 — happy path.
# ---------------------------------------------------------------------------


class TestMarkPaidActivePath:
    def test_sets_paid_until_and_keeps_status_active(self, env: dict[str, str]) -> None:
        _cid, kid = _seed_customer_and_key(
            env["db_path"], status="active", paid_until="2026-05-05"
        )
        _clear_buffers()

        t0 = time.perf_counter()
        result = runner.invoke(app, ["mark-paid", "Pq_abc12", "--until", "2026-06-05"])
        elapsed_ms = (time.perf_counter() - t0) * 1000

        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        # Advisory timing (AC1 footnote) — generous CI cap at 1000 ms.
        assert elapsed_ms < 1000, f"mark-paid took {elapsed_ms:.0f} ms"

        after = _fetch_api_key(env["db_path"], kid)
        assert after["paid_until"] == "2026-06-05"
        assert after["status"] == "active"
        assert (
            "Marked paid: Pq_abc12 (Pedro Lopes) \u2192 paid until 2026-06-05" in stdout
        )
        # No reactivated suffix on the active path.
        assert "(reactivated)" not in stdout

        audit = _latest_mark_paid_audit(env["db_path"])
        assert audit is not None
        assert audit["target_type"] == "api_key"
        assert audit["target_id"] == kid
        parsed = json.loads(str(audit["details_json"]))
        assert parsed == {"paid_until": "2026-06-05", "reactivated": False}
        assert str(audit["actor"]).startswith("cli:")

    def test_sentinel_mtime_advances(self, env: dict[str, str]) -> None:
        _cid, _kid = _seed_customer_and_key(
            env["db_path"], status="active", paid_until="2026-05-05"
        )
        before = _advance_sentinel_past(env["db_path"])
        _clear_buffers()
        result = runner.invoke(app, ["mark-paid", "Pq_abc12", "--until", "2026-06-05"])
        assert result.exit_code == 0
        after = _sentinel_mtime_ns(env["db_path"])
        assert after > before


# ---------------------------------------------------------------------------
# AC3 — suspended key reactivates + paid_until extends.
# ---------------------------------------------------------------------------


class TestMarkPaidReactivation:
    def test_suspended_reactivates_and_extends(self, env: dict[str, str]) -> None:
        _cid, kid = _seed_customer_and_key(
            env["db_path"], status="suspended", paid_until="2026-04-05"
        )
        _clear_buffers()
        result = runner.invoke(app, ["mark-paid", "Pq_abc12", "--until", "2026-06-05"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        after = _fetch_api_key(env["db_path"], kid)
        assert after["status"] == "active"
        assert after["paid_until"] == "2026-06-05"
        assert (
            "Marked paid: Pq_abc12 (Pedro Lopes) \u2192 paid until 2026-06-05 "
            "(reactivated)" in stdout
        )
        audit = _latest_mark_paid_audit(env["db_path"])
        assert audit is not None
        parsed = json.loads(str(audit["details_json"]))
        assert parsed == {"paid_until": "2026-06-05", "reactivated": True}


# ---------------------------------------------------------------------------
# AC5 — complimentary short-circuit (exit 0 informational).
# ---------------------------------------------------------------------------


class TestMarkPaidComplimentary:
    def test_complimentary_key_exits_0_with_message(self, env: dict[str, str]) -> None:
        _cid, kid = _seed_customer_and_key(
            env["db_path"],
            billing_mode="complimentary",
            key_prefix="Cx_abcd12",
            customer_name="Sofia Lima",
        )
        before = _fetch_api_key(env["db_path"], kid)
        _clear_buffers()
        result = runner.invoke(app, ["mark-paid", "Cx_abcd12", "--until", "2026-06-05"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert (
            "Key Cx_abcd12 is complimentary — no payment tracking required." in stdout
        )
        assert _count_mark_paid_audits(env["db_path"]) == 0
        after = _fetch_api_key(env["db_path"], kid)
        assert after == before
        # paid_until must stay NULL — the informational path does not write.
        assert after["paid_until"] is None


# ---------------------------------------------------------------------------
# AC6 — revoked exits 3.
# ---------------------------------------------------------------------------


class TestMarkPaidRevoked:
    def test_revoked_exits_3_with_hint(self, env: dict[str, str]) -> None:
        _cid, kid = _seed_customer_and_key(env["db_path"], status="revoked")
        before = _fetch_api_key(env["db_path"], kid)
        _clear_buffers()
        result = runner.invoke(app, ["mark-paid", "Pq_abc12", "--until", "2026-06-05"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Key is revoked: Pq_abc12" in stderr
        assert "issue-key" in stderr
        after = _fetch_api_key(env["db_path"], kid)
        assert after == before
        assert _count_mark_paid_audits(env["db_path"]) == 0


# ---------------------------------------------------------------------------
# AC7 — --until shape validation (exit 2, no DB open).
# ---------------------------------------------------------------------------


class TestMarkPaidUntilShape:
    def _prepare(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        monkeypatch.setenv(
            "KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode()
        )

    def test_empty_until_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._prepare(tmp_path, monkeypatch)
        result = runner.invoke(app, ["mark-paid", "Pq_abc12", "--until", ""])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --until must be an ISO date" in stderr
        # Fail-fast before DB open.
        assert not (tmp_path / "registry.db").exists()

    def test_tomorrow_literal_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._prepare(tmp_path, monkeypatch)
        result = runner.invoke(app, ["mark-paid", "Pq_abc12", "--until", "tomorrow"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --until must be an ISO date" in stderr
        assert not (tmp_path / "registry.db").exists()

    def test_invalid_month_exits_2(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        self._prepare(tmp_path, monkeypatch)
        result = runner.invoke(app, ["mark-paid", "Pq_abc12", "--until", "2026-13-40"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --until must be an ISO date" in stderr

    def test_compact_iso_normalizes_to_canonical_form(
        self, env: dict[str, str]
    ) -> None:
        """``20260605`` → stored as ``2026-06-05`` — lexicographic-sort safe."""
        _cid, kid = _seed_customer_and_key(env["db_path"], status="active")
        _clear_buffers()
        result = runner.invoke(app, ["mark-paid", "Pq_abc12", "--until", "20260605"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        after = _fetch_api_key(env["db_path"], kid)
        assert after["paid_until"] == "2026-06-05"
        assert "paid until 2026-06-05" in stdout


# ---------------------------------------------------------------------------
# AC8 — past dates accepted.
# ---------------------------------------------------------------------------


class TestMarkPaidPastDate:
    def test_past_date_accepted_silently(self, env: dict[str, str]) -> None:
        _cid, kid = _seed_customer_and_key(env["db_path"], status="active")
        _clear_buffers()
        result = runner.invoke(app, ["mark-paid", "Pq_abc12", "--until", "2020-01-01"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        # No warning, no reject.
        assert "Warning" not in stderr
        assert "Warning" not in stdout
        after = _fetch_api_key(env["db_path"], kid)
        assert after["paid_until"] == "2020-01-01"
        audit = _latest_mark_paid_audit(env["db_path"])
        assert audit is not None
        parsed = json.loads(str(audit["details_json"]))
        assert parsed == {"paid_until": "2020-01-01", "reactivated": False}


# ---------------------------------------------------------------------------
# AC16 / AC17 / AC18 — identifier resolution errors (shared with Story 1.6).
# ---------------------------------------------------------------------------


class TestMarkPaidIdentifierResolution:
    def test_customer_id_input_exits_2(self, env: dict[str, str]) -> None:
        cid, _kid = _seed_customer_and_key(env["db_path"])
        _clear_buffers()
        result = runner.invoke(app, ["mark-paid", cid, "--until", "2026-06-05"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: key identifier required (got customer ID)" in stderr
        assert _count_mark_paid_audits(env["db_path"]) == 0

    def test_missing_prefix_exits_3(self, env: dict[str, str]) -> None:
        _seed_customer_and_key(env["db_path"])
        _clear_buffers()
        result = runner.invoke(app, ["mark-paid", "nokey123", "--until", "2026-06-05"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Key not found: nokey123" in stderr
        assert "list-keys" in stderr

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
        result = runner.invoke(app, ["mark-paid", "Pq_abc12", "--until", "2026-06-05"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Ambiguous prefix: multiple keys match 'Pq_abc12'" in stderr


# ---------------------------------------------------------------------------
# AC19 — PII-austere INFO logs (FR37 / NFR15).
# ---------------------------------------------------------------------------


class TestMarkPaidLogging:
    def test_info_log_has_no_customer_pii(self, env: dict[str, str]) -> None:
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
                app, ["mark-paid", "Pq_abc12", "--until", "2026-06-05"]
            )
        finally:
            logger.removeHandler(handler)

        assert result.exit_code == 0
        mark_paid = [r for r in records if "Marked paid" in r.getMessage()]
        assert mark_paid
        joined = "\n".join(r.getMessage() for r in mark_paid)
        assert "id=key_" in joined
        assert "paid_until=2026-06-05" in joined
        assert "reactivated=False" in joined
        # PII-forbidden regex: no CPF/CNPJ digit runs, no email, no hash,
        # no cmdr_live_ plaintext.
        assert not _PII_FORBIDDEN_RE.search(joined), joined
        assert "Pedro Lopes" not in joined


# ---------------------------------------------------------------------------
# AC20 — help output surfaces the command at top level.
# ---------------------------------------------------------------------------


class TestMarkPaidHelp:
    def test_help_lists_command_flat(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "mark-paid" in result.stdout
        assert "Confirm payment for a key and extend its validity" in result.stdout
