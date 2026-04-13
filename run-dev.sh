#!/usr/bin/env bash

set -euo pipefail

REPO_ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"

if [[ -x "$REPO_ROOT/.venv/bin/python" ]]; then
  PYTHON_BIN="$REPO_ROOT/.venv/bin/python"
elif command -v python3 >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python3)"
elif command -v python >/dev/null 2>&1; then
  PYTHON_BIN="$(command -v python)"
else
  echo "Python was not found. Create the virtual environment or install Python 3 first." >&2
  exit 1
fi

if ! command -v npm >/dev/null 2>&1; then
  echo "npm was not found. Install Node.js and npm first." >&2
  exit 1
fi

if [[ ! -d "$REPO_ROOT/frontend" ]]; then
  echo "Expected a frontend directory at $REPO_ROOT/frontend." >&2
  exit 1
fi

if [[ ! -d "$REPO_ROOT/frontend/node_modules" ]]; then
  echo "Frontend dependencies are missing. Run 'cd frontend && npm install' first." >&2
  exit 1
fi

if ! "$PYTHON_BIN" -c "import uvicorn" >/dev/null 2>&1; then
  echo "Backend dependencies are missing in $PYTHON_BIN. Install the project dependencies first." >&2
  exit 1
fi

backend_pid=""
frontend_pid=""
backend_tail_pid=""
frontend_tail_pid=""
backend_log="$(mktemp -t market-analyser-backend)"
frontend_log="$(mktemp -t market-analyser-frontend)"

cleanup() {
  local exit_code=$?

  trap - EXIT INT TERM

  if [[ -n "$backend_pid" ]] && kill -0 "$backend_pid" 2>/dev/null; then
    kill "$backend_pid" 2>/dev/null || true
    wait "$backend_pid" 2>/dev/null || true
  fi

  if [[ -n "$frontend_pid" ]] && kill -0 "$frontend_pid" 2>/dev/null; then
    kill "$frontend_pid" 2>/dev/null || true
    wait "$frontend_pid" 2>/dev/null || true
  fi

  if [[ -n "$backend_tail_pid" ]] && kill -0 "$backend_tail_pid" 2>/dev/null; then
    kill "$backend_tail_pid" 2>/dev/null || true
    wait "$backend_tail_pid" 2>/dev/null || true
  fi

  if [[ -n "$frontend_tail_pid" ]] && kill -0 "$frontend_tail_pid" 2>/dev/null; then
    kill "$frontend_tail_pid" 2>/dev/null || true
    wait "$frontend_tail_pid" 2>/dev/null || true
  fi

  rm -f "$backend_log" "$frontend_log"

  exit "$exit_code"
}

trap cleanup EXIT INT TERM

: > "$backend_log"
: > "$frontend_log"

tail -n 0 -f "$backend_log" | awk -v prefix="[backend] " '{ print prefix $0; fflush(); }' &
backend_tail_pid=$!

tail -n 0 -f "$frontend_log" | awk -v prefix="[frontend] " '{ print prefix $0; fflush(); }' &
frontend_tail_pid=$!

echo "Starting backend on http://localhost:$BACKEND_PORT"
(
  cd "$REPO_ROOT"
  export WATCHFILES_FORCE_POLLING="${WATCHFILES_FORCE_POLLING:-true}"
  exec "$PYTHON_BIN" -m uvicorn api.main:app \
    --host "$BACKEND_HOST" \
    --port "$BACKEND_PORT" \
    --reload \
    --reload-dir api \
    --reload-dir pipeline \
    --reload-dir config
) >>"$backend_log" 2>&1 &
backend_pid=$!

echo "Starting frontend on http://localhost:$FRONTEND_PORT"
(
  cd "$REPO_ROOT/frontend"
  export NEXT_PUBLIC_API_URL="${NEXT_PUBLIC_API_URL:-http://localhost:$BACKEND_PORT}"
  exec npm run dev -- --hostname "$FRONTEND_HOST" --port "$FRONTEND_PORT"
) >>"$frontend_log" 2>&1 &
frontend_pid=$!

echo "Frontend:  http://localhost:$FRONTEND_PORT"
echo "API docs:  http://localhost:$BACKEND_PORT/docs"
echo "Press Ctrl+C to stop both services."

exit_code=0

while true; do
  if ! kill -0 "$backend_pid" 2>/dev/null; then
    wait "$backend_pid" || exit_code=$?
    echo "Backend exited." >&2
    break
  fi

  if ! kill -0 "$frontend_pid" 2>/dev/null; then
    wait "$frontend_pid" || exit_code=$?
    echo "Frontend exited." >&2
    break
  fi

  sleep 1
done

exit "$exit_code"
