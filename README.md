# Comadre

<p align="center">
  <img src="assets/logo-comadre.webp" alt="Comadre Logo">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/version-1.6.2-blue" alt="Version 1.6.2">
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/TTS-Kokoro_fp32-ff6f00" alt="Kokoro TTS">
  <img src="https://img.shields.io/badge/TTS-Qwen3_Q8__0-8b5cf6" alt="Qwen3 TTS">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

**Comadre Manda Áudio Direto, Rápido e Eficiente**

Self-hosted dual-engine TTS API optimized for Brazilian Portuguese. Kokoro fp32 for fast built-in voices with perfect sigla pronunciation. Qwen3-TTS C++ Q8_0 for voice cloning. OpenAI-compatible endpoint, CPU-only, network-isolated.

## Why Comadre — Cost & Performance at a Glance

Comadre exists for one reason: **scaling WhatsApp audio production without paying per-minute SaaS bills**. ElevenLabs and reseller aggregators (AI33.pro, etc.) get expensive fast — Comadre's cost is the VPS, full stop, regardless of how much audio you generate.

| What you get | Single replica (~$7/mo VPS) | Two replicas (~$21/mo VPS, validated 2026-04-11) |
|---|---|---|
| Sustainable throughput | **~13 audio messages/min** | **~20 audio messages/min** |
| Audio production rate | ~1.7 minutes of audio per wall-clock minute | ~2.6 minutes of audio per wall-clock minute |
| Realistic monthly capacity (8h × 22 working days) | ~295 hours of audio / ~137,000 messages | **~454 hours of audio / ~211,000 messages** |
| Concurrent active conversations supported (WhatsApp pace) | ~26 in parallel | **~40 in parallel** |
| Mean wait time at 20 req/min sustained | 36 s (within WhatsApp natural pace) | **8.6 s (excellent)** |
| Audio integrity verified | 100% (610/610 requests) | **100% (1,830/1,830 requests across 3 configurations)** |
| LGPD / data privacy | Inherent — audio never leaves your server | Same |
| Per-minute cost at saturation | **$0.00051/min** | **$0.00077/min** |

**Cost comparison at the "Large operation" tier (~211,000 audios/month, ~454 hours of audio):**

| Platform | Monthly cost | Pricing model |
|---|---|---|
| **Comadre 2 replicas** | **~$21** | Fixed VPS — does not grow with volume |
| AI33.pro (Edge tier) | ~$56 | Per-credit, scales linearly |
| AI33.pro (ElevenLabs/MiniMax tier) | ~$102 | Per-credit, scales linearly |
| ElevenLabs Scale + overage | **~$4,646** | Per-character, scales linearly |

Comadre is **~5x cheaper than AI33.pro Edge tier**, **~10x cheaper than AI33.pro ElevenLabs/MiniMax tier**, and **~220x cheaper than ElevenLabs** at this volume. Above this tier the gap only widens — Comadre's marginal cost is the next VPS upgrade (~$15–25 to double capacity), while the SaaS competitors keep charging per audio minute forever.

**Why this works:** Each Kokoro replica is CPU-bound and produces a roughly constant amount of audio per second of wall clock. Two replicas behind a queue-aware Caddy load balancer (`lb_policy least_conn`) extract the maximum throughput a shared 8-CPU host can deliver, with **zero audio corruption across 2,440 verified end-to-end test requests** spanning four configurations.

**Want the deep numbers?**

- [docs/cost-comparison-report.md](docs/cost-comparison-report.md) — Full cost breakdown vs ElevenLabs and AI33.pro at every tier, sizing rules, and the honest list of trade-offs (English).
- [docs/relatorio-comparativo-custos.md](docs/relatorio-comparativo-custos.md) — Same report in Brazilian Portuguese, ready to share with prospects who prefer pt-BR.
- [docs/replica-scaling-report.md](docs/replica-scaling-report.md) — Technical deep-dive: the four-way verification matrix (1 vs 2 replicas, round-robin vs least-conn, 4 vs 3 CPUs per replica), the queue-blindness fix that closed the scaling gap, and the methodology behind every number above.

## Quick Start

