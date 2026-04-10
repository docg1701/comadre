---
project_name: 'comadre'
user_name: 'Galvani'
date: '2026-03-25'
sections_completed: ['technology_stack', 'language_rules', 'framework_rules', 'testing_rules', 'code_quality', 'workflow_rules', 'critical_rules']
status: 'complete'
rule_count: 52
optimized_for_llm: true
---

# Project Context for AI Agents

_This file contains critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

- **Python 3.12+** — strict mypy + pydantic plugin, type-annotated throughout
- **FastAPI >=0.115** — async ASGI, dependency injection, lifespan events
- **pydantic-settings >=2.7** — environment-based config (no raw `os.environ`)
- **kokoro-onnx >=0.5.0** — Kokoro fp32 ONNX inference (voices: santa, dora, alex)
- **qwen3-tts-cli** — custom C++ binary, Q8_0 GGUF models (voices: clone, qwen-female, qwen-male)
- **num2words >=0.5** — pt_BR number-to-words expansion
- **ruff >=0.9** — lint + format (line-length 88, select: E,F,I,UP,B,SIM,N,C4,PTH,RUF)
- **mypy >=1.14** — strict mode; kokoro_onnx/num2words exempt from import checks
- **pytest >=8.3** — asyncio_mode=auto; `@pytest.mark.slow` for integration tests
- **Docker** — python:3.12-slim base, espeak-ng from source (commit 675d77226b16105)
- **uv 0.8.3** — sole package manager (never pip/poetry)
- **Docker Compose v2** — `docker compose` syntax only (never `docker-compose`)
- **Ansible** — community.docker >=3.12.0, 4 playbooks (bootstrap/update/health/cleanup)

## Critical Implementation Rules

### Python Language Rules

- **All type annotations required** — mypy strict mode enforced; every function signature, variable, and return type must be annotated
- **No raw `os.environ`** — all config via `pydantic_settings.BaseSettings` with validators; access through `get_settings()` (LRU-cached)
- **No raw `HTTPException`** — all errors via `ComadreError` subclasses (`VoiceNotFoundError`, `InvalidRequestError`, `GenerationError`, `AuthenticationError`, `ServiceUnavailableError`) with mandatory `status_code`, `error_type`, `hint` fields
- **No `print()` statements** — structured logging only via `get_logger("component")` returning pipe-delimited format: `timestamp | level | component | message`
- **Async patterns** — FastAPI endpoints are `async def`; queue uses `asyncio.Lock` (not threading); subprocess calls for Qwen3 use `asyncio.create_subprocess_exec`
- **Import graph is strict downward-only** — `config/logging` → `exceptions/voices/schemas` → `preprocessing` → `service` → `api/health` → `main`. Circular imports are forbidden.
- **Module boundary enforcement** — no HTTP concerns in `service.py`, no business logic in `api.py`, no model/engine logic in `api.py`
- **String formatting** — f-strings preferred; structured log messages use the pipe-delimited format, not free-form
- **Secret handling** — API key stored as `SecretStr`; comparison via `hmac.compare_digest()` (timing-safe)

### Framework & Architecture Rules

