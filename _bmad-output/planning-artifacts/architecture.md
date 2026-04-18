---
stepsCompleted: [1, 2, 3, 4, 5, 6, 7, 8]
status: 'complete'
completedAt: '2026-04-16'
lastEdited: '2026-04-18'
editHistory:
  - date: '2026-04-18'
    changes: |
      Retired FR27 (legacy single-API_KEY mode) and NFR31 (byte-identical 1.6.2 auth behaviour). Comadre 2.0.0 is registry-only; dual-mode dispatch, `monetization_enabled` toggle, and single-`API_KEY` env var removed. Rate-limit refactored: `slowapi` dropped in favour of `limits` directly, per-key only (bucket = `key:<key_id>`). Per-IP rate-limit removed from the application layer entirely. Driven by Story 2.2 code-review triage and operator-driven re-scope.
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/prd-validation-report.md
  - _bmad-output/planning-artifacts/ux-design-specification.md
  - _bmad-output/project-context.md
  - docs/api-architecture.md
  - docs/api-reference.md
  - docs/configuration-reference.md
  - docs/deployment-guide.md
  - docs/voice-management.md
workflowType: 'architecture'
project_name: 'comadre'
user_name: 'Galvani'
date: '2026-04-15'
---

# Architecture Decision Document

_This document builds collaboratively through step-by-step discovery. Sections are appended as we work through each architectural decision together._

## Project Context Analysis

### Requirements Overview

**Functional Requirements:**

52 FRs in 8 clusters, split across 2 parallel epics:

- **Epic 1 — Monetization Core (FR1–FR34):** Customer lifecycle (FR1–FR7), API key lifecycle (FR8–FR14), billing state management (FR15–FR20), API authentication and rate limiting (FR21–FR29), observability and auditing (FR30–FR34). These are journey-driven — every FR traces to one of the 6 user journeys.
- **Epic 2 — Security & Compliance (FR35–FR52):** LGPD compliance primitives (FR35–FR39), operational safety (FR40–FR45), security regression prevention (FR46–FR52). These are compliance/contract-driven — every FR traces to the non-regression contract or LGPD obligations, not to user journeys.

Both epics must ship together. Epic 1 without Epic 2 exposes LGPD risk and breaks the pentest-hardened posture.

**Non-Functional Requirements:**

37 NFRs across 6 categories, with architecture-shaping constraints:

- **Performance (NFR1–NFR7):** Auth cache-hit <5ms p99, cache-miss <15ms p99, cron sweep <1s for 1K keys, CLI list commands <200ms. The 5ms cache-hit target drives the in-memory caching requirement.
- **Security (NFR8–NFR17):** One-shot key display, SHA-256 hashing, Fernet encryption, timing-safe comparison with dummy-on-miss, 0600 file permissions, no personal data in logs. These define the storage and comparison layer completely.
- **Reliability (NFR18–NFR24):** Zero external dependencies at request time, unclean-shutdown tolerance, 24h RPO via nightly backups, cron must not block auth reads, no warm-up extension.
- **Scalability (NFR25–NFR29):** Single shard supports 1K customers / 2K keys, <50MB memory overhead, <50MB disk growth over 6 months. Multi-replica safety via independent auth caches + shared SQLite WAL.
- **Compatibility (NFR30–NFR33):** Public `/v1/audio/speech` and `/health` request/response contract byte-identical to 1.6.2 (NFR30). Ansible idempotency. CLI backward-compatible within 2.x. **2026-04-18 revision:** NFR31 retired — no legacy single-`API_KEY` mode; 2.0.0 is registry-only.
- **Compliance (NFR34–NFR37):** LGPD access/deletion within 15 days, breach-notification runbook, CDC proportionality (suspended-not-deleted).

**Scale & Complexity:**

- Primary domain: API backend + CLI tool
- Complexity level: medium-high
- Estimated architectural components: 8 new modules (keys/db, keys/auth, keys/cache, keys/billing, keys/crypto, keys/audit, keys/cli, keys/models) plus extensions to 4 existing modules (config, exceptions, rate_limit, main)

### Technical Constraints & Dependencies

**Hard constraints from existing architecture:**

1. **Import graph is downward-only.** New modules must slot in: `config/logging` → `exceptions/schemas` → `keys/models` → `keys/crypto` → `keys/db` → `keys/audit` → `keys/billing` → `keys/cache` → `keys/auth` → `rate_limit` → `api/health` → `main`. The CLI has its own entry point and is NOT in the runtime import graph.
2. **Zero new containers.** SQLite file on the existing Docker volume. No Redis, no Postgres, no sidecar.
3. **No new listening ports.** The CLI runs over SSH on the host, not as a service.
4. **No new network egress.** Auth path has zero external dependencies at request time.
5. **Caddy is the sole external entry point.** No new reverse-proxy routes for MVP (webhook endpoints deferred to 2.1+).
6. **Single FIFO queue per instance.** Monetization must not interfere with the asyncio.Lock-based request pipeline.
7. **All errors via ComadreError subclasses.** 5 new subclasses: ApiKeyNotFoundError, ApiKeySuspendedError, ApiKeyRevokedError, InvalidTaxIdError, KeyRegistryError.
8. **Structured logging only.** get_logger("component"), pipe-delimited format. No print(). No personal data in logs.
9. **uv only.** CLI installed via `uv tool install`. No pip, no poetry.
10. **Everything in English.** Code, comments, commits, docs, configs, API responses, error messages.

**Technology dependencies (already in stack or zero-new):**

- `sqlite3` (stdlib) — key registry storage
- `cryptography` (new dep) — Fernet encryption for CPF/CNPJ at rest
- `typer` (new dep) — CLI framework (brings `rich` as transitive dep)
- `pydantic-settings` (existing) — shared config for app + CLI

### Cross-Cutting Concerns Identified

1. **Authentication middleware** — touches every `/v1/audio/speech` request. Registry-only path: SHA-256 hash → TTLCache check → SQLite lookup on miss → `AuthPayload` on `request.state`. **2026-04-18 revision:** no dual-mode; legacy single-`API_KEY` path removed with FR27.
2. **Audit logging** — touches every CLI mutation and every cron event. Append-only `audit_log` table. Actor identification (`cli:<shell-user>`, `cron:suspension-sweep`, `auth:cache-miss`).
3. **Encryption** — touches every tax-ID write and read. Fernet encrypt on store, decrypt on display. Key rotation requires atomic re-encryption of all rows.
4. **Backward compatibility** — **2026-04-18 revision:** retired. 2.0.0 is a breaking release; no `monetization_enabled` gate, no legacy fallbacks. The NFR30 contract on `/v1/audio/speech` and `/health` request/response shape is preserved; the auth mechanism changes (single bearer → registry-backed bearer) and is a documented breaking change.
5. **Non-regression contract** — 40+ controls from prior pentests that must remain green. FR46–FR52 codify CI verification. Every PR in this cycle runs the full regression suite.
6. **CLI/runtime boundary** — the CLI and the FastAPI app share config and DB access but must never share import paths. The CLI entry point is `comadre-keys` (Typer); the app entry point is `uvicorn`. SQLite WAL provides the concurrency model.

