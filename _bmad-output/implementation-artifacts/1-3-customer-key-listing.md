# Story 1.3: Customer & Key Listing

Status: done

<!-- Validation optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want to list my customers and their keys with color-coded status and scannable tables,
so that I can see my portfolio at a glance and filter by status, billing mode, customer, or paid-until date for the monthly billing ritual.

**Covers FRs:** FR7 (list customers with tombstone filter), FR13 (list keys with filters)
**UX-DRs:** UX-DR2 (StatusTable), UX-DR8 (4-color palette), UX-DR9 (shared console), UX-DR10 (exit codes), UX-DR12 (empty results are not errors), UX-DR13 (first-run hint vs subsequent empty), UX-DR15 (realistic `--help` examples), UX-DR16 (80-col adaptation)
**NFRs:** NFR4 (list-class under 200 ms for 1 K customers), NFR33 (backwards-compatible within major version)
**Epic:** 1 — Key Registry & Customer Management
**Builds on:** Story 1.1 (`keys/` subpackage, `customer` + `api_key` + `audit_log` tables, `CustomerRecord` dataclass, `render_error`/`render_confirmation`, `_format_brl`, CliRunner/`_reset_for_tests` test harness, shared `_errors.py` helpers). Story 1.2 (`ApiKeyRecord`, `insert_api_key`, `generate_key_id`, `_format_brl`, `get_customer`).
**Unblocks:** Story 1.4 (`show <prefix|id>` reuses `DetailPanel` which shares the label-padding helper with `StatusTable`). Story 3.1 (`mark-paid` copy-pastes from Journey 2 which assumes the listings already exist). Story 3.2 (`at-risk` is another StatusTable variant).
**Depends on:** Nothing outside Stories 1.1–1.2 — no new dependencies, no new schema, no runtime-path changes.

## Scope

This story adds **two commands** — `list-customers` and `list-keys` — plus the shared `StatusTable` renderer they both produce (`list-customers` uses a subset without a status column; `list-keys` uses the full color-coded variant). Work breaks down as:

1. **DB read helpers** in `src/comadre/keys/db.py`:
   - `list_customers(conn, *, include_deleted: bool) -> list[CustomerListRow]` — LEFT JOIN against `api_key` so each row carries a `key_count`. Parameterized SQL only.
   - `list_api_keys(conn, *, status, billing_mode, customer_id, paid_until_lte) -> list[ApiKeyListRow]` — JOIN customer to surface `customer_name` for the table. Each filter is optional; unspecified filters are omitted from the WHERE clause (not passed as wildcard).
2. **Two new typed row dataclasses** in `src/comadre/keys/models.py`: `CustomerListRow` (id, name, email, tax_id_kind, key_count, registered_at, deleted_at, notes) and `ApiKeyListRow` (id, customer_id, customer_name, key_prefix, status, billing_mode, rate_limit_rpm, price_monthly, paid_until, created_at, last_used_at). These are immutable `@dataclass(frozen=True, slots=True)` per Story 1.2 convention.
3. **`StatusTable` renderer** in `src/comadre/keys/cli/output.py` — `render_status_table(title, rows, columns)` plus two command-specific assembly helpers: `render_customer_list(title, rows, *, first_run_hint)` and `render_key_list(title, rows)`. Color-coded status cells use `[green]active[/]`, `[yellow]suspended[/]`, `[red]revoked[/]`, `[blue]complimentary[/]` — text-first with color as accelerator (UX-DR8).
4. **JSON output mode** — `--format json` bypasses `rich` and emits via `Console.print_json()` on stdout. Contract documented in AC4 and AC8. Never include decrypted tax-ID values (that's Story 4.1's `export-customer` concern).
5. **First-run empty-state hint** — `list-customers` with zero rows on a DB that has never held a customer prints the create-customer usage line (UX-DR13). Subsequent empty results (e.g., `--deleted` with no tombstones) print just the informational sentence.
6. **New command modules** follow architecture §Module Organization exactly: `list-customers` lives in `cli/commands/customers.py`; `list-keys` lives in `cli/commands/keys.py`.
7. **Unit + integration tests** in `tests/test_keys_db.py`, `tests/test_keys_output.py`, and two new integration files `tests/test_keys_cli_list_customers.py` and `tests/test_keys_cli_list_keys.py` (same `CliRunner` + `_reset_for_tests` + `StringIO` pattern established in Story 1.1/1.2).

**Out of scope (future stories, DO NOT add):**

- `show <prefix|id>` (DetailPanel + audit tail) → Story 1.4.
- `update-customer` / `update-key` → Stories 1.5, 1.6.
- `rotate-key` / `revoke-key` / `suspend` / `reactivate` → Stories 1.6, 3.1.
- `at-risk` / `revenue` / `mark-paid` → Stories 3.1, 3.2.
- Decrypting tax IDs for display → never in list commands; Story 1.4's `show` decrypts, Story 4.1's `export-customer` decrypts.
- Auth-path reads, cache, `verify_api_key_registry` → Epic 2. **Never import from `keys.auth` or `keys.cache` in this story — those modules do not yet exist** (architecture §Import Boundary Rules).
- Last-24 h request-stat counters → Story 2.3 (`show --audit-tail` territory in 1.4 shows audit-log events, not in-memory counters).
- Audit-log rows for read operations — list commands are **read-only**; no `audit_log` row is written by either command (architecture §Transaction Scope: "audit log writes happen inside the same transaction as the mutation they record" — read queries are not mutations).

## Acceptance Criteria

> BDD-style. Every AC has a unit or integration test. Source AC text lives in `_bmad-output/planning-artifacts/epics.md:L355-L396` — this block expands each item with the technical detail the dev agent must honour.

### AC1 — `list-customers` populated happy path (FR7, UX-DR2, UX-DR9)

**Given** the operator has registered three customers via `create-customer` (Story 1.1) and issued zero or more keys against each via `issue-key` (Story 1.2)
**When** the operator runs `comadre-keys list-customers`
**Then**
- A `rich.Table` is printed to **stdout** with the shared `stdout_console()` singleton and `title="Customers"`. Column order follows UX-DR2's invariant (identifier → name → …): **Customer ID**, **Name**, **Email**, **Keys**, **Registered**. Exactly five columns — `list-customers` does not show a status column (customers have no status field in the schema).
- Column alignments: Customer ID left, Name left, Email left, Keys right (integer), Registered left (ISO 8601 date `YYYY-MM-DD`, not datetime — the table view strips the time-of-day component for scannability).
- Row order: `registered_at ASC` (oldest first — matches ULID natural sort; stable and predictable).
- Below the table, a plain stdout line prints `<N> customers found.` using `render_confirmation()` (UX-DR7 style — single line, no panel). Exactly one line; no trailing blank line.
- The `Keys` column shows the count of `api_key` rows joined by `customer_id`, regardless of key status (active + suspended + revoked + complimentary all counted). Implementation uses a single `SELECT ... LEFT JOIN api_key USING (customer_id) GROUP BY customer.id` — not N+1 per-row counts.
- Tombstoned rows (`deleted_at IS NOT NULL`) are **excluded** by default — the default WHERE clause includes `deleted_at IS NULL`.
- Exit code `0`. No stderr output. No `audit_log` row written.

### AC2 — `list-customers` empty states with UX-DR13 hint policy

**Given** the SQLite database exists and the `customer` table is empty (never held a row)
**When** the operator runs `comadre-keys list-customers`
**Then**
- stdout prints exactly two lines via `render_confirmation()`:
  ```
  No customers registered yet.
  To get started: comadre-keys create-customer --name "Name" --email "email@example.com" --cpf "000.000.000-00"
  ```
  Literal string match; the hint text mirrors `ux-design-specification.md:L1031-L1041` verbatim (including the `To get started:` prefix). Exit code `0` (empty results are NOT errors, UX-DR12). No error panel. No stderr.
- First-run detection: the hint prints if and only if **zero customer rows exist at all, including tombstones**, and zero api_key rows exist. Implementation: `SELECT COUNT(*) FROM customer` and `SELECT COUNT(*) FROM api_key` — both zero ⇒ first-run. A database with tombstoned-only customers is NOT first-run (the operator has used the system before).

**Given** customers exist but all have `deleted_at IS NOT NULL` (purged)
**When** the operator runs `comadre-keys list-customers` (no `--deleted` flag)
**Then**
- stdout prints exactly one line: `No active customers. Run 'comadre-keys list-customers --deleted' to see purged records.`
- Exit code `0`. No first-run hint (the operator has used the system).

**Given** customers exist (at least one active)
**When** the operator runs a filter that produces no rows — for this story only the tombstone filter path applies; for empty-result filter cases on `list-keys` see AC7
**Then** N/A for `list-customers` (no filter flags other than `--deleted`; see AC3).

### AC3 — `list-customers --deleted` includes tombstones (FR7, UX-DR2)

**Given** some customers are tombstoned (`deleted_at IS NOT NULL`) and some are active (`deleted_at IS NULL`)
**When** the operator runs `comadre-keys list-customers --deleted`
**Then**
- The table **includes** tombstoned customers alongside active ones. The table title becomes `"Customers (including purged)"` (distinct from the default `"Customers"` — UX-DR2 "table title reflects applied filter").
- Each tombstoned row shows the customer id, name, email, key count, and registered date **exactly as before the purge** — Story 4.1's `delete-customer --hard` will null the personal-data columns and only retain `id` + `registered_at` + `deleted_at`, but that's a Story 4.1 concern. For Story 1.3, the query returns whatever columns are present and the renderer does not attempt to detect purge state. A `Deleted` column is NOT added (rationale: UX-DR2 caps at 7 columns and the tombstone flag is implicit from the presence of a `deleted_at` row in the `--deleted` listing).
- Row order: `registered_at ASC`. Tombstoned rows sort naturally alongside active ones by their original registration time — do NOT move purged customers to the bottom.
- `--deleted` with zero rows total (no customers active or tombstoned) emits the first-run hint described in AC2 (zero-customer + zero-key DB is first-run regardless of flags).

### AC4 — `list-customers --format json` machine-readable output (PRD §CLI, FR7)

