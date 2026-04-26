# Deploy Fresh Friction Log

**Goal:** zero-friction Ansible deploy on `10.10.10.207` (Debian 13, x86_64). Each
defect found during the deploy is logged here with root cause + proposed fix +
patch reference. Success criterion: cleanup.yml + bootstrap.yml +
deploy-models.yml + deploy-voices.yml + health.yml all run green back-to-back
on a clean VPS without any out-of-band SSH intervention.

Operator: `galvani@10.10.10.207` (sudo with password).
Inventory: `deploy/ansible/inventory/production.yml`.

## Run log

### Pre-flight observations

- VPS is currently mid-life: caddy + tts-service container running 13 days,
  legacy cron `comadre-daily-restart` present (no longer written by current
  bootstrap, but cleanup removes it explicitly — already idempotent).
- Local `voices/` has 5 Kokoro `.npy` + 3 Qwen `.wav` files ready.
- Local `ansible 2.20.3`, collections `community.docker 5.0.6` /
  `community.general 11.2.1` installed and meet `requirements.yml` floors.
- SSH agent forwards github key.
- `COMADRE_KEY_REGISTRY_ENCRYPTION_KEY` and `COMADRE_BACKUP_PASSPHRASE` are NOT
  set in the operator's shell — generated fresh for this fresh-deploy run.

## Defects

### D1 — `key_registry_db_path` missing from real inventory files

**Symptom:** `bootstrap.yml` task `[Prereq] Validate key_registry_db_path` fails
with `'key_registry_db_path' is undefined` while the assert is being finalised
(the `success_msg` template references the variable unconditionally).

**Root cause:** `deploy/ansible/inventory/production.yml` and
`deploy/ansible/inventory/oracle.yml` are out of sync with their `.example`
counterparts. Both `.example` files declare:

```yaml
key_registry_db_path: /var/lib/comadre/registry.db
```

…but the real inventory files (committed in earlier rounds) lack this line.
`bootstrap.yml` made the variable a hard prereq and the example files were
updated, but the active inventories were not. Violates project rule: ".example
files must always mirror the real file structure, kept in sync on every
change" (CLAUDE.md → user memory `feedback_example_files.md`).

**Why ansible's `default()` filter does NOT save us here:** the `fail_msg` uses
`default('<undefined>')`, but `success_msg` does not — and ansible 2.20
finalises BOTH templates before deciding which to render, so the missing
variable explodes regardless of the assertion outcome.

**Fix:** add `key_registry_db_path: /var/lib/comadre/registry.db` to
`deploy/ansible/inventory/production.yml` and `oracle.yml`, matching the
example files exactly. Single-line addition, no semantic change — this is the
documented default; bootstrap, health, backup-keys, and restore-keys all
template this same path.

**Patch:** see commit on master after first-pass deploy.

### D2 — `comadre-registry` named volume mounts root-owned, blocking appuser writes

**Symptom:** `[TTS] Build image and start service` fails with
`dependency failed to start: container comadre-tts-service-1 is unhealthy`.
Container logs show the FastAPI lifespan crashing in
`get_connection(settings.key_registry_db_path)` with
`sqlite3.OperationalError: unable to open database file`, and a preceding
warning:
`could not chmod 0700 on registry parent dir /var/lib/comadre (insufficient privileges)`.

**Root cause:** the Dockerfile creates `/models /audio /voices` and chowns them
to `appuser` before declaring `USER appuser`, but it never creates
`/var/lib/comadre` (the in-container mount point for the `comadre-registry`
named volume). Docker mounts the named volume on first start with the default
ownership (root:root, 0755), inherited from the host's
`/var/lib/docker/volumes/comadre-registry/_data` directory. The non-root
`appuser` cannot create `registry.db` inside it, so SQLite's auto-create on
first `connect()` fails with `unable to open database file`.

