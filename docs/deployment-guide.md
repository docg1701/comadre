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
- `KEY_REGISTRY_ENCRYPTION_KEY` environment variable set (Fernet key — see [Bootstrap](#bootstrap----first-deployment) for generation)

Install the required Ansible collection:

```bash
ansible-galaxy collection install community.docker
```

## Inventory Configuration

Copy `deploy/ansible/inventory/production.yml.example` to `production.yml` and fill in your server details:

```yaml
all:
  hosts:
    comadre_vps:
      ansible_host: "YOUR_VPS_IP"
      ansible_user: "YOUR_SSH_USER"
      ansible_ssh_common_args: "-o ForwardAgent=yes"

  vars:
    key_registry_encryption_key: "{{ lookup('env', 'KEY_REGISTRY_ENCRYPTION_KEY') }}"
    operator_contact_hint: "Contact ops@example.com for billing."
    billing_timezone: "UTC"
    voices_local_dir: ""
    repo_url: "YOUR_REPO_URL"
    repo_branch: "master"
    default_voice: "kokoro/pm_santa"
    domain: "localhost"
    landing_enabled: true
    restart_hour: 3
    kokoro_model_url: "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
    kokoro_voices_url: "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"
    qwen3_enabled: true
    qwen3_model_url: "https://huggingface.co/PabloHoties/Qwen3-TTS-12Hz-0.6B-Base-GGUF/resolve/main/qwen3-tts-0.6b-q8_0.gguf"
    qwen3_tokenizer_url: "https://huggingface.co/PabloHoties/Qwen3-TTS-12Hz-0.6B-Base-GGUF/resolve/main/qwen3-tts-tokenizer-f16.gguf"
    qwen3_model_local: ""
    qwen3_tokenizer_local: ""
```

For Oracle Cloud Ampere A1 (aarch64) deployments, use `deploy/ansible/inventory/oracle.yml.example` as a starting point instead. It sets `qwen3_enabled: false` since the Qwen3 binary is x86_64-only, and configures a real domain for Let's Encrypt certificates.

**Variables:**

| Variable | Required | Description |
| --- | --- | --- |
| `ansible_host` | Yes | VPS IP address or hostname |
| `ansible_user` | Yes | SSH user with key-based auth |
| `key_registry_encryption_key` | Yes | Fernet key for encrypting tax IDs at rest (reads from `KEY_REGISTRY_ENCRYPTION_KEY` env var on the control machine). Maps to the `KEY_REGISTRY_ENCRYPTION_KEY` env var inside the container. |
| `operator_contact_hint` | No | Customer-facing contact string echoed in 401 hints. Maps to `OPERATOR_CONTACT_HINT`. |
| `billing_timezone` | No | IANA timezone for billing calculations and the daily suspension sweep day-boundary (default: `UTC`). Maps to `BILLING_TIMEZONE`. **This is a contractual input** — the zone you set here dictates when a customer's `paid_until` expires and their key flips to 401; communicate it formally to customers at contract time. Override to a local zone (e.g. `America/Sao_Paulo`) only when you have informed them. |
| `repo_url` | Yes | Git repository URL |
| `repo_branch` | No | Branch to deploy (default: `master`) |
| `default_voice` | No | Default voice for TTS when none specified (default: `kokoro/pm_santa`) |
| `domain` | No | Domain for Caddy HTTPS (default: `localhost` for self-signed). Set to a real domain for Let's Encrypt auto-cert. |
| `landing_enabled` | No | Deploy the public landing page at the root URL (default: `true`). When false, Caddy uses `Caddyfile-no-landing` which proxies all paths to the API. The API endpoints (`/v1/*`, `/health`, etc.) are always available regardless. |
| `qwen3_enabled` | No | Enable Qwen3 engine (default: `true`). Set `false` on hosts where the x86_64 binary cannot run (e.g. aarch64 / Oracle Cloud Ampere A1). Maps to `QWEN3_ENABLED` env var. |
| `restart_hour` | No | Daily restart hour, 0-23 (default: `3`) |
| `voices_local_dir` | No | Local directory containing `kokoro/` and `qwen/` subdirectories with voice files (empty to skip). See [voice-management.md](voice-management.md). |
| `kokoro_model_url` | No | URL to download Kokoro ONNX model on first start (default: GitHub release URL) |
| `kokoro_voices_url` | No | URL to download Kokoro voices binary on first start (default: GitHub release URL) |
| `qwen3_model_url` | No | URL to download Qwen3 GGUF model on first start (default: HuggingFace URL). Empty string skips download. |
| `qwen3_tokenizer_url` | No | URL to download Qwen3 tokenizer GGUF on first start (default: HuggingFace URL). Empty string skips download. |
| `qwen3_model_local` | No | Local path to pre-converted Qwen3 GGUF model for SCP deployment (empty to skip) |
| `qwen3_tokenizer_local` | No | Local path to pre-converted Qwen3 tokenizer GGUF for SCP deployment (empty to skip) |

## Complete Deployment Flow

A fresh deploy requires three playbooks in sequence:

```bash
cd deploy/ansible
export KEY_REGISTRY_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"

# 1. Bootstrap — installs everything, builds and starts services
ansible-playbook playbooks/bootstrap.yml -i inventory/production.yml \
  -e "ansible_become_password=YOUR_SUDO_PASS"

# 2. Deploy voices — copies voice files from local machine to VPS
ansible-playbook playbooks/deploy-voices.yml -i inventory/production.yml

# 3. Verify — read-only diagnostic check
ansible-playbook playbooks/health.yml -i inventory/production.yml

# 4. Register the first customer and issue their API key
ssh YOUR_SSH_USER@YOUR_VPS_IP "cd ~/comadre && docker compose exec tts-service \
  comadre-keys create-customer --name 'Acme Demo' --email ops@acme.example --tax-id 11144477735"
ssh YOUR_SSH_USER@YOUR_VPS_IP "cd ~/comadre && docker compose exec tts-service \
  comadre-keys issue-key --customer cust_<ulid-from-previous-step> --rpm 60 --price 149"
# The plaintext (cmdr_live_...) is printed once; copy it to your client config now.
```

After these four steps, the service is fully operational and ready to authenticate traffic.

## Available Playbooks

| Playbook | Purpose | Requires sudo |
|----------|---------|---------------|
| `bootstrap.yml` | First-time VPS setup (Docker, UFW, build, start) | Yes |
| `deploy-voices.yml` | Copy voice files to VPS (Kokoro .npy, Qwen3 .wav) | No |
| `deploy-models.yml` | Copy Qwen3 GGUF models via SCP (if not using auto-download) | No |
| `update.yml` | Pull latest code, rebuild image, restart services | No |
| `health.yml` | Read-only diagnostic (status, memory, disk, cron) | No |
| `cleanup.yml` | Full decommission: remove all artifacts and system components | Yes |

## Bootstrap -- First Deployment

Deploys Comadre on a clean Ubuntu VPS with a single command.

**What it does:**

1. Verifies the target is Ubuntu/Debian and SSH is working
2. Validates that `KEY_REGISTRY_ENCRYPTION_KEY` and `repo_url` are configured
3. Installs Docker Engine and Docker Compose v2
4. Adds the SSH user to the `docker` group
5. Installs and configures UFW firewall (ports 22, 80, 443)
6. Clones the repository to `~/comadre`
7. Creates empty voices directory structure in Docker volume
8. Creates `.env` with all configuration variables
9. Builds the Docker image and starts the service (tts-service + Caddy)
10. Configures cron jobs (daily restart, audio cleanup)
11. Waits for the health endpoint to report `healthy`

**Bootstrap does NOT deploy voice files and does NOT create customers or API keys.** Run `deploy-voices.yml` afterwards to copy voice files, and use `comadre-keys create-customer` + `comadre-keys issue-key` to populate the registry before any traffic is expected.

**Run:**

```bash
cd deploy/ansible
# Generate the registry encryption key (one-time).
export KEY_REGISTRY_ENCRYPTION_KEY="$(python -c 'from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())')"
# IMPORTANT: Store this value in your password manager. Losing it means losing
# the ability to decrypt every tax ID already in the registry.
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
Endpoint URL:    https://YOUR_VPS_DOMAIN
============================================
```

**Test the deployment (after issuing a key):**

```bash
curl -X POST https://YOUR_VPS_DOMAIN/v1/audio/speech \
  -H "Authorization: Bearer cmdr_live_YOUR_PLAINTEXT" \
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

### Registry-level health — `comadre-keys health`

`ansible-playbook health.yml` covers infrastructure (container state, disk, cron existence at the host level). **Registry-level health** — DB integrity, schema parity, permissions drift, last suspension-sweep age, cron-installed marker, auth-cache telemetry — lives in the `comadre-keys health` CLI verb that runs inside the `tts-service` container:

```bash
docker compose exec tts-service comadre-keys health              # table output
docker compose exec tts-service comadre-keys health --format json  # machine-readable
```

**Exit codes:** `0` healthy, `2` usage error, `5` DB error, `6` configuration error, **`7` unhealthy** (only in `--format json`; table mode always exits `0` — read-tier UX rule). A minimal Nagios-style check:

```bash
set -e
payload="$(docker compose exec -T tts-service comadre-keys health --format json)" && rc=$? || rc=$?
case $rc in
  0) echo "OK"; exit 0 ;;
  7) msg="$(echo "$payload" | jq -r '.checks[] | select(.severity == "warn" or .severity == "fail") | "\(.label): \(.value)"' | tr '\n' ';')"
     echo "WARNING: $msg"; exit 1 ;;
  *) echo "CRITICAL: comadre-keys health exited $rc"; exit 2 ;;
