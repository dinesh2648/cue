#!/usr/bin/env bash
# Redeploy Cue on the VM (sub-path hosting, e.g. /cue). Pull, rebuild backend + frontend,
# restart, and health-check.  Usage:  ./scripts/deploy.sh
#
# The frontend's NEXT_PUBLIC_* (basePath, API URL) are inlined at BUILD time, so the frontend
# must be rebuilt — and the build arg is forced through (compose's bake backend can otherwise
# drop it). Postgres migrations run automatically from the backend entrypoint on start.
set -euo pipefail
cd "$(dirname "$0")/.."

# basePath: from the environment, else from .env, else default to /cue.
BASE_PATH="${BASE_PATH:-$(grep -E '^BASE_PATH=' .env 2>/dev/null | head -1 | cut -d= -f2- | tr -d '"' || true)}"
BASE_PATH="${BASE_PATH:-/cue}"

echo "── Cue · deploy (BASE_PATH=${BASE_PATH}) ────────────────────"

echo "→ git pull"
git pull --ff-only || echo "  (skipped: git pull failed or not needed)"

echo "→ build backend"
docker compose --profile full build backend

echo "→ build frontend (basePath baked in)"
BASE_PATH="$BASE_PATH" COMPOSE_BAKE=false docker compose --profile full build frontend

echo "→ up -d"
docker compose --profile full up -d

echo "→ waiting for backend health"
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
[ "${ok:-}" = "1" ] || { echo "✗ unhealthy after deploy; check: docker compose --profile full logs backend"; exit 1; }

echo "✓ deployed — $(curl -fsS http://localhost:8000/health)"
docker compose --profile full ps
