# Story 3.3: Automated Suspension Sweep & Cron

Status: done

> **Scope note — FR18 / FR31 / FR43.** Epic 3 closes its billing loop with the daily cron that converts Day-06 expirations into automatic suspensions. Story 3.1 shipped the hand-operated `suspend` / `mark-paid` / `reactivate` verbs; Story 3.2 shipped the read-only `at-risk` / `revenue` previews; Story 3.3 ships the **zero-touch enforcement** that runs while the operator sleeps. The sweep is a single `UPDATE` over `api_key` gated by `billing_mode='manual' AND paid_until < today AND status='active'`, followed by one `suspend_key` audit row per newly-suspended key plus one `cron_suspend` summary row that carries the per-run timestamp so Story 3.4's `health` command can answer FR43's "when did the sweep last complete?" query even on zero-row days. **Complimentary keys are never touched** (`billing_mode='manual'` predicate). **The Fernet key is never read** — no encrypted column is involved. **The UPDATE must not block concurrent auth-path reads** (NFR23) — WAL mode is the existing invariant that guarantees this. **No rate-limit path change. No auth cache code change — the sentinel touch after commit propagates the status flip within the 60 s bound already documented by Story 2.1.**

## Story

As an operator,
I want the system to auto-suspend non-payers once a day without my intervention,
so that billing enforcement happens reliably at 00:30 São Paulo time while I'm asleep, the customer wakes up to a 401 instead of me remembering to type `suspend` for each of 20 keys on Day 06, and the Day-05 ritual I already close in five minutes stays five minutes — not five minutes plus a morning of cleanup.

