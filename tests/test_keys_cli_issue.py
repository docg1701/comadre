"""End-to-end CLI tests for `comadre-keys issue-key`.

Covers Story 1.2 acceptance criteria via Typer's CliRunner. Kept separate
from `test_keys_cli.py` (Story 1.1's create-customer tests) to keep diffs
clean for reviewers.
"""

from __future__ import annotations

import json
import re
import sqlite3
from datetime import date
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from typer.testing import CliRunner

import comadre.keys.cli.commands.keys as keys_cmd
import comadre.keys.cli.output as output_mod
from comadre.keys.cli import _clock
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


def _seed_customer(env: dict[str, str]) -> str:
    """Run create-customer end-to-end and return the new `cust_...` id."""
    result = runner.invoke(
        app,
        [
            "create-customer",
            "--name",
            "Helena Ribeiro",
            "--email",
            "helena@clinica.com",
            "--cpf",
            "123.456.789-09",
        ],
    )
    assert result.exit_code == 0, result.output
    stdout, _stderr = _buffers()
    match = re.search(r"cust_[0-9a-z]{26}", stdout)
    assert match is not None, f"Failed to find customer id in stdout: {stdout!r}"
    # Reset the stdout buffer so subsequent commands start with a clean slate.
    output_mod._stdout_console.file.seek(0)  # type: ignore[union-attr]
    output_mod._stdout_console.file.truncate()  # type: ignore[union-attr]
    return match.group(0)


def _freeze_today(monkeypatch: pytest.MonkeyPatch, today: date) -> None:
    monkeypatch.setattr(_clock, "resolve_today_in_tz", lambda _tz: today)


class TestIssueKeyManualHappyPath:
    """AC1 + AC8."""

    def test_manual_happy_path(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 13))
        customer_id = _seed_customer(env)

        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--price",
                "149",
            ],
        )
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert stderr == ""
        # Plaintext key present in stdout (AC1).
        match = re.search(r"cmdr_live_[A-Za-z0-9_-]{43}", stdout)
        assert match is not None, stdout
        plaintext = match.group(0)
        # Labeled rows. pt-BR number format (R$ 149,00).
        assert "rate limit:   60/min" in stdout
        assert "billing mode: manual" in stdout
        assert "price:        R$ 149,00/month" in stdout
        assert "first charge: 2026-05-05 (22 days free until then)" in stdout
        assert "copy now" in stdout

        # DB assertions.
        conn = sqlite3.connect(env["db_path"])
        conn.row_factory = sqlite3.Row
        try:
            keys = conn.execute("SELECT * FROM api_key").fetchall()
            assert len(keys) == 1
            row = keys[0]
            assert row["customer_id"] == customer_id
            assert re.fullmatch(r"[0-9a-f]{64}", row["key_hash"])
            assert len(row["key_prefix"]) == 8
            assert row["rate_limit_rpm"] == 60
            assert row["status"] == "active"
            assert row["billing_mode"] == "manual"
            assert row["price_monthly"] == 149.0
            assert row["paid_until"] is None
            assert re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", row["created_at"]
            )
            assert row["last_used_at"] is None
            assert row["notes"] == ""
            assert row["id"].startswith("key_")

            # AC8 audit row.
            audits = conn.execute(
                "SELECT * FROM audit_log WHERE action = 'issue_key'"
            ).fetchall()
            assert len(audits) == 1
            audit = audits[0]
            assert audit["target_type"] == "api_key"
            assert audit["target_id"] == row["id"]
            details = json.loads(audit["details_json"])
            assert details == {"billing_mode": "manual", "rate_limit_rpm": 60}
            assert re.fullmatch(r"cli:\S+", audit["actor"])
            assert re.fullmatch(
                r"\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z", audit["occurred_at"]
            )
        finally:
            conn.close()

        # Plaintext appears exactly once (AC1/AC4 reinforcement).
        assert stdout.count(plaintext) == 1

        # Plaintext NOT in stderr.
        assert plaintext not in stderr


