#!/usr/bin/env bash
# Report whether the start-bg.sh process is alive.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG_DIR="${LOG_DIR:-logs}"
BACKEND_PID_FILE="${BACKEND_PID_FILE:-$LOG_DIR/backend.pid}"
API_PORT="${API_PORT:-8000}"
MCP_PORT="${MCP_PORT:-7391}"

if [[ -f "$BACKEND_PID_FILE" ]]; then
  pid=$(cat "$BACKEND_PID_FILE" 2>/dev/null || echo "")
  if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
    printf "backend running (pid=%s, api=:%s, mcp=:%s)\n" "$pid" "$API_PORT" "$MCP_PORT"
  else
    printf "backend stale pidfile (pid=%s not alive)\n" "$pid"
  fi
else
  printf "backend not running\n"
fi
