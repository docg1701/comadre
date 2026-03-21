---
stepsCompleted: [1, 2, 3, 4, 5, 6]
status: complete
inputDocuments:
  - docs/IMPLEMENTATION_GUIDE.md
date: 2026-03-21
author: Galvani
---

# Product Brief: cumadre

<!-- Content will be appended sequentially through collaborative workflow steps -->

## Executive Summary

CUMADRE (Cumadre Manda Audio Direto, Rapido e Eficiente) is a self-hosted text-to-speech service with zero-shot voice cloning, purpose-built for automated customer service audio responses in Brazilian Portuguese. It runs as a network-isolated Docker service on a cheap VPS or any internet-connected PC, serving n8n chatbot workflows over the local network. The service wraps KokoClone (Kokoro TTS + Kanade voice conversion) behind a thin FastAPI layer with an OpenAI-compatible endpoint, requiring no cloud dependencies after deployment.

---

## Core Vision

### Problem Statement

Customer service chatbots built on n8n need to respond with natural-sounding audio — not robotic TTS or text-only messages — to maintain trust and engagement on voice-centric platforms like WhatsApp and Telegram. Cloud TTS APIs introduce external dependencies, recurring costs, and data exposure for every customer interaction.

### Problem Impact

Without a self-hosted voice solution, every audio response depends on third-party APIs — creating a single point of failure, ongoing per-request costs, and privacy concerns when customer interaction data leaves the local network.

### Why Existing Solutions Fall Short

- **Cloud TTS APIs** (ElevenLabs, Google, Azure) require internet access on every request, introduce latency, cost per character, and send customer data externally.
- **Kokoro-FastAPI** provides TTS but lacks voice cloning — responses sound generic, not like a real employee.
- **KokoClone** provides the full TTS + voice cloning pipeline but ships without a REST API, Dockerfile, or any deployment tooling.

### Proposed Solution

A minimal Docker service that wraps KokoClone's Python API with a single FastAPI endpoint (`POST /v1/audio/speech`), deployed via Ansible to a network-isolated VPS. The service receives text from n8n workflows, generates speech with Kokoro, converts it to a cloned employee voice with Kanade, and returns WAV or OGG audio. No internet access required after initial model download. Managed entirely through Ansible playbooks for bootstrap, updates, cleanup, and health monitoring.

### Key Differentiators

- **Fully network-isolated** — zero external API calls after deploy, no customer data leaves the local network.
- **Zero-shot voice cloning** — a single 3-10s WAV reference produces consistent employee-voice responses without training.
- **Self-hosted on commodity hardware** — runs on a 4 vCPU / 8 GB RAM VPS or any home PC.
- **OpenAI-compatible API** — drop-in integration with n8n HTTP Request nodes.
- **Complete lifecycle management** — Ansible playbooks for bootstrap deploy, safe updates, full cleanup, and health checks.

## Target Users

### Primary Users

#### n8n Workflow Engine (Machine Consumer)

CUMADRE's primary consumer is the n8n instance running on the same local network or VPS cluster. n8n workflows call `POST /v1/audio/speech` with text from LLM responses and receive audio files back. There is no human interaction with the TTS service itself — it is a pure API backend.

- **Interaction:** HTTP POST with JSON body, receives WAV/OGG binary response
- **Frequency:** On every customer interaction that requires an audio response
- **Expectation:** Response within 1-3 seconds, consistent voice quality

#### DevOps Operator (Human Operator)

The person who deploys, updates, monitors, and maintains CUMADRE via Ansible playbooks and SSH. Responsible for initial bootstrap, voice file provisioning, health monitoring, and lifecycle management.

- **Interaction:** Ansible CLI, SSH, health endpoint, docker logs
- **Frequency:** Deploy once, update occasionally, monitor periodically
- **Expectation:** Predictable deployment, safe updates without data loss, clear health status

### Secondary Users

#### End Customers (Indirect Beneficiaries)

Customers interacting with the chatbot on WhatsApp, Telegram, or other messaging platforms. They never interact with CUMADRE directly — they hear the cloned voice audio delivered by n8n through the messaging platform. Their experience depends on voice quality and response latency, but they are unaware the service exists.

