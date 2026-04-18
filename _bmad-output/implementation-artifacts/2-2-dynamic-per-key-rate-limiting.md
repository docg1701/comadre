# Story 2.2: Dynamic Per-Key Rate Limiting

Status: done

> **2026-04-18 rewrite.** Original Story 2.2 shipped a slowapi 0.1.9-based per-key bucket with dual-mode fallback (legacy per-IP under `MONETIZATION_ENABLED=false`). Code review surfaced a library-level gotcha — slowapi's limit-provider callable cannot receive the `Request` object — and the operator decided to (a) retire FR27 (legacy single-`API_KEY` mode) and NFR31 (byte-identical 1.6.2 auth), and (b) drop slowapi entirely. This rewrite uses `limits.aio.strategies.MovingWindowRateLimiter` directly behind a FastAPI `Depends(check_rate_limit)`, with per-key-only enforcement. Per-IP rate-limit removed from the application layer (no replacement at the reverse-proxy layer either — per-key caps + well-dimensioned key sales protect the TTS compute surface). See `_bmad-output/planning-artifacts/prd.md` revision note dated 2026-04-18 for the full rationale.

## Story

As an operator,
I want each API key to enforce its own `rate_limit_rpm` at request time — so that customers who pay for higher throughput get it, customers on a smaller tier are bounded predictably, and the VPS's aggregate capacity is distributed by business policy instead of by whoever is loudest.