```bash
# Clone and configure
git clone git@github.com:docg1701/comadre.git
cd comadre
cp .env.example .env
# Generate the registry encryption key and paste it into .env as
# KEY_REGISTRY_ENCRYPTION_KEY=<value>:
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"

# Build and run
docker compose up --build -d

# Issue the first customer + API key via the comadre-keys CLI
docker compose exec tts-service comadre-keys create-customer \
  --name "Acme Demo" --email ops@acme.example --tax-id 11144477735
docker compose exec tts-service comadre-keys issue-key \
  --customer <cust_id_from_previous_step> --rpm 60 --price 149
# The issued plaintext (cmdr_live_...) is shown once — copy it now.

# Test with Kokoro (fast)
curl -k -X POST https://localhost/v1/audio/speech \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT" \
  -H "Content-Type: application/json" \
  -d '{"input":"Bom dia, como posso ajudar?", "voice":"kokoro/pm_santa"}' \
  --output test.ogg

# Test with Qwen3 (cloned voice, if configured)
curl -k -X POST https://localhost/v1/audio/speech \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT" \
  -H "Content-Type: application/json" \
  -d '{"input":"Seu CPF foi validado com sucesso.", "voice":"qwen/galvani"}' \
  --output test_clone.ogg
```

## How It Works

```text
POST /v1/audio/speech  { "input": "...", "voice": "santa" }
    |
Route to engine by voice name
    |
Preprocess text (normalize, chunk, expand siglas)
    |
Generate speech (Kokoro ONNX or Qwen3 C++ binary)
    |
Post-process audio (EQ, compression, echo, noise mixing)
    |
Return OGG Opus or WAV
```

## Dual-Engine Architecture

| Voice | Engine | Use Case | Latency (4 vCPU) |
|-------|--------|----------|-------------------|
| `kokoro/pm_santa` (M) | Kokoro fp32 | Default, fast, perfect siglas | 5-16s |
| `kokoro/pf_dora` (F) | Kokoro fp32 | Female alternative | 5-16s |
| `kokoro/pm_alex` (M) | Kokoro fp32 | Male alternative | 5-16s |
| `qwen/galvani` | Qwen3-TTS C++ Q8_0 | Voice cloning (pre-configured reference) | 12-37s |
| `qwen/female` | Qwen3-TTS C++ Q8_0 | Qwen3 default female | 12-37s |
| `qwen/male` | Qwen3-TTS C++ Q8_0 | Qwen3 default male | 12-37s |

Each engine has its own:

- **Preprocessing**: Kokoro uses `normalize_text()` + `chunk_text()`. Qwen3 uses `expand_siglas()`.
- **Post-processing**: Kokoro uses radio_warm (EQ, compression, saturation, loudnorm). Qwen3 uses whatsapp-subtle (EQ, compression, atempo 1.15x, echo, noise).
- **Output**: OGG Opus 24kbps 16kHz mono (default) or WAV.

## Key Features

- **Perfect sigla pronunciation** via custom espeak-ng pt_extra dictionary (CPF, CNPJ, FGTS, SUS, LOAS... 67 entries, 34/34 verified)
- **Voice cloning** via Qwen3-TTS with pre-configured reference audio and seed reproducibility
- **OpenAI-compatible API** (`POST /v1/audio/speech`) -- works with any HTTP client or workflow tool
- **Network-isolated** -- zero external API calls after deployment
- **CPU-only** -- runs on a 4 vCPU / 8 GB RAM VPS or any PC
- **Single FIFO queue** per instance (`asyncio.Lock`) -- scale horizontally via `deploy.replicas` in compose.yaml
- **HTTPS via Caddy** -- auto-TLS reverse proxy with Let's Encrypt or self-signed certs
- **Browser demo** -- public landing page at the root path for trying the API from any device (bring your own API key)
- **Registry-backed API keys** -- issue, rotate, and revoke keys via the `comadre-keys` CLI. Keys are stored as SHA-256 hashes in an encrypted SQLite registry; tax IDs are Fernet-encrypted at rest.
- **Billing lifecycle verbs** -- `comadre-keys mark-paid <prefix> --until YYYY-MM-DD` confirms a payment (auto-reactivates suspended keys); `comadre-keys suspend <prefix>` / `comadre-keys reactivate <prefix>` are the manual out-of-cycle levers.
- **Billing reports** -- `comadre-keys at-risk --window 5d` previews active manual keys expiring in the next N days (the Day-04 chase list); `comadre-keys revenue --month current` summarises paid / pending / suspended / complimentary counts, MRR and projected revenue (the Day-05 screenshot).
- **Automated suspension sweep** -- a daily cron at 00:30 in the configured `BILLING_TIMEZONE` (default **UTC**) auto-suspends manual keys whose `paid_until` has elapsed, writing one audit row per key plus a summary row for liveness tracking. Run `comadre-keys suspend-sweep --dry-run` to preview the set without writing, or `comadre-keys suspend-sweep` to manually recover from a failed cron. The billing timezone is a contractual input — operators must communicate the chosen zone to customers, since it governs when `paid_until` expires and keys flip to 401.
- **Per-key rate limiting** -- each API key carries its own `rate_limit_rpm`. Customers on higher tiers get higher throughput; customers on smaller tiers are bounded predictably. Buckets are keyed on the registry's `key_id` and stable across key rotation. See [docs/rate-limiting.md](docs/rate-limiting.md).
- **Operator observability** -- per-key counters (`requests_total`, `rate_limit_429`, `peak_rpm`) snapshot every 15 s to disk. Inspect the auth cache with `comadre-keys cache-status`; inspect a specific key's last-24h activity with `comadre-keys show <key-prefix> --audit-tail N`.

