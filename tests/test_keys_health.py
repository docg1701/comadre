"""Story 3.4 — unit tests for ``comadre.keys.health``.

Exercises ``collect_health_report`` end-to-end against a tmp-path SQLite
DB plus filesystem fixtures (marker file, counter snapshots). CLI-level
assertions live in ``tests/test_keys_cli_health.py``; renderer assertions
live in ``tests/test_keys_output.py::TestRenderHealthReport``.
"""

from __future__ import annotations

import json
import re
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

import pytest

import comadre.keys.health as health_mod
from comadre.keys.audit import log_event
from comadre.keys.db import (
    _SCHEMA_VERSION,
    _apply_migrations,
    generate_customer_id,
    generate_key_id,
    get_connection,
)
from comadre.keys.health import (
    HealthCheck,
    HealthReport,
    _check_backup_cron_marker,
    _marker_parse,
    collect_health_report,
    health_report_to_json,
)

_ISO_UTC_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"


# ---------------------------------------------------------------------------
# Seed helpers — mirror the ones in test_keys_db_suspend_sweep.py
# ---------------------------------------------------------------------------


def _seed_customer(
    conn: sqlite3.Connection,
    *,
    name: str = "Helena",
    registered_at: str = "2026-04-10T10:00:00Z",
    deleted_at: str | None = None,
) -> str:
    cid = generate_customer_id()
    conn.execute(
        "INSERT INTO customer ("
        "id, name, email, tax_id_kind, tax_id_encrypted, notes, "
        "registered_at, deleted_at"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            cid,
            name,
            f"{name.lower()}@example.com",
            "cpf",
            b"ciphertext",
            "",
            registered_at,
            deleted_at,
        ),
    )
    conn.commit()
    return cid


def _seed_api_key(
    conn: sqlite3.Connection,
    *,
    customer_id: str,
    key_hash: str,
    status: str = "active",
    billing_mode: str = "manual",
    paid_until: str | None = None,
    key_prefix: str = "AAAAAAAA",
) -> str:
    kid = generate_key_id()
    conn.execute(
        "INSERT INTO api_key ("
        "id, customer_id, key_hash, key_prefix, rate_limit_rpm, status, "
        "billing_mode, price_monthly, paid_until, created_at, last_used_at, "
        "notes"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            kid,
            customer_id,
            key_hash,
            key_prefix,
            60,
            status,
            billing_mode,
            149.0,
            paid_until,
            "2026-04-10T12:00:00Z",
            None,
            "",
        ),
    )
    conn.commit()
    return kid


def _write_marker(
    db_path: Path,
    *,
    schedule: str = "30 0 * * *",
    cron_tz: str = "UTC",
    content: str | None = None,
) -> Path:
    marker = Path(f"{db_path}.cron-installed")
    if content is None:
        content = f"schedule={schedule}\ncron_tz={cron_tz}"
    marker.write_text(content, encoding="utf-8")
    marker.chmod(0o600)
    return marker


def _write_backup_cron_marker(
    db_path: Path,
    *,
    schedule: str = "0 2 * * *",
    cron_tz: str = "UTC",
    retention_days: str = "14",
    content: str | None = None,
) -> Path:
    marker = Path(f"{db_path}.backup-cron-installed")
    if content is None:
        content = (
            f"schedule={schedule}\ncron_tz={cron_tz}\nretention_days={retention_days}\n"
        )
    marker.write_text(content, encoding="utf-8")
    marker.chmod(0o600)
    return marker