**Covers FRs:** FR24 (per-key rate limit derived from the specific key's `rate_limit_rpm`).
**NFRs:** NFR7 (rate-limit code paths add ≤2 ms p99 to the post-auth pipeline).
**Not covered (retired 2026-04-18):** ~~FR25~~ (per-IP bound — moved to Caddy), ~~FR27~~ (legacy single-`API_KEY` mode — 2.0.0 is registry-only), ~~NFR31~~ (byte-identical 1.6.2 auth — auth mechanism itself is a documented breaking change).
**Epic:** 2 — API Authentication & Dynamic Rate Limiting. Second story in Epic 2; completes Journey 5's 429-vs-401 debugging affordance (`ux-design-specification.md` §J5) and closes the "customers paying for higher throughput" business mechanic (PRD §Dynamic Rate Limiting).

**Builds on (Epic 1 + Story 2.1):**
- Story 1.2 — `api_key.rate_limit_rpm INTEGER NOT NULL CHECK (rate_limit_rpm > 0)` column from v001 schema; `rpm` carried through `ApiKeyRecord`, `KeyDetailRow`, `IssuedKey`.
- Story 1.6 — `update-key --rpm` capped at `1..10_000` (`_KEY_RPM_MAX = 10_000` in `src/comadre/keys/cli/commands/keys.py`).
- Story 2.1 (as revised 2026-04-18) — `AuthPayload.rate_limit_rpm` + `AuthPayload.key_id` fields written to `request.state.auth_payload` by `verify_api_key` on every successful authentication. This is the datum Story 2.2 reads.
- Story 2.1 (as revised) — `verify_api_key` is registry-only (no dual-mode); `request.state.auth_payload` is always set when a request reaches `/v1/audio/speech`.

**Unblocks:**
- Story 2.3 (Request Counters & Cache Management) — increments per-key counters (`requests_total`, `rate_limit_429`, `peak_rpm`, `avg_rpm`) on the same bucket key Story 2.2 establishes; the bucket is plain `key:<key_id>` (no suffix smuggling).
- Story 3.4 (System Health Command) — `comadre-keys health` reports per-key rate-limit counts when queried.
- Story 4.5e (CI — Rate-Limit Middleware Registration) — the `Depends(check_rate_limit)` wiring + 429-on-over-limit contract Story 2.2 exercises is the regression target.

**Depends on:** Story 2.1 (must be done — gating). New dependency: `limits>=3.13` replaces `slowapi>=0.1.9` in `pyproject.toml`.

## Scope

Swaps the `/v1/audio/speech` rate-limit from a `@slowapi.limiter.limit(...)` decorator to a FastAPI `Depends(check_rate_limit)` backed by `limits.aio.strategies.MovingWindowRateLimiter` with in-memory storage. No per-IP bucket anywhere — per-key is the only rate-limit. Concretely:

1. **`src/comadre/rate_limit.py`** — full rewrite. Exports:
   - `RateLimiter` — dataclass bundling `MemoryStorage` + `MovingWindowRateLimiter`. `RateLimiter.build()` constructs a fresh instance; `await rl.reset()` clears all buckets (used by tests).
   - `check_rate_limit(request)` — async FastAPI dependency. Reads `request.state.auth_payload.rate_limit_rpm` and `request.app.state.rate_limiter`; `.hit()` the `key:<key_id>` bucket; raises `RateLimitError(retry_after=60)` on deny.
   - `get_client_ip(request)` — preserved (access-log middleware consumer only; no rate-limit use).
   - **Removed**: `limiter` (slowapi singleton), `get_rate_limit_key`, `resolve_speech_rate_limit`.
2. **`src/comadre/api.py`** — `/v1/audio/speech` gains `Depends(check_rate_limit)` after `Depends(verify_ready)` and `Depends(verify_api_key)`. The slowapi decorator is removed. Imports cleaned.
3. **`src/comadre/main.py`** — remove `SlowAPIMiddleware`, `app.state.limiter`, `_rate_limit_exceeded_handler`, and the `@limiter.limit(settings.rate_limit_health)` on `/health`. Lifespan builds `app.state.rate_limiter = RateLimiter.build()` after the registry/auth-cache bootstrap. `rate_limit_speech` and `rate_limit_health` `Settings` fields removed.
4. **`src/comadre/config.py`** — `api_key`, `monetization_enabled`, `rate_limit_speech`, `rate_limit_health` fields deleted. `key_registry_encryption_key` promoted to required (no default `None`); `_validate_fernet_key_shape` now runs on guaranteed-present values.
5. **`pyproject.toml`** — `slowapi>=0.1.9` → `limits>=3.13`.
6. **`.env.example`** — `API_KEY`, `MONETIZATION_ENABLED`, `RATE_LIMIT_SPEECH` removed. `KEY_REGISTRY_ENCRYPTION_KEY` promoted to top of the registry section.
7. **Tests**:
   - `tests/test_rate_limit.py` — full rewrite. `TestGetClientIp` (X-Forwarded-For cases), `TestRateLimiterBuild` (smoke), `TestCheckRateLimit` (4 cases: allow-up-to-rpm, trip-on-n+1, independent-buckets-per-key, same-key-two-ips-shares-bucket).
   - `tests/test_api.py::TestPerKeyRateLimit` — rewritten. 6 cases: allow-exactly-rpm, trip-on-n+1, engine-not-invoked-on-429, independent-buckets-same-customer (uses `insert_api_key` helper, not hand-rolled SQL — addresses a code-review finding), independent-buckets-across-customers, same-key-two-ips-shares-bucket, access-log-clean-on-429 (adds the "at least one 429 record exists" guard from the previous review).
   - `tests/conftest.py` — fused `app`/`app_monetized` into one `app` fixture (registry-mode); `auth_headers` seeds a real key; `fernet_key` fixture generates per-test. `_reset_rate_limiter` autouse removed — each test gets a fresh `RateLimiter`.
   - Deleted: `TestMonetizationDisabledRateLimit`, `TestMonetizationDisabledStillSucceeds`, `TestMonetizationOffBootstrap`, `TestMonetizationSettings` (replaced by `TestRegistrySettings`), `test_response_headers_match_legacy_mode`, `test_429_envelope_matches_legacy`, `test_resolve_and_keyfunc_called_once_per_request` (slowapi-specific).
8. **Story 1.6 deferred-work closure** — `issue-key --rpm` cap at `1..10_000` (mirroring `update-key`) shipped in the pre-rewrite Story 2.2 diff; retained in the rewrite. `_KEY_RPM_MAX` reused from `src/comadre/keys/cli/commands/keys.py`.
9. **Docs**:
   - `docs/rate-limiting.md` created — authoritative operator reference for the `limits`-library semantics (moving window, bucket identity, multi-replica caveat, X-RateLimit headers, rotate/revoke stability, `/health` policy).
   - `docs/monetization.md`, `docs/api-reference.md`, `docs/configuration-reference.md`, `docs/deployment-guide.md`, `docs/troubleshooting.md`, `docs/replica-scaling-report.md`, `docs/local-testing-guide.md`, `docs/api-architecture.md`, `docs/proxmox-vm-setup.md` rewritten in the 2026-04-18 sweep to reflect the registry-only auth path and the `limits`-library rate-limit (cross-linked from `rate-limiting.md`).
   - `CLAUDE.md` and `README.md` rewritten to match the 2.0.0 shipped reality.
   - Planning artifacts (`prd.md`, `epics.md`, `architecture.md`) already carry the FR27/NFR31 retirement notes (Phase B).

## Acceptance Criteria

> BDD-style. ACs rewritten 2026-04-18 for registry-only, per-key-only, slowapi-free.

### AC1 — Per-key bucket resolves from `AuthPayload`

**Given** a valid active key exists in the registry with `rate_limit_rpm=60`
**When** `check_rate_limit(request)` runs with `request.state.auth_payload` populated
**Then** the `limits` strategy `.hit()` is called with `parse("60/minute")` and bucket `f"key:{auth_payload.key_id}"`
**And** the function returns `None` (allow) when the bucket has capacity, raises `RateLimitError(retry_after=60)` when capped

### AC2 — Per-key limit allows up to `rate_limit_rpm` requests per minute

**Given** a key with `rate_limit_rpm=2`
**When** the customer sends 2 requests within a rolling 1-minute window
**Then** both return 200

### AC3 — Per-key limit trips on the `rate_limit_rpm + 1`-th request

**Given** a key with `rate_limit_rpm=2`
**When** the customer sends 3 requests within a rolling 1-minute window
**Then** the 3rd returns 429 with `Retry-After: 60` and body `{"error": {"message": "Rate limit exceeded", "type": "rate_limit_error", "hint": "Too many requests. Try again in 60 seconds."}}`

### AC4 — Different keys of different customers have independent buckets

**Given** customer A's key has `rate_limit_rpm=2` and customer B's key has `rate_limit_rpm=5`
**When** customer A exhausts their 2 requests and customer B fires 5 requests
**Then** all 7 requests return 200; customer A's 3rd and customer B's 6th return 429 independently

### AC5 — Two keys for the same customer have independent buckets (keyed by `key_id`)

**Given** the same customer has two keys issued (same `customer_id`, different `key_id`), each with `rate_limit_rpm=2`
**When** the first key exhausts its bucket
**Then** the second key still has full budget — buckets are keyed on `key_id`, not `customer_id`

### AC6 — Same key from two different client IPs shares a single bucket

**Given** a key with `rate_limit_rpm=2`
**When** requests arrive from two different `X-Forwarded-For` IPs
**Then** the bucket is the same `key:<key_id>` — IP-2's first request trips if IP-1 already consumed the 2-request budget

### AC7 — TTS engine not invoked on 429

**Given** a key with `rate_limit_rpm=2`
**When** the customer fires 3 requests
**Then** `router.generate_speech` is called exactly 2 times (FastAPI dependency runs before the handler body)

### AC8 — Access log clean on 429

**Given** a request that receives 429
**When** the access-log middleware emits its line
**Then** the line contains no plaintext token, no SHA-256 hash, no `cmdr_live_`, no customer name, no `key_<ulid>`, and no 64-hex-character run
**And** at least one access-log record corresponds to the 429 response (guards against a middleware regression that silently drops the record)

### AC9 — Rotation survivability

**Given** a key with `rate_limit_rpm=2` is exhausted (bucket at cap)
**When** `comadre-keys rotate-key` is run and the new plaintext is used within the same minute window
**Then** the first request with the new plaintext receives 429 — the bucket key `key:<key_id>` is preserved across rotation (only the plaintext changes, not the `key_id`)
**And** after the minute rolls over, the bucket refills and the new plaintext works

### AC10 — `issue-key --rpm 1..10_000` validation

**Given** `comadre-keys issue-key --rpm <N>`
**When** `N > 10_000` or `N < 1`
**Then** exits 2 with usage-error panel — mirrors `update-key --rpm` cap introduced in Story 1.6

### AC11 — NFR7 budget (≤2 ms p99 added by rate-limit path)

**Given** 100 consecutive requests with a cache-warm auth + rate-limit
**When** measured at p99
**Then** the added per-request overhead of `Depends(check_rate_limit)` is ≤2 ms
**And** no external I/O happens (storage is in-memory)

### AC12 — Slowapi fully removed

**Given** the final diff for Story 2.2
**When** grepped with `rg 'slowapi'` against the whole repo (excluding `_bmad-output/`)
**Then** zero matches — no import, no decorator, no middleware registration, no test fixture, no env var

### AC13 — `limits` library wired via `app.state.rate_limiter`

**Given** a running FastAPI app (lifespan entered)
**When** `app.state.rate_limiter` is inspected
**Then** it is a `comadre.rate_limit.RateLimiter` instance with `.storage` and `.strategy` populated
**And** `await app.state.rate_limiter.reset()` clears all buckets (used by tests)

## Tasks / Subtasks

- [x] **Task 1 — Swap dependency.** `pyproject.toml`: `slowapi>=0.1.9` → `limits>=3.13`. `uv sync` regenerates `uv.lock`. `uv run python -c "from limits.aio.storage import MemoryStorage; from limits.aio.strategies import MovingWindowRateLimiter; from limits import parse"` succeeds.

- [x] **Task 2 — Rewrite `src/comadre/rate_limit.py`.** Module-level exports: `RateLimiter` dataclass, `check_rate_limit(request)` async dependency, `get_client_ip(request)` (preserved). Remove `limiter`, `get_rate_limit_key`, `resolve_speech_rate_limit`.

- [x] **Task 3 — Update `src/comadre/api.py`.** Route gains `Depends(check_rate_limit)` in the dependencies list. Remove `@limiter.limit(...)` decorator. Imports pruned.

- [x] **Task 4 — Update `src/comadre/main.py`.** Remove `SlowAPIMiddleware`, `app.state.limiter`, `_rate_limit_exceeded_handler`, `add_exception_handler(429, ...)`, and the `/health` `@limiter.limit` decorator. Lifespan constructs `app.state.rate_limiter = RateLimiter.build()` after the auth-cache init.

- [x] **Task 5 — Prune `src/comadre/config.py`.** Drop `rate_limit_speech`, `rate_limit_health` fields (also `api_key`, `monetization_enabled` if still present from Phase C). Keep `key_registry_encryption_key` as required.

- [x] **Task 6 — `.env.example`.** `RATE_LIMIT_SPEECH`, `RATE_LIMIT_HEALTH` removed. `KEY_REGISTRY_ENCRYPTION_KEY` promoted to required (no leading comment).

- [x] **Task 7 — Rewrite `tests/test_rate_limit.py`.** `TestGetClientIp`, `TestRateLimiterBuild`, `TestCheckRateLimit`. No slowapi imports.

- [x] **Task 8 — Rewrite `tests/test_api.py::TestPerKeyRateLimit`.** 6 cases as specified above. `insert_api_key` helper used for the same-customer-two-keys test (replaces hand-rolled SQL).

- [x] **Task 9 — Update `tests/conftest.py`.** Single `app` fixture (registry-mode). `auth_headers` seeds a real key. `fernet_key` fixture provides per-test Fernet keys. Remove `_reset_rate_limiter` autouse. Rename `app_monetized`/`client_monetized` references across tests.

- [x] **Task 10 — Sanity gates.** `uv run ruff check .` clean. `uv run mypy src/` clean. `uv run pytest` — 1016/1016 pass.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (1M context).

### Completion Notes

- `limits` was already a transitive dependency of slowapi, so the `uv sync` swap uninstalled only `slowapi==0.1.9`. No new transitive deps.
- `check_rate_limit` is an async FastAPI dependency (not a middleware) so it runs inside FastAPI's dependency resolution, AFTER `verify_api_key` populates `request.state.auth_payload`. No dispatch-on-type, no bucket-key smuggling, no `isinstance` checks.
- The `/health` endpoint no longer has an app-layer rate-limit. No replacement added — the endpoint is cheap and idempotent, and there is no credible abuse scenario against it that per-key limits don't already handle on `/v1/audio/speech`.
- Story 2.3 (request counters) will need to iterate `app.state.rate_limiter.storage` to read bucket hit counts — the `limits` library exposes `.get(...)` on storage for this. Story 2.3 will not need to split any composite bucket key (the bucket is plain `key:<key_id>`).
- Legacy tests that fused legacy-mode comparisons with registry-mode behaviour (`test_response_headers_match_legacy_mode`, `test_429_envelope_matches_legacy`) were deleted outright — they tested a contract that no longer exists.
- The `_reset_rate_limiter` autouse in `conftest.py` is gone; bucket isolation now comes from each `app` fixture building a fresh `RateLimiter` via function scope.
- `tests/test_health.py::test_authenticated_warming_up_returns_full_response` was updated to seed a real registry key — it previously used the legacy `"Bearer test-key"` that no longer authenticates.

### File List

- `src/comadre/rate_limit.py` (rewritten; guards, dynamic Retry-After, X-RateLimit-* headers, rpm>=1 validation)
- `src/comadre/exceptions.py` (`RateLimitError` carries `limit`/`remaining`/`reset`; handler emits X-RateLimit-* headers)
- `src/comadre/api.py` (`@limiter.limit` decorator → `Depends(check_rate_limit)`)
- `src/comadre/main.py` (slowapi purged; `RateLimiter` built in lifespan; `AuthCache` wired to invalidation sentinel; `_try_auth` logs unexpected exceptions)
- `src/comadre/config.py` (rate_limit_speech / rate_limit_health removed; `key_registry_encryption_key` promoted to required)
- `src/comadre/keys/auth.py` (bearer shape-check short-circuit blocks DoS via unknown-token spray; `verify_api_key` moved here)
- `src/comadre/keys/cache.py` (`AuthCache` gains `invalidation_sentinel` param; `get()` flushes when sentinel mtime advances)
- `src/comadre/keys/db.py` (`_touch_auth_cache_sentinel` helper; `update_api_key` / `rotate_api_key` / `revoke_api_key` touch the sentinel on commit)
- `src/comadre/keys/cli/commands/keys.py` (`issue-key --rpm` cap 1..10 000; `_UPDATE_KEY_RPM_RANGE_HINT` trimmed)
- `pyproject.toml` + `uv.lock` (slowapi → limits)
- `.env.example` (rewritten from scratch; `KEY_REGISTRY_ENCRYPTION_KEY` required at top)
- `compose.yaml` (hard-require `KEY_REGISTRY_ENCRYPTION_KEY`; `comadre-registry` named volume; dead env vars removed)
- `deploy/ansible/playbooks/{bootstrap,update,health,deploy-voices}.yml` (legacy `api_key_value` purged; `/health` probes drop Authorization header)
- `deploy/ansible/inventory/{production,oracle}.yml(.example)` (dead vars removed; `key_registry_encryption_key` added)
- `deploy/bin/rotate-api-key.sh` (deleted — replaced by `comadre-keys rotate-key`)
- `CLAUDE.md`, `README.md` (rate-limiting and auth sections rewritten to 2.0.0 reality)
- `docs/rate-limiting.md` (new — algorithm, bucket identity, multi-replica caveat, X-RateLimit headers, operator surface)
- `docs/{monetization,api-reference,configuration-reference,deployment-guide,troubleshooting,replica-scaling-report,local-testing-guide,api-architecture,proxmox-vm-setup}.md` (swept for stale refs; auth + rate-limit sections rewritten)
- `tests/test_rate_limit.py` (rewritten: X-RateLimit headers, dynamic Retry-After, guards, rotation-survivability, concurrent-hit atomicity)
- `tests/test_api.py` (TestPerKeyRateLimit asserts dynamic Retry-After + X-RateLimit-* headers; `test_db_error_returns_500_envelope` uses valid-shape bearer)
- `tests/test_keys_cache.py` (`TestInvalidationSentinel` — sentinel-present, sentinel-appearing, sentinel-advance)
- `tests/test_keys_db.py` (`TestAuthCacheSentinelTouched` — every mutation advances sentinel mtime and leaves 0600 mode)
- `tests/test_keys_cli_issue.py` (hint assertion updated; dead `monkeypatch.setenv("API_KEY", …)` removed)
- `tests/{test_keys_cli_*,test_config,test_main_lifespan,conftest}.py` (dead `monkeypatch.setenv("API_KEY"/"MONETIZATION_ENABLED"/"RATE_LIMIT_HEALTH", …)` calls removed)

## Change Log

- **2026-04-18 (second review pass)** — Second adversarial pass on the full Story 2.2 scope (commit `1d27e12` + uncommitted review-cycle patches). 1 decision-needed resolved (`/health` shape-valid-random DoS → mitigate at Caddy layer; documented); 11 patches applied (math.ceil `Retry-After`, `_try_auth` surfaces `KeyRegistryError`, RFC-6750 case-insensitive Bearer scheme, clamped X-RateLimit-Remaining/Reset, URL-safe-base64 charset regex on the token shape check, AuthCache mtime strict-increase, middleware-based X-RateLimit-* header emission to fix a latent bug where the allow-path headers never reached the client because `/v1/audio/speech` returns its own Response, tightened access-log sanitization regexes, removed dead Settings kwargs in tests, and rewrote Scope §9 to match the shipped docs sweep); 4 deferred (library-level hit/stats atomicity, cross-mount sentinel propagation, mtime-based invalidation collision risk on coarse-mtime filesystems, pydantic ValidationError input-value leak in lifespan logs). Test suite: 1029 pass / 0 fail; `uv run ruff check .` clean; `uv run mypy src/` clean.
- **2026-04-18 (review cycle)** — All code-review findings resolved in one coherent sweep. Rate-limit hardened (dynamic `Retry-After`, X-RateLimit-* headers, state guards, rpm>=1 validation); bearer shape-check short-circuit blocks the `/health` DoS vector; cross-process `AuthCache` invalidation via filesystem sentinel (revoked keys stop authenticating on the next request); all infrastructure orphans (compose, ansible, scripts) rewritten to the 2.0.0 surface; `deploy/bin/rotate-api-key.sh` deleted; every doc under `docs/` / `CLAUDE.md` / `README.md` rewritten to match shipped reality; dead `monkeypatch.setenv("API_KEY", …)` / `"MONETIZATION_ENABLED"` / `"RATE_LIMIT_*"` calls purged from every test file; `docs/rate-limiting.md` created. Final grep across the tree (excluding `_bmad-output/`) for `slowapi` / `MONETIZATION_ENABLED` / `RATE_LIMIT_SPEECH` / `RATE_LIMIT_HEALTH` / `rotate-api-key` / `api_key_value` / `FR27` returns zero matches. Test suite: 1029 pass / 0 fail (previously 1016).
- **2026-04-18** — Initial rewrite. Retired `API_KEY` single-secret mode upstream. slowapi removed. Per-key-only rate-limit via `limits` library.
- **2026-04-17** — Original Story 2.2 dev-story cycle landed (with slowapi workaround). Code review triage surfaced the library constraint; this rewrite supersedes that implementation.

### Review Findings

Triaged from three adversarial layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor) on 2026-04-18 against commit `1d27e12`.

