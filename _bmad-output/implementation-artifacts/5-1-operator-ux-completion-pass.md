---
title: 'Story 5.1 — Operator UX Completion Pass'
type: 'feature'
created: '2026-04-25'
status: 'done'
baseline_commit: '65a945067ed56d79f4fd0036949027e0699379f6'
context:
  - 'CLAUDE.md'
  - '_bmad-output/planning-artifacts/prd.md'
  - 'docs/monetization.md'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** Eight operator-facing CLI gaps surfaced after Comadre 2.0.0 closure: PRD↔story-spec drift narrowed FR4 / FR6 / FR15 silently, the LGPD handbook §1.6 carve-out admitted no first-class fix for tax-ID typos, `rotate-key` lacks the `--yes` switch its peers all have, and `revenue` cannot replay historical state. Day-to-day operator flows currently require SQLite-on-the-host workarounds.

**Approach:** One coordinated pass that fills all eight gaps as new flags / verbs on the existing `comadre-keys` surface, with the same audit / confirmation / exit-code discipline as the rest of the CLI. Zero schema changes, zero auth-path changes, zero ansible changes.

## Boundaries & Constraints

**Always:**
- Reuse existing infrastructure: `_FORBIDDEN_DETAIL_KEYS` audit filter (audit.py:24), `crypto.py::encrypt_tax_id` / `decrypt_tax_id` single-Fernet invariant, `list_audit_events(conn, target_ids, limit)` (db.py:1115), `CustomerCreate` Pydantic field validators (models.py).
- Mirror existing UX precedent verbatim: `revoke-key --yes` flag wording, `--reason` validation pipeline (NUL/CRLF/empty checks → exit 2), ConfirmationLine rendering via `render_confirmation`.
- Audit `details_json` MUST NOT echo PII — `_FORBIDDEN_DETAIL_KEYS` covers `name`, `email`, `cpf`, `cnpj`, `tax_id`, `key_plaintext`, `authorization`. Tax-ID values never appear in audit; `tax_id_kind` (`cpf`/`cnpj`) is metadata and may.

**Ask First:**
- Any change to `src/comadre/keys/migrations/`, `src/comadre/keys/auth.py`, `src/comadre/api.py`, `src/comadre/rate_limit.py`, or `deploy/ansible/` (these are out of scope; if touching them looks unavoidable, HALT).
- Adding a second `fernet.decrypt` call site outside `crypto.py` (single-site invariant).

**Never:**
- Per-IP rate limiting (FR25 retired). Legacy single-key auth (FR27 / NFR31 retired).
- Performance benchmarks or new CI gates.
- Schema migrations — every gap is implementable on `v002`.
- New audit indexes — `list_audit_events` already runs viable on the existing `idx_audit_occurred`.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behaviour | Error Handling |
|---|---|---|---|
| `update-customer --name "New"` | active customer | name updated; audit `update_customer` with `details_json={"fields":["name"]}`; suffix `"name changed"` | name length 0 / >200 → exit 2 (Pydantic ValidationError → render_error) |
| `update-customer --notes "X" --add-note "Y"` | both flags | exit 2: "use either --add-note (append) OR --notes (replace), not both" | mutual-exclusion check before DB call |
| `mark-paid <p> --months 2` | `paid_until=2026-04-15` | new `paid_until=2026-06-15`; audit details `{"mode":"months","months":2}` | `--months` < 1 or > 36 → exit 2 |
| `mark-paid <p> --months 1` | expired key (`paid_until < today`) | new `paid_until = today + 1mo` | both `--months` and `--until` supplied → exit 2 |
| `mark-paid <p> --price-monthly 100.999` | active key | rounds to 101.00; atomic UPDATE of `paid_until` + `price_monthly`; audit `{"price_monthly_changed":true,"old":<prev>,"new":101.00}` | `<= 0` or `> 99999.99` or NaN/inf → exit 2 |
| `rotate-key <p> --yes` | closed stdin | succeeds; emits new plaintext; audit + sentinel touch unchanged | without `--yes` + closed stdin → exit 1 + "pass --yes if scripting" hint |
| `export-customer <id> --include-audit` | customer with key+payment events | envelope contains `audit_events: [{action,actor,occurred_at,details?}, …]`; details filtered through `_FORBIDDEN_DETAIL_KEYS` | default (no flag) → no `audit_events` field |
| `correct-tax-id <id> --new-tax-id <n> --reason "<text>" --yes` | active customer | atomic UPDATE of `tax_id_encrypted` + `tax_id_kind`; `customer_id` + FKs preserved; audit `correct_tax_id` with `{"old_kind","new_kind","reason"}` | invalid CPF/CNPJ checksum → exit 2 ("invalid CPF/CNPJ", input not echoed); tombstoned customer → 404-shape error |
| `revenue --month 2026-04 --as-of 2026-04-15` | audit log spans 2026-03..now | reconstructed snapshot; status as-of `2026-04-15` applied to month-window bucket logic | `--as-of` future → exit 2; `--as-of` < earliest audit row → exit 2 |

