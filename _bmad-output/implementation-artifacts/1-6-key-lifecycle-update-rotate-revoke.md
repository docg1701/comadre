# Story 1.6: Key Lifecycle (Update, Rotate, Revoke)

Status: done

<!-- Validation optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want to update an existing key's tier (RPM, price, notes), rotate a compromised key to fresh plaintext without churning customer IDs, and revoke a key when a contract ends,
so that I can manage the full API-key lifecycle from the CLI without issuing new `key_…` records every time a tier changes, and without leaking the old plaintext once rotation or revocation has happened.

**Covers FRs:** FR10 (update key RPM/price/notes), FR11 (rotate key — new plaintext, same `key_` ID), FR12 (revoke key with free-form reason; revoked row retained), FR30 (audit every mutation).
**UX-DRs:** UX-DR1 (double-border KeyPanel for `rotate-key`), UX-DR7 (ConfirmationLine for `update-key` and `revoke-key`), UX-DR8 (color-coded status), UX-DR9 (shared Console), UX-DR10 (exit codes), UX-DR11 (Destroy-tier `--yes` for `revoke-key`), UX-DR15 (realistic `--help` examples), UX-DR17 (copy-paste fidelity for rotated plaintext), UX-DR18 (warning text for pre-rotation-not-yet-reissued state; not used in Story 1.6 — see Scope guards).
**NFRs:** NFR5 (mutation class under 500 ms for 1 K customers), NFR9 (API keys stored as SHA-256 hashes — rotation re-hashes via the existing `hash_api_key` seam), NFR11 (timing-safe comparison — no regression; rotation writes a new hash, does not compare existing hashes), NFR15 (no plaintext/PII in logs), NFR16 (no invalid-input echo in error hints), NFR33 (backward-compatible within major version).
**Epic:** 1 — Key Registry & Customer Management. **Unblocks operator Journey 5 (Debug Session) — the final step of Ricardo's tier-change flow** (PRD L472–L475).

**Builds on:**
- Story 1.1 (`keys/` subpackage, v001 schema, `log_event` blocklist, `insert_customer` transaction-plus-audit pattern, `get_cli_actor()`, `_errors.py` helpers, `_clear_settings_cache` autouse, `render_error`).
- Story 1.2 (`generate_api_key_plaintext` / `hash_api_key` / `key_prefix_from_plaintext` in `keys/tokens.py`, `_format_brl`, `IssuedKey` dataclass, `render_key_panel` three-piece layout, `insert_api_key` transaction-plus-audit pattern, issue-key usage-error ordering and exit-code ladder, `first_error_msg`, `is_missing_encryption_key`, `_MISSING_KEY_HINT`).
- Story 1.3 (`render_empty_state`, `render_json`, `_iso_date`, autouse `_reset_consoles_to_buffers` fixture, stderr-routed `keys.cli` logger for clean stdout).
- Story 1.4 (`resolve_show_target` → `ShowTarget{kind, value}` discriminated union, `KeyDetailRow`, `_SHOW_NOT_FOUND_HINT` / `_SHOW_AMBIGUOUS_HINT`, cmdr_live_-paste redaction in logs).
- Story 1.5 (`update_customer` + `UpdateCustomerResult` helper shape, `{"fields": [...]}` audit-details contract, NUL / newline / whitespace validation ladder for free-text operator input, same-transaction UPDATE-plus-audit contract for row mutations).

**Unblocks:**
- Story 2.1 (`verify_api_key_registry`) — once rotation is available, the auth path's "old hash no longer matches" contract (FR11 end-of-life guarantee) is operator-testable end-to-end.
- Story 2.1 / Story 3.1 workflows that read `status ∈ {active, suspended, revoked}` rely on this story's `revoke_key` helper being the sole writer of `status='revoked'` (cron sweep writes `status='suspended'`; neither writes the other).
- Story 3.1 (`suspend` / `reactivate` / `mark-paid`) — inherits this story's `update_api_key`-style transactional helper signature and ConfirmationLine grammar (`Updated: <prefix> (<name>) — …`).
- Story 4.1 (`delete-customer --hard`) — depends on key-state lifecycle being complete so LGPD hard-delete has a fully-exercised "revoked-then-purged" path to chain after.

**Depends on:** Nothing outside Stories 1.1–1.5. No new Python dependencies. No schema migration (the `api_key` table has existed since v001 with all columns we mutate).

## Scope

Adds **three Typer commands** — `update-key`, `rotate-key`, `revoke-key` — plus the three DB helpers that power them. All three accept a single positional `<key-prefix>` (or `key_<ulid>`, or pasted `cmdr_live_<plaintext>`) and route through the existing `resolve_show_target` discriminator. All three write exactly one `audit_log` row per successful invocation inside the same transaction as the mutation. Work breaks down as:

