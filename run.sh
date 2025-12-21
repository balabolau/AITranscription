#!/usr/bin/env bash
set -euo pipefail

ROOT="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
SESSION="aitranscribe"
ENV_NAME="ai_transcript"

# We track only the Redis we start (daemonized) using a pidfile in the project directory
REDIS_PIDFILE="$ROOT/.redis.pid"
REDIS_LOGFILE="$ROOT/.redis.log"

# Command fragment to activate conda in a non-interactive shell
# Using bash -lc makes this much more reliable inside tmux.
CONDA_PREFIX_CMD="source \"\$(conda info --base)/etc/profile.d/conda.sh\" && conda activate \"$ENV_NAME\""

# Start Redis daemon only if not already responding, and write pidfile/logfile if we start it
START_REDIS_CMD="redis-cli ping >/dev/null 2>&1 || redis-server --daemonize yes --pidfile \"$REDIS_PIDFILE\" --logfile \"$REDIS_LOGFILE\""

BACKEND_CMD="cd \"$ROOT/backend\" && $CONDA_PREFIX_CMD && uvicorn main:app --reload"
WORKER_CMD="cd \"$ROOT/backend\" && $CONDA_PREFIX_CMD && $START_REDIS_CMD && export OBJC_DISABLE_INITIALIZE_FORK_SAFETY=YES && python worker.py"
FRONTEND_CMD="cd \"$ROOT/web-app\" && $CONDA_PREFIX_CMD && streamlit run Homepage.py"

# If session already exists, just attach
if tmux has-session -t "$SESSION" 2>/dev/null; then
  tmux attach -t "$SESSION"
  exit 0
fi

# Create session + 3 windows
tmux new-session -d -s "$SESSION" -n backend
tmux send-keys -t "$SESSION:backend" "bash -lc '$BACKEND_CMD'" C-m

tmux new-window -t "$SESSION" -n worker
tmux send-keys -t "$SESSION:worker" "bash -lc '$WORKER_CMD'" C-m

tmux new-window -t "$SESSION" -n frontend
tmux send-keys -t "$SESSION:frontend" "bash -lc '$FRONTEND_CMD'" C-m

tmux select-window -t "$SESSION:backend"
tmux attach -t "$SESSION"