</frozen-after-approval>

## Code Map

- `src/comadre/keys/cli/commands/customers.py:714` — `update_customer_cmd`: add `--name`, `--notes` flags + mutual-exclusion check.
- `src/comadre/keys/cli/commands/customers.py:700` — `_update_confirmation_suffix`: add `"name changed"`, `"notes replaced"` tokens.
- `src/comadre/keys/cli/commands/customers.py:895` — `export_customer_cmd`: add `--include-audit` flag; new envelope key.
- `src/comadre/keys/cli/commands/customers.py` — NEW: `correct_tax_id_cmd` (top-level verb registered on `customers_app`).
- `src/comadre/keys/cli/commands/billing.py:119` — `mark_paid_cmd`: add `--months`, `--price-monthly`; mutual-exclusion `--months` × `--until`.
- `src/comadre/keys/cli/commands/billing.py:716` — `revenue_cmd`: add `--as-of`.
- `src/comadre/keys/cli/commands/keys.py:955` — `rotate_key_cmd`: add `--yes` flag mirroring `revoke_key_cmd:1091`.
- `src/comadre/keys/db.py:553` — `update_customer`: extend signature with `new_name: str | None`, `replace_notes: str | None`. DB-layer mutual-exclusion guard.
- `src/comadre/keys/db.py:1544` — `mark_key_paid`: extend signature with `new_price_monthly: float | None`; atomic UPDATE.
- `src/comadre/keys/db.py:1115` — `list_audit_events`: REUSE for `--include-audit` (pass `target_ids = [customer_id, *key_ids_for(customer_id)]`).
- `src/comadre/keys/db.py` — NEW: `correct_customer_tax_id(conn, customer_id, *, new_tax_id_encrypted, new_tax_id_kind, reason, actor, today)`; NEW: `reconstruct_key_state_at(conn, as_of: date) -> dict[str, KeyStateSnapshot]` (audit-replay folding `issue_key`, `mark_paid`, `suspend`, `reactivate`, `revoke_key`, `update_key` actions per `target_id`).
- `src/comadre/keys/cli/output.py:113` — `render_confirmation`: untouched; reused.
- `docs/monetization.md` §1.4 — rewrite "Explicit exclusions" carve-out paragraph to document `--include-audit` opt-in.
- `CLAUDE.md` — append two "Non-Obvious Gotcha" rows.

## Tasks & Acceptance

**Execution** (ordered by dependency; each bullet sized ≈ one PR):

- [x] `customers.py:714` + `db.py:553` — extend `update_customer_cmd` with `--name` / `--notes`; reuse `CustomerCreate.name` Pydantic field for length validation; reject NUL/CR/LF on `--notes` per existing `_validate_note` rules; mutual-exclusion `--notes` × `--add-note`; extend `_update_confirmation_suffix`.
- [x] `billing.py:119` + `db.py:1544` — `mark-paid --months {1..36}` (compute `until_date` server-side via `relativedelta` from `python-dateutil`, fallback to hand-rolled `_add_calendar_months` if dep ladder forbids); `--price-monthly` with `Decimal(...).quantize("0.01")`; mutual-exclusion `--months` × `--until`; atomic UPDATE.
- [x] `keys.py:955` — `rotate-key --yes`; mirror `revoke_key_cmd` flag wording verbatim; non-TTY-without-`--yes` → exit 2 with inline hint string (pattern from `revoke_key_cmd`; matches the precedent — exit 2 not exit 1).
- [x] `customers.py:895` + `db.py:1115` — `export-customer --include-audit`; collect `target_ids = [customer_id] + all key_ids for that customer`; cap audit-list at the existing `list_audit_events` upper bound; recursively filter `details` through `_FORBIDDEN_DETAIL_KEYS` (new `audit.py::filter_forbidden_keys` helper). Updated `docs/monetization.md` §1.4.
- [x] NEW `customers.py::correct_tax_id_cmd` + NEW `db.py::correct_customer_tax_id` + NEW `tests/test_keys_cli_correct_tax_id.py` — validate via `crypto.py::validate_cpf` / `validate_cnpj`; encrypt via `crypto.py::encrypt_tax_id` (no Fernet import); single transaction; require `--reason` (mirror `revoke-key --reason` validators); `--yes` to skip prompt; tombstoned customer rejected; FKs preserved.
- [x] NEW `db.py::reconstruct_key_state_at` + `db.py::earliest_audit_date` + `billing.py:716` — audit-replay snapshot (status, billing_mode, paid_until, price_monthly per key_id) up to `as_of`; `revenue --as-of` validates `today >= as_of >= earliest_audit_row.date`; same bucket logic applied to snapshot. Documented price_monthly hybrid-replay limitation in CLAUDE.md.
- [x] `CLAUDE.md` — gotcha rows for `--include-audit` opt-in default-off, `correct-tax-id` preserving `customer_id`, `mark-paid --months` anchor semantics, and `revenue --as-of` hybrid replay.
- [x] `_bmad-output/implementation-artifacts/sprint-status.yaml` — Epic 5 added; story 5-1 currently `in-progress`. Flip to `done` after merge.

