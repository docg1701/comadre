"""Story 3.4 — end-to-end CLI tests for ``comadre-keys health``.

Mirrors the scaffolding in ``tests/test_keys_cli_cache_status.py`` (same
buffers fixture, env fixture, snapshot writer). Exercises the validation
ladder (exit 2 / 5 / 6 / 7), the exit-0-in-table-mode read-tier rule,
JSON payload structure, the AC15 read-only invariant, and the AC19
PII-austere log assertion.
"""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime, timedelta
from io import StringIO
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from rich.console import Console
from typer.testing import CliRunner

import comadre.keys.cli.commands.system as system_cmd
import comadre.keys.cli.output as output_mod
from comadre.config import get_settings
from comadre.keys.audit import log_event
from comadre.keys.cli.app import app
from comadre.keys.db import (
    _apply_migrations,
    generate_customer_id,
    generate_key_id,
    get_connection,
)

runner = CliRunner()


_PII_FORBIDDEN_RE = re.compile(
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


def _buffers() -> tuple[str, str]:
    stdout_file = output_mod._stdout_console.file  # type: ignore[union-attr]
    stderr_file = output_mod._stderr_console.file  # type: ignore[union-attr]
    return stdout_file.getvalue(), stderr_file.getvalue()


@pytest.fixture()
def env(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    key = Fernet.generate_key().decode()
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", key)
    return {"db_path": str(db_path), "key": key}


def _write_snapshot(
    db_path: str,
    *,
    age_seconds: int = 3,
    replica: str = "test-replica",
) -> Path:
    written = datetime.now(UTC) - timedelta(seconds=age_seconds)
    snapshot_path = Path(f"{db_path}.counters.{replica}.json")
    payload: dict[str, Any] = {
        "schema_version": 1,
        "written_at": written.strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{written.microsecond // 1000:03d}Z",
        "process_uptime_seconds": 60,
        "auth_cache": {
            "entries": 42,
            "maxsize": 4096,
            "ttl_seconds": 60,
            "hits": 1000,
            "misses": 10,
        },
        "per_key": {},
    }
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")
    return snapshot_path


def _write_marker(db_path: str, *, content: str | None = None) -> Path:
    marker = Path(f"{db_path}.cron-installed")
    marker.write_text(
        content or "schedule=30 0 * * *\ncron_tz=UTC",
        encoding="utf-8",
    )
    marker.chmod(0o600)
    return marker


def _write_backup(db_path: str) -> Path:
    """Drop a fresh ``*.backup-*.tar.gz.enc`` stub next to the DB.

    Story 4.3: the ``Last backup`` health row now demands a fresh archive
    to stay ``ok`` (warn otherwise). Every test that expects ``is_healthy``
    true must seed one via this helper.
    """
    archive = Path(f"{db_path}.backup-2026-04-20T02-00-00Z.tar.gz.enc")
    archive.write_bytes(b"encrypted-stub")
    return archive


def _write_backup_cron_marker(db_path: str, *, content: str | None = None) -> Path:
    """Drop the ``<db>.backup-cron-installed`` marker bootstrap.yml writes.

    Story 4.4: the ``Backup cron`` health row now demands the marker to
    stay ``ok`` (warn otherwise). Every healthy-path test must seed it.
    """
    marker = Path(f"{db_path}.backup-cron-installed")
    marker.write_text(
        content
        if content is not None
        else "schedule=0 2 * * *\ncron_tz=UTC\nretention_days=14\n",
        encoding="utf-8",
    )
    marker.chmod(0o600)
    return marker


def _seed_real_registry(db_path: str) -> None:
    """Seed a small realistic registry: customers, keys, audit trail."""
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        for idx, (name, email) in enumerate(
            (
                ("Helena Ribeiro", "helena@clinica.com"),
                ("Marcos Silva", "marcos@empresa.com"),
                ("Pedro Lopes", "pedro@consultorio.com"),
            )
        ):
            cid = generate_customer_id()
            conn.execute(
                "INSERT INTO customer ("
                "id, name, email, tax_id_kind, tax_id_encrypted, notes, "
                "registered_at, deleted_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    cid,
                    name,
                    email,
                    "cpf",
                    b"ciphertext",
                    "",
                    "2026-04-10T12:00:00Z",
                    None,
                ),
            )
            kid = generate_key_id()
            key_hash = f"{idx:064x}"
            prefix = name.upper().replace(" ", "")[:6].ljust(6, "X") + f"{idx:02d}"
            conn.execute(
                "INSERT INTO api_key ("
                "id, customer_id, key_hash, key_prefix, rate_limit_rpm, "
                "status, billing_mode, price_monthly, paid_until, "
                "created_at, last_used_at, notes"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    kid,
                    cid,
                    key_hash,
                    prefix,
                    60,
                    "active",
                    "manual",
                    149.0,
                    None,
                    "2026-04-10T12:00:00Z",
                    None,
                    "",
                ),
            )
        with conn:
            log_event(
                conn,
                actor="cron:suspension-sweep",
                action="cron_suspend",
                target_type="system",
                target_id=None,
                details={"swept_count": 0, "cutoff_date": "2026-04-18"},
            )
        conn.commit()
    finally:
        conn.close()


# ---------------------------------------------------------------------------
# Validation ladder
# ---------------------------------------------------------------------------


class TestUsageAndConfig:
    def test_invalid_format_exits_2(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["health", "--format", "xml"])
        assert result.exit_code == 2
        _, stderr = _buffers()
        assert "--format must be table or json" in stderr
        assert "table, json" in stderr

    def test_missing_encryption_key_exits_6(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 6
        _, stderr = _buffers()
        assert "KEY_REGISTRY_ENCRYPTION_KEY" in stderr

    def test_invalid_billing_tz_exits_6(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BILLING_TIMEZONE", "Mars/Olympus_Mons")
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 6
        _, stderr = _buffers()
        assert "BILLING_TIMEZONE" in stderr

    def test_db_unreachable_exits_5(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        def _raise_sqlite(_path: Any) -> None:
            raise sqlite3.OperationalError("simulated unreachable DB")

        monkeypatch.setattr(system_cmd, "get_connection", _raise_sqlite)
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 5
        _, stderr = _buffers()
        assert "Database error" in stderr


# ---------------------------------------------------------------------------
# Table mode — read-tier exit 0
# ---------------------------------------------------------------------------


class TestTableMode:
    def test_healthy_exits_0_renders_panel(self, env: dict[str, str]) -> None:
        _seed_real_registry(env["db_path"])
        _write_marker(env["db_path"])
        _write_snapshot(env["db_path"])
        _write_backup(env["db_path"])
        _write_backup_cron_marker(env["db_path"])
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0, _buffers()
        stdout, _ = _buffers()
        assert "System Health" in stdout
        assert "Healthy." in stdout

    def test_unhealthy_still_exits_0_in_table_mode(self, env: dict[str, str]) -> None:
        """AC14 / UX-DR10 — table mode never flips exit code on warnings."""
        _seed_real_registry(env["db_path"])
        # Drift DB perms → Database check flips to warn.
        Path(env["db_path"]).chmod(0o644)
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0
        stdout, _ = _buffers()
        assert "Unhealthy:" in stdout
        assert "warning(s)" in stdout


# ---------------------------------------------------------------------------
# JSON mode — exit 7 on unhealthy
# ---------------------------------------------------------------------------


class TestJsonMode:
    def test_healthy_exits_0(self, env: dict[str, str]) -> None:
        _seed_real_registry(env["db_path"])
        _write_marker(env["db_path"])
        _write_snapshot(env["db_path"])
        _write_backup(env["db_path"])
        _write_backup_cron_marker(env["db_path"])
        result = runner.invoke(app, ["health", "--format", "json"])
        assert result.exit_code == 0, _buffers()
        stdout, _ = _buffers()
        payload = json.loads(stdout)
        assert payload["is_healthy"] is True
        assert payload["warn_count"] == 0
        assert payload["fail_count"] == 0
        # Canonical ISO-UTC shape.
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$", payload["generated_at"]
        )

    def test_unhealthy_exits_7(self, env: dict[str, str]) -> None:
        _seed_real_registry(env["db_path"])
        Path(env["db_path"]).chmod(0o644)
        result = runner.invoke(app, ["health", "--format", "json"])
        assert result.exit_code == 7
        stdout, _ = _buffers()
        payload = json.loads(stdout)
        assert payload["is_healthy"] is False
        assert payload["warn_count"] >= 1

    def test_payload_structure_is_stable(self, env: dict[str, str]) -> None:
        _seed_real_registry(env["db_path"])
        _write_marker(env["db_path"])
        _write_snapshot(env["db_path"])
        _write_backup(env["db_path"])
        _write_backup_cron_marker(env["db_path"])
        result = runner.invoke(app, ["health", "--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(_buffers()[0])
        assert set(payload.keys()) == {
            "is_healthy",
            "generated_at",
            "warn_count",
            "fail_count",
            "checks",
        }
        assert len(payload["checks"]) == 10
        labels = {c["label"] for c in payload["checks"]}
        assert labels == {
            "Database",
            "Schema version",
            "Customers",
            "Keys",
            "Last suspension sweep",
            "Cron",
            "Backup cron",
            "Timezone drift",
            "Last backup",
            "Auth cache",
        }
        for c in payload["checks"]:
            assert set(c.keys()) == {"label", "severity", "value", "detail", "data"}
            assert c["severity"] in {"ok", "info", "warn", "fail"}
            assert c["data"] is None or isinstance(c["data"], dict)

    def test_unknown_key_round_trips_through_jq_query(
        self, env: dict[str, str]
    ) -> None:
        """Canonical operator query surfaces exactly the unhealthy checks."""
        _seed_real_registry(env["db_path"])
        Path(env["db_path"]).chmod(0o644)
        result = runner.invoke(app, ["health", "--format", "json"])
        assert result.exit_code == 7
        payload = json.loads(_buffers()[0])
        non_ok = [c for c in payload["checks"] if c["severity"] in ("warn", "fail")]
        assert len(non_ok) == payload["warn_count"] + payload["fail_count"]


# ---------------------------------------------------------------------------
# Marker rendering
# ---------------------------------------------------------------------------


class TestMarkerRendering:
    def test_marker_schedule_rendered_verbatim(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Align runtime BILLING_TIMEZONE with the marker's cron_tz so the
        # F57 drift-detection row stays ``ok`` and we can assert the
        # marker-rendering contract in isolation.
        monkeypatch.setenv("BILLING_TIMEZONE", "America/Sao_Paulo")
        _seed_real_registry(env["db_path"])
        _write_marker(
            env["db_path"],
            content="schedule=30 0 * * *\ncron_tz=America/Sao_Paulo",
        )
        _write_backup(env["db_path"])
        _write_backup_cron_marker(
            env["db_path"],
            content=(
                "schedule=0 2 * * *\ncron_tz=America/Sao_Paulo\nretention_days=14"
            ),
        )
        result = runner.invoke(app, ["health", "--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(_buffers()[0])
        cron = next(c for c in payload["checks"] if c["label"] == "Cron")
        assert cron["severity"] == "ok"
        assert cron["data"]["schedule"] == "30 0 * * *"
        assert cron["data"]["tz"] == "America/Sao_Paulo"


# ---------------------------------------------------------------------------
# Backup-cron marker (Story 4.4 — new "Backup cron" row)
# ---------------------------------------------------------------------------


class TestBackupCronRow:
    def test_table_render_includes_backup_cron_row(self, env: dict[str, str]) -> None:
        _seed_real_registry(env["db_path"])
        _write_marker(env["db_path"])
        _write_snapshot(env["db_path"])
        _write_backup(env["db_path"])
        _write_backup_cron_marker(env["db_path"])
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0, _buffers()
        stdout, _ = _buffers()
        assert "Backup cron" in stdout

    def test_json_includes_backup_cron_entry(self, env: dict[str, str]) -> None:
        _seed_real_registry(env["db_path"])
        _write_marker(env["db_path"])
        _write_snapshot(env["db_path"])
        _write_backup(env["db_path"])
        _write_backup_cron_marker(env["db_path"])
        result = runner.invoke(app, ["health", "--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(_buffers()[0])
        backup_cron = next(c for c in payload["checks"] if c["label"] == "Backup cron")
        assert backup_cron["severity"] == "ok"
        assert backup_cron["data"] == {
            "installed": True,
            "schedule": "0 2 * * *",
            "tz": "UTC",
            "retention_days": 14,
        }

    def test_missing_marker_flips_json_to_exit_7(self, env: dict[str, str]) -> None:
        _seed_real_registry(env["db_path"])
        _write_marker(env["db_path"])
        _write_snapshot(env["db_path"])
        _write_backup(env["db_path"])
        # Deliberately omit _write_backup_cron_marker — Backup cron warns.
        result = runner.invoke(app, ["health", "--format", "json"])
        assert result.exit_code == 7
        payload = json.loads(_buffers()[0])
        backup_cron = next(c for c in payload["checks"] if c["label"] == "Backup cron")
        assert backup_cron["severity"] == "warn"
        assert backup_cron["value"] == "Not installed"
        assert backup_cron["detail"] == "run ansible-playbook bootstrap.yml"
        assert payload["is_healthy"] is False

    def test_missing_marker_table_mode_warns_but_exits_zero(
        self, env: dict[str, str]
    ) -> None:
        """Table mode follows the read-tier UX rule: warn rendered, exit 0.

        Mirrors test_missing_marker_flips_json_to_exit_7 on the JSON side;
        the contract is JSON-mode propagates exit 7, table-mode does not.
        """
        _seed_real_registry(env["db_path"])
        _write_marker(env["db_path"])
        _write_snapshot(env["db_path"])
        _write_backup(env["db_path"])
        # Deliberately omit _write_backup_cron_marker.
        result = runner.invoke(app, ["health"])
        assert result.exit_code == 0, _buffers()
        stdout, _ = _buffers()
        assert "Backup cron" in stdout
        assert "Not installed" in stdout

    def test_billing_tz_drift_warns_when_marker_disagrees_with_runtime(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """F57 — runtime BILLING_TIMEZONE != marker cron_tz flips warn.

        Marker says cron fires in America/Sao_Paulo but the app runtime
        thinks "today" is UTC. The CLAUDE.md gotcha says this silently
        misaligns suspensions; the new ``Timezone drift`` row catches it.
        """
        monkeypatch.setenv("BILLING_TIMEZONE", "UTC")
        _seed_real_registry(env["db_path"])
        _write_marker(
            env["db_path"],
            content="schedule=30 0 * * *\ncron_tz=America/Sao_Paulo",
        )
        _write_snapshot(env["db_path"])
        _write_backup(env["db_path"])
        _write_backup_cron_marker(env["db_path"])  # default cron_tz=UTC
        result = runner.invoke(app, ["health", "--format", "json"])
        assert result.exit_code == 7
        payload = json.loads(_buffers()[0])
        drift = next(c for c in payload["checks"] if c["label"] == "Timezone drift")
        assert drift["severity"] == "warn"
        assert drift["data"]["runtime"] == "UTC"
        assert drift["data"]["suspension_cron_tz"] == "America/Sao_Paulo"
        assert drift["data"]["backup_cron_tz"] == "UTC"
        assert drift["data"]["matches"] is False

    def test_billing_tz_drift_ok_when_all_markers_agree(
        self, env: dict[str, str]
    ) -> None:
        _seed_real_registry(env["db_path"])
        _write_marker(env["db_path"])  # cron_tz=UTC
        _write_snapshot(env["db_path"])
        _write_backup(env["db_path"])
        _write_backup_cron_marker(env["db_path"])  # cron_tz=UTC
        result = runner.invoke(app, ["health", "--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(_buffers()[0])
        drift = next(c for c in payload["checks"] if c["label"] == "Timezone drift")
        assert drift["severity"] == "ok"
        assert drift["data"]["matches"] is True

    def test_suspension_cron_missing_does_not_flip_backup_cron(
        self, env: dict[str, str]
    ) -> None:
        """F52 symmetry — Cron and Backup cron flip is_healthy independently.

        Suspension-cron marker absent, backup-cron marker present: Cron warns,
        Backup cron stays ok, is_healthy=False (carried by Cron alone).
        """
        _seed_real_registry(env["db_path"])
        _write_snapshot(env["db_path"])
        _write_backup(env["db_path"])
        _write_backup_cron_marker(env["db_path"])
        # Deliberately omit _write_marker (suspension-cron marker).
        result = runner.invoke(app, ["health", "--format", "json"])
        assert result.exit_code == 7
        payload = json.loads(_buffers()[0])
        cron = next(c for c in payload["checks"] if c["label"] == "Cron")
        backup_cron = next(c for c in payload["checks"] if c["label"] == "Backup cron")
        assert cron["severity"] == "warn"
        assert backup_cron["severity"] == "ok"
        assert payload["is_healthy"] is False


# ---------------------------------------------------------------------------
# Read-only invariant (AC15)
# ---------------------------------------------------------------------------


class TestReadOnly:
    def test_db_mtime_unchanged(self, env: dict[str, str]) -> None:
        _seed_real_registry(env["db_path"])
        db_path = Path(env["db_path"])
        before_ns = db_path.stat().st_mtime_ns
        runner.invoke(app, ["health"])
        after_ns = db_path.stat().st_mtime_ns
        assert before_ns == after_ns

    def test_invalidate_sentinel_untouched(self, env: dict[str, str]) -> None:
        _seed_real_registry(env["db_path"])
        sentinel = Path(env["db_path"] + ".invalidate")
        sentinel.write_text("", encoding="utf-8")
        before_ns = sentinel.stat().st_mtime_ns
        runner.invoke(app, ["health"])
        after_ns = sentinel.stat().st_mtime_ns
        assert before_ns == after_ns


# ---------------------------------------------------------------------------
# PII-austere INFO log (AC19, NFR15)
# ---------------------------------------------------------------------------


class TestPiiAusterity:
    def test_log_contains_counts_not_pii(self, env: dict[str, str]) -> None:
        # ``comadre.logging`` sets ``propagate=False`` so caplog can't see
        # it. Attach a direct handler, matching the suspend-sweep test.
        from comadre.logging import get_logger

        _seed_real_registry(env["db_path"])
        _write_marker(env["db_path"])
        logger = get_logger("keys.cli")
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture(level=logging.INFO)
        logger.addHandler(handler)
        try:
            records.clear()
            result = runner.invoke(app, ["health"])
        finally:
            logger.removeHandler(handler)
        assert result.exit_code == 0
        health_records = [
            r for r in records if "Health report generated" in r.getMessage()
        ]
        assert health_records, [r.getMessage() for r in records]
        joined = "\n".join(r.getMessage() for r in health_records)
        assert "format=" in joined
        assert "is_healthy=" in joined
        assert "warn_count=" in joined
        assert "fail_count=" in joined
        assert not _PII_FORBIDDEN_RE.search(joined), joined
        assert "Helena Ribeiro" not in joined
        assert "Marcos Silva" not in joined
        assert "Pedro Lopes" not in joined


# ---------------------------------------------------------------------------
# Help surface (AC20)
# ---------------------------------------------------------------------------


class TestHelpSurface:
    def test_top_level_help_lists_health(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "health" in result.stdout

    def test_health_help_exits_zero(self) -> None:
        result = runner.invoke(app, ["health", "--help"])
        assert result.exit_code == 0
        assert "health" in result.stdout
