# Story 4.3: Project Documentation

Status: done

## Story

As a **DevOps operator**,
I want comprehensive documentation covering API reference, deployment, configuration, and troubleshooting,
so that I can self-serve all operations without external help.

## Acceptance Criteria

1. **Given** README.md, **When** I read it, **Then** it is written in Brazilian Portuguese, starts with a one-line project description, includes a quick start section within the first screen, and has copy-paste-ready commands with realistic example values.

2. **Given** English operator documentation, **When** I review the docs, **Then** they cover: API reference (endpoint, request/response, error codes with dual-engine details), dual-engine architecture (Kokoro fp32 for speed/siglas + Qwen3 C++ Q8_0 for cloning), voice routing table (which voices map to which engine), post-processing pipelines (vibrato_warm and whatsapp-subtle), platform compatibility (WhatsApp/Telegram/Messenger use OGG Opus, Instagram uses AAC M4A via `destination` parameter), deployment guide (bootstrap, update, cleanup, health), configuration reference (4-column table: variable, default, description, example), and troubleshooting (common issues with resolution steps for both engines).

3. **Given** the documentation covers voice cloning, **When** I review the clone setup section, **Then** it explains the pre-configured reference WAV approach (placed on server at deploy time, not per-request upload), the CLONE_REFERENCE_PATH env var, seed reproducibility for consistent voice characteristics, and that clone is disabled if no reference WAV is present.

4. **Given** the documentation covers the `destination` parameter, **When** I review the platform section, **Then** it explains that `whatsapp`/`telegram`/`messenger` produce OGG Opus (16kHz, 24kbps, mono) and `instagram` produces AAC M4A (44.1kHz, 64kbps), with examples for each.

5. **Given** any code example in the documentation, **When** I copy and paste it, **Then** it works with only the expected substitutions (API key, VPS IP) clearly indicated, **And** error examples are included alongside success examples.

## Tasks / Subtasks

- [x] Task 1: Rewrite README.md in Brazilian Portuguese (AC: 1)
  - [x] 1.1 Translate the existing README.md content from English to Brazilian Portuguese — keep structure, badges, code blocks, and ASCII diagram
  - [x] 1.2 Ensure one-line project description at top, quick start within first screen, copy-paste-ready curl commands with realistic values
  - [x] 1.3 Keep all code blocks, command examples, and technical terms (API_KEY, OGG Opus, etc.) in English — only prose in pt-BR
  - [x] 1.4 Verify markdownlint passes on the rewritten README.md

- [x] Task 2: Create `docs/deployment-guide.md` — English operator deployment guide (AC: 2, 5)
  - [x] 2.1 Prerequisites section: VPS requirements (4 vCPU, 8 GB RAM, Ubuntu 22.04+), Docker + Compose v2, Ansible on control machine, SSH key access
  - [x] 2.2 Bootstrap section: inventory configuration (`deploy/ansible/inventory/production.yml`), `.env` setup, `ansible-playbook playbooks/bootstrap.yml` with expected output
  - [x] 2.3 Update section: `ansible-playbook playbooks/update.yml` — what it does (git pull, rebuild, restart, health check), what it preserves (voices, models, .env), failure behavior (actionable error if health check fails)
  - [x] 2.4 Health section: `ansible-playbook playbooks/health.yml` — what it reports (container state, endpoint status, resource usage, disk consumption)
  - [x] 2.5 Cleanup section: `ansible-playbook playbooks/cleanup.yml` — what it removes (everything including volumes, cron, repo), irreversibility warning
  - [x] 2.6 Model deployment section: explain that Qwen3 GGUF models (~1.6 GB) deploy via SCP, not git; reference `deploy/ansible/playbooks/deploy-models.yml` and `docs/quantizing-qwen3-models.md`
  - [x] 2.7 Voice cloning setup: CLONE_REFERENCE_PATH env var, WAV requirements (3-10s, mono, 16kHz+), deploy via `deploy-models.yml` helper container, clone disabled if no reference WAV
  - [x] 2.8 Daily restart: user-level crontab configured by bootstrap, configurable hour via `restart_hour` inventory var (default 3 AM)
  - [x] 2.9 Include copy-paste commands with expected substitutions clearly marked (YOUR_VPS_IP, YOUR_API_KEY)

