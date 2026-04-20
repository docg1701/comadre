# Story 4.2: Encryption Key Rotation

Status: done

> **Scope note — FR36.** Adds the second CLI verb in Epic 4: `comadre-keys rotate-encryption-key --new-key <fernet>`. The operator supplies a freshly-generated Fernet key on the command line; the verb opens a single transaction, decrypts every active customer's `tax_id_encrypted` BLOB with the current key (read from `KEY_REGISTRY_ENCRYPTION_KEY`), re-encrypts each one with the new key, UPDATEs every row in place, writes a single `rotate_encryption_key` audit row, then prints the success line that tells the operator which value to put into `.env`. The "atomic re-encryption — no window of unreadable data" contract (FR36) is held by SQLite's transaction semantics: if any single row fails (decrypt error mid-way, disk full, KeyboardInterrupt), the whole UPDATE rolls back and every row retains its **original** ciphertext. The operator either lands the new ciphertext everywhere (and is then directed to swap `.env`) or lands it nowhere — never half. **No schema change. No auth-path change. No FastAPI runtime change. No new env var. No new dependency.** One new DB helper (`rotate_encryption_keys` in `keys/db.py`), one new CLI verb (`rotate_encryption_key_cmd` in `keys/cli/commands/system.py`), the matching tests.

## Story

As an operator,
I want to rotate the at-rest encryption key without any window in which the registry holds unreadable ciphertext,
so that I can follow security best practices, recover from a suspected key exposure (compromised `.env`, leaked backup tarball), and meet the LGPD breach-response duty (Art. 48) without taking the registry offline or restoring from a backup.

**Covers FRs:** FR36 (operator can rotate the encryption material by re-encrypting every protected field atomically, without a window in which data is unreadable).
**NFRs:** NFR10 (CPF/CNPJ encrypted at rest with Fernet — preserved across rotation). NFR15 (PII-austere INFO logs — neither the old nor the new key value, nor any decrypted tax ID, appears in structured logs). NFR16 (no error hint or response body echoes a customer-supplied invalid value — applies here to the operator's `--new-key` value if it is malformed).
**UX-DRs:** UX-DR11 (Destroy-tier `--yes` pattern — `rotate-encryption-key` is explicitly listed in the Destroy tier, ux-design-specification.md:894). UX-DR6 (ErrorDisplay on stderr for 4/5/6 errors). UX-DR7 (ConfirmationLine on stdout for the success path). UX-DR10 (exit-code contract — 0/2/4/5/6).
**Epic:** 4 — Security Hardening, LGPD & Operational Safety. Second story in Epic 4 (4.1 → **4.2** → 4.3 → 4.4 → 4.5a–g → 4.6). Story 4.6 (LGPD documentation & breach runbook) will reference this verb verbatim — `docs/monetization.md` "encryption-key rotation" runbook will cite `comadre-keys rotate-encryption-key --new-key <fernet>` plus the `.env` swap procedure (epics.md:1051-1053).

## Builds on

- **Story 4.1 — `decrypt_tax_id`.** `src/comadre/keys/crypto.py:81-97` is the symmetric counterpart to `encrypt_tax_id`. This story is the second consumer of `decrypt_tax_id` (the first is `export-customer`); the rotation loop calls it once per active customer to obtain the canonical-form plaintext before re-encrypting under the new key. The architecture invariant — "CPF/CNPJ encryption/decryption ONLY happens in `crypto.py` — no other module touches Fernet directly" (architecture.md:637) — is preserved: the new DB helper `rotate_encryption_keys` calls **only** `decrypt_tax_id` + `encrypt_tax_id` from `crypto.py`, never `Fernet` directly. The grep invariant `rg "fernet\.decrypt" src/` continues to return exactly one hit (the call site inside `decrypt_tax_id`).
- **Story 1.1 — `encrypt_tax_id`.** `src/comadre/keys/crypto.py:75-78` is the existing encryption boundary, unchanged. The rotation re-encrypts every active customer's canonical form through this same primitive; the resulting ciphertexts are byte-different from the originals (Fernet's IV is random per call) but semantically identical.
- **Story 1.1 — single-transaction + audit-row template.** `src/comadre/keys/db.py:351-397` (`insert_customer`) is the canonical "open the transaction in the helper, do the mutation, write one audit row, commit" template. `rotate_encryption_keys` follows the same shape on a larger scale: open one transaction, iterate the active-customer rows performing decrypt-then-encrypt-then-UPDATE per row, write one summary audit row, commit. Either every row's ciphertext flips to the new key OR none does.
- **Story 1.1 — `_chmod_0600`, `get_connection`, `_apply_migrations` discipline.** Every CLI command opens connections via `get_connection` and runs `_apply_migrations` at the top of the body before touching data. `rotate-encryption-key` is no exception.
- **Story 4.1 — Destroy-tier CLI confirmation skeleton.** `src/comadre/keys/cli/commands/customers.py:1084-1238` (`delete_customer_cmd`) is the most recent canonical Destroy-tier verb: literal-flag validation → settings ladder → DB open + migrations → pre-flight count for the prompt preview → `typer.confirm(abort=True)` on `--yes is False` → helper call → structured log + ConfirmationLine. `rotate-encryption-key` follows this skeleton verbatim; only the helper, the prompt text, the success line, and the error map differ.
- **Story 3.4 — system-verb CLI siting + `system.py` exit-code contract.** `src/comadre/keys/cli/commands/system.py:1-24` is the docstring contract for the system-verbs module — its line 5 already foreshadows: "Story 4.2 (`rotate-encryption-key`) will add the final subcommand here". The new verb lands in `system.py` next to `cache-status` / `suspend-sweep` / `health`, completing the "operational verbs in one module" grouping. The exit-code contract gains code 4 (validation error from the `--new-key` Fernet shape check); codes 0/2/5/6 are reused from the existing surface.
- **Story 3.3 — operator-TZ-irrelevant verb pattern.** `rotate-encryption-key` does NOT consume a date — the rotation is timestamped in UTC by `_utcnow_iso()` in the audit row, identical to how `delete_customer_hard` handles `deleted_at`. The shared `load_settings_and_tz` helper (keys/cli/commands/keys.py:738-781) is used for the settings ladder; the returned `billing_tz` is discarded.
- **Story 4.1 — pyproject.toml hygiene + ruff/mypy/pytest gate.** No new dependencies. The pre-commit gate (ruff / mypy strict / pytest / pre-commit) is unchanged; this story extends the existing surface.

## Unblocks

- **Story 4.3 — Backup & Restore Playbooks.** The backup playbook stores the encryption key encrypted separately from the SQLite payload (NFR14). After a key rotation, the operator must regenerate the next backup so the archived key matches the rotated value; this is a runbook step in 4.6, not a code dependency from 4.3 to 4.2.
- **Story 4.6 — LGPD Documentation & Breach Runbook.** `docs/monetization.md` will document the rotation procedure end-to-end: (1) `python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())'` to mint a new key; (2) `comadre-keys rotate-encryption-key --new-key <fernet>` to re-encrypt and audit; (3) edit `.env` to swap `KEY_REGISTRY_ENCRYPTION_KEY`; (4) `docker compose restart tts-service` to pick up the new value. 4.6 lands the prose; this story ships the verb the prose references.
- **Operator breach-response drill.** With this verb shipped, an operator who suspects key compromise (leaked `.env`, lost backup tarball, departed contractor with shell history) can rotate within seconds, swap the env var, and continue serving traffic — instead of restoring from the previous nightly backup or taking the registry offline.

## Depends on

- Story 4.1 must be `done`. Verified against `_bmad-output/implementation-artifacts/sprint-status.yaml` (2026-04-19): `4-1-lgpd-data-operations-export-hard-delete: done`. The new verb consumes `decrypt_tax_id` from Story 4.1; building 4.2 against an unmerged 4.1 would fail at import time.
- Stories 1.1 (schema + `encrypt_tax_id` + audit scaffolding), 3.4 (system.py CLI module), 4.1 (`decrypt_tax_id`) must all be `done`. Sprint-status.yaml confirms.
- **No new dependency.** `cryptography.fernet` is already pulled in by Story 1.1; no PyYAML-equivalent addition.
- **No schema change.** `customer.tax_id_encrypted BLOB NOT NULL` is the existing storage column; rotation rewrites the BLOB in place, leaving column shape untouched.
- **No auth-path / FastAPI runtime change.** `src/comadre/api.py`, `src/comadre/main.py`, `src/comadre/rate_limit.py`, `src/comadre/keys/auth.py`, `src/comadre/keys/cache.py`, `src/comadre/health.py` (HTTP), `src/comadre/counters.py` stay byte-identical (asserted by AC10).
- **No change to existing migrations.** `src/comadre/keys/migrations/v001_initial.sql` stays byte-identical.
- **No new env var.** The verb reads `KEY_REGISTRY_DB_PATH` + `KEY_REGISTRY_ENCRYPTION_KEY` (current key) via the shared `load_settings_and_tz` helper; the new key is supplied via `--new-key`, never read from the environment.

## Scope

Adds one new DB helper (`rotate_encryption_keys` in `src/comadre/keys/db.py`) plus its return dataclass (`RotateEncryptionKeysResult`), one new CLI verb (`rotate_encryption_key_cmd` in `src/comadre/keys/cli/commands/system.py`), one new audit-action constant on the implicit allowlist, the matching tests, plus the system.py module-docstring update covering the new exit code 4. **No new dep. No schema change. No auth-path change. No FastAPI runtime change. No new env var.**

