"""``comadre-keys health`` data-collection module (Story 3.4, FR34).

Computes a ``HealthReport`` from: the SQLite registry, the cron-installed
marker file, the optional backup glob, and the per-replica counter
snapshots. No mutation. Safe to run from cron / monitoring scripts.

Severity model:
  ok    — nominal; renders green; never affects ``is_healthy``.
  info  — informational; no marker; never affects ``is_healthy``.
  warn  — operational drift; renders yellow; flips ``is_healthy=False``
          in JSON mode → exit 7.
  fail  — failed check; renders red; flips ``is_healthy=False`` in JSON
          mode → exit 7. Distinguished from ``warn`` purely by visual
          severity in table mode; equivalent in JSON for aggregation.
"""

from __future__ import annotations

import sqlite3
import stat as stat_mod
from dataclasses import dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Literal

from comadre.counters import (
    AggregatedCacheStatus,
    aggregate_cache_status,
    read_all_snapshots,
)
from comadre.keys.db import (
    count_active_customers,
    count_keys_by_status,
    count_tombstones,
    get_last_sweep_timestamp,
)
from comadre.keys.formatters import format_seconds_ago

Severity = Literal["ok", "info", "warn", "fail"]

# Story 3.4 ↔ Story 4.3 handshake: flipped to ``False`` when 4.3 ships the
# backup playbook so ``_check_last_backup`` starts emitting warn/fail. While
# ``True`` the backup row stays ``info`` and never affects ``is_healthy``.
_BACKUP_NOT_IMPLEMENTED_INFO = True

# The sweep is considered fresh within 48 h (Story 3.4 spec §2). The cron
# fires daily at 00:30 operator-TZ; a 48 h threshold tolerates one missed
# run without flipping to warn, which absorbs ordinary ops noise.
_SWEEP_STALENESS_WARN_SECONDS = 48 * 3600

_ISO_UTC_FORMAT = "%Y-%m-%dT%H:%M:%SZ"


def _utcnow() -> datetime:
    """Clock seam — monkeypatched in tests to freeze time."""
    return datetime.now(UTC)


def _utcnow_iso() -> str:
    return _utcnow().strftime(_ISO_UTC_FORMAT)


@dataclass(frozen=True, slots=True)
class HealthCheck:
    """One field in the report: what was measured + how to interpret it.

    ``label``  — operator-facing title ("Database", "Cron", ...).
    ``value``  — raw renderable string (plain text, no markup).
    ``severity`` — drives colour (table) and ``is_healthy`` (JSON).
    ``detail`` — optional human hint ("expected 0600").
    ``data``   — optional structured payload for the JSON output.
    """

    label: str
    value: str
    severity: Severity
    detail: str | None = None
    data: dict[str, object] | None = None


@dataclass(frozen=True, slots=True)
class HealthReport:
    """Result payload returned by ``collect_health_report``."""

    checks: tuple[HealthCheck, ...]
    is_healthy: bool
    generated_at: str  # canonical %Y-%m-%dT%H:%M:%SZ


def _format_size(size_bytes: int) -> str:
    """Render a byte count as a compact humanized string."""
    if size_bytes < 1024:
        return f"{size_bytes} B"
    if size_bytes < 1024 * 1024:
        return f"{size_bytes / 1024:.1f} KB"
    if size_bytes < 1024 * 1024 * 1024:
        return f"{size_bytes / (1024 * 1024):.1f} MB"
    return f"{size_bytes / (1024 * 1024 * 1024):.2f} GB"


def _parse_iso_utc(value: str) -> datetime | None:
    try:
        return datetime.strptime(value, _ISO_UTC_FORMAT).replace(tzinfo=UTC)
    except (ValueError, TypeError):
        return None


def _check_db_path(db_path: Path) -> HealthCheck:
    """Stat the DB file — size + mode. Warns on mode drift from 0o600."""
    if not db_path.exists():
        return HealthCheck(
            label="Database",
            value=f"{db_path} (missing)",
            severity="fail",
            detail="database file does not exist",
            data={
                "path": str(db_path),
                "exists": False,
                "size_bytes": None,
                "mode_octal": None,
            },
        )
    st = db_path.stat()
    mode = stat_mod.S_IMODE(st.st_mode)
    mode_str = f"{mode:04o}"
    size_h = _format_size(st.st_size)
    if mode != 0o600:
        return HealthCheck(
            label="Database",
            value=f"{db_path} ({size_h}, mode {mode_str})",
            severity="warn",
            detail="expected 0600; run chmod 600 on the registry file",
            data={
                "path": str(db_path),
                "exists": True,
                "size_bytes": int(st.st_size),
                "mode_octal": mode_str,
            },
        )
    return HealthCheck(
        label="Database",
        value=f"{db_path} ({size_h}, mode {mode_str})",
        severity="ok",
        detail=None,
        data={
            "path": str(db_path),
            "exists": True,
            "size_bytes": int(st.st_size),
            "mode_octal": mode_str,
        },
    )


