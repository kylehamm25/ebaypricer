#!/bin/bash
# run_daily.sh – daily eBay sold append via anacron/cron
# Calls the Windows Python venv via WSL interop.

set -euo pipefail

PROJECT_ROOT="/mnt/c/Projects/EbayPrice"
PYTHON="$PROJECT_ROOT/.venv/Scripts/python.exe"
APPEND_SCRIPT="$PROJECT_ROOT/scripts/append_sold_orders.py"

LOG_DIR="$HOME/ebay_exports"
mkdir -p "$LOG_DIR"
LOG_FILE="$LOG_DIR/run_daily.log"

echo "[$(date)] Starting..." >> "$LOG_FILE"

cd "$PROJECT_ROOT"

# Convert Linux path to Windows path for the Windows Python
APPEND_SCRIPT_WIN=$(wslpath -w "$APPEND_SCRIPT" 2>/dev/null || echo "$APPEND_SCRIPT")

"$PYTHON" "$APPEND_SCRIPT_WIN" --days 1 >> "$LOG_FILE" 2>&1
EXIT_CODE=$?

echo "[$(date)] Finished with exit code $EXIT_CODE" >> "$LOG_FILE"
exit $EXIT_CODE