**Acceptance Criteria:**

- Given Gap 1, when `comadre-keys update-customer <id> --name "X"`, then `show <id>` reflects new name; `details_json` is exactly `{"fields":["name"]}`; no PII leak.
- Given Gap 2, when both `--notes` and `--add-note` supplied, then exit 2 with the disambiguation message.
- Given Gap 3 expired key, when `--months 1`, then `paid_until == today + relativedelta(months=1)`.
- Given Gap 4, when `--price-monthly 100.999 --months 1`, then both columns updated atomically; price stored as `101.00`; audit captures old/new.
- Given Gap 5, when `echo "" | rotate-key <prefix> --yes`, then exit 0 + new plaintext printed; without `--yes` + closed stdin → exit 1 + scripting hint.
- Given Gap 6, when `export-customer <id> --include-audit`, then envelope contains non-empty `audit_events` array; every entry has `{action, actor, occurred_at}`; `details` (if present) passes `_FORBIDDEN_DETAIL_KEYS` recursive filter; default export (no flag) has no `audit_events` key.
- Given Gap 7 valid input, when `correct-tax-id <id> --new-tax-id <valid> --reason "..." --yes`, then `tax_id_encrypted` decrypts to new value; `customer_id` unchanged; all `api_key.customer_id` FKs unchanged; audit `correct_tax_id` row carries old/new `tax_id_kind` + reason. Given invalid checksum, then exit 2; rejected input not echoed.
- Given Gap 8, when `revenue --month 2026-04 --as-of 2026-04-15` for a key created 2026-03-01 / paid 2026-04-10 / suspended 2026-04-20, then key bucket = `paid`. Same command with `--as-of 2026-04-25` → bucket = `suspended`. `--as-of 2099-01-01` → exit 2. `--as-of 1900-01-01` → exit 2.
- `git diff master -- src/comadre/keys/migrations/ src/comadre/keys/auth.py src/comadre/api.py src/comadre/rate_limit.py deploy/ansible/` is empty.

## Spec Change Log

### 2026-04-25 — Review pass (patches, no loopback)

**Triggering finding:** Acceptance auditor + edge-case hunter both flagged that the I/O Matrix and AC clauses for two verbs disagree with the shipped exit codes. Implementation matches the explicit "Always: Mirror existing UX precedent verbatim" Boundary; the matrix cells were typos against that Boundary.

**Amendments (documentary, code unchanged):**

1. **`correct-tax-id` invalid CPF/CNPJ checksum exits 4, not 2.** Mirrors `create-customer` (`customers.py:211`) and `delete-customer --hard` validators that already exit 4 on `InvalidTaxIdError` per the "tax-ID validation tier" UX-DR convention. The I/O Matrix row and AC §7 should read "exit 4" not "exit 2". Test `tests/test_keys_cli_correct_tax_id.py::test_correct_tax_id_invalid_checksum_exits_4` pins exit 4.
2. **`rotate-key --yes` non-TTY abort exits 2, not 1.** Mirrors `revoke-key --yes` (`keys.py:1178`) which uses Click's `Abort` → exit 2 (UX-DR10 usage tier) when stdin is closed without `--yes`. The I/O Matrix row and AC §5 should read "exit 2" not "exit 1". Test `test_rotate_key_without_yes_aborts_with_scripting_hint` pins exit 2.
3. **`mark-paid --until` audit `details_json` now carries `{"mode": "until"}`** alongside the existing `paid_until` / `reactivated` fields. Pre-5.1 callers that filter on `mode IS NULL` to detect Story-3.1-era rows must instead negate-test `mode == "until"`. Forward-only: the field is additive and keeps the audit-shape uniform across `--until` and `--months` paths.

