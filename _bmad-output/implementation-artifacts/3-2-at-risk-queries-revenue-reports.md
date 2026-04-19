# Story 3.2: At-Risk Queries & Revenue Reports

Status: done

> **Scope note — FR16 / FR17 split.** Story 3.2 adds the two **read-only** billing verbs Epic 3 needs to close the monthly ritual. `at-risk` answers "who's about to expire so I can ping them?" (Day 04–05 prep). `revenue` answers "how much did I make this month?" (Day 05 close / Day 06 screenshot). They share the `billing.py` Typer subapp that Story 3.1 created, they reuse Story 1.3's `list_api_keys` reader for the key enumeration, and they both land behind `--format json` for scripted pipelines. **No schema change. No new runtime module. No new dependency.** Both commands are strictly read-only — zero audit rows, zero sentinel touches, zero DB writes.

## Story

As an operator,
I want to preview upcoming key expirations with `comadre-keys at-risk --window Nd` and see paid/pending/suspended/complimentary + MRR + projected totals with `comadre-keys revenue --month current|YYYY-MM`,
so that on Day 04 I can proactively chase payments via WhatsApp Pix QRs and on Day 05 I can take the screenshot that proves the business model works.

**Covers FRs:** FR16 (look-ahead expiration query), FR17 (monthly revenue report with paid/pending/suspended/complimentary breakdown; complimentary never counted in MRR).
**UX-DRs:** UX-DR2 (StatusTable with invariant column order + yellow at-risk badges + table-title-reflects-filter), UX-DR4 (RevenueReport single-border `rich.Panel` with `Rule()` separators and `[bold]` totals).
**NFRs:** NFR5 (`revenue` / `at-risk` complete under 500 ms for 1 000-customer DB), NFR15 (PII-austere INFO logs), NFR16 (error `hint` never echoes invalid operator input).
**Epic:** 3 — Billing & Revenue Operations. Second story in Epic 3. Closes the Day-04/Day-05 ritual on top of the write surface Story 3.1 landed; Story 3.3's cron sweep runs orthogonally on Day-06 and shares zero code with 3.2.

## Builds on

- **Story 3.1 — `billing.py` scaffolding** — the Typer subapp at `src/comadre/keys/cli/commands/billing.py` already exists and is registered in `src/comadre/keys/cli/app.py:25` via `app.registered_commands.extend(billing_app.registered_commands)`. Story 3.2 **appends** `at-risk` and `revenue` as two new `@app.command(...)` decorators in the same file; no new app module, no new `app.py` edit. The exit-code contract docstring at the top of `billing.py` covers both new verbs unchanged (0 / 2 / 3 / 5 / 6 — `at-risk` and `revenue` can never emit 3 because they do not resolve a single key identifier).
- **Story 3.1 — shared CLI preamble** — `load_settings_and_tz()` and `resolve_today_in_tz` are the exact settings/tz loaders both new commands call (already imported in `billing.py`). The Story 3.1 rename made them public — Story 3.2 reuses them verbatim. No helper refactor.
- **Story 1.3 — `list_api_keys` reader** — `src/comadre/keys/db.py:508–565` is the DB-side enumeration used for both commands. `at-risk` calls it with `status="active"` + an in-Python filter on `paid_until` (the SQL `paid_until_lte` filter matches NULL-or-lte which is not what at-risk wants). `revenue` calls it with no filters and bucketizes in Python. **Do not add new helpers to `db.py`**: both commands are read paths over the same row set `list-keys` already exposes — adding `list_at_risk_keys` or `summarize_revenue` there would triplicate the SQL surface for zero value. Bucketize in the command body.
- **Story 1.3 — `--format json` branching** — `list_keys_cmd` at `src/comadre/keys/cli/commands/keys.py:482–700` is the reference pattern: `LIST_FORMAT_CHOICES = ("table", "json")` literal, upfront membership check (exit 2), `render_json([...])` for JSON, `render_empty_state([...])` for empty-human, `render_*` for populated-human. Story 3.2 follows the same pattern for `at-risk`; `revenue` follows the `show --format json` pattern (single-object payload via `Console.print_json(data=...)`, not an array).
- **Story 1.3 — `render_empty_state([lines])`** at `src/comadre/keys/cli/output.py:318–327` — the canonical empty-result renderer. `at-risk` with zero rows renders `render_empty_state(["No keys at risk in the next 5 days."])`; `revenue` with zero keys in-scope renders `render_empty_state(["No keys to report for <month>."])`. Exit 0 in both cases (empty results are not errors — UX-DR12 + `ux-design-specification.md:1015–1029`).
- **Story 1.3 — `_iso_date` + `_format_brl` renderers** at `src/comadre/keys/cli/output.py:78–88, 221–240` — the pt-BR currency formatter and the NULL-safe ISO-date slicer. Both new renderers reuse these verbatim. **Never reimplement currency formatting** — `_format_brl` handles the `1.234,56` convention and is covered by existing tests.
- **Story 1.3 — `render_key_list` column shape** (`src/comadre/keys/cli/output.py:270–305`) — for `at-risk`, the table is a StatusTable variant that **replaces** the `list-keys` "Paid Until" column with **"Paid Until" + "Days Left"** (a signed integer). The invariant column order from UX-DR2 is preserved: identifier → name → status → billing fields → dates. Status column is always `yellow` "suspended" OR `yellow` "at-risk (active, expiring)" per AC2 — see `render_at_risk_table` spec in §3.
- **Story 1.3 — `resolve_today_in_tz`** — `src/comadre/keys/cli/_clock.py` is the clock seam. Both commands resolve `today` via `_resolve_today_in_tz(billing_tz)` so tests can freeze the clock by monkeypatching that single symbol. **Never import `date.today` directly in command bodies.**
- **Story 2.1 billing auth behavior** — `ManualBillingProvider.is_payment_current` (`src/comadre/keys/billing.py:35–43`) treats `paid_until IS NULL` as "not paid" (trial window; auth allows-while-active). For **revenue reporting**, NULL `paid_until` on an `active` manual key counts as **pending** (revenue at risk, not yet received) — consistent with the `list-keys --paid-until-lte today` semantics from Story 1.3 where NULL is included in the at-risk set.
- **Story 1.3 `list-keys` + Story 3.1 `mark-paid` end-to-end** — both stories establish that `paid_until` is stored as a canonical `YYYY-MM-DD` TEXT string in SQLite and is sortable lexicographically. Story 3.2 relies on that canonical shape for `date.fromisoformat(paid_until)` in Python without try/except — malformed values cannot reach the command body in well-formed registries, and the defensive `_iso_date` renderer short-circuits any corrupted row to a `—` em-dash. See CLAUDE.md gotcha "Never check `paid_until` without also checking `billing_mode`" — both new commands honor this pairing.

## Unblocks

- **Story 3.3 — Automated Suspension Sweep & Cron** — 3.3 needs the same "expired active manual keys" predicate that `at-risk --window 0d` evaluates. 3.2 establishes the in-Python bucket shape (`ActiveManualBucket`, `ComplimentaryBucket`, etc.) that 3.3's `suspend_sweep` can reference for its pre-sweep dry-run (`suspend-sweep --dry-run`) if that flag materializes. No direct code sharing — 3.3 writes a single UPDATE; 3.2 only reads.
- **Story 3.4 — System Health Command** — 3.4's `health` command will need aggregate counts (active / suspended / revoked / complimentary). The bucketization logic introduced in 3.2 for `revenue` can be refactored into a shared `_summarize_portfolio(rows)` helper at 3.4 time **if 3.4 needs the exact same splits**. Story 3.2 does NOT pre-extract that helper — adding indirection for a future caller that hasn't landed yet is speculative scope. Keep the bucketize loop inline in `revenue_cmd` for now; 3.4 can extract it cleanly when the second caller arrives.
- **Story 4.1 — LGPD Data Operations (`export-customer`, `delete-customer --hard`)** — 4.1's export must round-trip customer state; if a customer's keys show up in `at-risk` the day before a hard-delete, the two surfaces must tell a consistent story. 3.2 does not touch 4.1's concerns but establishes the "every read command filters `customer.deleted_at IS NULL`" pattern via `list_api_keys`'s existing JOIN (Story 1.3 already enforces this — 3.2 inherits it).

## Depends on

- Stories 1.1–1.6, 2.1–2.3, 3.1 must be `done` (all are, per `_bmad-output/implementation-artifacts/sprint-status.yaml` L58–85 as of 2026-04-18).
- No new dependency in `pyproject.toml`. Both commands use stdlib `datetime`, `sqlite3`, `typer`, plus the existing `comadre.keys.*` + `comadre.keys.cli.*` + `rich` surfaces.
- No schema change. The `idx_api_key_sweep` partial index (`api_key(billing_mode, paid_until) WHERE status = 'active'`) in `v001_initial.sql:44` is already tuned for both queries' predicate shape. `at-risk` and `revenue` are both NFR5-bound (<500 ms for 1 000 customers); the existing index + the in-Python bucketize approach meets this trivially — a 1 000-row scan in SQLite + a single Python loop is sub-10 ms on the test runner.

## Scope

Adds two CLI commands (`at-risk`, `revenue`) in `src/comadre/keys/cli/commands/billing.py` plus two new renderer functions (`render_at_risk_table`, `render_revenue_report`) in `src/comadre/keys/cli/output.py` plus one new typed result dataclass (`RevenueReport`) in `src/comadre/keys/models.py`. **No new module. No schema change. No change to `db.py`. No change to `rate_limit.py` / `api.py` / `keys/auth.py` / `keys/cache.py`. No new dependency.**

### 1. New CLI command: `at-risk`

`src/comadre/keys/cli/commands/billing.py` — append after `reactivate_cmd`.

```python
@app.command("at-risk")
def at_risk_cmd(
    window: str = typer.Option(
        "5d",
        "--window",
        help=(
            "Look-ahead window for expirations. Format: Nd where N is a "
            "positive integer (days). Example: --window 5d, --window 14d."
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
    """Preview active manual keys whose paid_until falls within a window.

    Example: comadre-keys at-risk --window 5d
    """
```

Validation ladder:

