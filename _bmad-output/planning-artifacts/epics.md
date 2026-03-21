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

- FR1: n8n workflow can submit text and receive synthesized speech audio with a cloned voice
- FR2: n8n workflow can specify the output audio format (WAV or OGG)
- FR3: n8n workflow can specify which voice profile to use for generation
- FR4: The service can generate Brazilian Portuguese speech using espeak-ng phonemization
- FR5: The service can convert generated speech to a cloned voice using a reference WAV file
- FR6: n8n workflow can call an OpenAI-compatible `POST /v1/audio/speech` endpoint
- FR7: The service can authenticate requests using a bearer token
- FR8: The service can reject unauthorized requests with a 401 response
- FR9: The service can return appropriate error codes for malformed requests, missing voices, and internal failures
- FR10: The service can report a 503 status while warming up
- FR11: Any HTTP client can query a health endpoint to check service status
- FR12: The health endpoint can report available voice profiles
- FR13: The health endpoint can report service uptime
- FR14: DevOps operator can provision a voice by placing a reference WAV file (3-10s) in the voices directory
- FR15: DevOps operator can configure the default voice via environment variable
- FR16: The service can discover and load voice files from the mounted volume at startup
- FR17: The service can automatically download required models from HuggingFace on first run
- FR18: The service can cache downloaded models in a persistent volume
- FR19: The service can warm up models on startup to prevent slow first requests
- FR20: DevOps operator can configure the number of worker processes via environment variable
- FR21: The service can run multiple independent worker processes for concurrent request handling
- FR22: DevOps operator can bootstrap a complete deployment on a clean VPS using a single Ansible command
- FR23: DevOps operator can update the service from the latest repo without losing voices, model cache, or configuration
- FR24: DevOps operator can fully decommission the service leaving zero artifacts on the VPS
- FR25: DevOps operator can check service health, container state, and disk usage via Ansible
- FR26: The host can automatically restart the service on a daily schedule to mitigate memory leaks
- FR27: The service can operate with zero outbound network access after initial model download
- FR28: The service can run within Docker resource limits (CPU and memory constraints)

### NonFunctional Requirements

- NFR1: Response latency < 3 seconds for short phrases (~15 words) on 4 vCPU hardware
- NFR2: Cold start (container up to healthy) < 120 seconds, excluding initial model download
- NFR3: First request after restart completes within 5 seconds (warm-up requirement)
- NFR4: Throughput: 20-60 requests/minute depending on worker count
- NFR5: Memory usage: < 3 GB steady state per worker
- NFR6: All `/v1/audio/speech` requests require valid bearer token; invalid/missing tokens return 401
- NFR7: No sensitive data stored at rest — audio is generated and returned, not persisted
- NFR8: Service operates with zero outbound network access after model download
- NFR9: API key configured via environment variable, never hardcoded or logged
- NFR10: Service availability: 99%+ uptime excluding scheduled daily restarts
- NFR11: Daily automatic restart mitigates memory leak — RAM must not exceed 4 GB over 24 hours of continuous operation
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
- KokoClone is not on PyPI — must be installed as a uv git dependency pinned by commit hash in uv.lock
- Code quality tooling: ruff (lint+format), mypy --strict with pydantic plugin, pytest + pytest-asyncio + httpx, hadolint, yamllint, ansible-lint, shellcheck, markdownlint-cli2, all orchestrated by pre-commit
- Dependency groups (PEP 735): dev = lint + test + type-check groups in pyproject.toml
- Project structure: src/cumadre/ layout with 9 modules (main.py, api.py, schemas.py, service.py, config.py, exceptions.py, health.py, logging.py, voices.py)
- Import dependency graph enforced: config/logging at bottom, main.py at top, no circular imports
- Module responsibility boundaries: no HTTP concerns in service.py, no business logic in api.py, no raw os.environ (use pydantic-settings)
- All errors via CumadreError exception hierarchy, never raw HTTPException
- Docker single-stage build using python:3.12-slim with system deps (espeak-ng, ffmpeg, libsndfile1-dev)
- Compose v2 standard filename: compose.yaml (not docker-compose.yml)
- OGG encoding via ffmpeg subprocess call (~5 lines)
- CI/CD: GitHub Actions pipeline running pre-commit + pytest + docker build
- Ansible flat playbooks in deploy/ansible/playbooks/ (no roles — project too small)
- Ansible privilege model: `become: true` only for apt tasks in bootstrap; all other operations unprivileged
- All project files on VPS live in ~/cumadre — never in /opt, /tmp, or system directories
- User-level crontab for daily container restart (not system cron)
- Docker restart policy: `restart: unless-stopped`
- Docker health check must accommodate warm-up period (start_period)
- Container resource limits: cpus 4, memory 6G in compose.yaml
- Docker named volumes: cumadre-voices (ro), cumadre-models (rw)
- .env.example template with API_KEY, DEFAULT_VOICE, WORKERS, PORT
- entrypoint.sh script for uvicorn launch with WORKERS/PORT from env
- Implementation sequence: scaffolding → config → logging → voices → service → FastAPI app → Docker → Ansible → CI/CD → docs

