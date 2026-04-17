---
stepsCompleted: [1, 2, 3, 4]
status: 'complete'
completedAt: '2026-04-16'
inputDocuments:
  - _bmad-output/planning-artifacts/prd.md
  - _bmad-output/planning-artifacts/architecture.md
  - _bmad-output/planning-artifacts/ux-design-specification.md
  - _bmad-output/project-context.md
---

# Comadre - Epic Breakdown

## Overview

This document provides the complete epic and story breakdown for Comadre 2.0.0, decomposing the requirements from the PRD, UX Design, and Architecture into implementable stories. The 2.0.0 release adds customer-scoped API-key management and recurring billing to enable operators to resell TTS capacity.

## Requirements Inventory

### Functional Requirements

**Customer Lifecycle Management (FR1–FR7)**

- FR1: Operator can register a new customer by providing name, email, and either CPF or CNPJ (never both).
- FR2: System rejects a new customer record when the provided CPF or CNPJ fails Brazilian checksum validation.
- FR3: Operator can attach free-form notes to any customer record and append additional notes without overwriting existing ones.
- FR4: Operator can update a customer's email and notes without affecting other fields.
- FR5: Operator can irreversibly purge a customer record, including the tax-ID, all associated keys, and personal data, in compliance with the LGPD right to deletion.
- FR6: Operator can export a single customer's stored data in a machine-readable format suitable for fulfillment of LGPD data-subject access requests.
- FR7: Operator can list all customers, with an optional filter to include tombstone records left by prior LGPD purges.

**API Key Lifecycle Management (FR8–FR14)**

- FR8: Operator can issue a new API key against an existing customer, specifying the per-key rate limit and monthly price.
- FR9: Operator can issue a complimentary API key whose billing is handled outside Comadre (e.g., bundled in an external service contract).
- FR10: Operator can update an existing key's rate limit, monthly price, and notes without disclosing or changing the key plaintext.
- FR11: Operator can rotate a key, producing a new plaintext while retaining the same key id and customer association; the old key stops working immediately.
- FR12: Operator can revoke a key with a free-form reason; revoked keys are retained in the database as historical records.
- FR13: Operator can list keys filtered by status, billing mode, paid-until date, or customer id.
- FR14: Operator can view full context for a single key including customer, dates, price, notes, and recent audit events.

**Billing State Management (FR15–FR20)**

- FR15: Operator can mark a manual-mode key as paid through a specified future date.
- FR16: Operator can query which keys are approaching billing expiration within a configurable look-ahead window.
- FR17: Operator can generate a revenue report for any calendar month showing paid, pending, suspended, and complimentary breakdowns; complimentary keys are reported separately and never counted in recurring-revenue totals.
- FR18: System automatically suspends manual-mode keys whose paid date has elapsed, once per day, at a configurable operator-timezone time.
- FR19: System preserves suspended keys indefinitely; no data-deletion is automatic.
- FR20: System automatically restores a key to active status once its paid date is extended, with propagation time bounded by the auth cache behavior.

**API Authentication and Rate Limiting (FR21–FR29)**

- FR21: Customer can authenticate HTTP requests to `/v1/audio/speech` using a Bearer API key.
- FR22: System validates an incoming Bearer key against an immutably-hashed copy stored in the registry, never storing or comparing the plaintext.
- FR23: System caches valid authorizations to satisfy the NFR1 auth-path latency target for repeat requests from the same key.
- FR24: System enforces a per-key rate limit derived at request time from the specific key's configured limit.
- FR25: System enforces a per-IP rate limit applied independently of auth outcome, so failed auth attempts are bounded.
- FR26: System equalizes the timing of key-lookup operations so that an attacker cannot distinguish a hash hit from a miss by wall-clock observation.
- FR27: System can operate in a legacy single-API-key mode when the monetization toggle is disabled, preserving compatibility with pre-2.0.0 deployments.
- FR28: System returns a distinct 401 error envelope for suspended and revoked keys that directs the customer to their operator's billing contact.
- FR29: System preserves the request and response contract of `/v1/audio/speech` and `/health` identically to Comadre 1.6.2, so existing customer integrations continue to function without modification.

**Observability and Auditing (FR30–FR34)**

- FR30: System records every customer and key mutation to an append-only audit log with actor identity, action, target, and timestamp.
- FR31: System records every cron-initiated suspension or reactivation event to the audit log.
- FR32: Operator can view the audit tail for any customer or key directly from the CLI.
- FR33: System maintains in-memory per-key request counters (total, rate-limit rejections, peak throughput, average throughput) for short-term troubleshooting; counters are not durable and reset on service restart.
- FR34: Operator can query overall system health (cron liveness, database integrity, auth cache state, backup recency) with a single command.

**Data Privacy and LGPD Compliance (FR35–FR39)**

- FR35: System encrypts CPF and CNPJ values at rest, with encryption material supplied by the deploy environment.
- FR36: Operator can rotate the encryption material by re-encrypting every protected field atomically, without a window in which data is unreadable.
- FR37: System prevents personal data (CPF, CNPJ, API-key plaintext) from appearing in structured log messages regardless of log verbosity.
- FR38: System preserves audit-log metadata (who, when, what) after a customer's personal data is purged, so operator activity remains traceable without retaining personal data.
- FR39: Operator receives a `docs/monetization.md` section "LGPD Operator Obligations" containing: (a) a breach-notification runbook with ANPD contact information, a customer-notification email template, an evidence-preservation checklist, and an internal escalation path; (b) a privacy-policy template paragraph the operator can adapt for their own terms of service.

**Operational Safety (FR40–FR45)**

- FR40: System can back up the key registry and encryption material nightly, in a single encrypted archive separate from the database file itself.
- FR41: Operator can restore the key registry from a prior backup via a dedicated, idempotent playbook.
- FR42: System enforces strict file permissions on the SQLite database file and the encryption key material at deploy time, and the health command reports deviations.
- FR43: System runs the daily suspension sweep at a fixed operator-timezone time and makes the last successful run timestamp queryable.
- FR44: System can operate safely across multiple Comadre replicas reading and writing the same SQLite file without corruption under normal operational load.
- FR45: Operator can query auth-cache propagation behavior via a dedicated CLI command; immediate cross-replica cache invalidation is not supported in MVP. The 60-second auth-cache TTL (NFR6) is the worst-case propagation bound. The CLI command documents this bound and reports cache-health information; it performs no cache mutation.

**Security Regression Prevention (FR46–FR52)**

- FR46: CI can verify that every security header required by the Caddy configuration (HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, upgrade-insecure-requests) is present on every response code returned by the reverse proxy.
- FR47: CI can verify that `/docs`, `/redoc`, and `/openapi.json` return 404 in production-configured deployments.
- FR48: CI can verify that the auth path uses timing-safe comparison primitives exclusively and never string equality.
- FR49: CI can verify that oversized request bodies are rejected at the reverse-proxy layer before reaching the application.
- FR50: CI can verify that the rate-limit middleware is registered and actually applies to both the speech and health endpoints.
- FR51: CI can verify that no new code raises a raw `HTTPException`; every error path uses a `ComadreError` subclass.
- FR52: Operator can verify via the existing `health.yml` Ansible playbook that UFW, SQLite permissions, cron jobs, and backup playbook outputs are in their expected state, with a clear exit code on any deviation.

### NonFunctional Requirements

**Performance (NFR1–NFR7)**

