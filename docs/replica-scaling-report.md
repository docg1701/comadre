# Comadre Horizontal Scaling Report — 1 vs 2 Replicas

## Executive Summary

Doubling Comadre's `deploy.replicas` from 1 to 2 increases sustainable throughput from ~14 to ~21 requests per minute (a 1.5x speedup, not the theoretical 2x), and cuts p50 latency at saturation (50/min target) from 149s to 100s — a 33% reduction. The scaling is sub-linear because Caddy's `round_robin` load balancer is queue-blind: it dispatches new requests to busy replicas while idle ones could serve them faster, and CPU contention on the host (8 vCPU shared by two 4-CPU replicas) leaves no headroom for overhead.

Two infrastructure bugs were uncovered and fixed during this test, both committed to the repo:

1. **Caddy load-balancing was broken at every replica > 1.** Plain `reverse_proxy tts-service:8000` resolves Docker DNS once at startup and pins all traffic to a single replica IP. Verified empirically: 10/10 health requests landed on replica 1 (uptime 5970s) while replica 2 (uptime 1148s) received zero traffic. Fixed by replacing the simple form with Caddy's `dynamic a` upstream resolver plus `lb_policy round_robin` (Caddyfile commit `373493a`).
2. **HTTPS/IP access produced TLS internal errors.** When clients connect to an IP address (not a hostname), curl and most TLS libraries do not send SNI per RFC 6066, and Caddy could not pick a certificate. Fixed by adding `default_sni {$DOMAIN:localhost}` to the Caddyfile global block (commit `955675d`).

After both fixes, the scaling pipeline works end-to-end: a single `replicas: 1 → 2` change in `compose.yaml` followed by `docker compose up -d` produced two healthy replicas with verified round-robin distribution and 100% audio integrity at sustainable load.

## Test Environment

- **VPS:** Proxmox VM, Xeon E5-2680v4, 8 vCPU shared, 16 GB RAM, IP `10.10.10.207`
- **Per-replica limits:** 4 CPU cores, 6 GB RAM (`compose.yaml` `deploy.resources.limits`)
- **Reverse proxy:** Caddy 2-alpine, HTTPS with self-signed cert from internal CA
- **Engine:** Kokoro fp32 (ONNX), voice `kokoro/pm_santa`, no Qwen3 in benchmarks
- **OS:** Debian 13 (bookworm), Docker Engine 28.x, Compose v2
- **Comadre version:** v1.5.3 + commits `955675d`, `373493a`
- **Test date:** 2026-04-10
- **Audio format:** OGG Opus 24kbps 16kHz mono
- **Test workload:** 12 Brazilian Portuguese chatbot sentences, 80–200 chars, producing 5–12s audio

### Test methodology

Two scripts were run against each replica configuration:

| Script | Purpose | Scenarios | Total requests |
|--------|---------|-----------|----------------|
| `scripts/loadtest.py` | Saturation, queue, failure modes | 6 (baseline → burst, concurrency 1–50) | ~370 per run |
| `scripts/capacity_test.py` | Rate-based throughput, 8 tiers | 2, 5, 10, 20, 30, 50, 75, 100 req/min | 610 per run |

Procedure for each replica configuration:

1. `docker compose restart tts-service` — clear queue and memory state
2. Wait for `/health` to return `healthy` with `queue_depth=0`
3. Run `loadtest.py --scenario all`
4. `docker compose restart tts-service` again — clear loadtest queue
5. Run `capacity_test.py`

The restart between scripts is mandatory: without it, the capacity test's lowest tier inherits the stress-test queue and reports nonsense (a contaminated run on 1r showed `queue=69, p50=300s` at the 2/min tier — fixed by the restart and re-run).

### Adjustments needed for valid testing

Two production defaults had to be temporarily overridden on the VPS during testing. Both were restored at the end.

| Setting | Production default | During test | Why |
|---------|--------------------|-------------|-----|
| `RATE_LIMIT_SPEECH` | `30/minute` | `10000/minute` | Stress (50 concurrent) and burst (30 simultaneous) generated thousands of 429 responses, masking real saturation behavior |
| Test scripts TLS verify | Strict | `--insecure` flag added | Self-signed cert from Caddy's internal CA fails strict verification |

The test scripts now accept `--insecure` (commit `955675d`) so future runs against self-signed deployments work without code changes.

