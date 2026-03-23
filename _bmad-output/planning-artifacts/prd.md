---
stepsCompleted: [step-01-init, step-02-discovery, step-02b-vision, step-02c-executive-summary, step-03-success, step-04-journeys, step-05-domain-skipped, step-06-innovation-skipped, step-07-project-type, step-08-scoping, step-09-functional, step-10-nonfunctional, step-11-polish, step-12-complete]
status: complete
inputDocuments:
  - _bmad-output/planning-artifacts/product-brief-cumadre-2026-03-21.md
workflowType: 'prd'
classification:
  projectType: api_backend
  domain: general
  complexity: low
  projectContext: greenfield
---

# Product Requirements Document - cumadre

**Author:** Galvani
**Date:** 2026-03-21

## Executive Summary

CUMADRE (Cumadre Manda Audio Direto, Rapido e Eficiente) is a self-hosted text-to-speech service with optional voice cloning, purpose-built for automated customer service audio in Brazilian Portuguese. It uses a dual-engine architecture — Kokoro fp32 for fast built-in voices with perfect sigla pronunciation, and Qwen3-TTS C++ Q8_0 for voice cloning — behind a FastAPI endpoint compatible with the OpenAI audio API, packaged as a Docker service and deployed via Ansible to commodity hardware. The sole consumer is n8n workflow automation on the same local network — no human interacts with the service directly.

After initial deployment, CUMADRE requires zero internet access, zero per-request cost, and sends zero customer data externally. A DevOps operator manages the full lifecycle (bootstrap, update, cleanup, health) through Ansible playbooks.

### What Makes This Special

No single open-source TTS engine provides both fast built-in voices and voice cloning at acceptable quality on CPU-only hardware. After evaluating 10+ engine configurations (400+ audio samples), CUMADRE combines two complementary engines: Kokoro fp32 (RTF 1.1x, 10/10 sigla pronunciation via custom espeak-ng dictionary) for speed, and Qwen3-TTS C++ Q8_0 (RTF 2.5x, native voice cloning) for personalization. Cloud alternatives (ElevenLabs, Google, Azure) require internet on every request, introduce per-character cost, and expose customer data. KokoClone was evaluated and rejected (Kanade produces 1/10 diction quality on CPU). Chatterbox Multilingual was rejected (sigla pronunciation fundamentally broken).

CUMADRE is the productization layer: a FastAPI server with voice-based engine routing, engine-specific post-processing pipelines (vibrato_warm for Kokoro, whatsapp-subtle for Qwen3), a Dockerfile, compose.yaml, and four Ansible playbooks. It turns two research-grade inference engines into a deploy-once, zero-maintenance production service optimized for WhatsApp audio delivery (OGG Opus 24kbps 16kHz mono).

## Project Classification

- **Project Type:** API Backend — single REST endpoint consumed by n8n over HTTP
- **Domain:** General — no regulated industry, no compliance requirements beyond API key auth
- **Complexity:** Low — single-purpose service, one consumer, no multi-tenancy or user management
- **Project Context:** Greenfield — new service built from scratch

## Success Criteria

### User Success

**n8n Workflow Engine (primary consumer):**
- Receives playable OGG Opus audio from every valid API call
- Response latency: Kokoro typical 5-16s, Qwen3 typical 12-37s (acceptable for async WhatsApp)
- Consistent voice quality across requests (Qwen3 seed reproducibility for cloned voice)
- Drop-in integration via OpenAI-compatible endpoint — no custom client code

**DevOps Operator:**
- Single Ansible command for any lifecycle operation (bootstrap, update, cleanup, health)
- Bootstrap completes without manual intervention on a clean Ubuntu VPS
- Updates preserve voice files, model cache, and API key 100% of the time
- Clear health status via endpoint and playbook

### Business Success

| Objective | Success Criteria |
|---|---|
| Eliminate cloud TTS dependency | Zero external API calls after deploy |
| Zero marginal cost | $0 per audio generation — no per-character fees |
| Network isolation | No outbound traffic from TTS container post-deploy |
| Operational simplicity | Single Ansible command for any lifecycle operation |

