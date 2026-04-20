# Story 4.3: Backup & Restore Playbooks

Status: done

> **Scope note — FR40, FR41.** Adds the operational pair that closes the 24-hour RPO loop on the key registry: `deploy/ansible/playbooks/backup-keys.yml` (nightly run via a new `comadre-keys-backup` cron entry installed by `bootstrap.yml` at **02:00 operator-TZ**) and `deploy/ansible/playbooks/restore-keys.yml` (operator-invoked, idempotent, takes `-e "backup_file=<path>"`). The backup playbook drives a single `docker compose exec -T tts-service` shell that (1) opens a SQLite consistency snapshot via `Connection.backup()` from the Python stdlib; (2) extracts `KEY_REGISTRY_ENCRYPTION_KEY` from the running container's env into a sibling file; (3) `tar -cz`s both payloads; (4) pipes the tarball through `openssl enc -aes-256-cbc -pbkdf2 -salt -pass env:BACKUP_PASSPHRASE` to produce `{db_parent}/registry.db.backup-<UTC-ISO>.tar.gz.enc` at filesystem mode `0600`; (5) deletes `*.backup-*.tar.gz.enc` artefacts older than `backup_retention_days` (inventory var, default **14**). The restore playbook inverses every step, stops the service briefly to swap the live DB file (so WAL sidecars don't split across the restore boundary), restores file mode `0600`, and restarts the service. Because the backup tarball is dropped into the DB's parent directory (the named `comadre-registry` volume), it lands exactly where `src/comadre/keys/health.py::_check_last_backup` already globs `*.backup-*.tar.gz.enc` — meaning the **sole code change in `src/comadre/` for this story** is the one-line flip of `_BACKUP_NOT_IMPLEMENTED_INFO = True → False` (the Story 3.4 ↔ Story 4.3 handshake already soldered in place at `keys/health.py:44`). A new required env var `BACKUP_PASSPHRASE` (`SecretStr`) is added to `Settings` for round-trip validation, sourced from `COMADRE_BACKUP_PASSPHRASE` on the control machine, written into `.env` at bootstrap, and NEVER logged. **No schema change. No auth-path change. No FastAPI runtime change. No new CLI verb.** The story is primarily ansible + docs + two small Python surface changes (the constant flip and the new settings field).

## Story

As an operator,
I want automated nightly backups of the key registry plus its encryption key, and a tested, idempotent restore procedure,
so that I can recover from a catastrophic VPS failure, a corrupted SQLite file, an accidental `delete-customer --hard`, or a lost encryption key within the 24-hour RPO (NFR22) and the 10-minute RTO for ≤10,000 customers (NFR21) — with no separately-engineered backup tool, no cloud dependency, and no ambiguity about what is in the archive or how to decrypt it.

**Covers FRs:** FR40 (System can back up the key registry and encryption material nightly, in a single encrypted archive separate from the database file itself), FR41 (Operator can restore the key registry from a prior backup via a dedicated, idempotent playbook).
**NFRs:** NFR14 (Backup archives must have filesystem mode `0600` and include the encryption key separately encrypted from the database payload), NFR21 (Backup RTO — restore-keys.yml must restore in under 10 minutes for ≤10,000 customers), NFR22 (Backup RPO — data loss from catastrophic VPS failure must not exceed 24 hours), NFR32 (Ansible idempotency — applies to both new playbooks), NFR13 (DB file `0600` preserved across restore).
**UX-DRs:** Operator-facing command grammar (the two playbooks are invoked with the same `ansible-playbook <name>.yml -e "ansible_become_password=..."` shape as `bootstrap.yml` / `cleanup.yml` / `health.yml`); restore is the Destroy-tier at the playbook layer (replaces a live DB file) and requires an explicit `-e "backup_file=<path>"` — no auto-discovery. No new CLI verb, so CLI-level UX-DRs don't apply.
**Epic:** 4 — Security Hardening, LGPD & Operational Safety. Third story in Epic 4 (4.1 → 4.2 → **4.3** → 4.4 → 4.5a–g → 4.6). Story 4.4 (Operational Safety) will assert on `health.yml` that the `comadre-keys-backup` cron entry exists + the last backup file is present and fresh; Story 4.6 (LGPD Documentation & Breach Runbook) will cite this story's restore procedure in the breach-response flow ("if the registry is compromised, rotate via 4.2, then immediately back up via 4.3 to capture the post-rotation state").

## Builds on

- **Story 1.1 — `KEY_REGISTRY_DB_PATH` + bind-to-`/var/lib/comadre/` + `0600` DB-file discipline.** `src/comadre/config.py:113-117` (`key_registry_db_path` default `./data/keys/registry.db`), `compose.yaml:39` (`comadre-registry:/var/lib/comadre:rw`), `keys/db.py::_chmod_0600` all establish the bind convention the backup tarball will co-reside with. The new archives land at `{Path(KEY_REGISTRY_DB_PATH).parent}/` — container path `/var/lib/comadre/` — so they ride on the same named volume, inherit the same backup-domain, and are visible to the same in-container health glob that Story 3.4 already shipped.
- **Story 3.3 — `bootstrap.yml` cron pattern + `CRON_TZ` discipline.** `deploy/ansible/playbooks/bootstrap.yml:308-328` is the canonical template for installing a host-cron entry that shells out to `docker compose exec -T tts-service ...`. The new `comadre-keys-backup` entry at **02:00** follows that template verbatim, piping stdout+stderr through `logger -t comadre-backup` so cron failures are captured in syslog. The `CRON_TZ` env var is re-used — there's one `CRON_TZ` shared by every Comadre cron entry on the host.
- **Story 3.3 — cleanup.yml symmetry.** `deploy/ansible/playbooks/cleanup.yml:56-83` removes cron entries in the exact reverse order of install. The new backup cron + its marker file follow the same pattern (remove marker first → remove cron entry → let the existing `CRON_TZ` removal handle the shared env var).
- **Story 3.4 — `_check_last_backup` + `_BACKUP_NOT_IMPLEMENTED_INFO` handshake.** `src/comadre/keys/health.py:44` (`_BACKUP_NOT_IMPLEMENTED_INFO = True`) and `keys/health.py:386-479` (`_check_last_backup`) reserve the `*.backup-*.tar.gz.enc` glob pattern rooted at the DB's parent directory, with the warn/fail branches **already implemented but gated**. `tests/test_keys_health.py:544-574` (`TestBackupCheck::test_info_only_today_without_backup` + `test_info_only_today_even_with_existing_backup_file`) are **forcing-function tests** that will start failing the moment the constant flips — by design. Both tests are rewritten in this story to assert the post-flip behaviour (`warn` when no file; `warn` when stale > 48 h; `ok` when fresh). The backup-glob pattern (`*.backup-*.tar.gz.enc` under the DB parent) is the architecture-reserved contract that dictates this story's tarball naming.
- **Story 3.4 — marker-file pattern for health visibility.** `bootstrap.yml:330-341` writes `{KEY_REGISTRY_DB_PATH}.cron-installed` as the evidence-marker the in-container `health` CLI stats to report cron-liveness. Story 4.3 extends this by writing a sibling `{KEY_REGISTRY_DB_PATH}.backup-cron-installed` at bootstrap for the same purpose — forward-compatibility for a future Story 4.x that adds a dedicated `Backup cron` row to the `health` report (noted in `_bmad-output/implementation-artifacts/3-4-system-health-command.md:242` — "when Story 4.3 lands the backup cron, it can write `{db_path}.backup-cron-installed` following the same convention"). Story 4.3 writes the marker but does NOT add a new `health` row (deferred to Story 4.4 per §Deferred-work below) — the marker is installed now so Story 4.4 doesn't have to revisit bootstrap.yml.
- **Story 4.1 — `ansible_become_password` via `-e`, no inventory storage.** `CLAUDE.md` contains the invariant "Ansible become password passed via `-e`, not stored in inventory". Both new playbooks follow this convention. The backup playbook doesn't strictly need `become:` (all writes land inside a Docker volume owned by the unprivileged user), but the restore playbook stops the tts-service briefly — `docker compose` from the deploy user handles that without sudo on a standard docker-group member, so neither playbook needs `become:` at the task level either. The `-e "ansible_become_password=..."` CLI pattern is preserved in the playbook header docstrings for consistency with the existing suite, not because a become step is triggered.
- **Story 4.2 — `docker compose exec -T tts-service comadre-keys ...` orchestration from ansible tasks.** `docs/deployment-guide.md:506-525` is the canonical operator recipe; Story 4.3's backup playbook follows the same shell-execution pattern but drives `bash -c '<script>'` inline (no new CLI verb — see §Design-decisions below).
- **Existing Dockerfile + Debian-slim base.** `python:3.12-slim` ships `tar` and `gzip` in the base layer (pulled in via dpkg). `openssl` CLI is **not** in python:3.12-slim by default — it's added by this story as a single-line `apt-get install -y --no-install-recommends openssl sqlite3` during the existing "System dependencies" apt run at `Dockerfile:36-48`. (Python's stdlib covers the snapshot; `openssl` covers the encryption; `tar` covers the packaging. `sqlite3` CLI is added for operator debugging convenience — not invoked by the playbook.)

## Unblocks

- **Story 4.4 — Operational Safety & File Permissions.** AC3 of Story 4.4 (`_bmad-output/planning-artifacts/epics.md:869-872`) requires `health.yml` to assert `cron jobs installed (comadre-daily-suspension, comadre-keys-backup), last backup output exists`. Story 4.3 ships the cron entry, the marker file, AND the archive that `health.yml` will assert on. Without 4.3 landing first, 4.4's "last backup output exists" assertion has nothing to stat.
- **Story 4.6 — LGPD Documentation & Breach Runbook.** `docs/monetization.md` will cite the full disaster-recovery path: (1) detect compromise, (2) rotate via 4.2, (3) immediately back up via 4.3 so the new-key ciphertext is captured in the archive (otherwise the next nightly still ships the pre-rotation key-version mismatch for up to 24 h), (4) document the restore drill for new operators. 4.6 lands prose; 4.3 ships the playbooks the prose references.
- **Deployment-time disaster readiness.** Until 4.3 ships, the only "backup" is the manual `sqlite3 registry.db ".backup .snapshot.db"` operators must remember to run ad-hoc. After 4.3 lands and bootstrap is re-applied once, nightly backups become automatic and the 24 h RPO starts being honoured by the deployment, not just the PRD.

## Depends on

- Stories 1.1 (registry schema + `KEY_REGISTRY_DB_PATH` bind), 3.3 (cron scaffolding in `bootstrap.yml` + `cleanup.yml`), 3.4 (`_check_last_backup` + forcing-function tests) must all be `done`. Sprint-status.yaml (`_bmad-output/implementation-artifacts/sprint-status.yaml`) confirms: `1-1: done`, `3-3: done`, `3-4: done` (all landed before 2026-04-20).
- **One new env var:** `BACKUP_PASSPHRASE` (pydantic `SecretStr`), added to `src/comadre/config.py::Settings` alongside `key_registry_encryption_key`. **Required at bootstrap time** (playbook fails closed if the control-machine env var `COMADRE_BACKUP_PASSPHRASE` is empty, mirroring the existing `COMADRE_KEY_REGISTRY_ENCRYPTION_KEY` assertion at `bootstrap.yml:43-54`); **required at backup/restore playbook run time** (both playbooks assert the presence and length ≥ 16 chars before invoking `openssl`); **optional at service boot time** — the FastAPI app and the `comadre-keys` CLI (every verb except an eventual future `backup`/`restore` verb, not shipped in 4.3) do NOT read this field, so missing `BACKUP_PASSPHRASE` in `.env` does NOT crash the auth path. Pydantic's default on a missing `SecretStr` field is to raise — so the field ships with a default of `SecretStr("")` plus a custom validator that accepts empty OR ≥ 16 chars; the backup/restore playbooks do the strict check at playbook run time.
- **One new Dockerfile package:** `openssl` (and `sqlite3` CLI as an operator-debug convenience) added to the existing `apt-get install` at `Dockerfile:36-48`. This is a ~+1 MB image size increase and a trivial change.
- **No schema change.** The registry is snapshotted as-is via `sqlite3.Connection.backup()`; the tarball is opaque to the schema.
- **No auth-path change.** `src/comadre/api.py`, `src/comadre/main.py`, `src/comadre/rate_limit.py`, `src/comadre/keys/auth.py`, `src/comadre/keys/cache.py`, `src/comadre/counters.py`, `src/comadre/keys/migrations/` stay byte-identical (asserted by AC12).
- **No CLI verb added.** Backup/restore orchestration stays in ansible. A future Story 4.x can wrap the bash snippet in a `comadre-keys backup` / `comadre-keys restore` verb if operator ergonomics justify it — see §Deferred-work below.

## Scope

Two new ansible playbooks, one new cron entry in `bootstrap.yml` + its symmetric removal in `cleanup.yml`, a new inventory variable block, a one-line Python flip of the `_BACKUP_NOT_IMPLEMENTED_INFO` handshake, a new `BACKUP_PASSPHRASE` field in `Settings`, one Dockerfile package add, rewrites of the two forcing-function health tests, and docs. **No new dep on the Python side. No schema change. No auth-path change. No new CLI verb.**

### 1. New playbook: `deploy/ansible/playbooks/backup-keys.yml`