class TestIssueKeyComplimentary:
    """AC2."""

    def test_complimentary_happy_path(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 13))
        customer_id = _seed_customer(env)

        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "120",
                "--billing-mode",
                "complimentary",
                "--notes",
                "included in infra bundle",
            ],
        )
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        # pt-BR number format: comma decimal separator.
        assert "R$ 0,00 (bundled externally)" in stdout
        assert "\u2014 (not applicable)" in stdout  # em-dash
        assert "first charge:" not in stdout
        assert "billing mode: complimentary" in stdout

        conn = sqlite3.connect(env["db_path"])
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT * FROM api_key").fetchone()
            assert row["billing_mode"] == "complimentary"
            assert row["price_monthly"] == 0.0
            assert row["rate_limit_rpm"] == 120
            assert row["notes"] == "included in infra bundle"
            audit = conn.execute(
                "SELECT details_json FROM audit_log WHERE action='issue_key'"
            ).fetchone()
            details = json.loads(audit["details_json"])
            assert details == {"billing_mode": "complimentary", "rate_limit_rpm": 120}
            # AC2: operator `notes` must NOT leak into audit details.
            assert "notes" not in details
            assert "included" not in audit["details_json"]
        finally:
            conn.close()

    def test_complimentary_rejects_price(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        # Baseline audit count: create-customer already wrote one row.
        conn = sqlite3.connect(env["db_path"])
        try:
            before_audit = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        finally:
            conn.close()
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--billing-mode",
                "complimentary",
                "--price",
                "149",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--price is not applicable to complimentary keys" in stderr
        # Verbatim hint (both halves must be present, not just one).
        assert "omit --price" in stderr
        assert "--billing-mode to manual" in stderr

        conn = sqlite3.connect(env["db_path"])
        try:
            count = conn.execute("SELECT COUNT(*) FROM api_key").fetchone()[0]
            assert count == 0
            # No new audit row written either (rejection is pre-DB).
            after_audit = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
            assert after_audit == before_audit
        finally:
            conn.close()

    def test_manual_requires_price(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--price is required for manual billing mode" in stderr

    def test_manual_rejects_zero_price(self, env: dict[str, str]) -> None:
        """Zero-cost customers must route through complimentary mode."""
        customer_id = _seed_customer(env)
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--price",
                "0",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--price must be positive for manual billing mode" in stderr
        assert "complimentary" in stderr
        # No DB row / no audit row beyond the customer seed.
        conn = sqlite3.connect(env["db_path"])
        try:
            assert conn.execute("SELECT COUNT(*) FROM api_key").fetchone()[0] == 0
        finally:
            conn.close()

    def test_manual_rejects_negative_price(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--price",
                "-10",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--price must be positive for manual billing mode" in stderr

    def test_manual_rejects_non_finite_price(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--price",
                "inf",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--price must be a finite number" in stderr


class TestIssueKeyUsageErrors:
    def test_rejects_invalid_billing_mode(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--billing-mode",
                "weird",
                "--price",
                "149",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--billing-mode must be manual or complimentary" in stderr

    def test_rejects_nonpositive_rpm_zero(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "0",
                "--price",
                "149",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--rpm must be between 1 and 10000" in stderr

    def test_rejects_nonpositive_rpm_negative(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "-1",
                "--price",
                "149",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--rpm must be between 1 and 10000" in stderr

    def test_rpm_above_cap_rejected_usage_error(self, env: dict[str, str]) -> None:
        """Story 2.2 — mirror update-key's 1..10_000 cap on issue-key."""
        customer_id = _seed_customer(env)
        conn = sqlite3.connect(env["db_path"])
        try:
            before = conn.execute("SELECT COUNT(*) FROM api_key").fetchone()[0]
        finally:
            conn.close()
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "10001",
                "--price",
                "149",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "Usage error: --rpm must be between 1 and 10000" in stderr
        assert "Provide --rpm in the range 1..10000" in stderr
        conn = sqlite3.connect(env["db_path"])
        try:
            after = conn.execute("SELECT COUNT(*) FROM api_key").fetchone()[0]
        finally:
            conn.close()
        assert after == before == 0

    def test_rpm_at_cap_accepted(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """Boundary: --rpm 10000 is inclusive (AC13)."""
        _freeze_today(monkeypatch, date(2026, 4, 13))
        customer_id = _seed_customer(env)
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "10000",
                "--price",
                "999",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        conn = sqlite3.connect(env["db_path"])
        conn.row_factory = sqlite3.Row
        try:
            row = conn.execute("SELECT rate_limit_rpm FROM api_key").fetchone()
            assert row["rate_limit_rpm"] == 10000
        finally:
            conn.close()


class TestCustomerNotFound:
    """AC3."""

    def test_customer_not_found(self, env: dict[str, str]) -> None:
        # Seed a different customer so the DB + audit_log exist.
        _seed_customer(env)
        # Count rows before.
        conn = sqlite3.connect(env["db_path"])
        try:
            before_keys = conn.execute("SELECT COUNT(*) FROM api_key").fetchone()[0]
            before_audit = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        finally:
            conn.close()

        missing_id = "cust_01jnoexistence000000000000"  # 26-char valid shape
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                missing_id,
                "--rpm",
                "60",
                "--price",
                "149",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert f"Customer not found: {missing_id}" in stderr
        assert "list-customers" in stderr

        conn = sqlite3.connect(env["db_path"])
        try:
            after_keys = conn.execute("SELECT COUNT(*) FROM api_key").fetchone()[0]
            after_audit = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        finally:
            conn.close()
        assert after_keys == before_keys == 0
        assert after_audit == before_audit

    def test_tombstone_treated_as_missing(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        # Tombstone the seeded customer.
        conn = sqlite3.connect(env["db_path"])
        try:
            conn.execute(
                "UPDATE customer SET deleted_at = ? WHERE id = ?",
                ("2026-04-17T00:00:00Z", customer_id),
            )
            conn.commit()
        finally:
            conn.close()

        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--price",
                "149",
            ],
        )
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Customer not found" in stderr


class TestPlaintextDisciplineAndCopyFidelity:
    """AC1 + AC4 regression guards."""

    def test_plaintext_appears_only_in_panel(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 13))
        customer_id = _seed_customer(env)
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--price",
                "149",
            ],
        )
        stdout, stderr = _buffers()
        assert result.exit_code == 0
        match = re.search(r"cmdr_live_[A-Za-z0-9_-]{43}", stdout)
        assert match is not None
        plaintext = match.group(0)
        assert stdout.count(plaintext) == 1
        assert plaintext not in stderr
        # The CliRunner's captured stream should also not leak it via print().
        assert plaintext not in result.stdout

    def test_plaintext_line_has_no_leading_indent(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """AC4 automated surrogate."""
        _freeze_today(monkeypatch, date(2026, 4, 13))
        customer_id = _seed_customer(env)
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--price",
                "149",
            ],
        )
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        plaintext_line = next(
            line
            for line in stdout.split("\n")
            if re.search(r"cmdr_live_[A-Za-z0-9_-]{43}", line)
        )
        match = re.search(r"cmdr_live_[A-Za-z0-9_-]{43}", plaintext_line)
        assert match is not None, plaintext_line
        plaintext = match.group(0)
        assert plaintext_line.strip() == plaintext
        assert plaintext_line[0] not in (" ", "\t", "\u00a0")


class TestFirstChargeCalculation:
    """AC5."""

    def test_first_charge_is_next_billing_day(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 13))
        customer_id = _seed_customer(env)
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--price",
                "149",
            ],
        )
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "first charge: 2026-05-05 (22 days free until then)" in stdout

    def test_first_charge_same_day_rolls_to_next_month(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 5, 5))
        customer_id = _seed_customer(env)
        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--price",
                "149",
            ],
        )
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "first charge: 2026-06-05" in stdout