def _check_schema_version(conn: sqlite3.Connection, *, expected: int) -> HealthCheck:
    """Compare on-disk schema version to the binary's expected version."""
    row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
    current = int(row[0]) if row is not None and row[0] is not None else 0
    if current == expected:
        return HealthCheck(
            label="Schema version",
            value=f"{current} (current)",
            severity="ok",
            detail=None,
            data={"current": current, "expected": expected},
        )
    if current < expected:
        return HealthCheck(
            label="Schema version",
            value=f"{current} (migration pending, expected {expected})",
            severity="warn",
            detail=("run any other comadre-keys command to bootstrap migrations"),
            data={"current": current, "expected": expected},
        )
    return HealthCheck(
        label="Schema version",
        value=f"{current} (binary too old, expected {expected})",
        severity="fail",
        detail="upgrade comadre before running further commands",
        data={"current": current, "expected": expected},
    )


def _check_customer_count(conn: sqlite3.Connection) -> HealthCheck:
    active = count_active_customers(conn)
    tombstoned = count_tombstones(conn)
    if tombstoned == 0:
        value = f"{active} active"
    else:
        value = f"{active} active, {tombstoned} tombstoned"
    return HealthCheck(
        label="Customers",
        value=value,
        severity="ok",
        detail=None,
        data={"active": active, "tombstoned": tombstoned},
    )


def _check_key_counts(conn: sqlite3.Connection) -> HealthCheck:
    counts = count_keys_by_status(conn)
    value = (
        f"{counts['active']} active, "
        f"{counts['suspended']} suspended, "
        f"{counts['revoked']} revoked"
    )
    return HealthCheck(
        label="Keys",
        value=value,
        severity="ok",
        detail=None,
        data={
            "active": counts["active"],
            "suspended": counts["suspended"],
            "revoked": counts["revoked"],
        },
    )


def _check_last_sweep(
    conn: sqlite3.Connection,
    *,
    cron_installed: bool,
    staleness_warn_seconds: int,
) -> HealthCheck:
    last_at = get_last_sweep_timestamp(conn)
    if last_at is None:
        if cron_installed:
            return HealthCheck(
                label="Last suspension sweep",
                value="never (cron installed but not yet fired)",
                severity="warn",
                detail="wait until 00:30 operator-TZ for the first sweep",
                data={
                    "last_at": None,
                    "age_seconds": None,
                    "staleness_warn_seconds": staleness_warn_seconds,
                },
            )
        return HealthCheck(
            label="Last suspension sweep",
            value="never (cron not installed)",
            severity="info",
            detail=None,
            data={
                "last_at": None,
                "age_seconds": None,
                "staleness_warn_seconds": staleness_warn_seconds,
            },
        )
    parsed = _parse_iso_utc(last_at)
    if parsed is None:
        return HealthCheck(
            label="Last suspension sweep",
            value=f"{last_at} (unparseable timestamp)",
            severity="warn",
            detail="audit_log row has a malformed occurred_at",
            data={
                "last_at": last_at,
                "age_seconds": None,
                "staleness_warn_seconds": staleness_warn_seconds,
            },
        )
    delta = int((_utcnow() - parsed).total_seconds())
    age_label = format_seconds_ago(delta)
    # Future timestamp — clock skew between host and container, audit-log
    # tamper, or a TZ misconfig writing local time as UTC. Surface as warn
    # rather than letting format_seconds_ago's negative clamp render it
    # as a healthy "0s ago".
    if delta < 0:
        return HealthCheck(
            label="Last suspension sweep",
            value=f"{last_at} (future timestamp)",
            severity="warn",
            detail="timestamp is in the future — check clock skew or TZ",
            data={
                "last_at": last_at,
                "age_seconds": delta,
                "staleness_warn_seconds": staleness_warn_seconds,
            },
        )
    if delta > staleness_warn_seconds:
        hours = staleness_warn_seconds // 3600
        return HealthCheck(
            label="Last suspension sweep",
            value=f"{last_at} ({age_label})",
            severity="warn",
            detail=f"expected within {hours}h — check cron daemon",
            data={
                "last_at": last_at,
                "age_seconds": delta,
                "staleness_warn_seconds": staleness_warn_seconds,
            },
        )
    return HealthCheck(
        label="Last suspension sweep",
        value=f"{last_at} ({age_label})",
        severity="ok",
        detail=None,
        data={
            "last_at": last_at,
            "age_seconds": delta,
            "staleness_warn_seconds": staleness_warn_seconds,
        },
    )