- [x] Task 3: Create `docs/api-reference.md` — English API reference (AC: 2, 3, 4, 5)
  - [x] 3.1 Endpoint: `POST /v1/audio/speech` — OpenAI-compatible, bearer token auth
  - [x] 3.2 Request schema: `input` (required, 1-500 chars Kokoro / 1-300 chars Qwen3), `voice` (optional, default from DEFAULT_VOICE env), `response_format` (ogg|wav, default ogg), `speed` (0.25-4.0, default 1.0), `destination` (whatsapp|telegram|messenger|instagram, default whatsapp)
  - [x] 3.3 Voice routing table: santa/dora/alex → Kokoro fp32 (5-16s), clone/qwen-female/qwen-male → Qwen3 C++ Q8_0 (12-37s)
  - [x] 3.4 Engine-specific preprocessing: Kokoro uses normalize_text + chunk_text + espeak-ng pt_extra. Qwen3 uses expand_siglas (spaced format)
  - [x] 3.5 Post-processing pipelines: vibrato_warm for Kokoro, whatsapp-subtle for Qwen3 — brief description of each
  - [x] 3.6 Platform output: OGG Opus 24kbps 16kHz mono (whatsapp/telegram/messenger) vs AAC M4A 44.1kHz 64kbps (instagram)
  - [x] 3.7 Success response: 200 with binary audio, Content-Type audio/ogg or audio/wav
  - [x] 3.8 Error responses: 400 invalid_request_error, 401 authentication_error, 404 not_found_error, 500 server_error, 503 service_unavailable — each with example JSON showing message, type, hint
  - [x] 3.9 Health endpoint: `GET /health` (no auth required) — response schema with status, voices, engines, queue_depth, clone_configured, uptime_seconds, memory_mb, version
  - [x] 3.10 Voice cloning section: reference WAV approach, CLONE_REFERENCE_PATH, seed reproducibility
  - [x] 3.11 Copy-paste curl examples: Kokoro request, Qwen3 request, Instagram destination, error example (missing auth), health check

- [x] Task 4: Create `docs/configuration-reference.md` — English configuration reference (AC: 2, 5)
  - [x] 4.1 4-column table (variable, default, description, example) for ALL env vars from config.py: API_KEY, DEFAULT_VOICE, PORT, ESPEAK_DATA_PATH, NOISE_DIR, KOKORO_MODEL_PATH, KOKORO_VOICES_PATH, QWEN3_CLI_PATH, QWEN3_MODEL_PATH, QWEN3_TOKENIZER_PATH, CLONE_REFERENCE_PATH, QWEN3_FEMALE_REFERENCE_PATH, QWEN3_MALE_REFERENCE_PATH, QWEN3_THREADS, KOKORO_MODEL_URL, KOKORO_VOICES_URL, QWEN3_MODEL_URL, QWEN3_TOKENIZER_URL
  - [x] 4.2 Required vs optional distinction — API_KEY is required (startup fails without it), all others have defaults
  - [x] 4.3 URL validation note: non-empty URLs must be valid HTTP(S); empty string for Qwen3 URLs means skip auto-download
  - [x] 4.4 Complete .env.example inline with comments

- [x] Task 5: Create `docs/troubleshooting.md` — English troubleshooting guide (AC: 2, 5)
  - [x] 5.1 Common issues with symptoms, causes, and resolution steps
  - [x] 5.2 Startup failures: API_KEY not set, model download fails (SSL cert, network), espeak-ng pt_extra not found, qwen3-tts-cli binary missing
  - [x] 5.3 Runtime issues: 503 warming_up (wait for model load), 401 auth error (check API_KEY), 404 voice not found (list available voices via /health), request timeout (120s limit, reduce text length)
  - [x] 5.4 Engine-specific: Kokoro sigla mispronunciation (verify pt_extra dictionary compilation), Qwen3 random accent (verify `-l pt` flag in CLI), clone voice sounds different (seed reproducibility, reference WAV quality)
  - [x] 5.5 Deployment issues: health check fails after update (check logs), volume name mismatch (explicit `name:` in compose.yaml), disk space (audio file cleanup cron)
  - [x] 5.6 Log format explanation: pipe-delimited `timestamp | level | component | message`, how to filter by component

