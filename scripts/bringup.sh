#!/usr/bin/env bash
# One-command local bring-up: backend (:8000) + frontend (:3000), and — only if Recall live
# capture is configured — a public cloudflared tunnel wired into RECALL_PUBLIC_URL.
#
# OAuth / connector reconnect does NOT need the tunnel: APP_BASE_URL is stable localhost, so
# "Connect / Reconnect" on the Connections page just works. The tunnel is only for Recall's
# inbound transcript webhook (live meeting bots).
#
# Usage:  ./scripts/bringup.sh            # backend + frontend (+ tunnel if RECALL_API_KEY set)
#         ./scripts/bringup.sh --no-tunnel
set -euo pipefail
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
cd "$ROOT"

WANT_TUNNEL=1
[ "${1:-}" = "--no-tunnel" ] && WANT_TUNNEL=0

LOGS="$ROOT/.bringup-logs"; mkdir -p "$LOGS"

# Load RECALL_API_KEY from backend/.env (without exporting secrets to the terminal).
RECALL_SET=0
if grep -qE '^RECALL_API_KEY=.+' backend/.env 2>/dev/null; then RECALL_SET=1; fi

stop_existing() {
  # Free the ports so re-running bringup is clean.
  for port in 8000 3000; do
    pid=$(lsof -nP -iTCP:$port -sTCP:LISTEN -t 2>/dev/null || true)
    [ -n "$pid" ] && { echo "  stopping existing :$port (pid $pid)"; kill "$pid" 2>/dev/null || true; }
  done
  pkill -f "cloudflared tunnel" 2>/dev/null || true
  sleep 1
}

echo "▶ Bringing up Cue…"
stop_existing

# 1) Optional Recall tunnel — start FIRST so we can wire its URL before the backend boots.
if [ "$WANT_TUNNEL" = "1" ] && [ "$RECALL_SET" = "1" ] && command -v cloudflared >/dev/null 2>&1; then
  echo "▶ Starting cloudflared tunnel for Recall webhook…"
  : > "$LOGS/tunnel.log"
  cloudflared tunnel --url http://localhost:8000 > "$LOGS/tunnel.log" 2>&1 &
  # Wait for the public hostname to appear in the log.
  TUNNEL_URL=""
  for i in $(seq 1 30); do
    TUNNEL_URL=$(grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com' "$LOGS/tunnel.log" | head -1 || true)
    [ -n "$TUNNEL_URL" ] && break
    sleep 1
  done
  if [ -n "$TUNNEL_URL" ]; then
    echo "  tunnel: $TUNNEL_URL  → RECALL_PUBLIC_URL"
    # Write RECALL_PUBLIC_URL into backend/.env (run.sh exports it for the backend process).
    python3 - "$TUNNEL_URL" <<'PY'
import sys, pathlib
url = sys.argv[1]
p = pathlib.Path("backend/.env"); lines = p.read_text().splitlines(); out=[]; done=False
for ln in lines:
    if ln.startswith("RECALL_PUBLIC_URL="):
        out.append(f"RECALL_PUBLIC_URL={url}"); done=True
    else:
        out.append(ln)
if not done: out.append(f"RECALL_PUBLIC_URL={url}")
p.write_text("\n".join(out) + "\n")
PY
  else
    echo "  ⚠ tunnel URL not detected (see $LOGS/tunnel.log) — Recall live capture may not reach us"
  fi
else
  [ "$WANT_TUNNEL" = "1" ] && [ "$RECALL_SET" = "0" ] && echo "  (no RECALL_API_KEY → skipping tunnel; OAuth/prep don't need it)"
fi

# 2) Backend (run.sh applies migrations + exports backend/.env + serves :8000 with --reload).
echo "▶ Starting backend on :8000…"
( cd backend && bash run.sh > "$LOGS/backend.log" 2>&1 & )

# 3) Frontend (:3000).
echo "▶ Starting frontend on :3000…"
( npm --prefix frontend run dev > "$LOGS/frontend.log" 2>&1 & )

# 4) Wait for health.
echo -n "▶ Waiting for backend"; for i in $(seq 1 90); do curl -s http://127.0.0.1:8000/health >/dev/null 2>&1 && break; echo -n "."; sleep 1; done; echo
echo -n "▶ Waiting for frontend"; for i in $(seq 1 60); do curl -s -o /dev/null http://127.0.0.1:3000 2>/dev/null && break; echo -n "."; sleep 1; done; echo

echo ""
echo "✅ Up:"
echo "   • App:      http://localhost:3000"
echo "   • API:      http://localhost:8000  (docs: /docs)"
echo "   • Logs:     $LOGS/{backend,frontend,tunnel}.log"
echo ""
echo "🔌 Reconnect a connector at http://localhost:3000 → Connections. OAuth uses localhost,"
echo "   so it works without a tunnel. If you still get redirect_uri_mismatch, register these"
echo "   EXACT redirect URIs in the provider's OAuth client (Google Cloud Console etc.):"
echo "     http://localhost:8000/api/auth/google/callback"
echo "     http://localhost:8000/api/connectors/gmail/callback"
echo "     http://localhost:8000/api/connectors/google_drive/callback"
echo "     http://localhost:8000/api/connectors/google_calendar/callback"
echo "     http://localhost:8000/api/connectors/hubspot/callback"
echo "     http://localhost:8000/api/connectors/notion/callback"