### Technical Success

| Metric | Target | Measurement |
|---|---|---|
| Response latency (Kokoro) | Typical 5-16s per request | `time curl` with Kokoro voice |
| Response latency (Qwen3) | Typical 12-37s per request | `time curl` with clone voice |
| Service availability | 99%+ uptime (excluding scheduled restarts) | Health endpoint monitoring |
| Throughput (Kokoro) | ~10 req/min per instance on 4 vCPU | Load test |
| Throughput (Qwen3) | ~4.8 req/min per instance on 4 vCPU | Load test |
| RAM usage | < 6 GB total (both engines) | `docker stats tts-service` |
| Cold start time | < 120s (model download excluded) | Time from `docker compose up` to healthy |
| Sigla pronunciation | 34/34 correct via Kokoro+pt_extra | Listening test |

### Measurable Outcomes

- Deploy success rate: Bootstrap completes on clean VPS without manual intervention
- Safe update rate: `update.yml` preserves voices and model cache 100% of the time
- OGG Opus compatibility: output produces valid WhatsApp-compatible voice notes (24kbps 16kHz mono)
- Auth enforcement: Requests without valid API key return 401
- Dual engine routing: voice name correctly routes to Kokoro or Qwen3
- Sigla pronunciation: CPF, CNPJ, FGTS, SUS, LOAS etc. pronounce correctly via Kokoro+pt_extra
- Cleanup completeness: `cleanup.yml` leaves zero CUMADRE artifacts on VPS


## User Journeys

### Journey 1: First Deployment — Meet Carlos, the DevOps Operator

Carlos maintains the infrastructure for a small customer service operation. He's been asked to get voice responses working for the WhatsApp chatbot — without adding another cloud dependency. He finds CUMADRE.

**Opening Scene:** Carlos has a clean Ubuntu 22.04 VPS with 4 vCPU and 8 GB RAM. He clones the CUMADRE repo and reviews the deployment docs.

**Rising Action:** He configures the Ansible inventory with his VPS IP, sets an `API_KEY`, and optionally places a 5-second WAV recording of the employee for voice cloning. He runs `ansible-playbook bootstrap.yml`.

**Climax:** Ansible installs Docker, clones the repo to the VPS, builds the container, downloads models (Kokoro ~325 MB, Qwen3 ~1.6 GB), compiles the espeak-ng pt_extra dictionary, and starts the service. The health check goes green. Carlos tests with voice "santa" — and hears natural Brazilian Portuguese with perfect sigla pronunciation. He tests with voice "clone" — and hears the employee's cloned voice.

**Resolution:** Carlos configures the n8n HTTP Request node to point at the CUMADRE endpoint. The chatbot now responds with natural voice audio. No cloud API key, no per-request billing, no data leaving the network.

### Journey 2: Routine Operation — n8n Handles a Customer Interaction

**Opening Scene:** A customer sends a WhatsApp message asking about their order status. The n8n workflow receives the message via webhook.

**Rising Action:** n8n processes the message through STT (if voice) and the LLM, which generates a response: "Seu pedido foi enviado ontem e deve chegar até sexta-feira." The workflow POSTs this text to CUMADRE's `/v1/audio/speech` endpoint with `response_format: ogg` and the bearer token.

**Climax:** CUMADRE routes to the Kokoro engine (voice "santa"), preprocesses the text (normalize numbers, chunk sentences), generates speech, applies the vibrato_warm post-processing pipeline, and returns OGG Opus audio in ~10 seconds.

**Resolution:** n8n sends the OGG Opus audio as a voice note back to the customer on WhatsApp. The customer hears a natural voice with correct sigla pronunciation — not a robot. The entire exchange happened on the local network. WhatsApp conversations are async, so the latency is imperceptible.

### Journey 3: Update Cycle — Carlos Keeps CUMADRE Current

**Opening Scene:** A new CUMADRE release adds OGG quality improvements. Carlos needs to update without disrupting the live service.

**Rising Action:** Carlos runs `ansible-playbook update.yml`. Ansible pulls the latest repo, rebuilds the Docker image, and restarts the container.

