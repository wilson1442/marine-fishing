#!/bin/bash
# GFW fishing effort harvester cron wrapper
# Runs daily at 2 AM to pull fishing events (last 7 days)

LOG_DIR="/var/log/marine-fishing"
LOG_FILE="$LOG_DIR/gfw_harvester.log"
LOCK_FILE="/tmp/gfw_harvester.lock"

mkdir -p "$LOG_DIR"

# Prevent overlapping runs
if [ -f "$LOCK_FILE" ]; then
    pid=$(cat "$LOCK_FILE")
    if kill -0 "$pid" 2>/dev/null; then
        echo "$(date -Iseconds) - GFW harvester already running (PID $pid), skipping" >> "$LOG_FILE"
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi

echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

cd /opt/marine-fishing
source api/venv/bin/activate
source api/.env 2>/dev/null

echo "$(date -Iseconds) - Starting GFW harvester" >> "$LOG_FILE"
PYTHONPATH=/opt/marine-fishing python -m harvesters.gfw_harvester 7 >> "$LOG_FILE" 2>&1
