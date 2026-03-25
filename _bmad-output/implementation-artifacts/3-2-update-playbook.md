# Story 3.2: Update Playbook

Status: done

## Story

As a **DevOps operator**,
I want to update COMADRE from the latest repo without losing data,
So that I can deploy new features and fixes safely.

## Acceptance Criteria

1. **Given** a running COMADRE deployment, **When** I run `ansible-playbook playbooks/update.yml -i inventory/production.yml`, **Then** it pulls the latest repo, updates the qwen3-tts-cli binary if changed, rebuilds the Docker image (which recompiles espeak-ng pt_extra if the dictionary source changed), and restarts the container. **And** runs entirely unprivileged (no `become: true`).

2. **Given** the update playbook completes, **When** I check the service, **Then** voice files in comadre-voices volume are intact, model cache in comadre-models volume is intact, generated audio files in comadre-audio volume are intact, clone reference WAV is intact, and the API_KEY is unchanged.

3. **Given** the update playbook completes, **When** I read the final `[Summary]` task, **Then** it confirms service health status, data preservation, both engine statuses (Kokoro and Qwen3), clone configuration, and loaded voices.

4. **Given** the update includes changes to the pt_extra dictionary or noise WAV files, **When** the Docker image is rebuilt, **Then** the updated assets are baked into the new image automatically via the build process.

## Tasks / Subtasks

