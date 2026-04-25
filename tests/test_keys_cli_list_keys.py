"""End-to-end CLI tests for `comadre-keys list-keys` (Story 1.3)."""

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
) -> str:
    """Run issue-key end-to-end and return the new ``key_...`` id."""
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
        # rowid DESC breaks ties when two keys share the same created_at
        # (issue-key stores seconds precision so same-second calls collide).
        row = conn.execute(
            "SELECT id FROM api_key WHERE customer_id = ? "
            "ORDER BY created_at DESC, rowid DESC LIMIT 1",
            (customer_id,),
        ).fetchone()
    finally:
        conn.close()
    assert row is not None
    return str(row[0])


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
    key_hash: str | None = None,
    key_prefix: str = "RAWKEY00",
) -> str:
    """Seed an api_key row directly for statuses issue-key can't produce."""
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
                None,
                "",
            ),
        )
        conn.commit()
    finally:
        conn.close()
    return key_id


def _count(env: dict[str, str], table: str) -> int:
    conn = sqlite3.connect(env["db_path"])
    try:
        return int(conn.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0])
    finally:
        conn.close()


def _freeze_today(monkeypatch: pytest.MonkeyPatch, today: date) -> None:
    monkeypatch.setattr(keys_cmd, "_resolve_today_in_tz", lambda _tz: today)