esac
```

The eight checks in each report are: `Database`, `Schema version`, `Customers`, `Keys`, `Last suspension sweep`, `Cron`, `Last backup`, `Auth cache`. `Last backup` is `info`-only until the backup playbook ships — it never flips `is_healthy` today.

## Cleanup -- Full Decommission

Removes all Comadre artifacts **and** system-level components from the VPS, restoring it to its pre-bootstrap state. This is irreversible.

**What it removes:**

Application artifacts:

- Docker containers, images, volumes, and build cache
- Cron jobs (daily-restart, audio-cleanup)
- `~/comadre` directory

System-level components (installed by bootstrap):

- Docker Engine (`docker-ce`, `docker-ce-cli`, `containerd.io`, `docker-compose-plugin`)
- Docker data directories (`/var/lib/docker`, `/var/lib/containerd`)
- Docker apt repository and GPG key
- Docker group
- UFW firewall (disabled, rules reset, package removed)
- GitHub SSH key from `known_hosts`

**What it keeps:**

- `ca-certificates`, `curl`, `gnupg` — common system utilities, safe to keep

**Run:**

```bash
cd deploy/ansible
ansible-playbook playbooks/cleanup.yml -i inventory/production.yml \
  -e "ansible_become_password=YOUR_SUDO_PASS"