## Starter Template Evaluation

### Primary Technology Domain

**API backend (Python/FastAPI) + CLI tool (Typer)** — brownfield extension of Comadre 1.6.2.

### Starter Options Considered

**Not applicable — brownfield project.** Comadre has a mature, production-deployed codebase with 58 architecture rules, a pre-commit pipeline with 7 linters, strict mypy, and an Ansible-managed deployment. Introducing a starter template or scaffolding tool would conflict with the existing structure. The correct approach is to extend the existing codebase in-place.

### Selected Approach: In-Place Extension

**Rationale:**
The existing stack covers every concern a starter template would provide (build tooling, test infrastructure, lint configuration, CI pipeline, deployment automation). The 2.0.0 feature cluster adds a `keys/` subpackage to the existing `src/comadre/` tree and a Typer CLI entry point — both follow the established conventions.

**New Dependencies (2.0.0):**

| Dependency | Version | Purpose | Justification |
|---|---|---|---|
| `typer` | >=0.12 | CLI framework for `comadre-keys` | Standard Python CLI framework; brings `rich` as transitive dep for terminal rendering |
| `cryptography` | >=43.0 | Fernet encryption for CPF/CNPJ at rest | Industry-standard authenticated encryption; required by LGPD compliance (NFR10) |
| `validate-docbr` | >=2.0 | CPF/CNPJ checksum validation | De-facto Python lib for Brazilian documents; 2.0+ supports the alphanumeric CNPJ defined in RFB IN 2.229/2024 (effective July 2026) — delegating to a maintained dependency beats carrying our own implementation through the format change |
| `sqlite3` | stdlib | Key registry, audit log, billing state | Zero-dependency; already available in Python 3.12 runtime |

**Architectural Decisions Pre-Established by Existing Stack:**

**Language & Runtime:**
Python 3.12+, strict mypy with pydantic plugin, all type annotations required. No change.

**Configuration:**
pydantic-settings BaseSettings via `get_settings()` (LRU-cached). New settings fields added to existing `Settings` class: `key_registry_db_path`, `key_registry_encryption_key` (SecretStr, **required** as of 2026-04-18), `operator_contact_hint`, `billing_day`, `billing_timezone`. **Removed in 2.0.0:** `api_key` (single shared secret) and `monetization_enabled` (toggle) — see PRD revision note for FR27/NFR31 retirement.

**Testing Framework:**
pytest with asyncio_mode=auto, mocked by default. New test files: `test_keys_db.py`, `test_keys_auth.py`, `test_keys_cache.py`, `test_keys_billing.py`, `test_keys_crypto.py`, `test_keys_cli.py`. Minimum 90% coverage on new modules.

**Code Quality:**
ruff (lint + format, line-length 88), mypy strict, pre-commit with 7 linters. All new code follows existing conventions.

**Build & Deploy:**
Docker image rebuilt with new deps. No new container. `uv tool install` for CLI. Ansible bootstrap/cleanup playbooks extended.

**Project Structure:**
New `keys/` subpackage under `src/comadre/`, CLI entry point registered in `pyproject.toml`. CLI installed system-wide as `comadre-keys`.

## Core Architectural Decisions

### Decision Priority Analysis

**Critical Decisions (Block Implementation):**
- SQLite connection management (app-state singleton + per-invocation CLI)
- Auth cache implementation (cachetools.TTLCache, 60s TTL)
- Dual-mode auth switching (conditional inside verify_api_key)
- Module organization (flat keys/ subpackage with CLI sub-package)
- SQLite file location (dedicated comadre-keys Docker volume)

**Important Decisions (Shape Architecture):**
- ID generation (ULID with typed prefix)
- API key format (secrets.token_urlsafe with cmdr_live_ prefix)
- Schema migration (version table + manual SQL)
- Cron implementation (host crontab calling CLI directly)
- Cache invalidation model (accept 60s TTL bound; expose `cache-status` CLI for observability, no mutation)

**Deferred Decisions (Post-MVP):**
- PSP webhook endpoint routing (2.1+)
- Multi-shard aggregate reporting protocol (2.1+)
- Read-only web dashboard architecture (2.2+)

### Data Architecture

**ID Generation: ULID with Typed Prefix**
- Customer IDs: `cust_` + ULID (e.g., `cust_01HF3K9MP2QR7NW4`)
- Key IDs: `key_` + ULID (e.g., `key_01HF3K9MP2QR7NW4`)
- Dependency: `python-ulid` (lightweight, no transitive deps)
- Rationale: time-sortable without explicit ORDER BY on created_at; collision-resistant without coordination; matches PRD mockup format; CLI list output naturally sorts by creation order

**API Key Format: secrets.token_urlsafe with Prefix**
- Format: `cmdr_live_` + `secrets.token_urlsafe(32)` = `cmdr_live_` + 43 chars of URL-safe base64
- Visible prefix for identification: first 7 chars of the full key (`cmdr_li`)
- Storage: SHA-256 hash of full key + 8-char prefix stored separately
- Rationale: stdlib, proven entropy (256 bits), URL-safe characters for safe copy-paste in WhatsApp messages

**SQLite Connection Management: App-State Singleton + Per-Invocation CLI**
- FastAPI: single `sqlite3.Connection` created in lifespan, stored in `app.state.db`, closed on shutdown. WAL mode enforced at creation (`PRAGMA journal_mode=WAL`). Passed to auth middleware and rate-limit resolver via dependency injection.
- CLI: each `comadre-keys` invocation opens a fresh connection, executes the command, closes on exit. WAL mode enforced at creation.
- Rationale: matches the existing app.state pattern (engine router, queue lock). Single connection per replica is sufficient — auth reads are fast (<5ms), and the CLI runs short transactions. WAL mode ensures CLI writes don't block app reads.

**Schema Migration: Version Table + Manual SQL**
- `schema_version` table with a single row tracking the current version integer.
- On startup (lifespan) and on CLI init, check version and apply sequential `.sql` migration files from `src/comadre/keys/migrations/`.
- MVP ships at schema version 1. Future 2.x releases increment the version and add migration files.
- Rationale: zero new deps; SQLite-friendly; explicit and auditable; sufficient for a single-file database with a small schema.

