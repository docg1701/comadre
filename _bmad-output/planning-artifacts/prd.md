---
stepsCompleted: ['step-01-init', 'step-02-discovery', 'step-02b-vision', 'step-02c-executive-summary', 'step-03-success', 'step-04-journeys', 'step-05-domain', 'step-06-innovation-skipped', 'step-07-project-type', 'step-08-scoping', 'step-09-functional', 'step-10-nonfunctional', 'step-11-polish', 'step-12-complete', 'step-e-01-discovery', 'step-e-02-review', 'step-e-03-edit']
status: 'complete'
completedAt: '2026-04-15'
lastEdited: '2026-04-16'
editHistory:
  - date: '2026-04-16'
    changes: 'Amended FR45 and related references to reflect architecture decision that immediate cross-replica auth-cache invalidation is not supported in MVP; renamed CLI command cache-flush → cache-status. Driven by implementation-readiness-report-2026-04-16.md §Major Issues #1.'
  - date: '2026-04-18'
    changes: |
      Retired FR27 (legacy single-API_KEY mode) and NFR31 (byte-identical 1.6.2 behaviour). Comadre 2.0.0 is registry-only from the first byte — no `monetization_enabled` toggle, no fallback to the pre-2.0.0 single-`API_KEY` env var, no "legacy mode" rate-limit semantics. Driven by Story 2.2 code-review triage: slowapi 0.1.9's limit-provider signature made the dual-mode contract incoherent, and the toggle has no operational value since the same operator owns both the deploy and the migration. Story 2.2 is being rewritten to use `limits` directly (no slowapi), pure per-key rate-limit, FastAPI `Depends`. `API_KEY` env var is removed from deployment config; `KEY_REGISTRY_ENCRYPTION_KEY` becomes mandatory.
inputDocuments:
  - _bmad-output/project-context.md
  - docs/api-architecture.md
  - docs/api-reference.md
  - docs/configuration-reference.md
  - docs/deployment-guide.md
documentCounts:
  briefs: 0
  research: 0
  brainstorming: 0
  projectDocs: 5
workflowType: 'prd'
projectType: 'brownfield'
classification:
  projectType: api_backend
  projectTypeSecondary: cli_tool
  domain: general
  domainOverlay: fintech-adjacent
  complexity: medium
  projectContext: brownfield
---

# Product Requirements Document - comadre

**Author:** Galvani
**Date:** 2026-04-15

## Executive Summary

Comadre is a self-hosted Brazilian Portuguese text-to-speech API built for n8n chatbot workflows on WhatsApp, Telegram, and Messenger. Version 1.6.2 ships a mature, security-hardened, production-tested dual-engine service — Kokoro for speed, Qwen3 for voice cloning — running entirely on CPU with no cloud dependencies.

Version 2.0.0 adds the capability required to turn Comadre from a self-hosted internal tool into a sellable SaaS product: **customer-scoped API-key management and recurring billing**. The feature cluster replaces the current single `API_KEY` environment variable with a per-customer key registry stored in a local SQLite database, a Typer-based CLI accessed over SSH for operator workflows (customer onboarding, key issuance, suspension, reactivation, audit), a pluggable `BillingProvider` adapter (manual-first, PSP-ready), and dynamic per-key rate limiting via the existing slowapi infrastructure.

**Target users:**

- **Comadre operators** (primary): Brazilian solo developers and small agencies who deploy a VPS, run Comadre, and resell TTS capacity. They need to issue keys, track customers, and collect recurring payments without operating a payment portal, auth system, or admin web UI.
- **Operators' customers** (indirect): chatbot builders who need pt-BR TTS for their own n8n workflows and prefer per-key authentication tied to a local Brazilian provider over cloud services like ElevenLabs.

**Problem solved:**

Brazilian builders today face a binary choice for pt-BR chatbot TTS: cloud subscriptions (ElevenLabs at roughly US$22/mo for 30k chars, with vendor lock-in and added latency) or fully self-hosted infrastructure (operationally expensive for a single builder). Comadre 2.0.0 creates a third path — the **independent Comadre operator** who rents a VPS, runs Comadre, and sells keys at a margin. Revenue is predictable (single billing day per month, no per-customer calendar drift), unit economics are transparent (VPS tier maps 1:1 to customer rate limit and price), and operations stay at the command line.

### What Makes This Special

**Radical operational simplicity as a product feature.** Zero auth portal, zero OAuth, zero login UI, zero SMTP/2FA, zero new containers. The entire customer lifecycle — onboarding, key issuance, payment tracking, suspension, reactivation — runs through a single Typer CLI over SSH. What competitors encode as complexity (Kong, Tyk, Lago, Unkey + Stripe stacks), Comadre collapses into `typer` + SQLite + cron. The MVP is simpler to build than any off-the-shelf combination is to integrate.

**Self-contained VPS shards.** Each deployment carries its own SQLite customer database. No central store, no replication, no sync windows, no single point of failure. An operator with multiple niches runs multiple independent shards, each with its own pricing and clientele. Shard isolation is a business-model enabler, not a constraint.

**Infrastructure-transparent pricing.** VPS tier determines aggregate capacity; aggregate capacity determines the keys that can be sold on it. Small VPS → low total RPM → lower-priced keys with smaller per-key limits. Large VPS → premium keys with elevated per-key RPM. The operator's margin is visible in the unit economics, not hidden behind an opaque SKU.

**Billing as adapter, not as dependency.** The MVP ships with a `ManualBillingProvider`: the operator confirms payments out-of-band (Pix, boleto, transfer) and marks `paid_until` via CLI. A clean `BillingProvider` interface (`create_subscription`, `handle_webhook`, `cancel`) makes plugging Asaas, Iugu, Stripe, or Mercado Pago a one-day later integration, not a refactor. Operators get optionality without coupling.

**Dynamic per-key rate limiting.** The existing slowapi infrastructure stays; only the `key_func` changes. Every API key carries its own `rate_limit_rpm` field in SQLite. Customers negotiating higher throughput pay for a key with a higher limit. Infrastructure usage maps 1:1 to revenue.

**Core insight:** The Brazilian SaaS market has been trained to equate "professional" with "complex" — full auth portals, white-label dashboards, corporate billing UX. Comadre 2.0.0 inverts that: the product's deliberate lack of a user-facing management surface is what makes it operable by a single developer, affordable to run on a R$40/mo VPS, and resellable at a margin. Simplicity is the moat.

## Project Classification

- **Project Type:** `api_backend` (primary) — the product is the TTS REST API; monetization extends its auth and rate-limit layers without changing the public endpoint contract
- **Secondary Project Type:** `cli_tool` — operator interface is a Typer CLI accessed over SSH; no web or graphical admin surface
- **Domain:** `general` with fintech-adjacent overlay — the core product is TTS/ML, not a regulated financial service, but the feature cluster introduces recurring billing, Pix/boleto/NFSe considerations, and LGPD-covered customer data (CPF at rest)
- **Complexity:** `medium` — above general SaaS due to LGPD-sensitive data, Brazilian payment landscape, multi-tenant key-based auth, dynamic rate limiting, and scheduled billing automation; below `fintech/high` because Comadre is not itself a payment processor (KYC/AML/PCI-DSS obligations rest with the plugged PSP, when adopted)
- **Project Context:** `brownfield` — Comadre 1.6.2 is a production-deployed service with 58 crystallized architecture rules, live usage, and an Ansible-managed VPS fleet; monetization is a feature cluster within an established codebase, not a greenfield product

## Success Criteria

### User Success

**Operator success (primary user):**

- Complete customer onboarding — create customer, issue API key, hand the key to the customer — in under 60 seconds via a single CLI command sequence
- Confirm a monthly payment and extend a key's validity in under 5 seconds (`comadre-keys mark-paid <id> --until <date>`)
- Get a full portfolio snapshot (active keys, suspended keys, projected monthly revenue) in under 1 second from any VPS shard
- Spot at-risk accounts (approaching day 05 without confirmed payment) with a single command, days before cutoff
- Operate every lifecycle event from an SSH session; no browser, no portal, no login flow, ever

**Operator-customer success (indirect):**

- Receive an active API key and begin authenticating successfully within minutes of delivery
- Experience no measurable latency difference versus Comadre's pre-monetization behavior (auth overhead under 5ms p99)
- Receive clear, actionable error envelopes on suspension (HTTP 401 with `type: authentication_error` and a `hint` referencing how to reach the operator for billing resolution)
- When payment is confirmed after suspension, see the key return to active within 60 seconds (cache TTL bound)

**"Aha!" moments:**

- Operator: first day 05 arrives, payments land, `comadre-keys revenue --month current` shows the sum. Revenue is tangible, traceable, and command-line-visible.
- Operator-customer: first request with a new key succeeds identically to a direct Comadre request. The billing layer is invisible to them.

### Business Success

**Per-operator, per-VPS targets:**

| Horizon | Active keys | Monthly recurring revenue | Churn |
|---|---|---|---|
| 3 months post-launch | 10–20 | R$ 500 – R$ 1,500 | < 15% |
| 12 months post-launch | 30–60 across multi-shard | R$ 2,500 – R$ 7,000 | < 10% |

**Unit economics transparency:**

- Every operator can calculate gross margin per key in under a minute: `(monthly_price × active_keys) − VPS_cost = margin`
- VPS tier → per-key RPM ceiling → price tier. The mapping is documented and enforced in CLI warnings when issuing a key that exceeds the VPS's declared aggregate RPM budget.

**Adoption signal:**

- At least one non-author operator running Comadre 2.0.0 in production within 90 days of release — validates the "independent operator" thesis

### Technical Success

**Resource overhead (the central constraint):**

- Zero new containers. SQLite file only.
- Under 50 MB additional disk footprint per deployment (DB + backups after 6 months of typical use)
- Under 5 ms p99 auth overhead per TTS request vs. current single-key path
- CLI commands respond in under 200 ms for list/show operations on a 1,000-customer database
- Daily cron suspension sweep completes in under 1 second for 1,000 customers

**Compliance and security:**

- CPF encrypted at rest using `cryptography.fernet` with key material in environment variable (`KEY_REGISTRY_ENCRYPTION_KEY`)
- API keys stored as hash (`sha256`) + 8-char visible prefix for identification; full plaintext never persisted
- Timing-safe key comparison via `hmac.compare_digest` (reusing the current pattern)
- SQLite file permissions restricted to the Comadre service user; read-only for unprivileged accounts
- LGPD data-deletion path: operator can irreversibly purge a customer record (including encrypted CPF) via CLI

**Quality gates:**

- All existing tests pass after the change (no regressions in the 58-rule architecture envelope)
- `uv run pytest`, `uv run ruff check .`, `uv run mypy src/`, `uv run pre-commit run --all-files` — all green
- Minimum 90% test coverage on new modules: `keys/`, `auth/`, `billing/`, `cli/`
- Zero `HTTPException` raises; all new errors via `ComadreError` subclasses (new: `ApiKeySuspendedError`, `ApiKeyNotFoundError`, `RateLimitExceededForKeyError`)
- Import graph extension: new `keys/`, `auth/`, `billing/`, `cli/` modules respect the existing downward-only flow

**Operational success:**

- Bootstrap Ansible playbook creates the SQLite file, sets permissions, installs the daily suspension cron, and verifies the CLI is runnable — in the existing bootstrap flow, not a separate playbook
- `cleanup.yml` extends to remove the key database and its backups
- API-key rotation is handled exclusively via `comadre-keys rotate-key <prefix>` (per-customer). The pre-2.0.0 `rotate-api-key.sh` script is removed from the deploy package — there is no global master key to rotate in 2.0.0.
- CLI installed system-wide as `comadre-keys` via `uv tool install` during deploy, available to the operator without virtualenv activation

