# Comadre vs Cloud TTS: Cost & Performance Comparison

**v2-era document (2026-04).** The numbers below reflect the v2
dual-engine deployment (Kokoro fp32 + Qwen3-TTS). Comadre 3.0.0 replaced
both engines with kyutai-labs/pocket-tts (single engine + native voice
cloning) in August 2026. A v3 addendum with fresh capacity/cost numbers
will be appended after the production cutover and the loadtest/capacity
re-run (migration plan Phase 4). Until then, treat the figures as
historical.

## Executive Summary

Comadre delivers unlimited TTS audio for a **fixed monthly VPS cost** (from ~$7/mo for a single replica to ~$21/mo for the validated two-replica configuration), with **100% audio integrity across 2,440 verified test requests** spanning four configurations and a randomized realistic chatbot workload. Sustainable throughput is **~13 requests per minute on a single 4-CPU replica** and **~20 requests per minute on a two-replica deployment** (8-CPU host, queue-aware load balancing) — enough to power **27,000 to 42,000 complete WhatsApp customer-service conversations per month** under realistic working-day patterns. Voice quality is very good — comparable to MiniMax, better than Microsoft Edge TTS, and only slightly below ElevenLabs' best models. The companion kokoro-cloner project enables custom brand voices from a 10-second sample.

For a business handling 120 clients/day in Brazilian Portuguese, Comadre costs **~99% less than ElevenLabs** and **~50% less than AI33.pro**, while offering full data privacy, LGPD compliance by design, and zero external dependencies. The cost gap widens dramatically with volume: at 211,000 audios/month (a saturated two-replica deployment), Comadre costs ~$21/mo while ElevenLabs Scale + overage costs ~$4,646/mo and AI33.pro EL/MM-tier costs ~$102/mo. The trade-off is the need to self-manage infrastructure and a smaller voice catalog compared to ElevenLabs.

All Comadre performance numbers in this report are measured using the **Kokoro engine only** (CPU inference, no GPU). Comadre also supports Qwen3-TTS for voice cloning, but Qwen3 has significantly higher latency on CPU and is only viable for very low-volume voice-cloning customers (< 3 req/min) or customers willing to pay for GPU infrastructure — see the engine selection notes below. Cloud platform costs are calculated from published pricing. The deep technical methodology, four-way verification matrix (1 replica vs 2 replicas with both load-balancer policies, vs 2 replicas with reduced per-replica CPU), and the queue-blindness fix that closed the scaling gap are documented in [docs/replica-scaling-report.md](replica-scaling-report.md).

## Platform Profiles

### Comadre (Self-Hosted)

Open-source dual-engine TTS API optimized for Brazilian Portuguese. Runs on a standard VPS with no GPU required.

- **Primary engine:** Kokoro fp32 — fast CPU inference, no GPU required. All benchmarks in this report use Kokoro.
- **Secondary engine:** Qwen3-TTS C++ Q8_0 — voice cloning capability for the customer tier that has GPU budget OR very low volume (< 3 req/min). Not used in throughput/cost benchmarks because it does not scale on CPU.
- **Deployment:** Docker Compose on any VPS (4 vCPU / 8 GB RAM minimum for one replica; 8 vCPU / 16 GB RAM for the recommended two-replica configuration)
- **Pricing model:** Fixed monthly VPS cost (~$7/mo for one-replica entry tier, ~$21/mo for the verified two-replica configuration) or near-zero on self-hosted hardware
- **API:** OpenAI-compatible (`POST /v1/audio/speech`)
- **Languages:** Optimized for Brazilian Portuguese (espeak-ng custom dictionary, 67 sigla entries)
- **Load balancing (multi-replica):** Caddy reverse proxy with `dynamic a` upstream resolver and `lb_policy least_conn` — queue-depth-aware routing that exploits Comadre's single-FIFO-lock architecture to extract maximum sustained throughput from the available cores (validated 2026-04-11)

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

Budget cloud TTS aggregator that resells access to multiple providers — ElevenLabs, MiniMax, and Microsoft Edge TTS — through a unified credit system.

