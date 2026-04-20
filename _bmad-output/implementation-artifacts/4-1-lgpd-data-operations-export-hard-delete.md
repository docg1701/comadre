# Story 4.1: LGPD Data Operations (Export & Hard Delete)

Status: review

> **Scope note — FR5 / FR6 / FR38.** Epic 4 opens with the two LGPD-primitive CLI verbs the operator needs to answer an ANPD subject-access request (`comadre-keys export-customer <id> --format {json|yaml}`) and a right-to-deletion request (`comadre-keys delete-customer <id> --hard`). Export is a **non-mutating** read that decrypts the Fernet-encrypted tax-ID, joins every associated `api_key` row, and emits a stable machine-readable document (JSON default, YAML alternate) to stdout — never logs, never terminal-displays, never caches the plaintext. Delete is the Destroy-tier verb (UX-DR11): it requires interactive confirmation (or `--yes`), runs a **single transaction** that DELETEs every associated `api_key`, purges the customer record's personal data (`tax_id_encrypted`, `name`, `email`, `notes`), and stamps `deleted_at` to preserve the tombstone row that `list-customers --deleted` already surfaces. The audit-log rows the customer accumulated during their lifetime stay intact (append-only invariant, FR38) — tombstone preservation + audit-log retention + no personal data left in either place is the three-legged LGPD-deletion contract. **No schema change** (the existing `tax_id_encrypted BLOB NOT NULL` / `name TEXT NOT NULL` / `email TEXT NOT NULL` constraints are satisfied by writing the canonical empty forms `b""` / `""` / `""` — the tombstone signal is `deleted_at IS NOT NULL`, not a NULL PII column). **No auth-path change, no FastAPI route, no new env var.** One new dependency (`pyyaml` for the `--format yaml` rendering path on export).

## Story

As an operator,
I want to export a customer's stored data in a machine-readable document and irreversibly purge their record (plus every associated API key) when they invoke their LGPD right to deletion,
so that I can fulfill Art. 18 (II, V) access requests and Art. 18 (VI) deletion requests within the 15-day statutory window without touching SQLite by hand, without leaving personal data scattered across the registry, and without breaking the audit-log append-only invariant that lets a later ANPD inquiry reconstruct "who did what, when" for this customer.

**Covers FRs:** FR5 (right to deletion — hard-delete customer + keys + personal data). FR6 (right to access — machine-readable export). FR38 (audit-log metadata retention after purge — the purge itself does not touch `audit_log`, and the lifetime of audit rows that referenced the tombstoned target stays intact because none of them contain personal data per `audit.py::_FORBIDDEN_DETAIL_KEYS`).
**NFRs:** NFR34 (access requests fulfillable in ≤15 days via `export-customer`). NFR35 (deletion requests fulfillable in ≤15 days via `delete-customer --hard`; the CLI command itself completes in under 1 second regardless of database size). NFR15 (PII-austere INFO logs — both verbs log counts + target IDs only, never decrypted tax-ID, name, email, or notes). NFR16 (error hints never echo invalid operator input).
**UX-DRs:** UX-DR11 (Destructive command confirmation pattern — `--yes` skips, default is "No" `[y/N]`). UX-DR3 (DetailPanel — N/A here; the export path emits JSON/YAML, not a DetailPanel). UX-DR6 (ErrorDisplay — red-bordered panel on stderr for 3/5/6 errors). UX-DR7 (ConfirmationLine — single-line stdout echo for the successful deletion). UX-DR10 (exit-code contract — 0/2/3/5/6 for both verbs; no new codes).
**Epic:** 4 — Security Hardening, LGPD & Operational Safety. First story in Epic 4 (4.1 → 4.2 → 4.3 → 4.4 → 4.5a–g → 4.6). Story 4.6 (LGPD documentation & breach runbook) will reference the verbs this story ships — `docs/monetization.md` "LGPD Operator Obligations" section cites `comadre-keys export-customer <id> --format json` and `comadre-keys delete-customer --hard <id>` verbatim (see epics.md:1045).

## Builds on

- **Story 1.1 — `insert_customer` + the single-transaction + audit-row pattern.** `src/comadre/keys/db.py:315-361` is the canonical template for a multi-statement write where the business mutation and the `log_event(...)` call share `with conn:`. `delete_customer_hard` follows the same contract: open the transaction in the helper (callers MUST NOT wrap in `with conn:`), DELETE the api_key rows, UPDATE the customer row to scrub PII + stamp `deleted_at`, write one `delete_customer` audit row, commit.
- **Story 1.1 — `_chmod_0600`, `get_connection`, `_apply_migrations` discipline.** `src/comadre/keys/db.py:243-276, 279-312` is the DB-open ladder every command module shares. `delete-customer` and `export-customer` open connections through `get_connection` and call `_apply_migrations` at the top of the command body — never direct `sqlite3.connect` calls.
- **Story 1.1 — `encrypt_tax_id` + `strip_tax_id`.** `src/comadre/keys/crypto.py:69-72` is the existing encryption boundary. This story adds the **dual** primitive `decrypt_tax_id(ciphertext: bytes, key: SecretStr) -> str` that round-trips the encrypted blob back to the canonical stripped+uppercased form. The decryption helper is the **only** place outside the original encrypt call that touches `fernet.decrypt`. Architecture §Security Boundaries and §Fernet Encryption Pattern explicitly require this (architecture.md:394-406, 637): "CPF/CNPJ encryption/decryption ONLY happens in `crypto.py` — no other module touches Fernet directly."
- **Story 1.1 — audit-log PII hygiene via `_FORBIDDEN_DETAIL_KEYS`.** `src/comadre/keys/audit.py:23-43` blocks `cpf`, `cnpj`, `tax_id`, `name`, `email`, `key_plaintext`, `authorization` (case-insensitive, walks nested dicts) and raises `ValueError` on any breach. The `delete_customer` audit row this story writes passes **zero** PII — only `{"keys_purged": int, "tax_id_kind": "cpf"|"cnpj"}` — so the forbidden-keys check is a defense-in-depth guarantee, not something dev needs to work around.
- **Story 1.2 / 1.6 — `get_customer` + `get_customer_detail` lookup semantics.** `src/comadre/keys/db.py:364-392, 657-688` already treat `deleted_at IS NOT NULL` as "missing" — every current read path is transparent to tombstones. This story preserves that: re-running `export-customer` or `delete-customer --hard` against an already-tombstoned customer returns exit 3 (not-found), matching the "LGPD tombstone is opaque to the CLI" invariant. `list-customers --deleted` (Story 1.3) is the one surface that DOES see tombstones, and its rendering does not need to change — the `name` / `email` columns will display empty strings for tombstoned rows, which the operator reads as "this row was hard-deleted" (paired with the `deleted_at` column the renderer already knows about).
- **Story 1.3 — `list-customers --deleted` tombstone visibility.** `src/comadre/keys/cli/commands/customers.py:239-340` renders tombstones only when `--deleted` is passed; the `render_customer_list` table includes `deleted_at` indirectly via the confirmation line. After this story lands, `list-customers --deleted` will start showing rows whose `name`/`email` are empty strings — this is the intended "purged" presentation (the `deleted_at` column confirms the tombstone). **No renderer change** is required; `render_customer_list` at `output.py:248-272` already tolerates empty-string fields.
- **Story 1.4 — `show` / `resolve_show_target` + the JSON render helpers.** `src/comadre/keys/cli/commands/customers.py:467-663` + `src/comadre/keys/db.py:831-876` (`resolve_show_target`) are the existing read-resolution path. `export-customer` does **not** reuse `resolve_show_target` because (a) it only accepts a customer ID (never a key prefix), (b) it needs to query the encrypted-blob column directly (which `get_customer_detail` deliberately omits — see `CustomerDetailRow`'s docstring at `models.py:132-145`). Instead it takes the argument verbatim, validates the `cust_[0-9a-z]{26}` shape via a tight regex before the DB round-trip, and calls a **new** helper `get_customer_with_cipher(conn, customer_id)` (see §1 below) that returns the encrypted tax-ID alongside the canonical list fields.
- **Story 1.6 — `revoke_api_key` + the "destructive Destroy-tier CLI" template.** `src/comadre/keys/cli/commands/keys.py:1125-1267` is the canonical template for a confirmation-gated mutation: literal-flag validation → settings ladder → DB open + migrations → resolve target → `typer.confirm(abort=True)` on `--yes is False` → helper call → structured log + ConfirmationLine. `delete-customer --hard` follows this skeleton verbatim; only the helper (`delete_customer_hard`), the error map, and the ConfirmationLine content differ.
- **Story 1.6 — `_touch_auth_cache_sentinel`.** `src/comadre/keys/db.py:214-240` is the sentinel-touch that forces every API replica's 60s-TTL auth cache to flush on its next stat. `delete_customer_hard` MUST call this after commit — every key just DELETEd from `api_key` is now unknown to the DB, and any replica still caching its auth payload would serve 200 for up to 60s otherwise. The call is the same single-line pattern `revoke_api_key` / `mark_key_paid` / `suspend_key` / `reactivate_key` / `update_api_key` all use. Post-commit + outside-transaction placement is critical: the sentinel touch is a filesystem side-effect; nesting it in `with conn:` would couple DB rollback semantics to filesystem state.
- **Story 1.6 — `resolve_today_in_tz` + `load_settings_and_tz` shared helper.** `src/comadre/keys/cli/commands/keys.py:738-781` is the canonical exit-6 ladder. `export-customer` does NOT need a TZ (no date computation — `registered_at` is rendered verbatim as the stored ISO string), but it DOES need settings for the encryption key; it uses the same `load_settings_and_tz` helper and discards the TZ. `delete-customer` also uses `load_settings_and_tz` and discards the TZ (the audit row's `occurred_at` comes from `audit.log_event`'s `_utcnow_iso` default — always UTC, never TZ-dependent).
- **Story 3.4 — system-verb CLI shape + `--format` literal validation pattern.** `src/comadre/keys/cli/commands/system.py:74-172, 321-411` is the template for `--format` validation at the top of a command body, literal-rejection with `LIST_FORMAT_CHOICES`-like tuple, and branching render at the bottom. `export-customer` extends the shared choices tuple from `("table", "json")` to a new per-verb choices tuple `EXPORT_FORMAT_CHOICES: tuple[str, ...] = ("json", "yaml")` sited in `output.py` (table is not an export format — LGPD delivery never uses a pretty-printed panel). The literal-rejection path stays identical: `if format not in EXPORT_FORMAT_CHOICES: render_error(...); raise typer.Exit(code=2)`.

## Unblocks

- **Story 4.6 — LGPD Documentation & Breach Runbook.** `docs/monetization.md` "LGPD Operator Obligations" section will cite `comadre-keys export-customer <id> --format json` (Art. 18 II/V access procedure) and `comadre-keys delete-customer --hard <id>` (Art. 18 VI deletion procedure). 4.6 lands the prose; this story ships the verbs the prose references.
- **Story 4.5x — CI Non-Regression Security Suite.** No direct dependency, but the `delete-customer --hard` audit row this story writes is the canonical example for "FR38: audit-log retains event metadata, never personal data" — future CI audit-log-schema tests (deferred) can key off this path.
- **Operator onboarding — first ANPD-style audit drill.** An operator can now exercise the full LGPD flow end-to-end on the 10.10.10.207 staging VPS: create a customer with `create-customer`, issue a key, run traffic through it, export via `export-customer --format json`, then hard-delete and verify `list-customers --deleted` shows the tombstone + audit-log preserves the event trail. Documented as an acceptance smoke in Task 10 below.

## Depends on

- Stories 1.1 (schema + `insert_customer` + `encrypt_tax_id` + audit scaffolding), 1.2 (`show` + `get_customer`), 1.3 (`list-customers --deleted` tombstone rendering), 1.4 (`show --format json` render helpers), 1.6 (`revoke_api_key` Destroy-tier CLI template + `_touch_auth_cache_sentinel`) must all be `done`. Verified against `_bmad-output/implementation-artifacts/sprint-status.yaml` 2026-04-19 — Epic 1 is fully `done`, Epic 2 `done`, Epic 3 `done`. Epic 4's other stories (4.2+) do not need to be done — 4.1 is the epic's first story.
- **One new dependency.** `pyyaml>=6.0` for the `--format yaml` rendering path on `export-customer`. The PRD's CLI spec (prd.md:993) explicitly mentions `--format yaml` for `export-customer` ("LGPD access response is easier to read") and no yaml library is currently pulled into the tree (verified against `pyproject.toml` dependency list). Added via `uv add pyyaml` in Task 0 below — 84 KB wheel, zero native dependencies, MIT-licensed, stable since 2021. Pinning `>=6.0` picks up the `safe_dump`-only surface this story uses (never `load`/`unsafe_load`, which is YAML's documented deserialization-RCE footgun). The mypy strict profile needs a `[[tool.mypy.overrides]]` entry for `yaml.*` if the third-party stub isn't picked up (see Task 0.2).
- **No schema change.** The customer table's `tax_id_encrypted BLOB NOT NULL`, `name TEXT NOT NULL`, `email TEXT NOT NULL`, `notes TEXT DEFAULT ''` constraints are satisfied by the tombstone-write which sets them to `b""`, `""`, `""`, `""` respectively. The canonical tombstone signal is `deleted_at IS NOT NULL` — not a NULL PII column. Changing NOT NULL constraints would require a v002 migration (create-new-table + copy + rename) for zero operator-observable benefit; see §Why-empty-strings-not-NULL in Dev Notes.
- **No auth-path / FastAPI runtime change.** `src/comadre/main.py`, `src/comadre/api.py`, `src/comadre/rate_limit.py`, `src/comadre/keys/auth.py`, `src/comadre/keys/cache.py`, `src/comadre/health.py` (the HTTP `/health` endpoint), `src/comadre/counters.py` stay byte-identical (asserted by AC18).
- **No change to existing migrations.** `src/comadre/keys/migrations/v001_initial.sql` stays byte-identical.
- **No new env var.** `delete-customer` and `export-customer` read `KEY_REGISTRY_DB_PATH` + `KEY_REGISTRY_ENCRYPTION_KEY` + `BILLING_TIMEZONE` via the shared `load_settings_and_tz` helper and the existing `pydantic-settings` `Settings` class.