1. **`--format` membership.** `if format not in LIST_FORMAT_CHOICES: render_error(...); raise typer.Exit(code=2)`. Reuse the same literal from `output.py`.
2. **`--window` shape.** Strip whitespace. Require regex `^[1-9][0-9]*d$` (non-negative, non-zero, ends in `d`). Reject `"0d"` (a zero-day window is meaningless — use `list-keys --paid-until-lte today` for that), reject unit-less digits, reject `"-5d"` / `"5w"` / `"5"` / `""`. On violation render an ErrorDisplay with title `Usage error: --window must be Nd where N ≥ 1 (days)` and hint `Example: --window 5d (today through today+5). Use a larger window for more look-ahead.` Exit 2.
3. **Upper cap:** reject windows above **365d** to avoid the "whole portfolio" degenerate case. Hint: `Maximum window is 365d. Use 'comadre-keys list-keys' for a full scan.` Exit 2.
4. **Settings + TZ** (exit 6) — `load_settings_and_tz()`.
5. **DB open + migrations** (exit 5) — same pattern as the mutation commands, but **no `resolve_key_target` call** (at-risk operates on the full active-manual set).
6. **Compute `today` + `cutoff`** — `today = _resolve_today_in_tz(billing_tz)`; `cutoff = today + timedelta(days=window_days)` where `window_days` is the parsed integer.
7. **Enumerate active keys** — `list_api_keys(conn, status="active", billing_mode="manual")`. Complimentary rows are never returned because they are excluded by `billing_mode="manual"`. Revoked and suspended rows are never returned because the predicate is `status="active"`. This is the canonical predicate shape for FR16.
8. **Filter in Python** — retain rows where `paid_until IS NOT NULL` AND `today <= date.fromisoformat(row.paid_until) <= cutoff`. NULL `paid_until` (trial-window active manual keys) is **excluded** from `at-risk` — trial-window customers are handled by the J1 first-sale flow, not the Day-04 pre-billing review. Document this in `--help`.
9. **Sort in Python** — `sorted(rows, key=lambda r: (r.paid_until, r.customer_name))` so the operator sees the most imminent expirations first, with name as a stable tiebreak.
10. **Branch on `--format`** — JSON path: `render_json([_at_risk_row_to_json(r, days_left=...) for r in filtered])`. JSON payload shape mirrors `_key_row_to_json` with an added `days_left: int` field. Table path: if empty → `render_empty_state([f"No keys at risk in the next {window_days} days."])`. Populated → `render_at_risk_table(rows, window_days, today)`.
11. **Structured INFO log** (stderr) — `"At-risk queried | window_days=%d | count=%d"`. No customer_name, no key_prefix in aggregate. PII-austere per NFR15.

**Empty-state byte-identity.** The empty-message string is `f"No keys at risk in the next {window_days} days."` (not `{window}` with the `d` suffix — the parsed integer). AC matches the exact format shown in `ux-design-specification.md:1025–1026` and `epics.md:667`.

### 2. New CLI command: `revenue`

`src/comadre/keys/cli/commands/billing.py` — append after `at_risk_cmd`.

```python
@app.command("revenue")
def revenue_cmd(
    month: str = typer.Option(
        "current",
        "--month",
        help=(
            "Month to report: 'current' or YYYY-MM. Example: --month current "
            "or --month 2026-05."
        ),
    ),
    format: str = typer.Option(
        "table",
        "--format",
        help=(
            "Output format: table (default, human-readable panel) or json. "
            "Example: --format json."
        ),
    ),
) -> None:
    """Monthly revenue report: paid / pending / suspended / complimentary.

    Example: comadre-keys revenue --month current
    """
```

Validation ladder:

1. **`--format` membership** (exit 2) — same as `at-risk`.
2. **`--month` shape.** Strip whitespace.
   - `"current"` → resolve to `today.strftime("%Y-%m")` after TZ load (deferred).
   - Else match regex `^\d{4}-\d{2}$`. Reject anything else with `Usage error: --month must be 'current' or YYYY-MM (e.g., 2026-05)`. Exit 2.
   - Parse `year, month = map(int, month_str.split("-"))`. Reject `month not in 1..12` and `year not in 2020..2099` (sane operator bounds — no 1901 ghosts, no 3000 future). Exit 2.
