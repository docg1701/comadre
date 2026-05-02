# Implementation Plan — Deploy Key Migration

## Goal

Replace SSH agent forwarding with a dedicated read-only GitHub deploy key for
Ansible git operations. A GitHub Personal Access Token (classic, `repo` scope)
is used **only at bootstrap time** to register the deploy key via the GitHub
API. The PAT is stored as an Ansible Vault-encrypted variable, following the
exact same pattern used by radtracker.

## Motivation

| Concern | Agent forwarding (current) | Deploy key (target) |
|---|---|---|
| Privilege scope | Operator's entire GitHub identity exposed on VPS | Read-only access to exactly one repo |
| Attack surface | `SSH_AUTH_SOCK` socket lives on VPS during whole Ansible session (up to 45 min for bootstrap) | Private key on disk (`0600`), used only during `git` tasks |
| Key rotation resilience | Operator rotating personal key breaks the VPS until re-bootstrap | Deploy key is independent of operator identity |
| Idempotent updates | `update.yml` requires agent forwarding (`ssh-add` first) | `update.yml` works standalone — no operator-side prep beyond SSH access |

## Reference implementation

Radtracker's `deploy.yml` at `/home/galvani/dev/radtracker/ansible/playbooks/deploy.yml`
already uses this pattern successfully:

- `community.crypto.openssh_keypair` to generate a VPS-local ed25519 keypair
- `ansible.builtin.uri` to POST the public key to `https://api.github.com/repos/<owner>/<repo>/keys` (201/422 for idempotency)
- `ansible.builtin.git` with `key_file` + `accept_hostkey: true`
- PAT from Ansible Vault (`github_pat` variable in `group_vars/all.yml`)
- Deploy key title: `"radtracker-vps"` (hardcoded)
- API URL: hardcoded `https://api.github.com/repos/docg1701/radtracker/keys`

Comadre follows the same pattern.

---

## Tasks

### 1. Add `community.crypto` collection dependency

**File**: `deploy/ansible/requirements.yml`

**Change**: Add `community.crypto` entry.

```yaml
collections:
  - name: community.docker
    version: ">=3.0.0"
  - name: community.crypto
    version: ">=2.0.0"
  - name: community.general
    version: ">=8.0.0"
```

### 2. Add `github_repo_path` and `deploy_key_path` to inventory (4 files)

#### 2a. `production.yml.example`

**File**: `deploy/ansible/inventory/production.yml.example`

**Changes**:

- Remove `ansible_ssh_common_args: "-o ForwardAgent=yes"` from the host block
- Add two new variables in the `vars:` section and document how to encrypt `github_pat`:

```yaml
# Path to SSH deploy key generated on VPS for GitHub access
deploy_key_path: "/home/{{ ansible_user }}/.ssh/comadre_deploy"

# GitHub repository path as "owner/repo" — used to construct the API URL
# for deploy key registration (e.g. "docg1701/comadre")
github_repo_path: "CHANGE_ME"

# GitHub Personal Access Token (classic) with 'repo' scope.
# Used ONCE at bootstrap to register the deploy key via API. After
# registration the PAT can expire with zero impact.
# Encrypt with:
#   ansible-vault encrypt_string "ghp_YOUR_TOKEN" --name github_pat
# Then copy the output (!vault | ...) and replace the block below.
# Also create a vault password file:
#   echo -n "your_vault_password" > deploy/ansible/.vault_pass && chmod 600 deploy/ansible/.vault_pass
github_pat: !vault |
          $ANSIBLE_VAULT;1.1;AES256
          CHANGE_ME
```

#### 2b. `production.yml`

**File**: `deploy/ansible/inventory/production.yml`

**Changes**: Same as 2a.

#### 2c. `oracle.yml.example`

**File**: `deploy/ansible/inventory/oracle.yml.example`

**Changes**: Same as 2a.

#### 2d. `deploy/ansible/.vault_pass`

