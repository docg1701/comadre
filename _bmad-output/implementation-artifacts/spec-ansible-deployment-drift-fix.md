---
title: 'Ansible Deployment Drift Fix — Post Story 5.1 Audit'
type: 'bugfix'
created: '2026-04-25'
status: 'done'
baseline_commit: 'eb6e1cad6ea47c6b18bba1fbb62c4427c7a4265c'
context:
  - '{project-root}/CLAUDE.md'
  - '{project-root}/compose.yaml'
  - '{project-root}/src/comadre/config.py'
  - '{project-root}/src/comadre/keys/health.py'
  - '{project-root}/src/comadre/keys/cli/commands/system.py'
---

<frozen-after-approval reason="human-owned intent — do not modify unless human renegotiates">

## Intent

**Problem:** A full Ansible audit (post Story 5.1) found 8 defects: three production-critical (broken cron markers, broken backups, broken billing-timezone propagation) plus five smaller drift items. All trace back to the migration from a `./data/keys` bind-mount to the `comadre-registry` named volume, plus accumulated changes in `comadre-keys` CLI verbs and `.env` schema that the playbooks never absorbed.

**Approach:** A single coherent Ansible-correctness pass: write cron markers from inside the container into the named volume, pass `BACKUP_PASSPHRASE` per-invocation via `docker compose exec -e`, propagate `BILLING_TIMEZONE` into `.env`, fix the wrong `register-customer`/`issue-key` example, and resync `.env.example` + minor cron/recreate cleanups. No new design work — every change closes a documented contract that is already in code, CLAUDE.md, or the inventory comments.

## Boundaries & Constraints

**Always:**
- Write cron markers inside the container at `/var/lib/comadre/{registry.db.cron-installed,registry.db.backup-cron-installed}` so they live in the same named volume the in-container CLI reads from. Use `docker compose exec -T tts-service` with heredoc/`tee`. Mode 0600.
- `BACKUP_PASSPHRASE` is passed via `-e BACKUP_PASSPHRASE={{ backup_passphrase }}` on every `docker compose exec` invocation that runs `backup-keys.sh` or `restore-stage.sh`. It MUST NOT be added to `compose.yaml`'s `environment:` block — that contradicts CLAUDE.md's "consumed by playbooks, not by the FastAPI app or any CLI verb" rationale.
- `BILLING_TIMEZONE={{ billing_timezone | default('UTC') }}` is written into the `.env` content block in `bootstrap.yml`, AND added to `.env.example` so `update.yml`'s `.env`-sync absorbs it on existing hosts.
- `.env.example` mirrors what `bootstrap.yml` writes (operator memory rule: "example files must always mirror the real file structure").
- All fixes are idempotent — re-running `bootstrap.yml`, `update.yml`, `cleanup.yml` produces the same end state.

**Ask First:**
- (none — operator already decided: remove the daily-restart cron entirely; the memory-leak rationale is obsolete)

**Never:**
- Don't add `BACKUP_PASSPHRASE` to `compose.yaml`'s `environment:` block.
- Don't add an `env_file:` directive to `compose.yaml` — that would leak `KEY_REGISTRY_ENCRYPTION_KEY` and other secrets to every container env automatically and break the explicit-allowlist contract.
- Don't introduce a `./data/keys:/var/lib/comadre` bind mount — the named volume is the correct design (Story 4.4); just fix the marker writer.
- Don't change CLI verb semantics, health-endpoint shape, or `comadre-keys health` JSON contract — this is a deployment-layer fix only.

## I/O & Edge-Case Matrix

