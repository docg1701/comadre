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
pricing: ~$7/mo (4 vCPU/8 GB), ~$21/mo (8 vCPU/16 GB); the operator's actual
reference budget is **R$ 50/mo for a 4 vCPU / 8 GB VM**. Self-hosted on
existing hardware: electricity only. Marginal cost per audio: zero.

Competitors charge per credit because GPU inference costs money per request.
That pricing model is Comadre's moat: the same spend buys fixed capacity,
not metered usage.

**ElevenLabs (verified against elevenlabs.io/pricing, Aug 2026):** credits
replaced "characters" with unchanged value; per-model burn differs —
Flash/Turbo models cost 0.5 credit/char, Multilingual v2 / Eleven v3 cost
1 credit/char. Independent measurement: ~826–915 credits per finished minute.
Plans: Starter $6/30k · Creator $22/121k · Pro $99/600k · Scale $299/1.8M ·
Business $990/6M. No self-serve plan covers saturated single-replica volume:
670k audios/mo × ~110 credits ≈ 74M credits/mo — Enterprise-only territory.

**AI33.pro (aggregator):** the site is a login-gated app; two dated data
points — (a) repo survey Apr 2026: $10 / 2.1M credit packs, measured burn
90 credits per 12 s Edge-tier audio and 140–190 credits at the
ElevenLabs/MiniMax tier; (b) third-party listing 2026 (Cliptude):
~1M credits for ~$11/mo subscription — if current, credits got ~4.5× more
expensive than the pack model. Confirm in-account before quoting customers.

## Cost comparison

Assumptions: avg WhatsApp message ≈ 110 chars ≈ 7 s audio (~110–150 credits
on ElevenLabs quality tier); FX R$ 5.40/USD.

| Source | Cost per 7 s audio | Vs. Comadre (working-day) |
|---|---|---|
| **Comadre**, R$ 50/mo flat | R$ 0.00007 (saturated) – R$ 0.00031 | — |
| AI33.pro premium tier (Apr 2026 packs) | R$ 0.0014–0.0026 ($0.00026–0.00048) | ~8× |
| AI33.pro premium tier (2026 listing) | R$ 0.005–0.009 (~$0.001–0.0017) | ~20–35× |
| ElevenLabs Flash tier (0.5 credit/char, plan blend) | ~R$ 0.05 (~$0.009) | ~200× |
| ElevenLabs quality tier (1 credit/char, plan blend) | ~R$ 0.10 (~$0.018) | ~400–1,500× |

Monthly totals at saturation (~670k audios/mo, beyond any self-serve plan):
Comadre **R$ 50** · AI33.pro premium R$ 940–6,000 (depending on which price
list holds) · ElevenLabs quality tier **R$ 70k+** and unavailable without an
Enterprise contract.

Reading:

- Even the cheapest credible competitor (AI33 Edge, no cloning, lower
  quality) is one to two orders of magnitude more expensive at working
  volumes.
- The gap grows linearly with volume because Comadre's curve is flat while
  every credit model scales linearly.
- Competitor prices move frequently — re-verify both pages before renewing
  customer-facing pricing commitments; this report's competitor figures are
  snapshots, not contracts.

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

## Sources (accessed 2026-08-23)

- <https://elevenlabs.io/pricing> — live plan/credit table
- <https://help.elevenlabs.io/hc/en-us/articles/27562020846481> — credits vs
  characters, per-model burn
- toolproven.com/blog/elevenlabs-pricing — verified Jul 19 2026;
  826–915 credits/min measured
- aistackpicks.com/reviews/elevenlabs-pricing-2026 — verified May 24 2026
- cliptude.com/docs/eleven-labs-alternatives — AI33.pro listing, 2026
- Repo survey Apr 2026 (`git log` on this file) — AI33.pro pack pricing and
  measured credit burn
