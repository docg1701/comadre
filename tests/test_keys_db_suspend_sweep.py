"""Story 3.3 — tests for ``run_suspension_sweep`` and ``get_last_sweep_timestamp``.

Covers AC1-AC6, AC9, AC15, AC16, AC17. CLI-level assertions live in
``tests/test_keys_cli_suspend_sweep.py``. Seed helpers mirror the ones in
``tests/test_keys_db.py`` (tmp_path + ``get_connection`` + ``_apply_migrations``
+ raw-SQL seeders).
"""

from __future__ import annotations

import json
import sqlite3
import time
from datetime import date
from pathlib import Path
from typing import Any

import pytest

from comadre.keys.audit import log_event
from comadre.keys.db import (
    SuspensionSweepResult,
    _apply_migrations,
    generate_customer_id,
    generate_key_id,
    get_connection,
    get_last_sweep_timestamp,
    run_suspension_sweep,
)

_ISO_UTC_RE = r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z$"


def _seed_customer(conn: sqlite3.Connection, *, name: str = "Helena") -> str:
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
            "2026-04-01T12:00:00Z",
            None,
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
    key_prefix: str = "KEYAAAAA",
) -> str:
    key_id = generate_key_id()
    conn.execute(
        "INSERT INTO api_key ("
        "id, customer_id, key_hash, key_prefix, rate_limit_rpm, status, "
        "billing_mode, price_monthly, paid_until, created_at, last_used_at, "
        "notes"
        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
        (
            key_id,
            customer_id,
            key_hash,
            key_prefix,
            60,
            status,
            billing_mode,
            149.0,
            paid_until,
            "2026-04-01T12:00:00Z",
            None,
            "",
        ),
    )
    conn.commit()
    return key_id


def _fetch_status(conn: sqlite3.Connection, key_id: str) -> str:
    row = conn.execute("SELECT status FROM api_key WHERE id = ?", (key_id,)).fetchone()
    assert row is not None
    return str(row["status"])


def _fetch_audit(conn: sqlite3.Connection) -> list[sqlite3.Row]:
    return list(
        conn.execute(
            "SELECT actor, action, target_type, target_id, occurred_at, "
            "details_json FROM audit_log ORDER BY id ASC"
        )
    )