### UX Design Requirements

- UX-DR1: Error Response Builder — centralized FastAPI exception handler producing OpenAI-compatible error JSON with `message`, `type`, `hint` fields across all error paths (400, 401, 404, 500, 503). All three fields always present, never partial. `type` uses fixed vocabulary: `invalid_request_error`, `authentication_error`, `not_found_error`, `server_error`, `service_unavailable`
- UX-DR2: Health Response Assembler — rich health endpoint returning flat JSON with fixed field order: `status` (enum: healthy/warming_up/degraded), `voices` (always array, never null), `uptime_seconds`, `memory_mb`, `workers`, `version`. All numeric fields use unit suffixes
- UX-DR3: Structured Logger — pipe-delimited format (`timestamp | level | component | message`) with ISO 8601 UTC timestamps, fixed-width 5-char levels (INFO, WARN, ERROR, CRIT), and component tags (startup, request, memory, health, voice). Request logs include method, path, voice, format, chars, duration
- UX-DR4: Ansible Summary Tasks — every playbook ends with a `[Summary]` debug task reporting final state with proof (evidence over assertions). Bootstrap summary includes the test curl command
- UX-DR5: Voice Discovery Module — startup scan of /voices/ directory with WAV validation (file exists, valid WAV, 3-10s duration). Logs each loaded voice with duration and each skipped file with reason. Called at startup and by health assembler
- UX-DR6: Ansible Task Naming Convention — all tasks follow `[Component] Action description` pattern with consistent component names across playbooks: [Docker], [TTS], [Voice], [Config], [Health], [Cleanup], [Summary]. Failed tasks include `msg` with actionable recovery instructions
- UX-DR7: Error Response Trinity — every error across all surfaces (API responses, Ansible failures, log entries) communicates three things: What (description), Why (cause/context), Do (specific action to resolve). No error code without human-readable message, no problem without resolution
- UX-DR8: Startup Communication Pattern — sequential phase logging where each phase logs when it starts: model loading → voice discovery → warm-up → ready. Final "ready" message includes listen address. Startup failures log the specific phase that failed plus recovery hint
- UX-DR9: Configuration Defaults Pattern — sensible defaults (format=wav, workers=1, port=8000) with startup logging of resolved values. Required variables (API_KEY) cause clear startup failure with instructions if missing. Optional variables log their resolved value at startup
- UX-DR10: Terminal Accessibility — all output uses plain ASCII (no emoji, no Unicode box-drawing characters, no ANSI color codes). Pipe-delimited logs parseable by grep/awk/cut. Ansible task names use descriptive English phrases, no abbreviations
- UX-DR11: Documentation Standards — README.md in Brazilian Portuguese, all other docs in English. Copy-paste-ready code examples with realistic values. Configuration tables with 4 columns: variable, default, description, example
- UX-DR12: Self-documenting error messages — plain English with common vocabulary accessible to non-native English speakers. No idioms, no cultural references, no humor. Technical terms (WAV, OGG, bearer token) used only when they are the actual concept

### FR Coverage Map

