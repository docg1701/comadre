---
stepsCompleted:
  - step-01-document-discovery
  - step-02-prd-analysis
  - step-03-epic-coverage-validation
  - step-04-ux-alignment
  - step-05-epic-quality-review
  - step-06-final-assessment
status: complete
filesIncluded:
  - prd.md
  - prd-validation-report.md
  - architecture.md
  - epics.md
  - ux-design-specification.md
resolutions:
  - date: '2026-04-16'
    finding: 'Major Issue #1 — FR45 coverage claim not honest (cache-flush)'
    action: 'PRD FR45, §Authentication Model, and §CLI Tool Specification amended to reflect MVP behavior: no forced invalidation; 60s TTL is the propagation bound. CLI command renamed cache-flush → cache-status. Downstream updates applied to architecture.md (Important Decisions, Cache Invalidation section, CLI structure, File Manifest) and epics.md (Additional Requirements, FR45 definition, FR Coverage Map, Story 2.3 AC). Historical findings below kept intact for audit trail.'
---

# Implementation Readiness Assessment Report

**Date:** 2026-04-16
**Project:** comadre

> **Post-publication amendments (2026-04-16):** The two Major Issues identified below have been partially resolved. See frontmatter `resolutions` and §Amendments Since Publication at the bottom of this report for the audit trail. Historical finding text in the body is preserved as-is.

## PRD Analysis

### Functional Requirements

**Customer Lifecycle Management**

- **FR1:** Operator can register a new customer by providing name, email, and either CPF or CNPJ (never both).
- **FR2:** System rejects a new customer record when the provided CPF or CNPJ fails Brazilian checksum validation.
- **FR3:** Operator can attach free-form notes to any customer record and append additional notes without overwriting existing ones.
- **FR4:** Operator can update a customer's email and notes without affecting other fields.
- **FR5:** Operator can irreversibly purge a customer record, including the tax-ID, all associated keys, and personal data, in compliance with the LGPD right to deletion.
- **FR6:** Operator can export a single customer's stored data in a machine-readable format suitable for fulfillment of LGPD data-subject access requests.
- **FR7:** Operator can list all customers, with an optional filter to include tombstone records left by prior LGPD purges.

**API Key Lifecycle Management**

- **FR8:** Operator can issue a new API key against an existing customer, specifying the per-key rate limit and monthly price.
- **FR9:** Operator can issue a complimentary API key whose billing is handled outside Comadre (e.g., bundled in an external service contract).
- **FR10:** Operator can update an existing key's rate limit, monthly price, and notes without disclosing or changing the key plaintext.
- **FR11:** Operator can rotate a key, producing a new plaintext while retaining the same key id and customer association; the old key stops working immediately.
- **FR12:** Operator can revoke a key with a free-form reason; revoked keys are retained in the database as historical records.
- **FR13:** Operator can list keys filtered by status, billing mode, paid-until date, or customer id.
- **FR14:** Operator can view full context for a single key including customer, dates, price, notes, and recent audit events.

**Billing State Management**

- **FR15:** Operator can mark a manual-mode key as paid through a specified future date.
- **FR16:** Operator can query which keys are approaching billing expiration within a configurable look-ahead window.
- **FR17:** Operator can generate a revenue report for any calendar month showing paid, pending, suspended, and complimentary breakdowns; complimentary keys are reported separately and never counted in recurring-revenue totals.
- **FR18:** System automatically suspends manual-mode keys whose paid date has elapsed, once per day, at a configurable operator-timezone time.
- **FR19:** System preserves suspended keys indefinitely; no data-deletion is automatic.
- **FR20:** System automatically restores a key to active status once its paid date is extended, with propagation time bounded by the auth cache behavior.

**API Authentication and Rate Limiting**

- **FR21:** Customer can authenticate HTTP requests to `/v1/audio/speech` using a Bearer API key.
- **FR22:** System validates an incoming Bearer key against an immutably-hashed copy stored in the registry, never storing or comparing the plaintext.
- **FR23:** System caches valid authorizations to satisfy the NFR1 auth-path latency target for repeat requests from the same key.
- **FR24:** System enforces a per-key rate limit derived at request time from the specific key's configured limit.
- **FR25:** System enforces a per-IP rate limit applied independently of auth outcome, so failed auth attempts are bounded.
- **FR26:** System equalizes the timing of key-lookup operations so that an attacker cannot distinguish a hash hit from a miss by wall-clock observation.
- **FR27:** System can operate in a legacy single-API-key mode when the monetization toggle is disabled, preserving compatibility with pre-2.0.0 deployments.
- **FR28:** System returns a distinct 401 error envelope for suspended and revoked keys that directs the customer to their operator's billing contact.
- **FR29:** System preserves the request and response contract of `/v1/audio/speech` and `/health` identically to Comadre 1.6.2, so existing customer integrations continue to function without modification.

**Observability and Auditing**

- **FR30:** System records every customer and key mutation to an append-only audit log with actor identity, action, target, and timestamp.
- **FR31:** System records every cron-initiated suspension or reactivation event to the audit log.
- **FR32:** Operator can view the audit tail for any customer or key directly from the CLI.
- **FR33:** System maintains in-memory per-key request counters (total, rate-limit rejections, peak throughput, average throughput) for short-term troubleshooting; counters are not durable and reset on service restart.
- **FR34:** Operator can query overall system health (cron liveness, database integrity, auth cache state, backup recency) with a single command.

**Data Privacy and LGPD Compliance**

- **FR35:** System encrypts CPF and CNPJ values at rest, with encryption material supplied by the deploy environment.
- **FR36:** Operator can rotate the encryption material by re-encrypting every protected field atomically, without a window in which data is unreadable.
- **FR37:** System prevents personal data (CPF, CNPJ, API-key plaintext) from appearing in structured log messages regardless of log verbosity.
- **FR38:** System preserves audit-log metadata (who, when, what) after a customer's personal data is purged, so operator activity remains traceable without retaining personal data.
- **FR39:** Operator receives a `docs/monetization.md` section "LGPD Operator Obligations" containing: (a) a breach-notification runbook with ANPD contact information, a customer-notification email template, an evidence-preservation checklist, and an internal escalation path; (b) a privacy-policy template paragraph the operator can adapt for their own terms of service.

**Operational Safety**

- **FR40:** System can back up the key registry and encryption material nightly, in a single encrypted archive separate from the database file itself.
- **FR41:** Operator can restore the key registry from a prior backup via a dedicated, idempotent playbook.
- **FR42:** System enforces strict file permissions on the SQLite database file and the encryption key material at deploy time, and the health command reports deviations.
- **FR43:** System runs the daily suspension sweep at a fixed operator-timezone time and makes the last successful run timestamp queryable.
- **FR44:** System can operate safely across multiple Comadre replicas reading and writing the same SQLite file without corruption under normal operational load.
- **FR45:** Operator can force an immediate auth-cache invalidation across a replica, for cases where the natural cache-TTL propagation delay is unacceptable.

**Security Regression Prevention**

- **FR46:** CI can verify that every security header required by the Caddy configuration (HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, upgrade-insecure-requests) is present on every response code returned by the reverse proxy.
- **FR47:** CI can verify that `/docs`, `/redoc`, and `/openapi.json` return 404 in production-configured deployments.
- **FR48:** CI can verify that the auth path uses timing-safe comparison primitives exclusively and never string equality.
- **FR49:** CI can verify that oversized request bodies are rejected at the reverse-proxy layer before reaching the application.
- **FR50:** CI can verify that the rate-limit middleware is registered and actually applies to both the speech and health endpoints.
- **FR51:** CI can verify that no new code raises a raw `HTTPException`; every error path uses a `ComadreError` subclass.
- **FR52:** Operator can verify via the existing `health.yml` Ansible playbook that UFW, SQLite permissions, cron jobs, and backup playbook outputs are in their expected state, with a clear exit code on any deviation.