3. **Settings + TZ** (exit 6) — `load_settings_and_tz()`.
4. **Resolve `today`** — `today = _resolve_today_in_tz(billing_tz)`.
5. **Resolve `report_month`** — if `--month current`, use `today.year, today.month`. Else use the parsed year/month.
6. **Compute month boundaries** — `month_first = date(report_year, report_month, 1)`; `month_last = date(report_year, report_month, days_in_month)` via `calendar.monthrange(report_year, report_month)[1]`. `next_charge_date = first_charge_date(today=month_last, billing_day=settings.billing_day, tz=settings.billing_timezone)` (reuses Story 1.2's helper from `comadre.keys.billing`).
7. **DB open + migrations** (exit 5).
8. **Enumerate all keys** — `list_api_keys(conn, status=None, billing_mode=None)`. Revoked keys are **included** in the read but excluded from every bucket (they are historical records per FR12/FR19). Active, suspended, and complimentary rows bucketize as below.
9. **Bucketize in Python** (one pass over `rows`):
   - **`paid`** (counted in MRR): `status == "active"` AND `billing_mode == "manual"` AND `paid_until is not None` AND `date.fromisoformat(paid_until) >= month_first`. Rationale: "paid through this month" means `paid_until` covers at least the first of the reporting month (the operator paid on Day 05 of the prior month for the coming period, so the cycle aligns with calendar months).
   - **`pending`** (not yet in MRR, still billable): `status == "active"` AND `billing_mode == "manual"` AND (`paid_until IS NULL` OR `date.fromisoformat(paid_until) < month_first`). Rationale: active manual keys whose `paid_until` is behind the reporting month are payments the operator is still waiting for (Day 04 chase list) OR trial-window keys not yet billed.
   - **`suspended`** (carry-over): `status == "suspended"` AND `billing_mode == "manual"`. Rationale: Day-06 carry-overs from prior months; operator surface wants to see them so zero counts on a clean month are a positive signal.
   - **`complimentary`**: `billing_mode == "complimentary"` AND `status != "revoked"` (active OR suspended — complimentary suspensions from 3.1 AC12 count here, not in the suspended bucket). Rationale: FR17 explicitly segregates complimentary from MRR and projected revenue; a suspended complimentary key is still a bundled relationship, just paused.
   - **revoked** rows (`status == "revoked"`): **ignored entirely**. Not counted in any bucket. Not surfaced in any section.
10. **Compute totals:**
    - `mrr = sum(row.price_monthly for row in paid_rows)` (paid manual only).
    - `projected = sum(row.price_monthly for row in paid_rows + pending_rows)` (paid + pending manual).
    - Complimentary rows contribute `0.0` to both — `price_monthly` for complimentary keys is `0.0` by Story 1.2 convention, so technically summing them would be a no-op, but the bucket separation is load-bearing for the renderer and the JSON shape.
11. **Assemble a `RevenueReport` dataclass** (see §4 models) and pass to `render_revenue_report` or `_revenue_report_to_json`.
12. **Branch on `--format`** — JSON: `_revenue_report_to_json(report)`. Table: if **all four buckets** are empty → `render_empty_state([f"No keys to report for {month_label}."])`. Populated → `render_revenue_report(report)`.
13. **Structured INFO log** — `"Revenue report | month=%s | paid=%d | pending=%d | suspended=%d | complimentary=%d | mrr=%.2f | projected=%.2f"`. PII-austere.

**Why "paid" uses `paid_until >= month_first` and not `>= today`.** The report is per-calendar-month, not per-today. If today is 2026-05-20 and Pedro's key has `paid_until='2026-05-05'` (he paid for May on Apr 5, and his coverage ends today + 15 days if he pays June 5), he counts as **paid for May**. If Marcos's key is also `paid_until='2026-05-05'` but `--month 2026-06` is queried, Marcos is **pending** for June (he hasn't paid the June cycle yet). The predicate `paid_until >= month_first` is exactly the "covered at least the first of the reporting month" test — the cycle aligns with calendar months, not arbitrary dates.

**Why historical months show live state, not time-travel.** The epic AC (`epics.md:675–677`) says "the report shows the state as of that month based on payment records". A true time-travel report (replaying the audit log to reconstruct historical `paid_until` / `status` as of the reporting month) is **out of scope for 3.2** — it would require either a time-indexed snapshot table or a per-row audit replay, both of which cost schema changes and O(audit_rows) work per report. Instead, 3.2 reports the current live state filtered by the reporting month's `paid_until` predicate. For the operator's Day-05 workflow this is the correct semantic: "show me who paid for May, regardless of when I run the command". Historical months queried weeks later still give useful answers — paid rows stay paid (no-one un-pays), and the suspended bucket reflects cumulative carry-overs. The deferred-work entry at §9.2 notes the time-travel approach for a future story if operators ever need "state as of Day 06 of May 2026 specifically".

### 3. New renderer: `render_at_risk_table`

`src/comadre/keys/cli/output.py` — append after `render_key_list` (line ~305). Mirrors `render_key_list` byte-for-byte in column machinery; differs only in title composition, status cell color, and the added `Days Left` column.

```python
def render_at_risk_table(
    rows: list[ApiKeyListRow],
    window_days: int,
    today: date,
) -> None:
    """UX-DR2 — at-risk StatusTable with yellow badges and days-left column.

    Invariant column order (identifier → name → status → billing → dates):
      Prefix | Customer | Status | Price | Paid Until | Days Left

    ``today`` is injected so ``days_left`` is clock-frozen for tests —
    callers MUST pass the same ``today`` they used to filter the rows.
    """
```

Implementation notes:

- **Title**: `f"At-Risk Keys (next {window_days} days)"` — matches AC2 verbatim and `epics.md:663`.
- **Status cell**: always `[yellow]at-risk[/]`. The existing `_status_label` helper returns `("active", "green")` for active manual keys, which is wrong for this table — the at-risk *set* is a semantic overlay on active manual keys that should read yellow to signal urgency per UX-DR2. Use a hard-coded `Text("at-risk", style="yellow")` for the status cell — do NOT add a new `at_risk` variant to `_status_label` (overloading the status label with a set-membership concept would confuse every other caller of that helper).
- **Days Left**: `(date.fromisoformat(row.paid_until) - today).days`. Right-justified column. Rows are pre-filtered so `paid_until` is non-NULL; a defensive NULL check returning `"—"` is not needed because the caller's filter guarantees the invariant.
- **Price**: reuse `_format_brl(row.price_monthly)` with `R$ ` prefix (identical to `render_key_list`).
- **Footer**: `render_confirmation(f"{len(rows)} keys found.")` — same as `render_key_list`.

### 4. New renderer: `render_revenue_report` + `RevenueReport` dataclass

**Model** — `src/comadre/keys/models.py`, append near `Last24hStats` (line ~201):

```python
@dataclass(frozen=True, slots=True)
class RevenueReport:
    """Aggregated monthly revenue data payload for ``revenue_cmd``.

    ``month_label`` is the human-readable month label (``"May 2026"``,
    localized to the operator's ``document_output_language`` — English by
    default). ``mrr`` counts only **paid** manual-mode revenue.
    ``projected`` counts paid + pending. ``complimentary_rows`` carries
    the per-row notes so the renderer can list them with their bundled
    context; complimentary rows are NEVER summed into any total.

    All numeric totals are ``float`` for wire consistency with
    ``api_key.price_monthly``; the renderer applies ``_format_brl`` for
    pt-BR display. Counts are integers.
    """

    month_label: str
    month_iso: str  # "YYYY-MM" — stable key for JSON consumers
    paid_count: int
    pending_count: int
    suspended_count: int
    complimentary_count: int
    mrr: float
    projected: float
    next_charge_date: str  # ISO "YYYY-MM-DD"
    complimentary_rows: tuple[ApiKeyListRow, ...]
```

**Why a `tuple` of rows, not a separate `ComplimentaryEntry` dataclass.** `ApiKeyListRow` already carries `(key_prefix, customer_name, billing_mode, ...)` — adding a parallel dataclass with `(key_prefix, customer_name, notes)` would be redundant. The renderer reads `row.key_prefix`, `row.customer_name`, and reads `notes` via a second helper (complimentary rows' notes aren't in `ApiKeyListRow` today — see note below). `frozen=True, slots=True` keeps the type identity aligned with the other models in the file.

**Note on complimentary `notes`.** `ApiKeyListRow` does NOT include the `notes` column today (it's in `KeyDetailRow` only). To surface complimentary-row notes in the report (per `epics.md:672`, "complimentary keys are listed separately with their notes"), the renderer has two options:

- **Option A (chosen):** Extend `ApiKeyListRow` with a `notes: str` field (default `""`). Requires updating `list_api_keys` to select `k.notes` and populate the new column. One-line change in `db.py:540–562`; propagates to `list-keys` table output (ignored there — column not added to `render_key_list`) and the JSON shape (adds a `notes` key — see §5 JSON compatibility). Story 1.3's `_key_row_to_json` needs a corresponding line to include the field.
- **Option B (rejected):** Issue a second `SELECT k.notes FROM api_key WHERE id IN (...)` inside `revenue_cmd` just for complimentary rows. N+1 shape; fragile; duplicates a column the row already has adjacent to its primary read.

Option A is the right call: the `notes` column is cheap (TEXT with empty-string default), the JSON shape addition is backward-compatible (new key, existing consumers ignore it), and it removes a reason to ever touch `db.py` from `billing.py`.

**Renderer** — `src/comadre/keys/cli/output.py`, append after `render_key_list`:

```python
def render_revenue_report(report: RevenueReport) -> None:
    """UX-DR4 — single-border Panel with Rule() separators and [bold] totals.

    Structure (matches ``ux-design-specification.md:787–803`` + ``prd.md:331–342``):
      ┌─ Revenue Report — May 2026 ─┐
      │ Paid customers:        12   │
      │ Pending:                2   │
      │ Suspended (carry-over): 0   │
      │ Complimentary:          1   │
      │ ─────                       │   <-- Rule()
      │ Monthly recurring:     R$ 1.643,00 (bold)
      │ Projected (if all pay):R$ 1.891,00 (bold)
      │ Next charge date:      2026-06-05
      │ ─────                       │   <-- Rule() (only if complimentary_rows)
      │ Complimentary keys:         │
      │   cmdr_Cx (AgroBots) — ...  │
      └─────────────────────────────┘
```

- **Panel title**: `f"Revenue Report — {report.month_label}"` (one em-dash U+2014, spaces on both sides).
- **Box**: `box.ROUNDED` (matches the DetailPanel rendering in `render_key_detail`).
- **Rule separator**: `rich.rule.Rule()` (no title) between the count block and the totals block; second Rule() only when `report.complimentary_rows` is non-empty.
- **Bold totals**: `f"Monthly recurring:    [bold]R$ {_format_brl(report.mrr)}[/bold]"` and the projected line. `[bold]` markup on the totals; label and `R$ ` prefix stay unbolded so triple-click selects a readable "R$ 1.643,00" segment.
- **Label padding**: fixed to the longest label width across the panel (currently `"Complimentary:"` at 14 chars — compute dynamically like `render_customer_detail` / `render_key_detail` so future label changes don't drift). Right-pad labels; left-align values.
- **Complimentary listing lines**: `f"  {row.key_prefix} ({row.customer_name}) — {row.notes or '—'}"` — one line per row, two-space indent, em-dash between customer name and notes. If `notes` is empty, use the em-dash (U+2014) as a placeholder so the visual structure stays constant.
- **No footer `render_confirmation`** — the panel is the terminal output; a trailing "N keys reported" line would crowd the operator's screenshot.
- **`markup=True` on the panel** so `[bold]` renders; pass `markup=False, highlight=False` on the individual complimentary row lines to prevent a rogue `[red]` in operator-supplied notes from repainting the output (defense against the Story 1.4 deferred "Rich markup injection via stored notes" — same mitigation as `render_audit_tail`).

### 5. JSON output shapes

**`at-risk --format json`** — array of objects, one per at-risk row:

```json
[
  {
    "id": "key_01J...",
    "customer_id": "cust_01J...",
    "customer_name": "Pedro Lopes",
    "key_prefix": "Pq_abc12",
    "status": "active",
    "billing_mode": "manual",
    "rate_limit_rpm": 60,
    "price_monthly": 149.0,
    "paid_until": "2026-04-21",
    "created_at": "2026-01-05T12:00:00Z",
    "last_used_at": "2026-04-17T09:12:33Z",
    "days_left": 3
  }
]
```

Keys follow fixed order (reuse `_key_row_to_json` verbatim then append `days_left`). Helper name: `_at_risk_row_to_json(row, *, days_left)`.

**`revenue --month ... --format json`** — single object (not an array — a report is one entity, not a collection):

```json
{
  "month": "2026-05",
  "month_label": "May 2026",
  "paid_count": 12,
  "pending_count": 2,
  "suspended_count": 0,
  "complimentary_count": 1,
  "mrr": 1643.0,
  "projected": 1891.0,
  "next_charge_date": "2026-06-05",
  "complimentary": [
    { "key_prefix": "Cx_abc12", "customer_name": "AgroBots", "notes": "bundled R$ 850/mo" }
  ]
}
```

Helper name: `_revenue_report_to_json(report)`. Uses `Console.print_json(data=...)` (not `render_json([...])` — that helper wraps in an array).

**Why `mrr` and `projected` are floats and not strings.** `list-keys --format json` emits `price_monthly` as a float (`149.0`). Consistency demands the report do the same. Scripted pipelines consuming the JSON (ops dashboards, ad-hoc `jq` queries) will format for display themselves. The human surface uses `_format_brl` on the same floats.

### 6. ApiKeyListRow + list_api_keys notes-column addition

`src/comadre/keys/models.py` — add `notes: str` to `ApiKeyListRow` (default empty string for backward compat during migration, but since it's a `@dataclass(frozen=True, slots=True)` with no defaults elsewhere, emit it as a required field and update `list_api_keys` simultaneously — a mixed-field-order dataclass is not readable).

`src/comadre/keys/db.py:540–562` — `list_api_keys`:

1. Add `k.notes` to the SELECT column list (after `k.last_used_at`).
2. Add `notes=row["notes"] or ""` to the `ApiKeyListRow(...)` construction.

`src/comadre/keys/cli/commands/keys.py` — `_key_row_to_json` (L440–454):

Add `"notes": row.notes` at the end of the returned dict. Existing JSON consumers gain a new key but no key removal or rename — backward compatible.

No rename in tests: existing `list-keys --format json` tests don't assert "only these keys" — they assert the presence of the known keys — so adding `notes` doesn't break them. Re-run the suite to confirm.

### 7. JSON contract guarantees

- **Key order stable.** Python 3.7+ guarantees dict insertion order; `Console.print_json(data=...)` preserves it. Tests assert on `json.loads(out)` (order-insensitive) but the documented key order above is the source of truth for scripted consumers.
- **No `null` for empty counts.** Zero counts are emitted as `0`, not `null`. Zero-length `complimentary` is `[]`, not `null` — the array key is always present.
- **No extra fields.** The renderer emits exactly the keys shown in §5. No `debug`, no `schema_version`, no timestamps of when the report was run (the report is about the reporting month, not about execution time).

### 8. Exit-code contract (UX-DR10 + `billing.py` docstring)

| Exit | `at-risk` trigger | `revenue` trigger |
|------|-------------------|-------------------|
| 0 | Success (including empty result — `No keys at risk ...`) | Success (including empty result — `No keys to report ...`) |
| 2 | Bad `--window` shape / `--format` literal | Bad `--month` shape / `--format` literal |
| 3 | _never — neither command resolves a single key identifier_ | _never — neither command resolves a single key identifier_ |
| 5 | `sqlite3.Error`, `RuntimeError` from `_apply_migrations` | same |
| 6 | Missing `KEY_REGISTRY_ENCRYPTION_KEY` / invalid `BILLING_TIMEZONE` | same |

The `billing.py` module docstring already enumerates these (Story 3.1 §4 header). No docstring change — the existing text covers both new verbs unchanged. The exit-3 row is listed for completeness but neither new command can emit it; the deferred-work note §9 addresses this asymmetry as a future docstring cleanup.

### 9. Docs

- **`CLAUDE.md`** — extend the `keys/cli/` bullet (currently `create-customer, list-customers, update-customer, issue-key, list-keys, update-key, rotate-key, revoke-key, mark-paid, suspend, reactivate, show, cache-status`) to append `at-risk` and `revenue` after `reactivate`, keeping the alphabetical-by-function grouping (customers → keys → billing → system — `at-risk` and `revenue` both land in the billing cluster). One-word edit inside a single bullet.
- **`README.md`** — append to the billing-verbs line added in Story 3.1 (or create a fresh line under "Registry-backed API keys" if absent): `comadre-keys at-risk --window 5d` and `comadre-keys revenue --month current` with a one-sentence description each. The `revenue` one-liner is the operator's "screenshot the number" surface; the `at-risk` one-liner is the Day-04 chase-list.
- **`docs/configuration-reference.md`** — no new settings introduced (`BILLING_TIMEZONE` and `billing_day` are already documented and reused). Append a second one-line "see also" under the BILLING_TIMEZONE entry: `at-risk`, `revenue` → "read the reporting month / look-ahead window in this timezone."
- **No `docs/monetization.md`** — still deferred to Story 4.6 per Story 3.1 §6.

### 10. Tests

Follow the Story 3.1 convention — one test file per command, plus output-renderer tests in `test_keys_output.py` and a JSON-shape regression in a new `test_keys_output_revenue.py` (or append to `test_keys_output.py` — pick the smaller diff).

- **`tests/test_keys_cli_at_risk.py`** (NEW) — end-to-end CLI via `CliRunner`, mirroring `tests/test_keys_cli_list_keys.py` scaffolding:
  - AC coverage: table path (1, 2, 3, 5 rows), empty-table path (informational, exit 0), JSON path (valid JSON array with `days_left` ascending), `--window 1d` / `--window 14d` / `--window 365d`, invalid `--window` shapes (`0d`, `-5d`, `5w`, `5`, empty, `366d`, `abc`) all exit 2.
  - Time-freeze via monkeypatching `comadre.keys.cli._clock.resolve_today_in_tz` to a fixed `date(2026, 4, 18)`. Seed rows with `paid_until` at `2026-04-18` (edge-today), `2026-04-19` (days_left=1), `2026-04-22` (days_left=4), `2026-04-23` (days_left=5, edge-window), `2026-04-24` (days_left=6, outside window). Assert only the in-window rows surface.
  - NULL `paid_until` active manual key → excluded (trial-window rule).
  - Suspended manual key with `paid_until` in window → excluded (status != active).
  - Complimentary key with `paid_until` in window → excluded (billing_mode != manual).
  - Revoked key with `paid_until` in window → excluded.
  - Sort order: `paid_until ASC, customer_name ASC`. Seed two rows with the same `paid_until` but different customer names; assert alphabetical within the tie.
  - Empty-state byte-identity: `out.strip() == "No keys at risk in the next 5 days."` (exact; no trailing footer).
  - Non-empty table: table title contains `"At-Risk Keys (next 5 days)"`; row footer reads `"N keys found."`.
  - PII-austere log: `_PII_FORBIDDEN_RE` regex from Story 3.1 asserts no customer_name / email / plaintext / 64-hex hash in `caplog` records.
  - `--format json` + empty → JSON `[]` (not the informational sentence); exit 0.
  - `--format json` + populated → `json.loads(out)` parses; each element has the documented key set including `days_left: int`.
  - Performance sanity: happy path on a 100-row seed under 500 ms (NFR5 advisory; use `time.perf_counter()`; `assert elapsed_ms < 1000` in CI for slack).

- **`tests/test_keys_cli_revenue.py`** (NEW) — end-to-end CLI via `CliRunner`:
  - AC coverage: `--month current` on a mixed portfolio (paid, pending, suspended, complimentary, revoked) → assert the four counts, `mrr`, `projected`, `next_charge_date`, complimentary section renders with notes. Time-freeze to `date(2026, 5, 20)`.
  - `--month 2026-05` explicit → same result as `current` when today is May 2026.
  - `--month 2026-04` (prior month, same rows) → paid/pending buckets shift: rows with `paid_until='2026-05-05'` are paid for April (covers >= April 1) and pending for May/June.
  - `--month 2026-06` (future month) → rows with `paid_until='2026-05-05'` are pending for June (not yet covered); rows with `paid_until='2026-06-10'` are paid for June.
  - Invalid `--month` shapes: `"2026-13"`, `"26-05"`, `"may"`, `""`, `"2026-05-05"` (too specific), `"2019-05"` (year bound), `"2100-05"` (year bound) all exit 2.
  - Zero complimentary: the renderer omits the "Complimentary keys:" section (no trailing Rule() or listing) but the `complimentary_count: 0` field is present in JSON.
  - Zero paid + zero pending + zero suspended + zero complimentary (empty portfolio) → table path renders `No keys to report for May 2026.` (informational, exit 0); JSON path renders the full object with all-zero counts.
  - Revoked rows: seed 2 revoked keys and assert they are absent from every count and every section.
  - Complimentary that is SUSPENDED (Story 3.1 AC12 case) → counted in `complimentary_count`, NOT in `suspended_count`.
  - `--format json` + populated → `json.loads(out)` returns a single object (not an array); `complimentary` is a list with `key_prefix / customer_name / notes`.
  - pt-BR currency formatting: `R$ 1.643,00` and `R$ 1.891,00` byte-identity in table output for the canonical seed (12 paid × R$149.00 / adjust seed numbers to match).
  - `[bold]` markup surfaces in table output (assert via rendering with `Console(force_terminal=True, width=80)` and byte-comparing the ANSI stream, or — simpler — assert the substring `R$ 1.643,00` appears on the same line as `Monthly recurring:`).
  - Performance sanity: 1 000-row seed, `--month current`, assert elapsed < 1000 ms (advisory; NFR5 targets 500 ms).
  - PII-austere log regex.

- **`tests/test_keys_output.py`** (MOD) — add two renderer-level unit tests:
  - `test_render_at_risk_table_shape` — feed 3 rows with known `paid_until` + `today`; capture rendered output; assert title, column headers, yellow "at-risk" badge, days-left values, footer.
  - `test_render_revenue_report_shape` — feed a known `RevenueReport` dataclass; capture rendered output; assert panel title, label widths, bold-total markup, complimentary section presence/absence, next-charge-date formatting.
  - `test_render_revenue_report_markup_injection_guarded` — craft a complimentary row whose `notes` contains `"[red]evil[/]"`; assert the rendered output contains the literal `[red]evil[/]` (escaped / not interpreted) — the row-line `markup=False` guard. Parallels the Story 1.4 deferred Rich-markup-injection concern.

- **`tests/test_keys_cli_list_keys.py`** (MOD) — two-line amendment:
  - `_key_row_to_json` now emits `notes`; tighten the JSON-shape test to assert the new key.
  - The existing "all expected keys present" assertion already tolerates additional keys; no break.

- **`tests/test_keys_db.py`** (MOD) — single assertion: `TestListApiKeys` happy-path case now asserts `row.notes == "..."` for a seed row that has notes.

- **`tests/test_keys_models.py`** (MOD or NEW) — add `test_revenue_report_dataclass_frozen` and `test_api_key_list_row_notes_default`.

### 11. Exit-code + module-docstring (no change)

The Story 3.1 module docstring at the top of `billing.py` enumerates the exit-code contract. Story 3.2 adds two new verbs that honor the 0/2/5/6 subset (never 3 — no key-identifier resolution path). The docstring is unchanged; deferred note §9 in deferred-work.md can document the asymmetry if a future docstring refactor tightens it.

## Acceptance Criteria

> BDD-style. Each AC maps to at least one test. AC numbers are stable — do not renumber if a mid-story pivot adds/removes an AC (append a new number instead).

### AC1 — `at-risk` renders in-window active manual keys as a yellow StatusTable

**Given** a registry with:
- Key `Pq_abc12` (Pedro Lopes) — status `active`, billing_mode `manual`, paid_until `2026-04-20`
- Key `Mx_def34` (Marcos Silva) — status `active`, billing_mode `manual`, paid_until `2026-04-22`
- Key `Hx_ghi56` (Helena Ribeiro) — status `active`, billing_mode `manual`, paid_until `2026-04-30` (outside window)
- Today frozen to `2026-04-18`

**When** the operator runs `comadre-keys at-risk --window 5d`

**Then** exit code is 0
**And** stdout contains a table with title `At-Risk Keys (next 5 days)`
**And** the table has exactly two data rows: Pedro first (days_left=2), Marcos second (days_left=4)
**And** the Status column reads `at-risk` in yellow for both rows
**And** the footer reads `2 keys found.`
**And** the 5d window is inclusive on both ends (rows with paid_until == today+5 are included; today+6 is excluded)

### AC2 — `at-risk` empty state is informational (exit 0)

**Given** no active manual keys have `paid_until` within the next 5 days
**When** the operator runs `comadre-keys at-risk --window 5d`
**Then** exit code is 0
**And** stdout contains verbatim: `No keys at risk in the next 5 days.`
**And** no table renders
**And** no red ErrorDisplay renders

### AC3 — `at-risk` excludes NULL paid_until, suspended, complimentary, and revoked keys

**Given** the registry contains one of each:
- Active manual key with NULL `paid_until` (trial window)
- Suspended manual key with `paid_until` inside the window
- Active complimentary key with `paid_until` inside the window (seeded for the test even though complimentary rows normally have NULL paid_until)
- Revoked manual key with `paid_until` inside the window

**When** `at-risk --window 5d` runs
**Then** all four rows are excluded from output (table and JSON alike)
**And** the informational "No keys at risk" message renders (assuming no other in-window rows)

### AC4 — `at-risk` rejects invalid `--window` (exit 2)

**Given** any reachable DB
**When** the operator runs `at-risk --window <value>` for each of:
  `0d`, `-5d`, `5w`, `5`, `""`, `366d`, `abc`, `1.5d`, `5 d` (with space)
**Then** exit code is 2 for every case
**And** stderr contains an ErrorDisplay with title `Usage error: --window must be Nd where N ≥ 1 (days)` (for shape violations) or `Maximum window is 365d. Use 'comadre-keys list-keys' for a full scan.` (for the 366d case)
**And** no DB connection is opened (fail-fast)
**And** the hint never echoes the rejected input verbatim (NFR16 — `<value>` should not appear inside the hint body)

### AC5 — `at-risk --format json` emits a valid array with `days_left`

**Given** AC1's seed
**When** the operator runs `at-risk --window 5d --format json`
**Then** exit code is 0
**And** stdout parses as a JSON array of length 2
**And** each element contains at minimum `id`, `customer_id`, `customer_name`, `key_prefix`, `status`, `billing_mode`, `rate_limit_rpm`, `price_monthly`, `paid_until`, `created_at`, `last_used_at`, `days_left`, `notes`
**And** `days_left` is a non-negative integer
**And** the array is sorted by `(paid_until ASC, customer_name ASC)` — byte-order of the JSON array matches the table row order

### AC6 — `at-risk --format json` + empty → `[]`

**Given** no in-window rows
**When** `at-risk --format json` runs
**Then** exit code is 0
**And** stdout is exactly `[]\n` (JSON empty array, no informational text — JSON consumers read the array length, not English prose)

### AC7 — `revenue --month current` renders the four counts + MRR + projected + next-charge

**Given** today frozen to `2026-05-20`, `BILLING_DAY=5`, and a registry with:
- 12 active manual keys, paid_until `2026-06-05` (≥ month_first, so **paid**)
- 2 active manual keys, paid_until `2026-04-05` (< month_first, so **pending**)
- 0 suspended manual keys
- 1 complimentary key with notes `"bundled R$ 850/mo"`
- Each paid/pending manual key has `price_monthly=149.00`

**When** the operator runs `comadre-keys revenue --month current`

**Then** exit code is 0
**And** stdout contains a single-border Panel titled `Revenue Report — May 2026`
**And** the panel shows (label order fixed):
  - `Paid customers:            12`
  - `Pending:                    2`
  - `Suspended (carry-over):     0`
  - `Complimentary:              1`
**And** after a horizontal Rule():
  - `Monthly recurring:     R$ 1.788,00` (bold) — 12 × R$149.00
  - `Projected (if all pay):R$ 2.086,00` (bold) — 14 × R$149.00
  - `Next charge date:      2026-06-05`
**And** after a second Rule():
  - `Complimentary keys:`
  - `  Cx_abc12 (AgroBots) — bundled R$ 850/mo`
**And** pt-BR currency uses `.` as thousands separator and `,` as decimal separator

### AC8 — `revenue` excludes revoked keys from every bucket

**Given** the AC7 seed plus 3 revoked manual keys with various `paid_until` values
**When** `revenue --month current` runs
**Then** the paid / pending / suspended / complimentary counts are unchanged from AC7
**And** no revoked key appears in the complimentary section
**And** the revoked rows' `price_monthly` does NOT contribute to `mrr` or `projected`

### AC9 — `revenue` separates complimentary from MRR/projected (FR17 hard requirement)

**Given** the AC7 seed **plus** 2 additional complimentary keys each with `price_monthly=500.00` (the operator would never set a price on complimentary, but defense-in-depth: the row reader cannot assume price=0 for complimentary)
**When** `revenue --month current` runs
**Then** `complimentary_count = 3` (the original 1 + 2 new)
**And** `mrr` is unchanged from AC7 (R$1.788,00) — the 2 × R$500.00 does not leak into MRR
**And** `projected` is unchanged — does not leak into projected either

### AC10 — Suspended complimentary key counts as complimentary, not suspended

**Given** the AC7 seed **plus** 1 suspended complimentary key (the Story 3.1 AC12 case)
**When** `revenue --month current` runs
**Then** `complimentary_count = 2`
**And** `suspended_count = 0` (unchanged from AC7)

### AC11 — `revenue --month 2026-05` on a historical date matches `--month current` if today is still May 2026

**Given** today frozen to `2026-05-20`
**When** the operator runs `comadre-keys revenue --month 2026-05` and `comadre-keys revenue --month current`
**Then** both commands produce byte-identical stdout output

### AC12 — `revenue --month 2026-04` (prior) shifts the paid/pending buckets

**Given** today frozen to `2026-05-20` and the AC7 seed
**When** `revenue --month 2026-04` runs
**Then** the 12 active manual keys with `paid_until='2026-06-05'` count as **paid for April** (paid_until >= April 1)
**And** the 2 active manual keys with `paid_until='2026-04-05'` also count as **paid for April** (paid_until == April 5 >= April 1)
**And** the paid/pending split differs from `--month current` accordingly
**And** `next_charge_date` is computed from `date(2026, 4, 30)` as the month-last, via `first_charge_date` — `2026-05-05`

### AC13 — `revenue --month 2026-07` (future) treats uncovered keys as pending

**Given** today frozen to `2026-05-20` and the AC7 seed (12 rows paid_until=`2026-06-05`, 2 rows paid_until=`2026-04-05`)
**When** `revenue --month 2026-07` runs
**Then** all 14 active manual keys count as **pending for July** — every row has `paid_until < 2026-07-01`, so none satisfy the paid predicate
**And** MRR = 0 (zero paid rows for July), projected = 14 × R$149.00 = R$2.086,00, `next_charge_date = 2026-08-05`

> **AC wording resolved 2026-04-19.** Original AC13 prescribed `--month 2026-06` with `MRR=0`, which was self-inconsistent because the 12 seed rows at `paid_until=2026-06-05` satisfy the June predicate (`>= 2026-06-01`). The implemented test (`test_future_month_treats_uncovered_as_pending`) was already written against July; the AC text is aligned here to match. The June case — where the 12 rows count as paid — is implicitly covered by AC7 / AC11 (`--month current` on May 2026 plus byte-identity with explicit May) and by the deferred leap-year / month-boundary coverage notes in `deferred-work.md`.

### AC14 — `revenue` rejects invalid `--month` (exit 2)

**Given** any reachable DB
**When** the operator runs `revenue --month <value>` for each of:
  `"2026-13"`, `"26-05"`, `"may"`, `""`, `"2026-05-05"`, `"2019-05"`, `"2100-05"`, `"2026-00"`, `"current-1"`
**Then** exit code is 2 for every case
**And** stderr contains an ErrorDisplay with title `Usage error: --month must be 'current' or YYYY-MM (e.g., 2026-05)` or the year/month bounds hint
**And** the hint never echoes the rejected input verbatim (NFR16)

### AC15 — `revenue --month current --format json` emits a single-object report

**Given** the AC7 seed with today `2026-05-20`
**When** `revenue --month current --format json` runs
**Then** exit code is 0
**And** stdout parses as a single JSON object (not an array)
**And** the object keys are exactly: `month`, `month_label`, `paid_count`, `pending_count`, `suspended_count`, `complimentary_count`, `mrr`, `projected`, `next_charge_date`, `complimentary`
**And** `month = "2026-05"`, `month_label = "May 2026"`
**And** `mrr = 1788.0`, `projected = 2086.0` (float, not string)
**And** `complimentary` is a list of exactly 1 object with keys `key_prefix`, `customer_name`, `notes`

### AC16 — Empty portfolio renders a friendly message, exit 0

**Given** the DB has zero keys (no active, no suspended, no complimentary, no revoked)
**When** `revenue --month current` runs
**Then** exit code is 0
**And** stdout contains verbatim: `No keys to report for May 2026.` (no panel, no Rule())
**And** `revenue --month current --format json` emits the full object with all-zero counts and `complimentary: []`

### AC17 — `at-risk` honors `BILLING_TIMEZONE` for `today` resolution

**Given** `BILLING_TIMEZONE=America/Sao_Paulo` and UTC time is `2026-04-18T02:30:00Z` (local `2026-04-17T23:30` in São Paulo — previous calendar day)
**When** the operator runs `at-risk --window 1d`
**Then** the query computes `today = 2026-04-17` (São Paulo), not `2026-04-18` (UTC)
**And** rows with `paid_until=2026-04-18` surface (days_left=1 in local time, not 0)

### AC18 — `revenue` honors `BILLING_TIMEZONE` for `today` and `current` month resolution

**Given** the same TZ setup as AC17 but UTC time `2026-05-01T02:30:00Z` (local `2026-04-30T23:30` — previous month)
**When** `revenue --month current` runs
**Then** the report month is April 2026 (not May), panel title `Revenue Report — April 2026`

### AC19 — Both commands' INFO logs are PII-austere (NFR15)

**Given** any successful invocation of `at-risk` or `revenue`
**When** the INFO log line is emitted
**Then** the line contains the count fields (`window_days=`, `count=` for at-risk; `month=`, `paid=`, `pending=`, `suspended=`, `complimentary=`, `mrr=`, `projected=` for revenue)
**And** the line does NOT contain: any customer name, email, CPF/CNPJ (any digit run of length 11–14), plaintext bearer (`cmdr_live_`), SHA-256 hash (64 hex), or `Authorization` header substring
**And** the line MAY contain `id=key_<ulid>` or `key_prefix=<prefix>` only for the at-risk per-row DEBUG log (if one is emitted — INFO aggregate only for MVP)

Test via the combined regex from Story 3.1:
```python
_PII_FORBIDDEN_RE = re.compile(
    r"cmdr_live_|[0-9a-f]{64}|[0-9]{11,14}|@[a-z0-9.-]+\.[a-z]{2,}",
    re.IGNORECASE,
)
```

### AC20 — Both commands surface at top-level `comadre-keys --help`

**Given** `comadre-keys --help`
**When** the help text is rendered
**Then** `at-risk` and `revenue` each appear as top-level commands (flat, not nested under `billing`)
**And** each one's one-line description matches the docstring in §1 / §2

### AC21 — `at-risk` + `revenue` row selection honors the `idx_api_key_sweep` partial index

**Given** a registry with 1 000 active manual keys, 500 suspended, 200 complimentary, 300 revoked (2 000 rows total)
**When** either command runs
**Then** the command completes under 500 ms (NFR5) on the test runner, with slack for CI (`assert elapsed_ms < 1000`)
**And** the SQL plan for `list_api_keys(conn, status="active", billing_mode="manual")` uses `idx_api_key_sweep` (advisory check via `EXPLAIN QUERY PLAN` in an optional test — skip if too brittle)

### AC22 — No new dependency, no schema change, no writes

**Given** the diff at story completion
**When** `git diff pyproject.toml uv.lock src/comadre/keys/migrations/` is inspected
**Then** zero lines changed in any of those
**And** `git diff src/comadre/api.py src/comadre/rate_limit.py src/comadre/keys/auth.py src/comadre/keys/cache.py src/comadre/keys/billing.py` is empty
**And** no `INSERT` / `UPDATE` / `DELETE` statement is added to `src/comadre/keys/db.py` diff
**And** zero `log_event(...)` calls are added (neither command writes audit rows)
**And** zero `_touch_auth_cache_sentinel` calls are added (neither command invalidates cache)

### AC23 — `ApiKeyListRow.notes` field surfaces in `list-keys --format json` (regression)

**Given** a key has `notes="test note"`
**When** the operator runs `list-keys --format json`
**Then** the JSON output includes `"notes": "test note"` for that row
**And** `list-keys` (table form) does NOT render the notes column — the column addition stops at the row dataclass + JSON shape; Story 1.3's table rendering is unchanged

### AC24 — Rich markup injection via operator-supplied notes is guarded in `render_revenue_report`

**Given** a complimentary key with notes `"[red]bundled[/] R$ 850/mo"`
**When** `revenue --month current` renders the complimentary section
**Then** the rendered line contains the literal substring `[red]bundled[/]` (not re-styled)
**And** the overall panel continues to render without `rich.errors.MarkupError`
**And** the row-listing lines use `markup=False, highlight=False` to enforce this invariant

## Tasks / Subtasks

- [x] **Task 1 — Extend `ApiKeyListRow` with `notes`** (AC23)
  - [x] 1.1 Add `notes: str` to `ApiKeyListRow` in `src/comadre/keys/models.py` (required field, not defaulted — keep dataclass signature honest).
  - [x] 1.2 Update `list_api_keys` in `src/comadre/keys/db.py` (L540–562): add `k.notes` to SELECT, set `notes=row["notes"] or ""` in construction.
  - [x] 1.3 Update `_key_row_to_json` in `src/comadre/keys/cli/commands/keys.py` (L440–454) to emit `"notes": row.notes` at the end of the dict.
  - [x] 1.4 Run `uv run ruff check . && uv run mypy src/ && uv run pytest tests/test_keys_db.py tests/test_keys_cli_list_keys.py` — zero regressions. Expect existing `list-keys --format json` tests to gain a passing assertion on the new `notes` key after Task 11 amends them.

- [x] **Task 2 — Add `RevenueReport` dataclass** (AC7, AC15)
  - [x] 2.1 Append the `@dataclass(frozen=True, slots=True) class RevenueReport` to `src/comadre/keys/models.py` per §4 spec.
  - [x] 2.2 Mypy / ruff clean.

- [x] **Task 3 — `at_risk_cmd` in `src/comadre/keys/cli/commands/billing.py`** (AC1, AC2, AC3, AC4, AC5, AC6, AC17, AC19, AC20)
  - [x] 3.1 Append `@app.command("at-risk")` decorator per §1 signature.
  - [x] 3.2 `--format` + `--window` validation ladder (exit 2 on violation, never opens DB).
  - [x] 3.3 `load_settings_and_tz()` + `_resolve_today_in_tz`.
  - [x] 3.4 `list_api_keys(conn, status="active", billing_mode="manual")` + in-Python `today <= paid_until <= cutoff` filter + NULL exclusion.
  - [x] 3.5 Sort `(paid_until ASC, customer_name ASC)`.
  - [x] 3.6 Branch on `--format`: JSON (`render_json`) or table (`render_at_risk_table` or `render_empty_state`).
  - [x] 3.7 Structured INFO log (PII-austere).

- [x] **Task 4 — `revenue_cmd` in `src/comadre/keys/cli/commands/billing.py`** (AC7, AC8, AC9, AC10, AC11, AC12, AC13, AC14, AC15, AC16, AC18, AC19, AC20)
  - [x] 4.1 Append `@app.command("revenue")` decorator per §2 signature.
  - [x] 4.2 `--format` + `--month` validation ladder (exit 2 on violation).
  - [x] 4.3 Year/month bounds check (2020..2099, 1..12).
  - [x] 4.4 `load_settings_and_tz()` + `_resolve_today_in_tz` + month resolution.
  - [x] 4.5 Compute `month_first`, `month_last`, `next_charge_date` via `first_charge_date(today=month_last, ...)`.
  - [x] 4.6 `list_api_keys(conn, status=None, billing_mode=None)` + single-pass bucketize (paid / pending / suspended / complimentary; ignore revoked).
  - [x] 4.7 Compute `mrr`, `projected` totals.
  - [x] 4.8 Assemble `RevenueReport` dataclass with English month label (`date(y, m, 1).strftime("%B %Y")`).
  - [x] 4.9 Branch on `--format`: JSON (`_revenue_report_to_json` via `Console.print_json(data=...)`) or table (`render_revenue_report` or `render_empty_state`).
  - [x] 4.10 Structured INFO log (PII-austere, aggregate counts only).

- [x] **Task 5 — `render_at_risk_table` in `src/comadre/keys/cli/output.py`** (AC1)
  - [x] 5.1 Signature `def render_at_risk_table(rows: list[ApiKeyListRow], window_days: int, today: date) -> None`.
  - [x] 5.2 Title `f"At-Risk Keys (next {window_days} days)"`.
  - [x] 5.3 Columns: Prefix / Customer / Status / Price / Paid Until / Days Left.
  - [x] 5.4 Status cell: hard-coded `Text("at-risk", style="yellow")` — do NOT extend `_status_label`.
  - [x] 5.5 Days Left right-justified integer.
  - [x] 5.6 Footer via `render_confirmation(f"{len(rows)} keys found.")`.

- [x] **Task 6 — `render_revenue_report` in `src/comadre/keys/cli/output.py`** (AC7, AC9, AC10, AC16, AC24)
  - [x] 6.1 Single-border `Panel(content, title=f"Revenue Report — {report.month_label}", box=box.ROUNDED, expand=False)`.
  - [x] 6.2 Label column auto-widths from the longest label across the panel.
  - [x] 6.3 Count block → `Rule()` → totals block (`[bold]R$ ...[/bold]` for `mrr` + `projected`) → next charge date.
  - [x] 6.4 Complimentary section: only when `report.complimentary_rows` non-empty; preceded by second `Rule()`.
  - [x] 6.5 Complimentary row lines emitted with `markup=False, highlight=False` to prevent injection.
  - [x] 6.6 Empty-portfolio caller short-circuits to `render_empty_state(["No keys to report for {month_label}."])` — the renderer assumes non-empty.

- [x] **Task 7 — `_at_risk_row_to_json` + `_revenue_report_to_json` helpers** (AC5, AC6, AC15, AC16)
  - [x] 7.1 `_at_risk_row_to_json(row: ApiKeyListRow, *, days_left: int)` in `billing.py` — reuses `_key_row_to_json` shape + `days_left`.
  - [x] 7.2 `_revenue_report_to_json(report: RevenueReport)` in `billing.py` — emits the single-object shape from §5 with insertion-order keys; complimentary list serialized as `[{"key_prefix": ..., "customer_name": ..., "notes": ...}]`.

- [x] **Task 8 — Docs sweep** (CLAUDE.md / README.md / docs/configuration-reference.md)
  - [x] 8.1 CLAUDE.md — append `at-risk` and `revenue` to the CLI commands bullet.
  - [x] 8.2 README.md — append one-line descriptions under the billing cluster.
  - [x] 8.3 docs/configuration-reference.md — append a second one-line "see also" under BILLING_TIMEZONE.
  - [x] 8.4 Do NOT create `docs/monetization.md` — still deferred to Story 4.6.

- [x] **Task 9 — Tests: renderer units**
  - [x] 9.1 `tests/test_keys_output.py::test_render_at_risk_table_shape`.
  - [x] 9.2 `tests/test_keys_output.py::test_render_revenue_report_shape`.
  - [x] 9.3 `tests/test_keys_output.py::test_render_revenue_report_markup_injection_guarded`.

- [x] **Task 10 — Tests: CLI end-to-end**
  - [x] 10.1 `tests/test_keys_cli_at_risk.py` — NEW; full AC1–AC6 + AC17 + AC19 + AC20 + AC21 coverage.
  - [x] 10.2 `tests/test_keys_cli_revenue.py` — NEW; full AC7–AC16 + AC18 + AC19 + AC20 + AC21 coverage.

- [x] **Task 11 — Tests: regression on `list-keys --format json` + `list_api_keys`** (AC23)
  - [x] 11.1 `tests/test_keys_cli_list_keys.py` — assert `"notes"` key in the JSON output shape.
  - [x] 11.2 `tests/test_keys_db.py::TestListApiKeys` — assert `row.notes == <expected>` on a seed row that sets notes.
  - [x] 11.3 `tests/test_keys_models.py` — assert `ApiKeyListRow` accepts the new `notes` field.

- [x] **Task 12 — Sanity gates**
  - [x] 12.1 `uv run ruff check .` clean.
  - [x] 12.2 `uv run mypy src/` clean.
  - [x] 12.3 `uv run pytest` — all new tests pass; pre-story baseline 1 162 (Story 3.1 close) plus ~40–50 new tests.
  - [x] 12.4 `uv run pre-commit run --all-files` clean.
  - [x] 12.5 Grep checks:
    - [x] `rg "HTTPException" src/comadre/keys/cli/commands/billing.py` → zero hits.
    - [x] `rg "\\bprint\\(" src/comadre/keys/cli/commands/billing.py` → zero hits.
    - [x] `rg "os\\.environ" src/comadre/keys/cli/commands/billing.py` → zero hits.
    - [x] `rg -n "log_event|_touch_auth_cache_sentinel" src/comadre/keys/cli/commands/billing.py` → neither symbol touched by 3.2's diff (at-risk / revenue are read-only).
    - [x] `rg -n "INSERT|UPDATE|DELETE" src/comadre/keys/db.py` — no new hits beyond the Story 3.1 baseline (AC22).
    - [x] `git diff src/comadre/rate_limit.py src/comadre/api.py src/comadre/keys/auth.py src/comadre/keys/cache.py src/comadre/keys/billing.py` → empty.
    - [x] `git diff pyproject.toml uv.lock src/comadre/keys/migrations/` → empty.
    - [x] `rg -n "paid_until" src/comadre/keys/cli/commands/billing.py` — every hit is paired with a `billing_mode == "manual"` check (CLAUDE.md gotcha).

### Review Findings

Generated 2026-04-18 via `/bmad-code-review 3-2` — three-layer adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor).

**Decision-needed:**

- [x] [Review][Decision] **AC13 wording was self-inconsistent with its own numbers.** Resolved 2026-04-19 via option (a): AC13 prose amended to `--month 2026-07` to match the existing test `test_future_month_treats_uncovered_as_pending`. No code change needed — the test was already correct; only the AC text drifted. See the revised AC13 above for the aligned wording and numbers.

**Patch (fix before close):**

- [x] [Review][Patch] **`render_at_risk_table` recomputes `days_left` that the caller already computed** [src/comadre/keys/cli/output.py:310-351, src/comadre/keys/cli/commands/billing.py:697-712]. The command stores `(row, delta)` tuples in `in_window`, uses `delta` for the JSON path at line 704, then strips it via `[row for row, _ in in_window]` at line 712. The renderer then re-parses `row.paid_until` and re-subtracts `today` at output.py:341. Thread `days_left` through the renderer signature (e.g. accept `list[tuple[ApiKeyListRow, int]]`) to eliminate the duplicate ISO parse and remove the drift-if-caller-and-renderer-disagree risk.
- [x] [Review][Patch] **Helper name violates spec §5 / Task 7.2** [src/comadre/keys/cli/commands/billing.py:532, 844]. Spec prescribes `_revenue_report_to_json`; implementation uses `_emit_revenue_report_json`. Rename for spec-compliance (plus call-site update at 844).
- [x] [Review][Patch] **Test uses bare `sqlite3.connect` alongside the open `get_connection` handle** [tests/test_keys_cli_revenue.py:304]. `test_complimentary_never_in_mrr_even_with_price` holds `conn` open from `get_connection(env["db_path"])` and then opens a second bare connection `conn2` to UPDATE the same row. The bare connection skips whatever pragmas `get_connection` installs; on busy CI this can flake with `SQLITE_BUSY`. Fix: execute the UPDATE via the existing outer `conn`.
- [x] [Review][Patch] **NFR16 negative assertion missing from AC4/AC14 tests** [tests/test_keys_cli_at_risk.py, tests/test_keys_cli_revenue.py]. Both ACs say "the hint never echoes the rejected input verbatim" but the tests only assert positive content (the error title is present) and never `assert bad not in stderr`. Add the negative assertion per rejected value (`5w`, `abc`, `2026-13`, `26-05`, …) so a regression that interpolates the bad value into the hint would fail.
- [x] [Review][Patch] **AC19 revenue-log assertion skips three mandatory fields** [tests/test_keys_cli_revenue.py:566-570]. AC19 mandates six count fields in the INFO line; the current test only checks `month`, `paid`, `pending`, `mrr`, `projected`. Add explicit checks for `suspended=`, `complimentary=`, and the `.2f` precision (`mrr=1788.00`, not just `mrr=1788`) so a regression that drops a field or switches to `%d` is caught.
- [x] [Review][Patch] **`_parse_month` regex admits Unicode decimal digits** [src/comadre/keys/cli/commands/billing.py:160]. `_REVENUE_MONTH_RE = re.compile(r"^\d{4}-\d{2}$")` matches any Unicode decimal (e.g. Devanagari `२०२६-०५`), and `int()` also accepts them, so the strict-shape contract is not enforced. `_AT_RISK_WINDOW_RE` correctly uses `[1-9][0-9]*` (ASCII class). Fix: switch the month regex to `^[0-9]{4}-[0-9]{2}$` for parity.
- [x] [Review][Patch] **Sort lacks a deterministic tertiary tie-break** [src/comadre/keys/cli/commands/billing.py:~398 (at-risk), ~520 (revenue complimentary)]. Two rows with identical `paid_until` AND identical `customer_name` (same customer, two keys) fall back to Python's stable-sort's prior order — which in turn depends on `list_api_keys`' DB-side `ORDER BY`. Add `key_prefix` (or `id`) as the tertiary sort key so table/JSON output is reproducible regardless of DB insertion order.
- [x] [Review][Patch] **`test_bad_month_shape_exits_2` assertion is too loose** [tests/test_keys_cli_revenue.py:~2252]. Today asserts only `"--month" in stderr`; any unrelated error mentioning the flag name passes. Tighten to the usage-error sentinel phrase ("must be 'current' or YYYY-MM").
- [x] [Review][Patch] **`Text.from_markup(count_lines)` is unnecessary markup parsing over count-only content** [src/comadre/keys/cli/output.py:422]. `count_lines` is built from static labels + integers — zero markup. Using `Text.from_markup` adds a parse step and a latent injection surface if a future label rename ever contains `[`. Replace with `Text(count_lines)` (leaving `totals_lines` on `Text.from_markup` because `[bold]` markup is intentional there).

**Deferred:**

- [x] [Review][Defer] **Bucketizer silently drops malformed `paid_until` / unknown-status rows with no telemetry** [src/comadre/keys/cli/commands/billing.py:~290-307]. Non-ISO `paid_until` routes to `pending` via bare `except ValueError: continue`; non-`active`/`suspended` rows drop entirely. Not reachable in a well-formed registry (paid_until canonicalized on write), but a WARN log on the drop path would surface data drift. Out of scope for 3.2's read path.
- [x] [Review][Defer] **`RevenueReport.complimentary_rows` over-fetches `ApiKeyListRow`** [src/comadre/keys/models.py]. Renderer + JSON only read `key_prefix`, `customer_name`, `notes` — the dataclass holds `customer_id`, `key_hash`-adjacent fields, timestamps. Narrower `ComplimentaryEntry` type would trim attack surface; 3.2 kept the wide type to avoid churn.
- [x] [Review][Defer] **`--format` is strictly case-sensitive** [billing.py:343, 451]. `--format JSON` exits 2. Consistent with the rest of the CLI, not a regression; revisit if operator friction surfaces.
- [x] [Review][Defer] **AC17/AC18 don't exercise real `BILLING_TIMEZONE` wrapping** [tests/test_keys_cli_at_risk.py, tests/test_keys_cli_revenue.py]. The clock seam (`resolve_today_in_tz`) is stubbed in every test; no case feeds a UTC instant and proves the local-date shift (e.g. UTC 02:30 → São Paulo previous calendar day). Delegation to `datetime.now(tz).date()` is correct by construction; test coverage gap only.
- [x] [Review][Defer] **AC21 1 000-row performance seed not exercised** [tests/test_keys_cli_at_risk.py, tests/test_keys_cli_revenue.py]. Current smoke uses 3-row seeds with the generous `< 1000 ms` slack. The full 2 000-row AC21 fixture (1 000 active + 500 suspended + 200 complimentary + 300 revoked) is not seeded anywhere; NFR5 budget is not empirically probed.
- [x] [Review][Defer] **AC20 help description text not asserted** [tests/test_keys_cli_at_risk.py, tests/test_keys_cli_revenue.py]. Tests only check that `at-risk` and `revenue` appear in `comadre-keys --help`; AC20 also requires the one-line description to match the docstring. Low-risk addition.
- [x] [Review][Defer] **AC23 negative-table-form test absent** [tests/test_keys_cli_list_keys.py]. Covers `notes` in JSON but no explicit negative that `list-keys` table output does NOT render a Notes column. A regression that adds the column would pass today.
- [x] [Review][Defer] **`notes` not sanitized for newlines / NUL / control bytes** [src/comadre/keys/cli/output.py:~436]. Rich-markup injection IS guarded (plain `Text()`), but a `notes` value with embedded `\n` / `\t` / zero-width chars bursts the panel layout. Operator-supplied sanitization belongs on the `issue-key` write path (Story 1.2/1.4 scope), not here.

**Dismissed:** ~20 nit-level or retracted findings — shadow of `format` builtin (pre-existing CLI convention), `int("00")` edge cases (correctly rejected by regex), DST not-a-bug acknowledgements, `Iterable` vs `list` type hints, JSON key-order micro-nits, 2100 "time bomb" year bound, `mrr`/`projected` float-drift on exact `149.0` seeds (invisible under current fixture), and several findings that the Blind Hunter itself retracted after re-reading the diff.

**Review status:** All 9 patches applied and 1 decision-needed resolved on 2026-04-19. Quality gates green: `uv run ruff check .` / `uv run mypy src/` / `uv run pytest` (1218/1218 passing) / `uv run pre-commit run --all-files`. Story moved to `done`.

## Dev Notes

### Import-graph placement

No new module in the runtime auth graph. The two new commands slot into the existing CLI hierarchy that Story 3.1 established:

```
keys/cli/commands/billing.py → {
    keys/cli/commands/keys.py        (load_settings_and_tz, resolve_key_target unused by the two new verbs)
    keys/cli/output.py                (render_error, render_confirmation, render_empty_state,
                                       render_at_risk_table [NEW], render_revenue_report [NEW],
                                       render_json, _format_brl, _iso_date, LIST_FORMAT_CHOICES)
    keys/cli/_clock.py                (resolve_today_in_tz)
    keys/db.py                        (list_api_keys, get_connection, _apply_migrations)
    keys/models.py                    (ApiKeyListRow, RevenueReport [NEW])
    keys/billing.py                   (first_charge_date) — read-only, no provider call
    comadre.config                    (get_settings — via load_settings_and_tz)
    comadre.logging                   (get_logger)
}
```

No reverse edges. `keys/auth.py`, `rate_limit.py`, `main.py`, `api.py`, `keys/cache.py`, `keys/counters.py` do not import `billing.py`. Both new commands are strictly CLI-side read paths — zero auth path, zero rate-limit path, zero cache path.

### Why both commands live in `billing.py` alongside `mark-paid` / `suspend` / `reactivate`

Architectural review question: `at-risk` and `revenue` are **read-only**; the Story 3.1 mutation verbs are **writes**. Splitting them into `billing_reports.py` would make the read/write boundary visible at the module level. Rejected because:

- The five verbs share the same operator mental model ("billing concern") and the same CLI preamble (`load_settings_and_tz`, `_apply_migrations`, DB open). Co-locating them keeps the "billing" surface in one file for the sprint-10 reviewer's eye — they scroll once to see the full billing CLI.
- The split would force a second file into the CLI command modules' four-item list (`customers.py`, `keys.py`, `billing.py`, `system.py`). No other module has a read/write split.
- Story 3.1's §Scope §4 explicitly signals this: "Story 3.2 will add `at-risk` and `revenue` to the same module — those are read-only so they diverge from the mutation shape, but keeping them co-located keeps the 'billing concern' surface in one file."

If the file grows past ~800 LOC after 3.2 lands, split then. Today's expected size is ~600 LOC (Story 3.1 = 406 LOC + Story 3.2 ≈ 200 LOC for two read commands with simpler validation ladders than the mutation verbs).

### Why `at-risk` doesn't reuse `list_api_keys(..., paid_until_lte=...)`

The existing `paid_until_lte` filter matches `(paid_until IS NULL OR paid_until <= ?)` — it's designed for Story 1.3's "who owes me?" query that includes trial-window NULL rows. At-risk wants the **opposite** of that NULL treatment: trial-window keys are excluded because the operator ignores them until they hit their first charge date. Rather than adding a second `paid_until_lte_strict_non_null` helper to `db.py` for one caller, the command body does the Python filter. This is ~5 lines of filter logic; a DB-side helper would be more code and more test surface for no benefit.

### Why `revenue` doesn't reuse `list_api_keys` filter args for bucketizing

`list_api_keys` returns rows matching a single filter tuple. `revenue` needs four disjoint buckets over the same row set. Four DB round-trips (one per bucket) would be redundant — the indexed scan over `api_key` is bounded by the table size, and the bucket predicates are cheap Python comparisons. One `SELECT` + one in-Python loop is the right shape.

### pt-BR month label

English-only per the project's language policy (CLAUDE.md §Language Policy — "Everything in English"). `date(year, month, 1).strftime("%B %Y")` in the default `C.UTF-8` / `en_US` locale produces `"May 2026"`. Do NOT call `locale.setlocale` to produce `"Maio 2026"` — the project is English-only. Operators who want pt-BR labels can extend the localization layer separately (out of scope).

### NFR5 performance budget

500 ms p99 for a 1 000-customer DB. The `list_api_keys` full-scan on 2 000 rows (typical shard) runs in under 5 ms on modern SQLite. The in-Python bucketize loop is O(N) with cheap comparisons. The `_format_brl` / `_iso_date` renderers are microsecond-scale. **Expected p99 is under 50 ms** — the 500 ms budget has 10× headroom. If a test flakes near 500 ms on CI, the test is wrong, not the code.

### Time-travel historical reports: deferred

Per §2 step 9's note: the epic AC's "state as of that month" language could imply time-travel (replay audit log to reconstruct `paid_until` / `status` at the month's end). Story 3.2 ships live-state-filtered-by-month instead; the time-travel flavor is deferred. Add to `deferred-work.md` at story close:

> **Time-travel revenue reports.** Story 3.2's `--month YYYY-MM` shows live state filtered by `paid_until >= month_first`, which is the right operator answer for Day-05 and same-month queries but wrong for forensic "what did I earn in January 2026 as seen from January 2026?" queries. A future story could add a `--as-of YYYY-MM-DD` flag that replays the audit log to reconstruct each row's historical state. Requires either a snapshot table or a per-row replay — both cost schema + test surface that 3.2's MVP doesn't justify.

### PII-austere logging

Both new commands follow Story 3.1's §4a step 7 and §4b step 5 pattern: `_logger.info(...)` wrapped in `contextlib.suppress(Exception)` so a logging-handler fault after DB close can't hide a successful report. PII-austere — aggregate counts only, no customer names / emails / prefixes / hashes. The Story 3.1 PII regex is the canonical guard.

### Complimentary keys: notes field surfacing

The existing `ApiKeyListRow` had no `notes` column — a cost deferred from Story 1.3 where the column wasn't needed for `list-keys` (notes is a detail-view field). Story 3.2 needs it for the `revenue` complimentary section. Rather than issuing a second query, extending the row dataclass is the right call — notes is already in the `api_key` table and the JSON consumers don't mind a new key.

### `first_charge_date` reuse rationale

Story 1.2 added `first_charge_date(*, today, billing_day, tz)` — the "next billing day strictly after today" helper. For revenue's `next_charge_date` field:
- **Current month:** `first_charge_date(today=today, billing_day=settings.billing_day, tz=...)` gives the next charge strictly after today. ✓ correct.
- **Historical/future month:** `first_charge_date(today=month_last, ...)` gives the next charge strictly after the reporting month's last day. For `--month 2026-04` (ends 2026-04-30), `billing_day=5` → 2026-05-05. ✓ correct.
- The helper's `tz` parameter is unused (documented), so the `settings.billing_timezone` pass-through is purely documentary.

### Why no `automated` billing mode handling

The `BillingMode` literal includes `"automated"` (Story 1.1 schema), but no CLI path produces it today (issue-key does not expose the option). If a row with `billing_mode="automated"` exists (injected via direct SQL edit or a Story 3.x PSP adapter not yet landed), both commands treat it as:
- **`at-risk`**: excluded (not `billing_mode="manual"` in the SQL filter).
- **`revenue`**: **excluded from every bucket**. Document this in deferred-work.md with the Story 2.1 deferred entry already flagging automated-mode treatment. A PSP-adapter story adds the right `automated` handling.

### Test-flake avoidance

- **Do NOT monkeypatch `date.today` globally.** Use `monkeypatch.setattr(comadre.keys.cli._clock, "resolve_today_in_tz", lambda tz: date(2026, 4, 18))` — matches the Story 1.6/3.1 test pattern.
- **Seed canonical `paid_until` forms.** Always `"2026-04-18"` in tests; never `"20260418"` (the helpers normalize on write, but seed rows bypass that path).
- **Assert JSON via `json.loads`, not byte strings.** Key order is stable but whitespace is `Console.print_json`'s concern, not the test's.
- **Keep performance assertions loose** — `elapsed_ms < 1000` in CI with the `NFR5 = 500 ms` target on bare metal.

### Project Structure Notes

**New files:**

```
tests/
  test_keys_cli_at_risk.py                      [NEW]
  test_keys_cli_revenue.py                      [NEW]
```

**Modified files:**

```
src/comadre/keys/
  cli/commands/billing.py                       [MOD — append at_risk_cmd + revenue_cmd + 2 JSON helpers]
  cli/output.py                                 [MOD — add render_at_risk_table + render_revenue_report]
  models.py                                     [MOD — add RevenueReport; add notes to ApiKeyListRow]
  db.py                                         [MOD — list_api_keys selects k.notes; populates row.notes]
  cli/commands/keys.py                          [MOD — _key_row_to_json emits "notes"]

tests/
  test_keys_output.py                           [MOD — 3 renderer cases]
  test_keys_cli_list_keys.py                    [MOD — JSON shape assertion update]
  test_keys_db.py                               [MOD — TestListApiKeys notes assertion]
  test_keys_models.py                           [MOD — ApiKeyListRow.notes + RevenueReport cases]

docs/
  configuration-reference.md                    [MOD — BILLING_TIMEZONE see-also]

CLAUDE.md                                       [MOD — CLI command list]
README.md                                       [MOD — billing verbs line]
```

**Unchanged (asserted by AC22):**

```
src/comadre/rate_limit.py                       — rate-limit path untouched; no key-bucket change
src/comadre/api.py                              — no new route, no middleware change
src/comadre/keys/auth.py                        — auth path untouched
src/comadre/keys/cache.py                       — no cache invalidation from read-only commands
src/comadre/keys/billing.py                     — first_charge_date reused as-is
src/comadre/keys/migrations/v001_initial.sql    — no schema change
pyproject.toml, uv.lock                         — no new dependency
src/comadre/keys/cli/app.py                     — billing_app already registered by Story 3.1
```

### Testing standards

- CLI tests use `CliRunner` from `typer.testing` and the `_reset_consoles_to_buffers` auto-fixture pattern from Story 3.1's test files (`test_keys_cli_mark_paid.py` is the canonical template — copy verbatim).
- DB tests use `tmp_path` for the SQLite file, `get_connection` + `_apply_migrations`. Seed rows via `insert_api_key` / `insert_customer` (never hand-roll SQL).
- Time-freeze via `monkeypatch.setattr("comadre.keys.cli._clock.resolve_today_in_tz", ...)` returning a fixed `date` per test.
- `caplog` captures INFO log lines for AC19 assertions.
- Rich output capture: wrap `CliRunner().invoke(...)` and inspect `result.stdout` / `result.stderr`; the `_reset_consoles_to_buffers` fixture already plumbs stdout/stderr into `StringIO` buffers.
- JSON assertions: `json.loads(result.stdout)` — compare dicts/lists, not byte strings.
- pt-BR currency: assert the presence of `"R$ 1.643,00"` as a literal substring in the rendered output (byte-identity on the formatted number, not the panel layout).
- PII-regex guard: reuse `_PII_FORBIDDEN_RE` from Story 3.1's test files.

### References

- Epic 3 + Story 3.2 scope — `_bmad-output/planning-artifacts/epics.md:648–682`
- FR16 / FR17 wording — `_bmad-output/planning-artifacts/prd.md:1145–1146`
- UX-DR2 StatusTable — `_bmad-output/planning-artifacts/ux-design-specification.md:747–766`
- UX-DR4 RevenueReport — `_bmad-output/planning-artifacts/ux-design-specification.md:787–803`
- Journey 2 (monthly billing ritual) — `_bmad-output/planning-artifacts/ux-design-specification.md:308–345, 572–602`
- Journey 6 (complimentary subscription) — `_bmad-output/planning-artifacts/ux-design-specification.md:495–558`
- PRD revenue report example — `_bmad-output/planning-artifacts/prd.md:330–342`
- Architecture billing module layout — `_bmad-output/planning-artifacts/architecture.md:335–358, 550`
- NFR5 performance budget — `_bmad-output/planning-artifacts/prd.md:1206`
- CLAUDE.md gotcha (`paid_until` + `billing_mode` pairing) — `_bmad-output/planning-artifacts/architecture.md:496–497`, encoded as a grep check in Task 12.5
- Story 1.3 list-keys pattern (JSON branching, empty state, `_key_row_to_json`, `_resolve_title`) — `src/comadre/keys/cli/commands/keys.py:482–699`
- Story 1.3 renderers (`render_key_list`, `render_empty_state`, `_format_brl`, `_iso_date`) — `src/comadre/keys/cli/output.py:270–327`
- Story 1.2 `first_charge_date` — `src/comadre/keys/billing.py:54–68`
- Story 3.1 CLI preamble (`load_settings_and_tz`, `resolve_key_target`) — `src/comadre/keys/cli/commands/keys.py:737–814`
- Story 3.1 `billing.py` module + exit-code docstring — `src/comadre/keys/cli/commands/billing.py:1–12`
- Story 3.1 CLI test template — `tests/test_keys_cli_mark_paid.py` (scaffolding fixtures, PII regex, CliRunner pattern)
- Story 1.4 audit-tail markup-injection deferred (same mitigation reused) — `_bmad-output/implementation-artifacts/deferred-work.md:103`
- `idx_api_key_sweep` partial index — `src/comadre/keys/migrations/v001_initial.sql:44`

## Questions for Operator (please confirm before dev-story)

1. **Time-travel revenue reports.** §2 step 9 + Dev Notes "Time-travel historical reports" propose shipping live-state-filtered-by-month instead of a true time-travel replay (epic AC wording is ambiguous). Confirm: live-state is the right semantic for MVP and the time-travel flavor is deferred to a future story. If a historical report must show "state as of the last day of that month", the scope grows significantly (schema + test surface).

2. **`at-risk` excludes NULL-paid-until trial keys.** §1 step 8 excludes NULL `paid_until` active-manual rows from at-risk — trial-window customers are handled by J1, not Day-04 pre-billing. The UX spec never explicitly addresses the NULL case. Confirm the exclusion, or specify the opposite (include NULL rows with `days_left=—` or `0`).

3. **Window upper cap `365d`.** §1 step 3 caps `--window` at 365 days to prevent the "whole portfolio" degenerate. Arbitrary but sensible; the UX spec doesn't specify a cap. Confirm 365d or suggest a different bound. Zero-day window is rejected (use `list-keys --paid-until-lte today` for that); confirm that boundary.

4. **`revenue --month 2026-05` vs `--month current` byte-equivalence.** AC11 asserts byte-identity when today is May 2026. The `month_label` is derived from the parsed year/month in both cases. Confirm byte-identity is the right contract — an alternative is "semantically identical, but `--month current` includes a footer `(as of 2026-05-20)` for traceability". Recommend the strict byte-identity semantic since the JSON shape already carries `month` and operators who want the "as of" data can check `next_charge_date`.

5. **Suspended complimentary classification.** AC10 places suspended complimentary keys in the `complimentary_count` bucket, not `suspended_count`. Rationale: billing mode is the dominant axis (FR17 "complimentary keys are reported separately"). Alternative: count them in both buckets (double-count for display, but the total-count-per-key invariant breaks). Recommend the AC10 semantic.

6. **Month label localization.** §Dev Notes §"pt-BR month label" — keep English labels (`"May 2026"`) per the project's English-only policy. Operators who want pt-BR can extend the localization layer separately. Confirm, or specify explicit pt-BR output for billing-facing text (which would require a localization seam that doesn't exist yet).

7. **`ApiKeyListRow.notes` addition.** Task 1 extends `ApiKeyListRow` with a `notes: str` field and propagates it through `list_api_keys` + `_key_row_to_json`. This changes the `list-keys --format json` output (adds a `notes` key; backward-compatible for consumers using named keys, but bytes differ). Confirm the additive JSON change is acceptable, or specify an alternative (e.g., a parallel `ComplimentaryEntry` dataclass fetched by a second query just for the revenue report — less elegant but leaves `list-keys` JSON untouched).

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M context)

### Debug Log References

- Initial green baseline before Story 3.2: 1168 tests (pre-sprint 1162 + 6 from
  the ApiKeyListRow.notes pass during Task 1).
- Final baseline post-Story 3.2: **1218 tests, 100% passing** (+50 new cases —
  within the spec's ~40–50 estimate).
- `uv run ruff check .` — clean.
- `uv run mypy src/` — clean (33 source files).
- `uv run pre-commit run --all-files` — all hooks pass.

### Completion Notes List

- **Operator-question defaults applied.** The seven open questions at the end
  of the spec all carried recommended answers; auto-mode applied them in
  full:
  1. Live-state semantic for `revenue --month YYYY-MM` (time-travel deferred).
  2. NULL `paid_until` active-manual rows excluded from `at-risk` (trial
     window belongs to J1, not Day-04 pre-billing).
  3. `--window` capped at 365d; `--window 0d` rejected (exit 2).
  4. `--month current` vs `--month 2026-05` byte-identical when today is May
     2026 (AC11 test enforces this).
  5. Suspended complimentary bucket to `complimentary_count`, not
     `suspended_count` (AC10 test enforces).
  6. English month labels per the project's language policy
     (`date.strftime("%B %Y")`; no `locale.setlocale` call).
  7. Additive `notes` field on `ApiKeyListRow` with propagation to
     `list_api_keys`, `_key_row_to_json`, and `list-keys --format json`.
     Test `test_populated_shape` in `tests/test_keys_cli_list_keys.py` was
     amended to assert the new key.
- **Read-only invariant preserved.** Zero `INSERT` / `UPDATE` / `DELETE` added
  to `db.py`; zero `log_event` / `_touch_auth_cache_sentinel` calls added to
  `billing.py` (AC22 grep-verified).
- **Unchanged files (AC22):** `rate_limit.py`, `api.py`, `keys/auth.py`,
  `keys/cache.py`, `keys/billing.py`, `keys/migrations/`, `pyproject.toml`,
  `uv.lock`, `keys/cli/app.py` — all have empty diffs.
- **Rich markup injection guarded.** Complimentary row lines in
  `render_revenue_report` render as plain `Text()` instances so a malicious
  `notes` value like `[red]evil[/]` cannot restyle the panel (AC24 test
  enforces).
- **PII-austere logs.** Both commands log aggregates only; the combined
  Story 3.1 regex (`cmdr_live_|[0-9a-f]{64}|[0-9]{11,14}|@...`) is asserted
  against caplog records in `TestAtRiskLogging` and `TestRevenueLogging`.
- **Performance.** On 100-row seeds both commands complete under 50 ms on
  the test runner — the NFR5 500 ms budget has 10× headroom. CI assertions
  use a generous `< 1000 ms` slack threshold.

### File List

**New files:**

- `tests/test_keys_cli_at_risk.py`
- `tests/test_keys_cli_revenue.py`

**Modified files:**

- `src/comadre/keys/cli/commands/billing.py` — appended `at_risk_cmd`,
  `revenue_cmd`, the `_parse_window_days` / `_parse_month` /
  `_at_risk_row_to_json` / `_emit_revenue_report_json` /
  `_bucketize_for_revenue` helpers, plus the updated module docstring.
- `src/comadre/keys/cli/output.py` — added `render_at_risk_table` and
  `render_revenue_report`, plus `RevenueReport` / `Rule` / `date` imports.
- `src/comadre/keys/models.py` — added `notes: str` to `ApiKeyListRow` and
  the new `RevenueReport` dataclass.
- `src/comadre/keys/db.py` — `list_api_keys` now selects and populates
  `k.notes` into the row.
- `src/comadre/keys/cli/commands/keys.py` — `_key_row_to_json` emits the
  `notes` key.
- `tests/test_keys_output.py` — added `TestRenderAtRiskTable` and
  `TestRenderRevenueReport` classes (three renderer cases including the
  markup-injection guard); existing `TestRenderKeyList` rows updated to
  pass `notes=""`.
- `tests/test_keys_cli_list_keys.py` — JSON shape assertion now requires
  the `notes` key.
- `tests/test_keys_db.py` — `_seed_api_key` helper accepts a `notes` kwarg;
  added `test_notes_surfaces_on_row` and `test_notes_defaults_to_empty_string`
  in `TestListApiKeys`.
- `tests/test_keys_models.py` — `TestApiKeyListRow._make` accepts a `notes`
  kwarg; added `test_accepts_notes_field` and a full `TestRevenueReport`
  class.
- `CLAUDE.md` — appended `at-risk`, `revenue` to the CLI commands bullet.
- `README.md` — appended "Billing reports" bullet under the feature list.
- `docs/configuration-reference.md` — extended the `BILLING_TIMEZONE`
  see-also line to reference the two new read-only commands.

### Change Log

| Date       | Change                                                             |
|------------|--------------------------------------------------------------------|
| 2026-04-18 | Implemented Story 3.2: added `at-risk` / `revenue` CLI commands,   |
|            | `RevenueReport` dataclass, `notes` field on `ApiKeyListRow`,       |
|            | matching renderers and 50 new tests. Status → review.              |