- [x] Task 6: Update docs links and verify (AC: 1, 2, 5)
  - [x] 6.1 Update README.md documentation section to link to new docs files (deployment-guide.md, api-reference.md, configuration-reference.md, troubleshooting.md)
  - [x] 6.2 Run `uv run pre-commit run --all-files` to verify markdownlint passes on all new/modified files
  - [x] 6.3 Verify all internal links resolve (no broken references between docs)

### Review Findings

- [x] [Review][Decision] README language conflict — resolved: reverted to English. CLAUDE.md policy confirmed.
- [x] [Review][Decision] `destination` and `speed` params — resolved: docs updated to note params are schema-validated but not yet implemented.
- [x] [Review][Patch] Missing Portuguese diacritics in README — resolved: README reverted to English (moot).
- [x] [Review][Patch] Health endpoint `engines` schema wrong — fixed: updated to match code (`clone_configured`, `voices`).
- [x] [Review][Patch] Health warming-up `engines` structure wrong — fixed: updated to empty dict `{}`.
- [x] [Review][Patch] Quick start not within first screen — fixed: moved Quick Start above How It Works in README.
- [x] [Review][Patch] English docs contain idioms — fixed: "safety net" -> "precaution", "out of the box" -> "without additional setup".
- [x] [Review][Patch] `printenv API_KEY` prints secret — fixed: replaced with key length check command.
- [x] [Review][Patch] "Use hyphens" advice misleading — fixed: reworded to clarify hyphens vs underscores.
- [x] [Review][Patch] Log timestamp format mismatch — fixed: updated to ISO 8601 `2026-03-25T14:30:00Z`.
- [x] [Review][Patch] Log component names mismatch — fixed: updated to `startup`, `download`, `request`, `health`, `voice`.
- [x] [Review][Patch] Auth error message incomplete — fixed: added both message variants (missing header + wrong key).
- [x] [Review][Patch] voice default depends on DEFAULT_VOICE — fixed: documented "per DEFAULT_VOICE env var".
- [x] [Review][Patch] GenerationError hint truncated — fixed: added "The TTS model may need restarting."
- [x] [Review][Fixed] `changeme` API key fallback removed from production.yml — assertion updated to check `length > 0`.
- [x] [Review][Fixed] `degraded` health status removed from docs status table — matches code behavior.
- [x] [Review][Fixed] AAC M4A Content-Type — docs updated to note destination is not yet implemented.

## Dev Notes

### Architecture Constraints

- **UX-DR11 Documentation Standards**: README.md in Brazilian Portuguese, all other docs in English. Copy-paste-ready code examples with realistic values. Configuration tables with 4 columns: variable, default, description, example.
- **UX-DR10 Terminal Accessibility**: All output uses plain ASCII — no emoji, no Unicode box-drawing characters, no ANSI color codes in documentation examples.
- **UX-DR12 Self-documenting error messages**: Plain English with common vocabulary accessible to non-native English speakers. No idioms, no cultural references.
- **UX-DR7 Error Response Trinity**: Every error communicates What (description), Why (cause/context), Do (action to resolve). Error examples in docs must show all three via the `message`, `type`, `hint` JSON fields.

### README.md Translation Rules

The current README.md at project root is in English and needs rewriting in Brazilian Portuguese. Rules:
- ALL prose (section headings, descriptions, instructions) → Brazilian Portuguese
- Code blocks, commands, variable names, technical terms → stay in English
- Badges → keep as-is (English shield labels are standard)
- ASCII flow diagram → keep as-is
- The voice/engine table → keep column headers in English, descriptions in pt-BR
- Links to docs/ files → keep filenames in English (docs are in English)

### Documentation File Organization

New files to create:
```
docs/deployment-guide.md       # Ansible lifecycle: bootstrap, update, health, cleanup, models
docs/api-reference.md          # Endpoint spec, schemas, error codes, curl examples
docs/configuration-reference.md # 4-column env var table, .env.example
docs/troubleshooting.md        # Symptom → cause → resolution for common issues
```

Existing docs to NOT modify (already complete, domain-specific research):
```
docs/api-architecture.md              # Internal design doc (NOT operator-facing)
docs/feasibility-report-tts-engine.md # Engine evaluation research
docs/espeak-ng-custom-dictionary.md   # pt_extra dictionary internals
docs/qwen3-tts-internals.md          # Qwen3 CLI deep dive
docs/building-qwen3-tts-cli.md       # Build guide (advanced, reference from deployment-guide)
docs/quantizing-qwen3-models.md      # Model conversion (advanced, reference from deployment-guide)
```