**Total FRs: 52**

### Non-Functional Requirements

**Performance**

- **NFR1:** Auth-path overhead for a cache-hit request must stay under 5 ms at p99, measured against a 1,000-customer database.
- **NFR2:** Auth-path overhead for a cache-miss request must stay under 15 ms at p99, measured against a 1,000-customer database.
- **NFR3:** The daily suspension cron sweep must complete under 1 second for 1,000 active keys.
- **NFR4:** CLI list-class commands (`list-customers`, `list-keys`) must render the first screenful of output in under 200 ms for a 1,000-customer database.
- **NFR5:** CLI detail-class commands (`show`, `revenue`, `at-risk`) must complete in under 500 ms for the same database size.
- **NFR6:** The auth cache TTL must not exceed 60 seconds; reactivation of a newly-paid key must become visible within that window at the latest.
- **NFR7:** Monetization-related code paths must not add more than 2 ms p99 to the existing `/v1/audio/speech` post-auth request pipeline.

**Security**

- **NFR8:** API-key plaintext must be displayed to the operator at most once (at creation or rotation time) and never persist anywhere other than the operator's terminal scrollback.
- **NFR9:** API-key values must be stored in the registry as SHA-256 (or stronger) hashes; the cryptographic primitive choice is documented in `docs/monetization.md` and changes require an encryption-rotation playbook.
- **NFR10:** CPF and CNPJ values must be encrypted at rest using Fernet (or a stronger authenticated-encryption primitive); the encryption key is supplied by `KEY_REGISTRY_ENCRYPTION_KEY` and never hardcoded.
- **NFR11:** All key-comparison operations must use timing-safe primitives (`hmac.compare_digest` or equivalent); string equality is prohibited in the auth path.
- **NFR12:** Unsuccessful auth attempts must return in constant time regardless of whether the key hash matched a stored record.
- **NFR13:** The SQLite database file must have filesystem mode `0600` owned by the Comadre service user; the `health.yml` playbook fails if the mode drifts.
- **NFR14:** Backup archives must have filesystem mode `0600` and include the encryption key separately encrypted from the database payload.
- **NFR15:** No structured log message, at any log level, may contain a plaintext API key, a decrypted CPF, a decrypted CNPJ, or an `Authorization` header value.
- **NFR16:** No HTTP response body or `hint` field may echo the content of a customer-supplied invalid value (e.g., the rejected CPF), to prevent log-injection and reconnaissance.
- **NFR17:** All controls enumerated in §Domain-Specific Requirements > Continuity with Existing Hardening must remain satisfied on every PR merged to master; CI regression coverage is mandatory for each control row.

**Reliability & Availability**

- **NFR18:** Comadre 2.0.0 must preserve Comadre 1.6.2's latency SLA as documented in `CLAUDE.md` and in `project-context.md`: ≤10 seconds is great, 10–90 seconds is the natural WhatsApp pace, >90 seconds indicates system stress.
- **NFR19:** The auth path must have zero external dependencies at request time — no outbound HTTP, no DNS lookup, no network egress. If the VPS is online, auth works.
- **NFR20:** The key registry must tolerate unclean shutdown without corruption; the post-crash auth cache may be empty but the registry itself must remain readable.
- **NFR21:** Backup Recovery Time Objective (RTO): the `restore-keys.yml` playbook must restore a full key registry from a nightly backup in under 10 minutes for a typical-size shard (under 10,000 customers).
- **NFR22:** Backup Recovery Point Objective (RPO): data loss from a catastrophic VPS failure must not exceed 24 hours (bounded by nightly backup cadence).
- **NFR23:** The daily suspension cron must not block concurrent auth-path reads during the sweep.
- **NFR24:** A Comadre replica restart must not cause any outage longer than the existing warm-up window (≤60 seconds to `/health` returning `healthy`). Monetization must not extend the warm-up time.

**Scalability**

- **NFR25:** A single Comadre shard (one VPS, one SQLite file) must support at least 1,000 active customers and 2,000 active keys without violating the performance NFRs above.
- **NFR26:** Scaling beyond a single shard is operator-driven: the operator provisions an additional VPS and migrates or issues keys on it. No shared state is introduced between shards.
- **NFR27:** Per-shard memory overhead added by monetization must stay under 50 MB above the baseline 1.6.2 footprint; the auth cache is the dominant contributor and its size is bounded by the 60-second TTL and the active-request rate.
- **NFR28:** Disk-usage growth from monetization must stay under 50 MB for the first 6 months of typical operator use (customer records + audit log + backups retained in-place for rolling 30-day window).
- **NFR29:** Multi-replica deployments (same VPS, multiple container replicas sharing the SQLite volume) must operate without corruption under normal load; each replica's auth cache is independent, and cache skew up to the 60-second TTL is acceptable.

**Compatibility**

- **NFR30:** The public `/v1/audio/speech` and `/health` request/response contracts must remain byte-identical to Comadre 1.6.2; any customer integration that worked against 1.6.2 must continue to work against 2.0.0 without modification.
- **NFR31:** The legacy single-`API_KEY` auth mode (when `monetization_enabled=false`) must preserve every behavior of Comadre 1.6.2 exactly, including error envelopes, rate-limit values, and timing characteristics.
- **NFR32:** Ansible playbooks must remain idempotent: running `bootstrap.yml` or `update.yml` multiple times must not re-issue keys, re-provision the database, or trigger spurious restarts.
- **NFR33:** The `comadre-keys` CLI must be backward-compatible within a major version: CLI invocations that worked on 2.0.0 must continue to work on every 2.x release.

**Compliance**

- **NFR34:** LGPD data-subject access requests (Art. 18, II and V) must be fulfillable in under 15 days using the `export-customer` command, with the operator responsible for delivery to the data subject.
- **NFR35:** LGPD right-to-deletion requests (Art. 18, VI) must be fulfillable in under 15 days using the `delete-customer --hard` command; the command completes in under 1 second for any single customer regardless of database size.
- **NFR36:** LGPD breach notification (Art. 48): a runbook in `docs/monetization.md` must document the operator's notification duty and provide a template notification letter compliant with ANPD requirements.
- **NFR37:** Consumer-protection (CDC) compliance: the suspended-but-not-deleted key contract (FR19) guarantees that a non-paying customer's historical data is not destroyed, preventing disproportionate loss on reactivation.

**Total NFRs: 37**

### Additional Requirements

**Architectural constraints (from §Domain-Specific Requirements and §Implementation Considerations):**

- Import-graph extension constraint: new `keys/` submodules (`db`, `auth`, `billing`, `cli`) must respect the downward-only import flow; `keys/cli` is not imported by the app runtime.
- No new Docker containers; monetization lives inside the existing `tts-service` container.
- No new listening ports; CLI is SSH-only, never HTTP-exposed.
- No outbound network egress from the auth path (offline-capable).
- SQLite in WAL mode, single file, shared across replicas via the existing volume mount.
- `pydantic-settings` for all new config; no raw `os.environ`.
- All new errors via `ComadreError` subclasses: `ApiKeyNotFoundError`, `ApiKeySuspendedError`, `ApiKeyRevokedError`, `InvalidTaxIdError`, `KeyRegistryError`.
- `monetization_enabled` boolean toggle gates the new auth path for backward-compatible migration from 1.6.2.

**Integration requirements (from §Integration Requirements):**

- MVP reuses OS-level cron (pre-existing), no new scheduler.
- Ansible: `bootstrap.yml` installs DB/CLI/cron; `cleanup.yml` removes them; new `backup-keys.yml` and `restore-keys.yml` playbooks.
- No external services in MVP: no PSP, no SMTP, no webhook listener, no background queue.
- Growth phase (2.1+) reserves `/v1/billing/webhook/<provider>` behind existing Caddy reverse proxy with HMAC signature verification per adapter.

**Non-regression contract (from §Continuity with Existing Hardening):**

