# Story 1.9: Speech Endpoint with Auth, Queue & Warm-up

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **n8n workflow**,
I want to call `POST /v1/audio/speech` with a bearer token and receive engine-routed audio,
so that customers hear natural voice responses on WhatsApp/Telegram.

## Acceptance Criteria

1. **Given** a valid bearer token and valid request body `{"input": "Olá", "voice": "santa", "response_format": "ogg"}` **When** I send `POST /v1/audio/speech` **Then** I receive a 200 response with `Content-Type: audio/ogg` and binary OGG Opus audio

2. **Given** a missing or invalid Authorization header **When** I send `POST /v1/audio/speech` **Then** I receive a 401 JSON error with `type: "authentication_error"` and a hint about checking the API_KEY env var

3. **Given** a request with missing `input` field **When** I send `POST /v1/audio/speech` **Then** I receive a 400 JSON error with `type: "invalid_request_error"` and a hint showing the expected request format

4. **Given** no `voice` field in the request **When** I send `POST /v1/audio/speech` **Then** the service uses the DEFAULT_VOICE from configuration (default: santa)

5. **Given** the service has just started and engines are still warming up **When** I send `POST /v1/audio/speech` **Then** I receive a 503 JSON error with `type: "service_unavailable"` and a hint to retry in N seconds

6. **Given** the FastAPI lifespan **When** the application starts **Then** it loads config, configures logging, verifies espeak-ng pt_extra dictionary, detects clone reference WAV, loads Kokoro engine, verifies Qwen3 binary, runs Kokoro warm-up, runs Qwen3 warm-up, and sets the ready flag **And** each phase is logged when it starts (startup communication pattern) **And** the final "ready" message includes the listen address

7. **Given** concurrent requests arrive **When** the single asyncio.Lock queue processes them **Then** requests are handled sequentially (FIFO) with queue depth tracked for health endpoint

8. **Given** a request is being processed **When** engine-specific timeout (120s) is exceeded **Then** the request fails with a GenerationError and the queue is released for the next request

## Tasks / Subtasks