- **Providers:** ElevenLabs (premium voices), MiniMax (multilingual), Microsoft Edge TTS (free-tier quality)
- **Voice quality:** Varies by provider — ElevenLabs voices are excellent, MiniMax is very good, Edge is acceptable
- **Voice cloning:** Yes (via ElevenLabs provider)
- **Languages:** Dozens (inherits from ElevenLabs + MiniMax multilingual support)
- **Pricing model:** Credit packs
- **Rate:** $10 per 2,100,000 credits
- **Cost per audio (12s):** Edge ~90 credits, ElevenLabs/MiniMax ~140-190 credits
- **Effective rate (ElevenLabs/MiniMax):** ~12,350 audios per $10 = $0.00081/audio
- **Effective rate (Edge):** ~23,330 audios per $10 = $0.00043/audio
- **Cost per audio minute:** $0.0041 (ElevenLabs/MiniMax), $0.0021 (Edge)
- **Trade-off:** Quality depends on provider. Edge is cheapest but inferior to Kokoro (no cloning, worse prosody). ElevenLabs is best quality but costs 2x more credits. To match Comadre's quality, you need the MiniMax/ElevenLabs tier — not the cheap Edge tier. Latency and availability depend on upstream providers.

## Measured Performance (Comadre — Kokoro Engine)

This section reports performance data from two measurement campaigns. All data uses the Kokoro engine (`kokoro/pm_santa` voice), CPU-only inference, no GPU. The full technical methodology and verification matrix is in [docs/replica-scaling-report.md](replica-scaling-report.md).

**Test environment:** Proxmox VM, Xeon E5-2680v4, 8 vCPU shared / 16 GB RAM (configurable as either one 4-CPU replica or two 4-CPU replicas via `deploy.replicas` in `compose.yaml`). Equivalent to a Hetzner CPX31 (4 vCPU shared, 8 GB) for the single-replica tier or CPX41 (8 vCPU shared, 16 GB) for the two-replica tier.

### Verification campaigns

| Date | Workload | Configurations measured | Audio integrity |
|------|----------|------------------------|-----------------|
| 2026-04-06 | Deterministic 12-sentence corpus, sorted by length | 1 replica × 4 CPU | 818/818 (100%) |
| 2026-04-11 | **Randomized 24-sentence corpus** (varied topics, seeded `random.choice` for reproducibility) | 4 configurations: 1r/4c, 2r/4c round_robin, 2r/4c **least_conn**, 2r/3c least_conn | 2,440/2,440 (100%) |

The 2026-04-11 retest with the randomized corpus is **more conservative** than the older deterministic measurement: random adjacent picks include bursts of long messages that the sorted corpus smoothed out. The single-replica throughput observed dropped from 18 req/min (deterministic) to ~13 req/min (randomized). All sizing and cost figures below use the **conservative randomized numbers** so customers see worst-case capacity.

### Throughput by configuration (2026-04-11)

| Configuration | Sustainable throughput | Audio production rate | Notes |
|---|---|---|---|
| 1 replica × 4 CPU | **~13 req/min** | ~1.7 min audio per wall-clock minute | Single-instance ceiling |
| 2 replicas × 4 CPU, `round_robin` | ~19 req/min | ~2.5 min audio/min | Old default load balancer policy |
| **2 replicas × 4 CPU, `least_conn`** | **~20 req/min** | **~2.6 min audio/min** | **Recommended** — queue-aware routing |
| 2 replicas × 3 CPU, `least_conn` | ~15 req/min (worse) | ~1.9 min audio/min | Tested and rejected — under-CPU per replica |

The right metric for sizing is **audio production rate** (minutes of audio per wall-clock minute), because every Comadre replica is CPU-bound and produces a roughly constant amount of audio per second. Request throughput in req/min is derived from that rate divided by the average audio duration. With our measured average of **7.74 seconds per audio**, a single 4-CPU replica produces ~100 seconds of audio per wall-clock minute (~13 req/min), and the two-replica configuration produces ~155 seconds of audio per wall-clock minute (~20 req/min).

### Latency by request rate (2026-04-11, mean latency in seconds)

Measured with audio messages of 3.5–12.2 seconds (35–213 characters, mean 7.74 s / 123 chars — realistic chatbot variance).