- 25+ individual controls enumerated across four tables (external attack surface, authentication & rate limiting, error handling & logging, module boundaries & deployment). Every row must retain a CI regression test. These controls are the source material for Epic 2 (Security & Compliance) acceptance criteria per the PRD's §Epic Mapping.

**Out-of-scope explicit refusals (from §Scope Hardening):**

- No web UI of any kind (not even read-only, not even behind VPN).
- No SMTP, no email notifications, no 2FA.
- No central billing database; every VPS is a sovereign shard.
- No automated PSP in MVP (`ManualBillingProvider` only).
- No usage-based billing; flat monthly per-key pricing only.
- No customer self-service (no customer portal, no self-rotate, no status view).
- No tiered SLA; premium keys differ only in RPM ceiling.

**Business/commercial constraints (from §Success Criteria and §Resource Requirements):**

- Solo developer resource envelope; cycle must complete at prior feature-cycle pace.
- At least one non-author operator in production within 90 days as the platform-enablement validation signal.
- Per-operator targets: 10–20 active keys and R$ 500–1,500 MRR at 3 months; 30–60 keys and R$ 2,500–7,000 MRR at 12 months.

**Domain-specific constraints (from §Domain-Specific Requirements > Compliance):**

- LGPD applies: legal basis "execução de contrato", data minimization, encryption at rest for tax IDs, 15-day response window for access/deletion requests, ANPD breach-notification runbook, operator-as-controller posture.
- Brazilian tax/NFSe emission explicitly out of MVP scope (operator's accountant or PSP).
- CDC (consumer protection) suspended-but-not-deleted contract is binding.

### PRD Completeness Assessment

**Strengths:**

- 52 FRs and 37 NFRs cover the full MVP surface with unambiguous, testable language; no `TODO` / `[TBD]` placeholders remaining.
- Explicit two-epic decomposition (Monetization Core + Security & Compliance) already provided in §Product Scope, so the work is pre-segmented for Epic-level validation.
- Every FR category maps cleanly to at least one user journey (J1–J6), satisfying traceability requirements.
- Non-regression contract is enumerated verbatim with 25+ explicit controls — rare for a PRD at this stage and materially reduces ambiguity in Epic 2.
- §Epic Mapping section explicitly binds the non-regression controls to Epic 2 acceptance criteria, preventing "orphan" hardening work.
- Error handling taxonomy complete: new `ComadreError` subclasses named, status codes assigned, hints specified.
- Performance targets quantified (NFR1–NFR7) with specific database sizes (1,000 customers) for testability.
- LGPD obligations comprehensively addressed with named Articles (7 V, 18 II/V/VI, 48) and operator-vs-controller distinction clarified.
- Scope-hardening section explicitly refuses 7 tempting additions with documented rationale, preventing scope creep during Epic/Story authoring.
- A separate `prd-validation-report.md` already exists (52 KB, 2026-04-15) — this PRD has already been through a validation cycle.

**Potential gaps for traceability validation in later steps:**

- FR39 prescribes specific sub-content for `docs/monetization.md` (breach-notification runbook, ANPD contact, customer-notification email template, evidence-preservation checklist, internal escalation path, privacy-policy template paragraph) — later steps should verify the Epic 2 documentation story enumerates all six sub-items.
- Growth-phase PSP webhook endpoints (`/v1/billing/webhook/<provider>`) are named but explicitly deferred; later steps should verify epics/stories do not accidentally leak 2.1+ work into 2.0.0.
- The `export-customer` and `delete-customer --hard` CLI commands each map to multiple FRs (FR5, FR6, FR7, FR35–FR38, NFR34, NFR35) — Epic/Story coverage will need to verify each requirement has a concrete acceptance criterion, not just a command reference.
- The `cache-flush` CLI command is specified functionally (FR45) but appears as a "runbook-documented" command in §Authentication Model — later steps should verify story acceptance criteria cover the command's observable behavior, not merely its existence.
- Cross-cutting in-memory request counter requirement (FR33) is best-effort only; later steps should verify epics/stories acknowledge this is non-durable observability and not a billing record.

## Epic Coverage Validation

### Epic Structure Overview

Four epics, 19 stories total:

- **Epic 1 — Key Registry & Customer Management** (6 stories: 1.1–1.6) — FRs: FR1–FR4, FR7–FR14, FR30, FR32, FR35, FR37
- **Epic 2 — API Authentication & Dynamic Rate Limiting** (3 stories: 2.1–2.3) — FRs: FR21–FR29, FR33, FR45. Depends on Epic 1.
- **Epic 3 — Billing & Revenue Operations** (4 stories: 3.1–3.4) — FRs: FR15–FR20, FR31, FR34, FR43. Depends on Epic 1.
- **Epic 4 — Security Hardening, LGPD & Operational Safety** (6 stories: 4.1–4.6) — FRs: FR5, FR6, FR36, FR38–FR42, FR44, FR46–FR52. Depends on Epics 1–3.

### Coverage Matrix

| FR | PRD Requirement (short) | Epic Coverage | Status |
|---|---|---|---|
| FR1  | Register customer with name/email/CPF-CNPJ | Epic 1 — Story 1.1 | ✓ Covered |
| FR2  | Reject invalid CPF/CNPJ checksum | Epic 1 — Story 1.1 | ✓ Covered |
| FR3  | Attach/append notes to customer | Epic 1 — Story 1.5 | ✓ Covered |
| FR4  | Update customer email/notes only | Epic 1 — Story 1.5 | ✓ Covered |
| FR5  | LGPD hard-delete customer + keys + personal data | Epic 4 — Story 4.1 | ✓ Covered |
| FR6  | LGPD export customer data (machine-readable) | Epic 4 — Story 4.1 | ✓ Covered |
| FR7  | List customers with tombstone filter | Epic 1 — Story 1.3 | ✓ Covered |
| FR8  | Issue API key with RPM and monthly price | Epic 1 — Story 1.2 | ✓ Covered |
| FR9  | Issue complimentary API key | Epic 1 — Story 1.2 | ✓ Covered |
| FR10 | Update key RPM/price/notes without changing plaintext | Epic 1 — Story 1.6 | ✓ Covered |
| FR11 | Rotate key (new plaintext, same ID) | Epic 1 — Story 1.6 | ✓ Covered |
| FR12 | Revoke key with reason, retained as historical | Epic 1 — Story 1.6 | ✓ Covered |
| FR13 | List keys with status/billing/paid-until/customer filters | Epic 1 — Story 1.3 | ✓ Covered |
| FR14 | Show full key context + audit events | Epic 1 — Story 1.4 | ✓ Covered |
| FR15 | Mark manual-mode key as paid through date | Epic 3 — Story 3.1 | ✓ Covered |
| FR16 | Query at-risk keys by look-ahead window | Epic 3 — Story 3.2 | ✓ Covered |
| FR17 | Revenue report (paid/pending/suspended/complimentary) | Epic 3 — Story 3.2 | ✓ Covered |
| FR18 | Auto-suspend expired manual-mode keys daily | Epic 3 — Story 3.3 | ✓ Covered |
| FR19 | Preserve suspended keys indefinitely (no auto-delete) | Epic 3 — Story 3.1 | ✓ Covered |
| FR20 | Auto-restore key when paid_until extended | Epic 3 — Story 3.1 | ✓ Covered |
| FR21 | Bearer key authentication on `/v1/audio/speech` | Epic 2 — Story 2.1 | ✓ Covered |
| FR22 | Validate key against SHA-256 hash, never compare plaintext | Epic 2 — Story 2.1 | ✓ Covered |
| FR23 | Cache valid authorizations (60s TTLCache) | Epic 2 — Story 2.1 | ✓ Covered |
| FR24 | Per-key dynamic rate limit (request-time resolution) | Epic 2 — Story 2.2 | ✓ Covered |
| FR25 | Per-IP rate limit independent of auth outcome | Epic 2 — Story 2.2 | ✓ Covered |
| FR26 | Timing-equalized key lookup (dummy compare on miss) | Epic 2 — Story 2.1 | ✓ Covered |
| FR27 | Legacy single-API_KEY mode when monetization disabled | Epic 2 — Story 2.1 | ✓ Covered |
| FR28 | Distinct 401 for suspended/revoked with operator hint | Epic 2 — Story 2.1 | ✓ Covered |
| FR29 | Preserve `/v1/audio/speech` and `/health` contracts | Epic 2 — Story 2.1 | ✓ Covered |
| FR30 | Append-only audit log for all mutations | Epic 1 — Stories 1.1 (foundation) + all mutation stories | ✓ Covered |
| FR31 | Audit log for cron suspension/reactivation | Epic 3 — Story 3.3 | ✓ Covered |
| FR32 | CLI audit tail for any customer or key | Epic 1 — Story 1.4 | ✓ Covered |
| FR33 | In-memory per-key request counters | Epic 2 — Story 2.3 | ✓ Covered |
| FR34 | System health command (cron, DB, cache, backup) | Epic 3 — Story 3.4 | ✓ Covered |
| FR35 | Encrypt CPF/CNPJ at rest with Fernet | Epic 1 — Story 1.1 | ✓ Covered |
| FR36 | Rotate encryption key with atomic re-encryption | Epic 4 — Story 4.2 | ✓ Covered |
| FR37 | Prevent personal data in logs | Epic 1 — Story 1.1 (foundation-level discipline) | ✓ Covered |
| FR38 | Preserve audit metadata after customer purge | Epic 4 — Story 4.1 | ✓ Covered |
| FR39 | LGPD obligations section in `docs/monetization.md` | Epic 4 — Story 4.6 | ✓ Covered |
| FR40 | Nightly backup of registry + encryption key | Epic 4 — Story 4.3 | ✓ Covered |
| FR41 | Restore from backup via idempotent playbook | Epic 4 — Story 4.3 | ✓ Covered |
| FR42 | Enforce file permissions + health deviation reporting | Epic 4 — Story 4.4 | ✓ Covered |
| FR43 | Suspension sweep at fixed TZ + timestamp queryable | Epic 3 — Story 3.3 | ✓ Covered |
| FR44 | Multi-replica SQLite safety (WAL mode) | Epic 4 — Story 4.4 | ✓ Covered |
| FR45 | Force immediate auth-cache invalidation | Epic 2 — Story 2.3 | ✓ Covered |
| FR46 | CI: verify security headers on all responses | Epic 4 — Story 4.5 | ✓ Covered |
| FR47 | CI: verify `/docs`, `/redoc`, `/openapi.json` return 404 | Epic 4 — Story 4.5 | ✓ Covered |
| FR48 | CI: verify timing-safe comparison only | Epic 4 — Story 4.5 | ✓ Covered |
| FR49 | CI: verify oversized request body rejection | Epic 4 — Story 4.5 | ✓ Covered |
| FR50 | CI: verify rate-limit middleware registered | Epic 4 — Story 4.5 | ✓ Covered |
| FR51 | CI: verify no raw `HTTPException` | Epic 4 — Story 4.5 | ✓ Covered |
| FR52 | `health.yml` verifies UFW/perms/cron/backup | Epic 4 — Story 4.4 | ✓ Covered |

### Cross-Validation Against Epic-Declared Coverage

Verified by two independent walks:

1. **PRD → Epic walk** (above) — every PRD FR1–FR52 has at least one story mapping.
2. **Epic → PRD walk** — every FR asserted in an epic's "Covers" field corresponds to a real PRD FR number (no orphan FRs in epics that don't exist in the PRD).