- [x] [Review][Decision] Infra orphans resolved — `compose.yaml` now hard-requires `KEY_REGISTRY_ENCRYPTION_KEY` and exposes a `comadre-registry` named volume mounted at `/var/lib/comadre`; ansible playbooks (`bootstrap`, `update`, `health`, `deploy-voices`) write `KEY_REGISTRY_ENCRYPTION_KEY` and drop the `Authorization: Bearer` header from every `/health` probe; `deploy/bin/rotate-api-key.sh` deleted outright in favour of `comadre-keys rotate-key`.
- [x] [Review][Decision] `/health` SQLite DoS resolved — `verify_api_key` short-circuits on malformed bearer shape (`cmdr_live_` + 43 chars) before touching the DB, so unknown-bearer spray hits a constant-time rejection rather than serialising on `app.state.registry_db`.
- [x] [Review][Decision] Cache invalidation resolved — CLI mutations (`update-key`, `rotate-key`, `revoke-key`) touch `{KEY_REGISTRY_DB_PATH}.invalidate`; `AuthCache.get()` stats the sentinel on every read and flushes the cache when mtime advances. Revoked keys stop authenticating on the very next request; no 60s window.
- [x] [Review][Decision] Per-replica `MemoryStorage` documented explicitly in `docs/rate-limiting.md` (multi-replica behaviour section); current `replicas: 1` stays the default. Shared-storage rate-limiting is tracked as a future story, not shipped here.
- [x] [Review][Decision] `X-RateLimit-Limit` / `X-RateLimit-Remaining` / `X-RateLimit-Reset` headers re-added on both allow and 429 paths via `get_window_stats()`; `Retry-After` is now dynamic and matches `X-RateLimit-Reset - now`.
- [x] [Review][Patch] AC12 cleanup sweep complete — `.env.example` rewritten from scratch, `CLAUDE.md` / `README.md` / every doc under `docs/` / every `tests/test_keys_cli*.py` / `tests/conftest.py` / `tests/test_main_lifespan.py` scrubbed of slowapi / `MONETIZATION_ENABLED` / `API_KEY` / `RATE_LIMIT_SPEECH` / `RATE_LIMIT_HEALTH` references. Final grep across the tree (excluding `_bmad-output/`) returns zero matches.
- [x] [Review][Patch] `check_rate_limit` now guards `request.state.auth_payload` and `request.app.state.rate_limiter` with explicit `getattr` checks that raise diagnosable `KeyRegistryError` instead of opaque 500s [`src/comadre/rate_limit.py`].
- [x] [Review][Patch] `Retry-After` is now dynamic, computed as `max(1, X-RateLimit-Reset - now)`. `RateLimitError` carries `limit` / `remaining` / `reset` / `retry_after`; handler emits all four headers [`src/comadre/rate_limit.py`, `src/comadre/exceptions.py`].
- [x] [Review][Patch] `_UPDATE_KEY_RPM_RANGE_HINT` trimmed to `"Provide --rpm in the range 1..10000."` — no more story reference [`src/comadre/keys/cli/commands/keys.py`].
- [x] [Review][Patch] `check_rate_limit` rejects `rate_limit_rpm < 1` with a diagnosable `KeyRegistryError`; covered by `TestCheckRateLimitGuards::test_rpm_below_one_rejected` [`src/comadre/rate_limit.py`, `tests/test_rate_limit.py`].
- [x] [Review][Patch] Rotation-survivability covered by `TestCheckRateLimit::test_rotation_preserves_bucket` in `tests/test_rate_limit.py`.
- [x] [Review][Patch] Concurrent-hit atomicity covered by `TestCheckRateLimit::test_concurrent_hits_are_atomic` in `tests/test_rate_limit.py` (`asyncio.gather` of N+1 hits on rpm=N bucket).
- [x] [Review][Patch] `docs/rate-limiting.md` created; covers moving-window semantics, per-replica caveat, X-RateLimit headers, rotate/revoke stability, and `/health` policy.
- [x] [Review][Patch] `_try_auth` now distinguishes `ComadreError` (expected auth denials, silent) from any other exception (logged at ERROR with `exc_info=True`) so auth-path regressions surface in the logs [`src/comadre/main.py`].
- [x] [Review][Patch] File List updated below to include `src/comadre/keys/auth.py`, `src/comadre/keys/cache.py`, `src/comadre/keys/cli/commands/keys.py`, `src/comadre/keys/db.py`, `src/comadre/exceptions.py`.
- [x] [Review][Defer] Timing-attack surface: cache hit vs. miss latency is now observable on every request (dual-mode hmac path is gone) — defensive constant-time / timing-equalisation mitigation is a standalone hardening task [`src/comadre/keys/auth.py`].
- [x] [Review][Defer] `api_key.rate_limit_rpm` CHECK has no upper bound (`> 0` only) — CLI caps at 10 000 but a direct SQL edit or malformed backup restore could set `rpm=10^9`, bloating `MemoryStorage`. Schema hardening belongs to a future story [`src/comadre/keys/migrations/v001_initial.sql`].
- [x] [Review][Defer] Denied-key spam (suspended / revoked) never reaches `check_rate_limit`, so the bucket accrues no cost — by design (auth-first). Mitigation belongs with DoS-hardening story.
- [x] [Review][Defer] `MemoryStorage` retains bucket state per unique `key_id` for the lifetime of the process — verify `limits` eviction semantics at scale; practically minor for Comadre key cardinality [`src/comadre/rate_limit.py`].
- [x] [Review][Defer] NFR7 (`≤2 ms p99` budget on the added path) is unverified — add `scripts/bench_rate_limit.py` in a follow-up story.

