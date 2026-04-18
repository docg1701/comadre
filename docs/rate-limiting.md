# Rate Limiting

Comadre enforces one rate-limit bucket per API key. The per-key cap lives in the registry (`api_key.rate_limit_rpm`) and is consulted on every authenticated request. There is no per-IP rate limit at the application layer and no global toggle — the registry row is authoritative.

## Design rationale

- **Per-key, not per-IP.** Rate-limit is a billing lever, not a firewall. Each customer buys a tier by way of an API key with a specific `rate_limit_rpm`. An IP-based limit would cap all customers sharing an egress NAT, and would not differentiate paid tiers.
- **No reverse-proxy handoff.** Caddy is free to add connection-level protections (concurrency caps, IP blocks, TLS) but the per-key business logic lives in the application where the registry is reachable.
- **In-memory storage.** Bucket state is per-replica in RAM. This removes an external dependency (no Redis, no shared SQLite write contention on the hot path) at the cost of per-replica enforcement semantics — documented below.

## Algorithm

- **Library**: [`limits`](https://limits.readthedocs.io/) — an algorithm-agnostic rate-limit toolkit used directly as a FastAPI dependency (no middleware wrapper).
- **Strategy**: `limits.aio.strategies.MovingWindowRateLimiter` — sliding 1-minute window. Each `.hit()` call adds a timestamped event to the bucket and returns `True` only if the count in the last 60 seconds would remain within `rate_limit_rpm` after the hit.
- **Storage**: `limits.aio.storage.MemoryStorage` — plain in-process dictionaries. No fsync, no network round-trip.
- **Wiring**: constructed once in the lifespan (`RateLimiter.build()`) and stored on `app.state.rate_limiter`. Tests reset buckets between cases via `await app.state.rate_limiter.reset()`.
- **Dependency ordering**: `check_rate_limit` is a FastAPI dependency declared **after** `verify_api_key`. When it runs, `request.state.auth_payload` is guaranteed populated, so the `rate_limit_rpm` and `key_id` values are read from there — no second DB lookup on the hot path.

Pseudo-flow for `POST /v1/audio/speech`:

```text
verify_api_key(request)              → sets request.state.auth_payload
check_rate_limit(request, response)  → limiter.hit(key:<key_id>, rpm)
    allowed?  True  → write X-RateLimit-* headers onto response,
                      handler runs, TTS engine generates audio
    allowed?  False → raise RateLimitError(retry_after, limit, remaining, reset)
route handler (generate_speech)
```

## Bucket identity

Each bucket is keyed on the string `key:<key_id>` where `<key_id>` is the registry row's ULID-based identifier (e.g. `key_01jxy...`).

Consequences of this choice:

- **Rotation preserves the bucket.** `comadre-keys rotate-key` swaps the plaintext and the SHA-256 hash but keeps the same `key_id`. A customer exhausting their budget and then rotating cannot reset the window — the next request lands on the same counter.
- **Buckets are per key, not per customer.** A customer with two active keys (same `customer_id`, different `key_id`) gets two independent buckets. This is intentional: operationally two keys often represent two distinct integrations and should be sized independently.
- **No PII in the bucket key.** `key_id` is an opaque ULID — the bucket key is safe to log at debug level if needed.
- **IP is not part of the bucket.** Two clients sharing a plaintext share the bucket.

## Multi-replica behaviour

`MemoryStorage` is per-process. Today Comadre ships `replicas: 1` in `compose.yaml`, so the in-memory window is the global window. If `replicas` is raised to N:

- Each replica keeps its own moving window for each key.
- A key with `rate_limit_rpm=60` can emit up to `60 × N` requests per minute cluster-wide (in the worst-case distribution where Caddy's `least_conn` policy spreads traffic perfectly).
- The counter on each replica resets when that replica restarts.

This trade-off is honest and visible: the alternative (shared storage) trades a simple deploy for an extra dependency (Redis) or a write-contention-prone shared SQLite table. For Comadre's current throughput and replica count, the in-memory path is the right choice. Moving to shared storage is a candidate future story if and when per-replica multiplication becomes a real operator problem.

If you scale up and need closer-to-strict per-key caps, divide intended RPM by replica count when setting `comadre-keys update-key --rpm <n>`, or accept the multiplied budget as opportunistic elasticity.

## Response headers

Every authenticated response carries the client's current view of its bucket:

| Header | Meaning |
| --- | --- |
| `X-RateLimit-Limit` | The key's `rate_limit_rpm` at request time (integer). |
| `X-RateLimit-Remaining` | Requests still available in the current moving window (integer). |
| `X-RateLimit-Reset` | Unix epoch seconds at which the oldest counted hit falls off the window (integer). |

On a 429 the same three headers are emitted alongside `Retry-After`, so clients can back off accurately without polling. `Retry-After` is computed from the current window state, not a fixed constant — it is `max(1, X-RateLimit-Reset - now)`.

## 429 envelope

When `check_rate_limit` denies the request, Comadre returns:

```text
HTTP/1.1 429 Too Many Requests
Retry-After: 37
X-RateLimit-Limit: 60
X-RateLimit-Remaining: 0
X-RateLimit-Reset: 1745003460
Content-Type: application/json

{
  "error": {
    "message": "Rate limit exceeded",
    "type": "rate_limit_error",
    "hint": "Too many requests. Try again in 37 seconds."
  }
}
```

Notes:

- `Retry-After` and the hint's "Try again in N seconds" are the same integer, derived from `X-RateLimit-Reset - now` (clamped to a minimum of 1). Clients can rely on either channel.
- The TTS engine is not invoked on a 429. The per-replica FIFO queue is not touched.
- The access log middleware still records the request so operators can observe the 429 rate per replica.

## `/health` policy

`GET /health` has no application-layer rate limit. The endpoint is cheap, idempotent, and does not consume model compute. When called without a valid bearer it returns a minimal payload (status + voices); when called with a valid bearer it returns the authenticated detail payload (engines, queue depth, uptime, memory, version).

**Unauthenticated probe protection is the reverse proxy's job.** Caddy is expected to apply a loose IP-based rate limit on `/health` so that unauthenticated spray with shape-valid-random bearers (`cmdr_live_` + 43 valid base64url chars) cannot serialize on the single SQLite connection and starve CLI mutations. The app-layer `verify_api_key` shape check blocks trivially malformed tokens before the DB lookup, but it does not bound request rate — that is an infrastructure concern and lives in `deploy/caddy/Caddyfile`.

## Operator surface

The per-key RPM is set at issuance and mutated through the `comadre-keys` CLI:

| Intent | Command |
| --- | --- |
| Provision a key at a specific tier | `comadre-keys issue-key --customer <cust_id> --rpm <n> --billing-mode manual --price <brl>` |
| Change the cap after issuance | `comadre-keys update-key <key-prefix> --rpm <n>` |
| Retire a key | `comadre-keys revoke-key <key-prefix> --reason "..."` |

`--rpm` is validated at 1..10 000 by the CLI. Every `comadre-keys` mutation touches a sentinel file at `{KEY_REGISTRY_DB_PATH}.invalidate`; the running API stats this sentinel on each cache read and flushes its `AuthCache` the moment mtime advances. A revoked key stops authenticating on the very next request — no 60-second TTL window. `rotate-key` preserves the bucket; `revoke-key` removes the auth path, which makes the bucket irrelevant.

## Bucket persistence

Buckets live only in process memory. On container restart — whether via `docker compose restart tts-service`, the daily restart cron, or a crash — every key's window resets to zero. This is intentional:

- The customer's registry row (`rate_limit_rpm`) is unchanged, so policy is preserved.
- The runtime counter is disposable; losing it on restart costs at most one minute of oversized burst for active keys.
- Restart is the simplest possible cache invalidation for `AuthCache` + rate-limit combined (when you need immediate effect for a `revoke-key`, a restart also nukes any over-limit counters).

At Comadre's throughput this trade is fine. Customers rarely notice window resets, and operators already treat restart as a known-safe operation.

## Future direction

- **Shared storage.** Moving bucket state to Redis or a dedicated SQLite bucket table would make per-key caps cluster-wide-strict at the cost of one more dependency. Candidate for a future story; not shipped today.
- **Observability counters.** A future story adds per-key `requests_total` / `rate_limit_429` / `peak_rpm` counters surfaced via `comadre-keys` for billing and capacity planning.

## See also

- [monetization.md](monetization.md) — how `rate_limit_rpm` fits into customer tiers and billing.
- [configuration-reference.md](configuration-reference.md) — environment variables (no rate-limit env vars by design).
- [deployment-guide.md](deployment-guide.md) — scaling section with per-replica bucket caveat in context.
