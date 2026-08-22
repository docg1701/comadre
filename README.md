# Comadre

<p align="center">
  <img src="assets/logo-comadre.webp" alt="Comadre Logo">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/version-3.0.0-blue" alt="Version 3.0.0">
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/TTS-pocket--tts-ff6f00" alt="pocket-tts">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

**Comadre Manda Áudio Direto, Rápido e Eficiente**

Self-hosted TTS API for Brazilian Portuguese on the **Kyutai pocket-tts**
engine (pinned 2.1.0) with **native voice cloning**: upload a 5-20 second
audio sample, get a clone of that voice usable immediately in the session
and optionally stored on your server. OpenAI-compatible endpoint, CPU-only,
fully offline after first boot.

## Quick Start

```bash
# Clone and configure
git clone git@github.com:docg1701/comadre.git
cd comadre
cp .env.example .env
# Generate the registry encryption key and paste it into .env as
# KEY_REGISTRY_ENCRYPTION_KEY=<value>:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Accept the gated-model terms at https://huggingface.co/kyutai/pocket-tts
# with your HF account, create a token, and paste it into .env as HF_TOKEN=

# Build and run (first boot downloads the model with HF_TOKEN)
docker compose up --build -d

# Issue the first customer + API key via the comadre-keys CLI
docker compose exec tts-service comadre-keys create-customer \
  --name "Acme Demo" --email ops@acme.example --cpf 11144477735
docker compose exec tts-service comadre-keys issue-key \
  --customer <cust_id_from_previous_step> --rpm 60 --price 149
# The issued plaintext (cmdr_live_...) is shown once — copy it now.

# Speak with the default catalog voice (pocket/rafael)
curl -k -X POST https://localhost/v1/audio/speech \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT" \
  -H "Content-Type: application/json" \
  -d '{"input":"Bom dia, como posso ajudar?", "voice":"pocket/rafael"}' \
  --output test.ogg

# Clone a voice (ephemeral, this session only)
curl -k -X POST https://localhost/v1/voices \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT" \
  -F "file=@minha-voz.wav" -F "display_name=Minha voz"

# Clone and store for future use
curl -k -X POST https://localhost/v1/voices \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT" \
  -F "file=@minha-voz.wav" -F "persist=true"

# Speak with the clone (use the "voice" value from the previous response)
curl -k -X POST https://localhost/v1/audio/speech \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT" \
  -H "Content-Type: application/json" \
  -d '{"input":"Olá! Esta é a minha voz clonada.", "voice":"pocket/u_01J2K4M6N8P0Q2R4S6"}' \
  --output clone.ogg
```

`bootstrap.yml` hardens the runtime automatically: after the first boot
passes its health check it blanks `HF_TOKEN` and sets `HF_HUB_OFFLINE=1`
in `.env`, then restarts the service — fully offline, zero manual steps.

## How It Works

```text
POST /v1/audio/speech  { "input": "...", "voice": "pocket/<name>" }
    |
resolve voice (filesystem state LRU or ephemeral clone)
    |
normalize_text() [+ expand_siglas()] — pocket-tts chunks internally
    |
generate_audio(state, text, copy_state=True) -> 24 kHz float32
    |
_samples_to_wav() -> ffmpeg pipeline (EQ/compression/noise + atempo speed)
    |
OGG Opus 24 kbps 16 kHz mono (or WAV 24 kHz)

POST /v1/voices (multipart upload)
    |
auth -> per-IP gate -> per-key RPM -> FIFO lock (shared with speech)
    |
size/duration/format validation (3-30 s, <= 10 MB, wav/mp3)
    |
get_state_for_audio_prompt(tmp, truncate=True)
    |
[persist] export_model_state -> /voices/pocket/u_<ULID>.safetensors + .wav + .json
    |  (else: ephemeral in-memory clone with TTLs)
201 { voice, display_name, persisted, duration_s, sample_rate, expires_at }
```

## Voices (v3)

| Voice | Source | Notes |
|-------|--------|-------|
| `pocket/rafael` | Catalog embedding | Default voice (Kyutai) |
| `pocket/<name>` | `/voices/pocket/<name>.wav` | Operator voice — drop a WAV, available immediately (state materializes lazily) |
| `pocket/u_<ULID>` | API upload | Your clone; ephemeral (session) or persisted on the server |

