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

CUMADRE (Cumadre Manda Audio Direto, Rapido e Eficiente) is a self-hosted text-to-speech service with zero-shot voice cloning, purpose-built for automated customer service audio in Brazilian Portuguese. It wraps KokoClone (Kokoro TTS + Kanade voice conversion) behind a FastAPI endpoint compatible with the OpenAI audio API, packaged as a Docker service and deployed via Ansible to commodity hardware. The sole consumer is n8n workflow automation on the same local network — no human interacts with the service directly.

After initial deployment, CUMADRE requires zero internet access, zero per-request cost, and sends zero customer data externally. A DevOps operator manages the full lifecycle (bootstrap, update, cleanup, health) through Ansible playbooks.

### What Makes This Special

KokoClone solves the hard ML problem — high-quality TTS with zero-shot voice cloning from a single 3-10s reference WAV — but ships as a bare Python library with no API, no Docker image, and no deployment story. Cloud alternatives (ElevenLabs, Google, Azure) require internet on every request, introduce per-character cost, and expose customer data. Kokoro-FastAPI provides a REST layer but lacks voice cloning entirely.

CUMADRE is the productization layer: ~80 lines of FastAPI wrapping KokoClone's API, a Dockerfile, docker-compose.yml, and four Ansible playbooks. It turns a research-grade Python library into a deploy-once, zero-maintenance production service. The core insight is that the AI capability already exists — the gap is operational usability.

## Project Classification

- **Project Type:** API Backend — single REST endpoint consumed by n8n over HTTP
- **Domain:** General — no regulated industry, no compliance requirements beyond API key auth
- **Complexity:** Low — single-purpose service, one consumer, no multi-tenancy or user management
- **Project Context:** Greenfield — new service built from scratch

## Success Criteria

### User Success

**n8n Workflow Engine (primary consumer):**
- Receives playable audio (WAV or OGG) from every valid API call
- Response latency < 3s for short phrases (~15 words)
- Consistent cloned voice quality across requests
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
| Response latency | < 3s per request (~15 words) | `time curl` against endpoint |
| Service availability | 99%+ uptime (excluding scheduled restarts) | Health endpoint monitoring |
| Throughput | 20-60 req/min on 4 vCPU | Load test with concurrent requests |
| RAM usage | < 3 GB steady state | `docker stats tts-service` |
| Cold start time | < 120s (model download excluded) | Time from `docker compose up` to healthy |
| Memory stability | No growth beyond 4 GB over 24h | Mitigated by daily restart cron |

### Measurable Outcomes

- Deploy success rate: Bootstrap completes on clean VPS without manual intervention
- Safe update rate: `update.yml` preserves voices and model cache 100% of the time
- OGG compatibility: `response_format: ogg` produces valid Telegram-compatible voice notes
- Auth enforcement: Requests without valid API key return 401
- Multiple workers: `WORKERS=2` handles concurrent requests correctly
- Cleanup completeness: `cleanup.yml` leaves zero CUMADRE artifacts on VPS


## User Journeys

### Journey 1: First Deployment — Meet Carlos, the DevOps Operator

Carlos maintains the infrastructure for a small customer service operation. He's been asked to get voice responses working for the WhatsApp chatbot — without adding another cloud dependency. He finds CUMADRE.

**Opening Scene:** Carlos has a clean Ubuntu 22.04 VPS with 4 vCPU and 8 GB RAM. He clones the CUMADRE repo and reviews the deployment docs.

**Rising Action:** He configures the Ansible inventory with his VPS IP, sets an `API_KEY`, and copies a 5-second WAV recording of the employee whose voice will be cloned to the local voices directory. He runs `ansible-playbook bootstrap.yml`.

**Climax:** Ansible installs Docker, clones the repo to the VPS, builds the container, downloads models from HuggingFace, and starts the service. The health check goes green. Carlos runs `curl -X POST` against `/v1/audio/speech` with a test phrase — and hears the cloned employee voice speaking naturally in Brazilian Portuguese.

**Resolution:** Carlos configures the n8n HTTP Request node to point at the CUMADRE endpoint. The chatbot now responds with natural voice audio. No cloud API key, no per-request billing, no data leaving the network.

### Journey 2: Routine Operation — n8n Handles a Customer Interaction

**Opening Scene:** A customer sends a WhatsApp message asking about their order status. The n8n workflow receives the message via webhook.

**Rising Action:** n8n processes the message through STT (if voice) and the LLM, which generates a response: "Seu pedido foi enviado ontem e deve chegar até sexta-feira." The workflow POSTs this text to CUMADRE's `/v1/audio/speech` endpoint with `response_format: ogg` and the bearer token.

**Climax:** CUMADRE generates speech with Kokoro, converts it to the cloned employee voice with Kanade, encodes to OGG, and returns the binary in under 3 seconds.

**Resolution:** n8n sends the OGG audio as a voice note back to the customer on WhatsApp. The customer hears a natural, familiar voice — not a robot. The entire exchange happened on the local network.

### Journey 3: Update Cycle — Carlos Keeps CUMADRE Current

