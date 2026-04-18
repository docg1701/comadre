"""End-to-end CLI tests for ``comadre-keys rotate-key`` (Story 1.6)."""

from __future__ import annotations

import json
import logging
import re
import sqlite3
from collections.abc import Iterator
from datetime import UTC, datetime
from io import StringIO
from pathlib import Path

import pytest
from cryptography.fernet import Fernet
from rich.console import Console
from typer.testing import CliRunner

import comadre.keys.cli.output as output_mod
from comadre.config import get_settings
from comadre.keys.cli.app import app
from comadre.keys.db import (
    _apply_migrations,
    generate_customer_id,
    generate_key_id,
    get_connection,
    insert_api_key,
    insert_customer,
)
from comadre.keys.models import ApiKeyRecord, CustomerRecord
from comadre.keys.tokens import hash_api_key

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
    monkeypatch.setenv("API_KEY", "test-api-key")
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


def _seed_customer_and_key(
    db_path: str,
    *,
    billing_mode: str = "manual",
    rate_limit_rpm: int = 60,
    price_monthly: float = 149.0,
    status: str = "active",
    paid_until: str | None = None,
    notes: str = "",
    key_hash: str = "a" * 64,
    key_prefix: str = "Pq_abc12",
) -> tuple[str, str]:
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        cid = generate_customer_id()
        insert_customer(
            conn,
            CustomerRecord(
                id=cid,
                name="Helena Ribeiro",
                email="helena@clinica.com",
                tax_id_kind="cpf",
                tax_id_encrypted=b"gAAAAA-ciphertext",
                notes="",
                registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                deleted_at=None,
            ),
            actor="cli:tester",
        )
        kid = generate_key_id()
        insert_api_key(
            conn,
            ApiKeyRecord(
                id=kid,
                customer_id=cid,
                key_hash=key_hash,
                key_prefix=key_prefix,
                rate_limit_rpm=rate_limit_rpm,
                status=status,  # type: ignore[arg-type]
                billing_mode=billing_mode,  # type: ignore[arg-type]
                price_monthly=price_monthly,
                paid_until=paid_until,
                created_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                last_used_at=None,
                notes=notes,
            ),
            actor="cli:tester",
        )
        return cid, kid
    finally:
        conn.close()


def _fetch_api_key(db_path: str, kid: str) -> dict[str, object]:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT id, customer_id, key_hash, key_prefix, rate_limit_rpm, "
            "status, billing_mode, price_monthly, paid_until, created_at, "
            "last_used_at, notes FROM api_key WHERE id = ?",
            (kid,),
        ).fetchone()
        assert row is not None
        return dict(row)
    finally:
        conn.close()


def _latest_rotate_audit(db_path: str) -> dict[str, object] | None:
    conn = sqlite3.connect(db_path)
    try:
        conn.row_factory = sqlite3.Row
        row = conn.execute(
            "SELECT actor, action, target_type, target_id, details_json "
            "FROM audit_log WHERE action = 'rotate_key' "
            "ORDER BY id DESC LIMIT 1"
        ).fetchone()
        return dict(row) if row is not None else None
    finally:
        conn.close()


def _count_rotate_audits(db_path: str) -> int:
    conn = sqlite3.connect(db_path)
    try:
        return int(
            conn.execute(
                "SELECT COUNT(*) FROM audit_log WHERE action = 'rotate_key'"
            ).fetchone()[0]
        )
    finally:
        conn.close()


_PLAINTEXT_RE = re.compile(r"cmdr_live_[A-Za-z0-9_\-]{43}")


def _parse_plaintext_from_panel(stdout: str) -> str:
    """Extract the naked plaintext line from the KeyPanel output."""
    match = _PLAINTEXT_RE.search(stdout)
    assert match is not None, stdout
    return match.group(0)


# ---------------------------------------------------------------------------
# AC8 — happy path (full-column preservation, new hash + prefix).
# ---------------------------------------------------------------------------


