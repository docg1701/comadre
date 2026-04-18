# Story 1.5: Customer Updates & Notes

Status: done

<!-- Validation optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want to update a customer's email and append operational notes without touching other fields,
so that I can keep customer records current and add short annotations (e.g., "paga tarde — lembrar dia 3") as the customer relationship evolves, with full traceability in the audit log.

**Covers FRs:** FR3 (attach/append notes without overwrite), FR4 (update email + notes without affecting other fields), FR30 (append-only audit log entry per mutation).
**UX-DRs:** UX-DR6 (ErrorDisplay), UX-DR7 (ConfirmationLine), UX-DR9 (shared Console), UX-DR10 (exit codes), UX-DR15 (realistic `--help` examples), UX-DR16 (80-col adaptation).
**NFRs:** NFR5 (detail/mutation class under 500 ms for 1 K customers), NFR15 (no plaintext/PII in logs), NFR16 (no invalid-input echo in error hints), NFR33 (backward-compatible within major version).
**Epic:** 1 — Key Registry & Customer Management.
**Builds on:**
- Story 1.1 (`keys/` subpackage, `v001_initial.sql` schema, `CustomerCreate` model, `EmailStr` validation, `insert_customer` transaction-plus-audit pattern, `get_cli_actor()`, `_errors.py` helpers, `_clear_settings_cache` autouse, `render_error`/`render_confirmation`).
- Story 1.2 (`_format_brl`, `_resolve_today_in_tz` seam via `cli/_clock.py`, ConfirmationLine precedent for one-shot mutations).
- Story 1.3 (`render_empty_state`, `render_json`, `_iso_date`, autouse `_reset_consoles_to_buffers` fixture, stderr-routed `keys.cli` logger for clean stdout).
- Story 1.4 (`get_customer_detail`, `CustomerDetailRow`, `_customer_detail_to_json`, `render_customer_detail`, `_SHOW_NOT_FOUND_HINT`, `resolve_show_target` branching; clock seam already lives in `cli/_clock.py`).

**Unblocks:**
- Story 1.6 `update-key` — reuses the same audit-fields-only contract (`details_json = {"fields": [...]}`), prefix-resolution via `resolve_show_target`, and the "at least one of --X or --Y required" usage-error pattern.
- Story 3.1 `mark-paid`/`suspend`/`reactivate` — inherits the single-line ConfirmationLine format established here (`Updated: {id} ({name}) — <human diff>`).
- Story 4.1 `export-customer`/`delete-customer --hard` — validates that mutation paths leave a permanent, PII-free audit trail (FR38 prerequisite).

**Depends on:** Nothing outside Stories 1.1–1.4. No new dependencies, no schema migration (the `customer.notes` column exists since v001; `customer.email` is already TEXT NOT NULL).

## Scope

Adds **one command** — `update-customer <customer-id> [--email NEW] [--add-note TEXT]` — plus the single DB helper that powers it. Work breaks down as:

1. **`update_customer` helper in `src/comadre/keys/db.py`:**
   - Signature: `update_customer(conn, customer_id, *, new_email, add_note, actor, today) -> UpdateCustomerResult | None`.
   - Opens its own `with conn:` transaction (same pattern as `insert_customer` / `insert_api_key`). SELECTs the live row (tombstone-filtered), mutates `email` and/or `notes`, writes the audit row, all in one commit.
   - Returns `None` when the customer is missing or tombstoned (lets the command map to exit 3). Otherwise returns an `UpdateCustomerResult` dataclass carrying the refreshed `CustomerDetailRow` plus an `updated_fields: tuple[Literal["email", "notes"], ...]` list the ConfirmationLine renderer consumes.
   - Note-append format: `"[{today_iso}] {note_text}"` separated from the existing notes by `"\n"`. `today_iso` is the operator-billing-TZ date (`YYYY-MM-DD`) resolved via the existing `_resolve_today_in_tz` seam — same clock surface Story 1.2's `issue-key` uses, so tests freeze it with the same fixture. An empty existing notes field stores only the new stamped line (no leading newline).