- NFR1: Auth-path overhead for a cache-hit request must stay under 5 ms at p99, measured against a 1,000-customer database.
- NFR2: Auth-path overhead for a cache-miss request must stay under 15 ms at p99, measured against a 1,000-customer database.
- NFR3: The daily suspension cron sweep must complete under 1 second for 1,000 active keys.
- NFR4: CLI list-class commands must render the first screenful of output in under 200 ms for a 1,000-customer database.
- NFR5: CLI detail-class commands must complete in under 500 ms for the same database size.
- NFR6: The auth cache TTL must not exceed 60 seconds; reactivation of a newly-paid key must become visible within that window at the latest.
- NFR7: Monetization-related code paths must not add more than 2 ms p99 to the existing `/v1/audio/speech` post-auth request pipeline.

**Security (NFR8–NFR17)**

- NFR8: API-key plaintext must be displayed to the operator at most once (at creation or rotation time) and never persist anywhere other than the operator's terminal scrollback.
- NFR9: API-key values must be stored in the registry as SHA-256 (or stronger) hashes.
- NFR10: CPF and CNPJ values must be encrypted at rest using Fernet (or a stronger authenticated-encryption primitive).
- NFR11: All key-comparison operations must use timing-safe primitives (`hmac.compare_digest` or equivalent).
- NFR12: Unsuccessful auth attempts must return in constant time regardless of whether the key hash matched a stored record.
- NFR13: The SQLite database file must have filesystem mode `0600` owned by the Comadre service user.
- NFR14: Backup archives must have filesystem mode `0600` and include the encryption key separately encrypted from the database payload.
- NFR15: No structured log message, at any log level, may contain a plaintext API key, a decrypted CPF, a decrypted CNPJ, or an `Authorization` header value.
- NFR16: No HTTP response body or `hint` field may echo the content of a customer-supplied invalid value.
- NFR17: All controls enumerated in the non-regression contract must remain satisfied on every PR merged to master.

**Reliability & Availability (NFR18–NFR24)**

- NFR18: Comadre 2.0.0 must preserve Comadre 1.6.2's latency SLA (≤10s great, 10–90s natural WhatsApp pace, >90s stressed).
- NFR19: The auth path must have zero external dependencies at request time.
- NFR20: The key registry must tolerate unclean shutdown without corruption.
- NFR21: Backup RTO: restore-keys.yml must restore a full key registry from a nightly backup in under 10 minutes for under 10,000 customers.
- NFR22: Backup RPO: data loss from a catastrophic VPS failure must not exceed 24 hours.
- NFR23: The daily suspension cron must not block concurrent auth-path reads during the sweep.
- NFR24: A Comadre replica restart must not cause any outage longer than the existing warm-up window (≤60s).

**Scalability (NFR25–NFR29)**

- NFR25: A single Comadre shard must support at least 1,000 active customers and 2,000 active keys without violating performance NFRs.
- NFR26: Scaling beyond a single shard is operator-driven: additional VPS provisioned independently.
- NFR27: Per-shard memory overhead added by monetization must stay under 50 MB above the baseline 1.6.2 footprint.
- NFR28: Disk-usage growth from monetization must stay under 50 MB for the first 6 months of typical use.
- NFR29: Multi-replica deployments must operate without corruption under normal load.

**Compatibility (NFR30–NFR33)**

- NFR30: The public `/v1/audio/speech` and `/health` request/response contracts must remain byte-identical to Comadre 1.6.2.
- NFR31: The legacy single-API_KEY auth mode must preserve every behavior of 1.6.2 exactly.
- NFR32: Ansible playbooks must remain idempotent.
- NFR33: The `comadre-keys` CLI must be backward-compatible within a major version.

**Compliance (NFR34–NFR37)**

- NFR34: LGPD data-subject access requests must be fulfillable in under 15 days using the `export-customer` command.
- NFR35: LGPD right-to-deletion requests must be fulfillable in under 15 days using the `delete-customer --hard` command; the command completes in under 1 second.
- NFR36: LGPD breach notification: a runbook in `docs/monetization.md` must document the operator's notification duty.
- NFR37: CDC compliance: the suspended-but-not-deleted key contract guarantees historical data is not destroyed.

### Additional Requirements

**From Architecture:**

- Brownfield extension — no starter template. Extend existing codebase in-place within `src/comadre/`.
- New dependencies: `typer` >=0.12, `cryptography` >=43.0, `cachetools`, `python-ulid`. Added via `uv add`.
- New `keys/` subpackage under `src/comadre/` with `cli/` sub-package for the Typer app.
- SQLite connection management: app-state singleton (FastAPI lifespan) + per-invocation connection (CLI). WAL mode enforced at creation.
- Auth cache: `cachetools.TTLCache(maxsize=4096, ttl=60)` keyed by SHA-256 hash of bearer token. Cache value is `AuthPayload` dataclass.
- Schema migration: `schema_version` table with sequential `.sql` migration files in `keys/migrations/`.
- Cron implementation: host crontab calling CLI directly (not in-container). Installed by `bootstrap.yml`.
- SQLite file location: bind mount `./data/keys:/keys:rw` (Gap 2 resolution — not a named Docker volume). Host path `~/comadre/data/keys/registry.db`.
- ID generation: ULID with typed prefix (`cust_` + ULID, `key_` + ULID) via `python-ulid`.
- API key format: `cmdr_live_` + `secrets.token_urlsafe(32)`. Stored prefix: first 8 chars after `cmdr_live_`.
- Dual-mode auth: conditional inside `verify_api_key()` gated by `monetization_enabled` boolean.
- Cache invalidation model: no mutation in MVP. `cache-status` CLI (renamed from `cache-flush`) reports the 60-second auth-cache TTL propagation bound and cache-health telemetry; it does not force invalidation. Operators needing faster propagation restart the affected replica(s).
- BillingProvider ABC with 3 methods (`is_payment_current`, `on_key_issued`, `on_key_revoked`). Only `ManualBillingProvider` in MVP.
- Import graph downward-only: `config/logging` → `exceptions/schemas` → `keys/models` → `keys/crypto` → `keys/db` → `keys/audit` → `keys/billing` → `keys/cache` → `keys/auth` → `rate_limit` → `api/health` → `main`. CLI has its own entry point.
- New ComadreError subclasses: `ApiKeyNotFoundError`, `ApiKeySuspendedError`, `ApiKeyRevokedError`, `InvalidTaxIdError`, `KeyRegistryError`.
- New settings fields in `config.py`: `monetization_enabled`, `key_registry_db_path`, `key_registry_encryption_key` (SecretStr), `operator_contact_hint`, `billing_day`, `billing_timezone`.
- CLI entry point: `pyproject.toml` → `[project.scripts]` → `comadre-keys = "comadre.keys.cli.app:main"`. Installed system-wide via `uv tool install`.
- All naming conventions (DB tables, IDs, audit actions, CLI commands) defined in architecture patterns section.
- Implementation sequence: models+crypto → db+audit+migrations → cache → billing → auth → config+exceptions extensions → rate_limit extension → main extension → cli → ansible+cron+docs.

### UX Design Requirements