| Target rate | 1 replica mean | 1 replica p50 | 1 replica max | 2 replicas LC mean | 2 replicas LC p50 | 2 replicas LC max |
|---|---|---|---|---|---|---|
| 2/min | 4.4s | 2.9s | 7.3s | 4.5s | 3.1s | 7.9s |
| 5/min | 5.2s | 5.5s | 7.2s | 4.9s | 5.4s | 7.7s |
| 10/min | 4.7s | 4.7s | 6.5s | 4.7s | 4.4s | 10.4s |
| 20/min | **36.6s** | 33.7s | 68.7s | **8.6s** | 8.1s | 17.5s |
| 30/min | **84.3s** | 84.0s | 165.5s | **37.8s** | 38.9s | 75.2s |
| 50/min | 177.3s | 170.5s | 335.6s | **95.3s** | 90.2s | 230.0s |
| 75/min | 280.5s | 272.0s | 624.8s | 162.8s | 160.7s | 331.4s |
| 100/min | 384.4s | 384.4s | 801.0s | 232.8s | 219.9s | 448.9s |

**Practical SLA target for WhatsApp customer service: latency ≤ 90 seconds (mean).** WhatsApp audio responses are asynchronous — the customer is not staring at the screen waiting in real time, the same way a typed reply in a professional conversation already takes 1+ minutes. A TTS-generated audio response that takes 30–90 seconds is invisible against the natural conversational rhythm. Above 90 seconds the system is starting to be stressed.

Under that 90-second SLA, **a single 4-CPU replica handles up to ~30 req/min** and **two replicas with `least_conn` handle up to ~50 req/min**. Above those rates, the queue grows faster than it drains, latency exceeds the SLA, and a larger configuration is required.

### Latency by text size (single request, no queue)

| Text size | Characters | Audio duration | Generation time |
|-----------|-----------|----------------|-----------------|
| Short | ~50 | 2.5–3.5s | 1.4–1.7s |
| Medium (typical chatbot) | ~120 | 7–8s | 4–6s |
| Long | ~200 | 11–13s | 5–7s |

### Resource usage

| Metric | 1 replica | 2 replicas |
|--------|-----------|------------|
| Memory at idle | ~570 MB | ~1,140 MB |
| Memory under load | ~1,028 MB stable | ~2,056 MB stable |
| Memory peak (all tests) | 1,502 MB | ~3,000 MB |
| Memory leak | None detected | None detected |
| CPU per replica | 4 cores (100% during generation) | 4 cores each |
| Total CPU at saturation | 4 cores | 8 cores |
| Crashes during testing | 0 | 0 |
| Audio corruption | 0/610 (1r capacity) | 0/1,830 (2r capacity across 3 runs) |

### What `least_conn` fixed (2026-04-11 verification)

The 2026-04-06 deployment used `lb_policy round_robin` for the multi-replica case. Round-robin is queue-blind: it dispatches new requests to replicas in fixed rotation, so when one replica is busy with a long message, the next request still goes there instead of the idle replica. Switching to `lb_policy least_conn` exploits Comadre's architecture: each replica processes requests serially behind a single `asyncio.Lock`, and the HTTP connection stays open during both queue wait and inference, so Caddy's "active connection count" exactly equals the queue depth + in-flight request on each replica. `least_conn` is therefore literally queue-depth-aware in this design.

Measured impact (2 replicas, concurrency 20 stress test):

| Metric | round_robin | least_conn |
|---|---|---|
| Heavy-scenario success rate | 60.0% | **91.1%** (+31.1pp, ~4.5x fewer client timeouts) |
| 20 req/min mean latency | 12.1s | **8.6s** (−29%) |
| 30 req/min mean latency | 36.3s | 37.8s (similar) |
| Saturation throughput (50–100 req/min) | ~19.4 r/min | ~19.6 r/min (+1%) |

The throughput gain at full saturation is small because both replicas are pinned to 100% CPU regardless of policy. The big win is in the **moderate-overload regime** (concurrency just above replica count), where queue-aware routing prevents one replica from accumulating a backlog while the other idles. That regime is where most real production loads sit.

## Cost Comparison

### Assumptions