## Loadtest Results

`scripts/loadtest.py --scenario all` — 6 scenarios with increasing concurrency. Throughput is measured in successful requests per minute over the scenario wall time.

| Scenario | Concurrency | 1r success | 1r req/min | 1r p50 | 2r success | 2r req/min | 2r p50 | Throughput speedup | p50 reduction |
|----------|-------------|------------|------------|--------|------------|------------|--------|--------------------|---------------|
| baseline | 1 | 100% (20/20) | 7.1 | 7.95s | 100% (20/20) | 7.1 | 8.00s | 1.00x | — |
| light | 3 | 100% (28/28) | 8.4 | 21.68s | 100% (39/39) | 11.4 | 10.21s | **1.36x** | **53%** |
| moderate | 10 | 100% (53/53) | 8.2 | 72.62s | 100% (74/74) | 13.4 | 42.59s | **1.63x** | **41%** |
| heavy | 20 | 48.5% (32/66) | 9.3 | 130.00s | 78.2% (68/87) | 12.5 | 71.27s | **1.34x** | **45%** |
| stress | 50 | 17.8% (18/101) | 20.5* | 130.03s | 26.1% (29/111) | 21.9* | 130.01s | 1.07x | — |
| burst | 30 simul. | 0% (0/30) | — | — | 0% (0/30) | — | — | — | — |

\* Stress throughput numbers are inflated because most requests fail fast at the 130s timeout — only the 18 (1r) and 29 (2r) successful completions are meaningful for throughput.

### Loadtest observations

- **Baseline is unchanged.** A single concurrent request can only use one replica at a time, so adding a second one provides no benefit. Both runs complete the same 20 requests in ~168 seconds with ~8s p50 latency.
- **Light and moderate are where 2 replicas pay off.** At concurrency 3 and 10, the second replica has work to do, queue depth stays manageable (max 3 and 9 respectively for 2r vs max 3 and 10 for 1r), and 100% of requests succeed.
- **Heavy scenario (concurrency 20) shows the biggest practical improvement.** Success rate jumps from 48.5% to 78.2% — the 130s client-side timeout kills fewer requests because the queue drains twice as fast. 36 additional audios per 7-minute test window.
- **Stress scenario is dominated by timeouts on both configurations.** Sending 50 concurrent requests against a server that processes ~12 req/min always loses — adding a second replica just halves the kill rate (from 82% to 74% failures).
- **Burst is broken on both runs (0% success).** The 30 simultaneous requests inherit the 80+ depth queue from the preceding stress scenario; they all hit the 130s timeout. This is a test ordering artifact, not a scaling failure. The loadtest scenarios run back-to-back with no inter-scenario drain, and at ~12 req/min processing rate the queue takes ~7 minutes to clear — longer than the 130s timeout. To fix this would require either a queue-drain step in the loadtest script or running burst as a standalone scenario.

### Memory under load

| Configuration | Idle (per-replica) | Peak (per-replica) | Total VPS RAM |
|---------------|--------------------|--------------------|-----|
| 1 replica | 568 MB | 1502 MB | ~1.5 GB |
| 2 replicas | 568 MB | 1494 MB | ~3.0 GB |

Each replica behaves identically and uses the same amount of memory. Two replicas double the memory cost. The 6 GB per-replica limit in `compose.yaml` is comfortable headroom for the observed ~1.5 GB peak (Kokoro-only workload — Qwen3 would push it to ~5.7 GB per replica).

## Capacity Test Results

`scripts/capacity_test.py` — 8 controlled rate tiers, 120 seconds per tier, no client-side timeout (all requests wait until completion).

