#!/bin/bash
# Rotate the Comadre API key without redeployment.
# Usage: ssh your-vps "bash ~/comadre/deploy/bin/rotate-api-key.sh"
set -euo pipefail

COMADRE_DIR="${COMADRE_DIR:-$HOME/comadre}"
ENV_FILE="$COMADRE_DIR/.env"

if [ ! -f "$ENV_FILE" ]; then
    echo "ERROR: $ENV_FILE not found" >&2
    exit 1
fi

NEW_KEY=$(openssl rand -base64 32)

sed -i "s|^API_KEY=.*|API_KEY=$NEW_KEY|" "$ENV_FILE"

echo ""
echo "=== New API Key (shown once) ==="
echo ""
echo "  $NEW_KEY"
echo ""
echo "================================="
echo ""

cd "$COMADRE_DIR"
docker compose up -d --no-build tts-service
echo "Container restarted. Waiting for health check..."

for _ in $(seq 1 30); do
    if curl -sf http://localhost:8000/health > /dev/null 2>&1; then
        echo "Service is healthy. Key rotation complete."
        exit 0
    fi
    sleep 2
done

echo "WARNING: Service did not become healthy within 60s." >&2
echo "Check: docker compose logs --tail 20" >&2
exit 1
