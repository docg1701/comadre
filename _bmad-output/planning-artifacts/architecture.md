---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
lastStep: 8
status: 'complete'
completedAt: '2026-03-21'
inputDocuments:
  - _bmad-output/planning-artifacts/product-brief-comadre-2026-03-21.md
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/ux-design-specification.md
workflowType: 'architecture'
project_name: 'comadre'
user_name: 'Galvani'
date: '2026-03-21'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**

28 functional requirements across 7 categories:

| Category | FRs | Architectural Implication |
|---|---|---|
| Audio Generation (FR1-FR5b) | Text → engine routing → TTS → post-processing → audio output | Dual-engine pipeline: Kokoro fp32 (built-in voices, espeak-ng pt_extra) + Qwen3-TTS C++ Q8_0 (voice cloning), engine-specific post-processing |
| API Interface (FR6-FR10) | OpenAI-compatible endpoint, bearer auth, error codes, 503 warm-up | FastAPI with middleware auth, structured error handlers, startup readiness gate |
| Service Health & Monitoring (FR11-FR13) | Health endpoint with status, voices, uptime | Dedicated health route aggregating runtime state from multiple sources |
| Voice Management (FR14-FR16) | Volume-mounted WAV files, discovery at startup, configurable default | Voice discovery module scanning /voices/ directory, validation at boot |
| Container Lifecycle (FR17-FR21) | Auto model download, persistent cache, dual warm-up, single FIFO queue | Docker volumes for models/voices/noise, single process with asyncio.Lock queue, startup dual-engine warm-up, horizontal scaling via Caddy |
| Deployment & Operations (FR22-FR26) | Four Ansible playbooks, daily restart cron | Ansible roles for bootstrap/update/cleanup/health, host-level cron for memory leak |
| Security & Isolation (FR27-FR28) | Zero outbound network post-deploy, Docker resource limits | Network-isolated container, CPU/memory constraints in docker-compose.yml |

**Non-Functional Requirements:**

| NFR | Target | Architectural Driver |
|---|---|---|
| Response latency (Kokoro) | Typical 5-16s per request | CPU-bound inference, RTF 1.1x + post-processing ~2s |
| Response latency (Qwen3) | Typical 12-37s per request | CPU-bound inference, RTF 2.5x + post-processing ~2s |
| Cold start | < 120s (excl. model download) | Dual-engine model loading + warm-up on startup |
| Memory total | < 6 GB steady state | Both engines loaded in single instance |
| Memory stability | Stable over 24h | Kokoro leak fixed in phonemizer-fork >=3.3.2; daily restart as safety net |
| Throughput (Kokoro) | ~10 req/min per instance | Sequential processing via asyncio.Lock |
| Throughput (Qwen3) | ~4.8 req/min per instance | Sequential processing via asyncio.Lock |
| Availability | 99%+ (excl. scheduled restarts) | Docker restart policy + health check + cron restart |
| Data preservation | 100% on updates | Docker volumes for voices and model cache, not baked into image |

**Scale & Complexity:**

- Primary domain: API backend
- Complexity level: Low
- Estimated architectural components: 5 (FastAPI app, Docker packaging, Ansible playbooks, voice management, health/monitoring)

### Technical Constraints & Dependencies

| Constraint | Source | Impact |
|---|---|---|
| Dual-engine architecture | Feasibility study (10+ configs, 400+ samples) | Kokoro fp32 for speed + siglas, Qwen3-TTS C++ Q8_0 for cloning. Two preprocessing pipelines, two post-processing chains |
| Kokoro uses espeak-ng via misaki | misaki has no native Portuguese G2P | Must build espeak-ng from source + compile custom pt_extra dictionary. Copy data to BOTH system path and misaki bundled path |
| Qwen3-TTS is a C++ binary (qwen3-tts-cli) | Upstream qwen3-tts.cpp project | Subprocess calls, not Python API. Custom seed patch for deterministic generation |
| Qwen3 sigla pronunciation | 7/10 quality with spaced format | expand_siglas() preprocessing required; seed library per sigla pattern for consistency |
| ffmpeg required for post-processing + OGG | Post-processing pipelines (vibrato, EQ, compression, noise) + OGG Opus encoding | Must be installed in Docker image (system package) |
| Model download on first run | Model distribution | Kokoro ONNX ~325 MB + voices ~27 MB (HuggingFace), Qwen3 GGUF ~1.3 GB + tokenizer ~341 MB. Cached in Docker volume |
| uv for Python dependency management | Project policy | Dockerfile uses uv, not pip |
| Single consumer (n8n) on local network | Deployment context | No TLS, no rate limiting, no multi-tenancy, plain HTTP. n8n-side failover pattern |
| CPU-only inference | Hardware target (4 vCPU / 8 GB RAM commodity VPS) | No CUDA/GPU dependencies; 4-core thread scaling is sweet spot for Qwen3 |
| Sequential request processing | Single FIFO queue (asyncio.Lock) | No concurrent generation — horizontal scaling via Caddy load balancer |

### Cross-Cutting Concerns Identified

1. **Dual-Engine Routing** — Voice name determines engine selection. Must be consistent across request processing, health reporting, voice listing, and error messages. Engine-specific preprocessing and post-processing must be dispatched correctly.

2. **Engine-Specific Post-Processing** — Two distinct ffmpeg pipelines: vibrato_warm (Kokoro: vibrato, bass boost, exciter, compressor, echo, noise) and whatsapp-subtle (Qwen3: EQ, compressor, atempo 1.15x, noise). Noise calibration differs per engine (Kokoro needs 3x more noise). Both output OGG Opus 24kbps 16kHz mono.

3. **Model & Asset Persistence** — Docker volumes must survive container rebuilds, updates, and restarts. Affects Dockerfile design (cache in volume, not layer), compose.yaml (volume mounts), Ansible update playbook (must not delete volumes). Assets include: Kokoro ONNX model + voices, Qwen3 GGUF models, noise WAV files, clone reference WAV.

4. **Startup Readiness** — Dual-engine model loading + voice discovery + warm-up creates a multi-second startup window. Health endpoint must return 503 during this window. Docker health check must accommodate it. Ansible bootstrap must wait for it.

5. **Error Consistency** — The OpenAI-compatible error format with `hint` field must be uniform across all error paths (auth, validation, voice not found, engine failure, post-processing failure, warm-up). Centralized exception handling is required to prevent inconsistency.

6. **Structured Logging** — Pipe-delimited format with component tags must be configured application-wide. All modules (startup, request handling, voice discovery, health, engine routing) log through the same formatter.

7. **pt-BR Pronunciation Quality** — Kokoro path: espeak-ng with custom pt_extra dictionary (67 entries, 34/34 verified). Qwen3 path: THINK mode with `-l pt`, expand_siglas() spaced format, seed reproducibility for consistency. Each engine has different pronunciation strengths and preprocessing requirements.

8. **Queue Management** — Single FIFO queue with asyncio.Lock. Health endpoint reports queue depth. n8n-side failover pattern handles overload (alerting, text fallback, retry). No Redis, no Celery — minimal infrastructure.

## Starter Template Evaluation

### Primary Technology Domain