**Auth Cache: cachetools.TTLCache**
- `cachetools.TTLCache(maxsize=4096, ttl=60)` keyed by SHA-256 hash of the bearer token.
- Cache value: `AuthPayload` dataclass with `customer_id`, `status`, `rate_limit_rpm`, `paid_until`, `billing_mode`.
- No personal data in cache (no CPF, no CNPJ, no email, no name).
- Dependency: `cachetools` (small, focused, well-maintained).
- Rationale: battle-tested TTL eviction; thread-safe for the single-threaded asyncio event loop; maxsize prevents unbounded memory growth; 4096 entries covers the NFR25 target of 2K active keys with headroom.

### Authentication & Security

**Registry-Only Auth (2026-04-18 revision)**
- `verify_api_key()` FastAPI dependency has a single path: hash the inbound token, check the TTLCache, on miss query SQLite, validate status + paid_until + billing_mode, cache the result, set `request.state.auth_payload` on success.
- Return type is `None`; side-effect is `request.state.auth_payload` (an `AuthPayload` on success; attribute absent on any failure path before the raise).
- Dual-mode conditional, `settings.monetization_enabled` gate, and the single-`API_KEY` `hmac.compare_digest` legacy path are **removed** per FR27 retirement.
- Rationale: dual-mode was cheap in principle but expensive in practice — AC shape, test matrix, and library interactions (slowapi limit-provider signature) all had to handle both. Single-mode removes that tax.

**Cache Invalidation: Accept 60s TTL, Expose `cache-status` for Observability**
- The `comadre-keys cache-status` command (FR45, renamed from the earlier `cache-status` name) reports the cache-TTL propagation bound and, when practical, cache-health telemetry (hit rate, entry count). It performs no cache mutation.
- Reference output: `"Auth cache propagation bound: 60 seconds. Key-state changes become visible to the API within this window. This command does not force invalidation; to empty the cache faster, restart the affected replica(s)."`
- Rationale: adding a signal or sentinel mechanism to the auth hot path introduces complexity and a potential failure mode for a 60-second worst case. The operator can tell the customer "wait a minute" — which is already the documented behavior. If 2.1+ reveals a real need (e.g., emergency revocation), a signal-based mechanism can be added then. The `cache-status` name honestly reflects that the command is read-only; the previous `cache-status` name misled by implying mutation.

**Key Comparison Flow:**
1. Extract Bearer token from Authorization header.
2. SHA-256 hash the token.
3. Check TTLCache by hash → HIT: validate status/paid_until → allow/deny.
4. MISS: SELECT from api_key WHERE key_hash = ? → found: cache + validate → allow/deny.
5. NOT FOUND: `hmac.compare_digest(hash, dummy_hash)` (timing equalization) → deny.
6. On allow: per-key rate limit resolved from `AuthPayload.rate_limit_rpm`.

### API & Communication Patterns

**API Contract: Zero Changes**
- `/v1/audio/speech` request/response shape is byte-identical to 1.6.2.
- `/health` response adds no new fields; authenticated detail still returns engines/queue/memory/uptime/version.
- Error envelope `{error: {message, type, hint}}` unchanged; new error types use existing shape.
- No new HTTP endpoints in MVP. No REST surface for operator data.

**Rate Limiting: Per-Key Only via `limits` Library (2026-04-18 revision)**
- `slowapi` is **removed** as a dependency. The `/v1/audio/speech` endpoint uses FastAPI `Depends(check_rate_limit)`, which reads `request.state.auth_payload.rate_limit_rpm` (populated by `verify_api_key`) and enforces it via `limits.aio.strategies.MovingWindowRateLimiter` with in-memory storage.
- Bucket key: `f"key:{auth_payload.key_id}"`. Stable across `rotate-key` (same `key_id`, new plaintext).
- Limit string: `f"{auth_payload.rate_limit_rpm}/minute"`. Read from the `AuthCache`-backed payload; no settings fallback in code because the DB schema's `CHECK (rate_limit_rpm > 0)` guarantees every row has a valid value.
- No per-IP bucket in the application and no per-IP replacement at the reverse-proxy layer either. Enumeration is cryptographically bounded by key entropy (128 bits of `cmdr_live_` + 32 hex chars); per-key caps bound TTS compute regardless of origin IP, so per-IP would be a redundant layer fighting the per-key limit.
- Rationale: slowapi 0.1.9's limit-provider callable cannot receive the `Request` object, forcing ugly string-smuggling workarounds under a dual-mode contract. `limits` directly (which is what slowapi wraps) gives full control: bucket, limit, and identifier passed explicitly, no dispatch-on-type. Per-IP logic at the app layer was only coherent under the single-shared-`API_KEY` world (multiple callers per key); with per-customer keys, IP-level concerns are proxy-layer concerns.

**Error Envelope Extensions:**
- `ApiKeyNotFoundError(401)`: same envelope as current invalid-key 401. Indistinguishable from current behavior (enumeration resistance).
- `ApiKeySuspendedError(401)`: `hint` includes `OPERATOR_CONTACT_HINT` value. Only returned after successful hash match (key possession proven).
- `ApiKeyRevokedError(401)`: same as suspended, different hint text.
- `InvalidTaxIdError(400)`: CLI-only, never reaches HTTP path.
- `KeyRegistryError(500)`: SQLite unreachable or corrupt. Auth path fails closed.

### Frontend Architecture

Not applicable — Comadre 2.0.0 has no frontend. The operator interface is CLI-only (Typer + rich). The customer interface is the existing HTTP API. The landing page at `/` is a static HTML file served by Caddy, unchanged from 1.6.2.

### Infrastructure & Deployment

**SQLite File Location: Dedicated Docker Volume (comadre-keys)**
- New volume `comadre-keys` mounted at `/keys` inside the container.
- DB file path: `/keys/registry.db` (inside container) = volume host path accessible to the CLI.
- Config: `KEY_REGISTRY_DB_PATH=/keys/registry.db` in compose.yaml.
- CLI reads the volume's host path directly (resolved by Docker volume inspect or configured in .env).
- Rationale: isolates key data from model files; targeted backup via `backup-keys.yml`; follows existing volume-per-concern pattern.

**Cron: Host Crontab Calling CLI Directly**
- New cron entry `comadre-daily-suspension` at 00:30 operator TZ: `comadre-keys suspend-sweep`.
- Installed by `bootstrap.yml` alongside existing `comadre-daily-restart` and `comadre-audio-cleanup`.
- Optional: `comadre-keys-backup` at 02:00: runs `backup-keys.yml` or a direct SQLite backup command.
- Rationale: follows existing cron pattern; CLI is installed system-wide via `uv tool install`; no Docker image changes needed; cron output captured in syslog for operator debugging.