| Scenario | Input / State | Expected Output / Behavior | Error Handling |
|----------|--------------|---------------------------|----------------|
| Fresh bootstrap on Ubuntu VPS | `inventory/production.yml` with `billing_timezone: America/Sao_Paulo`, valid keys/passphrase | Service healthy; `comadre-keys health --format json` reports `is_healthy=true`; `Cron` and `Backup cron` rows render `installed`; container env contains `BILLING_TIMEZONE=America/Sao_Paulo` | Existing `assert` blocks still gate prerequisites |
| Nightly backup cron fires (02:00 op TZ) | `BACKUP_PASSPHRASE` set in inventory; service running | New `*.backup-*.tar.gz.enc` archive in `/var/lib/comadre`, mode 0600; `find -mtime +N -delete` prunes old | Script exits non-zero if passphrase missing; cron pipefail surfaces to logger |
| `restore-keys.yml` with archived key ≠ live key | `-e backup_file=...` valid archive | Stage script decrypts, integrity-checks DB, prints `KEY_DIVERGES` + `ARCHIVED_KEY=...`; service restarts healthy | Operator informed via summary; `.env` not auto-modified |
| `health.yml` after fresh bootstrap | All assertions in scope | All asserts pass including `is_healthy=true` from `comadre-keys health --format json` | Each assert carries actionable `fail_msg` |
| `update.yml` on host where `.env` predates this fix | Existing host, `.env` lacks `BILLING_TIMEZONE` | `[Config] Add missing env vars` task adds it from `.env.example`; `recreate: always` picks up the new env | Reports added vars in stdout |
| `cleanup.yml` full decommission | Bootstrapped host | All markers + crons + container + volumes removed; UFW reset; Docker uninstalled | `failed_when: false` on already-absent paths preserves idempotency |

</frozen-after-approval>

## Code Map

- `deploy/ansible/playbooks/bootstrap.yml` -- markers (lines 400-438), `.env` write (268-283), `register-customer`/`issue-key` summary (480-483), caddy `recreate: auto` (294), daily-restart cron (354-359)
- `deploy/ansible/playbooks/cleanup.yml` -- marker removal paths (71, 84) — must mirror bootstrap's new in-container write path
- `deploy/ansible/playbooks/backup-keys.yml` -- `docker compose exec` invocation (117-123) — needs `-e BACKUP_PASSPHRASE`
- `deploy/ansible/playbooks/restore-keys.yml` -- two `docker compose exec` invocations (88, 112) — both need `-e BACKUP_PASSPHRASE`
- `deploy/ansible/inventory/production.yml`, `production.yml.example`, `oracle.yml`, `oracle.yml.example` -- delete unused `restart_hour` (was only consumed by the now-deleted daily-restart cron); examples must mirror real inventory shape
- `compose.yaml` -- DO NOT add `BACKUP_PASSPHRASE`; add `BILLING_TIMEZONE: "${BILLING_TIMEZONE:-UTC}"` to `tts-service.environment` so the var written in `.env` actually reaches the container
- `.env.example` -- add `BACKUP_PASSPHRASE=` and `BILLING_TIMEZONE=UTC` to mirror what bootstrap writes
- `src/comadre/keys/cli/commands/system.py:400` (read-only reference) -- `cron_marker_path = f"{db_path}.cron-installed"` is the contract bootstrap must satisfy

## Tasks & Acceptance