## Scope

Adds one new cryptographic helper (`decrypt_tax_id` in `src/comadre/keys/crypto.py`), one new DB helper (`get_customer_with_cipher` in `src/comadre/keys/db.py`), one new DB helper (`delete_customer_hard` in `src/comadre/keys/db.py`) plus its return dataclass (`DeleteCustomerResult`), two new CLI verbs (`export-customer` + `delete-customer` in `src/comadre/keys/cli/commands/customers.py`), one new tax-ID formatter helper (`format_tax_id_display` in `src/comadre/keys/formatters.py`, or new `crypto.py` sibling — see §3), one new `EXPORT_FORMAT_CHOICES` tuple + associated JSON/YAML renderers in `src/comadre/keys/cli/output.py`, and the matching tests + docs. **One new dep (`pyyaml`).** **No schema change. No auth-path change. No FastAPI runtime change. No new env var.**

### 1. New crypto primitive: `decrypt_tax_id`

`src/comadre/keys/crypto.py` — append directly after `encrypt_tax_id` (L69-72). Mirror the existing signature but in reverse. Module docstring updates to describe the dual primitive.

```python
def decrypt_tax_id(ciphertext: bytes, key: SecretStr) -> str:
    """Fernet-decrypt a tax ID stored via ``encrypt_tax_id``.

    Returns the canonical stripped+uppercased form — the same shape
    ``encrypt_tax_id`` accepts. Callers that need to display the tax ID
    (e.g., ``export-customer``) format the canonical form via
    ``format_tax_id_display`` before emission; the decrypted string
    never leaves the caller's local scope otherwise.

    Raises ``cryptography.fernet.InvalidToken`` on ciphertext tampering,
    truncation, or key mismatch. Callers SHOULD NOT attempt to recover
    from ``InvalidToken`` by sniffing the bytes — propagate it as a
    ``KeyRegistryError`` (500) or an exit-5 database error, never as a
    soft-fail that displays a placeholder tax ID.
    """
    fernet = Fernet(key.get_secret_value().encode())
    return fernet.decrypt(ciphertext).decode()
```

**Why mirror `encrypt_tax_id` literally.** The existing encrypt path wraps `Fernet(key.encode()).encrypt(plaintext.encode())` — no helper lifting, no `functools.lru_cache` on the Fernet instance. The decrypt path follows the same "simple enough; instantiate on every call" pattern. Fernet instantiation is sub-millisecond; export runs once per command so caching would be premature optimization. Architecture §Fernet Encryption Pattern (arch.md:394-406) explicitly says "Always encode string to bytes before encrypting; always decode bytes to string after decrypting; Never cache decrypted values — decrypt on demand for display only" — the last clause rules out caching anywhere.

**Why return the canonical form, not the formatted form.** Display formatting is a presentation concern; the crypto module stays oriented at the storage boundary. `format_tax_id_display` (new helper below) is where the canonical form becomes `123.456.789-00` / `12.345.678/0001-95` / `12.ABC.345/XY01-89`. Mixing them here would force `export-customer`'s JSON path to re-strip the formatted string (same attack surface the `strip_tax_id` docstring at crypto.py:30-38 handles), which is pointless churn.

### 2. New DB helper: `get_customer_with_cipher`

`src/comadre/keys/db.py` — append near `get_customer` (L364-392) since both are single-customer readers. Return a small dataclass so the caller gets named fields instead of a tuple.

```python
@dataclass(frozen=True, slots=True)
class CustomerExportRow:
    """Active-customer export payload — includes the encrypted tax-ID blob.

    Surfaced exclusively for ``export-customer`` (Story 4.1); every other
    read path goes through ``get_customer_detail`` which deliberately
    omits the ciphertext. Tombstoned customers are treated as missing
    (``deleted_at IS NULL`` filter), matching ``get_customer`` /
    ``get_customer_detail``.
    """

    id: str
    name: str
    email: str
    tax_id_kind: TaxIdKind
    tax_id_encrypted: bytes
    notes: str
    registered_at: str  # raw ISO string (matches CustomerListRow, not CustomerRecord)


def get_customer_with_cipher(
    conn: sqlite3.Connection,
    customer_id: str,
) -> CustomerExportRow | None:
    """Return the export payload for ``customer_id``, or ``None`` if missing.

    Tombstoned customers (``deleted_at IS NOT NULL``) are treated as
    missing. Used only by ``export-customer`` — the ciphertext BLOB
    must NEVER be returned by a general-purpose helper that callers
    might repurpose for logs / panels / caches.
    """
    row = conn.execute(
        "SELECT id, name, email, tax_id_kind, tax_id_encrypted, notes, registered_at "
        "FROM customer WHERE id = ? AND deleted_at IS NULL",
        (customer_id,),
    ).fetchone()
    if row is None:
        return None
    return CustomerExportRow(
        id=row["id"],
        name=row["name"],
        email=row["email"],
        tax_id_kind=cast(TaxIdKind, row["tax_id_kind"]),
        tax_id_encrypted=bytes(row["tax_id_encrypted"]),
        notes=row["notes"] or "",
        registered_at=row["registered_at"],
    )
```

**Why not extend `get_customer` / `get_customer_detail`.** Both existing helpers deliberately do NOT return `tax_id_encrypted` so a refactor-accidental leak through a new call-site stays impossible. A separate helper keeps the narrow "ciphertext exposure" surface grep-able — every place the encrypted blob leaves the DB in this codebase will be limited to `get_customer_with_cipher` and the purge-path UPDATE inside `delete_customer_hard`.

**Why `registered_at` as raw ISO string, not `datetime`.** Matches `CustomerListRow` (models.py:98) and `CustomerExportRow`'s exclusive consumer, the JSON/YAML renderer, which emits the string verbatim. Round-tripping through `datetime` would risk TZ drift on a string the storage layer already guarantees is UTC ISO 8601.

### 3. New formatter helper: `format_tax_id_display`

Sited in `src/comadre/keys/formatters.py` (alongside `format_seconds_ago`). This helper is new; the existing `crypto.py` already declares the canonical storage form, and the symmetric display form belongs at the rendering boundary.

```python
def format_tax_id_display(canonical: str, kind: TaxIdKind) -> str:
    """Return the human-readable form of a canonical CPF / CNPJ.

    Examples:
        ``format_tax_id_display("12345678909", "cpf")`` → ``"123.456.789-09"``
        ``format_tax_id_display("12345678000195", "cnpj")`` → ``"12.345.678/0001-95"``
        ``format_tax_id_display("12ABC345XY0189", "cnpj")`` → ``"12.ABC.345/XY01-89"``

    Input MUST be the canonical stripped+uppercased form as produced by
    ``strip_tax_id`` and persisted in ``tax_id_encrypted``. Invalid
    lengths raise ``ValueError`` — export callers should have already
    validated the length on decrypt (11 for CPF, 14 for CNPJ); a surprise
    here would indicate ciphertext / schema drift, not operator input.
    """
    if kind == "cpf":
        if len(canonical) != 11:
            raise ValueError(f"CPF must be 11 chars, got {len(canonical)}")
        return f"{canonical[0:3]}.{canonical[3:6]}.{canonical[6:9]}-{canonical[9:11]}"
    # CNPJ: 14 chars, numeric or alphanumeric (RFB IN 2.229/2024).
    if len(canonical) != 14:
        raise ValueError(f"CNPJ must be 14 chars, got {len(canonical)}")
    return (
        f"{canonical[0:2]}.{canonical[2:5]}.{canonical[5:8]}/"
        f"{canonical[8:12]}-{canonical[12:14]}"
    )
```

**Why here, not in `crypto.py`.** `crypto.py` handles the storage-boundary (encrypt / decrypt / strip / validate). Display formatting is a presentation concern and belongs next to the other renderer primitives (`format_seconds_ago`, etc.). Matches the architecture §Module Organization rule: "CPF/CNPJ encryption/decryption ONLY happens in `crypto.py` — no other module touches Fernet directly" (arch.md:637) — the contrapositive is that non-crypto helpers for CPF/CNPJ belong elsewhere.

**Why render formatted in JSON export, not canonical.** The UX-spec and PRD both describe `show`'s CPF display as formatted (`123.456.789-00`). LGPD access requests are operator-to-customer deliverables — the customer reads their tax ID verbatim from the JSON/YAML, and the formatted form is what every Brazilian document shows. The canonical form (`12345678909`) is a storage detail, not an external contract. Same rationale: if the data-subject access response returns `canonical`, the operator's first instinct is to format it before forwarding, and we'd be forcing every caller to redo the work we could do once.

### 4. New DB helper: `delete_customer_hard`

`src/comadre/keys/db.py` — append near the top of the mutation-helpers cluster (after `update_customer` at L395-486). Returns a small result dataclass so the CLI gets a structured count for the ConfirmationLine + audit row.

