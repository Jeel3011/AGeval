#!/usr/bin/env bash
# Boots a local AGeval API server (live Supabase from .env), registers an API
# key, runs the live multi-agent hammer test through the real adapters + API,
# then tears the server down.
set -euo pipefail
cd "$(dirname "$0")/.."

# A throwaway admin secret just for this local run.
export AGEVAL_ADMIN_SECRET="${AGEVAL_ADMIN_SECRET:-hammer-local-$(date +%s)}"
export AGEVAL_CORS_ORIGINS="*"
PORT="${PORT:-8000}"
BASE="http://localhost:${PORT}"

echo "==> starting API server on ${BASE}"
.venv/bin/uvicorn main:app --port "${PORT}" --log-level warning >/tmp/ageval_hammer_server.log 2>&1 &
SERVER_PID=$!
trap 'echo "==> stopping server"; kill $SERVER_PID 2>/dev/null || true' EXIT

# Wait for /health
for i in $(seq 1 30); do
  if curl -fsS "${BASE}/health" >/dev/null 2>&1; then break; fi
  sleep 0.5
done
curl -fsS "${BASE}/health" >/dev/null || { echo "server did not come up"; cat /tmp/ageval_hammer_server.log; exit 1; }
echo "==> server healthy"

echo "==> registering API key"
KEY=$(curl -fsS -X POST "${BASE}/register" \
  -H "Content-Type: application/json" \
  -H "x-admin-secret: ${AGEVAL_ADMIN_SECRET}" \
  -d '{"label":"hammer"}' | .venv/bin/python -c "import sys,json;print(json.load(sys.stdin)['api_key'])")
echo "==> got key ${KEY:0:18}..."

export AGEVAL_API_KEY="$KEY"
export AGEVAL_API_URL="$BASE"

echo "==> running hammer agents"
.venv/bin/python examples/hammer_agents.py --base "$BASE"
