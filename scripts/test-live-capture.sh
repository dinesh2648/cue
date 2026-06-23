#!/usr/bin/env bash
# Validate the LIVE meeting-capture pipeline WITHOUT Recall.ai or a real call.
# It posts the exact transcript.data webhook events Recall sends from a Google Meet
# to /api/webhooks/recall, then shows the transcript + generated suggestions.
#   ./scripts/test-live-capture.sh            (defaults to http://localhost:8000)
#   API=https://your-vm ./scripts/test-live-capture.sh
set -euo pipefail
API="${API:-http://localhost:8000}"

MID=$(curl -fsS -X POST "$API/api/meetings/demo" | python3 -c "import sys,json;print(json.load(sys.stdin)['id'])")
echo "→ simulating a live Google Meet into meeting $MID"

emit() { # $1 = speaker, $2 = is_host (true/false), $3 = text
  curl -fsS -X POST "$API/api/webhooks/recall?meeting_id=$MID" -H 'Content-Type: application/json' \
    -d "{\"event\":\"transcript.data\",\"data\":{\"data\":{\"participant\":{\"name\":\"$1\",\"is_host\":$2},\"words\":[{\"text\":\"$3\"}]}}}" >/dev/null
}

emit "Alex Rivera" true  "Hi Sarah, good to see you — how are things at Northwind?"
emit "Sarah Chen"  false "What is the current status of our contract?"
emit "Sarah Chen"  false "And can you share your SOC 2 report?"
emit "Sarah Chen"  false "How many support tickets do we have open right now?"

echo "── transcript (host→rep, others→customer) ──"
curl -fsS "$API/api/meetings/$MID/transcript" | python3 -c "import sys,json;[print('  ',s['role'],'·',s['speaker']+':',s['text']) for s in json.load(sys.stdin)]"
echo "── suggestions generated live ──"
curl -fsS "$API/api/meetings/$MID/suggestions" | python3 -c "import sys,json;[print('  ',s['intent_type'],'('+str(int(s['confidence']*100))+'%) grounded='+str(s['grounded'])) for s in json.load(sys.stdin)]"
echo "→ open the meeting in the UI to watch it live:  /meeting/$MID"