### 1. New DB helper: `rotate_encryption_keys`

`src/comadre/keys/db.py` — append after `delete_customer_hard` (the most recent multi-row mutation helper). Returns a small dataclass so the CLI gets a structured count for the ConfirmationLine + structured log.

```python
@dataclass(frozen=True, slots=True)
class RotateEncryptionKeysResult:
    """Return payload from ``rotate_encryption_keys`` (Story 4.2).

    ``rows_re_encrypted`` is the count of ``customer`` rows whose
    ``tax_id_encrypted`` was decrypted under the old key and rewritten
    under the new key in the same transaction. Tombstoned rows
    (``deleted_at IS NOT NULL`` — zero-length BLOB ciphertext per the
    Story 4.1 tombstone contract) are intentionally skipped; the count
    reflects active customers only. ``occurred_at`` is the canonical
    ISO-UTC timestamp the helper wrote on the summary audit row, echoed
    back so the CLI can render it without re-sampling the clock.
    """

    rows_re_encrypted: int
    occurred_at: str


def rotate_encryption_keys(
    conn: sqlite3.Connection,
    *,
    old_key: SecretStr,
    new_key: SecretStr,
    actor: str,
) -> RotateEncryptionKeysResult:
    """Re-encrypt every active customer's tax-ID under ``new_key`` in one transaction.

    1. Begin transaction.
    2. ``SELECT id, tax_id_encrypted FROM customer WHERE deleted_at IS NULL``
       — tombstoned rows (zero-length BLOB ciphertext) are skipped because
       Fernet rejects empty input and the row holds no PII anyway.
    3. For each row: ``decrypt_tax_id(old)`` → ``encrypt_tax_id(canonical, new)``
       → ``UPDATE customer SET tax_id_encrypted = ? WHERE id = ?``.
    4. ``log_event(action='rotate_encryption_key', target_type='registry',
       target_id=None, details={'rows_re_encrypted': N})``.
    5. Commit.

    Callers MUST NOT wrap in ``with conn:``. The helper owns the
    transaction so all UPDATEs and the audit write either all commit
    or all roll back. Mid-iteration failures (decrypt error from a
    corrupted row, disk full, ``KeyboardInterrupt``) propagate as
    exceptions; the ``with conn:`` rolls back and every row retains
    its **original** ciphertext — the FR36 "no window of unreadable
    data" guarantee.

    The decrypted canonical plaintext exists only inside the loop's
    local frame and is overwritten on each iteration — no cache, no
    return-channel exposure. The audit ``details`` carry only the
    structural count; ``_FORBIDDEN_DETAIL_KEYS`` rejects any attempt
    to pass tax-ID material.
    """
    from comadre.keys.audit import log_event
    from comadre.keys.crypto import decrypt_tax_id, encrypt_tax_id

    occurred_at = _utcnow_iso()
    rows_re_encrypted = 0

    with conn:
        rows = conn.execute(
            "SELECT id, tax_id_encrypted FROM customer "
            "WHERE deleted_at IS NULL"
        ).fetchall()

        for row in rows:
            canonical = decrypt_tax_id(bytes(row["tax_id_encrypted"]), old_key)
            new_ciphertext = encrypt_tax_id(canonical, new_key)
            conn.execute(
                "UPDATE customer SET tax_id_encrypted = ? "
                "WHERE id = ? AND deleted_at IS NULL",
                (new_ciphertext, row["id"]),
            )
            rows_re_encrypted += 1

        log_event(
            conn,
            actor=actor,
            action="rotate_encryption_key",
            target_type="registry",
            target_id=None,
            details={"rows_re_encrypted": rows_re_encrypted},
            occurred_at=occurred_at,
        )

    return RotateEncryptionKeysResult(
        rows_re_encrypted=rows_re_encrypted,
        occurred_at=occurred_at,
    )
```

**Why the helper takes `old_key` explicitly instead of reading `settings.key_registry_encryption_key` itself.** The CLI already loads settings via `load_settings_and_tz`; passing `old_key` keeps the helper testable without monkeypatching `get_settings()` and matches the project's "config flows down from the CLI command body" pattern (every other db.py helper takes its inputs explicitly).

**Why tombstoned rows are skipped (not also re-encrypted).** Per Story 4.1's tombstone contract (`CLAUDE.md` "LGPD tombstone keeps `tax_id_encrypted BLOB NOT NULL` — purge writes `X''` (zero-length BLOB)"), tombstoned customers store an **empty** ciphertext. `Fernet.decrypt(b"")` raises `InvalidToken`; trying to re-encrypt an empty BLOB would fail. More importantly, the empty BLOB carries zero PII — there is nothing to "rotate the encryption of". Filtering `deleted_at IS NULL` is both correct (skip rows that would error) and semantically clean (only re-encrypt rows that have data).

**Why `_touch_auth_cache_sentinel` is NOT called.** Encryption-key rotation does not change any `api_key.key_hash`, `status`, `paid_until`, or `rate_limit_rpm` — the auth payload is identical pre- and post-rotation. The auth cache holds `AuthPayload` rows, not encrypted tax IDs (which never enter the cache; arch.md:435-441). Cross-process invalidation is unnecessary; touching the sentinel would force a needless cache flush across every replica.

**Why a single transaction over per-row transactions.** The "no window of unreadable data" guarantee (FR36) requires atomic rollback on any mid-stream failure. Per-row transactions would leave the registry in a half-rotated state on disk-full / power-loss / SIGKILL — a subset of rows decryptable only with the new key, the rest only with the old. SQLite's transaction semantics give us the rollback for free; the implementation just has to honour it by holding `with conn:` open across the entire loop.

**Why `target_type='registry'` (not None and not `'customer'`).** The rotation is a registry-wide event — not targeted at any single customer or key. `'registry'` is the right cardinality and matches the convention the suspension-sweep summary row will graduate to in a future hardening pass (`target_type='registry'` is preferable to `None` for grep-ability of registry-level audit events).

**Why the audit row is written INSIDE the same transaction as the UPDATEs.** Same reason every other audit-paired mutation in the codebase: if the rotation rolls back (e.g., decrypt error on row 47 of 50), the audit row must roll back too — otherwise the audit log claims "rotated 50 rows" when zero actually changed. The transactional pairing is a load-bearing invariant.

**Why the loop materializes via `.fetchall()` instead of streaming via the cursor.** SQLite does not allow concurrent UPDATE on the same connection while a SELECT cursor is still open — calling `conn.execute(UPDATE ...)` on the connection that has an open cursor raises `OperationalError("database table is locked")` on some platforms / versions. Materializing into a Python list up front (1000 rows × ~150 bytes per ciphertext = ~150 KB — well within memory budget) sidesteps this entirely. NFR35's reference scale (1000 customers) makes this trivially safe; even a 100K-customer deployment would only allocate ~15 MB.

### 2. New CLI verb: `rotate-encryption-key`

`src/comadre/keys/cli/commands/system.py` — append after `health_cmd`. Follows the `delete_customer_cmd` Destroy-tier template (Story 4.1).

**Imports added at the top of `system.py`:**

```python
from comadre.keys.db import (
    _SCHEMA_VERSION,
    _apply_migrations,
    get_connection,
    list_api_keys,
    rotate_encryption_keys,           # NEW
    run_suspension_sweep,
)
```

Plus the Fernet shape-check import:

```python
from cryptography.fernet import Fernet, InvalidToken
```

**Module-level constants (above `cache_status_cmd`):**

```python
_ROTATE_KEY_BAD_FERNET_HINT = (
    "Generate a fresh Fernet key with: python -c 'from "
    "cryptography.fernet import Fernet; "
    "print(Fernet.generate_key().decode())'."
)
_ROTATE_KEY_DECRYPT_FAILED_HINT = (
    "The current KEY_REGISTRY_ENCRYPTION_KEY value cannot decrypt at "
    "least one customer's tax-ID ciphertext. The transaction has been "
    "rolled back — every row retains its original encryption. Verify "
    ".env matches the deployment-time key before retrying."
)
```

**Command signature:**

```python
@app.command("rotate-encryption-key")
def rotate_encryption_key_cmd(
    new_key: str = typer.Option(
        ...,
        "--new-key",
        help=(
            "New Fernet key (44-char base64) to re-encrypt every active "
            "customer's tax ID with. Generate with: python -c 'from "
            "cryptography.fernet import Fernet; "
            "print(Fernet.generate_key().decode())'."
        ),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Skip the interactive confirmation prompt (for scripting).",
    ),
) -> None:
    """Re-encrypt every active customer's tax ID under a new Fernet key (FR36).

    Atomic: either every active row's ciphertext flips to the new key OR
    none does. After success, edit .env to set KEY_REGISTRY_ENCRYPTION_KEY
    to the new value and restart the service.

    Example: comadre-keys rotate-encryption-key --new-key gAAAAA...
             comadre-keys rotate-encryption-key --new-key gAAAAA... --yes
    """
```

**Body ladder (mirrors `delete_customer_cmd` + a Fernet-shape pre-check):**