- UX-DR1: KeyPanel component — industry-standard three-piece layout (warning Panel + naked plaintext line + context Panel; see `ux-design-specification.md` §KeyPanel) for one-shot key display at `issue-key` and `rotate-key`. Key plaintext is deliberately OUTSIDE any panel (column 0, no leading whitespace, no wrap) for triple-click copy fidelity. Includes "Copy now — shown only once" warning, prefix, RPM, price (pt-BR locale: `R$ 1.234,56`), billing mode, first charge date. Complimentary variant shows "R$ 0,00 (bundled externally)" and "paid_until: — (not applicable)".
- UX-DR2: StatusTable component — `rich.Table` with color-coded status badges for `list-keys`, `list-customers`, `at-risk`. Columns follow invariant order: identifier → name → status → billing fields → dates. Max 7 columns at 80-col width. Row count shown below. Table title reflects applied filter.
- UX-DR3: DetailPanel component — single-border `rich.Panel` with labeled key-value pairs for `show`. Labels right-padded to longest label width. Key detail variant: prefix, customer, status, RPM, price, billing, paid until, created, last used, age, notes. Customer detail variant: ID, name, email, tax ID kind, key count, registered, notes.
- UX-DR4: RevenueReport component — single-border `rich.Panel` with `Rule()` separators and `[bold]` totals for `revenue`. Shows paid/pending/suspended/complimentary counts, MRR, projected total, next charge date. Complimentary keys listed separately with notes.
- UX-DR5: AuditTail component — chronological event list (newest first) appended below DetailPanel for `show --audit-tail N`. Each line: timestamp, event type, actor, optional details. Indented 2 spaces. "No events recorded" for empty state.
- UX-DR6: ErrorDisplay component — red single-border `rich.Panel` on stderr. Error message as panel title, hint as panel body. Used for all error conditions. Exit code non-zero per exit code table.
- UX-DR7: ConfirmationLine component — single-line `Console.print()` on stdout for routine mutations (`mark-paid`, `suspend`, `reactivate`, `update-key`). Format: "Action verb: prefix (Name) → relevant detail". No panel, no border, no blank lines.
- UX-DR8: 4-color semantic palette enforced consistently: green=active/success/paid, yellow=suspended/warning/pending, red=revoked/error/overdue, blue=complimentary/info. Color always paired with text label, never color-only. No background colors. No bold on status badges.
- UX-DR9: Shared `rich.Console` instance used by all commands. Stderr console for errors. `NO_COLOR` env var and `--no-color` flag compliance. `force_terminal=True` never set.
- UX-DR10: Structured exit codes: 0=success (including empty results), 1=general, 2=usage, 3=not-found, 4=validation, 5=database, 6=permission.
- UX-DR11: Destructive command confirmation pattern — `--yes` flag to skip interactive confirmation. Default is "No" (`[y/N]`). Applies to: `delete-customer --hard`, `revoke-key`, `rotate-encryption-key`.
- UX-DR12: Empty results are not errors — informational text message, exit code 0. No error panel for empty query results.
- UX-DR13: First-run empty state includes hint with next command to run. Subsequent empty states omit the hint.
- UX-DR14: Cross-command navigation — each command prints identifiers needed by the next likely command (`create-customer` prints customer ID, `issue-key` prints prefix, `at-risk` prints prefixes).
- UX-DR15: `--help` per command includes a realistic example with real-looking values, not abstract placeholders.
- UX-DR16: Terminal width adaptation — 80-col minimum. At <80, abbreviate column headers (e.g., "Customer" → "Cust."). Never drop status or identifier columns.
- UX-DR17: Copy-paste fidelity for key plaintext — must be selectable via triple-click without grabbing border characters.
- UX-DR18: Warning display pattern — warnings are inline text on stderr, before primary output, not in panels. Used for non-fatal conditions (e.g., RPM exceeds VPS tier).

### FR Coverage Map

| FR | Epic | Description |
|---|---|---|
| FR1 | 1 | Register customer with name, email, CPF/CNPJ |
| FR2 | 1 | Reject invalid CPF/CNPJ checksum |
| FR3 | 1 | Attach/append notes to customer |
| FR4 | 1 | Update customer email and notes |
| FR5 | 4 | LGPD hard-delete customer + keys + personal data |
| FR6 | 4 | LGPD export customer data |
| FR7 | 1 | List customers with tombstone filter |
| FR8 | 1 | Issue API key with RPM and price |
| FR9 | 1 | Issue complimentary API key |
| FR10 | 1 | Update key RPM, price, notes |
| FR11 | 1 | Rotate key (new plaintext, same ID) |
| FR12 | 1 | Revoke key with reason |
| FR13 | 1 | List keys with filters |
| FR14 | 1 | Show full key context + audit tail |
| FR15 | 3 | Mark key as paid through date |
| FR16 | 3 | Query at-risk keys by look-ahead window |
| FR17 | 3 | Revenue report with paid/pending/suspended/complimentary |
| FR18 | 3 | Auto-suspend expired manual-mode keys daily |
| FR19 | 3 | Preserve suspended keys indefinitely |
| FR20 | 3 | Auto-restore key after paid_until extended |
| FR21 | 2 | Bearer key authentication on /v1/audio/speech |
| FR22 | 2 | Validate key against SHA-256 hash |
| FR23 | 2 | Cache valid authorizations (TTLCache) |
| FR24 | 2 | Per-key dynamic rate limit |
| FR25 | 2 | Per-IP rate limit on failed auth |
| FR26 | 2 | Timing-equalized key lookup |
| FR27 | 2 | Legacy single-API_KEY mode toggle |
| FR28 | 2 | Distinct 401 for suspended/revoked with operator hint |
| FR29 | 2 | Preserve /v1/audio/speech and /health contracts |
| FR30 | 1 | Append-only audit log for all mutations |
| FR31 | 3 | Audit log for cron suspension/reactivation events |
| FR32 | 1 | CLI audit tail for any customer or key |
| FR33 | 2 | In-memory per-key request counters |
| FR34 | 3 | System health command (cron, DB, cache, backup) |
| FR35 | 1 | Encrypt CPF/CNPJ at rest with Fernet |
| FR36 | 4 | Rotate encryption key with atomic re-encryption |
| FR37 | 1 | Prevent personal data in logs |
| FR38 | 4 | Preserve audit metadata after customer purge |
| FR39 | 4 | LGPD obligations section in docs/monetization.md |
| FR40 | 4 | Nightly backup of registry + encryption key |
| FR41 | 4 | Restore from backup via idempotent playbook |
| FR42 | 4 | Enforce file permissions + health check deviation reporting |
| FR43 | 3 | Suspension sweep at fixed operator-TZ time, timestamp queryable |
| FR44 | 4 | Multi-replica SQLite safety (WAL) |
| FR45 | 2 | Report auth-cache TTL propagation bound via `cache-status` CLI (read-only) |
| FR46 | 4 | CI: verify security headers on all responses |
| FR47 | 4 | CI: verify /docs /redoc /openapi.json return 404 |
| FR48 | 4 | CI: verify timing-safe comparison only |
| FR49 | 4 | CI: verify oversized request body rejection |
| FR50 | 4 | CI: verify rate-limit middleware registered |
| FR51 | 4 | CI: verify no raw HTTPException |
| FR52 | 4 | Ansible health.yml verifies UFW, permissions, cron, backup |

## Epic List

### Epic 1: Key Registry & Customer Management
The operator can register customers (with validated, encrypted CPF/CNPJ), issue API keys, manage the full customer/key lifecycle, and view audit history — all from the CLI over SSH. This is the foundation layer that enables the "primeira venda" moment (Journey 1).
**FRs covered:** FR1–FR4, FR7–FR14, FR30, FR32, FR35, FR37

### Epic 2: API Authentication & Dynamic Rate Limiting
Customers authenticate HTTP requests with their per-customer API keys. Each key enforces its own rate limit. Legacy single-key mode is preserved when monetization is disabled. Suspended/revoked keys get clear error envelopes directing the customer to their operator. Enables Journey 4 (Customer API Integration) and Journey 5 (Debug Session).
**FRs covered:** FR21–FR29, FR33, FR45
**Depends on:** Epic 1

### Epic 3: Billing & Revenue Operations
The operator can track payments, auto-suspend non-payers via daily cron, view revenue reports with paid/pending/projected breakdown, manage complimentary subscriptions, and query system health. Enables Journey 2 (Monthly Billing Ritual), Journey 3 (Delinquent Customer), and Journey 6 (Complimentary Subscription).
**FRs covered:** FR15–FR20, FR31, FR34, FR43
**Depends on:** Epic 1