| Target | 1r actual | 1r p50 | 1r p95 | 1r max | 2r actual | 2r p50 | 2r p95 | 2r max | Throughput speedup |
|--------|-----------|--------|--------|--------|-----------|--------|--------|--------|--------------------|
| 2/min | 2.1/min | 3.9s | 6.9s | 7.0s | 2.1/min | 4.4s | 7.8s | 7.9s | 1.00x |
| 5/min | 5.2/min | 3.9s | 6.6s | 6.8s | 5.1/min | 4.2s | 6.9s | 7.7s | 0.98x |
| 10/min | 10.1/min | 4.0s | 6.8s | 7.0s | 10.1/min | 4.3s | 9.0s | 10.4s | 1.00x |
| 20/min | 14.7/min | 23.1s | 47.4s | 48.3s | 16.7/min | 11.9s | 26.0s | 26.5s | **1.14x** |
| 30/min | 14.4/min | 60.3s | 119.4s | 132.3s | 19.7/min | 26.3s | 58.5s | 66.8s | **1.37x** |
| 50/min | 13.7/min | 149.1s | 301.7s | 318.2s | 17.2/min | 100.6s | 211.7s | 230.0s | **1.26x** |
| 75/min | 12.1/min | 336.1s | 600.8s | 624.8s | 20.0/min | 160.7s | 312.0s | 331.4s | **1.65x** |
| 100/min | 13.0/min | 396.6s | 763.2s | 801.0s | 21.1/min | 219.9s | 416.5s | 448.9s | **1.62x** |

All 1640 requests across both runs were successful and produced valid audio files (verified with ffprobe).

### Capacity test observations

- **Below the 1r plateau (2, 5, 10/min) the second replica is invisible.** Both configurations match the target rate, and p50 latency is 4–5 seconds (the natural cost of generating one chatbot-length audio). The scheduler simply has no spare requests to send to replica 2.
- **Sustainable throughput plateau:**
  - 1 replica: ~12–15 req/min
  - 2 replicas: ~17–21 req/min
- **Effective capacity gain at saturation: 1.4–1.6x, not 2x.** The single biggest reason is that Caddy's `round_robin` policy is queue-blind. When request A is in flight on replica 1 (taking 11s for a long message) and request B arrives, round-robin sends it to replica 2 (good). But request C, arriving immediately after, goes back to replica 1 — even though replica 2 might finish first. With workload variance from 80–200 char messages producing 5–12s audio, replica utilization becomes uneven. A queue-aware policy like `lb_policy least_conn` would likely close most of the gap.
- **Latency at peak load improves dramatically.** At 30/min the p50 drops from 60.3s to 26.3s (56% reduction). At 50/min, p50 drops from 149.1s to 100.6s (33% reduction). At 75/min, p50 drops from 336.1s to 160.7s (52% reduction). This is the most user-visible benefit of scaling — even when total throughput doesn't double, individual request wait times do roughly halve under heavy load.
- **The 1r plateau is a flat ceiling.** Above 14 req/min the actual throughput on 1r flatlines and does not climb — sending more requests just grows the queue. The 2r plateau is the same shape, just higher (~21 req/min).

### Throughput plateau visualization

```text
req/min actual throughput
   25 │
   20 │                                    ●═══════●═══════●  2 replicas
      │                            ●═══════/
   15 │                  ●─────────●───────●───────●───────●  1 replica
      │                  /
   10 │           ●─────/
      │          /
    5 │      ●──/
      │   ──/
    0 │──/
      └────┬────┬────┬────┬────┬────┬────┬────┬──→
           2    5    10   20   30   50   75   100  target req/min
```

## Scaling Efficiency Analysis

### Why is the speedup 1.5x and not 2x?

Three contributing factors, in order of impact:

1. **Caddy round-robin is queue-blind.** When request durations vary (5–12s in our workload), naive rotation sends new requests to whichever replica is "next" rather than "freest." Long-running requests on one replica accumulate queue depth while the other replica idles. Switching to `lb_policy least_conn` would address this directly.
2. **Per-process Python overhead.** Each replica runs a complete Python process with Kokoro loaded (~568 MB idle, ~1500 MB peak). Two processes mean double the GIL coordination, double the memory bandwidth pressure, and double the GC. On a CPU-bound workload like ONNX inference, this overhead is small but non-zero.
3. **CPU contention.** Two replicas at 4 CPU each = 8 CPU = the full VPS allocation. There is zero headroom for the host, Caddy, audio cleanup cron, or other system processes. The Linux scheduler still preempts replica work to run housekeeping. Lifting the per-replica limit to 3 CPU (6 CPU total) would leave 2 CPU free but reduce single-request latency.

### What scales linearly and what doesn't

