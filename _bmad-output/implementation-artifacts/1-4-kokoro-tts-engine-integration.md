# Story 1.4: Kokoro TTS Engine Integration

Status: done

## Story

As an **n8n workflow**,
I want the service to generate speech via the Kokoro fp32 engine for built-in voices,
so that customers hear natural-sounding audio responses in Brazilian Portuguese.

## Context

Kokoro TTS uses espeak-ng as sole phonemizer for pt-BR (misaki has no native Portuguese G2P module). espeak-ng has known limitations: open/close vowel confusion, stress errors, no date/time normalization. Mitigations: text preprocessing, custom pt_extra dictionary (67 entries), and sentence chunking are REQUIRED for acceptable quality.

This story REPLACES the legacy KokoClone integration in `service.py` with `kokoro-onnx` from PyPI. KokoClone was evaluated and rejected (Kanade produces 1/10 diction quality on CPU). The existing service.py is a KokoClone wrapper that must be fully rewritten.

**Scope boundary:** This story implements Kokoro engine ONLY. Qwen3 is Story 1.5. Engine routing is Story 1.6. HTTP/API layer is Stories 1.7-1.9.

## Acceptance Criteria

1. **Given** kokoro-onnx is installed as a PyPI dependency
   **When** service.py receives text and voice "santa"/"dora"/"alex"
   **Then** it preprocesses via `normalize_text()` + `chunk_text()`, generates speech via Kokoro fp32, and returns WAV at 24kHz

2. **Given** the espeak-ng pt_extra dictionary files are in place
   **When** Kokoro generates speech containing siglas (CPF, CNPJ, SUS, etc.)
   **Then** pronunciation is correct (verified against 34/34 test cases)

3. **Given** text containing numbers, currency, dates, times
   **When** `preprocessing.py` normalizes
   **Then** num2words converts correctly for pt_BR

4. **Given** text longer than 500 chars
   **When** preprocessing rejects it
   **Then** clear error with char limit hint

5. **Given** text longer than ~200 tokens per chunk
   **When** `chunk_text` splits
   **Then** it splits at sentence boundaries

6. **Given** a valid WAV from Kokoro
   **When** vibrato_warm post-processing runs
   **Then** output is processed through vibrato(4.5Hz, 6%) -> highpass(80Hz) -> bass(+3dB) -> EQ -> exciter -> softclip -> compressor(4:1) -> lowpass(8kHz) -> echo(40ms, 0.12) -> loudnorm(-18 LUFS) -> noise(room=0.45, hiss=0.24) -> loudnorm(-17 LUFS) -> OGG Opus 24kbps 16kHz mono

7. **Given** format "wav"
   **When** service generates audio
   **Then** post-processing still applies but outputs WAV instead of OGG

## Tasks / Subtasks

- [x] Task 1: Update dependencies in pyproject.toml (AC: 1)
  - [x] Remove `kokoclone` from `[project.dependencies]`
  - [x] Remove `[tool.uv.sources]` kokoclone git entry
  - [x] Add `kokoro-onnx>=0.5.0`
  - [x] Remove `core.*`, `torch.*`, `torchaudio.*` from mypy overrides (KokoClone-era dead entries)
  - [x] Remove `soundfile>=0.13` from dependencies (KokoClone-era, unused by Kokoro path)
  - [x] Run `uv sync` to update lock file
- [x] Task 2: Update config.py with Kokoro model settings (AC: 1, 2)
  - [x] Add `kokoro_model_path` setting (default: "models/kokoro-v1.0.onnx")
  - [x] Add `kokoro_voices_path` setting (default: "models/voices-v1.0.bin")
  - [x] Add tests for new config fields
- [x] Task 3: Rewrite service.py for kokoro-onnx (AC: 1, 3, 4, 5)
  - [x] Replace entire KokoClone wrapper with KokoroEngine class
  - [x] Define `KOKORO_VOICES` mapping and `KOKORO_CHAR_LIMIT`
  - [x] Implement `load_model()` using `kokoro_onnx.Kokoro()`
  - [x] Implement `warm_up()` with dummy pt-BR text
  - [x] Implement `generate_speech()` pipeline
  - [x] Add char limit validation raising InvalidRequestError
  - [x] Convert numpy audio arrays to WAV bytes