### Epic 4: Security Hardening, LGPD & Operational Safety
The operator can fulfill LGPD obligations (data export, hard deletion, breach notification), back up and restore the key registry, rotate encryption keys, and trust that the full non-regression security contract holds across every PR. Ensures compliance and operational resilience.
**FRs covered:** FR5, FR6, FR36, FR38, FR39, FR40–FR42, FR44, FR46–FR52
**Depends on:** Epics 1–3

## Epic 1: Key Registry & Customer Management

The operator can register customers (with validated, encrypted CPF/CNPJ), issue API keys, manage the full customer/key lifecycle, and view audit history — all from the CLI over SSH. This is the foundation layer that enables the "primeira venda" moment (Journey 1).

### Story 1.1: Customer Registration with CPF/CNPJ Validation

As an operator,
I want to register a new customer with validated CPF/CNPJ via CLI,
So that I can start onboarding paying customers with proper tax-ID verification and encryption.

**Covers:** FR1, FR2, FR35, FR37, FR30 (foundation)
**UX-DRs:** UX-DR6, UX-DR7, UX-DR9, UX-DR10, UX-DR14

**Scope:** Establishes the entire foundation layer. Creates the `keys/` subpackage, adds dependencies to `pyproject.toml` (typer, cryptography, python-ulid), extends `config.py` with monetization settings, adds `InvalidTaxIdError` and `KeyRegistryError` to `exceptions.py`, implements models, crypto (CPF/CNPJ validation + Fernet), db (connection management, schema migration, v001 SQL creating all tables), audit log, CLI app with `create-customer`, and the ErrorDisplay + ConfirmationLine output components.

**Acceptance Criteria:**

**Given** an operator has SSH access to the VPS and `comadre-keys` is installed
**When** they run `comadre-keys create-customer --name "Helena Ribeiro" --email "helena@clinica.com" --cpf "123.456.789-00"`
**Then** the system validates the CPF checksum, encrypts it with Fernet, stores the customer with a `cust_` + ULID ID, and prints `Customer created: cust_01... (Helena Ribeiro)`
**And** the audit log records a `create_customer` event with actor `cli:<shell-user>`

**Given** an operator provides a CNPJ instead of CPF
**When** they run `comadre-keys create-customer --name "Empresa LTDA" --email "fin@empresa.com" --cnpj "12.345.678/0001-90"`
**Then** the system validates the CNPJ checksum (14-digit, 2 verification digits), encrypts it, and stores with `tax_id_kind=cnpj`

**Given** an operator provides both `--cpf` and `--cnpj`
**When** the command is executed
**Then** Typer rejects the command with a usage error (exit code 2) before any database operation

**Given** an operator provides an invalid CPF (bad checksum)
**When** the command is executed
**Then** the system displays a red-bordered ErrorDisplay panel on stderr with the message "Invalid CPF: checksum verification failed" and a hint "Verify the CPF digits and try again." and exits with code 4
**And** the invalid CPF value is never echoed in the error message or logged (FR37, NFR16)

**Given** `KEY_REGISTRY_ENCRYPTION_KEY` is not set in `.env`
**When** the operator tries to run any `comadre-keys` command
**Then** pydantic-settings raises a validation error with a clear message about the missing required setting

**Given** the SQLite database does not exist yet
**When** `create-customer` is the first command ever run
**Then** the system creates the database file, runs v001 migration (creates all tables + indexes), enforces WAL mode, and proceeds with the customer creation

**Given** the database already exists at the configured path
**When** `create-customer` is run
**Then** the system checks the schema version, skips migration if current, and proceeds normally

### Story 1.2: API Key Issuance

As an operator,
I want to issue an API key for a customer and see the plaintext exactly once,
So that I can deliver the key to my customer via WhatsApp and start earning revenue.

**Covers:** FR8, FR9, FR30
**UX-DRs:** UX-DR1, UX-DR8, UX-DR14, UX-DR17

**Acceptance Criteria:**

**Given** a customer `cust_01HF3...` exists
**When** the operator runs `comadre-keys issue-key --customer cust_01HF3... --rpm 60 --price 149`
**Then** the system generates a `cmdr_live_` + `secrets.token_urlsafe(32)` key, stores the SHA-256 hash + 8-char prefix, and displays a double-border KeyPanel on stdout containing: the plaintext key on its own line (copy-friendly, no leading whitespace), "Copy now — shown only once" warning, prefix, RPM, price, billing mode (manual), and first charge date (next day `BILLING_DAY`)
**And** the plaintext key is never stored in the database, logs, or cache
**And** the audit log records an `issue_key` event

**Given** the operator issues a complimentary key
**When** they run `comadre-keys issue-key --customer cust_01... --rpm 120 --billing-mode complimentary --notes "included in infra bundle"`
**Then** the KeyPanel shows `billing mode: complimentary`, `price: R$ 0,00 (bundled externally)` (pt-BR comma-decimal), `paid_until: — (not applicable)`
**And** `price_monthly` is stored as `0.0` and `paid_until` is stored as NULL

**Given** the referenced customer ID does not exist
**When** `issue-key` is run
**Then** the system displays an ErrorDisplay panel with "Customer not found" and exits with code 3

**Given** the key plaintext is displayed in the KeyPanel
**When** the operator triple-clicks the key line in the terminal
**Then** only the key plaintext is selected — no border characters, no labels, no trailing whitespace

### Story 1.3: Customer & Key Listing

As an operator,
I want to list my customers and their keys with color-coded status,
So that I can see my portfolio at a glance and filter by status or billing state.

**Covers:** FR7, FR13
**UX-DRs:** UX-DR2, UX-DR12, UX-DR13, UX-DR16

**Acceptance Criteria:**

**Given** the operator has registered customers
**When** they run `comadre-keys list-customers`
**Then** the system displays a `rich.Table` with columns: customer ID, name, email, key count, registered date
**And** the table title shows "Customers" and a row count below (e.g., "3 customers found")

**Given** no customers exist yet (first-run state)
**When** they run `comadre-keys list-customers`
**Then** the system prints "No customers registered yet." followed by a hint: `comadre-keys create-customer --name "Name" --email "email@example.com" --cpf "000.000.000-00"`
**And** exits with code 0 (not an error)

**Given** keys exist with various statuses
**When** the operator runs `comadre-keys list-keys`
**Then** the system displays a StatusTable with columns: prefix, customer name, status (color-coded: green=active, yellow=suspended, red=revoked, blue=complimentary), price, paid until
**And** status badges always include the text label alongside color (never color-only)

**Given** the operator wants to filter keys
**When** they run `comadre-keys list-keys --status suspended` or `--billing-mode complimentary` or `--customer cust_01...`
**Then** only matching keys are shown, the table title reflects the filter (e.g., "Suspended Keys"), and empty results show an informational message (not an error panel)

**Given** the operator wants machine-readable output
**When** they run `comadre-keys list-keys --format json`
**Then** the output is valid JSON on stdout with no rich formatting, and any errors remain on stderr

**Given** the operator includes `--deleted` on `list-customers`
**When** executed
**Then** tombstone records (where `deleted_at` is not NULL) are included in the listing

**Given** the terminal is 80 columns wide
**When** any `list-*` command is executed
**Then** the table is readable without horizontal scrolling, with max 7 columns

### Story 1.4: Key & Customer Detail View with Audit Trail

As an operator,
I want to view full context for a key or customer including recent audit events,
So that I can answer customer questions and troubleshoot issues in a single command.

**Covers:** FR14, FR32
**UX-DRs:** UX-DR3, UX-DR5

**Acceptance Criteria:**

**Given** a key with prefix `cmdr_Pq` exists
**When** the operator runs `comadre-keys show cmdr_Pq`
**Then** the system displays a single-border DetailPanel with: prefix, customer name (+ customer ID), status (color-coded), RPM, price, billing mode, paid until, created date, last used date, age, notes
**And** labels are right-padded to the longest label in the panel