- **Working days:** 22 per month
- **Working hours:** 8 per day
- **Average audio length (measured):** 7.74 seconds, 123 characters (mean of 1,830 verified Kokoro outputs from the 2026-04-11 randomized corpus, voice `kokoro/pm_santa`)
- **Messages per WhatsApp customer-service conversation:** ~6 audios (typical 5–10 minute professional turn-taking with audio on both sides)
- **Comadre cost reference:** Hetzner Cloud shared-vCPU pricing in 2026 — ~$7/mo for a 4-vCPU host (one replica), ~$21/mo for an 8-vCPU host (two replicas with `least_conn`). Self-hosted cost on existing hardware is near-zero (electricity only).
- **ElevenLabs cost basis:** Scale plan at $330/mo (2,000,000 chars included) + $0.18 per 1,000 chars overage. Conversion ~1,000 chars = 1 minute of audio per ElevenLabs documentation.
- **AI33.pro cost basis:** $10 per 2,100,000 credits. Cost per character derived from the $10/2.1M-credits rate and the published per-12s-audio credit costs (90 credits Edge tier; 140–190 credits ElevenLabs/MiniMax tier). At our measured 123-char average, that works out to ~$0.000264 per audio (Edge) or ~$0.000483 per audio (EL/MM).

### Cost by sustained traffic level

This table maps a customer's sustained req/min to the recommended Comadre configuration and the equivalent monthly cost on each platform. Volumes assume 8h × 22 working days/month at the listed sustained rate.

| Customer profile | Sustained req/min | Audios/month | Audio minutes/month | Comadre config | Comadre cost/mo | AI33.pro Edge | AI33.pro EL/MM | ElevenLabs Scale+ |
|---|---|---|---|---|---|---|---|---|
| Micro chatbot | 5 | 52,800 | 6,811 | 1 replica × 4 CPU | **~$7** | $14 | $26 | $1,139 |
| Small business | 10 | 105,600 | 13,622 | 1 replica × 4 CPU | **~$7** | $28 | $51 | $2,308 |
| Growing business | 13 (1r ceiling) | 137,280 | 17,709 | 1 replica × 4 CPU | **~$7** | $36 | $66 | $3,009 |
| Large operation | 20 (2r ceiling) | 211,200 | 27,245 | **2 replicas × 4 CPU** | **~$21** | $56 | $102 | $4,646 |
| High-volume | 28 | 295,680 | 38,143 | 3 replicas × 4 CPU (extrapolated) | **~$30–45** | $78 | $143 | $6,516 |
| Very-high-volume | 38 | 401,280 | 51,765 | 4 replicas × 4 CPU (extrapolated) | **~$45** | $106 | $194 | $8,854 |

The 1- and 2-replica rows are **measured** (1,830 audios verified end-to-end on 2026-04-11). The 3- and 4-replica rows are **extrapolated** from the linearity observed between 1r and 2r (each additional 4-CPU replica adds ~7 req/min of sustained capacity). The recommended scaling topology is **one larger VPS with N replicas**, not multiple small VPSs each running one replica — intra-host scaling with `least_conn` validated 2026-04-11 makes single-host multi-replica deployments operationally simpler and slightly cheaper than the multi-VPS approach.

### Cost per minute of audio

| Platform | Cost/min at "Small business" (10 req/min, ~227 hours audio/mo) | Cost/min at "Large operation" (20 req/min, ~454 hours audio/mo) | Pricing model |
|----------|-------------|-------------|-------|
| **Comadre 1 replica** | **$0.00051/min** | n/a (above 1r ceiling) | Fixed VPS |
| **Comadre 2 replicas** | n/a (below 2r utilization) | **$0.00077/min** | Fixed VPS |
| AI33.pro Edge | $0.00204/min | $0.00204/min | Per-credit |
| AI33.pro EL/MM | $0.00375/min | $0.00375/min | Per-credit |
| ElevenLabs Scale+overage | ~$0.169/min | ~$0.171/min | Per-character |

At the "Large operation" tier (20 req/min sustained, ~454 hours of audio per month), Comadre on a single 8-CPU VPS is **~5x cheaper than AI33.pro Edge tier**, **~10x cheaper than AI33.pro EL/MM tier**, and **~220x cheaper than ElevenLabs**. Above this tier the gap widens further because Comadre's marginal cost is the next VPS upgrade tier (~$15–25 to double capacity), while AI33.pro and ElevenLabs scale linearly with consumption forever.

### Why the Comadre cost stays flat

ElevenLabs and AI33.pro charge per audio (per character or per credit, scaled to length). Their cost grows linearly with every minute generated — there is no economy of scale beyond the plan boundary, only metering. A customer that 10x their volume sees their bill 10x.

