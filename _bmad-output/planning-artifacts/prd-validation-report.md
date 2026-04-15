---
validationTarget: '_bmad-output/planning-artifacts/prd.md'
validationDate: '2026-04-15'
inputDocuments:
  - _bmad-output/project-context.md
  - docs/api-architecture.md
  - docs/api-reference.md
  - docs/configuration-reference.md
  - docs/deployment-guide.md
validationStepsCompleted: ['step-v-01-discovery', 'step-v-02-format-detection', 'step-v-03-density-validation', 'step-v-04-brief-coverage-validation', 'step-v-05-measurability-validation', 'step-v-06-traceability-validation', 'step-v-07-implementation-leakage-validation', 'step-v-08-domain-compliance-validation', 'step-v-09-project-type-validation', 'step-v-10-smart-validation', 'step-v-11-holistic-quality-validation', 'step-v-12-completeness-validation']
validationStatus: COMPLETE
holisticQualityRating: '5/5 — Excellent'
overallStatus: PASS
polishApplied: '2026-04-15 — FR23, FR39, NFR20, NFR23 edited per Top-3-Improvements recommendations 1 and 3'
---

# PRD Validation Report

**PRD Being Validated:** `_bmad-output/planning-artifacts/prd.md`
**Validation Date:** 2026-04-15
**Project:** Comadre 2.0.0 (customer-scoped API-key management and recurring billing)

## Input Documents

Loaded from PRD frontmatter (all verified to exist):

- `_bmad-output/project-context.md` — Project context (14 KB)
- `docs/api-architecture.md` — Architecture reference (13 KB)
- `docs/api-reference.md` — API reference (9 KB)
- `docs/configuration-reference.md` — Config reference (7 KB)
- `docs/deployment-guide.md` — Deployment guide (22 KB)

**Classification (from PRD frontmatter):**
- Project Type: `api_backend` (primary), `cli_tool` (secondary)
- Domain: `general` with `fintech-adjacent` overlay
- Complexity: `medium`
- Context: `brownfield`

## Validation Findings

## Format Detection

**PRD Structure (all Level 2 headers, in order):**

1. Executive Summary (line 32)
2. Project Classification (line 61)
3. Success Criteria (line 69)
4. Product Scope (line 159)
5. User Journeys (line 214)
6. Domain-Specific Requirements (line 599)
7. API Backend & CLI Tool Specific Requirements (line 769)
8. Project Scoping & Phased Development (line 1032)
9. Functional Requirements (line 1115)
10. Non-Functional Requirements (line 1193)

**BMAD Core Sections Present:**

- Executive Summary: **Present** (line 32)
- Success Criteria: **Present** (line 69)
- Product Scope: **Present** (line 159)
- User Journeys: **Present** (line 214)
- Functional Requirements: **Present** (line 1115)
- Non-Functional Requirements: **Present** (line 1193)

**Additional sections (BMAD-aware extensions):**

- Project Classification — frontmatter classification surfaced as a body section
- Domain-Specific Requirements — fintech-adjacent overlay (Pix/boleto/NFSe, LGPD)
- API Backend & CLI Tool Specific Requirements — project-type-specific section
- Project Scoping & Phased Development — explicit MVP/Growth/Vision phasing

**Format Classification:** BMAD Standard
**Core Sections Present:** 6/6

## Information Density Validation

**Anti-Pattern Violations:**

- **Conversational Filler:** 0 occurrences (scanned: "the system will allow", "it is important to note", "in order to", "for the purpose of", "with regard to")
- **Wordy Phrases:** 0 occurrences (scanned: "due to the fact that", "in the event of", "at this point in time", "in a manner that", "in spite of the fact")
- **Redundant Phrases:** 0 occurrences (scanned: "future plans", "past history", "absolutely essential", "completely finish", "end result", "final outcome", "advance planning", "free gift")
- **Additional patterns scanned:** "in addition to", "as a matter of fact", "needless to say", "when all is said", "each and every", "first and foremost", "null and void" — 0 occurrences

**Total Violations:** 0

**Severity Assessment:** Pass

**Recommendation:** PRD demonstrates excellent information density with zero anti-pattern violations. The author has produced concise, direct prose throughout 1,248 lines — a notable result for a document of this size.

## Product Brief Coverage

**Status:** N/A — No Product Brief was provided as input. PRD frontmatter lists `briefs: 0`. Inputs were `project-context.md` and 4 brownfield reference docs (api-architecture, api-reference, configuration-reference, deployment-guide).

## Measurability Validation

### Functional Requirements

**Total FRs Analyzed:** 52 (FR1–FR52, lines 1115–1191)

**Format Violations:** 0
- All 52 FRs follow `[Actor] can [capability]` or `System [capability]` patterns.
- Actors used: `Operator`, `Customer`, `System`, `CI` — all clearly defined.

**Subjective Adjectives Found in FR/NFR sections:** 0
- Sole "fast enough" occurrence (line 346) is in User Journeys, qualified with a metric `(< 60s)`. Not a violation.

**Vague Quantifiers in FR/NFR sections:** 3 minor
- Line 1180 (FR44): "multiple Comadre replicas" — contextually means ≥2; bounded elsewhere by NFR25 (1,000 customers, 2,000 keys).
- Line 1234 (NFR29): "multiple container replicas" — same pattern, acceptable.
- Line 1240 (NFR32): "running ... multiple times" — idempotency context, "multiple" = ≥2 by definition. Acceptable.

**Implementation Leakage:** 6 instances, all justified for brownfield context
- NFR9: `SHA-256` (named primitive); NFR10: `Fernet`; NFR11: `hmac.compare_digest`; NFR23/NFR29: `WAL mode`; FR21: `Bearer`; FR46/FR52: `Caddy`/`Ansible`.
- **Verdict:** acceptable. NFR9 explicitly documents that "the cryptographic primitive choice is documented in `docs/monetization.md` and changes require an encryption-rotation playbook" — primitive choice is a deliberate, traceable spec, not implementation drift. For a brownfield project layering features onto an existing stack (SQLite, Caddy, Ansible already deployed), naming the existing tech sharpens the spec rather than leaking implementation.

**FR Violations Total:** 3 (all minor, all `multiple` quantifier; no hard violations)

### Non-Functional Requirements

**Total NFRs Analyzed:** 37 (NFR1–NFR37, lines 1193–1248)