1. **New-key Fernet shape validation (exit 4).** `try: Fernet(new_key.encode()) except (ValueError, TypeError): render_error("Invalid encryption key: --new-key is not a valid Fernet key", _ROTATE_KEY_BAD_FERNET_HINT); raise typer.Exit(code=4)`. **Critical**: the `render_error` message must NOT echo the operator-supplied `new_key` value (NFR16 anti-enumeration applies to the operator's own input being possibly captured into terminal logs / shell scrollback if the operator typoed and pasted accidentally).
2. **Settings ladder (exit 6).** `load_settings_and_tz()` — the TZ is discarded; the helper enforces `key_registry_encryption_key` (the OLD key) presence, which we need for the decrypt half of the rotation.
3. **Open DB + migrations (exit 5).** Standard `get_connection` + `_apply_migrations` pattern with `from exc` trace preservation.
4. **Pre-flight count for the confirmation prompt.** `pre_count = conn.execute("SELECT COUNT(*) FROM customer WHERE deleted_at IS NULL").fetchone()[0]` — used in the prompt template so the operator sees scope before committing. Exit 5 on `sqlite3.Error`.
5. **Confirmation gate (UX-DR11).** If `--yes` is False:
   ```python
   typer.confirm(
       f"This will re-encrypt {pre_count} active customer "
       f"tax ID(s) with the new key. Continue?",
       default=False,
       abort=True,
       err=True,
   )
   ```
   On `click.exceptions.Abort`: echo `"Aborted."` to stderr, `raise typer.Exit(code=2)`. Matches the `delete_customer_cmd` and `revoke_key_cmd` abort pattern verbatim.
6. **Helper call (exit 5 on `sqlite3.Error` or `InvalidToken`).** Wrap the `rotate_encryption_keys` call in `try/except`:
   ```python
   try:
       result = rotate_encryption_keys(
           conn,
           old_key=settings.key_registry_encryption_key,
           new_key=SecretStr(new_key),
           actor=get_cli_actor(),
       )
   except InvalidToken:
       render_error(
           "Database error: tax-ID ciphertext failed to decrypt during rotation",
           _ROTATE_KEY_DECRYPT_FAILED_HINT,
       )
       raise typer.Exit(code=5) from None
   except sqlite3.Error as exc:
       render_error("Database error", str(exc))
       raise typer.Exit(code=5) from None
   ```
7. **Close DB.**
8. **PII-austere INFO log.** `_logger.info("Encryption key rotated | rows_re_encrypted=%d | occurred_at=%s", result.rows_re_encrypted, result.occurred_at)` — never the new key, never the old key, never any decrypted tax ID.
9. **Success ConfirmationLine (UX-DR7) — epic AC verbatim.** The epic AC pins this string explicitly:
   ```python
   render_confirmation(
       f"Encryption key rotated. Update KEY_REGISTRY_ENCRYPTION_KEY in "
       f".env to: {new_key}"
   )
   ```
   The confirmation is on stdout; the new key value is echoed back to the operator's terminal as a copy-paste hint for the `.env` swap. **This is intentional**: the operator just typed the value on the same command line (already in shell history); echoing it on success preserves the "what to do next" UX without introducing a new disclosure surface. The success line is the **only** place the CLI prints a key value, and it never appears in error paths, INFO logs, or the audit log's `details_json`.

**Why the Fernet shape check happens BEFORE settings load.** A bad `--new-key` should fail fast with exit 4 (validation error) without opening the DB or even loading settings. The settings ladder can be slow on first invocation (env-file walk, pydantic validation); fail-fast on the operator's own typo is courteous.

**Why the prompt text says "active customer tax ID(s)" (not just "customer tax IDs").** Tombstoned rows are skipped; making this explicit in the prompt matches the actual behaviour and gives the operator the correct mental model. The `(s)` parenthetical handles the singular/plural transition without conditional grammar.

**Why the abort exit code is 2 (not 1).** Matches `revoke_key_cmd` (keys.py:1221) and `delete_customer_cmd` (customers.py:1206) — UX-DR10 maps 1 to "general" and 2 to "usage error"; a `[y/N]: n` is closer to "operator issued a usage-tier correction" than "general error". Consistency across Destroy-tier verbs is the invariant.

**Why we wrap `new_key` in `SecretStr` for the helper call.** `encrypt_tax_id` and `decrypt_tax_id` both take `SecretStr` as their key parameter — wrapping the raw string at the call site keeps the helper signatures honest and preserves pydantic's masking guarantee ("the value `**********` won't appear in any error trace").

### 3. Module-docstring update for `system.py`

`src/comadre/keys/cli/commands/system.py` top-of-file docstring (lines 1-24) currently enumerates the exit-code contract for cache-status / suspend-sweep / health and explicitly notes "Story 4.2 (`rotate-encryption-key`) will add the final subcommand here". Update to:

- Drop the "Story 4.2 will add" forecast (the verb now exists).
- Add code 4 to the exit-code table: "4 — validation error from `rotate-encryption-key --new-key` Fernet shape check".
- Note that `rotate-encryption-key` is the second source of code 5 (alongside DB errors): "5 — database error from `get_connection` / `_apply_migrations` / `run_suspension_sweep` / health-collection query / encryption-rotation decrypt failure (which rolls back atomically — every row retains its original ciphertext)".

### 4. Docs

- **`README.md`** — "Registry-backed API keys" feature bullet list gains: "Encryption-key rotation (`comadre-keys rotate-encryption-key --new-key <fernet>`) — atomic re-encryption of every active customer's tax ID, transaction-safe, audit-logged."
- **`docs/configuration-reference.md`** — no change (no new env vars).
- **`docs/deployment-guide.md`** — extend the "Key Registry Management" section with a "Rotating the encryption key" subsection (~12 lines) covering: (1) generate a new Fernet key with the documented one-liner; (2) run the rotate verb with `--yes` for automation or interactive for the prompt; (3) edit `.env` on the host to swap `KEY_REGISTRY_ENCRYPTION_KEY` to the new value; (4) `docker compose restart tts-service` to load the new env. Cross-reference Story 4.6's runbook will subsume / link this section.
- **`CLAUDE.md`** — one new entry under "Non-Obvious Gotchas":
  - "**`rotate-encryption-key` re-encrypts only `deleted_at IS NULL` customers**; tombstoned rows hold a zero-length `tax_id_encrypted` BLOB that Fernet would reject (`InvalidToken` on empty input) and that carries no PII to rotate. Don't 'fix' the helper to include tombstones — the skip is correct by design (Story 4.1 contract). The audit-row count reflects active rows only."

### 5. Tests

All tests use the existing fixtures (`tmp_path`, `_reset_consoles_to_buffers` auto-fixture, `CliRunner` from `typer.testing`, `insert_customer` + `insert_api_key` seeds). No new fixture scaffolding.

**`tests/test_keys_db.py`** — add `TestRotateEncryptionKeys` class:
- Happy path with N=3 active customers (mixed CPF / numeric CNPJ / alphanumeric CNPJ): pre-rotation ciphertexts are decryptable by `OLD_KEY` and not by `NEW_KEY`; post-rotation, ciphertexts are decryptable by `NEW_KEY` and not by `OLD_KEY`; canonical plaintext round-trips bit-identical. `result.rows_re_encrypted == 3`, `result.occurred_at` is parseable as ISO-UTC.
- N=0 active customers (empty DB) returns `rows_re_encrypted=0` and still writes the `rotate_encryption_key` audit row with `details={"rows_re_encrypted": 0}`.
- Tombstoned rows are skipped: seed 2 active + 1 tombstoned (zero-length ciphertext) → `result.rows_re_encrypted == 2`, the tombstoned row's `tax_id_encrypted` is unchanged (still `b""`).
- Same-key rotation (old == new): `result.rows_re_encrypted == N`; ciphertexts change byte-wise (Fernet IV randomness) but decrypt to the same canonical form; no error.
- `InvalidToken` on the old key (wrong key supplied): the entire transaction rolls back — every row's `tax_id_encrypted` retains its **original** value (assert by capturing pre-rotation ciphertexts and comparing post-rollback); the `rotate_encryption_key` audit row is NOT present (rolled back too).
- Audit row content: `action='rotate_encryption_key'`, `target_type='registry'`, `target_id IS NULL`, `details_json='{"rows_re_encrypted": N}'`, `actor` matches the supplied `actor` argument, `occurred_at` matches `result.occurred_at`.
- Audit `details` payload passes the `_FORBIDDEN_DETAIL_KEYS` guard (no `cpf`/`cnpj`/`tax_id`/`name`/`email`/`key_plaintext`/`authorization`).
- `TestListCommandsDoNotWrite::test_no_writes_across_all_helpers` — explicitly NOT extended to cover `rotate_encryption_keys` (it IS a write helper; that test catches accidental writes from read-helpers).

**`tests/test_keys_cli_rotate_encryption_key.py`** (new file, matches Story 3.x per-verb naming) — `TestRotateEncryptionKeyCmd`:
- `--new-key <fresh-fernet> --yes` against a 2-customer DB → exit 0, ConfirmationLine matches "Encryption key rotated. Update KEY_REGISTRY_ENCRYPTION_KEY in .env to: <new-key>", post-state is decryptable by the new key and not by the old.
- Interactive `y\n` → exit 0; prompt text on stderr matches "This will re-encrypt 2 active customer tax ID(s) with the new key. Continue?"; same post-state as `--yes`.
- Interactive `n\n` → exit 2; "Aborted." on stderr; DB unchanged (assert pre-rotation ciphertexts intact).
- Empty Enter (default = No) → same as `n` (exit 2, abort, no mutation).
- Empty DB (zero customers) → exit 0, ConfirmationLine still rendered, prompt says "0 active customer tax ID(s)" (the operator sees the scope before confirming a no-op rotation).
- Bad `--new-key` value (truncated, wrong-length base64, non-base64) → exit 4 BEFORE any DB connection is opened (assert via mocking `get_connection` and asserting zero calls); error panel: "Invalid encryption key: --new-key is not a valid Fernet key" + the "Generate with..." hint.
- Missing `KEY_REGISTRY_ENCRYPTION_KEY` (the OLD key) → exit 6 with the standard "Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set" panel.
- `sqlite3.Error` on DB open (simulated via unreadable DB file) → exit 5 with "Database error" panel.
- `sqlite3.Error` on the pre-flight `COUNT(*)` query → exit 5.
- `InvalidToken` from `rotate_encryption_keys` (simulated via corrupted `tax_id_encrypted` BLOB seeded into one row) → exit 5 with "Database error: tax-ID ciphertext failed to decrypt during rotation" + the "current KEY_REGISTRY_ENCRYPTION_KEY value cannot decrypt..." hint; **post-rollback every row retains its original ciphertext** (assert).
- Tombstoned rows are silently skipped: seed 2 active + 1 tombstoned → exit 0, prompt says "2 active customer tax ID(s)", ConfirmationLine printed, the tombstoned row's BLOB is unchanged.
- `--format` flag is NOT accepted (exit 2 on `--format json`).
- INFO log line matches `"Encryption key rotated | rows_re_encrypted=N | occurred_at=YYYY-MM-DDTHH:MM:SSZ"`; `caplog` regex assertion rejects: any 11-/14-digit run, the literal old-key value, the literal new-key value (`gAAAAA...` Fernet prefix), the formatted CPF/CNPJ shape (`123.456.789-09`).
- Audit row written: `action='rotate_encryption_key'`, `target_type='registry'`, `target_id IS NULL`, `details_json='{"rows_re_encrypted": N}'`, `actor='cli:<username>'`. The audit `details_json` field does NOT contain the new key value, the old key value, or any decrypted tax ID (regex assertion).
- The success ConfirmationLine **is** the only stdout/log surface that prints the new key value (regex over `caplog`/`stderr` rejects the new-key string everywhere except the success line).

**`tests/test_keys_audit.py`** — extend the `_FORBIDDEN_DETAIL_KEYS` smoke if not already general: assert the `rotate_encryption_keys` audit-payload dict (`{"rows_re_encrypted": N}`) passes the forbidden-keys check.

### 6. Grep checks (for the implementer's pre-commit pass)

Run before claiming the story done:

- `rg "fernet\.decrypt" src/` — EXACTLY ONE hit in `src/comadre/keys/crypto.py::decrypt_tax_id`. Any other hit is a security regression.
- `rg "Fernet\(" src/` — EXACTLY THREE hits: (a) `keys/crypto.py::encrypt_tax_id`, (b) `keys/crypto.py::decrypt_tax_id`, (c) `config.py::_validate_fernet_key_shape` (existing pre-Story 4.2). The new CLI verb's Fernet shape check imports `Fernet` from `cryptography.fernet` but uses it only for the `Fernet(new_key.encode())` validation — that's the fourth instance, expected. So expect EXACTLY FOUR hits after this story.
- `rg "HTTPException" src/` — ZERO hits (non-regression contract; FR51).
- `rg "rotate_encryption_key|rotate-encryption-key" src/` — present in `db.py` (helper), `cli/commands/system.py` (verb + audit-action string).
- `rg "tax_id_encrypted" src/comadre/keys/cli/` — exactly two hits, both in `cli/commands/customers.py` (Story 4.1 — `create_customer_cmd` INSERT and `export_customer_cmd` attribute access). The new system.py verb does NOT name the column directly — it goes through the `rotate_encryption_keys` helper, which is the encapsulation boundary.
- `rg "docs_url|redoc_url|openapi_url" src/comadre/main.py` — all three are `None` (FR47; non-regression).
- `uv run ruff check . && uv run mypy src/ && uv run pytest` — all green.

## Acceptance Criteria

### AC1 — `rotate-encryption-key --new-key <fresh-fernet>` re-encrypts every active customer atomically

**Given** a DB seeded with 3 active customers (mixed CPF / numeric CNPJ / alphanumeric CNPJ) whose `tax_id_encrypted` BLOBs were created with the current `KEY_REGISTRY_ENCRYPTION_KEY` (`OLD_KEY`).

**When** the operator runs `comadre-keys rotate-encryption-key --new-key <NEW_KEY> --yes`.

**Then** stdout shows: `Encryption key rotated. Update KEY_REGISTRY_ENCRYPTION_KEY in .env to: <NEW_KEY>`.

**And** exit code 0.

**And** querying the DB directly: every active customer's `tax_id_encrypted` is now decryptable by `NEW_KEY` (yields the original canonical form bit-identical) and **not** by `OLD_KEY` (raises `InvalidToken`).

**And** one new `audit_log` row is present: `action='rotate_encryption_key'`, `target_type='registry'`, `target_id IS NULL`, `details_json='{"rows_re_encrypted": 3}'`, `actor='cli:<username>'`, `occurred_at` matches the structured INFO log line.

### AC2 — Interactive `y` runs the rotation; interactive `n` (or empty Enter) aborts

**Given** the same seed as AC1.

**When** the operator runs `comadre-keys rotate-encryption-key --new-key <NEW_KEY>` and answers `y` to the prompt.

**Then** the prompt on stderr reads: `This will re-encrypt 3 active customer tax ID(s) with the new key. Continue? [y/N]:`.

**And** the same AC1 success outcome: exit 0, ConfirmationLine, post-state rotated.

**Given** the same seed.

**When** the operator answers `n` (or presses Enter without typing).

**Then** stderr shows `Aborted.` and exit code 2.

**And** the DB is unchanged — every row's `tax_id_encrypted` is bit-identical to the pre-prompt state; no `rotate_encryption_key` audit row is added.

### AC3 — Bad `--new-key` is rejected upfront (exit 4) without touching the DB

**Given** any registry state.

**When** the operator runs `comadre-keys rotate-encryption-key --new-key NOT-A-VALID-FERNET-KEY --yes`.

**Then** stderr shows an ErrorDisplay titled `Invalid encryption key: --new-key is not a valid Fernet key` with the "Generate a fresh Fernet key with: python -c '...'" hint.

**And** exit code 4.

**And** the DB is not opened (verifiable: monkeypatch `get_connection` to fail on call → the error never surfaces because the function is never called).

**And** the operator-supplied invalid `--new-key` value is **not** echoed in the error message or hint (NFR16 anti-enumeration).

### AC4 — Mid-rotation `InvalidToken` rolls back atomically — every row retains its original encryption

**Given** an active customer whose `tax_id_encrypted` was hand-corrupted to a token that does not decrypt under the current `KEY_REGISTRY_ENCRYPTION_KEY` (simulating partial schema drift).

**When** the operator runs `comadre-keys rotate-encryption-key --new-key <NEW_KEY> --yes`.

**Then** stderr shows an ErrorDisplay titled `Database error: tax-ID ciphertext failed to decrypt during rotation` with the "current KEY_REGISTRY_ENCRYPTION_KEY value cannot decrypt..." hint.

**And** exit code 5.

**And** every row's `tax_id_encrypted` remains bit-identical to the pre-rotation state (assert by capturing all ciphertexts before the run and comparing after — including the rows that successfully decrypted-and-re-encrypted in the failed transaction, which must rollback to their originals too).

**And** no `rotate_encryption_key` audit row is present (rolled back).

### AC5 — Tombstoned rows are skipped; the count and prompt reflect active rows only

**Given** a DB with 2 active customers and 1 tombstoned customer (`deleted_at IS NOT NULL`, `tax_id_encrypted = b""` per Story 4.1's tombstone contract).

**When** the operator runs `comadre-keys rotate-encryption-key --new-key <NEW_KEY>` and is shown the prompt.

**Then** the prompt reads: `This will re-encrypt 2 active customer tax ID(s) with the new key. Continue? [y/N]:`.

**And** on confirmation: the 2 active rows are re-encrypted under `NEW_KEY`; the tombstoned row's `tax_id_encrypted` is unchanged (still `b""`); `result.rows_re_encrypted == 2`; the audit row records `details_json='{"rows_re_encrypted": 2}'`.

### AC6 — Empty DB (zero active customers) succeeds with `rows_re_encrypted=0`

**Given** a DB with zero customers (or only tombstoned customers).

**When** the operator runs `comadre-keys rotate-encryption-key --new-key <NEW_KEY> --yes`.

**Then** exit code 0; ConfirmationLine matches AC1's grammar (no special-case rendering); audit row carries `details_json='{"rows_re_encrypted": 0}'`.

### AC7 — Missing `KEY_REGISTRY_ENCRYPTION_KEY` exits 6

**Given** `KEY_REGISTRY_ENCRYPTION_KEY` (the OLD key) is unset.

**When** the operator runs `comadre-keys rotate-encryption-key --new-key <NEW_KEY> --yes`.

**Then** stderr shows the standard "Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set" panel; exit code 6.

### AC8 — INFO log is PII-austere; the only place the new key value appears is the success ConfirmationLine

**Given** AC1's seed.

**When** the rotation runs.

**Then** the structured INFO log line contains: `Encryption key rotated | rows_re_encrypted=3 | occurred_at=YYYY-MM-DDTHH:MM:SSZ`.

**And** a regex applied to the captured `caplog` rejects: any 11-/14-digit run, any `123.456.789-09`-shaped formatted tax ID, the literal `OLD_KEY` value, the literal `NEW_KEY` value, the Fernet prefix `gAAAAA`.

**And** `result.stdout` (which is where the ConfirmationLine lands) contains `NEW_KEY` exactly once (in the success line); `result.stderr` contains `NEW_KEY` zero times (never in error panels, never in prompts).

**And** the `audit_log.details_json` for the new row contains `{"rows_re_encrypted": 3}` only — no key material, no tax ID material.

### AC9 — `--format` is NOT a flag; passing it exits 2

**Given** any state.

**When** the operator runs `comadre-keys rotate-encryption-key --new-key <NEW_KEY> --format json`.

**Then** Typer rejects the unknown option; exit code 2.

### AC10 — Read-only invariant on non-target surfaces (regression guard)

**Given** the Story 4.2 diff.

**When** `git diff --name-only master...HEAD` is run.

**Then** the set excludes: `src/comadre/api.py`, `src/comadre/main.py`, `src/comadre/rate_limit.py`, `src/comadre/keys/auth.py`, `src/comadre/keys/cache.py`, `src/comadre/health.py` (the HTTP `/health` endpoint), `src/comadre/counters.py`, `src/comadre/keys/migrations/`, `src/comadre/keys/crypto.py` (Story 4.1's `decrypt_tax_id` is consumed unchanged). Any hit on these paths is a regression of the non-regression contract.

**And** `pyproject.toml` shows ZERO new dependencies (no addition under `[project.dependencies]` or `[dependency-groups]`).

### AC11 — `comadre-keys --help` lists the new verb

**Given** the installed CLI.

**When** the operator runs `comadre-keys --help`.

**Then** `rotate-encryption-key` appears in the subcommand list with the one-line docstring summary.

**And** `comadre-keys rotate-encryption-key --help` shows the realistic example (UX-DR15): `comadre-keys rotate-encryption-key --new-key gAAAAA... --yes`.

### AC12 — `_FORBIDDEN_DETAIL_KEYS` defense-in-depth on the audit payload

**Given** the `rotate_encryption_keys` helper's audit-row construction.

**When** the audit payload dict is built (`{"rows_re_encrypted": N}`).

**Then** the dict passes `audit._assert_no_forbidden_keys` (no `cpf`, `cnpj`, `tax_id`, `name`, `email`, `key_plaintext`, or `authorization` keys present).

**And** a unit test asserts this directly by calling `_assert_no_forbidden_keys` on the constructed dict, independent of the broader helper-call test (caught by `audit.log_event` in practice; the unit test makes the contract explicit at the helper-design boundary).

## Tasks / Subtasks

- [x] **Task 1 — New DB helper `rotate_encryption_keys`** (AC1, AC4, AC5, AC6, AC12)
  - [x] 1.1 Append `RotateEncryptionKeysResult` dataclass + `rotate_encryption_keys` helper to `src/comadre/keys/db.py` after `delete_customer_hard`.
  - [x] 1.2 Imports inside the helper: lazy `from comadre.keys.audit import log_event` + lazy `from comadre.keys.crypto import decrypt_tax_id, encrypt_tax_id` (matches the `delete_customer_hard` lazy-import pattern that avoids module-load cycles).
  - [x] 1.3 `TestRotateEncryptionKeys` added to `tests/test_keys_db.py` — 7 subcases: happy path (3 mixed-kind customers) / N=0 empty DB / tombstone-skip (2 active + 1 tombstoned) / same-key idempotent / `InvalidToken` rollback (every row retains original) / audit-row content / forbidden-keys-guard compliance.

- [x] **Task 2 — New CLI verb `rotate-encryption-key`** (AC1–AC9, AC11)
  - [x] 2.1 Append `rotate_encryption_key_cmd` to `src/comadre/keys/cli/commands/system.py` after `health_cmd`.
  - [x] 2.2 Add module-level constants `_ROTATE_KEY_BAD_FERNET_HINT` + `_ROTATE_KEY_DECRYPT_FAILED_HINT`.
  - [x] 2.3 Extend the `system.py` import block: add `rotate_encryption_keys` to the `comadre.keys.db` import + add `from cryptography.fernet import Fernet, InvalidToken` + add `from pydantic import SecretStr` + `click` + `get_cli_actor` + `stderr_console`.
  - [x] 2.4 `tests/test_keys_cli_rotate_encryption_key.py` created with 14 subcases covering AC1 (--yes), AC2 (interactive y/n/Enter), AC3 (bad Fernet shape — pre-DB), AC4 (InvalidToken rollback), AC5 (tombstone skip), AC6 (empty DB), AC7 (missing OLD key), AC8 (PII-austere log + new-key only on success line), AC9 (no --format), AC11 (--help text).
  - [x] 2.5 `rg "fernet\.decrypt" src/` grep invariant passes — exactly one hit in `crypto.py::decrypt_tax_id`.
  - [x] 2.6 `rg "Fernet\(" src/` returns exactly four hits (encrypt_tax_id, decrypt_tax_id, config._validate_fernet_key_shape, the new CLI shape check).

- [x] **Task 3 — Module-docstring updates** (AC11, maintenance)
  - [x] 3.1 `system.py` top-of-file docstring: drop the "Story 4.2 will add the final subcommand" forecast; add code 4 to the exit-code table; extend code 5 description to mention the encryption-rotation decrypt failure.
  - [x] 3.2 `comadre-keys --help` and `comadre-keys rotate-encryption-key --help` verified to render the expected text.

- [x] **Task 4 — Docs**
  - [x] 4.1 `README.md` feature-bullet gains the encryption-rotation entry.
  - [x] 4.2 `docs/deployment-guide.md` gains the "Rotating the encryption key" subsection under "Key Registry Management" (placed alongside the LGPD operator procedures).
  - [x] 4.3 `CLAUDE.md` gains one new "Non-Obvious Gotcha": `rotate-encryption-key` skips tombstoned rows by design, success-line echo is the sole key-material surface, exit code 4 added to the system.py ladder.

- [ ] **Task 5 — Integration smoke on 10.10.10.207** (deploy-time acceptance — operator-VPS Task, deferred to deploy)
  - [ ] 5.1 Deploy the branch to 10.10.10.207 staging.
  - [ ] 5.2 Seed 2 customers via `comadre-keys create-customer ...`.
  - [ ] 5.3 Generate a fresh Fernet key with `python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"`.
  - [ ] 5.4 Run `comadre-keys rotate-encryption-key --new-key <fresh> --yes`; verify ConfirmationLine + exit 0.
  - [ ] 5.5 Edit `~/comadre/.env` to swap `KEY_REGISTRY_ENCRYPTION_KEY` to the new value; `docker compose restart tts-service`.
  - [ ] 5.6 Verify post-restart: `comadre-keys export-customer cust_... --format json` succeeds (decrypts under the new key) and `curl https://<host>/v1/audio/speech ...` succeeds with each customer's API key (the auth path is unaffected — keys did not rotate).
  - [ ] 5.7 Verify audit trail: `sqlite3 data/keys/registry.db "SELECT action, actor, details_json FROM audit_log WHERE action = 'rotate_encryption_key'"` returns one row with `{"rows_re_encrypted": 2}`.

- [x] **Task 6 — Final quality gate**
  - [x] 6.1 `uv run ruff check .` → zero findings.
  - [x] 6.2 `uv run mypy src/` → zero findings under strict mode.
  - [x] 6.3 `uv run pytest` → full suite green (1391 passed).
  - [x] 6.4 `uv run pre-commit run --all-files` → zero hook failures.
  - [x] 6.5 Grep invariants from §6 — `fernet.decrypt` exactly one hit; `Fernet(` exactly four hits; `HTTPException` only a pre-existing docstring reference in `main.py:250` (not a raise/import, not introduced by this story); `docs_url/redoc_url/openapi_url=None` all pass.

### Review Findings

Code review 2026-04-19 — three adversarial reviewers (Blind Hunter, Edge Case Hunter, Acceptance Auditor). 6 patches, 6 deferred, ~14 dismissed as noise.

- [x] [Review][Patch] `assert settings.key_registry_encryption_key is not None` is stripped by `python -O` / `PYTHONOPTIMIZE=1` [src/comadre/keys/cli/commands/system.py:535] — replaced the `assert` with an explicit `if ... is None: render_error(...); raise typer.Exit(code=6)` so the exit-6 contract survives optimized runs.
- [x] [Review][Patch] Unexpected exceptions from the helper (TypeError, ValueError from audit guard, KeyboardInterrupt during the rotation loop or confirm prompt) surface as raw tracebacks [src/comadre/keys/cli/commands/system.py:543-551] — added `except KeyboardInterrupt` on both the confirm prompt and the helper call (clean "Aborted." + `typer.Exit(code=130)`) plus a defensive `except Exception as exc` after the sqlite3 branch that maps unexpected failures to `render_error("Unexpected rotation failure", ...) + typer.Exit(code=5)`.
- [x] [Review][Patch] Rich `render_confirmation` wraps the 44-char new-key across two lines on 80-col terminals [src/comadre/keys/cli/commands/system.py:568-571] — switched the success line from `render_confirmation(...)` to `stdout_console().print(..., soft_wrap=True)` so Rich never splits the Fernet key across a wrap boundary.
- [x] [Review][Patch] `rows_re_encrypted += 1` increments unconditionally instead of via UPDATE `.rowcount` [src/comadre/keys/db.py:714-719] — now `rows_re_encrypted += cursor.rowcount` so a concurrent tombstone between the SELECT and the UPDATE cannot overstate the audit total.
- [x] [Review][Patch] AC12 test asserts against `_FORBIDDEN_DETAIL_KEYS` set-containment instead of calling `_assert_no_forbidden_keys()` [tests/test_keys_db.py:4480] — the `TestRotateEncryptionKeys::test_audit_details_dict_passes_forbidden_keys_guard` assertion now calls `_assert_no_forbidden_keys(details)` directly, exercising the guard's nested-mapping recursion as the spec pinned.
- [x] [Review][Patch] Extra parentheses wrapping a single-arg `render_error` title [src/comadre/keys/cli/commands/system.py:544-547] — collapsed to a plain string literal.
- [x] [Review][Defer] Pre-count vs helper-count race under a concurrent `tts-service` writer [src/comadre/keys/cli/commands/system.py:540-546 vs src/comadre/keys/db.py:707-709] — deferred, accepted-by-spec. §Dev-Notes explicitly states "the helper's actual count is the audit-row source of truth". Worth revisiting if Story 4.x ever documents multi-operator rotation.
- [x] [Review][Defer] `bytes(row["tax_id_encrypted"])` raises `TypeError` not caught by CLI if column is ever NULL [src/comadre/keys/db.py:712] — deferred, schema has `NOT NULL`. Defense in depth only relevant if a future migration weakens the constraint.
- [x] [Review][Defer] Confirmation prompt does not identify the target DB path [src/comadre/keys/cli/commands/system.py:555-562] — deferred, additive UX. Operators with multiple registries (staging / prod) cannot distinguish at confirm time; consider including `{settings.key_registry_db_path}` in the prompt in a future hardening pass.
- [x] [Review][Defer] Non-canonical plaintext silently re-encrypted (no post-decrypt shape validation) [src/comadre/keys/db.py:712-718] — deferred, out-of-scope. Data-quality drift is a separate concern; rotation is supposed to preserve bytes, not audit them.
- [x] [Review][Defer] Docker log driver captures the stdout success line containing the new key [docs/deployment-guide.md:506-526] — deferred, runbook concern for Story 4.6. Add a "prune container logs after rotation" caveat there; the echo itself is epic-AC-verbatim and cannot be removed.
- [x] [Review][Defer] DB-level rollback test uses wrong-old-key (fails at row 1) rather than mid-loop corruption at row 2 of 3 [tests/test_keys_db.py:4364] — deferred, the CLI test at `test_keys_cli_rotate_encryption_key.py::TestRotateEncryptionKeyInvalidToken.test_corrupted_ciphertext_rolls_back_every_row` already exercises mid-loop rollback via SQLite rowid ordering. Tightening the DB test is additive.

## Dev Notes

### Import-graph placement

- `src/comadre/keys/db.py` (Story 4.2 extension): `RotateEncryptionKeysResult` + `rotate_encryption_keys` sit alongside `DeleteCustomerResult` + `delete_customer_hard`. The helper lazy-imports `log_event` (existing pattern) and `decrypt_tax_id`/`encrypt_tax_id` (new — but the pattern is identical: deferred to function-call time to avoid `db → crypto → ... → db` cycles in case future refactors reshape the dep graph; today the cycle does not exist but the lazy import is cheap insurance).
- `src/comadre/keys/cli/commands/system.py` (Story 4.2 extension): `rotate_encryption_key_cmd` joins `cache_status_cmd`, `suspend_sweep_cmd`, `health_cmd`. Imports `Fernet` + `InvalidToken` from `cryptography.fernet` (new for this module — `Fernet` is used only for the upfront `--new-key` shape check, and `InvalidToken` for the rollback exception path); `SecretStr` from `pydantic` (new — wraps `--new-key` for the helper signature); `rotate_encryption_keys` from `keys.db` (new in this story).
- `src/comadre/keys/crypto.py` is **NOT modified** — Story 4.2 consumes the existing `encrypt_tax_id` (Story 1.1) and `decrypt_tax_id` (Story 4.1) unchanged.

### Why the success line echoes the new key value (epic AC verbatim)

The epic AC pins the success ConfirmationLine: `"Encryption key rotated. Update KEY_REGISTRY_ENCRYPTION_KEY in .env to: <new-key>"`. The CLI's general security boundary says encryption keys are "never echoed in logs, never included in error hints, never printed by the CLI" (prd.md:698). These are reconciled by treating the success line as the **single, deliberate, operator-facing exception**: the operator just supplied the new key on the command line (already in shell history); the success-line echo is a copy-paste hint for the immediate `.env` swap that closes the rotation procedure. The new-key value never appears anywhere else: not in INFO logs, not in error panels, not in the audit `details_json`, not in the prompt text. The grep invariant (AC8 — "the only place the new key value appears in stdout/stderr/log is the success line") is the load-bearing assertion.

If a future operator asks for a `--no-echo-success` flag (e.g., for compliance environments where even shell-history exposure of the new key is unacceptable), that is a Story 4.x extension — not a 4.2 deviation. The PRD pins the verbose success line; we ship as specified.

### Why we do NOT also generate the new key on the operator's behalf

`rotate-encryption-key` could plausibly accept `--generate` (or default to generating internally if `--new-key` is absent) and print the freshly-minted key as part of the success line. The epic AC does not specify this. Reasons not to add it in 4.2:

1. **Single responsibility.** The verb's job is rotation, not key generation. The Fernet generation one-liner is documented in `bootstrap.yml`, in the `--help` text, and in the deployment guide — operators who run rotation already know how to generate keys.
2. **`--new-key` becomes optional, breaking the AC contract.** The epic AC says `--new-key <fernet>`, implying required. Making it optional creates a footgun: an operator who omits the flag would generate a fresh key they then have to retrieve from the success line — vs. their explicit pre-generated key being more obvious.
3. **Generation in CLI logic widens the attack surface.** `Fernet.generate_key()` reads from the OS RNG; if a future CI run contaminates the test path, a generated-then-printed key has different forensic semantics than an operator-supplied one. Keep generation outside the CLI's responsibility.

If `--generate` is requested in a future hardening pass, it is additive — `--new-key` stays required-by-default, and `--generate` becomes a mutually-exclusive sibling that prints the minted key into the success line.

### Why no `target_id` and `target_type='registry'` on the audit row

The audit_log schema permits both nullable. `target_type='registry'` (string) is preferable to `NULL` because:
- It lets the operator grep audit events by category: `WHERE target_type = 'registry'` returns rotation events alongside future registry-wide actions (e.g., 4.x add-on bulk operations).
- It preserves the "every audit row identifies what it touched" convention even when there is no single target to point at.

`target_id IS NULL` is correct because rotation does not target any single customer or key — it touches every active customer's `tax_id_encrypted`. Synthesizing a fake target_id (`"all-customers"`, `"registry"`) would mislead future grep operators into treating it as a real ID.

### Why a single `actor` parameter (not `cli:` hard-coded)

`get_cli_actor()` returns `"cli:<unix-username>"` (or `"cli:unknown"` on getpass failure). Passing it as a parameter (rather than calling it inside the helper) keeps the helper testable without monkeypatching `os.getlogin()` and matches the convention every other audit-paired helper uses (`insert_customer`, `delete_customer_hard`, `update_customer`, etc., all take `actor` as a kwarg).

### Why the prompt count is computed via a separate `COUNT(*)` query (not from the materialized `.fetchall()`)

The pre-flight `COUNT(*)` runs **before** the confirmation prompt and **outside** the transaction. The materialization happens **inside** the transaction in the helper. Doing the count inside the helper would mean either:
- Running the rotation, then prompting (defeats the prompt's purpose), OR
- Opening a sub-transaction just for the count (overkill for a one-row aggregate).

The race window between pre-flight count and helper SELECT is a non-issue on the single-writer CLI: only one operator runs `rotate-encryption-key` at a time; `create-customer` (the only verb that adds active rows) is itself operator-serial. If the count drifts by ±1 between prompt and helper, the helper's actual count is the audit-row source of truth.

### NFR35 performance budget

`rotate_encryption_keys` is O(N) on active customers, where each iteration is one decrypt + one encrypt + one UPDATE. Fernet operations are sub-millisecond; SQLite UPDATE-by-PK with the `customer.id` PK index is sub-millisecond. **Total per-row cost: ~2ms.** A 1000-customer DB rotates in under 5 seconds; a 100K-customer deployment in under 5 minutes. Both well within operational tolerance for what is fundamentally a deliberate, infrequent operator action (key rotation is not on the request hot path).

The bigger risk is **transaction holding time**: while the rotation is open, every write attempt by another process (e.g., a parallel `create-customer` from a second operator session) waits on `busy_timeout=5000`. For 100K customers this could cause short-lived 5s waits on concurrent writes. Documented as a runbook note in 4.6: "rotate during a maintenance window if you have >10K customers".

### Test-flake avoidance

- Clock-seam: `_utcnow_iso()` is called once in the helper (for `occurred_at`); tests freeze via `monkeypatch.setattr("comadre.keys.db._utcnow_iso", lambda: "2026-04-19T00:00:00Z")` when asserting the audit row's `occurred_at` literal. Same pattern as Story 3.3 / 4.1.
- Prompt input: `CliRunner().invoke(app, [...], input="y\n")` / `input="n\n"` / `input=""` (Enter-without-typing = abort).
- `Fernet.generate_key()` for the test fresh new-key: generate once per test in a fixture; pass the same value to `--new-key` and to the post-state decrypt assertions. Never reuse a hard-coded key across tests (would mask key-swap bugs).
- Pre-rotation ciphertext capture for the AC4 rollback assertion: `pre = {row["id"]: bytes(row["tax_id_encrypted"]) for row in conn.execute("SELECT id, tax_id_encrypted FROM customer").fetchall()}` — capture before the failing rotation, compare every byte after.
- The corrupted-ciphertext seed for AC4: `conn.execute("UPDATE customer SET tax_id_encrypted = ? WHERE id = ?", (b"corrupted-non-fernet-bytes", customer_id))` — this is an intentional test-time corruption, not a production-realistic scenario. The point is to exercise the rollback path; the production-realistic trigger is "operator already swapped `.env` without running rotate first" (the gotcha the epic AC explicitly calls out: "the operator changes `.env` without running this command — all encrypted fields become unreadable").

### Project Structure Notes

- **Alignment with unified project structure (paths, modules, naming)**
  - Helper naming: `rotate_encryption_keys` (plural — operates on every customer's row, parallel to `run_suspension_sweep`'s plural noun for a multi-row operation).
  - CLI verb: `rotate-encryption-key` (singular — names the operation, not the rows; matches PRD spec verbatim, prd.md:982).
  - Audit action: `rotate_encryption_key` (singular, matches the verb; in the architecture's audit-action list at arch.md:323 already enumerated as expected).
  - File placement: helper in `keys/db.py`, verb in `keys/cli/commands/system.py`, tests in `tests/test_keys_db.py` + new `tests/test_keys_cli_rotate_encryption_key.py`. No new modules created.

- **Detected conflicts or variances (with rationale)**
  - The success ConfirmationLine deliberately echoes the new-key value (epic AC verbatim) — this is the single operator-facing exception to the "CLI never prints encryption keys" general rule. Documented in §Dev-Notes.
  - The new CLI verb diverges from Story 4.1's pattern by **inlining `Fernet(new_key.encode())` for the shape check** instead of factoring it through `crypto.py`. This is intentional: the check operates on the operator-supplied new-key value, never on stored ciphertext, and never produces or consumes any tax-ID material — it is purely a validation of the user-supplied parameter, not a crypto operation in the architecture's "Fernet boundary" sense. The grep invariant `rg "fernet\.decrypt" src/` continues to return exactly one hit.

### Testing standards

- DB / crypto tests use `tmp_path` for the SQLite file + `get_connection` + `_apply_migrations`. Seed customers via `insert_customer` (never hand-roll INSERTs). Pre-rotation Fernet keys come from a fixture that calls `Fernet.generate_key()` once per test invocation.
- CLI tests use `CliRunner` from `typer.testing` + the `_reset_consoles_to_buffers` auto-fixture pattern (copy verbatim from `test_keys_cli_delete_customer.py` — most recent canonical Destroy-tier template).
- `caplog` captures INFO log lines for AC8 PII assertions.
- The success-line "new key appears here and only here" test (AC8) requires capturing both `result.stdout`, `result.stderr`, and `caplog.text`, then asserting `new_key in result.stdout` AND `new_key not in result.stderr` AND `new_key not in caplog.text` AND querying `audit_log.details_json` for absence-of-new-key.
- Audit-row read: `conn.execute("SELECT * FROM audit_log WHERE action = 'rotate_encryption_key'").fetchone()` post-helper-call; assert the row's columns one-by-one.

### Deferred work to flag at story close

- **`--new-key` from stdin / file** (e.g., `--new-key -` or `--new-key-from-file <path>`). Reduces shell-history exposure of the new key value. Out of 4.2 scope; epic AC pins the inline-value form.
- **`--generate` flag** that mints a fresh key inside the CLI and prints it via the success line. Out of 4.2 scope; the inline `--new-key` is the canonical path.
- **`--dry-run` flag** that previews the rotation count without writing. Lower value than `suspend-sweep --dry-run` (which previews the operator-controllable list of rows that will be touched); a rotation preview just counts active customers, which `comadre-keys list-customers` already shows. Out of 4.2 scope.
- **Maintenance-window concurrency note** for >10K-customer deployments. Surfaces as a documentation entry in Story 4.6 (operator runbook), not a code change.
- **Validate `KEY_REGISTRY_ENCRYPTION_KEY` against `tax_id_encrypted` decryptability at startup** (not just at command-time). If the operator swapped `.env` without running rotate, every export / future rotate will fail. A startup self-check in `main.py`'s lifespan that decrypts one canary row would surface the mismatch on `docker compose restart` instead of on the first export attempt. Out of 4.2 scope; candidate for a future hardening story.

### References

- Epic 4 Story 4.2 scope — `_bmad-output/planning-artifacts/epics.md:786-817`
- FR36 (atomic re-encryption) — `_bmad-output/planning-artifacts/prd.md:1174`
- NFR10 (CPF/CNPJ encrypted at rest with Fernet) — `_bmad-output/planning-artifacts/prd.md:1214`
- NFR15 (PII-austere INFO logs) — `_bmad-output/planning-artifacts/prd.md:1219`
- NFR16 (no error-hint echo of operator-supplied invalid input) — `_bmad-output/planning-artifacts/prd.md:1220`
- UX-DR11 (Destroy-tier `--yes` pattern) — `_bmad-output/planning-artifacts/epics.md:196`
- UX-spec destructive command grammar + `rotate-encryption-key` Destroy-tier listing — `_bmad-output/planning-artifacts/ux-design-specification.md:894, 162`
- Architecture Fernet encryption pattern — `_bmad-output/planning-artifacts/architecture.md:394-406`
- Architecture "no other module touches Fernet directly" — `_bmad-output/planning-artifacts/architecture.md:637`
- Architecture audit-action naming convention (includes `rotate_encryption_key`) — `_bmad-output/planning-artifacts/architecture.md:322-327`
- Architecture single-transaction for multi-row CLI ops — `_bmad-output/planning-artifacts/architecture.md:474-478`
- Architecture CLI exit-code contract — `_bmad-output/planning-artifacts/architecture.md:421`
- PRD CLI specification for `rotate-encryption-key` — `_bmad-output/planning-artifacts/prd.md:982`
- PRD encryption-key handling rules — `_bmad-output/planning-artifacts/prd.md:698`
- PRD "rotation without re-encrypting existing rows" risk mitigation — `_bmad-output/planning-artifacts/prd.md:757`
- `decrypt_tax_id` (consumed unchanged from Story 4.1) — `src/comadre/keys/crypto.py:81-97`
- `encrypt_tax_id` (consumed unchanged from Story 1.1) — `src/comadre/keys/crypto.py:75-78`
- `delete_customer_hard` (single-transaction multi-row mutation template) — `src/comadre/keys/db.py:555-637`
- `delete_customer_cmd` (Destroy-tier CLI template) — `src/comadre/keys/cli/commands/customers.py:1084-1238`
- `health_cmd` (system.py CLI template) — `src/comadre/keys/cli/commands/system.py:321-411`
- `load_settings_and_tz` (shared exit-6 ladder) — `src/comadre/keys/cli/commands/keys.py:738-781`
- `audit.py::log_event` + `_FORBIDDEN_DETAIL_KEYS` (PII hygiene guard) — `src/comadre/keys/audit.py:23-43, 64-105`
- `get_cli_actor` (actor-string resolver) — `src/comadre/keys/audit.py:50-61`
- `system.py` module docstring (the one this story rewrites) — `src/comadre/keys/cli/commands/system.py:1-24`
- `bootstrap.yml` Fernet generation one-liner (referenced in `--help` text + hint) — `deploy/ansible/playbooks/bootstrap.yml:4-7, 47-54`
- CLAUDE.md tombstone gotcha (`tax_id_encrypted = X''` for tombstoned rows) — `CLAUDE.md`

## Questions for Operator (please confirm before dev-story)

> All questions have recommended answers. In auto-mode, apply the recommended answer; if any run hits a disagreement, reopen as a deferred-work entry.

1. **`--new-key` stdin/file alternative.** The epic AC pins `--new-key <value>` (inline). Stdin (`--new-key -`) or file (`--new-key-from-file <path>`) would reduce shell-history exposure of the key value. Recommend **inline only** — matches epic AC verbatim, single supported path, simpler `--help` text. Defer stdin/file as a future Story 4.x add-on.

2. **`--generate` to mint a fresh key in-process.** Could be added as a sibling to `--new-key`. Recommend **not in 4.2** — single-responsibility (rotation, not generation), epic AC does not specify, and the Fernet generation one-liner is documented in `bootstrap.yml` and the `--help` text. Defer if a hardening pass requests it.

3. **Success line echoes the new-key value (epic AC verbatim).** Conflicts loosely with the "CLI never prints encryption keys" general rule. Recommend **echo as specified** — operator just typed the value (already in shell history); the success-line echo is a copy-paste hint for the immediate `.env` swap. Document the deliberate exception in `CLAUDE.md` if a code reviewer flags it.

4. **`target_type='registry'` vs `target_type=NULL` on the audit row.** Both are schema-valid. Recommend **`'registry'`** — preserves the "every audit row identifies what it touched" convention; lets operators grep registry-level events by category in future audit-tooling.

5. **Prompt count grammar `2 active customer tax ID(s)` vs `2 active customer tax IDs` / `1 active customer tax ID`.** The `(s)` parenthetical handles singular/plural without conditional grammar. Recommend **the `(s)` form** — matches the `delete_customer_cmd` "(N key(s))" pattern verbatim; consistency across Destroy-tier verbs is the invariant.

6. **Rotation atomicity strategy: single transaction over the full row set vs per-row sub-transactions with a checkpoint table.** Single transaction is simpler and gives free rollback; per-row would survive partial-completion crashes but would need a new `rotation_progress` table. Recommend **single transaction** — matches FR36's "no window of unreadable data" guarantee, no schema change, sub-second performance for any deployment up to 10K customers. Document the ">10K customer maintenance-window note" in 4.6's runbook.

7. **Encryption-key shape validation: full `Fernet(new_key.encode())` vs `len(new_key) == 44 and base64.urlsafe_b64decode(new_key)`.** The first is authoritative (catches every Fernet-rejection case); the second is faster but might let through edge cases. Recommend **full `Fernet(new_key.encode())`** — sub-millisecond cost, authoritative, exception is `(ValueError, TypeError)` only; matches the existing `config._validate_fernet_key_shape` pattern.

## Dev Agent Record

### Agent Model Used

- Claude Opus 4.7 (1M context) via Claude Code.

### Debug Log References

- None required. The TDD cycle landed tests + code cleanly on the first
  implementation; the only iteration was a stray missing `finally:`
  block in `test_keys_db.py` (caught by the first test-collection run)
  and three ruff findings (unused `stdout, stderr` unpack, import
  organisation, a stale quoted annotation). No production code paths
  needed debug investigation.

### Completion Notes List

- DB helper `rotate_encryption_keys` (db.py:656) holds one transaction
  over a materialised SELECT of every `deleted_at IS NULL` customer,
  decrypts under `old_key`, re-encrypts under `new_key`, UPDATEs in
  place, writes one `rotate_encryption_key` audit row with
  `target_type='registry'`, `target_id=NULL`,
  `details_json='{"rows_re_encrypted": N}'`, and returns a
  `RotateEncryptionKeysResult` carrying the count and the audit
  `occurred_at`.
- Mid-iteration failure (`InvalidToken` on a corrupted ciphertext,
  `sqlite3.Error`, any exception) rolls the whole transaction back —
  every row retains its original ciphertext and no audit row is
  written. Verified by `TestRotateEncryptionKeys.test_invalid_old_key_rolls_back_every_row`
  and by `TestRotateEncryptionKeyInvalidToken.test_corrupted_ciphertext_rolls_back_every_row`
  (both capture pre-rotation ciphertexts and assert byte-identity after
  rollback).
- Tombstoned rows are skipped by the `WHERE deleted_at IS NULL` filter
  so `Fernet.decrypt(b"")` never fires; their zero-length BLOB stays
  byte-identical, and the audit count reflects active rows only
  (verified by `test_skips_tombstoned_rows` /
  `test_tombstoned_rows_are_skipped`).
- CLI verb `rotate_encryption_key_cmd` (system.py:440) follows the
  Destroy-tier template verbatim: Fernet shape check → exit 4 (before
  settings/DB); `load_settings_and_tz` → exit 6 (missing old key or bad
  TZ); `get_connection` + `_apply_migrations` → exit 5; pre-flight
  `COUNT(*) WHERE deleted_at IS NULL` for the prompt preview; confirm
  gate with `abort=True` on `--yes is False` → exit 2 on click.Abort;
  helper call with `InvalidToken` → exit 5 / `sqlite3.Error` → exit 5;
  DB close; PII-austere INFO log
  (`Encryption key rotated | rows_re_encrypted=N | occurred_at=...`);
  success ConfirmationLine echoing the new key as the `.env` hint.
- The success ConfirmationLine is the SOLE surface that prints the new
  key value. Regex + direct assertions in
  `TestRotateEncryptionKeyLogging.test_log_has_no_pii_or_key_material`
  prove: `new_key` appears exactly once on stdout; never on stderr;
  never in `caplog`; never in the audit `details_json`. PII check also
  rejects `12345678909`, `123.456.789-09`, `gAAAAA`, any 11-/14-digit
  run, and the seeded customer name.
- `rg "fernet\.decrypt" src/` returns 1 hit — `crypto.py::decrypt_tax_id`.
  `rg "Fernet\(" src/` returns 4 hits (encrypt, decrypt,
  `config._validate_fernet_key_shape`, and the new
  `system.py::rotate_encryption_key_cmd` shape check). The new CLI
  verb does NOT name `tax_id_encrypted` directly — rotation flows
  through `rotate_encryption_keys`, which is the encapsulation
  boundary.
- All 1391 tests pass; ruff, mypy strict, and pre-commit are green.
- **AC10 (read-only invariant):** This story's diff touches
  `src/comadre/keys/db.py` (new helper + imports), `src/comadre/keys/cli/commands/system.py`
  (new verb + imports + module docstring), plus docs (README.md,
  docs/deployment-guide.md, CLAUDE.md) and tests. It does **not**
  touch `src/comadre/api.py`, `src/comadre/main.py`,
  `src/comadre/rate_limit.py`, `src/comadre/keys/auth.py`,
  `src/comadre/keys/cache.py`, `src/comadre/health.py`,
  `src/comadre/counters.py`, `src/comadre/keys/migrations/`, or
  `src/comadre/keys/crypto.py`. `pyproject.toml` is unchanged — no new
  dependency.
- **Task 5 (integration smoke on 10.10.10.207) is deferred to the
  deploy step.** The CLI and DB behaviour are fully covered by the
  unit + CLI test matrix; the VPS smoke is the operator-side
  acceptance dance and will run when the branch is deployed.

### File List

Production code:
- `src/comadre/keys/db.py` — add `RotateEncryptionKeysResult`
  dataclass + `rotate_encryption_keys` helper; add `SecretStr` import.
- `src/comadre/keys/cli/commands/system.py` — add
  `rotate_encryption_key_cmd` verb, `_ROTATE_KEY_BAD_FERNET_HINT` +
  `_ROTATE_KEY_DECRYPT_FAILED_HINT` constants; import `click`,
  `Fernet`, `InvalidToken`, `SecretStr`, `get_cli_actor`,
  `stderr_console`, `rotate_encryption_keys`; rewrite module docstring
  (drops the "Story 4.2 will add" forecast; adds exit codes 4 and the
  rotation-rollback note to code 5).

Tests:
- `tests/test_keys_db.py` — add `TestRotateEncryptionKeys` class (7
  tests) + `_seed_active_customer` helper; add top-level imports for
  `Fernet`, `InvalidToken`, `SecretStr`, `cast`, `TaxIdKind`,
  `decrypt_tax_id`, `encrypt_tax_id`, `rotate_encryption_keys`.
- `tests/test_keys_cli_rotate_encryption_key.py` — new file, 14
  tests across 9 classes (happy / abort / Fernet shape / InvalidToken
  / tombstones / empty / missing config / DB errors / logging /
  flags).

Docs:
- `README.md` — new "Encryption-key rotation" feature bullet under
  "Registry-backed API keys".
- `docs/deployment-guide.md` — new "Rotating the encryption key"
  subsection under "Key Registry Management" (the 4-step operator
  procedure).
- `CLAUDE.md` — new "Non-Obvious Gotcha" covering the tombstone skip,
  the success-line echo as the sole key-material surface, and exit
  code 4 addendum for the system.py verbs.

Planning artifacts (status tracking):
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — story
  status flipped ready-for-dev → in-progress → review; header
  comment + body `last_updated` bumped.
- `_bmad-output/implementation-artifacts/4-2-encryption-key-rotation.md`
  — Dev Agent Record filled; tasks 1–4 + task 6 checked; task 5
  (VPS smoke) left unchecked as deferred to deploy.

### Change Log

- 2026-04-19 — Story 4.2 spec drafted from epic AC, architecture invariants, and Story 4.1's freshly-landed `decrypt_tax_id` primitive. Status: ready-for-dev.
- 2026-04-20 — Implementation landed. DB helper `rotate_encryption_keys` + CLI verb `rotate-encryption-key` + 7 DB tests + 14 CLI tests + docs (README, deployment-guide, CLAUDE.md). All ACs covered; pre-commit / ruff / mypy / pytest green (1391 passed). Task 5 (VPS integration smoke) deferred to deploy. Status: review.
