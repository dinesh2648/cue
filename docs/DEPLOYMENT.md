# Deployment & operations (VM)

Cue ships as two containers (backend + frontend) orchestrated by Docker Compose.
Everything is driven by a single root `.env`.

## First-time setup on the VM

```bash
git clone <your-repo> cue && cd cue
cp .env.example .env          # edit: keys + public URLs (or leave blank for a pilot)
./scripts/setup.sh            # builds images, starts containers, waits for health, migrates
```

That's it — frontend on `:3000`, API on `:8000`. Put a reverse proxy (Caddy/Nginx) in
front for TLS and your domain.

### Production `.env` essentials
- `PUBLIC_API_URL`, `APP_BASE_URL`, `FRONTEND_URL`, `CORS_ORIGINS` → your real https domain(s).
- `TOKEN_ENCRYPTION_KEY` → a strong secret (**required**).
- `ANTHROPIC_API_KEY` (real Claude), `CLERK_*` (SSO), `STRIPE_*` (billing), provider OAuth, `RECALL_API_KEY` — as needed.
- **Postgres:** set `DATABASE_URL=postgresql+psycopg://copilot:copilot@postgres:5432/copilot` and run with the data services:
  ```bash
  docker compose --profile full up -d --build
  ./scripts/migrate.sh
  ```

## Day-2 operations

| Task | Command |
|---|---|
| **Deploy new version** (after `git pull`) | `./scripts/deploy.sh` |
| **Restart** (e.g. after editing `.env`) | `./scripts/restart.sh` |
| **Apply DB migrations** (Postgres) | `./scripts/migrate.sh` |
| **Tail logs** | `./scripts/logs.sh` (or `… backend` / `… frontend`) |
| **Stop** (keep data) | `./scripts/stop.sh` |
| **Status** | `docker compose ps` |

`scripts/deploy.sh` is the redeploy path: `git pull` → rebuild changed images →
restart → health-check → migrate (Postgres). `restart: unless-stopped` means containers
survive VM reboots.

## Notes
- **Data**: SQLite lives in the `backenddata` volume; Postgres in `pgdata`. Back these up.
- **Health**: backend `/health`; compose has a healthcheck and the frontend waits for it.
- **Scale**: bump uvicorn workers / run multiple backend replicas behind the proxy; move
  rate-limit + realtime fan-out to Redis (`REDIS_URL`) for multi-instance.
- **Rollback**: redeploy the previous git tag/commit (`git checkout <tag> && ./scripts/deploy.sh`).
- **TLS/domain**: terminate at a reverse proxy; point it at `:3000` (app) and `:8000` (API),
  and set the `*_URL` env to the public https addresses, then rebuild (frontend bakes `PUBLIC_API_URL`).
