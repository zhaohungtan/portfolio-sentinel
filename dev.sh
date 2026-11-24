#!/bin/zsh
set -euo pipefail
cd "$(dirname "$0")"

if [[ ! -x .venv/bin/uvicorn ]]; then
  echo "Missing .venv. Run: python3.13 -m venv .venv && .venv/bin/pip install -r requirements.txt && .venv/bin/pip install -e ."
  exit 1
fi

.venv/bin/uvicorn api.server:app --host 127.0.0.1 --port 8000 &
API_PID=$!
npm --prefix web run dev -- --hostname 127.0.0.1 --port 3000 &
WEB_PID=$!

cleanup() {
  kill "$API_PID" "$WEB_PID" 2>/dev/null || true
}
trap cleanup EXIT INT TERM
wait