- [x] Task 1: Create `src/cumadre/main.py` — FastAPI app, lifespan, health route, shared state (AC: #5, #6, #7)
  - [x] 1.1 Define `AppState` typed container: `router`, `settings`, `ready`, `start_time`, `queue_lock`, `queue_depth`
  - [x] 1.2 Implement `lifespan()` async context manager with 9-phase startup sequence (AC: #6)
  - [x] 1.3 Create `create_app() -> FastAPI` factory function
  - [x] 1.4 Register exception handlers via `register_exception_handlers(app)`
  - [x] 1.5 Implement `GET /health` route wrapping `build_health_response()`
  - [x] 1.6 Mount `api_router` from api.py under the app
  - [x] 1.7 Define `verify_ready` dependency that raises `ServiceUnavailableError` when `app.state.ready is False` (AC: #5)

- [x] Task 2: Create `src/cumadre/api.py` — POST /v1/audio/speech route handler (AC: #1, #2, #3, #4, #7, #8)
  - [x] 2.1 Implement `verify_api_key` FastAPI dependency using `Authorization` header (AC: #2)
  - [x] 2.2 Implement `POST /v1/audio/speech` route handler
  - [x] 2.3 Resolve default voice from `settings.default_voice` when `request.voice` is None (AC: #4)
  - [x] 2.4 Acquire `app.state.queue_lock`, increment/decrement `queue_depth` (AC: #7)
  - [x] 2.5 Call `router.generate_speech()` with `asyncio.wait_for(timeout=120)` (AC: #8)
  - [x] 2.6 Return `Response(content=audio_bytes, media_type=...)` with correct Content-Type and Content-Disposition (AC: #1)
  - [x] 2.7 Log every request at INFO level: method, path, voice, format, chars, duration (UX-DR3)

## Dev Notes

### What Already Exists (DO NOT recreate)

| Module | Key Exports Used by This Story |
|--------|-------------------------------|
| `config.py` | `Settings` class (api_key, default_voice, port, all model paths, espeak_data_path, clone_reference_path, qwen3_threads), `get_settings()` cached singleton |
| `logging.py` | `get_logger(component)` → pipe-delimited logger, `setup_logging(level)` |
| `exceptions.py` | `CumadreError` hierarchy: `AuthenticationError`, `ServiceUnavailableError(retry_seconds)`, `InvalidRequestError`, `VoiceNotFoundError`, `GenerationError`. `register_exception_handlers(app)` function. `cumadre_error_handler()`, `unhandled_error_handler()` |
| `schemas.py` | `SpeechRequest(input, voice, response_format, speed, destination)`, `ResponseFormat` enum (ogg/wav), `Destination` enum |
| `service.py` | `KokoroEngine` (.load_model(), .warm_up(), .generate_speech(), .is_loaded), `QwenEngine` (.load_model(), .warm_up(), .generate_speech(), .is_loaded, .is_clone_configured), `EngineRouter(kokoro, qwen)` (.generate_speech(), .available_voices(), .engine_status()) |
| `health.py` | `build_health_response(router=, ready=, start_time=, queue_depth=) -> tuple[dict, int]`, `HealthStatus` enum |
| `voices.py` | `discover_voices(voices_dir)` → list of VoiceInfo (name, path, duration_seconds) |
| `preprocessing.py` | Used internally by engines — not directly called by api.py |
| `__init__.py` | `__version__ = "0.1.0"` |

### What This Story Creates

1. **New file `src/cumadre/main.py`** — FastAPI application factory, lifespan context manager, health endpoint, shared state management
2. **New file `src/cumadre/api.py`** — Speech endpoint route handler with auth dependency, queue management, response formatting

### What This Story Does NOT Create

- **No test files** — Story 1.10 creates `tests/test_api.py` and updates `tests/conftest.py` with async client fixtures
- **No Dockerfile** — Epic 2 (Story 2.1)
- **No compose.yaml** — Epic 2 (Story 2.2)
- **No entrypoint.sh** — Epic 2 (Story 2.1)

### Implementation Guidance

#### main.py Module Design

The module is the application entry point. It creates the FastAPI app, manages lifespan (startup/shutdown), registers exception handlers, and mounts the health endpoint and api router. NO business logic — it orchestrates other modules.

**Import graph position:** main.py is the TOP of the import graph. It imports from api.py, health.py, config.py, logging.py, exceptions.py, service.py, and voices.py. Nothing imports from main.py.

```python
"""CUMADRE FastAPI application entry point."""

from __future__ import annotations

import asyncio
import time
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from typing import Any

from fastapi import FastAPI, Request
from fastapi.responses import JSONResponse

from cumadre.api import api_router
from cumadre.config import Settings, get_settings
from cumadre.exceptions import ServiceUnavailableError, register_exception_handlers
from cumadre.health import build_health_response
from cumadre.logging import get_logger, setup_logging
from cumadre.service import EngineRouter, KokoroEngine, QwenEngine

logger = get_logger("startup")
```

#### Lifespan — 9-Phase Startup Sequence (AC #6)

Each phase MUST log when it starts. Failure at any phase = log CRIT + exit (don't start half-broken). The `ready` flag is only set after ALL phases complete. UX-DR8 requires sequential phase logging.

```python
@asynccontextmanager
async def lifespan(app: FastAPI) -> AsyncIterator[None]:
    settings = get_settings()
    start_time = time.monotonic()

    # Phase 1: Load config (already done via get_settings)
    logger.info("Configuration loaded")

    # Phase 2: Configure structured logging
    setup_logging()
    logger.info("Structured logging configured")

    # Phase 3: Verify espeak-ng pt_extra data
    logger.info("Verifying espeak-ng pt_extra dictionary...")
    # Log verification result (file existence check at espeak_data_path if set)

    # Phase 4: Detect clone reference WAV
    logger.info("Detecting clone reference WAV...")
    # Log whether clone reference exists at settings.clone_reference_path

    # Phase 5: Load Kokoro model
    logger.info("Loading Kokoro TTS model...")
    kokoro = KokoroEngine()
    kokoro.load_model(
        model_path=settings.kokoro_model_path,
        voices_path=settings.kokoro_voices_path,
        espeak_data_path=settings.espeak_data_path,
    )

    # Phase 6: Verify Qwen3 binary
    logger.info("Verifying qwen3-tts-cli binary...")
    qwen = QwenEngine()
    qwen.load_model(
        cli_path=settings.qwen3_cli_path,
        model_path=settings.qwen3_model_path,
        tokenizer_path=settings.qwen3_tokenizer_path,
        female_reference_path=settings.qwen3_female_reference_path,
        male_reference_path=settings.qwen3_male_reference_path,
        clone_reference_path=settings.clone_reference_path,
        threads=settings.qwen3_threads,
    )

    # Phase 7: Warm up Kokoro
    logger.info("Warming up Kokoro engine...")
    kokoro.warm_up()

    # Phase 8: Warm up Qwen3
    logger.info("Warming up Qwen3 engine...")
    qwen.warm_up()

    # Phase 9: Ready
    router = EngineRouter(kokoro=kokoro, qwen=qwen)
    app.state.router = router
    app.state.settings = settings
    app.state.start_time = start_time
    app.state.queue_lock = asyncio.Lock()
    app.state.queue_depth = 0
    app.state.ready = True

    logger.info("Service ready on port %d", settings.port)

    yield

    # Shutdown
    logger.info("Shutting down...")
```

**CRITICAL:** Set `app.state.ready = False` before the lifespan `yield` if any setup phase needs it. Initialize the state attributes (especially `ready = False`) BEFORE the startup phases begin, so the health endpoint and readiness check work correctly during startup. The pattern:

```python
# Initialize state EARLY (before engine loading)
app.state.ready = False
app.state.queue_lock = asyncio.Lock()
app.state.queue_depth = 0
app.state.start_time = time.monotonic()
app.state.settings = settings

# ... phases 3-8 ...

# Set ready LAST
app.state.ready = True
```

This ensures `GET /health` returns 503/warming_up during the entire startup window.

#### Health Endpoint (in main.py)

The health endpoint is registered directly in main.py (not in api.py) because it has no auth requirement and a different concern boundary.

```python
@app.get("/health")
async def health_endpoint(request: Request) -> JSONResponse:
    body, status_code = build_health_response(
        router=request.app.state.router,
        ready=request.app.state.ready,
        start_time=request.app.state.start_time,
        queue_depth=request.app.state.queue_depth,
    )
    return JSONResponse(content=body, status_code=status_code)
```

**IMPORTANT:** The health endpoint must work DURING startup (returning 503). This means `app.state.router` must be initialized before the health endpoint can respond. Two approaches:
- Option A: Initialize a "bare" EngineRouter early and replace it after loading (complex, fragile)
- Option B: Handle the case where `app.state.router` might not exist yet — return a minimal warming_up response

**Recommended: Option B.** If `app.state.ready` is False and `router` is not yet available, return a hardcoded warming_up response. The health endpoint should NEVER crash.

```python
@app.get("/health")
async def health_endpoint(request: Request) -> JSONResponse:
    if not getattr(request.app.state, "ready", False):
        # During startup, router may not exist yet
        router = getattr(request.app.state, "router", None)
        if router is None:
            return JSONResponse(
                content={
                    "status": "warming_up",
                    "voices": [],
                    "engines": {},
                    "queue_depth": 0,
                    "clone_configured": False,
                    "uptime_seconds": 0,
                    "memory_mb": 0,
                    "version": __version__,
                },
                status_code=503,
            )
    body, status_code = build_health_response(
        router=request.app.state.router,
        ready=request.app.state.ready,
        start_time=request.app.state.start_time,
        queue_depth=request.app.state.queue_depth,
    )
    return JSONResponse(content=body, status_code=status_code)
```

#### create_app() Factory

```python
def create_app() -> FastAPI:
    app = FastAPI(
        title="CUMADRE",
        version=__version__,
        lifespan=lifespan,
    )
    register_exception_handlers(app)
    app.include_router(api_router)
    return app
```

The factory pattern is essential for testability — Story 1.10 will import `create_app()` and override state for testing.

#### api.py Module Design

The module contains the speech route handler. It owns the asyncio.Lock acquire/release and queue depth tracking. NO model loading, NO audio encoding — it delegates to `EngineRouter.generate_speech()`.

**Import graph position:** api.py imports from schemas.py, exceptions.py, config.py, logging.py, service.py. It is imported by main.py only.

```python
"""Speech endpoint route handler for CUMADRE."""

from __future__ import annotations

import asyncio
import time
from typing import TYPE_CHECKING

from fastapi import APIRouter, Depends, Header, Request, Response

from cumadre.exceptions import (
    AuthenticationError,
    GenerationError,
    ServiceUnavailableError,
)
from cumadre.logging import get_logger
from cumadre.schemas import ResponseFormat, SpeechRequest

if TYPE_CHECKING:
    pass

logger = get_logger("request")

api_router = APIRouter()
```

#### Auth Dependency — verify_api_key (AC #2)

FastAPI dependency injection function. Checks `Authorization: Bearer <token>` against `settings.api_key`.

```python
async def verify_api_key(
    request: Request,
    authorization: str = Header(default=""),
) -> None:
    """Validate bearer token against configured API key."""
    settings = request.app.state.settings
    if not authorization.startswith("Bearer "):
        raise AuthenticationError("Missing or malformed Authorization header")
    token = authorization.removeprefix("Bearer ")
    if token != settings.api_key.get_secret_value():
        raise AuthenticationError()
```

**AuthenticationError constructor (verified from exceptions.py):**
- Signature: `__init__(self, message: str = "Invalid or missing API key") -> None`
- Hint is **hardcoded**: `"Check the API_KEY environment variable and ensure your Authorization header uses 'Bearer <key>'."`
- The hardcoded hint already satisfies AC #2 ("hint about checking the API_KEY env var")
- Only `message` can be customized — the hint cannot be overridden without modifying exceptions.py
- Use `AuthenticationError()` for default message, or `AuthenticationError("Missing or malformed Authorization header")` for specific cases

#### Readiness Dependency — verify_ready (AC #5)

```python
async def verify_ready(request: Request) -> None:
    """Reject requests during startup warm-up."""
    if not getattr(request.app.state, "ready", False):
        raise ServiceUnavailableError(
            message="Service is warming up, engines not yet loaded",
            retry_seconds=30,
        )
```

**ServiceUnavailableError constructor (verified from exceptions.py):**
- Signature: `__init__(self, message: str = "Service is warming up", *, retry_seconds: int = 30)`
- Hint is auto-generated: `"The service is still loading models. Retry in {retry_seconds} seconds."`
- `raise ServiceUnavailableError()` uses all defaults — sufficient for AC #5

#### Speech Route Handler (AC #1, #3, #4, #7, #8)

```python
@api_router.post(
    "/v1/audio/speech",
    dependencies=[Depends(verify_ready), Depends(verify_api_key)],
)
async def generate_speech(
    request: Request,
    body: SpeechRequest,
) -> Response:
    """Generate speech audio from text input."""
    settings = request.app.state.settings
    router = request.app.state.router
    queue_lock = request.app.state.queue_lock

    # Resolve default voice (AC #4)
    voice = body.voice or settings.default_voice

    # Determine media type
    media_type = (
        "audio/ogg" if body.response_format == ResponseFormat.ogg else "audio/wav"
    )
    extension = body.response_format.value

    start = time.monotonic()

    # Acquire FIFO queue (AC #7)
    request.app.state.queue_depth += 1
    try:
        async with queue_lock:
            # Generate with timeout (AC #8)
            try:
                audio_bytes = await asyncio.wait_for(
                    asyncio.to_thread(
                        router.generate_speech,
                        text=body.input,
                        voice_name=voice,
                        response_format=body.response_format.value,
                    ),
                    timeout=120.0,
                )
            except TimeoutError:
                raise GenerationError(
                    message=f"Speech generation timed out after 120 seconds for voice '{voice}'"
                )
    finally:
        request.app.state.queue_depth -= 1

    duration = time.monotonic() - start
    logger.info(
        "POST /v1/audio/speech voice=%s format=%s chars=%d duration=%.1fs",
        voice,
        extension,
        len(body.input),
        duration,
    )

    return Response(
        content=audio_bytes,
        media_type=media_type,
        headers={
            "Content-Disposition": f'attachment; filename="speech.{extension}"',
        },
    )
```

**CRITICAL — asyncio.to_thread:** `EngineRouter.generate_speech()` is a synchronous method (it calls Kokoro's sync ONNX inference and Qwen3's subprocess). Wrap it in `asyncio.to_thread()` so the FIFO Lock doesn't block the event loop. This allows the health endpoint and other non-queued requests to respond while generation is running.

**Queue depth tracking:** Increment `queue_depth` BEFORE acquiring the lock (it counts waiting + active requests). Decrement in `finally` to ensure it's always decremented even on error. This gives the health endpoint an accurate count of how many requests are queued.

**Timeout handling (AC #8):** `asyncio.wait_for()` raises `TimeoutError` (Python 3.11+) when exceeded. Catch it and re-raise as `GenerationError` for consistent error formatting via the exception handler.

#### Pydantic Validation Error Handling (AC #3)

FastAPI automatically returns 422 for Pydantic validation errors (missing fields, wrong types). The architecture requires 400 with `type: "invalid_request_error"` instead.

Register a **RequestValidationError** handler in `main.py` (or add it to `register_exception_handlers`):

```python
from fastapi.exceptions import RequestValidationError

async def validation_error_handler(
    request: Request, exc: RequestValidationError
) -> JSONResponse:
    return JSONResponse(
        status_code=400,
        content={
            "error": {
                "message": "Invalid request body",
                "type": "invalid_request_error",
                "hint": str(exc.errors()),
            }
        },
    )
```

**Decision:** Either add this handler in main.py after `register_exception_handlers()`, or add it inside `register_exception_handlers()` in exceptions.py. Adding it in main.py keeps exceptions.py unchanged (previous story created it). Adding it to exceptions.py is architecturally cleaner. **Prefer adding to main.py** to avoid modifying a file from a previous story unless necessary.

Wait — actually check if `register_exception_handlers()` already handles `RequestValidationError`. If not, this MUST be added. The AC says "400 JSON error with type: invalid_request_error" — FastAPI's default is 422, which violates the spec.

### Anti-Patterns to Avoid

- **DO NOT** add business logic to main.py — it orchestrates, not implements
- **DO NOT** import FastAPI or Starlette types in service.py, health.py, or preprocessing.py — import graph flows downward only
- **DO NOT** use `os.environ` — use `get_settings()` / `request.app.state.settings`
- **DO NOT** raise raw `HTTPException` — use `CumadreError` subclasses exclusively
- **DO NOT** use `print()` — use `get_logger(component)` for structured logging
- **DO NOT** create a `HealthResponse` Pydantic model — health uses plain dict for field-order control
- **DO NOT** add global state (module-level variables for router, lock, etc.) — use `app.state` exclusively
- **DO NOT** add `psutil`, `aiofiles`, or any other new dependency — everything needed is already in pyproject.toml
- **DO NOT** add retry logic inside the request path — fail fast, let the caller retry
- **DO NOT** call `router._kokoro` or `router._qwen` directly — use public methods only
- **DO NOT** create tests — Story 1.10 handles all test creation
- **DO NOT** modify existing modules (service.py, health.py, config.py, schemas.py, etc.) unless strictly required to fix an integration issue discovered during implementation. If modification is needed, document it clearly in the completion notes.

### Testing Guidance

**Story 1.9 does NOT create tests.** Story 1.10 will create:
- `tests/test_api.py` — auth, validation, success paths, engine routing, error codes
- Updated `tests/conftest.py` — AsyncClient fixture via httpx, mock settings, temp voice dir

However, you MUST verify the app works by running:
```bash
uv run ruff check src/cumadre/main.py src/cumadre/api.py
uv run mypy src/cumadre/main.py src/cumadre/api.py
uv run pytest  # All existing tests must still pass (349 passed, 11 skipped)
```

### Project Structure Notes

- `main.py` is a NEW file at `src/cumadre/main.py` — top of import graph
- `api.py` is a NEW file at `src/cumadre/api.py` — imported only by main.py
- Both files MUST pass mypy strict mode and ruff checks
- `main.py` imports from: `api`, `config`, `exceptions`, `health`, `logging`, `service`
- `api.py` imports from: `exceptions`, `logging`, `schemas`. Uses `request.app.state` for runtime dependencies
- Neither file should be imported by any existing module (they are at the top of the graph)

### References

- [Source: _bmad-output/planning-artifacts/epics.md — Story 1.9 acceptance criteria, lines 412-452]
- [Source: _bmad-output/planning-artifacts/architecture.md — Module Responsibility: main.py = "FastAPI app creation, lifespan, router mounting", api.py = "Route handlers for /v1/audio/speech"]
- [Source: _bmad-output/planning-artifacts/architecture.md — Import Dependency Graph: main.py imports api.py, health.py; api.py imports schemas.py, exceptions.py, service.py]
- [Source: _bmad-output/planning-artifacts/architecture.md — Startup Sequence (lifespan): 9-phase startup, lines 672-690]
- [Source: _bmad-output/planning-artifacts/architecture.md — Request Processing: 10-step flow, lines 692-711]
- [Source: _bmad-output/planning-artifacts/architecture.md — Data Flow: n8n POST → api.py → service.py → engine → response, lines 953-991]
- [Source: _bmad-output/planning-artifacts/architecture.md — Decision D3: asyncio.Lock FIFO queue]
- [Source: _bmad-output/planning-artifacts/architecture.md — Decision D4: FastAPI lifespan + health endpoint gating]
- [Source: _bmad-output/planning-artifacts/architecture.md — Auth: Bearer token, dependency injection, line 374]
- [Source: _bmad-output/planning-artifacts/architecture.md — Error format: message + type + hint, always all three fields, lines 600-606]
- [Source: _bmad-output/planning-artifacts/prd.md — Endpoint specs: POST /v1/audio/speech, GET /health, lines 157-173]
- [Source: _bmad-output/planning-artifacts/prd.md — Error codes: 200, 400, 401, 404, 500, 503, lines 235-244]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md — UX-DR1: Error Response Builder with type vocabulary]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md — UX-DR8: Startup Communication Pattern — sequential phase logging]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md — UX-DR3: Request logging with method, path, voice, format, chars, duration]
- [Source: src/cumadre/config.py — Settings class with api_key, default_voice, all model paths]
- [Source: src/cumadre/exceptions.py — CumadreError hierarchy, register_exception_handlers()]
- [Source: src/cumadre/schemas.py — SpeechRequest model, ResponseFormat enum]
- [Source: src/cumadre/service.py — EngineRouter, KokoroEngine, QwenEngine]
- [Source: src/cumadre/health.py — build_health_response() signature]

### Previous Story Intelligence

**From Story 1.8 (Health Endpoint):**
- `build_health_response()` returns `tuple[dict[str, Any], int]` — body dict and status code. The caller wraps in JSONResponse.
- `queue_depth` parameter defaults to 0 — Story 1.9 passes the actual value from `app.state.queue_depth`.
- `start_time` should use `time.monotonic()` — same clock as health.py internals.
- TYPE_CHECKING guard pattern for imports that are only needed for type annotations.
- Test suite: 349 passed, 11 skipped. All quality gates pass.

**From Story 1.7 (Exception Handling & Request Schemas):**
- `register_exception_handlers(app)` installs CumadreError handler + unhandled exception handler.
- `AuthenticationError(message="...")` — check if it accepts `hint` param. Default hint is `"Check the API_KEY environment variable."`.
- `ServiceUnavailableError(message="...", retry_seconds=30)` — hint auto-generated.
- `SpeechRequest.voice` is `str | None = None` — None means use default voice.
- `SpeechRequest._validate_char_limit()` checks per-engine char limits (500 Kokoro, 300 Qwen3).
- Used starlette Request import (not fastapi.Request) for modules below main.py. For api.py, importing `from fastapi import Request` is correct since api.py is allowed to have HTTP concerns.

**From Story 1.6 (Engine Router):**
- `EngineRouter.generate_speech(text, voice_name, response_format, noise_dir, seed)` — synchronous method. MUST wrap in `asyncio.to_thread()` in the async route handler.
- Voice resolution and engine dispatch happen inside `generate_speech()` — api.py just passes the voice name.
- `VoiceNotFoundError` is raised by the router if voice is not recognized — no need to validate voice in api.py.

**From Story 1.5 (Qwen3 Engine):**
- `QwenEngine.load_model()` verifies the binary exists and model files are accessible. Raises `GenerationError` if binary is not found.
- `QwenEngine.warm_up()` runs a short dummy text through the full pipeline.

**From Story 1.4 (Kokoro Engine):**
- `KokoroEngine.load_model()` downloads models if not present (HuggingFace).
- `KokoroEngine.warm_up()` runs a short dummy text through full pipeline including post-processing.

### Git Intelligence

Recent commit pattern: `Implement Story X.Y: description`. Current test suite: 349 passed, 11 skipped. All quality gates pass (ruff, mypy strict, pytest, pre-commit). No new dependencies added recently. The codebase is clean and ready for the application entry point.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

None — clean implementation with no debugging required.

### Completion Notes List

- **Task 1 (main.py):** Created FastAPI application entry point with 9-phase lifespan startup sequence. State is initialized early (ready=False) so health endpoint works during startup. Health endpoint returns hardcoded 503/warming_up when router is not yet available, and delegates to `build_health_response()` once router exists. Added `RequestValidationError` handler to convert FastAPI's default 422 to 400 with `invalid_request_error` type (AC #3). Factory pattern via `create_app()` for testability.
- **Task 1.7 (verify_ready):** Placed in `api.py` instead of `main.py` to preserve import graph direction (nothing imports from main.py). Uses `getattr` with default for safe access during startup.
- **Task 2 (api.py):** Created speech route handler with auth dependency, FIFO queue management, and 120s timeout. `verify_api_key` checks Bearer token against `settings.api_key`. `queue_depth` incremented before lock acquisition (counts waiting + active). `asyncio.to_thread()` wraps sync `generate_speech()` to avoid blocking the event loop.
- **Integration fix:** Changed `config.py` `default_voice` from `"default"` to `"santa"` — "default" is not a valid voice name and would cause VoiceNotFoundError. AC #4 specifies "default: santa". Updated corresponding test assertion.

### Change Log

- 2026-03-24: Story 1.9 implementation complete — created main.py, api.py; fixed default_voice in config.py

### File List

- `src/cumadre/main.py` — NEW: FastAPI app factory, lifespan, health endpoint, validation error handler
- `src/cumadre/api.py` — NEW: Speech route handler, auth dependency, readiness dependency, queue management
- `src/cumadre/config.py` — MODIFIED: Changed default_voice from "default" to "santa" (integration fix)
- `tests/test_config.py` — MODIFIED: Updated test assertion for new default_voice value
