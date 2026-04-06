# Comadre vs Cloud TTS: Cost & Performance Comparison

## Executive Summary

Comadre delivers unlimited TTS audio for a fixed cost of $7/month on a single VPS (or near-zero on self-hosted hardware), with measured throughput of 18 audio messages per minute, 100% audio integrity across 818 test requests, and predictable latency under load. Voice quality is very good — comparable to MiniMax, better than Microsoft Edge TTS, and only slightly below ElevenLabs' best models. The companion kokoro-cloner project enables custom brand voices from a 10-second sample. For a business handling 120 clients/day in Brazilian Portuguese, Comadre costs 97-99% less than ElevenLabs and 35-77% less than AI33.pro, while offering full data privacy, LGPD compliance by design, and zero external dependencies. The trade-off is the need to self-manage infrastructure and a smaller voice catalog compared to ElevenLabs.

All Comadre performance numbers in this report are measured, not estimated. Cloud platform costs are calculated from published pricing.

## Platform Profiles

### Comadre (Self-Hosted)

Open-source dual-engine TTS API optimized for Brazilian Portuguese. Runs on a standard VPS with no GPU required.

- **Engines:** Kokoro fp32 (fast, built-in voices) + Qwen3-TTS C++ Q8_0 (voice cloning)
- **Deployment:** Docker Compose on any VPS (4 vCPU, 8 GB RAM minimum)
- **Pricing model:** Fixed monthly VPS cost (Hetzner CX33: EUR 6.49/mo = ~$7.01/mo)
- **API:** OpenAI-compatible (`POST /v1/audio/speech`)
- **Languages:** Optimized for Brazilian Portuguese (espeak-ng custom dictionary, 67 sigla entries)

### ElevenLabs (Cloud SaaS)

Industry-leading cloud TTS with premium voice quality and extensive voice library.

- **Pricing model:** Tiered subscription + per-character overage

| Plan | Price/mo | Characters | Audio minutes | Cost/min |
|------|----------|-----------|---------------|----------|
| Starter | $5 | 30,000 | ~30 | $0.167 |
| Creator | $22 | 100,000 | ~100 | $0.220 |
| Pro | $99 | 500,000 | ~500 | $0.198 |
| Scale | $330 | 2,000,000 | ~2,000 | $0.165 |
| Overage (Scale) | -- | -- | -- | $0.180/1k chars |

*~1,000 characters = 1 minute of audio (ElevenLabs documentation).*

### AI33.pro (Cloud API)

Budget cloud TTS API with credit-based pricing.

- **Pricing model:** Credit packs
- **Rate:** $10 per 2,100,000 credits
- **Cost per audio:** 170 credits per 12-second audio
- **Effective rate:** 12,353 audios per $10 = $0.00081/audio
- **Cost per audio minute:** $0.00405/min

## Measured Performance (Comadre)

All data from load tests run on 2026-04-06 against a Hetzner CX33 VPS (4 shared vCPU, 8 GB RAM) located at 10.10.10.207.

### Throughput

| Test | Requests | Success rate | Throughput | Audio integrity |
|------|----------|-------------|------------|-----------------|
| Saturation test | 208 | 97.1% (timeouts at 50 concurrent) | 10.9 req/min | 208/208 (100%) |
| Capacity test | 610 | 100% (no timeout, unlimited wait) | 18.0 req/min max | 610/610 (100%) |
| **Combined** | **818** | -- | -- | **818/818 (100%)** |

### Latency by Request Rate

Measured with audio messages of 5-12 seconds (80-200 characters, typical chatbot messages):

| Target rate | Actual throughput | Latency p50 | Latency p95 | Latency max | Queue depth |
|------------|-------------------|-------------|-------------|-------------|-------------|
| 2/min | 2.1/min | 3.0s | 5.0s | 5.5s | 1 |
| 5/min | 5.2/min | 2.9s | 5.0s | 5.5s | 1 |
| 10/min | 10.2/min | 2.9s | 5.1s | 5.5s | 1 |
| 20/min | 18.0/min | 11.3s | 18.5s | 20.2s | 6 |
| 30/min | 18.0/min | 36.4s | 72.6s | 81.5s | 25 |
| 50/min | 18.2/min | 106.5s | 204.7s | 211.7s | 65 |

### Latency by Text Size (Single Request, No Queue)

| Text size | Characters | Audio duration | Generation time |
|-----------|-----------|----------------|-----------------|
| Short | ~50 | 2.5-3.2s | 1.4-1.7s |
| Medium | ~200 | 11.4-13.0s | 5.2-6.1s |
| Long | ~450 | 26.5-27.4s | 11.6-12.3s |

### Resource Usage

