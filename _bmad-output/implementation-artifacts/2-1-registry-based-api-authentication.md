# Story 2.1: Registry-Based API Authentication

Status: done

<!-- Validation optional. Run validate-create-story for quality check before dev-story. -->

## Story

As a customer (API consumer),
I want the Comadre HTTP API to authenticate my Bearer API key against the per-customer registry with a sub-5 ms cache-hit p99,
so that my `POST /v1/audio/speech` and `GET /health` requests keep the byte-identical 1.6.2 contract while the operator gains per-customer key control, timing-safe comparison, and distinct 401 envelopes for suspended / revoked / unknown keys — and the legacy single-`API_KEY` deployment keeps working untouched when `MONETIZATION_ENABLED=false`.

**Covers FRs:** FR21 (Bearer auth on `/v1/audio/speech`), FR22 (SHA-256-hash validation — never plaintext), FR23 (cached valid auths with 60 s TTL), FR26 (timing-equalized lookup — dummy `hmac.compare_digest` on miss), FR27 (legacy single-`API_KEY` mode preserved when monetization disabled), FR28 (distinct 401 envelope for suspended / revoked with operator-contact hint), FR29 (request/response contract of `/v1/audio/speech` and `/health` byte-identical to 1.6.2).
**NFRs:** NFR1 (cache-hit auth ≤5 ms p99 @ 1 K customers), NFR2 (cache-miss auth ≤15 ms p99 @ 1 K customers), NFR7 (monetization adds ≤2 ms p99 to post-auth pipeline), NFR11 (all key-comparison via `hmac.compare_digest`, never `==`), NFR12 (constant-time miss via dummy comparison), NFR15 (no plaintext / Authorization value in logs), NFR19 (zero external deps at request time — cache + SQLite only), NFR30 (`/v1/audio/speech` and `/health` contracts byte-identical), NFR31 (legacy mode preserves every 1.6.2 behavior exactly).
**Epic:** 2 — API Authentication & Dynamic Rate Limiting. First story in Epic 2; opens Journey 4 (Customer API Integration, PRD L634–L657) and seeds Journey 5 (Debug Session, PRD L440–L478) on the HTTP side.

