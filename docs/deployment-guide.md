# Deployment Guide

Full lifecycle management for COMADRE TTS service using Ansible playbooks.

## Prerequisites

**VPS requirements:**

- 4 vCPU, 8 GB RAM minimum
- Ubuntu 22.04+ or Debian 12+
- SSH key access configured
- Ports: service port (default 8000) open for your network

**Control machine requirements:**

- Ansible 2.14+ installed
- `community.docker` Ansible collection installed
- SSH access to the VPS
- `COMADRE_API_KEY` environment variable set

Install the required Ansible collection:

```bash
ansible-galaxy collection install community.docker
```

## Inventory Configuration

Edit `deploy/ansible/inventory/production.yml` with your server details:

```yaml
all:
  hosts:
    comadre_vps:
      ansible_host: "YOUR_VPS_IP"
      ansible_user: "YOUR_SSH_USER"

  vars:
    api_key_value: "{{ lookup('env', 'COMADRE_API_KEY') }}"
    voices_local_dir: ""
    repo_url: "YOUR_REPO_URL"
    repo_branch: "master"
    port: 8000
    restart_hour: 3
    qwen3_model_local: ""
    qwen3_tokenizer_local: ""
```

**Variables:**

| Variable | Required | Description |
| --- | --- | --- |
| `ansible_host` | Yes | VPS IP address |
| `ansible_user` | Yes | SSH user with key-based auth |
| `api_key_value` | Yes | API authentication key (reads from `COMADRE_API_KEY` env var) |
| `repo_url` | Yes | Git repository URL |
| `repo_branch` | No | Branch to deploy (default: `master`) |
| `port` | No | Service port (default: `8000`) |
| `restart_hour` | No | Daily restart hour, 0-23 (default: `3`) |
| `voices_local_dir` | No | Local directory containing `kokoro/` and `qwen/` subdirectories with voice files (empty to skip). See [voice-management.md](voice-management.md). |
| `qwen3_model_local` | No | Local path to pre-converted Qwen3 GGUF model (empty to skip) |
| `qwen3_tokenizer_local` | No | Local path to pre-converted Qwen3 tokenizer GGUF (empty to skip) |

## Bootstrap -- First Deployment

Deploys COMADRE on a clean Ubuntu VPS with a single command.

**What it does:**

1. Verifies the target is Ubuntu/Debian and SSH is working
2. Validates that `API_KEY` and `repo_url` are configured
3. Installs Docker Engine and Docker Compose v2
4. Adds the SSH user to the `docker` group
5. Clones the repository to `~/comadre`
6. Deploys voice files to voices volume (if `voices_local_dir` is configured)
7. Creates `.env` with API_KEY, DEFAULT_VOICE, and PORT
8. Builds the Docker image and starts the service
9. Configures cron jobs (daily restart, audio cleanup)
10. Waits for the health endpoint to report `healthy`

**Run:**

```bash
cd deploy/ansible
export COMADRE_API_KEY="your-secret-key-here"
ansible-playbook playbooks/bootstrap.yml -i inventory/production.yml
```

**Expected output on success:**

```text
TASK [[Summary] Report deployment status]
============================================
COMADRE TTS Service -- Bootstrap Complete
============================================

Service Status:  healthy
Loaded Voices:   kokoro/pf_dora, kokoro/pm_alex, kokoro/pm_santa, qwen/female-reference, qwen/galvani
Endpoint URL:    http://YOUR_VPS_IP:8000
============================================
```

**Test the deployment:**

```bash
curl -X POST http://YOUR_VPS_IP:8000/v1/audio/speech \
  -H "Authorization: Bearer YOUR_API_KEY" \
  -H "Content-Type: application/json" \
  -d '{"input":"Ola mundo", "voice":"kokoro/pm_santa"}' \
  --output test.ogg
```

The playbook is idempotent -- safe to run multiple times.

## Update -- Deploy New Version

Updates a running COMADRE deployment from the latest git commit.

**What it does:**

1. Verifies `~/comadre` exists and the service is running
2. Pulls latest changes from git
3. Rebuilds the Docker image and restarts the service
4. Waits for the health endpoint to report `healthy`
5. Reports actionable error if health check fails

**What it preserves:**

- Docker volumes (models, voices, audio) are not affected
- `.env` file is not modified
- Cron jobs remain unchanged

**Run:**

```bash
cd deploy/ansible
ansible-playbook playbooks/update.yml -i inventory/production.yml
```

**If the health check fails after update**, the playbook prints recovery steps:

