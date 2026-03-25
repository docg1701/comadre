# Story 4.2: Hardening & Deferred Fixes

Status: done

## Story

As a developer and operator,
I want all deferred code review findings resolved before documentation is written,
so that the documentation accurately reflects the final production behavior.

## Acceptance Criteria

1. **Given** compose.yaml volume definitions, **When** Docker Compose v2 creates volumes, **Then** each volume has an explicit `name:` matching what Ansible playbooks mount (e.g., `cumadre-models`, `cumadre-voices`), preventing project-prefix mismatch.

2. **Given** `download.py` moves a temporary file to its final path, **When** the source and destination are on different filesystem mount boundaries, **Then** `shutil.move` is used instead of `Path.rename()` so the operation succeeds.

3. **Given** the Dockerfile purges build tools (`gcc`, `g++`), **When** `apt-get autoremove` runs, **Then** `libstdc++` is NOT removed (explicitly marked or excluded), so onnxruntime imports work at runtime.

4. **Given** the synchronous model download in `lifespan()`, **When** a multi-GB download is in progress, **Then** the download runs in a thread pool (`asyncio.to_thread` or equivalent) so the health endpoint remains reachable during startup.

5. **Given** the CI workflow `.github/workflows/ci.yml`, **When** lint, test, and build jobs run, **Then** uv dependencies are cached (`astral-sh/setup-uv` `cache: true`), pre-commit environments are cached (`~/.cache/pre-commit`), and each job has a `timeout-minutes` set.

6. **Given** the Dockerfile clones espeak-ng from GitHub, **When** the image is built, **Then** a pinned commit SHA is used instead of unpinned `master`, producing reproducible builds.

7. **Given** compose.yaml references `${API_KEY}`, **When** `API_KEY` is unset on the host, **Then** Docker Compose does NOT emit a warning (use `${API_KEY:-}` or `${API_KEY:?}`).

8. **Given** the Dockerfile installs `libsndfile1-dev`, **When** the image is built, **Then** only the runtime package `libsndfile1` is installed (not the dev headers), reducing image size.

9. **Given** a model download fails or takes several minutes, **When** the operator watches the logs, **Then** they see progress logging, actionable error context (`logger.critical` with URL and error), and clear SSL certificate error messages.

10. **Given** config fields `kokoro_model_url`, etc., **When** an invalid URL is provided, **Then** pydantic validates the URL format at config load time (not at download time).

11. **Given** Ansible playbooks `bootstrap.yml` and `deploy-models.yml` use `~/cumadre/...` in path parameters, **When** the playbook runs on the remote host, **Then** the `~` is correctly expanded (use `{{ ansible_env.HOME }}` or absolute paths).

12. **Given** compose.yaml hardcodes `PORT: '8000'` internally, **When** the operator overrides `${PORT:-8000}` on the host side, **Then** both sides use the same variable consistently.

13. **Given** no rollback strategy exists in the update playbook, **When** a deploy health check fails after rebuild, **Then** the playbook reports the failure clearly with actionable next steps (rollback automation is deferred but the failure must not be silent).

## Tasks / Subtasks

- [x] Task 1: Fix Docker volume name mismatch (AC: 1)
  - [x] 1.1 Add explicit `name:` to each volume definition in `compose.yaml` (cumadre-models, cumadre-voices, cumadre-audio)
  - [x] 1.2 Verify Ansible playbooks (bootstrap.yml, deploy-models.yml) reference matching unprefixed volume names
  - [x] 1.3 Run `docker compose config` to verify volume names resolve correctly

- [x] Task 2: Fix cross-filesystem rename in download.py (AC: 2)
  - [x] 2.1 Replace `tmp.rename(dest)` at line 31 with `shutil.move(str(tmp), str(dest))`
  - [x] 2.2 Add `import shutil` to download.py
  - [x] 2.3 Update or add test for cross-filesystem move scenario