class TestRunSuspensionSweep:
    def test_sweeps_expired_active_manual_keys(self, tmp_path: Path) -> None:
        """AC1 — sweep flips only expired, active, manual rows."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            k_expired_old = _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                key_prefix="OLD11111",
                paid_until="2026-04-04",
            )
            k_cutoff_day = _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="b" * 64,
                key_prefix="CUT22222",
                paid_until="2026-04-06",
            )
            k_expired_recent = _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="c" * 64,
                key_prefix="REC33333",
                paid_until="2026-04-05",
            )

            result = run_suspension_sweep(conn, today=date(2026, 4, 6))

            assert isinstance(result, SuspensionSweepResult)
            assert result.swept_count == 2
            assert set(result.swept_key_ids) == {k_expired_old, k_expired_recent}
            assert result.cutoff_date == "2026-04-06"
            assert _fetch_status(conn, k_expired_old) == "suspended"
            assert _fetch_status(conn, k_expired_recent) == "suspended"
            assert _fetch_status(conn, k_cutoff_day) == "active"
        finally:
            conn.close()

    def test_never_sweeps_complimentary(self, tmp_path: Path) -> None:
        """AC1 — complimentary keys are never swept (billing_mode filter)."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            k_comp = _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                billing_mode="complimentary",
                paid_until="2026-04-05",
            )
            result = run_suspension_sweep(conn, today=date(2026, 4, 6))
            assert result.swept_count == 0
            assert _fetch_status(conn, k_comp) == "active"
        finally:
            conn.close()

    def test_never_sweeps_trial_window_null_paid_until(self, tmp_path: Path) -> None:
        """AC1 — NULL paid_until (trial window) is never swept."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            k_trial = _seed_api_key(
                conn, customer_id=cid, key_hash="a" * 64, paid_until=None
            )
            result = run_suspension_sweep(conn, today=date(2026, 4, 6))
            assert result.swept_count == 0
            assert _fetch_status(conn, k_trial) == "active"
        finally:
            conn.close()

    def test_never_sweeps_suspended(self, tmp_path: Path) -> None:
        """AC1 — already-suspended rows are excluded by ``status='active'``."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            k_susp = _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                status="suspended",
                paid_until="2026-04-01",
            )
            pre_audit_count = len(_fetch_audit(conn))
            result = run_suspension_sweep(conn, today=date(2026, 4, 6))
            assert result.swept_count == 0
            assert _fetch_status(conn, k_susp) == "suspended"
            # Only the summary row was added — no new per-key audit for k_susp.
            new_rows = _fetch_audit(conn)[pre_audit_count:]
            assert all(r["target_id"] != k_susp for r in new_rows)
        finally:
            conn.close()

    def test_never_sweeps_revoked(self, tmp_path: Path) -> None:
        """AC1 — revoked rows are terminal and never swept."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            k_rev = _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                status="revoked",
                paid_until="2026-04-01",
            )
            result = run_suspension_sweep(conn, today=date(2026, 4, 6))
            assert result.swept_count == 0
            assert _fetch_status(conn, k_rev) == "revoked"
        finally:
            conn.close()

    def test_writes_per_key_suspend_key_audit_rows(self, tmp_path: Path) -> None:
        """AC2 — one ``action='suspend_key'`` row per swept key."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            k1 = _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                key_prefix="AAAAAAAA",
                paid_until="2026-04-01",
            )
            k2 = _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="b" * 64,
                key_prefix="BBBBBBBB",
                paid_until="2026-04-03",
            )

            run_suspension_sweep(conn, today=date(2026, 4, 6))

            per_key = [
                r
                for r in _fetch_audit(conn)
                if r["action"] == "suspend_key" and r["target_id"] in {k1, k2}
            ]
            assert len(per_key) == 2
            for row in per_key:
                assert row["actor"] == "cron:suspension-sweep"
                assert row["target_type"] == "api_key"
                payload: dict[str, Any] = json.loads(row["details_json"])
                assert payload["cutoff_date"] == "2026-04-06"
                assert "paid_until" in payload
                assert payload["paid_until"] in {"2026-04-01", "2026-04-03"}
        finally:
            conn.close()

    def test_writes_summary_cron_suspend_audit_row(self, tmp_path: Path) -> None:
        """AC3 — exactly one summary row per invocation."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                paid_until="2026-04-01",
            )
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="b" * 64,
                key_prefix="BBBBBBBB",
                paid_until="2026-04-02",
            )

            result = run_suspension_sweep(conn, today=date(2026, 4, 6))

            summary = [
                r
                for r in _fetch_audit(conn)
                if r["action"] == "cron_suspend" and r["target_type"] == "system"
            ]
            assert len(summary) == 1
            assert summary[0]["target_id"] is None
            assert summary[0]["actor"] == "cron:suspension-sweep"
            payload = json.loads(summary[0]["details_json"])
            assert payload == {"swept_count": 2, "cutoff_date": "2026-04-06"}
            # AC3 byte-identity between result.completed_at and the summary row.
            assert summary[0]["occurred_at"] == result.completed_at
        finally:
            conn.close()

    def test_zero_row_sweep_still_writes_summary_row(self, tmp_path: Path) -> None:
        """AC4 — zero-row sweep still records the timestamp."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            # Only ineligible rows.
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                billing_mode="complimentary",
                paid_until="2026-04-01",
            )
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="b" * 64,
                key_prefix="BBBBBBBB",
                paid_until=None,
            )
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="c" * 64,
                key_prefix="CCCCCCCC",
                status="suspended",
                paid_until="2026-04-01",
            )
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="d" * 64,
                key_prefix="DDDDDDDD",
                paid_until="2026-04-06",
            )

            result = run_suspension_sweep(conn, today=date(2026, 4, 6))

            assert result.swept_count == 0
            assert result.swept_key_ids == ()
            summary = [
                r
                for r in _fetch_audit(conn)
                if r["action"] == "cron_suspend" and r["target_type"] == "system"
            ]
            assert len(summary) == 1
            per_key = [r for r in _fetch_audit(conn) if r["action"] == "suspend_key"]
            assert per_key == []
            # Canonical ISO-UTC shape.
            import re

            assert re.match(_ISO_UTC_RE, result.completed_at)
        finally:
            conn.close()

    def test_touches_sentinel_on_success(self, tmp_path: Path) -> None:
        """AC5 — sentinel file is touched after successful commit."""
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                paid_until="2026-04-01",
            )
            sentinel = Path(str(db_path) + ".invalidate")
            # Pre-create sentinel at a baseline mtime so we can assert strict-greater.
            sentinel.touch()
            baseline_mtime = sentinel.stat().st_mtime
            # Sleep past second-resolution mtime boundaries on coarse filesystems.
            time.sleep(0.05)
            run_suspension_sweep(conn, today=date(2026, 4, 6))
            assert sentinel.exists()
            assert sentinel.stat().st_mtime > baseline_mtime
        finally:
            conn.close()

    def test_sweep_never_touches_sentinel_on_rollback(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """AC6 — mid-sweep error leaves state untouched (rollback)."""
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            k1 = _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                key_prefix="AAAAAAAA",
                paid_until="2026-04-01",
            )
            k2 = _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="b" * 64,
                key_prefix="BBBBBBBB",
                paid_until="2026-04-02",
            )
            k3 = _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="c" * 64,
                key_prefix="CCCCCCCC",
                paid_until="2026-04-03",
            )
            # Pre-seed the sentinel with a known baseline mtime so we can
            # assert it didn't change — AC6's literal wording ("sentinel
            # mtime is unchanged"). A prior version of this test deleted the
            # sentinel and asserted absence, which would have silently passed
            # a regression that moved the touch inside the ``with conn:``
            # block (filesystem ops don't participate in DB rollback).
            sentinel = Path(str(db_path) + ".invalidate")
            sentinel.touch()
            baseline_mtime = sentinel.stat().st_mtime
            # Sleep past second-resolution mtime boundaries on coarse FSes.
            time.sleep(0.05)

            # Raise on the second per-key audit write.
            call_counter = {"n": 0}
            real_log_event = log_event

            def _fail_on_second(conn: sqlite3.Connection, **kwargs: Any) -> None:
                call_counter["n"] += 1
                if call_counter["n"] == 2:
                    raise ValueError("simulated audit failure")
                real_log_event(conn, **kwargs)

            monkeypatch.setattr(
                "comadre.keys.db.log_event", _fail_on_second, raising=False
            )
            # run_suspension_sweep does ``from comadre.keys.audit import log_event``
            # at call time — monkeypatch the source module.
            monkeypatch.setattr("comadre.keys.audit.log_event", _fail_on_second)

            with pytest.raises(ValueError, match="simulated audit failure"):
                run_suspension_sweep(conn, today=date(2026, 4, 6))

            # All three rows stayed active — transaction rolled back.
            assert _fetch_status(conn, k1) == "active"
            assert _fetch_status(conn, k2) == "active"
            assert _fetch_status(conn, k3) == "active"
            # No new audit rows committed (the rollback wipes everything written
            # inside the ``with conn:`` block, including the successful first call).
            assert not any(
                r["action"] in {"suspend_key", "cron_suspend"}
                for r in _fetch_audit(conn)
            )
            # Sentinel mtime unchanged — the post-commit touch never ran.
            assert sentinel.exists()
            assert sentinel.stat().st_mtime == baseline_mtime
        finally:
            conn.close()

    def test_actor_param_flows_through(self, tmp_path: Path) -> None:
        """Custom ``actor`` parameter propagates to every resulting audit row."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                paid_until="2026-04-01",
            )

            run_suspension_sweep(conn, today=date(2026, 4, 6), actor="test:sweep")

            new_rows = [
                r
                for r in _fetch_audit(conn)
                if r["action"] in {"suspend_key", "cron_suspend"}
            ]
            assert new_rows
            for row in new_rows:
                assert row["actor"] == "test:sweep"
        finally:
            conn.close()

    def test_swept_key_ids_is_tuple(self, tmp_path: Path) -> None:
        """``swept_key_ids`` is a tuple (immutable) and reflects the DB state."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            expected_ids: set[str] = set()
            for i in range(10):
                kid = _seed_api_key(
                    conn,
                    customer_id=cid,
                    key_hash=f"{i:064x}",
                    key_prefix=f"KEY{i:05d}",
                    paid_until="2026-04-01",
                )
                expected_ids.add(kid)

            result = run_suspension_sweep(conn, today=date(2026, 4, 6))

            assert isinstance(result.swept_key_ids, tuple)
            assert set(result.swept_key_ids) == expected_ids
            # DB agrees.
            rows = conn.execute(
                "SELECT id FROM api_key WHERE status = 'suspended'"
            ).fetchall()
            assert {r["id"] for r in rows} == expected_ids
        finally:
            conn.close()

    def test_performance_budget_nfr3(self, tmp_path: Path) -> None:
        """AC9 — 1 000-key sweep under 1 000 ms (NFR3).

        Actual wall-clock should be <100 ms on bare metal; slack is for CI jitter.
        """
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            # Bulk-seed 1 000 rows via direct SQL (per-call insertion would be slow).
            with conn:
                for i in range(1000):
                    conn.execute(
                        "INSERT INTO api_key ("
                        "id, customer_id, key_hash, key_prefix, rate_limit_rpm, "
                        "status, billing_mode, price_monthly, paid_until, "
                        "created_at, last_used_at, notes"
                        ") VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                        (
                            generate_key_id(),
                            cid,
                            f"{i:064x}",
                            f"K{i:07d}",
                            60,
                            "active",
                            "manual",
                            149.0,
                            "2026-01-01",
                            "2026-01-01T00:00:00Z",
                            None,
                            "",
                        ),
                    )

            start = time.perf_counter()
            result = run_suspension_sweep(conn, today=date(2026, 4, 6))
            elapsed_ms = (time.perf_counter() - start) * 1000.0

            assert result.swept_count == 1000
            # NFR3: under 1 s for 1 K keys; production figure should be <100 ms.
            assert elapsed_ms < 1000.0, f"sweep took {elapsed_ms:.1f} ms"

            # AC9 — assert the 1 000 per-key audit rows + 1 summary row
            # were actually committed. A regression that silently skipped
            # log_event under high volume would pass a wall-clock-only check.
            per_key_count = conn.execute(
                "SELECT COUNT(*) FROM audit_log "
                "WHERE action = 'suspend_key' AND target_type = 'api_key'"
            ).fetchone()[0]
            summary_count = conn.execute(
                "SELECT COUNT(*) FROM audit_log "
                "WHERE action = 'cron_suspend' AND target_type = 'system'"
            ).fetchone()[0]
            assert per_key_count == 1000
            assert summary_count == 1
        finally:
            conn.close()