```

After cleanup, the VPS is restored to its pre-bootstrap state. To redeploy, run `bootstrap.yml` again.

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

**Configuration:** The Caddyfile is at `deploy/caddy/Caddyfile`. It uses handle-based routing to serve two concerns from a single domain:

- **API paths** (`/v1/*`, `/health`, `/docs`, `/openapi.json`, `/redoc`) are reverse-proxied to `tts-service:8000` via Docker internal DNS.
- **All other paths** serve a static landing page from `/srv/www` (the `deploy/landing/` directory bind-mounted in `compose.yaml`).

For multi-replica deployments, the Caddyfile uses the `dynamic a` upstream resolver to re-query Docker DNS every 5 seconds and load-balance across all healthy replica IPs with the `least_conn` policy (queue-depth-aware: routes each request to the replica with the fewest active connections, which equals the fewest queued+in-flight TTS jobs in Comadre's single-FIFO-lock architecture). Plain `reverse_proxy host:port` resolves DNS only once at startup and would pin all traffic to a single replica — `dynamic a` is required.

A variant `deploy/caddy/Caddyfile-no-landing` exists for deployments where the landing page is disabled (`landing_enabled: false` in inventory). It proxies all paths to the API with no static file serving. The Ansible playbooks swap in the correct Caddyfile automatically based on the `landing_enabled` variable.

### Landing Page

The default Caddyfile serves a self-contained HTML page at the root URL that lets anyone with a valid API key try Comadre from a browser. Control this with the `landing_enabled` ansible variable:

- **`landing_enabled: true`** (default): Uses the standard `Caddyfile` with handle-based routing. The landing page is served at `/`, API endpoints at their usual paths.
- **`landing_enabled: false`**: Uses `Caddyfile-no-landing`, which proxies all traffic directly to the TTS service. Useful for internal/private deployments where a public-facing page is not wanted.

The API endpoints (`/v1/*`, `/health`, `/docs`, `/openapi.json`, `/redoc`) are always available regardless of the `landing_enabled` setting.

## Key Registry Management

Comadre authenticates every TTS request against a SQLite key registry encrypted with a single Fernet key (`KEY_REGISTRY_ENCRYPTION_KEY`). Customers and their API keys are managed entirely through the `comadre-keys` CLI, which runs inside the tts-service container and shares the registry volume.

### How keys work

- The registry file lives at `/var/lib/comadre/registry.db` inside the container (bind-mounted from the `comadre-registry` named volume).
- Each key row stores a SHA-256 hash of the plaintext, an 8-character display prefix, the customer id, `rate_limit_rpm`, `billing_mode`, `price_monthly`, `status`, and `paid_until`.
- Plaintext is a `cmdr_live_<random>` token shown only at issuance (and again after `rotate-key`).
- Authentication is constant-time — unknown tokens, revoked keys, and suspended/past-due keys all return 401 with the same timing profile.

### Initial bootstrap — generate and store the encryption key

```bash
# 1. Generate the Fernet key on your control machine (one-time, per deployment).
python -c "from cryptography.fernet import Fernet; print(Fernet.generate_key().decode())"
# Example output: j8F4...k2Y=

# 2. Store the value in your password manager. Losing it means every tax ID
#    already in the registry is unrecoverable.

# 3. Export it for Ansible and run bootstrap.
export KEY_REGISTRY_ENCRYPTION_KEY="j8F4...k2Y="
ansible-playbook playbooks/bootstrap.yml -i inventory/production.yml \
  -e "ansible_become_password=YOUR_SUDO_PASS"
```

Bootstrap writes `KEY_REGISTRY_ENCRYPTION_KEY` into `~/comadre/.env` on the VPS. The tts-service container reads it at startup.

### Seed the first customer and issue a key

```bash
ssh YOUR_SSH_USER@YOUR_VPS_IP "cd ~/comadre && docker compose exec tts-service \
  comadre-keys create-customer \
    --name 'Acme Demo' \
    --email ops@acme.example \
    --tax-id 11144477735"
# → cust_01jABC...

ssh YOUR_SSH_USER@YOUR_VPS_IP "cd ~/comadre && docker compose exec tts-service \
  comadre-keys issue-key \
    --customer cust_01jABC... \
    --rpm 60 \
    --billing-mode manual \
    --price 149"
# → cmdr_live_XXXXXXXXXXXXX   (printed once; paste into the client config now)
```

### Rotating a compromised key

```bash
ssh YOUR_SSH_USER@YOUR_VPS_IP "cd ~/comadre && docker compose exec tts-service \
  comadre-keys rotate-key <key-prefix-or-id>"
```

The old plaintext stops working immediately. The `key_id` is preserved, so the per-key rate-limit bucket and all billing state carry over. The new plaintext is printed once — copy it into the client config before the terminal scrolls away. No container restart is required; the registry is read at every cache miss and the cached entry for the old hash simply never matches again.

### Raising or lowering a customer's throughput

```bash
comadre-keys update-key <key-prefix> --rpm 120
```

`--rpm` accepts values in the range 1..10 000. Every `comadre-keys` mutation touches the registry invalidation sentinel, so the change takes effect on the very next request — no cache-TTL wait.

### Retiring a key

```bash
comadre-keys revoke-key <key-prefix> --reason "bundle contract ended 2026-09-30"
```

Revocation is terminal — subsequent requests return 401. Issue a fresh key with `comadre-keys issue-key` if the customer returns.

See [monetization.md](monetization.md) for the full CLI reference and lifecycle reasoning.

### LGPD operator procedures

Brazilian LGPD (Art. 18) gives customers the right to access the personal data Comadre holds about them and to request irreversible deletion. Two CLI verbs implement the operator side of that contract:

**Data-subject access request (Art. 18 II / V).** Emit a machine-readable document with the customer's name, email, decrypted tax ID (formatted), notes, and associated key prefixes:

```bash
comadre-keys export-customer <cust_id> --format json > /tmp/export.json
# or for a human-readable deliverable:
comadre-keys export-customer <cust_id> --format yaml > /tmp/export.yaml
```

The export is non-mutating — no DB rows change, no audit row is written. Forward the resulting document to the subject via the agreed channel (email, client portal, etc.).

**Deletion request (Art. 18 VI).** Permanently purge the customer's personal data and every associated API key. The command deletes all `api_key` rows, scrubs `name` / `email` / `tax_id_encrypted` / `notes` on the customer row, and stamps `deleted_at` — the tombstone row and audit-log history remain to support later ANPD inquiries (FR38 retention contract):

```bash
# Interactive (requires typing "y" at the prompt)
comadre-keys delete-customer <cust_id> --hard

# Scripted (skip the prompt — use in automation)
comadre-keys delete-customer <cust_id> --hard --yes
```

`--hard` is required. After deletion, `list-customers` no longer shows the customer; `list-customers --deleted` shows the tombstone with blank name/email columns as a signal that the row was purged.

Story 4.6 (LGPD documentation & breach runbook) consolidates these procedures into a full operator handbook once it lands; this section is the interim reference.

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

    encode gzip

    @api path /v1/* /health /docs /openapi.json /redoc
    handle @api {
        reverse_proxy {
            dynamic a { name tts-service; port 8000; refresh 5s }
            lb_policy least_conn
            trusted_proxies private_ranges
        }
    }
    handle {
        root * /srv/www
        file_server
    }

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

## Horizontal Scaling

Each Comadre instance processes one request at a time (single FIFO queue via `asyncio.Lock`). To increase throughput, add replicas instead of increasing CPU per instance.

### How to scale

Change `replicas` in `compose.yaml` and redeploy:

```yaml
deploy:
  replicas: 2    # or 3, 4, etc.
  resources:
    limits:
      cpus: "4"
      memory: 6G
```

```bash
cd ~/comadre
docker compose up -d --build
```

Caddy load-balances across all healthy replicas using the `dynamic a` upstream resolver in `deploy/caddy/Caddyfile`, which re-queries Docker DNS every 5 seconds and applies the `least_conn` policy. No Caddy configuration changes are needed when adding or removing replicas — only the `replicas` field in `compose.yaml`.

### Resource requirements per replica

| Resource | Per replica | 2 replicas | 3 replicas |
|----------|-----------|------------|------------|
| CPU      | 4 cores   | 8 cores    | 12 cores   |
| RAM      | 6 GB      | 12 GB      | 18 GB      |
| Disk     | Shared (models + voices volumes) | Same | Same |

Memory breakdown per replica: Python process with Kokoro loaded ~4.2 GB peak RSS + Qwen3 subprocess ~1.5 GB peak during inference = ~5.7 GB combined. The 6 GB limit provides ~300 MB headroom. Qwen3 has a 4-core sweet spot — beyond 4 cores per replica, diminishing returns (<2% gain).

### What is shared vs per-instance

| Component | Scope | Notes |
|-----------|-------|-------|
| Models (`comadre-models`) | Shared volume | All replicas read the same model files |
| Voices (`comadre-voices`) | Shared volume (read-only) | All replicas discover the same voices |
| Audio (`comadre-audio`) | Shared volume | Cleanup cron runs on one replica |
| FIFO queue (`asyncio.Lock`) | Per-instance | Each replica has its own queue |
| Per-key rate-limit buckets (`limits` in-memory) | Per-instance | Each replica holds its own moving-window counters. Effective RPM for a customer = `rate_limit_rpm × replicas`. |
| Auth cache (`AuthCache`) | Per-instance | 60 s TTL ceiling; every `comadre-keys` mutation touches `{KEY_REGISTRY_DB_PATH}.invalidate` and each replica's cache flushes on the next read, so a CLI change propagates across replicas synchronously when they share the registry volume. |
| Key registry SQLite | Shared volume (`comadre-registry`) | All replicas read and write the same file. |
| Health endpoint | Per-instance | Reports queue depth and memory for that replica only. |

### Caveats

- **Rate-limit buckets are per-instance.** With N replicas the effective RPM for a key is `N × rate_limit_rpm` because each replica's `limits` in-memory storage runs its own moving window. The default deploy is `replicas: 1`, so this is dormant; if you scale up, either (a) divide the intended per-key RPM by the replica count when setting `comadre-keys update-key --rpm`, or (b) accept the multiplied limit as acceptable elasticity. Shared-storage rate-limiting (Redis/SQLite) is a candidate future story. See [rate-limiting.md](rate-limiting.md).
- **Queue depth is per-instance.** The `/health` endpoint reports the queue depth of whichever replica handles the request. For cluster-wide monitoring, check all replicas or use centralized logging.
- **Audio cleanup cron** runs `docker compose exec` which targets one replica. Since the audio volume is shared, this is sufficient.
- **All replicas restart simultaneously.** The daily restart cron (`docker compose up -d --no-build`) recreates all replicas at once. Each replica loads ~3.4 GB of models on startup, causing a memory spike of `N * 3.4 GB`. With 2+ replicas on a VPS with limited RAM, this can trigger OOM kills. To mitigate, restart replicas individually: `for i in $(docker compose ps -q tts-service); do docker restart "$i"; sleep 120; done`.
- **First deployment with replicas > 1** should start with `replicas: 1` to download and cache models in the shared volume. After models are cached, scale up. Concurrent downloads from multiple replicas to the same temp file can corrupt the model.
- **Caddy blocks on all replicas healthy.** The `depends_on: condition: service_healthy` in compose.yaml means Caddy waits for every replica to pass its healthcheck before starting. If any single replica fails (e.g., OOM during concurrent model loading), Caddy never starts and the entire service is unreachable. For multi-replica deployments, consider changing to `condition: service_started`.