- [x] Task 3: Protect libstdc++ from autoremove (AC: 3)
  - [x] 3.1 In Dockerfile lines 53-63, add `apt-mark manual libstdc++6` before `apt-get autoremove` to prevent removal
  - [x] 3.2 Verify with `docker compose build` that onnxruntime still imports

- [x] Task 4: Make model download non-blocking (AC: 4)
  - [x] 4.1 In `main.py` lifespan(), wrap `ensure_kokoro_models()` and `ensure_qwen3_models()` calls (lines 49-60) with `await asyncio.to_thread()`
  - [x] 4.2 Add progress logging before each download call ("Downloading Kokoro model from {url}...")
  - [x] 4.3 Verify health endpoint returns 503/warming_up during download phase

- [x] Task 5: Add CI caching and timeouts (AC: 5)
  - [x] 5.1 Add `cache: true` to `astral-sh/setup-uv@v4` action in lint and test jobs
  - [x] 5.2 Add `actions/cache@v4` step for `~/.cache/pre-commit` in lint job (key on `.pre-commit-config.yaml` hash)
  - [x] 5.3 Add `timeout-minutes: 15` to lint and test jobs, `timeout-minutes: 20` to build job

- [x] Task 6: Pin espeak-ng commit SHA in Dockerfile (AC: 6)
  - [x] 6.1 Research current stable espeak-ng commit SHA from GitHub
  - [x] 6.2 Replace `git clone --depth 1 https://github.com/espeak-ng/espeak-ng.git` (line 19) with `git clone https://github.com/espeak-ng/espeak-ng.git && cd espeak-ng && git checkout {SHA}`
  - [x] 6.3 Add comment with date and reason for chosen SHA

- [x] Task 7: Fix API_KEY and PORT variable handling (AC: 7, 12)
  - [x] 7.1 In compose.yaml, change `${API_KEY}` (line 13) to `${API_KEY:?API_KEY must be set}` (required var)
  - [x] 7.2 Unify PORT: replace hardcoded `PORT: "8000"` (line 15) with `PORT: "${PORT:-8000}"` so both host and container use the same variable
  - [x] 7.3 Verify `docker compose config` shows correct resolution

- [x] Task 8: Switch to runtime libsndfile package (AC: 8)
  - [x] 8.1 In Dockerfile line 7, replace `libsndfile1-dev` with `libsndfile1`
  - [x] 8.2 Verify build still succeeds (no Python packages need libsndfile headers at build time)

- [x] Task 9: Improve download observability (AC: 9)
  - [x] 9.1 Add progress logging to `_download_file()` in download.py: log file size after HEAD request, log completion
  - [x] 9.2 Wrap download exceptions with `logger.critical(f"Failed to download {url}: {err}")` and re-raise
  - [x] 9.3 Add specific `except ssl.SSLCertVerificationError` handler with actionable message ("SSL certificate verification failed for {url}. Check system CA certificates or use REQUESTS_CA_BUNDLE env var.")
  - [x] 9.4 Use structured logging format (pipe-delimited: `timestamp | level | download | message`)

- [x] Task 10: Add URL validation to config (AC: 10)
  - [x] 10.1 In config.py, change `kokoro_model_url: str` (line 65) and similar fields to use pydantic `HttpUrl` or a custom validator
  - [x] 10.2 Handle empty string URLs (Qwen3 defaults to `""` meaning skip download) — use `HttpUrl | Literal[""]` or a custom validator that allows empty
  - [x] 10.3 Add test that invalid URLs fail at config load time

- [x] Task 11: Fix Ansible path expansion (AC: 11)
  - [x] 11.1 In all playbooks, replace bare `~/cumadre` paths with `{{ ansible_env.HOME }}/cumadre` for `community.docker.docker_container_copy_into` path parameters
  - [x] 11.2 Verify `ansible.builtin.git`, `ansible.builtin.file`, `ansible.builtin.cron` modules handle `~` correctly (they do — only docker modules need fixing)
  - [x] 11.3 Test with `ansible-playbook --check` against inventory

