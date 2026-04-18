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
