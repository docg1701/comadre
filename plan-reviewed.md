# Implementation Plan — Eliminate Local File Dependencies in Ansible Playbooks

## Review Findings

### What was correct

- The plan accurately identifies both `lookup('file', ...)` sites in `restore-keys.yml` and correctly models the `backup-keys.yml` precedent.
- `restore-stage.sh` requires no body changes; its env-var-driven design makes it directly executable when baked into the image.
- The `slurp` + `b64decode` approach for `restore-swap.sh` is the right tool — the script must execute inside an alpine helper container, not on the VPS host, so `ansible.builtin.script` is unsuitable.
- `no_log`, `environment:`/`BACKUP_PASSPHRASE`, and `changed_when` semantics are preserved correctly in the stage task.
- The Dockerfile addition uses a direct `COPY` (not `--from=builder`), matching the existing `backup-keys.sh` block exactly.
- `deploy-voices.yml` localhost dependency is correctly classified as accepted architectural risk.

### What changed in this review

1. **Fixed dependency mapping error** — The original plan stated "Task 3 depends on Task 6". Task 3 (swap `slurp` implementation) does not depend on Task 6 (acceptance/idempotency verification). The only ordering constraint is that the `slurp` task must appear *before* the `docker_container` task that consumes `swap_script_raw` inside the same playbook — an internal file-order requirement, not a cross-task dependency. The Dependencies section has been corrected.
2. **Noted stale comment in current `restore-keys.yml`** — The existing comment above the swap task describes a base64 round-trip (`sh -c "$(cat ... | base64 -d)"`) that the actual code does not perform; the current code uses `lookup('file', ...)` directly. The plan's proposed comment replacement fixes this discrepancy; the review makes the mismatch explicit.
3. **Minor path-expansion note** — `slurp` uses `~/comadre/...`, consistent with the rest of the playbook (`stat`, `command chdir`). This is correct because `slurp` expands `~` on the remote host via `os.path.expanduser`.

### Blockers

None. The plan is safe to execute.

---

## Goal

Remove `lookup('file', playbook_dir + '/../scripts/...')` from `restore-keys.yml`
so the disaster-recovery playbook does not depend on the control node's
filesystem. The VPS-side clone at `~/comadre` (created by `bootstrap.yml`)
becomes the single source of truth for all deploy scripts.

---

## Context & Design Decisions

### What changed in `backup-keys.yml` (the precedent)

`backup-keys.yml` previously used the same `lookup('file', ...)` pattern (the
`_backup_script` jinja blob). It was fixed in the B16 patch by baking
`backup-keys.sh` into the Docker image as `/usr/local/bin/comadre-keys-backup`.
Today `backup-keys.yml` calls the in-image binary directly:

```yaml
ansible.builtin.command:
  cmd: docker compose exec -T -e BACKUP_PASSPHRASE ... tts-service comadre-keys-backup
```

The same approach applies to `restore-stage.sh`. For `restore-swap.sh` the
situation differs — it runs in an alpine helper container, not the tts-service
image, so we use `slurp` from the VPS-side clone instead.

### Why `deploy-voices.yml` is different

Voice files (`.npy`, `.wav`) are operator-owned binary assets, not repo-tracked
infrastructure scripts. They are not versioned in Git, have no default content,
and vary per deployment. The localhost dependency here is **accepted risk** — a
voice-deployment playbook whose input is files on the operator's machine is
semantically correct. Fixing it would require building object-storage
integration or a voice-registry service, which is out of scope. This plan
documents the risk and leaves the playbook unchanged.

---

## Tasks

### 1. Bake `restore-stage.sh` into the Docker image

- **File**: `Dockerfile`
- **Changes**: After the existing `COPY deploy/ansible/scripts/backup-keys.sh` block
  (line 79), add:

  ```dockerfile
  COPY deploy/ansible/scripts/restore-stage.sh /usr/local/bin/comadre-keys-restore-stage
  RUN chmod +x /usr/local/bin/comadre-keys-restore-stage
  ```

