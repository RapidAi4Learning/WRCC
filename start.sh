#!/usr/bin/env bash
# Start the WRCC Social Media Marketing backend (FastAPI :8000) and frontend (Next.js :3000).
# Usage: ./start.sh
set -euo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_DIR="$ROOT_DIR/backend"
FRONTEND_DIR="$ROOT_DIR/frontend"

# Locate the backend venv python (Windows uses Scripts/, Unix uses bin/).
if [ -x "$BACKEND_DIR/.venv/Scripts/python.exe" ]; then
  VENV_PYTHON="$BACKEND_DIR/.venv/Scripts/python.exe"
elif [ -x "$BACKEND_DIR/.venv/bin/python" ]; then
  VENV_PYTHON="$BACKEND_DIR/.venv/bin/python"
else
  echo "error: backend venv not found at backend/.venv" >&2
  echo "  create it first:  cd backend && python -m venv .venv && .venv/Scripts/activate && pip install -e \".[dev]\"" >&2
  exit 1
fi

if [ ! -f "$BACKEND_DIR/.env" ]; then
  echo "error: backend/.env is missing" >&2
  echo "  copy the template first:  cp backend/.env.example backend/.env  (set DATABASE_URL, ADMIN_EMAIL, ADMIN_PASSWORD)" >&2
  exit 1
fi

if [ ! -d "$FRONTEND_DIR/node_modules" ]; then
  echo "frontend/node_modules missing — running npm install..."
  (cd "$FRONTEND_DIR" && npm install)
fi

# Kill whatever is still listening on a port (stale dev server from a previous
# session) so the fresh start never fails with "address already in use".
free_port() {
  local port="$1"
  local pids=""
  if command -v taskkill >/dev/null 2>&1; then
    # Windows (Git Bash): netstat columns are PROTO LOCAL FOREIGN STATE PID.
    pids=$(netstat -ano | awk -v addr=":$port" \
      '$1 == "TCP" && $2 ~ addr"$" && $4 == "LISTENING" {print $5}' | sort -u)
    for pid in $pids; do
      # Never touch PID 0 (idle) or 4 (System).
      [ "$pid" -gt 4 ] 2>/dev/null || continue
      echo "port $port in use — killing PID $pid"
      taskkill //PID "$pid" //F >/dev/null 2>&1 || true
    done
  elif command -v lsof >/dev/null 2>&1; then
    pids=$(lsof -ti tcp:"$port" 2>/dev/null || true)
    for pid in $pids; do
      echo "port $port in use — killing PID $pid"
      kill -9 "$pid" 2>/dev/null || true
    done
  fi
  # Give the OS a beat to release the socket before rebinding.
  if [ -n "$pids" ]; then
    sleep 1
  fi
}

free_port 8000
free_port 3000

PIDS=()
cleanup() {
  echo ""
  echo "shutting down..."
  for pid in "${PIDS[@]}"; do
    kill "$pid" 2>/dev/null || true
  done
  wait 2>/dev/null || true
}
trap cleanup EXIT INT TERM

echo "starting backend  → http://localhost:8000"
(cd "$BACKEND_DIR" && "$VENV_PYTHON" -m uvicorn app.main:app --reload --port 8000) &
PIDS+=($!)

echo "starting frontend → http://localhost:3000"
(cd "$FRONTEND_DIR" && npm run dev) &
PIDS+=($!)

echo ""
echo "both servers running — press Ctrl+C to stop"
wait
