"""Shared pytest configuration and marker registration."""

from __future__ import annotations

import asyncio
import sqlite3
import time
from collections.abc import AsyncIterator
from pathlib import Path
from typing import Any
from unittest.mock import MagicMock

import pytest
from cryptography.fernet import Fernet
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from comadre.config import Settings, get_settings
from comadre.keys.cache import AuthCache
from comadre.keys.db import _apply_migrations, get_connection
from comadre.main import create_app
from comadre.rate_limit import RateLimiter


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests requiring real model inference"
    )


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Clear get_settings LRU cache to prevent cross-test leakage."""
    get_settings.cache_clear()


# 2026-04-18: the slowapi ``_reset_rate_limiter`` autouse fixture is gone.
# Each test's ``app`` fixture constructs a fresh ``RateLimiter`` with its own
# in-memory storage, so no cross-test bucket leakage is possible.


@pytest.fixture()
def fernet_key() -> str:
    """Return a freshly generated Fernet key for tests."""
    return Fernet.generate_key().decode()


@pytest.fixture()
def mock_settings(fernet_key: str) -> Settings:
    """Return a Settings instance with test defaults.

    2026-04-18: `api_key` (single shared secret) was removed when FR27 was
    retired; registry mode is the only auth path. Tests that need a
    specific encryption key override `key_registry_encryption_key`.
    """
    return Settings(key_registry_encryption_key=SecretStr(fernet_key))


@pytest.fixture()
def mock_router() -> MagicMock:
    """Return a mock EngineRouter with typical methods stubbed."""
    router = MagicMock()
    router.generate_speech.return_value = b"fake-audio-bytes"
    router.available_voices.return_value = [
        "kokoro/pm_alex",
        "kokoro/pf_dora",
        "kokoro/pm_santa",
        "qwen/female-reference",
        "qwen/male-reference",
    ]
    router.engine_status.return_value = {
        "kokoro": {
            "loaded": True,
            "voices": ["kokoro/pm_alex", "kokoro/pf_dora", "kokoro/pm_santa"],
        },
        "qwen3": {
            "loaded": True,
            "voices": ["qwen/female-reference", "qwen/male-reference"],
        },
    }
    return router


@pytest.fixture()
def registry_db_path(tmp_path: Path) -> Path:
    """Return the tmp-path location the test app writes its registry to."""
    return tmp_path / "registry.db"


@pytest.fixture()
def app(
    mock_router: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
    registry_db_path: Path,
    fernet_key: str,
) -> Any:
    """Registry-mode FastAPI app with mocked engine state.

    2026-04-18: the pre-FR27-retirement `app` / `app_monetized` split is
    collapsed into a single fixture — there is no legacy mode. Opens the
    registry DB, applies migrations, attaches an ``AuthCache``. Integration
    tests seed customer/api_key rows via ``app.state.registry_db`` directly.
    """
    monkeypatch.setenv("RATE_LIMIT_HEALTH", "9999/minute")
    monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(registry_db_path))
    monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", fernet_key)
    monkeypatch.setenv(
        "OPERATOR_CONTACT_HINT", "Contact Ana on WhatsApp: +55 11 90000-0000"
    )
    get_settings.cache_clear()

    application = create_app()
    application.state.settings = get_settings()
    application.state.router = mock_router
    application.state.ready = True
    application.state.queue_lock = asyncio.Lock()
    application.state.queue_depth = 0
    application.state.start_time = time.monotonic()

    conn = get_connection(registry_db_path)
    _apply_migrations(conn)
    application.state.registry_db = conn
    application.state.auth_cache = AuthCache()
    application.state.rate_limiter = RateLimiter.build()

    try:
        yield application
    finally:
        conn.close()


@pytest.fixture()
async def client(app: Any) -> AsyncIterator[AsyncClient]:
    """httpx AsyncClient wired to the test app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.fixture()
def registry_db(app: Any) -> sqlite3.Connection:
    """Shortcut to the test app's SQLite connection."""
    conn: sqlite3.Connection = app.state.registry_db
    return conn


@pytest.fixture()
def auth_headers(app: Any, monkeypatch: pytest.MonkeyPatch) -> dict[str, str]:
    """Seed a generous active key and return a Bearer-auth header dict.

    2026-04-18: pre-FR27-retirement this fixture returned a legacy
    ``test-key-12345`` bearer; now it seeds an actual registry row with a
    high ``rate_limit_rpm`` so any test using ``auth_headers`` can fire
    dozens of requests without tripping the per-key limit.
    """
    from datetime import date

    from comadre.keys import auth as auth_module
    from tests._keys_fixtures import seed_customer_and_key

    monkeypatch.setattr(
        auth_module, "_today_in_billing_tz", lambda _s: date(2026, 4, 17)
    )
    plaintext, _kid, _cid = seed_customer_and_key(
        app.state.registry_db, rate_limit_rpm=9999
    )
    return {"Authorization": f"Bearer {plaintext}"}
