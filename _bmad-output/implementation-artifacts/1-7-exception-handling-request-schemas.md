# Story 1.7: Exception Handling & Request Schemas

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **n8n workflow**,
I want consistent, self-documenting error responses on every failure,
so that I can programmatically handle errors and the operator can diagnose issues.

## Acceptance Criteria

1. **Given** the exceptions module **When** I inspect the error hierarchy **Then** `ComadreError` is the base class with `status_code`, `error_type`, and `hint` attributes, and subclasses exist for: `AuthenticationError` (401), `InvalidRequestError` (400), `VoiceNotFoundError` (404), `GenerationError` (500), `ServiceUnavailableError` (503)

2. **Given** any `ComadreError` is raised during request processing **When** the centralized exception handler catches it **Then** it returns JSON with all three fields always present: `error.message`, `error.type`, `error.hint` **And** the `hint` field contains an actionable instruction, never a restatement of the message

3. **Given** an unexpected exception (not a ComadreError subclass) **When** the fallback handler catches it **Then** it returns a 500 response with `error.type: "server_error"` and a generic hint referencing log inspection **And** the full traceback is logged server-side at ERROR level but never returned to the client

4. **Given** the schemas module **When** I inspect `SpeechRequest` **Then** it validates `input` (required string), `voice` (optional string, default from config), `response_format` (optional, default "ogg", enum: "ogg"/"wav"), `speed` (optional float, default 1.0, range 0.25-4.0), `destination` (optional string, default "whatsapp", enum: "whatsapp"/"telegram"/"messenger"/"instagram") **And** char limits are validated per engine: 500 for Kokoro voices (santa/dora/alex), 300 for Qwen3 voices (clone/qwen-female/qwen-male)

## Tasks / Subtasks

