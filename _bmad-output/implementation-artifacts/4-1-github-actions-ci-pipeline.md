# Story 4.1: GitHub Actions CI Pipeline

Status: done

## Story

As a developer,
I want automated quality checks on every push and pull request,
so that code quality, type safety, tests, and Docker build are validated before merging.

## Acceptance Criteria

1. **Given** `.github/workflows/ci.yml` exists, **When** I push code or open a pull request, **Then** GitHub Actions runs: pre-commit (ruff, mypy, hadolint, yamllint, shellcheck, markdownlint), pytest, and `docker compose build`. **And** the Docker build step validates that espeak-ng compiles from source, pt_extra dictionary compiles, qwen3-tts-cli binary is placed, and noise WAV files are baked in.

2. **Given** any quality check fails, **When** I view the CI run, **Then** the failing step is clearly identified with actionable output.

3. **Given** all checks pass, **When** the CI run completes, **Then** the pipeline reports success and the PR is safe to merge.

4. **Given** the Docker build step in CI, **When** it builds the image, **Then** the build succeeds despite the complexity of espeak-ng from source compilation, dual-engine binary assets, and pt_extra dictionary compilation.

## Tasks / Subtasks

- [x] Task 1: Create `.github/workflows/ci.yml` (AC: 1, 2, 3, 4)
  - [x] 1.1 Define workflow triggers (push to master, pull_request)
  - [x] 1.2 Implement lint job: install uv, sync dev deps, run `pre-commit run --all-files`
  - [x] 1.3 Implement test job: install uv, sync dev deps, run `uv run pytest`
  - [x] 1.4 Implement build job: `docker compose build` (validates full Dockerfile chain)
  - [x] 1.5 Verify all three jobs report clear, actionable failure output on error

## Dev Notes

### Architecture Constraints

- **Single workflow file:** `.github/workflows/ci.yml` — architecture decision D8
- **Three-stage pipeline:** lint → test → build (test and build can run in parallel after lint)
- **Tool chain is already configured** — all linter configs, pyproject.toml sections, and `.pre-commit-config.yaml` exist and pass locally. CI just runs them in GitHub Actions.
- **No deployment step** — CI validates only; deployment is via Ansible (Epic 3)

### Pre-Commit Handles ALL Linting

The project already runs all quality tools through `pre-commit run --all-files`. The CI lint job does NOT need to invoke each linter individually — just install pre-commit and run it. This covers:

| Hook | Tool | Config |
|------|------|--------|
| ruff-check | ruff v0.15.7 | pyproject.toml `[tool.ruff]` |
| ruff-format | ruff v0.15.7 | pyproject.toml `[tool.ruff]` |
| mypy | mypy (local hook via `uv run mypy src/`) | pyproject.toml `[tool.mypy]` strict + pydantic plugin |
| hadolint-docker | hadolint v2.12.0 | .hadolint.yaml (ignores DL3008, DL3013, DL3059) |
| yamllint | yamllint v1.37.1 | .yamllint.yaml (excludes `_bmad-output/`, `_bmad/`, `.claude/`) |
| shellcheck | shellcheck v0.10.0.1 | via pre-commit |
| markdownlint-cli2 | markdownlint v0.17.2 | .markdownlint.yaml (excludes `_bmad-output/`, `_bmad/`, `docs/`, `.claude/`) |

**Critical:** The mypy hook is a `repo: local` hook that runs `uv run mypy src/`. This requires uv and the project's dev dependencies to be installed BEFORE pre-commit runs.

### CI Environment Requirements

**Lint job:**
1. Python 3.12
2. Install uv (use `astral-sh/setup-uv` action)
3. `uv sync` (installs all dev deps including mypy, ruff, pre-commit)
4. `uv run pre-commit run --all-files`

**Why uv sync before pre-commit:** The mypy hook is `repo: local` with `entry: uv run mypy` — it needs the project venv with mypy and pydantic plugin installed. Without it, mypy fails.

**Test job:**
1. Python 3.12
2. Install uv
3. `uv sync`
4. `uv run pytest` (373 tests, all mocked — no models, no Docker, no network needed)