- **Dual-engine routing by voice name** — voice name determines engine: `santa`/`dora`/`alex` → KokoroEngine; `clone`/`qwen-female`/`qwen-male` → QwenEngine. Router dispatches automatically.
- **Engine-specific preprocessing** — Kokoro: `normalize_text()` + `chunk_text()` (full pt-BR normalization). Qwen3: `expand_siglas()` only (spaced acronyms like `C N P J`).
- **Engine-specific post-processing** — Kokoro: `radio_warm` pipeline (EQ, compressor, saturation, loudnorm). Qwen3: `whatsapp_subtle` pipeline (EQ, compressor, atempo 1.15x). Both output OGG Opus 24kbps 16kHz mono.
- **Single FIFO queue per instance** — one `asyncio.Lock`, no multi-worker model. Horizontal scaling by increasing `deploy.replicas` in `compose.yaml` — Caddy load-balances across replicas via the `dynamic a` upstream resolver in `Caddyfile` (re-resolves Docker DNS every 5s, round-robin policy). Plain `reverse_proxy host:port` does NOT round-robin — it resolves once at startup. No threading/multiprocessing.
- **9-phase startup lifespan** — strict ordering: state init → config → logging → Kokoro model download → Qwen3 model download → noise dir → espeak-ng data → clone ref detection → engine load + warm-up. Both engines must succeed or startup fails.
- **Health endpoint contract** — returns 503 `warming_up` during startup, 200 `healthy` when ready. Reports `queue_depth`, `engines`, `voices`, `memory_mb`, `uptime_seconds`, `version`.
- **Request validation** — char limits are engine-specific: Kokoro 500 chars, Qwen3 300 chars. Enforced via `SpeechRequest` pydantic validator based on resolved voice→engine mapping.
- **Noise calibration differs per engine** — Kokoro needs 3x more room/hiss noise (RMS 0.063) than Qwen3 (RMS 0.016). Never apply same noise level to both.

### Testing Rules

- **All tests are mocked by default** — no real models, no real inference. Tests run fast without GPU or model files.
- **`@pytest.mark.slow` for integration tests** — tests requiring actual model files (in `test_feasibility.py`) are excluded from default `uv run pytest`. Run with `uv run pytest -m slow` explicitly.
- **Async test pattern** — `asyncio_mode = "auto"` in pytest config; all test functions are `async def`; use `AsyncClient` from httpx (not `TestClient`).
- **Nested test classes by behavior** — group tests semantically: `TestSpeechSuccess`, `TestAuthenticationError`, `TestVoiceNotFound`, `TestValidationError`, `TestServiceUnavailable`. One class per behavior, not per method.
- **Fixtures in `conftest.py`** — `mock_settings` (Settings with TEST_API_KEY), `mock_router` (MagicMock with stubbed methods), `app` (FastAPI with mocked state, no lifespan), `client` (AsyncClient), `auth_headers` (Bearer token dict).
- **`_clear_settings_cache` autouse fixture** — clears `get_settings` LRU cache before each test to prevent cross-test config leakage.
- **Mock assertion pattern** — use `mock_router.generate_speech.assert_called_once()` + inspect `call_args.kwargs` for argument verification, not just response status codes.
- **Test file naming** — `test_{module}.py` mirrors source module; `test_routing.py` tests the engine router dispatch logic separately from `test_service.py`.

### Code Quality & Style Rules

- **Everything in English** — code, comments, commits, docs, configs, API responses, error messages, README.md. No exceptions, no Portuguese in any project file.
- **ruff enforces lint + format** — line-length 88; rules: E, F, I, UP, B, SIM, N, C4, PTH, RUF. Auto-fix enabled in pre-commit with `--exit-non-zero-on-fix`.
- **Pre-commit gate** — all commits pass: ruff-check, ruff-format, hadolint, yamllint, shellcheck, markdownlint-cli2, mypy. Run `uv run pre-commit run --all-files` to verify.
- **File organization** — one module per concern in `src/comadre/`. No god files. `service.py` is the largest (~849 LOC) because it contains both engine classes + post-processing pipelines.
- **Naming conventions** — snake_case for files, functions, variables. PascalCase for classes (`KokoroEngine`, `QwenEngine`, `ComadreError`). UPPER_SNAKE for constants (`KOKORO_VOICES`, `QWEN_VOICES`, `WORD_SIGLAS`).
- **No docstrings on obvious methods** — only add comments where logic isn't self-evident. The codebase is lean; type annotations serve as documentation.
- **Commit message format** — imperative tense, English: `Implement Story X.Y: <description>`, `Fix <what>`, `Release vX.Y.Z: <notes>`. No emoji prefixes.

