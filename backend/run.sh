#!/usr/bin/env bash
# Create venv, install deps, seed demo data, and serve the API on :8000.
set -euo pipefail
cd "$(dirname "$0")"

if [ ! -d .venv ]; then
  echo "→ creating virtualenv"
  python3 -m venv .venv
fi
# shellcheck disable=SC1091
source .venv/bin/activate

echo "→ installing dependencies"
pip install -q --upgrade pip
pip install -q -r requirements.txt

# Export backend/.env into the process so os.getenv-based config (Recall, connector
# OAuth client ids/secrets) is picked up — pydantic only loads its own Settings fields.
# NOTE: local runs read THIS file, not the repo-root .env (which is Docker-only and
# has in-container paths like DATABASE_URL=/data/...). Put local creds here.
if [ -f .env ]; then
  set -a
  # shellcheck disable=SC1091
  . ./.env
  set +a
fi

# Postgres uses Alembic-managed schema; SQLite self-creates via init_db on startup.
case "${DATABASE_URL:-}" in
  postgres*|postgresql*)
    echo "→ applying database migrations (alembic upgrade head)"
    alembic upgrade head
    ;;
esac

echo "→ starting API on http://localhost:8000  (docs: /docs)"
exec uvicorn app.main:app --reload --port 8000