### Measurable Outcomes

**At release (2.0.0):**

- Operator can complete the full onboarding → key-delivery → mark-paid flow on a fresh bootstrap in under 3 minutes (excluding VPS provisioning)
- A Comadre instance with 100 active keys shows no measurable degradation in TTS request p99 latency vs. the same instance without monetization
- `comadre-keys list` on a 1,000-customer database returns in under 200 ms
- Documentation (`docs/monetization.md`) passes the `bmad-editorial-review-structure` and `bmad-editorial-review-prose` skills without critical findings

**30 days post-release (field observation):**

- At least one operator (other than the project author) has successfully onboarded ≥ 5 paying customers
- Zero LGPD incidents: no leaked CPFs, no unauthorized key access, no SQLite extractions from a compromised instance
- Zero billing-related data-loss incidents (suspended-but-not-deleted contract honored in every observed case)

## Product Scope

### MVP — Minimum Viable Product (2.0.0)

**Work organized into two parallel epic groups.** Both must ship for 2.0.0 to be meaningful; the split ensures security and compliance work receives dedicated attention rather than being fragmented across feature stories.

**Epic 1 — Monetization Core (feature epic)**

- **SQLite schema and storage layer**: `customer` (name, email, tax_id-encrypted, tax_id_kind ∈ {cpf, cnpj}, registered_at, notes), `api_key` (id, customer_id, key_hash, key_prefix, rate_limit_rpm, status, billing_mode, paid_until, price_monthly, created_at, last_used_at), `audit_log` (who/what/when for every CLI mutation)
- **API-key auth middleware**: replaces current single `API_KEY` env-var check; looks up by hash, validates `status=active AND (billing_mode != 'manual' OR paid_until >= today)`, caches in memory with 60s TTL
- **Dynamic per-key rate limiting**: slowapi `key_func=get_api_key`, dynamic limit resolved from the cached key record
- **`comadre-keys` Typer CLI**: `create-customer`, `update-customer`, `issue-key`, `update-key`, `list-customers`, `list-keys`, `show <id>`, `suspend <key>`, `reactivate <key>`, `revoke-key <key> --reason`, `mark-paid <key> --until <date>`, `revenue --month current|YYYY-MM`, `at-risk`, `rotate-key <key>`
- **Daily suspension cron**: sweeps `billing_mode='manual' AND paid_until < today`, sets `status=suspended`, logs to `audit_log`. Runs at 00:30 operator TZ.
- **`BillingProvider` adapter + `ManualBillingProvider`** (the only concrete implementation in 2.0.0)
- **Documentation (feature slice)**: `docs/monetization.md` operator runbook (onboarding, billing ritual, troubleshooting, complimentary keys), `CLAUDE.md` section, per-command `--help` with operator-actionable examples
- **Ansible integration**: `bootstrap.yml` extension, `cleanup.yml` extension, `health.yml` extension with monetization probes
- **Upgrade path (2026-04-18 revision — no backward-compat):** 2.0.0 is a breaking release. The single-`API_KEY` env var is removed. Operators upgrading from 1.6.2 must (a) set `KEY_REGISTRY_ENCRYPTION_KEY`, (b) create at least one customer + issue one key via `comadre-keys` CLI before the first request, (c) redeploy. No dual-mode, no `monetization_enabled` toggle. The only deployer is the project author; the break is contained.

**Epic 2 — Security & Compliance (dedicated security epic)**

Lifts the non-regression contract and the LGPD obligations into first-class stories. Every item here maps to a concrete story with explicit acceptance criteria and verification, independent of feature progress.

- **Non-regression guard**: CI job that runs the full hardening regression suite on every PR — security headers, banner stripping, disabled docs endpoints, `request_body max_size`, `redirect_slashes=False`, `/health` minimal-for-unauth, UFW rules, timing-safe comparison, `SlowAPIMiddleware` registered, error envelope uniformity
- **CPF/CNPJ validation and encryption**: checksum-validated input via `validate-docbr` (>=2.0; handles both numeric and the July 2026 alphanumeric CNPJ per RFB IN 2.229/2024), `cryptography.fernet` encryption at rest with `KEY_REGISTRY_ENCRYPTION_KEY` (`SecretStr`), rotation command (`rotate-encryption-key`) that re-encrypts all rows before swapping the key
- **API-key cryptographic handling**: SHA-256 hash + 8-char visible prefix, plaintext displayed **once** at creation and never persisted, timing-safe comparison in the lookup path with a dummy comparison on miss to equalize timing
- **Logging and error discipline**: middleware scrubs CPF/CNPJ from log messages; access log continues to log only `client_ip | method | path | status | duration`; error hints sanitized (no env var names, no internal paths, no echoes of invalid tax-ID input); new `ComadreError` subclasses (`ApiKeySuspendedError`, `ApiKeyNotFoundError`, `InvalidTaxIdError`, `KeyRegistryError`) with proper `status_code`, `error_type`, `hint`
- **SQL-injection prevention story**: parameterized queries exclusively, `bandit` or equivalent static-analysis check in pre-commit, code-review checklist item
- **SQLite durability**: WAL mode enforced at DB init, file permissions `0600` owned by service user, Ansible regression check for file mode
- **Enumeration resistance**: 401 returns identical envelope for "invalid key" and "suspended key" at the rate-limit layer; operator-contact hint only after successful hash match
- **LGPD compliance primitives**: `delete-customer --hard` (purges encrypted tax ID + associated keys), `export-customer --format json` (decrypted export for data-subject access requests), audit-log retention rules, breach-notification runbook section
- **Backup and restore**: `backup-keys.yml` (nightly SQLite snapshot + encryption key, encrypted separately) and `restore-keys.yml` playbooks; backup tarball mode `0600`; documented restoration procedure
- **Cron observability**: `comadre-keys health` reports last successful cron sweep; `health.yml` playbook flags cron absence
- **Documentation (security slice)**: LGPD obligations section in `docs/monetization.md`, breach-notification runbook, encryption-key handling guide, `.env` hardening checklist, the non-regression contract reproduced verbatim so future contributors can self-audit

### Growth Features (2.1+)

**Compete on convenience once MVP is validated:**

- `AsaasBillingProvider` (or Iugu/Stripe BR) — first automated PSP integration, exposes a webhook endpoint behind Caddy at `/v1/billing/webhook/<provider>`
- NFSe emission automation via the PSP (when applicable)
- CLI `report` command with `rich`-formatted revenue trends (monthly, per-key, per-customer)
- Multi-shard aggregate reporting: `comadre-keys aggregate --shards vps1,vps2,vps3` pulls status from multiple instances over SSH
- Per-key usage analytics (requests/day, average chars, upsell signals)
- Bulk-operation CLI verbs (`suspend-batch`, `mark-paid-batch`) for end-of-month operator workflows
- Pluggable notification hooks on suspension/reactivation events (operator chooses: Slack webhook, email SMTP, WhatsApp via n8n)

### Vision (2.2+)

**Expand the independent-operator thesis into a network:**

- Cooperative abuse blocklist: operators opt in to share hashed CPFs/emails of known abusers, federated via signed Git commits in a shared repo
- Operator directory (`comadre.dev/operators`): public listing of active operators, their pricing tiers, and capacity signals — a marketplace, not a platform
- Referral revenue-sharing adapter: when an operator forwards a lead to another operator, a split is tracked and settled via the same `BillingProvider` abstraction
- Lightweight read-only web dashboard (served behind Headscale VPN only): status view of the operator's portfolio, no mutation capability — the CLI remains the source of truth

## User Journeys

### Journey 1 — The Operator's First Sale (Primary User, Happy Path)

**Persona:** Ricardo, 34, solo developer in Curitiba. Runs a small agency building WhatsApp automations for clinics and lawyer offices. Has been paying ElevenLabs R$120/mo for client projects and feels the cost cutting into margin. Discovered Comadre in a Discord server, deployed 1.6.2 on a R$42/mo VPS for one of his own projects, and loved the quality. Now someone asks him if they can "just use the same voice thing" he built — and he realizes he can sell access instead of managing separate deployments.

**Opening Scene:**
Ricardo is on a Tuesday call with Dra. Helena, a dentist who runs five WhatsApp booking bots. She pays R$400/mo for ElevenLabs across them. He mentions his Comadre instance. She asks: "Quanto você cobraria pra eu usar o seu?" Ricardo doesn't have an answer. He's never sold access before. He hangs up and opens a terminal.

**Rising Action:**
He SSHs into his VPS. Checks the Comadre docs. Finds `docs/monetization.md`. Reads the operator runbook in 4 minutes. Notices the `comadre-keys` CLI is already installed (bootstrap handled it). He creates Helena as an individual customer with her CPF:

```bash
comadre-keys create-customer \
  --name "Helena Ribeiro" \
  --email "helena@clinicadra.com.br" \
  --cpf "123.456.789-00" \
  --notes "5 bots, WhatsApp booking"
```

Or, if the customer registers as a legal entity:

```bash
comadre-keys create-customer \
  --name "Clínica Dra. Helena LTDA" \
  --email "financeiro@clinicadra.com.br" \
  --cnpj "12.345.678/0001-90" \
  --notes "faturamento PJ, emite NF"
```

The `--cpf` and `--cnpj` flags are mutually exclusive. Both are validated on entry using the Brazilian tax-ID checksum algorithm (11 digits with 2 verification digits for CPF, 14 digits with 2 verification digits for CNPJ). Formatting with or without punctuation is accepted; the stored value is the digits-only form, encrypted at rest. Invalid tax IDs are rejected with a clear error message before any record is created.

CLI returns `customer-id: cust_01HF3...`. Then:

```bash
comadre-keys issue-key \
  --customer cust_01HF3... \
  --rpm 60 \
  --price 149
```

CLI prints:

```text
==============================================================
  API KEY (copy now - shown only once)
  cmdr_live_KQjPz8vR9NwT3MxAbYcH5dLeFgJ2nSsU

  prefix:       cmdr_li
  rate limit:   60/min
  billing mode: manual
  price:        R$ 149,00/month
  first charge: 2026-05-05 (22 days free until then)
==============================================================
```

**Climax:**
Ricardo copies the key into a WhatsApp message to Helena with a one-liner about the endpoint and the Authorization header. Twelve minutes later she replies: "Testei aqui, perfeito!" Total elapsed time from the call ending to a paying customer online: **under 20 minutes.**

**Resolution:**
Ricardo runs `comadre-keys list-customers`. One row. Helena. Status: trial. Next charge: 2026-05-05. He takes a screenshot, posts it in the Discord with the caption "primeira venda, simples assim." Two people DM him asking how.

**Revealed Requirements:**
- `create-customer` with required fields (name, email, and either `--cpf` or `--cnpj`) and optional notes, returning an opaque `customer-id`
- Brazilian tax-ID validation: CPF and CNPJ checksum enforced via `validate-docbr` (delegating to an actively-maintained library that tracks Receita Federal rule changes, including the July 2026 alphanumeric CNPJ transition)
- Mutually exclusive `--cpf` and `--cnpj` flags on `create-customer`
- `issue-key --customer <id> --rpm N --price X` emitting a one-time plaintext key with prefix visible and immediate summary
- Automatic calculation of "first charge date" = next day 05 after creation
- Clear single-shot key display with a copy-now warning (plaintext never stored)
- Trial status that's not visually confusing vs. active paid status

