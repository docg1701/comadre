# Story 1.3: Voice Discovery & Validation

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a **DevOps operator**,
I want the service to discover and validate voice files at startup,
so that I know which voices are available and get clear warnings about invalid files.

## Acceptance Criteria

1. **Given** a voices directory containing valid WAV files (3-10 seconds) **When** the voice discovery module scans the directory **Then** it returns a list of valid voice names (filename without extension) **And** logs each loaded voice with its duration (e.g., "Voice 'carlos' loaded from /voices/carlos.wav (5.2s)")

2. **Given** a voices directory containing a non-WAV file (e.g., .mp3) **When** the voice discovery module scans the directory **Then** it skips the file and logs a warning: "File /voices/test.mp3 skipped: not a WAV file"

3. **Given** a voices directory containing a WAV file longer than 10 seconds **When** the voice discovery module scans the directory **Then** it skips the file and logs a warning with the actual duration and the 10s limit

4. **Given** a voices directory containing a WAV file shorter than 3 seconds **When** the voice discovery module scans the directory **Then** it skips the file and logs a warning with the actual duration and the 3s minimum

5. **Given** an empty voices directory **When** the voice discovery module scans the directory **Then** it returns an empty list and logs a warning that no voices were found

6. **Given** a voices directory that does not exist **When** the voice discovery module scans the directory **Then** it returns an empty list and logs a warning that the directory was not found

## Tasks / Subtasks

