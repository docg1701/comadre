# Deferred Work

Items surfaced during code reviews that were judged real but non-gating for the current story. Re-triage when picking up a related story or a hardening pass.

## Deferred from: code review of story-1-1 (2026-04-16)

- **AC7 partial-migration crash scenario unverified.** Current `with conn:` guarantees atomicity so no real defect, but no test exercises crash-between-DDL-and-version-row. Add when touching migration runner next. [`src/comadre/keys/db.py`]
- **AC8 `occurred_at` "generated once per transaction" invariant.** `log_event` computes its own timestamp per call, fine for 1.1 (one audit row per txn) but blocks future multi-row stories (1.6, 4.1). Refactor `log_event` signature to accept a shared `occurred_at`. [`src/comadre/keys/audit.py`]
- **`os.getlogin()` log-injection sanitization.** Actor column trusts raw username; theoretical `utmp` poisoning. Sanitize to `[A-Za-z0-9._-]` when touching audit path next. [`src/comadre/keys/audit.py`]
- **Operator-config validators.** No checks for: path traversal in `key_registry_db_path`, invalid IANA `billing_timezone`, low-entropy Fernet key. All are operator-controlled config so risk is bounded, but a config-doctor command (Epic 3 health) could surface them. [`src/comadre/config.py`]
- **CLI UX edges on optional fields.** NUL byte in `--name`/`--email`, whitespace-only `--name`, unbounded `--notes` length, repeated `--cpf` flag. Address when building the `update-customer` command in Story 1.5 — the validators will be shared. [`src/comadre/keys/cli/commands/customers.py`, `models.py`]
- **Unicode / NBSP handling in tax IDs.** `strip_tax_id` mask regex uses `\s` which doesn't match NBSP (U+00A0) or zero-width spaces. Address if we hit support tickets about "validates locally but not in registry" mismatches. [`src/comadre/keys/crypto.py`]
- **Test-framework micro-issues.** `_reset_for_tests` leading-underscore import from tests, isolation_level comment in `test_no_inner_transaction` is misleading (DEFERRED is already the default), `test_second_run_skips_migration` monkeypatches `importlib.resources.files` globally via module attribute. Clean up in the next test-hygiene pass. [`tests/test_keys_output.py`, `tests/test_keys_audit.py`, `tests/test_keys_cli.py`]
- **Robustness improvements not currently required.** SIGINT mid-transaction, NTP clock skew producing non-monotonic `occurred_at`, ULID collision retry, `Fernet` instance caching in bulk-import contexts. Defer to load-test or bulk-import story. [`src/comadre/keys/db.py`, `src/comadre/keys/crypto.py`]
- **Silent chmod-failure swallow on parent dir.** `contextlib.suppress(PermissionError)` around `parent.chmod(0o700)` is silent — add a `get_logger("keys.db").warning(...)` when next touching `get_connection`. Low priority because the file itself is still chmod'd. [`src/comadre/keys/db.py`]