**Climax:** The service comes back up. Carlos checks: voice files still mounted, model cache intact, API key unchanged. The health endpoint returns green.

**Resolution:** Carlos verifies with a test request. The updated service is live with zero data loss and minimal downtime.

### Journey 4: Troubleshooting — Something Breaks at 2 AM

**Opening Scene:** The n8n workflow starts getting timeouts from CUMADRE. Carlos gets an alert.

**Rising Action:** Carlos runs `ansible-playbook health.yml` from his laptop. It reports: container running, health endpoint returning 200, but `docker stats` shows RAM at 3.8 GB and climbing — the known Kokoro memory leak.

**Climax:** Carlos confirms the daily restart cron is set. For immediate relief, he restarts the container manually: `docker compose restart tts-service`. RAM drops back to normal levels.

**Resolution:** The service recovers. The Kokoro memory leak is fixed in phonemizer-fork >=3.3.2, so the daily restart is a safety net. Carlos verifies the cron job schedule and logs the incident.

### Journey 5: Full Decommission — End of Life

**Opening Scene:** The operation migrates to a different TTS solution. Carlos needs to clean up the VPS completely.

**Rising Action:** Carlos runs `ansible-playbook cleanup.yml`. Ansible stops containers, removes images, volumes, data, and uninstalls Docker.

**Resolution:** Zero CUMADRE artifacts remain on the VPS. The machine is clean for reuse.

### Journey Requirements Summary

| Journey | Capabilities Revealed |
|---|---|
| First Deployment | Bootstrap playbook, model auto-download, health endpoint, voice mounting, warm-up |
| Routine Operation | `/v1/audio/speech` endpoint, OGG Opus output, bearer auth, dual-engine routing, OpenAI-compatible API |
| Update Cycle | Update playbook, data preservation (voices, models, config), container rebuild |
| Troubleshooting | Health playbook, `docker stats` visibility, container restart, queue depth monitoring |
| Decommission | Cleanup playbook, complete artifact removal |

## API Backend Specific Requirements

### Project-Type Overview

CUMADRE is a single-purpose API backend: one generation endpoint, one health endpoint, bearer token auth, JSON in, binary audio out. It follows the OpenAI audio API contract so existing HTTP clients and n8n nodes work without custom integration code.

### Endpoint Specifications

| Endpoint | Method | Purpose | Request | Response |
|---|---|---|---|---|
| `/v1/audio/speech` | POST | Generate speech audio | JSON body | OGG Opus binary (or WAV) |
| `/health` | GET | Service status, voices, engine load, queue | None | JSON |

#### `POST /v1/audio/speech`

- **Request body:** JSON with `input` (text, max 500 chars Kokoro / 300 chars Qwen3), `voice` (voice name — routes to engine), `response_format` (`ogg` default or `wav`), `destination` (optional: `whatsapp`, `telegram`, `messenger` — determines optimal encoding parameters)
- **Voice routing:** `santa`, `dora`, `alex` → Kokoro fp32; `clone` → Qwen3 with reference; `qwen-female`, `qwen-male` → Qwen3 without cloning
- **Response:** Binary audio file with appropriate `Content-Type` header (default OGG Opus 24kbps 16kHz mono)
- **Auth:** `Authorization: Bearer <API_KEY>` required on every request
- **Timeout:** 120s per request, 240s total with n8n-side failover

#### `GET /health`

- **Response:** JSON with service status, available voices, engine load, queue depth, clone configuration, uptime, memory
- **Auth:** No authentication required (monitoring-friendly)

### Authentication Model

- Single shared secret via `API_KEY` environment variable
- Bearer token scheme: `Authorization: Bearer <token>`
- Checked on every `/v1/audio/speech` request
- 401 Unauthorized returned for missing or invalid tokens
- No user management, no roles, no token rotation — single operator, single key
- Health endpoint unauthenticated for monitoring integration

### Data Schemas

**Request (POST /v1/audio/speech):**
```json
{
  "input": "Text to synthesize in pt-BR",
  "voice": "santa",
  "response_format": "ogg",
  "destination": "whatsapp"
}
```

