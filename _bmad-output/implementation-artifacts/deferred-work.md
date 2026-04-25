# Deferred Work

Items surfaced during code reviews that remain after the 2026-04-25 (round 2) hardening pass. Re-triage when picking up a related story.

> **Provenance:** This file was pruned on 2026-04-25 (round 2) to remove all entries that landed in the in-flight hardening pass (43 SHIPPED + 13 NO-OP closures). Status of every Epic 4-era deferred item is tracked in `_bmad-output/implementation-artifacts/epic-4-retro-2026-04-24.md` §5.3 (`[SHIPPED]` / `[NO-OP]` / `[REMAINING]`). The 26 `[REMAINING]` items below are the only Epic 4-era backlog still open.

## Deferred from: code review of story-4-6 (2026-04-24)

- **Brittle `path:line-range` citations across `docs/monetization.md` §LGPD Operator Obligations §References** — every reference is `prd.md:NNN`, `architecture.md:NNN`, `epics.md:NNN`, `deployment-guide.md:NNN`, `audit.py:NN-NN` form. AC15 explicitly mandates this format, so the design is locked-in for 4.6. Future edits to those source files silently falsify the cited line ranges. Re-triage when/if a docs-regression CI gate (already in this file, see "Docs-regression CI gate" entry below) lands — that gate could parse `path:line-range` citations and assert the cited file is at least N lines long, with a deeper variant grepping for an expected anchor near the cited line. [`docs/monetization.md` §References]
- **Sprint-status YAML duplicate `last_updated`** — header comment (`# last_updated: 2026-04-24 (story X → review)`) and body (`last_updated: 2026-04-24`) must stay in sync. The YAML file's own comment acknowledges this is intentional but fragile. A pre-commit hook (`grep '^# last_updated' | head -1` vs `yq '.last_updated'`) could enforce it. Out of any single story's scope; queue for a tooling-pass story if drift ever materialises. [`_bmad-output/implementation-artifacts/sprint-status.yaml:2,47`]
- **Deferred-work bullets in `docs/monetization.md` §LGPD Operator Obligations name future work without tracking IDs** — the handbook's own deferred-work subsection lists `--include-audit`, `correct-tax-id`, ANPD URL pinning, etc. without linking to issue/story IDs. The project's actual tracking surface is this `deferred-work.md` file plus `sprint-status.yaml`; the handbook's bullets are summary-only. If a future 2.x ever wires real issue tracking (GitHub issues, Linear, etc.), the handbook's bullets should gain numeric anchors. [`docs/monetization.md` §Deferred work tracked against this handbook]

## Deferred from: code review of story-4-5d round 2 (2026-04-24)

- **`@api_chunked` `*chunked*` substring match can false-positive on extension tokens** — values like `x-chunked-encoding` or `chunked-xyz` are rejected with 411 despite not being RFC chunked framing. No known real-world client sends such values; speculative. [`deploy/caddy/Caddyfile:38`, `Caddyfile-no-landing:28`]
- **Caddy `respond` rejections are plaintext, not the `ComadreError` JSON envelope** — inconsistent error shape for API clients. Design decision (Caddy-level errors pre-date app-level handlers). A dedicated envelope-unification story would be needed (folds into Caddy `handle_errors` work — F67 in retro §5.3).

## Deferred from: code review of story-4-3 (2026-04-20) — HARDENING-PASS REMAINING

- **AES-256-CBC envelope is unauthenticated (no AEAD).** Spec chose CBC+PBKDF2 for openssl-1/3 portability. When OpenSSL 3.2+ is the guaranteed floor, migrate to `-aes-256-gcm` or a `openssl enc`+HMAC belt for authenticity. **F2 — REMAINING (architectural; breaks existing archives).** [`deploy/ansible/playbooks/backup-keys.yml:126`, `restore-keys.yml:112-115`]
- **Archived Fernet key echoed to ansible logs on key-divergence restore path.** Conflicts with the CLAUDE.md "SOLE surface that prints key material" invariant inherited from Story 4.2. Spec §7 Q7 chose warn-and-wait-with-key-echo. Revisit if a log-capture channel ever materializes. [`deploy/ansible/playbooks/restore-keys.yml:131, 261`]
- **`bash -c '{{ _backup_script }}'` quoting fragility.** Current content works (verified via `shlex.split` simulation), but any future edit introducing quote-sensitive content could silently break. Candidate to move scripts to `deploy/ansible/scripts/*.sh`. **F6 — REMAINING.** [`deploy/ansible/playbooks/backup-keys.yml:96-137`, `restore-keys.yml:96-137`]
- **`backup_file` operator-supplied via `-e` interpolates into `test -r "{{ backup_file }}"` / `openssl -in "{{ backup_file }}"`.** Command-injection surface under operator-in-the-loop DR. Pass through a `-e BACKUP_FILE=` env var + `$BACKUP_FILE` in the script as hardening. **F4 — REMAINING.** [`deploy/ansible/playbooks/restore-keys.yml:77-85, 112-115`]