- [x] Task 1: Add `AuthenticationError` and `ServiceUnavailableError` to exceptions.py (AC: #1)
  - [x] 1.1 Add `AuthenticationError(ComadreError)` with status_code=401, error_type="authentication_error"
  - [x] 1.2 Add `ServiceUnavailableError(ComadreError)` with status_code=503, error_type="service_unavailable"
  - [x] 1.3 Add tests for both new exceptions in test_exceptions.py

- [x] Task 2: Add centralized exception handlers to exceptions.py (AC: #2, #3)
  - [x] 2.1 Add `comadre_error_handler(request, exc)` async function returning JSONResponse with `{"error": {"message": ..., "type": ..., "hint": ...}}`
  - [x] 2.2 Add `unhandled_error_handler(request, exc)` async function returning 500 JSONResponse with generic error and logging full traceback at ERROR level
  - [x] 2.3 Add `register_exception_handlers(app)` function that registers both handlers on a FastAPI app instance
  - [x] 2.4 Add tests for both handlers (mock FastAPI Request, verify JSON structure, verify traceback logging for unhandled errors)

- [x] Task 3: Create schemas.py with SpeechRequest model (AC: #4)
  - [x] 3.1 Create `src/comadre/schemas.py` with `SpeechRequest(BaseModel)` and all fields
  - [x] 3.2 Add `ResponseFormat` enum ("ogg", "wav") and `Destination` enum ("whatsapp", "telegram", "messenger", "instagram")
  - [x] 3.3 Add `model_validator` for per-engine char limit validation (500 Kokoro, 300 Qwen3)
  - [x] 3.4 Create `tests/test_schemas.py` with tests for all validations

## Dev Notes

### What Already Exists (DO NOT recreate)

**`src/comadre/exceptions.py`** already has:
- `ComadreError` base class with `message`, `status_code`, `error_type`, `hint` attributes
- `VoiceNotFoundError(ComadreError)` — 404, "not_found_error"
- `InvalidRequestError(ComadreError)` — 400, "invalid_request_error"
- `GenerationError(ComadreError)` — 500, "server_error"

**`tests/test_exceptions.py`** already has 14 tests for the above 4 classes.

### What This Story Adds

1. **Two new exception subclasses** in `exceptions.py`:
   - `AuthenticationError` (401, "authentication_error")
   - `ServiceUnavailableError` (503, "service_unavailable")

2. **Centralized FastAPI exception handlers** in `exceptions.py`:
   - `comadre_error_handler` — catches any `ComadreError`, returns structured JSON
   - `unhandled_error_handler` — catches `Exception`, returns generic 500, logs traceback
   - `register_exception_handlers(app)` — registers both handlers on the app

3. **New file `schemas.py`** with `SpeechRequest` Pydantic model.

### Implementation Guidance

#### AuthenticationError (Task 1.1)

```python
class AuthenticationError(ComadreError):
    """Raised when authentication fails."""

    def __init__(self, message: str = "Invalid or missing API key") -> None:
        super().__init__(
            message=message,
            status_code=401,
            error_type="authentication_error",
            hint="Check the API_KEY environment variable and ensure your Authorization header uses 'Bearer <key>'.",
        )
```

#### ServiceUnavailableError (Task 1.2)

```python
class ServiceUnavailableError(ComadreError):
    """Raised when the service is not ready to handle requests."""

    def __init__(self, message: str = "Service is warming up", *, retry_seconds: int = 30) -> None:
        super().__init__(
            message=message,
            status_code=503,
            error_type="service_unavailable",
            hint=f"The service is still loading models. Retry in {retry_seconds} seconds.",
        )
        self.retry_seconds = retry_seconds
```

#### Exception Handlers (Task 2)

Place handler functions and the registration function in `exceptions.py`. The handlers need two imports:
- `from starlette.requests import Request`
- `from starlette.responses import JSONResponse`

Use starlette imports (not fastapi) since these are the actual types FastAPI uses internally, and exceptions.py must not import from fastapi directly.

**Response JSON structure** (nested under `error` key — matches OpenAI pattern):
```json
{
  "error": {
    "message": "Voice 'ghost' not found",
    "type": "not_found_error",
    "hint": "Available voices: ['santa', 'dora', 'alex']. Place WAV files (3-10s) in the /voices/ directory."
  }
}
```

**Unhandled error handler** must:
- Log full traceback using `get_logger("request")` at ERROR level with `exc_info=exc` (not `exc_info=True`, which would call `sys.exc_info()` and return `None` since the handler is not inside an `except` block)
- Return generic 500 with `error_type: "server_error"` and hint about checking logs
- NEVER include the actual exception message or traceback in the response

**`register_exception_handlers(app)`** — called from `main.py` during app creation:
```python
def register_exception_handlers(app: FastAPI) -> None:
    app.add_exception_handler(ComadreError, comadre_error_handler)
    app.add_exception_handler(Exception, unhandled_error_handler)
```

Note: The `app` parameter type hint should use `from __future__ import annotations` and `TYPE_CHECKING` guard for `FastAPI` to avoid making fastapi a hard import in exceptions.py.

#### SpeechRequest Schema (Task 3)

Create `src/comadre/schemas.py` — this file has **no app imports** per architecture rules.

```python
class ResponseFormat(str, Enum):
    ogg = "ogg"
    wav = "wav"

class Destination(str, Enum):
    whatsapp = "whatsapp"
    telegram = "telegram"
    messenger = "messenger"
    instagram = "instagram"

class SpeechRequest(BaseModel):
    input: str = Field(min_length=1)
    voice: str | None = None  # Default filled from config at API layer
    response_format: ResponseFormat = ResponseFormat.ogg
    speed: float = Field(default=1.0, ge=0.25, le=4.0)  # Reserved for future use
    destination: Destination = Destination.whatsapp
```

**Per-engine char limit validation:** Use a `model_validator(mode="after")` that checks voice against hardcoded voice sets. The voice-to-engine mapping must be duplicated here (not imported from service.py) because schemas.py has no app imports.

```python
_KOKORO_VOICES = frozenset({"santa", "dora", "alex"})
_QWEN_VOICES = frozenset({"clone", "qwen-female", "qwen-male"})
_KOKORO_CHAR_LIMIT = 500
_QWEN_CHAR_LIMIT = 300
```

Validation logic in the `model_validator`:
- If `voice is None` → skip char limit check (default voice resolved later at API layer)
- If `voice in _KOKORO_VOICES` → enforce 500 char limit on `input`
- If `voice in _QWEN_VOICES` → enforce 300 char limit on `input`
- If `voice` not in either set → pass through (VoiceNotFoundError is raised later in the service layer)

When char limit is exceeded, raise `ValueError` with a clear message including the limit and engine name. Pydantic will convert this to a 422 response; the API layer (Story 1.9) will later catch and re-raise as `InvalidRequestError`.

### Anti-Patterns to Avoid

- **DO NOT** import from `service.py`, `config.py`, `voices.py`, or `api.py` in `schemas.py` — the import graph does not allow it
- **DO NOT** use raw `HTTPException` in exception handlers — return `JSONResponse` directly
- **DO NOT** include Python tracebacks in error responses to the client
- **DO NOT** add HTTP endpoint handlers (that's Story 1.9)
- **DO NOT** add the asyncio.Lock queue (that's Story 1.9)
- **DO NOT** add FastAPI lifespan/startup logic (that's Story 1.9)
- **DO NOT** modify existing `VoiceNotFoundError`, `InvalidRequestError`, or `GenerationError` classes
- **DO NOT** add `main.py` or `api.py` files — just prepare the handlers and schema for later integration
- **DO NOT** log the actual exception message in unhandled error responses — only log server-side

### Testing Guidance

**Test file locations:**
- `tests/test_exceptions.py` — extend with tests for `AuthenticationError`, `ServiceUnavailableError`, and both exception handlers
- `tests/test_schemas.py` — new file for `SpeechRequest` validation tests

**Exception handler tests** (Task 2.4):
- Create a mock `Request` object (or use `starlette.testclient`)
- Call handler functions directly as async functions (use `pytest.mark.asyncio`)
- Verify response status code, content-type, and JSON body structure
- For unhandled handler: verify traceback is logged (mock the logger) and NOT in response body

**Schema tests** (Task 3.4):
- Valid request with all defaults
- Valid request with all fields specified
- Empty input string → validation error
- Kokoro voice with 501 chars → validation error
- Kokoro voice with 500 chars → passes
- Qwen3 voice with 301 chars → validation error
- Qwen3 voice with 300 chars → passes
- Unknown voice with 500+ chars → passes (not validated at schema level)
- None voice → passes (no char limit check)
- Invalid response_format → validation error
- Invalid destination → validation error
- Speed within bounds → passes
- Speed out of bounds → validation error

### Project Structure Notes

- `schemas.py` is a NEW file at `src/comadre/schemas.py` — matches architecture spec
- Exception handlers added to EXISTING `exceptions.py` — not a new file
- Import graph: `exceptions.py` imports from `logging.py` (for `get_logger`) and starlette (for Request/JSONResponse). No upward imports.
- `schemas.py` imports only from pydantic and stdlib. No app imports.

### References

- [Source: _bmad-output/planning-artifacts/epics.md — Story 1.7 acceptance criteria]
- [Source: _bmad-output/planning-artifacts/architecture.md — Error Handling Pattern, Code Structure, Import Dependency Graph, Enforcement Guidelines]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md — Error Response Trinity (What/Why/Do), Error Communication Pattern]
- [Source: src/comadre/exceptions.py — Existing ComadreError hierarchy (4 classes)]
- [Source: src/comadre/config.py — Settings class with default_voice field]
- [Source: src/comadre/service.py — KOKORO_VOICES, QWEN_VOICES mappings, char limits]
- [Source: tests/test_exceptions.py — Existing test patterns (14 tests)]

### Previous Story Intelligence

**From Story 1.6 (Engine Router):**
- `EngineRouter` class added to `service.py` with unified `generate_speech()` dispatch
- Voice mappings: `KOKORO_VOICES = {"santa": "pm_santa", "dora": "pf_dora", "alex": "pm_alex"}`, `QWEN_VOICES = {"clone": "clone", "qwen-female": "female", "qwen-male": "male"}`
- Clone guard already at router level — raises `VoiceNotFoundError` if clone not configured
- 277 tests passed, 11 skipped (integration). All quality gates pass.
- `VoiceNotFoundError` and `InvalidRequestError` work correctly in the service layer

**From Story 1.5 (Qwen3 Engine):**
- `QwenEngine` validates 300 char limit using `InvalidRequestError`
- Replaced raw `RuntimeError` with `GenerationError` in engine code

**From Story 1.4 (Kokoro Engine):**
- `KokoroEngine` validates 500 char limit using `InvalidRequestError`
- kokoro-onnx replaced legacy kokoclone — never reference kokoclone

### Git Intelligence

Recent commits follow pattern: one commit per story with descriptive message. Current test suite: 277 passed, 11 skipped. All quality gates (ruff, mypy strict, pytest, pre-commit) pass consistently.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

None — clean implementation, no debugging required.

### Completion Notes List

- Task 1: Added `AuthenticationError` (401) and `ServiceUnavailableError` (503) exception subclasses to `exceptions.py`. ServiceUnavailableError includes configurable `retry_seconds` attribute. 14 new tests added (6 for AuthenticationError, 8 for ServiceUnavailableError).
- Task 2: Added `comadre_error_handler`, `unhandled_error_handler`, and `register_exception_handlers` to `exceptions.py`. Uses starlette imports (not fastapi) for Request/JSONResponse. FastAPI type hint guarded behind `TYPE_CHECKING`. Unhandled errors log traceback server-side via `get_logger("request")` and never leak details to client. 10 new async handler tests added.
- Task 3: Created `src/comadre/schemas.py` with `SpeechRequest` model, `ResponseFormat` (StrEnum), `Destination` (StrEnum). Per-engine char limit validation via `model_validator(mode="after")`: 500 for Kokoro voices, 300 for Qwen3 voices, unknown/None voices pass through. 22 new tests in `tests/test_schemas.py`.
- All quality gates pass: ruff clean, mypy strict clean, 326 tests passed (49 new), 11 skipped (integration).

### Change Log

- 2026-03-24: Implemented Story 1.7 — added AuthenticationError, ServiceUnavailableError, centralized exception handlers, and SpeechRequest schema with per-engine char limit validation.

### File List

- `src/comadre/exceptions.py` — modified (added AuthenticationError, ServiceUnavailableError, exception handlers, register function)
- `src/comadre/schemas.py` — new (SpeechRequest, ResponseFormat, Destination, char limit validation)
- `tests/test_exceptions.py` — modified (added 24 tests for new exceptions and handlers)
- `tests/test_schemas.py` — new (22 tests for SpeechRequest validation)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — modified (story status update)
- `_bmad-output/implementation-artifacts/1-7-exception-handling-request-schemas.md` — modified (task checkboxes, dev record)