**Given** the operator wants audit history
**When** they run `comadre-keys show cmdr_Pq --audit-tail 20`
**Then** the DetailPanel is followed by a chronological list (newest first) of the last 20 audit events for that key, each showing: timestamp, event type, actor
**And** if fewer than 20 events exist, all are shown

**Given** the operator shows a customer by ID
**When** they run `comadre-keys show cust_01HF3...`
**Then** the system displays a DetailPanel with: ID, name, email, tax ID kind (CPF/CNPJ — not the decrypted value), key count, registered date, notes

**Given** the prefix or ID does not match any record
**When** `show` is run
**Then** the system displays an ErrorDisplay panel with "not found" message and exits with code 3

**Given** no audit events exist for a key
**When** `show --audit-tail 10` is run
**Then** the audit section shows "No events recorded" as a single line

### Story 1.5: Customer Updates & Notes

As an operator,
I want to update a customer's email or append notes,
So that I can keep customer records current and add operational annotations.

**Covers:** FR3, FR4
**UX-DRs:** UX-DR7

**Acceptance Criteria:**

**Given** a customer `cust_01HG7...` exists
**When** the operator runs `comadre-keys update-customer cust_01HG7... --email "new@email.com"`
**Then** the email is updated and a ConfirmationLine is printed: `Updated: cust_01HG7... (Marcos Silva) — email changed`
**And** the audit log records an `update_customer` event

**Given** the operator wants to add a note
**When** they run `comadre-keys update-customer cust_01HG7... --add-note "pays late - remind day 3"`
**Then** the note is appended (not overwritten) to the existing notes field with a timestamp prefix
**And** the ConfirmationLine confirms the note addition

**Given** the customer ID does not exist
**When** `update-customer` is run
**Then** ErrorDisplay panel, exit code 3

### Story 1.6: Key Lifecycle (Update, Rotate, Revoke)

As an operator,
I want to update key parameters, rotate a compromised key, and revoke keys when contracts end,
So that I can manage the full key lifecycle without creating new records.

**Covers:** FR10, FR11, FR12
**UX-DRs:** UX-DR1, UX-DR7, UX-DR11, UX-DR15, UX-DR18

**Acceptance Criteria:**

**Given** a key with prefix `cmdr_Pq` exists
**When** the operator runs `comadre-keys update-key cmdr_Pq --rpm 120 --price 199`
**Then** the RPM and price are updated, a ConfirmationLine is printed: `Updated: cmdr_Pq (Helena Ribeiro) — rpm: 60→120, price: R$ 149,00→R$ 199,00` (pt-BR comma-decimal)
**And** the audit log records an `update_key` event

**Given** a key needs rotation (compromised or requested)
**When** the operator runs `comadre-keys rotate-key cmdr_Pq`
**Then** a new plaintext key is generated (same `key_` ID, same customer), the old hash is replaced, and a double-border KeyPanel displays the new plaintext with "Copy now — shown only once"
**And** the old key stops working immediately (hash no longer matches)
**And** the audit log records a `rotate_key` event

**Given** a contract ends and the key must be permanently disabled
**When** the operator runs `comadre-keys revoke-key cmdr_Pq --reason "bundle contract ended 2026-09-30"`
**Then** the system prompts for confirmation: "This will permanently revoke key cmdr_Pq. Continue? [y/N]:" (default No)
**And** on confirmation, status changes to `revoked`, the reason is stored, and a ConfirmationLine is printed
**And** the audit log records a `revoke_key` event with the reason

**Given** the operator uses `--yes` to skip confirmation
**When** they run `comadre-keys revoke-key cmdr_Pq --reason "..." --yes`
**Then** the revocation proceeds without prompting

**Given** every command in this story
**When** `--help` is passed
**Then** usage includes a realistic example with real-looking values

## Epic 2: API Authentication & Dynamic Rate Limiting

Customers authenticate HTTP requests with their per-customer API keys. Each key enforces its own rate limit. Legacy single-key mode is preserved when monetization is disabled. Suspended/revoked keys get clear error envelopes directing the customer to their operator.

### Story 2.1: Registry-Based API Authentication

As a customer (API consumer),
I want to authenticate with my per-customer API key,
So that my requests are validated against the key registry with minimal latency.

**Covers:** FR21, FR22, FR23, FR26, FR27, FR28, FR29
**NFRs:** NFR1, NFR2, NFR7, NFR11, NFR12

**Scope:** Adds `cachetools` dependency. Creates `keys/cache.py` (TTLCache wrapper), `keys/auth.py` (verify_api_key_registry). Modifies `api.py` (dual-mode `verify_api_key`), `main.py` (lifespan: DB init, cache init, migration check). The auth cache stores `AuthPayload` dataclass keyed by SHA-256 hash. Dual-mode switching gated by `monetization_enabled`.

**Acceptance Criteria:**

**Given** `monetization_enabled=true` and a valid active key exists in the registry
**When** a customer sends `POST /v1/audio/speech` with `Authorization: Bearer cmdr_live_KQjP...`
**Then** the system hashes the token with SHA-256, checks the TTLCache (maxsize=4096, ttl=60), on miss queries SQLite by `key_hash`, caches the `AuthPayload`, validates `status=active` and `paid_until >= today` (for manual billing), and allows the request
**And** the response is byte-identical to Comadre 1.6.2 (FR29)

**Given** the same key is used again within 60 seconds
**When** the second request arrives
**Then** the cache-hit path resolves the auth in under 5ms p99 (NFR1) without touching SQLite

**Given** `monetization_enabled=false` (default)
**When** a request arrives with `Authorization: Bearer <token>`
**Then** the legacy single-API_KEY `hmac.compare_digest` path executes exactly as in 1.6.2 (FR27)
**And** no SQLite lookup occurs, no cache is consulted

**Given** a key is suspended (`status=suspended`)
**When** a request arrives with that key
**Then** the system returns 401 with `{"error": {"message": "...", "type": "authentication_error", "hint": "Your API key has been suspended. Contact your Comadre operator for billing resolution."}}` (FR28)
**And** the `hint` includes the value from `OPERATOR_CONTACT_HINT` if configured

**Given** a key hash is not found in the registry
**When** a request arrives with an unknown token
**Then** the system performs `hmac.compare_digest(hash, dummy_hash)` for timing equalization (FR26) and returns 401 with the standard auth-error envelope — indistinguishable from the suspended-key 401 at the rate-limit layer

**Given** the SQLite database is unreachable or corrupt
**When** a cache-miss triggers a DB lookup
**Then** the system raises `KeyRegistryError(500)`, logs at ERROR level, and fails closed (denies access)

**Given** `/health` is called with a valid customer key
**When** `monetization_enabled=true`
**Then** authenticated detail is returned (same contract as 1.6.2, FR29)

### Story 2.2: Dynamic Per-Key Rate Limiting

As an operator,
I want each API key to enforce its own rate limit,
So that customers who pay for higher throughput get it, and the VPS capacity is distributed fairly.

**Covers:** FR24, FR25
**NFRs:** NFR7

**Acceptance Criteria:**

**Given** `monetization_enabled=true` and a key has `rate_limit_rpm=60`
**When** the customer sends 61 requests in a rolling 1-minute window
**Then** the 61st request receives 429 with `Retry-After` header
**And** the rate limit is keyed by the API key hash (not by IP)

**Given** `monetization_enabled=true` and a key has `rate_limit_rpm=120`
**When** the same customer sends 120 requests in a minute
**Then** all 120 succeed; the 121st is throttled

**Given** an auth attempt fails (invalid key)
**When** the request is rate-limited
**Then** the per-IP rate limit applies (existing `RATE_LIMIT_SPEECH` default 30/min), since no key was resolved
**And** the per-IP limit is independent of per-key limits (FR25)