- **One voice format**: `pocket/<name>` — no engine prefixes.
- **Ephemeral clones**: keyed to your API key, idle TTL 1 h / absolute TTL 24 h,
  max 5 per key, global LRU cap 50 — memory-only, gone on restart.
- **Stored clones**: max 20 per customer, managed via `DELETE /v1/voices/<name>`
  (own voices only) or by the operator on the filesystem.
- **Speed** (0.25-4.0) applies to ALL voices via ffmpeg `atempo` chains.
- **Model upgrades are safe**: the reference WAV is always stored; the clone
  state regenerates automatically when the model hash changes.

## Key Features

- **Single-engine pocket-tts** — kyutai-labs/pocket-tts 2.1.0, language
  `portuguese` (deploy-time `portuguese_24l` variant available).
- **Native voice cloning** — upload 5-20 s of audio and speak with that voice
  in the same session or store it for future requests (LGPD consent required).
- **Sigla preprocessing** — `normalize_text()` (currency/dates/times/numbers) +
  `expand_siglas()` spaced letters (`CNPJ` → `C N P J`), toggled by
  `POCKET_SIGLA_SPACING`.
- **OpenAI-compatible API** (`POST /v1/audio/speech`) — works with any HTTP
  client or workflow tool (n8n: JSON for speech, Form-Data for cloning).
- **Network-isolated runtime** — downloads happen once on first boot with
  `HF_TOKEN`; afterwards `HF_HUB_OFFLINE=1` makes generation fully offline.
- **CPU-only** — 4 vCPU / 8 GB RAM VPS; torch CPU wheel via the pytorch-cpu
  index; optional int8 quantization (`POCKET_QUANTIZE`).
- **Single FIFO queue** per instance (`asyncio.Lock`) — clone encoding and
  speech share the same queue. Scale horizontally via `deploy.replicas` in
  compose.yaml (Caddy load-balances with `least_conn`).
- **HTTPS via Caddy** — auto-TLS reverse proxy with Let's Encrypt or
  self-signed certs.
- **Browser demo** — public landing page with the TTS form plus a "Clonar
  voz" section (consent checkbox, persist option, clone preview) and a
  "Minhas vozes" list with delete buttons.
- **Registry-backed API keys** — issue, rotate, and revoke keys via the
  `comadre-keys` CLI. Keys are stored as SHA-256 hashes in an encrypted
  SQLite registry; tax IDs are Fernet-encrypted at rest.
- **Billing lifecycle verbs** — `comadre-keys mark-paid <prefix> --until
  YYYY-MM-DD` confirms a payment to an exact date (auto-reactivates suspended
  keys); `mark-paid <prefix> --months <1..36>` extends from `paid_until` (if
  today-or-later) or from today (if expired); both accept `--price-monthly`.
  `suspend` / `reactivate` are the manual out-of-cycle levers.
- **Billing reports** — `comadre-keys at-risk --window 5d` previews keys
  expiring soon; `comadre-keys revenue --month current` summarises MRR and
  projected revenue; `--as-of YYYY-MM-DD` replays the audit log for
  historical reports (`BILLING_TIMEZONE`-aware).
- **Automated suspension sweep** — daily cron at 00:30 in the configured
  `BILLING_TIMEZONE` (default UTC) auto-suspends expired manual keys.
- **Per-key rate limiting** — each API key carries its own `rate_limit_rpm`;
  voice-clone uploads consume the same bucket as speech. See
  [docs/rate-limiting.md](docs/rate-limiting.md).
- **Operator observability** — per-key counters snapshot every 15 s to disk;
  `comadre-keys cache-status`, `show <prefix> --audit-tail N`.
- **System health** — `comadre-keys health` renders DB integrity + 0600 modes,
  cron-installed markers, backup liveness, and cache telemetry. Exit 0
  healthy / exit 7 unhealthy JSON.
- **LGPD data operations** — `export-customer` now includes the customer's
  stored voice clones (biometric data) as a `voices` array;
  `delete-customer --hard` purges the clone files alongside the registry
  rows and records `voices_deleted` in the audit log. Uploads require
  explicit consent (landing-page checkbox).
- **Encryption-key rotation** — `comadre-keys rotate-encryption-key`
  re-encrypts every active tax ID atomically.
- **Nightly encrypted backups** — `ansible-playbook backup-keys.yml` produces
  `{registry.db}.backup-<UTC-ISO>.tar.gz.enc`; `restore-keys.yml` rolls back.