**Missing Metrics:** 0
- All performance NFRs (NFR1–NFR7) include explicit thresholds (`< 5ms p99`, `< 200ms`, `< 1 second`, etc.) and the database-size baseline (`1,000-customer database`).
- All recovery NFRs (NFR21, NFR22) include RTO/RPO numbers (`under 10 minutes`, `must not exceed 24 hours`).
- All scalability NFRs (NFR25–NFR29) bound footprint (`under 50 MB`) and capacity (`1,000 active customers, 2,000 active keys`).
- All compliance NFRs (NFR34–NFR36) include LGPD article references and time bounds (`under 15 days`).

**Incomplete Template:** 0
- Each NFR carries criterion + metric + (where applicable) measurement method or baseline. Examples: NFR1 names p99 percentile and database-size baseline; NFR21 names the playbook (`restore-keys.yml`) as the measurement vehicle.

**Missing Context:** 0
- Every NFR cluster has explanatory sentences nearby explaining *why this matters* and *who it affects*. NFR18 traces the latency SLA back to `CLAUDE.md` and `project-context.md`. NFR34–NFR37 cite specific LGPD/CDC articles.

**NFR Violations Total:** 0

### Overall Assessment

**Total Requirements:** 89 (52 FRs + 37 NFRs)
**Total Violations:** 3 (all minor `multiple` quantifier instances; zero hard violations)

**Severity:** Pass

**Recommendation:** Requirements demonstrate exceptional measurability — every NFR carries a numeric bound or behavioral identity contract, and every FR is testable. The three `multiple` instances are contextually clear and don't warrant rework. The implementation-leakage instances are explicitly justified by the brownfield context and traceable through `docs/monetization.md`. No revisions required for measurability; downstream architecture work can take the FR/NFR set as-is.

## Traceability Validation

### Chain Validation

**Executive Summary → Success Criteria:** Intact
- Vision (Comadre 2.0.0 = customer-scoped key mgmt + recurring billing for solo VPS operators) directly maps to Success Criteria sections: User Success (operator <60s onboarding, customer transparent auth), Business Success (R$500–1500 MRR at 3mo, <15% churn), Technical Success (under 5ms p99 auth, under 50MB footprint), Operational Success (Ansible bootstrap integration).
- Each "What Makes This Special" claim (radical operational simplicity, self-contained shards, infrastructure-transparent pricing, billing-as-adapter, dynamic per-key rate limits) appears as a measurable Success criterion.

**Success Criteria → User Journeys:** Intact
- Operator success criteria → J1 (first sale), J2 (recurring collection), J3 (delinquent customer), J5 (debug session), J6 (complimentary subscription).
- Operator-customer success criteria → J4 (API consumer happy path).
- "Aha! moments" → J2 (revenue --month current shows the sum) and J4 (key works identically to pre-monetization).
- Business success table → J2 (the day-05 collection ritual is the entire revenue thesis).

**User Journeys → Functional Requirements:** Intact
- The PRD provides an explicit author-built **Journey Requirements Summary** (lines 555–597) mapping every capability area to one or more journeys (J1–J6). This is a journey→FR-cluster traceability matrix already in the document.
- Mapping by FR cluster:
  | FR Cluster | Lines | Trace |
  |---|---|---|
  | Customer Lifecycle (FR1–FR7) | 1117–1125 | J1, J3 |
  | API Key Lifecycle (FR8–FR14) | 1127–1135 | J1, J3, J5, J6 |
  | Billing State (FR15–FR20) | 1137–1144 | J2, J3, J6 |
  | Auth & Rate Limiting (FR21–FR29) | 1146–1156 | J4, J5 |
  | Observability & Auditing (FR30–FR34) | 1158–1164 | J2, J5 |
  | LGPD Compliance (FR35–FR39) | 1166–1172 | Domain Requirements + Scope Epic 2 (intentional) |
  | Operational Safety (FR40–FR45) | 1174–1181 | Operational Success criteria + Scope Epic 2 |
  | Security Regression (FR46–FR52) | 1183–1191 | Non-regression contract (Domain Requirements §Continuity with Existing Hardening) + Scope Epic 2 |

**Scope → FR Alignment:** Intact
- Epic 1 (Monetization Core) ↔ FR1–FR34 — feature work driven by user journeys.
- Epic 2 (Security & Compliance) ↔ FR35–FR52 — explicitly carved as a dedicated security epic; FRs trace to Domain Requirements and the non-regression contract rather than user journeys (a deliberate, documented architectural choice).
- Growth (2.1+) and Vision (2.2+) sections do not yet have FRs — correct deferral.

### Orphan Elements

**Orphan Functional Requirements:** 0
- FR35–FR52 are not journey-traced but are explicitly traced to Domain Requirements (LGPD, fintech-adjacent overlay) and Scope Epic 2 (Security & Compliance). The PRD's choice to carve Epic 2 as compliance/regression-driven (not journey-driven) is sound: every FR ties to either a user journey OR a documented compliance/security obligation.
- The PRD even acknowledges this in the Journey Requirements Summary row: "LGPD compliance | `delete-customer --hard` with CPF/CNPJ purge | (implicit, required by scope)".

**Unsupported Success Criteria:** 0
- Every success criterion either ties to a journey (operator/customer success), a measurable outcome (business success table), or a quality gate (technical success, operational success).

**User Journeys Without FRs:** 0
- All 6 journeys have FR clusters that enable them. The Journey Requirements Summary makes this explicit.

### Traceability Matrix Summary

| Trace dimension | Coverage |
|---|---|
| Executive Summary → Success Criteria | 100% — every vision claim has a measurable criterion |
| Success Criteria → User Journeys | 100% — all 4 success dimensions have journey support |
| User Journeys → FRs (journey-driven FRs) | 34/34 — FR1–FR34 fully mapped via author's summary table |
| Compliance/Regression FRs → Domain Requirements + Scope | 18/18 — FR35–FR52 traced to Epic 2 / Domain Requirements |
| Scope → FRs | 100% — both MVP epics carry their FR sets |

**Total Traceability Issues:** 0

**Severity:** Pass

**Recommendation:** Traceability is the strongest dimension of this PRD. The author-built Journey Requirements Summary preempts the most common downstream gap (FR-to-journey orphans), and the deliberate Epic 1/Epic 2 split makes explicit which requirements are user-driven vs. compliance/regression-driven. Architecture and epic-decomposition work can rely on this mapping directly — no orphan FRs to chase down, no journeys missing capability support.

## Implementation Leakage Validation

**Scope:** Lines 1115–1248 (FR1–FR52 and NFR1–NFR37 only). Mentions of implementation terms outside FR/NFR sections (Executive Summary, Scope, Domain Requirements) are intentional architectural framing, not leakage.