Each epic's declared FR set in the Epic List section matches the union of its stories' "Covers" fields:

- Epic 1 declared: FR1–FR4, FR7–FR14, FR30, FR32, FR35, FR37 → Story-level sum: identical ✓
- Epic 2 declared: FR21–FR29, FR33, FR45 → Story-level sum: identical ✓
- Epic 3 declared: FR15–FR20, FR31, FR34, FR43 → Story-level sum: identical ✓
- Epic 4 declared: FR5, FR6, FR36, FR38, FR39, FR40–FR42, FR44, FR46–FR52 → Story-level sum: identical ✓

### Missing Requirements

**No critical missing FRs.** All 52 PRD FRs are mapped to at least one epic/story with explicit "Covers" annotation.

**No high-priority missing FRs.** All FR categories (Customer Lifecycle, API Key Lifecycle, Billing State, API Auth & Rate Limiting, Observability, LGPD, Operational Safety, Security Regression) are represented across the four epics.

**No orphan FRs in epics.** Every FR number referenced in an epic or story exists in the PRD.

### Coverage Statistics

- Total PRD FRs: **52**
- FRs covered in epics: **52**
- Coverage percentage: **100%**
- Epics: **4**
- Stories: **19**
- Average FRs per story: **~2.7** (with FR30 and FR37 cross-cutting multiple stories as foundation-level concerns)

### Observations for Later Steps

- **FR30 (audit log) and FR37 (log sanitization) are cross-cutting** — declared as Story 1.1 foundation responsibilities but actually enforced by every mutation story. Later steps should verify that stories 1.2, 1.5, 1.6, 3.1, 3.3, 4.1, 4.2 each include acceptance criteria asserting audit-log entries are written with actor/action/target/timestamp, since the FR is only formally "covered" in 1.1's foundation work.
- **FR33 request counters depend on instance-local state** — Story 2.3 explicitly notes counters reset on service restart. Later steps should verify Story 2.3's acceptance criteria clearly communicate this non-durable observability contract to prevent misuse as a billing record.
- **FR45 cache-flush is effectively a no-op** — the architecture decided to accept the 60s TTL rather than implement a real cache flush. Story 2.3 covers this as an informational message. Later steps should verify the story's acceptance criteria are adequate given the reduced scope.
- **FR39 LGPD documentation** — Story 4.6 acceptance criteria include all six sub-items from the PRD (breach runbook, ANPD contact, email template, evidence checklist, escalation path, privacy-policy paragraph), so this complex FR is fully decomposed.

## UX Alignment Assessment

### UX Document Status

**Found** — `ux-design-specification.md` (67 KB, 1,124 lines, status: complete, 14 steps completed on 2026-04-15).

Document structure: executive summary, core UX, emotional response design, pattern analysis, design system, defining interaction, visual design, chosen direction, user journey flows (J1–J4 as Mermaid flowcharts), component strategy (7 custom components), UX consistency patterns, responsive/accessibility, testing strategy.

**Formal UX-DR requirements enumerated in epics**: 18 UX-DRs (UX-DR1–UX-DR18) carried forward from the UX spec into the epics' Requirements Inventory section.

### UX ↔ PRD Alignment

