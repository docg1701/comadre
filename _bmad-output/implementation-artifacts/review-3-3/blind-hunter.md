- **Title** — Cron job swallows non-zero exit code, operator alerting is blind
- **Location** — deploy/ansible/playbooks/bootstrap.yml:99-105
- **Issue** — The cron job pipes `docker compose exec ... comadre-keys suspend-sweep 2>&1 | logger`. The exit code of a pipeline in the default (non-`pipefail`) shell cron runs under is the exit status of the last command (`logger`), which is always 0. Exit codes 5/6 documented in `system.py` are therefore lost — a misconfigured BILLING_TIMEZONE or a DB error fires every night and cron never notices or MAILs. Operator monitoring that watches cron exit statuses sees green forever.
- **Evidence** —
  ```
  job: >-
    cd ~/comadre &&
    docker compose exec -T tts-service comadre-keys suspend-sweep 2>&1 |
    logger -t comadre-suspension-sweep
  ```
- **Severity** — High

- **Title** — `cd ~/comadre` relies on the cron user's HOME resolving to the project — silent skip if not
- **Location** — deploy/ansible/playbooks/bootstrap.yml:103
- **Issue** — The job starts with `cd ~/comadre && docker compose ...`. If the cron user's HOME is unexpected (e.g., the playbook runs system-level crontab vs per-user), the `cd` fails and the `&&` short-circuits — nothing runs, `logger` emits nothing, and again the exit is 0. There is no absolute path, no `become_user` visible in the hunk, and the `name: CRON_TZ` env cron task has no `user:` set either, so these probably land in root's crontab while `comadre` lives elsewhere. Worth confirming explicitly; as written this is fragile.
- **Evidence** — `cd ~/comadre && docker compose exec -T tts-service comadre-keys suspend-sweep 2>&1 | logger ...`
- **Severity** — High

- **Title** — `run_suspension_sweep` calls `_touch_auth_cache_sentinel` outside the transaction — cache stays stale on replica failure
- **Location** — src/comadre/keys/db.py:580 (after the `with conn:` block)
- **Issue** — The sentinel touch happens *after* `with conn:` commits. If the process is killed between `COMMIT` and `_touch_auth_cache_sentinel(conn)` (SIGKILL, OOM, container restart), the DB is updated but replicas that watch the sentinel never invalidate their auth cache. Suspended keys continue to authenticate for the auth-cache TTL. A more robust pattern would touch the sentinel inside the transaction or wrap it in a finally that runs regardless of whether we reached return. At minimum the sentinel touch needs exception handling — if it raises (disk full, permission flip), the function currently propagates that error to the caller even though the DB already committed.
- **Evidence** —
  ```
      with conn:
          cursor = conn.execute(...)
          ...
          log_event(conn, ... action="cron_suspend", ... occurred_at=completed_at)

      _touch_auth_cache_sentinel(conn)
  ```
- **Severity** — Medium

- **Title** — `completed_at` sampled before the UPDATE — clock skew between ISO timestamp and the transaction commit
- **Location** — src/comadre/keys/db.py:543-578
- **Issue** — `completed_at = _utcnow_iso()` is computed *before* the `with conn:` block starts. If the UPDATE + per-key audit writes take seconds (e.g., 1000 rows, slow disk), the "completed_at" in the summary row and returned struct is actually a *started_at* timestamp — off by however long the transaction took. The docstring claims it is "the canonical ISO-UTC timestamp the sweep wrote on its summary audit row" but semantically it's the pre-transaction clock. Sampling after the `with conn:` block (post-commit) would match the name.
- **Evidence** —
  ```
  today_iso = today.isoformat()
  completed_at = _utcnow_iso()

  with conn:
      cursor = conn.execute(...)
  ```
- **Severity** — Low

- **Title** — `today` parameter is trusted as a naïve `date` — caller TZ assumption is unenforceable
- **Location** — src/comadre/keys/db.py:510-512
- **Issue** — `run_suspension_sweep(conn, *, today: date, ...)` accepts any `date`. The docstring says strict `<` semantics match FR18 relative to "operator TZ", but a future caller could pass `datetime.utcnow().date()` (UTC midnight) instead of the São Paulo-local date and the function silently accepts it — sweeping a 3-hour-early "today" between 21:00 and 00:00 local. There's no assertion, no typing wrapper. The CLI currently guards this via `resolve_today_in_tz`; a second caller (Story 3.4 health? a manual script?) has no compile-time check.
- **Evidence** — `def run_suspension_sweep(conn, *, today: date, actor: str = "cron:suspension-sweep")`
- **Severity** — Low

