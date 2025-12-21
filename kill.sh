#!/usr/bin/env bash
set -euo pipefail

SESSION="aitranscribe"
ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
REDIS_PIDFILE="$ROOT/.redis.pid"

# 1) Kill tmux session (stops uvicorn/worker/streamlit)
tmux kill-session -t "$SESSION" 2>/dev/null || true

# 2) Stop Redis ONLY if we started it (pidfile exists)
if [[ -f "$REDIS_PIDFILE" ]]; then
  REDIS_PID="$(cat "$REDIS_PIDFILE" || true)"

  # Try graceful shutdown first (won't error out if it fails)
  redis-cli shutdown >/dev/null 2>&1 || true

  # If still running, kill by PID (safe: only the PID from our pidfile)
  if [[ -n "${REDIS_PID:-}" ]] && ps -p "$REDIS_PID" >/dev/null 2>&1; then
    kill "$REDIS_PID" >/dev/null 2>&1 || true
  fi

  rm -f "$REDIS_PIDFILE"
fi