def _write_snapshot(
    db_path: Path,
    *,
    replica: str = "test-replica",
    age_seconds: int = 3,
    hits: int = 1000,
    misses: int = 10,
    entries: int = 42,
) -> Path:
    written = datetime.now(UTC) - timedelta(seconds=age_seconds)
    snapshot_path = Path(f"{db_path}.counters.{replica}.json")
    payload = {
        "schema_version": 1,
        "written_at": written.strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{written.microsecond // 1000:03d}Z",
        "process_uptime_seconds": 60,
        "auth_cache": {
            "entries": entries,
            "maxsize": 4096,
            "ttl_seconds": 60,
            "hits": hits,
            "misses": misses,
        },
        "per_key": {},
    }
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")
    return snapshot_path


def _collect(
    conn: sqlite3.Connection, db_path: Path, **overrides: object
) -> HealthReport:
    kwargs: dict[str, object] = {
        "conn": conn,
        "db_path": str(db_path),
        "schema_version_expected": _SCHEMA_VERSION,
        "cron_marker_path": str(db_path) + ".cron-installed",
        "backup_parent": str(db_path.parent),
    }
    kwargs.update(overrides)
    return collect_health_report(**kwargs)  # type: ignore[arg-type]


def _check_by_label(report: HealthReport, label: str) -> HealthCheck:
    for c in report.checks:
        if c.label == label:
            return c
    raise AssertionError(f"No check labelled {label!r}")


# ---------------------------------------------------------------------------
# Tests
# ---------------------------------------------------------------------------


class TestFullHealthyReport:
    def test_collect_full_healthy_report(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(
                conn, customer_id=cid, key_hash="a" * 64, key_prefix="AAAA1111"
            )
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="b" * 64,
                key_prefix="BBBB1111",
                status="suspended",
            )
            # One recent sweep row.
            with conn:
                log_event(
                    conn,
                    actor="cron:suspension-sweep",
                    action="cron_suspend",
                    target_type="system",
                    target_id=None,
                    details={"swept_count": 0, "cutoff_date": "2026-04-18"},
                )
            _write_marker(db_path)
            _write_backup_cron_marker(db_path)
            _write_snapshot(db_path)
            # Story 4.3: the backup row now demands a fresh archive to stay ok.
            archive = tmp_path / "registry.db.backup-2026-04-20T02-00-00Z.tar.gz.enc"
            archive.write_bytes(b"encrypted-stub")
            report = _collect(conn, db_path)
        finally:
            conn.close()

        assert report.is_healthy is True
        # 9 fixed checks (Story 4.4 added "Backup cron").
        assert len(report.checks) == 9
        labels = [c.label for c in report.checks]
        assert labels == [
            "Database",
            "Schema version",
            "Customers",
            "Keys",
            "Last suspension sweep",
            "Cron",
            "Backup cron",
            "Last backup",
            "Auth cache",
        ]
        severities = {c.severity for c in report.checks}
        assert "warn" not in severities
        assert "fail" not in severities


class TestDatabaseCheck:
    def test_warn_when_db_permissions_drift(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            db_path.chmod(0o644)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Database")
        assert check.severity == "warn"
        assert "0644" in check.value
        assert check.detail is not None
        assert "0600" in check.detail
        assert report.is_healthy is False

    def test_ok_when_mode_0600(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Database")
        assert check.severity == "ok"
        assert "0600" in check.value

    def test_db_size_uses_real_st_size(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            expected_size = db_path.stat().st_size
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Database")
        assert check.data is not None
        # WAL sidecar + checkpoint-on-close can change st_size between the
        # collector's stat and a post-close stat; anchor against the stat
        # taken inside the same connection lifecycle as the collector.
        assert check.data["size_bytes"] == expected_size
        assert isinstance(check.data["size_bytes"], int)
        assert int(check.data["size_bytes"]) > 0


class TestSchemaVersionCheck:
    def test_warn_when_below_expected(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            with conn:
                conn.execute("DELETE FROM schema_version")
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) "
                    "VALUES (0, '2026-04-01T00:00:00Z')"
                )
            report = collect_health_report(
                conn=conn,
                db_path=str(db_path),
                schema_version_expected=1,
                cron_marker_path=str(db_path) + ".cron-installed",
                backup_parent=str(db_path.parent),
            )
        finally:
            conn.close()
        check = _check_by_label(report, "Schema version")
        assert check.severity == "warn"

    def test_fail_when_above_expected(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            with conn:
                conn.execute(
                    "INSERT INTO schema_version (version, applied_at) "
                    "VALUES (999, '2026-04-01T00:00:00Z')"
                )
            report = collect_health_report(
                conn=conn,
                db_path=str(db_path),
                schema_version_expected=1,
                cron_marker_path=str(db_path) + ".cron-installed",
                backup_parent=str(db_path.parent),
            )
        finally:
            conn.close()
        check = _check_by_label(report, "Schema version")
        assert check.severity == "fail"
        assert report.is_healthy is False


class TestCustomerCount:
    def test_counts_active_and_tombstoned(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            _seed_customer(conn, name="Alive1")
            _seed_customer(conn, name="Alive2")
            _seed_customer(conn, name="Alive3")
            dead = _seed_customer(conn, name="Dead")
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-15T00:00:00Z", dead),
            )
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = "
                "(SELECT id FROM customer WHERE name = 'Alive2')",
                ("2026-04-15T00:00:00Z",),
            )
            conn.commit()
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Customers")
        assert "2 active, 2 tombstoned" in check.value

    def test_omits_tombstoned_tail_when_zero(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            _seed_customer(conn, name="Alive1")
            _seed_customer(conn, name="Alive2")
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Customers")
        assert check.value == "2 active"
        assert "tombstoned" not in check.value


class TestKeyCounts:
    def test_all_three_statuses_rendered_even_when_zero(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(
                conn, customer_id=cid, key_hash="a" * 64, key_prefix="KKKK1111"
            )
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Keys")
        assert check.value == "1 active, 0 suspended, 0 revoked"


class TestLastSweepCheck:
    def test_ok_when_recent(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            with conn:
                log_event(
                    conn,
                    actor="cron:suspension-sweep",
                    action="cron_suspend",
                    target_type="system",
                    target_id=None,
                    details={"swept_count": 0},
                )
            _write_marker(db_path)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Last suspension sweep")
        assert check.severity == "ok"
        assert check.data is not None
        assert isinstance(check.data["age_seconds"], int)
        assert check.data["age_seconds"] >= 0

    def test_warn_when_stale_beyond_threshold(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            with conn:
                log_event(
                    conn,
                    actor="cron:suspension-sweep",
                    action="cron_suspend",
                    target_type="system",
                    target_id=None,
                    details={"swept_count": 0},
                    occurred_at="2026-04-15T03:30:00Z",
                )
            _write_marker(db_path)
            # Freeze now to 72h after the sweep.
            fixed_now = datetime(2026, 4, 18, 3, 30, 0, tzinfo=UTC)
            monkeypatch.setattr(health_mod, "_utcnow", lambda: fixed_now)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Last suspension sweep")
        assert check.severity == "warn"
        assert check.detail is not None
        assert "48h" in check.detail
        assert report.is_healthy is False

    def test_info_when_never_and_no_cron(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Last suspension sweep")
        assert check.severity == "info"
        assert "never" in check.value
        assert "cron not installed" in check.value

    def test_warn_when_never_but_cron_installed(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            _write_marker(db_path)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Last suspension sweep")
        assert check.severity == "warn"
        assert "not yet fired" in check.value
        assert check.detail is not None
        assert "00:30" in check.detail


class TestCronMarkerCheck:
    def test_warn_when_missing(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Cron")
        assert check.severity == "warn"
        assert "Not installed" in check.value
        assert check.detail is not None
        assert "bootstrap.yml" in check.detail

    def test_ok_with_canonical_marker(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            _write_marker(db_path, schedule="30 0 * * *", cron_tz="America/Sao_Paulo")
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Cron")
        assert check.severity == "ok"
        assert "30 0 * * *" in check.value
        assert "America/Sao_Paulo" in check.value

    def test_warn_with_unparseable_marker(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            _write_marker(db_path, content="\x00garbage\x01")
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Cron")
        assert check.severity == "warn"
        assert "unparseable" in check.value.lower()

    def test_warn_when_missing_required_keys(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            # Only schedule= present, no cron_tz=
            _write_marker(db_path, content="schedule=30 0 * * *")
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Cron")
        assert check.severity == "warn"

    def test_unknown_keys_tolerated(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            _write_marker(
                db_path,
                content=(
                    "schedule=30 0 * * *\n"
                    "cron_tz=UTC\n"
                    "future_field=reserved_for_story_4_x"
                ),
            )
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Cron")
        assert check.severity == "ok"


class TestBackupCronMarker:
    """Story 4.4 — ``Backup cron`` row consumes the bootstrap.yml marker."""

    def test_warn_when_marker_missing(self, tmp_path: Path) -> None:
        check = _check_backup_cron_marker(tmp_path / "missing.marker")
        assert check.label == "Backup cron"
        assert check.severity == "warn"
        assert check.value == "Not installed"
        assert check.detail is not None
        assert "bootstrap.yml" in check.detail
        assert check.data == {"installed": False}

    def test_ok_when_marker_well_formed(self, tmp_path: Path) -> None:
        marker = tmp_path / "registry.db.backup-cron-installed"
        marker.write_text(
            "schedule=0 2 * * *\ncron_tz=UTC\nretention_days=14\n",
            encoding="utf-8",
        )
        check = _check_backup_cron_marker(marker)
        assert check.severity == "ok"
        assert "comadre-keys-backup at 0 2 * * *" in check.value
        assert "CRON_TZ=UTC" in check.value
        assert "retention=14d" in check.value
        assert check.data == {
            "installed": True,
            "schedule": "0 2 * * *",
            "tz": "UTC",
            "retention_days": 14,
        }

    def test_warn_on_missing_retention_days_field(self, tmp_path: Path) -> None:
        """All three fields must be present; missing retention_days → warn."""
        marker = tmp_path / "marker"
        marker.write_text("schedule=0 2 * * *\ncron_tz=UTC\n", encoding="utf-8")
        check = _check_backup_cron_marker(marker)
        assert check.severity == "warn"
        assert check.value == "Marker present but unparseable"
        assert check.data == {"installed": True, "parsed": False}

    def test_warn_on_garbage_marker(self, tmp_path: Path) -> None:
        marker = tmp_path / "marker"
        marker.write_text("just some garbage\n", encoding="utf-8")
        check = _check_backup_cron_marker(marker)
        assert check.severity == "warn"
        assert check.value == "Marker present but unparseable"

    def test_ok_with_alternate_tz_and_retention(self, tmp_path: Path) -> None:
        marker = tmp_path / "marker"
        marker.write_text(
            "schedule=15 3 * * *\ncron_tz=America/Sao_Paulo\nretention_days=30\n",
            encoding="utf-8",
        )
        check = _check_backup_cron_marker(marker)
        assert check.severity == "ok"
        assert "15 3 * * *" in check.value
        assert "America/Sao_Paulo" in check.value
        assert "retention=30d" in check.value
        assert check.data["retention_days"] == 30

    def test_warn_on_non_integer_retention_days(self, tmp_path: Path) -> None:
        """retention_days=banana must not render as green ``retention=bananad``."""
        marker = tmp_path / "marker"
        marker.write_text(
            "schedule=0 2 * * *\ncron_tz=UTC\nretention_days=banana\n",
            encoding="utf-8",
        )
        check = _check_backup_cron_marker(marker)
        assert check.severity == "warn"
        assert "retention_days is not an integer" in check.value
        assert check.data["retention_days"] == "banana"

    def test_warn_on_non_positive_retention_days(self, tmp_path: Path) -> None:
        """retention_days must be > 0 — zero and negatives flip to warn."""
        for bad in ("0", "-7"):
            marker = tmp_path / f"marker-{bad}"
            marker.write_text(
                f"schedule=0 2 * * *\ncron_tz=UTC\nretention_days={bad}\n",
                encoding="utf-8",
            )
            check = _check_backup_cron_marker(marker)
            assert check.severity == "warn", bad
            assert "must be positive" in check.value

    def test_warn_when_marker_path_is_a_directory(self, tmp_path: Path) -> None:
        """is_file() guard — directories must not be read_text()'d."""
        marker = tmp_path / "marker-dir"
        marker.mkdir()
        check = _check_backup_cron_marker(marker)
        assert check.severity == "warn"
        assert check.value == "Marker path is not a regular file"
        assert check.data == {
            "installed": True,
            "parsed": False,
            "regular_file": False,
        }


class TestCollectHealthReportBackupCronWiring:
    """Story 4.4 — collect_health_report wires the new check into the tuple."""

    def test_backup_cron_row_present_between_cron_and_last_backup(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            with conn:
                log_event(
                    conn,
                    actor="cron:suspension-sweep",
                    action="cron_suspend",
                    target_type="system",
                    target_id=None,
                    details={"swept_count": 0},
                )
            _write_marker(db_path)
            _write_backup_cron_marker(db_path)
            archive = tmp_path / "registry.db.backup-2026-04-20T02-00-00Z.tar.gz.enc"
            archive.write_bytes(b"encrypted-stub")
            report = _collect(conn, db_path)
        finally:
            conn.close()
        labels = [c.label for c in report.checks]
        assert labels.index("Backup cron") == labels.index("Cron") + 1
        assert labels.index("Last backup") == labels.index("Backup cron") + 1
        backup_cron = _check_by_label(report, "Backup cron")
        assert backup_cron.severity == "ok"
        assert report.is_healthy is True

    def test_backup_cron_row_default_marker_path_derives_from_db_path(
        self, tmp_path: Path
    ) -> None:
        """No backup_cron_marker_path kwarg → derive ``<db>.backup-cron-installed``."""
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            _write_backup_cron_marker(db_path)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        backup_cron = _check_by_label(report, "Backup cron")
        assert backup_cron.severity == "ok"

    def test_backup_cron_row_missing_marker_flips_is_healthy_false(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            # Seed everything else so only Backup cron + Last backup warn.
            with conn:
                log_event(
                    conn,
                    actor="cron:suspension-sweep",
                    action="cron_suspend",
                    target_type="system",
                    target_id=None,
                    details={"swept_count": 0},
                )
            _write_marker(db_path)
            archive = tmp_path / "registry.db.backup-2026-04-20T02-00-00Z.tar.gz.enc"
            archive.write_bytes(b"encrypted-stub")
            report = _collect(conn, db_path)
        finally:
            conn.close()
        backup_cron = _check_by_label(report, "Backup cron")
        assert backup_cron.severity == "warn"
        assert backup_cron.value == "Not installed"
        assert report.is_healthy is False

    def test_backup_cron_marker_path_kwarg_overrides_default(
        self, tmp_path: Path
    ) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            custom = tmp_path / "custom.marker"
            custom.write_text(
                "schedule=0 4 * * *\ncron_tz=UTC\nretention_days=7\n",
                encoding="utf-8",
            )
            report = _collect(conn, db_path, backup_cron_marker_path=str(custom))
        finally:
            conn.close()
        backup_cron = _check_by_label(report, "Backup cron")
        assert backup_cron.severity == "ok"
        assert "0 4 * * *" in backup_cron.value
        assert "retention=7d" in backup_cron.value


class TestBackupCheck:
    """Story 4.3 — the constant flipped to ``False``; warn/ok branches active."""

    def test_warn_when_no_backup_present(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Last backup")
        assert check.severity == "warn"
        assert check.value == "never"
        assert check.detail == "run backup-keys.yml"
        assert check.data is not None
        assert check.data["available_after_story_4_3"] is True
        assert check.data["path"] is None

    def test_ok_when_fresh_backup_present(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            archive = tmp_path / "registry.db.backup-2026-04-20T02-00-00Z.tar.gz.enc"
            archive.write_bytes(b"encrypted-stub")
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Last backup")
        assert check.severity == "ok"
        assert check.data is not None
        assert check.data["available_after_story_4_3"] is True

    def test_warn_when_backup_is_stale(self, tmp_path: Path) -> None:
        """Freshness threshold is 48h — backdate past it to force warn."""
        import os

        db_path = tmp_path / "registry.db"
        archive = tmp_path / "registry.db.backup-2026-04-15T02-00-00Z.tar.gz.enc"
        archive.write_bytes(b"encrypted-stub")
        ancient = time.time() - (72 * 3600)
        os.utime(archive, (ancient, ancient))
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Last backup")
        assert check.severity == "warn"
        assert "expected within 48h" in (check.detail or "")

    def test_is_healthy_flips_false_on_missing_backup(self, tmp_path: Path) -> None:
        """The whole report goes un-healthy when the backup row is warn."""
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        assert report.is_healthy is False
        backup = _check_by_label(report, "Last backup")
        assert backup.severity == "warn"


class TestAuthCacheCheck:
    def test_info_when_no_replicas(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Auth cache")
        assert check.severity == "info"
        assert "no API replicas" in check.value

    def test_ok_when_replica_reports(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            _write_snapshot(db_path, replica="one")
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Auth cache")
        assert check.severity == "ok"
        assert "1 replica," in check.value
        assert "1 replicas" not in check.value  # plural correct at N=1
        assert "%" in check.value  # hit rate rendered


class TestAggregation:
    def test_is_healthy_false_with_one_warn(self) -> None:
        report = HealthReport(
            checks=(
                HealthCheck(label="A", value="ok", severity="ok"),
                HealthCheck(label="B", value="warning", severity="warn"),
            ),
            is_healthy=False,
            generated_at="2026-04-19T00:00:00Z",
        )
        # Using the JSON helper exercises the aggregation output path.
        payload = health_report_to_json(report)
        assert payload["is_healthy"] is False
        assert payload["warn_count"] == 1
        assert payload["fail_count"] == 0

    def test_is_healthy_true_with_info_only(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            _write_marker(db_path)
            _write_backup_cron_marker(db_path)
            # With marker present but no sweep, "Last suspension sweep" is
            # warn — so we deliberately seed a sweep to keep it info-free.
            with conn:
                log_event(
                    conn,
                    actor="cron:suspension-sweep",
                    action="cron_suspend",
                    target_type="system",
                    target_id=None,
                    details={"swept_count": 0},
                )
            # Story 4.3: backup row now requires a fresh archive to stay ok.
            archive = tmp_path / "registry.db.backup-2026-04-20T02-00-00Z.tar.gz.enc"
            archive.write_bytes(b"encrypted-stub")
            report = _collect(conn, db_path)
        finally:
            conn.close()
        # No warn/fail on a clean run → healthy even though Auth cache is info.
        assert report.is_healthy is True


class TestGeneratedAt:
    def test_iso_utc_format(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        assert re.match(_ISO_UTC_RE, report.generated_at) is not None


class TestMarkerParse:
    def test_parses_two_keys(self) -> None:
        out = _marker_parse("schedule=30 0 * * *\ncron_tz=UTC")
        assert out == {"schedule": "30 0 * * *", "cron_tz": "UTC"}

    def test_rejects_missing_equals(self) -> None:
        assert _marker_parse("schedule 30 0 * * *\ncron_tz=UTC") is None

    def test_rejects_empty(self) -> None:
        assert _marker_parse("") is None
        assert _marker_parse("\n\n") is None

    def test_rejects_binary(self) -> None:
        assert _marker_parse("schedule=\x00\x01binary\ncron_tz=UTC") is None

    def test_tolerates_trailing_newline(self) -> None:
        assert _marker_parse("schedule=30\ncron_tz=UTC\n") == {
            "schedule": "30",
            "cron_tz": "UTC",
        }


class TestPerformance:
    def test_collect_under_500ms_for_1k_customers(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            # Seed 1 000 customers + 2 000 keys using executemany — raw SQL
            # for speed (the high-level helpers add transaction overhead
            # per row that would dominate the seed time).
            customer_rows = [
                (
                    generate_customer_id(),
                    f"Customer {i}",
                    f"c{i}@example.com",
                    "cpf",
                    b"ciphertext",
                    "",
                    "2026-04-10T12:00:00Z",
                    None,
                )
                for i in range(1000)
            ]
            conn.executemany(
                "INSERT INTO customer ("
                "id, name, email, tax_id_kind, tax_id_encrypted, notes, "
                "registered_at, deleted_at"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                customer_rows,
            )
            key_rows = []
            for i, (cid, *_) in enumerate(customer_rows):
                for j in range(2):
                    key_rows.append(
                        (
                            generate_key_id(),
                            cid,
                            f"{i:064x}"[:64] if j == 0 else f"{(i + 99999):064x}"[:64],
                            f"K{i:06d}{j:01d}",
                            60,
                            "active" if (i + j) % 3 != 0 else "suspended",
                            "manual",
                            149.0,
                            None,
                            "2026-04-10T12:00:00Z",
                            None,
                            "",
                        )
                    )
            conn.executemany(
                "INSERT INTO api_key ("
                "id, customer_id, key_hash, key_prefix, rate_limit_rpm, "
                "status, billing_mode, price_monthly, paid_until, "
                "created_at, last_used_at, notes"
                ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                key_rows,
            )
            audit_rows = [
                (
                    "cron:suspension-sweep",
                    "cron_suspend",
                    "system",
                    None,
                    json.dumps({"swept_count": 0}),
                    f"2026-04-{(i % 28) + 1:02d}T12:00:00Z",
                )
                for i in range(5000)
            ]
            conn.executemany(
                "INSERT INTO audit_log ("
                "actor, action, target_type, target_id, details_json, "
                "occurred_at"
                ") VALUES (?, ?, ?, ?, ?, ?)",
                audit_rows,
            )
            conn.commit()

            start = time.perf_counter()
            report = _collect(conn, db_path)
            elapsed_ms = (time.perf_counter() - start) * 1000
        finally:
            conn.close()

        assert elapsed_ms < 500, f"collect took {elapsed_ms:.1f} ms (>500 ms)"
        # Sanity: report still has the 9 canonical checks (Story 4.4 added
        # "Backup cron").
        assert len(report.checks) == 9


class TestReadOnly:
    def test_collect_does_not_write_to_db(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            # Force the file's mtime to stabilise.
            conn.commit()
            before_ns = db_path.stat().st_mtime_ns
            # Touch the file back to a sentinel time so a stat-cache hiccup
            # doesn't noise the assertion on fast filesystems.
            time.sleep(0.01)
            _collect(conn, db_path)
            after_ns = db_path.stat().st_mtime_ns
        finally:
            conn.close()
        assert before_ns == after_ns
