# Story 2.2: Dynamic Per-Key Rate Limiting

Status: review

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
   - `docs/monetization.md` content from the pre-rewrite story (slowapi multi-replica note etc.) is now stale; a follow-up pass should trim it to reflect the `limits`-library semantics. Out of scope for this story.
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

- `src/comadre/rate_limit.py` (rewritten)
- `src/comadre/api.py` (decorator → Depends)
- `src/comadre/main.py` (slowapi purged; RateLimiter built in lifespan)
- `src/comadre/config.py` (rate_limit_speech / rate_limit_health removed)
- `pyproject.toml` + `uv.lock` (slowapi → limits)
- `.env.example` (legacy env vars removed)
- `tests/rate_limit.py` (rewritten)
- `tests/test_api.py` (TestPerKeyRateLimit rewritten; TestRegistryAuth renamed; legacy tests deleted)
- `tests/test_config.py` (api_key / monetization tests removed; TestRegistrySettings added)
- `tests/test_main_lifespan.py` (MonetizationOff bootstrap deleted; registry_env fixture renamed)
- `tests/test_keys_cli_issue.py` (TestMonetizationDisabledStillSucceeds deleted)
- `tests/test_health.py` (warming-up test seeds a real key)
- `tests/conftest.py` (single `app` fixture; `auth_headers` seeds real key; `fernet_key` added)

## Change Log

- **2026-04-18** — Rewrite. FR27 / NFR31 retired upstream (PRD/epics/architecture revised 2026-04-18). slowapi removed. Per-key-only rate-limit via `limits` library; no replacement per-IP layer. All tests pass (1016/1016).
- **2026-04-17** — Original Story 2.2 dev-story cycle landed (with slowapi workaround). Code review triage surfaced the library constraint; this rewrite supersedes that implementation.