API backend (Python/FastAPI) with Docker packaging and Ansible deployment. No starter scaffolding tool applies — this is a from-scratch project with a well-defined, minimal scope.

### Starter Options Considered

| Option | Verdict | Rationale |
|---|---|---|
| `uv init --package` | **Selected** | Creates src layout with pyproject.toml — the only scaffolding needed |
| FastAPI project generators (tiangolo/full-stack-fastapi-template) | Rejected | Massively over-engineered for a single-endpoint service. Includes SQLAlchemy, Alembic, Celery, React frontend |
| cookiecutter-fastapi templates | Rejected | Add opinions and boilerplate that don't match this project's simplicity |
| Manual from scratch | Rejected | `uv init --package` does the minimal setup correctly |

### Selected Starter: `uv init --package`

**Rationale:** COMADRE is ~80-150 lines of core code. Any template beyond `uv init` adds more to delete than to keep. The src layout, pyproject.toml, and .python-version are the only scaffolding needed.

**Initialization Command:**

```bash
uv init --package comadre
```

### Engine Integration Discovery

After evaluating 10+ engine configurations with 400+ audio samples (documented in `docs/feasibility-report-tts-engine.md`), a dual-engine architecture was selected.

#### Engine Evaluation Results

| Engine | Diction | Siglas | RTF (CPU) | Verdict |
|---|---|---|---|---|
| **Kokoro fp32 pm_santa** | 9/10 | 10/10 (pt_extra) | 1.1x | **SELECTED — FAST PATH** |
| **Qwen3 C++ Q8_0** | 9/10 | 7/10 (spaced) | 2.4-3.6x | **SELECTED — CLONE PATH** |
| Kokoro pf_dora | 8/10 | 10/10 | 1.1x | Alt female voice |
| Kokoro pm_alex | 8/10 | 10/10 | 1.1x | Alt male voice |
| KokoClone (Kokoro + Kanade) | 1/10 | N/A | 1.5x | **REJECTED** — Kanade voice conversion produces unusable diction on CPU |
| Chatterbox ONNX FP32 | 9/10 | 2/10 | 1.8x | **REJECTED** — sigla pronunciation fundamentally broken (character-level tokenizer, no phoneme control) |
| Qwen3 PyTorch | 9/10 | 7/10 | 6.5x | Too slow for CPU |

#### Kokoro fp32 (Fast Path)

| Aspect | Detail |
|---|---|
| Installation | `kokoro-onnx` from PyPI + `misaki` + `espeakng-loader` |
| Core API | `kokoro_onnx.Kokoro(model_path)` → `kokoro.create(text, voice, lang='pt-br')` |
| Voices | Built-in: pm_santa (M, default), pf_dora (F), pm_alex (M) — no reference WAV needed |
| Models | `kokoro-v1.0.onnx` (325 MB) + `voices-v1.0.bin` (27 MB) from HuggingFace |
| Sigla pronunciation | **10/10** via custom espeak-ng pt_extra dictionary (67 entries, 34/34 verified) |
| Preprocessing | `normalize_text()` (numbers, currency, dates, times) → `chunk_text()` (max 200 tokens, sentence boundaries). Siglas handled natively by espeak-ng — no text preprocessing needed |
| Post-processing | vibrato_warm: vibrato(4.5Hz, 6%) → highpass(80Hz) → bass(+3dB) → EQ → exciter(4.5kHz) → softclip → compressor(4:1) → lowpass(8kHz) → echo(40ms) → loudnorm(-18 LUFS) → noise(room=0.45, hiss=0.24) → loudnorm(-17 LUFS) → OGG Opus |
| Memory leak | **Fixed** in phonemizer-fork >=3.3.2. Daily restart as safety net |
| Char limit | 500 chars max per request |
| Sample rate | 24kHz output |

**CRITICAL espeak-ng pt_extra setup:** The `misaki` library bundles its own `pt_dict` and **IGNORES `ESPEAK_DATA_PATH`**. Must copy ALL compiled data files (pt_dict + phondata + phonindex + phontab) to BOTH system path AND `espeakng_loader` bundled path inside the venv.

#### Qwen3-TTS C++ Q8_0 (Clone Path)

| Aspect | Detail |
|---|---|
| Installation | Pre-built `qwen3-tts-cli` binary (from qwen3-tts.cpp, ~600 KB) with custom seed patch |
| Core API | Subprocess: `qwen3-tts-cli -m model.gguf -t tokenizer.gguf -l pt --seed N --temperature 0.7 -j 4 "text"` |
| Voice selection | **All Qwen3 voices use x-vector cloning** from reference WAVs. The 0.6B-Base model has no built-in voice presets — voice identity is determined entirely by the reference audio's speaker embedding. Bundled pt-BR references (female/male) ship in `voices/`, operator can add custom clone reference at deploy time |
| Models | `qwen3-tts-0.6b-q8_0.gguf` (1.3 GB) + `qwen3-tts-tokenizer-f16.gguf` (341 MB) |
| Sigla pronunciation | 7/10 with spaced format preprocessing (`C N P J`); word siglas (SUS, PIX, LOAS) kept as-is |
| Preprocessing | `expand_siglas()` converts spelled siglas to spaced format. Word acronyms kept intact |
| Post-processing | whatsapp-subtle: highpass(100Hz) → EQ → compressor(6:1) → lowpass(8kHz) → echo(40ms) → atempo(1.15x) → loudnorm(-18 LUFS) → noise(room=0.15, hiss=0.08) → loudnorm(-17 LUFS) → OGG Opus |
| THINK mode | **ALWAYS use `-l pt`** — activates reasoning tokens for Portuguese pronunciation. Without it: random accent, inconsistent siglas |
| Seed reproducibility | Custom C++ patch adds `--seed N` for deterministic generation. Same seed + same text = identical audio (MD5 match) |
| Thread scaling | 4 cores = sweet spot (measured). Beyond 4: diminishing returns (1.5% gain at 6 cores) |
| Char limit | 300 chars max per request |
| Q8_0 vs F16 | Q8_0: 9% faster, 28% less RAM, quality ≈ F16 — **recommended** |

#### Voice-to-Engine Routing (Fixed)

| Voice Name | Engine | Reference WAV | Description |
|---|---|---|---|
| `santa` | Kokoro fp32 | — (built-in pm_santa) | Male, default voice |
| `dora` | Kokoro fp32 | — (built-in pf_dora) | Female voice |
| `alex` | Kokoro fp32 | — (built-in pm_alex) | Male alt |
| `clone` | Qwen3 C++ Q8_0 | Operator-provided at deploy time | Custom voice cloning |
| `qwen-female` | Qwen3 C++ Q8_0 | `voices/female-reference.wav` (bundled) | Female voice via x-vector cloning from pt-BR reference |
| `qwen-male` | Qwen3 C++ Q8_0 | `voices/male-reference.wav` (bundled) | Male voice via x-vector cloning from pt-BR reference |

