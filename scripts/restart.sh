#!/usr/bin/env bash
# Restart services without rebuilding (e.g. after editing .env).
#   ./scripts/restart.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "→ restarting Cue containers"
docker compose up -d            # picks up .env changes; recreates only if needed
docker compose restart

echo "→ waiting for backend health"
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
[ "${ok:-}" = "1" ] && echo "✓ restarted" || { echo "✗ unhealthy; check: ./scripts/logs.sh backend"; exit 1; }
docker compose ps
