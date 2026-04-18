# Story 3.1: Payment Tracking (mark-paid, suspend, reactivate)

Status: done

> **Scope note — FR15 / FR19 / FR20 split.** Epic 3 opens with three billing verbs that share the same pattern (mutate one column of `api_key`, write one audit row, touch the cache sentinel), but they answer three different operator questions: "Pedro paid, log it" (`mark-paid`), "Cut Marcos off now" (`suspend`), "I know Marcos didn't pay but re-enable anyway" (`reactivate`). `mark-paid` alone carries the reactivation side-effect mandated by FR20 — when the key is already `suspended`, it also flips `status='active'` in the same transaction. `suspend` and `reactivate` are pure status mutations and never touch `paid_until`. Story 3.3 will add the cron-driven sweep that turns Day-06 expirations into auto-suspensions; Story 3.1 is the operator-hand surface only.

## Story

As an operator,
I want to confirm a payment, manually suspend a key out-of-cycle, and manually reactivate a suspended key — each as a single-line command under 200 ms — so that the monthly billing ritual for 20 customers takes 5 minutes, not 30.

**Covers FRs:** FR15 (`mark-paid` writes `paid_until`), FR19 (suspended keys retained indefinitely — no auto-delete), FR20 (extending `paid_until` automatically reactivates a suspended key within the auth-cache propagation bound).
**UX-DRs:** UX-DR7 (ConfirmationLine — single-line stdout confirmation for mutation verbs).
**Epic:** 3 — Billing & Revenue Operations. First story in Epic 3. Opens the Day-05 billing ritual (`ux-design-specification.md` L56, L572–631); cron sweep (Story 3.3) and revenue reports (Story 3.2) layer on top of the status/`paid_until` writes this story lands.

## Builds on

- **Story 1.6** — `update_api_key` / `rotate_api_key` / `revoke_api_key` in `src/comadre/keys/db.py:847–1125` are the definitive template for "single-column mutation + audit + sentinel-touch" helpers. Story 3.1's three helpers mirror this shape (helper owns the transaction, callers never wrap `with conn:`, audit write is inside the same txn, `_touch_auth_cache_sentinel` is called outside after commit).
- **Story 1.6** — `_resolve_key_target` + `_load_settings_and_tz` + `_truncate_ident` in `src/comadre/keys/cli/commands/keys.py:737–813` are the shared CLI preamble. Story 3.1's three commands call the same helpers verbatim for identifier resolution, config/tz loading, and error-panel identifier echoing. No refactor — reuse.
- **Story 2.1 + 2.2 sentinel pattern** — `_touch_auth_cache_sentinel(conn)` (`src/comadre/keys/db.py:163`) makes every status change effectively immediate in the API (the 60-second TTL bound in FR20 is the worst-case; the sentinel-based `AuthCache._flush_if_invalidated` short-circuits it to the next request). All three helpers MUST call the sentinel helper after commit.
- **Story 2.1 auth flow** — `ApiKeySuspendedError` (`src/comadre/exceptions.py`) is the 401 envelope the API returns for a suspended key. `mark-paid`'s reactivation branch closes the loop: the key starts returning 200 again on the very next request after commit (cache flush via sentinel), or at most 60 s later if the sentinel mtime race loses.
- **Story 2.2 rate-limit bucket** — `RateLimiter` keys buckets on `key:<key_id>` (`src/comadre/rate_limit.py:114`). `key_id` is stable across status changes, so a suspend→reactivate round-trip preserves the bucket's counter state — the key resumes against the same window it left. No rate-limit code change required.
- **Story 1.4 show --audit-tail** — the three new audit actions (`mark_paid`, `suspend_key`, `reactivate_key`) surface verbatim in `comadre-keys show <prefix> --audit-tail N` with no renderer change (`render_audit_tail` uppercases the action string and renders `details_json` as a suffix). This is how the AC "audit log records a `mark_paid` event" is operator-observable.
- **Story 1.6 ConfirmationLine grammar** — `render_confirmation` (`src/comadre/keys/cli/output.py:68`) is the UX-DR7 stdout surface. Story 3.1 reuses the em-dash-separated grammar (`Revoked: {prefix} ({name}) — reason: {text}`) with three new verb phrasings. No new renderer.

## Unblocks

- **Story 3.2** (At-Risk Queries & Revenue Reports) — `revenue --month current` aggregates `price_monthly` across rows split by `status` + `paid_until ≥ first_of_month`; the write-side semantics for those columns land here.
- **Story 3.3** (Automated Suspension Sweep & Cron) — the sweep runs `UPDATE api_key SET status='suspended' WHERE billing_mode='manual' AND paid_until < ? AND status='active'` as a single statement. It writes the same `suspend_key` audit action shape that Story 3.1 introduces; 3.3 just writes it in bulk under actor `cron:suspension-sweep`. Matching the action name now means 3.3's per-row audit rows look identical to operator-initiated suspensions in `show --audit-tail` — no branch on actor to read the tail correctly.
- **Story 3.4** (System Health Command) — `health` reads the `audit_log` to show "last successful sweep at …". The `suspend_key` action-name choice here is what the health command will `WHERE action='suspend_key' AND actor LIKE 'cron:%'` on.

## Depends on

- Stories 1.1–1.6 and 2.1–2.3 must be `done` (all are, per `_bmad-output/implementation-artifacts/sprint-status.yaml` L60–76 as of 2026-04-18). No new dependency in `pyproject.toml` — stdlib `sqlite3`, `datetime`, `typer`, the existing `comadre.keys.*` surface.
- No schema change. No migration. `api_key.paid_until` and `api_key.status` already exist from v001_initial.sql (L18, L21).

## Scope

Adds three CLI commands (`mark-paid`, `suspend`, `reactivate`) each backed by one new helper in `src/comadre/keys/db.py`, plus a new `src/comadre/keys/cli/commands/billing.py` Typer subapp registered at the top-level app. No new runtime modules. No schema change. No `rate_limit.py` change. No `api.py` change. No new dependency.

### 1. New DB helper: `mark_key_paid`

`src/comadre/keys/db.py` — sibling of `update_api_key` / `revoke_api_key`.

Signature:

```python
@dataclass(frozen=True, slots=True)
class MarkPaidResult:
    """Return payload from ``mark_key_paid``.

    ``key`` is the refreshed ``KeyDetailRow`` (post-mutation). ``reactivated``
    captures the FR20 side-effect: True when the row was ``suspended`` and
    this call flipped it to ``active``; False when the row was already
    ``active`` and only ``paid_until`` changed. The CLI uses the flag to
    render a slightly different ConfirmationLine suffix (``... → paid until
    2026-06-05 (reactivated)`` vs just ``... → paid until 2026-06-05``).
    """

    key: KeyDetailRow
    reactivated: bool


def mark_key_paid(
    conn: sqlite3.Connection,
    key_id: str,
    *,
    paid_until: str,  # YYYY-MM-DD, caller-validated
    actor: str,
    today: date,
) -> MarkPaidResult | None:
    ...
```

Behavior:

1. `SELECT status, billing_mode FROM api_key WHERE id = ?`. If missing → return `None`.
2. If `status == 'revoked'` → raise `ValueError("cannot mark-paid a revoked key")`. Revocation is terminal (consistent with `rotate_api_key` / `update_api_key`).
3. If `billing_mode == 'complimentary'` → raise `ValueError("cannot mark-paid a complimentary key")`. The CLI maps this to the informational-message exit-0 path described in §6; the helper itself rejects the operation so non-CLI callers can't silently write `paid_until` onto a row that has no billing semantics.
4. Capture `reactivated = (status == 'suspended')`.
5. In a single `with conn:` transaction:
   - `UPDATE api_key SET paid_until = ?, status = CASE WHEN status = 'suspended' THEN 'active' ELSE status END WHERE id = ? AND status != 'revoked'`. Using a CASE expression in one UPDATE keeps the mutation atomic and avoids a "read status, write status" round-trip.
   - `log_event(action='mark_paid', target_type='api_key', target_id=key_id, details={'paid_until': paid_until, 'reactivated': reactivated})`.
6. After commit, call `_touch_auth_cache_sentinel(conn)` so a just-reactivated key starts passing auth on the next API request (not 60 s later).
7. Re-read the row via `get_key_detail_by_id(conn, key_id, today=today)`; RuntimeError if the row vanished (same contract as `revoke_api_key`).
8. Return `MarkPaidResult(key=refreshed, reactivated=reactivated)`.

