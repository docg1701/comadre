---
stepsCompleted: [1, 2, 3, 4, 5, 6]
status: complete
inputDocuments:
  - docs/IMPLEMENTATION_GUIDE.md
date: 2026-03-21
author: Galvani
---

# Product Brief: comadre

<!-- Content will be appended sequentially through collaborative workflow steps -->

## Executive Summary

COMADRE (Comadre Manda Audio Direto, Rapido e Eficiente) is a self-hosted text-to-speech service with optional voice cloning, purpose-built for automated customer service audio responses in Brazilian Portuguese. It runs as a network-isolated Docker service on a cheap VPS or any internet-connected PC, serving n8n chatbot workflows over the local network. The service uses a dual-engine architecture — Kokoro fp32 for fast built-in voices and Qwen3-TTS C++ Q8_0 for voice cloning — behind a FastAPI layer with an OpenAI-compatible endpoint, requiring no cloud dependencies after deployment.

---

## Core Vision

### Problem Statement

Customer service chatbots built on n8n need to respond with natural-sounding audio — not robotic TTS or text-only messages — to maintain trust and engagement on voice-centric platforms like WhatsApp and Telegram. Cloud TTS APIs introduce external dependencies, recurring costs, and data exposure for every customer interaction.

### Problem Impact

Without a self-hosted voice solution, every audio response depends on third-party APIs — creating a single point of failure, ongoing per-request costs, and privacy concerns when customer interaction data leaves the local network.

### Why Existing Solutions Fall Short

- **Cloud TTS APIs** (ElevenLabs, Google, Azure) require internet access on every request, introduce latency, cost per character, and send customer data externally.
- **Kokoro-FastAPI** provides TTS but lacks voice cloning — responses sound generic, not like a real employee.
- **KokoClone** (Kokoro + Kanade voice conversion) was evaluated and rejected — Kanade produces 1/10 diction quality on CPU.
- **Chatterbox Multilingual** was evaluated and rejected — sigla pronunciation fundamentally broken for the legal domain (character-level tokenization, no phoneme control).
- **No single open-source engine** provides both fast built-in voices and voice cloning at acceptable quality on CPU-only hardware.

### Proposed Solution

A Docker service with a dual-engine TTS architecture behind a single FastAPI endpoint (`POST /v1/audio/speech`), deployed via Ansible to a network-isolated VPS. Kokoro fp32 handles fast built-in voices (pm_santa, pf_dora, pm_alex) with perfect sigla pronunciation via espeak-ng custom dictionary. Qwen3-TTS C++ Q8_0 handles voice cloning with a pre-configured reference audio. Voice-based routing selects the engine automatically. Each engine has its own post-processing pipeline optimized for WhatsApp audio delivery (OGG Opus 24kbps 16kHz mono). No internet access required after initial model download. Managed entirely through Ansible playbooks for bootstrap, updates, cleanup, and health monitoring. n8n-side failover pattern enables alerting and text fallback when the service is overloaded.

### Key Differentiators

- **Fully network-isolated** — zero external API calls after deploy, no customer data leaves the local network.
- **Dual-engine architecture** — Kokoro fp32 for speed (RTF 1.1x, perfect sigla pronunciation), Qwen3-TTS C++ Q8_0 for voice cloning (RTF 2.5x).
- **Pre-configured voice cloning** — reference audio placed on server at deploy time, seed-based reproducibility for consistent output.
- **Perfect sigla pronunciation** — custom espeak-ng pt_extra dictionary with 67 entries (CPF, CNPJ, FGTS, SUS, etc.) verified 34/34 correct.
- **Self-hosted on commodity hardware** — runs on a 4 vCPU / 8 GB RAM VPS or any home PC.
- **OpenAI-compatible API** — drop-in integration with n8n HTTP Request nodes.
- **Complete lifecycle management** — Ansible playbooks for bootstrap deploy, safe updates, full cleanup, and health checks.

## Target Users

### Primary Users

#### n8n Workflow Engine (Machine Consumer)

