"""Shared pytest configuration and marker registration."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from comadre.config import Settings, get_settings
from comadre.main import create_app

TEST_API_KEY = "test-key-12345"


def pytest_configure(config: pytest.Config) -> None:
    """Register custom markers."""
    config.addinivalue_line(
        "markers", "slow: marks tests requiring real model inference"
    )


@pytest.fixture(autouse=True)
def _clear_settings_cache() -> None:
    """Clear get_settings LRU cache to prevent cross-test leakage."""
    get_settings.cache_clear()


@pytest.fixture()
def mock_settings() -> Settings:
    """Return a Settings instance with a known API key and defaults."""
    return Settings(api_key=SecretStr(TEST_API_KEY))


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
def app(mock_settings: Settings, mock_router: MagicMock) -> Any:
    """Create a FastAPI app with mocked state (no lifespan)."""
    application = create_app()
    application.state.settings = mock_settings
    application.state.router = mock_router
    application.state.ready = True
    application.state.queue_lock = asyncio.Lock()
    application.state.queue_depth = 0
    application.state.start_time = time.monotonic()
    return application


@pytest.fixture()
async def client(app: Any) -> AsyncIterator[AsyncClient]:
    """Return an httpx AsyncClient wired to the test app."""
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c


@pytest.fixture()
def auth_headers() -> dict[str, str]:
    """Return authorization headers matching mock_settings."""
    return {"Authorization": f"Bearer {TEST_API_KEY}"}