**Response:** Binary audio stream (`audio/ogg` or `audio/wav`)

### Platform Audio Format Requirements

The `destination` parameter (optional) allows the API to optimize the output encoding for each messaging platform. When omitted, defaults to OGG Opus with standard settings (works for all platforms).

| Platform | Voice Note Format | Also Accepts | Max Size | Voice Note UX? | API |
|---|---|---|---|---|---|
| **WhatsApp** | OGG Opus (required for waveform) | AAC, MP3, AMR, MP4 | 16 MB | Yes (OGG Opus only) | Cloud API `POST /messages` |
| **Telegram** | OGG Opus (required for waveform) | MP3, M4A (render as audio file) | 50 MB | Yes (OGG Opus only) | Bot API `sendVoice` |
| **Messenger** | OGG Opus or MP3 | WAV, OGG | 25 MB | No (audio player) | Send API `POST /me/messages` |
| **Instagram Direct** | AAC / M4A | WAV, MP4 | 25 MB | No (audio player) | Messenger Platform API |

**Key insights:**
- **WhatsApp + Telegram**: OGG Opus required for native voice note waveform UX. Other formats render as generic audio attachments.
- **Messenger**: Accepts OGG Opus and MP3 — renders as audio player regardless (no voice note UX via API).
- **Instagram Direct**: Requires AAC/M4A format (does not accept OGG Opus). Renders as audio player.
- **Default encoding**: OGG Opus mono 16kHz 24kbps — works for WhatsApp, Telegram, and Messenger.
- **Instagram encoding**: AAC M4A mono 44.1kHz 64kbps — required for Instagram Direct compatibility.
- The `destination` parameter selects the correct ffmpeg encoding pipeline. Default is `whatsapp` (OGG Opus).

**Health Response (GET /health):**
```json
{
  "status": "healthy",
  "voices": ["santa", "dora", "alex", "clone", "qwen-female", "qwen-male"],
  "engines": {
    "kokoro": {"loaded": true, "voices": ["santa", "dora", "alex"]},
    "qwen3": {"loaded": true, "model": "q8_0", "clone_reference": "configured"}
  },
  "queue_depth": 0,
  "clone_configured": true,
  "uptime_seconds": 3600,
  "memory_mb": 4200,
  "version": "0.2.0"
}
```

### Error Codes

| Code | Condition |
|---|---|
| 200 | Success — audio binary returned |
| 401 | Missing or invalid API key |
| 400 | Malformed request (missing input, invalid format) |
| 404 | Requested voice not found |
| 500 | Internal error (model failure, encoding error) |
| 503 | Service not ready (still warming up) |

### Rate Limits & Throughput

- No explicit rate limiting — single consumer (n8n) on local network
- Throughput per instance: Kokoro ~10 req/min, Qwen3 ~4.8 req/min on 4 vCPU
- Single FIFO queue per instance with asyncio.Lock — requests processed sequentially
- Horizontal scaling via Caddy load balancer with round-robin and health checks
- Both engines loaded in memory (~4-6 GB total)

### API Versioning

- Single version (`v1`) — no versioning strategy needed
- Breaking changes ship as new deployments via Ansible update playbook

### Implementation Considerations

- OpenAI-compatible contract means n8n HTTP Request nodes work with zero custom config
- `uv` for all Python dependency management in Docker build
- Kokoro: espeak-ng with custom pt_extra dictionary for phonemization (sigla pronunciation)
- Qwen3: native BPE tokenizer with THINK mode for Portuguese; expand_siglas() text preprocessing
- ffmpeg required for post-processing pipelines and OGG Opus encoding
- Dual-engine warm-up on startup prevents slow first request
- Single process — no shared state concerns, scaling is horizontal via Caddy
- n8n-side failover pattern: allows alerting, text fallback, per-context retry logic

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP Approach:** Problem-solving MVP — deliver the minimum that makes n8n voice responses work without cloud dependencies. The product either generates cloned-voice audio on the local network or it doesn't. There's no partial value.

