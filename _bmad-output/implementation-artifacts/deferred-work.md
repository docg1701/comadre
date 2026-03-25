# Deferred Work

## Deferred from: code review of story 2-2 (2026-03-24)

- Download failure crashes startup with no retry or backoff — design trade-off for container workloads, consider adding retry with exponential backoff
- Empty comadre-voices volume causes Qwen3 failure on first run — operator must pre-populate voice reference WAVs before starting with Qwen3
- No URL scheme validation on download URLs — operator-controlled config, consider adding HttpUrl validation
- Dockerfile installs libsndfile1-dev instead of runtime libsndfile1 — image bloat, should use libsndfile1 runtime package
- Stale .tmp file with wrong ownership blocks subsequent downloads — unlikely edge case on container kill mid-download
- Healthcheck start_period may be insufficient for large downloads on slow connections — operator can increase start_period
- Non-reproducible Docker build — espeak-ng cloned from unpinned master, consider pinning a commit SHA
- Default voice set to Qwen3 bypasses schema char limit validation — pre-existing design issue in SpeechRequest validator
- COPY deploy/bin/qwen3-tts-cli fails if binary not present — build dependency not tracked in git

## Deferred from: code review of story 3-1 (2026-03-24)

- Dockerfile purges gcc/g++ — libstdc++ may be removed by autoremove, breaking runtime onnxruntime imports
- `Path.rename()` in download.py fails across filesystem mount boundaries — use shutil.move instead
- No checksum verification for multi-GB model downloads — truncated files go undetected
- Synchronous model download in lifespan() blocks async event loop — health endpoint unreachable during download
- URL config fields (kokoro_model_url, etc.) have no format validation — bad URLs fail at download, not at config load
- espeak-ng cloned from unpinned master in Dockerfile — non-reproducible builds
- compose.yaml hardcodes internal PORT to "8000" while host-side uses ${PORT:-8000} — variable override partially broken
- compose.yaml healthcheck uses bare `python` which may not resolve — use absolute /app/.venv/bin/python
- No download progress logging for large files — operator sees nothing during multi-minute downloads
- Download exception at startup gives no actionable context — wrap with logger.critical
- compose.yaml API_KEY unset on host causes runtime pydantic crash — use ${API_KEY:?} syntax
- SSL cert errors in downloads give opaque messages — catch ssl.SSLCertVerificationError
- Dockerfile COPY noise/ may be empty on fresh clone — WAV files in noise/ are gitignored
- Named volumes start empty — first-run model downloads block startup for ~10 min
- Dockerfile COPY deploy/bin/qwen3-tts-cli fails if binary not present — build dependency not tracked in git (duplicate of story 2.2 item)

## Deferred from: post-review gap analysis (2026-03-24)

- Ansible bootstrap playbook does NOT deploy Qwen3 GGUF model files to VPS — models (~1.6 GB) must be copied via SSH manually. A future story should add Ansible tasks using the helper container pattern to populate the comadre-models Docker volume before service startup. See `docs/quantizing-qwen3-models.md` for the manual deployment procedure.

## Deferred from: code review of story 3-2 (2026-03-25)

- No rollback on failed rebuild/health check — if health check fails after 10 minutes, the broken new version stays running. Consider a rollback strategy (keep previous image tag, revert on failure).
- Port variable coupling between inventory and compose.yaml — inventory `port` variable could diverge from compose.yaml hardcoded `PORT: '8000'`. Pre-existing config coupling across files.

## Deferred from: code review of story 4-1 (2026-03-25)

- No uv dependency cache in CI — lint and test jobs download all packages from PyPI every run (~30-60s each). Enable `cache: true` on `astral-sh/setup-uv@v4`.
- No pre-commit environment cache in CI — hook environments rebuilt every lint run (1-3 min). Cache `~/.cache/pre-commit`.
- No Docker layer cache in CI — espeak-ng source compilation repeats every build job (~3-5 min). Use `docker/build-push-action` with GHA cache.
- No job timeout in CI workflow — defaults to 360 min. Add `timeout-minutes` to each job.
- Unpinned espeak-ng master in Docker build — non-reproducible builds (duplicate of earlier deferred item)
- Unset API_KEY warning in compose.yaml — `${API_KEY}` without default produces Docker Compose warning in CI. Fix: `${API_KEY:-}`.

## Deferred from: code review of story 3-3 (2026-03-25)

- Volume name mismatch: helper containers in bootstrap.yml and deploy-models.yml mount `comadre-models` (unprefixed), but Docker Compose v2 may create volumes as `comadre_comadre-models` (project-prefixed) since compose.yaml has no explicit `name:` on volume definitions. If volumes are different, models and clone WAV are deployed to volumes the service never mounts. Verify on deployed VPS with `docker volume ls | grep comadre`. Fix: add `name: comadre-models` (etc.) to each volume definition in compose.yaml.
- `~` expansion in `community.docker.docker_container_copy_into` path parameter — bootstrap.yml and deploy-models.yml both use `~/comadre/deploy/staging/...` as the `path:` value. Module may not expand `~` to the remote user's home directory. Pre-existing pattern from bootstrap.yml clone WAV deployment.

## Resolved in: code review of story 4-3 (2026-03-25)

- FIXED: `changeme` API key fallback removed from `production.yml` — now uses bare `lookup('env', 'COMADRE_API_KEY')` with no fallback. Playbook assertions updated to check `length > 0` instead of `!= 'changeme'`.
- RESOLVED: `degraded` health status removed from api-reference.md status table — docs now only list `healthy` and `warming_up` (matching code behavior). Enum value remains in code but is harmless.
- RESOLVED: AAC M4A Content-Type gap — api-reference.md Platform Output Formats section updated to note destination is not yet implemented, all output currently uses OGG Opus.

## Resolved in: code review of story 4-2 (2026-03-25)

All items below were resolved (fixed or dismissed) during the Story 4.2 code review. No new deferrals.

- FIXED: cleanup.yml image prune replaced with `remove_images: all` on docker_compose_v2 task
- FIXED: Pinned uv binary to 0.8.3 in Dockerfile
- DISMISSED: deploy-models.yml staging cleanup scope — self-healing on retry
- DISMISSED: http:// URLs pass validation — operator-controlled, internal mirrors may use HTTP
- DISMISSED: health.yml port mismatch — by design, re-bootstrap propagates changes
- DISMISSED: deploy-models.yml partial file — no checksum verification explicitly excluded from scope
- DISMISSED: bootstrap.yml stale staging — low impact, overwritten on retry
- DISMISSED: No asyncio.to_thread test — integration concern, not business logic
