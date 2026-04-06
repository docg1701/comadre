# Deployment Guide

Full lifecycle management for Comadre TTS service using Ansible playbooks.

## Prerequisites

**VPS requirements:**

- 4 vCPU, 8 GB RAM minimum
- Ubuntu 22.04+ or Debian 12+
- SSH key access configured
- Ports: 80 and 443 open (Caddy HTTPS reverse proxy)

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
| `domain` | No | Domain for Caddy HTTPS (default: `localhost` for self-signed) |
| `rate_limit_speech` | No | Rate limit for speech endpoint per IP (default: `30/minute`) |
| `rate_limit_health` | No | Rate limit for health endpoint per IP (default: `60/minute`) |
| `qwen3_model_local` | No | Local path to pre-converted Qwen3 GGUF model (empty to skip) |
| `qwen3_tokenizer_local` | No | Local path to pre-converted Qwen3 tokenizer GGUF (empty to skip) |

## Complete Deployment Flow

A fresh deploy requires three playbooks in sequence:

```bash
cd deploy/ansible
export COMADRE_API_KEY="your-secret-key"

# 1. Bootstrap — installs everything, builds and starts services
ansible-playbook playbooks/bootstrap.yml -i inventory/production.yml \
  -e "ansible_become_password=YOUR_SUDO_PASS"

# 2. Deploy voices — copies voice files from local machine to VPS
ansible-playbook playbooks/deploy-voices.yml -i inventory/production.yml

# 3. Verify — read-only diagnostic check
ansible-playbook playbooks/health.yml -i inventory/production.yml
```

After these three steps, the service is fully operational with all voices available.

## Available Playbooks

| Playbook | Purpose | Requires sudo |
|----------|---------|---------------|
| `bootstrap.yml` | First-time VPS setup (Docker, UFW, build, start) | Yes |
| `deploy-voices.yml` | Copy voice files to VPS (Kokoro .npy, Qwen3 .wav) | No |
| `deploy-models.yml` | Copy Qwen3 GGUF models via SCP (if not using auto-download) | No |
| `update.yml` | Pull latest code, rebuild image, restart services | No |
| `health.yml` | Read-only diagnostic (status, memory, disk, cron) | No |
| `cleanup.yml` | Remove all Comadre artifacts from VPS | Yes |

## Bootstrap -- First Deployment

Deploys Comadre on a clean Ubuntu VPS with a single command.

**What it does:**

1. Verifies the target is Ubuntu/Debian and SSH is working
2. Validates that `API_KEY` and `repo_url` are configured
3. Installs Docker Engine and Docker Compose v2
4. Adds the SSH user to the `docker` group
5. Installs and configures UFW firewall (ports 22, 80, 443)
6. Installs and configures UFW firewall (ports 22, 80, 443)
7. Clones the repository to `~/comadre`
8. Creates empty voices directory structure in Docker volume
9. Creates `.env` with all configuration variables
10. Builds the Docker image and starts the service (tts-service + Caddy)
11. Configures cron jobs (daily restart, audio cleanup)
12. Waits for the health endpoint to report `healthy`

**Bootstrap does NOT deploy voice files.** Run `deploy-voices.yml` after bootstrap to copy voice files from your local machine to the VPS.

**Run:**

```bash
cd deploy/ansible
export COMADRE_API_KEY="your-secret-key-here"
ansible-playbook playbooks/bootstrap.yml -i inventory/production.yml \
  -e "ansible_become_password=YOUR_SUDO_PASS"
```

**Expected output on success:**

```text
TASK [[Summary] Report deployment status]
============================================
Comadre TTS Service -- Bootstrap Complete
============================================

Service Status:  healthy
Loaded Voices:   kokoro/pf_dora, kokoro/pm_alex, kokoro/pm_santa, qwen/female, qwen/galvani
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

Updates a running Comadre deployment from the latest git commit.

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

Removes all Comadre artifacts from the VPS. This is irreversible.

**What it removes:**

- Docker containers, images, and volumes (models, voices, audio)
- Cron jobs (daily-restart, audio-cleanup)
- `~/comadre` directory

**Run:**

```bash
cd deploy/ansible
ansible-playbook playbooks/cleanup.yml -i inventory/production.yml \
  -e "ansible_become_password=YOUR_SUDO_PASS"
