# Comadre

<p align="center">
  <img src="assets/logo-comadre.webp" alt="Comadre Logo">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/version-1.2.1-blue" alt="Version 1.2.1">
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/TTS-Kokoro_fp32-ff6f00" alt="Kokoro TTS">
  <img src="https://img.shields.io/badge/TTS-Qwen3_Q8__0-8b5cf6" alt="Qwen3 TTS">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

**Comadre Manda Audio Direto, Rapido e Eficiente**

Self-hosted dual-engine TTS API optimized for Brazilian Portuguese. Kokoro fp32 for fast built-in voices with perfect sigla pronunciation. Qwen3-TTS C++ Q8_0 for voice cloning. OpenAI-compatible endpoint, CPU-only, network-isolated.

## Quick Start

```bash
# Clone and configure
git clone git@github.com:docg1701/comadre.git
cd comadre
cp .env.example .env   # Set API_KEY

# Build and run
docker compose up --build -d

# Test with Kokoro (fast)
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":"Bom dia, como posso ajudar?", "voice":"santa"}' \
  --output test.ogg

# Test with Qwen3 (cloned voice, if configured)
curl -X POST http://localhost:8000/v1/audio/speech \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":"Seu CPF foi validado com sucesso.", "voice":"clone"}' \
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
| `santa` (M) | Kokoro fp32 | Default, fast, perfect siglas | 5-16s |
| `dora` (F) | Kokoro fp32 | Female alternative | 5-16s |
| `alex` (M) | Kokoro fp32 | Male alternative | 5-16s |
| `clone` | Qwen3-TTS C++ Q8_0 | Voice cloning (pre-configured reference) | 12-37s |
| `qwen-female` | Qwen3-TTS C++ Q8_0 | Qwen3 default female | 12-37s |
| `qwen-male` | Qwen3-TTS C++ Q8_0 | Qwen3 default male | 12-37s |

Each engine has its own:

- **Preprocessing**: Kokoro uses `normalize_text()` + `chunk_text()`. Qwen3 uses `expand_siglas()`.
- **Post-processing**: Kokoro uses vibrato_warm (vibrato, EQ, exciter, compression, echo, noise). Qwen3 uses whatsapp-subtle (EQ, compression, atempo 1.15x, echo, noise).
- **Output**: OGG Opus 24kbps 16kHz mono (default) or WAV.

## Key Features

- **Perfect sigla pronunciation** via custom espeak-ng pt_extra dictionary (CPF, CNPJ, FGTS, SUS, LOAS... 67 entries, 34/34 verified)
- **Voice cloning** via Qwen3-TTS with pre-configured reference audio and seed reproducibility
- **OpenAI-compatible API** (`POST /v1/audio/speech`) -- works with any HTTP client or workflow tool
- **Network-isolated** -- zero external API calls after deployment
- **CPU-only** -- runs on a 4 vCPU / 8 GB RAM VPS or any PC
- **Single FIFO queue** per instance (`asyncio.Lock`) -- scale horizontally for concurrency

## Requirements

- 4 vCPUs, 8 GB RAM (VPS or bare metal)
- ~2 GB disk for models (Kokoro auto-downloads; Qwen3 requires manual setup -- see [deployment guide](docs/deployment-guide.md))
- Docker and Docker Compose v2
- Optional: 5-10 second WAV recording for voice cloning (Qwen3 engine)

## Deployment

Full lifecycle management via Ansible:

```bash
cd deploy/ansible
ansible-playbook playbooks/bootstrap.yml -i inventory/production.yml  # Deploy
ansible-playbook playbooks/update.yml -i inventory/production.yml     # Update
ansible-playbook playbooks/health.yml -i inventory/production.yml     # Diagnose
ansible-playbook playbooks/cleanup.yml -i inventory/production.yml    # Remove
```

## Documentation

- [docs/api-reference.md](docs/api-reference.md) -- API endpoint spec, schemas, error codes, curl examples
- [docs/deployment-guide.md](docs/deployment-guide.md) -- Deployment lifecycle: bootstrap, update, cleanup, health, models
- [docs/configuration-reference.md](docs/configuration-reference.md) -- Environment variables reference
- [docs/troubleshooting.md](docs/troubleshooting.md) -- Common issues with resolution steps
- [docs/api-architecture.md](docs/api-architecture.md) -- Internal API design, queue architecture, post-processing pipelines
- [docs/feasibility-report-tts-engine.md](docs/feasibility-report-tts-engine.md) -- Engine evaluation (10+ configs, 400+ samples)
- [docs/espeak-ng-custom-dictionary.md](docs/espeak-ng-custom-dictionary.md) -- pt_extra dictionary for sigla pronunciation
- [docs/qwen3-tts-internals.md](docs/qwen3-tts-internals.md) -- Qwen3 CLI params, THINK mode, seed reproducibility

## Development

```bash
uv sync                                    # Install dependencies
uv run pytest                              # Run tests
uv run ruff check . && uv run mypy src/    # Lint + type check
uv run pre-commit run --all-files          # All quality checks
```

## License

[MIT](LICENSE)
