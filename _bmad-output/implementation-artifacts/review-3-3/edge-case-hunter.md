# Edge-Case Hunter — Story 3.3

- **Title** — `completed_at` sampled before the transaction can violate AC3 byte-identity under clock-adjustment
- **Location** — `src/comadre/keys/db.py:1422-1458`
- **Trigger** — NTP slew / manual `timedatectl set-time` / container clock skew between `_utcnow_iso()` at line 1423 and the summary-row INSERT inside the `with conn:` block. The stamp is captured before the UPDATE and all per-key audit rows run; on a 1000-row sweep the gap can be 100-1000 ms, enough for an NTP step to make `completed_at` appear to precede the summary row's real wall-clock INSERT time by minutes.
- **Actual behavior** — Returned `result.completed_at` and the summary row's `occurred_at` remain byte-identical (AC3 preserved), but both carry the PRE-transaction timestamp — not the commit instant. Any operator reasoning "when did the sweep finish?" via either value gets a stale answer and `CLAUDE.md`'s gotcha text "`completed_at` is the canonical ISO-UTC timestamp … the sweep wrote on its summary audit row" is misleading — it's actually the "started about to write" timestamp.
- **Expected behavior** — Either sample `completed_at` *after* the `with conn:` block commits (moving the assignment between `with conn:` exit and `_touch_auth_cache_sentinel`) to reflect the real commit instant, or explicitly document that `completed_at` is the sweep *start* time. The current naming + docstring mismatch is the bug, not the placement per se.
- **Severity** — Low

- **Title** — `_utcnow_iso()` second-resolution clobbers ordering when two sweeps fire in the same wall-second
- **Location** — `src/comadre/keys/db.py:191-193`, `get_last_sweep_timestamp` at `src/comadre/keys/db.py:1483-1487`
- **Trigger** — Two back-to-back sweep invocations (e.g. a human operator runs `comadre-keys suspend-sweep` at 00:30:05 and the cron kicks in at exactly 00:30:05 — or the AC17 idempotence test pattern executed rapidly). Timestamps are formatted with `%Y-%m-%dT%H:%M:%SZ` (no microseconds).
- **Actual behavior** — Both summary rows carry identical `occurred_at` strings. `MAX(occurred_at)` returns a tie — SQLite picks one arbitrarily (undefined tie-break without a secondary ORDER BY on `id`). `get_last_sweep_timestamp` still returns *a* timestamp, but `AC16` says "the most-recent sweep's timestamp", which becomes ambiguous under second-collisions.
- **Expected behavior** — Either tie-break by `id DESC` (largest ROWID wins → most recent) or format with sub-second precision. The test `test_returns_most_recent_summary_row` feeds two distinct timestamps 5 s apart so never exercises this.
- **Severity** — Low

- **Title** — Zero-row sweep still writes a summary row in an **empty `with conn:`** block — BEGIN/COMMIT on no work
- **Location** — `src/comadre/keys/db.py:1425-1458`
- **Trigger** — Zero rows expired; `swept_rows` is `[]`; `for row in swept_rows` is a no-op; only the one summary `log_event` runs.
- **Actual behavior** — Works correctly but executes a full UPDATE-that-touches-nothing, plus an INSERT, inside a WAL transaction. The UPDATE still takes write-lock briefly (WAL tolerates this) — fine on a 20-key DB, but on 100 K+ rows the UPDATE scans `idx_api_key_sweep` and can contend with a concurrent writer on a busy multi-replica host. Not a correctness bug, but an observable I/O amplification vs. a "SELECT count first, then only UPDATE if nonzero" design.
- **Expected behavior** — Acceptable for the current scale; document that the sweep always acquires the WAL write-lock even on zero-row days so an operator observing `busy_timeout` stalls at 00:30 knows where to look. Or a guard: if the SELECT-version of the predicate returns zero, skip the UPDATE and still emit the summary row.
- **Severity** — Nit