- [x] Task 12: Improve deploy failure reporting (AC: 13)
  - [x] 12.1 In update.yml, after health check failure (line 88+), add a rescue block or `failed_when` with actionable message: "Health check failed. Service may be in broken state. Check logs with: docker compose -f ~/cumadre/compose.yaml logs --tail=50"
  - [x] 12.2 Ensure the playbook does NOT silently continue after health check failure

## Dev Notes

### Architecture Constraints

- **Module boundaries enforced** — no HTTP concerns in service.py, no business logic in api.py
- **Import graph flows downward only** — config/logging → exceptions/voices/schemas → preprocessing → service → api/health → main. No circular imports.
- **All errors via CumadreError hierarchy** — never raw HTTPException
- **Structured logging** — pipe-delimited `timestamp | level | component | message`, never `print()`
- **Configuration** — pydantic-settings only, never raw `os.environ`
- **Docker Compose v2 syntax** — `docker compose`, never `docker-compose`
- **Package management** — `uv` only, never `pip`
- **Type annotations** — mypy strict mode with pydantic plugin, `from __future__ import annotations` at module top

### Exact Code Locations to Modify

**compose.yaml:**
- Lines 9-11: Volume mounts (`cumadre-models:/models:rw`, `cumadre-voices:/voices:ro`, `cumadre-audio:/audio:rw`)
- Line 13: `API_KEY: ${API_KEY}` — needs `${API_KEY:?API_KEY must be set}`
- Line 15: `PORT: "8000"` — hardcoded, needs `${PORT:-8000}`
- Bottom of file: volume definitions need explicit `name:` keys

**Dockerfile:**
- Line 7: `libsndfile1-dev` → `libsndfile1`
- Line 19: `git clone --depth 1 https://github.com/espeak-ng/espeak-ng.git /tmp/espeak-ng` — unpinned master
- Lines 53-63: gcc/g++ purge + autoremove section — add `apt-mark manual libstdc++6` before autoremove

**src/cumadre/download.py:**
- Line 13: `_DOWNLOAD_TIMEOUT = 300`
- Line 24: Uses `.tmp` suffix temp files
- Line 31: `tmp.rename(dest)` — must become `shutil.move(str(tmp), str(dest))`
- Line 35: `tmp.unlink(missing_ok=True)` in except block
- Lines 41-42: Skip logic `if path.is_file(): return`
- Lines 49-83: `ensure_kokoro_models()` and `ensure_qwen3_models()` functions

**src/cumadre/main.py:**
- Lines 27-28: `lifespan()` async context manager
- Lines 49-54: `ensure_kokoro_models()` call — wrap in `asyncio.to_thread()`
- Lines 55-60: `ensure_qwen3_models()` call — wrap in `asyncio.to_thread()`

**src/cumadre/config.py:**
- Lines 65-69: `kokoro_model_url: str` with HuggingFace URL default
- Lines 72-76: `kokoro_voices_url: str` with HuggingFace URL default
- Lines 79-81: `qwen3_model_url: str = ""` (empty = skip)
- Lines 83-85: `qwen3_tokenizer_url: str = ""` (empty = skip)

**.github/workflows/ci.yml:**
- Lines 10-20: Lint job — no cache settings, no timeout
- Lines 24-33: Test job — no cache, no timeout
- Lines 37-41: Build job — no timeout
- Python version: `"3.12"` (lines 17, 30)

**deploy/ansible/playbooks/bootstrap.yml:**
- Line 122: `dest: "~/cumadre"` (git clone)
- Lines 137, 152, 165: `"~/cumadre/deploy/staging"` paths
- Line 145: `cumadre-voices:/voices` (volume ref — already unprefixed, OK)
- Line 174: `.env` file path `"~/cumadre/.env"`
- Lines 186-187: `project_src: "~/cumadre"` (docker compose)

