#!/bin/bash
# run_hourly.sh – hourly eBay pipeline via anacron/cron
# Calls main.py which runs all pipeline steps in sequence.

set -euo pipefail

PROJECT_ROOT="/mnt/c/Projects/EbayPrice"
PYTHON="$PROJECT_ROOT/.venv/Scripts/python.exe"
MAIN_SCRIPT="$PROJECT_ROOT/scripts/main.py"

LOG_DIR="$HOME/ebay_exports"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_hourly.log"

echo "[$(date)] Starting hourly pipeline..." >> "$LOG_FILE"

cd "$PROJECT_ROOT"

MAIN_SCRIPT_WIN=$(wslpath -w "$MAIN_SCRIPT" 2>/dev/null || echo "$MAIN_SCRIPT")

"$PYTHON" "$MAIN_SCRIPT_WIN" >> "$LOG_FILE" 2>&1
EXIT_CODE=$?
echo "[$(date)] Finished with exit code $EXIT_CODE" >> "$LOG_FILE"
exit $EXIT_CODE
