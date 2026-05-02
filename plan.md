# Implementation Plan

> Revision 2 — incorporates reviewer feedback (bloqueador + observations).

## Goal

Fix deploy key title collision so multiple VPSes can run bootstrap without GitHub rejecting duplicate titles, and add GitHub-side cleanup to `cleanup.yml`.

## Problem Summary

- `bootstrap.yml` L243: `title: "comadre-vps"` is a fixed string. Second VPS bootstrap generates a new key, POSTs with same title → GitHub returns **422** (duplicate). Playbook treats 422 as OK (`status_code: [201, 422]`), but the second VPS's private key doesn't match the first VPS's already-registered public key → `git clone` fails with SSH auth error.
- `cleanup.yml`: removes only local key files (`deploy_key_path` + `.pub`). No `DELETE /repos/{owner}/{repo}/keys/{key_id}` call → deploy keys accumulate as orphans on GitHub.

## Tasks

### 1. Add `stat` pre-check before key generation in `bootstrap.yml`

- **File**: `deploy/ansible/playbooks/bootstrap.yml`
- **Changes**: Insert a `stat` task before the existing `[Git] Generate deploy key` block (before L222). Check if `{{ deploy_key_path }}` exists. Register the result as `deploy_key_stat`.
- **Acceptance**: The variable `deploy_key_stat.stat.exists` is available for conditional execution of subsequent tasks.

### 2. Make key generation + GitHub registration conditional