**Builds on (Epic 1, all done):**
- Story 1.1 — `keys/` subpackage, v001 schema (`customer`, `api_key`, `audit_log`, `schema_version`), `get_connection(path)` with WAL + 0600, `_apply_migrations`, `KeyRegistryError`, `MONETIZATION_ENABLED` / `KEY_REGISTRY_DB_PATH` / `KEY_REGISTRY_ENCRYPTION_KEY` / `OPERATOR_CONTACT_HINT` / `BILLING_DAY` / `BILLING_TIMEZONE` settings.
- Story 1.2 — `hash_api_key(plaintext) -> hex SHA-256` in `comadre.keys.tokens`; `cmdr_live_` + 43-char `secrets.token_urlsafe(32)` format; 8-char stored prefix contract; `ApiKeyRecord` dataclass.
- Story 1.3 — stderr-routed structured logging pattern (`get_logger("component")` + pipe-delimited format) used by `keys.*` modules.
- Story 1.4 — `ApiKeyRecord`, `KeyDetailRow`, lookup-by-hash-style `?`-placeholder SELECTs in `keys/db.py`.
- Story 1.5 / 1.6 — transaction-plus-audit pattern (`with conn:` owned by the helper), audit blocklist, "same-transaction UPDATE-plus-audit" grammar (not used by 2.1's read-only auth path, but governs the adjacent helpers).
- `ManualBillingProvider.is_payment_current(key, *, today)` from `comadre.keys.billing` — validates `paid_until >= today` (manual) / always-true (complimentary) / always-false (manual with `paid_until=NULL`).

**Unblocks:**
- Story 2.2 (Dynamic Per-Key Rate Limiting) — reads `request.state.auth_payload.rate_limit_rpm` set here.
- Story 2.3 (Request Counters & Cache Management) — wraps the same `app.state.auth_cache` instance to surface `entries` / `hit_rate` / `ttl_seconds` via `comadre-keys cache-status`.
- Story 3.1 (Payment Tracking) — `mark-paid` / `suspend` / `reactivate` effects become visible to the API within the 60 s TTL this story establishes.
- Story 4.5a–4.5g (CI Non-Regression Suite) — the 401 envelope and timing-safe contract codified here are the regression target.

**Depends on:** Nothing outside Epic 1. Adds ONE new runtime dependency — `cachetools>=5.3` (pulls in `cachetools`'s own zero-dep wheel; no transitive graph explosion). No schema migration (v001 already defines every table the auth path reads).

## Scope

Adds the registry-based auth path and wires the cache + exception classes + lifespan bootstrap. Concretely:

1. **`AuthPayload` dataclass** added to `src/comadre/keys/models.py`. Frozen, `slots=True`, carries the minimal fields needed by the auth path and (in Story 2.2) the rate-limit resolver: `customer_id: str`, `key_id: str`, `status: CustomerStatus`, `billing_mode: BillingMode`, `rate_limit_rpm: int`, `paid_until: str | None`. **No personal data** — no `name`, no `email`, no `tax_id_encrypted`, no `key_hash`, no `plaintext`. The lone non-obvious field is `key_id` — carried so Story 2.3's per-key counters can key on the stable `key_*` ULID rather than the rotatable 8-char prefix.

2. **`AuthCache` in `src/comadre/keys/cache.py` (new module).** Thin wrapper around `cachetools.TTLCache(maxsize=4096, ttl=60)` keyed by SHA-256 hex digest of the bearer token, value = `AuthPayload`. Surface: `get(key_hash) -> AuthPayload | None`, `set(key_hash, payload) -> None`, `clear() -> None`, `snapshot() -> dict` (Story 2.3 uses `snapshot`; this story populates the field but does not expose a CLI). Thread-safety model matches the single-threaded asyncio event loop (cachetools' own `Lock` is still acquired — defence in depth for future threadpool scenarios). `maxsize=4096` covers NFR25's 2 K active keys with 2× headroom. The module has **no `keys.db` import** — keeps the import graph downward-only: `keys.models` → `keys.cache`.

3. **`verify_api_key_registry` in `src/comadre/keys/auth.py` (new module).** Async function. Takes `request: Request` and a bearer token string. Computes `token_hash = sha256.hexdigest()` once (via the existing `hash_api_key` seam from `keys.tokens`). Checks `request.app.state.auth_cache` first; on hit, goes directly to status+billing validation. On miss, calls a new `lookup_key_auth(conn, key_hash)` helper in `keys.db` (returns `AuthPayload | None`). On DB-found, `cache.set` + validate + set `request.state.auth_payload` + return. On DB-not-found, perform one `hmac.compare_digest(token_hash, _DUMMY_HASH)` call for timing equalisation (FR26) then raise `ApiKeyNotFoundError(401)`. Status/billing branches: `'suspended'` → `ApiKeySuspendedError`, `'revoked'` → `ApiKeyRevokedError`, `'active'` + `ManualBillingProvider.is_payment_current(record, today=...) == False` → `ApiKeySuspendedError` (same customer-visible effect — the suspend-sweep just hasn't run yet), `'active'` + `is_payment_current == True` → allow. The helper NEVER writes to `audit_log` (auth is read-only). On `sqlite3.Error` anywhere in the path, raise `KeyRegistryError(500)` — fail closed.

4. **`lookup_key_auth` helper in `src/comadre/keys/db.py`.** Signature: `lookup_key_auth(conn: sqlite3.Connection, key_hash: str) -> AuthPayload | None`. Single `SELECT id, customer_id, status, billing_mode, rate_limit_rpm, paid_until FROM api_key WHERE key_hash = ? LIMIT 1` with the existing `?`-placeholder grammar. Returns `None` on no row. Materialises the row into `AuthPayload` directly — skips `KeyDetailRow` because the auth path doesn't need the name join or `age_days`. This is the ONE new SQL path in 2.1; every existing query stays untouched.

5. **`ApiKeyNotFoundError`, `ApiKeySuspendedError`, `ApiKeyRevokedError` in `src/comadre/exceptions.py`.** All three extend `ComadreError`, carry `status_code=401`, `error_type="authentication_error"`. `ApiKeyNotFoundError.message = "Invalid or missing API key"`, `hint = "Ensure your Authorization header uses the format 'Bearer <your-api-key>'."` — identical to the current `AuthenticationError` envelope so a cache-miss-lookup-miss is indistinguishable at the HTTP layer from a malformed header (FR26 / enumeration resistance). `ApiKeySuspendedError.message = "Your API key has been suspended"`, `hint = f"Your API key has been suspended. {operator_contact_hint}"`. `ApiKeyRevokedError.message = "Your API key has been revoked"`, `hint = f"Your API key has been revoked. {operator_contact_hint}"`. All three take `operator_contact_hint: str` in `__init__` (plumbed from `settings.operator_contact_hint`); `ApiKeyNotFoundError` takes no args (constant envelope).

6. **Dual-mode branch in `src/comadre/api.py::verify_api_key`.** Gains a branch at the top: when `settings.monetization_enabled is False`, execute the existing 1.6.2 path UNCHANGED (the legacy Bearer-vs-`settings.api_key` `hmac.compare_digest`). When `True`, parse the Authorization header (same "Bearer " prefix check, same `AuthenticationError` on malformed), strip the token, delegate to `verify_api_key_registry(request, token=...)`. The function signature stays `-> None` (side-effects on `request.state.auth_payload`; FastAPI `Depends()` does not consume return values for endpoint injection in the current wiring). `api.py` imports exactly ONE name from `keys/`: `verify_api_key_registry`. No `keys.db`, no `keys.cache`, no `keys.models` imports inside `api.py` (architecture L372 boundary).

7. **Lifespan bootstrap in `src/comadre/main.py`.** When `settings.monetization_enabled` is True, add a new Phase 2a (between "Configuration loaded" and "Model check") that: (a) calls `get_connection(settings.key_registry_db_path)` and stores the connection on `app.state.registry_db`; (b) calls `_apply_migrations(app.state.registry_db)` — idempotent, safe on startup; (c) instantiates `AuthCache(maxsize=4096, ttl=60)` on `app.state.auth_cache`. On shutdown, close the DB connection inside a `try/finally` around the existing `yield`. When `monetization_enabled` is False, the new phase is SKIPPED entirely — no DB opened, no cache allocated; 1.6.2 behaviour preserved end-to-end. The `create_app()` factory is otherwise unchanged — middleware order is unchanged, `SlowAPIMiddleware` stays registered as before, exception handlers register the three new subclasses automatically via the existing `ComadreError` dispatcher in `exceptions.py`.

8. **`cachetools>=5.3` added to `pyproject.toml`.** Pure-Python, stdlib-only transitive deps. Update the lock (`uv lock`) and pin in the runtime image. No change to `uv tool install comadre-keys` — CLI still does not need `cachetools` because CLI doesn't touch the auth cache.

9. **Unit + integration tests:**
   - `tests/test_keys_cache.py` (new) — `AuthCache` get/set, TTL expiration via monkey-patched clock, `snapshot`, `clear`.
   - `tests/test_keys_auth.py` (new) — `verify_api_key_registry` behavioural matrix: cache-hit, cache-miss + DB-found, DB-miss with dummy compare, suspended, revoked, paid_until expired, complimentary, malformed `paid_until` string (Story 1.2 deferred-work closure), DB error → `KeyRegistryError`.
   - `tests/test_keys_db.py` — append `TestLookupKeyAuth` (found / not-found / revoked-row-still-returned / complimentary-with-null-paid-until).
   - `tests/test_api.py` — append `TestMonetizationEnabledAuth` class: `/v1/audio/speech` + `/health` with monetization on, covering the envelope contract preservation + distinct-401 paths. Existing `TestSpeechSuccess` / `TestAuthentication` test classes stay unchanged (default `monetization_enabled=False` keeps legacy path green).
   - `tests/test_exceptions.py` — append three tests, one per new subclass, asserting `status_code` / `error_type` / `hint` shape and envelope rendering via `comadre_error_handler`.

10. **Docs touch (minimal):** one-line mention in `docs/monetization.md` referencing the 60-second auth-cache TTL and the Story 2.3 `cache-status` command that will expose it. Do NOT write the full operator runbook — that lands in Story 4.6.

**Out of scope (future stories, DO NOT add):**

- **Per-key rate limiting (`rate_limit.py` change)** → Story 2.2. Story 2.1 only WRITES `request.state.auth_payload`; Story 2.2 READS it from `key_func`. `rate_limit.py` stays byte-untouched in this story.
- **`comadre-keys cache-status` CLI / Story 2.3 counters** → Story 2.3. Story 2.1 exposes `AuthCache.snapshot()` but does NOT wire a CLI command or per-key counters.
- **`last_used_at` write-back on successful auth** → Deferred. The PRD says `last_used_at` is "updated opportunistically, not on every request" (prd.md L870). A background write-behind pattern is a future-story concern; writing on every request is an NFR1/NFR2 hazard we refuse.
- **Audit-log entry on auth success / failure** → NO. Auth is read-only. An audit row per request would explode the audit_log table (≥30 req/min × 60 × 24 = 43 K rows/day/key). The architecture invariant (L468) says audit writes happen inside the mutation's transaction; auth is not a mutation.
- **Cross-replica cache invalidation / signalling** → Deferred to 2.1+ per architecture L194–L197. The 60-second TTL is the worst-case propagation bound. Operators who need faster propagation restart the replica.
- **Metrics exporter / Prometheus integration** → Out of 2.0.0 scope entirely.
- **Config split (`RegistrySettings` vs `RuntimeSettings`)** → Story 1.2 deferred item. Story 2.1 is NOT the right vehicle — 2.1 needs both the TTS `api_key` field (for legacy mode) and the registry fields (for registry mode). A single `Settings` class still works. Address in a dedicated config-hygiene pass after Epic 2 stabilises.
- **Webhook / PSP adapter endpoints (`/v1/billing/webhook/*`)** → 2.1+ roadmap per PRD L803–L809. `BillingProvider` ABC stays with one concrete implementation (`ManualBillingProvider`).
- **Auth-cache persistence across restarts** → Intentionally in-memory only. NFR19 says zero external deps at request time; adding Redis would break that. A cold restart loses the cache, which is fine — cache-miss path is NFR2-budgeted at 15 ms p99.
- **Changing `key_func` on the `/v1/audio/speech` slowapi decorator** → Story 2.2. Story 2.1's auth path MUST set `request.state.auth_payload` so Story 2.2 has something to read, but the decorator itself keeps `get_client_ip` in 2.1.
- **`ApiKeyNotFoundError` hint divergence from `AuthenticationError`** → No. By design, the two are indistinguishable at the envelope level (FR26 enumeration resistance; PRD L662 "The 401 for invalid keys does NOT reveal whether the key was ever valid"). The two exception classes exist separately only so downstream logging / future telemetry can discriminate server-side — the customer sees one envelope.
- **Renaming `verify_api_key` or its path** → NO. The function name, module, and `Depends()` registration are all unchanged. 1.6.2 callers (any test suite, any external integration test) keep working.

## Acceptance Criteria

> BDD-style. Every AC has a unit or integration test. Source AC text lives in `_bmad-output/planning-artifacts/epics.md:L495-L538` — this block expands each item with the technical detail the dev agent must honour. Error-envelope shapes trace to `_bmad-output/planning-artifacts/prd.md:L900-L921`.

### AC1 — Cache-miss happy path (monetization on, valid active manual key) (FR21, FR22, FR23, FR29)

**Given** `MONETIZATION_ENABLED=true`, `OPERATOR_CONTACT_HINT="Contact Ana on WhatsApp: +55 11 90000-0000"`, a seeded active manual-mode key with `key_hash=H`, `rate_limit_rpm=60`, `billing_mode='manual'`, `paid_until='2099-12-31'`, and an empty `app.state.auth_cache`
**When** a customer sends `POST /v1/audio/speech` with `Authorization: Bearer cmdr_live_<plaintext-hashing-to-H>` and a valid `SpeechRequest` body
**Then**
- `verify_api_key` parses the header, calls `verify_api_key_registry`, which computes `sha256(plaintext).hexdigest()` via `hash_api_key`, confirms `auth_cache.get(H)` is `None`, calls `lookup_key_auth(conn, H)` which issues **exactly one** `SELECT id, customer_id, status, billing_mode, rate_limit_rpm, paid_until FROM api_key WHERE key_hash = ? LIMIT 1` with positional `(H,)`, constructs an `AuthPayload(customer_id=..., key_id=..., status='active', billing_mode='manual', rate_limit_rpm=60, paid_until='2099-12-31')`, stores it via `auth_cache.set(H, payload)`, sets `request.state.auth_payload = payload`, and returns `None` (Depends-style side-effect contract).
- The response is HTTP 200 with `Content-Type: audio/ogg`, `Content-Disposition: attachment; filename="speech.ogg"`, and the audio bytes from `router.generate_speech` — **byte-identical** to the Story 1.2 `test_valid_request_returns_200_with_audio_ogg` fixture response for the same input (FR29 / NFR30).
- **No row is appended to `audit_log`** — the auth path is read-only (architecture L468 transaction-scope invariant; Scope §Out of Scope "audit on auth"). Assert via `SELECT COUNT(*) FROM audit_log` before/after the request: zero delta.
- **No `last_used_at` write** — Scope §Out of Scope says deferred. Assert via `SELECT last_used_at FROM api_key WHERE id = ?`: byte-unchanged from the seed value (`NULL` for a fresh seed).
- The structured access log ("access" logger, pipe-delimited format, existing `main.py` middleware) emits one line: `<client_ip> POST /v1/audio/speech 200 <duration>s`. **Never** the plaintext. **Never** the `Authorization` header value. **Never** the key hash. **Never** the customer name (there is no join to `customer` in `lookup_key_auth`, so the name isn't in scope for the access-log path).
- `app.state.auth_cache.snapshot()["entries"]` is `1` post-request (one hash cached). Cache key is the hex SHA-256 of the token.

### AC2 — Cache-hit path sub-5 ms (NFR1)

**Given** the same key as AC1, and AC1 has already run so `auth_cache.get(H)` now returns a non-None `AuthPayload`
**When** the customer sends a second `POST /v1/audio/speech` within 60 seconds of AC1
**Then**
- `verify_api_key_registry` computes the same `token_hash`, gets the cached `AuthPayload` from `auth_cache`, skips the `lookup_key_auth` call entirely (zero SQL executed — assert via `sqlite3.Connection.set_trace_callback` monkey-patched to a list and checked post-auth), re-validates the status + billing on the cached payload, sets `request.state.auth_payload`, and returns.
- The response is HTTP 200 with the Story 1.2 byte-identical envelope.
- `app.state.auth_cache.snapshot()["entries"]` stays at `1` — the cache did not re-insert. Hit-rate telemetry (`snapshot()["hits"]` — implementation detail of `AuthCache`) increments by 1.
- **Performance budget (NFR1):** on a seeded 1 K-customer / 2 K-key DB, the cache-hit branch of `verify_api_key_registry` completes under **5 ms p99** measured via `time.perf_counter()` around the function call (Task 9.2 measurement, Dev Agent Record records the number). The committed test asserts the cache-hit path performs zero SQL and zero DB connection acquires, not a wall-clock bound (see Scope §deferred AC20-style perf test).

### AC3 — DB lookup miss triggers dummy compare and uniform 401 (FR26, NFR12)

**Given** `MONETIZATION_ENABLED=true`, empty auth cache, no row in `api_key` matches `sha256('unknown-token-xyz').hexdigest()`
**When** a customer sends `POST /v1/audio/speech` with `Authorization: Bearer unknown-token-xyz`
**Then**
- `verify_api_key_registry` computes the hash, misses the cache, calls `lookup_key_auth` which returns `None`, performs **exactly one** `hmac.compare_digest(token_hash, _DUMMY_HASH)` call (asserted via a spy on `hmac.compare_digest` or via pre-computing the dummy constant and checking both arguments), and raises `ApiKeyNotFoundError()`.
- The HTTP response is **401** with the standard envelope:
  ```json
  {"error": {"message": "Invalid or missing API key", "type": "authentication_error", "hint": "Ensure your Authorization header uses the format 'Bearer <your-api-key>'."}}
  ```
  — **byte-identical** to the 1.6.2 `AuthenticationError` envelope (FR26 enumeration resistance; PRD L662).
- `auth_cache.snapshot()["entries"]` stays at `0` — **never cache a miss** (architecture L428: "Cache writes happen only on successful DB lookup").
- The structured access log line is emitted at the same level as a 200 response — **no** additional `ERROR` or `WARNING` line is generated for a bad-key-attempt. Anti-enumeration: an attacker probing random tokens sees the same log shape as a legitimate typo (the existing per-IP slowapi limit still bounds probe rate).

### AC4 — Suspended key returns distinct 401 with operator hint (FR28)

**Given** `MONETIZATION_ENABLED=true`, `OPERATOR_CONTACT_HINT="Contact Ana on WhatsApp: +55 11 90000-0000"`, a seeded key with `key_hash=H`, `status='suspended'`, `billing_mode='manual'`, `paid_until='2026-04-10'` (in the past — belt-and-braces)
**When** a customer sends `POST /v1/audio/speech` with the matching Bearer token
**Then**
- `verify_api_key_registry` resolves the payload (cache-miss + DB hit), reaches the status-validation branch, and raises `ApiKeySuspendedError(operator_contact_hint=settings.operator_contact_hint)`.
- The HTTP response is **401** with:
  ```json
  {"error": {"message": "Your API key has been suspended", "type": "authentication_error", "hint": "Your API key has been suspended. Contact Ana on WhatsApp: +55 11 90000-0000"}}
  ```
- The `AuthPayload` **IS** cached by the hit branch (architecture L428 "cache writes on successful DB lookup" — the lookup succeeded even if the status is suspended). When the operator later runs `mark-paid` via CLI, the status change becomes visible within the 60 s TTL. Assert `auth_cache.snapshot()["entries"] == 1` post-request.
- `app.state.auth_cache` now contains a `status='suspended'` AuthPayload — the next request within 60 s gets the suspended-401 from the cache path without a DB round-trip (validates AC2's generalisation to the suspended hot path).
- No `audit_log` row written.

### AC5 — Revoked key returns distinct 401 (FR28)

**Given** the AC4 seed, but `status='revoked'`
**When** the matching Bearer request arrives
**Then**
- `ApiKeyRevokedError(operator_contact_hint=...)` is raised.
- Response 401 with `message="Your API key has been revoked"`, `hint="Your API key has been revoked. {contact}"`.
- Cache behaviour identical to AC4 (the revoked payload is cached — 60 s worst-case propagation when Story 1.6's `revoke-key` fires later).

### AC6 — Manual-mode key with expired `paid_until` is treated as suspended-equivalent (FR28 bridge)

**Given** `MONETIZATION_ENABLED=true`, a seeded key with `status='active'` (the suspend-sweep cron has NOT yet run), `billing_mode='manual'`, `paid_until='2020-01-01'` (long-expired)
**When** the matching Bearer request arrives
**Then**
- `verify_api_key_registry` resolves the payload, reaches the billing branch, calls `ManualBillingProvider.is_payment_current(record, today=<today-in-billing-tz>)` which returns `False` (since `date.fromisoformat('2020-01-01') < today`), and raises `ApiKeySuspendedError(operator_contact_hint=...)` — **same envelope as AC4**.
- **Rationale:** from the customer's perspective, a manually-paid key that's past `paid_until` is suspended in effect — the cron just hasn't fired yet. Serving the request would undermine the billing contract. The operator-contact hint is the same actionable path. A separate `ApiKeyPaymentOverdueError` subclass was REJECTED on scope-creep grounds (PRD §Error Codes L900–L921 enumerates three 401 subclasses, not four).
- **Time seam:** `today` must be read via a caller-injectable hook to keep tests clock-free. The auth path imports a `_today_in_tz(settings)` helper (new in `keys/auth.py`) that reads `settings.billing_timezone` and returns `date.today()` in that zone via `zoneinfo.ZoneInfo`. The helper's only caller in 2.1 is the auth path; Story 1.x CLI's `_resolve_today_in_tz` lives under `keys/cli/` and is not importable from runtime code. Two parallel seams are fine — the CLI and the runtime path have different import-graph constraints.
- No DB mutation: `api_key.status` stays `'active'` (the cron, not the auth path, is the writer). Assert via direct-SQL snapshot before/after.

### AC7 — Complimentary key always allowed regardless of `paid_until` (FR27 cousin, FR28 carve-out)

**Given** `MONETIZATION_ENABLED=true`, a seeded key with `status='active'`, `billing_mode='complimentary'`, `paid_until=NULL`, `price_monthly=0.0`
**When** the matching Bearer request arrives
**Then**
- `ManualBillingProvider.is_payment_current(record, today=...)` returns `True` unconditionally for `billing_mode='complimentary'` (billing.py L36–L37).
- The request is allowed; response 200 with the Story 1.2 envelope.
- The cached `AuthPayload.billing_mode == 'complimentary'` and `.paid_until is None`. A follow-up cache-hit request within 60 s skips even the billing check's branch (the complimentary branch is the first condition in `is_payment_current`).

### AC8 — Malformed `paid_until` ISO string fails closed (Story 1.2 deferred-work closure)

**Given** `MONETIZATION_ENABLED=true`, a seeded key where `paid_until` is an invalid ISO string (e.g., `'2026-13-45'` or `'not-a-date'` — injected via direct SQL to simulate a schema-invariant violation or a corrupted backup restore)
**When** the matching Bearer request arrives
**Then**
- `is_payment_current` raises `ValueError` on `date.fromisoformat('2026-13-45')`.
- `verify_api_key_registry` catches the `ValueError`, logs one `ERROR`-level line (`"Malformed paid_until in registry for key_id=<id>; failing closed"` — no plaintext, no customer name, no hash) via `get_logger("keys.auth")`, and raises `ApiKeySuspendedError(operator_contact_hint=...)` (fails closed to the suspended envelope — the operator will investigate and either fix via `mark-paid` or delete the bad row).
- Response is 401 with the suspended envelope (same as AC4).
- Closes the Story 1.2 deferred-work item "`paid_until` malformed-ISO crash in `is_payment_current`" from `deferred-work.md`.

### AC9 — DB-level error fails closed with 500 and does NOT cache (FR22, KeyRegistryError contract)

**Given** `MONETIZATION_ENABLED=true`, `app.state.registry_db` has been forcibly closed or the SQLite file has mode `0000` post-startup (simulated via monkey-patch raising `sqlite3.OperationalError` from `conn.execute`)
**When** a cache-miss request arrives
**Then**
- `lookup_key_auth` raises `sqlite3.OperationalError`.
- `verify_api_key_registry` catches `sqlite3.Error` (the superclass), logs one `ERROR`-level line (`"Key registry database unreachable or corrupt"` — no SQL text, no hash), and raises `KeyRegistryError()`.
- Response is **500** with the standard envelope:
  ```json
  {"error": {"message": "Key registry database unreachable or corrupt", "type": "server_error", "hint": "Check KEY_REGISTRY_DB_PATH exists, is readable, and has mode 0600."}}
  ```
- `auth_cache.snapshot()["entries"]` is unchanged — **nothing is cached from a failure path** (architecture L428).
- The request fails closed — the customer gets a 500, NOT a 200. Asserted via an exhaustive matrix: `assert response.status_code == 500` with the monkey-patched DB error.

### AC10 — Missing or malformed Authorization header → legacy-shape 401 (FR29 invariant)

**Given** `MONETIZATION_ENABLED=true` (or `false` — both paths share this branch)
**When** a customer sends `POST /v1/audio/speech` with (a) no `Authorization` header, (b) `Authorization: Basic xyz`, (c) `Authorization: Bearer` (missing token), or (d) `Authorization: BearerXYZ` (no space)
**Then** each of (a)–(d) returns **401** with the byte-identical `AuthenticationError` envelope from 1.6.2 (`message="Missing or malformed Authorization header"`, `hint="Ensure your Authorization header uses the format 'Bearer <your-api-key>'."`). No cache lookup, no DB lookup, no dummy compare — the pre-hash header check fires first in both legacy and registry paths. Regression against existing `tests/test_api.py` auth-edge cases must stay green unchanged.

### AC11 — Legacy mode (`MONETIZATION_ENABLED=false`) is byte-identical to 1.6.2 (FR27, NFR31)

**Given** `MONETIZATION_ENABLED=false` (the default in `Settings`), `settings.api_key.get_secret_value() == 'test-key-12345'` (the existing `tests/conftest.py` fixture)
**When** a customer sends `POST /v1/audio/speech` with `Authorization: Bearer test-key-12345` + a valid body
**Then**
- `verify_api_key`'s first branch fires: `hmac.compare_digest(token, settings.api_key.get_secret_value())` — **exactly the 1.6.2 code path**, byte-for-byte. No SQL executed. No cache lookup. No `auth_cache` instance was ever allocated by the lifespan (Scope §7 — Phase 2a is skipped entirely when `monetization_enabled=False`).
- Response 200 with the existing Story 1.2 envelope.
- `hasattr(app.state, "auth_cache") == False` and `hasattr(app.state, "registry_db") == False`. Assert at startup — the two attributes are GATED by the boolean.
- **Regression gate:** every existing test in `tests/test_api.py`, `tests/test_rate_limit.py`, and `tests/test_health.py` passes WITHOUT MODIFICATION when Story 2.1 lands. No test fixture gets a `monetization_enabled=True` flip (the default is False). Any test that needs the monetization-on path uses a new `app_monetized` fixture in `tests/conftest.py`.
- Legacy wrong-key path: `Bearer wrong-key` → 401 with 1.6.2's `AuthenticationError` envelope (same as `AuthenticationError("Invalid or missing API key")`). No divergence.

### AC12 — `/health` with a valid customer key returns authenticated detail (FR29 invariant)

**Given** `MONETIZATION_ENABLED=true`, a valid active key seeded
**When** the customer sends `GET /health` with the matching Bearer token
**Then**
- `main.py::health_endpoint` calls `_try_auth` which calls `verify_api_key` with the same header. With monetization on, `verify_api_key_registry` resolves + validates + sets `request.state.auth_payload`, no exception raised → `_try_auth` returns `True`.
- The **authenticated** `build_health_response` shape is returned (engines, queue_depth, uptime_seconds, memory_mb, version) — byte-identical to 1.6.2's authenticated /health when monetization is off.

### AC13 — `/health` with an unknown/invalid key returns MINIMAL detail (FR29 invariant)

**Given** `MONETIZATION_ENABLED=true`
**When** `GET /health` is sent with a Bearer token that doesn't match any key hash
**Then**
- `verify_api_key_registry` raises `ApiKeyNotFoundError`. `_try_auth` catches the broad `Exception` (current main.py L281 pattern) and returns `False`.
- The **minimal** health response is returned (status, voices). Status code 200 if ready (1.6.2 behaviour), 503 minimal if warming up. No auth-error envelope is emitted for `/health` — the `_try_auth` swallow is intentional and predates this story (1.6.2 behaviour, preserved).
- Assert: the minimal health response is byte-identical to 1.6.2's "no Authorization header" /health shape. Regression gate, not a new behaviour.

### AC14 — Anti-enumeration: suspended vs not-found are indistinguishable at the per-IP rate-limit layer (FR26)

**Given** `MONETIZATION_ENABLED=true`, the per-IP `RATE_LIMIT_SPEECH` default `30/minute` in effect, two different-length tokens (one suspended, one not-found) hashed distinctly
**When** a probe attacker rotates through 100 random tokens from the same IP within a minute
**Then**
- The per-IP limiter trips at 30 tokens (existing 1.6.2 behaviour). Requests 31–100 return 429 with the standard `Retry-After: 60` envelope — never reach `verify_api_key_registry`.
- Of the ≤30 requests that DO reach the auth path, the not-found branch returns the `ApiKeyNotFoundError` envelope identical to the malformed-header envelope (AC3), and the suspended branch returns the `ApiKeySuspendedError` envelope. **The two envelopes differ** (AC4 vs AC3 — message and hint text diverge), but only for a client who has already proven possession of a real key hash. An attacker probing unknown tokens can never distinguish "not found" from "we ran out of IP budget" except via response code (401 vs 429) — both are deny outcomes. This is the FR26 enumeration-resistance contract as PRD L662 scopes it.
- **What we do NOT promise:** constant-time wall-clock equality between 401-suspended and 401-not-found. The architecture's timing invariant (FR26, NFR12) is specifically about the lookup comparison itself — `hmac.compare_digest` on hit vs `hmac.compare_digest(hash, dummy_hash)` on miss. Post-lookup branches (status validation, hint formatting) are not claimed constant-time and do not need to be (the attacker has already been identified as possessing a real key by the time they reach the status branch).

### AC15 — New exception subclasses render the standard envelope and log sanitation is intact (NFR15)

**Given** `ApiKeyNotFoundError()`, `ApiKeySuspendedError(operator_contact_hint="X")`, `ApiKeyRevokedError(operator_contact_hint="X")` instances
**When** each is raised inside a request handler registered on the Story 1.6.2 `comadre_error_handler`
**Then**
- Response status codes are 401 / 401 / 401.
- Response bodies are structurally identical `{"error": {"message", "type", "hint"}}` JSON.
- `type` is `"authentication_error"` for all three.
- `message` differs: `"Invalid or missing API key"` / `"Your API key has been suspended"` / `"Your API key has been revoked"`.
- `hint` for `ApiKeyNotFoundError` is the legacy `AuthenticationError` hint (verbatim string match — enumeration resistance). `hint` for suspended/revoked includes the `operator_contact_hint` argument verbatim (the `{operator_contact_hint}` interpolation happens ONCE in `__init__`, never at handler time — prevents format-string-injection-style issues if `OPERATOR_CONTACT_HINT` ever carries `{...}`).
- Any `ERROR`/`WARNING` log lines emitted during the raise/render cycle contain NO plaintext (`cmdr_live_…`), NO hash (64-hex run), NO Authorization header value, NO customer name, NO CPF/CNPJ. Assert via an attached throwaway handler on the `keys.auth` / `request` / `startup` loggers collecting records across the test and scanning each message body with regexes for `cmdr_live_`, a 64-hex-char run, and the seeded customer name.

### AC16 — Lifespan bootstrap wires `app.state.registry_db` + `app.state.auth_cache` when monetization is on; skips when off

**Given** a test fixture that constructs `create_app()` with `MONETIZATION_ENABLED=true` + `KEY_REGISTRY_ENCRYPTION_KEY=<Fernet-key>` + `KEY_REGISTRY_DB_PATH=<tmp_path>/registry.db`
**When** the FastAPI lifespan enters
**Then**
- `app.state.registry_db` is a `sqlite3.Connection` with WAL + foreign_keys enabled (asserted via `PRAGMA journal_mode` → `'wal'`, `PRAGMA foreign_keys` → `1`).
- `app.state.auth_cache` is an `AuthCache` instance with `maxsize=4096`, `ttl=60`.
- `_apply_migrations` has been called exactly once (assert via monkey-patch spy, or assert `SELECT MAX(version) FROM schema_version` returns `1`).
- On app shutdown (lifespan exit), `app.state.registry_db.close()` is called once inside `try/finally` — does not swallow exceptions from the `yield` body, but is unconditional.

**Given** a test fixture with `MONETIZATION_ENABLED=false`
**When** the lifespan enters
**Then**
- `hasattr(app.state, "registry_db") == False`.
- `hasattr(app.state, "auth_cache") == False`.
- `_apply_migrations` is never called (monkey-patch spy records 0 invocations).
- The DB file at `settings.key_registry_db_path` is NOT created (asserted on `tmp_path`).

### AC17 — `cachetools>=5.3` is the only new runtime dependency (NFR19, NFR27)

**Given** `pyproject.toml` pre- and post-Story 2.1
**When** the diff is inspected
**Then**
- Exactly one new entry in `[project.dependencies]` or `[project]`'s dependency block: `cachetools>=5.3`. No new optional deps. No bumps to existing pins beyond what `uv lock` computes transitively for `cachetools`.
- `uv.lock` contains `cachetools` with its hash. No new transitive dependencies surface (cachetools 5.x is pure-Python, stdlib-only).
- Sentinel grep `rg '^import cachetools|^from cachetools' src/comadre/` returns **exactly one** match: `src/comadre/keys/cache.py` (the `AuthCache` wrapper). `api.py`, `main.py`, `auth.py` import only the `AuthCache` wrapper — never `cachetools` directly. Enforces the single-abstraction boundary so a future swap (e.g. LRU, ARC) touches one file.

### AC18 — `/v1/audio/speech` response contract is byte-identical to 1.6.2 in both modes (FR29, NFR30)

**Given** both `MONETIZATION_ENABLED=false` (legacy) and `MONETIZATION_ENABLED=true` (registry) modes, each with a valid auth
**When** `POST /v1/audio/speech` returns 200 OK
**Then**
- `Content-Type`, `Content-Disposition`, and response body bytes are identical across the two modes for the same fixture input (same `mock_router.generate_speech` return value).
- **Header delta check:** the set of response headers returned by `/v1/audio/speech` in registry mode is exactly equal to the set returned in legacy mode. No `X-Auth-Payload-Customer-Id`, no `X-Auth-Mode`, no `Cache-Control` drift. Asserted via `assert sorted(registry_response.headers.items()) == sorted(legacy_response.headers.items())` with both modes' setup.
- Error envelopes for `/v1/audio/speech` 4xx / 5xx in legacy mode stay unchanged: `AuthenticationError` → 401, `RateLimitError` → 429 + `Retry-After: 60`, `RequestValidationError` → 400, `GenerationError` → 500, `ServiceUnavailableError` → 503 + `Retry-After: 30`.
- The only envelope additions in registry mode are the three new `ComadreError` subclasses (AC3 / AC4 / AC5 / AC6 — envelopes documented there), all of which share the `{"error": {"message", "type", "hint"}}` shape.

### AC19 — Performance sanity: cache-hit zero SQL, cache-miss one SELECT (NFR1, NFR2)

**Given** a seeded DB with 1 000 customers and 2 000 keys, `MONETIZATION_ENABLED=true`
**When** the dev agent runs `time uv run pytest tests/test_keys_auth.py::TestPerfSanity -q` (one-off; not required CI gate — explicit opt-in marker)
**Then**
- Cache-hit path executes **zero** `conn.execute` calls — asserted via `sqlite3.Connection.set_trace_callback` spy.
- Cache-miss path executes **exactly one** `conn.execute` call — the indexed `SELECT … WHERE key_hash = ?` using `idx_api_key_hash` (existing v001 index).
- Dev Agent Record captures the wall-clock p99 from `pytest-benchmark` or a hand-rolled `time.perf_counter()` loop (≥100 iterations, p99 = 99th percentile). Target: **hit ≤5 ms p99**, **miss ≤15 ms p99** on the dev laptop (well within NFR1 / NFR2's 1 K-customer bound). Committed test asserts the call-count invariants only, not the wall-clock bound (per Story 1.6's AC20 pattern — perf budget tracked in Dev Agent Record, not as a brittle committed assertion).

### AC20 — Quality gates and non-regression greps

**Given** the story implementation is complete
**When** the dev agent runs the full quality pipeline
**Then**
- `uv run ruff check . && uv run ruff format --check .` — zero warnings.
- `uv run mypy src/` — zero errors in strict mode. New modules (`keys/cache.py`, `keys/auth.py`) and `AuthPayload` are strict-compatible (frozen+slots dataclass; explicit field types).
- `uv run pytest` — the full suite passes. Story 1.6 closed at ≈933 tests; Story 2.1 adds roughly 30–50 tests across four files; target final count ≈ 965–985.
- `uv run pre-commit run --all-files` — all hooks pass.
- Sentinel grep `rg 'HTTPException' src/comadre/keys/ src/comadre/api.py src/comadre/main.py src/comadre/exceptions.py` — empty (FR51).
- Sentinel grep `rg '==\s*settings\.api_key' src/comadre/` — empty (NFR11: only `hmac.compare_digest`, never `==`).
- Sentinel grep `rg 'os\.environ' src/comadre/keys/` — empty (pydantic-settings only).
- Sentinel grep `rg 'conn\.execute\(f"' src/comadre/keys/` — the only matches are the pre-existing Story 1.5/1.6 literal-column-name joins for `update_customer` / `update_api_key`. No new f-string SQL in this story.
- Sentinel grep `rg '\bprint\(' src/comadre/keys/cache.py src/comadre/keys/auth.py` — empty (structured logging only).

## Tasks / Subtasks

Ordered for bottom-up construction. Each task ends with a runnable checkpoint. Do not reorder — imports chain downward.

- [x] **Task 1 — Add `cachetools>=5.3` and `AuthPayload` model** (AC: #1, #2, #15, #17)
  - [x] 1.1 `uv add cachetools@'>=5.3,<6'`. Verify `pyproject.toml` + `uv.lock` update. Confirm `uv run python -c "import cachetools; print(cachetools.__version__)"` prints a 5.x version. Do not bump any existing dependency version — only add.
  - [x] 1.2 Append `AuthPayload` to `src/comadre/keys/models.py` (alphabetical-ish slot after `IssuedKey`):
    ```python
    @dataclass(frozen=True, slots=True)
    class AuthPayload:
        """Minimal authorization payload cached per bearer-token hash.

        Populated by the auth path, read by the rate-limit resolver and any
        downstream middleware that needs the per-key context. **No personal
        data** — no name / email / tax_id / plaintext / hash. The ``key_id``
        field carries the stable ``key_*`` ULID so counters and logging can
        reference the key across rotations (the 8-char ``key_prefix`` changes
        on rotate; ``key_id`` does not).
        """

        customer_id: str
        key_id: str
        status: CustomerStatus
        billing_mode: BillingMode
        rate_limit_rpm: int
        paid_until: str | None
    ```
  - [x] 1.3 Append unit tests in `tests/test_keys_models.py`: `TestAuthPayload` with two methods — `is_frozen_and_hashable` (assert immutable, asserts `hash(payload_a) == hash(payload_b)` for equal instances) and `rejects_extra_attributes` (`slots=True` blocks attr assignment). No `notes`, `name`, `email` attributes defined — assert via `hasattr(payload, 'name') == False`.

- [x] **Task 2 — Add `ApiKeyNotFoundError`, `ApiKeySuspendedError`, `ApiKeyRevokedError`** (AC: #3, #4, #5, #15)
  - [x] 2.1 Extend `src/comadre/exceptions.py`. Place the three new classes **after** `AuthenticationError` (L81–L93 in current file) and **before** `RateLimitError` — alphabetical-adjacent and semantically grouped with the other auth 401s.
    ```python
    class ApiKeyNotFoundError(ComadreError):
        """Raised when the bearer token's SHA-256 hash does not match any row.

        Envelope is deliberately identical to ``AuthenticationError`` for
        enumeration-resistance (FR26 / PRD L662). The distinction exists
        only so server-side logging / future telemetry can discriminate.
        """

        def __init__(self) -> None:
            super().__init__(
                message="Invalid or missing API key",
                status_code=401,
                error_type="authentication_error",
                hint=(
                    "Ensure your Authorization header uses the format"
                    " 'Bearer <your-api-key>'."
                ),
            )


    class ApiKeySuspendedError(ComadreError):
        """Raised when the key was found but its status is 'suspended' or its
        manual-mode ``paid_until`` is in the past.

        ``operator_contact_hint`` is plumbed from
        ``settings.operator_contact_hint``; interpolated ONCE here so the
        handler never re-formats attacker-controlled strings.
        """

        def __init__(self, operator_contact_hint: str) -> None:
            super().__init__(
                message="Your API key has been suspended",
                status_code=401,
                error_type="authentication_error",
                hint=f"Your API key has been suspended. {operator_contact_hint}",
            )


    class ApiKeyRevokedError(ComadreError):
        """Raised when the key was found but its status is 'revoked'."""

        def __init__(self, operator_contact_hint: str) -> None:
            super().__init__(
                message="Your API key has been revoked",
                status_code=401,
                error_type="authentication_error",
                hint=f"Your API key has been revoked. {operator_contact_hint}",
            )
    ```
  - [x] 2.2 `register_exception_handlers` requires **no change** — `ComadreError` dispatcher catches all subclasses.
  - [x] 2.3 Append three tests in `tests/test_exceptions.py` (one per class) asserting the `status_code` / `error_type` / `hint` shape + envelope rendering via `comadre_error_handler`. Include a grep-style assertion: `"{operator_contact_hint}"` (the literal placeholder) is NOT in the rendered hint — proves the interpolation fires at construction time, not render time.

- [x] **Task 3 — Add `lookup_key_auth` in `keys/db.py`** (AC: #1, #3, #4, #5, #6, #7, #9, #19)
  - [x] 3.1 Place the helper immediately after `get_key_detail_by_id` (current db.py, search for the function name). Signature:
    ```python
    def lookup_key_auth(
        conn: sqlite3.Connection,
        key_hash: str,
    ) -> AuthPayload | None:
        """Return the minimal auth payload for ``key_hash``, or None on miss.

        Used by ``verify_api_key_registry``. Never writes (auth path is
        read-only). Uses the existing ``idx_api_key_hash`` UNIQUE index —
        the SELECT is O(1).
        """
        cursor = conn.execute(
            "SELECT id, customer_id, status, billing_mode, rate_limit_rpm, "
            "paid_until FROM api_key WHERE key_hash = ? LIMIT 1",
            (key_hash,),
        )
        row = cursor.fetchone()
        if row is None:
            return None
        return AuthPayload(
            customer_id=row["customer_id"],
            key_id=row["id"],
            status=row["status"],
            billing_mode=row["billing_mode"],
            rate_limit_rpm=row["rate_limit_rpm"],
            paid_until=row["paid_until"],
        )
    ```
  - [x] 3.2 Export `lookup_key_auth` from `comadre.keys.db` — no `__all__` maintenance needed (module-level public fns in the existing codebase are imported by name, not via `*`).
  - [x] 3.3 Append `TestLookupKeyAuth` to `tests/test_keys_db.py`:
    - `test_returns_authpayload_for_active_manual_key`.
    - `test_returns_authpayload_for_suspended_key` (helper still returns the row — status validation is the auth layer's responsibility).
    - `test_returns_authpayload_for_revoked_key`.
    - `test_returns_authpayload_for_complimentary_key_with_null_paid_until`.
    - `test_returns_none_for_unknown_hash` (seed 3 keys; call with a distinct hash).
    - `test_exactly_one_sql_statement_executed` — attach a `sqlite3.Connection.set_trace_callback` list; assert `len == 1` and the statement starts with `SELECT`.
    - `test_uses_hash_index` — run `EXPLAIN QUERY PLAN SELECT … WHERE key_hash = ?`; assert the plan mentions `idx_api_key_hash`.

- [x] **Task 4 — Build `AuthCache` in `src/comadre/keys/cache.py`** (AC: #1, #2, #16, #17)
  - [x] 4.1 Create `src/comadre/keys/cache.py`:
    ```python
    """In-memory TTL cache for auth payloads.

    Wraps ``cachetools.TTLCache`` so downstream code depends on this module
    (and this module alone) for cache behaviour. A future swap (LRU, ARC,
    per-replica vs shared) touches this file only.

    The cache stores ``AuthPayload`` keyed by SHA-256 hex digest of the
    bearer token — the same hash used for the DB lookup. **No plaintext,
    no personal data** ever enters the cache.
    """

    from __future__ import annotations

    from typing import Any

    from cachetools import TTLCache

    from comadre.keys.models import AuthPayload

    AUTH_CACHE_DEFAULT_MAXSIZE = 4096
    AUTH_CACHE_DEFAULT_TTL_SECONDS = 60


    class AuthCache:
        """Thread-safe TTL cache for ``AuthPayload`` values.

        ``cachetools.TTLCache`` is not thread-safe on its own — we don't
        need thread-safety for asyncio's single-threaded event loop, but
        future adoption of a threadpool (e.g., syncio database adapters)
        would. Keeping the wrapper class means any lock migration touches
        one module, not every caller.
        """

        def __init__(
            self,
            *,
            maxsize: int = AUTH_CACHE_DEFAULT_MAXSIZE,
            ttl: int = AUTH_CACHE_DEFAULT_TTL_SECONDS,
        ) -> None:
            self._cache: TTLCache[str, AuthPayload] = TTLCache(
                maxsize=maxsize, ttl=ttl
            )
            self._hits = 0
            self._misses = 0
            self.maxsize = maxsize
            self.ttl = ttl

        def get(self, key_hash: str) -> AuthPayload | None:
            payload = self._cache.get(key_hash)
            if payload is None:
                self._misses += 1
            else:
                self._hits += 1
            return payload

        def set(self, key_hash: str, payload: AuthPayload) -> None:
            self._cache[key_hash] = payload

        def clear(self) -> None:
            self._cache.clear()

        def snapshot(self) -> dict[str, Any]:
            """Return a read-only snapshot for telemetry.

            Story 2.3 reads this via ``comadre-keys cache-status --format json``.
            Story 2.1 exposes the fields but does not wire the CLI.
            """
            return {
                "entries": len(self._cache),
                "maxsize": self.maxsize,
                "ttl_seconds": self.ttl,
                "hits": self._hits,
                "misses": self._misses,
            }
    ```
  - [x] 4.2 Add `tests/test_keys_cache.py`:
    - `test_get_returns_none_on_miss_and_increments_miss_counter`.
    - `test_set_then_get_returns_payload_and_increments_hit_counter`.
    - `test_ttl_expiration_purges_entry` — inject a patched `cachetools.TTLCache.timer` (the class exposes `timer` attribute; advance manually) or use `time.monotonic` monkey-patching; assert `get` returns `None` after `ttl + 1` ticks.
    - `test_clear_empties_cache_preserves_counters` — hits/misses counters are per-process telemetry; clearing entries does not reset counters (matches cachetools semantics).
    - `test_snapshot_shape` — returns a dict with `entries`, `maxsize`, `ttl_seconds`, `hits`, `misses` keys. No `keys`, no `values`, no payload-leak risk.
    - `test_single_import_boundary` — `rg 'cachetools' tests/test_keys_cache.py` is allowed, but the test file imports only `AuthCache` from `comadre.keys.cache` (not from `cachetools` directly) — enforces the wrapper-is-the-boundary contract.

- [x] **Task 5 — Build `verify_api_key_registry` in `src/comadre/keys/auth.py`** (AC: #1, #3, #4, #5, #6, #7, #8, #9, #14, #15)
  - [x] 5.1 Create `src/comadre/keys/auth.py`:
    ```python
    """Registry-backed API-key authentication path.

    The sole entry point is ``verify_api_key_registry`` — called by
    ``comadre.api.verify_api_key`` when ``settings.monetization_enabled``
    is True. Sets ``request.state.auth_payload`` on success; raises a
    ``ComadreError`` subclass on any denial outcome.

    The module's only runtime I/O is a single indexed SELECT against the
    key registry on cache-miss. Zero external deps — the timing-equalization
    dummy compare is ``hmac.compare_digest`` from stdlib.
    """

    from __future__ import annotations

    import hmac
    from datetime import date
    from zoneinfo import ZoneInfo

    from fastapi import Request

    from comadre.config import Settings
    from comadre.exceptions import (
        ApiKeyNotFoundError,
        ApiKeyRevokedError,
        ApiKeySuspendedError,
        KeyRegistryError,
    )
    from comadre.keys.billing import ManualBillingProvider
    from comadre.keys.cache import AuthCache
    from comadre.keys.db import lookup_key_auth
    from comadre.keys.models import ApiKeyRecord, AuthPayload
    from comadre.keys.tokens import hash_api_key
    from comadre.logging import get_logger

    _logger = get_logger("keys.auth")

    # Pre-computed dummy hash for timing-equalisation. Constant per process.
    _DUMMY_HASH = hash_api_key("__dummy_for_timing_equalisation__")

    # Shared billing provider instance. MVP has exactly one implementation.
    _billing = ManualBillingProvider()


    def _today_in_billing_tz(settings: Settings) -> date:
        """Return today's date resolved in ``settings.billing_timezone``.

        Extracted as a single-caller seam so tests can monkey-patch
        ``comadre.keys.auth._today_in_billing_tz`` without touching
        ``date.today`` globally. Mirrors the CLI's ``_resolve_today_in_tz``
        pattern (which lives under ``keys/cli/`` and cannot be imported
        here per the architecture's import-boundary rule).
        """
        import datetime as _dt

        return _dt.datetime.now(ZoneInfo(settings.billing_timezone)).date()


    async def verify_api_key_registry(request: Request, token: str) -> None:
        """Registry-mode auth. Sets ``request.state.auth_payload`` on pass.

        Never writes to ``audit_log``. Never updates ``last_used_at``.
        Fails closed on any SQLite error.
        """
        settings: Settings = request.app.state.settings
        cache: AuthCache = request.app.state.auth_cache
        conn = request.app.state.registry_db

        token_hash = hash_api_key(token)
        payload = cache.get(token_hash)

        if payload is None:
            try:
                payload = lookup_key_auth(conn, token_hash)
            except Exception as exc:  # sqlite3.Error and anything else
                _logger.error(
                    "Key registry database unreachable or corrupt",
                    exc_info=exc,
                )
                raise KeyRegistryError() from exc
            if payload is None:
                hmac.compare_digest(token_hash, _DUMMY_HASH)
                raise ApiKeyNotFoundError()
            cache.set(token_hash, payload)

        # Status branch.
        if payload.status == "suspended":
            raise ApiKeySuspendedError(settings.operator_contact_hint)
        if payload.status == "revoked":
            raise ApiKeyRevokedError(settings.operator_contact_hint)

        # Billing branch (active only).
        record = _payload_to_record(payload)
        try:
            paid = _billing.is_payment_current(
                record, today=_today_in_billing_tz(settings)
            )
        except ValueError as exc:
            _logger.error(
                "Malformed paid_until in registry for key_id=%s; failing closed",
                payload.key_id,
                exc_info=exc,
            )
            raise ApiKeySuspendedError(settings.operator_contact_hint) from exc
        if not paid:
            raise ApiKeySuspendedError(settings.operator_contact_hint)

        request.state.auth_payload = payload


    def _payload_to_record(payload: AuthPayload) -> ApiKeyRecord:
        """Adapt ``AuthPayload`` to the ``ApiKeyRecord`` shape that
        ``ManualBillingProvider.is_payment_current`` expects.

        Only the fields the provider reads (``billing_mode``, ``paid_until``)
        are populated. Other fields carry placeholder values — this record
        never persists and never reaches a DB writer.
        """
        from datetime import datetime

        return ApiKeyRecord(
            id=payload.key_id,
            customer_id=payload.customer_id,
            key_hash="",
            key_prefix="",
            rate_limit_rpm=payload.rate_limit_rpm,
            status=payload.status,
            billing_mode=payload.billing_mode,
            price_monthly=0.0,
            paid_until=payload.paid_until,
            created_at=datetime.now(),
            last_used_at=None,
            notes="",
        )
    ```
  - [x] 5.2 Tests in `tests/test_keys_auth.py` (use `FakeCache` for `AuthCache`, `FakeConn` for the SQLite seam, monkey-patch `hash_api_key`, build `Request` via FastAPI `Request` scope helpers or `AsyncClient`). Pattern: one test per AC3–AC9, plus variance coverage:
    - `cache_hit_short_circuits_db_lookup` (AC2).
    - `cache_miss_db_hit_caches_payload_sets_request_state` (AC1).
    - `db_miss_runs_dummy_compare_and_raises_not_found` (AC3) — assert `hmac.compare_digest` called once with `_DUMMY_HASH` (spy).
    - `suspended_status_raises_suspended_error_with_operator_hint` (AC4).
    - `revoked_status_raises_revoked_error_with_operator_hint` (AC5).
    - `manual_expired_paid_until_raises_suspended_error` (AC6) — monkey-patch `_now_in_tz` to return `date(2026, 4, 17)`.
    - `complimentary_always_allowed` (AC7).
    - `malformed_paid_until_raises_suspended_error_fails_closed` (AC8) — seed `paid_until='not-a-date'`; assert `ApiKeySuspendedError` + one ERROR log line.
    - `db_error_raises_key_registry_error` (AC9) — monkey-patch `lookup_key_auth` to raise `sqlite3.OperationalError`.
    - `cache_write_skipped_on_db_miss` (AC3 tail) — after the denial, `cache.snapshot()["entries"]` unchanged.
    - `cache_write_happens_for_suspended_payload` (AC4 tail) — cache receives the suspended payload; subsequent cache-hit still denies.

- [x] **Task 6 — Dual-mode branch in `src/comadre/api.py::verify_api_key`** (AC: #10, #11)
  - [x] 6.1 Modify `verify_api_key`:
    ```python
    from comadre.keys.auth import verify_api_key_registry

    async def verify_api_key(
        request: Request,
        authorization: str = Header(default=""),
    ) -> None:
        """Validate bearer token. Dual-mode: legacy vs registry."""
        settings = request.app.state.settings
        if not authorization.startswith("Bearer "):
            raise AuthenticationError(
                "Missing or malformed Authorization header"
            )
        token = authorization.removeprefix("Bearer ")
        if not settings.monetization_enabled:
            if not hmac.compare_digest(token, settings.api_key.get_secret_value()):
                raise AuthenticationError()
            return
        await verify_api_key_registry(request, token=token)
    ```
  - [x] 6.2 Confirm `api.py` imports in this order (architecture L372 boundary):
    ```python
    from comadre.config import get_settings            # unchanged
    from comadre.exceptions import (
        AuthenticationError, GenerationError, ServiceUnavailableError,
    )                                                  # unchanged
    from comadre.keys.auth import verify_api_key_registry  # NEW
    from comadre.logging import get_logger              # unchanged
    ```
    Nothing from `keys.db`, `keys.cache`, `keys.models` is imported in `api.py`. The single `keys.auth` import is the architectural seam.
  - [x] 6.3 Append tests in `tests/test_api.py`:
    - `TestMonetizationEnabledAuth` class with fixtures `app_monetized` / `client_monetized` / `seeded_active_key` / `seeded_suspended_key` / `seeded_revoked_key`. Uses a tmp SQLite DB, `KEY_REGISTRY_ENCRYPTION_KEY=<Fernet.generate_key().decode()>`.
    - Tests: `test_valid_active_key_returns_200`, `test_suspended_key_returns_401_with_operator_hint`, `test_revoked_key_returns_401_with_operator_hint`, `test_unknown_key_returns_401_legacy_envelope`, `test_malformed_authorization_returns_401_legacy_envelope`, `test_expired_manual_paid_until_returns_401_suspended`, `test_complimentary_null_paid_until_returns_200`, `test_response_headers_match_legacy_mode` (AC18), `test_no_audit_log_row_on_any_auth_outcome` (AC1 tail).
    - The EXISTING `TestSpeechSuccess`, `TestAuthentication`, and other test classes must pass WITHOUT MODIFICATION — they exercise the legacy branch.

- [x] **Task 7 — Lifespan bootstrap in `src/comadre/main.py`** (AC: #11, #16)
  - [x] 7.1 Import `AuthCache` and `get_connection` + `_apply_migrations`:
    ```python
    from comadre.keys.cache import AuthCache
    from comadre.keys.db import _apply_migrations, get_connection
    ```
    Mirror the existing `from comadre.keys.cli.commands ...` import grammar from the CLI — `_apply_migrations` private-name import was accepted in Stories 1.3–1.6 as a pre-existing cross-boundary convention (deferred-work item still open; do not re-raise in this story).
  - [x] 7.2 Insert a new **Phase 2a** between "Phase 2: Configure structured logging" (current main.py L47–L49) and "Phase 2.5: Ensure models are downloaded" (L51):
    ```python
    # Phase 2a: Key-registry bootstrap (monetization-gated)
    if settings.monetization_enabled:
        logger.info("Opening key registry at %s", settings.key_registry_db_path)
        app.state.registry_db = get_connection(settings.key_registry_db_path)
        _apply_migrations(app.state.registry_db)
        app.state.auth_cache = AuthCache(maxsize=4096, ttl=60)
        logger.info("Key registry ready; auth cache initialised (maxsize=4096, ttl=60s)")
    else:
        logger.info("Monetization disabled; skipping key registry bootstrap")
    ```
  - [x] 7.3 Wrap the existing `yield` in a `try/finally` so the DB closes on shutdown:
    ```python
    try:
        yield
    finally:
        logger.info("Shutting down...")
        if settings.monetization_enabled:
            db = getattr(app.state, "registry_db", None)
            if db is not None:
                db.close()
    ```
    The existing `logger.info("Shutting down...")` moves into the `finally`. Preserve indentation; don't create an extra log line.
  - [x] 7.4 Tests in `tests/test_main.py` (new if absent, or append to an existing module test) + `tests/conftest.py`:
    - `test_monetization_off_skips_registry_bootstrap` — lifespan runs, `registry_db` + `auth_cache` absent.
    - `test_monetization_on_opens_registry_and_runs_migrations` — lifespan runs, `registry_db` present, WAL enabled, `schema_version` table has row `version=1`.
    - `test_monetization_on_closes_db_on_shutdown` — register a shutdown spy on `sqlite3.Connection.close`; assert called once.

- [x] **Task 8 — End-to-end regression against `tests/conftest.py`** (AC: #11, #18)
  - [x] 8.1 Do NOT modify the default `app` fixture — it must continue to exercise the legacy path (`MONETIZATION_ENABLED` unset → default `False`). Every existing test in the suite keeps passing unmodified.
  - [x] 8.2 Add a sibling `app_monetized` fixture in `tests/conftest.py`:
    ```python
    @pytest.fixture()
    def app_monetized(
        mock_router: MagicMock,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> Any:
        from cryptography.fernet import Fernet

        db_path = tmp_path / "registry.db"
        monkeypatch.setenv("API_KEY", TEST_API_KEY)
        monkeypatch.setenv("RATE_LIMIT_SPEECH", "9999/minute")
        monkeypatch.setenv("RATE_LIMIT_HEALTH", "9999/minute")
        monkeypatch.setenv("MONETIZATION_ENABLED", "true")
        monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(db_path))
        monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode())
        get_settings.cache_clear()
        application = create_app()
        application.state.router = mock_router
        application.state.ready = True
        application.state.queue_lock = asyncio.Lock()
        application.state.queue_depth = 0
        application.state.start_time = time.monotonic()
        # Run lifespan manually (tests bypass it) — open DB + cache + migrations.
        application.state.registry_db = get_connection(str(db_path))
        _apply_migrations(application.state.registry_db)
        application.state.auth_cache = AuthCache()
        application.state.settings = get_settings()
        return application
    ```
    Same pattern as the legacy `app` fixture but with the extra env vars + the manual lifespan-phase-2a emulation.
  - [x] 8.3 Add seeding helpers in a new `tests/_keys_fixtures.py` module: `seed_active_manual_key(db, *, customer_name, rate_limit_rpm=60, paid_until='2099-12-31') -> tuple[str, str]` returns `(plaintext, key_id)`. Reuses Story 1.1/1.2 helpers from `keys.db` where possible. Called by both `TestMonetizationEnabledAuth` (in `test_api.py`) and `tests/test_keys_auth.py`.

- [x] **Task 9 — Quality gates and performance measurement**
  - [x] 9.1 `uv run ruff check . && uv run ruff format --check .` — zero warnings.
  - [x] 9.2 `uv run mypy src/` — zero errors in strict mode.
  - [x] 9.3 `uv run pytest` — full suite green; target ≈965–985 tests.
  - [x] 9.4 `uv run pre-commit run --all-files` — all hooks pass.
  - [x] 9.5 **Performance sanity** (AC19): write a one-off script `scripts/_perf_auth.py` (NOT committed; delete after the Dev Agent Record captures the numbers). Seed 1 000 customers + 2 000 keys, pre-hash one plaintext, measure `verify_api_key_registry` p99 via `time.perf_counter()` over 1 000 iterations for (a) cache-hit and (b) cache-miss. Target: hit ≤5 ms, miss ≤15 ms. Record the actual values in Dev Agent Record.
  - [x] 9.6 **Sentinel greps** (AC20):
    - `rg 'HTTPException' src/comadre/keys/ src/comadre/api.py src/comadre/main.py src/comadre/exceptions.py` — empty (FR51).
    - `rg '==\s*settings\.api_key' src/comadre/` — empty (NFR11).
    - `rg 'os\.environ' src/comadre/keys/ src/comadre/api.py src/comadre/main.py` — empty.
    - `rg 'conn\.execute\(f"' src/comadre/keys/` — matches limited to pre-existing Story 1.5/1.6 `update_customer` / `update_api_key` literal-column-name joins; no new f-string SQL.
    - `rg '\bprint\(' src/comadre/keys/cache.py src/comadre/keys/auth.py` — empty.
    - `rg '^import cachetools|^from cachetools' src/comadre/` — exactly one match: `src/comadre/keys/cache.py`.
  - [x] 9.7 Do NOT update `sprint-status.yaml` in this branch — the story-creation workflow flips the status, and the dev-story workflow transitions it on completion.

- [x] **Task 10 — Manual verification**
  - [x] 10.1 **Hot-path smoke (legacy mode).** With `MONETIZATION_ENABLED` unset (default False) run `uv run uvicorn comadre.main:create_app --factory --port 8001` in a scratch shell, then `curl -H 'Authorization: Bearer test-key-12345' -X POST http://127.0.0.1:8001/v1/audio/speech -d '{"input":"oi","voice":"kokoro/pm_santa","response_format":"ogg"}' -H 'Content-Type: application/json' -o /tmp/a.ogg`. Confirm 200 + audio output (with a dev kokoro model available) or confirm the 503 "warming up" envelope if no model is loaded — the important thing is the AUTH branch behaves identically to 1.6.2.
  - [x] 10.2 **Hot-path smoke (registry mode).** Set `MONETIZATION_ENABLED=true` and `KEY_REGISTRY_ENCRYPTION_KEY=$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')` in a local `.env`. Seed via CLI: `uv run comadre-keys create-customer --name "Smoke" --email "s@t.com" --cpf "123.456.789-09"` then `uv run comadre-keys issue-key --customer <cust> --rpm 60 --price 149` — capture the plaintext. Restart the uvicorn shell. `curl -H "Authorization: Bearer $PLAINTEXT" -X POST http://127.0.0.1:8001/v1/audio/speech -d '…'` → expect 200 (or the 503 warming envelope). Inspect stderr: no plaintext, no hash, no customer name in the access log. Fire a second curl within 60 s: should also succeed; `comadre-keys cache-status` does NOT land in this story but manual inspection of the auth-cache state via an ad-hoc Python REPL attached to the running process (or via a `logger.debug(app.state.auth_cache.snapshot())` print added transiently) can confirm `entries=1`, `hits=1` after the second request.
  - [x] 10.3 **Suspended / revoked smoke.** `uv run comadre-keys revoke-key <prefix> --reason "smoke test" --yes`. Wait ≥60 s for the cache TTL. Fire the curl again: expect 401 with `"Your API key has been revoked. Contact your Comadre operator for billing."` in the hint. Record the observed envelope byte-for-byte in the Dev Agent Record.
  - [x] 10.4 **Error panels & log piping.** Confirm: (a) `curl -H 'Authorization: Bearer fake'` returns 401 with the `"Invalid or missing API key"` envelope (same as legacy); (b) the access log shows the 401 at INFO level with NO plaintext / hash / customer name; (c) `jq -s '.' < /tmp/comadre.log` parses cleanly (existing structured log contract not broken).

## Dev Notes

### Architecture invariants (from `_bmad-output/planning-artifacts/architecture.md`)

- **Import graph downward-only.** Story 2.1 adds `keys/cache.py` (depends on `keys/models.py` + `cachetools`) and `keys/auth.py` (depends on `keys/cache.py`, `keys/db.py`, `keys/billing.py`, `keys/models.py`, `keys/tokens.py`). The new modules slot into the architecture's prescribed order: `config/logging → exceptions/schemas → keys/models → keys/crypto → keys/db → keys/audit → keys/billing → keys/cache → keys/auth → rate_limit → api/health → main`. [Source: `architecture.md#Technical-Constraints` L59]
- **api.py imports exactly one name from `keys/`.** The `verify_api_key_registry` function. No `keys.db`, no `keys.cache`, no `keys.models` imports in `api.py`. [Source: `architecture.md#Import-Boundary-Rules` L372]
- **CLI must NEVER import from `keys.auth` / `keys.cache`.** The runtime modules are off-limits to the CLI. The CLI still reads `keys.db` + `keys.audit` + `keys.billing` + `keys.crypto` + `keys.models` + `keys.tokens`. [Source: `architecture.md#Import-Boundary-Rules` L367–L368]
- **No raw HTTPException.** Every auth-path denial raises a `ComadreError` subclass. The existing `comadre_error_handler` in `exceptions.py` handles the three new subclasses automatically via isinstance dispatch. [Source: `architecture.md#Enforcement-Guidelines` L471–L488]
- **No `print()`; use `get_logger("keys.auth")` for structured lines.** [Source: `architecture.md` L474]
- **Parameterized SQL only.** The `lookup_key_auth` SELECT uses positional `?` — zero f-strings, zero format strings. [Source: `architecture.md#SQLite-Query-Patterns` L376–L383]
- **Auth cache is per-replica.** Each FastAPI replica has its own `AuthCache` in `app.state.auth_cache`. No cross-replica signal. The 60 s TTL is the worst-case propagation bound (FR45 / architecture L194–L197).
- **Auth payload flow.** `verify_api_key → request.state.auth_payload → (Story 2.2) rate_limit resolver → discarded after response`. Never stored on `app.state`, never written to `audit_log`, never logged. [Source: `architecture.md#Communication-Patterns` L419–L424]
- **Cache on success only.** Architecture L428: "Cache writes happen only on successful DB lookup" — we cache the `AuthPayload` for suspended/revoked keys too (the lookup succeeded; the key just isn't allowed to serve), but NEVER cache a `None` or a `KeyRegistryError`. AC3 + AC9 assert the counter-example.
- **Transaction scope.** Auth is read-only — no transactions, no `with conn:` wrapping. [Source: `architecture.md#Transaction-Scope` L465–L469]
- **Fail closed on DB error.** `sqlite3.Error → KeyRegistryError(500)`. [Source: `architecture.md#Error-Handling-in-Auth-Path` L459–L463]
- **Dual-mode is a boolean gate, not a rolling toggle.** `MONETIZATION_ENABLED=False` → legacy path, full 1.6.2 parity. `True` → registry path. No per-request toggle. No per-key override. [Source: `architecture.md#Authentication-Security` L187–L192; prd.md L841]

### Data contracts

- **`AuthPayload` fields** — `customer_id: str`, `key_id: str`, `status: CustomerStatus` (Literal), `billing_mode: BillingMode` (Literal), `rate_limit_rpm: int`, `paid_until: str | None` (ISO 8601 date string or None for complimentary). Frozen, `slots=True`. No personal data. [Source: `architecture.md#Data-Architecture` L178–L183; `keys/models.py` L17–L19]
- **`api_key` table columns touched** — `id, customer_id, key_hash, status, billing_mode, rate_limit_rpm, paid_until`. Read-only; never written. The existing `idx_api_key_hash` UNIQUE index makes the SELECT O(1). [Source: `prd.md#Data-Schemas` L859–L884]
- **`paid_until` format** — ISO date `YYYY-MM-DD` for manual keys; `NULL` for complimentary. `ManualBillingProvider.is_payment_current` parses via `date.fromisoformat` (raises `ValueError` on malformed; AC8 covers). [Source: `keys/billing.py` L35–L43]
- **Hash format** — lowercase hex SHA-256 of ASCII-encoded plaintext. 64 characters. Always via `hash_api_key(plaintext)` — never `hashlib.sha256(...)` inline. [Source: `keys/tokens.py` L30–L37]
- **Error-envelope shape (all three new subclasses)** — `{"error": {"message": str, "type": "authentication_error", "hint": str}}`. Status 401. [Source: `prd.md#Error-Codes` L900–L921; `exceptions.py#AuthenticationError` L81–L93]

### Config-coupling gotcha (deferred from Story 1.2)

`Settings.api_key: SecretStr = Field(min_length=1)` is still **required** regardless of `MONETIZATION_ENABLED`. A monetization-on-only deploy must still set a non-empty `API_KEY` in `.env` — the legacy path simply never consults it when the gate is off. The Story 1.2 code-review surfaced this as the deferred item "CLI requires TTS-side config fields it doesn't need" and flagged Epic 2 as the natural time to split `Settings`. **Story 2.1 does NOT do the split** — a clean `RegistrySettings` / `RuntimeSettings` schism is cross-cutting (every module that calls `get_settings()` needs to pick one side), and the auth path spans both. Manual verification Task 10.2 includes a throwaway `API_KEY=sentinel-never-used` in the local `.env` to work around this. Flag for Epic 2 retrospective; revisit in a dedicated config-hygiene pass once Story 2.3 closes Epic 2.

### Library version gotchas

- **`cachetools>=5.3`.** 5.x dropped Python 3.7 support, drops the `Cache.missing` deprecated hook, and introduces `TTLCache.timer` as an instance attribute (not a classvar) — we rely on both `maxsize` and `ttl` kwargs that stayed stable across 5.0→5.x. Pin `>=5.3,<6` to insulate against the hypothetical 6.0.
- **`TTLCache` is NOT thread-safe.** The stdlib `asyncio` event loop is single-threaded, so we're safe for the current runtime — but `AuthCache` wraps the mutable state so a future threadpool migration (e.g. syncio DB adapter) touches one module. [Source: cachetools docs]
- **`zoneinfo.ZoneInfo(tz)` in Python 3.12** — requires `tzdata` wheel on Alpine/musl images. The existing `pyproject.toml` already pulls `tzdata` transitively via pydantic. Confirm on `docker build` that the import doesn't blow up. [Source: python 3.12 zoneinfo docs]
- **`hmac.compare_digest`** — accepts `str | bytes`. Both arguments must be the same type. `hash_api_key` returns `str`; `_DUMMY_HASH` is derived from the same function so both are `str`. Never feed raw bytes vs str or the comparison short-circuits.
- **FastAPI `Request.state`** — lives for the request lifecycle. `request.state.auth_payload` is reset per-request; no persistence across the response. [Source: FastAPI/Starlette docs]
- **`cachetools.TTLCache.timer`** — used by the test `test_ttl_expiration_purges_entry`. In cachetools 5.x, `TTLCache.timer` is a class method descriptor binding to `time.monotonic` by default. Monkey-patch via `monkeypatch.setattr(AuthCache, '_cache.timer', lambda: fake_time)` — or construct `TTLCache(maxsize, ttl, timer=lambda: fake_time)` if the wrapper exposes the constructor's `timer=` forward. Prefer the latter to avoid touching private attrs.

### Previous story intelligence

- **Story 1.1 — v001 schema + settings.** All registry columns we SELECT exist at v001; no migration in this story. `MONETIZATION_ENABLED` / `KEY_REGISTRY_*` / `OPERATOR_CONTACT_HINT` / `BILLING_DAY` / `BILLING_TIMEZONE` settings are already wired in `config.py`. The Fernet-key-required-when-monetization-on validator fires at settings load time; if the operator enables monetization without the key, `get_settings()` raises `ValidationError` and the FastAPI lifespan exits cleanly (existing behaviour).
- **Story 1.2 — `hash_api_key` seam + `cmdr_live_` contract.** The auth path hashes inbound tokens via the EXACT SAME function that `issue-key` uses to compute the stored hash. Any mismatch (e.g. encoding drift) would break every key; the seam is a shared test fixture. Also: Story 1.2's deferred-work item "`paid_until` malformed-ISO crash in `is_payment_current`" lands here in AC8 as the auth-path fail-closed contract.
- **Story 1.3 — structured logging to stderr, pipe-delimited.** `get_logger("keys.auth")` emits one ERROR line on DB failure + one ERROR line on malformed `paid_until`. No plaintext / hash / customer name ever lands on either. The stderr routing (established by `keys.cli` logger in 1.3) applies to new runtime loggers as well — the `main.py::setup_logging` call configures both.
- **Story 1.4 — `ApiKeyRecord` dataclass + lookup-by-ID pattern.** `lookup_key_auth` follows the same shape as `get_key_detail_by_id` but without the name JOIN. `_payload_to_record` adapts `AuthPayload` → `ApiKeyRecord` (the shape `ManualBillingProvider` takes). The fabricated record never persists — only billing_mode + paid_until are read.
- **Story 1.5 — transaction-plus-audit grammar.** Not relevant to the auth path (read-only). Listed for completeness so the dev agent knows the convention without needing to look it up.
- **Story 1.6 — `revoke_api_key` / `rotate_api_key` helpers.** Story 2.1's auth path is the mirror: when a customer's key is revoked via 1.6, the revocation propagates to the API within the 60 s TTL. The integration test in Task 10.3 confirms this bound end-to-end.

### Git intelligence

Last 5 commits on master (as of 2026-04-17 after Story 1.6 code-review land):

- `7924586 feat(keys): land story 1.4 — comadre-keys show with DetailPanel, AuditTail, JSON output, and code-review fixes` — adds `ApiKeyRecord`, `KeyDetailRow` — the row shapes `lookup_key_auth` mirrors.
- `a696c68 feat(voices): add pf_influencer_02 voice profile` — unrelated.
- `f4ceb97 feat(keys): land story 1.3 — list-customers + list-keys with StatusTable, filters, JSON, and code-review fixes` — stderr log routing precedent.
- `17dfc4e test(keys): stabilize help-surface assertion against CI terminal width` — unrelated.
- `612d952 feat(keys): land story 1.2 — comadre-keys issue-key with one-shot KeyPanel` — `hash_api_key` / `generate_api_key_plaintext` / `key_prefix_from_plaintext` — the seam we hash inbound tokens through.

Story 1.5 + 1.6 are committed via the current branch HEAD `7924586` but live on files not yet visible to the story-creation workflow's git-log slice — that's OK; the sprint-status.yaml is the authoritative state marker and both 1.5 / 1.6 are marked `done`.

### Deferred-work items addressed or surfaced by Story 2.1

**Closed in this story:**

- **Story 1.2 — `paid_until` malformed-ISO crash in `is_payment_current`.** AC8 + Task 5.1's `try/except ValueError` around `is_payment_current` closes this item. Deferred-work entry to be struck on story close.

**Surfaced (flag for code-review time):**

- **`last_used_at` write-back missing.** Scope §Out of Scope explicitly defers. A future-story concern; no test yet asserts the absence because `last_used_at=NULL` is the only stable value the legacy + registry paths both produce.
- **Cache-clear on explicit revoke / suspend / mark-paid.** The 60 s TTL is the worst-case propagation bound. A cross-replica signal mechanism is deferred to 2.1+ per architecture L194–L197; re-raising it here for clarity.
- **`AuthPayload` / `ApiKeyRecord` duality in `_payload_to_record`.** The adaptor materialises a fake `ApiKeyRecord` to call `ManualBillingProvider`. A cleaner design — adapting the BillingProvider ABC to accept `AuthPayload` or a minimal `BillingContext` — is orthogonal to Story 2.1 scope and should be re-examined at Story 3.3 when the cron sweep touches the same provider. Log as deferred.
- **`_today_in_billing_tz` duplicates the CLI's `_resolve_today_in_tz` helper.** The two helpers live on different sides of the runtime/CLI boundary (architecture import-graph rule) and cannot be unified without a third seam. Log as deferred for a future clock-seam hygiene pass.
- **Auth-path perf regression test (AC19 deferred).** Spec matches Story 1.6's AC20 pattern — measurement in Dev Agent Record, not a committed wall-clock assertion. Revisit when a perf incident warrants a `pytest-benchmark` marker.
- **Per-key telemetry (total requests, 429 count, peak RPM).** Explicitly Story 2.3 scope. Story 2.1 populates `AuthCache.snapshot()['hits']/['misses']` at the cache level; per-key counters on top of that are 2.3.

### UX invariants reproduced from `ux-design-specification.md`

- **UX-DR6 ErrorDisplay (`ux:L820–L833`)** — applies to CLI output; the HTTP path uses the existing `comadre_error_handler` in `exceptions.py`. The three new `ComadreError` subclasses emit the standard JSON envelope, not the CLI red-border panel. AC15 is the canonical assertion.
- **401 envelope shape from `ux:L640–L665` (Journey 4 — Customer API Integration).** "The 401 `hint` for suspended keys names the operator's contact (configurable via `OPERATOR_CONTACT_HINT`)." "The 401 for invalid keys does NOT reveal whether the key was ever valid (enumeration resistance)." Both are codified as AC4 + AC3 respectively.
- **PRD L900–L921 Error Codes table** — the canonical list: 401 unknown, 401 suspended, 401 revoked, all under `authentication_error`. No 403, no 418, no custom type.
- **PRD L930 — "Endpoint limits (unchanged from 1.6.2 at deployment default)"** — Story 2.1 does NOT change the rate-limit key function. The `30/minute` default is per-IP (current 1.6.2 contract); Story 2.2 changes it to per-key. Preserve exactly.

### Scope guards (things NOT to do in Story 2.1)

- **Do NOT modify `src/comadre/rate_limit.py`.** The `key_func=get_client_ip` stays unchanged. Story 2.2 changes the key function; Story 2.1 only WRITES `request.state.auth_payload` so 2.2 has something to read.
- **Do NOT write to `audit_log` from the auth path.** Architecture invariant L468 — audit writes happen inside the mutation's transaction; auth is not a mutation.
- **Do NOT write `last_used_at` on every request.** Deferred. Write-behind is a future-story concern; NFR1 (5 ms cache-hit) budget does not include a DB write.
- **Do NOT cache DB-miss or DB-error outcomes.** Cache writes happen only on successful lookups (architecture L428). AC3 + AC9 assert the counter-examples.
- **Do NOT emit new HTTP headers on `/v1/audio/speech` responses.** FR29 / NFR30 byte-identical contract. AC18 asserts the header set.
- **Do NOT add new routes.** No `/v1/billing/*`, no `/v1/auth/*`, no admin surface. The public API surface stays on `/v1/audio/speech` + `/health` + `/`.
- **Do NOT touch `schemas.py`.** `SpeechRequest` / `HealthResponse` / error envelope are unchanged.
- **Do NOT touch `config.py`.** All registry-related settings are already present (Story 1.1). The existing Fernet-key-required-when-monetization-on validator is already there.
- **Do NOT touch `src/comadre/keys/cli/`.** The CLI is out of scope for 2.1. The runtime auth path is the only surface.
- **Do NOT rename `verify_api_key`.** The dependency function name and its `Depends()` registration stay — every existing test assumes the name.
- **Do NOT emit a `last_auth_payload` or `last_key_id` on `app.state` or anywhere module-level.** Architecture L424: "Never store AuthPayload in a module-level variable or app.state." The payload lives ONLY on `request.state` for the request lifecycle.
- **Do NOT add a `--monetization-check` CLI command or a health probe for cache state.** Story 2.3 wires `comadre-keys cache-status`. Story 2.1 exposes `AuthCache.snapshot()` but does NOT consume it.
- **Do NOT change `main.py::_try_auth` or the `/health` handler shape.** AC12 + AC13 preserve 1.6.2 behaviour; the `_try_auth` swallow of `Exception` is intentional.
- **Do NOT expose `register_exception_handlers` changes.** The `ComadreError` dispatcher already handles every subclass.
- **Do NOT re-implement `hash_api_key`, `get_connection`, `_apply_migrations`, `ManualBillingProvider`, or any `keys.*` helper.** Import and reuse.
- **Do NOT add a `--monetization-check` flag to `comadre-keys`.** Out of scope.

### Enumeration resistance & log sanitisation (FR26, FR37, NFR15, NFR16)

- **The 401 `ApiKeyNotFoundError` envelope is byte-identical to the 401 `AuthenticationError` envelope from 1.6.2.** An attacker probing random tokens cannot distinguish "no such key" from "malformed header" from the response body. AC3 / AC10 / AC15 are the canonical assertions. The two exception CLASSES differ only so server-side telemetry can discriminate — never the envelope.
- **The dummy `hmac.compare_digest` runs on every DB-miss.** FR26 / NFR12. The constant `_DUMMY_HASH` is pre-computed at module import time so the compare call's wall-clock cost matches the successful-compare case on cache-hit. AC3 spy asserts one invocation.
- **Structured logs never carry plaintext, hash, Authorization header, customer name, or decrypted CPF/CNPJ.** The auth-path logger emits two ERROR lines (DB failure; malformed paid_until) — both parameterise on `key_id` only. AC15's log-handler probe catches any regression.
- **Access log shape is unchanged from 1.6.2.** `<client_ip> POST /v1/audio/speech 200 <duration>s`. No per-request payload. No customer identifier. [Source: `main.py::access_log_middleware` L252–L266]
- **The cache NEVER stores plaintext, personal data, or hashes as values.** Values are `AuthPayload` only. Keys are hex SHA-256 (the same hash used for DB lookup). A memory dump of the running process contains AuthPayloads keyed by hex strings — no plaintext recovery possible.
- **`OPERATOR_CONTACT_HINT` is interpolated ONCE at exception `__init__`.** Prevents format-string-style issues if the operator ever sets `OPERATOR_CONTACT_HINT="Contact {admin}!"` — the `{admin}` stays literal, never format-expanded. AC15 asserts by grepping the rendered hint for `{`.

### Project Structure Notes

- **New files (4):**
  - `src/comadre/keys/cache.py` — Task 4.
  - `src/comadre/keys/auth.py` — Task 5.
  - `tests/test_keys_cache.py` — Task 4.
  - `tests/test_keys_auth.py` — Task 5.
- **Modified existing files (5):**
  - `src/comadre/keys/models.py` — +`AuthPayload` dataclass (~15 lines).
  - `src/comadre/keys/db.py` — +`lookup_key_auth` (~20 lines).
  - `src/comadre/exceptions.py` — +3 subclasses (~60 lines).
  - `src/comadre/api.py` — dual-mode branch + 1 import (~8 lines change).
  - `src/comadre/main.py` — lifespan Phase 2a + shutdown close (~15 lines).
  - `pyproject.toml` + `uv.lock` — `cachetools>=5.3` dependency.
  - `tests/conftest.py` — +`app_monetized` fixture (~20 lines).
  - `tests/test_api.py` — +`TestMonetizationEnabledAuth` (~150 lines).
  - `tests/test_keys_db.py` — +`TestLookupKeyAuth` (~80 lines).
  - `tests/test_exceptions.py` — +3 tests (~30 lines).
  - `tests/test_keys_models.py` — +`TestAuthPayload` (~15 lines).
  - `tests/_keys_fixtures.py` (new, small helper module; alternatively extend `conftest.py`).
- **No changes to runtime files** `src/comadre/rate_limit.py`, `src/comadre/schemas.py`, `src/comadre/config.py`, `src/comadre/health.py`, `src/comadre/service.py`, `src/comadre/preprocessing.py`, `src/comadre/download.py`, any file under `src/comadre/keys/cli/`, or any `*.sql` migration.
- Placements per architecture.md §Module Organization (L327–L350). No deviations.

### Testing Standards

- All tests mocked by default; no real models, no `@pytest.mark.slow`.
- `AsyncClient` from `httpx.ASGITransport` — same as Story 1.x + 1.6.2 for HTTP-level tests.
- `tmp_path` for registry DB files. Fernet key via `Fernet.generate_key().decode()` in each fixture.
- Reuse Story 1.1's `_clear_settings_cache` autouse from `tests/conftest.py`. The new `app_monetized` fixture also clears the cache before constructing the app.
- `AuthCache` tests use the `cachetools.TTLCache(timer=...)` constructor seam for clock injection — NEVER monkey-patch `time.monotonic` globally (would leak into asyncio event loop).
- Audit-log assertions are `SELECT COUNT(*)` deltas (zero) — AC1 invariant.
- Performance assertions (AC19) check call-counts via `conn.set_trace_callback` spies, not wall-clock. Wall-clock lives in the Dev Agent Record only.
- Log-leakage assertions attach a throwaway `logging.Handler` to the relevant logger, drain records after the test, and regex-scan each record body.
- Target coverage: 90%+ on new code. The auth module is the most-tested path in the repo post-2.1 land.

## References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-2.1-Registry-Based-API-Authentication` (L495–L538)] — AC source text.
- [Source: `_bmad-output/planning-artifacts/prd.md#Authentication-Model` (L811–L838)] — auth-path flow diagram; 60 s TTL bound.
- [Source: `_bmad-output/planning-artifacts/prd.md#Backward-Compatible-Migration-Mode` (L839–L841)] — `MONETIZATION_ENABLED` gate semantics.
- [Source: `_bmad-output/planning-artifacts/prd.md#Data-Schemas` (L843–L888)] — `api_key` columns read by `lookup_key_auth`.
- [Source: `_bmad-output/planning-artifacts/prd.md#Error-Codes` (L900–L921)] — 401 envelope contract for the three new subclasses.
- [Source: `_bmad-output/planning-artifacts/prd.md#Rate-Limits` (L923–L938)] — per-IP fallback when monetization disabled.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Data-Architecture` (L154–L183)] — `AuthPayload` fields; `TTLCache(maxsize=4096, ttl=60)`.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Authentication-Security` (L185–L205)] — dual-mode branch; key-comparison flow.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Import-Boundary-Rules` (L366–L372)] — import graph enforcement.
- [Source: `_bmad-output/planning-artifacts/architecture.md#SQLite-Query-Patterns` (L376–L383)] — `?`-placeholder grammar.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Enforcement-Guidelines` (L471–L488)] — no `HTTPException`, no `==` on keys, grep sentinels.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Communication-Patterns` (L417–L432)] — auth payload flow + cache-on-success rule.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Process-Patterns` (L452–L469)] — auth-path error handling; read-only transaction scope.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Journey-4-Customer-API-Integration` (L634–L665)] — 401 hint shape; enumeration resistance principle.
- [Source: `src/comadre/api.py` (L40–L50)] — current `verify_api_key` body; the dual-mode branch's dispatch point.
- [Source: `src/comadre/main.py` (L32–L170)] — lifespan entry/exit; Phase 2a insertion point.
- [Source: `src/comadre/exceptions.py` (L81–L93)] — `AuthenticationError` — envelope template for `ApiKeyNotFoundError`.
- [Source: `src/comadre/exceptions.py` (L127–L138)] — existing `KeyRegistryError` — the fail-closed envelope.
- [Source: `src/comadre/keys/billing.py` (L32–L43)] — `ManualBillingProvider.is_payment_current` — `paid_until` parsing semantics (AC8).
- [Source: `src/comadre/keys/tokens.py` (L30–L37)] — `hash_api_key` seam.
- [Source: `src/comadre/keys/db.py` (L162–L195)] — `get_connection` (WAL + 0600); `_apply_migrations` (L198–L231).
- [Source: `src/comadre/keys/models.py` (L65–L80)] — `ApiKeyRecord` — shape `lookup_key_auth` mirrors.
- [Source: `src/comadre/config.py` (L123–L204)] — monetization settings block; Fernet-key-required validator.
- [Source: `src/comadre/rate_limit.py` (L1–L27)] — `get_client_ip` + `limiter` — unchanged by 2.1; context for Story 2.2.
- [Source: `_bmad-output/implementation-artifacts/1-6-key-lifecycle-update-rotate-revoke.md`] — story-spec grammar + Dev Agent Record pattern followed here.
- [Source: `_bmad-output/implementation-artifacts/1-2-api-key-issuance.md`] — `IssuedKey` + `hash_api_key` seam precedents.
- [Source: `_bmad-output/implementation-artifacts/deferred-work.md#Deferred-from-code-review-of-story-1-2-2026-04-17`] — `paid_until` malformed-ISO item closed by AC8.
- [Source: `CLAUDE.md`] — project language policy, Docker v2, `uv` only, no raw `HTTPException`, no `print()`.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (1M context)

### Debug Log References

- Cross-fixture env leakage: `app_monetized`'s `monkeypatch.setenv("MONETIZATION_ENABLED", "true")` bleeds into the legacy `mock_settings` fixture when both appear in the same test (pydantic-settings re-reads env at instantiation). Resolved in `test_response_headers_match_legacy_mode` by building a dedicated legacy app in-place with `Settings(..., monetization_enabled=False)` instead of pulling the `client` fixture.
- `caplog` cannot capture `keys.auth` records because `get_logger()` sets `logger.propagate = False`. Added a local `_CapturingHandler` + `auth_log_handler` fixture on the `keys.auth` logger directly for every test that needs log-line assertions.
- `sqlite3.Connection.close` is a slot method on an immutable type — can't monkey-patch. Spy for the close-on-shutdown test instead wraps `get_connection` and asserts post-lifespan that the returned connection raises `sqlite3.ProgrammingError` on `execute`.
- `cachetools` has no mypy stubs. Added a `cachetools.*` entry to `tool.mypy.overrides` with `ignore_missing_imports = true`, and `cast("AuthPayload | None", self._cache.get(...))` in the wrapper's `get` to preserve the narrow return type.

### Completion Notes List

- Added `AuthPayload` dataclass (frozen, slots, no personal data) to `keys/models.py` and the read-only `lookup_key_auth` helper in `keys/db.py` — a single indexed SELECT against `idx_api_key_hash`.
- New `keys/cache.py` `AuthCache` wraps `cachetools.TTLCache(maxsize=4096, ttl=60)` and tracks `hits`/`misses` counters for Story 2.3's telemetry surface. `cachetools` is imported from exactly one file in the runtime tree.
- New `keys/auth.py::verify_api_key_registry` is the single entry point called by `api.py::verify_api_key` when `monetization_enabled` is True. Cache-hit short-circuits SQL; cache-miss runs one `SELECT` then either denies via `ApiKeyNotFoundError` (with a timing-equalising `hmac.compare_digest(token_hash, _DUMMY_HASH)` call) or caches the payload. Status+billing branches raise `ApiKeySuspendedError` / `ApiKeyRevokedError` with the operator contact hint; malformed `paid_until` and `sqlite3.Error` fail closed.
- `api.py::verify_api_key` keeps the 1.6.2 code path byte-identical when `monetization_enabled=False`; registry path delegates to the new helper and leaves `rate_limit.py` untouched (Story 2.2 concern).
- `main.py` lifespan grew a Phase 2a that opens `registry_db`, runs `_apply_migrations`, and instantiates `auth_cache` only when monetization is on. Shutdown closes the DB inside a `try/finally`. Legacy mode skips every new attribute — `hasattr(app.state, "auth_cache") == False`.
- `tests/conftest.py` gained an `app_monetized` fixture (mirrors the legacy `app` but seeds the registry + cache) plus `client_monetized` + `registry_db` shortcuts. Seeding helper in `tests/_keys_fixtures.py` is shared by `test_api.py` and `test_keys_auth.py`.
- Total test delta: +50 tests across `test_keys_models.py`, `test_exceptions.py`, `test_keys_db.py`, `test_keys_cache.py`, `test_keys_auth.py`, `test_api.py`, and a new `test_main_lifespan.py`. Full suite: 1004 passed (was 954).
- Perf sanity (AC19) on a 1000-customer / 2000-key seeded DB (dev laptop, n=1000 iterations): cache-hit p50=0.010ms / p95=0.016ms / p99=0.022ms; cache-miss p50=0.035ms / p95=0.054ms / p99=0.073ms. Both ~200× under the NFR1 (5ms) / NFR2 (15ms) budgets.
- Closes deferred-work item "Story 1.2 — `paid_until` malformed-ISO crash in `is_payment_current`" (AC8 catches the `ValueError`, logs one sanitised ERROR line keyed only on `key_id`, and raises `ApiKeySuspendedError`).
- Sentinel greps (AC20): `HTTPException` absent from `src/comadre/keys/**`, `api.py`, `main.py`, `exceptions.py`; `==\s*settings\.api_key` absent from `src/comadre`; `os.environ` absent from `src/comadre/keys`; `print(` absent from `keys/cache.py` and `keys/auth.py`; `cachetools` imported from exactly one file (`keys/cache.py`).
- `docs/monetization.md` is a minimal stub pointing to the 60s TTL and the upcoming Story 2.3 `cache-status` CLI; the full operator runbook still lands in Story 4.6.

### File List

**New:**
- `src/comadre/keys/cache.py`
- `src/comadre/keys/auth.py`
- `tests/test_keys_cache.py`
- `tests/test_keys_auth.py`
- `tests/test_main_lifespan.py`
- `tests/_keys_fixtures.py`
- `docs/monetization.md`

**Modified:**
- `src/comadre/keys/models.py` — added `AuthPayload` dataclass
- `src/comadre/keys/db.py` — added `lookup_key_auth` helper
- `src/comadre/exceptions.py` — added `ApiKeyNotFoundError`, `ApiKeySuspendedError`, `ApiKeyRevokedError`
- `src/comadre/api.py` — dual-mode branch in `verify_api_key`
- `src/comadre/main.py` — lifespan Phase 2a + shutdown close
- `pyproject.toml` — added `cachetools>=5.3,<6` runtime dep and mypy override for its missing stubs
- `uv.lock` — resolved `cachetools==5.5.2`
- `tests/conftest.py` — added `app_monetized`, `client_monetized`, `registry_db` fixtures
- `tests/test_api.py` — added `TestMonetizationEnabledAuth` + `TestMonetizationHealthEndpoint`
- `tests/test_keys_db.py` — added `TestLookupKeyAuth`
- `tests/test_keys_models.py` — added `TestAuthPayload`
- `tests/test_exceptions.py` — added three tests, one per new exception subclass
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — story transitioned ready-for-dev → in-progress → review

### Change Log

| Date       | Change                                                                                                                  | Author     |
|------------|-------------------------------------------------------------------------------------------------------------------------|------------|
| 2026-04-17 | Story 2.1 context file created via `bmad-create-story` workflow — status `ready-for-dev`.                                | Galvani    |
| 2026-04-17 | Dev-story workflow: implemented registry auth, AuthCache, dual-mode branch, lifespan bootstrap; +50 tests; status `review`. | Galvani |
| 2026-04-18 | Code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor): 2 HIGH (non-ASCII token → 500; ZoneInfoNotFoundError → 500), 3 MEDIUM (test gaps), 1 LOW patch + 10 deferred + 22 dismissed. | Galvani |

### Review Findings

- [x] [Review][Patch] Non-ASCII bearer token raises `UnicodeEncodeError` → 500 instead of 401 [src/comadre/keys/auth.py:68] — fixed by wrapping the `hash_api_key(token)` call in `try/except UnicodeEncodeError` and raising `ApiKeyNotFoundError` after a dummy `hmac.compare_digest` (preserves FR26 timing equalisation). Regression tests: `tests/test_keys_auth.py::TestNonAsciiBearerToken` + `tests/test_api.py::TestMonetizationEnabledAuth::test_non_ascii_bearer_token_returns_401` (uses raw bytes header to bypass httpx's client-side ASCII check).
- [x] [Review][Patch] `ZoneInfoNotFoundError` → 500 on every request when `BILLING_TIMEZONE` invalid or tzdata missing [src/comadre/keys/auth.py:55,89] — fixed by catching `ZoneInfoNotFoundError` in the billing branch, logging one sanitised ERROR line keyed on the misconfigured timezone (no key/plaintext/hash leakage), and raising the default `KeyRegistryError` envelope (500). Customer-facing message stays generic; operator gets the detailed log line. Regression test: `tests/test_keys_auth.py::TestZoneInfoFailureFailsClosed`.
- [x] [Review][Patch] AC9 — 500 envelope for DB-error path not asserted at HTTP layer [tests/test_api.py] — added `TestMonetizationEnabledAuth::test_db_error_returns_500_envelope` (monkey-patches `lookup_key_auth` to raise `sqlite3.OperationalError`, asserts 500 + envelope shape + `entries == 0`).
- [x] [Review][Patch] AC1 — access-log sanitisation never asserted at integration level [tests/test_api.py] — added `TestMonetizationEnabledAuth::test_access_log_does_not_leak_secrets` (attaches a probe handler directly to the `access` logger because `propagate=False`; scans for `cmdr_live_`, the plaintext, the SHA-256 hash, the customer name, and any 64-hex run).
- [x] [Review][Patch] AC14 — anti-enumeration claim not exercised end-to-end [tests/test_api.py] — added `TestMonetizationEnabledAuth::test_anti_enumeration_envelopes_diverge` (asserts not-found vs suspended 401 envelopes diverge in `message` and `hint`, and that the not-found envelope never leaks the word `suspended`).
- [x] [Review][Patch] AC18 — header-set comparison should use `items()` not `keys()` [tests/test_api.py:542] — tightened to `sorted(legacy.headers.items()) == sorted(registry.headers.items())`.

- [x] [Review][Defer] Synchronous `sqlite3` I/O on the asyncio event loop — should use `asyncio.to_thread` [src/comadre/keys/auth.py:73] — deferred, single indexed SELECT is 0.073ms p99 in the perf-sanity run; well under NFR2 budget. Revisit if cold-cache load becomes a real saturation source.
- [x] [Review][Defer] Private `_apply_migrations` import from `main.py` [src/comadre/main.py:25] — deferred, pre-existing convention from Stories 1.3–1.6 (still open in `deferred-work.md`); a public migration API is a separate hygiene pass.
- [x] [Review][Defer] AC4/AC5 — operator-hint string not byte-compared at integration level [tests/test_api.py:411,427] — deferred, exact-string contract is asserted at unit level (`tests/test_exceptions.py`); integration test only checks substring. Tighten in a follow-up test pass.
- [x] [Review][Defer] AC1/AC2 — `auth_cache.snapshot()["entries"]` not asserted on the HTTP integration path [tests/test_api.py] — deferred, covered at the auth-helper unit-test layer (`tests/test_keys_auth.py:193`).
- [x] [Review][Defer] AC3 — 401 envelope not byte-compared against legacy `AuthenticationError` envelope at HTTP layer [tests/test_api.py:429] — deferred, byte-equality covered at exception-class level (`tests/test_exceptions.py:248-257`).
- [x] [Review][Defer] AC11 — `hasattr(app.state, "auth_cache") == False` not explicitly asserted with the legacy `app` fixture [tests/conftest.py:71] — deferred, covered by the lifespan-level test (`tests/test_main_lifespan.py:184-185`).
- [x] [Review][Defer] AC16 — `PRAGMA journal_mode='wal'` and `PRAGMA foreign_keys=1` not asserted in the lifespan-bootstrap test [tests/test_main_lifespan.py:87-104] — deferred, pragmas covered by Story 1.1's `get_connection` tests.
- [x] [Review][Defer] Lifespan partial failure on `_apply_migrations` leaks the open SQLite connection [src/comadre/main.py:54-63] — deferred, process is dying anyway and OS reclaims the FD; cosmetic at most.
- [x] [Review][Defer] `_payload_to_record` placeholder fields couple auth path to internal `ManualBillingProvider.is_payment_current` field-set [src/comadre/keys/auth.py:104-124] — deferred, low-risk so long as billing provider stays read-only on `billing_mode`/`paid_until`. Re-examine when Story 3.3 cron sweep touches the same provider.
- [x] [Review][Defer] `billing_mode='automated'` silently treated as `manual` by `is_payment_current` [src/comadre/keys/billing.py:35-43] — deferred, no `automated` keys exist today (issue-key doesn't expose it); flag for Story 3.x when PSP adapter lands.
