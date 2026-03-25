# Story 3.3: Health, Cleanup & Model Deploy Playbooks

Status: done

## Story

As a **DevOps operator**,
I want to diagnose service issues, fully decommission CUMADRE when needed, and pre-deploy Qwen3 GGUF models via Ansible,
So that I can troubleshoot at 2 AM, leave zero artifacts when retiring the service, and avoid relying on slow first-run auto-downloads for 1.6 GB model files.

## Acceptance Criteria

1. **Given** a running CUMADRE deployment, **When** I run `ansible-playbook playbooks/health.yml -i inventory/production.yml`, **Then** it checks container state, queries the health endpoint, and reports: memory usage, loaded voices, both engine statuses (Kokoro and Qwen3), queue depth, clone configuration status, uptime, disk consumption (including audio volume size), and audio file cleanup cron status. **And** runs entirely unprivileged.

2. **Given** the health playbook detects high memory (> 5 GB), **When** I read the output, **Then** it warns about memory pressure and suggests restarting the container and verifying the daily restart cron.

3. **Given** the health playbook finds the container not running, **When** I read the output, **Then** it reports the container state and suggests checking `docker compose logs` and restarting.

4. **Given** the health playbook detects audio file disk usage above threshold, **When** I read the output, **Then** it warns about disk pressure and suggests verifying the audio cleanup cron is active (expected: every 6h, deleting files older than 24h).

5. **Given** the health playbook checks engine status, **When** Qwen3 reports as disabled, **Then** the output explains that clone reference WAV may be missing and suggests verifying CLONE_REFERENCE configuration.

6. **Given** a CUMADRE deployment I want to remove, **When** I run `ansible-playbook playbooks/cleanup.yml -i inventory/production.yml`, **Then** it stops containers, removes images, removes all three named volumes (cumadre-models, cumadre-voices, cumadre-audio), removes the ~/cumadre directory, and removes both crontab entries (daily restart and audio cleanup). **And** runs entirely unprivileged.

7. **Given** the cleanup playbook completes, **When** I inspect the VPS, **Then** zero CUMADRE artifacts remain. **And** the `[Summary]` task confirms complete removal.

8. **Given** locally converted Qwen3 GGUF model files on the operator's machine, **When** I run `ansible-playbook playbooks/deploy-models.yml -i inventory/production.yml`, **Then** it copies both `qwen3-tts-0.6b-q8_0.gguf` (~1.3 GB) and `qwen3-tts-tokenizer-f16.gguf` (~325 MB) into the `cumadre-models` Docker volume using the helper container pattern. **And** runs entirely unprivileged.

9. **Given** the deploy-models playbook completes and the service is running, **When** the container starts (or restarts), **Then** `download.py` detects the pre-deployed models and skips auto-download.

10. **Given** the operator has not set `qwen3_model_local` and `qwen3_tokenizer_local` inventory variables, **When** I run `ansible-playbook playbooks/deploy-models.yml`, **Then** it fails with a clear message explaining that local model paths must be configured.

## Tasks / Subtasks