- **Title** — `billing_mode='complimentary'` but with non-NULL `paid_until` is silently ignored — no defensive log
- **Location** — `src/comadre/keys/db.py:1429`, AC1 (key E in the story spec)
- **Trigger** — The test harness deliberately seeds a complimentary key with `paid_until='2026-04-05'` (the predicate filters it out by `billing_mode='manual'`). In production this state shouldn't exist — Story 1.2 enforces `billing_mode='complimentary' ⟹ paid_until IS NULL` — but no runtime assertion exists if a manual SQL edit or legacy import produces this corruption.
- **Actual behavior** — Corrupt complimentary rows sit permanently un-swept with stale `paid_until`. No warning is emitted.
- **Expected behavior** — Either the schema carries a `CHECK` constraint enforcing the invariant, or `run_suspension_sweep` logs a defensive WARN when it detects complimentary rows with non-NULL `paid_until` during a scan. Neither exists today; the assumption is implicit.
- **Severity** — Nit

- **Title** — `paid_until` comparison is lex-sort vs. semantic date-sort — single-digit "YYYY-M-D" silently never sweeps
- **Location** — `src/comadre/keys/db.py:1432`, `src/comadre/keys/cli/commands/system.py:272` (`date.fromisoformat(row.paid_until)`)
- **Trigger** — A row with `paid_until='2026-4-5'` (non-canonical, non-zero-padded) — never written by Story 3.1's `mark_paid` (it canonicalizes via `_parse_until`), but possible via legacy import or manual SQL. Comparison `'2026-4-5' < '2026-04-06'` is character-wise in SQLite: `'2026-4-5'` starts with `'2026-'` then `'4'` vs. `'0'`; `'4' > '0'` so lex-sort puts it AFTER `'2026-04-06'`. The row never matches the `paid_until < today_iso` predicate.
- **Actual behavior** — Sweep silently skips the non-canonical row. In the dry-run path, `date.fromisoformat('2026-4-5')` actually *succeeds* in Python 3.11+ (the parser was loosened to accept un-padded forms). So dry-run would list it as to-be-suspended while the real sweep doesn't touch it — a **dry-run/real-run divergence** that the test suite never exercises.
- **Expected behavior** — Either canonicalize `paid_until` storage on INSERT/UPDATE at the schema level (CHECK `paid_until GLOB '____-__-__'`) or have the dry-run path use the same lex-comparison the real sweep uses (string `<` on `today.isoformat()`) to keep the two renderings congruent.
- **Severity** — Medium

- **Title** — Dry-run path catches `ValueError` on malformed `paid_until` but silently drops the row
- **Location** — `src/comadre/keys/cli/commands/system.py:271-274`
- **Trigger** — A row whose `paid_until` is malformed beyond what `date.fromisoformat` accepts (e.g. `'2026-02-30'`, `'bogus'`).
- **Actual behavior** — `continue` — the row is skipped from the preview entirely; no warning, no log. The real sweep compares `paid_until < today_iso` as a raw string: `'bogus' > '2026-04-06'` lex-wise, so real sweep also skips. Both agree, but the operator loses visibility on data corruption.
- **Expected behavior** — Emit a WARN-level log line listing `row.key_prefix` so the operator can follow up. The silent `continue` covers real corruption cases the dry-run preview is designed to surface.
- **Severity** — Low

- **Title** — `load_settings_and_tz` ValidationError when *both* encryption key missing and TZ invalid returns on first failure, never surfacing the second
- **Location** — `src/comadre/keys/cli/commands/keys.py:749-779`, consumed by `src/comadre/keys/cli/commands/system.py:200-202`
- **Trigger** — Operator env: `KEY_REGISTRY_ENCRYPTION_KEY` missing AND `BILLING_TIMEZONE=Not/Real` at the same time.
- **Actual behavior** — First `return None` fires on the encryption key failure; operator fixes that, re-runs, gets a *second* exit-6 for the TZ. Two round-trips to diagnose.
- **Expected behavior** — Single pass listing all misconfigurations. Not a regression from this story (pre-existing helper behavior), but worth flagging since `suspend-sweep` inherits it.
- **Severity** — Nit

- **Title** — `cast(Settings, settings_obj)` at `system.py:204` is a typing lie if `load_settings_and_tz` ever narrows
- **Location** — `src/comadre/keys/cli/commands/system.py:200-204`
- **Trigger** — Future refactor of `load_settings_and_tz` that returns a different settings shape (e.g. a read-only DTO). Because the return type is annotated `tuple[object, ZoneInfo] | None`, the `cast` at the call site is a silent bridge that mypy cannot audit.
- **Actual behavior** — A code-level type-safety hole: `settings.key_registry_db_path` access on line 214 would break at runtime without a mypy complaint.
- **Expected behavior** — Tighten `load_settings_and_tz`'s return annotation to `tuple[Settings, ZoneInfo] | None` — the `cast` then becomes unnecessary and the bridge closes.
- **Severity** — Low

