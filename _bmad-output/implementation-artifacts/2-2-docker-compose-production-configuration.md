# Story 2.2: Docker Compose & Production Configuration

Status: done

## Story

As a DevOps operator,
I want a compose.yaml that defines the complete production runtime,
so that `docker compose up` starts a properly configured, resource-limited service.

## Acceptance Criteria

1. **Given** compose.yaml, **When** I run `docker compose up`, **Then** the tts-service starts with three named volumes: `cumadre-models:/models:rw`, `cumadre-voices:/voices:ro`, `cumadre-audio:/audio:rw`.

2. **Given** compose.yaml environment variables, **When** I inspect the service definition, **Then** it defines `API_KEY` (from host env or .env), `DEFAULT_VOICE` (default: santa), `CLONE_REFERENCE_PATH` (path to clone reference WAV inside container), and `ESPEAK_DATA_PATH` (system espeak-ng data path). There is NO `WORKERS` env var — single-process architecture enforced.

3. **Given** compose.yaml resource limits, **When** the container is running, **Then** it is constrained to `cpus: 4` and `memory: 6G`.

4. **Given** compose.yaml restart policy, **When** the container crashes or host reboots, **Then** Docker automatically restarts it (`restart: unless-stopped`).

5. **Given** compose.yaml health check, **When** the container starts, **Then** Docker polls `GET /health` with `start_period: 120s` to accommodate dual-engine model download and warm-up. Container is marked healthy only when health endpoint returns 200.

6. **Given** the container is running with cached models, **When** I inspect outbound network traffic, **Then** zero outbound connections are made.

7. **Given** the cumadre-audio volume, **When** TTS requests are processed, **Then** generated audio files are written to the audio volume (periodic cleanup configured by Ansible in Epic 3).

## Tasks / Subtasks