- [x] Task 1: Create `deploy/ansible/playbooks/health.yml` (AC: #1, #2, #3, #4, #5)
  - [x] 1.1 Add prerequisite checks (verify ~/cumadre exists)
  - [x] 1.2 Add container state check via `community.docker.docker_container_info`
  - [x] 1.3 Add health endpoint query via `ansible.builtin.uri` (handle both 200 and 503 gracefully, and connection refused)
  - [x] 1.4 Add disk usage check via `ansible.builtin.command` (`df -h /` and audio volume size)
  - [x] 1.5 Add crontab verification via `ansible.builtin.command` (`crontab -l`)
  - [x] 1.6 Add memory warning when `memory_mb > 5120`
  - [x] 1.7 Add disk pressure warning based on filesystem usage threshold
  - [x] 1.8 Add Qwen3 disabled explanation when engine reports not loaded
  - [x] 1.9 Add `[Summary]` task with full diagnostic report

- [x] Task 2: Create `deploy/ansible/playbooks/cleanup.yml` (AC: #6, #7)
  - [x] 2.1 Add prerequisite check (verify ~/cumadre exists, warn before deletion)
  - [x] 2.2 Stop and remove service via `community.docker.docker_compose_v2` with `state: absent`, `remove_volumes: true`
  - [x] 2.3 Remove Docker images via `community.docker.docker_image` or `ansible.builtin.command`
  - [x] 2.4 Remove both crontab entries (`cumadre-daily-restart` and `cumadre-audio-cleanup`) via `ansible.builtin.cron` with `state: absent`
  - [x] 2.5 Remove ~/cumadre directory via `ansible.builtin.file` with `state: absent`
  - [x] 2.6 Add `[Summary]` task confirming complete removal

- [x] Task 3: Create `deploy/ansible/playbooks/deploy-models.yml` (AC: #8, #9, #10)
  - [x] 3.1 Add prerequisite checks (verify ~/cumadre exists, verify model path variables are set)
  - [x] 3.2 Stage both GGUF files on VPS via `ansible.builtin.copy` to `~/cumadre/deploy/staging/`
  - [x] 3.3 Create helper container with `cumadre-models` volume mounted via `community.docker.docker_container`
  - [x] 3.4 Copy both files into volume at `/models/` via `community.docker.docker_container_copy_into`
  - [x] 3.5 Remove helper container and clean up staging directory
  - [x] 3.6 Add `[Summary]` task confirming model deployment with file sizes
  - [x] 3.7 Add `qwen3_model_local` and `qwen3_tokenizer_local` variables to `deploy/ansible/inventory/production.yml`

- [x] Task 4: Validate all three playbooks (AC: all)
  - [x] 4.1 Run `ansible-playbook --syntax-check` on all three playbooks
  - [x] 4.2 Run `yamllint` on all three playbooks
  - [x] 4.3 Run `ansible-lint` on all three playbooks (production profile)
  - [x] 4.4 Audit: zero `become: true` tasks in all three playbooks
  - [x] 4.5 Audit: all tasks follow `[Component] Action description` naming
  - [x] 4.6 Audit: no paths outside `~/cumadre`
  - [x] 4.7 Verify existing test suite still passes: `uv run pytest`

## Dev Notes

### health.yml — Diagnostic Cascade

The health playbook is a **read-only diagnostic** tool. It must NEVER modify anything. The flow:

1. `[Prereq]` Verify `~/cumadre` directory exists (stat + assert)
2. `[Docker]` Check container state via `community.docker.docker_container_info` (register: `tts_container`)
3. `[Docker]` If container not running → skip to summary with error message (use `when:` conditionals, do NOT fail the play)
4. `[Health]` Query `http://localhost:{{ port }}/health` via `ansible.builtin.uri` — **do NOT use `until` loop** (unlike bootstrap/update, this is a one-shot diagnostic, not a wait-for-healthy poll). Use `status_code: [200, 503]` to accept both healthy and warming_up responses. Also use `ignore_errors: true` to handle connection refused gracefully.
5. `[Disk]` Run `df -h /` to get root filesystem usage (use `ansible.builtin.command`)
6. `[Disk]` Get audio volume size via `docker exec tts-service du -sh /audio` (use `ansible.builtin.command`, handle container-not-running case)
7. `[Cron]` Run `crontab -l` and check for both cron entries (use `ansible.builtin.command`, `ignore_errors: true` — no crontab is a valid state to report)
8. `[Summary]` Comprehensive diagnostic report with warnings

### Health Endpoint Response Format

The `/health` endpoint returns this JSON structure:
```json
{
  "status": "healthy",
  "voices": ["santa", "dora", "alex", "clone", "qwen-female", "qwen-male"],
  "engines": {
    "kokoro": {"loaded": true, "voices": ["santa", "dora", "alex"]},
    "qwen3": {"loaded": true, "model": "q8_0", "clone_configured": true}
  },
  "queue_depth": 0,
  "clone_configured": true,
  "uptime_seconds": 3600,
  "memory_mb": 4200,
  "version": "0.2.0"
}
```

HTTP status codes: 200 = healthy, 503 = warming_up. Connection refused = service not responding.

**Key field paths for Jinja access (via `hc: "{{ health_check.json }}"`):**
- `hc.status` → "healthy" or "warming_up"
- `hc.voices | join(', ')` → voice list
- `hc.engines.kokoro.loaded` → boolean
- `hc.engines.qwen3.loaded` → boolean
- `hc.engines.qwen3.clone_configured` → boolean (inside engines block)
- `hc.clone_configured` → boolean (top-level shortcut)
- `hc.queue_depth` → integer
- `hc.uptime_seconds` → integer
- `hc.memory_mb` → integer (peak RSS)
- `hc.version` → string

### Health Playbook Warning Logic

**Memory pressure (AC #2):**
```yaml
- name: "[Health] Warn on high memory usage"
  when:
    - health_check is defined
    - health_check.json is defined
    - (health_check.json.memory_mb | default(0) | int) > 5120
  ansible.builtin.debug:
    msg: >-
      WARNING: Memory usage is {{ health_check.json.memory_mb }} MB (threshold: 5 GB).
      Consider restarting the container: cd ~/cumadre && docker compose restart
      Verify daily restart cron is active: crontab -l | grep cumadre-daily-restart
```

**Container not running (AC #3):** Use `when: not (tts_container.exists and tts_container.container.State.Running)` to skip health query and show error in summary.

**Disk pressure (AC #4):** Parse `df` output for usage percentage > 80% and warn.

**Qwen3 disabled (AC #5):** Check `hc.engines.qwen3.loaded == false` and suggest checking CLONE_REFERENCE configuration.

### cleanup.yml — Full VPS Wipe

The cleanup playbook **destroys everything**. The flow:

1. `[Prereq]` Verify `~/cumadre` directory exists (stat + assert). If not found, skip to summary reporting "nothing to clean up."
2. `[TTS]` Stop and remove containers + volumes: `community.docker.docker_compose_v2` with `project_src: "~/cumadre"`, `state: absent`, `remove_volumes: true`, `remove_orphans: true`
3. `[Cleanup]` Remove CUMADRE Docker images: use `ansible.builtin.command` with `docker image prune -f --filter label=com.docker.compose.project=cumadre` or list and remove images matching the project
4. `[Cron]` Remove daily restart cron: `ansible.builtin.cron` with `name: "cumadre-daily-restart"`, `state: absent`
5. `[Cron]` Remove audio cleanup cron: `ansible.builtin.cron` with `name: "cumadre-audio-cleanup"`, `state: absent`
6. `[Cleanup]` Remove `~/cumadre` directory: `ansible.builtin.file` with `path: "~/cumadre"`, `state: absent`
7. `[Summary]` Confirm complete removal

### Critical: docker_compose_v2 with state: absent

The `community.docker.docker_compose_v2` module with `state: absent` runs `docker compose down`. Adding `remove_volumes: true` passes `--volumes` to remove named volumes. This is the equivalent of `docker compose down --volumes --remove-orphans`.

**Important:** The `docker_compose_v2` module requires `project_src` to find `compose.yaml`. Since we're removing `~/cumadre` afterward, compose-down MUST happen first.

### Cron Entry Names (Must Match bootstrap.yml Exactly)

The bootstrap playbook creates two cron entries with these exact names:
- `cumadre-daily-restart` — used in `[Cron] Configure daily restart`
- `cumadre-audio-cleanup` — used in `[Cron] Configure audio cleanup every 6 hours`

The cleanup playbook must reference these exact same `name:` values with `state: absent` to remove them. The health playbook should grep `crontab -l` for these names to verify they exist.

### deploy-models.yml — Qwen3 GGUF Pre-deployment

Resolves the deferred gap from Story 3.1 post-review: "Ansible bootstrap playbook does NOT deploy Qwen3 GGUF model files to VPS."

**Why a separate playbook (not in bootstrap.yml):**
- Can be run independently: initial deploy, re-deploy after volume loss, deploy updated quantizations
- bootstrap.yml is already working and complete — adding optional large-file transfers would bloat it
- Models are a one-time operation separate from service lifecycle
- Operator may build GGUF files days after initial bootstrap

**The flow:**

1. `[Prereq]` Verify `~/cumadre` directory exists (stat + assert)
2. `[Prereq]` Validate both model paths are set (`qwen3_model_local` and `qwen3_tokenizer_local` must not be empty)
3. `[Models]` Stage both GGUF files on VPS: `ansible.builtin.copy` from local to `~/cumadre/deploy/staging/`
4. `[Models]` Create helper container: `community.docker.docker_container` with `image: alpine:3.21`, volumes `cumadre-models:/models`, `state: present`
5. `[Models]` Copy TTS model into volume: `community.docker.docker_container_copy_into` to `/models/qwen3-tts-0.6b-q8_0.gguf`
6. `[Models]` Copy tokenizer into volume: `community.docker.docker_container_copy_into` to `/models/qwen3-tts-tokenizer-f16.gguf`
7. `[Models]` Remove helper container: `community.docker.docker_container` with `state: absent`
8. `[Models]` Clean up staging directory: `ansible.builtin.file` with `state: absent`
9. `[Summary]` Report deployed model files and sizes

**Helper container pattern (from bootstrap.yml clone WAV deployment):**

This is the same pattern used for deploying the clone reference WAV in bootstrap.yml:
```yaml
- name: "[Models] Stage GGUF files on VPS"
  ansible.builtin.copy:
    src: "{{ qwen3_model_local }}"
    dest: "~/cumadre/deploy/staging/{{ qwen3_model_local | basename }}"
    mode: "0644"

- name: "[Models] Create helper container for volume access"
  community.docker.docker_container:
    name: cumadre-volume-helper
    image: alpine:3.21
    volumes:
      - "cumadre-models:/models"
    state: present
    auto_remove: false

- name: "[Models] Copy TTS model into models volume"
  community.docker.docker_container_copy_into:
    container: cumadre-volume-helper
    path: "~/cumadre/deploy/staging/qwen3-tts-0.6b-q8_0.gguf"
    container_path: "/models/qwen3-tts-0.6b-q8_0.gguf"
    owner_id: 0
    group_id: 0
    mode: "0644"
```

**Destination filenames must match compose.yaml environment variables exactly:**
- `QWEN3_MODEL_PATH: /models/qwen3-tts-0.6b-q8_0.gguf`
- `QWEN3_TOKENIZER_PATH: /models/qwen3-tts-tokenizer-f16.gguf`

**How download.py skips pre-deployed models (AC #9):**
`ensure_qwen3_models()` in `src/cumadre/download.py` checks `if model.is_file() and tokenizer.is_file()` — if both files exist in the volume, it logs "Qwen3 models already present, skipping download" and returns immediately. No app changes needed.

**Inventory variables to add to `deploy/ansible/inventory/production.yml`:**
```yaml
# Optional: local paths to pre-converted Qwen3 GGUF model files
# See docs/quantizing-qwen3-models.md for conversion procedure
# Leave empty to rely on auto-download via download URLs (slower first startup)
qwen3_model_local: ""
qwen3_tokenizer_local: ""
```

**Model file details (from `docs/quantizing-qwen3-models.md`):**
- `qwen3-tts-0.6b-q8_0.gguf` — ~1.3 GB, TTS transformer + text tokenizer (Q8_0 quantized)
- `qwen3-tts-tokenizer-f16.gguf` — ~325 MB, Vocoder / audio decoder (F16, not quantized)
- Total: ~1.6 GB transferred via SCP (Ansible `copy` module uses SFTP)
- One-time transfer — models persist in `cumadre-models` Docker volume across restarts and updates

### Architecture Patterns to Follow (from bootstrap.yml and update.yml)

- **Play target:** `hosts: cumadre_vps`
- **Task naming:** `[Component] Action description` pattern
- **Health check module:** `ansible.builtin.uri` with `url: "http://localhost:{{ port }}/health"`, `return_content: true`
- **Container info:** `community.docker.docker_container_info` with `name: tts-service`
- **Summary pattern:** `ansible.builtin.debug` with `msg: |` block
- **Variable reuse:** Use inventory variables (`port`, `ansible_host`, `api_key_value`)
- **Gather facts:** `gather_facts: false` (not needed — no apt, no OS detection)
- **Zero privilege escalation:** NO `become: true` in either playbook

### Anti-Patterns to Avoid

- **NO `become: true`** — everything runs as unprivileged VPS user in docker group
- **NO modification in health.yml** — read-only diagnostics only
- **NO `docker-compose` v1 syntax** — use `community.docker.docker_compose_v2` module
- **NO files outside `~/cumadre`** — all paths use `~/cumadre`
- **NO `shell:` when an Ansible module exists** — prefer builtin modules
- **NO hardcoded IPs, ports, or keys** — use inventory variables
- **NO `gather_facts: true`** — not needed
- **NO raw `docker compose` via shell for compose operations** — use `community.docker.docker_compose_v2` module
- **NO failing the play when container is down in health.yml** — gracefully report the state instead

### Previous Story Learnings (from Stories 3.1 and 3.2)

1. **`community.docker.docker_compose_v2`** requires `community.docker >= 3.12.0` (already in `requirements.yml`). Use `project_src: "~/cumadre"`.
2. **`community.docker.docker_container_info`** with `name: tts-service` returns `.exists` and `.container.State.Running` (used in update.yml prereqs).
3. **Health endpoint** uses `ansible.builtin.uri` with `url: "http://localhost:{{ port }}/health"`, `return_content: true`.
4. **Summary** uses `vars: hc: "{{ health_check.json }}"` and `ansible.builtin.debug` with multi-line `msg: |`.
5. **Task names** must follow `[Component] Action description` pattern exactly.
6. **`ansible-lint`** uses production profile; suppress `no-handler` with `# noqa: no-handler` only where justified.
7. **`changed_when: false`** should be used on all `ansible.builtin.command` tasks that are read-only (like `df`, `du`, `crontab -l`).
8. **Container name** is `tts-service` (hardcoded in compose.yaml).
9. **Volume names**: `cumadre-models`, `cumadre-voices`, `cumadre-audio` (defined in compose.yaml).
10. **2 pre-existing test failures** in test_routing.py (subprocess mock issue) confirmed on master — not regressions.

### Deferred Work Resolved by This Story

- **Qwen3 GGUF model deployment via Ansible** (from post-review gap analysis, 2026-03-24): Resolved by `deploy-models.yml` using the helper container pattern to copy pre-converted GGUF files into the `cumadre-models` volume.

### Deferred Work Awareness (NOT in scope)

These items from deferred-work.md are NOT in scope for this story but are relevant context:
- **Port variable coupling** (from 3.2 review): inventory `port` variable could diverge from compose.yaml hardcoded `PORT: '8000'`. The health playbook should use `{{ port }}` from inventory consistently.
- **No rollback on failed rebuild** (from 3.2 review): cleanup.yml does not need rollback — it's intentionally destructive.
- **Synchronous model download blocks async event loop** (from 3.1 review): health endpoint may be unreachable during first-run download. The health playbook's one-shot query with `ignore_errors: true` handles this gracefully.

### Testing Standards

- `ansible-playbook --syntax-check playbooks/health.yml` must pass
- `ansible-playbook --syntax-check playbooks/cleanup.yml` must pass
- `ansible-playbook --syntax-check playbooks/deploy-models.yml` must pass
- `yamllint` must pass on all three playbooks
- `ansible-lint` must pass (production profile, same as bootstrap/update)
- Zero `become: true` tasks (privilege audit)
- All tasks follow `[Component] Action description` naming
- No paths outside `~/cumadre`
- Existing Python test suite must still pass: `uv run pytest` (392+ passed, 11 skipped)

### Project Structure Notes

Three new files and one modified file:
```
deploy/ansible/playbooks/health.yml         # NEW
deploy/ansible/playbooks/cleanup.yml        # NEW
deploy/ansible/playbooks/deploy-models.yml  # NEW
deploy/ansible/inventory/production.yml     # MODIFIED (add qwen3_model_local, qwen3_tokenizer_local vars)
```

All three playbooks depend on:
- `deploy/ansible/inventory/production.yml` (existing, same variables)
- `deploy/ansible/ansible.cfg` (existing, same config)
- `deploy/ansible/requirements.yml` (existing, already has `community.docker >= 3.12.0`)

### References

- [Source: deploy/ansible/playbooks/bootstrap.yml] — Primary pattern reference (task naming, health check, summary, cron entry names, **helper container pattern for volume file deployment**)
- [Source: deploy/ansible/playbooks/update.yml] — Container info check pattern, health poll, summary format
- [Source: deploy/ansible/inventory/production.yml] — Variable definitions (api_key_value, port, restart_hour)
- [Source: deploy/ansible/ansible.cfg] — SSH and execution config
- [Source: compose.yaml] — Volume names (cumadre-models, cumadre-voices, cumadre-audio), container name (tts-service), port config, **QWEN3_MODEL_PATH and QWEN3_TOKENIZER_PATH env vars**
- [Source: src/cumadre/health.py] — Health response fields and structure
- [Source: src/cumadre/download.py] — Auto-download skip logic (`ensure_qwen3_models` checks `is_file()` before downloading)
- [Source: docs/quantizing-qwen3-models.md] — Qwen3 GGUF file names, sizes, and conversion procedure
- [Source: _bmad-output/planning-artifacts/architecture.md#Ansible Playbooks] — Privilege model and playbook specifications
- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.3] — Acceptance criteria
- [Source: _bmad-output/implementation-artifacts/3-1-ansible-project-structure-bootstrap-playbook.md] — Cron entry names, architecture patterns, helper container pattern
- [Source: _bmad-output/implementation-artifacts/3-2-update-playbook.md] — Container info check, summary pattern
- [Source: _bmad-output/implementation-artifacts/deferred-work.md] — Known deferred issues (model deploy gap resolved by this story)

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

None — clean implementation with no blockers.

### Completion Notes List

- **health.yml**: Read-only diagnostic playbook with 9 task groups. Checks container state via `docker_container_info`, queries `/health` endpoint accepting both 200/503 with `ignore_errors` for connection refused, checks disk usage (`df -h /` + `docker exec du -sh /audio`), verifies both cron entries (`cumadre-daily-restart`, `cumadre-audio-cleanup`). Warns on memory > 5 GB, disk > 80%, and Qwen3 disabled. Comprehensive summary report with all health fields.
- **cleanup.yml**: Destructive decommission playbook. Uses `docker_compose_v2` with `state: absent` + `remove_volumes: true` to stop/remove containers and all three named volumes. Prunes project images, removes both cron entries by exact name match, removes `~/cumadre` directory. Gracefully exits via `end_play` if deployment not found.
- **deploy-models.yml**: Qwen3 GGUF pre-deployment playbook using helper container pattern (same as bootstrap clone WAV). Validates both `qwen3_model_local` and `qwen3_tokenizer_local` are set. Stages files on VPS, creates alpine helper with `cumadre-models` volume, copies both GGUF files, cleans up. Destination paths match `compose.yaml` env vars exactly.
- **inventory/production.yml**: Added `qwen3_model_local` and `qwen3_tokenizer_local` variables (default empty).
- All validations pass: syntax-check, yamllint, ansible-lint (production profile), zero `become:true`, `[Component]` naming, no paths outside `~/cumadre`.
- Existing test suite: 392 passed, 11 skipped, 2 pre-existing failures (subprocess mock in test_routing.py — confirmed on master).

### Change Log

- 2026-03-25: Implemented Story 3.3 — health, cleanup, and deploy-models playbooks

### Review Findings

- [x] [Review][Decision] AC 4: Audio disk pressure check uses root FS %, not audio volume size — dismissed, root FS > 80% is sufficient proxy
- [x] [Review][Patch] Jinja2 does not short-circuit `and` — crashes when container doesn't exist [health.yml:44,56,98,137] — fixed
- [x] [Review][Patch] Summary `container_running` string is always truthy — shows "Running" when it shouldn't [health.yml:159] — fixed
- [x] [Review][Patch] Disk usage regex fails on wrapped `df` output or no-match [health.yml:108-115] — fixed
- [x] [Review][Patch] No block/always — orphans helper container and 1.6 GB staging on failure [deploy-models.yml:86-122] — fixed
- [x] [Review][Defer] Volume name mismatch: helper uses `cumadre-models`, Compose may prefix to `cumadre_cumadre-models` [compose.yaml, deploy-models.yml, bootstrap.yml] — deferred, pre-existing
- [x] [Review][Defer] `~` expansion in `docker_container_copy_into` path may not work [deploy-models.yml, bootstrap.yml] — deferred, pre-existing

### File List

- `deploy/ansible/playbooks/health.yml` — NEW: read-only diagnostic playbook
- `deploy/ansible/playbooks/cleanup.yml` — NEW: full VPS decommission playbook
- `deploy/ansible/playbooks/deploy-models.yml` — NEW: Qwen3 GGUF model pre-deployment playbook
- `deploy/ansible/inventory/production.yml` — MODIFIED: added qwen3_model_local and qwen3_tokenizer_local variables
- `_bmad-output/implementation-artifacts/sprint-status.yaml` — MODIFIED: story status updated
- `_bmad-output/implementation-artifacts/3-3-health-cleanup-playbooks.md` — MODIFIED: story file updated