**Build job:**
1. Docker (available by default on `ubuntu-latest` runners)
2. `docker compose build` — validates the entire Dockerfile chain

### Docker Build Complexity — What CI Validates

The Dockerfile is a single-stage build with significant compilation steps. The `docker compose build` step in CI validates that ALL of these succeed:

1. **espeak-ng from source** — `git clone` → `autogen.sh` → `configure` → `make` → `make install`
2. **pt_extra dictionary compilation** — `COPY deploy/espeak-ng/pt_extra` → `espeak-ng --compile=pt`
3. **uv dependency install** — `uv sync --frozen --no-dev` (requires `uv.lock` committed)
4. **misaki espeak data patching** — copies compiled pt_dict to espeakng_loader bundled path
5. **qwen3-tts-cli binary** — `COPY deploy/bin/qwen3-tts-cli` (600 KB, tracked in git)
6. **Noise WAV files** — `COPY noise/` (hiss.wav + room.wav, tracked in git)
7. **Entrypoint** — `COPY scripts/entrypoint.sh`

All Docker build dependencies are committed to git. No external downloads needed beyond the base image and espeak-ng git clone.

**Build time warning:** The espeak-ng compilation makes Docker build slow (~3-5 min). Consider caching the Docker layer. GitHub Actions `docker/build-push-action` with cache-to/cache-from can help, but is NOT required for AC compliance — a plain `docker compose build` satisfies the acceptance criteria.

### Workflow Triggers

```yaml
on:
  push:
    branches: [master]
  pull_request:
    branches: [master]
```

The project uses `master` as the main branch (not `main`).

### Job Dependencies

Recommended structure:
- **lint** runs first (fastest feedback)
- **test** runs after lint passes (or in parallel — developer choice)
- **build** runs after lint passes (or in parallel — Docker build is independent of Python tests)

Making test and build depend on lint (`needs: [lint]`) saves runner minutes when lint fails. But parallel execution is also acceptable if faster feedback on all fronts is preferred.

### What NOT to Include

- **No deployment** — Ansible handles that (Epic 3)
- **No coverage upload** — coverage is installed but uploading to Codecov/etc. is not in scope
- **No integration tests** — `pytest -m slow` requires real models; skip in CI
- **No image push** — no container registry; images are built on the VPS via Ansible
- **No branch protection rules** — configuring GitHub branch protection is out of scope (can be done manually)
- **No ansible-lint step** — ansible-lint is NOT in `.pre-commit-config.yaml` and is not a dev dependency. It was mentioned in architecture but is not currently configured. Do NOT add it — that would be scope creep.

### Known Deferred Issues Affecting CI

These are pre-existing issues documented in `deferred-work.md`. CI may surface them, but they are NOT blockers and NOT in scope to fix:

- **Non-reproducible Docker build** — espeak-ng cloned from unpinned master. CI will rebuild from whatever master currently is. Known trade-off.
- **Dockerfile purges gcc/g++** — `apt-get autoremove` after purging build tools may remove libstdc++. If this happens, the Docker build succeeds but runtime fails. CI only builds, doesn't run the image.
- **COPY noise/ may be empty on fresh clone** — noise WAVs ARE tracked in git (verified), so CI checkout will have them. This deferred item is about scenarios where someone deletes them locally.

### Project Structure Notes

**File to create:**
```
.github/
└── workflows/
    └── ci.yml
```

This is the ONLY file to create. All quality tool configs already exist:
- `.pre-commit-config.yaml` — all hooks configured
- `.hadolint.yaml` — Dockerfile lint ignores
- `.yamllint.yaml` — YAML lint rules
- `.ansible-lint` — Ansible lint profile (not used in CI)
- `.markdownlint.yaml` — Markdown lint rules
- `pyproject.toml` — ruff, mypy, pytest configs

### References

- [Source: _bmad-output/planning-artifacts/architecture.md — Decision D8: GitHub Actions]
- [Source: _bmad-output/planning-artifacts/architecture.md — Code Quality Tooling table]
- [Source: _bmad-output/planning-artifacts/architecture.md — Project Structure — CI/CD Files]
- [Source: _bmad-output/planning-artifacts/epics.md — Epic 4, Story 4.1 acceptance criteria]
- [Source: .pre-commit-config.yaml — exact hook versions and configurations]
- [Source: pyproject.toml — dependency groups, tool configs]
- [Source: Dockerfile — full build chain to be validated]
- [Source: compose.yaml — `docker compose build` target]