**Why one audit row, not two.** A `mark_paid` that reactivates could notionally write both `mark_paid` and a `reactivate_key` audit row. The single-row form is cleaner: the operator reading `show --audit-tail` sees one event for one operator action. The `reactivated: true` field in `details_json` is unambiguous and queryable (`WHERE json_extract(details_json, '$.reactivated') = 1` for Story 3.2's revenue-side analyses). Two rows would show up in the tail as "MARK_PAID" immediately followed by "REACTIVATE_KEY" with the same timestamp, which looks like a bug.

**Why the CASE expression and not a branch.** A Python-side `if status == 'suspended': execute(UPDATE ... status='active', paid_until=?) else: execute(UPDATE ... paid_until=?)` would open a 1-microsecond race window where a concurrent writer could change `status` between the SELECT and the UPDATE. The CASE form makes the status-preservation policy atomic at the SQL engine. In the single-writer CLI this is theoretical, but the `WHERE id = ? AND status != 'revoked'` predicate provides the same defense-in-depth as `update_api_key`.

### 2. New DB helper: `suspend_key`

`src/comadre/keys/db.py` — manual out-of-cycle suspension.

```python
@dataclass(frozen=True, slots=True)
class SuspendKeyResult:
    """Return payload from ``suspend_key`` — refreshed KeyDetailRow only."""

    key: KeyDetailRow


def suspend_key(
    conn: sqlite3.Connection,
    key_id: str,
    *,
    actor: str,
    today: date,
) -> SuspendKeyResult | None:
    ...
```

Behavior:

1. `SELECT status FROM api_key WHERE id = ?`. Missing → `None`.
2. `status == 'revoked'` → `ValueError("cannot suspend a revoked key")`.
3. `status == 'suspended'` → `ValueError("already suspended")`. Idempotence is an anti-pattern here — if the operator types `suspend` on a row that is already suspended, they likely misread `list-keys` and should see the correction, not a silent no-op that writes a misleading audit row.
4. In `with conn:`:
   - `UPDATE api_key SET status = 'suspended' WHERE id = ? AND status = 'active'` (the predicate is load-bearing: if a concurrent `suspend_sweep` or another CLI beat us to it, the UPDATE no-ops and we raise `RuntimeError` below).
   - Assert `cursor.rowcount == 1`; else `RuntimeError` (same pattern as `revoke_api_key`).
   - `log_event(action='suspend_key', target_type='api_key', target_id=key_id, details=None)`. No `details_json` — the action name + actor + occurred_at carries enough signal; there is no operator-supplied reason on manual suspend (if the operator needs to record context, they use `update-customer --add-note` or `update-key --notes "..."` before suspending).
5. Call `_touch_auth_cache_sentinel(conn)` after commit.
6. Re-read via `get_key_detail_by_id`; RuntimeError on vanished row.
7. Return `SuspendKeyResult(key=refreshed)`.

**Why match the cron sweep's action name.** Story 3.3 will write `suspend_key` audit rows under actor `cron:suspension-sweep`. Using the same `action='suspend_key'` here means `show --audit-tail` renders manual and cron suspensions with the same verb — operators can read the actor column to distinguish, and any future "why was this key suspended?" query stays one predicate simple.

### 3. New DB helper: `reactivate_key`

`src/comadre/keys/db.py` — suspended → active without touching `paid_until`.

```python
@dataclass(frozen=True, slots=True)
class ReactivateKeyResult:
    """Return payload from ``reactivate_key`` — refreshed KeyDetailRow only."""

    key: KeyDetailRow


def reactivate_key(
    conn: sqlite3.Connection,
    key_id: str,
    *,
    actor: str,
    today: date,
) -> ReactivateKeyResult | None:
    ...
```

Behavior:

1. `SELECT status FROM api_key WHERE id = ?`. Missing → `None`.
2. `status == 'revoked'` → `ValueError("cannot reactivate a revoked key")`.
3. `status == 'active'` → `ValueError("already active")`. Same rationale as the `suspend_key` already-suspended rejection.
4. `UPDATE api_key SET status = 'active' WHERE id = ? AND status = 'suspended'`.
5. Assert `cursor.rowcount == 1`; else RuntimeError.
6. `log_event(action='reactivate_key', target_type='api_key', target_id=key_id, details=None)`.
7. `_touch_auth_cache_sentinel(conn)` after commit.
8. Re-read + return `ReactivateKeyResult(key=refreshed)`.

**Why `reactivate_key` does NOT touch `paid_until`.** The epic AC is explicit (`epics.md:638`): "`paid_until` is NOT modified (the operator must separately run `mark-paid` if extending)". This separation matters for J3 (delinquent customer): an operator reactivating a suspended key as a goodwill gesture *without* confirming payment must not silently extend the billing date. The next cron sweep will then re-suspend the key on the normal schedule — that is the intended behavior, not a bug.

### 4. New CLI module: `src/comadre/keys/cli/commands/billing.py`

Fresh Typer subapp. Three commands today; Story 3.2 will append `at-risk` and `revenue`. Creating the module now means 3.2 only adds handlers, not bootstrap.

Module layout mirrors `keys/cli/commands/keys.py`:

```python
"""`comadre-keys mark-paid` / `suspend` / `reactivate` (Story 3.1).

Exit-code contract (UX-DR10):
  0 — success
  2 — usage error (bad --until shape, empty prefix, etc.)
  3 — not-found / terminal state (key missing, ambiguous prefix,
      already-active / already-suspended / revoked)
  5 — database error (sqlite3.Error, RuntimeError from helper)
  6 — permission / configuration error (missing encryption key,
      invalid IANA timezone)
"""
```

**Shared preamble.** All three commands import and call `_load_settings_and_tz` and `_resolve_key_target` from `src/comadre/keys/cli/commands/keys.py`. Those helpers are currently private to that module (leading underscore); Story 3.1 promotes them to public names (drop the underscore) or re-exports them through a small `_shared.py` — pick whichever diff is smaller during implementation. The architectural requirement is **zero duplication** of the settings-load / tz-load / key-target-resolve ladder.

**Recommended: promote `_load_settings_and_tz` → `load_settings_and_tz` and `_resolve_key_target` → `resolve_key_target` in `keys.py`, update the three existing call sites there, then import them from `billing.py`.** This keeps the "shared across command modules" surface in one file and avoids adding a `_shared.py` sibling module for two helpers. The `_truncate_ident` helper can stay private (it's a formatting utility, not a flow helper) — re-export via `from comadre.keys.cli.commands.keys import _truncate_ident` if `billing.py` needs it.

#### 4a. `mark-paid` command

```python
@app.command("mark-paid")
def mark_paid_cmd(
    key_prefix: str = typer.Argument(
        ...,
        metavar="KEY_PREFIX",
        help=(
            "8-char key prefix, key_<ulid>, or pasted cmdr_live_<plaintext>. "
            'Example: "cmdr_Pq" or "Pq_abc12".'
        ),
    ),
    until: str = typer.Option(
        ...,
        "--until",
        help=(
            "Extend paid_until to this ISO date (YYYY-MM-DD). "
            "Example: --until 2026-06-05."
        ),
    ),
) -> None:
    """Confirm payment for a key and extend its validity.

    Example: comadre-keys mark-paid cmdr_Pq --until 2026-06-05
    """
```

Validation ladder:

1. **`--until` shape.** Strip whitespace. `date.fromisoformat(until)` — on ValueError render usage error and `raise typer.Exit(code=2)`. Re-emit the parsed date via `.isoformat()` so alternate ISO forms (`"20260605"`) normalize to `"2026-06-05"` before storage (the `api_key.paid_until` TEXT column is sorted lexicographically by the cron sweep; non-canonical forms would silently break `paid_until < ?` comparisons). **Do NOT reject past dates** — retroactive payment recording is a legitimate operator workflow (e.g., "Marcos paid on the 8th but I'm logging it on the 12th"); the next cron sweep will correctly re-suspend the row on schedule. Document this in `--help`.
2. **Settings + TZ** (exit 6) — call `load_settings_and_tz()`; bail with exit 6 on None return.
3. **DB open + migrations** (exit 5) — same pattern as siblings.
4. **Resolve prefix → KeyDetailRow** (exit 3 on not-found / ambiguous / customer-input) — call `resolve_key_target(conn, key_prefix, today)`.
5. **Complimentary short-circuit** (exit 0, not error). Check `key_row.billing_mode == 'complimentary'` BEFORE calling the helper. Render `render_confirmation(f"Key {key_row.key_prefix} is complimentary — no payment tracking required.")` and return. Exit 0. Per `epics.md:642` this is an informational state, not an error. No audit row is written (no mutation occurred).
6. **Call `mark_key_paid(conn, key_row.id, paid_until=until_iso, actor=get_cli_actor(), today=today)`**. Map exceptions:
   - `ValueError("cannot mark-paid a revoked key")` → exit 3 with hint "Revoked keys are terminal. Issue a new key via issue-key if the customer returns."
   - `ValueError("cannot mark-paid a complimentary key")` → defense-in-depth (step 5 catches it first); exit 3 with the complimentary-is-informational hint.
   - `sqlite3.Error` / `RuntimeError` → exit 5.
7. **Structured INFO log** (stderr, via `_logger.info`): `"Marked paid | id=%s | paid_until=%s | reactivated=%s"`. No customer_name in log (FR37/NFR15 — logs are PII-austere; name flows only into the operator-facing ConfirmationLine).
8. **ConfirmationLine.** Per `epics.md:622`:
   - Active key: `f"Marked paid: {prefix} ({customer_name}) \u2192 paid until {until_iso}"`
   - Reactivated (was suspended): `f"Marked paid: {prefix} ({customer_name}) \u2192 paid until {until_iso} (reactivated)"`
   U+2192 is the right-arrow; the `(reactivated)` suffix is the operator's only visual signal that FR20 fired. Without it, an operator who forgot a key was suspended would miss the silent status flip.

#### 4b. `suspend` command

```python
@app.command("suspend")
def suspend_cmd(
    key_prefix: str = typer.Argument(
        ...,
        metavar="KEY_PREFIX",
        help=(
            "8-char key prefix, key_<ulid>, or pasted cmdr_live_<plaintext>. "
            'Example: "cmdr_Pq" or "Pq_abc12".'
        ),
    ),
) -> None:
    """Manually suspend an API key (out-of-cycle; use for abuse or contract disputes).

    Example: comadre-keys suspend cmdr_Pq
    """
```

Validation ladder: same shape as `mark-paid` minus the `--until` step. No `--reason` flag (intentional — suspended keys are reversible via `reactivate` and per UX-DR11 only the `Destroy` tier requires reasons). No `--yes` gate (suspension is reversible, so it sits in the `Mutate` tier per `ux-design-specification.md:893`).

Helper dispatch:

- Call `suspend_key(conn, key_row.id, actor=get_cli_actor(), today=today)`.
- Map: `ValueError("cannot suspend a revoked key")` → exit 3; `ValueError("already suspended")` → exit 3 with hint "Run `comadre-keys show {prefix}` to inspect current status."
- `sqlite3.Error` / `RuntimeError` → exit 5.

ConfirmationLine: `f"Suspended: {prefix} ({customer_name})"` — no trailing clause. The bare form matches the UX-DR7 "single-line, minimal" spec (`ux-design-specification.md:846`).

#### 4c. `reactivate` command

```python
@app.command("reactivate")
def reactivate_cmd(
    key_prefix: str = typer.Argument(
        ...,
        metavar="KEY_PREFIX",
        help=(
            "8-char key prefix, key_<ulid>, or pasted cmdr_live_<plaintext>. "
            'Example: "cmdr_Pq" or "Pq_abc12".'
        ),
    ),
) -> None:
    """Reactivate a suspended key without extending billing (does NOT set paid_until).

    Example: comadre-keys reactivate cmdr_Pq
    """
```

Validation ladder: identical shape to `suspend`.

Helper dispatch:

- Call `reactivate_key(conn, key_row.id, actor=get_cli_actor(), today=today)`.
- Map: `ValueError("cannot reactivate a revoked key")` → exit 3; `ValueError("already active")` → exit 3 with hint "Run `comadre-keys show {prefix}` to inspect current status."
- `sqlite3.Error` / `RuntimeError` → exit 5.

ConfirmationLine: `f"Reactivated: {prefix} ({customer_name})"`.

### 5. Register `billing_app` in `src/comadre/keys/cli/app.py`

Append to the existing merge block:

```python
from comadre.keys.cli.commands.billing import app as billing_app
...
app.registered_commands.extend(billing_app.registered_commands)
```

Commands surface flat (`comadre-keys mark-paid` etc.) — no nested grouping, per the existing app-merge pattern (`src/comadre/keys/cli/app.py:22-24`).

### 6. Docs

- **`docs/configuration-reference.md`** — no new settings introduced. No changes required unless the existing billing-day / billing-timezone entries need an operator-runbook pointer for the new commands; add a one-line "see also: `mark-paid`, `suspend`, `reactivate`" cross-reference under the billing-timezone entry.
- **`CLAUDE.md`** — extend the `keys/cli/` bullet (currently "create-customer, list-customers, update-customer, issue-key, list-keys, update-key, rotate-key, revoke-key, show, cache-status") with the three new verbs. Keep alphabetical-by-function grouping: customers first, then keys, then billing, then system.
- **`README.md`** — add a one-line mention in the CLI-command overview table/bullet if one exists (verify during implementation). The `mark-paid` command is the most operator-facing addition and deserves a top-level bullet; `suspend` / `reactivate` can share a line.
- **No `docs/monetization.md` yet.** The full operator runbook for the billing ritual is planned for Story 4.6 (LGPD + runbook). Story 3.1 does NOT create `docs/monetization.md` — it would duplicate content that Story 4.6 will author. The command `--help` text carries the per-command ergonomics until then.

### 7. Tests

Follow the Story 1.6 convention: one test file per command, plus helper-level tests in `test_keys_db.py` and audit-shape tests in `test_keys_audit.py`.

- **`tests/test_keys_db.py`** (MOD) — new test classes:
  - `TestMarkKeyPaid`:
    - Happy path (active key, future date) → `paid_until` updated, `reactivated=False`, audit row shape `{paid_until, reactivated: false}`.
    - Suspended-key path → `paid_until` updated, `status='active'`, `reactivated=True`, audit row `{paid_until, reactivated: true}`.
    - Revoked-key path → `ValueError`, no mutation.
    - Complimentary-key path → `ValueError`, no mutation.
    - Missing-key path → returns `None`.
    - Atomicity: inject `log_event` failure via monkeypatch → assert the `paid_until` UPDATE was rolled back (`SELECT paid_until` unchanged from pre-call).
    - Past date accepted: `paid_until='2020-01-01'` on an active key writes without error (retroactive semantics).
    - Sentinel touched: `{db_path}.invalidate` mtime advanced post-call.
  - `TestSuspendKey`:
    - Happy path (active) → `status='suspended'`, audit row `action='suspend_key'`, `details_json IS NULL`, sentinel touched.
    - Already-suspended → `ValueError("already suspended")`, no mutation, no audit row.
    - Revoked → `ValueError("cannot suspend a revoked key")`.
    - Missing → `None`.
    - Complimentary key, status=active: `suspend` succeeds (complimentary doesn't block manual suspension — the cron sweep ignores `billing_mode='complimentary'`, but a human operator can still suspend for abuse).
  - `TestReactivateKey`:
    - Happy path (suspended) → `status='active'`, `paid_until` UNCHANGED (explicit assertion — FR20 rules out silent extension), audit `action='reactivate_key'`, sentinel touched.
    - Already-active → `ValueError("already active")`, no mutation.
    - Revoked → `ValueError`.
    - Missing → `None`.

- **`tests/test_keys_audit.py`** (MOD) — add a case covering the new allowed action strings. The audit-log blocklist (`_FORBIDDEN_DETAIL_KEYS`) does not need an update: the three new action shapes carry only `paid_until` + `reactivated` booleans + nothing, none of which are in the forbidden-key set. Add a regression test that `{'paid_until': '2026-06-05', 'reactivated': False}` round-trips through `log_event` + SELECT unchanged.

- **`tests/test_keys_cli_mark_paid.py`** (NEW) — end-to-end CLI via `CliRunner`, mirroring `test_keys_cli_revoke_key.py`'s fixture scaffolding verbatim (auto-fixture `_reset_consoles_to_buffers`, `env` fixture with tmp DB + Fernet key):
  - AC coverage: happy path (active), reactivation path (suspended → active), complimentary exit-0 informational message, revoked-key exit-3, missing-key exit-3, ambiguous-prefix exit-3, customer-ID input exit-2.
  - Invalid `--until`: non-date string, empty, `"today"` (rejected — we accept only ISO dates), past date accepted without warning, alternate ISO form (`"20260605"`) normalizes to `"2026-06-05"` in DB.
  - ConfirmationLine byte-identity (active): `"Marked paid: Pq_abc12 (Pedro Lopes) → paid until 2026-06-05"`.
  - ConfirmationLine byte-identity (reactivated): includes the `(reactivated)` suffix.
  - Audit row assertions via direct SQLite SELECT: one `mark_paid` row, `target_id` matches `key_id`, `details_json` JSON-decodes to the expected dict with `reactivated: false` on the active path and `reactivated: true` on the suspended path.
  - `_touch_auth_cache_sentinel` coverage: the sentinel file mtime advances post-command (stat before/after).
  - Structured log line contains `key_id=`, `paid_until=`, `reactivated=` — and NEVER the customer name, email, CPF/CNPJ, or plaintext (regex guard).
  - Performance sanity: the happy path round-trip completes under 200 ms on the test runner's tmp_path SQLite (this is an advisory check via `time.perf_counter()`; skip if CI is too slow, but do NOT remove the assertion — flaky-slow-CI should surface as a perf regression, not get silenced).

- **`tests/test_keys_cli_suspend.py`** (NEW) — same scaffolding pattern:
  - AC coverage: happy path (active → suspended), already-suspended exit-3, revoked exit-3, missing exit-3, ambiguous exit-3, customer-ID input exit-2.
  - Complimentary-key suspension is allowed (active complimentary → suspended) — document the intent in the test name (`test_complimentary_can_be_manually_suspended`).
  - Audit shape: `action='suspend_key'`, `details_json IS NULL`, actor `cli:<username>`.
  - ConfirmationLine byte-identity: `"Suspended: Pq_abc12 (Pedro Lopes)"`.
  - Sentinel mtime advanced.

- **`tests/test_keys_cli_reactivate.py`** (NEW) — same scaffolding:
  - AC coverage: happy path (suspended → active), already-active exit-3, revoked exit-3, missing exit-3, ambiguous exit-3, customer-ID input exit-2.
  - **FR20 paid-date-preservation test**: seed a key with `status='suspended'`, `paid_until='2026-04-05'` (past); run `reactivate`; assert `status='active'` AND `paid_until='2026-04-05'` (unchanged, not bumped). This is the load-bearing FR20 AC.
  - ConfirmationLine byte-identity: `"Reactivated: Pq_abc12 (Pedro Lopes)"`.
  - Audit shape: `action='reactivate_key'`, `details_json IS NULL`.
  - Sentinel mtime advanced.

- **`tests/test_keys_cli_show.py`** (MOD) — the existing `TestShowKeyAuditTail.test_key_audit_tail_20` already exercises a `mark_paid` audit row via `_raw_insert_audit` (L351–358). Add two sibling cases that use the real `mark-paid` / `suspend` / `reactivate` commands to seed the audit rows (not the raw-insert helper) and assert the same rendering. This closes the loop that "the audit action strings Story 3.1 writes are identical to what `show --audit-tail` renders".

- **`tests/test_keys_auth.py`** (MOD) — add an integration case that exercises the full reactivation round-trip:
  1. Seed an active key; authenticate once (cache hit) → 200.
  2. Run `suspend` via CLI.
  3. Authenticate again → `ApiKeySuspendedError` (cache was flushed by the sentinel; the suspended status reaches the auth path without waiting 60 s).
  4. Run `mark-paid --until <future>`.
  5. Authenticate again → 200 (cache flushed again; status back to active).

  This is the end-to-end FR20 assertion. Without this case the sentinel-touch could regress silently.

### 8. Exit-code contract (UX-DR10)

| Exit | Condition |
|------|-----------|
| 0 | Success. Also: `mark-paid` on complimentary key (informational, no mutation). |
| 2 | Usage error: bad `--until` shape; customer-ID passed as key argument. |
| 3 | Not-found (missing / ambiguous prefix), terminal-state rejections (revoked, already-suspended, already-active), complimentary-key blocked at helper level (defense-in-depth). |
| 5 | Database error (`sqlite3.Error`, `RuntimeError` from helpers). |
| 6 | Configuration error (missing `KEY_REGISTRY_ENCRYPTION_KEY`, invalid `BILLING_TIMEZONE`). |

Note the intentional asymmetry: `mark-paid` on a complimentary key exits 0 (it is not an error — the command was called on the wrong kind of key and the CLI communicates that), whereas the helper's `ValueError` would be exit 3 for any non-CLI caller. The CLI's §4a step 5 short-circuit exists precisely to provide the friendlier operator surface.

## Acceptance Criteria

> BDD-style. Each AC maps to at least one test. AC numbers are stable — do not renumber if a mid-story pivot adds/removes an AC (append a new number instead).

### AC1 — `mark-paid` sets `paid_until` on an active key

**Given** an active manual-mode key with prefix `cmdr_Pq`, customer `Pedro Lopes`, and `paid_until='2026-05-05'`
**When** the operator runs `comadre-keys mark-paid cmdr_Pq --until 2026-06-05`
**Then** `api_key.paid_until` equals `'2026-06-05'`, `api_key.status` remains `'active'`, exit code is 0
**And** stdout contains verbatim: `Marked paid: cmdr_Pq (Pedro Lopes) → paid until 2026-06-05`
**And** the command completes in under 200 ms (UX spec §"mark-paid hot path", advisory check)

### AC2 — `mark-paid` writes a `mark_paid` audit row

**Given** AC1's setup
**When** `mark-paid` runs
**Then** a new row exists in `audit_log` with `action='mark_paid'`, `target_type='api_key'`, `target_id=<key_id>`, `actor='cli:<shell-user>'`
**And** `details_json` decodes to `{"paid_until": "2026-06-05", "reactivated": false}`

### AC3 — `mark-paid` reactivates a suspended key (FR20)

**Given** a suspended manual-mode key with `paid_until='2026-04-05'` (past)
**When** the operator runs `comadre-keys mark-paid cmdr_Pq --until 2026-06-05`
**Then** `api_key.status='active'`, `api_key.paid_until='2026-06-05'`, exit code is 0
**And** stdout contains verbatim: `Marked paid: cmdr_Pq (Pedro Lopes) → paid until 2026-06-05 (reactivated)`
**And** the audit row's `details_json` decodes to `{"paid_until": "2026-06-05", "reactivated": true}`

### AC4 — Reactivated key authenticates in the API within one request (FR20 propagation)

**Given** a suspended key in the registry
**And** a running API that has the suspended `AuthPayload` cached
**When** the operator runs `mark-paid --until <future>` on that key
**Then** the **next** `POST /v1/audio/speech` request with that key returns 200 (not 401)
**And** the auth cache flush happens via the sentinel pattern (the cache's `_sentinel_mtime_ns` advances)
**And** the 60-second TTL bound in FR20 is a worst-case; the sentinel-based flush is the actual path

### AC5 — `mark-paid` on a complimentary key is informational (exit 0)

**Given** a complimentary key `cmdr_Cx`
**When** the operator runs `comadre-keys mark-paid cmdr_Cx --until 2026-06-05`
**Then** exit code is 0
**And** stdout contains verbatim: `Key cmdr_Cx is complimentary — no payment tracking required.`
**And** no `mark_paid` audit row is written (no mutation occurred)
**And** `api_key.paid_until` remains NULL

### AC6 — `mark-paid` on a revoked key returns exit 3

**Given** a revoked key `cmdr_Rv`
**When** the operator runs `comadre-keys mark-paid cmdr_Rv --until 2026-06-05`
**Then** exit code is 3
**And** stderr contains a red-bordered ErrorDisplay with title "Key is revoked: cmdr_Rv" and a hint about issuing a new key
**And** no mutation occurred (paid_until unchanged, no audit row added)

### AC7 — `mark-paid` rejects invalid `--until` shape (exit 2)

**Given** any reachable key
**When** the operator runs `mark-paid cmdr_Pq --until "tomorrow"` (or `""`, or `"2026-13-40"`)
**Then** exit code is 2
**And** stderr contains an ErrorDisplay with title `Usage error: --until must be an ISO date (YYYY-MM-DD)` and a concrete example in the hint
**And** no DB connection is opened (fail-fast before `get_connection`)

### AC8 — `mark-paid` accepts past dates (retroactive recording)

**Given** an active key
**When** the operator runs `mark-paid cmdr_Pq --until 2020-01-01`
**Then** exit code is 0
**And** `api_key.paid_until='2020-01-01'` (no warning, no reject)
**And** the audit row records the past date verbatim in `details_json`

Rationale: retroactive payment logging is a legitimate workflow (receipt arrives late, operator logs late). The cron sweep will correctly treat the row as expired on the next run.

### AC9 — `suspend` mutates active → suspended with audit

**Given** an active key `cmdr_Pq` (customer Pedro Lopes)
**When** the operator runs `comadre-keys suspend cmdr_Pq`
**Then** exit code is 0, `api_key.status='suspended'`
**And** stdout contains verbatim: `Suspended: cmdr_Pq (Pedro Lopes)`
**And** one `audit_log` row exists with `action='suspend_key'`, `actor='cli:<shell-user>'`, `details_json IS NULL`
**And** the `.invalidate` sentinel mtime advanced

### AC10 — `suspend` on already-suspended returns exit 3

**Given** a suspended key
**When** the operator runs `suspend` again
**Then** exit code is 3
**And** stderr contains `Key already suspended: cmdr_Pq` with hint about running `show`
**And** no duplicate audit row is written

### AC11 — `suspend` on a revoked key returns exit 3

**Given** a revoked key
**When** the operator runs `suspend`
**Then** exit code is 3 with `Key is revoked: ...` ErrorDisplay
**And** no mutation

### AC12 — `suspend` on a complimentary key is allowed

**Given** an active complimentary key (e.g., bundled contract with abusive behavior)
**When** the operator runs `suspend`
**Then** exit code is 0, `api_key.status='suspended'`, audit row written
**And** the cron sweep (Story 3.3) would NOT touch this row in the future because of the `billing_mode='manual'` predicate; only manual reactivation restores it

Rationale: complimentary keys are bundled externally but abuse is still the operator's concern. Blocking manual suspension on complimentary would remove the only lever for J6's "contract ended" case.

### AC13 — `reactivate` mutates suspended → active and PRESERVES `paid_until`

**Given** a suspended key with `paid_until='2026-04-05'` (past)
**When** the operator runs `comadre-keys reactivate cmdr_Pq`
**Then** exit code is 0, `api_key.status='active'`
**And** `api_key.paid_until='2026-04-05'` (UNCHANGED — explicit assertion required)
**And** stdout contains verbatim: `Reactivated: cmdr_Pq (Pedro Lopes)`
**And** one `audit_log` row with `action='reactivate_key'`, `details_json IS NULL`
**And** the sentinel mtime advanced

This is the load-bearing FR20-complement AC: `reactivate` is the "without payment" path; silently extending `paid_until` here would break J3 (the delinquent-customer journey relies on being able to reactivate as goodwill without committing to a billing period).

### AC14 — `reactivate` on already-active returns exit 3

**Given** an active key
**When** the operator runs `reactivate`
**Then** exit code is 3 with `Key already active: ...` ErrorDisplay
**And** no mutation

### AC15 — `reactivate` on revoked returns exit 3

**Given** a revoked key
**When** the operator runs `reactivate`
**Then** exit code is 3 with `Key is revoked: ...` ErrorDisplay

### AC16 — All three commands reject customer-ID input (exit 2)

**Given** a customer ID `cust_01j8xr3e4c5m7kn9p2qt8vwyz`
**When** the operator runs `mark-paid cust_01j... --until 2026-06-05` (or `suspend` / `reactivate` with the same arg)
**Then** exit code is 2
**And** stderr contains `Usage error: key identifier required (got customer ID)` with the hint from `_KEY_CUSTOMER_ID_HINT`
**And** no DB mutation

### AC17 — All three commands reject ambiguous prefix (exit 3)

**Given** two keys whose 8-char prefixes collide (vanishingly rare, but the resolver returns a list in this case)
**When** the operator runs any of the three commands with the shared prefix
**Then** exit code is 3
**And** stderr contains `Ambiguous prefix: multiple keys match '<prefix>'` with the hint about using `key_<ulid>`
**And** no mutation

### AC18 — All three commands reject missing prefix (exit 3)

**Given** a prefix that matches no row
**When** the operator runs any of the three commands
**Then** exit code is 3
**And** stderr contains `Key not found: <prefix>` with `_KEY_NOT_FOUND_HINT`

### AC19 — Structured INFO log lines are PII-austere (FR37 / NFR15)

**Given** any successful invocation of `mark-paid` / `suspend` / `reactivate`
**When** the INFO log line is emitted
**Then** the line contains `id=key_<ulid>` and (for `mark-paid`) `paid_until=<date>` and `reactivated=<bool>`
**And** the line does NOT contain: the customer name, email, CPF, CNPJ (any digit run of length 11–14), the plaintext bearer (`cmdr_live_`), the SHA-256 hash (64 hex chars), or an `Authorization` header substring

Test via a combined regex across `caplog.records[*].message`.

### AC20 — Three commands surface at top-level `comadre-keys --help`

**Given** `comadre-keys --help`
**When** the help text is rendered
**Then** `mark-paid`, `suspend`, `reactivate` each appear as top-level commands (flat, not nested under `billing`)
**And** each one's one-line description matches the one in §4a / §4b / §4c

### AC21 — `show --audit-tail` renders the three new actions verbatim

**Given** a key with one of each action in its audit history
**When** the operator runs `comadre-keys show cmdr_Pq --audit-tail 20`
**Then** the AuditTail section contains the uppercased strings `MARK_PAID`, `SUSPEND_KEY`, `REACTIVATE_KEY`
**And** the `MARK_PAID` line's trailing details block shows `{"paid_until": "2026-06-05", "reactivated": false}` (or `true`) as a JSON suffix
**And** the `SUSPEND_KEY` and `REACTIVATE_KEY` lines have no trailing details (their `details_json IS NULL`)

### AC22 — No new dependency in `pyproject.toml`

**Given** the diff at story completion
**When** `git diff pyproject.toml` is inspected
**Then** zero lines changed under `[project] dependencies` or `[project.optional-dependencies]`
**And** `uv sync` produces no lockfile changes beyond what this story's `.py` edits strictly require (none expected)

### AC23 — No `rate_limit.py` / `api.py` changes

**Given** the diff at story completion
**When** `git diff src/comadre/rate_limit.py src/comadre/api.py` is inspected
**Then** both files are unchanged. Rate-limit buckets are keyed on `key_id` and survive suspend/reactivate round-trips by design (Story 2.2 architecture); no code change is required to honor FR20's propagation bound (the sentinel pattern from Story 2.1 does the flush).

## Tasks / Subtasks

- [x] **Task 1 — Promote the shared CLI preamble helpers** (AC16, AC17, AC18)
  - [x] 1.1 Rename `_load_settings_and_tz` → `load_settings_and_tz` in `src/comadre/keys/cli/commands/keys.py`.
  - [x] 1.2 Rename `_resolve_key_target` → `resolve_key_target` in the same file.
  - [x] 1.3 Update the three existing call sites in `keys.py` (update-key, rotate-key, revoke-key) to use the new names.
  - [x] 1.4 Confirm `_truncate_ident` stays private (it's formatting, not flow) and is importable as `from comadre.keys.cli.commands.keys import _truncate_ident` for `billing.py` error-echo use.
  - [x] 1.5 Run `uv run ruff check . && uv run mypy src/ && uv run pytest` — zero regressions in the Story 1.6 test suite.

- [x] **Task 2 — `mark_key_paid` helper** (AC1, AC2, AC3, AC5 defense-in-depth, AC6, AC8)
  - [x] 2.1 `MarkPaidResult` dataclass in `src/comadre/keys/db.py` (frozen, slots=True).
  - [x] 2.2 `mark_key_paid(conn, key_id, *, paid_until, actor, today)` per §1 spec.
  - [x] 2.3 Single CASE-expression UPDATE; `WHERE id = ? AND status != 'revoked'` defense-in-depth.
  - [x] 2.4 Audit row with `action='mark_paid'`, details `{"paid_until", "reactivated"}`.
  - [x] 2.5 `_touch_auth_cache_sentinel(conn)` after commit.
  - [x] 2.6 Post-commit re-read via `get_key_detail_by_id`; RuntimeError on vanished row.

- [x] **Task 3 — `suspend_key` helper** (AC9, AC10, AC11, AC12)
  - [x] 3.1 `SuspendKeyResult` dataclass.
  - [x] 3.2 `suspend_key(conn, key_id, *, actor, today)` per §2 spec.
  - [x] 3.3 `UPDATE ... SET status='suspended' WHERE id = ? AND status = 'active'`; rowcount-1 guard → RuntimeError.
  - [x] 3.4 Audit row `action='suspend_key'`, `details_json IS NULL`.
  - [x] 3.5 Sentinel touch + re-read.

- [x] **Task 4 — `reactivate_key` helper** (AC13, AC14, AC15)
  - [x] 4.1 `ReactivateKeyResult` dataclass.
  - [x] 4.2 `reactivate_key(conn, key_id, *, actor, today)` per §3 spec.
  - [x] 4.3 `UPDATE ... SET status='active' WHERE id = ? AND status = 'suspended'`; rowcount-1 guard.
  - [x] 4.4 Explicit `paid_until` preservation (the UPDATE does not include `paid_until` in the SET clause — AC13 load-bearing).
  - [x] 4.5 Audit row `action='reactivate_key'`, `details_json IS NULL`.
  - [x] 4.6 Sentinel touch + re-read.

- [x] **Task 5 — `src/comadre/keys/cli/commands/billing.py`** (AC1, AC5, AC7, AC9, AC13, AC16, AC17, AC18, AC20)
  - [x] 5.1 Module docstring with the exit-code contract.
  - [x] 5.2 `mark_paid_cmd` — validation ladder per §4a; complimentary short-circuit BEFORE helper call.
  - [x] 5.3 `suspend_cmd` — per §4b.
  - [x] 5.4 `reactivate_cmd` — per §4c.
  - [x] 5.5 All three commands reuse `load_settings_and_tz` + `resolve_key_target` from `keys.py`.
  - [x] 5.6 `--until` parser: `date.fromisoformat(until.strip()).isoformat()`; empty-string + parse-error → exit 2 with the example-bearing hint.
  - [x] 5.7 INFO log lines emitted via `_logger = get_logger("keys.cli")`; assert no PII via the AC19 regex in tests.

- [x] **Task 6 — Register `billing_app` in `src/comadre/keys/cli/app.py`** (AC20)
  - [x] 6.1 Import `billing_app` from `comadre.keys.cli.commands.billing`.
  - [x] 6.2 `app.registered_commands.extend(billing_app.registered_commands)` after the existing three extends (customers / keys / system).

- [x] **Task 7 — Docs sweep**
  - [x] 7.1 `CLAUDE.md` — add `mark-paid, suspend, reactivate` to the CLI commands bullet.
  - [x] 7.2 `README.md` — one-line mention of the three new verbs in the CLI overview (verify a CLI section exists; add if absent).
  - [x] 7.3 `docs/configuration-reference.md` — cross-reference pointer under the billing-timezone entry (one line).
  - [x] 7.4 Do NOT create `docs/monetization.md` — deferred to Story 4.6 per §6 scope note.

- [x] **Task 8 — Tests: helpers**
  - [x] 8.1 `tests/test_keys_db.py::TestMarkKeyPaid` — happy / suspended-reactivates / revoked / complimentary / missing / atomicity / past-date / sentinel-touched.
  - [x] 8.2 `tests/test_keys_db.py::TestSuspendKey` — happy / already-suspended / revoked / missing / complimentary-allowed.
  - [x] 8.3 `tests/test_keys_db.py::TestReactivateKey` — happy (paid_until preserved!) / already-active / revoked / missing.
  - [x] 8.4 `tests/test_keys_audit.py` — regression that the new `details_json` shapes (`{"paid_until", "reactivated"}`) pass the `_FORBIDDEN_DETAIL_KEYS` check and round-trip unchanged.

- [x] **Task 9 — Tests: CLI end-to-end** (one file per command per Story 1.6 convention)
  - [x] 9.1 `tests/test_keys_cli_mark_paid.py` — NEW; ~15 cases covering AC1, AC2, AC3, AC5, AC6, AC7, AC8, AC16, AC17, AC18, AC19, AC20, plus ConfirmationLine byte-identity + sentinel-mtime-advanced assertions + sub-200ms advisory timing.
  - [x] 9.2 `tests/test_keys_cli_suspend.py` — NEW; ~10 cases covering AC9, AC10, AC11, AC12, AC16, AC17, AC18, AC19, AC20.
  - [x] 9.3 `tests/test_keys_cli_reactivate.py` — NEW; ~10 cases covering AC13, AC14, AC15, AC16, AC17, AC18, AC19, AC20, with an explicit `paid_until`-preservation assertion on the happy path.

- [x] **Task 10 — Tests: integration + show coverage**
  - [x] 10.1 `tests/test_keys_cli_show.py` — extend `TestShowKeyAuditTail` with cases that seed audit rows via the real commands (not `_raw_insert_audit`) to confirm AC21 (MARK_PAID / SUSPEND_KEY / REACTIVATE_KEY render verbatim with correct details suffixes).
  - [x] 10.2 `tests/test_keys_auth.py` — add a test that exercises the full suspend → auth-denied → mark-paid → auth-allowed round-trip via the CLI + the registry auth path. This is the AC4 assertion end-to-end.

- [x] **Task 11 — Sanity gates**
  - [x] 11.1 `uv run ruff check .` clean.
  - [x] 11.2 `uv run mypy src/` clean (strict + pydantic plugin).
  - [x] 11.3 `uv run pytest` — all new tests pass; pre-story baseline (1090) plus story additions (~45-55 new tests estimated).
  - [x] 11.4 `uv run pre-commit run --all-files` clean.
  - [x] 11.5 Grep checks:
    - [x] `rg "HTTPException" src/comadre/keys/cli/commands/billing.py` → zero hits (UX-DR10 + `ComadreError`-only contract).
    - [x] `rg "\\bprint\\(" src/comadre/keys/cli/commands/billing.py` → zero hits (use `render_confirmation` / `render_error`).
    - [x] `rg "os\\.environ" src/comadre/keys/cli/commands/billing.py src/comadre/keys/db.py` → zero hits (use pydantic-settings).
    - [x] `rg -n "paid_until" src/comadre/keys/db.py | rg -v "billing_mode"` — manually eyeball: every `paid_until` touch should be next to a `billing_mode` check or storage, consistent with the CLAUDE.md gotcha "Never check `paid_until` without also checking `billing_mode`".
    - [x] `git diff src/comadre/rate_limit.py src/comadre/api.py` → empty (AC23).
    - [x] `git diff pyproject.toml uv.lock` → empty or only whitespace (AC22).

## Dev Notes

### Import-graph placement

No new module in the runtime auth graph. The new CLI module `keys/cli/commands/billing.py` slots into the existing CLI hierarchy:

```
keys/cli/commands/billing.py → {
    keys/cli/commands/keys.py        (for load_settings_and_tz,
                                      resolve_key_target, _truncate_ident,
                                      _KEY_NOT_FOUND_HINT, etc.)
    keys/cli/output.py                (for render_error, render_confirmation)
    keys/cli/_errors.py               (for first_error_msg, is_missing_encryption_key)
    keys/cli/_clock.py                (for resolve_today_in_tz)
    keys/db.py                        (for the three new helpers)
    keys/audit.py                     (for get_cli_actor)
    keys/models.py                    (for KeyDetailRow type hints)
    comadre.config                    (for get_settings)
    comadre.logging                   (for get_logger)
}
```

No reverse edges. `keys/auth.py`, `rate_limit.py`, `main.py`, `api.py`, `keys/cache.py`, `keys/counters.py` do not import `billing.py`.

### Why the three commands share one module

All three verbs share the same dispatch shape (settings → tz → DB → resolve → helper → confirm) and the same helper-error taxonomy. Splitting them into three files would triplicate the docstring header and the `_KEY_*_HINT` imports. Story 3.2 will add `at-risk` and `revenue` to the same module — those are read-only so they diverge from the mutation shape, but keeping them co-located keeps the "billing concern" surface in one file for the sprint-09 reviewer's eye.

### Why `mark-paid` does not take `--yes` or prompt

Per UX-DR11 tier table (`ux-design-specification.md:893`), `mark-paid` / `suspend` / `reactivate` are all `Mutate` tier (reversible). None of them prompt. The only `Destroy`-tier verbs in Epic 3 are Story 3.3's `suspend-sweep` (not prompted — it's cron-driven; the `--yes` is implicit in the cron schedule) and Story 4.1's `delete-customer --hard`. Operators running the Day-05 billing ritual process 20 keys in 5 minutes; any prompt would blow that budget.

### Why the `reactivated` flag lives in `details_json` and not a second audit row

Two audit rows with the same `occurred_at` and different `action` strings (`mark_paid` + `reactivate_key`) would render in `show --audit-tail` as two lines, breaking the operator's mental model that "one operator command = one audit event". The single-row form with `{"reactivated": true}` in details is queryable for Story 3.2 reports (`WHERE action='mark_paid' AND json_extract(details_json, '$.reactivated') = 1`) and displays cleanly in the tail.

### Complimentary + `mark-paid` — why exit 0 not exit 3

The epic AC (`epics.md:642`) specifies: "`Key cmdr_Pq is complimentary — no payment tracking required.` and exits with code 0". This is counter to the usual "unsupported operation → exit 3" taxonomy but is UX-driven: complimentary keys are a small minority of the portfolio, and an operator who runs `mark-paid` on one is making a context-switch mistake (they're in billing-ritual flow, not in complimentary-management flow). The friendly exit 0 tells them "no harm done, this key doesn't need this command" without breaking their flow. The helper-level `ValueError` still exists as defense-in-depth for any non-CLI caller.

### Past dates accepted (AC8 rationale)

The temptation is to reject `--until <past-date>` because it looks wrong. Don't. Real operator workflows include:

- The receipt from the bank clearing system arrives 3–5 days after the Pix transfer. Operator logs `paid_until=<day of transfer>` retroactively.
- A customer pays for two months at once; operator logs the first month on the 05th, the second on the 05th of the next month — but by then the first month's date is in the past.
- Audit backfill: operator reconstructs billing history from Pix statements on a new VPS.

The cron sweep runs nightly with `paid_until < today`; past dates correctly trigger the next sweep. No silent data corruption; just honest state.

### No `--format json` on the mutation verbs

The `--help` example in `ux-design-specification.md:1008` shows `--format TEXT  Output format: table, json  [default: table]` for `mark-paid`. Story 1.6 did not ship `--format json` on `update-key` / `rotate-key` / `revoke-key` (none of the ConfirmationLine-class commands do). Story 3.1 continues that precedent: no `--format json` on the three new verbs.

Operators who need machine-readable output can run `comadre-keys show <prefix> --format json` immediately after the mutation to capture post-state. This keeps the mutation surface minimal; adding JSON output to every mutation bloats the spec surface and tempts operators to script fragile pipelines against ConfirmationLine parsing (which is explicitly not a stable interface — the pt-BR grammar may evolve).

If the operator survey post-MVP strongly requests JSON output on mutations, it's a trivial additive change (one branch inside each `_cmd` function).

### `suspend_key` action name alignment with cron

Story 3.3 will write `suspend_key` audit rows under actor `cron:suspension-sweep`. Using the same action string here (`suspend_key`, not `suspend` or `manual_suspend`) means:

- `show --audit-tail` renders manual and cron suspensions as `SUSPEND_KEY` with different actors — the operator reads the actor column to distinguish.
- Story 3.4's health command can query `SELECT * FROM audit_log WHERE action='suspend_key' AND actor LIKE 'cron:%' ORDER BY occurred_at DESC LIMIT 1` for "last successful sweep" without branching on action-name.
- Story 3.2's revenue report can count `WHERE action='suspend_key' AND occurred_at >= ?` for "suspensions this month" without branching.

### `_FORBIDDEN_DETAIL_KEYS` is safe for the new details

`src/comadre/keys/audit.py:23-33` blocklists `{cpf, cnpj, tax_id, name, email, key_plaintext, authorization}` (case-insensitive, recursive on nested dicts). The new `details_json` shape for `mark_paid` is `{"paid_until": "<YYYY-MM-DD>", "reactivated": <bool>}` — none of those keys are in the blocklist. No audit-guard update required.

### Test-flake avoidance

The sub-200 ms assertion in AC1 (`test_mark_paid_happy_path_under_200ms`) is an advisory performance check. If the CI runner is under load, a cold-start SQLite path can cross 200 ms occasionally. Use `time.perf_counter()`, record the delta, and `assert elapsed_ms < 500` in CI (generous) while logging the actual time to stderr for local runs. The UX spec's 200 ms is the *user-perceived* latency bound on a warm VPS; flaky test failures on a cold CI runner are noise.

### Project Structure Notes

**New files:**

```
src/comadre/keys/cli/commands/
  billing.py                                    [NEW]

tests/
  test_keys_cli_mark_paid.py                    [NEW]
  test_keys_cli_suspend.py                      [NEW]
  test_keys_cli_reactivate.py                   [NEW]
```

**Modified files:**

```
src/comadre/keys/
  db.py                                         [MOD — 3 helpers + 3 result dataclasses]
  cli/app.py                                    [MOD — register billing_app]
  cli/commands/keys.py                          [MOD — promote _load_settings_and_tz,
                                                        _resolve_key_target to public names]

tests/
  test_keys_db.py                               [MOD — 3 new TestClasses]
  test_keys_audit.py                            [MOD — details_json regression case]
  test_keys_cli_show.py                         [MOD — AuditTail rendering AC21]
  test_keys_auth.py                             [MOD — full round-trip AC4]

docs/
  configuration-reference.md                    [MOD — cross-reference pointer]

CLAUDE.md                                       [MOD — CLI command list]
README.md                                       [MOD — CLI overview mention]
```

**Unchanged (asserted by AC22 / AC23):**

```
src/comadre/rate_limit.py                       — rate-limit bucket key is key_id,
                                                  stable across status changes
src/comadre/api.py                              — no new route, no middleware change
src/comadre/keys/auth.py                        — sentinel-driven cache flush already works
src/comadre/keys/cache.py                       — AuthCache invalidation is general-purpose
src/comadre/keys/migrations/v001_initial.sql    — no schema change
pyproject.toml, uv.lock                         — no new dependency
```

### Testing standards

- All tests run without the TTS model (`test_api.py::app` fixture already mocks the engine router; not needed here but the convention stands).
- CLI tests use `CliRunner` from `typer.testing` and the `_reset_consoles_to_buffers` auto-fixture (copy from `tests/test_keys_cli_revoke_key.py` verbatim — Story 1.6 established the pattern and Story 3.1 follows it).
- DB tests use `tmp_path` for the SQLite file, `get_connection` + `_apply_migrations` per the project pattern. Never hand-roll SQL to seed state — use `insert_customer` + `insert_api_key` (helpers enforce the schema contract and the audit-write invariant).
- `caplog` captures INFO log lines for AC19 assertions.
- Freeze today via `monkeypatch` on `comadre.keys.cli._clock.resolve_today_in_tz` or on `comadre.keys.auth._today_in_billing_tz` depending on which surface the test exercises. Never freeze `date.today` globally.
- PII-regex guard for AC19 — reuse the combined regex from Story 2.3 `tests/test_counters.py`:
  ```python
  _PII_FORBIDDEN_RE = re.compile(
      r"cmdr_live_|[0-9a-f]{64}|[0-9]{11,14}|@[a-z0-9.-]+\.[a-z]{2,}",
      re.IGNORECASE,
  )
  ```
  Assert no match across any `caplog.records[*].message` for each test case that exercises a successful command path.

### References

- Epic 3 + Story 3.1 scope — `_bmad-output/planning-artifacts/epics.md:605–646`
- FR15 / FR19 / FR20 full wording — `_bmad-output/planning-artifacts/prd.md:1144,1148,1149`
- UX-DR7 ConfirmationLine — `_bmad-output/planning-artifacts/ux-design-specification.md:835–846`
- UX-DR11 three-tier command hierarchy — `_bmad-output/planning-artifacts/ux-design-specification.md:884–914`
- Journey 2 (monthly billing ritual) — `_bmad-output/planning-artifacts/ux-design-specification.md:308–345, 572–602`
- Journey 3 (delinquent customer) — `_bmad-output/planning-artifacts/ux-design-specification.md:369–406, 604–631`
- Journey 6 (complimentary subscription) — `_bmad-output/planning-artifacts/ux-design-specification.md:495–558`
- Architecture billing module layout — `_bmad-output/planning-artifacts/architecture.md:335–358, 648`
- Architecture billing-provider pattern — `_bmad-output/planning-artifacts/architecture.md:442–458`
- Architecture action-name conventions — `_bmad-output/planning-artifacts/architecture.md:322–325`
- CLAUDE.md gotcha (`paid_until` + `billing_mode` pairing) — `CLAUDE.md` §Non-Obvious Gotchas (though currently documented in architecture.md:496–497, the rule applies)
- Story 1.6 CLI preamble pattern — `src/comadre/keys/cli/commands/keys.py:737–813`
- Story 1.6 helper pattern (transaction + audit + sentinel + re-read) — `src/comadre/keys/db.py:847–1125`
- Story 2.1 sentinel invalidation pattern — `src/comadre/keys/cache.py:60–85`, `src/comadre/keys/db.py:163–183`
- Story 2.1 auth flow — `src/comadre/keys/auth.py:106–185`
- ManualBillingProvider current semantics — `src/comadre/keys/billing.py:32–51`
- `ApiKeySuspendedError` envelope — `src/comadre/exceptions.py` (used at `src/comadre/keys/auth.py:142`)

## Questions for Operator (please confirm before dev-story)

1. **Complimentary `mark-paid` — exit 0 vs exit 3.** The epic explicitly specifies exit 0 with the informational message. I've honored that (AC5). Confirm the helper-level `ValueError` mapped to exit 0 at the CLI (and exit 3 for any non-CLI caller) is the right split. Alternative: make the helper return a `SkippedComplimentary` sentinel instead of raising, so the "no error" semantics are explicit at the type level. Recommend accepting the story's default (CLI short-circuits before calling the helper); non-CLI callers are hypothetical today.

2. **`reactivate` on complimentary — any guardrails?** The story allows `suspend` on a complimentary key (AC12 — abuse case). Symmetry suggests `reactivate` should work on a suspended complimentary key too (bundle renewed). The helper allows it; no special handling needed. Confirm this reading, or specify a rejection.

3. **Past-date `mark-paid` — any warning?** AC8 accepts past dates silently. Alternative: print a `Warning:` line to stderr before the ConfirmationLine (like `issue-key`'s RPM-over-VPS-tier warning at `ux-design-specification.md:936`). Recommend silent accept — retroactive logging is a normal workflow and a warning would train operators to ignore warnings.

4. **`suspend` / `reactivate` JSON output.** §Scope §6 says no `--format json` on the three new verbs, matching the Story 1.6 precedent. Confirm this is acceptable even though the UX spec's `mark-paid --help` example shows `--format` as an option. If operators need structured output for scripted billing pipelines, we add it as a one-line extension.

5. **Docs scope.** §6 defers `docs/monetization.md` to Story 4.6. Confirm no dedicated operator runbook doc is required at 3.1 close; the per-command `--help` + the cross-references in CLAUDE.md / README.md are sufficient.

6. **Helper-promotion diff.** Task 1 renames `_load_settings_and_tz` → `load_settings_and_tz` and `_resolve_key_target` → `resolve_key_target` in `keys.py`, updating the three existing call sites. Alternative: keep the leading underscore and add a re-export shim (`from comadre.keys.cli.commands.keys import _load_settings_and_tz as load_settings_and_tz`) — uglier but zero-blast-radius on the Story 1.6 code. Recommend the rename — the helpers are now cross-module shared and the underscore was correct when they were single-module private, wrong now.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M context).

### Debug Log References

- Ruff / ruff-format — all 8 touched files reformatted in Task 11 sanity sweep (ruff-format applied line-length 88 rewraps).
- Mypy strict — clean on 33 source files after adding three helpers + dataclasses in `db.py`.
- Full test suite — 1162 passed (pre-story baseline 1090 + 72 story additions).
- Pre-commit — all hooks green (ruff-check, ruff-format, hadolint, yamllint, shellcheck, markdownlint-cli2, mypy).

### Completion Notes List

- **Task 1 — helper rename.** Renamed `_load_settings_and_tz` → `load_settings_and_tz` and `_resolve_key_target` → `resolve_key_target` in `src/comadre/keys/cli/commands/keys.py`. Updated the 3 call sites (update-key, rotate-key, revoke-key). `_truncate_ident` stayed private and is imported from `billing.py` for error-title echoing.
- **Tasks 2–4 — DB helpers.** Added `MarkPaidResult`, `SuspendKeyResult`, `ReactivateKeyResult` dataclasses and `mark_key_paid` / `suspend_key` / `reactivate_key` helpers to `src/comadre/keys/db.py`. `mark_key_paid` uses a single CASE-expression UPDATE for atomic suspended→active flip. `reactivate_key` explicitly does NOT touch `paid_until` (load-bearing FR20-complement per AC13). All three call `_touch_auth_cache_sentinel(conn)` after commit and re-read via `get_key_detail_by_id`.
- **Task 5 — billing CLI module.** New `src/comadre/keys/cli/commands/billing.py` Typer subapp with `mark-paid`, `suspend`, `reactivate`. Complimentary short-circuit lives in the `mark-paid` CLI (exit 0 informational per AC5); the helper raises ValueError as defense-in-depth for non-CLI callers. `--until` parsed via `date.fromisoformat(raw.strip()).isoformat()` so compact ISO forms (`20260605`) normalize to canonical `2026-06-05` before storage.
- **Task 6 — CLI registration.** Appended `billing_app.registered_commands` to `app.registered_commands` in `src/comadre/keys/cli/app.py` after customers/keys, before system. Flat surface — operators invoke `comadre-keys mark-paid` etc. at the top level.
- **Task 7 — docs.** Added the three verbs to the `CLAUDE.md` CLI bullet (alphabetical-by-function: customers → keys → billing → system). Added a one-line README bullet under "Registry-backed API keys". Added the "see also" cross-reference under the BILLING_TIMEZONE row in `docs/configuration-reference.md`. `docs/monetization.md` deferred to Story 4.6 per §6.
- **Tasks 8–10 — tests.** Added helper test classes (`TestMarkKeyPaid`, `TestSuspendKey`, `TestReactivateKey`) + 3 sentinel-touch cases in `test_keys_db.py`. Added `test_mark_paid_details_shape_roundtrips` in `test_keys_audit.py`. Three new CLI test files (`test_keys_cli_mark_paid.py` 15 cases, `test_keys_cli_suspend.py` 10 cases, `test_keys_cli_reactivate.py` 9 cases). Added AC21 show-audit-tail cases in `test_keys_cli_show.py` (`test_billing_verbs_render_via_real_commands`, `test_mark_paid_reactivation_renders_true_details`) and AC4 full round-trip (`TestFR20RoundTripViaCli.test_full_fr20_round_trip`) in `test_keys_auth.py`.
- **Task 11 — gates.** `ruff check .`, `mypy src/`, `pytest`, and `pre-commit run --all-files` all clean. All grep checks passed: zero `HTTPException` / `print(` / `os.environ` hits in new files; `rate_limit.py` + `api.py` diff empty (AC23); `pyproject.toml` + `uv.lock` diff empty (AC22).
- **AC coverage summary.** AC1/AC2/AC8 (active mark-paid + audit + past date) via `TestMarkPaidActivePath` + `TestMarkPaidPastDate`. AC3 (reactivation + `reactivated: true` audit) via `TestMarkPaidReactivation`. AC4 (FR20 full round-trip via CLI + sentinel cache flush) via `TestFR20RoundTripViaCli`. AC5 (complimentary exit 0) via `TestMarkPaidComplimentary`. AC6 (revoked exit 3) via `TestMarkPaidRevoked`. AC7 (bad --until shapes, no DB open) via `TestMarkPaidUntilShape`. AC9–AC12 via `TestSuspendActive` + `TestSuspendTerminalStates` + `TestSuspendComplimentary`. AC13–AC15 via `TestReactivateSuspended` + `TestReactivateTerminalStates` (including the load-bearing `paid_until`-preserved assertion). AC16/AC17/AC18 (identifier resolution) covered in all three CLI test files. AC19 (PII-austere logs) via the `_PII_FORBIDDEN_RE` regex guard in each CLI test file. AC20 (top-level help) via three `TestXxxHelp` classes. AC21 (show audit-tail rendering) via the two new `TestShowKeyAuditTail` siblings. AC22/AC23 (no dep changes, rate_limit/api untouched) via git-diff grep checks at Task 11.

### File List

**New:**

```
src/comadre/keys/cli/commands/billing.py
tests/test_keys_cli_mark_paid.py
tests/test_keys_cli_suspend.py
tests/test_keys_cli_reactivate.py
```

**Modified:**

```
src/comadre/keys/db.py                       (3 helpers + 3 result dataclasses)
src/comadre/keys/cli/app.py                  (register billing_app)
src/comadre/keys/cli/commands/keys.py        (helper rename: _load_settings_and_tz → load_settings_and_tz, _resolve_key_target → resolve_key_target)
tests/test_keys_db.py                        (TestMarkKeyPaid / TestSuspendKey / TestReactivateKey + 3 sentinel-touch cases)
tests/test_keys_audit.py                     (test_mark_paid_details_shape_roundtrips)
tests/test_keys_cli_show.py                  (AC21 — TestShowKeyAuditTail::test_billing_verbs_render_via_real_commands + test_mark_paid_reactivation_renders_true_details)
tests/test_keys_auth.py                      (AC4 — TestFR20RoundTripViaCli::test_full_fr20_round_trip)
docs/configuration-reference.md              (BILLING_TIMEZONE see-also cross-ref)
CLAUDE.md                                    (CLI command list)
README.md                                    (billing verbs bullet)
_bmad-output/implementation-artifacts/sprint-status.yaml  (story transition)
```

**Unchanged (asserted by AC22 / AC23):**

```
src/comadre/rate_limit.py
src/comadre/api.py
src/comadre/keys/auth.py
src/comadre/keys/cache.py
src/comadre/keys/migrations/v001_initial.sql
pyproject.toml
uv.lock
```

### Review Findings

Reviewed 2026-04-18 — three-layer adversarial review (Blind Hunter, Edge Case Hunter, Acceptance Auditor). After deduplication: 4 patches, 5 deferred, 12 dismissed.

- [x] [Review][Patch] `mark_key_paid` is missing the `cursor.rowcount != 1` guard that `suspend_key` and `reactivate_key` have [src/comadre/keys/db.py:1203-1209] — if a concurrent writer revokes the row between the SELECT and the UPDATE, the `WHERE id = ? AND status != 'revoked'` filter makes the UPDATE no-op, yet the helper still writes a `mark_paid` audit row and returns a `MarkPaidResult` whose refreshed `key.status` is `'revoked'` with `reactivated` reflecting the pre-UPDATE read. Add `if cursor.rowcount != 1: raise RuntimeError(...)` after the UPDATE, matching the sibling helpers' shape. Narrow real-world blast radius (single-writer CLI) but the asymmetry breaks the defense-in-depth invariant the spec explicitly argues for (§1.5 "Why the CASE expression and not a branch"). **Fixed.**
- [x] [Review][Patch] `assert result is not None` is stripped under `python -O` and leaves an `AttributeError` traceback instead of a clean exit [src/comadre/keys/cli/commands/billing.py:194, 285, 373] — replace each with `if result is None: raise typer.Exit(code=5)` (or `RuntimeError` + the existing exit-5 branch). Not common in day-to-day use, but CLIs that ship in PyInstaller bundles or wrapped in `python -O` lose the defense entirely. **Fixed** — replaced all three with explicit `if result is None: render_error(...); raise typer.Exit(code=5)`.
- [x] [Review][Patch] `_touch_auth_cache_sentinel(conn)` runs unguarded after the `with conn:` block in all three new helpers [src/comadre/keys/db.py:1219, 1282, 1345] — if the sentinel touch raises (disk full, EPERM on the sentinel file, read-only FS), the DB commit has already landed but the auth-cache flush never fires, so replicas keep serving stale cached `AuthPayload`s until the next successful sentinel touch or the 60 s TTL. Wrap the call in a guard that logs at WARNING and swallows, e.g. `try: _touch_auth_cache_sentinel(conn); except OSError as exc: _logger.warning("sentinel touch failed after commit: %s", exc)`. Keeps the state↔audit invariant aligned with graceful degradation rather than raising from a post-commit context. **Fixed** — guard moved into `_touch_auth_cache_sentinel` itself (single point of failure), wrapping `sentinel.touch()` + `_chmod_0600` in `contextlib.suppress(OSError)` with an updated docstring. Covers all six existing + new call sites, not just the three new ones.
- [x] [Review][Patch] AC19 tests assert `paid_until=` / `reactivated=` / `key_prefix=` but never `id=key_<ulid>` — the spec is explicit that the INFO log line MUST contain `id=key_<ulid>` on all three verbs [tests/test_keys_cli_mark_paid.py ≈L494-495, tests/test_keys_cli_suspend.py ≈L2822, tests/test_keys_cli_reactivate.py ≈L2436]. Production code emits `id=%s` correctly; this is a test-coverage gap. Add `assert "id=key_" in joined` to each of the three PII-austere-log test bodies. **Fixed** — `assert "id=key_" in joined` added to all three log-assertion sites.
- [x] [Review][Defer] `get_connection` exception path only catches `sqlite3.Error`, not `OSError`/`PermissionError` [src/comadre/keys/cli/commands/billing.py:136, 238, 326] — deferred, pre-existing pattern across all CLI commands in `keys.py` (L299, L625, L925, L1035, L1198). Fixing only `billing.py` creates inconsistency; broader audit belongs to a separate CLI robustness story.
- [x] [Review][Defer] `_apply_migrations` exception path only catches `sqlite3.Error`, not `RuntimeError` — the helper raises `RuntimeError` on schema-version downgrade [src/comadre/keys/db.py:266], which would bubble as a raw traceback [src/comadre/keys/cli/commands/billing.py:143, 245, 333] — deferred, same pre-existing pattern mirrored from `keys.py`. The helper-dispatch catches both types; the migrations site does not. Belongs to the same CLI robustness sweep as F4.
- [x] [Review][Defer] No DB-level CHECK constraint on `api_key.paid_until` format [src/comadre/keys/migrations/v001_initial.sql] — deferred, pre-existing schema. The helper relies on "caller-validated YYYY-MM-DD"; a direct non-CLI caller could store a malformed string. AC22 explicitly forbids schema changes in this story.
- [x] [Review][Defer] Three `# type: ignore[attr-defined]` directives added at `settings.key_registry_db_path` access sites [src/comadre/keys/cli/commands/billing.py:135, 237, 325] — deferred, pre-existing signature drift on `load_settings_and_tz` (returns a loose tuple typing). Fixing requires widening the helper's return type across all CLI call sites; out of scope for 3.1.
- [x] [Review][Defer] Copy-paste drift across three `_seed_customer_and_key` helpers in the new CLI test files, each with slightly different signatures and defaults — deferred, cosmetic test-only concern; the same pattern was accepted in Story 1.6 and merits a separate tests-refactor pass rather than per-story churn.

**Dismissed (12):** `_parse_until` accepts ISO week-date forms like `2026-W23-5` (spec explicitly permits alternate ISO forms, `.isoformat()` normalizes deterministically); private cross-module imports of `_apply_migrations` / `_truncate_ident` (spec §4 explicitly permits the `_truncate_ident` re-import); complimentary exit-0 path conflates with real success on stdout (spec AC5 mandates the exact wording); audit action-name asymmetry `mark_paid` vs `suspend_key` / `reactivate_key` (spec §2 deliberately aligns with Story 3.3's cron-sweep action name); unknown ValueError from helper re-raised raw (deliberate — genuine surprises should surface with traceback for debugging rather than being caught by a catch-all); `async def test_full_fr20_round_trip` missing `@pytest.mark.asyncio` (pytest-asyncio `asyncio_mode = "auto"` is set in `pyproject.toml`); sentinel-mtime flakiness on coarse-resolution filesystems (2 s offset comfortably exceeds modern FS resolution); AC4 `_sentinel_mtime_ns` not explicitly asserted in round-trip test (functional `ApiKeySuspendedError` assertion is a stronger end-to-end proof than asserting a private attribute); `conn.close()` suppress scope `sqlite3.Error` is too narrow (`Connection.close()` does not raise `OSError` in practice); `resolve_key_target` test-fixture console-binding concern (266 tests pass, binding works); test-module imports allegedly missing (verified all imports present in `tests/test_keys_auth.py` L3-32); sentinel file permissions diverge between test and production (no perms check in `_touch_auth_cache_sentinel`, non-issue).

### Change Log

| Date       | Change                                                              |
|------------|---------------------------------------------------------------------|
| 2026-04-18 | Story 3.1 — landed mark-paid / suspend / reactivate CLI + helpers; renamed shared CLI preamble helpers to public names; 72 new tests, all AC covered, status → review. |
| 2026-04-18 | Code review — 4 patches queued, 5 deferred, 12 dismissed; no decision-needed items. Status stays `review` until patches are resolved. |
| 2026-04-18 | Code-review patches applied: `mark_key_paid` rowcount guard, `assert → typer.Exit` at 3 CLI sites, `_touch_auth_cache_sentinel` wrapped in `OSError` suppress at the definition (covers all 6 call sites), `id=key_` log-assertion added at 3 test sites. All 1162 tests pass, ruff/mypy clean. Status → `done`. |