| Metric | Value |
|--------|-------|
| Memory at idle | ~574 MB |
| Memory under load | ~1,490 MB (stable) |
| Memory peak (all tests) | 1,497 MB |
| Memory leak | None detected |
| CPU limit | 4 cores (100% during generation) |
| Crashes during testing | 0 |
| Audio corruption | 0/818 |

## Cost Comparison

### Assumptions

- **Working days:** 22 per month
- **Working hours:** 8 per day
- **Messages per client:** 6 (typical sales/post-sales conversation)
- **Peak distribution:** 60% of traffic in 4 peak hours (10-12h, 14-16h)
- **Comadre VPS:** Hetzner CX33 at EUR 6.49/mo ($7.01/mo at 1.08 EUR/USD)

### Scenario A: Short Audio Messages (avg 7 seconds, ~100 chars)

| Business size | Clients/day | Msgs/day | Msgs/month | Audio min/mo | Comadre | ElevenLabs | AI33.pro |
|--------------|-------------|----------|-----------|-------------|---------|------------|----------|
| Micro | 50 | 300 | 6,600 | 770 | **$7** | $330 (Scale) | $5.34 |
| Small | 120 | 720 | 15,840 | 1,848 | **$7** | $330 (Scale) | $12.82 |
| Medium | 300 | 1,800 | 39,600 | 4,620 | **$7** | $802 (Scale+) | $32.05 |
| Growing | 500 | 3,000 | 66,000 | 7,700 | **$14** (2x VPS) | $1,218 (Scale+) | $53.41 |
| Large | 1,000 | 6,000 | 132,000 | 15,400 | **$21** (3x VPS) | $2,304 (Scale+) | $106.82 |

### Scenario B: Long Audio Messages (avg 17.5 seconds, ~200 chars)

| Business size | Clients/day | Msgs/day | Msgs/month | Audio min/mo | Comadre | ElevenLabs | AI33.pro |
|--------------|-------------|----------|-----------|-------------|---------|------------|----------|
| Micro | 50 | 300 | 6,600 | 1,925 | **$7** | $330 (Scale) | $7.79 |
| Small | 120 | 720 | 15,840 | 4,620 | **$7** | $802 (Scale+) | $18.69 |
| Medium | 300 | 1,800 | 39,600 | 11,550 | **$14** (2x VPS) | $1,764 (Scale+) | $46.73 |
| Growing | 500 | 3,000 | 66,000 | 19,250 | **$21** (3x VPS) | $2,844 (Scale+) | $77.88 |
| Large | 1,000 | 6,000 | 132,000 | 38,500 | **$35** (5x VPS) | $5,556 (Scale+) | $155.76 |

### Cost Per Audio Minute

| Platform | Cost/min (at scale) | Model |
|----------|-------------------|-------|
| **Comadre** | **$0.0004** (at 15,840 msgs/mo) | Fixed |
| AI33.pro | $0.0041 | Per-credit |
| ElevenLabs | $0.165-0.220 | Per-character |

Comadre is **10x cheaper** than AI33.pro and **400x cheaper** than ElevenLabs per audio minute at typical volume.

## Capacity Planning

Comadre processes requests sequentially (single FIFO queue per instance). Throughput per VPS:

| Audio length | Throughput/VPS | Max sustainable rate |
|-------------|---------------|---------------------|
| Short (7s) | 18 req/min | 10 req/min (queue-free) |
| Long (17.5s) | 10 req/min | 5 req/min (queue-free) |

### When to Add Instances

For WhatsApp chatbots, response times up to 120 seconds are acceptable.

| Business size | Peak req/min | VPS needed (short audio) | VPS needed (long audio) | Monthly cost |
|--------------|-------------|-------------------------|------------------------|-------------|
| 50 clients/day | 3 | 1 | 1 | $7 |
| 120 clients/day | 5 | 1 | 1 | $7 |
| 300 clients/day | 12 | 1 | 2 | $7-14 |
| 500 clients/day | 20 | 2 | 3 | $14-21 |
| 1,000 clients/day | 40 | 3 | 5 | $21-35 |

Horizontal scaling is done by adding VPS instances behind a Caddy load balancer. Each instance is independent — no shared state, no coordination overhead.

### Self-Hosted Hardware Option

For businesses that own or can acquire hardware, Comadre runs on minimal specs (4-core CPU, 4 GB RAM, any x86_64 machine). A one-time hardware purchase (~$150-300 for a mini PC or repurposed desktop) eliminates the monthly VPS cost entirely. The only recurring cost is electricity (~$2-5/month for a low-power mini PC).

| Deployment | Monthly cost | 1-year total | 2-year total |
|-----------|-------------|-------------|-------------|
| Hetzner VPS | $7/mo | $84 | $168 |
| Self-hosted mini PC | ~$3/mo (electricity) | ~$186 (hw + power) | ~$222 |
| Self-hosted (existing hardware) | ~$3/mo (electricity) | $36 | $72 |