**Given** `monetization_enabled=false`
**When** rate limiting is evaluated
**Then** slowapi uses the existing per-IP static limit from `RATE_LIMIT_SPEECH` (1.6.2 behavior)

**Given** the monetization code paths are active
**When** measured at p99
**Then** the post-auth pipeline adds no more than 2ms to request processing (NFR7)

### Story 2.3: Request Counters & Cache Management

As an operator,
I want in-memory per-key request counters and a cache-management command,
So that I can troubleshoot rate-limit issues and understand cache behavior.

**Covers:** FR33, FR45

**Acceptance Criteria:**

**Given** requests are flowing through the auth path
**When** the system processes requests for a key
**Then** in-memory counters track: total requests, rate-limit rejections (429 count), peak RPM, and average RPM per key
**And** counters reset on service restart (not durable)

**Given** the counters are active
**When** the operator runs `comadre-keys show <prefix> --audit-tail 20`
**Then** the last-24h stats section includes: requests total, auth success, rate_limit_429, peak RPM, average RPM (if available from the running instance)

**Given** the operator wants to inspect auth-cache propagation behavior
**When** they run `comadre-keys cache-status`
**Then** the system prints a human-readable message reporting the 60-second auth-cache TTL propagation bound (e.g., "Auth cache propagation bound: 60 seconds. Key-state changes become visible to the API within this window. This command does not force invalidation; to empty the cache faster, restart the affected replica(s).") and, when practical, cache-health telemetry such as entry count and hit rate
**And** exits with code 0
**And** performs no cache mutation (architecture decision: MVP does not support forced invalidation; the 60-second TTL is the worst-case propagation bound, per FR45)

**Given** the operator wants machine-readable cache telemetry
**When** they run `comadre-keys cache-status --format json`
**Then** the output is valid JSON containing at minimum the `ttl_seconds` field (value 60); additional fields (`entries`, `hit_rate`) are emitted when the running instance can produce them

## Epic 3: Billing & Revenue Operations

The operator can track payments, auto-suspend non-payers via daily cron, view revenue reports with paid/pending/projected breakdown, manage complimentary subscriptions, and query system health.

### Story 3.1: Payment Tracking (mark-paid, suspend, reactivate)

As an operator,
I want to confirm payments, manually suspend keys, and reactivate them,
So that I can run the monthly billing ritual in under 5 minutes.

**Covers:** FR15, FR19, FR20
**UX-DRs:** UX-DR7

**Acceptance Criteria:**

**Given** a manual-mode key with prefix `cmdr_Pq` is active
**When** the operator runs `comadre-keys mark-paid cmdr_Pq --until 2026-06-05`
**Then** `paid_until` is updated to `2026-06-05`, a ConfirmationLine prints: `Marked paid: cmdr_Pq (Pedro Lopes) → paid until 2026-06-05`, and the command completes in under 200ms
**And** the audit log records a `mark_paid` event

**Given** a key is suspended (by cron or manually)
**When** the operator runs `comadre-keys mark-paid cmdr_Pq --until 2026-06-05`
**Then** `paid_until` is updated AND `status` changes from `suspended` to `active` (FR20)
**And** the key reactivates in the API within the 60s cache TTL

**Given** the operator needs to suspend a key out-of-cycle (abuse, contract dispute)
**When** they run `comadre-keys suspend cmdr_Pq`
**Then** `status` changes to `suspended`, ConfirmationLine prints confirmation
**And** the audit log records a `suspend_key` event with actor `cli:<shell-user>`

**Given** a suspended key needs manual reactivation without payment
**When** the operator runs `comadre-keys reactivate cmdr_Pq`
**Then** `status` changes to `active`, ConfirmationLine prints confirmation
**And** `paid_until` is NOT modified (the operator must separately run `mark-paid` if extending)

**Given** the key is complimentary (`billing_mode=complimentary`)
**When** `mark-paid` is run on it
**Then** the system displays an informational message: "Key cmdr_Pq is complimentary — no payment tracking required." and exits with code 0

**Given** suspended keys exist in the database
**When** time passes without any operator action
**Then** suspended keys are never auto-deleted (FR19) — they remain indefinitely until reactivated or revoked

### Story 3.2: At-Risk Queries & Revenue Reports

As an operator,
I want to preview upcoming expirations and see my monthly revenue,
So that I can proactively chase payments and track business growth.

**Covers:** FR16, FR17
**UX-DRs:** UX-DR2, UX-DR4

**Acceptance Criteria:**

**Given** keys with `paid_until` approaching within a look-ahead window
**When** the operator runs `comadre-keys at-risk --window 5d`
**Then** the system displays a StatusTable of keys whose `paid_until` falls within the next 5 days, showing: prefix, customer name, price, paid until, days left
**And** status badges show yellow for at-risk keys
**And** the table title shows "At-Risk Keys (next 5 days)"

**Given** no keys are at risk
**When** `at-risk --window 5d` is run
**Then** the system prints "No keys at risk in the next 5 days." and exits with code 0

**Given** the operator wants a revenue report
**When** they run `comadre-keys revenue --month current`
**Then** the system displays a single-border RevenueReport panel with: paid customer count, pending count, suspended (carry-over) count, complimentary count (not in MRR), horizontal separator, monthly recurring (paid) in bold, projected (if all pay) in bold, next charge date
**And** complimentary keys are listed separately with their notes
**And** complimentary keys are NEVER counted in MRR or projected revenue

**Given** the operator queries a historical month
**When** they run `comadre-keys revenue --month 2026-05`
**Then** the report shows the state as of that month based on payment records

**Given** the operator wants machine-readable output
**When** they run `comadre-keys revenue --month current --format json`
**Then** the output is valid JSON with all report fields

### Story 3.3: Automated Suspension Sweep & Cron

As an operator,
I want the system to auto-suspend non-payers daily without my intervention,
So that billing enforcement happens reliably even when I'm not at the terminal.

**Covers:** FR18, FR31, FR43
**NFRs:** NFR3, NFR23

**Acceptance Criteria:**

**Given** manual-mode keys exist where `paid_until < today`
**When** the operator runs `comadre-keys suspend-sweep` (or cron triggers it at 00:30 operator TZ)
**Then** the system executes a single `UPDATE api_key SET status='suspended' WHERE billing_mode='manual' AND paid_until < ? AND status='active'` with today's date
**And** complimentary keys (`billing_mode='complimentary'`) are never touched
**And** each suspended key gets an `audit_log` entry with actor `cron:suspension-sweep` (FR31)
**And** the sweep completes under 1 second for 1,000 keys (NFR3)

**Given** the cron runs while API requests are being served
**When** the sweep UPDATE executes
**Then** WAL mode ensures concurrent auth-path reads are not blocked (NFR23)

**Given** the sweep has run
**When** the timestamp is recorded
**Then** the last successful sweep timestamp is queryable by the `health` command (FR43)

**Given** bootstrap.yml runs on the VPS
**When** monetization is enabled
**Then** a cron entry `comadre-daily-suspension` is installed at 00:30 in the operator's configured `BILLING_TIMEZONE`
**And** the cron entry runs `comadre-keys suspend-sweep`
**And** cron output is captured in syslog

**Given** no keys are expired
**When** the sweep runs
**Then** zero rows are updated, the sweep still completes successfully (exit 0), and the timestamp is recorded

### Story 3.4: System Health Command

As an operator,
I want to query system health in a single command,
So that I can verify cron liveness, DB integrity, cache state, and backup recency.

**Covers:** FR34

**Acceptance Criteria:**