| FR | Epic | Description |
|---|---|---|
| FR1 | Epic 1 | Submit text, receive cloned-voice audio |
| FR2 | Epic 1 | Specify output format (WAV/OGG) |
| FR3 | Epic 1 | Specify voice profile |
| FR4 | Epic 1 | Brazilian Portuguese speech via espeak-ng |
| FR5 | Epic 1 | Voice cloning via reference WAV |
| FR6 | Epic 1 | OpenAI-compatible POST /v1/audio/speech |
| FR7 | Epic 1 | Bearer token authentication |
| FR8 | Epic 1 | Reject unauthorized requests (401) |
| FR9 | Epic 1 | Error codes for malformed requests, missing voices, failures |
| FR10 | Epic 1 | 503 status during warm-up |
| FR11 | Epic 1 | Health endpoint for service status |
| FR12 | Epic 1 | Health reports available voices |
| FR13 | Epic 1 | Health reports uptime |
| FR14 | Epic 1 | Provision voice via reference WAV file |
| FR15 | Epic 1 | Configure default voice via env var |
| FR16 | Epic 1 | Discover and load voices at startup |
| FR17 | Epic 2 | Auto-download models from HuggingFace |
| FR18 | Epic 2 | Cache models in persistent volume |
| FR19 | Epic 1 | Warm up models on startup |
| FR20 | Epic 2 | Configure worker count via env var |
| FR21 | Epic 2 | Multiple independent workers |
| FR22 | Epic 3 | Bootstrap deployment via Ansible |
| FR23 | Epic 3 | Update without losing data |
| FR24 | Epic 3 | Full decommission via Ansible |
| FR25 | Epic 3 | Health check via Ansible |
| FR26 | Epic 3 | Daily auto-restart via cron |
| FR27 | Epic 2 | Zero outbound network post-deploy |
| FR28 | Epic 2 | Docker resource limits |

## Epic List

### Epic 1: Audio Generation API
n8n can POST text to an OpenAI-compatible endpoint and receive cloned-voice audio (WAV/OGG) with proper authentication, error handling, and health monitoring. The service runs locally via `uv run`.
**FRs covered:** FR1, FR2, FR3, FR4, FR5, FR6, FR7, FR8, FR9, FR10, FR11, FR12, FR13, FR14, FR15, FR16, FR19

### Epic 2: Container Packaging & Production Runtime
The operator can run CUMADRE as a Docker service with automatic model download/caching, configurable workers for concurrency, resource limits, and zero outbound network after first run.
**FRs covered:** FR17, FR18, FR20, FR21, FR27, FR28

### Epic 3: Deployment & Lifecycle Operations
The operator can manage CUMADRE's full lifecycle on a remote VPS with single Ansible commands — bootstrap from scratch, update safely, check health diagnostics, decommission completely, and auto-restart daily for memory leak mitigation.
**FRs covered:** FR22, FR23, FR24, FR25, FR26

### Epic 4: CI/CD Pipeline & Documentation
Developers have automated quality gates on every push (lint, type check, test, Docker build), and operators have comprehensive documentation to self-serve all operations.
**FRs covered:** Cross-cutting (supports NFR19, UX-DR11)

## Epic 1: Audio Generation API

n8n can POST text to an OpenAI-compatible endpoint and receive cloned-voice audio (WAV/OGG) with proper authentication, error handling, and health monitoring. The service runs locally via `uv run`.

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

### Story 1.4: KokoClone TTS Service Wrapper

As an **n8n workflow**,
I want the service to generate cloned-voice speech from text,
So that customers hear natural-sounding audio responses.

**Acceptance Criteria:**

**Given** KokoClone is installed as a uv git dependency
**When** service.py receives text, a voice name, and format "wav"
**Then** it generates Brazilian Portuguese speech via Kokoro TTS, converts it to the cloned voice via Kanade using the reference WAV, and returns WAV bytes at 24kHz

**Given** a valid text input and format "ogg"
**When** service.py generates audio
**Then** it encodes the WAV output to OGG via ffmpeg subprocess and returns valid OGG bytes

**Given** a voice name that has no corresponding reference WAV
**When** service.py attempts to generate audio
**Then** it raises a `VoiceNotFoundError` (not an HTTPException) with the requested voice name and list of available voices

**Given** KokoClone fails during generation
**When** service.py catches the model error
**Then** it raises a `GenerationError` with a descriptive message and logs the full traceback at ERROR level

### Story 1.5: Exception Handling & Request Schemas

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
**Then** it validates `input` (required string), `voice` (optional string), `response_format` (optional, default "wav", enum: "wav"/"ogg")

### Story 1.6: Health Endpoint

As a **DevOps operator**,
I want a rich health endpoint that reports service state at a glance,
So that I can monitor the service and diagnose issues without SSH-ing into the VPS.

