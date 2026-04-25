# Test Suite Review — 2026-04-25

**Goal (refined 2026-04-25 by Galvani):** drive Comadre's test suite from a 4.16× source-to-test ratio (bloated, llm-slop) down to a **0.5–0.7× ratio** (target: 3,500–5,000 test LOC). The ruler is **"se eu deletar isso, algum usuário sente?"** — anything that does not test real, important user-observable functionality is deleted "sem dó nem piedade".

**Trigger:** Galvani's review (2026-04-25): "suite bloated, mais de 50% inútil, testa os próprios testes / linhas de código / repete sem testar nada novo, dead code, manutenção é um terror, no final é uma merda inútil … é llm-slop maldito."

---

## 1. Baseline metrics

| Metric | Value |
|---|---|
| Source LOC (`src/comadre/`) | 7,106 |
| Test LOC (`tests/`, excl. fixtures) | 29,564 |
| Ratio | **4.16×** |
| Test files | 55 |
| Test functions | 1,360 |
| Tests passing | 1,420 (incl. parametrize cardinality) |

**Healthy reference points (Galvani's bar):**
- **0.5–0.7×** — what we want. Each test earns its keep by exercising user-observable behavior or guarding a real failure mode. Examples: `requests` library is ~0.7×; `click` is ~0.6×.
- 1.0–1.5× — test-light but acceptable for production Python services with discipline.
- 1.5–2.5× — slipping; usually means implementation-detail testing.
- 3×+ — bloated; copy-paste, parametrize-misuse, mock-call-asserts.
- 4×+ — llm-slop territory: every PR adds 5 tests, nothing consolidates. **This is where Comadre is.**

**Target:** 7,106 source LOC × 0.5 to 0.7 = **3,553 to 4,974 test LOC.** Current 29,564 LOC → cut **24,000–26,000 LOC (-81% to -88%).**

---

## 2. Verdicts by file (top 25 by LOC)

Each file gets one of three verdicts:

- **TRIM** — kill clearly redundant tests + collapse parametrize-misses. Estimated cut: 40–70%.
- **REVIEW** — needs case-by-case judgment; kill ratio uncertain. Sample first.
- **KEEP** — already lean or tests genuinely complex behavior.

| LOC | Tests | File | Verdict | Estimated cut |
|----:|------:|---|---|---:|
| 4537 | 174 | `test_keys_db.py` | TRIM | -65% (≈3000 LOC) |
| 1510 | 75 | `test_keys_output.py` | TRIM | -60% (≈900 LOC) |
| 1256 | 48 | `test_api.py` | REVIEW | -30% (≈400 LOC) |
| 1190 | 43 | `test_keys_cli_show.py` | TRIM | -40% (≈480 LOC) |
| 1084 | 75 | `test_service.py` | REVIEW | -25% (≈270 LOC) |
| 1040 | 46 | `test_keys_health.py` | TRIM | -50% (≈520 LOC) |
| 846 | 27 | `test_keys_cli_update_customer.py` | TRIM | -45% |
| 765 | 28 | `test_keys_cli_update_key.py` | TRIM | -45% |
| 761 | 21 | `test_keys_cli_issue.py` | REVIEW | -30% |
| 727 | 27 | `test_keys_cli_list_keys.py` | TRIM | -40% |
| 683 | 17 | `test_keys_auth.py` | KEEP | -10% (security-critical) |
| 674 | 17 | `test_keys_db_suspend_sweep.py` | REVIEW | -30% |
| 611 | 14 | `test_keys_cli_rotate_encryption_key.py` | TRIM | -50% (44 LOC/test is suspicious — probably overengineered scenarios) |
| 600 | 23 | `test_keys_cli_health.py` | TRIM | -45% |
| 595 | 22 | `test_keys_cli_revoke_key.py` | TRIM | -45% |
| 588 | 38 | `test_counters.py` | REVIEW | -30% |
| 584 | 14 | `test_keys_cli_rotate_key.py` | TRIM | -45% |
| 574 | 15 | `test_keys_cli_revenue.py` | TRIM | -45% |
| 541 | 44 | `test_keys_models.py` | TRIM | -65% (likely pydantic-validates-pydantic) |
| 528 | 13 | `test_keys_cli_suspend_sweep.py` | TRIM | -45% |
| 506 | 14 | `test_keys_cli_at_risk.py` | TRIM | -45% |
| 488 | 9 | `test_non_regression/test_request_body_limit.py` | KEEP (CI gate) | -10% |
| 485 | 15 | `test_keys_cli_export_customer.py` | TRIM | -40% |
| 484 | 14 | `test_keys_cli.py` | REVIEW | -30% |
| 480 | 15 | `test_keys_cli_mark_paid.py` | TRIM | -45% |

**Top-25 LOC: 21,996.** Estimated post-trim: **~12,500 LOC** (-43%).
**Plus the long tail (≈7,500 LOC across the remaining 30 files):** estimated -30% (~5,200 LOC).
**Projected total post-trim:** **~17,700 LOC of tests** → ratio **2.5× source** (acceptable; further trims after running the suite for a few epics).

---

## 3. Killing criteria (recalibrated for 0.5–0.7× target)

The new ruler: **"if I delete this test, does any real user feel a real bug?"** If the answer requires explanation, kill the test.

**KILL — categorical (no judgment needed):**

1. **Pydantic-validates-pydantic** — `test_field_required`, `test_invalid_email_rejected`, `test_min_length_enforced`. Pydantic's own suite covers this. Exception: a single happy+unhappy roundtrip for *custom* `field_validator` bodies (Fernet-shape, IANA-tz, NUL-rejection). All other validation tests die.
2. **Module-shape / import / constant tests** — `test_module_has_attribute`, `test_singleton_returns_same_instance`, `test_constant_value_is_Y`, `test_stdout_and_stderr_are_distinct`. Imports work or the program doesn't run; tests are noise.
3. **Mock-call asserts** — when the test body is `mock.assert_called_once_with(...)` and there is no output assertion, the test guards an implementation detail. Delete (do not refactor — the function is too internal to need a unit test).
4. **Trivial format / id-shape tests** — `test_format_prefix`, `test_lowercase_id`, `test_total_length`, `test_uniqueness`. 4 tests for a 3-line `f"cust_{ulid()}"` helper. One integration test that calls `create-customer` and asserts the resulting ID prefix is enough; everything else dies.
5. **Scanner self-tests** — `test_scan_flags_bad_example`, `test_scan_respects_allowlist_comment`, `test_scan_rejects_string_literal_allowlist_bypass`, `test_scan_flags_chained_mixed_ops`, etc. The scanner is part of production CI; one meta-test per scanner is enough (a single fixture with one violation + one allowlisted violation). The current 7-test cluster collapses to 1.
6. **SQL-filter combination tests** — `test_filter_by_status` + `test_filter_by_billing_mode` + `test_filter_by_customer` + `test_filter_by_paid_until_lte` + `test_filter_composition` for the same `list_api_keys()`. Pick *one* integration test of the CLI verb that uses the function (`comadre-keys list-keys --status active`) and trust SQLite + the test of the verb. Six unit tests die for one CLI test.
7. **Boundary-spam** — `IntRange(1, 1000)` does not need 4 tests. Click and pydantic test their own boundaries.
8. **Repetition across classes** — `test_treats_tombstone_as_missing` in 4 different `Test*` classes for 4 different read functions, all asserting `WHERE deleted_at IS NULL`. The CLI verb that reads tombstoned customers is covered by *one* CLI integration test; the SQL predicate is trusted.
9. **Render-variant tests** — `test_active_manual`, `test_active_complimentary`, `test_suspended`, `test_revoked`, `test_suspended_complimentary` for status-label formatting. The CLI verb that emits the labels is covered by one happy-path test of `comadre-keys list-customers`; the formatter's branch coverage is trusted.
10. **Error-class internals** — `test_status_code_is_401`, `test_error_type_is_authentication_error`, `test_hint_starts_with_provide`. The integration test that triggers the error and asserts the JSON body is enough.
11. **Logging assertions** — tests that assert a specific log line was emitted (`caplog.records[0].message == "..."`). Logs are operational telemetry, not contracts. Delete unless the log line is a security audit (Fernet rotation, key revocation) — then one integration test that asserts the audit row, not the log line.
12. **Tests that test the framework instead of the code** — `test_dependency_injection_works`, `test_lifespan_runs_phases_in_order`, `test_pytest_marker_registered`, `test_get_settings_is_lru_cached`. FastAPI/pytest tests its own; we don't.

**Reduction: parametrize is rarely the right tool at this aggression level — most of the cases above just delete entirely.** A 5-row parametrize is still 5 tests in the count, and the maintenance cost stays. Prefer a single integration test that exercises the code path naturally.

**KEEP — short list:**

- **One integration test per CLI verb.** `comadre-keys create-customer` happy-path + one error path. That's two tests, not 27.
- **One auth round-trip.** `issue-key → curl → 200`. One key-revoked path. One key-suspended path. Three tests, not the current 17 in `test_keys_auth.py`.
- **Encryption rotation atomicity.** Mid-loop Fernet rotation must not corrupt rows. This is the only test that justifies its complexity.
- **Suspension sweep.** One end-to-end: seed customer + key with paid_until=yesterday → run sweep cron → assert key flips to suspended. One test.
- **Rate limit.** One per-key bucket integration test.
- **Backup/restore.** One round-trip end-to-end.
- **CI non-regression scanners.** Keep — these ARE the value of the suite. But each scanner gets ONE self-test, not five.
- **Anything tied to a real bug** that has a commit-message reference.

---

## 4. Hard examples — what would die in `test_keys_db.py` at 0.5–0.7×

`test_keys_db.py` is **174 tests / 4,537 LOC**. The DB layer is consumed exclusively by CLI verbs and the FastAPI auth path. Both surfaces have their own integration tests. Therefore:

- **All unit tests of `list_*`, `get_*`, `insert_*`, `update_*`, `delete_*`, `is_first_run*`, `count_tombstones`, `resolve_show_target` die.** Their behavior is exercised by the CLI integration tests for the verbs that call them.
- **All format/id/uniqueness tests of `generate_customer_id` / `generate_key_id` die.** The integration test that calls `create-customer` and asserts a `cust_*` prefix is enough.
- **All PRAGMA tests die** — if WAL/FK aren't on, every other test fails on real SQL semantics.
- **What stays:** ONE migration test (fresh DB → all tables present + version 2). ONE rollback test (insert customer with audit failure → both rows absent). ONE concurrency test that exists for a real reason.

**Estimated reduction in `test_keys_db.py`: 174 → ~5 tests, 4,537 → ~200 LOC.**

The same ruler applied to `test_keys_output.py`: 75 tests → ~3 (one rendered-list table snapshot, one error-panel snapshot, one JSON-shape snapshot for machine consumers). 1,510 LOC → ~150 LOC.

The same applied to `test_keys_cli_*` cluster: each verb has 1 happy + 1 error = 2 tests. 12 files × 2 tests × ~30 LOC each = ~720 LOC for the entire CLI surface.

---

## 5. Phased execution plan

**Phase 1 — produce inventory (this document).** ✅ **Done.**

**Phase 2 — demolish, one file per commit:**

1. `test_keys_db.py` 4,537 → ~200 LOC
2. `test_keys_output.py` 1,510 → ~150 LOC
3. `test_keys_cli_show.py` 1,190 → ~80 LOC
4. `test_keys_health.py` 1,040 → ~120 LOC
5. `test_keys_models.py` 541 → ~60 LOC
6. `test_keys_cli_*.py` cluster (12 files, ~7,500 LOC) → 12 × ~60 LOC = 720 LOC
7. `test_api.py` 1,256 → ~250 LOC (HTTP boundary keeps a bit more — error envelope contract is real)
8. `test_service.py` 1,084 → ~150 LOC
9. `test_keys_auth.py` 683 → ~200 LOC (security-critical; keep three round-trips)
10. The remaining ~30 files → trim aggressively; long tail averaged ~50 LOC each.

Each commit's gate:
- Full pytest suite green (`uv run pytest`).
- Full non-regression suite green (`uv run pytest -m non_regression`).
- CI run on master after every push.
- `git diff --stat` reported in commit body so each cut is auditable.

**Phase 3 — recheck ratio.** Stop when test LOC < 5,000 and ratio ≤ 0.7×. Re-evaluate after each epic; the new project-context.md rule is "every retrospective spot-checks the test:source ratio and applies §3 above to any new tests added since the last retro."

---

## 6. What this is NOT

- **Not a coverage drop.** Behavior coverage (HTTP→DB integration, CLI exit-code contract, security-critical paths) stays 100%. The cuts are at the level of "we tested the same SQL filter 9 times" or "we asserted the same pydantic validator 3 times".
- **Not a permission to skip new tests.** Stories continue to ship with tests. The criteria above apply to *new* tests too — code reviews should kill tests in PR rather than waiting for the next round of bloat-cleanup.
- **Not optional.** The rule "every retrospective triages `deferred-work.md` to zero" (added 2026-04-25 to `project-context.md`) gets a sibling: "every retrospective spot-checks one of the top-5 test files for new bloat."