- [x] Task 4: Implement vibrato_warm post-processing (AC: 6, 7)
  - [x] Implement `_apply_vibrato_warm()` function
  - [x] Build ffmpeg complex filter chain
  - [x] Handle noise WAV file mixing
  - [x] Support both OGG Opus and WAV output paths
- [x] Task 5: Rewrite tests for kokoro-onnx (AC: all)
  - [x] Mock `kokoro_onnx.Kokoro` class instead of `core.cloner.KokoClone`
  - [x] Test voice mapping (santa->pm_santa, etc.)
  - [x] Test char limit validation (500 chars)
  - [x] Test vibrato_warm pipeline invocation
  - [x] Test WAV and OGG output paths
  - [x] Test multi-chunk generation
  - [x] Test model-not-loaded guard
- [x] Task 6: Verify all quality checks pass
  - [x] `uv run ruff check .`
  - [x] `uv run mypy src/`
  - [x] `uv run pytest`
  - [x] `uv run pre-commit run --all-files`

## Dev Notes

### Critical: kokoro-onnx API

Library: `kokoro-onnx` v0.5.0 on PyPI. GitHub: `thewh1teagle/kokoro-onnx`.

**Constructor:**
```python
from kokoro_onnx import Kokoro, EspeakConfig

kokoro = Kokoro(
    model_path="models/kokoro-v1.0.onnx",
    voices_path="models/voices-v1.0.bin",
    espeak_config=EspeakConfig(data_path="/path/to/espeak-ng-data"),
)
```

**Generation:**
```python
# Returns (NDArray[np.float32], int) — audio samples + sample_rate (always 24000)
samples, sample_rate = kokoro.create(
    text="Olá, como vai?",
    voice="pm_santa",      # Built-in voice ID
    speed=1.0,
    lang="pt-br",          # Language code for phonemizer
)
```

**Utility:**
```python
kokoro.get_voices()  # Returns list[str] of available voice IDs
```

**Key constants:**
- `kokoro_onnx.SAMPLE_RATE` = 24000
- `kokoro_onnx.MAX_PHONEME_LENGTH` = 510

### Critical: Kokoro Voice Mapping

User-facing names map to kokoro-onnx built-in voice IDs:

| User Voice | kokoro-onnx ID | Gender |
|------------|----------------|--------|
| `santa`    | `pm_santa`     | Male (default) |
| `dora`     | `pf_dora`      | Female |
| `alex`     | `pm_alex`      | Male alt |

Define as a constant dict in service.py:
```python
KOKORO_VOICES: dict[str, str] = {
    "santa": "pm_santa",
    "dora": "pf_dora",
    "alex": "pm_alex",
}
KOKORO_CHAR_LIMIT = 500
```

Kokoro voices are BUILT-IN (embedded in voices-v1.0.bin). They do NOT use reference WAV files. The `voices.py` module's `VoiceInfo`/`discover_voices()` is for Qwen3 clone reference detection only — do NOT use it for Kokoro voice validation.

### Critical: espeak-ng pt_extra Dictionary

The `EspeakConfig(data_path=...)` parameter tells kokoro-onnx where to find espeak-ng data including the custom pt_extra dictionary. This is the correct way to handle the pt_extra path — do NOT set `os.environ["ESPEAK_DATA_PATH"]` (misaki/espeakng_loader ignores that env var).

Use the `espeak_data_path` setting from `config.py` to pass through to `EspeakConfig`. When `None`, kokoro-onnx uses the bundled espeakng_loader data path.

**Docker gotcha:** In production, the compiled pt_extra data files (pt_dict, phondata, phonindex, phontab) must exist in BOTH:
1. System espeak-ng path (`/usr/local/share/espeak-ng-data/`)
2. espeakng_loader bundled path (`.venv/lib/.../espeakng_loader/espeak-ng-data/`)

This is a Docker/deployment concern (Story 2.1), NOT this story's scope. For this story, if `espeak_data_path` is configured, pass it to `EspeakConfig`. If not, rely on bundled data.

### Critical: Replacing KokoClone in service.py

The current `service.py` (174 lines) is a KokoClone wrapper. It must be FULLY REWRITTEN. Key differences:

| Aspect | KokoClone (current) | kokoro-onnx (target) |
|--------|---------------------|----------------------|
| Import | `from core.cloner import KokoClone` | `from kokoro_onnx import Kokoro, EspeakConfig` |
| Init | `KokoClone()` (no args) | `Kokoro(model_path, voices_path, espeak_config)` |
| Generate | `cloner.generate(text, lang, ref_wav, out_path)` writes WAV file | `kokoro.create(text, voice, lang="pt-br")` returns `(NDArray, int)` |
| Voices | Uses reference WAV from VoiceInfo.path | Built-in voice IDs (pm_santa, etc.) |
| Output | WAV file on disk | numpy float32 array in memory |

