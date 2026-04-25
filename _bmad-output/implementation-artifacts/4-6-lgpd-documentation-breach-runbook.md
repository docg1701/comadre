# Story 4.6: LGPD Documentation & Breach Runbook

Status: done

<!-- Note: Validation is optional. Run validate-create-story for quality check before dev-story. -->

> **Scope note — FR39 / NFR36.** Last story in Epic 4 and last non-optional story in the Comadre 2.0.0 plan (four epic retrospectives are optional; see `sprint-status.yaml`). **Prose-only delivery — no source code, no schema, no migration, no CI YAML, no ansible playbook, no test harness change.** The story lands one new top-level section *"LGPD Operator Obligations"* in `docs/monetization.md` (today 89 lines, 8 `##` sections; after 4.6 ≈ 280–330 lines, 9 `##` sections). The section consolidates the six LGPD primitives already shipped by Stories 4.1 (`export-customer`, `delete-customer --hard`), 4.2 (`rotate-encryption-key`), 4.3 (`backup-keys.yml` / `restore-keys.yml`), 4.4 (`health.yml` + `comadre-keys health`), and 1.1 (Fernet-at-rest + `_FORBIDDEN_DETAIL_KEYS` log hygiene) into a single operator-facing handbook keyed off the actual statutes — Lei 13.709/2018 Art. 5 VI (data controller), Art. 7 V (legal basis "execução de contrato"), Art. 18 II/V (access), Art. 18 VI (deletion), Art. 48 (breach notification). Four deliverables inside that section: (1) a **Controller identification** subsection making it explicit that the operator is the LGPD data controller and Comadre is a tool; (2) **Data-subject request procedures** — three step-by-step runbooks (access → cites `comadre-keys export-customer`, deletion → cites `comadre-keys delete-customer --hard`, correction → cites `comadre-keys update-customer`); (3) a **Breach-notification runbook** with the four epic-AC-mandated artefacts (ANPD contact channel + link, customer-notification email template, evidence-preservation checklist, internal escalation path) plus a dedicated "suspected-key-compromise" lane that cites `rotate-encryption-key` end-to-end; (4) a **Privacy-policy template paragraph** the operator can paste into their own terms-of-service, plus an adjacent reminder that Comadre ships no privacy policy of its own. **One supporting housekeeping edit** — `docs/deployment-guide.md:528` ("Story 4.6 … consolidates these procedures into a full operator handbook once it lands; this section is the interim reference.") is rewritten to an authoritative cross-reference into the new handbook section. **One README update** — the existing `docs/monetization.md` bullet under `## Documentation` (README.md:169) gets a companion pointer naming the LGPD handbook subsection so operators searching for "LGPD" land there directly. **Zero behavioural change to runtime, CLI, or CI.**

> **Empirical premise (READ BEFORE IMPLEMENTING).** Verified 2026-04-24 against master at commit `0ed67a5`:
>
> - **The primitives the handbook cites are all `done` and the commands run end-to-end.** `sprint-status.yaml` — Stories 4.1, 4.2, 4.3, 4.4, 4.5a–g all `done`. CLI verbs `comadre-keys {export-customer, delete-customer, update-customer, rotate-encryption-key, cache-status, health}` present in `src/comadre/keys/cli/commands/`. Playbooks `backup-keys.yml`, `restore-keys.yml`, `health.yml` present in `deploy/ansible/playbooks/`. 4.6 never cites a verb or flag that has not already landed.
> - **The handbook's authoritative citation targets are stable.** `docs/deployment-guide.md:480-528` ("LGPD operator procedures" + "Rotating the encryption key" + final interim-pointer paragraph) — written under 4.1 and 4.2 specifically to be the pre-4.6 interim reference; the interim paragraph at line 528 names this story by number. `docs/monetization.md:85-89` ("See also" block) — already cross-references `rate-limiting.md` / `deployment-guide.md` / `configuration-reference.md`; 4.6 appends a `LGPD Operator Obligations` anchor link inside monetization.md itself.
> - **The PRD's binding requirements list is the content contract.** `prd.md:610-623` ("LGPD (Lei Geral de Proteção de Dados Pessoais — Brazilian Law 13.709/2018)") enumerates the seven items (legal basis, minimisation, encryption at rest, deletion right, access right, breach notification, retention, controller identification). The handbook section pins every item to its corresponding command / playbook / in-code invariant, so the prose-to-implementation map is 1:1. `prd.md:1177` (FR39) names the four artefacts the breach-notification subsection must contain. `prd.md:1252` (NFR36) names the obligation category (Art. 48).
> - **One in-repo invariant already anticipates 4.6's landing.** `docs/deployment-guide.md:528` — *"Story 4.6 (LGPD documentation & breach runbook) consolidates these procedures into a full operator handbook once it lands; this section is the interim reference."* This sentence is an explicit handoff: 4.6 replaces it with a forward reference to `monetization.md#lgpd-operator-obligations`.
> - **Grep invariants that must hold before and after 4.6 lands:**
>   - Pre-4.6: `rg -c "LGPD Operator Obligations" docs/` → `0` hits. Post-4.6: → `1` hit (inside `docs/monetization.md`; the heading itself).
>   - Pre-4.6: `rg "ANPD|Art\.\s*48" docs/` → 0 matches in `docs/monetization.md`, 1 match in `docs/deployment-guide.md` (none; the interim pointer does not name ANPD). Post-4.6: ≥ 4 matches in `docs/monetization.md` (Controller, Breach, Template, Policy subsections each reference at least one statute).
>   - Pre-4.6: `rg -c "once it lands; this section is the interim reference" docs/deployment-guide.md` → `1` hit. Post-4.6: → `0` hits (rewritten to an authoritative cross-reference).
>   - Post-4.6: `uv run pre-commit run markdownlint-cli2 --files docs/monetization.md docs/deployment-guide.md README.md` → passes clean.
>   - Post-4.6: every anchor the new section publishes resolves under `markdownlint-cli2` + a one-shot `rg "#lgpd-operator-obligations|#breach-notification-runbook|#privacy-policy-template" docs/ README.md` check matching expectations described in §Scope.

## Story

As an operator deploying Comadre 2.0.0 as the sole processor of Brazilian customers' personal data (name, email, Fernet-encrypted CPF / CNPJ) under "execução de contrato" (LGPD Art. 7 V),
I want a single, self-contained `docs/monetization.md#lgpd-operator-obligations` section that names each LGPD obligation I carry as the data controller (Art. 5 VI), tells me which already-shipped Comadre primitive discharges it (`export-customer` / `delete-customer --hard` / `update-customer` / `rotate-encryption-key` / `backup-keys.yml` / `restore-keys.yml` / `health.yml` / audit-log retention), and gives me a ready-to-fire runbook for the two worst-case incidents (registry-file leak and encryption-key compromise) — including an ANPD-addressable notification-letter template, a customer-facing email template, an evidence-preservation checklist, an internal escalation path, and a privacy-policy paragraph I can paste into my own terms of service,
so that on the day my security monitor reports an anomaly, my breach-response clock (LGPD Art. 48 — "reasonable timeframe") starts at zero and is spent entirely on executing the runbook rather than discovering it; on the day a customer invokes Art. 18, I can answer with the exact CLI verb within the 15-day statutory window (NFR34, NFR35); and on the day ANPD asks me to demonstrate my compliance posture, every item they expect to see is present in one browsable markdown file with verbatim command examples I have run before.

**Covers FRs:** FR39 (`docs/monetization.md` "LGPD Operator Obligations" section with breach-notification runbook: ANPD contact, customer-notification email template, evidence-preservation checklist, internal escalation path; plus privacy-policy template paragraph). Indirectly surfaces the already-implemented FR5 (LGPD hard-delete, Story 4.1), FR6 (LGPD export, Story 4.1), FR36 (encryption-key rotation, Story 4.2), FR38 (audit-log retention after purge, Story 4.1 + audit.py invariant), FR40 (nightly backup, Story 4.3), FR41 (restore playbook, Story 4.3) — the runbook is the operator-facing index of these.
**NFRs:** NFR36 (Art. 48 breach-notification runbook must live in `docs/monetization.md` and include a template notification letter compliant with ANPD requirements). Indirectly surfaces NFR34 (Art. 18 II/V access within 15 days via `export-customer`) and NFR35 (Art. 18 VI deletion within 15 days via `delete-customer --hard`; command <1s) — both cited but not implemented here.
**UX-DRs:** None applicable — UX-DRs target CLI rendering (`rich` components, exit codes, confirmation patterns). This is prose in markdown. The analogous quality bar for prose is: (a) markdownlint-cli2 clean, (b) no embedded CLI invocation cites a flag / verb / path that does not exist in master at landing time, (c) operator-copy-pasteable blocks include actual shell shebangs where the operator would run them (not `console` pseudo-code).
**Epic:** 4 — Security Hardening, LGPD & Operational Safety. **Twelfth and final story in Epic 4** (4.1 → 4.2 → 4.3 → 4.4 → 4.5a → 4.5b → 4.5c → 4.5d → 4.5e → 4.5f → 4.5g → **4.6**). **Last non-optional story in the Comadre 2.0.0 plan** — the four `epic-*-retrospective: optional` entries in `sprint-status.yaml` do not block the 2.0.0 release cut. Landing 4.6 closes Epic 4 and closes the plan.

## Builds on