- **Operational health assertion playbook** — `ansible-playbook health.yml`
  asserts DB modes, cron entries, backup presence, UFW rules, and the
  in-container health aggregate (plus the pocket engine probe).

## Requirements

- 4 vCPUs, 8 GB RAM (VPS or bare metal)
- ~600 MB disk for models (model ~370 MB + tokenizer/embedding ~2 MB);
  the container image is ~3-3.5 GB (torch CPU + pocket-tts)
- Docker and Docker Compose v2 (Caddy handles external access on ports 80/443)
- Optional: a HuggingFace account + token for the one-time gated-model
  download (accept the terms at <https://huggingface.co/kyutai/pocket-tts>)
- Optional: a 5-20 second WAV/MP3 recording to clone your own voice

## Deployment

Full lifecycle management via Ansible:

```bash
cd deploy/ansible
ansible-playbook playbooks/bootstrap.yml -i inventory/production.yml -e "ansible_become_password=YOUR_SUDO_PASS"  # Deploy
ansible-playbook playbooks/update.yml -i inventory/production.yml     # Update
ansible-playbook playbooks/health.yml -i inventory/production.yml     # Diagnose
ansible-playbook playbooks/cleanup.yml -i inventory/production.yml -e "ansible_become_password=YOUR_SUDO_PASS"   # Remove
```

Air-gapped model deployment: `ansible-playbook playbooks/deploy-models.yml`
with `pocket_model_local` / `pocket_tokenizer_local` / `pocket_rafael_local`
inventory vars (the playbook fails its prerequisite check when they are
empty — that is intentional; the default path is auto-download).

## Documentation

- [docs/api-reference.md](docs/api-reference.md) — API endpoints (speech +
  voices), schemas, error table, curl + n8n examples
- [docs/deployment-guide.md](docs/deployment-guide.md) — Deployment lifecycle,
  HF token step, model deployment, HTTPS
- [docs/configuration-reference.md](docs/configuration-reference.md) —
  Environment variables reference
- [docs/voice-management.md](docs/voice-management.md) — Voice artifacts,
  cloning quotas/TTLs, operator provisioning, LGPD verbs
- [docs/monetization.md](docs/monetization.md) — Billing tiers + LGPD operator
  handbook (incl. voice-clone biometrics)
- [docs/rate-limiting.md](docs/rate-limiting.md) — Per-key algorithm, bucket
  identity, 429 semantics
- [docs/troubleshooting.md](docs/troubleshooting.md) — HF gating/401,
  offline boot, torch/RAM, state regen, upload validation errors
- [docs/api-architecture.md](docs/api-architecture.md) — Internal design,
  queue architecture, VoiceRegistry/LRU, pipelines
- [docs/pocket-tts-migration-feasibility.md](docs/pocket-tts-migration-feasibility.md) —
  Why pocket-tts (v3 decision analysis)
- [docs/pocket-tts-v3-migration-plan.md](docs/pocket-tts-v3-migration-plan.md) —
  The executed migration plan (with the Phase 0 spike record)
- [docs/replica-scaling-report.md](docs/replica-scaling-report.md) — v2-era
  scaling/cost numbers (a v3 addendum lands after the production cutover)

## Load Testing

```bash
# Saturation test (concurrency-based, 6 scenarios)
uv run --group test python scripts/loadtest.py \
  --url https://YOUR_VPS_DOMAIN --api-key cmdr_live_YOUR_PLAINTEXT --scenario all

# Capacity test (rate-based, WhatsApp context, ElevenLabs cost comparison)
uv run --group test python scripts/capacity_test.py \
  --url https://YOUR_VPS_DOMAIN --api-key cmdr_live_YOUR_PLAINTEXT
```

Both scripts default to `--voice pocket/rafael`. Issue a dedicated load-test
key via `comadre-keys issue-key --rpm 10000 --billing-mode complimentary`,
and `comadre-keys revoke-key` it when the run is done.

## Development

```bash
uv sync                                    # Install dependencies (torch CPU index)
uv run pytest                              # Run tests
uv run pytest -m slow                      # Real-model integration tests
uv run ruff check . && uv run mypy src/    # Lint + type check
uv run pre-commit run --all-files          # All quality checks
uv run python scripts/spike_pocket_tts.py  # Tuning harness (RTF, sigla A/B, clone timing)
```

## License

- Comadre: [MIT](LICENSE)
- TTS model: Kyutai Pocket TTS — [cc-by-4.0](https://creativecommons.org/licenses/by/4.0/)