**Covers FRs:** FR18 (daily auto-suspend at operator-TZ time), FR31 (audit row per cron-initiated suspension/reactivation event), FR43 (last successful sweep timestamp queryable).
**NFRs:** NFR3 (sweep completes <1 s for 1 000 active keys), NFR15 (PII-austere INFO logs), NFR16 (error hint never echoes invalid operator input), NFR23 (cron UPDATE does not block concurrent auth-path reads — WAL invariant).
**UX-DRs:** UX-DR7 (ConfirmationLine — sweep's one-line stdout when a human triggers it ad-hoc), UX-DR10 (exit-code contract: 0 success including zero-row sweep, 5 DB error, 6 configuration error).
**Epic:** 3 — Billing & Revenue Operations. Third and final runtime story in Epic 3; Story 3.4 adds the `health` read surface that consumes this story's `cron_suspend` timestamp.

## Builds on

- **Story 3.1 — `suspend_key` helper + audit action name** — `src/comadre/keys/db.py:1242-1302` is the canonical single-key suspend helper. Story 3.1's §2 "Why match the cron sweep's action name" explicitly reserved `action='suspend_key'` so `show --audit-tail` renders manual and cron suspensions identically; the operator distinguishes them via the `actor` column (`cli:galvani` vs `cron:suspension-sweep`). Story 3.3's per-row audit rows **MUST** use `action='suspend_key'` — any other action name breaks the audit-tail render and defeats the point of 3.1's naming decision. The cron sweep does NOT call `suspend_key(conn, key_id, ...)` per row — that would do one SELECT + one UPDATE per key, blowing the NFR3 <1 s budget on 1 000 keys. Instead, Story 3.3 adds a new bulk helper `run_suspension_sweep(conn, today=..., actor=...)` that does a single `UPDATE api_key` + bulk audit row insertion in one transaction.
- **Story 3.1 — `_touch_auth_cache_sentinel` pattern** — every mutation helper in `db.py` calls `_touch_auth_cache_sentinel(conn)` after `with conn:` commits. Story 3.3's `run_suspension_sweep` follows the same pattern so suspended keys start returning 401 on the next API request (not 60 s later). The sentinel touch is a single filesystem `touch` regardless of row count, so the cost is amortized across the bulk UPDATE.
- **Story 3.1 — CLI exit-code contract** — `src/comadre/keys/cli/commands/billing.py:4-17` enumerates 0 / 2 / 3 / 5 / 6. Story 3.3's `suspend-sweep` CLI never emits 2 or 3 (no operator-supplied key identifier, no parseable flags beyond `--help`); it emits only 0, 5, 6. The scope of each code matches 3.1 verbatim — `system.py`'s module docstring already covers `cache-status`'s 0/2/6 trio and will extend cleanly.
- **Story 3.2 — `list_api_keys` read-path + `idx_api_key_sweep` partial index** — `src/comadre/keys/migrations/v001_initial.sql:44` defines `CREATE INDEX idx_api_key_sweep ON api_key(billing_mode, paid_until) WHERE status = 'active'`. The index is **exactly** tuned for the sweep's `WHERE billing_mode='manual' AND paid_until < ? AND status='active'` predicate. `EXPLAIN QUERY PLAN` must show `USING INDEX idx_api_key_sweep` — if it doesn't, the sweep's <1 s budget on 1K keys is at risk. This is asserted by AC9.
- **Story 3.2 — `ManualBillingProvider.is_payment_current`** — `src/comadre/keys/billing.py:35-43` treats `paid_until IS NULL` as "not paid" (trial window). The cron sweep's predicate `paid_until < today` **does not** match `NULL < today` in SQLite (NULL-propagating comparison returns NULL, not true), so trial-window keys are **not** swept — they belong to the J1 first-sale flow, the same semantic Story 3.2's `at-risk` command encodes. Document this alongside the command body.
- **Story 2.1 — `cron:suspension-sweep` actor convention** — `_bmad-output/planning-artifacts/architecture.md:325` names the actor format. `src/comadre/keys/audit.py:50-61` defines `get_cli_actor() → 'cli:<unix-user>'` for operator commands; the sweep hardcodes `'cron:suspension-sweep'` regardless of which user's crontab fires it (or whether a human runs `comadre-keys suspend-sweep` manually). Rationale: the audit actor names the *behavior*, not the triggering identity. A human running the sweep manually is recovering from a failed cron, and the audit trail reads cleaner when all sweep rows share one actor string.
- **Story 2.3 — `cache-status` CLI shape in `system.py`** — `src/comadre/keys/cli/commands/system.py` is the canonical template for a non-billing operational command: `get_settings()` for config validation, `ZoneInfo(settings.billing_timezone)` for TZ check, `_apply_migrations(conn)` for DB bootstrap, PII-austere INFO log. Story 3.3 appends `suspend_sweep_cmd` to the same module following the same ladder.
- **Existing `comadre-audio-cleanup` cron pattern** — `deploy/ansible/playbooks/bootstrap.yml:296-306` is the exact template for the new `comadre-daily-suspension` entry. The existing entry runs every 6 h via `cd ~/comadre && docker compose exec -T tts-service find /audio -type f ... || logger -t comadre-cleanup '...'`. Story 3.3 mirrors this: `docker compose exec -T tts-service comadre-keys suspend-sweep 2>&1 | logger -t comadre-suspension-sweep`. The `-T` flag is load-bearing — without it, `docker compose exec` allocates a TTY and fails under cron (no controlling terminal).

## Unblocks

- **Story 3.4 — System Health Command** — `comadre-keys health` reads `MAX(occurred_at) FROM audit_log WHERE action='cron_suspend' AND target_type='system'` to display the "last successful suspension sweep at <timestamp>" line per FR43. Story 3.3 persists this data via the summary audit row; Story 3.4 reads and renders it. Story 3.3 ships the `get_last_sweep_timestamp(conn) -> str | None` helper so 3.4's implementation is a one-liner call + formatting.
- **Story 4.1 — LGPD export** — `export-customer` must serialize the customer's `audit_log` events. The new `suspend_key` rows with `actor='cron:suspension-sweep'` need to be clearly labeled in the export so the customer sees "the system suspended your key on <date>" rather than a cryptic `cli:<username>` they don't recognize. Story 4.1 already plans to preserve the actor column; Story 3.3 just ensures the convention is established before the export surface exists.
- **Story 4.3 — Backup / restore** — the `cron_suspend` summary row gives the restore playbook a self-test hook: after restore, `health` reports the pre-restore `last_sweep_at`. If the timestamp is 48 h stale the operator knows cron hasn't fired since restore (systemd-cron may need re-enable).

## Depends on

- Stories 1.1–1.6, 2.1–2.3, 3.1, 3.2 must be `done` (all are as of 2026-04-19; see `_bmad-output/implementation-artifacts/sprint-status.yaml`).
- No schema change. The `idx_api_key_sweep` partial index from `v001_initial.sql:44` already exists and is tuned for the sweep's predicate.
- No new dependency in `pyproject.toml` / `uv.lock`. The sweep uses stdlib `sqlite3`, `datetime`, `typer`, and the existing `comadre.keys.*` + `comadre.logging` surfaces.
- No rate-limit code change. No auth path change. No new FastAPI route. The cron runs inside the same container as the API (via `docker compose exec -T`) — the existing `comadre-registry` named volume is the shared SQLite file.

## Scope

Adds one new DB helper (`run_suspension_sweep` in `src/comadre/keys/db.py`), one new read helper (`get_last_sweep_timestamp` in the same module — consumed by Story 3.4's `health` command), one new CLI command (`suspend-sweep` in `src/comadre/keys/cli/commands/system.py`), and one new Ansible cron entry + CRON_TZ variable in `deploy/ansible/playbooks/bootstrap.yml` + the matching removal in `cleanup.yml`. **No new module. No schema change. No rate-limit change. No auth change. No new dependency.**

### 1. New DB helper: `run_suspension_sweep`

`src/comadre/keys/db.py` — sibling of `suspend_key` / `reactivate_key` / `mark_key_paid`.

```python
@dataclass(frozen=True, slots=True)
class SuspensionSweepResult:
    """Return payload from ``run_suspension_sweep``.

    ``swept_key_ids`` carries the full list of ``api_key.id`` values that
    flipped from ``active`` to ``suspended``. ``swept_count`` is
    ``len(swept_key_ids)`` — exposed separately so the CLI doesn't
    materialize the list to log a count. ``completed_at`` is the single
    summary-row timestamp the sweep wrote (``%Y-%m-%dT%H:%M:%SZ``
    canonical ISO UTC form) — fed back to ``render_confirmation`` so the
    operator-facing ConfirmationLine shows the same timestamp that
    ``health`` will later read from the audit log. ``cutoff_date`` is the
    ``today`` the caller passed, echoed back so the CLI can print it
    verbatim in the log line without re-parsing.
    """

    swept_key_ids: tuple[str, ...]
    swept_count: int
    completed_at: str
    cutoff_date: str  # YYYY-MM-DD


def run_suspension_sweep(
    conn: sqlite3.Connection,
    *,
    today: date,
    actor: str = "cron:suspension-sweep",
) -> SuspensionSweepResult:
    ...
```

Behavior:

1. Compute `today_iso = today.isoformat()` (canonical YYYY-MM-DD — matches the lex-sortable shape `mark-paid` enforces on write).
2. Open a single `with conn:` transaction scoped to the full sweep so the bulk UPDATE, every per-row audit insertion, AND the summary audit row either all commit or all roll back.
3. **Identify the sweep set via `RETURNING`.** Execute:
   ```sql
   UPDATE api_key
   SET status = 'suspended'
   WHERE billing_mode = 'manual'
     AND status = 'active'
     AND paid_until IS NOT NULL
     AND paid_until < ?
   RETURNING id, paid_until
   ```
   Parameter: `(today_iso,)`. Notes:
   - `paid_until IS NOT NULL` is **load-bearing**. SQLite NULL comparison semantics would already exclude NULL rows from `paid_until < ?`, but adding the explicit `IS NOT NULL` predicate makes the intent visible in the SQL and survives a future migration that might rewrite the predicate.
   - `RETURNING` is available on SQLite 3.35+ (Python 3.11+ ships 3.37+); pin the requirement in `db.py`'s docstring. If `RETURNING` is unavailable, fall back to a pre-UPDATE `SELECT id, paid_until FROM api_key WHERE <predicate>` + the UPDATE — but prefer `RETURNING` to eliminate the TOCTOU gap between SELECT and UPDATE (a concurrent CLI `mark-paid` between the two steps would otherwise silently miss a suspension).
   - The predicate uses `paid_until < ?` (strict less-than), matching FR18's "whose paid date has elapsed" semantic. A key with `paid_until = today` is still considered paid through today; the sweep catches it on the next morning.
4. Materialize the rowset: `swept_rows = cursor.fetchall()` → `swept_key_ids = tuple(row["id"] for row in swept_rows)`, `swept_count = len(swept_key_ids)`.
5. For each `row in swept_rows`, write one per-key audit row via `log_event(...)`:
   ```python
   log_event(
       conn,
       actor=actor,  # "cron:suspension-sweep" for cron-driven calls
       action="suspend_key",  # matches Story 3.1's manual-suspend naming
       target_type="api_key",
       target_id=row["id"],
       details={"paid_until": row["paid_until"], "cutoff_date": today_iso},
   )
   ```
   `details_json` carries both the row's expired `paid_until` and the sweep's `cutoff_date` — this gives Story 4.1 export a self-contained forensic record ("your key's `paid_until` was 2026-04-05 and the sweep ran with cutoff 2026-04-06"). No PII keys — `paid_until` and `cutoff_date` are operational, not personal.
6. Write exactly ONE summary audit row per sweep invocation — **always**, even when `swept_count == 0`:
   ```python
   completed_at = _utcnow_iso()  # reused helper at db.py:170
   log_event(
       conn,
       actor=actor,
       action="cron_suspend",  # architecture.md §324 canonical name
       target_type="system",
       target_id=None,
       details={"swept_count": swept_count, "cutoff_date": today_iso},
   )
   ```
   **Why the summary row is mandatory on zero-row sweeps.** AC "no keys are expired" explicitly requires the timestamp to be recorded. Health command (Story 3.4) reads `MAX(occurred_at) FROM audit_log WHERE action='cron_suspend'`; a sweep that did nothing still proved cron liveness at its scheduled time, and the operator's mental model is "the last time the sweep *ran*", not "the last time it *suspended*".
   **Why action name `cron_suspend` and not `cron_suspend_sweep`.** Architecture `§324` reserved the shorter name. The `target_type='system'` + `target_id=NULL` combination disambiguates summary rows from per-key `suspend_key` rows without overloading the action string.
7. After `with conn:` commits, call `_touch_auth_cache_sentinel(conn)` — identical to every other mutation helper. Called outside the transaction so it only runs on successful commit. Single filesystem touch; amortized across the whole sweep (not per row).
8. Return `SuspensionSweepResult(swept_key_ids=swept_key_ids, swept_count=swept_count, completed_at=completed_at, cutoff_date=today_iso)`.

**Why one transaction, not per-row transactions.** Architecture `§476` is explicit: "The suspension sweep (`suspend-sweep`) uses a single UPDATE statement, not per-row transactions." Per-row transactions would cost N `fsync` calls + N sentinel touches on a 1 000-key sweep, blowing the NFR3 budget by orders of magnitude. A single transaction means one `fsync` on commit regardless of row count. The audit-log insertions inside the transaction are cheap (append-only, no index rebuild) — 1 000 inserts at ~30 µs each = 30 ms, well under the 1 s budget.

**Why the helper does not accept a pre-computed rowset.** A cleaner signature might be `run_suspension_sweep(conn, rows_to_suspend: list[str], ...)` where the caller pre-identifies the keys. Rejected because: (a) it creates a TOCTOU race between identification and update (a concurrent `mark-paid` could flip a row to `active` before the UPDATE lands); (b) it forces the caller to know the sweep predicate, leaking the SQL shape into CLI code. Keeping the predicate inside the helper makes the sweep a single atomic conceptual operation.

**Why `actor` is a parameter and not hardcoded.** Tests and non-CLI callers (future backup/restore verification hooks) need to vary the actor for assertion purposes — the test suite writes `actor='test:sweep'` to distinguish fixture-driven rows from real audit data. CLI callers always pass the canonical `'cron:suspension-sweep'` string (see §4 below).

### 2. New read helper: `get_last_sweep_timestamp`

`src/comadre/keys/db.py` — public helper for Story 3.4's `health` command to consume. Lives next to `run_suspension_sweep` so readers find both in one place.

```python
def get_last_sweep_timestamp(conn: sqlite3.Connection) -> str | None:
    """Return the canonical ISO-UTC timestamp of the most-recent completed
    suspension sweep, or ``None`` if the sweep has never run on this DB.

    Reads the most-recent ``action='cron_suspend'`` / ``target_type='system'``
    row from ``audit_log``. ``MAX(occurred_at)`` works because the sweep
    writes canonical ``%Y-%m-%dT%H:%M:%SZ`` strings (lex-sortable) — the
    same ISO-UTC shape every other audit row uses.

    Consumed by Story 3.4's ``comadre-keys health`` command; exposed here
    so 3.3's diff is a one-function addition instead of 3.4 hunting for
    the right SELECT across two stories' code.
    """
    row = conn.execute(
        "SELECT MAX(occurred_at) AS last_at "
        "FROM audit_log "
        "WHERE action = 'cron_suspend' AND target_type = 'system'"
    ).fetchone()
    if row is None or row["last_at"] is None:
        return None
    return cast(str, row["last_at"])
```

**Why scope via both `action` AND `target_type`.** Defense-in-depth against a future action-name collision. If some later story introduces an `action='cron_suspend'` with `target_type='api_key'` (e.g., per-key cron audit), the summary row still uniquely matches `target_type='system'`. The compound predicate matches the audit log's structured discriminators instead of relying on the action string alone.

**Why no `details_json` filtering.** A read of `MAX(occurred_at)` is O(log N) with `idx_audit_occurred` (v001_initial.sql:45) regardless of predicate complexity — SQLite scans the index backward and short-circuits on the first matching row. Adding a `json_extract` on `details_json` would force a full table scan.

### 3. New CLI command: `suspend-sweep`

`src/comadre/keys/cli/commands/system.py` — appended after `cache_status_cmd`. Same module as `cache-status` / `health` / `rotate-encryption-key` per architecture `§357`.

```python
@app.command("suspend-sweep")
def suspend_sweep_cmd(
    dry_run: bool = typer.Option(
        False,
        "--dry-run",
        help=(
            "Preview the sweep without writing: lists the keys that would "
            "be suspended (id + paid_until), does NOT UPDATE, does NOT "
            "audit. Exit 0 regardless of count."
        ),
    ),
) -> None:
    """Suspend manual-mode keys whose paid_until has elapsed (FR18 / FR43).

    Designed for cron (00:30 operator-TZ). Safe to run manually to recover
    from a failed cron or to preview the sweep via --dry-run.

    Complimentary keys are never touched (billing_mode='manual' filter).
    Trial-window keys (NULL paid_until) are never touched — those belong
    to the J1 first-sale flow, not the Day-06 enforcement cycle.

    Example: comadre-keys suspend-sweep
             comadre-keys suspend-sweep --dry-run
    """
```

Validation ladder (mirrors `cache-status`):

1. **Settings + TZ** (exit 6). Reuses `load_settings_and_tz()` from `comadre.keys.cli.commands.keys`. `None` → `raise typer.Exit(code=6)`. Missing encryption key or invalid `BILLING_TIMEZONE` are the two failure modes; both render their canonical error panels inside the helper.
2. **Compute `today`** — `today = resolve_today_in_tz(billing_tz)`. This is the operator-TZ-aware "what calendar day is it right now" — critical for FR18 because the cron runs at 00:30 São Paulo time but the VPS host clock is UTC. Without the TZ-aware resolution, a sweep triggered at 00:30 São Paulo on April 6 would see UTC April 6 03:30 — same date in this case, but on the January 1 UTC-offset boundary, an untz-aware `date.today()` would sweep the wrong day.
3. **Open DB + migrations** (exit 5). Pattern mirrors `cache_status_cmd` except the DB is actually touched here. Wrap `get_connection(settings.key_registry_db_path)` in `try/except sqlite3.Error` → exit 5. Wrap `_apply_migrations(conn)` in `try/except sqlite3.Error, RuntimeError` → exit 5 (RuntimeError is the "schema downgrade detected" branch; swallowing it is consistent with the deferred-work entry in `deferred-work.md` that tracks broader `_apply_migrations` error mapping).
4. **Dry-run branch** (if `dry_run=True`):
   - `list_api_keys(conn, status='active', billing_mode='manual')` to get the active-manual set.
   - Filter in Python: `paid_until` not None AND `date.fromisoformat(paid_until) < today`.
   - Sort `(paid_until ASC, key_prefix ASC)` — deterministic by the same invariant Story 3.2's `at-risk` uses.
   - Render via `render_empty_state([f"No keys would be suspended by the sweep on {today.isoformat()}."])` when zero, or via a new `render_suspend_sweep_preview(rows, cutoff_date)` (§4 renderer spec below) when populated.
   - **No audit writes. No UPDATE. No sentinel touch.** Exit 0.
5. **Real sweep branch** (if `dry_run=False`):
   - Call `run_suspension_sweep(conn, today=today, actor="cron:suspension-sweep")`.
   - Wrap in `try/except sqlite3.Error, RuntimeError` → exit 5.
6. **Close DB** in the `finally` of the outer `try` (matches every other CLI command in the repo).
7. **Structured INFO log** (PII-austere aggregate):
   ```python
   with contextlib.suppress(Exception):
       _logger.info(
           "Suspension sweep completed | cutoff=%s | swept_count=%d | "
           "completed_at=%s | dry_run=%s",
           today.isoformat(),
           result.swept_count if not dry_run else preview_count,
           result.completed_at if not dry_run else "(dry-run)",
           dry_run,
       )
   ```
   No `key_id`, no `key_prefix`, no customer name — per NFR15. The count is operational data, not PII.
8. **ConfirmationLine** (UX-DR7). Real sweep: `f"Suspension sweep completed: {swept_count} key(s) suspended at {completed_at} (cutoff {cutoff_date})."`. Dry-run: `f"Dry-run — {preview_count} key(s) would be suspended at cutoff {today_iso}."`. Both via `render_confirmation(...)`.

**Why hardcode `actor='cron:suspension-sweep'` regardless of invocation source.** A human running `comadre-keys suspend-sweep` manually is recovering from a failed cron. The audit trail must tell a consistent story — "the sweep ran at <time>" is the operator-meaningful event, not "the operator triggered the sweep at <time>". Hardcoding the actor means one query (`WHERE actor='cron:suspension-sweep'`) gives the complete sweep history regardless of trigger. The flip side — "did a human or cron fire this?" — is not an operationally interesting question; if there's a discrepancy, the DB row timestamps will make the cause obvious.

**Why `--dry-run` is the one operator-facing flag.** An ops-bounded audit surface. The operator might want to verify "if I ran the sweep right now, who would it hit?" before cron fires — particularly useful on the first deploy or after a backup restore. Dry-run does exactly one thing: read, filter, display. Exit 0 always (even on populated preview). Zero writes, zero audit rows.

**Why no `--verbose` / `--format json` flag.** Added scope. The sweep's stdout is an operator-facing ConfirmationLine + a structured log line; scripts that want the swept-key list read the audit log (`comadre-keys show <prefix> --audit-tail N` or the planned 3.4 `health --format json`). Adding JSON output here would leak the per-key ID list onto stdout, which invites operator scripting around the sweep output — defeating the "cron is zero-touch" design goal.

### 4. New renderer: `render_suspend_sweep_preview`

`src/comadre/keys/cli/output.py` — append near `render_at_risk_table` (L310). Mirrors `render_at_risk_table` byte-for-byte in the column machinery; differs only in title and the absence of a `Days Left` column (dry-run previews keys **already** past cutoff — "days_overdue" is arguably more useful but would be a net-new column; keep the same columns as `at-risk` minus `Days Left` so the operator's eye moves consistently).

```python
def render_suspend_sweep_preview(
    rows: list[ApiKeyListRow],
    cutoff_date: date,
) -> None:
    """UX-DR2 — preview table for `suspend-sweep --dry-run`.

    Invariant column order (identifier → name → status → billing → dates):
      Prefix | Customer | Status | Price | Paid Until

    Status cell is always ``[yellow]to-suspend[/]`` — signals the
    operator that these rows will flip on the real sweep. Consistent with
    the ``at-risk`` table's ``[yellow]at-risk[/]`` badge.
    """
```

Implementation notes:

- **Title**: `f"Dry-run preview: keys to suspend at cutoff {cutoff_date.isoformat()}"`.
- **Status cell**: hard-coded `Text("to-suspend", style="yellow")`. Reuses the `at-risk` renderer's decision to NOT extend `_status_label` — the "would-be-suspended" set is a semantic overlay, not a persisted status.
- **Footer**: `render_confirmation(f"{len(rows)} key(s) would be suspended. Run without --dry-run to proceed.")`.

**Why a separate renderer and not `render_at_risk_table`.** `render_at_risk_table` has a `window_days` argument and a `Days Left` column tied to the look-ahead semantic. Sharing the helper would require a polymorphic mode flag, which is worse than two 20-line functions.

### 5. Ansible cron installation

`deploy/ansible/playbooks/bootstrap.yml` — append a new task in the "Cron Jobs" section (L286-306), after `comadre-audio-cleanup`. **Place the new cron entry adjacent to the existing two** so the "all scheduled jobs" audit surface stays in one block.

```yaml
- name: "[Cron] Set CRON_TZ for billing-aware schedules"
  ansible.builtin.cron:
    name: "CRON_TZ"
    env: true
    value: "{{ billing_timezone | default('America/Sao_Paulo') }}"

- name: "[Cron] Configure daily suspension sweep at 00:30 operator TZ"
  ansible.builtin.cron:
    name: "comadre-daily-suspension"
    minute: "30"
    hour: "0"
    job: >-
      cd ~/comadre &&
      docker compose exec -T tts-service comadre-keys suspend-sweep 2>&1 |
      logger -t comadre-suspension-sweep
```

Rationale:

- **CRON_TZ envvar task.** `ansible.builtin.cron` with `env: true` manages an envvar at the top of the user's crontab. All subsequent schedule entries in that crontab honor the TZ. Cron's `CRON_TZ` support is in Debian/Ubuntu's `cron` package since Jessie; no new system dependency.
- **`billing_timezone` variable.** Add to `deploy/ansible/inventory/production.yml` + `production.yml.example` + `oracle.yml` + `oracle.yml.example` as `billing_timezone: "America/Sao_Paulo"` with a comment explaining that it must match the `BILLING_TIMEZONE` in `.env` (else the cron schedule drifts from the app's "today" computation). The inventory already has a pattern of per-host knobs (`restart_hour`, `default_voice`) — follow suit.
- **`-T` flag on `docker compose exec`.** Cron has no controlling TTY; without `-T`, `docker compose exec` errors with `the input device is not a TTY`. Mirrors the `comadre-audio-cleanup` entry that already uses `-T`.
- **`2>&1 | logger -t comadre-suspension-sweep`.** Redirects both stdout and stderr into syslog with a recognizable tag. Operators tail `/var/log/syslog | grep comadre-suspension-sweep` to audit sweep runs. Matches architecture `§250` "cron output captured in syslog for operator debugging".
- **No `|| logger '<error>'` fallback** (unlike `comadre-audio-cleanup`). The sweep CLI's own exit code captures the failure; bubbling a non-zero exit into cron's MTA mail (if configured) is the operator's alerting channel. Adding a fallback logger would mask the distinction between "sweep ran successfully on zero rows" and "sweep failed to reach the container" — both are operationally different and deserve different responses.

`deploy/ansible/playbooks/cleanup.yml` — symmetric removal:

```yaml
- name: "[Cron] Remove daily suspension sweep"
  ansible.builtin.cron:
    name: "comadre-daily-suspension"
    state: absent

- name: "[Cron] Remove CRON_TZ envvar"
  ansible.builtin.cron:
    name: "CRON_TZ"
    env: true
    state: absent
```

**Why not remove `CRON_TZ` only if no other Comadre cron needs it.** `cleanup.yml` tears the deployment down; removing the envvar matches "leave no trace" semantic. If a future Comadre version re-enables the cron, the envvar gets re-added on `bootstrap.yml`.

### 6. Fast-path manual invocation for operators

Document in `README.md` + `docs/configuration-reference.md` the two ways an operator can trigger the sweep:

- **Cron (zero-touch, default):** installed by `bootstrap.yml`, runs at 00:30 São Paulo time. No operator action ever.
- **Manual:** `docker compose exec tts-service comadre-keys suspend-sweep` — recovers from a failed cron (e.g., VPS was down at 00:30). Safe to run any time.
- **Preview:** `docker compose exec tts-service comadre-keys suspend-sweep --dry-run` — answers "what would the sweep hit if it ran now?" without touching data. Useful for post-restore verification.

### 7. Exit-code contract

| Exit | `suspend-sweep` trigger                                                        |
| ---- | ------------------------------------------------------------------------------ |
| 0    | Success (including zero-row sweep — the timestamp was still recorded)          |
| 0    | `--dry-run` always exits 0 regardless of preview count                         |
| 2    | _never — no operator-parseable flag beyond `--dry-run`/`--help`_               |
| 3    | _never — no key identifier resolution_                                         |
| 5    | `sqlite3.Error` from `get_connection`, `_apply_migrations`, or the sweep UPDATE |
| 5    | `RuntimeError` from `_apply_migrations` (schema-downgrade) or `run_suspension_sweep` |
| 6    | Missing `KEY_REGISTRY_ENCRYPTION_KEY` / invalid `BILLING_TIMEZONE` (via `load_settings_and_tz`) |

`system.py`'s module docstring (currently enumerates 0/2/6 for `cache-status`) extends to 0/5/6 for the new verb — add 5 to the header.

### 8. JSON / machine-readable output

**Not in scope for this story.** The sweep is designed for cron — stdout is operator-facing ConfirmationLine, stderr is structured log line. Scripts that want the swept-key list query the audit log via `comadre-keys show <prefix> --audit-tail N` or the future 3.4 `health --format json`.

### 9. Docs

- **`CLAUDE.md`** — extend the `keys/cli/` bullet to append `suspend-sweep` at the end of the system cluster: `comadre-keys cache-status, suspend-sweep`. Current ordering keeps alphabetical-by-function (customers → keys → billing → system).
- **`CLAUDE.md`** — append a new gotcha under "Non-Obvious Gotchas":
  > **Suspension sweep predicate uses strict `paid_until < today`, not `<=`.** A key with `paid_until == today` is considered paid through today; the sweep catches it on the next morning. This matches FR18's "whose paid date has elapsed" wording. Don't "fix" the predicate to `<=` — you'd suspend customers who paid today and haven't yet ridden out their coverage.
- **`README.md`** — append a one-line entry under "Registry-backed API keys → Billing" for the manual/dry-run invocations (cron is silent).
- **`docs/configuration-reference.md`** — extend the `BILLING_TIMEZONE` entry to note that it **must** match `ansible_cron.CRON_TZ` set by `bootstrap.yml`; a mismatch drifts the cron from the app's notion of "today".
- **No `docs/monetization.md`** — still deferred to Story 4.6 per Story 3.1 §6.

### 10. Tests

- **`tests/test_keys_db_suspend_sweep.py`** (NEW) — unit tests for `run_suspension_sweep` and `get_last_sweep_timestamp`:
  - **`test_sweeps_expired_active_manual_keys`**: seed 3 rows — `paid_until=2026-04-05` (expired), `paid_until=2026-04-06` (cutoff day, still paid), `paid_until=2026-04-04` (expired). Today = `2026-04-06`. Call `run_suspension_sweep(conn, today=date(2026, 4, 6))`. Assert `swept_count == 2`, both expired rows now `status='suspended'`, the cutoff-day row still `active`, `swept_key_ids` contains both expired key IDs in stable order.
  - **`test_never_sweeps_complimentary`**: seed 1 complimentary row with `paid_until=2026-04-05` (seeded even though comp normally has NULL). Expect `swept_count == 0`, row stays `active`. No audit rows written for that ID.
  - **`test_never_sweeps_trial_window_null_paid_until`**: seed 1 active-manual row with `paid_until=NULL`. Expect `swept_count == 0`. Row stays `active`.
  - **`test_never_sweeps_suspended`**: seed 1 already-suspended row with `paid_until=2026-04-01`. Expect `swept_count == 0`. No new audit row for that ID (the existing manual-suspend audit is untouched).
  - **`test_never_sweeps_revoked`**: seed 1 revoked row with `paid_until=2026-04-01`. Expect `swept_count == 0`.
  - **`test_writes_per_key_suspend_key_audit_rows`**: sweep 2 keys. Assert exactly 2 audit rows with `action='suspend_key'`, `actor='cron:suspension-sweep'`, `target_type='api_key'`, each `target_id` in the swept set, `details_json` contains both `paid_until` AND `cutoff_date`.
  - **`test_writes_summary_cron_suspend_audit_row`**: sweep 2 keys. Assert exactly 1 audit row with `action='cron_suspend'`, `actor='cron:suspension-sweep'`, `target_type='system'`, `target_id IS NULL`, `details_json` contains `swept_count=2` and `cutoff_date`.
  - **`test_zero_row_sweep_still_writes_summary_row`**: DB with only complimentary / NULL / revoked / cutoff-day rows. Assert `swept_count == 0`, assert exactly 1 summary audit row written (0 per-key rows), `completed_at` is canonical ISO-UTC.
  - **`test_touches_sentinel_on_success`**: use a real tmp DB, after sweep assert `{db_path}.invalidate` exists and mtime > sweep_start.
  - **`test_sweep_never_touches_sentinel_on_rollback`**: monkeypatch `log_event` to raise ValueError mid-loop (simulating a forbidden-key audit rejection). Expect the sweep to propagate the error, `api_key.status` to be unchanged (rollback), sentinel mtime unchanged.
  - **`test_actor_param_flows_through`**: pass `actor='test:sweep'`. Assert every resulting audit row has `actor='test:sweep'` — proves the helper does not hardcode.
  - **`test_returning_rowset_is_deterministic`**: seed 10 swept-eligible rows with varying IDs; assert `swept_key_ids` is a tuple (not a list), and the content matches the DB's post-sweep `suspended` set. Order is SQLite-internal (not asserted) but membership is.
  - **`test_performance_budget_nfr3`**: seed 1 000 active manual keys with `paid_until='2026-01-01'`. Run `run_suspension_sweep(conn, today=date(2026, 4, 6))`. Wrap in `time.perf_counter()`; assert `elapsed_ms < 1000` (NFR3 <1 s for 1K keys). On bare metal the actual figure should be under 100 ms — the slack tolerates CI jitter.
  - **`test_uses_idx_api_key_sweep`** (advisory, skip on CI flake): `EXPLAIN QUERY PLAN UPDATE api_key SET status='suspended' WHERE billing_mode='manual' AND status='active' AND paid_until IS NOT NULL AND paid_until < ?` contains `USING INDEX idx_api_key_sweep`. Marked `@pytest.mark.skipif(...)` if the plan output varies across SQLite patch versions.
  - **`test_get_last_sweep_timestamp_returns_none_on_fresh_db`**: fresh DB, call helper, assert `None`.
  - **`test_get_last_sweep_timestamp_returns_most_recent`**: seed 2 summary rows with distinct `occurred_at`. Assert helper returns the later one.
  - **`test_get_last_sweep_timestamp_ignores_per_key_rows`**: seed 1 per-key `suspend_key` row (not a summary) + 1 older summary. Assert helper returns the summary's `occurred_at`, not the per-key row's.

- **`tests/test_keys_cli_suspend_sweep.py`** (NEW) — end-to-end CLI via `CliRunner`. Mirrors `tests/test_keys_cli_mark_paid.py` scaffolding (same `_reset_consoles_to_buffers` auto-fixture, same PII regex, same `monkeypatch.setattr("comadre.keys.cli._clock.resolve_today_in_tz", ...)` time-freeze):
  - **`test_full_sweep_happy_path`**: seed 3 expired keys + 2 paid keys. Time-freeze `2026-04-06`. Run `suspend-sweep`. Assert exit 0, stdout contains `"Suspension sweep completed: 3 key(s) suspended"` + `"cutoff 2026-04-06"`. Assert `3 + 1 = 4` new audit rows (3 per-key + 1 summary).
  - **`test_zero_row_sweep_exits_0`**: DB with only paid keys. Run sweep. Exit 0, stdout contains `"0 key(s) suspended"`. Exactly 1 audit row (summary).
  - **`test_dry_run_writes_nothing`**: seed 2 expired keys. Run `suspend-sweep --dry-run`. Exit 0. Stdout contains `"Dry-run"` + `"2 key(s) would be suspended"`. Assert DB: both rows still `status='active'`, ZERO audit rows written.
  - **`test_dry_run_empty_preview_message`**: DB with only paid keys. `suspend-sweep --dry-run`. Stdout contains `"No keys would be suspended by the sweep on 2026-04-06."`.
  - **`test_missing_encryption_key_exits_6`**: unset `KEY_REGISTRY_ENCRYPTION_KEY`. Run. Exit 6. Stderr panel title contains `"Configuration error: KEY_REGISTRY_ENCRYPTION_KEY"`.
  - **`test_invalid_billing_tz_exits_6`**: set `BILLING_TIMEZONE=Not/Real`. Run. Exit 6.
  - **`test_db_error_exits_5`**: point `KEY_REGISTRY_DB_PATH` to a non-writable path. Run. Exit 5.
  - **`test_pii_austere_log`**: run a successful sweep that suspends 2 real customer keys. Capture caplog INFO records. Assert no customer names, no emails, no CPF digits (11-14 digit runs), no SHA-256 hashes (64 hex chars), no `cmdr_live_` prefix — reuse Story 3.1's `_PII_FORBIDDEN_RE`.
  - **`test_actor_hardcoded_cron_suspension_sweep`**: run sweep from CLI (which internally calls `run_suspension_sweep` with actor=`cron:suspension-sweep`). Query `audit_log` — every new row has `actor='cron:suspension-sweep'`, never `cli:<user>`.
  - **`test_confirmation_line_contains_canonical_timestamp`**: run. Capture stdout. Assert the timestamp in the ConfirmationLine matches `\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}Z` (ISO-UTC canonical form written by `_utcnow_iso`). The same timestamp is queryable via `get_last_sweep_timestamp` — assert byte-identity between the two.
  - **`test_suspend_sweep_appears_in_top_level_help`**: `CliRunner().invoke(app, ["--help"])`. Stdout contains `suspend-sweep`. One-line description matches the command docstring's first sentence.
  - **`test_idempotent_second_run_suspends_nothing`**: run sweep twice with the same `today`. First run suspends N. Second run must suspend 0 (already-suspended rows excluded by `status='active'` predicate). Two summary rows total; per-key rows only from the first run.
  - **`test_manual_rerun_after_mark_paid_reactivates_and_resweeps`**: seed 1 expired key. Sweep — suspended. Run `mark-paid <key> --until 2026-04-10` (reactivates per Story 3.1 AC20). Advance time to `2026-04-11`. Sweep again — key re-suspended. Assert the audit tail reads in order: `suspend_key (cron)` → `mark_paid (cli, reactivated=true)` → `suspend_key (cron)`.

- **`tests/test_keys_output.py`** (MOD) — renderer unit tests:
  - **`test_render_suspend_sweep_preview_shape`**: feed 2 rows + a fixed cutoff. Assert title contains `"Dry-run preview: keys to suspend at cutoff 2026-04-06"`. Status cell is `to-suspend` in yellow. Footer reads `"2 key(s) would be suspended. Run without --dry-run to proceed."`.
  - **`test_render_suspend_sweep_preview_markup_injection_guarded`** (defense-in-depth, same mitigation as 3.2's renderer): craft a row with `customer_name="[red]evil[/]"`. Rendered output contains the literal `[red]evil[/]` (escaped, not interpreted).

- **No new ansible integration tests.** `deploy/ansible/playbooks/bootstrap.yml` is exercised by the existing `ansible-playbook --check` smoke in CI (if one exists; if not, manual verification on the VPS is the acceptance gate). Add a brief note to the story close about the manual verification step on 10.10.10.207.

### 11. Grep checks (Task-12 style, for the implementer's pre-commit pass)

- `rg -n "action='suspend_key'" src/comadre/keys/db.py` — exactly 2 hits (the Story 3.1 manual helper + Story 3.3 sweep helper). Any third hit is a copy-paste bug.
- `rg -n "action='cron_suspend'" src/comadre/keys/db.py` — exactly 1 hit (the new summary-row write).
- `rg -n "cron:suspension-sweep" src/comadre/keys/` — exactly 2 hits (the default parameter in `run_suspension_sweep` + the CLI's hardcoded call site).
- `rg -n "paid_until < " src/comadre/keys/db.py` — new hit for the sweep SQL. No `paid_until <= `.
- `rg "HTTPException" src/comadre/keys/cli/commands/system.py` → zero hits.
- `rg "\\bprint\\(" src/comadre/keys/cli/commands/system.py` → zero hits (stdout goes through `render_*` / `stdout_console`).
- `rg "os\\.environ" src/comadre/keys/cli/commands/system.py` → zero hits (pydantic-settings only).
- `git diff src/comadre/rate_limit.py src/comadre/api.py src/comadre/keys/auth.py src/comadre/keys/cache.py` — empty (AC12 invariant).
- `git diff pyproject.toml uv.lock src/comadre/keys/migrations/` — empty (no new dep, no schema change).

## Acceptance Criteria

> BDD-style. Each AC maps to at least one test. AC numbers are stable — do not renumber if a mid-story pivot adds/removes an AC (append a new number instead).

### AC1 — Sweep suspends only manual-mode keys with expired `paid_until` and `status='active'`

**Given** a registry with:

- Key A — `status='active'`, `billing_mode='manual'`, `paid_until='2026-04-05'` (1 day expired)
- Key B — `status='active'`, `billing_mode='manual'`, `paid_until='2026-04-06'` (today — still paid)
- Key C — `status='active'`, `billing_mode='manual'`, `paid_until='2026-03-15'` (3 weeks expired)
- Key D — `status='active'`, `billing_mode='manual'`, `paid_until=NULL` (trial window)
- Key E — `status='active'`, `billing_mode='complimentary'`, `paid_until='2026-04-05'` (seeded for the test)
- Key F — `status='suspended'`, `billing_mode='manual'`, `paid_until='2026-04-05'` (already suspended)
- Key G — `status='revoked'`, `billing_mode='manual'`, `paid_until='2026-04-05'` (revoked)
- Today = `2026-04-06`

**When** the operator (or cron) runs `comadre-keys suspend-sweep`

**Then** exit code is 0
**And** keys A and C flip to `status='suspended'`
**And** keys B, D, E, F, G are unchanged
**And** `swept_count == 2`
**And** the stdout ConfirmationLine reads `Suspension sweep completed: 2 key(s) suspended at <ISO-UTC> (cutoff 2026-04-06).`

### AC2 — Per-suspended-key audit row with actor `cron:suspension-sweep`

**Given** the AC1 setup after the sweep

**When** the audit log is queried for `target_id ∈ {A, C}`

**Then** each of A and C has exactly one new `audit_log` row
**And** each row has `actor='cron:suspension-sweep'`, `action='suspend_key'`, `target_type='api_key'`, `target_id=<key id>`
**And** `details_json` parses to a dict with `paid_until` matching the key's pre-sweep value AND `cutoff_date='2026-04-06'`
**And** `occurred_at` is canonical `%Y-%m-%dT%H:%M:%SZ` UTC

### AC3 — Single summary audit row per sweep invocation

**Given** any sweep invocation (even zero-row)

**When** the audit log is queried for `action='cron_suspend' AND target_type='system'`

**Then** the count of summary rows increased by exactly 1
**And** the row has `actor='cron:suspension-sweep'`, `target_id IS NULL`
**And** `details_json` parses to `{"swept_count": <N>, "cutoff_date": "2026-04-06"}`
**And** `occurred_at` equals the `completed_at` returned by `run_suspension_sweep` (byte-identity)

### AC4 — Zero-row sweep still completes and records the timestamp

**Given** a DB with only:

- Complimentary keys
- Trial-window (NULL `paid_until`) active manual keys
- Suspended / revoked keys
- Manual keys with `paid_until >= today`

**When** `suspend-sweep` runs

**Then** exit code is 0
**And** `swept_count == 0`
**And** no per-key audit rows are added
**And** exactly 1 summary audit row is written with `swept_count=0`
**And** `get_last_sweep_timestamp(conn)` returns the summary row's `occurred_at` (FR43)
**And** the ConfirmationLine reads `Suspension sweep completed: 0 key(s) suspended at <ISO-UTC> (cutoff 2026-04-06).`

### AC5 — Cache sentinel touch on successful sweep

**Given** a sweep that flipped at least one key

**When** the transaction commits

**Then** `{KEY_REGISTRY_DB_PATH}.invalidate` exists on disk
**And** its mtime is more recent than the sweep start time
**And** the auth cache in any running API replica flushes on the next request (observable via `cache-status`' `snapshot_age_seconds` — integration-tested indirectly through the Story 2.1 auth path already covered by those tests)

### AC6 — Rollback on mid-sweep failure leaves state untouched

**Given** a monkeypatched `log_event` that raises `ValueError` on the second per-key audit write

**When** a 3-key sweep triggers the error

**Then** the `sqlite3.Error` / `ValueError` propagates out of `run_suspension_sweep`
**And** zero keys are `suspended` (all 3 stayed `active`)
**And** zero audit rows were committed (transaction rolled back)
**And** the sentinel mtime is unchanged

### AC7 — `--dry-run` previews without writing

**Given** a registry where 2 keys meet the sweep predicate

**When** the operator runs `suspend-sweep --dry-run`

**Then** exit code is 0
**And** stdout renders a preview table with 2 rows, yellow `to-suspend` status badges, and a footer `2 key(s) would be suspended. Run without --dry-run to proceed.`
**And** the real DB has zero modified rows (the two eligible keys are still `active`)
**And** zero audit rows were written (no per-key, no summary)
**And** the sentinel mtime is unchanged

### AC8 — `--dry-run` with empty preview renders an informational message

**Given** a registry where no keys meet the sweep predicate

**When** `suspend-sweep --dry-run` runs

**Then** exit code is 0
**And** stdout renders `No keys would be suspended by the sweep on 2026-04-06.`
**And** no table renders
**And** zero audit rows written

### AC9 — NFR3 performance budget: sweep under 1 s for 1 000 active keys

**Given** 1 000 active manual keys all with `paid_until='2026-01-01'`

**When** `run_suspension_sweep(conn, today=date(2026, 4, 6))` is timed via `time.perf_counter()`

**Then** elapsed wall-clock time is under 1 000 ms
**And** all 1 000 keys are flipped to `suspended`
**And** 1 000 per-key audit rows + 1 summary row are committed
**And** `EXPLAIN QUERY PLAN` on the UPDATE statement shows `USING INDEX idx_api_key_sweep` (advisory; marked skippable if SQLite patch-version drift breaks the exact string match)

### AC10 — NFR23 WAL invariant: sweep does not block concurrent auth reads

**Given** the DB is opened in WAL journal mode (invariant set at `get_connection` time)

**When** a sweep is running in one connection

**Then** a second connection can concurrently SELECT from `api_key` without blocking (documented by construction; tested indirectly via the WAL-mode assertion in `test_get_connection_uses_wal` — already covered by Story 1.1)
**And** this story does NOT add a `BEGIN IMMEDIATE` / lock-escalation path that would break the invariant

### AC11 — Cron triggers the sweep at 00:30 operator TZ

**Given** `bootstrap.yml` installed the `comadre-daily-suspension` cron entry

**When** the operator reviews the crontab via `crontab -l`

**Then** the output contains a line `CRON_TZ=America/Sao_Paulo` (or the configured `billing_timezone`)
**And** the output contains `30 0 * * * cd ~/comadre && docker compose exec -T tts-service comadre-keys suspend-sweep 2>&1 | logger -t comadre-suspension-sweep`
**And** running `ansible-playbook bootstrap.yml` a second time reports `ok` on the cron task (idempotence)
**And** running `ansible-playbook cleanup.yml` removes both the `CRON_TZ` envvar line and the suspension cron line

### AC12 — No changes to auth, rate-limit, or cache code

**Given** the diff at story completion

**When** `git diff src/comadre/api.py src/comadre/rate_limit.py src/comadre/keys/auth.py src/comadre/keys/cache.py` is inspected

**Then** the diff is empty
**And** `git diff pyproject.toml uv.lock src/comadre/keys/migrations/` is empty
**And** no new `@app.command` decorator is added outside `system.py`
**And** `src/comadre/main.py` has no diff (sweep is CLI-only, never loaded by the FastAPI runtime)

### AC13 — PII-austere logging (NFR15)

**Given** any successful `suspend-sweep` invocation

**When** the INFO log line is emitted

**Then** the line contains the fields `cutoff=`, `swept_count=`, `completed_at=`, `dry_run=`
**And** the line does NOT contain any customer name, email, CPF/CNPJ (any digit run of length 11–14), plaintext bearer (`cmdr_live_`), SHA-256 hash (64 hex), `Authorization` header substring, or any `key_id` / `key_prefix` at INFO level
**And** the PII-forbidden regex from Story 3.1 (`cmdr_live_|[0-9a-f]{64}|[0-9]{11,14}|@[a-z0-9.-]+\.[a-z]{2,}`) finds zero matches in the caplog records for the sweep run

### AC14 — Error hint never echoes invalid operator input (NFR16)

**Given** a misconfigured environment (missing `KEY_REGISTRY_ENCRYPTION_KEY` OR invalid `BILLING_TIMEZONE`)

**When** `suspend-sweep` runs

**Then** stderr renders the canonical error panel
**And** the panel's hint body does NOT contain the raw rejected value except where it is demonstrably safe (a valid IANA string echoed in an error is acceptable; an attacker-controlled malformed envvar is not echoed verbatim)
**And** exit code is 6

### AC15 — `cron:suspension-sweep` is the actor regardless of trigger

**Given** a human operator runs `comadre-keys suspend-sweep` interactively OR cron runs it at 00:30

**When** the sweep completes and writes audit rows

**Then** every new audit row (per-key + summary) has `actor='cron:suspension-sweep'`
**And** NO audit row has `actor='cli:<unix-username>'`

### AC16 — `get_last_sweep_timestamp` powers FR43 queryability

**Given** at least one sweep has completed on the DB

**When** `get_last_sweep_timestamp(conn)` is called

**Then** it returns the `occurred_at` of the most-recent `action='cron_suspend' AND target_type='system'` audit row
**And** the return value is a canonical ISO-UTC string (`%Y-%m-%dT%H:%M:%SZ`)
**And** on a fresh DB with no sweeps, the helper returns `None`
**And** per-key `suspend_key` audit rows are NOT candidates — only `target_type='system'` summary rows count (defense against future action-name collisions)

### AC17 — Sweep is idempotent across repeated invocations

**Given** a sweep that suspended N keys

**When** the same sweep runs again within the same `today` (no `mark-paid` in between)

**Then** exit code is 0
**And** `swept_count == 0` on the second run (first run already moved eligible keys out of the `status='active'` set)
**And** a second summary audit row is written (the sweep *ran*, even on zero effect)
**And** the total number of summary rows is now 2; the total number of per-key rows is still N

### AC18 — Sweep / reactivation / resweep cycle produces a coherent audit tail

**Given** key X is suspended by the sweep on day D1 (`paid_until=D0, today=D1`)
**And** the operator runs `mark-paid X --until D3` on day D2 (reactivates per Story 3.1 AC20)
**And** the sweep runs again on day D4 (`paid_until=D3 < D4`)

**When** `comadre-keys show X --audit-tail 5` is rendered

**Then** the tail shows 3 events in order: `SUSPEND_KEY` (actor `cron:suspension-sweep`, D1), `MARK_PAID` (actor `cli:<user>`, D2, `reactivated=true`), `SUSPEND_KEY` (actor `cron:suspension-sweep`, D4)
**And** the audit-tail renderer (from Story 1.4) renders all three without modification

### AC19 — `suspend-sweep` surfaces at top-level `comadre-keys --help`

**Given** `comadre-keys --help`

**When** the help text is rendered

**Then** `suspend-sweep` appears as a top-level command (flat, not nested under `system`)
**And** its one-line description matches the first sentence of `suspend_sweep_cmd`'s docstring

## Tasks / Subtasks

- [x] **Task 1 — Add `SuspensionSweepResult` dataclass + `run_suspension_sweep` helper in `src/comadre/keys/db.py`** (AC1, AC2, AC3, AC4, AC5, AC6, AC9, AC10, AC15)
  - [x] 1.1 Append `@dataclass(frozen=True, slots=True) class SuspensionSweepResult` near `SuspendKeyResult` (L124-128).
  - [x] 1.2 Implement `run_suspension_sweep(conn, *, today, actor="cron:suspension-sweep") -> SuspensionSweepResult` per §1 spec.
  - [x] 1.3 Use the `UPDATE ... RETURNING id, paid_until` shape to eliminate TOCTOU.
  - [x] 1.4 Write per-key `action='suspend_key'` rows + one summary `action='cron_suspend'` / `target_type='system'` row.
  - [x] 1.5 Always write the summary row — even on `swept_count=0`.
  - [x] 1.6 Call `_touch_auth_cache_sentinel(conn)` after commit.
  - [x] 1.7 Mypy + ruff clean.

- [x] **Task 2 — Add `get_last_sweep_timestamp(conn)` read helper in `src/comadre/keys/db.py`** (AC4, AC16)
  - [x] 2.1 One-function addition near `run_suspension_sweep`.
  - [x] 2.2 Query `MAX(occurred_at)` gated by `action='cron_suspend' AND target_type='system'`.
  - [x] 2.3 Return `None` on fresh DB; never raise.

- [x] **Task 3 — Add `suspend_sweep_cmd` in `src/comadre/keys/cli/commands/system.py`** (AC1, AC4, AC7, AC8, AC11, AC13, AC14, AC15, AC17, AC19)
  - [x] 3.1 Import `load_settings_and_tz` from `keys.py` and `resolve_today_in_tz` from `_clock.py` (matches the billing-command pattern).
  - [x] 3.2 Decorator `@app.command("suspend-sweep")` with `--dry-run` flag.
  - [x] 3.3 Settings + TZ validation ladder (exit 6).
  - [x] 3.4 DB open + migrations (exit 5).
  - [x] 3.5 Dry-run branch: `list_api_keys(conn, status='active', billing_mode='manual')` + Python filter + sort + `render_suspend_sweep_preview` (populated) or `render_empty_state` (zero). Zero writes.
  - [x] 3.6 Real-run branch: `run_suspension_sweep(conn, today=today, actor='cron:suspension-sweep')`. Catch `sqlite3.Error` / `RuntimeError` → exit 5.
  - [x] 3.7 Structured INFO log (PII-austere — aggregate counts only, wrapped in `contextlib.suppress(Exception)`).
  - [x] 3.8 ConfirmationLine via `render_confirmation(...)` with the canonical phrasing from §3 step 8.
  - [x] 3.9 Extend the `system.py` module docstring to include exit code 5 (currently only 0/2/6).

- [x] **Task 4 — Add `render_suspend_sweep_preview` in `src/comadre/keys/cli/output.py`** (AC7)
  - [x] 4.1 Signature `def render_suspend_sweep_preview(rows: list[ApiKeyListRow], cutoff_date: date) -> None`.
  - [x] 4.2 Title `f"Dry-run preview: keys to suspend at cutoff {cutoff_date.isoformat()}"`.
  - [x] 4.3 Columns: Prefix | Customer | Status | Price | Paid Until (no Days Left column — see rationale §4).
  - [x] 4.4 Status cell: hard-coded `Text("to-suspend", style="yellow")`.
  - [x] 4.5 Footer: `render_confirmation(f"{len(rows)} key(s) would be suspended. Run without --dry-run to proceed.")`.
  - [x] 4.6 Row-data interpolation uses `Text(row.customer_name)` wrapper to defeat Rich markup injection (same guard principle as Story 3.2's `render_revenue_report`).

- [x] **Task 5 — Ansible cron entries** (AC11)
  - [x] 5.1 Add `billing_timezone: "America/Sao_Paulo"` to `deploy/ansible/inventory/production.yml` + `.example` + `oracle.yml` + `.example`.
  - [x] 5.2 Append `CRON_TZ` envvar task + `comadre-daily-suspension` cron task to `bootstrap.yml` per §5 spec.
  - [x] 5.3 Append symmetric removal tasks to `cleanup.yml`.
  - [x] 5.4 Update the "Next steps" summary in `bootstrap.yml` (L328-358) to mention the sweep is now installed.
  - [ ] 5.5 `ansible-playbook --check` smoke pass (manual — deferred to 10.10.10.207 acceptance gate; see Completion Notes).

- [x] **Task 6 — DB tests** (AC1, AC2, AC3, AC4, AC5, AC6, AC9, AC15, AC16, AC17)
  - [x] 6.1 Create `tests/test_keys_db_suspend_sweep.py` per §10 spec (17 test cases — 15 planned + 2 additional).
  - [x] 6.2 Reuse the `tmp_path` + `get_connection` + `_apply_migrations` + raw-SQL seed pattern established across `test_keys_db.py`.
  - [x] 6.3 Include the NFR3 1K-key benchmark with `< 1000 ms` slack.
  - [x] 6.4 Rollback test covers TOCTOU-free `RETURNING` behavior.

- [x] **Task 7 — CLI tests** (AC1, AC4, AC7, AC8, AC11, AC13, AC14, AC15, AC17, AC18, AC19)
  - [x] 7.1 Create `tests/test_keys_cli_suspend_sweep.py` per §10 spec (13 test cases).
  - [x] 7.2 Scaffolding copied from `tests/test_keys_cli_mark_paid.py` (buffers fixture, env fixture, PII regex, CliRunner wiring).
  - [x] 7.3 Time-freeze via `monkeypatch.setattr(system_cmd, "resolve_today_in_tz", lambda _tz: date(2026, 4, 6))`.
  - [x] 7.4 AC18 end-to-end cycle test chains sweep → mark-paid → sweep and asserts audit tail.

- [x] **Task 8 — Renderer tests** (AC7)
  - [x] 8.1 Add `test_shape` to `tests/test_keys_output.py::TestRenderSuspendSweepPreview`.
  - [x] 8.2 Add `test_markup_injection_guarded` (defense-in-depth parallel to Story 3.2).

- [x] **Task 9 — Docs sweep** (CLAUDE.md / README.md / docs/configuration-reference.md)
  - [x] 9.1 `CLAUDE.md` CLI bullet — append `suspend-sweep` to the system cluster.
  - [x] 9.2 `CLAUDE.md` "Non-Obvious Gotchas" — add the strict `paid_until < today` note.
  - [x] 9.3 `README.md` — append manual / dry-run one-liners.
  - [x] 9.4 `docs/configuration-reference.md` — note `BILLING_TIMEZONE` must match `CRON_TZ`.

- [x] **Task 10 — Sanity gates**
  - [x] 10.1 `uv run ruff check .` clean.
  - [x] 10.2 `uv run mypy src/` clean.
  - [x] 10.3 `uv run pytest` — 1250 passed (baseline 1218 + 32 new).
  - [x] 10.4 `uv run pre-commit run --all-files` clean.
  - [x] 10.5 Grep-check suite per §11.
  - [ ] 10.6 Manual smoke on 10.10.10.207 — deferred to deploy-time acceptance gate.

## Dev Notes

### Import-graph placement

```
keys/cli/commands/system.py → {
    keys/cli/commands/keys.py        (load_settings_and_tz)
    keys/cli/_clock.py                (resolve_today_in_tz)
    keys/cli/output.py                (render_error, render_confirmation,
                                       render_empty_state, render_suspend_sweep_preview [NEW])
    keys/db.py                        (get_connection, _apply_migrations,
                                       list_api_keys, run_suspension_sweep [NEW],
                                       get_last_sweep_timestamp [NEW])
    keys/models.py                    (ApiKeyListRow)
    keys/audit.py                     (unused at the CLI level — the DB helper calls log_event)
    comadre.config                    (get_settings — via load_settings_and_tz)
    comadre.logging                   (get_logger)
}
```

No reverse edges. `keys/auth.py`, `rate_limit.py`, `main.py`, `api.py`, `keys/cache.py`, `keys/counters.py` do NOT import from `system.py` or `db.py`'s new symbols. The sweep is strictly a CLI + DB write path.

### Why the sweep belongs in `system.py`, not `billing.py`

Architecture `§357` is explicit: `system.py → health, rotate-encryption-key, cache-status, suspend-sweep`. The sweep is an operational verb — cron runs it, humans only trigger it to recover from a failed cron. It is NOT a verb the operator types during the Day-05 billing ritual (that's `list-keys`, `mark-paid`, `at-risk`, `revenue` — all of which live in `billing.py`).

The read-vs-write axis is orthogonal: `cache-status` and `health` are read-only, `rotate-encryption-key` and `suspend-sweep` are write. Grouping them by "operational surface" (as opposed to "billing surface") keeps the CLI module map legible.

### Why `UPDATE ... RETURNING` and not `SELECT ... ; UPDATE ...`

Two reasons:

1. **Atomicity.** A pre-UPDATE SELECT + a separate UPDATE creates a TOCTOU window between identification and mutation. A concurrent CLI `mark-paid` (on another SSH session) between the two statements would flip a row back to a paid state; the UPDATE's `paid_until < ?` predicate then no-ops on that row, but the pre-UPDATE SELECT already recorded it as swept — leading to a ghost audit row without a real state change. `RETURNING` eliminates the gap by making identification a side-effect of the UPDATE.
2. **Performance.** `UPDATE ... RETURNING` is one SQL statement, one B-tree walk, one transaction-log entry. The SELECT+UPDATE form is two walks and two log entries. On 1K keys the delta is ~10ms either way — not load-bearing — but the `RETURNING` shape is the textbook idiom and the simpler code.

SQLite 3.35 added `RETURNING` (March 2021); Python 3.12 ships 3.41+. No compatibility concern.

### Why `action='cron_suspend'` on the summary row

Architecture `§324` explicitly reserves this name: "Cron actions: `cron_suspend` (daily sweep)". Using a different string would create a silent drift between the architecture doc and the implementation. Story 3.4's `health` command will `WHERE action='cron_suspend'`; any other name breaks 3.4 without warning.

Story 3.1's audit-action scheme uses `suspend_key` for *per-key* suspensions (manual + cron share this action, disambiguated via `actor`). The summary row uses a distinct action (`cron_suspend`) because it describes the *sweep operation*, not a per-key mutation. The two rows answer different questions:

- "Who suspended this specific key and when?" → per-key `suspend_key` row.
- "When did the sweep last run (even if it suspended nothing)?" → summary `cron_suspend` row.

### Why the sweep hardcodes the actor but the DB helper accepts a parameter

CLI always passes `'cron:suspension-sweep'` (regardless of whether a human or cron invoked it). Tests need to vary the actor string for fixture disambiguation (e.g., seed "historical" sweep rows with `actor='test:sweep-2026-03-06'` to verify `get_last_sweep_timestamp` ordering). Making the parameter mandatory-string at the helper level, with a CLI-side default, is the cleanest separation.

### Why no `--format json` on `suspend-sweep`

Cron is zero-touch. JSON output would invite operator scripts to parse the sweep's stdout — coupling automation to a command's output shape. The audit log is the canonical machine-readable interface: `comadre-keys show <prefix> --audit-tail N` renders the per-key suspensions; Story 3.4's `health --format json` will expose the summary-row timestamp. Keeping `suspend-sweep` intentionally minimal forces consumers to the right data surface.

The `--dry-run` preview is operator-facing only — the rare-but-real "let me see what would happen before I run it" workflow — and is rendered via the same StatusTable machinery as the billing reports for visual consistency.

### Why `CRON_TZ` via the ansible `cron` module's `env: true`

Cron's `CRON_TZ=<iana>` envvar is interpreted by `cron` itself (Debian/Ubuntu's default `cron` package, since Jessie) to translate the schedule fields. Setting it once at the top of the crontab file makes all subsequent entries TZ-aware. The alternative — computing the UTC-equivalent hour/minute at Ansible template time via `{{ ... | to_datetime(...) }}` — is fragile against DST transitions.

**DST caveat.** Brazil abolished DST in 2019, so `America/Sao_Paulo` is DST-free. Operators in DST-observing TZ configurations (e.g., `Europe/Berlin`) will see the sweep fire at 00:30 local time year-round, with the cron schedule silently skipping one hour in spring and duplicating one hour in fall. For MVP this is acceptable — the sweep is idempotent (AC17), so a skipped run catches up at the next fire, and a duplicated run is a no-op. Document the caveat in `docs/configuration-reference.md` and move on. A robust-against-DST design (systemd-timer, or `RandomizedDelaySec`) can follow if an operator actually deploys in a DST zone.

### NFR3 performance budget

1 000 active manual keys → single UPDATE with `idx_api_key_sweep` partial index covers the WHERE clause at O(log N + matched_rows). On tmpfs SQLite, the UPDATE itself lands in ~5 ms. The 1 000 per-key `log_event` inserts each go through a `conn.execute` call with parameterized binding — ~30 µs per insert on modern SQLite, so 30 ms total. The summary row + the fsync on commit + the sentinel touch add ~10 ms. **Budget headroom is 10×** — a 100 ms sweep on 1 K keys, with a 1 000 ms NFR3 ceiling. Test assertion uses `< 1000 ms` slack to tolerate CI jitter; actual production figures should track <100 ms.

### Performance risk: audit_log scaling

After one year of daily sweeps, the audit_log grows by ~365 summary rows + ~N_expired per-key rows. For a 20-customer VPS this is trivial (a few KB/year). For a 1 000-customer portfolio with 5 % monthly delinquency, it's ~50 rows/day, ~18 000/year — still well under SQLite's performance thresholds. The `idx_audit_occurred` index keeps `get_last_sweep_timestamp`'s `MAX(occurred_at)` at O(log N) forever. Not a scaling concern.

### Integration with Story 3.4 `health` (forward reference)

Story 3.4's `health` command consumes `get_last_sweep_timestamp(conn)` to render a "Last suspension sweep: 2026-04-06T03:30:12Z" line. No new work for Story 3.3 beyond exposing the helper; Story 3.4's story file will cite this exact helper signature as a `Builds on` entry.

### Test-flake avoidance

- **Do NOT monkeypatch `date.today` globally.** Use `monkeypatch.setattr("comadre.keys.cli._clock.resolve_today_in_tz", lambda tz: date(2026, 4, 6))` — same idiom as Stories 1.6 / 3.1 / 3.2.
- **Seed canonical `paid_until`.** Always `'2026-04-05'`. Any non-canonical form would silently break the lex-order comparison. (Story 3.1 `mark-paid`'s `_parse_until` canonicalizes on write; seed rows bypass that path.)
- **Assert audit rows via parsed JSON**, not byte strings — `json.loads(row["details_json"]) == {"paid_until": "2026-04-05", "cutoff_date": "2026-04-06"}`. The Story 3.1 deferred note already flagged byte-string assertions as a test-hygiene debt; don't add new instances.
- **Sentinel assertion uses `sentinel.stat().st_mtime > sweep_start_mtime`** (not `!=`). Mtime on some filesystems is second-precision; same-second touches produce equal mtimes. Use `time.sleep(0.01)` before the sweep to guarantee a post-test mtime delta, or monkeypatch the test to pre-read the sentinel mtime → advance the clock → sweep → assert strict-greater.
- **NFR3 performance test uses `elapsed_ms < 1000` on CI, with a comment noting the actual figure should be <100 ms on bare metal.** A regression that doubles sweep time to 200 ms wouldn't fail this test — and that's intentional. Performance regression is a separate concern from correctness; treat this assertion as a smoke, not a benchmark.

### Integration with Story 2.1 / Story 2.2 auth path

The auth cache sentinel propagates status changes to every running API replica within 60 s (the `AuthCache` TTL) or instantly on the next cache-miss (sentinel mtime check). A key suspended by the sweep at 00:30 will 401 on the very next API request from that customer, regardless of which replica they land on. Story 2.1's `ApiKeySuspendedError` envelope provides the customer-facing message.

### Deferred work to flag at story close

Add to `deferred-work.md`:

- **No DST-aware scheduling for non-DST-free operators.** `CRON_TZ` in cron honors DST transitions but skips/duplicates the local 00:30 slot on DST days. The sweep is idempotent so the effect is bounded (AC17), but a systemd-timer-based schedule with `RandomizedDelaySec` would be more robust. Revisit if a non-Brazil operator deploys Comadre.
- **Sweep does not clean the auth cache directly.** The sentinel-file mechanism has a 60 s worst-case propagation bound. A direct HTTP call from the CLI to an internal "invalidate these key_ids" endpoint would bring the bound to zero — but requires a new API surface. Out of scope for 3.3.
- **`EXPLAIN QUERY PLAN` assertion is advisory-only.** The AC9 check for `USING INDEX idx_api_key_sweep` in the plan is marked skippable because SQLite's plan output format varies across patch versions. A stable assertion requires either a plan-parsing library or a direct `stat1` table inspection. Not worth the maintenance surface for 3.3.
- **Sweep has no rate-limit-bucket reset.** A key that hits 429 at 00:00 and is swept at 00:30 keeps its `limits` library bucket entry in memory until the bucket's window expires. If the operator `mark-paid`s the key at 01:00 and reactivates it, the key resumes against the same bucket. This is correct by design (the bucket is keyed by `key_id`, which is stable across status changes — see Story 2.2 §Builds on) but means a suspended-then-reactivated key might see a stale `Retry-After` header for a few seconds after reactivation. Documented in `docs/rate-limiting.md` already; not a sweep-specific concern.
- **Sweep's `details_json` carries no customer-facing reason string.** An operator who hard-deletes a customer's key rows for LGPD would lose the "why" of the cron suspension (beyond the derived `paid_until < cutoff_date` arithmetic). Story 4.1's LGPD export + delete workflow must preserve the audit trail; the sweep's JSON-structured audit shape is designed for that.
- **`get_last_sweep_timestamp` does not distinguish "sweep has never run" from "audit log was pruned"**. Both return `None`. If a future story adds audit-log retention (pruning rows older than N days), the semantic changes silently. Pair with audit-retention design when that story lands.

### Project Structure Notes

**New files:**

```
tests/
  test_keys_db_suspend_sweep.py                 [NEW]
  test_keys_cli_suspend_sweep.py                [NEW]
```

**Modified files:**

```
src/comadre/keys/
  db.py                                         [MOD — SuspensionSweepResult dataclass + run_suspension_sweep + get_last_sweep_timestamp]
  cli/commands/system.py                        [MOD — suspend_sweep_cmd + module-docstring exit-5 extension]
  cli/output.py                                 [MOD — render_suspend_sweep_preview]

tests/
  test_keys_output.py                           [MOD — 2 renderer cases]

deploy/ansible/
  playbooks/bootstrap.yml                       [MOD — CRON_TZ + comadre-daily-suspension cron entries]
  playbooks/cleanup.yml                         [MOD — symmetric removal]
  inventory/production.yml                      [MOD — billing_timezone var]
  inventory/production.yml.example              [MOD — same]
  inventory/oracle.yml                          [MOD — same]
  inventory/oracle.yml.example                  [MOD — same]

docs/
  configuration-reference.md                    [MOD — BILLING_TIMEZONE / CRON_TZ note]

CLAUDE.md                                       [MOD — CLI command list + strict < gotcha]
README.md                                       [MOD — manual / dry-run one-liners]
```

**Unchanged (asserted by AC12):**

```
src/comadre/rate_limit.py                       — rate-limit path untouched
src/comadre/api.py                              — no new route, no middleware change
src/comadre/main.py                             — sweep never loaded by FastAPI runtime
src/comadre/keys/auth.py                        — auth path untouched
src/comadre/keys/cache.py                       — no cache code change (sentinel touch is the existing propagation mechanism)
src/comadre/keys/billing.py                     — BillingProvider ABC untouched; the sweep is SQL-driven, not provider-driven
src/comadre/keys/migrations/v001_initial.sql    — no schema change; idx_api_key_sweep already tuned
src/comadre/keys/cli/commands/billing.py        — no new verb added here; sweep lives in system.py
src/comadre/keys/cli/app.py                     — system_app already registered; no new extend call
pyproject.toml, uv.lock                         — no new dependency
```

### Testing standards

- CLI tests use `CliRunner` from `typer.testing` + the `_reset_consoles_to_buffers` auto-fixture pattern (copy verbatim from `test_keys_cli_mark_paid.py` — canonical template).
- DB tests use `tmp_path` for the SQLite file + `get_connection` + `_apply_migrations`. Seed via `insert_api_key` / `insert_customer` (never hand-roll SQL).
- Time-freeze via `monkeypatch.setattr("comadre.keys.cli._clock.resolve_today_in_tz", ...)` returning a fixed `date` per test.
- `caplog` captures INFO log lines for AC13 PII assertions.
- Rich output capture via `result.stdout` / `result.stderr` from the `CliRunner().invoke(...)` call — the `_reset_consoles_to_buffers` fixture already plumbs stdout/stderr into `StringIO` buffers.
- JSON assertions on audit `details_json`: `json.loads(row["details_json"]) == {...}` — compare dicts, not byte strings.
- PII-regex guard: reuse `_PII_FORBIDDEN_RE` from Story 3.1's test files.

### References

- Epic 3 + Story 3.3 scope — `_bmad-output/planning-artifacts/epics.md:683-717`
- FR18 / FR31 / FR43 wording — `_bmad-output/planning-artifacts/prd.md:1147, 1177, 1184`
- NFR3 (1 s / 1 K keys) — `_bmad-output/planning-artifacts/prd.md:109`
- NFR23 (WAL invariant) — `_bmad-output/planning-artifacts/prd.md:135`
- Audit-action naming (`cron_suspend`, `cron:suspension-sweep`) — `_bmad-output/planning-artifacts/architecture.md:322-326`
- Cron pattern (host crontab calling docker compose exec) — `deploy/ansible/playbooks/bootstrap.yml:286-306` (existing `comadre-audio-cleanup` is the template)
- Transaction scope (single UPDATE for the sweep) — `_bmad-output/planning-artifacts/architecture.md:476`
- `idx_api_key_sweep` partial index — `src/comadre/keys/migrations/v001_initial.sql:44`
- Story 3.1 `suspend_key` helper (per-key action-name shared by manual and cron) — `src/comadre/keys/db.py:1242-1302`
- Story 3.1 `_touch_auth_cache_sentinel` pattern — `src/comadre/keys/db.py:193-219`
- Story 3.2 `list_api_keys` read path — `src/comadre/keys/db.py:508-565`
- Story 3.2 `render_at_risk_table` (template for `render_suspend_sweep_preview`) — `src/comadre/keys/cli/output.py:310-351`
- Story 2.3 `cache-status` CLI shape in `system.py` (template for new command) — `src/comadre/keys/cli/commands/system.py`
- Story 1.4 audit-tail renderer (consumes new rows without modification) — `src/comadre/keys/cli/output.py::render_audit_tail`
- PII-forbidden regex (NFR15 guard) — `tests/test_keys_cli_mark_paid.py::_PII_FORBIDDEN_RE`
- `first_charge_date` / `days_until` in `comadre.keys.billing` — unused by the sweep but noted for completeness (Story 3.2 / 3.4 consume them)
- Journey 2 (monthly billing ritual, Day-06 sweep) — `_bmad-output/planning-artifacts/ux-design-specification.md:572-631`

## Questions for Operator (please confirm before dev-story)

> All seven have recommended answers. In auto-mode, apply the recommended answer; if any run hits a disagreement, reopen as a deferred-work entry.

1. **Summary audit row action name = `cron_suspend`.** Architecture `§324` explicitly reserves this name. Confirm this is the canonical action for the summary row, distinct from the per-key `suspend_key` action. Alternative: `cron_suspend_sweep_ran` — more descriptive but departs from the architecture doc. Recommend `cron_suspend` + distinguish via `target_type='system'` (Story 3.4's health reader uses the compound predicate).

2. **Summary row always written — even on zero-row sweeps.** AC4 mandates this (FR43 requires the timestamp to be queryable even when no keys were suspended). Confirm this is correct; the alternative ("skip summary on zero-row sweeps") would make `health` report misleading staleness on slow-billing months.

3. **Sweep predicate uses strict `paid_until < today`, not `<=`.** A key with `paid_until = today` is still paid through today. The sweep catches it on the next morning. Matches FR18 "whose paid date has elapsed". Confirm.

4. **`--dry-run` is operator-facing only; no `--format json`.** The sweep is cron-first; JSON output on the write command would invite script-coupling to the sweep's stdout shape. The audit log is the canonical machine-readable surface. Confirm this scope.

5. **Actor is always `cron:suspension-sweep`, even when a human runs the CLI manually.** Audit trail describes behavior, not triggering identity. Alternative: `cli:<user>` when human, `cron:suspension-sweep` when cron — but then `health`'s "who suspends" query needs to union two actor strings. Recommend the hardcoded form.

6. **Cron TZ via `CRON_TZ` envvar at the top of the crontab.** The Ansible `cron` module sets this via `env: true`. Alternative: compute the UTC offset at Ansible template time — fragile against DST. Recommend `CRON_TZ`, document the DST caveat in deferred-work. For Brazil (DST-free since 2019) this is effectively free.

7. **Manual invocation path via `docker compose exec -T tts-service comadre-keys suspend-sweep`.** The `-T` flag is load-bearing under cron (no TTY). Confirm the cron entry follows the existing `comadre-audio-cleanup` shape; document the manual-run invocation in README the same way.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (Claude Opus 4.7, 1M-context Anthropic release)

### Debug Log References

- One mid-run test failure: `TestPIIGuard.test_pii_austere_log` initially used `caplog` to capture the INFO log, but `comadre.logging.get_logger` sets `propagate = False`, so caplog's root handler never sees the records. Switched to the custom-handler pattern already used by Story 3.2's `test_info_log_is_aggregate_and_pii_free` (attach a `logging.Handler` to `get_logger("keys.cli")` for the duration of the CLI invocation). Tests green on the second run.
- Ruff format pass rewrote two files (`test_keys_output.py`, `system.py`) on the first `pre-commit` run — style-only diffs (import ordering and trailing whitespace); no semantic changes. Re-ran tests + pre-commit after the reformat; all green.

### Completion Notes List

- Shipped `SuspensionSweepResult` dataclass + `run_suspension_sweep(conn, *, today, actor=...)` and `get_last_sweep_timestamp(conn)` in `src/comadre/keys/db.py`. Single-transaction sweep uses `UPDATE api_key ... RETURNING id, paid_until` over `idx_api_key_sweep`, writes one `action='suspend_key'` audit row per swept key + exactly one `action='cron_suspend' / target_type='system'` summary row (even on zero-row sweeps), then touches the auth-cache sentinel after commit. `completed_at` on the `SuspensionSweepResult` has byte-identity with the summary row's `occurred_at` (AC3) — required a minor additive change to `comadre.keys.audit.log_event` to accept an optional pre-computed `occurred_at`; documented in the helper docstring and verified by `test_writes_summary_cron_suspend_audit_row`.
- `suspend-sweep` CLI appended to `src/comadre/keys/cli/commands/system.py` with a `--dry-run` flag. Dry-run path does `list_api_keys(status='active', billing_mode='manual')` + Python filter/sort + the new `render_suspend_sweep_preview` table; zero writes. Real path calls the new helper with hardcoded `actor='cron:suspension-sweep'`. Exit codes 0/5/6 per §7; 2 never emitted (only flag is `--dry-run`). Module docstring extended to reflect the new exit-5 mapping.
- `render_suspend_sweep_preview` appended to `src/comadre/keys/cli/output.py`. Mirrors `render_at_risk_table` minus the `Days Left` column (preview rows are already past cutoff). Status cell hardcoded to yellow `to-suspend`; customer-name cell wrapped in `Text(...)` to neutralise Rich markup injection. The `date` import was added to the module header.
- Ansible cron installed: `bootstrap.yml` gets a `CRON_TZ=<billing_timezone>` envvar task + the `comadre-daily-suspension` entry (00:30 local, runs `docker compose exec -T tts-service comadre-keys suspend-sweep 2>&1 | logger -t comadre-suspension-sweep`). `cleanup.yml` has the symmetric removal. `billing_timezone: "America/Sao_Paulo"` added to all four inventory files (production, production.yml.example, oracle, oracle.yml.example). Bootstrap's "Next steps" summary now reports the sweep schedule line.
- Docs: `CLAUDE.md` CLI bullet updated + "Non-Obvious Gotchas" note added for the strict `paid_until < today` predicate and the `BILLING_TIMEZONE`↔`CRON_TZ` parity invariant. `README.md` gained a "Automated suspension sweep" bullet. `docs/configuration-reference.md` extended the `BILLING_TIMEZONE` row to call out the cron parity requirement.
- Tests: `tests/test_keys_db_suspend_sweep.py` (17 cases) + `tests/test_keys_cli_suspend_sweep.py` (13 cases) + 2 renderer cases appended to `tests/test_keys_output.py`. Baseline 1218 tests + 32 new = 1250 passing. `uv run ruff check .`, `uv run mypy src/`, `uv run pre-commit run --all-files` all green.
- Grep checks (§11) verified: `action='suspend_key'` has 2 hits in db.py (Story 3.1 + Story 3.3 sweep); `action='cron_suspend'` has 1 hit; `cron:suspension-sweep` has 2 hits (default param + CLI call site); no `HTTPException`, no raw `print()`, no `os.environ` in system.py. `git diff` confirms `api.py`, `rate_limit.py`, `auth.py`, `cache.py`, `main.py`, `billing.py`, `migrations/`, `pyproject.toml`, `uv.lock` all untouched (AC12).
- **Deferred to deploy-time acceptance**: Task 5.5 (`ansible-playbook --check` smoke) and Task 10.6 (manual smoke on 10.10.10.207 — `suspend-sweep --dry-run` against the real DB and observing the cron fire at 00:30 São Paulo time). CI does not run Ansible; these verifications belong to the next deploy window.
- **Follow-ups worth flagging to `deferred-work.md`** (per §Deferred work to flag at story close): no DST-aware scheduling (AC17 idempotence keeps the blast radius bounded), sweep does not directly HTTP-invalidate the auth cache (sentinel mechanism has a 60 s worst-case bound), `EXPLAIN QUERY PLAN` advisory check was not wired into the test suite (SQLite plan-string drift), sweep's `details_json` lacks a customer-facing reason string (forward concern for Story 4.1's LGPD export), and `get_last_sweep_timestamp` returns `None` for both "never ran" and "audit log pruned" (pair with audit-retention design if and when that story lands).

### File List

**New:**
- `src/comadre/keys/db.py` additions — `SuspensionSweepResult` dataclass, `run_suspension_sweep(...)` helper, `get_last_sweep_timestamp(...)` helper (within existing module; see diff)
- `src/comadre/keys/cli/commands/system.py` additions — `suspend_sweep_cmd` Typer command + `_suspend_sweep_dry_run` private helper (within existing module)
- `src/comadre/keys/cli/output.py` addition — `render_suspend_sweep_preview(...)` renderer (within existing module)
- `tests/test_keys_db_suspend_sweep.py` — 17 unit tests for the DB helpers
- `tests/test_keys_cli_suspend_sweep.py` — 13 end-to-end CLI tests

**Modified:**
- `src/comadre/keys/audit.py` — `log_event(...)` gained an optional `occurred_at` parameter so the sweep can pin the summary-row timestamp for byte-identity with `SuspensionSweepResult.completed_at`
- `src/comadre/keys/db.py` — additions described above (dataclass + two helpers)
- `src/comadre/keys/cli/commands/system.py` — additions described above + module-docstring exit-code contract extended with 5
- `src/comadre/keys/cli/output.py` — `render_suspend_sweep_preview` + `date` added to the datetime import
- `tests/test_keys_output.py` — `render_suspend_sweep_preview` added to the import list + new `TestRenderSuspendSweepPreview` class (2 cases)
- `deploy/ansible/playbooks/bootstrap.yml` — new `CRON_TZ` envvar task + `comadre-daily-suspension` cron task + "Next steps" summary line
- `deploy/ansible/playbooks/cleanup.yml` — symmetric removal for the two new cron entries + summary-block update
- `deploy/ansible/inventory/production.yml` — `billing_timezone` variable
- `deploy/ansible/inventory/production.yml.example` — same
- `deploy/ansible/inventory/oracle.yml` — same
- `deploy/ansible/inventory/oracle.yml.example` — same
- `CLAUDE.md` — CLI command list gained `suspend-sweep`; new "Non-Obvious Gotcha" covering strict `<` semantics and `BILLING_TIMEZONE`↔`CRON_TZ` parity
- `README.md` — added "Automated suspension sweep" feature bullet
- `docs/configuration-reference.md` — `BILLING_TIMEZONE` row extended with the `CRON_TZ` parity requirement
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — 3-3 flipped ready-for-dev → in-progress → review
- `_bmad-output/implementation-artifacts/3-3-automated-suspension-sweep-cron.md` — status transitions + Tasks/Subtasks completion + Dev Agent Record

### Change Log

- 2026-04-19 — Story 3.3 implemented end-to-end. Added bulk suspension sweep helper + CLI verb + renderer + Ansible cron entries + tests + docs. 1250 tests pass (baseline 1218 + 32 new). Ruff / mypy / pre-commit clean. Auth path, rate-limit path, and migrations untouched per AC12.
- 2026-04-19 — Code review complete. 1 decision resolved (`billing_timezone` default flipped from `America/Sao_Paulo` to `UTC` — operator-neutral, internationally predictable default; customer-notice framing added to `docs/configuration-reference.md` + `docs/deployment-guide.md`; touches `src/comadre/config.py`, `tests/test_config.py`, `deploy/ansible/playbooks/bootstrap.yml`, `deploy/ansible/inventory/*.yml.example`, `README.md`, `CLAUDE.md`). 11 patches applied:
  - Ansible cron now wraps the sweep in `/bin/bash -c 'set -o pipefail; … | logger'` so exit codes 5/6 propagate to cron's MTA instead of being absorbed by `logger`.
  - `run_suspension_sweep` samples `completed_at` *after* the UPDATE and pins `occurred_at` on every audit row (per-key + summary) so the sweep is a single atomic timestamp — audit ordering by `(occurred_at, id)` now matches insertion order.
  - `get_last_sweep_timestamp` rewritten as `ORDER BY occurred_at DESC, id DESC LIMIT 1` for deterministic tie-break on same-second sweeps.
  - CLI exit-5 branches changed from `raise typer.Exit(code=5) from None` to `from exc` so the underlying exception preserves `__cause__` for cron-captured stderr forensics.
  - `render_at_risk_table` + `render_suspend_sweep_preview` `assert row.paid_until is not None` replaced with runtime `if ... continue` guards (survives `python -O`).
  - Dry-run emits a WARN log on malformed `paid_until` instead of silently dropping the row.
  - Dry-run sort key dropped the dead `or ""` fallback (caller guarantees non-None).
  - `_PII_FORBIDDEN_RE` extended to cover formatted CPF (`xxx.xxx.xxx-xx`) and CNPJ (`xx.xxx.xxx/xxxx-xx`).
  - `test_db_error_exits_5` rewritten to force a deterministic `sqlite3.OperationalError` via monkeypatch on `get_connection` and assert `exit_code == 5` (was `!= 0`).
  - `test_sweep_never_touches_sentinel_on_rollback` now pre-seeds the sentinel with a baseline mtime and asserts `mtime == baseline_mtime` on rollback (matches AC6 wording).
  - `test_performance_budget_nfr3` now asserts the 1 000 per-key + 1 summary audit rows alongside the wall-clock budget.
- 2026-04-19 — Status: review → done. Full suite 1250/1250 across 3 consecutive runs. ruff / mypy / yamllint / shellcheck / markdownlint / pre-commit all green. 8 deferred items logged in `_bmad-output/implementation-artifacts/deferred-work.md` under the story-3-3 heading.

### Review Findings

Raw reviewer outputs under `_bmad-output/implementation-artifacts/review-3-3/` (`blind-hunter.md`, `edge-case-hunter.md`, `acceptance-auditor.md`). Triage below; `[x]` are deferred to `deferred-work.md`, `[ ]` are open.

- [x] [Review][Decision] **CRON_TZ=America/Sao_Paulo retroactively re-anchors `comadre-daily-restart` and `comadre-audio-cleanup`** — RESOLVED 2026-04-19 by flipping the default `billing_timezone` from `America/Sao_Paulo` to `UTC` across `src/comadre/config.py` (Python default), `deploy/ansible/playbooks/bootstrap.yml` (Ansible jinja default), `deploy/ansible/inventory/production.yml.example`, `deploy/ansible/inventory/oracle.yml.example`, `docs/configuration-reference.md`, `docs/deployment-guide.md`, `tests/test_config.py` (assertion), `README.md`, and `CLAUDE.md`. Rationale: billing TZ is a contractual input with customer-visible consequences (paid_until day-turnover, 401 flip timing), so it must be internationally predictable by default. UTC keeps the pre-existing `restart_hour: 3` and `*/6` audio-cleanup schedules semantically unchanged (Oracle Cloud VPS host was already UTC), and the `CRON_TZ=UTC` + host-UTC pair is a no-op in terms of wall-clock drift. Operators who explicitly set `billing_timezone: "America/Sao_Paulo"` in inventory opt into the full Comadre-cron-bundle shift knowingly. Docs now include an explicit customer-notice requirement in `docs/configuration-reference.md` and `docs/deployment-guide.md`.
- [x] [Review][Patch] **Cron pipeline `cmd | logger` silently swallows non-zero exit codes** [deploy/ansible/playbooks/bootstrap.yml:319-322] — Pipeline exit is `logger`'s status (0) under the default POSIX `sh` cron invokes, so exits 5 (DB error) and 6 (config error) never reach cron's MTA. Directly contradicts §5 rationale ("The sweep CLI's own exit code captures the failure; bubbling a non-zero exit into cron's MTA mail is the operator's alerting channel"). The sister `comadre-audio-cleanup` entry uses `|| logger` (on-failure fallback that preserves exit), and the new entry diverges. Fix options: `/bin/bash -c 'set -o pipefail; … | logger …'`, or redirect via `>> /var/log/comadre/suspend.log 2>&1`, or mirror the `|| logger` pattern and drop the pipe.
- [x] [Review][Patch] **Per-key `suspend_key` audit rows not pinned to `completed_at`; summary row timestamp precedes its own detail rows in `occurred_at` order** [src/comadre/keys/db.py:~1423, ~1439-1447] — `completed_at` is sampled *before* the `with conn:` block, then reused only for the summary row; per-key `log_event` calls inside the loop each resample `_utcnow_iso()`. Result: ordered by `occurred_at`, the summary (earlier) precedes the per-key rows (later) — reverse of logical / insertion order. Fix: compute `completed_at` once and pass `occurred_at=completed_at` to both per-key and summary `log_event` calls so the sweep is a single atomic timestamp. Also resolves the misleading docstring wording ("the sweep wrote on its summary audit row").
- [x] [Review][Patch] **`test_db_error_exits_5` does not actually assert exit code 5** [tests/test_keys_cli_suspend_sweep.py:~400] — Current assertion is `exit_code != 0` with a comment acknowledging the weakness; §7 exit-code contract + AC14 + three reviewers flag this. Regression that maps DB errors to exit 1 would pass. Fix: force a `sqlite3.Error` deterministically (e.g., `monkeypatch.setattr(system_cmd, "get_connection", _raise_sqlite_error)`) and assert `result.exit_code == 5`.
- [x] [Review][Patch] **`raise typer.Exit(code=5) from None` suppresses `__cause__` in all three DB-error branches** [src/comadre/keys/cli/commands/system.py:~329, ~337, ~349] — Original exception lost; cron-captured stderr shows only `"Database error: <str(exc)>"` with no traceback/type. Operators lose forensic signal on the precise path where it matters most. Fix: drop `from None` — the explicit `render_error(...)` already writes a clean user-facing message and Typer's own output only triggers on unhandled exceptions.
- [x] [Review][Patch] **`assert row.paid_until is not None` gets stripped under `python -O`** [src/comadre/keys/cli/output.py:~453] — If `PYTHONOPTIMIZE=1` ever enters the runtime (container image tweak, PyInstaller bundle), `None` flows into `_iso_date` and yields either an exception or the literal string "None" in the rendered table. Replace with a real guard (`if row.paid_until is None: continue` or raise a clear ValueError).
- [x] [Review][Patch] **Dry-run silently drops rows with malformed `paid_until`** [src/comadre/keys/cli/commands/system.py:~384-389] — `try: date.fromisoformat(...) except ValueError: continue` hides data corruption from the operator and creates dry-run/real-run divergence (SQL lex-compare vs Python parse). Emit a `WARN` log line per dropped row with the key prefix before `continue`; keeps the dry-run happy path but leaves forensic breadcrumbs.
- [x] [Review][Patch] **PII regex is blind to dotted/dashed CPF formats** [tests/test_keys_cli_suspend_sweep.py:~22] — `[0-9]{11,14}` requires 11 contiguous digits; a CPF rendered as `123.456.789-10` (Brazilian canonical) doesn't match. If a future log line quotes formatted CPFs, the test passes silently. Extend to `r"cmdr_live_|[0-9a-f]{64}|[0-9]{11,14}|\d{3}\.\d{3}\.\d{3}-\d{2}|\d{2}\.\d{3}\.\d{3}/\d{4}-\d{2}|@[a-z0-9.-]+\.[a-z]{2,}"` (covers CPF `xxx.xxx.xxx-xx` and CNPJ `xx.xxx.xxx/xxxx-xx`).
- [x] [Review][Patch] **Rollback test asserts sentinel `does not exist` instead of `mtime unchanged`** [tests/test_keys_db_suspend_sweep.py:~422-459] — Test deletes any pre-existing sentinel before the sweep and then asserts absence. AC6's wording ("sentinel mtime is unchanged") assumes a pre-seeded sentinel (the `_touch_auth_cache_sentinel` pattern leaves one after any prior mutation). A future refactor that moves the sentinel touch *inside* the `with conn:` block (Blind Hunter Medium #3) wouldn't fail this test because the rolled-back filesystem `touch` still removes the file. Strengthen: pre-seed sentinel via `sentinel.touch()`, capture `baseline_mtime`, assert `sentinel.stat().st_mtime == baseline_mtime` post-rollback.
- [x] [Review][Patch] **`get_last_sweep_timestamp` has no tie-breaker on same-second summary rows** [src/comadre/keys/db.py:~1483-1487] — `_utcnow_iso` has second resolution. Two sweeps in the same wall-second (manual + cron collision at 00:30:05) produce tied `occurred_at`; `MAX(occurred_at)` returns an arbitrary one. Fix: `SELECT occurred_at FROM audit_log WHERE action='cron_suspend' AND target_type='system' ORDER BY occurred_at DESC, id DESC LIMIT 1` — identical semantics on distinct timestamps, deterministic on ties.
- [x] [Review][Patch] **NFR3 performance test (`test_performance_budget_nfr3`) does not assert the 1000+1 audit rows** [tests/test_keys_db_suspend_sweep.py:~520-560] — AC9 explicitly requires "1 000 per-key audit rows + 1 summary row are committed". Current test only asserts `swept_count == 1000` and wall-clock. A regression that skips log_event under high volume passes. Add `assert conn.execute("SELECT COUNT(*) FROM audit_log WHERE action='suspend_key'").fetchone()[0] == 1000` and the summary-row equivalent.
- [x] [Review][Patch] **Dry-run sort has dead `or ""` branch signalling a fuzzy invariant** [src/comadre/keys/cli/commands/system.py:~391] — The `for` loop above already `continue`s when `row.paid_until is None`, so the sort's `paid_until or ""` fallback is dead code. Drop the fallback: `preview.sort(key=lambda r: (r.paid_until, r.customer_name, r.key_prefix))`. Cleaner typing contract.

Deferred (real concerns, non-gating; tracked in deferred-work.md):

- [x] [Review][Defer] **`paid_until` lex-sort (SQL) vs Python-semantic-sort (dry-run) divergence on non-canonical date strings** [src/comadre/keys/db.py:~1432, src/comadre/keys/cli/commands/system.py:~272] — `mark-paid` canonicalizes on write, so every row in practice has `YYYY-MM-DD`; defense-in-depth via a CHECK constraint (`paid_until GLOB '____-__-__'`) would close the gap permanently. Deferred: schema change is a separate concern.
- [x] [Review][Defer] **`_touch_auth_cache_sentinel` swallows `OSError` via `contextlib.suppress` — AC5 can fail silently** [src/comadre/keys/db.py:~238-240] — Pre-existing helper introduced in Story 3.1; if the sentinel write fails (read-only FS, EPERM), replicas fall back to 60s TTL instead of instant invalidation. Add a `WARN` log and pair with an operator-visible metric. Not gating for 3.3.
- [x] [Review][Defer] **`cast(Settings, settings_obj)` escapes type narrowing from `load_settings_and_tz`** [src/comadre/keys/cli/commands/system.py:~316-317] — Tighten `load_settings_and_tz`'s return annotation to `tuple[Settings, ZoneInfo] | None` so the cast becomes redundant. Touches a shared helper used by multiple Story 1/3 commands.
- [x] [Review][Defer] **Ansible `billing_timezone` has no validation — a typo (`America/Sao-Paulo`) silently desyncs cron from app** [deploy/ansible/playbooks/bootstrap.yml:308-312] — Add an `assert` task against IANA zones or `zoneinfo.available_timezones()`.
- [x] [Review][Defer] **`time.sleep(0.05)` in sentinel-mtime tests is flaky on filesystems with 1s mtime resolution** [tests/test_keys_db_suspend_sweep.py:~477] — CI runs on ext4 with sub-second mtime, so not hitting today; flags FAT32/NFS-relatime risk. Pre-set `os.utime(sentinel, (0, 0))` to avoid the sleep dependency.
- [x] [Review][Defer] **CLI tests patch `system_cmd.resolve_today_in_tz` instead of the source module `comadre.keys.cli._clock.resolve_today_in_tz`** [tests/test_keys_cli_suspend_sweep.py:~67-68] — Story spec's "Test-flake avoidance" guidance explicitly prefers patching the source module for refactor resilience. Works today via import-in-module binding; brittle under future refactors.
- [x] [Review][Defer] **`get_last_sweep_timestamp` returns the audit-log string without ISO validation** [src/comadre/keys/db.py:~1487] — If a corrupt row slips into audit_log, Story 3.4's `health` displays it verbatim. Cheap `date.fromisoformat` guard + canonical-form assertion would harden the contract.
- [x] [Review][Defer] **`cleanup.yml` removes the suspension cron before `CRON_TZ` — partial-failure state leaves a lingering `CRON_TZ` without its consumer** [deploy/ansible/playbooks/cleanup.yml:~66-76] — Wrap both tasks in a `block:` or swap the order (remove `CRON_TZ` first, then the cron entry).

Dismissed as noise (23 nits; not persisted):

1. `completed_at` sampled pre-transaction (merged into the per-key timestamp patch).
2. `today` parameter accepts any `date` without TZ guard — CLI enforces via `resolve_today_in_tz`.
3. `UPDATE … RETURNING` has no `ORDER BY` — `swept_key_ids` order is not part of the contract.
4. `contextlib.suppress(Exception)` around INFO log — spec-prescribed at §3 step 7 (PII-austere fallback pattern).
5. `_fetch_summary_row` ordered by `id DESC` — test-internal; works with SQLite `INTEGER PRIMARY KEY`.
6. Dry-run's own runs do not refresh FR43 timestamp — by design; Story 3.4 reads real-run timestamps only.
7. `cd ~/comadre` fragility — matches the sister `comadre-audio-cleanup` convention (pre-existing).
8. Cron tasks missing `user:` — matches existing playbook convention (become_user handles this).
9. 00:30 sweep vs 03:00 restart timing — current margin is safe.
10. `_utcnow_iso` second resolution ordering — resolved by the `get_last_sweep_timestamp` tie-break patch.
11. Zero-row sweep still runs UPDATE — by design, AC4.
12. Complimentary row with non-NULL `paid_until` silently ignored — schema invariant upheld by issue-key.
13. `load_settings_and_tz` returns only the first validation failure — pre-existing helper behavior.
14. `contextlib.suppress(sqlite3.Error)` on `conn.close()` — pre-existing close pattern.
15. Concurrent `mark-paid` during sweep — accepted by RETURNING's atomicity.
16. Dry-run pulls full active/manual set into Python — out of scope (today's largest portfolio is ~20 keys).
17. `TestIdempotence` hard-coded `== 3` — derived from fixture; explicit is fine.
18. `TestCycle` audit-order relies on `id` ASC — test harness does not VACUUM.
19. `get_last_sweep_timestamp` requires `sqlite3.Row` row_factory — internal helper, `get_connection` sets it.
20. No CHECK constraint on `audit_log.action` — schema-wide concern; out of 3.3 scope.
21. No runtime SQLite version check — docstring notes the 3.35+ requirement; Python 3.12 ships 3.41+.
22. `_PII_FORBIDDEN_RE` is deny-list — pre-existing test hygiene debt (Story 3.1).
23. `EXPLAIN QUERY PLAN` assertion missing — spec explicitly deferred (§Deferred work).
24. Dry-run footer wording drifts from §3 step 8 — spec-internal contradiction; §4 prevails (code + tests consistent).
25. Dry-run sort `customer_name` inclusion — matches Story 3.2's `at-risk` precedent; spec gloss was imprecise.
26. Task 5.1 inventory `.yml` files absent from diff — operator-local artifacts (`.example` is the canonical template).
27. Grep §11 single-quoted literal — quote-convention cosmetic; semantic invariant (2 write sites) holds.
28. DST transition untested — spec explicitly deferred; Brazil is DST-free.
