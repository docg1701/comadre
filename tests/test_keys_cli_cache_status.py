"""End-to-end CLI tests for `comadre-keys cache-status` (Story 2.3)."""

from __future__ import annotations

import json
from datetime import UTC, datetime, timedelta
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

from comadre.keys.cli.app import app

# F41 — autouse fixtures (`_clear_settings_cache`,
# `_reset_cli_consoles_to_buffers`) now live in tests/conftest.py
# and apply to every test. Helpers (``_buffers`` / ``_clear_buffers``)
# live in tests/_keys_cli_helpers.py.
from tests._keys_cli_helpers import buffers as _buffers

runner = CliRunner()


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
    per_key: dict[str, dict[str, Any]] | None = None,
    auth_cache: dict[str, Any] | None = None,
    process_uptime_seconds: int = 3712,
    replica: str = "test-replica",
) -> Path:
    """Write a counters snapshot that the CLI will read.

    Per-replica filename — the CLI globs ``{db_path}.counters.*.json``, so
    the tests pick a deterministic replica slug rather than the machine
    hostname to stay hermetic across environments.
    """
    written = datetime.now(UTC) - timedelta(seconds=age_seconds)
    snapshot_path = Path(f"{db_path}.counters.{replica}.json")
    payload = {
        "schema_version": 1,
        "written_at": written.strftime("%Y-%m-%dT%H:%M:%S.")
        + f"{written.microsecond // 1000:03d}Z",
        "process_uptime_seconds": process_uptime_seconds,
        "auth_cache": auth_cache
        or {
            "entries": 17,
            "maxsize": 4096,
            "ttl_seconds": 60,
            "hits": 1842,
            "misses": 23,
        },
        "per_key": per_key or {},
    }
    snapshot_path.write_text(json.dumps(payload), encoding="utf-8")
    return snapshot_path