**Resource Requirements:** Solo developer. The FastAPI server with dual-engine routing, post-processing pipelines, and engine-specific preprocessing is the core complexity. Docker and Ansible are configuration. The hard ML inference is solved by Kokoro and Qwen3-TTS C++.

### MVP Feature Set (Phase 1)

**Core User Journeys Supported:**
- Journey 1 (First Deployment) — full bootstrap via Ansible
- Journey 2 (Routine Operation) — API request/response cycle
- Journey 3 (Update Cycle) — safe update preserving data
- Journey 4 (Troubleshooting) — health check and restart
- Journey 5 (Decommission) — complete cleanup

**Must-Have Capabilities:**
- `POST /v1/audio/speech` — text in, OGG Opus out, voice-based engine routing
- `GET /health` — service status, voices, engine load, queue depth, clone config
- Dual-engine architecture: Kokoro fp32 (built-in voices) + Qwen3-TTS C++ Q8_0 (voice cloning)
- Engine-specific post-processing: vibrato_warm (Kokoro), whatsapp-subtle (Qwen3)
- Engine-specific preprocessing: normalize+chunk (Kokoro), expand_siglas (Qwen3)
- espeak-ng custom pt_extra dictionary for perfect sigla pronunciation (Kokoro)
- Bearer token authentication
- Docker packaging with volume mounts (voices, models, noise files)
- Single FIFO queue per instance; horizontal scaling via Caddy load balancer
- Auto model download on first run (Kokoro ONNX ~325 MB, Qwen3 GGUF ~1.6 GB)
- Dual-engine warm-up on startup
- n8n-side failover pattern with alerting and text fallback
- Four Ansible playbooks: bootstrap, update, cleanup, health
- Daily restart cron (safety net)
- Documentation in English + README.md in pt-BR

### Post-MVP Features

**Phase 2 (Growth):**
- Response caching for repeated phrases (measure demand first)
- Prometheus metrics endpoint
- Qwen3 seed library management (known-good seeds per sigla pattern)
- Additional Kokoro voice blending (e.g., pf_dora:60,pm_alex:40)

**Phase 3 (Expansion):**
- Multi-language TTS beyond pt-BR
- Streaming audio response
- Multiple Caddy instances for high-availability load balancing
- GPU acceleration for higher throughput (if hardware budget changes)

### Risk Mitigation Strategy

**Technical Risks:**
- *Memory growth* — Kokoro memory leak fixed in phonemizer-fork >=3.3.2. Daily restart cron as safety net.
- *Qwen3 sigla inconsistency* — 7/10 quality with spaced format preprocessing. Mitigated by seed reproducibility (custom C++ patch) and per-sigla seed library.
- *Dual-engine complexity* — two engines, two preprocessing pipelines, two post-processing chains. Mitigated by clear module boundaries and voice-based routing.
- *Model download fails on first run* — HuggingFace dependency only at initial deploy. Models are cached in a Docker volume and survive restarts/updates.
- *OGG encoding quality* — depends on ffmpeg. Validate Telegram voice note compatibility during development.

**Market Risks:**
- None in the traditional sense — this is an internal tool, not a commercial product. The only "market" is the n8n workflow on the same network.

**Resource Risks:**
- Solo developer project. If unavailable, the service runs unattended — it's deploy-once. Ansible playbooks are the bus factor mitigation: anyone with SSH access can operate the lifecycle.

## Functional Requirements

### Audio Generation

- FR1: n8n workflow can submit text and receive synthesized speech audio via a dual-engine architecture with voice-based routing
- FR2: n8n workflow can specify the output audio format (OGG Opus default, WAV optional)
- FR3: n8n workflow can specify which voice to use, which determines the engine (santa/dora/alex → Kokoro; clone/qwen-female/qwen-male → Qwen3)
- FR4: The Kokoro engine can generate Brazilian Portuguese speech using espeak-ng phonemization with custom pt_extra dictionary for sigla pronunciation
- FR5: The Qwen3 engine can generate speech with a pre-configured cloned voice using a reference WAV placed on the server at deploy time
- FR5a: The service can apply engine-specific post-processing pipelines (vibrato_warm for Kokoro, whatsapp-subtle for Qwen3) to produce WhatsApp-optimized OGG Opus 24kbps 16kHz mono
- FR5b: The service can apply engine-specific text preprocessing (normalize_text + chunk_text for Kokoro; expand_siglas for Qwen3)