def _marker_parse(text: str) -> dict[str, str] | None:
    """Parse the cron-installed marker. Returns ``None`` when unparseable.

    Marker format: ``key=value`` lines, ASCII. Unknown keys are tolerated
    silently so a future schema extension (Story 4.x) stays
    forward-compatible. A parse failure anywhere returns ``None`` so the
    renderer can surface a single "unparseable" warn path.
    """
    result: dict[str, str] = {}
    had_kv = False
    for raw_line in text.splitlines():
        line = raw_line.strip()
        if not line:
            continue
        # Binary / control byte in the line → treat as unparseable.
        if any(ord(ch) < 0x20 and ch not in "\t" for ch in line):
            return None
        if "=" not in line:
            return None
        key, _, value = line.partition("=")
        key = key.strip()
        value = value.strip()
        if not key:
            return None
        result[key] = value
        had_kv = True
    if not had_kv:
        return None
    return result


def _check_cron_marker(marker_path: Path) -> HealthCheck:
    if not marker_path.exists():
        return HealthCheck(
            label="Cron",
            value="Not installed",
            severity="warn",
            detail="run ansible-playbook bootstrap.yml",
            data={"installed": False},
        )
    try:
        text = marker_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return HealthCheck(
            label="Cron",
            value="Marker present but unparseable",
            severity="warn",
            detail="re-run ansible-playbook bootstrap.yml",
            data={"installed": True, "parsed": False},
        )
    parsed = _marker_parse(text)
    if parsed is None:
        return HealthCheck(
            label="Cron",
            value="Marker present but unparseable",
            severity="warn",
            detail="re-run ansible-playbook bootstrap.yml",
            data={"installed": True, "parsed": False},
        )
    schedule = parsed.get("schedule", "").strip()
    cron_tz = parsed.get("cron_tz", "").strip()
    if not schedule or not cron_tz:
        return HealthCheck(
            label="Cron",
            value="Marker present but unparseable",
            severity="warn",
            detail="re-run ansible-playbook bootstrap.yml",
            data={"installed": True, "parsed": False},
        )
    value = f"comadre-daily-suspension at {schedule} (CRON_TZ={cron_tz})"
    return HealthCheck(
        label="Cron",
        value=value,
        severity="ok",
        detail=None,
        data={"installed": True, "schedule": schedule, "tz": cron_tz},
    )


def _check_last_backup(
    backup_parent: Path,
    backup_pattern: str,
    *,
    allow_warn: bool,
    staleness_warn_seconds: int = 48 * 3600,
) -> HealthCheck:
    """Look for the most-recent backup artefact.

    Today (``_BACKUP_NOT_IMPLEMENTED_INFO=True``) this always returns
    ``info`` — the backup playbook (Story 4.3) has not shipped. When 4.3
    lands and flips the constant, ``allow_warn=True`` re-enables the warn
    branch for stale / absent backups.
    """
    matches: list[Path] = []
    try:
        if backup_parent.exists():
            matches = list(backup_parent.glob(backup_pattern))
    except OSError:
        matches = []

    if not allow_warn:
        if not matches:
            return HealthCheck(
                label="Last backup",
                value="never (Story 4.3 not yet shipped)",
                severity="info",
                detail=None,
                data={"available_after_story_4_3": False},
            )
        # A backup file somehow exists (manual or early adoption of 4.3).
        # Report the mtime but stay at info severity until the constant
        # flip enables warn/fail branches.
        newest = max(matches, key=lambda p: p.stat().st_mtime)
        mtime_epoch = int(newest.stat().st_mtime)
        mtime_iso = datetime.fromtimestamp(mtime_epoch, UTC).strftime(_ISO_UTC_FORMAT)
        age = int(
            (_utcnow() - datetime.fromtimestamp(mtime_epoch, UTC)).total_seconds()
        )
        return HealthCheck(
            label="Last backup",
            value=f"{mtime_iso} ({format_seconds_ago(age)})",
            severity="info",
            detail=None,
            data={
                "available_after_story_4_3": False,
                "path": str(newest),
                "mtime_iso": mtime_iso,
                "age_seconds": age,
            },
        )

    # Story 4.3 — reserved warn path (exercised only after the constant flip).
    if not matches:  # pragma: no cover
        return HealthCheck(
            label="Last backup",
            value="never",
            severity="warn",
            detail="run backup-keys.yml",
            data={"available_after_story_4_3": True, "path": None},
        )
    newest = max(matches, key=lambda p: p.stat().st_mtime)  # pragma: no cover
    mtime_epoch = int(newest.stat().st_mtime)  # pragma: no cover
    mtime_iso = datetime.fromtimestamp(mtime_epoch, UTC).strftime(  # pragma: no cover
        _ISO_UTC_FORMAT
    )
    age = int(  # pragma: no cover
        (_utcnow() - datetime.fromtimestamp(mtime_epoch, UTC)).total_seconds()
    )
    if age > staleness_warn_seconds:  # pragma: no cover
        return HealthCheck(
            label="Last backup",
            value=f"{mtime_iso} ({format_seconds_ago(age)})",
            severity="warn",
            detail=f"expected within {staleness_warn_seconds // 3600}h",
            data={
                "available_after_story_4_3": True,
                "path": str(newest),
                "mtime_iso": mtime_iso,
                "age_seconds": age,
            },
        )
    return HealthCheck(  # pragma: no cover
        label="Last backup",
        value=f"{mtime_iso} ({format_seconds_ago(age)})",
        severity="ok",
        detail=None,
        data={
            "available_after_story_4_3": True,
            "path": str(newest),
            "mtime_iso": mtime_iso,
            "age_seconds": age,
        },
    )