- **File**: `deploy/ansible/scripts/restore-stage.sh`
- **Changes**: No changes needed. The script already reads its inputs from
  environment variables (`BACKUP_FILE`, `BACKUP_PASSPHRASE`,
  `KEY_REGISTRY_DB_PATH`, `KEY_REGISTRY_ENCRYPTION_KEY`). It will work as-is
  when invoked as a binary inside the container.
- **Acceptance**: Rebuild the image with `docker compose build tts-service` —
  verify `/usr/local/bin/comadre-keys-restore-stage` exists and is executable.

### 2. Replace `lookup('file', ...)` for restore-stage in `restore-keys.yml`

- **File**: `deploy/ansible/playbooks/restore-keys.yml`
- **Changes**: Replace the `[Stage] Decrypt + untar + integrity-check` task
  (currently a `ansible.builtin.shell` with `stdin: "{{ lookup('file', ...) }}"`)
  with an `ansible.builtin.command` that calls the in-image binary directly,
  mirroring the `backup-keys.yml` pattern:

  **Before** (current, lines ~107–127):

  ```yaml
  - name: "[Stage] Decrypt + untar + integrity-check"
    ansible.builtin.shell:
      cmd: >-
        docker compose exec -T
        -e BACKUP_FILE={{ backup_file | quote }}
        -e BACKUP_PASSPHRASE
        tts-service bash -s
      chdir: "~/comadre"
      stdin: "{{ lookup('file', playbook_dir + '/../scripts/restore-stage.sh') }}"
    environment:
      BACKUP_PASSPHRASE: "{{ backup_passphrase }}"
    register: stage_result
    changed_when: true
    no_log: true
  ```

  **After**:

  ```yaml
  - name: "[Stage] Decrypt + untar + integrity-check"
    ansible.builtin.command:
      cmd: >-
        docker compose exec -T
        -e BACKUP_FILE={{ backup_file | quote }}
        -e BACKUP_PASSPHRASE
        tts-service comadre-keys-restore-stage
      chdir: "~/comadre"
    environment:
      BACKUP_PASSPHRASE: "{{ backup_passphrase }}"
    register: stage_result
    changed_when: true
    no_log: true
  ```

  Key differences:
  - `ansible.builtin.shell` → `ansible.builtin.command` (no shell interpolation needed)
  - Remove `stdin:` line entirely
  - Replace `bash -s` with `comadre-keys-restore-stage` (the baked binary)
  - Keep `-e BACKUP_FILE={{ backup_file | quote }}` because `BACKUP_FILE` is
    operator-supplied and must stay env-var-passed per F4
  - The `environment:` block (`BACKUP_PASSPHRASE`) is preserved exactly — it
    keeps the passphrase out of argv via name-only `-e BACKUP_PASSPHRASE`

- **Acceptance**: Run `restore-keys.yml` against a staging VPS with a known
  backup archive. Verify the stage step completes, `stage_result.stdout`
  contains `stage OK`, and `KEY_DIVERGES` / `KEY_MATCHES` detection still works.

### 3. Replace `lookup('file', ...)` for restore-swap in `restore-keys.yml`

- **File**: `deploy/ansible/playbooks/restore-keys.yml`
- **Changes**: The restore-swap script runs in an alpine helper container
  (NOT the tts-service image). We cannot bake it into the tts-service image.
  Instead, use `ansible.builtin.slurp` to read it from the VPS-side clone.

  Add a new task **before** the `[Restore] Swap DB file via helper container`
  block:

  ```yaml
  - name: "[Restore] Read swap script from VPS clone"
    ansible.builtin.slurp:
      src: "~/comadre/deploy/ansible/scripts/restore-swap.sh"
    register: swap_script_raw
  ```

  Then, inside the `[Restore] Create helper container for volume access` task,
  replace `"{{ lookup('file', playbook_dir + '/../scripts/restore-swap.sh') }}"`
  with `"{{ swap_script_raw['content'] | b64decode }}"`:

  **Before** (current, lines ~176–192):

  ```yaml
  - name: "[Restore] Create helper container for volume access"
    community.docker.docker_container:
      name: comadre-restore-helper
      image: alpine:3.21
      command:
        - "sh"
        - "-c"
        - "{{ lookup('file', playbook_dir + '/../scripts/restore-swap.sh') }}"
      volumes:
        - "comadre-registry:/var/lib/comadre"
      state: started
      auto_remove: false
  ```

  **After**:

  ```yaml
  - name: "[Restore] Create helper container for volume access"
    community.docker.docker_container:
      name: comadre-restore-helper
      image: alpine:3.21
      command:
        - "sh"
        - "-c"
        - "{{ swap_script_raw['content'] | b64decode }}"
      volumes:
        - "comadre-registry:/var/lib/comadre"
      state: started
      auto_remove: false
  ```

