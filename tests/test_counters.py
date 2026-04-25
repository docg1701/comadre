"""Unit tests for ``comadre.counters.RequestCounters`` (Story 2.3).

Lean by design (test-suite review 2026-04-25): per-AC unit tests
collapsed into integration-style covers — counters survive a request/
429 cycle, snapshot is JSON-serializable + PII-clean, atomic write
produces 0600 file, multi-replica aggregation works.
"""

from __future__ import annotations

import json
import re
import stat
import time
from pathlib import Path

import pytest

from comadre.counters import (
    DEFAULT_SNAPSHOT_INTERVAL_SECONDS,
    SNAPSHOT_SCHEMA_VERSION,
    RequestCounters,
    aggregate_cache_status,
    aggregate_key_stats,
    read_all_snapshots,
)


def test_counters_track_requests_429_independently_per_key() -> None:
    """Two keys + a 429 → counters land in separate buckets, no double-count."""
    rc = RequestCounters()
    for _ in range(3):
        rc.incr_request("key_aaa")
        rc.incr_auth_success("key_aaa")
    rc.incr_429("key_aaa")
    rc.incr_request("key_bbb")
    rc.incr_auth_success("key_bbb")

    a = rc.per_key["key_aaa"]
    b = rc.per_key["key_bbb"]
    assert a.requests_total == 3 and a.auth_success == 3 and a.rate_limit_429 == 1
    assert b.requests_total == 1 and b.auth_success == 1 and b.rate_limit_429 == 0


def test_counters_peak_rpm_non_decreasing_window_prunes(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """peak_rpm = max-observed; window_hits prunes after WINDOW_SECONDS."""
    from comadre.counters import WINDOW_SECONDS

    monkeypatch.setattr(time, "monotonic", lambda: 100.0)
    rc = RequestCounters()
    for _ in range(10):
        rc.incr_request("key_aaa")
    assert rc.per_key["key_aaa"].peak_rpm == 10

    monkeypatch.setattr(time, "monotonic", lambda: 100.0 + WINDOW_SECONDS + 1)
    for _ in range(3):
        rc.incr_request("key_aaa")
    bucket = rc.per_key["key_aaa"]
    assert bucket.peak_rpm == 10
    assert len(bucket.window_hits) == 3


def test_snapshot_is_pii_clean_and_json_serializable() -> None:
    """AC19: snapshot must NEVER contain bearer / hash / CPF / email tokens.
    Defense-in-depth — the writer has no path that emits them, but the
    test fails loud if one ever appears."""
    rc = RequestCounters()
    rc.incr_request("key_01ABC")
    rc.incr_429("key_01ABC")
    data = rc.snapshot(auth_cache_snapshot={"entries": 1, "hits": 5, "misses": 1})

    assert data["schema_version"] == SNAPSHOT_SCHEMA_VERSION == 1
    assert data["per_key"]["key_01ABC"]["requests_total"] == 1
    assert data["per_key"]["key_01ABC"]["rate_limit_429"] == 1

    serialized = json.dumps(data)  # JSON serializable
    assert "cmdr_live_" not in serialized
    assert re.search(r"[0-9a-f]{64}", serialized) is None  # SHA-256 hex
    assert re.search(r"\d{11,14}", serialized) is None  # CPF/CNPJ
    assert (
        re.search(r"[A-Za-z0-9._%+-]+@[A-Za-z0-9.-]+\.[A-Za-z]{2,}", serialized) is None
    )


def test_atomic_write_produces_mode_0600_and_no_tmp_leftover(
    tmp_path: Path,
) -> None:
    """Snapshot writer: atomic ``.tmp`` rename → final file 0600 + no leftover."""
    path = tmp_path / "counters.json"
    rc = RequestCounters(snapshot_path=path)
    rc._auth_cache_snapshot = lambda: {"entries": 0}
    rc.incr_request("key_aaa")
    rc._write_snapshot_sync()

    assert path.exists()
    assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list(tmp_path.glob("*.tmp")) == []
    data = json.loads(path.read_text())
    assert data["per_key"]["key_aaa"]["requests_total"] == 1


async def test_snapshot_writer_lifecycle_writes_final_snapshot_on_stop(
    tmp_path: Path,
) -> None:
    """``stop_snapshot_writer`` writes one final snapshot then cancels —
    so a graceful shutdown doesn't lose the most-recent counts."""
    path = tmp_path / "counters.json"
    rc = RequestCounters(snapshot_path=path, snapshot_interval_seconds=9999)
    rc.start_snapshot_writer(auth_cache_snapshot=lambda: {"entries": 0})
    rc.incr_request("key_aaa")
    await rc.stop_snapshot_writer()
    data = json.loads(path.read_text())
    assert data["per_key"]["key_aaa"]["requests_total"] == 1
    # Idempotent: a second stop must not raise.
    await rc.stop_snapshot_writer()


def test_aggregate_across_replicas_sums_counters_picks_max_for_peak(
    tmp_path: Path,
) -> None:
    """Multi-replica deployments: ``aggregate_*`` sums counters and
    picks max for peak_rpm / last_activity_at — operator-visible
    correctness across replicas."""
    db_base = tmp_path / "registry.db"
    for replica, payload in (
        (
            "alpha",
            {
                "schema_version": 1,
                "written_at": "2026-04-18T12:00:00.000Z",
                "process_uptime_seconds": 60,
                "auth_cache": {
                    "entries": 5,
                    "hits": 10,
                    "misses": 1,
                    "maxsize": 4096,
                    "ttl_seconds": 60,
                },
                "per_key": {
                    "key_x": {
                        "requests_total": 10,
                        "auth_success": 10,
                        "rate_limit_429": 0,
                        "peak_rpm": 5,
                        "avg_rpm_last_60s": 5,
                        "last_activity_at": "2026-04-18T12:00:00.000Z",
                    },
                },
            },
        ),
        (
            "beta",
            {
                "schema_version": 1,
                "written_at": "2026-04-18T12:00:00.000Z",
                "process_uptime_seconds": 60,
                "auth_cache": {
                    "entries": 3,
                    "hits": 4,
                    "misses": 0,
                    "maxsize": 4096,
                    "ttl_seconds": 60,
                },
                "per_key": {
                    "key_x": {
                        "requests_total": 7,
                        "auth_success": 7,
                        "rate_limit_429": 1,
                        "peak_rpm": 9,
                        "avg_rpm_last_60s": 7,
                        "last_activity_at": "2026-04-18T12:01:00.000Z",
                    },
                },
            },
        ),
    ):
        snap_path = Path(f"{db_base}.counters.{replica}.json")
        snap_path.write_text(json.dumps(payload))

    snapshots = read_all_snapshots(str(db_base))
    assert len(snapshots) == 2

    cache_agg = aggregate_cache_status(snapshots)
    assert cache_agg.hits == 14
    assert cache_agg.entries == 8

    key_agg = aggregate_key_stats(snapshots, "key_x")
    assert key_agg is not None
    assert key_agg.requests_total == 17  # 10 + 7
    assert key_agg.rate_limit_429 == 1
    assert key_agg.peak_rpm == 9  # max(5, 9)
    assert key_agg.last_activity_at == "2026-04-18T12:01:00.000Z"  # latest


def test_default_snapshot_interval_is_15s() -> None:
    """The 15-second cadence is contractual — operators tune it via env."""
    assert DEFAULT_SNAPSHOT_INTERVAL_SECONDS == 15
    assert RequestCounters().snapshot_interval_seconds == 15
