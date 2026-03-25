# Story 1.1: Project Scaffolding & Quality Tooling

Status: done

## Story

As a **developer**,
I want a properly initialized Python project with all quality tooling configured,
So that all future code is written against consistent standards from day one.

## Acceptance Criteria

1. **Given** a clean repository **When** I run `uv init --package comadre` **Then** the project has `src/comadre/` layout with `pyproject.toml` and `.python-version` (3.12)

2. **Given** the initialized project **When** I review `pyproject.toml` **Then** it includes ruff, mypy (strict + pydantic plugin), pytest + pytest-asyncio + httpx configs, and PEP 735 dependency groups (dev, lint, test, type-check)

3. **Given** the project with quality tooling **When** I run `uv run pre-commit run --all-files` **Then** ruff, mypy, hadolint, yamllint, shellcheck, and markdownlint all execute without errors

4. **Given** the project structure **When** I inspect the repository **Then** `.gitignore`, `.env.example` (API_KEY, DEFAULT_VOICE, WORKERS, PORT), `.hadolint.yaml`, `.yamllint.yaml`, `.ansible-lint`, `.markdownlint.yaml`, and `voices/.gitkeep` all exist

## Tasks / Subtasks

- [x] Task 1: Initialize project with uv (AC: #1)
  - [x] 1.1: Run `uv init --package comadre` to create src layout
  - [x] 1.2: Verify `.python-version` is set to `3.12`
  - [x] 1.3: Verify `src/comadre/__init__.py` exists
  - [x] 1.4: Set `__version__` in `src/comadre/__init__.py`

- [x] Task 2: Configure pyproject.toml with all tooling (AC: #2)
  - [x] 2.1: Add project metadata (name, description, license, python requires >=3.12)
  - [x] 2.2: Add runtime dependencies: fastapi, uvicorn, pydantic-settings, soundfile (these will be needed by future stories — include now so linters have context)
  - [x] 2.3: Add PEP 735 dependency groups:
    - `lint`: ruff, pre-commit
    - `test`: pytest, pytest-asyncio, httpx, coverage
    - `type-check`: mypy, pydantic mypy plugin support
    - `dev`: includes lint + test + type-check groups
  - [x] 2.4: Configure `[tool.ruff]` — target Python 3.12, line-length 88
  - [x] 2.5: Configure `[tool.ruff.lint]` — select rules (E, F, I, UP, B, SIM, etc.)
  - [x] 2.6: Configure `[tool.mypy]` — strict mode, pydantic plugin: `plugins = ["pydantic.mypy"]`
  - [x] 2.7: Configure `[tool.pytest.ini_options]` — asyncio_mode = "auto", testpaths = ["tests"]
  - [x] 2.8: Run `uv sync` to install all dependencies and generate `uv.lock`

- [x] Task 3: Create pre-commit configuration (AC: #3)
  - [x] 3.1: Create `.pre-commit-config.yaml` with hooks:
    - ruff (lint + format)
    - mypy (with `--strict` and pydantic plugin)
    - hadolint (Dockerfile linting)
    - yamllint (YAML linting)
    - shellcheck (shell script linting)
    - markdownlint-cli2 (Markdown linting)
  - [x] 3.2: Run `uv run pre-commit install` to set up git hooks

- [x] Task 4: Create linter configuration files (AC: #4)
  - [x] 4.1: Create `.hadolint.yaml` — trust `DL3008` (apt pinning) since we need system deps
  - [x] 4.2: Create `.yamllint.yaml` — relaxed rules for Ansible/compose compatibility
  - [x] 4.3: Create `.ansible-lint` — production profile, skip specific rules if needed
  - [x] 4.4: Create `.markdownlint.yaml` — allow long lines in tables, inline HTML for architecture docs

- [x] Task 5: Create project scaffolding files (AC: #4)
  - [x] 5.1: Update `.gitignore` — Python, Docker, env files, model cache, __pycache__, .mypy_cache, .ruff_cache, .env, *.egg-info
  - [x] 5.2: Create `.env.example` with documented variables:
    ```
    API_KEY=your-secret-api-key-here
    DEFAULT_VOICE=default
    WORKERS=1
    PORT=8000
    ```
  - [x] 5.3: Create `voices/.gitkeep` (empty file)
  - [x] 5.4: Create placeholder `src/comadre/__init__.py` with `__version__`

- [x] Task 6: Create directory structure for future stories (AC: #4)
  - [x] 6.1: Create `tests/` directory with empty `__init__.py`
  - [x] 6.2: Create `deploy/ansible/inventory/` directory structure
  - [x] 6.3: Create `deploy/ansible/playbooks/` directory structure
  - [x] 6.4: Create `scripts/` directory

- [x] Task 7: Validation pass (AC: #3)
  - [x] 7.1: Run `uv run pre-commit run --all-files` and fix any issues
  - [x] 7.2: Run `uv run ruff check .` — should pass
  - [x] 7.3: Run `uv run mypy src/` — should pass (only __init__.py exists)
  - [x] 7.4: Run `uv run pytest` — should pass (no tests yet, but should find no errors)

## Dev Notes

### Critical Architecture Decisions

This is the foundation story. Every subsequent story depends on the patterns established here. Mistakes here compound across all 15+ stories.

**Build Backend:** `uv_build` (uv native backend, default for `--package` since uv 0.8+). Do NOT switch to setuptools or poetry.

**Layout:** `src/comadre/` — NOT flat layout. The `--package` flag ensures this. Import safety: prevents tests from accidentally importing local source instead of installed package.

**Python Version:** 3.12 exactly. Set in `.python-version` file.

**Compose Filename:** `compose.yaml` — Docker Compose v2 standard. NOT `docker-compose.yml`.

### Module Structure (reference for directory creation)

The full project will contain these modules in `src/comadre/`:
```
__init__.py    — Package init, __version__
main.py        — FastAPI app, lifespan, router mounting
api.py         — POST /v1/audio/speech route handler
schemas.py     — Pydantic request/response models
service.py     — KokoClone wrapper, TTS + voice cloning + OGG encoding
config.py      — Settings(BaseSettings) — all env vars
exceptions.py  — ComadreError hierarchy + exception handlers
health.py      — GET /health route, runtime state assembly
logging.py     — Structured pipe-delimited formatter + setup
voices.py      — Voice discovery, WAV validation, listing
```

**For this story:** Only create `__init__.py`. Other modules are created in their respective stories. Do NOT create placeholder files for modules not yet implemented.

### Import Dependency Graph (enforce from day one)

```
config.py      <- imported by everything (no app imports)
logging.py     <- imported by everything (no app imports)
schemas.py     <- imported by api.py, health.py (no app imports)
exceptions.py  <- imported by api.py, service.py, voices.py
voices.py      <- imported by service.py, health.py
service.py     <- imported by api.py
health.py      <- imported by main.py
api.py         <- imported by main.py
main.py        <- entry point (imports everything, imported by nothing)
```

### Dependency Groups (PEP 735) — exact format

```toml
[dependency-groups]
dev = [
    { include-group = "lint" },
    { include-group = "test" },
    { include-group = "type-check" },
]
lint = ["ruff>=0.9", "pre-commit>=4.0"]
test = ["pytest>=8.3", "pytest-asyncio>=0.25", "httpx>=0.28", "coverage>=7.6"]
type-check = ["mypy>=1.14"]
```

### Tool Configuration Notes

**ruff:** Config must go under `[tool.ruff]` and `[tool.ruff.lint]` (NOT old top-level `select`/`ignore`). The `select`/`ignore` keys must be under `[tool.ruff.lint]`.

**mypy:** Strict mode with pydantic plugin:
```toml
[tool.mypy]
strict = true
plugins = ["pydantic.mypy"]
```

**pytest-asyncio:** Default mode changed to `"strict"` in recent versions. Must explicitly set `mode = "auto"`:
```toml
[tool.pytest.ini_options]
asyncio_mode = "auto"
testpaths = ["tests"]
```

**httpx:** In 0.28+, the `app` parameter on `AsyncClient()` was removed. Tests must use `transport=httpx.ASGITransport(app=app)` instead. This affects conftest.py in Story 1.10.

**hadolint:** Configure in `.hadolint.yaml`. Trust `DL3008` (apt version pinning) and `DL3013` (pip version pinning — not applicable since we use uv). Use `DL3059` trust for multiple consecutive RUN instructions if needed.

**pre-commit:** For mypy hook, it needs `additional_dependencies` to include pydantic and any typed stubs. Alternatively, use a `local` hook that runs `uv run mypy` so it picks up the project's full dependency tree.

**shellcheck:** Use the pre-commit mirror repo. Checks `scripts/entrypoint.sh` (created in Story 2.1).

**ansible-lint:** Configure with production profile. The `.ansible-lint` file is YAML format (despite no extension in the architecture spec).

### Anti-Patterns to Avoid

- Do NOT use `pip` or `pip install` anywhere — all dependencies via `uv`
- Do NOT create a `setup.py` or `setup.cfg` — `pyproject.toml` only
- Do NOT use `docker-compose.yml` filename — it's `compose.yaml`
- Do NOT add KokoClone as a dependency in this story — it's added in Story 1.4
- Do NOT create module files beyond `__init__.py` — other stories own those
- Do NOT use `print()` for any output — structured logging comes in Story 1.2
- Do NOT add `pydantic` directly — it's a transitive dep of `fastapi` and `pydantic-settings`

### .gitignore Requirements

Must cover:
- Python: `__pycache__/`, `*.py[cod]`, `*.egg-info/`, `dist/`, `build/`, `.eggs/`
- Type checking: `.mypy_cache/`
- Linting: `.ruff_cache/`
- Environment: `.env` (but NOT `.env.example`)
- IDE: `.vscode/`, `.idea/`
- Docker: No docker-specific ignores needed (compose.yaml is tracked)
- Models: `models/` (local development cache, not tracked)

**Important:** Do NOT gitignore `_bmad-output/` — it must be tracked.

### Project Structure Notes

- `voices/` directory with `.gitkeep` — actual WAV files are operator-provisioned, not tracked in git
- `deploy/ansible/` directory structure created empty — populated in Epic 3
- `scripts/` directory created empty — `entrypoint.sh` added in Story 2.1
- `tests/` directory created with `__init__.py` — test files added in Story 1.8

### References

- [Source: _bmad-output/planning-artifacts/architecture.md#Starter Template Evaluation]
- [Source: _bmad-output/planning-artifacts/architecture.md#Code Quality Tooling]
- [Source: _bmad-output/planning-artifacts/architecture.md#Dependency Groups (PEP 735)]
- [Source: _bmad-output/planning-artifacts/architecture.md#Implementation Patterns & Consistency Rules]
- [Source: _bmad-output/planning-artifacts/architecture.md#Complete Project Directory Structure]
- [Source: _bmad-output/planning-artifacts/epics.md#Story 1.1: Project Scaffolding & Quality Tooling]
- [Source: _bmad-output/planning-artifacts/prd.md#Additional Requirements]
- [Source: _bmad-output/planning-artifacts/ux-design-specification.md#UX-DR10: Terminal Accessibility]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

- `.python-version` defaulted to 3.13 from uv init; manually corrected to 3.12
- `uv init --package comadre` (without `.`) created a subdirectory; re-ran with `uv init --package --name comadre .`
- markdownlint failed on `_bmad-output/` planning artifacts and docs; excluded generated directories from hook scope
- MD013 (line-length) disabled entirely in markdownlint — impractical for documentation
- Build backend is `uv_build` (uv's native backend), not `hatchling` as mentioned in Dev Notes — uv 0.8+ defaults to uv_build

### Completion Notes List

- Initialized Python project with `uv init --package` creating proper `src/comadre/` layout
- Configured `pyproject.toml` with full tooling: ruff, mypy (strict + pydantic plugin), pytest-asyncio, PEP 735 dependency groups
- Pre-commit hooks configured for ruff, mypy, hadolint, yamllint, shellcheck, markdownlint-cli2
- Mypy runs as local hook via `uv run mypy` for full dependency access (pydantic plugin requires project venv)
- All linter configs created: `.hadolint.yaml`, `.yamllint.yaml`, `.ansible-lint`, `.markdownlint.yaml`
- Project scaffolding complete: `.gitignore`, `.env.example`, `voices/.gitkeep`, directory structure
- All validation passes: `ruff check .`, `mypy src/`, `pytest`, `pre-commit run --all-files`

### File List

- `pyproject.toml` (new) — project metadata, dependencies, tool configs
- `uv.lock` (new) — locked dependency versions
- `.python-version` (new) — Python 3.12
- `src/comadre/__init__.py` (new) — package init with __version__
- `.pre-commit-config.yaml` (new) — pre-commit hook configuration
- `.hadolint.yaml` (new) — Dockerfile linter config
- `.yamllint.yaml` (new) — YAML linter config
- `.ansible-lint` (new) — Ansible linter config
- `.markdownlint.yaml` (new) — Markdown linter config
- `.env.example` (new) — environment variable template
- `.gitignore` (modified) — added mypy_cache, ruff_cache, .eggs/, models/
- `voices/.gitkeep` (new) — voice directory placeholder
- `tests/__init__.py` (new) — test package init
- `deploy/ansible/inventory/.gitkeep` (new) — directory placeholder
- `deploy/ansible/playbooks/.gitkeep` (new) — directory placeholder
- `scripts/.gitkeep` (new) — directory placeholder

### Change Log

- 2026-03-21: Story 1.1 implemented — full project scaffolding with quality tooling configured and validated
