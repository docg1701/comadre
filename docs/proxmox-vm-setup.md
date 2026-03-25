# Proxmox VM Setup for COMADRE

Step-by-step guide for creating a Debian 13 VM on Proxmox VE to run COMADRE.

**Research date:** 2026-03-25
**Proxmox VE version:** 9.1 (released 2025-11-19, based on Debian 13 "Trixie")
**Guest OS:** Debian 13.4 "Trixie" (released 2026-03-14)

## 1. Download the Debian ISO

In the Proxmox web UI (`https://<proxmox-ip>:8006`):

1. Expand your node in the left sidebar, click **local** storage
2. Go to the **ISO Images** tab
3. Click **Download from URL**
4. Paste:

    ```text
    https://cdimage.debian.org/debian-cd/13.4.0/amd64/iso-cd/debian-13.4.0-amd64-netinst.iso
    ```

5. Click **Query URL**, then **Download**

Alternative -- download directly on the Proxmox host via SSH:

```bash
cd /var/lib/vz/template/iso/
wget https://cdimage.debian.org/debian-cd/13.4.0/amd64/iso-cd/debian-13.4.0-amd64-netinst.iso
```

## 2. Create the VM

Click **Create VM** in the top-right. Check **Advanced** at the bottom of the wizard.

### General

| Field | Value |
| --- | --- |
| Name | `comadre-tts` |

### OS

| Field | Value |
| --- | --- |
| ISO image | `debian-13.4.0-amd64-netinst.iso` |
| Type | Linux |
| Version | 6.x - 2.6 Kernel |

### System

| Field | Value | Why |
| --- | --- | --- |
| Machine | q35 | Modern chipset, better PCIe support |
| BIOS | OVMF (UEFI) | Recommended for Debian 13 |
| EFI Storage | local-lvm | Required with OVMF |
| SCSI Controller | VirtIO SCSI single | Best disk performance with IO threads |
| QEMU Agent | Enabled | Shows IP in Proxmox, graceful shutdown, backup freeze |

### Disks

| Field | Value | Why |
| --- | --- | --- |
| Bus/Device | SCSI | Uses VirtIO SCSI controller above |
| Storage | local-lvm | Or your preferred storage |
| Size | 32 GB | 20 GB minimum, 32 GB gives headroom for Docker images |
| Cache | Write back | Best performance |
| Discard | Enabled | Reclaims space via TRIM on thin-provisioned storage |
| IO Thread | Enabled | Dedicated IO thread per disk, 30-50% improvement |

### CPU

| Field | Value | Why |
| --- | --- | --- |
| Sockets | 1 | |
| Cores | 4 | Qwen3 sweet spot (diminishing returns beyond 4) |
| Type | host | Exposes AVX/AVX2/FMA to guest. 3-10% faster than kvm64 for CPU-bound inference. Only use kvm64 if you need live migration across different CPUs. |

### Memory

| Field | Value |
| --- | --- |
| Memory (MiB) | 8192 |
| Ballooning | Disabled (predictable latency for TTS inference) |

### Network

| Field | Value | Why |
| --- | --- | --- |
| Bridge | vmbr0 | VM gets LAN IP via DHCP |
| Model | VirtIO (virtio) | Paravirtualized, vastly faster than e1000 |

Click **Finish**.

## 3. Install Debian

1. Select the VM in Proxmox > **Console** > **Start**
2. Walk through the Debian installer:
   - Language, keyboard, hostname, domain (leave empty)
   - Root password (set one or leave empty for sudo-only)
   - Create a user account and password
   - Partitioning: **Guided - use entire disk** (default is fine)
   - Software selection: **uncheck** Desktop Environment, **check** SSH server and standard system utilities
3. Reboot when prompted. Proxmox auto-ejects the ISO.

## 4. Post-install configuration

### Find the VM IP

From the Proxmox console (logged in as the user you created):

```bash
ip addr show
```

Or after installing the guest agent (next step), the IP appears in Proxmox UI under VM > Summary > IPs.

### SSH key setup (from your workstation)

```bash
ssh-copy-id YOUR_USER@VM_IP
ssh YOUR_USER@VM_IP
```

### Install essentials and guest agent

```bash
sudo apt update && sudo apt upgrade -y
sudo apt install -y qemu-guest-agent htop curl git
sudo systemctl enable --now qemu-guest-agent
```

### Harden SSH

```bash
sudo sed -i 's/^#PasswordAuthentication yes/PasswordAuthentication no/' /etc/ssh/sshd_config
sudo sed -i 's/^#PermitRootLogin prohibit-password/PermitRootLogin no/' /etc/ssh/sshd_config
sudo systemctl restart sshd
```