2. **`update-customer` command in `src/comadre/keys/cli/commands/customers.py`** (colocated with `create-customer` / `list-customers` / `show`, same rationale as Story 1.4 — the resolver-plus-detail-render plumbing lives one import away).
   - Positional `customer_id: str`. Options `--email`, `--add-note`. At least one of the two is required (usage error otherwise).
   - Validates `--email` by instantiating `pydantic.TypeAdapter(EmailStr).validate_python(email)` — isolates the validation to the email shape without constructing a full `CustomerCreate` (name/tax-ID aren't being changed).
   - `--add-note` is stripped (`.strip()`) then rejected when empty — whitespace-only notes are a usage error (exit 2).
   - Opens DB, applies migrations, calls `update_customer`. On `None` → ErrorDisplay exit 3. On success → ConfirmationLine per AC5.
   - Structured INFO log: `Updated customer | id=<cust_…> | fields=<comma-joined>`. Never includes name, email, tax-ID, or the note text.

3. **Audit-log contract.** `details_json = {"fields": [...]}` where the list is a sorted subset of `["email", "notes"]`. The audit blocklist in `keys/audit.py` already rejects `email` / `cpf` / `cnpj` / `name` / `key_plaintext` / `authorization` at the top level; we pass the list under the safe key `"fields"` so the blocklist check doesn't trip. **Never** record the old/new email values or the note text — FR37/NFR15 prohibit PII in the audit row and the `action` + `occurred_at` + `actor` already establish the "who/when/what-kind-of-change" record needed by FR30.

4. **Unit + integration tests** — extend `tests/test_keys_db.py` with the new helper coverage; create `tests/test_keys_cli_update_customer.py` mirroring Story 1.4's `test_keys_cli_show.py` fixture scaffolding. `tests/test_keys_output.py` needs no new class because we reuse `render_confirmation` / `render_error`.

**Out of scope (future stories, DO NOT add):**
- `--name`, `--cpf`, `--cnpj` updates → name is stable per PRD data model; tax-ID rotation is a Fernet re-encryption operation deferred to Story 4.2 (`rotate-encryption-key`) and LGPD purge (Story 4.1). Any future "change the legal name because of a cadastral correction" path will be a separate PRD entry — not Story 1.5.
- `--clear-notes` / `--replace-notes` → intentionally absent. FR3 demands append-only; overwrite semantics would let an operator destroy audit-relevant context accidentally. Operators who truly need to redact a note use `delete-customer --hard` + re-create (Story 4.1) or ask for a dedicated "redact-note" command post-MVP.
- `--format json` → mutation commands stay single-line per UX-DR7 and the PRD CLI spec at `prd.md:L960` which lists only `--add-note` / `--email` for this verb. Adding `--format json` would invite asymmetric piping: the operator pipes the mutation result but the subsequent `show` would be the canonical truth. Keep ConfirmationLine exclusivity — Story 1.6 establishes the same rule for `update-key`.
- `update-customer` on a tombstoned record → the `deleted_at IS NOT NULL` filter in `get_customer_detail` (Story 1.4) already treats tombstones as missing; surface the same "not found" error rather than allowing resurrection.
- Key updates → Story 1.6.
- Batch/CSV imports of note annotations → not on any epic roadmap.
- Importing from `keys.auth` or `keys.cache` — the CLI path cannot (architecture §Import Boundary Rules); the mutation is a plain SQLite write and the 60-second auth-cache TTL on the runtime side absorbs any downstream visibility delay (NFR6).
- Adding a `--yes` confirmation prompt — `update-customer` is UX-DR hierarchy **Mutate** tier (reversible — operator can run `--email` again with the right value; notes are append-only). Only **Destroy**-tier commands (`delete-customer --hard`, `revoke-key`, `rotate-encryption-key`) prompt.

## Acceptance Criteria

> BDD-style. Every AC has a unit or integration test. Source AC text lives in `_bmad-output/planning-artifacts/epics.md:L430-L453` — this block expands each item with the technical detail the dev agent must honour.

### AC1 — `--email` happy path changes only the email and audits the fields list (FR4, FR30, UX-DR7)

**Given** a customer `cust_01j…` exists with `email="helena@clinica.com"` and `notes="5 bots, WhatsApp booking"` (created via Story 1.1 `create-customer`)
**When** the operator runs `comadre-keys update-customer cust_01j… --email "helena@novaclinica.com"`
**Then**
- The `customer.email` column is updated to `"helena@novaclinica.com"`. No other column (`name`, `tax_id_kind`, `tax_id_encrypted`, `notes`, `registered_at`, `deleted_at`) changes — assert via direct-SQL snapshot before/after.
- A single row is appended to `audit_log` with `action="update_customer"`, `actor=f"cli:{os.getlogin()}"` (fallback to `getpass.getuser()` — Story 1.1 contract), `target_type="customer"`, `target_id=<customer.id>`, and `details_json='{"fields": ["email"]}'` (exact byte-equal literal — `json.dumps(..., sort_keys=True)` from `log_event`, list order is the sorted-literal `["email"]`).
- A ConfirmationLine on stdout: `Updated: cust_01j… (Helena Ribeiro) — email changed`. No border, no panel, no blank lines (UX-DR7). Trailing newline from `Console.print` is expected; no extra blank line.
- Exit code `0`. Stderr is empty except the single structured INFO log line `Updated customer | id=cust_01j… | fields=email` (routed to stderr per Story 1.3 `cli/__init__.py`).
- No change to any `api_key` row. No cache mutation (auth cache lives in the runtime process — CLI cannot touch it; the 60-second TTL bounds downstream auth latency for the next inbound request using the owning customer's key).

### AC2 — `--add-note` happy path preserves existing notes and appends a timestamped line (FR3, FR30)

**Given** a customer exists with `notes="5 bots, WhatsApp booking"`
**When** the operator runs `comadre-keys update-customer cust_01j… --add-note "paga tarde - lembrar dia 3"` on 2026-04-20 (clock frozen by test seam)
**Then**
- The `customer.notes` column becomes the exact literal `"5 bots, WhatsApp booking\n[2026-04-20] paga tarde - lembrar dia 3"`. The separator between the existing notes and the new entry is a single `\n` (LF). The new line starts with `[YYYY-MM-DD]` where the date is resolved in `settings.billing_timezone` via `_resolve_today_in_tz` (same seam as Story 1.2 `issue-key`). No trailing newline.
- The `customer.email` column is unchanged.
- A single `audit_log` row with `action="update_customer"`, `details_json='{"fields": ["notes"]}'`. **The note text itself is NOT in `details_json`** — FR37/NFR15 prohibit personal/operator-sensitive data in audit details. The audit record establishes "a note was appended on this day by this operator"; the note content lives in `customer.notes` alongside every other note.
- ConfirmationLine: `Updated: cust_01j… (Helena Ribeiro) — note added`.
- Exit `0`.

**Given** the same customer after AC2, the operator later runs a second `--add-note "upgraded 2026-05-12 from 60→120rpm"` on 2026-05-12
**When** the command executes
**Then**
- `customer.notes` is now `"5 bots, WhatsApp booking\n[2026-04-20] paga tarde - lembrar dia 3\n[2026-05-12] upgraded 2026-05-12 from 60→120rpm"`. Each subsequent append stacks one more `\n[YYYY-MM-DD] text` line at the end; earlier entries are byte-preserved.
- Two `audit_log` rows exist for this customer with `action="update_customer"` (one per command).

**Given** a customer whose `notes` column is empty (`""`)
**When** `update-customer … --add-note "first note"` runs on 2026-04-20
**Then** `customer.notes` becomes the literal `"[2026-04-20] first note"` — **no leading newline** (empty-existing-notes branch in the helper).

### AC3 — Combined `--email` + `--add-note` updates both in one transaction with one audit row (FR3, FR4, FR30)

**Given** a customer exists
**When** the operator runs `comadre-keys update-customer cust_01j… --email "new@e.com" --add-note "bumped tier 2026-04-20"`
**Then**
- Both `customer.email` and `customer.notes` are updated in a single `with conn:` transaction. Assert by monkey-patching `log_event` to raise on the first call: the email and notes changes must both roll back (no partial apply). Equivalently, snapshot both columns before, force a failure in the audit path via a `monkeypatch.setattr(db, 'log_event', raising_stub)`, run the command, assert exit code 5 AND both columns unchanged AND zero `audit_log` rows written.
- On success, a single `audit_log` row is written with `details_json='{"fields": ["email", "notes"]}'` (sorted alphabetically — `json.dumps(..., sort_keys=True)` gives us the key order, and the list itself is explicitly sorted in Python before serialization).
- ConfirmationLine: `Updated: cust_01j… (Helena Ribeiro) — email changed, note added`. The two-clause suffix uses `, ` (comma-space) as the separator — single-line only.
- Exit `0`.

### AC4 — Missing customer and tombstoned customer both map to "not found" exit 3 (UX-DR6, UX-DR10)

**Given** no customer matches `cust_01nonexistent0000000000000`
**When** the operator runs `comadre-keys update-customer cust_01nonexistent0000000000000 --add-note "x"`
**Then**
- ErrorDisplay panel on stderr with title `Customer not found: cust_01nonexistent0000000000000` and hint `Run 'comadre-keys list-customers' to see registered records.`
- Exit code `3`.
- No `audit_log` row is written (assert via `SELECT COUNT(*) FROM audit_log` delta = 0).

**Given** a customer exists but `deleted_at IS NOT NULL` (tombstoned by a future Story 4.1 hard-delete, seeded directly via SQL in the test fixture)
**When** `update-customer cust_<tombstoned> --add-note "x"` runs
**Then** the same `Customer not found` error and exit 3 (tombstones are opaque to CLI — Story 1.2 `get_customer` and Story 1.4 `show` already enforce this). No audit row written.

### AC5 — Usage errors on neither-flag, both-empty, invalid email, whitespace-only note (UX-DR10)

**Given** the operator omits both optional flags
**When** they run `comadre-keys update-customer cust_01j…`
**Then**
- ErrorDisplay title `Usage error: at least one of --email or --add-note is required`, hint `Provide --email NEW_EMAIL or --add-note "text" (or both).`
- Exit `2`.
- DB is not opened (assert `not (tmp_path / "registry.db").exists()` after the invocation — the usage check fires before `get_connection()`).

**Given** the operator passes `--email ""` (empty string)
**When** the command runs
**Then** Typer parses the empty string into `email=""`; the command treats it as "provided" but invalid at pydantic-validation time. ErrorDisplay title `Usage error: invalid email`, hint = the first pydantic error message (e.g., `"value is not a valid email address: An email address cannot be empty."`). Exit `2`. DB not touched.

**Given** the operator passes `--email "not-an-email"` (malformed)
**When** the command runs
**Then** same `Usage error: invalid email` title, hint = pydantic error message. Exit `2`.

**Given** the operator passes `--add-note "   "` (whitespace-only) or `--add-note ""`
**When** the command runs
**Then** ErrorDisplay title `Usage error: --add-note must be non-empty`, hint `Provide note text with content. Whitespace-only notes are rejected.`. Exit `2`. DB not touched. The `--add-note` is stripped (`text.strip()`) once at the start of the command body — the stored note preserves the operator's original interior spacing but trailing/leading whitespace is trimmed before length check.

**Given** the operator passes `--email "ok@e.com" --add-note "   "`
**When** the command runs
**Then** the note-validation error still fires and exits 2 — we validate both flags before opening the DB so a single usage mistake doesn't partially apply the email. The ordering: (a) neither-flag check → (b) email-shape check → (c) note-shape check → (d) DB open. This order puts the cheapest checks first and the most-expensive (DB connection) last.

### AC6 — Read-after-write: the DetailPanel reflects changes immediately (FR14 invariant)

**Given** AC1/AC2/AC3 have just completed successfully
**When** the operator runs `comadre-keys show <cust_id>` in a follow-up invocation
**Then** the DetailPanel body reflects the new `email` value and/or the updated `notes` block (each stamped entry on its own line — the Panel renders multi-line notes as-is; Rich wraps long lines within the Panel width).

This AC exists to lock in the contract that `update-customer` does not cache or buffer — a subsequent `show` reads the freshly-committed row via `get_customer_detail`. No `PRAGMA wal_checkpoint` is needed (SQLite readers see the committed transaction immediately).

### AC7 — `--help` renders a realistic example and does not open the DB (UX-DR15)

**Given** the operator runs `comadre-keys update-customer --help`
**Then**
- Typer prints usage with the two options visible. Option help strings include realistic examples (UX-DR15):
  - `--email` help: `Replace the stored email address. Example: --email "helena@novaclinica.com".`
  - `--add-note` help: `Append a dated note to the customer record. Example: --add-note "paga tarde - lembrar dia 3".`
- The docstring footer (epilog) contains `Example: comadre-keys update-customer cust_01j8xr3e4c5m7kn9p2qt8vwy --add-note "paga tarde - lembrar dia 3"`.
- Exit `0`. No DB file is created (assert `not (tmp_path / "registry.db").exists()` post-invocation — same guard as Story 1.1/1.2/1.3/1.4 for `--help`).

### AC8 — Anti-enumeration and log sanitization (FR37, NFR15, NFR16)

**Given** any `update-customer` invocation succeeds or fails
**Then**
- The structured INFO log (stderr) is exactly one line per successful command: `Updated customer | id=<cust_id> | fields=<csv>` where `<csv>` is `email`, `notes`, or `email,notes`. **Never** includes customer name, email value (old or new), note text, or any other field content.
- On `Customer not found`, the error title echoes only the operator-supplied literal (e.g., `cust_01nonexistent…`) — not any DB-derived value. Same shape for tombstone misses.
- The `audit_log.details_json` column contains only `{"fields": [...]}` — never the old email, new email, or note text. The `keys/audit.py` blocklist already rejects forbidden top-level keys (`email`, `cpf`, `cnpj`, `name`, `key_plaintext`, `authorization`, `tax_id`); we pass the change summary under the safe `"fields"` key, and a regression test seeds a `{"email": "x"}` payload to confirm `log_event` still raises `ValueError` on blocklist violations.
- `KEY_REGISTRY_ENCRYPTION_KEY` is **not** read or used by this command (tax-ID encryption is untouched). The command still validates settings load (exit 6 if `.env` is unreadable) to give the operator a consistent error surface.

### AC9 — No-op email (same value) is accepted and audited exactly like a change

**Given** `customer.email = "helena@clinica.com"`
**When** the operator runs `update-customer cust_… --email "helena@clinica.com"` (re-submits the current value)
**Then**
- The UPDATE executes; `rowcount == 1` (SQLite UPDATE matches on `WHERE id=? AND deleted_at IS NULL` without equality-comparing the new value to the old).
- An `audit_log` row with `details_json='{"fields": ["email"]}'` is written.
- ConfirmationLine: `Updated: … — email changed`.

Rationale: detecting and short-circuiting same-value updates adds branching complexity for a degenerate case the operator can avoid by not running the command. The audit trail records the operator's intent to set a value regardless of whether the DB write was a no-op — consistent with the "operator-initiated events go in the audit log" spirit of FR30.

### AC10 — Performance budget (NFR5)

**Given** a database with 1,000 customers and 5,000 audit rows seeded (temporary script, not committed)
**When** `update-customer cust_… --email "x@y.com" --add-note "bump"` runs end-to-end
**Then** wall-clock time is well under 500 ms (NFR5 detail-class budget). The SQL footprint is a single indexed `SELECT` by primary key + a single `UPDATE` + a single `INSERT INTO audit_log` — all O(1). Record the elapsed wall-clock in the Dev Agent Record (target: <50 ms end-to-end on the dev laptop; well within NFR5's 500 ms budget for a 10× safety margin).

## Tasks / Subtasks

Ordered for bottom-up construction. Each task ends with a runnable checkpoint. Do not reorder — imports chain downward.

- [x] **Task 1 — Extend `keys/db.py` with `update_customer` helper** (AC: #1, #2, #3, #4, #9)
  - [x] 1.1 Add the new helper + result dataclass to `src/comadre/keys/db.py`:
    ```python
    from typing import Literal

    UpdatedField = Literal["email", "notes"]


    @dataclass(frozen=True, slots=True)
    class UpdateCustomerResult:
        """Return payload from ``update_customer``.

        Carries the refreshed ``CustomerDetailRow`` so the CLI can feed it to
        the ConfirmationLine renderer without a follow-up ``get_customer_detail``
        round-trip. ``updated_fields`` is a sorted, de-duplicated tuple of the
        columns the caller actually touched — used for both the audit payload
        and the human suffix.
        """

        customer: CustomerDetailRow
        updated_fields: tuple[UpdatedField, ...]


    def update_customer(
        conn: sqlite3.Connection,
        customer_id: str,
        *,
        new_email: str | None,
        add_note: str | None,
        actor: str,
        today: date,
    ) -> UpdateCustomerResult | None:
        """Apply the email/notes mutation inside a single transaction.

        Returns ``None`` when the customer is missing or tombstoned.
        Otherwise commits the mutation + an ``update_customer`` audit row
        and returns the refreshed detail row.

        Callers MUST NOT wrap this in ``with conn:`` — the function owns
        its transaction so the UPDATE and the audit write either both
        commit or both roll back (same contract as ``insert_customer``).

        ``today`` is the operator-TZ date used to stamp the appended note
        (``[YYYY-MM-DD] text``). Passed by the caller so tests freeze the
        clock with ``monkeypatch.setattr(customers_cmd, '_resolve_today_in_tz', ...)``
        (Story 1.2 seam, reused in Story 1.4).
        """
        from comadre.keys.audit import log_event

        updated: list[UpdatedField] = []
        with conn:
            row = conn.execute(
                "SELECT notes FROM customer "
                "WHERE id = ? AND deleted_at IS NULL",
                (customer_id,),
            ).fetchone()
            if row is None:
                return None

            existing_notes = row["notes"] or ""
            new_notes = existing_notes
            if add_note is not None:
                stamped = f"[{today.isoformat()}] {add_note}"
                new_notes = (
                    stamped if not existing_notes else f"{existing_notes}\n{stamped}"
                )
                updated.append("notes")

            # Build the SET clause dynamically so only the touched columns
            # are rewritten. The predicate literals are hard-coded; operator
            # input only lands in positional ``?`` bindings.
            set_parts: list[str] = []
            params: list[object] = []
            if new_email is not None:
                set_parts.append("email = ?")
                params.append(new_email)
                updated.append("email")
            if add_note is not None:
                set_parts.append("notes = ?")
                params.append(new_notes)

            if not set_parts:
                # Defensive: the CLI layer rejects neither-flag before we get
                # here. If a future caller skips that check, we still don't
                # want to write a no-op audit row.
                return None

            params.append(customer_id)
            # Defense-in-depth: the SELECT above already filtered tombstones,
            # but adding `deleted_at IS NULL` to the UPDATE WHERE prevents a
            # mutation slipping through if a future caller restructures the
            # SELECT-then-UPDATE pair.
            sql = (
                f"UPDATE customer SET {', '.join(set_parts)} "
                "WHERE id = ? AND deleted_at IS NULL"
            )
            conn.execute(sql, params)

            fields_sorted = sorted(set(updated))
            log_event(
                conn,
                actor=actor,
                action="update_customer",
                target_type="customer",
                target_id=customer_id,
                details={"fields": fields_sorted},
            )

        refreshed = get_customer_detail(conn, customer_id)
        if refreshed is None:
            # Shouldn't happen — the row existed inside the transaction and
            # nothing else in this process is racing it. Map to a hard error
            # rather than silently returning None (which the CLI would read
            # as "tombstone" and surface an exit-3 instead of exit-5).
            raise RuntimeError(
                f"update_customer: row vanished after commit for {customer_id!r}"
            )
        return UpdateCustomerResult(
            customer=refreshed,
            updated_fields=tuple(sorted(set(updated))),
        )
    ```
  - [x] 1.2 The SQL build uses `", ".join(set_parts)` over a static list of literal column names (`"email = ?"`, `"notes = ?"`). Operator input never interpolates into the SQL text — only positional `?` bindings carry it. Matches Story 1.3 `list_api_keys` precedent; no f-string SQL violation.
  - [x] 1.3 Export nothing new from `keys/__init__.py` — callers use fully-qualified `from comadre.keys.db import update_customer, UpdateCustomerResult`.
  - [x] 1.4 Tests in `tests/test_keys_db.py` (append a new `TestUpdateCustomer` class):
    - `test_update_customer_email_only_changes_email_column` — seed customer; call helper with `new_email="x@y.com"`, `add_note=None`; assert returned `updated_fields == ("email",)`, DB `email` updated, `notes` unchanged, one audit row with `details_json='{"fields": ["email"]}'`.
    - `test_update_customer_note_only_changes_notes_column` — existing notes `"seed"`; call with `add_note="new"`, `today=date(2026, 4, 20)`; assert DB `notes == "seed\n[2026-04-20] new"`, email unchanged, `updated_fields == ("notes",)`, audit `details_json='{"fields": ["notes"]}'`.
    - `test_update_customer_note_on_empty_existing_no_leading_newline` — `notes=""`; assert result `"[2026-04-20] first"` (no leading `\n`).
    - `test_update_customer_note_appends_second_entry` — two successive calls; assert `notes` ends with both stamped lines separated by `\n`.
    - `test_update_customer_both_email_and_note_in_one_txn` — assert both columns change, one audit row, `details_json='{"fields": ["email", "notes"]}'` (sorted).
    - `test_update_customer_missing_returns_none` — unknown `customer_id`; assert helper returns `None`, zero audit rows written.
    - `test_update_customer_tombstone_returns_none` — seed row, set `deleted_at` via direct SQL; assert helper returns `None`, zero audit rows, no mutation to the tombstoned row.
    - `test_update_customer_rolls_back_when_audit_fails` — monkey-patch `comadre.keys.db.log_event` (imported lazily inside the helper, so patch `comadre.keys.audit.log_event`) to raise `sqlite3.IntegrityError`; call helper; assert `email` and `notes` unchanged in DB (transaction rolled back) AND no audit row written. **Important:** the `with conn:` block converts the exception into a rollback before re-raising, so the caller observes `sqlite3.IntegrityError`. Matches Story 1.1's `test_no_inner_transaction` pattern.
    - `test_update_customer_same_email_value_still_audits` — AC9; seed `email="a@b.com"`, call with same value; assert audit row still written with `{"fields": ["email"]}`.
    - `test_update_customer_audit_details_does_not_leak_values` — capture the most recent `audit_log.details_json`; assert the literal email / note text is not substring-present anywhere in the row (details_json, actor, action).
    - `test_update_customer_today_uses_caller_supplied_value` — pass `today=date(2030, 1, 1)`; assert the stamped line starts with `[2030-01-01]` (confirms the clock is caller-controlled, not `date.today()`).

- [x] **Task 2 — `update-customer` command** (AC: #1–#10)
  - [x] 2.1 Extend `src/comadre/keys/cli/commands/customers.py`:
    ```python
    from pydantic import TypeAdapter, ValidationError
    from pydantic_core import PydanticCustomError  # if needed for the error message

    _EMAIL_ADAPTER = TypeAdapter(EmailStr)  # reused; construction is cheap but
                                            # the adapter caches its schema.

    _UPDATE_CUSTOMER_HINTS = {
        "neither_flag": (
            "Provide --email NEW_EMAIL or --add-note \"text\" (or both)."
        ),
        "note_empty": (
            "Provide note text with content. Whitespace-only notes are rejected."
        ),
    }


    @app.command("update-customer")
    def update_customer_cmd(
        customer_id: str = typer.Argument(
            ...,
            metavar="CUSTOMER_ID",
            help=(
                "Customer ID from create-customer / list-customers. "
                "Example: cust_01j8xr3e4c5m7kn9p2qt8vwy."
            ),
        ),
        email: str | None = typer.Option(
            None,
            "--email",
            help=(
                "Replace the stored email address. "
                'Example: --email "helena@novaclinica.com".'
            ),
        ),
        add_note: str | None = typer.Option(
            None,
            "--add-note",
            help=(
                "Append a dated note to the customer record. "
                'Example: --add-note "paga tarde - lembrar dia 3".'
            ),
        ),
    ) -> None:
        """Update a customer's email and/or append a dated operator note.

        Example: comadre-keys update-customer cust_01j8xr3e4c5m7kn9p2qt8vwy
                 --add-note "paga tarde - lembrar dia 3"
        """
        ...
    ```
  - [x] 2.2 Command body, in order:
    1. **Neither-flag check.** If `email is None and add_note is None` → ErrorDisplay title `Usage error: at least one of --email or --add-note is required`, hint from `_UPDATE_CUSTOMER_HINTS["neither_flag"]`. Exit `2`. **DB not opened.**
    2. **Email shape check (if provided).** Run `_EMAIL_ADAPTER.validate_python(email)`. On `ValidationError` → ErrorDisplay title `Usage error: invalid email`, hint = `first_error_msg(exc)` (existing `_errors.py` helper). Exit `2`. DB not opened. The validation returns the canonical email (pydantic's `EmailStr` coerces trailing whitespace off and lowercases the domain); reassign `email` to the canonical form so the UPDATE writes the normalized string.
    3. **Note shape check (if provided).** `stripped = add_note.strip()`; if not `stripped` → ErrorDisplay title `Usage error: --add-note must be non-empty`, hint from `_UPDATE_CUSTOMER_HINTS["note_empty"]`. Exit `2`. DB not opened. Reassign `add_note = stripped` so interior text is preserved but leading/trailing whitespace never reaches the DB.
    4. **Settings load.** Same try/except ladder as `create-customer` / `list-customers` / `show` — exit `6` on `ValidationError`/`OSError`/missing encryption key (use `_missing_key_hint` + `is_missing_encryption_key` + `first_error_msg`). The encryption key isn't actually used by this command (no Fernet operation), but we validate it exists so the operator gets the same config-error surface across all `comadre-keys` verbs. One less "why did this command run but that one failed" confusion.
    5. **Resolve billing-TZ date.** `billing_tz = ZoneInfo(settings.billing_timezone)` with the `ZoneInfoNotFoundError | ValueError` → exit 6 mapping (same shape as `show`). `today = _resolve_today_in_tz(billing_tz)`.
    6. **Open DB + migrations.** `get_connection()` in a try/finally + `contextlib.suppress(sqlite3.Error)` on close. `_apply_migrations(conn)` inside a try/except `sqlite3.Error` → exit `5`.
    7. **Call the helper.**
       ```python
       try:
           result = update_customer(
               conn,
               customer_id,
               new_email=email,
               add_note=add_note,
               actor=get_cli_actor(),
               today=today,
           )
       except sqlite3.Error as exc:
           render_error("Database error", str(exc))
           raise typer.Exit(code=5) from None
       ```
    8. **Branch on the result.**
       - `result is None` → ErrorDisplay title `Customer not found: {customer_id}`, hint `Run 'comadre-keys list-customers' to see registered records.`. Exit `3`.
       - Otherwise → structured INFO log (stderr) `Updated customer | id=%s | fields=%s`, `customer_id`, `",".join(result.updated_fields)`. Then emit the ConfirmationLine.
    9. **ConfirmationLine assembly.** Map `updated_fields` to the human suffix:
       - `("email",)` → `"email changed"`.
       - `("notes",)` → `"note added"`.
       - `("email", "notes")` → `"email changed, note added"`.
       - Full line: `f"Updated: {result.customer.id} ({result.customer.name}) — {suffix}"`. The em-dash is U+2014 to match `create-customer` / `issue-key` precedent.
       - `render_confirmation(line)` — stdout, no panel.
    10. Exit `0` implicit.
  - [x] 2.3 No change needed in `app.py` — `app.registered_commands.extend(customers_app.registered_commands)` already picks up new `@customers_app.command(...)` entries. Verify via `uv run comadre-keys --help` that `update-customer` appears alongside `create-customer`, `issue-key`, `list-customers`, `list-keys`, `show`.
  - [x] 2.4 The command imports `update_customer` + `UpdateCustomerResult` from `comadre.keys.db` (add to the existing import block in `customers.py`). Also extend the pydantic import to `from pydantic import EmailStr, TypeAdapter, ValidationError` — `EmailStr` is not currently imported directly in `customers.py` (the module only touches `ValidationError`), and the adapter needs both. We construct the adapter directly rather than round-tripping through `CustomerCreate` (the latter would require `name` / `tax_id_kind` / `tax_id_digits` which aren't in scope here).

- [x] **Task 3 — Integration tests: `update-customer`** (AC: #1–#10)
  - [x] 3.1 Create `tests/test_keys_cli_update_customer.py`. Reuse the three autouse fixtures from `test_keys_cli_show.py` (`_clear_settings_cache`, `_reset_consoles_to_buffers`, `env`) and the helpers (`_buffers`, `_clear_buffers`, `_seed_customer`, `_count`). Copy verbatim — a shared `conftest.py` extraction is deferred until at least four test files reuse them (now at four: list-customers, list-keys, show, update-customer). **Action:** when Task 3 completes, open a follow-up note in `deferred-work.md` flagging the shared fixture extraction — four copies is the last tolerable threshold per Story 1.4 notes.
  - [x] 3.2 Freeze the clock via:
    ```python
    @pytest.fixture()
    def _freeze_today(monkeypatch: pytest.MonkeyPatch):
        import comadre.keys.cli.commands.customers as customers_cmd
        from datetime import date

        def _factory(frozen: date):
            monkeypatch.setattr(
                customers_cmd, "_resolve_today_in_tz", lambda tz: frozen
            )

        return _factory
    ```
    Same signature as Story 1.2's `_freeze_today` — the monkey-patch target is `customers_cmd._resolve_today_in_tz` (the underscore-alias re-export established in Story 1.4 Task 6).
  - [x] 3.3 Tests:
    - **AC1 — email happy path:** `test_update_customer_email_only` — seed customer; run with `--email "new@e.com"`; assert exit 0, ConfirmationLine literal `Updated: cust_01… (Helena Ribeiro) — email changed`, DB `email = "new@e.com"`, DB `notes` unchanged, one audit row with `details_json == '{"fields": ["email"]}'`.
    - **AC2 — note happy path:** `test_update_customer_add_note_stamps_date` — freeze today to `date(2026, 4, 20)`, seed customer with `notes="5 bots"`, run `--add-note "paga tarde"`; assert DB notes equal the literal `"5 bots\n[2026-04-20] paga tarde"`, ConfirmationLine `— note added`, audit fields `["notes"]`.
    - **AC2 — second append stacks:** `test_update_customer_add_note_second_append_stacks`.
    - **AC2 — empty-existing notes:** `test_update_customer_add_note_on_empty_notes_no_leading_newline` — seed `notes=""` via direct SQL, freeze 2026-04-20, run `--add-note "first"`; assert DB notes == `"[2026-04-20] first"` (no leading `\n`).
    - **AC3 — both flags in one txn:** `test_update_customer_both_flags` — assert both columns change, one audit row, `details_json == '{"fields": ["email", "notes"]}'`, ConfirmationLine suffix `— email changed, note added`.
    - **AC3 — rollback on audit failure:** `test_update_customer_rolls_back_when_log_event_fails` — monkey-patch `comadre.keys.audit.log_event` to raise `sqlite3.IntegrityError`; run the command; assert exit 5, email/notes unchanged in DB, zero audit rows.
    - **AC4 — missing customer:** `test_update_customer_missing_exits_3` — run on `cust_01nonexistent0000000000000`; assert stderr has `Customer not found: cust_01nonexistent0000000000000`, exit 3, zero audit rows written to the DB.
    - **AC4 — tombstone:** `test_update_customer_tombstone_treated_as_missing` — seed customer, tombstone via direct SQL (`UPDATE customer SET deleted_at = ? WHERE id = ?`), run command; assert same `Customer not found` shape + exit 3 + zero audit rows + DB row's `deleted_at` unchanged.
    - **AC5 — neither flag:** `test_update_customer_without_flags_exits_2` — run `update-customer <cust_id>` with no options; assert exit 2, title `Usage error: at least one of --email or --add-note is required`, DB file not created (assert `not (tmp_path / "registry.db").exists()` — the check runs before `get_connection()`).
    - **AC5 — empty email:** `test_update_customer_empty_email_exits_2`.
    - **AC5 — malformed email:** `test_update_customer_malformed_email_exits_2` — run `--email "not-an-email"`; assert exit 2, title `Usage error: invalid email`.
    - **AC5 — whitespace note:** `test_update_customer_whitespace_note_exits_2` — `--add-note "   "`; assert exit 2, title `Usage error: --add-note must be non-empty`, DB not opened.
    - **AC5 — empty note:** `test_update_customer_empty_note_exits_2`.
    - **AC5 — NUL byte in note:** `test_update_customer_nul_byte_note_exits_2` — run `--add-note "ok\x00danger"`; assert exit 2, title `Usage error: --add-note contains illegal characters`, hint `Note text must not contain NUL bytes.`; DB not opened.
    - **AC5 — note-stripped preserves interior whitespace:** `test_update_customer_note_strips_outer_not_inner` — seed, run `--add-note "  spaced  inside  "`; assert DB notes ends with `"[2026-04-20] spaced  inside"` (leading/trailing stripped, interior two-space gaps preserved).
    - **AC5 — ordering: both flags, note invalid, email valid:** `test_update_customer_both_flags_note_invalid_exits_2_no_email_change` — freeze today, seed customer, run `--email "ok@e.com" --add-note " "`; assert exit 2, DB email unchanged, zero audit rows.
    - **AC6 — read-after-write:** `test_update_customer_then_show_reflects_changes` — seed, `update-customer --email new --add-note "x"`, clear buffers, run `show <cust_id>`; assert the DetailPanel body contains the new email AND the stamped note line.
    - **AC7 — help surface:** `test_update_customer_help_has_realistic_examples` — `update-customer --help`; strip ANSI + Panel glyphs (reuse Story 1.3/1.4's normaliser); assert `cust_01j8xr`, `helena@novaclinica.com`, `paga tarde`, `--email`, `--add-note` all present; assert the epilog `Example: comadre-keys update-customer cust_01j8xr3e4c5m7kn9p2qt8vwy --add-note` substring. Assert `not (tmp_path / "registry.db").exists()` after `--help` returns.
    - **AC8 — log sanitization:** `test_update_customer_log_has_no_pii` — attach a throwaway `logging.Handler` to `keys.cli` (Story 1.3 pattern — `caplog` is blind because `propagate=False`); run `update-customer --email "secret@example.com" --add-note "sensitive"`; assert log record contains `Updated customer | id=cust_… | fields=email,notes` AND does NOT contain `secret@example.com`, `sensitive`, `Helena Ribeiro`, or any substring of the note text.
    - **AC8 — audit-details sanitization:** `test_update_customer_audit_details_json_no_pii` — run mutation; SELECT the latest `audit_log.details_json`; assert the literal email / note text is absent; assert the row parses to exactly `{"fields": [...]}`.
    - **AC9 — same-value email still audits:** `test_update_customer_same_email_still_audits` — seed `email="a@b.com"`, run `--email "a@b.com"`; assert exit 0, audit row count +1, `details_json` == `{"fields": ["email"]}`, ConfirmationLine still says `— email changed`.
    - **Regression — read-only contract for `list-customers`:** `test_update_customer_then_list_customers_counts_unchanged` — seed 2 customers, update one; `list-customers` still shows both, key counts unchanged.
    - **Regression — Epic 4.5 audit blocklist still active:** `test_update_customer_blocklist_intercepts_forbidden_details` — directly call `log_event` with `details={"email": "x"}` (smoke test of the existing blocklist — proves a future refactor that drops our `{"fields": [...]}` wrapping would immediately fail).

- [x] **Task 4 — Quality gates**
  - [x] 4.1 `uv run ruff check . && uv run ruff format --check .` — zero warnings on all new/modified files.
  - [x] 4.2 `uv run mypy src/comadre/keys/` — zero errors in strict mode. The new `UpdateCustomerResult` dataclass should need no `cast(...)` at call sites (the CLI unwraps `updated_fields` directly from the result value — no union narrowing required).
  - [x] 4.3 `uv run pytest` — all new tests pass; Story 1.4 closed at ~800 tests; Story 1.5 adds ~25–35 tests; target final count ≈ 825–835.
  - [x] 4.4 `uv run pre-commit run --all-files` — all hooks pass (ruff, mypy, hadolint, yamllint, shellcheck, markdownlint-cli2).
  - [x] 4.5 Do NOT update `sprint-status.yaml` — that transition happens when the reviewer moves the story to `done` via the `code-review` workflow.
  - [x] 4.6 **Non-regression guard rails for Epic 4.5 CI:**
    - `rg 'HTTPException' src/comadre/keys/cli/commands/customers.py` — empty (FR51).
    - `rg 'f"UPDATE|f"DELETE|f"INSERT' src/comadre/keys/db.py` — only the Story 1.5 `set_parts` join (which is a literal-column-name join, not an f-string with operator input). The grep should show zero NEW f-string SQL containing `{customer_id}`, `{email}`, or any other parameter name — only the column-literal join that feeds into positional `?` bindings.
    - `rg '\bprint\(' src/comadre/keys/cli/commands/customers.py` — no bare builtin `print(`. Only `console.print(...)` is permitted (Story 1.3 precedent).
    - `rg 'os\.environ' src/comadre/keys/` — empty.
    - `rg 'tax_id_encrypted' src/comadre/keys/cli/commands/customers.py` — only the existing Story 1.1 `create-customer` write path; `update-customer` must NOT read or write `tax_id_encrypted`.
  - [x] 4.7 **Performance sanity (NFR5).** On a DB seeded with 1,000 customers + 5,000 audit rows (temporary one-off script, not committed), `time uv run comadre-keys update-customer <cust_id> --email "x@y.com" --add-note "bump"` completes in well under 500 ms. The SQL footprint is `SELECT by primary key → UPDATE by primary key → INSERT INTO audit_log`, all O(1). Record the wall-clock in the Dev Agent Record.

- [x] **Task 5 — Manual verification**
  - [x] 5.1 **Hot-path smoke.** From a fresh `./data/keys/registry.db`, run:
    ```bash
    uv run comadre-keys create-customer --name "Helena Ribeiro" --email "helena@clinica.com" --cpf "123.456.789-09" --notes "5 bots, WhatsApp booking"
    uv run comadre-keys update-customer <cust_id> --add-note "paga tarde - lembrar dia 3"
    uv run comadre-keys update-customer <cust_id> --email "helena@novaclinica.com"
    uv run comadre-keys show <cust_id>
    ```
    Confirm: (a) both updates print a single-line confirmation on stdout; (b) `show` renders the new email AND a `Notes:` field whose body contains the original seed text and two stamped lines on successive rows (Rich wraps the multi-line body inside the panel); (c) the DB file remains mode `0600`; (d) no stderr noise beyond the structured INFO logs.
  - [x] 5.2 **Error panels.** Run `update-customer <cust_id>` (no flags), `update-customer nope --email ok@e.com`, `update-customer <cust_id> --email not-an-email`, `update-customer <cust_id> --add-note "  "`; confirm each prints a red-bordered ErrorDisplay on stderr and exits with the expected code (2, 3, 2, 2).
  - [x] 5.3 **Log piping.** Tail the structured log (`2>&1 1>/dev/null`) during each happy-path invocation; confirm `Updated customer | id=cust_… | fields=email` (or `notes`, or `email,notes`) lines appear on stderr; confirm no customer name, email value, or note text ever appears in the log stream.
  - [x] 5.4 **Audit inspection.** `sqlite3 ./data/keys/registry.db "SELECT actor, action, target_id, details_json FROM audit_log ORDER BY id DESC LIMIT 5;"` — confirm `action=update_customer`, `details_json='{"fields": ["email"]}'` (or `["notes"]`, or `["email", "notes"]`) exactly, and that no ciphertext / plaintext / PII appears in any column.

## Dev Notes

### Architecture invariants (from `_bmad-output/planning-artifacts/architecture.md`)

- **Import graph downward-only.** Story 1.5 adds a command to `cli/commands/customers.py` and a helper to `db.py`. No module-order changes. **Must not import from `keys.auth` or `keys.cache`** — those modules still don't exist and the CLI path is forbidden from touching them even after they land. [Source: `architecture.md#Import-Boundary-Rules` L366-L372]
- **CLI / runtime separation.** Do NOT touch `main.py`, `api.py`, `rate_limit.py`, `service.py`, `config.py`, `exceptions.py`. Preserves the 1.6.2 public contract byte-for-byte. [Source: `architecture.md` L519-L521]
- **No raw HTTPException.** Errors flow through `render_error(...)` + `typer.Exit(code=...)` with the AC exit-code mapping. [Source: `architecture.md#Enforcement-Guidelines` L471-L488]
- **No `print()`.** All output via `render_confirmation` / `render_error`. Structured logging via `get_logger("keys.cli")`, which is already routed to stderr by `src/comadre/keys/cli/__init__.py` (Story 1.3 fix — load-bearing for anyone downstream piping `update-customer` into a script, even though Story 1.5 has no `--format json`). [Source: Story 1.3 Dev Agent Record.]
- **Parameterized SQL only.** The `set_parts` join builds an UPDATE statement from literal column names (`"email = ?"`, `"notes = ?"`). Operator input lands only in positional `?` bindings. Matches `list_api_keys` (Story 1.3) and `list_audit_events` (Story 1.4) predicate-assembly precedent — no f-string SQL containing parameters. [Source: `architecture.md#SQLite-Query-Patterns` L376-L383]
- **Transaction scope.** The helper owns `with conn:`; callers must NOT wrap. Same contract as `insert_customer` (Story 1.1) and `insert_api_key` (Story 1.2). The audit row is written INSIDE the same transaction so rollback is atomic. [Source: `architecture.md#Transaction-Scope` L465-L469]
- **Audit write contract.** `log_event(...)` is called with `details={"fields": [...]}` — the existing case-insensitive blocklist in `keys/audit.py` rejects `email`, `cpf`, `cnpj`, `name`, `key_plaintext`, `authorization` at the top level (and within nested dicts). We pass the change summary under the safe `"fields"` key; the blocklist doesn't trigger because `"fields"` isn't on the list. A regression test feeds a forbidden key directly to `log_event` to confirm the blocklist still fires. [Source: `src/comadre/keys/audit.py` L23-L44]

### Data contracts

- `customer.email` — TEXT NOT NULL. Story 1.1 validates via `pydantic.EmailStr`; Story 1.5 revalidates via the same `EmailStr` through a `TypeAdapter` at the CLI entry. Storage is the canonical pydantic-normalized string (lowercased domain, trimmed whitespace). [Source: `src/comadre/keys/migrations/v001_initial.sql` L4, `src/comadre/keys/models.py` L31]
- `customer.notes` — TEXT DEFAULT `''`. Story 1.5 appends `"[YYYY-MM-DD] text"` lines separated by `\n`. No column-length enforcement at the SQL layer (SQLite TEXT is unbounded); the deferred-work item "unbounded --notes length" from Story 1.1 stays deferred — operators self-moderate note length, and the DetailPanel wraps long bodies via Rich.
- `audit_log.details_json` — TEXT, nullable. Story 1.5 writes `'{"fields": [...]}'` via `json.dumps(..., sort_keys=True)` (inherited from `log_event`). Fixed key order so test assertions can compare byte-exact strings.
- `audit_log.target_type` / `audit_log.target_id` — `"customer"` / `<cust_id>`. No key-level audit entries — a customer-email-change has zero direct effect on any key row, so scoping the audit event to the customer target keeps `show <key-prefix> --audit-tail` output clean.
- **Clock seam** — the date stamp in the appended note comes from `_resolve_today_in_tz(ZoneInfo(settings.billing_timezone))` — the same alias-to-`cli._clock.resolve_today_in_tz` that `issue-key` (Story 1.2) and `show` (Story 1.4) import. Tests monkey-patch `customers_cmd._resolve_today_in_tz` to freeze the date; the helper receives `today` as a parameter so the SQL stays pure and the helper is testable without clock mocking.

### Library version gotchas

- **`pydantic.EmailStr` via `TypeAdapter`.** Construct once at module scope (`_EMAIL_ADAPTER = TypeAdapter(EmailStr)`) — the adapter caches its schema and the per-invocation cost is a single validation. `TypeAdapter(EmailStr).validate_python(value)` returns the canonical form (lowercased domain) or raises `pydantic.ValidationError`. Use `first_error_msg(exc)` (existing `_errors.py` helper) to extract the human message for the ErrorDisplay hint.
- **`pydantic` auto-strips whitespace** from string inputs when `EmailStr` is the type? **No — pydantic v2 does NOT strip whitespace from `EmailStr` by default.** We don't rely on implicit trimming; the command pre-strips the `--email` value via `email = email.strip()` before adapter validation (add this to Task 2.2 step 2 explicitly — it's easy to forget). Treat empty-after-strip as the invalid-email branch (pydantic will reject it anyway, but explicit is better than implicit).
- **`sqlite3.Row` + `row_factory`.** The existing `get_connection` sets `conn.row_factory = sqlite3.Row` so our `SELECT notes FROM customer` returns a row you can index by `row["notes"]`. `None` on missing; we test via `if row is None`.
- **`with conn:` + exception → rollback.** The `with conn:` block auto-rolls back on any exception before re-raising. The Story 1.1 `test_no_inner_transaction` pattern covers this; Story 1.5's `test_update_customer_rolls_back_when_audit_fails` is the corresponding check for the update path.
- **`date.isoformat()` returns `YYYY-MM-DD`** in ISO 8601. Stable for the note stamp. `date.fromisoformat("2026-04-20")` parses it back. No timezone ambiguity because `_resolve_today_in_tz` resolves the local date in the billing TZ before passing it to the helper.

### Previous story intelligence (Stories 1.1, 1.2, 1.3, 1.4)

- **CliRunner Click 8.2+ pattern.** `CliRunner()` with no `mix_stderr=False`. Wire stdout/stderr to `StringIO` via `_reset_for_tests()` + fixture-assigned `output_mod._stdout_console` / `_stderr_console`. **Copy the three autouse fixtures from `tests/test_keys_cli_show.py` verbatim** — same pattern used across the entire CLI test suite.
- **Help-only invocations do not open the DB.** Assert `not (tmp_path / "registry.db").exists()` after `--help` runs. Carry this invariant into `update-customer --help`.
- **`_reset_for_tests()` teardown is mandatory** — without it, a subsequent test's autouse fixture inherits a console that's already buffered-out.
- **`get_cli_actor()` contract.** Returns `"cli:<unix-username>"` with `os.getlogin()` → `getpass.getuser()` → `"cli:unknown"` fallback chain. Don't re-implement; import from `comadre.keys.audit`.
- **Log-capture pattern.** Attach a throwaway `logging.Handler` directly to the `keys.cli` logger because `propagate=False` makes `caplog` blind (Story 1.3 `TestLogSanitization` pattern; Story 1.4 `test_show_log_has_kind_not_names` reused it). Use the same idiom for `test_update_customer_log_has_no_pii`.
- **`_resolve_today_in_tz` seam.** Lives in `src/comadre/keys/cli/_clock.py` (Story 1.4 Task 6) and is re-exported from `cli/commands/keys.py` and `cli/commands/customers.py` under the underscore alias `_resolve_today_in_tz`. Test monkey-patch target: `comadre.keys.cli.commands.customers._resolve_today_in_tz`. Story 1.2's `_freeze_today` fixture is the reference implementation.
- **`_errors.py` helpers.** `first_error_msg(exc: ValidationError) -> str` returns the first-field human message; `is_missing_encryption_key(exc)` tests the "KEY_REGISTRY_ENCRYPTION_KEY not set" path. Both are already imported by `customers.py` — no new imports.
- **`_missing_key_hint`.** The module-level string literal in `customers.py` for the exit-6 hint. Story 1.5 reuses it verbatim — no duplicate constant.
- **Help-text normalisation for assertions.** Typer `--help` renders inside a Rich panel whose border glyphs (`│ ╭ ╮ ╰ ╯ ─`) fragment long option strings across rows. Strip those glyphs **before** collapsing whitespace; Story 1.3 and Story 1.4 established the exact `re.sub` pair. Reuse verbatim in Task 3's `test_update_customer_help_has_realistic_examples`.

### Git intelligence

Last 5 commits on master (as of 2026-04-17 late afternoon, after Story 1.4's code-review land):
- `7924586 feat(keys): land story 1.4 — comadre-keys show with DetailPanel, AuditTail, JSON output, and code-review fixes` — adds `get_customer_detail`, `CustomerDetailRow`, `render_customer_detail`, `_resolve_today_in_tz` relocation, `_SHOW_NOT_FOUND_HINT`, JSON serializers. All directly consumed by Story 1.5.
- `f4ceb97 feat(keys): land story 1.3 — list-customers + list-keys with StatusTable, filters, JSON, and code-review fixes` — the stderr log-routing fix in `cli/__init__.py` is load-bearing for Story 1.5's log-sanitization AC even though we don't emit JSON ourselves.
- `612d952 feat(keys): land story 1.2 — comadre-keys issue-key with one-shot KeyPanel` — `_format_brl`, clock seam, ConfirmationLine precedent.
- `50cdada feat(keys): land story 1.1 impl, draft story 1.2, validate-docbr migration` — foundational subpackage, v001 schema, `insert_customer`, audit blocklist.
- `a696c68 feat(voices): add pf_influencer_02 voice profile` — unrelated voice work.

Working tree at story start: the create-story workflow introduces this story file and bumps `sprint-status.yaml`. Story 1.5 implementation begins from a clean tree with Story 1.4 landed.

### Deferred-work items relevant to this story

From `_bmad-output/implementation-artifacts/deferred-work.md`:

- **Story 1.1 deferred, now actionable:** "CLI UX edges on optional fields. NUL byte in `--name`/`--email`, whitespace-only `--name`, unbounded `--notes` length, repeated `--cpf` flag. Address when building the `update-customer` command in Story 1.5 — the validators will be shared." **Action in Story 1.5:**
  - **Whitespace-only `--email`.** Handled: pre-strip in Task 2.2 step 2 + pydantic `EmailStr` rejects empty/whitespace strings.
  - **NUL byte in `--email` / `--add-note`.** Pydantic `EmailStr` rejects NUL in email (malformed). For `--add-note` we add an explicit `"\x00" in add_note → Usage error` guard in Task 2.2 step 3 (belt-and-suspenders — SQLite accepts NUL bytes but they'd corrupt the stored notes column and mess with later greps). Hint: `Note text must not contain NUL bytes.`.
  - **Unbounded `--notes` length.** Left unbounded for Story 1.5 (consistent with Story 1.1 `--notes`). Flag for a follow-up hardening pass that picks a cap across both commands at once.
  - **Repeated `--email` / `--add-note` flag.** Typer's default is "last wins" for single-value options; no test needed (Typer / Click semantics are stable). Flag if a future operator surprise surfaces.
- **Story 1.1 deferred, still deferred:** `os.getlogin()` log-injection sanitization. We reuse `get_cli_actor()` unchanged. The threat is theoretical `utmp` poisoning; the audit row still survives because the actor column is TEXT. Sanitize when next touching `audit.py`.
- **Story 1.1 deferred, still deferred:** `AC8 occurred_at per-transaction invariant`. `log_event` still computes its own timestamp per call — fine for Story 1.5 (one audit row per txn). Blocks only multi-row-audit stories (e.g., 4.1 `delete-customer --hard` which touches customer + keys + audit in one txn).
- **Story 1.2 deferred, still deferred:** "`comadre-keys` CLI requires TTS-side config fields it doesn't need." Story 1.5 inherits the same limitation — a `.env` with `API_KEY=test` + `KEY_REGISTRY_ENCRYPTION_KEY=<fernet>` is sufficient. Epic 2 splits settings.
- **Story 1.4 deferred, still deferred:** Rich markup injection via stored `name` / `notes`. A customer whose notes contain `[red]X[/]` would re-style any DetailPanel that renders them. Pre-existing across all `render_*` helpers. Story 1.5 adds a *writer* for `notes` but does not introduce the injection surface (the reader is Story 1.4's `render_customer_detail`). Still a cross-cutting hardening concern; no change in Story 1.5.

### UX invariants reproduced from `ux-design-specification.md`

- **UX-DR6 ErrorDisplay** (`ux:L826-L833`): red-bordered stderr Panel, title = message, body = hint. Exit code per UX-DR10.
- **UX-DR7 ConfirmationLine** (`ux:L835-L846`): plain single line on stdout via `Console.print(...)`. No panel, no border, no blank lines. Story 1.5 suffix grammar: `"— email changed"` / `"— note added"` / `"— email changed, note added"` (comma-space join, U+2014 em-dash).
- **UX-DR9 Shared Console** (`ux:L250-L256`): all output through `stdout_console()` / `stderr_console()`. Already wired by existing `render_*` helpers.
- **UX-DR10 Exit codes** (`ux:L1046-L1056`): 0 success, 2 usage, 3 not-found, 5 database, 6 config. Story 1.5 uses exactly these five codes. **No exit 4** — the tax-ID validation path (the only producer of exit 4 so far) is absent here.
- **UX-DR15 Realistic `--help` examples** (`ux:L995-L1013`): realistic values in every option help string and the epilog example line.
- **UX-DR16 Terminal width adaptation** (`ux:L1063-L1081`): 80-col minimum. The ConfirmationLine is a single line — may wrap on <80-col terminals but Rich handles soft-wrapping automatically. No custom abbreviation logic needed.

### Scope guards (things NOT to do in Story 1.5)

- **Do NOT add `--name`, `--cpf`, `--cnpj` flags.** Out of PRD CLI spec. Name/tax-ID updates are out of scope for 2.0.0 entirely — the only way to change them today is `delete-customer --hard` (Story 4.1) + re-create.
- **Do NOT add `--format json`.** UX-DR7 and PRD `prd.md:L960` keep mutation output single-line.
- **Do NOT add `--yes`.** This is a Mutate-tier command, not Destroy-tier. No confirmation prompt, no `--yes` flag.
- **Do NOT add a migration file.** Schema is unchanged — `customer.email` / `customer.notes` have existed since v001.
- **Do NOT add a new dependency.** Story 1.5 uses `typer`, `pydantic` (already depended on), `sqlite3` / `datetime` / `json` (stdlib).
- **Do NOT touch `src/comadre/main.py`, `api.py`, `rate_limit.py`, `service.py`, `config.py`, `exceptions.py`, or `cli/app.py`.** `cli/app.py` picks up the new command via the existing `app.registered_commands.extend(customers_app.registered_commands)` flow — no edits needed.
- **Do NOT regress Story 1.3's `keys.cli` → stderr log routing.** Even though Story 1.5 has no JSON stdout, a future operator scripting `update-customer` into a CI job depends on stdout being noise-free.
- **Do NOT audit the old/new email values or the note text.** FR37/NFR15. The `keys/audit.py` blocklist will reject `{"email": "..."}` at the top level — do not bypass by renaming the key to `{"new_email_value": "..."}` either. The `{"fields": [...]}` summary is the intended contract.
- **Do NOT allow updates on tombstoned customers.** Tombstones are opaque (Story 1.2 `get_customer`, Story 1.4 `show`). Silently resurrecting a tombstoned row would violate the LGPD deletion contract FR5 / FR38.
- **Do NOT normalize or canonicalize the note text beyond `.strip()`.** Operator wrote what they wrote; we only trim outer whitespace and reject empty-after-strip.
- **Do NOT re-implement `_format_brl`, `_iso_date`, `_status_label`, `render_confirmation`, `render_error`, `_resolve_today_in_tz`, or `_missing_key_hint`.** Import and reuse.

### Enumeration resistance & log sanitization (FR37, NFR15, NFR16)

- **`Customer not found` error** echoes only the operator-supplied `customer_id` (their own input, not an enumerated DB value). No "found in tombstone" branch — tombstoned customers yield the same `Customer not found` title as never-existed IDs. Rationale: revealing "this ID used to exist" would let an operator with stolen terminal access enumerate historical customers.
- **`audit_log.details_json`** carries only `{"fields": [...]}`. No old/new email, no note text. Story 1.5 test `test_update_customer_audit_details_json_no_pii` asserts the row body contains no literal email / note substring.
- **Structured INFO log** (stderr) format: `Updated customer | id=<cust_id> | fields=<csv>`. `cust_id` is the opaque ULID (already cleared for logging in Story 1.3). **Never** the name, email, or note text.
- **No tax-ID decryption** happens in this command path. The helper SELECTs `notes` alone (not `tax_id_encrypted`), and the CLI doesn't construct a Fernet instance. Task 4.6 grep for `tax_id_encrypted` in `customers.py` confirms no new reads.

### Project Structure Notes

- **New files (1):**
  - `tests/test_keys_cli_update_customer.py` — the Task 3 integration suite.
- **Modified existing files (2 + test appends):**
  - `src/comadre/keys/db.py` — +1 helper (`update_customer`) + 1 result dataclass (`UpdateCustomerResult`) + 1 `TypeAlias`-style `Literal` (`UpdatedField`).
  - `src/comadre/keys/cli/commands/customers.py` — +`update_customer_cmd`, +`_EMAIL_ADAPTER` module-level constant, +`_UPDATE_CUSTOMER_HINTS` dict, +`from pydantic import TypeAdapter` import, +`update_customer` / `UpdateCustomerResult` imports from `comadre.keys.db`.
  - `tests/test_keys_db.py` — +`TestUpdateCustomer` class with ~11 test methods.
- **No changes to existing runtime files** (`api.py`, `main.py`, `rate_limit.py`, `service.py`, `config.py`, `exceptions.py`, `cli/app.py`, `cli/__init__.py`, `cli/output.py`, `cli/commands/keys.py`, `cli/_clock.py`, `cli/_errors.py`, `migrations/*.sql`, `audit.py`, `models.py`, `crypto.py`).
- All placements per architecture.md §Module Organization (L327-L350). No deviations.

### Testing Standards

- All tests mocked by default; no real models, no `@pytest.mark.slow`.
- `CliRunner` from `typer.testing` — synchronous, same as Stories 1.1–1.4.
- `tmp_path` for DB files. In-memory SQLite (`sqlite3.connect(":memory:")`) acceptable for the Task 1 helper tests that don't exercise `get_connection()`'s chmod path; use a real `tmp_path` DB for the integration tests.
- Reuse Story 1.1's `_clear_settings_cache` autouse from `tests/conftest.py`.
- Target coverage: 90%+ on new code (`update_customer`, `update_customer_cmd`).
- Autouse fixture `_reset_consoles_to_buffers` — copy the exact version from `tests/test_keys_cli_show.py`.
- `width=120` in the test Console — same as Stories 1.1/1.2/1.3/1.4. The ConfirmationLine fits on one line at 120 cols for any realistic customer id + name + suffix combination.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-1.5-Customer-Updates-Notes` (L430-L453)] — AC source text.
- [Source: `_bmad-output/planning-artifacts/prd.md#CLI-Tool-Specification` (L960)] — `update-customer <customer-id> [--add-note | --email]` spec.
- [Source: `_bmad-output/planning-artifacts/prd.md#Journey-3` (L389-L402)] — `update-customer --add-note` real-world usage (Marcos the late-payer).
- [Source: `_bmad-output/planning-artifacts/prd.md#Functional-Requirements` (L26-L27, L66)] — FR3 + FR4 + FR30.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Naming-Patterns` (L313-L314)] — `update_customer` audit action name.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Import-Boundary-Rules` (L366-L372)] — CLI must not import from `keys.auth` / `keys.cache`.
- [Source: `_bmad-output/planning-artifacts/architecture.md#SQLite-Query-Patterns` (L376-L383)] — parameterized `?` placeholders, no f-string SQL with parameters.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Transaction-Scope` (L465-L469)] — helper owns `with conn:`; audit write inside same transaction.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Enforcement-Guidelines` (L471-L488)] — grep-based regression rules (Task 4.6).
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#ConfirmationLine` (L835-L846)] — single-line mutation output contract.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#ErrorDisplay` (L820-L833)] — red-bordered stderr panel for errors.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Command-Hierarchy` (L886-L894)] — Mutate-tier (no `--yes`).
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Responsive-Strategy` (L1063-L1081)] — 80-col adaptation.
- [Source: `_bmad-output/implementation-artifacts/1-1-customer-registration-with-cpf-cnpj-validation.md#Dev-Agent-Record`] — CliRunner fixture pattern, insert_customer transaction contract, audit blocklist invariant.
- [Source: `_bmad-output/implementation-artifacts/1-2-api-key-issuance.md#Dev-Agent-Record`] — `_resolve_today_in_tz` seam, `_format_brl`, `get_customer` tombstone contract.
- [Source: `_bmad-output/implementation-artifacts/1-3-customer-key-listing.md#Dev-Agent-Record`] — stderr log routing (load-bearing for Story 1.5's log-sanitization AC), help-surface Panel-glyph normalisation.
- [Source: `_bmad-output/implementation-artifacts/1-4-key-customer-detail-view-with-audit-trail.md#Dev-Agent-Record`] — `get_customer_detail`, `CustomerDetailRow`, clock-seam relocation, `_SHOW_NOT_FOUND_HINT` pattern.
- [Source: `_bmad-output/implementation-artifacts/deferred-work.md`] — Story 1.1 UX-edges carve-out now owned by Story 1.5.
- [Source: `_bmad-output/project-context.md#Critical-Implementation-Rules`] — uv-only, no `os.environ`, no raw `HTTPException`, structured logging, English only.
- [Source: `CLAUDE.md`] — project language policy, Docker v2, `uv` only, no raw `HTTPException`, no `print()`.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m] (Opus 4.7, 1M context)

### Debug Log References

- `uv run pytest` — 836 passed (Story 1.4 closed at 801; Story 1.5 adds 35 new tests: 11 in `TestUpdateCustomer` + 24 in `tests/test_keys_cli_update_customer.py`).
- `uv run ruff check . && uv run ruff format --check .` — zero warnings, 59 files clean.
- `uv run mypy src/` — no issues in 28 source files (strict mode).
- `uv run pre-commit run --all-files` — all hooks pass (ruff, ruff-format, hadolint, yamllint, shellcheck, markdownlint-cli2, mypy).
- Task 4.6 grep guards all clean: `HTTPException` absent from `customers.py`; the only `f"UPDATE…` hit in `db.py` is the intended `set_parts` literal-column-name join; the only `print(` in `customers.py` is inside the `_missing_key_hint` string literal (telling operators how to generate a Fernet key via `python -c 'print(...)'`); no `os.environ` anywhere under `src/comadre/keys/`; `tax_id_encrypted` is only referenced in the existing `create-customer` write path — `update_customer` never touches the column.
- **Task 4.7 performance sanity (NFR5):** seeded a 1000-customer / 5000-audit-row SQLite DB, ran `uv run comadre-keys update-customer <cust_id> --email "x@y.com" --add-note "bump"` end-to-end; **elapsed 288.7 ms** (well under the 500 ms NFR5 budget). The majority is `uv run` + Python import startup; the actual `SELECT → UPDATE → INSERT INTO audit_log` footprint is O(1) against a primary-key index. No further tuning needed.
- **Task 5 manual smoke:** ran the five-step hot-path (create → `--add-note` → `--email` → `show` → audit inspect) against a throwaway `/tmp` DB; `show` renders the DetailPanel with the new email and the stamped note (`[2026-04-17] paga tarde - lembrar dia 3`); three audit rows landed in reverse chronological order with `details_json` exactly `{"fields": ["email"]}`, `{"fields": ["notes"]}`, `{"tax_id_kind": "cpf"}`; DB file mode stayed `0600`. Error panels for all four failure modes render red-bordered on stderr with the expected exit codes (2, 3, 2, 2).

### Completion Notes List

- **Helper (`src/comadre/keys/db.py`).** Added `UpdatedField` `Literal`, `UpdateCustomerResult` dataclass, and `update_customer(conn, customer_id, *, new_email, add_note, actor, today)`. The helper owns its `with conn:` transaction; on a missing or tombstoned customer it returns `None` without writing any audit row; on success it writes exactly one `audit_log` row with `action="update_customer"` and `details={"fields": sorted([...])}` before returning a refreshed `CustomerDetailRow`. The `SET` clause is assembled from a list of literal column fragments (`"email = ?"`, `"notes = ?"`) — operator input reaches SQL only through positional `?` bindings, preserving the Story 1.3 `list_api_keys` no-f-string-SQL precedent. Note-append format: `"[{today_iso}] {note_text}"` with `\n` separator only when there is existing notes text (empty-existing-notes branch stores only the stamped line, no leading newline).
- **Command (`src/comadre/keys/cli/commands/customers.py`).** Added `update_customer_cmd` with validation ordering (a) neither-flag → exit 2, (b) `TypeAdapter(EmailStr)` validation (pre-stripped) → exit 2, (c) NUL-byte + whitespace checks on `--add-note` → exit 2, (d) settings / encryption-key sanity → exit 6, (e) billing-TZ date resolution → exit 6, (f) DB open + migrations → exit 5, (g) `update_customer` helper → exit 5 on `sqlite3.Error`, exit 3 on `None` result, or success with ConfirmationLine. Suffix grammar: `"email changed"`, `"note added"`, or both joined with `, ` — em-dash `U+2014` matches the `create-customer` / `issue-key` precedent. Structured INFO log on stderr: `Updated customer | id=<cust_id> | fields=<csv>`; never includes name, email value, or note text.
- **FR37/NFR15 sanitization.** `audit_log.details_json` carries only `{"fields": [...]}`. The Task 1.4 test `test_audit_details_does_not_leak_values` and the Task 3 tests `test_log_has_no_pii` / `test_audit_details_json_no_pii` all assert absence of the literal email / note text across the log record AND the audit row. The existing `keys/audit.py` blocklist is exercised end-to-end by `TestUpdateCustomerAuditBlocklist.test_blocklist_intercepts_forbidden_details`.
- **Clock seam.** The CLI resolves `today` via `_resolve_today_in_tz` (already re-exported in `customers.py` since Story 1.4) and passes it into the helper. Tests freeze by `monkeypatch.setattr(customers_cmd, "_resolve_today_in_tz", lambda _tz: frozen)` — same pattern as the `show` command tests in Story 1.4.
- **Deferred-work carve-out landed.** Story 1.1's `--email` whitespace, NUL-byte, and `--notes` handling gap is now explicitly guarded: the command pre-strips `--email`, rejects empty/malformed emails via pydantic, strips `--add-note` and rejects empty-after-strip, and rejects any `\x00` in the note. `--notes` length remains unbounded per the Story 1.5 scope note — a single hardening pass across both write paths is deferred until the next `--notes`-touching story.

### File List

- **Modified:** `src/comadre/keys/db.py` (added `UpdatedField` `Literal`, `UpdateCustomerResult` dataclass, `update_customer` helper; ~105 new lines).
- **Modified:** `src/comadre/keys/cli/commands/customers.py` (added `EmailStr` / `TypeAdapter` imports, `UpdateCustomerResult` / `update_customer` imports, `_EMAIL_ADAPTER` constant, three hint constants, `_update_confirmation_suffix` helper, `update_customer_cmd` Typer command; ~175 new lines).
- **Modified:** `tests/test_keys_db.py` (added `update_customer` to the import list, `_UPDATE_FROZEN_TODAY` constant, `_seed_customer_with_notes` helper, `TestUpdateCustomer` class with 11 test methods; ~300 new lines).
- **New:** `tests/test_keys_cli_update_customer.py` (24 integration tests covering AC1–AC9 plus regression guards, ~680 lines).
- **Modified:** `_bmad-output/implementation-artifacts/sprint-status.yaml` (Story 1-5 row + `last_updated` field; transition `ready-for-dev` → `in-progress` → `review`).
- **Modified:** `_bmad-output/implementation-artifacts/1-5-customer-updates-notes.md` (Tasks/Subtasks checkboxes flipped, Dev Agent Record populated, Change Log entry added, Status flipped to `review`).

### Change Log

- **2026-04-17** — Story 1.5 implementation landed. Added `update-customer` CLI command (email replacement + append-only dated notes) and `update_customer` DB helper with a single-transaction UPDATE-plus-audit contract. Covers FR3/FR4/FR30, UX-DR6/7/9/10/15/16, and NFR5/NFR15/NFR16. 35 new tests (11 helper + 24 CLI integration), 836 tests total, all gates green (`ruff`, `mypy --strict`, `pre-commit`). Sprint-status advanced to `review`.
- **2026-04-17** — Code review complete. Three patches applied: (1) CLI now maps `RuntimeError` from the helper's post-commit re-read branch to exit 5 instead of letting it escape to exit 1; (2) `--add-note` now rejects embedded `\n` / `\r` (closed a dated-entry forgery vector); (3) `update_customer` computes `fields_sorted` once and reuses it for both the audit details and the returned tuple. Three regression tests added. 839 tests passing. Seven non-gating items moved to `deferred-work.md`. Story advanced to `done`.

### Review Findings

- [x] [Review][Patch] `RuntimeError` from the post-commit "row vanished" branch escapes the CLI and exits 1 instead of the spec-mandated exit 5 — the CLI `try` block around `update_customer` only catches `sqlite3.Error`, so `db.py:338` `raise RuntimeError(...)` bubbles past `finally` (which only suppresses close errors) and Typer/Click maps the uncaught exception to exit 1. Spec Task 1.1 docstring and UX-DR10 both mandate exit 5 for database failures. **Fixed** — CLI now catches `RuntimeError` and maps to `render_error("Database error", ...)` + exit 5; regression test `TestUpdateCustomerBothFlags.test_runtime_error_from_helper_maps_to_exit_5`. [`src/comadre/keys/cli/commands/customers.py:762-769`]
- [x] [Review][Patch] `--add-note` is not newline-sanitized, so an operator can forge past- or future-dated entries in the `notes` column. `db.py:298` builds `f"[{today.isoformat()}] {add_note}"` with no `\n` check; a note value like `"ok\n[2099-01-01] fake entry"` appends a second line that looks indistinguishable from a genuine stamped entry. NUL is rejected but LF — the far more damaging injection vector for this date-prefixed log format — is not. **Fixed** — CLI now rejects `\n` or `\r` in `--add-note` before DB open with `Usage error: --add-note must be a single line` (exit 2); regression tests `test_newline_note_exits_2` and `test_carriage_return_note_exits_2`. [`src/comadre/keys/cli/commands/customers.py:689-700`]
- [x] [Review][Patch] `sorted(set(updated))` is computed twice in `update_customer` — once for the audit payload (line 323) and once for the `UpdateCustomerResult.updated_fields` tuple (line 343). Two sources of truth for the same value; a future edit that changes one path silently desyncs the audit row from the ConfirmationLine. Compute once and reuse. **Fixed** — computed once into `fields_sorted` and reused for both the audit details list and the returned `UpdateCustomerResult.updated_fields` tuple. [`src/comadre/keys/db.py:323-344`]
- [x] [Review][Defer] Concurrent tombstone race between `with conn:` commit and the outside-transaction `get_customer_detail` reread — deferred, same class as the RuntimeError patch; single-writer SQLite plus the single-FIFO CLI usage pattern make the multi-process collision extremely unlikely. [`src/comadre/keys/db.py:333-340`]
- [x] [Review][Defer] Non-NUL control characters in `--add-note` (CR `\r`, ANSI escape `\x1b`, other `C0` controls) are not rejected — deferred, cross-cutting with Story 1.4's deferred Rich-markup-injection item on `render_customer_detail`. [`src/comadre/keys/cli/commands/customers.py:678-692`]
- [x] [Review][Defer] Unbounded `--add-note` length and unbounded cumulative `customer.notes` growth — deferred, already carved out in Story 1.1/1.5 scope notes for a cross-command hardening pass. [`src/comadre/keys/cli/commands/customers.py:685-692`, `src/comadre/keys/db.py:297-303`]
- [x] [Review][Defer] Audit-details JSON assertions compare exact byte strings (e.g. `'{"fields": ["email"]}'`) — deferred, brittle against a future `json.dumps` formatting change in `log_event`; switch to `json.loads(...)` equality. [`tests/test_keys_db.py:457,487,574,692,729`, `tests/test_keys_cli_update_customer.py:961,993,1077,1485,1507`]
- [x] [Review][Defer] `UpdateCustomerResult.customer` triggers a full post-commit `get_customer_detail` round-trip only to read `.id` (already known) and `.name` — deferred, optimization not a bug; a targeted `SELECT name` inside the transaction would eliminate the extra read. [`src/comadre/keys/db.py:333-344`, `src/comadre/keys/cli/commands/customers.py:778-779`]
- [x] [Review][Defer] `_logger.info` raising after a successful commit would bypass `render_confirmation` — deferred, low probability; wrap in `contextlib.suppress(Exception)` when next touching the log path. [`src/comadre/keys/cli/commands/customers.py:772-779`]
- [x] [Review][Defer] No test exercises two concurrent `update-customer` invocations against the same row — deferred, project runs a single FIFO queue so the realistic write contention window is bounded. [`tests/test_keys_cli_update_customer.py`]
