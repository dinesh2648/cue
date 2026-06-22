#!/usr/bin/env bash
# Stop containers (data volumes are preserved).  ./scripts/stop.sh
set -euo pipefail
cd "$(dirname "$0")/.."
docker compose down
echo "✓ stopped (volumes kept; run ./scripts/setup.sh to start again)"
