#!/usr/bin/env bash
set -euo pipefail

# Usage: scripts/run-cli.sh <dist-name> <cli-command> [args...]

if [ $# -lt 2 ]; then
  echo "Usage: $0 <dist-name> <cli-command> [args...]" >&2
  exit 1
fi

DIST_NAME="$1"; shift
CLI_CMD="$1"; shift

exec uv run --package "$DIST_NAME" "$CLI_CMD" "$@"
