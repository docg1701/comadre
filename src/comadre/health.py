"""Health response assembler for COMADRE."""

from __future__ import annotations

import resource
import time
from enum import StrEnum
from typing import TYPE_CHECKING, Any

from comadre import __version__
from comadre.logging import get_logger

if TYPE_CHECKING:
    from comadre.service import EngineRouter

logger = get_logger("health")


class HealthStatus(StrEnum):
    """Service health status values."""

    healthy = "healthy"
    warming_up = "warming_up"
    degraded = "degraded"


def _get_memory_mb() -> int:
    """Return peak process RSS in megabytes (ru_maxrss)."""
    usage_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage_kb // 1024


def _get_uptime_seconds(start_time: float) -> int:
    """Return seconds since application startup."""
    return int(time.monotonic() - start_time)


def build_health_response(
    *,
    router: EngineRouter,
    ready: bool,
    start_time: float,
    queue_depth: int = 0,
) -> tuple[dict[str, Any], int]:
    """Build health response dict and HTTP status code.

    Returns (response_body, status_code) tuple.
    Field order is contractual — dict insertion order is preserved in Python 3.7+.
    """
    if ready:
        status = HealthStatus.healthy
        status_code = 200
    else:
        status = HealthStatus.warming_up
        status_code = 503

    engine_status = router.engine_status()
    clone_configured: bool = engine_status["qwen3"]["clone_configured"]  # type: ignore[assignment]

    body: dict[str, Any] = {
        "status": str(status),
        "voices": router.available_voices(),
        "engines": engine_status,
        "queue_depth": queue_depth,
        "clone_configured": clone_configured,
        "uptime_seconds": _get_uptime_seconds(start_time),
        "memory_mb": _get_memory_mb(),
        "version": __version__,
    }

    return body, status_code
