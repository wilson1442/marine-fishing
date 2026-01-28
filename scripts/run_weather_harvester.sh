#!/bin/bash
# Weather harvester cron wrapper
# Runs hourly via cron to pull NDBC buoy data

LOG_DIR="/var/log/marine-fishing"
LOG_FILE="$LOG_DIR/weather_harvester.log"
LOCK_FILE="/tmp/weather_harvester.lock"

mkdir -p "$LOG_DIR"

# Prevent overlapping runs
if [ -f "$LOCK_FILE" ]; then
    pid=$(cat "$LOCK_FILE")
    if kill -0 "$pid" 2>/dev/null; then
        echo "$(date -Iseconds) - Weather harvester already running (PID $pid), skipping" >> "$LOG_FILE"
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi

echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

cd /opt/marine-fishing
source api/venv/bin/activate
PYTHONPATH=/opt/marine-fishing python -m harvesters.weather_harvester >> "$LOG_FILE" 2>&1
