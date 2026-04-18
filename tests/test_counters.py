"""Unit tests for ``comadre.counters.RequestCounters`` — Story 2.3."""

from __future__ import annotations

import asyncio
import json
import stat
import time
from pathlib import Path
from typing import Any

import pytest

from comadre.counters import (
    DEFAULT_SNAPSHOT_INTERVAL_SECONDS,
    SNAPSHOT_SCHEMA_VERSION,
    WINDOW_SECONDS,
    RequestCounters,
    _iso_utc_ms,
)


class TestIncrementCounts:
    """AC1 — ``incr_request`` / ``incr_auth_success`` bump the right fields."""

    def test_incr_request_seeds_bucket_and_counts_one(self) -> None:
        rc = RequestCounters()
        rc.incr_request("key_aaa")
        bucket = rc.per_key["key_aaa"]
        assert bucket.requests_total == 1
        assert len(bucket.window_hits) == 1
        assert bucket.peak_rpm == 1

    def test_incr_auth_success_independent_of_request(self) -> None:
        rc = RequestCounters()
        rc.incr_auth_success("key_aaa")
        assert rc.per_key["key_aaa"].auth_success == 1
        assert rc.per_key["key_aaa"].requests_total == 0

    def test_happy_path_increments_both(self) -> None:
        rc = RequestCounters()
        rc.incr_request("key_aaa")
        rc.incr_auth_success("key_aaa")
        bucket = rc.per_key["key_aaa"]
        assert bucket.requests_total == 1
        assert bucket.auth_success == 1
        assert bucket.rate_limit_429 == 0

    def test_two_keys_are_independent(self) -> None:
        rc = RequestCounters()
        rc.incr_request("key_aaa")
        rc.incr_request("key_bbb")
        rc.incr_request("key_bbb")
        assert rc.per_key["key_aaa"].requests_total == 1
        assert rc.per_key["key_bbb"].requests_total == 2


class TestRateLimit429:
    """AC2 — 429 bumps ``rate_limit_429`` without re-incrementing ``requests_total``."""

    def test_429_does_not_double_count_total(self) -> None:
        rc = RequestCounters()
        # Simulate three successful auths (= three requests), then one 429
        for _ in range(3):
            rc.incr_request("key_aaa")
            rc.incr_auth_success("key_aaa")
        rc.incr_429("key_aaa")
        bucket = rc.per_key["key_aaa"]
        assert bucket.requests_total == 3
        assert bucket.auth_success == 3
        assert bucket.rate_limit_429 == 1

    def test_429_only_creates_bucket_lazily(self) -> None:
        rc = RequestCounters()
        rc.incr_429("key_aaa")
        # Counter appears with zeroed fields and rate_limit_429=1. Should
        # not happen in production (verify_api_key would raise first), but
        # the counter does not guard against it — fail-loud > silent drop.
        assert rc.per_key["key_aaa"].rate_limit_429 == 1
        assert rc.per_key["key_aaa"].requests_total == 0


