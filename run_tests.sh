#!/usr/bin/env bash
# Runs every test: Python unit tests, Node drawing tests, and the headless app test against a temporary server.
set -euo pipefail
cd "$(dirname "$0")"
PORT="${PORT:-8765}"

echo "== python =="
python3 -m pytest tests -q

echo "== node: helpers and drawing =="
node tests/frontend.test.js

echo "== node: full app against a live server on :$PORT =="
python3 -m uvicorn backend.api.server:app --port "$PORT" --log-level warning &
SERVER=$!
trap 'kill $SERVER 2>/dev/null || true' EXIT
for _ in $(seq 1 40); do
  if curl -s -o /dev/null "http://127.0.0.1:$PORT/api/meta"; then break; fi
  sleep 0.5
done
API_BASE="http://127.0.0.1:$PORT" node tests/app_smoke.test.js
echo "ALL TESTS PASSED"