class TestFirstRunEmpty:
    """AC7 — first-run hint on empty DB and on customers-but-no-keys DB."""

    def test_empty_db_prints_hint(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["list-keys"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert "No keys issued yet." in stdout
        flat = re.sub(r"\s+", " ", stdout)
        assert "To issue one: comadre-keys issue-key" in flat
        assert "--customer <customer-id>" in flat

    def test_customers_exist_but_no_keys_prints_hint(self, env: dict[str, str]) -> None:
        """AC7 first case: customers registered, zero keys issued → same hint
        as the fully-empty DB. The operator needs the bootstrap nudge
        regardless of whether create-customer has been run."""
        _seed_customer(env)
        result = runner.invoke(app, ["list-keys"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert "No keys issued yet." in stdout
        flat = re.sub(r"\s+", " ", stdout)
        assert "To issue one: comadre-keys issue-key" in flat

    def test_empty_customer_string_rejected(self, env: dict[str, str]) -> None:
        """``--customer ''`` must not fall through as a None-equivalent
        (empty SQL filter + blank title). Reject at usage layer."""
        result = runner.invoke(app, ["list-keys", "--customer", ""])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--customer must not be empty" in stderr


class TestPopulated:
    """AC5 — populated happy path with color-coded status."""

    def _seed_four_statuses(
        self, env: dict[str, str], customer_id: str
    ) -> dict[str, str]:
        # active-manual via issue-key
        active_manual = _issue_key(env, customer_id, price=149.0)
        # active-complimentary via issue-key
        active_comp = _issue_key(env, customer_id, billing_mode="complimentary")
        # suspended-manual + revoked-manual via direct SQL (no command yet)
        suspended = _raw_insert_key(
            env,
            customer_id=customer_id,
            status="suspended",
            paid_until="2026-04-01",
            created_at="2026-04-17T10:00:00Z",
            key_prefix="SUSPENdd",
        )
        revoked = _raw_insert_key(
            env,
            customer_id=customer_id,
            status="revoked",
            paid_until="2026-05-01",
            created_at="2026-04-17T11:00:00Z",
            key_prefix="REVOKEdd",
        )
        return {
            "active_manual": active_manual,
            "active_comp": active_comp,
            "suspended": suspended,
            "revoked": revoked,
        }

    def test_all_statuses_visible(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        self._seed_four_statuses(env, customer_id)
        result = runner.invoke(app, ["list-keys"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        for label in ("active", "suspended", "revoked", "complimentary"):
            assert label in stdout
        assert "4 keys found." in stdout

    def test_notes_column_absent_from_table(self, env: dict[str, str]) -> None:
        """AC23 negative — operator-supplied ``notes`` must NOT render in the
        list-keys table (private operator scratchpad, not a roster column).

        Seed a key with a unique sentinel note, then assert the sentinel is
        absent from rendered stdout. The neighbouring test_all_statuses_visible
        positively asserts every column that DOES render; this is the
        defense-in-depth negative of that contract.
        """
        customer_id = _seed_customer(env)
        sentinel = "ZZNOTESENTINELZZ"
        # Direct SQL because no command sets api_key.notes today; bypassing
        # the CLI is the point of this test (we want to exercise the
        # render path against any future writer that ends up populating the
        # column).
        key_id = _raw_insert_key(env, customer_id=customer_id, key_prefix="WITHNOTE")
        conn = sqlite3.connect(env["db_path"])
        try:
            conn.execute(
                "UPDATE api_key SET notes = ? WHERE id = ?", (sentinel, key_id)
            )
            conn.commit()
        finally:
            conn.close()
        result = runner.invoke(app, ["list-keys"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert sentinel not in stdout, (
            f"notes column leaked into list-keys table: {stdout!r}"
        )


class TestFilterByStatus:
    """AC6 — --status filter + title."""

    @pytest.mark.parametrize(
        "status,expected_count,title",
        [
            ("active", 2, "Active Keys"),
            ("suspended", 1, "Suspended Keys"),
            ("revoked", 1, "Revoked Keys"),
        ],
    )
    def test_filter(
        self,
        env: dict[str, str],
        status: str,
        expected_count: int,
        title: str,
    ) -> None:
        customer_id = _seed_customer(env)
        TestPopulated()._seed_four_statuses(env, customer_id)
        result = runner.invoke(app, ["list-keys", "--status", status])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert title in stdout
        assert f"{expected_count} keys found." in stdout

    def test_invalid_status_rejected(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["list-keys", "--status", "weird"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--status must be active, suspended, or revoked" in stderr


class TestFilterByBillingMode:
    """AC6 — --billing-mode filter + title."""

    @pytest.mark.parametrize(
        "mode,expected_count,title",
        [
            ("manual", 3, "Manual Keys"),
            ("complimentary", 1, "Complimentary Keys"),
        ],
    )
    def test_filter(
        self,
        env: dict[str, str],
        mode: str,
        expected_count: int,
        title: str,
    ) -> None:
        customer_id = _seed_customer(env)
        TestPopulated()._seed_four_statuses(env, customer_id)
        result = runner.invoke(app, ["list-keys", "--billing-mode", mode])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert title in stdout
        assert f"{expected_count} keys found." in stdout

    def test_invalid_billing_mode_rejected(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["list-keys", "--billing-mode", "weird"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--billing-mode must be manual or complimentary" in stderr

    def test_automated_rejected(self, env: dict[str, str]) -> None:
        """--billing-mode automated is reserved for future PSP adapters."""
        result = runner.invoke(app, ["list-keys", "--billing-mode", "automated"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--billing-mode must be manual or complimentary" in stderr


class TestFilterByCustomer:
    """AC6 + AC7 — --customer filter with title lookup + not-found empty."""

    def test_filter_matches(self, env: dict[str, str]) -> None:
        c1 = _seed_customer(env, name="Alpha", email="alpha@a.com")
        c2 = _seed_customer(
            env,
            name="Bravo",
            email="bravo@b.com",
            cpf="111.444.777-35",
        )
        _issue_key(env, c1)
        _issue_key(env, c1)
        _issue_key(env, c2)

        result = runner.invoke(app, ["list-keys", "--customer", c1])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "Keys for Alpha" in stdout
        assert "2 keys found." in stdout

    def test_filter_unknown_customer_empty_not_error(self, env: dict[str, str]) -> None:
        _seed_customer(env)
        missing = "cust_01nonexistent00000000000000"
        result = runner.invoke(app, ["list-keys", "--customer", missing])
        stdout, stderr = _buffers()
        # UX-DR12 — empty is not an error.
        assert result.exit_code == 0
        assert stderr == ""
        assert f"No keys found for customer {missing}." in stdout


class TestFilterByPaidUntilLte:
    """AC6 — --paid-until-lte semantics + today resolver."""

    def _seed_three_paid_until(self, env: dict[str, str], customer_id: str) -> None:
        _raw_insert_key(
            env,
            customer_id=customer_id,
            paid_until=None,
            created_at="2026-04-10T10:00:00Z",
            key_prefix="NULLPAID",
        )
        _raw_insert_key(
            env,
            customer_id=customer_id,
            paid_until="2026-04-01",
            created_at="2026-04-11T10:00:00Z",
            key_prefix="OLDPAID0",
        )
        _raw_insert_key(
            env,
            customer_id=customer_id,
            paid_until="2026-05-01",
            created_at="2026-04-12T10:00:00Z",
            key_prefix="FUTPAID0",
        )

    def test_iso_date_includes_nulls(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        self._seed_three_paid_until(env, customer_id)
        result = runner.invoke(app, ["list-keys", "--paid-until-lte", "2026-04-15"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        # NULL and <=2026-04-15 return; 2026-05-01 excluded.
        assert "2 keys found." in stdout
        assert "NULLPAID" in stdout
        assert "OLDPAID0" in stdout
        assert "FUTPAID0" not in stdout

    def test_today_resolver(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 15))
        customer_id = _seed_customer(env)
        self._seed_three_paid_until(env, customer_id)
        result = runner.invoke(app, ["list-keys", "--paid-until-lte", "today"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "2 keys found." in stdout

    def test_invalid_format(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["list-keys", "--paid-until-lte", "17-04-2026"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 2
        assert "--paid-until-lte must be an ISO date (YYYY-MM-DD) or 'today'" in stderr

    def test_whitespace_is_stripped(self, env: dict[str, str]) -> None:
        """Copy-pasted ISO values with surrounding whitespace must not reject."""
        customer_id = _seed_customer(env)
        self._seed_three_paid_until(env, customer_id)
        result = runner.invoke(app, ["list-keys", "--paid-until-lte", "  2026-04-15  "])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "2 keys found." in stdout

    def test_non_dashed_iso_normalized(self, env: dict[str, str]) -> None:
        """date.fromisoformat accepts '20260415'; normalization must rewrite
        it to 'YYYY-MM-DD' before SQL binding, otherwise the lexicographic
        compare against 'YYYY-MM-DD' storage rows is wrong."""
        customer_id = _seed_customer(env)
        self._seed_three_paid_until(env, customer_id)
        result = runner.invoke(app, ["list-keys", "--paid-until-lte", "20260415"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "2 keys found." in stdout

    def test_title_only_paid_until_lte(self, env: dict[str, str]) -> None:
        """AC6 title precedence — when only --paid-until-lte is set (and no
        customer/billing/status filter matches), the table title shows
        'Keys (paid until ≤ <date>)'."""
        customer_id = _seed_customer(env)
        self._seed_three_paid_until(env, customer_id)
        result = runner.invoke(app, ["list-keys", "--paid-until-lte", "2026-04-15"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "Keys (paid until \u2264 2026-04-15)" in stdout


class TestFilterComposition:
    """AC6 — Journey 2 canonical query."""

    def test_status_billing_paid_until_today(
        self,
        env: dict[str, str],
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        _freeze_today(monkeypatch, date(2026, 4, 15))
        customer_id = _seed_customer(env)
        # Match: active + manual + paid_until null
        _issue_key(env, customer_id, price=149.0)
        # Non-match: active + complimentary
        _issue_key(env, customer_id, billing_mode="complimentary")
        # Non-match: suspended + manual
        _raw_insert_key(
            env,
            customer_id=customer_id,
            status="suspended",
            billing_mode="manual",
            paid_until="2026-04-01",
            created_at="2026-04-17T10:00:00Z",
            key_prefix="SUSPENdd",
        )
        # Non-match: active + manual + paid_until in future
        _raw_insert_key(
            env,
            customer_id=customer_id,
            status="active",
            billing_mode="manual",
            paid_until="2026-05-01",
            created_at="2026-04-17T11:00:00Z",
            key_prefix="FUTUREpd",
        )

        result = runner.invoke(
            app,
            [
                "list-keys",
                "--status",
                "active",
                "--billing-mode",
                "manual",
                "--paid-until-lte",
                "today",
            ],
        )
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "1 keys found." in stdout
        # --customer precedence wins over --billing-mode; here no --customer,
        # so title is "Manual Keys" (billing-mode beats status per AC6).
        assert "Manual Keys" in stdout


class TestSubsequentEmpty:
    """AC7 — non-first-run empty is a one-liner, no hint."""

    def test_status_filter_empty(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        _issue_key(env, customer_id)
        result = runner.invoke(app, ["list-keys", "--status", "suspended"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert "No suspended keys found." in stdout
        # UX-DR13 — no hint on subsequent empty.
        assert "To issue one:" not in stdout


class TestFormatJson:
    """AC8 — machine-readable output."""

    def test_populated_shape(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        _issue_key(env, customer_id, price=149.0)
        _issue_key(env, customer_id, billing_mode="complimentary")
        _raw_insert_key(
            env,
            customer_id=customer_id,
            status="suspended",
            created_at="2026-04-17T10:00:00Z",
        )

        result = runner.invoke(app, ["list-keys", "--format", "json"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        data = json.loads(stdout)
        assert len(data) == 3
        for entry in data:
            assert set(entry.keys()) == {
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
                "notes",
            }
            assert "key_hash" not in entry
            # Numeric fields emit as numbers.
            assert isinstance(entry["price_monthly"], (int, float))
            assert isinstance(entry["rate_limit_rpm"], int)
            assert isinstance(entry["notes"], str)

    def test_with_filter(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        _issue_key(env, customer_id)
        _raw_insert_key(
            env,
            customer_id=customer_id,
            status="suspended",
            created_at="2026-04-17T10:00:00Z",
        )
        result = runner.invoke(
            app, ["list-keys", "--status", "suspended", "--format", "json"]
        )
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        data = json.loads(stdout)
        assert len(data) == 1
        assert data[0]["status"] == "suspended"

    def test_empty_is_empty_array(self, env: dict[str, str]) -> None:
        result = runner.invoke(app, ["list-keys", "--format", "json"])
        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        assert json.loads(stdout) == []
        # No hint text in JSON mode.
        assert "To issue one" not in stdout


class TestNoColor:
    """AC10 — NO_COLOR strips ANSI but keeps labels."""

    def test_no_ansi_escapes(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("NO_COLOR", "1")
        buf = StringIO()
        output_mod._stdout_console = Console(file=buf, force_terminal=False, width=120)
        customer_id = _seed_customer(env)
        _issue_key(env, customer_id)
        _clear_buffers()
        result = runner.invoke(app, ["list-keys"])
        stdout = output_mod._stdout_console.file.getvalue()  # type: ignore[union-attr]
        assert result.exit_code == 0
        assert "\x1b[" not in stdout
        # Labels still readable without color.
        assert "active" in stdout


class TestHelpSurface:
    """AC10 — realistic examples in --help."""

    def test_help_lists_realistic_examples(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KEY_REGISTRY_DB_PATH", raising=False)
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)
        result = runner.invoke(app, ["list-keys", "--help"])
        assert result.exit_code == 0
        # Typer wraps long help lines inside a rich Panel. To make assertions
        # portable across terminal widths we: (1) strip ANSI escapes, (2) drop
        # the Panel border glyphs (│ ╭ ╮ ╰ ╯ ─), (3) collapse whitespace runs.
        ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        cleaned = ansi.sub("", result.stdout)
        for glyph in ("\u2502", "\u256d", "\u256e", "\u2570", "\u256f", "\u2500"):
            cleaned = cleaned.replace(glyph, " ")
        flat = re.sub(r"\s+", " ", cleaned)
        assert "--status suspended" in flat
        assert "--billing-mode complimentary" in flat
        assert "cust_01j" in flat
        assert "--paid-until-lte today" in flat
        assert "--format json" in flat
        assert not (tmp_path / "registry.db").exists()


class TestReadOnly:
    """AC9 — list commands never mutate the DB."""

    def test_no_writes(self, env: dict[str, str]) -> None:
        customer_id = _seed_customer(env)
        _issue_key(env, customer_id)
        _raw_insert_key(
            env,
            customer_id=customer_id,
            status="suspended",
            created_at="2026-04-17T10:00:00Z",
        )
        before = {
            "customer": _count(env, "customer"),
            "api_key": _count(env, "api_key"),
            "audit_log": _count(env, "audit_log"),
        }
        for args in (
            ["list-keys"],
            ["list-keys", "--status", "active"],
            ["list-keys", "--billing-mode", "manual"],
            ["list-keys", "--customer", customer_id],
            ["list-keys", "--paid-until-lte", "2026-05-01"],
            ["list-keys", "--format", "json"],
        ):
            result = runner.invoke(app, args)
            assert result.exit_code == 0
            _clear_buffers()
        after = {
            "customer": _count(env, "customer"),
            "api_key": _count(env, "api_key"),
            "audit_log": _count(env, "audit_log"),
        }
        assert before == after


class TestLogSanitization:
    """AC10 — logs carry count/flags only, not names/emails.

    The project's ``get_logger`` sets ``propagate=False`` so the standard
    ``caplog`` fixture (which hangs off the root logger) misses these
    records. Instead we attach a MemoryHandler directly to the
    ``keys.cli`` logger for the test.
    """

    def test_log_has_count_not_names(
        self,
        env: dict[str, str],
    ) -> None:
        from comadre.logging import get_logger

        customer_id = _seed_customer(env, name="Helena Ribeiro")
        _issue_key(env, customer_id)
        _clear_buffers()

        logger = get_logger("keys.cli")
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture(level=logging.INFO)
        logger.addHandler(handler)
        try:
            result = runner.invoke(app, ["list-keys"])
        finally:
            logger.removeHandler(handler)
        assert result.exit_code == 0
        list_records = [r for r in records if "Listed keys" in r.getMessage()]
        assert list_records, "Expected a 'Listed keys' INFO record"
        joined = "\n".join(r.getMessage() for r in list_records)
        assert "Listed keys | count=" in joined
        # No name / email in structured log output.
        assert "Helena" not in joined
        assert "helena@clinica.com" not in joined
