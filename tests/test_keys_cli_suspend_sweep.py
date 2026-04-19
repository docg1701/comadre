"""End-to-end CLI tests for ``comadre-keys suspend-sweep`` (Story 3.3)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, date, datetime
from io import StringIO
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from rich.console import Console
from typer.testing import CliRunner

import comadre.keys.cli.commands.system as system_cmd
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


_PII_FORBIDDEN_RE = re.compile(
    # cmdr_live_*          plaintext bearer prefix
    # [0-9a-f]{64}         SHA-256 hash (raw storage form)
    # [0-9]{11,14}         CPF (11) / CNPJ (14) unformatted
    # \d{3}\.\d{3}\.\d{3}-\d{2}        CPF formatted (xxx.xxx.xxx-xx)
    # \d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}  CNPJ formatted (xx.xxx.xxx/xxxx-xx)
    # @<domain>            email address
    r"cmdr_live_|[0-9a-f]{64}|[0-9]{11,14}"
    r"|\d{3}\.\d{3}\.\d{3}-\d{2}"
    r"|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}"
    r"|@[a-z0-9.-]+\.[a-z]{2,}",
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


def _freeze_today(monkeypatch: pytest.MonkeyPatch, today: date) -> None:
    monkeypatch.setattr(system_cmd, "resolve_today_in_tz", lambda _tz: today)


def _buffers() -> tuple[str, str]:
    stdout_file = output_mod._stdout_console.file  # type: ignore[union-attr]
    stderr_file = output_mod._stderr_console.file  # type: ignore[union-attr]
    return stdout_file.getvalue(), stderr_file.getvalue()


def _clear_buffers() -> None:
    for attr in ("_stdout_console", "_stderr_console"):
        console = getattr(output_mod, attr)
        console.file.seek(0)  # type: ignore[union-attr]
        console.file.truncate()  # type: ignore[union-attr]


def _seed_customer(conn: sqlite3.Connection, *, name: str, email: str) -> str:
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
            registered_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
            deleted_at=None,
        ),
        actor="cli:tester",
    )
    return cid


def _seed_key(
    conn: sqlite3.Connection,
    *,
    customer_id: str,
    key_prefix: str,
    key_hash: str,
    status: str = "active",
    billing_mode: str = "manual",
    paid_until: str | None = None,
) -> str:
    kid = generate_key_id()
    insert_api_key(
        conn,
        ApiKeyRecord(
            id=kid,
            customer_id=customer_id,
            key_hash=key_hash,
            key_prefix=key_prefix,
            rate_limit_rpm=60,
            status=status,  # type: ignore[arg-type]
            billing_mode=billing_mode,  # type: ignore[arg-type]
            price_monthly=149.0 if billing_mode == "manual" else 0.0,
            paid_until=paid_until,
            created_at=datetime(2026, 4, 1, 12, 0, 0, tzinfo=UTC),
            last_used_at=None,
            notes="",
        ),
        actor="cli:tester",
    )
    return kid


def _seed_expired_portfolio(db_path: str) -> dict[str, str]:
    """Three expired manual keys + two paid keys."""
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        ids: dict[str, str] = {}
        c1 = _seed_customer(conn, name="Pedro Lopes", email="p@c.com")
        c2 = _seed_customer(conn, name="Marcos Silva", email="m@c.com")
        c3 = _seed_customer(conn, name="Helena Ribeiro", email="h@c.com")
        ids["p1"] = _seed_key(
            conn,
            customer_id=c1,
            key_prefix="Pq_abc12",
            key_hash="a" * 64,
            paid_until="2026-04-04",
        )
        ids["p2"] = _seed_key(
            conn,
            customer_id=c2,
            key_prefix="Mx_def34",
            key_hash="b" * 64,
            paid_until="2026-04-05",
        )
        ids["p3"] = _seed_key(
            conn,
            customer_id=c3,
            key_prefix="Hx_ghi56",
            key_hash="c" * 64,
            paid_until="2026-04-01",
        )
        ids["paid1"] = _seed_key(
            conn,
            customer_id=c1,
            key_prefix="Pd_xxx00",
            key_hash="d" * 64,
            paid_until="2026-04-10",
        )
        ids["paid2"] = _seed_key(
            conn,
            customer_id=c2,
            key_prefix="Pe_yyy00",
            key_hash="e" * 64,
            paid_until="2026-04-30",
        )
        return ids
    finally:
        conn.close()


def _fetch_status(db_path: str, key_id: str) -> str:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT status FROM api_key WHERE id = ?", (key_id,)
        ).fetchone()
        assert row is not None
        return str(row["status"])
    finally:
        conn.close()


def _count_audit(db_path: str, *, action: str | None = None) -> int:
    conn = sqlite3.connect(db_path)
    try:
        if action is None:
            row = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()
        else:
            row = conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = ?", (action,)
            ).fetchone()
        return int(row[0])
    finally:
        conn.close()


def _fetch_summary_row(db_path: str) -> dict[str, object] | None:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT occurred_at, actor, target_id, details_json "
            "FROM audit_log WHERE action = 'cron_suspend' "
            "AND target_type = 'system' ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


class TestHappyPath:
    def test_full_sweep_happy_path(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC1 / AC2 / AC3 / AC15 end-to-end."""
        ids = _seed_expired_portfolio(env["db_path"])
        _freeze_today(monkeypatch, date(2026, 4, 6))
        _clear_buffers()

        result = runner.invoke(app, ["suspend-sweep"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert "Suspension sweep completed: 3 key(s) suspended" in stdout
        assert "cutoff 2026-04-06" in stdout

        for k in ("p1", "p2", "p3"):
            assert _fetch_status(env["db_path"], ids[k]) == "suspended"
        for k in ("paid1", "paid2"):
            assert _fetch_status(env["db_path"], ids[k]) == "active"

        assert _count_audit(env["db_path"], action="suspend_key") >= 3
        assert _count_audit(env["db_path"], action="cron_suspend") == 1

        summary = _fetch_summary_row(env["db_path"])
        assert summary is not None
        assert summary["actor"] == "cron:suspension-sweep"
        assert summary["target_id"] is None
        parsed = json.loads(str(summary["details_json"]))
        assert parsed == {"swept_count": 3, "cutoff_date": "2026-04-06"}

    def test_zero_row_sweep_exits_0(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC4 — zero-row sweep still records the summary row."""
        conn = get_connection(env["db_path"])
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn, name="Solo", email="s@c.com")
            _seed_key(
                conn,
                customer_id=cid,
                key_prefix="K1_paid00",
                key_hash="a" * 64,
                paid_until="2026-04-30",
            )
        finally:
            conn.close()

        _freeze_today(monkeypatch, date(2026, 4, 6))
        _clear_buffers()
        result = runner.invoke(app, ["suspend-sweep"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert "0 key(s) suspended" in stdout
        assert _count_audit(env["db_path"], action="cron_suspend") == 1
        assert _count_audit(env["db_path"], action="suspend_key") == 0


class TestDryRun:
    def test_dry_run_writes_nothing(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC7 — --dry-run previews, does NOT mutate or audit."""
        ids = _seed_expired_portfolio(env["db_path"])
        _freeze_today(monkeypatch, date(2026, 4, 6))
        pre_audit = _count_audit(env["db_path"])
        _clear_buffers()

        result = runner.invoke(app, ["suspend-sweep", "--dry-run"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert "Dry-run preview: keys to suspend at cutoff 2026-04-06" in stdout
        assert "3 key(s) would be suspended" in stdout
        # All three still active, DB untouched.
        for k in ("p1", "p2", "p3"):
            assert _fetch_status(env["db_path"], ids[k]) == "active"
        assert _count_audit(env["db_path"]) == pre_audit

    def test_dry_run_empty_preview_message(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC8 — empty preview renders an informational line."""
        conn = get_connection(env["db_path"])
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn, name="Solo", email="s@c.com")
            _seed_key(
                conn,
                customer_id=cid,
                key_prefix="K1_paid00",
                key_hash="a" * 64,
                paid_until="2026-04-30",
            )
        finally:
            conn.close()

        _freeze_today(monkeypatch, date(2026, 4, 6))
        pre_audit = _count_audit(env["db_path"])
        _clear_buffers()
        result = runner.invoke(app, ["suspend-sweep", "--dry-run"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "No keys would be suspended by the sweep on 2026-04-06." in stdout
        assert _count_audit(env["db_path"]) == pre_audit


class TestConfigErrors:
    def test_missing_encryption_key_exits_6(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "registry.db"
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        _clear_buffers()
        result = runner.invoke(app, ["suspend-sweep"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 6
        assert "KEY_REGISTRY_ENCRYPTION_KEY" in stderr

    def test_invalid_billing_tz_exits_6(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BILLING_TIMEZONE", "Not/Real")
        _clear_buffers()
        result = runner.invoke(app, ["suspend-sweep"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 6
        assert "BILLING_TIMEZONE" in stderr


class TestDBError:
    def test_db_error_exits_5(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC / exit-5 — ``sqlite3.Error`` from ``get_connection`` maps to exit 5.

        Forces a deterministic ``sqlite3.OperationalError`` via monkeypatch
        so the assertion pins the exit-5 contract (not just ``!= 0``).
        """

        def _raise_sqlite_error(_path: Path) -> sqlite3.Connection:
            raise sqlite3.OperationalError("simulated DB failure")

        monkeypatch.setattr(system_cmd, "get_connection", _raise_sqlite_error)
        _clear_buffers()
        result = runner.invoke(app, ["suspend-sweep"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 5
        assert "Database error" in stderr


class TestPIIGuard:
    def test_pii_austere_log(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC13 — INFO log is PII-free."""
        from comadre.logging import get_logger

        _seed_expired_portfolio(env["db_path"])
        _freeze_today(monkeypatch, date(2026, 4, 6))
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
            result = runner.invoke(app, ["suspend-sweep"])
        finally:
            logger.removeHandler(handler)
        assert result.exit_code == 0
        sweep_records = [
            r for r in records if "Suspension sweep completed" in r.getMessage()
        ]
        assert sweep_records, [r.getMessage() for r in records]
        joined = "\n".join(r.getMessage() for r in sweep_records)
        assert "cutoff=2026-04-06" in joined
        assert "swept_count=3" in joined
        assert not _PII_FORBIDDEN_RE.search(joined), joined
        assert "Pedro Lopes" not in joined
        assert "Marcos Silva" not in joined
        assert "Helena Ribeiro" not in joined


class TestActorAndTimestamp:
    def test_actor_hardcoded_cron_suspension_sweep(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC15 — every new audit row has actor='cron:suspension-sweep'."""
        _seed_expired_portfolio(env["db_path"])
        _freeze_today(monkeypatch, date(2026, 4, 6))
        _clear_buffers()
        result = runner.invoke(app, ["suspend-sweep"])
        assert result.exit_code == 0
        conn = sqlite3.connect(env["db_path"])
        try:
            conn.row_factory = sqlite3.Row
            rows = list(
                conn.execute(
                    "SELECT actor FROM audit_log "
                    "WHERE action IN ('suspend_key', 'cron_suspend')"
                )
            )
        finally:
            conn.close()
        assert rows
        assert all(r["actor"] == "cron:suspension-sweep" for r in rows)

    def test_confirmation_line_contains_canonical_timestamp(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC3 — ConfirmationLine timestamp matches ``get_last_sweep_timestamp``."""
        _seed_expired_portfolio(env["db_path"])
        _freeze_today(monkeypatch, date(2026, 4, 6))
        _clear_buffers()
        result = runner.invoke(app, ["suspend-sweep"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        match = re.search(r"at (\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z)", stdout)
        assert match is not None, stdout
        shown = match.group(1)
        # Byte-identity with the DB's summary row.
        summary = _fetch_summary_row(env["db_path"])
        assert summary is not None
        assert summary["occurred_at"] == shown


class TestHelpSurface:
    def test_suspend_sweep_appears_in_top_level_help(self) -> None:
        """AC19 — ``comadre-keys --help`` surfaces the new verb at top level."""
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "suspend-sweep" in result.output


class TestIdempotence:
    def test_idempotent_second_run_suspends_nothing(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC17 — second run on the same today sweeps 0."""
        _seed_expired_portfolio(env["db_path"])
        _freeze_today(monkeypatch, date(2026, 4, 6))
        _clear_buffers()
        first = runner.invoke(app, ["suspend-sweep"])
        assert first.exit_code == 0
        _clear_buffers()
        second = runner.invoke(app, ["suspend-sweep"])
        stdout, _stderr = _buffers()
        assert second.exit_code == 0
        assert "0 key(s) suspended" in stdout
        # Two summary rows; per-key rows only from the first run.
        assert _count_audit(env["db_path"], action="cron_suspend") == 2
        assert _count_audit(env["db_path"], action="suspend_key") == 3


class TestCycle:
    def test_manual_rerun_after_mark_paid_reactivates_and_resweeps(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC18 — sweep → mark-paid → sweep cycle produces a coherent audit tail."""
        conn = get_connection(env["db_path"])
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn, name="Pedro Lopes", email="p@c.com")
            _seed_key(
                conn,
                customer_id=cid,
                key_prefix="Pq_abc12",
                key_hash="a" * 64,
                paid_until="2026-04-04",
            )
        finally:
            conn.close()

        # Day 1 — sweep suspends the key.
        _freeze_today(monkeypatch, date(2026, 4, 5))
        _clear_buffers()
        result = runner.invoke(app, ["suspend-sweep"])
        assert result.exit_code == 0

        # Day 2 — mark-paid reactivates until Day 3.
        _freeze_today(monkeypatch, date(2026, 4, 6))
        # mark-paid lives in the billing module; patch its clock too.
        import comadre.keys.cli.commands.billing as billing_cmd

        monkeypatch.setattr(
            billing_cmd, "_resolve_today_in_tz", lambda _tz: date(2026, 4, 6)
        )
        _clear_buffers()
        result = runner.invoke(app, ["mark-paid", "Pq_abc12", "--until", "2026-04-07"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert "(reactivated)" in stdout

        # Day 4 — sweep again, re-suspends.
        _freeze_today(monkeypatch, date(2026, 4, 8))
        _clear_buffers()
        result = runner.invoke(app, ["suspend-sweep"])
        assert result.exit_code == 0

        # Audit tail in chronological order: suspend_key, mark_paid, suspend_key.
        conn = sqlite3.connect(env["db_path"])
        try:
            conn.row_factory = sqlite3.Row
            tail = list(
                conn.execute(
                    "SELECT action, actor FROM audit_log "
                    "WHERE action IN ('suspend_key', 'mark_paid') "
                    "ORDER BY id ASC"
                )
            )
        finally:
            conn.close()
        actions = [r["action"] for r in tail]
        assert actions == ["suspend_key", "mark_paid", "suspend_key"]
        assert tail[0]["actor"] == "cron:suspension-sweep"
        assert str(tail[1]["actor"]).startswith("cli:")
        assert tail[2]["actor"] == "cron:suspension-sweep"