class TestHelpSurface:
    """AC9."""

    def test_issue_key_help_lists_realistic_examples(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # No DB/settings touch for --help.
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KEY_REGISTRY_DB_PATH", raising=False)
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        result = runner.invoke(app, ["issue-key", "--help"])
        assert result.exit_code == 0
        # Normalize: strip ANSI escape sequences and collapse whitespace runs
        # to a single space. Typer renders the help inside a rich Panel whose
        # line-wrapping depends on terminal width (80 on CI, wider locally),
        # and line-wraps can split an example like "--price 149" across two
        # lines. Normalizing both dimensions makes the assertion portable.
        ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        help_text = re.sub(r"\s+", " ", ansi.sub("", result.stdout))
        assert "cust_01j" in help_text
        assert "Example: --rpm 60" in help_text
        assert "--price 149" in help_text
        # English example (project language policy: code/help text in English).
        assert "bundled into infra package" in help_text
        # DB file never created.
        assert not (tmp_path / "registry.db").exists()


class TestAuditRollbackOnFailure:
    """AC8."""

    def test_audit_rollback_on_failure(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 13))
        customer_id = _seed_customer(env)

        # Count baseline audit rows (create_customer left one).
        conn = sqlite3.connect(env["db_path"])
        try:
            before_audit = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        finally:
            conn.close()

        import comadre.keys.audit as audit_mod

        def _boom(*_args: object, **_kw: object) -> None:
            raise ValueError("forced audit blocklist hit")

        monkeypatch.setattr(audit_mod, "log_event", _boom)

        result = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--price",
                "149",
            ],
        )
        _stdout, stderr = _buffers()
        conn = sqlite3.connect(env["db_path"])
        try:
            keys_count = conn.execute("SELECT COUNT(*) FROM api_key").fetchone()[0]
            audit_count = conn.execute("SELECT COUNT(*) FROM audit_log").fetchone()[0]
        finally:
            conn.close()
        # Rollback invariant: neither api_key nor audit_log gains a row.
        assert keys_count == 0
        assert audit_count == before_audit
        # UX-DR10: audit failures map to exit code 5 with a structured error.
        assert result.exit_code == 5
        assert "Audit error" in stderr
        assert "forced audit blocklist hit" in stderr


class TestHashCollision:
    """AC6."""

    def test_hash_collision_returns_db_error(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 13))
        customer_id = _seed_customer(env)

        # Force the same plaintext every call — the second issue-key will
        # collide on the UNIQUE key_hash index.
        fixed = "cmdr_live_" + "a" * 43
        monkeypatch.setattr(keys_cmd, "generate_api_key_plaintext", lambda: fixed)

        first = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--price",
                "149",
            ],
        )
        assert first.exit_code == 0

        # Clear buffers between invocations so assertions only see the 2nd call.
        output_mod._stdout_console.file.seek(0)  # type: ignore[union-attr]
        output_mod._stdout_console.file.truncate()  # type: ignore[union-attr]
        output_mod._stderr_console.file.seek(0)  # type: ignore[union-attr]
        output_mod._stderr_console.file.truncate()  # type: ignore[union-attr]

        second = runner.invoke(
            app,
            [
                "issue-key",
                "--customer",
                customer_id,
                "--rpm",
                "60",
                "--price",
                "149",
            ],
        )
        _stdout, stderr = _buffers()
        assert second.exit_code == 5
        assert "key hash collision" in stderr
