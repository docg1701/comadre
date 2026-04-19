# Configuration Reference

Comadre is configured via environment variables. All variables are loaded at startup using pydantic-settings. The single required variable is `KEY_REGISTRY_ENCRYPTION_KEY`; everything else has sensible defaults.

## Environment Variables

| Variable | Default | Description | Example |
| --- | --- | --- | --- |
| `KEY_REGISTRY_ENCRYPTION_KEY` | *(required)* | Fernet key used to encrypt tax IDs at rest in the SQLite key registry. Must be a valid 44-character base64 Fernet key. Startup fails if missing or malformed. Uses `SecretStr` internally so the value never appears in logs or error renderings. | *(output of `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)* |
| `KEY_REGISTRY_DB_PATH` | `./data/keys/registry.db` | SQLite registry file path. Parent directory is created with mode 0700 and the file with mode 0600 on first use. WAL sidecars inherit the same mode. | `/var/lib/comadre/registry.db` |
| `OPERATOR_CONTACT_HINT` | `Contact your Comadre operator for billing.` | Operator contact string echoed in 401 hints for suspended / revoked / past-due keys. Keep it short and customer-facing. | `Contact ops@acme.example for billing.` |
| `BILLING_TIMEZONE` | `UTC` | IANA timezone used for billing-day calculations (first-charge dates, `paid_until` comparisons, stamped note dates) and the daily suspension sweep's day-boundary. Must be a valid zone; startup fails otherwise. **MUST match the `CRON_TZ` envvar set by `deploy/ansible/playbooks/bootstrap.yml`** (sourced from the inventory's `billing_timezone` variable) — drift between the two silently shifts the daily suspension sweep's "today" computation relative to the cron schedule. **Billing-TZ is a contractual input**: whichever zone this variable holds dictates when a customer's `paid_until` expires and their API key flips to 401. Operators MUST communicate the chosen zone to customers at contract time and avoid changing it post-onboarding (a change silently shifts when existing keys go past-due). Default `UTC` is the operator-neutral, internationally predictable choice; override only when you have formally informed the customer base. See also: `comadre-keys mark-paid`, `comadre-keys suspend`, `comadre-keys reactivate` for the operator-hand billing verbs; `comadre-keys at-risk`, `comadre-keys revenue` read the reporting month / look-ahead window in this timezone; `comadre-keys suspend-sweep` is the manual/dry-run entry point for the daily auto-suspension cron. | `America/Sao_Paulo` |
| `BILLING_DAY` | `5` | Day-of-month (1–28) for monthly billing sweeps. Kept inside 1..28 so every month has the date. | `10` |
| `DEFAULT_VOICE` | `kokoro/pm_santa` | Voice used when the request omits `voice`. Uses `engine/name` format. | `kokoro/pf_dora` |
| `PORT` | `8000` | HTTP port for the FastAPI server (1..65535). Exposed only inside the Docker network — Caddy fronts 80/443. | `9000` |
| `ESPEAK_DATA_PATH` | `None` | Override bundled espeak-ng data path for custom pt-BR pronunciation. | `/usr/local/share/espeak-ng-data` |
| `NOISE_DIR` | `/app/noise` | Directory containing room/hiss noise WAV files used by post-processing pipelines. | `/app/noise` |
| `VOICES_DIR` | `/voices` | Root directory for voice discovery. Must contain `kokoro/` (`.npy`) and/or `qwen/` (`.wav`) subdirectories. See [voice-management.md](voice-management.md). | `/voices` |
| `KOKORO_MODEL_PATH` | `models/kokoro-v1.0.onnx` | Kokoro ONNX model file. | `/models/kokoro-v1.0.onnx` |
| `KOKORO_VOICES_PATH` | `models/voices-v1.0.bin` | Kokoro voices binary file. | `/models/voices-v1.0.bin` |
| `KOKORO_MODEL_URL` | *(GitHub release URL)* | URL fetched on first start when the Kokoro model file is missing. | `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx` |
| `KOKORO_VOICES_URL` | *(GitHub release URL)* | URL fetched on first start when the Kokoro voices file is missing. | `https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin` |
| `QWEN3_ENABLED` | `true` | Enable the Qwen3 engine. Set `false` on hosts where the x86_64 binary cannot run (e.g. aarch64 / Oracle Cloud Ampere A1). Disabling skips Qwen3 download, load, and warm-up and hides `qwen/*` voices. | `false` |
| `QWEN3_CLI_PATH` | `/usr/local/bin/qwen3-tts-cli` | Path to the qwen3-tts-cli binary. | `/usr/local/bin/qwen3-tts-cli` |
| `QWEN3_MODEL_PATH` | `models/qwen3-tts-0.6b-q8_0.gguf` | Qwen3 Q8_0 GGUF model file. | `/models/qwen3-tts-0.6b-q8_0.gguf` |
| `QWEN3_TOKENIZER_PATH` | `models/qwen3-tts-tokenizer-f16.gguf` | Qwen3 tokenizer GGUF file. | `/models/qwen3-tts-tokenizer-f16.gguf` |
| `QWEN3_THREADS` | `4` | CPU threads for Qwen3 inference. Minimum 1. Beyond 4, diminishing returns (~1.5% gain at 6 cores). | `4` |
| `QWEN3_MODEL_URL` | *(empty)* | URL to auto-download the Qwen3 GGUF model. Empty string skips download — the file must then exist at `QWEN3_MODEL_PATH`. | `https://huggingface.co/PabloHoties/Qwen3-TTS-12Hz-0.6B-Base-GGUF/resolve/main/qwen3-tts-0.6b-q8_0.gguf` |
| `QWEN3_TOKENIZER_URL` | *(empty)* | URL to auto-download the Qwen3 tokenizer GGUF. Empty string skips download. | `https://huggingface.co/PabloHoties/Qwen3-TTS-12Hz-0.6B-Base-GGUF/resolve/main/qwen3-tts-tokenizer-f16.gguf` |
| `DOMAIN` | `localhost` | Domain name used by Caddy. A real domain triggers Let's Encrypt; `localhost` uses a self-signed cert from Caddy's internal CA. Compose-level variable, not consumed by the Python process. | `tts.example.com` |

## Auxiliary files

The key registry lives at `KEY_REGISTRY_DB_PATH`, and two sibling files share the same parent directory and mode `0600`:

| Path | Purpose |
| --- | --- |
| `{KEY_REGISTRY_DB_PATH}.invalidate` | Cache-invalidation sentinel. The `comadre-keys` CLI touches this file on every `api_key` mutation; the API stats it on each cache read and flushes the `AuthCache` the moment mtime advances. See [rate-limiting.md](rate-limiting.md#operator-surface). |
| `{KEY_REGISTRY_DB_PATH}.counters.{replica_id}.json` | Per-replica request counters snapshot written every 15 s by the API process (one file per replica, `{replica_id}` = `socket.gethostname()`). The `comadre-keys cache-status` and `show <key-prefix> --audit-tail N` commands glob every matching file and aggregate. See [rate-limiting.md](rate-limiting.md#counters). |

Neither file is a configuration surface — the paths are derived from `KEY_REGISTRY_DB_PATH` and cannot be overridden. The CLI silently degrades when either file is absent (e.g. API not running yet).

## Rate limiting is not env-configured

Per-key rate limits are set at key-issuance time via `comadre-keys issue-key --rpm <n>` and changed via `comadre-keys update-key --rpm <n>` (both capped at 1..10 000). There is no environment variable that sets a global RPM floor, ceiling, or per-IP limit — the registry row is authoritative. See [rate-limiting.md](rate-limiting.md) and [monetization.md](monetization.md).

## URL Validation

All URL fields (`KOKORO_MODEL_URL`, `KOKORO_VOICES_URL`, `QWEN3_MODEL_URL`, `QWEN3_TOKENIZER_URL`) are validated at config-load time:

- Non-empty values must parse as valid HTTP/HTTPS URLs.
- Empty string is allowed for the Qwen3 URLs (skips auto-download — the files must then be present at the configured paths).
- Invalid URLs cause startup to fail with a pydantic validation message.

## Docker Compose Environment

In production, environment variables are set in `compose.yaml` (not `.env` directly). The compose file maps host `.env` values to the `tts-service` container:

```yaml
tts-service:
  build: .
  expose:
    - "8000"
  volumes:
    - comadre-models:/models:rw
    - comadre-voices:/voices:ro
    - comadre-audio:/audio:rw
    - comadre-registry:/var/lib/comadre:rw
  environment:
    KEY_REGISTRY_ENCRYPTION_KEY: ${KEY_REGISTRY_ENCRYPTION_KEY:?KEY_REGISTRY_ENCRYPTION_KEY must be set}
    KEY_REGISTRY_DB_PATH: "${KEY_REGISTRY_DB_PATH:-/var/lib/comadre/registry.db}"
    OPERATOR_CONTACT_HINT: "${OPERATOR_CONTACT_HINT:-Contact your Comadre operator for billing.}"
    BILLING_TIMEZONE: "${BILLING_TIMEZONE:-UTC}"
    DEFAULT_VOICE: "${DEFAULT_VOICE:-kokoro/pm_santa}"
    PORT: "8000"
    ESPEAK_DATA_PATH: /usr/local/share/espeak-ng-data
    NOISE_DIR: /app/noise
    VOICES_DIR: /voices
    KOKORO_MODEL_PATH: /models/kokoro-v1.0.onnx
    KOKORO_VOICES_PATH: /models/voices-v1.0.bin
    QWEN3_MODEL_PATH: /models/qwen3-tts-0.6b-q8_0.gguf
    QWEN3_TOKENIZER_PATH: /models/qwen3-tts-tokenizer-f16.gguf
    QWEN3_CLI_PATH: /usr/local/bin/qwen3-tts-cli
    QWEN3_THREADS: "4"
    QWEN3_ENABLED: "${QWEN3_ENABLED:-true}"
    QWEN3_MODEL_URL: "${QWEN3_MODEL_URL:-}"
    QWEN3_TOKENIZER_URL: "${QWEN3_TOKENIZER_URL:-}"
    KOKORO_MODEL_URL: "${KOKORO_MODEL_URL:-}"
    KOKORO_VOICES_URL: "${KOKORO_VOICES_URL:-}"
  deploy:
    replicas: 1
    resources:
      limits:
        cpus: "4"
        memory: 6G
```

`KEY_REGISTRY_ENCRYPTION_KEY` uses the `?` syntax, so Docker Compose refuses to start if it is missing from `.env`. The TTS service is not exposed on the host network — all external traffic flows through Caddy on 80/443. Scale horizontally by increasing `replicas` (see [rate-limiting.md](rate-limiting.md) for the per-replica rate-limit caveat).

## Complete .env.example

The canonical template lives at `.env.example` in the repository root. At the time of writing its contents are:

```bash
# Comadre — Environment Configuration
# Copy to .env and fill in values.

# Fernet key for encrypting tax IDs at rest in the key registry (REQUIRED).
# Generate with:
#   python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
KEY_REGISTRY_ENCRYPTION_KEY=

# SQLite key registry path. Must match the in-container path used by both the
# tts-service container and the comadre-keys CLI (when run against the same
# mount). Compose bind-mounts the comadre-registry named volume at
# /var/lib/comadre, so the default below keeps the CLI and the service pointed
# at the same file.
KEY_REGISTRY_DB_PATH=/var/lib/comadre/registry.db

# Operator contact string shown in CLI error hints (e.g. your ops email).
OPERATOR_CONTACT_HINT=

# Default voice for TTS when none specified (format: engine/name).
DEFAULT_VOICE=kokoro/pm_santa

# Domain for HTTPS (Caddy auto-provisions Let's Encrypt cert).
# Use "localhost" for a self-signed cert on private networks.
DOMAIN=localhost

# Enable Qwen3 engine. Set to false on hosts where the x86_64 binary cannot
# run (e.g. aarch64 / Oracle Cloud Ampere A1).
QWEN3_ENABLED=true

# Model download URLs (auto-download on first container start; leave empty to
# skip download for that model).
KOKORO_MODEL_URL=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx
KOKORO_VOICES_URL=https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin
QWEN3_MODEL_URL=
QWEN3_TOKENIZER_URL=
```

Advanced voice/model/threading overrides (`VOICES_DIR`, `NOISE_DIR`, `KOKORO_MODEL_PATH`, `QWEN3_CLI_PATH`, `QWEN3_THREADS`, `BILLING_DAY`, `BILLING_TIMEZONE`, `ESPEAK_DATA_PATH`, `PORT`) accept the defaults in the table above and can be set in `.env` only when a deployment needs to deviate.
