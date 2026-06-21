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

echo "→ starting API on http://localhost:8000  (docs: /docs)"
exec uvicorn app.main:app --reload --port 8000