- **Title** — `_suspend_sweep_dry_run` silently drops rows with malformed `paid_until`; real sweep's SQL does not
- **Location** — src/comadre/keys/cli/commands/system.py:381-389 vs src/comadre/keys/db.py:547-553
- **Issue** — Dry-run does:
  ```
  try:
      paid_date = date.fromisoformat(row.paid_until)
  except ValueError:
      continue
  ```
  i.e., skips garbage dates. The real sweep compares them at the SQL level with `paid_until < ?` — SQLite string comparison on `'not-a-date' < '2026-04-06'` yields `False` (all letters > digits), so garbage dates survive the real sweep too. OK in this case, but a `paid_until` like `"2026-4-6"` (no zero-padding) would lexicographically compare `< '2026-04-06'` → swept by real run, skipped by dry-run (parsed OK → `date(2026,4,6) < date(2026,4,6)` is False → skipped for a different reason, consistent). However `"1999-12-31abc"` raises `ValueError` in `date.fromisoformat` yet lexicographically `< today_iso` — real sweep flips it, dry-run hides it. Preview ≠ reality on malformed data.
- **Evidence** — See the try/except above; SQL in db.py:552 uses `paid_until < ?` without validation.
- **Severity** — Low

- **Title** — No explicit `ORDER BY` on `UPDATE ... RETURNING` — ordering/reproducibility
- **Location** — src/comadre/keys/db.py:546-555
- **Issue** — The `UPDATE ... RETURNING` has no `ORDER BY`; `swept_key_ids` order is an implementation detail of SQLite's query planner / the partial index. Tests compare via `set(...)`, so current tests pass. Any future caller that relies on ordering (e.g., for a deterministic replay log, or when this gets concatenated into a mail notification) will see flaky ordering between SQLite versions. Cosmetic now; fragile later.
- **Evidence** — The SQL statement quoted in db.py:547-553.
- **Severity** — Nit

- **Title** — `raise typer.Exit(code=5) from None` masks original exception in structured logging
- **Location** — src/comadre/keys/cli/commands/system.py:329-330, 336-337, 348-349
- **Issue** — `from None` suppresses the `__cause__` chain. If this is invoked by cron and the stderr lands in `logger`, the operator sees only `"Database error: <str(exc)>"` and loses the original traceback and exception type. For Story 3.3's stated "write one audit row per key plus a summary row for liveness tracking" safety guarantees, this is the one place operators will want forensics. Consider `raise typer.Exit(code=5)` without `from None`, or log the full exception first.
- **Evidence** —
  ```
  except sqlite3.Error as exc:
      render_error("Database error", str(exc))
      raise typer.Exit(code=5) from None
  ```
- **Severity** — Low

- **Title** — `cast(Settings, settings_obj)` is a typing escape hatch hiding untested helper behavior
- **Location** — src/comadre/keys/cli/commands/system.py:316-317
- **Issue** — `load_settings_and_tz()` return shape isn't visible in this diff (imported from `commands.keys`). Using `cast` without a runtime check means if that helper changes its tuple ordering / types, mypy stays silent and the `settings.key_registry_db_path` access on line 327 blows up at runtime. A simple `isinstance(settings_obj, Settings)` assert would catch regressions.
- **Evidence** — `settings_obj, billing_tz = loaded; settings = cast(Settings, settings_obj)`
- **Severity** — Nit

- **Title** — Dry-run preview rendered via sort on `(paid_until or "", customer_name, key_prefix)` — `None` never reached but empty-string tiebreak is surprising
- **Location** — src/comadre/keys/cli/commands/system.py:391
- **Issue** — The loop above already `continue`s on `row.paid_until is None`, so `paid_until or ""` can never hit the `or ""` branch — dead code that signals "maybe None slips through". Minor, but tells reviewers the invariant is fuzzy.
- **Evidence** — `preview.sort(key=lambda r: (r.paid_until or "", r.customer_name, r.key_prefix))`
- **Severity** — Nit

- **Title** — `render_suspend_sweep_preview` uses `assert row.paid_until is not None` — stripped under `python -O`
- **Location** — src/comadre/keys/cli/output.py:453
- **Issue** — `_iso_date(row.paid_until)` is called right after `assert`. Under `python -O` (PyInstaller bundles, some Docker images set PYTHONOPTIMIZE=1), the assertion is stripped and a `None` can flow into `_iso_date`, whose behavior isn't visible in the diff — it may raise or format as the string "None". Use a real check or rely on the type system.
- **Evidence** —
  ```
  for row in rows:
      assert row.paid_until is not None
      table.add_row(..., _iso_date(row.paid_until))
  ```