**New file**: `deploy/ansible/.vault_pass` — store the Vault password (already in `.gitignore` if it exists; create the `.gitignore` entry if needed).

### 3. Replace `[Git]` section in `bootstrap.yml`

**File**: `deploy/ansible/playbooks/bootstrap.yml`

**Change**: Delete both existing tasks under `# Git Clone`:

- `[Git] Add GitHub to known_hosts`
- `[Git] Clone Comadre repository`

Replace with:

```yaml
    # =========================================================================
    # GitHub Deploy Key Setup
    # =========================================================================

    - name: "[Git] Generate deploy key for GitHub access"
      community.crypto.openssh_keypair:
        path: "{{ deploy_key_path }}"
        type: ed25519
        comment: "comadre-deploy"
      become: false

    - name: "[Git] Read deploy public key"
      ansible.builtin.slurp:
        src: "{{ deploy_key_path }}.pub"
      register: pubkey_content
      become: false

    - name: "[Git] Register deploy key with GitHub"
      ansible.builtin.uri:
        url: "https://api.github.com/repos/{{ github_repo_path }}/keys"
        method: POST
        headers:
          Authorization: "Bearer {{ github_pat }}"
          Accept: "application/vnd.github+json"
        body:
          title: "comadre-vps"
          key: "{{ pubkey_content.content | b64decode }}"
          read_only: true
        body_format: json
        status_code: [201, 422]
      register: deploy_key_result
      no_log: true
      become: false
      changed_when: deploy_key_result.status == 201

    - name: "[Git] Clone Comadre repository via deploy key"
      ansible.builtin.git:
        repo: "{{ repo_url }}"
        dest: "~/comadre"
        version: "{{ repo_branch }}"
        key_file: "{{ deploy_key_path }}"
        accept_hostkey: true
        force: true
        update: true
      become: false
```

**Design notes** (matching radtracker):

