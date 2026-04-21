#!/usr/bin/env bash
# Background-launch backend (uvicorn) + mcp (python -m app.mcp_server) in
# production mode. Pid files and merged stdout/stderr land in logs/.
set -euo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG_DIR="${LOG_DIR:-logs}"
LOG_FILE="${LOG_FILE:-$LOG_DIR/taskflow.log}"
BACKEND_PID_FILE="${BACKEND_PID_FILE:-$LOG_DIR/backend.pid}"
MCP_PID_FILE="${MCP_PID_FILE:-$LOG_DIR/mcp.pid}"

API_HOST="${API_HOST:-0.0.0.0}"
API_PORT="${API_PORT:-8000}"
MCP_HOST="${MCP_HOST:-0.0.0.0}"
MCP_PORT="${MCP_PORT:-7391}"

mkdir -p "$LOG_DIR"

# Refuse double-start
for pf in "$BACKEND_PID_FILE" "$MCP_PID_FILE"; do
  if [[ -f "$pf" ]] && kill -0 "$(cat "$pf")" 2>/dev/null; then
    echo "✗ already running (pid=$(cat "$pf"), pidfile=$pf). run 'make stop' first." >&2
    exit 1
  fi
  rm -f "$pf"
done

VENV_BIN="backend/.venv/bin"
if [[ ! -x "$VENV_BIN/uvicorn" ]]; then
  echo "✗ backend venv missing — run 'make setup' first." >&2
  exit 1
fi
if [[ ! -f frontend/dist/index.html ]]; then
  echo "✗ frontend/dist/index.html missing — run 'make build' first." >&2
  exit 1
fi

echo "start-bg → backend :$API_PORT + mcp :$MCP_PORT (log=$LOG_FILE)"

(
  cd backend
  TASKFLOW_ENV=production TASKFLOW_FRONTEND_DIST_DIR=../frontend/dist \
    nohup "../$VENV_BIN/uvicorn" app.main:app \
      --host "$API_HOST" --port "$API_PORT" --workers 1 \
      >> "../$LOG_FILE" 2>&1 &
  echo $! > "../$BACKEND_PID_FILE"
)

(
  cd backend
  TASKFLOW_ENV=production TASKFLOW_MCP_HOST="$MCP_HOST" TASKFLOW_MCP_PORT="$MCP_PORT" \
    nohup "../$VENV_BIN/python" -m app.mcp_server \
      >> "../$LOG_FILE" 2>&1 &
  echo $! > "../$MCP_PID_FILE"
)

sleep 1

BPID=$(cat "$BACKEND_PID_FILE" 2>/dev/null || echo "?")
MPID=$(cat "$MCP_PID_FILE" 2>/dev/null || echo "?")
echo "✓ running — backend pid=$BPID · mcp pid=$MPID"
echo "  tail logs : make logs"
echo "  stop      : make stop"
echo "  status    : make status"