**Acceptance Criteria:**

**Given** the service is running and healthy
**When** I send `GET /health`
**Then** I receive a 200 JSON response with fixed field order: `status` ("healthy"), `voices` (array of loaded voice names), `uptime_seconds`, `memory_mb`, `workers`, `version`

**Given** the service is still loading models or warming up
**When** I send `GET /health`
**Then** I receive a 503 JSON response with `status: "warming_up"`

**Given** the health endpoint
**When** I send a request without an Authorization header
**Then** it responds normally (no authentication required for health)

**Given** the health response
**When** I inspect the `voices` field
**Then** it is always an array (never null), and empty `[]` if no voices are loaded

### Story 1.7: Speech Endpoint with Auth & Warm-up

As an **n8n workflow**,
I want to call `POST /v1/audio/speech` with a bearer token and receive cloned-voice audio,
So that customers hear natural voice responses on WhatsApp/Telegram.

**Acceptance Criteria:**

**Given** a valid bearer token and valid request body `{"input": "Olá", "voice": "carlos", "response_format": "ogg"}`
**When** I send `POST /v1/audio/speech`
**Then** I receive a 200 response with `Content-Type: audio/ogg` and binary OGG audio

**Given** a missing or invalid Authorization header
**When** I send `POST /v1/audio/speech`
**Then** I receive a 401 JSON error with `type: "authentication_error"` and a hint about checking the API_KEY env var

**Given** a request with missing `input` field
**When** I send `POST /v1/audio/speech`
**Then** I receive a 400 JSON error with `type: "invalid_request_error"` and a hint showing the expected request format

**Given** no `voice` field in the request
**When** I send `POST /v1/audio/speech`
**Then** the service uses the DEFAULT_VOICE from configuration

**Given** the service has just started and models are still warming up
**When** I send `POST /v1/audio/speech`
**Then** I receive a 503 JSON error with `type: "service_unavailable"` and a hint to retry in N seconds

**Given** the FastAPI lifespan
**When** the application starts
**Then** it loads config, configures logging, discovers voices, loads KokoClone models, runs warm-up inference, and sets the ready flag
**And** each phase is logged when it starts (startup communication pattern)
**And** the final "ready" message includes the listen address

### Story 1.8: API & Health Tests

As a **developer**,
I want automated tests covering auth, validation, success paths, and health states,
So that regressions are caught before deployment.

**Acceptance Criteria:**

**Given** the test suite
**When** I run `uv run pytest`
**Then** all tests pass using mocked KokoClone (no real model loading)

**Given** conftest.py
**When** tests use the test client
**Then** it provides a FastAPI AsyncClient via httpx, mock settings, and temporary voice directory fixtures

**Given** test_api.py
**When** I review the test coverage
**Then** it tests: valid request returns audio, missing auth returns 401, malformed request returns 400, missing voice returns 404, service warming up returns 503

**Given** test_health.py
**When** I review the test coverage
**Then** it tests: healthy status returns 200 with all fields, warming_up status returns 503, voices array reflects discovered voices, health requires no authentication

## Epic 2: Container Packaging & Production Runtime

The operator can run CUMADRE as a Docker service with automatic model download/caching, configurable workers for concurrency, resource limits, and zero outbound network after first run.

### Story 2.1: Dockerfile & Entrypoint

As a **DevOps operator**,
I want a production-ready Docker image that builds the service with all dependencies,
So that I can run CUMADRE as a container without installing Python or system packages on the host.

**Acceptance Criteria:**

**Given** the Dockerfile
**When** I run `docker compose build`
**Then** it builds a single-stage image from python:3.12-slim with espeak-ng, ffmpeg, and libsndfile1-dev installed as system packages
**And** Python dependencies are installed via `uv sync --frozen` from the committed uv.lock

**Given** the entrypoint.sh script
**When** the container starts
**Then** it launches uvicorn with the number of workers from the WORKERS env var (default 1) and the port from PORT env var (default 8000)

**Given** the built Docker image
**When** the container starts for the first time (no cached models)
**Then** KokoClone automatically downloads models from HuggingFace (~1 GB) and stores them in the /models directory

**Given** models were previously downloaded
**When** the container restarts or is rebuilt
**Then** models are loaded from the cached /models directory with zero network access required

### Story 2.2: Docker Compose & Production Configuration