- Deploy key title is `"comadre-vps"` (hardcoded, like radtracker's `"radtracker-vps"`)
- `github_repo_path` is a config variable like `"docg1701/comadre"` — no URL parsing
- `status_code: [201, 422]` makes re-bootstrap idempotent (422 = key already exists is non-fatal)
- `no_log: true` prevents the PAT from appearing in Ansible output
- `accept_hostkey: true` eliminates the need for the separate `known_hosts` task
- All four tasks run `become: false` (they operate in the user's home directory)
- `changed_when: deploy_key_result.status == 201` — only reports "changed" on first creation

### 4. Update git pull in `update.yml`

**File**: `deploy/ansible/playbooks/update.yml`

**Change**: Replace the `[Git] Pull latest changes` task:

```yaml
    - name: "[Git] Pull latest changes via deploy key"
      ansible.builtin.git:
        repo: "{{ repo_url }}"
        dest: "~/comadre"
        version: "{{ repo_branch }}"
        key_file: "{{ deploy_key_path }}"
        accept_hostkey: true
        force: true
        update: true
      become: false
```

### 5. Remove `[Git] Remove GitHub from known_hosts` from `cleanup.yml`, add deploy key removal

**File**: `deploy/ansible/playbooks/cleanup.yml`

**Changes**:

- Delete the existing `[Git] Remove GitHub from known_hosts` task (no longer created by bootstrap)
- Add a new task after the cron removal section:

```yaml
    # =========================================================================
    # Remove Deploy Key
    # =========================================================================

    - name: "[Git] Remove deploy key from VPS"
      ansible.builtin.file:
        path: "{{ item }}"
        state: absent
      loop:
        - "{{ deploy_key_path }}"
        - "{{ deploy_key_path }}.pub"
```

- Update the `[Summary]` output: remove the "GitHub SSH key removed from known_hosts" line, add "Deploy key files removed".

**Note**: The deploy key on GitHub's side is NOT removed programmatically (PAT may be expired). Operators should manually remove it from the repo's Settings → Deploy keys if desired.

### 6. Update `docs/deployment-guide.md`

**File**: `docs/deployment-guide.md`

**Changes**:

- **Prerequisites**: Add `community.crypto` to the collection install command; add PAT generation + Vault encryption steps
- **Inventory example block**: Remove `ansible_ssh_common_args: "-o ForwardAgent=yes"`, add `deploy_key_path`, `github_repo_path`, `github_pat`
- **Variables table**: Add rows for `deploy_key_path`, `github_repo_path`, `github_pat`
- **Bootstrap "What it does" step 6**: Replace "Clones the repository" with "Generates SSH deploy key, registers it with GitHub, and clones the repository"
- **Bootstrap run command**: Add `--vault-password-file deploy/ansible/.vault_pass` to the example command. Add PAT encryption steps before the run command.
- **Update section**: Note deploy key auth is used (no agent forwarding needed)
- **Cleanup section**: Mention deploy key file removal and manual GitHub-side cleanup
- **Troubleshooting**: Add a "Deploy key não registra no GitHub" section (like radtracker's)

---

## Files Modified

| File | Change |
|---|---|
| `deploy/ansible/requirements.yml` | Add `community.crypto` collection |
| `deploy/ansible/inventory/production.yml.example` | Remove `ForwardAgent=yes`, add `deploy_key_path`, `github_repo_path`, `github_pat` |
| `deploy/ansible/inventory/production.yml` | Same as example |
| `deploy/ansible/inventory/oracle.yml.example` | Same as example |
| `deploy/ansible/.vault_pass` | New file (`.gitignore`d) |
| `deploy/ansible/playbooks/bootstrap.yml` | Replace git section with deploy key tasks |
| `deploy/ansible/playbooks/update.yml` | Add `key_file` + `accept_hostkey` + `become: false` |
| `deploy/ansible/playbooks/cleanup.yml` | Remove known_hosts task, add deploy key removal |
| `docs/deployment-guide.md` | Document new flow, new vars, new prerequisites |

## New Files

| File | Purpose |
|---|---|
| `deploy/ansible/.vault_pass` | Ansible Vault password file (`.gitignore`d) |

## Execution Order

1. Tasks 1 and 2 are independent
2. Task 3 depends on tasks 1 (collection installed) and 2 (variables defined)
3. Task 4 depends on task 3 only conceptually (update.yml uses the deploy key generated by bootstrap.yml)
4. Tasks 5 and 6 can be done anytime after 2

## Risks

1. **PAT expiration before re-bootstrap**: If an operator re-runs `bootstrap.yml` on an existing VPS with an expired PAT, the deploy key registration step fails with 401. Since the deploy key already exists, the 422 path normally handles idempotency — but 422 only fires if the key is still registered. If someone manually deleted it from GitHub and the PAT is also expired, bootstrap fails. Solution: generate a new PAT, re-encrypt, re-run. This is a rare edge case (deploy key deleted + PAT expired simultaneously).

2. **`community.crypto` requires `cryptography`**: The `openssh_keypair` module needs the `cryptography` Python package on the control machine. Most Ansible installations include it; if missing, `pip install cryptography`. Document in prerequisites.

3. **Transition for existing VPS deployments**: An existing VPS bootstrapped with the old pattern has no deploy key file. The first `update.yml` run after this migration will fail because `key_file` points to a non-existent file. Solution: the first update after migration MUST be preceded by a one-time re-run of `bootstrap.yml` (which will generate the deploy key, register it, and pull the repo). Alternatively, generate the deploy key manually on the VPS before running `update.yml`.

4. **`.vault_pass` file must exist**: If the operator runs the playbook without `--vault-password-file` and without the `.vault_pass` file, Ansible prompts interactively for the Vault password. The file makes it non-interactive. The `.gitignore` must include `.vault_pass` to prevent accidentally committing it.
