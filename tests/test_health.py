"""Tests for health response assembler."""

from __future__ import annotations

import asyncio
import time
from unittest.mock import MagicMock, patch

import pytest
from httpx import ASGITransport, AsyncClient

from comadre import __version__
from comadre.config import get_settings
from comadre.health import HealthStatus, build_health_response
from comadre.main import create_app


@pytest.fixture()
def mock_router() -> MagicMock:
    """Return a mock EngineRouter with typical healthy state."""
    router = MagicMock()
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


class TestHealthyResponse:
    """Tests for ready=True (healthy) responses."""

    def test_returns_200_status_code(self, mock_router: MagicMock) -> None:
        _, status_code = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic()
        )
        assert status_code == 200

    def test_status_field_is_healthy(self, mock_router: MagicMock) -> None:
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic()
        )
        assert body["status"] == "healthy"

    def test_all_fields_present(self, mock_router: MagicMock) -> None:
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic()
        )
        expected_keys = {
            "status",
            "voices",
            "engines",
            "queue_depth",
            "uptime_seconds",
            "memory_mb",
            "version",
        }
        assert set(body.keys()) == expected_keys

    def test_field_order_is_contractual(self, mock_router: MagicMock) -> None:
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic()
        )
        assert list(body.keys()) == [
            "status",
            "voices",
            "engines",
            "queue_depth",
            "uptime_seconds",
            "memory_mb",
            "version",
        ]

    def test_voices_is_list(self, mock_router: MagicMock) -> None:
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic()
        )
        assert isinstance(body["voices"], list)
        assert body["voices"] == [
            "kokoro/pm_alex",
            "kokoro/pf_dora",
            "kokoro/pm_santa",
            "qwen/female-reference",
            "qwen/male-reference",
        ]


class TestWarmingUpResponse:
    """Tests for ready=False (warming_up) responses."""

    def test_returns_503_status_code(self, mock_router: MagicMock) -> None:
        _, status_code = build_health_response(
            router=mock_router, ready=False, start_time=time.monotonic()
        )
        assert status_code == 503

    def test_status_field_is_warming_up(self, mock_router: MagicMock) -> None:
        body, _ = build_health_response(
            router=mock_router, ready=False, start_time=time.monotonic()
        )
        assert body["status"] == "warming_up"


class TestVoicesField:
    """Tests for the voices field behavior."""

    def test_empty_voices_returns_empty_list(self, mock_router: MagicMock) -> None:
        mock_router.available_voices.return_value = []
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic()
        )
        assert body["voices"] == []
        assert isinstance(body["voices"], list)


class TestEnginesField:
    """Tests for the engines field structure."""

    def test_engines_contains_kokoro_and_qwen3(self, mock_router: MagicMock) -> None:
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic()
        )
        assert "kokoro" in body["engines"]
        assert "qwen3" in body["engines"]

    def test_kokoro_engine_structure(self, mock_router: MagicMock) -> None:
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic()
        )
        kokoro = body["engines"]["kokoro"]
        assert kokoro["loaded"] is True
        assert "kokoro/pm_santa" in kokoro["voices"]

    def test_qwen3_engine_structure(self, mock_router: MagicMock) -> None:
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic()
        )
        qwen3 = body["engines"]["qwen3"]
        assert qwen3["loaded"] is True
        assert "qwen/female-reference" in qwen3["voices"]


class TestVersionField:
    """Tests for the version field."""

    def test_version_matches_package(self, mock_router: MagicMock) -> None:
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic()
        )
        assert body["version"] == __version__


class TestUptimeField:
    """Tests for the uptime_seconds field."""

    def test_uptime_is_positive(self, mock_router: MagicMock) -> None:
        start_time = time.monotonic() - 100
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=start_time
        )
        assert body["uptime_seconds"] >= 100
        assert isinstance(body["uptime_seconds"], int)


class TestMemoryField:
    """Tests for the memory_mb field."""

    @patch("comadre.health.resource")
    def test_memory_mb_calculation(
        self, mock_resource: MagicMock, mock_router: MagicMock
    ) -> None:
        mock_resource.getrusage.return_value.ru_maxrss = 512_000  # ~500 MB in KB
        mock_resource.RUSAGE_SELF = 0
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic()
        )
        assert body["memory_mb"] == 500  # 512000 // 1024

    @patch("comadre.health.resource")
    def test_memory_mb_is_positive_int(
        self, mock_resource: MagicMock, mock_router: MagicMock
    ) -> None:
        mock_resource.getrusage.return_value.ru_maxrss = 1024  # 1 MB
        mock_resource.RUSAGE_SELF = 0
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic()
        )
        assert body["memory_mb"] == 1
        assert isinstance(body["memory_mb"], int)


class TestQueueDepth:
    """Tests for the queue_depth field."""

    def test_queue_depth_defaults_to_zero(self, mock_router: MagicMock) -> None:
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic()
        )
        assert body["queue_depth"] == 0

    def test_queue_depth_custom_value(self, mock_router: MagicMock) -> None:
        body, _ = build_health_response(
            router=mock_router, ready=True, start_time=time.monotonic(), queue_depth=5
        )
        assert body["queue_depth"] == 5


class TestHealthStatusEnum:
    """Tests for the HealthStatus enum."""

    def test_healthy_value(self) -> None:
        assert HealthStatus.healthy == "healthy"

    def test_warming_up_value(self) -> None:
        assert HealthStatus.warming_up == "warming_up"

    def test_degraded_value(self) -> None:
        assert HealthStatus.degraded == "degraded"


# --- HTTP-level health endpoint tests ---


class TestHealthHTTPEndpoint:
    """Tests for GET /health via HTTP using AsyncClient."""

    async def test_health_returns_200_when_ready(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        assert response.status_code == 200
        body = response.json()
        assert body["status"] == "healthy"
        expected_keys = {
            "status",
            "voices",
            "engines",
            "queue_depth",
            "uptime_seconds",
            "memory_mb",
            "version",
        }
        assert set(body.keys()) == expected_keys

    async def test_health_returns_503_when_not_ready(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        monkeypatch.setenv("API_KEY", "test-key")
        monkeypatch.setenv("RATE_LIMIT_SPEECH", "9999/minute")
        monkeypatch.setenv("RATE_LIMIT_HEALTH", "9999/minute")
        get_settings.cache_clear()
        app = create_app()
        app.state.ready = False
        app.state.router = None
        app.state.queue_lock = asyncio.Lock()
        app.state.queue_depth = 0
        app.state.start_time = time.monotonic()
        async with AsyncClient(
            transport=ASGITransport(app=app),
            base_url="http://test",
        ) as c:
            response = await c.get("/health")
        assert response.status_code == 503
        body = response.json()
        assert body["status"] == "warming_up"

    async def test_health_requires_no_authentication(self, client: AsyncClient) -> None:
        # No Authorization header — should still return 200
        response = await client.get("/health")
        assert response.status_code == 200

    async def test_health_voices_reflect_router(self, client: AsyncClient) -> None:
        response = await client.get("/health")
        body = response.json()
        assert body["voices"] == [
            "kokoro/pm_alex",
            "kokoro/pf_dora",
            "kokoro/pm_santa",
            "qwen/female-reference",
            "qwen/male-reference",
        ]
