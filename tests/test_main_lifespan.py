"""Tests for the monetization-gated Phase 2a lifespan bootstrap.

The legacy lifespan is covered indirectly by every other `test_api` /
`test_health` case; this module only validates the branch Story 2.1 adds.
"""

from __future__ import annotations

import sqlite3
from pathlib import Path
from typing import Any

import pytest
from cryptography.fernet import Fernet
from fastapi import FastAPI

from comadre.config import get_settings
from comadre.main import lifespan


async def _run_lifespan(app: FastAPI) -> None:
    """Open the lifespan context manager, then close it immediately."""
    cm = lifespan(app)
    await cm.__aenter__()
    await cm.__aexit__(None, None, None)


def _stub_engine_init(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass heavy startup phases — engines / downloads / warm-ups.

    Swaps the cooperating pieces that would otherwise try to hit the
    filesystem / model files: KokoroEngine/QwenEngine instantiation,
    ``ensure_*_models`` downloads, and engine warm-up. What's left is the
    skeleton the Phase 2a branch operates on.
    """
    import comadre.main as main_module

    class _StubKokoro:
        def load_model(self, **_: object) -> None:
            """No-op."""

        def warm_up(self) -> None:
            """No-op."""

    class _StubQwen:
        def load_model(self, **_: object) -> None:
            """No-op."""

        def warm_up(self, **_: object) -> None:
            """No-op."""

    monkeypatch.setattr(main_module, "KokoroEngine", _StubKokoro)
    monkeypatch.setattr(main_module, "QwenEngine", _StubQwen)
    monkeypatch.setattr(main_module, "ensure_kokoro_models", lambda **_: None)
    monkeypatch.setattr(main_module, "ensure_qwen3_models", lambda **_: None)

    # Stub the router so the `available_voices()` sanity-check passes.
    class _StubRouter:
        def __init__(self, **_: object) -> None:
            pass

        def available_voices(self) -> list[str]:
            return ["kokoro/pm_santa"]

        def _parse_voice(self, _voice: str) -> None:
            return None

    monkeypatch.setattr(main_module, "EngineRouter", _StubRouter)


@pytest.fixture()
def registry_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Set env vars so ``get_settings()`` builds a registry-mode Settings.

    2026-04-18: legacy single-API_KEY mode retired (FR27). Registry is the
    sole auth path; this is the default — no toggle to flip on.
    """
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("QWEN3_ENABLED", "false")
    monkeypatch.setenv("VOICES_DIR", str(tmp_path))
    monkeypatch.setenv("NOISE_DIR", str(tmp_path))
    get_settings.cache_clear()
    return db_path


class TestRegistryBootstrap:
    async def test_opens_registry_and_runs_migrations(
        self,
        monkeypatch: pytest.MonkeyPatch,
        registry_env: Path,
    ) -> None:
        _stub_engine_init(monkeypatch)
        app = FastAPI()
        await _run_lifespan(app)
        # After lifespan exits the connection is closed — check the file
        # state before/after lifespan cycle for migration application.
        conn = sqlite3.connect(registry_env)
        try:
            version_row = conn.execute(
                "SELECT MAX(version) FROM schema_version"
            ).fetchone()
            assert version_row[0] == 1
        finally:
            conn.close()

    async def test_auth_cache_initialised(
        self,
        monkeypatch: pytest.MonkeyPatch,
        registry_env: Path,
    ) -> None:
        _stub_engine_init(monkeypatch)
        app = FastAPI()
        cm = lifespan(app)
        await cm.__aenter__()
        try:
            assert hasattr(app.state, "auth_cache")
            snapshot = app.state.auth_cache.snapshot()
            assert snapshot["maxsize"] == 4096
            assert snapshot["ttl_seconds"] == 60
        finally:
            await cm.__aexit__(None, None, None)

    async def test_shutdown_closes_db_connection(
        self,
        monkeypatch: pytest.MonkeyPatch,
        registry_env: Path,
    ) -> None:
        _stub_engine_init(monkeypatch)
        opened: list[sqlite3.Connection] = []

        import comadre.main as main_module

        real_get_connection = main_module.get_connection

        def spy_get_connection(path: Any) -> sqlite3.Connection:
            conn = real_get_connection(path)
            opened.append(conn)
            return conn

        monkeypatch.setattr(main_module, "get_connection", spy_get_connection)

        app = FastAPI()
        await _run_lifespan(app)

        assert len(opened) == 1
        # Post-shutdown the connection must be closed.
        with pytest.raises(sqlite3.ProgrammingError):
            opened[0].execute("SELECT 1").fetchone()