### API Interface

- FR6: n8n workflow can call an OpenAI-compatible `POST /v1/audio/speech` endpoint
- FR7: The service can authenticate requests using a bearer token
- FR8: The service can reject unauthorized requests with a 401 response
- FR9: The service can return appropriate error codes for malformed requests, missing voices, and internal failures
- FR10: The service can report a 503 status while warming up

### Service Health & Monitoring

- FR11: Any HTTP client can query a health endpoint to check service status
- FR12: The health endpoint can report available voice profiles and their engine assignments
- FR13: The health endpoint can report service uptime, queue depth, engine load status, and clone configuration

### Voice Management

- FR14: DevOps operator can configure voice cloning by placing a reference WAV file (3-10s) on the server at deploy time for Qwen3
- FR15: DevOps operator can configure the default voice via environment variable (default: santa)
- FR16: The service can discover built-in Kokoro voices and detect clone reference configuration at startup

### Container Lifecycle

- FR17: The service can automatically download required models on first run (Kokoro ONNX ~325 MB + voices ~27 MB from HuggingFace; Qwen3 GGUF ~1.3 GB + tokenizer ~341 MB)
- FR18: The service can cache downloaded models in a persistent volume
- FR19: The service can warm up both engines on startup to prevent slow first requests
- FR20: The service uses a single FIFO queue per instance with asyncio.Lock for sequential request processing
- FR21: Horizontal scaling is achieved by deploying multiple instances behind a Caddy load balancer with round-robin and health checks

### Deployment & Operations

- FR22: DevOps operator can bootstrap a complete deployment on a clean VPS using a single Ansible command
- FR23: DevOps operator can update the service from the latest repo without losing voices, model cache, or configuration
- FR24: DevOps operator can fully decommission the service leaving zero artifacts on the VPS
- FR25: DevOps operator can check service health, container state, and disk usage via Ansible
- FR26: The host can automatically restart the service on a daily schedule as a safety net (Kokoro memory leak fixed in phonemizer-fork >=3.3.2)

### Audio File Lifecycle

- FR29: The service can periodically clean up generated audio files to prevent disk space exhaustion on the VPS SSD

### Security & Isolation

- FR27: The service can operate with zero outbound network access after initial model download
- FR28: The service can run within Docker resource limits (CPU and memory constraints)

## Non-Functional Requirements

### Performance

- Kokoro response latency: typical 5-16s per request on 4 vCPU (RTF 1.1x, post-processing adds ~2s)
- Qwen3 response latency: typical 12-37s per request on 4 vCPU (RTF 2.5x, post-processing adds ~2s)
- Cold start (container up to healthy) < 120 seconds, excluding initial model download
- First request after restart completes within 10 seconds (dual-engine warm-up requirement)
- Throughput per instance: Kokoro ~10 req/min, Qwen3 ~4.8 req/min on 4 vCPU
- Memory usage: < 6 GB total (both engines loaded in single instance)

### Security

- All `/v1/audio/speech` requests require valid bearer token; invalid/missing tokens return 401
- No sensitive data stored at rest — audio is generated and returned, not persisted
- Service operates with zero outbound network access after model download
- API key configured via environment variable, never hardcoded or logged

### Reliability

- Service availability: 99%+ uptime excluding scheduled daily restarts
- Daily automatic restart as safety net — RAM should remain stable (Kokoro leak fixed in phonemizer-fork >=3.3.2)
- Model cache persists across container restarts and updates via Docker volume
- Voice files and configuration survive update operations 100% of the time
- Health endpoint accurately reflects actual service state (not just container running)

### Operational

- Bootstrap playbook completes without manual intervention on a clean Ubuntu VPS
- Update playbook completes without data loss in under 5 minutes
- Cleanup playbook removes 100% of CUMADRE artifacts from VPS
- Health playbook reports container state, endpoint status, resource usage, and disk consumption
- All Python dependencies managed via `uv`