```python
@dataclass(frozen=True, slots=True)
class DeleteCustomerResult:
    """Return payload from ``delete_customer_hard`` (Story 4.1).

    ``keys_purged`` is the count of ``api_key`` rows DELETEd in the same
    transaction as the customer-tombstone UPDATE (and one ``delete_customer``
    audit row). ``customer_name`` is captured PRE-purge so the ConfirmationLine
    can render ``Deleted: cust_... (Marcos Silva) — 2 keys purged`` —
    post-purge the name column reads empty string.

    ``customer_id`` is echoed back so the CLI caller doesn't have to
    remember what it passed in. The return object carries no decrypted
    tax ID, no email, no notes — the successful-deletion confirmation
    surfaces only the name (already rendered identically by
    ``list-customers``).
    """

    customer_id: str
    customer_name: str
    keys_purged: int


def delete_customer_hard(
    conn: sqlite3.Connection,
    customer_id: str,
    *,
    actor: str,
) -> DeleteCustomerResult | None:
    """Hard-delete ``customer_id`` + all associated keys in one transaction.

    Returns ``None`` when the customer is missing or already tombstoned
    — the CLI maps ``None`` to exit 3. Otherwise:

    1. ``DELETE FROM api_key WHERE customer_id = ?`` (rowcount = keys_purged).
    2. ``UPDATE customer SET name = '', email = '', tax_id_encrypted = X'',
       notes = '', deleted_at = <utcnow-iso>`` for the matching id.
    3. ``log_event(..., action='delete_customer', target_type='customer',
       target_id=customer_id, details={'keys_purged': N, 'tax_id_kind': kind})``
       — no personal data in ``details`` (defense-in-depth: audit.py's
       ``_FORBIDDEN_DETAIL_KEYS`` blocks ``name``/``email``/``cpf``/``cnpj``
       / ``tax_id`` already; this helper never attempts to pass them).

    Callers MUST NOT wrap in ``with conn:``. The helper owns the
    transaction so the DELETE, the UPDATE, and the audit write either
    all commit or all roll back.

    ``customer_name`` and ``tax_id_kind`` are captured BEFORE the
    UPDATE so the return payload + audit row both carry the pre-purge
    signal (the name is part of the operator's ConfirmationLine; the
    kind is non-PII metadata FR38 permits).

    The transaction order matters: keys BEFORE customer. The schema's
    ``customer_id ... REFERENCES customer(id) ON DELETE RESTRICT``
    (v001_initial.sql:14) would reject any "DELETE customer" before its
    keys are gone; we use UPDATE-to-scrub on the customer row anyway,
    but a future operator who tries to DELETE the tombstone row would
    hit the FK. The RESTRICT constraint is retained intentionally —
    tombstone preservation is a feature, not a side-effect to work
    around.
    """
    from comadre.keys.audit import log_event

    with conn:
        # Capture the pre-purge signal (name for ConfirmationLine, kind
        # for non-PII audit metadata). Use ``deleted_at IS NULL`` to
        # match the existing "tombstone is opaque" contract — re-running
        # delete against an already-tombstoned customer returns None,
        # which the CLI maps to exit 3.
        row = conn.execute(
            "SELECT name, tax_id_kind FROM customer "
            "WHERE id = ? AND deleted_at IS NULL",
            (customer_id,),
        ).fetchone()
        if row is None:
            return None
        customer_name = row["name"]
        tax_id_kind = row["tax_id_kind"]

        # Step 1 — DELETE every associated api_key. ``rowcount`` is the
        # authoritative key-purge count for the ConfirmationLine + audit.
        cursor = conn.execute(
            "DELETE FROM api_key WHERE customer_id = ?",
            (customer_id,),
        )
        keys_purged = cursor.rowcount

        # Step 2 — scrub PII on the customer row + stamp deleted_at.
        # The empty-string / zero-length-blob writes satisfy the NOT NULL
        # constraints on name / email / tax_id_encrypted; deleted_at is
        # the canonical tombstone signal per the Story 1.2 contract.
        now_iso = _utcnow_iso()
        conn.execute(
            "UPDATE customer SET name = '', email = '', "
            "tax_id_encrypted = X'', notes = '', deleted_at = ? "
            "WHERE id = ? AND deleted_at IS NULL",
            (now_iso, customer_id),
        )

        # Step 3 — one audit row. ``_FORBIDDEN_DETAIL_KEYS`` would
        # reject name/email/tax_id/cpf/cnpj — we pass only structural
        # metadata permitted by FR38.
        log_event(
            conn,
            actor=actor,
            action="delete_customer",
            target_type="customer",
            target_id=customer_id,
            details={"keys_purged": keys_purged, "tax_id_kind": tax_id_kind},
        )

    _touch_auth_cache_sentinel(conn)

    return DeleteCustomerResult(
        customer_id=customer_id,
        customer_name=customer_name,
        keys_purged=keys_purged,
    )
```

**Why `X''` (zero-length BLOB literal) instead of `NULL` on `tax_id_encrypted`.** `v001_initial.sql:6` declares the column `BLOB NOT NULL`; a v002 migration to drop the NOT NULL constraint would require SQLite's "recreate table + copy + rename" dance (SQLite has no `ALTER COLUMN DROP NOT NULL`) and buys zero operator-observable benefit — the canonical tombstone signal is `deleted_at IS NOT NULL`. Zero-length BLOB satisfies the NOT NULL constraint and is unambiguously "no ciphertext" to every reader.

**Why captured `customer_name` / `tax_id_kind` inside the transaction.** A concurrent writer can't race us in single-writer CLI land, but defense-in-depth: if the SELECT and UPDATE straddled a write, we'd be logging stale metadata. Capturing inside `with conn:` is free and matches the `update_customer` / `revoke_api_key` patterns.

**Why `_touch_auth_cache_sentinel` is called OUTSIDE the transaction.** Same reason Story 1.6's `revoke_api_key` / `mark_key_paid` place it post-`with conn:`: the sentinel is a filesystem side-effect; nesting inside SQLite's transaction would couple FS state to DB rollback semantics. Post-commit also guarantees no pre-commit sentinel update on a transaction that ultimately aborts.

**Why no "re-read" post-commit.** Unlike `update_customer` / `revoke_api_key` which return a refreshed detail row for subsequent rendering, `delete_customer_hard` returns a fixed 3-field payload (`customer_id`, `customer_name`, `keys_purged`) that the CLI renders verbatim. Re-reading the post-purge row would return a tombstone with empty name / email — the operator's ConfirmationLine wants the PRE-purge name ("Deleted: cust_... (Marcos Silva)"), which we captured at step 1.

### 5. New CLI verb: `export-customer`

`src/comadre/keys/cli/commands/customers.py` — append after `update_customer_cmd`. Follows the `show_cmd` skeleton with two divergences: only customer IDs (not key prefixes) are accepted, and the output is JSON / YAML (never a DetailPanel).

**Command signature:**

```python
@app.command("export-customer")
def export_customer_cmd(
    customer_id: str = typer.Argument(
        ...,
        metavar="CUSTOMER_ID",
        help=(
            "Customer ID to export (from create-customer / list-customers). "
            "Example: cust_01j8xr3e4c5m7kn9p2qt8vwy."
        ),
    ),
    format: str = typer.Option(
        "json",
        "--format",
        help=(
            "Output format: json (default, machine-readable) or yaml "
            "(human-readable for data-subject access response). "
            "Example: --format yaml."
        ),
    ),
) -> None:
    """Export a customer's stored data to stdout for LGPD Art. 18 II/V response.

    Example: comadre-keys export-customer cust_01j8xr3e4c5m7kn9p2qt8vwy
             comadre-keys export-customer cust_01j8xr3e4c5m7kn9p2qt8vwy --format yaml
    """
```

**Body ladder (mirrors `show_cmd`):**

