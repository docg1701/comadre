#!/bin/bash
# Unban an IP from Comadre's fail2ban jail.
# Usage: sudo ./unban-ip.sh 1.2.3.4
set -euo pipefail

if [ "$(id -u)" -ne 0 ]; then
    echo "ERROR: This script must be run as root (use sudo)" >&2
    exit 1
fi

if [ $# -ne 1 ]; then
    echo "Usage: $0 <IP_ADDRESS>" >&2
    exit 1
fi

fail2ban-client set caddy-auth unbanip "$1"
echo "Unbanned $1 from caddy-auth jail."
