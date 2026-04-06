# CLAUDE.md

## Project Overview

Comadre is a self-hosted TTS API with dual-engine architecture: Kokoro fp32 (fast built-in voices) + Qwen3-TTS C++ Q8_0 (voice cloning). Serves n8n chatbot workflows for WhatsApp/Telegram/Messenger in Brazilian Portuguese.

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

- **Dual-engine + filesystem voice discovery**: voice param format is `engine/name` (e.g. `kokoro/pm_santa`, `qwen/galvani`). Kokoro voices: `.npy` files in `/voices/kokoro/` or built-in from `.npz`. Qwen3 voices: `.wav` files in `/voices/qwen/`. Drop a file → available immediately, no restart. See `docs/voice-management.md`.
- **Single FIFO queue** per instance (`asyncio.Lock`). No multi-worker model. Scale horizontally via Caddy.
- **Engine-specific preprocessing**: Kokoro uses `normalize_text()` + `chunk_text()`. Qwen3 uses `expand_siglas()`.
- **Engine-specific post-processing**: Kokoro → vibrato_warm pipeline. Qwen3 → whatsapp-subtle pipeline. Both output OGG Opus.
- **Siglas**: Kokoro handles them natively via espeak-ng pt_extra dictionary (67 entries, 34/34 verified). Qwen3 uses spaced format (`C N P J`).
- **Module boundaries enforced**: no HTTP concerns in `service.py`, no business logic in `api.py`, no raw `os.environ` (use pydantic-settings), no raw `HTTPException` (use `ComadreError` hierarchy).
- **HTTPS via Caddy**: Caddy reverse proxy terminates TLS (auto Let's Encrypt or self-signed). TTS service only exposed internally on Docker network. Configure domain via `DOMAIN` env var.
- **Rate limiting**: slowapi per-IP rate limiting. Speech: 30/min, Health: 60/min (configurable via `RATE_LIMIT_SPEECH`, `RATE_LIMIT_HEALTH`). Shared limiter instance in `src/comadre/rate_limit.py`.
- **Import graph flows downward only**: config/logging → exceptions/schemas → preprocessing → service → rate_limit → api/health → main. No circular imports.

## Code Conventions

- Python 3.12, type-annotated (mypy strict + pydantic plugin)
- `ruff` for lint+format (line-length 88)
- All errors via `ComadreError` subclasses with `status_code`, `error_type`, `hint` — never raw HTTPException
- Structured logging: pipe-delimited `timestamp | level | component | message` — never `print()`
- Docker Compose v2 syntax: `docker compose`, never `docker-compose`
- Package management: `uv` only, never `pip` or `poetry`
- Ansible become password: pass via `-e "ansible_become_password=PASSWORD"` on every playbook that uses `become: true` (bootstrap, cleanup). Never modify inventory to store passwords.

## Key File Locations

- `src/comadre/` — application code (config, logging, schemas, exceptions, preprocessing, service, rate_limit, health, download, api, main)
- `tests/` — pytest suite (mocked, no real models)
- `deploy/espeak-ng/pt_extra` — custom sigla dictionary for espeak-ng
- `docs/` — technical research docs (feasibility report, engine internals, dictionary docs, **qwen3-tts-cli build guide**, **qwen3 model quantization guide**, **voice management guide**)
- `deploy/bin/qwen3-tts-cli` — pre-built Qwen3 C++ binary (see `docs/building-qwen3-tts-cli.md` to rebuild)
- `deploy/bin/rotate-api-key.sh` — API key rotation script (run on VPS, no redeploy needed)
- `deploy/caddy/Caddyfile` — Caddy reverse proxy config (HTTPS termination)
- `scripts/loadtest.py` — saturation test (concurrency-based, 6 scenarios)
- `scripts/capacity_test.py` — capacity test (rate-based, WhatsApp context, ElevenLabs comparison)
- `_bmad-output/` — planning artifacts (PRD, architecture, epics, stories, sprint status)

## Non-Obvious Gotchas

- **misaki ignores ESPEAK_DATA_PATH** — the bundled `pt_dict` in `espeakng_loader` takes precedence. Must copy compiled pt_extra data to BOTH system path AND the espeakng_loader bundled path inside the venv.
- **Qwen3 requires `-l pt`** for THINK mode — without it, accent is random and siglas are inconsistent.
- **Qwen3 4-core sweet spot** — beyond 4 CPU cores, diminishing returns (1.5% gain at 6 cores). GGML uses all threads per request.
- **Noise calibration differs per engine** — Kokoro needs 3x more room/hiss noise than Qwen3 (RMS 0.063 vs 0.016).
- **kokoclone dependency is legacy** — still in pyproject.toml but REJECTED. Will be replaced by kokoro-onnx in Story 1.4.
- **qwen3-tts-cli build is non-trivial** — requires building ggml submodule first, patching OpenMP linking, and applying the seed patch. Full procedure in `docs/building-qwen3-tts-cli.md`.
- **Qwen3 Q8_0 GGUF now available pre-built** — from `PabloHoties/Qwen3-TTS-12Hz-0.6B-Base-GGUF` on HuggingFace. The app auto-downloads when `QWEN3_MODEL_URL` and `QWEN3_TOKENIZER_URL` are set. Manual conversion (see `docs/quantizing-qwen3-models.md`) is no longer required.
- **Models auto-download on first startup** — Kokoro models download from GitHub releases, Qwen3 models from HuggingFace. For air-gapped deployments, use `deploy-models.yml` to copy via SCP.