### Development Workflow Rules

- **Package management: `uv` only** — `uv sync` to install, `uv run` to execute. Never pip install, never poetry. Lock file is `uv.lock`.
- **Quality check commands** — `uv run pytest` (tests), `uv run ruff check .` (lint), `uv run mypy src/` (type check), `uv run pre-commit run --all-files` (all gates).
- **CI pipeline** — GitHub Actions on push/PR to master: lint → test → docker build. Tests exclude `@pytest.mark.slow`.
- **Docker build requires `API_KEY` env var** — even for CI builds (uses dummy value). `docker compose build` with `API_KEY=ci-build-dummy`.
- **Models deploy via SSH, not git** — GGUF files (~1.6 GB) are too large for git. SCP to VPS + helper container into Docker volume. Ansible does NOT automate model transfer yet.
- **Ansible inventory requires manual setup** — `inventory/production.yml` ships with `CHANGE_ME` placeholders for `ansible_host`, `ansible_user`, `repo_url`. Must be configured per deployment.
- **Daily restart at 3 AM** — configured in Ansible as memory leak precaution (`restart_hour: 3`).
- **Horizontal scaling only** — single FIFO queue per container instance. Add more containers behind Caddy, never add workers/threads to a single instance.

### Critical Don't-Miss Rules

**espeak-ng / misaki gotcha:**
- misaki (Kokoro's phonemizer) ignores `ESPEAK_DATA_PATH` — it uses its own bundled `pt_dict` inside `espeakng_loader`. Custom pt_extra dictionary must be copied to BOTH the system path AND the misaki bundled path inside the venv/container. Dockerfile handles this; local dev must replicate.

**Qwen3 engine gotchas:**
- Qwen3 requires `-l pt` flag for THINK mode — without it, accent is random and siglas are inconsistent. Always pass language flag.
- Qwen3 4-core sweet spot — beyond 4 CPU cores, diminishing returns (only 1.5% gain at 6 cores). `QWEN3_THREADS=4` in compose.yaml.
- Qwen3 Q8_0 model must be converted locally — no pre-built Q8_0 exists. Neither `llama-quantize` nor `gpt-2-quantize` supports `qwen3-tts` architecture. Convert from HuggingFace safetensors using upstream script. See `docs/quantizing-qwen3-models.md`.
- qwen3-tts-cli build is non-trivial — requires building ggml submodule first, patching OpenMP linking, applying seed patch. See `docs/building-qwen3-tts-cli.md`.

**Sigla handling divergence:**
- Kokoro handles siglas natively via espeak-ng pt_extra dictionary (67 entries). Qwen3 uses `expand_siglas()` to space them (`CNPJ` → `C N P J`), except `WORD_SIGLAS` (SUS, PIX, LOAS, etc.) which are pronounced as words.

**Anti-patterns — never do these:**
- Never use `pip` or `poetry` — `uv` only
- Never use `docker-compose` — Docker Compose v2: `docker compose`
- Never suggest GPU or cloud TTS solutions — CPU-only, self-hosted, budget constraint is absolute
- Never use `/tmp` or system temp dirs for builds/artifacts — always work inside the repository
- Never write Portuguese in any project file — English only, no exceptions
- Never add workers/threads to scale — horizontal scaling via multiple containers only
- Never raise raw `HTTPException` — use `ComadreError` subclasses
- Never import upward in the module graph — strict downward-only: config/logging → exceptions/voices/schemas → preprocessing → service → api/health → main

---

## Usage Guidelines

**For AI Agents:**

- Read this file before implementing any code
- Follow ALL rules exactly as documented
- When in doubt, prefer the more restrictive option
- Update this file if new patterns emerge

**For Humans:**

- Keep this file lean and focused on agent needs
- Update when technology stack changes
- Review quarterly for outdated rules
- Remove rules that become obvious over time

Last Updated: 2026-03-25
