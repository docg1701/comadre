# Blind Hunter — Story 1.6 Findings

**Note:** Produced in-thread (Opus 4.7) as fallback for rate-limited subagent. The reviewer had prior spec context; findings restricted to diff-observable issues only.

## MAJOR

- **`update_api_key` silent-no-op returns `None` ambiguously.** After confirming row exists and isn't revoked, `if not set_parts: return None` (src.diff:945–949) reuses the "row missing" return signal. A caller can't distinguish "missing row" from "caller forgot to pass any field". Distinct `ValueError` would be cleaner.
- **`revoke_api_key` does not validate `reason`.** Helper takes `reason` directly to `log_event` without stripping, NUL/LF check, or length cap. CLI scrubs — but any non-CLI caller (future REST / cron) writes raw bytes to `audit_log.details_json`. Evidence: `src.diff:1093–1125`.
- **`rotate-key` generates plaintext before the helper's revocation check.** `generate_api_key_plaintext()` (src.diff:531) runs before `rotate_api_key` rejects a revoked row. Wasted entropy on the reject branch, and couples ordering if the token helper ever becomes non-pure.
- **`_redact_log_target` is dead code.** Defined at src.diff:178–189, never called. Success paths use helper-returned `key_prefix` from the resolver; the redactor is moot. Delete it or wire it in.
- **Assertions in production code.** `_key_update_clauses` uses `assert result.changes.price_old is not None` (src.diff:218–219). Stripped under `-O` / `PYTHONOPTIMIZE=1`. `keys/audit.py` docstring explicitly warns against this pattern. Use an explicit check or a `RuntimeError`.

## MINOR

- **Redundant `.replace("Z", "+00:00")` before `datetime.fromisoformat`.** Python 3.11+ parses `Z` natively (src.diff:1046).
- **Pattern divergence in helper refreshes.** `update_api_key` and `revoke_api_key` reload via `get_key_detail_by_id`; `rotate_api_key` hand-builds an `ApiKeyRecord` from the pre-UPDATE row + new hash. Deliberate for perf (per docstring) but breaks the refactor-by-analogy reflex.
- **`_logger.info` suppress-`Exception`.** Broad catch — a handler bug disappears silently. Trade-off is documented ("durability > observability"); still worth a once-over.

## CRITICAL

None from a diff-only view.
