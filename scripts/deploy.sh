#!/usr/bin/env bash
# Redeploy after code changes (e.g. `git pull`) — rebuild, migrate, restart, health-check.
#   ./scripts/deploy.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "── Cue · deploy ────────────────────────────────────────"

if [ -d .git ]; then
  echo "→ git pull"
  git pull --ff-only || echo "  (skipped: git pull failed or not needed)"
fi

echo "→ rebuilding + restarting (zero-downtime where possible)"
docker compose up -d --build

echo "→ waiting for backend health"
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
[ "${ok:-}" = "1" ] || { echo "✗ unhealthy after deploy; check: ./scripts/logs.sh backend"; exit 1; }

if grep -Eqi 'postgres' .env 2>/dev/null; then
  echo "→ applying database migrations"
  docker compose exec -T backend alembic upgrade head
fi

echo "✓ deployed — $(curl -fsS http://localhost:8000/health)"
docker compose ps
