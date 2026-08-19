# Configuration Reference

Comadre is configured via environment variables. All variables are loaded at startup using pydantic-settings. The single required variable is `KEY_REGISTRY_ENCRYPTION_KEY`; everything else has sensible defaults.

## Environment Variables

| Variable | Default | Description | Example |
| --- | --- | --- | --- |
| `KEY_REGISTRY_ENCRYPTION_KEY` | *(required)* | Fernet key used to encrypt tax IDs at rest in the SQLite key registry. Must be a valid 44-character base64 Fernet key. Startup fails if missing or malformed. Uses `SecretStr` internally so the value never appears in logs or error renderings. | *(output of `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`)* |
| `KEY_REGISTRY_DB_PATH` | `./data/keys/registry.db` | SQLite registry file path. Parent directory is created with mode 0700 and the file with mode 0600 on first use. WAL sidecars inherit the same mode. | `/var/lib/comadre/registry.db` |
| `BACKUP_PASSPHRASE` | *(empty)* | Passphrase for AES-256 encryption of the nightly backup tarball. Must be ≥ 16 characters when set; empty is accepted at service boot so a deployment that hasn't yet re-run `bootstrap.yml` with the new env var can still start the auth path. Consumed only by `deploy/ansible/playbooks/backup-keys.yml` and `restore-keys.yml` — the FastAPI app and every `comadre-keys` CLI verb ignore it. Uses `SecretStr` so the value never appears in logs or error renderings. | *(output of `python -c "import secrets; print(secrets.token_urlsafe(32))"`)* |
| `OPERATOR_CONTACT_HINT` | `Contact your Comadre operator for billing.` | Operator contact string echoed in 401 hints for suspended / revoked / past-due keys. Keep it short and customer-facing. | `Contact ops@acme.example for billing.` |
| `BILLING_TIMEZONE` | `UTC` | IANA timezone used for billing-day calculations (first-charge dates, `paid_until` comparisons, stamped note dates) and the daily suspension sweep's day-boundary. Must be a valid zone; startup fails otherwise. **MUST match the `CRON_TZ` envvar set by `deploy/ansible/playbooks/bootstrap.yml`** (sourced from the inventory's `billing_timezone` variable) — drift between the two silently shifts the daily suspension sweep's "today" computation relative to the cron schedule. **Billing-TZ is a contractual input**: whichever zone this variable holds dictates when a customer's `paid_until` expires and their API key flips to 401. Operators MUST communicate the chosen zone to customers at contract time and avoid changing it post-onboarding (a change silently shifts when existing keys go past-due). Default `UTC` is the operator-neutral, internationally predictable choice; override only when you have formally informed the customer base. See also: `comadre-keys mark-paid`, `comadre-keys suspend`, `comadre-keys reactivate` for the operator-hand billing verbs; `comadre-keys at-risk`, `comadre-keys revenue` read the reporting month / look-ahead window in this timezone; `comadre-keys suspend-sweep` is the manual/dry-run entry point for the daily auto-suspension cron. | `America/Sao_Paulo` |
| `BILLING_DAY` | `5` | Day-of-month (1–28) for monthly billing sweeps. Kept inside 1..28 so every month has the date. | `10` |
| `DEFAULT_VOICE` | `pocket/rafael` | Voice used when the request omits `voice`. Format: `pocket/<name>`. | `pocket/galvani` |
| `PORT` | `8000` | HTTP port for the FastAPI server (1..65535). Exposed only inside the Docker network — Caddy fronts 80/443. | `9000` |
| `NOISE_DIR` | `/app/noise` | Directory containing room/hiss noise WAV files used by the post-processing pipeline. | `/app/noise` |
| `VOICES_DIR` | `/voices` | Root directory for voice discovery. Contains a `pocket/` subdirectory (reference `.wav` + optional `.safetensors`/`.json`). Also read by the LGPD CLI verbs. See [voice-management.md](voice-management.md). | `/voices` |
| `POCKET_LANGUAGE` | `portuguese` | Language variant — `portuguese` or `portuguese_24l` (validated). One variant per replica (deploy-time choice). | `portuguese_24l` |
| `POCKET_CONFIG_PATH` | `models/pocket-tts-config/portuguese.yaml` | pocket-tts config YAML (baked into the image with local paths). | `/app/models/pocket-tts-config/portuguese.yaml` |
| `POCKET_MODEL_PATH` | `models/pocket-tts/portuguese/model.safetensors` | pocket-tts model weights (gated download; sha256 of this file is the registry's `model_hash`). | `/models/pocket-tts/portuguese/model.safetensors` |
| `POCKET_TOKENIZER_PATH` | `models/pocket-tts/portuguese/tokenizer.model` | sentencepiece tokenizer. | `/models/pocket-tts/portuguese/tokenizer.model` |
| `POCKET_DEFAULT_VOICE_PATH` | `models/pocket-tts/portuguese/embeddings/rafael.safetensors` | Catalog voice state (rafael). | `/models/pocket-tts/portuguese/embeddings/rafael.safetensors` |
| `POCKET_THREADS` | `4` | CPU threads (≥1), applied via `torch.set_num_threads` AFTER the pocket_tts import (the library pins 1). | `4` |
| `POCKET_QUANTIZE` | `false` | int8 quantization of attention + FFN layers (torchao). Phase 0 spike measured +26% RTF on the distilled model — opt-in per host. | `true` |
| `POCKET_TEMPERATURE` | `0.7` | Generation temperature (≥0). | `0.7` |
| `POCKET_SIGLA_SPACING` | `true` | Apply `expand_siglas` (spaced letters, `CNPJ` → `C N P J`) — the sigla quality lever. | `false` |
| `VOICE_UPLOAD_MAX_MB` | `10` | Upload size cap for voice-clone audio (1-50). | `10` |
| `VOICE_REF_MIN_SECONDS` | `3` | Minimum reference-audio duration (≥1); below → 400 `too_short`. | `3` |
| `VOICE_REF_MAX_SECONDS` | `30` | Maximum reference-audio duration (≥ min); above → 400 `too_long`. The library truncates at 30 s. | `30` |
| `VOICE_EPHEMERAL_IDLE_TTL_SECONDS` | `3600` | Ephemeral-clone idle TTL (swept every 60 s). | `3600` |
| `VOICE_EPHEMERAL_ABSOLUTE_TTL_SECONDS` | `86400` | Ephemeral-clone absolute TTL. | `86400` |
| `VOICE_EPHEMERAL_MAX_PER_KEY` | `5` | Ephemeral clones per API key. | `5` |
| `VOICE_EPHEMERAL_GLOBAL_MAX` | `50` | Global LRU cap for ephemeral clones (cross-key eviction). | `50` |
| `VOICE_STORED_MAX_PER_CUSTOMER` | `20` | Stored (persisted) clones per customer. | `20` |
| `HF_TOKEN` | *(empty)* | HuggingFace token for the ONE-TIME first-boot download of the gated weights (accept the terms at <https://huggingface.co/kyutai/pocket-tts>). Unset after the first boot. | `hf_...` |
| `HF_HUB_OFFLINE` | `0` | `1` = fully offline runtime (cache-only model lookup; missing files fail fast with the "run once with HF_TOKEN" message). Set to `1` after the first boot. | `1` |
| `DOMAIN` | `localhost` | Domain name used by Caddy. A real domain triggers Let's Encrypt; `localhost` uses a self-signed cert from Caddy's internal CA. Compose-level variable, not consumed by the Python process. | `tts.example.com` |

## Auxiliary files

The key registry lives at `KEY_REGISTRY_DB_PATH`, and three sibling files share the same parent directory and mode `0600`:

| Path | Purpose |
| --- | --- |
| `{KEY_REGISTRY_DB_PATH}.invalidate` | Cache-invalidation sentinel. The `comadre-keys` CLI touches this file on every `api_key` mutation; the API stats it on each cache read and flushes the `AuthCache` the moment mtime advances. See [rate-limiting.md](rate-limiting.md#operator-surface). |
| `{KEY_REGISTRY_DB_PATH}.counters.{replica_id}.json` | Per-replica request counters snapshot written every 15 s by the API process (one file per replica, `{replica_id}` = `socket.gethostname()`). The `comadre-keys cache-status` and `show <key-prefix> --audit-tail N` commands glob every matching file and aggregate. See [rate-limiting.md](rate-limiting.md#counters). |
| `{KEY_REGISTRY_DB_PATH}.cron-installed` | Cron-installed marker for the daily suspension sweep, written by `deploy/ansible/playbooks/bootstrap.yml` and removed by `cleanup.yml`. Two ASCII `key=value` lines (`schedule=...`, `cron_tz=...`), mode `0600`. `comadre-keys health` reads this to report the cron's installed status; the container cannot read the host crontab, so the marker is the only source of truth for the CLI. **Do not hand-edit** — manual changes drift from the real crontab and mislead `health`'s cron check. |
| `{KEY_REGISTRY_DB_PATH}.backup-cron-installed` | Cron-installed marker for the nightly `comadre-keys-backup` cron, written by `bootstrap.yml` and removed by `cleanup.yml`. Three ASCII `key=value` lines (`schedule=...`, `cron_tz=...`, `retention_days=...`), mode `0600`. Consumed by both `health.yml` (ansible-layer assertion) **and** `comadre-keys health`'s dedicated `Backup cron` row (Story 4.4). The CLI row renders as `comadre-keys-backup at <schedule> (CRON_TZ=<tz>, retention=<days>d)` when the marker is well-formed (severity `ok`); a missing or unparseable marker flips the row to `warn` and the JSON-mode aggregate to `is_healthy=false` (exit 7). |
| `{KEY_REGISTRY_DB_PATH}.backup-<UTC-ISO>.tar.gz.enc` | Nightly encrypted backup archive written by `deploy/ansible/playbooks/backup-keys.yml`. Contains `registry.db` (SQLite `.backup()` snapshot) + `encryption-key.txt` (the live Fernet key captured at backup time), tarred and encrypted with AES-256-CBC + PBKDF2 via the `BACKUP_PASSPHRASE` env var. Mode `0600`. Retention defaults to 14 days, tunable via the `backup_retention_days` ansible inventory var. `comadre-keys health` globs `*.backup-*.tar.gz.enc` in this directory to report the `Last backup` freshness row. |

None of these files is a configuration surface — the paths are derived from `KEY_REGISTRY_DB_PATH` and cannot be overridden. The CLI silently degrades when any of them is absent (e.g. API not running yet, or the cron has not been installed).

## Rate limiting is not env-configured

Per-key rate limits are set at key-issuance time via `comadre-keys issue-key --rpm <n>` and changed via `comadre-keys update-key --rpm <n>` (both capped at 1..10 000). There is no environment variable that sets a global RPM floor, ceiling, or per-IP limit — the registry row is authoritative. See [rate-limiting.md](rate-limiting.md) and [monetization.md](monetization.md).

## Removed in v3.0.0

All v2 engine variables were removed and are ignored: `ESPEAK_DATA_PATH`,
`KOKORO_MODEL_PATH`, `KOKORO_VOICES_PATH`, `KOKORO_MODEL_URL`,
`KOKORO_VOICES_URL`, `QWEN3_ENABLED`, `QWEN3_CLI_PATH`,
`QWEN3_MODEL_PATH`, `QWEN3_TOKENIZER_PATH`, `QWEN3_THREADS`,
`QWEN3_MODEL_URL`, `QWEN3_TOKENIZER_URL` (the old URL validators were
deleted with them). Model downloads now go through HuggingFace with
pinned revisions — see `docs/deployment-guide.md`.

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
