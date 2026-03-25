# Story 3.1: Ansible Project Structure & Bootstrap Playbook

Status: done

## Story

As a **DevOps operator**,
I want to bootstrap CUMADRE on a clean VPS with a single Ansible command,
So that the service is fully deployed and healthy without manual intervention.

## Acceptance Criteria

1. **Given** `deploy/ansible/` directory **When** I inspect the structure **Then** it contains `ansible.cfg`, `inventory/production.yml`, and `playbooks/` directory.

2. **Given** a clean Ubuntu VPS with SSH access **When** I run `ansible-playbook playbooks/bootstrap.yml -i inventory/production.yml` **Then** it:
   - Installs Docker (using `become: true` for apt tasks only)
   - Clones the repo to `~/cumadre`
   - Deploys the qwen3-tts-cli binary (~600 KB with seed patch)
   - Deploys the clone reference WAV (if provided)
   - Builds the container
   - Starts the service
   - Configures audio cleanup cron
   - Configures daily restart cron
   - Waits for healthy status
   - **All project files on the VPS live in `~/cumadre`** (never in /opt, /tmp, or system directories)

3. **Given** the bootstrap playbook **When** I inspect the task names **Then** every task follows the `[Component] Action description` pattern (e.g., `[Docker] Install Docker Engine`, `[TTS] Build service container`, `[Health] Verify endpoint responds`).

4. **Given** the bootstrap playbook completes successfully **When** I read the final task output **Then** it is a `[Summary]` task reporting: service status, loaded voices, engine statuses (both Kokoro and Qwen3), clone configuration status, endpoint URL, and a copy-paste-ready test curl command.

5. **Given** the bootstrap playbook **When** it configures the daily restart cron **Then** it creates a user-level crontab entry (not system cron) that runs `docker compose restart` daily as a safety net (Kokoro memory leak fixed in phonemizer-fork >=3.3.2, but daily restart adds defense-in-depth).

6. **Given** the bootstrap playbook **When** it configures audio cleanup **Then** it creates a user-level crontab entry that runs every 6 hours, deleting audio files (`*.ogg`, `*.wav`) older than 24 hours from the audio volume to prevent disk space exhaustion.

7. **Given** a prerequisite check fails (e.g., missing SSH access) **When** the playbook task fails **Then** the failure `msg` includes what went wrong, why, and what to do to fix it.

## Tasks / Subtasks

