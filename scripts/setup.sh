#!/usr/bin/env bash
# First-time setup on a VM (or locally). Idempotent — safe to re-run.
#   ./scripts/setup.sh
set -euo pipefail
cd "$(dirname "$0")/.."

echo "── Cue · setup ─────────────────────────────────────────"

if ! command -v docker >/dev/null 2>&1; then
  echo "✗ Docker not found. Install Docker Engine + Compose v2, then re-run."
  echo "  Ubuntu: https://docs.docker.com/engine/install/ubuntu/"
  exit 1
fi
if ! docker compose version >/dev/null 2>&1; then
  echo "✗ Docker Compose v2 not found (need 'docker compose')."
  exit 1
fi

if [ ! -f .env ]; then
  cp .env.example .env
  echo "→ created .env from .env.example"
  echo "  Edit .env to add keys (Anthropic, Clerk, Stripe, connectors) — or leave blank for the pilot."
fi

echo "→ building images + starting containers"
docker compose up -d --build

echo "→ waiting for backend to become healthy"
for _ in $(seq 1 60); do
  if curl -fsS http://localhost:8000/health >/dev/null 2>&1; then ok=1; break; fi
  sleep 2
done
[ "${ok:-}" = "1" ] || { echo "✗ backend did not become healthy; check: ./scripts/logs.sh backend"; exit 1; }

# Postgres deployments need migrations (SQLite auto-creates tables)
if grep -Eqi 'postgres' .env 2>/dev/null; then
  echo "→ applying database migrations (Postgres)"
  docker compose exec -T backend alembic upgrade head
fi

echo ""
echo "✓ Cue is up:"
echo "    Frontend  http://localhost:3000"
echo "    API       http://localhost:8000   (docs: /docs)"
echo ""
docker compose ps