- **Why `slurp` instead of `ansible.builtin.script`**: `ansible.builtin.script`
  copies the script to the target, runs it, then deletes it. But the script
  needs to execute **inside** the alpine Docker container, not directly on the
  VPS host. `slurp` reads the file content into memory, then the
  `docker_container` module passes it as the `command` argument to the container
  entrypoint (`sh -c`).

- **Acceptance**: Run `restore-keys.yml` end-to-end against a staging VPS.
  Verify the helper container starts, exits 0, and the DB swap succeeds
  (`test -f /var/lib/comadre/registry.db` inside the container after restore).

### 4. Update comment block about F6 in `restore-keys.yml`

- **File**: `deploy/ansible/playbooks/restore-keys.yml`
- **Changes**: The existing comment block above the stage task references "F6 —
  script body lives in deploy/ansible/scripts/restore-stage.sh". Update it to
  reference the baked binary path instead, matching the `backup-keys.yml` B16
  documentation style.

  Replace the comment (lines ~104–110):

  ```yaml
  # F6 — script body lives in deploy/ansible/scripts/restore-stage.sh;
  # piped into ``bash -s`` inside the container. ``$BACKUP_FILE`` is
  # passed via -e so the script reads it via shell parameter expansion
  # (F4 — no raw jinja interpolation into a shell command).
  ```

  With:

  ```yaml
  # B16 — restore-stage script is baked into the tts-service image at
  # ``/usr/local/bin/comadre-keys-restore-stage`` (Dockerfile). The
  # binary is invoked directly via ``docker compose exec``, same pattern
  # as ``comadre-keys-backup`` in backup-keys.yml. ``$BACKUP_FILE`` is
  # passed via -e so the script reads it via shell parameter expansion
  # (F4 — no raw jinja interpolation into a shell command).
  ```

- **Also update** the comment above the swap helper container (lines ~176–179).
  The current comment incorrectly describes a base64 round-trip that the code
  does not actually perform (the current code uses `lookup('file', ...)`
  directly). Replace it with an accurate description:

  ```yaml
  # The script body is read from the VPS-side clone via ``slurp``
  # (task ``[Restore] Read swap script from VPS clone`` above) and
  # passed through ``b64decode`` into the container's ``sh -c``.
  # This eliminates the control-node file dependency — the VPS-side
  # repo clone (maintained by bootstrap.yml) is the single source of
  # truth for deploy scripts.
  ```

- **Acceptance**: Visual review — comments are accurate and reference correct
  file paths/binary names.

### 5. Add documentation note to `deploy-voices.yml`

- **File**: `deploy/ansible/playbooks/deploy-voices.yml`
- **Changes**: Add a note at the top of the playbook documenting the accepted
  risk:

  ```yaml
  # NOTE: This playbook reads voice files from the control node's filesystem
  # (``voices_local_dir`` with ``delegate_to: localhost``). This is the
  # design intent — voice files (.npy, .wav) are operator-owned binary assets
  # not tracked in Git, not deployment infrastructure scripts. If the control
  # node is lost, voice files must be recovered from the operator's backups.
  # For a fully machine-independent workflow, store voice files in object
  # storage (S3) and add a download task before the staging step.
  ```

- **Acceptance**: Visual review — comment is present and clear.

### 6. Verify `restore-keys.yml` still works idempotently

- **File**: `deploy/ansible/playbooks/restore-keys.yml`
- **Acceptance**: Run the modified playbook twice against the same staging VPS
  with the same backup file. Both runs succeed. Second run is not a no-op
  (re-restoring the same archive is expected to succeed and produce the same
  DB state), but all tasks complete green.

### 7. Verify `no_log` and secrecy invariants