- [x] Task 1: Create ansible.cfg (AC: #1)
  - [x] 1.1 Create `deploy/ansible/ansible.cfg` with inventory default, SSH settings, and retry/timeout config
  - [x] 1.2 Set `inventory = inventory/production.yml` as default
  - [x] 1.3 Configure SSH pipelining for performance
  - [x] 1.4 Set `host_key_checking = False` for initial bootstrap (operator's choice)

- [x] Task 2: Create production inventory (AC: #1)
  - [x] 2.1 Replace `inventory/.gitkeep` with `inventory/production.yml`
  - [x] 2.2 Define `cumadre_vps` host group with `ansible_host`, `ansible_user` variables
  - [x] 2.3 Add group vars: `api_key_value`, `clone_reference_wav` (optional), `repo_url`, `repo_branch`
  - [x] 2.4 Add inline comments explaining each variable

- [x] Task 3: Create bootstrap playbook structure (AC: #2, #3, #7)
  - [x] 3.1 Create `deploy/ansible/playbooks/bootstrap.yml` — replace `.gitkeep`
  - [x] 3.2 Implement prerequisite checks block with clear failure messages
  - [x] 3.3 Implement `[Docker]` tasks: install Docker Engine via apt (`become: true`), add user to docker group
  - [x] 3.4 Implement `[Git]` tasks: clone repo to `~/cumadre`
  - [x] 3.5 Implement `[Assets]` tasks: deploy qwen3-tts-cli binary from `deploy/bin/`, deploy clone reference WAV if variable is set
  - [x] 3.6 Implement `[TTS]` tasks: build Docker image, start service with `docker compose up -d`
  - [x] 3.7 All task names follow `[Component] Action description` pattern

- [x] Task 4: Implement cron tasks (AC: #5, #6)
  - [x] 4.1 Daily restart cron: user-level crontab, `docker compose -f ~/cumadre/compose.yaml restart`, default 3 AM
  - [x] 4.2 Audio cleanup cron: user-level crontab, every 6 hours, find+delete `*.ogg` and `*.wav` older than 24h from audio volume
  - [x] 4.3 Use Ansible `cron` module (not `cron.d`) for user-level entries

- [x] Task 5: Implement health wait and summary (AC: #4)
  - [x] 5.1 `[Health]` task: poll `http://localhost:{{ port }}/health` until `status == "healthy"` with timeout
  - [x] 5.2 `[Summary]` task: debug output with service status, loaded voices, engine statuses, clone config, endpoint URL, test curl command
  - [x] 5.3 Test curl command must be copy-paste-ready: `curl -H "Authorization: Bearer {{ api_key_value }}" http://{{ ansible_host }}:{{ port }}/v1/audio/speech -d '{"input":"Olá mundo","voice":"santa"}'`

- [x] Task 6: Validate and test (AC: #1-#7)
  - [x] 6.1 Run `ansible-lint` on all playbook files (if available, or validate syntax with `ansible-playbook --syntax-check`)
  - [x] 6.2 Run `yamllint` on all YAML files
  - [x] 6.3 Verify all task names follow `[Component] Action description` pattern
  - [x] 6.4 Verify no `become: true` except on apt/Docker install tasks
  - [x] 6.5 Verify all project paths use `~/cumadre` (never /opt, /tmp, or system directories)

## Dev Notes

### Architecture Constraints

- **Privilege model**: `become: true` ONLY for apt tasks (Docker install, adding user to docker group). Everything else unprivileged.
- **File locations**: All project files in `~/cumadre` on VPS. Never `/opt`, `/tmp`, or system directories.
- **Docker Compose v2**: Always `docker compose`, never `docker-compose`.
- **Single-process**: No `--workers` flag. Entrypoint already enforces this.
- **User-level cron**: Use Ansible `cron` module (creates user crontab entries). Never system `/etc/cron.d/`.
- **Named volumes**: `cumadre-models`, `cumadre-voices`, `cumadre-audio` — created by compose.yaml, not by Ansible.

### Existing Infrastructure (from Story 2.1 & 2.2)

The container stack is fully implemented:
- **Dockerfile** (88 lines): Single-stage from `python:3.12-slim`, espeak-ng from source with pt_extra dual-path copy, uv deps, qwen3-tts-cli binary, noise WAVs, non-root `appuser`, entrypoint at `/app/scripts/entrypoint.sh`
- **compose.yaml** (43 lines): 3 named volumes (`cumadre-models:rw`, `cumadre-voices:ro`, `cumadre-audio:rw`), 14 env vars with absolute model paths, resource limits (4 CPU / 6G RAM), Python healthcheck, `restart: unless-stopped`
- **scripts/entrypoint.sh**: `exec uvicorn cumadre.main:create_app --factory --host 0.0.0.0 --port ${PORT:-8000}`
- **src/cumadre/download.py**: Auto-downloads Kokoro (~352 MB) and Qwen3 (~1.6 GB) models on first run to `/models` volume

### Critical Implementation Details

**Bootstrap playbook flow** (architecture-defined order):
1. `[Prereq]` Verify SSH, detect Ubuntu/Debian, verify user exists
2. `[Docker]` Install Docker Engine via apt (`become: true`)
3. `[Docker]` Add VPS user to docker group (`become: true`)
4. `[Git]` Clone cumadre repo to `~/cumadre` (or pull if exists for idempotency)
5. `[Assets]` Copy qwen3-tts-cli binary to `~/cumadre/deploy/bin/` (if updated)
6. `[Assets]` Copy clone reference WAV to voices volume directory (if provided)
7. `[TTS]` Build Docker image: `docker compose build`
8. `[TTS]` Start service: `docker compose up -d`
9. `[Cron]` Configure daily restart cron (user-level, default 3 AM)
10. `[Cron]` Configure audio cleanup cron (user-level, every 6h)
11. `[Health]` Wait for `/health` to return `status: "healthy"` (allow 120s+ for model download + warm-up on first run)
12. `[Summary]` Report status, voices, engines, clone config, endpoint URL, test curl

**qwen3-tts-cli binary**: Pre-built, ~600 KB, statically linked C++ linux/amd64. Located at `deploy/bin/qwen3-tts-cli` in the repo. Dockerfile COPYs it to `/usr/local/bin/qwen3-tts-cli` during image build.

**Clone reference WAV**: Optional. If `clone_reference_wav` variable is set in inventory, copy the WAV file into the `cumadre-voices` volume mount point on the host. Docker mounts it read-only at `/voices/`.

**Health endpoint**: Returns JSON with `status`, `voices`, `engines`, `queue_depth`, `clone_configured`, `uptime_seconds`, `memory_mb`, `version`. Returns 503 during warm-up, 200 when ready.

**First-run model download**: ~2 GB total (Kokoro ONNX + voices + Qwen3 GGUF + tokenizer). The health wait timeout must accommodate this on slow connections. Consider `retries: 60` with `delay: 10` (10 min total) for the health poll task.

### Audio Cleanup Cron Details

The audio volume accumulates generated OGG/WAV files. The cleanup cron runs inside the host (not the container) targeting the Docker volume mount path. Use `docker volume inspect cumadre-audio --format '{{ .Mountpoint }}'` to get the actual host path, or use a `docker exec` approach:
```bash
docker exec tts-service find /audio -type f \( -name "*.ogg" -o -name "*.wav" \) -mmin +1440 -delete
```
The `docker exec` approach is preferred because it doesn't require knowing the host volume path and works with the container's filesystem permissions.

### Daily Restart Cron Details

```bash
cd ~/cumadre && docker compose restart
```
- Must `cd` first so compose finds `compose.yaml`
- User-level crontab: `ansible.builtin.cron` module with `user` parameter omitted (defaults to connection user)
- Default schedule: `0 3 * * *` (3 AM daily)

### Inventory Design

```yaml
all:
  hosts:
    cumadre_vps:
      ansible_host: "{{ vps_ip }}"       # Set by operator
      ansible_user: "{{ vps_user }}"     # Set by operator
  vars:
    api_key_value: "{{ lookup('env', 'CUMADRE_API_KEY') | default('changeme', true) }}"
    clone_reference_wav: ""               # Optional: local path to clone WAV
    repo_url: "https://github.com/user/cumadre.git"  # Operator sets
    repo_branch: "master"
    port: 8000
    restart_hour: 3                       # Daily restart hour (0-23)
```

### Anti-Patterns to Avoid

- **NO `become: true` on docker compose commands** — user is in docker group after bootstrap
- **NO files outside `~/cumadre`** — all project files in user home
- **NO `docker-compose` v1 syntax** — always `docker compose`
- **NO system cron** (`/etc/cron.d/`) — use user-level crontab via `ansible.builtin.cron`
- **NO hardcoded IPs or keys** — all from inventory variables
- **NO `restart: always`** in compose — already set to `unless-stopped`
- **NO manual volume creation** — compose.yaml defines volumes, `docker compose up` creates them
- **NO `ansible_become: true` at play level** — only per-task for apt operations
- **NO raw `shell:` when an Ansible module exists** — prefer `ansible.builtin.apt`, `ansible.builtin.git`, `ansible.builtin.cron`, `community.docker.docker_compose_v2`

### Testing Standards

- `ansible-playbook --syntax-check playbooks/bootstrap.yml`
- `yamllint` on all YAML files (if configured)
- `ansible-lint` if available
- All task names audited for `[Component] Action` pattern
- Privilege audit: grep for `become:` — must only appear on Docker/apt tasks

### Project Structure Notes

**Files to create:**
```
deploy/ansible/
  ansible.cfg                     # NEW
  inventory/
    production.yml                # NEW (replace .gitkeep)
  playbooks/
    bootstrap.yml                 # NEW (replace .gitkeep)
```

**Files that already exist (DO NOT modify):**
```
Dockerfile                        # Container build (Story 2.1)
compose.yaml                      # Container orchestration (Story 2.2)
scripts/entrypoint.sh             # Container entrypoint (Story 2.1)
deploy/bin/qwen3-tts-cli          # Pre-built binary (baked into image)
deploy/espeak-ng/pt_extra         # Custom dictionary (compiled during build)
```

### Deferred Work Awareness

From Story 2.2 code review (items NOT to address in this story):
- Download failure crashes startup (no retry) — design trade-off, not an Ansible concern
- Empty cumadre-voices volume causes Qwen3 failure — operator must pre-populate, bootstrap can warn
- Non-reproducible Docker build (espeak-ng unpinned master) — pre-existing, not in scope
- Healthcheck start_period may be insufficient on slow connections — operator can tune compose.yaml

### References

- [Source: _bmad-output/planning-artifacts/epics.md#Epic 3 — Story 3.1]
- [Source: _bmad-output/planning-artifacts/architecture.md#Deployment Operations — Bootstrap Playbook Flow]
- [Source: _bmad-output/planning-artifacts/architecture.md#Ansible Privilege Model]
- [Source: _bmad-output/planning-artifacts/architecture.md#Cron Jobs]
- [Source: _bmad-output/planning-artifacts/architecture.md#Volume Architecture]
- [Source: _bmad-output/implementation-artifacts/2-1-dockerfile-entrypoint.md — Container build details]
- [Source: _bmad-output/implementation-artifacts/2-2-docker-compose-production-configuration.md — Compose config details]
- [Source: _bmad-output/implementation-artifacts/deferred-work.md — Known deferred items]

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

- ansible-playbook --syntax-check: PASSED
- yamllint: PASSED (0 errors after line-length fixes)
- ansible-lint: PASSED (production profile, 1 no-handler suppressed with noqa — meta:reset_connection must run inline)
- pytest: 394 passed, 11 skipped, 0 failures (no regressions)
- Privilege audit: become:true only on Docker/apt tasks + volume copy
- Path audit: no /opt, /tmp, or system directories — all ~/cumadre
- Task name audit: all 21 tasks follow [Component] Action pattern

### Completion Notes List

- Created `deploy/ansible/ansible.cfg` with SSH pipelining, host_key_checking=False, inventory default
- Created `deploy/ansible/inventory/production.yml` replacing .gitkeep — defines cumadre_vps host group with operator-configurable variables and inline comments
- Created `deploy/ansible/playbooks/bootstrap.yml` replacing .gitkeep — full 12-step bootstrap flow: Prereq, Docker, Git, Assets, TTS, Cron, Health, Summary
- Idempotency: modern Docker GPG key via get_url+signed-by (not deprecated apt_key), conditional meta:reset_connection, smart changed_when on compose commands, all apt/cron/git/copy modules are naturally idempotent
- Audio cleanup uses `docker exec` approach per dev notes (avoids host volume path discovery)
- Daily restart uses `cd ~/cumadre && docker compose restart` per dev notes
- Health poll: 60 retries x 10s delay = 10 min timeout for first-run model download
- Summary task outputs all required fields plus copy-paste-ready curl command
- Note: `ansible_become_password` not included as a group var — become is only used per-task and the operator should use `--ask-become-pass` or SSH key-based sudo. This is safer than storing sudo passwords in inventory.

### Change Log

- 2026-03-24: Implemented Story 3.1 — Ansible project structure and bootstrap playbook

### File List

- deploy/ansible/ansible.cfg (NEW)
- deploy/ansible/inventory/production.yml (NEW, replaced .gitkeep)
- deploy/ansible/playbooks/bootstrap.yml (NEW, replaced .gitkeep)

### Review Findings

#### Decision Needed (all resolved)

- [x] [Review][Decision] Missing qwen3-tts-cli binary deployment task — Resolved: removed orphaned deploy/bin task. Binary comes via git clone; must be committed to repo first.
- [x] [Review][Decision] `become: true` on voices volume copy violates privilege model — Resolved: replaced with helper container pattern using `community.docker.docker_container_copy_into`. No become needed.
- [x] [Review][Decision] `ansible.builtin.command` for docker compose instead of `community.docker` module — Resolved: switched to `community.docker.docker_compose_v2` with `build: always`. Added `requirements.yml`.
- [x] [Review][Decision] Git clone `force: false` + `update: true` fails on local VPS modifications — Dismissed: VPS is managed by Ansible, no manual edits. `force: false` is correct.

#### Patch (all applied)

- [x] [Review][Patch] `changed_when` for docker compose build — Resolved: replaced with `community.docker.docker_compose_v2` module (handles change detection natively)
- [x] [Review][Patch] API key defaults to 'changeme' with no playbook validation — Fixed: added `[Prereq] Validate API key` assert task
- [x] [Review][Patch] No .env file created before `docker compose up` — Fixed: added `[Config] Create .env file` task
- [x] [Review][Patch] Summary debug task leaks API key in plaintext curl command — Fixed: replaced with `$CUMADRE_API_KEY` env var placeholder
- [x] [Review][Patch] Audio cleanup cron errors every 6h when container is stopped — Fixed: added `docker inspect` running-state guard
- [x] [Review][Patch] Docker GPG key and apt repo hardcode 'ubuntu' — Fixed: uses `{{ ansible_distribution | lower }}` for Ubuntu/Debian compat
- [x] [Review][Patch] Sprint status header comment inconsistency — Fixed
- [x] [Review][Patch] `repo_url` defaults to placeholder — Fixed: changed to `CHANGE_ME` with assert validation
- [x] [Review][Patch] Double blank line between test methods in test_config.py — Fixed

#### Deferred (pre-existing from Stories 2.1/2.2)

- [x] [Review][Defer] Dockerfile purges gcc/g++ — libstdc++ may be removed by autoremove [Dockerfile:55-66] — deferred, pre-existing
- [x] [Review][Defer] `Path.rename()` fails across filesystem mount boundaries in download.py [download.py:31] — deferred, pre-existing
- [x] [Review][Defer] No checksum verification for multi-GB model downloads [download.py] — deferred, pre-existing
- [x] [Review][Defer] Synchronous model download blocks async event loop during startup [main.py:49-60] — deferred, pre-existing
- [x] [Review][Defer] URL config fields have no format validation [config.py:65-86] — deferred, pre-existing
- [x] [Review][Defer] espeak-ng cloned from unpinned master — non-reproducible builds [Dockerfile:20] — deferred, pre-existing
- [x] [Review][Defer] compose.yaml hardcodes internal PORT to 8000 while host-side is variable [compose.yaml:6,15] — deferred, pre-existing
- [x] [Review][Defer] compose.yaml healthcheck uses `python` which may not resolve in PATH [compose.yaml:34] — deferred, pre-existing
- [x] [Review][Defer] No download progress logging for large files [download.py:22-34] — deferred, pre-existing
- [x] [Review][Defer] Download exception at startup gives no actionable context [main.py:49-60] — deferred, pre-existing
- [x] [Review][Defer] compose.yaml API_KEY unset on host causes runtime crash [compose.yaml:13] — deferred, pre-existing
- [x] [Review][Defer] SSL cert errors in downloads give opaque messages [download.py:27] — deferred, pre-existing
- [x] [Review][Defer] Dockerfile COPY noise/ may be empty on fresh clone [Dockerfile:74] — deferred, pre-existing
- [x] [Review][Defer] Named volumes start empty — first-run downloads block startup [compose.yaml:9-11] — deferred, pre-existing
- [x] [Review][Defer] Dockerfile COPY deploy/bin/qwen3-tts-cli fails if binary not present [Dockerfile:66] — deferred, pre-existing

#### Post-Review Gap: Ansible Model Deployment

The bootstrap playbook does NOT deploy Qwen3 GGUF model files (~1.6 GB) to the VPS. Models must be copied via SSH manually before the service can use Qwen3 (see `docs/quantizing-qwen3-models.md` for the manual procedure).

A future story (likely Story 3-2 update playbook or a new story) should add an Ansible task block that:

1. Copies `qwen3-tts-0.6b-q8_0.gguf` and `qwen3-tts-tokenizer-f16.gguf` from the operator's machine to the VPS
2. Uses the helper container pattern (`docker run --rm -v cumadre-models:/models -v ~/staging:/src:ro alpine cp ...`) to populate the Docker volume
3. Runs before the TTS service build/start tasks
4. Is idempotent — skips copy if models already exist in the volume with correct size

Without this, the Ansible bootstrap deploys a working Kokoro-only service. Qwen3 requires manual model deployment as a separate step.