**deploy/ansible/playbooks/deploy-models.yml:**
- Lines 65, 72, 78, 122: `"~/cumadre/deploy/staging"` paths
- Line 92: `"cumadre-models:/models"` (volume ref — already unprefixed, OK)

**deploy/ansible/playbooks/update.yml:**
- Line 20: `path: "~/cumadre"` check
- Lines 66-67: `dest: "~/cumadre"` (git pull)
- Lines 77-79: `project_src: "~/cumadre"` (docker compose)
- Line 88: Health check URL `http://localhost:{{ port }}/health`

**deploy/ansible/playbooks/health.yml:**
- Line 21: `path: "~/cumadre"` check
- Line 58: Health endpoint URL

**deploy/ansible/playbooks/cleanup.yml:**
- Line 77: `path: "~/cumadre"` removal

### Ansible ~ Path Expansion: What Needs Fixing vs What's OK

Not all Ansible modules have the same `~` expansion behavior. Key distinction:

| Module | `~` Expansion | Action Needed |
|--------|---------------|---------------|
| `ansible.builtin.git` | Expands `~` natively | No change |
| `ansible.builtin.file` | Expands `~` natively | No change |
| `ansible.builtin.cron` | Expands `~` natively | No change |
| `ansible.builtin.template` | Expands `~` natively | No change |
| `ansible.builtin.copy` | Expands `~` natively | No change |
| `community.docker.docker_compose_v2` | Expands `~` via Ansible | Likely OK, but verify |
| `community.docker.docker_container` | Does NOT expand `~` in `volumes:` | Must use absolute paths |
| `community.docker.docker_container_copy_into` | May NOT expand `~` in `path:` | Must use `{{ ansible_env.HOME }}` |

**Focus fixes on:** `community.docker.*` module path parameters where `~` may not expand. All `ansible.builtin.*` modules handle `~` correctly.

### URL Validation: Handling Empty String for Qwen3

Qwen3 model URLs default to `""` (empty string), meaning "skip auto-download, operator pre-provisions models via SCP". The URL validator must allow this:

```python
# Option A: Union type with validator
kokoro_model_url: HttpUrl = HttpUrl("https://github.com/...")
qwen3_model_url: str = ""  # Empty = skip download

@field_validator("qwen3_model_url", "qwen3_tokenizer_url")
@classmethod
def validate_optional_url(cls, v: str) -> str:
    if v == "":
        return v
    # Validate as URL
    HttpUrl(v)
    return v
```

This preserves the empty-string-means-skip behavior while validating non-empty URLs at config load time.

### Making Downloads Non-Blocking: Implementation Pattern

The current `lifespan()` calls `ensure_kokoro_models()` and `ensure_qwen3_models()` synchronously, blocking the event loop. During a ~10 minute first-run download, the health endpoint is unreachable (returns connection refused, not 503).

Fix pattern:
```python
# In lifespan(), replace:
ensure_kokoro_models(settings)
# With:
await asyncio.to_thread(ensure_kokoro_models, settings)
```

This moves the blocking I/O to a thread pool while keeping the lifespan async, allowing the health endpoint to respond with 503/warming_up during download.

**Important:** The `app.state.ready = False` flag is already set before downloads begin, so the health endpoint will correctly return 503 once the event loop is free to handle requests.

### CI Cache Strategy

**uv cache:** `astral-sh/setup-uv@v4` has built-in `cache: true` support. It caches `~/.cache/uv` keyed on `uv.lock` hash. Saves ~30-60s per job.

**Pre-commit cache:** Use `actions/cache@v4` with:
- Path: `~/.cache/pre-commit`
- Key: `pre-commit-${{ hashFiles('.pre-commit-config.yaml') }}`
- Saves 1-3 minutes (hook environment setup).