- **Severity** — Low

- **Title** — `with contextlib.suppress(Exception)` around INFO log swallows all logging errors including KeyboardInterrupt-adjacent bugs
- **Location** — src/comadre/keys/cli/commands/system.py:355-362 and 395-402
- **Issue** — Catching bare `Exception` around `_logger.info(...)` means any misconfigured logger, any serializer bug, any missing handler traceback is hidden. Cron consumers rely on this INFO line for dashboarding — silently losing it means "ran successfully but dashboard shows stale" becomes indistinguishable from "didn't run". Narrower suppression (or no suppression — `logger.info` should not raise in practice) is more defensive.
- **Evidence** —
  ```
  with contextlib.suppress(Exception):
      _logger.info("Suspension sweep completed | ...", ...)
  ```
- **Severity** — Low

- **Title** — `rollback` test actually demonstrates a broader rollback than documented
- **Location** — tests/test_keys_db_suspend_sweep.py:1638-1707 (`test_sweep_never_touches_sentinel_on_rollback`)
- **Issue** — The test asserts that on mid-sweep failure **the UPDATE also rolls back**. But `UPDATE api_key SET status='suspended' ... RETURNING ...` issued inside `with conn:` should indeed be rolled back by the context manager on exception. The test's comment even says "transaction rolled back" — good. However the same test also asserts `not sentinel.exists()`. The code's flow shows the sentinel touch is *after* the `with conn:` block — if the `with conn:` block raises, the sentinel touch is never reached, so the assertion passes for the wrong reason. If a future author moves `_touch_auth_cache_sentinel(conn)` inside the `with conn:` block (which would actually be safer per my finding above), the sentinel would be touched and then cleaned up on rollback — but `_touch_auth_cache_sentinel` is a file op, rollback does NOT undo that. The test gives a false sense of safety around that refactor.
- **Evidence** — `assert not sentinel.exists()` at the end of the rollback test, combined with sentinel being outside the `with conn:` block.
- **Severity** — Low

- **Title** — Test `test_db_error_exits_5` asserts only `exit_code != 0` — doesn't actually pin exit 5
- **Location** — tests/test_keys_cli_suspend_sweep.py:1047-1065
- **Issue** — The test name, the docstring, and the exit-code contract in `system.py` all promise exit code **5** for DB errors. The assertion reads `assert result.exit_code != 0`. The author's own comment admits "non-sqlite errors propagate through Click as non-zero exit codes but not 5. Accept either…". This means the contract is untested — a regression that makes DB errors exit 1 or exit 255 passes this test. Either the contract should be honored (and the path engineered to actually raise `sqlite3.Error`) or the test should be split.
- **Evidence** —
  ```
  # Accept either as "the command refused to proceed on a broken path"
  assert result.exit_code != 0
  ```
- **Severity** — Medium

- **Title** — `_fetch_summary_row` ordering by `id DESC LIMIT 1` not by `occurred_at` — idempotence test fragile
- **Location** — tests/test_keys_cli_suspend_sweep.py:907-912
- **Issue** — `SELECT ... WHERE action='cron_suspend' ... ORDER BY id DESC LIMIT 1` assumes autoincrement id correlates with insertion order. True for SQLite INTEGER PRIMARY KEY, but if the schema (not in diff) uses a UUID text id or rowid reassignment, this breaks silently. `ORDER BY occurred_at DESC` would be more intent-matching.
- **Evidence** —
  ```
  "FROM audit_log WHERE action = 'cron_suspend' "
  "AND target_type = 'system' ORDER BY id DESC LIMIT 1"
  ```
- **Severity** — Nit

- **Title** — PII regex is narrow — won't catch CPF in `###.###.###-##` formatted form or email in uppercase after casefolding changes
- **Location** — tests/test_keys_cli_suspend_sweep.py:720-723
- **Issue** — `[0-9]{11,14}` requires 11+ contiguous digits. A CPF rendered in Brazilian canonical form `123.456.789-10` contains dots/dashes — does NOT match. A regression that logs formatted CPFs sails through this test. The emails regex requires `@` followed by lowercase — `@Example.COM` fails on the character class. Since the regex uses `re.IGNORECASE`, the TLD char class `[a-z]` actually does match uppercase, so that piece is OK; but the dot-separated CPF blind spot remains.
- **Evidence** — `r"cmdr_live_|[0-9a-f]{64}|[0-9]{11,14}|@[a-z0-9.-]+\.[a-z]{2,}"`
- **Severity** — Low