### Install Docker (official repository)

```bash
# Remove conflicting packages
for pkg in docker.io docker-doc docker-compose podman-docker containerd runc; do
  sudo apt remove -y $pkg 2>/dev/null
done

# Add Docker GPG key
sudo install -m 0755 -d /etc/apt/keyrings
curl -fsSL https://download.docker.com/linux/debian/gpg | sudo gpg --dearmor -o /etc/apt/keyrings/docker.gpg
sudo chmod a+r /etc/apt/keyrings/docker.gpg

# Add Docker repository (uses "trixie" codename)
echo \
  "deb [arch=$(dpkg --print-architecture) signed-by=/etc/apt/keyrings/docker.gpg] https://download.docker.com/linux/debian \
  $(. /etc/os-release && echo "$VERSION_CODENAME") stable" | \
  sudo tee /etc/apt/sources.list.d/docker.list > /dev/null

# Install Docker Engine + Compose plugin
sudo apt update
sudo apt install -y docker-ce docker-ce-cli containerd.io docker-buildx-plugin docker-compose-plugin

# Add your user to the docker group
sudo usermod -aG docker $USER
```

Log out and back in for the group to take effect:

```bash
exit
ssh YOUR_USER@VM_IP
docker compose version   # Should work without sudo
```

### Performance tuning

```bash
# Disable swap (prevents unpredictable latency during inference)
sudo swapoff -a
sudo sed -i '/swap/d' /etc/fstab

# Limit Docker log size (prevents disk fill)
sudo mkdir -p /etc/docker
cat <<'EOF' | sudo tee /etc/docker/daemon.json
{
  "log-driver": "json-file",
  "log-opts": { "max-size": "10m", "max-file": "3" }
}
EOF
sudo systemctl restart docker
```

### Verify Docker and cgroup v2

```bash
docker info | grep "Storage Driver"   # Expected: overlay2
stat -fc %T /sys/fs/cgroup/           # Expected: cgroup2fs
```

Debian 13 ships with cgroup v2 enabled by default. Docker works without kernel parameter changes.

## 5. Deploy COMADRE

The VM is ready. See [local-testing-guide.md](local-testing-guide.md) for steps to build and run the service, or use Ansible from your workstation:

```bash
cd deploy/ansible

# Edit inventory with your VM's IP and SSH user
vim inventory/production.yml

# Deploy
export COMADRE_API_KEY="your-secret-key"
ansible-playbook playbooks/bootstrap.yml -i inventory/production.yml
```

## Notes

- **Nested virtualization is NOT needed.** Docker uses namespaces/cgroups, not hardware virtualization.
- **VM is the right choice** (not LXC). Docker in LXC requires privileged containers and kernel-sharing hacks. Proxmox documentation recommends VMs for Docker workloads.
- **CPU type `host`** passes through all CPU instruction sets including AVX/AVX2 and FMA, which benefits GGML-based Qwen3 inference.
- **ARM is not supported.** The `qwen3-tts-cli` binary is compiled for x86-64. ARM hosts (Oracle free tier, Raspberry Pi) require recompilation.

## VM config summary

```text
Name:    comadre-tts
OS:      Debian 13.4 "Trixie" (netinst)
Machine: q35, OVMF (UEFI)
CPU:     4 cores, type=host, 1 socket
RAM:     8192 MiB, ballooning off
Disk:    32 GB, VirtIO SCSI single, IO thread, discard, write-back cache
Network: vmbr0, VirtIO (virtio)
Agent:   QEMU Guest Agent enabled
```

## Sources

- [Proxmox VE 9.1 release announcement](https://proxmox.com/en/about/company-details/press-releases/proxmox-virtual-environment-9-1)
- [Proxmox VE downloads](https://www.proxmox.com/en/downloads/proxmox-virtual-environment)
- [Debian 13 "Trixie" release notes](https://www.debian.org/releases/trixie/)
- [Debian 13.4 ISO download](https://cdimage.debian.org/debian-cd/13.4.0/amd64/iso-cd/)
- [Docker Engine install on Debian (official)](https://docs.docker.com/engine/install/debian/)
- [Proxmox VE 9 VM template for Debian Trixie](https://forum.proxmox.com/threads/pve9-create-a-vm-template-for-a-debian-trixie-server-with-cloud-init.170206/)
- [Proxmox VM best practices](https://forum.proxmox.com/threads/best-practice-and-recommendations-for-building-vm-templates.173743/)
- [QEMU Guest Agent wiki](https://pve.proxmox.com/wiki/Qemu-guest-agent)
