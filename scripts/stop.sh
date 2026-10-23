#!/usr/bin/env bash
# Stop whatever start-bg.sh launched: SIGTERM, wait for a graceful stop (open
# connections drain, running steps are killed and recorded), then SIGKILL only
# what is still alive. Falls back to pkill patterns if the pidfile is missing.
set -uo pipefail

ROOT="$(cd "$(dirname "$0")/.." && pwd)"
cd "$ROOT"

LOG_DIR="${LOG_DIR:-logs}"
BACKEND_PID_FILE="${BACKEND_PID_FILE:-$LOG_DIR/backend.pid}"
STOP_TIMEOUT_SEC="${STOP_TIMEOUT_SEC:-20}"

# Anchored on this repo's venv so other `python -m app` processes on the host
# are left alone. The last two match the earlier two-process layout, so `make
# stop` still cleans up servers started before an upgrade.
PATTERNS=(
  "backend/\.venv/bin/python -m app$"
  "backend/\.venv/bin/uvicorn app\.main"
  "backend/\.venv/bin/python -m app\.mcp_server"
)

pids=()
# mcp.pid is left over from the two-process layout.
for pf in "$BACKEND_PID_FILE" "$LOG_DIR/mcp.pid"; do
  if [[ -f "$pf" ]]; then
    pid=$(cat "$pf" 2>/dev/null || true)
    [[ -n "$pid" ]] && kill -0 "$pid" 2>/dev/null && pids+=("$pid")
    rm -f "$pf"
  fi
done

if [[ ${#pids[@]} -eq 0 ]]; then
  echo "no pidfile — falling back to pkill patterns"
  for p in "${PATTERNS[@]}"; do
    while read -r pid; do [[ -n "$pid" ]] && pids+=("$pid"); done < <(pgrep -f "$p" 2>/dev/null)
  done
fi

if [[ ${#pids[@]} -eq 0 ]]; then
  echo "not running"
  exit 0
fi

kill "${pids[@]}" 2>/dev/null || true

alive() {
  local pid
  for pid in "${pids[@]}"; do kill -0 "$pid" 2>/dev/null && return 0; done
  return 1
}

for ((i = 0; i < STOP_TIMEOUT_SEC * 2; i++)); do
  alive || { echo "stopped"; exit 0; }
  sleep 0.5
done

echo "still running after ${STOP_TIMEOUT_SEC}s — sending SIGKILL"
kill -9 "${pids[@]}" 2>/dev/null || true
echo "stopped"
