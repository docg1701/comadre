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
