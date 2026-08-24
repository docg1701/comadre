# AGENTS.md

## Project Overview

Comadre is a self-hosted TTS API: **kyutai-labs pocket-tts 2.1.0** (pinned, `portuguese`, CPU-only) with native voice cloning (5-20s audio → clone, ephemeral or stored). Serves n8n chatbots (WhatsApp/Telegram/Messenger, pt-BR). v3.0.0 removed the v2 dual-engine. **API-first**: every feature via HTTP — landing page (`deploy/landing/`) is demo only.

## Tooling

- **Agent harness: DeepSeek Harness (DSH)** — loads `AGENTS.md` at session start; single source of truth.
- **`CLAUDE.md` absent by design** — superseded by `AGENTS.md`. Do not re-add `.claude/` or Claude artifacts.

## Language Policy

Everything in English — code, comments, commits, docs, configs, API responses. No exceptions.

## Build & Test

```bash
uv sync                          # torch CPU via pytorch-cpu index
uv run pytest                    # unit (mocked, no model)
uv run pytest -m slow            # integration (needs models)
uv run ruff check .              # lint
uv run mypy src/                 # strict
uv run pre-commit run --all-files
```

## CI / Release — mandatory

GitHub Actions (`.github/workflows/ci.yml`). Every push to `master` and every `v*` tag MUST be green — local green is not enough.

Jobs (sequential): **Lint** → **Test** → **Non-Regression** (docker) → **Release** (on `v*` tag only, needs 1-3 green). Release extracts `## [X.Y.Z]` from `CHANGELOG.md` and fails if absent.

```bash
gh run list --repo docg1701/comadre --limit 5
gh run watch <id> --repo docg1701/comadre
gh run view <id> --repo docg1701/comadre --log-failed
```

Release flow: bump versions + `## [X.Y.Z]` in `CHANGELOG.md` → commit → push `master` → **wait CI green** → `git tag vX.Y.Z` → push tag → **watch Release green** → `playbooks/update.yml` on VPS → verify `/health` version. Every fix ships as a patch tag in the same cycle — nothing rides unreleased.

## Architecture

- **Voices**: `pocket/<name>`. Operator: drop `.wav` into `/voices/pocket/` → live immediately (`.safetensors` + `.json` lazily, regen on `model_hash` mismatch). API uploads: `pocket/u_<ULID>` (`u_` reserved). Catalog `pocket/rafael` is a virtual embedding (`POCKET_DEFAULT_VOICE_PATH`). See `docs/voice-management.md`.
- **VoiceRegistry** (`src/comadre/service.py`): filesystem scan, LRU 16, ephemeral registry (idle 3600s, absolute 86400s, max 5/key, global LRU 50), stored quota 20/customer, 60s sweeper. All model work under per-replica FIFO `asyncio.Lock` (API layer owns it).
- **Upload**: `POST /v1/voices` → verify_ready → per-IP 600/min → verify_api_key → per-key RPM bucket → Content-Length 413 → stream to tmp with size guard → soundfile 3-30s → FIFO lock → `get_state_for_audio_prompt(truncate=True)` → persist trio or ephemeral → 201.
- **FIFO queue**: one `asyncio.Lock` per replica. Scale via `compose.yaml` replicas — Caddy `dynamic a` resolver (5s, `least_conn`).
- **Preprocessing**: `normalize_text()` (currency/dates/times/phones/percent/numbers + sanitizer). Sigla spacing removed — intact `ABS`/`CNPJ` reads more naturally. Library chunks internally; char limit 1000.
- **Post-processing**: one pipeline (`_apply_pipeline`): ffmpeg EQ/compression/loudnorm + atempo chain for `speed` [0.5,2.0] + noise mix + encode. OGG Opus 24k 16kHz mono `voip` (default, WhatsApp-verified), MP3 64k 44.1k, WAV 24k. 500 ms lead silence masks clipped first phoneme.
- **Module boundaries**: no HTTP in `service.py`, no business logic in `api.py`/`voices_api.py`, no raw `os.environ` (use `pydantic-settings`), no raw `HTTPException` (use `ComadreError`), `voice_storage.py` is the only shared filesystem layer (API + `comadre-keys` LGPD verbs).
- **HTTPS**: Caddy terminates TLS (port 80/443), sole external entry. Domain via `DOMAIN`.
- **Rate limiting**: per-key via `limits` (`MovingWindowRateLimiter`, in-memory). `POST /v1/audio/speech` + `POST /v1/voices` share one bucket per `key:<key_id>` (from `rate_limit_rpm`). Stable across `rotate-key`; `/health` not rate-limited at app layer. Counters in `src/comadre/counters.py` (reset on restart, snapshotted every 15s to `{DB}.counters.{hostname}.json`). In-memory → N replicas = N× effective RPM.
- **Landing**: Caddy `file_server` at `/`, API at `/v1/*`/`/health`. Assets `deploy/landing/` bind-mounted `/srv/www:ro`. Voice picker from `/health`, `pocket/rafael` default.
- **Import graph**: `config/logging → exceptions/schemas → preprocessing → service/voice_storage → rate_limit → api/voices_api → main`. Downward only.

## Code Conventions

- Python 3.12, mypy strict + pydantic plugin, ruff (88), `uv` only, `docker compose` v2.
- All errors via `ComadreError` (`status_code`/`error_type`/`hint`); structured `timestamp | level | component | message` logging; never `print()`.
- Ansible: pass `-e "ansible_become_password=PWD"` for every `become: true` playbook; never store passwords in inventory.

## Key Files