**Docker layer cache:** NOT in scope for this story (would require migrating from `docker compose build` to `docker/build-push-action`). Listed as excluded item.

**Timeout values:**
- Lint: 15 min (pre-commit hooks + mypy can be slow)
- Test: 15 min (400+ tests, all mocked, typically ~10s but buffer for slow runners)
- Build: 20 min (espeak-ng compilation takes 3-5 min + Docker pull)

### Volume Name Mismatch: The Actual Risk

Docker Compose v2 prefixes volume names with the project name by default. If `compose.yaml` is in `~/cumadre/`, the project name is `cumadre`, so:
- Defined as `cumadre-models` → created as `cumadre_cumadre-models`
- Ansible mounts `cumadre-models` (unprefixed) → different volume

Fix: Add explicit `name:` to prevent prefixing:
```yaml
volumes:
  cumadre-models:
    name: cumadre-models
  cumadre-voices:
    name: cumadre-voices
  cumadre-audio:
    name: cumadre-audio
```

### Items NOT Included (Low Priority / Edge Cases)

These were assessed as low priority and excluded from this story:

- **Stale `.tmp` file with wrong ownership** — unlikely edge case on container kill mid-download
- **Healthcheck `start_period` tuning** — operator can adjust; no code change needed
- **Default voice bypasses schema char limit** — pre-existing design issue, not a bug
- **COPY deploy/bin/qwen3-tts-cli fails if binary not present** — build dependency tracked in git; documented in build guide
- **Empty cumadre-voices volume** — operator responsibility to pre-populate; documented
- **Named volumes start empty on first run** — expected behavior; model download handles it
- **Download retry/backoff** — design trade-off for container workloads; restart policy handles it
- **No Docker layer cache in CI** — optimization only, would require `docker/build-push-action` migration
- **No model checksum verification** — good practice but adds complexity; deferred to future story

### Project Structure Notes

Files to modify (no new files created):
```
compose.yaml                              # Volume names, env vars, PORT
Dockerfile                                # espeak-ng pin, libsndfile, libstdc++ protection
src/cumadre/download.py                   # shutil.move, progress logging, SSL errors
src/cumadre/main.py                       # asyncio.to_thread for downloads
src/cumadre/config.py                     # URL validation
.github/workflows/ci.yml                  # Cache, timeouts
deploy/ansible/playbooks/bootstrap.yml    # Path expansion
deploy/ansible/playbooks/deploy-models.yml # Path expansion
deploy/ansible/playbooks/update.yml       # Path expansion, failure reporting
deploy/ansible/playbooks/health.yml       # Path expansion
deploy/ansible/playbooks/cleanup.yml      # Path expansion
```

No new files. No new dependencies. No changes to import graph or module boundaries.

### Testing Approach

- Run `uv run pytest` after Python changes (download.py, main.py, config.py) — all 400+ tests must pass
- Run `uv run pre-commit run --all-files` for lint/format/type checks
- Run `docker compose config` after compose.yaml changes to verify YAML resolution
- Run `docker compose build` to verify Dockerfile changes (espeak-ng pin, libsndfile, libstdc++)
- Ansible changes: validate with `ansible-playbook --syntax-check` and `ansible-lint`

### Previous Story Intelligence

**From Story 4.1 (GitHub Actions CI Pipeline):**
- CI workflow already exists at `.github/workflows/ci.yml` with three jobs (lint, test, build)
- Test depends on lint; build depends on lint; test and build run in parallel
- Pre-existing test failures in `test_routing.py` were fixed (subprocess mock issue)
- 392 tests pass, 11 skipped (slow-marked integration tests)
- `uv sync` required before `pre-commit run` because mypy hook is `repo: local` with `entry: uv run mypy`