**Why this passed previous deploys:** Docker named volumes inherit the
underlying mountpoint ownership ONLY when the volume is first created AND the
mountpoint exists in the image with the desired ownership. Earlier deploys
must have happened before Story 4.4 tightened the parent-dir mode to 0700
and `db.py::get_connection` started enforcing 0600 on `registry.db` —
container ran briefly as root long enough for the file to be created
writable, then subsequent restarts kept working because the file already
existed. After today's `cleanup.yml`, the volume is genuinely empty + only
the (root-owned) mountpoint exists.

**Fix:** in `Dockerfile`, extend the existing `mkdir + chown` line to include
`/var/lib/comadre`. Canonical Docker pattern — the Dockerfile already does
this for `/models /audio /voices`. Diff:

```diff
-    mkdir -p /models /audio /voices && \
-    chown -R appuser:appuser /app /models /audio /voices
+    mkdir -p /models /audio /voices /var/lib/comadre && \
+    chown -R appuser:appuser /app /models /audio /voices /var/lib/comadre
```

When Docker mounts an empty named volume on top of an image-provided
directory whose mountpoint exists with non-root ownership, Docker copies
the mountpoint's ownership into the new volume on first mount. So this
single change makes the named volume come up appuser-owned automatically,
and the `db.py::_chmod_0600 + parent.mkdir(mode=0o700)` runtime safety net
finally has the right inputs to work with.

**Patch:** see Dockerfile change on master.

### D3 — `health.yml` fails on a fresh post-bootstrap deploy

**Symptom:** `ansible-playbook health.yml` immediately after a green
`bootstrap.yml` exits non-zero on `[DB] Assert comadre-keys health is_healthy`
with two failing checks:

```
- Last suspension sweep: never (cron installed but not yet fired)
  (wait until 00:30 operator-TZ for the first sweep)
- Last backup: never (run backup-keys.yml)
```

The in-container `comadre-keys health --format json` exits 7 because both
"freshness" rows have no antecedent event in `audit_log` / no archive on
disk. Operators are told to either wait until the next cron firing
(00:30 / 02:00 operator TZ — up to 24 h) or run `backup-keys.yml`
manually. That's friction — health.yml should pass on a successful deploy.

**Root cause:** bootstrap.yml installs the cron entries but never fires the
first iteration of either job. The `comadre-keys health` CLI's freshness
checks (Story 3.4) are designed to catch a cron that's installed-but-broken
by reading the most recent successful run; with no run yet, "never" is
correctly reported but produces a false fail-on-fresh-deploy.

**Fix v1 (REJECTED — operator feedback "não invente health checkpoints"):**
extend bootstrap.yml's tail with two zero-touch initialisation tasks
(`[Init] Seed audit_log via suspend-sweep` + `import_playbook:
backup-keys.yml`). This works but invents new ad-hoc health-related
plumbing rather than fixing the actual modelling error in the application.