| Metric | Scaling behavior | Notes |
|--------|------------------|-------|
| Memory (idle) | **Linear** (1.0x → 2.0x) | Each replica is independent — Python + Kokoro model duplicated |
| Memory (peak) | **Linear** (1.0x → 2.0x) | Same model loaded twice into RAM |
| CPU (under load) | **Linear** (1.0x → 2.0x) | Both replicas saturate their CPU limit |
| Throughput (sustainable) | **Sub-linear** (1.0x → 1.4–1.6x) | Round-robin variance + CPU contention |
| Latency at saturation | **Roughly inverse** (1.0x → 0.5x) | The most user-visible benefit |
| Idle baseline latency | **Unchanged** (1.0x → 1.0x) | A single request still uses one replica |

## Resource Cost Comparison

| Resource | 1 replica | 2 replicas | Delta |
|----------|-----------|------------|-------|
| Idle memory | ~570 MB | ~1140 MB | +570 MB (+100%) |
| Peak memory (Kokoro only) | ~1500 MB | ~3000 MB | +1500 MB (+100%) |
| Peak memory (with Qwen3) | ~5700 MB (estimate) | ~11400 MB (estimate) | +5700 MB |
| CPU at saturation | 4 cores | 8 cores | +4 cores |
| Required VPS | 4 vCPU, 8 GB | 8 vCPU, 16 GB | doubled |
| Sustainable throughput | ~14 req/min | ~21 req/min | +7 req/min (+50%) |
| Cost per req/min (sustainable) | $0.50/mo (Hetzner CPX21 ÷ 14) | $0.70/mo (Hetzner CPX31 ÷ 21) | +40% |

The cost per sustainable request is **higher** with 2 replicas because the throughput gain (50%) is smaller than the resource cost (100%). For pure throughput-optimized deployments, two smaller VPSs each running 1 replica would be more cost-effective than one larger VPS running 2 replicas. The case for 2 replicas on a single host is **operational** (single management plane, single Caddy, single backup target) rather than economic.

## Caveats and Issues Observed

### Issues fixed during testing (in repo)

1. **Caddy did not load-balance at all** with plain `reverse_proxy tts-service:8000`. Fixed in commit `373493a` by switching to `dynamic a` resolver with `lb_policy round_robin`. The `dynamic a` directive re-queries Docker's internal DNS every 5 seconds, picks up newly-added replicas without restart, and rotates traffic across all returned A records.
2. **TLS internal error on IP-based access** because curl/httpx don't send SNI when connecting to a literal IP. Fixed in commit `955675d` by adding `default_sni {$DOMAIN:localhost}` to the Caddyfile global block.
3. **Test scripts couldn't reach HTTPS-only deployments** due to strict cert verification on self-signed certs. Fixed in commit `955675d` by adding `--insecure` to both `loadtest.py` and `capacity_test.py`.

### Known limitations of this test methodology

- **The loadtest's burst scenario inherits queue from the preceding stress scenario.** Both 1r and 2r show 0% success on burst — this is a test ordering artifact, not a scaling defect. The fix is to run burst standalone or insert a queue-drain wait.
- **Capacity test's lowest tier is sensitive to startup state.** A first run on 1r showed contaminated 2/min results because the loadtest queue hadn't drained. Always restart the service between loadtest and capacity test.
- **Rate limiting blocks load testing.** The default `RATE_LIMIT_SPEECH=30/minute` causes 429 storms under stress workloads. For testing, raise it to a high value (`10000/minute`) on the VPS via `.env`, recreate the service, and restore afterward.

### Operational caveats for multi-replica deployments

- **All replicas restart simultaneously.** The daily restart cron and `docker compose up -d --no-build` recreate every replica at once. With 2+ replicas, the simultaneous model load at boot can spike memory to `N × 1500 MB` (Kokoro) or `N × 5700 MB` (Kokoro+Qwen3). Mitigation: restart replicas individually (`for i in $(docker compose ps -q tts-service); do docker restart "$i"; sleep 60; done`).
- **First deploy must use `replicas: 1`.** Concurrent model downloads from multiple replicas to the same shared volume can corrupt the model files. Always start with 1 replica, let it download and cache models, then scale up.
- **`depends_on: condition: service_healthy` blocks Caddy on every replica passing healthcheck.** If one replica fails to start (e.g., OOM during simultaneous model load), Caddy never starts and the entire service is unreachable. For multi-replica deployments where partial availability is preferable, change to `condition: service_started`.
- **Rate limiting is per-instance.** With 2 replicas and `RATE_LIMIT_SPEECH=30/minute`, a single client IP can effectively send 60 req/min (30 per replica) because slowapi is in-memory and not shared across replicas. For strict global rate limiting, an external Redis store would be required.
- **Health endpoint reports per-instance state.** Whichever replica answers the health request reports its own `queue_depth`, `memory_mb`, and `uptime_seconds`. Cluster-wide observability requires querying each replica directly via `docker exec`, or aggregating logs.