**Given** two customers exist, one with two keys and one with zero
**When** the operator runs `comadre-keys list-customers --format json`
**Then**
- stdout emits **valid JSON** — a top-level array, one object per customer, in the same row order as the human-readable table (`registered_at ASC`). No rich formatting, no ANSI escape sequences, no table borders, no row-count sentence.
- Per-object schema, lowercase snake_case keys:
  ```json
  {
    "id": "cust_01jgxr...",
    "name": "Helena Ribeiro",
    "email": "helena@clinica.com",
    "tax_id_kind": "cpf",
    "key_count": 2,
    "registered_at": "2026-04-15T12:34:56Z",
    "deleted_at": null,
    "notes": ""
  }
  ```
  `tax_id_encrypted` is **NOT** included — it's ciphertext, pointless to consumers and opens a surface for exfiltration scripts. `deleted_at` appears as `null` for active rows, as the ISO timestamp for tombstones. Order of keys within each object is the order above (use a helper `dict` literal, not the row factory's insertion order — deterministic for tests).
- The JSON is emitted via `rich.Console.print_json()` on the stdout console so `NO_COLOR` and `force_terminal` still behave (rich strips ANSI in JSON mode anyway, but use the same console for output consistency).
- `stdout | jq length` returns the row count; errors (if any) appear only on stderr. No informational "N customers found" line on stdout in JSON mode.
- With zero rows, the output is `[]` (empty array) — NOT the first-run hint text (that would break JSON consumers). Exit code `0`.
- `--deleted --format json` is supported — includes tombstoned rows in the array in the same order.

### AC5 — `list-keys` populated happy path with color-coded status (FR13, UX-DR2, UX-DR8)

**Given** keys exist across the four status/billing combinations (at least one each of: active manual, suspended manual, revoked manual, active complimentary)
**When** the operator runs `comadre-keys list-keys`
**Then**
- A `rich.Table` is printed to stdout with `title="Keys"` and columns in UX-DR2 invariant order: **Prefix**, **Customer**, **Status**, **RPM**, **Price**, **Paid Until**. Six columns — well under the 7-column UX-DR16 cap. Do NOT add a `Billing Mode` column (the `Status` cell already disambiguates `complimentary`; adding it bloats the 80-col table past its 7-column budget when we later add `--audit-tail`-like variants).
- Column alignments: Prefix left (fixed 8-char monospace handle), Customer left, Status left (color-coded text cell), RPM right, Price right (pt-BR locale via `_format_brl` from Story 1.2 — `R$ 149,00`, `R$ 1.234,56`), Paid Until left (ISO `YYYY-MM-DD` or the literal `—` em-dash for NULL).
- Status cell rendering (UX-DR8 — color + text label, never color-only):
  - `active` → `[green]active[/green]` (manual billing) or `[blue]complimentary[/blue]` (the `complimentary` label supersedes `active` for complimentary keys — UX-DR8 semantic: blue carries the meaning, and the operator reads the billing-mode status directly)
  - `suspended` → `[yellow]suspended[/yellow]`
  - `revoked` → `[red]revoked[/red]`
  The `status` column value is derived from a small pure helper `_status_label(status, billing_mode) -> tuple[str, str]` returning `(text, color)` so the test can assert label mapping without parsing rich markup.