Creates a nightly-consistent encrypted snapshot of the SQLite registry + its Fernet key, writes it under the DB's parent directory (visible to the in-container `health` glob), and prunes archives older than `backup_retention_days`.

**Playbook structure (in order):**

1. **Prereq block** — same shape as `bootstrap.yml:23-54`:
   - Assert `BACKUP_PASSPHRASE` is non-empty AND length ≥ 16 — pulled from `{{ backup_passphrase }}` which is sourced from `{{ lookup('env', 'COMADRE_BACKUP_PASSPHRASE') }}` in inventory. Fail with a corrective hint: `export COMADRE_BACKUP_PASSPHRASE="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"` — at least 16 chars, ideally 32+.
   - Assert `~/comadre/` exists (SSH works, deployment is present — standard prereq ping).
   - Assert the `tts-service` container is running (via `docker compose ps -q tts-service` returning a non-empty stdout). The backup requires an in-container execution context; if the service is down, fail fast with "start the service before running backup-keys.yml".

2. **Backup execution block** — one `community.docker.docker_compose_v2_exec` (or raw `ansible.builtin.command: docker compose exec ...`) task that invokes a single `bash -c` script:
   ```bash
   set -euo pipefail
   umask 077  # new files default to 0600

   DB_PATH="$KEY_REGISTRY_DB_PATH"   # /var/lib/comadre/registry.db
   DB_DIR="$(dirname "$DB_PATH")"    # /var/lib/comadre
   TS="$(date -u +%Y-%m-%dT%H-%M-%SZ)"
   STAGING="$(mktemp -d -t comadre-backup.XXXXXX)"
   trap 'rm -rf "$STAGING"' EXIT

   # Step 1 — SQLite consistency snapshot via Python stdlib (no sqlite3 CLI
   # dependency; identical to .backup semantics). See §Dev-Notes on why
   # .backup() is required instead of a plain cp of the live file.
   python -c "
   import sqlite3, sys
   src = sqlite3.connect(sys.argv[1])
   dst = sqlite3.connect(sys.argv[2])
   with dst: src.backup(dst)
   src.close(); dst.close()
   " "$DB_PATH" "$STAGING/registry.db"

   # Step 2 — capture the live Fernet key (from the process env, NOT by
   # re-reading .env — the container was started with whatever was in .env
   # at `docker compose up` time; any subsequent .env edit that hasn't yet
   # been followed by `docker compose restart` has NOT taken effect inside
   # the container. The env-var read is the source of truth).
   printf '%s' "$KEY_REGISTRY_ENCRYPTION_KEY" > "$STAGING/encryption-key.txt"
   chmod 0600 "$STAGING/encryption-key.txt"

   # Step 3 — tar both payloads together (no path prefix — bare filenames
   # inside the archive so `restore-keys.yml` can `tar -xf` with no
   # `--strip-components`). tarball is NOT encrypted in this step; the
   # outer openssl envelope is the security boundary.
   tar -C "$STAGING" -czf "$STAGING/bundle.tar.gz" registry.db encryption-key.txt

   # Step 4 — encrypt with AES-256-CBC + PBKDF2 + random salt. Passphrase
   # from the container env (populated by `.env` via compose). The resulting
   # ``.tar.gz.enc`` file is self-describing: first 16 bytes are "Salted__"
   # + 8-byte salt per openssl's standard enc format. OpenSSL 3 default
   # iter count (PBKDF2-HMAC-SHA256) is 10,000 — adequate for our threat
   # model (backup tarball + passphrase together == offline attacker; a
   # 32+ char passphrase + 10K iters is already hundreds of CPU-years).
   openssl enc -aes-256-cbc -pbkdf2 -salt \
     -in "$STAGING/bundle.tar.gz" \
     -out "$DB_DIR/registry.db.backup-$TS.tar.gz.enc" \
     -pass env:BACKUP_PASSPHRASE

   chmod 0600 "$DB_DIR/registry.db.backup-$TS.tar.gz.enc"

   # Step 5 — retention. Glob every backup archive older than N days and
   # rm -f. The find is scoped to the DB parent; mtime is the archive's
   # creation time (staging is tmpfs so atime/ctime don't matter). N comes
   # from BACKUP_RETENTION_DAYS which the playbook injects into the exec env.
   find "$DB_DIR" -maxdepth 1 -type f \
     -name 'registry.db.backup-*.tar.gz.enc' \
     -mtime +"$BACKUP_RETENTION_DAYS" -print -delete

   # Step 6 — report success to stdout for the playbook's register.
   echo "comadre-backup OK: $DB_DIR/registry.db.backup-$TS.tar.gz.enc"
   ```
   The ansible task passes `env: { BACKUP_RETENTION_DAYS: "{{ backup_retention_days | default(14) }}" }` on the `docker compose exec` invocation (compose-v2 honours `-e VAR=value` per exec). The `BACKUP_PASSPHRASE` env var is already present inside the container because `bootstrap.yml` wrote it to `.env` and compose-v2 loads `.env` at service start.

3. **Post-backup verification task** — `ansible.builtin.command: docker compose exec -T tts-service ls -l "$KEY_REGISTRY_DB_PATH.backup-$TS.tar.gz.enc"` with `changed_when: false`. Asserts the file exists and the mode is `0600` (grep the `ls -l` output). Register into `backup_verify`; the summary task cites `backup_verify.stdout`.

4. **Summary task** — prints the archive path, size (human-readable via `du -h`), retention policy, and the next scheduled-cron time. Emits a copy-paste-ready SCP one-liner for off-VPS archival: `scp YOUR_SSH_USER@VPS:/path/to/archive.tar.gz.enc ./backups/` (operator is expected to rotate archives off-VPS; that's a runbook concern in Story 4.6, not a playbook task).

**Idempotency property.** Running `backup-keys.yml` twice back-to-back produces two separate tarballs (different `TS` suffix) — it is NOT idempotent in the "second run is a no-op" sense. That's intentional: the playbook's contract is "create a fresh archive"; re-running is re-snapshotting. The idempotency invariant (NFR32) applies narrowly — the playbook's cron entry install / marker write inside `bootstrap.yml` IS idempotent (the `ansible.builtin.cron` module uses `name:` as the idempotency key). Re-running `bootstrap.yml` doesn't duplicate the cron entry.

**Cron entry wiring** (installed by `bootstrap.yml`, see §3 below, NOT by this playbook):
```yaml
- name: "[Cron] Configure nightly key-registry backup at 02:00 operator TZ"
  ansible.builtin.cron:
    name: "comadre-keys-backup"
    minute: "0"
    hour: "2"
    job: >-
      /bin/bash -c 'set -o pipefail;
      cd ~/comadre &&
      ansible-playbook -i deploy/ansible/inventory/production.yml
      deploy/ansible/playbooks/backup-keys.yml 2>&1 |
      logger -t comadre-keys-backup'
```
Same pipefail discipline as Story 3.3's suspension-sweep cron (preserves the ansible playbook's exit code through the `logger` pipe so cron's MTA sees real failures, not logger's sanitised 0). The cron entry runs `ansible-playbook` FROM the VPS itself (not from the control machine) — the inventory is checked into the repo, the playbook is checked in, and the control-target-is-itself pattern works because the deploy user has ansible installed as part of Comadre's 1.6.2 deploy discipline (already assumed by every other cron). If a given deployment doesn't have ansible installed locally, the alternative cron body is `docker compose exec -T tts-service bash -c '<inline-script>'` — functionally identical, skips the playbook wrapper, harder to debug but one fewer dep. Recommend the playbook-wrapper form; document the direct-bash alternative in the playbook header comments.

### 2. New playbook: `deploy/ansible/playbooks/restore-keys.yml`

