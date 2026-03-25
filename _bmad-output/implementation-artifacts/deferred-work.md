# Deferred Work

## Deferred from: code review of story 2-2 (2026-03-24)

- Download failure crashes startup with no retry or backoff — design trade-off for container workloads, consider adding retry with exponential backoff
- Empty cumadre-voices volume causes Qwen3 failure on first run — operator must pre-populate voice reference WAVs before starting with Qwen3
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

- Ansible bootstrap playbook does NOT deploy Qwen3 GGUF model files to VPS — models (~1.6 GB) must be copied via SSH manually. A future story should add Ansible tasks using the helper container pattern to populate the cumadre-models Docker volume before service startup. See `docs/quantizing-qwen3-models.md` for the manual deployment procedure.
