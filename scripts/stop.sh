#!/usr/bin/env bash
# Stop whatever start-bg.sh launched. Falls back to pkill if the pidfile is
# missing (e.g. process killed by the OS).
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG_DIR="${LOG_DIR:-logs}"
BACKEND_PID_FILE="${BACKEND_PID_FILE:-$LOG_DIR/backend.pid}"

# The patterns after `-m app` match the earlier two-process layout, so `make
# stop` still cleans up servers started before an upgrade.
PATTERNS=("python -m app$" "uvicorn app.main" "app.mcp_server")

stopped=0
# mcp.pid is left over from the two-process layout.
for pf in "$BACKEND_PID_FILE" "$LOG_DIR/mcp.pid"; do
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
  for p in "${PATTERNS[@]}"; do pkill -f "$p" 2>/dev/null || true; done
fi

sleep 0.5

# Belt-and-suspenders: force kill anything still running
for p in "${PATTERNS[@]}"; do pkill -9 -f "$p" 2>/dev/null || true; done

echo "stopped"
