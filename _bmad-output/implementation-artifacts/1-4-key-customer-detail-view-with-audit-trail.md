# Story 1.4: Key & Customer Detail View with Audit Trail

Status: done

<!-- Validation optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want to view full context for a key or customer — including recent audit events — with a single command,
so that I can answer customer questions and troubleshoot billing / auth disputes without hopping between commands or greping the DB.

**Covers FRs:** FR14 (single-key detail view), FR32 (audit tail from CLI)
**UX-DRs:** UX-DR3 (DetailPanel), UX-DR5 (AuditTail), UX-DR9 (shared console), UX-DR10 (exit codes), UX-DR12 (empty results are not errors), UX-DR15 (realistic `--help` examples), UX-DR16 (80-col adaptation)
**NFRs:** NFR4 (list-class under 200 ms for 1 K customers — also applies to `show`), NFR15 (no anti-enumeration leaks), NFR33 (backwards-compatible within major version)
**Epic:** 1 — Key Registry & Customer Management
**Builds on:** Story 1.1 (`keys/` subpackage, DB schema, encryption, `_format_brl`, CliRunner + `_reset_for_tests` test harness, `_errors.py` helpers, pt-BR rendering). Story 1.2 (`ApiKeyRecord`, `get_customer`, `_format_brl`, `_resolve_today_in_tz` seam). Story 1.3 (`StatusTable`, `render_customer_list`/`render_key_list`, `render_json`, `render_empty_state`, `_status_label`, `_iso_date`, list-row dataclasses, JSON helpers, stderr-routed `keys.cli` logger).
**Unblocks:** Story 1.5 (`update-customer` reuses the customer-lookup helper and prints a DetailPanel on success). Story 1.6 (`update-key`/`rotate-key`/`revoke-key` reuse prefix-resolution + DetailPanel). Story 3.1 (`mark-paid`/`suspend`/`reactivate` reuse prefix-resolution). Epic 4 `export-customer` (Story 4.1) reuses the `resolve_target(...)` seam.
**Depends on:** Nothing outside Stories 1.1–1.3 — no new dependencies, no new schema, no runtime-path changes.

## Scope

Adds **one command** — `show <customer-id | key-prefix>` — plus the two new render components (DetailPanel and AuditTail) the epic calls out. Work breaks down as:

1. **Target resolver** in `src/comadre/keys/db.py`:
   - `resolve_show_target(conn, raw) -> ShowTarget` — given an operator-typed string, decide whether it's a customer ID (`cust_…`) or a key prefix (8 stored chars, or the full plaintext from which we derive the prefix). Returns a typed `ShowTarget` union so the caller branches on type, not on string-shape re-inspection.
   - `get_customer_detail(conn, customer_id) -> CustomerDetailRow | None` — LEFT JOIN against `api_key` for `key_count` (same pattern as Story 1.3's `list_customers`). Returns `None` when the row is missing **or tombstoned** (active-only default — matches Story 1.2 `get_customer` behaviour).
   - `get_key_detail(conn, key_prefix) -> KeyDetailRow | list[KeyDetailRow]` — look up by exact 8-char `key_prefix`. Returns the list literal when the prefix matches more than one row (ambiguous — practically impossible given secrets.token_urlsafe entropy, but see AC7); returns the single row directly otherwise.
   - `list_audit_events(conn, target_id, limit) -> list[AuditEventRow]` — newest-first chronological slice of `audit_log` for a given `target_id`. Parameterized `ORDER BY occurred_at DESC LIMIT ?`.
2. **Two new typed row dataclasses** in `src/comadre/keys/models.py`: `CustomerDetailRow` (all customer columns + `key_count` joined; NO decrypted tax_id — only `tax_id_kind`) and `KeyDetailRow` (api_key columns + `customer_name` joined + `age_days` computed). Plus `AuditEventRow` (id, occurred_at, actor, action, target_type, target_id, details_json). All `@dataclass(frozen=True, slots=True)`.
3. **DetailPanel + AuditTail renderers** in `src/comadre/keys/cli/output.py`:
   - `render_customer_detail(row)` — single-border `Panel` with right-padded labels: **ID**, **Name**, **Email**, **Tax ID Kind**, **Keys**, **Registered**, **Notes**. No decrypted tax-ID (Story 4.1 territory).
   - `render_key_detail(row)` — single-border `Panel` with labels: **Prefix**, **Customer**, **Status** (color-coded via existing `_status_label`), **RPM**, **Price**, **Billing**, **Paid Until**, **Created**, **Last Used**, **Age**, **Notes**.
   - `render_audit_tail(events, limit)` — plain `Console.print()` under the panel (no border — UX-DR5). Lines indented two spaces, format `YYYY-MM-DD HH:MM:SS  <ACTION>    <actor>  <opt detail>`. Section header: `Last {N} events:`. Empty result: literal `No events recorded` single line.
4. **JSON output mode** — `--format json` emits a single object containing `target` (the detail dict) and, when `--audit-tail N` is set, an `events` array. Empty events array when audit-tail requested but no rows. Never include decrypted tax-ID values.
5. **`show` command module** in `cli/commands/customers.py` (same place as `list-customers` — the command handles **both** customer and key targets via the resolver, so colocating with customer commands keeps the file organised; the alternative — two near-identical entry points — would bloat imports and diverge over time). Registered via the existing `app.registered_commands.extend(customers_app.registered_commands)` flow.
6. **Unit + integration tests** — append to `tests/test_keys_db.py` and `tests/test_keys_output.py`; create `tests/test_keys_cli_show.py` mirroring Story 1.3's fixture pattern (autouse `_clear_settings_cache` + `_reset_consoles_to_buffers` + `env`, shared `_seed_customer`/`_issue_key` helpers).

**Out of scope (future stories, DO NOT add):**

- `update-customer` / `update-key` → Stories 1.5, 1.6.
- `rotate-key` / `revoke-key` / `suspend` / `reactivate` → Stories 1.6, 3.1.
- Decryption of `tax_id_encrypted` for display → Story 4.1's `export-customer`. `show cust_…` surfaces only `tax_id_kind` (the literal `cpf`/`cnpj` string), **never** the decrypted value.
- Request-log stats (peak RPM, 429 count, average RPM, auth_success tallies) → Story 2.3. Journey 5 PRD L436-L483 shows a mock `Last 24h stats` block; that belongs to Story 2.3's in-memory counters, not this story's audit-log slice.
- Cached / TTL reads — `show` issues a fresh SQLite read every invocation. Cache is Story 2.1.
- Imports from `keys.auth` or `keys.cache` — those modules do not exist in the Story 1.4 tree; adding the imports would fail at runtime (architecture §Import Boundary Rules).
- Audit-log writes for `show` itself — this is a read-only command, no `audit_log` row is written. Same contract Story 1.3 established (architecture §Transaction Scope).
- Tombstone inspection via `show` — `show cust_…` on a tombstoned customer returns `not found` (exit 3). The `--deleted` introspection path stays on `list-customers --deleted` until Story 4.1 adds `export-customer --include-deleted`.

## Acceptance Criteria

> BDD-style. Every AC has a unit or integration test. Source AC text lives in `_bmad-output/planning-artifacts/epics.md:L397-L428` — this block expands each item with the technical detail the dev agent must honour.

### AC1 — `show <key-prefix>` populated happy path (FR14, UX-DR3, UX-DR9)

**Given** an active manual key exists with `key_prefix = "EVb4xk8B"` (issued via Story 1.2's `issue-key`)
**When** the operator runs `comadre-keys show EVb4xk8B`
**Then**
- A `rich.Panel` is printed to **stdout** via the shared `stdout_console()` singleton. Panel title is `"Key: EVb4xk8B"`. Border uses `rich.box.ROUNDED` (single-line — UX-DR3 "single-line border", distinct from Story 1.2 KeyPanel's double-line warning panel).
- Panel body is a single `\n`-joined text block with right-padded labels. Label set, in exactly this order: **Prefix**, **Customer**, **Status**, **RPM**, **Price**, **Billing**, **Paid Until**, **Created**, **Last Used**, **Age**, **Notes**. Labels are right-padded to the longest label in the panel — the padding is computed once at render time (`max(len(label) for label in LABELS) + 1`). This is the same padding convention Story 1.2's `_format_label` helper established; the renderer MAY import `_format_label` and `_LABEL_WIDTH` — but because the DetailPanel label set differs from KeyPanel's, a local `_DETAIL_LABEL_WIDTH` is acceptable. Prefer the import if the existing helper already fits.
- Value rendering per row:
  - `Prefix` → `row.key_prefix` (8-char stored form, monospace).
  - `Customer` → `f"{customer_name} ({customer_id})"`. Exactly the same format used by Story 1.2's KeyPanel (`"Helena Ribeiro (cust_01j8xr…)"`).
  - `Status` → color-coded via the existing `_status_label(status, billing_mode)` helper (Story 1.3). `[green]active[/]`, `[yellow]suspended[/]`, `[red]revoked[/]`, `[blue]complimentary[/]`. Uses `rich.text.Text(label, style=color)` so `NO_COLOR` strips the color while keeping the label text.
  - `RPM` → `f"{rpm}/min"` (matches Story 1.2 KeyPanel rendering).
  - `Price` → manual: `f"R$ {_format_brl(price)}/month"` (reuse `_format_brl` from Story 1.2). Complimentary: `"R$ 0,00 (bundled externally)"` (matches Story 1.2 KeyPanel rendering).
  - `Billing` → literal `row.billing_mode` (`manual` / `complimentary`).
  - `Paid Until` → ISO date `YYYY-MM-DD` or the literal `—` em-dash (U+2014) for NULL / complimentary (reuse `_iso_date` helper from Story 1.3).
  - `Created` → ISO date (first 10 chars of `created_at`).
  - `Last Used` → full timestamp `YYYY-MM-DD HH:MM:SS` (not just date — the PRD Journey 5 mock shows `2026-05-12 14:23:45`, so the detail view keeps the time component where list views strip it for scannability). For NULL (never used), render the literal `never`.
  - `Age` → human-readable days-since-created, computed as `(today_in_billing_tz - created_date).days` via the existing `_resolve_today_in_tz` seam (Story 1.2 — tests freeze it). Rendering: `"{days} days"` (plural always — `"1 days"` is acceptable per Story 1.3 AC5 pluralization policy); `"today"` for zero days.
  - `Notes` → `row.notes` or the literal `—` em-dash for empty string. Single-line; multi-line notes render as-is (no truncation — operator notes are short per PRD data model).
- No audit-tail section is printed (the `--audit-tail` flag is absent).
- Below the panel, no trailing row-count line (this is a detail view, not a list).
- Exit code `0`. No stderr output. **No `audit_log` row written** — read-only contract (same as Story 1.3 AC9).

### AC2 — `show --audit-tail N` appends chronological audit events (FR32, UX-DR5)

**Given** the same active key from AC1, plus audit history: one `issue_key` event from Story 1.2, two hypothetical future `mark_paid` and `update_key` events seeded directly into `audit_log`
**When** the operator runs `comadre-keys show EVb4xk8B --audit-tail 20`
**Then**
- The DetailPanel from AC1 is printed first, unchanged.
- A blank line separates the panel from the audit section.
- A section header prints on stdout: `Last <N> events:` where `<N>` is the **actual** number of events returned, **NOT** the requested limit (the UX spec at L462 is intentionally ambiguous; "Last N" with N = actual count is friendlier than "Last 20 events" followed by 3 events). Example: 3 events returned → `Last 3 events:`. Zero events → AC5 below.
- Event lines follow the UX-DR5 indent+format spec (L810-L812): two leading spaces, then `<YYYY-MM-DD HH:MM:SS>  <ACTION_UPPER>  <actor>  <optional detail>`. Exactly two spaces between columns (a single long right-aligned field would need per-column width computation; UX spec is fine with two-space gutters). Column widths:
  - Timestamp column: 19 chars (`YYYY-MM-DD HH:MM:SS`).
  - Action column: padded to the width of the longest action name in the returned event set (e.g., `update_key` → 10 chars), uppercased. The uppercase matches the PRD Journey 5 mock (`AUTH_SUCCESS`, `RATE_LIMIT_429`, `MARK_PAID`).
  - Actor column: left-aligned, no padding.
  - Optional detail column: when present, a compact JSON rendering of `details_json` (e.g., `{"rate_limit_rpm": 120}`) following a two-space gutter. When `details_json IS NULL`, omit the column entirely (no trailing whitespace).
- Order: newest first. SQL: `ORDER BY occurred_at DESC, id DESC LIMIT ?`. The secondary `id DESC` tie-breaks audit rows with identical timestamps (SQLite's autoincrement `id` is monotonic).
- The limit `N` is bounded to `[1, 1000]`. Typer validator rejects values outside this range with usage error exit 2 (title `Usage error: --audit-tail must be between 1 and 1000`). `--audit-tail 0` is explicitly rejected — if the operator doesn't want the tail, they should omit the flag.
- Exit code `0`. No stderr. No audit write.

### AC3 — `show <customer-id>` populated happy path (FR14, UX-DR3)

**Given** a customer `cust_01j8xr3e4c5m7kn9p2qt8vwyz0` exists with 2 issued keys
**When** the operator runs `comadre-keys show cust_01j8xr3e4c5m7kn9p2qt8vwyz0`
**Then**
- A `rich.Panel` is printed to stdout with title `"Customer: cust_01j8xr3e4c5m7kn9p2qt8vwyz0"`. Same single-line border as AC1.
- Panel body rows, in order: **ID**, **Name**, **Email**, **Tax ID Kind**, **Keys**, **Registered**, **Notes**. Exactly seven rows.
- Value rendering:
  - `ID` → the full customer id.
  - `Name` → `row.name`.
  - `Email` → `row.email`.
  - `Tax ID Kind` → uppercase literal `CPF` or `CNPJ` (matches the PRD Journey 1 rendering style — the operator-facing label capitalises the acronym even though the stored enum is lowercase). **Never** the decrypted tax ID.
  - `Keys` → `str(row.key_count)` (integer total, same LEFT JOIN as Story 1.3 `list_customers`).
  - `Registered` → ISO date of `registered_at`.
  - `Notes` → `row.notes` or `—` em-dash for empty.
- No `tax_id_encrypted` bytes appear anywhere in stdout or stderr (explicit assertion in tests — search for the ciphertext byte repr).
- Exit code `0`. No stderr. No audit write. `--audit-tail` is accepted on the customer path too (AC4 covers that).

### AC4 — `show <customer-id> --audit-tail N` aggregates customer-level events (FR32)

**Given** a customer with one `create_customer` event and two `issue_key` events (one per key)
**When** the operator runs `comadre-keys show <cust_id> --audit-tail 20`
**Then**
- The customer DetailPanel from AC3 is printed first.
- The audit section **includes events whose `target_id` equals the customer id OR whose `target_id` belongs to any `api_key` row owned by that customer**. Rationale: Journey 5 UX expects "all events about this customer" — including key-level events (issue_key, update_key, rotate_key) — when the operator types a customer id. The SQL: `target_id = ?1 OR target_id IN (SELECT id FROM api_key WHERE customer_id = ?1)` (bound twice with the same customer id).
- Events sort newest-first across both customer and key rows.
- AC2's column-padding, uppercase-action, and "Last N events:" header rules apply unchanged.

### AC5 — Empty audit result on `--audit-tail N` (UX-DR5)

**Given** a key exists but its `audit_log` slice for the target produces zero rows (can happen when the operator deletes audit history manually, or on a test fixture that seeds a key via direct SQL without the audit row)
**When** the operator runs `comadre-keys show <prefix> --audit-tail 10`
**Then**
- The DetailPanel is printed unchanged.
- A blank line and then the literal single line `No events recorded` (UX-DR5 empty state, L817). Two-space indent to match the event lines above. No section header `Last 0 events:` — the single sentence replaces the header entirely.
- Exit code `0` (empty result is not an error, UX-DR12).

### AC6 — Target not found (UX-DR6, UX-DR10)

**Given** the operator mistypes a prefix or ID
**When** they run `comadre-keys show XYZWQ000`
**Then**
- stderr prints a red-bordered ErrorDisplay panel with title `"Not found: no customer or key matches 'XYZWQ000'"` and hint `"Run 'comadre-keys list-customers' or 'comadre-keys list-keys' to see registered records."`
- Exit code `3`.
- Anti-enumeration invariant (FR37 / NFR15): the rejected input literal `"XYZWQ000"` MAY appear in the error title (it's the operator's own input, not an enumerated DB value). The error MUST NOT reveal whether the input *looked* like a customer ID vs. a key prefix (no branching like "customer not found" vs "key prefix not found") — both yield the same title. This prevents the ID-shape from leaking whether customers or keys are being registered at all.

**Given** a tombstoned customer (`deleted_at IS NOT NULL`) is addressed by id
**When** the operator runs `comadre-keys show cust_<tombstoned>`
**Then**
- Same `Not found` error as above (exit 3). Treating tombstones as missing is consistent with Story 1.2 `get_customer` and Story 1.3 `list-customers` (default). The `--deleted` introspection stays on `list-customers`.

### AC7 — Ambiguous key prefix (FR37 / enumeration resistance)

**Given** two `api_key` rows somehow share an identical `key_prefix` (vanishingly rare — 1 in 62^8, seeded directly in the test fixture)
**When** the operator runs `comadre-keys show <shared-prefix>`
**Then**
- stderr prints an ErrorDisplay with title `"Ambiguous prefix: multiple keys match '<prefix>'"` and hint `"Run 'comadre-keys list-keys' to see the full list, then use the key's customer id (cust_...) instead."`
- Exit code `3` (same as not-found — don't branch exit codes on collision vs miss).
- The error MUST NOT list the colliding `key_` IDs (leaks enumerable internal identifiers beyond what the operator already knows). The error MUST NOT include customer names/emails/tax IDs from the colliding rows. Only the operator-supplied prefix echoes back.
- Practically impossible in production; the test exists to lock the behaviour in (and to document that prefix-only identification has a theoretical failure mode, which is why Story 4.1's `export-customer` accepts `cust_…` / `key_…` ULIDs rather than 8-char prefixes).

### AC8 — `--format json` machine-readable output

**Given** a key and its audit history exist
**When** the operator runs `comadre-keys show <prefix> --format json --audit-tail 5`
**Then**
- stdout emits a **single JSON object** (not an array — `show` returns one target, not a collection). Top-level shape:
  ```json
  {
    "target_type": "api_key",
    "target": { ...key detail fields, AC8 key-object schema... },
    "events": [ { ...audit row object... }, ... ]
  }
  ```
- `target_type` is the literal `"api_key"` or `"customer"` — consumers branch on this instead of parsing the object shape.
- Key `target` object schema (fixed key order):
  ```json
  {
    "id": "key_01j...",
    "customer_id": "cust_01j...",
    "customer_name": "Helena Ribeiro",
    "key_prefix": "EVb4xk8B",
    "status": "active",
    "billing_mode": "manual",
    "rate_limit_rpm": 60,
    "price_monthly": 149.0,
    "paid_until": null,
    "created_at": "2026-04-15T12:34:56Z",
    "last_used_at": null,
    "age_days": 2,
    "notes": ""
  }
  ```
  - `key_hash` is NOT included (same contract as Story 1.3 AC8).
  - `price_monthly` is a JSON number, not a string (same contract).
- Customer `target` object schema (fixed key order):
  ```json
  {
    "id": "cust_01j...",
    "name": "Helena Ribeiro",
    "email": "helena@clinica.com",
    "tax_id_kind": "cpf",
    "key_count": 2,
    "registered_at": "2026-04-15T12:34:56Z",
    "notes": ""
  }
  ```
  - `tax_id_encrypted` is NOT included. `deleted_at` is NOT included (by contract, `show` never returns tombstoned customers — so the field would always be `null`, and exposing it might suggest the column is meaningful on this path; omit entirely).
- `events` array schema (per element, fixed key order):
  ```json
  {
    "id": 42,
    "occurred_at": "2026-04-15T10:30:00Z",
    "actor": "cli:ricardo",
    "action": "issue_key",
    "target_type": "api_key",
    "target_id": "key_01j...",
    "details": { "billing_mode": "manual", "rate_limit_rpm": 60 }
  }
  ```
  - `details` is the **parsed** JSON object (from `details_json` TEXT) for consumer ergonomics — not a re-stringified JSON literal. When `details_json IS NULL`, emit `null`.
  - Ordering: newest-first (same as table mode).
  - When `--audit-tail` is omitted, `events` key is **absent from the top-level object** (not `[]`). When `--audit-tail N` is set but returns zero rows, emit `"events": []` (same distinction as Story 1.3's empty-list vs absent-field rule).
- Not-found / ambiguous paths emit the **error** on stderr as usual (no JSON on stdout) and exit 3 — the `--format json` flag does NOT change error rendering (it's a data-format flag, not a protocol flag). An alternative where JSON-mode errors emit `{"error": {...}}` on stdout was considered and rejected: consumers are expected to check exit codes, not parse stdout on failure.
- Exit code `0` on success. No hint text in JSON mode — ever.

### AC9 — Read-only contract (architecture invariant)

**Given** any `show` invocation succeeds or fails
**Then**
- No row is written to `api_key`, `customer`, or `audit_log`. Snapshot `SELECT COUNT(*)` on all three tables before and after every invocation in the test fixture — deltas must be zero.
- The SQLite connection is opened via `get_connection()` and closed in a `try/finally` + `contextlib.suppress(sqlite3.Error)` (Story 1.2/1.3 pattern).
- No `with conn:` block is entered — all queries are SELECTs.
- No `log_event` call — the absence of the transaction boundary is the read-only signal (architecture §Transaction Scope).
- No `get_cli_actor()` call — actor machinery is audit-write territory.

### AC10 — Usability, accessibility, and `--help` (UX-DR8, UX-DR9, UX-DR15, UX-DR16)

**Given** a terminal at 80 columns and `NO_COLOR=1` set
**When** the operator runs `show <prefix>` and `show <cust_id>` with representative data
**Then**
- Output is readable without horizontal scrolling. The DetailPanel auto-widens to the longest `label + value` pair; rich handles wrapping for long values (e.g., a 200-char notes field wraps inside the panel — acceptable at 80 cols).
- No ANSI escape sequences appear in the captured stdout when `NO_COLOR=1` — verified by the autouse `Console(no_color=True, force_terminal=False, width=120)` fixture plus an assertion `"\x1b[" not in stdout`.
- The status badge label (`active`, `suspended`, `revoked`, `complimentary`) is readable via plain text — color is an accelerator, not a carrier (UX-DR8).
- Every cell content comes from `render_*` helpers — no `print()` / `typer.echo` / raw `sys.stdout.write`. Verified by Task 8 grep.

**Given** the operator runs `comadre-keys show --help`
**Then** Typer prints usage with realistic example values (UX-DR15):
- Positional `TARGET` help: `Customer ID (cust_...) or 8-char key prefix. Example: "EVb4xk8B" or "cust_01j8xr3e4c5m7kn9p2qt8vwy".`
- `--audit-tail` help: `Append the N most recent audit events. Example: --audit-tail 20. Range: 1..1000.`
- `--format` help: `Output format: table (default, human-readable) or json. Example: --format json.`
- Example (epilog / docstring footer): `Example: comadre-keys show EVb4xk8B --audit-tail 20`.
- Exit code `0`. No DB or Fernet resolution happens for `--help` (pure Typer rendering; assert `not (tmp_path / "registry.db").exists()` after a help-only invocation).

## Tasks / Subtasks

Ordered for bottom-up construction. Each task ends with a runnable checkpoint. Do not reorder — tests and imports chain downward.

- [x] **Task 1 — Extend `keys/models.py` with detail-row dataclasses** (AC: #1, #3, #4, #8)
  - [x] 1.1 Add three `@dataclass(frozen=True, slots=True)` classes to `src/comadre/keys/models.py` (same convention as Story 1.3):
    ```python
    @dataclass(frozen=True, slots=True)
    class CustomerDetailRow:
        """One row of the ``show <cust_id>`` result — immutable display payload."""
        id: str
        name: str
        email: str
        tax_id_kind: TaxIdKind
        key_count: int
        registered_at: str  # ISO 8601 UTC str
        notes: str


    @dataclass(frozen=True, slots=True)
    class KeyDetailRow:
        """One row of the ``show <key-prefix>`` result — immutable display payload.

        ``age_days`` is computed by the caller (uses ``_resolve_today_in_tz`` seam
        so tests can freeze the clock). ``customer_name`` is joined in so the
        renderer doesn't need a second query. ``key_hash`` is deliberately NOT
        included.
        """
        id: str
        customer_id: str
        customer_name: str
        key_prefix: str
        status: CustomerStatus
        billing_mode: BillingMode
        rate_limit_rpm: int
        price_monthly: float
        paid_until: str | None
        created_at: str  # ISO 8601 UTC str
        last_used_at: str | None  # ISO 8601 UTC str
        age_days: int
        notes: str


    @dataclass(frozen=True, slots=True)
    class AuditEventRow:
        """One row of the ``audit_log`` slice served by ``--audit-tail``."""
        id: int
        occurred_at: str  # ISO 8601 UTC str
        actor: str
        action: str
        target_type: str | None
        target_id: str | None
        details_json: str | None
    ```
  - [x] 1.2 Export nothing new from `keys/__init__.py` — importers use fully-qualified `from comadre.keys.models import ...`. Matches Story 1.3 convention.
  - [x] 1.3 Tests in `tests/test_keys_models.py`:
    - One constructor-round-trip test per new class (same shape as Story 1.3's `TestCustomerListRow` / `TestApiKeyListRow`).
    - `test_frozen` and `test_has_slots` per class (reuse Story 1.3's pattern — `hasattr(row, "__dict__")` is the slots check).

- [x] **Task 2 — Extend `keys/db.py` with parameterized detail helpers** (AC: #1, #3, #4, #6, #7, #8, #9)
  - [x] 2.1 Add `get_customer_detail(conn, customer_id) -> CustomerDetailRow | None`:
    ```sql
    SELECT
        c.id, c.name, c.email, c.tax_id_kind, c.notes,
        c.registered_at,
        COUNT(k.id) AS key_count
    FROM customer AS c
    LEFT JOIN api_key AS k ON k.customer_id = c.id
    WHERE c.id = ? AND c.deleted_at IS NULL
    GROUP BY c.id
    ```
    Returns `None` when no row is returned. The tombstone filter is explicit (`AND c.deleted_at IS NULL`) — mirrors Story 1.2 `get_customer`.
  - [x] 2.2 Add `get_key_detail(conn, key_prefix, *, today) -> KeyDetailRow | list[KeyDetailRow]`:
    - SQL: `SELECT k.*, c.name AS customer_name FROM api_key AS k JOIN customer AS c ON c.id = k.customer_id WHERE k.key_prefix = ?`.
    - Fetch all rows. If zero rows → return `None`. If one row → return a `KeyDetailRow` with `age_days` computed via `(today - date.fromisoformat(k.created_at[:10])).days`. If ≥ 2 rows → return a `list[KeyDetailRow]` (length ≥ 2) so the caller can render AC7's ambiguous-prefix error.
    - `today` is a `datetime.date` passed by the caller (from `_resolve_today_in_tz(settings.billing_timezone)` — Story 1.2 seam, tests freeze it). Putting it on the signature keeps the SQL pure and testable without monkey-patching the clock.
    - **Why the type union returns**: the single-vs-many distinction is a domain event, not an internal detail — the caller branches differently (render panel vs render error). Returning a `list` always and forcing the caller to check `len()` was considered and rejected because it hides the "ambiguous" signal one level deeper.
  - [x] 2.3 Add `list_audit_events(conn, target_ids, limit) -> list[AuditEventRow]`:
    - `target_ids` is a `Sequence[str]` of one or more IDs (customer id + its key ids for AC4; just the one id for AC2).
    - SQL: `SELECT id, occurred_at, actor, action, target_type, target_id, details_json FROM audit_log WHERE target_id IN ({placeholders}) ORDER BY occurred_at DESC, id DESC LIMIT ?`. Placeholders are generated programmatically (`",".join("?" * len(target_ids))`) — same predicate-assembly pattern as Story 1.3 `list_api_keys`; operator input never interpolates into SQL, only positional `?` bindings.
    - Returns `list[AuditEventRow]`. Empty result → empty list.
    - **Validation**: `assert 1 <= limit <= 1000` at function entry (defensive — the Typer layer validates, but this guards direct callers). Use `raise ValueError` rather than `assert` so `-O` mode doesn't strip it (matches Story 1.2 audit blocklist precedent).
  - [x] 2.4 Add `resolve_show_target(conn, raw, *, today) -> ShowTarget`:
    - `ShowTarget` is a `TypeAlias` discriminated union — for MVP simplicity use a tagged `tuple[Literal["customer"] | Literal["key_single"] | Literal["key_ambiguous"] | Literal["not_found"], object]`, OR a `dataclass` with `kind: Literal[...]` and `value: CustomerDetailRow | KeyDetailRow | list[KeyDetailRow] | None`. Prefer the dataclass — it's self-documenting and the caller can `match` on `.kind` without tuple positional magic.
    - Branching logic:
      1. If `raw.startswith("cust_")` → treat as customer id. Call `get_customer_detail(conn, raw)`. Return `kind="customer"` with the row, or `kind="not_found"` on None.
      2. If `raw.startswith("cmdr_live_")` → strip that prefix and take the first 8 chars as a `key_prefix` candidate (convenience for operators who paste a full plaintext — though they should not). Proceed to step 4.
      3. If `raw.startswith("key_")` → treat as a full key id. Look up via direct `SELECT` on `api_key.id` (add `get_key_detail_by_id(conn, key_id, *, today)` — a small sibling helper reusing the same join + `age_days` computation). This path is a nice-to-have; the PRD L975 spec says `<customer-id | key-prefix>` not `<key-id>`, but supporting the full `key_…` ULID for scripts that chain commands is cheap (and Story 3.1 `mark-paid` will want it). Return `kind="key_single"` or `kind="not_found"`.
      4. Else (no matching prefix tag) → treat as a bare `key_prefix`. Accept any length from 1..8 chars for ergonomic mistypes; if length < 8, the exact-match query simply returns zero rows (we do NOT use LIKE — partial matching opens an enumeration side channel and the operator can list-keys instead). Call `get_key_detail(conn, raw, today=today)`. Branch on the return type: `None` → `kind="not_found"`; single row → `kind="key_single"`; list → `kind="key_ambiguous"` with the list.
    - Module placement: `resolve_show_target` lives in `db.py` despite being partly command-layer logic — it's the last helper before the command module and keeping it in `db.py` means the command body stays small. The alternative (a new `keys/resolve.py`) is overkill for one helper.
  - [x] 2.5 Tests in `tests/test_keys_db.py` (append):
    - `test_get_customer_detail_returns_row` / `test_get_customer_detail_returns_none_on_missing` / `test_get_customer_detail_treats_tombstone_as_missing`.
    - `test_get_customer_detail_counts_keys_via_left_join` (seed 0/1/2 keys, assert counts).
    - `test_get_key_detail_single_row` / `test_get_key_detail_none_when_missing` / `test_get_key_detail_ambiguous_returns_list` (seed two rows with identical `key_prefix` via direct SQL, assert list length 2, types match).
    - `test_get_key_detail_joins_customer_name` (assert `customer_name` populated).
    - `test_get_key_detail_age_days_computation` (freeze today; assert age == (today - created_date).days for created 10 days ago).
    - `test_list_audit_events_newest_first` (seed 3 events with staggered `occurred_at`; assert DESC order).
    - `test_list_audit_events_limit` (seed 5 events, query with limit=3; assert 3 rows, newest).
    - `test_list_audit_events_filter_by_target_ids` (seed events for two unrelated targets; assert only the requested target's events return).
    - `test_list_audit_events_customer_plus_keys_union` (AC4 seed: create_customer event + issue_key event + an update_key event; query with target_ids = [cust_id, key_id]; assert all three return).
    - `test_list_audit_events_limit_validation` (limit=0 → ValueError; limit=1001 → ValueError).
    - `test_resolve_show_target_customer_happy_path` / `test_resolve_show_target_key_prefix_happy_path` / `test_resolve_show_target_key_id_happy_path` / `test_resolve_show_target_cmdr_live_prefix_convenience` (operator pastes `cmdr_live_XXXXXXXX…`, helper strips and matches the 8-char prefix).
    - `test_resolve_show_target_not_found_customer` / `test_resolve_show_target_not_found_key_prefix` / `test_resolve_show_target_tombstone_as_not_found`.
    - `test_resolve_show_target_ambiguous_prefix` (seed 2 rows with identical prefix; assert `kind == "key_ambiguous"`).
    - **Regression guard**: `test_show_commands_do_not_write` — snapshot `SELECT COUNT(*)` on `customer`, `api_key`, `audit_log` before and after every resolver/detail/audit call; all deltas zero.

- [x] **Task 3 — Extend `keys/cli/output.py` with DetailPanel + AuditTail renderers** (AC: #1, #2, #3, #4, #5, #10)
  - [x] 3.1 Add `render_customer_detail(row: CustomerDetailRow) -> None`:
    - Build a `rich.Panel` with `title=f"Customer: {row.id}"`, `box=box.ROUNDED`, `expand=False`.
    - Body: labeled key-value lines joined by `\n`. Labels: `ID:`, `Name:`, `Email:`, `Tax ID Kind:`, `Keys:`, `Registered:`, `Notes:`. Label column width = `max(len(label) for label in labels)` + 1 (extra space after colon).
    - Value formatting:
      - `ID` → `row.id`.
      - `Name` → `row.name`.
      - `Email` → `row.email`.
      - `Tax ID Kind` → `row.tax_id_kind.upper()` (CPF / CNPJ).
      - `Keys` → `str(row.key_count)`.
      - `Registered` → `_iso_date(row.registered_at)` (reuse Story 1.3 helper).
      - `Notes` → `row.notes or "\u2014"`.
    - Print via `stdout_console()`.
  - [x] 3.2 Add `render_key_detail(row: KeyDetailRow) -> None`:
    - Build a `rich.Panel` with `title=f"Key: {row.key_prefix}"`, `box=box.ROUNDED`, `expand=False`.
    - Body labels: `Prefix:`, `Customer:`, `Status:`, `RPM:`, `Price:`, `Billing:`, `Paid Until:`, `Created:`, `Last Used:`, `Age:`, `Notes:`.
    - Value formatting:
      - `Prefix` → `row.key_prefix`.
      - `Customer` → `f"{row.customer_name} ({row.customer_id})"`.
      - `Status` → `rich.text.Text(*_status_label(row.status, row.billing_mode))` (label+color from Story 1.3 helper). Join the Text renderable into the `\n`-separated body via `rich.text.Text.assemble` or a pre-rendered `str(Text.markup)` → Rich markup string `"[green]active[/]"` is fine and keeps the body as a single `str` (which the Panel constructor prefers). Use the markup form:
        ```python
        label, color = _status_label(row.status, row.billing_mode)
        status_cell = f"[{color}]{label}[/]" if color else label
        ```
        This is the same form UX spec example shows at L453 (`│ Status:      active`).
      - `RPM` → `f"{row.rate_limit_rpm}/min"`.
      - `Price` → `"R$ 0,00 (bundled externally)"` for complimentary, else `f"R$ {_format_brl(row.price_monthly)}/month"` (reuse Story 1.2's `_format_brl`).
      - `Billing` → `row.billing_mode`.
      - `Paid Until` → `_iso_date(row.paid_until)` (em-dash for NULL).
      - `Created` → `_iso_date(row.created_at)`.
      - `Last Used` → `"never"` if `row.last_used_at` is None, else `row.last_used_at.replace("T", " ").rstrip("Z")` (convert ISO 8601 `2026-05-12T14:23:45Z` → `2026-05-12 14:23:45` — matches PRD Journey 5 mock).
      - `Age` → `"today"` if `row.age_days == 0`, else `f"{row.age_days} days"`.
      - `Notes` → `row.notes or "\u2014"`.
    - Print via `stdout_console()`.
  - [x] 3.3 Add `render_audit_tail(events: list[AuditEventRow]) -> None`:
    - If `events` is empty: print one blank line then `"  No events recorded"` (two leading spaces) via `render_confirmation()`. Return.
    - Else:
      - Print blank line, then the header `f"Last {len(events)} events:"` via `render_confirmation()`.
      - Compute `action_width = max(len(e.action) for e in events)`.
      - For each event, emit one line:
        ```python
        timestamp = e.occurred_at.replace("T", " ").rstrip("Z")
        action = e.action.upper().ljust(action_width)
        detail = (
            f"  {e.details_json}" if e.details_json is not None else ""
        )
        line = f"  {timestamp}  {action}  {e.actor}{detail}"
        ```
        Print via `render_confirmation(line)`. The details column is the raw `details_json` text (already JSON-formatted in SQLite) — no re-parsing or re-formatting needed for the table view.
  - [x] 3.4 Add `render_show_json(*, target_type: Literal["customer", "api_key"], target: dict[str, object], events: list[dict[str, object]] | None) -> None`:
    - Assemble a top-level dict in fixed order: `{"target_type": ..., "target": ..., "events": ...}`. If `events is None`, omit the `events` key entirely (AC8 distinction).
    - Call `stdout_console().print_json(data=payload)` — reuses Story 1.3's centralised JSON path.
  - [x] 3.5 **Do NOT** re-implement `_status_label`, `_iso_date`, `_format_brl`, `render_confirmation`, `render_empty_state`, or `render_json` — import the existing helpers from the same module.
  - [x] 3.6 Tests in `tests/test_keys_output.py` (append):
    - `test_render_customer_detail_contains_all_labels` — seed a `CustomerDetailRow`; capture via the existing `_reset_for_tests` + `StringIO` fixture; assert each label appears; assert `cpf` → `CPF` uppercase transformation; assert the full customer id appears in the title.
    - `test_render_customer_detail_empty_notes_uses_emdash`.
    - `test_render_customer_detail_hides_tax_id_ciphertext` — pass a row whose notes contain the literal string `"gAAAAA"` (simulating a ciphertext leak attempt). Assert the byte repr of any Fernet token pattern (`b"gAAAAA"`) does NOT appear in output. Forward-looking guard: if a future refactor accidentally wires `tax_id_encrypted` into `CustomerDetailRow`, this test catches it before the code hits prod.
    - `test_render_key_detail_active_manual` / `test_render_key_detail_complimentary` (price label = bundled-externally) / `test_render_key_detail_suspended` / `test_render_key_detail_revoked` — all four status/billing combinations assert the color-coded Status row.
    - `test_render_key_detail_age_days_today` (age 0 → `today`) / `test_render_key_detail_age_days_plural` (age 1 → `1 days`; age 30 → `30 days`).
    - `test_render_key_detail_last_used_never` (None → `never`) / `test_render_key_detail_last_used_timestamp` (ISO 8601 `Z` → `2026-05-12 14:23:45`).
    - `test_render_audit_tail_populated` (seed 3 events with mixed `details_json`; assert the `Last 3 events:` header, two-space indent, uppercase actions, details column presence).
    - `test_render_audit_tail_empty` — `No events recorded` single line.
    - `test_render_audit_tail_action_column_padding` (seed events with varying action-name lengths; assert the column is padded to the longest).
    - `test_render_show_json_customer_shape` (assert key order + absent keys per AC8).
    - `test_render_show_json_key_shape`.
    - `test_render_show_json_omits_events_key_when_none` (asserts the top-level dict has exactly `target_type` + `target` keys, no `events`).

- [x] **Task 4 — `show` command** (AC: #1–#10)
  - [x] 4.1 Extend `src/comadre/keys/cli/commands/customers.py` (colocated with `list-customers` for the reasons in Scope #5). Add:
    ```python
    @app.command("show")
    def show_cmd(
        target: str = typer.Argument(
            ...,
            metavar="TARGET",
            help=(
                'Customer ID (cust_...) or 8-char key prefix. '
                'Example: "EVb4xk8B" or "cust_01j8xr3e4c5m7kn9p2qt8vwy".'
            ),
        ),
        audit_tail: int | None = typer.Option(
            None,
            "--audit-tail",
            help=(
                "Append the N most recent audit events. "
                "Example: --audit-tail 20. Range: 1..1000."
            ),
        ),
        format: str = typer.Option(
            "table",
            "--format",
            help=(
                "Output format: table (default, human-readable) or json. "
                "Example: --format json."
            ),
        ),
    ) -> None:
        """Show full context for a customer or API key (optionally with audit tail).

        Example: comadre-keys show EVb4xk8B --audit-tail 20
        """
        ...
    ```
  - [x] 4.2 Command body, in order:
    1. Validate `--format` ∈ {"table", "json"}. Invalid → exit 2, title `Usage error: --format must be table or json`.
    2. Validate `--audit-tail`. `None` → no tail. Integer outside `[1, 1000]` → exit 2, title `Usage error: --audit-tail must be between 1 and 1000`.
    3. Load settings (try/except `ValidationError` + `OSError` → exit 6; reuse `_errors.py` helpers + the module-level `_missing_key_hint` Story 1.3 extracted). Resolve `billing_tz = ZoneInfo(settings.billing_timezone)` with the Story 1.2 `ZoneInfoNotFoundError | ValueError` → exit 6 mapping. Compute `today = _resolve_today_in_tz(billing_tz)` once. **Import note**: `_resolve_today_in_tz` currently lives in `cli/commands/keys.py` (Story 1.2). For Story 1.4, **move it to `cli/_clock.py`** (a new one-liner module) and re-export from `keys.py` for backwards compatibility with existing tests. Rationale: `customers.py` now needs the same seam, and cross-importing from `keys.py` would create a lateral import inside the commands layer — lateral imports are stylistically fine but the module is about to grow, so the relocation pays off immediately. Keep the re-export in `keys.py` so Story 1.2's `_freeze_today(monkeypatch, keys_cmd, ...)` tests continue to work unchanged.
    4. Open DB via `get_connection()` in a try/finally + `contextlib.suppress(sqlite3.Error)`. Apply migrations. All subsequent reads use this one connection.
    5. `result = resolve_show_target(conn, target, today=today)`. Branch on `result.kind`:
       - `"not_found"`: render ErrorDisplay (`Not found: no customer or key matches '<target>'`, hint `Run 'comadre-keys list-customers' or 'comadre-keys list-keys' to see registered records.`). Exit 3. **JSON mode**: still an error — no JSON on stdout, just the stderr panel + exit 3.
       - `"key_ambiguous"`: render ErrorDisplay (`Ambiguous prefix: multiple keys match '<target>'`, hint per AC7). Exit 3.
       - `"customer"` / `"key_single"`: continue to step 6.
    6. If `audit_tail is not None`: compute `target_ids` per AC2 vs AC4 scoping:
       - For customer (AC4 — broader "everything about this customer"): `target_ids = [customer_id] + [key.id for key in SELECT k.id FROM api_key WHERE k.customer_id = ?]` (one extra SELECT — acceptable for a detail command).
       - For key (AC2 — strictly "events for that key"): `target_ids = [key.id]`. Do NOT include the customer id here — the PRD AC says "the last 20 audit events for that key", so the scope stops at the key. If the operator wants the broader chain, they run `show <cust_id> --audit-tail N`.
       - Call `events = list_audit_events(conn, target_ids, limit=audit_tail)`.
       - Else `events = None`.
    7. Close the connection.
    8. Structured INFO log: `_logger.info("Showed detail | kind=%s | target=%s | audit_tail=%s", result.kind, target_if_opaque_id_else_length, audit_tail)`. The `target` value is an opaque ULID or an 8-char prefix — safe to log (same FR37 rationale Story 1.3 used for customer-id logging). **Never** include the customer name, email, or tax ID in the log.
    9. Branch on `--format`:
       - `table`:
         - If `result.kind == "customer"`: `render_customer_detail(result.value)`.
         - Else: `render_key_detail(result.value)`.
         - If `events is not None`: `render_audit_tail(events)`.
       - `json`:
         - Build the target dict via a command-local helper `_customer_detail_to_json(row)` / `_key_detail_to_json(row)` (AC8 schemas, fixed key order).
         - Build events list via `_audit_event_to_json(event)`.
         - `render_show_json(target_type=..., target=..., events=...)`.
    10. Exit 0 implicit.
  - [x] 4.3 No change needed in `app.py` — the existing `app.registered_commands.extend(customers_app.registered_commands)` picks up the new command. Verify via `uv run comadre-keys --help` that `show` appears alongside `create-customer`, `issue-key`, `list-customers`, `list-keys`.

- [x] **Task 5 — JSON serialization helpers** (AC: #8)
  - [x] 5.1 Add `_customer_detail_to_json(row: CustomerDetailRow) -> dict[str, object]` in `customers.py`. Literal dict construction, AC8 key order exactly.
  - [x] 5.2 Add `_key_detail_to_json(row: KeyDetailRow) -> dict[str, object]` in `customers.py` (same module since `show` lives there).
  - [x] 5.3 Add `_audit_event_to_json(event: AuditEventRow) -> dict[str, object]`:
    - Parse `details_json` from TEXT to `dict | list | None` via `json.loads` in a try/except `json.JSONDecodeError` → fall back to the raw string (defensive: old audit rows written before Story 1.2's `sort_keys=True` contract still parse). `None` → `None`.
    - Emit the AC8 event-object schema with fixed key order.
  - [x] 5.4 All three helpers live in `customers.py` (not a shared `_json.py`) — same scope-guard rationale Story 1.3 Task 6 used.

- [x] **Task 6 — Move `_resolve_today_in_tz` to `cli/_clock.py`** (AC: #1, housekeeping)
  - [x] 6.1 Create `src/comadre/keys/cli/_clock.py`:
    ```python
    """Thin clock seam — tests freeze via monkeypatch.

    Lives in its own module so both ``customers.py`` (show) and ``keys.py``
    (issue-key, list-keys) can import without creating a lateral dep.
    """

    from __future__ import annotations

    from datetime import date, datetime
    from zoneinfo import ZoneInfo


    def resolve_today_in_tz(tz: ZoneInfo) -> date:
        """Return today's date resolved in ``tz``. Thin seam for tests."""
        return datetime.now(tz).date()
    ```
  - [x] 6.2 In `src/comadre/keys/cli/commands/keys.py`:
    - Replace the local `_resolve_today_in_tz` with `from comadre.keys.cli._clock import resolve_today_in_tz as _resolve_today_in_tz` (keep the underscore alias so existing tests that patch `keys_cmd._resolve_today_in_tz` continue to work).
    - **Verify** that `monkeypatch.setattr(keys_cmd, "_resolve_today_in_tz", ...)` still binds against the re-exported name. It will — Python's attribute lookup finds the module-level binding, which is an alias to the same callable.
  - [x] 6.3 In `src/comadre/keys/cli/commands/customers.py`: import the same helper under the same underscore alias for consistency with `keys.py`.
  - [x] 6.4 Run the existing `tests/test_keys_cli_issue.py` and `tests/test_keys_cli_list_keys.py` suites to confirm `_freeze_today(monkeypatch, date(...))` still works unchanged. No test edits should be required.

- [x] **Task 7 — Integration tests: `show`** (AC: #1–#10)
  - [x] 7.1 Create `tests/test_keys_cli_show.py`. Reuse the three autouse fixtures from `test_keys_cli_list_keys.py` (`_clear_settings_cache`, `_reset_consoles_to_buffers`, `env`) and the `_buffers()`, `_clear_buffers()`, `_seed_customer()`, `_issue_key()`, `_raw_insert_key()` helpers. Copy verbatim — these helpers have stabilised across Stories 1.1–1.3 and a shared `conftest.py` extraction is deferred until at least four test files reuse them (today's count is three — right at the threshold, but each file re-imports a slightly different subset, so a shared helper would have to over-expose its surface area).
  - [x] 7.2 Tests:
    - **AC1 — key happy path:** `test_show_key_populated_renders_detail_panel` — seed one active manual key; run `show <prefix>`; assert panel title `"Key: <prefix>"`, each of the 11 labels present, pt-BR price, `—` em-dash for `Paid Until` NULL, `never` for `Last Used`, `today` for `Age` when clock is frozen to the seeded day.
    - **AC1 variants:** `test_show_key_complimentary` (price = bundled-externally), `test_show_key_suspended_label` (status label `suspended`), `test_show_key_revoked_label` (`revoked`), `test_show_key_with_notes` (notes string round-trips; whitespace preserved).
    - **AC2 — key + audit tail:** `test_show_key_with_audit_tail_20` — seed key + issue_key event + directly-insert a mark_paid event + an update_key event. Run `show <prefix> --audit-tail 20`. Assert: blank line after panel; `Last 3 events:` header; each event line is two-space-indented; actions UPPERCASED; newest-first order; details column present for the event whose `details_json` is non-null.
    - **AC2 — limit bounds:** `test_audit_tail_zero_rejected` (exit 2), `test_audit_tail_1001_rejected` (exit 2), `test_audit_tail_valid_1` and `test_audit_tail_valid_1000`.
    - **AC3 — customer happy path:** `test_show_customer_populated_renders_detail_panel` — seed customer + two issue_key; run `show <cust_id>`; assert 7 rows with correct labels; `tax_id_kind` rendered as `CPF`; `Keys: 2`.
    - **AC3 anti-enumeration:** `test_show_customer_does_not_leak_ciphertext` — seed customer; capture stdout; assert `b"gAAAAA"` prefix does NOT appear anywhere in the output bytes; assert no base64-looking 40+ char uninterrupted run appears (a paranoid forward-looking guard against future accidental wiring).
    - **AC4 — customer + audit tail aggregates keys:** `test_show_customer_audit_tail_includes_key_events` — seed customer, issue one key, run `show <cust_id> --audit-tail 20`. Assert the audit section contains BOTH the `create_customer` event AND the `issue_key` event. Newest-first order (issue_key above create_customer).
    - **AC5 — empty audit result:** `test_show_key_audit_tail_empty_prints_no_events` — seed key via `_raw_insert_key` (bypasses `issue-key`, so no audit row). Run `show <prefix> --audit-tail 10`. Assert the literal `No events recorded` single line after the panel. No `Last 0 events:` header.
    - **AC6 — not found:** `test_show_missing_prefix_exits_3` — run `show NOPENOPE`; assert stderr title `Not found: no customer or key matches 'NOPENOPE'`; exit 3.
    - `test_show_missing_customer_id_exits_3` — run `show cust_01nonexistent00000000000000`; same error shape.
    - `test_show_tombstoned_customer_treated_as_missing` — seed customer, tombstone via direct SQL, `show <cust_id>` → exit 3 not-found.
    - `test_show_not_found_error_identical_for_customer_and_key_shapes` — assert the error title is the same literal whether the miss is a key-prefix shape or a cust_... shape (anti-enumeration guarantee).
    - **AC7 — ambiguous prefix:** `test_show_ambiguous_prefix_exits_3` — seed two keys with identical `key_prefix` via `_raw_insert_key` on both. Run `show <shared-prefix>`. Assert title `Ambiguous prefix: multiple keys match '<prefix>'`, exit 3. Assert the error body does NOT contain either colliding `key_01…` ULID.
    - **AC8 — JSON customer:** `test_show_customer_format_json_shape` — `show <cust_id> --format json`; assert `json.loads(stdout)["target_type"] == "customer"`; target object has the AC8 customer-schema keys only (no `tax_id_encrypted`, no `deleted_at`); `events` key is absent (no `--audit-tail`).
    - `test_show_customer_format_json_with_audit_tail` — `--audit-tail 5`; assert `events` key present; empty DB without forced audit → `events == []`; parsed `details` is a dict (from `details_json` text).
    - **AC8 — JSON key:** `test_show_key_format_json_shape` — assert `target_type == "api_key"`; target has AC8 key-schema keys; `key_hash` NOT present.
    - `test_show_format_json_not_found_emits_error_to_stderr` — `show NOPE --format json`; assert exit 3; stdout is empty (no JSON); stderr carries the error panel.
    - **AC9 — read-only:** `test_show_does_not_write` — snapshot table counts; run 10 `show` invocations across both happy paths + errors + JSON; counts unchanged.
    - **AC10 — NO_COLOR:** `test_show_no_color_has_no_ansi` — set `NO_COLOR=1`; re-wire Console without `no_color=True` so rich honours the env; assert `"\x1b[" not in stdout`.
    - **AC10 — help surface:** `test_show_help_lists_realistic_examples` — `show --help`; strip ANSI + Panel glyphs (same util Story 1.3 used); assert `cust_01j`, `EVb4xk8B`, `--audit-tail 20`, `--format json` all appear. Assert no DB file created after --help.
    - `test_show_help_does_not_touch_db` — regression for Story 1.1's no-DB-for-help rule.
    - `test_show_log_has_kind_not_names` — attach a throwaway `logging.Handler` directly to `keys.cli` (Story 1.3's pattern — caplog won't see the records because `propagate=False`). Run `show <cust_id>`. Assert the log contains `Showed detail | kind=customer` and does NOT contain the customer's name or email.

- [x] **Task 8 — Quality gates**
  - [x] 8.1 `uv run ruff check . && uv run ruff format --check .` — zero warnings on all new/modified files.
  - [x] 8.2 `uv run mypy src/comadre/keys/` — zero errors in strict mode. Pay attention to the `ShowTarget` dataclass union — mypy needs a `Literal[...]` discriminator plus a matching `object` payload, or a proper `typing.TypedDict` / `dataclass` per variant. Prefer a single dataclass with `kind: Literal["customer", "key_single", "key_ambiguous", "not_found"]` and `value: CustomerDetailRow | KeyDetailRow | list[KeyDetailRow] | None` — mypy is happy with the union as long as every caller narrows via `match result.kind:` or `if result.kind == ...`.
  - [x] 8.3 `uv run pytest` — all new tests pass, existing 703 tests (as of Story 1.3) still pass. Story 1.4 adds roughly 40–55 tests; final count should be ~745–760.
  - [x] 8.4 `uv run pre-commit run --all-files` — all hooks pass.
  - [x] 8.5 Do NOT update `sprint-status.yaml` — that transition happens when the reviewer moves the story to `done`.
  - [x] 8.6 **Non-regression guard rails for Epic 4.5 CI:**
    - `rg 'HTTPException' src/comadre/keys/cli/commands/` — empty (FR51).
    - `rg 'f"SELECT|f"INSERT|f"UPDATE|f"DELETE' src/comadre/keys/db.py` — only the Story 1.3 `where_clause` concatenator; any new f-string SQL in Story 1.4 is a violation. The `list_audit_events` IN-placeholder assembly uses the `",".join("?" * n)` pattern — no f-string SQL, matches Story 1.3 precedent.
    - `rg '\bprint\(' src/comadre/keys/` — no `^\s*print\(` (bare builtin print). `console.print(...)` matches are allowed per Story 1.3 precedent.
    - `rg 'os\.environ' src/comadre/keys/` — empty.
    - `rg 'tax_id_encrypted' src/comadre/keys/cli/` — empty (the renderer must never see the ciphertext column).
  - [x] 8.7 **Performance sanity (NFR4).** On a DB seeded with 1,000 customers + 5,000 keys + 50,000 audit rows (temporary one-off script — not committed), `time uv run comadre-keys show <prefix> --audit-tail 100` completes in well under 200 ms. The audit query hits `idx_audit_occurred` (descending scan, stops at LIMIT 100). Record the elapsed wall-clock and the isolated query time in the Dev Agent Record.

- [x] **Task 9 — Manual verification**
  - [x] 9.1 **DetailPanel eyeball at 80 cols.** Resize to 80 cols. `show <prefix>` with a realistic row. Confirm: (a) panel title wraps cleanly if necessary; (b) labels right-pad to the longest label; (c) status badge color matches UX-DR8; (d) pt-BR price renders (`R$ 1.234,56/month`).
  - [x] 9.2 **AuditTail eyeball.** Same terminal, `show <prefix> --audit-tail 20` after seeding 20 fake events via direct SQL. Confirm chronological newest-first ordering and uppercase action column. Record the terminal used in the Dev Agent Record.
  - [x] 9.3 **JSON piping.** `show <prefix> --format json | jq '.target.status'` returns the quoted status. `show <prefix> --format json --audit-tail 5 | jq '.events | length'` returns `5` (or fewer if the slice is smaller). Stderr warnings (if any) do not contaminate stdout.
  - [x] 9.4 **Error panel sanity.** `show NOPE`, `show cust_01nonexistent…`, and `show <shared-prefix>` (ambiguous) all exit 3 with distinct but anti-enumeration-safe titles.
  - [x] 9.5 **Log routing.** Tail the structured log (`2>&1 1>/dev/null`) during each invocation — `Showed detail | kind=... | target=... | audit_tail=...` appears on stderr; **no customer name / email / tax-id appears in the log**.

## Dev Notes

### Architecture invariants (from `_bmad-output/planning-artifacts/architecture.md`)

- **Import graph downward-only.** Story 1.4 adds the `show` command to `cli/commands/customers.py`; the resolver goes in `db.py`. No module-order changes. **Must not import from `keys.auth` or `keys.cache`** — those modules still do not exist. [Source: architecture.md §Import Boundary Rules, L366-L372]
- **CLI / runtime separation.** Do NOT touch `main.py`, `api.py`, `rate_limit.py`, `service.py`, `config.py`, `exceptions.py`. Preserves the 1.6.2 public contract byte-for-byte. [Source: architecture.md L519-L521]
- **No raw HTTPException.** Errors go through `render_error` + `typer.Exit` with AC6's exit-3 mapping.
- **No `print()`.** All output via `render_*` helpers. Structured logging via `get_logger("keys.cli")` — which Story 1.3 routed to **stderr** in `src/comadre/keys/cli/__init__.py`. JSON stdout stays pure. [Source: Story 1.3 Dev Agent Record — the log-routing fix is load-bearing for AC8.]
- **Parameterized SQL only.** The `IN (?, ?, ...)` assembly in `list_audit_events` uses the same "literal placeholders from a counted range" pattern Story 1.3 `list_api_keys` used. No f-string SQL. [Source: architecture.md §SQLite Query Patterns L376-L383, §Enforcement Guidelines]
- **CLI read-only.** `show` does not open `with conn:` and does not call `log_event`. [Source: architecture.md §Transaction Scope L465-L469]

### Data contracts

- `customer.registered_at` / `api_key.created_at` / `api_key.last_used_at` / `api_key.paid_until` / `audit_log.occurred_at` are all TEXT ISO 8601 UTC strings (or NULL where nullable). Detail-row dataclasses propagate them **as-is**; the renderer slices to date or formats to `YYYY-MM-DD HH:MM:SS` per AC1.
- `api_key.billing_mode IN ('manual', 'complimentary', 'automated')`. Same as Story 1.3 — `automated` is reserved and never surfaces here.
- `api_key.status IN ('active', 'suspended', 'revoked')`.
- `customer.tax_id_encrypted BLOB` — NEVER decrypted or surfaced.
- `audit_log.details_json` is TEXT — the AuditTail table view prints the raw JSON string; the JSON mode parses it into a dict via `json.loads`.

### Library version gotchas

- **`rich.box.ROUNDED`** is the single-border box. UX-DR3 requires single-line; `box.DOUBLE` is reserved for `KeyPanel` (UX-DR1). Do NOT use `box.HEAVY` / `box.ASCII` / `box.SQUARE`.
- **`rich.Panel(body: str | Text, …)`** — when the body mixes Rich markup (e.g., `[green]active[/]`) and plain text, pass a plain `str` and set `markup=True` (the Panel default). Panel respects `NO_COLOR` and strips the style while keeping the label text — consistent with Story 1.3 renderers.
- **`Console.print_json(data=dict)`** — Story 1.3 established that `sort_keys=False` is the default; tests assert key order by using hand-built literal dicts. Keep this invariant.
- **`date.fromisoformat("2026-04-15")`** is 3.7+ stdlib. Age computation: `(today - date.fromisoformat(created_at[:10])).days`. Negative values (e.g., a seeded-future row) should not happen in production; if the test fixture creates one, the render still emits `{days} days` where days is negative — which is ugly but not a crash. Story 1.4 does not add a guard; callers that observe negative days should fix their fixture.
- **`json.loads(details_json)`** — raises `json.JSONDecodeError` on malformed TEXT. The `_audit_event_to_json` helper catches this and falls back to the raw string (defensive: pre-Story-1.2 audit rows predate `sort_keys=True`, though in practice all rows produced by the codebase are valid JSON).

### Previous story intelligence (Stories 1.1, 1.2, 1.3)

- **CliRunner Click 8.2+ pattern.** `CliRunner()` with no `mix_stderr=False`. Wire stdout/stderr to `StringIO` via `_reset_for_tests()` + fixture-assigned `output_mod._stdout_console` / `_stderr_console`. Copy the autouse fixture from `test_keys_cli_list_keys.py` verbatim.
- **Help-only invocations do not open the DB.** Assert `not (tmp_path / "registry.db").exists()` after `--help` runs. Lock this in for `show --help` too.
- **`_reset_for_tests()` teardown is mandatory.** Without the teardown, a subsequent test's autouse fixture inherits a console that's already buffered-out.
- **Log-capture pattern.** Story 1.3's `TestLogSanitization` attaches a throwaway `logging.Handler` directly to `keys.cli` because `propagate=False` makes caplog blind. Reuse the same idiom in Task 7's `test_show_log_has_kind_not_names`.
- **Help text normalisation.** Typer renders `--help` inside a rich Panel whose border glyphs (`│ ╭ ╮ ╰ ╯ ─`) fragment long option strings across rows. Story 1.3 strips those glyphs **before** collapsing whitespace so assertions like `"cust_01j8xr" in flat` survive CI 80-col wrapping. Reuse the same normaliser in Task 7.
- **Story 1.3 log routing.** `keys.cli` logger goes to stderr. Any test that asserts "log line absent from stdout" succeeds automatically; any test that asserts "log line present on stderr" must either inspect the Console-buffered stderr OR attach a local Handler.
- **Story 1.2 `_resolve_today_in_tz` seam.** Currently in `cli/commands/keys.py`. Task 6 moves it to `cli/_clock.py` and re-exports under the same underscore alias so existing `monkeypatch.setattr(keys_cmd, "_resolve_today_in_tz", ...)` calls keep working. Re-run `test_keys_cli_issue.py` + `test_keys_cli_list_keys.py` after the move.
- **Story 1.3 `_iso_date` and `_status_label`.** Already in `cli/output.py` — **import and reuse**, do not re-implement.
- **Story 1.2 `_format_brl`.** Already in `cli/output.py` — **import and reuse** (the helper is `_`-prefixed but tests and sibling modules already consume it, so the prefix is documentary not a hard private).
- **Story 1.2 `get_customer` treats tombstones as missing.** AC6 tombstone test relies on this contract. Do NOT regress it by adding an `include_deleted` flag here.

### Git intelligence

Last 5 commits on master (as of 2026-04-17 late afternoon, after Story 1.3's completion):
- **Story 1.3 landing commit** (squashed via code-review workflow) — foundations this story builds on: `list_customers` / `list_api_keys` / `count_first_run` / `count_tombstones` in `db.py`; `_status_label` / `_iso_date` / `render_customer_list` / `render_key_list` / `render_json` / `render_empty_state` in `output.py`; the stderr log-routing fix in `cli/__init__.py`; the `CustomerListRow` + `ApiKeyListRow` dataclasses.
- `612d952 feat(keys): land story 1.2` — `issue-key`, `_format_brl`, `_resolve_today_in_tz`, `get_customer`, KeyPanel.
- `50cdada feat(keys): land story 1.1` — the foundational `keys/` package + migration v001 + `create-customer`.
- `f07e662 docs(bmad): land 2.0.0 architecture, epics, readiness report, and sprint plan` — planning context.
- `05e0b59 feat(voices): add pm_influencer_01 voice profile` — unrelated.

Working tree should be clean at story start (Story 1.3 done). The only expected modifications before Story 1.4 lands: this story file and `sprint-status.yaml` (both committed separately by the create-story workflow).

### Deferred-work items relevant to this story

From `_bmad-output/implementation-artifacts/deferred-work.md`:

- **`comadre-keys` CLI still requires TTS-side config (`api_key`, `domain`).** Story 1.4 inherits the same limitation — a `.env` with `API_KEY=test` + `KEY_REGISTRY_ENCRYPTION_KEY=<fernet>` is sufficient. Epic 2 splits the settings.
- **`price_monthly` float drift.** `_format_brl` rounds at two decimals; a fixture `price=149.0 - 0.01` showing as `R$ 148,99` is a test-data bug, not a formatter bug.
- **Request-log stats.** Journey 5 PRD shows a mock `Last 24h stats` block. That is Story 2.3, not 1.4. Do NOT add request-stat aggregation to the `show` output.

### UX invariants reproduced from `ux-design-specification.md`

- **UX-DR3 DetailPanel** (`ux:L768-L786`): single-line border, labeled key-value pairs, right-padded labels to longest, color-coded status field, audit tail appended below as a separate section.
- **UX-DR5 AuditTail** (`ux:L805-L818`): no panel border (supplementary, not primary); two-space indent; newest first; timestamp + event + actor + optional detail columns; `No events recorded` empty state.
- **UX-DR8 4-color palette** (`ux:L382-L403`): unchanged from Story 1.3 — reuse `_status_label`.
- **UX-DR9 Shared console** (`ux:L250-L256`): all output through `stdout_console()` / `stderr_console()`.
- **UX-DR12 Empty results are not errors** (`ux:L1017-L1029`): `show --audit-tail` with zero events exits 0 with `No events recorded`.
- **UX-DR15 Realistic `--help` examples** (`ux:L995-L1013`): AC10 enumerates the strings.
- **UX-DR16 Terminal width adaptation** (`ux:L1063-L1081`): 80-col minimum; rich wraps long Panel bodies automatically.
- **Exit codes (UX-DR10, `ux:L1046-L1056`):** 0 success, 2 usage, 3 not-found / ambiguous, 5 database, 6 config. **Important**: `show` introduces exit 3 on the DETAIL path (Story 1.3 `list-keys --customer <missing>` was exit 0 — filter miss is not an error there). The difference is intentional: `show` is a direct lookup; missing a direct lookup IS an error.

### Scope guards (things NOT to do in this story)

- **Do NOT add `update-*` commands.** Stories 1.5, 1.6.
- **Do NOT decrypt `tax_id_encrypted`.** Only `tax_id_kind` surfaces.
- **Do NOT add `--format yaml`.** YAML is reserved for Story 4.1's `export-customer`.
- **Do NOT add `--audit-tail` to `list-customers` / `list-keys`.** Audit tail is scoped to `show`. Adding it to listings would overflow the 80-col row budget and dilute the "detail view" intent.
- **Do NOT add request-log stats (peak RPM, 429 count, avg RPM).** Story 2.3.
- **Do NOT add a migration file.** Schema unchanged.
- **Do NOT add a new dependency.** Story 1.4 uses `rich` (already in), `typer` (already in), `sqlite3` (stdlib), `datetime` (stdlib), `json` (stdlib). Nothing else.
- **Do NOT touch `src/comadre/main.py`, `api.py`, `rate_limit.py`, `service.py`, `config.py`, `exceptions.py`, or `cli/app.py`.** The last is technically part of the CLI, but `app.py` picks up new commands via the existing `app.registered_commands.extend(...)` flow — no edits needed.
- **Do NOT regress Story 1.3's `keys.cli` → stderr log routing.** JSON stdout purity depends on it.
- **Do NOT add tombstone inspection to `show`.** Tombstoned customers yield exit 3 not-found. Story 4.1 handles the purge-introspection path.
- **Do NOT index `key_prefix`.** Even at 5,000 keys, a full table scan on an 8-char TEXT column is sub-millisecond. Adding an index just for `show` is premature — wait until a real perf issue exists (none in the NFR4 budget).

### Enumeration resistance & log sanitization (FR37, NFR15, NFR16)

- **Not-found and ambiguous errors** echo only the operator-supplied input (their own text — not an enumerated DB value). The error title is identical for customer-shape and key-prefix-shape inputs: `Not found: no customer or key matches '<input>'`. Rationale: branching would signal whether customers or keys are being registered at all.
- **Ambiguous prefix error** does NOT reveal the colliding `key_` ULIDs or customer names. Only the prefix echoes back. (Practically impossible to hit in prod — test exists to lock the behaviour in.)
- **INFO log format** (Task 4.2 step 8): `Showed detail | kind=<customer|key_single|...> | target=<opaque> | audit_tail=<int|None>`. `target` is an opaque ULID or an 8-char prefix (safe — FR37 threat model for Story 1.3 already cleared opaque IDs). **NEVER** include customer name, email, tax-id, or `details_json` contents in the log.
- **Stored `tax_id_encrypted`** is ciphertext bytes — the Story 1.4 code path never reads this column (the detail-row dataclass doesn't carry it; the SELECT clause doesn't select it). Task 8.6 grep guard locks this in.

### Project Structure Notes

- **New files (2):**
  - `src/comadre/keys/cli/_clock.py` — the relocated `resolve_today_in_tz` seam.
  - `tests/test_keys_cli_show.py` — the Task 7 integration suite.
- **Modified existing files (4 + test appends):**
  - `src/comadre/keys/models.py` — +3 dataclasses (`CustomerDetailRow`, `KeyDetailRow`, `AuditEventRow`).
  - `src/comadre/keys/db.py` — +4 helpers (`get_customer_detail`, `get_key_detail`, `list_audit_events`, `resolve_show_target`) + 1 sibling (`get_key_detail_by_id`) + `ShowTarget` dataclass.
  - `src/comadre/keys/cli/output.py` — +4 renderers (`render_customer_detail`, `render_key_detail`, `render_audit_tail`, `render_show_json`).
  - `src/comadre/keys/cli/commands/customers.py` — +`show` command + 3 JSON helpers (`_customer_detail_to_json`, `_key_detail_to_json`, `_audit_event_to_json`).
  - `src/comadre/keys/cli/commands/keys.py` — +1 import change (relocated `_resolve_today_in_tz`).
  - `tests/test_keys_models.py` — +3 dataclass test classes.
  - `tests/test_keys_db.py` — +detail / audit / resolver test cases.
  - `tests/test_keys_output.py` — +4 renderer test classes.
- **No changes to existing runtime files** (`api.py`, `main.py`, `rate_limit.py`, `service.py`, `config.py`, `exceptions.py`, `cli/app.py`, `cli/__init__.py`).
- All placements per architecture.md §Module Organization (L327-L350). No deviations.

### Testing Standards

- All tests mocked by default; no real models, no `@pytest.mark.slow`.
- `CliRunner` from `typer.testing` for CLI tests — synchronous, same as Stories 1.1 / 1.2 / 1.3.
- `tmp_path` for DB files. In-memory SQLite (`sqlite3.connect(":memory:")`) is fine for pure-SQL-shape tests in `test_keys_db.py` (Task 2.5), but NOT for the `get_connection()` wrapper (chmod's the file, needs a real path).
- Reuse Story 1.1's `_clear_settings_cache` autouse from `tests/conftest.py`.
- Target coverage: 90%+ on the new code (`resolve_show_target`, `get_customer_detail`, `get_key_detail`, `list_audit_events`, `render_customer_detail`, `render_key_detail`, `render_audit_tail`, `render_show_json`, the new `show` command).
- Autouse fixture `_reset_consoles_to_buffers` — copy the exact version from `test_keys_cli_list_keys.py:L34-L46`.
- `width=120` in the test console — same as Stories 1.1/1.2/1.3. At this width the DetailPanel + AuditTail render without rich truncation, so assertions on cell text are reliable.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-1.4-Key-Customer-Detail-View-with-Audit-Trail` (L397-L428)] — AC source text.
- [Source: `_bmad-output/planning-artifacts/prd.md#CLI-Tool-Specification` (L973-L986)] — `show <customer-id | key-prefix> [--audit-tail N]` spec.
- [Source: `_bmad-output/planning-artifacts/prd.md#Journey-5-Debug-Session` (L436-L483)] — `show --audit-tail` diagnostic usage + Last 24h stats mock (Story 2.3, out of scope).
- [Source: `_bmad-output/planning-artifacts/prd.md#Functional-Requirements` (L1139, L1166)] — FR14 + FR32.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Naming-Patterns` (L291-L322)] — DB / ID / audit-action / CLI naming. `show` is a one-word command (no hyphen).
- [Source: `_bmad-output/planning-artifacts/architecture.md#Import-Boundary-Rules` (L366-L372)] — CLI must not import from `keys.auth` or `keys.cache`.
- [Source: `_bmad-output/planning-artifacts/architecture.md#SQLite-Query-Patterns` (L376-L383)] — parameterized `?` placeholders, no f-string SQL.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Enforcement-Guidelines` (L471-L488)] — grep-based regression rules (Task 8.6).
- [Source: `_bmad-output/planning-artifacts/architecture.md` (L738)] — MVP `show --audit-tail` reads only `audit_log` (no request-log counters).
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#DetailPanel` (L768-L786)] — component spec.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#AuditTail` (L805-L818)] — component spec + empty-state rule.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Information-Architecture` (L445-L470)] — compound command output structure (DetailPanel + AuditTail).
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Visual-Design-Foundation` (L382-L403)] — 4-color palette rules (reused via `_status_label`).
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Responsive-Strategy` (L1063-L1081)] — 80-col adaptation.
- [Source: `_bmad-output/implementation-artifacts/1-1-customer-registration-with-cpf-cnpj-validation.md#Dev-Agent-Record`] — CliRunner fixture pattern, no-DB-for-help rule.
- [Source: `_bmad-output/implementation-artifacts/1-2-api-key-issuance.md#Dev-Agent-Record`] — `_resolve_today_in_tz` seam, `_format_brl`, `get_customer` tombstone contract.
- [Source: `_bmad-output/implementation-artifacts/1-3-customer-key-listing.md#Dev-Agent-Record`] — `_status_label`, `_iso_date`, `render_json`, `render_empty_state`, stderr log routing (load-bearing for AC8), caplog/propagate workaround, help-surface Panel-glyph normalisation.
- [Source: `_bmad-output/project-context.md#Critical-Implementation-Rules`] — uv-only, no `os.environ`, no raw `HTTPException`, structured logging, English only.
- [Source: `CLAUDE.md`] — project language policy, Docker v2, `uv` only, no raw `HTTPException`, no `print()`.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (claude-opus-4-7) via the BMAD `bmad-dev-story` workflow.

### Debug Log References

- Audit tests picked up an extra `create_customer` audit row from the
  `_seed_customer` helper (which runs `insert_customer`, a writer). Switched
  the Story-1.4 audit tests to the pre-existing `_seed_customer_with_time`
  raw-SQL seeder (via a thin `_seed_customer_raw` wrapper) so the audit
  fixtures start with a clean `audit_log`.
- `show --help` auto-rendering test (AC10): the existing Story 1.3
  normalisation (strip ANSI + Panel glyphs, collapse whitespace) carries
  over unchanged — reused verbatim in `TestShowHelpSurface`.
- `Age: today` assertion in the AC1 happy-path test was initially freezing
  the clock to `date(2026, 4, 16)` but `issue-key` writes `created_at` via
  `datetime.now(UTC)` (today's real date). Switched the freeze to
  `datetime.now(UTC).date()` so the fixture day matches the inserted row.

### Completion Notes List

- Added three frozen+slots dataclasses (`CustomerDetailRow`,
  `KeyDetailRow`, `AuditEventRow`) to `src/comadre/keys/models.py`.
- Added detail/audit/resolver helpers to `src/comadre/keys/db.py`:
  `get_customer_detail`, `get_key_detail`, `get_key_detail_by_id`,
  `list_audit_events`, `resolve_show_target`, and a `ShowTarget`
  discriminated-result dataclass. `list_audit_events` builds its
  `IN (…)` placeholder list programmatically (`",".join("?" * n)`),
  matching Story 1.3's precedent — operator input only lands in
  positional `?` bindings.
- Added `render_customer_detail`, `render_key_detail`,
  `render_audit_tail`, and `render_show_json` to
  `src/comadre/keys/cli/output.py`. All reuse the pre-existing
  `_status_label`, `_iso_date`, `_format_brl` helpers (no re-implementation).
- Moved the `_resolve_today_in_tz` clock seam into a dedicated
  `src/comadre/keys/cli/_clock.py` module and re-exported it from
  `keys.py` (via `from … import resolve_today_in_tz as _resolve_today_in_tz`)
  so existing `monkeypatch.setattr(keys_cmd, "_resolve_today_in_tz", …)`
  tests keep working unchanged. Imported under the same underscore alias
  in `customers.py`.
- Added the `show` command + AC8 JSON serializers
  (`_customer_detail_to_json`, `_key_detail_to_json`, `_audit_event_to_json`)
  in `src/comadre/keys/cli/commands/customers.py`. The `--format json` path
  never emits hint text; not-found / ambiguous errors still route to stderr
  with exit 3.
- Structured INFO log format: `Showed detail | kind=<…> | target=<…> |
  audit_tail=<…>`. Never includes customer name / email / tax id.
- Audit tail scoping: for the customer path, `target_ids` is the customer
  id plus every `api_key.id` owned by that customer (so the section shows
  "everything about this customer" per AC4). For the key path, the scope
  is just the key id (per AC2). Order: newest-first with `occurred_at DESC,
  id DESC` tie-break.
- Full regression suite: 800 passing (up from 703 at Story 1.3 close).
  `uv run ruff check .`, `uv run ruff format --check .`, `uv run mypy
  src/comadre/keys/`, and `uv run pre-commit run --all-files` all green.
- Epic 4.5 regression greps — all clean:
  - No `HTTPException` in `src/comadre/keys/cli/commands/`.
  - No f-string SQL in `src/comadre/keys/db.py`.
  - No bare `print(` in `src/comadre/keys/` (only `console.print(...)`).
  - No `os.environ` in `src/comadre/keys/`.
  - Only pre-existing (Story 1.1 create-customer) write-path reference to
    `tax_id_encrypted` in `src/comadre/keys/cli/`; no read path touches the
    column (the `CustomerDetailRow` dataclass doesn't even carry it, and
    the `get_customer_detail` SELECT clause omits it).
- Manual smoke-test (table, audit-tail, JSON, error paths) verified on a
  throwaway `/tmp/show-smoke/registry.db` against a fresh CLI build.

### File List

- `src/comadre/keys/cli/_clock.py` (new) — relocated `resolve_today_in_tz`
  seam.
- `tests/test_keys_cli_show.py` (new) — AC1–AC10 integration suite.
- `src/comadre/keys/models.py` — +`CustomerDetailRow`, +`KeyDetailRow`,
  +`AuditEventRow`.
- `src/comadre/keys/db.py` — +`ShowTargetKind`, +`ShowTarget`,
  +`get_customer_detail`, +`get_key_detail`, +`get_key_detail_by_id`,
  +`_row_to_key_detail`, +`_KEY_DETAIL_SELECT`, +`list_audit_events`,
  +`resolve_show_target`, new `Sequence`/`Literal`/`dataclass`/`date`
  imports.
- `src/comadre/keys/cli/output.py` — +`render_customer_detail`,
  +`render_key_detail`, +`render_audit_tail`, +`render_show_json`,
  +`_pad_label`, +`_format_last_used`, +`_format_age`, label tuples,
  `Literal` import, new dataclass imports.
- `src/comadre/keys/cli/commands/keys.py` — dropped the local
  `_resolve_today_in_tz` body in favour of the `cli._clock` re-export
  (same underscore alias preserved).
- `src/comadre/keys/cli/commands/customers.py` — +`show_cmd`,
  +`_customer_detail_to_json`, +`_key_detail_to_json`,
  +`_audit_event_to_json`, +`_SHOW_NOT_FOUND_HINT`,
  +`_SHOW_AMBIGUOUS_HINT`, new `json`/`ZoneInfo`/`_clock`/`_apply_migrations`-sibling
  imports.
- `tests/test_keys_models.py` — +`TestCustomerDetailRow`,
  +`TestKeyDetailRow`, +`TestAuditEventRow`.
- `tests/test_keys_db.py` — +`TestGetCustomerDetail`,
  +`TestGetKeyDetail`, +`TestGetKeyDetailById`, +`TestListAuditEvents`,
  +`TestResolveShowTarget`, +`TestShowHelpersDoNotWrite`,
  +`_insert_audit`, +`_seed_customer_raw`, +`_FROZEN_TODAY`,
  new `date`/`KeyDetailRow`/db-helper imports.
- `tests/test_keys_output.py` — +`TestRenderCustomerDetail`,
  +`TestRenderKeyDetail`, +`TestRenderAuditTail`, +`TestRenderShowJson`,
  +`_make_customer_detail`, +`_make_key_detail`, +`_audit_event`.

### Change Log

- 2026-04-17: Story 1.4 implementation complete. `comadre-keys show` with
  DetailPanel + AuditTail + JSON output + anti-enumeration error surface.
  Clock seam relocated to `cli/_clock.py` for reuse across customer and
  key commands. All regression suites (800 tests), ruff, mypy strict, and
  pre-commit green. Status → review.

### Review Findings

Code review on 2026-04-17. Three parallel layers: Blind Hunter (adversarial,
diff-only), Edge Case Hunter (path tracer, repo read-only), Acceptance
Auditor (spec conformance). Triage: 4 patches, 3 deferrals, ~31 dismissed
(spec-compliant, established pattern, or noise).

- [x] [Review][Patch] `cmdr_live_…` plaintext leaked to INFO log [src/comadre/keys/cli/commands/customers.py:541-546] — Fixed: `target_log` now redacts `cmdr_live_…` payloads to `cmdr_live_<first-8>…` before the structured log emission. Regression test `TestShowLogSanitization::test_log_redacts_cmdr_live_plaintext` locks the contract.
- [x] [Review][Patch] AC6 anti-enumeration identity test uses substring, not equality [tests/test_keys_cli_show.py:566-577] — Fixed: `test_error_title_identical_for_customer_and_key_shapes` now strips Rich box-drawing decorations (which auto-size to the operator's input width and are not a coded branch) and asserts the full text is byte-equal modulo the echoed operand.
- [x] [Review][Patch] AC8 fixed key order asserted only by set membership in CLI integration tests [tests/test_keys_cli_show.py:623, 645] — Fixed: both `test_customer_shape` and `test_key_shape` now assert `list(target.keys()) == [...]` with the explicit AC8 key order.
- [x] [Review][Patch] `cmdr_live_` resolver branch comment is wrong [src/comadre/keys/db.py:540-541] — Fixed: comment now reads "resolve through the same bare-prefix lookup as the fallback branch below" — accurate to the inline-return shape.
- [x] [Review][Defer] `ShowTarget.value` typing forces `cast(...)` at every call site [src/comadre/keys/db.py:559-569, src/comadre/keys/cli/commands/customers.py:527, 534, 560, 567, 573, 575] — deferred, pre-existing. Spec §Task 8.2 explicitly accepts the discriminated-union shape; `match`/variant-dataclass refactor would be cross-cutting and is not warranted by Story 1.4 alone.
- [x] [Review][Defer] `list_audit_events` IN-clause hits `SQLITE_MAX_VARIABLE_NUMBER` for customers with hundreds of keys [src/comadre/keys/db.py:list_audit_events] — deferred, pre-existing-style. SQLite's modern default cap is 32k, but the path is still unbounded by code; add chunking or move to a temp table when bulk operators arrive (no current customer has >20 keys).
- [x] [Review][Defer] Rich-markup injection via stored `name` / `notes` / `customer_name` interpolated into Panel bodies [src/comadre/keys/cli/output.py:render_customer_detail, render_key_detail] — deferred, pre-existing pattern from Story 1.2/1.3 panels. A stored value containing `[red]Acme[/]` would re-style the panel. Address as a cross-cutting `rich.markup.escape(...)` sweep over all `render_*` helpers in a hardening pass.