---

### Journey 2 — Dia 05, The Recurring Collection Ritual (Primary User, Recurring Happy Path)

**Persona:** Same Ricardo, six months later. He has 14 active customers across two VPS shards (one R$42/mo tier for low-RPM keys, one R$80/mo tier for premium keys). Monthly revenue around R$1,800.

**Opening Scene:**
It's the 4th of the month, late evening. Ricardo opens his terminal, already knowing the ritual. Tomorrow, payments should land.

**Rising Action:**
He runs on shard 1:

```bash
comadre-keys at-risk --window 5d
```

CLI prints a table showing 2 customers whose `paid_until` is 2026-05-05 (tomorrow). He sends them each a Pix QR code via WhatsApp with a pre-written template. Both reply within an hour confirming payment.

On the morning of the 5th, he runs:

```bash
comadre-keys list-keys --status active --paid-until-lte today
```

12 keys appear. He opens his bank's Pix statement, cross-references transfers received. For each confirmed transfer:

```bash
comadre-keys mark-paid <key-prefix> --until 2026-06-05
```

Takes 3-4 seconds per customer. 12 customers in under a minute. Two customers haven't paid yet — he moves on.

**Climax:**
Runs:

```bash
comadre-keys revenue --month current
```

```text
===========================================================
  Revenue Report — May 2026
===========================================================
  Paid customers:           12
  Pending:                   2
  Suspended (carry-over):    0
  Monthly recurring (paid): R$ 1,643.00
  Projected (if all pay):   R$ 1,891.00
  Next charge date:         2026-06-05
===========================================================
```

**Resolution:**
On the 6th at 00:30, the cron sweep runs. The 2 non-payers are auto-suspended. Ricardo gets zero notifications — the system handled it. One of the two pays that afternoon at 15:00; Ricardo runs `mark-paid` and the key reactivates within the 60-second cache TTL. The second stays suspended for 11 days before finally paying.

**Revealed Requirements:**
- `at-risk --window <duration>` to preview upcoming charges
- `list-keys --status active --paid-until-lte <date>` for cross-referencing incoming payments
- `mark-paid <key-prefix> --until <date>` accepting partial key prefix for speed
- `revenue --month current|YYYY-MM` report with paid/pending/suspended/projected split
- Cron-driven suspension sweep at fixed time, no operator intervention required
- Key reactivation fast enough (< 60s) that the operator can confirm payment and tell the customer "já tá ativa" in the same conversation

---

### Journey 3 — The Delinquent Customer (Primary User, Edge Case)

**Persona:** Ricardo, with customer "Marcos" who paid months 1-3 but went silent.

**Opening Scene:**
It's the 7th of the month. Ricardo's WhatsApp buzzes — Marcos: "ei a API tá dando 401, teve algum problema?"

**Rising Action:**
Ricardo runs:

```bash
comadre-keys show <marcos-key-prefix>
```

```text
Key:          cmdr_li... (suspended)
Customer:     Marcos Silva (cust_01HG7...)
Paid until:   2026-04-05
Status:       suspended (since 2026-04-06 00:30)
Last used:    2026-04-05 23:47
Monthly:      R$ 89.00
Age:          3 months 22 days
Notes:        "marketing agency, 2 bots"
```

He types back: "Oi Marcos! Tua mensalidade venceu em 05/04, a chave suspendeu automaticamente dia 06. Posso reativar assim que confirmar o pagamento. R$ 89 via Pix: [qr-code]."

**Climax:**
Marcos pays in 20 minutes, sends the comprovante. Ricardo verifies the transfer, runs:

```bash
comadre-keys mark-paid <marcos-key-prefix> --until 2026-05-05
```

A minute later Marcos sends: "voltou!" Ricardo responds with the full cycle explanation: "Todo dia 05 é a data universal de cobrança, se não pagar suspende dia 06 — mas a chave não é deletada, só pausada. Na próxima é bom lembrar!"

**Resolution:**
Marcos sets a reminder on his phone for the 4th of every month. Ricardo adds a note to the customer record:

```bash
comadre-keys update-customer cust_01HG7... --add-note "paga tarde - lembrar dia 3"
```

**Revealed Requirements:**
- `show <key-prefix>` showing full context: customer, status, dates, notes, age, price
- Suspended keys retained indefinitely (never auto-deleted); reactivation path is the same `mark-paid` command
- Clear error envelope on 401 when key is suspended, with a `hint` that references the operator's contact (so the customer knows to reach out)
- `update-customer --add-note` for operator annotations without editing other fields
- Audit trail: the key's suspension is traceable (who? what? when? — in this case: "the cron, at 00:30, because paid_until expired")

---

### Journey 4 — The Operator's Customer (API Consumer)

**Persona:** Helena, Dra. Helena from Journey 1. Not technical. She hires a freelance dev named Pedro to plug Ricardo's key into her n8n workflow.

**Opening Scene:**
Pedro receives the key from Helena via WhatsApp forward. He's never heard of Comadre. He opens the Comadre landing page on his browser (`https://<ricardo-vps>/`), reads the minimal intro, finds the `/docs` endpoint.

**Rising Action:**
He opens n8n, creates an HTTP Request node:
- URL: `https://<ricardo-vps>/v1/audio/speech`
- Method: POST
- Auth header: `Bearer cmdr_live_KQjPz8vR9NwT3MxAbYcH5dLeFgJ2nSsU`
- Body: `{"input": "Bom dia, Dra. Helena", "voice": "kokoro/pm_santa"}`

Hits execute. Gets an OGG file. Plugs it into the WhatsApp send-audio node. Tests end-to-end. Works.

**Climax:**
He notices the API returns identical-looking responses to what the Comadre public docs describe. No "monetization wrapper" visible in the API contract. The `Authorization: Bearer <key>` header works exactly like the docs show. He doesn't need to know anything about Ricardo's billing setup. He never touches a customer portal, never logs in anywhere, never creates an account.

**Resolution:**
Pedro ships the workflow to Helena's bots. They run normally for a month. On the 6th of the following month, one morning, the TTS node in n8n returns 401 with `{"error": {"type": "authentication_error", "hint": "Your API key has been suspended. Contact your Comadre operator for billing resolution."}}`. Pedro forwards the error to Helena. Helena checks with Ricardo. Paid, reactivated, n8n works again. Total downtime: 2 hours.

**Revealed Requirements:**
- API contract for `/v1/audio/speech` must remain 100% identical to pre-monetization Comadre — same request shape, same response shape, same error envelope
- The 401 error on suspension must include a `hint` that directs the customer to their operator (operator name/email configurable per-deployment: `OPERATOR_CONTACT_HINT` env var)
- The public landing page at `/` must work identically whether monetization is on or off
- No "monetization portal" anywhere in the customer-facing surface

---

### Journey 5 — Debug Session (Troubleshooting)

**Persona:** Ricardo again. A customer complains the API is "intermittently failing" with 401s.

**Opening Scene:**
Ricardo suspects rate-limit confusion. The customer has a 60/min key and claims to only send "about 40 requests a minute." But sometimes gets 401 ... wait, 401 or 429?

**Rising Action:**
Ricardo runs:

```bash
comadre-keys show <key-prefix> --audit-tail 20
```

CLI prints the last 20 audit-log entries and request-log stats for this key. He sees:

```text
Last 20 events for key cmdr_li...:
  2026-05-12 14:23:45  AUTH_SUCCESS      from IP 203.0.113.45
  2026-05-12 14:23:45  AUTH_SUCCESS      from IP 203.0.113.45
  2026-05-12 14:23:46  RATE_LIMIT_429    from IP 203.0.113.45 (61/min > 60/min)
  ...
Last 24h stats:
  requests total:     8,234
  auth success:       8,201
  rate_limit_429:        33
  auth_failures:          0
  peak RPM:              71
  average RPM:           13.2
```

**Climax:**
Not 401s — 429s. The customer is hitting peak bursts above their 60/min limit. Ricardo copies the output into WhatsApp: "tu tá batendo picos de 71/min, o teu plano é 60. Duas opções: (a) rate-limit no teu lado pra não estourar, ou (b) subir pro plano 120/min por +R$50/mês."

**Resolution:**
The customer upgrades. Ricardo runs:

```bash
comadre-keys update-key <key-prefix> --rpm 120 --price 139
```

Price and limit update immediately. Customer is billed the new value starting next cycle. Ricardo adds a note: "upgraded 2026-05-12 from 60→120rpm after burst issue."

**Revealed Requirements:**
- `show --audit-tail N` for recent events on a specific key
- Request-log stats per-key (total, success, 429 count, peak RPM, avg RPM over a window) — lightweight in-memory counters, not full request logging
- `update-key --rpm N --price X` for mid-cycle tier changes
- Clear separation of error categories so the operator can distinguish "the key is suspended" (401) from "the customer is oversubscribed" (429)

---

### Journey 6 — The Infrastructure Bundle (Complimentary Subscription)

**Persona:** Ricardo, the same operator. One of his customers, "AgroBots" (a legal entity), subscribes to a R$850/month bundle that includes: a managed VPS, hosted n8n, and Comadre access. The Comadre portion is embedded in the bundle — Ricardo does not bill it separately because the payment arrives from the umbrella infrastructure contract.

**Opening Scene:**
Ricardo closes the contract with AgroBots. When provisioning, he does not want Comadre's key to show up in the MRR report as "R$ 0,00" or be at risk of suspension every day 06. He wants the key to be **complimentary** — technically active, not billed, not swept by the cron.

**Rising Action:**
He registers the legal entity with a CNPJ (validated by checksum on entry), then:

```bash
comadre-keys issue-key \
  --customer cust_01HJ9... \
  --rpm 120 \
  --billing-mode complimentary \
  --notes "incluída no pacote infra R$850/mo"
```

CLI returns:

```text
==============================================================
  COMPLIMENTARY API KEY (copy now — shown only once)
  cmdr_live_Xd7kLp3ZmQ9FnRsAvTyCjH2uWbE4oNgP

  prefix:       cmdr_li
  rate limit:   120/min
  billing mode: complimentary
  price:        R$ 0,00 (bundled externally)
  paid_until:   — (not applicable)
  status:       active (permanent until revoked)
==============================================================
```

**Climax:**
The 5th of the following month arrives. `comadre-keys revenue --month current` shows:

```text
===========================================================
  Revenue Report — June 2026
===========================================================
  Paid customers:           13
  Pending:                   1
  Suspended (carry-over):    1
  Complimentary:             1   (not counted in MRR)
  ─────────────────────────────
  Monthly recurring (paid): R$ 1,732.00
  Projected (if all pay):   R$ 1,821.00
  Complimentary keys:        1 (AgroBots — "incluída no pacote infra R$850/mo")
===========================================================
```

On the 6th, the cron suspension sweep ignores AgroBots's key (`billing_mode != 'manual'`). AgroBots never sees a 401, never receives a Comadre-specific charge.

**Resolution:**
Months later, the AgroBots contract ends. Ricardo revokes manually:

```bash
comadre-keys revoke-key <key-prefix> --reason "bundle contract ended 2026-09-30"
```

Key suspended. Customer record preserved. AgroBots can return in the future with a `reactivate` if the bundle is renewed.

