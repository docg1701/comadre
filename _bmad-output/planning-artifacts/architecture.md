---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
lastStep: 8
status: 'complete'
completedAt: '2026-03-21'
inputDocuments:
  - _bmad-output/planning-artifacts/product-brief-cumadre-2026-03-21.md
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/ux-design-specification.md
workflowType: 'architecture'
project_name: 'cumadre'
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
| Audio Generation (FR1-FR5) | Text → TTS → voice cloning → audio output | Core pipeline: Kokoro TTS + Kanade voice conversion, espeak-ng for pt-BR phonemization |
| API Interface (FR6-FR10) | OpenAI-compatible endpoint, bearer auth, error codes, 503 warm-up | FastAPI with middleware auth, structured error handlers, startup readiness gate |
| Service Health & Monitoring (FR11-FR13) | Health endpoint with status, voices, uptime | Dedicated health route aggregating runtime state from multiple sources |
| Voice Management (FR14-FR16) | Volume-mounted WAV files, discovery at startup, configurable default | Voice discovery module scanning /voices/ directory, validation at boot |
| Container Lifecycle (FR17-FR21) | Auto model download, persistent cache, warm-up, configurable workers | Docker volumes for models and voices, multi-process via uvicorn workers, startup warm-up hook |
| Deployment & Operations (FR22-FR26) | Four Ansible playbooks, daily restart cron | Ansible roles for bootstrap/update/cleanup/health, host-level cron for memory leak |
| Security & Isolation (FR27-FR28) | Zero outbound network post-deploy, Docker resource limits | Network-isolated container, CPU/memory constraints in docker-compose.yml |

**Non-Functional Requirements:**

| NFR | Target | Architectural Driver |
|---|---|---|
| Response latency | < 3s (~15 words, 4 vCPU) | CPU-bound inference — worker count and process isolation matter |
| Cold start | < 120s (excl. model download) | Model loading + warm-up inference on startup |
| Memory per worker | < 3 GB steady state | Each worker loads full model stack independently |
| Memory stability | No growth beyond 4 GB over 24h | Upstream Kokoro leak — mitigated by daily restart cron, not code fix |
| Throughput | 20-60 req/min | Linear scaling via WORKERS env var (independent processes) |
| Availability | 99%+ (excl. scheduled restarts) | Docker restart policy + health check + cron restart |
| Data preservation | 100% on updates | Docker volumes for voices and model cache, not baked into image |

**Scale & Complexity:**

- Primary domain: API backend
- Complexity level: Low
- Estimated architectural components: 5 (FastAPI app, Docker packaging, Ansible playbooks, voice management, health/monitoring)

### Technical Constraints & Dependencies