- [x] Task 1: Dockerfile update for /voices mount point (AC: #1)
  - [x] 1.1: Add `/voices` to the `mkdir -p` and `chown` line in the Dockerfile
- [x] Task 2: Create compose.yaml (AC: #1, #2, #3, #4, #5)
  - [x] 2.1: Define tts-service with `build: .` context
  - [x] 2.2: Define three named volumes at bottom of file
  - [x] 2.3: Mount volumes with correct access modes
  - [x] 2.4: Define environment variables with model path overrides
  - [x] 2.5: Set resource limits under `deploy.resources.limits`
  - [x] 2.6: Set `restart: unless-stopped`
  - [x] 2.7: Configure healthcheck with start_period
  - [x] 2.8: Map port 8000
  - [x] 2.9: Set container_name: tts-service
- [x] Task 3: Validate compose.yaml (AC: all)
  - [x] 3.1: Run `docker compose config` to validate syntax
  - [x] 3.2: Run yamllint if configured
- [x] Task 4: Update .env.example if needed (AC: #2)
  - [x] 4.1: Ensure all compose.yaml env vars are documented
- [x] Task 5: Quality gates (AC: all)
  - [x] 5.1: hadolint passes on updated Dockerfile
  - [x] 5.2: All existing tests still pass (`uv run pytest`)

## Dev Notes

### Critical: Model Path Override

The config defaults use **relative paths** (e.g., `models/kokoro-v1.0.onnx`), which resolve from WORKDIR `/app` to `/app/models/`. But the volume mounts at `/models` (root level). The compose.yaml **MUST** set absolute model paths via environment variables:

```yaml
environment:
  KOKORO_MODEL_PATH: /models/kokoro-v1.0.onnx
  KOKORO_VOICES_PATH: /models/voices-v1.0.bin
  QWEN3_MODEL_PATH: /models/qwen3-tts-0.6b-q8_0.gguf
  QWEN3_TOKENIZER_PATH: /models/qwen3-tts-tokenizer-f16.gguf
```

Without this, models download to `/app/models/` (ephemeral) instead of `/models/` (volume-backed). This is the #1 disaster to prevent.

Similarly, voice reference paths must point to the volume:

```yaml
  QWEN3_FEMALE_REFERENCE_PATH: /voices/female-reference.wav
  QWEN3_MALE_REFERENCE_PATH: /voices/male-reference.wav
  # CLONE_REFERENCE_PATH: /voices/audio-referencia-01.wav  # uncomment when clone WAV is provided
```

### Critical: Dockerfile Missing /voices

The current Dockerfile (line 77-79) creates `/models` and `/audio` but **NOT** `/voices`:
```dockerfile
RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /models /audio && \
    chown -R appuser:appuser /app /models /audio
```

Must add `/voices` so the mount point exists with correct ownership:
```dockerfile
RUN useradd --create-home --shell /bin/bash appuser && \
    mkdir -p /models /audio /voices && \
    chown -R appuser:appuser /app /models /audio /voices
```

Without this, the `:ro` volume mount at `/voices` will be owned by root. Since the container runs as `appuser`, reads may fail depending on host file permissions.

### Environment Variables — Complete List

From `src/cumadre/config.py` Settings class, these are the env vars compose.yaml should define:

| Variable | compose.yaml Value | Rationale |
|---|---|---|
| `API_KEY` | `${API_KEY}` (from .env) | Auth token — operator sets in .env |
| `DEFAULT_VOICE` | `santa` | Architecture default |
| `PORT` | `8000` | Match EXPOSE and entrypoint default |
| `ESPEAK_DATA_PATH` | `/usr/local/share/espeak-ng-data` | System path where pt_extra was compiled |
| `NOISE_DIR` | `/app/noise` | Already baked into image (Story 2.1) |
| `KOKORO_MODEL_PATH` | `/models/kokoro-v1.0.onnx` | Volume-backed absolute path |
| `KOKORO_VOICES_PATH` | `/models/voices-v1.0.bin` | Volume-backed absolute path |
| `QWEN3_MODEL_PATH` | `/models/qwen3-tts-0.6b-q8_0.gguf` | Volume-backed absolute path |
| `QWEN3_TOKENIZER_PATH` | `/models/qwen3-tts-tokenizer-f16.gguf` | Volume-backed absolute path |
| `QWEN3_CLI_PATH` | `/usr/local/bin/qwen3-tts-cli` | Already the config default |
| `QWEN3_THREADS` | `4` | Architecture sweet spot (D3) |
| `QWEN3_FEMALE_REFERENCE_PATH` | `/voices/female-reference.wav` | Volume-backed |
| `QWEN3_MALE_REFERENCE_PATH` | `/voices/male-reference.wav` | Volume-backed |

`CLONE_REFERENCE_PATH` should be commented out or omitted — operator adds it when a clone WAV is placed in the voices volume.

**DO NOT** add a `WORKERS` env var. Single-process architecture is enforced by the entrypoint (no `--workers` flag).

### Healthcheck Configuration

The health endpoint at `GET /health` returns:
- **503** during warm-up (engines loading/downloading models)
- **200** when ready

Docker healthcheck must accommodate:
- First-run model download (~2 GB): can take minutes on slow connections
- Dual-engine warm-up: Kokoro model load + Qwen3 binary verification

```yaml
healthcheck:
  test: ["CMD", "curl", "-sf", "http://localhost:8000/health"]
  interval: 30s
  timeout: 10s
  retries: 3
  start_period: 120s
```

`start_period: 120s` means Docker ignores health failures for the first 2 minutes. Note: `curl` must be available in the image — `python:3.12-slim` includes it? **Verify.** If not, use a Python-based healthcheck or install curl in the Dockerfile.

**Alternative healthcheck without curl** (safer):
```yaml
test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
```

### Volume Strategy

| Volume | Mount | Mode | Contents |
|---|---|---|---|
| `cumadre-models` | `/models` | `rw` | Kokoro ONNX (~325 MB), voices (~27 MB), Qwen3 GGUF (~1.3 GB), tokenizer (~341 MB) |
| `cumadre-voices` | `/voices` | `ro` | Operator-provisioned reference WAV files for voice cloning |
| `cumadre-audio` | `/audio` | `rw` | Generated audio files (accumulate, cleaned by cron in Epic 3) |

### Resource Limits

Architecture decision D3 + feasibility study:
- `cpus: 4` — Qwen3 sweet spot, diminishing returns beyond 4 cores
- `memory: 6G` — both engines loaded simultaneously (~4-6 GB measured)

Use `deploy.resources.limits` in compose.yaml (Compose v2 syntax):

```yaml
deploy:
  resources:
    limits:
      cpus: "4"
      memory: 6G
```

### compose.yaml Target Structure

```yaml
services:
  tts-service:
    build: .
    container_name: tts-service
    restart: unless-stopped
    ports:
      - "${PORT:-8000}:8000"
    volumes:
      - cumadre-models:/models:rw
      - cumadre-voices:/voices:ro
      - cumadre-audio:/audio:rw
    environment:
      API_KEY: ${API_KEY}
      DEFAULT_VOICE: santa
      PORT: "8000"
      ESPEAK_DATA_PATH: /usr/local/share/espeak-ng-data
      NOISE_DIR: /app/noise
      KOKORO_MODEL_PATH: /models/kokoro-v1.0.onnx
      KOKORO_VOICES_PATH: /models/voices-v1.0.bin
      QWEN3_MODEL_PATH: /models/qwen3-tts-0.6b-q8_0.gguf
      QWEN3_TOKENIZER_PATH: /models/qwen3-tts-tokenizer-f16.gguf
      QWEN3_CLI_PATH: /usr/local/bin/qwen3-tts-cli
      QWEN3_THREADS: "4"
      QWEN3_FEMALE_REFERENCE_PATH: /voices/female-reference.wav
      QWEN3_MALE_REFERENCE_PATH: /voices/male-reference.wav
    deploy:
      resources:
        limits:
          cpus: "4"
          memory: 6G
    healthcheck:
      test: ["CMD", "python", "-c", "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"]
      interval: 30s
      timeout: 10s
      retries: 3
      start_period: 120s

volumes:
  cumadre-models:
  cumadre-voices:
  cumadre-audio:
```

### Anti-Patterns to Avoid

- **DO NOT** add `WORKERS` env var or `--workers` flag anywhere — single-process is architectural
- **DO NOT** use `docker-compose` v1 syntax — use `docker compose` v2
- **DO NOT** use relative model paths — volumes mount at root-level absolute paths
- **DO NOT** use `restart: always` — `unless-stopped` allows intentional stops
- **DO NOT** hardcode API_KEY in compose.yaml — reference from .env via `${API_KEY}`
- **DO NOT** set `privileged: true` or add unnecessary capabilities
- **DO NOT** use `docker-compose.yml` filename — use `compose.yaml` per architecture spec

### Previous Story Intelligence (2.1)

Story 2.1 created the Dockerfile and entrypoint. Key learnings:
- Non-root `appuser` is used — all volume mount points need `chown appuser:appuser`
- Entrypoint uses `exec uvicorn cumadre.main:create_app --factory --host 0.0.0.0 --port "${PORT:-8000}"`
- Build deps are cleaned up — image is production-ready
- Model download uses urllib (no extra deps) — writes to `Path(model_path)` so absolute paths are critical
- Noise WAVs baked in at `/app/noise/` — no volume needed for noise
- Review found: workers field removed from config (contradicts single-process)

### Git Intelligence

Recent commit patterns:
- Commit messages follow: "Implement Story X.Y: <description>"
- Tests are comprehensive (394 tests passing as of Story 1.10)
- Quality gates: ruff, mypy strict, hadolint, shellcheck all clean
- Story 2.1 added: Dockerfile, entrypoint.sh, download.py, noise WAVs, test_download.py

### curl Availability Check

`python:3.12-slim` does **not** include `curl`. Two options:
1. Add `curl` to Dockerfile apt-get install (adds ~7 MB)
2. Use Python-based healthcheck: `python -c "import urllib.request; urllib.request.urlopen('http://localhost:8000/health')"`

Option 2 is preferred — zero image size impact, Python is already available.

### Project Structure Notes

- `compose.yaml` goes in project root (same level as Dockerfile) per architecture spec
- File must be named `compose.yaml` (not `docker-compose.yml`)
- Architecture file at `_bmad-output/planning-artifacts/architecture.md` lines 813-814 confirms this

### References

- [Source: _bmad-output/planning-artifacts/epics.md — Epic 2, Story 2.2 acceptance criteria]
- [Source: _bmad-output/planning-artifacts/architecture.md — D5 (Docker build), Container Boundary diagram (lines 865-893)]
- [Source: _bmad-output/planning-artifacts/architecture.md — Resource limits, volume strategy (lines 878-882)]
- [Source: _bmad-output/planning-artifacts/prd.md — FR17-FR21, FR27-FR28]
- [Source: _bmad-output/implementation-artifacts/2-1-dockerfile-entrypoint.md — Dockerfile structure, review findings]
- [Source: src/cumadre/config.py — Settings class with all env vars and defaults]
- [Source: src/cumadre/download.py — Model download uses Path(model_path), confirms absolute path requirement]
- [Source: Dockerfile — Lines 77-79, /voices mount point missing]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

- hadolint: DL3008 warning (pin apt versions) is pre-existing from Story 2.1, not introduced here
- `docker compose config` validated cleanly with all env vars, volumes, and resource limits
- 394 tests pass, 11 skipped (integration), zero regressions

### Completion Notes List

- Task 1: Added `/voices` to Dockerfile `mkdir -p` and `chown` (line 78-79) so the volume mount point exists with correct ownership for `appuser`
- Task 2: Created `compose.yaml` matching the target structure from Dev Notes exactly. Used Python-based healthcheck (no curl in slim image). All 14 env vars defined with absolute model/voice paths pointing to volume mounts. Resource limits set to 4 CPUs / 6G memory per architecture D3. No WORKERS env var (single-process enforced).
- Task 3: `docker compose config` validates cleanly. yamllint not configured in project — skipped.
- Task 4: Fixed `DEFAULT_VOICE=default` to `DEFAULT_VOICE=santa` in .env.example to match config.py and compose.yaml defaults. All compose.yaml env vars already documented.
- Task 5: hadolint passes (only pre-existing DL3008 warning). All 394 existing tests pass.

### Change Log

- 2026-03-24: Story 2.2 implementation complete — compose.yaml created, Dockerfile updated for /voices, .env.example fixed

### File List

- `Dockerfile` (modified — added /voices to mkdir and chown)
- `compose.yaml` (new — production Docker Compose configuration)
- `.env.example` (modified — fixed DEFAULT_VOICE from "default" to "santa")

### Review Findings

- [x] [Review][Decision] CLONE_REFERENCE_PATH not defined in compose.yaml — resolved: added as YAML comment per user choice
- [x] [Review][Patch] Entrypoint cannot find uvicorn — PATH not set for .venv [scripts/entrypoint.sh:4, Dockerfile] — fixed: added ENV PATH to Dockerfile
- [x] [Review][Patch] No timeout on urlretrieve — download hangs indefinitely on network issues [src/cumadre/download.py:23] — fixed: replaced urlretrieve with urlopen(timeout=300) + shutil.copyfileobj
- [x] [Review][Patch] ensure_kokoro_models skips individual download when OTHER URL is empty — OR guard should be per-file [src/cumadre/download.py:46] — fixed: extracted _ensure_file() for per-file URL check
- [x] [Review][Defer] Download failure crashes startup with no retry or backoff [src/cumadre/main.py:49-60] — deferred, design trade-off for container workloads
- [x] [Review][Defer] Empty cumadre-voices volume causes Qwen3 failure on first run [compose.yaml:10] — deferred, deployment concern (operator must pre-populate)
- [x] [Review][Defer] No URL scheme validation on download URLs [src/cumadre/config.py:65-86] — deferred, operator-controlled config
- [x] [Review][Defer] Dockerfile installs libsndfile1-dev instead of runtime libsndfile1 [Dockerfile:7] — deferred, pre-existing from Story 2.1
- [x] [Review][Defer] Stale .tmp file with wrong ownership blocks subsequent downloads [src/cumadre/download.py:23-29] — deferred, unlikely edge case
- [x] [Review][Defer] Healthcheck start_period may be insufficient for large downloads on slow connections [compose.yaml:35] — deferred, operator can tune
- [x] [Review][Defer] Non-reproducible Docker build — espeak-ng cloned from unpinned master [Dockerfile:19] — deferred, pre-existing from Story 2.1
- [x] [Review][Defer] Default voice set to Qwen3 bypasses schema char limit validation — deferred, pre-existing design issue
- [x] [Review][Defer] COPY deploy/bin/qwen3-tts-cli fails if binary not present [Dockerfile:66] — deferred, pre-existing from Story 2.1