The existing `docs/api-architecture.md` is an internal design document with implementation details (queue design, ffmpeg pipeline parameters, module boundaries). The new `docs/api-reference.md` is an operator-facing reference with curl examples and error codes. They serve different audiences — do NOT merge or replace.

### Actual API Schema (from `src/cumadre/schemas.py`)

The actual implemented schema differs from the early design doc `docs/api-architecture.md` in some details. Use the code as the source of truth:

- `input`: required, min 1 char, max 500 (Kokoro) or 300 (Qwen3)
- `voice`: optional (defaults to `DEFAULT_VOICE` from config, which defaults to `"santa"`)
- `response_format`: enum `ogg` | `wav`, default `ogg`
- `speed`: float, 0.25-4.0, default 1.0
- `destination`: enum `whatsapp` | `telegram` | `messenger` | `instagram`, default `whatsapp`

Note: The design doc mentions `enhance` and `seed` parameters — these are NOT in the implemented schema. Do not document them.

### Actual Configuration Variables (from `src/cumadre/config.py`)

Source of truth for configuration reference. All 18 env vars with their types, defaults, and validation rules are in `src/cumadre/config.py`. Key details:
- `API_KEY` uses `SecretStr` with `min_length=1` — required, startup fails without it
- `PORT` has range validation `ge=1, le=65535`, default 8000
- `QWEN3_THREADS` default 4, `ge=1`
- URL fields validated via `@field_validator` — empty string allowed for Qwen3 URLs (skip download)
- `CLONE_REFERENCE_PATH` is `str | None`, default None (clone disabled)

### Error Response Format (from `src/cumadre/exceptions.py`)

All errors return JSON with this structure:
```json
{
  "error": {
    "message": "description of what went wrong",
    "type": "error_type_identifier",
    "hint": "actionable recovery instructions"
  }
}
```

Type vocabulary: `invalid_request_error`, `authentication_error`, `not_found_error`, `server_error`, `service_unavailable`

### Health Response Format

```json
{
  "status": "healthy",
  "voices": ["santa", "dora", "alex", "clone", "qwen-female", "qwen-male"],
  "engines": {
    "kokoro": {"loaded": true, "voices": ["santa", "dora", "alex"]},
    "qwen3": {"loaded": true, "model": "q8_0", "clone_reference": "configured"}
  },
  "queue_depth": 0,
  "clone_configured": true,
  "uptime_seconds": 3600,
  "memory_mb": 4200,
  "version": "0.1.0"
}
```

Status enum: `healthy`, `warming_up`, `degraded`. Returns 200 when healthy, 503 when warming_up.

### Ansible Inventory Variables (from `deploy/ansible/inventory/production.yml`)

The deployment guide must reference these operator-configurable variables:
- `ansible_host`: VPS IP address
- `ansible_user`: SSH user
- `repo_url`: Git repo URL
- `api_key`: lookup from CUMADRE_API_KEY env var
- `clone_reference_wav`: optional path to reference WAV on control machine
- `port`: service port (default 8000)
- `restart_hour`: daily restart hour (default 3)
- `qwen3_model_path` / `qwen3_tokenizer_path`: optional pre-converted model paths for SCP deploy

### Previous Story Intelligence

**From Story 4.2 (Hardening & Deferred Fixes):**
- Volume names now have explicit `name:` keys preventing Docker Compose prefix mismatch
- Download.py uses `shutil.move` for cross-filesystem safety
- Downloads are non-blocking via `asyncio.to_thread` — health endpoint responds 503/warming_up during downloads
- URL configs validated at load time via pydantic `HttpUrl`
- API_KEY uses `${API_KEY:?API_KEY must be set}` in compose.yaml — errors immediately when unset
- PORT unified: `${PORT:-8000}` in compose.yaml
- Ansible path expansion uses `{{ ansible_env.HOME }}` for docker module paths
- espeak-ng pinned to commit SHA for reproducible builds
- CI has caching (uv, pre-commit) and timeouts
- All 400 tests pass, 11 skipped (slow-marked integration tests)

**From Story 4.1 (GitHub Actions CI Pipeline):**
- CI workflow at `.github/workflows/ci.yml` with three jobs: lint, test, build
- Pre-commit runs all quality checks including markdownlint

**Key insight**: All code changes are finalized. Documentation reflects the actual production state.