| UX Element | PRD Source | Alignment |
|---|---|---|
| 6 core output types (key panel / status table / summary report / detail view / confirmation / error panel) | §CLI Tool Specification output formats | ✓ Aligned |
| CLI subcommand list (create/issue/mark-paid/revenue/etc.) | §CLI Tool Specification command structure | ✓ Aligned — every UX-referenced command is in the PRD CLI spec |
| J1–J4 Mermaid flows | §User Journeys (J1 First Sale, J2 Billing Ritual, J3 Delinquent, J4 Customer Integration) | ✓ Aligned — 4 of 6 PRD journeys explicitly flow-charted (J5 Debug and J6 Complimentary referenced in component variants rather than Mermaid) |
| One-shot key plaintext display with "Copy now" warning | §User Journeys J1 mockup + Revealed Requirements | ✓ Aligned |
| Key prefix as universal handle | §CLI Tool Specification (accepts partial key prefix) + §User Journeys J3 | ✓ Aligned |
| Error envelope `{error: {message, type, hint}}` with operator contact hint | §Error Codes + §Authentication Model | ✓ Aligned — 401 suspended hint references `OPERATOR_CONTACT_HINT` |
| Enumeration resistance in 401 responses | §Technical Constraints > Enumeration resistance | ✓ Aligned — J4 flow explicitly states "401 for invalid keys does NOT reveal whether key was ever valid" |
| Byte-identical `/v1/audio/speech` contract | NFR30, FR29 | ✓ Aligned — J4 flow confirms "dev doesn't know monetization exists" |
| 4-color semantic palette (green/yellow/red/blue) | Derived from PRD status enum (active/suspended/revoked + complimentary billing mode) | ✓ Aligned |
| Structured exit codes 0–6 | PRD §CLI Tool Specification says "Every command exits 0 on success, non-zero on error" | ✓ Aligned — UX formalizes into 7 categories |
| LGPD destructive command confirmation | FR5 (delete-customer --hard) + PRD §Technical Constraints | ✓ Aligned |
| Revenue report excludes complimentary from MRR | FR17 + §User Journeys J6 | ✓ Aligned |
| Zero interactive prompts for `mark-paid` hot path | §CLI Tool Specification ("All commands are non-interactive by default") + §User Journeys J2 | ✓ Aligned |
| `NO_COLOR` + `--no-color` compliance | PRD §CLI Tool Specification does not explicitly mention NO_COLOR | ⚠ **UX extends PRD** — UX spec adds NO_COLOR/`--no-color` as an accessibility requirement not explicitly required by the PRD. Not a misalignment (UX spec is additive), but worth noting for Epic 1 story AC completeness. |
| Terminal width adaptation (80-col minimum, header abbreviation at narrow widths) | PRD does not specify terminal-width behavior | ⚠ **UX extends PRD** — UX-DR16 is a UX-only constraint. Accepted since Comadre's brownfield inheritance of `rich` makes this a no-cost enhancement. |
| First-run empty-state hint on `list-customers` | PRD does not specify first-run experience | ⚠ **UX extends PRD** — UX-DR13 is additive, supported by implementation. |

**Verdict:** UX expands the PRD's CLI surface with presentation-layer details (colors, widths, accessibility) but introduces no conflicting requirements. The PRD intentionally left these "implementation decisions" to the UX process; the UX spec closes that gap.

### UX ↔ Architecture Alignment

| UX Requirement | Architecture Support | Alignment |
|---|---|---|
| UX-DR1 KeyPanel | `keys/cli/output.py` → `render_key_panel()` (architecture line 347) | ✓ Aligned |
| UX-DR2 StatusTable | `keys/cli/output.py` → `render_status_table()` | ✓ Aligned |
| UX-DR3 DetailPanel | `keys/cli/output.py` → `render_detail_panel()` | ✓ Aligned |
| UX-DR4 RevenueReport | `keys/cli/output.py` → `render_revenue_report()` | ✓ Aligned |
| UX-DR5 AuditTail | `keys/cli/output.py` → `render_audit_tail()` | ✓ Aligned |
| UX-DR6 ErrorDisplay | `keys/cli/output.py` → `render_error()` on stderr | ✓ Aligned |
| UX-DR7 ConfirmationLine | `keys/cli/output.py` → `render_confirmation()` | ✓ Aligned |
| UX-DR8 4-color palette | `rich` library (brought by `typer` as transitive dep); arch confirms zero new deps needed | ✓ Aligned |
| UX-DR9 Shared `rich.Console` instance | Architecture §Coding Standards > CLI Output Patterns: "use `rich.Console` via the shared instance in `output.py`" | ✓ Aligned — explicitly forbidden to create ad-hoc Console objects |
| UX-DR10 Exit codes 0–6 | Architecture line 409 explicitly maps: 0=success, 1=general, 2=usage, 3=not-found, 4=validation, 5=database, 6=permission | ✓ Aligned — identical to UX-DR10 |
| UX-DR11 Destructive `--yes` pattern | Architecture §CLI Output Patterns + Epic 4 Story 4.1 AC | ✓ Aligned |
| UX-DR12 Empty results not errors | Architecture §CLI Output Patterns + Epic 1 Story 1.3 AC | ✓ Aligned |
| UX-DR13 First-run hint | Epic 1 Story 1.3 AC specifies exact hint text | ✓ Aligned |
| UX-DR14 Cross-command navigation | Architecture §Naming Conventions ensures IDs printed by one command are accepted by the next; Epic 1 Stories 1.1, 1.2 AC verify output | ✓ Aligned |
| UX-DR15 `--help` with realistic example | Typer-native feature; Epic 1 Story 1.6 AC asserts presence | ✓ Aligned |
| UX-DR16 Terminal width adaptation | `rich` auto-detects `Console.width`; architecture line 692 confirms rich covers this | ✓ Aligned |
| UX-DR17 Triple-click copy fidelity for key plaintext | Architecture requires `render_key_panel()` with double border; Epic 1 Story 1.2 AC explicitly tests "only key plaintext is selected — no border chars" | ✓ Aligned — enforced at AC level |
| UX-DR18 Inline warning on stderr (non-panel) | Architecture §CLI Output Patterns: "Success data → stdout. Errors → stderr." Warnings follow the errors-to-stderr rule. UX spec clarifies warnings are text-not-panel | ✓ Aligned |

**Architecture-level confirmation of UX support** (from `architecture.md`):

- Line 347: `output.py` is the single file containing all render functions
- Line 406–412: CLI Output Patterns section codifies stdout/stderr split, shared Console, exit codes, key panel
- Line 476: "Match CLI command names, flags, and output exactly to the PRD specification and UX spec component definitions"
- Line 483: "Never add `print()` to CLI code — use `rich.Console` via the shared instance"
- Line 553: Test module `test_keys_output.py` dedicated to "rich rendering output verification"
- Line 639: Component-to-location-to-test mapping confirms CLI UX tests exist
- Line 692: "Typer's transitive dependency on rich satisfies the UX spec's rendering requirements without additional deps"

### Alignment Issues

**None critical.** All 18 UX-DRs have explicit architectural support in `keys/cli/output.py` and/or explicit acceptance-criteria coverage in Epic 1/3/4 stories. No architectural capability is missing, and no UX requirement lacks a module/file destination.

### Warnings

