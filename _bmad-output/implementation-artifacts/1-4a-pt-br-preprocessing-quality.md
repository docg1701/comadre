# Story 1.4a: pt-BR Text Preprocessing & Quality Mitigations

Status: review

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an **n8n workflow**,
I want input text to be normalized and chunked before TTS generation,
so that customers hear correct pronunciation of numbers, currency, dates, and times in Brazilian Portuguese, and long texts are not silently truncated.

## Acceptance Criteria

1. **Given** text containing numbers **When** preprocessing normalizes the text **Then** `1500` becomes "mil e quinhentos", `3º` becomes "terceiro", and standalone integers are converted to pt-BR words via num2words

2. **Given** text containing Brazilian currency **When** preprocessing normalizes the text **Then** `R$ 1.500,00` becomes "mil e quinhentos reais" and `R$ 42,50` becomes "quarenta e dois reais e cinquenta centavos" via num2words currency mode

3. **Given** text containing dates in dd/mm/yyyy format **When** preprocessing normalizes the text **Then** `21/03/2026` becomes "vinte e um de março de dois mil e vinte e seis" using custom date parsing + num2words

4. **Given** text containing times in HH:MM format **When** preprocessing normalizes the text **Then** `14:30` becomes "quatorze e trinta" using custom time parsing + num2words

