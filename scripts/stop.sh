#!/usr/bin/env bash
# Stop whatever start-bg.sh launched. Falls back to pkill if pidfiles are
# missing (e.g. process killed by the OS).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG_DIR="${LOG_DIR:-logs}"
BACKEND_PID_FILE="${BACKEND_PID_FILE:-$LOG_DIR/backend.pid}"
MCP_PID_FILE="${MCP_PID_FILE:-$LOG_DIR/mcp.pid}"

stopped=0
for pf in "$BACKEND_PID_FILE" "$MCP_PID_FILE"; do
  if [[ -f "$pf" ]]; then
    pid=$(cat "$pf" 2>/dev/null || true)
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      kill "$pid" 2>/dev/null || true
      stopped=$((stopped + 1))
    fi
    rm -f "$pf"
  fi
done

if [[ "$stopped" -eq 0 ]]; then
  echo "no pidfile — falling back to pkill"
  pkill -f "uvicorn app.main" 2>/dev/null || true
  pkill -f "app.mcp_server" 2>/dev/null || true
fi

sleep 0.5

# Belt-and-suspenders: force kill anything still listening on the known ports
pkill -9 -f "uvicorn app.main" 2>/dev/null || true
pkill -9 -f "app.mcp_server" 2>/dev/null || true

echo "stopped"
