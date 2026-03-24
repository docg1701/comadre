# Story 1.5: Qwen3-TTS Engine Integration

Status: done

## Story

As an **n8n workflow**,
I want the service to generate speech via the Qwen3-TTS engine for clone and Qwen voices,
so that customers hear cloned-voice or alternative voice audio responses.

## Context

Qwen3-TTS runs as a C++ Q8_0 quantized binary (`qwen3-tts-cli`) invoked via subprocess. It supports voice cloning from a reference WAV and deterministic generation via a custom seed patch. Unlike Kokoro (embedded Python library), Qwen3 is an external binary — all interaction is via subprocess with stdin/stdout/files.

**Scope boundary:** This story implements Qwen3 engine ONLY. Engine routing is Story 1.6. HTTP/API layer is Stories 1.7-1.9. This story creates `QwenEngine` as a peer to `KokoroEngine` in `service.py`.

## Acceptance Criteria

1. **Given** `qwen3-tts-cli` binary is available at the configured path
   **When** `service.py` receives text and voice `"clone"`/`"qwen-female"`/`"qwen-male"`
   **Then** it preprocesses via `expand_siglas()`, generates speech via `qwen3-tts-cli` subprocess with `-l pt --temperature 0.7 --seed N -j 4`, and returns WAV

2. **Given** text containing spelled siglas (CPF, CNPJ, FGTS, etc.)
   **When** `expand_siglas()` processes them
   **Then** they become spaced format (`"C N P J"`). Word siglas (SUS, PIX, LOAS, CEP, DETRAN, ENEM, SAMU, ANVISA, CRAS, PIS) are kept as-is

3. **Given** voice `"clone"` and a clone reference WAV is configured
   **When** Qwen3 generates speech
   **Then** it uses the reference audio path in the CLI invocation

4. **Given** voice `"clone"` but no clone reference WAV is configured
   **When** `QwenEngine` initializes
   **Then** `"clone"` voice is unavailable and `is_clone_configured` returns `False`

5. **Given** text longer than 300 chars
   **When** preprocessing validates it
   **Then** `InvalidRequestError` with char limit hint

6. **Given** a valid WAV from Qwen3
   **When** `whatsapp-subtle` post-processing runs
   **Then** output is processed through highpass(100Hz) -> EQ -> compressor(6:1) -> lowpass(8kHz) -> echo(40ms) -> atempo(1.15x) -> loudnorm(-18 LUFS) -> noise(room=0.15, hiss=0.08) -> loudnorm(-17 LUFS) -> OGG Opus 24kbps 16kHz mono

7. **Given** a seed parameter
   **When** Qwen3 generates with same seed and same text
   **Then** output is identical (deterministic via custom C++ `--seed` patch)

## Tasks / Subtasks

- [x] Task 1: Add Qwen3 configuration fields to `config.py` (AC: 1, 3, 4)
  - [x]Add `qwen3_cli_path: str` (default: `/usr/local/bin/qwen3-tts-cli`)
  - [x]Add `qwen3_model_path: str` (default: `models/qwen3-tts-0.6b-q8_0.gguf`)
  - [x]Add `qwen3_tokenizer_path: str` (default: `models/qwen3-tts-tokenizer-f16.gguf`)
  - [x]Add `clone_reference_path: str | None` (default: `None`)
  - [x]Add `qwen3_threads: int` (default: `4`, ge=1)
  - [x]Add tests for new config fields in `test_config.py`

- [x] Task 2: Implement `expand_siglas()` in `preprocessing.py` (AC: 2)
  - [x]Define `WORD_SIGLAS` set: `{SUS, PIX, LOAS, CEP, DETRAN, ENEM, SAMU, ANVISA, CRAS, PIS}`
  - [x]Regex to match 2+ uppercase letter sequences: `r"\b([A-Z]{2,})\b"`
  - [x]Keep word siglas as-is, space out all others: `"CNPJ"` -> `"C N P J"`
  - [x]Add tests for `expand_siglas()` in `test_preprocessing.py`

- [x] Task 3: Implement `QwenEngine` class in `service.py` (AC: 1, 3, 4, 5, 7)
  - [x]Define `QWEN_VOICES` dict and `QWEN_CHAR_LIMIT = 300`
  - [x]Implement `__init__()` with clone reference detection
  - [x]Implement `is_loaded` property (binary existence check)
  - [x]Implement `is_clone_configured` property
  - [x]Implement `load_model()` — verify binary exists, verify model files exist
  - [x]Implement `warm_up()` — dummy subprocess invocation
  - [x]Implement `generate_speech()` — build CLI args, run subprocess, return WAV bytes
  - [x]Handle seed parameter (default: -1 = random)
  - [x]Validate 300-char limit before generation

