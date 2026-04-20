# Story 4.4: Operational Safety & File Permissions

Status: done

> **Scope note — FR42, FR44, FR52.** Closes the "operational safety" loop opened by Stories 1.1 (DB-mode discipline at `keys/db.py`), 2.1 (per-replica auth cache), 3.3 (suspension-sweep cron), 3.4 (in-container `comadre-keys health`), and 4.3 (backup playbook + cron + marker). Story 4.4 ships TWO complementary surfaces:
>
> 1. **Belt-and-braces enforcement at bootstrap time** — `bootstrap.yml` gains an explicit ansible-layer chmod pass (after `docker compose up`) that asserts mode `0600` on `/var/lib/comadre/registry.db` and mode `0700` on its parent. The Python connection layer already does this on first open (`keys/db.py::_chmod_0600` + `get_connection` parent-mkdir at mode 0700) — the new ansible step is **redundant by design** so the playbook is self-evidently AC-fulfilling and operators reading `bootstrap.yml` can trace FR42/NFR13 to a single named task without reading Python.
>
> 2. **`health.yml` flips from "diagnostic debug-printer" to "assertion playbook with non-zero exit on deviation" (FR52)** — today's `health.yml` only emits `ansible.builtin.debug` WARN lines and always exits 0. Story 4.4 rewrites it as a chain of `ansible.builtin.assert:` tasks that fail fast on: DB file mode != 0600, parent dir mode != 0700, missing `comadre-daily-suspension` cron, missing `comadre-keys-backup` cron, missing `*.backup-*.tar.gz.enc` artefact, UFW rules drifted from exactly `22/tcp + 80/tcp + 443/tcp ALLOW`. Each assertion carries a corrective hint. The playbook ALSO delegates DB-state probes to `docker compose exec tts-service comadre-keys health --format json` — the in-container CLI is the single source of truth for schema version, customer/key counts, sweep freshness, cache state, last-backup freshness; the ansible layer asserts on its exit code and re-emits its checks list. The CLI's exit-7-on-unhealthy contract (Story 3.4) is the bridge.
>
> Story 4.4 ALSO adds the long-deferred `Backup cron` row to the in-container `comadre-keys health` CLI, consuming the `registry.db.backup-cron-installed` marker that Story 4.3 wrote at bootstrap as forward-compat. This closes the "we wrote a marker that nobody reads" debt and gives the CLI a separate, fail-fast signal for "is the backup cron installed?" alongside the existing "Last backup" freshness row. **No schema change. No auth-path change. No FastAPI runtime change. No new CLI verb.** Implementation is overwhelmingly ansible + a one-function addition to `keys/health.py` (`_check_backup_cron_marker`) modelled on the existing `_check_cron_marker`.

## Story

As an operator,
I want the deployment to enforce filesystem permissions on the key registry, validate that every operational invariant (DB mode, parent dir mode, both crons installed, recent backup, UFW unchanged) holds via a single `ansible-playbook health.yml` invocation that exits non-zero on any deviation, and trust that adding replicas via `compose.yaml`'s `deploy.replicas` doesn't corrupt the shared SQLite file or cross-pollinate auth caches,
so that I can integrate `health.yml` into a monitoring / CI cadence (e.g. nightly cron, GitHub Actions wake-up, a weekly hands-on audit) and treat its exit code as the trustworthy "is my Comadre deployment safe?" boolean — without needing to manually eyeball debug output, ssh into a replica, or re-validate against a runbook.