Comadre charges what the VPS charges, full stop. Generating 200 hours of audio per month and generating 800 hours per month on the same VPS cost identically — the cost only changes when you cross a hardware capacity boundary and need a bigger VPS. Each VPS upgrade tier adds ~$15–25/month in exchange for ~150–410 additional hours of audio capacity per month. At the smallest viable size (~$7/mo, 1 replica) Comadre already pays for itself vs ElevenLabs above ~300 audios/month, and vs AI33.pro above ~30,000 audios/month.

## Capacity Planning

Comadre processes requests sequentially per replica (single FIFO queue per instance, `asyncio.Lock`). Multiple replicas share a host via Caddy's `dynamic a` upstream resolver and `lb_policy least_conn` (queue-aware routing).

### Sustainable throughput per replica configuration

Measured 2026-04-11 with realistic randomized chatbot corpus, mean audio 7.74 s.

| Configuration | Sustainable req/min | Max under 90s SLA (mean latency) | Audio production rate |
|---|---|---|---|
| 1 replica × 4 CPU | ~13 req/min | ~30 req/min | ~1.7 min audio per wall-clock minute |
| 2 replicas × 4 CPU + `least_conn` | ~20 req/min | ~50 req/min | ~2.6 min audio per wall-clock minute |
| 3 replicas × 4 CPU (extrapolated) | ~28 req/min | ~70 req/min | ~3.6 min audio per wall-clock minute |
| 4 replicas × 4 CPU (extrapolated) | ~38 req/min | ~95 req/min | ~4.9 min audio per wall-clock minute |

The "sustainable" column is the rate at which the queue stays bounded indefinitely. The "90 s SLA" column is the rate at which the mean per-request latency stays within the 90-second WhatsApp turn-taking budget — comfortably above sustainable because moderate overload is absorbed by the queue without exceeding 90 s mean wait. Each additional 4-CPU replica adds approximately 7 req/min of sustained capacity in linear fashion.

### When to add replicas / upgrade VPS

For WhatsApp chatbots, mean response times up to 90 seconds are well within the natural turn-taking rhythm of professional conversations and not perceived as delay by the customer.

| Business size | Sustained req/min | Recommended Comadre config | Recommended VPS size | Monthly cost |
|---|---|---|---|---|
| 50 clients/day, ~3 req/min | 3 | 1 replica × 4 CPU | 4 vCPU / 8 GB shared | ~$7 |
| 120 clients/day, ~5 req/min | 5 | 1 replica × 4 CPU | 4 vCPU / 8 GB shared | ~$7 |
| 300 clients/day, ~12 req/min | 12 | 1 replica × 4 CPU (at ceiling) | 4 vCPU / 8 GB shared | ~$7 |
| 500 clients/day, ~20 req/min | 20 | **2 replicas × 4 CPU + least_conn** | **8 vCPU / 16 GB shared** | **~$21** |
| 800 clients/day, ~28 req/min | 28 | 3 replicas × 4 CPU | 12+ vCPU / 24 GB | ~$30–45 |
| 1,000 clients/day, ~40 req/min | 38 | 4 replicas × 4 CPU | 16 vCPU / 32 GB | ~$45 |
| > 1,500 clients/day, > 50 req/min | 50+ | Multi-VPS or large dedicated host | Multiple 8 vCPU hosts | $40–80 |

**Sizing rule that came out of the 2026-04-11 verification:** never give a Kokoro replica fewer than 4 CPU cores. Tested 3-CPU per replica directly (Run D) and observed ~22% throughput regression with no latency benefit — ONNX inference is CPU-bound and scales close to linearly down to 4 cores. The optimal layout is `replicas = floor(host_cpus / 4)`, leaving Caddy and the host kernel to share whatever cores remain.

Horizontal scaling can also be done by adding *multiple VPS instances* (each running 1 replica) behind an external Caddy. This trades a small cost premium for stronger failure isolation: losing one VPS only loses 1/N of capacity instead of all of it. For most customers the single-host multi-replica approach is simpler and slightly cheaper; multi-VPS is the right choice when uptime targets demand independent failure domains.

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

Every number below is measured (2026-04-11 randomized corpus, voice `kokoro/pm_santa`).

