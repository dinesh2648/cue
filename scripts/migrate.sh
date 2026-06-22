#!/usr/bin/env bash
# Apply database migrations (Postgres). SQLite auto-creates tables, so this is a no-op there.
#   ./scripts/migrate.sh
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose exec -T backend alembic upgrade head
echo "✓ migrations applied (alembic upgrade head)"
