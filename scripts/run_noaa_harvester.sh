#!/bin/bash
# NOAA fisheries harvester cron wrapper
# Runs weekly (Sundays 3 AM) to pull commercial and recreational landings

LOG_DIR="/var/log/marine-fishing"
LOG_FILE="$LOG_DIR/noaa_harvester.log"
LOCK_FILE="/tmp/noaa_harvester.lock"

mkdir -p "$LOG_DIR"

# Prevent overlapping runs
if [ -f "$LOCK_FILE" ]; then
    pid=$(cat "$LOCK_FILE")
    if kill -0 "$pid" 2>/dev/null; then
        echo "$(date -Iseconds) - NOAA harvester already running (PID $pid), skipping" >> "$LOG_FILE"
        exit 0
    fi
    rm -f "$LOCK_FILE"
fi

echo $$ > "$LOCK_FILE"
trap 'rm -f "$LOCK_FILE"' EXIT

cd /opt/marine-fishing
source api/venv/bin/activate

echo "$(date -Iseconds) - Starting NOAA commercial harvester" >> "$LOG_FILE"
PYTHONPATH=/opt/marine-fishing python -m harvesters.noaa_harvester commercial >> "$LOG_FILE" 2>&1

echo "$(date -Iseconds) - Starting NOAA MRIP recreational harvester" >> "$LOG_FILE"
PYTHONPATH=/opt/marine-fishing python -m harvesters.noaa_harvester mrip >> "$LOG_FILE" 2>&1
