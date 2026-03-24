# Story 1.10: API & Health Tests

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **developer**,
I want automated tests covering auth, validation, success paths, engine routing, and health states,
so that regressions are caught before deployment.

## Acceptance Criteria

1. **Given** the test suite **When** I run `uv run pytest` **Then** all tests pass using mocked engines (no real model loading for both Kokoro and Qwen3)

2. **Given** conftest.py **When** tests use the test client **Then** it provides a FastAPI AsyncClient via httpx, mock settings, and mock router fixtures

3. **Given** test_api.py **When** I review the test coverage **Then** it tests: valid request returns audio, missing auth returns 401, malformed request returns 400, missing voice returns 404, service warming up returns 503

4. **Given** test_routing.py **When** I review the test coverage **Then** it tests: Kokoro voices route to Kokoro engine, Qwen3 voices route to Qwen3 engine, unknown voice returns VoiceNotFoundError, correct preprocessing pipeline per engine, correct post-processing pipeline per engine

5. **Given** test_health.py **When** I review the test coverage **Then** it tests: healthy status returns 200 with all fields including engines and queue_depth, warming_up status returns 503, voices array reflects discovered voices, clone_configured reflects clone reference state, health requires no authentication

6. **Given** test_queue.py **When** I review the test coverage **Then** it tests: sequential processing under asyncio.Lock, queue depth increments and decrements correctly

## Tasks / Subtasks

