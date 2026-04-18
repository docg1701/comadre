"""End-to-end CLI tests for `comadre-keys show` (Story 1.4)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterator
from datetime import date
from io import StringIO
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from rich.console import Console
from typer.testing import CliRunner

import comadre.keys.cli.commands.customers as customers_cmd
import comadre.keys.cli.commands.keys as keys_cmd
import comadre.keys.cli.output as output_mod
from comadre.config import get_settings
from comadre.keys.cli.app import app

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


def _seed_customer(
    env: dict[str, str],
    *,
    name: str = "Helena Ribeiro",
    email: str = "helena@clinica.com",
    cpf: str = "123.456.789-09",
) -> str:
    _clear_buffers()
    result = runner.invoke(
        app,
        [
            "create-customer",
            "--name",
            name,
            "--email",
            email,
            "--cpf",
            cpf,
        ],
    )
    assert result.exit_code == 0, result.output
    stdout, _stderr = _buffers()
    match = re.search(r"cust_[0-9a-z]{26}", stdout)
    assert match is not None, stdout
    _clear_buffers()
    return match.group(0)


def _issue_key(
    env: dict[str, str],
    customer_id: str,
    *,
    rpm: int = 60,
    price: float = 149.0,
    billing_mode: str = "manual",
) -> tuple[str, str]:
    """Run issue-key end-to-end and return (key_id, key_prefix)."""
    args = [
        "issue-key",
        "--customer",
        customer_id,
        "--rpm",
        str(rpm),
        "--billing-mode",
        billing_mode,
    ]
    if billing_mode == "manual":
        args.extend(["--price", str(price)])
    _clear_buffers()
    result = runner.invoke(app, args)
    assert result.exit_code == 0, result.output
    _clear_buffers()
    conn = sqlite3.connect(env["db_path"])
    try:
        row = conn.execute(
            "SELECT id, key_prefix FROM api_key WHERE customer_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (customer_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return str(row[0]), str(row[1])


def _raw_insert_key(
    env: dict[str, str],
    *,
    customer_id: str,
    status: str = "active",
    billing_mode: str = "manual",
    rate_limit_rpm: int = 60,
    price_monthly: float = 149.0,
    paid_until: str | None = None,
    created_at: str = "2026-04-16T12:00:00Z",
    last_used_at: str | None = None,
    key_hash: str | None = None,
    key_prefix: str = "RAWKEY00",
    notes: str = "",
) -> str:
    """Seed an api_key row directly (bypassing issue-key's audit write)."""
    from comadre.keys.db import generate_key_id

    key_id = generate_key_id()
    hash_value = key_hash or (key_id.replace("key_", "").ljust(64, "0"))
    conn = sqlite3.connect(env["db_path"])
    try:
        conn.execute(
            "INSERT INTO api_key ("
            "id, customer_id, key_hash, key_prefix, rate_limit_rpm, status, "
            "billing_mode, price_monthly, paid_until, created_at, last_used_at, "
            "notes"
            ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                key_id,
                customer_id,
                hash_value,
                key_prefix,
                rate_limit_rpm,
                status,
                billing_mode,
                price_monthly,
                paid_until,
                created_at,
                last_used_at,
                notes,
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return key_id


def _raw_insert_audit(
    env: dict[str, str],
    *,
    occurred_at: str,
    actor: str,
    action: str,
    target_type: str,
    target_id: str,
    details_json: str | None = None,
) -> None:
    conn = sqlite3.connect(env["db_path"])
    try:
        conn.execute(
            "INSERT INTO audit_log "
            "(occurred_at, actor, action, target_type, target_id, details_json) "
            "VALUES (?, ?, ?, ?, ?, ?)",
            (occurred_at, actor, action, target_type, target_id, details_json),
        )
        conn.commit()
    finally:
        conn.close()


def _count(env: dict[str, str], table: str) -> int:
    conn = sqlite3.connect(env["db_path"])
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def _freeze_today(monkeypatch: pytest.MonkeyPatch, today: date) -> None:
    """Freeze the clock for both command modules (show lives in customers)."""
    monkeypatch.setattr(customers_cmd, "_resolve_today_in_tz", lambda _tz: today)
    monkeypatch.setattr(keys_cmd, "_resolve_today_in_tz", lambda _tz: today)


# ---------------------------------------------------------------------------
# AC1 — show <key-prefix> populated happy path.
# ---------------------------------------------------------------------------


class TestShowKeyPopulated:
    def test_renders_detail_panel(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        from datetime import UTC, datetime

        customer_id = _seed_customer(env)
        _key_id, key_prefix = _issue_key(env, customer_id)
        # Freeze the clock to the day the key was actually issued so ``Age``
        # renders ``today`` (issue-key uses ``datetime.now(UTC)`` directly
        # for ``created_at``; the show seam computes age relative to today).
        _freeze_today(monkeypatch, datetime.now(UTC).date())

        result = runner.invoke(app, ["show", key_prefix])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        # All 11 labels present.
        for label in (
            "Prefix:",
            "Customer:",
            "Status:",
            "RPM:",
            "Price:",
            "Billing:",
            "Paid Until:",
            "Created:",
            "Last Used:",
            "Age:",
            "Notes:",
        ):
            assert label in stdout
        # Title includes the prefix.
        assert f"Key: {key_prefix}" in stdout
        # Business values rendered per AC1.
        assert "active" in stdout
        assert "60/min" in stdout
        assert "R$ 149,00/month" in stdout
        assert "never" in stdout
        assert "today" in stdout
        # em-dash for Paid Until NULL.
        assert "\u2014" in stdout
        # No trailing row count; not a list.
        assert "keys found" not in stdout
        # No audit section when --audit-tail is absent.
        assert "No events recorded" not in stdout
        assert "events:" not in stdout

    def test_complimentary(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _key_id, key_prefix = _issue_key(env, customer_id, billing_mode="complimentary")
        result = runner.invoke(app, ["show", key_prefix])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "R$ 0,00 (bundled externally)" in stdout
        assert "complimentary" in stdout

    def test_suspended_label(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _raw_insert_key(
            env,
            customer_id=customer_id,
            status="suspended",
            key_prefix="SUSPEND1",
            paid_until="2026-04-01",
        )
        result = runner.invoke(app, ["show", "SUSPEND1"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "suspended" in stdout

    def test_revoked_label(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _raw_insert_key(
            env,
            customer_id=customer_id,
            status="revoked",
            key_prefix="REVOKED1",
            paid_until="2026-05-01",
        )
        result = runner.invoke(app, ["show", "REVOKED1"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "revoked" in stdout

    def test_notes_preserved(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _raw_insert_key(
            env,
            customer_id=customer_id,
            key_prefix="WITHNOTE",
            notes="rotated after leak",
        )
        result = runner.invoke(app, ["show", "WITHNOTE"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "rotated after leak" in stdout


# ---------------------------------------------------------------------------
# AC2 — show <key-prefix> --audit-tail N.
# ---------------------------------------------------------------------------


class TestShowKeyAuditTail:
    def test_key_audit_tail_20(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        key_id, key_prefix = _issue_key(env, customer_id)
        # Seed two extra audit rows for this key (simulating future actions).
        _raw_insert_audit(
            env,
            occurred_at="2026-04-15T14:00:00Z",
            actor="cli:ricardo",
            action="mark_paid",
            target_type="api_key",
            target_id=key_id,
        )
        _raw_insert_audit(
            env,
            occurred_at="2026-04-16T09:15:00Z",
            actor="cli:ricardo",
            action="update_key",
            target_type="api_key",
            target_id=key_id,
            details_json='{"notes": "bumped rpm"}',
        )
        result = runner.invoke(app, ["show", key_prefix, "--audit-tail", "20"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert "Last 3 events:" in stdout
        for line in ("UPDATE_KEY", "MARK_PAID", "ISSUE_KEY"):
            assert line in stdout
        # Newest-first — the seeded 2026-04-16 UPDATE_KEY must appear
        # before the seeded 2026-04-15 MARK_PAID.
        assert stdout.index("UPDATE_KEY") < stdout.index("MARK_PAID")
        # Two-space indent on event lines.
        assert re.search(r"\n  2026-04-16 09:15:00  UPDATE_KEY", stdout)
        # Details column present for update_key.
        assert '{"notes": "bumped rpm"}' in stdout

    def test_audit_tail_zero_rejected(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        _key_id, key_prefix = _issue_key(env, customer_id)
        result = runner.invoke(app, ["show", key_prefix, "--audit-tail", "0"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--audit-tail must be between 1 and 1000" in stderr

    def test_audit_tail_too_large_rejected(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        _key_id, key_prefix = _issue_key(env, customer_id)
        result = runner.invoke(app, ["show", key_prefix, "--audit-tail", "1001"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--audit-tail must be between 1 and 1000" in stderr

    def test_audit_tail_valid_1(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _key_id, key_prefix = _issue_key(env, customer_id)
        result = runner.invoke(app, ["show", key_prefix, "--audit-tail", "1"])
        _stdout, _stderr = _buffers()
        assert result.exit_code == 0

    def test_audit_tail_valid_1000(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _key_id, key_prefix = _issue_key(env, customer_id)
        result = runner.invoke(app, ["show", key_prefix, "--audit-tail", "1000"])
        _stdout, _stderr = _buffers()
        assert result.exit_code == 0

    def test_billing_verbs_render_via_real_commands(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Story 3.1 AC21 — MARK_PAID / SUSPEND_KEY / REACTIVATE_KEY render verbatim.

        Exercises the three new commands end-to-end (not ``_raw_insert_audit``)
        so the test closes the loop: ``show --audit-tail`` renders whatever
        action strings the Story 3.1 commands actually write.
        """
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _key_id, key_prefix = _issue_key(env, customer_id)

        # Sequence: mark-paid (active; no reactivation), suspend, reactivate.
        _clear_buffers()
        assert (
            runner.invoke(
                app, ["mark-paid", key_prefix, "--until", "2026-06-05"]
            ).exit_code
            == 0
        )
        _clear_buffers()
        assert runner.invoke(app, ["suspend", key_prefix]).exit_code == 0
        _clear_buffers()
        assert runner.invoke(app, ["reactivate", key_prefix]).exit_code == 0
        _clear_buffers()

        result = runner.invoke(app, ["show", key_prefix, "--audit-tail", "20"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        for action in ("MARK_PAID", "SUSPEND_KEY", "REACTIVATE_KEY"):
            assert action in stdout
        # The MARK_PAID row carries the JSON details suffix.
        assert '{"paid_until": "2026-06-05", "reactivated": false}' in stdout
        # SUSPEND_KEY and REACTIVATE_KEY have no trailing details block
        # (details_json IS NULL). Check: the action line ends at the actor
        # field with no trailing {...} JSON.
        for action in ("SUSPEND_KEY", "REACTIVATE_KEY"):
            for line in stdout.splitlines():
                if action in line:
                    assert "{" not in line.split(action, 1)[1]

    def test_mark_paid_reactivation_renders_true_details(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Story 3.1 AC21 — ``mark_paid`` on suspended writes ``reactivated: true``."""
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _key_id, key_prefix = _issue_key(env, customer_id)

        _clear_buffers()
        assert runner.invoke(app, ["suspend", key_prefix]).exit_code == 0
        _clear_buffers()
        assert (
            runner.invoke(
                app, ["mark-paid", key_prefix, "--until", "2026-06-05"]
            ).exit_code
            == 0
        )
        _clear_buffers()

        result = runner.invoke(app, ["show", key_prefix, "--audit-tail", "20"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert "MARK_PAID" in stdout
        assert '{"paid_until": "2026-06-05", "reactivated": true}' in stdout


# ---------------------------------------------------------------------------
# Story 2.3 — show <key> --audit-tail renders last-24h stats.
# ---------------------------------------------------------------------------


def _write_counters_snapshot(
    env: dict[str, str],
    *,
    key_id: str | None = None,
    age_seconds: int = 3,
    requests_total: int = 412,
    rate_limit_429: int = 3,
    peak_rpm: int = 47,
    avg_rpm_last_60s: int = 12,
    process_uptime_seconds: int = 3712,
    replica: str = "test-replica",
) -> Path:
    """Seed a per-replica counters snapshot file next to the test DB."""
    import json as _json
    from datetime import UTC, datetime, timedelta

    written = datetime.now(UTC) - timedelta(seconds=age_seconds)
    snapshot_path = Path(env["db_path"] + f".counters.{replica}.json")
    per_key: dict[str, dict[str, object]] = {}
    if key_id is not None:
        per_key[key_id] = {
            "requests_total": requests_total,
            "auth_success": requests_total,
            "rate_limit_429": rate_limit_429,
            "peak_rpm": peak_rpm,
            "avg_rpm_last_60s": avg_rpm_last_60s,
            "last_activity_at": (datetime.now(UTC) - timedelta(seconds=2)).strftime(
                "%Y-%m-%dT%H:%M:%S.000Z"
            ),
        }
    payload = {
        "schema_version": 1,
        "written_at": written.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
        "process_uptime_seconds": process_uptime_seconds,
        "auth_cache": {
            "entries": 1,
            "maxsize": 4096,
            "ttl_seconds": 60,
            "hits": 10,
            "misses": 2,
        },
        "per_key": per_key,
    }
    snapshot_path.write_text(_json.dumps(payload), encoding="utf-8")
    return snapshot_path


class TestShowKeyLast24hStats:
    """AC12, AC13, AC14 — last-24h stats section for key targets."""

    def test_fresh_snapshot_renders_section(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        key_id, key_prefix = _issue_key(env, customer_id)
        _write_counters_snapshot(
            env,
            key_id=key_id,
            requests_total=412,
            rate_limit_429=3,
            peak_rpm=47,
            avg_rpm_last_60s=12,
        )
        result = runner.invoke(app, ["show", key_prefix, "--audit-tail", "20"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "Last-24h stats" in stdout
        assert "Requests total:     412" in stdout
        assert "Rate-limit 429:     3" in stdout
        assert "Peak RPM:           47" in stdout
        assert "Avg RPM (last 60s): 12" in stdout
        # Section appears between DetailPanel and AuditTail.
        assert stdout.index("Last-24h stats") < stdout.index("Last 1 events:")

    def test_missing_snapshot_renders_unavailable(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _key_id, key_prefix = _issue_key(env, customer_id)
        # Intentionally no snapshot.
        result = runner.invoke(app, ["show", key_prefix, "--audit-tail", "20"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "Last-24h stats: unavailable." in stdout
        # AuditTail still renders below.
        assert "Last 1 events:" in stdout or "No events recorded" in stdout

    def test_snapshot_missing_key_id_renders_unavailable(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _key_id, key_prefix = _issue_key(env, customer_id)
        # Snapshot present but only for a DIFFERENT key_id.
        _write_counters_snapshot(env, key_id="key_OTHER", age_seconds=3)
        result = runner.invoke(app, ["show", key_prefix, "--audit-tail", "20"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "Last-24h stats: unavailable." in stdout

    def test_stale_snapshot_renders_with_age_label(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Stale data is shown honestly with a freshness label, not hidden.

        Operators can decide whether a 2-minute-old aggregate is
        acceptable for their diagnostic. Industry-standard behaviour:
        surface the age, never hide data behind an arbitrary cutoff.
        """
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        key_id, key_prefix = _issue_key(env, customer_id)
        _write_counters_snapshot(
            env, key_id=key_id, age_seconds=120, requests_total=999
        )
        result = runner.invoke(app, ["show", key_prefix, "--audit-tail", "20"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        # Section renders with a "2m ago" freshness label.
        assert "Last-24h stats" in stdout
        assert "2m ago" in stdout
        # Data is visible — not collapsed to "unavailable".
        assert "Requests total:     999" in stdout

    def test_multi_replica_aggregates_counters(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Two replica snapshots → summed counters + max peak_rpm."""
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        key_id, key_prefix = _issue_key(env, customer_id)
        _write_counters_snapshot(
            env,
            key_id=key_id,
            replica="alpha",
            requests_total=100,
            rate_limit_429=2,
            peak_rpm=20,
            avg_rpm_last_60s=5,
        )
        _write_counters_snapshot(
            env,
            key_id=key_id,
            replica="beta",
            requests_total=50,
            rate_limit_429=1,
            peak_rpm=35,
            avg_rpm_last_60s=3,
        )
        result = runner.invoke(app, ["show", key_prefix, "--audit-tail", "20"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "aggregated across 2 replicas" in stdout
        assert "Requests total:     150" in stdout  # summed
        assert "Rate-limit 429:     3" in stdout  # summed
        assert "Peak RPM:           35" in stdout  # max
        assert "Avg RPM (last 60s): 8" in stdout  # summed

    def test_customer_target_omits_stats_section(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _issue_key(env, customer_id)
        _write_counters_snapshot(env, key_id="key_ANY", age_seconds=3)
        result = runner.invoke(app, ["show", customer_id, "--audit-tail", "20"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "Last-24h stats" not in stdout

    def test_key_target_without_audit_tail_omits_stats_section(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Bare ``show <key>`` stays Story 1.4-shaped — no forensics section."""
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        key_id, key_prefix = _issue_key(env, customer_id)
        _write_counters_snapshot(env, key_id=key_id, age_seconds=3)
        result = runner.invoke(app, ["show", key_prefix])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "Last-24h stats" not in stdout


class TestShowKeyLast24hStatsJson:
    """AC12 / AC14 JSON-shape behaviour for the ``stats`` field."""

    def test_key_json_with_audit_tail_has_stats(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        key_id, key_prefix = _issue_key(env, customer_id)
        _write_counters_snapshot(env, key_id=key_id, requests_total=42, peak_rpm=5)
        result = runner.invoke(
            app, ["show", key_prefix, "--audit-tail", "5", "--format", "json"]
        )
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        parsed = json.loads(stdout)
        assert parsed["target_type"] == "api_key"
        assert "stats" in parsed
        assert parsed["stats"] is not None
        assert parsed["stats"]["requests_total"] == 42
        assert parsed["stats"]["peak_rpm"] == 5
        # Multi-replica bookkeeping is surfaced in the JSON payload too.
        assert parsed["stats"]["replicas"] == 1

    def test_key_json_with_audit_tail_missing_snapshot_has_null_stats(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _key_id, key_prefix = _issue_key(env, customer_id)
        result = runner.invoke(
            app, ["show", key_prefix, "--audit-tail", "5", "--format", "json"]
        )
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        parsed = json.loads(stdout)
        assert parsed["target_type"] == "api_key"
        assert "stats" in parsed
        assert parsed["stats"] is None

    def test_customer_json_with_audit_tail_no_stats_field(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _issue_key(env, customer_id)
        _write_counters_snapshot(env, key_id="key_ANY", age_seconds=3)
        result = runner.invoke(
            app, ["show", customer_id, "--audit-tail", "5", "--format", "json"]
        )
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        parsed = json.loads(stdout)
        assert "stats" not in parsed

    def test_key_json_without_audit_tail_no_stats_field(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        key_id, key_prefix = _issue_key(env, customer_id)
        _write_counters_snapshot(env, key_id=key_id, age_seconds=3)
        result = runner.invoke(app, ["show", key_prefix, "--format", "json"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        parsed = json.loads(stdout)
        assert "stats" not in parsed


# ---------------------------------------------------------------------------
# AC3 — show <customer-id> populated happy path.
# ---------------------------------------------------------------------------


class TestShowCustomerPopulated:
    def test_customer_detail_panel(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _issue_key(env, customer_id)
        _issue_key(env, customer_id)
        result = runner.invoke(app, ["show", customer_id])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        for label in (
            "ID:",
            "Name:",
            "Email:",
            "Tax ID Kind:",
            "Keys:",
            "Registered:",
            "Notes:",
        ):
            assert label in stdout
        assert f"Customer: {customer_id}" in stdout
        assert "CPF" in stdout
        # Two keys issued.
        assert "2" in stdout

    def test_does_not_leak_ciphertext(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        result = runner.invoke(app, ["show", customer_id])
        stdout, stderr = _buffers()
        assert result.exit_code == 0
        combined = stdout + stderr
        assert "gAAAAA" not in combined
        # No base64-shaped long run (40+ chars uninterrupted alnum/= hint of a
        # Fernet token or encoded blob).
        assert not re.search(r"[A-Za-z0-9+/=_-]{60,}", combined)


# ---------------------------------------------------------------------------
# AC4 — customer audit tail aggregates key-level events.
# ---------------------------------------------------------------------------


class TestShowCustomerAuditTail:
    def test_includes_create_customer_and_issue_key(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _issue_key(env, customer_id)
        result = runner.invoke(app, ["show", customer_id, "--audit-tail", "20"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert "CREATE_CUSTOMER" in stdout
        assert "ISSUE_KEY" in stdout
        # Newest first: issue_key must appear BEFORE create_customer textually.
        assert stdout.index("ISSUE_KEY") < stdout.index("CREATE_CUSTOMER")

    def test_json_format_customer_audit_tail_events(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _issue_key(env, customer_id)
        result = runner.invoke(
            app,
            ["show", customer_id, "--format", "json", "--audit-tail", "20"],
        )
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        parsed = json.loads(stdout)
        actions = [e["action"] for e in parsed["events"]]
        assert "create_customer" in actions
        assert "issue_key" in actions
        # details parsed into a dict (not a JSON string).
        details_by_action = {e["action"]: e["details"] for e in parsed["events"]}
        assert isinstance(details_by_action["issue_key"], dict)


# ---------------------------------------------------------------------------
# AC5 — empty audit-tail result.
# ---------------------------------------------------------------------------


class TestShowKeyAuditTailEmpty:
    def test_no_events_recorded(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _raw_insert_key(
            env,
            customer_id=customer_id,
            key_prefix="ORPHAN00",
            created_at="2026-04-16T10:00:00Z",
        )
        result = runner.invoke(app, ["show", "ORPHAN00", "--audit-tail", "10"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert "No events recorded" in stdout
        assert "Last 0 events:" not in stdout


# ---------------------------------------------------------------------------
# AC6 — target not found.
# ---------------------------------------------------------------------------


class TestShowNotFound:
    def test_missing_prefix_exits_3(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["show", "NOPENOPE"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Not found: no customer or key matches 'NOPENOPE'" in stderr

    def test_missing_customer_id_exits_3(self, env: dict[str, str]) -> None:
        missing = "cust_01nonexistent00000000000"
        result = runner.invoke(app, ["show", missing])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert f"Not found: no customer or key matches '{missing}'" in stderr

    def test_tombstoned_customer_treated_as_missing(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        conn = sqlite3.connect(env["db_path"])
        try:
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-20T00:00:00Z", customer_id),
            )
            conn.commit()
        finally:
            conn.close()
        result = runner.invoke(app, ["show", customer_id])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Not found: no customer or key matches" in stderr

    def test_error_title_identical_for_customer_and_key_shapes(
        self, env: dict[str, str]
    ) -> None:
        operand_a = "NOPENOPE"
        operand_b = "cust_01nonexistent00000000000"
        result_a = runner.invoke(app, ["show", operand_a])
        _stdout_a, stderr_a = _buffers()
        _clear_buffers()
        result_b = runner.invoke(app, ["show", operand_b])
        _stdout_b, stderr_b = _buffers()
        assert result_a.exit_code == result_b.exit_code == 3

        # Anti-enumeration invariant (FR37 / NFR15): the rendered text must be
        # byte-identical between customer-shape and key-shape inputs once the
        # echoed operator-supplied operand is normalized to a placeholder.
        # Box-drawing decorations (the Rich panel border) auto-size to the
        # title length — that variance is a direct consequence of the
        # operator's own input width, not a coded branch — so we strip them
        # before comparing the actual message content.
        def _normalize(stderr: str, operand: str) -> str:
            stripped = "".join(ch for ch in stderr if ch not in "│╭╮╰╯─ ")
            return stripped.replace(operand, "<INPUT>")

        assert _normalize(stderr_a, operand_a) == _normalize(stderr_b, operand_b)


# ---------------------------------------------------------------------------
# AC7 — ambiguous prefix.
# ---------------------------------------------------------------------------


class TestShowAmbiguousPrefix:
    def test_ambiguous_prefix_exits_3(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        key_a = _raw_insert_key(
            env, customer_id=customer_id, key_hash="a" * 64, key_prefix="COLLIDE1"
        )
        key_b = _raw_insert_key(
            env, customer_id=customer_id, key_hash="b" * 64, key_prefix="COLLIDE1"
        )
        result = runner.invoke(app, ["show", "COLLIDE1"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Ambiguous prefix: multiple keys match 'COLLIDE1'" in stderr
        # Must not reveal the colliding key ids.
        assert key_a not in stderr
        assert key_b not in stderr


# ---------------------------------------------------------------------------
# AC8 — JSON output.
# ---------------------------------------------------------------------------


class TestShowFormatJson:
    def test_customer_shape(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        result = runner.invoke(app, ["show", customer_id, "--format", "json"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        parsed = json.loads(stdout)
        assert parsed["target_type"] == "customer"
        target = parsed["target"]
        # AC8 fixed key order — assert ordered list, not just set membership,
        # so a future regression that switched to ``dict(sorted(...))`` is
        # caught at the integration boundary.
        assert list(target.keys()) == [
            "id",
            "name",
            "email",
            "tax_id_kind",
            "key_count",
            "registered_at",
            "notes",
        ]
        assert "events" not in parsed

    def test_key_shape(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        key_id, key_prefix = _issue_key(env, customer_id)
        result = runner.invoke(app, ["show", key_prefix, "--format", "json"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        parsed = json.loads(stdout)
        assert parsed["target_type"] == "api_key"
        target = parsed["target"]
        # AC8 fixed key order — assert ordered list, not just membership.
        assert list(target.keys()) == [
            "id",
            "customer_id",
            "customer_name",
            "key_prefix",
            "status",
            "billing_mode",
            "rate_limit_rpm",
            "price_monthly",
            "paid_until",
            "created_at",
            "last_used_at",
            "age_days",
            "notes",
        ]
        assert target["id"] == key_id
        assert target["key_prefix"] == key_prefix
        assert "key_hash" not in target
        # price_monthly serialized as a number.
        assert isinstance(target["price_monthly"], (int, float))

    def test_not_found_emits_error_to_stderr(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["show", "NOPE", "--format", "json"])
        stdout, stderr = _buffers()
        assert result.exit_code == 3
        # No JSON on stdout.
        assert stdout.strip() == ""
        assert "Not found" in stderr

    def test_empty_events_array_when_no_audit(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _raw_insert_key(
            env,
            customer_id=customer_id,
            key_prefix="NOAUDIT1",
            created_at="2026-04-16T10:00:00Z",
        )
        result = runner.invoke(
            app, ["show", "NOAUDIT1", "--format", "json", "--audit-tail", "5"]
        )
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        parsed = json.loads(stdout)
        assert parsed["events"] == []


# ---------------------------------------------------------------------------
# AC9 — read-only contract.
# ---------------------------------------------------------------------------


class TestShowReadOnly:
    def test_no_writes(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _key_id, key_prefix = _issue_key(env, customer_id)
        before = {
            "customer": _count(env, "customer"),
            "api_key": _count(env, "api_key"),
            "audit_log": _count(env, "audit_log"),
        }
        invocations: list[list[str]] = [
            ["show", key_prefix],
            ["show", key_prefix, "--audit-tail", "5"],
            ["show", customer_id],
            ["show", customer_id, "--audit-tail", "5"],
            ["show", key_prefix, "--format", "json"],
            ["show", customer_id, "--format", "json", "--audit-tail", "5"],
            ["show", "NOPENOPE"],
            ["show", "cust_01nonexistent00000000000"],
            ["show", "NOPE", "--format", "json"],
        ]
        for args in invocations:
            result = runner.invoke(app, args)
            assert result.exit_code in (0, 3)
            _clear_buffers()
        after = {
            "customer": _count(env, "customer"),
            "api_key": _count(env, "api_key"),
            "audit_log": _count(env, "audit_log"),
        }
        assert before == after


# ---------------------------------------------------------------------------
# AC10 — accessibility + help surface.
# ---------------------------------------------------------------------------


class TestShowAccessibility:
    def test_no_color_has_no_ansi(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env)
        _key_id, key_prefix = _issue_key(env, customer_id)
        # Re-wire stdout without no_color=True so Rich honors NO_COLOR env.
        monkeypatch.setenv("NO_COLOR", "1")
        output_mod._reset_for_tests()
        stdout_buf = StringIO()
        stderr_buf = StringIO()
        output_mod._stdout_console = Console(
            file=stdout_buf, force_terminal=False, width=120
        )
        output_mod._stderr_console = Console(
            file=stderr_buf, force_terminal=False, width=120, stderr=True
        )
        result = runner.invoke(app, ["show", key_prefix])
        stdout = stdout_buf.getvalue()
        assert result.exit_code == 0
        assert "\x1b[" not in stdout
        assert "active" in stdout


class TestShowHelpSurface:
    def test_help_lists_realistic_examples(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KEY_REGISTRY_DB_PATH", raising=False)
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        result = runner.invoke(app, ["show", "--help"])
        assert result.exit_code == 0
        ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        cleaned = ansi.sub("", result.stdout)
        for glyph in ("\u2502", "\u256d", "\u256e", "\u2570", "\u256f", "\u2500"):
            cleaned = cleaned.replace(glyph, " ")
        flat = re.sub(r"\s+", " ", cleaned)
        assert "cust_01j" in flat
        assert "EVb4xk8B" in flat
        assert "--audit-tail 20" in flat
        assert "--format json" in flat
        # Epilog example.
        assert "comadre-keys show EVb4xk8B --audit-tail 20" in flat

    def test_help_does_not_touch_db(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KEY_REGISTRY_DB_PATH", raising=False)
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        result = runner.invoke(app, ["show", "--help"])
        assert result.exit_code == 0
        assert not (tmp_path / "registry.db").exists()


# ---------------------------------------------------------------------------
# Log sanitization (structured INFO log has kind, not names).
# ---------------------------------------------------------------------------


class TestShowLogSanitization:
    def test_log_has_kind_not_names(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        from comadre.logging import get_logger

        _freeze_today(monkeypatch, date(2026, 4, 16))
        customer_id = _seed_customer(env, name="Helena Ribeiro")
        _clear_buffers()

        logger = get_logger("keys.cli")
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture(level=logging.INFO)
        logger.addHandler(handler)
        try:
            result = runner.invoke(app, ["show", customer_id])
        finally:
            logger.removeHandler(handler)
        assert result.exit_code == 0
        shown = [r for r in records if "Showed detail" in r.getMessage()]
        assert shown, "Expected a 'Showed detail' INFO record"
        joined = "\n".join(r.getMessage() for r in shown)
        assert "kind=customer" in joined
        assert "Helena" not in joined
        assert "helena@clinica.com" not in joined

    def test_log_redacts_cmdr_live_plaintext(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Operator-pasted `cmdr_live_<secret>` must not reach the INFO log."""
        from comadre.logging import get_logger

        _freeze_today(monkeypatch, date(2026, 4, 16))
        _clear_buffers()

        logger = get_logger("keys.cli")
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture(level=logging.INFO)
        logger.addHandler(handler)
        try:
            # Plaintext below is fabricated — no key by this prefix exists,
            # so the resolver returns not_found. The log emission happens
            # only on success paths today, but we still verify the redaction
            # contract by exercising the resolver with a structurally valid
            # plaintext via an issued key.
            customer_id = _seed_customer(env)
            _, key_prefix = _issue_key(env, customer_id)
            secret_suffix = key_prefix + "rest_of_the_secret_should_not_log"
            pasted = "cmdr_live_" + secret_suffix
            _clear_buffers()
            records.clear()
            result = runner.invoke(app, ["show", pasted])
        finally:
            logger.removeHandler(handler)
        assert result.exit_code == 0
        shown = [r for r in records if "Showed detail" in r.getMessage()]
        assert shown, "Expected a 'Showed detail' INFO record"
        joined = "\n".join(r.getMessage() for r in shown)
        assert "rest_of_the_secret_should_not_log" not in joined
        assert secret_suffix not in joined
        # Redacted form: cmdr_live_<first-8-of-suffix>… (truncation marker).
        assert "cmdr_live_" + key_prefix + "…" in joined
