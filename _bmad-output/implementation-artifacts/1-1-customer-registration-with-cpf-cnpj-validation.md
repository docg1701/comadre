# Story 1.1: Customer Registration with CPF/CNPJ Validation

Status: done

<!-- Validation optional. Run validate-create-story for quality check before dev-story. -->

## Story

As an operator,
I want to register a new customer with validated CPF/CNPJ via the `comadre-keys` CLI,
so that I can start onboarding paying customers with proper tax-ID verification and at-rest encryption.

**Covers FRs:** FR1, FR2, FR30, FR35, FR37
**UX-DRs:** UX-DR6 (ErrorDisplay), UX-DR7 (ConfirmationLine), UX-DR9 (shared Console), UX-DR10 (exit codes), UX-DR14 (cross-command navigation)
**Epic:** 1 — Key Registry & Customer Management
**Enables:** Journey 1 ("primeira venda"). Unblocks every other story in Epics 1–4.

## Scope (Foundation Story)

This is the brownfield foundation story for the entire `comadre-keys` CLI. It adds:

1. **New dependencies** in `pyproject.toml`: `typer>=0.12`, `cryptography>=43.0`, `python-ulid>=2.2`, `validate-docbr>=2.0`, `pydantic[email]>=2.9` (bring `rich` transitively via typer).
2. **Config extension** — 6 new fields on `Settings` for monetization.
3. **Exception extension** — 2 new `ComadreError` subclasses (`InvalidTaxIdError`, `KeyRegistryError`).
4. **New `src/comadre/keys/` subpackage** scaffolding: `models.py`, `crypto.py`, `db.py`, `audit.py`, `migrations/v001_initial.sql`, `cli/app.py`, `cli/output.py`, `cli/commands/customers.py`.
5. **SQLite schema v001** — creates `customer`, `api_key`, `audit_log`, `schema_version` tables + indexes. WAL mode enforced at connection creation.
6. **CPF/CNPJ checksum validation** via `validate-docbr` (>=2.0 for alphanumeric CNPJ support, effective July 2026).
7. **Fernet encryption** for `tax_id_encrypted` (on write only — decryption is a future story's concern).
8. **Audit log write path** — append-only, no personal data in `details_json`.
9. **`comadre-keys create-customer` command** with mutually-exclusive `--cpf` / `--cnpj`.
10. **rich output components** — `render_error()` (UX-DR6) and `render_confirmation()` (UX-DR7) with shared Console singleton (UX-DR9) and NO_COLOR compliance.
11. **`comadre-keys` entry point** registered in `pyproject.toml → [project.scripts]`.
12. **Tests** — unit tests for models, crypto, db, audit, CLI via `CliRunner`.

Out of scope (future stories): key issuance (1.2), list commands (1.3), show/audit-tail (1.4), update/notes (1.5), key lifecycle (1.6), runtime auth path (Epic 2).

## Acceptance Criteria

> BDD-style. Every AC must be covered by at least one test, a manual command execution, or a filesystem check. All AC text already captured in `_bmad-output/planning-artifacts/epics.md` lines 294–324 — reproduced here with expanded technical detail.

### AC1 — Successful CPF registration (happy path)

**Given** `KEY_REGISTRY_ENCRYPTION_KEY` is set in `.env` to a valid Fernet key and the SQLite database does not exist
**When** the operator runs `comadre-keys create-customer --name "Helena Ribeiro" --email "helena@clinica.com" --cpf "123.456.789-09"`
**Then**
- The CPF checksum validates (real algorithm; `123.456.789-09` has valid digits — **use this value in all test fixtures**; do NOT use `...-00` which fails the checksum).
- The SQLite file is created at `settings.key_registry_db_path`, v001 migration runs (creates all four tables + indexes), WAL mode is enabled (`PRAGMA journal_mode = WAL` returns `"wal"`), file mode is `0600`, parent directory `0700`.
- A `customer` row is inserted with `id = "cust_" + <26-char lowercase ULID>`, `tax_id_kind = "cpf"`, `tax_id_encrypted = <Fernet ciphertext bytes>` (length > 40 bytes; begins with `gAAAAA` when base64-decoded), `notes = ""`, `registered_at = <ISO 8601 UTC>`, `deleted_at IS NULL`.
- Stdout prints exactly one line: `Customer created: cust_01... (Helena Ribeiro)` via `render_confirmation()` — no border, no blank lines, no Rich panel.
- Exit code `0`.
- An `audit_log` row is inserted in the SAME transaction as the customer row, with `actor = "cli:<unix-username>"`, `action = "create_customer"`, `target_type = "customer"`, `target_id = <new customer id>`, `details_json` ≤ 256 chars and containing ONLY non-personal metadata (e.g., `{"tax_id_kind": "cpf"}` — NEVER the CPF, name, or email).

### AC2 — Successful CNPJ registration

**Given** the prerequisites in AC1 but the database already exists
**When** the operator runs `comadre-keys create-customer --name "Empresa LTDA" --email "fin@empresa.com" --cnpj "12.345.678/0001-95"`
**Then**
- The CNPJ checksum validates (14-digit, 2 verification digits; `12.345.678/0001-95` is the canonical valid fixture — do NOT use `.../0001-90`).
- A `customer` row is inserted with `tax_id_kind = "cnpj"` and the 14-digit digits-only form encrypted.
- The schema version check skips migration (already at v001).
- Stdout prints `Customer created: cust_01... (Empresa LTDA)`, exit `0`.

### AC3 — Mutually-exclusive flags rejected

**Given** any valid database state
**When** the operator runs `comadre-keys create-customer --name "X" --email "x@x.com" --cpf "..." --cnpj "..."`
**Then**
- Typer rejects with a usage error BEFORE any crypto, DB, or audit call.
- Stderr shows a rich-rendered error panel (red border) via `render_error()` with title `"Usage error: --cpf and --cnpj are mutually exclusive"` and hint `"Provide exactly one of --cpf or --cnpj."`
- Exit code `2` (usage error, per UX-DR10).
- No SQLite file is created if it didn't exist, and no rows are written if it did.

**When** the operator runs `comadre-keys create-customer --name "X" --email "x@x.com"` (neither flag)
**Then** same behavior with message `"Usage error: exactly one of --cpf or --cnpj is required"`, exit `2`.

### AC4 — Invalid CPF checksum rejected (no value echo)

**Given** a valid database
**When** the operator runs `comadre-keys create-customer --name "X" --email "x@x.com" --cpf "111.111.111-11"`
**Then**
- `InvalidTaxIdError` is raised (status_code 400 conceptually, but CLI never returns HTTP — maps to exit code `4` per UX-DR10).
- Stderr shows a red `Panel` via `render_error()` with title `"Invalid CPF: checksum verification failed"` and hint `"Verify the CPF digits and try again."`
- **The rejected CPF value NEVER appears anywhere** — not in the error title, not in the hint, not in any log line (FR37, NFR16). This is enforced by test.
- Exit code `4`.
- No customer row inserted, no audit row inserted.

Same pattern for invalid CNPJ → title `"Invalid CNPJ: checksum verification failed"`, exit `4`.

### AC5 — Missing encryption key configuration

**Given** `KEY_REGISTRY_ENCRYPTION_KEY` is not set in `.env`
**When** the operator runs any `comadre-keys` subcommand (including `--help` is fine; command execution is not)
**Then**
- During command execution (not import), pydantic-settings raises `ValidationError` on the missing required `SecretStr`.
- The CLI traps the ValidationError and renders via `render_error()` with title `"Configuration error: KEY_REGISTRY_ENCRYPTION_KEY is not set"` and hint `"Generate one with: python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())' and add it to .env. Restart the service if monetization is enabled there too."`
- Exit code `6` (permission/config, per UX-DR10).
- The encryption key value itself is NEVER echoed in error messages or logs if set to a malformed value.

### AC6 — First-run database bootstrap

**Given** the configured DB path does not exist and the parent directory is writable
**When** the first `create-customer` command runs
**Then**
- `sqlite3.connect(...)` creates the file.
- `PRAGMA journal_mode = WAL` executes successfully.
- `PRAGMA foreign_keys = ON` executes (required for the `api_key.customer_id REFERENCES customer(id) ON DELETE RESTRICT` constraint in future stories).
- The migration runner reads `v001_initial.sql` from `src/comadre/keys/migrations/`, splits on `;`, executes each statement inside a single transaction.
- After migration completes, `schema_version` table contains exactly one row: `(version = 1, applied_at = <ISO 8601 UTC>)`.
- The connection is closed before the customer insert opens a fresh transaction.
- File permissions set to `0600` using `os.chmod` immediately after the connect-to-create returns.

### AC7 — Idempotent re-run (schema already at v001)

**Given** the database already exists at schema version 1
**When** `create-customer` runs
**Then**
- The migration runner reads `schema_version`, sees `version=1`, skips migration entirely (no DDL re-execution; no errors even if re-execution would fail due to `CREATE TABLE` without `IF NOT EXISTS`).
- The command completes normally.

### AC8 — Audit log record shape (FR30 explicit invariant)

**Given** any successful mutation (this story: only `create_customer`)
**Then** every `audit_log` row satisfies:
- `occurred_at` — ISO 8601 UTC string, generated once at transaction start (not per-row for multi-row writes).
- `actor` — format `"cli:<username>"` where username is `os.getlogin()` with fallback to `getpass.getuser()`. If both fail (e.g., sudo without `-E`), fallback is literal `"cli:unknown"`. Never `None`.
- `action` — snake_case verb_noun from the fixed vocabulary (this story only writes `"create_customer"`).
- `target_type ∈ {"customer", "api_key", "system"}` or NULL.
- `target_id` — matches target_type (e.g., `cust_...` for customer).
- `details_json` — JSON-serialized dict. MUST NOT contain keys: `cpf`, `cnpj`, `tax_id`, `name`, `email`, `key_plaintext`, `Authorization`. Enforced by a test that greps the serialized string.
- The row is written in the SAME SQLite transaction as the business mutation — verify by raising an exception between the customer insert and audit insert in a test; the customer row must roll back.

### AC9 — `comadre-keys` binary entry point

**Given** the package is installed via `uv sync` (dev) or `uv tool install .` (production simulation)
**When** the operator runs `comadre-keys --help`
**Then**
- The binary is resolvable on PATH.
- Output shows the top-level Typer app help with at least one command (`create-customer`) listed.
- Exit code `0`.
- `--help` suppresses any DB or crypto lookup — pure Typer / Click rendering only.

**When** the operator runs `comadre-keys create-customer --help`
**Then** output includes a realistic example (UX-DR15; full compliance is a future story concern but this story must not prevent it): at minimum the flags `--name`, `--email`, `--cpf`, `--cnpj`, `--notes` are documented with non-abstract example values such as `"Helena Ribeiro"`, `"helena@clinica.com"`, `"123.456.789-09"`.

## Tasks / Subtasks

Tasks are ordered for bottom-up construction (architecture.md §Implementation Sequence). Each task ends with a runnable checkpoint. Do not skip ahead.

- [x] **Task 1 — Dependencies & entry point** (AC: #9)
  - [x] 1.1 Add `typer>=0.12`, `cryptography>=43.0`, `python-ulid>=2.2` to `[project.dependencies]` in `pyproject.toml`. Run `uv sync` (no `pip`, no `poetry` — project rule).
  - [x] 1.2 Add `[project.scripts]` section: `comadre-keys = "comadre.keys.cli.app:main"`.
  - [x] 1.3 Bump `pyproject.toml` version from `1.6.2` to `2.0.0.dev0` (in-progress marker; final `2.0.0` is set at Epic-4 retrospective time).
  - [x] 1.4 Update `.env.example` — add the 6 new env vars with comments (see Task 2 for field list). This mirrors the existing `.env.example` pattern; it is an enforced invariant (`feedback_example_files`).
  - [x] 1.5 Checkpoint: `uv run comadre-keys --help` resolves and prints Typer help (even if empty command set).

- [x] **Task 2 — Settings extension** (AC: #5)
  - [x] 2.0 **`.env` auto-loading gotcha.** `src/comadre/config.py` currently sets `model_config = SettingsConfigDict(case_sensitive=False)` — **no `env_file`** — so the running FastAPI container works only because docker-compose/uvicorn inject env vars from the host environment, not because pydantic-settings reads `.env` itself. The new `comadre-keys` CLI runs outside Docker and must read `.env` on its own. Update `SettingsConfigDict` to `SettingsConfigDict(case_sensitive=False, env_file=".env", env_file_encoding="utf-8", extra="ignore")`. `extra="ignore"` is required because the host's `.env` may also contain pre-existing TTS vars unrelated to the CLI. Verify the existing FastAPI container still starts (it does — compose injection takes precedence over `.env`).
  - [x] 2.1 In `src/comadre/config.py`, add these fields to the existing `Settings` class (keep alphabetical grouping or append at the end — match the file's existing style):
    ```python
    monetization_enabled: bool = Field(default=False, description="...")
    key_registry_db_path: str = Field(default="./data/keys/registry.db", description="...")
    key_registry_encryption_key: SecretStr | None = Field(default=None, description="...")
    operator_contact_hint: str = Field(default="Contact your Comadre operator for billing.", description="...")
    billing_day: int = Field(default=5, ge=1, le=28, description="...")
    billing_timezone: str = Field(default="America/Sao_Paulo", description="...")
    ```
  - [x] 2.2 Add a model-level validator: if `monetization_enabled` is `True`, `key_registry_encryption_key` must be non-None and `.get_secret_value()` must produce valid base64 that `Fernet()` accepts. Otherwise raise `ValueError` with message `"KEY_REGISTRY_ENCRYPTION_KEY is required when MONETIZATION_ENABLED=true and must be a valid Fernet key"`.
  - [x] 2.3 Checkpoint: `uv run mypy src/comadre/config.py` passes strict.
  - [x] 2.4 Write `tests/test_config.py` additions covering the validator (both branches) using `monkeypatch` to set/unset env vars. Use the existing `_clear_settings_cache` fixture pattern.

- [x] **Task 3 — Exception classes** (AC: #4, #5)
  - [x] 3.1 In `src/comadre/exceptions.py`, add two new `ComadreError` subclasses before `comadre_error_handler`:
    - `InvalidTaxIdError(ComadreError)` — `status_code=400`, `error_type="invalid_request_error"`. Constructor signature: `def __init__(self, kind: Literal["cpf","cnpj"]) -> None`. Message: `f"Invalid {kind.upper()}: checksum verification failed"`. Hint: `f"Verify the {kind.upper()} digits and try again."` **The raw input value is NEVER stored on the exception or echoed anywhere** — this is an explicit anti-enumeration rule (FR37, NFR16).
    - `KeyRegistryError(ComadreError)` — `status_code=500`, `error_type="server_error"`. Constructor: `def __init__(self, message: str = "Key registry database unreachable or corrupt") -> None`. Hint: `"Check KEY_REGISTRY_DB_PATH exists, is readable, and has mode 0600."`
  - [x] 3.2 Tests in `tests/test_exceptions.py`: instantiate each, assert status_code / error_type / message / hint. Verify no way to embed CPF into `InvalidTaxIdError` (compile-time — it doesn't accept a value argument).
  - [x] 3.3 Checkpoint: `uv run ruff check src/comadre/exceptions.py && uv run mypy src/comadre/exceptions.py` passes.

- [x] **Task 4 — `keys/models.py` (data models)** (AC: #1, #2)
  - [x] 4.1 Create `src/comadre/keys/__init__.py` (empty module marker; public re-exports added as later stories land).
  - [x] 4.2 Create `src/comadre/keys/models.py` with:
    ```python
    from __future__ import annotations
    from dataclasses import dataclass, field
    from datetime import datetime
    from typing import Literal
    from pydantic import BaseModel, EmailStr, Field, field_validator

    TaxIdKind = Literal["cpf", "cnpj"]
    CustomerStatus = Literal["active", "suspended", "revoked"]  # reserved for 1.6
    BillingMode = Literal["manual", "complimentary", "automated"]  # reserved for 1.2+

    class CustomerCreate(BaseModel):
        name: str = Field(min_length=1, max_length=200)
        email: EmailStr
        tax_id_kind: TaxIdKind
        tax_id_digits: str  # digits-only, post-strip (e.g. "12345678909"); already-validated
        notes: str = ""

    @dataclass(frozen=True, slots=True)
    class CustomerRecord:
        id: str                   # cust_<ulid lowercase>
        name: str
        email: str
        tax_id_kind: TaxIdKind
        tax_id_encrypted: bytes
        notes: str
        registered_at: datetime
        deleted_at: datetime | None
    ```
  - [x] 4.3 `email: EmailStr` requires `pydantic[email]` — if `email-validator` is not already transitive, add `pydantic[email]` to deps in Task 1. Verify with `uv pip list | grep email-validator`.
  - [x] 4.4 Write `tests/test_keys_models.py` — validate `CustomerCreate` rejects empty name, bad email format, invalid tax_id_kind.

- [x] **Task 5 — `keys/crypto.py` (validation + Fernet)** (AC: #1, #2, #4)
  - [x] 5.1 Create `src/comadre/keys/crypto.py` with four pure functions:
    - `strip_tax_id(raw: str) -> str` — removes mask characters (`.`, `-`, `/`, whitespace) and uppercases the remainder. Preserves letters so alphanumeric CNPJ (RFB IN 2.229/2024, effective July 2026) round-trips cleanly.
    - `validate_cpf(raw: str) -> None` — raises `InvalidTaxIdError("cpf")` when the stripped length ≠ 11 or `validate_docbr.CPF().validate(raw)` fails.
    - `validate_cnpj(raw: str) -> None` — raises `InvalidTaxIdError("cnpj")` when the stripped length ≠ 14 or `validate_docbr.CNPJ().validate(raw)` fails (covers both numeric and alphanumeric formats).
    - `encrypt_tax_id(canonical: str, key: SecretStr) -> bytes` — Fernet-encrypts the stripped+uppercased canonical form.
  - [x] 5.2 Validation delegated to `validate-docbr` (>=2.0; tracks Receita Federal rule changes, including alphanumeric CNPJ in 2.0.0 released 2026-04-04). Defaults: `CPF(repeated_digits=False)` — rejects `111.111.111-11` etc. as required by NFR spec. The explicit length check is needed because validate-docbr zero-pads shorter CPF inputs for typed-user tolerance; our storage contract requires the canonical 11/14-char form, so shortforms are rejected upfront.
  - [x] 5.3 Add Fernet helpers:
    ```python
    def encrypt_tax_id(digits: str, key: SecretStr) -> bytes:
        fernet = Fernet(key.get_secret_value().encode())
        return fernet.encrypt(digits.encode())
    ```
    Decryption deliberately NOT added in this story — no caller yet (Story 1.4 `show` and Story 4.1 `export`).
  - [x] 5.4 Write `tests/test_keys_crypto.py`:
    - **10+ valid CPF fixtures** (digits + masked), 5 invalid checksums, 2 wrong-length inputs, all-zeros rejection, all-same-digit rejection.
    - Analogous for CNPJ plus masked-form acceptance.
    - `strip_tax_id` tests exercise alphanumeric CNPJ: `"12.abc.345/xy01-89"` → `"12ABC345XY0189"` (punctuation stripped, letters preserved, uppercased).
    - Round-trip encryption for both numeric CPF and alphanumeric CNPJ canonical forms.
    - **Critical test for FR37/NFR16**: assert `InvalidTaxIdError` has no attribute holding the raw input, and that its `message` and `hint` strings contain no digit substring that could come from the input.

- [x] **Task 6 — `keys/migrations/v001_initial.sql` + migration runner** (AC: #6, #7)
  - [x] 6.1 Create `src/comadre/keys/migrations/__init__.py` (empty).
  - [x] 6.2 Create `src/comadre/keys/migrations/v001_initial.sql` with the EXACT schema from PRD §Data Model (prd.md:L847-L888) — four tables + four indexes. Verbatim:
    ```sql
    CREATE TABLE customer (
        id              TEXT PRIMARY KEY,
        name            TEXT NOT NULL,
        email           TEXT NOT NULL,
        tax_id_kind     TEXT NOT NULL CHECK (tax_id_kind IN ('cpf', 'cnpj')),
        tax_id_encrypted BLOB NOT NULL,
        notes           TEXT DEFAULT '',
        registered_at   TEXT NOT NULL,
        deleted_at      TEXT
    );

    CREATE TABLE api_key (
        id              TEXT PRIMARY KEY,
        customer_id     TEXT NOT NULL REFERENCES customer(id) ON DELETE RESTRICT,
        key_hash        TEXT NOT NULL UNIQUE,
        key_prefix      TEXT NOT NULL,
        rate_limit_rpm  INTEGER NOT NULL CHECK (rate_limit_rpm > 0),
        status          TEXT NOT NULL CHECK (status IN ('active', 'suspended', 'revoked')),
        billing_mode    TEXT NOT NULL CHECK (billing_mode IN ('manual', 'complimentary', 'automated')),
        price_monthly   REAL NOT NULL DEFAULT 0.0,
        paid_until      TEXT,
        created_at      TEXT NOT NULL,
        last_used_at    TEXT,
        notes           TEXT DEFAULT ''
    );

    CREATE TABLE audit_log (
        id              INTEGER PRIMARY KEY AUTOINCREMENT,
        occurred_at     TEXT NOT NULL,
        actor           TEXT NOT NULL,
        action          TEXT NOT NULL,
        target_type     TEXT,
        target_id       TEXT,
        details_json    TEXT
    );

    CREATE TABLE schema_version (
        version     INTEGER PRIMARY KEY,
        applied_at  TEXT NOT NULL
    );

    CREATE UNIQUE INDEX idx_api_key_hash ON api_key(key_hash);
    CREATE INDEX idx_api_key_customer ON api_key(customer_id);
    CREATE INDEX idx_api_key_sweep ON api_key(billing_mode, paid_until) WHERE status = 'active';
    CREATE INDEX idx_audit_occurred ON audit_log(occurred_at);
    ```
    **Schema rule**: no `IF NOT EXISTS` — the `schema_version` table is authoritative. Running this SQL against an already-initialized DB is a bug (the version check prevents it).
  - [x] 6.3 In `src/comadre/keys/db.py` (Task 7), implement `_apply_migrations(conn: sqlite3.Connection) -> None` that:
    - Ensures the `schema_version` table exists first (via its own `CREATE TABLE IF NOT EXISTS schema_version (...)` preamble — migration sentinel bootstrapping is the only legit `IF NOT EXISTS` usage).
    - Reads `SELECT MAX(version) FROM schema_version` → current.
    - If `current < 1`: reads the `.sql` file via `importlib.resources.files("comadre.keys.migrations").joinpath("v001_initial.sql").read_text(encoding="utf-8")`, splits on `";"` with empty-statement skip, executes each inside a single `with conn:` transaction, then `INSERT INTO schema_version VALUES (1, ?)`.
    - If `current >= 1`: no-op.

- [x] **Task 7 — `keys/db.py` (connection + CRUD)** (AC: #1, #2, #6, #7, #8)
  - [x] 7.1 Create `src/comadre/keys/db.py`:
    ```python
    def get_connection(path: str | Path) -> sqlite3.Connection:
        """Open connection with WAL + foreign_keys. Creates parent dir 0700, file 0600."""
        # - mkdir(parent, mode=0o700, parents=True, exist_ok=True)
        # - sqlite3.connect(path, detect_types=sqlite3.PARSE_DECLTYPES)
        # - chmod(path, 0o600) after connect (connect creates the file if missing)
        # - conn.execute("PRAGMA journal_mode = WAL")
        # - conn.execute("PRAGMA foreign_keys = ON")
        # - conn.row_factory = sqlite3.Row
        # - return conn
    ```
  - [x] 7.2 `insert_customer(conn, record: CustomerRecord, actor: str) -> None` — opens single `with conn:` transaction wrapping both the customer INSERT and the audit INSERT. ALL queries use parameterized `?` placeholders (NEVER f-strings or `.format()` — SQL-injection gate from architecture §Enforcement Guidelines).
  - [x] 7.3 `generate_customer_id() -> str` returning `f"cust_{str(ULID()).lower()}"`.
    - **Gotcha:** `python-ulid` 2.x uses `from ulid import ULID` and `str(ULID())` returns uppercase Crockford base32. The architecture.md example `ulid.new().str.lower()` uses the 1.x API — that call DOES NOT EXIST in 2.x. Use the 2.x form above.
  - [x] 7.4 Write `tests/test_keys_db.py` using `sqlite3.connect(":memory:")` fixture (but note: the WAL + 0600 checks need a temp file — use `tmp_path` for those tests). Cover: fresh-DB migration, re-run migration skip, insert_customer happy path, insert_customer with intentional audit-insert failure rolls back customer row (assert `SELECT COUNT(*)` = 0).

- [x] **Task 8 — `keys/audit.py`** (AC: #8)
  - [x] 8.1 Create `src/comadre/keys/audit.py` with:
    - `get_cli_actor() -> str` — returns `f"cli:{os.getlogin() or getpass.getuser() or 'unknown'}"`. Catch `OSError` from `os.getlogin()` (common in systemd/cron contexts) and fall through.
    - `log_event(conn, *, actor: str, action: str, target_type: str | None, target_id: str | None, details: dict[str, object] | None = None) -> None` — INSERTs into `audit_log`. Serializes `details` via `json.dumps(details, ensure_ascii=False, sort_keys=True)` if non-None. **BLOCKLIST ENFORCEMENT:** before serializing, if any key in `details` is in the forbidden set `{"cpf", "cnpj", "tax_id", "name", "email", "key_plaintext", "Authorization", "authorization"}`, raise `AssertionError("audit details contain forbidden personal data key")`. This is a defense-in-depth guard — callers should not pass these; the assertion catches slips.
    - `log_event` does NOT open its own transaction. Callers pass the connection from their `with conn:` block.
  - [x] 8.2 Tests in `tests/test_keys_audit.py`: verify INSERT shape, verify blocklist raises, verify `details=None` produces NULL `details_json`, verify `occurred_at` is ISO 8601 UTC ending in `Z`.

- [x] **Task 9 — `keys/cli/output.py` (rendering components)** (AC: #1, #4, UX-DR6/7/9)
  - [x] 9.1 Create `src/comadre/keys/cli/__init__.py` (empty).
  - [x] 9.2 Create `src/comadre/keys/cli/output.py`:
    ```python
    from rich.console import Console
    from rich.panel import Panel

    _stdout_console: Console | None = None
    _stderr_console: Console | None = None

    def stdout_console() -> Console:
        """Shared stdout console. NO_COLOR and --no-color respected automatically by rich when the env var is set."""
        global _stdout_console
        if _stdout_console is None:
            _stdout_console = Console()  # no force_terminal; let rich detect
        return _stdout_console

    def stderr_console() -> Console:
        global _stderr_console
        if _stderr_console is None:
            _stderr_console = Console(stderr=True)
        return _stderr_console

    def render_error(message: str, hint: str) -> None:
        """UX-DR6: red-bordered single Panel on stderr. Caller is responsible for exit code."""
        stderr_console().print(Panel(hint, title=message, border_style="red"))

    def render_confirmation(message: str) -> None:
        """UX-DR7: plain single-line Console.print on stdout. No panel, no border."""
        stdout_console().print(message)
    ```
  - [x] 9.3 **NO_COLOR compliance** — rich auto-detects `NO_COLOR`. Add a test in `tests/test_keys_output.py` that uses `monkeypatch.setenv("NO_COLOR", "1")` and asserts the captured output (via `Console(file=StringIO())` override in test fixture) contains no ANSI escape (`\x1b[`).
  - [x] 9.4 Shared-console invariant: verify the second call to `stdout_console()` returns the same object (`id()` check). **Never add `print()` anywhere in the `keys/` tree** — project rule.
  - [x] 9.5 **Test reset hook** — expose `_reset_for_tests()` that sets both globals to `None`. Autouse pytest fixture in the module's test file to call it between tests (otherwise Console caches terminal-detection from the first invocation).

- [x] **Task 10 — `keys/cli/commands/customers.py` (`create-customer`)** (AC: #1, #2, #3, #4, #5, #9)
  - [x] 10.1 Create `src/comadre/keys/cli/commands/__init__.py` (empty).
  - [x] 10.2 Create `src/comadre/keys/cli/commands/customers.py` with a Typer app:
    ```python
    app = typer.Typer(help="Customer registry commands.", no_args_is_help=True)

    @app.command("create-customer")
    def create_customer(
        name: str = typer.Option(..., "--name", help="Customer full name. Example: \"Helena Ribeiro\"."),
        email: str = typer.Option(..., "--email", help="Customer email. Example: \"helena@clinica.com\"."),
        cpf: str | None = typer.Option(None, "--cpf", help="CPF (with or without formatting). Example: \"123.456.789-09\". Mutually exclusive with --cnpj."),
        cnpj: str | None = typer.Option(None, "--cnpj", help="CNPJ. Example: \"12.345.678/0001-95\". Mutually exclusive with --cpf."),
        notes: str = typer.Option("", "--notes", help="Free-form notes. Example: \"5 bots, WhatsApp booking\"."),
    ) -> None:
        ...
    ```
  - [x] 10.3 Command body sequence (respect exit-code table UX-DR10):
    1. Mutex check — if both or neither of `cpf`/`cnpj` set: `render_error("Usage error: ...", "...")` on stderr, `raise typer.Exit(2)`.
    2. `settings = get_settings()` — wrap in try/except `ValidationError`: render config error, `raise typer.Exit(6)`.
    3. `digits = strip_tax_id(cpf or cnpj)`; then `validate_cpf(digits)` or `validate_cnpj(digits)`. On `InvalidTaxIdError`: `render_error(exc.message, exc.hint)`, `raise typer.Exit(4)`.
    4. Encrypt: `encrypted = encrypt_tax_id(digits, settings.key_registry_encryption_key)`.
    5. `conn = get_connection(settings.key_registry_db_path)`; `_apply_migrations(conn)`.
    6. Build `CustomerRecord(id=generate_customer_id(), name=name, email=email, tax_id_kind="cpf"|"cnpj", tax_id_encrypted=encrypted, notes=notes, registered_at=datetime.now(UTC), deleted_at=None)`.
    7. Inside `with conn:` — insert customer; `log_event(conn, actor=get_cli_actor(), action="create_customer", target_type="customer", target_id=rec.id, details={"tax_id_kind": rec.tax_id_kind})`.
    8. `conn.close()`.
    9. `render_confirmation(f"Customer created: {rec.id} ({rec.name})")` on stdout. Implicit exit `0`.
    10. Wrap step 5–8 in `try/except sqlite3.Error as exc: render_error("Database error", str(exc)); raise typer.Exit(5)`.
  - [x] 10.4 Defensive: `pydantic.EmailStr` may raise on invalid email at `CustomerCreate()` construction. Catch `ValueError` → render as usage error → exit `2`.
  - [x] 10.5 **Logging rule** — if the command logs anything via `get_logger("keys.cli")`, it MUST NEVER include: the raw CPF/CNPJ input, the decrypted tax_id_digits, the customer name, the email. Log only: `"Customer created" | id=cust_... | tax_id_kind=cpf`. This is a test-verified invariant.

- [x] **Task 11 — `keys/cli/app.py` (top-level Typer app)** (AC: #9)
  - [x] 11.1 Create `src/comadre/keys/cli/app.py`:
    ```python
    import typer
    from comadre.keys.cli.commands.customers import app as customers_app

    app = typer.Typer(
        name="comadre-keys",
        help="Comadre key registry — customer and API-key management CLI.",
        no_args_is_help=True,
        add_completion=False,
    )
    app.registered_commands.extend(customers_app.registered_commands)

    def main() -> None:
        app()

    if __name__ == "__main__":
        main()
    ```
    Prefer `app.registered_commands.extend(...)` over `app.add_typer(customers_app)` so the CLI exposes flat commands (`comadre-keys create-customer`, not `comadre-keys customers create-customer`) — matches the PRD CLI spec exactly.
  - [x] 11.2 Checkpoint: `uv run comadre-keys --help` shows `create-customer`. Running `uv run comadre-keys create-customer --help` shows flag help with realistic values.

- [x] **Task 12 — CLI integration tests** (AC: #1–#9)
  - [x] 12.1 Create `tests/test_keys_cli.py` using `typer.testing.CliRunner`. DO NOT use `asyncio_mode=auto` patterns here — Typer CLI tests are synchronous.
  - [x] 12.2 Fixtures: `tmp_path`-based DB path set via `monkeypatch.setenv("KEY_REGISTRY_DB_PATH", str(tmp_path / "registry.db"))`. Provide a valid Fernet key via `monkeypatch.setenv("KEY_REGISTRY_ENCRYPTION_KEY", Fernet.generate_key().decode())`.
  - [x] 12.3 Tests (minimum — add more for completeness):
    - `test_create_customer_cpf_happy_path` — AC1. Assert stdout contains `"Customer created: cust_"`, exit 0, DB row count = 1, audit count = 1.
    - `test_create_customer_cnpj_happy_path` — AC2.
    - `test_create_customer_both_flags_rejected` — AC3 (both).
    - `test_create_customer_neither_flag_rejected` — AC3 (neither).
    - `test_create_customer_invalid_cpf` — AC4. **Critical**: assert the rejected value `"111.111.111-11"` appears in NEITHER `result.stdout` nor `result.stderr`.
    - `test_create_customer_missing_encryption_key` — AC5. `monkeypatch.delenv("KEY_REGISTRY_ENCRYPTION_KEY", raising=False)`, expect exit 6.
    - `test_first_run_bootstraps_db` — AC6. Assert file exists post-command, mode is `0o600`, schema_version row present.
    - `test_second_run_skips_migration` — AC7. Pre-create DB at v1, mock the migration SQL file read to raise, assert no read occurs.
    - `test_audit_log_no_personal_data` — AC8. Create customer, `SELECT details_json FROM audit_log`, assert it is exactly `'{"tax_id_kind": "cpf"}'` (or equivalent sorted form).

- [x] **Task 13 — Quality gates**
  - [x] 13.1 `uv run ruff check . && uv run ruff format --check .` — zero warnings on new files.
  - [x] 13.2 `uv run mypy src/comadre/keys/` — zero errors in strict mode. If pydantic-plugin complains about `SecretStr | None`, use `Field(default=None)` not bare `None`.
  - [x] 13.3 `uv run pytest` — all new tests pass; existing tests still pass (no regressions).
  - [x] 13.4 `uv run pre-commit run --all-files` — passes.
  - [x] 13.5 Manual sanity: `rm -rf data/keys/ && uv run comadre-keys create-customer --name "Helena Ribeiro" --email "helena@clinica.com" --cpf "123.456.789-09"` on localhost — observe single-line confirmation and non-empty `registry.db`.
  - [x] 13.6 NO_COLOR sanity: `NO_COLOR=1 uv run comadre-keys create-customer --name "Empresa" --email "x@x.com" --cnpj "12.345.678/0001-95"` — output contains no ANSI escapes (pipe to `cat -v` to confirm).
  - [x] 13.7 Performance sanity (NFR5 — detail-class commands <500ms at 1K customers): not required to hit 1K in this story's fixtures, but run `time uv run comadre-keys create-customer ... --cpf "..."` against an empty DB and confirm wall time <2s on a warm local Python interpreter. True NFR5 verification lands with Story 1.3/1.4 against a seeded DB.

## Dev Notes

### Architecture invariants (from `_bmad-output/planning-artifacts/architecture.md`)

- **Import graph downward-only.** Allowed in this story: `comadre.config` ← `comadre.keys.crypto` ← `comadre.keys.db`, `comadre.keys.audit`. CLI modules import from `keys.db`, `keys.audit`, `keys.crypto`, `keys.models`. CLI MUST NEVER import `keys.auth` or `keys.cache` (those don't exist yet and are runtime-only once they do).
- **CLI/runtime separation.** `src/comadre/main.py`, `api.py`, `rate_limit.py`, `service.py` — **do not modify any of them in this story.** The CLI is a separate entry point. The app's lifespan DB init lands in Story 2.1, not here.
- **No raw HTTPException.** All errors in `keys/` raise `ComadreError` subclasses. The CLI catches them and exits with the UX-DR10 code — it does not re-raise.
- **No `print()`.** Use `render_confirmation()` / `render_error()` only. Structured logging via `get_logger("keys.<component>")`. [Source: project-context.md §Python Language Rules]
- **No raw `os.environ`.** Only `get_settings()`. [Source: config.py pattern]
- **Parameterized SQL only.** `conn.execute("INSERT ... VALUES (?, ?, ?)", (a, b, c))`. Never f-strings. Story 4.5g adds a bandit CI gate; be early-compliant. [Source: architecture.md §SQLite Query Patterns]

### Data contracts (from `_bmad-output/planning-artifacts/prd.md` §Data Model)

- `customer.id` — format `cust_` + 26-char lowercase ULID (e.g., `cust_01jgxr3e4c5m7kn9p2qt8vwy`). **Lowercase** is required — architecture.md:L302 mandates it.
- `customer.tax_id_encrypted` — Fernet ciphertext stored as `BLOB`. SQLite's `BLOB` maps to `bytes` via the `sqlite3` driver; pass `bytes` directly.
- `customer.registered_at` — ISO 8601 UTC string `YYYY-MM-DDTHH:MM:SSZ` (NO microseconds; truncate with `.replace(microsecond=0)` or format with `strftime("%Y-%m-%dT%H:%M:%SZ")`).
- `customer.deleted_at` — `NULL` in this story; Story 4.1 sets it for tombstones.
- `audit_log.details_json` — JSON string with `sort_keys=True` for deterministic test assertions. Empty dict is allowed and stored as `'{}'`.

### Library version gotchas (verified 2026-04-16 via context7)

- **`python-ulid` 2.x API** (`mdomke/python-ulid`): the architecture.md reference `ulid.new().str.lower()` is the **1.x API and will fail with `AttributeError`**. Use `str(ULID()).lower()` from `from ulid import ULID`. Document this single-line change in commit message so future readers don't hit the same snag.
- **`cryptography.fernet.Fernet`**: `Fernet.generate_key()` returns `bytes` (urlsafe-base64-encoded 32 bytes). `Fernet(key)` accepts `bytes | str`. Since we store the key as `SecretStr`, call `fernet = Fernet(settings.key_registry_encryption_key.get_secret_value().encode())`.
- **`typer` 0.12+** has no built-in mutually-exclusive flag helper. Enforce the mutex inside the command body; see Task 10.3 step 1. (Future consideration: `typer-config` or a custom `@mutually_exclusive` decorator — not worth the cost for one command.)
- **`validate-docbr` 2.x** (`alvarofpp/validate-docbr`): `CPF().validate(raw)` and `CNPJ().validate(raw)` are bools and accept masked input (`"123.456.789-09"`, `"12.345.678/0001-95"`). Default `CPF(repeated_digits=False)` rejects all-same-digit inputs — that's the behaviour we want. **2.0 adds alphanumeric CNPJ support** per RFB IN 2.229/2024 (effective July 2026). Gotcha: CPF inputs shorter than 11 digits are silently zero-padded and accepted as valid (e.g., `"1234567890"` → treated as `"01234567890"`). That is user-input tolerance, but breaks our "store canonical 11/14-char form" contract — so `validate_cpf`/`validate_cnpj` add an explicit length check against the stripped input before calling the library.

### UX invariants reproduced from `ux-design-specification.md`

- **UX-DR6 ErrorDisplay** (ux:L798-811): `Panel(hint, title=message, border_style="red")` on **stderr**. Non-zero exit per UX-DR10.
- **UX-DR7 ConfirmationLine** (ux:L813-824): plain `Console.print(message)` on **stdout**. No panel, no border, no blank lines.
- **UX-DR9 Shared Console** (ux:L250-256): single `rich.console.Console` instance for stdout and one for stderr. `force_terminal=True` NEVER set (let rich autodetect). Width auto-detected; 80-col minimum. `NO_COLOR` and `--no-color` respected.
- **UX-DR10 Exit codes** (ux:L1022-1035): 0 success, 1 general, 2 usage, 3 not-found (Story 1.4), 4 validation, 5 database, 6 permission/config.
- **UX-DR14 Cross-command navigation** (ux:L964-971): `create-customer` prints `cust_...` on a single line so the operator pipes/copies it into `issue-key --customer cust_...` (Story 1.2).

### Enumeration resistance & log sanitization (FR37, NFR15, NFR16)

- Never echo rejected CPF/CNPJ values in error text, hint text, or logs.
- `InvalidTaxIdError.__init__` deliberately does not accept a value argument (Task 3.1). This is a compile-time guard.
- `audit_log.details_json` blocklist (Task 8.1) is a runtime guard.
- Structured log format `timestamp | level | component | message` — do NOT include dynamic personal data in the `message` component. Safe pattern: `logger.info("Customer created | id=%s | tax_id_kind=%s", rec.id, rec.tax_id_kind)`.

### Project Structure Notes

- New files placed under `src/comadre/keys/` per architecture §Module Organization. No deviations.
- Existing `src/comadre/` files modified this story: `config.py` (add 6 fields), `exceptions.py` (add 2 classes), `pyproject.toml` (deps + entry point + version), `.env.example` (mirror). **No other existing module is modified** — preserves the 1.6.2 runtime contract byte-for-byte.
- Test files created: `test_keys_models.py`, `test_keys_crypto.py`, `test_keys_db.py`, `test_keys_audit.py`, `test_keys_output.py`, `test_keys_cli.py`. `test_config.py` and `test_exceptions.py` are MODIFIED (append-only).

### Testing Standards

- All tests mocked by default (`@pytest.mark.slow` is for model-requiring tests; none apply here). [Source: project-context.md §Testing Rules]
- Use `CliRunner` from `typer.testing` for CLI tests. Do NOT use `AsyncClient` — CLI is synchronous.
- SQLite tests: prefer `:memory:` for pure schema tests; use `tmp_path` when WAL mode or file permissions are under test. `:memory:` does not persist WAL semantics meaningfully.
- Import existing fixtures where relevant (`_clear_settings_cache` autouse from `tests/conftest.py`) — no need to duplicate.
- Target coverage: 90%+ on `src/comadre/keys/` per architecture §Testing Framework (hard minimum). The tests enumerated in Task 12.3 achieve this without line-counting.

### References

- [Source: `_bmad-output/planning-artifacts/architecture.md#Core-Architectural-Decisions`] — ID format, Fernet pattern, SQLite connection management.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Implementation-Patterns-Consistency-Rules`] — DB naming, SQL query patterns, CLI output patterns.
- [Source: `_bmad-output/planning-artifacts/architecture.md#Project-Structure-Boundaries`] — exact module layout for `keys/` subpackage.
- [Source: `_bmad-output/planning-artifacts/prd.md#Data-Model` (L847-L888)] — verbatim SQL schema.
- [Source: `_bmad-output/planning-artifacts/prd.md#Error-Codes` (L900-L922)] — `InvalidTaxIdError(400)`, `KeyRegistryError(500)` envelope.
- [Source: `_bmad-output/planning-artifacts/prd.md#Authentication-Model` (L811-L838)] — future-compatibility; this story doesn't touch the auth path but must not break it.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Core-Components` (UX-DR6 L798-L811, UX-DR7 L813-L824, UX-DR9 L250-L256)] — rich rendering contracts.
- [Source: `_bmad-output/planning-artifacts/ux-design-specification.md#Exit-Codes` (L1022-L1035)] — UX-DR10 code table.
- [Source: `_bmad-output/planning-artifacts/epics.md#Epic-1` (L282-L324)] — AC BDD blocks (reproduced above with expansion).
- [Source: `_bmad-output/planning-artifacts/implementation-readiness-report-2026-04-16.md#Cross-Cutting-Concern-Observations`] — FR30 audit-log invariant must be correctly implemented here so stories 1.2, 1.5, 1.6, 3.x, 4.x can trust the contract. AC8 makes this explicit.
- [Source: `_bmad-output/project-context.md#Critical-Implementation-Rules`] — uv-only, no `os.environ`, no raw `HTTPException`, structured logging, English only.
- [Source: `_bmad-output/planning-artifacts/prd.md#CLI-Tool-Specification` (L954-L1010) + `#Journey-1` (L228-L246)] — command name, flag names, usage example.
- [Source: `CLAUDE.md`] — project language policy (English), `uv` only, `docker compose` v2, no raw `HTTPException`, structured logging.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7[1m] (via Claude Code).

### Debug Log References

- Fernet key-leak test: initial `str(ValidationError)` assertion too strict because Pydantic v2 always embeds the whole model input dict in the root ValidationError. Adjusted the config-level test to verify `errors()[i]["msg"]` carries only our authored message; the user-facing no-echo invariant is enforced at the CLI layer (see `TestMissingEncryptionKey.test_malformed_key_not_echoed`).
- CPF/CNPJ valid fixtures: hand-computed check digits were wrong for several bases; regenerated algorithmically via a short oneliner (documented in chat) before landing the fixture list.
- Typer collapse-to-single-command: a single-command Typer app hides the subcommand layer at `--help`, which broke AC9's "top-level help lists create-customer" wording. Added a no-op `@app.callback()` to keep multi-command mode — comment on the callback explains the reason.
- Migration runner `schema_version` bootstrap: Task 6.3 specified an `IF NOT EXISTS` preamble while Task 6.2 supplied verbatim SQL (no `IF NOT EXISTS`). Chose to check `sqlite_master` for the sentinel table and run the SQL as-is — this honours AC7 ("re-execution would fail due to CREATE TABLE without IF NOT EXISTS") and the PRD's verbatim schema. No behaviour difference versus the `IF NOT EXISTS` preamble.
- `typer.testing.CliRunner` no longer accepts `mix_stderr=False` on Click 8.2+; rewired the CLI's `rich.Console` singletons to `StringIO` buffers via `_reset_for_tests()` so stderr and stdout can be inspected independently.
- Ruff RUF001 flagged an EN DASH in config description; swapped for ASCII hyphen.
- `os.chmod` → `Path.chmod`, `try/except/pass` → `contextlib.suppress` per PTH101/SIM105.

### Completion Notes List

- All 9 ACs satisfied (AC1–AC9) — validated by unit + integration tests and manual sanity runs.
- Full regression: `uv run pytest` passes 514 tests (previously ~400; 100+ new tests for this story).
- Quality gates: `ruff check`, `ruff format --check`, `mypy src/` (strict, 23 source files), `pre-commit run --all-files` all green.
- Manual sanity: `comadre-keys create-customer` against fresh DB produced `registry.db` with mode `0600` and single-line `Customer created: cust_<ULID> (Helena Ribeiro)` confirmation; NO_COLOR run shows zero ANSI escapes under `cat -v`; wall time 0.36 s warm-start.
- Anti-enumeration (FR37/NFR16) verified at three layers: (1) compile-time — `InvalidTaxIdError.__init__` accepts only `kind`; (2) runtime CLI — `render_error` uses static title/hint only; (3) test — `TestAntiEnumeration` and `TestInvalidChecksum.test_invalid_cpf_rejected_no_echo` assert the rejected value never appears in stdout/stderr/exception attributes.
- FR30 audit-log invariant: `audit.log_event` enforces a blocklist of personal-data keys (`cpf`, `cnpj`, `tax_id`, `name`, `email`, `key_plaintext`, `Authorization`); the only non-personal metadata the create-customer path stores is `{"tax_id_kind": "cpf"|"cnpj"}` (verified by `TestAuditLogNoPersonalData.test_audit_details_json_shape`).
- Transactional safety: `insert_customer` opens the `with conn:` block — customer and audit rows commit or roll back together. Tested with a forced `sqlite3.IntegrityError` from a monkey-patched `log_event`.
- Runtime app untouched — `api.py`, `main.py`, `service.py`, `rate_limit.py` have no edits. Only `config.py` (new fields + validator + `env_file=".env"`) and `exceptions.py` (two new subclasses) were modified among existing modules; both changes are additive.
- New scaffolding (`keys/` subpackage, `keys/cli/` app, `migrations/v001_initial.sql`) is self-contained and ready for Story 1.2 (key issuance) to add the `api_key` CRUD layer without touching existing files.
- `_bmad-output/implementation-artifacts/sprint-status.yaml` updated: `1-1-customer-registration-with-cpf-cnpj-validation` status advanced `ready-for-dev` → `in-progress` → `review`.

### File List

**New files (16):**

- `src/comadre/keys/__init__.py`
- `src/comadre/keys/models.py`
- `src/comadre/keys/crypto.py`
- `src/comadre/keys/db.py`
- `src/comadre/keys/audit.py`
- `src/comadre/keys/migrations/__init__.py`
- `src/comadre/keys/migrations/v001_initial.sql`
- `src/comadre/keys/cli/__init__.py`
- `src/comadre/keys/cli/app.py`
- `src/comadre/keys/cli/output.py`
- `src/comadre/keys/cli/commands/__init__.py`
- `src/comadre/keys/cli/commands/customers.py`
- `tests/test_keys_models.py`
- `tests/test_keys_crypto.py`
- `tests/test_keys_db.py`
- `tests/test_keys_audit.py`
- `tests/test_keys_output.py`
- `tests/test_keys_cli.py`

**Modified existing files (5):**

- `pyproject.toml` — version bump to `2.0.0.dev0`; added `typer>=0.12`, `cryptography>=43.0`, `python-ulid>=2.2`, `pydantic[email]>=2.9` deps; added `[project.scripts] comadre-keys = "comadre.keys.cli.app:main"`.
- `src/comadre/config.py` — added `env_file=".env"` + `extra="ignore"` to `SettingsConfigDict`; 6 new fields (`monetization_enabled`, `key_registry_db_path`, `key_registry_encryption_key`, `operator_contact_hint`, `billing_day`, `billing_timezone`); model-level Fernet-key validator.
- `src/comadre/exceptions.py` — added `InvalidTaxIdError` (400) and `KeyRegistryError` (500) subclasses.
- `.env.example` — mirrored the 6 new env vars with comments.
- `tests/test_config.py` — `TestMonetizationSettings` class with 12 new tests.
- `tests/test_exceptions.py` — `TestInvalidTaxIdError` and `TestKeyRegistryError` classes (16 new tests).

**Sprint tracking:**

- `_bmad-output/implementation-artifacts/sprint-status.yaml` — 1-1 status transitions.

## Change Log

| Date       | Change                                                                                                                                   |
|------------|------------------------------------------------------------------------------------------------------------------------------------------|
| 2026-04-16 | Story 1.1 created (context drafted; status ready-for-dev).                                                                               |
| 2026-04-17 | Story 1.1 implemented: `comadre-keys create-customer` CLI + key-registry foundation (`keys/` subpackage, SQLite v001 migration, Fernet at-rest encryption, audit log, CPF/CNPJ validation). Status → review. |
| 2026-04-17 | Replaced the hand-rolled 2-verification-digit CPF/CNPJ validator with `validate-docbr>=2.0`. Rationale: the upcoming alphanumeric CNPJ (RFB IN 2.229/2024, July 2026) would force us to reimplement the algorithm anyway; `validate-docbr` 2.0.0 (2026-04-04) already ships that support and is actively maintained. Updated `src/comadre/keys/crypto.py`, `tests/test_keys_crypto.py`, `pyproject.toml`, `architecture.md`, and `prd.md` — every "no external library" directive reversed to point at `validate-docbr`. 517 tests green, mypy strict clean, pre-commit clean. |
| 2026-04-17 | Code review (Blind Hunter + Edge Case Hunter + Acceptance Auditor) identified 1 decision-needed, 15 patches, 9 deferrals, 7 dismissals. All 15 patches applied + decision resolved by anchoring `.env` to project root (industry standard). Key fixes: (1) audit blocklist replaced `assert` with `raise ValueError` so it survives `python -O`, is case-insensitive, and walks nested dicts; (2) WAL sidecars `.db-wal`/`.db-shm` now chmod'd to 0600; (3) CPF/CNPJ validators now check canonical form consistently; (4) migration runner uses `executescript` + busy_timeout + schema-downgrade guard; (5) Fernet key validation moved to `field_validator` on `SecretStr` (masks malformed value in errors); (6) config-error handler distinguishes missing-key from other failures; (7) test suite strengthened with symmetric CPF/CNPJ anti-enumeration, AC3 hint assertions, AC1 ciphertext/timestamp CLI integration checks, AC8 actor shape assertion, and a `print()`/`typer.echo()` regression sentinel. 523 tests green, mypy strict clean, pre-commit clean. Status → done. |

### Review Findings

_Code review 2026-04-16 — Blind Hunter + Edge Case Hunter + Acceptance Auditor._

**Decision-needed (resolved):**

- [x] [Review][Decision] `.env` path resolution footgun → **resolved: anchor to project root** (industry standard used by `uv`, `poetry`, `pipenv`). Added `_project_env_file()` helper in `src/comadre/config.py` that walks upward from the module until it finds the directory containing `pyproject.toml`. When installed as a wheel the walk fails and no `.env` is loaded — containers continue to use real env vars via compose/systemd. Prevents stray-CWD `.env` files from silently rotating the at-rest encryption key.

**Patch (fixed):**

- [x] [Review][Patch] Replace `assert` in audit blocklist with `raise ValueError` — guard now survives `python -O` / `PYTHONOPTIMIZE=1`. Verified by running a `-O` smoke test. [`src/comadre/keys/audit.py`]
- [x] [Review][Patch] Audit blocklist is now case-insensitive (`key.lower()` comparison). Parametrized test added with `CPF`/`Email`/`Tax_Id` variants. [`src/comadre/keys/audit.py`]
- [x] [Review][Patch] Audit blocklist walks nested dicts recursively via `_assert_no_forbidden_keys`. Dedicated nested-rejection test added. [`src/comadre/keys/audit.py`]
- [x] [Review][Patch] `get_connection` now chmod's `registry.db-wal` and `registry.db-shm` sidecars to `0o600` alongside the main DB file via a shared `_chmod_0600` helper. [`src/comadre/keys/db.py`]
- [x] [Review][Patch] `validate_cpf` / `validate_cnpj` now pass `canonical` (post-strip) to validate-docbr. Length check and checksum now operate on the same string. [`src/comadre/keys/crypto.py`]
- [x] [Review][Patch] Migration runner now uses `conn.executescript(sql)` instead of `sql.split(";")` — future migrations with semicolons inside string literals / triggers / CHECK clauses remain correct. [`src/comadre/keys/db.py`]
- [x] [Review][Patch] Added `PRAGMA busy_timeout = 5000` in `get_connection` to tolerate concurrent CLI invocations instead of failing immediately with `SQLITE_BUSY`. [`src/comadre/keys/db.py`]
- [x] [Review][Patch] Migration runner now raises `RuntimeError` when `schema_version > _SCHEMA_VERSION` (downgrade guard). [`src/comadre/keys/db.py`]
- [x] [Review][Patch] `CustomerCreate.tax_id_digits` now enforces `pattern=r"^[0-9A-Z]+$"`. [`src/comadre/keys/models.py`]
- [x] [Review][Patch] Config-error handler now catches `OSError` / `PermissionError` separately and surfaces the actual pydantic error message when the failure is not specifically about the missing encryption key. [`src/comadre/keys/cli/commands/customers.py`]
- [x] [Review][Patch] Moved Fernet-key-shape validation to a `field_validator` on the `SecretStr`-typed field so pydantic masks the value as `**********` in the `input_value` field of the error. [`src/comadre/config.py`]
- [x] [Review][Patch] AC4 anti-enumeration tests now assert the full digits-only `"11111111111"` (CPF) and `"11111111111111"` (CNPJ) are absent from stdout, stderr, and CliRunner output; the CNPJ case got symmetric no-echo coverage (`test_invalid_cnpj_rejected_no_echo`). [`tests/test_keys_cli.py`]
- [x] [Review][Patch] Added explanatory comment to `test_monetization_enabled_rejects_malformed_key` noting the pydantic-core `input_value` limitation and citing the CLI-level test as the AC5 boundary guard. Field-level validator on `SecretStr` now masks the value in the rendered error. [`tests/test_config.py`]
- [x] [Review][Patch] AC3 mutex tests now assert the UX-DR6 hint text `"Provide exactly one of --cpf or --cnpj."`. Added `test_mutex_rejected_with_preexisting_db` to cover the "no rows written when DB existed" branch. [`tests/test_keys_cli.py`]
- [x] [Review][Patch] CLI happy-path test now asserts AC1 ciphertext shape (`>40 bytes`, Fernet version byte 0x80), AC1 `registered_at` regex, and AC8 `actor` shape via `SELECT`. Also added `assert result.stdout == ""` as a regression sentinel against raw `print()`/`typer.echo()` bypassing the rendered pipeline. [`tests/test_keys_cli.py`]

**Deferred (non-gating, re-triage later — see `deferred-work.md`):**

- [x] [Review][Defer] AC7 partial-migration crash scenario unverified — `with conn:` atomicity covers it de-facto [`src/comadre/keys/db.py`]
- [x] [Review][Defer] AC8 `occurred_at` per-transaction invariant for future multi-row writes [`src/comadre/keys/audit.py`]
- [x] [Review][Defer] `os.getlogin()` log-injection sanitization [`src/comadre/keys/audit.py`]
- [x] [Review][Defer] Operator-config validators (path traversal, IANA timezone, Fernet entropy) [`src/comadre/config.py`]
- [x] [Review][Defer] CLI UX edges: NUL bytes, whitespace-only name, unbounded `--notes`, repeated flags [`src/comadre/keys/cli/commands/customers.py`, `models.py`]
- [x] [Review][Defer] NBSP / zero-width / Unicode-normalization handling in tax-ID strip [`src/comadre/keys/crypto.py`]
- [x] [Review][Defer] Test-framework micro-issues (`_reset_for_tests` leading underscore, `isolation_level` comment, `importlib.resources.files` monkeypatch leak) [various test files]
- [x] [Review][Defer] SIGINT mid-tx, NTP clock-skew, ULID collision retry, `Fernet` instance caching [`src/comadre/keys/db.py`, `crypto.py`]
- [x] [Review][Defer] Silent `chmod` failure on parent dir should log a warning [`src/comadre/keys/db.py:L44-46`]

