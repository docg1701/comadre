"""Story 4.4 — multi-replica safety regression for ``get_connection`` (FR44, NFR29).

Comadre 2.0 lets operators scale ``deploy.replicas`` in ``compose.yaml``.
Every replica opens its own SQLite connection against the same registry
file under WAL mode. These tests pin the contract that the connection
helper sustains concurrent reads during an open writer transaction
without ``SQLITE_BUSY``, that WAL mode is set on every fresh connection,
and that the parent directory + DB file land on mode ``0700`` / ``0600``
per ``_chmod_0600`` + ``mkdir(mode=0o700)``.

The within-process two-connection scenario is sufficient for the WAL
contract (SQLite's WAL semantics are symmetric across the process
boundary). True cross-process scaling is exercised in Task 8 of the
story spec via ``compose.yaml``'s ``deploy.replicas``.
"""

from __future__ import annotations

import sqlite3
import stat
from pathlib import Path

import pytest

from comadre.keys.db import (
    _apply_migrations,
    generate_customer_id,
    get_connection,
)


def _now() -> str:
    return "2026-04-20T12:00:00Z"


_INSERT_CUSTOMER = (
    "INSERT INTO customer ("
    "id, name, email, tax_id_kind, tax_id_encrypted, notes, "
    "registered_at, deleted_at"
    ") VALUES (?, ?, ?, ?, ?, ?, ?, ?)"
)


def test_two_connections_concurrent_read_during_open_writer_txn(
    tmp_path: Path,
) -> None:
    """FR44 + NFR29 — WAL lets a reader proceed while a writer's transaction
    is still open.

    This is the load-bearing multi-replica contract: replica A holds an
    uncommitted BEGIN IMMEDIATE; replica B must still be able to read the
    committed snapshot without ``SQLITE_BUSY`` and must NOT see A's
    in-flight write. Under rollback-journal mode, B would block on the
    shared-DB writer lock — the test would fail. WAL's value proposition
    is exactly this concurrent-reader-during-open-writer window.
    """
    db_path = tmp_path / "registry.db"
    conn_a = get_connection(db_path)
    _apply_migrations(conn_a)
    conn_b = get_connection(db_path)
    try:
        cid_pre = generate_customer_id()
        with conn_a:
            conn_a.execute(
                _INSERT_CUSTOMER,
                (
                    cid_pre,
                    "Pre-existing",
                    "pre@example.com",
                    "cpf",
                    b"\x00",
                    "",
                    _now(),
                    None,
                ),
            )

        # A opens an explicit IMMEDIATE transaction and inserts without
        # committing. The writer lock is now held by A.
        conn_a.execute("BEGIN IMMEDIATE")
        cid_mid = generate_customer_id()
        conn_a.execute(
            _INSERT_CUSTOMER,
            (
                cid_mid,
                "Mid-flight",
                "mid@example.com",
                "cpf",
                b"\x00",
                "",
                _now(),
                None,
            ),
        )

        # B reads while A still holds the writer lock.
        # WAL guarantees no SQLITE_BUSY and returns the pre-A-commit snapshot.
        pre = conn_b.execute(
            "SELECT name FROM customer WHERE id = ?", (cid_pre,)
        ).fetchall()
        assert [r["name"] for r in pre] == ["Pre-existing"]
        mid = conn_b.execute(
            "SELECT name FROM customer WHERE id = ?", (cid_mid,)
        ).fetchall()
        assert mid == []  # A's write is uncommitted — invisible to B.

        # A second writer (B) must be blocked on the writer lock held by A.
        # WAL serialises writers — readers are concurrent, writers are not.
        with pytest.raises(sqlite3.OperationalError, match="database is locked"):
            conn_b.execute("BEGIN IMMEDIATE")

        # A commits; B then sees the new row on its next read (new snapshot).
        conn_a.execute("COMMIT")
        # End any implicit read transaction B might hold so the next SELECT
        # opens a fresh snapshot that includes A's commit.
        conn_b.commit()
        post = conn_b.execute(
            "SELECT name FROM customer WHERE id = ?", (cid_mid,)
        ).fetchall()
        assert [r["name"] for r in post] == ["Mid-flight"]

        assert stat.S_IMODE(db_path.stat().st_mode) == 0o600
    finally:
        conn_a.close()
        conn_b.close()


def test_journal_mode_is_wal_on_every_fresh_get_connection(
    tmp_path: Path,
) -> None:
    """Every fresh connection independently sets WAL mode at open.

    Uses a unique DB path per iteration — reusing one path would be
    tautological (WAL is a persistent file-level attribute, so
    iterations 2+ would read back ``wal`` even if the PRAGMA call were
    silently dropped from ``get_connection``).
    """
    for i in range(3):
        db_path = tmp_path / f"registry-{i}.db"
        conn = get_connection(db_path)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"
        finally:
            conn.close()


def test_parent_directory_is_0700_after_first_connection(tmp_path: Path) -> None:
    """FR42 / NFR13 — parent dir mode + DB file mode enforced at open."""
    db_path = tmp_path / "subdir" / "registry.db"
    assert not db_path.parent.exists()  # mkdir is part of the contract
    conn = get_connection(db_path)
    try:
        parent_mode = stat.S_IMODE(db_path.parent.stat().st_mode)
        assert parent_mode == 0o700
        db_mode = stat.S_IMODE(db_path.stat().st_mode)
        assert db_mode == 0o600
    finally:
        conn.close()
