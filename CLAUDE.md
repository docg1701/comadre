# CLAUDE.md

## Project Overview

CUMADRE is a self-hosted TTS API with dual-engine architecture: Kokoro fp32 (fast built-in voices) + Qwen3-TTS C++ Q8_0 (voice cloning). Serves n8n chatbot workflows for WhatsApp/Telegram/Messenger in Brazilian Portuguese.

## Language Policy

- **Everything in English** — code, comments, commits, docs, configs, API responses, error messages, README.md.
- No exceptions. All project files are in English.
- Why: optimizes LLM interaction and developer experience.

## Build & Test

```bash
uv sync                          # Install all deps
uv run pytest                    # Run tests (mocked, no model needed)
uv run pytest -m slow            # Run integration tests (requires models)
uv run ruff check .              # Lint
uv run mypy src/                 # Type check (strict mode)
uv run pre-commit run --all-files  # All quality checks
```

## Architecture — What You Must Know

- **Dual-engine**: voice name routes to engine. `santa`/`dora`/`alex` → Kokoro. `clone`/`qwen-female`/`qwen-male` → Qwen3.
- **Single FIFO queue** per instance (`asyncio.Lock`). No multi-worker model. Scale horizontally via Caddy.
- **Engine-specific preprocessing**: Kokoro uses `normalize_text()` + `chunk_text()`. Qwen3 uses `expand_siglas()`.
- **Engine-specific post-processing**: Kokoro → vibrato_warm pipeline. Qwen3 → whatsapp-subtle pipeline. Both output OGG Opus.
- **Siglas**: Kokoro handles them natively via espeak-ng pt_extra dictionary (67 entries, 34/34 verified). Qwen3 uses spaced format (`C N P J`).
- **Module boundaries enforced**: no HTTP concerns in `service.py`, no business logic in `api.py`, no raw `os.environ` (use pydantic-settings), no raw `HTTPException` (use `CumadreError` hierarchy).
- **Import graph flows downward only**: config/logging → exceptions/voices/schemas → preprocessing → service → api/health → main. No circular imports.

## Code Conventions

- Python 3.12, type-annotated (mypy strict + pydantic plugin)
- `ruff` for lint+format (line-length 88)
- All errors via `CumadreError` subclasses with `status_code`, `error_type`, `hint` — never raw HTTPException
- Structured logging: pipe-delimited `timestamp | level | component | message` — never `print()`
- Docker Compose v2 syntax: `docker compose`, never `docker-compose`
- Package management: `uv` only, never `pip` or `poetry`

## Key File Locations

- `src/cumadre/` — application code (config, logging, voices, preprocessing, service, exceptions)
- `tests/` — pytest suite (mocked, no real models)
- `deploy/espeak-ng/pt_extra` — custom sigla dictionary for espeak-ng
- `docs/` — technical research docs (feasibility report, engine internals, dictionary docs)
- `_bmad-output/` — planning artifacts (PRD, architecture, epics, stories, sprint status)

## Non-Obvious Gotchas

- **misaki ignores ESPEAK_DATA_PATH** — the bundled `pt_dict` in `espeakng_loader` takes precedence. Must copy compiled pt_extra data to BOTH system path AND the espeakng_loader bundled path inside the venv.
- **Qwen3 requires `-l pt`** for THINK mode — without it, accent is random and siglas are inconsistent.
- **Qwen3 4-core sweet spot** — beyond 4 CPU cores, diminishing returns (1.5% gain at 6 cores). GGML uses all threads per request.
- **Noise calibration differs per engine** — Kokoro needs 3x more room/hiss noise than Qwen3 (RMS 0.063 vs 0.016).
- **kokoclone dependency is legacy** — still in pyproject.toml but REJECTED. Will be replaced by kokoro-onnx in Story 1.4.