- [x] Task 1: Create `src/comadre/voices.py` (AC: #1-#6)
  - [x] 1.1: Define `VoiceInfo` frozen dataclass with `name: str`, `path: Path`, `duration_seconds: float`
  - [x] 1.2: Define constants `MIN_VOICE_DURATION = 3.0` and `MAX_VOICE_DURATION = 10.0`
  - [x] 1.3: Implement `_validate_wav(file_path: Path) -> VoiceInfo | None` — opens with `wave` stdlib, calculates duration from frames/framerate, returns `VoiceInfo` if valid or `None` if invalid (logs reason)
  - [x] 1.4: Implement `discover_voices(voices_dir: Path) -> list[VoiceInfo]` — scans directory for `.wav` files, validates each, logs loaded/skipped, warns if no voices found or directory missing
  - [x] 1.5: Implement `list_voice_names(voices: list[VoiceInfo]) -> list[str]` — returns sorted list of voice names from VoiceInfo list
- [x] Task 2: Write tests for voices module (AC: #1-#6)
  - [x] 2.1: Create `tests/test_voices.py`
  - [x] 2.2: Create a `_create_wav` test helper using `wave` stdlib to write valid WAV files with configurable duration
  - [x] 2.3: Test valid WAV files in range (3-10s) are discovered and returned
  - [x] 2.4: Test non-WAV files (.mp3, .txt) are skipped with warning log
  - [x] 2.5: Test WAV files > 10s are skipped with warning log showing actual duration
  - [x] 2.6: Test WAV files < 3s are skipped with warning log showing actual duration
  - [x] 2.7: Test empty directory returns empty list with warning log
  - [x] 2.8: Test nonexistent directory returns empty list with warning log
  - [x] 2.9: Test corrupted/invalid .wav files are skipped with warning log
  - [x] 2.10: Test voice names are filename stems (no extension)
  - [x] 2.11: Test `list_voice_names()` returns sorted names
- [x] Task 3: Validation pass
  - [x] 3.1: Run `uv run ruff check .` — must pass
  - [x] 3.2: Run `uv run mypy src/` — must pass (strict mode)
  - [x] 3.3: Run `uv run pytest` — all tests must pass (including Story 1.2 tests)
  - [x] 3.4: Run `uv run pre-commit run --all-files` — must pass

## Dev Notes

### Critical Architecture Constraints

**Module Position in Import Graph:**
- `voices.py` is a mid-level module: imported by `service.py` and `health.py`
- `voices.py` may import from: `config.py`, `logging.py`, `exceptions.py`
- `voices.py` must NOT import from: `main.py`, `api.py`, `schemas.py`, `service.py`, `health.py`
- For this story, `voices.py` imports ONLY from `logging.py` (for `get_logger`). The `config.py` import is not needed because `discover_voices()` takes a `Path` parameter. The `exceptions.py` module already exists (created in previous sprint iteration).

**Module Responsibility:**
- `voices.py` handles: voice file discovery, WAV validation, voice listing
- `voices.py` must NOT contain: TTS generation logic, HTTP concerns, or FastAPI dependencies

**Logging:**
- Use `get_logger("voice")` — component tag is `voice` (from UX-DR3 component list: startup, request, memory, health, voice)
- All log messages must be plain ASCII, no emoji, no ANSI codes (UX-DR10)

**No raw `os.environ`:** The voices directory path is passed as a function parameter, not read from env vars.

**No `print()` statements:** All output through structured logging.

### voices.py Implementation Guide

```python
import dataclasses
import wave
from pathlib import Path

from comadre.logging import get_logger

MIN_VOICE_DURATION = 3.0
MAX_VOICE_DURATION = 10.0

logger = get_logger("voice")

@dataclasses.dataclass(frozen=True)
class VoiceInfo:
    name: str
    path: Path
    duration_seconds: float
```

**Key design decisions:**

- **`wave` stdlib, NOT `soundfile`:** The architecture specifies "Python wave stdlib" for voice discovery (~40 lines). The `soundfile` dependency exists for TTS audio output in Story 1.4 — voice discovery only needs to read WAV headers for validation, not decode audio data.
- **`discover_voices()` takes a `Path` parameter:** No default value. In Docker, the caller passes `Path("/voices")`. In tests, the caller passes `tmp_path`. This keeps the module pure (no filesystem assumptions) and fully testable.
- **No state storage:** `discover_voices()` is a pure function that scans and returns. State caching is the caller's responsibility (main.py lifespan in Story 1.9 will store the result).
- **VoiceInfo dataclass:** Frozen (immutable) dataclass carrying `name` (stem of filename), `path` (full Path to WAV), and `duration_seconds`. The `path` field is used for clone reference WAV detection (Qwen3 voice cloning path).
- **`list_voice_names()` helper:** Takes an already-discovered `list[VoiceInfo]` and returns sorted names. Used by health endpoint (Story 1.8) and error messages (Story 1.7 `VoiceNotFoundError` hint).

**Duration calculation:**
```python
with wave.open(str(file_path), "rb") as wf:
    frames = wf.getnframes()
    framerate = wf.getframerate()
    duration = frames / framerate
```

**Log format examples (from UX-DR5):**
```
2026-03-21T14:32:16Z | INFO  | voice    | Voice 'carlos' loaded from /voices/carlos.wav (5.2s)
2026-03-21T14:32:16Z | WARN  | voice    | File /voices/test.mp3 skipped: not a WAV file
2026-03-21T14:32:16Z | WARN  | voice    | File /voices/long.wav skipped: duration 45.0s exceeds 10s limit
2026-03-21T14:32:16Z | WARN  | voice    | File /voices/short.wav skipped: duration 1.5s below 3s minimum
2026-03-21T14:32:16Z | WARN  | voice    | No voice files found in /voices/
2026-03-21T14:32:16Z | WARN  | voice    | Voices directory not found: /voices/
```

**File scanning logic:**
1. Check if `voices_dir` exists — if not, log warning and return `[]`
2. Iterate all files in `voices_dir` (non-recursive, `Path.iterdir()`)
3. Skip files without `.wav` suffix (case-insensitive: `.WAV` is also valid) — log warning for each
4. For `.wav` files, attempt `wave.open()` — catch `wave.Error` for corrupted files, log warning
5. Check duration is in [3.0, 10.0] range — log warning if outside
6. Collect valid `VoiceInfo` entries
7. If no valid voices found after scanning, log warning
8. Return list sorted by name for deterministic ordering

### Testing Strategy

**WAV file generation helper:**
Use `wave` stdlib to create test WAV files with configurable duration:
```python
def _create_wav(path: Path, duration_seconds: float, framerate: int = 24000) -> None:
    n_frames = int(framerate * duration_seconds)
    with wave.open(str(path), "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(framerate)
        wf.writeframes(b"\x00\x00" * n_frames)
```

**Test approach:**
- Use `tmp_path` pytest fixture for isolated temp directories
- Use `caplog` or capture log output via the structured logger to assert log messages
- Each test creates its own directory structure with specific files
- Verify both return values AND log output

**Log assertion pattern:**
Since we use a custom `PipeFormatter`, capture output from the `voice` logger. Use `caplog` with `propagate=True` temporarily, or capture from a `StringIO` handler.

### Anti-Patterns to Avoid

- Do NOT use `soundfile` or `librosa` — `wave` stdlib is sufficient for header reading and is zero-dependency
- Do NOT use `os.listdir()` or `os.walk()` — use `pathlib.Path.iterdir()` for type safety
- Do NOT recurse into subdirectories — flat scan of the voices directory only
- Do NOT import from `exceptions.py` — for this story, validation failures are logged and skipped, not raised as exceptions
- Do NOT add voices_dir to `Settings` in `config.py` — the architecture does not prescribe it; the path is passed as a parameter
- Do NOT create `main.py`, `service.py`, `health.py`, or any other module — those belong to later stories
- Do NOT store module-level mutable state (e.g., `_discovered_voices: list[VoiceInfo] = []`) — the discovery function is pure; state management is the caller's responsibility
- Do NOT add emoji to log messages (UX-DR10)

### Previous Story Intelligence

**From Story 1.2 (done):**
- `get_logger("voice")` from `comadre.logging` provides the structured pipe-delimited logger with component tag `voice`
- Logger output format: `timestamp | level | component | message` with fixed-width levels
- `WARN ` (not `WARNING`) is the correct level name in log output
- Logger has `propagate = False` set — for test assertions, either add a test handler or set propagate temporarily
- No new dependencies needed — `wave` is Python stdlib, `pathlib` is stdlib

**From Story 1.1 (done):**
- `soundfile>=0.13` is already in `pyproject.toml` but is for Story 1.4's audio output, NOT for voice discovery
- `tests/` directory and `tests/__init__.py` exist
- Pre-commit hooks: ruff, mypy (strict), hadolint, yamllint, shellcheck, markdownlint
- Pre-commit excludes `_bmad-output/`, `_bmad/`, `.claude/`
- Commits use format: "Add [feature description] (Story X.Y)"

**Git patterns from recent commits:**
- `be201ea` Add configuration and structured logging (Story 1.2)
- `3c81bad` Add project scaffolding and quality tooling (Story 1.1)

### Project Structure Notes

**Files to create in this story:**
```
src/comadre/voices.py     (new)
tests/test_voices.py      (new)
```

**Files NOT to create or modify:**
- `src/comadre/config.py` — no changes needed (no VOICES_DIR setting)
- `src/comadre/logging.py` — already complete from Story 1.2
- `src/comadre/exceptions.py` — belongs to Story 1.5
- `src/comadre/main.py` — belongs to Story 1.7
- `src/comadre/service.py` — belongs to Story 1.4
- `src/comadre/health.py` — belongs to Story 1.6
- `pyproject.toml` — no new dependencies needed (`wave` and `pathlib` are stdlib)

**Existing files for reference (do not modify):**
- `src/comadre/config.py` — Settings class with `default_voice: str` field (the voice name, not directory)
- `src/comadre/logging.py` — `get_logger(component)` returns pipe-formatted logger

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Voice Management (FR14-FR16)]
- [Source: _bmad-output/planning-artifacts/architecture.md#Module Responsibility — voices.py]
- [Source: _bmad-output/planning-artifacts/architecture.md#Import Dependency Graph — voices.py imported by service.py, health.py]
- [Source: _bmad-output/planning-artifacts/architecture.md#Startup Sequence — step 3: Discover voices]
- [Source: _bmad-output/planning-artifacts/architecture.md#Voice Discovery Module — ~40 lines, Python wave stdlib]
- [Source: _bmad-output/planning-artifacts/architecture.md#Architectural Boundaries — voices.py at filesystem boundary]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 1.3: Voice Discovery & Validation]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md#Voice Discovery Module — scan, validate, report]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md#UX-DR10: Terminal Accessibility — plain ASCII, no emoji]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

None — clean implementation with no blockers.

### Completion Notes List

- Implemented `src/comadre/voices.py` with VoiceInfo frozen dataclass, MIN/MAX duration constants, `_validate_wav()`, `discover_voices()`, and `list_voice_names()` functions
- Used `wave` stdlib only (no soundfile dependency) for WAV header reading
- `discover_voices()` takes a `Path` parameter (no env var access, no state storage)
- All log messages use plain ASCII via `get_logger("voice")` with pipe-delimited format
- Case-insensitive `.wav` suffix matching, sorted directory iteration for deterministic output
- Created 16 tests covering all 6 acceptance criteria: valid discovery, non-WAV skip, too-long skip, too-short skip, empty dir, missing dir, corrupted WAV, boundary durations, name stems, sorted names
- All 45 tests pass (29 existing + 16 new), no regressions
- ruff check, ruff format, mypy strict, and all pre-commit hooks pass

### Change Log

- 2026-03-21: Implemented voice discovery and validation module (Story 1.3)

### File List

- `src/comadre/voices.py` (new) — Voice discovery and validation module
- `tests/test_voices.py` (new) — 16 tests for voice module