- [x] Task 4: Implement `whatsapp-subtle` post-processing (AC: 6)
  - [x]Implement `_apply_whatsapp_subtle()` following `_apply_vibrato_warm()` pattern
  - [x]Stage 1 filter: highpass(100Hz) -> EQ -> compressor(6:1) -> lowpass(8kHz) -> echo -> atempo(1.15x) -> loudnorm(-18 LUFS)
  - [x]Stage 2: noise mixing (room=0.15, hiss=0.08) -> loudnorm(-17 LUFS) -> OGG Opus 24kbps 16kHz mono
  - [x]Support both OGG and WAV output paths
  - [x]Reuse `_find_noise_file()`, `_encode_final()` from existing service code

- [x] Task 5: Add Qwen3 tests in `test_service.py` (AC: all)
  - [x]Mock `subprocess.run` for `qwen3-tts-cli` invocation
  - [x]Test voice mapping (clone/qwen-female/qwen-male)
  - [x]Test char limit validation (300 chars)
  - [x]Test `expand_siglas()` integration
  - [x]Test clone reference path handling (present vs absent)
  - [x]Test whatsapp-subtle pipeline invocation
  - [x]Test seed parameter passing
  - [x]Test WAV and OGG output paths
  - [x]Test binary-not-found error handling
  - [x]Test subprocess timeout handling
  - [x]Test `_apply_noise_and_encode()` refactoring backward-compat (Kokoro still passes 0.45/0.24)

- [x] Task 6: Verify all quality checks pass
  - [x]`uv run ruff check .`
  - [x]`uv run mypy src/`
  - [x]`uv run pytest`
  - [x]`uv run pre-commit run --all-files`

## Dev Notes

### Critical: qwen3-tts-cli Invocation

The CLI binary is a C++ executable with a custom seed patch. **All flags are mandatory for production quality.**

**Base invocation (no cloning):**
```bash
qwen3-tts-cli \
  -m /path/to/qwen3-tts-0.6b-q8_0.gguf \
  -t /path/to/qwen3-tts-tokenizer-f16.gguf \
  -l pt \
  --temperature 0.7 \
  --top-p 0.95 \
  --repetition-penalty 1.05 \
  --max-tokens 2400 \
  --seed 42 \
  -j 4 \
  -o /tmp/output.wav \
  "texto a sintetizar"
```

**With voice cloning reference:**
```bash
qwen3-tts-cli \
  -m /path/to/qwen3-tts-0.6b-q8_0.gguf \
  -t /path/to/qwen3-tts-tokenizer-f16.gguf \
  -l pt \
  --temperature 0.7 \
  --top-p 0.95 \
  --repetition-penalty 1.05 \
  --max-tokens 2400 \
  --seed 42 \
  -j 4 \
  -r /voices/clone-reference.wav \
  -o /tmp/output.wav \
  "texto a sintetizar"
```

**Parameter reference:**

| Flag | Value | Required | Purpose |
|------|-------|----------|---------|
| `-m` | model path | Yes | Q8_0 GGUF model file (1.3 GB) |
| `-t` | tokenizer path | Yes | Tokenizer GGUF (341 MB) |
| `-l` | `pt` | **ALWAYS** | Activates THINK mode for Portuguese (lang ID 2071). Without it: random accent, broken siglas |
| `--temperature` | `0.7` | Yes | Lower = more stable (default 0.9 is too variable) |
| `--top-p` | `0.95` | Yes | Nucleus sampling threshold (default 1.0) |
| `--repetition-penalty` | `1.05` | Yes | Token repetition penalty (prevents loops) |
| `--max-tokens` | dynamic | Yes | Runaway safeguard: `min(4096, max(100, len(text) * 8))` |
| `--seed` | integer or -1 | Yes | -1 = random, N = deterministic. Custom C++ patch |
| `-j` | `4` | Yes | Thread count. 4 = sweet spot. Beyond 4: 1.5% gain at 6 cores |
| `-r` | reference WAV | Clone only | Path to clone reference audio (3-10s) |
| `-o` | output path | Yes | Output WAV file path |
| text | positional arg | Yes | Text to synthesize (last argument) |

**Output:** WAV file at 24kHz. Read the file bytes after subprocess completes.