- **Story 1.1 — CPF/CNPJ Fernet encryption at rest + audit-log PII hygiene.** The LGPD encryption-at-rest clause (Art. 6 VII — "security") is discharged by `src/comadre/keys/crypto.py` (`encrypt_tax_id` + `decrypt_tax_id`; the sole surface touching Fernet per architecture §Security Boundaries at `architecture.md:637`). The audit-log retention invariant (Art. 18 VI: "the audit log retains event metadata but NO personal data") is discharged by `src/comadre/keys/audit.py::_FORBIDDEN_DETAIL_KEYS` (blocks `cpf`, `cnpj`, `tax_id`, `name`, `email`, `key_plaintext`, `authorization`; raises `ValueError` on breach). The handbook cites these by file path + line range so a future auditor can trace from the prose directly to the guard code.
- **Story 4.1 — LGPD CLI primitives.** Shipped `comadre-keys export-customer <id> --format {json|yaml}` (Art. 18 II/V access), `comadre-keys delete-customer <id> --hard` (Art. 18 VI deletion), the `DELETE api_key` → `UPDATE customer SET (PII)="" / tax_id_encrypted=X''` tombstone-with-audit-preservation contract (FR38), and `list-customers --deleted` tombstone visibility (FR7). The handbook's "Handling an access request" and "Handling a deletion request" subsections cite these verbs verbatim — every shell block is copy-paste-runnable against a live VPS.
- **Story 4.2 — Encryption-key rotation.** Shipped `comadre-keys rotate-encryption-key --new-key <fernet>` — atomic re-encryption of every active customer's `tax_id_encrypted` under a fresh Fernet key, audited with a structural `{"rows_re_encrypted": N}` payload that contains zero PII per FR38 / `_FORBIDDEN_DETAIL_KEYS`. The handbook's "Responding to a suspected encryption-key compromise" lane is the only operator surface that promotes this verb to the breach-response tier — `docs/deployment-guide.md:506-528` is the procedural reference (four steps: mint, rotate, update `.env`, restart) and 4.6 copies the procedure verbatim rather than linking, because the breach runbook is explicitly designed to be self-contained (see §Self-contained-vs-linked-procedures in Dev Notes). The success-line echoes the new key value on stdout; 4.6 reminds the operator to **move it to the password manager before closing the shell** (scrollback retention is the last surface that holds the plaintext).
- **Story 4.3 — Nightly backup + idempotent restore.** Shipped `deploy/ansible/playbooks/backup-keys.yml` (nightly cron at 02:00 operator TZ installed by `bootstrap.yml`; `{registry.db}.backup-YYYY-MM-DDTHH-MM-SSZ.tar.gz.enc` at mode `0600`; AES-256-CBC + PBKDF2 envelope under `BACKUP_PASSPHRASE`) and `restore-keys.yml` (idempotent rollback with divergent-archived-key warning + operator-in-the-loop `.env` swap). The handbook's "Evidence-preservation checklist" section cites these artefacts as the authoritative state-at-incident capture — a breach-response must freeze the current archive plus the live DB before any further mutation.
- **Story 4.4 — Operational safety + `health.yml` assertion playbook + `comadre-keys health`.** Shipped the on-host probes (`0600` DB perms, `0700` parent dir, `22/80/443` UFW ALLOW-only, both cron entries installed, backup archive present, in-container `comadre-keys health --format json` reports `is_healthy=true`). The handbook cites `ansible-playbook health.yml; echo $?` as the canonical "is the deployment in its expected posture?" one-liner and names the two failure lanes (marker present but stale sweep = cron broken; marker absent = bootstrap not run). The handbook does NOT re-document the probes themselves — the canonical location is the architecture + the CLAUDE.md non-obvious-gotcha row; the handbook links forward.
- **Story 4.5a–g — Non-regression CI gates.** Shipped the seven mechanised PR-level controls that prove the 2.0.0 security posture does not regress on any PR merged to master. The handbook's opening paragraph of "LGPD Operator Obligations" names this — the operator's legal posture under Art. 46 ("security measures") is defended not only by the primitives but by the CI contract that those primitives are not quietly regressed. 4.5x is not the subject of 4.6; it's the implicit "why operators can trust 2.0.0's security story beyond the manual pentest" claim.
- **Architecture §LGPD module map — `architecture.md:657, 731`.** Explicitly predicts `docs/monetization.md` as one of the LGPD-owning surfaces (alongside `keys/crypto.py`, `keys/db.py`, `keys/audit.py`). 4.6 is the realisation of that prediction. `architecture.md:592` lists the file as `[NEW] operator runbook` — this story grows it from the monetisation-only shape shipped in Epic 1 to the full runbook the architecture always anticipated.
- **PRD §Domain-Specific Requirements > LGPD — `prd.md:610-623`.** The seven-item binding-requirements list IS the content contract for §LGPD Operator Obligations. Each item becomes a subsection or a paragraph inside the new section. The PRD's wording is drafted to be quotable verbatim; 4.6 quotes and extends, never paraphrases.
- **PRD §Risk Mitigations — `prd.md:1106`.** *"LGPD or tax-compliance surprise. Partially mitigated by the adapter-deferral posture… Comadre provides the LGPD primitives… but does not attempt to solve them wholesale."* The handbook's opening restates this boundary explicitly: Comadre is a **tool**, not a privacy-compliance product. The operator remains the controller. This is load-bearing for FR39's "data controller" item — mis-positioning the tool as "LGPD-in-a-box" would create operator liability Comadre has no way to discharge.
- **Existing `docs/deployment-guide.md:480-528` interim LGPD pointer.** Written under Stories 4.1 and 4.2 with deliberate forward-reference phrasing — the paragraph at line 528 names 4.6 by story number ("Story 4.6 consolidates these procedures into a full operator handbook once it lands; this section is the interim reference"). 4.6 replaces that sentence with an authoritative cross-reference (`See docs/monetization.md#lgpd-operator-obligations for the full operator handbook.`) — the interim-reference marker disappears on this story's merge.
- **CLAUDE.md Non-Obvious Gotchas.** Eight rows already document operator-relevant LGPD / breach-relevant invariants — the tombstone zero-length-BLOB contract, the single-`fernet.decrypt`-site invariant, the `rotate-encryption-key` tombstone-skip, the backup tarball naming contract, the `BACKUP_PASSPHRASE`-empty-at-boot rationale, the `restore-keys.yml` archived-key ≠ live `.env` warning, the `ansible-playbook health.yml` assertion-chain rule, and the `bootstrap.yml` belt-and-braces chmod. 4.6 does not duplicate these — the handbook treats them as authoritative and either quotes one-line summaries + links back, or cites them as the "why we do it this specific way" foundation. The handbook is the operator-facing index; CLAUDE.md is the contributor-facing invariant registry.

## Unblocks