COMADRE's primary consumer is the n8n instance running on the same local network or VPS cluster. n8n workflows call `POST /v1/audio/speech` with text from LLM responses and receive audio files back. There is no human interaction with the TTS service itself — it is a pure API backend.

- **Interaction:** HTTP POST with JSON body, receives WAV/OGG binary response
- **Frequency:** On every customer interaction that requires an audio response
- **Expectation:** Response within 5-16s (Kokoro) or 12-37s (Qwen3), consistent voice quality. WhatsApp conversations are async — latency is acceptable.

#### DevOps Operator (Human Operator)

The person who deploys, updates, monitors, and maintains COMADRE via Ansible playbooks and SSH. Responsible for initial bootstrap, voice file provisioning, health monitoring, and lifecycle management.

- **Interaction:** Ansible CLI, SSH, health endpoint, docker logs
- **Frequency:** Deploy once, update occasionally, monitor periodically
- **Expectation:** Predictable deployment, safe updates without data loss, clear health status

### Secondary Users

#### End Customers (Indirect Beneficiaries)

Customers interacting with the chatbot on WhatsApp, Telegram, or other messaging platforms. They never interact with COMADRE directly — they hear the cloned voice audio delivered by n8n through the messaging platform. Their experience depends on voice quality and response latency, but they are unaware the service exists.

### User Journey

1. **DevOps operator** runs Ansible bootstrap playbook → COMADRE is deployed, models download, warm-up completes
2. **DevOps operator** optionally places clone reference WAV on the server for Qwen3 voice cloning
3. **n8n workflow** receives customer message → processes through STT/LLM → calls COMADRE API (voice name selects engine) → receives OGG Opus audio → sends to customer on WhatsApp
4. **DevOps operator** periodically checks health endpoint and docker stats, runs update playbook when repo changes

## Success Metrics

Service success is measured by operational reliability and audio quality — there are no user acquisition or engagement metrics. COMADRE either works or it doesn't.

### Operational KPIs

| Metric | Target | Measurement |
|---|---|---|
| Response latency (Kokoro) | Typical 5-16s per request | `time curl` against the endpoint with Kokoro voice |
| Response latency (Qwen3) | Typical 12-37s per request | `time curl` against the endpoint with clone voice |
| Audio quality | Natural-sounding pt-BR with correct sigla pronunciation | Manual listening test (20 sample phrases) |
| Service availability | 99%+ uptime (excluding scheduled restarts) | Health endpoint monitoring |
| Throughput (Kokoro) | ~10 req/min per instance on 4 vCPU | Load test with concurrent requests |
| Throughput (Qwen3) | ~4.8 req/min per instance on 4 vCPU | Load test with concurrent requests |
| RAM usage | < 6 GB total (both engines loaded) | `docker stats tts-service` |
| Cold start time | < 120s (model download excluded) | Time from `docker compose up` to healthy |
| Warm-up time | First request after restart < 10s | Health check `start_period` |

### Business Objectives

| Objective | Success Criteria |
|---|---|
| Eliminate cloud TTS dependency | Zero external API calls after deploy |
| Reduce per-interaction cost | $0 marginal cost per audio generation |
| Maintain network isolation | No outbound traffic from TTS container post-deploy |
| Operational simplicity | Single Ansible command for any lifecycle operation |

### Key Performance Indicators

- **Deploy success rate:** Ansible bootstrap completes without manual intervention on a clean VPS
- **Safe update rate:** Repo update playbook preserves voice files and model cache 100% of the time
- **OGG compatibility:** `response_format: ogg` produces valid Telegram-compatible voice notes
- **Memory stability:** RAM does not grow beyond 6 GB over 24h continuous operation (daily restart as safety net; Kokoro leak fixed in phonemizer-fork >=3.3.2)

## MVP Scope

### Core Features