**What to keep from current service.py:**
- `_concatenate_wavs()` helper — reuse for multi-chunk WAV concatenation
- Logger setup pattern (`get_logger("request")`, `get_logger("startup")`)
- Error handling pattern (catch exceptions, raise GenerationError)
- Temp file cleanup in finally block

**What to change:**
- Replace `TTSService` class internals entirely
- Replace `_encode_ogg()` with `_apply_vibrato_warm()` (full pipeline, not just OGG encoding)
- Generate method returns numpy arrays, must convert to WAV bytes using `wave` + `numpy`
- Voice lookup uses `KOKORO_VOICES` dict, not `VoiceInfo` list
- Add char limit validation before preprocessing

### Critical: numpy-to-WAV Conversion

kokoro-onnx returns `(NDArray[np.float32], int)` — float32 samples in [-1.0, 1.0] range at 24kHz. Convert to WAV bytes:

```python
import io, wave, numpy as np

def _samples_to_wav(samples: np.ndarray, sample_rate: int) -> bytes:
    """Convert float32 audio samples to WAV bytes."""
    # Scale to int16 range
    int16_samples = (samples * 32767).astype(np.int16)
    buf = io.BytesIO()
    with wave.open(buf, "wb") as wf:
        wf.setnchannels(1)
        wf.setsampwidth(2)  # 16-bit
        wf.setframerate(sample_rate)
        wf.writeframes(int16_samples.tobytes())
    return buf.getvalue()
```