### Classification of FR/NFR Implementation Term Mentions

| Category | Count | Examples (line) | Verdict |
|---|---|---|---|
| **Capability-relevant** (the term IS the contract) | 6 | `Bearer API key` (FR21, FR22), `/v1/audio/speech`, `/health`, `/docs`, `/redoc`, `/openapi.json` (FR21, FR29, FR47, NFR30), `comadre-keys` CLI (NFR33), legacy `API_KEY` env var (FR27, NFR31) | Acceptable — these are the public interface contract |
| **Brownfield-justified** (naming existing infrastructure being extended) | 6 | `Caddy` (FR46), `Ansible health.yml` (FR52), `Ansible bootstrap.yml`/`update.yml` (NFR32), `SQLite` file as persistent store (FR42, FR44, NFR13, NFR29) | Acceptable — the requirement is "extend existing X", naming X is necessary |
| **Deliberate documented primitive specs** (with `or stronger`/`or equivalent` hedge) | 3 | `SHA-256 (or stronger)` (NFR9), `Fernet (or a stronger authenticated-encryption primitive)` (NFR10), `timing-safe primitives (hmac.compare_digest or equivalent)` (NFR11) | Acceptable — NFR9 explicitly states primitive choice is a documented spec in `docs/monetization.md` requiring an encryption-rotation playbook to change. The `or stronger` hedge prevents lock-in. |
| **Minor leakage** (could be abstracted, but no harm) | 4 | `caches ... in memory` (FR23, line 1150), `hmac.compare_digest` named without hedge in NFR11, `WAL mode` (NFR20, NFR23 — names a SQLite-specific journaling mode) | Borderline — abstraction would read e.g., "the suspension cron must not block concurrent auth-path reads" instead of "WAL mode guarantees..." |

### Leakage by Workflow Category

- **Frontend Frameworks:** 0 violations
- **Backend Frameworks:** 0 violations (no `FastAPI` in FR/NFR sections)
- **Databases (SQLite):** 6 mentions, all brownfield-justified (extending the existing storage layer)
- **Cloud Platforms:** 0 violations
- **Infrastructure (Caddy, Ansible):** 3 mentions, all brownfield-justified
- **Libraries (`hmac.compare_digest`, slowapi):** 1 named in NFR11 with `or equivalent` hedge; slowapi not directly named in FR/NFR
- **Cryptographic Primitives (SHA-256, Fernet):** 2 mentions, both with `or stronger` hedge and documented spec rationale
- **Protocols (HTTP, REST, GraphQL):** all `HTTP`/`Bearer` mentions are capability-relevant (RFC standards used as contract terms)
- **Other Implementation Details:** WAL mode (2 instances), in-memory cache (1) — see "Minor leakage" row above

### Summary

**Total Implementation Leakage Violations (strict count):** 4 (the "Minor leakage" row)
**Total mentions of named tech (broad count):** 19 across 89 requirements

