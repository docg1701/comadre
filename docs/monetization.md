# Monetization

Comadre monetization is policy-driven, per API key, with the encrypted SQLite key registry as the single source of truth. There is no global on/off toggle: every request to `POST /v1/audio/speech` is authenticated against the registry and rate-limited by the specific key's `rate_limit_rpm`. The `comadre-keys` CLI is the sole operator surface for creating customers, issuing keys, adjusting limits, and retiring keys.

## What monetization means

Each `api_key` row carries two business-facing fields:

| Field | Type | Purpose |
| --- | --- | --- |
| `rate_limit_rpm` | integer, 1..10 000 | Requests-per-minute allowed for this key. Drives the per-key bucket at request time. |
| `billing_mode` | `manual` or `complimentary` | `manual`: operator-invoiced monthly at `price_monthly` BRL. `complimentary`: bundled externally, no per-key charge, `price_monthly` is always zero. |

`status` (`active` / `suspended` / `revoked`) and `paid_until` gate authentication itself — a suspended or past-due key returns 401 before it ever hits the rate-limit path.

The registry lives at `KEY_REGISTRY_DB_PATH` (default `/var/lib/comadre/registry.db`) and is encrypted at rest via Fernet using `KEY_REGISTRY_ENCRYPTION_KEY`. Tax IDs are ciphertext columns; key plaintexts are never stored (only SHA-256 hashes and an 8-character display prefix).

## Issuing a key

```bash
comadre-keys create-customer --name "Acme" --email ops@acme.example --tax-id 11144477735
# → prints cust_<ulid>
comadre-keys issue-key \
  --customer cust_<ulid> \
  --rpm 60 \
  --billing-mode manual \
  --price 149
```

The plaintext (a `cmdr_live_<random>` token) is rendered once on stdout and never again. `--rpm` must be in the range `1..10 000` (cap enforced by the CLI). For bundled customers where no per-key invoice applies, use `--billing-mode complimentary` and omit `--price`.

## Per-key rate limiting

`POST /v1/audio/speech` runs two dependencies in order: `verify_api_key` (populates `request.state.auth_payload`), then `check_rate_limit` (enforces the per-key bucket).

- **Algorithm**: sliding-window over 1 minute, `limits.aio.strategies.MovingWindowRateLimiter` with in-memory storage.
- **Bucket identity**: `key:<key_id>` — the registry's ULID-based `key_id`, not the plaintext and not the customer_id. Two keys for the same customer each get their own bucket.
- **Rotation stability**: `comadre-keys rotate-key` swaps the plaintext but preserves `key_id`, so the bucket counter carries over. Rotation is not a rate-limit reset.
- **No per-IP bucket**: the application layer does not rate-limit by IP. Reverse-proxy-level hygiene (connection limits, IP blocks) is Caddy's job.

**Multi-replica caveat.** Storage is per-replica in-memory. If `compose.yaml` runs `replicas: N > 1`, effective RPM for a customer is `N × rate_limit_rpm` (each replica enforces the limit independently). The shipped default is `replicas: 1`, so this is dormant today — raise it deliberately and size customer `rpm` values accordingly. The full trade-off is documented in [rate-limiting.md](rate-limiting.md).

## 429 semantics

When a request would exceed the key's per-minute budget, the application raises `RateLimitError` which serializes to:

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

`Retry-After` and the `Try again in N seconds` hint are derived from `X-RateLimit-Reset - now` — they always match. `X-RateLimit-*` headers are also emitted on allowed responses so clients can observe their remaining budget. The TTS engine is never invoked on a 429 — the rate-limit dependency runs before the route handler body.

## Lifecycle operations

| Intent | Command | Effect |
| --- | --- | --- |
| Raise or lower a customer's throughput | `comadre-keys update-key <prefix> --rpm <new>` | New cap is enforced on the next request — no cache-TTL wait. |
| Change monthly price | `comadre-keys update-key <prefix> --price <brl>` | Manual-mode only. Rejected for complimentary keys. |
| Replace a compromised plaintext | `comadre-keys rotate-key <prefix>` | New plaintext, same `key_id`, same bucket, same billing state. Old plaintext stops working immediately. |
| Retire a key permanently | `comadre-keys revoke-key <prefix> --reason "..."` | Terminal. All subsequent requests with this key return 401. |
| Audit a customer or key | `comadre-keys show <cust_id-or-prefix>` | Detail panel plus the tail of the audit log for that target. |

**Auth cache and synchronous invalidation.** The FastAPI process caches authenticated `AuthPayload` objects (60-second TTL ceiling) keyed by the token hash. Every `comadre-keys` mutation (`update-key`, `revoke-key`, `rotate-key`) touches a sentinel file at `{KEY_REGISTRY_DB_PATH}.invalidate`; the API stats this sentinel on every cache read and flushes immediately when mtime advances. A revoked key stops authenticating on the very next request. The TTL remains a safety net for scenarios where the sentinel cannot be observed (e.g. registry file moved, volume remount).

## What is explicitly out of scope

- **No per-IP fallback.** The application does not rate-limit by source IP. If you need blanket IP hygiene, configure it in Caddy.
- **No single-key environment-variable mode.** Authentication is registry-only. Every bearer token must correspond to an active row in the SQLite registry.
- **No global on/off toggle.** The registry is always authoritative. Issuing a `complimentary` key with a high `rate_limit_rpm` is the way to provision a bypass-style tier.
- **No app-layer `/health` rate limit.** `GET /health` is cheap and idempotent; it returns authenticated-state detail only when a valid bearer is presented.

## See also

- [rate-limiting.md](rate-limiting.md) — algorithm details, bucket semantics, multi-replica behaviour.
- [deployment-guide.md](deployment-guide.md) — bootstrap procedure, encryption-key generation, seeding the first customer.
- [configuration-reference.md](configuration-reference.md) — full environment variable reference.