## Deferred from: code review of story-3-3 (2026-04-19) — HARDENING-PASS REMAINING

- **`cast(Settings, settings_obj)` is a typing escape hatch on `load_settings_and_tz`.** Tighten the helper's return annotation to `tuple[Settings, ZoneInfo] | None` so mypy audits the bridge; the cast becomes redundant. **F36 — REMAINING (cross-cutting refactor).** [`src/comadre/keys/cli/commands/system.py:~316-317`]
- **Ansible `billing_timezone` has no validation — a typo (`America/Sao-Paulo`) silently desyncs cron from the app.** Python-side IANA validator landed in `src/comadre/config.py` (2026-04-25 hardening pass); ansible-side `assert` task in `bootstrap.yml` validating against `zoneinfo.available_timezones()` is the remaining half. [`deploy/ansible/playbooks/bootstrap.yml:308-312`]
- **CLI tests patch `system_cmd.resolve_today_in_tz` instead of the source module `comadre.keys.cli._clock.resolve_today_in_tz`.** Story spec's "Test-flake avoidance" explicitly prefers patching the source module for refactor resilience. Works today via the import-in-module binding; brittle against a future refactor that re-resolves the symbol dynamically. **F56 — REMAINING.** [`tests/test_keys_cli_suspend_sweep.py:~67-68`]

## Deferred from: code review of story-2-2 second pass (2026-04-18) — HARDENING-PASS REMAINING

- **`/health` shape-valid-random DoS — mitigate at Caddy.** The bearer shape-check short-circuit blocks garbage tokens but lets shape-valid uniform-random tokens through to `lookup_key_auth`, which serializes on the single SQLite connection. Operator decision 2026-04-18: add IP-based rate limit on unauthenticated `/health` via Caddy's `rate_limit` directive. **F14 — REMAINING.** [`src/comadre/main.py:300-303`, `deploy/caddy/Caddyfile`]
- **Cross-mount sentinel invalidation silently fails.** If CLI runs on the host and API in a container with a non-bind-mount copy of the DB directory, sentinel touches don't propagate and revoked keys keep authenticating for up to the 60s cache TTL. Add a startup probe. **F16 — REMAINING.** [`src/comadre/keys/db.py:163-183`]
- **Sentinel invalidation via mtime is vulnerable to coarse-mtime filesystems and same-tick collisions.** Move to content-based signaling (write a monotonic counter to the sentinel file, compare content not mtime). **F17 — REMAINING (architectural).** [`src/comadre/keys/cache.py:72-79`]

## Deferred from: code review of story-2-2 post-rewrite (2026-04-18) — HARDENING-PASS REMAINING

- **Timing-observable latency between `AuthCache` hit and miss.** With the legacy single-API_KEY hmac fast path retired, every request now goes through hash + SELECT (cache miss) or cache get (hit). The delta is measurable and can be used to enumerate which keys are recently active. **F18 — REMAINING (security-critical, needs bench).** [`src/comadre/keys/auth.py`]
- **`api_key.rate_limit_rpm` CHECK has no upper bound.** Schema enforces `> 0`; CLI caps 1..10000, but a direct SQL edit or malformed backup restore could set `rpm=10^9`. Add a CHECK (`rate_limit_rpm BETWEEN 1 AND 10000`) in a v002 migration. **F19 — REMAINING.** [`src/comadre/keys/migrations/v001_initial.sql:17`]
- **Denied-key spam never hits the rate-limit bucket.** FastAPI dependency order runs `verify_api_key` before `check_rate_limit`; suspended / revoked / unknown keys 401 before paying any bucket cost. Mitigation belongs in the DoS-hardening story (combine with F14). **F20 — REMAINING.** [`src/comadre/keys/auth.py`, `src/comadre/rate_limit.py`]