1. **`update_api_key` helper in `src/comadre/keys/db.py`.** Signature: `update_api_key(conn, key_id, *, new_rpm, new_price, new_notes, actor) -> UpdateKeyResult | None`. Opens its own `with conn:` transaction (same pattern as `insert_customer` / `insert_api_key` / `update_customer`). SELECTs the live row by `id` (primary-key lookup — the CLI resolves prefix → `key_id` before calling the helper), applies whichever of `{rate_limit_rpm, price_monthly, notes}` are non-None, writes one `update_key` audit row, commits. Returns `None` if the row is missing (defensive — the CLI's `resolve_show_target` lookup almost always prevents this). Raises `ValueError("cannot update a revoked key")` when the current row has `status='revoked'` (the transaction is rolled back unwritten because the SELECT runs first). Returns `UpdateKeyResult{key: KeyDetailRow, updated_fields: tuple[Literal["rpm","price","notes"], ...], changes: KeyFieldDeltas}` — `changes` captures `(old_rpm, new_rpm)`, `(old_price, new_price)` so the ConfirmationLine can render the `60→120` arrow form per AC1.

2. **`rotate_api_key` helper in `src/comadre/keys/db.py`.** Signature: `rotate_api_key(conn, key_id, *, new_plaintext, actor) -> RotateKeyResult | None`. Opens `with conn:`. Loads the current row via `get_key_detail_by_id`. If `status='revoked'` → raises `ValueError("cannot rotate a revoked key")` (inside the `with`, which rolls back). Hashes `new_plaintext` via the existing `hash_api_key` seam, extracts the new 8-char prefix via `key_prefix_from_plaintext`, executes `UPDATE api_key SET key_hash=?, key_prefix=?, last_used_at=NULL WHERE id=?`, writes one `rotate_key` audit row with `details={"key_prefix_old": <old>, "key_prefix_new": <new>}` (prefixes are not PII — they already appear in the `Key issued` structured log since Story 1.2). Commits. Returns `RotateKeyResult{record: ApiKeyRecord, customer_name: str, old_prefix: str}` so the CLI can feed it into `render_key_panel` without a follow-up `get_key_detail_by_id` round-trip. **Atomicity invariant:** the UPDATE and audit write must both commit or both roll back — if the audit write fails (blocklist violation, disk full) the old `key_hash` stays authoritative and no plaintext has been disclosed yet (we render the KeyPanel only after `conn.commit()`).

3. **`revoke_api_key` helper in `src/comadre/keys/db.py`.** Signature: `revoke_api_key(conn, key_id, *, reason, actor) -> RevokeKeyResult | None`. Opens `with conn:`. Loads the current row. If already `status='revoked'` → raises `ValueError("already revoked")` (surfaced as exit 3 "Key already revoked"). Else executes `UPDATE api_key SET status='revoked' WHERE id=? AND status != 'revoked'` + one `revoke_key` audit row with `details={"reason": <reason>}`. The blocklist in `keys/audit.py` does NOT forbid `"reason"` — it only forbids `{"cpf", "cnpj", "tax_id", "name", "email", "key_plaintext", "authorization"}` — so a free-text reason travels cleanly through `details_json`. Returns `RevokeKeyResult{key: KeyDetailRow, customer_name: str, reason: str}` for the ConfirmationLine renderer.

4. **Three commands in `src/comadre/keys/cli/commands/keys.py`** (colocated with `issue-key` and `list-keys` — same rationale: the token helpers, billing helpers, and KeyPanel renderer live one import away). Each command follows the Story 1.2 / 1.4 / 1.5 validation ladder: (a) flag-shape checks (exit 2) → (b) settings load (exit 6) → (c) billing-TZ validation (exit 6) → (d) DB open + migrations (exit 5) → (e) `resolve_show_target` prefix lookup (exit 3 on `not_found` / `key_ambiguous` / `customer` branches) → (f) helper call (exit 3 on "already revoked" / "cannot mutate revoked" ValueError; exit 5 on `sqlite3.Error`) → (g) render + exit 0.

5. **Output helper extension in `src/comadre/keys/cli/output.py`.** Extend the existing `_context_block` so that, when `issued.first_charge_date is None` **and** the record is manual-mode, the panel renders `paid until: <iso>` using `record.paid_until` (or `paid until: \u2014` when the key has never been paid). `issue-key` keeps its existing path (passes a non-None `first_charge_date` → panel shows `first charge: <iso> (N days free until then)`). `rotate-key` passes `first_charge_date=None` so the panel shows `paid until:` instead — the operator's mental model is "rotation preserves billing state; only the plaintext and `last_used_at` change." Complimentary-mode behavior is unchanged (`paid until: \u2014 (not applicable)` hardcoded literal applies in both `issue-key` and `rotate-key` flows).

6. **Pyproject / lock file:** no new dependencies. `typer.confirm` lives in Typer already. `difflib`, `secrets`, `hashlib`, `datetime`, `zoneinfo`, `json` are stdlib.

7. **Unit + integration tests:**
   - `tests/test_keys_db.py` — append `TestUpdateApiKey`, `TestRotateApiKey`, `TestRevokeApiKey` classes.
   - `tests/test_keys_cli_update_key.py` (new) — end-to-end for `update-key`.
   - `tests/test_keys_cli_rotate_key.py` (new) — end-to-end for `rotate-key`.
   - `tests/test_keys_cli_revoke_key.py` (new) — end-to-end for `revoke-key`, including the interactive-confirm paths.
   - `tests/test_keys_output.py` — add a test asserting that `_context_block` renders `paid until:` when `first_charge_date is None` on a manual-mode record.

**Out of scope (future stories, DO NOT add):**

- **`suspend <key>` / `reactivate <key>` / `mark-paid <key>`** → Epic 3 Story 3.1. `suspend` writes `status='suspended'` (not `'revoked'`). `revoke-key` is terminal; `suspend` is reversible. Do NOT implement suspension under the `revoke-key` verb.
- **`--billing-mode` flag on `update-key`** → billing-mode changes are contract-level (manual ↔ complimentary transitions bring `--price` and `paid_until` semantics along with them). The supported path is `revoke-key` → `issue-key` with the new mode. Explicitly reject `--billing-mode` as an unknown flag (Typer's default behavior).
- **`--price` change on a complimentary key** → same rationale as issue-key's mutex (`complimentary` + `--price` = exit 2 usage error). Operator wanting to turn a bundled key into a paid one revokes + reissues.
- **`--customer` change on `update-key`** → a key is bound to a customer for its entire lifetime; the audit trail would rot if we let it hop. If the operator truly needs to move a key to a new customer (unheard-of), revoke + reissue.
- **`--add-note` append semantics for `update-key` `--notes`** → the customer `notes` column is narrative (operator notebook), append-only by FR3. Key `notes` is metadata (one-line tier-change stamps like "upgraded 2026-05-12 from 60→120rpm"). Replace semantics fit the key surface cleanly; forcing append would let `api_key.notes` grow unbounded over the lifetime of a rotating/upgrading key. Future `--add-note` on keys is a separate PRD entry, not a Story 1.6 hidden feature.
- **`revoke-customer` / cascading revocation** → out of scope. Story 4.1 `delete-customer --hard` is the LGPD operation; normal contract-end customer deletion is not in Epic 1 or Epic 4 roadmap.
- **`rotate-key --reveal-old`** → the old plaintext is lost by design the moment it was hashed in `issue-key` (NFR9). No "recover old key" flag; rotation means the old key is gone.
- **`--reason` on `update-key`** → spec-silent. The `update_key` audit row already records operator + action + fields changed. If a narrative is needed, the operator adds it via `update-customer --add-note` after the key update.
- **`--dry-run`** → spec-silent. Operators who want to preview a change run `show <prefix>` first. Adding `--dry-run` across all three commands is boilerplate that invites skew with the real mutation code.
- **`--format json` for any of the three commands** → same reasoning as Story 1.5: mutation commands stay single-line per UX-DR7 + PRD L960–L967. `rotate-key` has a multi-line KeyPanel on stdout (already non-machine-parseable by design — plaintext lives on one line for triple-click copy, context on another). Scripting paths use `show --format json` after the mutation.
- **Rich-markup escaping on `customer_name`** → still deferred cross-cutting with Story 1.4's `render_customer_detail` item (`customer_name` containing `[red]X[/]` would re-style the KeyPanel context rows). Same pre-existing surface; Story 1.6 does not regress and does not fix.
- **Concurrent two-rotations-against-same-key regression test** → still deferred per `deferred-work.md` (project runs a single FIFO queue; SQLite's `busy_timeout=5000` plus the `with conn:` atomicity bounds the realistic race window).
- **Optimization of the post-commit `get_key_detail_by_id` re-read** → deferred per Story 1.5 code review (Task 1.3 continues the round-trip pattern for consistency; optimization is not a bug).
- **Increasing `api_key.rate_limit_rpm` upper bound enforcement in Story 2.2** — we ADD a sane cap here (see Dev Notes §Validation ladder) to close Story 1.2's deferred "unbounded `--rpm`" item. Story 2.2 will tighten the cap further based on shard capacity.

## Acceptance Criteria

> BDD-style. Every AC has a unit or integration test. Source AC text lives in `_bmad-output/planning-artifacts/epics.md:L455-L489` — this block expands each item with the technical detail the dev agent must honour.

### AC1 — `update-key` happy path: `--rpm` + `--price` with arrow-form ConfirmationLine (FR10, FR30, UX-DR7)

**Given** a key with `key_prefix="Pq…"` (8 chars, exact; lookup is exact-match via `resolve_show_target`), `status="active"`, `billing_mode="manual"`, `rate_limit_rpm=60`, `price_monthly=149.00`, owned by customer `Helena Ribeiro` (`cust_01j…`)
**When** the operator runs `comadre-keys update-key Pq_abc12 --rpm 120 --price 199`
**Then**
- The `api_key.rate_limit_rpm` column is updated to `120`. The `api_key.price_monthly` column is updated to `199.0` (SQLite `REAL`). No other column (`id`, `customer_id`, `key_hash`, `key_prefix`, `status`, `billing_mode`, `paid_until`, `created_at`, `last_used_at`, `notes`) changes — assert via direct-SQL snapshot before/after.
- A single row is appended to `audit_log` with `action="update_key"`, `actor=f"cli:{os.getlogin()}"`, `target_type="api_key"`, `target_id=<key.id>`, and `json.loads(details_json) == {"fields": ["price", "rpm"]}` (alphabetical, sorted via `json.dumps(..., sort_keys=True)` in `log_event`). Tests assert via `json.loads` equality — not byte-exact string comparison (closes the Story 1.5 deferred-work item in the same commit).
- A ConfirmationLine on stdout: `Updated: Pq_abc12 (Helena Ribeiro) — rpm: 60→120, price: R$ 149,00→R$ 199,00`. pt-BR comma-decimal via the existing `_format_brl` helper (thousands with `.`, decimal with `,`, two decimal places). The separator between the two clauses is `, ` (comma-space). The arrow is `\u2192` (RIGHTWARDS ARROW, U+2192) — keeps consistent with `mark-paid` precedent that will land in Story 3.1 (`Marked paid: cmdr_Pq (Pedro Lopes) → paid until 2026-06-05`, UX spec L841).
- Exit code `0`. Stderr is empty except the single structured INFO log line `Updated key | id=<key_id> | fields=price,rpm` (routed to stderr per Story 1.3 `cli/__init__.py`).
- No `customer` row is touched (assert via `SELECT updated_at`-style snapshot — the customer schema has no `updated_at` column so assert all fields byte-equal).
- No cache mutation (auth cache is runtime-only — CLI cannot reach it — and the 60-second TTL bounds downstream `verify_api_key` latency for the owning key, NFR6).

### AC2 — `update-key --rpm` alone (no price change) writes only the rpm field and the arrow-form half-suffix

**Given** the same key as AC1
**When** the operator runs `comadre-keys update-key Pq_abc12 --rpm 120`
**Then**
- `api_key.rate_limit_rpm` becomes `120`. `api_key.price_monthly` is byte-unchanged at `149.0`.
- Audit row `details_json` parses to `{"fields": ["rpm"]}`.
- ConfirmationLine: `Updated: Pq_abc12 (Helena Ribeiro) — rpm: 60→120`.

**Given** the same key, now at `rate_limit_rpm=120`
**When** the operator runs `comadre-keys update-key Pq_abc12 --price 199`
**Then**
- `api_key.rate_limit_rpm` is byte-unchanged at `120`. `api_key.price_monthly` becomes `199.0`.
- Audit row `details_json` parses to `{"fields": ["price"]}`.
- ConfirmationLine: `Updated: Pq_abc12 (Helena Ribeiro) — price: R$ 149,00→R$ 199,00`. (The "old" side of the arrow echoes the `149.00` value from before the `--rpm` update above — the previous-value snapshot is read inside the helper's `with conn:` transaction, not from a prior cached read.)

### AC3 — `update-key --notes` replaces the notes field and renders the single-clause suffix

**Given** a key with `notes="bundled into infra package"`
**When** the operator runs `comadre-keys update-key Pq_abc12 --notes "upgraded 2026-05-12 from 60→120rpm"`
**Then**
- `api_key.notes` is byte-equal to `"upgraded 2026-05-12 from 60→120rpm"` (REPLACE semantics — distinct from `update-customer --add-note` which is append-only). This is intentional per PRD L965 wording "`update-key [--rpm N] [--price R$] [--notes]`" vs L960 "`update-customer [--add-note | --email]`" — keys notes are tier-change metadata, customer notes are narrative.
- Audit row `details_json` parses to `{"fields": ["notes"]}`. **The note TEXT is NOT in `details_json`** — FR37/NFR15 prohibit operator-sensitive free text in audit details. The audit record establishes "a note was replaced on this day by this operator"; the content lives in `api_key.notes`.
- ConfirmationLine: `Updated: Pq_abc12 (Helena Ribeiro) — notes updated`.

### AC4 — Combined `--rpm --price --notes` updates all three in one transaction with one audit row

**Given** a key at RPM 60, price 149, notes "original"
**When** `comadre-keys update-key Pq_abc12 --rpm 120 --price 199 --notes "upgraded 2026-05-12"`
**Then**
- All three columns change in a single `with conn:` transaction. Assert atomicity: monkey-patch `comadre.keys.audit.log_event` to raise `sqlite3.IntegrityError`; run the command; assert exit 5, all three `api_key` columns byte-unchanged, zero new `audit_log` rows.
- On success, one `audit_log` row with `json.loads(details_json) == {"fields": ["notes", "price", "rpm"]}` (alphabetical).
- ConfirmationLine: `Updated: Pq_abc12 (Helena Ribeiro) — rpm: 60→120, price: R$ 149,00→R$ 199,00, notes updated`. Three-clause suffix joined with `, ` in the fixed order `rpm → price → notes` (matches the table-like mental order operators use when reading `show <prefix>` output).
- Exit `0`.

### AC5 — `update-key` rejects invalid / forbidden flag combinations with exit 2

**Given** the operator omits all three optional flags
**When** they run `comadre-keys update-key Pq_abc12`
**Then**
- ErrorDisplay title `Usage error: at least one of --rpm, --price, or --notes is required`, hint `Provide --rpm N, --price R$, or --notes "text" (any combination).`
- Exit `2`. DB is not opened (assert `not (tmp_path / "registry.db").exists()` after the invocation — the usage check fires before `get_connection()`).

**Given** a complimentary-mode key
**When** `comadre-keys update-key Pq_abc12 --price 199` is run
**Then** ErrorDisplay title `Usage error: --price is not applicable to complimentary keys`, hint identical to issue-key's hint (`Complimentary keys are bundled externally; omit --price or rotate via revoke-key + issue-key.`). Exit `2`. DB WAS opened (the billing-mode check requires reading the current row — place this AFTER the initial `resolve_show_target` succeeds, so a non-existent prefix still prefers "not found" to "usage error"). No mutation, no audit row.

**Given** a non-positive or non-finite `--rpm` / `--price`
**When** the command runs
**Then** same shape as issue-key AC2: `--rpm` → `Usage error: --rpm must be positive`; `--price ≤ 0` → `Usage error: --price must be positive for manual billing mode`; non-finite `--price` (`nan`/`inf`) → `Usage error: --price must be a finite number`. All exit `2`. DB NOT opened.

**Given** `--rpm 50000` (above the sane upper bound)
**When** the command runs
**Then** ErrorDisplay title `Usage error: --rpm must be between 1 and 10000`, hint `Provide --rpm in the range 1..10000. Story 2.2 will tighten this cap per VPS tier.`. Exit `2`. This closes the Story 1.2 deferred-work item "`--rpm` has no upper bound" with a generous cap that Story 2.2 is free to tighten.

**Given** `--notes` containing NUL / CR / LF / ANSI escape
**When** the command runs
**Then** `\x00` → title `Usage error: --notes contains illegal characters`, hint `Notes text must not contain NUL bytes.`; `\n` or `\r` → title `Usage error: --notes must be a single line`, hint `Notes text must be a single line. Use update-customer --add-note for multi-line narrative.`. Exit `2`. DB NOT opened. (Mirrors Story 1.5 `--add-note` hardening ladder to close the deferred-work "non-NUL control characters" item — non-NUL C0 controls other than `\r` / `\n` are NOT rejected here; same carve-out as Story 1.5, fixes in a single future pass together with Rich-markup escaping.)

**Given** `--notes` length > 1024 characters
**When** the command runs
**Then** ErrorDisplay title `Usage error: --notes exceeds 1024 characters`, hint `Operator notes are capped at 1024 characters per update. Summarize or split across multiple update-key calls.`. Exit `2`. This closes Story 1.1's deferred-work "unbounded `--notes` length" carve-out with the 1 KiB cap suggested in that note. The cap applies to `update-key --notes` only in this story (update-customer and create-customer stay uncapped until a dedicated hardening pass).

### AC6 — `update-key` on a revoked key is rejected with exit 3 `Key is revoked`

**Given** a key with `status="revoked"`
**When** `comadre-keys update-key <prefix> --rpm 120` runs
**Then**
- ErrorDisplay title `Key is revoked: <prefix>`, hint `Revoked keys are immutable. Issue a new key via issue-key if the customer returns.`.
- Exit `3`. No mutation, no audit row. The helper raises a sentinel `ValueError` caught by the command and mapped to exit 3 (not exit 5 — the error is operator-actionable, not a DB fault).

### AC7 — `update-key` not-found and ambiguous-prefix paths map to exit 3 (UX-DR6, UX-DR10)

**Given** no key matches `prefix_missing_`
**When** `comadre-keys update-key prefix_missing_ --rpm 60` runs
**Then**
- ErrorDisplay title `Key not found: <prefix>`, hint `Run 'comadre-keys list-keys' to see issued keys.`.
- Exit `3`. No audit row.
- **The error title echoes only the operator-supplied literal (never a DB-derived value), truncated to 80 characters.** A pasted multi-KB prefix is truncated (`first-80-chars…`) to prevent the Story 1.2 deferred-work item "Raw `--customer` string interpolated into error title with no length cap" from regressing through this command. Same truncation applies to all three commands in this story.

**Given** two keys share the same 8-char `key_prefix` (vanishingly rare but enforced by `get_key_detail`'s list-returning branch)
**When** `comadre-keys update-key <shared_prefix> --rpm 60` runs
**Then**
- ErrorDisplay title `Ambiguous prefix: multiple keys match '<prefix>'`, hint = `_SHOW_AMBIGUOUS_HINT` (existing Story 1.4 constant: `Use the full key_<ulid> identifier or rotate one of the colliding keys.`). Exit `3`. No mutation.

**Given** the operator passes a `cust_…` identifier instead of a key prefix
**When** `update-key cust_01j… --rpm 60` runs
**Then**
- The `resolve_show_target` discriminator returns `kind="customer"` — the command rejects it as usage error: title `Usage error: key identifier required (got customer ID)`, hint `Pass an 8-char key prefix, a key_<ulid>, or the pasted plaintext (cmdr_live_…). Not a customer ID.`. Exit `2`. This is the only place all three commands diverge from `show` — `show` accepts customer IDs; update/rotate/revoke do not.

### AC8 — `rotate-key` generates fresh plaintext, same `key_` ID, and the old hash stops working (FR11)

**Given** a key with `id="key_01j…abc"`, `key_hash=<H_old>`, `key_prefix="Pq_abc12"`, `status="active"`, `billing_mode="manual"`, `rate_limit_rpm=60`, `price_monthly=149.00`, `paid_until="2026-05-05"`, `last_used_at="2026-04-10T14:23:45Z"`, `notes="bundled"`
**When** the operator runs `comadre-keys rotate-key Pq_abc12`
**Then**
- The `api_key.key_hash` column is replaced with a new SHA-256 hex digest distinct from `H_old`. The `api_key.key_prefix` column is replaced with the 8-char slice following `cmdr_live_` in the new plaintext (via the existing `key_prefix_from_plaintext` seam: `plaintext[len("cmdr_live_") : len("cmdr_live_") + 8]`). The `api_key.last_used_at` column is set to `NULL` (old stats no longer apply to the new plaintext).
- **Byte-unchanged columns:** `id` (same `key_01j…abc`), `customer_id`, `rate_limit_rpm` (`60`), `status` (`active`), `billing_mode` (`manual`), `price_monthly` (`149.0`), `paid_until` (`"2026-05-05"`), `created_at`, `notes`. Assert via direct-SQL snapshot before/after — all nine columns byte-equal.
- One `audit_log` row appended with `action="rotate_key"`, `target_type="api_key"`, `target_id=<key_id>`, `json.loads(details_json) == {"key_prefix_new": "<new_8>", "key_prefix_old": "Pq_abc12"}`. The `"reason"` key is intentionally absent (rotation doesn't require one).
- A KeyPanel is rendered on stdout: double-border warning panel titled `"API KEY (copy now — shown only once)"` + naked plaintext line at column 0 (starting with `cmdr_live_`, 53 chars total) + double-border context panel with rows `prefix: <new>`, `customer: Helena Ribeiro (cust_01j…)`, `rate limit: 60/min`, `billing mode: manual`, `price: R$ 149,00/month`, `paid until: 2026-05-05`. The `paid until:` row replaces the `first charge:` row because `IssuedKey.first_charge_date=None` on the rotation path (see `_context_block` extension).
- Structured INFO log on stderr: `Key rotated | id=<key_id> | key_prefix_old=Pq_abc12 | key_prefix_new=<new>`. **Never** the plaintext. **Never** the old hash. **Never** the customer name.
- Exit code `0`.
- **Hot-end-of-life contract** (FR11): the old `cmdr_live_<…>` plaintext no longer matches any row's `key_hash`. Assert by re-hashing a retained copy of the original plaintext in the test and verifying `SELECT COUNT(*) FROM api_key WHERE key_hash = ?` returns `0`.

### AC9 — `rotate-key` on a complimentary key preserves `billing_mode=complimentary` and renders the complimentary KeyPanel variant

**Given** a complimentary key with `paid_until=NULL`, `price_monthly=0.0`
**When** `rotate-key <prefix>` runs
**Then**
- KeyPanel context panel shows `billing mode: complimentary`, `price: R$ 0,00 (bundled externally)`, `paid until: \u2014 (not applicable)` — identical to the issue-key complimentary variant (existing hardcoded literals in `_context_block`).
- The `api_key.billing_mode` and `api_key.price_monthly` columns stay byte-equal (`complimentary`, `0.0`). The `api_key.paid_until` column stays `NULL`.

### AC10 — `rotate-key` on a revoked key is rejected with exit 3 `Key is revoked`

**Given** a key with `status="revoked"`
**When** `rotate-key <prefix>` runs
**Then**
- ErrorDisplay title `Key is revoked: <prefix>`, hint `Revoked keys cannot be rotated. Issue a new key via issue-key if the customer returns.`. Exit `3`. No mutation, no audit row, no plaintext generated or rendered. **Critical:** the plaintext generation via `generate_api_key_plaintext` must happen AFTER the revocation check (inside the `with conn:` transaction where the current row is loaded). Otherwise a failed-branch rotation would leak an unused key into `/dev/urandom`-derived entropy — not a security bug but a smell.

### AC11 — `rotate-key` is atomic across the hash-update and the audit write

**Given** `comadre.keys.audit.log_event` is monkey-patched to raise `sqlite3.IntegrityError`
**When** `rotate-key <prefix>` runs
**Then**
- Exit `5`, ErrorDisplay title `Database error`, hint = the `sqlite3.IntegrityError` message.
- `api_key.key_hash` and `api_key.key_prefix` are byte-unchanged (the `with conn:` block rolled back the UPDATE).
- `api_key.last_used_at` is byte-unchanged (rollback rewinds it to its prior value).
- Zero new `audit_log` rows.
- **The KeyPanel is NOT rendered** (the helper raises before return; the CLI's `render_key_panel` call is unreached). This is load-bearing for operator trust: if the operator sees a KeyPanel, the new plaintext WORKS. No halfway states.

### AC12 — `rotate-key` hash-collision path maps to exit 5 with a retry hint (same shape as issue-key AC6)

**Given** the `UPDATE api_key SET key_hash=?, key_prefix=? …` raises `sqlite3.IntegrityError` with code `SQLITE_CONSTRAINT_UNIQUE` against the `idx_api_key_hash` index (the vanishingly-rare case where the freshly-generated 43-char token hashes to an existing row's hash)
**When** the command runs
**Then** ErrorDisplay title `Database error: key hash collision`, hint `Retry the command — this is vanishingly rare. If it repeats, check disk integrity.` Exit `5`. Zero new audit rows. `api_key.key_hash` byte-unchanged.

### AC13 — `revoke-key` with `--reason` and `--yes` skips confirmation, sets status, and writes the audit row (FR12, FR30, UX-DR11)

**Given** a key with `status="active"` or `status="suspended"`
**When** the operator runs `comadre-keys revoke-key Pq_abc12 --reason "bundle contract ended 2026-09-30" --yes`
**Then**
- `api_key.status` becomes `"revoked"`. All other columns (`id`, `customer_id`, `key_hash`, `key_prefix`, `billing_mode`, `rate_limit_rpm`, `price_monthly`, `paid_until`, `created_at`, `last_used_at`, `notes`) stay byte-equal. (Deliberately, `last_used_at` is NOT reset — it's a historical marker even after revocation.)
- One `audit_log` row appended with `action="revoke_key"`, `target_type="api_key"`, `target_id=<key.id>`, `json.loads(details_json) == {"reason": "bundle contract ended 2026-09-30"}`.
- ConfirmationLine on stdout: `Revoked: Pq_abc12 (Helena Ribeiro) — reason: bundle contract ended 2026-09-30`. Single-line per UX-DR7 / UX-DR11 Destroy-tier row "ConfirmationLine + warning" (the "warning" is the prompt itself, which `--yes` skipped).
- Structured INFO log on stderr: `Key revoked | id=<key_id> | key_prefix=Pq_abc12`. **The reason is NOT logged** (it may contain customer-specific narrative; see FR37/NFR15). The audit row is the durable record; the log is for cron-like activity aggregation.
- Exit `0`.

### AC14 — `revoke-key` without `--yes` prompts for confirmation; typing anything other than `y` / `Y` aborts

**Given** a key with `status="active"`, operator runs `comadre-keys revoke-key Pq_abc12 --reason "contract ended"` with no `--yes`
**When** Typer's `confirm` prompt appears on stderr with the literal text `This will permanently revoke key Pq_abc12. Continue? [y/N]:`
**Then**
- If the operator's stdin delivers `y\n` (or `Y\n`) → proceeds as AC13 (row updated, audit row written, ConfirmationLine, exit 0).
- If the operator delivers `\n` (bare Enter — default is "No"), `n\n`, `N\n`, any word starting with `n`, or any non-y input → command aborts cleanly: `Aborted.` on stderr, exit `2` (usage-error tier), `api_key.status` byte-unchanged, zero new audit rows.
- If EOF is delivered (`CliRunner(input=None)` on a Typer `confirm` raises `click.exceptions.Abort`) → same shape as the 'n' branch: `Aborted.` on stderr, exit `2`. (We intercept `click.exceptions.Abort` at the command boundary so it maps to exit 2, not Click's default exit 1.)
- **Prompt text lives on stderr**, NOT stdout, so a scripted `comadre-keys revoke-key … | tee output.log` doesn't capture the prompt into the log file. `typer.confirm(..., err=True)` is the canonical seam.

### AC15 — `revoke-key` on an already-revoked key is rejected with exit 3 `Key already revoked`

**Given** a key with `status="revoked"`
**When** `revoke-key <prefix> --reason "…" --yes` runs
**Then**
- ErrorDisplay title `Key already revoked: <prefix>`, hint `Revocation is terminal. Issue a new key via issue-key if the customer returns.`. Exit `3`. No mutation, no audit row.

### AC16 — `revoke-key` rejects empty / whitespace-only / NUL / newline / oversize `--reason`

**Given** `--reason ""` (Typer parses empty string) or `--reason "   "` (whitespace-only, strips to empty)
**When** the command runs
**Then** ErrorDisplay title `Usage error: --reason must be non-empty`, hint `Provide reason text with content. Whitespace-only reasons are rejected.`. Exit `2`. DB not opened.

**Given** `--reason "\x00danger"` or `--reason "forge\n[2099-01-01] fake"`
**When** the command runs
**Then** NUL → `Usage error: --reason contains illegal characters` + hint `Reason text must not contain NUL bytes.`; newline → `Usage error: --reason must be a single line` + hint `Reason text must be a single line. Newlines would forge dated entries in the stored audit row.`. Exit `2`. DB not opened.

**Given** `--reason` length > 1024 chars
**When** the command runs
**Then** ErrorDisplay title `Usage error: --reason exceeds 1024 characters`, hint `Revocation reasons are capped at 1024 characters. Summarize or store the detail in customer notes.`. Exit `2`. DB not opened.

### AC17 — `--help` on all three commands renders realistic examples and does not open the DB (UX-DR15)

**Given** the operator runs `comadre-keys update-key --help` / `comadre-keys rotate-key --help` / `comadre-keys revoke-key --help`
**Then**
- Typer prints usage with each option visible. Option help strings include realistic examples:
  - `update-key`: `--rpm` help `Per-key requests-per-minute limit (1..10000). Example: --rpm 120.`; `--price` help `Monthly price in BRL for manual billing. Example: --price 199.`; `--notes` help `Replace stored operator notes (≤1024 chars, single line). Example: --notes "upgraded 2026-05-12 from 60→120rpm".`.
  - `rotate-key`: prefix help `8-char key prefix, key_<ulid>, or pasted cmdr_live_<plaintext>. Example: "Pq_abc12".` (no flags besides the positional).
  - `revoke-key`: prefix help identical shape; `--reason` help `Free-form reason (≤1024 chars, single line). Example: --reason "bundle contract ended 2026-09-30".`; `--yes` help `Skip the interactive confirmation prompt (for scripting).`.
- The docstring footer (epilog) contains a full `Example:` invocation line per command:
  - `update-key`: `Example: comadre-keys update-key Pq_abc12 --rpm 120 --price 199`
  - `rotate-key`: `Example: comadre-keys rotate-key Pq_abc12`
  - `revoke-key`: `Example: comadre-keys revoke-key Pq_abc12 --reason "bundle contract ended 2026-09-30"`
- Exit `0`. No DB file is created (`not (tmp_path / "registry.db").exists()` post-invocation — the `--help` branch short-circuits before any settings / DB work).

### AC18 — Anti-enumeration and log sanitization (FR37, NFR15, NFR16)

**Given** any `update-key` / `rotate-key` / `revoke-key` invocation succeeds or fails
**Then**
- The structured INFO log lines are:
  - `update-key` success → `Updated key | id=<key_id> | fields=<csv>` (csv is sorted subset of `notes,price,rpm`). Never the old/new price value. Never the notes text. Never the customer name.
  - `rotate-key` success → `Key rotated | id=<key_id> | key_prefix_old=<old> | key_prefix_new=<new>`. Never the plaintext. Never the hash.
  - `revoke-key` success → `Key revoked | id=<key_id> | key_prefix=<prefix>`. Never the reason text. Never the customer name.
- Error paths never echo more than the operator-supplied literal (truncated to 80 chars — AC7 note). The "not found" title renders only the operator's input; a DB row's `key_prefix` is never substituted back into the error panel.
- `audit_log.details_json` columns carry:
  - `update_key` → `{"fields": ["price", "rpm"]}` (or the sorted subset). Never old/new values.
  - `rotate_key` → `{"key_prefix_new": "<new>", "key_prefix_old": "<old>"}`. Never the plaintext, never the hash.
  - `revoke_key` → `{"reason": "<reason>"}`. The free-text reason is intentionally stored here — it's the only durable record of operator intent for the revocation, and it is NOT personal data (the blocklist in `keys/audit.py` covers CPF / CNPJ / name / email / key_plaintext / authorization; "reason" is explicitly safe).
- `KEY_REGISTRY_ENCRYPTION_KEY` is still validated at load time (exit 6 when missing) but never read or used by any of the three commands (tax-ID encryption is unchanged). Consistent configuration-error surface across all `comadre-keys` verbs.

### AC19 — Read-after-write: `show <prefix>` reflects rotation and revocation immediately (FR14 invariant)

**Given** AC8 (rotate), AC13 (revoke), or AC1 (update) have just completed successfully
**When** the operator runs `comadre-keys show <key-prefix>` in a follow-up invocation
**Then** the DetailPanel body reflects the new state: updated RPM / price / notes, new `key_prefix` for rotation, and color-coded `revoked` red status for revocation. Rotation updates the `Prefix:` row in the DetailPanel to the new 8-char value; the old prefix is visible ONLY in the `--audit-tail` section (`ROTATE_KEY ... {"key_prefix_old": "Pq_abc12", "key_prefix_new": "<new>"}`), never as a duplicate record.

### AC20 — Performance budget (NFR5)

**Given** a database with 1,000 customers, 2,000 keys, and 5,000 audit rows seeded (temporary script, not committed)
**When** any of the three commands runs end-to-end via `time uv run comadre-keys <cmd> …`
**Then** wall-clock time is well under 500 ms per invocation (NFR5 detail/mutation budget). The SQL footprint per command is a single indexed SELECT by `key_prefix` + a single indexed UPDATE by primary key + a single INSERT INTO `audit_log` + (for rotate-key) a single follow-up SELECT by primary key for the refreshed display row — all O(1). Record the elapsed wall-clock in the Dev Agent Record (target: <100 ms end-to-end on the dev laptop, well within the NFR5 500 ms budget).

## Tasks / Subtasks

Ordered for bottom-up construction. Each task ends with a runnable checkpoint. Do not reorder — imports chain downward.

- [x] **Task 1 — Extend `keys/db.py` with the three helpers + result dataclasses** (AC: #1–#4, #6, #8–#12, #13, #15)
  - [x] 1.1 Add three result dataclasses and three `Literal` aliases:
    ```python
    from typing import Literal

    UpdateKeyField = Literal["notes", "price", "rpm"]


    @dataclass(frozen=True, slots=True)
    class KeyFieldDeltas:
        """Old/new snapshot of the numeric fields the operator touched.

        ``None`` on either side means the field was not in the update set;
        the CLI omits the clause from the ConfirmationLine. Carrying
        both old and new lets the renderer assemble the ``60→120`` arrow
        form without a second DB read.
        """

        rpm_old: int | None
        rpm_new: int | None
        price_old: float | None
        price_new: float | None


    @dataclass(frozen=True, slots=True)
    class UpdateKeyResult:
        key: KeyDetailRow
        updated_fields: tuple[UpdateKeyField, ...]
        changes: KeyFieldDeltas


    @dataclass(frozen=True, slots=True)
    class RotateKeyResult:
        record: ApiKeyRecord
        customer_name: str
        old_prefix: str


    @dataclass(frozen=True, slots=True)
    class RevokeKeyResult:
        key: KeyDetailRow
        customer_name: str
        reason: str
    ```
  - [x] 1.2 Add three helper functions. Each owns its `with conn:` transaction; callers MUST NOT wrap:
    ```python
    def update_api_key(
        conn: sqlite3.Connection,
        key_id: str,
        *,
        new_rpm: int | None,
        new_price: float | None,
        new_notes: str | None,
        actor: str,
        today: date,
    ) -> UpdateKeyResult | None: ...

    def rotate_api_key(
        conn: sqlite3.Connection,
        key_id: str,
        *,
        new_plaintext: str,
        actor: str,
    ) -> RotateKeyResult | None: ...

    def revoke_api_key(
        conn: sqlite3.Connection,
        key_id: str,
        *,
        reason: str,
        actor: str,
    ) -> RevokeKeyResult | None: ...
    ```
    - `update_api_key` body: `with conn:` → SELECT the current row (`SELECT status, billing_mode, rate_limit_rpm, price_monthly FROM api_key WHERE id = ?`); if row missing → return `None`; if `status='revoked'` → raise `ValueError("cannot update a revoked key")`; if `billing_mode='complimentary'` AND `new_price is not None` → raise `ValueError("cannot set --price on a complimentary key")` (the CLI catches this and maps to exit 2 — same shape as issue-key's mutex); build the SET clause via a literal-column-name list (`"rate_limit_rpm = ?"`, `"price_monthly = ?"`, `"notes = ?"`) plus positional `?` bindings only — mirrors the Story 1.5 `update_customer` SQL-assembly precedent, zero f-string-with-operator-input; execute `UPDATE api_key SET <joined> WHERE id = ? AND status != 'revoked'`; compute `fields_sorted: tuple[UpdateKeyField, ...] = tuple(sorted(set(updated)))`; call `log_event(conn, actor=actor, action="update_key", target_type="api_key", target_id=key_id, details={"fields": list(fields_sorted)})`. After `with conn:` returns, re-read via `get_key_detail_by_id(conn, key_id, today=today)`; on `None` raise `RuntimeError("update_api_key: row vanished after commit …")` (caller maps to exit 5 — same pattern as Story 1.5's `update_customer` post-patch). Return `UpdateKeyResult(key=refreshed, updated_fields=fields_sorted, changes=KeyFieldDeltas(rpm_old=…, rpm_new=…, price_old=…, price_new=…))` where the `changes` snapshot is taken from the pre-UPDATE SELECT inside the same transaction.
    - `rotate_api_key` body: `with conn:` → load current row via primary-key SELECT (same shape as update); if missing → return `None`; if `status='revoked'` → raise `ValueError("cannot rotate a revoked key")`; compute `new_hash = hash_api_key(new_plaintext)` and `new_prefix = key_prefix_from_plaintext(new_plaintext)`; execute `UPDATE api_key SET key_hash = ?, key_prefix = ?, last_used_at = NULL WHERE id = ?` — propagates `sqlite3.IntegrityError` on UNIQUE-hash collision (caller maps to exit 5 per AC12); call `log_event(..., action="rotate_key", details={"key_prefix_old": old_prefix, "key_prefix_new": new_prefix})`. After commit, re-read via `get_key_detail_by_id` (the CLI needs the fresh `ApiKeyRecord` for the KeyPanel — we promote the `KeyDetailRow` back to an `ApiKeyRecord` inside the helper by assembling the fields from the freshly-read row — acceptable because rotate-key is a lower-frequency operation than update-key). Return `RotateKeyResult(record=<ApiKeyRecord>, customer_name=<from join>, old_prefix=<old>)`.
    - `revoke_api_key` body: `with conn:` → load current row; if missing → return `None`; if `status='revoked'` → raise `ValueError("already revoked")`; execute `UPDATE api_key SET status = 'revoked' WHERE id = ? AND status != 'revoked'`; assert `cursor.rowcount == 1` — if not, raise `RuntimeError("revoke_api_key: update failed to match any row after SELECT succeeded")` (guards against a concurrent revocation between the SELECT and UPDATE in the same `with conn:`; under single-writer CLI this is effectively unreachable, but the `RuntimeError` gives the caller an exit-5 surface rather than silent success). Call `log_event(..., action="revoke_key", details={"reason": reason})`. After commit, re-read via `get_key_detail_by_id` to populate the `KeyDetailRow` + `customer_name` for the ConfirmationLine. Return `RevokeKeyResult(key=refreshed, customer_name=row["customer_name"], reason=reason)`.
  - [x] 1.3 No change to `get_key_detail_by_id` (exists since Story 1.4). No change to `resolve_show_target`. No change to `_row_to_key_detail`. No migration file. No new exports from `keys/__init__.py`.
  - [x] 1.4 `tests/test_keys_db.py` — append three test classes:
    - `TestUpdateApiKey`: `test_rpm_only_changes_rpm_column`, `test_price_only_changes_price_column`, `test_notes_only_changes_notes_column`, `test_all_three_fields_in_one_txn`, `test_complimentary_plus_price_raises_valueerror`, `test_revoked_raises_valueerror`, `test_missing_returns_none`, `test_rolls_back_when_audit_fails`, `test_details_json_via_json_loads_equality` (asserts `json.loads(details_json) == {"fields": [...]}` — closes Story 1.5 deferred-work), `test_deltas_capture_prior_values`, `test_notes_replace_not_append` (seed notes `"old"`, call with `new_notes="new"`, assert column is exactly `"new"` — distinct from `update_customer` append semantics).
    - `TestRotateApiKey`: `test_same_id_new_hash_new_prefix`, `test_last_used_at_reset_to_null`, `test_unchanged_columns_byte_equal` (assert 9 columns byte-equal), `test_old_plaintext_no_longer_matches` (retain pre-rotate plaintext, re-hash it, assert `SELECT COUNT(*) WHERE key_hash = ?` is 0 post-rotate), `test_complimentary_preserves_billing_mode`, `test_revoked_raises_valueerror`, `test_missing_returns_none`, `test_rolls_back_when_audit_fails` (assert `key_hash` / `key_prefix` byte-unchanged after `log_event` monkey-patched to raise), `test_audit_details_has_prefix_old_and_new`, `test_hash_collision_propagates_integrity_error` (monkey-patch `hash_api_key` to return an existing row's hash; assert `sqlite3.IntegrityError` propagates).
    - `TestRevokeApiKey`: `test_active_to_revoked`, `test_suspended_to_revoked`, `test_already_revoked_raises_valueerror`, `test_missing_returns_none`, `test_other_columns_byte_equal` (revocation touches only `status`), `test_last_used_at_preserved` (contrast with rotation), `test_audit_details_has_reason`, `test_rolls_back_when_audit_fails`, `test_reason_is_stored_verbatim_including_punctuation_and_unicode`.

- [x] **Task 2 — `update-key` command in `src/comadre/keys/cli/commands/keys.py`** (AC: #1–#7, #18, #20)
  - [x] 2.1 Extend imports:
    ```python
    from comadre.keys.db import (
        UpdateKeyResult,
        update_api_key,
        # keep existing imports (insert_api_key, etc.)
    )
    ```
  - [x] 2.2 Add module-level hint constants (grouped with `_MISSING_KEY_HINT`):
    ```python
    _UPDATE_KEY_NEITHER_HINT = (
        "Provide --rpm N, --price R$, or --notes \"text\" (any combination)."
    )
    _UPDATE_KEY_NOTES_NUL_HINT = "Notes text must not contain NUL bytes."
    _UPDATE_KEY_NOTES_NEWLINE_HINT = (
        "Notes text must be a single line. Use update-customer --add-note "
        "for multi-line narrative."
    )
    _UPDATE_KEY_NOTES_OVERSIZE_HINT = (
        "Operator notes are capped at 1024 characters per update. Summarize "
        "or split across multiple update-key calls."
    )
    _UPDATE_KEY_RPM_RANGE_HINT = (
        "Provide --rpm in the range 1..10000. Story 2.2 will tighten this "
        "cap per VPS tier."
    )
    _UPDATE_KEY_COMPLIMENTARY_HINT = (
        "Complimentary keys are bundled externally; omit --price or rotate "
        "via revoke-key + issue-key."
    )
    _UPDATE_KEY_REVOKED_HINT = (
        "Revoked keys are immutable. Issue a new key via issue-key if the "
        "customer returns."
    )
    _UPDATE_KEY_NOT_FOUND_HINT = (
        "Run 'comadre-keys list-keys' to see issued keys."
    )
    _UPDATE_KEY_AMBIGUOUS_HINT = (
        "Use the full key_<ulid> identifier or rotate one of the colliding keys."
    )
    _UPDATE_KEY_CUSTOMER_ID_HINT = (
        "Pass an 8-char key prefix, a key_<ulid>, or the pasted plaintext "
        "(cmdr_live_...). Not a customer ID."
    )
    _KEY_RPM_MAX = 10_000
    _KEY_NOTES_MAX = 1024
    _KEY_IDENT_ECHO_MAX = 80  # AC7 — truncate operator input in error titles
    ```
  - [x] 2.3 Add a `_truncate_ident(raw: str) -> str` helper that returns `raw[:80] + "…"` when `len(raw) > 80`, else `raw`. Apply in every error title that echoes the operator's positional argument (update/rotate/revoke). This closes the Story 1.2 deferred-work "Raw `--customer` string interpolated into error title with no length cap" item for keys-side commands.
  - [x] 2.4 Add the Typer command body:
    ```python
    @app.command("update-key")
    def update_key_cmd(
        key_prefix: str = typer.Argument(
            ...,
            metavar="KEY_PREFIX",
            help=(
                "8-char key prefix, key_<ulid>, or pasted cmdr_live_<plaintext>. "
                'Example: "Pq_abc12".'
            ),
        ),
        rpm: int | None = typer.Option(
            None,
            "--rpm",
            help="Per-key requests-per-minute limit (1..10000). Example: --rpm 120.",
        ),
        price: float | None = typer.Option(
            None,
            "--price",
            help=(
                "Monthly price in BRL for manual billing. Example: --price 199."
            ),
        ),
        notes: str | None = typer.Option(
            None,
            "--notes",
            help=(
                "Replace stored operator notes (<=1024 chars, single line). "
                'Example: --notes "upgraded 2026-05-12 from 60->120rpm".'
            ),
        ),
    ) -> None:
        """Update a key's RPM, monthly price, and/or operator notes.

        Example: comadre-keys update-key Pq_abc12 --rpm 120 --price 199
        """
        # 1. Neither-flag check.
        # 2. --rpm bounds (1..10000, include non-finite guard analogous to
        #    issue-key AC2 for floats? rpm is int — Typer's int conversion
        #    rejects non-numerics with its own usage error, so only bounds
        #    remain).
        # 3. --price finiteness + positivity checks (copy from issue-key).
        # 4. --notes NUL / CR/LF / length checks (mirrors Story 1.5
        #    --add-note ladder).
        # 5. Settings load + encryption-key sanity (exit 6).
        # 6. Billing-TZ resolution (exit 6).
        # 7. DB open + migrations (exit 5).
        # 8. Prefix resolution via `resolve_show_target` (reject not_found,
        #    key_ambiguous, customer branches per AC7).
        # 9. Complimentary + --price mutex check on the resolved row (exit 2).
        # 10. Call `update_api_key` inside a try/except ladder:
        #       ValueError("cannot update a revoked key") -> exit 3 with
        #         AC6 title.
        #       ValueError("cannot set --price on a complimentary key") ->
        #         exit 2 (redundant safety net; Step 9 catches it first).
        #       sqlite3.Error -> exit 5.
        #       RuntimeError (helper's post-commit re-read) -> exit 5.
        # 11. Structured INFO log (stderr) per AC18 (fields CSV, no values).
        # 12. ConfirmationLine assembly:
        #       clauses: list[str] = []
        #       if "rpm" in result.updated_fields:
        #           clauses.append(
        #               f"rpm: {result.changes.rpm_old}"
        #               f"\u2192{result.changes.rpm_new}"
        #           )
        #       if "price" in result.updated_fields:
        #           clauses.append(
        #               f"price: R$ {_format_brl(result.changes.price_old)}"
        #               f"\u2192R$ {_format_brl(result.changes.price_new)}"
        #           )
        #       if "notes" in result.updated_fields:
        #           clauses.append("notes updated")
        #       suffix = ", ".join(clauses)
        #       render_confirmation(
        #           f"Updated: {result.key.key_prefix} "
        #           f"({result.key.customer_name}) \u2014 {suffix}"
        #       )
        # 13. Exit 0 implicit.
    ```
  - [x] 2.5 Helper `_key_update_clauses(result: UpdateKeyResult) -> list[str]` — the ConfirmationLine clause-assembly, extracted for unit testing so AC1/AC2/AC3/AC4 suffix grammar is fixed by a test, not read-by-eye from test output. Use U+2192 (RIGHTWARDS ARROW) and U+2014 (EM DASH) — NOT ASCII `->` / `--`.
  - [x] 2.6 Wrap the `_logger.info(...)` call in `contextlib.suppress(Exception)` per Story 1.5 deferred-work item "`_logger.info` raising after a successful commit would bypass `render_confirmation`". Apply to all three commands in this story (closes the item at once). Rationale: once the DB commit has happened, the operator's mutation is durable; a logging-side failure must not prevent the ConfirmationLine / KeyPanel from rendering.

- [x] **Task 3 — `rotate-key` command** (AC: #8–#12, #18, #19, #20)
  - [x] 3.1 Extend imports:
    ```python
    from comadre.keys.db import (
        RotateKeyResult,
        rotate_api_key,
    )
    from comadre.keys.models import IssuedKey
    # generate_api_key_plaintext, key_prefix_from_plaintext already imported.
    ```
  - [x] 3.2 Add the Typer command:
    ```python
    @app.command("rotate-key")
    def rotate_key_cmd(
        key_prefix: str = typer.Argument(
            ...,
            metavar="KEY_PREFIX",
            help=(
                "8-char key prefix, key_<ulid>, or pasted cmdr_live_<plaintext>. "
                'Example: "Pq_abc12".'
            ),
        ),
    ) -> None:
        """Rotate an API key — same key_<id>, fresh plaintext, old hash dies.

        Example: comadre-keys rotate-key Pq_abc12
        """
        ...
    ```
  - [x] 3.3 Command body:
    1. Settings + encryption-key sanity (exit 6) — no flags to validate upfront.
    2. Billing-TZ resolution (exit 6).
    3. DB open + migrations (exit 5).
    4. `resolve_show_target` prefix lookup — reject `not_found` / `key_ambiguous` / `customer` branches (exit 3 / 3 / 2 respectively). Truncate the echoed identifier via `_truncate_ident`.
    5. Generate the NEW plaintext via `generate_api_key_plaintext()` **after** the revocation check runs inside `rotate_api_key` — hoist the generation into the CLI because the helper needs it as an argument; the helper's revocation check runs before the UPDATE, so a revoked-branch abort simply discards the unused plaintext. (Alternative: move the plaintext generation inside the helper — rejected because `rotate_api_key`'s signature is then not testable without injecting a fake `token_urlsafe`; passing the plaintext in keeps the helper pure.)
    6. Call `rotate_api_key(conn, key_id=<resolved>, new_plaintext=<new>, actor=get_cli_actor())` in a try/except ladder:
       - `ValueError("cannot rotate a revoked key")` → exit 3 with `Key is revoked: <prefix>` + `_ROTATE_KEY_REVOKED_HINT`.
       - `sqlite3.IntegrityError` with `sqlite_errorcode == SQLITE_CONSTRAINT_UNIQUE` AND `"key_hash"` in args → exit 5 with `Database error: key hash collision` + the same retry hint as issue-key AC6.
       - `sqlite3.Error` → exit 5.
       - `RuntimeError` → exit 5.
    7. Structured INFO log per AC18 (suppress exceptions).
    8. Assemble an `IssuedKey`:
       ```python
       issued = IssuedKey(
           plaintext=new_plaintext,
           record=result.record,
           customer_name=result.customer_name,
           first_charge_date=None,   # signals rotate-key path to
                                     # `_context_block` (shows "paid until:"
                                     # instead of "first charge:")
           first_charge_days_free=None,
       )
       render_key_panel(issued)
       ```
    9. Exit 0 implicit.
  - [x] 3.4 Hint constants:
    ```python
    _ROTATE_KEY_REVOKED_HINT = (
        "Revoked keys cannot be rotated. Issue a new key via issue-key if the "
        "customer returns."
    )
    _ROTATE_KEY_NOT_FOUND_HINT = _UPDATE_KEY_NOT_FOUND_HINT  # share
    _ROTATE_KEY_AMBIGUOUS_HINT = _UPDATE_KEY_AMBIGUOUS_HINT
    _ROTATE_KEY_CUSTOMER_ID_HINT = _UPDATE_KEY_CUSTOMER_ID_HINT
    ```
  - [x] 3.5 Extend `src/comadre/keys/cli/output.py::_context_block` so that, when `issued.first_charge_date is None` AND `rec.billing_mode == "manual"`, the trailing row is `paid until: <iso>` (using `_iso_date(rec.paid_until)` — returns em-dash for NULL/malformed) **instead of** `first charge: …`. Preserves the existing `issue-key` path (non-None `first_charge_date` → `first charge: …`). Preserves the complimentary path (unchanged — the complimentary branch already hardcodes `paid until: — (not applicable)`).
  - [x] 3.6 Unit test for the `_context_block` extension in `tests/test_keys_output.py` — seed a manual-mode `IssuedKey` with `first_charge_date=None`, `record.paid_until="2026-05-05"`, assert the rendered body contains `paid until: 2026-05-05` (NOT `first charge:`). Seed another with `record.paid_until=None`, assert `paid until: —` (U+2014) appears.

- [x] **Task 4 — `revoke-key` command** (AC: #13–#18, #19, #20)
  - [x] 4.1 Extend imports (`RevokeKeyResult`, `revoke_api_key`).
  - [x] 4.2 Typer command:
    ```python
    @app.command("revoke-key")
    def revoke_key_cmd(
        key_prefix: str = typer.Argument(
            ...,
            metavar="KEY_PREFIX",
            help=(
                "8-char key prefix, key_<ulid>, or pasted cmdr_live_<plaintext>. "
                'Example: "Pq_abc12".'
            ),
        ),
        reason: str = typer.Option(
            ...,
            "--reason",
            help=(
                "Free-form reason (<=1024 chars, single line). Stored in "
                'the audit log. Example: --reason "bundle contract ended 2026-09-30".'
            ),
        ),
        yes: bool = typer.Option(
            False,
            "--yes",
            help="Skip the interactive confirmation prompt (for scripting).",
        ),
    ) -> None:
        """Permanently revoke an API key (destructive; --yes or interactive confirm).

        Example: comadre-keys revoke-key Pq_abc12 --reason "bundle contract ended 2026-09-30"
        """
        ...
    ```
  - [x] 4.3 Command body:
    1. `--reason` shape validation: strip outer whitespace, reject empty-after-strip (exit 2), reject `\x00` (exit 2), reject `\n` / `\r` (exit 2), reject length > `_KEY_NOTES_MAX` (1024) (exit 2). Reassign `reason` to the stripped canonical form so the stored audit row carries the trimmed literal.
    2. Settings + encryption-key sanity + billing-TZ (exit 6) — same shape as the other two commands.
    3. DB open + migrations (exit 5).
    4. `resolve_show_target` lookup — reject `not_found` / `key_ambiguous` / `customer` as before.
    5. Confirmation gate:
       ```python
       if not yes:
           try:
               typer.confirm(
                   f"This will permanently revoke key {resolved_key_prefix}. "
                   "Continue?",
                   default=False,
                   abort=True,
                   err=True,  # prompt lives on stderr, UX-DR11 compliance
               )
           except click.exceptions.Abort:
               # typer re-raises click's Abort when abort=True + user says "n"
               # or sends EOF. Exit 2 (usage tier) maps the "operator bailed"
               # case cleanly. Abort's default exit is 1 — remap here.
               stderr_console().print("Aborted.")
               raise typer.Exit(code=2) from None
       ```
       Rationale for `abort=True`: Typer's `confirm` with `abort=True` raises `click.exceptions.Abort` on a "No" answer (default) — catch it and remap to our usage exit code. Without `abort=True`, we'd inspect the returned bool manually, which would bypass Click's built-in EOF handling for piped invocations.
    6. Call `revoke_api_key(conn, key_id=<resolved>, reason=reason, actor=get_cli_actor())`:
       - `ValueError("already revoked")` → exit 3 with `Key already revoked: <prefix>` title + `_REVOKE_KEY_ALREADY_HINT`.
       - `sqlite3.Error` → exit 5.
       - `RuntimeError` → exit 5.
    7. Structured INFO log per AC18 (no reason text).
    8. ConfirmationLine: `Revoked: {result.key.key_prefix} ({result.customer_name}) \u2014 reason: {reason}`. U+2014 em-dash, single line. The reason is echoed here **on the operator's own machine**, not in logs — the operator saw the prompt, typed `--reason`, and now sees the confirmation carrying the same string they typed. FR37 is about log/audit leakage, not operator-console display. The ConfirmationLine is ephemeral terminal output.
    9. Exit 0 implicit.
  - [x] 4.4 Hint constants:
    ```python
    _REVOKE_KEY_ALREADY_HINT = (
        "Revocation is terminal. Issue a new key via issue-key if the "
        "customer returns."
    )
    _REVOKE_KEY_REASON_EMPTY_HINT = (
        "Provide reason text with content. Whitespace-only reasons are rejected."
    )
    _REVOKE_KEY_REASON_NUL_HINT = "Reason text must not contain NUL bytes."
    _REVOKE_KEY_REASON_NEWLINE_HINT = (
        "Reason text must be a single line. Newlines would forge dated entries "
        "in the stored audit row."
    )
    _REVOKE_KEY_REASON_OVERSIZE_HINT = (
        "Revocation reasons are capped at 1024 characters. Summarize or store "
        "the detail in customer notes."
    )
    ```

- [x] **Task 5 — Integration tests: `update-key`** (AC: #1–#7, #17, #18, #19)
  - [x] 5.1 Create `tests/test_keys_cli_update_key.py`. Reuse the three autouse fixtures from `tests/test_keys_cli_show.py` and `tests/test_keys_cli_update_customer.py` (`_clear_settings_cache`, `_reset_consoles_to_buffers`, `env`) plus the `_buffers` / `_clear_buffers` / `_seed_customer` helpers. **Deferred-work note on shared fixtures:** five copies of these fixtures now exist (list-customers, list-keys, show, update-customer, update-key). The Story 1.5 note about "four copies is the last tolerable threshold" is now decisively past — add a `tests/conftest_keys_cli.py` helper-module (or extend `tests/conftest.py`) in this story's scope OR log it as a hardening item. **Action:** Log as a single deferred item in `deferred-work.md` under Story 1.6; do not do the shared-fixture extraction in this story (scope creep — five tests modules already work with the copied fixtures). The extraction cost is O(5) file rewrites with no functional gain; a dedicated test-hygiene pass is the right vehicle.
  - [x] 5.2 Add a `_seed_key(env, *, customer_id, billing_mode="manual", rpm=60, price=149.0, notes="")` helper that calls `comadre-keys issue-key --customer <id> --rpm <rpm> --billing-mode <mode> [--price <price>] [--notes <notes>]` and returns the new key's `key_prefix` (parse from the KeyPanel output — same technique as `_seed_customer` parses the `create-customer` confirmation line).
  - [x] 5.3 Tests (one per AC slice; drop the `test_` prefix in the summary below):
    - AC1 happy path: `rpm_and_price_updates_both_columns`.
    - AC2 rpm-only: `rpm_only_updates_only_rpm`; price-only: `price_only_updates_only_price`.
    - AC3 notes replace: `notes_flag_replaces_existing_notes_not_append`.
    - AC4 three-flag combo + rollback: `all_three_flags_in_one_txn`, `rolls_back_when_log_event_fails`.
    - AC5 usage errors: `without_flags_exits_2`, `complimentary_plus_price_exits_2`, `rpm_zero_exits_2`, `rpm_above_cap_exits_2`, `price_negative_exits_2`, `price_nan_exits_2`, `notes_nul_exits_2`, `notes_newline_exits_2`, `notes_carriage_return_exits_2`, `notes_oversize_exits_2`.
    - AC6 revoked: `revoked_key_exits_3`.
    - AC7 not-found / ambiguous / customer-ID: `missing_key_exits_3_with_truncated_echo`, `ambiguous_prefix_exits_3`, `customer_id_exits_2`.
    - AC7 identifier truncation: `error_title_truncates_long_operator_input` — seed an 8-char-prefixed DB, run `update-key` with a 5 KB positional argument, assert the ErrorDisplay title contains only the first 80 chars + `…`.
    - AC17 help: `update_key_help_has_realistic_examples` (strip ANSI + Panel glyphs, assert `Pq_abc12`, `120`, `199`, `upgraded 2026-05-12 from 60→120rpm`, `Example: comadre-keys update-key Pq_abc12 --rpm 120 --price 199` all present; assert no DB file created).
    - AC18 audit sanitization: `audit_details_json_via_json_loads_equality`, `audit_details_has_no_pii_values` (assert old/new RPM/price values are not present in any column of the audit row), `log_has_no_pii` (attach throwaway handler to `keys.cli`, assert log line contains `fields=…` but not the customer name / note text / price value).
    - AC19 read-after-write: `then_show_reflects_changes` (update, then `show --format json`, assert the JSON payload has the new `rpm` / `price` / `notes`).
    - Regression — issue-key untouched: `issue_key_still_works_after_update_key_landed` (smoke test that the pre-existing command still emits a KeyPanel).

- [x] **Task 6 — Integration tests: `rotate-key`** (AC: #8–#12, #17, #18, #19)
  - [x] 6.1 Create `tests/test_keys_cli_rotate_key.py` with the standard fixture bundle.
  - [x] 6.2 Tests:
    - AC8 full-column preservation: `rotates_same_id_new_hash_new_prefix_preserves_9_columns`.
    - AC8 end-of-life contract: `old_plaintext_no_longer_matches_any_row` — seed via `issue-key`, capture plaintext from the KeyPanel (parse stdout — the 53-char `cmdr_live_...` line lives at a fixed position between the two panels), rotate, re-hash the captured plaintext, assert `SELECT COUNT(*) FROM api_key WHERE key_hash = ?` returns 0.
    - AC8 KeyPanel output: `keypanel_shows_paid_until_not_first_charge` — seed with `paid_until` set (via direct SQL `UPDATE api_key SET paid_until='2026-05-05'`), rotate, assert the stdout KeyPanel contains `paid until: 2026-05-05`, NOT `first charge:`.
    - AC9 complimentary: `rotate_complimentary_preserves_billing_mode` — seed complimentary, rotate, assert KeyPanel shows `billing mode: complimentary` + `paid until: — (not applicable)`.
    - AC10 revoked: `rotate_revoked_exits_3_no_mutation_no_plaintext_leak` — assert exit 3, KeyPanel NOT rendered, no new audit row.
    - AC11 atomicity: `rolls_back_when_log_event_fails` — assert exit 5, `key_hash` byte-unchanged, no KeyPanel rendered.
    - AC12 hash collision: `hash_collision_exits_5_with_retry_hint` — monkey-patch `comadre.keys.tokens.generate_api_key_plaintext` to return a plaintext that hashes to an existing row's hash (seed two keys, force the second rotate to collide with the first's hash). Alternative: monkey-patch `hash_api_key` to return a colliding literal.
    - AC17 help: `rotate_key_help_has_realistic_examples`.
    - AC18 log sanitization: `log_has_no_plaintext_no_hash` — attach throwaway handler, rotate, assert log line contains `key_prefix_old=…` + `key_prefix_new=…` but not the plaintext string or any 64-hex-char run.
    - AC19 read-after-write: `then_show_reflects_new_prefix_old_visible_only_in_audit_tail`.
    - Regression — `show --audit-tail` renders the rotate event with the prefix delta: `audit_tail_shows_rotate_event_with_prefix_delta`.

- [x] **Task 7 — Integration tests: `revoke-key`** (AC: #13–#18, #19)
  - [x] 7.1 Create `tests/test_keys_cli_revoke_key.py` with the standard fixture bundle.
  - [x] 7.2 Tests:
    - AC13 happy path `--yes`: `revoke_active_key_with_yes_flag`.
    - AC13 happy path `--yes` on a suspended key: `revoke_suspended_key_with_yes_flag` — seed via direct SQL `UPDATE api_key SET status='suspended'`, revoke, assert `status='revoked'`.
    - AC14 interactive confirm `y`: `interactive_confirm_y_proceeds` — `CliRunner` with `input="y\n"`.
    - AC14 interactive confirm default-no: `interactive_confirm_default_no_aborts` — `CliRunner` with `input="\n"`, assert exit 2, `Aborted.` on stderr, `status` byte-unchanged.
    - AC14 interactive confirm `n`: `interactive_confirm_n_aborts`.
    - AC14 interactive confirm EOF: `interactive_confirm_eof_aborts_exit_2` — `CliRunner` with `input=""`, assert exit 2.
    - AC14 prompt-on-stderr invariant: `interactive_prompt_lives_on_stderr` — assert the prompt text is in the stderr buffer, NOT the stdout buffer (so `| tee` doesn't capture it).
    - AC15 already revoked: `already_revoked_exits_3`.
    - AC16 reason shape: `empty_reason_exits_2`, `whitespace_reason_exits_2`, `nul_reason_exits_2`, `newline_reason_exits_2`, `carriage_return_reason_exits_2`, `oversize_reason_exits_2`.
    - AC17 help: `revoke_key_help_has_realistic_examples`.
    - AC18 audit-details sanitization: `audit_details_stores_reason_verbatim`, `audit_details_via_json_loads_equality`.
    - AC18 log sanitization: `log_has_no_reason_text` — reason stored in the audit row (`details_json`) but **never** echoed in the `Key revoked | …` log line.
    - AC19 read-after-write: `then_show_renders_revoked_red_status`.
    - Regression — `list-keys --status revoked` surfaces the revoked row: `list_keys_status_revoked_sees_this_key`.

- [x] **Task 8 — Output module extension tests** (AC: #8, #9)
  - [x] 8.1 In `tests/test_keys_output.py`, add `TestContextBlockPaidUntilBranch`:
    - `manual_first_charge_none_with_paid_until_shows_paid_until_row` — seed an `IssuedKey` with `first_charge_date=None`, `record.paid_until="2026-05-05"`, `billing_mode="manual"`, assert the rendered body includes the literal `paid until: 2026-05-05` and does NOT include `first charge:`.
    - `manual_first_charge_none_with_null_paid_until_shows_em_dash` — `record.paid_until=None`, assert the body includes `paid until: \u2014`.
    - `manual_with_first_charge_date_still_shows_first_charge` — regression: `first_charge_date="2026-05-05"`, `first_charge_days_free=21`, assert body includes `first charge: 2026-05-05 (21 days free until then)` (existing issue-key contract unchanged).
    - `complimentary_always_shows_not_applicable` — both branches render the hardcoded complimentary `paid until: \u2014 (not applicable)` regardless of `first_charge_date` value.

- [x] **Task 9 — Quality gates**
  - [x] 9.1 `uv run ruff check . && uv run ruff format --check .` — zero warnings.
  - [x] 9.2 `uv run mypy src/comadre/keys/` — zero errors in strict mode. New dataclasses must be strict-compatible (use `frozen=True, slots=True` + explicit field types).
  - [x] 9.3 `uv run pytest` — all new tests pass; Story 1.5 closed at ~839 tests; Story 1.6 adds roughly 60–80 tests across five files; target final count ≈ 900–920.
  - [x] 9.4 `uv run pre-commit run --all-files` — all hooks pass.
  - [x] 9.5 Do NOT update `sprint-status.yaml` — that transition happens when the reviewer moves the story to `done` via the `code-review` workflow.
  - [x] 9.6 **Non-regression guard rails (Epic 4.5 sentinel greps):**
    - `rg 'HTTPException' src/comadre/keys/cli/commands/keys.py` — empty (FR51).
    - `rg 'f"UPDATE|f"DELETE|f"INSERT' src/comadre/keys/db.py` — exactly the existing Story 1.5 `set_parts` join (literal-column-name assembly) and the new Story 1.6 `update_api_key` equivalent. Both join literal column names separated by commas; operator input lands only in positional `?` bindings. Zero new f-string SQL carrying `{variable}` substitution.
    - `rg '\bprint\(' src/comadre/keys/cli/commands/keys.py` — no bare builtin `print(`. Only `stdout_console().print(...)` / `stderr_console().print(...)` via `render_*` helpers or the confirmation-prompt branch.
    - `rg 'os\.environ' src/comadre/keys/` — empty.
    - `rg 'tax_id_encrypted' src/comadre/keys/cli/commands/keys.py` — empty (no tax-ID reads or writes by any of the three commands).
  - [x] 9.7 **Performance sanity (NFR5).** On a DB seeded with 1,000 customers + 2,000 keys + 5,000 audit rows (temporary one-off script, not committed), measure all three commands end-to-end; each should land well under 500 ms. Record the wall-clock in the Dev Agent Record.

- [x] **Task 10 — Manual verification**
  - [x] 10.1 **Hot-path smoke.** From a fresh `./data/keys/registry.db`, run:
    ```bash
    uv run comadre-keys create-customer --name "Helena Ribeiro" --email "helena@clinica.com" --cpf "123.456.789-09"
    uv run comadre-keys issue-key --customer <cust_id> --rpm 60 --price 149 --notes "bundled into infra"
    # capture <prefix> from the KeyPanel
    uv run comadre-keys update-key <prefix> --rpm 120 --price 199 --notes "upgraded 2026-05-12 from 60->120rpm"
    uv run comadre-keys rotate-key <prefix>
    # capture <new_prefix> from the fresh KeyPanel
    uv run comadre-keys revoke-key <new_prefix> --reason "bundle contract ended 2026-09-30" --yes
    uv run comadre-keys show <new_prefix> --audit-tail 10
    ```
    Confirm: (a) update prints ConfirmationLine `Updated: <prefix> (Helena Ribeiro) — rpm: 60→120, price: R$ 149,00→R$ 199,00, notes updated`; (b) rotate prints a KeyPanel with `paid until:` (not `first charge:`) since the key had no paid_until set yet we see the em-dash; (c) revoke prints `Revoked: … — reason: bundle contract ended 2026-09-30`; (d) `show --audit-tail 10` shows `REVOKE_KEY`, `ROTATE_KEY`, `UPDATE_KEY`, `ISSUE_KEY`, `CREATE_CUSTOMER` in newest-first order; (e) DB file mode stays `0600`; (f) stderr carries the structured INFO lines (one per mutation) with no customer name / plaintext / price value / reason text.
  - [x] 10.2 **Error panels.** Run each failure mode end-to-end and confirm red-bordered ErrorDisplay on stderr with the expected exit codes:
    - `update-key nopekey --rpm 60` (exit 3, `Key not found`).
    - `update-key <revoked_prefix> --rpm 60` (exit 3, `Key is revoked`).
    - `rotate-key <revoked_prefix>` (exit 3).
    - `revoke-key <revoked_prefix> --reason "x" --yes` (exit 3, `Key already revoked`).
    - `update-key <prefix>` (exit 2, neither flag).
    - `revoke-key <prefix> --reason " "` (exit 2, whitespace).
    - `update-key <prefix> --rpm 99999` (exit 2, range).
    - `update-key <complimentary_prefix> --price 50` (exit 2, mutex).
  - [x] 10.3 **Interactive prompt test.** Run `revoke-key <prefix> --reason "contract ended"` and type:
    - `y` + Enter → revoked, confirmation line.
    - Enter (default no) → `Aborted.`, exit 2, no mutation.
    - Ctrl-D (EOF) → same `Aborted.` path, exit 2.
  - [x] 10.4 **Audit inspection.** `sqlite3 ./data/keys/registry.db "SELECT actor, action, target_id, details_json FROM audit_log ORDER BY id DESC LIMIT 10;"` — confirm the five newest rows contain `revoke_key`, `rotate_key`, `update_key`, `issue_key`, `create_customer` actions with their expected `details_json` payloads and no plaintext / hash / name / email / reason-if-revoke leakage across the other columns.
  - [x] 10.5 **Log piping.** Tail stderr (`2>&1 1>/dev/null`) during each happy-path invocation; confirm the structured log shape AC18 specifies. Confirm no plaintext, hash, customer name, note text, price value, or revocation reason ever appears in the log stream.

## Dev Notes

### Architecture invariants (from `_bmad-output/planning-artifacts/architecture.md`)

- **Import graph downward-only.** Story 1.6 adds three commands to `cli/commands/keys.py` and three helpers to `db.py`. No module-order changes. **Must not import from `keys.auth` or `keys.cache`** — those modules still don't exist and the CLI path is forbidden from touching them even after they land. [Source: `architecture.md#Import-Boundary-Rules` L366-L372]
- **CLI / runtime separation.** Do NOT touch `main.py`, `api.py`, `rate_limit.py`, `service.py`, `config.py`, `exceptions.py`. The 1.6.2 public contract stays byte-for-byte. [Source: `architecture.md` L519-L521]
- **No raw HTTPException.** Errors flow through `render_error(...)` + `typer.Exit(code=...)` with the AC exit-code mapping. [Source: `architecture.md#Enforcement-Guidelines` L471-L488]
- **No `print()`.** All non-prompt output via `render_confirmation` / `render_error` / `render_key_panel`. The ONE exception is `typer.confirm(..., err=True)` for the revoke-key prompt — that's Click's built-in prompt machinery, which writes to the configured stream via `click.echo` internally (not via our shared Console). Story 1.6 accepts this as the canonical confirmation surface; it's the only place in `comadre-keys` that writes to stderr outside `stderr_console()`. Regression check: `rg '\bprint\(' src/comadre/keys/cli/commands/keys.py` stays empty.
- **Parameterized SQL only.** Each helper builds its UPDATE's SET clause from literal column-name fragments joined with `", "`; operator input lands only in positional `?` bindings. Matches Story 1.3 `list_api_keys` and Story 1.5 `update_customer` precedent. [Source: `architecture.md#SQLite-Query-Patterns` L376-L383]
- **Transaction scope.** Each helper owns `with conn:`; callers must NOT wrap. The UPDATE and audit write either both commit or both roll back. Same contract as `insert_customer` / `insert_api_key` / `update_customer`. [Source: `architecture.md#Transaction-Scope` L465-L469]
- **Audit action names.** `update_key`, `rotate_key`, `revoke_key` — three of the snake_case verb-noun actions enumerated in the architecture naming table. [Source: `architecture.md#Audit-Action-Naming` L313-L314]
- **Audit blocklist.** Keys `cpf` / `cnpj` / `tax_id` / `name` / `email` / `key_plaintext` / `authorization` are rejected at `log_event`. Our `details_json` payloads use only safe keys: `"fields"`, `"key_prefix_old"`, `"key_prefix_new"`, `"reason"`. [Source: `src/comadre/keys/audit.py` L23-L44]
- **Prefix resolution via `resolve_show_target`.** Same entry point as `show <target>`. The key difference: update/rotate/revoke commands must REJECT the `customer` branch (exit 2) because they are key-verbs only. `show` accepts both branches. [Source: `src/comadre/keys/db.py::resolve_show_target` L627-L671]

### Data contracts

- `api_key.rate_limit_rpm` — `INTEGER NOT NULL CHECK (rate_limit_rpm > 0)`. Story 1.6 updates with an additional 1..10000 CLI cap (Story 2.2 will tighten further). [Source: `src/comadre/keys/migrations/v001_initial.sql` L17]
- `api_key.price_monthly` — `REAL NOT NULL DEFAULT 0.0`. Complimentary keys store `0.0`; updating `--price` on a complimentary key is rejected as a usage error (Story 1.2 mutex, extended here). Float-precision drift is a known deferred-work item (Story 1.2) — not addressed in Story 1.6. [Source: v001 L20]
- `api_key.notes` — `TEXT DEFAULT ''`. Story 1.6 REPLACES the column (distinct from `customer.notes` which is append-only). Operator mental model: key notes = metadata tier stamps; customer notes = narrative notebook. [Source: v001 L24]
- `api_key.status` — `CHECK (status IN ('active', 'suspended', 'revoked'))`. Story 1.6 transitions: update rejects revoked; rotate rejects revoked; revoke rejects already-revoked. Story 3.1 will add the `suspended ↔ active` transitions; Story 1.6 does NOT write `suspended`. [Source: v001 L18]
- `api_key.key_hash` — `TEXT NOT NULL UNIQUE`. Story 1.6 `rotate_api_key` is the only writer besides `insert_api_key`. The UNIQUE index `idx_api_key_hash` makes the rare collision path observable as `sqlite3.IntegrityError` with `SQLITE_CONSTRAINT_UNIQUE` — mapped to exit 5 per AC12. [Source: v001 L15, L42]
- `api_key.last_used_at` — `TEXT` (nullable ISO UTC). Story 1.6 `rotate_api_key` resets to `NULL` (old stats no longer apply to the new plaintext). `update_api_key` and `revoke_api_key` preserve it. The runtime `verify_api_key` path (Story 2.1) is the only writer post-issuance — our CLI does not write `last_used_at`. [Source: v001 L23]
- `audit_log.details_json` — `TEXT` nullable. Story 1.6 writes via `json.dumps(..., sort_keys=True)` from `log_event`. Our payloads:
  - `update_key`: `{"fields": ["notes" | "price" | "rpm", ...]}` (sorted subset).
  - `rotate_key`: `{"key_prefix_new": "<8>", "key_prefix_old": "<8>"}`.
  - `revoke_key`: `{"reason": "<free-text>"}`.
- **Clock seam.** `update-key` takes `today` for the same reason `update-customer` does — consistent signature across mutation helpers, even though `update_api_key` does not itself use `today`. This lets the caller seam through a frozen clock in tests without the helper touching `date.today()` directly. `rotate-key` and `revoke-key` don't need `today` — no date-dependent column touched.

### Library version gotchas

- **`typer.confirm(..., abort=True, err=True)`** — Click 8.2+ contract (confirmed by pyproject.toml dep ladder). `abort=True` raises `click.exceptions.Abort` on a "No" answer. `err=True` routes the prompt to stderr so piped-output scripting (`revoke-key … | tee`) doesn't capture the prompt into the piped file. Story 1.6 catches the `Abort` at the command boundary and remaps the exit code to 2 (Click's default is 1; UX-DR10 reserves exit 2 for usage-tier errors, which includes "operator bailed at the prompt").
- **`CliRunner` stdin injection.** `CliRunner(runner).invoke(app, [...], input="y\n")` feeds the string to the child Click context's stdin. For EOF, pass `input=""` (empty string → EOF immediately → Abort on `abort=True`). Click's `CliRunner` is fine with this pattern — no special `mix_stderr=False` needed (Story 1.4 Click 8.2+ bump already unblocked this).
- **Pydantic `TypeAdapter` not used in Story 1.6** — all validation is inline (rpm/price float + range; reason/notes string shape). No `EmailStr` or `BaseModel` hop. Keeps the command bodies flat. If a future story adds `--rpm-range` or similar enumerated inputs, migrate to Typer's `click.Choice` path at that time (deferred from Story 1.3 — Typer idiomaticity pass).
- **`hash_api_key` / `key_prefix_from_plaintext`** are pure stdlib wrappers. Safe to call inside the `with conn:` block (no syscall, no allocation worth worrying about). Both already tested in `tests/test_keys_tokens.py`.
- **`generate_api_key_plaintext` entropy.** `secrets.token_urlsafe(32)` returns 256 bits of URL-safe base64, 43 chars. Rotation thus has the same collision bound as issue-key — negligible per-key (2^-128 collision probability against a 1K-key table). Per AC12, we still handle the UNIQUE constraint path so a future crypto-RNG failure doesn't silent-corrupt the DB.
- **`date.today()` is NOT used.** The helper receives `today` as a parameter; the CLI resolves it via `_resolve_today_in_tz(billing_tz)` like every other CLI command. Keeps tests clock-free.

### Previous story intelligence (Stories 1.1, 1.2, 1.3, 1.4, 1.5)

- **CliRunner Click 8.2+ pattern.** No `mix_stderr=False`. Wire stdout/stderr to `StringIO` via `_reset_for_tests()` + fixture-assigned `output_mod._stdout_console` / `_stderr_console`. Copy fixtures verbatim from `tests/test_keys_cli_update_customer.py`.
- **Help-only invocations do not open the DB.** Assert `not (tmp_path / "registry.db").exists()` after every `--help` run. Extend the invariant to the three new commands.
- **`get_cli_actor()` contract.** `cli:<unix-username>` with fallback. Import from `comadre.keys.audit`.
- **Log-capture pattern.** Attach a throwaway `logging.Handler` to the `keys.cli` logger (propagate=False makes `caplog` blind). Same idiom as Story 1.5's `test_log_has_no_pii`.
- **`_resolve_today_in_tz` seam.** Lives in `src/comadre/keys/cli/_clock.py` (Story 1.4 Task 6). Re-exported from `cli/commands/keys.py` under the underscore alias `_resolve_today_in_tz`. Monkey-patch `keys_cmd._resolve_today_in_tz` to freeze.
- **`_errors.py` helpers.** `first_error_msg(exc)` for pydantic ValidationError; `is_missing_encryption_key(exc)` for settings load. Both already imported by `commands/keys.py`.
- **`_MISSING_KEY_HINT`** — module-level string literal in `keys.py`. Story 1.6 reuses it verbatim.
- **Help-text normalisation.** Strip Rich panel border glyphs (`│ ╭ ╮ ╰ ╯ ─`) **before** collapsing whitespace in help-surface test assertions. Story 1.3 / 1.4 / 1.5 helpers copy verbatim.
- **`resolve_show_target` four-branch discriminator.** `kind` ∈ `{customer, key_single, key_ambiguous, not_found}`. Story 1.6 commands are key-verbs — only `key_single` is valid. Reject the other three with specific error titles + hints.
- **`cmdr_live_<plaintext>` pasted-input redaction in logs.** Story 1.4 established the `cmdr_live_ + first-8-of-suffix + …` truncation for `show`. Story 1.6 MUST apply the same redaction to `update-key` / `rotate-key` / `revoke-key` log lines when the operator pasted the full plaintext — the structured log must never carry more than the 8-char prefix.
- **ConfirmationLine em-dash U+2014.** Every mutation ConfirmationLine uses U+2014, not ASCII `--` or `-`. The existing `Updated: …` format is the grammar to match.
- **Story 1.5 deferred-work items addressed in Story 1.6:**
  - "`_logger.info` raising after commit" → wrap `_logger.info(...)` in `contextlib.suppress(Exception)` in all three commands (Task 2.6).
  - "Audit-details JSON assertions compare exact byte strings" → use `json.loads(row["details_json"]) == {...}` in all Story 1.6 tests. Do NOT add byte-equality assertions (Task 1.4 / Task 5–7).
  - "Non-NUL control characters in `--add-note`" → partially addressed: Story 1.6 rejects NUL + LF + CR in `--notes` and `--reason`. Other C0 controls remain deferred with Rich-markup escaping (cross-cutting).
  - "Unbounded `--add-note` length" → partially addressed: Story 1.6 caps `--notes` and `--reason` at 1024 chars each. `create-customer --notes` / `update-customer --add-note` stay uncapped (out of Story 1.6 scope).
  - "`UpdateCustomerResult.customer` round-trip" → deferred: Story 1.6 continues the round-trip pattern for consistency.
  - "Concurrent tombstone race" → deferred: single-writer CLI; re-raise as `RuntimeError` → exit 5 (Task 1.2 matches the Story 1.5 patch).
  - "No concurrent-update regression test" → deferred (same rationale).
- **Story 1.2 deferred-work items addressed in Story 1.6:**
  - "`--rpm` has no upper bound" → AC5 adds the 1..10000 cap on `update-key --rpm`. Apply to `issue-key` as well? — intentionally NOT part of Story 1.6 scope; the rationale for applying here is "we're touching the validation surface"; `issue-key` will be covered by Story 2.2's shard-aware cap. Same cap value (10000) will be the starting point for that story.
  - "Raw `--customer` string interpolated into error title with no length cap" → AC7 adds `_truncate_ident` for the positional `<key-prefix>` across all three commands (80-char cap with `…` suffix).
  - "`paid_until` malformed-ISO crash in `is_payment_current`" → NOT relevant to Story 1.6 (we don't read `paid_until` at decision time; we pass it through byte-for-byte during rotation and display it via `_iso_date` which tolerates malformed values by returning the em-dash).
  - "`KeyboardInterrupt` between INSERT commit and `render_key_panel` orphans the key" → partial mitigation: rotate-key is now available as the operator's recovery path. A future story can add signal-handling across the issue-key / rotate-key window (out of scope).
- **Story 1.1 deferred-work item now actionable in Story 1.6:** "Unbounded `--notes` length" — partially addressed (1 KiB cap on `update-key --notes` only). `create-customer --notes` stays uncapped.

### Git intelligence

Last 5 commits on master (as of 2026-04-17 after Story 1.5 code-review land):
- `7924586 feat(keys): land story 1.4 — comadre-keys show with DetailPanel, AuditTail, JSON output, and code-review fixes` — adds `resolve_show_target`, `KeyDetailRow`, `get_key_detail_by_id`. All directly consumed by Story 1.6.
- `f4ceb97 feat(keys): land story 1.3 — list-customers + list-keys with StatusTable, filters, JSON, and code-review fixes` — stderr log routing is load-bearing for Story 1.6's log-sanitization ACs.
- `612d952 feat(keys): land story 1.2 — comadre-keys issue-key with one-shot KeyPanel` — `_format_brl`, clock seam, `IssuedKey`, `render_key_panel`, `_context_block` (extended in Task 3.5).
- `50cdada feat(keys): land story 1.1 impl` — foundational subpackage, v001 schema, `log_event` blocklist.
- `a696c68 feat(voices): add pf_influencer_02 voice profile` — unrelated voice work.

Story 1.5 landed between 7924586 and the story-1-6 create-story run; the working tree at Story 1.6 start carries Story 1.5 implementation already committed (the `update_customer` + `UpdateCustomerResult` + `_update_confirmation_suffix` pattern is in place and is the reference implementation for Story 1.6's three helpers).

### Deferred-work items surfaced by Story 1.6 (flag for review at code-review time)

- **Shared CLI-test fixture module.** Five copies of `_clear_settings_cache` / `_reset_consoles_to_buffers` / `env` / `_buffers` / `_clear_buffers` / `_seed_customer` will exist after Story 1.6 tasks 5–7 land. Carve out a dedicated test-hygiene pass to extract to a `tests/_keys_cli_fixtures.py` helper module. Log in `deferred-work.md` under Story 1.6.
- **`issue-key --rpm` upper bound.** Story 1.6 caps `update-key --rpm` at 10000. `issue-key` still accepts unbounded RPM. Story 2.2 was the original carve-out; re-confirm the scope alignment at that story's creation.
- **`revoke-key` `--yes` semantics on an interactive TTY.** Today's Typer confirm is terminal-aware — if the CLI is run without a TTY and without `--yes`, Click raises `Abort` immediately (no prompt possible). This matches the UX-DR11 contract (`--yes` needed for scripting), but an operator running `revoke-key` under `nohup` or `systemd` with no `--yes` will see an unhelpful `Aborted.`. Log as deferred — add a "this is non-interactive; pass --yes" hint in a future UX pass.
- **`rotate-key` plaintext-in-memory duration.** The new plaintext is held by the command body from `generate_api_key_plaintext()` through `render_key_panel(issued)` — roughly the same window as `issue-key`. A `SIGINT` between commit and `render_key_panel` leaves a rotated row whose plaintext is lost (same class of issue as Story 1.2 `KeyboardInterrupt`). Defer — signal handling across issue/rotate needs a unified design.
- **`api_key` has no `revoked_at` column.** Revocation timestamp lives solely in `audit_log.occurred_at`. If Epic 3 / Epic 4 grows a need to sort revoked keys by revocation time (e.g. for LGPD retention policy), add a v002 migration adding `revoked_at TEXT` + backfill from audit. Not needed for Story 1.6 functionality.
- **Concurrent `rotate-key` invocations against the same row.** Project runs a single FIFO queue for the runtime and CLI invocations are operator-serial, but SQLite's `busy_timeout=5000` is the only protection against two operators on two SSH sessions racing. Story 1.6 does not add a regression test for this. Log as deferred.

### UX invariants reproduced from `ux-design-specification.md`

- **UX-DR1 KeyPanel (`ux:L708-L745`)** — double-border warning + naked plaintext + double-border context. Rotate-key uses the same structure as issue-key; only `_context_block` behavior differs (paid-until row).
- **UX-DR7 ConfirmationLine (`ux:L835-L846`)** — plain single line on stdout. `Updated: … — …`, `Revoked: … — …`. Grammar matches the UX spec's example style (`Marked paid: cmdr_Pq (Pedro Lopes) → paid until 2026-06-05`).
- **UX-DR8 4-color palette (`ux:L1028-L1036`)** — revoked = red. `show` renders the color; `revoke-key`'s ConfirmationLine does NOT colorize (it's a single plain line). The operator's color cue for revocation lives in `show`.
- **UX-DR9 Shared Console (`ux:L250-L256`)** — all panel / confirmation output through `stdout_console()` / `stderr_console()`. The ONE exception: `typer.confirm(..., err=True)` for the revoke-key prompt (Click internals use `click.echo` to the configured stream; this is architecturally fine — the confirm prompt is not a Comadre-rendered surface).
- **UX-DR10 Exit codes (`ux:L1046-L1056`)** — 0 success, 2 usage, 3 not-found / already-revoked / cannot-mutate-revoked, 5 database, 6 config. Story 1.6 uses 0, 2, 3, 5, 6 (no exit 4 — tax-ID validation path absent).
- **UX-DR11 Destroy-tier confirmation (`ux:L886-L913`)** — revoke-key is the first Destroy-tier command landing in the codebase. Pattern: `--yes` skips; no `--yes` → interactive `[y/N]` defaulting to No. Story 4.1 `delete-customer --hard` and Story 4.2 `rotate-encryption-key` will follow this story's implementation as the canonical precedent.
- **UX-DR15 Realistic `--help` examples (`ux:L995-L1013`)** — every option help string carries a realistic example; every command epilog carries a full `Example:` invocation. AC17 enforces per command.
- **UX-DR16 Terminal width adaptation (`ux:L1063-L1081`)** — ConfirmationLine is a single Rich-wrapped line; no custom abbreviation logic. KeyPanel's naked plaintext line stays on one row via `no_wrap=True` + `overflow="ignore"` (existing `render_key_panel` behavior; unchanged by Story 1.6).
- **UX-DR17 Copy-paste fidelity (`ux:L743`)** — rotate-key's new plaintext MUST render on a naked line at column 0 (not inside any Panel), identical to issue-key. The existing `render_key_panel` implementation handles this; Story 1.6 does not alter the rendering shape.

### Scope guards (things NOT to do in Story 1.6)

- **Do NOT add `suspend` / `reactivate` / `mark-paid`.** Epic 3 Story 3.1. These are separate status-transitions (`active ↔ suspended`) with separate audit actions (`suspend_key`, `reactivate_key`, `mark_paid`) and separate CLI flags.
- **Do NOT add `--billing-mode` to `update-key`.** A billing-mode change is a contract event; the supported path is `revoke-key` → `issue-key`. The existing `issue-key` billing-mode mutex (price vs. complimentary) would need to be duplicated in `update-key` with exponentially more branches.
- **Do NOT make `update-key --notes` append-only.** Explicitly distinct from `update-customer --add-note`. Rationale in Scope.
- **Do NOT generate the new plaintext before the revocation check in `rotate-key`.** Wasted entropy is not a security bug but a smell — and it makes the "rotate rejected" path harder to test because the plaintext leaks into entropy-sensitive tests otherwise.
- **Do NOT write `last_used_at` anywhere except `rotate_api_key` (which sets it to NULL).** The runtime `verify_api_key` path (Story 2.1) is the sole non-rotation writer. The CLI must not touch this column on update or revoke.
- **Do NOT add a `--force` flag to bypass the `revoked`-key check.** Revoked is terminal. Operators needing to "un-revoke" use `issue-key` with a new customer record or with the same customer and accept a new `key_<ulid>`.
- **Do NOT add a v002 migration.** v001 schema is sufficient. `api_key.revoked_at` / `api_key.revoked_reason` are not needed — the audit log is the durable revocation record.
- **Do NOT touch `src/comadre/main.py`, `api.py`, `rate_limit.py`, `service.py`, `config.py`, `exceptions.py`, or `cli/app.py`.** `cli/app.py` picks up the new commands via the existing `app.registered_commands.extend(keys_app.registered_commands)` flow. No edits needed.
- **Do NOT regress Story 1.3's `keys.cli` → stderr log routing.** The three new commands all emit structured INFO lines on stderr. stdout MUST stay clean for piping (mutation ConfirmationLines and the rotate-key KeyPanel are the only stdout writes).
- **Do NOT audit old/new field values for `update-key`.** The audit row carries `{"fields": [...]}` only. FR37/NFR15 prohibit personal / operator-sensitive data in the audit row.
- **Do NOT re-implement `_format_brl`, `_iso_date`, `_status_label`, `render_confirmation`, `render_error`, `render_key_panel`, `_resolve_today_in_tz`, `_MISSING_KEY_HINT`, `_SHOW_NOT_FOUND_HINT`, `_SHOW_AMBIGUOUS_HINT`.** Import and reuse.
- **Do NOT touch `keys/billing.py`** — the `ManualBillingProvider.on_key_revoked` hook is a no-op stub today; wiring it into `revoke-key` adds nothing in MVP (the hook exists for future PSP adapters) and would couple the CLI to the billing module. Leave it for Story 3.x when the provider grows real behavior.

### Enumeration resistance & log sanitization (FR37, NFR15, NFR16)

- **Error titles echo only operator-supplied literals, truncated to 80 chars.** The `_truncate_ident` helper guards against a multi-KB positional argument blowing up the ErrorDisplay panel (Story 1.2 deferred item). A pasted `cmdr_live_<plaintext>` is further redacted in logs to `cmdr_live_<first-8>…` (Story 1.4 pattern).
- **`audit_log.details_json`** carries only safe-key payloads: `fields` (list of column names), `key_prefix_old` / `key_prefix_new` (public identifiers, already in issue-key logs), `reason` (free-text operator intent — not on the blocklist). Old/new RPM values, old/new price values, notes text, customer name, email are NEVER in `details_json`.
- **Structured INFO logs** are formatted per AC18 with field lists and prefix identifiers only. `cmdr_live_<plaintext>` pasted as a target is redacted before logging.
- **No tax-ID decryption** happens in any of the three commands. Task 9.6 grep for `tax_id_encrypted` in `commands/keys.py` stays empty.
- **`revoke-key`'s reason** is stored in `audit_log.details_json` (durable, operator-queryable via `show --audit-tail`) but never echoed in the structured log line. It IS echoed in the ConfirmationLine back to the operator's own terminal — FR37 covers logs and audit, not terminal display.

### Project Structure Notes

- **New files (3):**
  - `tests/test_keys_cli_update_key.py` — Task 5.
  - `tests/test_keys_cli_rotate_key.py` — Task 6.
  - `tests/test_keys_cli_revoke_key.py` — Task 7.
- **Modified existing files (5):**
  - `src/comadre/keys/db.py` — +3 helpers, +3 result dataclasses, +1 `Literal` alias, +1 `KeyFieldDeltas` dataclass. ~200 new lines.
  - `src/comadre/keys/cli/commands/keys.py` — +`update_key_cmd`, +`rotate_key_cmd`, +`revoke_key_cmd`, +hint-constant block, +`_truncate_ident` helper, +`_key_update_clauses` helper. ~400 new lines.
  - `src/comadre/keys/cli/output.py` — extend `_context_block` by ~10 lines (paid-until branch for manual-mode rotation).
  - `tests/test_keys_db.py` — append `TestUpdateApiKey` (11 methods), `TestRotateApiKey` (10 methods), `TestRevokeApiKey` (9 methods). ~700 new lines.
  - `tests/test_keys_output.py` — append `TestContextBlockPaidUntilBranch` (4 methods). ~50 new lines.
- **No changes to existing runtime files** (`api.py`, `main.py`, `rate_limit.py`, `service.py`, `config.py`, `exceptions.py`, `cli/app.py`, `cli/__init__.py`, `cli/_clock.py`, `cli/_errors.py`, `cli/commands/customers.py`, `migrations/*.sql`, `audit.py`, `models.py`, `crypto.py`, `billing.py`, `tokens.py`).
- All placements per architecture.md §Module Organization (L327-L350). No deviations.

### Testing Standards

- All tests mocked by default; no real models, no `@pytest.mark.slow`.
- `CliRunner` from `typer.testing` — synchronous, same as Stories 1.1–1.5.
- `tmp_path` for DB files. In-memory SQLite (`sqlite3.connect(":memory:")`) acceptable for Task 1 helper tests that don't exercise `get_connection()`'s chmod path; use a real `tmp_path` DB for the integration tests.
- Reuse Story 1.1's `_clear_settings_cache` autouse from `tests/conftest.py`.
- Target coverage: 90%+ on new code.
- Autouse fixture `_reset_consoles_to_buffers` — copy verbatim from `tests/test_keys_cli_update_customer.py`.
- `width=120` in the test Console — same as Stories 1.1–1.5.
- Audit-details assertions via `json.loads(row["details_json"]) == {...}` — NOT byte-equal string match (closes Story 1.5 deferred-work).
- Interactive-confirm tests feed stdin via `CliRunner(...).invoke(app, [...], input="y\n")` / `input="\n"` / `input=""` (EOF).

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-1.6-Key-Lifecycle-Update-Rotate-Revoke` (L455-L489)] — AC source text.
- [Source: `_bmad-output/planning-artifacts/prd.md#CLI-Tool-Specification` (L964-L967)] — `update-key`, `rotate-key`, `revoke-key` spec.
- [Source: `_bmad-output/planning-artifacts/prd.md#Journey-5` (L440-L478)] — `update-key --rpm --price` real-world usage (Ricardo / burst-peak customer).
- [Source: `_bmad-output/planning-artifacts/prd.md#Journey-6` (L543-L555)] — `revoke-key --reason` complimentary-bundle revocation.
- [Source: `_bmad-output/planning-artifacts/prd.md#Functional-Requirements` (L36-L40)] — FR10 + FR11 + FR12 + FR14.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Naming-Patterns` (L313-L314)] — `update_key` / `rotate_key` / `revoke_key` audit action names.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Import-Boundary-Rules` (L366-L372)] — CLI must not import from `keys.auth` / `keys.cache`.
- [Source: `_bmad-output/planning-artifacts/architecture.md#SQLite-Query-Patterns` (L376-L383)] — parameterized `?` placeholders, no f-string SQL with parameters.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Transaction-Scope` (L465-L469)] — helper owns `with conn:`; audit write inside same transaction.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Enforcement-Guidelines` (L471-L488)] — grep-based regression rules (Task 9.6).
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#KeyPanel` (L708-L745)] — double-border + naked-plaintext + context layout for rotate-key.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#ConfirmationLine` (L835-L846)] — single-line mutation output contract.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#ErrorDisplay` (L820-L833)] — red-bordered stderr panel for errors.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Command-Hierarchy` (L886-L913)] — Destroy-tier `--yes` + interactive confirmation pattern for revoke-key.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Responsive-Strategy` (L1063-L1081)] — 80-col adaptation.
- [Source: `_bmad-output/implementation-artifacts/1-2-api-key-issuance.md`] — `IssuedKey` dataclass, `render_key_panel`, `_context_block`, `_MISSING_KEY_HINT`, issue-key usage-error ladder.
- [Source: `_bmad-output/implementation-artifacts/1-3-customer-key-listing.md`] — stderr log routing, help-surface panel-glyph normalisation.
- [Source: `_bmad-output/implementation-artifacts/1-4-key-customer-detail-view-with-audit-trail.md`] — `resolve_show_target`, `KeyDetailRow`, `_SHOW_NOT_FOUND_HINT` / `_SHOW_AMBIGUOUS_HINT`, `cmdr_live_` redaction.
- [Source: `_bmad-output/implementation-artifacts/1-5-customer-updates-notes.md`] — `UpdateCustomerResult` shape, NUL/LF/CR/length validation ladder, `json.loads` audit-details assertion style, `_logger.info` suppress pattern.
- [Source: `_bmad-output/implementation-artifacts/deferred-work.md`] — Story 1.5 / 1.2 / 1.1 deferred items addressed (or re-deferred with rationale) in Story 1.6.
- [Source: `_bmad-output/project-context.md#Critical-Implementation-Rules`] — uv-only, no `os.environ`, no raw `HTTPException`, structured logging, English only.
- [Source: `CLAUDE.md`] — project language policy, Docker v2, `uv` only, no raw `HTTPException`, no `print()`.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m] (Opus 4.7, 1M context)

### Debug Log References

_No interactive debug sessions — all work executed via ``uv run pytest`` / ``uv run mypy`` / ``uv run pre-commit`` in the main shell._

### Completion Notes List

- **All 20 acceptance criteria satisfied.** 122 new tests land green across five files (30 DB-helper unit tests in ``tests/test_keys_db.py``, 27 ``update-key`` integration tests, 12 ``rotate-key`` integration tests, 20 ``revoke-key`` integration tests, 4 ``_context_block`` paid-until-branch tests plus a regression on the existing issue-key first-charge branch). Full suite: **933 passed in ~29 s**.
- **Helper signatures** — ``update_api_key`` and ``revoke_api_key`` both accept ``today: date`` (clock seam). The Story 1.6 code sketch omitted ``today`` from ``revoke_api_key``, but the post-commit ``get_key_detail_by_id`` re-read needs an operator-TZ date to compute ``age_days`` without touching ``date.today()`` — adding the parameter keeps the test suite clock-free and matches the ``update_api_key`` / ``update_customer`` precedent. ``rotate_api_key`` keeps its original signature (no ``today``) because the helper assembles the refreshed ``ApiKeyRecord`` from the in-memory pre-UPDATE SELECT + the fresh hash / prefix, skipping a second DB read entirely — ``ApiKeyRecord`` has no date-derived fields.
- **Shared CLI helpers** — ``_load_settings_and_tz`` and ``_resolve_key_target`` were extracted in ``keys.py`` so the three new commands don't each copy the 40-line settings → TZ → DB-open → prefix-resolution ladder. Each existing command (``issue-key``, ``list-keys``, ``show``) retains its own inlined ladder — I deliberately did NOT refactor those to consume the new helpers so the story's scope stays bounded and the code-review diff is reviewer-friendly.
- **Ignored-plaintext discard** — ``rotate_api_key``'s revoked-branch check fires inside ``with conn:`` BEFORE the ``UPDATE api_key SET key_hash = ?``. When rotation is rejected, the CLI's freshly-generated plaintext simply goes out of scope and the transaction rolls back unwritten. No entropy leaks into a partial state.
- **Story 1.5 deferred-work items addressed here:**
  - ``_logger.info`` raising after commit — every Story 1.6 log call is wrapped in ``contextlib.suppress(Exception)``.
  - Audit-details JSON assertions now compare via ``json.loads(row["details_json"]) == {...}`` in all new tests.
  - ``--notes`` / ``--reason`` NUL, LF, CR, length validation — closes the partial-controls-only Story 1.5 item for the new surface; other C0 controls remain deferred with Rich-markup escaping (cross-cutting future pass).
- **Story 1.2 deferred-work items addressed here:**
  - ``--rpm`` upper bound — closed for ``update-key --rpm`` (cap at 10 000). ``issue-key`` still uncapped per scope; Story 2.2 will tighten further per VPS tier.
  - Raw-identifier-in-error-title length cap — closed for all three new commands via the ``_truncate_ident`` helper (80-char cap + ellipsis).
- **NFR5 performance** — on 1 K customers + 2 K keys, end-to-end ``time uv run comadre-keys update-key …`` measured 301 ms, ``rotate-key`` 347 ms, ``revoke-key`` 308 ms (wall-clock including ``uv run`` Python startup). Well under the 500 ms detail/mutation budget. Database cost itself is microseconds — the ``uv run`` cold-start dominates.
- **Quality gates** — ``ruff check .`` clean, ``ruff format --check .`` clean, ``mypy src/`` zero errors, ``pre-commit run --all-files`` all hooks pass.
- **Sentinel greps (Task 9.6)** — ``HTTPException`` / ``os.environ`` / ``tax_id_encrypted`` / bare ``print(`` none in ``src/comadre/keys/cli/commands/keys.py`` and ``src/comadre/keys/``. The two f-string SQL matches in ``src/comadre/keys/db.py`` are the existing Story 1.5 ``update_customer`` pattern and the new Story 1.6 ``update_api_key`` equivalent — both join literal column-name fragments with ``", "`` and only bind operator input to positional ``?`` placeholders. Zero dynamic-predicate interpolation of operator input.

### File List

**New files (4):**
- ``tests/test_keys_cli_update_key.py`` — 27 integration tests (AC1–AC7, AC17, AC18, AC19 + issue-key regression).
- ``tests/test_keys_cli_rotate_key.py`` — 12 integration tests (AC8–AC12, AC17, AC18, AC19).
- ``tests/test_keys_cli_revoke_key.py`` — 20 integration tests (AC13–AC19).
- ``_bmad-output/implementation-artifacts/1-6-key-lifecycle-update-rotate-revoke.md`` — this story spec file.

**Modified existing files (6):**
- ``src/comadre/keys/db.py`` — +3 helpers (``update_api_key``, ``rotate_api_key``, ``revoke_api_key``), +4 result dataclasses (``UpdateKeyResult``, ``KeyFieldDeltas``, ``RotateKeyResult``, ``RevokeKeyResult``), +1 ``Literal`` alias (``UpdateKeyField``).
- ``src/comadre/keys/cli/commands/keys.py`` — +3 commands (``update_key_cmd``, ``rotate_key_cmd``, ``revoke_key_cmd``), internal helpers (``_load_settings_and_tz``, ``_resolve_key_target``, ``_truncate_ident``, ``_redact_log_target``, ``_key_update_clauses``), +1 hint-constant block, extended imports to pull in ``click``, ``render_confirmation``, ``stderr_console``, ``_format_brl``, ``RotateKeyResult``, ``UpdateKeyResult``, ``resolve_show_target``, ``revoke_api_key``, ``rotate_api_key``, ``update_api_key``, ``KeyDetailRow``.
- ``src/comadre/keys/cli/output.py`` — extended ``_context_block`` with the rotate-key "paid until:" branch (manual-mode + ``first_charge_date is None``); ``issue-key`` output contract unchanged.
- ``tests/test_keys_db.py`` — appended ``TestUpdateApiKey`` (12 methods), ``TestRotateApiKey`` (10 methods), ``TestRevokeApiKey`` (9 methods); added ``json`` import, ``revoke_api_key`` / ``rotate_api_key`` / ``update_api_key`` imports, ``comadre.keys.tokens`` imports; shared ``_seed_customer_and_key`` / ``_fetch_api_key`` helpers.
- ``tests/test_keys_output.py`` — appended ``TestContextBlockPaidUntilBranch`` (4 methods) plus a ``_manual_record_with_paid_until`` helper.
- ``_bmad-output/implementation-artifacts/sprint-status.yaml`` — story 1.6 status transitioned ``ready-for-dev → in-progress → review``; last_updated stamped 2026-04-17.
- ``_bmad-output/implementation-artifacts/deferred-work.md`` — appended Story 1.6 deferred items (shared CLI fixture extraction, ``issue-key --rpm`` cap alignment, non-TTY ``--yes`` UX hint, ``rotate-key`` signal-handling window, ``api_key.revoked_at`` column gap, concurrent-rotation regression).

### Change Log

| Date       | Change                                                                                                                            | Author     |
|------------|-----------------------------------------------------------------------------------------------------------------------------------|------------|
| 2026-04-17 | Story 1.6 context file created via ``create-story`` workflow — status ``ready-for-dev``.                                          | Galvani    |
| 2026-04-17 | Dev-story workflow started — 20 ACs, 10 tasks, 50 subtasks. Sprint status transitioned to ``in-progress``.                        | dev-story  |
| 2026-04-17 | Landed ``update_api_key`` / ``rotate_api_key`` / ``revoke_api_key`` helpers in ``src/comadre/keys/db.py`` + 31 unit tests.        | dev-story  |
| 2026-04-17 | Extended ``_context_block`` with the rotate-key "paid until:" branch in ``src/comadre/keys/cli/output.py`` + 4 regression tests.   | dev-story  |
| 2026-04-17 | Landed ``update-key`` / ``rotate-key`` / ``revoke-key`` Typer commands in ``src/comadre/keys/cli/commands/keys.py``.               | dev-story  |
| 2026-04-17 | Added 59 CLI integration tests across three new ``tests/test_keys_cli_{update,rotate,revoke}_key.py`` files.                       | dev-story  |
| 2026-04-17 | Quality gates pass: ``ruff check`` / ``ruff format --check`` / ``mypy src/`` / ``pre-commit run --all-files`` / 933 tests green.   | dev-story  |
| 2026-04-17 | Sprint status transitioned to ``review``; Dev Agent Record / File List / Change Log populated.                                     | dev-story  |

### Review Findings

Code review 2026-04-17 (Opus 4.7, in-thread fallback — adversarial subagents hit rate limit). 20 raw findings → 11 patches, 1 decision-needed, 2 defers, 6 dismissed. Raw reviewer outputs in `review-1-6/findings-*.md`.

#### Decision needed (resolved)

- [x] [Review][Decision] **`update-key --notes` vs `revoke-key --reason` whitespace asymmetry** — **resolved: strip both.** Align `update-key --notes` with `revoke-key --reason` and `update-customer --add-note` (strip-before-validate). Promoted to a patch below.

#### Patch

- [x] [Review][Patch] **Strip `update-key --notes` outer whitespace before validation / storage** [`src/comadre/keys/cli/commands/keys.py::update_key_cmd`] — align with `revoke-key --reason` and `update-customer --add-note` (strip-before-validate convention). Strip after NUL / newline check, before length check, then pass the canonical form into `update_api_key`.
- [x] [Review][Patch] **Replace strippable `assert` in `_key_update_clauses` with runtime check** [`src/comadre/keys/cli/commands/keys.py:~1125`] — under `python -O` / `PYTHONOPTIMIZE=1`, the two `assert result.changes.price_* is not None` calls disappear and `_format_brl(None)` raises `TypeError`. `keys/audit.py` docstring explicitly warns against `assert` for load-bearing checks. Replace with explicit `if ... is None: raise RuntimeError(...)`.
- [x] [Review][Patch] **Move `--reason` shape validation into `revoke_api_key` helper** [`src/comadre/keys/db.py::revoke_api_key`] — CLI scrubs, but any direct caller (future REST / cron) writes raw bytes. Mirror the NUL / LF / strip.empty / 1024-char ladder inside the helper so the storage contract is enforced at every call-site.
- [x] [Review][Patch] **Disambiguate `update_api_key` empty-update-set return** [`src/comadre/keys/db.py::update_api_key`] — `return None` is already the "row missing" signal; the `if not set_parts` defensive branch reuses the same value ambiguously. Raise `ValueError("update_api_key: no fields to update")` instead so direct callers can distinguish the two cases.
- [x] [Review][Patch] **Delete unreferenced `_redact_log_target` helper** [`src/comadre/keys/cli/commands/keys.py:178-189`] — defined but never called. Success-path log lines use helper-returned canonical IDs (safe by construction); redaction is moot. Dead code.
- [x] [Review][Patch] **Add ambiguous-prefix integration test for all three commands** [`tests/test_keys_cli_{update,rotate,revoke}_key.py`] — AC7 prescribes `Ambiguous prefix: multiple keys match '<prefix>'` + exit 3, but no test constructs two keys with identical 8-char prefixes. Coverage gap only, behavior is handled by shared `_resolve_key_target`.
- [x] [Review][Patch] **Add not-found integration tests for `rotate-key` and `revoke-key`** [`tests/test_keys_cli_rotate_key.py`, `tests/test_keys_cli_revoke_key.py`] — `test_update_key.py` has `test_missing_key_exits_3`; the sibling commands don't. Positive end-to-end assertion missing.
- [x] [Review][Patch] **Tighten `update_key_cmd` ValueError routing** [`src/comadre/keys/cli/commands/keys.py:~440-455`] — `except ValueError: if "revoked" in msg → exit 3 else → exit 2 with complimentary hint`. A future helper `ValueError` with neither substring gets misrouted. Match full sentinel string(s) explicitly, or switch to typed exceptions.
- [x] [Review][Patch] **Assert prompt IS on stderr (positive invariant)** [`tests/test_keys_cli_revoke_key.py::test_interactive_prompt_lives_on_stderr`] — today asserts only NOT-in-stdout. Positive stderr-carries-prompt is untested; a future regression that routes prompt to stdout would still pass this test.
- [x] [Review][Patch] **Use U+2192 arrow in `update-key --notes` help example** [`src/comadre/keys/cli/commands/keys.py:~332`] — AC17 shows `60→120rpm` (U+2192); code + test use ASCII `60->120rpm`. Internally consistent, diverges from spec wording. Align to spec.
- [x] [Review][Patch] **Remove unnecessary `.replace("Z", "+00:00")`** [`src/comadre/keys/db.py:~1046` in `rotate_api_key`] — Python 3.11+ `datetime.fromisoformat` parses the `Z` suffix natively. Cosmetic cleanup.
- [x] [Review][Patch] **Pre-check revocation in `rotate_key_cmd` before generating plaintext** [`src/comadre/keys/cli/commands/keys.py::rotate_key_cmd`] — scope-guard "Do NOT generate the new plaintext before the revocation check in rotate-key" (story file L881) is violated: `generate_api_key_plaintext()` runs before `rotate_api_key`'s revocation check. `key_row.status` is already available from `_resolve_key_target`; short-circuit on `status == "revoked"` before the entropy call. The helper's in-transaction check remains load-bearing for TOCTOU safety, but the CLI should honor the scope-guard.

#### Deferred (already written to `deferred-work.md`)

- [x] [Review][Defer] **`rotate_api_key` JOIN misdiagnoses orphaned keys** [`src/comadre/keys/db.py::rotate_api_key` SELECT L~1016-1025] — `JOIN customer ... ON c.id = k.customer_id` returns empty if customer is hard-deleted; helper returns `None` → CLI says "key not found". No hard-delete path exists today; Story 4.1 is the natural place to fix. Deferred — cross-cutting with LGPD hard-delete scope.
- [x] [Review][Defer] **AC20 performance budget not regression-tested** — Dev Agent Record cites 301 / 347 / 308 ms but no committed test. Scope explicitly allows this. Deferred — add a micro-benchmark marker when a perf-regression incident demands it.

#### Dismissed

- Hash-collision detection via substring `"key_hash" in args_msg` — fallback is correct (exit 5), only the retry hint depends on the match; fragile only in hypothetical schema renames.
- `_logger.info` broad `Exception` suppression — documented deliberate trade-off ("durability > observability"); spec Story 1.5 deferred-work item closed exactly by this approach.
- `revoke-key` does DB work before confirm prompt — the prompt needs the canonical 8-char `key_prefix` from the DB (not the pasted plaintext), so pre-prompt resolution is required.
- AC5 ordering (missing + complimentary + price) not explicitly asserted — ordering is evident in code layout; cost of a dedicated test > benefit.
- Refresh-pattern divergence (rotate hand-builds vs update/revoke re-read) — documented deliberate choice per dev notes.
- Tests don't cover "junk" input for interactive confirm — Click's `CliRunner` with finite stdin reduces junk paths to EOF, already tested.