**Execution:**
- [x] `compose.yaml` -- add `BILLING_TIMEZONE: "${BILLING_TIMEZONE:-UTC}"` to `tts-service.environment` block — without this, `.env` writes alone never reach the container
- [x] `.env.example` -- append `BILLING_TIMEZONE=UTC` (with explanatory comment matching `inventory/production.yml.example`) and `BACKUP_PASSPHRASE=` (with the same generation hint as inventory) — operator memory rule: examples mirror real file
- [x] `deploy/ansible/playbooks/bootstrap.yml` -- (a) add `BILLING_TIMEZONE={{ billing_timezone | default('UTC') }}` to the `.env` content block; (b) replace both `[Cron] Write health marker for ...` tasks with `docker compose exec -T tts-service bash -c 'cat > /var/lib/comadre/registry.db.cron-installed && chmod 600 ...'` (and `.backup-cron-installed`) — marker content piped via stdin; (c) fix summary to use `comadre-keys create-customer` and add `--price 149.00` to the `issue-key` example; (d) change `recreate: auto` → `recreate: always` so caddy reloads when Caddyfile-no-landing is swapped on rerun; (e) delete the `[Cron] Configure daily restart` task entirely (memory-leak rationale is obsolete) AND drop the `restart_hour` line from the summary block. `cleanup.yml`'s existing `[Cron] Remove daily restart cron` task STAYS — it removes the cron entry from any host crontab that still carries it from a previous bootstrap (the cron itself is host-side state, not playbook code).
- [x] `deploy/ansible/inventory/production.yml`, `production.yml.example`, `oracle.yml`, `oracle.yml.example` -- delete the `restart_hour` variable + its surrounding comment lines from all four files (now unreferenced)
- [x] `deploy/ansible/playbooks/cleanup.yml` -- replace the two `ansible.builtin.file:` marker removal tasks with `docker compose exec -T tts-service rm -f /var/lib/comadre/registry.db.cron-installed /var/lib/comadre/registry.db.backup-cron-installed` (still gated on container existence, `failed_when: false`)
- [x] `deploy/ansible/playbooks/backup-keys.yml` -- in the "[Backup] Snapshot + encrypt + prune" task add `-e BACKUP_PASSPHRASE={{ backup_passphrase }}` alongside the existing `-e BACKUP_RETENTION_DAYS`
- [x] `deploy/ansible/playbooks/restore-keys.yml` -- in both `docker compose exec` invocations (`[Prereq] Verify backup archive is readable` and `[Stage] Decrypt + untar + integrity-check`), add `-e BACKUP_PASSPHRASE={{ backup_passphrase }}`
- [~] Manual smoke test on `10.10.10.207` (Proxmox dev VPS) — operator-side, deferred: run `update.yml` → `comadre-keys health --format json` reports `is_healthy=true`, run `backup-keys.yml` → fresh archive lands in `/var/lib/comadre`, run `health.yml` → all assertions pass. Cannot be validated from the dev workstation alone; happens at deploy time.

**Acceptance Criteria:**
- Given a fresh `bootstrap.yml` run on a clean Ubuntu VPS, when `health.yml` is invoked, then every assertion passes — including `is_healthy=true` reported by `comadre-keys health --format json` (proves cron markers landed in the right place AND `BILLING_TIMEZONE` reached the container).
- Given a host where `bootstrap.yml` already ran (markers in old wrong location, no `BILLING_TIMEZONE` in `.env`), when `update.yml` is run after this fix, then on the next service restart `BILLING_TIMEZONE` is in the container env, the markers are recreated in `/var/lib/comadre/`, and `comadre-keys health` reports the cron rows as installed.
- Given `BACKUP_PASSPHRASE` set in inventory, when the nightly backup cron fires (or `backup-keys.yml` is invoked manually), then a `registry.db.backup-<UTC-ISO>.tar.gz.enc` archive is created at mode 0600 inside `/var/lib/comadre/`. (Negative test: with passphrase removed from inventory, the playbook prereq assert fails before any container exec runs.)
- Given a backup archive captured under one encryption key, when `restore-keys.yml -e backup_file=... -e ansible_become_password=...` is run with `BACKUP_PASSPHRASE` matching the archive's, then the stage script decrypts successfully, divergence detection prints `KEY_DIVERGES`/`KEY_MATCHES` correctly, and the service restarts healthy.
- Given the bootstrap summary block, when an operator copy-pastes the `comadre-keys ... issue-key` example, then the command succeeds — i.e. the verb is `create-customer` (not `register-customer`) and the `issue-key` example includes `--price`.

## Review Findings

Three adversarial reviewers ran against the diff at the end of step-03.

**Acceptance auditor — PASS.** All ACs structurally satisfied; AC1/AC2 are runtime-gated and unverifiable from diff alone. Flagged: `docs/deployment-guide.md` still referenced `restart_hour` → patched in the same pass (lines 49, 76, 139, 223, 690-705).

**Blind hunter — 9 findings, 2 actionable patches.** Real: `BACKUP_PASSPHRASE` interpolated into `-e VAR=value` lands in `/proc/<pid>/cmdline` → patched both `backup-keys.yml` + `restore-keys.yml` to use `-e BACKUP_PASSPHRASE` (no value) + ansible-task `environment:` block so the passphrase rides through the docker CLI's process env, never argv. Also patched: `--price 149.00` example clarified with `# BRL/month` comment. Other 7 findings either contradicted by code the reviewer couldn't see (cleanup ordering, container-readiness wait, legacy-cron removal) or trade-offs already accepted by the spec.