## Requirements

- 4 vCPUs, 8 GB RAM (VPS or bare metal)
- ~2 GB disk for models (Kokoro auto-downloads; Qwen3 requires manual setup -- see [deployment guide](docs/deployment-guide.md))
- Docker and Docker Compose v2 (Caddy reverse proxy handles all external access on ports 80/443)
- Optional: 5-10 second WAV recording for voice cloning (Qwen3 engine)

## Deployment

Full lifecycle management via Ansible:

```bash
cd deploy/ansible
ansible-playbook playbooks/bootstrap.yml -i inventory/production.yml -e "ansible_become_password=YOUR_SUDO_PASS"  # Deploy
ansible-playbook playbooks/update.yml -i inventory/production.yml     # Update
ansible-playbook playbooks/health.yml -i inventory/production.yml     # Diagnose
ansible-playbook playbooks/cleanup.yml -i inventory/production.yml -e "ansible_become_password=YOUR_SUDO_PASS"   # Remove
```

## Documentation

- [docs/api-reference.md](docs/api-reference.md) -- API endpoint spec, schemas, error codes, curl examples
- [docs/deployment-guide.md](docs/deployment-guide.md) -- Deployment lifecycle: bootstrap, update, cleanup, HTTPS, key registry bootstrap
- [docs/configuration-reference.md](docs/configuration-reference.md) -- Environment variables reference
- [docs/monetization.md](docs/monetization.md) -- Customer tiers, per-key pricing, rate-limit lifecycle
- [docs/rate-limiting.md](docs/rate-limiting.md) -- Per-key algorithm, bucket identity, 429 semantics, operator controls
- [docs/troubleshooting.md](docs/troubleshooting.md) -- Common issues with resolution steps
- [docs/api-architecture.md](docs/api-architecture.md) -- Internal API design, queue architecture, post-processing pipelines
- [docs/feasibility-report-tts-engine.md](docs/feasibility-report-tts-engine.md) -- Engine evaluation (10+ configs, 400+ samples)
- [docs/espeak-ng-custom-dictionary.md](docs/espeak-ng-custom-dictionary.md) -- pt_extra dictionary for sigla pronunciation
- [docs/qwen3-tts-internals.md](docs/qwen3-tts-internals.md) -- Qwen3 CLI params, THINK mode, seed reproducibility

## Load Testing

```bash
# Saturation test (concurrency-based, 6 scenarios)
uv run --group test python scripts/loadtest.py \
  --url https://YOUR_VPS_DOMAIN --api-key cmdr_live_YOUR_PLAINTEXT --scenario all

# Capacity test (rate-based, WhatsApp context, ElevenLabs cost comparison)
uv run --group test python scripts/capacity_test.py \
  --url https://YOUR_VPS_DOMAIN --api-key cmdr_live_YOUR_PLAINTEXT
```

Issue a dedicated load-test key via `comadre-keys issue-key --rpm 10000 --billing-mode complimentary`, and `comadre-keys revoke-key` it when the run is done.

## Development

```bash
uv sync                                    # Install dependencies
uv run pytest                              # Run tests
uv run ruff check . && uv run mypy src/    # Lint + type check
uv run pre-commit run --all-files          # All quality checks
```

## License

[MIT](LICENSE)