**Given** the system is running normally
**When** the operator runs `comadre-keys health`
**Then** the system displays a single-border panel showing: DB file path and size, DB permissions (0600 check), schema version, customer count, active/suspended/revoked key counts, last suspension sweep timestamp, cron job installed (yes/no), last backup timestamp (if backup file exists)
**And** exits with code 0

**Given** the DB file permissions have drifted from 0600
**When** `health` is run
**Then** the permissions field shows a warning (yellow) with the actual mode

**Given** the cron job is missing
**When** `health` is run
**Then** the cron field shows a warning: "Not installed"

**Given** the operator wants a machine-checkable result
**When** they run `comadre-keys health --format json`
**Then** the output is valid JSON and exits non-zero on any unhealthy condition

## Epic 4: Security Hardening, LGPD & Operational Safety

The operator can fulfill LGPD obligations (data export, hard deletion, breach notification), back up and restore the key registry, rotate encryption keys, and trust that the full non-regression security contract holds across every PR.

### Story 4.1: LGPD Data Operations (Export & Hard Delete)

As an operator,
I want to export a customer's data and irreversibly purge their record,
So that I can fulfill LGPD data-subject access and deletion requests within the legal timeframe.

**Covers:** FR5, FR6, FR38
**NFRs:** NFR34, NFR35
**UX-DRs:** UX-DR11

**Acceptance Criteria:**

**Given** a customer `cust_01HG7...` exists with encrypted CPF and associated keys
**When** the operator runs `comadre-keys export-customer cust_01HG7... --format json`
**Then** the system outputs a JSON document to stdout containing: customer ID, name, email, decrypted tax ID (CPF or CNPJ), tax ID kind, registered date, notes, and a list of all associated keys (prefix, status, billing mode, created date)
**And** the export completes in under 1 second regardless of database size (NFR35)

**Given** the operator needs YAML format
**When** they run `comadre-keys export-customer cust_01HG7... --format yaml`
**Then** the output is valid YAML with the same fields

**Given** the operator must fulfill a deletion request
**When** they run `comadre-keys delete-customer --hard cust_01HG7...`
**Then** the system prompts: "This will permanently delete customer Marcos Silva and all associated keys. This action cannot be undone. Encrypted tax ID will be purged. Continue? [y/N]:"
**And** on confirmation: the customer record's personal data (tax_id_encrypted, name, email) is purged, all associated keys are deleted, `deleted_at` is set (tombstone row preserved for listing with `--deleted`)
**And** the audit log retains event metadata (who, when, customer_id reference) but NO personal data (FR38)
**And** exit code 0

**Given** `--yes` is passed
**When** `delete-customer --hard cust_01HG7... --yes` is run
**Then** the deletion proceeds without prompting

**Given** the customer has no associated keys
**When** `delete-customer --hard` is run
**Then** the customer record is purged and confirmation shows "0 keys purged"

### Story 4.2: Encryption Key Rotation

As an operator,
I want to rotate the encryption key without any window of unreadable data,
So that I can follow security best practices and recover from potential key exposure.

**Covers:** FR36

**Acceptance Criteria:**

**Given** the operator has a new Fernet key ready
**When** they run `comadre-keys rotate-encryption-key --new-key <new-fernet-key>`
**Then** the system prompts for confirmation: "This will re-encrypt all customer tax IDs with the new key. Continue? [y/N]:"
**And** on confirmation: within a single transaction, decrypts every `tax_id_encrypted` with the current key and re-encrypts with the new key
**And** only after ALL rows are successfully re-encrypted does the command print: "Encryption key rotated. Update KEY_REGISTRY_ENCRYPTION_KEY in .env to: <new-key>"
**And** the audit log records a `rotate_encryption_key` event with actor `cli:<shell-user>`

**Given** `--yes` is passed
**When** the command runs
**Then** rotation proceeds without prompting

**Given** the new key is invalid (not a valid Fernet key)
**When** the command runs
**Then** an ErrorDisplay is shown and exit code 4, no rows are modified

**Given** the transaction fails mid-way (disk full, power loss)
**When** the process crashes
**Then** SQLite transaction rollback ensures all rows retain their original encryption — no data is left in an intermediate state

**Given** the operator changes `.env` without running this command
**When** the old key is replaced directly
**Then** all encrypted fields become unreadable — this is documented as a "do not do this" in the operator runbook

### Story 4.3: Backup & Restore Playbooks

As an operator,
I want automated nightly backups and a tested restore procedure,
So that I can recover from data loss within the 24-hour RPO.

**Covers:** FR40, FR41
**NFRs:** NFR14, NFR21, NFR22

**Acceptance Criteria:**

**Given** the operator runs `ansible-playbook backup-keys.yml -e "ansible_become_password=PASSWORD"`
**When** the playbook executes
**Then** it creates a SQLite snapshot (using `.backup` command for consistency), includes the `KEY_REGISTRY_ENCRYPTION_KEY` separately encrypted, packages both into a tarball with file mode `0600` (NFR14), and stores it at a configurable backup path
**And** old backups beyond a configurable retention window are cleaned up

**Given** bootstrap.yml has been run with monetization enabled
**When** the cron is installed
**Then** a `comadre-keys-backup` cron entry at 02:00 operator TZ runs the backup playbook or a direct SQLite backup command

**Given** a backup tarball exists
**When** the operator runs `ansible-playbook restore-keys.yml -e "ansible_become_password=PASSWORD" -e "backup_file=<path>"`
**Then** the playbook restores the SQLite file from the tarball, sets permissions to `0600`, verifies WAL mode, and reports success
**And** the playbook is idempotent — running it twice with the same backup produces the same result

**Given** the restore completes
**When** the service is restarted
**Then** the key registry is operational with all data from the backup (RPO bounded by nightly cadence, NFR22)
**And** restoration completes in under 10 minutes for under 10,000 customers (NFR21)

### Story 4.4: Operational Safety & File Permissions

As an operator,
I want the system to enforce file permissions and safe multi-replica operation,
So that the database is protected from unauthorized access and concurrent corruption.

**Covers:** FR42, FR44, FR52

**Acceptance Criteria:**

**Given** bootstrap.yml runs
**When** the key registry database is created
**Then** the file permissions are set to `0600` owned by the Comadre service user
**And** the `data/keys/` directory is set to `0700`

**Given** multiple Comadre replicas (via `deploy.replicas` in compose.yaml) share the same SQLite file via bind mount
**When** concurrent auth reads and CLI/cron writes occur
**Then** WAL mode (enforced at connection creation) prevents corruption under normal operational load (FR44)
**And** each replica's auth cache is independent (no shared cache state)

**Given** the operator runs `ansible-playbook health.yml`
**When** the playbook checks the monetization-related state
**Then** it reports: DB file permissions (fail if not `0600`), cron jobs installed (comadre-daily-suspension, comadre-keys-backup), last backup output exists, UFW rules unchanged (22/80/443 only)
**And** the playbook exits non-zero on any deviation (FR52)

**Given** a new replica is added via `deploy.replicas`
**When** it starts and initializes its lifespan
**Then** it opens the shared SQLite file in WAL mode, creates its own in-memory auth cache, and checks the schema version — no migration runs if already current

### CI Non-Regression Security Suite (4.5 Umbrella)

The CI non-regression work (originally a single Story 4.5) is split into 7 sub-stories (4.5a–4.5g), each covering one security control. Each sub-story adds one CI check file (or entry) to `tests/test_non_regression.py` (or equivalent) and wires it into the GitHub Actions workflow. All 7 must be done for Epic 4 to be complete. The umbrella itself is not a separately-tracked story — it is a grouping header for the sub-stories that follow.

**Shared scope across 4.5a–4.5g:**
- All sub-stories share the same CI workflow file (`.github/workflows/non-regression.yml` or an extension of the existing CI).
- All sub-stories share the same test module namespace (e.g., `tests/test_non_regression/test_*.py`).
- First sub-story merged establishes the file/workflow skeleton; subsequent sub-stories append checks.
- **NFRs:** NFR17 applies across all sub-stories.