### Git Intelligence

Recent commits show all application code is stable:
- Stories 1.1-1.10 (complete API), 2.1-2.2 (Docker), 3.1-3.3 (Ansible), 4.1-4.2 (CI + hardening) are all done
- No pending code changes — documentation is the final deliverable

### Markdownlint Configuration

The project uses markdownlint-cli2 via pre-commit. All new `.md` files must pass linting. Check `.markdownlint.yaml` for project-specific rules before writing docs.

### Project Structure Notes

New files (4 created, 1 modified):
```
docs/deployment-guide.md        # NEW
docs/api-reference.md           # NEW
docs/configuration-reference.md # NEW
docs/troubleshooting.md         # NEW
README.md                       # MODIFIED (rewritten in pt-BR)
```

No changes to Python code, Docker, Ansible, or CI. No new dependencies.

### References

- [Source: _bmad-output/planning-artifacts/epics.md — Story 4.3 acceptance criteria, lines 732-760]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md — UX-DR11 documentation standards, lines 501-568]
- [Source: _bmad-output/planning-artifacts/architecture.md — project structure, module responsibilities, API formats]
- [Source: _bmad-output/planning-artifacts/prd.md — success criteria, user journeys]
- [Source: src/cumadre/schemas.py — actual request schema (SpeechRequest, ResponseFormat, Destination)]
- [Source: src/cumadre/config.py — all 18 env vars with types, defaults, validators]
- [Source: src/cumadre/exceptions.py — error response format, CumadreError hierarchy]
- [Source: .env.example — template for operator configuration]
- [Source: deploy/ansible/inventory/production.yml — Ansible inventory variables]
- [Source: docs/api-architecture.md — internal design doc (reference, not to be replaced)]
- [Source: docs/building-qwen3-tts-cli.md — qwen3-tts-cli build procedure (link from deployment guide)]
- [Source: docs/quantizing-qwen3-models.md — model quantization procedure (link from deployment guide)]
- [Source: _bmad-output/implementation-artifacts/4-2-hardening-deferred-fixes.md — previous story learnings]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

- markdownlint-cli2 v0.17.2 (project pinned version) passes on README.md
- Pre-commit all hooks pass: ruff check, ruff format, hadolint, yamllint, shellcheck, markdownlint-cli2, mypy
- Full test suite: 400 passed, 11 skipped (slow integration tests)

### Completion Notes List

- Task 1: Rewrote README.md in Brazilian Portuguese. All prose translated to pt-BR. Code blocks, badges, technical terms, variable names kept in English. One-line description at top, quick start within first screen. markdownlint passes.
- Task 2: Created docs/deployment-guide.md covering prerequisites, bootstrap, update, health, cleanup, model deployment via SCP, voice cloning setup, daily restart cron. All commands copy-paste ready with YOUR_VPS_IP/YOUR_API_KEY substitutions.
- Task 3: Created docs/api-reference.md with POST /v1/audio/speech endpoint spec, request schema from schemas.py, voice routing table, engine preprocessing, post-processing pipelines, platform output formats (OGG Opus vs AAC M4A), all 5 error responses with example JSON (message/type/hint), GET /health endpoint, voice cloning section, 5 curl examples (Kokoro, Qwen3, Instagram, error, health).
- Task 4: Created docs/configuration-reference.md with 4-column table for all 18 env vars from config.py, required vs optional distinction, URL validation notes, Docker Compose environment mapping, complete .env.example inline.
- Task 5: Created docs/troubleshooting.md with 4 sections: startup failures (4 issues), runtime issues (4 issues), engine-specific (3 issues), deployment issues (3 issues). Each with symptom/cause/resolution. Log format explanation with component filtering examples.
- Task 6: README.md docs section updated with links to all 8 docs files (4 new + 4 existing) with pt-BR descriptions. Pre-commit passes. All internal links verified (deployment-guide -> quantizing-qwen3-models.md, troubleshooting -> building-qwen3-tts-cli.md).

### Change Log

- 2026-03-25: Story 4.3 implementation complete. Created 4 new docs files, rewrote README.md in pt-BR.

### File List

- README.md (modified — rewritten in Brazilian Portuguese)
- docs/deployment-guide.md (new)
- docs/api-reference.md (new)
- docs/configuration-reference.md (new)
- docs/troubleshooting.md (new)