- **Title** — `contextlib.suppress(sqlite3.Error)` on `conn.close()` masks operator-visible write failures
- **Location** — `src/comadre/keys/cli/commands/system.py:237-239`
- **Trigger** — On a corrupt or unmountable SQLite file, `conn.close()` can raise (rare but possible — e.g. disk I/O error flushing WAL).
- **Actual behavior** — The close error is swallowed; the sweep reports success even if the final WAL checkpoint fails. The next `comadre-keys` invocation might see the DB in an unexpected state.
- **Expected behavior** — Either log the suppressed error at WARN (for post-mortem) or let it propagate. The current silent suppression is consistent with other commands in the module but hides real problems.
- **Severity** — Nit

- **Title** — Concurrent `mark-paid` during sweep sees intermediate state (TOCTOU of `_touch_auth_cache_sentinel`, not the UPDATE)
- **Location** — `src/comadre/keys/db.py:1460` — `_touch_auth_cache_sentinel(conn)` runs OUTSIDE `with conn:`
- **Trigger** — Sweep commits at T0; between T0 and the `touch()` at T0+ε, operator runs `mark-paid` on one of the swept keys. `mark-paid` acquires the DB write-lock, flips `status='active'`, commits, touches the sentinel, returns. Sweep now resumes and touches the sentinel a *second* time (same mtime second).
- **Actual behavior** — Mostly harmless — two sentinel touches in the same second just means one `AuthCache` flush. But the operator-facing sweep ConfirmationLine still reports "3 key(s) suspended", while one of them has been reactivated seconds later. No audit row drift (both operations committed in order); just an operator-communication issue.
- **Expected behavior** — Document this race — or return `swept_key_ids` (already present in `SuspensionSweepResult`) through to the ConfirmationLine so the operator can cross-check. Current minor.
- **Severity** — Nit

