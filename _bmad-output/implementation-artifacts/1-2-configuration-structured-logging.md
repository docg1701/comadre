# Story 1.2: Configuration & Structured Logging

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **developer**,
I want type-safe configuration and structured logging,
so that all modules have a consistent foundation for settings and observability.

## Acceptance Criteria

1. **Given** the project from Story 1.1 **When** I import config.py **Then** it provides a `Settings(BaseSettings)` class loading `API_KEY` (required), `DEFAULT_VOICE` (default: `"default"`), `WORKERS` (default: `1`), `PORT` (default: `8000`) from environment variables

2. **Given** `API_KEY` is not set in the environment **When** the `Settings` class is instantiated **Then** it raises a validation error with a clear message about the missing required variable

3. **Given** the logging module **When** any module logs a message **Then** the output follows pipe-delimited format: `timestamp | level | component | message` with ISO 8601 UTC timestamps and fixed-width 5-char levels

4. **Given** the logging module **When** I create a logger with `get_logger("startup")` **Then** messages include the component tag and render correctly in plain ASCII (no emoji, no ANSI color codes)

## Tasks / Subtasks

- [x] Task 1: Create `src/comadre/config.py` (AC: #1, #2)
  - [x] 1.1: Define `Settings(BaseSettings)` with `model_config = SettingsConfigDict(...)` — no env prefix, case-insensitive
  - [x] 1.2: Declare `api_key: SecretStr` (required — no default value, masked in repr/logs)
  - [x] 1.3: Declare `default_voice: str = "default"`, `workers: int = 1`, `port: int = 8000`
  - [x] 1.4: Add a module-level `get_settings()` function returning a cached `Settings()` instance (use `@lru_cache`)
  - [x] 1.5: Verify that missing `API_KEY` raises `pydantic.ValidationError` with `type=missing`
- [x] Task 2: Create `src/comadre/logging.py` (AC: #3, #4)
  - [x] 2.1: Define a custom `PipeFormatter(logging.Formatter)` that outputs `timestamp | level | component | message`
  - [x] 2.2: Timestamps must be ISO 8601 UTC (e.g., `2026-03-21T14:32:00Z`)
  - [x] 2.3: Levels must be fixed-width 5 chars: `INFO `, `WARN `, `ERROR`, `CRIT `, `DEBUG`
  - [x] 2.4: Implement `get_logger(component: str) -> logging.Logger` that returns a logger with the pipe formatter attached to a `StreamHandler(sys.stdout)`
  - [x] 2.5: Implement `setup_logging(level: int = logging.INFO) -> None` to configure the root logger with the pipe formatter
  - [x] 2.6: Ensure plain ASCII output — no emoji, no ANSI escape codes, no Unicode box-drawing
- [x] Task 3: Write tests for config module
  - [x] 3.1: Create `tests/test_config.py`
  - [x] 3.2: Test that `Settings` loads values from environment variables
  - [x] 3.3: Test that missing `API_KEY` raises `ValidationError`
  - [x] 3.4: Test default values (`default_voice="default"`, `workers=1`, `port=8000`)
- [x] Task 4: Write tests for logging module
  - [x] 4.1: Create `tests/test_logging.py`
  - [x] 4.2: Test that `get_logger("startup")` returns a logger with the pipe formatter
  - [x] 4.3: Test log output format matches `timestamp | level | component | message`
  - [x] 4.4: Test fixed-width level formatting (5 chars)
  - [x] 4.5: Test that output contains no ANSI escape codes
- [x] Task 5: Validation pass
  - [x] 5.1: Run `uv run ruff check .` — must pass
  - [x] 5.2: Run `uv run mypy src/` — must pass (strict mode)
  - [x] 5.3: Run `uv run pytest` — all tests must pass
  - [x] 5.4: Run `uv run pre-commit run --all-files` — must pass

## Dev Notes

### Critical Architecture Constraints

**Module Position in Import Graph:**
- `config.py` is at the bottom of the import graph — imported by every other module, imports NOTHING from the app
- `logging.py` is at the bottom of the import graph — imported by every other module, imports NOTHING from the app
- Neither `config.py` nor `logging.py` may import from `main.py`, `api.py`, `schemas.py`, `service.py`, `exceptions.py`, `health.py`, or `voices.py`

**No raw `os.environ`:** All environment variables must go through `pydantic-settings`. Never `os.getenv("API_KEY")`.

**No `print()` statements:** All output must go through the structured logging module.

**No `logging.basicConfig()`:** The project uses a custom formatter. The `setup_logging()` function configures the root logger programmatically.

### config.py Implementation Guide

```python
from functools import lru_cache
from pydantic_settings import BaseSettings, SettingsConfigDict

class Settings(BaseSettings):
    model_config = SettingsConfigDict(
        case_sensitive=False,
    )

    api_key: SecretStr              # Required — no default, masked in repr/logs
    default_voice: str = "default"
    workers: int = 1
    port: int = 8000

@lru_cache(maxsize=1)
def get_settings() -> Settings:
    return Settings()
```

**Key design decisions:**
- No `env_prefix` — env vars are `API_KEY`, `DEFAULT_VOICE`, `WORKERS`, `PORT` (not `COMADRE_API_KEY`)
- No `.env` file loading — environment variables are set via `compose.yaml` or shell. The `.env` file is for developer convenience only and is handled by Docker Compose / shell, not the app
- `@lru_cache` on `get_settings()` ensures the `Settings` object is created exactly once. This also means tests must call `get_settings.cache_clear()` when patching env vars
- Field `api_key: SecretStr` with no default means pydantic-settings raises `ValidationError` with `type=missing` if `API_KEY` is not in the environment. Use `settings.api_key.get_secret_value()` to access the raw string

**pydantic-settings v2.12+ note:** Source priority is init > env > dotenv > secrets > defaults. Since we don't configure dotenv or secrets sources, the effective priority is simply env > defaults.

### logging.py Implementation Guide

**Log format spec (from UX-DR3):**
```
2026-03-21T14:32:00Z | INFO  | startup  | Loading Kokoro TTS model...
```

Four fields, pipe-delimited:
1. `timestamp` — ISO 8601 UTC, always ends with `Z`
2. `level` — fixed-width 5 chars: `DEBUG`, `INFO `, `WARN `, `ERROR`, `CRIT `
3. `component` — the logger name passed to `get_logger()`
4. `message` — the log message

**Level mapping:** Python's `logging.WARNING` must render as `WARN ` (not `WARNING`). Python's `logging.CRITICAL` must render as `CRIT ` (not `CRITICAL`). This requires overriding in the custom formatter.

**Component tags used across the project** (from UX-DR3): `startup`, `request`, `memory`, `health`, `voice`. Other stories will call `get_logger()` with these names.

**Request logs** (future Story 1.9) will include: method, path, voice, format, chars, duration — but the logging module itself just provides the formatter and `get_logger()`. The calling code constructs the message string.

**Implementation approach:**
- Subclass `logging.Formatter` to create `PipeFormatter`
- Override `format()` to produce the pipe-delimited output
- Use `datetime.now(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")` for timestamps (not `time.gmtime` which lacks `Z` suffix)
- Map level names: `{WARNING: "WARN ", CRITICAL: "CRIT ", INFO: "INFO ", ERROR: "ERROR", DEBUG: "DEBUG"}`
- `get_logger(component)` creates a logger with name=component, attaches a `StreamHandler(sys.stdout)` with `PipeFormatter`, and sets `propagate = False` to avoid duplicate output
- `setup_logging()` configures the root logger similarly, for any uncategorized log output

### Testing Strategy

**test_config.py:**
- Use `monkeypatch.setenv()` / `monkeypatch.delenv()` to control environment variables
- Call `get_settings.cache_clear()` in a fixture or before each test to reset the cached instance
- Test missing `API_KEY` with `pytest.raises(ValidationError)`
- Test that default values are correct when only `API_KEY` is set
- Test that all env vars override defaults

**test_logging.py:**
- Capture log output using a `logging.Handler` that writes to a `StringIO` buffer, or use `caplog` fixture
- Assert the format pattern: ISO 8601 timestamp, pipe delimiters, fixed-width levels
- Verify `WARN ` (not `WARNING`) and `CRIT ` (not `CRITICAL`)
- Verify no ANSI escape codes (regex: `\x1b\[` should not appear)
- Verify logger name appears as the component field

### Anti-Patterns to Avoid

- Do NOT load `.env` files in the Settings class — Docker Compose handles `.env` in production
- Do NOT use `env_prefix` — the architecture specifies bare `API_KEY`, not `COMADRE_API_KEY`
- Do NOT use `structlog` — standard library `logging` with custom formatter is sufficient for pipe-delimited output
- Do NOT use `colorama`, `rich`, or any ANSI color library — terminal accessibility requires plain ASCII (UX-DR10)
- Do NOT add emoji to log messages — terminal accessibility (UX-DR10)
- Do NOT create any other module files (`main.py`, `api.py`, etc.) — those belong to other stories
- Do NOT use `logging.basicConfig()` — it conflicts with the custom formatter setup
- Do NOT add `logger = get_logger("config")` inside `config.py` itself — `config.py` must not import from `logging.py` (both are at the bottom of the import graph, creating a potential circular import). If config logging is needed later, it will be done from `main.py`

### Previous Story Intelligence

**From Story 1.1 (done):**
- Build backend is `uv_build` (not `hatchling` as mentioned in some architecture docs)
- `.python-version` is set to `3.12`
- markdownlint has MD013 (line-length) disabled
- Mypy runs as a local hook via `uv run mypy` for full dependency access
- Pre-commit excludes `_bmad-output/`, `_bmad/`, `.claude/` directories
- Runtime deps already in `pyproject.toml`: `fastapi>=0.115`, `uvicorn[standard]>=0.34`, `pydantic-settings>=2.7`, `soundfile>=0.13`
- `pydantic-settings` is already a project dependency — no need to add it
- The `tests/` directory exists with `__init__.py`

**Git patterns from Story 1.1:**
- Commits use format: "Add [feature description] (Story X.Y)"
- Files created follow the architecture's module names exactly

### Project Structure Notes

**Files to create in this story:**
```
src/comadre/config.py     (new)
src/comadre/logging.py    (new)
tests/test_config.py      (new)
tests/test_logging.py     (new)
```

**Files NOT to create or modify:**
- `src/comadre/main.py` — belongs to Story 1.7
- `src/comadre/__init__.py` — already exists, no changes needed
- `pyproject.toml` — `pydantic-settings` is already a dependency; no new deps needed for this story

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Implementation Patterns & Consistency Rules — Module Responsibility table]
- [Source: _bmad-output/planning-artifacts/architecture.md#Implementation Patterns & Consistency Rules — Import Dependency Graph]
- [Source: _bmad-output/planning-artifacts/architecture.md#Format Patterns — Log Format]
- [Source: _bmad-output/planning-artifacts/architecture.md#Core Architectural Decisions — D6: pydantic-settings]
- [Source: _bmad-output/planning-artifacts/architecture.md#Process Patterns — Startup Sequence]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 1.2: Configuration & Structured Logging]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md#UX-DR3: Structured Logger]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md#UX-DR9: Configuration Defaults Pattern]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md#UX-DR10: Terminal Accessibility]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

No issues encountered during implementation.

### Completion Notes List

- Implemented `Settings(BaseSettings)` in `config.py` with `api_key` (required), `default_voice`, `workers`, `port` fields. Uses `@lru_cache` for singleton pattern via `get_settings()`.
- Implemented `PipeFormatter`, `get_logger()`, and `setup_logging()` in `logging.py`. Format: `timestamp | level | component | message` with ISO 8601 UTC timestamps and fixed-width 5-char levels (WARN/CRIT mapping).
- 22 tests covering: env var loading, missing API_KEY validation error, default values, case insensitivity, cache behavior, pipe format output, all 5 log levels, ANSI escape absence, component tags, handler deduplication, propagation control.
- All validation passed: ruff check, mypy strict, pytest (22/22), pre-commit (all hooks).

### Change Log

- 2026-03-21: Implemented Story 1.2 — configuration module and structured logging with full test coverage.

### File List

- `src/comadre/config.py` (new)
- `src/comadre/logging.py` (new)
- `tests/test_config.py` (new)
- `tests/test_logging.py` (new)