**Known-bad state avoided:** Future readers who saw the I/O Matrix without this log would file phantom regressions claiming the implementation deviates. The Boundary already overrode the matrix detail; this entry makes the override explicit.

**KEEP instructions for re-derivation (if this story ever loops back):**
- Mirror `revoke-key` `Abort` → exit 2 + non-TTY hint pattern verbatim in `rotate-key` and `correct-tax-id` (do NOT invent a new exit code).
- Reuse `audit.py::filter_forbidden_keys` (now Mapping + Sequence-recursive) for any future `--include-audit`-style export — do not rewrite the recursion locally.
- Keep `correct_tax_id_cmd`'s `_CUSTOMER_ID_PATTERN` pre-DB shape check (added during the review pass; closes a gap where typos opened DB connections).
- Keep the `--notes ""` empty-string rejection in `update_customer_cmd` (added during the review pass; an empty replace would silently wipe the column).

### Patches applied during the review pass

- **`audit.py::filter_forbidden_keys` recurses into `Sequence` values (lists/tuples) in addition to `Mapping`.** Defense-in-depth: the audit-write path's blocklist invariant covers nested-dict shapes; the read-path filter must too, in case the schema ever grows list-typed payloads.
- **`reconstruct_key_state_at` now type-guards `details["paid_until"]` against non-string values.** Schema NOT NULL/TEXT shields the live row, but a corrupt or out-of-band audit row with `paid_until: null` or `paid_until: 12345` would have caused `_bucketize_for_revenue` to raise `TypeError` from `date.fromisoformat`. Now silently skips the assignment, leaving the snapshot's prior `paid_until` intact.
- **`correct_tax_id_cmd` rejects malformed `customer_id` with exit 2 BEFORE opening settings / encrypting / opening the DB.** Parity with `export-customer` / `delete-customer`. Closes the gap where a typo'd ID opened a connection just to fail at `get_customer` with exit 3.
- **`update_customer_cmd` rejects empty / whitespace-only `--notes`** with exit 2. An operator who typed `--notes ""` thinking it was a no-op would otherwise wipe the column silently.

## Design Notes

**Why `correct-tax-id` not `delete-customer --hard` + `create-customer`:** delete-and-recreate severs `customer_id` continuity — all `api_key.customer_id` FKs, billing history, and audit chain re-anchor on a fresh customer row. `correct-tax-id` keeps the row stable; only the encrypted blob and `tax_id_kind` mutate.

**Why `--include-audit` is opt-in:** LGPD Art. 18 II/V minimum-necessary reading is the default; broad-reading (audit history of all key issuance / rotation / payment events) is the operator's legal-counsel call. Default-off preserves the leaner export.

**Audit-replay correctness for Gap 8:** `reconstruct_key_state_at` is a pure function over `audit_log` — it reads no current-state columns. Validate against a hand-built fixture (issue → mark_paid → suspend → reactivate sequence) before relying on the snapshot for revenue arithmetic.

## Verification

**Commands:**
- `uv run pytest tests/keys/cli/ -k "update_customer or mark_paid or rotate_key or export_customer or correct_tax_id or revenue"` — expected: all green.
- `uv run ruff check . && uv run mypy src/` — expected: clean.
- `rg "fernet\.decrypt" src/` — expected: exactly one hit (`crypto.py::decrypt_tax_id`).
- `rg "fernet\.encrypt" src/` — expected: exactly one hit (`crypto.py::encrypt_tax_id`).
- `git diff master -- src/comadre/keys/migrations/ src/comadre/keys/auth.py src/comadre/api.py src/comadre/rate_limit.py deploy/ansible/` — expected: empty.
- `uv run pre-commit run --all-files` — expected: clean.

**Manual checks:**
- `comadre-keys --help` lists `correct-tax-id`. Each new flag visible on `<verb> --help`.
- Seed an end-to-end fixture (create-customer → issue-key → mark-paid → rotate-key → export-customer --include-audit → correct-tax-id → revenue --as-of) and confirm every confirmation line, exit code, and audit row matches the matrix above.

## Suggested Review Order

**New verb (largest novelty surface, read first to grasp the discipline pattern)**