- [x] Task 1: Create `deploy/ansible/playbooks/update.yml` (AC: #1, #2, #4)
  - [x] 1.1 Add prerequisite checks (verify ~/comadre exists, service is running, API key configured)
  - [x] 1.2 Add `[Git] Pull latest changes` task using `ansible.builtin.git` with `update: true`
  - [x] 1.3 Add `[TTS] Rebuild image and restart service` using `community.docker.docker_compose_v2` with `build: always`
  - [x] 1.4 Add `[Health] Wait for service to become healthy` (same pattern as bootstrap: 60 retries x 10s)
  - [x] 1.5 Add `[Summary] Report update status` with health, engines, voices, data preservation confirmation
- [x] Task 2: Validate playbook (AC: #1, #2, #3)
  - [x] 2.1 Run `ansible-playbook --syntax-check playbooks/update.yml`
  - [x] 2.2 Run `yamllint` on the playbook
  - [x] 2.3 Run `ansible-lint` on the playbook
  - [x] 2.4 Audit: zero `become: true` tasks
  - [x] 2.5 Audit: all tasks follow `[Component] Action description` naming pattern
  - [x] 2.6 Audit: no paths outside `~/comadre`

## Dev Notes

### Playbook Flow

The update playbook is deliberately simple compared to bootstrap. It assumes a working deployment already exists (created by `bootstrap.yml`). The flow:

1. `[Prereq]` Verify `~/comadre` directory exists (fail fast if not bootstrapped)
2. `[Prereq]` Verify container is running (fail fast if service is down — operator should investigate first)
3. `[Git]` Pull latest changes to `~/comadre` (same repo/branch as bootstrap)
4. `[TTS]` Rebuild Docker image and restart service
5. `[Health]` Wait for healthy status (60 retries x 10s = 10 min timeout)
6. `[Summary]` Report update results

### Architecture Patterns to Follow (from bootstrap.yml)

- **Play target:** `hosts: comadre_vps` (same inventory as bootstrap)
- **Task naming:** `[Component] Action description` pattern (e.g., `[Git] Pull latest changes`)
- **Module usage:** Use `community.docker.docker_compose_v2` for compose operations, not raw `shell:` commands
- **Health check pattern:** `ansible.builtin.uri` with `until` loop, 60 retries, 10s delay, checking `status == 200` and `json.status == "healthy"`
- **Summary pattern:** `ansible.builtin.debug` with `msg: |` block showing formatted output from health check JSON
- **Variable reuse:** Use inventory variables (`port`, `repo_branch`, `ansible_host`, `api_key_value`) — no hardcoded values
- **Gather facts:** `gather_facts: false` (not needed — no apt, no OS detection)

### Critical Constraint: Zero Privilege Escalation

The update playbook must have **NO** `become: true` tasks. Everything runs as the unprivileged VPS user who is already in the `docker` group (set up by bootstrap). This includes:
- `git pull` (user owns `~/comadre`)
- `docker compose build` (user in docker group)
- `docker compose up` (user in docker group)
- Health checks (plain HTTP curl)

### Data Preservation — How It Works

The update does NOT touch Docker volumes. The `docker_compose_v2` module with `build: always` + `state: present`:
1. Rebuilds the image (new code, new pt_extra, new noise WAVs baked in)
2. Recreates the container from the new image
3. **Re-mounts** the existing named volumes (`comadre-models`, `comadre-voices`, `comadre-audio`)

Named volumes persist across container recreation by design. The `.env` file lives on the host filesystem at `~/comadre/.env` — it is NOT inside the container or a volume.

Crucially, `docker_compose_v2` with `state: present` does NOT run `docker compose down -v` (which would delete volumes). It performs an in-place rebuild+restart.

### Binary Update — Automatic via Git Pull

The `qwen3-tts-cli` binary at `deploy/bin/qwen3-tts-cli` is tracked in git. When `git pull` fetches a new binary, the subsequent `docker compose build` COPYs it into the image. No special handling needed.

### Dictionary/Noise Update — Automatic via Docker Build

The Dockerfile:
- Compiles `deploy/espeak-ng/pt_extra` into the image (both system and misaki bundled path)
- COPYs `noise/*.wav` into `/app/noise/`

Any changes to these files are picked up automatically on `docker compose build`.

### Anti-Patterns to Avoid

- **NO** `become: true` anywhere — this is the key differentiator from bootstrap
- **NO** `docker compose down` before `up` — unnecessary and risks volume deletion if flags are wrong
- **NO** manual volume operations — volumes are managed by compose.yaml
- **NO** `docker-compose` v1 syntax — use `community.docker.docker_compose_v2` module
- **NO** `shell:` or `command:` for compose operations — use the dedicated module
- **NO** restart of cron jobs — they're already configured by bootstrap and don't change
- **NO** `.env` file recreation — it already exists and must be preserved (operator may have customized it)
- **NO** clone reference WAV re-deployment — it's in the comadre-voices volume, untouched by rebuild
- **NO** `gather_facts: true` — not needed for unprivileged-only operations

### Previous Story Learnings (from Story 3.1)

1. **`community.docker.docker_compose_v2`** is the correct module (requires `community.docker >= 3.12.0` from `requirements.yml`). Use `project_src: "~/comadre"`, `state: present`, `build: always`, `remove_orphans: true`.
2. **Health check** uses `ansible.builtin.uri` with `url: "http://localhost:{{ port }}/health"`, `return_content: true`, `register: health_check`, `until:` condition, `retries: 60`, `delay: 10`.
3. **Summary** uses `vars: hc: "{{ health_check.json }}"` and `ansible.builtin.debug` with multi-line `msg: |` block accessing `hc.status`, `hc.voices`, `hc.engines.kokoro`, `hc.engines.qwen3`, `hc.clone_configured`, `hc.uptime_seconds`.
4. **Task names** must follow `[Component] Action description` pattern exactly.
5. **`ansible-lint`** uses production profile; suppress `no-handler` with `# noqa: no-handler` only where justified.
6. **`git` module** uses `force: false`, `update: true` for safe idempotent pulls (does not discard local changes).
7. **`changed_when`** may be needed on compose tasks since the module always reports changed. In bootstrap, this was not suppressed — match the same behavior.

### Testing Standards

- `ansible-playbook --syntax-check playbooks/update.yml` must pass
- `yamllint` must pass (line-length 88 consistent with project ruff config, or use yamllint project config)
- `ansible-lint` must pass (production profile, same as bootstrap)
- Zero `become: true` tasks (privilege audit)
- All tasks follow `[Component] Action description` naming
- No paths outside `~/comadre`
- Existing Python test suite must still pass: `uv run pytest` (394+ tests, all mocked)

### Project Structure Notes

The new file goes at `deploy/ansible/playbooks/update.yml`, alongside the existing `bootstrap.yml`. No other files need to be created or modified. The playbook depends on:
- `deploy/ansible/inventory/production.yml` (existing, same variables)
- `deploy/ansible/ansible.cfg` (existing, same config)
- `deploy/ansible/requirements.yml` (existing, already has `community.docker >= 3.12.0`)

### References

- [Source: deploy/ansible/playbooks/bootstrap.yml] — Primary pattern reference for all task structures
- [Source: deploy/ansible/inventory/production.yml] — Variable definitions (api_key_value, port, repo_url, repo_branch, clone_reference_wav)
- [Source: deploy/ansible/ansible.cfg] — SSH and execution config
- [Source: _bmad-output/planning-artifacts/architecture.md#Ansible Playbooks] — Privilege model and playbook specifications
- [Source: _bmad-output/planning-artifacts/epics.md#Story 3.2] — Acceptance criteria and requirements
- [Source: _bmad-output/implementation-artifacts/3-1-ansible-project-structure-bootstrap-playbook.md] — Previous story learnings and patterns
- [Source: _bmad-output/implementation-artifacts/deferred-work.md] — Known deferred issues (not in scope for this story)
- [Source: compose.yaml] — Volume names, service name, port config
- [Source: Dockerfile] — Build process (pt_extra compilation, noise COPY, binary COPY)

## Dev Agent Record

### Agent Model Used

Claude Opus 4.6 (1M context)

### Debug Log References

None — clean implementation with no issues.

### Completion Notes List

- Created `deploy/ansible/playbooks/update.yml` with 7 tasks following bootstrap.yml patterns exactly
- Prereqs: verify ~/comadre dir exists (stat+assert) and API key configured (assert)
- Git pull: `ansible.builtin.git` with `force: false`, `update: true` for safe idempotent pulls
- TTS rebuild: `community.docker.docker_compose_v2` with `state: present`, `build: always`, `remove_orphans: true`
- Health check: `ansible.builtin.uri` with `until` loop, 60 retries x 10s delay
- Summary: reports health, engines, voices, clone config, uptime, and confirms data preservation
- Zero `become: true` tasks — entirely unprivileged
- `gather_facts: false` — not needed for update operations
- All validations pass: syntax-check, yamllint, ansible-lint (production profile)
- No .env recreation, no volume operations, no cron changes — preserves existing config
- 2 pre-existing test failures in test_routing.py (subprocess mock issue) confirmed on master before changes
- No regressions: 392 passed, 11 skipped (same as master baseline)

### Change Log

- 2026-03-25: Created deploy/ansible/playbooks/update.yml — unprivileged update playbook

### Review Findings

- [x] [Review][Decision] Missing prereq: verify container is running before update — Added `community.docker.docker_container_info` check per spec flow step 2. Fixed.
- [x] [Review][Patch] Misleading "zero downtime risk" header comment — Removed "zero downtime risk" claim. Fixed.
- [x] [Review][Defer] No rollback on failed rebuild/health check — if health check fails after 10 minutes, the broken new version stays running. Real concern but rollback is out of scope for this story. — deferred, architectural enhancement
- [x] [Review][Defer] Port variable coupling between inventory and compose.yaml — inventory `port` could diverge from compose.yaml hardcoded `PORT: '8000'`. Pre-existing config coupling, not introduced by this change. — deferred, pre-existing

### File List

- deploy/ansible/playbooks/update.yml (new)