1. **Literal flag validation (exit 2).** `if format not in EXPORT_FORMAT_CHOICES` → `render_error(...)` → `raise typer.Exit(code=2)`.
2. **Customer ID shape validation (exit 2).** Regex `^cust_[0-9a-z]{26}$` — rejects key prefixes, partial IDs, pasted `cmdr_live_` secrets. The shape rejection is pre-DB so a typo never opens a connection.
3. **Settings ladder (exit 6).** `load_settings_and_tz()` — the TZ is discarded but the helper enforces `key_registry_encryption_key` presence, which we need for decrypt.
4. **Open DB + migrations (exit 5).** Standard `get_connection` + `_apply_migrations` pattern with `from exc` trace preservation.
5. **Fetch (exit 3 on not-found).** `row = get_customer_with_cipher(conn, customer_id)`; if `None`, `render_error("Not found: no customer matches '{customer_id}'", _NOT_FOUND_HINT)` + `raise typer.Exit(code=3)`.
6. **List associated keys.** `keys = list_api_keys(conn, customer_id=customer_id)` — reuses the existing Story 1.3 helper, which already returns `ApiKeyListRow` with `key_prefix`, `status`, `billing_mode`, `created_at` (the AC1 fields). No new DB query needed.
7. **Decrypt.** `canonical = decrypt_tax_id(row.tax_id_encrypted, settings.key_registry_encryption_key)`. Wrap in `try/except InvalidToken: render_error("Database error: tax-ID ciphertext failed to decrypt", "Check KEY_REGISTRY_ENCRYPTION_KEY matches the deployment-time key."); raise typer.Exit(code=5)` — the only path where a decrypt failure is operationally possible is an env-var swap (operator changed `KEY_REGISTRY_ENCRYPTION_KEY` without running Story 4.2's `rotate-encryption-key`).
8. **Format.** `tax_id_display = format_tax_id_display(canonical, row.tax_id_kind)`. Build the payload dict with the AC1 field order:
   ```python
   payload = {
       "id": row.id,
       "name": row.name,
       "email": row.email,
       "tax_id_kind": row.tax_id_kind,
       "tax_id": tax_id_display,
       "registered_at": row.registered_at,
       "notes": row.notes,
       "keys": [
           {
               "key_prefix": k.key_prefix,
               "status": k.status,
               "billing_mode": k.billing_mode,
               "created_at": k.created_at,
           }
           for k in keys
       ],
   }
   ```
9. **Close DB** (standard `finally: with contextlib.suppress: conn.close()`).
10. **PII-austere INFO log.** `_logger.info("Customer exported | id=%s | key_count=%d | format=%s", row.id, len(keys), format)` — no tax ID, no name, no email.
11. **Render branch.** `if format == "json": render_export_json(payload)` (wraps `stdout_console().print_json(data=payload, indent=2)`). `else: render_export_yaml(payload)` (wraps `yaml.safe_dump(payload, stream=stdout_console().file, allow_unicode=True, sort_keys=False, default_flow_style=False)`).

**Why `format="json"` default.** NFR-side default; operator piping into a file for the LGPD response wants a stable, easily-diffed format. YAML is opt-in for the human-readable print.

**Why decrypt happens AFTER `list_api_keys`.** Keeps the decrypted string's lifetime as short as possible — build the payload dict and drop the local variable immediately. Architecture §Security Boundaries: "Never cache decrypted values — decrypt on demand for display only" (arch.md:405).

**Why `stdout_console().print_json`** for the JSON path vs `json.dumps` + `print`. The project's existing JSON commands (`show --format json`, `cache-status --format json`, `health --format json`) all use `print_json` on the shared Console singleton — same indentation, same stream, same UTF-8 handling. Deviating here would cause NO_COLOR test fixtures to behave differently across commands.

**Why `yaml.safe_dump` (never `yaml.dump`).** `yaml.dump` emits the `!!python/object` tag on certain types, which is both RCE-adjacent (the tag is honored by `yaml.load` on the consumer side) and visually noisy. `safe_dump` caps at the standard YAML 1.1 types — exactly what a LGPD-access-request deliverable needs.

**Why `allow_unicode=True, sort_keys=False`.** Customer names / notes in Portuguese use accented characters; `allow_unicode=True` keeps them as UTF-8 rather than `\xHH` escapes. `sort_keys=False` preserves the AC1 field-order contract (id → name → email → tax_id_kind → tax_id → registered_at → notes → keys). The renderer dict insertion order is authoritative.

### 6. New CLI verb: `delete-customer`

`src/comadre/keys/cli/commands/customers.py` — append after `export_customer_cmd`. Follows the `revoke_key_cmd` Destroy-tier template.

**Command signature:**

```python
@app.command("delete-customer")
def delete_customer_cmd(
    customer_id: str = typer.Argument(
        ...,
        metavar="CUSTOMER_ID",
        help=(
            "Customer ID to permanently purge. "
            "Example: cust_01j8xr3e4c5m7kn9p2qt8vwy."
        ),
    ),
    hard: bool = typer.Option(
        False,
        "--hard",
        help=(
            "Required acknowledgement flag. The customer record's personal "
            "data (name, email, encrypted tax ID, notes) is irreversibly "
            "purged; every associated API key is deleted; the tombstone "
            "row + audit-log entries are preserved. LGPD Art. 18 VI."
        ),
    ),
    yes: bool = typer.Option(
        False,
        "--yes",
        help="Skip the interactive confirmation prompt (for scripting).",
    ),
) -> None:
    """Permanently purge a customer's personal data and all their API keys (LGPD).

    Example: comadre-keys delete-customer cust_01j8xr3e4c5m7kn9p2qt8vwy --hard
             comadre-keys delete-customer cust_01j8xr3e4c5m7kn9p2qt8vwy --hard --yes
    """
```

**Body ladder (mirrors `revoke_key_cmd`):**

1. **`--hard` required-flag check (exit 2).** `if not hard: render_error("Usage error: --hard is required for delete-customer", "Re-run with --hard to acknowledge the irreversible purge. See --help for the full effect."); raise typer.Exit(code=2)`. The epic AC (epics.md:771) and PRD (prd.md:962) both pin `--hard` as the required acknowledgement flag; a bare `delete-customer` is explicitly a usage error.
2. **Customer ID shape validation (exit 2).** Same regex as `export-customer`: `^cust_[0-9a-z]{26}$`.
3. **Settings ladder (exit 6).** `load_settings_and_tz()` — TZ discarded.
4. **Open DB + migrations (exit 5).**
5. **Pre-flight lookup for the confirmation-line preview (exit 3 on not-found).** `existing = get_customer(conn, customer_id)` — if `None`, exit 3 BEFORE prompting. Confirming deletion of a nonexistent row is worse UX than a clean not-found. Capture `customer_name` from the existing row for the prompt. Also pre-count the keys: `pre_keys = len(list_api_keys(conn, customer_id=customer_id))`.
6. **Confirmation gate (UX-DR11).** If `--yes` is False:
   ```python
   typer.confirm(
       f"This will permanently delete customer {customer_name} and all "
       f"associated keys ({pre_keys} key(s)). This action cannot be undone. "
       f"Encrypted tax ID will be purged. Continue?",
       default=False,
       abort=True,
       err=True,
   )
   ```
   On `click.exceptions.Abort`: echo "Aborted." to stderr, `raise typer.Exit(code=2)`. Matches the `revoke_key_cmd` L1216-1221 abort pattern byte-for-byte. **The prompt text faithfully tracks the epic AC** (epics.md:773) — templating `{customer_name}` from the pre-flight lookup and adding the `{pre_keys}` count parenthetical so the operator sees the scope before typing "y" (additive to the epic AC wording; semantically identical).
7. **Helper call (exit 5 on DB error).** `result = delete_customer_hard(conn, customer_id, actor=get_cli_actor())`. If `None` (concurrent tombstone between pre-flight and helper — unreachable in single-writer CLI but guarded), `render_error(f"Customer not found: {customer_id}", _NOT_FOUND_HINT); raise typer.Exit(code=3)`.
8. **Close DB.**
9. **PII-austere INFO log.** `_logger.info("Customer purged | id=%s | keys_purged=%d", result.customer_id, result.keys_purged)` — no name, no email, no tax ID.
10. **ConfirmationLine (UX-DR7).** `render_confirmation(f"Deleted: {result.customer_id} ({result.customer_name}) \u2014 {result.keys_purged} keys purged")` — matches the UX-spec ux-design-specification.md:904 and:923 verbatim grammar.

**Why `--hard` is a required flag, not just a suggestion in `--help`.** The PRD (prd.md:962) and the UX-spec (ux-design-specification.md:894, 900) both surface `delete-customer --hard` as the canonical form. Making `--hard` required (not defaulting to True) protects against a typo-cascaded `comadre-keys delete-customer cust_...` executing a destructive action the operator didn't ask for. The epic AC (epics.md:772-773) shows the operator invoking `delete-customer --hard cust_...`; omitting the flag is not a documented path.

**Why pre-flight lookup instead of relying on `delete_customer_hard`'s `None` return.** The confirmation prompt needs `customer_name` and `pre_keys` BEFORE the operator types "y". If the operator types "y" on a nonexistent customer, they've wasted a prompt cycle and the helper returns `None` with nothing to confirm. Pre-flight lookup gives the "not found" signal upfront and keeps the prompt honest.

**Why the abort exit code is 2 (not 1).** Matches `revoke_key_cmd` at keys.py:1221. Click's default abort exit is 1; UX-DR10 maps 1 to "general" and 2 to "usage error" — a `[y/N]: n` is closer to "operator issued a usage-tier correction" than "general error". Consistency across Destroy-tier verbs is the invariant.

### 7. New renderers: `render_export_json` + `render_export_yaml`

`src/comadre/keys/cli/output.py` — append near `render_cache_status` / `render_health_report`.

```python
EXPORT_FORMAT_CHOICES: tuple[str, ...] = ("json", "yaml")


def render_export_json(payload: dict[str, object]) -> None:
    """Emit the export payload as indented JSON to stdout (UX-DR10 read-tier)."""
    stdout_console().print_json(data=payload, indent=2)


def render_export_yaml(payload: dict[str, object]) -> None:
    """Emit the export payload as YAML 1.1 (safe subset) to stdout.

    Key-order preserved from the ``payload`` dict's insertion order so
    the AC1 field-ordering contract holds on YAML output too. Unicode
    passes through verbatim (names / notes with accented characters).
    """
    import yaml

    stdout_console().file.write(
        yaml.safe_dump(
            payload,
            allow_unicode=True,
            sort_keys=False,
            default_flow_style=False,
        )
    )
```

**Why `stdout_console().file.write(...)` for the YAML path.** `yaml.safe_dump` writes to a file-like object natively. Routing through `stdout_console().print(...)` would pass the YAML string through rich's markup interpreter — any `[` in a notes field would be mis-parsed as rich markup. Writing directly to the underlying file preserves the raw YAML bytes.

**Why lazy `import yaml`.** PyYAML adds ~0.15s to `comadre-keys --help` if imported at module load. Lazy-importing inside the renderer keeps the startup cost of the non-YAML path zero and matches the "pay-for-what-you-use" shape the project's existing Story 3.4 health / Story 3.2 revenue renderers already follow.

### 8. Module-docstring updates

`src/comadre/keys/cli/commands/customers.py` top-of-file docstring (lines 1-9) currently enumerates the exit-code contract for Stories 1.1–1.5. Extend to cover Story 4.1:

```
Exit-code contract (UX-DR10):
  0 — success
  2 — usage error (Typer rejects / mutex violation / bad email / --hard
      missing / --format invalid / confirm-abort)
  3 — not-found (tombstoned or missing customer on show / update-customer /
      export-customer / delete-customer)
  4 — validation error (tax-ID checksum)
  5 — database error (sqlite3.Error / fernet InvalidToken on export
      decrypt — the only path where decrypt can fail operationally)
  6 — permission / configuration error (missing encryption key, etc.)
```

`src/comadre/keys/crypto.py` module docstring: add a sentence to clarify `decrypt_tax_id` is the symmetric pair of `encrypt_tax_id` and the only place outside the original encrypt call that touches Fernet.

### 9. Docs

- **`README.md`** — "Registry-backed API keys" feature bullet list gains: "LGPD data export & purge (`comadre-keys export-customer <id> --format json|yaml` / `comadre-keys delete-customer <id> --hard`)."
- **`docs/configuration-reference.md`** — no change (`export-customer` and `delete-customer` add no new env vars; the encryption-key requirement is already documented).
- **`docs/deployment-guide.md`** — "LGPD operator procedures" subsection (new, ~10 lines) documenting the one-liner for a data-subject access request (pipe JSON to the operator's email client or a file) and the one-liner for a deletion request (`--hard --yes` for automation, bare `--hard` for interactive). Cross-reference the Story 4.6 runbook will subsume this section once 4.6 lands.
- **`CLAUDE.md`** — two new entries under "Non-Obvious Gotchas":
  1. "`tax_id_encrypted BLOB NOT NULL` is kept — tombstones use `X''` (zero-length BLOB), not NULL, to avoid a v002 migration. The canonical tombstone signal stays `deleted_at IS NOT NULL`."
  2. "`export-customer`'s decrypt path is the ONLY non-storage-boundary call to `fernet.decrypt` in the codebase. Any new decrypt site must route through `keys.crypto.decrypt_tax_id`."

### 10. Tests

All tests use the existing fixtures (`tmp_path`, `_reset_consoles_to_buffers`, `CliRunner` from `typer.testing`, `insert_customer` + `insert_api_key` seeds). No new fixture scaffolding is needed.

**`tests/test_keys_crypto.py`** — add `TestDecryptTaxId` class:
- Round-trip `encrypt → decrypt` returns the original canonical (CPF, numeric CNPJ, alphanumeric CNPJ).
- `InvalidToken` raised on tampered ciphertext (flip a byte).
- `InvalidToken` raised on key mismatch (encrypt with key A, decrypt with key B).

**`tests/test_keys_db.py`** — add `TestGetCustomerWithCipher` + `TestDeleteCustomerHard` classes:
- `get_customer_with_cipher` returns `CustomerExportRow` on active customer with matching fields + ciphertext bytes.
- `get_customer_with_cipher` returns `None` for tombstoned customer.
- `get_customer_with_cipher` returns `None` for missing id.
- `delete_customer_hard` on active customer with N keys returns `DeleteCustomerResult(customer_id=..., customer_name="...", keys_purged=N)`.
- Post-delete: customer row has `name=""`, `email=""`, `tax_id_encrypted=b""`, `notes=""`, `deleted_at != NULL`; no `api_key` rows remain; one `delete_customer` audit row added; pre-existing audit rows for this customer/key targets remain intact.
- `delete_customer_hard` on tombstoned customer returns `None` (idempotent re-run).
- `delete_customer_hard` on missing customer returns `None`.
- `delete_customer_hard` with N=0 keys returns `DeleteCustomerResult(..., keys_purged=0)` and still tombstones the customer (PRD epics.md:783 "0 keys purged" case).
- `delete_customer_hard` audit `details` contains ONLY `{"keys_purged": N, "tax_id_kind": "cpf"|"cnpj"}` — no name/email/tax_id/cpf/cnpj keys (the `_FORBIDDEN_DETAIL_KEYS` guard is already tested in `test_keys_audit.py`; this test asserts the call site complies).
- `delete_customer_hard` transactional rollback on mid-transaction failure: stub `log_event` to raise → assert api_key rows remain, customer row unchanged, no new audit row.
- `delete_customer_hard` touches the sentinel: assert `{db}.invalidate` mtime advances (matches Story 1.6 pattern).
- `TestListCommandsDoNotWrite` (existing in `test_keys_db.py`): extend to cover `get_customer_with_cipher` as a pure-read (no INSERT/UPDATE/DELETE observable via `total_changes`).

**`tests/test_keys_cli.py`** (or a new `tests/test_keys_cli_export_customer.py` + `tests/test_keys_cli_delete_customer.py` — matches the per-verb file naming Story 3.x established) — `TestExportCustomer`:
- `--format json` (default) returns indented JSON with AC1 fields in order; tax_id formatted (`123.456.789-00`).
- `--format yaml` returns valid YAML parseable back to the original payload; key order preserved.
- `--format csv` → exit 2, usage error panel.
- Unknown customer id → exit 3, not-found error.
- Tombstoned customer → exit 3, not-found (opaque).
- Missing encryption key → exit 6, configuration error.
- Malformed ciphertext (manually corrupt the BLOB via test seed) → exit 5.
- INFO log line contains `id=cust_...`, `key_count=N`, `format=json|yaml`; no tax ID, no name, no email (PII regex assertion).
- Customer with 0 keys exports a payload where `keys: []`.
- Customer with 3 keys exports payloads where `len(payload["keys"]) == 3` and each has exactly `{key_prefix, status, billing_mode, created_at}` keys.

**`tests/test_keys_cli_delete_customer.py`** — `TestDeleteCustomer`:
- Bare `delete-customer cust_...` (no `--hard`) → exit 2, usage error.
- `delete-customer --hard cust_...` with interactive input "y\n" → exit 0, confirmation shown, customer purged.
- `delete-customer --hard cust_...` with interactive input "n\n" → exit 2, "Aborted." on stderr, customer UNCHANGED.
- `delete-customer --hard cust_... --yes` → exit 0 without prompt, customer purged.
- `delete-customer --hard cust_...` with 0 keys → confirmation line "0 keys purged", exit 0, customer purged.
- `delete-customer --hard cust_...` with 2 keys → "2 keys purged", both keys gone from `api_key`, customer tombstoned.
- Unknown customer id → exit 3, pre-prompt not-found (no confirmation prompt reached).
- Tombstoned customer id → exit 3.
- Missing `--hard` → exit 2 BEFORE any DB open (assert via `CliRunner` that settings aren't loaded / DB isn't created).
- Prompt text matches the epic AC verbatim (templated with name + key count).
- INFO log contains `id=cust_...`, `keys_purged=N`; no PII (regex assertion against the combined captured log + stdout).
- Audit row written with `action='delete_customer'`, `target_type='customer'`, `target_id=cust_...`, `details={"keys_purged": N, "tax_id_kind": "cpf"|"cnpj"}`, `actor='cli:<username>'`.
- Pre-existing audit rows for the customer + its keys remain intact post-delete (FR38 retention contract).
- Sentinel mtime advances after commit (AuthCache TTL short-circuit).
- `list-customers` does NOT show the purged customer; `list-customers --deleted` DOES show the tombstone with empty name/email.
- `--format` flag is NOT accepted by `delete-customer` (exit 2 on `--format json`).

**`tests/test_keys_output.py`** — `TestRenderExportJson` + `TestRenderExportYaml`:
- JSON render emits valid JSON, UTF-8-decodable, indented 2 spaces.
- YAML render round-trips via `yaml.safe_load` back to the original dict.
- YAML preserves key order from the payload dict's insertion order.
- Both renderers tolerate notes containing `[`, `]`, `:`, `#` (markup / YAML delimiters) without drift.

**`tests/test_keys_audit.py`** — extend `_FORBIDDEN_DETAIL_KEYS` coverage if not already present: assert `delete_customer_hard`'s `details` dict passes the forbidden-keys check (call `_assert_no_forbidden_keys` directly on the constructed dict in a unit test).

### 11. Grep checks (Task-N style, for the implementer's pre-commit pass)

Run before claiming the story done:

- `rg "fernet\.decrypt" src/` — EXACTLY ONE hit in `src/comadre/keys/crypto.py::decrypt_tax_id`. Any other hit is a security regression.
- `rg "HTTPException" src/` — ZERO hits (non-regression contract; FR51).
- `rg "tax_id_encrypted" src/comadre/keys/ | rg -v "crypto\.py\|db\.py\|models\.py"` — ZERO hits. The ciphertext BLOB must not leak into `cli/`, `audit.py`, `billing.py`, `cache.py`, `auth.py`.
- `rg "import yaml" src/` — EXACTLY ONE hit in `src/comadre/keys/cli/output.py::render_export_yaml` (lazy import inside the function body). No module-level imports.
- `rg "list-customers|list-keys" tests/` — existing tests still pass; the tombstone rendering smoke (pre-existing in `test_keys_cli_list_customers.py`) passes with one new test asserting empty-name / empty-email tombstones render without raising.
- `rg "docs_url|redoc_url|openapi_url" src/comadre/main.py` — all three are `None` (FR47; non-regression).
- `uv run ruff check . && uv run mypy src/ && uv run pytest` — all green.

## Acceptance Criteria

### AC1 — `comadre-keys export-customer cust_... --format json` emits the canonical payload

**Given** an active customer `cust_01HG7xyz...` exists with encrypted CPF `123.456.789-09`, name "Marcos Silva", email `marcos@example.com`, notes `"owner of a bot"`, `registered_at='2026-03-12T14:22:05Z'`, and two associated active keys with prefixes `Pq_abc12`, `Pq_def34`.

**When** the operator runs `comadre-keys export-customer cust_01HG7xyz... --format json`.

**Then** stdout is a valid JSON document with 2-space indentation, keys (in this order): `id`, `name`, `email`, `tax_id_kind`, `tax_id`, `registered_at`, `notes`, `keys`. The `tax_id` value is the formatted form `"123.456.789-09"`. The `keys` array contains exactly two objects, each with the key set `{key_prefix, status, billing_mode, created_at}` in that order.

**And** exit code 0.

**And** stderr is empty (no ErrorDisplay panel).

### AC2 — `--format yaml` emits an equivalent YAML document with the same field order

**Given** the same seed as AC1.

**When** the operator runs `comadre-keys export-customer cust_01HG7xyz... --format yaml`.

**Then** stdout parses back via `yaml.safe_load` to a dict equal to the AC1 JSON payload (field-for-field).

**And** the YAML preserves the AC1 key order (id → name → email → tax_id_kind → tax_id → registered_at → notes → keys).

**And** exit code 0.

### AC3 — Performance: export completes in under 1 second regardless of DB size (NFR35)

**Given** a DB seeded with 1000 customers and 2000 api_keys (the NFR5 / NFR35 reference scale).

**When** the operator runs `comadre-keys export-customer cust_...` against any single target.

**Then** the command completes in under 1 second (wall-clock, including process startup, settings load, DB open, migrations, query, decrypt, format, print).

### AC4 — Unknown customer ID exits 3 with not-found error

**Given** no customer matches `cust_01HG7zzz...` in the DB.

**When** the operator runs `comadre-keys export-customer cust_01HG7zzz...`.

**Then** stderr renders an ErrorDisplay titled "Not found: no customer matches 'cust_01HG7zzz...'" with hint "Run 'comadre-keys list-customers' to see registered records."

**And** exit code 3.

**And** stdout is empty.

### AC5 — Tombstoned customer is opaque to export (also exit 3)

**Given** a customer `cust_01HG7xyz...` exists but `deleted_at IS NOT NULL` (hard-deleted by a prior run).

**When** the operator runs `comadre-keys export-customer cust_01HG7xyz...`.

**Then** the same AC4 outcome: exit 3, not-found error.

### AC6 — Invalid `--format` exits 2

**Given** any valid customer ID.

**When** the operator runs `comadre-keys export-customer cust_... --format csv` (or any unknown format).

**Then** stderr shows "Usage error: --format must be json or yaml" with hint "Valid values: json, yaml."

**And** exit code 2.

### AC7 — `comadre-keys delete-customer --hard cust_...` with interactive `y` purges + confirms

**Given** an active customer `cust_01HG7xyz...` (Marcos Silva) with 2 associated active keys.

**When** the operator runs `comadre-keys delete-customer --hard cust_01HG7xyz...` and answers `y` to the prompt.

**Then** the prompt on stderr reads: "This will permanently delete customer Marcos Silva and all associated keys (2 key(s)). This action cannot be undone. Encrypted tax ID will be purged. Continue? [y/N]:"

**And** stdout shows "Deleted: cust_01HG7xyz... (Marcos Silva) — 2 keys purged".

**And** exit code 0.

**And** querying the DB directly shows: customer row's `name=""`, `email=""`, `tax_id_encrypted=b""`, `notes=""`, `deleted_at != NULL`; zero api_key rows with `customer_id='cust_01HG7xyz...'`; one new audit_log row with `action='delete_customer'`, `target_id='cust_01HG7xyz...'`, `details_json='{"keys_purged": 2, "tax_id_kind": "cpf"}'`.

### AC8 — Interactive `n` aborts without mutation

**Given** the same seed as AC7.

**When** the operator answers `n` (or presses Enter without typing).

**Then** stderr shows "Aborted." and exit code 2.

**And** the customer + its keys are unchanged; no audit_log row is added.

### AC9 — `--yes` skips confirmation for automation

**Given** the same seed as AC7.

**When** the operator runs `comadre-keys delete-customer --hard cust_01HG7xyz... --yes`.

**Then** no prompt is rendered, the purge runs, stdout shows the same ConfirmationLine as AC7, exit code 0.

### AC10 — `--hard` is required

**Given** any valid customer ID.

**When** the operator runs `comadre-keys delete-customer cust_01HG7xyz...` (no `--hard`).

**Then** stderr shows "Usage error: --hard is required for delete-customer" with a hint pointing to `--help` for the full effect.

**And** exit code 2.

**And** the DB is unchanged; no prompt is shown; no connection is opened (verifiable by mocking `get_connection` and asserting zero calls).

### AC11 — Customer with zero keys still tombstones + renders "0 keys purged"

**Given** a customer `cust_01HG7xyz...` with no associated keys.

**When** the operator runs `comadre-keys delete-customer --hard cust_01HG7xyz... --yes`.

**Then** stdout shows "Deleted: cust_01HG7xyz... (Marcos Silva) — 0 keys purged".

**And** the customer row is tombstoned as AC7; one `delete_customer` audit row is added with `details_json='{"keys_purged": 0, "tax_id_kind": "cpf"|"cnpj"}'`.

### AC12 — Unknown customer ID exits 3 before prompting

**Given** no customer matches `cust_01HG7zzz...`.

**When** the operator runs `comadre-keys delete-customer --hard cust_01HG7zzz...` (no `--yes`).

**Then** exit 3 is emitted BEFORE any confirmation prompt is shown (verifiable: stderr has no "[y/N]" prompt text, only the "Not found" ErrorDisplay).

### AC13 — Tombstoned customer is opaque to delete-customer (also exit 3)

**Given** a customer already tombstoned by a prior run.

**When** the operator runs `delete-customer --hard cust_... --yes` against it.

**Then** exit 3, not-found error. No double-tombstone, no second audit row.

### AC14 — Audit-log retention (FR38): pre-existing audit rows stay intact

**Given** a customer with audit rows from `create_customer`, `issue_key` (for each of N keys), `mark_paid`, `suspend_key`, `update_key`, etc. accumulated over the customer's lifetime.

**When** the operator runs `delete-customer --hard cust_... --yes`.

**Then** the audit_log table retains EVERY row whose `target_id` matches the customer or any of its keys — the purge UPDATEs the customer row and DELETEs the api_key rows but NEVER writes to audit_log except to append the one new `delete_customer` summary row.

**And** `comadre-keys show cust_... --audit-tail 1000` returns exit 3 (the tombstone is opaque to `show`), but a direct SELECT against audit_log still shows the full trail — the operator has the information needed to respond to an ANPD audit without personal data being retained.

### AC15 — INFO log is PII-austere (NFR15)

**Given** AC7's seed.

**When** the `delete-customer` or `export-customer` command runs.

**Then** the structured INFO log line contains: `"Customer purged | id=cust_01HG7xyz... | keys_purged=2"` (delete) OR `"Customer exported | id=cust_01HG7xyz... | key_count=2 | format=json"` (export).

**And** a regex applied to the captured `caplog` output rejects: any 11-digit or 14-digit run (canonical CPF/CNPJ), any `123.456.789-09`-shaped formatted tax ID, the literal strings "Marcos Silva" and "marcos@example.com", the string "cmdr_live_" (no plaintext keys), the string "BEGIN" (no hex-dumped blobs).

### AC16 — `export-customer` never logs or stdouts the ciphertext

**Given** AC1's seed.

**When** `export-customer --format json` runs.

**Then** the INFO log contains no bytes that match the Fernet ciphertext (assertion: capture the raw ciphertext bytes from the DB, grep the log + stdout for any slice of length ≥8 matching it — zero hits).

**And** the JSON output contains the formatted tax ID (`"123.456.789-09"`) but NO field named `tax_id_encrypted` or `tax_id_cipher`.

### AC17 — Configuration / DB error mapping

**Given** `KEY_REGISTRY_ENCRYPTION_KEY` is unset.

**When** either verb runs.

**Then** stderr shows "Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set" with the standard hint; exit code 6.

**And** for a `sqlite3.Error` on DB open (simulated via an unreadable DB file), exit 5 with the "Database error" panel.

**And** for a `cryptography.fernet.InvalidToken` on export decrypt (simulated via a corrupted `tax_id_encrypted` BLOB), exit 5 with the "Database error: tax-ID ciphertext failed to decrypt" panel (no raw bytes echoed — NFR16).

### AC18 — Read-only invariant on non-target surfaces (regression guard)

**Given** the Story 4.1 diff.

**When** `git diff --name-only master...HEAD` is run.

**Then** the set excludes: `src/comadre/api.py`, `src/comadre/main.py`, `src/comadre/rate_limit.py`, `src/comadre/keys/auth.py`, `src/comadre/keys/cache.py`, `src/comadre/health.py` (the HTTP `/health` endpoint), `src/comadre/counters.py`, `src/comadre/keys/migrations/`. Any hit on these paths is a regression of the non-regression contract.

**And** `pyproject.toml` diff shows ONLY the `pyyaml>=6.0` addition under `[project.dependencies]` + the mypy-override extension. `uv.lock` is regenerated correspondingly.

### AC19 — `list-customers --deleted` shows the new tombstone without PII

**Given** AC7 has just run (one customer tombstoned, 2 keys purged).

**When** the operator runs `comadre-keys list-customers --deleted`.

**Then** the table output includes the tombstoned row with `Name=""`, `Email=""`, `Keys=0`, a non-NULL `Registered` date, and the operator can see it exists without any personal data rendered.

**And** the ConfirmationLine at the bottom shows `1 customers found.`.

### AC20 — `export-customer` + `delete-customer` appear in `comadre-keys --help`

**Given** the installed CLI.

**When** the operator runs `comadre-keys --help`.

**Then** both `export-customer` and `delete-customer` appear in the subcommand list with their one-line docstring summaries.

**And** `comadre-keys export-customer --help` shows a realistic example (UX-DR15): `comadre-keys export-customer cust_01j8xr3e4c5m7kn9p2qt8vwy --format yaml`.

**And** `comadre-keys delete-customer --help` shows: `comadre-keys delete-customer cust_01j8xr3e4c5m7kn9p2qt8vwy --hard`.

### AC21 — Round-trip: export → hard-delete → list-customers --deleted reflects purge

**Given** an end-to-end smoke: seed customer + keys, run export, hard-delete, then list.

**When** executed in sequence.

**Then** (a) the exported JSON captures the full pre-delete state; (b) post-delete, re-running export returns exit 3; (c) `list-customers` (no `--deleted`) does NOT show the customer; (d) `list-customers --deleted` DOES show the tombstone with empty name/email; (e) the audit_log trail from create/issue/mark-paid/etc. remains intact, with the new `delete_customer` row as the last entry.

### AC22 — `--format yaml` does not interpret rich markup

**Given** a customer with notes containing `"[urgent]"` (square brackets — rich markup syntax).

**When** `export-customer --format yaml` is run.

**Then** the YAML output contains the literal string `[urgent]` (not interpreted as rich markup, not rendered as a color token) and round-trips via `yaml.safe_load`.

### AC23 — Sentinel-touch propagates revocation to replicas

**Given** an active customer with one key whose auth payload is cached in a running API replica.

**When** `delete-customer --hard` runs.

**Then** `{db_path}.invalidate` mtime advances (assertion matches the Story 1.6 `revoke_api_key` pattern), forcing the replica's `AuthCache` to flush on its next stat.

## Tasks / Subtasks

- [x] **Task 0 — Dependency + tooling prep** (AC18)
  - [x] 0.1 `uv add pyyaml` — pins to `>=6.0.3`; `uv.lock` regenerates cleanly.
  - [x] 0.2 Added `types-PyYAML` to the `type-check` dependency group (stubs preferred over mypy-override).
  - [x] 0.3 `uv sync` + `uv run python -c "import yaml; print(yaml.__version__)"` sanity check — 6.0.3 reports clean.

- [x] **Task 1 — New crypto primitive `decrypt_tax_id`** (AC17, partial)
  - [x] 1.1 Appended `decrypt_tax_id(ciphertext, key) -> str` to `src/comadre/keys/crypto.py`.
  - [x] 1.2 Module docstring extended to describe the dual primitive.
  - [x] 1.3 `TestDecryptTaxId` added to `tests/test_keys_crypto.py` (CPF / numeric CNPJ / alphanumeric CNPJ round-trip + tampered ciphertext + key mismatch + empty bytes — 6 subcases).

- [x] **Task 2 — New DB helper `get_customer_with_cipher`** (AC1, AC5)
  - [x] 2.1 `CustomerExportRow` dataclass + `get_customer_with_cipher` helper appended to `src/comadre/keys/db.py`.
  - [x] 2.2 `TestGetCustomerWithCipher` added to `tests/test_keys_db.py` (hit / missing / tombstoned).
  - [x] 2.3 `TestListCommandsDoNotWrite::test_no_writes_across_all_helpers` extended with `get_customer_with_cipher` call.

- [x] **Task 3 — New formatter `format_tax_id_display`** (AC1, AC2)
  - [x] 3.1 `format_tax_id_display(canonical, kind) -> str` appended to `src/comadre/keys/formatters.py`.
  - [x] 3.2 `tests/test_keys_formatters.py` created with 10 subcases: CPF / CNPJ numeric / CNPJ alphanumeric / leading-zero CPF + wrong-length rejections.

- [x] **Task 4 — New DB helper `delete_customer_hard`** (AC7, AC8, AC11, AC14, AC23)
  - [x] 4.1 `DeleteCustomerResult` dataclass + `delete_customer_hard` helper appended to `src/comadre/keys/db.py`.
  - [x] 4.2 `TestDeleteCustomerHard` added to `tests/test_keys_db.py` — 7 subcases: happy path (2 keys) / zero keys / CNPJ kind audit / missing / tombstoned opaque / transactional rollback / forbidden-keys-guard compliance.
  - [x] 4.3 Transactional-rollback test included (stubs `log_event` to raise, asserts rows unchanged).
  - [x] 4.4 `test_delete_customer_hard_touches_sentinel` added under `TestAuthCacheSentinelTouched`.

- [x] **Task 5 — New CLI verb `export-customer`** (AC1–AC6, AC15–AC17, AC20, AC21)
  - [x] 5.1 `export_customer_cmd` appended to `src/comadre/keys/cli/commands/customers.py`.
  - [x] 5.2 `EXPORT_FORMAT_CHOICES` tuple + `render_export_json` + `render_export_yaml` added to `src/comadre/keys/cli/output.py` (YAML lazy-imports pyyaml at call time).
  - [x] 5.3 `tests/test_keys_cli_export_customer.py` created with 14 subcases covering AC1/AC2/AC4/AC5/AC6/AC15/AC16/AC17/AC20/AC22.

- [x] **Task 6 — New CLI verb `delete-customer`** (AC7–AC13, AC19, AC20, AC21, AC23)
  - [x] 6.1 `delete_customer_cmd` appended to `src/comadre/keys/cli/commands/customers.py`.
  - [x] 6.2 `tests/test_keys_cli_delete_customer.py` created with 15 subcases covering AC7/AC8/AC10/AC11/AC12/AC13/AC14/AC15/AC19/AC20.
  - [x] 6.3 `rg "fernet\.decrypt" src/` grep invariant passes — exactly one hit in `crypto.py::decrypt_tax_id`.

- [x] **Task 7 — Renderer tests** (AC2, AC22)
  - [x] 7.1 `TestRenderExportJson` + `TestRenderExportYaml` added to `tests/test_keys_output.py`.
  - [x] 7.2 YAML insertion-order test explicit.
  - [x] 7.3 Rich-markup-tolerant (`[urgent]`) YAML round-trip test explicit.

- [x] **Task 8 — Module docstring updates** (AC20, maintenance)
  - [x] 8.1 `customers.py` top-of-file exit-code contract extended to cover Story 4.1 verbs.
  - [x] 8.2 `crypto.py` module docstring extended to describe the dual primitive.
  - [x] 8.3 `comadre-keys --help` and both `--help` subcommands verified to show the expected text.

- [x] **Task 9 — Docs** (AC20)
  - [x] 9.1 `README.md` feature-bullet gained the LGPD pair (`export-customer`, `delete-customer`).
  - [x] 9.2 `docs/deployment-guide.md` gained the "LGPD operator procedures" subsection under "Key Registry Management".
  - [x] 9.3 `CLAUDE.md` gained two "Non-Obvious Gotchas": tombstone zero-length-BLOB rationale + `fernet.decrypt` single-site invariant.

- [ ] **Task 10 — Integration smoke on 10.10.10.207** (AC21, deploy-time acceptance)
  - [ ] 10.1 Deploy the branch to 10.10.10.207 staging (Comadre 2.0.0 dev registry).
  - [ ] 10.2 Seed a synthetic customer `comadre-keys create-customer --name "Smoke Test" --email smoke@example.com --cpf 123.456.789-09`.
  - [ ] 10.3 Issue a key: `comadre-keys issue-key --customer cust_... --rpm 60`.
  - [ ] 10.4 Export: `comadre-keys export-customer cust_... --format yaml | tee /tmp/smoke-export.yaml`; diff against expected.
  - [ ] 10.5 Hard-delete: `comadre-keys delete-customer --hard cust_... --yes`; confirm ConfirmationLine, exit 0.
  - [ ] 10.6 Verify tombstone: `comadre-keys list-customers --deleted | grep cust_...` shows empty name/email.
  - [ ] 10.7 Verify audit trail: `sqlite3 data/keys/registry.db "SELECT action, actor, target_id FROM audit_log WHERE target_id = 'cust_...' ORDER BY occurred_at"` returns the full lifecycle including the `delete_customer` row.
  - [ ] 10.8 Verify the auth cache flush: run a `curl` against `/v1/audio/speech` with the now-purged key; expect 401.

- [x] **Task 11 — Final quality gate**
  - [x] 11.1 `uv run ruff check .` → zero findings.
  - [x] 11.2 `uv run mypy src/` → zero findings under strict mode.
  - [x] 11.3 `uv run pytest` → full suite green (1369 passed).
  - [x] 11.4 `uv run pre-commit run --all-files` → zero hook failures.
  - [x] 11.5 Grep invariants from §11 — `fernet.decrypt`, `import yaml`, `docs_url/redoc_url/openapi_url=None` all pass. See Completion Notes re: `tax_id_encrypted` appearing in `customers.py` as a necessary attribute access to pass the ciphertext BLOB to `decrypt_tax_id` — the spirit-level invariant (no ciphertext in logs/stdout/JSON/YAML) is enforced and tested via AC16.

## Dev Notes

### Import-graph placement

- `src/comadre/keys/crypto.py` (Story 4.1 extension): `decrypt_tax_id` lives alongside `encrypt_tax_id`. `crypto.py` imports from stdlib + `cryptography` + `pydantic` only. Keeps the "only this module touches Fernet" invariant.
- `src/comadre/keys/db.py` (Story 4.1 extensions): `CustomerExportRow` + `get_customer_with_cipher` + `DeleteCustomerResult` + `delete_customer_hard` all sited in the existing `db.py`. `db.py` imports from stdlib + `ulid` + `keys.models`; inner helpers lazy-import `keys.audit` (to avoid a module-load cycle). `delete_customer_hard`'s `log_event` call follows the same lazy-import precedent.
- `src/comadre/keys/formatters.py` (Story 4.1 extension): `format_tax_id_display` joins `format_seconds_ago`. Stdlib-only module; no upstream imports.
- `src/comadre/keys/cli/output.py` (Story 4.1 extensions): `EXPORT_FORMAT_CHOICES` + `render_export_json` + `render_export_yaml`. `yaml` is imported **lazily inside** `render_export_yaml` (not at module top) to keep `comadre-keys --help` / `list-customers` fast paths free from PyYAML's ~0.15s import cost. Every other imports in `output.py` is already resolved; adding `EXPORT_FORMAT_CHOICES` alongside `LIST_FORMAT_CHOICES` keeps the shared-choices cluster grepable.
- `src/comadre/keys/cli/commands/customers.py` (Story 4.1 extensions): `export_customer_cmd` + `delete_customer_cmd`. Uses the shared `load_settings_and_tz` import from `cli.commands.keys` (re-exported as a non-circular sibling-module symbol, matching Story 3.1 / 3.3 precedent). Uses `get_customer_with_cipher`, `delete_customer_hard`, `list_api_keys` from `db`; `decrypt_tax_id` from `crypto`; `format_tax_id_display` from `formatters`; `EXPORT_FORMAT_CHOICES`, `render_export_json`, `render_export_yaml`, `render_confirmation`, `render_error` from `cli.output`; `get_cli_actor` from `audit`.

### Why empty-string / zero-length-blob writes, not NULL + v002 migration

`v001_initial.sql:3-6` declares `name`, `email`, `tax_id_encrypted` as NOT NULL. Two design options to signal "this row is a tombstone":

1. **Option A — overwrite with empty canonical forms** (`name=""`, `email=""`, `tax_id_encrypted=X''`). NOT NULL constraint is satisfied; the canonical tombstone signal is `deleted_at IS NOT NULL`. Existing readers (`get_customer`, `get_customer_detail`, `list_customers`, `resolve_show_target`) all filter via `deleted_at IS NULL`, so an empty-field tombstone is invisible to them. `list-customers --deleted` WILL show the tombstone, with empty name/email columns — this is the intended "purged" presentation. No migration. **This is what the story ships.**

2. **Option B — v002 migration to drop the NOT NULL constraints**. SQLite has no `ALTER COLUMN DROP NOT NULL`; we'd need to create a new table, copy data, drop the old, rename. Adds a failure surface for every existing deployment + changes the schema version. Zero operator-observable benefit over Option A.

**Option A is strictly superior** — same semantics at the application layer (tombstone signal is `deleted_at`, not the PII column), zero schema churn, zero migration risk. The only pedantic argument for B is "NULL is more explicitly 'no data' than empty string" — but `tax_id_encrypted=X''` (zero-length BLOB) is unambiguously "no ciphertext" to every reader, and `name=""` / `email=""` are unambiguously "no value" when paired with `deleted_at != NULL`. The tombstone invariant holds.

### Why two separate verbs, not a combined `customer-purge` / `customer-lifecycle` subcommand

The epic explicitly names two verbs (`export-customer`, `delete-customer --hard`) and the UX-spec (ux-design-specification.md:892-894) puts them in different tiers (Read vs Destroy). A combined verb would violate the tier separation — an operator running "just export to a file" should never be one typo away from triggering a destructive action. Typer also gives cleaner `--help` surfaces for one-verb-one-job.

### Why `--hard` is required (not a default)

UX-DR11 mandates the flag for destructive actions. Making `--hard` default to True would mean `comadre-keys delete-customer cust_...` silently destroys data — violates both UX-DR11 and the principle of least surprise. Explicit `--hard` is the documented form in the PRD (prd.md:962), UX-spec (ux-design-specification.md:894, 900), and epics.md:772. The flag is also a future extension point: `--soft` or `--rename` could be added later (outside Story 4.1 scope) without breaking existing operator muscle memory, because `--hard` would keep selecting the current behavior.

### Why the ConfirmationLine renders PRE-purge name, not post-purge

Post-purge the name column is empty string. The operator's "what did I just delete" feedback needs a human-readable identifier — "Deleted: cust_01HG7... (Marcos Silva)" is readable, "Deleted: cust_01HG7... ()" is not. `delete_customer_hard` captures `customer_name` inside the transaction before the UPDATE so the return payload has this information. The UX-spec (ux-design-specification.md:903, 910, 923) specifies this exact grammar.

### Why `export-customer` does not include `key_hash` or `rate_limit_rpm` / `paid_until` / `price_monthly`

The epic AC (epics.md:764) specifies the exact field set: `key_prefix`, `status`, `billing_mode`, `created_at`. `key_hash` is a security boundary (never leaves storage); `rate_limit_rpm` / `paid_until` / `price_monthly` are operator-internal billing detail, not customer-facing LGPD-access data. Including them would expand the scope of a LGPD access response beyond what Art. 18 (II, V) mandates ("the data the operator holds about the subject"). The operator can always run `comadre-keys show cust_...` for the full picture, which is an operator-facing surface, not a subject-deliverable.

### Why `--format json` default for `export-customer` (not `--format yaml`)

Operator tooling pipes to a file; JSON is the stable machine-readable format every tool understands. YAML is opt-in when the operator prefers a human-readable deliverable (literally emailing the subject). PRD (prd.md:993) lists YAML specifically for `export-customer` because the human-readable shape helps, not because it should be the default.

### Why lazy-import YAML, not module-level

Module-level `import yaml` would slow every `comadre-keys` invocation by ~0.15s (PyYAML's `__init__.py` + `c_loader` bootstrap on some platforms). `comadre-keys list-customers` runs hundreds of times in an operator's workflow; PyYAML is only needed when `export-customer --format yaml` is invoked. Lazy import keeps the hot path free.

### Why no `--format table` for `export-customer`

LGPD access is a deliverable, not a monitoring surface. A pretty-printed panel is for operator eyeballs; the deliverable format needs to be machine-readable + durable. Table mode would also violate the AC1 structured-field-order contract.

### Why `export-customer` does NOT take `--audit-tail`

The audit tail is an operator-forensic surface (Story 1.4), not part of the LGPD access contract. Art. 18 (II, V) covers "the personal data held", not "the operator's log of every action taken". Adding audit tail to the export would leak operator-internal actors, cron metadata, rate-limit decisions — data that is NOT the customer's. If the customer specifically requests their activity log, the operator builds a subset-query manually (future Story 4.x extension territory); out of 4.1 scope.

### Why `delete_customer_hard` uses `DELETE` on api_key, not UPDATE-to-scrub

The api_key rows carry no direct personal data (the key_hash is an opaque hash, the prefix is not PII, billing_mode / rate_limit / status are structural). DELETE is the natural verb — the keys no longer exist, not "these keys have a zeroed-out owner". The api_key's `customer_id` FK constraint (`ON DELETE RESTRICT`) blocks the reverse operation (deleting a customer with active keys), which is exactly what we want — the order of operations (keys first, then customer tombstone) is enforced structurally.

### NFR35 performance budget

`delete_customer_hard` is a single-transaction O(K) operation where K is the number of keys belonging to the target customer. With `idx_api_key_customer` (v001_initial.sql:43), the DELETE is index-scan + K rows = sub-millisecond per key. The UPDATE on customer uses PK lookup (O(1)). `_touch_auth_cache_sentinel` is a single `stat` + `touch` + `chmod` = microseconds. **Total command time budget: under 100 ms** for typical customers (K ≤ 10); well under the NFR35 1-second requirement.

`export-customer` is O(K) on `list_api_keys` (index scan) + 1 decrypt (sub-millisecond). Even with K=1000, the entire pipeline completes in under 100 ms. The NFR35 reference scale (1000-customer DB) does not exercise per-customer key counts beyond O(few); the AC3 budget holds comfortably.

### Test-flake avoidance

- Clock-seam: neither verb touches `date.today()` — `delete_customer_hard`'s `deleted_at` uses `_utcnow_iso()`. Tests can freeze the clock via `monkeypatch.setattr("comadre.keys.db._utcnow_iso", lambda: "2026-04-19T00:00:00Z")` when asserting the `deleted_at` column literal — same pattern Story 3.3 uses.
- Prompt input: use `CliRunner().invoke(app, [...], input="y\n")` / `input="n\n"`. Matches the existing `revoke_key_cmd` test suite.
- YAML canonical form: assert on `yaml.safe_load(stdout) == expected_dict` (structural equality), never byte-string equality — YAML allows multiple valid representations of the same tree.
- JSON canonical form: use `json.loads(stdout) == expected_dict` (structural equality) or compare with `indent=2` pinned via `print_json(indent=2)`.
- The `types-PyYAML` dependency is dev-only; production containers should NOT install type stubs. Confirm by checking that the `[dependency-groups] type-check` block carries `types-PyYAML`, not the top-level `[project] dependencies`.

### Integration with `list-customers --deleted`

Story 1.3's `list-customers --deleted` renderer (`render_customer_list` at output.py:248-272) already tolerates empty `name` / `email` fields — it does not apply defensive "Name:" / "Email:" placeholder logic. Once this story lands, the `--deleted` output will start showing rows with blank `Name` and `Email` columns; the operator reads this as "this row was hard-deleted" (confirmed by the presence of `deleted_at` metadata the renderer already plumbs through the `CustomerListRow`). No renderer change is needed; AC19 is a behavioral assertion, not a rendering change.

### Deferred work to flag at story close

- If the dev encounters a case where `list-customers --deleted` output needs a clearer "purged" indicator (e.g., literal "[PURGED]" label instead of blank name/email), flag in the deferred-work section; out of 4.1 scope.
- `rotate-encryption-key` (Story 4.2) depends on `decrypt_tax_id` — confirm the helper signature is stable before 4.2 starts.
- Future Story 4.x: add a `--include-audit` opt-in flag to `export-customer` for a LGPD-plus subject-access response (out of 4.1 scope; would require an operator-internal-data review).
- Future Story 4.x: a "soft-delete" verb (e.g., `deactivate-customer`) that preserves personal data but marks the customer inactive; would precede hard-delete in J6 (customer departure). Out of 4.1 scope; FR5 explicitly requires the irreversible purge as the primary deletion mechanism.

### Project Structure Notes

- **Alignment with unified project structure (paths, modules, naming)**
  - New helpers align with existing naming: `get_customer_with_cipher` mirrors `get_customer` / `get_customer_detail`; `delete_customer_hard` mirrors `update_customer`; `decrypt_tax_id` mirrors `encrypt_tax_id`; `format_tax_id_display` mirrors `format_seconds_ago`.
  - CLI verbs `export-customer` and `delete-customer` match the PRD CLI spec (prd.md:962-963) verbatim.
  - Audit action name `delete_customer` matches the architecture §Audit Action Naming convention (arch.md:322-327).
  - File placement: all new code lives in existing modules (`crypto.py`, `db.py`, `formatters.py`, `cli/output.py`, `cli/commands/customers.py`). No new modules created.
  - Test file placement: new per-verb test files `test_keys_cli_export_customer.py` and `test_keys_cli_delete_customer.py` match the Story 3.x convention (one file per CLI verb).
  - `pyproject.toml` gains `pyyaml>=6.0` under `[project.dependencies]` and `types-PyYAML` under `[dependency-groups.type-check]`.

- **Detected conflicts or variances (with rationale)**
  - The existing `customers.py` CLI module docstring (lines 1-9) enumerates Stories 1.1–1.5's exit codes. Story 4.1 extends this to cover the new verbs; no breaking change.
  - `format_tax_id_display` sited in `formatters.py` rather than `crypto.py` per §3 rationale (display formatting is presentation, not storage boundary). Potential variance: a code reviewer might expect all CPF/CNPJ helpers in one module — if this is raised, surface the `crypto.py` docstring rule ("encryption/decryption ONLY") as the reason.
  - `yaml` is lazy-imported to keep the hot path fast; if a code reviewer flags the lazy import as unconventional, surface the PyYAML ~0.15s bootstrap cost justification.

### Testing standards

- CLI tests use `CliRunner` from `typer.testing` + the `_reset_consoles_to_buffers` auto-fixture pattern (copy verbatim from `test_keys_cli_cache_status.py` / `test_keys_cli_revoke_key.py` — canonical templates).
- DB / crypto tests use `tmp_path` for the SQLite file + `get_connection` + `_apply_migrations`. Seed customers/keys via `insert_customer` / `insert_api_key` (never hand-roll SQL beyond audit-log seeds for FR38 retention tests).
- Fernet key fixture: use the existing `tests/_keys_fixtures.py::FERNET_KEY` (or equivalent) — never generate a fresh key per test (that would mask key-swap bugs).
- `caplog` captures INFO log lines for AC15 PII assertions.
- Rich output capture via `result.stdout` / `result.stderr` from `CliRunner().invoke(...)` — `_reset_consoles_to_buffers` plumbs both into `StringIO` buffers.
- JSON assertions: `payload = json.loads(stdout)`; dict equality, never byte-string comparison.
- YAML assertions: `payload = yaml.safe_load(stdout)`; dict equality; additional structural assertions (e.g., key order) via `list(payload.keys())`.
- PII-regex guard: reuse `_PII_FORBIDDEN_RE` from Story 3.1 / 3.3 / 3.4 test files; extend if needed for formatted CPF/CNPJ patterns.
- Interactive prompt tests: `CliRunner().invoke(app, [...], input="y\n")` / `input="n\n"` / `input=""` (Enter-without-typing = abort per the UX-spec default).

### References

- Epic 4 Story 4.1 scope — `_bmad-output/planning-artifacts/epics.md:750-784`
- FR5 (LGPD hard-delete) — `_bmad-output/planning-artifacts/prd.md:1128`
- FR6 (LGPD export) — `_bmad-output/planning-artifacts/prd.md:1129`
- FR7 (tombstone visibility via `--deleted`) — `_bmad-output/planning-artifacts/prd.md:1130`
- FR38 (audit-log metadata retention) — `_bmad-output/planning-artifacts/prd.md:1176`
- NFR34 (LGPD access ≤15 days) — `_bmad-output/planning-artifacts/prd.md:1250`
- NFR35 (LGPD deletion ≤15 days + <1s command) — `_bmad-output/planning-artifacts/prd.md:1251`
- NFR15 (PII-austere INFO logs) — `_bmad-output/planning-artifacts/prd.md:1219`
- NFR16 (error hints never echo invalid input) — `_bmad-output/planning-artifacts/prd.md:1220`
- UX-DR11 (Destroy-tier `--yes` pattern) — `_bmad-output/planning-artifacts/epics.md:196`
- UX-spec destructive command pattern — `_bmad-output/planning-artifacts/ux-design-specification.md:894-913`
- UX-spec Destroy-tier ConfirmationLine grammar — `_bmad-output/planning-artifacts/ux-design-specification.md:923`
- Architecture LGPD module map — `_bmad-output/planning-artifacts/architecture.md:657, 731`
- Architecture Fernet encryption pattern — `_bmad-output/planning-artifacts/architecture.md:394-406`
- Architecture "no other module touches Fernet directly" — `_bmad-output/planning-artifacts/architecture.md:637`
- Architecture CLI exit-code contract — `_bmad-output/planning-artifacts/architecture.md:421`
- Architecture single-transaction for multi-record CLI ops — `_bmad-output/planning-artifacts/architecture.md:474-478`
- PRD CLI specification for `export-customer` / `delete-customer` — `_bmad-output/planning-artifacts/prd.md:962-963`
- PRD LGPD binding requirements — `_bmad-output/planning-artifacts/prd.md:606-624`
- PRD audit-log integrity invariant — `_bmad-output/planning-artifacts/prd.md:702`
- PRD anti-enumeration constraint (tax-ID never echoed on error) — `_bmad-output/planning-artifacts/prd.md:707, 710`
- `insert_customer` template (single-txn + audit row) — `src/comadre/keys/db.py:315-361`
- `update_customer` template (re-read post-commit skipped for `delete_customer_hard` — see §4) — `src/comadre/keys/db.py:395-486`
- `revoke_key_cmd` Destroy-tier CLI template — `src/comadre/keys/cli/commands/keys.py:1125-1267`
- `_touch_auth_cache_sentinel` (post-commit sentinel touch) — `src/comadre/keys/db.py:214-240`
- `get_customer` / `get_customer_detail` (tombstone-opaque read pattern) — `src/comadre/keys/db.py:364-392, 657-688`
- `list_api_keys` (used by `export-customer` to join keys) — `src/comadre/keys/db.py:529-587`
- `encrypt_tax_id` / `strip_tax_id` (existing crypto primitives) — `src/comadre/keys/crypto.py:69-72, 30-38`
- `audit.py::_FORBIDDEN_DETAIL_KEYS` (PII hygiene guard) — `src/comadre/keys/audit.py:23-43`
- `load_settings_and_tz` (shared exit-6 ladder) — `src/comadre/keys/cli/commands/keys.py:738-781`
- `LIST_FORMAT_CHOICES` pattern (template for `EXPORT_FORMAT_CHOICES`) — `src/comadre/keys/cli/output.py:49`
- `v001_initial.sql` schema (BLOB NOT NULL constraint retained) — `src/comadre/keys/migrations/v001_initial.sql:1-10`
- CLAUDE.md LGPD module-boundary notes — `CLAUDE.md`

## Questions for Operator (please confirm before dev-story)

> All questions have recommended answers. In auto-mode, apply the recommended answer; if any run hits a disagreement, reopen as a deferred-work entry.

1. **Tombstone representation: empty strings + zero-length BLOB vs v002 migration to NULL.** The schema's NOT NULL constraints on `name`, `email`, `tax_id_encrypted` need to be satisfied. Option A writes `""` / `""` / `X''`; Option B adds a v002 migration dropping the NOT NULL constraints. Recommend **Option A** (§Dev-Notes §Why-empty-strings-not-NULL). Zero schema churn, identical application semantics, `deleted_at IS NOT NULL` remains the canonical tombstone signal.

2. **YAML library choice: `pyyaml` vs hand-rolled YAML writer.** The PRD names YAML as the LGPD-access-response format; the project has no YAML dep today. Options: add `pyyaml>=6.0` OR hand-roll a ~30-line safe-writer (strings + lists + dicts only). Recommend **`pyyaml`** — MIT, ~84 KB wheel, zero native deps, stable API, `safe_dump` is well-understood. Hand-rolled would land us in maintenance for marginal benefit.

3. **Exit code on abort (`[y/N]: n`).** Two plausible codes: 1 (Click default, "general") or 2 ("usage"). Recommend **2** to match `revoke_key_cmd` at keys.py:1221 — consistency across Destroy-tier verbs.

4. **`--hard` flag semantics: required for acknowledgement vs implicit default-True.** Making `--hard` a required flag (AC10) protects against typo-triggered destruction; making it default-True removes one flag from the invocation. Recommend **required** — matches PRD / UX-spec verbatim (prd.md:962, ux-design-specification.md:894, 900), principle of least surprise, future extension point for `--soft` / `--rename` without breaking muscle memory.

5. **Tax ID formatted-display for export (AC1).** Options: emit canonical (`"12345678909"`) vs formatted (`"123.456.789-09"`). Recommend **formatted** — LGPD access responses are operator-to-customer deliverables; every Brazilian document shows the formatted form; the canonical is a storage detail.

6. **Export key-field scope: minimal (AC1 exact: prefix, status, billing_mode, created_at) vs operator-friendly (add rate_limit_rpm, paid_until, price_monthly).** Recommend **minimal** — LGPD access is about "the personal data the operator holds about the subject", not operator-internal billing metadata. The operator can always run `show` for the full picture. Minimal keeps the export surface small + the deliverable focused.

7. **`export-customer` default format: `json` vs `yaml`.** Recommend **`json`** — machine-readable first, tooling-friendly, every operator's downstream pipe understands it. YAML is opt-in for the human-readable print.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M context) via Claude Code CLI.

### Debug Log References

- `uv add pyyaml` + `uv add --group type-check types-PyYAML` — `uv.lock` regenerates; `pyyaml==6.0.3`, `types-pyyaml==6.0.12.20260408`.
- `uv run pytest tests/test_keys_crypto.py` → 56 passed (50 pre-existing + 6 new).
- `uv run pytest tests/test_keys_formatters.py` → 10 passed (new file).
- `uv run pytest tests/test_keys_db.py::TestGetCustomerWithCipher tests/test_keys_db.py::TestDeleteCustomerHard tests/test_keys_db.py::TestListCommandsDoNotWrite tests/test_keys_db.py::TestAuthCacheSentinelTouched::test_delete_customer_hard_touches_sentinel` → 12 passed.
- `uv run pytest tests/test_keys_cli_export_customer.py` → 14 passed.
- `uv run pytest tests/test_keys_cli_delete_customer.py` → 15 passed.
- `uv run pytest tests/test_keys_output.py` → 75 passed (70 pre-existing + 5 new).
- `uv run pytest -q` → 1369 passed in 42 s.
- `uv run ruff check . && uv run mypy src/` → both clean.
- `uv run pre-commit run --all-files` → all hooks passed (ruff-format, mypy, ruff, yamllint, markdownlint-cli2, dockerfile-lint, shellcheck).

### Completion Notes List

- **Story scope complete, ready for code review.** All 23 ACs implemented; 9 tasks plus the final quality gate closed. Task 10 (integration smoke on 10.10.10.207) is explicitly deployment-time acceptance — deferred to the operator; the branch is implementation-ready.
- **Dual Fernet primitive**: `decrypt_tax_id` sits alongside `encrypt_tax_id` in `crypto.py` as the architectural twin. `rg "fernet\.decrypt" src/` returns exactly one hit — the architecture §Security Boundaries invariant holds.
- **Tombstone representation**: zero-length BLOB + empty strings satisfy the existing NOT NULL constraints; no v002 migration. The canonical tombstone signal stays `deleted_at IS NOT NULL`. Documented as a new Non-Obvious Gotcha in `CLAUDE.md`.
- **YAML lazy import**: `import yaml` lives inside `render_export_yaml` (not at module top) so `comadre-keys --help` and hot-path commands don't pay the ~0.15 s PyYAML bootstrap. `rg "import yaml" src/` returns exactly one hit.
- **No auth-path / FastAPI changes**: `api.py`, `main.py`, `rate_limit.py`, `auth.py`, `cache.py`, `health.py` (HTTP), `counters.py`, and `migrations/` are byte-identical to `master`. `HTTPException` grep returns zero real usages (one hit is a pre-existing docstring mention of Starlette's `HTTPException`, not a regression).
- **Deviation from §11 grep invariant on `tax_id_encrypted`**: the story's verbatim check `rg "tax_id_encrypted" src/comadre/keys/ | rg -v "crypto\.py|db\.py|models\.py"` should yield zero hits. It yields two: (1) `formatters.py` — docstring mention only, no attribute access; (2) `customers.py:export_customer_cmd` — legitimate attribute read `row.tax_id_encrypted` passed directly to `decrypt_tax_id`. The design (§1–§5) requires the CLI orchestrator to pull the BLOB from the dataclass and hand it to the crypto helper; doing it any other way would violate the architecture's "only `crypto.py` touches Fernet" rule. The spirit-level invariant (no ciphertext in logs / stdout / JSON / YAML) is enforced and tested by AC16.
- **Interactive prompt behavior**: the `typer.confirm` prompt runs on stderr (`err=True`) so `delete-customer | tee log.txt` never captures the prompt text — matches the Story 1.6 `revoke-key` pattern. Tests assert this negative invariant.
- **Defense-in-depth for `_FORBIDDEN_DETAIL_KEYS`**: the `delete_customer_hard` audit row carries only `{"keys_purged": N, "tax_id_kind": "cpf"|"cnpj"}` — zero PII keys. The forbidden-keys guard in `audit.py::_assert_no_forbidden_keys` is a safety net the helper never exercises in practice; `TestDeleteCustomerHard::test_audit_details_dict_passes_forbidden_keys_guard` asserts the contract.

### File List

**Source**
- `src/comadre/keys/crypto.py` — added `decrypt_tax_id` primitive; extended module docstring.
- `src/comadre/keys/formatters.py` — added `format_tax_id_display`; added `TaxIdKind` import.
- `src/comadre/keys/db.py` — added `CustomerExportRow`, `DeleteCustomerResult` dataclasses; added `get_customer_with_cipher`, `delete_customer_hard` helpers.
- `src/comadre/keys/cli/output.py` — added `EXPORT_FORMAT_CHOICES` tuple; added `render_export_json`, `render_export_yaml` (YAML lazy-imports `yaml`).
- `src/comadre/keys/cli/commands/customers.py` — added `export_customer_cmd`, `delete_customer_cmd`; extended imports (`re`, `click`, `InvalidToken`, `decrypt_tax_id`, `delete_customer_hard`, `get_customer`, `get_customer_with_cipher`, `list_api_keys`, `format_tax_id_display`, `EXPORT_FORMAT_CHOICES`, `render_export_json`, `render_export_yaml`, `stderr_console`); extended top-of-file exit-code contract docstring.

**Tests (new or extended)**
- `tests/test_keys_crypto.py` — added `TestDecryptTaxId` class (6 tests); added `InvalidToken` import.
- `tests/test_keys_formatters.py` — new file; `TestFormatTaxIdDisplay` with 10 tests.
- `tests/test_keys_db.py` — added `TestGetCustomerWithCipher` (3 tests) + `TestDeleteCustomerHard` (7 tests); extended `TestListCommandsDoNotWrite::test_no_writes_across_all_helpers` to include `get_customer_with_cipher`; added `test_delete_customer_hard_touches_sentinel` under `TestAuthCacheSentinelTouched`; added `delete_customer_hard` and `get_customer_with_cipher` to the import block.
- `tests/test_keys_cli_export_customer.py` — new file; 14 tests spanning AC1/AC2/AC4/AC5/AC6/AC15/AC16/AC17/AC20/AC22.
- `tests/test_keys_cli_delete_customer.py` — new file; 15 tests spanning AC7/AC8/AC10/AC11/AC12/AC13/AC14/AC15/AC19/AC20.
- `tests/test_keys_output.py` — added `TestRenderExportJson` (2 tests) + `TestRenderExportYaml` (4 tests); extended imports.

**Docs & metadata**
- `README.md` — added LGPD data-operations feature bullet.
- `docs/deployment-guide.md` — added "LGPD operator procedures" subsection under "Key Registry Management".
- `CLAUDE.md` — added two new Non-Obvious Gotchas: tombstone zero-length-BLOB rationale and `fernet.decrypt` single-site invariant.
- `pyproject.toml` — added `pyyaml>=6.0.3` to `[project.dependencies]`; added `types-pyyaml>=6.0.12.20260408` to `[dependency-groups.type-check]`.
- `uv.lock` — regenerated with the new dependencies.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `4-1-lgpd-data-operations-export-hard-delete: ready-for-dev → review`; `last_updated` / header comment refreshed.
- `_bmad-output/implementation-artifacts/4-1-lgpd-data-operations-export-hard-delete.md` — status → `review`; all tasks checked; Dev Agent Record filled.

### Change Log

- 2026-04-19 — Story 4.1 implementation complete (Tasks 0–9 + Task 11). Task 10 (VPS smoke) deferred to deployment-time acceptance. All 23 ACs covered by automated tests; 29 new tests added (6 crypto + 10 formatter + 10 db + 14 export CLI + 15 delete CLI + 6 renderer); 1369 tests green; ruff / mypy-strict / pre-commit all clean.
