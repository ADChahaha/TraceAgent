#!/usr/bin/env bash
set -Eeuo pipefail

ROOT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")/.." && pwd)"

if ! command -v python >/dev/null 2>&1; then
  echo "Missing python. Activate the project Python environment first."
  exit 1
fi

if ! command -v pnpm >/dev/null 2>&1; then
  echo "Missing pnpm. Install pnpm first, then run this script again."
  exit 1
fi

cd "$ROOT_DIR"

echo "Installing agent..."
python -m pip install -e agent

echo "Installing backend..."
python -m pip install -e backend

echo "Installing frontend dependencies..."
if [[ "${CI:-}" == "true" ]]; then
  pnpm --dir frontend install --frozen-lockfile
else
  pnpm --dir frontend install
fi

echo "Building frontend..."
pnpm --dir frontend build

echo
echo "TraceAgent install completed."
echo "Start services with: ./scripts/start.sh"