**Ansible Extensions:**
- `bootstrap.yml`: creates comadre-keys volume, sets DB file permissions (0600), installs CLI via `uv tool install`, adds cron entries, adds `KEY_REGISTRY_ENCRYPTION_KEY` to .env.
- `cleanup.yml`: removes comadre-keys volume, removes cron entries, uninstalls CLI.
- `health.yml`: reports monetization status, DB file permissions, cron liveness, last backup timestamp.
- New `backup-keys.yml`: SQLite snapshot + encryption key backup, encrypted tarball, mode 0600.
- New `restore-keys.yml`: restore from backup tarball, idempotent.

**Environment Variables (New):**

| Variable | Default | Type | Description |
|---|---|---|---|
| `KEY_REGISTRY_DB_PATH` | `/keys/registry.db` | str | Path to SQLite key registry |
| `KEY_REGISTRY_ENCRYPTION_KEY` | *(required — 2.0.0 is registry-only)* | SecretStr | Fernet key for CPF/CNPJ encryption |
| `OPERATOR_CONTACT_HINT` | `"Contact your Comadre operator."` | str | Displayed in 401 hints for suspended keys |
| `BILLING_DAY` | `5` | int | Day of month for billing cycle |
| `BILLING_TIMEZONE` | `America/Sao_Paulo` | str | IANA timezone for cron and billing logic |
**Removed in 2.0.0** (per FR27 retirement, 2026-04-18):
- `API_KEY` — single shared bearer. Registry-only auth; no global secret.
- `MONETIZATION_ENABLED` — toggle. Registry is always on.
- `RATE_LIMIT_SPEECH` — slowapi-format per-IP string. Replaced by per-key `rate_limit_rpm` from the DB row.

### Decision Impact Analysis

**Implementation Sequence:**
1. `keys/models.py` + `keys/crypto.py` — data models, CPF/CNPJ validation (via `validate-docbr`), and Fernet encryption
2. `keys/db.py` + `keys/audit.py` + migrations — storage layer (depends on models + crypto)
3. `keys/cache.py` — TTLCache wrapper (depends on models)
4. `keys/billing.py` — ManualBillingProvider + suspension sweep (depends on db + audit)
5. `keys/auth.py` — verify_api_key integration (depends on cache + db)
6. `config.py` + `exceptions.py` extensions — new settings fields and error classes
7. `rate_limit.py` extension — dynamic per-key limit resolver
8. `main.py` extension — lifespan DB init, migration check
9. `keys/cli/` — Typer app, commands, output rendering (depends on all of the above)
10. Ansible + cron + docs — deployment integration