- **File**: `deploy/ansible/playbooks/restore-keys.yml`
- **Acceptance**:
  - `no_log: true` is still present on the `[Stage] Decrypt ...` task.
  - `BACKUP_PASSPHRASE` is forwarded via name-only `-e BACKUP_PASSPHRASE` form
    (no `=value` — value comes from `environment:` block).
  - `backup_passphrase` is never interpolated into a shell string or `cmd:`
    field (only passed via `environment:`).
  - The `[Stage] Detect archived-vs-live key divergence` task still reads
    `stage_result.stdout` correctly (the binary outputs `KEY_DIVERGES` /
    `KEY_MATCHES` / `ARCHIVED_KEY=` to stdout, unchanged from the script).

---

## Files to Modify

| File | Change |
|---|---|
| `Dockerfile` | Add `COPY` + `RUN chmod` for `restore-stage.sh` → `/usr/local/bin/comadre-keys-restore-stage` |
| `deploy/ansible/playbooks/restore-keys.yml` | Replace `lookup('file', ...)` for stage (→ in-image binary) and swap (→ `slurp` + `b64decode`); update F6/B16 comments |
| `deploy/ansible/playbooks/deploy-voices.yml` | Add documentation comment about accepted localhost risk |

## New Files

None. All scripts already exist at `deploy/ansible/scripts/`.

---

## Dependencies

- Task 2 depends on Task 1 (binary must be baked into image before playbook can
  invoke it).
- Task 4 depends on Tasks 2 and 3 (comment updates reference the new task shapes).
- Tasks 5, 6, and 7 are independent and can be done in any order after Tasks
  1–4 are complete.

> **Internal ordering constraint for Task 3**: The `[Restore] Read swap script
> from VPS clone` `slurp` task must be placed **before** the `[Restore] Swap DB
> file via helper container` block in the playbook file, because the
> `docker_container` task references `swap_script_raw`. If placed after, the
> playbook fails with an undefined-variable error.

---

## Risks

1. **`slurp` requires Python on the target**: `ansible.builtin.slurp` uses
   Python on the remote host to read the file and base64-encode it. VPS hosts
   (Ubuntu) have Python pre-installed. The playbook already has `gather_facts:
   false` — `slurp` does not require facts gathering. **Validated**: works.

2. **`restore-stage.sh` is large and has inline heredocs**: The script is ~110
   lines with embedded Python heredocs. When invoked as `bash -s` via stdin
   (old approach), heredocs work fine. When invoked as a binary
   (`/usr/local/bin/comadre-keys-restore-stage`), heredocs still work because
   the script is a self-contained file with a shebang. **No change needed to
   the script body.**

3. **`restore-swap.sh` is tiny and trivial**: The swap script is 14 lines of
   simple shell (`rm`, `mv`, `chmod`, `rm -rf`). There is no benefit to baking
   it into the Docker image (it needs alpine, not the tts-service Python image).
   The `slurp` approach is the correct one for this case.

4. **Image rebuild required**: After Task 1, any VPS running the old image must
   be redeployed (`docker compose build && docker compose up -d`) before
   `restore-keys.yml` can use the new binary. This is the same constraint that
   `backup-keys.sh` → `comadre-keys-backup` already had. The `bootstrap.yml` /
   `update.yml` playbooks already handle image rebuild on deploy.

5. **Comment-only changes to `deploy-voices.yml`**: The accepted-risk approach
   for voices is pragmatic but means the problem described in any local-file-
   dependency tracking is not fully resolved for that playbook. This is an
   explicit architectural decision, not an oversight.

6. **`slurp` path and `docker_container` `command` semantics**: `slurp` reads the
   file into memory; `b64decode` reproduces the exact string that `lookup('file',
   ...)` would have yielded. The `docker_container` module already receives a
   multiline string in its `command` list today (via `lookup`); switching to
   `slurp` does not change the string shape and therefore does not introduce
   new quoting risk.

7. **`--from=builder` is not needed**: The Dockerfile change uses direct `COPY`
   from the build context, identical to the existing `backup-keys.sh` block.
   Only the `uv` binary uses `--from=ghcr.io/astral-sh/uv:0.8.3`; deployment
   scripts are copied from the repo, not from another image stage.