- **Title** — `_touch_auth_cache_sentinel` best-effort swallow hides the one case where AC5 is required to pass
- **Location** — `src/comadre/keys/db.py:238-240`
- **Trigger** — Read-only FS (e.g. Docker bind mount accidentally `:ro`), full disk, EPERM on the parent dir.
- **Actual behavior** — Sweep commits, sentinel touch swallowed via `contextlib.suppress(OSError)`, API replicas don't learn of status change until the 60 s `AuthCache` TTL expires. **AC5 silently breaks**: "`{KEY_REGISTRY_DB_PATH}.invalidate` exists on disk" would be false. No log line tells the operator that the sentinel pipe is broken — only a late-arriving customer 200 (instead of 401) would reveal it.
- **Expected behavior** — Log a WARN when the sentinel touch fails (pattern borrowed from `_touch_auth_cache_sentinel`'s own docstring: "The DB commit is authoritative; cache staleness falls back to TTL"). Currently silent.
- **Severity** — Medium

- **Title** — Dry-run `list_api_keys` pulls the entire `active/manual` set into Python before filtering
- **Location** — `src/comadre/keys/cli/commands/system.py:265-276`
- **Trigger** — A 10 000-customer registry where most keys are currently `active/manual`. Dry-run pulls the full list, then filters in Python.
- **Actual behavior** — O(N_active_manual) memory and ≥200 ms wall time on large DBs. No NFR budget violated (NFR3 is about the real sweep), but the dry-run preview is implicitly assumed cheap.
- **Expected behavior** — Add a `paid_until_lt` filter to `list_api_keys` (mirror of the existing `paid_until_lte`) so the SQL filter does the heavy lifting. Low priority for current scale.
- **Severity** — Nit

- **Title** — `render_suspend_sweep_preview` has no NULL-guard other than `assert row.paid_until is not None` — fails under `-O`
- **Location** — `src/comadre/keys/cli/output.py:385`
- **Trigger** — Python running with `-O` or `PYTHONOPTIMIZE=1` (`assert` statements are stripped). The dry-run filter guarantees non-NULL `paid_until` via `if row.paid_until is None: continue`, but if a future refactor bypasses the CLI filter and calls the renderer directly with a NULL row, the `assert` is a tripwire that doesn't fire in optimized builds.
- **Actual behavior** — `_iso_date(None)` returns the em-dash; `table.add_row` renders `—` in the Paid Until column. Not a crash, but an operator signal is lost.
- **Expected behavior** — Replace the `assert` with a real guard (raise `ValueError` or skip the row with a `continue`). Or drop the assert entirely since `_iso_date` already handles NULL gracefully.
- **Severity** — Nit

- **Title** — Ansible `billing_timezone` variable has no validation — a typo produces silent drift from `BILLING_TIMEZONE`
- **Location** — `deploy/ansible/playbooks/bootstrap.yml:308-312`, `deploy/ansible/inventory/production.yml.example:45`, `deploy/ansible/inventory/oracle.yml.example:40`
- **Trigger** — Operator edits inventory to `billing_timezone: "America/Sao-Paulo"` (hyphen instead of underscore) by typo. `cron` parses `CRON_TZ=America/Sao-Paulo`, falls back to UTC silently (or preserves UTC depending on glibc version). The app's `BILLING_TIMEZONE` is still `America/Sao_Paulo` from `.env`. Drift.
- **Actual behavior** — The cron fires at `00:30 UTC`, but `resolve_today_in_tz` computes `today` in São Paulo (UTC-3). On Jan-01 boundary the sweep sees the wrong day's data; CLAUDE.md's gotcha warning applies but there's no playbook-level assertion.
- **Expected behavior** — Add an Ansible `assert` task validating `billing_timezone` against a known-good set (or even just `is defined`). The `bootstrap.yml` default-expression `billing_timezone | default('America/Sao_Paulo')` masks an unset variable but not a typo'd one.
- **Severity** — Low

- **Title** — Bootstrap cron task ordering — `CRON_TZ` envvar is set AFTER two preceding cron entries (daily-restart + audio-cleanup) that ignore it
- **Location** — `deploy/ansible/playbooks/bootstrap.yml:289-322`
- **Trigger** — Fresh install OR idempotent re-run.
- **Actual behavior** — `ansible.builtin.cron` with `env: true` inserts the `CRON_TZ` line at the top of the crontab **regardless of where it appears in the playbook** (this is how the module works), so the ordering is harmless in practice. BUT: the previous two cron entries (`comadre-daily-restart` at `restart_hour: 3` — presumably VPS-local time — and `comadre-audio-cleanup` every 6 h) are now ALSO re-interpreted under `CRON_TZ=America/Sao_Paulo`. If the VPS runs in UTC and `restart_hour: 3` was meant to be UTC-3 (overnight São Paulo), the change silently shifts those schedules by 3 h.
- **Expected behavior** — Either scope `CRON_TZ` narrowly (set-then-unset around the suspension-sweep line — not supported by `ansible.builtin.cron`'s env mode), or document that ALL comadre cron entries must be operator-TZ-aware going forward. The current implicit coupling is a latent footgun when a second cron job is added.
- **Severity** — Medium

- **Title** — `cleanup.yml` cron-removal order removes the suspension-sweep entry BEFORE removing `CRON_TZ`, but `CRON_TZ` affects all cron jobs
- **Location** — `deploy/ansible/playbooks/cleanup.yml:66-75`
- **Trigger** — Partial cleanup failure between the two tasks.
- **Actual behavior** — If cleanup.yml aborts between the suspension-sweep removal and the `CRON_TZ` removal, the crontab has a lingering `CRON_TZ` line with no corresponding suspension-sweep entry. On next `bootstrap.yml` run, the idempotent `cron` module adds the suspension-sweep line without touching `CRON_TZ` — fine. But a human running `crontab -l` between the two tasks sees a confused state. Not a bug, a UX wart.
- **Expected behavior** — Swap the order: remove `CRON_TZ` first, then the suspension-sweep (so the crontab is always in a consistent state during cleanup). Or run both in a single `block:`.
- **Severity** — Nit

- **Title** — DST transition fires the sweep at wall-clock `23:30` or `00:30` depending on direction — documented but not tested
- **Location** — `deploy/ansible/playbooks/bootstrap.yml:314-322`, docs at `_bmad-output/implementation-artifacts/3-3-automated-suspension-sweep-cron.md:751-753`
- **Trigger** — Operator deploys in a DST-observing TZ (e.g. `Europe/Berlin`). Spring-forward: `00:30` skipped; sweep doesn't fire that day. Fall-back: `00:30` hit twice; cron fires twice — sweep runs twice (idempotent per AC17, but `get_last_sweep_timestamp` jumps "forward" on the second fire within the same second-resolution window).
- **Actual behavior** — Correct by design (sweep is idempotent). But the story spec says "Brazil abolished DST in 2019", which is only partially true for the operator-hot-path — an operator choosing a `billing_timezone` outside Brazil gets no warning.
- **Expected behavior** — Either add an Ansible `debug` noting DST caveats when `billing_timezone` is not in a known-DST-free list, or note in `configuration-reference.md` that the DST-observant path is un-validated. Currently only the implementation notes in the story file carry this caveat.
- **Severity** — Low

- **Title** — `test_touches_sentinel_on_success` uses `time.sleep(0.05)` — flaky on CI with coarse mtime resolution
- **Location** — `tests/test_keys_db_suspend_sweep.py:477-480`
- **Trigger** — CI runner with FAT32 / ext3-without-dir-index / NFS-relatime filesystem where mtime granularity is 1 s. `time.sleep(0.05)` is sub-second, so `baseline_mtime == post_sweep_mtime` is possible.
- **Actual behavior** — Test flakes `assert sentinel.stat().st_mtime > baseline_mtime`.
- **Expected behavior** — Either `time.sleep(1.01)` to clear 1 s granularity, or use the os.utime baseline-override trick: `os.utime(sentinel, times=(0, 0))` then assert mtime > 0. Current 50 ms sleep is vulnerable.
- **Severity** — Low

- **Title** — `test_db_error_exits_5` accepts ANY non-zero exit code — doesn't actually verify exit-5 mapping
- **Location** — `tests/test_keys_cli_suspend_sweep.py:400-408`
- **Trigger** — Test design: "`assert result.exit_code != 0`" passes for exits 1, 2, 5, 6, or Typer's own exits. A regression that maps DB error to exit-2 (usage error) would still pass this test.
- **Actual behavior** — The test's own comment acknowledges this: "Accept either as 'the command refused to proceed on a broken path'". The actual exit-5 contract from the module docstring is not asserted.
- **Expected behavior** — Stronger assertion: `assert result.exit_code == 5` (or skip the test entirely — leaving it as an un-specific smoke creates a false sense of exit-code-contract coverage).
- **Severity** — Low

- **Title** — Tests freeze `resolve_today_in_tz` in `system_cmd` module only — a dry-run path that imports `resolve_today_in_tz` from another module would miss the patch
- **Location** — `tests/test_keys_cli_suspend_sweep.py:67-68`
- **Trigger** — Future refactor moves dry-run into a helper that re-imports `resolve_today_in_tz` from `comadre.keys.cli._clock` directly. The test's `monkeypatch.setattr(system_cmd, "resolve_today_in_tz", ...)` patches only the binding in `system_cmd`, so the helper sees the real-world "today" and the test starts flaking on the day of execution.
- **Actual behavior** — Current code imports `resolve_today_in_tz` into `system_cmd`'s namespace, so the patch works today. Fragile against refactors.
- **Expected behavior** — Patch the source-of-truth: `monkeypatch.setattr("comadre.keys.cli._clock.resolve_today_in_tz", ...)` — the story's own Test-flake-avoidance section calls this out ("Do NOT monkeypatch `date.today` globally"). Current CLI tests don't follow the story's own guidance.
- **Severity** — Low

- **Title** — `TestIdempotence.test_idempotent_second_run_suspends_nothing` hard-codes `== 3` but uses `_seed_expired_portfolio` which seeds 3 expired — coupling test to fixture arithmetic
- **Location** — `tests/test_keys_cli_suspend_sweep.py:443-461`
- **Trigger** — Future edit to `_seed_expired_portfolio` adding a fourth expired key. The assertion `_count_audit(env["db_path"], action="suspend_key") == 3` silently breaks with no indication the coupling was intentional.
- **Actual behavior** — Coupled-via-magic-number.
- **Expected behavior** — Derive from `len(ids) - len({paid1, paid2})` or inline the seed into the test. Minor hygiene.
- **Severity** — Nit

- **Title** — `TestCycle.test_manual_rerun_after_mark_paid_reactivates_and_resweeps` asserts audit order via `ORDER BY id ASC` — assumes AUTOINCREMENT monotone
- **Location** — `tests/test_keys_cli_suspend_sweep.py:502-515`
- **Trigger** — SQLite's `rowid` is monotone within a single connection but can be reassigned after VACUUM. Test uses a single `tmp_path` DB and three separate `CliRunner` invocations — each opens a fresh connection via `get_connection`. `rowid` monotonicity is preserved across connections on the same DB provided no VACUUM happens, which is true here.
- **Actual behavior** — Works today.
- **Expected behavior** — Safer to `ORDER BY occurred_at ASC, id ASC` — but since `_utcnow_iso()` has second-resolution, three sub-second-spaced invocations on the same second would tie, pushing the tie-break back to `id`. Defensible as-is; noted for future hardening.
- **Severity** — Nit

- **Title** — `get_last_sweep_timestamp` uses `conn.row_factory` via name-based access but test does NOT set `row_factory` on the fresh DB
- **Location** — `src/comadre/keys/db.py:1483-1487`, `tests/test_keys_db_suspend_sweep.py:570-577`
- **Trigger** — `row["last_at"]` requires `conn.row_factory = sqlite3.Row`. `get_connection` sets this at line 269, so all test paths going through `get_connection` are safe. But a direct `sqlite3.connect(path)` (as `_fetch_summary_row` uses at `tests/test_keys_cli_suspend_sweep.py:202-209`) does NOT set the row factory — the test then overrides it manually. Any consumer who forgets to set `row_factory` gets a `TypeError: tuple indices must be integers or slices, not str`.
- **Actual behavior** — Tests pass because they go through `get_connection`. External consumers may trip.
- **Expected behavior** — Either defensively set `row_factory` inside `get_last_sweep_timestamp` or document the precondition. Currently implicit.
- **Severity** — Nit

- **Title** — `audit_log.action='cron_suspend'` + `target_type='system'` is enforced nowhere in the schema — any future typo permanently stalls `get_last_sweep_timestamp`
- **Location** — `src/comadre/keys/migrations/v001_initial.sql`, `src/comadre/keys/db.py:1450-1458`
- **Trigger** — A refactor that typos `action="cron-suspend"` (dash) or `target_type="System"` (case). `get_last_sweep_timestamp` returns None forever after; `health` (Story 3.4) reports "sweep has never run". No DB constraint catches it.
- **Actual behavior** — Silent drift until the health report is inspected.
- **Expected behavior** — Either CHECK constraints on `audit_log.action` (enum of valid action names) or a test that asserts the exact string pair matches the helper's SELECT predicate. Neither exists; the current tests exercise the current pair but would pass after a double-renaming refactor.
- **Severity** — Low

- **Title** — No test verifies SQLite version ≥ 3.35 at runtime — RETURNING fails with opaque syntax error on 3.34 or earlier
- **Location** — `src/comadre/keys/db.py:1418` (docstring claim) vs. lack of runtime check
- **Trigger** — Container built on an ancient Alpine base with SQLite 3.33 (hypothetical — Python 3.12 ships 3.41+ as stated, but a dev hacks around pyenv/system-sqlite hybrid).
- **Actual behavior** — First sweep invocation raises `sqlite3.OperationalError: near "RETURNING": syntax error` — mapped to exit-5 by the CLI layer, but the error message doesn't point at the root cause (SQLite version).
- **Expected behavior** — Startup check in `get_connection`: `conn.execute("SELECT sqlite_version()").fetchone()` → parse-and-assert ≥ 3.35. Or explicit hint in the exit-5 error panel mentioning SQLite version. Currently silent.
- **Severity** — Nit

- **Title** — `_PII_FORBIDDEN_RE` at `tests/test_keys_cli_suspend_sweep.py:22` allows e.g. `@sao_paulo.br` through — regex false-negatives are not covered
- **Location** — `tests/test_keys_cli_suspend_sweep.py:22`
- **Trigger** — A customer email like `foo@example.com` is correctly caught; `foo@example.br` (matching TLD length ≥ 2) is caught; but the log line `cutoff=2026-04-06` does not match. The regex is operationally sufficient for the current sweep log shape (no `@` substrings emitted), but the test claims PII-austerity broadly.
- **Actual behavior** — Works for the current INFO log. Fragile against future log-line additions that quote customer data.
- **Expected behavior** — Consider an allow-list ("log must match this exact format") instead of a deny-list. Low priority; matches Story 3.1's pattern.
- **Severity** — Nit