**Dynamic `--max-tokens` calculation (runaway safeguard):**
```python
max_tokens = min(4096, max(100, len(text) * 8))
```
This caps token generation proportionally to input length, preventing silence-filled runaway output. Combined with the 60s subprocess timeout, this provides a double safeguard.

### Critical: THINK Mode is Non-Negotiable

The `-l pt` flag activates language ID 2071 (Portuguese), which enables THINK mode reasoning tokens. Without it:
- Random accent (sometimes English, sometimes Portuguese)
- Sigla pronunciation inconsistent
- Wrong intonation patterns

**ALWAYS pass `-l pt` in every invocation. There are no exceptions.**

### Critical: QwenEngine Class Design

Follow the exact same pattern as `KokoroEngine` (peer class, same method signatures):

```python
QWEN_VOICES: dict[str, str] = {
    "clone": "clone",        # Uses reference WAV
    "qwen-female": "female", # Default female, no cloning
    "qwen-male": "male",     # Default male, no cloning
}
QWEN_CHAR_LIMIT = 300
```

**Constructor and properties:**
```python
class QwenEngine:
    def __init__(self) -> None:
        self._cli_path: str | None = None
        self._model_path: str | None = None
        self._tokenizer_path: str | None = None
        self._clone_reference_path: str | None = None
        self._threads: int = 4
        self._loaded: bool = False

    @property
    def is_loaded(self) -> bool: ...

    @property
    def is_clone_configured(self) -> bool:
        return self._clone_reference_path is not None
```