**From Story 3.1-3.3 (Ansible):**
- Privilege model: `become: true` ONLY for apt/docker install; all else unprivileged
- Idempotency: `community.docker.docker_compose_v2` needs `state: present` + `changed_when`
- Cron jobs are user-level (`ansible.builtin.cron`), not system cron
- Helper container pattern used for volume population (alpine:3.21, mount volume, copy files in)

**From Story 2.1-2.2 (Docker):**
- Single-stage Dockerfile from `python:3.12-slim`
- espeak-ng compiled from source (autogen.sh → configure → make → make install)
- pt_extra dictionary compiled and copied to BOTH system path AND espeakng_loader bundled path
- qwen3-tts-cli binary COPY'd from `deploy/bin/`
- Non-root `appuser` runs the service

### References

- [Source: _bmad-output/implementation-artifacts/deferred-work.md — all 30 deferred findings across 6 reviews]
- [Source: _bmad-output/planning-artifacts/architecture.md — Decisions D1-D11, module boundaries, deployment patterns]
- [Source: _bmad-output/planning-artifacts/epics.md — Epic 4 story definitions and acceptance criteria]
- [Source: compose.yaml — volume definitions (lines 9-11), env vars (lines 13-23), volume block (bottom)]
- [Source: Dockerfile — espeak-ng clone (line 19), libsndfile (line 7), purge section (lines 53-63)]
- [Source: src/cumadre/download.py — Path.rename (line 31), download logic (lines 13-83)]
- [Source: src/cumadre/main.py — lifespan() (lines 27-28), model downloads (lines 49-60)]
- [Source: src/cumadre/config.py — URL fields (lines 65-85)]
- [Source: .github/workflows/ci.yml — full pipeline (lines 1-42)]
- [Source: deploy/ansible/playbooks/*.yml — all playbook path references]
- [Source: deploy/ansible/inventory/production.yml — port and config variables]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

- Initial test run: 399 passed, 1 failed (shutil.move mock test needed side_effect to actually create file)
- Fixed mock test with `fake_move` side_effect, all 400 tests pass
- Pre-commit: ruff line-too-long in config.py docstring (wrapped to multi-line), hadolint DL3003 in Dockerfile (split `cd` into WORKDIR)
- All 400 tests pass, 11 skipped (slow), all pre-commit hooks pass

### Completion Notes List

- Task 1: Added explicit `name:` keys to all three volume definitions in compose.yaml, preventing Docker Compose project-prefix mismatch. Verified with `docker compose config`.
- Task 2: Replaced `tmp.rename(dest)` with `shutil.move(str(tmp), str(dest))` for cross-filesystem safety. `shutil` was already imported. Added test verifying shutil.move is called.
- Task 3: Added `apt-mark manual libstdc++6` before `apt-get autoremove` in Dockerfile to prevent onnxruntime runtime dependency from being removed.
- Task 4: Wrapped both `ensure_kokoro_models()` and `ensure_qwen3_models()` in `await asyncio.to_thread()` so downloads don't block the event loop. Health endpoint can now respond 503/warming_up during downloads.
- Task 5: Added `cache: true` to setup-uv in both lint and test jobs, `actions/cache@v4` for pre-commit cache in lint job, and timeout-minutes (15/15/20) to all three CI jobs.
- Task 6: Pinned espeak-ng to commit `675d77226b16105e96382d38ee27c0ad9660fa1e` (2026-03-24), which includes PR #2344 pt-BR improvements. Used separate WORKDIR + checkout to satisfy hadolint.
- Task 7: Changed `${API_KEY}` to `${API_KEY:?API_KEY must be set}` (errors when unset) and `PORT: "8000"` to `PORT: "${PORT:-8000}"` (unified host/container). Verified with `docker compose config`.
- Task 8: Replaced `libsndfile1-dev` with `libsndfile1` in Dockerfile (no Python packages need headers at build time).
- Task 9: Added `ssl.SSLCertVerificationError` handler with actionable message, general exception handler with `logger.critical` and URL context. Added 2 new tests verifying critical logging on failures.
- Task 10: Added `@field_validator` for all URL fields using `HttpUrl` validation, allowing empty string for optional Qwen3 URLs. Added 3 new tests (invalid kokoro URL, invalid qwen3 URL, empty qwen3 URL allowed).
- Task 11: Replaced `~/cumadre` with `{{ ansible_env.HOME }}/cumadre` in `docker_container_copy_into` path params in bootstrap.yml and deploy-models.yml. Enabled `gather_facts: true` in deploy-models.yml for `ansible_env` access.
- Task 12: Added explicit failure task in update.yml that triggers when health check fails, providing actionable next steps (check logs, check status, try restart, rollback instructions).

### Review Findings

- [x] [Review][Fixed] AC 9 progress logging — resolved via Content-Length from GET response headers (user chose option 2 over HEAD request). [src/cumadre/download.py:31]
- [x] [Review][Fixed] Dockerfile espeak-ng shallow fetch — replaced `git clone` with `git init` + `git fetch --depth 1` + `git checkout FETCH_HEAD`. [Dockerfile:19-22]
- [x] [Review][Fixed] SSL error hint corrected to SSL_CERT_FILE / SSL_CERT_DIR — was referencing `requests`-specific REQUESTS_CA_BUNDLE. [src/cumadre/download.py:40]
- [x] [Review][Fixed] CI build job API_KEY — added `env: API_KEY: ci-build-dummy` to prevent `${API_KEY:?}` expansion failure. [.github/workflows/ci.yml:53]
- [x] [Review][Fixed] cleanup.yml image prune replaced with `remove_images: all` on docker_compose_v2 task [deploy/ansible/playbooks/cleanup.yml:40] — `docker image prune` won't remove tagged images; `remove_images: all` does.
- [x] [Review][Fixed] Pinned uv binary to 0.8.3 in Dockerfile [Dockerfile:34] — was `ghcr.io/astral-sh/uv:latest`, now `ghcr.io/astral-sh/uv:0.8.3` for reproducible builds.
- [x] [Review][Dismissed] deploy-models.yml staging cleanup scope — self-healing on retry; staging dir overwritten on next run.
- [x] [Review][Dismissed] http:// URLs pass validation — operator-controlled config; internal mirrors may use HTTP.
- [x] [Review][Dismissed] health.yml port mismatch after inventory change — by design; re-bootstrap propagates config changes.
- [x] [Review][Dismissed] deploy-models.yml partial file in volume — explicitly excluded from scope (no model checksum verification).
- [x] [Review][Dismissed] bootstrap.yml stale staging directory — low impact, overwritten on next bootstrap run.
- [x] [Review][Dismissed] No asyncio.to_thread test — integration concern; verifying framework behavior, not business logic.

### Change Log

- 2026-03-25: Implemented Story 4.2 — all 12 tasks across 13 acceptance criteria resolved. 6 new tests added (3 download, 3 config). All 400 tests pass.

### File List

- compose.yaml — volume names, API_KEY required, PORT unified
- Dockerfile — libsndfile1 (not -dev), espeak-ng pinned SHA, apt-mark libstdc++6
- src/cumadre/download.py — shutil.move, SSL error handler, critical logging
- src/cumadre/main.py — asyncio.to_thread for downloads
- src/cumadre/config.py — URL field_validator with HttpUrl
- .github/workflows/ci.yml — uv cache, pre-commit cache, timeouts
- deploy/ansible/playbooks/bootstrap.yml — ansible_env.HOME in docker_container_copy_into
- deploy/ansible/playbooks/deploy-models.yml — ansible_env.HOME, gather_facts: true
- deploy/ansible/playbooks/update.yml — health check failure reporting
- tests/test_download.py — 3 new tests (shutil.move, critical logging, SSL error)
- tests/test_config.py — 3 new tests (invalid URL rejected, empty URL allowed)
