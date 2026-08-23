# Comadre Horizontal Scaling Report — pocket-tts v3

Measured 2026-08-23 on the production Proxmox VM (`10.10.10.207`), engine
pocket-tts 2.1.0 (distilled 6-layer model, `torch.set_num_threads(1)` per
replica), voice `pocket/rafael`, workload seed 42. Raw artifacts:
`tests/results/campaign-v3/` (`r1-4vcpu-extra/`, `r1/`, `r2/`, `r2-4vcpu/`).
Deployed versions during the campaign: 3.0.5–3.0.7 (engine identical, pinned).

## Environment

| Host size | CPU | RAM | Per-replica limit |
|---|---|---|---|
| Small | 4 vCPU (Xeon E5-2680 v4) | 8 GB | 4 CPU / 6 GB (`compose.yaml`) |
| Large | 8 vCPU (same physical CPU pool) | 16 GB | same |

The VM is resized between host sizes; IP, disk and containers are unchanged.
One Caddy fronts all replicas via the `dynamic a` upstream resolver +
`least_conn` policy (commit `373493a`; queue-depth-aware, re-resolves Docker
DNS every 5 s).

## Methodology

- `scripts/loadtest.py --scenario all --seed 42` — six scenarios
  (baseline c=1 ×20; light c=3 180 s; moderate c=10 300 s; heavy c=20 300 s;
  stress c=50 180 s; burst c=30 ×30). Client timeout 130 s.
- `scripts/capacity_test.py --seed 42` — sustained-rate tiers 2→100 req/min,
  120 s each, no client timeout (600 s per request).
- Test key `vnMQTBKO` rpm raised to 10000 for the run, restored to 100 after.
- No other traffic on the VPS during runs.

## Results — capacity test (sustained throughput ceiling)

Actual achieved rate once the target exceeds server capacity (100% audio
validity everywhere; queueing absorbs the difference):

| Config | Plateau | Scaling vs 1r |
|---|---|---|
| 1 replica @ 4 vCPU | **15.5 req/min** | — |
| 2 replicas @ 4 vCPU | **21.0 req/min** | 1.35x |
| 1 replica @ 8 vCPU | **19.6 req/min** | — |
| 2 replicas @ 8 vCPU | **30.0 req/min** | 1.53x |

Latency below saturation (p50, ≤ 20 req/min target): 2.0–6.3 s across all
configs. Above saturation the FIFO queue grows linearly (e.g. 1r @ 4 vCPU
targeting 100 req/min → p50 307 s) until the client timeout kills requests.

## Results — load test (saturation behaviour)

Throughput in successful req/min (success % where < 100):

| Scenario | 1r @ 4 vCPU | 2r @ 4 vCPU | 1r @ 8 vCPU | 2r @ 8 vCPU |
|---|---|---|---|---|
| baseline (c=1) | 9.1 · p50 5.97s | 9.4 · 5.86s | 11.6 · 4.57s | 11.7 · ~4.6s |
| light (c=3) | 9.4 | 14.0 | 13.4 | 17.7 |
| moderate (c=10) | 9.4 | 11.8 | 10.7 | 16.1 |
| heavy (c=20) | 9.1 (26%) | 11.3 (92%) | 11.5 (100%) | 18.9 (100%) |
| stress (c=50) | 14.0% | 22.0% | 23.4% | 36.1% |
| burst (c=30) | 0% | 0% | 0% | 33.3% |

Reading:

- **Below concurrency ≈ 10 every config is lossless** (100% success).
- **heavy (c=20)** is the practical discriminator: a single 4-vCPU replica
  collapses (26%), anything else holds ≥ 92%; both configs on the large host
  hold 100%.
- stress/burst failures are client-timeout kills of queued requests (130 s),
  not server errors — the server drains the queue afterwards.

## Analysis

1. **Scaling is sub-linear because CPU is shared.** On the 4-vCPU host, two
   replicas fight for the same cores (per-replica limit 4 CPU > host total);
   the second replica adds queue-drain parallelism (+35%) but not compute.
   On the 8-vCPU host there is headroom and scaling reaches 1.53x.
2. **Hardware and replicas are complements.** Going 4→8 vCPU at 1 replica
   buys +26% ceiling; at 2 replicas, +43%. The largest jump (15.5 → 30) needs
   both.
3. **`least_conn` is load-bearing** — with the old queue-blind policy the v2
   campaign measured only 1.5x scaling even without CPU contention.
4. **Per-replica rate-limit buckets remain per-instance** (in-memory
   `limits` storage): N replicas multiply effective per-key RPM by N.
   Documented in [rate-limiting.md](rate-limiting.md); Redis backend remains
   the future fix if strict cluster-wide limits are ever required.

## Recommendations

- Default deployment stays `replicas: 1`. The current production VM is back
  on its standard 4 vCPU profile, ceiling ≈ 15 req/min ≈ 20k+ audios/day —
  ample for WhatsApp chatbot traffic (see
  [cost-comparison-report.md](cost-comparison-report.md)).
- Scale to `replicas: 2` only together with a host resize to ≥ 8 vCPU;
  2 replicas on 4 vCPU mostly buy shorter queues, not more throughput.
- Update playbooks: restart replicas individually on deploy (simultaneous
  cold starts spike memory N × ~1.5 GB and race the first model download).
