# AGENTS.md

## Project Overview

Comadre is a self-hosted TTS API with dual-engine architecture: Kokoro fp32 (fast built-in voices) + Qwen3-TTS C++ Q8_0 (voice cloning). Serves n8n chatbot workflows for WhatsApp/Telegram/Messenger in Brazilian Portuguese.

## Language Policy

- **Everything in English** — code, comments, commits, docs, configs, API responses, error messages, README.md.
- No exceptions. All project files are in English.
- Why: optimizes LLM interaction and developer experience.

## Build & Test

```bash
uv sync                          # Install all deps
uv run pytest                    # Run tests (mocked, no model needed)
uv run pytest -m slow            # Run integration tests (requires models)
uv run ruff check .              # Lint
uv run mypy src/                 # Type check (strict mode)
uv run pre-commit run --all-files  # All quality checks
```

## Architecture — What You Must Know

- **Dual-engine + filesystem voice discovery**: voice param format is `engine/name` (e.g. `kokoro/pm_santa`, `qwen/galvani`). Kokoro voices: `.npy` files in `/voices/kokoro/` or built-in from `.npz`. Qwen3 voices: `.wav` files in `/voices/qwen/`. Drop a file → available immediately, no restart. See `docs/voice-management.md`.
- **Single FIFO queue** per instance (`asyncio.Lock`). No multi-worker model. Scale horizontally by increasing `deploy.replicas` in `compose.yaml` — Caddy load-balances across replicas via the `dynamic a` upstream resolver in `Caddyfile` (re-resolves Docker DNS every 5s, `least_conn` policy — queue-depth-aware, exploits the single-FIFO-lock-per-replica design where Caddy's active-connection count equals queued+in-flight requests).
- **Engine-specific preprocessing**: Kokoro uses `normalize_text()` + `chunk_text()`. Qwen3 uses `expand_siglas()`.
- **Engine-specific post-processing**: Kokoro → radio_warm pipeline. Qwen3 → whatsapp-subtle pipeline. Both output OGG Opus.
- **Siglas**: Kokoro handles them natively via espeak-ng pt_extra dictionary (67 entries, 34/34 verified). Qwen3 uses spaced format (`C N P J`).
- **Module boundaries enforced**: no HTTP concerns in `service.py`, no business logic in `api.py`, no raw `os.environ` (use pydantic-settings), no raw `HTTPException` (use `ComadreError` hierarchy).
- **HTTPS via Caddy**: Caddy reverse proxy terminates TLS (auto Let's Encrypt or self-signed). Caddy is the sole external access point (ports 80/443) — the TTS service is not exposed on the host network. Configure domain via `DOMAIN` env var.
- **Rate limiting**: per-key only via the `limits` library (`MovingWindowRateLimiter` over in-memory storage). `POST /v1/audio/speech` enforces one bucket per API key, keyed on `key:<key_id>` and fed by the registry row's `rate_limit_rpm` (retrieved as `AuthPayload.rate_limit_rpm` during auth). The bucket identity is the DB `key_id`, so it is stable across `comadre-keys rotate-key` (new plaintext, same bucket) and independent for two keys issued to the same customer. `/health` is not rate-limited at the app layer. `get_client_ip()` is retained for the access log (reads `X-Forwarded-For` from Caddy, falls back to `request.client.host`). Rate-limit storage is in-memory per replica — multiplying replicas multiplies effective RPM; documented in `docs/rate-limiting.md`. Per-key counters (`requests_total`, `auth_success`, `rate_limit_429`, `peak_rpm`, `avg_rpm_last_60s`) live in `src/comadre/counters.py`, reset on restart, and are snapshotted every 15 s to `{KEY_REGISTRY_DB_PATH}.counters.{hostname}.json` (one file per replica). `comadre-keys cache-status` and `comadre-keys show <key-prefix> --audit-tail N` glob every matching file and aggregate across replicas — sums for counters, max for `peak_rpm`/`last_activity_at`, min for `snapshot_age_seconds`/`process_uptime_seconds` — so multi-replica deployments see cluster-wide traffic, not last-writer-wins.
- **Landing page**: served by Caddy via `file_server` at root path (`/`). API paths (`/v1/*`, `/health`, `/docs`) routed via `@api` handle block to tts-service. Static assets in `deploy/landing/`, bind-mounted as `/srv/www:ro`. Controlled by `landing_enabled` ansible variable (default true).
- **Import graph flows downward only**: config/logging → exceptions/schemas → preprocessing → service → rate_limit → api/health → main. No circular imports.

## Code Conventions

- Python 3.12, type-annotated (mypy strict + pydantic plugin)
- `ruff` for lint+format (line-length 88)
- All errors via `ComadreError` subclasses with `status_code`, `error_type`, `hint` — never raw HTTPException
- Structured logging: pipe-delimited `timestamp | level | component | message` — never `print()`
- Docker Compose v2 syntax: `docker compose`, never `docker-compose`
- Package management: `uv` only, never `pip` or `poetry`
- Ansible become password: pass via `-e "ansible_become_password=PASSWORD"` on every playbook that uses `become: true` (bootstrap, cleanup). Never modify inventory to store passwords.

## Key File Locations

- `src/comadre/` — application code (config, logging, schemas, exceptions, preprocessing, service, rate_limit, health, download, api, main)
- `tests/` — pytest suite (mocked, no real models)
- `deploy/espeak-ng/pt_extra` — custom sigla dictionary for espeak-ng
- `docs/` — technical research docs (feasibility report, engine internals, dictionary docs, **qwen3-tts-cli build guide**, **qwen3 model quantization guide**, **voice management guide**)
- `deploy/bin/qwen3-tts-cli` — pre-built Qwen3 C++ binary (see `docs/building-qwen3-tts-cli.md` to rebuild)
- `src/comadre/keys/cli/` — `comadre-keys` CLI (Typer app). Commands: `create-customer`, `list-customers`, `update-customer`, `delete-customer`, `export-customer`, `correct-tax-id`, `issue-key`, `list-keys`, `update-key`, `rotate-key`, `revoke-key`, `rotate-encryption-key`, `mark-paid`, `suspend`, `reactivate`, `at-risk`, `revenue`, `show`, `cache-status`, `suspend-sweep`, `health` (21 verbs total). This is the sole key-management surface.
- `deploy/caddy/Caddyfile` — Caddy reverse proxy config (HTTPS termination)
- `scripts/loadtest.py` — saturation test (concurrency-based, 6 scenarios)
- `scripts/capacity_test.py` — capacity test (rate-based, WhatsApp context, ElevenLabs comparison)

## Non-Obvious Gotchas

- **misaki ignores ESPEAK_DATA_PATH** — the bundled `pt_dict` in `espeakng_loader` takes precedence. Must copy compiled pt_extra data to BOTH system path AND the espeakng_loader bundled path inside the venv.
- **Qwen3 requires `-l pt`** for THINK mode — without it, accent is random and siglas are inconsistent.
- **Qwen3 4-core sweet spot** — beyond 4 CPU cores, diminishing returns (1.5% gain at 6 cores). GGML uses all threads per request.
- **Noise calibration differs per engine** — Kokoro needs 3x more room/hiss noise than Qwen3 (RMS 0.063 vs 0.016).
- **kokoclone dependency is legacy** — still in pyproject.toml but REJECTED. Will be replaced by kokoro-onnx in Story 1.4.
- **qwen3-tts-cli build is non-trivial** — requires building ggml submodule first, patching OpenMP linking, and applying the seed patch. Full procedure in `docs/building-qwen3-tts-cli.md`.
- **Qwen3 Q8_0 GGUF now available pre-built** — from `PabloHoties/Qwen3-TTS-12Hz-0.6B-Base-GGUF` on HuggingFace. The app auto-downloads when `QWEN3_MODEL_URL` and `QWEN3_TOKENIZER_URL` are set. Manual conversion (see `docs/quantizing-qwen3-models.md`) is no longer required.
- **Models auto-download on first startup** — Kokoro models download from GitHub releases, Qwen3 models from HuggingFace. For air-gapped deployments, use `deploy-models.yml` to copy via SCP.
- **Suspension sweep predicate uses strict `paid_until < today`, not `<=`** — a key with `paid_until == today` is considered paid through today; the sweep catches it on the next morning. This matches FR18's "whose paid date has elapsed" wording. Don't "fix" the predicate to `<=` — you'd suspend customers who paid today and haven't yet ridden out their coverage. The cron fires at 00:30 in the operator's configured `billing_timezone` (default **UTC**) via `CRON_TZ` set by `bootstrap.yml`; the app's `BILLING_TIMEZONE` env var MUST match (drift silently shifts the app's "today" relative to the cron schedule). The billing TZ is a **contractual input** — whatever value this holds dictates when `paid_until` expires and a key flips to 401; operators must communicate the zone to customers and avoid changing it mid-relationship. UTC is the operator-neutral international default; override (e.g. `America/Sao_Paulo`) only when you've formally informed the customer base.
- **`comadre-keys health` cannot read the host's crontab from inside the `tts-service` container** — cron-installed detection uses a marker file at `{KEY_REGISTRY_DB_PATH}.cron-installed` written by `bootstrap.yml`, not a `crontab -l` shell-out. The marker confirms ansible installed the cron entry; for "is the cron actually firing?" look at the "Last suspension sweep" age field, which reads `audit_log` directly. The two checks complement: marker present + recent sweep = healthy; marker present + stale sweep = cron installed but failing; marker absent = bootstrap not run. Never hand-edit the marker — it will drift from the real crontab and mislead `health`.
- **`comadre-keys health --format json` exits 7 on any warn/fail check**; table mode always exits 0 (read-tier UX rule). Exit codes across `comadre-keys`: 0 success, 2 usage / validation (NUL/CR/LF in `--name` / `--reason`, mutex violations, oversize `--notes`, CPF/CNPJ checksum failure, duplicate tax-ID), 3 entity not found (customer / key prefix), 4 Fernet shape failure (`rotate-encryption-key --new-key` only — every other validation error is exit 2), 5 DB error (sqlite3 / `InvalidToken` on rotation aftermath), 6 config / permission (missing `KEY_REGISTRY_ENCRYPTION_KEY`, unreadable `.env`), 7 unhealthy JSON output. Don't "harmonise" the schema by collapsing 3 into 2 — operators distinguish "you typed a bad CPF" (retry) from "this customer ID doesn't exist" (look it up) via the exit code.
- **LGPD tombstone keeps `tax_id_encrypted BLOB NOT NULL` — purge writes `X''` (zero-length BLOB), not `NULL`, to avoid a v002 migration.** `delete_customer_hard` scrubs `name`/`email`/`notes` to `""` and `tax_id_encrypted` to the zero-length blob so the existing NOT NULL constraints still pass. The canonical tombstone signal is `deleted_at IS NOT NULL`; every read path already treats tombstones as missing. Don't "fix" the schema by dropping the NOT NULL constraints — SQLite has no `ALTER COLUMN DROP NOT NULL`, so the fix would require create-new-table + copy + rename, for zero operator-observable benefit.
- **`export-customer`'s decrypt is the ONLY non-storage-boundary `fernet.decrypt` call in the codebase.** The `rg "fernet\.decrypt" src/` invariant should return exactly one hit — `crypto.py::decrypt_tax_id`. Any new decrypt site must route through `keys.crypto.decrypt_tax_id` (architecture §Security Boundaries: "CPF/CNPJ encryption/decryption ONLY happens in `crypto.py`"). Adding a second Fernet call outside `crypto.py` is a review-blocker.
- **`rotate-encryption-key` re-encrypts only `deleted_at IS NULL` customers**; tombstoned rows hold a zero-length `tax_id_encrypted` BLOB that Fernet would reject (`InvalidToken` on empty input) and that carries no PII to rotate. Don't "fix" the helper to include tombstones — the skip is correct by design (Story 4.1 contract). The audit-row count reflects active rows only. The success ConfirmationLine deliberately echoes the new key value (epic AC verbatim) as a copy-paste hint for the `.env` swap — it is the SOLE surface that prints key material (never in INFO logs, error panels, or the audit `details_json`). Exit-code addendum for `system.py` verbs: 4 joins the table for `rotate-encryption-key`'s `--new-key` Fernet shape check.
- **Backup tarball naming is load-bearing: `{KEY_REGISTRY_DB_PATH}.backup-YYYY-MM-DDTHH-MM-SSZ.tar.gz.enc`.** The glob pattern in `keys/health.py::_check_last_backup` is `*.backup-*.tar.gz.enc` rooted at `Path(KEY_REGISTRY_DB_PATH).parent`. Renaming the archive (dropping `.enc`, moving into a `backups/` subdirectory, switching timestamp format) silently breaks the `Last backup` health row — it reports `never` even with an archive sitting right there. Don't "clean up" the naming; the contract is architecture-reserved since Story 3.4. ISO-8601 uses `-` separators between time components (`T02-00-00Z`, not `T02:00:00Z`) because colons are illegal on Windows and some network filesystems.
- **`BACKUP_PASSPHRASE` is accepted empty at service boot by design (Story 4.3).** `SecretStr` field with `default=SecretStr("")` + a validator that requires `>= 16` chars ONLY when non-empty. Rationale: the passphrase is consumed by the backup/restore playbooks, not by the FastAPI app or any `comadre-keys` CLI verb. Forcing it required-at-boot would make upgrade-to-2.1.1 chicken-and-egg (service won't start → can't run `bootstrap.yml` → service won't start). The ansible playbooks themselves do the strict length check via `ansible.builtin.assert`. Grep invariant: `rg "backup_passphrase" src/comadre/` returns exactly one hit in `config.py`.
- **`restore-keys.yml` warns on archived-key ≠ live `.env` but does NOT auto-swap.** If the archive was captured under a pre-rotation encryption key and the operator has since rotated, the archived `tax_id_encrypted` ciphertexts only decrypt with the archived key. The playbook prints the archived key on stdout as a copy-paste hint for the `.env` swap; it never writes to `.env` itself. Rationale: auto-swapping would silently revert a deliberate rotation; operator-in-the-loop is the safer default. Until the operator swaps `.env` and restarts, every `comadre-keys export-customer` call on a restored customer fails with `InvalidToken`.
- **`ansible-playbook health.yml` is the operational-state assertion playbook (Story 4.4); it exits non-zero on any deviation.** Wire it into monitoring (cron + `logger -t comadre-health`), CI (Story 4.5x), or operator runbooks. The probes: DB mode `0600`, parent dir mode `0700`, `comadre-daily-suspension` + `comadre-keys-backup` cron entries present in the host crontab, ≥ 1 `*.backup-*.tar.gz.enc` archive in `/var/lib/comadre`, UFW active with exactly 22/80/443 ALLOW (≤ 6 lines for v4 + v6 dupes), in-container `comadre-keys health --format json` reports `is_healthy=true`. Each assertion carries a corrective hint in its `fail_msg`. The pre-existing diagnostic surfaces (Caddy state, `/health` response, disk usage, voice list) are preserved as informational pre-checks but the assertion chain is the trustworthy "is the deployment safe?" boolean. Don't soften an assertion to a debug print — operators must be able to `ansible-playbook health.yml; echo $?` and trust the result.
- **`bootstrap.yml`'s explicit chmod tasks (Story 4.4) are belt-and-braces on top of `keys/db.py::get_connection`'s `_chmod_0600` + `mkdir(mode=0o700)`.** The Python connection layer enforces these modes on every connection open — runtime safety net. The ansible tasks make `bootstrap.yml` self-evidently FR42 / NFR13 fulfilling and trace to a single named task (operators don't need to read Python to verify the contract). The `chmod` shell-out goes through `docker compose exec` because the registry path lives inside a named Docker volume — host-side `ansible.builtin.file:` cannot reach the in-container path without `docker volume inspect`-derived host paths, which are docker-engine-internal and break on Docker Desktop / podman. The `[FS] Wait for service lifespan to materialise registry.db` poll (`retries: 30, delay: 2`) is load-bearing — the FastAPI lifespan creates the file on first connection, so the chmod must run AFTER the wait succeeds. Don't "fix" the redundancy by removing either layer — Python protects against runtime drift, ansible protects against bootstrap-time misconfiguration.
- **`comadre-keys health` has TWO cron-installed rows** (Story 4.4): `Cron` (suspension-sweep, marker `{db}.cron-installed`) and `Backup cron` (nightly key-registry backup, marker `{db}.backup-cron-installed`, includes `retention_days`). Both are warn-on-missing and flip `is_healthy=False` independently. The marker paths derive mechanically from `KEY_REGISTRY_DB_PATH`; operators who customise the DB path MUST re-run `bootstrap.yml` so the new marker location matches. The `Backup cron` row sits between `Cron` and `Last backup` in the rendered table — order is documented but not asserted, so JSON consumers iterate the list rather than rely on positional access.
- **`export-customer --include-audit` is opt-in (default off) by design (Story 5.1 Gap 6).** The default export honours the LGPD Art. 18 II/V minimum-necessary reading — name, email, decrypted tax-ID, notes, and key prefixes are the data-subject-facing fields. Adding the audit-log history (every `mark_paid` / `suspend_key` / `rotate_key` / `update_key` event, with actor + timestamp) is a broader-reading interpretation of Art. 18 II/V that operators' counsel may or may not commission. Default-off keeps the lean response correct for the common case; the opt-in is documented in `docs/monetization.md` §1.4. Don't flip the default — counsel-driven, not engineering-driven. Defense-in-depth: the emitted `audit_events[].details` payload re-runs the same `_FORBIDDEN_DETAIL_KEYS` filter that `log_event` enforces at write time (via `audit.py::filter_forbidden_keys`), so a corrupt out-of-band INSERT still cannot leak a PII key through the export.
- **`correct-tax-id` preserves `customer_id` and every `api_key.customer_id` FK; `delete-customer --hard` + `create-customer` does NOT (Story 5.1 Gap 7).** A tax-ID correction (operator typo, CPF↔CNPJ swap, RFB alphanumeric reissue) MUST go through `correct-tax-id` — the helper does an in-transaction UPDATE of `tax_id_encrypted` + `tax_id_kind` and writes an audit row with `{old_kind, new_kind, reason}` (NEVER the value). Delete+recreate produces a tombstone + a brand-new `cust_<ulid>` row; all keys, billing history, and audit chain re-anchor or orphan. The handbook §1.6 carve-out that previously documented the delete+recreate workaround should now point at this verb. The `--reason` validators mirror `revoke-key --reason` (NUL/CR/LF/empty/oversize → exit 2); `--yes` bypasses the Destroy-tier confirmation prompt for scripting. The new tax-ID is encrypted via `crypto.py::encrypt_tax_id` (single-Fernet invariant — `correct-tax-id` does NOT import Fernet).
- **`mark-paid --months` anchors on `paid_until` if it is today-or-later, otherwise on today (Story 5.1 Gap 3).** The "extend the existing window" semantic is operator-friendly when the customer pays before expiry; the "start a new window" semantic kicks in only after expiry so an operator who renews late doesn't lose the days between expiry and renewal. The audit row carries `{"mode": "months", "months": N}` distinguishing this path from `--until`. `--months` and `--until` are mutually exclusive; one is required. Companion flag `--price-monthly` is atomic with the `paid_until` write — single UPDATE statement; the audit row records `{price_monthly_changed: true, old, new}` (price is operator-internal billing data, not PII).
- **`revenue --as-of` is full audit replay (Story 5.1 Gap 8 + review-pass).** `db.py::reconstruct_key_state_at(conn, as_of, *, tz)` walks the `audit_log` forward up to `as_of`, mutating per-key snapshots from `mark_paid` / `suspend_key` / `reactivate_key` / `revoke_key` events. `status` and `paid_until` are fully audit-tracked. `price_monthly` is fully replayable from Story 5.1 review-pass forward: BOTH `mark_paid` (Gap 4) AND `update_key` (review-pass) carry `{price_monthly_changed, old, new}` when the price moves. The replay snapshots each key's price to its current value, then walks every post-`as_of` price-change event and rewinds via the recorded `old` field — so the snapshot at `as_of` is the price right before the next change. `billing_mode` is treated as immutable (no CLI verb mutates it post-`issue_key`). Audit timestamps (`occurred_at` / `created_at`) are converted from UTC to `BILLING_TIMEZONE` before truncating to date so day-boundary comparisons honour the operator's midnight, not UTC's. Validates `earliest_audit_row.date ≤ as_of ≤ today` (both in `BILLING_TIMEZONE`); out-of-range exits 2. **Legacy fallback:** keys whose price moved only via pre-Story-5.1-review audit rows that lack `old/new` will show the current price (the only safe fallback); fresh deployments do not hit this path.
- **`update_customer` audit `details_json` carries `notes_op` (Story 5.1 review-pass).** Two operator paths land in the same `update_customer` action: `--add-note` (additive, append-mode) and `--notes` (destructive, replace-mode). Without a discriminator, a forensic reader cannot detect a notes-column wipe. `notes_op` is `"append"` or `"replace"` (operator-internal metadata, not PII — safe to record). Same-value writes (e.g. `--name "X"` against a customer already named "X") produce no UPDATE and no audit row at the helper level, so the audit log is free of "changed" rows that did not actually change anything. The `_FORBIDDEN_DETAIL_KEYS` invariant is enforced symmetrically on write (now `Sequence`-recursive) and read (`filter_forbidden_keys`).
- **`export-customer --include-audit` envelope grows `audit_events_total` + `audit_events_truncated` (Story 5.1 review-pass).** An LGPD Art. 18 II/V response must be provably complete or provably partial; silently capping at 1000 rows without signalling the truncation is a compliance gap. `audit_events` is now sorted ascending (chronological — matches `monetization.md` §1.4 wording). The `_audit_event_to_export_dict` projection emits `details: {"_corrupt": true}` for rows whose `details_json` is non-decodable or whose top-level JSON is not an object; the previous behaviour (silently dropping the field) hid out-of-band INSERTs from forensic readers. The `_EXPORT_AUDIT_LIMIT=1000` cap is unchanged — operators who hit truncation can paginate via `comadre-keys show --audit-tail` for the slice they need.

## Ansible Operations — LLM Runbook

Full guide: `docs/deployment-guide.md`. This section covers only invariants an
LLM MUST obey when executing ansible tasks.

### 1. Working directory

Always `cd deploy/ansible` first. The `ansible.cfg` there sets the inventory.
Running from elsewhere picks up no config → "host not found".

### 2. Mandatory environment variables

Export both before `bootstrap.yml`, `backup-keys.yml`, `restore-keys.yml`,
`health.yml`:

```bash
export COMADRE_KEY_REGISTRY_ENCRYPTION_KEY="<fernet>"
export COMADRE_BACKUP_PASSPHRASE="<passphrase>"
```

Generate with `uv run python -c` (see deployment-guide.md §Bootstrap). The
inventory reads them via `lookup('env', ...)` — unset → prerequisite assert
fails.

### 3. SSH credentials

Always pass both on every playbook invocation:

```bash
-e "ansible_password=PWD" -e "ansible_become_password=PWD"
```

Even for "no become" playbooks — `health.yml`'s UFW probe falls back to sudo.
Omit `ansible_password` only when using SSH key auth.

### 4. Execution order (fresh deploy)

```text
cleanup.yml → bootstrap.yml → deploy-voices.yml → health.yml → backup-keys.yml
```

Bootstrap needs **≥ 3600 s bash timeout** (model downloads + 30-min health poll).
`cleanup.yml` is optional if the VPS is already bare.

### 5. `deploy-models.yml` fails by design

When `qwen3_model_local` and `qwen3_tokenizer_local` are empty strings (the
default), the playbook fails its prerequisite check. This is **intentional** —
models auto-download on first startup via URLs. Do NOT treat this as a bug or
attempt to fix it.

### 6. Caddy Caddyfile syntax

`servers { header ... }` is invalid in Caddy v2. It was removed in commit
`f861f7b` after causing a crash loop. Do not reintroduce it. Server/Via
stripping is handled at the site level.

### 7. API key creation

The bootstrap summary message references `--tax-id` — this option does not
exist. Use `--cpf` or `--cnpj`; `--email` is also required:

```bash
comadre-keys create-customer --name "N" --email "x@y.com" --cpf "52998224725"
comadre-keys issue-key --customer cust_<id> --rpm 30 --price 149.00
```