**TTS Service (Docker container):**
- FastAPI server with dual-engine architecture (Kokoro fp32 + Qwen3-TTS C++ Q8_0)
- `POST /v1/audio/speech` — OpenAI-compatible endpoint, accepts JSON, returns OGG Opus audio
- `GET /health` — reports status, available voices, engine load, queue depth, clone configuration
- Bearer token authentication via `API_KEY` environment variable (shared secret, checked on every request)
- Single FIFO queue per instance with asyncio.Lock (horizontal scaling via Caddy load balancer)
- Voice-based engine routing: santa/dora/alex → Kokoro; clone/qwen-female/qwen-male → Qwen3
- Engine-specific post-processing: vibrato_warm (Kokoro), whatsapp-subtle (Qwen3) → OGG Opus 24kbps 16kHz mono
- Engine-specific preprocessing: normalize_text + chunk_text (Kokoro), expand_siglas (Qwen3)
- espeak-ng custom pt_extra dictionary for perfect sigla pronunciation (Kokoro path)
- Qwen3 THINK mode with seed reproducibility for consistent cloned voice output
- Automatic model download on first run (Kokoro ONNX ~325 MB, Qwen3 GGUF ~1.6 GB)
- Dual-engine warm-up on startup
- Brazilian Portuguese via espeak-ng phonemizer (Kokoro) and native BPE tokenizer (Qwen3)

**Docker packaging:**
- Dockerfile based on python:3.12-slim with espeak-ng, ffmpeg, libsndfile
- compose.yaml (Docker Compose v2) with TTS service, volume mounts for voices, models, and noise files
- Resource limits (4 CPU, 6 GB) and health check configured
- Daily restart cron on host as safety net

**Ansible playbooks:**
- `bootstrap.yml` — full deploy from scratch: install Docker, clone repo, copy voice files, configure API key, build and start containers
- `update.yml` — pull repo changes, rebuild container, restart service without losing voices, model cache, or configuration
- `cleanup.yml` — full VPS wipe: stop containers, remove images/volumes/data, uninstall Docker
- `health.yml` — check service status: health endpoint, docker stats, container state, disk usage

**Voice configuration:**
- Built-in Kokoro voices: pm_santa (M, default), pf_dora (F), pm_alex (M)
- Optional clone reference WAV (3-10s) placed on server at deploy time for Qwen3 voice cloning
- Voice selection via `voice` request parameter; `DEFAULT_VOICE` env var for default

**Project documentation:**
- README.md (Brazilian Portuguese) — public-facing project description
- Complete English documentation: API reference, deployment guide, Ansible playbook usage, configuration reference, troubleshooting guide

### Out of Scope

- **No n8n deployment** — n8n runs on a separate VPS, not managed by COMADRE
- **No Chatwoot integration** — not part of this project
- **No human-in-the-loop** — not part of this project
- **No multi-language support** — pt-BR only
- **No GPU support** — CPU-only on commodity hardware
- **No response caching** — measure demand first
- **No HTTPS/TLS** — internal network only, plain HTTP
- **No user management** — single shared API key, no roles or accounts

### MVP Success Criteria

| Criteria | Validation |
|---|---|
| Bootstrap deploys cleanly on a fresh VPS | Run `ansible-playbook bootstrap.yml` on clean Ubuntu, service reaches healthy state |
| Audio generation works end-to-end | `curl POST /v1/audio/speech` with API key returns playable OGG Opus audio with correct voice |
| Dual engine routing works | Kokoro voices (santa, dora, alex) use Kokoro engine; clone/qwen voices use Qwen3 |
| Unauthorized requests rejected | Requests without valid API key return 401 |
| OGG Opus output works for WhatsApp | Output is valid OGG Opus 24kbps 16kHz mono |
| Sigla pronunciation correct | CPF, CNPJ, FGTS, SUS, LOAS etc. pronounce correctly via Kokoro+pt_extra |
| Latency within budget | Kokoro typical 5-16s, Qwen3 typical 12-37s on 4 vCPU |
| Queue handles concurrent requests | Single FIFO queue processes requests sequentially without failures |
| Update preserves data | Run `update.yml`, verify voices, model cache, and API key intact |
| Cleanup is total | Run `cleanup.yml`, verify zero COMADRE artifacts remain on VPS |
| Health check is accurate | `health.yml` reports real container/service state |
| Documentation is complete | All playbooks, API endpoints, and configuration options documented |