## Deferred from: code review of story-1-6 (2026-04-17)

- **AC20 performance budget not regression-tested.** Dev Agent Record cites 301 ms (`update-key`) / 347 ms (`rotate-key`) / 308 ms (`revoke-key`) measured on a 1 K-customer / 2 K-key / 5 K-audit seed. Spec explicitly permits leaving this as an ad-hoc script rather than a committed test. Revisit when a perf-regression incident suggests a micro-benchmark marker is worth the maintenance cost. [`tests/test_keys_cli_{update,rotate,revoke}_key.py`]

## Deferred from: dev-story of story-1-6 (2026-04-17) — HARDENING-PASS REMAINING

- **Shared CLI-test fixture module.** Five copies of ``_clear_settings_cache`` / ``_reset_consoles_to_buffers`` / ``env`` / ``_buffers`` / ``_clear_buffers`` / seed helpers now live across many test files. Extract to a shared ``tests/conftest_keys_cli.py``. **F41 — REMAINING.** [`tests/test_keys_cli_*.py`]
- **``rotate-key`` plaintext-in-memory duration.** The new plaintext is held by the command body from ``generate_api_key_plaintext()`` through ``render_key_panel(issued)``. A unified signal-handling design across issue/rotate is needed before this is actionable. [`src/comadre/keys/cli/commands/keys.py::rotate_key_cmd`]
- **``api_key`` has no ``revoked_at`` column.** Revocation timestamp lives solely in ``audit_log.occurred_at``. If Epic 3 / Epic 4 grows a need to sort revoked keys by revocation time, add a v002 migration adding ``revoked_at TEXT``. [`src/comadre/keys/migrations/v001_initial.sql`]
- **Concurrent ``rotate-key`` invocations against the same row.** Project runs a single FIFO queue for the runtime; SQLite's ``busy_timeout=5000`` is the only protection. Pair with Story 1.5's "no concurrent-update regression test" item. [`tests/test_keys_cli_rotate_key.py`]
- **Cross-cutting ``load_settings_and_tz`` adoption.** ``issue-key`` / ``list-keys`` / ``show`` / ``update-customer`` still inline their own settings→TZ→DB-open ladder. **F38 — REMAINING.** [`src/comadre/keys/cli/commands/keys.py`, `src/comadre/keys/cli/commands/customers.py`]

## Deferred from: code review of story-1-5 (2026-04-17) — HARDENING-PASS REMAINING

- **Audit-details JSON assertions compare exact byte strings.** Tests assert literals like `'{"fields": ["email"]}'`. If `log_event` ever switches `json.dumps` separators, every one of these tests breaks. Migrate to `json.loads(row["details_json"]) == {"fields": [...]}`. **F42 — REMAINING.** [`tests/test_keys_db.py:457,487,574,692,729`, `tests/test_keys_cli_update_customer.py:961,993,1077,1485,1507`]
- **`UpdateCustomerResult.customer` does a full post-commit `get_customer_detail` round-trip to read only `.id` (already known) and `.name`.** Optimization. [`src/comadre/keys/db.py:333-344`, `src/comadre/keys/cli/commands/customers.py:778-779`]
- **`_logger.info` raising after a successful commit would bypass `render_confirmation`.** Wrap the log call in `contextlib.suppress(Exception)`. [`src/comadre/keys/cli/commands/customers.py:772-779`]

## Deferred from: code review of story-1-2 (2026-04-17)

- **`price_monthly` stored as SQLite `REAL` (binary float).** Classic money-as-float precision drift. Schema defined in Story 1.1's v001 migration; changing requires a v002. [`migrations/v001_initial.sql`]

## Deferred from: code review of story-1-1 (2026-04-16) — HARDENING-PASS REMAINING

