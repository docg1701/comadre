# Troubleshooting

Common issues with symptoms, causes, and resolution steps for both engines.

## Startup Failures

### API_KEY not set

**Symptom:** Container exits immediately on startup.

**Cause:** `API_KEY` environment variable is missing or empty in `.env`.

**Resolution:**

1. Check `.env` file exists and contains `API_KEY=your-key-here`
2. Verify Docker Compose reads it: `docker compose config | grep API_KEY`
3. Restart: `docker compose up -d`

### Model download fails

**Symptom:** Container starts but health endpoint returns 503 indefinitely. Logs show download errors.

**Cause:** Network issue, SSL certificate problem, or invalid download URL.

**Resolution:**

1. Check logs: `docker compose logs --tail=50`
2. Look for SSL or connection errors in the download output
3. Verify the download URLs are accessible from the VPS: `curl -I <model-url>`
4. Alternative: pre-deploy models via `deploy-models.yml` playbook and clear download URLs

### espeak-ng pt_extra not found

**Symptom:** Kokoro engine loads but sigla pronunciation is incorrect (spells letters instead of pronouncing as words).

**Cause:** The custom pt_extra dictionary was not compiled into espeak-ng data.

**Resolution:**

1. Verify the Dockerfile copies pt_extra data during build
2. Rebuild the image: `docker compose up -d --build`
3. Check that `ESPEAK_DATA_PATH` points to the correct directory

### qwen3-tts-cli binary missing

**Symptom:** Qwen3 engine fails to load. Health endpoint shows `qwen3.loaded: false`.

**Cause:** The `qwen3-tts-cli` binary is not present at `QWEN3_CLI_PATH`.

**Resolution:**

1. Verify the binary exists inside the container: `docker exec tts-service ls -la /usr/local/bin/qwen3-tts-cli`
2. Check the Dockerfile copies the binary from `deploy/bin/qwen3-tts-cli`
3. If rebuilding the binary is needed, see [building-qwen3-tts-cli.md](building-qwen3-tts-cli.md)

## Runtime Issues

### 503 warming_up

**Symptom:** All requests return 503 with `"Service is warming up"`.

**Cause:** Models are still downloading or loading. This is normal after a fresh start or restart.

**Resolution:**

1. Wait for model loading to complete (can take 1-3 minutes depending on download speed)
2. Monitor progress: `docker compose logs -f`
3. Check health endpoint: `curl http://localhost:8000/health`
4. If 503 persists beyond 5 minutes, check logs for download or loading errors

### 401 authentication error

**Symptom:** Requests return 401 with `"Invalid or missing API key"`.

**Cause:** The `Authorization` header is missing, malformed, or the key does not match.

**Resolution:**

1. Verify header format: `Authorization: Bearer YOUR_API_KEY` (note the space after "Bearer")
2. Check the key matches what is in `.env` on the VPS
3. Verify the key is loaded (check length, not the value): `docker exec tts-service sh -c 'echo API_KEY length: ${#API_KEY}'`

### 404 voice not found

**Symptom:** Requests return 404 with `"Voice 'name' not found"`.

**Cause:** The requested voice name is not in the available voices list.

**Resolution:**

1. Check available voices via health endpoint: `curl http://localhost:8000/health | jq .voices`
2. Voice names use the `engine/name` format: `kokoro/pm_santa`, `kokoro/pf_dora`, `kokoro/pm_alex`, `qwen/female-reference`, `qwen/galvani`, etc.
3. Voice names are case-sensitive. The engine prefix (`kokoro/` or `qwen/`) is required. See [voice-management.md](voice-management.md) for the full list of available voices and how to add new ones.

### Request timeout

**Symptom:** Request hangs and eventually times out (120 second limit).

**Cause:** Text is too long for the selected engine, or the service is processing another request (single FIFO queue).

**Resolution:**

1. Reduce text length (max 500 chars for Kokoro, 300 chars for Qwen3)
2. Check queue depth: `curl http://localhost:8000/health | jq .queue_depth`
3. If queue is consistently backed up, consider scaling horizontally

## Engine-Specific Issues

### Kokoro sigla mispronunciation