**Opening Scene:** A new CUMADRE release adds OGG quality improvements. Carlos needs to update without disrupting the live service.

**Rising Action:** Carlos runs `ansible-playbook update.yml`. Ansible pulls the latest repo, rebuilds the Docker image, and restarts the container.

**Climax:** The service comes back up. Carlos checks: voice files still mounted, model cache intact, API key unchanged. The health endpoint returns green.

**Resolution:** Carlos verifies with a test request. The updated service is live with zero data loss and minimal downtime.

### Journey 4: Troubleshooting — Something Breaks at 2 AM

**Opening Scene:** The n8n workflow starts getting timeouts from CUMADRE. Carlos gets an alert.

**Rising Action:** Carlos runs `ansible-playbook health.yml` from his laptop. It reports: container running, health endpoint returning 200, but `docker stats` shows RAM at 3.8 GB and climbing — the known Kokoro memory leak.

**Climax:** Carlos confirms the daily restart cron is set. For immediate relief, he restarts the container manually: `docker compose restart tts-service`. RAM drops back to ~2 GB.

**Resolution:** The service recovers. Carlos verifies the cron job schedule and adjusts it to run more frequently if needed. He logs the incident for future reference.

### Journey 5: Full Decommission — End of Life

**Opening Scene:** The operation migrates to a different TTS solution. Carlos needs to clean up the VPS completely.

**Rising Action:** Carlos runs `ansible-playbook cleanup.yml`. Ansible stops containers, removes images, volumes, data, and uninstalls Docker.

**Resolution:** Zero CUMADRE artifacts remain on the VPS. The machine is clean for reuse.

### Journey Requirements Summary

| Journey | Capabilities Revealed |
|---|---|
| First Deployment | Bootstrap playbook, model auto-download, health endpoint, voice mounting, warm-up |
| Routine Operation | `/v1/audio/speech` endpoint, WAV/OGG output, bearer auth, < 3s latency, OpenAI-compatible API |
| Update Cycle | Update playbook, data preservation (voices, cache, config), container rebuild |
| Troubleshooting | Health playbook, `docker stats` visibility, container restart, memory leak mitigation via cron |
| Decommission | Cleanup playbook, complete artifact removal |

## API Backend Specific Requirements

### Project-Type Overview

CUMADRE is a single-purpose API backend: one generation endpoint, one health endpoint, bearer token auth, JSON in, binary audio out. It follows the OpenAI audio API contract so existing HTTP clients and n8n nodes work without custom integration code.

### Endpoint Specifications

| Endpoint | Method | Purpose | Request | Response |
|---|---|---|---|---|
| `/v1/audio/speech` | POST | Generate speech audio | JSON body | WAV or OGG binary |
| `/health` | GET | Service status + available voices | None | JSON |

#### `POST /v1/audio/speech`

- **Request body:** JSON with `input` (text), `voice` (voice name), `response_format` (`wav` or `ogg`)
- **Response:** Binary audio file with appropriate `Content-Type` header
- **Auth:** `Authorization: Bearer <API_KEY>` required on every request

#### `GET /health`

