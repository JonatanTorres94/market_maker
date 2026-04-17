#!/usr/bin/env bash
set -Eeuo pipefail

PROJECT_DIR="/home/jonatan/trading-bot"
PYTHON_BIN="$PROJECT_DIR/venv/bin/python"
LOG_DIR="$PROJECT_DIR/logs"

DRIFT_GATE_LOOKBACK_SECONDS="${DRIFT_GATE_LOOKBACK_SECONDS:-3}"
DRIFT_GATE_THRESHOLD_BPS="${DRIFT_GATE_THRESHOLD_BPS:-1.5}"

if [[ ! -x "$PYTHON_BIN" ]]; then
  echo "ERROR: Python not found at $PYTHON_BIN"
  exit 1
fi

mkdir -p "$LOG_DIR"
cd "$PROJECT_DIR"

LOG_FILE="$LOG_DIR/market_maker_$(date '+%Y%m%dT%H%M%S').log"
echo "[$(date '+%Y-%m-%d %H:%M:%S')] Starting market maker → $LOG_FILE"

# Exportamos las variables para que el proceso hijo las vea
export DRIFT_GATE_LOOKBACK_SECONDS
export DRIFT_GATE_THRESHOLD_BPS

# Ahora exec llama directamente al binario de python
exec "$PYTHON_BIN" -m src.scripts.run_market_maker >> "$LOG_FILE" 2>&1