- Price cell rendering:
  - `billing_mode='manual'` → `R$ 149,00/month` (pt-BR, `_format_brl` already enforces dot-thousand/comma-decimal)
  - `billing_mode='complimentary'` → `R$ 0,00` (no `/month` suffix; no "bundled externally" parenthetical — that's reserved for the KeyPanel in UX-DR1 which has more real estate).
- Paid Until cell: ISO date for manual keys with a non-NULL `paid_until`; `—` (U+2014 em-dash) for NULL (trial window) and for all complimentary keys.
- Row order: `created_at ASC` (oldest key first — matches ULID natural ordering; stable, predictable, matches the PRD Journey 5 output style).
- Below the table, a plain stdout line prints `<N> keys found.` (plural `keys` always — "1 key found" vs "2 keys found" IS acceptable in English but the spec uses the plural constant for simplicity; N=1 still prints "1 keys found". OPTIONAL polishing — use the simpler constant form).
- Exit code `0`. No stderr. No `audit_log` row written (read-only contract).

### AC6 — `list-keys` filters: `--status`, `--billing-mode`, `--customer`, `--paid-until-lte` (FR13, UX-DR2)

**Given** a populated database with a mix of statuses, billing modes, customers, and paid-until dates
**When** the operator runs any of the filter combinations below
**Then**
- `--status {active|suspended|revoked}` — filters by `api_key.status = ?`. Table title becomes `"Active Keys"`, `"Suspended Keys"`, or `"Revoked Keys"` (UX-DR2). Typer-level validation: any other value → exit 2, `render_error("Usage error: --status must be active, suspended, or revoked", "Valid values: active, suspended, revoked.")`.
- `--billing-mode {manual|complimentary}` — filters by `api_key.billing_mode = ?`. Table title becomes `"Manual Keys"` or `"Complimentary Keys"`. Invalid value → exit 2, same usage-error template. **Do NOT accept `automated`** — the schema allows it for a future PSP adapter, but no key in the MVP carries that value, and exposing it as a filter would promise a capability we don't have.
- `--customer <cust_...>` — filters by `api_key.customer_id = ?`. Table title becomes `"Keys for <customer_name>"` (the name is looked up once; if the customer ID doesn't resolve, the command treats the result set as empty and the title falls back to `"Keys for <customer_id>"`). No exit-3 "customer not found" — that would fight AC7 where empty results are not errors. The operator who typos a customer ID sees "0 keys found" and re-runs the command with the right ID.
- `--paid-until-lte <DATE>` — filters by `(api_key.paid_until IS NULL OR api_key.paid_until <= ?)`. Accepts either an ISO date `YYYY-MM-DD` or the literal string `today` (resolved once per invocation via `_resolve_today_in_tz(billing_tz)` — the Story 1.2 seam, so tests can freeze the clock). Any other string → exit 2 usage error, title `Usage error: --paid-until-lte must be an ISO date (YYYY-MM-DD) or 'today'`.
- Filters **compose** via AND. Example: `list-keys --status active --billing-mode manual --paid-until-lte today` yields the canonical Journey 2 "who owes me?" query. Each composed filter contributes one AND clause.
- **Table title precedence (prescriptive):** when multiple filters are set, pick the **single most-specific** title in this priority order and do NOT stack:
  1. `--customer` set → `"Keys for <name>"` (or `"Keys for <customer_id>"` if the id doesn't resolve; see step 5 in Task 5.2).
  2. else `--billing-mode` set → `"Manual Keys"` / `"Complimentary Keys"`.
  3. else `--status` set → `"Active Keys"` / `"Suspended Keys"` / `"Revoked Keys"`.
  4. else `--paid-until-lte` set → `"Keys (paid until ≤ <date>)"`.
  5. else (no filters) → `"Keys"`.
  Rationale: stacking filter adjectives ("Active Manual Keys for Helena (paid until ≤ 2026-04-15)") wrecks the 80-col budget; the row data already reflects all composed filters, so the title just advertises the operator's intent at a glance. Document the precedence in a doc-comment on the `_resolve_title` helper.
- **SQL injection safety:** all four filter values are bound via `?` placeholders. The filter list is assembled programmatically — `WHERE` clauses concatenate from a `list[str]` of predicate strings and a parallel `list[Any]` of parameter values. **Never interpolate `status`, `billing_mode`, the customer id, or the date into the SQL string literal** (FR48, Story 4.5g bandit scan will flag this pattern).

### AC7 — `list-keys` empty result sets (UX-DR12, UX-DR13)

**Given** the DB has customers but zero `api_key` rows
**When** the operator runs `comadre-keys list-keys` (no filters)
**Then** stdout prints exactly two lines:
```
No keys issued yet.
To issue one: comadre-keys issue-key --customer <customer-id> --rpm 60 --price 149
```
Exit code `0`. No panel. First-run hint (UX-DR13). The `<customer-id>` placeholder literal string is preserved in the hint — the operator substitutes it.

**Given** the DB has keys but a filter excludes all of them
**When** the operator runs `comadre-keys list-keys --status suspended` and no suspended keys exist
**Then** stdout prints exactly one line: `No suspended keys found.`
Exit code `0`. No hint (operator has used the system; UX-DR13).

**Given** a `--customer` filter matches an ID that does not exist in the database
**When** the operator runs `comadre-keys list-keys --customer cust_01nonexistent00000000000000`
**Then** stdout prints `No keys found for customer cust_01nonexistent00000000000000.` Exit code `0`. No not-found error panel (UX-DR12).

**Given** the DB is completely empty (zero customers and zero keys)
**When** the operator runs `comadre-keys list-keys`
**Then** the first-run two-line hint applies (same as the first case above). The command does NOT say "register a customer first" — it jumps straight to `issue-key` because `<customer-id>` in the hint is a placeholder the operator sees and resolves ("I need a customer first — let me run `create-customer`"). This keeps the hint stable across first-run states.

### AC8 — `list-keys --format json` machine-readable output

**Given** keys exist
**When** the operator runs `comadre-keys list-keys --format json` (with any combination of filters)
**Then** stdout emits a top-level JSON array of objects in `created_at ASC` order. Each object's schema:
```json
{
  "id": "key_01jgxr...",
  "customer_id": "cust_01jgxr...",
  "customer_name": "Helena Ribeiro",
  "key_prefix": "EVb4xk8B",
  "status": "active",
  "billing_mode": "manual",
  "rate_limit_rpm": 60,
  "price_monthly": 149.0,
  "paid_until": null,
  "created_at": "2026-04-15T12:34:56Z",
  "last_used_at": null
}
```
- `key_hash` is **NOT included** (hash is purely internal; exposing it serves no JSON consumer and broadens attack surface — offline brute-force, enumeration).
- `price_monthly` is emitted as a JSON number (`149.0`, `0.0` for complimentary) not a string — consumers doing math should not need to parse "R$ 149,00".
- `paid_until` is either `null` or an ISO date string `YYYY-MM-DD`. `created_at` and `last_used_at` are ISO 8601 UTC strings (or `null`).
- Empty result (including first-run): output is `[]` (empty array). **No hint text in JSON mode — ever.** Exit code `0`.
- All filters (`--status`, `--billing-mode`, `--customer`, `--paid-until-lte`) compose with `--format json` identically to the human mode.

### AC9 — Read-only contract (architecture invariant)

**Given** any `list-customers` or `list-keys` invocation succeeds or fails
**Then**
- No row is ever written to `api_key`, `customer`, or `audit_log`. Verify by snapshotting `SELECT COUNT(*)` on all three tables before and after each command in a test fixture — deltas must be zero.
- The SQLite connection is opened via `get_connection()` (enforces 0600 file mode, WAL journal, `foreign_keys=ON`) and closed in a `try/finally` wrapping `contextlib.suppress(sqlite3.Error)` (Story 1.2 pattern — suppress close errors post-commit, though here there are no commits to protect).
- No `with conn:` block is entered — these queries are pure SELECTs and do not need an explicit transaction (SQLite autocommit for reads). This also guarantees no accidental `log_event` call can sneak into a listing command and silently write audit rows (the `with conn:` boundary is the architecture's transaction anchor; its absence is the read-only signal).
- No `get_cli_actor()` call — the actor machinery is only needed for audit writes.

### AC10 — Usability and accessibility (UX-DR8, UX-DR9, UX-DR15, UX-DR16)

**Given** a terminal at 80 columns and `NO_COLOR=1` set
**When** the operator runs `list-customers` and `list-keys` with representative fixture data
**Then**
- Output is readable without horizontal scrolling. Column widths total ≤ 78 (80 minus left/right table border columns). At 80 cols the table keeps all six `list-keys` columns visible (none dropped); at narrower widths `rich` may truncate rightmost cells but headers stay visible. No explicit width override (`Console` autodetects).
- No ANSI escape sequences (`\x1b[`) appear in the captured output when `NO_COLOR=1` or `--no-color` is set — verified by capturing stdout to a `StringIO`-backed `Console(no_color=True, force_terminal=False, width=120)` in the autouse fixture and asserting `"\x1b[" not in captured`.
- Status badges remain readable without color — the text label (`active`, `suspended`, `revoked`, `complimentary`) carries the meaning (UX-DR8 "never color-only").
- Every cell content comes from data that passed through `render_confirmation`/`render_status_table` — no `print()` / `typer.echo` / raw `sys.stdout.write`. Verified by a grep-based sentinel in Task 10.

**Given** the operator runs `comadre-keys list-customers --help` or `comadre-keys list-keys --help`
**Then** Typer prints usage with realistic example values (UX-DR15), not abstract `<TEXT>` placeholders. The help text lines must include at least:
- `list-customers --help`:
  - `--deleted` help: `Include purged customers (tombstoned by LGPD hard-delete).`
  - `--format` help: `Output format. Example: --format json. Default: table.`
  - Example (in a `--help` footer or epilog): `Example: comadre-keys list-customers --deleted --format json`.
- `list-keys --help`:
  - `--status` help: `Filter by status: active, suspended, or revoked. Example: --status suspended.`
  - `--billing-mode` help: `Filter by billing mode: manual or complimentary. Example: --billing-mode complimentary.`
  - `--customer` help: `Filter by customer ID. Example: --customer "cust_01j8xr3e4c5m7kn9p2qt8vwy".`
  - `--paid-until-lte` help: `Filter by paid-until date (YYYY-MM-DD) or 'today'. Example: --paid-until-lte today.`
  - `--format` help: same as list-customers.
  - Example: `Example: comadre-keys list-keys --status active --billing-mode manual --paid-until-lte today`.
- Exit code `0`. No DB or Fernet resolution happens for `--help` (pure Typer rendering; assert `not (tmp_path / "registry.db").exists()` after a help-only invocation).

## Tasks / Subtasks

Ordered for bottom-up construction. Each task ends with a runnable checkpoint. Do not reorder — the tests and imports chain downward.

- [x] **Task 1 — Extend `keys/models.py` with list-row dataclasses** (AC: #1, #4, #5, #8)
  - [x] 1.1 Add two `@dataclass(frozen=True, slots=True)` classes to `src/comadre/keys/models.py`:
    ```python
    @dataclass(frozen=True, slots=True)
    class CustomerListRow:
        """One row of the `list-customers` result set — immutable display payload."""
        id: str
        name: str
        email: str
        tax_id_kind: TaxIdKind
        key_count: int
        registered_at: str  # ISO 8601 UTC str (pre-formatted from SQLite)
        deleted_at: str | None
        notes: str


    @dataclass(frozen=True, slots=True)
    class ApiKeyListRow:
        """One row of the `list-keys` result set — immutable display payload.

        `customer_name` is joined in so the renderer doesn't need a second
        query per row. `key_hash` is deliberately NOT included — list output
        never exposes the hash.
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
        last_used_at: str | None
    ```
  - [x] 1.2 Keep `registered_at` / `created_at` / `last_used_at` / `paid_until` / `deleted_at` as **str or None** (not `datetime`) — SQLite returns them as TEXT and the renderer emits them as strings. Avoiding the round-trip through `datetime` removes a class of bugs (tz mismatches, fractional-seconds drift) in the hot path of list commands.
  - [x] 1.3 Tests in `tests/test_keys_models.py` — one constructor test per class asserting every field round-trips; verify `frozen=True` (re-assignment raises `dataclasses.FrozenInstanceError`); verify `slots=True` (setting a new attribute raises `AttributeError`).

- [x] **Task 2 — Extend `keys/db.py` with parameterized list helpers** (AC: #1, #2, #3, #5, #6, #7, #9)
  - [x] 2.1 Add `list_customers(conn, *, include_deleted: bool) -> list[CustomerListRow]`:
    - Single SQL with `LEFT JOIN` to count keys per customer:
      ```sql
      SELECT
          c.id, c.name, c.email, c.tax_id_kind, c.notes,
          c.registered_at, c.deleted_at,
          COUNT(k.id) AS key_count
      FROM customer AS c
      LEFT JOIN api_key AS k ON k.customer_id = c.id
      WHERE (? OR c.deleted_at IS NULL)
      GROUP BY c.id
      ORDER BY c.registered_at ASC
      ```
      Bind `include_deleted` as the first `?` parameter (SQLite treats the Python bool as 0/1). This avoids two separate query strings.
    - Return `[CustomerListRow(...)]`. Convert row values directly — `notes or ""` for NULL, `deleted_at` left as str-or-None.
  - [x] 2.2 Add `list_api_keys(conn, *, status, billing_mode, customer_id, paid_until_lte) -> list[ApiKeyListRow]`:
    - Signature: all filter params default to `None`. Each non-None param adds one predicate to a programmatic `WHERE` clause:
      ```python
      predicates: list[str] = []
      params: list[object] = []
      if status is not None:
          predicates.append("k.status = ?")
          params.append(status)
      if billing_mode is not None:
          predicates.append("k.billing_mode = ?")
          params.append(billing_mode)
      if customer_id is not None:
          predicates.append("k.customer_id = ?")
          params.append(customer_id)
      if paid_until_lte is not None:
          predicates.append("(k.paid_until IS NULL OR k.paid_until <= ?)")
          params.append(paid_until_lte)
      where_clause = ("WHERE " + " AND ".join(predicates)) if predicates else ""
      sql = (
          "SELECT k.id, k.customer_id, c.name AS customer_name, "
          "k.key_prefix, k.status, k.billing_mode, k.rate_limit_rpm, "
          "k.price_monthly, k.paid_until, k.created_at, k.last_used_at "
          f"FROM api_key AS k JOIN customer AS c ON c.id = k.customer_id "
          f"{where_clause} "
          "ORDER BY k.created_at ASC"
      )
      ```
      **The only f-string interpolation permitted is for `where_clause` — which is itself assembled from fixed literal `AND`-joined predicate strings containing `?` placeholders only. No operator-supplied string ever lands in the SQL text.** Task 10.6 has the grep regression guard for this exact case.
    - Return `[ApiKeyListRow(...)]`.
  - [x] 2.3 Add `count_first_run(conn) -> bool` — a small helper for AC2/AC7 first-run hint policy:
    ```python
    customers = conn.execute("SELECT COUNT(*) FROM customer").fetchone()[0]
    keys = conn.execute("SELECT COUNT(*) FROM api_key").fetchone()[0]
    return customers == 0 and keys == 0
    ```
    Cheap — both tables are counted in one SQL round-trip each, and the DB is guaranteed small on a first-run path (zero rows by definition). Also add `count_tombstones(conn) -> int`:
    ```python
    row = conn.execute(
        "SELECT COUNT(*) FROM customer WHERE deleted_at IS NOT NULL"
    ).fetchone()
    return int(row[0])
    ```
    Needed by Task 4.2 step 6 to distinguish the "all customers purged" empty state from the "no customers at all" first-run state.
  - [x] 2.4 Tests in `tests/test_keys_db.py` (append — keep Story 1.1/1.2 tests intact):
    - `test_list_customers_returns_rows_sorted_by_registered_at` — seed three customers with staggered `registered_at`; assert the return list matches insertion order.
    - `test_list_customers_counts_keys_per_customer` — seed two customers, issue keys against one; assert `key_count` is 0 / N correctly. Include one customer with a complimentary key, one with manual, one with no keys.
    - `test_list_customers_excludes_tombstones_by_default` — seed customer, `UPDATE customer SET deleted_at = ? WHERE id = ?`, call with `include_deleted=False`; assert the tombstone is absent. Call again with `include_deleted=True`; assert it's present.
    - `test_list_customers_empty_returns_empty_list` — fresh DB; returns `[]`.
    - `test_list_api_keys_no_filters_returns_all_sorted` — seed keys with staggered `created_at`; assert order.
    - `test_list_api_keys_filter_by_status` — parametric `("active",)`, `("suspended",)`, `("revoked",)` covers the Literal set.
    - `test_list_api_keys_filter_by_billing_mode` — parametric `("manual",)`, `("complimentary",)`.
    - `test_list_api_keys_filter_by_customer` — two customers, assert only the matched customer's keys return.
    - `test_list_api_keys_filter_by_paid_until_lte_includes_nulls` — seed three keys: (a) `paid_until=NULL`, (b) `paid_until='2026-04-01'`, (c) `paid_until='2026-05-01'`; query with `paid_until_lte='2026-04-15'`; assert (a) and (b) return, (c) excluded. This test locks in the `IS NULL OR <= ?` semantics.
    - `test_list_api_keys_filter_composition` — combine `--status active --billing-mode manual --paid-until-lte today` in one call; assert the AND-composition works (seed one key that matches all three, one that fails each in turn).
    - `test_list_api_keys_joined_customer_name_is_correct` — assert the JOIN populates `customer_name`.
    - `test_count_first_run_true_on_empty_db` / `test_count_first_run_false_when_customer_exists` / `test_count_first_run_false_when_tombstoned_customer_exists` (even after purge, DB has been used).
    - `test_count_tombstones_returns_zero_on_fresh_db` / `test_count_tombstones_counts_only_tombstoned_rows` (seed two customers, tombstone one; assert returns 1).
    - **Regression guard**: `test_list_commands_do_not_write` — snapshot `SELECT COUNT(*) FROM customer`, `api_key`, `audit_log` before and after every `list_customers` / `list_api_keys` call; all three deltas are zero.

- [x] **Task 3 — Extend `keys/cli/output.py` with `StatusTable` + list renderers** (AC: #1, #5, #7, #10)
  - [x] 3.1 Add a small pure helper for the status cell:
    ```python
    def _status_label(status: CustomerStatus, billing_mode: BillingMode) -> tuple[str, str]:
        """Return (text, rich_color) for UX-DR8 — text-first, color-as-accelerator.

        `complimentary` blue supersedes `active` green when billing_mode is
        complimentary (the badge is a semantic signal, not a raw column value).
        """
        if billing_mode == "complimentary":
            return ("complimentary", "blue")
        if status == "active":
            return ("active", "green")
        if status == "suspended":
            return ("suspended", "yellow")
        if status == "revoked":
            return ("revoked", "red")
        return (status, "")  # defensive: unknown literal renders with no color
    ```
    Unit-test this pure helper exhaustively (five cases) — it encapsulates the UX-DR8 semantic.
  - [x] 3.2 Add `render_customer_list(title: str, rows: list[CustomerListRow]) -> None`:
    - Assumes `rows` is non-empty (caller handles empty-state via `render_empty_state`).
    - Build a `rich.Table` with `title=title`, columns `Customer ID`, `Name`, `Email`, `Keys` (right-aligned `justify="right"`), `Registered` (truncate ISO timestamp to date — first 10 chars). Append rows; print via `stdout_console()`. Emit `<N> customers found.` line after.
    - Empty-state messaging is the caller's responsibility: the command body chooses between first-run hint, all-purged hint, and generic "no match" before deciding whether to call `render_customer_list` vs `render_empty_state`. Keeping the message policy in the command body makes the three distinct cases visible at the call site (AC2, AC3, AC7).
  - [x] 3.3 Add `render_key_list(title: str, rows: list[ApiKeyListRow]) -> None`:
    - On empty: caller invokes `render_empty_state(lines)` instead (keeps `render_key_list` focused on the populated path).
    - On non-empty: build a `rich.Table` with `title=title`, six columns per AC5. Status cell: `Text(text, style=color)` so the badge keeps its label when `NO_COLOR` strips the color. RPM: f"{rpm}/min"; Price: per billing-mode rule (AC5). Paid Until: ISO-date slice of `paid_until` or `"\u2014"` em-dash for NULL / complimentary. Emit `<N> keys found.` after.
  - [x] 3.4 Add `render_json(payload: list[dict[str, object]]) -> None` — emits via `stdout_console().print_json(data=payload)`. Centralizing this avoids two call sites duplicating the serialization.
  - [x] 3.5 Add `render_empty_state(lines: list[str]) -> None` — each line via `render_confirmation(line)` (plain stdout, no panel, exit 0 responsibility with the caller).
  - [x] 3.6 Tests in `tests/test_keys_output.py` (append):
    - `test_status_label_active_manual` / `test_status_label_active_complimentary` / `test_status_label_suspended` / `test_status_label_revoked` — assert the 4-color mapping exactly.
    - `test_render_customer_list_populated` — capture stdout via the `_reset_for_tests()` + `StringIO` fixture; assert table title, column headers, row values, `N customers found.` trailer. Width 120, `no_color=True`.
    - `test_render_customer_list_first_run_empty` — `render_customer_list("Customers", [], first_run=True)` emits the exact two-line hint string (AC2).
    - `test_render_customer_list_subsequent_empty` — `first_run=False` emits only the one-line informational sentence (pass via caller).
    - `test_render_key_list_populated_has_color_labels` — seed one row per status/billing-mode combo; assert each label word appears in the captured text (`active`, `suspended`, `revoked`, `complimentary`). With `no_color=True` the labels still show; the tests don't need to inspect ANSI codes (that's the NO_COLOR regression — AC10 / Task 8.5).
    - `test_render_key_list_price_formatting` — manual `price=149.0` → `R$ 149,00/month`; manual `price=1234.56` → `R$ 1.234,56/month`; complimentary → `R$ 0,00`.
    - `test_render_key_list_paid_until_emdash_for_null` — paid_until None → U+2014 em-dash; paid_until `2026-06-05` → ISO date string.
    - `test_render_json_matches_payload` — pass a fixture list; assert `json.loads(stdout)` matches the input shape.

- [x] **Task 4 — `list-customers` command** (AC: #1, #2, #3, #4, #9, #10)
  - [x] 4.1 Extend `src/comadre/keys/cli/commands/customers.py` with:
    ```python
    @app.command("list-customers")
    def list_customers_cmd(
        deleted: bool = typer.Option(
            False,
            "--deleted",
            help="Include purged customers (tombstoned by LGPD hard-delete).",
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
        """List registered customers with key counts and registration dates."""
        ...
    ```
  - [x] 4.2 Command body:
    1. Validate `--format`: must be `"table"` or `"json"`. Anything else → exit 2 usage error, title `Usage error: --format must be table or json`.
    2. Load settings (try/except `ValidationError` + `OSError` mapped to exit 6 — reuse the `_errors.py` helpers `first_error_msg` / `is_missing_encryption_key` as `customers.py` already does). `KEY_REGISTRY_ENCRYPTION_KEY` is still required (same Story 1.2 AC7 rationale — the CLI needs it because 1.1 encrypted rows with it, even though listings do not decrypt).
    3. Open DB via `get_connection()` inside a try/except `sqlite3.Error` → exit 5. Run `_apply_migrations(conn)` defensively (idempotent).
    4. Read `rows = list_customers(conn, include_deleted=deleted)`. Read `first_run = count_first_run(conn)` BEFORE closing the connection.
    5. Close the connection inside `finally` + `contextlib.suppress(sqlite3.Error)` (Story 1.2 pattern).
    6. Branch on `--format`:
       - `json`: `render_json([_customer_row_to_json(r) for r in rows])`. The row-to-json helper lives in this module (or in a small shared `_json.py`; favor colocation in the command module for MVP). **No hint text in JSON mode — ever.** Empty result serializes as `[]`.
       - `table`: determine title (`"Customers"` for default, `"Customers (including purged)"` for `--deleted`).
         - If `rows` is non-empty → `render_customer_list(title, rows)`.
         - If `rows` is empty and `first_run` is True (AC2) → `render_empty_state(["No customers registered yet.", 'To get started: comadre-keys create-customer --name "Name" --email "email@example.com" --cpf "000.000.000-00"'])`.
         - If `rows` is empty, `first_run` is False, `deleted` is False, and `count_tombstones(conn) > 0` → `render_empty_state(["No active customers. Run 'comadre-keys list-customers --deleted' to see purged records."])` (AC2 all-purged variant). This requires a small `count_tombstones(conn) -> int` helper in `db.py` — add it in Task 2.3 alongside `count_first_run`.
         - Otherwise (`rows` empty, not first-run, not all-purged) → `render_empty_state(["No customers found."])`.
    7. Structured INFO log: `_logger.info("Listed customers | count=%d | include_deleted=%s", len(rows), deleted)`. **Never log names, emails, or IDs — count + flag only.**
    8. Exit 0 implicit.
  - [x] 4.3 Register — no change needed in `app.py`; the existing `app.registered_commands.extend(customers_app.registered_commands)` pulls the new command in. Verify `uv run comadre-keys --help` lists `list-customers`.

- [x] **Task 5 — `list-keys` command** (AC: #5, #6, #7, #8, #9, #10)
  - [x] 5.1 Extend `src/comadre/keys/cli/commands/keys.py` with:
    ```python
    _VALID_STATUSES = ("active", "suspended", "revoked")
    _VALID_FORMATS = ("table", "json")


    @app.command("list-keys")
    def list_keys_cmd(
        status: str | None = typer.Option(None, "--status", help="..."),
        billing_mode: str | None = typer.Option(None, "--billing-mode", help="..."),
        customer: str | None = typer.Option(None, "--customer", help="..."),
        paid_until_lte: str | None = typer.Option(None, "--paid-until-lte", help="..."),
        format: str = typer.Option("table", "--format", help="..."),
    ) -> None:
        """List API keys with filters and color-coded status."""
        ...
    ```
  - [x] 5.2 Command body:
    1. Validate each filter literal:
       - `status` not in `(None,) + _VALID_STATUSES` → exit 2, title `Usage error: --status must be active, suspended, or revoked`.
       - `billing_mode` not in `(None, "manual", "complimentary")` → exit 2, title `Usage error: --billing-mode must be manual or complimentary`. Reject `"automated"` explicitly.
       - `format` not in `_VALID_FORMATS` → exit 2.
       - `paid_until_lte`:
         - `None` → no filter.
         - `"today"` → resolve via `_resolve_today_in_tz(ZoneInfo(settings.billing_timezone)).isoformat()` (Story 1.2 seam — tests freeze this).
         - Else → try `date.fromisoformat(paid_until_lte)`; on `ValueError`, exit 2, title `Usage error: --paid-until-lte must be an ISO date (YYYY-MM-DD) or 'today'`.
       - `customer`: no early validation — passed through to the query. An unmatched id yields `"No keys found for customer <id>."` (AC7).
    2. Load settings (same try/except mapping as Task 4 step 2). Resolve `billing_tz = ZoneInfo(settings.billing_timezone)` with the same `ZoneInfoNotFoundError | ValueError` → exit 6 mapping as Story 1.2.
    3. Open DB + migrations + run `rows = list_api_keys(conn, status=..., billing_mode=..., customer_id=customer, paid_until_lte=resolved_date)`.
    4. Compute table title with the precedence rule (AC6): `--customer` > `--billing-mode` > `--status` > `--paid-until-lte`. Implementation: a small helper `_resolve_title(...)` with a table of (filter, template) tuples. Default title (no filters): `"Keys"`.
    5. If `--customer` is set and `rows` is empty: look up the customer name via `get_customer(conn, customer)` (Story 1.2 helper). If found, title becomes `"Keys for <name>"`; if not, title stays `"Keys for <customer_id>"`. The empty-result message is `"No keys found for customer <customer_id>."` (AC7).
    6. Branch on `--format`:
       - `json`: `render_json([_key_row_to_json(r) for r in rows])`.
       - `table`: if `rows` empty → `render_empty_state(lines)` with the right hint (first-run vs subsequent; reuse `count_first_run(conn)`). Otherwise `render_key_list(title, rows)`.
    7. Close connection (try/finally + suppress).
    8. Log: `_logger.info("Listed keys | count=%d | status=%s | billing_mode=%s | customer=%s | paid_until_lte=%s", len(rows), status, billing_mode, customer, resolved_date)`. **Customer id may appear in the log** (opaque ULID, not personal data per the FR37 threat model).
    9. Exit 0 implicit.

- [x] **Task 6 — JSON serialization helpers** (AC: #4, #8)
  - [x] 6.1 In `customers.py` add `_customer_row_to_json(row: CustomerListRow) -> dict[str, object]`. Literal dict construction, exact key order matching AC4's schema. `deleted_at` is `row.deleted_at` (None or the raw ISO str).
  - [x] 6.2 In `keys.py` add `_key_row_to_json(row: ApiKeyListRow) -> dict[str, object]`. Exact key order per AC8. `price_monthly` stays a float.
  - [x] 6.3 Keep the helpers in their owning command modules (not a shared utility). The JSON shape is specific to each row type and sharing would force a `__tojson__` protocol for no gain at MVP scale.

- [x] **Task 7 — Integration tests: `list-customers`** (AC: #1–#4, #9, #10)
  - [x] 7.1 Create `tests/test_keys_cli_list_customers.py`. Reuse the three autouse fixtures from `test_keys_cli.py`: `_clear_settings_cache`, `_reset_consoles_to_buffers`, and the `env` fixture. Copy the `_buffers()` helper. Add a `_seed_customer(env)` helper (already present in `test_keys_cli_issue.py` — copy it verbatim; don't introduce a shared conftest helper unless three+ files need it).
  - [x] 7.2 Tests:
    - `test_empty_db_prints_first_run_hint` — fresh DB, no invocations. Run `list-customers`. Assert stdout contains the two-line hint verbatim. Exit 0. No DB writes (count before/after).
    - `test_populated_table_rows` — seed three customers via three `create-customer` invocations (use CliRunner + `_seed_customer`), then issue two keys against customer 1, one key against customer 2, zero keys against customer 3. Run `list-customers`. Assert the table contains all three customer IDs, names, emails, the correct key counts (2, 1, 0), and ISO dates. Assert the `<N> customers found.` trailer (N=3).
    - `test_deleted_flag_includes_tombstones` — seed two customers, mark one tombstoned via direct `UPDATE customer SET deleted_at = '2026-04-17T12:00:00Z' WHERE id = ?`. Run `list-customers` → one row. Run `list-customers --deleted` → two rows, title `Customers (including purged)`.
    - `test_default_excludes_tombstones` — same setup; assert the tombstoned id is absent from the default output.
    - `test_all_tombstoned_shows_purged_hint` — seed then tombstone all; `list-customers` prints the "No active customers. Run ..." sentence.
    - `test_format_json_empty_is_empty_array` — fresh DB + `--format json` → `stdout == "[]\n"` (or `"[]"` — assert `json.loads(stdout) == []`). No hint text in JSON mode.
    - `test_format_json_populated_shape` — seed two customers. Run with `--format json`. Assert `json.loads(stdout)` is a list of two dicts; each dict has exactly the AC4 keys; `tax_id_encrypted` is NOT present; `deleted_at` is None; `key_count` is correct.
    - `test_format_json_deleted_flag` — seed one tombstoned + one active. `--deleted --format json` → two objects; one with `deleted_at` non-null.
    - `test_format_invalid_exits_2` — `list-customers --format yaml` → exit 2, stderr title `Usage error: --format must be table or json`.
    - `test_read_only_no_audit_rows` — snapshot `SELECT COUNT(*) FROM audit_log`; run `list-customers` + `list-customers --deleted` + `list-customers --format json`; assert audit count unchanged. Also assert `customer` and `api_key` counts unchanged.
    - `test_help_lists_realistic_examples` — `list-customers --help` → stdout contains `--deleted`, `--format json`, the example string from AC10. DB file does NOT exist (`not (tmp_path / "registry.db").exists()`).
    - `test_no_color_has_no_ansi_escapes` — set `NO_COLOR=1` via `monkeypatch.setenv`, seed one row, run `list-customers`; assert `"\x1b[" not in stdout`.

- [x] **Task 8 — Integration tests: `list-keys`** (AC: #5–#10)
  - [x] 8.1 Create `tests/test_keys_cli_list_keys.py`. Same fixtures as Task 7. Helper `_seed_key(env, customer_id, *, rpm=60, price=149.0, billing_mode="manual")` that runs the full `issue-key` command end-to-end and returns the DB row via a direct SELECT (needed to check post-conditions). Optional direct-SQL seeding helper `_raw_insert_key(db_path, **kw)` for stories that need a specific status/billing combination without going through `issue-key` (which always inserts `status=active`). Use the direct helper ONLY to set `status='suspended'` / `status='revoked'` / `paid_until='YYYY-MM-DD'` — these states are produced by Stories 1.6 / 3.1, not yet implemented, so integration tests need an end-run.
  - [x] 8.2 Tests:
    - `test_empty_db_prints_first_run_hint_for_keys` — fresh DB. `list-keys` → stdout has the two-line `No keys issued yet.` hint. Exit 0.
    - `test_populated_all_statuses_visible` — seed four keys: active-manual, active-complimentary (via `issue-key --billing-mode complimentary`), suspended-manual (direct SQL), revoked-manual (direct SQL). Run `list-keys`. Assert stdout contains `active`, `suspended`, `revoked`, `complimentary` as status labels. Trailer `4 keys found.` (or `1 keys found.` pluralization policy — match whichever Task 3.3 lands).
    - `test_filter_by_status` — parametric `("active", 2)`, `("suspended", 1)`, `("revoked", 1)` asserting row counts. Assert title matches `"Active Keys"` etc.
    - `test_filter_by_billing_mode` — parametric `("manual", 3)`, `("complimentary", 1)`.
    - `test_filter_by_customer` — seed keys for two customers; `--customer <cust-1>` returns only customer 1's keys; title `"Keys for <name>"`.
    - `test_filter_by_customer_not_found` — `--customer cust_01nonexistent00000000000000` → exit 0, stdout `No keys found for customer cust_01nonexistent00000000000000.`, no error panel.
    - `test_filter_by_paid_until_lte_iso_date` — seed three keys with paid_until: None, `'2026-04-01'`, `'2026-05-01'` (direct SQL). `--paid-until-lte 2026-04-15` → NULL + `2026-04-01` returned (2 rows), `2026-05-01` excluded. Lock in the `IS NULL OR <= ?` semantics.
    - `test_filter_by_paid_until_lte_today` — freeze today via `_freeze_today(monkeypatch, date(2026, 4, 15))` (Story 1.2 pattern). `--paid-until-lte today` resolves to `2026-04-15` and matches the same rows as above.
    - `test_filter_by_paid_until_lte_invalid_format` — `--paid-until-lte 17-04-2026` → exit 2, stderr title `Usage error: --paid-until-lte must be an ISO date (YYYY-MM-DD) or 'today'`.
    - `test_filter_composition` — `--status active --billing-mode manual --paid-until-lte today` (Journey 2 canonical). Assert the AND composition returns exactly the matching rows.
    - `test_invalid_status_rejected` — `--status weird` → exit 2.
    - `test_invalid_billing_mode_rejected` — `--billing-mode weird` → exit 2. Also `--billing-mode automated` → exit 2 (explicit MVP-doesn't-support-automated assertion).
    - `test_format_json_populated_shape` — seed three keys. `--format json` → three JSON objects; each has exactly the AC8 keys; `key_hash` is NOT present; `price_monthly` is a number; `paid_until` is null or ISO date str.
    - `test_format_json_with_filter` — `--status suspended --format json` → array of only suspended rows.
    - `test_format_json_empty_is_empty_array` — fresh DB + `--format json` → `json.loads(stdout) == []`.
    - `test_subsequent_empty_no_hint` — seed one customer (no keys). `list-keys --status suspended` → stdout `"No suspended keys found."` (no hint because not first-run — keys table is empty but customer table isn't). Wait — Task 2.3's `count_first_run` requires BOTH tables empty for first-run; so this test actually shows the first-run hint is suppressed by the customer row. Correct: the test asserts the one-line informational message, not the hint.
    - `test_no_color_has_no_ansi_escapes` — `NO_COLOR=1` + seed + run; assert no ANSI.
    - `test_help_lists_realistic_examples` — `list-keys --help` contains each `--<flag>` example string from AC10. DB file does NOT exist afterwards.
    - `test_read_only_no_writes` — snapshot all three table counts; run each of the above variants; counts unchanged.
    - `test_customer_id_in_log_not_in_panel` — log-capture via `caplog`, run `list-keys`; assert `Listed keys | count=` appears in log, and that customer names/emails do NOT appear in any log record (the `count=` line is the only INFO emitted).

- [x] **Task 9 — Manual verification**
  - [x] 9.1 **Human eyeball check at 80 cols.** Resize the dev terminal to 80 columns. Run `comadre-keys list-keys` on a DB with ≥ 5 keys covering all four statuses. Confirm: (a) all six columns visible without horizontal scrolling; (b) status badges readable (color separable from background on both light and dark themes — test both if available); (c) price column right-aligned; (d) prefix column left-aligned. Record the terminal emulator(s) tested in the Dev Agent Record.
  - [x] 9.2 **NO_COLOR sanity.** `NO_COLOR=1 uv run comadre-keys list-keys | cat -v`. Confirm zero `^[` escape sequences. Labels still readable (`active`, `suspended`, `revoked`, `complimentary`) via plain text.
  - [x] 9.3 **JSON piping sanity.** `uv run comadre-keys list-keys --format json | jq '.[] | {prefix, status, price_monthly}'`. Confirm `jq` parses cleanly. Pipe errors (e.g., a stderr warning) don't contaminate stdout.
  - [x] 9.4 **Log sanitization check.** Tail the structured log while running each command. Confirm only `count=`, `status=`, `billing_mode=`, `customer=`, `paid_until_lte=` fields appear — no name, email, tax-id, key plaintext, or hash.
  - [x] 9.5 **First-run hint copy check.** On a fresh DB (`rm data/keys/registry.db`), run `list-customers`. Confirm the two-line hint matches the exact text in AC2 (including the em-dash, quotes, and CLI example). Repeat for `list-keys` on a DB with zero keys.

- [x] **Task 10 — Quality gates**
  - [x] 10.1 `uv run ruff check . && uv run ruff format --check .` — zero warnings on all new/modified files.
  - [x] 10.2 `uv run mypy src/comadre/keys/` — zero errors in strict mode.
  - [x] 10.3 `uv run pytest` — all new tests pass, existing 629 tests (as of Story 1.2) still pass. Story 1.3 adds roughly 40–60 tests; final count should be ~670–690. **No `@pytest.mark.slow` markers** — all tests mocked or in-memory SQLite.
  - [x] 10.4 `uv run pre-commit run --all-files` — all hooks pass.
  - [x] 10.5 Do NOT update `_bmad-output/implementation-artifacts/sprint-status.yaml` — that transition happens when the reviewer moves the story to `done`.
  - [x] 10.6 **Non-regression guard rails for Epic 4.5 CI (early compliance).** Grep the new code:
    - `rg 'HTTPException' src/comadre/keys/cli/commands/` — empty (FR51).
    - Write a one-off shell check that confirms no f-string SQL in the new list helpers: `rg 'f\"SELECT|f\"INSERT|f\"UPDATE|f\"DELETE' src/comadre/keys/db.py` must return **only** the `where_clause` f-string from Task 2.2 (allowlisted by context). Verify that string contains no `{` placeholder referencing operator input — only the concatenated literal predicate list.
    - `rg '\bprint\(' src/comadre/keys/` — empty.
    - `rg 'os\.environ' src/comadre/keys/` — empty.
  - [x] 10.7 Performance sanity (NFR4). On a fresh DB seeded with 1,000 customers (use a `conftest` helper if desirable, OR run a quick `scripts/seed_registry.py` once and measure manually), `time uv run comadre-keys list-customers | head -20` completes in well under 200 ms. This is not a unit test (flaky on CI) — it's a Task 9-level manual sanity check. Record the elapsed time in the Dev Agent Record.

## Dev Notes

### Architecture invariants (from `_bmad-output/planning-artifacts/architecture.md`)

- **Import graph downward-only.** Story 1.3 extends the graph within existing boundaries: `keys/db.py` gains two list helpers (still below `cli/`); `cli/commands/customers.py` and `cli/commands/keys.py` gain new subcommands (CLI layer — already the top of the import graph). No module-order changes. **MUST NOT import from `keys.auth` or `keys.cache`** (they don't exist). [Source: architecture.md:L366-L372]
- **CLI / runtime separation.** Do NOT touch `src/comadre/main.py`, `api.py`, `rate_limit.py`, `service.py`, `config.py`, `exceptions.py`. Preserves the 1.6.2 public contract byte-for-byte. [Source: architecture.md:L519-L521]
- **No raw HTTPException.** All CLI errors flow through `render_error` + `typer.Exit`. Tasks 4.2 / 5.2 exit-code maps follow UX-DR10 exactly.
- **No `print()`.** All output via `render_confirmation` / `render_customer_list` / `render_key_list` / `render_json` / `render_error`. Structured logging via `get_logger("keys.cli")`. [Source: project-context.md §Python Language Rules]
- **No raw `os.environ`.** Only `get_settings()`. [Source: project-context.md §Python Language Rules]
- **Parameterized SQL only.** Architecture §Enforcement Guidelines. The `where_clause` f-string in Task 2.2 is the **only** permitted f-string in SQL construction, and it exclusively concatenates literal `AND`-joined predicate strings containing `?` placeholders. No operator-supplied string is ever interpolated into SQL text. [Source: architecture.md:L376-L383, §Enforcement Guidelines]
- **CLI read-only.** List commands do not open `with conn:` blocks and do not call `log_event`. The absence of the transaction boundary is the contract's read-only signal. [Source: architecture.md §Transaction Scope, L465-L469]

### Data contracts (from `prd.md` §Data Model L845-L888 and architecture.md §Naming Patterns)

- `customer.registered_at` / `customer.deleted_at` / `api_key.created_at` / `api_key.last_used_at` / `api_key.paid_until` are all TEXT columns containing ISO 8601 UTC strings (no microseconds, Z suffix) or NULL. Story 1.3's list rows propagate them **as-is**. The renderer formats them for display (truncate to `YYYY-MM-DD` for `Registered` and `Paid Until` columns).
- `api_key.billing_mode IN ('manual', 'complimentary', 'automated')`. Story 1.3 exposes `manual` and `complimentary` filters; `automated` is reserved (PSP adapters in 2.1+) and the `--billing-mode automated` filter is explicitly rejected.
- `api_key.status IN ('active', 'suspended', 'revoked')`.
- `customer.tax_id_encrypted BLOB` — **never** surfaced in list output. Decryption is Story 1.4 / 4.1 territory.

### Library version gotchas

- **`rich.Console.print_json(data=...)`** — accepts a Python object, serializes with `json.dumps(..., indent=2, sort_keys=False)` by default. Sort-keys **must be False** to preserve the insertion order of our hand-built dict literals (tests assert key order). If the default ever changes, pin `sort_keys=False` explicitly. Do NOT pass `indent=None` to compact-mode — the two-space indent is the readable default and downstream `jq` consumers don't care.
- **`rich.Text(text, style="color")`** vs. `f"[color]{text}[/color]"` markup — both work, but `Text` survives `no_color=True` rendering (strips the style, keeps the text) with zero ambiguity. The tests assert on text labels only; use whichever the Task 3 author prefers.
- **`Console.print_json(data=[])`** emits `[]\n` on SOME rich versions (3.7.1+) and `[]` on older ones. Tests should use `json.loads(stdout)` and compare to `[]` — not raw string match.
- **`typer.Option(... "--paid-until-lte", ...)`** — Typer turns the `--paid-until-lte` flag into a Python parameter named `paid_until_lte` (the dash-to-underscore is automatic). Do NOT manually remap.
- **`date.fromisoformat("2026-04-15")`** (stdlib 3.7+) — accepts `YYYY-MM-DD` only. `"today"` is not valid; hence the explicit `if value == "today": ...` branch before parsing.
- **`ZoneInfo` exception handling** — Story 1.2's `_resolve_today_in_tz` seam does NOT re-resolve the tz (it accepts a `ZoneInfo` and returns `date`). Tests freeze it with `lambda _tz: date(2026, 4, 15)`. Reuse the seam for `list-keys --paid-until-lte today` — new code should call `_resolve_today_in_tz(billing_tz)` when `paid_until_lte == "today"`.

### Previous story intelligence (Stories 1.1, 1.2)

- **CliRunner Click 8.2+ pattern.** `CliRunner()` with no `mix_stderr=False` (that kwarg is gone). Wire stdout/stderr to `StringIO` buffers via `_reset_for_tests()` + fixture-assigned `output_mod._stdout_console` / `_stderr_console`. Copy the autouse fixture from `test_keys_cli_issue.py` verbatim.
- **Audit blocklist raises `ValueError`, not `AssertionError`.** Story 1.3 writes zero audit rows, so this doesn't bite directly — but the test helper `_raw_insert_key` (Task 8.1) must NOT touch `audit_log` (it bypasses `insert_api_key` entirely and thus skips the audit row). Tests asserting audit-count deltas of zero are robust to this.
- **`CliRunner` help-only invocations do not open the DB.** Regression: assert `not (tmp_path / "registry.db").exists()` after `--help` runs. Story 1.1's `test_help_lists_realistic_examples` codifies this; Story 1.3's equivalents (Tasks 7.2 / 8.2 `_help_lists_realistic_examples`) must do the same.
- **Customer lookup BEFORE pydantic validation.** Story 1.2's AC3 lesson: syntactically invalid customer IDs must yield exit 3 "not found" rather than exit 2 "usage error". `list-keys --customer <garbage>` applies the same rule — but here the resolution is simpler: we don't validate the `--customer` flag at all; we let the SQL JOIN miss return zero rows and present the "No keys found" message. **No exit 3 for `--customer` in list-keys** — empty results are not errors (UX-DR12).
- **pt-BR `_format_brl` helper already exists** in `src/comadre/keys/cli/output.py`. Import + reuse — do NOT duplicate. Story 1.2 landed the pt-BR format; Story 1.3's `render_key_list` price cell calls it directly.
- **`get_customer(conn, customer_id)` already exists** in `src/comadre/keys/db.py` (Story 1.2). Reuse for the title-resolution path in Task 5.2 step 5.
- **Shared `_errors.py` helpers** (`first_error_msg`, `is_missing_encryption_key`) — import from `comadre.keys.cli._errors`, never re-define (Story 1.2 Task 7 enforcement).

### Git intelligence

Last 5 commits on master (as of 2026-04-17 22:00 local time):
- `612d952 feat(keys): land story 1.2 — comadre-keys issue-key with one-shot KeyPanel` — the direct parent. Story 1.3 builds on this commit's working tree.
- `50cdada feat(keys): land story 1.1 impl, draft story 1.2, validate-docbr migration` — foundation.
- `f07e662 docs(bmad): land 2.0.0 architecture, epics, readiness report, and sprint plan` — the planning context Story 1.3 is built from.
- `05e0b59 feat(voices): add pm_influencer_01 voice profile` / `36697a1 docs(bmad): add UX design specification for 2.0.0 monetization CLI` — unrelated / already applied.

Working tree should be clean at story start (Story 1.2 is `done`). The only expected modifications before Story 1.3 lands: this story file and `sprint-status.yaml` (both committed separately by the create-story workflow).

### Deferred-work items relevant to this story

From `_bmad-output/implementation-artifacts/deferred-work.md`:

- **`comadre-keys` CLI still requires TTS-side config (`api_key`, `domain`).** Story 1.3 inherits this limitation — the CLI will refuse to run without `API_KEY` set in `.env`. On the VPS this is not a problem (the TTS config is already present); on a greenfield dev workstation, a `.env` with just `KEY_REGISTRY_ENCRYPTION_KEY` and `API_KEY=test` is sufficient. The split of `Settings` into `RuntimeSettings` + `RegistrySettings` is Epic 2 work, not Story 1.3.
- **`--rpm` unbounded.** Not relevant to this story — list-keys reads `rate_limit_rpm` but does not validate or mutate it.
- **`price_monthly` as SQLite REAL (float precision).** Story 1.3 displays it via `_format_brl`; float drift would show up as `R$ 148,99999` instead of `R$ 149,00`. `_format_brl` uses `f"{amount:,.2f}"` which rounds at two decimals — not a storage fix, but a display mask. **If any test fails on `R$ 148,99` vs `R$ 149,00` because of a seeded fixture's `price=149.0 - 0.01`, the test is wrong, not the formatter.**

### UX invariants reproduced from `ux-design-specification.md`

- **UX-DR2 StatusTable** (`ux:L746-L766`): color-coded status cells, invariant column order (identifier → name → status → billing → dates), max 7 columns at 80-col, row count below table, title reflects filter. Story 1.3 implements the canonical form for `list-keys`; `list-customers` is a StatusTable-without-status-column sibling.
- **UX-DR8 Four-color palette** (`ux:L382-L403`): green / yellow / red / blue, paired with text label, no background colors, no bold on badges. `complimentary` blue supersedes `active` green when `billing_mode='complimentary'` — the badge reflects the operator-meaningful concept, not the raw column.
- **UX-DR9 Shared console** (`ux:L250-L256`): all output through the singleton `stdout_console()` / `stderr_console()`. Do NOT instantiate ad-hoc `Console()` objects — width detection and `NO_COLOR` must be consistent.
- **UX-DR12 Empty results are not errors** (`ux:L1017-L1029`): informational text on stdout, exit code 0. No red error panel.
- **UX-DR13 First-run hint** (`ux:L1032-L1041`): the create-customer / issue-key usage line appears on the first empty state; subsequent empty states omit the hint. Task 2.3's `count_first_run` helper is the canonical detector.
- **UX-DR15 Realistic `--help` examples** (`ux:L995-L1013`): every `--flag` help string includes a real-looking example. AC10 enumerates the expected strings verbatim.
- **UX-DR16 Terminal width adaptation** (`ux:L1068-L1081`): 80-col minimum; narrower truncates rightmost columns; status and identifier columns always visible. `rich` handles the adaptation automatically — no manual breakpoint logic.
- **Exit codes (UX-DR10, `ux:L1046-L1056`):** 0 success, 2 usage, 5 database, 6 config/permission. No 3 (not-found) in list commands — empty filter results are not errors.

### Scope guards (things NOT to do in this story)

- **Do NOT add `show <prefix|id>` or `--audit-tail`.** Those are Story 1.4. Even if the dev agent sees a tempting code reuse opportunity (the `ApiKeyListRow` + `CustomerListRow` shape is close to what `show` needs), DON'T pre-implement the detail panel here — it owns its own AC set and will share `_status_label` but needs a different render path.
- **Do NOT decrypt tax IDs.** `customer.tax_id_encrypted` stays encrypted in every output path this story adds. `list-customers` shows `tax_id_kind` (`cpf` / `cnpj`) but never the decrypted value.
- **Do NOT add `--format yaml`.** YAML is for Story 4.1's `export-customer --format yaml` (LGPD data-subject response). List commands support only `table` and `json`.
- **Do NOT add the `--paid-until-gte` / `--paid-until` filter.** Only `--paid-until-lte` is in the PRD CLI spec. Adding its inverse is scope creep.
- **Do NOT add shell tab-completion for filter values.** Typer's built-in `--install-completion` handles top-level commands; per-flag dynamic completion (e.g., tab-complete status values) is nice-to-have, post-MVP.
- **Do NOT cache list results.** These are direct SQLite queries on a small table — NFR4's 200 ms target is met by the existing indexes (`idx_api_key_customer`, `idx_api_key_sweep`) plus the default `PRIMARY KEY` scan on `customer`.
- **Do NOT touch `.env.example`.** Story 1.1 already added the monetization env vars. Story 1.3 uses `BILLING_TIMEZONE` (for `--paid-until-lte today` resolution) which is already declared.
- **Do NOT add a new migration file.** The schema is unchanged. `v001_initial.sql` already has the indexes we need.
- **Do NOT add request-stat counters.** The `Last 24h stats` section in PRD Journey 5 is Story 2.3 (`show --audit-tail` plus in-memory counters). Story 1.3's `list-keys` carries DB columns only.

### Enumeration resistance & log sanitization (FR37, NFR15, NFR16)

- The plaintext key never appears in list output — we only store `key_prefix` (8 chars). Safe.
- `key_hash` never appears in list output (AC8 explicit). Safe.
- Customer `email` appears in `list-customers` output (both table and JSON). This is operator-facing, not customer-facing — the operator already knows their customers' emails. **But** email must not appear in INFO-level structured logs (FR37). Task 4.2 step 7 log format: `count=%d | include_deleted=%s` — safe. Task 5.2 step 8: `count | status | billing_mode | customer | paid_until_lte` — also safe (customer id is opaque ULID).
- Tax-ID values (decrypted) **never** appear — this story never touches the ciphertext other than to not surface it.
- `Authorization` header values are never in play (no HTTP path in this story).

### Project Structure Notes

- **New files (4):** `tests/test_keys_cli_list_customers.py`, `tests/test_keys_cli_list_keys.py`. (Only two new test files; Tasks 2.4 / 3.6 append to existing `test_keys_db.py` and `test_keys_output.py`.)
- **Modified existing files (4):** `src/comadre/keys/models.py` (+2 dataclasses), `src/comadre/keys/db.py` (+3 functions: `list_customers`, `list_api_keys`, `count_first_run`), `src/comadre/keys/cli/output.py` (+`_status_label`, `render_customer_list`, `render_key_list`, `render_json`, `render_empty_state`), `src/comadre/keys/cli/commands/customers.py` (+`list-customers` command + JSON helper), `src/comadre/keys/cli/commands/keys.py` (+`list-keys` command + JSON helper).
- **No changes to existing runtime files** (`api.py`, `main.py`, `rate_limit.py`, `service.py`, `config.py`, `exceptions.py`). Preserves the 1.6.2 public contract.
- All placements per architecture.md §Module Organization (L327-L350). No deviations.

### Testing Standards

- All tests mocked by default; no real models, no `@pytest.mark.slow`.
- Use `CliRunner` from `typer.testing` for CLI tests — synchronous, same as Stories 1.1 / 1.2.
- Use `tmp_path` for DB files. In-memory SQLite (`sqlite3.connect(":memory:")`) is fine for pure SQL-shape tests in `test_keys_db.py` (Task 2.4), but NOT for the `get_connection()` wrapper (it chmod's the file, which needs a real path).
- Reuse Story 1.1's `_clear_settings_cache` autouse from `tests/conftest.py`.
- Target coverage: 90%+ on the new code (`list_customers`, `list_api_keys`, `count_first_run`, `_status_label`, `render_customer_list`, `render_key_list`, both new CLI commands) per architecture §Testing Framework.
- Autouse fixture `_reset_consoles_to_buffers` — copy the exact version from `test_keys_cli_issue.py:L38-L50`.
- `width=120` in the test console — matches Story 1.1/1.2. At this width the full `list-keys` row fits without rich truncation, so assertions on cell text are reliable.

### References

- [Source: `_bmad-output/planning-artifacts/epics.md#Story-1.3-Customer-Key-Listing` (L355-L396)] — AC source text.
- [Source: `_bmad-output/planning-artifacts/prd.md#CLI-Tool-Specification` (L973-L974, L985-L1005)] — `list-customers` / `list-keys` flag set and canonical "who owes me?" query.
- [Source: `_bmad-output/planning-artifacts/prd.md#Journey-2-Monthly-Billing-Ritual` (L278-L346)] — filter composition example `--status active --paid-until-lte today`.
- [Source: `_bmad-output/planning-artifacts/prd.md#Journey-5-Debug-Session` (L436-L483)] — `show --audit-tail` is Story 1.4, not 1.3 (scope guard).
- [Source: `_bmad-output/planning-artifacts/architecture.md#Core-Architectural-Decisions` (L171-L176)] — SQLite WAL + per-CLI-invocation connection pattern. Story 1.3 uses the same.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Implementation-Patterns-Consistency-Rules` (L293-L321)] — DB / ID / audit-action / CLI naming. `list-customers` / `list-keys` hyphenated.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Import-Boundary-Rules` (L366-L372)] — CLI must not import from `keys.auth` or `keys.cache`.
- [Source: `_bmad-output/planning-artifacts/architecture.md#SQLite-Query-Patterns` (L376-L383)] — parameterized `?` placeholders, no f-string SQL.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Enforcement-Guidelines` (L471-L488)] — grep-based regression rules (Task 10.6).
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#StatusTable` (L746-L766)] — component spec.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Empty-States` (L1017-L1041)] — first-run hint policy and empty-results-are-not-errors.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Visual-Design-Foundation` (L382-L403)] — 4-color palette rules.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Responsive-Strategy` (L1063-L1081)] — 80-col terminal adaptation.
- [Source: `_bmad-output/implementation-artifacts/1-1-customer-registration-with-cpf-cnpj-validation.md#Dev-Agent-Record`] — prior-story intelligence (CliRunner mix_stderr removed, `_reset_for_tests` pattern, audit blocklist raises ValueError).
- [Source: `_bmad-output/implementation-artifacts/1-2-api-key-issuance.md#Dev-Agent-Record`] — `_resolve_today_in_tz` seam, `_format_brl` helper, `get_customer` read helper, Story 1.2 `_errors.py` extraction.
- [Source: `_bmad-output/implementation-artifacts/deferred-work.md`] — CLI config inheritance, `--rpm` unbounded, `price_monthly` float-drift (all out of scope for 1.3).
- [Source: `_bmad-output/project-context.md#Critical-Implementation-Rules`] — uv-only, no `os.environ`, no raw `HTTPException`, structured logging, English only.
- [Source: `CLAUDE.md`] — project language policy, Docker v2 syntax, `uv` only, no raw `HTTPException`, no `print()`.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (Claude Opus 4.7, 1M context)

### Debug Log References

- **DB query timing for NFR4 (1,001 rows).** `list_customers` returned 1,001 `CustomerListRow` objects in 3.32 ms (measured inside the Python process, LEFT JOIN + GROUP BY against a fresh DB with one primed row and 1,000 directly-inserted rows). Wall-clock `time uv run comadre-keys list-customers --format json` on the same DB was 0.555 s — the bulk of that is Python + uv + settings bootstrap, not the query. NFR4's 200 ms budget comfortably covered; no indexing change needed.
- **80-column smoke test (Task 9.1).** On gnome-terminal at 80 cols with `stty cols 80`, the `list-keys` table rendered all six columns; rich auto-wrapped the `Customer` cell ("Helena Ribeiro" → two lines) and ellipsized the `Status` cell's `complimentary` label to `complimen…`. Labels for `active` / `suspended` / `revoked` stayed intact, and the color accelerator is still visible in truetype palettes. UX-DR16 acceptance: rightmost cells may truncate, headers stay visible — satisfied.
- **NO_COLOR sanity (Task 9.2).** `NO_COLOR=1 uv run comadre-keys list-keys | od -c | grep -c '033\['` returned 0. Labels remain readable without color.
- **JSON piping sanity (Task 9.3) and log-routing fix.** First pass on an empty DB showed the structured log line contaminating stdout, so `comadre-keys list-keys --format json | jq` errored with `Extra data`. Root cause: `get_logger()` wires its `StreamHandler` to `sys.stdout`, which was fine for Stories 1.1/1.2 (no JSON output) but clashed with 1.3's JSON mode. Routed the `keys.cli` component logger to `sys.stderr` inside `src/comadre/keys/cli/__init__.py` at import time — scoped fix that leaves the rest of the logging module untouched. Post-fix: stdout is pure JSON, `jq` parses cleanly, and structured operator logs still appear on stderr.
- **caplog incompatibility.** Project loggers set `propagate=False`, so pytest's standard `caplog` fixture can't see `keys.cli` records. The log-sanitization test (`TestLogSanitization` in `test_keys_cli_list_keys.py`) attaches a throwaway `logging.Handler` directly to the `keys.cli` logger for the duration of the CLI invocation — simpler than monkey-patching propagation, and it preserves the project's logging convention.
- **Tested via `CliRunner` fixture cloning.** Both integration files follow the autouse rewire pattern established by `test_keys_cli.py` and `test_keys_cli_issue.py` (fresh StringIO buffers per test, `_reset_for_tests()` tear-down). Help-surface tests strip Panel border glyphs (`│ ╭ ╮ ╰ ╯ ─`) before collapsing whitespace so wrapped help lines read as a single contiguous run — necessary because CI terminal width differs from local and wrapping splits `--billing-mode complimentary` across Panel rows.

### Completion Notes List

- All 10 ACs satisfied with automated coverage; 74 new tests pass, 703 total (was 629 at Story 1.2's end).
- **Scope-additive fix:** `keys.cli` logger now routes to stderr (in `src/comadre/keys/cli/__init__.py`). Not called out in the story but required for AC4 / AC8 JSON-mode stdout purity. No public contract affected; server-side loggers (`comadre.api`, etc.) keep their stdout default.
- **Out-of-scope bits honoured:** no `show`/`update-*`/`rotate-key`/`revoke-key`/`suspend`/`reactivate`/`at-risk`/`revenue`/`mark-paid`; no decryption of `tax_id_encrypted`; no imports from `keys.auth` or `keys.cache` (they don't exist); no audit rows written for any listing; no `with conn:` transactions; no `--format yaml`; no `--paid-until-gte`; no migration files; no cache layer.
- **Parameterized-SQL compliance (FR48 / Task 10.6):** the only f-string in `db.py` SQL assembly is the fixed `{where_clause}` concatenator in `list_api_keys`; its contents are hand-built from literal predicate strings containing `?` placeholders, with operator-supplied values bound positionally.
- **UX-DR13 first-run policy:** `count_first_run(conn)` drives the two-line hint; `count_tombstones(conn)` drives the all-purged single-line hint for `list-customers`; `list-keys` uses `count_first_run` plus per-filter empty-sentence fallbacks.
- **NFR4 perf:** 1,001-row `list_customers` resolved in 3.32 ms in-process — well under the 200 ms budget.

### File List

**Modified (source):**
- `src/comadre/keys/models.py` (+44 lines) — added `CustomerListRow`, `ApiKeyListRow` frozen+slotted dataclasses.
- `src/comadre/keys/db.py` (+117 lines) — added `list_customers`, `list_api_keys`, `count_first_run`, `count_tombstones`; `cast` import; expanded models import.
- `src/comadre/keys/cli/output.py` (+127 lines) — added `_status_label`, `_iso_date`, `render_customer_list`, `render_key_list`, `render_json`, `render_empty_state`; `rich.table.Table`, `rich.text.Text`, model imports.
- `src/comadre/keys/cli/commands/customers.py` (+130 lines) — added `list-customers` command + `_customer_row_to_json` helper + module-level constants; lifted `_missing_key_hint` to module scope; added renderer/db imports.
- `src/comadre/keys/cli/commands/keys.py` (+221 lines) — added `list-keys` command + `_key_row_to_json` + `_resolve_title` helpers + module-level constants; added renderer/db/model imports.
- `src/comadre/keys/cli/__init__.py` (+27 lines) — routes `keys.cli` logger to stderr so JSON stdout stays pure.

**Modified (tests):**
- `tests/test_keys_models.py` (+70 lines) — `TestCustomerListRow`, `TestApiKeyListRow`.
- `tests/test_keys_db.py` (+357 lines) — `_seed_customer_with_time`, `_seed_api_key`, `_count_rows` helpers; `TestListCustomers`, `TestListApiKeys`, `TestCountFirstRun`, `TestCountTombstones`, `TestListCommandsDoNotWrite`.
- `tests/test_keys_output.py` (+180 lines) — `TestStatusLabel`, `TestRenderCustomerList`, `TestRenderKeyList`, `TestRenderJson`, `TestRenderEmptyState`.

**New (tests):**
- `tests/test_keys_cli_list_customers.py` — 11 integration tests covering AC1–AC4, AC9, AC10.
- `tests/test_keys_cli_list_keys.py` — 24 integration tests covering AC5–AC10.

**Modified (planning artifact):**
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — story 1.3 status `ready-for-dev` → `in-progress` → `review`.
- `_bmad-output/implementation-artifacts/1-3-customer-key-listing.md` — task checkboxes, status header, Dev Agent Record, File List, Change Log.

## Change Log

- 2026-04-17 — Landed Story 1.3: `list-customers` + `list-keys` with color-coded StatusTable, `--format json`, filter composition, and first-run hints. Added dual-command integration coverage (35 tests) + 39 unit/renderer tests. Routed `keys.cli` logger to stderr so JSON stdout stays clean for `jq` pipelines.
- 2026-04-17 — Code review run (Blind Hunter + Edge Case Hunter + Acceptance Auditor). 3 decision-needed, 11 patch items, 4 deferred, ~16 dismissed. See `### Review Findings` below.

### Review Findings

- [x] [Review][Decision→Patch] AC7 first-run hint when customers exist but zero keys — **Resolved: fire the hint when `api_key` table alone is empty**, matching AC7's literal text and industry-standard progressive empty-state patterns (gh CLI, aws CLI). Follow-up patch item added below.
- [x] [Review][Decision→Accepted] Out-of-spec logger rewire in `src/comadre/keys/cli/__init__.py` — **Resolved: accepted as a required AC enabler.** stdout-is-data / stderr-is-diagnostics is the POSIX convention; the rewire makes AC4/AC8 hold for `| jq` pipelines. Annotated in Dev Notes below.
- [x] [Review][Decision→Accepted] Listings require `KEY_REGISTRY_ENCRYPTION_KEY` despite being read-only — **Resolved: kept consistent with Story 1.1/1.2.** Fail-closed catches misconfiguration early. The real fix (splitting `Settings` into `RuntimeSettings` + `RegistrySettings`) is already tracked as Epic 2 work in `deferred-work.md`.

- [x] [Review][Patch] `--paid-until-lte` accepts non-YYYY-MM-DD ISO forms (e.g. `"20260415"`) that lexicographically mismatch stored `YYYY-MM-DD` rows — normalized via `resolved_paid = date.fromisoformat(trimmed).isoformat()` [src/comadre/keys/cli/commands/keys.py]
- [x] [Review][Patch] `--paid-until-lte` does not strip leading/trailing whitespace — copy-paste input yields exit 2; `.strip()` applied before validation [src/comadre/keys/cli/commands/keys.py]
- [x] [Review][Patch] `--customer ""` (empty string) bypasses the `None` guard and produces a `"Keys for "` title plus an empty-id SQL lookup — rejected with a usage error before the DB call [src/comadre/keys/cli/commands/keys.py]
- [x] [Review][Patch] `_iso_date` returns `value[:10]` unconditionally — malformed or short values now return the em-dash (length check + YYYY-MM-DD shape check) [src/comadre/keys/cli/output.py]
- [x] [Review][Patch] `_status_label` unreachable fallback `return (status, "")` — now raises `ValueError` so future `CustomerStatus`/`BillingMode` Literal extensions fail loudly in tests [src/comadre/keys/cli/output.py]
- [x] [Review][Patch] `count_first_run` returns `bool` but the `count_` prefix lies about its return type — renamed to `is_first_run` [src/comadre/keys/db.py + callers]
- [x] [Review][Patch] Duplicate `_VALID_LIST_FORMATS = ("table", "json")` declared in both command modules — consolidated into `LIST_FORMAT_CHOICES` in `cli/output.py` [src/comadre/keys/cli/output.py + consumers]
- [x] [Review][Patch] `_issue_key` test helper uses `ORDER BY created_at DESC LIMIT 1` — added `, rowid DESC` tiebreaker to avoid same-second non-determinism [tests/test_keys_cli_list_keys.py]
- [x] [Review][Patch] `TestPopulatedTable.test_populated_table_contents` asserts `"0" in stdout` / `"1" in stdout` / `"2" in stdout` — tightened to split each row on the `│` box-drawing character and match the key-count cell directly [tests/test_keys_cli_list_customers.py]
- [x] [Review][Patch] Integration tests cast arbitrary strings into `CustomerStatus`/`BillingMode` via `cast(object, status)` + `# type: ignore[arg-type]` — dropped the casts; parametrize values now declared with the Literal type so mypy strict mode exercises the real contract [tests/test_keys_db.py]
- [x] [Review][Patch] `paid_until_lte`-only title branch `"Keys (paid until ≤ <date>)"` has no test coverage — added `test_title_only_paid_until_lte` plus whitespace and non-dashed-ISO regression tests [tests/test_keys_cli_list_keys.py]
- [x] [Review][Patch] AC7 first-run hint for `list-keys` when only `api_key` is empty — added `is_first_run_for_keys()` helper and a dedicated test for the "customers exist, zero keys" case [src/comadre/keys/db.py + src/comadre/keys/cli/commands/keys.py + tests/test_keys_cli_list_keys.py]

- [x] [Review][Defer] `_apply_migrations` is imported as a private `_`-prefixed symbol from two CLI modules — pre-existing Story 1.1/1.2 pattern; promote to public name in a follow-up cleanup. [deferred, pre-existing]
- [x] [Review][Defer] Bare `str` Typer options instead of `click.Choice`/`Enum` for `--status` / `--billing-mode` / `--format` — loses framework-provided tab-completion and `--help` enumeration, but matches Story 1.2 `issue-key` style. [deferred, pre-existing]
- [x] [Review][Defer] `list_api_keys` assembles SQL via an `f"{where_clause}"` interpolation that is currently safe (literal predicate strings with `?` placeholders) but opens a trap for future dynamic predicates — Task 10.6 grep sentinel guards it today; larger refactor could switch to a `WHERE 1=1` + appended-`AND` pattern. [deferred, design-level]
- [x] [Review][Defer] `render_json` does not validate against NaN / Inf floats — no current writer produces these in `price_monthly`, but future PSP adapters might; guard with `json.dumps(..., allow_nan=False)` pre-check. [deferred, future-facing]