class TestGetLastSweepTimestamp:
    def test_returns_none_on_fresh_db(self, tmp_path: Path) -> None:
        """AC16 — no sweep has run → ``None``."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            assert get_last_sweep_timestamp(conn) is None
        finally:
            conn.close()

    def test_returns_most_recent_summary_row(self, tmp_path: Path) -> None:
        """AC16 — most-recent ``cron_suspend``/``system`` row wins."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            with conn:
                log_event(
                    conn,
                    actor="cron:suspension-sweep",
                    action="cron_suspend",
                    target_type="system",
                    target_id=None,
                    details={"swept_count": 0, "cutoff_date": "2026-04-05"},
                    occurred_at="2026-04-05T03:30:00Z",
                )
                log_event(
                    conn,
                    actor="cron:suspension-sweep",
                    action="cron_suspend",
                    target_type="system",
                    target_id=None,
                    details={"swept_count": 3, "cutoff_date": "2026-04-06"},
                    occurred_at="2026-04-06T03:30:05Z",
                )
            assert get_last_sweep_timestamp(conn) == "2026-04-06T03:30:05Z"
        finally:
            conn.close()

    def test_ignores_per_key_suspend_key_rows(self, tmp_path: Path) -> None:
        """AC16 — per-key ``suspend_key`` rows are NOT candidates."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            with conn:
                # A per-key suspend_key row — newer timestamp but wrong target_type.
                log_event(
                    conn,
                    actor="cron:suspension-sweep",
                    action="suspend_key",
                    target_type="api_key",
                    target_id="key_fake",
                    details={"paid_until": "2026-04-01"},
                    occurred_at="2026-04-07T00:00:00Z",
                )
                # The real summary row — older.
                log_event(
                    conn,
                    actor="cron:suspension-sweep",
                    action="cron_suspend",
                    target_type="system",
                    target_id=None,
                    details={"swept_count": 1, "cutoff_date": "2026-04-05"},
                    occurred_at="2026-04-05T03:30:00Z",
                )
            assert get_last_sweep_timestamp(conn) == "2026-04-05T03:30:00Z"
        finally:
            conn.close()


class TestIdempotence:
    def test_second_run_suspends_nothing(self, tmp_path: Path) -> None:
        """AC17 — repeated invocation is a no-op; summary row still written."""
        conn = get_connection(tmp_path / "registry.db")
        try:
            _apply_migrations(conn)
            cid = _seed_customer(conn)
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="a" * 64,
                paid_until="2026-04-01",
            )
            _seed_api_key(
                conn,
                customer_id=cid,
                key_hash="b" * 64,
                key_prefix="BBBBBBBB",
                paid_until="2026-04-02",
            )

            first = run_suspension_sweep(conn, today=date(2026, 4, 6))
            second = run_suspension_sweep(conn, today=date(2026, 4, 6))

            assert first.swept_count == 2
            assert second.swept_count == 0

            per_key = [r for r in _fetch_audit(conn) if r["action"] == "suspend_key"]
            summary = [r for r in _fetch_audit(conn) if r["action"] == "cron_suspend"]
            assert len(per_key) == 2  # only the first run wrote per-key rows
            assert len(summary) == 2  # both runs wrote summary rows
        finally:
            conn.close()
