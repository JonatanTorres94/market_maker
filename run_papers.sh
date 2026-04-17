#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="/home/jonatan/trading-bot"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"

SESSION_ID="${1:?Usage: run_papers.sh <session_id>}"
CONTINUE_ON_ERROR="${CONTINUE_ON_ERROR:-true}"

cd "$PROJECT_DIR"

run_step() {
  local module="$1"
  echo "--- RUN_SESSION_ID=$SESSION_ID python -m $module ---"
  RUN_SESSION_ID="$SESSION_ID" "$PYTHON_BIN" -m "$module"
  local code=$?
  if [[ $code -ne 0 ]]; then
    echo "ERROR: $module failed (exit $code)"
    [[ "$CONTINUE_ON_ERROR" == "false" ]] && exit $code
  fi
}

run_step src.scripts.reconcile_orders
run_step src.scripts.reconcile_executions
run_step src.scripts.analyze_journal

echo "--- Updating comparison table ---"
"$PYTHON_BIN" -m src.scripts.compare_papers

echo "Done: $SESSION_ID"
