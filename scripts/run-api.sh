#!/usr/bin/env bash
set -euo pipefail

# Usage: scripts/run-api.sh <dist-name> <module_path> [--port 8000]
# Example: scripts/run-api.sh my-app my_app.api.main:app --port 8000

if [ $# -lt 2 ]; then
  echo "Usage: $0 <dist-name> <module:app> [--port 8000]" >&2
  exit 1
fi

DIST_NAME="$1"; shift
APP_SPEC="$1"; shift

exec uv run --package "$DIST_NAME" uvicorn "$APP_SPEC" --reload "$@"
