"""Tests for the monetization-gated Phase 2a lifespan bootstrap.

The legacy lifespan is covered indirectly by every other test_api / test_health
case; this module only validates the branch Story 2.1 adds.
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


def _stub_engine_init(monkeypatch: pytest.MonkeyPatch) -> None:
    """Bypass heavy startup phases: KokoroEngine/QwenEngine instantiation,
    ``ensure_*_models`` downloads, and engine warm-up."""
    import comadre.main as main_module

    class _StubEngine:
        def load_model(self, **_: object) -> None:
            pass

        def warm_up(self, **_: object) -> None:
            pass

    class _StubRouter:
        def __init__(self, **_: object) -> None:
            pass

        def available_voices(self) -> list[str]:
            return ["kokoro/pm_santa"]

        def _parse_voice(self, _voice: str) -> None:
            return None

    monkeypatch.setattr(main_module, "KokoroEngine", _StubEngine)
    monkeypatch.setattr(main_module, "QwenEngine", _StubEngine)
    monkeypatch.setattr(main_module, "ensure_kokoro_models", lambda **_: None)
    monkeypatch.setattr(main_module, "ensure_qwen3_models", lambda **_: None)
    monkeypatch.setattr(main_module, "EngineRouter", _StubRouter)


@pytest.fixture()
def registry_env(monkeypatch: pytest.MonkeyPatch, tmp_path: Path) -> Path:
    """Set env vars so ``get_settings()`` builds a valid Settings."""
    db_path = tmp_path / "registry.db"
    monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode())
    monkeypatch.setenv("QWEN3_ENABLED", "false")
    monkeypatch.setenv("VOICES_DIR", str(tmp_path))
    monkeypatch.setenv("NOISE_DIR", str(tmp_path))
    get_settings.cache_clear()
    return db_path


async def test_registry_bootstrap_migrates_caches_and_closes_db(
    monkeypatch: pytest.MonkeyPatch, registry_env: Path
) -> None:
    """Single integration cover: lifespan opens the registry, applies
    migrations, attaches the auth-cache, and closes the connection on
    shutdown."""
    _stub_engine_init(monkeypatch)

    opened: list[sqlite3.Connection] = []
    import comadre.main as main_module

    real_get_connection = main_module.get_connection

    def spy(path: Any) -> sqlite3.Connection:
        conn = real_get_connection(path)
        opened.append(conn)
        return conn

    monkeypatch.setattr(main_module, "get_connection", spy)

    app = FastAPI()
    cm = lifespan(app)
    await cm.__aenter__()
    try:
        # Auth cache wired with contractual sizing.
        snapshot = app.state.auth_cache.snapshot()
        assert snapshot["maxsize"] == 4096
        assert snapshot["ttl_seconds"] == 60
    finally:
        await cm.__aexit__(None, None, None)

    # Migrations applied — schema_version row matches the constant.
    from comadre.keys.db import _SCHEMA_VERSION

    conn = sqlite3.connect(registry_env)
    try:
        version_row = conn.execute("SELECT MAX(version) FROM schema_version").fetchone()
        assert version_row[0] == _SCHEMA_VERSION
    finally:
        conn.close()

    # Connection closed on shutdown — using it raises ProgrammingError.
    assert len(opened) == 1
    with pytest.raises(sqlite3.ProgrammingError):
        opened[0].execute("SELECT 1").fetchone()