**Edge case hunter — 11 findings (1 self-retracted), 3 actionable patches.** Real:
- EH#1/#11 (cmdline leak) — patched as above (already covered by the blind-hunter patch).
- EH#5: stale "03:00 daily restart" comments in 3 inventory files → rewritten to standalone justification of `backup_hour: 2`.
- EH#9: `cat > file && chmod 600` non-atomic; window where umask-default permissions apply → switched to `set -e; umask 077; cat > file; chmod 600 file` so the marker creates at 0600 atomically and a partial write aborts before chmod claims success.
- EH#12: `recreate: always` comment falsely cited Caddyfile bind-mount as the rationale; bind-mount content changes don't bump compose's config hash either way → comment rewritten to cite the real reason (`.env` value deltas don't bump the hash and need explicit recreate).
- Cascade cleanups in same pass: `docs/rate-limiting.md:112`, `docs/replica-scaling-report.md:184,225`, `_bmad-output/project-context.md:102`, `_bmad-output/planning-artifacts/architecture.md:248`.

**Dismissed (noise / accepted trade-off):**
- EH#2 (recreate kills in-flight requests) — bootstrap is an explicit operator op, equivalent to `update.yml`'s deploy cycle; trade-off accepted.
- EH#3 (marker write races recreate) — guarded by the `[FS] Wait for service lifespan to materialise registry.db` task; the marker only writes after the new container's lifespan opened a real DB connection.
- EH#4 (`failed_when: false` masks volume-removal failures) — cleanup.yml is best-effort by design across the whole playbook.
- EH#6 (cleanup summary still names `daily-restart`) — still accurate for legacy hosts; the cleanup task itself is preserved (per spec).
- EH#7 (chmod runs as container UID) — not a regression vs. previous host-side path.
- EH#8 (BILLING_TIMEZONE whitespace asymmetry) — `config.py:127` IANA validator fail-fast at boot if `.env` is malformed; cron-side bootstrap-time variable is normalized by ansible.
- EH#10 — reviewer self-retracted on second pass.

## Design Notes

**Marker write pattern (chosen approach):**
```yaml
- name: "[Cron] Write health marker for comadre-daily-suspension"
  ansible.builtin.shell:
    cmd: >-
      docker compose exec -T tts-service bash -c
      'cat > /var/lib/comadre/registry.db.cron-installed && chmod 600 /var/lib/comadre/registry.db.cron-installed'
    chdir: "~/comadre"
    stdin: |
      schedule=30 0 * * *
      cron_tz={{ billing_timezone | default('UTC') }}
  changed_when: true
```
Rationale: `tee` would also work, but `cat >` keeps the chmod and the write atomic in one `bash -c` so a crashed write never leaves a 0644 marker behind. The named-volume mount means the marker survives container restarts and is visible to every replica.

**Why not `env_file:` in compose.yaml:** would auto-leak `KEY_REGISTRY_ENCRYPTION_KEY` and the (planned) `BACKUP_PASSPHRASE` into the container's process env, defeating CLAUDE.md's "Fernet decrypt happens only in `crypto.py`" + "BACKUP_PASSPHRASE consumed only by playbooks" invariants. Explicit allowlist in `environment:` is the deliberate boundary.

**Daily-restart cron decision:** removed entirely. Original memory-leak rationale is obsolete; `restart: unless-stopped` + healthcheck cover transient failures. The unused `restart_hour` inventory variable is deleted from all four inventory files (`production.yml{,.example}`, `oracle.yml{,.example}`) — no dead code, no downgrade-safety hedging.

## Verification

**Commands:**
- `cd ~/comadre && uv run ansible-lint deploy/ansible/playbooks/*.yml` -- expected: zero errors (warnings acceptable on existing patterns)
- `ansible-playbook -i deploy/ansible/inventory/production.yml deploy/ansible/playbooks/update.yml -e "ansible_become_password=$ANSIBLE_BECOME_PASS"` -- expected: success, no `[Health]` retry exhaustion
- `ssh galvani@10.10.10.207 'cd ~/comadre && docker compose exec tts-service comadre-keys health --format json' | jq .is_healthy` -- expected: `true`
- `ssh galvani@10.10.10.207 'cd ~/comadre && docker compose exec tts-service env | grep -E "^(BILLING_TIMEZONE|KEY_REGISTRY_ENCRYPTION_KEY)="'` -- expected: both present, `BILLING_TIMEZONE` matches inventory
- `ansible-playbook -i deploy/ansible/inventory/production.yml deploy/ansible/playbooks/backup-keys.yml -e "ansible_become_password=$ANSIBLE_BECOME_PASS"` -- expected: archive listed in summary, `[Verify] Confirm archive is mode 0600` passes
- `ansible-playbook -i deploy/ansible/inventory/production.yml deploy/ansible/playbooks/health.yml` -- expected: all assertions pass; ansible exit code 0