1. **UX-DR17 (triple-click copy) is implementation-sensitive** — the "key plaintext on its own line at column 0 inside the panel" constraint is difficult to verify by unit test and will need manual validation during Story 1.2 implementation. The AC in Story 1.2 captures the requirement but a visual inspection is needed. (Recommendation: add a manual test step in Story 1.2's test plan or a pexpect-based integration test.)

2. **UX-DRs 13, 16, 18 (first-run hint, width adaptation, inline warning style) are not separately traced in the FR→Epic map** — they are covered via UX-DR references in story headers but do not carry their own FR numbers in the PRD. This is expected (they are UX-layer requirements, not functional) but later steps should verify stories 1.3 (first-run), 1.2 (key panel width behavior), and 1.6 (warning display) each assert these UX-DRs in acceptance criteria.

3. **UX J5 (Debug Session) and J6 (Complimentary Subscription) lack Mermaid flowcharts** — the UX spec includes only J1–J4 as flowcharts. J5 and J6 are referenced throughout in component variants and acceptance criteria, but a dedicated flow was not produced. Since epics cover the corresponding FRs (FR33 for counters/J5, FR9 for complimentary/J6), this is acceptable — but it means operators learn J5/J6 workflows from the PRD prose rather than the UX spec's visual flows.

4. **UX spec introduces requirements not in PRD** — `NO_COLOR` compliance, 80-column minimum width, first-run empty-state hints, color-vision-deficiency palette selection. These are additive (not conflicting) and accepted because they cost nothing extra given the `rich` library inheritance. Later steps should verify the relevant story acceptance criteria reference them.

## Epic Quality Review

### Best Practices Compliance Checklist

| Criterion | Epic 1 | Epic 2 | Epic 3 | Epic 4 |
|---|---|---|---|---|
| Delivers user value | ✅ Yes | ✅ Yes | ✅ Yes | ✅ Yes |
| Functions independently (within declared deps) | ✅ Standalone | ✅ Uses only Epic 1 | ✅ Uses only Epic 1 | ✅ Uses Epics 1–3 |
| Stories appropriately sized | ⚠ 1.1 oversized | ✅ Yes | ✅ Yes | ⚠ 4.5 oversized |
| No forward dependencies | ✅ Clean | ✅ Clean | ✅ Clean | ✅ Clean |
| Database tables created when needed | ⚠ All at once | N/A | N/A | N/A |
| Clear acceptance criteria | ✅ BDD format | ✅ BDD format | ✅ BDD format | ✅ BDD format |
| Traceability to FRs maintained | ✅ Covered in every story | ✅ Covered | ✅ Covered | ✅ Covered |

### Epic-by-Epic Assessment

#### Epic 1: Key Registry & Customer Management

**User value check:** ✅ Title and goal describe operator outcomes ("register customers," "issue API keys," "manage lifecycle," "view audit history"). Enables Journey 1 ("primeira venda"). Not a technical milestone.

**Independence check:** ✅ No forward dependencies. Stands alone as a shippable unit — an operator could use Epic 1 with `monetization_enabled=false` to manage a key registry without the new auth path.

**Story-level assessment:**

| Story | User Value | Independence | AC Format | Size |
|---|---|---|---|---|
| 1.1 Customer Registration with CPF/CNPJ Validation | ✅ Operator registers first customer | ✅ Foundation story, no deps | ✅ 7 Given/When/Then blocks | ⚠ Oversized (see below) |
| 1.2 API Key Issuance | ✅ Operator issues first key | ✅ Depends only on 1.1 | ✅ 4 G/W/T blocks | ✅ Focused |
| 1.3 Customer & Key Listing | ✅ Operator views portfolio | ✅ Depends on 1.1, 1.2 | ✅ 7 G/W/T blocks | ✅ Focused |
| 1.4 Key & Customer Detail View with Audit Trail | ✅ Operator troubleshoots | ✅ Depends on 1.1, 1.2 | ✅ 5 G/W/T blocks | ✅ Focused |
| 1.5 Customer Updates & Notes | ✅ Operator annotates customer | ✅ Depends on 1.1 | ✅ 3 G/W/T blocks | ✅ Focused |
| 1.6 Key Lifecycle (Update, Rotate, Revoke) | ✅ Operator manages key lifecycle | ✅ Depends on 1.2 | ✅ 5 G/W/T blocks | ⚠ Combines 3 verbs |

**🟡 Minor concern — Story 1.1 is oversized.** The scope note states it "establishes the entire foundation layer" and lists 10+ deliverables: creating the `keys/` subpackage, adding dependencies (typer, cryptography, python-ulid), extending `config.py`, adding 2 exception classes, implementing models, crypto, db, audit, CLI app, and the `create-customer` command. For a brownfield foundation story this is typical, but could be split into 1.1a (scaffolding + config + crypto primitives) and 1.1b (create-customer command + audit log). Not a blocker because the AC covers all scope items explicitly.

**🟡 Minor concern — Upfront schema creation in v001 migration.** Story 1.1 AC says "runs v001 migration (creates all tables + indexes)" — this creates `customer`, `api_key`, `audit_log`, and `schema_version` tables at once. The best-practices rule "Each story creates tables it needs" would prefer incremental migrations. However, SQLite's single-file nature makes upfront schema creation pragmatic: migrating per story would add significant complexity without practical benefit. Accepted trade-off; documented here so later reviews don't re-litigate.

**🟡 Minor concern — Story 1.6 combines 3 verbs (update/rotate/revoke).** They are thematically coherent (key lifecycle mutations) and the AC block is complete. Acceptable; could be split into 1.6a (update-key), 1.6b (rotate-key), 1.6c (revoke-key) for more granular sprint tracking but not required.

#### Epic 2: API Authentication & Dynamic Rate Limiting

**User value check:** ✅ Title is borderline technical ("API Authentication") but the goal clarifies the user outcome: "Customers authenticate HTTP requests with their per-customer API keys. Each key enforces its own rate limit." Enables Journeys 4 and 5. Not purely technical — delivers capability the customer observes (per-key rate limit, suspension hints).

**Independence check:** ✅ Declared "Depends on: Epic 1". No forward dependencies. Epic 2 stories use only Epic 1 outputs.

**Story-level assessment:**

| Story | User Value | Independence | AC Format | Size |
|---|---|---|---|---|
| 2.1 Registry-Based API Authentication | ✅ Customer auth works via registry | ✅ Depends on Epic 1 | ✅ 7 G/W/T blocks | ✅ Large but cohesive |
| 2.2 Dynamic Per-Key Rate Limiting | ✅ Per-key RPM enforcement | ✅ Depends on 2.1 | ✅ 5 G/W/T blocks | ✅ Focused |
| 2.3 Request Counters & Cache Management | ✅ Operator troubleshoots rate limits | ✅ Depends on 2.1 | ✅ 3 G/W/T blocks | ✅ Focused |

**🟠 Major issue — Story 2.3's cache-flush may not satisfy FR45 as written.** FR45 says "Operator can force an immediate auth-cache invalidation" — but the AC for cache-flush states: "the system prints: 'Cache TTL is 60 seconds. Changes propagate within that window.' and exits with code 0. And no actual cache manipulation occurs (architecture decision: accept 60s TTL)."

This is a **scope reduction** from the PRD requirement. The PRD's authentication-model section does soften it to "optional, for when a 60-second delay is unacceptable," but FR45 is still phrased as a binding operator capability.

**Remediation options:**

1. **Update FR45** — amend the PRD to say "Operator can verify cache invalidation behavior; immediate invalidation is not supported in MVP, 60-second TTL is the propagation bound." Makes the documented behavior match the implementation. Cleanest path.
2. **Implement real cache flush** — add a SIGHUP handler or IPC channel so `cache-flush` actually purges in-memory caches on all replicas. Higher complexity, real engineering work.
3. **Document as a known limitation** — keep AC as-is but add an explicit note in Story 2.3 and `docs/monetization.md` that this is a deliberate non-implementation of FR45. Pragmatic.

Recommendation: **option 1 (amend FR45)** — the architecture's pragmatic decision is sound, but the PRD text should be updated so the coverage claim remains honest. Today FR45 is "covered" in name only.

#### Epic 3: Billing & Revenue Operations

**User value check:** ✅ Title and goal describe operator outcomes ("track payments," "auto-suspend non-payers," "view revenue reports"). Enables Journeys 2, 3, 6. Pure business value, not technical.

**Independence check:** ✅ Declared "Depends on: Epic 1" only. Can ship without Epic 2 — `mark-paid` and `revenue` operate on the registry directly; the auth cache reactivation guarantee (FR20) only activates once Epic 2 ships. Acceptable because Epic 2 is also a hard dependency for shipping 2.0.0.

**Story-level assessment:**

| Story | User Value | Independence | AC Format | Size |
|---|---|---|---|---|
| 3.1 Payment Tracking (mark-paid, suspend, reactivate) | ✅ Monthly billing ritual | ✅ Depends on Epic 1 | ✅ 6 G/W/T blocks | ⚠ Combines 3 verbs |
| 3.2 At-Risk Queries & Revenue Reports | ✅ Visibility + pride moment | ✅ Depends on Epic 1, 3.1 | ✅ 5 G/W/T blocks | ✅ Focused |
| 3.3 Automated Suspension Sweep & Cron | ✅ Zero-touch enforcement | ✅ Depends on Epic 1 + bootstrap.yml | ✅ 5 G/W/T blocks | ✅ Focused |
| 3.4 System Health Command | ✅ Operator confidence | ✅ Depends on Epic 1 + 3.3 | ✅ 4 G/W/T blocks | ✅ Focused |

**🟡 Minor concern — Story 3.1 combines mark-paid, suspend, reactivate.** Thematically coherent (billing state mutations). Acceptable; splitting into 3 stories would fragment the FR15/FR19/FR20 block.

#### Epic 4: Security Hardening, LGPD & Operational Safety

**User value check:** ✅ All sub-goals have direct operator value — LGPD compliance (avoid ANPD fines), backup/restore (disaster recovery), non-regression (trust that security posture holds). Not purely technical.

**Independence check:** ✅ Declared "Depends on: Epics 1–3". Intentional — Epic 4 is the wrap-up that hardens the release. Correct ordering.

**Story-level assessment:**

| Story | User Value | Independence | AC Format | Size |
|---|---|---|---|---|
| 4.1 LGPD Data Operations (Export & Hard Delete) | ✅ LGPD compliance | ✅ Depends on Epic 1 | ✅ 5 G/W/T blocks | ⚠ Combines export + delete |
| 4.2 Encryption Key Rotation | ✅ Security operational need | ✅ Depends on Story 1.1 | ✅ 5 G/W/T blocks | ✅ Focused |
| 4.3 Backup & Restore Playbooks | ✅ Disaster recovery | ✅ Depends on Epic 1 | ✅ 4 G/W/T blocks | ⚠ Combines backup + restore |
| 4.4 Operational Safety & File Permissions | ✅ Multi-replica hardening | ✅ Depends on Epic 1+2+3 | ✅ 4 G/W/T blocks | ✅ Focused |
| 4.5 CI Non-Regression Security Suite | ✅ Prevent pentest regressions | ✅ Self-contained CI config | ✅ 7 G/W/T checks | 🟠 Oversized |
| 4.6 LGPD Documentation & Breach Runbook | ✅ Operator self-service compliance | ✅ Depends on Epic 1–3 features | ✅ 5 G/W/T blocks | ✅ Focused |

**🟠 Major issue — Story 4.5 is oversized.** Contains 7 distinct CI check implementations (FR46–FR51 + bandit): security headers, disabled docs, timing-safe comparison, oversized-body rejection, rate-limit middleware registration, no-raw-HTTPException, SQL-injection static analysis. Each CI check is an independently testable, independently implementable unit.

**Remediation options:**

1. **Split into 7 sub-stories (4.5a–4.5g)** — one per check. Each sub-story is one CI workflow addition. Enables incremental merging and isolated failure diagnosis.
2. **Keep as one story but define internal milestones** — acceptable if sprint planning tracks the 7 checks as sub-tasks.

Recommendation: **split into 4.5a–4.5g** during sprint planning. Each check maps to one FR (FR46, FR47, FR48, FR49, FR50, FR51 + the bandit one). Story authorship in `bmad-create-story` will likely do this naturally.

**🟡 Minor concerns:**

- **Story 4.1 combines export + delete** — both LGPD operations, acceptable grouping.
- **Story 4.3 combines backup + restore** — both are Ansible playbook work, acceptable grouping.

### Cross-Cutting Concern Observations

**🟡 FR30 (audit log) as implicit dependency.** Every mutation story (1.2, 1.5, 1.6, 3.1, 3.3, 4.1, 4.2) correctly asserts audit-log writes in acceptance criteria, but FR30 is formally "covered" by Story 1.1's foundation work. This means Story 1.1 MUST correctly implement the audit-log contract for every subsequent story to work. Recommendation: add a dedicated AC to Story 1.1 asserting audit-log record shape and append-only invariant, so later stories can trust the contract.

**🟡 FR29 (byte-identical public contract) is regression-style.** Story 2.1 carries it explicitly, but Epic 2 as a whole is implicitly constrained. This is consistent with the non-regression contract, but worth flagging for Story 2.2 and 2.3 to include "contract unchanged" assertions in their AC.

**🟡 FR33 (in-memory counters) depends on instance-local state.** Story 2.3 AC says "counters reset on service restart (not durable)". Clear communication of the non-durable nature. Later, review should ensure the `--audit-tail` output format makes this non-durability explicit to operators ("stats since last restart").

### Starter Template / Greenfield-vs-Brownfield Check

**Project is brownfield.** Architecture explicitly states: "Brownfield extension — no starter template. Extend existing codebase in-place within `src/comadre/`." Epic 1 Story 1.1 correctly acts as the "foundation" story for the brownfield extension rather than a starter-template clone. No violation.

Brownfield indicators present:
- Integration with existing `verify_api_key` dependency (Story 2.1) ✅
- Legacy `monetization_enabled=false` compatibility (Story 2.1, FR27) ✅
- Extension of existing Ansible playbooks rather than new ones (Stories 3.3, 4.4) ✅
- Reuse of existing `ComadreError` hierarchy (Story 1.1 extensions) ✅

### Quality Violations Summary

#### 🔴 Critical Violations

**None.** No epic is a pure technical milestone. No forward dependencies. No story is epic-sized-without-delivery-path. No circular dependencies.

#### 🟠 Major Issues

1. **FR45 coverage claim is not honest** — Story 2.3 cache-flush is a no-op; PRD needs amendment or the story needs real implementation. Recommend: amend PRD FR45.
2. **Story 4.5 CI Non-Regression Security Suite is 7 distinct deliverables in one story** — recommend splitting into 4.5a–4.5g during `bmad-create-story`.

#### 🟡 Minor Concerns

1. Story 1.1 is a large foundation story — acceptable for brownfield, but could be split for cleaner sprint tracking.
2. v001 migration creates all tables upfront rather than per-story — pragmatic for SQLite.
3. Story 1.6 combines update/rotate/revoke-key — could be split.
4. Story 3.1 combines mark-paid/suspend/reactivate — could be split.
5. Story 4.1 combines export + delete — acceptable LGPD grouping.
6. Story 4.3 combines backup + restore — acceptable Ansible grouping.
7. FR30 audit log contract is implicit foundation — recommend adding explicit AC to Story 1.1.
8. FR33 counters reset on restart — ensure operator-facing `show` output explicitly communicates the non-durable semantics.
9. UX-DR17 triple-click copy fidelity is hard to unit-test — add manual or pexpect-based verification step to Story 1.2.

### Actionable Recommendations for Remediation

**Before Story creation phase (`bmad-create-story`):**

1. **Decide FR45 resolution path** (amend PRD text OR expand Story 2.3 scope). Recommended: amend PRD text. Effort: 10 minutes.
2. **Plan splitting Story 4.5** into 4.5a through 4.5g (one per CI check). Can be done during sprint planning. Effort: 30 minutes.

**Optional improvements (non-blocking):**

3. Consider splitting Story 1.1 into 1.1a (scaffolding/config/crypto) and 1.1b (create-customer + audit log). Benefit: smaller sprint units; Cost: minor coordination overhead.
4. Add explicit FR30 audit-log-contract AC to Story 1.1.
5. Add manual/pexpect verification step to Story 1.2 for UX-DR17 (triple-click copy fidelity).

## Summary and Recommendations

### Overall Readiness Status

**🟢 READY (with 2 documented major items recommended before story authoring)**

The planning artifacts — PRD (52 FRs + 37 NFRs), Architecture (8 new modules + extensions to 4), UX Design (18 UX-DRs), and Epics (4 epics / 19 stories) — are coherent, traceable, and implementation-ready. Every PRD functional requirement has at least one story mapping (100% coverage). Every UX-DR has corresponding architectural support. No critical violations were found; no forward dependencies, no technical-milestone epics, no circular references. The 2 major issues identified are remediable in minutes and do not require architectural or planning rework.

### Readiness Scorecard

| Dimension | Finding | Status |
|---|---|---|
| Document completeness | All 4 required artifacts present (PRD, Architecture, Epics, UX) | ✅ |
| Duplicate-document conflicts | None — no whole/sharded conflicts | ✅ |
| FR coverage | 52/52 FRs mapped to epics (100%) | ✅ |
| NFR traceability | 37 NFRs present; referenced in architecture and story ACs | ✅ |
| Epic independence | All 4 epics functionally independent within declared dependency order | ✅ |
| Forward dependencies | None found | ✅ |
| Story sizing | 17/19 stories appropriately sized; 2 flagged (1.1, 4.5) | 🟡 |
| Acceptance-criteria quality | All 19 stories use Given/When/Then BDD structure with measurable outcomes | ✅ |
| UX ↔ PRD alignment | 100% — 3 additive UX extensions (NO_COLOR, width adaptation, first-run hints), no conflicts | ✅ |
| UX ↔ Architecture alignment | 18/18 UX-DRs have architectural support in `keys/cli/output.py` | ✅ |
| Non-regression contract coverage | 25+ controls enumerated in PRD, captured in Epic 4 Story 4.5 | ✅ |
| Brownfield integration | Existing `verify_api_key`, `ComadreError`, Ansible playbooks, Caddy config all properly extended | ✅ |
| Critical violations | 0 | ✅ |
| Major issues | 2 | 🟠 |
| Minor concerns | 9 | 🟡 |

### Critical Issues Requiring Immediate Action

**None.** Planning is ready to advance to sprint planning and story creation.

### Major Issues (Recommended Before Story Authoring)

1. **FR45 (cache-flush) coverage is not honest as written.** Story 2.3 AC makes `cache-flush` a no-op informational message, but FR45 says "Operator can force an immediate auth-cache invalidation." The architecture's pragmatic decision to accept the 60s TTL is reasonable, but the PRD text should be updated so the coverage claim matches reality.
   - **Recommended action:** Invoke `bmad-edit-prd` and amend FR45 to: "Operator can query auth-cache propagation behavior; immediate cross-replica invalidation is not supported in MVP — the 60-second TTL is the worst-case propagation bound. The `cache-flush` command documents this behavior to the operator."
   - **Effort:** 10 minutes.

2. **Story 4.5 (CI Non-Regression Security Suite) is 7 distinct CI deliverables in one story.** FR46–FR51 + bandit each merit their own story for granular sprint tracking and isolated failure diagnosis.
   - **Recommended action:** During `bmad-sprint-planning` or `bmad-create-story`, split 4.5 into 4.5a–4.5g (one per CI check). Each sub-story gets one FR and one CI workflow addition.
   - **Effort:** 30 minutes during sprint planning.

### Minor Concerns (Address Opportunistically)

3. Story 1.1 foundation scope is large — accepted as brownfield pattern; optional split into 1.1a (scaffolding) + 1.1b (create-customer) during sprint planning.
4. v001 migration creates all tables at once — pragmatic SQLite trade-off; documented to prevent re-litigation.
5. Stories 1.6, 3.1 each combine 3 CLI verbs — acceptable thematic grouping; optional split for finer sprint units.
6. Stories 4.1, 4.3 each combine 2 commands/deliverables — acceptable thematic grouping.
7. FR30 audit log contract is implicit foundation — recommend adding an explicit "audit-log record shape" AC to Story 1.1.
8. FR33 counters reset on restart — ensure `show` output communicates "stats since last restart" explicitly to operators.
9. UX-DR17 triple-click copy is hard to unit-test — add pexpect-based or manual verification step to Story 1.2.
10. UX J5 and J6 flows are referenced textually but not charted — optional backfill in UX spec.
11. UX adds NO_COLOR/width/first-run-hint requirements not in PRD — purely additive; ensure relevant stories reference the corresponding UX-DRs in their AC (already done).

### Recommended Next Steps

1. **Amend PRD FR45** to honest wording (invoke `bmad-edit-prd` with path `_bmad-output/planning-artifacts/prd.md`). 10 minutes.
2. **Commit existing untracked artifacts** — `architecture.md`, `epics.md`, and this readiness report must be tracked in git per project convention (`feedback_bmad_output_tracked.md`). Use `git add _bmad-output/planning-artifacts/` then commit with message like `docs(bmad): add 2.0.0 architecture, epics, and readiness assessment`.
3. **Invoke `bmad-sprint-planning`** to generate the sprint status tracking file from the 4 epics / 19 stories. Plan to split Story 4.5 into 4.5a–4.5g at this stage.
4. **Invoke `bmad-create-story`** for Story 1.1 first — the foundation story that unblocks all others. Treat this as the longest-running story in the sprint.
5. **Establish the CI regression-test skeleton early** — even before stories 4.5a–4.5g land, the test harness file (`tests/test_non_regression.py` or similar) can be scaffolded so future CI-check stories only add assertions.
6. **Consider optional PRD companion doc** — a short `docs/monetization-decisions.md` capturing the 60s-TTL trade-off, the brownfield foundation-story pattern, and the upfront-migration pragmatism. Prevents future "why didn't we do this the textbook way?" questions.

### Final Note

This assessment identified **11 issues across 3 severity tiers**: 0 critical, 2 major, 9 minor. The 2 major items (FR45 amendment + Story 4.5 split) are remediable in under an hour of combined effort and do not require architectural or planning rework. Address the major items before or during sprint planning, triage the minor concerns opportunistically, and proceed confidently to implementation.

**The planning phase for Comadre 2.0.0 is ready to transition to Phase 4 (Implementation).**

---

*Report generated: 2026-04-16 by the BMad `bmad-check-implementation-readiness` skill. Assessor role: expert Product Manager specializing in requirements traceability. All findings backed by explicit cross-references to PRD/UX/Architecture/Epics documents.*

---

## Amendments Since Publication

### 2026-04-16 — Major Issue #1 resolved (FR45 coverage honesty)

**Action:** PRD amended via `bmad-edit-prd` skill.

**Changes propagated:**

- **`prd.md`**
  - FR45 rewritten to honestly describe MVP capability (read-only cache-status query; no forced invalidation; 60s TTL is the worst-case propagation bound).
  - §Authentication Model cache-invalidation paragraph rewritten; adds restart as the escape hatch for faster propagation.
  - §CLI Tool Specification command listing updated — `cache-flush` renamed to `cache-status` with accurate inline description.
  - Frontmatter: added `step-e-01-discovery`, `step-e-02-review`, `step-e-03-edit` to `stepsCompleted`; `lastEdited: 2026-04-16`; `editHistory` entry documenting driver (this report's §Major Issues #1).

- **`architecture.md`**
  - Important Decisions list: "Cache flush mechanism" → "Cache invalidation model (accept 60s TTL bound; expose `cache-status` CLI for observability, no mutation)".
  - §Cache Flush section renamed to §Cache Invalidation; text rewritten to describe `cache-status` as read-only and explain the rename rationale.
  - All `cache-flush` CLI references in Module Structure and File Manifest renamed to `cache-status`.

- **`epics.md`**
  - Additional Requirements: cache-flush bullet rewritten; documents rename and restart escape hatch.
  - Requirements Inventory FR45 definition updated to match the amended PRD text.
  - FR Coverage Map FR45 row updated: "Force immediate auth-cache invalidation" → "Report auth-cache TTL propagation bound via `cache-status` CLI (read-only)".
  - Story 2.3 AC block replaced: command renamed to `cache-status`; AC language reflects read-only observability; adds a second `--format json` AC covering the `ttl_seconds` machine-readable output.

**Remaining Major Issue #2 (Story 4.5 split) — NOT yet addressed.** Will be handled during `bmad-sprint-planning` when stories 4.5a–4.5g are authored individually. No PRD or architecture change required for that remediation.

**Current status:** Planning artifacts are now internally consistent. The FR45 coverage claim is honest, the command name signals read-only semantics, and all downstream artifacts (architecture, epics) match the PRD. The implementation readiness verdict remains 🟢 READY.
