# Monetization (Epic 2)

This document stubs the operator-facing monetization reference. The full
runbook lands in Story 4.6; this file collects in-flight notes as the
feature lands story-by-story.

## Auth cache

Story 2.1 introduces an in-memory TTL cache for authorized `AuthPayload`
values. The cache is keyed by SHA-256 hex digest of the bearer token,
lives per FastAPI replica in `app.state.auth_cache`, and uses a 60-second
TTL with a 4096-entry maximum.

The TTL is the worst-case propagation bound for operator mutations —
`mark-paid`, `suspend`, `reactivate`, and `revoke-key` all become visible
to the API within 60 seconds of the CLI commit. Operators who need faster
propagation restart the replica.

Story 2.3 exposes the cache counters (`hits`, `misses`, `entries`,
`ttl_seconds`) through `comadre-keys cache-status`.

## Rate Limiting

- `POST /v1/audio/speech` rate-limits per API key when
  `MONETIZATION_ENABLED=true`, using each key's `rate_limit_rpm` from the
  registry. When monetization is disabled, the per-IP `RATE_LIMIT_SPEECH`
  default (30/min) applies instead.
- `GET /health` always rate-limits per client IP (`RATE_LIMIT_HEALTH`,
  default 60/min) regardless of mode.
- Rate-limit error envelopes are byte-identical across both modes:
  HTTP 429, `Retry-After: 60`,
  `{"error": {"message": "Rate limit exceeded", "type": "rate_limit_error", "hint": "Too many requests. Try again in 60 seconds."}}`.
- Per-key buckets key on the stable `key_<ulid>` identity, so
  `comadre-keys rotate-key` preserves a customer's bucket state —
  rotation is not a DoS bypass.
- slowapi's default in-memory storage is per-replica; multi-replica
  deployments bound effective throughput by `rpm × replica_count`. A
  `docker compose restart` resets every bucket.