**Revealed Requirements:**
- `--cpf` and `--cnpj` are mutually exclusive on `create-customer`; both validated by the Brazilian verification-digit algorithm
- `api_key.billing_mode` enum with values: `manual` (default, MVP), `complimentary`, `automated` (reserved for future PSP adapters)
- `paid_until` is nullable for `complimentary` keys; cron suspension filters `WHERE billing_mode = 'manual' AND paid_until < today`
- Revenue report explicitly separates complimentary keys with a descriptive note (from the key's `notes` field), but **never** includes them in MRR or projected revenue
- `revoke-key --reason <text>` for manual termination of a complimentary key (ends bundle contracts)

---

### Journey Requirements Summary

The six journeys collectively require these capability areas:

**CLI capability areas (operator-facing):**

| Capability | Primary commands | Revealed by journey |
|---|---|---|
| Customer lifecycle | `create-customer`, `update-customer`, `delete-customer --hard`, `list-customers`, `show` | J1, J3 |
| Tax-ID validation | CPF/CNPJ checksum validation on `create-customer`, mutually-exclusive flags | J1, J6 |
| Key lifecycle | `issue-key`, `update-key`, `rotate-key`, `revoke-key`, `list-keys`, `suspend`, `reactivate`, `show` | J1, J3, J5, J6 |
| Billing state | `mark-paid`, `at-risk`, `revenue`, automatic cron suspension sweep | J2, J3 |
| Complimentary billing mode | `issue-key --billing-mode complimentary`, `revoke-key --reason`, separate revenue reporting | J6 |
| Observability | `show --audit-tail`, per-key request stats, `revenue --month` | J2, J5 |
| LGPD compliance | `delete-customer --hard` with CPF/CNPJ purge | (implicit, required by scope) |

**API capability areas (customer-facing):**

| Capability | Contract | Revealed by journey |
|---|---|---|
| API-key authentication | Bearer token lookup by hash against SQLite, 60s memory cache | J4 |
| Dynamic rate limiting | slowapi with `key_func=get_api_key`, per-key RPM limit | J5 |
| Suspension 401 | Clear error envelope with operator contact hint | J3, J4 |
| Rate-limit 429 | Standard slowapi response with `Retry-After` header | J5 |
| Identical public contract | Zero changes to `/v1/audio/speech` request/response shape | J4 |

**Automation capability areas:**

| Capability | Mechanism | Revealed by journey |
|---|---|---|
| Daily suspension sweep | Cron at 00:30 operator TZ, bulk `UPDATE` of expired keys | J2, J3 |
| Billing-mode-aware suspension | Cron filters `WHERE billing_mode = 'manual' AND paid_until < today`, ignores complimentary | J6 |
| Reactivation propagation | 60s in-memory cache TTL on the auth lookup | J3 |
| Audit logging | Append-only `audit_log` table, every CLI mutation + cron event | J3, J5 |
| Request-stat counters | In-memory counters per key, reset on restart (best-effort observability, not billing record) | J5 |

**Documentation capability areas:**

| Capability | Deliverable | Revealed by journey |
|---|---|---|
| Operator runbook | `docs/monetization.md` covering onboarding, billing ritual, troubleshooting, complimentary keys | J1, J2, J5, J6 |
| Customer-facing error guidance | Error `hint` fields pointing to operator contact | J3, J4 |
| CLI `--help` per subcommand | Typer auto-help with operator-actionable examples | J1, J2, J3, J5, J6 |

## Domain-Specific Requirements

### Compliance & Regulatory

**LGPD (Lei Geral de Proteção de Dados Pessoais — Brazilian Law 13.709/2018)**

Applies directly because Comadre 2.0.0 processes personal data: customer name, email, CPF (individuals), CNPJ (legal entities — CNPJ alone is less sensitive but often accompanied by a responsible person's name and email).

Binding requirements:

- **Legal basis for processing** — declared as "execução de contrato" (Art. 7, V): the operator collects customer data exclusively to execute the API-access subscription. No secondary use, no data sharing, no profiling.
- **Data minimization** — schema stores only what is necessary for billing identification and contact: name, email, either CPF or CNPJ, free-form notes. No address, no phone, no birthdate, no photographs.
- **Encryption at rest for sensitive fields** — CPF and CNPJ encrypted via `cryptography.fernet` with key material in `KEY_REGISTRY_ENCRYPTION_KEY` environment variable. Email and name stored as plaintext (required for CLI display; lower-sensitivity).
- **Right to deletion (Art. 18, VI)** — `comadre-keys delete-customer --hard <id>` irreversibly purges the customer record, encrypted tax ID included, plus all associated keys. Audit log retains only event metadata (who, when, customer-id reference), never personal data.
- **Right to access (Art. 18, II and V)** — `comadre-keys export-customer <id> --format json` produces a machine-readable export of the stored data (decrypted tax ID included), for fulfillment of access requests.
- **Breach notification (Art. 48)** — if the SQLite file is exposed or the encryption key is compromised, the operator must notify ANPD and affected customers within a reasonable timeframe. Runbook entry in `docs/monetization.md` documents this obligation.
- **Data retention** — retained as long as the commercial relationship plus the period required by Brazilian commercial law (typically 5 years for fiscal records). Deletion is operator-driven via CLI, not automatic.
- **Controller identification** — the operator is the LGPD data controller (Art. 5, VI). Comadre the software is a tool. `docs/monetization.md` makes this explicit so operators know they must publish their own privacy policy.

**Brazilian tax and invoicing (out of MVP scope)**

MVP does not emit NFSe nor interact with municipal tax authorities. NFSe is the operator's responsibility (their accountant, a PSP like Asaas, or dedicated invoicing). Integration deferred to 2.1+.

**Consumer protection (CDC)**

The suspended-but-not-deleted contract honors CDC principle of proportionality. MVP does not collect funds directly; refund policy is the operator's responsibility. `docs/monetization.md` provides a template paragraph operators can include in their own terms of service.

### Continuity with Existing Hardening (Non-Regression Contract)

Comadre 1.6.2 has undergone two black-box penetration tests and several hardening phases. The monetization feature cluster **must not regress any of these controls**. Every PR in this cycle must pass a checklist that verifies the following remain intact:

**External attack surface (Caddy + FastAPI):**

| Control | Source | Verification |
|---|---|---|
| Security headers (HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, `upgrade-insecure-requests`) | `deploy/caddy/Caddyfile`, `Caddyfile-no-landing` | Integration test hitting `/` and `/v1/*`, asserting each header present and correct |
| Server/Via banner stripping (Caddy `-Server`, `-Via` at servers and handler levels) | Caddyfile global `servers` block and per-handler `header_down` | Response inspection test — no `Server: ...` or `Via: ...` on any status code (the documented Caddy 404/308 leak is excluded; see `feedback_caddy_server_header.md`) |
| `request_body max_size 1MB` in Caddy reverse_proxy | Caddyfile `request_body` directive | Test sending 2MB payload, expect 413 before reaching app |
| Swagger UI / ReDoc / OpenAPI spec disabled | `docs_url=None, redoc_url=None, openapi_url=None` in `create_app()` | Test that `/docs`, `/redoc`, `/openapi.json` return 404 |
| `redirect_slashes=False` | `FastAPI(redirect_slashes=False)` | Test that `/health/` does not 307-redirect to `/health` |
| UFW ports 22/80/443 only | `deploy/ansible/playbooks/bootstrap.yml` | `ansible-playbook health.yml` reports UFW status; no new listening port added by CLI or cron |
| tts-service only on internal Docker network | `compose.yaml` `expose: 8000`, no `ports:` | No new service opens a host port |
| Docker log rotation (10MB × 5) | `compose.yaml` `logging` driver | Compose config retained in all new services (none expected — MVP adds no containers) |

**Authentication and rate limiting:**

| Control | Source | Verification |
|---|---|---|
| Timing-safe API-key comparison | `hmac.compare_digest` in `verify_api_key` | All new key-comparison code paths use `hmac.compare_digest`, never `==` |
| `SecretStr` for sensitive config | `api_key: SecretStr` in `config.py` | New sensitive config fields (`key_registry_encryption_key`) use `SecretStr` |
| slowapi `SlowAPIMiddleware` registered | `app.add_middleware(SlowAPIMiddleware)` in `create_app()` | Regression test: rate-limit actually applies (regression target for the bug in `edfcb33`) |
| `get_client_ip` reads XFF only behind Caddy `trusted_proxies private_ranges` | `rate_limit.py` + Caddyfile | New endpoints (if any) reuse the same helper — never `request.client.host` directly |
| `/v1/audio/speech` auth contract unchanged from caller's perspective | `api.py` `verify_api_key` dependency (reimplemented internally) | Existing test suite in `tests/test_api.py` passes without contract-breaking modification |
| `/health` minimal-for-unauth behavior | `main.py` `_try_auth` + `build_minimal_health_response` | Regression test in `tests/test_health.py` retained |

**Error handling and logging:**

| Control | Source | Verification |
|---|---|---|
| Uniform error envelope `{error: {message, type, hint}}` | `exceptions.py` + all handlers | Every new error path returns this shape; zero raw `HTTPException` raises |
| `ComadreError` subclasses only | `exceptions.py` hierarchy | New errors (`ApiKeySuspendedError`, `ApiKeyNotFoundError`, `InvalidTaxIdError`, `KeyRegistryError`) extend `ComadreError`, set `status_code`, `error_type`, `hint` |
| Error hints sanitized — no env var names, no internal paths, no stack traces | `exceptions.py` hint fields | Code review checklist item; tax-ID validation errors never echo the invalid input |
| 405 handler returns standard envelope | `_method_not_allowed_handler` in `main.py` | Retained |
| 422→400 validation handler retained | `validation_error_handler` in `main.py` | Retained |
| Structured logging via `get_logger(component)` — never `print()`, never dumps of headers/bodies | `logging.py` setup + codebase-wide discipline | Pre-commit / code review; new middleware never logs `Authorization` header or request body content |

**Module boundaries (architecture):**

| Control | Source | Verification |
|---|---|---|
| Import graph downward-only (`config` → `exceptions/schemas` → `preprocessing` → `service` → `rate_limit` → `api/health` → `main`) | Project-wide convention | New modules placed correctly: `keys/db` and `keys/auth` between `rate_limit` and `api`; `keys/billing` between `keys/db` and `keys/auth`; `keys/cli` has its own entry point and is NOT imported by the app runtime |
| No HTTP concerns in `service.py`, no business logic in `api.py` | Enforced by review | New key-lookup logic lives in `keys/auth.py`, not `api.py` |
| No raw `os.environ` — use `pydantic-settings` | `config.py` pattern | New settings (`key_registry_db_path`, `key_registry_encryption_key`, `operator_contact_hint`, `billing_day`) added to `Settings` class, not read from `os.environ` directly |

**Deployment and ops:**

| Control | Source | Verification |
|---|---|---|
| Docker Compose v2 syntax (`docker compose`, never `docker-compose`) | `CLAUDE.md`, playbooks | New playbook tasks use v2 syntax |
| `uv` only for package management | `CLAUDE.md`, `uv.lock` | New deps added via `uv add`, never pip/poetry |
| Ansible become password passed via `-e`, not stored in inventory | `CLAUDE.md` | New playbooks (`backup-keys.yml`, `restore-keys.yml`) use the same pattern |
| Required env vars guarded in compose (`${VAR:?must be set}`) | `compose.yaml` | `KEY_REGISTRY_ENCRYPTION_KEY:?must be set` guard added. `API_KEY` guard **removed** in 2.0.0 (retired with FR27). |
| No workers/threads for scaling — horizontal replicas only | `compose.yaml` `deploy.replicas` | Monetization stays compatible with multi-replica (each replica reads the same SQLite file, WAL mode for concurrent reads) |
| Models deploy via SSH/SCP, not git | `deploy-models.yml` | No DB fixtures committed to git; DB created on first boot, optionally seeded from a backup tarball |
| `_bmad-output/` tracked in git | `CLAUDE.md` | New artifacts (PRD, architecture, stories) committed |

### Technical Constraints (Monetization-Specific)

**Security boundaries:**

- **SSH is the sole administrative surface** — all CLI operations require a logged-in SSH session. No CLI subcommand exposes itself as an HTTP endpoint. No new listening ports.
- **SQLite file permissions** — `0600`, owned by the Comadre service user. Ansible bootstrap sets this; `health.yml` verifies it; regression test in the deploy playbook fails if the mode drifts.
- **Encryption-at-rest key handling** — `KEY_REGISTRY_ENCRYPTION_KEY` set via `.env` (mode `0600`), read via `pydantic-settings` as `SecretStr`. Never echoed in logs, never included in error hints, never printed by the CLI.
- **API-key storage** — plaintext never persisted. SHA-256 hash + 8-character prefix for identification only. Plaintext key displayed **once** at creation; never retrievable afterward. `show` commands never display plaintext.
- **Timing-safe key lookup** — the auth middleware hashes the inbound bearer token with SHA-256, then `hmac.compare_digest` against the stored hash. Even on a miss, a dummy comparison is performed to equalize timing (prevents "key exists" vs "key missing" timing leaks).
- **In-memory cache** — 60s TTL keyed by hash, stores only the minimal auth payload (`customer_id`, `status`, `rate_limit_rpm`, `paid_until`, `billing_mode`). Never caches the plaintext key; never caches CPF/CNPJ.
- **Audit log integrity** — append-only `audit_log` table; no DELETE or UPDATE except via `delete-customer --hard` which purges personal data but retains event metadata. Tampering detectable post-facto via nightly backup comparison.
- **SQL injection prevention** — all queries use parameterized statements (`?` placeholders, never string interpolation). Any CLI arg that becomes a SQL value passes through sqlite3's bound-parameter layer, never a format string.

**Privacy requirements:**

- CPF/CNPJ never appears in logs, HTTP responses, error envelopes, or CLI output except in explicit operator-initiated `show` and `export-customer` commands.
- Customer name and email appear in operator-facing CLI output only; never in customer-facing API responses.
- The access-log middleware continues to log `client_ip | method | path | status | duration` and nothing else — no Authorization header, no request body, no response body, no API-key prefix.
- Validation errors on CPF/CNPJ do not echo the invalid value in the error message or hint — prevents log-injection and reconnaissance.
- Tax-ID checksum validation runs entirely in-process, no external service call.

**Enumeration resistance:**

- The 401 error envelope does not distinguish between "key does not exist" and "key has been suspended" at the *rate-limit layer* — both rate-limit identically (by client IP, since a missing key cannot be rate-limited by key). An invalid-key 401 returns the standard auth-error hint without revealing whether the prefix was ever valid.
- The *suspended-key* 401 returns a hint directing the customer to their operator (per J3/J4), but only after successful hash match. Valid-but-suspended vs. invalid is distinguishable *only after proving key possession* — acceptable because a valid key was already observed by someone.
- Rate limiting applies to failed auth attempts via the existing per-IP bucket (slowapi handles this regardless of auth success). Unlimited enumeration is therefore bounded by the per-IP rate limit.

**Performance requirements (unchanged from §Success Criteria):**

- Auth-path overhead (SQLite lookup + cache hit path) under 5 ms p99 for a 1,000-customer database. Verified by a benchmark in the test suite that fails CI on regression.
- Suspension cron sweep under 1 s for 1,000 active keys. WAL mode prevents cron sweeps from blocking auth reads.
- CLI `list-customers` / `list-keys` under 200 ms for 1,000 customers.

**Availability requirements:**

- Monetization must not degrade existing Comadre availability (≤10s great TTS latency, 10–90s acceptable WhatsApp pace).
- SQLite single-file durability acceptable given nightly backup. Backup restoration runbook documented.
- Auth path has no external dependencies (no network, no DNS, no outbound HTTP). VPS online ⇒ auth works.

### Integration Requirements

**MVP (2.0.0):**

- OS-level cron (pre-existing in deploy). New entries: `comadre-daily-suspension` at 00:30 operator TZ, `comadre-keys-backup` at 02:00.
- Ansible playbooks (extends existing suite). `bootstrap.yml` installs DB/CLI/cron; `cleanup.yml` removes them; new `backup-keys.yml` and `restore-keys.yml`.
- **No external services.** No PSP, no SMTP, no webhook listener, no background queue. Fully self-contained in the existing Comadre container + host cron.

**Growth (2.1+, not binding for MVP):**

- PSP webhook endpoints at `/v1/billing/webhook/<provider>` behind the existing Caddy reverse proxy, signature-verified per-provider. Each adapter validates the provider's HMAC signature *before* mutating any record. Reuses the same security controls (envelope, rate-limit, `request_body max_size`, structured logging).

### Risk Mitigations

| Risk | Mitigation | Residual exposure |
|---|---|---|
| SQLite file corruption | Nightly backup via `backup-keys.yml`; restore runbook | Up to 24 h of data loss |
| Encryption key loss (operator deletes `KEY_REGISTRY_ENCRYPTION_KEY`) | Key included in nightly backup tarball, encrypted with operator-owned secret, stored separately | If both backup and key lost, CPF/CNPJ unrecoverable; other billing state remains legible |
| CPF/CNPJ leak via log | Middleware scrubs tax IDs; code-review discipline prevents `logger.info(customer.cpf)` | No automated enforcement in MVP; mitigated by the rule: CPF/CNPJ only ever touched by the `keys/db` module |
| Plaintext API key leak via log | CLI prints plaintext key **once** to stdout; access log never logs Authorization header; no request-body dumps | Operator must secure the terminal session where the plaintext appears (SSH scrollback, tmux buffers) |
| Timing-attack enumeration of valid key prefixes | SHA-256 hash + `hmac.compare_digest` against stored hash, with a dummy comparison on miss to equalize timing | Negligible — attacker learns nothing from timing |
| Unbounded key enumeration | slowapi per-IP rate limit applies to failed auth attempts regardless of key existence | Bounded by existing 30/min per-IP limit |
| SQL injection via CLI input | Parameterized queries everywhere; no string-formatted SQL | Requires discipline — enforceable via `bandit` or manual review |
| Cron not running (drift, clock skew, disabled) | `comadre-keys health` command reports last successful cron run; `health.yml` playbook flags cron absence | Operator must periodically verify |
| Concurrent CLI + cron writes | WAL mode; CLI uses short transactions; cron uses single `UPDATE ... WHERE` | No multi-writer hazard at current scale |
| Operator forgets billing day 05 | `issue-key` output explicitly shows first-charge date | None expected |
| Encryption-key rotation without re-encrypting existing rows | `rotate-encryption-key` command is the only supported path; enforces full re-encryption before swapping the key | If operator bypasses the command and edits `.env` directly, all encrypted fields become unreadable — documented as a "do not do this" in the runbook |
| Backup tarball leak | Backup file mode `0600`; backup dir outside Docker volumes | Operator must secure off-VPS copies of backups |
| Audit log tampering by a compromised service user | WAL + nightly backup comparison + append-only discipline | Detection only, not prevention (consistent with threat model: trusted operator, untrusted external) |
| PSP webhook spoofing (Growth, 2.1+) | Each adapter verifies HMAC signature before mutating any record | 2.1+ implementation concern |
| ANPD audit or data-subject access request | `export-customer` + `delete-customer --hard` + audit log provide everything needed | Operator must respond within LGPD-mandated timeframes |
| Regression in existing pentest-resolved controls | Non-regression contract (above) enumerates every control; CI job runs the full regression suite; PR checklist requires sign-off | Risk is procedural, not technical |

**Domain considerations explicitly out of scope for MVP:**

- PCI-DSS (no card data; delegated to PSP in 2.1+)
- Open Banking / Pix Automático direct integration (delegated to PSP adapters)
- KYC/AML verification of operator's customers (operator's business process)
- GDPR for EU data subjects (Comadre targets Brazilian market)
- Multi-region data residency (data stays on operator's VPS)

### Epic Mapping

The controls enumerated in this section (Continuity with Existing Hardening, Technical Constraints, Risk Mitigations, LGPD primitives) are the source material for **Epic 2 — Security & Compliance** defined in the Product Scope. Every row in the non-regression contract tables maps to one or more acceptance criteria in a security story; no control appears only here and not in a story. When `bmad-create-epics-and-stories` runs, security work is enumerated as first-class stories rather than embedded as checkboxes inside feature stories.

## API Backend & CLI Tool Specific Requirements

With the compliance posture, non-regression contract, and LGPD primitives established above, the next sections describe the technical surface that realizes these requirements: the HTTP endpoints, authentication model, data schemas, error envelope, rate-limit resolution, and the operator-facing CLI command surface. Everything here is observable from either the customer-facing API or the operator-facing CLI; nothing here introduces new external exposure or breaks the public contract inherited from Comadre 1.6.2.


### Project-Type Overview

Comadre 2.0.0 is fundamentally an `api_backend` with a `cli_tool` companion. The customer-facing surface is the HTTP API (unchanged public contract); the operator-facing surface is a local CLI. The split is clean: no CLI command exposes itself over HTTP, and no API endpoint mutates operator-only state. The only cross-surface interaction is the SQLite key-registry file that both read and write, coordinated by transactions and the 60-second in-memory cache TTL in the API auth path.

### Endpoint Specification

**Customer-facing endpoints (2.0.0 — MVP):**

The public API contract is identical to Comadre 1.6.2. No new endpoints are added for the customer-facing surface. The only observable change is *how* the existing endpoints authenticate.

| Method | Path | Status | Change |
|---|---|---|---|
| `POST` | `/v1/audio/speech` | Unchanged contract | Bearer token is now resolved via SQLite key-registry lookup instead of a global `API_KEY` env-var comparison |
| `GET` | `/health` | Unchanged contract | Authenticated detail retrieval now accepts any valid customer key (not only a single operator key) |
| `GET` | `/` | Unchanged | Static landing page served by Caddy |

**Explicitly NOT in MVP:**

- No `/v1/customers`, `/v1/keys`, `/v1/invoices`, or any other admin HTTP endpoint
- No `/v1/billing/webhook/*` (deferred to 2.1+ with automated PSP integration)
- No `GET /v1/audio/speech/status` or other polling endpoints
- No REST-style CRUD surface on the operator's data

**Growth path (2.1+):**

| Method | Path | Purpose |
|---|---|---|
| `POST` | `/v1/billing/webhook/asaas` | Asaas PSP webhook (HMAC-signature verified) |
| `POST` | `/v1/billing/webhook/iugu` | Iugu PSP webhook |
| `POST` | `/v1/billing/webhook/stripe` | Stripe PSP webhook |

Each adapter validates signature *before* any SQLite mutation. Each is rate-limited by the same slowapi machinery. Each reuses the standard error envelope on failure.

### Authentication Model

**2.0.0 auth path (replaces the single-`API_KEY` check):**

```text
client → Caddy (TLS, XFF injection)
       → FastAPI
         → slowapi per-IP throttle (always-on)
         → verify_api_key dependency
           → extract Bearer token
           → SHA-256 hash the inbound token
           → cache lookup (60s TTL)
             HIT  → validate status + paid_until + billing_mode → allow/deny
             MISS → SQLite SELECT by key_hash
                    found    → cache entry, validate, allow/deny
                    not found → dummy hmac.compare_digest (timing equalization) → deny
         → slowapi per-key throttle (dynamic rpm from cached record)
         → route handler
```

**Guarantees:**

- Bearer format is the only accepted auth scheme (`Authorization: Bearer <token>`). Any other scheme, or a missing header, returns 401 with `type: authentication_error`.
- The plaintext bearer token is never stored, never logged, never echoed in error envelopes.
- Timing-safe comparison (`hmac.compare_digest`) on hash match; dummy comparison on miss to equalize timing.
- The cache stores only the minimal authorization payload (`customer_id`, `status`, `rate_limit_rpm`, `paid_until`, `billing_mode`). Plaintext keys and personal data never enter the cache.
- Cache invalidation: natural 60-second TTL. After an operator runs `suspend`, `reactivate`, `mark-paid`, or `revoke-key`, the effect propagates to all replicas within the TTL window. MVP does not support immediate cross-replica cache invalidation — the 60-second TTL is the worst-case propagation bound. The `comadre-keys cache-status` CLI command reports this bound to the operator (and, when practical, cache-health telemetry such as hit rate) without performing any cache mutation. Operators who need faster propagation can restart the affected replica(s), which empties the in-memory cache.

**Upgrade from 1.6.2 (2026-04-18 revision):**

2.0.0 is a breaking release with no dual-mode. The SQLite-backed registry is the sole accepted auth path. Operators upgrading must seed at least one customer + issue one key before bringing the service back up. The single-`API_KEY` env var is no longer honoured; a request authenticated with the old global key fails closed with the same 401 envelope as any invalid key. Container restart clears the in-memory auth cache — post-upgrade first request pays one SQLite lookup, same as any cold start.

### Data Schemas

**SQLite schema (MVP):**

```sql
CREATE TABLE customer (
    id              TEXT PRIMARY KEY,             -- cust_01HF3...
    name            TEXT NOT NULL,
    email           TEXT NOT NULL,
    tax_id_kind     TEXT NOT NULL CHECK (tax_id_kind IN ('cpf', 'cnpj')),
    tax_id_encrypted BLOB NOT NULL,                -- Fernet ciphertext
    notes           TEXT DEFAULT '',
    registered_at   TEXT NOT NULL,                 -- ISO 8601 UTC
    deleted_at      TEXT                           -- NULL unless hard-deleted (LGPD purge retains tombstone row with null tax_id)
);

CREATE TABLE api_key (
    id              TEXT PRIMARY KEY,             -- key_01HF3...
    customer_id     TEXT NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
    key_hash        TEXT NOT NULL UNIQUE,          -- sha256(plaintext)
    key_prefix      TEXT NOT NULL,                 -- first 8 chars, for identification
    rate_limit_rpm  INTEGER NOT NULL CHECK (rate_limit_rpm > 0),
    status          TEXT NOT NULL CHECK (status IN ('active', 'suspended', 'revoked')),
    billing_mode    TEXT NOT NULL CHECK (billing_mode IN ('manual', 'complimentary', 'automated')),
    price_monthly   REAL NOT NULL DEFAULT 0.0,     -- BRL, 0.0 for complimentary
    paid_until      TEXT,                          -- NULL for complimentary; ISO date otherwise
    created_at      TEXT NOT NULL,
    last_used_at    TEXT,                          -- updated opportunistically, not on every request
    notes           TEXT DEFAULT ''
);

CREATE TABLE audit_log (
    id              INTEGER PRIMARY KEY AUTOINCREMENT,
    occurred_at     TEXT NOT NULL,
    actor           TEXT NOT NULL,                 -- 'cli:<shell-user>' or 'cron:suspension-sweep' or 'auth:cache-miss'
    action          TEXT NOT NULL,                 -- create_customer, issue_key, suspend, mark_paid, ...
    target_type     TEXT,                          -- 'customer' | 'api_key' | 'system'
    target_id       TEXT,                          -- customer_id or key_id
    details_json    TEXT                           -- structured event data; MUST NOT contain personal data
);

CREATE UNIQUE INDEX idx_api_key_hash ON api_key(key_hash);
CREATE INDEX idx_api_key_customer ON api_key(customer_id);
CREATE INDEX idx_api_key_sweep ON api_key(billing_mode, paid_until) WHERE status = 'active';
CREATE INDEX idx_audit_occurred ON audit_log(occurred_at);
```

**pydantic models (request-side):**

- `CustomerCreate` — name, email, (cpf XOR cnpj), optional notes. `@model_validator` enforces mutual exclusivity and checksum validation.
- `KeyIssue` — customer_id, rate_limit_rpm, billing_mode (defaults to `manual`), price_monthly (defaults based on billing_mode), notes.
- `KeyUpdate` — partial update on rate_limit_rpm, price_monthly, notes.
- `KeyRevoke` — key_id, reason (free-text).
- `PaymentConfirm` — key_id, paid_until (ISO date).

**No changes** to existing customer-facing schemas: `SpeechRequest`, `HealthResponse`, error envelope. The public API contract is preserved identically.

### Error Codes

| Code | Scenario | `type` | Source |
|---|---|---|---|
| 400 | Invalid request (existing) | `invalid_request_error` | Existing |
| 400 | Invalid CPF/CNPJ checksum on `create-customer` | `invalid_request_error` | New, CLI-only (never surfaces on HTTP) |
| 401 | Missing/malformed Authorization header | `authentication_error` | Existing |
| 401 | Unknown API key (hash not found) | `authentication_error` | Existing contract, new internal path |
| 401 | API key suspended or revoked | `authentication_error` with operator-contact hint | New |
| 404 | Voice not found (existing) | `not_found_error` | Existing |
| 405 | Method not allowed (existing) | `method_not_allowed_error` | Existing |
| 429 | Rate limit exceeded (per-key via dynamic slowapi) | `rate_limit_error` | Existing envelope, new dynamic limit source |
| 500 | Generation error (existing) | `server_error` | Existing |
| 503 | Service warming up (existing) | `service_unavailable` | Existing |

New `ComadreError` subclasses:

- `ApiKeyNotFoundError(401, authentication_error)` — hash lookup miss
- `ApiKeySuspendedError(401, authentication_error)` — hash match but status=suspended; hint directs to operator
- `ApiKeyRevokedError(401, authentication_error)` — hash match but status=revoked; hint directs to operator
- `InvalidTaxIdError(400, invalid_request_error)` — CLI-side only; never reaches HTTP path
- `KeyRegistryError(500, server_error)` — SQLite unreachable or corrupt; auth path fails closed

### Rate Limits

**Endpoint limits (unchanged from 1.6.2 at deployment default):**

| Endpoint | Default | Key function | Source |
|---|---|---|---|
| `POST /v1/audio/speech` | `rate_limit_rpm` per API key (DB row) | `key:<key_id>` | New in 2.0.0; `limits` library direct, no slowapi |
| `GET /health` | Unthrottled at app layer | n/a | 2026-04-18 revision: slowapi removed, no replacement rate-limit on `/health` |

**Per-key limit resolution (2026-04-18 revision):**

Every API key carries its own `rate_limit_rpm` field. The speech endpoint uses a FastAPI `Depends(check_rate_limit)` that reads `request.state.auth_payload.rate_limit_rpm` (populated by `verify_api_key`) and enforces it via the `limits` library directly — `slowapi` is **removed** in 2.0.0 in favour of a thinner layer over `limits.aio.strategies.MovingWindowRateLimiter`. Bucket key is `key:<key_id>`; `key_id` is stable across `rotate-key`, so a rotated plaintext shares the pre-rotation bucket until the minute rolls over. The rate-limit database row's `rate_limit_rpm` is enforced verbatim — no defensive global default, because the schema's `CHECK (rate_limit_rpm > 0)` constraint guarantees every row has a valid value.

**No per-IP rate-limit in the application layer.** The only rate-limit bucket is per-key. Motivation: per-IP logic in the app exists only when multiple callers share a key (pre-2.0.0 single-`API_KEY` world); once every caller authenticates with their own key, per-IP is a redundant layer that fights the per-key cap.

### API Documentation

Public `openapi.json`, `/docs`, `/redoc` remain **disabled** (pentest finding `adcb431`). Documentation is exclusively prose-form in the repo:

- `docs/api-reference.md` — unchanged customer-facing contract
- `docs/monetization.md` — operator runbook (new, 2.0.0)
- `CLAUDE.md` — updated with monetization-specific architecture gotchas
- Per-CLI-command `typer --help` — operator-actionable, includes examples
- `project-context.md` regenerated at release to reflect the new module graph

**No versioning story change:** the `/v1/*` prefix remains the public version marker. No `/v2/`, no dual-routing, no deprecation shim — the auth internals change but the surface stays on `v1`.

**No SDK delivered by the project.** Customers integrate via raw HTTP (n8n HTTP Request node, `curl`, `requests`, etc.). If a customer wants an SDK, they can generate one from the internal OpenAPI spec — but `openapi.json` is disabled for security, so this would require a deploy-time toggle. Out of scope for 2.0.0.

### CLI Tool Specification

**Command structure (Typer subcommands):**

```text
comadre-keys create-customer  --name --email ({--cpf | --cnpj}) [--notes]
comadre-keys update-customer  <customer-id> [--add-note | --email]
comadre-keys delete-customer  <customer-id> --hard          # LGPD purge
comadre-keys export-customer  <customer-id> --format {json|yaml}  # LGPD access

comadre-keys issue-key        --customer <id> --rpm N [--billing-mode {manual|complimentary}] [--price R$]
comadre-keys update-key       <key-prefix> [--rpm N] [--price R$] [--notes]
comadre-keys rotate-key       <key-prefix>                  # new plaintext, same id, old hash replaced
comadre-keys revoke-key       <key-prefix> --reason <text>

comadre-keys mark-paid        <key-prefix> --until <YYYY-MM-DD>
comadre-keys suspend          <key-prefix>                  # manual suspension (out-of-cycle)
comadre-keys reactivate       <key-prefix>

comadre-keys list-customers   [--deleted] [--format {table|json}]
comadre-keys list-keys        [--status] [--billing-mode] [--paid-until-lte <date>] [--format]
comadre-keys show             <customer-id | key-prefix> [--audit-tail N]

comadre-keys revenue          --month {current|YYYY-MM}
comadre-keys at-risk          --window <Nd>
comadre-keys health                                          # cron status, DB integrity, cache stats

comadre-keys rotate-encryption-key  --new-key <fernet-key>   # re-encrypt all rows atomically
comadre-keys cache-status                                    # report the 60s cache-TTL propagation bound (no mutation)

comadre-keys --version
comadre-keys --install-completion                            # Typer built-in
```

**Output formats:**

- Human-readable: `rich`-formatted tables (default for `list-*`, `show`, `revenue`, `at-risk`)
- Machine-readable: `--format json` on every list/show command, emitting newline-delimited JSON objects (NDJSON) or a single JSON array at the operator's choice
- YAML via `--format yaml` for `export-customer` (LGPD access response is easier to read)
- Every command exits `0` on success, non-zero on error, with error envelope identical in structure to the HTTP `{error: {message, type, hint}}` shape (but rendered as human-readable text on stderr unless `--format json`)

**Config method:**

- Reads from the same `pydantic-settings` instance as the FastAPI app (no duplicate config loading). `.env` on the VPS is the single source of truth.
- Key config keys the CLI cares about: `KEY_REGISTRY_DB_PATH`, `KEY_REGISTRY_ENCRYPTION_KEY`, `OPERATOR_CONTACT_HINT`, `BILLING_DAY` (integer, default 5), `BILLING_TIMEZONE` (IANA string, default `America/Sao_Paulo`).
- CLI never takes credentials as CLI arguments; always reads from environment/`.env`.

**Scripting support:**

- All commands are non-interactive by default; no CLI command prompts for input. Confirmation-required verbs (`delete-customer --hard`, `rotate-encryption-key`) accept `--yes` to skip confirmation for automation.
- `comadre-keys health --format json` is the canonical machine-checkable health check for operator monitoring; exits non-zero on any unhealthy condition.
- `comadre-keys list-keys --status active --paid-until-lte today --format json` is the canonical "who owes me" query for external automation (if an operator scripts their own Pix reconciliation).

**Shell completion:**

- Typer's `--install-completion` installs bash/zsh/fish completion per-user. Bootstrap documents this as a recommended (not required) post-install step.

### Implementation Considerations

**Replica safety:**

- SQLite is single-writer-many-reader under WAL. The daily cron sweep is the only heavy writer; all CLI commands issue short transactions. Multi-replica deployments share the same volume-mounted SQLite file and each replica's auth cache is independent (60s TTL per replica).
- The CLI must be runnable from any replica container or from the host. Bootstrap installs it system-wide via `uv tool install` so the operator's SSH session has it without activating a venv.

**Upgrade from 1.6.2 (2026-04-18 revision):**

- 2.0.0 is a breaking release — no `monetization_enabled` toggle, no dual-mode. Upgrade sequence: (1) set `KEY_REGISTRY_ENCRYPTION_KEY` in deploy env, (2) bring up a fresh 2.0.0 container, (3) `docker compose exec` or SSH + `comadre-keys create-customer` + `issue-key` to seed at least one key, (4) hand the plaintext to the consumer(s) of the old single-`API_KEY`, (5) service is live. No fallback path — the single-`API_KEY` env var is no longer honoured.
- Rollback: git-revert to the 1.6.2 tag and redeploy. The registry SQLite file persists across versions (it is simply ignored by 1.6.2). No destructive rollback.

**Observability hooks (minimal in MVP):**

- Structured logs continue through `get_logger(component)`.
- `audit_log` table is the source of truth for operator-facing activity history.
- In-memory request-stat counters per key (total, 429 count, peak RPM, avg RPM) are reset on restart — best-effort observability only, not a billing record.

**Runtime Constraints:**

- No new Docker container. Nothing added to `compose.yaml` except environment variables.
- No new background process beyond the existing OS cron.
- No new network egress (no outbound HTTP, no telemetry).
- No admin TCP port, ever.

## Project Scoping & Phased Development

### MVP Strategy & Philosophy

**MVP Approach: Revenue MVP with Platform-Enablement flavor.**

The question driving this cycle is not "does the product work?" — Comadre 1.6.2 already works in production. The question is "can the operator sell it?" The MVP succeeds the moment the first non-author operator runs `comadre-keys revenue --month current` and sees a positive number from actual customer payments. Every MVP decision derives from that test.

Secondary philosophy: **Platform enablement.** The MVP makes Comadre a product an operator *can* resell, not the one Comadre deploys once for itself. The distinction drives the architectural simplicity (no central plane, shard-per-VPS) and the operational posture (CLI-over-SSH, no new containers, no cloud dependencies).

**What is explicitly NOT the MVP approach:**

- **Not Experience MVP** — no visual polish work, no landing-page redesign for monetization, no customer portal. The CLI is intentionally utilitarian.
- **Not Problem-Solving MVP** — the problem (TTS for pt-BR chatbots) was already solved in 1.6.2. This cycle solves the *business* problem of selling that solution.
- **Not a pilot** — the output is an actual release (2.0.0), not a behind-a-flag experiment. 2026-04-18 revision: `monetization_enabled` toggle retired entirely; 2.0.0 is registry-only from the first byte, no flag-gated rollout.

### Resource Requirements

- **Team size:** solo developer (project author). No new hires, no contractors. One of the non-regression constraints is that this cycle must be completable at the same pace as prior feature cycles.
- **Infrastructure:** zero new infrastructure. No new containers, no new database server, no new managed services. SQLite file + existing cron + existing Ansible playbooks. A single VPS remains the entire production footprint for a given operator shard.
- **External dependencies:** zero new third-party services for MVP. Payment Service Providers deferred to 2.1+ as optional pluggable adapters.
- **Validation capacity:** the author can run the MVP against a small pool of friendly operators (Discord / local network) for 30-day field observation. No formal beta program needed.

### MVP Feature Set (Phase 1, Release 2.0.0)

Fully specified in §Product Scope under "MVP — Minimum Viable Product (2.0.0)". The MVP is decomposed into two parallel epics:

- **Epic 1 — Monetization Core** (feature work: schema, auth middleware, CLI, billing adapter, cron, Ansible)
- **Epic 2 — Security & Compliance** (non-regression guard, LGPD primitives, logging discipline, SQL-injection prevention, backup/restore, cron observability)

The MVP ships when **both epics** pass their acceptance criteria — not sooner. Shipping Epic 1 without Epic 2 would expose the project to the exact risks the dedicated security epic is designed to prevent.

**Core user journeys supported at MVP:** J1 (first sale), J2 (recurring collection), J3 (delinquent customer), J4 (customer-side integration), J5 (troubleshooting), J6 (complimentary subscription). All six documented in §User Journeys map to CLI commands and API contract items already listed in §API Backend & CLI Tool Specific Requirements.

### Post-MVP Features

Full lists in §Product Scope under "Growth Features (2.1+)" and "Vision (2.2+)". Strategic framing:

**Phase 2 — Growth (2.1+):** triggered when MVP has validated the operator thesis (≥1 non-author operator running in production with paying customers). Compete on convenience: automate the PSP billing path, add aggregate multi-shard reporting, expose per-key analytics. None of this is ship-blocking for 2.0.0.

**Phase 3 — Expansion (2.2+):** expand the independent-operator thesis into a network: cooperative blocklists, an operator directory, referral revenue sharing, read-only web dashboard behind Headscale. Requires a critical mass of operators first; explicitly gated on Growth-phase adoption signals.

### Risk Mitigation Strategy

The PRD enumerates risks in three places that together form the full risk picture:

- **§Domain-Specific Requirements > Risk Mitigations** — technical/security/operational risks with per-row mitigation and residual exposure (the primary risk table)
- **§Success Criteria > Measurable Outcomes** — validation signals that serve as early warnings if a risk materializes
- **§Product Scope > Vision** — long-term risks around the operator-network thesis, deferred for later phases

This section consolidates the scoping-relevant risk categories and references where each is handled:

**Technical risks:**

- *Regression of existing pentest-resolved controls.* Highest-priority technical risk. Mitigation: dedicated Epic 2 with per-control regression tests in CI; PR checklist; non-regression contract reproduced verbatim in `docs/monetization.md`. Detailed in §Domain-Specific Requirements > Continuity with Existing Hardening.
- *SQLite file corruption or encryption-key loss.* Mitigated by nightly backup playbook + documented restore runbook. Detailed in §Risk Mitigations table.
- *Auth path performance regression.* Bounded by the <5ms p99 overhead target in §Success Criteria. CI benchmark fails the build if regressed.
- *Multi-replica SQLite write contention.* Bounded by WAL mode + short transactions + cron being the only heavy writer. Detailed in §Implementation Considerations > Replica safety.

**Market risks:**

- *The independent-operator thesis might not land.* Detected via the "≥1 non-author operator in 90 days" signal in §Success Criteria. If the signal fails, Growth phase (2.1+) does not proceed; the MVP becomes a refinement cycle for the author's own operation.
- *Brazilian payment landscape might favor cloud providers anyway.* De-risked by the BillingProvider adapter design: if cloud PSPs become dominant, the Asaas adapter in 2.1+ plugs in without refactor. The MVP does not commit to any specific PSP.
- *Customers might reject self-hosted-brand TTS vs. ElevenLabs name recognition.* Out of the operator's control; Comadre's job is to make the unit economics work, not solve the brand-trust problem for every operator's customers.

**Resource risks:**

- *Solo developer, finite attention.* Mitigated by MVP narrow scope: no PSP integration, no SMTP, no web UI, no new containers. Every deferred item is explicitly listed in §Product Scope to prevent scope creep from accumulating as invisible debt.
- *Cycle delay from Epic 2 work.* Accepted as a feature, not a bug. Epic 2 is *not* cuttable. If the cycle runs long, Growth Phase (2.1+) slips — not the non-regression contract.
- *LGPD or tax-compliance surprise.* Partially mitigated by the adapter-deferral posture: the MVP does not emit NFSe or take payments directly, so the operator's tax/legal posture is their own concern. Comadre provides the LGPD primitives (`export-customer`, `delete-customer --hard`, audit log) that let the operator respond to obligations but does not attempt to solve them wholesale.

### Scope Hardening — What This PRD Refuses to Scope

The MVP deliberately refuses the following, with the rationale documented so future contributors understand these are intentional omissions, not forgotten items:

- **No web UI of any kind** — not even read-only, not even behind VPN. Every proposal to add one is deferred to Vision (Phase 3) with the Headscale-gated read-only dashboard.
- **No SMTP integration, no email notifications, no 2FA** — stated as a first-principles user preference, reinforced throughout the discovery conversation.
- **No central billing database** — every VPS is a sovereign shard. Multi-shard aggregation (if ever needed) happens operator-side via SSH, not by introducing a central plane.
- **No automated PSP in MVP** — the manual `mark-paid` path is the only billing-confirmation surface in 2.0.0. Asaas/Iugu/Stripe adapters ship in 2.1+ behind the same `BillingProvider` interface. The MVP is the interface; the implementations are later.
- **No usage-based billing** — all pricing in MVP is flat monthly per key. Usage metering is a capability that belongs in Growth (2.1+) if at all.
- **No customer self-service** — customers cannot rotate their own key, cannot see their own billing status, cannot update their own contact info. All lifecycle mutations are operator-initiated. This is the entire simplification thesis of the product.
- **No tiered SLA** — Comadre's existing latency SLA (≤10s great, 10–90s natural WhatsApp pace, >90s stressed) applies uniformly. Premium keys get more RPM, not faster individual requests.

## Functional Requirements

### Customer Lifecycle Management

- **FR1:** Operator can register a new customer by providing name, email, and either CPF or CNPJ (never both).
- **FR2:** System rejects a new customer record when the provided CPF or CNPJ fails Brazilian checksum validation.
- **FR3:** Operator can attach free-form notes to any customer record and append additional notes without overwriting existing ones.
- **FR4:** Operator can update a customer's email and notes without affecting other fields.
- **FR5:** Operator can irreversibly purge a customer record, including the tax-ID, all associated keys, and personal data, in compliance with the LGPD right to deletion.
- **FR6:** Operator can export a single customer's stored data in a machine-readable format suitable for fulfillment of LGPD data-subject access requests.
- **FR7:** Operator can list all customers, with an optional filter to include tombstone records left by prior LGPD purges.

### API Key Lifecycle Management

- **FR8:** Operator can issue a new API key against an existing customer, specifying the per-key rate limit and monthly price.
- **FR9:** Operator can issue a complimentary API key whose billing is handled outside Comadre (e.g., bundled in an external service contract).
- **FR10:** Operator can update an existing key's rate limit, monthly price, and notes without disclosing or changing the key plaintext.
- **FR11:** Operator can rotate a key, producing a new plaintext while retaining the same key id and customer association; the old key stops working immediately.
- **FR12:** Operator can revoke a key with a free-form reason; revoked keys are retained in the database as historical records.
- **FR13:** Operator can list keys filtered by status, billing mode, paid-until date, or customer id.
- **FR14:** Operator can view full context for a single key including customer, dates, price, notes, and recent audit events.

### Billing State Management

- **FR15:** Operator can mark a manual-mode key as paid through a specified future date.
- **FR16:** Operator can query which keys are approaching billing expiration within a configurable look-ahead window.
- **FR17:** Operator can generate a revenue report for any calendar month showing paid, pending, suspended, and complimentary breakdowns; complimentary keys are reported separately and never counted in recurring-revenue totals.
- **FR18:** System automatically suspends manual-mode keys whose paid date has elapsed, once per day, at a configurable operator-timezone time.
- **FR19:** System preserves suspended keys indefinitely; no data-deletion is automatic.
- **FR20:** System automatically restores a key to active status once its paid date is extended, with propagation time bounded by the auth cache behavior.

### API Authentication and Rate Limiting

- **FR21:** Customer can authenticate HTTP requests to `/v1/audio/speech` using a Bearer API key.
- **FR22:** System validates an incoming Bearer key against an immutably-hashed copy stored in the registry, never storing or comparing the plaintext.
- **FR23:** System caches valid authorizations to satisfy the NFR1 auth-path latency target for repeat requests from the same key.
- **FR24:** System enforces a per-key rate limit derived at request time from the specific key's configured limit.
- **FR25:** ~~System enforces a per-IP rate limit applied independently of auth outcome, so failed auth attempts are bounded.~~ **RETIRED 2026-04-18.** Per-IP rate-limit removed from the application layer. Rationale: with per-key rate-limit and well-dimensioned key sales (sum of `rate_limit_rpm` ≤ server capacity), the TTS compute surface is bounded independent of IP. Enumeration is bounded cryptographically by key entropy (128 bits of `cmdr_live_` + 32 hex chars); per-IP inside the Python layer only added complexity without protecting anything the per-key limit doesn't already cover.
- **FR26:** System equalizes the timing of key-lookup operations so that an attacker cannot distinguish a hash hit from a miss by wall-clock observation.
- **FR27:** ~~System can operate in a legacy single-API-key mode when the monetization toggle is disabled, preserving compatibility with pre-2.0.0 deployments.~~ **RETIRED 2026-04-18.** Comadre 2.0.0 is registry-only from the first byte. The single-`API_KEY` env var is removed; `monetization_enabled` toggle is removed; dual-mode dispatch in `verify_api_key` is removed. Operators upgrade by seeding a customer + key before first request (see §Upgrade from 1.6.2).
- **FR28:** System returns a distinct 401 error envelope for suspended and revoked keys that directs the customer to their operator's billing contact.
- **FR29:** System preserves the request and response contract of `/v1/audio/speech` and `/health` identically to Comadre 1.6.2, so existing customer integrations continue to function without modification.

### Observability and Auditing

- **FR30:** System records every customer and key mutation to an append-only audit log with actor identity, action, target, and timestamp.
- **FR31:** System records every cron-initiated suspension or reactivation event to the audit log.
- **FR32:** Operator can view the audit tail for any customer or key directly from the CLI.
- **FR33:** System maintains in-memory per-key request counters (total, rate-limit rejections, peak throughput, average throughput) for short-term troubleshooting; counters are not durable and reset on service restart.
- **FR34:** Operator can query overall system health (cron liveness, database integrity, auth cache state, backup recency) with a single command.

### Data Privacy and LGPD Compliance

- **FR35:** System encrypts CPF and CNPJ values at rest, with encryption material supplied by the deploy environment.
- **FR36:** Operator can rotate the encryption material by re-encrypting every protected field atomically, without a window in which data is unreadable.
- **FR37:** System prevents personal data (CPF, CNPJ, API-key plaintext) from appearing in structured log messages regardless of log verbosity.
- **FR38:** System preserves audit-log metadata (who, when, what) after a customer's personal data is purged, so operator activity remains traceable without retaining personal data.
- **FR39:** Operator receives a `docs/monetization.md` section "LGPD Operator Obligations" containing: (a) a breach-notification runbook with ANPD contact information, a customer-notification email template, an evidence-preservation checklist, and an internal escalation path; (b) a privacy-policy template paragraph the operator can adapt for their own terms of service.

### Operational Safety

- **FR40:** System can back up the key registry and encryption material nightly, in a single encrypted archive separate from the database file itself.
- **FR41:** Operator can restore the key registry from a prior backup via a dedicated, idempotent playbook.
- **FR42:** System enforces strict file permissions on the SQLite database file and the encryption key material at deploy time, and the health command reports deviations.
- **FR43:** System runs the daily suspension sweep at a fixed operator-timezone time and makes the last successful run timestamp queryable.
- **FR44:** System can operate safely across multiple Comadre replicas reading and writing the same SQLite file without corruption under normal operational load.
- **FR45:** Operator can query auth-cache propagation behavior via a dedicated CLI command; immediate cross-replica cache invalidation is not supported in MVP. The 60-second auth-cache TTL (see NFR6) is the worst-case propagation bound for key-state changes (`suspend`, `reactivate`, `mark-paid`, `revoke-key`, `update-key`). The CLI command documents this bound to the operator and reports cache-health information; it performs no cache mutation.

### Security Regression Prevention

- **FR46:** CI can verify that every security header required by the Caddy configuration (HSTS, CSP, X-Frame-Options, X-Content-Type-Options, Referrer-Policy, Permissions-Policy, upgrade-insecure-requests) is present on every response code returned by the reverse proxy.
- **FR47:** CI can verify that `/docs`, `/redoc`, and `/openapi.json` return 404 in production-configured deployments.
- **FR48:** CI can verify that the auth path uses timing-safe comparison primitives exclusively and never string equality.
- **FR49:** CI can verify that oversized request bodies are rejected at the reverse-proxy layer before reaching the application.
- **FR50:** CI can verify that the rate-limit middleware is registered and actually applies to both the speech and health endpoints.
- **FR51:** CI can verify that no new code raises a raw `HTTPException`; every error path uses a `ComadreError` subclass.
- **FR52:** Operator can verify via the existing `health.yml` Ansible playbook that UFW, SQLite permissions, cron jobs, and backup playbook outputs are in their expected state, with a clear exit code on any deviation.

## Non-Functional Requirements

### Performance

- **NFR1:** Auth-path overhead for a cache-hit request must stay under 5 ms at p99, measured against a 1,000-customer database.
- **NFR2:** Auth-path overhead for a cache-miss request must stay under 15 ms at p99, measured against a 1,000-customer database.
- **NFR3:** The daily suspension cron sweep must complete under 1 second for 1,000 active keys.
- **NFR4:** CLI list-class commands (`list-customers`, `list-keys`) must render the first screenful of output in under 200 ms for a 1,000-customer database.
- **NFR5:** CLI detail-class commands (`show`, `revenue`, `at-risk`) must complete in under 500 ms for the same database size.
- **NFR6:** The auth cache TTL must not exceed 60 seconds; reactivation of a newly-paid key must become visible within that window at the latest.
- **NFR7:** Monetization-related code paths must not add more than 2 ms p99 to the existing `/v1/audio/speech` post-auth request pipeline.

### Security

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

### Reliability & Availability

- **NFR18:** Comadre 2.0.0 must preserve Comadre 1.6.2's latency SLA as documented in `CLAUDE.md` and in `project-context.md`: ≤10 seconds is great, 10–90 seconds is the natural WhatsApp pace, >90 seconds indicates system stress.
- **NFR19:** The auth path must have zero external dependencies at request time — no outbound HTTP, no DNS lookup, no network egress. If the VPS is online, auth works.
- **NFR20:** The key registry must tolerate unclean shutdown without corruption; the post-crash auth cache may be empty but the registry itself must remain readable.
- **NFR21:** Backup Recovery Time Objective (RTO): the `restore-keys.yml` playbook must restore a full key registry from a nightly backup in under 10 minutes for a typical-size shard (under 10,000 customers).
- **NFR22:** Backup Recovery Point Objective (RPO): data loss from a catastrophic VPS failure must not exceed 24 hours (bounded by nightly backup cadence).
- **NFR23:** The daily suspension cron must not block concurrent auth-path reads during the sweep.
- **NFR24:** A Comadre replica restart must not cause any outage longer than the existing warm-up window (≤60 seconds to `/health` returning `healthy`). Monetization must not extend the warm-up time.

### Scalability

- **NFR25:** A single Comadre shard (one VPS, one SQLite file) must support at least 1,000 active customers and 2,000 active keys without violating the performance NFRs above.
- **NFR26:** Scaling beyond a single shard is operator-driven: the operator provisions an additional VPS and migrates or issues keys on it. No shared state is introduced between shards.
- **NFR27:** Per-shard memory overhead added by monetization must stay under 50 MB above the baseline 1.6.2 footprint; the auth cache is the dominant contributor and its size is bounded by the 60-second TTL and the active-request rate.
- **NFR28:** Disk-usage growth from monetization must stay under 50 MB for the first 6 months of typical operator use (customer records + audit log + backups retained in-place for rolling 30-day window).
- **NFR29:** Multi-replica deployments (same VPS, multiple container replicas sharing the SQLite volume) must operate without corruption under normal load; each replica's auth cache is independent, and cache skew up to the 60-second TTL is acceptable.

### Compatibility

- **NFR30:** The public `/v1/audio/speech` and `/health` request/response contracts must remain byte-identical to Comadre 1.6.2; any customer integration that worked against 1.6.2 must continue to work against 2.0.0 without modification.
- **NFR31:** ~~The legacy single-`API_KEY` auth mode (when `monetization_enabled=false`) must preserve every behavior of Comadre 1.6.2 exactly, including error envelopes, rate-limit values, and timing characteristics.~~ **RETIRED 2026-04-18.** The legacy single-`API_KEY` mode is removed in 2.0.0. NFR30 (request/response contract byte-identical to 1.6.2 on `/v1/audio/speech` + `/health`) stands. Auth-envelope byte-identity is no longer meaningful because the auth mechanism itself changed (single bearer → registry-backed bearer); the 401/403 envelope **shape** (`error.{message,type,hint}`) is preserved, but the content of `message` and `hint` reflects the new auth path.
- **NFR32:** Ansible playbooks must remain idempotent: running `bootstrap.yml` or `update.yml` multiple times must not re-issue keys, re-provision the database, or trigger spurious restarts.
- **NFR33:** The `comadre-keys` CLI must be backward-compatible within a major version: CLI invocations that worked on 2.0.0 must continue to work on every 2.x release.

### Compliance

- **NFR34:** LGPD data-subject access requests (Art. 18, II and V) must be fulfillable in under 15 days using the `export-customer` command, with the operator responsible for delivery to the data subject.
- **NFR35:** LGPD right-to-deletion requests (Art. 18, VI) must be fulfillable in under 15 days using the `delete-customer --hard` command; the command completes in under 1 second for any single customer regardless of database size.
- **NFR36:** LGPD breach notification (Art. 48): a runbook in `docs/monetization.md` must document the operator's notification duty and provide a template notification letter compliant with ANPD requirements.
- **NFR37:** Consumer-protection (CDC) compliance: the suspended-but-not-deleted key contract (FR19) guarantees that a non-paying customer's historical data is not destroyed, preventing disproportionate loss on reactivation.