- **File**: `deploy/ansible/playbooks/bootstrap.yml`
- **Changes**:
  - Add `when: not deploy_key_stat.stat.exists` to the existing three tasks: `[Git] Generate deploy key`, `[Git] Read deploy public key`, and `[Git] Register deploy key with GitHub`.
  - Change the title from `"comadre-vps"` to `"comadre-vps-{{ ansible_host }}"` (L243).
    **Why `ansible_host` and not `inventory_hostname`**: the example inventories (`production.yml`, `oracle.yml`, `*.example`) all name their single host `comadre_vps`. If an operator copies this pattern for multiple VPSes (e.g. `inventory/vps1.yml`, `inventory/vps2.yml`, each with a host named `comadre_vps`), `inventory_hostname` evaluates to `comadre_vps` everywhere → collision reproduced. `ansible_host` is the actual connection target (IP or DNS), guaranteed unique per VPS.
  - Add `force: false` explicitly to `openssh_keypair` for clarity.
  - Change `status_code` from `[201, 422]` to `[201]` (collisions can't happen with unique titles).
  - Keep `no_log: true` on the register task (the response may leak repository metadata, and the registered key's `id` is visible in the JSON payload).
- **Acceptance**:
  - First bootstrap on a VPS: key is generated and registered with unique title → 201.
  - Re-bootstrap on same VPS: key already exists → `stat` check skips generate+register → clone uses existing key → no GitHub API call at all.
  - Bootstrap on second VPS: key doesn't exist → generated and registered with different unique title (e.g. `comadre-vps-vps2`) → 201.

### 3. Add GitHub deploy key deletion to `cleanup.yml`

- **File**: `deploy/ansible/playbooks/cleanup.yml`
- **Changes**: Insert a new block **before** the existing `[Git] Remove deploy key from VPS` task (before L209). The block must:
  1. **Slurp local public key**: Read `{{ deploy_key_path }}.pub` (only if it exists — use `when: deploy_key_stat.stat.exists` from a preceding stat check).
  2. **GET all deploy keys**: `GET https://api.github.com/repos/{{ github_repo_path }}/keys` with Bearer auth.
  3. **Find matching key**: Iterate the JSON array. A key matches if *either*:
     - `title == "comadre-vps-{{ inventory_hostname }}"` (new unique format), OR
     - `title == "comadre-vps"` AND `key == <local_public_key>` (old fixed-title format — safe because key-material match proves this VPS owns it).
  4. **DELETE each match**: `DELETE https://api.github.com/repos/{{ github_repo_path }}/keys/{{ key.id }}`. Accept `[204, 404]`. Run with `failed_when: false` so missing keys don't block decommission.
- **Acceptance**:
  - After cleanup, no deploy key with this VPS's title or key material remains on GitHub.
  - Running cleanup on a VPS that was already cleaned up (key already gone) is a no-op (404 accepted).
  - Running cleanup on a VPS bootstrapped with the old fixed-title code still removes its key (matched by key material).

### 4. Verify `update.yml` needs no changes

- **File**: `deploy/ansible/playbooks/update.yml`
- **Analysis**: Uses `key_file: "{{ deploy_key_path }}"` for `git pull`. Each VPS has its own key at that path. The unique-title fix in bootstrap ensures each VPS has a working key → no changes needed.
- **Acceptance**: `update.yml` continues to work as-is on both existing and newly-bootstrapped VPSes.

## Files to Modify

- `deploy/ansible/playbooks/bootstrap.yml`
  - Pre-L222: Insert `stat` task for `{{ deploy_key_path }}`.
  - L222–258: Wrap key generation, slurp, and GitHub registration in `when: not deploy_key_stat.stat.exists`.
  - L243: `title: "comadre-vps-{{ ansible_host }}"` (was `"comadre-vps"`).
  - L248: `status_code: [201]` (was `[201, 422]`).

- `deploy/ansible/playbooks/cleanup.yml`
  - Pre-L209: Insert new block — stat check + slurp pubkey + GET keys + filter + DELETE loop.
    - All new tasks carry `become: false` (key lives under `~/.ssh`, not `/root/.ssh`).
    - URI tasks carry `no_log: true` (avoid leaking repository metadata).
    - Public-key comparison uses `| trim` on both sides (slurp may include trailing newline).
    - Match by title `"comadre-vps-{{ ansible_host }}"` OR by key material for old fixed-title format.
  - L233 summary text: update to mention GitHub key cleanup.

- `docs/deployment-guide.md`
  - §"Deploy key registration fails": update references from `"comadre-vps"` to the new unique-title format.

- `docs/deploy-key-collision.txt`
  - **Delete** after fix is live. Written in Portuguese — violates project language policy (AGENTS.md: "Everything in English").

## New Files

None.

## Dependencies

- Task 2 depends on Task 1 (needs `deploy_key_stat` variable).
- Tasks 3 and 4 are independent of each other and of 1–2.
- All tasks are independent of application code; no Python changes.

## Risks

1. **Existing VPS with old fixed title**: On re-bootstrap with the new code, the local key already exists → `stat` check skips generation + registration. The old `"comadre-vps"` key on GitHub is harmless and continues to work. **No action needed.** Cleanup later removes it via key-material match (with `| trim` on both sides to avoid trailing-newline mismatch).

2. **`github_pat` expired at cleanup time**: The PAT is documented as "can expire after bootstrap with zero impact." For cleanup to delete the deploy key from GitHub, the PAT must still be valid. **Mitigation**: The DELETE task uses `failed_when: false` — if the PAT is expired, cleanup skips GitHub deletion gracefully and still removes local files. Add a `debug` message if the API returns 401/403 so the operator knows manual cleanup is needed.

3. **`openssh_keypair` idempotency**: The module defaults to `force: false` (preserves existing keys). The `stat` pre-check ensures we only run generation if the file is absent, so `force: false` is already implicit — no explicit parameter needed.

4. **Multi-VPS cleanup of old fixed-title key**: Two VPSes both bootstrapped with old `"comadre-vps"` title share the same title on GitHub. Cleanup on VPS A deletes its key (matched by key material), leaving VPS B's key intact (different key material). **Safe.**

5. **Race condition in key deletion**: No risk — cleanup is a single-threaded ansible run per VPS.

6. **Pagination**: `GET /repos/{owner}/{repo}/keys` returns up to 100 keys per page. For a self-hosted repo with < 100 deploy keys this is irrelevant. Noted as a known limitation.

## Edge Cases

- **Bootstrap on VPS where key file exists but isn't registered on GitHub** (e.g., copied from backup, partial bootstrap): `stat` check passes → generation skipped → clone uses existing key. If key isn't registered, clone fails with auth error as expected.
- **Cleanup on VPS never bootstrapped** (no `~/comadre`, no deploy key): All tasks use `failed_when: false` and `when:` guards → clean no-op.
- **Trailing newline in slurped public key**: `ansible.builtin.slurp` base64-decoded output may include a trailing `\n`. The GitHub API `key` field does not. Apply `| trim` to both sides before comparison.
- **`become` escalation on cleanup tasks**: Key files live under `/home/{{ ansible_user }}/.ssh/`. All new cleanup tasks must carry `become: false` so they don't accidentally resolve to `/root/.ssh/`.
