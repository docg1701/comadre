# Comadre

<p align="center">
  <img src="assets/logo-comadre.webp" alt="Comadre Logo">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/version-3.1.13-blue" alt="Version 3.1.13">
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/TTS-pocket--tts-ff6f00" alt="pocket-tts">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

<!-- markdownlint-disable-next-line MD036 -- tagline, intentionally not a heading -->
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

**Speech synthesis — `POST /v1/audio/speech`**

1. The request carries the text (`input`) and a `voice` such as `pocket/rafael`.
2. The server resolves that voice: a stored clone from disk (LRU-cached) or an
   ephemeral in-memory one.
3. The text is normalized (currency, dates, times, phones, percent, numbers;
   emoji/URLs stripped; siglas read intact) — pocket-tts handles long texts
   by chunking them internally.
4. pocket-tts generates raw audio at 24 kHz (seed/temperature control the
   sampling when provided; a leading comma warm-up prevents the first
   syllable being swallowed).
5. An ffmpeg pass applies EQ, compression and loudness normalization, a
   500 ms lead silence (masks the clipped first phoneme) and speed
   adjustment when `speed != 1.0`.
6. The result is returned as OGG Opus 24 kbps 16 kHz mono `-application voip`
   (compatível com WhatsApp), MP3 64 kbps 44.1 kHz mono (compatível), or WAV
   24 kHz mono — filename `comadre-<voice>.<fmt>`.

**Voice cloning — `POST /v1/voices` (multipart upload)**

1. The uploaded audio is authenticated, rate-limited, then validated:
   any soundfile-readable format (WAV, MP3, OGG/Opus — WhatsApp voice notes
   work as-is — or FLAC), 3–30 s, up to 10 MB.
2. A voice embedding is extracted from the sample.
3. If `persist=true`, the clone is saved to `/voices/pocket/` as
   `u_<ULID>.safetensors` (model state) + `u_<ULID>.wav` (reference audio,
   transcoded to PCM 24 kHz mono) + `u_<ULID>.json` (metadata); otherwise it
   lives only in memory and expires after a few hours.
4. The response returns the new voice name plus duration and sample rate.

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
- **Smart pt-BR preprocessing** — `normalize_text()` reads currency, dates
  (full + short), times (`14:00`, `9h30`), phones, percent and the `24/7`
  idiom naturally, strips emoji/URLs/stray slashes. Siglas are read
  intact — letter-spacing was removed after A/B testing.
- **OpenAI-compatible API** (`POST /v1/audio/speech`) — works with any HTTP
  client or workflow tool (n8n: JSON for speech, Form-Data for cloning).
- **Network-isolated runtime** — downloads happen once on first boot with
  `HF_TOKEN`; afterwards `HF_HUB_OFFLINE=1` makes generation fully offline.
- **CPU-only** — 4 vCPU / 8 GB RAM VPS; torch CPU wheel via the pytorch-cpu
  index; optional int8 quantization (`POCKET_QUANTIZE`).
- **Measured performance** — sustained ~15 audios/min on the default
  single-replica 4 vCPU deployment (~22k audios/day), scaling to ~30/min with
  2 replicas on an 8 vCPU host; typical-message latency p50 ≈ 2–6 s.
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
- Optional: a 5-20 second recording to clone your own voice — WAV, MP3,
  OGG/Opus (WhatsApp voice notes work as-is), or FLAC;
  [docs/voice-reference-script.md](docs/voice-reference-script.md) has a
  ready-to-read pt-BR script engineered for clone quality

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
- [docs/voice-reference-script.md](docs/voice-reference-script.md) —
  Read-aloud pt-BR script for recording cloning reference audio
- [docs/monetization.md](docs/monetization.md) — Billing tiers + LGPD operator
  handbook (incl. voice-clone biometrics)
- [docs/rate-limiting.md](docs/rate-limiting.md) — Per-key algorithm, bucket
  identity, 429 semantics, per-IP pre-auth gates
- [docs/troubleshooting.md](docs/troubleshooting.md) — HF gating/401,
  offline boot, torch/RAM, state regen, upload validation errors
- [docs/api-architecture.md](docs/api-architecture.md) — Internal design,
  queue architecture, VoiceRegistry/LRU, pipelines
- [docs/local-testing-guide.md](docs/local-testing-guide.md) — End-to-end
  local run (models, dev server, smoke tests)
- [docs/proxmox-vm-setup.md](docs/proxmox-vm-setup.md) — Proxmox VM creation
  guide for the target host

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
