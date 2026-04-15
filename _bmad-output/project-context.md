---
project_name: 'comadre'
user_name: 'Galvani'
date: '2026-04-14'
sections_completed: ['technology_stack', 'language_rules', 'framework_rules', 'testing_rules', 'code_quality', 'workflow_rules', 'critical_rules']
status: 'complete'
rule_count: 58
optimized_for_llm: true
---

# Project Context for AI Agents

_Critical rules and patterns that AI agents must follow when implementing code in this project. Focus on unobvious details that agents might otherwise miss._

---

## Technology Stack & Versions

- **Python 3.12+** — strict mypy + pydantic plugin, type-annotated throughout
- **FastAPI >=0.115** — async ASGI, dependency injection, lifespan events
- **pydantic-settings >=2.7** — environment-based config (no raw `os.environ`)
- **kokoro-onnx >=0.5.0** — Kokoro fp32 ONNX inference
- **qwen3-tts-cli** — custom C++ binary, Q8_0 GGUF (pre-built available from HuggingFace `PabloHoties/Qwen3-TTS-12Hz-0.6B-Base-GGUF`)
- **slowapi >=0.1.9** — per-IP rate limiting (X-Forwarded-For aware)
- **num2words >=0.5** — pt_BR number-to-words expansion
- **ruff >=0.9** — lint + format (line-length 88; rules: E, F, I, UP, B, SIM, N, C4, PTH, RUF)
- **mypy >=1.14** — strict mode; `kokoro_onnx`, `num2words` exempt from import checks
- **pytest >=8.3** — `asyncio_mode=auto`; `@pytest.mark.slow` for integration tests
- **Caddy 2-alpine** — reverse proxy, TLS termination, landing page, load balancing
- **Docker** — `python:3.12-slim` base, espeak-ng built from source (commit 675d77226b16105)
- **uv 0.8.3+** — sole package manager (never pip/poetry); build backend via `uv_build`
- **Docker Compose v2** — `docker compose` syntax only (never `docker-compose`)
- **Ansible** — `community.docker >=3.12.0`; 4 playbooks (bootstrap/update/health/cleanup)

## Critical Implementation Rules

### Python Language Rules

- **All type annotations required** — mypy strict; every signature, variable, and return type must be annotated
- **No raw `os.environ`** — config via `pydantic_settings.BaseSettings` with validators; access through `get_settings()` (LRU-cached)
- **No raw `HTTPException`** — all errors via `ComadreError` subclasses (`VoiceNotFoundError`, `InvalidRequestError`, `GenerationError`, `AuthenticationError`, `ServiceUnavailableError`, `RateLimitError`) with mandatory `status_code`, `error_type`, `hint` fields
- **No `print()`** — structured logging only via `get_logger("component")`, pipe-delimited format: `timestamp | level | component | message`
- **Async patterns** — FastAPI endpoints `async def`; queue uses `asyncio.Lock` (not threading); Qwen3 subprocess via `asyncio.create_subprocess_exec` or `asyncio.to_thread`
- **Import graph strict downward-only** — `config/logging` → `exceptions/schemas` → `preprocessing` → `service` → `rate_limit` → `api/health` → `main`. Circular imports forbidden.
- **Module boundaries** — no HTTP concerns in `service.py`, no business logic in `api.py`, no model/engine logic in `api.py`
- **Secret handling** — API key stored as `SecretStr`; comparison via `hmac.compare_digest()` (timing-safe)
- **Client IP resolution** — always use `get_client_ip(request)` from `rate_limit.py`, never `request.client.host` directly (Caddy injects real IP via `X-Forwarded-For`)

### Framework & Architecture Rules