### Previous Story Intelligence

**From Epic 3 (Stories 3.1–3.3):**
- All Ansible playbooks pass `yamllint` and `ansible-lint --profile production`
- Task naming convention: `[Component] Action description`
- Deploy patterns use Docker Compose v2 syntax (`docker compose`, not `docker-compose`)

**From Story 1.1 (Project Scaffolding):**
- Pre-commit was set up with all hooks from day one
- mypy uses `repo: local` hook pattern (runs via `uv run mypy src/`)
- This means CI must have uv + deps installed before pre-commit

**From Story 1.10 (Tests):**
- 373 tests pass, 11 skipped (slow-marked integration tests)
- All tests are mocked — no models, no network, no Docker needed
- Test runtime is fast (~5-10s)
- Uses `httpx.AsyncClient` with `ASGITransport` (not TestClient)

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

- yamllint validation: passed (no warnings)
- pre-commit run --all-files: all 7 hooks passed (ruff-check, ruff-format, hadolint, yamllint, shellcheck, markdownlint, mypy)
- pytest: 392 passed, 11 skipped, 2 pre-existing failures (subprocess mock issue in test_routing.py — unrelated to this story)

### Completion Notes List

- Created `.github/workflows/ci.yml` with three-stage pipeline: lint → test + build (parallel after lint)
- Lint job: checkout → setup-python 3.12 → setup-uv → uv sync → pre-commit run --all-files
- Test job: checkout → setup-python 3.12 → setup-uv → uv sync → uv run pytest (needs: lint)
- Build job: checkout → docker compose build (needs: lint)
- Test and build run in parallel after lint passes, saving runner time
- Each job uses separate steps for clear, actionable failure output (AC2)
- No scope creep: no deployment, no coverage upload, no integration tests, no ansible-lint, no branch protection
- Pre-existing test failures (2) in test_routing.py are subprocess mock issues, not regressions from this change

### File List

- `.github/workflows/ci.yml` (new)
- `tests/test_routing.py` (modified — fixed 2 broken subprocess mocks)

### Review Findings

- [x] [Review][Decision] Pre-existing test failures will make CI red from day one — 2 tests in test_routing.py (`test_qwen_calls_expand_siglas`, `test_qwen_uses_whatsapp_subtle_pipeline`) fail with `TypeError: catching classes that do not inherit from BaseException` at `service.py:630`. **Fixed:** patched `subprocess.run` instead of entire `subprocess` module, and added `patch.object` on `_build_command` to bypass `_model_path` assertion.
- [x] [Review][Defer] No uv dependency cache [ci.yml] — neither lint nor test jobs cache `~/.cache/uv`, adding ~30-60s per job per run. `astral-sh/setup-uv@v4` supports `cache: true`. — deferred, optimization
- [x] [Review][Defer] No pre-commit environment cache [ci.yml] — lint job does not cache `~/.cache/pre-commit`, rebuilding all hook environments every run (1-3 min overhead). — deferred, optimization
- [x] [Review][Defer] No Docker layer cache [ci.yml] — espeak-ng source compilation repeats every build job run (~3-5 min). `docker/build-push-action` with GHA cache backend would help. — deferred, optimization
- [x] [Review][Defer] No job timeout [ci.yml] — no `timeout-minutes` set; defaults to 360 min. A stuck build or test could consume CI minutes. — deferred, low risk
- [x] [Review][Defer] Unpinned espeak-ng master in Docker build [Dockerfile] — known pre-existing issue; non-reproducible Docker build. — deferred, pre-existing
- [x] [Review][Defer] Unset API_KEY warning in compose.yaml [compose.yaml] — `${API_KEY}` without default produces a warning in CI logs. Fix: `${API_KEY:-}`. — deferred, pre-existing

### Change Log

- 2026-03-25: Created GitHub Actions CI pipeline with lint/test/build jobs (Story 4.1)
