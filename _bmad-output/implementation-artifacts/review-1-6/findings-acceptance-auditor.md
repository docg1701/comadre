# Acceptance Auditor — Story 1.6 Findings

**Note:** Produced in-thread (Opus 4.7) as fallback for rate-limited subagent.

## MAJOR

- **AC7 ambiguous-prefix path is spec'd but untested.** Spec calls for `Ambiguous prefix: multiple keys match '<prefix>'` + exit 3 on all three commands (spec L171–L172). Code handles via `_resolve_key_target` but no test constructs two keys sharing an 8-char prefix. Partial coverage.
- **AC17 help text uses ASCII `->` where spec shows `→` (U+2192).** Spec L272 example: `--notes "upgraded 2026-05-12 from 60→120rpm"`. Code emits `"upgraded 2026-05-12 from 60->120rpm"` (src.diff:332) and test asserts the ASCII form (test_update_key.diff ~line 200). Code + test are internally consistent; spec wording is not honored byte-for-byte. Minor — the ConfirmationLine arrow IS U+2192 per AC1 (code uses `\u2192`, test asserts `\u2192`), only the help-text example diverges.

## MINOR

- **AC5 ordering not explicitly asserted.** Spec L132–L134 requires the complimentary `--price` mutex to fire AFTER `resolve_show_target` succeeds (so not-found still takes precedence). `test_complimentary_plus_price_exits_2` seeds the key so the ordering is exercised implicitly, but no negative test asserts "missing key + complimentary + price → exit 3 not exit 2".
- **AC20 performance budget not regression-tested.** Dev Agent Record claims 301ms / 347ms / 308ms. Spec explicitly allows this (temporary script, not committed). OK per scope but worth noting — a future regression is detectable only by re-running the ad-hoc script.

## None for:

- AC1 (rpm+price arrow form) — ✓
- AC2 (rpm-only, price-only) — ✓
- AC3 (notes REPLACE not APPEND) — ✓
- AC4 (3-flag combo + atomicity rollback) — ✓
- AC6 (revoked exit 3) — ✓
- AC8 (rotate 9-column preservation + end-of-life contract) — ✓
- AC9 (complimentary rotation) — ✓
- AC10 (rotate revoked exit 3) — ✓
- AC11 (rotate atomicity, KeyPanel not rendered on rollback) — ✓
- AC12 (hash collision exit 5 + retry hint) — ✓
- AC13 (revoke --yes active + suspended) — ✓
- AC14 (interactive confirm y/n/EOF + prompt-on-stderr) — ✓ (weak invariant noted by Edge Case Hunter)
- AC15 (already revoked exit 3) — ✓
- AC16 (reason shape: empty / whitespace / NUL / LF / CR / oversize) — ✓
- AC18 (audit + log sanitization) — ✓
- AC19 (read-after-write via `show`) — ✓

## Scope guards — verified clean

- No `--billing-mode` flag on update-key.
- No `suspend` / `reactivate` / `mark-paid` commands.
- No v002 migration.
- `last_used_at` is written only in `rotate_api_key` (SET to NULL).
- No raw `HTTPException`.
- No `os.environ` reads.
- `keys/main.py` / `api.py` / `rate_limit.py` / `service.py` / `config.py` / `exceptions.py` untouched.
- Import graph downward-only (the new helpers don't import from `keys.auth` / `keys.cache` — those modules still don't exist).

## Deferred-work claims verified

- `_logger.info` wrapped in `contextlib.suppress(Exception)` on all three commands ✓
- Audit-details assertions use `json.loads == {...}` in every new test ✓
- `_truncate_ident` applied to all three commands' error titles ✓
- `--rpm` 10000 cap on `update-key` only (per scope) ✓
- `--notes` / `--reason` 1024-char cap ✓
- NUL / LF / CR rejection on `--notes` / `--reason` ✓

## AC coverage summary

| AC | Status |
|----|--------|
| AC1 | ✓ |
| AC2 | ✓ |
| AC3 | ✓ |
| AC4 | ✓ |
| AC5 | ✓ |
| AC6 | ✓ |
| AC7 | ✗ partial (ambiguous-prefix untested on all 3 commands) |
| AC8 | ✓ |
| AC9 | ✓ |
| AC10 | ✓ |
| AC11 | ✓ |
| AC12 | ✓ |
| AC13 | ✓ |
| AC14 | ✓ |
| AC15 | ✓ |
| AC16 | ✓ |
| AC17 | ~ minor (ASCII `->` in help vs spec's U+2192) |
| AC18 | ✓ |
| AC19 | ✓ |
| AC20 | ~ deferred (perf test not committed, allowed by scope) |