As a **DevOps operator**,
I want a compose.yaml that defines the complete production runtime,
So that `docker compose up` starts a properly configured, resource-limited service.

**Acceptance Criteria:**

**Given** compose.yaml
**When** I run `docker compose up`
**Then** the tts-service starts with two named volumes mounted: `cumadre-voices:/voices:ro` and `cumadre-models:/models:rw`

**Given** compose.yaml resource limits
**When** the container is running
**Then** it is constrained to cpus: 4 and memory: 6G

**Given** compose.yaml restart policy
**When** the container crashes or the host reboots
**Then** Docker automatically restarts it (`restart: unless-stopped`)

**Given** compose.yaml health check
**When** the container starts
**Then** Docker health check polls `GET /health` with a start_period that accommodates model download and warm-up (120s)
**And** the container is marked healthy only when the health endpoint returns 200

**Given** WORKERS=2 in the environment
**When** the container starts
**Then** uvicorn launches 2 independent worker processes handling concurrent requests

**Given** the container is running with cached models
**When** I inspect outbound network traffic
**Then** zero outbound connections are made — all operation is local

## Epic 3: Deployment & Lifecycle Operations

The operator can manage CUMADRE's full lifecycle on a remote VPS with single Ansible commands — bootstrap from scratch, update safely, check health diagnostics, decommission completely, and auto-restart daily for memory leak mitigation.

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
**Then** it installs Docker (using `become: true` for apt tasks only), clones the repo to ~/cumadre, copies voice files, builds the container, starts the service, and waits for healthy status

**Given** the bootstrap playbook
**When** I inspect the task names
**Then** every task follows the `[Component] Action description` pattern (e.g., `[Docker] Install Docker Engine`, `[TTS] Build service container`, `[Health] Verify endpoint responds`)

**Given** the bootstrap playbook completes successfully
**When** I read the final task output
**Then** it is a `[Summary]` task reporting: service status, loaded voice, endpoint URL, and a copy-paste-ready test curl command

**Given** the bootstrap playbook
**When** it configures the daily restart cron
**Then** it creates a user-level crontab entry (not system cron) that runs `docker compose restart` daily

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
**Then** it pulls the latest repo, rebuilds the Docker image, and restarts the container
**And** runs entirely unprivileged (no `become: true`)

**Given** the update playbook completes
**When** I check the service
**Then** voice files in cumadre-voices volume are intact, model cache in cumadre-models volume is intact, and the API_KEY is unchanged

**Given** the update playbook completes
**When** I read the final `[Summary]` task
**Then** it confirms service health status, data preservation, and loaded voices

### Story 3.3: Health & Cleanup Playbooks

As a **DevOps operator**,
I want to diagnose service issues and fully decommission CUMADRE when needed,
So that I can troubleshoot at 2 AM and leave zero artifacts when retiring the service.

**Acceptance Criteria:**

**Given** a running CUMADRE deployment
**When** I run `ansible-playbook playbooks/health.yml -i inventory/production.yml`
**Then** it checks container state, queries the health endpoint, reports memory usage, loaded voices, uptime, and disk consumption
**And** runs entirely unprivileged

**Given** the health playbook detects high memory (> 3.5 GB)
**When** I read the output
**Then** it warns about memory pressure and suggests restarting the container and verifying the daily restart cron

**Given** the health playbook finds the container not running
**When** I read the output
**Then** it reports the container state and suggests checking `docker compose logs` and restarting

**Given** a CUMADRE deployment I want to remove
**When** I run `ansible-playbook playbooks/cleanup.yml -i inventory/production.yml`
**Then** it stops containers, removes images, volumes, the ~/cumadre directory, and the daily restart crontab entry
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

**Given** any quality check fails
**When** I view the CI run
**Then** the failing step is clearly identified with actionable output

**Given** all checks pass
**When** the CI run completes
**Then** the pipeline reports success and the PR is safe to merge

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
**Then** they cover: API reference (endpoint, request/response, error codes), deployment guide (bootstrap, update, cleanup, health), configuration reference (4-column table: variable, default, description, example), and troubleshooting (common issues with resolution steps)

**Given** any code example in the documentation
**When** I copy and paste it
**Then** it works with only the expected substitutions (API key, VPS IP) clearly indicated
**And** error examples are included alongside success examples