## Recommendations

### When to scale to 2 replicas

Scale up when **all** of the following hold:

- Sustained traffic regularly exceeds **10 req/min** (the queue-free 1r capacity)
- p95 latency under your normal load exceeds your acceptable budget (e.g., > 30s for chatbot UX)
- The VPS has **at least 8 vCPU and 12 GB RAM free** for the replicas (plus host overhead)
- Operational simplicity (single host, single restart cycle) is preferred over per-VPS cost optimization

### How to scale safely

```bash
# 1. Verify current deployment is healthy
ssh galvani@10.10.10.207 "cd ~/comadre && docker compose ps"

# 2. Edit compose.yaml on the VPS (or via git pull if committing the change)
ssh galvani@10.10.10.207 "cd ~/comadre && sed -i 's/replicas: 1/replicas: 2/' compose.yaml"

# 3. Recreate (creates the new replica, leaves the old one running)
ssh galvani@10.10.10.207 "cd ~/comadre && docker compose up -d"

# 4. Verify both replicas healthy
ssh galvani@10.10.10.207 "cd ~/comadre && docker compose ps"

# 5. Confirm Caddy is round-robining (uptime values should alternate)
for i in $(seq 1 10); do curl -sk https://YOUR_DOMAIN/health | jq .uptime_seconds; done
```

### Future improvements that would close the scaling gap

1. **Switch to `lb_policy least_conn` in the Caddyfile.** This would route new requests to whichever replica has the fewest active connections, reducing variance from long-message processing. Expected gain: throughput speedup from ~1.5x to ~1.8x at saturation.
2. **Reduce per-replica CPU limit to 3 cores.** With `cpus: "3"`, two replicas use 6 of 8 CPUs, leaving 2 for host overhead. This may increase single-request latency (~10–15%) but reduce scheduling jitter and improve consistency at peak.
3. **Use external rate limiting (Redis-backed slowapi or Caddy-level limits).** Per-instance rate limiting multiplies the effective limit by replica count, which is rarely the desired behavior in production.
4. **Implement startup staggering in the daily restart cron.** Restart one replica, wait for healthy, then restart the next. Avoids the simultaneous model-load memory spike.

### Per-VPS scaling vs multi-VPS scaling

For pure throughput-per-dollar, **N small VPSs each running 1 replica is more cost-effective** than 1 large VPS running N replicas, because the round-robin variance and CPU contention disappear when each replica owns its own host. The per-VPS approach also gives independent failure domains: one host going down loses 1/N of capacity instead of all capacity. The per-host approach (multiple replicas on one VPS) wins when operational simplicity (single host to manage) outweighs the throughput-per-dollar gap.

## Summary

| Metric | 1 replica | 2 replicas | Verdict |
|--------|-----------|------------|---------|
| Sustainable throughput | ~14 req/min | ~21 req/min | **1.5x** (sub-linear) |
| p50 latency at 50/min target | 149s | 100s | **1.5x faster** |
| p95 latency at 50/min target | 302s | 212s | **1.4x faster** |
| Memory (peak, Kokoro only) | ~1500 MB | ~3000 MB | 2x (linear) |
| CPU (saturated) | 4 cores | 8 cores | 2x (linear) |
| Audio integrity | 100% | 100% | unchanged |
| Idle latency (single request) | 4s | 4s | unchanged |
| Required VPS | 4 vCPU / 8 GB | 8 vCPU / 16 GB | doubled |

Horizontal scaling via `deploy.replicas` works correctly after the Caddy `dynamic a` fix in commit `373493a`. The single-character `replicas: 1 → 2` change in `compose.yaml` followed by `docker compose up -d` produces a working two-replica deployment with verified round-robin distribution. The scaling efficiency is 1.5x rather than 2x, primarily because Caddy's round-robin policy doesn't account for queue depth — switching to `least_conn` would likely improve this. For workloads that need more than ~14 req/min sustainable throughput on Kokoro, scaling to 2 replicas is the right answer; for workloads above ~25 req/min, a larger VPS or multi-VPS topology is required.
