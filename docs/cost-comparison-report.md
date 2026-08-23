# Comadre vs Cloud TTS: Cost & Performance Comparison — pocket-tts v3

Updated 2026-08-23 with measured pocket-tts 2.1.0 numbers (the v2 Kokoro-era
version of this report was retired; raw data in `tests/results/campaign-v3/`).
Methodology and scaling details: [replica-scaling-report.md](replica-scaling-report.md).

## What Comadre is now (v3)

Single engine, **pocket-tts 2.1.0** (Kyutai), Brazilian Portuguese, CPU-only,
with **native voice cloning** — a 5–20 s reference sample becomes a usable
voice via the API (`POST /v1/voices`) or the demo landing page, ephemeral or
persisted per customer. Voice quality is a clear step above v2's Kokoro, and
cloning removes the fixed-catalog limitation that was v2's main competitive
gap against ElevenLabs.

## Measured capacity (production VM)

| Deployment | Host | Sustained ceiling | Audios/day | Conversations/month* |
|---|---|---|---|---|
| 1 replica, 4 vCPU / 8 GB (**current**) | Proxmox VM | 15.5 req/min | ~22k | ~27k |
| 2 replicas, 4 vCPU / 8 GB | Proxmox VM | 21.0 req/min | ~30k | ~37k |
| 1 replica, 8 vCPU / 16 GB | Proxmox VM | 19.6 req/min | ~28k | ~34k |
| 2 replicas, 8 vCPU / 16 GB | Proxmox VM | 30.0 req/min | ~43k | ~53k |

\* WhatsApp customer-service conversations/month assuming ~13 audios per
conversation, 8 h × 22 working days at sustained plateau (conservative:
real traffic is bursty, but bursts only queue — success stays 100% below
concurrency ≈ 10).

Latency at working loads: p50 ≈ 2–6 s for a typical message regardless of
config — acceptable for WhatsApp audio, where the alternative (human) is
minutes.

## Cost basis

Comadre cost = fixed VPS + operator time. Reference Hetzner shared-vCPU
pricing: ~$7/mo (4 vCPU/8 GB), ~$21/mo (8 vCPU/16 GB). Self-hosted on
existing hardware: electricity only. Marginal cost per audio: zero.

Competitors charge per credit because GPU inference costs money per request.
That pricing model is Comadre's moat: the same spend buys fixed capacity,
not metered usage.

## Cost comparison

Assumptions: avg message 109 chars ≈ 7 s audio (~1,000 chars/min).
ElevenLabs: Scale $330/mo incl. 2M chars + $0.18/1k chars overage.
AI33.pro aggregator: $10 / 2.1M credits (~$0.0005/audio at ElevenLabs/MiniMax
tier). Both figures from the v2 survey; published prices, not re-quoted.

| Usage profile | Audios/mo | Audio min/mo | Comadre (4 vCPU) | ElevenLabs Scale+ | AI33.pro |
|---|---|---|---|---|---|
| Light (500 msgs) | 500 | 58 | **~$7** | $22 (Creator) | $0.25 |
| Medium (2k msgs) | 2,000 | 233 | **~$7** | $99 (Pro) | $1.00 |
| Heavy (10k msgs) | 10,000 | 1,167 | **~$7** | $359 | $5.00 |
| Intensive (50k msgs) | 50,000 | 5,833 | **~$7** | $1,380 | $25.00 |
| Saturated 1r @ 4 vCPU | ~670k | ~7,700 | **~$7** | ~$16,300 | ~$335 |

Reading:

- Below ~275 msgs/month an ElevenLabs Starter plan is cheaper — irrelevant
  volume for a business chatbot.
- From there Comadre wins at every scale, and the gap grows linearly with
  volume because Comadre's curve is flat.
- AI33.pro's Edge-tier credits undercut everyone on price but offer neither
  cloning nor quality parity; their EL/MM tier is the fair comparison above.

## Quality & feature position

| Dimension | Comadre v3 | ElevenLabs | AI33.pro |
|---|---|---|---|
| Voice quality (PT-BR) | Very good (pocket-tts) | Best-in-class | Depends on tier |
| Native voice cloning | **Yes, self-served via API** | Yes, paid tiers | Via upstream |
| Data privacy / LGPD | **Audio never leaves the operator's infra** | Processed abroad | Multi-provider, unclear |
| Pricing model | Flat (VPS) | Per credit/char | Per credit |
| Latency dependency | None (local FIFO queue) | Upstream availability | Upstream ×2 |
| Rate control | Own keys, own limits | Provider throttles | Aggregator throttles |

## Takeaways

1. The default 4-vCPU deployment sustains **15 audios/min forever at ~$7/mo**
   — enough for dozens of simultaneous WhatsApp bot customers on one key
   each (per-key RPM caps at 30–120 in practice).
2. Cloning changes the sales story: competitors bill cloning as a premium
   feature; Comadre gives every customer their own voice at zero marginal
   cost.
3. Scaling path when needed: resize host to 8 vCPU (+43% ceiling with
   2 replicas) before adding more replicas — CPU, not replica count, is the
   binding constraint (see replica-scaling-report).
4. The honest trade-offs remain: operator-managed infrastructure, no SLA but
   your own, and voice quality below ElevenLabs' best models — compensated
   by unlimited volume, privacy, and two orders of magnitude of cost
   difference at scale.