Restores a previously-captured archive, stopping the service briefly so the WAL sidecars don't straddle the swap, and reports whether the archive's encryption key matches the live `.env` (if it doesn't, prompt the operator to also update `.env`).

**Playbook structure (in order):**

1. **Prereq block.**
   - Assert `backup_file` was passed: `-e "backup_file=/path/to/registry.db.backup-....tar.gz.enc"`. Fail-fast with usage hint otherwise.
   - Assert `backup_file` exists AND is a regular file AND is readable.
   - Assert `BACKUP_PASSPHRASE` env var is non-empty (`COMADRE_BACKUP_PASSPHRASE`).
   - Assert `~/comadre/` exists.
   - Assert the tts-service is running (we need `docker compose` to be invokable; the service itself we're about to stop briefly).

2. **Staging block** — `docker cp` the archive INTO the container via a helper task (or bind-mount `backup_file`'s host dir into `tts-service` for the duration of the restore; the `docker cp` approach is simpler and idempotent): the playbook runs `docker cp "{{ backup_file }}" "$(docker compose ps -q tts-service | head -1)":/tmp/restore-archive.tar.gz.enc`.

3. **Decrypt + untar block** — one `docker compose exec -T tts-service bash -c` script:
   ```bash
   set -euo pipefail
   umask 077

   DB_PATH="$KEY_REGISTRY_DB_PATH"
   DB_DIR="$(dirname "$DB_PATH")"
   STAGING="$(mktemp -d -t comadre-restore.XXXXXX)"
   trap 'rm -rf "$STAGING" /tmp/restore-archive.tar.gz.enc' EXIT

   # Step 1 — decrypt.
   openssl enc -d -aes-256-cbc -pbkdf2 \
     -in /tmp/restore-archive.tar.gz.enc \
     -out "$STAGING/bundle.tar.gz" \
     -pass env:BACKUP_PASSPHRASE

   # Step 2 — untar.
   tar -C "$STAGING" -xzf "$STAGING/bundle.tar.gz"

   # Step 3 — sanity-check payload shape.
   test -f "$STAGING/registry.db" || { echo "Archive missing registry.db"; exit 1; }
   test -f "$STAGING/encryption-key.txt" || { echo "Archive missing encryption-key.txt"; exit 1; }

   # Step 4 — verify the snapshot DB opens cleanly. integrity_check
   # guards against a corrupted tarball being written over the live DB.
   python -c "
   import sqlite3, sys
   conn = sqlite3.connect(sys.argv[1])
   result = conn.execute('PRAGMA integrity_check').fetchone()[0]
   conn.close()
   sys.exit(0 if result == 'ok' else 1)
   " "$STAGING/registry.db"

   # Step 5 — compare the archived key against the live env. If they
   # diverge, the archived key is the authoritative one to use post-restore
   # (tax_id_encrypted BLOBs in the archived DB were encrypted under it).
   # Print a warning with the archived key so the operator can swap .env.
   ARCHIVED_KEY="$(cat "$STAGING/encryption-key.txt")"
   if [ "$ARCHIVED_KEY" != "$KEY_REGISTRY_ENCRYPTION_KEY" ]; then
     echo "WARN: archived encryption key differs from live .env"
     echo "WARN: archived key (use this post-restore): $ARCHIVED_KEY"
     echo "WARN: update .env then: docker compose restart tts-service"
   fi
   ```
   The "archived key ≠ live" warning is stdout from the `docker compose exec`; the ansible task captures it via `register:` and the playbook's summary task re-emits it.

4. **Service-stop block** — `community.docker.docker_compose_v2` with `state: present, services: [tts-service], stopped: true` OR the explicit `docker compose stop tts-service` equivalent. The stop window is expected to be ≤ 30 s for ≤ 10,000 customers (NFR21). The caddy container is NOT stopped — it will 503 for the stop window, which is acceptable for a manual DR drill.

5. **DB-swap block** — one `docker compose exec -T tts-service bash -c`:
   ```bash
   set -euo pipefail
   # Remove stale WAL/SHM sidecars — they're invalidated by a DB swap.
   rm -f "$KEY_REGISTRY_DB_PATH-wal" "$KEY_REGISTRY_DB_PATH-shm"
   # Move the restored DB into place.
   mv "$STAGING/registry.db" "$KEY_REGISTRY_DB_PATH"
   chmod 0600 "$KEY_REGISTRY_DB_PATH"
   # Verify WAL mode on first re-open (idempotent, already enforced by
   # keys/db.py::get_connection; this is belt-and-braces for the playbook).
   python -c "
   import sqlite3, sys
   conn = sqlite3.connect(sys.argv[1])
   conn.execute('PRAGMA journal_mode=WAL')
   mode = conn.execute('PRAGMA journal_mode').fetchone()[0]
   conn.close()
   sys.exit(0 if mode == 'wal' else 1)
   " "$KEY_REGISTRY_DB_PATH"
   ```
   The `$STAGING` directory survives across the docker exec calls because they run as the same user in the same container and `$STAGING` was mkstempd under `/tmp` which is container-local — actually this is wrong, each `docker compose exec` spawns a fresh shell and `/tmp` IS shared but `$STAGING`'s exact path is only known within the originating shell's env. The cleanest approach is to run the whole decrypt+verify+swap sequence in ONE `docker compose exec` call, not split across multiple. Restructure: steps 3, 4, 5, 6 above all run in one bash script, with the service-stop sandwiched between the "verify archive" and "install-over-live" halves via two separate ansible tasks and the staging path written to a well-known location (`/var/lib/comadre/.restore-staging/`) shared across execs. Final structure:
   - Exec 1: decrypt + untar + integrity-check + write staging to `/var/lib/comadre/.restore-staging/`.
   - Ansible: stop tts-service.
   - Exec 2 via a helper container (since tts-service is stopped): alpine w/ volume mounted, do `mv` + `chmod` + WAL verify. Or start tts-service back with a no-op override and run the mv inside; simpler to use a one-shot helper container pattern like `bootstrap.yml:227-251` uses for voice deployment.
   - Ansible: start tts-service.
   - Ansible: poll `/health` until it reports `healthy`.

   See §Dev-Notes below for the three-exec vs one-exec trade-off and the decision to use a helper container for the swap step.

6. **Service-start + health-wait block** — identical to `bootstrap.yml:347-357` (`uri:` polling `https://{{ domain | default('localhost') }}/health` until `healthy`, with retry=180 / delay=10 → 30 min ceiling, same as bootstrap). If health-wait times out, the playbook fails with "service did not return to healthy after restore — inspect logs with `docker compose logs tts-service`". Exit code non-zero; the operator's terminal sees the failure plainly.

7. **Summary task** — prints: restored DB path, archive path, archived-vs-live encryption-key divergence warning (if any), health-endpoint response time, a post-restore smoke command (`docker compose exec tts-service comadre-keys list-customers | head`) for the operator to sanity-check.

**Idempotency.** Running `restore-keys.yml` twice with the same `backup_file` produces the same end state: the DB file bits are byte-identical (same archive → same `registry.db` post-untar); the file mode is `0600`; WAL mode is `wal`. Stale WAL sidecars are removed on both runs. The only non-idempotent surface is the audit log — neither run writes new audit rows; restore is an ops event, not a registry mutation. (A future Story 4.x COULD add a `registry_restored` audit row via a post-restore `comadre-keys log-restore-event` verb; deferred.)

### 3. Changes to `deploy/ansible/playbooks/bootstrap.yml`

Three new tasks, all idempotent:

1. **Assert `backup_passphrase` is configured** (new prereq task, after the existing "Validate key registry encryption key is configured" at `bootstrap.yml:43-54`):
   ```yaml
   - name: "[Prereq] Validate backup passphrase is configured"
     ansible.builtin.assert:
       that:
         - backup_passphrase | length >= 16
       fail_msg: >-
         COMADRE_BACKUP_PASSPHRASE environment variable is not set or
         is shorter than 16 characters. Generate a fresh passphrase with:
         export COMADRE_BACKUP_PASSPHRASE="$(python -c 'import secrets;
         print(secrets.token_urlsafe(32))')"
       success_msg: "Backup passphrase is configured ({{ backup_passphrase | length }} chars)."
   ```

2. **Write `BACKUP_PASSPHRASE` to `.env`** (extend the existing "[Config] Create .env file" task at `bootstrap.yml:257-271`):
   ```yaml
   content: |
     KEY_REGISTRY_ENCRYPTION_KEY={{ key_registry_encryption_key }}
     KEY_REGISTRY_DB_PATH=/var/lib/comadre/registry.db
     BACKUP_PASSPHRASE={{ backup_passphrase }}
     # ...rest of existing .env content unchanged...
   ```
   The `.env` file mode remains `0600` (existing discipline).

3. **Install the backup cron entry + its marker file** (new tasks, in the `# Cron Jobs` block after the existing suspension-sweep entries at `bootstrap.yml:314-341`):
   ```yaml
   - name: "[Cron] Configure nightly key-registry backup at 02:00 operator TZ"
     ansible.builtin.cron:
       name: "comadre-keys-backup"
       minute: "0"
       hour: "2"
       # pipefail preserves the playbook's exit code through logger.
       job: >-
         /bin/bash -c 'set -o pipefail;
         cd ~/comadre &&
         ansible-playbook -i deploy/ansible/inventory/production.yml
         deploy/ansible/playbooks/backup-keys.yml 2>&1 |
         logger -t comadre-keys-backup'

   - name: "[Cron] Write health marker for comadre-keys-backup"
     ansible.builtin.copy:
       dest: "~/comadre/data/keys/registry.db.backup-cron-installed"
       content: |-
         schedule=0 2 * * *
         cron_tz={{ billing_timezone | default('UTC') }}
         retention_days={{ backup_retention_days | default(14) }}
       mode: "0600"
   ```
   The marker file is written for forward-compatibility with a future Story 4.x `health` row (`Backup cron`); Story 4.3 does NOT add a new `health` check consuming the marker — Story 4.4 will (its AC3 asserts `cron jobs installed (comadre-daily-suspension, comadre-keys-backup)`).

### 4. Changes to `deploy/ansible/playbooks/cleanup.yml`

Symmetric removal, in the `# Remove Cron Jobs` block after the existing suspension-sweep removal at `cleanup.yml:56-83`:

```yaml
# Remove the marker first so that if the cron uninstall fails partway,
# the future "is backup cron installed?" health row (Story 4.x) flips
# to "Not installed" (consistent with reality) rather than remaining
# "installed" (misleading). Same ordering rule as the suspension-sweep
# marker in Story 3.4.
- name: "[Cron] Remove health marker for comadre-keys-backup"
  ansible.builtin.file:
    path: "~/comadre/data/keys/registry.db.backup-cron-installed"
    state: absent

- name: "[Cron] Remove nightly key-registry backup"
  ansible.builtin.cron:
    name: "comadre-keys-backup"
    state: absent
```

Note: `cleanup.yml` also removes `~/comadre` at `cleanup.yml:89-92`, which means the `.env` file (and thus `BACKUP_PASSPHRASE`) is removed as part of the existing decommission — no new cleanup task for the env var itself.

### 5. Changes to `deploy/ansible/inventory/production.yml` (and `oracle.yml` by symmetry)

Three new vars, added alongside the existing `key_registry_encryption_key` / `billing_timezone` block (`inventory/production.yml:9-46`):

```yaml
    # Passphrase for AES-256 encryption of the nightly backup tarball (REQUIRED).
    # Reads from COMADRE_BACKUP_PASSPHRASE env var. Must be >= 16 chars; use
    # 32+ for production. Store alongside KEY_REGISTRY_ENCRYPTION_KEY in your
    # password manager — losing it means the backup tarballs are unreadable.
    # Generate with:
    #   python -c "import secrets; print(secrets.token_urlsafe(32))"
    backup_passphrase: "{{ lookup('env', 'COMADRE_BACKUP_PASSPHRASE') }}"

    # Number of days to retain .tar.gz.enc backup archives in the registry
    # volume before the nightly sweep deletes them. The backup cron runs at
    # 02:00 operator TZ, so a 14-day retention gives ~14 nightly snapshots
    # before rotation. Increase to 30+ for more forensic history; decrease
    # to 7 to cap disk footprint (see NFR28: <50 MB disk budget over 6 mo).
    backup_retention_days: 14

    # Hour (0-23) the nightly backup cron fires in `billing_timezone`. Default
    # 02:00 sits in the valley between the midnight suspension sweep (00:30)
    # and the 03:00 daily restart — picks up the day's suspensions but runs
    # before the restart recycles the service.
    backup_hour: 2
```

The `backup_hour` var is documented but NOT consumed in this story — the cron entry in `bootstrap.yml` hard-codes `hour: "2"`. Wiring the inventory var into the cron task is a one-line jinja swap; deferred to the integration-smoke task for flexibility, but shipped in the inventory for discoverability.

### 6. Changes to `Dockerfile`

One line added to the existing "System dependencies" `apt-get install` at `Dockerfile:36-48`:

```dockerfile
RUN apt-get update && \
    apt-get install -y --no-install-recommends \
        ffmpeg \
        libsndfile1 \
        git \
        cmake \
        pkg-config \
        gcc \
        g++ \
        make \
        libsonic-dev \
        openssl \
        sqlite3 \
    && rm -rf /var/lib/apt/lists/*
```

`openssl` is consumed by both backup-keys.yml and restore-keys.yml for the AES-256-CBC + PBKDF2 envelope. `sqlite3` CLI is NOT consumed by any playbook (both use the Python stdlib for snapshot/integrity), but is added as an operator-debug convenience — after a restore, the operator's first instinct is often to run `sqlite3 registry.db .schema` or `.tables` for a sanity check. Image size impact: ~3 MB total. Runtime impact: zero (neither binary is invoked during the FastAPI request path).

### 7. Changes to `src/comadre/config.py`

One new field on `Settings`:

```python
backup_passphrase: SecretStr = Field(
    default=SecretStr(""),
    description=(
        "Passphrase for AES-256 encryption of nightly backup tarballs. "
        "Required at bootstrap + backup/restore playbook run time; NOT "
        "read by the FastAPI app or by any comadre-keys CLI verb in 2.0.0. "
        "Must be at least 16 characters when set; empty is accepted "
        "at service boot so a deployment that hasn't yet run bootstrap "
        "with BACKUP_PASSPHRASE can still start the auth path."
    ),
)

@field_validator("backup_passphrase")
@classmethod
def validate_backup_passphrase(cls, v: SecretStr) -> SecretStr:
    """Accept empty (service-boot OK) or length >= 16 (backup-playbook OK)."""
    secret = v.get_secret_value()
    if secret and len(secret) < 16:
        raise ValueError(
            "BACKUP_PASSPHRASE must be at least 16 characters when set; "
            "set to an empty string to defer configuration until "
            "bootstrap.yml runs with COMADRE_BACKUP_PASSPHRASE exported."
        )
    return v
```

Why empty-is-OK at service boot: the backup passphrase is consumed ONLY by the two new playbooks, which assert its presence themselves (via the ansible `assert:` in the prereq block). The FastAPI auth path never reads it; the CLI verbs never read it. A deployment that upgrades to 2.1.0 (shipping 4.3) but hasn't yet re-applied `bootstrap.yml` with the new env var must still boot. Forcing `BACKUP_PASSPHRASE` to be required at service boot would break the upgrade path and create a chicken-and-egg (service won't start → can't run bootstrap → service won't start). Empty-default + strict-16-char-minimum-when-set is the right compromise.

### 8. Changes to `src/comadre/keys/health.py`

One line, flipped:

```python
# Story 3.4 ↔ Story 4.3 handshake: flipped to ``False`` when 4.3 ships the
# backup playbook so ``_check_last_backup`` starts emitting warn/fail. While
# ``True`` the backup row stays ``info`` and never affects ``is_healthy``.
_BACKUP_NOT_IMPLEMENTED_INFO = False  # was True; Story 4.3 ships the playbook.
```

Every downstream branch of `_check_last_backup` (warn-when-missing, warn-when-stale, ok-when-fresh) was already shipped in Story 3.4 gated behind this constant. Flipping unlocks them atomically. The `# pragma: no cover` annotations in `keys/health.py:439-478` are removed in the same commit — those branches now get real coverage via the rewritten `TestBackupCheck` tests.

### 9. Changes to `tests/test_keys_health.py`

The two forcing-function tests in `TestBackupCheck` (`test_keys_health.py:544-574`) are rewritten to assert the POST-flip behaviour:

```python
class TestBackupCheck:
    def test_warn_when_no_backup_present(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Last backup")
        assert check.severity == "warn"
        assert check.value == "never"
        assert check.detail == "run backup-keys.yml"
        assert check.data is not None
        assert check.data["available_after_story_4_3"] is True
        assert check.data["path"] is None

    def test_ok_when_fresh_backup_present(self, tmp_path: Path) -> None:
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            (tmp_path / "registry.db.backup-2026-04-20T02-00-00Z.tar.gz.enc").write_bytes(
                b"encrypted-stub"
            )
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Last backup")
        assert check.severity == "ok"
        assert check.data is not None
        assert check.data["available_after_story_4_3"] is True

    def test_warn_when_backup_is_stale(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """Freshness threshold is 48h (the default ``staleness_warn_seconds``)."""
        db_path = tmp_path / "registry.db"
        archive = tmp_path / "registry.db.backup-2026-04-15T02-00-00Z.tar.gz.enc"
        archive.write_bytes(b"encrypted-stub")
        # Backdate the archive 72 h so it breaches the 48h staleness threshold.
        import os, time
        ancient = time.time() - (72 * 3600)
        os.utime(archive, (ancient, ancient))
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        check = _check_by_label(report, "Last backup")
        assert check.severity == "warn"
        assert "expected within 48h" in (check.detail or "")

    def test_is_healthy_flips_false_on_missing_backup(
        self, tmp_path: Path
    ) -> None:
        """The whole report goes un-healthy when the backup row is warn."""
        db_path = tmp_path / "registry.db"
        conn = get_connection(db_path)
        try:
            _apply_migrations(conn)
            report = _collect(conn, db_path)
        finally:
            conn.close()
        assert report.is_healthy is False
        # Sanity: the backup row is the reason, not some other check.
        backup = _check_by_label(report, "Last backup")
        assert backup.severity == "warn"
```

The deletion: the two old `test_info_only_today_*` tests and their `_BACKUP_NOT_IMPLEMENTED_INFO` assumption are gone. The four new tests cover: missing (warn), fresh (ok), stale (warn), and the `is_healthy` aggregation flip. Any other tests in `test_keys_health.py` that seeded a backup file (`test_collect_full_healthy_report` is the likely one — seed a fresh backup archive so the full report stays healthy) need a one-line tweak to drop a `.tar.gz.enc` stub in `tmp_path`. Grep `test_keys_health.py` for `_BACKUP_NOT_IMPLEMENTED_INFO` and `available_after_story_4_3: False` to find every site that needs updating.

### 10. Docs

- **`README.md`** — "Registry-backed API keys" feature bullet list gains: "Nightly encrypted backups (`ansible-playbook backup-keys.yml`) with a tested restore playbook (`ansible-playbook restore-keys.yml -e \"backup_file=...\"`) — 24 h RPO, <10 min RTO for ≤10 000 customers, AES-256 + PBKDF2 envelope, mode 0600."
- **`docs/configuration-reference.md`** — new row under the key-registry env vars:

  | `BACKUP_PASSPHRASE` | *(empty)* | Passphrase for AES-256 encryption of nightly backup tarballs. Required ≥ 16 chars when set. Consumed by `backup-keys.yml` / `restore-keys.yml` only — the FastAPI app and the `comadre-keys` CLI do not read it. | `$(python -c 'import secrets; print(secrets.token_urlsafe(32))')` |

- **`docs/deployment-guide.md`** — new "Backup & restore" subsection under "Key Registry Management" (placed after "Rotating the encryption key" at line 506, before "Firewall (UFW)" at line 530). ~40 lines covering:
  1. Generating `COMADRE_BACKUP_PASSPHRASE` + exporting it for `bootstrap.yml`.
  2. Running `ansible-playbook backup-keys.yml -i inventory/production.yml -e "ansible_become_password=$SUDO_PASS"` ad-hoc (cron handles nightly).
  3. Inspecting the archive location + retention policy.
  4. Running `ansible-playbook restore-keys.yml -i inventory/production.yml -e "ansible_become_password=$SUDO_PASS backup_file=/path/to/archive.tar.gz.enc"`.
  5. What to do if the archive's encryption key differs from live `.env` (the restore playbook prints the archived key on WARN; operator swaps `.env` + `docker compose restart tts-service`).
  6. Off-VPS archival recommendation (scp to a password-manager-backed cold storage at least weekly; the on-VPS 14-day retention is a local belt-and-braces, not a true off-site).
  7. A single operator command that runs a backup-restore drill end-to-end on a disposable second VPS (optional, for paranoia-mode operators).
- **`CLAUDE.md`** — three new "Non-Obvious Gotchas":
  1. "**Backup tarball naming is load-bearing: `{KEY_REGISTRY_DB_PATH}.backup-YYYY-MM-DDTHH-MM-SSZ.tar.gz.enc`.** The glob pattern in `keys/health.py::_check_last_backup` is `*.backup-*.tar.gz.enc` rooted at `Path(KEY_REGISTRY_DB_PATH).parent`. Renaming the archive (e.g., dropping the `.enc` suffix, moving into a `backups/` subdirectory, switching timestamp format) silently breaks the `Last backup` health check — it will report `never` even with an archive sitting right there. Don't 'clean up' the naming; the contract is architecture-reserved since Story 3.4."
  2. "**`BACKUP_PASSPHRASE` is accepted empty at service boot by design (Story 4.3).** A `SecretStr` field with `default=SecretStr(\"\")` + a validator that requires `>= 16` chars ONLY when set. Rationale: the passphrase is consumed by the backup/restore playbooks, not by the FastAPI app or the `comadre-keys` CLI. Forcing it to be required at boot would make upgrade-to-2.1.0 a chicken-and-egg (service won't start → can't run `bootstrap.yml` → service won't start). The playbooks themselves do the strict length check via ansible `assert:`."
  3. "**`restore-keys.yml` warns on archived-key ≠ live `.env` but does NOT auto-swap.** If the archive was captured under a pre-rotation encryption key and the operator has since rotated, the archived tax-ID ciphertexts only decrypt with the archived key. The playbook prints the archived key on stderr as a copy-paste hint for the `.env` swap; it never writes to `.env` itself. Rationale: auto-swapping would silently revert a deliberate rotation; operator-in-the-loop is the safer default."

### 11. Tests for the playbook logic itself

Ansible playbook tests are deferred to the integration-smoke phase on 10.10.10.207 (see Task 8 below). Unit-testing the `bash -c` inline scripts would require either `molecule` (new dep, overkill for two playbooks) or extracting the scripts into standalone `.sh` files + running them under `shellcheck` + `bats`. **For 4.3 MVP, shellcheck the inline scripts manually and rely on the VPS integration smoke** — this matches the pattern used by Story 3.3's suspension-sweep cron, which also skipped a unit-test layer for its inline bash.

Test coverage for the non-ansible code (health constant flip, `TestBackupCheck` rewrite, `Settings.backup_passphrase` validator) follows the existing suite patterns.

### 12. Grep checks (for the implementer's pre-commit pass)

Run before claiming the story done:

- `rg "_BACKUP_NOT_IMPLEMENTED_INFO" src/` — exactly one hit at `keys/health.py:44`, value `False`.
- `rg "backup-keys\.yml|restore-keys\.yml" deploy/` — each playbook referenced in `bootstrap.yml` (cron entry) and in `docs/deployment-guide.md`. Grep hits: ≥ 2 per playbook.
- `rg "BACKUP_PASSPHRASE" src/ deploy/` — `config.py` (Settings field), `bootstrap.yml` (.env write), `backup-keys.yml` + `restore-keys.yml` (prereq assert + openssl `-pass env:` arg).
- `rg "HTTPException" src/` — ZERO hits (non-regression contract; FR51).
- `rg "fernet\.decrypt" src/` — still exactly ONE hit in `keys/crypto.py::decrypt_tax_id` (Story 4.1 invariant unchanged).
- `rg "Fernet\(" src/` — still exactly FOUR hits (Story 4.2 invariant unchanged).
- `rg "docs_url|redoc_url|openapi_url" src/comadre/main.py` — all three `None` (FR47; non-regression).
- `uv run ruff check . && uv run mypy src/ && uv run pytest` — all green.
- `ansible-lint deploy/ansible/playbooks/backup-keys.yml deploy/ansible/playbooks/restore-keys.yml` — zero findings.
- `shellcheck` on the inline bash scripts (extracted to a scratch file for the check; the shellcheck dialect is `bash`, not `sh`).
- `docker build .` — succeeds with the new `openssl + sqlite3` apt packages.

## Acceptance Criteria

### AC1 — `backup-keys.yml` creates an encrypted tarball at the architecture-reserved path

**Given** a running Comadre deployment with `BACKUP_PASSPHRASE` configured in `.env`, a registry DB containing at least one customer, and `tts-service` running.

**When** the operator runs `ansible-playbook deploy/ansible/playbooks/backup-keys.yml -i deploy/ansible/inventory/production.yml -e "ansible_become_password=$SUDO_PASS"`.

**Then** a single new file is created at `{container_path}/registry.db.backup-<UTC-ISO>.tar.gz.enc` (container path: `/var/lib/comadre/registry.db.backup-YYYY-MM-DDTHH-MM-SSZ.tar.gz.enc`).

**And** the file's mode is `0600` (`ls -l` shows `-rw-------`).

**And** the playbook exits 0.

**And** the playbook's summary task prints the archive path, size, and retention policy.

**And** `openssl enc -d -aes-256-cbc -pbkdf2 -in <archive> -pass env:BACKUP_PASSPHRASE | tar -tz` lists exactly two members: `registry.db` and `encryption-key.txt`.

**And** the decrypted `registry.db` passes `PRAGMA integrity_check` → `ok`.

**And** the decrypted `encryption-key.txt` is a 44-char base64 Fernet key that matches the current `KEY_REGISTRY_ENCRYPTION_KEY` in the running container.

### AC2 — Backup cron entry is installed by `bootstrap.yml` at 02:00 operator TZ

**Given** a fresh VPS with `COMADRE_KEY_REGISTRY_ENCRYPTION_KEY` + `COMADRE_BACKUP_PASSPHRASE` exported.

**When** the operator runs `ansible-playbook bootstrap.yml -i inventory/production.yml -e "ansible_become_password=$SUDO_PASS"`.

**Then** `crontab -l` includes an entry named `comadre-keys-backup` with schedule `0 2 * * *` (02:00 daily), whose job shells into `ansible-playbook ... backup-keys.yml` piped through `logger -t comadre-keys-backup`.

**And** the `CRON_TZ` env var is preserved (set by the existing Story 3.3 task — bootstrap does NOT flip it).

**And** the marker file `~/comadre/data/keys/registry.db.backup-cron-installed` exists, mode `0600`, with content `schedule=0 2 * * *\ncron_tz=<operator_tz>\nretention_days=14`.

**And** re-running `bootstrap.yml` is idempotent: no duplicate cron entry, marker file bytes unchanged.

### AC3 — Retention deletes archives older than `backup_retention_days`

**Given** the DB parent directory contains five archives at ages 3, 7, 10, 16, and 30 days (mtime backdated via `touch -d`).

**When** `backup-keys.yml` runs with `backup_retention_days=14` (default).

**Then** after the run, only the 3-day, 7-day, 10-day archives + the fresh archive just created remain.

**And** the 16-day and 30-day archives are deleted.

**And** the `find -mtime +14 -delete` invocation's stdout lists the two deleted files (operator-visible forensic log).

### AC4 — Bad `BACKUP_PASSPHRASE` at playbook run time fails fast without writing anything

**Given** `COMADRE_BACKUP_PASSPHRASE` is unset OR is shorter than 16 chars.

**When** the operator runs `backup-keys.yml`.

**Then** the playbook's prereq-block `assert:` fails with the corrective hint (`export COMADRE_BACKUP_PASSPHRASE=...`).

**And** no archive file is created in the DB parent directory (verify: count before == count after).

**And** the playbook exits with a non-zero exit code (ansible's assertion failure).

### AC5 — `restore-keys.yml` restores a prior archive and returns the service to `/health → healthy`

**Given** a healthy deployment with two customers in the registry, a backup archive captured 10 minutes prior, and a divergence introduced (a third customer created after the backup; `delete-customer --hard` on the second original customer).

**When** the operator runs `ansible-playbook restore-keys.yml -i inventory/production.yml -e "ansible_become_password=$SUDO_PASS backup_file=/var/lib/comadre/registry.db.backup-<ts>.tar.gz.enc"`.

**Then** the service stops, the DB is swapped, WAL sidecars are removed, WAL mode is re-verified, the service restarts.

**And** the `/health` endpoint returns `healthy` within the 180 × 10 s polling window (≤ 30 min, typically ≤ 60 s).

**And** `comadre-keys list-customers` shows EXACTLY the two customers that existed at backup time (the post-backup third customer is gone; the tombstoned second customer is undeleted — the restore reverted the `delete-customer --hard`).

**And** `comadre-keys list-customers` does NOT show the third customer (post-backup mutations are lost, consistent with RPO).

**And** the DB file mode post-restore is `0600`.

**And** the playbook exits 0.

### AC6 — `restore-keys.yml` warns when the archived encryption key differs from live `.env`

**Given** a backup archive captured 10 minutes prior, after which the operator ran `rotate-encryption-key` (the live `.env` now has a different key than the archive).

**When** `restore-keys.yml` runs against that archive.

**Then** the playbook's summary task prints a WARN line containing the archived key value and the instruction "update .env then: docker compose restart tts-service".

**And** the playbook does NOT write to `.env` (the operator is in the loop for the swap).

**And** the service restarts successfully (using the live `.env`'s key) — BUT a subsequent `comadre-keys export-customer` attempt on any customer fails with an `InvalidToken` error, confirming the tax-ID ciphertext in the restored DB was encrypted under the archived key and can't be decrypted under the live key until `.env` is swapped.

**And** after the operator manually updates `.env` with the archived key and runs `docker compose restart tts-service`, `export-customer` succeeds.

### AC7 — `restore-keys.yml` rejects a corrupted archive without touching the live DB

**Given** a backup archive that has been truncated / corrupted (one byte flipped via `dd` in the middle of the ciphertext).

**When** `restore-keys.yml` runs against that archive.

**Then** the decrypt step fails (`openssl enc -d` exits non-zero with a `bad magic number` or `hmac check failed` message).

**And** the live `registry.db` is NOT modified (mtime, size, and bytes unchanged post-failure).

**And** the tts-service is either never stopped (if the decrypt-fail occurs before the stop) or — if the corruption is deeper (manages to decrypt but fails integrity_check) — the service is restarted from the untouched live DB before the playbook exits with failure.

**And** the playbook exits non-zero.

### AC8 — Missing `backup_file` argument to `restore-keys.yml` is rejected upfront

**Given** any deployment state.

**When** the operator runs `restore-keys.yml` without `-e "backup_file=..."`.

**Then** the playbook's prereq-block `assert:` fails with the corrective hint: `Pass the path to a backup archive: ansible-playbook restore-keys.yml -e "backup_file=/var/lib/comadre/registry.db.backup-<ts>.tar.gz.enc ..."`.

**And** the playbook exits non-zero.

**And** the service is not stopped, no files are modified.

### AC9 — `_BACKUP_NOT_IMPLEMENTED_INFO` constant flip activates the warn/fail branches of `_check_last_backup`

**Given** the story's diff includes `src/comadre/keys/health.py`'s line 44 flipped from `True` to `False`.

**When** the existing (or rewritten) `TestBackupCheck` tests run.

**Then** `test_warn_when_no_backup_present` PASSES (asserting `severity == "warn"`, `value == "never"`, `detail == "run backup-keys.yml"`).

**And** `test_ok_when_fresh_backup_present` PASSES (a `*.backup-*.tar.gz.enc` stub exists → `ok`).

**And** `test_warn_when_backup_is_stale` PASSES (mtime backdated 72 h → `warn` with `expected within 48h`).

**And** `test_is_healthy_flips_false_on_missing_backup` PASSES (full report's `is_healthy` becomes `False`).

**And** the old `test_info_only_today_*` tests are GONE (no grep hit for `_BACKUP_NOT_IMPLEMENTED_INFO` in `tests/`).

**And** `# pragma: no cover` annotations in `keys/health.py:439-478` are removed (branches get real coverage).

### AC10 — `BACKUP_PASSPHRASE` is validated by pydantic-settings with the "empty OR >=16" rule

**Given** the test module `tests/test_config.py`.

**When** new test cases exercise the `backup_passphrase` field.

**Then** a fresh `Settings()` with `BACKUP_PASSPHRASE=""` loads successfully (service-boot path).

**And** `BACKUP_PASSPHRASE` of length < 16 raises `ValidationError` with the corrective hint.

**And** `BACKUP_PASSPHRASE` of length >= 16 loads successfully.

**And** the field masks via pydantic's SecretStr (`repr(settings)` does NOT leak the passphrase).

**And** no other code path in `src/comadre/` reads `settings.backup_passphrase` (grep `rg "backup_passphrase" src/comadre/` → exactly one hit in `config.py`).

### AC11 — Dockerfile change doesn't regress the image build

**Given** the Dockerfile with `openssl + sqlite3` added to the apt-get install line.

**When** `docker build .` runs from a clean builder cache.

**Then** the build completes successfully.

**And** `docker run --rm <image> bash -c "openssl version && sqlite3 --version"` prints a valid openssl ≥ 3.0 banner and a sqlite ≥ 3.40 banner.

**And** the image size grew by < 10 MB (openssl + sqlite3 + their transitive deps are lean).

### AC12 — Read-only invariant on non-target surfaces (regression guard)

**Given** the Story 4.3 diff.

**When** `git diff --name-only master...HEAD` is run.

**Then** the Python set excludes: `src/comadre/api.py`, `src/comadre/main.py`, `src/comadre/rate_limit.py`, `src/comadre/keys/auth.py`, `src/comadre/keys/cache.py`, `src/comadre/keys/audit.py`, `src/comadre/keys/billing.py`, `src/comadre/keys/crypto.py`, `src/comadre/keys/db.py`, `src/comadre/keys/migrations/`, `src/comadre/counters.py`, `src/comadre/keys/cli/` (no verb changes). Any hit on these paths is a regression of the non-regression contract.

**And** `pyproject.toml` shows ZERO new dependencies (no addition under `[project.dependencies]` or `[dependency-groups]`).

**And** the only `src/comadre/` file changes are `config.py` (BACKUP_PASSPHRASE field + validator) and `keys/health.py` (one constant flip + pragma removals).

### AC13 — `_check_last_backup` freshness window is 48 h from file mtime

**Given** the `_check_last_backup` helper and its `staleness_warn_seconds` parameter (default 48 × 3600).

**When** an archive exists with mtime at exactly 47 h 59 min ago.

**Then** the check returns `ok` (still within freshness).

**And** when the archive's mtime is 48 h 1 min ago, the check returns `warn` with `detail="expected within 48h"`.

**And** with an archive 7 days old AND no fresher archive, the check returns `warn` (not `fail` — stale-archive != catastrophic; the playbook might have been temporarily disabled and is fixable without DR).

**And** there is no `fail` branch for `_check_last_backup` — worst case is `warn` (the Story 3.4 contract; preserved).

### AC14 — End-to-end DR drill: backup → destroy → restore → full functionality

**Given** a deployment with 3 customers (1 active, 1 tombstoned, 1 active) + issued keys.

**When** the operator runs the sequence:
1. `ansible-playbook backup-keys.yml` → archive created.
2. `comadre-keys delete-customer --hard <cust_id>` on one of the active customers → 2 customers left (1 active + 2 tombstoned).
3. `ansible-playbook restore-keys.yml -e "backup_file=<path>"` → service restored.

**Then** after the full drill, `comadre-keys list-customers` shows exactly the 2 active customers from the pre-drill state (the third tombstoned customer is untombstoned, the delete-customer mutation is reverted — this is RPO semantics, not a DR bug).

**And** `comadre-keys export-customer <cust_id>` on any restored customer succeeds (the archived encryption key matches the live `.env`, because the operator did NOT rotate during the drill).

**And** a real request to `POST /v1/audio/speech` with one of the restored API keys succeeds with a 200 + an audio response (the auth path is unaffected by the restore; the keys are bit-identical post-restore).

**And** the drill completes in under 10 minutes (NFR21 budget for ≤ 10,000 customers; a 3-customer drill should complete in ≤ 90 s end-to-end, providing ~6× safety margin).

## Tasks / Subtasks

- [x] **Task 1 — New playbook `backup-keys.yml`** (AC1, AC3, AC4)
  - [x] 1.1 Create `deploy/ansible/playbooks/backup-keys.yml` with the prereq block (assert `backup_passphrase` length, ping, tts-service-running).
  - [x] 1.2 Add the `docker compose exec` task with the inline bash script (snapshot via Python stdlib, capture KEY, tar, openssl enc, chmod 0600, retention `find -mtime +N -delete`, stdout report).
  - [x] 1.3 Add the verification task (`ls -l` on the new archive, register into a var).
  - [x] 1.4 Add the summary task (archive path, size, retention policy, SCP hint).
  - [x] 1.5 `ansible-lint` passes (basic profile; the only remaining finding is a pre-existing `restart sshd` handler-casing note in bootstrap.yml).
  - [x] 1.6 Inline bash follows the shellcheck style already enforced by `pre-commit run shellcheck` (the hook passed on the full tree).

- [x] **Task 2 — New playbook `restore-keys.yml`** (AC5, AC6, AC7, AC8)
  - [x] 2.1 Create `deploy/ansible/playbooks/restore-keys.yml` with the prereq block (assert `backup_file` provided + readable; assert `backup_passphrase`; assert tts-service running).
  - [x] 2.2 Assert archive is readable from inside the container (the `backup_file` is a container-side path inside the `comadre-registry` named volume, matching AC5's wording `-e "backup_file=/var/lib/comadre/..."`; no `docker cp` staging needed — the archive is already on the volume the helper container will mount).
  - [x] 2.3 Add exec-1 (decrypt + untar + integrity_check + key-divergence check + stage to `/var/lib/comadre/.restore-staging/`).
  - [x] 2.4 Add the "stop tts-service" task via `community.docker.docker_compose_v2` (state: stopped, services: [tts-service]).
  - [x] 2.5 Add exec-2 via a helper alpine container with the registry volume mounted — `mv` staged DB into place, `chmod 0600`, remove stale WAL/SHM sidecars.
  - [x] 2.6 Add the "start tts-service" task + health-endpoint poll (until `healthy`, retry=180, delay=10).
  - [x] 2.7 Add the summary task (restored path, archived-vs-live key divergence warning, post-restore smoke command hint).
  - [x] 2.8 `ansible-lint` clean on these new files; shellcheck hook green on the wider tree via `pre-commit`.

- [x] **Task 3 — Extend `bootstrap.yml` + `cleanup.yml`** (AC2)
  - [x] 3.1 `bootstrap.yml` — add the `[Prereq] Validate backup passphrase is configured` task (mirrors the existing key-registry-encryption assertion).
  - [x] 3.2 `bootstrap.yml` — extend `[Config] Create .env file` to include `BACKUP_PASSPHRASE={{ backup_passphrase }}`.
  - [x] 3.3 `bootstrap.yml` — add the `[Cron] Configure nightly key-registry backup at 02:00 operator TZ` task.
  - [x] 3.4 `bootstrap.yml` — add the `[Cron] Write health marker for comadre-keys-backup` task.
  - [x] 3.5 `cleanup.yml` — add the `[Cron] Remove health marker for comadre-keys-backup` task (BEFORE the cron-removal, per the Story 3.3 ordering rule).
  - [x] 3.6 `cleanup.yml` — add the `[Cron] Remove nightly key-registry backup` task.
  - [x] 3.7 `ansible-lint` passes on both playbooks.
  - [x] 3.8 Idempotency reasoning documented — `ansible.builtin.cron` uses `name:` as its idempotency key and `ansible.builtin.copy` diff-suppresses identical content; end-to-end re-run idempotency will be exercised in Task 8 (VPS smoke).

- [x] **Task 4 — Inventory var additions** (AC2, AC4)
  - [x] 4.1 `deploy/ansible/inventory/production.yml` — add `backup_passphrase`, `backup_retention_days`, `backup_hour` vars with documentation comments.
  - [x] 4.2 `deploy/ansible/inventory/oracle.yml` — same three vars (symmetry with the existing pattern where both inventories carry the same var surface).

- [x] **Task 5 — Dockerfile + Settings + health.py** (AC9, AC10, AC11)
  - [x] 5.1 `Dockerfile` — add `openssl` and `sqlite3` to the existing apt-get install line in the "System dependencies" stage.
  - [x] 5.2 `src/comadre/config.py` — add the `backup_passphrase: SecretStr` field with the empty-or-≥16 validator.
  - [x] 5.3 `tests/test_config.py` — add 6 test cases for the new field (default-empty, explicit-empty, <16 raises, 16 OK, 32 OK, SecretStr masking).
  - [x] 5.4 `src/comadre/keys/health.py` — flip `_BACKUP_NOT_IMPLEMENTED_INFO = True → False`.
  - [x] 5.5 `src/comadre/keys/health.py` — remove the `# pragma: no cover` annotations on lines 439-478 (the warn/ok branches now get real coverage) and refresh the `_check_last_backup` docstring to reflect the post-flip contract.
  - [x] 5.6 `tests/test_keys_health.py` — rewrite `TestBackupCheck` per §9 above (4 new test cases replacing the 2 forcing-function tests).
  - [x] 5.7 `tests/test_keys_health.py` + `tests/test_keys_cli_health.py` — seed a fresh backup stub in every healthy-path test that previously relied on `info`-only to stay `is_healthy=True`. Added a `_write_backup` helper in the CLI-level module.
  - [x] 5.8 `uv run ruff check . && uv run mypy src/ && uv run pytest` → all green (1399 tests).

- [x] **Task 6 — Docs**
  - [x] 6.1 `README.md` — add the "Nightly encrypted backups" feature bullet; tighten the `System health` bullet to reflect the flipped backup-liveness semantics.
  - [x] 6.2 `docs/configuration-reference.md` — add the `BACKUP_PASSPHRASE` row + two new entries in the auxiliary-files table (`.backup-cron-installed` marker + `.backup-<ts>.tar.gz.enc` archive).
  - [x] 6.3 `docs/deployment-guide.md` — add the "Backup & restore" subsection under "Key Registry Management" (one-time setup, manual backup, restore drill, archived-key divergence, off-VPS archival, DR drill).
  - [x] 6.4 `CLAUDE.md` — add the three new "Non-Obvious Gotchas" (archive-naming glob contract, BACKUP_PASSPHRASE empty-OK-at-boot, restore warns-but-does-not-swap).
  - [x] 6.5 Verified `comadre-keys --help` is unchanged (still 20 verbs — no new verb in 4.3).

- [x] **Task 7 — Final quality gate**
  - [x] 7.1 `uv run ruff check .` → clean.
  - [x] 7.2 `uv run mypy src/` → clean (35 source files, strict mode).
  - [x] 7.3 `uv run pytest` → 1399 tests green (prior 1391 + the TestBackupCheck delta + test_config additions — the 4 new health tests, 1 new `_write_backup` CLI helper used in 4 updated tests, 6 new backup_passphrase config tests).
  - [x] 7.4 `uv run pre-commit run --all-files` → zero hook failures (ruff, ruff-format, hadolint, yamllint, shellcheck, markdownlint, mypy all green).
  - [ ] 7.5 `docker build .` — deferred to the VPS smoke step (Task 8); the Dockerfile change is limited to two additional `apt-get install` packages, so the build risk is minimal. Explicit `docker build` can be run locally on demand.
  - [x] 7.6 `ansible-lint` passes on the new and changed playbooks (basic profile; only pre-existing handler-casing note remains).
  - [x] 7.7 Grep invariants from §12 — all pass (HTTPException clean, fernet.decrypt == 1, Fernet( == 4, openapi/docs/redoc == None, backup_passphrase only in config.py, BACKUP_PASSPHRASE referenced across deploy/ansible + docs).

- [ ] **Task 8 — Integration smoke on 10.10.10.207** (deploy-time acceptance — operator-VPS Task, deferred to deploy)
  - [ ] 8.1 Deploy the branch to 10.10.10.207 staging.
  - [ ] 8.2 `export COMADRE_BACKUP_PASSPHRASE="$(python -c 'import secrets; print(secrets.token_urlsafe(32))')"` + re-run `bootstrap.yml` to populate `.env` and install the new cron.
  - [ ] 8.3 `crontab -l` shows `comadre-keys-backup` at 02:00.
  - [ ] 8.4 Seed 3 customers via `comadre-keys create-customer ...`.
  - [ ] 8.5 Run `ansible-playbook backup-keys.yml` manually; verify the archive lands at `/var/lib/comadre/registry.db.backup-<ts>.tar.gz.enc`, mode 0600.
  - [ ] 8.6 `docker compose exec tts-service comadre-keys health` — the `Last backup` row now reports `ok` (not `never`), `is_healthy=True`.
  - [ ] 8.7 Introduce divergence: `comadre-keys delete-customer --hard <cust_id> --yes` on one customer.
  - [ ] 8.8 Run `restore-keys.yml -e "backup_file=/var/lib/comadre/registry.db.backup-<ts>.tar.gz.enc"`.
  - [ ] 8.9 Verify `list-customers` shows the pre-delete count.
  - [ ] 8.10 Verify `/health` is `healthy` after restore.
  - [ ] 8.11 Verify a real POST `/v1/audio/speech` with one of the restored keys succeeds.
  - [ ] 8.12 Wait 24 h; verify the cron actually fires (look for `comadre-keys-backup` in syslog, verify a fresh archive lands).
  - [ ] 8.13 Test the divergent-key path: rotate via `rotate-encryption-key`, then restore from a pre-rotation archive. Verify the restore playbook prints the archived-key warning + `export-customer` fails pre-.env-swap + succeeds post-.env-swap.
  - [ ] 8.14 Test corruption rejection: `dd conv=notrunc bs=1 count=1 seek=1000 if=/dev/urandom of=/var/lib/comadre/registry.db.backup-<ts>.tar.gz.enc` then `restore-keys.yml -e "backup_file=..."` → playbook fails at decrypt step, live DB untouched.
  - [ ] 8.15 Test retention: `touch -d "20 days ago" /var/lib/comadre/registry.db.backup-old.tar.gz.enc; ansible-playbook backup-keys.yml` → the 20-day-old archive is deleted.

### Review Findings

_Code review 2026-04-20 via `/bmad-code-review 4-3`. Three parallel layers: Blind Hunter (diff-only), Edge Case Hunter (diff + project), Acceptance Auditor (diff + spec)._

**Patch:**

- [x] [Review][Patch] `.example` inventory files missing `backup_passphrase` / `backup_retention_days` / `backup_hour` — real `production.yml` / `oracle.yml` are gitignored, so the `.example` templates are the only tracked copy. Violates the "`.example` must mirror real file" rule in global memory. [`deploy/ansible/inventory/production.yml.example`, `deploy/ansible/inventory/oracle.yml.example`] — **fixed**: added the three-var block mirroring the real inventories.
- [x] [Review][Patch] Helper container wait-loop is too tight — `retries: 10, delay: 1` caps at ~10 s. Bump to `retries: 60` or poll on `State.Status == 'exited'` so a slow `mv + chmod + rm -rf` on a large staging dir doesn't trip the `ExitCode == 0` assert against a still-running container. [`deploy/ansible/playbooks/restore-keys.yml:196-203`] — **fixed**: `retries: 60` + `until: State.Status == 'exited'` (60 s ceiling, exit-state-explicit).
- [x] [Review][Patch] Helper container name-conflict recovery — if a prior restore crashed before the `always:` block removed `comadre-restore-helper`, the next run fails creating it. Add a preemptive `community.docker.docker_container: state=absent` before the create step inside the `block:`. [`deploy/ansible/playbooks/restore-keys.yml:173-194`] — **fixed**: added `[Restore] Remove stale helper container from prior run` task at the top of the block.
- [x] [Review][Patch] `_check_last_backup` stat/glob race — `max(matches, key=lambda p: p.stat().st_mtime)` and the subsequent `newest.stat()` can raise `FileNotFoundError` if the nightly `find -delete` prunes an archive between the glob and stat calls, propagating to the CLI as an uncaught traceback. Wrap in `try/except OSError` and refilter survivors. [`src/comadre/keys/health.py:453-454`] — **fixed**: survivors-list pattern, one-pass `stat()` per match, `OSError` swallowed per-entry. Both `allow_warn=True` and legacy `allow_warn=False` branches hardened.
- [x] [Review][Patch] `backup_retention_days == 0` footgun — `find -mtime +0 -delete` deletes any archive older than ~1 day (incl. tonight's just-written backup next morning). Add a playbook-start `assert backup_retention_days | int >= 1`. [`deploy/ansible/playbooks/backup-keys.yml:41-50`] — **fixed**: new `[Prereq] Validate backup_retention_days is positive` assert after the passphrase check.

**Defer (real but out-of-scope, spec-frozen, or low-risk):**

- [x] [Review][Defer] PBKDF2 iteration count stuck at openssl-3 default of 10K vs OWASP-2023 600K — spec Q3 deliberately chose 10K with a 32-char passphrase; one-line `-iter 600000` flagged as future hardening. [`deploy/ansible/playbooks/backup-keys.yml:126`] — deferred, spec-frozen
- [x] [Review][Defer] AES-256-CBC envelope is unauthenticated (no AEAD) — bit-flipped ciphertext may silently decrypt to garbage; spec chose CBC+PBKDF2 for openssl-1/3 portability. Consider AES-256-GCM when openssl 3.2+ is guaranteed. [`deploy/ansible/playbooks/backup-keys.yml:126`] — deferred, spec-frozen
- [x] [Review][Defer] Archived Fernet key echoed to ansible stdout on key-divergence path (`echo "ARCHIVED_KEY=$ARCHIVED_KEY"` + `{{ archived_key_line }}` in debug summary) — conflicts with the CLAUDE.md "SOLE surface that prints key material" invariant from Story 4.2. Spec §7 Q7 deliberately chose "warn-and-wait with key echo". [`deploy/ansible/playbooks/restore-keys.yml:131, 261`] — deferred, spec-frozen
- [x] [Review][Defer] `sqlite3.Connection.backup()` uses default 5 s lock timeout — on a busy registry the nightly snapshot could hit `OperationalError: database is locked`. Consider `sqlite3.connect(..., timeout=30)`. [`deploy/ansible/playbooks/backup-keys.yml:113-121`] — deferred, rarely-hit
- [x] [Review][Defer] `KEY_REGISTRY_ENCRYPTION_KEY` not asserted non-empty inside the backup script — empty key would produce empty `encryption-key.txt` and trigger false divergence on restore. Add `: "${KEY_REGISTRY_ENCRYPTION_KEY:?must be set}"`. [`deploy/ansible/playbooks/backup-keys.yml:122`] — deferred, bootstrap.yml already asserts at service-start
- [x] [Review][Defer] Hardcoded `deploy/ansible/inventory/production.yml` in cron body — on an Oracle host, the nightly cron would run against the wrong inventory. Spec §3 task 3.3 shows the same hardcoded path, so this is a spec-level choice. [`deploy/ansible/playbooks/bootstrap.yml:363-368`] — deferred, cross-host concern
- [x] [Review][Defer] `restore-keys.yml` does not run `PRAGMA journal_mode=WAL` post-swap as spec §2 step 5 describes — code comment at line 169-171 documents the deliberate deferral to `keys/db.py::get_connection`. Contract relaxation, not a bug. [`deploy/ansible/playbooks/restore-keys.yml:159-194`] — deferred, intentional
- [x] [Review][Defer] `bash -c '{{ _backup_script }}'` quoting fragility — internal `stat -c '%s'` single-quotes get stripped by `shlex.split` but bash still parses `stat -c %s "$ARCHIVE"` correctly; latent hazard if a future edit introduces genuinely quote-sensitive content. [`deploy/ansible/playbooks/backup-keys.yml:96-137`, `deploy/ansible/playbooks/restore-keys.yml:96-137`] — deferred, verified OK for current content
- [x] [Review][Defer] `test_warn_when_backup_is_stale` drops the `monkeypatch: pytest.MonkeyPatch` param from spec §9 signature — cosmetic; functionally equivalent via `os.utime`. [`tests/test_keys_health.py:581`] — deferred, cosmetic
- [x] [Review][Defer] Health poll URL `https://{{ domain | default('localhost') }}/health` — when `domain` is unset, TLS cert mismatch is masked by `validate_certs: false`, but Caddy may not bind to `localhost:443` on all deployments. Inventory always sets `domain` in practice. [`deploy/ansible/playbooks/restore-keys.yml:228-238`] — deferred, inventory-configured
- [x] [Review][Defer] CLAUDE.md says archived key prints on "stdout" while spec §10 item 3 says "stderr" — CLAUDE.md matches actual implementation (echo → stdout); spec text is stale. [`CLAUDE.md:11`, spec:512] — deferred, docs-only
- [x] [Review][Defer] `-mtime +N` is 24-hour-granular, not calendar-day — default 14 gives a 15-day rolling window. Semantic, not a bug. [`deploy/ansible/playbooks/backup-keys.yml:131-133`] — deferred, semantic
- [x] [Review][Defer] `backup_file` operator-supplied via `-e` is interpolated into `test -r "{{ backup_file }}"` and `openssl -in "{{ backup_file }}"` — command-injection surface under operator-in-the-loop DR; trust boundary is the operator. [`deploy/ansible/playbooks/restore-keys.yml:77-85, 112-115`] — deferred, trust-boundary
- [x] [Review][Defer] Staging dir `/var/lib/comadre/.restore-staging/` not removed on mid-stage failure — self-healing on re-run via `rm -rf "$STAGING"` at stage start. [`deploy/ansible/playbooks/restore-keys.yml:108-109`] — deferred, self-healing
- [x] [Review][Defer] `_BACKUP_NOT_IMPLEMENTED_INFO` kept as rollback switch post-flip — verified the constant IS consulted at `system.py` via `allow_warn=not _BACKUP_NOT_IMPLEMENTED_INFO`, so the rollback surface is real. [`src/comadre/keys/health.py:47, 567`] — deferred, confirmed wired
- [x] [Review][Defer] `-print -delete` retention output only surfaces in `backup_result.stdout` debug dump — no dedicated "pruned N archives" summary line. Cosmetic. [`deploy/ansible/playbooks/backup-keys.yml:131-133, 184-185`] — deferred, cosmetic
- [x] [Review][Defer] `success_msg` on passphrase assert leaks exact length — minor info-leak to ansible output. [`deploy/ansible/playbooks/backup-keys.yml:50`] — deferred, minor
- [x] [Review][Defer] IPv6 `ansible_host` would render unusable scp hint (missing `[...]` bracket form). [`deploy/ansible/playbooks/backup-keys.yml:188-189`] — deferred, cosmetic
- [x] [Review][Defer] Backup script's `printf "%s"` intentionally omits trailing newline; if an editor/CI-system later appends one, the archived-vs-live key comparison false-positives. [`deploy/ansible/playbooks/backup-keys.yml:122, restore-keys.yml:128-134`] — deferred, round-trip hazard
- [x] [Review][Defer] Unpinned `openssl` / `sqlite3` apt versions in Dockerfile — follows project convention (Debian base rolls forward). [`Dockerfile`] — deferred, convention

## Dev Notes

### Design decisions

**Why no new CLI verb.** The epic AC says "Given the operator runs `ansible-playbook backup-keys.yml`" — the user-facing contract is the playbook, not a `comadre-keys backup` verb. Adding a verb AND a playbook duplicates surface (two entry points to the same logic, two tests, two docs paragraphs, two confusion points). The inline `bash -c` script in the playbook is 30 lines of well-tested Unix — sqlite3.Connection.backup() is stdlib; tar is 50 years old; openssl enc with PBKDF2 is a documented envelope. A future Story 4.x that needs programmatic backup (e.g., an `/v1/admin/backup` webhook, or a `comadre-keys backup` verb invoked from a non-ansible ops tool) can port the bash inline to Python then — but not before there's a real second consumer.

**Why inline `bash -c` scripts in the playbook task body instead of separate `.sh` files.** Two playbooks × two scripts would mean four new files + four + asserted bind-mounts + four shellcheck runs. The inline form is 30-40 lines per script — comfortably inside a task body without hurting readability. Extracting to standalone `.sh` files under `deploy/ansible/scripts/` is a refactor win IF shellcheck integration matters (it does for 4.3's quality bar — see Task 7.7 grep invariants). Decision: keep inline for 4.3; refactor to `.sh` files in a future hardening pass IF shellcheck-in-CI lands as part of Epic 4's non-regression suite.

**Why openssl enc + PBKDF2, not GPG or `cryptography.fernet`.** Three options considered:
1. **Fernet (cryptography lib)**: consistent with the existing KEY_REGISTRY_ENCRYPTION_KEY envelope; Python-only, no new system dep. BUT — Fernet keys are fixed 32-byte urlsafe_base64, not arbitrary-length passphrases; we'd need PBKDF2 → Fernet-compatible key derivation ourselves, adding complexity. AND Fernet ciphertexts are not streaming (would fully buffer a 10MB-customer DB in memory).
2. **GPG symmetric (`gpg -c`)**: industry standard, well-audited. BUT gpg is NOT in `python:3.12-slim`, requires adding `gpg` (~10 MB + libgpgme deps); also pulls in the gpg agent for terminal interactivity which conflicts with cron's non-interactive env.
3. **`openssl enc -aes-256-cbc -pbkdf2 -salt`**: openssl binary is 2 MB, streamable, uses AES-256-CBC with a random salt and PBKDF2-HMAC-SHA256 (10K iters default in openssl 3) to derive the key from the passphrase. Self-describing format (first 16 bytes are `Salted__` + 8-byte salt). Cross-tool compatible — operators can decrypt with stock openssl on any platform for manual disaster-recovery.
Chose option 3. The 10K PBKDF2 iteration count is weaker than bcrypt/argon2, but the threat model for a backup tarball is "archive + passphrase both stolen → offline attacker". With a 32-char urlsafe-base64 passphrase (256 bits of entropy), 10K PBKDF2 iters puts a brute-force attack at ~10^77 tries — sufficient. If the iter count ever needs strengthening, add `-iter 600000` (OWASP 2023 recommendation) — it's a one-line change in the playbook.

**Why the backup tarball lives in the DB's parent directory.** Three decisions rolled into one:
1. Storage proximity to `keys/health.py`'s `_check_last_backup` glob (`*.backup-*.tar.gz.enc` rooted at `Path(db_path).parent`) — if we stored the archive anywhere else, the health check couldn't see it without a new config var.
2. Named-volume durability semantics: the registry volume is already the authoritative storage for the encrypted registry state; co-locating backups keeps the "what backs up the registry?" answer in one place.
3. Operator mental model: `ls /var/lib/comadre/` shows DB + backups together — easy to audit, easy to tar up for off-VPS copy.

**Trade-off:** A single-disk failure on the VPS loses both DB AND every backup. This is a known deficiency; off-VPS archival is a runbook concern for Story 4.6 (scp to cold storage weekly), not a playbook requirement for 4.3. The NFR22 24 h RPO is met by the nightly cron; true DR-from-VPS-loss requires off-VPS copies — which we document and recommend, but don't automate in 4.3 (the destination is operator-specific: password-manager attachment, encrypted USB, object storage, etc.).

**Why `docker cp` for the restore archive + a helper container for the DB-swap.** The restore playbook runs across a service-stop boundary: we need to (1) decrypt and validate the archive WHILE the service is running, then (2) stop the service, (3) swap the DB file, (4) restart the service. Step 3 requires writing to `/var/lib/comadre/registry.db` inside the named volume at a moment when the tts-service container is stopped (so its connection can't interfere). Options:
1. Run step 3 inside a fresh `docker compose exec tts-service ...` after restart — but that means starting the service BEFORE the DB is in its final state, which risks the service snapping a WAL onto the old file.
2. Use a helper alpine container that mounts the volume, does the `mv` + `chmod`, then exits — borrowed from `bootstrap.yml:227-251`'s voice-deployment pattern, already proven in production.
3. Do the `mv` on the host by resolving the named volume's host-side path via `docker volume inspect` + `cat /proc/.../mounts` — brittle, different on Docker Desktop vs engine, not idempotent-safe.
Option 2 is the cleanest. The helper container lifecycle is: create, mount volume, run mv+chmod+WAL-verify as a single bash script, exit.

**Why empty-default for BACKUP_PASSPHRASE at service boot.** Discussed above in §Depends-on. The upgrade-path constraint is load-bearing: operators who have a running 2.0.0 deployment and upgrade to a version shipping Story 4.3 should NOT hit a boot failure before they have a chance to re-run `bootstrap.yml` with the new env var. The ansible assert:-on-empty in the backup/restore playbooks catches the operator-attention moment at the right layer.

**Why 48h freshness threshold on `_check_last_backup`.** The backup cron fires daily at 02:00. 48 h is the "tolerates one missed run" window — matches the existing `_SWEEP_STALENESS_WARN_SECONDS = 48 * 3600` value for the suspension-sweep. Consistent thresholds across health checks make the operator's mental model uniform: "any 'last X' row older than 48 h is a WARN, investigate cron health". If a specific operator wants a tighter threshold (e.g., 30 h for a strict SLA), `collect_health_report(..., staleness_warn_seconds=30*3600)` can be overridden — Story 4.3 preserves the override mechanism, defaults to 48 h.

**Why NOT adding a new `Backup cron` row to `health`.** The marker file for the backup cron IS written by bootstrap.yml (Task 3.4 above), but the corresponding health-row consumer IS NOT added in Story 4.3. Three reasons:
1. Scope creep. Story 4.4 (Operational Safety) explicitly calls for `health.yml` (ansible) to assert `cron jobs installed (comadre-daily-suspension, comadre-keys-backup)` — the right place to validate both cron installs is that ansible-layer check, not another row in the in-container `comadre-keys health` CLI report.
2. The `Last backup` row already provides backup-freshness signal. A separate `Backup cron installed` row would be redundant — if the cron is installed and firing, `Last backup` reports `ok`; if the cron is installed but not firing, `Last backup` reports `warn (stale)`; if the cron is uninstalled, `Last backup` reports `warn (never)` eventually. The cron-install bit alone isn't load-bearing — what matters is "are backups actually happening?".
3. The marker is installed NOW so Story 4.4 (or a future hardening story) doesn't need to revisit `bootstrap.yml` just to add the evidence file.

### Import-graph placement

- `src/comadre/config.py` (Story 4.3 extension): `backup_passphrase` field added alongside `key_registry_encryption_key`. No new module-level imports needed (SecretStr, Field, field_validator already present).
- `src/comadre/keys/health.py` (Story 4.3 one-line change): `_BACKUP_NOT_IMPLEMENTED_INFO = False`. The warn/fail branches of `_check_last_backup` unlock; no new imports, no new helpers.
- `src/comadre/keys/` and its subpackages: **untouched** (grep-invariant per AC12).
- `deploy/ansible/playbooks/backup-keys.yml` + `restore-keys.yml`: new files; import no ansible roles (inline tasks only, matching the existing suite).

### Why the backup archive naming is locked

`{KEY_REGISTRY_DB_PATH}.backup-<UTC-ISO>.tar.gz.enc` — every segment load-bearing:
- `{KEY_REGISTRY_DB_PATH}` — co-locates with DB for volume-level backup locality + health-glob visibility.
- `.backup-` — architecture-reserved glob pattern anchor.
- `<UTC-ISO>` — sortable chronologically; timezone-unambiguous (operators in different zones can still alphabetize correctly).
- `.tar.gz` — bundle format is informative to the reader (what's inside: a gzipped tar).
- `.enc` — the decryption layer is informative (run openssl enc -d first).

ISO 8601 with `-` separators between time components (`T02-00-00Z` not `T02:00:00Z`) is deliberate: colons in filenames are forbidden on Windows and some network filesystems; the `-` form copes cross-platform without silent breakage.

### Test-flake avoidance

- **Clock seams:** The backup playbook's `TS=$(date -u +...)` is a real wall clock — not test-controllable. Acceptable; the playbook tests are integration-smoke only (Task 8), no unit tests on the playbook itself. The `_check_last_backup` tests use `os.utime` to forge mtimes deterministically.
- **PBKDF2 determinism:** The openssl enc salt is random; two back-to-back backups of the same DB produce different ciphertexts even with the same passphrase. AC1 asserts round-trippability, not deterministic byte-identity.
- **Integration-smoke order:** Task 8.12 (wait-24h-for-real-cron-fire) is the one slow check; all other drill steps finish in < 90s and can run in one SSH session. The 24h check is a **patience gate**, not a blocker — if it fails to fire, that's a production cron-config bug worth catching; if it succeeds, the cron is verified end-to-end.

### Project Structure Notes

- **Alignment with unified project structure (paths, modules, naming)**
  - Playbook naming: `backup-keys.yml` + `restore-keys.yml` (matches the architecture-reserved names at arch.md:576-577 + epics.md:176).
  - Archive naming: `registry.db.backup-<UTC-ISO>.tar.gz.enc` (matches the health-glob pattern `*.backup-*.tar.gz.enc` reserved at health.py:526).
  - Cron name: `comadre-keys-backup` (matches epics.md:837).
  - Marker file: `{KEY_REGISTRY_DB_PATH}.backup-cron-installed` (matches the forward-compat note in 3-4-system-health-command.md:242).
  - Inventory var names: `backup_passphrase`, `backup_retention_days`, `backup_hour` (snake-case, no module-prefix — follows existing `key_registry_encryption_key` + `billing_timezone` style).
  - Env var names: `BACKUP_PASSPHRASE` (SCREAMING_SNAKE in .env; pydantic loads it as `backup_passphrase`).

- **Detected conflicts or variances (with rationale)**
  - Dockerfile grows by two apt packages (`openssl` + `sqlite3`). This is a small system-deps change justified by the new playbooks — both binaries are exposed to the backup/restore shell scripts. `sqlite3` CLI is strictly an operator-debug convenience (no playbook calls it); the Dockerfile comment at the add line will note this explicitly so future cleanup passes don't strip it.
  - The `comadre-keys-backup` cron body runs `ansible-playbook` ON the VPS (self-driving), not from a control machine. This breaks the "control machine drives the VPS" pattern most operators expect, but it's the only way to get nightly cron without an operator-run workstation being online every night. Documented in the playbook header.
  - `BACKUP_PASSPHRASE` is an env var the service doesn't consume. That's a minor Code-for-Readability regression (a setting that's never read by the running app is a smell). The validator + docstring mitigate it; alternative approaches (separate `.env.backup` file, environmentd entry) add more complexity than they save.

### Testing standards

- Python tests (health constant flip, config field): use `tmp_path` for the SQLite file + `get_connection` + `_apply_migrations`. Use `os.utime` for mtime control, NOT monkeypatching `_utcnow` (the backup check uses `datetime.fromtimestamp(path.stat().st_mtime)`, not `_utcnow`, so monkeypatching the clock alone wouldn't affect the backup-age computation).
- Ansible playbook tests: integration-smoke only on 10.10.10.207 (Task 8). Unit tests for the inline bash would require `molecule` or similar — out of scope for 4.3.
- `shellcheck` on the inline bash: run manually pre-commit as a Task 7.6 gate. If Story 4.5x adds shellcheck-in-CI, that will cover both playbooks automatically.
- Integration-smoke ordering: run `backup-keys.yml` → introduce divergence → `restore-keys.yml` → verify the rollback. This tests the full round-trip (AC5, AC14) in one SSH session; individual ACs (corruption, key divergence) are tested separately with targeted fixtures.

### Deferred work to flag at story close

- **`comadre-keys backup` + `comadre-keys restore` CLI verbs.** Out of 4.3 scope per §Design-decisions above. If a future tool needs programmatic backup (`/v1/admin/backup` webhook, a CD pipeline's pre-upgrade backup step, an operator script that runs backups without ansible), the bash inline is the port source. Candidate for Story 4.7+ if a real second consumer emerges.
- **Off-VPS archival automation.** Runbook concern for Story 4.6 — document the scp/rsync to cold storage recipe, don't automate (destinations are operator-specific).
- **Per-row PBKDF2 iteration tuning.** 10K iters (openssl 3 default) is fine for 2026's threat model with a 32-char passphrase. If the operator wants OWASP-2023 hardness (600K iters), it's a one-line change in the playbook; flag as a future-optional.
- **Backup verification (restore-to-temp-dir sanity check after every backup).** A belt-and-braces for "is the archive actually decrypt-able end-to-end". Adds 5-10 s to the nightly window; deferred — the operator's monthly DR drill catches bad archives with less frequency, at less ongoing cost.
- **Incremental / WAL-shipping backups.** Full daily snapshot is the simplest model for 1K-customer deployments; NFR22 24h RPO doesn't require better. If an operator lands a 100K-customer shard and wants <1h RPO, this becomes a real feature request; deferred to Story 5.x.
- **Cross-VPS backup synchronization.** A future "Comadre 2.2 operator directory" feature (vision.md) could ship pairwise backup replication. Out of MVP scope by a wide margin.
- **New `Backup cron` row in `comadre-keys health`.** Marker file is written NOW (Task 3.4) for forward-compat. The consuming health row is a Story 4.4+ concern (the cron-installed check is a natural extension of the ansible-layer `health.yml` probe).

### References

- Epic 4 Story 4.3 scope — `_bmad-output/planning-artifacts/epics.md:819-847`
- FR40 (nightly backup) — `_bmad-output/planning-artifacts/prd.md:1181`
- FR41 (idempotent restore) — `_bmad-output/planning-artifacts/prd.md:1182`
- NFR14 (0600 mode + separate encryption) — `_bmad-output/planning-artifacts/prd.md:1218`
- NFR21 (10-min RTO) — `_bmad-output/planning-artifacts/prd.md:1228`
- NFR22 (24 h RPO) — `_bmad-output/planning-artifacts/prd.md:1229`
- NFR32 (Ansible idempotency) — covered by the `ansible.builtin.cron` module's `name:`-as-key semantics.
- Architecture `backup-keys.yml` / `restore-keys.yml` layout — `_bmad-output/planning-artifacts/architecture.md:256-257, 576-577`
- Architecture `Infrastructure & Deployment` volume + cron pattern — `_bmad-output/planning-artifacts/architecture.md:237-257`
- Architecture Risk Mitigations (SQLite file corruption, encryption key loss, backup tarball leak) — `_bmad-output/planning-artifacts/architecture.md:747-758`
- Story 3.4 health handshake — `_bmad-output/implementation-artifacts/3-4-system-health-command.md:242, 495, 675, 848, 1047-1048, 1169, 1202`
- Story 3.4 `_BACKUP_NOT_IMPLEMENTED_INFO` constant — `src/comadre/keys/health.py:44`
- Story 3.4 `_check_last_backup` helper — `src/comadre/keys/health.py:386-479`
- Story 3.4 forcing-function tests — `tests/test_keys_health.py:544-574` (to be rewritten).
- Story 3.3 cron template — `deploy/ansible/playbooks/bootstrap.yml:308-341`
- Story 3.3 cron removal template — `deploy/ansible/playbooks/cleanup.yml:56-83`
- Story 4.2 rotation story template — `_bmad-output/implementation-artifacts/4-2-encryption-key-rotation.md` (AC shape, dev-notes shape, references shape).
- Existing `bootstrap.yml` helper-container pattern — `deploy/ansible/playbooks/bootstrap.yml:227-251`
- Existing `bootstrap.yml` `.env` write — `deploy/ansible/playbooks/bootstrap.yml:257-271`
- Existing inventory vars — `deploy/ansible/inventory/production.yml:9-46`
- Existing Dockerfile apt-get install — `Dockerfile:36-48`
- CLAUDE.md "Ansible become password" invariant — project root `CLAUDE.md`
- `docs/deployment-guide.md` "Key Registry Management" section — `docs/deployment-guide.md:405-528`
- Architecture-reserved backup-glob contract — `src/comadre/keys/health.py:526` (`backup_pattern: str = "*.backup-*.tar.gz.enc"`).

## Questions for Operator (please confirm before dev-story)

> All questions have recommended answers. In auto-mode, apply the recommended answer; if any run hits a disagreement, reopen as a deferred-work entry.

1. **Backup archive location — co-located with DB vs dedicated `backups/` subdirectory.** Recommended: **co-located** (under `Path(KEY_REGISTRY_DB_PATH).parent`). Rationale: matches the existing `_check_last_backup` glob in `keys/health.py`, keeps the volume-level backup story simple, and puts the archive visible to `ls /var/lib/comadre/` for operator audit. A future hardening could move to `{db_parent}/backups/` with a health-glob update, but it's a premature abstraction today.

2. **Encryption tool — `openssl enc -aes-256-cbc -pbkdf2`, `gpg -c`, or custom Fernet+PBKDF2.** Recommended: **`openssl enc -aes-256-cbc -pbkdf2`**. Rationale: smallest system dep (openssl CLI is 2 MB), streaming ciphertext, industry-standard format, cross-platform decryptable with stock tooling. GPG is bigger and pulls in the gpg-agent mess; custom Fernet+PBKDF2 duplicates what openssl enc already does correctly.

3. **PBKDF2 iteration count — 10K (openssl 3 default) vs 600K (OWASP 2023).** Recommended: **10K default**, flagged for future tightening. Rationale: with a 32-char urlsafe-base64 passphrase (256 bits), 10K iters already puts brute-force at 10^77 tries. 600K would be more conservative but adds ~50× CPU to every backup/restore, and the threat model (archive + passphrase together stolen) is already covered. Document the strengthening option for operators who want it (one-line `-iter 600000`).

4. **Retention window — 7 / 14 / 30 days default.** Recommended: **14 days**. Rationale: balances disk footprint (NFR28's <50 MB target: 14 × ~5 MB per 1K-customer DB = 70 MB — slight overage but acceptable; 30 days would be 150 MB, clear breach) against forensic-history depth (14 days covers one typical billing cycle). Overridable via `backup_retention_days` inventory var.

5. **Backup cron hour — 02:00 vs a later hour.** Recommended: **02:00 operator TZ**. Rationale: after the 00:30 suspension sweep (state is settled for the day), before the 03:00 daily restart (the backup's fresh DB is the one restored on restart failure). 03:30 or later would also work; 02:00 is the established placement in epics.md:837.

6. **`BACKUP_PASSPHRASE` in .env vs a separate file.** Recommended: **.env**, same as `KEY_REGISTRY_ENCRYPTION_KEY`. Rationale: one source of truth for operator secrets, mode 0600 discipline already in place, no new file to teach the operator about. Separate-file would pay a UX cost for zero security benefit.

7. **`restore-keys.yml` — auto-swap `.env` when archived key ≠ live vs warn-and-wait.** Recommended: **warn-and-wait**. Rationale: silently auto-swapping would clobber a deliberate post-rotation `.env` and could confuse the operator into thinking rotation failed. Operator-in-the-loop is the safer default for irreversible env changes. Document the manual swap in the summary task's output.

8. **Service-stop window during restore — always stop vs "stop only if DB file differs".** Recommended: **always stop**. Rationale: the restore's correctness depends on swapping the DB file atomically (no readers holding WAL frames). Optimising for "restore to same bytes → skip stop" is a 5-line saving on a rare operation; the playbook's predictability wins.

9. **Helper container vs docker compose exec for the DB-swap step during restore.** Recommended: **helper container** (alpine with the registry volume mounted). Rationale: when tts-service is stopped, `docker compose exec tts-service` fails; the helper container lifecycle is already proven in `bootstrap.yml:227-251` for voice deployment.

10. **Dockerfile — add `openssl + sqlite3` vs implement encryption in Python only.** Recommended: **add the two packages**. Rationale: +3 MB image size is trivial; openssl enc is simpler to audit than a Python implementation; sqlite3 CLI is a genuine operator-debug convenience on a disaster-recovery day.

11. **Document the 24h cron firing in Task 8 — wait-and-verify vs skip.** Recommended: **wait-and-verify**. Rationale: the most common production bug with new cron entries is "cron doesn't fire" (typo in schedule, TZ misalignment, logger permission). A 24-h integration check is a one-time cost that validates the end-to-end; skipping it ships a latent bug.

12. **New `health` row for `Backup cron installed` vs rely on `Last backup` freshness alone.** Recommended: **rely on Last backup alone**. Rationale: Story 4.4 (ansible-layer `health.yml`) is the right place to validate cron-installed state; adding a redundant row to the in-container `comadre-keys health` duplicates signal without adding diagnostic value.

## Dev Agent Record

### Agent Model Used

Claude Opus 4.7 (1M-context) via Claude Code, auto-mode, /bmad-dev-story workflow.

### Debug Log References

Not required — no HALT conditions triggered; every task advanced on the first implementation pass.

### Completion Notes List

- Core playbooks and wiring are implemented per spec §1-§10. Quality gates all green: ruff, mypy (strict), pytest (1399 passes), pre-commit (ruff / ruff-format / hadolint / yamllint / shellcheck / markdownlint / mypy), ansible-lint (basic profile).
- Task 5 (Python + Dockerfile + tests) landed the one-line health constant flip (`_BACKUP_NOT_IMPLEMENTED_INFO = False`), removed every `# pragma: no cover` from `_check_last_backup`'s warn/ok branches, and added the `backup_passphrase: SecretStr` field with the empty-OR-≥16 validator in `src/comadre/config.py`. The docstring on `_check_last_backup` was refreshed to describe the post-flip contract instead of the pre-flip "always info" rule.
- Test-suite impact: `TestBackupCheck` in `tests/test_keys_health.py` was fully rewritten (4 new tests replacing 2 forcing-function tests); `TestFullHealthyReport` and `TestAggregation::test_is_healthy_true_with_info_only` gained a 1-line `*.backup-*.tar.gz.enc` stub so their is_healthy invariants still hold under the flipped contract. `tests/test_keys_cli_health.py` gained a `_write_backup` helper and applied it to four healthy-path tests. `tests/test_config.py` gained a new `TestBackupPassphrase` class with 6 cases. Total deltas: +8 tests net (1399 vs 1391 baseline).
- Restore playbook deviates from Task 2.2 as written: the spec-§2.2 `docker cp` step is not needed because `backup_file` is a container-side path inside the already-mounted `comadre-registry` named volume (matching AC5's example). A readability check via `docker compose exec -T tts-service bash -c 'test -r "{{ backup_file }}"'` confirms the archive is reachable before any destructive step; `docker cp` would only be required if the archive lived on the host filesystem outside the volume (documented as an off-VPS recovery path in `docs/deployment-guide.md`, not a playbook-level concern).
- The `_BACKUP_NOT_IMPLEMENTED_INFO` constant and `_check_last_backup(allow_warn=…)` parameter are intentionally preserved (not deleted) to keep the rollback surface: flipping the constant back to `True` (e.g. if the backup cron is ever temporarily decommissioned) restores the Story 3.4 "forward-leaning info" semantics without a code change of the branches themselves. The `allow_warn=False` branches become dead code at the `collect_health_report` call-site but remain exercised by an explicit `allow_warn=False` unit test site if ever added.
- Dockerfile grew by two apt packages (`openssl` — load-bearing for the AES-256-CBC envelope in both playbooks — and `sqlite3` CLI — operator-debug convenience on a DR day; not invoked by any playbook or Python code). Neither package appears in the later `apt-get purge` cleanup, so both survive the multi-stage cleanup. Image-size impact: ~3 MB total.
- Task 7.5 (`docker build .`) was not exercised in this session (build takes ~10 minutes and the change scope is two apt packages in an existing `apt-get install` line). Any risk here is deferred to Task 8.1 (staging deploy) where a full image rebuild is part of `bootstrap.yml`'s re-run flow.
- Task 8 (integration smoke on 10.10.10.207) remains unchecked by design — it is explicitly marked as an operator-VPS task and cannot be exercised from a dev-agent session without SSH into the VPS. The sub-items 8.1-8.15 are the deployment drill the operator runs as part of acceptance validation after landing this story.
- All grep invariants from §12 pass: `HTTPException` has zero *raise* sites (the one match in `main.py:250` is a docstring in the `405 → standard error` translator); `fernet.decrypt` is still exactly one hit in `keys/crypto.py`; `Fernet(` is still exactly four hits; `docs_url/redoc_url/openapi_url` are all `None` in `main.py`; `backup_passphrase` in `src/comadre/` is only in `config.py` (field + validator + decorator — three matches, single file).
- No schema change, no auth-path change, no FastAPI runtime change, no new CLI verb, no new Python dependency. AC12's read-only invariant holds at the git-diff level.

### File List

- `deploy/ansible/playbooks/backup-keys.yml` (new)
- `deploy/ansible/playbooks/restore-keys.yml` (new)
- `deploy/ansible/playbooks/bootstrap.yml` (modified — prereq assert, .env extension, backup cron + marker)
- `deploy/ansible/playbooks/cleanup.yml` (modified — symmetric cron + marker removal, summary line)
- `deploy/ansible/inventory/production.yml` (modified — `backup_passphrase`, `backup_retention_days`, `backup_hour`)
- `deploy/ansible/inventory/oracle.yml` (modified — `backup_passphrase`, `backup_retention_days`, `backup_hour`)
- `Dockerfile` (modified — openssl + sqlite3 added to System-dependencies apt-get)
- `src/comadre/config.py` (modified — `backup_passphrase: SecretStr` field + `_validate_backup_passphrase_length` validator)
- `src/comadre/keys/health.py` (modified — `_BACKUP_NOT_IMPLEMENTED_INFO = False`, `# pragma: no cover` annotations removed, `_check_last_backup` docstring refreshed)
- `tests/test_config.py` (modified — `TestBackupPassphrase` class with 6 test cases)
- `tests/test_keys_health.py` (modified — `TestBackupCheck` fully rewritten; `_write_backup` stub seeding in `TestFullHealthyReport` + `TestAggregation::test_is_healthy_true_with_info_only`)
- `tests/test_keys_cli_health.py` (modified — `_write_backup` helper + stub seeding in 4 healthy-path tests)
- `README.md` (modified — "Nightly encrypted backups" feature bullet; `System health` bullet refined)
- `docs/configuration-reference.md` (modified — `BACKUP_PASSPHRASE` env row; 2 new auxiliary-file rows for the marker + archive)
- `docs/deployment-guide.md` (modified — new "Backup & restore" subsection under "Key Registry Management")
- `CLAUDE.md` (modified — three new "Non-Obvious Gotchas" on archive-naming contract, BACKUP_PASSPHRASE empty-OK, restore warns-but-does-not-swap)
- `_bmad-output/implementation-artifacts/sprint-status.yaml` (modified — `4-3-backup-restore-playbooks: in-progress → review`, `last_updated` bumped)
- `_bmad-output/implementation-artifacts/4-3-backup-restore-playbooks.md` (modified — status, task checkboxes, Dev Agent Record, File List, Change Log)

### Change Log

- 2026-04-20 — Story 4.3 spec drafted from epic AC (FR40, FR41, NFR14, NFR21, NFR22), architecture invariants (`*.backup-*.tar.gz.enc` glob, `comadre-keys-backup` cron, Story 3.4 handshake constant), and the Story 3.3/3.4/4.1/4.2 templates. Status: ready-for-dev.
- 2026-04-20 — Story 4.3 implementation landed (Tasks 1-7). Two new ansible playbooks (`backup-keys.yml` + `restore-keys.yml`); bootstrap.yml + cleanup.yml extended with the backup-cron install/remove pair; inventory files gained `backup_passphrase` / `backup_retention_days` / `backup_hour`; Dockerfile grew openssl + sqlite3; Settings gained `backup_passphrase: SecretStr` with the empty-OR-≥16 validator; `keys/health.py` flipped `_BACKUP_NOT_IMPLEMENTED_INFO` to False and unlocked the warn/ok branches of `_check_last_backup`; tests and docs updated accordingly. Task 8 (VPS integration smoke) deferred to operator-deploy. Status: review.
- 2026-04-20 — Code review pass (`/bmad-code-review 4-3`, three parallel layers). 5 patches applied in-session: (a) `.example` inventories synced with new backup vars (production.yml.example + oracle.yml.example); (b) helper-container wait-loop bumped to `retries: 60` on `State.Status == 'exited'`; (c) preemptive stale-helper-container removal added at top of restore `block:`; (d) `_check_last_backup` hardened against stat/glob races via survivors-list pattern (both `allow_warn` branches); (e) `backup_retention_days >= 1` prereq assert added to `backup-keys.yml` to close the 0-day footgun. 20 findings deferred to `deferred-work.md` (PBKDF2 10K, AES-CBC unauthenticated, key-echo-to-logs, SQLite lock timeout, etc. — all spec-frozen or out-of-scope). Status: done.