- **Voice format is `engine/name`** — e.g. `kokoro/pm_santa`, `qwen/galvani`. Engine prefix must be `kokoro` or `qwen`. Name must match `^[a-zA-Z0-9_-]+$` (path-traversal safe). `EngineRouter._parse_voice()` enforces this.
- **Filesystem-based voice discovery** — Kokoro: built-in from `.npz` archive + custom `.npy` files in `/voices/kokoro/`. Qwen3: `.wav` files in `/voices/qwen/`. Drop a file → available immediately, no restart. Built-ins take precedence over `.npy` only when no `.npy` exists.
- **Engine-specific preprocessing** — Kokoro: `normalize_text()` + `chunk_text()` (full pt-BR normalization). Qwen3: `expand_siglas()` only (spaced acronyms like `C N P J`).
- **Engine-specific post-processing** — Kokoro: `radio_warm` pipeline (EQ, compressor, saturation, loudnorm). Qwen3: `whatsapp_subtle` pipeline (EQ, compressor, `atempo=1.15`). Both output OGG Opus 24kbps 16kHz mono.
- **Engine-specific char limits** — Kokoro 500 (schema default), Qwen3 300. `SpeechRequest` model validator rejects Qwen3 voices over 300 chars. Kokoro limit also enforced inside `KokoroEngine.generate_speech`.
- **Single FIFO queue per instance** — one `asyncio.Lock` in `app.state.queue_lock`, no multi-worker model. `queue_depth` incremented/decremented around the lock. Horizontal scaling via `deploy.replicas` in `compose.yaml`.
- **Caddy load-balancing** — `dynamic a` resolver on `tts-service:8000`, re-resolves Docker DNS every 5s with `lb_policy least_conn`. Never switch to `reverse_proxy host:port` (resolves once at startup) or round-robin (loses queue-depth awareness of single-FIFO-lock design).
- **Caddy is the sole external access point** — ports 80/443 only. `tts-service` uses `expose: 8000` (no `ports`), reachable only on the Docker bridge network.
- **TLS via Caddy** — auto Let's Encrypt when `DOMAIN` env var is set to a public hostname; self-signed fallback for `localhost`. Never terminate TLS in the app.
- **Landing page routing** — Caddy `@api path /v1/* /health` matcher proxies to tts-service; `handle {}` default serves static `/srv/www` (bind-mount of `deploy/landing/`). Static assets controlled by `landing_enabled` ansible variable.
- **Rate limiting** — `slowapi.Limiter` keyed by `get_client_ip`. Defaults: `RATE_LIMIT_SPEECH=30/minute`, `RATE_LIMIT_HEALTH=60/minute`. `SlowAPIMiddleware` + custom 429 handler returning `{error: {message, type, hint}}` + `Retry-After`.
- **Trusted proxies** — Caddy `trusted_proxies private_ranges` prevents `X-Forwarded-For` spoofing; the app reads only the leftmost entry.
- **9-phase startup lifespan** — state init → config → logging → model downloads (Kokoro + optionally Qwen3) → noise dir verify → espeak-ng data verify → voices dir verify → engine load → warm-up. Engine init failure → startup fails.
- **Engines can be partially disabled** — `QWEN3_ENABLED=false` skips Qwen3 download/load/warm-up (used on aarch64 where x86_64 binary can't run). `available_voices()` excludes `qwen/*` entries; router returns `InvalidRequestError` if a `qwen/*` voice is requested.
- **Health endpoint contract** — 503 `warming_up` during startup, 200 `healthy` when ready. Auth-gated full response (`engines`, `queue_depth`, `memory_mb`, `uptime_seconds`, `version`); unauthenticated gets minimal `{status, voices}`.
- **Error envelope is uniform** — every error response is `{"error": {"message", "type", "hint"}}`. Custom handlers for 405 (method_not_allowed_error) and 422→400 (invalid_request_error) preserve this shape.
- **Noise calibration differs per engine** — Kokoro: RMS 0.063 (3x more room/hiss). Qwen3: RMS 0.016. Never apply same noise level to both.
- **Default voice** — `DEFAULT_VOICE=kokoro/pm_santa`; validated against `router.available_voices()` at startup; invalid format logs a warning but doesn't fail startup.
- **Models auto-download on first startup** — Kokoro from GitHub releases (default URLs baked in); Qwen3 from `QWEN3_MODEL_URL` / `QWEN3_TOKENIZER_URL` (empty = skip download, for air-gapped). `deploy-models.yml` ansible playbook handles SCP transfer for air-gapped.

### Testing Rules

- **All tests are mocked by default** — no real models, no real inference. Run fast, no GPU.
- **`@pytest.mark.slow` for integration tests** — tests requiring model files excluded from default `uv run pytest`. Run via `uv run pytest -m slow`.
- **Async test pattern** — `asyncio_mode = "auto"`; all test functions `async def`; use `AsyncClient` from httpx (not `TestClient`).
- **Nested test classes by behavior** — group semantically: `TestSpeechSuccess`, `TestAuthenticationError`, `TestVoiceNotFound`, `TestValidationError`, `TestServiceUnavailable`.
- **Fixtures in `conftest.py`** — `mock_settings`, `mock_router` (MagicMock with stubbed methods), `app` (FastAPI with mocked state, no lifespan), `client` (AsyncClient), `auth_headers`.
- **`_clear_settings_cache` autouse fixture** — clears `get_settings` LRU cache before each test to prevent config leakage.
- **Mock assertion pattern** — `mock_router.generate_speech.assert_called_once()` + inspect `call_args.kwargs`, not just response status.
- **Test file naming** — `test_{module}.py` mirrors source; `test_routing.py` tests `EngineRouter` dispatch separately from `test_service.py`.

### Code Quality & Style Rules

- **Everything in English** — code, comments, commits, docs, configs, API responses, error messages, README.md. No exceptions, no Portuguese in project files.
- **ruff enforces lint + format** — line-length 88; rules: E, F, I, UP, B, SIM, N, C4, PTH, RUF. Auto-fix in pre-commit with `--exit-non-zero-on-fix`.
- **Pre-commit gate** — commits pass: ruff-check, ruff-format, hadolint, yamllint, shellcheck, markdownlint-cli2, mypy. Verify with `uv run pre-commit run --all-files`.
- **File organization** — one module per concern in `src/comadre/`. `service.py` is largest (~849 LOC) because it contains both engine classes + post-processing pipelines.
- **Naming conventions** — snake_case for files/functions/vars. PascalCase for classes (`KokoroEngine`, `QwenEngine`, `EngineRouter`, `ComadreError`). UPPER_SNAKE for constants.
- **Default to no comments** — only when WHY is non-obvious (constraint, workaround, surprise). Don't explain WHAT; don't reference task/callers.
- **Commit message format** — imperative tense, English: `feat(scope): ...`, `fix: ...`, `chore: ...`. No emoji prefixes.
- **`.example` files mirror real files** — any change to `.env` must be mirrored in `.env.example`; same for any other template pair.

### Development Workflow Rules

- **Package management: `uv` only** — `uv sync` to install, `uv run` to execute. Lock file is `uv.lock`. Never pip, never poetry.
- **Quality check commands** — `uv run pytest` (tests), `uv run ruff check .` (lint), `uv run mypy src/` (type), `uv run pre-commit run --all-files` (all gates).
- **CI pipeline** — GitHub Actions on push/PR to master: lint → test → docker build. Tests exclude `@pytest.mark.slow`.
- **Docker build requires `API_KEY`** — even for CI (uses dummy). `docker compose build` with `API_KEY=ci-build-dummy`.
- **Ansible become password** — pass via `-e "ansible_become_password=PASSWORD"` on every playbook that uses `become: true`. Never modify inventory to store passwords.
- **Models deploy via SSH, not git** — GGUF files (~1.6 GB) too large for git. Air-gapped: use `deploy-models.yml` (SCP + helper container into Docker volume).
- **Ansible inventory requires manual setup** — `inventory/production.yml` ships with `CHANGE_ME` placeholders for `ansible_host`, `ansible_user`, `repo_url`.
- **Daily restart at 3 AM** — Ansible memory-leak precaution (`restart_hour: 3`).
- **API key rotation** — run `deploy/bin/rotate-api-key.sh` on the VPS; no redeploy needed.
- **Horizontal scaling only** — single FIFO queue per container. Add replicas behind Caddy, never workers/threads inside one instance.
- **Never work in `/tmp`** — all builds/artifacts stay inside the repository (see `.gitignore` for exclusions).
- **`_bmad-output/` is tracked in git** — never add it to `.gitignore`.

### Critical Don't-Miss Rules

**espeak-ng / misaki gotcha:**
- misaki (Kokoro's phonemizer) ignores `ESPEAK_DATA_PATH` — it uses its own bundled `pt_dict` inside `espeakng_loader`. Custom pt_extra dictionary must be copied to BOTH the system path AND the misaki bundled path inside the venv/container. Dockerfile handles this; local dev must replicate.

**Qwen3 engine gotchas:**
- Qwen3 requires `-l pt` for THINK mode — without it, accent is random and siglas are inconsistent.
- Qwen3 4-core sweet spot — beyond 4 CPU cores, diminishing returns (1.5% gain at 6 cores). `QWEN3_THREADS=4`.
- Qwen3 Q8_0 GGUF pre-built is now available from `PabloHoties/Qwen3-TTS-12Hz-0.6B-Base-GGUF` on HuggingFace. Manual conversion (docs/quantizing-qwen3-models.md) is no longer required.
- qwen3-tts-cli build is non-trivial — requires building ggml submodule first, patching OpenMP linking, applying seed patch. See `docs/building-qwen3-tts-cli.md`.
- Qwen3 cannot run on aarch64 — the pre-built binary is x86_64. Set `QWEN3_ENABLED=false` on ARM hosts.

**Sigla handling divergence:**
- Kokoro handles siglas natively via espeak-ng pt_extra dictionary (67 entries). Qwen3 uses `expand_siglas()` to space them (`CNPJ` → `C N P J`), except `WORD_SIGLAS` (SUS, PIX, LOAS, etc.) which are pronounced as words.

**Caddy gotchas:**
- `Server: Caddy` leak on 404/308 is unfixable Caddy limitation. Don't attempt to suppress it.
- The `dynamic a` resolver is load-bearing — plain `reverse_proxy tts-service:8000` would cache the first-resolved IP and defeat replica scaling.

**Anti-patterns — never do these:**
- Never use `pip` or `poetry` — `uv` only
- Never use `docker-compose` — Docker Compose v2: `docker compose`
- Never suggest GPU or cloud TTS — CPU-only, self-hosted, budget constraint absolute
- Never use `/tmp` or system temp dirs for builds/artifacts
- Never write Portuguese in any project file
- Never add workers/threads to scale — horizontal replicas only
- Never raise raw `HTTPException` — use `ComadreError` subclasses
- Never import upward in the module graph
- Never read `request.client.host` for rate limiting or logging — use `get_client_ip(request)`
- Never expose `tts-service` on host ports — Caddy is the sole entry point
- Never hardcode voice names as bare strings (`santa`, `clone`) — always `engine/name`
- Never translate existing unaccented PT prose via regex substitution — always retranslate from scratch

---

## Usage Guidelines

**For AI Agents:**

- Read this file before implementing any code
- Follow ALL rules exactly as documented
- When in doubt, prefer the more restrictive option
- Update this file if new patterns emerge

**For Humans:**

- Keep this file lean and focused on agent needs
- Update when technology stack or architecture changes
- Review after major refactors
- Remove rules that become obvious over time

Last Updated: 2026-04-14