### User Journey

1. **DevOps operator** runs Ansible bootstrap playbook → CUMADRE is deployed, models download, warm-up completes
2. **DevOps operator** copies employee reference WAV to the voices directory
3. **n8n workflow** receives customer message → processes through STT/LLM → calls CUMADRE API → receives audio → sends to customer
4. **DevOps operator** periodically checks health endpoint and docker stats, runs update playbook when repo changes

## Success Metrics

Service success is measured by operational reliability and audio quality — there are no user acquisition or engagement metrics. CUMADRE either works or it doesn't.

### Operational KPIs

| Metric | Target | Measurement |
|---|---|---|
| Response latency | < 3s per request (short phrases ~15 words) | `time curl` against the endpoint |
| Audio quality | Natural-sounding cloned voice in pt-BR | Manual listening test (20 sample phrases) |
| Service availability | 99%+ uptime (excluding scheduled restarts) | Health endpoint monitoring |
| Throughput | 20-60 req/min on 4 vCPU | Load test with concurrent requests |
| RAM usage | < 3 GB steady state | `docker stats tts-service` |
| Cold start time | < 120s (model download excluded) | Time from `docker compose up` to healthy |
| Warm-up time | First request after restart < 5s | Health check `start_period` |

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
- **Memory stability:** RAM does not grow beyond 4 GB over 24h continuous operation (mitigated by daily restart cron)

## MVP Scope

### Core Features

**TTS Service (Docker container):**
- FastAPI server wrapping KokoClone's Python API (~80 lines)
- `POST /v1/audio/speech` — OpenAI-compatible endpoint, accepts JSON, returns WAV or OGG
- `GET /health` — reports status and available voices
- Bearer token authentication via `API_KEY` environment variable (shared secret, checked on every request)
- Configurable worker count via `WORKERS` env var (default 1, increase to scale throughput at cost of RAM)
- Automatic model download from HuggingFace on first run
- Warm-up on startup to prevent slow first request
- Brazilian Portuguese via espeak-ng phonemizer

**Docker packaging:**
- Dockerfile based on python:3.12-slim with espeak-ng, ffmpeg, libsndfile
- docker-compose.yml with TTS service, volume mounts for voices and model cache
- Resource limits and health check configured
- Daily restart cron on host to mitigate Kokoro memory leak

**Ansible playbooks:**
- `bootstrap.yml` — full deploy from scratch: install Docker, clone repo, copy voice files, configure API key, build and start containers
- `update.yml` — pull repo changes, rebuild container, restart service without losing voices, model cache, or configuration
- `cleanup.yml` — full VPS wipe: stop containers, remove images/volumes/data, uninstall Docker
- `health.yml` — check service status: health endpoint, docker stats, container state, disk usage

**Voice configuration:**
- Single employee reference WAV (3-10s) mounted as volume
- Configurable via `DEFAULT_VOICE` environment variable

**Project documentation:**
- README.md (Brazilian Portuguese) — public-facing project description
- Complete English documentation: API reference, deployment guide, Ansible playbook usage, configuration reference, troubleshooting guide

### Out of Scope

- **No n8n deployment** — n8n runs on a separate VPS, not managed by CUMADRE
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
| Audio generation works end-to-end | `curl POST /v1/audio/speech` with API key returns playable WAV with cloned voice |
| Unauthorized requests rejected | Requests without valid API key return 401 |
| OGG output works for Telegram | `response_format: ogg` produces valid OGG/Vorbis audio |
| Latency within budget | < 3s for ~15 word phrases on 4 vCPU |
| Multiple workers function correctly | Service runs with `WORKERS=2`, handles concurrent requests |
| Update preserves data | Run `update.yml`, verify voices, model cache, and API key intact |
| Cleanup is total | Run `cleanup.yml`, verify zero CUMADRE artifacts remain on VPS |
| Health check is accurate | `health.yml` reports real container/service state |
| Documentation is complete | All playbooks, API endpoints, and configuration options documented |