class TestPeakAndAverage:
    """AC3, AC4 — peak_rpm is max-observed; avg_rpm_last_60s is post-prune count."""

    def test_peak_rpm_is_non_decreasing(self, monkeypatch: pytest.MonkeyPatch) -> None:
        rc = RequestCounters()
        # Freeze monotonic clock to inject controlled timestamps. All 10
        # hits in the same second → peak_rpm = 10.
        monkeypatch.setattr(time, "monotonic", lambda: 100.0)
        for _ in range(10):
            rc.incr_request("key_aaa")
        assert rc.per_key["key_aaa"].peak_rpm == 10

        # Jump past the window; the 10 old hits prune. Three new hits →
        # avg_rpm_last_60s should be 3, peak stays at 10.
        monkeypatch.setattr(time, "monotonic", lambda: 100.0 + WINDOW_SECONDS + 1)
        for _ in range(3):
            rc.incr_request("key_aaa")
        bucket = rc.per_key["key_aaa"]
        assert bucket.peak_rpm == 10
        assert len(bucket.window_hits) == 3

    def test_avg_rpm_last_60s_equals_window_length(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        rc = RequestCounters()
        now = [100.0]
        monkeypatch.setattr(time, "monotonic", lambda: now[0])
        # 8 fresh hits within the window.
        for _ in range(8):
            rc.incr_request("key_aaa")
        # 4 "old" hits — bump time past the window and confirm prune.
        now[0] = 100.0 + WINDOW_SECONDS + 1
        rc.per_key["key_aaa"].prune_window(now=now[0])
        assert len(rc.per_key["key_aaa"].window_hits) == 0


class TestSnapshotSchema:
    """AC7, AC19 — snapshot produces schema-v1 JSON with zero PII."""

    def test_snapshot_has_schema_version_1(self) -> None:
        rc = RequestCounters()
        data = rc.snapshot(auth_cache_snapshot={"entries": 0})
        assert data["schema_version"] == SNAPSHOT_SCHEMA_VERSION == 1

    def test_snapshot_includes_process_uptime(self) -> None:
        rc = RequestCounters()
        data = rc.snapshot(auth_cache_snapshot={})
        # Fresh counters → uptime is 0 or a tiny positive int.
        assert isinstance(data["process_uptime_seconds"], int)
        assert data["process_uptime_seconds"] >= 0

    def test_snapshot_forwards_auth_cache_dict(self) -> None:
        rc = RequestCounters()
        auth_cache_snap = {"entries": 17, "maxsize": 4096, "hits": 10, "misses": 2}
        data = rc.snapshot(auth_cache_snapshot=auth_cache_snap)
        assert data["auth_cache"] == auth_cache_snap

    def test_snapshot_per_key_entry_fields(self) -> None:
        rc = RequestCounters()
        rc.incr_request("key_aaa")
        rc.incr_auth_success("key_aaa")
        rc.incr_429("key_aaa")
        data = rc.snapshot(auth_cache_snapshot={})
        entry = data["per_key"]["key_aaa"]
        assert entry["requests_total"] == 1
        assert entry["auth_success"] == 1
        assert entry["rate_limit_429"] == 1
        assert entry["peak_rpm"] == 1
        assert entry["avg_rpm_last_60s"] == 1
        assert isinstance(entry["last_activity_at"], str)

    def test_snapshot_last_activity_none_before_first_request(self) -> None:
        rc = RequestCounters()
        rc.incr_auth_success("key_aaa")  # no incr_request yet
        data = rc.snapshot(auth_cache_snapshot={})
        assert data["per_key"]["key_aaa"]["last_activity_at"] is None

    def test_snapshot_is_json_serializable(self) -> None:
        rc = RequestCounters()
        rc.incr_request("key_aaa")
        data = rc.snapshot(auth_cache_snapshot={"entries": 1})
        # Round-trip through json to assert no non-serializable values slipped in.
        json.loads(json.dumps(data))

    def test_snapshot_contains_no_pii_markers(self) -> None:
        """AC19 — snapshot must never contain bearer / hash / email / CPF material."""
        rc = RequestCounters()
        rc.incr_request("key_01ABC")
        rc.incr_429("key_01ABC")
        data = rc.snapshot(auth_cache_snapshot={"entries": 0})
        serialized = json.dumps(data)
        assert "cmdr_live_" not in serialized
        # 64-hex run (SHA-256 hex form)
        import re

        assert re.search(r"[0-9a-f]{64}", serialized) is None


class TestAtomicWrite:
    """AC7 — snapshot writer uses ``.tmp`` + atomic rename."""

    def test_write_produces_file_with_valid_json(self, tmp_path: Path) -> None:
        path = tmp_path / "counters.json"
        rc = RequestCounters(snapshot_path=path)
        rc._auth_cache_snapshot = lambda: {"entries": 0}
        rc.incr_request("key_aaa")
        rc._write_snapshot_sync()
        assert path.exists()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == 1
        assert "key_aaa" in data["per_key"]

    def test_write_sets_mode_0600_on_first_write(self, tmp_path: Path) -> None:
        path = tmp_path / "counters.json"
        rc = RequestCounters(snapshot_path=path)
        rc._auth_cache_snapshot = lambda: {"entries": 0}
        rc._write_snapshot_sync()
        mode = stat.S_IMODE(path.stat().st_mode)
        assert mode == 0o600

    def test_tmp_file_is_cleaned_up_after_replace(self, tmp_path: Path) -> None:
        path = tmp_path / "counters.json"
        rc = RequestCounters(snapshot_path=path)
        rc._auth_cache_snapshot = lambda: {"entries": 0}
        rc._write_snapshot_sync()
        # No leftover .tmp sibling — atomic replace moved it into place.
        assert list(tmp_path.glob("*.tmp")) == []

    def test_write_is_idempotent(self, tmp_path: Path) -> None:
        """Two consecutive writes yield valid files both times (chmod guarded)."""
        path = tmp_path / "counters.json"
        rc = RequestCounters(snapshot_path=path)
        rc._auth_cache_snapshot = lambda: {"entries": 0}
        rc._write_snapshot_sync()
        rc._write_snapshot_sync()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["schema_version"] == 1


class TestSnapshotWriterTask:
    """AC15, AC16 — snapshot writer lifecycle on the asyncio event loop."""

    async def test_start_returns_task_and_fires_once(self, tmp_path: Path) -> None:
        path = tmp_path / "counters.json"
        rc = RequestCounters(snapshot_path=path, snapshot_interval_seconds=0)
        task = rc.start_snapshot_writer(auth_cache_snapshot=lambda: {"entries": 0})
        assert task is rc._task
        # Give the loop a chance to iterate the writer once.
        await asyncio.sleep(0.05)
        await rc.stop_snapshot_writer()
        assert path.exists()

    async def test_stop_writes_final_snapshot_and_cancels_cleanly(
        self, tmp_path: Path
    ) -> None:
        path = tmp_path / "counters.json"
        rc = RequestCounters(snapshot_path=path, snapshot_interval_seconds=9999)
        rc.start_snapshot_writer(auth_cache_snapshot=lambda: {"entries": 0})
        # Writer is sleeping ~9999s; stop should write a final snapshot
        # anyway because ``stop_snapshot_writer`` does one final write
        # before cancelling the task.
        rc.incr_request("key_aaa")
        await rc.stop_snapshot_writer()
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data["per_key"]["key_aaa"]["requests_total"] == 1

    async def test_stop_is_idempotent(self, tmp_path: Path) -> None:
        rc = RequestCounters(snapshot_path=tmp_path / "c.json")
        rc.start_snapshot_writer(auth_cache_snapshot=lambda: {})
        await rc.stop_snapshot_writer()
        await rc.stop_snapshot_writer()  # must not raise

    async def test_writer_survives_single_write_failure(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """A failing write must not crash the writer task."""
        import comadre.counters as counters_mod

        path = tmp_path / "counters.json"
        rc = RequestCounters(snapshot_path=path, snapshot_interval_seconds=0)

        call_count = {"n": 0}
        real_write = counters_mod._atomic_write

        def flaky_write(target: Path, payload: str) -> None:
            call_count["n"] += 1
            if call_count["n"] == 1:
                raise OSError("disk full")
            real_write(target, payload)

        monkeypatch.setattr(counters_mod, "_atomic_write", flaky_write)
        rc.start_snapshot_writer(auth_cache_snapshot=lambda: {})
        # Drive the loop twice.
        await asyncio.sleep(0.05)
        await rc.stop_snapshot_writer()
        # Second call must have fired.
        assert call_count["n"] >= 2


class TestDefaults:
    """Sanity — the module-level constants are wired through."""

    def test_default_interval_is_15_seconds(self) -> None:
        assert DEFAULT_SNAPSHOT_INTERVAL_SECONDS == 15
        rc = RequestCounters()
        assert rc.snapshot_interval_seconds == DEFAULT_SNAPSHOT_INTERVAL_SECONDS

    def test_iso_utc_ms_roundtrip(self) -> None:
        from datetime import UTC, datetime

        dt = datetime(2026, 4, 18, 18, 32, 4, 123000, tzinfo=UTC)
        assert _iso_utc_ms(dt) == "2026-04-18T18:32:04.123Z"


class TestImportGraph:
    """AC20 — counters.py only imports from stdlib + comadre.logging."""

    def test_no_comadre_imports_other_than_logging(self) -> None:
        src = Path(__file__).resolve().parent.parent / "src" / "comadre" / "counters.py"
        content = src.read_text(encoding="utf-8")
        allowed = {"from comadre.logging import get_logger"}
        for raw_line in content.splitlines():
            stripped = raw_line.strip()
            if not stripped.startswith("from comadre."):
                continue
            assert stripped in allowed, f"Unexpected comadre import: {stripped!r}"

    def test_counters_loads_standalone(self) -> None:
        """``python -c 'import comadre.counters'`` must not fail."""
        # The mere fact that this test module imports ``RequestCounters``
        # at top level is the assertion — the import would ImportError if
        # the module pulled in a cycle.
        assert RequestCounters is not None


class TestReplicaPathHelpers:
    """Story 2.3 multi-replica — path helpers compose hostname-scoped files."""

    def test_default_replica_id_returns_non_empty_string(self) -> None:
        from comadre.counters import default_replica_id

        rid = default_replica_id()
        assert isinstance(rid, str)
        assert rid  # hostname is never empty on a sane system

    def test_snapshot_path_embeds_replica_id(self, tmp_path: Path) -> None:
        from comadre.counters import counters_snapshot_path

        db_path = tmp_path / "registry.db"
        got = counters_snapshot_path(db_path, replica_id="alpha-1")
        assert got == tmp_path / "registry.db.counters.alpha-1.json"

    def test_snapshot_glob_matches_any_replica(self, tmp_path: Path) -> None:
        from comadre.counters import counters_snapshot_glob

        db_path = tmp_path / "registry.db"
        parent, pattern = counters_snapshot_glob(db_path)
        assert parent == tmp_path
        # Glob matches the filename produced by counters_snapshot_path.
        assert pattern == "registry.db.counters.*.json"
        # Drop two files, one per "replica" — glob must see both.
        (tmp_path / "registry.db.counters.alpha.json").write_text("{}")
        (tmp_path / "registry.db.counters.beta.json").write_text("{}")
        matches = sorted(p.name for p in parent.glob(pattern))
        assert matches == [
            "registry.db.counters.alpha.json",
            "registry.db.counters.beta.json",
        ]


class TestReadAndAggregate:
    """Story 2.3 multi-replica — readers glob all snapshots; aggregators sum."""

    def _make_snapshot(
        self,
        tmp_path: Path,
        *,
        replica: str,
        written_at_offset_s: int = 0,
        per_key: dict[str, dict[str, Any]] | None = None,
        auth_cache: dict[str, Any] | None = None,
        process_uptime_seconds: int = 100,
    ) -> Path:
        """Write a snapshot JSON file under ``tmp_path`` for the given replica."""
        from datetime import UTC as _UTC
        from datetime import datetime as _dt
        from datetime import timedelta

        from comadre.counters import counters_snapshot_path

        written = _dt.now(_UTC) - timedelta(seconds=written_at_offset_s)
        db_path = tmp_path / "registry.db"
        path = counters_snapshot_path(db_path, replica_id=replica)
        payload = {
            "schema_version": 1,
            "written_at": written.strftime("%Y-%m-%dT%H:%M:%S.000Z"),
            "process_uptime_seconds": process_uptime_seconds,
            "auth_cache": auth_cache or {},
            "per_key": per_key or {},
        }
        path.write_text(json.dumps(payload), encoding="utf-8")
        return path

    def test_read_all_snapshots_returns_empty_when_none_exist(
        self, tmp_path: Path
    ) -> None:
        from comadre.counters import read_all_snapshots

        result = read_all_snapshots(tmp_path / "registry.db")
        assert result == []

    def test_read_all_snapshots_skips_malformed_json(self, tmp_path: Path) -> None:
        from comadre.counters import counters_snapshot_path, read_all_snapshots

        db_path = tmp_path / "registry.db"
        counters_snapshot_path(db_path, replica_id="good").write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "written_at": "2026-04-18T18:00:00.000Z",
                    "process_uptime_seconds": 10,
                    "auth_cache": {"entries": 1, "hits": 5, "misses": 1, "maxsize": 10},
                    "per_key": {},
                }
            ),
            encoding="utf-8",
        )
        counters_snapshot_path(db_path, replica_id="bad").write_text(
            "{not valid json", encoding="utf-8"
        )
        result = read_all_snapshots(db_path)
        # Only the good snapshot contributes.
        assert len(result) == 1

    def test_aggregate_cache_status_sums_across_replicas(self, tmp_path: Path) -> None:
        from comadre.counters import aggregate_cache_status, read_all_snapshots

        self._make_snapshot(
            tmp_path,
            replica="alpha",
            auth_cache={"entries": 10, "hits": 100, "misses": 5, "maxsize": 4096},
            process_uptime_seconds=60,
        )
        self._make_snapshot(
            tmp_path,
            replica="beta",
            auth_cache={"entries": 7, "hits": 50, "misses": 2, "maxsize": 4096},
            process_uptime_seconds=30,
            written_at_offset_s=2,
        )
        snapshots = read_all_snapshots(tmp_path / "registry.db")
        agg = aggregate_cache_status(snapshots)
        assert agg is not None
        assert agg.replicas == 2
        assert agg.entries == 17
        assert agg.hits == 150
        assert agg.misses == 7
        assert agg.maxsize_per_replica == 4096
        assert abs(agg.hit_rate - 150 / 157) < 1e-6
        # process_uptime_seconds = MIN across replicas (conservative window).
        assert agg.process_uptime_seconds == 30
        # snapshot_age_seconds = MIN (freshness of freshest).
        assert agg.snapshot_age_seconds == 0

    def test_aggregate_cache_status_none_when_no_snapshots(
        self, tmp_path: Path
    ) -> None:
        from comadre.counters import aggregate_cache_status, read_all_snapshots

        assert (
            aggregate_cache_status(read_all_snapshots(tmp_path / "registry.db")) is None
        )

    def test_aggregate_key_stats_sums_and_picks_max_for_peak_and_activity(
        self, tmp_path: Path
    ) -> None:
        from comadre.counters import aggregate_key_stats, read_all_snapshots

        self._make_snapshot(
            tmp_path,
            replica="alpha",
            per_key={
                "key_X": {
                    "requests_total": 100,
                    "auth_success": 100,
                    "rate_limit_429": 2,
                    "peak_rpm": 20,
                    "avg_rpm_last_60s": 5,
                    "last_activity_at": "2026-04-18T18:00:00.000Z",
                }
            },
            process_uptime_seconds=100,
        )
        self._make_snapshot(
            tmp_path,
            replica="beta",
            per_key={
                "key_X": {
                    "requests_total": 50,
                    "auth_success": 50,
                    "rate_limit_429": 1,
                    "peak_rpm": 35,
                    "avg_rpm_last_60s": 3,
                    "last_activity_at": "2026-04-18T18:05:00.000Z",
                }
            },
            process_uptime_seconds=50,
        )
        snapshots = read_all_snapshots(tmp_path / "registry.db")
        agg = aggregate_key_stats(snapshots, "key_X")
        assert agg is not None
        assert agg.requests_total == 150  # sum
        assert agg.auth_success == 150
        assert agg.rate_limit_429 == 3
        assert agg.peak_rpm == 35  # max
        assert agg.avg_rpm_last_60s == 8  # sum
        assert agg.last_activity_at == "2026-04-18T18:05:00.000Z"  # max
        assert agg.process_uptime_seconds == 50  # min
        assert agg.replicas == 2

    def test_aggregate_key_stats_none_when_no_replica_has_the_key(
        self, tmp_path: Path
    ) -> None:
        from comadre.counters import aggregate_key_stats, read_all_snapshots

        self._make_snapshot(
            tmp_path,
            replica="alpha",
            per_key={
                "key_OTHER": {
                    "requests_total": 1,
                    "auth_success": 1,
                    "rate_limit_429": 0,
                    "peak_rpm": 1,
                    "avg_rpm_last_60s": 1,
                    "last_activity_at": None,
                }
            },
        )
        snapshots = read_all_snapshots(tmp_path / "registry.db")
        assert aggregate_key_stats(snapshots, "key_X") is None