def _check_auth_cache(status: AggregatedCacheStatus | None) -> HealthCheck:
    """Wrap the existing ``AggregatedCacheStatus`` in a HealthCheck."""
    if status is None:
        return HealthCheck(
            label="Auth cache",
            value="no API replicas reporting (snapshot directory empty)",
            severity="info",
            detail=None,
            data={"auth_cache_available": False, "auth_cache": None},
        )
    hit_rate_pct = status.hit_rate * 100.0
    age_label = format_seconds_ago(status.snapshot_age_seconds)
    value = (
        f"{status.replicas} replicas, {status.entries} entries, "
        f"{hit_rate_pct:.1f}% hit rate, {age_label}"
    )
    return HealthCheck(
        label="Auth cache",
        value=value,
        severity="ok",
        detail=None,
        data={
            "auth_cache_available": True,
            "auth_cache": {
                "replicas": status.replicas,
                "entries": status.entries,
                "maxsize_per_replica": status.maxsize_per_replica,
                "hits": status.hits,
                "misses": status.misses,
                "hit_rate": status.hit_rate,
                "snapshot_age_seconds": status.snapshot_age_seconds,
                "process_uptime_seconds": status.process_uptime_seconds,
            },
        },
    )


def collect_health_report(
    *,
    conn: sqlite3.Connection,
    db_path: str,
    schema_version_expected: int,
    cron_marker_path: str,
    backup_parent: str,
    backup_pattern: str = "*.backup-*.tar.gz.enc",
    sweep_staleness_warn_seconds: int = _SWEEP_STALENESS_WARN_SECONDS,
) -> HealthReport:
    """Build the full HealthReport.

    The caller owns the ``sqlite3.Connection`` so the CLI can map
    ``sqlite3.Error`` to exit 5 around ``get_connection`` /
    ``_apply_migrations`` / this call uniformly.

    Expected failure modes (missing DB file, empty snapshot dir, missing
    marker, missing backup) degrade to ``info`` / ``warn`` checks.
    Unexpected failures (``sqlite3.Error`` mid-query, ``OSError`` on a
    stat we shouldn't have reached) propagate — the CLI maps them to
    exit 5.
    """
    db_path_obj = Path(db_path)
    marker_path_obj = Path(cron_marker_path)
    backup_parent_obj = Path(backup_parent)

    cron_check = _check_cron_marker(marker_path_obj)
    cron_installed = bool(cron_check.data and cron_check.data.get("installed"))

    snapshots = read_all_snapshots(db_path)
    cache_status = aggregate_cache_status(snapshots)

    checks: tuple[HealthCheck, ...] = (
        _check_db_path(db_path_obj),
        _check_schema_version(conn, expected=schema_version_expected),
        _check_customer_count(conn),
        _check_key_counts(conn),
        _check_last_sweep(
            conn,
            cron_installed=cron_installed,
            staleness_warn_seconds=sweep_staleness_warn_seconds,
        ),
        cron_check,
        _check_last_backup(
            backup_parent_obj,
            backup_pattern,
            allow_warn=not _BACKUP_NOT_IMPLEMENTED_INFO,
        ),
        _check_auth_cache(cache_status),
    )

    is_healthy = all(check.severity in {"ok", "info"} for check in checks)
    return HealthReport(
        checks=checks,
        is_healthy=is_healthy,
        generated_at=_utcnow_iso(),
    )


def health_report_to_json(report: HealthReport) -> dict[str, object]:
    """Serialise a HealthReport to the canonical JSON shape."""
    warn_count = sum(1 for c in report.checks if c.severity == "warn")
    fail_count = sum(1 for c in report.checks if c.severity == "fail")
    return {
        "is_healthy": report.is_healthy,
        "generated_at": report.generated_at,
        "warn_count": warn_count,
        "fail_count": fail_count,
        "checks": [
            {
                "label": c.label,
                "severity": c.severity,
                "value": c.value,
                "detail": c.detail,
                "data": c.data,
            }
            for c in report.checks
        ],
    }