**Severity:** Warning (per the workflow's count-based scale: 2–5 = Warning)

**Recommendation:** The Warning classification reflects the literal count, but the substance is closer to Pass for this brownfield context. Three observations:

1. **Brownfield context warrants different calibration.** The workflow's severity scale (Pass <2, Warning 2–5, Critical >5) is calibrated for greenfield projects. Naming `Caddy`, `Ansible`, and `SQLite` is the only way to specify "extend the existing X" precisely — abstracting these would weaken the requirements, not strengthen them.

2. **The 3 cryptographic primitives are a deliberate spec, not leakage.** NFR9/NFR10 use the `(or stronger)` hedge and explicitly state that primitive choice is a documented spec. Architects downstream get a concrete starting point with sanctioned upgrade paths.

3. **The 4 minor-leakage instances are worth a light pass before architecture work**, but none are blockers:
   - **FR23** (line 1150): "caches valid authorizations in memory" → could read "caches valid authorizations to satisfy NFR1 latency". The current phrasing is fine for a brownfield team.
   - **NFR11** (line 1210): `hmac.compare_digest` is named as the primitive but `(... or equivalent)` is missing. Could add the hedge to match NFR9/NFR10's pattern.
   - **NFR20** (line 1222): "via SQLite WAL mode" → "without registry corruption from unclean shutdown". WAL mode is an architecture choice, not a requirement.
   - **NFR23** (line 1225): "WAL mode guarantees single-writer-many-reader behavior" → "the suspension cron must not block concurrent auth-path reads". Same abstraction.

**Action:** Optional — apply the 4 minor abstractions in NFR11/NFR20/NFR23 (and optionally FR23) before downstream architecture work begins. Architects can otherwise consume this PRD as-is.

## Domain Compliance Validation

**Domain (frontmatter):** `general`
**Domain Overlay (frontmatter):** `fintech-adjacent`
**Workflow CSV complexity for `general`:** Low (no special sections required)
**De facto complexity:** Medium-High (the PRD self-elevates to fintech-adjacent treatment due to LGPD-covered tax-IDs, recurring billing semantics, and Pix/boleto/NFSe-aware scope decisions)

### Required Special Sections — Fintech-Adjacent Treatment (voluntary, exceeds `general` baseline)

| Required Section | Status | Evidence |
|---|---|---|
| Compliance Matrix | **Present & Adequate** | LGPD subsection (lines 603–616) cites 7 specific articles (Art. 5, VI; Art. 7, V; Art. 18, II; Art. 18, V; Art. 18, VI; Art. 48; data-retention rule) with concrete CLI commands fulfilling each. CDC consumer-protection (line 622). Out-of-scope items explicitly listed (lines 759–763): PCI-DSS, Open Banking, KYC/AML, GDPR, multi-region data residency. |
| Security Architecture | **Present & Adequate** | "Continuity with Existing Hardening" (lines 626–683) — five 4-column control tables (External Attack Surface, Auth & Rate Limiting, Error Handling, Module Boundaries, Deployment & Ops) covering ~40 individual controls with source-of-truth and verification method per row. Plus "Technical Constraints — Security boundaries" (lines 685–696) with 8 explicit boundaries. |
| Audit Requirements | **Present & Adequate** | `audit_log` append-only table specified (line 167, FR30, FR31, FR32). Audit-log retention rules in LGPD section (line 612: event metadata retained, personal data purgeable). Tampering detection (line 695: nightly backup comparison + append-only discipline). FR38 preserves audit metadata after personal data purge. |
| Fraud Prevention | **Present & Adequate** | Timing-safe lookup (NFR11, NFR12, line 693), SHA-256 + `hmac.compare_digest` with dummy-comparison-on-miss to equalize timing (lines 693, 744). Enumeration resistance (lines 706–710). Per-IP rate limit on failed auth (FR25, NFR15). Risk Mitigations table (lines 738–755) catalogs 16 risk vectors with mitigation + residual exposure. |
| Data Privacy / LGPD | **Present & Adequate** | Section §LGPD (lines 603–616) is a complete LGPD treatment: legal basis, data minimization, encryption at rest with named primitive, all rights (deletion, access, breach notification), retention rule, controller identification. FR35–FR39 codify the LGPD primitives as testable requirements. |
| Risk Register | **Present & Adequate** | Risk Mitigations table (lines 738–755) — 16 named risks, each with a mitigation strategy and residual exposure assessment. Includes infrastructure (SQLite corruption, encryption key loss), security (timing attacks, enumeration, SQL injection), operational (cron drift, concurrent writes), and compliance (ANPD audit, regression of pentest-resolved controls). |
| Out-of-Scope Compliance | **Present & Adequate** | Explicit list (lines 757–763): PCI-DSS delegated to PSP; Open Banking/Pix Automático delegated to PSP adapters; KYC/AML is operator's business process; GDPR (EU) explicitly out of market scope; multi-region data residency N/A. Each exclusion has a rationale, not just a bullet. |
| Epic Mapping | **Present & Adequate** | Lines 765–767: explicit statement that every row in the non-regression contract maps to acceptance criteria in Epic 2 stories. Preempts the common gap where compliance sections are written but never become stories. |

### Compliance Matrix Summary

| Requirement | Status | Notes |
|---|---|---|
| LGPD Art. 5 (controller ID) | Met | Line 616: operator is the controller, software is a tool |
| LGPD Art. 7, V (legal basis) | Met | Line 609: "execução de contrato" |
| LGPD Art. 18, II/V (right to access) | Met | FR6 + line 613: `export-customer --format json` |
| LGPD Art. 18, VI (right to deletion) | Met | FR5 + line 612: `delete-customer --hard` |
| LGPD Art. 48 (breach notification) | Met | NFR36 + line 614: runbook documented |
| Data minimization | Met | Line 610: schema stores only billing-essential fields |
| Encryption at rest (sensitive fields) | Met | NFR10 + line 611: `cryptography.fernet`, key in env |
| CDC proportionality | Met | NFR37 + line 622: suspended-not-deleted contract |
| Audit traceability post-purge | Met | FR38: audit-log metadata preserved |
| Pentest non-regression | Met | Lines 626–683: full controls table; FR46–FR52 codify CI verification |
| PCI-DSS | N/A (out of scope, delegated to PSP) | Line 759 |
| Open Banking / Pix Automático | N/A (out of scope, delegated to PSP) | Line 760 |
| KYC/AML | N/A (operator's business process) | Line 761 |
| GDPR | N/A (Brazilian market only) | Line 762 |

### Summary

**Required Sections Present:** 8/8 (fintech-adjacent treatment)
**Compliance Gaps:** 0
**Out-of-scope items with rationale:** 5/5

**Severity:** Pass (with distinction)

**Recommendation:** Domain compliance treatment is exemplary. The PRD self-elevates from `general` to fintech-adjacent treatment voluntarily, providing full LGPD primitives, a 5-table non-regression contract, a 16-row risk register, and explicit epic-mapping that prevents compliance sections from becoming orphan-prose. No gaps. No additional work required for downstream architecture or epic decomposition — the security/compliance epic (Epic 2) can be derived directly from this section.

## Project-Type Compliance Validation

**Project Type (frontmatter):** `api_backend` (primary) + `cli_tool` (secondary)

The PRD wraps both project-type requirements into one §API Backend & CLI Tool Specific Requirements section (lines 769–1031), preceded by a §Project-Type Overview that explains the api/CLI split.

### Required Sections — `api_backend`

| Required Section (per CSV) | Status | Evidence |
|---|---|---|
| `endpoint_specs` | **Present & Adequate** | §Endpoint Specification (lines 778–805) with explicit "MVP", "Explicitly NOT in MVP", and "Growth path (2.1+)" tables |
| `auth_model` | **Present & Adequate** | §Authentication Model (lines 807–838) with full auth-flow ASCII diagram, guarantees enumeration, and backward-compat migration mode |
| `data_schemas` | **Present & Adequate** | §Data Schemas (lines 839–894) with full SQLite DDL (3 tables + 4 indexes) and pydantic request models |
| `error_codes` | **Present & Adequate** | §Error Codes (lines 896–917) with full status-code table mapping HTTP code to `type` and source, plus 5 new `ComadreError` subclasses |
| `rate_limits` | **Present & Adequate** | §Rate Limits (lines 919–934) with per-endpoint defaults, key-function names, and dynamic-limit resolution semantics |
| `api_docs` | **Present & Adequate** | §API Documentation (lines 936–948) explains the deliberate `openapi.json`-disabled posture (pentest finding `adcb431`) and lists prose-form alternatives |

### Required Sections — `cli_tool`

| Required Section (per CSV) | Status | Evidence |
|---|---|---|
| `command_structure` | **Present & Adequate** | §CLI Tool Specification > Command structure (lines 952–982) with full Typer subcommand listing |
| `output_formats` | **Present & Adequate** | §Output formats (lines 984–989) covering `rich` tables, `--format json` (NDJSON), `--format yaml`, exit-code semantics, and stderr error envelope shape |
| `config_schema` | **Present & Adequate** | §Config method (lines 991–995) lists every env var the CLI consumes (`KEY_REGISTRY_DB_PATH`, `KEY_REGISTRY_ENCRYPTION_KEY`, `OPERATOR_CONTACT_HINT`, `BILLING_DAY`, `BILLING_TIMEZONE`) and the `pydantic-settings` shared-loading guarantee |
| `scripting_support` | **Present & Adequate** | §Scripting support (lines 997–1005) covers non-interactive defaults, `--yes` for confirmation skip, canonical health-check and at-risk queries, and shell completion |

### Excluded Sections — `api_backend` skip list

| Excluded Section | Status | Notes |
|---|---|---|
| `ux_ui` | **Absent** ✓ | No UI sections present (the landing page is only mentioned as a static Caddy-served unchanged element) |
| `visual_design` | **Absent** ✓ | No visual design language, mockups, or component library references |
| `user_journeys` | **Present** — but justified by `cli_tool` secondary type | The 6 user journeys (lines 214–598) are operator workflows for the CLI surface (J1 "first sale", J2 "day-05 collection ritual", J3 "delinquent customer", J5 "debug session", J6 "infrastructure bundle") plus J4 specifically for the API consumer. For dual-typed `api_backend`+`cli_tool` projects, user_journeys are essential to specify the operator workflow even when the api_backend skip list excludes them. The CSV's `cli_tool` row does not exclude user_journeys. The PRD treats this correctly. |

### Excluded Sections — `cli_tool` skip list

| Excluded Section | Status | Notes |
|---|---|---|
| `visual_design` | **Absent** ✓ | No visual design content |
| `ux_principles` | **Absent** ✓ | No UX-principles section beyond minimal usability concerns embedded in command structure |
| `touch_interactions` | **Absent** ✓ | No touch/mobile considerations (correctly — this is a CLI tool over SSH) |

### Compliance Summary

**Required Sections (api_backend):** 6/6 present
**Required Sections (cli_tool):** 4/4 present
**Excluded Sections present (api_backend):** 1 (user_journeys — justified by cli_tool secondary type)
**Excluded Sections present (cli_tool):** 0
**Compliance Score:** 100% (with the user_journeys nuance documented)

**Severity:** Pass

**Recommendation:** Project-type compliance is excellent. The PRD handles a dual-typed project (`api_backend` + `cli_tool`) correctly by satisfying both required-section sets in a single dedicated section (lines 769–1031). The user_journeys "violation" of the api_backend skip list is appropriate because the cli_tool secondary type does not exclude journeys, and the journeys themselves are CLI-operator-workflow-focused rather than API-consumer-screen-flows. No action required.

## SMART Requirements Validation

**Total Functional Requirements:** 52 (FR1–FR52)

### Scoring Summary

**All scores ≥ 3:** 100% (52/52)
**All scores ≥ 4:** 98% (51/52 — only FR39 dips to 3 in Specific/Measurable)
**Overall Average Score:** 4.7/5.0

### Scoring by Cluster

Detailed scoring grouped by FR cluster (all FRs in a cluster share the same scores unless individually flagged below).

| FR Cluster | FRs | Specific | Measurable | Attainable | Relevant | Traceable | Avg | Notes |
|---|---|---|---|---|---|---|---|---|
| Customer Lifecycle | FR1–FR7 | 5 | 5 | 5 | 5 | 5 | 5.0 | Crisp `Operator can ...` actions; FR2 names "Brazilian checksum validation" which is testable; FR5 cites LGPD article |
| API Key Lifecycle | FR8–FR14 | 5 | 5 | 5 | 5 | 5 | 5.0 | Each verb (issue, update, rotate, revoke, list, view) maps to a Typer subcommand in §CLI Tool Specification |
| Billing State Mgmt | FR15–FR20 | 5 | 5 | 5 | 5 | 5 | 5.0 | FR18 is exemplary: "automatically suspends ... once per day, at a configurable operator-timezone time" — fully specific |
| API Auth & Rate Limiting | FR21–FR29 | 5 | 5 | 5 | 5 | 5 | 5.0 | Strongest cluster — every FR has a measurable observable behavior; FR26 ("equalizes timing") is testable via timing benchmark |
| Observability & Auditing | FR30–FR34 | 5 | 4 | 5 | 5 | 5 | 4.8 | FR33's stat counters are explicitly "not durable, reset on service restart" — specificity excellent; Measurable=4 because counter values aren't bounded by a numeric SLA |
| LGPD Compliance | FR35–FR38 | 5 | 5 | 5 | 5 | 5 | 5.0 | Each FR ties to a specific LGPD article + a CLI command; FR37 ("prevents personal data ... regardless of log verbosity") is CI-testable |
| LGPD — FR39 only | FR39 | **3** | **3** | 5 | 5 | 4 | 4.0 | "Operator receives documented guidance ... including a breach-notification runbook and a privacy-policy template" — guidance/runbook quality is harder to measure than capability presence. Acceptance test would be: does `docs/monetization.md` contain the named runbook section? |
| Operational Safety | FR40–FR45 | 5 | 5 | 5 | 5 | 5 | 5.0 | FR40 names the artifact format ("single encrypted archive separate from database file"); FR43 names the queryable timestamp; FR44 has WAL-mode backing |
| Security Regression CI | FR46–FR52 | 5 | 5 | 5 | 5 | 5 | 5.0 | Each FR is a CI verification task with a binary pass/fail outcome — testability is inherent. The Continuity-with-Existing-Hardening tables (lines 626–683) provide explicit verification mechanisms |

### Per-FR Detail (Flagged FRs Only)

**FR39** (line 1172): "Operator receives documented guidance on their LGPD controller obligations, including a breach-notification runbook and a privacy-policy template."

| Dimension | Score | Notes |
|---|---|---|
| Specific | 3 | "Documented guidance" is broad; "breach-notification runbook" and "privacy-policy template" are named but not scoped (length, sections, examples?) |
| Measurable | 3 | Acceptance criterion would need to enumerate required runbook subsections (e.g., "must include: ANPD contact, customer notification template, evidence-preservation steps, internal escalation path") |
| Attainable | 5 | Documentation work, no technical risk |
| Relevant | 5 | Maps directly to LGPD Art. 48 obligation |
| Traceable | 4 | Traces to Domain Requirements §LGPD breach-notification and §Compliance Matrix |

### Improvement Suggestions

**FR39** — Tighten Specific and Measurable by adding an acceptance criterion that enumerates the runbook contents:

> **FR39 (refined):** Operator receives a `docs/monetization.md` § "LGPD Operator Obligations" containing: (a) a breach-notification runbook with ANPD contact information, a customer-notification email template, an evidence-preservation checklist, and an escalation path; (b) a privacy-policy template paragraph the operator can adapt for their own terms of service.

This converts a documentation requirement into a structured-content requirement that an editorial review (e.g., `bmad-editorial-review-structure`) can evaluate against a section checklist.

### Overall Assessment

**Severity:** Pass

**Recommendation:** Functional Requirements demonstrate exceptional SMART quality. 51/52 FRs score 4–5 across all five dimensions. The single flagged FR (FR39) is a documentation requirement, not a capability requirement, and its refinement is straightforward (enumerate the required runbook subsections). The PRD's strict adherence to the `[Actor] can [capability]` format, combined with the explicit Journey Requirements Summary mapping and the Continuity-with-Existing-Hardening tables, makes nearly every FR independently testable. This is rare for a 52-FR PRD and reflects significant authoring effort.

## Holistic Quality Assessment

### Document Flow & Coherence

**Assessment:** Excellent

**Strengths:**
- **Narrative arc is intentional.** The document opens with the business thesis (why an "independent operator" model unlocks Brazilian SaaS TTS), establishes the operator persona via Journey 1 ("Ricardo, 34, solo developer in Curitiba"), then progressively layers technical depth: success criteria → product scope → user journeys → domain compliance → API/CLI specs → scoping → FRs → NFRs. A reader can stop at any depth and have a coherent picture.
- **Each section transitions explicitly.** The §API Backend & CLI Tool Specific Requirements opens with "With the compliance posture, non-regression contract, and LGPD primitives established above, the next sections describe the technical surface that realizes these requirements" — the bridge sentence is a hallmark of intentional document architecture.
- **Self-references are accurate.** The PRD frequently cites its own prior sections (e.g., "as documented in `CLAUDE.md`", "per J3/J4", "per §Domain-Specific Requirements > Continuity with Existing Hardening") — these references are consistent and validated by my prior step checks.
- **Tone is consistent.** The same crisp, declarative voice runs through all 1,248 lines. No section feels like it was ghostwritten by a different author or generated separately.

**Areas for Improvement:**
- The PRD has no LGPD-purge journey (J3 covers suspension, J4 covers API consumer, but no journey walks through an `export-customer` or `delete-customer --hard` flow). A J7 "LGPD Data-Subject Access Request" would close the gap between the LGPD-mapped FRs (FR5, FR6, FR35–FR39) and the experiential narrative.
- The §Project Scoping & Phased Development section (line 1032) overlaps somewhat with the §Product Scope section (line 159). The two could be consolidated, or §Product Scope could be renamed to make the distinction clearer.

### Dual Audience Effectiveness

**For Humans:**
- **Executive-friendly:** Excellent. The Executive Summary's "What Makes This Special" subsection (lines 47–60) is a 5-bullet investor-pitch-grade differentiation list. The "Core insight" closing sentence ("simplicity is the moat") is quotable and substantive.
- **Developer clarity:** Excellent. SQLite DDL is provided verbatim, the auth-flow diagram is ASCII-art-readable, the CLI command tree is exhaustive, and the error-code table is a contract spec. A developer can start scaffolding `keys/db.py` and `keys/auth.py` from this PRD without needing the architecture document yet.
- **Designer clarity:** N/A (no UI surface beyond the existing static landing page); the cli_tool secondary type means there are no design artifacts to deliver.
- **Stakeholder decision-making:** Excellent. The success criteria table (3-month and 12-month MRR/churn targets) gives stakeholders concrete success/failure signals. The risk register (16 rows) provides the downside picture. The out-of-scope list (PCI-DSS, Open Banking, KYC/AML, GDPR) prevents scope creep.

**For LLMs:**
- **Machine-readable structure:** Excellent. ## Level 2 headers for all main sections, ### Level 3 for subsections, consistent table formatting, FR/NFR numbering uniform, and frontmatter classification metadata correctly populated.
- **UX readiness:** N/A (no UI surface).
- **Architecture readiness:** Excellent. The §API Backend & CLI Tool Specific Requirements section already provides the auth flow, schema, error envelope, and rate-limit machinery. An LLM running `bmad-create-architecture` will have minimal ambiguity to resolve — most architecture decisions are already pre-decided in the PRD's brownfield context.
- **Epic/Story readiness:** Excellent. The §Product Scope section already defines two epics (Monetization Core, Security & Compliance) with bullet-listed components. The §Epic Mapping subsection at line 765 explicitly states that every row in the non-regression contract maps to story acceptance criteria. An LLM running `bmad-create-epics-and-stories` has a near-deterministic decomposition path.

**Dual Audience Score:** 5/5

### BMAD PRD Principles Compliance

| Principle | Status | Notes |
|---|---|---|
| Information Density | **Met** | Step 3 found 0 anti-patterns across 1,248 lines |
| Measurability | **Met** | Step 5 found 0 hard violations across 89 requirements; only 3 minor `multiple` quantifiers |
| Traceability | **Met** | Step 6 found 0 orphans; author-built Journey Requirements Summary preempts the most common gap |
| Domain Awareness | **Met** | Step 8 found 8/8 fintech-adjacent sections; PRD voluntarily exceeds `general` baseline |
| Zero Anti-Patterns | **Met** | Step 7 found 4 minor implementation-leakage instances, all brownfield-justified |
| Dual Audience | **Met** | Both human readability (executive summary, persona-driven journeys) and LLM-consumability (consistent structure, schema, tables) excellent |
| Markdown Format | **Met** | Heading levels consistent; tables well-formed; code blocks properly fenced; no broken cross-references |

**Principles Met:** 7/7

### Overall Quality Rating

**Rating:** 5/5 — Excellent

**Justification:** This PRD is exemplary across all measured dimensions. The combination of:
- 100% BMAD core sections (6/6) plus 4 helpful extension sections,
- 0 information-density anti-patterns across 1,248 lines,
- 89 measurable requirements (52 FRs + 37 NFRs) with 0 orphans,
- A voluntary self-elevation to fintech-adjacent compliance treatment with 8/8 required sections,
- Dual project-type compliance (api_backend + cli_tool) at 100%,
- 51/52 FRs scoring 4–5 on all SMART dimensions,
- An author-built traceability matrix (Journey Requirements Summary) and explicit Epic Mapping,

… makes this PRD a model BMAD output. Architecture, epic decomposition, and story creation can proceed directly from this document with minimal upstream rework.

### Top 3 Improvements

1. **Refine FR39 with structured runbook subsection enumeration.**
   FR39 is the only FR scoring below 4 on Specific/Measurable dimensions. Restate it to enumerate the breach-notification runbook's required subsections (ANPD contact, customer notification template, evidence preservation checklist, escalation path) so editorial review (`bmad-editorial-review-structure`) can validate the document against a content checklist rather than a vague "guidance" requirement. **Effort: 5 minutes.**

2. **Add Journey 7 — LGPD Data-Subject Access Request.**
   The PRD has comprehensive LGPD FRs (FR5, FR6, FR35–FR39) and explicit LGPD compliance treatment, but no journey walks through what the operator actually does when a customer invokes Art. 18 (II/V/VI). A J7 covering "ANPD inquiry arrives → operator runs `export-customer`/`delete-customer --hard` → operator delivers within 15 days" would close the experiential gap and strengthen the Journey Requirements Summary's "(implicit, required by scope)" entry into a fully-traced row. **Effort: 30 minutes.**

3. **Apply 4 minor implementation-leakage abstractions in NFR11/NFR20/NFR23 (and optionally FR23).**
   These are the only borderline items from Step 7. Replacing "WAL mode guarantees ..." with the capability-level statement "the suspension cron must not block concurrent auth-path reads" and adding `or equivalent` to NFR11's `hmac.compare_digest` brings the NFR set fully into capability-level language while preserving the brownfield-specific guidance. **Effort: 10 minutes.**

### Summary

**This PRD is:** A model BMAD-Standard PRD — production-ready for downstream architecture, epic decomposition, and story creation with no required revisions; the 3 suggested improvements would polish an already-excellent document.

**To make it great:** It is already great. The top 3 improvements above are about converting Excellent (5/5) into Exemplary; none are blockers for proceeding to `bmad-create-architecture`.

## Completeness Validation

### Template Completeness

**Template Variables Found:** 0
- Scanned for `{variable}`, `{{variable}}`, `[TODO]`, `[TBD]`, `[FIXME]`, `[placeholder]`, `[insert]`, `[fill]`, `[to be determined]` patterns. None found anywhere in the 1,248-line document. ✓

### Content Completeness by Section

| Section | Status | Notes |
|---|---|---|
| Executive Summary | **Complete** | Vision (line 34), problem (line 44), target users (lines 38–42), differentiators ("What Makes This Special", lines 47–60), core insight (line 59) |
| Project Classification | **Complete** | All 5 fields populated: type, secondary type, domain, complexity, context |
| Success Criteria | **Complete** | 4 subsections (User, Business, Technical, Operational, Measurable Outcomes); Business Success table has 3-month and 12-month MRR/churn targets |
| Product Scope | **Complete** | MVP (Epic 1 + Epic 2 with full bullets), Growth (2.1+), Vision (2.2+) |
| User Journeys | **Complete** | 6 named journeys (J1–J6), each with persona, narrative, and outcome; plus Journey Requirements Summary mapping table |
| Domain-Specific Requirements | **Complete** | 7 subsections (Compliance & Regulatory, Continuity with Existing Hardening, Technical Constraints, Privacy, Enumeration Resistance, Performance, Availability, Integration, Risk Mitigations, Out-of-scope, Epic Mapping) |
| API Backend & CLI Tool Specific Requirements | **Complete** | 8 subsections (Project-Type Overview, Endpoint Specification, Authentication Model, Data Schemas, Error Codes, Rate Limits, API Documentation, CLI Tool Specification, Implementation Considerations, Runtime Constraints) |
| Project Scoping & Phased Development | **Complete** | MVP Strategy & Philosophy, Resource Requirements, MVP Feature Set, Post-MVP Features, Risk Mitigation Strategy, Scope Hardening |
| Functional Requirements | **Complete** | 52 FRs, all using `[Actor] can [capability]` format, organized into 8 thematic clusters |
| Non-Functional Requirements | **Complete** | 37 NFRs across 6 subsections (Performance, Security, Reliability & Availability, Scalability, Compatibility, Compliance) |

### Section-Specific Completeness

- **Success Criteria Measurability:** **All measurable** — every criterion has a numeric target, time bound, or testable predicate (e.g., "in under 60 seconds", "<5ms p99", "10–20 active keys at 3 months", "≥1 non-author operator within 90 days").
- **User Journeys Coverage:** **Yes, all user types covered** — operator (J1, J2, J3, J5, J6) and operator-customer (J4). The third potential user type (LGPD data subject) is the only journey not given a dedicated walkthrough — flagged in §Holistic Quality Assessment as Top-3 Improvement #2.
- **FRs Cover MVP Scope:** **Yes** — Epic 1 (Monetization Core) → FR1–FR34, Epic 2 (Security & Compliance) → FR35–FR52. Both MVP epics' bullet items map to FR clusters.
- **NFRs Have Specific Criteria:** **All have specific criteria** — every NFR has either a numeric bound (`<5ms p99`, `<200ms`, `<1s`, `<10min RTO`, `<24h RPO`, `<50MB`, `<15 days`), a behavioral identity contract ("byte-identical", "idempotent"), or a documented baseline (`1,000-customer database`, "Comadre 1.6.2 behavior").

### Frontmatter Completeness

| Field | Status | Value |
|---|---|---|
| `stepsCompleted` | **Present** | 14 steps listed (full PRD creation lineage from `step-01-init` through `step-12-complete`) |
| `status` | **Present** | `complete` |
| `completedAt` | **Present** | `2026-04-15` |
| `inputDocuments` | **Present** | 5 documents (project-context + 4 brownfield reference docs) |
| `documentCounts` | **Present** | briefs:0, research:0, brainstorming:0, projectDocs:5 |
| `workflowType` | **Present** | `prd` |
| `projectType` | **Present** | `brownfield` |
| `classification.projectType` | **Present** | `api_backend` |
| `classification.projectTypeSecondary` | **Present** | `cli_tool` |
| `classification.domain` | **Present** | `general` |
| `classification.domainOverlay` | **Present** | `fintech-adjacent` |
| `classification.complexity` | **Present** | `medium` |
| `classification.projectContext` | **Present** | `brownfield` |

**Frontmatter Completeness:** 13/13 (all expected fields populated)

### Completeness Summary

**Overall Completeness:** 100% (10/10 sections complete; 13/13 frontmatter fields present)
**Critical Gaps:** 0
**Minor Gaps:** 0

**Severity:** Pass

**Recommendation:** PRD is complete with all required sections, all required content, all measurable criteria, full frontmatter, and zero template variables remaining. No completeness work required before downstream consumption.

---

# Final Validation Summary

**Overall Status:** PASS
**Holistic Quality Rating:** 5/5 — Excellent

## Quick Results

| Validation Dimension | Result |
|---|---|
| Format | BMAD Standard (6/6 core sections + 4 extensions) |
| Information Density | Pass (0 anti-patterns across 1,248 lines) |
| Product Brief Coverage | N/A (no brief provided as input) |
| Measurability (52 FRs + 37 NFRs) | Pass (3 minor `multiple` quantifiers; zero hard violations) |
| Traceability | Pass (0 orphans; author-built Journey Requirements Summary) |
| Implementation Leakage | Warning by literal count (4 minor); Pass-equivalent for brownfield context |
| Domain Compliance | Pass with distinction (8/8 fintech-adjacent sections, voluntary self-elevation) |
| Project-Type Compliance | Pass (100% for dual `api_backend` + `cli_tool`) |
| SMART Quality | Pass (51/52 FRs score 4–5; only FR39 flagged) |
| Holistic Quality | Excellent (5/5; 7/7 BMAD principles met) |
| Completeness | Pass (100%; 0 template variables; 13/13 frontmatter fields) |

## Critical Issues

**None.**

## Warnings

1. **Implementation leakage (4 minor instances)** — FR23 (`in memory` cache), NFR11 (`hmac.compare_digest` without `or equivalent` hedge), NFR20/NFR23 (`WAL mode`). All brownfield-justified; abstraction is optional polish.
2. **FR39 SMART Specific/Measurable scores at 3** — "documented guidance" is broader than other FRs. Refinement is straightforward (enumerate runbook subsections).

## Strengths

- **Author-built traceability matrix** (Journey Requirements Summary, lines 555–597) preempts the most common downstream gap.
- **Voluntary self-elevation** to fintech-adjacent compliance treatment despite `general` classification — the LGPD coverage is article-level explicit (Art. 5/7/18/48), every right has a CLI command, and the breach-notification posture is named.
- **Zero information-density violations** across 1,248 lines — exceptional given the document size.
- **Continuity-with-Existing-Hardening** non-regression contract converts the 1.6.2 pentest history into testable CI requirements (FR46–FR52), with explicit Epic Mapping that prevents compliance prose from becoming orphan.
- **Dual project-type handling** done correctly — single §API Backend & CLI Tool Specific Requirements section satisfies both `api_backend` and `cli_tool` required-section sets.
- **51/52 FRs score 4–5 on all 5 SMART dimensions** — rare for a 52-FR PRD.
- **Persona-driven journeys** (Ricardo the Curitiba dev, Helena the agency owner, Pedro the n8n integrator) make abstract requirements concrete and decision-anchorable.

## Holistic Quality

**Rating:** 5/5 — Excellent

This PRD is a model BMAD-Standard output. Architecture, epic decomposition, and story creation can proceed directly with no required revisions.

## Top 3 Improvements (from Step 11)

1. **Refine FR39 with structured runbook subsection enumeration** (5 min) — convert documentation requirement into a structured-content requirement that editorial review can validate against a checklist.
2. **Add Journey 7 — LGPD Data-Subject Access Request** (30 min) — close the experiential gap for FR5/FR6/FR35–FR39; converts the Journey Requirements Summary's "(implicit, required by scope)" entry into a fully-traced row.
3. **Apply 4 minor implementation-leakage abstractions in NFR11/NFR20/NFR23 (and optionally FR23)** (10 min) — replace `WAL mode guarantees ...` with capability-level statements; add `or equivalent` hedge to NFR11.

**Total polish effort:** ~45 minutes.

## Recommendation

**PRD is in excellent shape. The 3 suggested improvements would convert "Excellent" into "Exemplary"; none are blockers for downstream work.**

You can proceed directly to **`bmad-create-architecture`** without applying these polish items, or apply them first if you prefer to enter Phase 3 with a clean validation report.

---

# Polish Applied (2026-04-15, post-validation)

After validation completed, the following improvements from the Top-3 list were applied directly to `prd.md`. The changes are capability-level refinements that do not alter requirement semantics — they tighten the language used to express an already-correct requirement.

### 1. FR39 — Refined with structured runbook subsection enumeration

**Before:**
> Operator receives documented guidance on their LGPD controller obligations, including a breach-notification runbook and a privacy-policy template.

**After:**
> Operator receives a `docs/monetization.md` section "LGPD Operator Obligations" containing: (a) a breach-notification runbook with ANPD contact information, a customer-notification email template, an evidence-preservation checklist, and an internal escalation path; (b) a privacy-policy template paragraph the operator can adapt for their own terms of service.

**Impact on scoring:** FR39 SMART Specific score 3 → 5; Measurable 3 → 5. All 52 FRs now score 4–5 across all dimensions.

### 2. FR23 — "in memory" replaced with NFR-target reference

**Before:**
> System caches valid authorizations in memory to reduce the auth-path latency for repeat requests from the same key.

**After:**
> System caches valid authorizations to satisfy the NFR1 auth-path latency target for repeat requests from the same key.

**Impact:** FR now describes the capability (meet NFR1) instead of the implementation (`in memory`). Architecture chooses the cache medium.

### 3. NFR20 — "via SQLite WAL mode" replaced with capability-level tolerance

**Before:**
> The key registry must tolerate unclean shutdown via SQLite WAL mode; the post-crash auth cache may be empty but the registry itself must remain readable.

**After:**
> The key registry must tolerate unclean shutdown without corruption; the post-crash auth cache may be empty but the registry itself must remain readable.

**Impact:** NFR now specifies the capability (survive unclean shutdown) without prescribing the mechanism (WAL mode). Architecture decides the durability mechanism.

### 4. NFR23 — WAL-mode prescriptive clause removed

**Before:**
> The daily suspension cron must not block the auth-path SQLite reads; WAL mode guarantees single-writer-many-reader behavior during the sweep.

**After:**
> The daily suspension cron must not block concurrent auth-path reads during the sweep.

**Impact:** NFR reduced to the capability assertion; architecture chooses the concurrency model.

### NFR11 — No change required

NFR11 already carried the `or equivalent` hedge on `hmac.compare_digest` (line 1210), so no abstraction was needed. My initial validation summary had a minor inconsistency; the fix list is 4 items (FR23, FR39, NFR20, NFR23), not 5.

### Post-Polish Severity Updates

| Validation Dimension | Pre-Polish | Post-Polish |
|---|---|---|
| Implementation Leakage | Warning (4 minor) | Pass (1 minor remaining — SQLite file naming in FR42/FR44/NFR13/NFR29, all brownfield-justified and intentional) |
| SMART Quality | 51/52 score 4–5 | 52/52 score 4–5 |
| Holistic Quality | 5/5 — Excellent | 5/5 — Excellent (unchanged; already at ceiling) |

**Note on remaining brownfield-justified SQLite references:** NFR13 ("SQLite database file must have filesystem mode 0600") and similar are deliberate: the requirement is "extend the existing storage with 0600 mode", and naming SQLite is what makes the requirement verifiable by the `health.yml` playbook. These are kept as-is.

### Top-3 Item Deferred

**Improvement #2 (Journey 7 — LGPD Data-Subject Access Request)** was not applied as part of "F" — it adds net-new narrative content (persona, flow, outcome) rather than refining existing text, and would benefit from the PRD author's input on the fictional requester's situation. Recommended to add during a targeted PRD-edit session or deferred to post-architecture cycle if operator feedback suggests it would clarify Epic 2's story decomposition.


