#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"
ENV_FILE="${ENV_FILE:-"$ROOT_DIR/.env"}"

if [[ ! -f "$ENV_FILE" ]]; then
  echo "Missing env file: $ENV_FILE"
  echo "Create .env in the repository root, then run ./scripts/dev.sh again."
  exit 1
fi

if ! command -v python >/dev/null 2>&1; then
  echo "Missing python. Activate the project Python environment first."
  exit 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "Missing pnpm. Install frontend dependencies first."
  exit 1
fi

set -a
# shellcheck disable=SC1090
source "$ENV_FILE"
set +a

AGENT_HOST="${AGENT_HOST:-127.0.0.1}"
AGENT_PORT="${AGENT_PORT:-8001}"
BACKEND_HOST="${BACKEND_HOST:-127.0.0.1}"
BACKEND_PORT="${BACKEND_PORT:-8000}"
FRONTEND_HOST="${FRONTEND_HOST:-127.0.0.1}"
FRONTEND_PORT="${FRONTEND_PORT:-3000}"

AGENT_SERVICE_BASE_URL="${AGENT_SERVICE_BASE_URL:-http://${AGENT_HOST}:${AGENT_PORT}}"
BACKEND_BASE_URL="${BACKEND_BASE_URL:-http://${BACKEND_HOST}:${BACKEND_PORT}}"

pids=()

cleanup() {
  local status=$?
  if [[ ${#pids[@]} -gt 0 ]]; then
    echo
    echo "Stopping TraceAgent dev services..."
    kill "${pids[@]}" >/dev/null 2>&1 || true
    wait "${pids[@]}" >/dev/null 2>&1 || true
  fi
  exit "$status"
}

trap cleanup EXIT INT TERM

start_service() {
  local name="$1"
  shift

  echo "Starting $name..."
  (
    cd "$ROOT_DIR"
    "$@"
  ) &

  local pid=$!
  pids+=("$pid")
  sleep 1

  if ! kill -0 "$pid" >/dev/null 2>&1; then
    set +e
    wait "$pid"
    local status=$?
    set -e
    exit "$status"
  fi
}

start_service "agent    http://${AGENT_HOST}:${AGENT_PORT}" \
  python -m uvicorn --app-dir agent main:app --reload --host "$AGENT_HOST" --port "$AGENT_PORT"

start_service "backend  http://${BACKEND_HOST}:${BACKEND_PORT}" \
  env AGENT_SERVICE_BASE_URL="$AGENT_SERVICE_BASE_URL" \
  python -m uvicorn backend.main:app --reload --host "$BACKEND_HOST" --port "$BACKEND_PORT"

start_service "frontend http://${FRONTEND_HOST}:${FRONTEND_PORT}" \
  env BACKEND_BASE_URL="$BACKEND_BASE_URL" \
  pnpm --dir frontend dev --hostname "$FRONTEND_HOST" --port "$FRONTEND_PORT"

echo
echo "TraceAgent is running:"
echo "  agent:    http://${AGENT_HOST}:${AGENT_PORT}"
echo "  backend:  http://${BACKEND_HOST}:${BACKEND_PORT}"
echo "  frontend: http://${FRONTEND_HOST}:${FRONTEND_PORT}"
echo
echo "Press Ctrl-C to stop all services."

while true; do
  for pid in "${pids[@]}"; do
    if ! kill -0 "$pid" >/dev/null 2>&1; then
      set +e
      wait "$pid"
      status=$?
      set -e
      exit "$status"
    fi
  done
  sleep 2
done
