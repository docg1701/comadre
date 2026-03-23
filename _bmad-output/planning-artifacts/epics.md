---
stepsCompleted: [step-01, step-02, step-03, step-04]
status: complete
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/architecture.md
  - _bmad-output/planning-artifacts/ux-design-specification.md
---

# cumadre - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for cumadre, decomposing the requirements from the PRD, UX Design if it exists, and Architecture requirements into implementable stories.

## Requirements Inventory

### Functional Requirements

- FR1: n8n workflow can submit text and receive synthesized speech audio with dual-engine TTS with voice-based routing
- FR2: n8n workflow can specify the output audio format (OGG Opus default, WAV optional)
- FR3: voice determines engine: santa/dora/alex → Kokoro; clone/qwen-female/qwen-male → Qwen3
- FR4: Kokoro engine generates Brazilian Portuguese speech using espeak-ng with custom pt_extra dictionary
- FR5: Qwen3 engine generates speech with pre-configured cloned voice using reference WAV at deploy time
- FR5a: Engine-specific post-processing pipelines (vibrato_warm for Kokoro, whatsapp-subtle for Qwen3) produce OGG Opus 24kbps 16kHz mono
- FR5b: Engine-specific text preprocessing (normalize_text + chunk_text for Kokoro; expand_siglas for Qwen3)
- FR6: n8n workflow can call an OpenAI-compatible `POST /v1/audio/speech` endpoint
- FR7: The service can authenticate requests using a bearer token
- FR8: The service can reject unauthorized requests with a 401 response
- FR9: The service can return appropriate error codes for malformed requests, missing voices, and internal failures
- FR10: The service can report a 503 status while warming up
- FR11: Any HTTP client can query a health endpoint to check service status
- FR12: The health endpoint can report available voice profiles and their engine assignments
- FR13: The health endpoint can report service uptime, queue depth, engine load status, and clone configuration
- FR14: DevOps operator can configure voice cloning by placing reference WAV (3-10s) on server at deploy time for Qwen3
- FR15: DevOps operator can configure default voice via env var (default: santa)
- FR16: The service can discover built-in Kokoro voices and detect clone reference configuration at startup
- FR17: The service can automatically download models on first run (Kokoro ONNX ~325 MB + voices ~27 MB; Qwen3 GGUF ~1.3 GB + tokenizer ~341 MB)
- FR18: The service can cache downloaded models in a persistent volume
- FR19: The service can warm up both engines on startup
- FR20: Single FIFO queue per instance with asyncio.Lock for sequential request processing
- FR21: Horizontal scaling via Caddy load balancer with round-robin and health checks
- FR22: DevOps operator can bootstrap a complete deployment on a clean VPS using a single Ansible command
- FR23: DevOps operator can update the service from the latest repo without losing voices, model cache, or configuration
- FR24: DevOps operator can fully decommission the service leaving zero artifacts on the VPS
- FR25: DevOps operator can check service health, container state, and disk usage via Ansible
- FR26: Daily restart as safety net (Kokoro leak fixed in phonemizer-fork >=3.3.2)
- FR27: The service can operate with zero outbound network access after initial model download
- FR28: The service can run within Docker resource limits (CPU and memory constraints)
- FR29: Periodic cleanup of generated audio files to prevent disk space exhaustion

### NonFunctional Requirements

- NFR1: Kokoro response latency: typical 5-16s. Qwen3 response latency: typical 12-37s on 4 vCPU
- NFR2: Cold start (container up to healthy) < 120 seconds, excluding initial model download
- NFR3: First request after restart < 10s (dual-engine warm-up)
- NFR4: Throughput per instance: Kokoro ~10 req/min, Qwen3 ~4.8 req/min on 4 vCPU
- NFR5: Memory usage: < 6 GB total (both engines loaded)
- NFR6: All `/v1/audio/speech` requests require valid bearer token; invalid/missing tokens return 401
- NFR7: No sensitive data stored at rest — audio is generated and returned, not persisted
- NFR8: Service operates with zero outbound network access after model download
- NFR9: API key configured via environment variable, never hardcoded or logged
- NFR10: Service availability: 99%+ uptime excluding scheduled daily restarts
- NFR11: Daily restart as safety net — Kokoro leak fixed in phonemizer-fork >=3.3.2
- NFR12: Model cache persists across container restarts and updates via Docker volume
- NFR13: Voice files and configuration survive update operations 100% of the time
- NFR14: Health endpoint accurately reflects actual service state (not just container running)
- NFR15: Bootstrap playbook completes without manual intervention on a clean Ubuntu VPS
- NFR16: Update playbook completes without data loss in under 5 minutes
- NFR17: Cleanup playbook removes 100% of CUMADRE artifacts from VPS
- NFR18: Health playbook reports container state, endpoint status, resource usage, and disk consumption
- NFR19: All Python dependencies managed via `uv`

### Additional Requirements