**Manual checks:**
- After bootstrap rerun with `landing_enabled: false`, browse `https://10.10.10.207/` — expect API-only Caddyfile served (404 on `/`, not the landing page) — confirms `recreate: always` reloaded caddy
- After successful backup, `ssh ... 'docker compose exec tts-service ls -la /var/lib/comadre/*.backup-*.tar.gz.enc'` — confirm exactly one new archive, mode `-rw-------`

## Suggested Review Order

**Plumbing the BILLING_TIMEZONE channel (entry point)**

- The `.env` channel: bootstrap writes it, compose forwards it, app validates it.
  [`compose.yaml:43`](../../compose.yaml#L43)
- Mirror in the .env.example so `update.yml`'s sync absorbs it on existing hosts.
  [`.env.example:30`](../../.env.example#L30)
- Bootstrap writes `BILLING_TIMEZONE` to `.env` so docker-compose substitution has a value.
  [`bootstrap.yml:275`](../../deploy/ansible/playbooks/bootstrap.yml#L275)

**Marker files now land in the named volume (the actual bug fix)**

- Suspension-sweep marker via `docker compose exec`, atomic 0600 via `umask 077`.
  [`bootstrap.yml:415`](../../deploy/ansible/playbooks/bootstrap.yml#L415)
- Backup-cron marker — same in-container atomic-0600 contract.
  [`bootstrap.yml:455`](../../deploy/ansible/playbooks/bootstrap.yml#L455)
- Cleanup no longer scrubs phantom host-side paths; volume teardown handles it.
  [`cleanup.yml:66`](../../deploy/ansible/playbooks/cleanup.yml#L66)

**`BACKUP_PASSPHRASE` reaches the script without leaking via /proc/cmdline**

- Forwarding pattern: `-e BACKUP_PASSPHRASE` (no value) + ansible task `environment:`.
  [`backup-keys.yml:131`](../../deploy/ansible/playbooks/backup-keys.yml#L131)
- Same pattern on the restore side; `BACKUP_FILE` stays inline (path, not secret).
  [`restore-keys.yml:115`](../../deploy/ansible/playbooks/restore-keys.yml#L115)

**`recreate: always` so .env edits actually take effect**

- Comment cites the real reason (compose config-hash insensitivity to .env value deltas).
  [`bootstrap.yml:289`](../../deploy/ansible/playbooks/bootstrap.yml#L289)

**CLI verb + price example fix**

- Operator-facing summary uses the verb that actually exists.
  [`bootstrap.yml:495`](../../deploy/ansible/playbooks/bootstrap.yml#L495)

**Deadcode removal — `restart_hour` / daily-restart cron**

- Inventory examples — variable removed and the obsolete "03:00 daily restart" comment in `backup_hour`'s justification rewritten.
  [`production.yml.example:30`](../../deploy/ansible/inventory/production.yml.example#L30)
  [`oracle.yml.example:31`](../../deploy/ansible/inventory/oracle.yml.example#L31)
- Bootstrap deletes the no-op `comadre-daily-restart` cron entirely.
  [`bootstrap.yml:354`](../../deploy/ansible/playbooks/bootstrap.yml#L354)
- Cleanup retains `[Cron] Remove daily restart cron` to scrub legacy hosts.
  [`cleanup.yml:56`](../../deploy/ansible/playbooks/cleanup.yml#L56)

**Doc cascade**

- Deployment guide: inventory example, variables table, bootstrap-step list, health-output list, and the deleted "Daily Restart" section replaced with a "Cron Jobs" overview.
  [`deployment-guide.md:48`](../../docs/deployment-guide.md#L48)
- Rate-limiting and replica-scaling docs no longer cite the daily-restart cron.
  [`rate-limiting.md:112`](../../docs/rate-limiting.md#L112)
  [`replica-scaling-report.md:184`](../../docs/replica-scaling-report.md#L184)
- BMAD project-context and architecture refreshed.
  [`project-context.md:101`](../../_bmad-output/project-context.md#L101)
  [`architecture.md:248`](../../_bmad-output/planning-artifacts/architecture.md#L248)

### Review Findings

Independent review pass (2026-04-25) — three parallel reviewers (blind hunter, edge-case hunter, acceptance auditor) ran against the working-tree diff. Auditor verdict: **CONDITIONAL PASS → PASS after follow-up patches.** Every Tasks/AC structurally satisfied; AC1/AC2/AC3 runtime-gated and pending the deferred 10.10.10.207 smoke test. Operator policy "no defer, no legacy" applied: every actionable finding patched in the same pass; remainder dismissed as noise (no defer bucket).

- [x] [Review][Patch] Parameterize `key_registry_db_path` as a play-level ansible var so marker paths and chmod targets derive from one source of truth [`bootstrap.yml`] — added `vars: key_registry_db_path: /var/lib/comadre/registry.db`; replaced 7 hardcoded literals (.env write, `[FS] Wait`, both `[FS] Enforce 0600`, the parent-dir chmod via `| dirname`, both marker writes) with `{{ key_registry_db_path }}` / `{{ key_registry_db_path }}.cron-installed` / `{{ key_registry_db_path }}.backup-cron-installed`. Honours the CLAUDE.md contract that operators MAY override `KEY_REGISTRY_DB_PATH` and re-run bootstrap.
- [x] [Review][Patch] Scrub legacy `~/comadre/data/keys/` host directory left over from pre-volume-migration bootstraps [`bootstrap.yml`] — added `[Migrate] Scrub legacy host-side key registry directory` task between `[Git] Clone` and `[Caddy]`. Idempotent `state: absent`; on a fresh host it is a no-op, on a legacy host it scrubs the orphan markers and DB copies that were unreachable from inside the container.
- [x] [Review][Patch] Cleanup-section cron list updated [`docs/deployment-guide.md:269`] — replaced `Cron jobs (daily-restart, audio-cleanup)` with the current cron set (`comadre-audio-cleanup`, `comadre-daily-suspension`, `comadre-keys-backup`, `CRON_TZ` envvar; legacy `comadre-daily-restart` scrubbed if present).
- [x] [Review][Patch] "four user-level cron entries" miscount fixed [`docs/deployment-guide.md:690`] — re-phrased as "three user-level cron jobs and a `CRON_TZ` envvar" (the fourth bullet was the envvar, not a cron job).

**Dismissed (20 findings):** all design choices already documented in the spec's earlier Review Findings section, reviewer self-retractions, or refuted by code outside the diff. Spot-verified during triage: `CRON_TZ` wired to `billing_timezone` at `bootstrap.yml:374`; `issue-key --price` exists at `keys.py:183`; `cleanup.yml:34-37` does set `remove_volumes: true`; the `[FS] Wait for service lifespan to materialise registry.db` poll absorbs the `recreate: always` race; `BACKUP_PASSPHRASE` prereq assert at `bootstrap.yml:59` enforces non-empty before the `.env` write. Additionally re-classified from defer to dismiss per "no defer" policy: marker `changed_when: true` is honest (markers genuinely re-write each run on operator-controlled values); `no_log: true` swallowing stderr is the correct security trade-off (debug story is via `backup-keys.sh` running outside ansible); the `-vvvv` `environment:` leak claim is a hypothetical ansible-version regression with no evidence in current versions.

#### Pass 2 — verification of pass-1 patches

Re-ran the same three reviewers against the pass-1 follow-up patches. Acceptance auditor: **PASS**. Blind hunter and edge-case hunter together surfaced **6 actionable items** that close the parameterization loop pass-1 opened (the `key_registry_db_path` ansible var was bootstrap-only; `compose.yaml` and `health.yml` ignored it, so an operator override silently failed to propagate). All applied in this same pass per the operator's "no defer" policy.

- [x] [Review][Patch] `key_registry_db_path` lifted to inventory `vars:` block — true single source of truth [`production.yml.example`, `oracle.yml.example`, `bootstrap.yml`] — moved the var declaration out of `bootstrap.yml`'s play-local `vars:` and into the inventory `all.vars` block (alongside `key_registry_encryption_key`, `backup_passphrase`, `backup_retention_days`, `backup_hour`); `bootstrap.yml` consumes it via the standard inventory injection path. Both `production.yml.example` and `oracle.yml.example` updated with the same comment block. Resolves EH-P2-1 (`update.yml` had no view of the var).
- [x] [Review][Patch] `compose.yaml` honours `KEY_REGISTRY_DB_PATH` env override [`compose.yaml:42`] — replaced the hardcoded value with `${KEY_REGISTRY_DB_PATH:-/var/lib/comadre/registry.db}` substitution, matching the surrounding `BILLING_TIMEZONE` / `OPERATOR_CONTACT_HINT` / `DEFAULT_VOICE` pattern. Without this, the `.env` line `bootstrap.yml` writes was decorative — compose ignored it. Resolves EH-P2-7.
- [x] [Review][Patch] `health.yml` parameterized end-to-end [`health.yml:135-260`] — five hardcoded path literals replaced across `[FS] Stat DB file mode`, `[FS] Assert DB file mode`, `[FS] Stat DB parent directory mode`, `[FS] Assert DB parent dir mode`, `[Backup] Count backup archives`, `[Backup] Smallest archive size`, `[Backup] Assert no archive is 0-byte` — all derive from `{{ key_registry_db_path }}` / `{{ key_registry_db_path | dirname }}`. ansible-lint passes the `production` profile. Resolves EH-P2-8.
- [x] [Review][Patch] Pre-flight assert against catastrophic `dirname` paths [`bootstrap.yml`] — new `[Prereq] Validate key_registry_db_path` asserts the value is defined, absolute, has a non-root parent (`| dirname != '/'`), and ends in a filename. Closes the `chmod 700 /` foot-gun the parameterization opened. Resolves EH-P2-6.
- [x] [Review][Patch] `[Migrate]` task documented in deployment-guide.md "What it does:" list [`docs/deployment-guide.md:131`] — added step 7 "Scrubs any legacy `~/comadre/data/keys/` directory left over from pre-volume-migration bootstraps (idempotent on fresh hosts)"; renumbered subsequent steps. Resolves EH-P2-3.
- [x] [Review][Patch] Marker-write comments corrected [`bootstrap.yml`] — dropped the inaccurate "atomically" claim from both marker comments; clarified that `umask 077` covers fresh creates while `chmod 600` is required (not optional) for re-bootstraps because `cat >` truncates an existing file in place and preserves its prior mode. Resolves BH-P2-1.

**Pass-2 dismissed (10 findings):** `recreate: always` memory cost and idempotency UX are accepted spec trade-offs (recurring complaint, recurring answer); operator help-text using `docker compose exec` without `-T` is correct for interactive use; argv vs `/proc/<pid>/environ` quibble misreads the threat model (ansible's `no_log: true` is the actual mitigation, the `environment:` keyword pattern is defense-in-depth against argv-scrapers specifically); existing `backup-keys.yml:44` and `restore-keys.yml:51` already assert `backup_passphrase | length >= 16`, so the "Jinja undefined inside `no_log`" claim is moot; the `[Migrate]` legacy DB scrub is the *intent*, not a bug (operator policy: no legacy debris); `docs/configuration-reference.md:10` already shows the production path in the Example column; cleanup `remove_volumes: true` verified; cron-list parenthetical creep is cosmetic; three independent UTC defaults all agree by construction; EH-P2-4 (misleading "mirrors config.py default" comment) became moot when the `vars:` block itself was removed in patch 1.

**Final verdict:** PASS. End-to-end parameterization holds (`compose.yaml:42` ↔ `bootstrap.yml` ↔ `health.yml` ↔ inventory `vars:` ↔ runtime `.env`); ansible-lint passes the `production` profile on `health.yml`; only pre-existing `name[casing]` violation on `bootstrap.yml`'s `restart sshd` task name (untouched by this pass) remains.