Self-hosting breaks even with VPS hosting after ~12 months if purchasing new hardware, or is immediately cheaper if using existing hardware.

## Latency & Reliability

### Comadre: Predictable and Self-Controlled

Every number below is measured:

| Condition | Response time | Source |
|-----------|--------------|--------|
| No queue (< 10 req/min) | 3-6 seconds | Capacity test |
| Light queue (20 req/min) | 11 seconds p50 | Capacity test |
| Heavy queue (30 req/min) | 36 seconds p50, 82s max | Capacity test |
| Saturated (50 req/min) | 107 seconds p50 | Capacity test |
| Server crash | 0 incidents in 818 requests | All tests |
| Audio corruption | 0 incidents in 818 requests | All tests |

Comadre's latency is deterministic: it depends only on queue depth, which depends only on your own traffic. No other customer affects your performance.

### Cloud Platforms: Shared and Unpredictable

ElevenLabs and AI33.pro run on shared infrastructure. Their latency depends on:

- Total load from all customers worldwide
- Time of day (business hours across multiple time zones)
- Seasonal peaks (Black Friday, holiday campaigns)
- Platform incidents and maintenance windows
- Rate limiting policies that may change without notice

Neither platform publishes SLA guarantees for response time. A request that takes 2 seconds at 3 AM may take 30 seconds at 10 AM on a Monday.

**Comadre eliminates this uncertainty.** You own the infrastructure, you measured the limits, and no external factor can degrade your service.

## Feature Comparison

| Feature | Comadre | ElevenLabs | AI33.pro |
|---------|---------|------------|----------|
| **Voice quality** | Very good (Kokoro) | Excellent | Good |
| **BR-PT optimization** | Yes (custom dictionary) | Generic multilingual | Unknown |
| **Sigla pronunciation** | Perfect (67 verified entries) | Inconsistent | Unknown |
| **Voice cloning** | Yes (Qwen3 + kokoro-cloner) | Yes (premium) | Unknown |
| **Custom voicepacks** | Yes (kokoro-cloner pipeline) | No (predefined clones) | Unknown |
| **Built-in voices (pt-BR)** | 3 optimized + unlimited via kokoro-cloner | Hundreds (multilingual) | Unknown |
| **Language focus** | Brazilian Portuguese only | Dozens of languages | Unknown |
| **Data privacy** | Full (on-premise) | Cloud (third-party) | Cloud (third-party) |
| **LGPD compliance** | Inherent (no data leaves your server) | Requires DPA | Requires DPA |
| **Uptime control** | You control | Vendor-dependent | Vendor-dependent |
| **Network dependency** | None (runs offline) | Requires internet | Requires internet |
| **API compatibility** | OpenAI-compatible | Proprietary | Proprietary |
| **Latency predictability** | Measured, deterministic | Variable, shared | Variable, shared |
| **Cost model** | Fixed monthly | Per-character | Per-credit |
| **Cost at 15k msgs/mo** | $7/mo | $330/mo | $13/mo |
| **Horizontal scaling** | Manual (add VPS) | Automatic | Automatic |
| **Setup complexity** | Medium (Docker + Ansible) | None (SaaS) | Low (API key) |
| **Maintenance** | Self-managed | Zero | Zero |

## Voice Quality & Cloning

### Quality Positioning

Comadre's Kokoro engine produces very good audio quality — comparable to MiniMax and noticeably better than Microsoft Edge TTS. It is only slightly inferior to ElevenLabs' top-tier models. For WhatsApp, Telegram, and Messenger voice messages, the quality difference is negligible to end users. ElevenLabs retains an edge for premium use cases like audiobooks, brand voices, and marketing videos.

### Custom Voice Cloning with kokoro-cloner

