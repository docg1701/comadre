"""Tests for ``/health`` (build_health_response + HTTP).

Lean by design (test-suite review 2026-04-25): one full-shape test for
the authenticated path (all 7 fields + order), one minimal-shape test
for unauthenticated (status + voices only), one 503 warming-up.
"""

from __future__ import annotations

import time
from unittest.mock import MagicMock

import pytest
from httpx import AsyncClient

from comadre.health import build_health_response, build_minimal_health_response


@pytest.fixture()
def mock_router() -> MagicMock:
    router = MagicMock()
    router.available_voices.return_value = [
        "kokoro/pm_santa",
        "qwen/female-reference",
    ]
    router.engine_status.return_value = {
        "kokoro": {"loaded": True, "voices": ["kokoro/pm_santa"]},
        "qwen3": {"loaded": True, "voices": ["qwen/female-reference"]},
    }
    return router


def test_full_health_response_has_seven_fields_in_fixed_order(
    mock_router: MagicMock,
) -> None:
    """The authenticated /health is a contract for monitor scripts:
    every field present, in a fixed order, status=healthy when ready."""
    body, status_code = build_health_response(
        router=mock_router, ready=True, start_time=time.monotonic()
    )
    assert status_code == 200
    assert body["status"] == "healthy"
    assert list(body.keys()) == [
        "status",
        "voices",
        "engines",
        "queue_depth",
        "uptime_seconds",
        "memory_mb",
        "version",
    ]
    assert body["voices"] == mock_router.available_voices()


def test_minimal_health_response_returns_only_status_and_voices(
    mock_router: MagicMock,
) -> None:
    """Unauthenticated /health: 200 + minimal shape; engine internals not exposed."""
    body, status_code = build_minimal_health_response(router=mock_router, ready=True)
    assert status_code == 200
    assert set(body.keys()) == {"status", "voices"}
    assert body["status"] == "healthy"


def test_minimal_health_response_returns_503_warming_up_when_not_ready(
    mock_router: MagicMock,
) -> None:
    body, status_code = build_minimal_health_response(router=mock_router, ready=False)
    assert status_code == 503
    assert body["status"] == "warming_up"


async def test_health_endpoint_unauthenticated_returns_minimal_shape(
    client: AsyncClient,
) -> None:
    """End-to-end smoke through the FastAPI app."""
    response = await client.get("/health")
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {"status", "voices"}
    assert body["status"] == "healthy"


async def test_health_endpoint_authenticated_returns_full_shape(
    client: AsyncClient, auth_headers: dict[str, str]
) -> None:
    response = await client.get("/health", headers=auth_headers)
    assert response.status_code == 200
    body = response.json()
    assert set(body.keys()) == {
        "status",
        "voices",
        "engines",
        "queue_depth",
        "uptime_seconds",
        "memory_mb",
        "version",
    }