- **AC8 `occurred_at` "generated once per transaction" invariant.** `log_event` computes its own timestamp per call, fine for 1.1 (one audit row per txn) but blocks future multi-row stories. Refactor `log_event` signature to accept a shared `occurred_at`. [`src/comadre/keys/audit.py`]
- **Unicode / NBSP handling in tax IDs.** `strip_tax_id` mask regex uses `\s` which doesn't match NBSP (U+00A0) or zero-width spaces. Address if we hit support tickets. [`src/comadre/keys/crypto.py`]
- **Test-framework micro-issues.** `_reset_for_tests` leading-underscore import from tests, isolation_level comment in `test_no_inner_transaction` is misleading, `test_second_run_skips_migration` monkeypatches `importlib.resources.files` globally. Clean up in next test-hygiene pass. [`tests/test_keys_output.py`, `tests/test_keys_audit.py`, `tests/test_keys_cli.py`]
- **Robustness improvements not currently required.** SIGINT mid-transaction, NTP clock skew producing non-monotonic `occurred_at`, ULID collision retry, `Fernet` instance caching in bulk-import contexts. Defer to load-test or bulk-import story. [`src/comadre/keys/db.py`, `src/comadre/keys/crypto.py`]

## Deferred from: code review of story-1-4 (2026-04-17) — HARDENING-PASS REMAINING

- **`ShowTarget.value` typing forces `cast(...)` at every call site.** The discriminated-union typing requires every reader to `cast(...)` the variant out. Spec §Task 8.2 explicitly accepts this shape, but a future cleanup could split into per-kind dataclasses. [`src/comadre/keys/db.py`, `src/comadre/keys/cli/commands/customers.py`]
- **`list_audit_events` IN-clause unbounded against `SQLITE_MAX_VARIABLE_NUMBER`.** Modern SQLite caps at 32k vars by default; theoretical today. [`src/comadre/keys/db.py`]
- **Rich markup injection via stored `name` / `notes` / `customer_name` in DetailPanel bodies.** Cross-cutting fix: wrap interpolated row-data with `rich.markup.escape(...)` across all `render_*` helpers. **F24 — REMAINING.** [`src/comadre/keys/cli/output.py`]

## Deferred from: code review of story-1-3 (2026-04-17)

- **Bare `str` Typer options vs `click.Choice`/`Enum`.** `list-keys` declares `--status` / `--billing-mode` / `--format` as `str | None` + hand-rolled membership checks. Cross-cutting Typer-idiomaticity sweep. [`src/comadre/keys/cli/commands/keys.py`]
- **`render_json` does not validate against NaN / Inf floats.** No current writer produces these. Guard with `json.dumps(..., allow_nan=False)`. [`src/comadre/keys/cli/output.py:271-278`]

## Deferred from: code review of story-3-1 (2026-04-18) — HARDENING-PASS REMAINING

- **`get_connection` OSError/PermissionError unhandled across all CLI commands.** Every CLI command catches only `sqlite3.Error` from `get_connection`. If `get_connection` itself raises `OSError`/`PermissionError`, the CLI crashes with a raw traceback. **F34 — REMAINING (cross-cutting).** [`src/comadre/keys/cli/commands/billing.py:136, 238, 326`, `src/comadre/keys/cli/commands/keys.py`]
- **`_apply_migrations` RuntimeError unhandled across all CLI commands.** `_apply_migrations` raises `RuntimeError` on a schema-version downgrade; every CLI command catches only `sqlite3.Error` around it. **F35 — REMAINING.** [`src/comadre/keys/cli/commands/billing.py:143, 245, 333`]
- **No DB CHECK constraint on `api_key.paid_until` format.** `mark_key_paid` stores `paid_until` verbatim, relying on the caller for YYYY-MM-DD validation. Revisit when the next schema bump lands. [`src/comadre/keys/migrations/v001_initial.sql`, `src/comadre/keys/db.py:1157`]
- **Copy-paste drift in three `_seed_customer_and_key` test fixtures.** Cosmetic test-only concern — a shared `tests/fixtures/registry.py` module would collapse all three. (Folds into F41.) [`tests/test_keys_cli_mark_paid.py`, `tests/test_keys_cli_suspend.py`, `tests/test_keys_cli_reactivate.py`]

## Deferred from: code review of story-4-2 (2026-04-19)

- **Confirmation prompt does not identify the target DB path.** **CLOSED 2026-04-25** (`F11` shipped — see retro §5.3).

## Deferred from: code review of 4-4-operational-safety-file-permissions (2026-04-20)