**Cross-Component Dependencies:**
- `keys/auth.py` depends on `keys/cache.py` and `keys/db.py` — the cache-miss path hits the DB.
- `keys/billing.py` depends on `keys/db.py` and `keys/audit.py` — suspension writes go through audit.
- `rate_limit.py` depends on `keys/auth.py` — the dynamic limit comes from the auth payload.
- `keys/cli/` depends on everything in `keys/` except `keys/auth.py` and `keys/cache.py` (CLI doesn't use the auth cache; it reads/writes DB directly).
- `main.py` depends on `keys/auth.py` for the verify_api_key integration and on `keys/db.py` for lifespan DB init.

## Implementation Patterns & Consistency Rules

### Pattern Categories Defined

**Critical Conflict Points Identified:** 12 areas where AI agents implementing different stories could make incompatible choices. All patterns below are specific to the 2.0.0 monetization feature cluster — general Python/FastAPI conventions are already enforced by project-context.md (58 rules).

### Naming Patterns

**Database Naming Conventions:**
- Tables: lowercase singular (`customer`, `api_key`, `audit_log`, `schema_version`)
- Columns: snake_case (`key_hash`, `paid_until`, `rate_limit_rpm`, `tax_id_encrypted`)
- Foreign keys: `{referenced_table}_id` (e.g., `customer_id`)
- Indexes: `idx_{table}_{columns}` (e.g., `idx_api_key_hash`, `idx_api_key_customer`, `idx_api_key_sweep`)
- CHECK constraints: inline, not named
- All column names and table names must match the PRD schema exactly (lines 843–884)

**ID Naming Conventions:**
- Customer IDs: `cust_` + ULID lowercase (e.g., `cust_01jgxr3e4c5m7kn9p2qt8vwy`)
- Key IDs: `key_` + ULID lowercase (e.g., `key_01jgxr3e4c5m7kn9p2qt8vwy`)
- Generate via `ulid.new().str.lower()` with prefix prepended
- Never use UUID, auto-increment, or custom ID schemes

**API Key Naming:**
- Full key: `cmdr_live_` + `secrets.token_urlsafe(32)` (e.g., `cmdr_live_KQjPz8vR9NwT3MxAbYcH5dLeFgJ2nSsU...`)
- Visible prefix for identification: first 7 characters of the full key (always `cmdr_li` due to the fixed prefix)
- Stored prefix: `key_prefix` column = first 8 characters *after* `cmdr_live_` (the unique part)
- Never store, log, or cache the full plaintext key after creation

**Audit Action Naming:**
- Actions: snake_case verb_noun (e.g., `create_customer`, `issue_key`, `mark_paid`, `suspend_key`, `revoke_key`, `rotate_key`, `delete_customer`, `reactivate_key`, `update_key`, `update_customer`, `rotate_encryption_key`)
- Cron actions: `cron_suspend` (daily sweep)
- Actor format: `cli:{unix_username}` for CLI, `cron:suspension-sweep` for cron, `system:startup` for migrations
- Get unix username via `os.getlogin()` with fallback to `getpass.getuser()`

**CLI Command Naming:**
- Typer subcommands: hyphen-separated verb-noun (e.g., `create-customer`, `issue-key`, `mark-paid`, `list-keys`)
- Must match PRD CLI specification exactly (lines 952–982)
- Internal function names: underscore equivalent (e.g., `def create_customer()`)

### Structure Patterns

**Module Organization:**
```
src/comadre/keys/
    __init__.py          # Public API: exports used by auth.py and main.py
    models.py            # Pydantic models (CustomerCreate, KeyIssue, AuthPayload, etc.)
    crypto.py            # Fernet encrypt/decrypt, CPF/CNPJ validation
    db.py                # SQLite CRUD (customer_*, key_*, get_connection)
    audit.py             # audit_log write operations
    billing.py           # BillingProvider ABC, ManualBillingProvider, suspend_sweep()
    cache.py             # AuthCache wrapper around TTLCache
    auth.py              # verify_api_key_registry(), integrate with FastAPI dependency
    migrations/
        __init__.py
        v001_initial.sql # CREATE TABLE statements
    cli/
        __init__.py      # Typer app instance
        app.py           # Main Typer app with subcommand registration
        commands/
            __init__.py
            customers.py # create-customer, update-customer, delete-customer, export-customer, list-customers
            keys.py      # issue-key, update-key, rotate-key, revoke-key, list-keys, suspend, reactivate
            billing.py   # mark-paid, at-risk, revenue
            system.py    # health, rotate-encryption-key, cache-status, suspend-sweep
        output.py        # All rich render functions (render_key_panel, render_status_table, etc.)
```

**Test Organization:**
```
tests/
    test_keys_models.py    # Pydantic model validation
    test_keys_crypto.py    # Encrypt/decrypt, CPF/CNPJ checksum
    test_keys_db.py        # SQLite CRUD with in-memory DB
    test_keys_audit.py     # Audit log writes
    test_keys_billing.py   # ManualBillingProvider, suspend_sweep
    test_keys_cache.py     # TTLCache behavior, TTL expiration
    test_keys_auth.py      # verify_api_key with monetization enabled/disabled
    test_keys_cli.py       # CLI command integration tests via CliRunner
    test_keys_output.py    # Rich rendering output verification
```

**Import Boundary Rules:**
- `keys/cli/` may import from `keys/db`, `keys/audit`, `keys/billing`, `keys/crypto`, `keys/models`
- `keys/cli/` must NEVER import from `keys/auth` or `keys/cache` (those are runtime-only)
- `keys/auth.py` may import from `keys/cache`, `keys/db`, `keys/models`
- `keys/auth.py` must NEVER import from `keys/cli/`
- `rate_limit.py` may import `AuthPayload` from `keys/models` but nothing else from `keys/`
- `api.py` must NEVER import from `keys/` directly — it uses `verify_api_key` dependency

### Format Patterns

**SQLite Query Patterns:**
- All queries use parameterized placeholders (`?`), never string interpolation or f-strings
- All writes wrapped in explicit transactions: `with conn:` context manager
- SELECT queries do not need explicit transactions (SQLite autocommit for reads)
- All datetime values stored as ISO 8601 UTC strings (`YYYY-MM-DDTHH:MM:SSZ`)
- All money values stored as `REAL` with 2 decimal places (BRL, no currency conversion)
- Example good: `conn.execute("SELECT * FROM api_key WHERE key_hash = ?", (hash_value,))`
- Example bad: `conn.execute(f"SELECT * FROM api_key WHERE key_hash = '{hash_value}'")`

**Fernet Encryption Pattern:**
```python
# Encrypt (on write)
fernet = Fernet(settings.key_registry_encryption_key.get_secret_value().encode())
encrypted = fernet.encrypt(plaintext_cpf.encode())  # returns bytes

# Decrypt (on read, CLI only)
decrypted = fernet.decrypt(encrypted_bytes).decode()  # returns str
```
- Always encode string to bytes before encrypting
- Always decode bytes to string after decrypting
- Never cache decrypted values — decrypt on demand for display only
- The Fernet key is read from `settings.key_registry_encryption_key` (SecretStr)

**CPF/CNPJ Validation Pattern:**
- Accept input with or without formatting (dots, dashes, slashes, whitespace)
- Validate via `validate-docbr` (`CPF` with default `repeated_digits=False`; `CNPJ` accepting numeric AND alphanumeric forms per RFB IN 2.229/2024, effective July 2026)
- Enforce canonical length upfront (11 for CPF, 14 for CNPJ) — validate-docbr zero-pads shorter inputs, which is too permissive for our storage contract
- `strip_tax_id` removes mask punctuation and uppercases the remainder so alphanumeric CNPJ normalizes deterministically
- Store the stripped+uppercased form in `tax_id_encrypted` (encrypted with Fernet)
- Display formatted form in CLI output (`123.456.789-00`, `12.345.678/0001-90`; alphanumeric CNPJ rendered as-is with the `XX.XXX.XXX/XXXX-NN` separator layout)
- Never echo invalid input in error messages (enumeration / log-injection prevention, FR37/NFR16)

**CLI Output Patterns:**
- Success data → stdout. Errors → stderr.
- Human-readable (default): use `render_*` functions from `output.py`
- Machine-readable (`--format json`): emit via `Console.print_json()`, bypass rich formatting
- Exit codes: 0=success, 1=general, 2=usage, 3=not-found, 4=validation, 5=database, 6=permission
- Empty results are NOT errors: print informational message, exit 0
- Single-line confirmations for mutations: `"Marked paid: cmdr_Pq (Name) → paid until YYYY-MM-DD"`
- Key plaintext display: always use `render_key_panel()` with double border, never print raw

### Communication Patterns

**Auth Payload Flow (2026-04-18 revision):**
- `verify_api_key()` returns `None`; its side effect is `request.state.auth_payload = AuthPayload(...)` on success. On any denial (401, 403, 500) it raises a `ComadreError` subclass before setting the attribute.
- `AuthPayload` is a frozen dataclass (immutable after creation).
- The payload flows: `verify_api_key()` → `request.state.auth_payload` → read by `check_rate_limit` (rate-limit dependency) and by route handlers → discarded after response.
- Never store AuthPayload in a module-level variable or `app.state`.
- No "legacy mode" shape — `auth_payload` is either set (registry allow) or the request never reaches the handler (raise). `getattr(request.state, "auth_payload", None)` is still used defensively in middleware for robustness against dependency-order regressions.

**Cache Interaction Pattern:**
- The auth path ALWAYS checks cache first, then DB on miss
- Cache writes happen only on successful DB lookup (never cache failures)
- Cache key is the SHA-256 hash of the bearer token (same hash used for DB lookup)
- Cache value is `AuthPayload` — never raw DB rows, never dicts
- The cache is per-replica (not shared). Each replica has its own TTLCache instance in app.state

**Billing Provider Pattern:**
```python
class BillingProvider(ABC):
    @abstractmethod
    def is_payment_current(self, key: ApiKeyRecord) -> bool: ...
    @abstractmethod
    def on_key_issued(self, key: ApiKeyRecord) -> None: ...
    @abstractmethod
    def on_key_revoked(self, key: ApiKeyRecord) -> None: ...

class ManualBillingProvider(BillingProvider):
    # MVP: checks paid_until >= today for manual billing mode
    # Complimentary keys: always current
```
- The `BillingProvider` ABC has exactly 3 methods — no `create_subscription` or `handle_webhook` in MVP
- `ManualBillingProvider` is the only concrete implementation in 2.0.0
- The provider is instantiated once and stored in app.state (not per-request)

### Process Patterns

**Error Handling in CLI:**
- All CLI errors catch exceptions and render via `render_error(message, hint)` on stderr
- Never let unhandled exceptions propagate to the terminal — wrap in try/except at the command level
- Map exceptions to exit codes: `ComadreError` subclasses carry their own mapping
- Validation errors (bad CPF, missing flags) caught by Typer or pydantic before business logic

**Error Handling in Auth Path:**
- Auth failures raise `ComadreError` subclasses — the existing exception handler in main.py renders them
- The auth path must NEVER raise `HTTPException` — always use the typed subclasses
- On `KeyRegistryError` (DB unreachable): fail closed (deny access), log at ERROR level
- On cache miss + DB miss: perform dummy `hmac.compare_digest` before raising `ApiKeyNotFoundError`

**Transaction Scope:**
- CLI commands that create or modify multiple records (e.g., `delete-customer --hard` removes customer + keys + audit) must use a single transaction
- The suspension sweep (`suspend-sweep`) uses a single UPDATE statement, not per-row transactions
- Audit log writes happen inside the same transaction as the mutation they record
- Never hold a transaction open across user interaction (CLI has no interactive prompts during writes)

### Enforcement Guidelines

**All AI Agents MUST:**
1. Run `uv run pytest && uv run ruff check . && uv run mypy src/` before claiming a story is complete
2. Verify no `HTTPException` in new code — grep for it as a sanity check
3. Verify no personal data (CPF, CNPJ, plaintext key) in any log statement
4. Verify all SQL uses parameterized queries — grep for string interpolation in `.py` files touching `conn.execute`
5. Verify import graph is downward-only — no circular imports, no CLI importing from auth/cache
6. Match CLI command names, flags, and output exactly to the PRD specification (lines 952–1005) and UX spec component definitions

**Anti-Patterns (Never Do These):**
- Never store decrypted CPF/CNPJ in the cache or in any in-memory data structure beyond the immediate render call
- Never import `keys.cli` from any module in the FastAPI runtime path
- Never use `sqlite3.connect()` directly in command code — always go through `keys/db.py:get_connection()`
- Never create a second TTLCache instance — use the one in `app.state.auth_cache`
- Never add `print()` to CLI code — use `rich.Console` via the shared instance in `output.py`
- Never hardcode the billing day (5) — always read from `settings.billing_day`
- Never check `paid_until` without also checking `billing_mode` (complimentary keys have no paid_until)

## Project Structure & Boundaries

### Complete Project Directory Structure

Files marked with `[NEW]` are added by 2.0.0. Files marked with `[MOD]` are modified. Unmarked files are unchanged.

```
comadre/
├── .github/
│   └── workflows/
│       └── ci.yml                          [MOD] add bandit step, keys test coverage gate
├── .env.example                            [MOD] add monetization env vars
├── compose.yaml                            [MOD] add comadre-keys volume, env vars
├── Dockerfile                              [MOD] add cryptography, typer, cachetools, python-ulid deps
├── pyproject.toml                          [MOD] add deps, CLI entry point [project.scripts]
├── CLAUDE.md                               [MOD] add monetization architecture section
│
├── src/comadre/
│   ├── __init__.py
│   ├── config.py                           [MOD] add monetization settings fields
│   ├── logging.py
│   ├── exceptions.py                       [MOD] add 5 new ComadreError subclasses
│   ├── schemas.py
│   ├── preprocessing.py
│   ├── download.py
│   ├── service.py
│   ├── rate_limit.py                       [MOD] add dynamic per-key limit resolver
│   ├── health.py
│   ├── api.py                              [MOD] verify_api_key gains registry branch
│   ├── main.py                             [MOD] lifespan: DB init, migration, cache init
│   │
│   └── keys/                               [NEW] entire subpackage
│       ├── __init__.py                     [NEW] public API exports
│       ├── models.py                       [NEW] pydantic models + AuthPayload dataclass
│       ├── crypto.py                       [NEW] Fernet encrypt/decrypt, CPF/CNPJ validation
│       ├── db.py                           [NEW] get_connection(), SQLite CRUD operations
│       ├── audit.py                        [NEW] audit_log write operations
│       ├── billing.py                      [NEW] BillingProvider ABC, ManualBillingProvider
│       ├── cache.py                        [NEW] AuthCache wrapper around TTLCache
│       ├── auth.py                         [NEW] verify_api_key_registry()
│       ├── migrations/
│       │   ├── __init__.py                 [NEW]
│       │   └── v001_initial.sql            [NEW] CREATE TABLE + indexes
│       └── cli/
│           ├── __init__.py                 [NEW] Typer app instance
│           ├── app.py                      [NEW] main app + subcommand registration
│           ├── output.py                   [NEW] all rich render functions
│           └── commands/
│               ├── __init__.py             [NEW]
│               ├── customers.py            [NEW] create/update/delete/export/list-customers
│               ├── keys.py                 [NEW] issue/update/rotate/revoke/list-keys/suspend/reactivate
│               ├── billing.py              [NEW] mark-paid, at-risk, revenue
│               └── system.py              [NEW] health, rotate-encryption-key, cache-status, suspend-sweep
│
├── tests/
│   ├── conftest.py                         [MOD] add DB fixtures, CLI runner, monetization mocks
│   ├── test_api.py                         [MOD] add monetization-enabled auth tests
│   ├── test_rate_limit.py                  [MOD] add dynamic per-key limit tests
│   ├── test_keys_models.py                 [NEW] pydantic model validation
│   ├── test_keys_crypto.py                 [NEW] encrypt/decrypt, CPF/CNPJ checksum
│   ├── test_keys_db.py                     [NEW] SQLite CRUD with in-memory DB
│   ├── test_keys_audit.py                  [NEW] audit log writes
│   ├── test_keys_billing.py                [NEW] ManualBillingProvider, suspend_sweep
│   ├── test_keys_cache.py                  [NEW] TTLCache behavior, TTL expiration
│   ├── test_keys_auth.py                   [NEW] verify_api_key dual-mode tests
│   ├── test_keys_cli.py                    [NEW] CLI command tests via CliRunner
│   └── test_keys_output.py                 [NEW] rich rendering output verification
│
├── deploy/
│   ├── ansible/
│   │   ├── playbooks/
│   │   │   ├── bootstrap.yml               [MOD] DB init, CLI install, cron, encryption key
│   │   │   ├── update.yml
│   │   │   ├── health.yml                  [MOD] monetization probes
│   │   │   ├── cleanup.yml                 [MOD] remove keys volume, cron, CLI
│   │   │   ├── deploy-voices.yml
│   │   │   ├── deploy-models.yml
│   │   │   ├── backup-keys.yml             [NEW] nightly SQLite + encryption key backup
│   │   │   └── restore-keys.yml            [NEW] restore from backup tarball
│   │   └── inventory/
│   │       ├── production.yml.example      [MOD] add monetization vars
│   │       └── oracle.yml.example          [MOD] add monetization vars
│   ├── caddy/
│   │   ├── Caddyfile
│   │   └── Caddyfile-no-landing
│   ├── bin/
│   │   └── rotate-api-key.sh
│   ├── espeak-ng/
│   │   └── pt_extra
│   └── landing/
│       └── index.html
│
├── docs/
│   ├── monetization.md                     [NEW] operator runbook
│   ├── api-architecture.md
│   ├── api-reference.md
│   ├── configuration-reference.md          [MOD] add monetization env vars
│   ├── deployment-guide.md                 [MOD] add monetization deploy steps
│   ├── voice-management.md
│   └── ...existing docs...
│
└── _bmad-output/
    ├── project-context.md                  [MOD] regenerate with monetization rules
    └── planning-artifacts/
        ├── prd.md
        ├── prd-validation-report.md
        ├── ux-design-specification.md
        └── architecture.md
```

### Architectural Boundaries

**API Boundary (HTTP surface — unchanged):**
- `POST /v1/audio/speech` — sole customer-facing endpoint. Auth path changes internally; contract unchanged.
- `GET /health` — diagnostic. Accepts any valid key (not just operator key) when monetization enabled.
- `GET /` — static landing page via Caddy. No monetization interaction.
- No new HTTP endpoints in MVP. No admin API. No webhook endpoints.

**CLI Boundary (SSH surface — new):**
- `comadre-keys` binary installed system-wide via `uv tool install`.
- Entry point: `pyproject.toml` → `[project.scripts]` → `comadre-keys = "comadre.keys.cli.app:main"`.
- Runs on the host, not inside Docker. Reads `.env` via pydantic-settings. Opens SQLite directly.
- Never imported by the FastAPI runtime. Separate process, separate connection.

**Data Boundary (SQLite):**
- Single file: `/keys/registry.db` (container path) = host volume path.
- FastAPI app: read-heavy (auth lookups), write-light (last_used_at updates).
- CLI: write-heavy (CRUD operations), read for display (list, show, revenue).
- Cron: write (suspension sweep), read (at-risk queries).
- WAL mode enables concurrent reads during CLI/cron writes.

**Cache Boundary (in-memory, per-replica):**
- `app.state.auth_cache` — TTLCache instance, lives only in FastAPI process memory.
- Not shared across replicas. Not accessible to CLI or cron.
- Auth path is the sole reader/writer. Cache misses fall through to SQLite.

**Encryption Boundary:**
- `keys/crypto.py` is the sole module that handles Fernet operations.
- CPF/CNPJ encryption/decryption ONLY happens in `crypto.py` — no other module touches Fernet directly.
- The encryption key is read from settings once per operation, never cached in module state.

### Requirements to Structure Mapping

**Epic 1 — Monetization Core:**

| FR Cluster | Primary Module | Supporting Modules | Tests |
|---|---|---|---|
| Customer Lifecycle (FR1–FR7) | `keys/db.py` | `keys/crypto.py`, `keys/models.py`, `keys/audit.py` | `test_keys_db.py`, `test_keys_crypto.py` |
| API Key Lifecycle (FR8–FR14) | `keys/db.py` | `keys/models.py`, `keys/audit.py` | `test_keys_db.py` |
| Billing State (FR15–FR20) | `keys/billing.py` | `keys/db.py`, `keys/audit.py` | `test_keys_billing.py` |
| Auth & Rate Limiting (FR21–FR29) | `keys/auth.py`, `rate_limit.py` | `keys/cache.py`, `keys/db.py`, `api.py` | `test_keys_auth.py`, `test_rate_limit.py` |
| Observability (FR30–FR34) | `keys/audit.py`, `keys/cache.py` | `keys/db.py` | `test_keys_audit.py`, `test_keys_cache.py` |
| CLI (all commands) | `keys/cli/commands/` | `keys/cli/output.py`, all `keys/` modules | `test_keys_cli.py`, `test_keys_output.py` |

**Epic 2 — Security & Compliance:**

| FR Cluster | Primary Module | Supporting Modules | Tests |
|---|---|---|---|
| LGPD (FR35–FR39) | `keys/crypto.py`, `keys/db.py` | `keys/audit.py`, `docs/monetization.md` | `test_keys_crypto.py`, `test_keys_db.py` |
| Operational Safety (FR40–FR45) | `deploy/ansible/playbooks/` | `keys/db.py`, `keys/cli/commands/system.py` | `test_keys_cli.py` |
| Security Regression (FR46–FR52) | `.github/workflows/ci.yml` | `test_api.py`, `test_rate_limit.py` | existing + extended tests |

### Data Flow

**Auth Request Flow (monetization enabled):**
```
Client → Caddy (TLS + XFF) → FastAPI
  → slowapi per-IP throttle
  → verify_api_key()
    → SHA-256(token)
    → auth_cache.get(hash)
      HIT → AuthPayload → validate status/paid_until
      MISS → keys/db.py SELECT by hash
        FOUND → cache.set(hash, payload) → validate
        NOT FOUND → hmac.compare_digest(dummy) → 401
  → slowapi per-key throttle (rpm from AuthPayload)
  → route handler → TTS engine → response
```

**CLI Command Flow:**
```
Operator SSH → comadre-keys <command>
  → pydantic-settings loads .env
  → keys/db.py opens SQLite (WAL mode)
  → command logic (CRUD via db.py, audit via audit.py, crypto via crypto.py)
  → keys/cli/output.py renders result (rich or JSON)
  → exit code
```

**Cron Suspension Flow:**
```
Host crontab (00:30) → comadre-keys suspend-sweep
  → keys/db.py opens SQLite
  → UPDATE api_key SET status='suspended'
    WHERE billing_mode='manual' AND paid_until < today AND status='active'
  → keys/audit.py logs each suspension
  → exit 0
```

## Architecture Validation Results

### Coherence Validation

**Decision Compatibility:** PASS
- All technology choices (Python 3.12, sqlite3 stdlib, cryptography, typer, cachetools, python-ulid) are compatible and have no conflicting dependencies.
- Typer's transitive dependency on rich satisfies the UX spec's rendering requirements without additional deps.
- pydantic-settings shared between app and CLI ensures config consistency.
- cachetools.TTLCache is single-threaded-safe, appropriate for asyncio event loop.

**Pattern Consistency:** PASS
- All new naming conventions (database, IDs, audit actions, CLI commands) extend existing project conventions without contradiction.
- Import graph extension is downward-only and consistent with the existing module hierarchy.
- Error handling (ComadreError subclasses) follows the established pattern exactly.
- Structured logging (get_logger, pipe-delimited) applies uniformly to new modules.

**Structure Alignment:** PASS
- Project tree supports all architectural decisions.
- CLI isolation (separate entry point, never imported by runtime) is enforced by module layout.
- Test organization mirrors source organization (one test file per module).
- Ansible playbook extensions follow existing patterns (bootstrap/update/health/cleanup).

### Requirements Coverage Validation

**Epic 1 — Monetization Core (FR1–FR34):** PASS
- All 34 FRs have clear module owners and test coverage targets.
- Customer lifecycle (FR1–FR7): keys/db.py + keys/crypto.py.
- Key lifecycle (FR8–FR14): keys/db.py + keys/audit.py.
- Billing state (FR15–FR20): keys/billing.py + cron.
- Auth & rate limiting (FR21–FR29): keys/auth.py + keys/cache.py + rate_limit.py.
- Observability (FR30–FR34): keys/audit.py + structured logs. **FR33 partially deferred** (see Gap 1).

**Epic 2 — Security & Compliance (FR35–FR52):** PASS
- LGPD (FR35–FR39): keys/crypto.py for encryption, keys/db.py for purge, docs/monetization.md for runbook.
- Operational safety (FR40–FR45): backup-keys.yml, restore-keys.yml, health.yml extensions.
- Security regression (FR46–FR52): CI pipeline extensions, existing test suite preserved.

**Non-Functional Requirements (NFR1–NFR37):** PASS
- Performance (NFR1–NFR7): TTLCache delivers <5ms cache-hit; SQLite delivers <15ms cache-miss; cron sweep is a single UPDATE.
- Security (NFR8–NFR17): SHA-256 hashing, Fernet encryption, timing-safe comparison, 0600 permissions, log scrubbing — all architecturally specified.
- Reliability (NFR18–NFR24): WAL mode, nightly backup, zero external deps, no warm-up extension.
- Scalability (NFR25–NFR29): 4096-entry cache, single SQLite file, <50MB overhead target.
- Compatibility (NFR30–NFR33): NFR30 public-contract byte-identity on `/v1/audio/speech` + `/health` preserved; NFR31 retired 2026-04-18 (no legacy mode); NFR32 Ansible idempotency; NFR33 CLI back-compat within 2.x.
- Compliance (NFR34–NFR37): export-customer, delete-customer --hard, breach runbook, CDC proportionality.

### Gap Analysis Results

**Gap 1 (Important — resolved by scoping): Per-key request counters (FR33)**
- In-memory per-key request counters cannot be queried from the host CLI.
- **Resolution:** MVP `show --audit-tail` displays audit_log events from SQLite (mutations, cron events). For request-level stats (peak RPM, 429 count), the operator greps the structured application logs by key prefix. Real-time in-memory counters exposed via an internal health endpoint are deferred to 2.1+.
- **Impact:** Journey 5's "Last 24h stats" section is simplified. The diagnostic use case (distinguishing 401 vs 429) is fully served by structured logs.

**Gap 2 (Critical — resolved by design change): SQLite file access from host CLI**
- Docker named volume is not directly accessible from the host without root-level Docker internals.
- **Resolution:** Replace named volume with bind mount. compose.yaml uses `./data/keys:/keys:rw`. Host path is `~/comadre/data/keys/registry.db`. CLI reads the host path from `KEY_REGISTRY_DB_PATH` in `.env`. Bootstrap creates directory with mode 0700, DB file with mode 0600.
- **Impact:** Simpler, more transparent. Operator can inspect the DB file directly. Backup targets a known host path.
- **Correction to §Infrastructure & Deployment:** The "Dedicated Docker Volume (comadre-keys)" decision is superseded by this bind mount approach. `KEY_REGISTRY_DB_PATH` defaults to `./data/keys/registry.db` (relative to project root) on the host and `/keys/registry.db` inside the container.

**No other gaps found.** All 52 FRs and 37 NFRs have architectural support.

### Architecture Completeness Checklist

**Requirements Analysis**
- [x] Project context thoroughly analyzed (58 existing rules + PRD + UX spec)
- [x] Scale and complexity assessed (medium-high, 1K customers target)
- [x] Technical constraints identified (10 hard constraints)
- [x] Cross-cutting concerns mapped (6 concerns)

**Architectural Decisions**
- [x] Critical decisions documented (5 critical, 5 important)
- [x] Technology stack fully specified (4 new deps, versions pinned)
- [x] Integration patterns defined (auth flow, CLI flow, cron flow)
- [x] Performance considerations addressed (cache sizing, TTL, WAL mode)

**Implementation Patterns**
- [x] Naming conventions established (DB, IDs, API keys, audit actions, CLI commands)
- [x] Structure patterns defined (module layout, test layout, import boundaries)
- [x] Communication patterns specified (auth payload flow, cache interaction, billing provider)
- [x] Process patterns documented (error handling, transaction scope, encryption)

**Project Structure**
- [x] Complete directory structure defined (all new and modified files listed)
- [x] Component boundaries established (API, CLI, data, cache, encryption)
- [x] Integration points mapped (auth path, cron, backup/restore)
- [x] Requirements to structure mapping complete (FR→module→test table)

### Architecture Readiness Assessment

**Overall Status:** READY FOR IMPLEMENTATION

**Confidence Level:** High — brownfield project with locked-in conventions reduces decision surface; two gaps found and resolved during validation.

**Key Strengths:**
- Existing 58-rule architecture envelope constrains new decisions, reducing risk of divergence
- Zero new containers, zero new network dependencies — minimal blast radius
- ~~Binary `monetization_enabled` toggle provides clean rollback path~~ **REVISED 2026-04-18:** rollback via git-revert to 1.6.2 tag; no toggle needed.
- CLI/runtime separation enforced by module layout, not just convention
- Every FR maps to a specific module and test file

**Areas for Future Enhancement (2.1+):**
- Per-key real-time request counters via internal health endpoint
- PSP webhook adapter architecture (BillingProvider implementations)
- Multi-shard aggregate reporting protocol
- Read-only web dashboard behind Headscale VPN

### Implementation Handoff

**AI Agent Guidelines:**
- Follow all architectural decisions exactly as documented in this file
- Use implementation patterns consistently — the patterns section is the definitive reference for "how"
- Respect import boundaries — violations break the module isolation guarantee
- Refer to this document for all architectural questions before making ad-hoc choices
- When in doubt between two approaches, prefer the one that keeps the import graph simpler

**First Implementation Priority:**
1. Add new dependencies to `pyproject.toml` (typer, cryptography, cachetools, python-ulid)
2. Add new settings fields to `config.py`
3. Add new ComadreError subclasses to `exceptions.py`
4. Create `keys/` subpackage with `models.py`, `crypto.py`, `db.py` (foundation layer)
5. Build upward through the dependency chain per the Implementation Sequence in §Decision Impact Analysis