- **Response:** JSON with service status, available voices, uptime
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
  "voice": "employee-name",
  "response_format": "wav|ogg"
}
```

**Response:** Binary audio stream (`audio/wav` or `audio/ogg`)

**Health Response (GET /health):**
```json
{
  "status": "healthy",
  "voices": ["employee-name"],
  "uptime": 3600
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
- Throughput target: 20-60 req/min on 4 vCPU depending on worker count
- Concurrency managed via `WORKERS` env var (default 1)
- Each worker holds models in memory (~2-3 GB RAM)

### API Versioning

- Single version (`v1`) — no versioning strategy needed
- Breaking changes ship as new deployments via Ansible update playbook

### Implementation Considerations

- OpenAI-compatible contract means n8n HTTP Request nodes work with zero custom config
- `uv` for all Python dependency management in Docker build
- espeak-ng required as phonemizer backend for pt-BR
- ffmpeg required for OGG encoding
- Model warm-up on startup prevents slow first request
- Workers are independent processes — no shared state between them

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP Approach:** Problem-solving MVP — deliver the minimum that makes n8n voice responses work without cloud dependencies. The product either generates cloned-voice audio on the local network or it doesn't. There's no partial value.

**Resource Requirements:** Solo developer. The FastAPI wrapper is ~80 lines. Docker and Ansible are configuration, not code. The hardest part is already solved by KokoClone.

### MVP Feature Set (Phase 1)

**Core User Journeys Supported:**
- Journey 1 (First Deployment) — full bootstrap via Ansible
- Journey 2 (Routine Operation) — API request/response cycle
- Journey 3 (Update Cycle) — safe update preserving data
- Journey 4 (Troubleshooting) — health check and restart
- Journey 5 (Decommission) — complete cleanup

**Must-Have Capabilities:**
- `POST /v1/audio/speech` — text in, WAV/OGG out, cloned voice
- `GET /health` — service status and available voices
- Bearer token authentication
- Docker packaging with volume mounts (voices, model cache)
- Configurable workers via `WORKERS` env var
- Auto model download from HuggingFace on first run
- Warm-up on startup
- Four Ansible playbooks: bootstrap, update, cleanup, health
- Daily restart cron (memory leak mitigation)
- Documentation in English + README.md in pt-BR

### Post-MVP Features

**Phase 2 (Growth):**
- Response caching for repeated phrases (measure demand first)
- Multiple voice profiles per deployment
- Prometheus metrics endpoint
- GPU acceleration for higher throughput

**Phase 3 (Expansion):**
- Multi-language TTS beyond pt-BR
- Voice training from longer samples
- Streaming audio response
- Horizontal scaling across containers

### Risk Mitigation Strategy

**Technical Risks:**
- *Kokoro memory leak* — mitigated by daily restart cron on host. If frequency increases, adjust cron schedule. Long-term: monitor KokoClone upstream for fixes.
- *Model download fails on first run* — HuggingFace dependency only at initial deploy. Models are cached in a Docker volume and survive restarts/updates.
- *OGG encoding quality* — depends on ffmpeg. Validate Telegram voice note compatibility during development.

**Market Risks:**
- None in the traditional sense — this is an internal tool, not a commercial product. The only "market" is the n8n workflow on the same network.

**Resource Risks:**
- Solo developer project. If unavailable, the service runs unattended — it's deploy-once. Ansible playbooks are the bus factor mitigation: anyone with SSH access can operate the lifecycle.

## Functional Requirements

### Audio Generation

- FR1: n8n workflow can submit text and receive synthesized speech audio with a cloned voice
- FR2: n8n workflow can specify the output audio format (WAV or OGG)
- FR3: n8n workflow can specify which voice profile to use for generation
- FR4: The service can generate Brazilian Portuguese speech using espeak-ng phonemization
- FR5: The service can convert generated speech to a cloned voice using a reference WAV file

### API Interface

- FR6: n8n workflow can call an OpenAI-compatible `POST /v1/audio/speech` endpoint
- FR7: The service can authenticate requests using a bearer token
- FR8: The service can reject unauthorized requests with a 401 response
- FR9: The service can return appropriate error codes for malformed requests, missing voices, and internal failures
- FR10: The service can report a 503 status while warming up

### Service Health & Monitoring

- FR11: Any HTTP client can query a health endpoint to check service status
- FR12: The health endpoint can report available voice profiles
- FR13: The health endpoint can report service uptime

### Voice Management

- FR14: DevOps operator can provision a voice by placing a reference WAV file (3-10s) in the voices directory
- FR15: DevOps operator can configure the default voice via environment variable
- FR16: The service can discover and load voice files from the mounted volume at startup

### Container Lifecycle

- FR17: The service can automatically download required models from HuggingFace on first run
- FR18: The service can cache downloaded models in a persistent volume
- FR19: The service can warm up models on startup to prevent slow first requests
- FR20: DevOps operator can configure the number of worker processes via environment variable
- FR21: The service can run multiple independent worker processes for concurrent request handling

### Deployment & Operations

- FR22: DevOps operator can bootstrap a complete deployment on a clean VPS using a single Ansible command
- FR23: DevOps operator can update the service from the latest repo without losing voices, model cache, or configuration
- FR24: DevOps operator can fully decommission the service leaving zero artifacts on the VPS
- FR25: DevOps operator can check service health, container state, and disk usage via Ansible
- FR26: The host can automatically restart the service on a daily schedule to mitigate memory leaks

### Security & Isolation

- FR27: The service can operate with zero outbound network access after initial model download
- FR28: The service can run within Docker resource limits (CPU and memory constraints)

## Non-Functional Requirements

### Performance

- Response latency < 3 seconds for short phrases (~15 words) on 4 vCPU hardware
- Cold start (container up to healthy) < 120 seconds, excluding initial model download
- First request after restart completes within 5 seconds (warm-up requirement)
- Throughput: 20-60 requests/minute depending on worker count
- Memory usage: < 3 GB steady state per worker

### Security

- All `/v1/audio/speech` requests require valid bearer token; invalid/missing tokens return 401
- No sensitive data stored at rest — audio is generated and returned, not persisted
- Service operates with zero outbound network access after model download
- API key configured via environment variable, never hardcoded or logged

### Reliability

- Service availability: 99%+ uptime excluding scheduled daily restarts
- Daily automatic restart mitigates memory leak — RAM must not exceed 4 GB over 24 hours of continuous operation
- Model cache persists across container restarts and updates via Docker volume
- Voice files and configuration survive update operations 100% of the time
- Health endpoint accurately reflects actual service state (not just container running)

### Operational

- Bootstrap playbook completes without manual intervention on a clean Ubuntu VPS
- Update playbook completes without data loss in under 5 minutes
- Cleanup playbook removes 100% of CUMADRE artifacts from VPS
- Health playbook reports container state, endpoint status, resource usage, and disk consumption
- All Python dependencies managed via `uv`