**Qwen3 voice mechanism:** The 0.6B-Base model uses x-vector speaker embeddings extracted from reference audio (`-r` flag). Without `-r`, it produces a fixed default voice (zero embedding). All three Qwen3 voices pass `-r` with different reference WAVs. The bundled references are sourced from [LibriVox - Coleção de Contos Brasileiros 001](https://librivox.org/colecao-librivox-de-contos-brasileiros-001/) (public domain): female = Leni (track 02), male = Lucas M. (track 04).

### pt-BR Pronunciation: Dual-Engine Approach

#### Kokoro Path — espeak-ng with custom pt_extra dictionary

The `misaki` G2P library (Kokoro's phonemizer) has **no native Portuguese module** — it falls back entirely to `espeak.EspeakG2P(language='pt-br')`. Quality is bounded by espeak-ng data quality.

**espeak-ng PR #2344** (merged 2026-03-20) delivered massive pt-BR improvements: +5,618 lines, 250+ corrections, 900+ abbreviations, 3,500+ words. The bundled `espeakng-loader` v1.52 data is over a year old and does NOT include these improvements.

**Custom pt_extra dictionary** (documented in `docs/espeak-ng-custom-dictionary.md`):
- 67 custom entries for Brazilian siglas
- Soletradas (spelled, `$abbrev` flag): CPF, CNPJ, RG, CNH, STF, STJ, TRT, CLT, FGTS, BPC... (53+ entries)
- Pronunciadas como palavra (custom phonemes): SUS, PIX, DETRAN, LOAS, CRAS, ANVISA, SAMU, ENEM... (14+ entries)
- **Verified 34/34 correct** in listening tests

**CRITICAL:** `misaki` bundles its own `pt_dict` and **IGNORES `ESPEAK_DATA_PATH`**. Must copy compiled data to BOTH:
1. System espeak-ng path (`/usr/local/share/espeak-ng-data/`)
2. `espeakng_loader` bundled path (`.venv/lib/.../espeakng_loader/espeak-ng-data/`)

**Text preprocessing for Kokoro:** `normalize_text()` (numbers, currency, dates, times via num2words) → `chunk_text()` (max 200 tokens, sentence boundaries). Siglas need NO text preprocessing — espeak-ng pt_extra handles them natively.

#### Qwen3 Path — THINK mode with expand_siglas

Qwen3-TTS uses a native BPE tokenizer with no espeak-ng dependency. Pronunciation quality depends on the THINK mode reasoning tokens.

**ALWAYS use `-l pt`** to activate THINK mode (Portuguese language ID 2071). Without it: random accent, inconsistent siglas, wrong intonation.

**Sigla preprocessing for Qwen3:** `expand_siglas()` converts spelled siglas to spaced format (`CNPJ` → `C N P J`). Word siglas (SUS, PIX, PIS, LOAS, CEP, DETRAN, ENEM, SAMU, ANVISA) are kept as-is. Result: 7/10 sigla quality — acceptable but inferior to Kokoro path.

**Seed reproducibility** (custom C++ patch, `docs/qwen3-tts-cpp-seed-patch.diff`): Same seed + same text = identical audio. Production strategy: build seed library per sigla pattern; use known-good seed for each request with siglas.

#### Alternative TTS engines evaluated and rejected

Full evaluation in `docs/feasibility-report-tts-engine.md`. Key rejections:

| Engine | Why Rejected |
|---|---|
| KokoClone (Kokoro + Kanade) | Kanade voice conversion: 1/10 diction on CPU |
| Chatterbox ONNX FP32 | Sigla pronunciation fundamentally broken (2/10); character-level tokenizer, no phoneme control, `[ipa]` token non-functional |
| XTTS v2 (Coqui) | CPU inference unusable (~250s/phrase) |
| Fish Speech S2 | Needs 12GB+ VRAM (GPU only) |
| F5-TTS pt-BR | CPU inference unusable (7+ min/phrase) |
| Qwen3-TTS PyTorch | Too slow for CPU (RTF 6.5x vs 2.5x with C++ Q8_0) |
| Qwen3-TTS 1.7B | OOM on 8 GB RAM |

### Project Structure

```
comadre/
├── src/
│   └── comadre/
│       ├── __init__.py
│       ├── main.py            # FastAPI app, startup lifecycle, health endpoint
│       ├── api.py             # POST /v1/audio/speech route
│       ├── schemas.py         # Pydantic request/response models
│       ├── service.py         # Dual-engine wrapper, audio generation + post-processing
│       ├── preprocessing.py   # pt-BR text normalization (numbers, currency, dates, chunking)
│       ├── config.py          # Settings via pydantic-settings
│       ├── exceptions.py      # Custom exceptions + error response builder
│       ├── health.py          # Health response assembler
│       ├── logging.py         # Structured logger configuration
│       └── voices.py          # Voice discovery module
├── tests/
│   ├── conftest.py
│   ├── test_api.py
│   └── test_health.py
├── deploy/
│   └── ansible/
│       ├── inventory/
│       │   └── production.yml
│       ├── playbooks/
│       │   ├── bootstrap.yml
│       │   ├── update.yml
│       │   ├── cleanup.yml
│       │   └── health.yml
│       └── ansible.cfg
├── scripts/
│   └── entrypoint.sh
├── voices/                    # Reference WAV files (tracked in git for bundled, volume-mounted for clone)
│   ├── female-reference.wav   # Bundled pt-BR female reference (public domain, LibriVox)
│   └── male-reference.wav     # Bundled pt-BR male reference (public domain, LibriVox)
├── Dockerfile
├── compose.yaml               # Docker Compose v2 standard filename
├── pyproject.toml
├── uv.lock
├── .python-version
├── .pre-commit-config.yaml
├── .hadolint.yaml
├── .yamllint.yaml
├── .ansible-lint
├── .markdownlint.yaml
├── .gitignore
├── CLAUDE.md
├── LICENSE
└── README.md
```

### Code Quality Tooling

| Format | Tool | Config Location |
|---|---|---|
| Python lint + format | ruff | pyproject.toml |
| Python type checking | mypy (strict + pydantic plugin) | pyproject.toml |
| Python tests | pytest + pytest-asyncio + httpx | pyproject.toml |
| Dockerfile | hadolint | .hadolint.yaml |
| YAML | yamllint | .yamllint.yaml |
| Ansible | ansible-lint (production profile) | .ansible-lint |
| Shell scripts | shellcheck | via pre-commit |
| Markdown | markdownlint-cli2 | .markdownlint.yaml |
| All of the above | pre-commit | .pre-commit-config.yaml |

### Dependency Groups (PEP 735)

```toml
[dependency-groups]
dev = [
    { include-group = "lint" },
    { include-group = "test" },
    { include-group = "type-check" },
]
lint = ["ruff>=0.9", "pre-commit>=4.0"]
test = ["pytest>=8.3", "pytest-asyncio>=1.0", "httpx>=0.28", "coverage>=7.6"]
type-check = ["mypy>=1.14"]
```

### Architectural Decisions Provided by Starter

| Decision | Choice | Rationale |
|---|---|---|
| Layout | `src/comadre/` | Import safety, prevents accidental local imports during testing |
| Build backend | hatchling | uv default, minimal config |
| Linter/formatter | ruff only | Replaces black + isort + flake8 in a single tool, 100x faster |
| Type checker | mypy --strict | Catches type errors before runtime; pydantic plugin essential for FastAPI |
| Compose filename | compose.yaml | Docker Compose v2 specification standard |
| Ansible location | deploy/ansible/ | Separates deployment from application code |
| Dev orchestration | pre-commit | Runs all linters consistently in dev and CI |

**Note:** Project initialization using `uv init --package` should be the first implementation story.

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D1 | Engine integration | Kokoro via kokoro-onnx (PyPI) + Qwen3 via qwen3-tts-cli binary (subprocess) | Kokoro for speed + siglas, Qwen3 for cloning. Binary subprocess avoids Python dependency conflicts |
| D2 | Model download strategy | Runtime + Docker volume cache | First start downloads from HuggingFace (Kokoro) and model repo (Qwen3). Cached in named volume |
| D3 | Concurrency model | Single FIFO queue with asyncio.Lock | Sequential processing, no shared state. Horizontal scaling via Caddy load balancer |
| D4 | Warm-up strategy | FastAPI lifespan + health endpoint gating | Lifespan warms up both engines; health returns 503 until ready; Docker health check accommodates |

**Important Decisions (Shape Architecture):**

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D5 | Docker build | Single-stage python:3.12-slim | espeak-ng from source + pt_extra compilation + qwen3-tts-cli binary in single stage |
| D6 | Configuration | pydantic-settings | Type-safe env var loading, validates API_KEY at startup, FastAPI ecosystem standard |
| D7 | Post-processing + encoding | ffmpeg subprocess pipelines | ffmpeg already a system dep. Two pipelines: vibrato_warm (Kokoro), whatsapp-subtle (Qwen3). Output: OGG Opus 24kbps 16kHz mono |
| D8 | CI/CD | GitHub Actions | pre-commit + pytest + docker build. Free, good uv support |
| D9 | Engine routing | Voice-name-based fixed routing | santa/dora/alex → Kokoro; clone/qwen-female/qwen-male → Qwen3. Simple, no dynamic routing logic |
| D10 | Failover | n8n-side failover pattern | n8n workflow handles retry, text fallback, alerting. Not in Caddy — allows workflow control |
| D11 | Seed reproducibility | Custom C++ patch for qwen3-tts-cli | `--seed N` parameter for deterministic Qwen3 generation. Seed library per sigla pattern |

**Deferred Decisions (Post-MVP):**

| Decision | Rationale for Deferral |
|---|---|
| Response caching | PRD: "measure demand first" — no evidence of repeated phrases yet |
| GPU acceleration | CPU-only for MVP target hardware; budget constraint is absolute |
| Prometheus metrics | Health endpoint sufficient for single-consumer service |
| Qwen3 seed library | Post-MVP: curate known-good seeds per sigla pattern for consistent pronunciation |

### Data Architecture

No database. No persistent data storage. Audio is generated and returned in the response — never persisted. The only stateful data:

| Data | Storage | Lifecycle |
|---|---|---|
| Kokoro models (~352 MB) | Docker named volume `comadre-models` | `kokoro-v1.0.onnx` (325 MB) + `voices-v1.0.bin` (27 MB). Downloaded once from HuggingFace |
| Qwen3 models (~1.6 GB) | Docker named volume `comadre-models` | `qwen3-tts-0.6b-q8_0.gguf` (1.3 GB) + `qwen3-tts-tokenizer-f16.gguf` (341 MB) |
| Clone reference WAV | Docker named volume `comadre-voices` | Operator-provisioned at deploy time for Qwen3 voice cloning |
| Noise WAV files (~2 MB) | Baked into Docker image | Room ambience + hiss noise for post-processing realism |
| espeak-ng pt_extra data | Baked into Docker image | Compiled custom dictionary (pt_dict ~141 KB + phoneme files) |
| qwen3-tts-cli binary | Baked into Docker image | Pre-built binary with seed patch (~600 KB) |
| API key | Environment variable | Set in compose.yaml or Ansible, never stored in image |

### Authentication & Security

| Decision | Implementation |
|---|---|
| Auth mechanism | Bearer token — `Authorization: Bearer <API_KEY>` |
| Key storage | `API_KEY` env var, never hardcoded or logged |
| Auth scope | All `/v1/audio/speech` requests. Health endpoint unauthenticated |
| Network security | No TLS (internal network). Docker network isolation. Zero outbound traffic post-deploy |
| Resource limits | CPU and memory constraints in compose.yaml |
| Auth implementation | FastAPI dependency injection — single `verify_api_key` dependency on the speech endpoint |

### API & Communication Patterns

| Decision | Implementation |
|---|---|
| API style | REST, OpenAI-compatible contract |
| Request validation | Pydantic models with FastAPI automatic validation |
| Error format | OpenAI JSON structure + `hint` field (centralized exception handlers) |
| Error types vocabulary | `invalid_request_error`, `authentication_error`, `not_found_error`, `server_error`, `service_unavailable` |
| Response format | Binary audio (`audio/wav` or `audio/ogg`) for success, JSON for errors |
| API documentation | FastAPI auto-generated OpenAPI/Swagger (built-in) |

### Frontend Architecture

Not applicable. No frontend. No UI.

### Infrastructure & Deployment

| Decision | Implementation |
|---|---|
| Container runtime | Docker with compose.yaml (Compose v2) |
| Base image | python:3.12-slim |
| System packages | espeak-ng (**built from source** + pt_extra dictionary compiled), ffmpeg, libsndfile1-dev, build deps (autoconf, automake, libtool, pkg-config) |
| Binary assets | qwen3-tts-cli (pre-built with seed patch), noise WAV files |
| Python packages | uv sync from uv.lock (kokoro-onnx, misaki, espeakng-loader, num2words, fastapi, uvicorn, pydantic-settings) |
| Deployment tool | Ansible (4 playbooks: bootstrap, update, cleanup, health) |
| Ansible structure | Flat playbooks in deploy/ansible/playbooks/ (no roles — project too small) |
| CI/CD | GitHub Actions (lint + test + build) |
| Monitoring | Health endpoint (engine load, queue depth, clone config) + docker stats + Ansible health playbook |
| Horizontal scaling | Caddy load balancer with round-robin, health checks per instance |
| Failover | n8n-side pattern: allows alerting, text fallback, per-context retry logic |
| Memory safety | Daily restart cron as safety net (Kokoro leak fixed in phonemizer-fork >=3.3.2) |
| Restart policy | `restart: unless-stopped` in compose.yaml |
| Log strategy | Structured pipe-delimited to stdout (Docker captures via `docker compose logs`) |

### Dependency Update Strategy

### Audio File Cleanup Strategy

Generated audio files are stored temporarily on the VPS SSD. Without periodic cleanup, disk space will be exhausted.

**Strategy:** User-level cron job configured by the bootstrap playbook:
- Clean up audio files older than 24 hours from the audio volume
- Run every 6 hours via user-level crontab
- Log cleanup actions for operational visibility
- Health playbook reports disk usage and cleanup cron status

```bash
# User-level crontab entry (configured by bootstrap playbook)
0 */6 * * * find ~/comadre/audio -name '*.ogg' -o -name '*.wav' -mmin +1440 -delete 2>/dev/null
```

### Platform Audio Format Compatibility

The `destination` request parameter allows platform-specific encoding optimization:

| Platform | Format | Codec | Rate | Bitrate | Voice Note UX |
|---|---|---|---|---|---|
| WhatsApp | OGG Opus | Opus | 16kHz | 24kbps | Yes (OGG Opus only) |
| Telegram | OGG Opus | Opus | 16kHz | 24kbps | Yes (OGG Opus only) |
| Messenger | OGG Opus | Opus | 16kHz | 24kbps | No (audio player) |
| Instagram | AAC (M4A) | AAC | 44.1kHz | 64kbps | No (audio player) |

**Key decision:** OGG Opus (mono, 16kHz, 24kbps) is the default — works for WhatsApp (voice note waveform), Telegram (voice note waveform), and Messenger (audio player). Instagram Direct requires AAC/M4A format. The `destination` request parameter selects the correct ffmpeg encoding pipeline: OGG Opus for whatsapp/telegram/messenger (default), AAC M4A for instagram.

**Note:** Post-processing pipelines currently output at 16kHz (speech/telephony standard). Opus accepts both 16kHz and 48kHz. 16kHz produces smaller files and is appropriate for voice messages.

### Dependency Update Strategy

**Python dependencies (kokoro-onnx, misaki, etc.):** Standard PyPI packages managed by uv. Update via `uv lock --upgrade`.

**qwen3-tts-cli binary:** Pre-built from qwen3-tts.cpp with custom seed patch. Update requires rebuilding the binary from source and replacing in the Docker image.

**espeak-ng pt_extra dictionary:** Custom entries in `deploy/espeak-ng/pt_extra`. Update by editing the file and rebuilding the Docker image (triggers recompilation).

**Routine update cycle:**

```bash
# Update all Python dependencies
uv lock --upgrade

# Verify locally
uv sync && uv run pytest

# Commit and deploy
git add uv.lock && git commit
ansible-playbook deploy/ansible/playbooks/update.yml
```

### Decision Impact Analysis

**Implementation Sequence:**

1. Project scaffolding (`uv init --package`, pyproject.toml, quality tooling config)
2. Configuration module (pydantic-settings)
3. Structured logging
4. Voice discovery module
5. Kokoro engine wrapper + Qwen3 engine wrapper + engine router
6. FastAPI app (health endpoint, speech endpoint, exception handlers, lifespan warm-up)
7. Dockerfile + compose.yaml
8. Ansible playbooks
9. CI/CD pipeline
10. Documentation

**Cross-Component Dependencies:**

| Component | Depends On |
|---|---|
| API endpoint | Service wrapper, schemas, exceptions, config, voice discovery |
| Health endpoint | Voice discovery, config, startup state |
| Service wrapper | kokoro-onnx (PyPI), qwen3-tts-cli (binary), voice config, preprocessing |
| Docker build | All Python code, system deps, uv.lock |
| Ansible playbooks | Docker build, compose.yaml, voice files |
| CI/CD | All of the above (validates the full chain) |

## Implementation Patterns & Consistency Rules

### Naming Patterns

**Python Code Naming:**

| Element | Convention | Example |
|---|---|---|
| Modules | snake_case | `voice_discovery.py` |
| Classes | PascalCase | `SpeechRequest`, `VoiceNotFoundError` |
| Functions/methods | snake_case | `generate_speech()`, `discover_voices()` |
| Variables | snake_case | `reference_audio`, `output_format` |
| Constants | UPPER_SNAKE_CASE | `DEFAULT_PORT`, `MAX_VOICE_DURATION` |
| Type aliases | PascalCase | `AudioBytes = bytes` |
| Private | leading underscore | `_load_model()`, `_warm_up` |
| Pydantic models | PascalCase, noun-based | `SpeechRequest`, `HealthResponse` |

**API Naming:**

| Element | Convention | Example |
|---|---|---|
| Endpoints | Lowercase with slashes, OpenAI-compatible | `/v1/audio/speech`, `/health` |
| JSON request fields | snake_case | `response_format`, `input` |
| JSON response fields | snake_case | `uptime_seconds`, `memory_mb` |
| Error type values | snake_case | `invalid_request_error`, `not_found_error` |
| HTTP headers | Standard casing | `Authorization`, `Content-Type` |

**Environment Variables:**

| Element | Convention | Example |
|---|---|---|
| App config | UPPER_SNAKE_CASE | `API_KEY`, `DEFAULT_VOICE`, `WORKERS`, `PORT` |
| No prefix | Keep it simple | `API_KEY` not `COMADRE_API_KEY` |

**File & Directory Naming:**

| Element | Convention | Example |
|---|---|---|
| Python files | snake_case.py | `voices.py`, `config.py` |
| Test files | test_*.py | `test_api.py`, `test_health.py` |
| Ansible playbooks | lowercase.yml | `bootstrap.yml`, `update.yml` |
| Shell scripts | lowercase.sh | `entrypoint.sh` |
| Config files | dotfile with extension | `.hadolint.yaml`, `.ansible-lint` |
| Docker | PascalCase / lowercase | `Dockerfile`, `compose.yaml` |

### Structure Patterns

**Module Responsibility:**

| Module | Responsibility | Must NOT contain |
|---|---|---|
| `main.py` | FastAPI app creation, lifespan, router mounting | Business logic, direct engine calls |
| `api.py` | Route handlers for `/v1/audio/speech` | Model loading, audio encoding |
| `schemas.py` | Pydantic request/response models only | Logic, imports from other app modules |
| `service.py` | Dual-engine wrapper: voice routing, Kokoro/Qwen3 dispatch, post-processing pipelines, OGG encoding | HTTP concerns, FastAPI dependencies |
| `preprocessing.py` | Engine-specific text preprocessing: normalize_text + chunk_text (Kokoro), expand_siglas (Qwen3) | HTTP concerns, TTS generation, voice discovery |
| `config.py` | pydantic-settings class, env var definitions | Logic beyond defaults/validation |
| `exceptions.py` | Exception classes + FastAPI exception handlers | Business logic |
| `health.py` | Health endpoint, runtime state aggregation | Audio generation logic |
| `logging.py` | Logger configuration, custom formatter | Business logic |
| `voices.py` | Voice file discovery, validation, listing | TTS generation, HTTP concerns |

**Import Dependency Graph:**

```
config.py          ← imported by everything (no app imports)
logging.py         ← imported by everything (no app imports)
schemas.py         ← imported by api.py, health.py (no app imports)
exceptions.py      ← imported by api.py, service.py, voices.py, preprocessing.py
preprocessing.py   ← imported by service.py (depends on config.py only)
voices.py          ← imported by service.py, health.py
service.py         ← imported by api.py
health.py          ← imported by main.py
api.py             ← imported by main.py
main.py            ← entry point (imports everything, imported by nothing)
```

No circular imports. Dependencies flow downward.

**Test Organization:**

| Test file | Tests | Approach |
|---|---|---|
| `conftest.py` | Shared fixtures: FastAPI test client, mock config, temp voice files | httpx AsyncClient with FastAPI app |
| `test_api.py` | Speech endpoint: auth, validation, success, error codes | Mock service.py (don't load real models in tests) |
| `test_health.py` | Health endpoint: status values, voice listing, warm-up state | Mock runtime state |

Tests are proportional — no testing the framework, no testing Pydantic validation that FastAPI already handles. Test our logic only.

### Format Patterns

**API Success Response:**

No JSON wrapper. Binary audio with headers:
```
HTTP/1.1 200 OK
Content-Type: audio/wav  (or audio/ogg)
Content-Disposition: attachment; filename="speech.wav"
```

**API Error Response (all error paths):**

```json
{
  "error": {
    "message": "Voice 'maria' not found",
    "type": "not_found_error",
    "hint": "Available voices: ['santa', 'dora', 'alex', 'clone', 'qwen-female', 'qwen-male']. Kokoro voices: santa, dora, alex. Qwen3 voices: clone, qwen-female, qwen-male."
  }
}
```

Rules:
- All three fields (`message`, `type`, `hint`) always present — never partial
- `type` uses fixed vocabulary: `invalid_request_error`, `authentication_error`, `not_found_error`, `server_error`, `service_unavailable`
- `hint` is always actionable — never restates the message
- No stack traces in production responses

**Health Response (always all fields):**

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
  "version": "0.2.0"
}
```

Rules:
- `status` is an enum: `healthy`, `warming_up`, `degraded`
- `voices` is always an array, never `null`
- `engines` shows per-engine status and voice assignments
- `queue_depth` shows current FIFO queue length
- `clone_configured` indicates whether clone reference WAV is available
- Field order is fixed — status first, version last
- All numeric fields have unit suffix: `_seconds`, `_mb`

**Log Format:**

```
2026-03-21T14:32:00Z | INFO  | startup  | Loading Kokoro TTS model...
```

Rules:
- Pipe-delimited, 4 fields: timestamp | level | component | message
- Timestamp: ISO 8601 UTC
- Level: fixed-width 5 chars (`INFO `, `WARN `, `ERROR`, `CRIT `)
- Components: `startup`, `request`, `memory`, `health`, `voice`
- Request logs include: method, path, voice, format, chars, duration

### Process Patterns

**Error Handling:**

```python
# Custom exceptions → centralized handler → consistent JSON
class ComadreError(Exception):
    status_code: int
    error_type: str
    hint: str

class VoiceNotFoundError(ComadreError):
    status_code = 404
    error_type = "not_found_error"

# Registered once in main.py via @app.exception_handler(ComadreError)
```

Rules:
- All expected errors are custom exception subclasses
- Unexpected errors caught by a fallback handler returning 500 with generic hint
- Never return raw Python tracebacks to the client
- Log the full traceback server-side at ERROR level

**Startup Sequence (lifespan):**

```
1. Load config (validate env vars — fail fast if API_KEY missing)
2. Configure structured logging
3. Verify espeak-ng pt_extra data is in place (system + misaki bundled path)
4. Detect clone reference WAV (optional — Qwen3 "clone" voice disabled if absent)
5. Load Kokoro model (kokoro-onnx)
6. Verify qwen3-tts-cli binary is available
7. Warm up Kokoro (short dummy pt-BR text through full pipeline including preprocessing + post-processing)
8. Warm up Qwen3 (short dummy text through full pipeline including expand_siglas + post-processing)
9. Set ready flag → health returns "healthy"
```

Rules:
- Each phase logs when it starts
- Failure at any phase = log CRIT + exit (don't start half-broken)
- Health returns 503 / `warming_up` until step 8 completes
- If clone reference WAV is absent, Qwen3 "clone" voice is disabled but service still starts

**Request Processing:**

```
1. Auth check (dependency injection)
2. Validate request body (Pydantic — automatic, enforce char limits per engine)
3. Acquire asyncio.Lock (FIFO queue)
4. Route voice to engine (santa/dora/alex → Kokoro; clone/qwen-* → Qwen3)
5. Apply engine-specific preprocessing:
   - Kokoro: normalize_text() + chunk_text() (max 200 tokens per chunk)
   - Qwen3: expand_siglas() (spaced format for spelled siglas)
6. Generate TTS:
   - Kokoro: kokoro-onnx for each chunk → concatenate WAV chunks
   - Qwen3: qwen3-tts-cli subprocess (-l pt, --seed N, --temperature 0.7)
7. Apply engine-specific post-processing pipeline via ffmpeg:
   - Kokoro: vibrato_warm (vibrato, EQ, exciter, compressor, echo, noise)
   - Qwen3: whatsapp-subtle (EQ, compressor, atempo 1.15x, echo, noise)
8. Encode to OGG Opus 24kbps 16kHz mono (or WAV if requested)
9. Release asyncio.Lock
10. Return binary response
```

Rules:
- Each step can fail independently with its own error type
- No retry logic inside the request path — fail fast, let the caller retry
- Log every request with duration at INFO level

### Enforcement Guidelines

**All AI Agents MUST:**

1. Follow the import dependency graph — no circular imports, no upward imports
2. Use the centralized exception hierarchy — never raise raw `HTTPException`
3. Include all three fields in error responses — never partial error JSON
4. Log through the structured logger — never `print()` or raw `logging.basicConfig()`
5. Keep module boundaries clean — no HTTP concerns in service.py, no business logic in api.py
6. Type-annotate all function signatures — mypy strict will enforce this
7. Use pydantic-settings for all configuration — never raw `os.environ`

**Pattern Enforcement:**

- **ruff** catches naming violations, import ordering, style issues
- **mypy --strict** catches missing type annotations, wrong types
- **pre-commit** runs all checks before every commit
- **CI pipeline** runs the full check suite on every push

### Pattern Examples

**Good:**
```python
# service.py — clean separation
async def generate_speech(text: str, voice: str, format: str) -> bytes:
    ...
    raise VoiceNotFoundError(voice=voice, available=list_voices())
```

**Anti-pattern:**
```python
# service.py — DON'T DO THIS
from fastapi import HTTPException
async def generate_speech(...):
    raise HTTPException(status_code=404, detail="not found")  # Wrong: HTTP concern in service
```

**Good:**
```python
# config.py — single source of truth
class Settings(BaseSettings):
    api_key: SecretStr
    default_voice: str = "santa"
    port: int = 8000
    espeak_data_path: str | None = None  # Override bundled espeak-ng data for pt-BR quality
    qwen3_cli_path: str = "/usr/local/bin/qwen3-tts-cli"
    clone_reference_path: str | None = None  # Path to clone reference WAV for Qwen3
```

**Anti-pattern:**
```python
# DON'T DO THIS — scattered os.environ calls
voice = os.environ.get("DEFAULT_VOICE", "default")  # Wrong: use Settings
```

## Project Structure & Boundaries

### Complete Project Directory Structure

```
comadre/
├── .github/
│   └── workflows/
│       └── ci.yml                    # GitHub Actions: lint + test + docker build
├── src/
│   └── comadre/
│       ├── __init__.py               # Package init, __version__
│       ├── main.py                   # FastAPI app, lifespan, router mounting
│       ├── api.py                    # POST /v1/audio/speech route handler
│       ├── schemas.py                # SpeechRequest, HealthResponse, ErrorResponse
│       ├── service.py                # Dual-engine wrapper: voice routing, Kokoro/Qwen3 dispatch, post-processing, OGG encoding
│       ├── preprocessing.py          # pt-BR text normalization + sentence chunking
│       ├── config.py                 # Settings(BaseSettings) — all env vars
│       ├── exceptions.py             # ComadreError hierarchy + exception handlers
│       ├── health.py                 # GET /health route, runtime state assembly
│       ├── logging.py                # Structured pipe-delimited formatter + setup
│       └── voices.py                 # Voice discovery, WAV validation, listing
├── tests/
│   ├── conftest.py                   # Test client fixture, mock settings, temp voice dir
│   ├── test_api.py                   # Speech endpoint: auth, validation, formats, errors
│   └── test_health.py               # Health endpoint: statuses, voices, warm-up state
├── deploy/
│   └── ansible/
│       ├── ansible.cfg               # Ansible config scoped to this directory
│       ├── inventory/
│       │   └── production.yml        # VPS host, connection vars
│       └── playbooks/
│           ├── bootstrap.yml         # Full deploy from scratch
│           ├── update.yml            # Pull + rebuild + restart, preserve data
│           ├── cleanup.yml           # Full VPS wipe
│           └── health.yml            # Diagnostic cascade
├── scripts/
│   └── entrypoint.sh                # Uvicorn launch with WORKERS/PORT from env
├── voices/                           # .gitkeep only — reference WAVs are operator-provisioned
│   └── .gitkeep
├── Dockerfile                        # Single-stage python:3.12-slim, system deps, uv sync
├── compose.yaml                      # TTS service, volumes, resource limits, health check
├── pyproject.toml                    # Project metadata, deps, ruff/mypy/pytest config
├── uv.lock                          # Locked dependencies (committed)
├── .python-version                   # 3.12
├── .pre-commit-config.yaml           # All quality hooks
├── .hadolint.yaml                    # Dockerfile lint config
├── .yamllint.yaml                    # YAML lint config
├── .ansible-lint                     # Ansible lint config
├── .markdownlint.yaml                # Markdown lint config
├── .gitignore                        # Python, Docker, env files, model cache
├── .env.example                      # Template: API_KEY, DEFAULT_VOICE, WORKERS, PORT
├── CLAUDE.md                         # AI agent instructions
├── LICENSE
└── README.md                         # Brazilian Portuguese — public-facing
```

### Architectural Boundaries

**API Boundary:**

```
External (n8n / curl)
        │
        ▼
┌─────────────────────────────┐
│  FastAPI (main.py)          │
│  ├── /v1/audio/speech (api) │ ◄── Bearer token auth + asyncio.Lock queue
│  └── /health (health)       │ ◄── No auth
└──────────┬──────────────────┘
           │
     ┌─────▼──────────────┐
     │    service.py       │ ◄── Business logic boundary
     │  ┌─ voice routing ─┐│
     │  │ santa/dora/alex  ││ → Kokoro fp32 (kokoro-onnx) → vibrato_warm pipeline
     │  │ clone/qwen-*     ││ → Qwen3-TTS C++ (subprocess) → whatsapp-subtle pipeline
     │  └─────────────────┘│
     │  preprocessing.py    │ ◄── Engine-specific text normalization
     │  ffmpeg pipelines    │ ◄── Post-processing + OGG Opus encoding
     └─────────┬───────────┘
               │
        ┌──────▼──────┐
        │  voices.py  │ ◄── Voice config + clone reference detection
        └─────────────┘
```

Rules:
- `api.py` and `health.py` are the only modules that touch HTTP request/response
- `service.py` knows nothing about HTTP — receives typed args, returns bytes
- `voices.py` knows nothing about HTTP or TTS — scans filesystem, returns voice metadata
- `config.py` is the single source of truth for all runtime configuration

**Container Boundary:**

```
┌─ Host (Debian 13) ──────────────────────────────┐
│                                                  │
│  User-level crontab (daily restart)             │
│                                                  │
│  ┌─ Docker (user in docker group) ───────────┐  │
│  │                                            │  │
│  │  comadre-service                          │  │
│  │  ├── Uvicorn (single worker)              │  │
│  │  ├── asyncio.Lock FIFO queue              │  │
│  │  ├── Port 8000 (mapped)                   │  │
│  │  │                                        │  │
│  │  │  Volumes:                              │  │
│  │  │  ├── comadre-voices:/voices (ro)       │  │
│  │  │  ├── comadre-models:/models (rw)       │  │
│  │  │  └── comadre-audio:/audio (rw)         │  │
│  │  │                                        │  │
│  │  │  Resource limits:                      │  │
│  │  │  ├── cpus: 4                           │  │
│  │  │  └── memory: 6G                        │  │
│  │  │                                        │  │
│  │  │  Network:                              │  │
│  │  │  └── No outbound (post-deploy)         │  │
│  │  └────────────────────────────────────────│  │
│  └────────────────────────────────────────────┘  │
└──────────────────────────────────────────────────┘
```

**Deployment Boundary:**

```
Developer machine                    VPS (Debian 13)
┌──────────────┐                    ┌──────────────────────┐
│ comadre/     │   Ansible SSH      │ ~/comadre/           │
│ deploy/      │ ──────────────►    │   Dockerfile         │
│  ansible/    │  (as VPS user)     │   compose.yaml       │
│  playbooks/  │                    │   src/               │
│              │                    │   voices/            │
│ voices/*.wav │ ──── copy ────►    │   voices/*.wav       │
└──────────────┘                    └──────────────────────┘

All project files live in ~/comadre (user home directory).
No files in /opt, /tmp, /src, /bin, or any system directory.
```

**Ansible Privilege Model:**

| Playbook | Privilege | Scope |
|---|---|---|
| `bootstrap.yml` | `become: true` for apt tasks only | Install Docker, add user to docker group (Debian 13 apt) |
| `bootstrap.yml` | Unprivileged for everything else | Clone repo to ~/comadre, copy voices, docker compose up |
| `update.yml` | Unprivileged | git pull in ~/comadre, docker compose build + restart |
| `cleanup.yml` | Unprivileged | docker compose down, rm -rf ~/comadre |
| `health.yml` | Unprivileged | curl health endpoint, docker stats |

**Critical rule:** After bootstrap installs system packages and adds the user to the `docker` group, all subsequent operations run without privilege escalation. The daily restart cron is a user-level crontab entry, not a system cron.

### Requirements to Structure Mapping

**FR Category → Files:**

| FR Category | Primary File(s) | Supporting Files |
|---|---|---|
| Audio Generation (FR1-FR5b) | `service.py`, `preprocessing.py` | `voices.py`, `config.py` |
| API Interface (FR6-FR10) | `api.py`, `schemas.py` | `exceptions.py`, `main.py` |
| Health & Monitoring (FR11-FR13) | `health.py` | `voices.py`, `config.py` |
| Voice Management (FR14-FR16) | `voices.py` | `config.py` |
| Container Lifecycle (FR17-FR21) | `Dockerfile`, `compose.yaml`, `main.py` (lifespan) | `entrypoint.sh` |
| Deployment & Ops (FR22-FR26) | `deploy/ansible/playbooks/*.yml` | `compose.yaml` |
| Security (FR27-FR28) | `api.py` (auth dep), `compose.yaml` (limits) | `config.py` |

**Cross-Cutting Concerns → Locations:**

| Concern | Files Involved |
|---|---|
| Structured logging | `logging.py` (config), all modules (usage) |
| Error consistency | `exceptions.py` (classes + handlers), `main.py` (handler registration) |
| Configuration | `config.py` (definition), `compose.yaml` (env vars), `.env.example` (template) |
| Engine routing | `service.py` (voice-to-engine dispatch), `preprocessing.py` (engine-specific text processing), `config.py` (voice config) |
| Post-processing | `service.py` (ffmpeg pipeline dispatch), noise WAV files (baked into image) |
| Queue management | `api.py` (asyncio.Lock acquire/release), `health.py` (queue_depth reporting) |
| Memory safety | `compose.yaml` (resource limits), `health.py` (memory reporting), `bootstrap.yml` (user crontab safety net) |
| Startup readiness | `main.py` (lifespan — dual-engine warm-up), `health.py` (503 gating), `compose.yaml` (healthcheck start_period) |

### Data Flow

```
n8n POST /v1/audio/speech
    │
    ▼
api.py: validate request (Pydantic) → verify auth (dependency) → acquire asyncio.Lock
    │
    ▼
service.py: route voice to engine
    │
    ├─── Kokoro voices (santa/dora/alex) ──────────────────────────────┐
    │    ▼                                                              │
    │    preprocessing.py: normalize_text() + chunk_text()             │
    │    ├── num2words: numbers, currency (R$), ordinals               │
    │    ├── custom: dates, times                                       │
    │    └── chunking: split into sentences (100-200 tokens, max 500c) │
    │    ▼ (for each chunk)                                             │
    │    kokoro-onnx: espeak-ng (pt_extra) → Kokoro fp32 → WAV 24kHz  │
    │    ▼                                                              │
    │    service.py: concatenate chunks → vibrato_warm pipeline         │
    │    (vibrato → highpass → bass → EQ → exciter → softclip →         │
    │     compressor → lowpass → echo → loudnorm → noise → loudnorm)   │
    │                                                                   │
    ├─── Qwen3 voices (clone/qwen-female/qwen-male) ──────────────────┐
    │    ▼                                                              │
    │    preprocessing.py: expand_siglas() (spaced format)             │
    │    ▼                                                              │
    │    subprocess: qwen3-tts-cli -l pt --seed N --temperature 0.7    │
    │    → WAV (with optional clone reference)                          │
    │    ▼                                                              │
    │    service.py: whatsapp-subtle pipeline                           │
    │    (EQ → compressor → atempo 1.15x → echo → noise)               │
    │                                                                   │
    └── Both paths ──► loudnorm → OGG Opus 24kbps 16kHz mono ─────────┘
    │
    ▼
api.py: release Lock → return Response(content=audio_bytes, media_type="audio/ogg")
    │
    ▼
n8n receives OGG Opus → sends to WhatsApp/Instagram/Telegram/Messenger
```

### Development Workflow Integration

**Local Development:**

```bash
uv sync                              # Install all deps (including dev groups)
uv run pre-commit install            # Set up git hooks
cp .env.example .env                 # Configure local env vars
uv run pytest                        # Run tests (mocked, no model needed)
uv run ruff check . && uv run mypy src/  # Lint + type check
```

**Docker Development:**

```bash
docker compose build                 # Build image
docker compose up                    # Start service (downloads models on first run)
curl http://localhost:8000/health     # Verify health
```

**Deployment:**

```bash
cd deploy/ansible
ansible-playbook playbooks/bootstrap.yml -i inventory/production.yml
```

## Architecture Validation Results

### Coherence Validation

- Decision compatibility: All technology choices verified compatible — no conflicts
- Pattern consistency: Naming, structure, and process patterns align with technology stack
- Structure alignment: Project tree supports all decisions, boundaries are clear

### Requirements Coverage

- **All functional requirements** (including new FR5a, FR5b) have explicit architectural support
- **All non-functional requirements** addressed (latency, memory, uptime, security, data preservation)
- **All cross-cutting concerns** mapped to specific files and patterns

### Implementation Readiness

- All modules defined with clear responsibilities and "must NOT contain" boundaries
- Import dependency graph prevents circular imports
- Error handling, startup, and request processing patterns fully specified with examples
- Test strategy proportional to codebase size
- Quality tooling covers Python, Dockerfile, YAML, Ansible, shell, and Markdown
- Dependency update workflow documented (PyPI packages via uv, qwen3-tts-cli binary, espeak-ng pt_extra dictionary)

### Architecture Completeness Checklist

**Requirements Analysis**

- [x] Project context analyzed — 30 FRs across 8 categories (including FR5a, FR5b, FR29)
- [x] Scale assessed — Low complexity, single-purpose API backend
- [x] Technical constraints identified — Dual-engine (Kokoro + Qwen3), espeak-ng pt_extra, qwen3-tts-cli binary, ffmpeg post-processing
- [x] Cross-cutting concerns mapped — memory, persistence, readiness, errors, logging

**Architectural Decisions**

- [x] 11 critical/important decisions documented with rationale
- [x] Technology stack fully specified — Python 3.12, FastAPI, uv, Docker, Ansible, Kokoro-ONNX, Qwen3-TTS C++
- [x] Integration approach defined — kokoro-onnx (PyPI) + qwen3-tts-cli (binary subprocess)
- [x] Performance approach defined — Single FIFO queue, horizontal scaling via Caddy, dual-engine warm-up

**Implementation Patterns**

- [x] Naming conventions — Python, API, env vars, files
- [x] Structure patterns — module responsibilities, import graph, test organization
- [x] Format patterns — API responses, errors, health, logs
- [x] Process patterns — error handling, startup, request flow

**Project Structure**

- [x] Complete directory tree with every file annotated
- [x] Architectural boundaries diagrammed — API, container, deployment
- [x] FR-to-file mapping complete
- [x] Deployment model defined — ~/comadre, unprivileged except bootstrap apt

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION

**Confidence Level:** High

**Key Strengths:**

- Extremely focused scope — single endpoint, single consumer, ~150 lines of core code
- ML inference delegated to Kokoro (kokoro-onnx) and Qwen3 (qwen3-tts-cli) — architecture manages routing, preprocessing, and post-processing
- Quality tooling is comprehensive — 8 linters covering every file format
- Deployment model is simple and safe — Ansible with clear privilege boundaries

**Areas for Future Enhancement (post-MVP):**

- Response caching for repeated phrases
- Prometheus metrics endpoint
- GPU acceleration support
- Renovate Bot for automated dependency updates

### Implementation Handoff

**AI Agent Guidelines:**

- Follow all architectural decisions exactly as documented
- Use implementation patterns consistently — especially the exception hierarchy and module boundaries
- Respect the import dependency graph — dependencies flow downward only
- All config via pydantic-settings, never raw os.environ
- All errors via ComadreError subclasses, never raw HTTPException
- All logging via structured logger, never print()
- All project files on VPS live in ~/comadre — never in /opt, /tmp, or system directories
- Ansible uses `become: true` only for apt tasks in bootstrap — everything else unprivileged

**First Implementation Priority:**

```bash
uv init --package comadre
```

Then configure pyproject.toml with all tool settings and quality tooling.
