#!/bin/bash
# Chlorophyll-a WMS sync — runs twice daily via cron (6am, 6pm UTC)
# Validates NASA ERDDAP WMS endpoint and logs sync status

LOG_DIR="/var/log/marine-fishing"
LOG_FILE="$LOG_DIR/chlorophyll_harvester.log"
LOCK_FILE="/tmp/chlorophyll_harvester.lock"

mkdir -p "$LOG_DIR"

# Prevent overlapping runs
if [ -f "$LOCK_FILE" ]; then
    pid=$(cat "$LOCK_FILE")
    if kill -0 "$pid" 2>/dev/null; then
        echo "$(date -Iseconds) - Chlorophyll harvester already running (PID $pid), skipping" >> "$LOG_FILE"
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi

echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

cd /opt/marine-fishing
source api/venv/bin/activate
PYTHONPATH=/opt/marine-fishing python -m harvesters.chlorophyll_harvester >> "$LOG_FILE" 2>&1