class TestAtomicWriteHardening:
    """Story 2.3 code-review P1/P2 — race-free atomic write via ``mkstemp``."""

    def test_concurrent_writes_do_not_tear(self, tmp_path: Path) -> None:
        """Two concurrent writers must each produce a valid final file.

        With the old ``.tmp``-suffix pattern, two writers using the same
        tmp path truncated each other. ``mkstemp`` gives each writer a
        unique tmp, so ``os.replace`` sees a fully-written source and the
        final file is always parseable. Last-writer-wins on the final
        inode, but neither produces torn output.
        """
        from concurrent.futures import ThreadPoolExecutor

        from comadre.counters import _atomic_write

        path = tmp_path / "concurrent.json"
        payload_a = json.dumps({"writer": "a", "n": 1})
        payload_b = json.dumps({"writer": "b", "n": 2})

        with ThreadPoolExecutor(max_workers=2) as pool:
            f1 = pool.submit(_atomic_write, path, payload_a)
            f2 = pool.submit(_atomic_write, path, payload_b)
            f1.result()
            f2.result()

        # The final file is one of the two payloads, never torn JSON.
        data = json.loads(path.read_text(encoding="utf-8"))
        assert data in ({"writer": "a", "n": 1}, {"writer": "b", "n": 2})

    def test_disk_full_cleans_up_tmp(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An OSError mid-write removes the tmp file; no orphan accumulates."""
        import os as os_mod

        from comadre.counters import _atomic_write

        path = tmp_path / "target.json"
        real_replace = os_mod.replace

        def boom(src: str, dst: str) -> None:
            raise OSError("disk full")

        monkeypatch.setattr(os_mod, "replace", boom)
        with pytest.raises(OSError):
            _atomic_write(path, "{}")
        monkeypatch.setattr(os_mod, "replace", real_replace)

        # No leftover tmp siblings.
        assert list(tmp_path.iterdir()) == []


# Keep mypy happy on attribute access for private fields.
_ = Any