---

### Story 4.5a: CI — Security Headers Regression

As a contributor,
I want CI to verify every required security header is present on every Caddy-served response,
So that a PR cannot silently drop HSTS, CSP, or any other hardened header.

**Covers:** FR46
**NFRs:** NFR17

**Acceptance Criteria:**

**Given** a PR is opened against master
**When** CI spins up the Caddy reverse proxy with the production-equivalent Caddyfile and hits representative endpoints (`/`, `/v1/audio/speech`, `/health`, a non-existent path for 404, a POST for 405)
**Then** every response carries: `Strict-Transport-Security`, `Content-Security-Policy`, `X-Frame-Options`, `X-Content-Type-Options`, `Referrer-Policy`, `Permissions-Policy`, and `upgrade-insecure-requests` (or its CSP directive form)
**And** each assertion identifies the specific missing header when it fails (clear diagnostic output)

**Given** the documented Caddy `Server`/`Via` leak on 404/308 (see `feedback_caddy_server_header.md`)
**When** the header-presence check runs
**Then** the test excludes the known-leak scenarios from the banner-stripping assertion but still asserts the security headers are present on those responses

---

### Story 4.5b: CI — Docs Endpoints Disabled Regression

As a contributor,
I want CI to verify `/docs`, `/redoc`, and `/openapi.json` all return 404 in production configuration,
So that a PR cannot re-enable the OpenAPI surface that was closed during pentest remediation.

**Covers:** FR47
**NFRs:** NFR17

**Acceptance Criteria:**

**Given** a PR is opened against master
**When** CI launches the application with the production settings profile and issues `GET /docs`, `GET /redoc`, and `GET /openapi.json`
**Then** all three responses return HTTP 404 with the standard `{error: {message, type, hint}}` envelope (the one produced by the project's 404 handler)
**And** none of the responses include OpenAPI content or Swagger UI HTML in the body

---

### Story 4.5c: CI — Timing-Safe Key Comparison Static Check

As a contributor,
I want CI to reject any new code that compares key material using string equality,
So that the timing-attack-resistant contract established by 1.6.2 cannot regress.

**Covers:** FR48
**NFRs:** NFR17

**Acceptance Criteria:**

**Given** a PR is opened against master
**When** CI runs a static scan (ripgrep-backed or AST-based) over `src/comadre/` for suspicious equality comparisons on identifiers named `*key*`, `*hash*`, `*token*`, or `*secret*`
**Then** the scan fails the build if any match is found, unless the match is on a known-safe line annotated with a scan-allowlist comment (documented pattern, reviewer-approved)
**And** calls to `hmac.compare_digest` are not flagged (the scan's allowlist)
**And** a unit test verifies the scan itself: adding a known-bad pattern in a fixture file causes the scan to fail

---

### Story 4.5d: CI — Oversized Request Body Rejection

As a contributor,
I want CI to verify oversized request bodies are rejected by Caddy before reaching FastAPI,
So that the `request_body max_size 1MB` control remains enforced.

**Covers:** FR49
**NFRs:** NFR17

**Acceptance Criteria:**

**Given** a PR is opened against master
**When** CI sends a POST request of 2 MB to `/v1/audio/speech` through Caddy
**Then** Caddy rejects the request with HTTP 413 (or the configured status) before the request reaches the application
**And** a second assertion verifies the payload boundary: a 1 MB request is accepted by Caddy (status < 413) — proves the limit is at ~1 MB, not at an arbitrary small value
**And** application logs show no record of receiving the oversized request

---

### Story 4.5e: CI — Rate-Limit Middleware Registration

As a contributor,
I want CI to verify `SlowAPIMiddleware` is registered and actively enforces limits on speech and health endpoints,
So that the bug fixed in commit `edfcb33` cannot silently regress.

**Covers:** FR50
**NFRs:** NFR17

**Acceptance Criteria:**

**Given** a PR is opened against master
**When** CI launches the application and issues more requests per minute to `/v1/audio/speech` than the configured `RATE_LIMIT_SPEECH` value, and separately to `/health` than `RATE_LIMIT_HEALTH`
**Then** both endpoints return HTTP 429 with a `Retry-After` header and the standard `{error: {message, type, hint}}` envelope once the limit is exceeded
**And** a startup assertion verifies `SlowAPIMiddleware` is in the FastAPI middleware stack (not merely imported)
**And** the test fixture uses short time windows (e.g., 2 req/10s) to keep CI fast

---

### Story 4.5f: CI — No Raw HTTPException

As a contributor,
I want CI to reject any new code that raises a raw `HTTPException` instead of a `ComadreError` subclass,
So that the uniform error-envelope contract is never silently broken.

**Covers:** FR51
**NFRs:** NFR17

**Acceptance Criteria:**

**Given** a PR is opened against master
**When** CI runs a static scan over `src/comadre/` (ripgrep-backed or AST-based) for `raise HTTPException` and `from fastapi import HTTPException`
**Then** the scan fails the build if any occurrence is found in new or modified files
**And** the scan allows the explicit import and usage inside dedicated exception-bridging code paths (if any exist), flagged by a scan-allowlist comment and reviewer approval
**And** a unit test verifies the scan itself: adding `raise HTTPException(...)` in a fixture file causes the scan to fail

---

### Story 4.5g: CI — SQL-Injection Static Analysis (Bandit)

As a contributor,
I want CI to run `bandit` (or equivalent) over `src/comadre/keys/` on every PR,
So that SQL-injection-prone patterns cannot reach master.

**Covers:** (Cross-cutting SQL-injection prevention from PRD §Technical Constraints and PRD §Epic 2 Security story)
**NFRs:** NFR17

**Acceptance Criteria:**

**Given** a PR is opened against master
**When** CI runs `bandit -r src/comadre/keys/` (or equivalent static analyzer) as a step in the workflow
**Then** the workflow fails if any HIGH-severity finding is reported, with the finding shown in the workflow output
**And** SQL-injection-prone patterns (e.g., f-string interpolation inside `conn.execute()`) are in the analyzer's default checks or are added via a project-specific configuration file
**And** a unit test verifies the analyzer itself: a fixture file containing `conn.execute(f"SELECT * FROM t WHERE id = {x}")` produces a HIGH-severity finding

---

### Story 4.6: LGPD Documentation & Breach Runbook

As an operator,
I want complete LGPD compliance documentation,
So that I can fulfill my obligations as data controller and respond to breaches properly.

**Covers:** FR39

**Acceptance Criteria:**

**Given** the operator deploys Comadre 2.0.0
**When** they open `docs/monetization.md`
**Then** it contains a section "LGPD Operator Obligations" with:
**And** a breach-notification runbook including: ANPD contact information, customer-notification email template, evidence-preservation checklist, internal escalation path
**And** a privacy-policy template paragraph the operator can adapt for their own terms of service
**And** clear statement that the operator is the LGPD data controller (Art. 5, VI) and Comadre is a tool
**And** documentation of the data retained (name, email, encrypted CPF/CNPJ), the legal basis ("execução de contrato", Art. 7 V), and retention period

**Given** the operator needs to handle a data-subject access request
**When** they consult the runbook
**Then** it references `comadre-keys export-customer <id> --format json` with a step-by-step procedure

**Given** the operator needs to handle a deletion request
**When** they consult the runbook
**Then** it references `comadre-keys delete-customer --hard <id>` with the expected output and audit-log behavior

**Given** the encryption key may have been compromised
**When** the operator consults the runbook
**Then** it provides a step-by-step for `rotate-encryption-key` plus the `.env` update procedure, with a warning about never editing `.env` directly without running the rotation command first