class TestRotateKeyHappy:
    def test_rotates_same_id_new_hash_new_prefix_preserves_9_columns(
        self, env: dict[str, str]
    ) -> None:
        old_hash = "a" * 64
        _cid, kid = _seed_customer_and_key(
            env["db_path"],
            key_hash=old_hash,
            key_prefix="Pq_abc12",
            rate_limit_rpm=60,
            price_monthly=149.0,
            paid_until="2026-05-05",
            notes="bundled",
        )
        before = _fetch_api_key(env["db_path"], kid)
        _clear_buffers()

        result = runner.invoke(app, ["rotate-key", "Pq_abc12"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr

        after = _fetch_api_key(env["db_path"], kid)
        # Changed: key_hash, key_prefix, last_used_at (the seed had NULL
        # anyway so post-NULL stays NULL).
        assert after["key_hash"] != old_hash
        assert after["key_prefix"] != "Pq_abc12"
        assert after["last_used_at"] is None
        # Preserved: 9 columns.
        for col in (
            "id",
            "customer_id",
            "rate_limit_rpm",
            "status",
            "billing_mode",
            "price_monthly",
            "paid_until",
            "created_at",
            "notes",
        ):
            assert after[col] == before[col], col

        # KeyPanel rendered.
        assert "API KEY (copy now" in stdout
        # Audit row written with prefix delta.
        audit = _latest_rotate_audit(env["db_path"])
        assert audit is not None
        parsed = json.loads(str(audit["details_json"]))
        assert parsed["key_prefix_old"] == "Pq_abc12"
        assert parsed["key_prefix_new"] == after["key_prefix"]
        assert "reason" not in parsed

    def test_last_used_at_reset_on_rotation(self, env: dict[str, str]) -> None:
        _cid, kid = _seed_customer_and_key(env["db_path"])
        # Simulate prior usage.
        conn = sqlite3.connect(env["db_path"])
        try:
            conn.execute(
                "UPDATE api_key SET last_used_at = ? WHERE id = ?",
                ("2026-04-10T14:23:45Z", kid),
            )
            conn.commit()
        finally:
            conn.close()

        result = runner.invoke(app, ["rotate-key", "Pq_abc12"])
        assert result.exit_code == 0
        after = _fetch_api_key(env["db_path"], kid)
        assert after["last_used_at"] is None

    def test_old_plaintext_no_longer_matches_any_row(self, env: dict[str, str]) -> None:
        """FR11 end-of-life contract."""
        # Seed a key then issue (via issue-key flow) so we know the plaintext.
        # Simpler: seed directly with a known plaintext's hash.
        old_plaintext = "cmdr_live_" + "Z" * 43
        old_hash = hash_api_key(old_plaintext)
        _cid, _kid = _seed_customer_and_key(env["db_path"], key_hash=old_hash)

        result = runner.invoke(app, ["rotate-key", "Pq_abc12"])
        assert result.exit_code == 0

        conn = sqlite3.connect(env["db_path"])
        try:
            count = conn.execute(
                "SELECT COUNT(*) FROM api_key WHERE key_hash = ?",
                (old_hash,),
            ).fetchone()[0]
            assert count == 0
        finally:
            conn.close()

    def test_keypanel_shows_paid_until_not_first_charge(
        self, env: dict[str, str]
    ) -> None:
        _seed_customer_and_key(env["db_path"], paid_until="2026-05-05")
        _clear_buffers()
        result = runner.invoke(app, ["rotate-key", "Pq_abc12"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        # paid-until row present; first-charge row absent.
        assert re.search(r"paid until:\s+2026-05-05", stdout)
        assert "first charge:" not in stdout

    def test_keypanel_shows_em_dash_paid_until_when_null(
        self, env: dict[str, str]
    ) -> None:
        _seed_customer_and_key(env["db_path"], paid_until=None)
        _clear_buffers()
        result = runner.invoke(app, ["rotate-key", "Pq_abc12"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr
        assert re.search(r"paid until:\s+\u2014", stdout)
        assert "(not applicable)" not in stdout  # that's the complimentary suffix


# ---------------------------------------------------------------------------
# AC9 — complimentary rotation preserves billing_mode.
# ---------------------------------------------------------------------------


class TestRotateKeyComplimentary:
    def test_rotate_complimentary_preserves_billing_mode(
        self, env: dict[str, str]
    ) -> None:
        _cid, kid = _seed_customer_and_key(
            env["db_path"],
            billing_mode="complimentary",
            price_monthly=0.0,
            paid_until=None,
        )
        _clear_buffers()
        result = runner.invoke(app, ["rotate-key", "Pq_abc12"])
        stdout, stderr = _buffers()
        assert result.exit_code == 0, stderr

        after = _fetch_api_key(env["db_path"], kid)
        assert after["billing_mode"] == "complimentary"
        assert after["price_monthly"] == 0.0
        assert after["paid_until"] is None
        assert "billing mode: complimentary" in stdout
        assert re.search(r"paid until:\s+\u2014 \(not applicable\)", stdout)


# ---------------------------------------------------------------------------
# AC10 — revoked key rejected.
# ---------------------------------------------------------------------------


class TestRotateKeyRevoked:
    def test_rotate_revoked_exits_3(self, env: dict[str, str]) -> None:
        _cid, kid = _seed_customer_and_key(env["db_path"], status="revoked")
        before = _fetch_api_key(env["db_path"], kid)
        _clear_buffers()
        result = runner.invoke(app, ["rotate-key", "Pq_abc12"])
        stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Key is revoked: Pq_abc12" in stderr
        # No mutation, no audit, no KeyPanel on stdout.
        after = _fetch_api_key(env["db_path"], kid)
        assert after == before
        assert _count_rotate_audits(env["db_path"]) == 0
        assert "API KEY (copy now" not in stdout


# ---------------------------------------------------------------------------
# AC11 — atomicity (audit failure rolls back hash update, no KeyPanel).
# ---------------------------------------------------------------------------


class TestRotateKeyNotFound:
    def test_missing_key_exits_3(self, env: dict[str, str]) -> None:
        _seed_customer_and_key(env["db_path"])
        _clear_buffers()
        result = runner.invoke(app, ["rotate-key", "nokey123"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Key not found: nokey123" in stderr
        assert "list-keys" in stderr

    def test_ambiguous_prefix_exits_3(self, env: dict[str, str]) -> None:
        # Seed one key via the helper, then insert a second key sharing the
        # same 8-char ``key_prefix`` but a distinct ``key_hash``.
        _cid, _kid = _seed_customer_and_key(
            env["db_path"], key_prefix="Pq_abc12", key_hash="a" * 64
        )
        conn = get_connection(env["db_path"])
        try:
            insert_api_key(
                conn,
                ApiKeyRecord(
                    id=generate_key_id(),
                    customer_id=_cid,
                    key_hash="b" * 64,
                    key_prefix="Pq_abc12",
                    rate_limit_rpm=60,
                    status="active",
                    billing_mode="manual",
                    price_monthly=149.0,
                    paid_until=None,
                    created_at=datetime(2026, 4, 16, 13, 0, 0, tzinfo=UTC),
                    last_used_at=None,
                    notes="",
                ),
                actor="cli:tester",
            )
        finally:
            conn.close()

        _clear_buffers()
        result = runner.invoke(app, ["rotate-key", "Pq_abc12"])
        _stdout, stderr = _buffers()
        assert result.exit_code == 3
        assert "Ambiguous prefix: multiple keys match 'Pq_abc12'" in stderr


class TestRotateKeyAtomic:
    def test_rolls_back_when_log_event_fails(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        _cid, kid = _seed_customer_and_key(env["db_path"], key_hash="a" * 64)
        before = _fetch_api_key(env["db_path"], kid)

        import comadre.keys.audit as audit_module

        original = audit_module.log_event

        def _boom(*args: object, **kwargs: object) -> None:
            if kwargs.get("action") == "rotate_key":
                raise sqlite3.IntegrityError("forced audit failure")
            return original(*args, **kwargs)  # type: ignore[arg-type]

        monkeypatch.setattr(audit_module, "log_event", _boom)

        _clear_buffers()
        result = runner.invoke(app, ["rotate-key", "Pq_abc12"])
        stdout, stderr = _buffers()
        assert result.exit_code == 5, stderr
        assert "Database error" in stderr

        after = _fetch_api_key(env["db_path"], kid)
        assert after["key_hash"] == before["key_hash"]
        assert after["key_prefix"] == before["key_prefix"]
        assert _count_rotate_audits(env["db_path"]) == 0
        # KeyPanel not rendered — no halfway state.
        assert "API KEY (copy now" not in stdout


# ---------------------------------------------------------------------------
# AC12 — hash collision maps to exit 5 with retry hint.
# ---------------------------------------------------------------------------


class TestRotateKeyHashCollision:
    def test_hash_collision_exits_5_with_retry_hint(
        self, env: dict[str, str], monkeypatch: pytest.MonkeyPatch
    ) -> None:
        # Seed a second key whose hash we'll force rotate-key to collide against.
        conn = get_connection(env["db_path"])
        try:
            _apply_migrations(conn)
            cid = generate_customer_id()
            insert_customer(
                conn,
                CustomerRecord(
                    id=cid,
                    name="Helena Ribeiro",
                    email="helena@clinica.com",
                    tax_id_kind="cpf",
                    tax_id_encrypted=b"gAAAAA-ct",
                    notes="",
                    registered_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                    deleted_at=None,
                ),
                actor="cli:tester",
            )
            k_other = generate_key_id()
            other_hash = "f" * 64
            insert_api_key(
                conn,
                ApiKeyRecord(
                    id=k_other,
                    customer_id=cid,
                    key_hash=other_hash,
                    key_prefix="Other123",
                    rate_limit_rpm=60,
                    status="active",
                    billing_mode="manual",
                    price_monthly=149.0,
                    paid_until=None,
                    created_at=datetime(2026, 4, 16, 12, 0, 0, tzinfo=UTC),
                    last_used_at=None,
                    notes="",
                ),
                actor="cli:tester",
            )
            kid_target = generate_key_id()
            insert_api_key(
                conn,
                ApiKeyRecord(
                    id=kid_target,
                    customer_id=cid,
                    key_hash="b" * 64,
                    key_prefix="Pq_abc12",
                    rate_limit_rpm=60,
                    status="active",
                    billing_mode="manual",
                    price_monthly=149.0,
                    paid_until=None,
                    created_at=datetime(2026, 4, 16, 12, 0, 1, tzinfo=UTC),
                    last_used_at=None,
                    notes="",
                ),
                actor="cli:tester",
            )
        finally:
            conn.close()

        # Force hash_api_key (resolved via the function-level ``from
        # comadre.keys.tokens import hash_api_key`` in ``rotate_api_key``)
        # to return the colliding hash.
        import comadre.keys.tokens as tokens_module

        monkeypatch.setattr(tokens_module, "hash_api_key", lambda _p: other_hash)

        _clear_buffers()
        result = runner.invoke(app, ["rotate-key", "Pq_abc12"])
        stdout, stderr = _buffers()
        assert result.exit_code == 5, stderr
        assert "key hash collision" in stderr
        # Retry hint present.
        assert "vanishingly rare" in stderr
        # Original row untouched.
        after = _fetch_api_key(env["db_path"], kid_target)
        assert after["key_hash"] == "b" * 64
        # No KeyPanel on stdout.
        assert "API KEY (copy now" not in stdout


# ---------------------------------------------------------------------------
# AC17 — help.
# ---------------------------------------------------------------------------


class TestRotateKeyHelp:
    def test_rotate_key_help_has_realistic_examples(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.chdir(tmp_path)
        monkeypatch.delenv("KEY_REGISTRY_DB_PATH", raising=False)
        monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)

        result = runner.invoke(app, ["rotate-key", "--help"])
        assert result.exit_code == 0
        ansi = re.compile(r"\x1b\[[0-9;]*[A-Za-z]")
        cleaned = ansi.sub("", result.stdout)
        for glyph in ("\u2502", "\u256d", "\u256e", "\u2570", "\u256f", "\u2500"):
            cleaned = cleaned.replace(glyph, " ")
        flat = re.sub(r"\s+", " ", cleaned)
        assert "Pq_abc12" in flat
        assert "comadre-keys rotate-key Pq_abc12" in flat
        assert not (tmp_path / "registry.db").exists()


# ---------------------------------------------------------------------------
# AC18 — log sanitization.
# ---------------------------------------------------------------------------


class TestRotateKeySanitization:
    def test_log_has_no_plaintext_no_hash(self, env: dict[str, str]) -> None:
        from comadre.logging import get_logger

        _cid, _kid = _seed_customer_and_key(env["db_path"], key_hash="a" * 64)
        logger = get_logger("keys.cli")
        records: list[logging.LogRecord] = []

        class _Capture(logging.Handler):
            def emit(self, record: logging.LogRecord) -> None:
                records.append(record)

        handler = _Capture(level=logging.INFO)
        logger.addHandler(handler)
        try:
            _clear_buffers()
            records.clear()
            result = runner.invoke(app, ["rotate-key", "Pq_abc12"])
        finally:
            logger.removeHandler(handler)

        stdout, _stderr = _buffers()
        assert result.exit_code == 0
        plaintext = _parse_plaintext_from_panel(stdout)
        joined = "\n".join(r.getMessage() for r in records)
        # Old prefix + new prefix present in log.
        assert "key_prefix_old=Pq_abc12" in joined
        assert "key_prefix_new=" in joined
        # Plaintext NEVER in log line.
        assert plaintext not in joined
        # No 64-hex run (hash proxy).
        assert not re.search(r"[0-9a-f]{64}", joined)
        # Customer name NEVER in log.
        assert "Helena Ribeiro" not in joined


# ---------------------------------------------------------------------------
# AC19 — read-after-write via `show`.
# ---------------------------------------------------------------------------


class TestRotateKeyReadAfterWrite:
    def test_then_show_reflects_new_prefix_old_visible_only_in_audit_tail(
        self, env: dict[str, str]
    ) -> None:
        _cid, kid = _seed_customer_and_key(env["db_path"], key_prefix="Pq_abc12")
        r_rot = runner.invoke(app, ["rotate-key", "Pq_abc12"])
        assert r_rot.exit_code == 0
        after = _fetch_api_key(env["db_path"], kid)
        new_prefix = str(after["key_prefix"])

        _clear_buffers()
        r_show = runner.invoke(app, ["show", new_prefix, "--audit-tail", "5"])
        stdout, _stderr = _buffers()
        assert r_show.exit_code == 0
        # DetailPanel shows the NEW prefix.
        assert f"Prefix:     {new_prefix}" in stdout or new_prefix in stdout
        # AuditTail carries the ROTATE_KEY event with prefix_old=Pq_abc12.
        assert "ROTATE_KEY" in stdout
        assert "Pq_abc12" in stdout  # old prefix visible only via audit
