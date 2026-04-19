- **`test_db_error_exits_5` does not assert exit code 5**
  - **AC / constraint violated** — AC14 (error-hint safety) / §7 exit-code contract (the "5" row for `sqlite3.Error`) / Task 7.1 test-name promise
  - **Evidence** — `tests/test_keys_cli_suspend_sweep.py:381` asserts `assert result.exit_code != 0` with a comment acknowledging "non-sqlite errors propagate through Click as non-zero exit codes but not 5. Accept either…". The test name and spec both mandate exit 5 for `sqlite3.Error` from `get_connection` / `_apply_migrations` / `run_suspension_sweep`. The code-under-test (`system.py:213-215`, `217-220`, `234-236`) does raise `typer.Exit(code=5)` correctly, but the test is weakened to `!= 0`, so the exit-5 mapping is not exercised end-to-end. A regression that replaces `raise typer.Exit(code=5)` with an unrelated non-zero exit (e.g., an uncaught exception's exit 1) would pass this test silently.
  - **Severity** — Medium
  - **Note** — AC covered by code but not covered by the test. Fix would be a DB path that reliably triggers `sqlite3.Error` (e.g., monkeypatch `get_connection` to raise `sqlite3.OperationalError`) and assert `result.exit_code == 5`.

- **NFR3 performance test does not assert the 1 000 per-key + 1 summary audit rows**
  - **AC / constraint violated** — AC9 (`And 1 000 per-key audit rows + 1 summary row are committed`)
  - **Evidence** — `tests/test_keys_db_suspend_sweep.py:520-560` — `test_performance_budget_nfr3` asserts `swept_count == 1000` and `elapsed_ms < 1000.0`, but never queries `audit_log` to verify the 1 001 rows were written. The other AC2/AC3 tests cover the N-to-audit-row invariant for small N, so the behavior is covered in aggregate; however, an NFR3-sized regression in audit-row emission (e.g., a silently-skipped log_event under high volume) wouldn't trip this test.
  - **Severity** — Low
  - **Note** — AC behavior is covered transitively via `test_writes_per_key_suspend_key_audit_rows` (small N); a pure NFR3-scale guard would assert audit row counts alongside the wall-clock check.

- **`EXPLAIN QUERY PLAN` / `USING INDEX idx_api_key_sweep` assertion not implemented**
  - **AC / constraint violated** — AC9 (`EXPLAIN QUERY PLAN … shows USING INDEX idx_api_key_sweep (advisory; marked skippable…)`), §10 Tests bullet `test_uses_idx_api_key_sweep`
  - **Evidence** — `Grep` on `tests/` shows `idx_api_key_sweep` is referenced only in `tests/test_keys_db.py:181` (schema-existence test, not a plan assertion). No `EXPLAIN QUERY PLAN` check over the sweep `UPDATE` exists. `tests/test_keys_db_suspend_sweep.py` is the story-scoped test file; it has no plan-check case.
  - **Severity** — Low
  - **Note** — Spec explicitly allows skipping ("advisory; marked skippable") and lists this in Deferred work at line 785. Acknowledged deferral; flagging for visibility.

- **AC6 rollback test verifies sentinel absence rather than unchanged mtime**
  - **AC / constraint violated** — AC6 (`the sentinel mtime is unchanged`)
  - **Evidence** — `tests/test_keys_db_suspend_sweep.py:422-424, 458-459` — test deletes any pre-existing sentinel (`if sentinel.exists(): sentinel.unlink()`) and then asserts `not sentinel.exists()`. The spec's AC6 phrasing assumes a pre-existing sentinel (as the `_touch_auth_cache_sentinel` pattern leaves one after any successful mutation). Functionally equivalent — both mean "no touch happened" — but semantically drifts from the AC wording.
  - **Severity** — Nit
  - **Note** — AC's stricter form (pre-seed sentinel at mtime M, assert post-rollback mtime == M) would catch a subtle regression where the sentinel is touched unconditionally (not just on commit).

- **Dry-run footer wording drifts from §3 step 8 spec**
  - **AC / constraint violated** — §3 step 8 (`Dry-run: f"Dry-run — {preview_count} key(s) would be suspended at cutoff {today_iso}."`)
  - **Evidence** — `src/comadre/keys/cli/output.py:390-392` — renderer footer reads `"{len(rows)} key(s) would be suspended. Run without --dry-run to proceed."`. Lacks the leading `"Dry-run — "` framing and the `"cutoff {today_iso}"` suffix that §3 step 8 mandates. The §4 renderer spec (step 5 / Task 4.5) specifies the actually-implemented string, so the two spec sections contradict each other and the implementer chose §4.
  - **Severity** — Nit
  - **Note** — Spec-internal contradiction between §3 step 8 and §4 step 5 / Task 4.5. Code + tests (AC7 assertion in `test_dry_run_writes_nothing:268` + `test_shape:653` in `test_keys_output.py`) consistently follow §4. Spec-doc drift, not a code defect.

- **Dry-run Python-side sort includes `customer_name`; spec §3 step 4 names only `(paid_until ASC, key_prefix ASC)`**
  - **AC / constraint violated** — §3 step 4 (`Sort (paid_until ASC, key_prefix ASC) — deterministic by the same invariant Story 3.2's at-risk uses`)
  - **Evidence** — `src/comadre/keys/cli/commands/system.py:278` — `preview.sort(key=lambda r: (r.paid_until or "", r.customer_name, r.key_prefix))`. This matches Story 3.2's actual `billing.py:824` `at-risk` sort, so the spec's claim "same invariant Story 3.2's at-risk uses" is honored in substance; the spec's parenthetical gloss `(paid_until ASC, key_prefix ASC)` was imprecise.
  - **Severity** — Nit
  - **Note** — Code follows the 3.2 precedent correctly; spec gloss was wrong. Output remains deterministic.

- **Task 5.1 lists production.yml + oracle.yml as modified, diff only shows `.example` files**
  - **AC / constraint violated** — Task 5.1 checklist item (`[x] 5.1 Add billing_timezone: "America/Sao_Paulo" to deploy/ansible/inventory/production.yml + .example + oracle.yml + .example`)
  - **Evidence** — `git diff` in the patch modifies only `deploy/ansible/inventory/production.yml.example` and `oracle.yml.example`. On inspection, `deploy/ansible/inventory/production.yml` (line 46) and `oracle.yml` (line 36) also contain `billing_timezone: "America/Sao_Paulo"` — these files are operator-local and not committed, so the changes exist on the local working tree even though they are absent from the diff. The "File List" in the story claims all four files are modified.
  - **Severity** — Nit
  - **Note** — No functional issue; `.yml` inventory files are local-operator artifacts (the `.example` files are the canonical template). Flagging only because a reviewer reading the diff alone would not see the real inventories' updates.

- **Task 5.5 and Task 10.6 deferred — deferrals acknowledged by spec**
  - **AC / constraint violated** — none (deferrals are explicit)
  - **Evidence** — Spec line 661 (`[ ] 5.5 ansible-playbook --check smoke pass (manual — deferred to 10.10.10.207 acceptance gate; see Completion Notes)`) and line 691 (`[ ] 10.6 Manual smoke on 10.10.10.207 — deferred to deploy-time acceptance gate`). Completion Notes line 909 reiterates both deferrals.
  - **Severity** — Nit (audit-only — confirming the deferrals are documented, not masquerading as done)
  - **Note** — No other `[x]`-marked task was found to be actually incomplete. Tasks 1-4, 6-9, and 10.1-10.5 verified to match the implementation.

- **Grep-check §11 for `action='suspend_key'` is technically zero-hit against source**
  - **AC / constraint violated** — §11 first grep check (`rg -n "action='suspend_key'" src/comadre/keys/db.py — exactly 2 hits`)
  - **Evidence** — Python source uses double-quoted strings (`action="suspend_key"` at `db.py:1312` and `db.py:1444`); only the docstring at `db.py:1276` contains the literal single-quoted form. The single-quoted literal grep from §11 returns 1 hit (the docstring), not 2. The spec's underlying intent (exactly two *write-site* occurrences of the action) is satisfied — there are exactly two `action="suspend_key"` lines in code.
  - **Severity** — Nit
  - **Note** — Grep command as written in §11 is wrong for this codebase's quote convention; the semantic invariant (2 write sites) holds. The Completion Notes list 908 correctly reports "2 hits in db.py" after normalizing the quote style.

- **All remaining ACs (AC1-AC5, AC7-AC8, AC10-AC19) verified in code and tests**
  - **AC / constraint** — n/a (summary)
  - **Evidence** — 
    - AC1: `run_suspension_sweep` predicate `billing_mode='manual' AND status='active' AND paid_until IS NOT NULL AND paid_until < ?` at `db.py:1427-1434`; covered by `test_sweeps_expired_active_manual_keys`, `test_never_sweeps_{complimentary,trial_window_null_paid_until,suspended,revoked}` and CLI `test_full_sweep_happy_path`.
    - AC2: per-row `action="suspend_key"` write at `db.py:1439-1447`; `details={"paid_until": …, "cutoff_date": …}`; covered by `test_writes_per_key_suspend_key_audit_rows`.
    - AC3: summary row with byte-identity `occurred_at == result.completed_at` at `db.py:1449-1458`; covered by `test_writes_summary_cron_suspend_audit_row` and CLI `test_confirmation_line_contains_canonical_timestamp`.
    - AC4: zero-row summary row path covered by `test_zero_row_sweep_still_writes_summary_row` and CLI `test_zero_row_sweep_exits_0`.
    - AC5: `_touch_auth_cache_sentinel(conn)` call after `with conn:` at `db.py:1460`; covered by `test_touches_sentinel_on_success`.
    - AC7: `_suspend_sweep_dry_run` at `system.py:258-295` does zero writes; covered by `test_dry_run_writes_nothing` with pre/post audit-count comparison.
    - AC8: empty-preview `render_empty_state` path at `system.py:291-293`; covered by `test_dry_run_empty_preview_message`.
    - AC10: no `BEGIN IMMEDIATE` / `BEGIN EXCLUSIVE` in the helper — `grep BEGIN` returns zero matches in `db.py`; WAL invariant preserved by construction.
    - AC11: `CRON_TZ` envvar + `30 0 * * *` cron entry in `bootstrap.yml:308-322`; symmetric removal in `cleanup.yml:66-76`; `billing_timezone` interpolation at both `value:` and the "Next steps" summary.
    - AC12: `git diff HEAD -- src/comadre/rate_limit.py src/comadre/api.py src/comadre/keys/auth.py src/comadre/keys/cache.py src/comadre/main.py pyproject.toml uv.lock src/comadre/keys/migrations/` returns empty output.
    - AC13: INFO log format at `system.py:243-249` uses `cutoff=%s | swept_count=%d | completed_at=%s | dry_run=False`; no `key_id` / `key_prefix` / name / email fields; `test_pii_austere_log` asserts `_PII_FORBIDDEN_RE` finds zero matches and that "Pedro Lopes"/"Marcos Silva"/"Helena Ribeiro" are absent.
    - AC14: `render_error` routes via the canonical panel; `load_settings_and_tz` is shared with Story 1.6 / 3.1 and already audited for hint safety.
    - AC15: hardcoded `actor="cron:suspension-sweep"` at `system.py:232`; `test_actor_hardcoded_cron_suspension_sweep` queries `audit_log` and asserts every row has this actor.
    - AC16: `get_last_sweep_timestamp` compound predicate `action='cron_suspend' AND target_type='system'` at `db.py:1481-1486`; covered by three tests (`test_returns_none_on_fresh_db`, `test_returns_most_recent_summary_row`, `test_ignores_per_key_suspend_key_rows`).
    - AC17: idempotence covered by `TestIdempotence.test_second_run_suspends_nothing` (db) + `TestIdempotence.test_idempotent_second_run_suspends_nothing` (CLI — asserts 2 summary rows, 3 per-key rows).
    - AC18: end-to-end cycle covered by `TestCycle.test_manual_rerun_after_mark_paid_reactivates_and_resweeps`, asserting `actions == ["suspend_key", "mark_paid", "suspend_key"]` with correct actor progression.
    - AC19: `test_suspend_sweep_appears_in_top_level_help` via `CliRunner().invoke(app, ["--help"])`; verifies top-level surfacing.
  - **Severity** — n/a