- [x] Task 1: Enhance `tests/conftest.py` — shared fixtures for HTTP-level testing (AC: #1, #2)
  - [x] 1.1 Add `mock_settings` fixture returning a `Settings` instance with a known `api_key` and defaults
  - [x] 1.2 Add `app` fixture that calls `create_app()`, skips lifespan, and wires `app.state` with mocked router, settings, queue_lock, queue_depth, ready=True, start_time
  - [x] 1.3 Add `client` async fixture returning `httpx.AsyncClient(transport=ASGITransport(app=app))` for HTTP-level tests
  - [x] 1.4 Add `auth_headers` fixture returning `{"Authorization": "Bearer test-key"}` matching mock_settings
  - [x] 1.5 Add `mock_router` fixture returning a MagicMock with `generate_speech` returning `b"fake-audio"`, `available_voices` returning sorted voice list, `engine_status` returning proper structure

- [x] Task 2: Create `tests/test_api.py` — speech endpoint HTTP tests (AC: #3)
  - [x] 2.1 Test valid request returns 200 with `Content-Type: audio/ogg` and binary body
  - [x] 2.2 Test missing Authorization header returns 401 with `type: "authentication_error"`
  - [x] 2.3 Test invalid Bearer token returns 401 with `type: "authentication_error"`
  - [x] 2.4 Test missing `input` field returns 400 with `type: "invalid_request_error"`
  - [x] 2.5 Test empty `input` field returns 400 with `type: "invalid_request_error"`
  - [x] 2.6 Test unknown voice returns 404 with `type: "not_found_error"` (mock router raises VoiceNotFoundError)
  - [x] 2.7 Test service warming up returns 503 with `type: "service_unavailable"` and `Retry-After` header
  - [x] 2.8 Test default voice resolution — request without `voice` field uses `settings.default_voice`
  - [x] 2.9 Test Content-Disposition header includes filename with correct extension
  - [x] 2.10 Test WAV format request returns `Content-Type: audio/wav`

- [x] Task 3: Add preprocessing/post-processing pipeline tests to `tests/test_routing.py` (AC: #4)
  - [x] 3.1 Test Kokoro `generate_speech` calls `normalize_text()` then `chunk_text()` on the input
  - [x] 3.2 Test Kokoro `generate_speech` calls `_apply_vibrato_warm()` on the generated audio
  - [x] 3.3 Test Qwen3 `generate_speech` calls `expand_siglas()` on the input
  - [x] 3.4 Test Qwen3 `generate_speech` calls `_apply_whatsapp_subtle()` on the generated audio

- [x] Task 4: Add HTTP-level health endpoint tests to `tests/test_health.py` (AC: #5)
  - [x] 4.1 Test `GET /health` returns 200 with all required fields when ready
  - [x] 4.2 Test `GET /health` returns 503 with `status: "warming_up"` when not ready (router=None)
  - [x] 4.3 Test `GET /health` requires no authentication (no Authorization header needed)
  - [x] 4.4 Test voices array in health response reflects mock router's available voices
  - [x] 4.5 Test clone_configured reflects clone reference state

- [x] Task 5: Create `tests/test_queue.py` — queue behavior tests (AC: #6)
  - [x] 5.1 Test sequential processing: two concurrent requests are processed one at a time under asyncio.Lock
  - [x] 5.2 Test queue depth increments when request is waiting/active and decrements after completion
  - [x] 5.3 Test queue depth decrements even when generation raises an error (finally block)

- [x] Task 6: Verify all quality gates pass (AC: #1)
  - [x] 6.1 Run `uv run pytest` — all tests pass (existing + new)
  - [x] 6.2 Run `uv run ruff check .` — no lint errors
  - [x] 6.3 Run `uv run mypy src/` — strict mode passes

## Dev Notes

### What Already Exists (DO NOT recreate or rewrite)

| File | Status | What It Tests |
|------|--------|---------------|
| `tests/conftest.py` | EXISTS — needs enhancement | Currently only registers `slow` marker. Story 1.10 adds AsyncClient fixtures, mock settings, mock router |
| `tests/test_health.py` | EXISTS — needs enhancement | Tests `build_health_response()` at function level (250 lines, 16 tests). Story 1.10 adds HTTP-level `/health` endpoint tests as a new class |
| `tests/test_routing.py` | EXISTS — needs enhancement | Tests `EngineRouter` at class level (247 lines, 18 tests). Story 1.10 adds preprocessing/post-processing pipeline verification tests |
| `tests/test_api.py` | DOES NOT EXIST | Story 1.10 creates this file — HTTP-level speech endpoint tests |
| `tests/test_queue.py` | DOES NOT EXIST | Story 1.10 creates this file — asyncio.Lock queue behavior tests |

**Other existing test files (DO NOT modify):**
- `tests/test_config.py` — Settings tests (36 tests)
- `tests/test_exceptions.py` — CumadreError hierarchy tests (29 tests)
- `tests/test_schemas.py` — SpeechRequest validation tests (21 tests)
- `tests/test_preprocessing.py` — normalize_text, chunk_text, expand_siglas tests
- `tests/test_service.py` — KokoroEngine, QwenEngine unit tests
- `tests/test_logging.py` — Structured logging tests
- `tests/test_voices.py` — Voice discovery tests
- `tests/test_feasibility.py` — Feasibility tests

### Key Source Files Being Tested

**`src/cumadre/main.py` (174 lines):**
- `create_app()` — FastAPI factory. Import this for test app creation.
- `lifespan()` — DO NOT run in tests. Tests must skip lifespan and manually set `app.state`.
- `health_endpoint()` — inline route at `GET /health`. Returns hardcoded 503 when `router` is None, delegates to `build_health_response()` otherwise.
- `validation_error_handler()` — converts FastAPI 422 to 400 with `invalid_request_error` type.

**`src/cumadre/api.py` (112 lines):**
- `verify_api_key(request, authorization)` — checks `Bearer <token>` against `settings.api_key.get_secret_value()` using `hmac.compare_digest()`. Raises `AuthenticationError`.
- `verify_ready(request)` — checks `request.app.state.ready`. Raises `ServiceUnavailableError(retry_seconds=30)`.
- `generate_speech(request, body)` — speech route handler. Uses `app.state.queue_lock`, `app.state.queue_depth`, `app.state.router.generate_speech()`.

**`src/cumadre/exceptions.py` (150 lines):**
- `cumadre_error_handler()` — returns JSON with `{"error": {"message", "type", "hint"}}`. Adds `Retry-After` header for `ServiceUnavailableError`.
- Exception handlers are registered via `register_exception_handlers(app)` inside `create_app()`.

### Implementation Guidance

#### conftest.py Fixtures (Task 1)

The test app must NOT run `lifespan()` (it loads real models). Instead, create the app and manually populate `app.state`:

```python
import asyncio
from unittest.mock import MagicMock

import pytest
from httpx import ASGITransport, AsyncClient
from pydantic import SecretStr

from cumadre.config import Settings
from cumadre.main import create_app

TEST_API_KEY = "test-key-12345"

@pytest.fixture()
def mock_settings() -> Settings:
    return Settings(api_key=SecretStr(TEST_API_KEY))

@pytest.fixture()
def mock_router() -> MagicMock:
    router = MagicMock()
    router.generate_speech.return_value = b"fake-audio-bytes"
    router.available_voices.return_value = [
        "alex", "dora", "qwen-female", "qwen-male", "santa",
    ]
    router.engine_status.return_value = {
        "kokoro": {"loaded": True, "voices": ["alex", "dora", "santa"]},
        "qwen3": {
            "loaded": True,
            "clone_configured": False,
            "voices": ["qwen-female", "qwen-male"],
        },
    }
    return router
```

**CRITICAL — Skipping lifespan:** Use `create_app()` but override `app.router.lifespan_context` or set state after creation. The simplest approach: create the app, then manually set all `app.state.*` attributes before passing to AsyncClient. FastAPI's `TestClient` runs lifespan by default — use `httpx.AsyncClient(transport=ASGITransport(app=app))` with lifespan="off" to avoid this.

**CRITICAL — AsyncClient setup:** httpx's `ASGITransport` does NOT run lifespan by default. Use `base_url="http://test"` (arbitrary, not a real URL):

```python
@pytest.fixture()
async def client(app):
    async with AsyncClient(
        transport=ASGITransport(app=app),
        base_url="http://test",
    ) as c:
        yield c
```

**CRITICAL — conftest.py must preserve existing marker registration.** Add fixtures BELOW the existing `pytest_configure` function.

#### test_api.py Design (Task 2)

Organize as classes mirroring the AC scenarios:

```
class TestSpeechSuccess        # AC #3: valid request → 200
class TestSpeechAuth           # AC #3: missing/invalid auth → 401
class TestSpeechValidation     # AC #3: malformed request → 400
class TestSpeechNotFound       # AC #3: missing voice → 404
class TestSpeechWarmUp         # AC #3: warming up → 503
```

All tests use the async client and mock router. The mock router's `generate_speech` returns `b"fake-audio-bytes"` for success cases. For 404, make mock router's `generate_speech` raise `VoiceNotFoundError`.

**For warming up (503):** Create a separate fixture/app where `app.state.ready = False`. The `verify_ready` dependency checks this and raises `ServiceUnavailableError` before auth is even checked. Verify the response includes `Retry-After` header.

**For validation errors (400):** Send requests with missing `input` field, empty body `{}`, or `input: ""`. FastAPI converts these to 422, but `validation_error_handler` converts to 400. Verify response has `type: "invalid_request_error"`.

**Request body for valid test:**
```python
{"input": "Hello world", "voice": "santa", "response_format": "ogg"}
```

**Auth header format:** `Authorization: Bearer test-key-12345`

#### test_routing.py Enhancements (Task 3)

The existing `test_routing.py` tests EngineRouter at the class level. AC4 requires additional tests for preprocessing and post-processing pipelines.

**Preprocessing pipeline tests:** Use `unittest.mock.patch` to verify that:
- `KokoroEngine.generate_speech()` calls `normalize_text()` then `chunk_text()` (in that order)
- `QwenEngine.generate_speech()` calls `expand_siglas()` (not normalize_text)

**Post-processing pipeline tests:** Use `unittest.mock.patch` to verify that:
- `KokoroEngine.generate_speech()` calls `_apply_vibrato_warm()` on the result
- `QwenEngine.generate_speech()` calls `_apply_whatsapp_subtle()` on the result

These tests need deeper mocking since `generate_speech()` on the engines calls internal functions. Patch at module level:
```python
@patch("cumadre.service._apply_vibrato_warm", return_value=b"processed")
@patch("cumadre.service._concatenate_wavs", return_value=b"concat-wav")
@patch("cumadre.service._samples_to_wav", return_value=b"wav-data")
def test_kokoro_uses_vibrato_warm_pipeline(mock_wav, mock_concat, mock_vibrato, kokoro):
    kokoro._kokoro.create.return_value = (np.zeros(100), 24000)
    kokoro.generate_speech("test", "santa", "ogg")
    mock_vibrato.assert_called_once()
```

**Add these as new test classes at the bottom of the existing file.** Do NOT modify existing tests.

#### test_health.py Enhancements (Task 4)

Add a new class `TestHealthHTTPEndpoint` at the bottom of the existing file. This class tests the `/health` endpoint via HTTP using the async client from conftest.py.

**Key tests:**
- `GET /health` with no auth header → 200 (proves no auth required)
- `GET /health` when `app.state.ready=True` → 200 with all fields
- `GET /health` when `app.state.ready=False, router=None` → 503 with warming_up status

**Import the async client fixture from conftest.py.** Mark tests as `@pytest.mark.anyio` or `@pytest.mark.asyncio` depending on which async test plugin is configured.

#### test_queue.py Design (Task 5)

Test the queue behavior at the application level using the async client.

**Sequential processing test:** Send two requests concurrently. Mock `router.generate_speech` with a side effect that records call order and uses `asyncio.Event` to control timing. Verify requests are processed sequentially (not in parallel).

**Queue depth test:** Mock `router.generate_speech` to capture `app.state.queue_depth` during execution. Verify depth is 1 during processing and 0 after.

**Error queue depth test:** Mock `router.generate_speech` to raise `GenerationError`. Verify `queue_depth` returns to 0 after the error.

### Anti-Patterns to Avoid

- **DO NOT** load real models — ALL tests use mocked engines/router
- **DO NOT** run the actual lifespan — manually set `app.state.*`
- **DO NOT** test Pydantic validation directly — that's already covered in test_schemas.py (21 tests)
- **DO NOT** test the exception hierarchy directly — that's already covered in test_exceptions.py (29 tests)
- **DO NOT** test `build_health_response()` function directly — that's already covered in the existing test_health.py (16 tests). Only add HTTP-level endpoint tests.
- **DO NOT** rewrite or reorganize existing test files — only ADD new classes/functions
- **DO NOT** add `psutil`, `aiofiles`, `pytest-httpx`, or any new test dependency — use `httpx` (already in dev deps), `pytest`, `pytest-asyncio` or `anyio`
- **DO NOT** use `TestClient` from FastAPI (sync) — use `httpx.AsyncClient` with `ASGITransport` (async)
- **DO NOT** test framework behavior (e.g., that FastAPI calls dependencies) — test OUR logic only
- **DO NOT** add `print()` statements in tests — use assertions

### Async Test Configuration

**Confirmed from pyproject.toml:**
- `pytest-asyncio>=0.25` is in test dependencies
- `asyncio_mode = "auto"` is set — all `async def test_*` functions are automatically detected as async tests. **No `@pytest.mark.asyncio` decorator needed.**
- `httpx>=0.28` is in test dependencies — use `httpx.AsyncClient` with `ASGITransport`
- `testpaths = ["tests"]`

### Error Response Contract

All error responses follow this format (verified from exceptions.py):

```json
{
  "error": {
    "message": "Human-readable description",
    "type": "error_type_slug",
    "hint": "Actionable recovery guidance"
  }
}
```

**Error type vocabulary:**
| Status | type | Trigger |
|--------|------|---------|
| 401 | `authentication_error` | Missing/invalid Bearer token |
| 400 | `invalid_request_error` | Pydantic validation failure (422→400 conversion) |
| 404 | `not_found_error` | Unknown voice name |
| 503 | `service_unavailable` | `app.state.ready=False` during startup |
| 500 | `server_error` | Generation timeout, unhandled errors |

**503 response includes `Retry-After: 30` header** (from ServiceUnavailableError handler).

### Project Structure Notes

- New files go in `tests/` alongside existing test files
- conftest.py fixtures are automatically available to all test files in the same directory
- Import `create_app` from `cumadre.main` for app creation
- Import `Settings` from `cumadre.config` for mock settings
- Import exception types from `cumadre.exceptions` for mock side effects
- Test file naming follows existing convention: `test_*.py`
- Test class naming follows existing convention: `TestDescriptiveName`
- Test function naming follows existing convention: `test_<subject>_<scenario>_<expectation>`

### References

- [Source: _bmad-output/planning-artifacts/epics.md — Story 1.10 acceptance criteria, lines 454-485]
- [Source: _bmad-output/planning-artifacts/architecture.md — Test Organization table, lines 569-577]
- [Source: _bmad-output/planning-artifacts/architecture.md — "Tests are proportional — no testing the framework", line 577]
- [Source: src/cumadre/main.py — create_app() factory, health_endpoint inline route, validation_error_handler]
- [Source: src/cumadre/api.py — verify_api_key, verify_ready, generate_speech route handler]
- [Source: src/cumadre/exceptions.py — CumadreError hierarchy, cumadre_error_handler with Retry-After, register_exception_handlers]
- [Source: src/cumadre/schemas.py — SpeechRequest model with per-engine char limits]
- [Source: src/cumadre/config.py — Settings class, api_key is SecretStr with min_length=1]
- [Source: src/cumadre/service.py — KokoroEngine uses normalize_text→chunk_text→_apply_vibrato_warm; QwenEngine uses expand_siglas→_apply_whatsapp_subtle]
- [Source: tests/conftest.py — existing marker registration (preserve)]
- [Source: tests/test_health.py — existing 16 function-level tests (preserve)]
- [Source: tests/test_routing.py — existing 18 EngineRouter tests (preserve)]
- [Source: _bmad-output/implementation-artifacts/1-9-speech-endpoint-with-auth-queue-warmup.md — Previous story completion notes, integration fixes, code review enhancements]

### Previous Story Intelligence

**From Story 1.9 (Speech Endpoint):**
- `create_app()` is the FastAPI factory — essential for test setup. Import from `cumadre.main`.
- Lifespan is 9-phase startup that loads real models. MUST be skipped in tests.
- `app.state` attributes: `ready`, `queue_lock`, `queue_depth`, `start_time`, `settings`, `router`.
- `hmac.compare_digest()` is used for timing-safe API key comparison — tests must provide exact match.
- `validation_error_handler` converts 422 → 400. Tests that send malformed JSON should expect 400, not 422.
- `verify_ready` is a dependency on the speech route, NOT on the health endpoint. Health works during warm-up.
- `queue_depth` is incremented BEFORE lock acquisition (counts waiting + active), decremented in `finally`.
- `Retry-After: 30` header is set on 503 responses by `cumadre_error_handler` for `ServiceUnavailableError`.
- Previous story noted: "Story 1.10 will import `create_app()` and override state for testing."

**From Story 1.8 (Health Endpoint):**
- `build_health_response()` returns `tuple[dict[str, Any], int]`. Health endpoint wraps in JSONResponse.
- Health endpoint has Option B fallback: hardcoded 503 response when `router` is None during startup.
- Health endpoint is in `main.py`, NOT in `api.py` — different auth boundary.

**From Story 1.7 (Exception Handling):**
- `register_exception_handlers(app)` registers both `CumadreError` and `Exception` handlers.
- `AuthenticationError` default message is "Invalid or missing API key", hint is hardcoded.
- All handlers return `{"error": {"message", "type", "hint"}}` format.

### Git Intelligence

Recent commits follow `Implement Story X.Y: description` pattern. Current test count: 349 passed, 11 skipped. All quality gates pass (ruff, mypy strict, pytest). Code review in Story 1.9 added `hmac.compare_digest()`, `Retry-After` header, and critical-level startup logging. The codebase uses `from __future__ import annotations` consistently.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

- Fixed ruff E501 line-length violations in conftest.py, test_api.py
- Fixed F401 unused import (typing.Any) in test_health.py
- Fixed F841 unused variable (barrier) in test_queue.py
- Fixed RuntimeError in test_queue.py sequential test: asyncio.to_thread runs generate_speech in a worker thread, so asyncio event loop APIs are unavailable. Replaced with time.monotonic() timestamp tracking to verify sequential execution.

### Completion Notes List

- Task 1: Enhanced conftest.py with 5 fixtures (mock_settings, mock_router, app, client, auth_headers). App fixture creates FastAPI via create_app() and manually populates app.state, bypassing lifespan. AsyncClient uses ASGITransport.
- Task 2: Created test_api.py with 10 tests across 5 classes covering all speech endpoint HTTP scenarios: success (200 ogg/wav, content-disposition, default voice), auth (401 missing/invalid), validation (400 missing/empty input), not found (404 unknown voice), warm-up (503 with Retry-After).
- Task 3: Added 4 pipeline tests to test_routing.py verifying Kokoro calls normalize_text→chunk_text→_apply_vibrato_warm and Qwen3 calls expand_siglas→_apply_whatsapp_subtle.
- Task 4: Added 5 HTTP-level health endpoint tests to test_health.py verifying 200 when ready, 503 when warming up, no auth required, voices reflect router, clone_configured reflects state.
- Task 5: Created test_queue.py with 3 tests verifying sequential processing under asyncio.Lock, queue depth tracking during processing, and queue depth decrement on error.
- Task 6: All quality gates pass — 373 tests passed (22 new), ruff clean, mypy strict clean.

### File List

- tests/conftest.py (modified) — added fixtures for HTTP-level testing
- tests/test_api.py (new) — 10 speech endpoint HTTP tests
- tests/test_routing.py (modified) — added 4 preprocessing/post-processing pipeline tests
- tests/test_health.py (modified) — added 5 HTTP-level health endpoint tests
- tests/test_queue.py (new) — 3 queue behavior tests

### Change Log

- 2026-03-24: Implemented Story 1.10 — 22 new tests covering API auth/validation/success, engine routing pipelines, health HTTP endpoint, and queue behavior. Total: 373 passed, 11 skipped.