class TestUsageAndConfig:
    """AC9 delivers a consistent exit surface with sibling commands."""

    def test_invalid_format_exits_2(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["cache-status", "--format", "xml"])
        assert result.exit_code == 2
        _, stderr = _buffers()
        assert "--format must be table or json" in stderr

    def test_missing_encryption_key_exits_6(
        self, monkeypatch: pytest.MonkeyPatch, tmp_path: Path
    ) -> None:
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))
        result = runner.invoke(app, ["cache-status"])
        assert result.exit_code == 6
        _, stderr = _buffers()
        assert "KEY_REGISTRY_ENCRYPTION_KEY" in stderr

    def test_bad_timezone_exits_6(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("BILLING_TIMEZONE", "Mars/Olympus_Mons")
        result = runner.invoke(app, ["cache-status"])
        assert result.exit_code == 6
        _, stderr = _buffers()
        assert "BILLING_TIMEZONE" in stderr


class TestBoundMessage:
    """AC9 — the verbatim propagation bound string appears on every reachable state."""

    _verbatim = (
        "Auth cache propagation bound: 60 seconds. "
        "Key-state changes become visible to the API within this window. "
        "This command does not force invalidation; to empty the cache "
        "faster, restart the affected replica(s)."
    )

    def test_bound_message_on_absent_snapshot(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["cache-status"])
        assert result.exit_code == 0
        stdout, _ = _buffers()
        stdout_flat = " ".join(stdout.split())
        assert self._verbatim in stdout_flat
        assert "Cache health: unavailable" in stdout

    def test_bound_message_on_fresh_snapshot(self, env: dict[str, str]) -> None:
        _write_snapshot(env["db_path"], age_seconds=3)
        result = runner.invoke(app, ["cache-status"])
        assert result.exit_code == 0
        stdout, _ = _buffers()
        stdout_flat = " ".join(stdout.split())
        assert self._verbatim in stdout_flat

    def test_bound_message_on_stale_snapshot(self, env: dict[str, str]) -> None:
        _write_snapshot(env["db_path"], age_seconds=120)
        result = runner.invoke(app, ["cache-status"])
        assert result.exit_code == 0
        stdout, _ = _buffers()
        stdout_flat = " ".join(stdout.split())
        assert self._verbatim in stdout_flat


class TestTableOutput:
    """AC8 — fresh snapshot renders the telemetry block."""

    def test_fresh_snapshot_includes_entries_and_hit_rate(
        self, env: dict[str, str]
    ) -> None:
        _write_snapshot(
            env["db_path"],
            age_seconds=3,
            auth_cache={
                "entries": 17,
                "maxsize": 4096,
                "ttl_seconds": 60,
                "hits": 1842,
                "misses": 23,
            },
        )
        result = runner.invoke(app, ["cache-status"])
        assert result.exit_code == 0
        stdout, _ = _buffers()
        assert "snapshot written 3s ago" in stdout
        # Multi-replica rendering surfaces entries + maxsize/replica.
        assert "Replicas:  1" in stdout
        assert "17" in stdout
        assert "4096" in stdout
        assert "98.8%" in stdout
        # 1842 / (1842 + 23) = 0.9876... → renders as 98.8%

    def test_stale_snapshot_renders_with_age_label(self, env: dict[str, str]) -> None:
        """Stale data is shown honestly with a freshness label, not hidden."""
        _write_snapshot(env["db_path"], age_seconds=120)
        result = runner.invoke(app, ["cache-status"])
        assert result.exit_code == 0
        stdout, _ = _buffers()
        # Age renders as "2m ago" (120s / 60 = 2 minutes).
        assert "2m ago" in stdout
        # Data is visible — not hidden behind an "unavailable" cutoff.
        assert "Cache health" in stdout
        assert "unavailable" not in stdout

    def test_multiple_replicas_aggregate_hits_and_entries(
        self, env: dict[str, str]
    ) -> None:
        """Two replica snapshots → summed hits/entries; min uptime reported."""
        _write_snapshot(
            env["db_path"],
            replica="alpha",
            auth_cache={"entries": 10, "maxsize": 4096, "hits": 100, "misses": 5},
            process_uptime_seconds=60,
            age_seconds=3,
        )
        _write_snapshot(
            env["db_path"],
            replica="beta",
            auth_cache={"entries": 7, "maxsize": 4096, "hits": 50, "misses": 2},
            process_uptime_seconds=30,
            age_seconds=5,
        )
        result = runner.invoke(app, ["cache-status"])
        assert result.exit_code == 0
        stdout, _ = _buffers()
        assert "Replicas:  2" in stdout
        # Summed entries = 17; hits = 150.
        assert "17" in stdout
        assert "150 hits / 157 lookups" in stdout


class TestJsonOutput:
    """AC10 — JSON payload always carries ttl_seconds + propagation_bound_message."""

    def test_json_always_contains_ttl_seconds(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["cache-status", "--format", "json"])
        assert result.exit_code == 0
        stdout, _ = _buffers()
        payload = json.loads(stdout)
        assert payload["ttl_seconds"] == 60
        assert "propagation_bound_message" in payload

    def test_json_with_fresh_snapshot_has_telemetry_fields(
        self, env: dict[str, str]
    ) -> None:
        _write_snapshot(env["db_path"], age_seconds=3)
        result = runner.invoke(app, ["cache-status", "--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(_buffers()[0])
        assert payload["snapshot_available"] is True
        assert payload["replicas"] == 1
        assert payload["entries"] == 17
        assert payload["maxsize_per_replica"] == 4096
        assert payload["hits"] == 1842
        assert payload["misses"] == 23
        assert abs(payload["hit_rate"] - (1842 / (1842 + 23))) < 1e-6

    def test_json_without_snapshot_omits_telemetry(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["cache-status", "--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(_buffers()[0])
        assert payload["snapshot_available"] is False
        assert "entries" not in payload
        assert "hit_rate" not in payload

    def test_json_aggregates_across_replicas(self, env: dict[str, str]) -> None:
        _write_snapshot(
            env["db_path"],
            replica="alpha",
            auth_cache={"entries": 10, "maxsize": 4096, "hits": 100, "misses": 5},
        )
        _write_snapshot(
            env["db_path"],
            replica="beta",
            auth_cache={"entries": 7, "maxsize": 4096, "hits": 50, "misses": 2},
        )
        result = runner.invoke(app, ["cache-status", "--format", "json"])
        assert result.exit_code == 0
        payload = json.loads(_buffers()[0])
        assert payload["replicas"] == 2
        assert payload["entries"] == 17
        assert payload["hits"] == 150
        assert payload["misses"] == 7


class TestReadOnly:
    """AC11 — cache-status mutates nothing."""

    def test_no_registry_db_created(self, env: dict[str, str]) -> None:
        before = Path(env["db_path"]).exists()
        runner.invoke(app, ["cache-status"])
        assert Path(env["db_path"]).exists() is before

    def test_snapshot_mtime_unchanged(self, env: dict[str, str]) -> None:
        snapshot_path = _write_snapshot(env["db_path"], age_seconds=3)
        before_ns = snapshot_path.stat().st_mtime_ns
        runner.invoke(app, ["cache-status"])
        after_ns = snapshot_path.stat().st_mtime_ns
        assert before_ns == after_ns

    def test_invalidate_sentinel_untouched(
        self, env: dict[str, str], tmp_path: Path
    ) -> None:
        sentinel = Path(env["db_path"] + ".invalidate")
        sentinel.write_text("", encoding="utf-8")
        before_ns = sentinel.stat().st_mtime_ns
        runner.invoke(app, ["cache-status"])
        after_ns = sentinel.stat().st_mtime_ns
        assert before_ns == after_ns


class TestMalformedSnapshot:
    """Malformed JSON degrades to the bound-only output (no crash)."""

    def test_malformed_json_degrades_to_unavailable(self, env: dict[str, str]) -> None:
        snapshot_path = Path(env["db_path"] + ".counters.test-replica.json")
        snapshot_path.write_text("{this is not JSON", encoding="utf-8")
        result = runner.invoke(app, ["cache-status"])
        assert result.exit_code == 0
        stdout, _ = _buffers()
        assert "unavailable" in stdout
        # No exception surfaced — the command exited cleanly. The warning
        # is emitted via comadre.logging (propagate=False) so caplog can't
        # observe it without fixture gymnastics; the exit-0 + degraded
        # output is sufficient evidence of the graceful-degrade path.


class TestSchemaWeirdSnapshot:
    """Snapshots that parse but miss auth_cache fields degrade to zeros.

    The aggregator treats a parseable snapshot with missing/weird
    ``auth_cache`` as a replica reporting with zero telemetry — still a
    contribution, just an empty one. The table renders honestly rather
    than collapsing the whole surface to "unavailable".
    """

    def test_missing_auth_cache_dict_renders_zeros(self, env: dict[str, str]) -> None:
        snapshot_path = Path(env["db_path"] + ".counters.weird.json")
        # Valid JSON but ``auth_cache`` is not a dict — aggregator skips
        # its telemetry fields (falls to 0s) but still counts it as a
        # replica reporting.
        snapshot_path.write_text(
            json.dumps(
                {
                    "schema_version": 1,
                    "written_at": datetime.now(UTC).strftime("%Y-%m-%dT%H:%M:%S.000Z"),
                    "process_uptime_seconds": 5,
                    "auth_cache": "not-a-dict",
                    "per_key": {},
                }
            ),
            encoding="utf-8",
        )
        result = runner.invoke(app, ["cache-status"])
        assert result.exit_code == 0
        stdout, _ = _buffers()
        # Replica reports with empty telemetry — shown as Replicas: 1.
        assert "Replicas:  1" in stdout
        assert "unavailable" not in stdout


class TestHelpSurface:
    """AC18 — cache-status is reachable as a flat comadre-keys subcommand."""

    def test_top_level_help_lists_cache_status(self) -> None:
        result = runner.invoke(app, ["--help"])
        assert result.exit_code == 0
        assert "cache-status" in result.stdout

    def test_cache_status_help_exits_zero(self) -> None:
        result = runner.invoke(app, ["cache-status", "--help"])
        assert result.exit_code == 0
        assert "cache-status" in result.stdout
