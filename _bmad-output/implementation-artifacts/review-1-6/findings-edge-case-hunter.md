# Edge Case Hunter — Story 1.6 Findings

**Note:** Produced in-thread (Opus 4.7) as fallback for rate-limited subagent.

## CRITICAL

- **`revoke_api_key` helper accepts unvalidated `reason`.** See Blind Hunter #2. Any caller bypassing the CLI writes raw control chars / multi-KB blobs into `audit_log.details_json`. `json.dumps` accepts `\x00` as `"\u0000"` — valid JSON but breaks downstream viewers. Fix: move shape validation into the helper, not the CLI.
- **`_key_update_clauses` assertions strippable under `-O`.** Under `PYTHONOPTIMIZE=1`, `assert result.changes.price_old is not None` disappears and `_format_brl(None)` raises `TypeError`. Not caught by any test (all run without `-O`). Fix: raise `RuntimeError` instead of asserting, matching `keys/audit.py` precedent.

## MAJOR

- **AC7 ambiguous-prefix path untested for all three commands.** `_resolve_key_target` handles the `key_ambiguous` branch (src.diff:292–296), but no test in `test_keys_cli_update_key.py`, `test_keys_cli_rotate_key.py`, or `test_keys_cli_revoke_key.py` constructs two keys with identical 8-char prefixes and asserts `Ambiguous prefix: multiple keys match` + exit 3.
- **No not-found integration test for `rotate-key` / `revoke-key`.** The `test_update_key.diff` has `test_missing_key_exits_3`; rotate-key and revoke-key tests do not. The code path via `_resolve_key_target` is shared but untested end-to-end for those two commands.
- **Mutex-error double-handling in `update_key_cmd`.** `except ValueError as exc: if "revoked" in msg → exit 3 else → exit 2 with complimentary hint` (src.diff:442–456). A future `ValueError` whose message contains neither substring gets misrouted to the complimentary-exit-2 branch. Fix: match the full sentinel string, or use typed exceptions.
- **Hash-collision detection relies on substring matching.** `"key_hash" in args_msg` (src.diff:555). Works today because the UNIQUE index message includes `api_key.key_hash`. A future schema-rename silently degrades to the generic `Database error` panel. The fallback is still correct (exit 5), but the retry hint disappears.
- **`rotate_api_key`'s customer JOIN fails silent on orphaned keys.** `JOIN customer AS c ON c.id = k.customer_id` (src.diff:1021) — if the customer row is hard-deleted (future Story 4.1), `fetchone()` returns `None` and the helper returns `None` as if the key was missing. Misdiagnoses orphan rotation as "not found". Deferred-work already lists LGPD hard-delete; re-deferring is acceptable.
- **`update-key --notes` stores whitespace verbatim; `revoke-key --reason` strips.** Asymmetry with no spec-level justification. Operator calling `update-key --notes "  padded  "` gets literal padding in the DB; `revoke-key --reason "  padded  "` gets `padded`. Decide one convention.
- **Prompt-on-stderr invariant weakly asserted.** `test_interactive_prompt_lives_on_stderr` (test_revoke_key.diff:315–331) only asserts the prompt is NOT in stdout. Doesn't verify it IS in stderr. CliRunner merges streams by default under Click 8.2; the positive invariant is untested.
- **`_logger.info` catches `Exception` — not `BaseException`.** Good (SIGINT / SystemExit propagate). But the suppression is silent — if the logging backend is misconfigured, the mutation still succeeds but observability is lost without signal. Consider a fallback stderr print on the exception.

## MINOR

- **Interactive-prompt tests don't cover junk input.** Click's `confirm` re-prompts on anything other than y/n until stdin exhausts. Tests cover y / n / empty-line / EOF — not a word like `maybe`. Probably fine (click's default for unknown input is re-ask, which under `CliRunner` with finite stdin still aborts).
- **`revoke-key` does DB work before the confirmation gate.** Settings + TZ + DB open + migrations + prefix lookup all fire before the prompt. Cheap, but operator who bails still pays.
- **`rotate_api_key` `datetime.fromisoformat(... .replace("Z", "+00:00"))`.** Python 3.11+ parses `Z` natively.
- **`_KEY_NOTES_MAX = 1024` reused for `--reason`.** Convenient today; surprising if the caps diverge.

## None (explicitly):

- Concurrency under the single-writer CLI — SELECT-then-UPDATE within `with conn:` is race-safe; `busy_timeout=5000` handles two-operator races.
- Clock seam — all helpers take `today` as parameter; tests bypass `date.today()`.
- Audit-details blocklist — none of `update_key` / `rotate_key` / `revoke_key` payloads use blocklisted keys.
- SQL parameterization — SET clause assembles literal column names only; operator input lands in `?` bindings.
- Transaction-scope contract — all three helpers own `with conn:`; the CLI does not wrap.