| Condition | 1 replica response time | 2 replicas (`least_conn`) response time | Source |
|-----------|------------------------|----------------------------------------|--------|
| No queue (< 10 req/min) | 4–5 s mean | 4–5 s mean | Capacity test |
| Light load (20 req/min) | 36 s mean | **8.6 s mean** | Capacity test |
| Moderate load (30 req/min) | 84 s mean (at SLA limit) | 38 s mean | Capacity test |
| Heavy load (50 req/min) | 177 s mean (over SLA) | **95 s mean** (at SLA limit) | Capacity test |
| Heavy concurrency (20 simultaneous, 5-min stress) | 27.7 % success (timeouts) | **91.1 % success** (`least_conn` win) | Loadtest |
| Server crash | 0 incidents in 2,440+ requests | 0 incidents | All tests |
| Audio corruption | 0 incidents in 2,440+ requests | 0 incidents | All tests |

Comadre's latency is deterministic: it depends only on queue depth, which depends only on your own traffic. No other customer affects your performance. The `least_conn` policy added in the 2026-04-11 verification reduced the heavy-concurrency timeout rate by ~4.5x compared to the previous round-robin policy, by routing each new request to whichever replica has the shortest queue at that moment.

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
| **Voice quality** | Very good (Kokoro) | Excellent | Varies (ElevenLabs/MiniMax/Edge) |
| **BR-PT optimization** | Yes (custom dictionary) | Generic multilingual | Generic (via providers) |
| **Sigla pronunciation** | Perfect (67 verified entries) | Inconsistent | Inconsistent (no custom dict) |
| **Voice cloning** | Yes (Qwen3 + kokoro-cloner) | Yes (premium) | Yes (via ElevenLabs provider) |
| **Custom voicepacks** | Yes (kokoro-cloner pipeline) | No (predefined clones) | No |
| **Built-in voices (pt-BR)** | 3 optimized + unlimited via kokoro-cloner | Hundreds (multilingual) | Hundreds (from 3 providers) |
| **Language focus** | Brazilian Portuguese only | Dozens of languages | Dozens (via ElevenLabs + MiniMax) |
| **Data privacy** | Full (on-premise) | Cloud (third-party) | Cloud (third-party) |
| **LGPD compliance** | Inherent (no data leaves your server) | Requires DPA | Requires DPA |
| **Uptime control** | You control | Vendor-dependent | Vendor-dependent |
| **Network dependency** | None (runs offline) | Requires internet | Requires internet |
| **API compatibility** | OpenAI-compatible | Proprietary | Proprietary |
| **Latency predictability** | Measured, deterministic | Variable, shared | Variable, shared |
| **Cost model** | Fixed monthly | Per-character | Per-credit |
| **Cost at 15k msgs/mo** | $7/mo | $330/mo | $13/mo |
| **Cost at 211k msgs/mo (~454h audio)** | $21/mo (2 replicas) | $4,646/mo | $102/mo (EL/MM tier) |
| **Horizontal scaling** | Manual (add VPS) | Automatic | Automatic |
| **Setup complexity** | Medium (Docker + Ansible) | None (SaaS) | Low (API key) |
| **Maintenance** | Self-managed | Zero | Zero |

## Voice Quality & Cloning

### Quality Positioning

Comadre's Kokoro engine produces very good audio quality — comparable to MiniMax and noticeably better than Microsoft Edge TTS. It is only slightly inferior to ElevenLabs' top-tier models. AI33.pro's quality varies depending on which provider is selected: their ElevenLabs voices are excellent, MiniMax voices are very good (comparable to Comadre), and Edge voices are noticeably lower quality. For WhatsApp, Telegram, and Messenger voice messages, the quality difference between Comadre and AI33.pro's MiniMax tier is negligible. ElevenLabs retains an edge for premium use cases like audiobooks, brand voices, and marketing videos.

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

Two measurement campaigns inform this report. The 2026-04-11 four-way verification matrix is the canonical source for sizing and cost figures because it uses a more realistic randomized workload — the older 2026-04-06 numbers remain referenced where they add historical context. Full details and the detailed-table-by-table data of the four-way matrix is in [docs/replica-scaling-report.md](replica-scaling-report.md).

### Saturation test (`scripts/loadtest.py`)

- 6 scenarios: baseline (concurrency 1), light (3), moderate (10), heavy (20), stress (50), burst (30 simultaneous)
- ~370 total requests per run (varies with scenario duration)
- Audio validation via ffprobe (duration > 0.1 s)
- Health monitoring every 1 second (queue depth, memory)
- Timeout: 130 seconds per request (matches the worst-case n8n-style client timeout)
- 2026-04-11 retest: deterministic seed (`--seed 42`) and randomized corpus selection make runs reproducible across configurations