- `src/comadre/` — `config`/`logging`/`schemas`/`exceptions`/`preprocessing`/`service`/`voice_storage`/`rate_limit`/`health`/`download`/`api`/`voices_api`/`main`; `keys/` — `db`/`auth`/`cache`/`crypto`/`audit`/`health`/`cli/` (21 verbs).
- `tests/` — mocked suite; cloning in `test_voice_registry.py`/`test_voices_api.py`.
- `deploy/pocket-tts/*.yaml` — baked configs (omit `weights_path_without_voice_cloning` → fail fast if gated weights missing).
- `docs/` — API/architecture/v3 spec/config/voice/deployment/troubleshooting/monetization/rate-limiting/scaling.
- `scripts/spike_pocket_tts.py` — tuning harness; `scripts/loadtest.py`/`capacity_test.py`.

## Gotchas (1 line each — break any and CI or prod breaks)

- `torch.set_num_threads(1)` is called inside `pocket_tts` import — re-apply `torch.set_num_threads(POCKET_THREADS)` after import (D15).
- `generate_audio(..., copy_state=True)` required — state mutates otherwise, corrupts LRU.
- Gated model `kyutai/pocket-tts@39592ff` needs one-time `HF_TOKEN`; offline `HF_HUB_OFFLINE=1` after. Don't unpin revisions.
- Config YAMLs omit `weights_path_without_voice_cloning` — missing gated weights must fail, not fall back.
- Keep reference `.wav` for every clone — needed for `model_hash` regen.
- `u_` prefix reserved for `u_<ULID>` uploads; operator names `u_*` not matching ULID are rejected.
- `torch` must be direct dep with `[[tool.uv.index]] pytorch-cpu` + `torch` source + `environments = ["sys_platform == 'linux'"]` — else uv resolves CUDA build; use `uv lock --no-cache` on index changes.
- `rafael` is virtual (embedding, not filesystem).
- Clone state ~3 MB per 5s (6-layer) — upload cap 30s / UI 5-20s.
- `RegistrySettings.voices_dir` is the sole CLI↔voices exception (LGPD `export`/`delete --hard` via `voice_storage`).
- `deploy-models.yml` fails when `pocket_*_local` empty — by design (auto-download via `HF_TOKEN`); not a bug.
- Suspension sweep is `paid_until < today` (strict), not `<=`; cron at 00:30 in `billing_timezone` (`CRON_TZ`); `BILLING_TIMEZONE` env must match; UTC default — changing it is contractual.
- `health` cron detection via marker `{DB}.cron-installed` (not `crontab -l`); "Last sweep" age from `audit_log`.
- `health --format json` exits 7 on warn/fail; table exits 0. Exit codes: 0 ok, 2 usage/validation, 3 not-found, 4 Fernet shape (rotate-encryption-key), 5 DB, 6 config/perm, 7 unhealthy JSON.
- Tombstone keeps `tax_id_encrypted NOT NULL` as `X''` (not `NULL`) — signal is `deleted_at IS NOT NULL`.
- `fernet.decrypt` has one allowed call site: `crypto.py::decrypt_tax_id` — new sites must route there.
- `rotate-encryption-key` skips tombstones, re-encrypts active only; success line echoes new key (sole surface).
- Backup glob `{DB}.backup-*.tar.gz.enc` (dash-separated `T02-00-00Z`, not colons) — renaming breaks `Last backup` health check.
- `BACKUP_PASSPHRASE` may be empty at boot (playbooks enforce ≥16 chars); `grep` invariant: one hit in `config.py`.
- `restore-keys.yml` warns on archived-key ≠ live `.env`, never auto-swaps.
- `health.yml` playbook exits non-zero on any deviation — wire to monitoring; don't soften to debug print.
- `bootstrap.yml` chmod tasks + `get_connection` `_chmod_0600`/`mkdir 0700` are both required (Python = runtime drift, ansible = bootstrap self-evidence); chmod runs after `[FS] Wait` poll (30×2s).
- `health` has two cron rows (`Cron` + `Backup cron`); marker paths derive from `KEY_REGISTRY_DB_PATH`.
- `export-customer --include-audit` default off (LGPD minimum; counsel decides).
- `correct-tax-id` preserves `customer_id`/FKs; `delete --hard` + `create` does not.
- `mark-paid --months` anchors on `paid_until` if ≥today else today; `--price-monthly` atomic; mutually exclusive with `--until`.
- `revenue --as-of` replays audit up to `as_of` (converted via `BILLING_TIMEZONE`); validates `earliest ≤ as_of ≤ today`; legacy price rows fallback to current price.
- `update_customer` `details_json` carries `notes_op` (`append`/`replace`); same-value writes produce no audit row.
- `export-customer --include-audit` adds `audit_events_total`/`truncated`, sorted asc, corrupt JSON → `{"_corrupt": true}`, cap 1000.

## Ansible Runbook

- `cd deploy/ansible` first (`ansible.cfg` sets inventory).
- Env before `bootstrap`/`backup`/`restore`/`health` + `HF_TOKEN` first v3 boot:
  `export COMADRE_KEY_REGISTRY_ENCRYPTION_KEY="<fernet>" COMADRE_BACKUP_PASSPHRASE="<pass>" [HF_TOKEN="<tok>"]`
- SSH: always `-e "ansible_password=PWD" -e "ansible_become_password=PWD"` (health UFW probe needs sudo even though unprivileged).
- Fresh order: `cleanup.yml` (optional) → `bootstrap.yml` (≥3600s timeout) → `deploy-voices.yml` → `health.yml` → `backup-keys.yml`.
- `deploy-models.yml` fail with empty `pocket_*_local` is intentional.
- Caddy: `servers { header ... }` invalid in v2 — don't re-add.
- Key creation: `create-customer --cpf`/`--cnpj` + `--email` (not `--tax-id`), then `issue-key --customer cust_… --rpm 30 --price 149.00`.