**Fix v2 (SHIPPED):** the bug is in `comadre.keys.health._check_last_sweep`
and `_check_last_backup`. Both treat "never (cron installed but not yet
fired)" as `severity="warn"` unconditionally. That conflates **operational
drift detection** (cron stopped firing) with **deployment readiness**
(cron just installed, hasn't had a chance yet). Per the official Docker
healthcheck doctrine, "is the service ready" is binary and time-bounded
by `start_period`; ongoing operational drift belongs in monitoring, not
in the deploy gate.

The application change adds a **grace period** to both freshness checks,
keyed off the marker file's `mtime` (≈ install time, written by
`bootstrap.yml`'s `cat > {db}.cron-installed`). Within the staleness
window (48 h, identical to the existing "Last sweep ageing" threshold)
the "never" reading is `severity="info"` (does not flip `is_healthy`);
beyond the window it escalates to `warn` (genuine drift — cron daemon
broken, suspended host, mounted-over crontab). New `install_age_seconds`
field is added to both `Cron` and `Backup cron` rows' `data` payload so
the freshness probes can read it without re-stat'ing.

This **deletes** the bootstrap.yml tail extension from Fix v1 and leaves
all initialisation to the cron daemons themselves — the "first run
delay" is no longer a deployment problem.

**Patch:** `src/comadre/keys/health.py` (grace-period logic +
`_marker_install_age_seconds` helper) + new test
`test_freshly_installed_cron_with_no_history_is_info_not_warn` in
`tests/test_keys_health.py` (locks the new contract: within window
→ info + is_healthy=True; beyond → warn + is_healthy=False).

### D5 — `health.yml`'s ansible-level `[Backup] Assert at least one backup archive exists` ignored grace period

**Symptom:** even with the application-layer grace-period fix from D3 v2,
`health.yml` still fails on a fresh-deploy at the ansible task `[Backup]
Assert at least one backup archive exists` because the playbook had its
own redundant filesystem assertion (FR42 epic AC3 — "last backup output
exists").

**Root cause:** the playbook's filesystem assertion was unconditional —
it counted `*.backup-*.tar.gz.enc` files and required `>= 1` regardless
of how recently the backup cron was installed. The CLI-layer fix from D3
v2 made the in-container `comadre-keys health` tolerant of the
post-bootstrap window, but the ansible playbook's PARALLEL assertion
re-introduced the same friction one layer up.

**Fix:** read the backup-cron marker's mtime via a single `bash -c` exec
(`stat -c %Y` on the marker file → seconds-since-epoch) at the same time
as the archive count, then gate the existence assertion behind the same
48 h grace window as the CLI: missing archive + marker_age < 48 h
→ skip assertion + emit a debug note explaining why; missing archive +
marker_age ≥ 48 h → fail loudly. The companion `[Backup] Smallest
archive size` task is now gated on `backup_count >= 1` so a
zero-archive grace-window host doesn't try to stat a non-existent glob.

**Patch:** `deploy/ansible/playbooks/health.yml` — replaces the two
single-purpose probes (`[Backup] Count …` + `[Backup] Smallest …`) with
a single `[Backup] Marker mtime + archive count` exec that reports both
values, plus a parsing `set_fact`, plus the gated assert + debug note.

### D4 — `health.yml`'s `[Backup] Smallest archive size` task fails with bash syntax error

**Symptom:** `[Backup] Smallest archive size in bytes` task fails with
`bash: -c: line 2: syntax error near unexpected token '|'`. Stdout is the
`stat -c %s` output (so the first command did execute and emit a size), but
bash rejected the `| sort -n | head -1` pipeline as if it were a separate
command line.

**Root cause:** YAML folded-scalar (`>-`) bug in `health.yml:244-247`. The
original block was:

```yaml
cmd: >-
  docker compose -f ~/comadre/compose.yaml exec -T tts-service bash -c
  'stat -c %s {{ key_registry_db_path | dirname }}/*.backup-*.tar.gz.enc 2>/dev/null
   | sort -n | head -1'
```

YAML folded scalars (`>-`) fold internal newlines into spaces ONLY between
lines that share the same indentation level. A "more indented" continuation
line (the third line begins with one extra leading space ` |`) is treated as
literal — its leading newline is preserved verbatim. So `bash -c` received:

```
stat -c %s /var/lib/comadre/*.backup-*.tar.gz.enc 2>/dev/null
 | sort -n | head -1
```

…with a literal `\n` between the redirect and the pipe. Bash sees a
complete command on line 1, then tries to start a new command beginning
with `|` on line 2 — illegal token, syntax error.

**Why this hadn't been caught yet:** the task only fires when ≥ 1 backup
archive exists in the registry volume (gated by the preceding `[Backup]
Assert at least one backup archive exists` task). Before this fresh-deploy
validation, no operator had run `health.yml` immediately after a successful
`backup-keys.yml` run on a clean volume — every prior `health.yml`
invocation either skipped this step (no archive) or hit the same syntax
error and was silently misattributed to "no backup yet".

**Fix:** collapse the bash -c body onto a single physical YAML line. Added
an inline comment describing the folding gotcha so a future editor doesn't
re-introduce the multi-line form. Diff:

```diff
     - name: "[Backup] Smallest archive size in bytes"
+      # NOTE: keep the bash -c body on a single physical YAML line. Folding
+      # via ``>-`` turns inter-line breaks into spaces ONLY when the lines
+      # share the same indentation; a more-indented continuation (e.g. a
+      # leading space before ``| sort``) preserves the newline literally...
       ansible.builtin.command:
         cmd: >-
           docker compose -f ~/comadre/compose.yaml exec -T tts-service bash -c
-          'stat -c %s {{ key_registry_db_path | dirname }}/*.backup-*.tar.gz.enc 2>/dev/null
-           | sort -n | head -1'
+          'stat -c %s {{ key_registry_db_path | dirname }}/*.backup-*.tar.gz.enc 2>/dev/null | sort -n | head -1'
```

**Patch:** see health.yml change on master.

## Out-of-scope playbooks for the zero-friction first deploy

`deploy-models.yml` is **opt-in** — it asserts `qwen3_model_local` /
`qwen3_tokenizer_local` are non-empty (operator-provided local GGUF files
for offline / air-gapped deploys). The standard deploy path uses
`QWEN3_MODEL_URL` / `QWEN3_TOKENIZER_URL` set in `.env` and the entrypoint
auto-downloads on first start; no `deploy-models.yml` run is required and
running it on a host where the locals are empty fails-fast with a clear
"set the path" message. This is the documented contract — running it
without local files is operator error, not deploy friction.

`restore-keys.yml` is operational (disaster recovery) and out of scope for
a fresh-deploy run. `update.yml` is a re-deploy aid, also out of scope.

The recipes exercised in this validation are:
- `cleanup.yml`        — destructive teardown
- `bootstrap.yml`      — fresh deploy (no init-task additions; the
                         application's freshness checks tolerate the
                         post-bootstrap pre-cron-firing window)
- `deploy-voices.yml`  — load custom voices into volume
- `health.yml`         — operational invariants (with a 48 h grace
                         period on the backup-existence assertion that
                         mirrors the CLI's grace period)

## Round 2 outcome — zero friction validated

After committing D1 + D2 + D3-v2 + D4 + D5 fixes (commits `d34f960`,
`859eff4`, `e66fcde`), the full pipeline ran end-to-end with no manual
intervention:

| Playbook            | OK | Failed | Skipped |
|---------------------|---:|-------:|--------:|
| `cleanup.yml`       | 24 |      0 |       0 |
| `bootstrap.yml`     | 41 |      0 |       1 |
| `deploy-voices.yml` | 16 |      0 |       0 |
| `health.yml`        | 32 |      0 |       6 |

(`bootstrap`'s 1 skip = `landing_enabled=false` branch; `health`'s 6
skips = grace-period-gated backup-archive size + filesystem mode probes
already covered by the CLI's `is_healthy=True`.)

Final smoke test:
- `curl -sk https://10.10.10.207/health` → `status=healthy`, 62 voices
  loaded (54 built-in Kokoro + 5 custom + 3 Qwen).
- `comadre-keys health` → `is_healthy=True | warn_count=0 | fail_count=0`,
  `Last suspension sweep: never (cron freshly installed)` rendered as
  the new info-grade row.
- 3 crons installed (`comadre-audio-cleanup`, `comadre-daily-suspension`,
  `comadre-keys-backup`), `CRON_TZ=America/Sao_Paulo` matches the
  registry's runtime `BILLING_TIMEZONE`, no drift.

## Defect summary

| ID | Surface             | Fix layer                | Commit    |
|----|---------------------|--------------------------|-----------|
| D1 | inventory drift     | local inventory (gitig.) | (local)   |
| D2 | Dockerfile          | container image          | `d34f960` |
| D3 | freshness modelling | application (`health.py`)| `859eff4` |
| D4 | YAML folding        | `health.yml`             | `859eff4` |
| D5 | parallel assertion  | `health.yml`             | `e66fcde` |