```

After cleanup, the VPS has zero Comadre artifacts. To redeploy, run `bootstrap.yml` again.

## Model Deployment

Qwen3 GGUF models (~1.6 GB total) are too large for git. They deploy via SCP through the `deploy-models.yml` playbook.

**Prerequisites:**

- Qwen3 models must be converted locally from HuggingFace safetensors
- See [quantizing-qwen3-models.md](quantizing-qwen3-models.md) for the conversion procedure
- Two files needed: `qwen3-tts-0.6b-q8_0.gguf` (~1.3 GB) and `qwen3-tts-tokenizer-f16.gguf` (~325 MB)
- **Preferred method:** Models auto-download on first startup when `QWEN3_MODEL_URL` and `QWEN3_TOKENIZER_URL` are set in the inventory. Pre-built GGUF files are available from `PabloHoties/Qwen3-TTS-12Hz-0.6B-Base-GGUF` on HuggingFace. Manual deployment via this playbook is only needed for air-gapped environments.

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
        female.wav
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

## HTTPS via Caddy

Comadre uses Caddy as a reverse proxy for automatic HTTPS. The TTS service is only exposed internally on the Docker network — all external traffic goes through Caddy on ports 80/443.

**With a public domain (Let's Encrypt):**

Set `DOMAIN` in `.env` to your domain. Caddy automatically provisions and renews certificates:

```bash
DOMAIN=tts.example.com
```

**With a private IP (self-signed):**

Leave `DOMAIN` as `localhost` (default). Caddy generates a self-signed certificate. Clients must accept self-signed certs or use `--insecure`/`-k` with curl.

**Configuration:** The Caddyfile is at `deploy/caddy/Caddyfile`. It proxies all traffic to `tts-service:8000` with gzip compression and file-based JSON logging to /var/log/caddy/access.log.

## API Key Rotation

### How the Key Works

The API key is generated during bootstrap and stored in `~/comadre/.env` on the VPS. Clients send it as `Authorization: Bearer <key>` in every request. The key is a 256-bit random value (base64-encoded), validated with timing-safe comparison.

### Initial Setup (During Bootstrap)

The key is set before running bootstrap:

```bash
# 1. Generate a key on your local machine
openssl rand -base64 32
# Output: DlzNODuV7Ons4rLm/94NyEABzoLiHvLUH5z7eYgKhdo=

# 2. Export it for the Ansible playbook
export COMADRE_API_KEY="DlzNODuV7Ons4rLm/94NyEABzoLiHvLUH5z7eYgKhdo="

# 3. Run bootstrap — the key is written to ~/comadre/.env on the VPS
ansible-playbook playbooks/bootstrap.yml -i inventory/production.yml

# 4. Copy the key to your n8n/chatbot config — this is the only time you see it
```

### Rotating a Compromised Key

If the key is compromised, rotate it in one command:

```bash
ssh YOUR_VPS_IP "bash ~/comadre/deploy/bin/rotate-api-key.sh"
```

Output:

```text
=== New API Key (shown once) ===

  aB3xK9mP2qR7nW4vL8cJ5fT1hY6dS0gU=

=================================

Container restarted. Waiting for health check...
Service is healthy. Key rotation complete.
```

**Immediately after rotation:**

1. Copy the new key from the output
2. Update your n8n/chatbot config with the new key
3. All requests with the old key will return 401

The new key is shown only once. If you lose it, rotate again.

## Firewall (UFW)

The bootstrap playbook installs and configures UFW with minimal rules:

| Port | Protocol | Purpose |
|------|----------|---------|
| 22 | TCP | SSH access |
| 80 | TCP | HTTP (Caddy redirects to HTTPS) |
| 443 | TCP | HTTPS (Caddy reverse proxy) |

All other incoming ports are blocked. Outgoing traffic is unrestricted.

**Check status:**

```bash
ssh YOUR_VPS_IP "sudo ufw status"
```

**Temporarily open a port (e.g., for debugging):**

```bash
ssh YOUR_VPS_IP "sudo ufw allow 8080/tcp"
# ... debug ...
ssh YOUR_VPS_IP "sudo ufw delete allow 8080/tcp"
```

## IP Allowlist (Optional)

If the API is only accessed from known IPs (e.g., your n8n server), you can restrict access in the Caddyfile:

```text
{$DOMAIN:localhost} {
    @blocked not remote_ip 203.0.113.10 198.51.100.0/24
    respond @blocked 403

    reverse_proxy tts-service:8000
    encode gzip
    log {
        output stdout
        format json
    }
}
```

Replace the IPs with your allowed addresses. Restart Caddy after changes: `docker compose restart caddy`.

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
