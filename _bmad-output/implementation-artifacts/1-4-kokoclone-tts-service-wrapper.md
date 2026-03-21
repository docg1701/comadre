# Story 1.4: KokoClone TTS Service Wrapper

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **n8n workflow**,
I want the service to generate cloned-voice speech from text,
so that customers hear natural-sounding audio responses.

## Acceptance Criteria

1. **Given** KokoClone is installed as a uv git dependency **When** service.py receives text, a voice name, and format "wav" **Then** it generates Brazilian Portuguese speech via Kokoro TTS, converts it to the cloned voice via Kanade using the reference WAV, and returns WAV bytes at 24kHz

2. **Given** a valid text input and format "ogg" **When** service.py generates audio **Then** it encodes the WAV output to OGG via ffmpeg subprocess and returns valid OGG bytes

3. **Given** a voice name that has no corresponding reference WAV **When** service.py attempts to generate audio **Then** it raises a `VoiceNotFoundError` (not an HTTPException) with the requested voice name and list of available voices

4. **Given** KokoClone fails during generation **When** service.py catches the model error **Then** it raises a `GenerationError` with a descriptive message and logs the full traceback at ERROR level

## Tasks / Subtasks

- [x] Task 1: Add KokoClone as uv git dependency (AC: #1)
  - [x] 1.1: Run `uv add kokoclone --git https://github.com/Ashish-Patnaik/kokoclone` to add KokoClone and all its transitive dependencies (torch, torchaudio, kokoro-onnx, misaki, kanade-tokenizer, etc.)
  - [x] 1.2: Verify `uv sync` succeeds and KokoClone is importable
  - [x] 1.3: Verify the correct import path — architecture expects `from core.cloner import KokoClone`; if the package structure differs, adapt the import in service.py accordingly
- [x] Task 2: Create minimal `src/cumadre/exceptions.py` (AC: #3, #4)
  - [x] 2.1: Define `CumadreError` base exception with `status_code: int`, `error_type: str`, `hint: str` instance attributes and `message: str`
  - [x] 2.2: Define `VoiceNotFoundError(CumadreError)` — status_code=404, error_type="not_found_error"
  - [x] 2.3: Define `GenerationError(CumadreError)` — status_code=500, error_type="server_error"
  - [x] 2.4: Story 1.5 will expand this module with AuthenticationError, InvalidRequestError, ServiceUnavailableError, and the centralized FastAPI exception handlers
- [x] Task 3: Create `src/cumadre/service.py` (AC: #1-#4)
  - [x] 3.1: Define `TTSService` class with `__init__`, `load_model`, `warm_up`, `generate_speech`
  - [x] 3.2: Implement `load_model()` — imports and instantiates KokoClone
  - [x] 3.3: Implement `warm_up(reference_wav: Path)` — runs dummy inference to preload model internals
  - [x] 3.4: Implement `generate_speech(text, voice_name, response_format, voices)` — resolves voice, generates WAV via KokoClone, optionally encodes to OGG
  - [x] 3.5: Implement `_encode_ogg(wav_path: Path) -> bytes` — ffmpeg subprocess converting WAV to OGG (~5 lines)
- [x] Task 4: Write tests for exceptions module (AC: #3, #4)
  - [x] 4.1: Create `tests/test_exceptions.py`
  - [x] 4.2: Test CumadreError attributes (status_code, error_type, hint, message)
  - [x] 4.3: Test VoiceNotFoundError has correct status_code and error_type
  - [x] 4.4: Test GenerationError has correct status_code and error_type
- [x] Task 5: Write tests for service module (AC: #1-#4)
  - [x] 5.1: Create `tests/test_service.py`
  - [x] 5.2: Test `generate_speech` with WAV format returns bytes (mock KokoClone)
  - [x] 5.3: Test `generate_speech` with OGG format returns bytes (mock KokoClone + ffmpeg)
  - [x] 5.4: Test voice name not found raises `VoiceNotFoundError` with correct message
  - [x] 5.5: Test KokoClone exception is wrapped in `GenerationError` with traceback logged
  - [x] 5.6: Test `load_model` instantiates KokoClone
  - [x] 5.7: Test `warm_up` calls generate with dummy text
- [x] Task 6: Validation pass
  - [x] 6.1: Run `uv run ruff check .` — must pass
  - [x] 6.2: Run `uv run mypy src/` — must pass (strict mode)
  - [x] 6.3: Run `uv run pytest` — all tests must pass (including Stories 1.1-1.3 tests)
  - [x] 6.4: Run `uv run pre-commit run --all-files` — must pass

## Dev Notes

### Critical Architecture Constraints

**Module Position in Import Graph:**
- `service.py` is a mid-level module: imported by `api.py` only
- `service.py` imports from: `config.py`, `logging.py`, `exceptions.py`, `voices.py`
- `service.py` must NOT import from: `main.py`, `api.py`, `schemas.py`, `health.py`
- No circular imports — dependencies flow downward only

**Module Responsibility:**
- `service.py` handles: KokoClone wrapping, TTS generation, voice cloning, OGG encoding
- `service.py` must NOT contain: HTTP concerns, FastAPI dependencies, request/response handling
- All function signatures use typed Python args and return bytes — no Request/Response objects

**Logging:**
- Use `get_logger("request")` — component tag is `request` for audio generation operations (from UX-DR3 component list)
- For model loading/warm-up, use `get_logger("startup")` — these happen during application startup
- All log messages must be plain ASCII, no emoji, no ANSI codes (UX-DR10)
- Log full tracebacks at ERROR level for KokoClone failures, using `logger.error("...", exc_info=True)`

**No raw `os.environ`:** All configuration comes from function parameters or the Settings class.

**No `print()` statements:** All output through structured logging.

**No raw HTTPException:** All errors via CumadreError subclasses.

### exceptions.py Implementation Guide

Create a minimal exceptions module. Story 1.5 will expand it with the remaining exceptions and FastAPI handlers.

```python
"""Custom exception hierarchy for CUMADRE."""


class CumadreError(Exception):
    """Base exception for all CUMADRE errors."""

    def __init__(
        self,
        message: str,
        *,
        status_code: int,
        error_type: str,
        hint: str,
    ) -> None:
        super().__init__(message)
        self.message = message
        self.status_code = status_code
        self.error_type = error_type
        self.hint = hint


class VoiceNotFoundError(CumadreError):
    """Raised when a requested voice is not available."""

    def __init__(self, voice: str, available: list[str]) -> None:
        super().__init__(
            message=f"Voice '{voice}' not found",
            status_code=404,
            error_type="not_found_error",
            hint=f"Available voices: {available}. Place WAV files (3-10s) in the /voices/ directory.",
        )
        self.voice = voice
        self.available = available


class GenerationError(CumadreError):
    """Raised when TTS generation fails."""

    def __init__(self, message: str) -> None:
        super().__init__(
            message=message,
            status_code=500,
            error_type="server_error",
            hint="Check server logs for the full traceback. The TTS model may need restarting.",
        )
```

**Key design decisions:**
- `CumadreError.__init__` takes keyword-only args for `status_code`, `error_type`, `hint` — prevents positional arg mistakes
- `VoiceNotFoundError` takes `voice` and `available` as convenience args, constructs the full message/hint automatically
- `GenerationError` takes only a `message` — hint is standardized since the operator action is always the same
- Story 1.5 will add: `AuthenticationError(401)`, `InvalidRequestError(400)`, `ServiceUnavailableError(503)`, and the centralized FastAPI `@app.exception_handler(CumadreError)` function

### service.py Implementation Guide

```python
"""KokoClone TTS service wrapper."""

from __future__ import annotations

import subprocess
import tempfile
from pathlib import Path
from typing import TYPE_CHECKING

from cumadre.exceptions import GenerationError, VoiceNotFoundError
from cumadre.logging import get_logger
from cumadre.voices import VoiceInfo, list_voice_names

if TYPE_CHECKING:
    from core.cloner import KokoClone

logger = get_logger("request")
startup_logger = get_logger("startup")

LANGUAGE = "pt"  # Brazilian Portuguese — hardcoded per FR4


class TTSService:
    """Wraps KokoClone for TTS generation with voice cloning."""

    def __init__(self) -> None:
        self._cloner: KokoClone | None = None

    @property
    def is_loaded(self) -> bool:
        return self._cloner is not None

    def load_model(self) -> None:
        from core.cloner import KokoClone  # lazy import — heavy dependency
        startup_logger.info("Loading KokoClone model...")
        self._cloner = KokoClone()
        startup_logger.info("KokoClone model loaded")

    def warm_up(self, reference_wav: Path) -> None:
        startup_logger.info("Running warm-up inference...")
        with tempfile.NamedTemporaryFile(suffix=".wav", delete=True) as tmp:
            self._cloner.generate("test", LANGUAGE, str(reference_wav), tmp.name)
        startup_logger.info("Warm-up complete")

    def generate_speech(
        self,
        text: str,
        voice_name: str,
        response_format: str,
        voices: list[VoiceInfo],
    ) -> bytes:
        # Resolve voice
        voice = next((v for v in voices if v.name == voice_name), None)
        if voice is None:
            raise VoiceNotFoundError(voice=voice_name, available=list_voice_names(voices))

        # Generate cloned-voice speech
        try:
            with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
                tmp_path = Path(tmp.name)
            self._cloner.generate(text, LANGUAGE, str(voice.path), str(tmp_path))
            if response_format == "ogg":
                return _encode_ogg(tmp_path)
            return tmp_path.read_bytes()
        except (VoiceNotFoundError, GenerationError):
            raise
        except Exception as exc:
            logger.error("TTS generation failed: %s", exc, exc_info=True)
            raise GenerationError(f"TTS generation failed: {exc}") from exc
        finally:
            tmp_path.unlink(missing_ok=True)
```

**Key design decisions:**

- **Lazy import of KokoClone:** `from core.cloner import KokoClone` is inside `load_model()`, not at module level. This prevents import errors when running tests without the real model, and avoids loading torch at import time.
- **TYPE_CHECKING guard:** The type hint for `self._cloner` uses `KokoClone` via `TYPE_CHECKING` block — this gives mypy the type info without triggering the import at runtime.
- **`generate_speech()` takes `voices: list[VoiceInfo]`:** The voice list is passed as a parameter, not stored in the service. State management is the caller's responsibility (main.py lifespan in Story 1.7).
- **Language hardcoded to `"pt"`:** FR4 specifies Brazilian Portuguese. KokoClone internally maps `lang="pt"` to `EspeakG2P(language="pt-br")`.
- **Temp file for KokoClone output:** KokoClone's `generate()` writes to a file path. We create a temp file, let KokoClone write to it, read the bytes, and clean up.
- **Exception re-raise pattern:** `VoiceNotFoundError` is raised before calling KokoClone. The `except Exception` catches only KokoClone/ffmpeg failures and wraps them in `GenerationError`. The `finally` block ensures temp file cleanup.
- **24kHz WAV output:** KokoClone outputs at 24kHz by default (from `KanadeModelConfig.sample_rate = 24000`). No resampling needed.

### OGG Encoding via ffmpeg

```python
def _encode_ogg(wav_path: Path) -> bytes:
    """Encode a WAV file to OGG Opus format using ffmpeg."""
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-i", str(wav_path), "-c:a", "libopus", "-f", "ogg", "pipe:1"],
            capture_output=True,
            check=True,
        )
    except subprocess.CalledProcessError as exc:
        logger.error("ffmpeg encoding failed: %s", exc.stderr.decode())
        raise GenerationError("Audio encoding to OGG failed") from exc
    return result.stdout
```

**Notes:**
- `-y` overwrites without prompting (not needed for pipe output but harmless)
- `-c:a libopus` uses the Opus codec (high quality, small files)
- `-f ogg` forces OGG container format
- `pipe:1` writes to stdout instead of a file
- `capture_output=True` captures both stdout (the audio) and stderr (ffmpeg logs)
- `check=True` raises CalledProcessError on non-zero exit
- ffmpeg is already a system dependency (installed in Docker image for this purpose)

### KokoClone API Reference

**Import:** `from core.cloner import KokoClone` (verify at implementation time — may be `from kokoclone.core.cloner import KokoClone` depending on package install)

**Constructor:** `KokoClone()` — no arguments needed. Auto-detects CPU/GPU. Downloads models from HuggingFace on first run (~500MB).

**Generate method:**
```python
cloner.generate(
    text: str,         # Input text to synthesize
    lang: str,         # Language code: "pt" for Brazilian Portuguese
    reference_audio: str,  # Path to reference WAV file (3-10s, for voice cloning)
    output_path: str = "output.wav"  # Output WAV file path
)
```

**Pipeline (two phases):**
1. Kokoro TTS: text → phonemes (espeak-ng pt-br) → speech audio (default voice)
2. Kanade voice conversion: source audio + reference WAV → cloned voice audio (24kHz)

**Models downloaded:**
- `PatnaikAshish/kokoclone` on HuggingFace (~300MB): Kokoro ONNX model, voice embeddings
- `frothywater/kanade-12.5hz` on HuggingFace: Kanade voice conversion model + Vocos vocoder

**System dependencies required:** espeak-ng, ffmpeg, libsndfile

### Testing Strategy

**All tests mock KokoClone.** No real model loading, no real TTS inference in tests.

**Mocking approach:**
```python
from unittest.mock import MagicMock, patch
import wave
import tempfile
from pathlib import Path

def _create_wav_bytes(duration: float = 1.0, framerate: int = 24000) -> bytes:
    """Create minimal WAV bytes for testing."""
    import io
    buf = io.BytesIO()
    n_frames = int(framerate * duration)
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)
        wf.setframerate(framerate)
        wf.writeframes(b"\x00\x00" * n_frames)
    return buf.getvalue()


# Mock KokoClone's generate() to write a real WAV file
def _mock_generate(text, lang, ref_audio, output_path="output.wav"):
    """Write a valid WAV to the output path (simulates KokoClone)."""
    wav_bytes = _create_wav_bytes()
    Path(output_path).write_bytes(wav_bytes)
```

**Test cases:**

| Test | AC | What to assert |
|------|-----|---------------|
| WAV generation | #1 | Returns non-empty bytes, mock generate called with correct args |
| OGG generation | #2 | Returns non-empty bytes, ffmpeg called or output is valid OGG |
| Voice not found | #3 | Raises VoiceNotFoundError with voice name and available list |
| Model failure | #4 | Raises GenerationError, traceback logged at ERROR level |
| load_model | #1 | KokoClone constructor called |
| warm_up | #1 | generate called with "test" text |

**Testing OGG encoding:**
- Option A: Mock `subprocess.run` and verify ffmpeg command args
- Option B: If ffmpeg is available in the test environment, do a real encode of a short WAV file
- Prefer Option A for CI reliability; Option B as an integration test

**Log assertion pattern:**
Since `request` and `startup` loggers have `propagate=False`, use the same pattern as Story 1.3:
- Add a temporary handler or set `propagate=True` during test
- Use `caplog` with the appropriate logger name

### Anti-Patterns to Avoid

- Do NOT import KokoClone at module level — lazy import inside `load_model()` only
- Do NOT use `soundfile` for WAV reading in service.py — KokoClone handles audio I/O; we just read the output file as raw bytes via `Path.read_bytes()`
- Do NOT add HTTP concerns (Request, Response, HTTPException, FastAPI decorators) to service.py
- Do NOT store the voices list in TTSService — pass it as a parameter to `generate_speech()`
- Do NOT hardcode file paths for temp files — use `tempfile.NamedTemporaryFile`
- Do NOT create `api.py`, `main.py`, `health.py`, or `schemas.py` — those belong to later stories
- Do NOT add FastAPI exception handlers in exceptions.py — the `@app.exception_handler` registration belongs to Story 1.5/1.7
- Do NOT add more exception subclasses than needed (AuthenticationError, InvalidRequestError, ServiceUnavailableError belong to Story 1.5)
- Do NOT use `os.environ` — all config via function parameters
- Do NOT add emoji to log messages (UX-DR10)
- Do NOT make `generate_speech` async — it's CPU-bound; the caller (api.py in Story 1.7) handles async wrapping

### Previous Story Intelligence

**From Story 1.3 (done):**
- `VoiceInfo` frozen dataclass with `name: str`, `path: Path`, `duration_seconds: float` — use `voice.path` to get the reference WAV path for KokoClone
- `list_voice_names(voices)` returns sorted list of voice names — use this in VoiceNotFoundError hint
- `discover_voices(voices_dir: Path)` returns `list[VoiceInfo]` — the caller will pass this to `generate_speech()`
- Logger pattern: `get_logger("voice")` with `propagate=False` — same pattern for `get_logger("request")` and `get_logger("startup")`

**From Story 1.2 (done):**
- `get_logger(component)` returns pipe-formatted logger with component tag
- Logger has `propagate=False` — for test assertions, add a test handler or set propagate temporarily
- Log levels: INFO, WARN, ERROR (use `logger.error("...", exc_info=True)` for traceback logging)

**From Story 1.1 (done):**
- `soundfile>=0.13` is already in pyproject.toml dependencies — used by KokoClone internally, not by service.py directly
- Pre-commit hooks: ruff, mypy (strict), hadolint, yamllint, shellcheck, markdownlint
- Pre-commit excludes `_bmad-output/`, `_bmad/`, `.claude/`
- Commit message format: "Add [feature description] (Story X.Y)"

**Git patterns from recent commits:**
- `d9ca8f6` Add voice discovery and validation module (Story 1.3)
- `be201ea` Add configuration and structured logging (Story 1.2)
- `3c81bad` Add project scaffolding and quality tooling (Story 1.1)

### Dependency Installation Notes

**KokoClone is a heavyweight dependency.** Adding it will pull in:
- `torch>=2.10.0`, `torchaudio>=2.10.0` (~2GB download)
- `kokoro-onnx[gpu]>=0.5.0`
- `misaki[en,ja,zh]>=0.9.4`
- `kanade-tokenizer` (git dependency from frothywater/kanade-tokenizer)
- `huggingface-hub`, `gradio`, `ninja`, etc.

**Installation command:**
```bash
uv add kokoclone --git https://github.com/Ashish-Patnaik/kokoclone
```

**Verification:**
```bash
uv sync
python -c "from core.cloner import KokoClone; print('OK')"
```

If the import path is different from `core.cloner`, check the installed package structure:
```bash
python -c "import kokoclone; print(kokoclone.__file__)"
```

**mypy considerations:** KokoClone and its dependencies (torch, etc.) may not have complete type stubs. You may need to add `[[tool.mypy.overrides]]` sections to pyproject.toml:
```toml
[[tool.mypy.overrides]]
module = ["core.*", "torch.*", "torchaudio.*", "kokoro_onnx.*"]
ignore_missing_imports = true
```

### Project Structure Notes

**Files to create in this story:**
```
src/cumadre/exceptions.py     (new — minimal, expanded in Story 1.5)
src/cumadre/service.py        (new)
tests/test_exceptions.py      (new)
tests/test_service.py         (new)
```

**Files to modify:**
```
pyproject.toml                (add KokoClone git dependency + mypy overrides)
uv.lock                      (auto-updated by uv add)
```

**Files NOT to create or modify:**
- `src/cumadre/api.py` — belongs to Story 1.7
- `src/cumadre/main.py` — belongs to Story 1.7
- `src/cumadre/health.py` — belongs to Story 1.6
- `src/cumadre/schemas.py` — belongs to Story 1.5
- `src/cumadre/config.py` — no changes needed
- `src/cumadre/logging.py` — no changes needed
- `src/cumadre/voices.py` — no changes needed

**Existing files for reference (do not modify):**
- `src/cumadre/voices.py` — VoiceInfo dataclass, discover_voices(), list_voice_names()
- `src/cumadre/logging.py` — get_logger(component), PipeFormatter
- `src/cumadre/config.py` — Settings class with api_key, default_voice, workers, port

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#KokoClone Integration Discovery]
- [Source: _bmad-output/planning-artifacts/architecture.md#Module Responsibility — service.py]
- [Source: _bmad-output/planning-artifacts/architecture.md#Import Dependency Graph — service.py imports exceptions.py, voices.py]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision D1 — KokoClone uv git dependency]
- [Source: _bmad-output/planning-artifacts/architecture.md#Decision D7 — OGG encoding via ffmpeg subprocess]
- [Source: _bmad-output/planning-artifacts/architecture.md#Data Flow — service.py resolve voice, KokoClone.generate, ffmpeg encode]
- [Source: _bmad-output/planning-artifacts/architecture.md#Error Handling — CumadreError hierarchy]
- [Source: _bmad-output/planning-artifacts/architecture.md#Startup Sequence — load model, warm-up inference]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 1.4: KokoClone TTS Service Wrapper]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 1.5: Exception Handling & Request Schemas — expanded in next story]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md#UX-DR7: Error Response Trinity]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md#UX-DR10: Terminal Accessibility]
- [Source: KokoClone GitHub — github.com/Ashish-Patnaik/kokoclone]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

- Fixed test_load_model: removed stray @patch decorator that injected an extra positional arg
- Fixed replace_all collateral: `# noqa: SLF001` removal collapsed lines; restored proper newlines

### Completion Notes List

- KokoClone installed as uv git dependency (180 packages resolved, 129 installed including torch 2.10, kanade-tokenizer, kokoro-onnx)
- Import path confirmed as `from core.cloner import KokoClone` — matches architecture spec
- exceptions.py: CumadreError base with keyword-only attrs, VoiceNotFoundError(404), GenerationError(500)
- service.py: TTSService with lazy KokoClone import, warm_up, generate_speech (WAV/OGG), _encode_ogg via ffmpeg subprocess
- Added mypy overrides for untyped third-party packages (core.*, torch.*, torchaudio.*, kokoro_onnx.*, soundfile.*)
- 18 new tests (test_exceptions: 12, test_service: 14) — all mocking KokoClone, no real model loading
- All 80 tests pass (0 regressions), ruff clean, mypy strict clean, pre-commit all hooks pass

### Change Log

- 2026-03-21: Implemented Story 1.4 — KokoClone TTS service wrapper with exceptions module, service module, and full test coverage

### File List

- pyproject.toml (modified — added kokoclone dependency + mypy overrides)
- uv.lock (modified — auto-updated by uv add)
- src/cumadre/exceptions.py (new)
- src/cumadre/service.py (new)
- tests/test_exceptions.py (new)
- tests/test_service.py (new)