**Covers FRs:** FR42 (System enforces strict file permissions on the SQLite database file and the encryption key material at deploy time, and the health command reports deviations), FR44 (System can operate safely across multiple Comadre replicas reading and writing the same SQLite file without corruption under normal operational load), FR52 (Operator can verify via the existing `health.yml` Ansible playbook that UFW, SQLite permissions, cron jobs, and backup playbook outputs are in their expected state, with a clear exit code on any deviation).
**NFRs:** NFR13 (DB file mode `0600` owned by Comadre service user), NFR29 (multi-replica deployments must operate without corruption under normal load), NFR32 (Ansible idempotency — `health.yml` is read-only so trivially idempotent; `bootstrap.yml`'s new chmod tasks must be idempotent under re-run).
**UX-DRs:** Operator-facing playbook grammar — `health.yml` follows the same `ansible-playbook health.yml -i deploy/ansible/inventory/production.yml` shape as `bootstrap.yml` / `cleanup.yml` / `backup-keys.yml` / `restore-keys.yml`. No `ansible_become_password` required — every probe is unprivileged (UFW status read is the only borderline; `ufw status` works for non-root on Ubuntu 22+, fall back to `sudo ufw status` only if the unprivileged read fails). The ansible-layer "fail" surface uses `ansible.builtin.assert`'s `fail_msg` for the corrective hint — no custom exit-code mapping needed; ansible exits non-zero on any failed assert by default.
**Epic:** 4 — Security Hardening, LGPD & Operational Safety. Fourth story in Epic 4 (4.1 → 4.2 → 4.3 → **4.4** → 4.5a–g → 4.6). Story 4.5x (CI non-regression suite) MAY include an "ansible-playbook health.yml on a docker-compose-spun-up Comadre" step — Story 4.4 ships the assertion playbook that 4.5x can wire into CI; Story 4.6 (LGPD docs / breach runbook) cites `health.yml` as the post-incident "did we restore correctly?" verification.

## Builds on

- **Story 1.1 — `_chmod_0600` + `get_connection` parent-dir 0700.** `src/comadre/keys/db.py:261-266` (helper) and `src/comadre/keys/db.py:298-331` (`get_connection`) already enforce DB file mode `0600` and parent directory mode `0700` on EVERY connection open (lifespan, every CLI invocation, every cron-driven `comadre-keys` call). Story 4.4 adds an ansible-layer chmod redundant pass at `bootstrap.yml` so the playbook itself is self-evidently FR42-fulfilling — the Python layer remains the runtime safety net.
- **Story 2.1 — per-replica `app.state.auth_cache` (`TTLCache`).** `src/comadre/keys/cache.py` (the `AuthCache` wrapper) and `src/comadre/main.py` (lifespan instantiating `app.state.auth_cache`) establish the "cache lives in process memory only, never shared across replicas" invariant. The cache-mtime sentinel (`{db_path}.invalidate`) is the cross-replica invalidation channel — a CLI mutation touches it, every replica's `AuthCache.get()` stats it on the next request and flushes when the mtime advances. Story 4.4 verifies this contract with a multi-connection regression test (two `get_connection`s against the same SQLite file, both write through, neither corrupts the other; cache is per-connection-process-state).
- **Story 3.3 — `comadre-daily-suspension` cron + marker file pattern.** `deploy/ansible/playbooks/bootstrap.yml:326-353` installs the cron entry and writes `~/comadre/data/keys/registry.db.cron-installed` as the in-container CLI's evidence-of-install marker. Story 4.4 reads the EXISTENCE of this cron entry from the host crontab (`crontab -l | grep -q comadre-daily-suspension`) inside `health.yml`, AND the in-container CLI continues to consume the marker file for its own `Cron` row (no change to that path).
- **Story 3.4 — `comadre-keys health` JSON contract + exit 7 on warn/fail.** `src/comadre/keys/cli/commands/system.py::health_cmd` (the Typer verb) already supports `--format json` and exits 7 on any warn/fail check (CLAUDE.md "comadre-keys health --format json exits 7 on any warn/fail check; table mode always exits 0" gotcha). Story 4.4's `health.yml` invokes this verb via `docker compose exec -T tts-service comadre-keys health --format json` and asserts on its exit code + on the parsed JSON's `is_healthy` boolean — the playbook does NOT re-implement the DB-state probes; it delegates to the CLI.
- **Story 3.4 — `_check_cron_marker` template.** `src/comadre/keys/health.py:341-386` (`_check_cron_marker`) is the canonical template for the new `_check_backup_cron_marker` Story 4.4 adds. Same shape: stat the marker file (`registry.db.backup-cron-installed`), parse its key/value lines, surface schedule + cron_tz + retention_days. Same warn-on-missing semantics. The two checks render as separate rows ("Cron" → daily-suspension; "Backup cron" → keys-backup), each independently flipping `is_healthy=False` when missing.
- **Story 4.3 — `comadre-keys-backup` cron + `registry.db.backup-cron-installed` marker + `*.backup-*.tar.gz.enc` archive.** `deploy/ansible/playbooks/bootstrap.yml:355-382` installs the backup cron and writes the marker; `deploy/ansible/playbooks/backup-keys.yml` produces the archive. Story 4.4's `health.yml` reads the cron entry from host crontab AND globs the archive path inside the container; the CLI's new `Backup cron` row reads the marker (forward-compat consumer Story 4.3 deferred to 4.4 by design).
- **`compose.yaml` named-volume registry mount.** `compose.yaml:39` (`comadre-registry:/var/lib/comadre:rw`) and `compose.yaml:60-61` (`deploy.replicas: 1`) establish the multi-replica plumbing surface. Story 4.4 verifies the replica-scaling path: scaling `replicas` up via `docker compose up --scale tts-service=N` (or editing `compose.yaml` and re-running `docker compose up -d`) produces N independent processes sharing the named volume, each opening its own SQLite connection (WAL mode), each maintaining its own `app.state.auth_cache`, none corrupting the shared file.
- **Existing `health.yml` shape.** `deploy/ansible/playbooks/health.yml` (the diagnostic-only version) is rewritten in this story to be assertion-based. The pre-existing diagnostic surfaces (container running, /health endpoint, disk usage, voice list) are retained as informational pre-checks, but the new content is the assertion chain that flips the playbook's exit code on any deviation.

## Unblocks

- **Story 4.5x — CI non-regression suite.** `health.yml` becoming an assertion playbook means CI can run `ansible-playbook health.yml` against a docker-compose-spun-up Comadre on every PR and treat the exit code as a build gate. Story 4.5e (CI rate-limit middleware registration) and 4.5a (CI security headers regression) are the closest semantic neighbours — they verify runtime contracts via HTTP probes; `health.yml` verifies operational contracts via filesystem + crontab probes. The two layers complement: 4.5x focuses on the HTTP attack surface; `health.yml` focuses on the deploy-side state.
- **Story 4.6 — LGPD documentation & breach runbook.** The breach runbook will cite `ansible-playbook health.yml` as the "after restoring from backup, before re-opening to traffic" verification step. Story 4.4 makes this citation actionable — without an exit-code-failing playbook, the runbook would have to say "eyeball the debug output", which is not auditable for an LGPD breach response.
- **Operator monitoring integration.** A nightly `crontab` entry running `ansible-playbook health.yml | logger -t comadre-health` becomes a viable lightweight monitoring channel. Pair with the operator's existing alerting (e.g. log-aggregator pattern-match on "ASSERTION FAILED") for zero-cost regression detection.

## Depends on

- **Stories 1.1, 2.1, 3.3, 3.4, 4.3 are `done`** (sprint-status.yaml confirms — checked 2026-04-20). Each contributes a piece Story 4.4 reads from or asserts on:
  - 1.1 → DB file at `/var/lib/comadre/registry.db`, parent dir mode 0700, `_chmod_0600` helper, WAL mode at connection open.
  - 2.1 → `app.state.auth_cache` per replica, sentinel-based cross-replica invalidation.
  - 3.3 → `comadre-daily-suspension` cron entry; `registry.db.cron-installed` marker file.
  - 3.4 → `comadre-keys health --format json` with exit 7 on warn/fail; `_check_cron_marker` template.
  - 4.3 → `comadre-keys-backup` cron entry; `registry.db.backup-cron-installed` marker file; `*.backup-*.tar.gz.enc` archive glob contract.
- **No new env var.** All probes consume existing settings + existing files.
- **No new Python dependency.** The new `_check_backup_cron_marker` function is added to `keys/health.py` using only stdlib + existing helpers.
- **No new ansible collection.** `health.yml` uses only `ansible.builtin.*` (assert, command, stat, debug) and `community.docker.*` (docker_compose_v2, docker_container_info) modules already declared in the project.
- **No new Dockerfile package.** Every assertion runs from ansible-on-host or via `docker compose exec` against the existing image.
- **No schema change.** No new tables, no new columns, no new migration. The Backup-cron health row reads a filesystem marker, not the DB.
- **No auth-path change.** `src/comadre/api.py`, `src/comadre/main.py`, `src/comadre/rate_limit.py`, `src/comadre/keys/auth.py`, `src/comadre/keys/cache.py`, `src/comadre/counters.py`, `src/comadre/keys/migrations/` stay byte-identical (asserted by AC15).

## Scope

Three workstreams, in order of implementation difficulty:

1. **`health.yml` rewrite** — assertion-based playbook with corrective hints + non-zero exit on deviation (largest piece — ~120 net lines of YAML).
2. **`bootstrap.yml` redundant chmod pass** — two new tasks after `docker compose up` that explicitly enforce `0600` on the DB file + `0700` on its parent inside the registry volume (~30 lines).
3. **`comadre-keys health` Backup cron row** — one new helper in `keys/health.py` (`_check_backup_cron_marker`) plus one extra check in `collect_health_report` (~50 lines + tests).

Plus docs and a multi-replica safety regression test.

### 1. Rewrite `deploy/ansible/playbooks/health.yml`

The current playbook is read-only diagnostic — it prints WARN strings via `ansible.builtin.debug` but **always exits 0**. Story 4.4 transforms it into an assertion playbook: every deviation from the expected operational state becomes an `ansible.builtin.assert:` failure with a corrective hint, and the playbook exits non-zero on the first failure (ansible's default behaviour).

**Playbook structure (in order of execution):**

1. **Prereq block** — same shape as `bootstrap.yml:23-65`:
   - Stat `~/comadre/`; assert it exists.
   - Ping the host (`ansible.builtin.ping`).
   - Assert the `tts-service` container is running (`docker compose ps -q --status running tts-service` returns ≥ 1 stdout line). FAIL with `start the service before running health.yml: cd ~/comadre && docker compose up -d`.

2. **DB-state delegation block** — single `docker compose exec` task that runs `comadre-keys health --format json`, captures stdout + exit code, parses the JSON:
   ```yaml
   - name: "[DB] Run in-container comadre-keys health (JSON)"
     ansible.builtin.command:
       cmd: docker compose -f ~/comadre/compose.yaml exec -T tts-service comadre-keys health --format json
     register: cli_health
     changed_when: false
     failed_when: false  # we want to inspect the JSON before failing

   - name: "[DB] Parse comadre-keys health JSON"
     ansible.builtin.set_fact:
       health_json: "{{ cli_health.stdout | from_json }}"

   - name: "[DB] Assert comadre-keys health is_healthy"
     ansible.builtin.assert:
       that:
         - cli_health.rc == 0
         - health_json.is_healthy | bool
       fail_msg: |
         comadre-keys health reports unhealthy state (exit {{ cli_health.rc }}).
         Failing checks:
         {% for c in health_json.checks if c.severity in ['warn', 'fail'] %}
           - {{ c.label }}: {{ c.value }}{% if c.detail %} ({{ c.detail }}){% endif %}
         {% endfor %}
         Re-run inside the container for full table output:
         docker compose exec tts-service comadre-keys health
       success_msg: "comadre-keys health: {{ health_json.checks | length }} checks, all green"
   ```
   The CLI's `is_healthy=True` aggregates DB perms, schema version, customer/key counts, last-suspension-sweep freshness, suspension-sweep cron-installed, **last-backup freshness, and (new) backup-cron-installed**. The ansible task asserts on the aggregate AND surfaces the failing rows in the failure message — no need to re-implement DB probes at the ansible layer.

3. **Backstop DB-perms assertions at the ansible layer (FR42 explicit)** — even though the in-container CLI already covers this (and would have flipped `is_healthy=False` if perms drifted), the epic AC3 names "DB file permissions (fail if not 0600)" specifically. Belt-and-braces: stat the DB file mode + parent dir mode from inside the container and assert again at the ansible layer. This makes the playbook traceable to FR42 without having to read CLI source.
   ```yaml
   - name: "[FS] Stat DB file mode"
     ansible.builtin.command:
       cmd: docker compose -f ~/comadre/compose.yaml exec -T tts-service stat -c '%a' /var/lib/comadre/registry.db
     register: db_mode
     changed_when: false

   - name: "[FS] Assert DB file mode is 0600"
     ansible.builtin.assert:
       that:
         - db_mode.stdout | trim == '600'
       fail_msg: |
         /var/lib/comadre/registry.db has mode {{ db_mode.stdout | trim }} (expected 600).
         Fix: docker compose exec tts-service chmod 600 /var/lib/comadre/registry.db
       success_msg: "DB file mode is 600"

   - name: "[FS] Stat DB parent directory mode"
     ansible.builtin.command:
       cmd: docker compose -f ~/comadre/compose.yaml exec -T tts-service stat -c '%a' /var/lib/comadre
     register: db_parent_mode
     changed_when: false

   - name: "[FS] Assert DB parent dir mode is 0700"
     ansible.builtin.assert:
       that:
         - db_parent_mode.stdout | trim == '700'
       fail_msg: |
         /var/lib/comadre has mode {{ db_parent_mode.stdout | trim }} (expected 700).
         Fix: docker compose exec tts-service chmod 700 /var/lib/comadre
       success_msg: "DB parent dir mode is 700"
   ```

4. **Cron-installed assertions** — read the host crontab once, assert both required entries are present:
   ```yaml
   - name: "[Cron] Read host crontab"
     ansible.builtin.command:
       cmd: crontab -l
     register: crontab_check
     changed_when: false
     failed_when: false  # crontab -l exits 1 when empty

   - name: "[Cron] Assert comadre-daily-suspension is installed"
     ansible.builtin.assert:
       that:
         - "'comadre-daily-suspension' in (crontab_check.stdout | default(''))"
       fail_msg: |
         The 'comadre-daily-suspension' cron entry is missing from the host crontab.
         Fix: re-run ansible-playbook bootstrap.yml -i inventory/production.yml \\
              -e "ansible_become_password=YOUR_SUDO_PASS"
       success_msg: "comadre-daily-suspension cron is installed"

   - name: "[Cron] Assert comadre-keys-backup is installed"
     ansible.builtin.assert:
       that:
         - "'comadre-keys-backup' in (crontab_check.stdout | default(''))"
       fail_msg: |
         The 'comadre-keys-backup' cron entry is missing from the host crontab.
         Fix: re-run ansible-playbook bootstrap.yml -i inventory/production.yml \\
              -e "ansible_become_password=YOUR_SUDO_PASS"
              (Story 4.3's backup cron is installed by bootstrap.yml.)
       success_msg: "comadre-keys-backup cron is installed"
   ```
   Note: the in-container CLI `_check_cron_marker` reads the marker file (which is host-side and reflects bootstrap-write state); `crontab -l` reads the actual host crontab. Both must pass — the marker confirms bootstrap ran; the crontab confirms cron actually has the entry. They CAN diverge (operator manually removes a cron entry without re-running cleanup); the ansible-layer crontab read catches the divergence.

5. **Backup-archive existence assertion** — the in-container CLI's `Last backup` row already reports `warn` when no archive exists (Story 4.3 contract), and the JSON-based aggregate assert in step 2 would catch this. Add an ansible-layer backstop for symmetry with the perms backstop and to surface the archive count:
   ```yaml
   - name: "[Backup] List backup archives in registry volume"
     ansible.builtin.command:
       cmd: docker compose -f ~/comadre/compose.yaml exec -T tts-service bash -c 'ls /var/lib/comadre/*.backup-*.tar.gz.enc 2>/dev/null | wc -l'
     register: backup_count
     changed_when: false

   - name: "[Backup] Assert at least one backup archive exists"
     ansible.builtin.assert:
       that:
         - backup_count.stdout | trim | int >= 1
       fail_msg: |
         No backup archives found at /var/lib/comadre/*.backup-*.tar.gz.enc.
         Either the nightly cron has not yet fired (wait until 02:00 operator TZ
         after bootstrap, or run a manual backup):
           ansible-playbook backup-keys.yml -i inventory/production.yml \\
             -e "ansible_become_password=YOUR_SUDO_PASS"
       success_msg: "{{ backup_count.stdout | trim }} backup archive(s) present"
   ```

6. **UFW-rules assertion** — `ufw status numbered` is unprivileged on Ubuntu 22+ for users in the `adm` group (the deploy user typically is); fall back to `become: true` only on permission denial. Assert the only ALLOW rules are 22/tcp + 80/tcp + 443/tcp:
   ```yaml
   - name: "[UFW] Read firewall rules"
     ansible.builtin.command:
       cmd: ufw status
     register: ufw_status
     changed_when: false
     become: true  # ufw status requires root on most distros

   - name: "[UFW] Extract ALLOW lines"
     ansible.builtin.set_fact:
       ufw_allow_lines: >-
         {{ ufw_status.stdout_lines
            | select('match', '.*ALLOW.*')
            | reject('match', '.*ALLOW OUT.*')
            | list }}

   - name: "[UFW] Assert UFW is active"
     ansible.builtin.assert:
       that:
         - "'Status: active' in ufw_status.stdout"
       fail_msg: |
         UFW is not active. Fix: re-run bootstrap.yml or:
           sudo ufw enable
           sudo ufw allow 22/tcp && sudo ufw allow 80/tcp && sudo ufw allow 443/tcp
       success_msg: "UFW is active"

   - name: "[UFW] Assert exactly the expected ALLOW rules are present"
     ansible.builtin.assert:
       that:
         # Each allowed port must appear in at least one ALLOW line.
         - ufw_allow_lines | select('search', '\\b22/tcp\\b') | list | length >= 1
         - ufw_allow_lines | select('search', '\\b80/tcp\\b') | list | length >= 1
         - ufw_allow_lines | select('search', '\\b443/tcp\\b') | list | length >= 1
         # No unexpected ALLOW rules. The expected set is exactly {22, 80, 443} TCP.
         # Each ALLOW line is a single rule; UFW often duplicates each as v4 + v6,
         # so the maximum expected count is 6 (3 ports × 2 IP families). Anything
         # higher is a deviation worth flagging.
         - ufw_allow_lines | length <= 6
       fail_msg: |
         UFW rules drifted from the expected set (22/tcp + 80/tcp + 443/tcp).
         Current ALLOW lines:
         {% for line in ufw_allow_lines %}
           {{ line }}
         {% endfor %}
         Fix: review and remove unexpected rules with:
           sudo ufw status numbered
           sudo ufw delete <number>
       success_msg: "UFW rules match the expected set ({{ ufw_allow_lines | length }} ALLOW lines)"
   ```

7. **Replica-count probe (informational, AC4)** — query the running replica count and report it; not an assertion (operator may legitimately scale 1→N or N→1):
   ```yaml
   - name: "[Replicas] Count running tts-service replicas"
     ansible.builtin.command:
       cmd: docker compose -f ~/comadre/compose.yaml ps -q --status running tts-service
     register: replica_check
     changed_when: false

   - name: "[Replicas] Report replica count"
     ansible.builtin.debug:
       msg: |
         tts-service replicas running: {{ replica_check.stdout_lines | length }}
         (Each replica maintains its own auth cache; cross-replica invalidation
         propagates within the 60s auth-cache TTL via the {db}.invalidate sentinel.)
   ```

8. **Diagnostic information block (preserved from current `health.yml`)** — disk usage, audio volume size, /health endpoint response, voice list. These are informational only — they do NOT assert. Operator gets the same diagnostic surface they have today; the assertion chain runs alongside.

9. **Summary task** — single `ansible.builtin.debug` printing a green "All checks passed" banner with the count of probes that ran. The failure path is ansible's default failure summary (which lists the failed assert with its `fail_msg`).

**Idempotency.** `health.yml` performs zero mutations — every probe is `changed_when: false` (commands) or read-only (`stat`, `command: ufw status`). NFR32 is trivially satisfied: re-running the playbook produces byte-identical output for an unchanged deployment.

### 2. Belt-and-braces chmod pass in `bootstrap.yml`

Add two new tasks AFTER `[TTS] Build image and start service` (the `community.docker.docker_compose_v2` task at `bootstrap.yml:289-295`) and BEFORE the cron-job block. The Python connection layer already handles this on first connect, but adding ansible-layer enforcement makes the playbook self-evidently FR42-compliant and traces to a named task in the playbook source.

```yaml
# =========================================================================
# File-Permission Enforcement (FR42, NFR13)
# =========================================================================
# The Python connection layer (src/comadre/keys/db.py::_chmod_0600 +
# get_connection's parent.mkdir(mode=0o700)) already enforces these modes
# on every connection open. The two tasks below are belt-and-braces — they
# make bootstrap.yml self-evidently AC-fulfilling for FR42 + NFR13 without
# requiring the reader to inspect Python source. Idempotent: chmod is a
# no-op when the mode already matches.

- name: "[FS] Wait for service lifespan to materialise registry.db"
  ansible.builtin.command:
    cmd: docker compose -f ~/comadre/compose.yaml exec -T tts-service test -f /var/lib/comadre/registry.db
  register: db_present
  retries: 30
  delay: 2
  until: db_present.rc == 0
  changed_when: false
  # The lifespan opens get_connection() which creates the file + applies
  # migrations on first start. 30 × 2s = 60s ceiling matches the existing
  # health-endpoint poll in step "[Health] Wait for service to become healthy".

- name: "[FS] Enforce 0600 on registry.db (and WAL/SHM sidecars)"
  ansible.builtin.command:
    cmd: docker compose -f ~/comadre/compose.yaml exec -T tts-service bash -c 'chmod 600 /var/lib/comadre/registry.db /var/lib/comadre/registry.db-wal /var/lib/comadre/registry.db-shm 2>/dev/null; true'
  changed_when: false
  # WAL and SHM sidecars only exist after the first write; the trailing
  # ``2>/dev/null; true'' tolerates their absence on a freshly-created DB
  # that has not yet had a write transaction. The real safety here is the
  # main DB file; sidecars are a subordinate concern.

- name: "[FS] Enforce 0700 on registry parent directory"
  ansible.builtin.command:
    cmd: docker compose -f ~/comadre/compose.yaml exec -T tts-service chmod 700 /var/lib/comadre
  changed_when: false
```

**Why the explicit chmod commands instead of `ansible.builtin.file: mode: '0600'`:** the registry path is INSIDE the container's named volume; ansible's `file:` module operates on host paths only. Going through `docker compose exec` is the only way to reach the in-container path without resorting to `docker volume inspect | jq '.Mountpoint'` + a host-side `file:` task that depends on volume-driver internals. The `chmod` shell-out is portable across docker engine and Docker Desktop.

### 3. Add `Backup cron` row to `comadre-keys health`

Story 4.3 wrote the `registry.db.backup-cron-installed` marker at bootstrap (Story 4.3 spec §3.4) but explicitly deferred adding the consuming health row to "a future Story 4.x" (Story 4.3 §Deferred-work bullet 6). Story 4.4 closes that loop.

#### 3.1 New helper in `src/comadre/keys/health.py`

Add `_check_backup_cron_marker` modelled on the existing `_check_cron_marker` (`keys/health.py:341-386`):

```python
def _check_backup_cron_marker(marker_path: Path) -> HealthCheck:
    """Backup cron marker — written by ``bootstrap.yml`` at install time.

    Format:
      schedule=<cron-expression>
      cron_tz=<IANA-timezone>
      retention_days=<int>

    Mirrors ``_check_cron_marker`` exactly; the only differences are the
    label ("Backup cron" vs "Cron"), the corrective hint, and the rendered
    value (which includes ``retention_days`` because it is operationally
    relevant to the backup contract — operators reading the health report
    need to know how many days of archives are being retained).
    """
    if not marker_path.exists():
        return HealthCheck(
            label="Backup cron",
            value="Not installed",
            severity="warn",
            detail="run ansible-playbook bootstrap.yml",
            data={"installed": False},
        )
    try:
        text = marker_path.read_text(encoding="utf-8")
    except (OSError, UnicodeDecodeError):
        return HealthCheck(
            label="Backup cron",
            value="Marker present but unparseable",
            severity="warn",
            detail="re-run ansible-playbook bootstrap.yml",
            data={"installed": True, "parsed": False},
        )
    parsed = _marker_parse(text)
    if parsed is None:
        return HealthCheck(
            label="Backup cron",
            value="Marker present but unparseable",
            severity="warn",
            detail="re-run ansible-playbook bootstrap.yml",
            data={"installed": True, "parsed": False},
        )
    schedule = parsed.get("schedule", "").strip()
    cron_tz = parsed.get("cron_tz", "").strip()
    retention = parsed.get("retention_days", "").strip()
    if not schedule or not cron_tz or not retention:
        return HealthCheck(
            label="Backup cron",
            value="Marker present but unparseable",
            severity="warn",
            detail="re-run ansible-playbook bootstrap.yml",
            data={"installed": True, "parsed": False},
        )
    value = (
        f"comadre-keys-backup at {schedule} "
        f"(CRON_TZ={cron_tz}, retention={retention}d)"
    )
    return HealthCheck(
        label="Backup cron",
        value=value,
        severity="ok",
        detail=None,
        data={
            "installed": True,
            "schedule": schedule,
            "tz": cron_tz,
            "retention_days": retention,
        },
    )
```

#### 3.2 Wire the new check into `collect_health_report`

Extend the function signature to accept a `backup_cron_marker_path` parameter (defaulted via the caller so existing call sites work) and append the new check to the report's checks tuple:

```python
def collect_health_report(
    *,
    conn: sqlite3.Connection,
    db_path: str,
    schema_version_expected: int,
    cron_marker_path: str,
    backup_parent: str,
    backup_pattern: str = "*.backup-*.tar.gz.enc",
    backup_cron_marker_path: str | None = None,  # NEW
    sweep_staleness_warn_seconds: int = _SWEEP_STALENESS_WARN_SECONDS,
) -> HealthReport:
    # ...existing prelude unchanged...

    if backup_cron_marker_path is None:
        # Default: same parent + name pattern as the suspension-sweep marker.
        backup_cron_marker_path = str(
            Path(db_path).with_name(Path(db_path).name + ".backup-cron-installed")
        )
    backup_cron_check = _check_backup_cron_marker(Path(backup_cron_marker_path))

    checks: tuple[HealthCheck, ...] = (
        _check_db_path(db_path_obj),
        _check_schema_version(conn, expected=schema_version_expected),
        _check_customer_count(conn),
        _check_key_counts(conn),
        _check_last_sweep(...),
        cron_check,                      # existing — daily-suspension marker
        backup_cron_check,               # NEW — backup cron marker
        _check_last_backup(...),
        _check_auth_cache(cache_status),
    )
    # ...rest unchanged...
```

**Order matters for the rendered table:** the new `Backup cron` row sits between `Cron` (suspension-sweep) and `Last backup`, grouping the cron-installed signals together visually. JSON consumers iterate the list; the order is documented but not asserted, so the change is forward-compatible for downstream automation.

#### 3.3 CLI invocation site update

`src/comadre/keys/cli/commands/system.py::health_cmd` calls `collect_health_report(...)`. The new parameter is auto-defaulted (it derives from `db_path`), so the CLI call site does not need any change. The default-derivation lives inside `collect_health_report` so a future caller (e.g. a webhook, an ops API) doesn't have to know the marker path convention.

### 4. Multi-replica safety regression test (FR44, NFR29)

Add a new test module `tests/test_keys_db_multi_replica.py` that opens TWO independent `get_connection`s against the same SQLite file and exercises the concurrency contract:

```python
def test_two_connections_can_concurrently_read_and_write(tmp_path: Path) -> None:
    """FR44 + NFR29: shared SQLite file under WAL allows concurrent ops.

    Simulates two replicas (or a replica + a CLI invocation) by opening
    two independent connections from the same process — sufficient to
    exercise WAL's concurrent-reader-vs-single-writer semantics. Real
    multi-process invocation is a deploy-smoke concern (Task 8 below).
    """
    db_path = tmp_path / "registry.db"
    conn_a = get_connection(db_path)
    conn_b = get_connection(db_path)
    try:
        _apply_migrations(conn_a)
        # B sees A's schema after a fresh transaction begins.
        version_via_b = conn_b.execute(
            "SELECT MAX(version) FROM schema_version"
        ).fetchone()[0]
        assert version_via_b == 1

        # A writes; B reads concurrently (no SQLITE_BUSY under WAL).
        with conn_a:
            conn_a.execute(
                "INSERT INTO customer (id, name, tax_id_encrypted, "
                "tax_id_kind, registered_at, updated_at) "
                "VALUES (?, ?, ?, ?, ?, ?)",
                ("cust_a", "Replica A", b"\x00", "cpf", _now(), _now()),
            )
        # B sees the row immediately (WAL post-commit visibility).
        rows_via_b = conn_b.execute(
            "SELECT name FROM customer WHERE id = ?", ("cust_a",)
        ).fetchall()
        assert [r["name"] for r in rows_via_b] == ["Replica A"]

        # Both connections continue to operate; mode stays 0600.
        assert stat.S_IMODE(db_path.stat().st_mode) == 0o600
    finally:
        conn_a.close()
        conn_b.close()


def test_journal_mode_is_wal_on_every_get_connection(tmp_path: Path) -> None:
    """Each connection independently sets WAL mode at open."""
    db_path = tmp_path / "registry.db"
    for _ in range(3):
        conn = get_connection(db_path)
        try:
            mode = conn.execute("PRAGMA journal_mode").fetchone()[0]
            assert mode.lower() == "wal"
        finally:
            conn.close()


def test_parent_directory_is_0700_after_first_connection(tmp_path: Path) -> None:
    """FR42 / NFR13 — parent dir mode is enforced at get_connection time."""
    db_path = tmp_path / "subdir" / "registry.db"
    assert not db_path.parent.exists()  # mkdir is part of the contract
    conn = get_connection(db_path)
    try:
        parent_mode = stat.S_IMODE(db_path.parent.stat().st_mode)
        assert parent_mode == 0o700
        db_mode = stat.S_IMODE(db_path.stat().st_mode)
        assert db_mode == 0o600
    finally:
        conn.close()
```

The multi-replica scenario in the wild involves multiple PROCESSES (one per replica), not multiple connections in one process. SQLite's WAL contract is symmetric — within-process and across-process readers both see committed transactions; the test exercises the within-process side, which is the easiest to assert deterministically. The cross-process side is exercised in Task 8 (VPS smoke) by scaling `compose.yaml`'s `deploy.replicas`.

### 5. Tests for the new `_check_backup_cron_marker` helper

Add a new `TestBackupCronMarker` class in `tests/test_keys_health.py` modelled on the existing `TestCronMarker`:

```python
class TestBackupCronMarker:
    def test_warn_when_marker_missing(self, tmp_path: Path) -> None:
        check = _check_backup_cron_marker(tmp_path / "missing.marker")
        assert check.label == "Backup cron"
        assert check.severity == "warn"
        assert check.value == "Not installed"
        assert check.data == {"installed": False}

    def test_ok_when_marker_well_formed(self, tmp_path: Path) -> None:
        marker = tmp_path / "registry.db.backup-cron-installed"
        marker.write_text(
            "schedule=0 2 * * *\n"
            "cron_tz=UTC\n"
            "retention_days=14\n"
        )
        check = _check_backup_cron_marker(marker)
        assert check.severity == "ok"
        assert "comadre-keys-backup at 0 2 * * *" in check.value
        assert "CRON_TZ=UTC" in check.value
        assert "retention=14d" in check.value
        assert check.data == {
            "installed": True,
            "schedule": "0 2 * * *",
            "tz": "UTC",
            "retention_days": "14",
        }

    def test_warn_on_missing_retention_days_field(self, tmp_path: Path) -> None:
        """All three fields must be present; missing retention_days → warn."""
        marker = tmp_path / "marker"
        marker.write_text("schedule=0 2 * * *\ncron_tz=UTC\n")
        check = _check_backup_cron_marker(marker)
        assert check.severity == "warn"
        assert check.value == "Marker present but unparseable"

    def test_warn_on_garbage_marker(self, tmp_path: Path) -> None:
        marker = tmp_path / "marker"
        marker.write_text("just some garbage\n")
        check = _check_backup_cron_marker(marker)
        assert check.severity == "warn"
```

Plus a regression on `collect_health_report` to verify the new check is wired in:

```python
def test_collect_full_healthy_report_includes_backup_cron_row(
    tmp_path: Path,
) -> None:
    db_path = tmp_path / "registry.db"
    conn = get_connection(db_path)
    try:
        _apply_migrations(conn)
        # Seed the suspension cron marker (Story 3.4 invariant).
        (tmp_path / "registry.db.cron-installed").write_text(
            "schedule=30 0 * * *\ncron_tz=UTC\n"
        )
        # Seed the backup cron marker (Story 4.4 — new).
        (tmp_path / "registry.db.backup-cron-installed").write_text(
            "schedule=0 2 * * *\ncron_tz=UTC\nretention_days=14\n"
        )
        # Seed a fresh backup so Last backup → ok.
        (tmp_path / "registry.db.backup-2026-04-20T02-00-00Z.tar.gz.enc").write_bytes(
            b"stub"
        )
        report = collect_health_report(
            conn=conn,
            db_path=str(db_path),
            schema_version_expected=1,
            cron_marker_path=str(tmp_path / "registry.db.cron-installed"),
            backup_parent=str(tmp_path),
        )
    finally:
        conn.close()
    labels = [c.label for c in report.checks]
    assert "Backup cron" in labels
    assert report.is_healthy is True
    backup_cron = next(c for c in report.checks if c.label == "Backup cron")
    assert backup_cron.severity == "ok"
```

Also extend `tests/test_keys_cli_health.py` to assert the new row appears in the table render (`"Backup cron"` substring in the captured stdout) and in the JSON shape (one entry with `label == "Backup cron"`).

### 6. Docs

- **`docs/deployment-guide.md`** — new "Operational health checks" subsection placed AFTER the existing "Backup & restore" subsection (added by Story 4.3) and BEFORE "Firewall (UFW)". ~30 lines covering:
  1. `ansible-playbook health.yml` invocation (no become password needed for the read-only path; UFW status is the one task that uses become).
  2. The probe list and what each asserts (DB perms, parent dir perms, both crons, backup archive present, UFW rules unchanged, in-container CLI is_healthy).
  3. The exit-code contract: 0 = all green, non-zero = at least one assertion failed (ansible's default behaviour).
  4. Recommended cadence: nightly via `crontab` piped to `logger -t comadre-health`, OR weekly hands-on via SSH, OR per-PR via CI (Story 4.5x will land this).
  5. Common failure modes and their fixes (the playbook's own `fail_msg` strings are the primary documentation; this section recaps the most likely ones — DB perms drift, missing cron, UFW rule added in error).

- **`docs/configuration-reference.md`** — the auxiliary-files table (added by Story 3.4 and extended by Story 4.3) gains no new rows (the backup-cron marker is already documented). The "Operator-facing CLI" section (if it exists) gains a new line under `comadre-keys health` noting the additional `Backup cron` row (label + severity model).

- **`CLAUDE.md`** — two new "Non-Obvious Gotchas":
  1. "**`ansible-playbook health.yml` is the operational-state assertion playbook (Story 4.4); it exits non-zero on any deviation.** Wire into monitoring (cron + logger), CI (Story 4.5x), or operator runbooks. The probes: DB mode == 0600, parent dir mode == 0700, both crons (`comadre-daily-suspension`, `comadre-keys-backup`) present in host crontab, ≥ 1 `*.backup-*.tar.gz.enc` archive in the registry volume, UFW active with exactly 22/80/443 ALLOW, in-container `comadre-keys health --format json` reports `is_healthy=True`. Each assertion carries a corrective hint in its `fail_msg`. The pre-existing diagnostic surfaces (container running, /health response, disk usage) are preserved as informational pre-checks but the new content is the assertion chain. Don't 'soften' an assertion to a debug print — the whole point of 4.4 is that operators can `ansible-playbook health.yml; echo $?` and trust the boolean."
  2. "**`bootstrap.yml`'s explicit chmod tasks (Story 4.4) are belt-and-braces on top of `keys/db.py::get_connection`'s `_chmod_0600` + `mkdir(mode=0o700)`.** The Python layer enforces these modes on every connection open — runtime safety net. The ansible tasks make the playbook self-evidently FR42 / NFR13 fulfilling and trace to a single named task (operators don't need to read Python to verify the contract). The `chmod` shell-out goes through `docker compose exec` because the registry lives inside a named Docker volume, not a host bind mount — host-side `ansible.builtin.file:` cannot reach the in-container path without resorting to `docker volume inspect`-derived host paths, which are docker-engine-internal and break on Docker Desktop / podman. Don't 'fix' the redundancy by removing either layer — Python protects against runtime drift, ansible protects against bootstrap-time misconfiguration."

### 7. Grep checks (for the implementer's pre-commit pass)

Run before claiming the story done:

- `rg "_check_backup_cron_marker" src/` — exactly two hits: definition in `keys/health.py`, call site inside `collect_health_report`.
- `rg "_check_cron_marker" src/` — still exactly two hits (Story 3.4 — definition + call site), unchanged by 4.4.
- `rg "Backup cron" src/` — exactly one hit, in `_check_backup_cron_marker`'s `label="Backup cron"` literal.
- `rg "ansible.builtin.assert" deploy/ansible/playbooks/health.yml` — exactly **6** hits (DB-state delegation, DB mode, parent mode, daily-suspension cron, keys-backup cron, backup-archive count, UFW active, UFW rules — eight assertions, but two are the UFW pair → 6 distinct task names with `assert:`). Adjust count per actual implementation; the precise number is documented in the playbook header comment for future readers.
- `rg "HTTPException" src/` — ZERO hits (non-regression; FR51).
- `rg "fernet\.decrypt" src/` — still exactly ONE hit in `keys/crypto.py` (Story 4.1 invariant unchanged).
- `rg "Fernet\(" src/` — still exactly FOUR hits (Story 4.2 invariant unchanged).
- `rg "_BACKUP_NOT_IMPLEMENTED_INFO" src/` — still exactly ONE hit in `keys/health.py:47`, value `False` (Story 4.3 invariant unchanged).
- `rg "docs_url|redoc_url|openapi_url" src/comadre/main.py` — all three `None` (FR47; non-regression).
- `uv run ruff check . && uv run mypy src/ && uv run pytest` — all green.
- `ansible-lint deploy/ansible/playbooks/health.yml deploy/ansible/playbooks/bootstrap.yml` — zero new findings.

## Acceptance Criteria

### AC1 — `bootstrap.yml` enforces DB file mode `0600` and parent dir mode `0700` on a fresh deploy

**Given** a clean VPS and `COMADRE_KEY_REGISTRY_ENCRYPTION_KEY` + `COMADRE_BACKUP_PASSPHRASE` exported.

**When** the operator runs `ansible-playbook bootstrap.yml -i inventory/production.yml -e "ansible_become_password=$SUDO_PASS"`.

**Then** after the playbook completes, `docker compose exec tts-service stat -c '%a' /var/lib/comadre/registry.db` returns `600`.

**And** `docker compose exec tts-service stat -c '%a' /var/lib/comadre` returns `700`.

**And** the playbook exits 0.

**And** re-running the playbook is idempotent — the chmod tasks report `OK` (no change) on the second run.

### AC2 — `bootstrap.yml`'s file-permission enforcement waits for the lifespan to materialise the DB

**Given** a deploy where the FastAPI lifespan hasn't yet completed first-connection initialisation when the chmod task runs.

**When** the chmod task fires.

**Then** the prerequisite `[FS] Wait for service lifespan to materialise registry.db` task polls (`retries: 30, delay: 2`) until `test -f /var/lib/comadre/registry.db` succeeds.

**And** only then does the chmod task run, against a file that exists.

**And** the playbook does not fail with a "no such file" error during the chmod step.

### AC3 — `health.yml` exits 0 against a healthy deployment

**Given** a deployment where: `tts-service` is running, DB mode is `0600`, parent dir mode is `0700`, both crons (`comadre-daily-suspension` + `comadre-keys-backup`) are installed, ≥ 1 `*.backup-*.tar.gz.enc` archive exists in the registry volume, UFW is active with exactly `22/tcp + 80/tcp + 443/tcp ALLOW` rules, and `docker compose exec tts-service comadre-keys health --format json` returns `is_healthy=True`.

**When** the operator runs `ansible-playbook health.yml -i inventory/production.yml -e "ansible_become_password=$SUDO_PASS"`.

**Then** the playbook exits 0.

**And** the summary task prints "All checks passed" with the count of probes that ran.

**And** every assert task's `success_msg` is rendered in the playbook output.

### AC4 — `health.yml` exits non-zero when DB file mode drifts from `0600`

**Given** a healthy deployment where the operator (or a supply-chain incident) has changed the DB file mode to `0644`.

**When** `ansible-playbook health.yml` runs.

**Then** the `[FS] Assert DB file mode is 0600` task fails.

**And** the `fail_msg` includes the actual mode (`644`), the expected mode (`600`), and the corrective `chmod` command.

**And** the playbook exits non-zero (ansible's default failure exit code).

**And** subsequent tasks do NOT run (assert failure halts execution).

### AC5 — `health.yml` exits non-zero when the parent directory mode drifts from `0700`

**Given** a healthy deployment where the operator has changed `/var/lib/comadre`'s mode to `0755`.

**When** `ansible-playbook health.yml` runs.

**Then** the `[FS] Assert DB parent dir mode is 0700` task fails with the corrective hint.

**And** the playbook exits non-zero.

### AC6 — `health.yml` exits non-zero when `comadre-daily-suspension` cron is missing

**Given** a healthy deployment where the operator has removed the suspension-sweep cron via `crontab -e`.

**When** `ansible-playbook health.yml` runs.

**Then** the `[Cron] Assert comadre-daily-suspension is installed` task fails.

**And** the `fail_msg` directs the operator to re-run `bootstrap.yml`.

**And** the playbook exits non-zero.

### AC7 — `health.yml` exits non-zero when `comadre-keys-backup` cron is missing

**Given** a healthy deployment where the backup cron has been removed from the host crontab.

**When** `ansible-playbook health.yml` runs.

**Then** the `[Cron] Assert comadre-keys-backup is installed` task fails with the corrective hint.

**And** the playbook exits non-zero.

### AC8 — `health.yml` exits non-zero when no backup archive exists

**Given** a deployment where every `*.backup-*.tar.gz.enc` archive in the registry volume has been deleted.

**When** `ansible-playbook health.yml` runs.

**Then** the `[Backup] Assert at least one backup archive exists` task fails.

**And** the `fail_msg` suggests waiting for the nightly cron OR running `backup-keys.yml` manually.

**And** the playbook exits non-zero.

### AC9 — `health.yml` exits non-zero when UFW rules drift

**Given** a deployment where the operator has added an `ALLOW 5432/tcp` rule (e.g. for a Postgres service) to UFW.

**When** `ansible-playbook health.yml` runs.

**Then** the `[UFW] Assert exactly the expected ALLOW rules are present` task fails (the count exceeds the `≤ 6` threshold for v4 + v6 dupes of {22, 80, 443}).

**And** the `fail_msg` lists every current ALLOW line so the operator can spot the drift.

**And** the playbook exits non-zero.

### AC10 — `health.yml` exits non-zero when the in-container CLI reports unhealthy

**Given** a deployment where the suspension-sweep cron has been installed but has not yet fired (so `comadre-keys health` reports `Last suspension sweep: never (cron installed but not yet fired)` → warn → `is_healthy=False`).

**When** `ansible-playbook health.yml` runs.

**Then** the `[DB] Assert comadre-keys health is_healthy` task fails.

**And** the `fail_msg` lists every warn/fail check from the JSON output, including the failing `Last suspension sweep` row.

**And** the playbook exits non-zero.

### AC11 — `health.yml` is read-only and trivially idempotent (NFR32)

**Given** a healthy deployment.

**When** `ansible-playbook health.yml` runs three times in succession.

**Then** every run produces byte-identical output (modulo timestamps).

**And** no task reports `changed=true` (every command is `changed_when: false`; every probe is read-only).

**And** the deployment state is unchanged between runs (DB mode, cron entries, UFW rules, file count all identical).

### AC12 — `comadre-keys health` includes the new `Backup cron` row

**Given** a deployment where the backup-cron marker file (`registry.db.backup-cron-installed`) was written by `bootstrap.yml`.

**When** the operator runs `docker compose exec tts-service comadre-keys health`.

**Then** the rendered table includes a `Backup cron` row between `Cron` and `Last backup`.

**And** the value reads `comadre-keys-backup at 0 2 * * * (CRON_TZ=UTC, retention=14d)` (or the operator's actual schedule / TZ / retention).

**And** the severity is `ok` when the marker is well-formed.

**And** `comadre-keys health --format json` includes a check entry with `label == "Backup cron"`, `severity == "ok"`, and a `data` object containing `installed`, `schedule`, `tz`, `retention_days`.

### AC13 — `Backup cron` flips `is_healthy=False` when the marker is missing

**Given** a deployment where the backup-cron marker has been removed.

**When** `comadre-keys health --format json` runs.

**Then** the `Backup cron` check has `severity == "warn"`, `value == "Not installed"`, `detail == "run ansible-playbook bootstrap.yml"`.

**And** `is_healthy` is `False`.

**And** the JSON-mode exit code is 7.

### AC14 — Multi-replica safety: shared SQLite + WAL + per-process auth caches (FR44, NFR29)

**Given** the regression test `tests/test_keys_db_multi_replica.py`.

**When** the test opens two independent connections via `get_connection` against the same DB path, applies migrations on the first, asserts the second sees the schema, writes from the first, and reads from the second.

**Then** the second connection sees the freshly-committed write without `SQLITE_BUSY`.

**And** both connections continue to operate without error.

**And** `PRAGMA journal_mode` returns `wal` on every `get_connection` call.

**And** the DB file mode remains `0600` after both connections close.

**And** the parent directory mode remains `0700`.

**And** all three test functions (`test_two_connections_can_concurrently_read_and_write`, `test_journal_mode_is_wal_on_every_get_connection`, `test_parent_directory_is_0700_after_first_connection`) pass.

### AC15 — Read-only invariant on non-target surfaces (regression guard)

**Given** the Story 4.4 diff.

**When** `git diff --name-only master...HEAD` is run.

**Then** the Python set excludes: `src/comadre/api.py`, `src/comadre/main.py`, `src/comadre/rate_limit.py`, `src/comadre/keys/auth.py`, `src/comadre/keys/cache.py`, `src/comadre/keys/audit.py`, `src/comadre/keys/billing.py`, `src/comadre/keys/crypto.py`, `src/comadre/keys/db.py`, `src/comadre/keys/migrations/`, `src/comadre/counters.py`, `src/comadre/config.py`, `src/comadre/keys/cli/` (no verb changes — the existing `health` verb's call to `collect_health_report` already uses keyword args, no signature change at the call site).

**And** the only `src/comadre/` file changes are `keys/health.py` (new helper + extended `collect_health_report` signature with default-derived parameter).

**And** `pyproject.toml` shows ZERO new dependencies.

**And** the only ansible playbook changes are `health.yml` (rewrite) and `bootstrap.yml` (three new tasks for chmod + lifespan-wait).

### AC16 — `ansible-lint` passes on the changed playbooks

**Given** the rewritten `health.yml` and the extended `bootstrap.yml`.

**When** `ansible-lint deploy/ansible/playbooks/health.yml deploy/ansible/playbooks/bootstrap.yml` runs.

**Then** zero new findings are reported (the pre-existing `restart sshd` handler-casing note in `bootstrap.yml` is allowed to remain).

### AC17 — End-to-end VPS drill: bootstrap → health passes → drift → health fails → fix → health passes

**Given** a fresh VPS.

**When** the operator runs the sequence:
1. `ansible-playbook bootstrap.yml` → service deploys.
2. `ansible-playbook health.yml` → exits 0.
3. `docker compose exec tts-service chmod 644 /var/lib/comadre/registry.db` → drift introduced.
4. `ansible-playbook health.yml` → exits non-zero with the DB-mode failure message.
5. `docker compose exec tts-service chmod 600 /var/lib/comadre/registry.db` → drift fixed.
6. `ansible-playbook health.yml` → exits 0 again.

**Then** the playbook behaviour matches the assert/fix/assert cycle.

**And** the corrective hint at step 4 (the exact `chmod` command in the `fail_msg`) is the same command the operator runs at step 5 — the playbook's hint is actionable verbatim.

## Tasks / Subtasks

- [x] **Task 1 — Rewrite `health.yml` as an assertion playbook** (AC3, AC4, AC5, AC6, AC7, AC8, AC9, AC10, AC11, AC16)
  - [x] 1.1 Replace the existing diagnostic-only `health.yml` with the assertion-based version per §1 above.
  - [x] 1.2 Preserve the existing diagnostic surfaces (container running, /health endpoint, disk usage, audio volume, voice list) as informational pre-checks running BEFORE the assertion chain — operators get the same diagnostic output they have today, plus the new fail-fast guarantees.
  - [x] 1.3 Each `ansible.builtin.assert:` task carries a `fail_msg` with the exact corrective command.
  - [x] 1.4 The DB-state delegation task uses `failed_when: false` on the `command:` (so the JSON parses) + the assert task asserts on `cli_health.rc == 0` AND `health_json.is_healthy | bool` separately.
  - [x] 1.5 The UFW assertion uses `become: true` for the `ufw status` read; tolerate `ufw status` returning non-zero by using `failed_when: false` on the command and asserting on `'Status: active' in stdout`.
  - [x] 1.6 `ansible-lint` clean (only the pre-existing `restart sshd` handler-casing finding remains, allowed by AC16).
  - [x] 1.7 Idempotent — every probe is `changed_when: false`, every read-only.

- [x] **Task 2 — Extend `bootstrap.yml` with file-permission enforcement tasks** (AC1, AC2)
  - [x] 2.1 Add the `[FS] Wait for service lifespan to materialise registry.db` task with `retries: 30, delay: 2, until: rc == 0` polling.
  - [x] 2.2 Add the `[FS] Enforce 0600 on registry.db (and WAL/SHM sidecars)` task with the bash-c shell-out that tolerates missing sidecars.
  - [x] 2.3 Add the `[FS] Enforce 0700 on registry parent directory` task.
  - [x] 2.4 Place all three tasks AFTER `[TTS] Build image and start service` and BEFORE the `# Cron Jobs` section.
  - [x] 2.5 `ansible-lint` clean (no new findings; pre-existing `restart sshd` handler-casing is the only violation surfaced).
  - [x] 2.6 Idempotency reasoning documented in a header comment — `chmod` is a no-op when the mode already matches; the wait-for-file task is read-only.

- [x] **Task 3 — Add `_check_backup_cron_marker` to `keys/health.py`** (AC12, AC13)
  - [x] 3.1 Add the new helper per §3.1 above. Reuse `_marker_parse` from the existing module (no duplication).
  - [x] 3.2 Extend `collect_health_report`'s signature with `backup_cron_marker_path: str | None = None`, default-derive from `db_path` when None.
  - [x] 3.3 Append the new check to the `checks` tuple between `cron_check` (suspension-sweep) and `_check_last_backup` so the rendered table groups cron-installed signals together.
  - [x] 3.4 No change required at the CLI call site — the new parameter is auto-defaulted.
  - [x] 3.5 `_check_last_backup`'s docstring left untouched — the new helper is independent.

- [x] **Task 4 — Tests for `_check_backup_cron_marker` and the integration into `collect_health_report`** (AC12, AC13)
  - [x] 4.1 Add `TestBackupCronMarker` class to `tests/test_keys_health.py` with the four cases (plus a fifth alternate-TZ/retention case for parity with `TestCronMarkerCheck`).
  - [x] 4.2 Update `TestFullHealthyReport::test_collect_full_healthy_report` to seed the new backup-cron marker; the canonical labels list and `len(report.checks)` assertion bump from 8 → 9. New `_write_backup_cron_marker` helper added alongside `_write_marker`.
  - [x] 4.3 Update `TestAggregation::test_is_healthy_true_with_info_only` similarly.
  - [x] 4.4 Add `TestCollectHealthReportBackupCronWiring` class with four cases: row-position invariant, default-derived marker path, missing-marker flips `is_healthy=False`, override-via-kwarg path.
  - [x] 4.5 `tests/test_keys_cli_health.py` — add `_write_backup_cron_marker` helper; seed it in every healthy-path test (`TestTableMode`, `TestJsonMode`, `TestMarkerRendering`).
  - [x] 4.6 New `TestBackupCronRow` class — table-render substring assertion, JSON shape assertion, missing-marker → exit 7 assertion.
  - [x] 4.7 Audited every healthy-path test in both files; updated all that previously expected `is_healthy=True` against a fresh tmp_path.

- [x] **Task 5 — Multi-replica safety regression test** (AC14)
  - [x] 5.1 Create `tests/test_keys_db_multi_replica.py` with the three test functions per §4 above (plus an extra B→A write-then-read cycle inside `test_two_connections_can_concurrently_read_and_write` to confirm either side can act as the single writer).
  - [x] 5.2 Imports: `get_connection`, `_apply_migrations`, `generate_customer_id` from `comadre.keys.db`; `stat`, `pathlib.Path`.
  - [x] 5.3 Each test uses `tmp_path` for isolation; both connections close in `finally:` blocks.
  - [x] 5.4 `uv run pytest tests/test_keys_db_multi_replica.py -v` → 3/3 green.

- [x] **Task 6 — Docs**
  - [x] 6.1 `docs/deployment-guide.md` — added the "Operational health checks — `ansible-playbook health.yml`" subsection between "Backup & restore" and "Firewall (UFW)" with the assertion table, recommended cadences, and common failure-mode recap.
  - [x] 6.2 `docs/configuration-reference.md` — extended the `{KEY_REGISTRY_DB_PATH}.backup-cron-installed` row in the auxiliary-files table to reflect that `comadre-keys health` now reads it via the dedicated `Backup cron` row (Story 4.4 closes the Story 4.3 forward-compat reservation).
  - [x] 6.3 `CLAUDE.md` — added three new "Non-Obvious Gotchas": (a) `ansible-playbook health.yml` exit-code contract; (b) `bootstrap.yml` chmod belt-and-braces rationale + `docker compose exec` constraint; (c) two cron-installed rows in `comadre-keys health`.
  - [x] 6.4 `README.md` — added a new feature bullet for the operational health assertion playbook after the "Nightly encrypted backups" bullet.

- [x] **Task 7 — Final quality gate**
  - [x] 7.1 `uv run ruff check .` → "All checks passed!"
  - [x] 7.2 `uv run mypy src/` → "Success: no issues found in 35 source files".
  - [x] 7.3 `uv run pytest` → 1414 passed (1399 baseline + 15 new tests).
  - [x] 7.4 `uv run pre-commit run --all-files` → all hooks pass (ruff format reformatted three new files on the first pass; second pass green).
  - [x] 7.5 `ansible-lint deploy/ansible/playbooks/health.yml deploy/ansible/playbooks/bootstrap.yml` → zero new findings (pre-existing `restart sshd` handler-casing remains, allowed by AC16).
  - [x] 7.6 Grep invariants from §7 — all pass: `_check_backup_cron_marker` 2 hits, `_check_cron_marker` 3 hits (definition + docstring reference + call site), `Backup cron` 5 hits (label literal × 5 in `_check_backup_cron_marker` branches), `fernet.decrypt` 1 hit (`crypto.py`), `Fernet(` 4 hits, `_BACKUP_NOT_IMPLEMENTED_INFO` 3 hits (declaration, docstring reference, call site), `docs_url|redoc_url|openapi_url` all `None` in `main.py`. The `HTTPException` grep returns one hit in `src/comadre/main.py:250` — pre-existing docstring referring to Starlette's HTTPException(405) handler, not a raised exception (non-regression).
  - [x] 7.7 `docker build .` — deferred to Task 8 (no Dockerfile change in this story so build risk is zero).

- [ ] **Task 8 — Integration smoke on 10.10.10.207** (deploy-time acceptance — operator-VPS Task, deferred to deploy)
  - [ ] 8.1 Deploy the branch to 10.10.10.207 staging.
  - [ ] 8.2 Re-run `bootstrap.yml` to install the new chmod tasks; confirm DB mode 600 + parent mode 700 via `docker compose exec tts-service stat -c '%a' /var/lib/comadre/registry.db` and `... /var/lib/comadre`.
  - [ ] 8.3 Run `ansible-playbook health.yml` → exits 0.
  - [ ] 8.4 Verify the new `Backup cron` row appears in `docker compose exec tts-service comadre-keys health`.
  - [ ] 8.5 Drift-then-recover drill (AC17): chmod the DB to 644, verify health.yml fails with the corrective hint, chmod back to 600, verify health.yml passes.
  - [ ] 8.6 UFW drift drill: `sudo ufw allow 5432/tcp`, verify health.yml fails, `sudo ufw delete allow 5432/tcp`, verify health.yml passes.
  - [ ] 8.7 Multi-replica scaling: edit `compose.yaml`'s `deploy.replicas` from 1 to 2, `docker compose up -d`, verify both replicas come healthy, verify `comadre-keys cache-status` shows 2 replicas, verify `health.yml` still passes (the assertions are replica-agnostic).
  - [ ] 8.8 Scale back: `deploy.replicas: 1`, `docker compose up -d`, verify single replica, `health.yml` passes.
  - [ ] 8.9 Crontab drift drill: `crontab -e`, comment out the `comadre-keys-backup` line, verify `health.yml` fails with the corrective hint, restore the line, verify `health.yml` passes.

## Dev Notes

### Design decisions

**Why delegate DB-state probes to `comadre-keys health --format json` instead of re-implementing them at the ansible layer.** The CLI is the single source of truth for DB-state checks. Re-implementing the probes in YAML would create two parallel implementations of the same logic — drift between them is inevitable. The CLI's exit-7-on-warn/fail contract (Story 3.4) is the ansible-layer's bridge: the playbook captures stdout, parses JSON, asserts on `is_healthy` AND surfaces every failing check in the failure message. Operators who want detailed output run `comadre-keys health` directly inside the container; operators who want a single boolean run `health.yml`.

**Why ALSO add backstop assertions for DB perms and parent dir perms at the ansible layer.** Two reasons:
1. The epic AC3 explicitly names "DB file permissions (fail if not 0600)" — naming the specific assertion at the ansible layer makes the playbook self-evidently AC-fulfilling without requiring the reader to also read `keys/health.py::_check_db_path`. Auditability matters for FR52's "operator can verify".
2. Defense-in-depth — if the in-container CLI ever has a bug (e.g. `_check_db_path` regresses to always returning `ok`), the ansible-layer chmod assertion catches the drift independently.
The cost is ~12 lines of YAML; the benefit is auditability + redundancy.

**Why the new `Backup cron` row in `comadre-keys health` instead of consuming the marker only at the ansible layer.** The marker file already exists on disk (Story 4.3 §3.4). The forward-compat path Story 4.3 explicitly noted is "Story 4.4 (or a future hardening story) will add the consuming health row" — closing the loop in 4.4 means the in-container CLI gives operators the same fail-fast signal whether they run `comadre-keys health` directly or `ansible-playbook health.yml`. Symmetry between the two surfaces is the value; without the row, a future operator running just the in-container CLI gets a different (looser) is_healthy aggregate than one running the ansible playbook.

**Why the chmod in `bootstrap.yml` is "belt-and-braces" rather than the primary enforcement mechanism.** The Python connection layer (`keys/db.py::_chmod_0600` + `get_connection`) is the runtime safety net — it fires on every `comadre-keys` CLI invocation, every cron-driven sweep, every API-replica lifespan startup. The ansible-layer chmod fires once per `bootstrap.yml` re-run. Together they form a layered defence:
- Bootstrap-time misconfiguration (e.g. operator runs `chmod 644` between deploys) → caught by Python on next CLI invocation OR by ansible on next bootstrap re-run.
- Runtime drift (e.g. supply-chain attack alters the file post-install) → caught by Python on the next connection.
- Audit trail — `bootstrap.yml` reads as a complete deploy spec without requiring the reader to also read Python source.
Removing either layer would weaken the contract; both layers are intentional.

**Why `health.yml` doesn't run as a cron itself.** Two reasons:
1. The playbook's value is operator-actionable: when it fails, the operator sees the exit code AND the fail_msg AND can run the corrective command. A cron-driven invocation losing the failure context (output goes to syslog or `/dev/null`) defeats the purpose.
2. Operators integrating into monitoring will want their own integration shape — a Slack notification, a PagerDuty event, a CI step. Story 4.4 ships the assertion playbook; the operator picks the integration. The deploy-guide subsection (§6) recommends a few patterns but doesn't impose any.

**Why the UFW rule check uses `length <= 6` instead of `length == 6` or `length == 3`.** UFW's `status` output duplicates each rule for IPv4 and IPv6 by default — a single `ufw allow 22/tcp` produces two ALLOW lines (`22/tcp ALLOW Anywhere` + `22/tcp (v6) ALLOW Anywhere (v6)`). On a deployment that disables IPv6 entirely, only the v4 lines appear (count = 3). The `<= 6` upper bound captures both modes without false-failing on the IPv6-disabled case. The lower-bound assertion (`length >= 1` per port) ensures each required port is present.

**Why `health.yml` does not assert UFW deny incoming + allow outgoing defaults.** The epic AC3 specifically calls for "UFW rules unchanged (22/80/443 only)" — the rule set, not the defaults. The defaults are set by `bootstrap.yml`'s "[UFW] Default deny incoming" + "[UFW] Default allow outgoing" tasks; if either drifts, UFW becomes effectively open OR effectively closed, both of which would surface as connectivity failures observable elsewhere. Keeping the assertion focused on the rule set matches the AC literally and avoids over-broad assertions that might false-fail in edge cases (e.g. an operator who deliberately runs `ufw default deny outgoing` on a tightened deployment).

**Why no new env var for the marker path.** The marker path derives mechanically from `KEY_REGISTRY_DB_PATH` (`{db_path}.backup-cron-installed`). Hard-coding the suffix in `_check_backup_cron_marker` and computing the full path in `collect_health_report` keeps configuration surface minimal. Operators who want to override the path can monkeypatch in tests or pass `backup_cron_marker_path=...` explicitly to `collect_health_report`; no production override path is needed because the bootstrap playbook hardcodes the same convention on the write side.

### Import-graph placement

- `src/comadre/keys/health.py` (Story 4.4 extension): adds one new helper `_check_backup_cron_marker` and extends `collect_health_report` with one defaulted parameter. No new module-level imports. Reuses `_marker_parse` (existing internal helper). Touches lines: helper insertion (~50 lines new), `collect_health_report` signature + checks-tuple insertion (~10 lines modified).
- `src/comadre/keys/cli/commands/system.py`: untouched. The `health_cmd` invocation of `collect_health_report` uses keyword args; the new defaulted parameter doesn't require any update at the call site.
- `src/comadre/` outside `keys/health.py`: **untouched** (grep-invariant per AC15).
- `deploy/ansible/playbooks/health.yml`: rewritten in place. Existing diagnostic surface preserved as informational pre-checks; new content is the assertion chain. The play structure (one play, single host group `comadre_vps`) is unchanged.
- `deploy/ansible/playbooks/bootstrap.yml`: extended with three new tasks (file-wait + DB-chmod + parent-chmod). Idempotent re-run is preserved.
- `tests/test_keys_db_multi_replica.py`: new file, three test functions, follows the existing `test_keys_db.py` style.

### Why the marker-derived path matters for portability

The new `Backup cron` row's marker path is `{KEY_REGISTRY_DB_PATH}.backup-cron-installed`. This string is **not** a magic constant; it derives mechanically from the configured DB path, and it MUST stay in lockstep with what `bootstrap.yml` writes (`~/comadre/data/keys/registry.db.backup-cron-installed` on the host, mapped to `/var/lib/comadre/registry.db.backup-cron-installed` inside the container via the named volume). If a future operator changes `KEY_REGISTRY_DB_PATH` without also re-running `bootstrap.yml` (which would write the marker at the new path), the `Backup cron` row will report `Not installed` indefinitely. The corrective is the same as for the `Cron` (suspension-sweep) row: re-run `bootstrap.yml`. Operators who customise the DB path are already expected to re-bootstrap; this is a known surface, not a new gotcha.

### Test-flake avoidance

- **Clock seams:** `_check_backup_cron_marker` does not use `_utcnow` — its severity is determined entirely by the marker file's existence and content. No clock-related flake surface.
- **Filesystem races:** the marker stat happens once; there's no glob → stat race like the one Story 4.3's review caught for `_check_last_backup`. The `Path.exists()` + `Path.read_text()` sequence is not atomic, but the failure mode (`FileNotFoundError` between exists() and read_text()) yields an `OSError` caught explicitly. No defensive-OSError-swallow is needed because the marker is written once at bootstrap and only removed at cleanup.
- **YAML idempotency:** the rewritten `health.yml` uses `changed_when: false` on every `command:` task, ensuring `--check` mode is also a no-op (NFR32).
- **Multi-replica test determinism:** the regression test uses two connections in one process, deterministic by construction. The cross-process scenario is exercised in Task 8 (VPS smoke), which is operator-driven and not subject to CI flake.

### Project Structure Notes

- **Alignment with unified project structure (paths, modules, naming)**
  - Marker file naming: `{db_path}.backup-cron-installed` (matches the pattern reserved by Story 3.4 for the suspension-sweep marker, extended by Story 4.3 for the backup cron).
  - New helper naming: `_check_backup_cron_marker` (mirrors `_check_cron_marker` exactly).
  - New row label: `Backup cron` (parallel to `Cron`).
  - New ansible task naming: `[FS] Enforce 0600 ...`, `[FS] Assert DB file mode is 0600`, `[Cron] Assert comadre-daily-suspension is installed`, `[UFW] Assert UFW is active` — same `[Section] Verb description` shape as the existing tasks across the playbook suite.
  - New test module naming: `tests/test_keys_db_multi_replica.py` (follows the `tests/test_<module>_<feature>.py` convention).

- **Detected conflicts or variances (with rationale)**
  - The chmod tasks in `bootstrap.yml` go through `docker compose exec` rather than ansible's native `file:` module. Rationale: the registry path is inside a named Docker volume, not a host bind mount; native `file:` cannot reach the in-container path without resorting to `docker volume inspect`-derived host paths. Documented inline in the playbook header comment.
  - `health.yml` uses `command:` modules with `changed_when: false` rather than the `community.docker.docker_compose_v2_exec` module for some delegations. Rationale: the `command:` form is idempotent (`changed_when: false`), the docker-compose-v2 module's exec-shape is verbose for one-line shell commands, and the `cmd: docker compose -f ~/comadre/compose.yaml exec ...` invocation matches the existing `health.yml` pattern (lines 39-42 of the current file). Stays consistent with the playbook's existing conventions.

### Testing standards

- Python tests (`_check_backup_cron_marker`, integration into `collect_health_report`, multi-replica safety): use `tmp_path` for isolation; explicit close in `try/finally` for SQLite connections; reuse the existing `get_connection` + `_apply_migrations` plumbing.
- Ansible playbook tests: integration-smoke only on 10.10.10.207 (Task 8). Unit-testing the inline shell would require `molecule` — out of scope, matches Story 4.3's pattern.
- Multi-replica cross-process testing: deferred to Task 8 (VPS smoke). Within-process two-connection testing is in `test_keys_db_multi_replica.py` and exercises the WAL contract sufficient for AC14 acceptance.

### Deferred work to flag at story close

- **Per-replica explicit identification in `comadre-keys health`.** The `Auth cache` row already aggregates across replicas via `cache-status`. `health` could surface a "Replica count: N" row for direct visibility, but the multi-replica state is already discoverable via `docker compose ps tts-service` + `cache-status`. Adding a row would duplicate signal; deferred unless an operator UX gap emerges.
- **Cross-replica DB-mode drift detection.** The chmod assertions check the file mode from one container's view — but the host filesystem has its own mode (the named volume's mountpoint). A drift between in-container view and host view is theoretically possible (rare: only on bind-mount + selinux scenarios); the in-container check is the operationally relevant one because the FastAPI process and the CLI both see the in-container path. Defer until a real bind-mount-mode-drift incident surfaces.
- **`health.yml` integration into CI.** Story 4.5x (CI non-regression suite) is the natural home — boot a docker-compose-spun-up Comadre, run `ansible-playbook health.yml`, assert exit 0. Wire-up is one shell step; deferred to 4.5x rather than landing in 4.4 to keep the story focused.
- **Marker-file cron_tz vs runtime BILLING_TIMEZONE drift detection.** Surfaced as a deferred item in Story 3.4's review — the suspension-sweep marker reports cron_tz but doesn't compare against the runtime env var. The new backup-cron marker has the same shape; the same drift-detection gap applies. Deferred to a future "config drift" health check that cross-validates the two TZs.
- **`health.yml` summary output as JSON.** Currently human-readable debug. A future operator who wants to consume the playbook output programmatically (Slack, PagerDuty, etc.) would benefit from a `--extra-vars output_format=json` switch. Deferred until a real consumer materialises.
- **Replica scaling beyond 2.** AC14's regression test uses two connections in one process; Task 8 scales `compose.yaml`'s `deploy.replicas` to 2 then back to 1. Higher replica counts (4, 8) are not exercised — the WAL contract is symmetric in N, so there's no theoretical reason 4+ replicas would behave differently, but a real-world saturation test (10 replicas, sustained writes from each) is deferred until a deployment with that scale exists.
- **Helper container for the chmod tasks instead of `docker compose exec`.** When `tts-service` is briefly unavailable (e.g. during a `docker compose restart`), the chmod tasks would fail. Pattern from `bootstrap.yml:227-251` (helper alpine container with the volume mounted) would isolate the chmod from service liveness. Deferred — the chmod tasks run AFTER `[TTS] Build image and start service` and AFTER the lifespan-wait poll, so the service is guaranteed running at the chmod moment. Only relevant if a future operator splits bootstrap into multiple plays.

### References

- Epic 4 Story 4.4 scope — `_bmad-output/planning-artifacts/epics.md:849-876`
- FR42 (file permissions) — `_bmad-output/planning-artifacts/prd.md` (FR42 cluster)
- FR44 (multi-replica safety) — `_bmad-output/planning-artifacts/prd.md` (FR44 cluster)
- FR52 (health.yml exit code) — `_bmad-output/planning-artifacts/prd.md` (FR52 cluster)
- NFR13 (DB file 0600) — `_bmad-output/planning-artifacts/prd.md` (NFR13)
- NFR29 (multi-replica without corruption) — `_bmad-output/planning-artifacts/prd.md` (NFR29)
- NFR32 (Ansible idempotency) — covered by `changed_when: false` discipline.
- Architecture `health.yml` extension — `_bmad-output/planning-artifacts/architecture.md:255` (`reports monetization status, DB file permissions, cron liveness, last backup timestamp`).
- Architecture multi-replica safety — `_bmad-output/planning-artifacts/architecture.md:50, 440, 628-633`.
- Architecture `bootstrap.yml` 0600 + 0700 mention — `_bmad-output/planning-artifacts/architecture.md:253, 752`.
- Story 1.1 `_chmod_0600` + `get_connection` — `src/comadre/keys/db.py:261-331`.
- Story 2.1 per-replica `app.state.auth_cache` — `src/comadre/keys/cache.py`, `src/comadre/main.py`.
- Story 3.3 cron template + marker write — `deploy/ansible/playbooks/bootstrap.yml:326-353`.
- Story 3.4 health JSON contract — `src/comadre/keys/cli/commands/system.py::health_cmd`, exit 7 on warn/fail.
- Story 3.4 `_check_cron_marker` template — `src/comadre/keys/health.py:341-386`.
- Story 4.3 backup cron + marker — `deploy/ansible/playbooks/bootstrap.yml:355-382`.
- Story 4.3 backup-cron marker reservation — `_bmad-output/implementation-artifacts/4-3-backup-restore-playbooks.md:293, 886-889` ("Marker file is written by bootstrap.yml ... Story 4.3 does NOT add a new ``Backup cron`` row to ``health`` ... A future Story 4.x — or this 4.4 spec — adds the consuming health row").
- Existing diagnostic `health.yml` — `deploy/ansible/playbooks/health.yml` (full file, ~190 lines, rewritten in this story).
- Existing `bootstrap.yml` — `deploy/ansible/playbooks/bootstrap.yml` (full file).
- CLAUDE.md "comadre-keys health --format json exits 7" gotcha — project root `CLAUDE.md`.
- CLAUDE.md "Suspension sweep predicate uses strict ..." gotcha — project root `CLAUDE.md` (companion gotcha that motivated the marker-file pattern).
- `compose.yaml` named-volume + replicas — `compose.yaml:35-71`.

## Questions for Operator (please confirm before dev-story)

> All questions have recommended answers. In auto-mode, apply the recommended answer; if any run hits a disagreement, reopen as a deferred-work entry.

1. **Delegate DB-state probes to in-container CLI vs re-implement in YAML.** Recommended: **delegate to `comadre-keys health --format json` AND add explicit ansible-layer backstops for DB perms + parent perms.** Rationale: single source of truth for DB-state probes (CLI), with redundant assertions on the perms specifically called out in the epic AC. Re-implementing every check at the ansible layer creates drift surface; delegating without the perms backstop would miss the AC's explicit naming of file permissions.

2. **`Backup cron` row in `comadre-keys health` — add now or defer.** Recommended: **add now (Story 4.4)**. Rationale: Story 4.3 wrote the marker file with explicit forward-compat for "Story 4.x adds the consuming row"; closing the loop in 4.4 keeps the in-container CLI signal symmetric with the ansible-layer assertion. Operators running just the CLI get the same is_healthy aggregate as those running the playbook.

3. **`health.yml` UFW assertion — strict equality vs ≤ 6 upper bound.** Recommended: **upper bound `≤ 6` (3 ports × {v4, v6})**. Rationale: UFW's IPv4/IPv6 dup behaviour varies across distros and IPv6-disabled deployments; an `== 6` assertion would false-fail on IPv4-only hosts. Lower bound (`each port ≥ 1` ALLOW line) ensures completeness; upper bound (`total ≤ 6`) catches deviation.

4. **`health.yml` should fail on absent backup archive vs only stale (`warn`).** Recommended: **fail on absent (`< 1` archive)**. Rationale: epic AC3 says "last backup output exists" — the literal reading is "≥ 1 archive must exist". Stale-vs-fresh is the in-container CLI's `Last backup` row's concern (Story 4.3 contract: warn on > 48 h old); the ansible-layer probe asserts only on existence to avoid double-counting the freshness signal.

5. **`bootstrap.yml` chmod tasks via `docker exec` vs helper container.** Recommended: **`docker exec`**. Rationale: the chmod tasks run AFTER `[TTS] Build image and start service` and AFTER the lifespan-wait poll — `tts-service` is guaranteed running. Helper container (alpine + volume mount) would be more robust against service-stopped scenarios but is unnecessary in the bootstrap-time invocation order.

6. **Multi-replica regression test — within-process two-connection vs cross-process spawn.** Recommended: **within-process two-connection**. Rationale: SQLite's WAL contract is symmetric across the process boundary; the within-process test is deterministic, fast, and exercises the same WAL surface. Cross-process testing requires `subprocess.Popen` orchestration that's flake-prone in CI; defer cross-process to Task 8 VPS smoke.

7. **Belt-and-braces chmod redundancy — keep both Python and ansible enforcement vs consolidate.** Recommended: **keep both**. Rationale: Python protects runtime drift (post-deploy supply-chain attack, accidental `chmod`); ansible protects bootstrap-time misconfiguration AND makes the playbook self-evidently AC-fulfilling. Removing either layer weakens the contract.

8. **`health.yml` cadence recommendation in docs — nightly cron, weekly hands-on, per-PR CI, all of the above.** Recommended: **all of the above, mention each as an option**. Rationale: operator preferences vary; the playbook's value is the exit-code contract, not any specific integration. Documenting multiple patterns lets operators pick the one that matches their existing alerting cadence.

9. **Health.yml summary output — human-readable debug only vs structured JSON option.** Recommended: **human-readable debug for 4.4, defer JSON output to a future story** if a programmatic consumer materialises. Rationale: the playbook's primary consumer is the operator running it interactively or via cron + logger; structured output is a YAGNI surface in MVP.

10. **Keep diagnostic surfaces (container running, /health, disk, voices) in `health.yml` vs slim down to assertions only.** Recommended: **keep them as informational pre-checks**. Rationale: the diagnostic surfaces are operationally useful and removing them would regress the existing `health.yml` UX. The new assertion chain runs alongside; operators get both. Header comment in the playbook explains the structure.

## Dev Agent Record

### Agent Model Used

claude-opus-4-7 (Claude Code dev-story workflow, 2026-04-20).

### Debug Log References

No HALT conditions encountered. Single notable iteration: `ansible-lint` initially flagged a `yaml[line-length]` violation on the `[Backup] Count backup archives` task — fixed by switching the inline `cmd:` literal to a YAML folded-block scalar (`>-`).

### Completion Notes List

- **Tasks 1, 2, 5 (ansible work):** `health.yml` rewritten as an assertion playbook (DB-state CLI delegation + DB perms backstops + cron asserts + backup-archive count + UFW rule check + diagnostic block + summary). `bootstrap.yml` extended with `[FS] Wait for service lifespan to materialise registry.db` (`retries: 30, delay: 2`) → `[FS] Enforce 0600 on registry.db (and WAL/SHM sidecars)` → `[FS] Enforce 0700 on registry parent directory`. Both playbooks are belt-and-braces on top of the existing Python connection-layer enforcement (`keys/db.py::_chmod_0600` + `get_connection`).
- **Task 3 (Python — `keys/health.py`):** new `_check_backup_cron_marker` helper modelled exactly on `_check_cron_marker` (label = `Backup cron`, mirrors the warn-on-missing / warn-on-unparseable / ok-on-well-formed shape, parses `schedule` + `cron_tz` + `retention_days`). `collect_health_report` gained a defaulted `backup_cron_marker_path: str | None = None` parameter (default-derives `{db_path}.backup-cron-installed`); the new check sits between `cron_check` (suspension-sweep) and `_check_last_backup` in the checks tuple. CLI call site untouched (kwargs).
- **Tasks 4, 5 (Python tests):** added `TestBackupCronMarker` (5 cases) and `TestCollectHealthReportBackupCronWiring` (4 cases) to `test_keys_health.py`; added `TestBackupCronRow` (3 cases) to `test_keys_cli_health.py`; created `tests/test_keys_db_multi_replica.py` (3 cases — concurrent read/write under WAL, journal mode invariant, 0600/0700 enforcement on first connection). Backfilled `_write_backup_cron_marker` helper in both health test modules and seeded the marker in every healthy-path test that previously expected `is_healthy=True`. Bumped `len(report.checks)` and the canonical labels list from 8 → 9 (perf test included).
- **Task 6 (docs):** `docs/deployment-guide.md` gained an "Operational health checks — `ansible-playbook health.yml`" subsection between "Backup & restore" and "Firewall (UFW)". `docs/configuration-reference.md` extended the `{KEY_REGISTRY_DB_PATH}.backup-cron-installed` row to reflect that the in-container CLI now reads it via the new `Backup cron` health row. `CLAUDE.md` gained three new gotchas (health.yml exit-code contract; bootstrap.yml chmod belt-and-braces rationale; two cron-installed rows in `comadre-keys health`). `README.md` got a new feature bullet for the operational health assertion playbook.
- **Task 7 (quality gate):** `ruff check`, `mypy src/`, `pytest` (1414 passed), `pre-commit run --all-files`, `ansible-lint health.yml bootstrap.yml` — all green. Grep invariants verified.
- **Task 8 deferred:** VPS smoke is operator-VPS work per the story's own scoping. Hand off to deploy.

### File List

**Modified — application code (1 file):**

- `src/comadre/keys/health.py` — added `_check_backup_cron_marker` helper + extended `collect_health_report` signature with `backup_cron_marker_path: str | None = None` (default-derived from `db_path`).

**Modified — tests (2 files):**

- `tests/test_keys_health.py` — imported `_check_backup_cron_marker`; added `_write_backup_cron_marker` helper; backfilled marker seeding in `TestFullHealthyReport::test_collect_full_healthy_report` + `TestAggregation::test_is_healthy_true_with_info_only` + `TestPerformance::test_collect_under_500ms_for_1k_customers`; added `TestBackupCronMarker` class (5 cases) and `TestCollectHealthReportBackupCronWiring` class (4 cases); bumped `len(report.checks)` from 8 → 9.
- `tests/test_keys_cli_health.py` — added `_write_backup_cron_marker` helper; seeded it in `TestTableMode::test_healthy_exits_0_renders_panel`, `TestJsonMode::test_healthy_exits_0`, `TestJsonMode::test_payload_structure_is_stable`, `TestMarkerRendering::test_marker_schedule_rendered_verbatim`; bumped `len(payload["checks"])` from 8 → 9 and the canonical labels set; added `TestBackupCronRow` class (3 cases).

**Added — tests (1 file):**

- `tests/test_keys_db_multi_replica.py` — three new test functions for FR44 / NFR29: concurrent read/write under WAL, WAL mode on every `get_connection`, 0700 parent + 0600 DB after first connection.

**Modified — ansible (2 files):**

- `deploy/ansible/playbooks/health.yml` — full rewrite from diagnostic-only to assertion playbook. Prereq + tts-service running assert; in-container `comadre-keys health --format json` delegation + assert; DB mode + parent dir mode backstops; `comadre-daily-suspension` + `comadre-keys-backup` cron asserts; backup-archive count assert; UFW active + rule-set assert; replica count info; preserved diagnostic block (Caddy state, /health endpoint, disk, audio volume, Qwen3 voice presence); summary banner.
- `deploy/ansible/playbooks/bootstrap.yml` — added three new tasks (`[FS] Wait for service lifespan to materialise registry.db`, `[FS] Enforce 0600 on registry.db (and WAL/SHM sidecars)`, `[FS] Enforce 0700 on registry parent directory`) inserted between `[TTS] Build image and start service` and the `# Cron Jobs` block.

**Modified — docs (4 files):**

- `docs/deployment-guide.md` — added "Operational health checks — `ansible-playbook health.yml`" subsection (~50 lines).
- `docs/configuration-reference.md` — extended the `{KEY_REGISTRY_DB_PATH}.backup-cron-installed` auxiliary-file row to reflect the new `Backup cron` health row.
- `CLAUDE.md` — added three new "Non-Obvious Gotchas" (`ansible-playbook health.yml` contract; `bootstrap.yml` chmod belt-and-braces; two cron-installed rows in `comadre-keys health`).
- `README.md` — new feature bullet "Operational health assertion playbook".

**Modified — sprint tracking (2 files):**

- `_bmad-output/implementation-artifacts/sprint-status.yaml` — `4-4-operational-safety-file-permissions`: `ready-for-dev` → `in-progress` → `review`.
- `_bmad-output/implementation-artifacts/4-4-operational-safety-file-permissions.md` — Status flipped + Tasks 1–7 ticked + Dev Agent Record populated.

### Change Log

- 2026-04-20 — Story 4.4 spec drafted from epic AC (FR42, FR44, FR52), architecture invariants (`health.yml` rewrite scope, `_chmod_0600` discipline, multi-replica WAL), and the Story 3.3/3.4/4.3 templates. Status: ready-for-dev.
- 2026-04-20 — Story 4.4 implementation landed: `_check_backup_cron_marker` + `Backup cron` health row in `keys/health.py`; `health.yml` rewritten as an assertion playbook with DB-state CLI delegation, DB perms backstops, cron asserts, backup-archive count, UFW rule check; `bootstrap.yml` extended with file-permission enforcement (lifespan-wait + 0600/0700 chmods); multi-replica safety regression test (`tests/test_keys_db_multi_replica.py`); docs updates across `docs/deployment-guide.md`, `docs/configuration-reference.md`, `CLAUDE.md`, `README.md`. 1414 tests pass; ruff/mypy/pre-commit/ansible-lint green. Status: review.
- 2026-04-20 — Code review landed 12 patches (2 blockers + 10 high/medium): (1) UFW assertion hardened to a strict whitelist — zero ALLOW lines outside `{22,80,443}/tcp` instead of loose `<= 6` upper bound; (2) bootstrap chmod split into required main-DB chmod + best-effort `[ -e $f ]`-guarded sidecar chmod (no more blanket `; true`); (3) health.yml asserts non-empty `cli_health.stdout` before `from_json`; (4) `_check_backup_cron_marker` coerces `retention_days` to a positive int and warns on non-integer / non-positive values (tests updated to expect int, plus new coverage for `banana`/`-7`/`0`/directory-at-marker-path); (5) UFW status read forces `LC_ALL=C` for PT_BR hosts; (6) `ALLOW FWD` (Docker) rules filtered out of the whitelist count alongside `ALLOW OUT`; (7) crontab grep now ignores commented-out entries; (8) multi-replica concurrency test uses `BEGIN IMMEDIATE` — reads during an open writer transaction + second-writer-must-block + post-commit-visibility; (9) lifespan-wait budget bumped 60 s → 300 s to absorb first-boot model downloads; (10) `test_journal_mode_is_wal_on_every_fresh_get_connection` uses a fresh DB path per iteration; (11) new `is_file()` guard on the marker path; (12) UFW status probe tries unprivileged first, falls back to `become: true` only when the unprivileged read fails. 1417 tests pass (1414 → 1417 after three new retention-validation + directory-marker tests); ruff/mypy/pre-commit/ansible-lint green.

### Review Findings

_Adversarial code review 2026-04-20 — Blind Hunter + Edge Case Hunter + Acceptance Auditor. Acceptance Auditor: all 17 ACs met (AC16/AC17 VPS-dependent). Two blockers surfaced by Blind Hunter + Edge Case concurrence; ten additional patches; eleven deferred; several noise items dismissed._

- [x] [Review][Patch] **UFW ALLOW assertion is strictly weaker than the claimed "exactly 22/80/443" invariant** [`deploy/ansible/playbooks/health.yml:353-372`] — upper-bound `length <= 6` + per-port `>= 1` passes an attack like `sudo ufw allow 3306/tcp` (total 4 lines, MySQL publicly exposed, health.yml green). Fix: reject any ALLOW line not matching the whitelist: `ufw_allow_lines | reject('search', '\\b(22|80|443)/tcp\\b') | list | length == 0`. **[Blocker]**
- [x] [Review][Patch] **`bash -c '... 2>/dev/null; true'` in bootstrap chmod masks every failure, not just missing WAL/SHM sidecars** [`deploy/ansible/playbooks/bootstrap.yml:320-330`] — main DB chmod failure (wrong uid, immutable flag, readonly volume, typo) silently reports `changed_when: false` → green. Fix: split into required `chmod 600 /var/lib/comadre/registry.db` (no `; true`) and tolerant `[ -e /var/lib/comadre/registry.db-wal ] && chmod 600 /var/lib/comadre/registry.db-wal` sidecar steps. **[Blocker]**
- [x] [Review][Patch] **`cli_health.stdout | from_json` crashes the playbook when CLI output is empty or non-JSON** [`deploy/ansible/playbooks/health.yml:193-197`] — when `comadre-keys health` segfaults / OOMs / is killed, `failed_when: false` absorbs the rc but `from_json` on empty string aborts with a Jinja "Cannot parse" traceback instead of the intended `fail_msg`. Fix: guard the parse with `when: cli_health.stdout | default('') | length > 0`, and add a prior assertion that stdout is non-empty with its own corrective hint.
- [x] [Review][Patch] **`retention_days` accepted as any string; non-numeric/negative/huge silently rendered as `ok`** [`src/comadre/keys/health.py:431-453`, `tests/test_keys_health.py:950-954`, `tests/test_keys_cli_health.py:827-834`] — `retention_days=banana` yields `value="... retention=bananad"` with severity `ok`. Tests pin `retention_days` as string `"14"`, locking in the bug. Fix: `int(retention)` in try/except; warn on non-positive / non-integer; update tests to expect coerced int.
- [x] [Review][Patch] **UFW `Status: active` assertion locale-sensitive** [`deploy/ansible/playbooks/health.yml:325-344`] — Brazilian-Portuguese host (`LC_ALL=pt_BR.UTF-8`) renders `Status: ativo`, assertion fires "UFW is not active" with misleading `ufw enable` hint. Fix: `cmd: bash -lc 'LC_ALL=C ufw status'` to force English output.
- [x] [Review][Patch] **UFW `ALLOW FWD` (Docker-integration) rules not filtered** [`deploy/ansible/playbooks/health.yml:333-340`] — reject filter only excludes `ALLOW OUT`; Docker's forwarded rules (`<port>/tcp ALLOW FWD Anywhere`) count toward the `<= 6` cap, false-failing on Docker+UFW hosts. Fix: switch to positive select (`select('match', '.*ALLOW\\s+IN\\b.*')`) or explicitly reject `ALLOW FWD` alongside `ALLOW OUT`.
- [x] [Review][Patch] **Crontab grep catches commented-out entries** [`deploy/ansible/playbooks/health.yml:272-289`] — a line like `# comadre-keys-backup 0 2 * * * …` passes the literal-string-containment assertion while the cron is effectively disabled. Fix: filter comments first, e.g. `crontab_check.stdout_lines | reject('match', '^\\s*#') | join('\\n')` before the `in` check.
- [x] [Review][Patch] **Lifespan-wait 60 s budget too short on first-boot** [`deploy/ansible/playbooks/bootstrap.yml:311-318`] — Kokoro + Qwen3 models auto-download on first startup (CLAUDE.md gotcha). Model downloads from HuggingFace regularly exceed 60 s on slow links, exhausting `retries: 30, delay: 2` and aborting `bootstrap.yml` before the chmod tasks run. Fix: bump to `retries: 150, delay: 2` (5 min) or `retries: 300, delay: 2` (10 min), matching the realistic first-boot model-download window.
- [x] [Review][Patch] **Multi-replica "concurrent" R/W test never crosses a transaction boundary** [`tests/test_keys_db_multi_replica.py:33-98`] — writes commit via `with conn_a:` BEFORE reads begin on `conn_b`; the scenario would pass under `journal_mode=DELETE` too. Fix: `conn_a.execute("BEGIN IMMEDIATE")` + write (uncommitted) + read from B (must return pre-write snapshot, no SQLITE_BUSY) + commit A + read from B again (sees new row).
- [x] [Review][Patch] **`test_journal_mode_is_wal_on_every_get_connection` tautological on a persistent DB** [`tests/test_keys_db_multi_replica.py:101-110`] — WAL is a persistent file-level attribute; iterations 2-3 pass even if `get_connection` silently dropped the `PRAGMA journal_mode = WAL`. Fix: loop over `tmp_path / f"registry-{i}.db"` so each iteration exercises a fresh file.
- [x] [Review][Patch] **Marker at non-file path (directory/symlink/FIFO) emits misleading hint** [`src/comadre/keys/health.py:400-420`] — `IsADirectoryError` at `read_text()` → "Marker present but unparseable" + detail "re-run `bootstrap.yml`", but `ansible.builtin.copy` fails on a dir destination. FIFO blocks indefinitely (no timeout). Fix: `if not marker_path.is_file(): return HealthCheck(..., detail="marker path is not a regular file — rm it and re-run bootstrap.yml")` before the `read_text()` call.
- [x] [Review][Patch] **UFW task `become: true` contradicts spec UX-DR "No `ansible_become_password` required"** [`deploy/ansible/playbooks/health.yml:325-331`] — spec UX-DR says probes are unprivileged with sudo fallback only on permission denial; impl uses `become: true` unconditionally. Operator running without `-e ansible_become_password` sees the UFW assertion fail with a misleading "not active" message when the real cause is missing sudo. Fix: try `ufw status` unprivileged first; on rc != 0 or missing-permission indicator, retry with `become: true`. (Alternative: document `-e ansible_become_password=...` as required in the deploy-guide.)
- [x] [Review][Defer] **Positional consumers of `report.checks` now misaligned (tuple 8 → 9)** [`src/comadre/keys/health.py:656-674`] — deferred, architecture explicitly says "order is documented but not asserted"; no in-tree consumer breaks, external scripts pinning `checks[6]` do. Consider `report.by_label("...")` in a future hardening pass.
- [x] [Review][Defer] **`parsed=False` data-field ambiguity — same value for parse-failed and missing-required-key** [`src/comadre/keys/health.py:414, 423, 434, 444`] — deferred, cosmetic for JSON consumers; distinguish in a future iteration via `data={"parsed": True, "missing_keys": [...]}`.
- [x] [Review][Defer] **API inconsistency: `cron_marker_path` required, `backup_cron_marker_path` auto-derives** [`src/comadre/keys/health.py:618-637`] — deferred, both are siblings of the DB path; either both should default or both should be required. No functional impact.
- [x] [Review][Defer] **Missing symmetry tests for independent `Cron`/`Backup cron` `is_healthy` flips** [`tests/test_keys_cli_health.py::TestBackupCronRow`] — deferred, CLAUDE.md asserts "flip `is_healthy=False` independently" but only the Backup-cron-missing case is tested; the mirror (suspension-cron-missing while Backup-cron-OK) is covered transitively via pre-existing TestCronMarker but not explicitly. Non-blocking.
- [x] [Review][Defer] **Summary `[Summary] All checks passed` banner hardcodes "DB mode: 600" etc. rather than referencing registered facts** [`deploy/ansible/playbooks/health.yml:486-549`] — deferred, if an assertion threshold ever changes, the summary will silently lie. Cosmetic.
- [x] [Review][Defer] **UFW rules with interface specifiers (`allow in on eth0`) would false-fail** [`deploy/ansible/playbooks/health.yml:353-362`] — deferred, spec defines expected set as plain `22/80/443 ALLOW` without interface scoping; operators using interface-scoped rules are off-spec.
- [x] [Review][Defer] **Backup-archive assertion counts 0-byte / truncated files as "present"** [`deploy/ansible/playbooks/health.yml:296-314`] — deferred, a crashed `backup-keys.yml` mid-`openssl enc` leaves an empty tarball that passes count-based assertion. Freshness/size sanity is a future-iteration concern; operationally caught by the restore drill in Story 4.3.
- [x] [Review][Defer] **`crontab -l` rc=127 (cron binary missing) vs rc=1 (empty crontab) indistinguishable** [`deploy/ansible/playbooks/health.yml:263-268`] — deferred, Ubuntu hosts ship cron by default; a missing binary is an exotic deployment scenario. Future improvement: split `failed_when` by rc.
- [x] [Review][Defer] **No post-chmod verification in bootstrap** [`deploy/ansible/playbooks/bootstrap.yml:320-335`] — deferred, kernel-silent-ignore scenarios (9p / WSL shared volumes / certain NFS) would surface at `health.yml` time instead of bootstrap time. Loop closes; bootstrap-time feedback is nice-to-have.
- [x] [Review][Defer] **Multi-replica test is in-process only; cross-process scenario deferred to Task 8 VPS smoke** [`tests/test_keys_db_multi_replica.py` whole file] — deferred, spec-sanctioned. File name sets an expectation of cross-process that the test doesn't fulfil; either rename to `test_keys_db_connection_contract.py` or spawn a `subprocess` child.
- [x] [Review][Defer] **Test for missing backup cron marker only exercises JSON exit 7; table-mode warn path untested** [`tests/test_keys_cli_health.py::TestBackupCronRow::test_missing_marker_flips_json_to_exit_7`] — deferred, table mode `exit 0 on warn` is contract-documented in CLAUDE.md; regression risk is low since shared `HealthReport` renders both.

_Dismissed as noise (not persisted):_ broken-symlink marker cosmetic; BOM/CRLF markers (bootstrap.yml writes markers, not operators); FIFO at marker path (operator self-shooting); embedded tabs in values (shared parser handles); Story 4.5x/4.6 references in playbook (spec traceability); `b"\x00"` as `tax_id_encrypted` test fixture; `docker compose exec` missing `set -euo pipefail` (superseded by chmod split above); UFW regex `\\bNN/tcp\\b` word-boundary quoting (works); IPv4-only host count (handled by `<=6`); `[Diag] Check audio volume` failure (`ignore_errors: true`); spec §7 stale grep counts (Dev Agent Record acknowledges each); AC15/16/17 VPS-dependent (spec-sanctioned deferrals); `partition("=")` on schedule values (works); empty `retention_days=` value (handled by `not retention`); chmod-as-non-root-container-user (runtime artifact, not a spec violation); `is_healthy=True rc=0` masks non-health JSON (`--format json` contract excludes extraneous output).