1. Check logs: `docker compose -f ~/comadre/compose.yaml logs --tail=50`
2. Check status: `docker compose -f ~/comadre/compose.yaml ps`
3. Try restart: `docker compose -f ~/comadre/compose.yaml restart`
4. Roll back: `cd ~/comadre && git log --oneline -5` then `git checkout <previous-commit> && docker compose up -d --build`

## Health -- Diagnostic Report

Read-only diagnostic tool for troubleshooting. Never modifies anything.

**What it reports:**

- Container state (running or not)
- Health endpoint response (status, voices, engines, memory, uptime)
- Disk usage (root filesystem and audio volume)
- Cron job status (daily restart and audio cleanup)

**Warnings triggered automatically:**

- Memory usage above 5 GB
- Disk usage above 80%
- Qwen3 engine not loaded (missing GGUF models or voice files)

**Run:**

```bash
cd deploy/ansible
ansible-playbook playbooks/health.yml -i inventory/production.yml
```

## Cleanup -- Full Decommission

Removes all COMADRE artifacts from the VPS. This is irreversible.

**What it removes:**

- Docker containers, images, and volumes (models, voices, audio)
- Cron jobs (daily-restart, audio-cleanup)
- `~/comadre` directory

**Run:**

```bash
cd deploy/ansible
ansible-playbook playbooks/cleanup.yml -i inventory/production.yml
```

After cleanup, the VPS has zero COMADRE artifacts. To redeploy, run `bootstrap.yml` again.

## Model Deployment

Qwen3 GGUF models (~1.6 GB total) are too large for git. They deploy via SCP through the `deploy-models.yml` playbook.

**Prerequisites:**

- Qwen3 models must be converted locally from HuggingFace safetensors
- See [quantizing-qwen3-models.md](quantizing-qwen3-models.md) for the conversion procedure
- Two files needed: `qwen3-tts-0.6b-q8_0.gguf` (~1.3 GB) and `qwen3-tts-tokenizer-f16.gguf` (~325 MB)

**Configure inventory:**

```yaml
qwen3_model_local: "/path/to/qwen3-tts-0.6b-q8_0.gguf"
qwen3_tokenizer_local: "/path/to/qwen3-tts-tokenizer-f16.gguf"
```

**Run:**

```bash
cd deploy/ansible
ansible-playbook playbooks/deploy-models.yml -i inventory/production.yml
```

The playbook copies files to a staging directory on the VPS, then deploys them into the `comadre-models` Docker volume using a temporary helper container. Staging files are cleaned up automatically.

After deployment, restart the service to load the new models:

```bash
ssh YOUR_SSH_USER@YOUR_VPS_IP "cd ~/comadre && docker compose restart"
```

**Alternative: auto-download.** If you set `QWEN3_MODEL_URL` and `QWEN3_TOKENIZER_URL` in `.env`, the application downloads models automatically on first start. This is slower but requires no manual file transfer.

## Voice Deployment

Voices are discovered from the filesystem at runtime. No environment variable configuration is needed for individual voices -- just place files in the correct directory. For full details, see [voice-management.md](voice-management.md).

**Deploy voices via Ansible:**

1. Set `voices_local_dir` in inventory to a local directory containing `kokoro/` and/or `qwen/` subdirectories:

    ```yaml
    voices_local_dir: "/path/to/my-voices"
    ```

    Directory structure:

    ```text
    /path/to/my-voices/
      kokoro/          # .npy voice profiles (optional)
      qwen/            # .wav reference audio (optional)
        galvani.wav
        female-reference.wav
    ```

2. Run bootstrap (for first deploy) or the `deploy-voices.yml` playbook:

    ```bash
    cd deploy/ansible
    ansible-playbook playbooks/deploy-voices.yml -i inventory/production.yml
    ```

3. Voices are available immediately -- no restart needed.

**Requirements for Qwen3 reference WAVs:**

- Duration: 3-10 seconds
- Format: WAV, mono, 16kHz or higher sample rate
- Content: clear speech in the target voice, minimal background noise

**Seed reproducibility:** Qwen3-TTS supports seed values for consistent voice characteristics across generations. The same seed + reference WAV produces similar voice quality.

## Daily Restart

The bootstrap playbook configures a user-level crontab entry that restarts the service daily. This is a precaution against potential memory leaks in long-running TTS inference.

**Default schedule:** 3:00 AM (configurable via `restart_hour` in inventory)

**Cron entries installed by bootstrap:**

- `comadre-daily-restart` -- restarts at the configured hour
- `comadre-audio-cleanup` -- every 6 hours, deletes audio files older than 24 hours

Verify cron is active:

```bash
ssh YOUR_SSH_USER@YOUR_VPS_IP "crontab -l | grep comadre"
```