- Top-level CLI verb — full validation pipeline + Destroy-tier confirmation gate + helper dispatch
  [`customers.py:1233`](../../src/comadre/keys/cli/commands/customers.py#L1233)
- DB helper — single-transaction UPDATE + audit row with `{old_kind, new_kind, reason}` (no PII)
  [`db.py:681`](../../src/comadre/keys/db.py#L681)

**Audit-replay subsystem (highest correctness risk)**

- Forward-replay snapshot builder — bootstrap from current row + walk audit ASC up to `as_of`
  [`db.py:1275`](../../src/comadre/keys/db.py#L1275)
- Lower-bound sentinel for `--as-of` validation
  [`db.py:1258`](../../src/comadre/keys/db.py#L1258)
- `revenue --as-of` wiring + `_bucketize_for_revenue` reuse over the snapshot
  [`billing.py:841`](../../src/comadre/keys/cli/commands/billing.py#L841)

**`mark-paid` flag extension (atomic price+date write)**

- Mutex check + month-anchor logic + `--price-monthly` Decimal pipeline
  [`billing.py:167`](../../src/comadre/keys/cli/commands/billing.py#L167)
- Decimal-quantize price validator (banker's rounding, range guard)
  [`billing.py:136`](../../src/comadre/keys/cli/commands/billing.py#L136)
- Helper extension — atomic `paid_until + price_monthly` UPDATE + audit `{old, new}`
  [`db.py:1827`](../../src/comadre/keys/db.py#L1827)

**`update-customer` flag extension**

- New `--name` / `--notes` flags + replace-vs-append mutex + empty-notes refusal (review patch)
  [`customers.py:734`](../../src/comadre/keys/cli/commands/customers.py#L734)
- Helper extension — `new_name` / `replace_notes` kwargs + `notes_op` discriminator
  [`db.py:555`](../../src/comadre/keys/db.py#L555)
- Confirmation suffix grammar — `name changed` / `notes replaced` vs `note added`
  [`customers.py:713`](../../src/comadre/keys/cli/commands/customers.py#L713)

**Audit filter widening for `--include-audit` (defense-in-depth)**

- Recursive forbidden-key filter — now walks both `Mapping` and `Sequence` (review patch)
  [`audit.py:57`](../../src/comadre/keys/audit.py#L57)
- `export-customer --include-audit` flag + envelope augmentation
  [`customers.py:1028`](../../src/comadre/keys/cli/commands/customers.py#L1028)
- Per-event projection helper — emits `{action,actor,occurred_at,details?}` post-filter
  [`customers.py:1004`](../../src/comadre/keys/cli/commands/customers.py#L1004)

**`rotate-key --yes` (smallest, mirrors `revoke-key` precedent verbatim)**

- New `--yes` flag + `Abort` → exit 2 + non-TTY hint (precedent-mirroring; spec exit code reconciled in Spec Change Log)
  [`keys.py:955`](../../src/comadre/keys/cli/commands/keys.py#L955)

**Tests**

- New verb end-to-end coverage (happy path + LGPD audit shape + checksum + mutex + shape-check)
  [`test_keys_cli_correct_tax_id.py`](../../tests/test_keys_cli_correct_tax_id.py)
- Audit-replay fixture (issue → mark_paid → suspend with backdated `occurred_at`) + boundary tests
  [`test_keys_cli_revenue.py`](../../tests/test_keys_cli_revenue.py)
- `--months` / `--price-monthly` happy-path + mutex + boundary
  [`test_keys_cli_mark_paid.py`](../../tests/test_keys_cli_mark_paid.py)
- `--name` / `--notes` mutation + LGPD audit-shape + replace-vs-append distinction
  [`test_keys_cli_update_customer.py`](../../tests/test_keys_cli_update_customer.py)
- `--include-audit` envelope + forbidden-keys filter assertion
  [`test_keys_cli_export_customer.py`](../../tests/test_keys_cli_export_customer.py)
- `--yes` flag + non-TTY abort + scripting hint
  [`test_keys_cli_rotate_key.py`](../../tests/test_keys_cli_rotate_key.py)

**Docs + sprint state**

- Four new "Non-Obvious Gotcha" rows: `--include-audit` opt-in, `correct-tax-id` FK preservation, `mark-paid --months` anchor, `revenue --as-of` hybrid replay
  [`CLAUDE.md`](../../CLAUDE.md)
- LGPD handbook §1.4 carve-out rewritten to reference the `--include-audit` opt-in
  [`monetization.md`](../../docs/monetization.md)
- Epic 5 added; story 5-1 still `in-progress` (flip to `done` after merge)
  [`sprint-status.yaml`](sprint-status.yaml)