Add `numpy` to mypy overrides if not already present (it's a transitive dep of kokoro-onnx but may need explicit type stubs).

### Critical: vibrato_warm Post-Processing Pipeline

The full pipeline spec from architecture:

```
vibrato(4.5Hz, 6%) -> highpass(80Hz) -> bass(+3dB) -> EQ(2.5kHz) ->
exciter(4.5kHz) -> softclip -> compressor(4:1) -> lowpass(8kHz) ->
echo(40ms, 0.12) -> loudnorm(-18 LUFS) -> noise(room=0.45, hiss=0.24) ->
loudnorm(-17 LUFS) -> OGG Opus 24kbps 16kHz mono
```

**Implementation approach:** Two-stage ffmpeg pipeline.

**Stage 1 — Audio effects (single ffmpeg call with filter chain):**
```
ffmpeg -i input.wav -af "
  vibrato=f=4.5:d=0.06,
  highpass=f=80,
  bass=g=3:f=200,
  equalizer=f=2500:width_type=o:width=1.5:g=2,
  aexciter=freq=4500,
  asoftclip=type=tanh,
  acompressor=ratio=4:threshold=-20dB:attack=5:release=50,
  lowpass=f=8000,
  aecho=0.8:0.8:40:0.12,
  loudnorm=I=-18:TP=-2:LRA=7
" -ar 24000 -f wav pipe:1
```

**Stage 2 — Noise mixing + final encoding:**
```
ffmpeg -i pipe:0 -i room_noise.wav -i hiss_noise.wav -filter_complex "
  [1:a]volume=0.45[room];
  [2:a]volume=0.24[hiss];
  [0:a][room][hiss]amix=inputs=3:duration=shortest,
  loudnorm=I=-17:TP=-1.5:LRA=7
" -c:a libopus -b:a 24k -ar 16000 -ac 1 -f ogg pipe:1
```

For WAV output, replace the final encoding with `-f wav pipe:1` (keep 24kHz, skip opus).

**Noise WAV files:** Required for the pipeline. Place in `assets/noise/` or similar. For development, create minimal placeholder noise files. In production, proper noise files are baked into the Docker image (Story 2.1).

If noise files are absent, log a warning and skip the noise mixing stage (graceful degradation). This prevents blocking development while noise files are sourced.

**Implementation as a function:**
```python
def _apply_vibrato_warm(
    wav_bytes: bytes,
    response_format: str,  # "ogg" or "wav"
    noise_dir: Path | None = None,
) -> bytes:
```

### Critical: InvalidRequestError for Char Limit

AC #4 requires rejecting text >500 chars. The current `exceptions.py` does NOT have `InvalidRequestError`. You must add it:

```python
class InvalidRequestError(CumadreError):
    """Raised when request parameters are invalid."""
    def __init__(self, message: str, hint: str) -> None:
        super().__init__(
            message=message,
            status_code=400,
            error_type="invalid_request_error",
            hint=hint,
        )
```

Validate in `generate_speech()` BEFORE preprocessing:
```python
if len(text) > KOKORO_CHAR_LIMIT:
    raise InvalidRequestError(
        message=f"Text exceeds {KOKORO_CHAR_LIMIT} character limit ({len(text)} chars)",
        hint=f"Shorten your text to {KOKORO_CHAR_LIMIT} characters or fewer.",
    )
```

[Source: _bmad-output/planning-artifacts/architecture.md#Error-Response-Format]
[Source: _bmad-output/planning-artifacts/epics.md#Story-1.7]

Note: `InvalidRequestError` is also needed by Story 1.7 (Exception Handling & Request Schemas). Adding it here is fine — it follows the architecture.

### Critical: Known kokoro-onnx Issues (v0.5.0)

1. **Issue #184 — IndexError on long phoneme sequences:** When phonemes exceed `MAX_PHONEME_LENGTH` (510), an IndexError occurs. Mitigation: our `chunk_text()` (max 200 tokens) keeps chunks well under this limit. Safe.

2. **Issue #148 — Memory leak on long sentences:** onnxruntime doesn't release memory for very long inputs. Mitigation: chunking + daily restart safety net. Acceptable.

3. **phonemizer-fork >=3.3.2** fixes the original Kokoro memory leak. This version is a transitive dependency of kokoro-onnx 0.5.0.

4. **Speed parameter range:** Must be 0.5 to 2.0 (asserted by library). Default 1.0.

5. **trim=True default:** Trims leading/trailing silence. First chunk takes ~2s to trim. Keep enabled.

### Model Files (Not Part of This Story)

kokoro-onnx requires two model files downloaded to the models directory:
- `kokoro-v1.0.onnx` (310 MB fp32) from GitHub releases
- `voices-v1.0.bin` (27 MB) from GitHub releases

No programmatic download API — models must be manually downloaded or handled by Docker entrypoint (Story 2.1). For dev testing, mock the Kokoro class. For integration tests (`pytest -m slow`), models must be present.

### generate_speech() Pipeline Summary

```
Input: (text: str, voice_name: str, response_format: str)
  |
  v
1. Validate voice_name in KOKORO_VOICES → VoiceNotFoundError if missing
2. Validate len(text) <= 500 → InvalidRequestError if exceeded
3. normalized = normalize_text(text)
4. chunks = chunk_text(normalized, max_tokens=200)
5. For each chunk:
     samples, sr = kokoro.create(chunk, KOKORO_VOICES[voice_name], lang="pt-br")
     wav_bytes = _samples_to_wav(samples, sr)
6. full_wav = _concatenate_wavs(wav_parts)
7. result = _apply_vibrato_warm(full_wav, response_format)
8. Return result bytes
```

### Project Structure Notes

**Files to modify:**
- `pyproject.toml` — Swap kokoclone for kokoro-onnx
- `src/cumadre/config.py` — Add model path settings
- `src/cumadre/service.py` — Full rewrite (KokoClone -> kokoro-onnx)
- `src/cumadre/exceptions.py` — Add InvalidRequestError
- `tests/test_service.py` — Full rewrite (mock kokoro-onnx)
- `tests/test_exceptions.py` — Add InvalidRequestError tests

**Files NOT to modify:**
- `src/cumadre/preprocessing.py` — Already complete, reuse as-is
- `src/cumadre/voices.py` — For Qwen3 clone reference, not Kokoro
- `src/cumadre/logging.py` — Already complete
- `src/cumadre/__init__.py` — No changes needed

**Import graph compliance (downward only):**
```
config.py, logging.py          ← leaf nodes
exceptions.py                  ← depends on nothing in app
preprocessing.py               ← depends on config.py only (via num2words)
service.py                     ← imports: config, logging, exceptions, preprocessing
```

`service.py` must NOT import from `api.py`, `health.py`, `main.py`, `schemas.py`, or `voices.py` (for Kokoro path).

### Testing Approach

**Mock strategy:** Mock `kokoro_onnx.Kokoro` class at the module level. Do NOT load real models in unit tests.

```python
@pytest.fixture()
def service() -> KokoroEngine:
    """Return a KokoroEngine with mocked Kokoro instance."""
    svc = KokoroEngine()
    mock_kokoro = MagicMock()
    # Return float32 samples at 24kHz
    mock_kokoro.create.return_value = (np.zeros(24000, dtype=np.float32), 24000)
    mock_kokoro.get_voices.return_value = ["pm_santa", "pf_dora", "pm_alex"]
    svc._kokoro = mock_kokoro
    return svc
```

**Test vibrato_warm:** Mock `subprocess.run` to verify ffmpeg is called with the correct filter chain arguments. Do NOT run real ffmpeg in unit tests.

**Logger capture pattern** (from Story 1.3): Enable `propagate=True` on the logger fixture, restore in teardown.

### Previous Story Intelligence

**From Story 1.3 (Voice Discovery):**
- Used `wave` stdlib for WAV reading — same pattern for `_samples_to_wav()`
- VoiceInfo is a frozen dataclass — do not modify
- `discover_voices()` takes a `Path` parameter, pure function — Kokoro does not use this

**From Story 1.2 (Config & Logging):**
- `get_logger(component)` returns isolated logger with `propagate=False`
- Settings uses `@lru_cache` — clear cache in tests with `get_settings.cache_clear()`
- No env_prefix: bare env var names (API_KEY, not CUMADRE_API_KEY)

**From Story 1.1 (Scaffolding):**
- Build backend: `uv_build` (not hatchling)
- Dependency groups follow PEP 735 pattern
- mypy strict mode + pydantic plugin enabled
- ruff select rules: E F I UP B SIM N C4 PTH RUF

### Git Intelligence

Recent commits show the codebase was recently refactored for the dual-engine architecture pivot (KokoClone -> Kokoro + Qwen3). The comment in pyproject.toml line 17 explicitly marks kokoclone as LEGACY to be replaced by kokoro-onnx in this story.

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story-1.4]
- [Source: _bmad-output/planning-artifacts/architecture.md#Kokoro-fp32-Integration]
- [Source: _bmad-output/planning-artifacts/architecture.md#Post-Processing-Pipelines]
- [Source: _bmad-output/planning-artifacts/architecture.md#Module-Boundaries]
- [Source: _bmad-output/planning-artifacts/prd.md#FR4-FR5b]
- [Source: docs/feasibility-report-tts-engine.md#Kokoro-ONNX]
- [Source: docs/espeak-ng-custom-dictionary.md]
- [Source: docs/api-architecture.md#Preprocessing]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

- mypy strict mode required `Any` type for `_kokoro` attribute (kokoro_onnx lacks full type stubs)
- `EspeakConfig` not explicitly exported from `kokoro_onnx` — used `kokoro_onnx.EspeakConfig` with `type: ignore[attr-defined]`
- `test_feasibility.py` had to be rewritten: KokoClone removed, torch uninstalled, old fixtures broken

### Completion Notes List

- Replaced KokoClone dependency with kokoro-onnx 0.5.0 from PyPI
- Fully rewrote `service.py`: new `KokoroEngine` class with built-in voice mapping (santa/dora/alex → pm_santa/pf_dora/pm_alex)
- Added `InvalidRequestError` to exception hierarchy for 400-level validation errors
- Implemented two-stage ffmpeg vibrato_warm pipeline with graceful noise degradation
- Added `kokoro_model_path` and `kokoro_voices_path` settings to config
- 152 tests pass, 11 integration tests skip (no model files), 0 regressions
- All quality gates green: ruff, mypy strict, pytest, pre-commit

### Change Log

- 2026-03-23: Story 1.4 implemented — KokoClone → kokoro-onnx migration complete

### File List

- pyproject.toml (modified — swapped kokoclone for kokoro-onnx, cleaned mypy overrides)
- uv.lock (modified — regenerated by uv sync)
- src/cumadre/config.py (modified — added kokoro_model_path, kokoro_voices_path)
- src/cumadre/service.py (rewritten — KokoroEngine replacing TTSService/KokoClone)
- src/cumadre/exceptions.py (modified — added InvalidRequestError)
- tests/test_service.py (rewritten — mocks kokoro-onnx instead of KokoClone)
- tests/test_config.py (modified — added tests for new config fields)
- tests/test_exceptions.py (modified — added InvalidRequestError tests)
- tests/test_feasibility.py (rewritten — uses kokoro-onnx for integration tests)