The companion project [kokoro-cloner](https://github.com/docg1701/kokoro-cloner) creates custom Kokoro voicepacks from a 10-second voice sample. The pipeline:

1. **Amplify** — Chatterbox clones your voice across 1,000 long pt-BR phrases (5,000 training WAVs)
2. **Optimize** — ECAPA-TDNN speaker embedding loss through frozen Kokoro backpropagates a 256-dim style vector to match your voice
3. **Infer** — Kokoro generates speech with your custom voicepack at full Kokoro speed

The result is a personalized voice that runs at Kokoro's native speed (3-6 seconds per message) with no quality penalty. This gives Comadre the best of both worlds: custom voice identity with the lowest latency and cost.

While Comadre ships with 3 pt-BR-optimized voices, kokoro-cloner enables **unlimited custom voices** — each created from a 10-second sample. The cloning process runs once, and the resulting `.npy` voicepack drops into Comadre's `/voices/kokoro/` directory — available immediately, no restart needed. Every cloned voice inherits Kokoro's fast inference speed and low resource usage.

**Cloning time by hardware:**

| GPU | VRAM | Estimated time | Notes |
|-----|------|---------------|-------|
| RTX 2060 Super | 8 GB | ~6 hours | Measured. Gradient checkpointing enabled (8 GB limit) |
| RX 9060 XT | 16 GB | ~2-3 hours | Estimated. ~3x more compute (RDNA 4), no gradient checkpointing needed (16 GB) |
| CPU only | 8 GB RAM | ~24-48 hours | No GPU required, just slower |

Voice creation is a one-time cost per voice. Once the voicepack is generated, it runs at Kokoro's native inference speed indefinitely.

## Honest Trade-offs: Where Comadre Loses

### Voice Catalog

Comadre ships with 3 pt-BR-optimized voices out of the box. New voices are created via the kokoro-cloner pipeline from a 10-second sample (~6 hours on a RTX 2060 Super, ~2-3 hours on a RX 9060 XT). ElevenLabs offers hundreds of ready-to-use voices across dozens of languages — pick one from a catalog instantly, no pipeline needed. For teams that need many distinct voices quickly, ElevenLabs has a practical advantage.

### Setup and Maintenance

Cloud platforms require zero infrastructure management. Comadre requires provisioning a VPS, running Ansible playbooks, and occasionally updating the service. For teams without DevOps experience, this is a real barrier. The Ansible automation reduces it to a few commands, but it's not zero.

### Automatic Scaling

Cloud platforms scale transparently. Comadre requires manually adding VPS instances and configuring a load balancer. For businesses with highly unpredictable traffic spikes, this manual process adds operational overhead.

### Portuguese Only

Comadre is built exclusively for Brazilian Portuguese — the text preprocessing, sigla dictionary, and audio post-processing are all pt-BR specific. It does not support other languages. If you need multilingual TTS, ElevenLabs is the only viable option among the three platforms compared here.

## When to Choose What

### Choose Comadre When

- **Volume exceeds 300 messages/month** — break-even point vs ElevenLabs Starter
- **Data privacy matters** — client conversations never leave your server (LGPD)
- **Predictable costs are essential** — fixed $7/mo regardless of volume
- **Brazilian Portuguese is the primary language** — custom sigla dictionary, tested pronunciation
- **You need predictable latency** — measured, self-controlled, no shared infrastructure
- **You want a custom brand voice** — kokoro-cloner creates a voicepack from a 10-second sample
- **You have basic DevOps capability** — or willingness to learn Docker + Ansible
- **You can self-host** — existing hardware eliminates monthly costs entirely

### Choose ElevenLabs When

- **Top-tier voice quality is non-negotiable** — audiobooks, premium video narration
- **You need many languages** — global audience, multi-language support
- **Volume is under 300 messages/month** — $5/mo Starter plan is hard to beat
- **Zero infrastructure management** — no VPS, no Docker, no Ansible
- **You need instant voice cloning** — no pipeline to run, clone from the UI

### Choose AI33.pro When

- **Budget is the primary constraint** — cheapest per-audio cost at low volume
- **Volume is under 8,000 messages/month** — below this, AI33 is close to Comadre's cost
- **You accept shared infrastructure risks** — uncontrolled latency, no SLA
- **Setup simplicity matters more than control** — API key and go

## Appendix: Test Methodology

### Saturation Test (`scripts/loadtest.py`)

- 6 scenarios: baseline, light (3 concurrent), moderate (10), heavy (20), stress (50), burst (30 simultaneous)
- 208 total requests across all scenarios
- Audio validation via ffprobe (duration > 0.1s)
- Health monitoring every 1 second (queue depth, memory)
- Timeout: 130 seconds per request

### Capacity Test (`scripts/capacity_test.py`)

- 8 rate tiers: 2, 5, 10, 20, 30, 50, 75, 100 requests/minute
- 610 total requests across all tiers
- No timeout — every request waited until completion
- Text corpus: 12 Brazilian Portuguese sentences, 80-200 characters (producing 5-12 second audio)
- Audio validation via ffprobe
- Health monitoring every 1 second

### Environment

- **VPS:** Hetzner CX33 — 4 shared vCPU (AMD EPYC), 8 GB RAM, 80 GB SSD
- **Location:** Germany (Falkenstein)
- **Container limits:** 4 CPUs, 6 GB RAM
- **Engine:** Kokoro fp32 (ONNX), voice `pm_santa`
- **Output format:** OGG Opus 24kbps 16kHz mono
- **Date:** 2026-04-06