- Starter template: `uv init --package cumadre` creates project scaffolding with src layout, pyproject.toml, and .python-version — this is Epic 1 Story 1
- Kokoro via kokoro-onnx (PyPI). Qwen3 via qwen3-tts-cli pre-built binary (subprocess)
- Code quality tooling: ruff (lint+format), mypy --strict with pydantic plugin, pytest + pytest-asyncio + httpx, hadolint, yamllint, ansible-lint, shellcheck, markdownlint-cli2, all orchestrated by pre-commit
- Dependency groups (PEP 735): dev = lint + test + type-check groups in pyproject.toml
- Project structure: src/cumadre/ layout with 10 modules (main.py, api.py, schemas.py, service.py, preprocessing.py, config.py, exceptions.py, health.py, logging.py, voices.py)
- Import dependency graph enforced: config/logging at bottom, main.py at top, no circular imports
- Module responsibility boundaries: no HTTP concerns in service.py, no business logic in api.py, no raw os.environ (use pydantic-settings)
- All errors via CumadreError exception hierarchy, never raw HTTPException
- Docker single-stage build using python:3.12-slim with system deps (espeak-ng **built from source** for pt-BR quality — PR #2344, ffmpeg, build deps: autoconf, automake, libtool, pkg-config)
- Compose v2 standard filename: compose.yaml (not docker-compose.yml)
- Single FIFO queue with asyncio.Lock — no multi-worker model
- Engine-specific post-processing pipelines via ffmpeg (vibrato_warm, whatsapp-subtle)
- Custom espeak-ng pt_extra dictionary (67 entries) for sigla pronunciation
- Noise WAV files for post-processing realism (~2 MB)
- qwen3-tts-cli binary with custom seed patch for deterministic Qwen3 generation
- Audio file cleanup strategy to prevent SSD exhaustion
- OGG encoding via ffmpeg subprocess call (~5 lines)
- CI/CD: GitHub Actions pipeline running pre-commit + pytest + docker build
- Ansible flat playbooks in deploy/ansible/playbooks/ (no roles — project too small)
- Ansible privilege model: `become: true` only for apt tasks in bootstrap; all other operations unprivileged
- All project files on VPS live in ~/cumadre — never in /opt, /tmp, or system directories
- User-level crontab for daily container restart (not system cron)
- Docker restart policy: `restart: unless-stopped`
- Docker health check must accommodate warm-up period (start_period)
- Container resource limits: cpus 4, memory 6G in compose.yaml
- Docker named volumes: cumadre-voices (ro), cumadre-models (rw), cumadre-audio (rw)
- .env.example template with API_KEY, DEFAULT_VOICE, PORT
- entrypoint.sh script for uvicorn launch with PORT from env
- Implementation sequence: scaffolding → config → logging → voices → preprocessing + service → FastAPI app → Docker → Ansible → CI/CD → docs
- New dependency: `num2words>=0.5` for pt-BR text normalization (numbers, currency, ordinals)

### UX Design Requirements

- UX-DR1: Error Response Builder — centralized FastAPI exception handler producing OpenAI-compatible error JSON with `message`, `type`, `hint` fields across all error paths (400, 401, 404, 500, 503). All three fields always present, never partial. `type` uses fixed vocabulary: `invalid_request_error`, `authentication_error`, `not_found_error`, `server_error`, `service_unavailable`
- UX-DR2: Health Response Assembler — rich health endpoint returning flat JSON with fixed field order: `status` (enum: healthy/warming_up/degraded), `voices` (always array, never null), `engines` (per-engine status), `queue_depth`, `clone_configured`, `uptime_seconds`, `memory_mb`, `version`. All numeric fields use unit suffixes
- UX-DR3: Structured Logger — pipe-delimited format (`timestamp | level | component | message`) with ISO 8601 UTC timestamps, fixed-width 5-char levels (INFO, WARN, ERROR, CRIT), and component tags (startup, request, memory, health, voice). Request logs include method, path, voice, format, chars, duration
- UX-DR4: Ansible Summary Tasks — every playbook ends with a `[Summary]` debug task reporting final state with proof (evidence over assertions). Bootstrap summary includes the test curl command
- UX-DR5: Voice Discovery Module — startup scan of built-in Kokoro voices and clone reference WAV detection. Logs each loaded voice with its engine assignment and each missing configuration with reason. Called at startup and by health assembler
- UX-DR6: Ansible Task Naming Convention — all tasks follow `[Component] Action description` pattern with consistent component names across playbooks: [Docker], [TTS], [Voice], [Config], [Health], [Cleanup], [Summary]. Failed tasks include `msg` with actionable recovery instructions
- UX-DR7: Error Response Trinity — every error across all surfaces (API responses, Ansible failures, log entries) communicates three things: What (description), Why (cause/context), Do (specific action to resolve). No error code without human-readable message, no problem without resolution
- UX-DR8: Startup Communication Pattern — sequential phase logging where each phase logs when it starts: config → logging → espeak-ng pt_extra verify → clone reference detect → Kokoro load → Qwen3 verify → Kokoro warm-up → Qwen3 warm-up → ready. Final "ready" message includes listen address. Startup failures log the specific phase that failed plus recovery hint
- UX-DR9: Configuration Defaults Pattern — sensible defaults (format=ogg, port=8000) with startup logging of resolved values. Required variables (API_KEY) cause clear startup failure with instructions if missing. Optional variables log their resolved value at startup
- UX-DR10: Terminal Accessibility — all output uses plain ASCII (no emoji, no Unicode box-drawing characters, no ANSI color codes). Pipe-delimited logs parseable by grep/awk/cut. Ansible task names use descriptive English phrases, no abbreviations
- UX-DR11: Documentation Standards — README.md in Brazilian Portuguese, all other docs in English. Copy-paste-ready code examples with realistic values. Configuration tables with 4 columns: variable, default, description, example
- UX-DR12: Self-documenting error messages — plain English with common vocabulary accessible to non-native English speakers. No idioms, no cultural references, no humor. Technical terms (WAV, OGG, bearer token) used only when they are the actual concept

### FR Coverage Map

| FR | Epic | Description |
|---|---|---|
| FR1 | Epic 1 | Submit text, receive dual-engine routed audio |
| FR2 | Epic 1 | Specify output format (OGG Opus default, WAV optional) |
| FR3 | Epic 1 | Voice determines engine routing |
| FR4 | Epic 1 | Kokoro Brazilian Portuguese speech via espeak-ng pt_extra |
| FR5 | Epic 1 | Qwen3 voice cloning via reference WAV |
| FR5a | Epic 1 | Engine-specific post-processing pipelines |
| FR5b | Epic 1 | Engine-specific text preprocessing |
| FR6 | Epic 1 | OpenAI-compatible POST /v1/audio/speech |
| FR7 | Epic 1 | Bearer token authentication |
| FR8 | Epic 1 | Reject unauthorized requests (401) |
| FR9 | Epic 1 | Error codes for malformed requests, missing voices, failures |
| FR10 | Epic 1 | 503 status during warm-up |
| FR11 | Epic 1 | Health endpoint for service status |
| FR12 | Epic 1 | Health reports available voices and engine assignments |
| FR13 | Epic 1 | Health reports uptime, queue depth, engine load, clone config |
| FR14 | Epic 1 | Configure voice cloning via reference WAV at deploy time for Qwen3 |
| FR15 | Epic 1 | Configure default voice via env var (default: santa) |
| FR16 | Epic 1 | Discover Kokoro voices and detect clone reference at startup |
| FR17 | Epic 2 | Auto-download models (Kokoro ONNX + Qwen3 GGUF) |
| FR18 | Epic 2 | Cache models in persistent volume |
| FR19 | Epic 1 | Warm up both engines on startup |
| FR20 | Epic 1 | Single FIFO queue with asyncio.Lock |
| FR21 | Epic 2 | Horizontal scaling via Caddy load balancer |
| FR22 | Epic 3 | Bootstrap deployment via Ansible |
| FR23 | Epic 3 | Update without losing data |
| FR24 | Epic 3 | Full decommission via Ansible |
| FR25 | Epic 3 | Health check via Ansible |
| FR26 | Epic 3 | Daily restart as safety net |
| FR27 | Epic 2 | Zero outbound network post-deploy |
| FR28 | Epic 2 | Docker resource limits |
| FR29 | Epic 2 | Periodic audio file cleanup |

## Epic List

### Epic 1: Audio Generation API
n8n can POST text to an OpenAI-compatible endpoint and receive dual-engine routed audio (OGG Opus/WAV) with voice-based engine selection (Kokoro for santa/dora/alex, Qwen3 for clone/qwen-female/qwen-male), proper authentication, error handling, and health monitoring. The service runs locally via `uv run`.
**FRs covered:** FR1, FR2, FR3, FR4, FR5, FR5a, FR5b, FR6, FR7, FR8, FR9, FR10, FR11, FR12, FR13, FR14, FR15, FR16, FR19, FR20

### Epic 2: Container Packaging & Production Runtime
The operator can run CUMADRE as a Docker service with espeak-ng pt_extra dictionary compilation, qwen3-tts-cli binary, automatic dual-model download/caching, single-worker process, resource limits, and zero outbound network after first run.
**FRs covered:** FR17, FR18, FR21, FR27, FR28, FR29

### Epic 3: Deployment & Lifecycle Operations
The operator can manage CUMADRE's full lifecycle on a remote VPS with single Ansible commands — bootstrap from scratch, update safely, check health diagnostics, decommission completely, and auto-restart daily as a safety net.
**FRs covered:** FR22, FR23, FR24, FR25, FR26

### Epic 4: CI/CD Pipeline & Documentation
Developers have automated quality gates on every push (lint, type check, test, Docker build), and operators have comprehensive documentation to self-serve all operations.
**FRs covered:** Cross-cutting (supports NFR19, UX-DR11)

## Epic 1: Audio Generation API

n8n can POST text to an OpenAI-compatible endpoint and receive dual-engine routed audio (OGG Opus/WAV) with voice-based engine selection (Kokoro for santa/dora/alex, Qwen3 for clone/qwen-female/qwen-male), proper authentication, error handling, and health monitoring. The service runs locally via `uv run`.

### Story 1.1: Project Scaffolding & Quality Tooling

As a **developer**,
I want a properly initialized Python project with all quality tooling configured,
So that all future code is written against consistent standards from day one.

**Acceptance Criteria:**

**Given** a clean repository
**When** I run `uv init --package cumadre`
**Then** the project has src/cumadre/ layout with pyproject.toml and .python-version (3.12)

**Given** the initialized project
**When** I review pyproject.toml
**Then** it includes ruff, mypy (strict + pydantic plugin), pytest + pytest-asyncio + httpx configs, and PEP 735 dependency groups (dev, lint, test, type-check)

**Given** the project with quality tooling
**When** I run `uv run pre-commit run --all-files`
**Then** ruff, mypy, hadolint, yamllint, shellcheck, and markdownlint all execute without errors

**Given** the project structure
**When** I inspect the repository
**Then** .gitignore, .env.example (API_KEY, DEFAULT_VOICE, WORKERS, PORT), .hadolint.yaml, .yamllint.yaml, .ansible-lint, .markdownlint.yaml, and voices/.gitkeep all exist

### Story 1.2: Configuration & Structured Logging

As a **developer**,
I want type-safe configuration and structured logging,
So that all modules have a consistent foundation for settings and observability.

**Acceptance Criteria:**

**Given** the project from Story 1.1
**When** I import config.py
**Then** it provides a `Settings(BaseSettings)` class loading API_KEY (required), DEFAULT_VOICE (default: "default"), WORKERS (default: 1), PORT (default: 8000) from environment variables

**Given** API_KEY is not set in the environment
**When** the Settings class is instantiated
**Then** it raises a validation error with a clear message about the missing required variable

**Given** the logging module
**When** any module logs a message
**Then** the output follows pipe-delimited format: `timestamp | level | component | message` with ISO 8601 UTC timestamps and fixed-width 5-char levels

**Given** the logging module
**When** I create a logger with `get_logger("startup")`
**Then** messages include the component tag and render correctly in plain ASCII (no emoji, no ANSI color codes)

### Story 1.3: Voice Discovery & Validation

As a **DevOps operator**,
I want the service to discover and validate voice files at startup,
So that I know which voices are available and get clear warnings about invalid files.

**Acceptance Criteria:**

**Given** a voices directory containing valid WAV files (3-10 seconds)
**When** the voice discovery module scans the directory
**Then** it returns a list of valid voice names (filename without extension)
**And** logs each loaded voice with its duration (e.g., "Voice 'carlos' loaded from /voices/carlos.wav (5.2s)")

**Given** a voices directory containing a non-WAV file (e.g., .mp3)
**When** the voice discovery module scans the directory
**Then** it skips the file and logs a warning: "File /voices/test.mp3 skipped: not a WAV file"

**Given** a voices directory containing a WAV file longer than 10 seconds
**When** the voice discovery module scans the directory
**Then** it skips the file and logs a warning with the actual duration and the 10s limit

**Given** an empty voices directory
**When** the voice discovery module scans the directory
**Then** it returns an empty list and logs a warning that no voices were found

### Story 1.4: Kokoro TTS Engine Integration

As an **n8n workflow**,
I want the service to generate speech via the Kokoro fp32 engine for built-in voices,
So that customers hear natural-sounding audio responses in Brazilian Portuguese.

**Context:** Kokoro TTS uses espeak-ng as sole phonemizer for pt-BR (misaki has no native Portuguese G2P module). espeak-ng has known limitations: open/close vowel confusion, stress errors, no date/time normalization. Mitigations: text preprocessing, custom pt_extra dictionary (67 entries), and sentence chunking are REQUIRED for acceptable quality.

**Acceptance Criteria:**

**Given** kokoro-onnx is installed as a PyPI dependency
**When** service.py receives text and voice "santa"/"dora"/"alex"
**Then** it preprocesses via normalize_text() + chunk_text(), generates speech via Kokoro fp32, and returns WAV at 24kHz

**Given** the espeak-ng pt_extra dictionary files are in place
**When** Kokoro generates speech containing siglas (CPF, CNPJ, SUS, etc.)
**Then** pronunciation is correct (verified against 34/34 test cases)

**Given** text containing numbers, currency, dates, times
**When** preprocessing.py normalizes
**Then** num2words converts correctly for pt_BR

**Given** text longer than 500 chars
**When** preprocessing rejects it
**Then** clear error with char limit hint

**Given** text longer than ~200 tokens per chunk
**When** chunk_text splits
**Then** it splits at sentence boundaries

**Given** a valid WAV from Kokoro
**When** vibrato_warm post-processing runs
**Then** output is processed through vibrato(4.5Hz, 6%) → highpass(80Hz) → bass(+3dB) → EQ → exciter → softclip → compressor(4:1) → lowpass(8kHz) → echo(40ms, 0.12) → loudnorm(-18 LUFS) → noise(room=0.45, hiss=0.24) → loudnorm(-17 LUFS) → OGG Opus 24kbps 16kHz mono

**Given** format "wav"
**When** service generates audio
**Then** post-processing still applies but outputs WAV instead of OGG

### Story 1.5: Qwen3-TTS Engine Integration

As an **n8n workflow**,
I want the service to generate speech via the Qwen3-TTS engine for clone and Qwen voices,
So that customers hear cloned-voice or alternative voice audio responses.

**Context:** Qwen3-TTS runs as a C++ Q8_0 quantized binary (qwen3-tts-cli) invoked via subprocess. It supports voice cloning from a reference WAV and deterministic generation via custom seed patch.

**Acceptance Criteria:**

**Given** qwen3-tts-cli binary is available
**When** service.py receives text and voice "clone"/"qwen-female"/"qwen-male"
**Then** it preprocesses via expand_siglas(), generates speech via qwen3-tts-cli subprocess with -l pt --temperature 0.7 --seed N -j 4, and returns WAV

**Given** text containing spelled siglas (CPF, CNPJ, FGTS, etc.)
**When** expand_siglas() processes them
**Then** they become spaced format ("C N P J"). Word siglas (SUS, PIX, LOAS) are kept as-is

**Given** voice "clone" and a clone reference WAV is configured
**When** Qwen3 generates speech
**Then** it uses the reference audio for voice cloning

**Given** voice "clone" but no clone reference WAV is configured
**When** service detects this at startup
**Then** "clone" voice is disabled and health reports clone_configured: false

**Given** text longer than 300 chars
**When** preprocessing rejects it
**Then** clear error with char limit hint

**Given** a valid WAV from Qwen3
**When** whatsapp-subtle post-processing runs
**Then** output is processed through highpass(100Hz) → EQ → compressor(6:1) → lowpass(8kHz) → echo(40ms) → atempo(1.15x) → loudnorm(-18 LUFS) → noise(room=0.15, hiss=0.08) → loudnorm(-17 LUFS) → OGG Opus 24kbps 16kHz mono

**Given** a seed parameter
**When** Qwen3 generates with same seed and same text
**Then** output is identical (deterministic)

### Story 1.6: Engine Router & Unified Service API

As an **n8n workflow**,
I want to specify a voice name and have the correct engine handle the request,
So that voice selection is simple and engine details are transparent.

**Acceptance Criteria:**

**Given** voice "santa", "dora", or "alex"
**When** service routes the request
**Then** Kokoro engine handles it with normalize_text + chunk_text preprocessing and vibrato_warm post-processing

**Given** voice "clone", "qwen-female", or "qwen-male"
**When** service routes the request
**Then** Qwen3 engine handles it with expand_siglas preprocessing and whatsapp-subtle post-processing

**Given** an unknown voice name
**When** service routes the request
**Then** it raises VoiceNotFoundError with available voice list

**Given** the service module
**When** generate_speech() is called
**Then** it provides a unified API that internally dispatches to the correct engine

**Given** noise WAV files (room ambience + hiss)
**When** post-processing runs
**Then** correct noise calibration is applied per engine (Kokoro needs 3x more noise than Qwen3)

### Story 1.7: Exception Handling & Request Schemas

As an **n8n workflow**,
I want consistent, self-documenting error responses on every failure,
So that I can programmatically handle errors and the operator can diagnose issues.

**Acceptance Criteria:**

**Given** the exceptions module
**When** I inspect the error hierarchy
**Then** `CumadreError` is the base class with `status_code`, `error_type`, and `hint` attributes, and subclasses exist for: `AuthenticationError` (401), `InvalidRequestError` (400), `VoiceNotFoundError` (404), `GenerationError` (500), `ServiceUnavailableError` (503)

**Given** any `CumadreError` is raised during request processing
**When** the centralized exception handler catches it
**Then** it returns JSON with all three fields always present: `error.message`, `error.type`, `error.hint`
**And** the `hint` field contains an actionable instruction, never a restatement of the message

**Given** an unexpected exception (not a CumadreError subclass)
**When** the fallback handler catches it
**Then** it returns a 500 response with `error.type: "server_error"` and a generic hint referencing log inspection
**And** the full traceback is logged server-side at ERROR level but never returned to the client

**Given** the schemas module
**When** I inspect `SpeechRequest`
**Then** it validates `input` (required string), `voice` (optional string, default from config), `response_format` (optional, default "ogg", enum: "ogg"/"wav"), `speed` (optional float, default 1.0, reserved for future use), `destination` (optional string, default "whatsapp", enum: "whatsapp"/"telegram"/"messenger"/"instagram")
**And** char limits are validated per engine: 500 for Kokoro voices (santa/dora/alex), 300 for Qwen3 voices (clone/qwen-female/qwen-male)

### Story 1.8: Health Endpoint

As a **DevOps operator**,
I want a rich health endpoint that reports service state at a glance,
So that I can monitor the service and diagnose issues without SSH-ing into the VPS.

**Acceptance Criteria:**

**Given** the service is running and healthy
**When** I send `GET /health`
**Then** I receive a 200 JSON response with fixed field order: `status` ("healthy"), `voices` (array of loaded voice names), `engines` (per-engine status object), `queue_depth`, `clone_configured`, `uptime_seconds`, `memory_mb`, `version`

**Given** the service is still loading models or warming up
**When** I send `GET /health`
**Then** I receive a 503 JSON response with `status: "warming_up"`

**Given** the health endpoint
**When** I send a request without an Authorization header
**Then** it responds normally (no authentication required for health)

**Given** the health response
**When** I inspect the `voices` field
**Then** it is always an array (never null), and empty `[]` if no voices are loaded

**Given** the health response
**When** I inspect the `engines` field
**Then** it contains per-engine status (kokoro: ready/loading/error, qwen3: ready/loading/error/disabled)

### Story 1.9: Speech Endpoint with Auth, Queue & Warm-up

As an **n8n workflow**,
I want to call `POST /v1/audio/speech` with a bearer token and receive engine-routed audio,
So that customers hear natural voice responses on WhatsApp/Telegram.

**Acceptance Criteria:**

**Given** a valid bearer token and valid request body `{"input": "Olá", "voice": "santa", "response_format": "ogg"}`
**When** I send `POST /v1/audio/speech`
**Then** I receive a 200 response with `Content-Type: audio/ogg` and binary OGG Opus audio

**Given** a missing or invalid Authorization header
**When** I send `POST /v1/audio/speech`
**Then** I receive a 401 JSON error with `type: "authentication_error"` and a hint about checking the API_KEY env var

**Given** a request with missing `input` field
**When** I send `POST /v1/audio/speech`
**Then** I receive a 400 JSON error with `type: "invalid_request_error"` and a hint showing the expected request format

**Given** no `voice` field in the request
**When** I send `POST /v1/audio/speech`
**Then** the service uses the DEFAULT_VOICE from configuration (default: santa)

**Given** the service has just started and engines are still warming up
**When** I send `POST /v1/audio/speech`
**Then** I receive a 503 JSON error with `type: "service_unavailable"` and a hint to retry in N seconds

**Given** the FastAPI lifespan
**When** the application starts
**Then** it loads config, configures logging, verifies espeak-ng pt_extra dictionary, detects clone reference WAV, loads Kokoro engine, verifies Qwen3 binary, runs Kokoro warm-up, runs Qwen3 warm-up, and sets the ready flag
**And** each phase is logged when it starts (startup communication pattern)
**And** the final "ready" message includes the listen address

**Given** concurrent requests arrive
**When** the single asyncio.Lock queue processes them
**Then** requests are handled sequentially (FIFO) with queue depth tracked for health endpoint

**Given** a request is being processed
**When** engine-specific timeout (120s) is exceeded
**Then** the request fails with a GenerationError and the queue is released for the next request

### Story 1.10: API & Health Tests

As a **developer**,
I want automated tests covering auth, validation, success paths, engine routing, and health states,
So that regressions are caught before deployment.

**Acceptance Criteria:**

**Given** the test suite
**When** I run `uv run pytest`
**Then** all tests pass using mocked engines (no real model loading for both Kokoro and Qwen3)

**Given** conftest.py
**When** tests use the test client
**Then** it provides a FastAPI AsyncClient via httpx, mock settings, and temporary voice directory fixtures

**Given** test_api.py
**When** I review the test coverage
**Then** it tests: valid request returns audio, missing auth returns 401, malformed request returns 400, missing voice returns 404, service warming up returns 503

**Given** test_routing.py
**When** I review the test coverage
**Then** it tests: Kokoro voices route to Kokoro engine, Qwen3 voices route to Qwen3 engine, unknown voice returns VoiceNotFoundError, correct preprocessing pipeline per engine, correct post-processing pipeline per engine

**Given** test_health.py
**When** I review the test coverage
**Then** it tests: healthy status returns 200 with all fields including engines and queue_depth, warming_up status returns 503, voices array reflects discovered voices, clone_configured reflects clone reference state, health requires no authentication

**Given** test_queue.py
**When** I review the test coverage
**Then** it tests: sequential processing under asyncio.Lock, queue depth increments and decrements correctly

## Epic 2: Container Packaging & Production Runtime

The operator can run CUMADRE as a Docker service with espeak-ng pt_extra dictionary compilation, qwen3-tts-cli binary, automatic dual-model download/caching, single-worker process, resource limits, and zero outbound network after first run.

### Story 2.1: Dockerfile & Entrypoint

As a **DevOps operator**,
I want a production-ready Docker image that builds the service with all dependencies for both engines,
So that I can run CUMADRE as a container without installing Python or system packages on the host.

**Acceptance Criteria:**

**Given** the Dockerfile
**When** I run `docker compose build`
**Then** it builds a single-stage image from python:3.12-slim with espeak-ng **built from source** (git master, includes PR #2344 pt-BR improvements) and ffmpeg (with AAC encoding support for Instagram destination) installed as system packages
**And** Python dependencies are installed via `uv sync --frozen` from the committed uv.lock
**And** build dependencies (autoconf, automake, libtool, pkg-config) are cleaned up after espeak-ng compilation to reduce image size

**Given** the Dockerfile
**When** the build compiles espeak-ng
**Then** the pt_extra dictionary is compiled and ALL data files (pt_dict, phondata, phonindex, phontab) are copied to BOTH the system espeak-ng data path (`/usr/local/share/espeak-ng-data/`) AND the misaki/espeakng_loader bundled data path inside the venv

**Given** the Dockerfile
**When** the build completes
**Then** the qwen3-tts-cli binary (~600 KB, with custom seed patch) is placed in the image at a known path
**And** noise WAV files (~2 MB total: room ambience + mic hiss) are baked into the image
**And** total baked-in binary assets (espeak-ng pt_extra data + qwen3-tts-cli + noise WAVs) are under 5 MB

**Given** the entrypoint.sh script
**When** the container starts
**Then** it launches uvicorn as a single process (no WORKERS env var, no multi-worker configuration) with the port from PORT env var (default 8000)

**Given** the built Docker image
**When** the container starts for the first time (no cached models)
**Then** it automatically downloads Kokoro ONNX model (~325 MB) + voice files (~27 MB) and Qwen3 GGUF model (~1.3 GB) + tokenizer (~341 MB) and stores them in the /models directory
**And** total model storage is approximately 2 GB

**Given** models were previously downloaded
**When** the container restarts or is rebuilt
**Then** models are loaded from the cached /models directory with zero network access required

**Given** the `destination` request parameter is set to `instagram`
**When** the post-processing pipeline encodes audio
**Then** ffmpeg outputs AAC M4A (44.1kHz, 64kbps) instead of OGG Opus, confirming AAC encoding capability is present in the Docker image

### Story 2.2: Docker Compose & Production Configuration

As a **DevOps operator**,
I want a compose.yaml that defines the complete production runtime,
So that `docker compose up` starts a properly configured, resource-limited service.

**Acceptance Criteria:**

**Given** compose.yaml
**When** I run `docker compose up`
**Then** the tts-service starts with three named volumes mounted: `cumadre-models:/models:rw`, `cumadre-voices:/voices:ro`, and `cumadre-audio:/audio:rw` (for generated audio files requiring periodic cleanup)

**Given** compose.yaml environment variables
**When** I inspect the service definition
**Then** it defines `API_KEY` (from host env or .env), `DEFAULT_VOICE` (default: santa), `CLONE_REFERENCE` (path to clone reference WAV inside container), and `ESPEAK_DATA_PATH` (system espeak-ng data path)
**And** there is NO `WORKERS` env var — single-process architecture is enforced

**Given** compose.yaml resource limits
**When** the container is running
**Then** it is constrained to cpus: 4 and memory: 6G (sufficient for both Kokoro and Qwen3 engines loaded simultaneously)

**Given** compose.yaml restart policy
**When** the container crashes or the host reboots
**Then** Docker automatically restarts it (`restart: unless-stopped`)

**Given** compose.yaml health check
**When** the container starts
**Then** Docker health check polls `GET /health` with a start_period that accommodates dual-engine model download and warm-up (120s)
**And** the container is marked healthy only when the health endpoint returns 200

**Given** the container is a single-worker process
**When** the container starts
**Then** uvicorn launches a single process with asyncio.Lock for sequential request handling (no concurrent TTS generation)

**Given** the container is running with cached models
**When** I inspect outbound network traffic
**Then** zero outbound connections are made — all operation is local

**Given** the cumadre-audio volume
**When** TTS requests are processed
**Then** generated audio files are written to the audio volume mount
**And** these files accumulate and require periodic cleanup (configured by Ansible bootstrap in Epic 3) to prevent disk exhaustion

## Epic 3: Deployment & Lifecycle Operations

The operator can manage CUMADRE's full lifecycle on a remote VPS with single Ansible commands — bootstrap from scratch, update safely, check health diagnostics, decommission completely, and auto-restart daily as a safety net.

### Story 3.1: Ansible Project Structure & Bootstrap Playbook

As a **DevOps operator**,
I want to bootstrap CUMADRE on a clean VPS with a single Ansible command,
So that the service is fully deployed and healthy without manual intervention.

**Acceptance Criteria:**

**Given** deploy/ansible/ directory
**When** I inspect the structure
**Then** it contains ansible.cfg, inventory/production.yml, and playbooks/ directory

**Given** a clean Ubuntu VPS with SSH access
**When** I run `ansible-playbook playbooks/bootstrap.yml -i inventory/production.yml`
**Then** it installs Docker (using `become: true` for apt tasks only), clones the repo to ~/cumadre, deploys the qwen3-tts-cli binary (~600 KB with seed patch), deploys the clone reference WAV (if provided), builds the container, starts the service, configures audio cleanup cron, configures daily restart cron, and waits for healthy status
**And** all project files on the VPS live in ~/cumadre (never in /opt, /tmp, or system directories)

**Given** the bootstrap playbook
**When** I inspect the task names
**Then** every task follows the `[Component] Action description` pattern (e.g., `[Docker] Install Docker Engine`, `[TTS] Build service container`, `[Health] Verify endpoint responds`)

**Given** the bootstrap playbook completes successfully
**When** I read the final task output
**Then** it is a `[Summary]` task reporting: service status, loaded voices, engine statuses (both Kokoro and Qwen3), clone configuration status, endpoint URL, and a copy-paste-ready test curl command

**Given** the bootstrap playbook
**When** it configures the daily restart cron
**Then** it creates a user-level crontab entry (not system cron) that runs `docker compose restart` daily as a safety net (Kokoro memory leak fixed in phonemizer-fork >=3.3.2, but daily restart adds defense-in-depth)

**Given** the bootstrap playbook
**When** it configures audio cleanup
**Then** it creates a user-level crontab entry that runs every 6 hours, deleting audio files (*.ogg, *.wav) older than 24 hours from the audio volume to prevent disk space exhaustion

**Given** a prerequisite check fails (e.g., missing SSH access)
**When** the playbook task fails
**Then** the failure `msg` includes what went wrong, why, and what to do to fix it

### Story 3.2: Update Playbook

As a **DevOps operator**,
I want to update CUMADRE from the latest repo without losing data,
So that I can deploy new features and fixes safely.

**Acceptance Criteria:**

**Given** a running CUMADRE deployment
**When** I run `ansible-playbook playbooks/update.yml -i inventory/production.yml`
**Then** it pulls the latest repo, updates the qwen3-tts-cli binary if changed, rebuilds the Docker image (which recompiles espeak-ng pt_extra if the dictionary source changed), and restarts the container
**And** runs entirely unprivileged (no `become: true`)

**Given** the update playbook completes
**When** I check the service
**Then** voice files in cumadre-voices volume are intact, model cache in cumadre-models volume is intact, generated audio files in cumadre-audio volume are intact, clone reference WAV is intact, and the API_KEY is unchanged

**Given** the update playbook completes
**When** I read the final `[Summary]` task
**Then** it confirms service health status, data preservation, both engine statuses (Kokoro and Qwen3), clone configuration, and loaded voices

**Given** the update includes changes to the pt_extra dictionary or noise WAV files
**When** the Docker image is rebuilt
**Then** the updated assets are baked into the new image automatically via the build process

### Story 3.3: Health & Cleanup Playbooks

As a **DevOps operator**,
I want to diagnose service issues and fully decommission CUMADRE when needed,
So that I can troubleshoot at 2 AM and leave zero artifacts when retiring the service.

**Acceptance Criteria:**

**Given** a running CUMADRE deployment
**When** I run `ansible-playbook playbooks/health.yml -i inventory/production.yml`
**Then** it checks container state, queries the health endpoint, and reports: memory usage, loaded voices, both engine statuses (Kokoro: ready/loading/error, Qwen3: ready/loading/error/disabled), queue depth, clone configuration status, uptime, disk consumption (including audio volume size), and audio file cleanup cron status
**And** runs entirely unprivileged

**Given** the health playbook detects high memory (> 5 GB)
**When** I read the output
**Then** it warns about memory pressure and suggests restarting the container and verifying the daily restart cron (safety net — Kokoro leak fixed in phonemizer-fork >=3.3.2)

**Given** the health playbook finds the container not running
**When** I read the output
**Then** it reports the container state and suggests checking `docker compose logs` and restarting

**Given** the health playbook detects audio file disk usage above threshold
**When** I read the output
**Then** it warns about disk pressure and suggests verifying the audio cleanup cron is active (expected: every 6h, deleting files older than 24h)

**Given** the health playbook checks engine status
**When** Qwen3 reports as disabled
**Then** the output explains that clone reference WAV may be missing and suggests verifying CLONE_REFERENCE configuration

**Given** a CUMADRE deployment I want to remove
**When** I run `ansible-playbook playbooks/cleanup.yml -i inventory/production.yml`
**Then** it stops containers, removes images, removes all three named volumes (cumadre-models, cumadre-voices, cumadre-audio), removes the ~/cumadre directory, and removes both crontab entries (daily restart and audio cleanup)
**And** runs entirely unprivileged

**Given** the cleanup playbook completes
**When** I inspect the VPS
**Then** zero CUMADRE artifacts remain
**And** the `[Summary]` task confirms complete removal

## Epic 4: CI/CD Pipeline & Documentation

Developers have automated quality gates on every push (lint, type check, test, Docker build), and operators have comprehensive documentation to self-serve all operations.

### Story 4.1: GitHub Actions CI Pipeline

As a **developer**,
I want automated quality checks on every push and pull request,
So that code quality, type safety, tests, and Docker build are validated before merging.

**Acceptance Criteria:**

**Given** .github/workflows/ci.yml
**When** I push code or open a pull request
**Then** GitHub Actions runs: pre-commit (ruff, mypy, hadolint, yamllint, shellcheck, markdownlint), pytest, and docker compose build
**And** the Docker build step validates that espeak-ng compiles from source, pt_extra dictionary compiles, qwen3-tts-cli binary is placed, and noise WAV files are baked in

**Given** any quality check fails
**When** I view the CI run
**Then** the failing step is clearly identified with actionable output

**Given** all checks pass
**When** the CI run completes
**Then** the pipeline reports success and the PR is safe to merge

**Given** the Docker build step in CI
**When** it builds the image
**Then** the build succeeds despite the complexity of espeak-ng from source compilation, dual-engine binary assets, and pt_extra dictionary compilation

### Story 4.2: Project Documentation

As a **DevOps operator**,
I want comprehensive documentation covering API reference, deployment, configuration, and troubleshooting,
So that I can self-serve all operations without external help.

**Acceptance Criteria:**

**Given** README.md
**When** I read it
**Then** it is written in Brazilian Portuguese, starts with a one-line project description, includes a quick start section within the first screen, and has copy-paste-ready commands with realistic example values

**Given** English operator documentation
**When** I review the docs
**Then** they cover: API reference (endpoint, request/response, error codes with dual-engine details), dual-engine architecture (Kokoro fp32 for speed/siglas + Qwen3 C++ Q8_0 for cloning), voice routing table (which voices map to which engine), post-processing pipelines (vibrato_warm and whatsapp-subtle), platform compatibility (WhatsApp/Telegram/Messenger use OGG Opus, Instagram uses AAC M4A via `destination` parameter), deployment guide (bootstrap, update, cleanup, health), configuration reference (4-column table: variable, default, description, example), and troubleshooting (common issues with resolution steps for both engines)

**Given** the documentation covers voice cloning
**When** I review the clone setup section
**Then** it explains the pre-configured reference WAV approach (placed on server at deploy time, not per-request upload), the CLONE_REFERENCE env var, seed reproducibility for consistent voice characteristics, and that clone is disabled if no reference WAV is present

**Given** the documentation covers the `destination` parameter
**When** I review the platform section
**Then** it explains that `whatsapp`/`telegram`/`messenger` produce OGG Opus (16kHz, 24kbps, mono) and `instagram` produces AAC M4A (44.1kHz, 64kbps), with examples for each

**Given** any code example in the documentation
**When** I copy and paste it
**Then** it works with only the expected substitutions (API key, VPS IP) clearly indicated
**And** error examples are included alongside success examples
