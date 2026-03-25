# Story 1.8: Health Endpoint

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **DevOps operator**,
I want a rich health endpoint that reports service state at a glance,
so that I can monitor the service and diagnose issues without SSH-ing into the VPS.

## Acceptance Criteria

1. **Given** the service is running and healthy **When** I send `GET /health` **Then** I receive a 200 JSON response with fixed field order: `status` ("healthy"), `voices` (array of loaded voice names), `engines` (per-engine status object), `queue_depth`, `clone_configured`, `uptime_seconds`, `memory_mb`, `version`

2. **Given** the service is still loading models or warming up **When** I send `GET /health` **Then** I receive a 503 JSON response with `status: "warming_up"`

3. **Given** the health endpoint **When** I send a request without an Authorization header **Then** it responds normally (no authentication required for health)

4. **Given** the health response **When** I inspect the `voices` field **Then** it is always an array (never null), and empty `[]` if no voices are loaded

5. **Given** the health response **When** I inspect the `engines` field **Then** it contains per-engine status objects with `loaded` (bool), `voices` (array), and for qwen3: `clone_configured` (bool)

## Tasks / Subtasks

- [x] Task 1: Create `src/comadre/health.py` — health response assembler module (AC: #1, #2, #4, #5)
  - [x] 1.1 Define `HealthStatus` enum: `healthy`, `warming_up`, `degraded`
  - [x] 1.2 Implement `build_health_response(router, ready, start_time)` that aggregates runtime state into a dict with fixed field order
  - [x] 1.3 Implement `_get_memory_mb()` helper using `resource.getrusage` (stdlib — no new dependency)
  - [x] 1.4 Implement `_get_uptime_seconds(start_time)` helper
  - [x] 1.5 Return 200 when ready=True, 503 when ready=False

- [x] Task 2: Create `tests/test_health.py` — unit tests for health module (AC: #1-#5)
  - [x] 2.1 Test healthy response: 200 status, all fields present, fixed field order, correct types
  - [x] 2.2 Test warming_up response: 503 status, `status: "warming_up"`
  - [x] 2.3 Test voices field is always an array (empty engines → empty array)
  - [x] 2.4 Test engines field structure (kokoro/qwen3 sub-objects)
  - [x] 2.5 Test clone_configured reflects router state
  - [x] 2.6 Test version matches `__version__`
  - [x] 2.7 Test uptime_seconds is a positive number
  - [x] 2.8 Test memory_mb is a positive number

## Dev Notes

### What Already Exists (DO NOT recreate)

**`src/comadre/service.py`** — EngineRouter already provides everything health needs:
- `EngineRouter.engine_status()` → returns `{"kokoro": {"loaded": bool, "voices": [...]}, "qwen3": {"loaded": bool, "clone_configured": bool, "voices": [...]}}`
- `EngineRouter.available_voices()` → returns sorted combined voice list from both engines
- `EngineRouter._qwen.is_clone_configured` → bool for clone reference WAV status

**`src/comadre/__init__.py`** — `__version__ = "0.1.0"` — use this for the version field.

**`src/comadre/exceptions.py`** — `ServiceUnavailableError` (503) already exists. Health module does NOT raise exceptions — it returns dicts. The 503 status code for warming_up is set directly on the JSONResponse.

**`src/comadre/logging.py`** — `get_logger("health")` for the component logger.

### What This Story Creates

1. **New file `src/comadre/health.py`** — Health response assembler. Pure data aggregation, no HTTP decorators, no FastAPI imports.
2. **New file `tests/test_health.py`** — Unit tests with mocked EngineRouter.

### What This Story Does NOT Create

- **No `main.py`** — lifespan, router mounting, and the actual `GET /health` route handler belong to Story 1.9
- **No `api.py`** — the speech endpoint is Story 1.9
- **No asyncio.Lock queue** — queue_depth tracking is Story 1.9 (health.py accepts `queue_depth` as a parameter, defaults to 0)
- **No authentication logic** — health is unauthenticated, but the auth middleware is Story 1.9

### Implementation Guidance

#### health.py Module Design

The module is a pure state assembler. It receives dependencies as parameters (no global state, no singletons). This makes testing trivial and follows the same dependency-injection pattern used in service.py.

```python
"""Health response assembler for COMADRE."""

from __future__ import annotations

import resource
import time
from enum import StrEnum

from comadre import __version__
from comadre.logging import get_logger

logger = get_logger("health")


class HealthStatus(StrEnum):
    healthy = "healthy"
    warming_up = "warming_up"
    degraded = "degraded"


def build_health_response(
    *,
    router: EngineRouter,
    ready: bool,
    start_time: float,
    queue_depth: int = 0,
) -> tuple[dict[str, object], int]:
    """Build health response dict and HTTP status code.

    Returns (response_body, status_code) tuple.
    Field order is contractual — dict insertion order is preserved in Python 3.7+.
    """
```

**Return type** is `tuple[dict[str, object], int]` — the dict body and the HTTP status code (200 or 503). The caller (main.py in Story 1.9) wraps this in a JSONResponse. This keeps health.py free of HTTP concerns.

#### Fixed Field Order (Contractual)

The dict must be constructed with keys in this exact insertion order:

```python
{
    "status": "healthy",              # HealthStatus enum value
    "voices": ["alex", "dora", ...],  # router.available_voices()
    "engines": {                      # router.engine_status()
        "kokoro": {"loaded": True, "voices": ["alex", "dora", "santa"]},
        "qwen3": {"loaded": True, "clone_configured": False, "voices": ["qwen-female", "qwen-male"]}
    },
    "queue_depth": 0,                 # passed in as parameter
    "clone_configured": False,        # from engine_status()["qwen3"]["clone_configured"]
    "uptime_seconds": 1234,           # int(time.monotonic() - start_time)
    "memory_mb": 512,                 # _get_memory_mb()
    "version": "0.1.0"               # from comadre.__version__
}
```

#### Status Logic

```python
if not ready:
    status = HealthStatus.warming_up
    status_code = 503
else:
    status = HealthStatus.healthy
    status_code = 200
```

The `degraded` status is reserved for future use (e.g., one engine loaded but the other failed). For now, only `healthy` and `warming_up` are returned.

#### Memory Reporting (_get_memory_mb)

Use `resource.getrusage(resource.RUSAGE_SELF).ru_maxrss` from stdlib. On Linux, `ru_maxrss` returns kilobytes, so divide by 1024 and round to int.

```python
def _get_memory_mb() -> int:
    """Return current process RSS in megabytes."""
    usage_kb = resource.getrusage(resource.RUSAGE_SELF).ru_maxrss
    return usage_kb // 1024
```

**DO NOT** add `psutil` as a dependency. The `resource` module is stdlib and sufficient for RSS reporting. The architecture says `memory_mb` — keep it as an int for simplicity.

#### Uptime Reporting (_get_uptime_seconds)

Use `time.monotonic()` for the start time (monotonic clock is immune to system clock changes). The caller records `start_time = time.monotonic()` at app startup and passes it in.

```python
def _get_uptime_seconds(start_time: float) -> int:
    """Return seconds since application startup."""
    return int(time.monotonic() - start_time)
```

Return as `int` — fractional seconds add noise, not value.

#### Queue Depth

Accepts `queue_depth: int = 0` as a parameter. Story 1.9 will pass the actual queue depth from the asyncio.Lock counter. For now, it defaults to 0.

#### Clone Configured

Extract from `router.engine_status()["qwen3"]["clone_configured"]`. Do NOT access `router._qwen` directly — use the public API.

### Anti-Patterns to Avoid

- **DO NOT** add `@app.get("/health")` or any FastAPI route decorator — health.py is a pure module, not an endpoint handler. The route is registered in main.py (Story 1.9).
- **DO NOT** import from `fastapi`, `starlette`, `api.py`, or `main.py` — health.py sits below them in the import graph
- **DO NOT** add `psutil` to dependencies — use `resource.getrusage` (stdlib)
- **DO NOT** use `time.time()` — use `time.monotonic()` for uptime (immune to NTP adjustments)
- **DO NOT** access `router._kokoro` or `router._qwen` directly — use `router.engine_status()` and `router.available_voices()`
- **DO NOT** add the asyncio.Lock queue or queue depth tracking — accept `queue_depth` as a parameter (Story 1.9 provides it)
- **DO NOT** add a `HealthResponse` Pydantic model — the response is a plain dict to keep field order explicit and avoid Pydantic serialization overhead. The architecture mentions `HealthResponse` in naming conventions as an example pattern, but the implementation uses a dict for field-order control
- **DO NOT** modify existing files (`service.py`, `exceptions.py`, `config.py`, `schemas.py`) — this story creates only `health.py` and `test_health.py`

### Testing Guidance

**Test file:** `tests/test_health.py`

**Pattern:** Follow the same fixtures + mocking pattern from `test_routing.py`.

```python
import time
from unittest.mock import MagicMock, patch

import pytest

from comadre.health import HealthStatus, build_health_response


@pytest.fixture()
def mock_router() -> MagicMock:
    router = MagicMock()
    router.available_voices.return_value = ["alex", "dora", "qwen-female", "qwen-male", "santa"]
    router.engine_status.return_value = {
        "kokoro": {"loaded": True, "voices": ["alex", "dora", "santa"]},
        "qwen3": {"loaded": True, "clone_configured": False, "voices": ["qwen-female", "qwen-male"]},
    }
    return router
```

**Test cases to cover:**

1. **Healthy status (200):** `ready=True` → status="healthy", status_code=200, all fields present in correct order
2. **Warming up status (503):** `ready=False` → status="warming_up", status_code=503
3. **Voices always array:** Mock `available_voices()` returning `[]` → voices field is `[]`, not None
4. **Engines field structure:** Verify kokoro and qwen3 sub-objects from `engine_status()`
5. **Clone configured:** Extract from engines.qwen3.clone_configured
6. **Version field:** Verify matches `comadre.__version__`
7. **Uptime:** Pass `start_time = time.monotonic() - 100` → uptime_seconds >= 100
8. **Memory:** Patch `resource.getrusage` → verify memory_mb is positive int
9. **Queue depth default:** No queue_depth passed → defaults to 0
10. **Queue depth custom:** Pass queue_depth=5 → reflected in response
11. **Field order:** Verify dict keys are in contractual order: status, voices, engines, queue_depth, clone_configured, uptime_seconds, memory_mb, version

**Testing memory:** Mock `resource.getrusage` to return a known value:
```python
@patch("comadre.health.resource")
def test_memory_mb(mock_resource, mock_router):
    mock_resource.getrusage.return_value.ru_maxrss = 512_000  # 512 MB in KB
    mock_resource.RUSAGE_SELF = 0
    body, _ = build_health_response(router=mock_router, ready=True, start_time=time.monotonic())
    assert body["memory_mb"] == 500  # 512000 // 1024
```

### Project Structure Notes

- `health.py` is a NEW file at `src/comadre/health.py` — matches architecture spec
- `test_health.py` is a NEW file at `tests/test_health.py` — matches architecture spec
- Import graph position: `health.py` imports from `comadre.__init__` (version), `comadre.logging` (logger). It receives `EngineRouter` as a parameter but does NOT import it (uses duck typing / Protocol or runtime type).
- For mypy strict compliance: use `TYPE_CHECKING` guard if you need the `EngineRouter` type hint, or accept a protocol/duck-typed parameter

### References

- [Source: _bmad-output/planning-artifacts/epics.md — Story 1.8 acceptance criteria, lines 384-411]
- [Source: _bmad-output/planning-artifacts/architecture.md — Module Responsibility table: health.py = "Health endpoint, runtime state aggregation"]
- [Source: _bmad-output/planning-artifacts/architecture.md — Import Dependency Graph: health.py imported by main.py, imports from schemas.py, voices.py]
- [Source: _bmad-output/planning-artifacts/architecture.md — Data Flow: GET /health → health.py aggregate → JSON 200/503]
- [Source: _bmad-output/planning-artifacts/architecture.md — Decision D4: FastAPI lifespan + health endpoint gating]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md — UX-DR2: Health Response Assembler spec]
- [Source: src/comadre/service.py — EngineRouter.engine_status() at line 739, available_voices() at line 735]
- [Source: src/comadre/__init__.py — __version__ = "0.1.0"]
- [Source: src/comadre/exceptions.py — ServiceUnavailableError class at line 95]

### Previous Story Intelligence

**From Story 1.7 (Exception Handling & Request Schemas):**
- Used starlette imports (not fastapi) for modules below main.py in import graph — same applies to health.py
- `TYPE_CHECKING` guard pattern established for FastAPI type hints
- 326 tests passed, 11 skipped. All quality gates pass (ruff, mypy strict, pytest, pre-commit).

**From Story 1.6 (Engine Router):**
- `EngineRouter.engine_status()` already returns the exact structure health.py needs
- `EngineRouter.available_voices()` returns sorted combined list excluding unconfigured clone
- Test pattern: `MagicMock` for engine instances, `@pytest.fixture()` for reusable setups

**From Story 1.4-1.5 (Engine Integration):**
- `KokoroEngine.is_loaded` and `QwenEngine.is_loaded` properties are booleans
- `QwenEngine.is_clone_configured` property checks if clone reference WAV exists
- These are already exposed through `EngineRouter.engine_status()` — no direct access needed

### Git Intelligence

Recent commits follow pattern: `Implement Story X.Y: description`. Current test suite: 326 passed, 11 skipped. All quality gates pass consistently. No psutil or external monitoring deps have been added.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

None — clean implementation, no issues encountered.

### Completion Notes List

- Implemented `src/comadre/health.py` as a pure state assembler module with no HTTP/FastAPI concerns
- `HealthStatus` StrEnum with `healthy`, `warming_up`, `degraded` values
- `build_health_response()` returns `(dict, int)` tuple with contractual field order
- `_get_memory_mb()` uses stdlib `resource.getrusage` (no psutil dependency)
- `_get_uptime_seconds()` uses `time.monotonic()` for NTP-immune uptime
- `clone_configured` extracted from `router.engine_status()["qwen3"]["clone_configured"]` (public API only)
- `queue_depth` parameter defaults to 0 (Story 1.9 provides actual value)
- TYPE_CHECKING guard for EngineRouter import (mypy strict compatible)
- 22 unit tests covering all acceptance criteria: healthy/warming_up responses, field order, voices array, engines structure, clone_configured, version, uptime, memory, queue depth, enum values
- Full test suite: 349 passed, 11 skipped. Zero regressions. ruff + mypy clean.

### Change Log

- 2026-03-24: Implemented Story 1.8 — health response assembler module and tests

### File List

- `src/comadre/health.py` (NEW) — Health response assembler module
- `tests/test_health.py` (NEW) — 22 unit tests for health module
