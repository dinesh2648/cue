#!/bin/sh
# Container startup: for Postgres, wait for the DB and apply migrations before serving; for
# SQLite (or unset) the app creates its schema on startup, so skip alembic. Makes
# `docker compose --profile full up` one-command — no manual migrate, no startup race.
set -e

case "${DATABASE_URL:-}" in
  sqlite*|"")
    echo "[entrypoint] SQLite/default DB — schema auto-creates on startup; skipping alembic."
    ;;
  *)
    echo "[entrypoint] Waiting for database and applying migrations (alembic upgrade head)…"
    n=0
    until alembic upgrade head; do
      n=$((n + 1))
      if [ "$n" -ge 30 ]; then
        echo "[entrypoint] Database not reachable / migrations failed after $n attempts — giving up." >&2
        exit 1
      fi
      echo "[entrypoint]   DB not ready (attempt $n/30) — retrying in 2s…"
      sleep 2
    done
    echo "[entrypoint] Migrations applied."
    ;;
esac

echo "[entrypoint] Starting API on :8000"
# --proxy-headers + trust all forwarders: correct client IP/scheme when behind nginx.
exec uvicorn app.main:app --host 0.0.0.0 --port 8000 --proxy-headers --forwarded-allow-ips="*"
