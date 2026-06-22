#!/usr/bin/env bash
# Tail container logs.  ./scripts/logs.sh [backend|frontend]
cd "$(dirname "$0")/.."
docker compose logs -f --tail=120 "$@"