5. **Given** text longer than ~510 tokens (Kokoro's pt-BR limit) **When** preprocessing chunks the text **Then** it splits at sentence boundaries (`.` `!` `?`) targeting 100-200 tokens per chunk, and `service.py` generates audio for each chunk and concatenates the WAV results

6. **Given** the `ESPEAK_DATA_PATH` environment variable is set **When** the service starts up **Then** it sets `os.environ["ESPEAK_DATA_PATH"]` to the configured path before loading the KokoClone model, overriding the bundled espeakng-loader data

7. **Given** `espeak_data_path` is a field in config.py **When** test_config.py runs **Then** it verifies the default is `None` and that it accepts a path string from the environment

## Tasks / Subtasks

- [x] Task 1: Create `src/cumadre/preprocessing.py` (AC: #1-#4)
  - [x] 1.1: Implement `normalize_numbers(text: str) -> str` — regex-match standalone integers and ordinals (`\d+º`, `\d+ª`, `\d+`), convert via `num2words(lang='pt_BR')` / `num2words(to='ordinal')`
  - [x] 1.2: Implement `normalize_currency(text: str) -> str` — regex-match `R$ X.XXX,XX` patterns, parse to float, convert via `num2words(to='currency', lang='pt_BR')`
  - [x] 1.3: Implement `normalize_dates(text: str) -> str` — regex-match `dd/mm/yyyy`, convert day + month name + year to pt-BR words
  - [x] 1.4: Implement `normalize_times(text: str) -> str` — regex-match `HH:MM`, convert hour and minute to pt-BR words
  - [x] 1.5: Implement `normalize_text(text: str) -> str` — orchestrate all normalizations in correct order (currency before numbers — `R$` pattern must match before bare numbers)
  - [x] 1.6: Implement `chunk_text(text: str, max_tokens: int = 200) -> list[str]` — split at sentence boundaries, group sentences into chunks of 100-200 tokens (approximate: split on whitespace for token count)
- [x] Task 2: Update `src/cumadre/service.py` (AC: #5)
  - [x] 2.1: Import `normalize_text` and `chunk_text` from `cumadre.preprocessing`
  - [x] 2.2: In `generate_speech()`, preprocess text before generation: `text = normalize_text(text)` then `chunks = chunk_text(text)`
  - [x] 2.3: For single-chunk text (most requests), preserve current behavior — no concatenation overhead
  - [x] 2.4: For multi-chunk text, generate WAV for each chunk, concatenate using `wave` module, then encode if OGG
  - [x] 2.5: Log chunk count at INFO level: `"Generating %d chunk(s) for %d characters"`
- [x] Task 3: Wire `ESPEAK_DATA_PATH` override in `service.py` (AC: #6)
  - [x] 3.1: In `load_model()`, before importing KokoClone, check if `espeak_data_path` is set and apply `os.environ["ESPEAK_DATA_PATH"]` override
  - [x] 3.2: Log the override at INFO level via startup_logger
- [x] Task 4: Add missing config tests (AC: #7)
  - [x] 4.1: In `tests/test_config.py`, add test: `espeak_data_path` defaults to `None`
  - [x] 4.2: In `tests/test_config.py`, add test: `espeak_data_path` accepts a path from `ESPEAK_DATA_PATH` env var
- [x] Task 5: Create `tests/test_preprocessing.py` (AC: #1-#5)
  - [x] 5.1: Test number normalization (integers, large numbers, ordinals with º/ª)
  - [x] 5.2: Test currency normalization (R$ with/without cents, edge cases)
  - [x] 5.3: Test date normalization (dd/mm/yyyy format, all 12 months)
  - [x] 5.4: Test time normalization (HH:MM, midnight 00:00, noon 12:00)
  - [x] 5.5: Test `normalize_text` orchestration (text with mixed content)
  - [x] 5.6: Test `chunk_text` (short text = 1 chunk, long text splits at sentences, respects token target)
  - [x] 5.7: Test edge cases: empty string, text with no normalizable content, single sentence
- [x] Task 6: Update `tests/test_service.py` (AC: #5)
  - [x] 6.1: Add test: `generate_speech` with multi-chunk text produces concatenated WAV
  - [x] 6.2: Add test: chunk count is logged at INFO level
  - [x] 6.3: Verify existing tests still pass (no regressions)
- [x] Task 7: Validation pass
  - [x] 7.1: Run `uv run ruff check .` — must pass
  - [x] 7.2: Run `uv run mypy src/` — must pass (strict mode)
  - [x] 7.3: Run `uv run pytest` — all tests must pass (including Stories 1.1-1.4)
  - [x] 7.4: Run `uv run pre-commit run --all-files` — must pass

## Dev Notes

### Critical Architecture Constraints

**Module Position in Import Graph:**
- `preprocessing.py` is imported by `service.py` only
- `preprocessing.py` imports from: standard library (`re`, `wave`, `io`), `num2words`
- `preprocessing.py` must NOT import from: `service.py`, `api.py`, `main.py`, `voices.py`, `exceptions.py`
- No circular imports — dependencies flow downward only

**Module Responsibility:**
- `preprocessing.py` handles: pt-BR text normalization (numbers, currency, dates, times), sentence chunking
- `preprocessing.py` must NOT contain: HTTP concerns, TTS generation, voice discovery, exception definitions
- All functions are pure — take string input, return string output (or list of strings for chunking)

**Logging:**
- Use `get_logger("request")` for preprocessing operations (part of request processing)
- All log messages: plain ASCII, no emoji, no ANSI codes (UX-DR10)
- Log preprocessing details at DEBUG level only (avoid flooding INFO)

**No raw `os.environ` in preprocessing.py** — the espeak data path override happens in `service.py`'s `load_model()`, not in preprocessing.

**No `print()` statements.** All output through structured logging.

### preprocessing.py Implementation Guide

**Normalization Order (CRITICAL):** Currency MUST be normalized before numbers. The regex for `R$ 1.500,00` must match before `1500` is treated as a standalone number.

```python
def normalize_text(text: str) -> str:
    """Normalize pt-BR text: currency, numbers, dates, times."""
    text = normalize_currency(text)   # FIRST — R$ pattern before bare numbers
    text = normalize_dates(text)      # dates before numbers (21/03/2026 has numbers)
    text = normalize_times(text)      # times before numbers (14:30 has numbers)
    text = normalize_numbers(text)    # LAST — catch remaining standalone numbers
    return text
```

**num2words API (verified working):**
```python
import num2words

num2words.num2words(1500, lang='pt_BR')                    # "mil e quinhentos"
num2words.num2words(1500, lang='pt_BR', to='currency')     # "mil e quinhentos reais"
num2words.num2words(1500.50, lang='pt_BR', to='currency')  # "mil e quinhentos reais e cinquenta centavos"
num2words.num2words(3, lang='pt_BR', to='ordinal')         # "terceiro"
num2words.num2words(2026, lang='pt_BR')                    # "dois mil e vinte e seis"
```

**Currency Regex Pattern:**
```python
# Matches: R$ 1.500,00 or R$ 42,50 or R$1500 or R$ 1500.00
# Brazilian format: dots as thousands separator, comma as decimal
r'R\$\s?(\d+(?:\.\d{3})*(?:,\d{2})?)'
# Note: \d{1,3} was changed to \d+ — the original would only match '150' from 'R$ 1500'
```

**Date Regex Pattern:**
```python
# Matches: 21/03/2026 (dd/mm/yyyy)
r'(\d{1,2})/(\d{1,2})/(\d{4})'
```

**pt-BR Month Names:**
```python
MONTHS_PT = [
    "janeiro", "fevereiro", "março", "abril", "maio", "junho",
    "julho", "agosto", "setembro", "outubro", "novembro", "dezembro",
]
```

**Time Regex Pattern:**
```python
# Matches: 14:30, 08:00, 00:00
r'(\d{1,2}):(\d{2})'
```

**Ordinal Regex Pattern:**
```python
# Matches: 3º, 1ª, 10º
r'(\d+)[ºª]'
```

**Chunking Strategy:**
```python
import re

def chunk_text(text: str, max_tokens: int = 200) -> list[str]:
    sentences = re.split(r'(?<=[.!?])\s+', text)
    chunks: list[str] = []
    current_chunk: list[str] = []
    current_tokens = 0

    for sentence in sentences:
        token_count = len(sentence.split())
        if current_tokens + token_count > max_tokens and current_chunk:
            chunks.append(" ".join(current_chunk))
            current_chunk = [sentence]
            current_tokens = token_count
        else:
            current_chunk.append(sentence)
            current_tokens += token_count

    if current_chunk:
        chunks.append(" ".join(current_chunk))

    return chunks if chunks else [text]  # never return empty list
```

### service.py Modification Guide

**Current `generate_speech` flow:**
1. Resolve voice → 2. Generate WAV → 3. Encode if OGG → 4. Return bytes

**New flow with preprocessing:**
1. Resolve voice → 2. Preprocess text → 3. Chunk text → 4. Generate WAV per chunk → 5. Concatenate if multi-chunk → 6. Encode if OGG → 7. Return bytes

**WAV Concatenation (using `wave` module):**
```python
import io
import wave

def _concatenate_wavs(wav_bytes_list: list[bytes]) -> bytes:
    """Concatenate multiple WAV byte sequences into one."""
    if len(wav_bytes_list) == 1:
        return wav_bytes_list[0]

    output = io.BytesIO()
    with wave.open(output, "wb") as out_wf:
        for i, wav_bytes in enumerate(wav_bytes_list):
            with wave.open(io.BytesIO(wav_bytes), "rb") as in_wf:
                if i == 0:
                    out_wf.setparams(in_wf.getparams())
                out_wf.writeframes(in_wf.readframes(in_wf.getnframes()))
    return output.getvalue()
```

**ESPEAK_DATA_PATH Override (in `load_model()`):**
```python
def load_model(self, espeak_data_path: str | None = None) -> None:
    if espeak_data_path is not None:
        import os
        os.environ["ESPEAK_DATA_PATH"] = espeak_data_path
        startup_logger.info("espeak-ng data path overridden: %s", espeak_data_path)
    from core.cloner import KokoClone
    # ... rest of load_model
```

**Note on `load_model` signature change:** The caller (main.py lifespan in Story 1.7) will pass `settings.espeak_data_path` to `load_model()`. This is an additive change — the parameter has a default of `None` so existing callers (tests) are unaffected.

### Testing Strategy

**All tests mock KokoClone.** No real model loading, no real TTS inference.

**preprocessing.py tests are pure — no mocking needed.** Each normalization function is a pure string transformation. Test with direct assertions.

**service.py chunk tests:** Use the existing `_mock_generate` helper that writes valid WAV files. For multi-chunk tests, verify that `generate()` is called N times (once per chunk) and that the output is valid WAV.

**Log assertion pattern (from Story 1.4):**
```python
@pytest.fixture()
def request_logger(caplog):
    req_log = logging.getLogger("request")
    req_log.propagate = True
    yield caplog
    req_log.propagate = False
```

### Anti-Patterns to Avoid

- Do NOT use nltk, spacy, or textacy — only `num2words` + standard library
- Do NOT import from `service.py` in `preprocessing.py` — keeps modules decoupled
- Do NOT silently truncate text — always chunk and process all content
- Do NOT change `generate_speech()` signature — it remains `(text, voice_name, response_format, voices) -> bytes`
- Do NOT add HTTP concerns to preprocessing.py
- Do NOT add emoji to log messages (UX-DR10)
- Do NOT break existing Story 1.4 tests — all 80 tests must continue passing
- Do NOT add `config.py` import to preprocessing.py — preprocessing functions are pure, configuration is the caller's concern
- Do NOT modify `_encode_ogg` — OGG encoding happens after concatenation, not per-chunk

### Previous Story Intelligence

**From Story 1.4 (done):**
- `TTSService` class with lazy KokoClone import via `TYPE_CHECKING` guard
- `generate_speech(text, voice_name, response_format, voices) -> bytes` — current signature, do not change
- `_encode_ogg(wav_path: Path) -> bytes` — ffmpeg subprocess, do not modify
- `_cloner.generate(text, lang, ref_audio, output_path)` — KokoClone API takes string args
- Temp file management pattern: `NamedTemporaryFile(delete=False)` → generate → read_bytes → unlink in finally
- Logger pattern: `get_logger("request")` with `propagate=False`
- Test mock pattern: `_mock_generate()` writes valid WAV to output_path
- Exception re-raise pattern: catch `(VoiceNotFoundError, GenerationError)` then `except Exception` wraps in `GenerationError`
- Null guard: `if self._cloner is None: raise RuntimeError("Model not loaded")`
- num2words added to pyproject.toml dependencies (was NOT present at Story 1.4 completion)
- mypy override for `num2words.*` added (was NOT present at Story 1.4 completion)

**From Story 1.2 (done):**
- `config.py` did NOT have `espeak_data_path` — field was added by this story (1.4a)
- `test_config.py` has 12 tests but NONE for `espeak_data_path` — Task 4 fills this gap
- `get_settings()` is `@lru_cache` — tests use `get_settings.cache_clear()` fixture

**Git patterns:**
```
1c4f8aa Add KokoClone TTS service wrapper (Story 1.4)
d9ca8f6 Add voice discovery and validation module (Story 1.3)
be201ea Add configuration and structured logging (Story 1.2)
```
Commit format: `"Add [feature] (Story X.Y)"`

### Project Structure Notes

**Files to create:**
```
src/cumadre/preprocessing.py    (new)
tests/test_preprocessing.py     (new)
```

**Files to modify:**
```
src/cumadre/service.py          (add preprocessing + chunking + concatenation)
src/cumadre/config.py           (add espeak_data_path field — was not present)
pyproject.toml                  (add num2words dependency + mypy override — was not present)
tests/test_service.py           (add chunking tests)
tests/test_config.py            (add espeak_data_path tests)
```

**Files NOT to create or modify:**
- `src/cumadre/api.py` — belongs to Story 1.7
- `src/cumadre/main.py` — belongs to Story 1.7
- `src/cumadre/health.py` — belongs to Story 1.6
- `src/cumadre/schemas.py` — belongs to Story 1.5
- `src/cumadre/exceptions.py` — no changes needed
- `src/cumadre/voices.py` — no changes needed
- `src/cumadre/logging.py` — no changes needed

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#pt-BR Phonemization: Research Findings & Mitigations]
- [Source: _bmad-output/planning-artifacts/architecture.md#Module Responsibility — preprocessing.py]
- [Source: _bmad-output/planning-artifacts/architecture.md#Import Dependency Graph — preprocessing.py imports]
- [Source: _bmad-output/planning-artifacts/architecture.md#Data Flow — preprocessing → chunking → per-chunk generation → concatenation]
- [Source: _bmad-output/planning-artifacts/architecture.md#Startup Sequence — espeak-ng data override]
- [Source: _bmad-output/planning-artifacts/architecture.md#Request Processing Steps — step 4 preprocess text]
- [Source: _bmad-output/planning-artifacts/architecture.md#Cross-Cutting Concern #6 — pt-BR Phonemization Quality]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 1.4 — ACs for preprocessing, chunking, espeak override]
- [Source: _bmad-output/implementation-artifacts/1-4-kokoclone-tts-service-wrapper.md — previous story intelligence]
- [Source: num2words PyPI — lang='pt_BR' API verified working]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

- Fixed currency regex: `\d{1,3}` prefix caused `R$ 1500` to match only `150`; changed to `\d+` for greedy integer match
- Fixed ordinal feminine: num2words `to='ordinal'` returns masculine only; added suffix-based gender swap (`ª` → replace trailing `o` with `a`)
- Added `_n2w()` typed wrapper to satisfy mypy strict `no-any-return` rule for untyped num2words library

### Completion Notes List

- preprocessing.py: 6 public functions (normalize_currency, normalize_dates, normalize_times, normalize_numbers, normalize_text, chunk_text) + 1 typed wrapper (_n2w)
- service.py: generate_speech now preprocesses and chunks text, generates WAV per chunk, concatenates via _concatenate_wavs, then encodes if OGG
- service.py: load_model() accepts optional espeak_data_path parameter, sets os.environ before KokoClone import
- 45 new tests (36 preprocessing + 7 service + 2 config), all passing
- 125 total tests, 0 regressions, ruff clean, mypy strict clean, pre-commit all hooks pass

### Change Log

- 2026-03-21: Implemented Story 1.4a — pt-BR text preprocessing module, service integration with chunking/concatenation, ESPEAK_DATA_PATH override, config test coverage

### File List

- src/cumadre/preprocessing.py (new)
- src/cumadre/service.py (modified — preprocessing integration, chunking, concatenation, espeak override)
- tests/test_preprocessing.py (new)
- tests/test_service.py (modified — multi-chunk, concatenation, espeak tests)
- tests/test_config.py (modified — espeak_data_path tests)