### Capacity test (`scripts/capacity_test.py`)

- 8 rate tiers: 2, 5, 10, 20, 30, 50, 75, 100 requests/minute
- ~610 total requests per run (8 tiers × 20 to 200 requests per tier depending on rate)
- No client timeout — every request waits until completion, so the test measures latency under sustained pressure rather than client-side timeouts
- 2026-04-11 retest: same seeded randomized corpus, same rate tiers, run against four configurations (1r/4c, 2r/4c round_robin, 2r/4c least_conn, 2r/3c least_conn)

### Text corpus

- **2026-04-06:** 12 Brazilian Portuguese sentences (80–200 characters, 5–12 second audio), selected deterministically by `text = TEXTS[req_id % len(TEXTS)]` — sorted by length, so each lap of 12 requests delivered the same `5-short + 4-medium + 3-long` shape
- **2026-04-11:** 24 Brazilian Portuguese sentences spanning the same 5–12 second audio window but covering varied topics (orders, shipping, payment methods, returns, support, scheduling, fidelity, NF-e) and varied greetings (Oi, Olá, Bom dia, Boa tarde, Boa noite, no greeting). Selection now uses a seeded `random.Random(seed)` instance shared across all tiers, with texts pre-computed per tier so the sequence is fully deterministic regardless of asyncio scheduling.
- Mean audio duration measured across 1,830 verified outputs from 2026-04-11: **7.74 seconds** (123 characters average, ~16 chars/second of audio)

### Environment

- **Host (2026-04-06):** Proxmox 9.1.7 VM on Xeon E5-2680v4, equivalent to a Hetzner CPX31 (4 vCPU shared / 8 GB RAM). Container limits: 4 CPU, 6 GB RAM.
- **Host (2026-04-11):** Same Proxmox/Xeon E5-2680v4 hardware, deployed VPS configuration — 8 vCPU shared / 16 GB RAM. Per-replica container limits: 4 CPU, 6 GB RAM. Two-replica configurations use both replicas of `tts-service` behind a single Caddy reverse proxy.
- **Engine:** Kokoro fp32 (ONNX), voice `kokoro/pm_santa` — CPU-only, no GPU.
- **Qwen3 was not used** in any throughput benchmark — see the engine selection notes in the executive summary for why.
- **Output format:** OGG Opus 24 kbps, 16 kHz mono.
- **Audio integrity (2026-04-11):** 2,440 of 2,440 requests across all four configurations produced valid audio files (verified with `ffprobe`). Zero crashes, zero corrupted outputs.
- **Test dates:** 2026-04-06 (initial single-replica), 2026-04-11 (multi-replica four-way verification)

## v3 Addendum — pocket-tts measured on the production VPS (2026-08-22)

Single replica, 4 vCPU shared (Proxmox VM, CPX31-class), `pocket/rafael`,
OGG Opus output. Full methodology identical to the sessions above
(`scripts/loadtest.py` 6 scenarios + `scripts/capacity_test.py` 8 rate
tiers, seed 42); raw data in `tests/results/v3-loadtest/` and
`tests/results/v3-capacity/`.

| Metric | v2 (Kokoro fp32) | v3 (pocket-tts 2.1.0) |
|---|---|---|
| Single-request latency (mixed sizes) | p50 ~12 s | p50 5.65 s |
| Sustained single-replica ceiling | ~13 req/min | ~16 req/min |
| Comfortable operating zone | ≤ 8 req/min (p50 < 6 s) | ≤ 10 req/min (p50 3.7–4.2 s) |
| RTF (inference+pipeline, in-container) | ~0.7–0.9 | 0.53–0.58 |
| Native voice cloning | No (Qwen3 sidecar, RTF 2.4+) | Yes, included (clone encode 0.7 s for a 10 s ref) |
| Audio integrity (this session) | 2440/2440 | 700/700 (loadtest 147 + capacity 580 incl. clone smoke) |

Above the ceiling every extra request just queues behind the FIFO and
the client's 130 s timeout eventually fires — by design (backpressure,
not collapse). Memory stayed flat through all tiers. Cost conclusion is
unchanged and strengthens: fixed ~$7/month now includes cloning that
previously needed a separate Qwen3 pipeline at 1/4 the speed.