- **Backup-archive assertion counts 0-byte / truncated files as "present"** [`deploy/ansible/playbooks/health.yml:296-314`] — a crashed `backup-keys.yml` mid-`openssl enc` leaves an empty tarball that passes the count-based assertion. **F13 — REMAINING.**
- **Multi-replica test is in-process only; cross-process scenario deferred to Task 8 VPS smoke** [`tests/test_keys_db_multi_replica.py` whole file] — spec-sanctioned. File name sets an expectation of cross-process that the test doesn't fulfil; consider renaming to `test_keys_db_connection_contract.py` or spawning a `subprocess` child.

## Deferred from: code review of 4-5a-ci-security-headers-regression (2026-04-21) — HARDENING-PASS REMAINING

- **`Caddyfile-no-landing` not exercised in CI** — the primary `Caddyfile` is covered; the no-landing variant has a byte-identical `header { ... }` block today. Promote to an explicit parametrised test the day the two files legitimately diverge. **F48 — REMAINING.**
- **404/405 + file_server header-middleware bypass (Caddyfile `handle_errors` hardening)** — already captured in Story 4.5a §Deferred-work; surfaced again by the Acceptance Auditor. A dedicated hardening story should add a site-block `handle_errors` that re-applies the 6 headers + `-Server`/`-Via` to 404/405 responses, then un-hook `_skip_if_file_server_error_path` and refresh `feedback_caddy_server_header.md` (user memory). **F67 + F68 — REMAINING (HIGH PRI).**

## Deferred from: code review of story-4-5d (2026-04-24)

- **Chunked / `Transfer-Encoding` oversized uploads bypass the fast-path 413 and hit the silent-truncation path.** Spec §"Deferred work to flag at story close" already lists this as out-of-scope. [`deploy/caddy/Caddyfile:29-42`]
- **GET/HEAD/DELETE/OPTIONS with `Content-Length: >1048576` returns 413.** RFC-legal but rare. [`deploy/caddy/Caddyfile:29-32`]
- **Exact-boundary probe at `_ONE_MB` and `_ONE_MB + 1` absent.** [`tests/test_non_regression/test_request_body_limit.py:31`]
- **No `Expect: 100-continue` probe.** [`tests/test_non_regression/test_request_body_limit.py`]
- **No negative-path probe asserting that POST to a non-`@api` path with 2 MiB does NOT return 413.** [`tests/test_non_regression/test_request_body_limit.py:14`]

## Deferred from: code review of story-4-5e (2026-04-24)

- **Test 3's 3-request budget exhaustion can straddle the 60s rolling window under CI stalls** — Pragmatic fix when needed: wrap the 3-request block in `@pytest.mark.timeout(10)`. [`tests/test_non_regression/test_rate_limit_wired.py:147-164`]
- **Envelope-hint tautology: `retry_after` is read from the response header and then fed into the expected envelope** — Both values read from the same `RateLimitError` in `exceptions.py:229-231`, so the coupling mirrors the production contract. [`tests/test_non_regression/test_rate_limit_wired.py:171-190`]

## Deferred from: code review of story-4-5f (2026-04-24) — HARDENING-PASS REMAINING

- **`from fastapi import *` star-import evades the HTTPException import scan.** One-line patch + fixture when the pattern appears in real code. [`tests/test_non_regression/test_no_raw_httpexception.py:122-128`]
- **`tokenize.generate_tokens` / `ast.parse` raise on malformed source rather than failing with a named path.** Inherited verbatim from 4.5c's shape. **F46 — REMAINING (folds into F43).** [`tests/test_non_regression/test_no_raw_httpexception.py:108, 139`]
- **`# scan-allow:` empty-reason enforcement is documentation-only.** Mechanize once across 4.5c/4.5f/4.5g simultaneously. **F44 — REMAINING (folds into F43).** [`tests/test_non_regression/test_no_raw_httpexception.py:13-16`]
- **`# scan-allow:` token is shared verbatim across 4.5c/4.5f/4.5g.** Candidate fix: namespace the token (`# scan-allow[4.5f]:`). **F45 — REMAINING (folds into F43).** [`tests/test_non_regression/test_no_raw_httpexception.py:58`, `tests/test_non_regression/test_timing_safe_compare.py` (4.5c)]

## Deferred from: code review of story-4-5g (2026-04-24)

- **`'f"SELECT' in findings[0].code'` self-test pins bandit's context-line formatting.** Bandit pinned at 1.9.4 in `uv.lock` today; revisit when bumping. [`tests/test_non_regression/test_sql_static_bandit.py:362`]