| Constraint | Source | Impact |
|---|---|---|
| KokoClone is a bare Python library | Upstream project | Must wrap API, manage model lifecycle, handle memory leak |
| Kokoro memory leak | Known upstream issue | Daily container restart cron required; health endpoint must report memory |
| espeak-ng is the sole phonemizer for pt-BR | Kokoro/misaki has no native Portuguese G2P | Must build espeak-ng from source (PR #2344, Mar 2026) for quality pt-BR; bundled `espeakng-loader` data is outdated |
| ffmpeg required for OGG encoding | Audio format conversion | Must be installed in Docker image (system package) |
| HuggingFace model download on first run | Model distribution | Internet required once at bootstrap; models cached in Docker volume |
| uv for Python dependency management | Project policy | Dockerfile uses uv, not pip |
| Single consumer (n8n) on local network | Deployment context | No TLS, no rate limiting, no multi-tenancy, plain HTTP |
| CPU-only inference | Hardware target (4 vCPU / 8 GB RAM commodity VPS) | No CUDA/GPU dependencies; throughput bounded by CPU |

### Cross-Cutting Concerns Identified

1. **Memory Leak Mitigation** — Touches container lifecycle (restart policy), health reporting (memory_mb field), deployment (cron setup in bootstrap), and operational monitoring (health playbook). Every component that interacts with the running service must account for degrading memory.

2. **Model & Voice Persistence** — Docker volumes must survive container rebuilds, updates, and restarts. Affects Dockerfile design (cache in volume, not layer), docker-compose.yml (volume mounts), Ansible update playbook (must not delete volumes), and voice discovery (scan volume at startup).

3. **Startup Readiness** — Model loading + voice discovery + warm-up creates a multi-second startup window where the service exists but cannot serve requests. Health endpoint must return 503 during this window. Docker health check must accommodate it. Ansible bootstrap must wait for it.

4. **Error Consistency** — The OpenAI-compatible error format with `hint` field must be uniform across all error paths (auth, validation, voice not found, model failure, encoding failure, warm-up). Centralized exception handling is required to prevent inconsistency.

5. **Structured Logging** — Pipe-delimited format with component tags must be configured application-wide. All modules (startup, request handling, voice discovery, health) log through the same formatter.

6. **pt-BR Phonemization Quality** — espeak-ng is the sole phonemizer for Portuguese with known limitations (vowel confusion, stress errors). Mitigated by: building espeak-ng from source (PR #2344), text pre-processing (numbers, currency, dates, chunking), custom dictionary for domain words, and a quality validation listening test before production.

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

**Rationale:** CUMADRE is ~80-150 lines of core code. Any template beyond `uv init` adds more to delete than to keep. The src layout, pyproject.toml, and .python-version are the only scaffolding needed.

**Initialization Command:**

```bash
uv init --package cumadre
```

### KokoClone Integration Discovery

KokoClone is **not on PyPI** — it's a GitHub-only project built on **kokoro-onnx** (not the official `kokoro` PyTorch package). Key findings from research:

#### kokoro vs kokoro-onnx

| | `kokoro` (official, hexgrad) | `kokoro-onnx` (thewh1teagle) |
|---|---|---|
| Runtime | PyTorch (~873 MB wheel) | **ONNX Runtime (~16 MB wheel)** |
| Extra deps | transformers, spacy, huggingface_hub | Minimal (numpy, phonemizer-fork) |
| Model format | `.pth` 325 MB | `.onnx` 310 MB / **int8: 88 MB** |
| CPU quantization | No | **Yes (int8, 2-3x faster on CPU)** |
| espeak-ng bundling | via espeakng-loader | via espeakng-loader |

KokoClone uses **kokoro-onnx** — the right choice for CPU-only deployment due to dramatically smaller footprint and int8 quantization support. Same Kokoro-82M model, same voices, same quality — only the inference runtime differs.

#### KokoClone capabilities

| Aspect | Detail |
|---|---|
| Installation | uv git dependency from GitHub |
| Core API | `from core.cloner import KokoClone` → `cloner.generate(text, lang, reference_audio, output_path)` |
| Voice cloning | Zero-shot: 3-10s reference WAV → speaker embedding → cloned speech |
| Models | ~1 GB auto-downloaded from HuggingFace on first run (Kokoro ONNX + Kanade tokenizer + Vocos vocoder) |
| Sample rate | 24kHz output |
| Languages | en, pt (Brazilian), hi, fr, ja, zh, it, es |
| Memory leak | **Fixed** in `phonemizer-fork>=3.3.2` (kokoro-onnx >=0.5.0). Daily restart cron is a safety net, not a hard requirement |
| System deps | espeak-ng (phonemizer — **must build from source for pt-BR quality**), ffmpeg (OGG encoding), libsndfile |
| Python deps | kokoro-onnx, misaki, kanade-tokenizer (git dep), soundfile, phonemizer-fork, espeakng-loader |
| Device | Auto-detects CPU/GPU; CPU-only for this project |

### pt-BR Phonemization: Research Findings & Mitigations

#### The core problem

The `misaki` G2P library (Kokoro's phonemizer) has **no native Portuguese module**. Native G2P exists only for English, Japanese, Chinese, Korean, Vietnamese, and Hebrew. For Portuguese (and Spanish, French, Hindi, Italian), misaki falls back entirely to `espeak.EspeakG2P(language='pt-br')`.

This means pt-BR quality is **bounded by espeak-ng's phonemization quality**.

#### Known espeak-ng limitations for pt-BR

| Issue | Severity | Impact |
|---|---|---|
| Open/close vowel confusion (`é`/`ê`, `ó`/`ô`) | **High** | Phonemic in pt-BR — wrong vowel = wrong word |
| Stress position errors | Medium | Rules work for most cases, fails on exceptions |
| No text chunking in Kokoro for pt-BR | **High** | Texts >510 tokens silently truncated |
| No pronunciation override syntax | Medium | The `[word](/phonemes/)` syntax only works for English |
| Dates and times not normalized | Medium | Pronounced as digit sequences |

#### Mitigation: Updated espeak-ng data (CRITICAL)

espeak-ng PR [#2344](https://github.com/espeak-ng/espeak-ng/pull/2344) (merged 2026-03-20, by fabiolimace — new official Portuguese maintainer) delivered massive pt-BR improvements:

- **+5,618 lines** in pronunciation dictionary
- 250+ pronunciation corrections
- 900+ abbreviations and acronyms (tech, politics, etc.)
- 3,500+ words and names
- Improved phoneme definitions for pt-BR
- Unicode Latin-1 Supplement normalization
- New documentation at `docs/languages/roa/pt.md`

**Problem:** `espeakng-loader` v1.52 (Jan 2025) bundles espeak-ng data that is **over a year old** — none of these improvements are included.

**Solution:** Build espeak-ng from source and override the data path:

```bash
# In Dockerfile: build espeak-ng from master
RUN git clone --depth 1 https://github.com/espeak-ng/espeak-ng.git /tmp/espeak-ng && \
    cd /tmp/espeak-ng && ./autogen.sh && ./configure && make && \
    cp -r espeak-ng-data /usr/share/espeak-ng-data-custom && \
    rm -rf /tmp/espeak-ng
```

```python
# In service startup, before loading models:
import os
os.environ["ESPEAK_DATA_PATH"] = "/usr/share/espeak-ng-data-custom"
```

New config field: `ESPEAK_DATA_PATH` (optional, defaults to bundled espeakng-loader path).

#### Mitigation: Text pre-processing module (REQUIRED)

A new `preprocessing.py` module must normalize text before sending to the TTS pipeline. espeak-ng does NOT normalize dates or times for pt-BR, and numbers/currency are more reliable when pre-processed.

**Required normalizations:**

| Input | Output | Library |
|---|---|---|
| `R$ 1.500,00` | `mil e quinhentos reais` | `num2words` (lang='pt_BR', to='currency') |
| `1500` | `mil e quinhentos` | `num2words` (lang='pt_BR') |
| `3º` | `terceiro` | `num2words` (lang='pt_BR', to='ordinal') |
| `21/03/2026` | `vinte e um de março de dois mil e vinte e seis` | Custom |
| `14:30` | `quatorze e trinta` | Custom |
| Domain-specific abbreviations | Expanded form | Custom dictionary |

New dependency: `num2words>=0.5` (already supports pt_BR).

#### Mitigation: Text chunking (REQUIRED)

Kokoro has **no chunking logic for Portuguese** — long texts are silently truncated at ~510 tokens. The `preprocessing.py` module must split text at sentence boundaries, targeting 100-200 tokens per chunk.

```python
import re
sentences = re.split(r'(?<=[.!?])\s+', text)
```

#### Mitigation: Custom espeak-ng dictionary

For domain-specific words that espeak-ng mispronounces, create a `pt_extra` file:

```
// dictsource/pt_extra — compiled with: espeak-ng --compile=pt
cumadre  kum'adR@
```

This file is compiled into `pt_dict` and applied after the main dictionary. Include it in the Docker build.

#### Mitigation: Voice blending

Kokoro supports mixing pt-BR voices for potentially better results:

```python
voice = 'pf_dora:60,pm_alex:40'  # Weighted blend
```

Available pt-BR voices: `pf_dora` (F), `pm_alex` (M), `pm_santa` (M). No quality grades are published for any of them — experimentation is needed.

#### Mitigation: Direct phoneme input for critical phrases

The `generate_from_tokens()` API bypasses espeak-ng entirely:

```python
# Inspect what espeak-ng generates
for result in pipeline("Seu texto"):
    print(result.phonemes)

# Override with corrected phonemes
for result in pipeline.generate_from_tokens(
    tokens="corrected_phonemes",
    voice='pf_dora'
):
    pass  # result.audio
```

This is a last-resort escape hatch for phrases where espeak-ng produces unacceptable results.

#### Alternative TTS engines evaluated

All alternatives were evaluated and **rejected** due to hardware constraints (4 vCPU / 8 GB RAM, CPU-only):

| Engine | pt-BR | Voice Clone | CPU Feasible | Why Rejected |
|---|---|---|---|---|
| XTTS v2 (Coqui) | Good | Zero-shot | No (~250s/phrase) | CPU inference unusable |
| Fish Speech S2 | Good | Zero-shot | No (needs 12GB+ VRAM) | Needs GPU |
| F5-TTS pt-BR | Very good (dedicated fine-tune) | Zero-shot | No (7+ min/phrase) | CPU inference unusable |
| Qwen3-TTS 0.6B | Good | Zero-shot | Marginal (10-15x RTF) | 6-8 GB RAM, too slow on 4 vCPU |
| Qwen3-TTS 1.7B | Good | Zero-shot | No (needs 14-16 GB RAM) | OOM on 8 GB |
| Bark | Fair | No real cloning | No (10-20x slow) | No voice cloning, too slow |
| Piper | No pt-BR voices | None | Excellent | No pt-BR, no cloning |
| Edge TTS | Excellent | None | Cloud-only | Not self-hosted |

**Conclusion:** KokoClone (Kokoro-82M + Kanade) remains the only viable option for CPU-only, self-hosted, pt-BR voice cloning. Quality mitigation through the strategies above is the path forward.

#### Quality validation gate

Before production deployment, a **listening test** of 20+ typical customer service phrases is required:

1. Generate audio for representative phrases (greetings, order status, scheduling, etc.)
2. Evaluate: pronunciation accuracy, naturalness, voice cloning similarity
3. If unacceptable, iterate on pre-processing rules, custom dictionary entries, or voice blending
4. This is tracked as an acceptance criterion for Story 1.4 (Service Wrapper)

### Project Structure

```
cumadre/
├── src/
│   └── cumadre/
│       ├── __init__.py
│       ├── main.py            # FastAPI app, startup lifecycle, health endpoint
│       ├── api.py             # POST /v1/audio/speech route
│       ├── schemas.py         # Pydantic request/response models
│       ├── service.py         # KokoClone wrapper, audio generation logic
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
├── voices/                    # Reference WAV files (gitignored, volume-mounted)
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
| Layout | `src/cumadre/` | Import safety, prevents accidental local imports during testing |
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
| D1 | KokoClone integration | uv git dependency pinned in uv.lock | Standard dependency management, reproducible builds, no submodule complexity |
| D2 | Model download strategy | Runtime + Docker volume cache | First start downloads from HuggingFace, cached in named volume. Survives rebuilds/updates |
| D3 | Worker process model | Uvicorn --workers N | Independent processes, no shared state. WORKERS=1 default, scales with RAM |
| D4 | Warm-up strategy | FastAPI lifespan + health endpoint gating | Lifespan runs dummy inference; health returns 503 until ready; Docker health check accommodates |

**Important Decisions (Shape Architecture):**

| # | Decision | Choice | Rationale |
|---|---|---|---|
| D5 | Docker build | Single-stage python:3.12-slim | torch dominates image size; multi-stage adds complexity for marginal savings |
| D6 | Configuration | pydantic-settings | Type-safe env var loading, validates API_KEY at startup, FastAPI ecosystem standard |
| D7 | OGG encoding | ffmpeg subprocess | ffmpeg already a system dep, ~5 lines, no extra Python deps |
| D8 | CI/CD | GitHub Actions | pre-commit + pytest + docker build. Free, good uv support |

**Deferred Decisions (Post-MVP):**

| Decision | Rationale for Deferral |
|---|---|
| Response caching | PRD: "measure demand first" — no evidence of repeated phrases yet |
| GPU acceleration | CPU-only for MVP target hardware |
| Prometheus metrics | Health endpoint sufficient for single-consumer service |
| Horizontal scaling | Single VPS is the deployment target |

### Data Architecture

No database. No persistent data storage. Audio is generated and returned in the response — never persisted. The only stateful data:

| Data | Storage | Lifecycle |
|---|---|---|
| ML models (~1 GB) | Docker named volume `cumadre-models` | Downloaded once, cached indefinitely, survives rebuilds |
| Voice reference WAVs | Docker named volume `cumadre-voices` | Operator-provisioned, mounted read-only by container |
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
| System packages | espeak-ng (**built from source** for pt-BR quality — PR #2344), ffmpeg, libsndfile1-dev, autoconf, automake, libtool, pkg-config (espeak-ng build deps) |
| Python packages | uv sync from uv.lock |
| Deployment tool | Ansible (4 playbooks: bootstrap, update, cleanup, health) |
| Ansible structure | Flat playbooks in deploy/ansible/playbooks/ (no roles — project too small) |
| CI/CD | GitHub Actions (lint + test + build) |
| Monitoring | Health endpoint + docker stats + Ansible health playbook |
| Memory leak mitigation | Host-level cron (daily container restart) configured by bootstrap playbook |
| Restart policy | `restart: unless-stopped` in compose.yaml |
| Log strategy | Structured pipe-delimited to stdout (Docker captures via `docker compose logs`) |

### Dependency Update Strategy

KokoClone is actively developed on GitHub and not published on PyPI. The update workflow:

**Routine update cycle:**

```bash
# Update all dependencies (PyPI + git)
uv lock --upgrade

# Or update only KokoClone
uv lock --upgrade-package kokoclone

# Verify locally
uv sync && uv run pytest

# Commit and deploy
git add uv.lock && git commit
ansible-playbook deploy/ansible/playbooks/update.yml
```

**How it works:** uv.lock pins git dependencies by exact commit hash. `uv lock --upgrade` fetches the latest commit from the default branch and updates the hash. Builds are reproducible — `uv sync --frozen` in Docker uses the exact pinned hash.

**Post-MVP automation:** Renovate Bot can be configured to auto-open PRs when git dependencies have new commits, same as it does for PyPI packages.

### Decision Impact Analysis

**Implementation Sequence:**

1. Project scaffolding (`uv init --package`, pyproject.toml, quality tooling config)
2. Configuration module (pydantic-settings)
3. Structured logging
4. Voice discovery module
5. KokoClone service wrapper
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
| Service wrapper | KokoClone (uv git dep), voice discovery, config |
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
| No prefix | Keep it simple | `API_KEY` not `CUMADRE_API_KEY` |

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
| `main.py` | FastAPI app creation, lifespan, router mounting | Business logic, direct KokoClone calls |
| `api.py` | Route handlers for `/v1/audio/speech` | Model loading, audio encoding |
| `schemas.py` | Pydantic request/response models only | Logic, imports from other app modules |
| `service.py` | KokoClone wrapper, TTS generation, OGG encoding | HTTP concerns, FastAPI dependencies |
| `preprocessing.py` | pt-BR text normalization: numbers, currency, dates, times, chunking | HTTP concerns, TTS generation, voice discovery |
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
    "hint": "Available voices: ['carlos']. Place WAV files (3-10s) in the /voices/ directory."
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
  "voices": ["carlos"],
  "uptime_seconds": 3600,
  "memory_mb": 2048,
  "workers": 2,
  "version": "1.0.0"
}
```

Rules:
- `status` is an enum: `healthy`, `warming_up`, `degraded`
- `voices` is always an array, never `null`
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
class CumadreError(Exception):
    status_code: int
    error_type: str
    hint: str

class VoiceNotFoundError(CumadreError):
    status_code = 404
    error_type = "not_found_error"

# Registered once in main.py via @app.exception_handler(CumadreError)
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
3. Override espeak-ng data path if ESPEAK_DATA_PATH is set (for updated pt-BR data)
4. Discover voices (log found/skipped files)
5. Load KokoClone model
6. Run warm-up inference (short dummy pt-BR text through full pipeline including preprocessing)
7. Set ready flag → health returns "healthy"
```

Rules:
- Each phase logs when it starts
- Failure at any phase = log CRIT + exit (don't start half-broken)
- Health returns 503 / `warming_up` until step 6 completes

**Request Processing:**

```
1. Auth check (dependency injection)
2. Validate request body (Pydantic — automatic)
3. Resolve voice (voices module)
4. Preprocess text for pt-BR (preprocessing module — numbers, currency, dates, chunking)
5. Generate TTS for each chunk (service module — espeak-ng → Kokoro → Kanade)
6. Concatenate audio chunks
7. Encode to requested format (service module — WAV or OGG via ffmpeg)
8. Return binary response
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
    default_voice: str = "default"
    workers: int = 1
    port: int = 8000
    espeak_data_path: str | None = None  # Override bundled espeak-ng data for pt-BR quality
```

**Anti-pattern:**
```python
# DON'T DO THIS — scattered os.environ calls
voice = os.environ.get("DEFAULT_VOICE", "default")  # Wrong: use Settings
```

## Project Structure & Boundaries

### Complete Project Directory Structure

```
cumadre/
├── .github/
│   └── workflows/
│       └── ci.yml                    # GitHub Actions: lint + test + docker build
├── src/
│   └── cumadre/
│       ├── __init__.py               # Package init, __version__
│       ├── main.py                   # FastAPI app, lifespan, router mounting
│       ├── api.py                    # POST /v1/audio/speech route handler
│       ├── schemas.py                # SpeechRequest, HealthResponse, ErrorResponse
│       ├── service.py                # KokoClone wrapper, TTS + voice cloning + OGG encoding
│       ├── preprocessing.py          # pt-BR text normalization + sentence chunking
│       ├── config.py                 # Settings(BaseSettings) — all env vars
│       ├── exceptions.py             # CumadreError hierarchy + exception handlers
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
│  ├── /v1/audio/speech (api) │ ◄── Bearer token auth (dependency)
│  └── /health (health)       │ ◄── No auth
└──────────┬──────────────────┘
           │
     ┌─────▼─────┐
     │ service.py │ ◄── Business logic boundary
     │  KokoClone │
     │  ffmpeg    │
     └─────┬─────┘
           │
    ┌──────▼──────┐
    │  voices.py  │ ◄── Filesystem boundary (reads /voices/ volume)
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
│  │  cumadre-service                          │  │
│  │  ├── Uvicorn (N workers)                  │  │
│  │  ├── Port 8000 (mapped)                   │  │
│  │  │                                        │  │
│  │  │  Volumes:                              │  │
│  │  │  ├── cumadre-voices:/voices (ro)       │  │
│  │  │  └── cumadre-models:/models (rw)       │  │
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
│ cumadre/     │   Ansible SSH      │ ~/cumadre/           │
│ deploy/      │ ──────────────►    │   Dockerfile         │
│  ansible/    │  (as VPS user)     │   compose.yaml       │
│  playbooks/  │                    │   src/               │
│              │                    │   voices/            │
│ voices/*.wav │ ──── copy ────►    │   voices/*.wav       │
└──────────────┘                    └──────────────────────┘

All project files live in ~/cumadre (user home directory).
No files in /opt, /tmp, /src, /bin, or any system directory.
```

**Ansible Privilege Model:**

| Playbook | Privilege | Scope |
|---|---|---|
| `bootstrap.yml` | `become: true` for apt tasks only | Install Docker, add user to docker group (Debian 13 apt) |
| `bootstrap.yml` | Unprivileged for everything else | Clone repo to ~/cumadre, copy voices, docker compose up |
| `update.yml` | Unprivileged | git pull in ~/cumadre, docker compose build + restart |
| `cleanup.yml` | Unprivileged | docker compose down, rm -rf ~/cumadre |
| `health.yml` | Unprivileged | curl health endpoint, docker stats |

**Critical rule:** After bootstrap installs system packages and adds the user to the `docker` group, all subsequent operations run without privilege escalation. The daily restart cron is a user-level crontab entry, not a system cron.

### Requirements to Structure Mapping

**FR Category → Files:**

| FR Category | Primary File(s) | Supporting Files |
|---|---|---|
| Audio Generation (FR1-FR5) | `service.py`, `preprocessing.py` | `voices.py`, `config.py` |
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
| Memory leak mitigation | `compose.yaml` (resource limits), `health.py` (memory reporting), `bootstrap.yml` (user crontab setup) |
| Startup readiness | `main.py` (lifespan), `health.py` (503 gating), `compose.yaml` (healthcheck start_period) |

### Data Flow

```
n8n POST /v1/audio/speech
    │
    ▼
api.py: validate request (Pydantic) → verify auth (dependency)
    │
    ▼
service.py: resolve voice
    │
    ▼
preprocessing.py: normalize text for pt-BR
    ├── num2words: numbers, currency (R$), ordinals
    ├── custom: dates, times, domain abbreviations
    └── chunking: split into sentences (100-200 tokens each)
    │
    ▼ (for each chunk)
service.py: KokoClone.generate(normalized_text, lang, ref_wav)
    │                              │
    │                    ┌─────────▼──────────────────┐
    │                    │ espeak-ng (updated PR #2344) │
    │                    │ → pt-BR phonemes (IPA)       │
    │                    │                              │
    │                    │ Kokoro TTS (ONNX, int8)      │
    │                    │ → raw speech audio            │
    │                    │                              │
    │                    │ Kanade voice clone            │
    │                    │ → cloned audio (24kHz)        │
    │                    └─────────┬────────────────────┘
    │                              │
    ▼                              ▼
service.py: concatenate chunks → if ogg → ffmpeg subprocess → OGG bytes
                                : if wav → raw WAV bytes
    │
    ▼
api.py: return Response(content=audio_bytes, media_type="audio/wav|ogg")
    │
    ▼
n8n receives binary audio → sends to WhatsApp/Telegram
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

- **28/28 functional requirements** have explicit architectural support
- **All non-functional requirements** addressed (latency, memory, uptime, security, data preservation)
- **All cross-cutting concerns** mapped to specific files and patterns

### Implementation Readiness

- All modules defined with clear responsibilities and "must NOT contain" boundaries
- Import dependency graph prevents circular imports
- Error handling, startup, and request processing patterns fully specified with examples
- Test strategy proportional to codebase size
- Quality tooling covers Python, Dockerfile, YAML, Ansible, shell, and Markdown
- Dependency update workflow documented (including KokoClone git dependency)

### Architecture Completeness Checklist

**Requirements Analysis**

- [x] Project context analyzed — 28 FRs across 7 categories
- [x] Scale assessed — Low complexity, single-purpose API backend
- [x] Technical constraints identified — KokoClone not on PyPI, memory leak (fixed upstream), espeak-ng/ffmpeg deps
- [x] Cross-cutting concerns mapped — memory, persistence, readiness, errors, logging

**Architectural Decisions**

- [x] 8 critical/important decisions documented with rationale
- [x] Technology stack fully specified — Python 3.12, FastAPI, uv, Docker, Ansible
- [x] Integration approach defined — uv git dependency for KokoClone
- [x] Performance approach defined — Uvicorn workers, warm-up, resource limits

**Implementation Patterns**

- [x] Naming conventions — Python, API, env vars, files
- [x] Structure patterns — module responsibilities, import graph, test organization
- [x] Format patterns — API responses, errors, health, logs
- [x] Process patterns — error handling, startup, request flow

**Project Structure**

- [x] Complete directory tree with every file annotated
- [x] Architectural boundaries diagrammed — API, container, deployment
- [x] FR-to-file mapping complete
- [x] Deployment model defined — ~/cumadre, unprivileged except bootstrap apt

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION

**Confidence Level:** High

**Key Strengths:**

- Extremely focused scope — single endpoint, single consumer, ~150 lines of core code
- All ML complexity delegated to KokoClone — architecture only manages the wrapper
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
- All errors via CumadreError subclasses, never raw HTTPException
- All logging via structured logger, never print()
- All project files on VPS live in ~/cumadre — never in /opt, /tmp, or system directories
- Ansible uses `become: true` only for apt tasks in bootstrap — everything else unprivileged

**First Implementation Priority:**

```bash
uv init --package cumadre
```

Then configure pyproject.toml with all tool settings and quality tooling.