**`load_model()` verifies paths exist (fail-fast):**
- Check `qwen3_cli_path` binary exists and is executable
- Check model GGUF exists
- Check tokenizer GGUF exists
- If `clone_reference_path` is set, validate it exists and is a valid WAV using inline `wave.open()` check (do NOT import private `voices._validate_wav()` — use a simple try/except with `wave.open()` to verify it's a readable WAV within 3-10s duration)
- Log clone status on startup

**`generate_speech()` pipeline:**
```
Input: (text, voice_name, response_format, noise_dir, seed=-1)
  |
  v
1. Validate voice_name in QWEN_VOICES -> VoiceNotFoundError
2. If voice_name == "clone" and not is_clone_configured -> VoiceNotFoundError with clone-specific hint
3. Validate text not empty -> InvalidRequestError
4. Validate len(text) <= 300 -> InvalidRequestError
5. preprocessed = expand_siglas(text)
6. Build CLI command list
7. Run subprocess with timeout (60s for Qwen3, NOT 30s — it's 2.5x slower than Kokoro)
8. Read output WAV file
9. result = _apply_whatsapp_subtle(wav_bytes, response_format, noise_dir)
10. Clean up temp file in finally block
11. Return result bytes
```

### Critical: Subprocess Execution Pattern

Use temp files for I/O (not stdin/stdout — the CLI writes to `-o` file):

```python
import tempfile

def generate_speech(self, text: str, voice_name: str, ...) -> bytes:
    with tempfile.NamedTemporaryFile(suffix=".wav", delete=False) as tmp:
        tmp_path = tmp.name

    try:
        cmd = self._build_command(text, voice_name, tmp_path, seed)
        result = subprocess.run(
            cmd,
            capture_output=True,
            check=True,
            timeout=60,  # Qwen3 is slower: 12-37s typical
        )
        wav_bytes = Path(tmp_path).read_bytes()
        return _apply_whatsapp_subtle(wav_bytes, response_format, noise_dir)
    except subprocess.TimeoutExpired as exc:
        logger.error("qwen3-tts-cli timed out after 60s")
        raise GenerationError("Qwen3 TTS generation timed out") from exc
    except subprocess.CalledProcessError as exc:
        logger.error("qwen3-tts-cli failed: %s", exc.stderr.decode(errors="replace"))
        raise GenerationError("Qwen3 TTS generation failed") from exc
    finally:
        Path(tmp_path).unlink(missing_ok=True)
```

**Timeout:** Use 60s (not 30s like Kokoro). Qwen3 typical latency is 12-37s. A 30s timeout would kill legitimate long requests.

### Critical: whatsapp-subtle Post-Processing Pipeline

**Follow the exact same two-stage pattern as `_apply_vibrato_warm()`.** The only differences are the filter chain and noise volumes.

**Stage 1 filter chain:**
```
highpass=f=100,
equalizer=f=200:width_type=o:width=1.5:g=1.5,
equalizer=f=700:width_type=o:width=1.5:g=-2,
equalizer=f=3000:width_type=o:width=1.5:g=3,
equalizer=f=7000:width_type=o:width=1.5:g=-4,
acompressor=threshold=0.15:ratio=6:attack=15:release=200:makeup=5,
lowpass=f=8000,
aecho=0.8:0.85:40:0.12,
atempo=1.15,
loudnorm=I=-18:TP=-2:LRA=7
```

**Stage 2 noise mixing (lower volumes than Kokoro):**
```
[1:a]volume=0.15[room];
[2:a]volume=0.08[hiss];
[0:a][room][hiss]amix=inputs=3:duration=shortest,
loudnorm=I=-17:TP=-1.5:LRA=7
```

**Key differences from vibrato_warm:**

| Aspect | vibrato_warm (Kokoro) | whatsapp-subtle (Qwen3) |
|--------|----------------------|------------------------|
| Vibrato | Yes (4.5Hz, 6%) | No |
| Bass boost | +3dB@200Hz | No |
| EQ | Single band 2.5kHz | 4-band (200/700/3k/7kHz) |
| Exciter | Yes (4.5kHz) | No |
| Softclip | Yes (tanh) | No |
| Compressor ratio | 4:1 | 6:1 |
| Compressor threshold | -20dB | 0.15 (linear) |
| Speed (atempo) | None | 1.15x |
| Room noise | 0.45 | 0.15 |
| Hiss noise | 0.24 | 0.08 |

**Reuse existing helpers:** `_find_noise_file()`, `_apply_noise_and_encode()` (needs noise volume params), `_encode_final()`. Refactor `_apply_noise_and_encode()` to accept `room_volume`/`hiss_volume` parameters instead of hardcoding 0.45/0.24 (see Noise Volume Refactoring section below).

**Note on `subprocess.run()` and async:** The subprocess call blocks the event loop for 12-60s. This is acceptable because the single FIFO queue (`asyncio.Lock`) means only one request runs at a time — `asyncio.create_subprocess_exec()` is NOT needed.

### Critical: expand_siglas() Implementation

```python
# Word siglas that are pronounced as words, not spelled out
WORD_SIGLAS: frozenset[str] = frozenset({
    "SUS", "PIX", "LOAS", "CEP", "DETRAN", "ENEM",
    "SAMU", "ANVISA", "CRAS", "PIS",
})

_SIGLA_RE = re.compile(r"\b([A-Z]{2,})\b")

def expand_siglas(text: str) -> str:
    """Convert spelled siglas to spaced format for Qwen3 pronunciation.

    Spelled siglas (CNPJ, CPF, FGTS) become "C N P J", "C P F", "F G T S".
    Word siglas (SUS, PIX, LOAS) are kept as-is.
    """
    def _replace(match: re.Match[str]) -> str:
        sigla = match.group(1)
        if sigla in WORD_SIGLAS:
            return sigla
        return " ".join(sigla)

    return _SIGLA_RE.sub(_replace, text)
```

**Add to `preprocessing.py`** alongside existing `normalize_text()` and `chunk_text()`. The import graph is clean: `preprocessing.py` depends only on `re` and `num2words`.

**Note:** Qwen3 does NOT use `normalize_text()` or `chunk_text()` — only `expand_siglas()`. Qwen3 handles numbers, dates, and times natively via its BPE tokenizer + THINK mode.

### Critical: Config Changes

Add these fields to the `Settings` class in `config.py`:

```python
qwen3_cli_path: str = Field(
    default="/usr/local/bin/qwen3-tts-cli",
    description="Path to the qwen3-tts-cli binary",
)
qwen3_model_path: str = Field(
    default="models/qwen3-tts-0.6b-q8_0.gguf",
    description="Path to the Qwen3 TTS Q8_0 model file",
)
qwen3_tokenizer_path: str = Field(
    default="models/qwen3-tts-tokenizer-f16.gguf",
    description="Path to the Qwen3 TTS tokenizer file",
)
clone_reference_path: str | None = Field(
    default=None,
    description="Path to clone reference WAV for Qwen3 voice cloning",
)
qwen3_threads: int = Field(
    default=4,
    ge=1,
    description="Number of CPU threads for Qwen3 inference",
)
```

### Critical: Noise Volume Refactoring

The existing `_apply_noise_and_encode()` hardcodes Kokoro volumes (0.45/0.24). For Qwen3, you need (0.15/0.08). **Refactor to accept volume parameters:**

```python
def _apply_noise_and_encode(
    processed_wav: bytes,
    room_noise: Path,
    hiss_noise: Path,
    response_format: str,
    room_volume: float = 0.45,   # Add parameter
    hiss_volume: float = 0.24,   # Add parameter
) -> bytes:
```

Update the `filter_complex` string to use `f"volume={room_volume}"` / `f"volume={hiss_volume}"`. Update `_apply_vibrato_warm()` to pass the Kokoro volumes explicitly. This is a **backward-compatible** change (default values match current behavior). Add a regression test: verify `_apply_vibrato_warm()` still passes 0.45/0.24 after refactoring.

### Critical: Runaway Generation Safeguard

Qwen3 can produce silence-padded output (5.5 min of silence after valid speech). Two safeguards:
1. **Dynamic `--max-tokens`:** `min(4096, max(100, len(text) * 8))` — caps generation proportionally to input length
2. **60s subprocess timeout** — hard cutoff for pathologically long generation

Post-MVP enhancement: implement silence trimming on the output WAV before post-processing (see `trim_silence()` approach in `docs/qwen3-tts-internals.md`).

### Model Files (Not Part of This Story)

Qwen3 requires three artifacts:
- `qwen3-tts-cli` — C++ binary with custom seed patch (built from source)
- `qwen3-tts-0.6b-q8_0.gguf` (1.3 GB) — quantized model
- `qwen3-tts-tokenizer-f16.gguf` (341 MB) — tokenizer

These are deployment concerns (Story 2.1). For dev testing, mock the subprocess call. For integration tests (`pytest -m slow`), the binary and models must be present.

### Testing Approach

**Mock strategy:** Mock `subprocess.run` to simulate `qwen3-tts-cli` behavior. Mock `Path.read_bytes()` for output WAV. Do NOT run real binary in unit tests.

```python
@pytest.fixture()
def qwen_engine() -> QwenEngine:
    """Return a QwenEngine with mock-verified paths."""
    engine = QwenEngine()
    engine._cli_path = "/usr/local/bin/qwen3-tts-cli"
    engine._model_path = "models/qwen3-tts-0.6b-q8_0.gguf"
    engine._tokenizer_path = "models/qwen3-tts-tokenizer-f16.gguf"
    engine._loaded = True
    return engine
```

**Test subprocess call arguments:** Verify the exact CLI flags are passed:
```python
@patch("subprocess.run")
def test_generate_passes_correct_flags(mock_run, qwen_engine):
    # ... setup ...
    mock_run.assert_called_once()
    cmd = mock_run.call_args[0][0]
    assert "-l" in cmd and cmd[cmd.index("-l") + 1] == "pt"
    assert "--temperature" in cmd
    assert "--seed" in cmd
```

**Test clone reference:**
```python
def test_clone_voice_without_reference_raises(qwen_engine):
    """Clone voice requires configured reference WAV."""
    qwen_engine._clone_reference_path = None
    with pytest.raises(VoiceNotFoundError):
        qwen_engine.generate_speech("Olá", "clone", "ogg")
```

**Logger capture pattern** (from Story 1.3): Enable `propagate=True` on the logger fixture, restore in teardown.

### Previous Story Intelligence (from Story 1.4)

**Key learnings to apply:**
- mypy strict mode required `Any` type for untyped external objects — apply same pattern for subprocess return types
- `_samples_to_wav()` uses `np.clip` before int16 conversion — Qwen3 outputs a WAV file directly, no numpy conversion needed
- vibrato_warm two-stage ffmpeg pattern works well — copy the exact structure for whatsapp-subtle
- Graceful noise degradation (skip noise mixing if files absent) — reuse same pattern
- `test_feasibility.py` had to be rewritten when engine changed — keep integration tests isolated

**Code patterns established in 1.4:**
- Engine class with `load_model()`, `warm_up()`, `generate_speech()` methods
- Constants at module level: `VOICES` dict, `CHAR_LIMIT`
- Error handling: catch exceptions, re-raise as `GenerationError`
- Temp file cleanup in `finally` block
- Logger setup: `get_logger("request")` and `get_logger("startup")`

### Git Intelligence

Recent commits show Story 1.4 was completed on 2026-03-23:
- `fbd8ba0`: Implement Story 1.4: Kokoro TTS engine integration (kokoro-onnx)
- KokoClone fully removed, kokoro-onnx integrated
- 161 tests passing, all quality gates green
- `_apply_vibrato_warm()` pattern established for ffmpeg post-processing

### Project Structure Notes

**Files to modify:**
- `src/cumadre/config.py` — Add Qwen3 settings (cli_path, model_path, tokenizer_path, clone_reference_path, threads)
- `src/cumadre/preprocessing.py` — Add `expand_siglas()` function and `WORD_SIGLAS` set
- `src/cumadre/service.py` — Add `QwenEngine` class and `_apply_whatsapp_subtle()`, refactor `_apply_noise_and_encode()` for volume params
- `tests/test_config.py` — Add Qwen3 config field tests
- `tests/test_preprocessing.py` — Add `expand_siglas()` tests
- `tests/test_service.py` — Add `QwenEngine` test class

**Files NOT to modify:**
- `src/cumadre/exceptions.py` — All needed exception types already exist
- `src/cumadre/voices.py` — Already complete, NOT needed for clone validation (use inline `wave.open()` in service.py)
- `src/cumadre/logging.py` — Already complete
- `pyproject.toml` — No new PyPI dependencies needed (Qwen3 is a subprocess binary)
- `src/cumadre/__init__.py` — No changes needed

**New imports needed in `service.py`:** `import tempfile` (for temp WAV output file)

**Import graph compliance (downward only):**
```
config.py, logging.py          <- leaf nodes
exceptions.py                  <- depends on nothing in app
preprocessing.py               <- depends on re, num2words only
voices.py                      <- depends on logging only
service.py                     <- imports: config, logging, exceptions, preprocessing (NO new imports needed)
```

**Note on `generate_speech()` signature asymmetry:** `QwenEngine.generate_speech()` includes a `seed` parameter that `KokoroEngine.generate_speech()` does not. Story 1.6 (Engine Router) must handle this asymmetry (e.g., optional kwargs or engine-specific parameter passing).

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Story-1.5]
- [Source: _bmad-output/planning-artifacts/architecture.md#Qwen3-TTS-C++-Q8_0-Integration]
- [Source: _bmad-output/planning-artifacts/architecture.md#Post-Processing-Pipelines]
- [Source: _bmad-output/planning-artifacts/architecture.md#Module-Boundaries]
- [Source: _bmad-output/planning-artifacts/prd.md#FR5-FR5b]
- [Source: docs/qwen3-tts-internals.md]
- [Source: docs/api-architecture.md#Engine-Routing]
- [Source: _bmad-output/implementation-artifacts/1-4-kokoro-tts-engine-integration.md]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

- Fixed ruff E501 line-too-long in test_service.py (subprocess.TimeoutExpired line)
- Fixed max_tokens test: uppercase "A"*100 was treated as a sigla by expand_siglas — switched to lowercase

### Completion Notes List

- Task 1: Added 5 Qwen3 config fields (qwen3_cli_path, qwen3_model_path, qwen3_tokenizer_path, clone_reference_path, qwen3_threads) with 11 new tests
- Task 2: Implemented expand_siglas() with WORD_SIGLAS frozenset and _SIGLA_RE regex, 15 new tests
- Task 3: Implemented QwenEngine class with load_model(), warm_up(), generate_speech(), _build_command() methods. Subprocess invocation with all mandatory CLI flags, 60s timeout, temp file I/O, clone reference handling
- Task 4: Implemented _apply_whatsapp_subtle() two-stage ffmpeg pipeline. Refactored _apply_noise_and_encode() to accept room_volume/hiss_volume parameters (backward-compatible defaults). Kokoro uses 0.45/0.24, Qwen3 uses 0.15/0.08
- Task 5: 46 new Qwen3 tests covering voice mapping, clone reference, char limit, subprocess CLI flags, seed parameter, max_tokens calculation, expand_siglas integration, error handling (timeout, CalledProcessError), load_model validation, whatsapp-subtle pipeline, noise volume backward-compat regression
- Task 6: All quality checks pass — ruff, mypy strict, 232 tests (0 failures), pre-commit clean

### Change Log

- 2026-03-24: Implemented Story 1.5 — Qwen3-TTS engine integration (all tasks complete)

### File List

- src/cumadre/config.py (modified — added Qwen3 config fields)
- src/cumadre/preprocessing.py (modified — added WORD_SIGLAS, _SIGLA_RE, expand_siglas())
- src/cumadre/service.py (modified — added QwenEngine class, _apply_whatsapp_subtle(), refactored _apply_noise_and_encode() for volume params)
- tests/test_config.py (modified — added 11 Qwen3 config tests)
- tests/test_preprocessing.py (modified — added 15 expand_siglas tests)
- tests/test_service.py (modified — added 46 Qwen3/whatsapp-subtle tests)
