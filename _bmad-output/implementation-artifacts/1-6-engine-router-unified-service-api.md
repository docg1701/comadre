# Story 1.6: Engine Router & Unified Service API

Status: done

## Story

As an n8n workflow,
I want to specify a voice name and have the correct engine handle the request,
so that voice selection is simple and engine details are transparent.

## Acceptance Criteria

1. **Given** voice "santa", "dora", or "alex"
   **When** service routes the request
   **Then** Kokoro engine handles it with normalize_text + chunk_text preprocessing and vibrato_warm post-processing

2. **Given** voice "clone", "qwen-female", or "qwen-male"
   **When** service routes the request
   **Then** Qwen3 engine handles it with expand_siglas preprocessing and whatsapp-subtle post-processing

3. **Given** an unknown voice name
   **When** service routes the request
   **Then** it raises VoiceNotFoundError with available voice list

4. **Given** the service module
   **When** generate_speech() is called
   **Then** it provides a unified API that internally dispatches to the correct engine

5. **Given** noise WAV files (room ambience + hiss)
   **When** post-processing runs
   **Then** correct noise calibration is applied per engine (Kokoro needs 3x more noise than Qwen3)

## Tasks / Subtasks

- [x] Task 1: Create `EngineRouter` class in `service.py` (AC: #3, #4)
  - [x] 1.1 Add `EngineRouter` class that holds references to `KokoroEngine` and `QwenEngine` instances
  - [x] 1.2 Implement `_resolve_engine(voice_name)` that returns the correct engine instance based on voice name
  - [x] 1.3 Implement `generate_speech(text, voice_name, response_format, noise_dir, seed)` as unified entry point that dispatches to the resolved engine
  - [x] 1.4 Implement `available_voices()` returning combined voice list from both engines (sorted)
  - [x] 1.5 Implement `engine_status()` returning per-engine loaded/clone status dict for health endpoint
  - [x] 1.6 Raise `VoiceNotFoundError` with full available voice list when voice is unknown

- [x] Task 2: Validate routing correctness (AC: #1, #2, #5)
  - [x] 2.1 Verify Kokoro voices (santa/dora/alex) route to `KokoroEngine.generate_speech()` which already applies normalize_text + chunk_text + vibrato_warm
  - [x] 2.2 Verify Qwen3 voices (clone/qwen-female/qwen-male) route to `QwenEngine.generate_speech()` which already applies expand_siglas + whatsapp-subtle
  - [x] 2.3 Verify noise calibration is preserved (Kokoro: room=0.45/hiss=0.24, Qwen3: room=0.15/hiss=0.08) — already implemented in each engine's post-processing

- [x] Task 3: Write tests in `tests/test_routing.py` (AC: #1-5)
  - [x] 3.1 Test each Kokoro voice routes to KokoroEngine
  - [x] 3.2 Test each Qwen3 voice routes to QwenEngine
  - [x] 3.3 Test unknown voice raises VoiceNotFoundError with voice list in hint
  - [x] 3.4 Test `available_voices()` returns sorted combined list
  - [x] 3.5 Test `engine_status()` returns correct per-engine status
  - [x] 3.6 Test clone voice raises error when clone not configured
  - [x] 3.7 Test seed parameter is forwarded to Qwen3 engine only

- [x] Task 4: Quality gates
  - [x] 4.1 `uv run ruff check .` passes
  - [x] 4.2 `uv run mypy src/` passes (strict mode)
  - [x] 4.3 `uv run pytest` passes (all existing + new tests)
  - [x] 4.4 `uv run pre-commit run --all-files` passes

## Dev Notes

### What Already Exists (DO NOT RECREATE)

The heavy lifting is done. Both engines are fully implemented in `src/comadre/service.py`:

- **`KokoroEngine`** — `generate_speech(text, voice_name, response_format, noise_dir)` already calls `normalize_text()` + `chunk_text()`, generates chunks, concatenates WAVs, and applies `_apply_vibrato_warm()` with room=0.45/hiss=0.24 noise volumes.
- **`QwenEngine`** — `generate_speech(text, voice_name, response_format, noise_dir, seed)` already calls `expand_siglas()`, builds CLI command, runs subprocess, and applies `_apply_whatsapp_subtle()` with room=0.15/hiss=0.08 noise volumes.
- **Voice mappings** already defined: `KOKORO_VOICES = {"santa": "pm_santa", "dora": "pf_dora", "alex": "pm_alex"}` and `QWEN_VOICES = {"clone": "clone", "qwen-female": "female", "qwen-male": "male"}`.
- **`VoiceNotFoundError`** already exists in `exceptions.py` with status_code=404, error_type, and hint containing available voices.
- **`InvalidRequestError`** already exists for 400-level validation.

### What This Story Adds

A thin **`EngineRouter`** class that:
1. Holds references to both engine instances
2. Maps voice name → engine
3. Exposes a single `generate_speech()` that delegates to the correct engine
4. Provides `available_voices()` and `engine_status()` for downstream consumers (Story 1.8 health, Story 1.9 speech endpoint)

This is a **routing and aggregation layer**, not a rewrite. Do NOT duplicate preprocessing, post-processing, or validation logic that already lives inside each engine.

### Implementation Guidance

**Where to add code:** `src/comadre/service.py` — add `EngineRouter` class after the two engine classes. This keeps the import graph clean (service.py already imports from config, exceptions, preprocessing).

**EngineRouter signature sketch:**

```python
class EngineRouter:
    def __init__(self, kokoro: KokoroEngine, qwen: QwenEngine) -> None: ...
    def _resolve_engine(self, voice_name: str) -> KokoroEngine | QwenEngine: ...
    def generate_speech(
        self,
        text: str,
        voice_name: str,
        response_format: str = "ogg",
        noise_dir: Path | None = None,
        seed: int = -1,
    ) -> bytes: ...
    def available_voices(self) -> list[str]: ...
    def engine_status(self) -> dict[str, dict[str, bool]]: ...
```

**Routing logic in `_resolve_engine()`:**
- Check `voice_name in KOKORO_VOICES` → return `self._kokoro`
- Check `voice_name in QWEN_VOICES` → return `self._qwen`
- Otherwise → raise `VoiceNotFoundError` with `available_voices()` in hint

**`generate_speech()` dispatch:**
- Call `_resolve_engine(voice_name)` to get engine
- If engine is `QwenEngine`, forward `seed` parameter
- If engine is `KokoroEngine`, do NOT pass `seed` (it doesn't accept it)
- Return engine's `generate_speech()` result directly

**`engine_status()` return shape** (for Story 1.8 health endpoint):
```python
{
    "kokoro": {"loaded": True, "voices": ["alex", "dora", "santa"]},
    "qwen3": {"loaded": True, "clone_configured": False, "voices": ["clone", "qwen-female", "qwen-male"]},
}
```
Note: `clone` should only appear in voices list if `qwen.is_clone_configured` is True. `qwen-female` and `qwen-male` always available when engine is loaded.

**Test file:** Create `tests/test_routing.py` (new file). Mock both engines — do NOT load real models. Pattern from previous stories: `@patch` on engine methods, assert correct engine's `generate_speech()` was called with correct arguments.

### Anti-Patterns to Avoid

- **DO NOT** re-implement preprocessing inside the router. Each engine already handles its own preprocessing.
- **DO NOT** re-implement post-processing inside the router. Each engine already applies its own pipeline.
- **DO NOT** add char-limit validation in the router. Each engine already enforces its own limit (500/300).
- **DO NOT** add an asyncio.Lock here. That belongs in Story 1.9 (speech endpoint).
- **DO NOT** add HTTP/FastAPI concerns. The router is a pure service-layer class.
- **DO NOT** modify existing `KokoroEngine` or `QwenEngine` classes unless absolutely necessary for the router to work. They are tested and done.

### Module Boundary Rules

- `service.py` contains business logic only — no HTTP, no FastAPI, no Request/Response objects.
- `EngineRouter` depends on `KokoroEngine`, `QwenEngine`, `VoiceNotFoundError`, and the voice constant dicts. All already imported/defined in `service.py`.
- The router will be consumed by `api.py` (Story 1.9) — but do NOT create `api.py` now.

### Import Graph (must remain downward-only)

```
config.py / logging.py          (leaf modules)
    ↓
exceptions.py / voices.py / schemas.py
    ↓
preprocessing.py
    ↓
service.py  ← EngineRouter lives here (alongside KokoroEngine, QwenEngine)
    ↓
api.py / health.py              (Story 1.8, 1.9 — not yet created)
    ↓
main.py                         (Story 1.9 — not yet created)
```

### Project Structure Notes

- New test file: `tests/test_routing.py`
- Modified file: `src/comadre/service.py` (add EngineRouter class)
- No new source modules needed — router lives in existing `service.py`

### Testing Standards

- All tests mocked (no real model loading). Pattern: `@patch("comadre.service.KokoroEngine.generate_speech")` etc.
- Use pytest fixtures for EngineRouter setup with mocked engines
- Test file naming: `test_routing.py` (separate from `test_service.py` which tests individual engines)
- Must pass: `ruff check`, `mypy --strict`, `pytest`, `pre-commit run --all-files`

### Previous Story Intelligence

**From Story 1.5 (Qwen3 engine):**
- `QwenEngine.generate_speech()` accepts `seed` parameter (default -1). Router must forward this for Qwen3 voices only.
- Clone voice requires `is_clone_configured` check — already done inside `QwenEngine.generate_speech()` which raises `InvalidRequestError`. Router does NOT need to duplicate this check, but `engine_status()` should expose it.
- 46 tests added, all passing. Total suite: 232 tests.

**From Story 1.4 (Kokoro engine):**
- `KokoroEngine.generate_speech()` does NOT accept `seed`. Router must not pass it.
- `kokoro-onnx` replaced legacy `kokoclone`. Do not reference kokoclone anywhere.
- All 152 tests pass. Quality gates clean.

**Noise calibration (AC #5) is already correct:**
- Kokoro `_apply_vibrato_warm()` uses room=0.45, hiss=0.24
- Qwen3 `_apply_whatsapp_subtle()` uses room=0.15, hiss=0.08
- Ratio is ~3x as required. No changes needed — just verify in routing tests that the correct engine (and thus correct pipeline) is invoked.

### Git Intelligence

Recent commits show consistent patterns:
- Commit messages: `Implement Story X.Y: description`
- Stories 1.4 and 1.5 each added ~40-50 tests
- All commits pass pre-commit hooks
- `pyproject.toml` and `uv.lock` updated when deps change (not expected for this story — no new deps)

### References

- [Source: _bmad-output/planning-artifacts/epics.md — Story 1.6 acceptance criteria, lines 329-356]
- [Source: _bmad-output/planning-artifacts/architecture.md — Module responsibilities, import graph, voice routing decision D9]
- [Source: src/comadre/service.py — KokoroEngine, QwenEngine, KOKORO_VOICES, QWEN_VOICES constants]
- [Source: src/comadre/exceptions.py — VoiceNotFoundError, InvalidRequestError, GenerationError]
- [Source: _bmad-output/implementation-artifacts/1-5-qwen3-tts-engine-integration.md — Previous story learnings]
- [Source: _bmad-output/implementation-artifacts/1-4-kokoro-tts-engine-integration.md — Previous story learnings]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

No issues encountered. Clean implementation.

### Completion Notes List

- Added `EngineRouter` class to `service.py` (lines 685-748) as a thin routing/aggregation layer
- Router delegates entirely to existing engine `generate_speech()` methods — no preprocessing, post-processing, or validation logic duplicated
- `_resolve_engine()` maps voice names via existing `KOKORO_VOICES` / `QWEN_VOICES` dicts
- `generate_speech()` dispatches to correct engine with proper parameter handling (seed forwarded to Qwen3 only)
- `available_voices()` returns sorted combined list, excluding clone when not configured
- `engine_status()` returns per-engine status dict for downstream health endpoint (Story 1.8)
- 23 new tests in `test_routing.py` covering all 7 subtask areas
- Total test suite: 277 passed, 11 skipped (integration). No regressions.
- All quality gates pass: ruff, mypy strict, pytest, pre-commit

### File List

- `src/comadre/service.py` — added `EngineRouter` class
- `tests/test_routing.py` — new file, 23 routing tests

### Change Log

- 2026-03-24: Implemented EngineRouter class with unified voice routing API and 23 tests