**Symptom:** Siglas like CPF, CNPJ, or FGTS are spelled letter-by-letter instead of pronounced correctly.

**Cause:** The espeak-ng pt_extra dictionary is not loaded. The bundled `espeakng_loader` data takes precedence over `ESPEAK_DATA_PATH`.

**Resolution:**

1. Verify pt_extra was compiled: check Dockerfile for the espeak-ng dictionary build step
2. The compiled pt_extra data must be copied to BOTH the system path AND the espeakng_loader bundled path inside the container
3. Rebuild the image: `docker compose up -d --build`

### Qwen3 random accent

**Symptom:** Qwen3 output has inconsistent or random accent (sometimes sounds like Mandarin or English instead of Brazilian Portuguese).

**Cause:** The `-l pt` flag is missing from the qwen3-tts-cli invocation. Without it, the language mode is undefined.

**Resolution:**

1. Check service.py to verify the `-l pt` flag is passed to the CLI command
2. This should be handled automatically by the application code
3. If the issue persists, check the qwen3-tts-cli binary version: `docker exec tts-service qwen3-tts-cli --version`

### Clone voice sounds different

**Symptom:** The cloned voice does not match the reference audio closely, or sounds different between runs.

**Cause:** Reference WAV quality issues, or seed value not producing consistent results.

**Resolution:**

1. Verify reference WAV quality: 3-10 seconds, mono, 16kHz+, clear speech, minimal background noise
2. Check the reference file exists: `docker exec tts-service ls -la /voices/`
3. Seed reproducibility gives similar (not identical) results across runs -- some variation is expected
4. Try a different reference recording with clearer audio

## Deployment Issues

### Health check fails after update

**Symptom:** The update playbook fails at the health check step after rebuilding.

**Cause:** Code change introduced a startup error, or model files are incompatible with new code.

**Resolution:**

1. Check logs: `docker compose -f ~/comadre/compose.yaml logs --tail=50`
2. Check container status: `docker compose -f ~/comadre/compose.yaml ps`
3. Try restarting: `docker compose -f ~/comadre/compose.yaml restart`
4. Roll back to previous version:

    ```bash
    cd ~/comadre
    git log --oneline -5
    git checkout <previous-commit>
    docker compose up -d --build
    ```

### Volume name mismatch

**Symptom:** Models or voices are not found after a rebuild, even though they were previously deployed.

**Cause:** Docker Compose prefixes volume names with the project directory name unless volumes have explicit `name:` keys.

**Resolution:**

1. Verify compose.yaml has explicit `name:` for each volume:

    ```yaml
    volumes:
      comadre-models:
        name: comadre-models
    ```

2. Check existing volumes: `docker volume ls | grep comadre`
3. If volumes have wrong names, copy data to correctly named volumes and remove old ones

### Disk space

**Symptom:** Service becomes slow or fails to generate audio. Disk usage warnings in health playbook.

**Cause:** Generated audio files accumulate over time.

**Resolution:**

1. Check disk usage: `df -h /`
2. Check audio volume size: `docker exec tts-service du -sh /audio`
3. Verify the audio cleanup cron is active: `crontab -l | grep comadre-audio-cleanup`
4. Expected: runs every 6 hours, deletes audio files older than 24 hours
5. Manual cleanup: `docker exec tts-service find /audio -type f \( -name '*.ogg' -o -name '*.wav' \) -mmin +1440 -delete`

## Log Format

COMADRE uses structured pipe-delimited logging:

```text
2026-03-25T14:30:00Z | INFO  | request | TTS generation completed in 8.3s
2026-03-25T14:30:01Z | ERROR | request | Unhandled exception during request processing
```

**Format:** `timestamp | level | component | message`

**Components:**

| Component | Description |
| --- | --- |
| `startup` | Application initialization and model loading |
| `download` | Model download progress |
| `request` | HTTP request handling, TTS generation, and errors |
| `health` | Health endpoint checks |
| `voice` | Voice discovery and validation |

**Filtering logs by component:**

```bash
# Show only request logs
docker compose logs | grep '| request |'

# Show only errors
docker compose logs | grep '| ERROR |'

# Follow logs in real time
docker compose logs -f --tail=20
```