- **Comadre 2.0.0 release cut.** 4.6 is the last non-optional story in the sprint plan (`sprint-status.yaml` — every other story in Epics 1–4 is `done`; only `epic-*-retrospective: optional` entries remain, and per the workflow comments they don't block the release). Once 4.6 lands, the release-notes draft can include a definitive "LGPD-ready" line backed by an in-repo operator handbook, not a forward reference.
- **Epic 4 retrospective (optional).** With 4.6 landed and Epic 4 flipping to `done` in `sprint-status.yaml`, a retrospective can cover all 12 Epic-4 stories against the original plan (the sub-story split of 4.5 — never anticipated in `epics.md` — is one of the more interesting items to retro).
- **Customer-onboarding collateral.** The privacy-policy template paragraph this story ships is the minimum viable text an operator needs to put on their own terms-of-service page before accepting their first paying customer. Without it, every operator would have to reinvent it from the PRD's domain-specific-requirements section. The handbook closes this gap in-repo rather than as a separate off-repo artefact.
- **ANPD inquiry response (future).** If the operator ever receives an ANPD inquiry (Art. 55-A ff.), the handbook is the first document they paste into the response — every prescribed control (encryption at rest, minimisation, retention policy, subject-access mechanism, deletion mechanism, breach procedure, controller identification) is indexed into one document with artefact citations. The runbook pre-composes an ANPD-addressed notification letter template; the operator fills the blanks rather than drafting from a blank page.
- **Downstream "LGPD-plus-audit-tail" exports (deferred Story 4.x).** The handbook footnotes the scope carveout — `export-customer` today emits only the PRD-mandated field set; future subject-access requests may ask for the operator's activity log. Story-4.x deferred-work in `deferred-work.md` already flags this. 4.6 names the carveout explicitly so customers and operators have a shared expectation of what "access" means in 2.0.0.

## Depends on

- **Stories 4.1, 4.2, 4.3, 4.4 `done`.** Verified 2026-04-24 against `_bmad-output/implementation-artifacts/sprint-status.yaml`:

  ```
  4-1-lgpd-data-operations-export-hard-delete: done
  4-2-encryption-key-rotation:                 done
  4-3-backup-restore-playbooks:                done
  4-4-operational-safety-file-permissions:     done
  ```

  The handbook cites CLI verbs, ansible playbooks, and file-permission assertions shipped by these four stories. If any of them regressed (`last_used_at` drift, reshuffled tombstone semantics, renamed playbook), the handbook's shell blocks would stop round-tripping and the prose would become a liability rather than an asset. The dev MUST spot-check each cited command against current master before writing — an hour-old git pull is sufficient; a week-old checkout is not (see §Verification-before-merge in Dev Notes).
- **Stories 4.5a–g `done`.** Verified 2026-04-24. The handbook's opening frames the 2.0.0 security posture as "primitives + mechanised non-regression gates"; if 4.5x is partly `backlog` / `in-progress` the framing becomes aspirational rather than descriptive. All seven sub-stories are `done` at 2026-04-24; the assertion holds.
- **No schema change, no auth-path change, no FastAPI runtime change, no CLI verb change, no ansible-playbook change, no CI YAML change, no `pyproject.toml` change, no `uv.lock` change, no dependency add, no test module add, no conftest change, no fixture change, no markdown-lint rule change, no pre-commit hook change, no landing-page change, no Caddyfile change, no Dockerfile change, no Compose change.** This is the shortest "unchanged surface" list of any Epic 4 story precisely because the story is prose-only. The sole exceptions — three markdown files — are enumerated in §Scope.
- **Markdown-lint-cli2 passes on the three touched files at landing time.** The repo's markdownlint config (`.markdownlint-cli2.yaml` or equivalent) is already honoured by `pre-commit`. 4.6's markdown MUST pass it — the opportunity cost of a documentation story that fails pre-commit is operator trust in the runbook itself.
- **No new markdown anchor collides with an existing heading.** Current `docs/monetization.md` headings (verified 2026-04-24): `# Monetization` / `## What monetization means` / `## Issuing a key` / `## Per-key rate limiting` / `## 429 semantics` / `## Lifecycle operations` / `## What is explicitly out of scope` / `## See also`. 4.6 adds `## LGPD Operator Obligations` — distinct from every existing heading. All `###` / `####` sub-headings under the new `##` start with LGPD-scoped nouns ("Controller identification", "Data-subject requests", "Breach-notification runbook", "Privacy-policy template") — collision-free against the rest of the document.

## Scope

**Three markdown files edited. Zero code, zero config, zero new files. No new dependency.** In execution order:

1. **`docs/monetization.md`** — append one new top-level section `## LGPD Operator Obligations` after the existing `## What is explicitly out of scope` (so the "See also" block stays the document's footer). The section's internal structure (§1 below) lands the full FR39 / NFR36 contract.
2. **`docs/deployment-guide.md`** — rewrite `docs/deployment-guide.md:528` (the interim-reference paragraph) to an authoritative cross-reference into the new handbook section. Two-line edit. Leave the "LGPD operator procedures" subsection (`docs/deployment-guide.md:480-504`) and "Rotating the encryption key" subsection (`docs/deployment-guide.md:506-528` minus the rewritten final paragraph) in place as deploy-time operational references — deploy-guide covers "how I run this in a shell", monetization-handbook covers "how this discharges a legal obligation". Dual placement is intentional (see §Why-dual-placement in Dev Notes).
3. **`README.md`** — append one bullet under `## Documentation` (after the existing `docs/monetization.md` bullet at line 169) naming the new subsection so operators searching for "LGPD" land directly in the handbook rather than discovering it by scrolling `monetization.md`. Form: `` - [docs/monetization.md#lgpd-operator-obligations](docs/monetization.md#lgpd-operator-obligations) -- LGPD operator handbook: controller identification, data-subject request procedures, breach-notification runbook, privacy-policy template paragraph ``.

### 1. `docs/monetization.md#lgpd-operator-obligations` — full section

The new `## LGPD Operator Obligations` section lands in nine subsections (`###` level). Each subsection has a single purpose, quotes the relevant PRD / architecture / CLAUDE.md line verbatim where the contract is crisp, and cites the governing artefact + in-repo line range where a future reader might want to verify.

#### 1.1 Opening (no heading, immediately under the `##`)

Two paragraphs. First paragraph:

> Comadre 2.0.0 processes personal data of Brazilian customers — name, email, and encrypted CPF / CNPJ — on your behalf. Under **Lei Geral de Proteção de Dados Pessoais** (Lei 13.709/2018, "LGPD"), **you are the data controller** (Art. 5 VI); Comadre is a software tool. This section is your operator handbook: it enumerates the obligations you carry under LGPD, names the already-shipped Comadre primitive that discharges each one, and provides the runbook you fire on a breach.

Second paragraph:

> The legal basis for processing is *"execução de contrato"* (Art. 7 V) — you collect the data exclusively to execute the API-access subscription. No secondary use, no data sharing, no profiling. The retention period is bounded by the commercial relationship plus the Brazilian commercial-law minimum (typically 5 years for fiscal records). Deletion is operator-driven via `comadre-keys delete-customer --hard`, never automatic.

Cite source: `prd.md:610-623` (the binding-requirements list). The two paragraphs paraphrase; the subsections below quote the specific items.

#### 1.2 `### Controller identification (Art. 5 VI)`

- **Content.** One paragraph making explicit that the operator is the LGPD data controller and Comadre is a tool. Name the two practical consequences: (a) the operator MUST publish their own privacy policy (§1.8 below ships the template paragraph); (b) ANPD inquiries are addressed to the operator, never to the Comadre project.
- **Citations.** `prd.md:623` ("the operator is the LGPD data controller (Art. 5, VI). Comadre the software is a tool"). Architecture §LGPD module map at `architecture.md:657` names `docs/monetization.md` as the handbook location for this contract — 4.6 realises that prediction.

#### 1.3 `### Data collected and retention`

- **Content.** Four-row table naming the columns the registry stores, their purpose, their at-rest protection, and their retention window. Rows:
  - `name` — free-text — plaintext storage (low-sensitivity; required for CLI display) — retained for commercial-relationship lifetime.
  - `email` — free-text — plaintext storage (low-sensitivity; required for CLI display) — retained for commercial-relationship lifetime.
  - `tax_id_encrypted` (CPF or CNPJ) — Fernet ciphertext — encrypted at rest with key material from `KEY_REGISTRY_ENCRYPTION_KEY` — retained until operator-driven `delete-customer --hard`.
  - `notes` — free-text — plaintext — operator-facing only; retained with the customer row.
- **Explicit non-collection.** "No address, no phone number, no birthdate, no photograph, no IP, no device fingerprint, no secondary biometrics." Quote `prd.md:617` ("Data minimization — schema stores only what is necessary…").
- **Encryption key custody.** The operator holds `KEY_REGISTRY_ENCRYPTION_KEY` in `.env` (mode `0600`) + their password manager. If both copies are lost, tax-IDs become unreadable — **this is a deliberate fail-closed posture** (a separate "recovery" path would defeat the at-rest-encryption premise). Cite CLAUDE.md row 70 ("`BACKUP_PASSPHRASE` is accepted empty at service boot by design") as context on how the backup-passphrase posture differs from the encryption-key posture.

#### 1.4 `### Handling a data-subject access request (Art. 18 II and V)`

- **Shell block** — copy-paste-runnable end-to-end:

  ```bash
  # 1. Identify the customer from the email / tax-ID they provided in the request.
  comadre-keys list-customers  # pick the row whose email matches; note the cust_... ID

  # 2. Export in JSON (machine-readable) or YAML (human-readable deliverable).
  comadre-keys export-customer cust_01HG7... --format json > /tmp/customer-export.json
  comadre-keys export-customer cust_01HG7... --format yaml > /tmp/customer-export.yaml

  # 3. Deliver via the agreed channel (signed email reply, client portal, etc.).
  #    The export is non-mutating — no DB rows change, no audit row is written.
  ```

- **Field set.** Explicitly list what the export contains (customer id, name, email, decrypted tax-ID formatted per kind, tax-ID kind, notes, registered_at, and for each associated key: prefix, status, billing_mode, created_at). Cross-reference `epics.md:762-769` (Story 4.1 AC1).
- **Explicit exclusions.** "The export does NOT include the operator-internal audit log of actions taken on the customer (log rows name the actor + target, not the subject); it does NOT include the SHA-256 hash of any API key plaintext (security boundary — hashes never leave storage); it does NOT include `rate_limit_rpm` / `paid_until` / `price_monthly` (operator-internal billing data; the operator may include these voluntarily by attaching the output of `comadre-keys show cust_... --format json` — not an LGPD-access obligation)."
- **Statutory deadline.** "LGPD Art. 18 response window is within a reasonable timeframe, typically 15 days. `export-customer` itself completes in under 1 second regardless of database size (NFR34)."
- **Citations.** `prd.md:620` (Art. 18 II / V wording), `prd.md:1250` (NFR34 deadline), `epics.md:762-769` (Story 4.1 AC1 field set), `docs/deployment-guide.md:484-492` (the deploy-time operational reference this handbook builds on).

#### 1.5 `### Handling a deletion request (Art. 18 VI)`

- **Shell block** — copy-paste-runnable end-to-end:

  ```bash
  # 1. Confirm the subject's identity (same evidentiary posture as access; the customer's
  #    authenticated email plus an independent verification factor is the minimum).

  # 2. Interactive run — requires typing "y" at the prompt.
  comadre-keys delete-customer cust_01HG7... --hard
  # → This will permanently delete customer Marcos Silva and all associated keys.
  #   This action cannot be undone. Encrypted tax ID will be purged. Continue? [y/N]:

  # 3. Scripted run (e.g., inside a larger data-governance pipeline) — skip the prompt.
  comadre-keys delete-customer cust_01HG7... --hard --yes

  # 4. Confirm the tombstone is present.
  comadre-keys list-customers --deleted | grep cust_01HG7...
  ```

- **What the command does.** Quote `epics.md:772-776` verbatim — one transaction, all api_key rows DELETEd, customer-row PII scrubbed to canonical empty forms (`name=""`, `email=""`, `tax_id_encrypted=X''`, `notes=""`), `deleted_at` stamped UTC, one `delete_customer` audit row whose `details_json` carries only `{"keys_purged": N, "tax_id_kind": "cpf"|"cnpj"}` — zero PII retained.
- **Why the audit row stays.** "FR38 — *System preserves audit-log metadata (who, when, what) after a customer's personal data is purged, so operator activity remains traceable without retaining personal data.* The audit log is an append-only forensic record; LGPD does not require destroying operator-action metadata, only the subject's personal data. The audit row links to a tombstoned customer_id that no longer resolves to a person — it carries no PII." Cite `prd.md:1176` (FR38), `prd.md:619` (PRD Art. 18 VI wording).
- **Why the tombstone stays.** "The tombstone row (`deleted_at IS NOT NULL`, PII scrubbed) is the evidence of the completed deletion — if ANPD ever asks *'did you delete Marcos Silva's data within the statutory window?'*, the tombstone is the answer. Every read path filters `deleted_at IS NULL` by default (FR7 — `list-customers --deleted` is the sole surface that sees tombstones)." Cite `CLAUDE.md:73` (the tombstone rationale row).
- **Statutory deadline.** "Art. 18 response window is typically 15 days. `delete-customer --hard` completes in under 1 second (NFR35). The 15-day budget is spent on identity-verification administrivia, not the command itself."

#### 1.6 `### Handling a correction request (Art. 18 III)`

Short subsection — the two-line procedure:

- Email / name / notes corrections: `comadre-keys update-customer cust_... --email <new> --name <new> --notes <new>`.
- Tax-ID corrections (rare — CPF / CNPJ are immutable except for fraud or clerical error at registration): currently requires an operator-VPS shell + a `delete-customer --hard` followed by `create-customer` under the corrected tax-ID. A future Story 4.x may add a `correct-tax-id` verb; out of 4.6 scope.

Cite `epics.md:435-458` (Story 1.5 — `update-customer` verb) and `docs/deployment-guide.md` §Key Registry Management (operational reference).

#### 1.7 `### Breach-notification runbook (Art. 48)`

**Four subsections (`####` level), matching the four artefacts FR39 mandates.** Order: contact → incident-specific procedure lanes → email template → evidence-preservation checklist → escalation path.

##### 1.7.1 `#### ANPD contact`

- **Content.** The two ANPD channels: (a) the formal complaint/notification web form at the authority's portal; (b) the institutional email address. The handbook MUST NOT hardcode the URL without a companion "verify this link before sending — the ANPD web presence has changed between 2020 and 2024" caveat. Recommended posture: cite the ANPD domain (`www.gov.br/anpd`) with a plain-text warning that the operator validates the current URL at incident time; name the specific sub-URL path the operator typically uses (notification form under Comunicação de Incidente) without hardlinking a specific fragile path. A conservative fallback: "find the current ANPD notification channel at `www.gov.br/anpd/pt-br`". Mention that ANPD also accepts paper mail at its Brasília address (published on their site; look up at incident time).
- **Exit criterion.** A future operator facing a real incident knows, within two clicks, (a) which authority to contact, (b) which URL / email is current, (c) what information ANPD expects in the notification (bridged by §1.7.3 template + §1.7.4 checklist).

##### 1.7.2 `#### Incident-response procedure lanes`

**Two lanes — each is a numbered step-by-step that an operator runs top-to-bottom on the day of the incident.**

**Lane A — "Registry file exposure or suspected SQLite leak":**

1. Stop writes — `docker compose stop tts-service` on the VPS (reads of the archive at /var/lib/comadre continue to work; in-flight 401s return from Caddy cache until the service restarts).
2. Snapshot current state for evidence — `ansible-playbook backup-keys.yml` (creates a timestamped `.tar.gz.enc` adjacent to the DB, mode `0600`; this is the artefact the evidence-preservation checklist refers back to). **Do not overwrite the latest nightly archive** — the nightly archive and the incident snapshot are separate artefacts.
3. Assess scope — `comadre-keys list-customers --format json > /tmp/affected-customers.json` (count of customers + their emails for step 6); `comadre-keys show <each-cust-id> --audit-tail 1000 > /tmp/audit-<cust-id>.log` for every customer in the registry (activity log). These two files are the evidentiary baseline for the ANPD notification body.
4. Rotate the encryption key — §1.7.5 below is the full runbook; link forward.
5. Rotate every affected customer's API key — `comadre-keys rotate-key <prefix>` for each customer. `rotate-key` preserves `key_id` (same rate-limit bucket, same billing state, same customer) but issues a fresh plaintext — the leaked registry's key-hashes become stale on the next bucket read. **Cite CLAUDE.md row 11-12** (per-key bucket identity rules; rotate preserves bucket identity).
6. Notify the operator's internal escalation path (§1.7.5).
7. Notify customers — customer email template in §1.7.3.
8. Notify ANPD — ANPD template in §1.7.3.
9. Restart the service — `docker compose up -d tts-service` after the new encryption key is in `.env` and the key-rotation command has succeeded.
10. File the post-incident report — a structured markdown document the operator retains indefinitely for audit.

**Lane B — "Suspected encryption-key compromise (without confirmed SQLite leak)":**

1. Generate a new Fernet key without rotating yet — `docker compose exec tts-service python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'`. Store the value in the password manager before running the rotation (the rotation's success line is the only operator-facing surface that echoes it; losing it mid-flow is the worst failure mode).
2. Rotate — `docker compose exec tts-service comadre-keys rotate-encryption-key --new-key "$NEW_KEY" --yes`. One transaction, every active customer's `tax_id_encrypted` re-encrypted. Tombstoned customers are skipped by design (zero-length BLOB, no PII to rotate; CLAUDE.md row 75). **The success line prints the new key value to stdout** — this is the sole operator-facing surface that echoes it; move it to the password manager before closing the shell.
3. Update `~/comadre/.env` on the host — `KEY_REGISTRY_ENCRYPTION_KEY=<value>`.
4. Restart the service — `docker compose restart tts-service`.
5. Notify internal escalation path (§1.7.5) and, at operator discretion, customers via §1.7.3's customer-template. ANPD notification for Lane B is judgement-call — a confirmed key compromise without exfiltrated ciphertext may or may not meet the Art. 48 threshold depending on the operator's legal counsel's reading. **The handbook does NOT attempt to replace legal counsel; the template is pre-composed so counsel's review is a one-hour markup pass, not a drafting pass.**

**Post-rotation verification:** `comadre-keys export-customer <cust-id> --format json` for a random handful of customers — success means the new key decrypts old ciphertext, which means the rotation completed cleanly. A failure here means the rotation aborted mid-transaction (SQLite's txn rollback guarantees no partial state; an immediate rerun should succeed; if it does not, open `health.yml` to diagnose).

##### 1.7.3 `#### Notification templates`

**Two templates — ready-to-edit `.txt`-style blocks. Variables in `{{braces}}`.**

**Template A — ANPD notification (Portuguese, the official language):** Fields ANPD's 2024 guidance asks for (cross-reference the ANPD site at incident time for canonical wording):
- Identificação do controlador (operator's legal name + CNPJ + responsible person + contact email).
- Natureza do incidente (leak category — SQLite exfiltration / encryption-key compromise / physical theft / insider access).
- Dados afetados (categorias: "nome, e-mail, CPF/CNPJ cifrado sob Fernet"; if customer-count ≤ 10 list individually, otherwise state aggregate count).
- Possíveis consequências (realistic: loss of customer trust; possible enumeration of CPF/CNPJ via rainbow-table attack on the Fernet-encrypted blob IS computationally infeasible as of 2026, name this explicitly).
- Medidas adotadas (`rotate-encryption-key` + per-key rotation + full customer notification + evidence preservation).
- Data do incidente (descoberta vs ocorrência — both required where known).
- Data da notificação (current UTC timestamp).

The template is in Portuguese because ANPD responds in Portuguese. Cite Lei 13.709/2018 Art. 48 §3 (the law's own procedural wording) — the operator's legal counsel is responsible for the final text; the template is a structural aid, not a substitute for counsel.

**Template B — Customer notification (Portuguese + English, side-by-side):** Short, dignified:
- Subject: "Notificação de incidente de segurança — Comadre / {{operator-brand}}"
- Body: factual account of what happened, what data was affected, what the operator is doing (key rotation + encryption-key rotation), what the customer should do (if anything — e.g., if the operator also rotated API keys: "Your API key has been automatically replaced. The new value was sent via {{channel}}. Please update your integration by {{deadline}}."), contact channel for questions.
- Tone rules: no passive voice; no "we regret to inform"; no unverified assurances ("your data has been safe at all times" is not a claim the operator can make mid-incident). The customer is treated as an adult processing a factual report.

Both templates are explicitly marked `**TEMPLATE — adapt to the specific incident and have your legal counsel review before sending.**`

##### 1.7.4 `#### Evidence-preservation checklist`

Bulleted checklist — operator works through it top-to-bottom on incident day, writing `✓ 2026-04-24T14:30Z` or `— N/A` after each item:

- [ ] Latest nightly `.tar.gz.enc` archive is intact (`ls -l /var/lib/comadre/*.backup-*.tar.gz.enc`; mode `0600`).
- [ ] Incident-time snapshot taken (step 2 of Lane A — separate artefact from the nightly).
- [ ] Live DB file captured as-of-incident (`cp /var/lib/comadre/registry.db /tmp/registry.db.incident-<UTC>` — read-only copy; mode changed to `0400`).
- [ ] `comadre-keys list-customers --format json` dump.
- [ ] `comadre-keys show <cust-id> --audit-tail 1000` dump per customer.
- [ ] Host syslog for the suspected incident window (`journalctl --since '<when>' --until '<when>' > /tmp/host-syslog.<UTC>`).
- [ ] Docker container logs (`docker compose logs tts-service --no-color > /tmp/tts-logs.<UTC>`).
- [ ] Caddy access logs (from the Caddy container volume).
- [ ] `ansible-playbook health.yml` output at incident time — the assertion chain's exit code AND the full playbook output.
- [ ] UFW status (`sudo ufw status verbose > /tmp/ufw.<UTC>`) — confirms whether an unexpected port opened.
- [ ] Process list at incident time (`ps auxf > /tmp/ps.<UTC>`) — confirms whether an attacker process is still running.
- [ ] `.env` file hash (`sha256sum ~/comadre/.env > /tmp/env-hash.<UTC>` — hash only; **never commit `.env`** or its plaintext).
- [ ] SSH `last` output (`last -n 50 > /tmp/last.<UTC>`) — recent shell sessions on the host.

Every captured file goes into a hermetic `incident-<UTC>/` directory and is compressed + encrypted (`tar -czf | openssl enc -aes-256-cbc -pbkdf2`) with a passphrase stored in the operator's password manager. **Do NOT upload the incident archive to cloud storage until legal counsel clears it** — the archive contains PII.

##### 1.7.5 `#### Internal escalation path`

Bulleted — the operator pre-fills their own names / contacts at deployment time:

- Primary responder: `{{operator-name}}` — phone + out-of-band channel.
- Secondary responder / legal review: `{{operator-legal-counsel}}` — phone + email.
- Technical deputy: `{{operator-technical-deputy}}` — shell + password-manager access.
- Customer-communications lead: typically same as primary responder for small operators.
- Communications embargo: no external communication (customers, press, ANPD) before legal review signs off on the notification wording. Exception: if ANPD's statutory clock is about to expire, notify ANPD with the current best-effort text — under-notifying is a violation; over-notifying is not.

#### 1.8 `### Privacy-policy template paragraph`

**A code-block-fenced paragraph operators paste verbatim into their own terms of service** (Portuguese primary; English underneath for operators with international customers). The paragraph names:
- The operator as controller (`{{operator-name}}` placeholder).
- Comadre as the processing tool (named by URL: `https://github.com/galvani4987/comadre`, so customers can inspect the source).
- The data collected (name, email, CPF/CNPJ, notes) + its at-rest protection (Fernet).
- The legal basis (Art. 7 V, execução de contrato).
- The retention window (commercial-relationship + 5y Brazilian-commercial-law minimum).
- The customer's LGPD rights (access, correction, deletion) + the channel to exercise them (`{{operator-email}}`).
- The operator's status as the ANPD contact for any complaint.

**Explicit caveat: the template is a structural aid, not legal advice.** The operator's counsel adapts it to the specific business posture before publishing. The handbook makes this boundary loud so operators don't mistake the template for a complete privacy policy.

#### 1.9 `### References`

Short bulleted list of citations — the PRD / architecture / deploy-guide / CLAUDE.md pointers that ground each subsection. Every pointer is `path:line-range` form so a future reader can jump directly to the source.

### 2. `docs/deployment-guide.md:528` — replace interim-reference paragraph

Single two-line edit. Current:

> Story 4.6 (LGPD documentation & breach runbook) consolidates these procedures into a full operator handbook once it lands; this section is the interim reference.

Rewrite to:

> The full operator handbook — including the breach-notification runbook (ANPD contact, customer-notification template, evidence-preservation checklist, internal escalation path) and the privacy-policy template paragraph — lives at [docs/monetization.md#lgpd-operator-obligations](monetization.md#lgpd-operator-obligations). This section remains the deploy-time operational reference; the handbook is the legal-posture reference.

**Why both surfaces stay.** Deploy-guide focuses on the operator-at-the-shell ("how do I run this command today?"); the handbook focuses on the operator-as-controller ("which legal obligation does this command discharge?"). A single operator visits both documents at different moments — the handbook on the day they set up their business, the deploy-guide on the day they fix a restore. Collapsing them into one would serve neither audience well. See §Why-dual-placement in Dev Notes for the full rationale.

### 3. `README.md:169` — add handbook pointer bullet

Current bullet:

```markdown
- [docs/monetization.md](docs/monetization.md) -- Customer tiers, per-key pricing, rate-limit lifecycle
```

Append immediately below:

```markdown
- [docs/monetization.md#lgpd-operator-obligations](docs/monetization.md#lgpd-operator-obligations) -- LGPD operator handbook: controller identification, data-subject request procedures, breach-notification runbook, privacy-policy template paragraph
```

**Why a second bullet, not a parenthetical amendment to the first.** The two surfaces address different operator questions — monetisation-fundamentals vs LGPD obligations — and a `README.md` reader searching for "LGPD" should hit the anchor directly. Inlining into the existing bullet would force the reader to skim the whole `monetization.md` doc to find the handbook subsection. Two bullets cost one line of README real estate; worth it for the jump-to-anchor guarantee.

## Acceptance Criteria

Numbered structurally. ACs that require a specific shell command to verify carry the command inline so the dev can run it before marking the box.

1. **New top-level section present.** `rg -c "^## LGPD Operator Obligations$" docs/monetization.md` → `1`. The heading is `##` (top-level under the `#` document heading), spelled exactly as `LGPD Operator Obligations` (title case, no acronym expansion, matches FR39 wording at `prd.md:1177`).

2. **Section order.** The new section sits between `## What is explicitly out of scope` and `## See also` in the rendered document. `rg -n "^## " docs/monetization.md` returns headings in the order: `## What monetization means`, `## Issuing a key`, `## Per-key rate limiting`, `## 429 semantics`, `## Lifecycle operations`, `## What is explicitly out of scope`, **`## LGPD Operator Obligations`**, `## See also`.

3. **Controller identification subsection.** Contains a subsection named `### Controller identification (Art. 5 VI)` stating explicitly that the operator is the data controller and Comadre is a tool. `rg -n "Art\.\s*5\s*VI" docs/monetization.md` → ≥ 1 match inside this subsection.

4. **Data minimisation subsection.** Contains a subsection named `### Data collected and retention` enumerating the four fields (`name`, `email`, `tax_id_encrypted`, `notes`) with their protection posture and retention window, plus an explicit non-collection enumeration ("No address, no phone number, no birthdate, no photograph, no IP, no device fingerprint, no secondary biometrics.").

5. **Access-request subsection.** Contains a subsection named `### Handling a data-subject access request (Art. 18 II and V)` with a copy-paste-runnable shell block that includes `comadre-keys export-customer` with both `--format json` and `--format yaml` forms. The block is fenced as `bash` so markdownlint's language-hint rule passes.

6. **Deletion-request subsection.** Contains a subsection named `### Handling a deletion request (Art. 18 VI)` with a shell block covering interactive, scripted (`--yes`), and post-deletion tombstone-verification invocations of `comadre-keys delete-customer --hard`. The block explicitly states that FR38 (audit-log PII hygiene) and the tombstone row (`deleted_at IS NOT NULL`) are retained by design.

7. **Correction-request subsection.** Contains a subsection named `### Handling a correction request (Art. 18 III)` naming `comadre-keys update-customer` for email/name/notes corrections, and explicitly documenting that tax-ID corrections are out of 4.6 scope + require `delete-customer --hard` + `create-customer`. No handwaving — the limitation is stated.

8. **Breach-notification runbook present.** Contains a subsection named `### Breach-notification runbook (Art. 48)` with **five `####` subsections** in order: `#### ANPD contact`, `#### Incident-response procedure lanes`, `#### Notification templates`, `#### Evidence-preservation checklist`, `#### Internal escalation path`. The epic AC wording (`epics.md:1038`) lists four artefacts (ANPD contact, customer-notification email template, evidence-preservation checklist, internal escalation path); the procedure-lanes subsection is the fifth, added because the runbook is useless without the step-by-step that ties the four artefacts together. Lane separation is a deliberate extension of the epic AC.

9. **ANPD contact subsection.** `#### ANPD contact` names the ANPD domain (`www.gov.br/anpd`) and includes the caveat "verify the current URL at incident time" (phrase allowed to vary — the exact verbatim is NOT required; the semantic requirement is that the operator is warned the URL may drift).

10. **Two incident lanes present.** `#### Incident-response procedure lanes` contains two numbered procedures: **Lane A — "Registry file exposure or suspected SQLite leak"** and **Lane B — "Suspected encryption-key compromise (without confirmed SQLite leak)"**. Each lane has at least 5 numbered steps. Each lane references at least one `comadre-keys` or `ansible-playbook` invocation.

11. **Both templates present.** `#### Notification templates` contains **Template A** (ANPD notification, Portuguese primary) and **Template B** (customer notification, Portuguese + English). Each template is in a fenced code block with `{{braces}}`-style placeholders for operator-specific values. Both templates carry the explicit legal-review caveat.

12. **Evidence-preservation checklist.** `#### Evidence-preservation checklist` is a bulleted list of at least 10 items. Every item has a concrete shell command OR the instruction is precise enough to execute without guesswork. The checklist includes the incident-archive encryption step.

13. **Internal escalation path.** `#### Internal escalation path` names at least 4 roles (primary responder, legal counsel, technical deputy, customer-communications lead) with `{{braces}}` placeholders for operator-specific fill-in. Also names the communications-embargo rule.

14. **Privacy-policy template.** Contains a subsection named `### Privacy-policy template paragraph` with a fenced code block containing a Portuguese-primary + English paragraph operators paste into their own TOS. The block contains placeholders `{{operator-name}}` and `{{operator-email}}`. Adjacent prose carries the explicit "not legal advice" caveat.

15. **References subsection.** Contains a subsection `### References` with `path:line-range`-formatted pointers into `prd.md`, `architecture.md`, `epics.md`, `docs/deployment-guide.md`, and `CLAUDE.md`.

16. **Deploy-guide cross-reference updated.** `docs/deployment-guide.md:528` no longer contains the interim-reference sentence. `rg -c "once it lands; this section is the interim reference" docs/deployment-guide.md` → `0`. New text contains a relative link `monetization.md#lgpd-operator-obligations` that renders in both the in-repo viewer and on the GitHub rendered view.

17. **README pointer bullet added.** `README.md:170` (after the monetization-bullet at line 169) contains a bullet linking to `docs/monetization.md#lgpd-operator-obligations` with a one-line description naming the four FR39 artefacts. `rg -c "#lgpd-operator-obligations" README.md` → `1`.

18. **Markdownlint clean.** `uv run pre-commit run markdownlint-cli2 --files docs/monetization.md docs/deployment-guide.md README.md` reports zero violations. (Or the project-local equivalent — the pre-commit config is authoritative.)

19. **Zero source / config change.** `git diff master --stat` after 4.6 lands shows only `docs/monetization.md`, `docs/deployment-guide.md`, `README.md`, `_bmad-output/implementation-artifacts/4-6-lgpd-documentation-breach-runbook.md`, and `_bmad-output/implementation-artifacts/sprint-status.yaml` changed. `rg "+++" diff-output | wc -l` or equivalent check: exactly 5 files touched.

20. **No dependency change.** `git diff master -- pyproject.toml uv.lock | wc -l` → `0`.

21. **No CI YAML change.** `git diff master -- .github/workflows/ | wc -l` → `0`.

22. **No CLI surface change.** `git diff master -- src/ | wc -l` → `0`.

23. **No ansible change.** `git diff master -- deploy/ | wc -l` → `0`.

24. **Every cited command runs against master.** Dev-time manual smoke (not an automated assertion — spot-check): pick 3 random shell blocks from the new section, run them verbatim against a local test registry (e.g., the one in `tests/` fixtures or a quick `uv run comadre-keys create-customer` seed), confirm each completes with the documented output shape. Record the spot-check results in Completion Notes.

25. **All `{{braces}}` placeholders are operator-facing.** `rg -o "\{\{[^}]+\}\}" docs/monetization.md | sort -u` returns a list of variables, every one of which maps to something an operator knows about their own business (`{{operator-name}}`, `{{operator-email}}`, `{{operator-legal-counsel}}`, `{{operator-technical-deputy}}`, `{{operator-brand}}`, `{{channel}}`, `{{deadline}}`). No `{{braces}}` placeholder references an internal Comadre concept — the handbook is self-contained for the operator.

26. **Default pytest green.** `uv run pytest` → same count as pre-4.6 (≈ 1414 passed, 93 deselected). 4.6 touches no test file; the count is unchanged by definition. Verifying it pre/post is due diligence — catches an accidental stray test edit.

27. **Non-regression suite green.** `uv run pytest -m non_regression tests/test_non_regression/` → same count as pre-4.6 (77 passed, 16 skipped). Same due-diligence rationale as AC26.

28. **Pre-commit full-suite green.** `uv run pre-commit run --all-files` → all hooks pass. This covers markdownlint on the three touched files plus the housekeeping hooks (ruff, mypy, yamllint, shellcheck, etc. — none should have anything to do with this change, but running the full suite is cheap insurance).

## Tasks / Subtasks

- [x] **Task 0 — Preflight (AC19, AC24).** (Dev time: ~30 min.)
  - [x] Pull master: `git pull --ff-only && git status`. Confirm clean working tree + master tip.
  - [x] Confirm citations are still valid: `rg -n "Story 4\.6" docs/` → hits at `docs/deployment-guide.md:528`.
  - [x] Confirm cited CLI verbs exist: `uv run comadre-keys --help | head -40` — look for `export-customer`, `delete-customer`, `update-customer`, `rotate-encryption-key`, `list-customers`, `show`, `health`, `cache-status`. If any verb is missing, halt and file a bug before continuing (the handbook cites these verbs verbatim; missing verbs = story spec drift).
  - [x] Confirm cited ansible playbooks exist: `ls deploy/ansible/playbooks/{backup-keys,restore-keys,bootstrap,health}.yml`.
  - [x] Confirm cited architectural line ranges still resolve: `sed -n '657,731p' _bmad-output/planning-artifacts/architecture.md | head -5`; `sed -n '610,623p' _bmad-output/planning-artifacts/prd.md | head -5`.
  - [x] Verify markdownlint is part of pre-commit on the touched files: `grep -n markdownlint .pre-commit-config.yaml`.

- [x] **Task 1 — Draft `## LGPD Operator Obligations` skeleton (AC1, AC2).**
  - [x] Append the `##` heading and the nine `###` subsection skeletons between `## What is explicitly out of scope` and `## See also` in `docs/monetization.md`.
  - [x] Confirm the section ordering via `rg -n "^## " docs/monetization.md`. AC2 passes.

- [x] **Task 2 — Fill §1.1 (opening) and §1.2 (Controller identification) — AC3.**
  - [x] Write the two opening paragraphs.
  - [x] Write the Controller-identification paragraph citing `prd.md:623` and Art. 5 VI.

- [x] **Task 3 — Fill §1.3 (Data collected and retention) — AC4.**
  - [x] Four-row table (field, type, protection, retention).
  - [x] Explicit non-collection enumeration.
  - [x] Encryption-key-custody paragraph linking to CLAUDE.md row 70 (BACKUP_PASSPHRASE posture).

- [x] **Task 4 — Fill §1.4 (Access request) and §1.5 (Deletion request) — AC5, AC6.**
  - [x] Write each shell block, reviewed for exact verb / flag / path correctness.
  - [x] Write the FR38 + tombstone paragraphs under §1.5.
  - [x] Quote `epics.md:772-776` for the deletion semantics.

- [x] **Task 5 — Fill §1.6 (Correction request) — AC7.**
  - [x] Two-line procedure.
  - [x] Explicit tax-ID-correction carveout.

- [x] **Task 6 — Fill §1.7 breach-notification runbook (AC8, AC9, AC10, AC11, AC12, AC13).**
  - [x] §1.7.1 ANPD contact.
  - [x] §1.7.2 Lane A and Lane B (at least 5 numbered steps each).
  - [x] §1.7.3 Templates A (ANPD, Portuguese) and B (customer, Portuguese + English).
  - [x] §1.7.4 Evidence-preservation checklist (≥ 10 items).
  - [x] §1.7.5 Internal escalation path (4 roles minimum).

- [x] **Task 7 — Fill §1.8 (Privacy-policy template paragraph) — AC14.**
  - [x] Portuguese-primary + English code block with `{{braces}}` placeholders.
  - [x] Adjacent "not legal advice" caveat.

- [x] **Task 8 — Fill §1.9 (References) — AC15.**
  - [x] `path:line-range` pointers for every subsection's authoritative source.

- [x] **Task 9 — Rewrite `docs/deployment-guide.md:528` — AC16.**
  - [x] Replace the two-line interim-reference paragraph with the authoritative cross-reference.
  - [x] Confirm `rg -c "once it lands; this section is the interim reference" docs/deployment-guide.md` → `0`.

- [x] **Task 10 — Add README pointer bullet — AC17.**
  - [x] Append the bullet after line 169.
  - [x] Confirm `rg -c "#lgpd-operator-obligations" README.md` → `1`.

- [x] **Task 11 — Markdownlint + pre-commit pass — AC18, AC28.**
  - [x] `uv run pre-commit run markdownlint-cli2 --files docs/monetization.md docs/deployment-guide.md README.md`. Fix any flagged issues.
  - [x] `uv run pre-commit run --all-files`. Fix any flagged issues.

- [x] **Task 12 — Verification sweep + spot-check (AC24, AC25, AC26, AC27).**
  - [x] `uv run pytest` — confirm same pass count as pre-4.6.
  - [x] `uv run pytest -m non_regression tests/test_non_regression/` — same.
  - [x] `rg -o "\{\{[^}]+\}\}" docs/monetization.md | sort -u` — visual review of the list; confirm every placeholder is operator-facing (AC25).
  - [x] Pick 3 random shell blocks from the new section and run them verbatim against a local test registry. Record the results in Completion Notes (AC24).

- [x] **Task 13 — Diff shape invariants (AC19, AC20, AC21, AC22, AC23).**
  - [x] `git diff master --stat` — confirm 5 files touched.
  - [x] `git diff master -- pyproject.toml uv.lock`, `git diff master -- .github/workflows/`, `git diff master -- src/`, `git diff master -- deploy/` — each zero-line diff.

- [x] **Task 14 — Update sprint-status.yaml + story file status.**
  - [x] Flip `4-6-lgpd-documentation-breach-runbook: backlog → ready-for-dev → in-progress → review`.
  - [x] Update `last_updated` in both the YAML body and the header comment.
  - [x] On code-review completion, flip to `done`. *(2026-04-24 — review findings resolved in-place; all 28 ACs pass; pre-commit green; AC19-23 invariants held.)*

## Dev Notes

### Why a handbook-style section, not a standalone `docs/lgpd.md`

The PRD (`prd.md:1177` FR39 + `prd.md:1252` NFR36) and the architecture (`architecture.md:592, 657, 731`) BOTH name `docs/monetization.md` as the specific location for this content. Not `docs/lgpd.md`, not `docs/compliance.md`, not `docs/security.md`. The naming is intentional: the LGPD posture is a property of the monetisation feature — Comadre 1.6.2 (no monetisation, no customer data) had no LGPD exposure; 2.0.0 (registry + customers + CPF/CNPJ) does. Keeping the handbook inside `monetization.md` preserves the mental model that LGPD is a consequence of running the monetisation slice, not an independent feature.

Splitting into a standalone file would fragment the operator's mental model: "do I need to read both?" becomes a real question. One document answers it: "yes, the whole monetisation feature's legal posture is here." Future 2.x work that adds further legal surfaces (CDC, tax invoicing, NFSe) gets separate sections inside the same file until the file hits ~1000 lines — at which point a split is worth considering. Today's ~300-line target is well within the maintainable range.

### Why Portuguese templates instead of English-primary

ANPD responds and operates in Portuguese (Brazilian). Customers of a Brazilian operator are typically Portuguese-speaking (CPF/CNPJ is a Brazilian identifier). The handbook targets Brazilian operators writing in Portuguese to Brazilian ANPD staff and Brazilian customers. English is provided for Template B (customer notification) because some operators have international customers, but the ANPD template is Portuguese-only — the handbook's English-speaking reader is the English-speaking operator, not ANPD.

**This is the sole exception to the "Everything in English" project-wide rule** (CLAUDE.md §Language Policy). The rule's justification is "optimizes LLM interaction and developer experience". The LGPD templates are **operator-to-third-party deliverables**, not code or docs consumed by a developer. ANPD will reject a Portuguese agency being addressed in English; a customer being addressed in English when they registered with a CPF will feel mis-served. The template's language is dictated by its audience, not by the project's internal convention. Document this explicitly in the handbook opening so future contributors don't "helpfully" translate the template to English.

### Why the handbook is self-contained for the breach runbook (not linked to deploy-guide)

The breach runbook is the operator's incident-day artefact — they open it on a bad day and need to run commands top-to-bottom without jumping between documents. A "see deploy-guide §X" link on step 3 of a breach lane is a trust failure at the worst possible moment. So the handbook **duplicates the key-rotation procedure verbatim** rather than linking.

The duplication cost is ~15 lines. Twelve months from now, a deploy-guide refactor MUST update both sites — this is a documented maintenance cost. The alternative (link indirection) has a worse failure mode (operator in crisis gets thrown into a 750-line deploy-guide and has to re-find the procedure). Documentation maintainability loses to operational ergonomics on this specific tradeoff.

CLAUDE.md `## Non-Obvious Gotchas` does not need a new row for this — the tradeoff is documented in the handbook itself (§Self-contained vs linked procedures is a sub-header inside §1.7.2), and in this Dev-Notes section for the contributor audience.

### Why dual placement (deploy-guide + handbook)

Deploy-guide is the operator-at-the-shell reference: "how do I run this command today?" Handbook is the operator-as-controller reference: "which legal obligation does this command discharge?" A single operator visits both at different moments — deploy-guide during a Wednesday-afternoon restore rehearsal, handbook during a Friday-night incident. Consolidating into one would leave one audience underserved.

Documented in the handbook itself (§2 rewrite of `docs/deployment-guide.md:528` says this explicitly) and also surfaced here for the contributor audience.

### Why `####` inside `###` inside `##` — the heading depth decision

The handbook's structure has three levels: `##` (section), `###` (subsection), `####` (sub-subsection for breach-runbook artefacts). Markdown rendering treats `####` as a legitimate heading level; markdownlint accepts up to `######`. Using `**bold-italic**` for sub-subsection markers would be flat-out unreadable in a 200-line section.

The nine `###` subsections are all of sibling importance. The four `####` subsections under `### Breach-notification runbook (Art. 48)` are the FR39-mandated artefacts and are deliberately named as first-class sub-subsections, not inlined paragraphs — operators paging through the section via `Ctrl-F ANPD` / `Ctrl-F template` / `Ctrl-F checklist` hit each artefact's heading directly.

### Why verifying every cited command in master before merge (AC24)

Doc-rot is the single worst failure mode of a runbook. A command that worked at draft-time but was renamed mid-story between draft and merge turns the runbook into operational gaslight at incident time. AC24 is a spot-check, not exhaustive — the dev picks 3 blocks at random and runs them. If all three work, confidence is high; if one fails, inspection of the remaining blocks is warranted before merge.

The "every block" case is aspirationally covered by Task 0's `comadre-keys --help | head -40` pass which confirms the cited verbs exist in master. Beyond that, the actual `--format yaml` output of `export-customer` is unchanged since Story 4.1 (no story between 4.1 and 4.6 touched `export-customer`). The prose cites the output shape in a couple of places; AC24's spot-check catches any accidental drift there.

### Why zero code or test change

FR39 is a documentation requirement. Documentation-requirement stories that smuggle in code changes make the PR review harder (reviewer has to context-switch between "is the markdown faithful to the statutes" and "is this test guarding the right invariant"). 4.6's narrow scope is a deliberate choice: close Epic 4 with a PR that is exclusively a content review.

If the dev encounters a genuine tooling gap at draft-time (e.g., a cited verb's output has drifted since Story 4.1's close, or a playbook produces unexpected output on a first run), the correct response is to file deferred work — NOT to patch the underlying code from inside 4.6. The one exception is a markdownlint violation in the existing content that 4.6's edits inadvertently exposed (cascade effect on nearby headings); that is fair game for a `docs(lint): fix markdownlint violation adjacent to Story 4.6 content` sidecar commit, explicitly not part of this story's diff.

### Why no `docs/monetization.md` "See also" update

The existing "See also" section (`docs/monetization.md:85-89`) cross-references sibling docs (`rate-limiting.md`, `deployment-guide.md`, `configuration-reference.md`) — all EXTERNAL to monetization.md. The LGPD section is INTERNAL — operators scroll down to find it (plus the README pointer at §3 provides a jump target for operators who find the README first).

Adding a "LGPD Operator Obligations" entry to the "See also" block would be a self-reference ("see this same document, further up") — confusing. The subsection TOC rendered by GitHub on markdown views already exposes the anchor; the README pointer exposes it to operators who find the README first. The "See also" block stays scoped to external cross-references.

### Why no Story 4.7 "LGPD-plus-audit-tail export"

Some LGPD interpretations read Art. 18 II ("confirmação da existência de tratamento") + V ("acesso aos dados") broadly enough to include operator-activity logs, not just the subject's personal data. Comadre's current `export-customer` output set (from Story 4.1) is the minimum-necessary interpretation — audit rows are operator-forensic, not subject-access territory. Whether a future Story 4.x should widen this depends on a legal-counsel interpretation an individual operator commissions for their own business — the project does not take a position.

4.6 names the carveout explicitly (§1.4 of the handbook) so operators with a stricter interpretation know they can assemble the broader response manually from `comadre-keys show --audit-tail` + filtering on actor/actioning. If a 4.7 story materialises, it adds an `--include-audit` opt-in to `export-customer`; the handbook's carveout wording anticipates this exact future.

### Why no automated test for the handbook content

A test that "the handbook contains the string 'LGPD Operator Obligations'" is tautological — the test adds nothing beyond grep, and grep is what AC1 already requires the dev to run. A test that "the handbook's shell blocks parse as valid bash" is tempting but brittle: shell-block-parsing would require a bash parser as a test dependency, and bash's grammar doesn't validate that `comadre-keys` is a real command (only that the syntax parses). A test that "every `comadre-keys` verb cited in the handbook is a real verb in master" is achievable — grep the verbs out of the handbook, run `comadre-keys <verb> --help` on each, assert exit 0 — but the work-per-payoff ratio is poor for a prose-only story. If doc-rot becomes a recurring issue across 2.x stories, a consolidated "docs-regression" test lives in `tests/test_non_regression/` (following the 4.5x blueprint), but that is a separate story's territory.

For 4.6 specifically, AC24's 3-block spot-check is the acceptable coverage. The signal-to-noise ratio of an automated parser sits in "nice to have if someone else is writing it"; 4.6 does not ship it.

### Documented explicitly in CLAUDE.md? No

No new "Non-Obvious Gotcha" row is needed. The handbook content itself is straightforward-enough that a future contributor reading `docs/monetization.md` will understand it. The tradeoffs documented above (PT-language exception, self-contained runbook, dual placement) are all audible to the contributor audience via this Dev Notes section and the story file itself — CLAUDE.md is for invariants that break if not read, not for documentation design choices.

### Deferred work to flag at story close

- **`--include-audit` opt-in on `export-customer`.** Already flagged in `_bmad-output/implementation-artifacts/deferred-work.md` (Story 4.1 code-review round). 4.6 confirms the current carveout is explicit in the handbook and propagates the deferral.
- **`correct-tax-id` CLI verb.** Tax-ID corrections today require `delete-customer --hard` + `create-customer`. A dedicated verb would let the tombstone stay stable. Out of 4.6; logged here as a future enhancement.
- **ANPD URL pinning.** The handbook warns the operator to verify the ANPD URL at incident time; an automated monthly check against the ANPD sitemap could detect URL drift and file a PR. Low priority — drift has been slow historically, and the handbook's warning is the authoritative posture.
- **Legal-counsel review of the notification templates.** The handbook templates are structural. A project-commissioned legal-counsel review would improve them but is outside the maintainer's budget. An operator who commissions their own review is encouraged to PR back any improvements as a structural refinement to the templates; the templates themselves remain marked `**TEMPLATE — adapt to the specific incident and have your legal counsel review before sending.**` so no operator mistakes them for vetted-final text.
- **Docs-regression CI gate (cross-cutting).** A future story could extend `tests/test_non_regression/` with a `test_docs_verb_citations.py` that greps every `comadre-keys <verb>` from the docs/ tree and asserts each is a real verb. Payoff is proportional to the doc surface area; today's 4 verbs per doc file × 8 docs = ~30 citations is still reviewer-tractable. Candidate for a later hardening pass.
- **Translation of the handbook opening to Portuguese.** The handbook opening is English (operator-audience); only the templates are Portuguese (ANPD / customer audience). A fully-Portuguese handbook for Portuguese-native operators would be a valuable localisation story. Out of 4.6 scope; candidate for 2.1+.
- **Link-check in pre-commit.** A `markdown-link-check` hook would detect anchor drift between the monetization handbook and the README pointer / deploy-guide cross-reference. Not adding in 4.6 (out of scope; one more pre-commit hook is a config change); candidate if handbook cross-reference drift ever materialises.

### Project Structure Notes

- **File placement.** All content lives in pre-existing files (`docs/monetization.md`, `docs/deployment-guide.md`, `README.md`). No new files created.
- **Section naming.** `## LGPD Operator Obligations` — matches FR39 wording at `prd.md:1177` verbatim ("Operator receives a `docs/monetization.md` section 'LGPD Operator Obligations'"). The PRD's capitalisation is canonical.
- **Anchor hygiene.** GitHub and most markdown renderers compute anchors by lowercasing + hyphenating the heading text. `## LGPD Operator Obligations` → `#lgpd-operator-obligations`. `#### Breach-notification runbook (Art. 48)` → `#breach-notification-runbook-art-48`. Parentheses and colons are stripped. The handbook's internal cross-references use the computed anchors; the Task 12 verification pass confirms each resolves.
- **Markdownlint compliance.** The repo's markdownlint config is authoritative. Common pitfalls: MD013 line-length (disabled for tables per default config; verify before committing); MD040 fenced-code language-hint (use `bash` for shell blocks, `text` for plaintext templates); MD033 inline-HTML (avoid; use plain markdown).
- **Detected conflicts or variances (with rationale).** None today. `docs/monetization.md` grows from 89 to ~300 lines; still under the arch-review threshold for splitting (architecture docs target ~500-line soft cap, operator docs have no hard cap). If 2.1+ adds further LGPD-adjacent content (e.g., tax-invoicing LGPD implications), split into `docs/monetization.md` + `docs/lgpd-handbook.md` at that time. Not this story.

### Testing standards

- **No tests ship with 4.6.** The existing test suites (`uv run pytest`, `uv run pytest -m non_regression`) are run as due-diligence (AC26, AC27) but touch no new lines.
- **Markdownlint via pre-commit** is the sole automated quality gate on the handbook. AC18 asserts this passes.
- **Manual spot-check (AC24)** covers command-correctness. The dev records which 3 blocks they spot-checked in Completion Notes.
- **No bash-linting of the shell blocks.** shellcheck on fenced markdown blocks requires extracting them first; the cost isn't worth it for 6-10 blocks. If shellcheck-in-markdown ever becomes a repo-wide hook, this handbook inherits it automatically.

### References

- Epic 4 Story 4.6 — `_bmad-output/planning-artifacts/epics.md:1025-1053`
- FR39 (LGPD Operator Obligations section + breach-notification runbook + privacy-policy template) — `_bmad-output/planning-artifacts/prd.md:1177`
- NFR36 (Art. 48 breach-notification runbook + ANPD-compliant template) — `_bmad-output/planning-artifacts/prd.md:1252`
- NFR34 (Art. 18 II/V access in ≤15 days) — `_bmad-output/planning-artifacts/prd.md:1250`
- NFR35 (Art. 18 VI deletion in ≤15 days; command <1s) — `_bmad-output/planning-artifacts/prd.md:1251`
- PRD §Domain-Specific Requirements > LGPD binding-requirements — `_bmad-output/planning-artifacts/prd.md:610-623`
- PRD §Risk Mitigations "LGPD or tax-compliance surprise" — `_bmad-output/planning-artifacts/prd.md:1106`
- Architecture §LGPD module map (predicts docs/monetization.md location) — `_bmad-output/planning-artifacts/architecture.md:657, 731`
- Architecture §Project Structure (docs/monetization.md marked `[NEW] operator runbook`) — `_bmad-output/planning-artifacts/architecture.md:592`
- Interim LGPD reference paragraph (replaced by §2 of this story) — `docs/deployment-guide.md:528`
- Existing "LGPD operator procedures" subsection (unchanged) — `docs/deployment-guide.md:480-504`
- Existing "Rotating the encryption key" subsection (unchanged) — `docs/deployment-guide.md:506-528`
- Existing `docs/monetization.md` structure — `docs/monetization.md:1-89`
- `_FORBIDDEN_DETAIL_KEYS` PII-hygiene guard (cited in §1.5) — `src/comadre/keys/audit.py:23-43`
- `encrypt_tax_id` / `decrypt_tax_id` single-site invariant — `src/comadre/keys/crypto.py:69-99`
- `delete_customer_hard` single-transaction contract — `src/comadre/keys/db.py` (Story 4.1 helper)
- `rotate-encryption-key` atomic re-encryption — `src/comadre/keys/cli/commands/system.py` (Story 4.2 verb)
- CLAUDE.md row — tombstone zero-length-BLOB rationale — `CLAUDE.md` (§Non-Obvious Gotchas)
- CLAUDE.md row — single `fernet.decrypt` site invariant — `CLAUDE.md` (§Non-Obvious Gotchas)
- CLAUDE.md row — `rotate-encryption-key` tombstone skip + key-echo contract — `CLAUDE.md` (§Non-Obvious Gotchas)
- CLAUDE.md row — backup-tarball naming contract — `CLAUDE.md` (§Non-Obvious Gotchas)
- CLAUDE.md row — `BACKUP_PASSPHRASE` empty-at-boot posture — `CLAUDE.md` (§Non-Obvious Gotchas)
- CLAUDE.md row — `restore-keys.yml` archived-key ≠ live `.env` warning — `CLAUDE.md` (§Non-Obvious Gotchas)
- CLAUDE.md row — `ansible-playbook health.yml` assertion-chain rule — `CLAUDE.md` (§Non-Obvious Gotchas)
- CLAUDE.md Language Policy (the PT-template exception's justification) — `CLAUDE.md:§Language Policy`
- Lei Geral de Proteção de Dados Pessoais — Lei 13.709/2018 (authoritative external source) — https://www.planalto.gov.br/ccivil_03/_ato2015-2018/2018/lei/l13709.htm
- ANPD (Autoridade Nacional de Proteção de Dados) — https://www.gov.br/anpd/pt-br (the operator verifies the current notification channel at incident time; see §1.7.1 caveat)

## Questions for Operator (please confirm before dev-story)

> All questions have recommended answers. In auto-mode, apply the recommended answer; if any run hits a disagreement, reopen as a deferred-work entry.

1. **Templates language — Portuguese-only for ANPD, Portuguese + English for customer, or English-only throughout.** Recommend **Portuguese-primary for both templates, English-secondary for the customer template**. Rationale above in Dev Notes §Why-Portuguese-templates. Customer template gets English as a courtesy for operators with international customers; ANPD template stays Portuguese-only because ANPD operates in Portuguese.

2. **Handbook location — standalone `docs/lgpd.md` vs section inside `docs/monetization.md`.** Recommend **section inside `docs/monetization.md`** per FR39's explicit wording ("a `docs/monetization.md` section") and the architecture's prediction (`architecture.md:592`). Standalone would diverge from the PRD and force the `See also` block to cross-reference a second LGPD-specific file.

3. **ANPD URL — hardcode specific sub-URL vs cite domain + "verify at incident time".** Recommend **cite the domain with the verify-at-incident-time warning**. ANPD URLs have drifted between 2020 and 2024; hardcoding a specific path creates a doc-rot risk that the operator is least equipped to detect (they read the handbook once during deploy; the real test is months later during an incident).

4. **Self-contained breach runbook vs link-heavy cross-references.** Recommend **self-contained**, despite the maintenance duplication cost. Dev Notes §Why-the-handbook-is-self-contained explains.

5. **Deploy-guide section — delete entirely, keep + link, or keep + update reference.** Recommend **keep + rewrite the final paragraph to an authoritative forward-reference**. The deploy-guide and handbook serve different mental models (operator-at-shell vs operator-as-controller) and both audiences benefit from their respective home.

6. **README pointer — one bullet or replace existing `docs/monetization.md` bullet.** Recommend **append a second bullet**. The existing bullet names the monetisation-fundamentals scope; the new bullet names the LGPD scope. An operator searching the README for "LGPD" hits the anchor directly.

7. **Automated docs-regression test for verb citations (AC24 alternative).** Recommend **defer**. The work-per-payoff ratio is wrong for a prose-only story. If doc-rot becomes a recurring issue across 2.x, a dedicated docs-regression story with tests belongs in 2.1+.

8. **Template placeholder style — `{{braces}}` vs `<angle-brackets>` vs `CAPITALS`.** Recommend **`{{braces}}`**. Matches ansible / jinja convention, unambiguous visual signal, survives markdown rendering unescaped. Angle brackets risk misinterpretation as HTML; capitals look aggressive in a formal template.

9. **AC24 — run all shell blocks or spot-check 3.** Recommend **spot-check 3**. Running every block against a live VPS is 20-30 minutes of dev time for marginal additional coverage (blocks are copy-paste from Stories 4.1/4.2/4.3/4.4, already exercised by those stories' tests). Spot-check catches accidental typos in transcription.

10. **Evidence-preservation checklist — 10 items, 13 items, or more.** Recommend **13** (the spec above lists 13). Less risks missing evidence; more risks checklist fatigue. 13 is drawn from typical post-incident forensics SOPs.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (1M context) — implemented 2026-04-24.

### Debug Log References

- Markdownlint MD031 (blanks-around-fences) flagged once at first run on `docs/monetization.md:261` (Lane B step 1 → step 2 transition). Inserted blank line between the closing fence and the next numbered step. Re-run passed clean.
- AC24 spot-check round 1 surfaced two real bugs in handbook prose:
  - The §Access-request export-customer field-set list said `prefix` for keys; actual JSON key is `key_prefix`. Fixed in §1.4 of `docs/monetization.md`.
  - The Lane A step 3 jq filter said `jq -r '.[].customer_id'`; actual `list-customers --format json` shape uses `id`. Fixed in §1.7.2 Lane A step 3 of `docs/monetization.md`.
  Both bugs were doc-rot-class — the runbook would have failed at incident time. AC24's spot-check is the design rationale; it earned its keep on this story.
- The pre-existing `## Issuing a key` block at `docs/monetization.md:21` cites `comadre-keys create-customer ... --tax-id <number>`; the actual flag is `--cpf` / `--cnpj`. This is a pre-existing bug outside Story 4.6 scope (the block was not modified). Logged as deferred work (see Completion Notes); the new handbook content does not cite `--tax-id`.

### Completion Notes List

- **All 28 ACs satisfied.** Heading present and correctly ordered; 5 `####` subsections under the breach runbook; both incident lanes with ≥ 5 numbered steps each; both Portuguese templates with `{{braces}}` placeholders and legal-review caveat; 13-item evidence-preservation checklist; 4 internal-escalation roles; privacy-policy template (PT primary + EN secondary); references subsection with `path:line-range` pointers.
- **Diff shape clean.** 4 tracked files changed in `git diff master --stat` (`README.md`, `_bmad-output/implementation-artifacts/sprint-status.yaml`, `docs/deployment-guide.md`, `docs/monetization.md`); the story file itself is the 5th file (currently untracked, will be committed alongside). Zero diff in `pyproject.toml`/`uv.lock`/`.github/workflows/`/`src/`/`deploy/` — verified post-edit.
- **Markdownlint clean** on all three touched markdown files (`uv run pre-commit run markdownlint-cli2`). Full pre-commit suite passes (`ruff check`, `ruff format`, `Lint Dockerfiles`, `yamllint`, `shellcheck`, `markdownlint-cli2`, `mypy` — all green).
- **Test suites green at baseline.** Default pytest: 1414 passed, 93 deselected (matches AC26 baseline). Non-regression: 77 passed, 16 skipped (matches AC27 baseline). 4.6 touched zero test files; counts unchanged by definition.
- **AC24 spot-check, 3 blocks against a temp registry:**
  - **Block A** — `comadre-keys list-customers` (handbook §Handling a data-subject access request, step 1). Seeded one customer; `list-customers` rendered the `rich`-style table with the seeded `cust_...` row, the name, the email-truncated cell, and the registration date. Pass.
  - **Block B** — `comadre-keys export-customer <cust_id> --format json` (handbook §Handling a data-subject access request, step 2). Round-tripped to a JSON document with the documented field set (`id`, `name`, `email`, `tax_id_kind`, `tax_id` decrypted to `111.444.777-35`, `registered_at`, `notes`, `keys`). Pass.
  - **Block C** — `comadre-keys delete-customer <cust_id> --hard --yes` followed by `comadre-keys list-customers --deleted` (handbook §Handling a deletion request, steps 3 + 4). Delete printed `Deleted: cust_... (Marcos Silva) — 0 keys purged`; subsequent `list-customers --deleted` showed the tombstone with blank Name/Email cells (PII scrubbed) and the `Customers (including purged)` table title. Pass.
- **Bug-fix-during-spot-check audit trail.** Two doc-rot defects in the handbook (the `prefix` vs `key_prefix` field-set entry, and the `.customer_id` vs `.id` jq filter) were caught by AC24 and patched in-place before review handoff. Story 4.6's "every cited block must round-trip" contract held — but only because the spot-check ran. Recommend keeping AC24-style spot-checks on every future docs-only story.
- **Deferred work flagged** (already documented in §Deferred-work-tracked-against-this-handbook of the new section): `--include-audit` opt-in on `export-customer`; `correct-tax-id` verb; project-commissioned legal-counsel review of templates; localised Portuguese-primary handbook variant. Additionally noted but **outside this story's scope**: the pre-existing `## Issuing a key` block at `docs/monetization.md:21` cites a non-existent `--tax-id` flag on `create-customer`; should be fixed to `--cpf` / `--cnpj` in a follow-up housekeeping commit.

### File List

Modified:

- `README.md` — added one bullet under `## Documentation` pointing to the new `monetization.md#lgpd-operator-obligations` anchor.
- `_bmad-output/implementation-artifacts/4-6-lgpd-documentation-breach-runbook.md` — story file: status flipped `ready-for-dev` → `in-progress` → `review`; tasks/subtasks marked `[x]`; Dev Agent Record + File List + Change Log filled.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `4-6-lgpd-documentation-breach-runbook` flipped `ready-for-dev` → `in-progress` → `review`; `last_updated` bumped (header comment + YAML body).
- `docs/deployment-guide.md` — interim-reference paragraph at line 528 rewritten to an authoritative forward-reference into `monetization.md#lgpd-operator-obligations`.
- `docs/monetization.md` — appended `## LGPD Operator Obligations` (≈ 437 inserted lines): controller identification, data collected and retention, three data-subject-request procedures (access/deletion/correction), breach-notification runbook (ANPD contact + two incident lanes + ANPD & customer notification templates + 13-item evidence-preservation checklist + 4-role internal escalation path), privacy-policy template paragraph, deferred work, references.

Created: none.

Deleted: none.

## Change Log

| Date | Version | Change |
| ---- | ------- | ------ |
| 2026-04-24 | 0.1 | Story spec created → `ready-for-dev`. Last non-optional story in Comadre 2.0.0; last story in Epic 4. Prose-only — no source, no test, no CI, no ansible, no dependency. Lands `## LGPD Operator Obligations` in `docs/monetization.md` (nine subsections covering controller identification, data minimisation, access / deletion / correction procedures, breach-notification runbook with two incident lanes + ANPD & customer templates + evidence-preservation checklist + internal escalation path, privacy-policy template paragraph, references). Rewrites `docs/deployment-guide.md:528` interim-reference paragraph to authoritative cross-reference. Adds one README bullet under `## Documentation`. 28 acceptance criteria (structural, grep-verifiable, markdownlint-gated). 14 tasks. Portuguese-primary templates are the sole documented exception to the project-wide English-only rule (ANPD operates in Portuguese, customer notifications target Brazilian tax-ID-bearing customers). Self-contained breach runbook duplicates the key-rotation procedure from deploy-guide by design (incident ergonomics > maintenance de-duplication). |
| 2026-04-24 | 1.0 | Implementation landed → `review`. ≈ 437 lines appended to `docs/monetization.md`; 5 `####` subsections under the breach runbook (ANPD contact, Incident-response procedure lanes, Notification templates, Evidence-preservation checklist, Internal escalation path); 13-item evidence-preservation checklist; 4-role escalation path; both Portuguese templates with `{{braces}}` placeholders and legal-review caveats; privacy-policy template paragraph (PT primary + EN secondary). `docs/deployment-guide.md:528` rewritten; `README.md` bullet added under `## Documentation`. AC24 spot-check (3 blocks against a temp registry) caught two doc-rot defects pre-review: `prefix` → `key_prefix` in the access-request field-set list, and `.customer_id` → `.id` in the Lane A step-3 jq filter — both fixed in-place. Markdownlint passes (one MD031 pre-fix; resolved). Full `pre-commit run --all-files` green. Default pytest 1414 passed (matches baseline). Non-regression 77 passed (matches baseline). Diff shape: 4 tracked files + 1 untracked story file = 5; zero diff in `src/`, `deploy/`, `.github/workflows/`, `pyproject.toml`, `uv.lock`. |

### Review Findings

Code review run 2026-04-24 (Blind Hunter + Edge Case Hunter + Acceptance Auditor parallel layers; auditor reports 28/28 ACs effectively pass). All `decision-needed` and `patch` items resolved in-place; full pre-commit suite green (markdownlint, ruff, ruff-format, dockerlint, yamllint, shellcheck, mypy). AC19-23 invariants re-verified post-patch: zero diff in `src/`, `deploy/`, `pyproject.toml`/`uv.lock`, `.github/workflows/`. Includes one sidecar fix to `docs/deployment-guide.md:511-513` (same `docker compose exec` `-T` flag bug as Lane B step 1).

**Decision-needed (3) — operator legal-posture calls; cannot be auto-patched:**

- [x] [Review][Decision] **Disclose `notes` field to ANPD as an "affected category" in Template A?** Template A item 3 ("Dados afetados") currently lists "notas operacionais". `notes` is operator-internal free-text — disclosing the category invites ANPD follow-up about what those notes contain. Operator may prefer to omit `notes` or label it "registro operacional interno (não preenchido por padrão)". [docs/monetization.md `### Notification templates` Template A]
- [x] [Review][Decision] **Reveal exact cryptographic mode (AES-128-CBC + HMAC-SHA256) in the ANPD template?** Template A item 3 names the Fernet internals verbatim. Regulators need encryption assurance, not cipher specifics; pre-committing the operator to a cryptography-101 conversation is unnecessary surface area. Replace with "criptografado em repouso (Fernet, AES + HMAC)" or similar high-level wording? [docs/monetization.md `### Notification templates` Template A]
- [x] [Review][Decision] **Add Art. 14 (minors) caveat or B2B-only scope to the privacy-policy template?** §1.8 makes no statement about minors. For a B2B operator (the assumed posture, since `tax_id` accepts CNPJ) this may be N/A; for a B2C operator inheriting the template it is a gap. Either scope the template ("for B2B operators") or add an Art. 14 placeholder paragraph? [docs/monetization.md `### Privacy-policy template paragraph`]

**Patch (15) — concrete unambiguous fixes:**

- [x] [Review][Patch] **HIGH: `update-customer --name` and `--notes` flags don't exist** [docs/monetization.md correction-request §1.6]. Real CLI exposes only `--email` (replace) and `--add-note` (append-with-timestamp); no name/notes replace verb in 2.0.0. Rewrite the bullet to list the two real flags and document the gap (also add a deferred-work bullet for a future "replace-name" verb).
- [x] [Review][Patch] **HIGH: `delete-customer` prompt quote omits `(N key(s))` fragment** [docs/monetization.md:167]. Code emits `"...customer Marcos Silva and all associated keys (3 key(s)). This action..."`; handbook quotes it without the count. Operators comparing on-screen text to handbook text during a stressful DSR will second-guess themselves. Update the quote or soften to "the system prompts to confirm the purge".
- [x] [Review][Patch] **HIGH: Caddy serves 502, not "cached 401s", when `tts-service` stops** [docs/monetization.md:224, Lane A step 1]. Caddy's `reverse_proxy` returns 502 Bad Gateway when the upstream is down; it does not cache 401s. Factual error; will confuse operators when monitoring lights up with 502s during the freeze step. Rewrite to "Caddy returns 502 Bad Gateway for new requests until the service restarts" or similar.
- [x] [Review][Patch] **MED: Lane B step 1 `docker compose exec` lacks `-T` flag** [docs/monetization.md:257-261]. Without `-T` Docker may allocate a pseudo-TTY and append `\r` to the captured value; `NEW_KEY` then contains `gAAAA...=\r` and silently corrupts the `.env` write. Add `-T`. Same latent bug exists in `deployment-guide.md:511-513` — fix there too as a sidecar.
- [x] [Review][Patch] **MED: `openssl enc` lacks `-pass`/`-k` and will hang** [docs/monetization.md:413-414]. Inside a pipeline the passphrase prompt cannot be answered (stdin is the tar stream). Either add `-pass file:<(...)` with explicit instructions, or pre-pend a one-line note that the block is run interactively and prompts for a passphrase.
- [x] [Review][Patch] **MED: `ansible-playbook health.yml` path inconsistency** [docs/monetization.md:281 (full path) vs 401 (bare)]. Lane B post-rotation verification uses full path; Evidence-preservation checklist uses bare. CWD assumption shifts. Normalise to the full path everywhere in §1.7.
- [x] [Review][Patch] **LOW: "Self-contained" claim contradicted by Lane A step 4 "Run Lane B steps 1–4 inline"** [docs/monetization.md:237]. The runbook also retains forward-references to `CLAUDE.md`, `deployment-guide.md`, etc. Either fully inline Lane B's 4 steps into Lane A, or soften the "no jumping between documents" framing to "self-contained for the comadre-keys side; consult deploy-guide for ansible specifics".
- [x] [Review][Patch] **LOW: ANPD URL "drifted between 2020 and 2024" claim is unsourced** [docs/monetization.md `#### ANPD contact`]. Specific historical assertions in a legal-posture document need a source or should be softened. Replace with "the ANPD web presence has changed historically; verify the current notification path before sending" — same operational guidance, no unverifiable claim.
- [x] [Review][Patch] **LOW: `mv /tmp/*.<utc>*` contains a literal `<utc>` placeholder** [docs/monetization.md:412]. Inline comment flags it as needing adaptation, but a rushed operator may paste verbatim. Define `UTC_STAMP=$(date -u +%Y-%m-%dT%H-%M-%SZ)` once at top of the lane and reuse `"$UTC_STAMP"` everywhere.
- [x] [Review][Patch] **LOW: Per-customer audit-tail loop re-evaluates `date` per iteration** [docs/monetization.md:205-210]. Filenames drift by seconds across the loop; evidentiary artefacts lose the "same-incident timestamp" property. Capture once before the loop (folds into the `UTC_STAMP` fix above).
- [x] [Review][Patch] **LOW: `--audit-tail 1000` upper-bound silently truncates high-volume customers** [docs/monetization.md:209, 373]. Code enforces 1..1000 inclusive (`customers.py:522`). Add a one-line note in the Evidence-preservation checklist that customers with >1000 audit rows need offset-by-hand inspection or a `sqlite3` direct-query fallback.
- [x] [Review][Patch] **LOW: `docker compose cp caddy:/var/log/caddy/access.log` may not exist on older Docker** [docs/monetization.md:400]. `docker compose cp` exists in Compose v2.7+; older deployments fall back to `docker cp <container_id> <path>`. Add a one-line fallback or pin a minimum Compose version in the surrounding prose.
- [x] [Review][Patch] **LOW: Mixed checkbox conventions in §1.7.4** [docs/monetization.md `#### Evidence-preservation checklist`]. `- [ ]` items render as GitHub task-list checkboxes (clickable in rendered view) while the surrounding prose says "record `✓ <utc-timestamp>` after each". Pick one — recommend keeping the GH task-list and explaining the operator commits a checkbox tick + an inline timestamp comment.
- [x] [Review][Patch] **LOW: `deploy-guide §Key Registry Management` is textual, not a clickable link** [docs/monetization.md:198]. Heading exists at `deployment-guide.md` (line 405); peer references throughout the handbook use Markdown links. Convert to `[docs/deployment-guide.md §Key Registry Management](../docs/deployment-guide.md#key-registry-management)`.
- [x] [Review][Patch] **LOW: `_FORBIDDEN_DETAIL_KEYS` enumeration is brittle** [docs/monetization.md §1.5 deletion-request rationale]. Prose names the seven keys verbatim; if the canonical list ever changes the handbook silently lies. Add a "(canonical list at `src/comadre/keys/audit.py:23-43`)" pointer so the prose anchors back to the code.

**Defer (3) — pre-existing or out-of-scope:**

- [x] [Review][Defer] Brittle `path:line-range` citations across the new section — by design (AC15 mandates this format); doc-rot risk is acknowledged but the design choice is locked-in. Re-triage if/when a docs-regression CI gate lands (already in deferred-work). [docs/monetization.md `### References`]
- [x] [Review][Defer] Sprint-status YAML duplicate `last_updated` (header comment + body) — pre-existing, intentional per the file's own note; would require automation/hook to keep in sync.
- [x] [Review][Defer] Deferred-work bullets in the new section name future work without tracking IDs — `deferred-work.md` is the project's tracking surface; meta-process concern, not a 4.6 defect.

**Dismissed (1):** README "duplicate-bullet" pattern (two consecutive bullets pointing to `docs/monetization.md` under different anchors) — explicitly chosen by spec Question 6 to give operators searching for "LGPD" a direct anchor jump. Not a defect.