### Review Findings — Second Pass (2026-04-18)

Second adversarial pass triaged after the post-rewrite cleanup sweep. Same three layers (Blind Hunter, Edge Case Hunter, Acceptance Auditor) against the full Story 2.2 scope (commit `1d27e12` + uncommitted review-cycle patches).

- [x] [Review][Defer] `/health` SQLite DoS only half-resolved — shape-valid-random bearers (`cmdr_live_` + 43 valid chars) still serialize on the single SQLite connection, shape check stops garbage only. Operator decision 2026-04-18: mitigate at the Caddy / reverse-proxy layer (IP-based rate limit on `/health` unauthenticated path) rather than re-adding an app-layer limit. Deferred-work entry tracks the Caddy config; `docs/rate-limiting.md` updated to state `/health` rate limiting is expected at the infra layer. [`src/comadre/main.py:300-303`, `src/comadre/keys/auth.py:79-93`]
- [x] [Review][Patch] `retry_after` now uses `math.ceil` — sub-second remainders round up so a client retrying at `Retry-After` finds the bucket open, not a second 429 [`src/comadre/rate_limit.py`].
- [x] [Review][Patch] `_try_auth` now catches `KeyRegistryError` before the general `ComadreError` branch and logs at ERROR with `exc_info=True`; a DB meltdown no longer silently masks behind `/health 200 minimal` [`src/comadre/main.py`].
- [x] [Review][Patch] Bearer-scheme check is now RFC 6750 case-insensitive (`authorization[:6].lower() != "bearer"`); token bytes still compared verbatim against the registry hash [`src/comadre/keys/auth.py`].
- [x] [Review][Patch] `X-RateLimit-Remaining` clamped to `max(0, remaining)` — `hit`/`get_window_stats` race can no longer emit a negative header [`src/comadre/rate_limit.py`].
- [x] [Review][Patch] Shape check replaced with `_VALID_TOKEN_RE = re.compile(rf"\A{re.escape(API_KEY_PREFIX)}[A-Za-z0-9_-]{{43}}\Z")` — Unicode, whitespace, and any non-URL-safe-base64 char rejected before any cache or DB lookup [`src/comadre/keys/auth.py`].
- [x] [Review][Patch] `X-RateLimit-Reset` clamped to `max(int(reset_time), int(now) + 1)` — the header can no longer expose a past-unix-timestamp under clock skew or stale windows [`src/comadre/rate_limit.py`].
- [x] [Review][Patch] `test_per_key_limit_allows_exactly_rpm_requests` asserts `x-ratelimit-limit` / `-remaining` / `-reset` on both 200 responses. Surfaced a real architectural bug: FastAPI does not merge dependency-injected Response headers when the route returns its own `Response` object (as `/v1/audio/speech` does). Fix: `check_rate_limit` stashes the header triple on `request.state.rate_limit_headers`, and a new `access_log_middleware` merge step writes them onto every outbound response [`src/comadre/rate_limit.py`, `src/comadre/main.py`].
- [x] [Review][Patch] `test_access_log_clean_on_429` tightened — the loose `[0-9a-f]{64}` is anchored to word boundaries and augmented with a `key_`/`cust_` ULID-shape regex `\b(?:key|cust)_[0-9A-HJKMNP-TV-Z]{26}\b`, catching any accidental ULID leak beyond the specific IDs seeded [`tests/test_api.py`].
- [x] [Review][Patch] `tests/test_keys_auth.py` — removed dead `api_key=SecretStr(...)` and `monetization_enabled=True` Settings kwargs. Change Log's "zero matches" claim is now actually true [`tests/test_keys_auth.py`].
- [x] [Review][Patch] Scope §9 rewritten to reflect the documentation sweep that actually shipped: `docs/rate-limiting.md` created; `docs/monetization.md` + 8 other docs rewritten in the 2026-04-18 cleanup; `CLAUDE.md` / `README.md` rewritten to 2.0.0 reality.
- [x] [Review][Patch] `AuthCache._flush_if_invalidated` uses `>` (strictly-increasing) — clock rollback no longer triggers spurious flushes. Same-tick collisions on coarse-mtime filesystems remain a documented defer-item [`src/comadre/keys/cache.py`].
- [x] [Review][Defer] `get_window_stats` is not strictly atomic with `.hit()` — `MemoryStorage.get_moving_window` has no lock. Under concurrent load, headers can drift from the actual consumed state. Impact is header accuracy only; retry semantics remain correct. Library-level mitigation. [`src/comadre/rate_limit.py:108-109`]
- [x] [Review][Defer] Cross-mount sentinel invalidation silently fails — if CLI runs on host and API in container with a non-bind-mount copy, sentinel touches don't propagate. Documented in `docs/troubleshooting.md:211-213` but no runtime guard or startup self-check. [`src/comadre/keys/db.py:163-183`]
- [x] [Review][Defer] Sentinel invalidation via mtime is vulnerable to coarse-mtime filesystems (FAT32 / NFS / some overlay FS) and same-tick collisions on ext4. Move to content-based signaling (write a monotonic counter to the sentinel file) in a hardening pass. [`src/comadre/keys/cache.py:72-79`]
- [x] [Review][Defer] Pydantic `ValidationError` for a malformed `KEY_REGISTRY_ENCRYPTION_KEY` leaks the raw input value in the error repr; if startup crashes, the bad key appears in Docker / systemd logs. Defensive mitigation (truncate repr in the field validator, or catch+re-raise sanitized in lifespan) belongs with a broader secret-handling hardening pass. [`src/comadre/config.py`]
