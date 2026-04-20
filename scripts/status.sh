#!/usr/bin/env bash
# Report whether start-bg.sh processes are alive.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG_DIR="${LOG_DIR:-logs}"
BACKEND_PID_FILE="${BACKEND_PID_FILE:-$LOG_DIR/backend.pid}"
MCP_PID_FILE="${MCP_PID_FILE:-$LOG_DIR/mcp.pid}"
API_PORT="${API_PORT:-8000}"
MCP_PORT="${MCP_PORT:-7391}"

check() {
  local name="$1" pf="$2" port="$3"
  if [[ -f "$pf" ]]; then
    local pid
    pid=$(cat "$pf" 2>/dev/null || echo "")
    if [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null; then
      printf "%-8s running (pid=%s, port=%s)\n" "$name" "$pid" "$port"
    else
      printf "%-8s stale pidfile (pid=%s not alive)\n" "$name" "$pid"
    fi
  else
    printf "%-8s not running\n" "$name"
  fi
}

check backend "$BACKEND_PID_FILE" "$API_PORT"
check mcp     "$MCP_PID_FILE"     "$MCP_PORT"
