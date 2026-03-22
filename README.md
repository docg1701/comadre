# CUMADRE

<p align="center">
  <img src="assets/logo-cumadre.webp" alt="CUMADRE Logo">
</p>

<p align="center">
  <img src="https://img.shields.io/badge/python-3.12+-blue?logo=python&logoColor=white" alt="Python 3.12+">
  <img src="https://img.shields.io/badge/FastAPI-0.115+-009688?logo=fastapi&logoColor=white" alt="FastAPI">
  <img src="https://img.shields.io/badge/API-OpenAI_Compatible-412991?logo=openai&logoColor=white" alt="OpenAI Compatible">
  <img src="https://img.shields.io/badge/license-MIT-green" alt="MIT License">
</p>

**Cumadre Manda Audio Direto, Rapido e Eficiente**

Self-hosted text-to-speech service with voice cloning, optimized for automated customer service responses in Brazilian Portuguese. Integrates with n8n workflows to convert LLM text responses into audio messages using a cloned human voice.

## How it works

1. Customer sends a voice message (WhatsApp, Telegram, Instagram, etc.)
2. n8n workflow transcribes it (Groq Whisper) and generates a text response (LLM)
3. CUMADRE converts the text response into audio using a cloned employee voice
4. n8n sends the audio back to the customer

## Stack

- **KokoClone** — Kokoro TTS (82M params) + Kanade voice conversion (120M params)
- **FastAPI** — HTTP API wrapper (`POST /v1/audio/speech`, OpenAI-compatible)
- **Docker** — Single container deployment
- **n8n** — Workflow orchestration and messaging platform integration

## Requirements

- 4 vCPUs, 8 GB RAM (VPS or bare metal)
- ~3 GB disk for models (auto-downloaded on first run)
- A 5-10 second WAV recording of the voice to clone
- Docker and Docker Compose

## Quick start

```bash
# 1. Clone and build
git clone git@github.com:docg1701/cumadre.git
cd cumadre
docker compose up --build -d

# 2. Copy the reference voice (done once by DevOps)
cp employee_recording.wav voices/employee.wav

# 3. Test
curl -X POST http://localhost:8880/v1/audio/speech \
  -H "Content-Type: application/json" \
  -d '{"input":"Bom dia, como posso ajudar?","voice":"employee"}' \
  --output test.wav
```

## Documentation

- [Implementation Guide](docs/IMPLEMENTATION_GUIDE.md) — Architecture, code, Docker, n8n integration, Telegram, Chatwoot
- [TTS Research Report](docs/VOICE_CLONING_TTS_RESEARCH_REPORT.md) — Evaluation of 18 open-source TTS models
- [Decision Matrix](docs/DECISION_MATRIX.md) — Weighted scoring of all candidates

## License

[MIT](LICENSE)
