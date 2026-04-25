"""Tests for ``comadre.keys.health`` — the operational gate for ansible health.yml.

Lean by design (test-suite review 2026-04-25): each individual check
function had 3-5 unit tests; collapsed into integration-style tests that
exercise the full report so a regression that breaks the wiring between
the collector and a check is caught.
"""

from __future__ import annotations

import json
import os
import sqlite3
import time
from datetime import UTC, datetime, timedelta
from pathlib import Path

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
    collect_health_report,
    health_report_to_json,
)


def _seed_minimum(conn: sqlite3.Connection) -> None:
    cid = generate_customer_id()
    conn.execute(
        "INSERT INTO customer "
        "(id, name, email, tax_id_kind, tax_id_encrypted, notes, "
        "registered_at, deleted_at) VALUES (?, 'Helena', 'h@x.com', 'cpf', "
        "?, '', '2026-04-10T10:00:00Z', NULL)",
        (cid, b"ciphertext"),
    )
    conn.execute(
        "INSERT INTO api_key "
        "(id, customer_id, key_hash, key_prefix, rate_limit_rpm, status, "
        "billing_mode, price_monthly, paid_until, created_at, last_used_at, "
        "notes) VALUES (?, ?, ?, 'AAAA1111', 60, 'active', 'manual', 149.0, "
        "NULL, '2026-04-10T12:00:00Z', NULL, '')",
        (generate_key_id(), cid, "a" * 64),
    )
    conn.commit()


def _write_marker(db_path: Path, *, kind: str, content: str) -> Path:
    marker = Path(f"{db_path}.{kind}-installed")
    marker.write_text(content, encoding="utf-8")
    marker.chmod(0o600)
    return marker


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


def test_full_healthy_report_has_all_nine_checks_in_fixed_order(tmp_path: Path) -> None:
    """Story 3.4 + 4.4 contract: nine checks in a fixed order, every
    severity ok/info, ``is_healthy=True``."""
    db_path = tmp_path / "registry.db"
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        _seed_minimum(conn)
        with conn:
            log_event(
                conn,
                actor="cron:suspension-sweep",
                action="cron_suspend",
                target_type="system",
                target_id=None,
                details={"swept_count": 0, "cutoff_date": "2026-04-18"},
            )
        _write_marker(db_path, kind="cron", content="schedule=30 0 * * *\ncron_tz=UTC")
        _write_marker(
            db_path,
            kind="backup-cron",
            content="schedule=0 2 * * *\ncron_tz=UTC\nretention_days=14\n",
        )
        # Fresh backup archive within 48h (Story 4.3 contract).
        archive = tmp_path / "registry.db.backup-2026-04-20T02-00-00Z.tar.gz.enc"
        archive.write_bytes(b"encrypted-stub")
        # Replica counter snapshot for Auth cache check.
        snapshot_path = Path(f"{db_path}.counters.test-replica.json")
        written = datetime.now(UTC) - timedelta(seconds=3)
        snapshot_path.write_text(
            json.dumps(
                {
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
            )
        )
        report = _collect(conn, db_path)
    finally:
        conn.close()

    assert report.is_healthy is True
    assert [c.label for c in report.checks] == [
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
    assert severities <= {"ok", "info"}


def test_db_permissions_drift_emits_warn_and_flips_is_healthy(tmp_path: Path) -> None:
    """NFR13: registry.db mode 0600 is enforced. Drift is the single
    most-actionable signal in the health report; surface it loudly."""
    db_path = tmp_path / "registry.db"
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        db_path.chmod(0o644)
        report = _collect(conn, db_path)
    finally:
        conn.close()
    db_check = _check_by_label(report, "Database")
    assert db_check.severity == "warn"
    assert "0644" in db_check.value
    assert db_check.detail is not None and "0600" in db_check.detail
    assert report.is_healthy is False


def test_missing_or_stale_backup_flips_is_healthy(tmp_path: Path) -> None:
    """Story 4.3: ``Last backup`` must be fresh (< 48h) and present.
    Both 'never' and 'stale' must warn AND drop is_healthy."""
    db_path = tmp_path / "registry.db"

    # No archive at all.
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        report = _collect(conn, db_path)
    finally:
        conn.close()
    check = _check_by_label(report, "Last backup")
    assert check.severity == "warn"
    assert check.value == "never"
    assert report.is_healthy is False

    # Stale archive (> 48h old).
    archive = tmp_path / "registry.db.backup-2026-04-15T02-00-00Z.tar.gz.enc"
    archive.write_bytes(b"encrypted-stub")
    ancient = time.time() - (72 * 3600)
    os.utime(archive, (ancient, ancient))
    conn = get_connection(db_path)
    try:
        report = _collect(conn, db_path)
    finally:
        conn.close()
    check = _check_by_label(report, "Last backup")
    assert check.severity == "warn"
    assert "expected within 48h" in (check.detail or "")


def test_missing_cron_markers_warn_for_both_suspension_and_backup_rows(
    tmp_path: Path,
) -> None:
    """Both ``Cron`` (suspension-sweep) and ``Backup cron`` rows must be
    present and well-formed; missing-marker is the canary for a
    bootstrap-not-run host."""
    db_path = tmp_path / "registry.db"
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        # No marker files written.
        report = _collect(conn, db_path)
    finally:
        conn.close()
    cron = _check_by_label(report, "Cron")
    backup_cron = _check_by_label(report, "Backup cron")
    assert cron.severity == "warn"
    assert backup_cron.severity == "warn"
    assert report.is_healthy is False


def test_health_report_to_json_aggregates_warn_and_fail_counts() -> None:
    """The JSON envelope is what monitoring consumes — it must surface
    warn_count + fail_count + is_healthy honestly."""
    report = HealthReport(
        checks=(
            HealthCheck(label="A", value="ok", severity="ok"),
            HealthCheck(label="B", value="warn", severity="warn"),
            HealthCheck(label="C", value="fail", severity="fail"),
            HealthCheck(label="D", value="info", severity="info"),
        ),
        is_healthy=False,
        generated_at="2026-04-19T00:00:00Z",
    )
    payload = health_report_to_json(report)
    assert payload["is_healthy"] is False
    assert payload["warn_count"] == 1
    assert payload["fail_count"] == 1
    assert len(payload["checks"]) == 4