- **Title** — Dry-run writes no audit row, leaves "last sweep" timestamp stale
- **Location** — src/comadre/keys/cli/commands/system.py:339-341
- **Issue** — By design (documented). But FR43's health command (Story 3.4) will read "last sweep timestamp" from the audit log. An operator who ONLY runs `--dry-run` for weeks (e.g., because they're debugging) will see the health command complain the sweep hasn't run, while the system is actually healthy. Could be intentional, but worth flagging: dry-run should probably NOT affect liveness, but the semantics of "preview mode masking the liveness signal" are not explicit to operators.
- **Evidence** — Dry-run branch returns before `run_suspension_sweep` is ever invoked; no audit row written.
- **Severity** — Nit

- **Title** — Bootstrap cron task missing `user:` — presumed to land in `root`'s crontab
- **Location** — deploy/ansible/playbooks/bootstrap.yml:91-105
- **Issue** — Both new `ansible.builtin.cron` tasks omit the `user:` parameter. Default is the `become` user (likely root if the play uses `become: true`). The documented command is `docker compose exec -T tts-service ...` — if the user running `docker` isn't in the `docker` group, this fails. And CRON_TZ env is set in the same (likely root) crontab — so *other* crons in the non-root user's crontab do not inherit the TZ, which is a silent trap if an operator later adds a billing job under their own user.
- **Evidence** —
  ```
  - name: "[Cron] Set CRON_TZ for billing-aware schedules"
    ansible.builtin.cron:
      name: "CRON_TZ"
      env: true
      value: "{{ billing_timezone | default('America/Sao_Paulo') }}"
  ```
  (no `user:`)
- **Severity** — Medium

- **Title** — Daily restart and suspension sweep timing — 3:00 restart may happen mid-sweep
- **Location** — deploy/ansible/playbooks/bootstrap.yml (cron config) + oracle.yml.example:39 & production.yml.example:44 (restart_hour: 3)
- **Issue** — Sweep runs 00:30. Restart runs 03:00 (`restart_hour: 3`). That's safe on a fast sweep. BUT the performance test asserts up to 1 s for 1K keys — real production with 100K rows and slow disk could run longer, and if someone bumps `restart_hour: 0`, the restart could interrupt the sweep mid-transaction. The `with conn:` guarantees atomicity, but the `_touch_auth_cache_sentinel` (or the next `log_event`) happens outside. More importantly, the cron job does `docker compose exec` — if the container is restarting, the exec fails and, per Finding #1 above, the failure is swallowed by the `| logger` pipeline.
- **Evidence** — oracle.yml.example:39 `restart_hour: 3`, bootstrap.yml:100 `hour: "0"` and `minute: "30"`.
- **Severity** — Nit

- **Title** — `get_last_sweep_timestamp` returns string from DB without validating ISO shape
- **Location** — src/comadre/keys/db.py:600-610
- **Issue** — The return is `cast(str, row["last_at"])`. If the audit table is corrupted or a manual INSERT writes a bogus `occurred_at`, callers (Story 3.4 `health`) get garbage and may emit it to operators as "last sweep: 2026/04/19 12pm" etc. A format check (compile-time regex match) or `date.fromisoformat` validation would be cheap insurance.
- **Evidence** — `return cast(str, row["last_at"])`
- **Severity** — Nit

- **Title** — Summary audit row `occurred_at` pinned via new `occurred_at=` kwarg — per-key rows NOT pinned
- **Location** — src/comadre/keys/db.py:560-578
- **Issue** — The per-key `log_event(...)` calls (line 561) do NOT pass `occurred_at`, so each per-key row samples `_utcnow_iso()` inside the helper. On a 1000-key sweep these timestamps span up to a second. That's fine semantically, but it means per-key rows have timestamps *slightly later than* the summary row's `occurred_at = completed_at` (which was sampled before the transaction started — see earlier finding). Ordering anomaly: the "summary" looks older than its own per-key detail rows. Any query ordering audit rows by `occurred_at` will interleave the summary *before* its detail rows. Unexpected for forensic workflows.
- **Evidence** — Compare lines 543 (`completed_at = _utcnow_iso()` pre-block) and 561-567 (per-key `log_event` with no `occurred_at` argument, so each resamples `_utcnow_iso()` mid-loop).
- **Severity** — Medium
