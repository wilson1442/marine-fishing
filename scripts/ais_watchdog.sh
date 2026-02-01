#!/bin/bash
# AIS Stream Harvester Watchdog
# Checks if the AIS harvester is running and healthy every 10 minutes.
# If the process is dead or hung (no log activity in 10 minutes), restarts it.
#
# Install via cron:
#   */10 * * * * /opt/marine-fishing/scripts/ais_watchdog.sh >> /var/log/marine-fishing/ais_watchdog.log 2>&1

PID_FILE="/tmp/ais_harvester.pid"
LOG_FILE="/var/log/marine-fishing/ais_harvester.log"
WATCHDOG_LOG="/var/log/marine-fishing/ais_watchdog.log"
HARVESTER_SCRIPT="/opt/marine-fishing/scripts/run_ais_harvester.sh"
STALE_THRESHOLD=600  # 10 minutes with no log output = hung

timestamp() {
    date -Iseconds
}

log() {
    echo "$(timestamp) - WATCHDOG - $1"
}

# Rotate watchdog log if > 5MB
if [ -f "$WATCHDOG_LOG" ]; then
    size=$(stat -c%s "$WATCHDOG_LOG" 2>/dev/null || stat -f%z "$WATCHDOG_LOG" 2>/dev/null || echo 0)
    if [ "$size" -gt 5242880 ]; then
        mv "$WATCHDOG_LOG" "$WATCHDOG_LOG.old"
    fi
fi

# Check 1: Is the process running?
process_running=false
if [ -f "$PID_FILE" ]; then
    pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
        process_running=true
    else
        log "WARNING: Stale PID file found (PID $pid not running)"
        rm -f "$PID_FILE"
    fi
fi

if [ "$process_running" = false ]; then
    log "ERROR: AIS harvester is not running. Restarting..."
    bash "$HARVESTER_SCRIPT" start
    log "Restart initiated"
    exit 0
fi

# Check 2: Is the process hung? (no log output in STALE_THRESHOLD seconds)
if [ -f "$LOG_FILE" ]; then
    last_modified=$(stat -c%Y "$LOG_FILE" 2>/dev/null || stat -f%m "$LOG_FILE" 2>/dev/null)
    now=$(date +%s)
    age=$((now - last_modified))

    if [ "$age" -gt "$STALE_THRESHOLD" ]; then
        log "ERROR: AIS harvester appears hung (no log activity for ${age}s). Restarting..."
        bash "$HARVESTER_SCRIPT" stop
        sleep 2
        bash "$HARVESTER_SCRIPT" start
        log "Restart after hung detection completed"
        exit 0
    fi
fi

# Check 3: Is the process a zombie or consuming no CPU at all?
if [ "$process_running" = true ]; then
    proc_state=$(ps -o state= -p "$pid" 2>/dev/null | tr -d ' ')
    if [ "$proc_state" = "Z" ]; then
        log "ERROR: AIS harvester is a zombie process. Restarting..."
        bash "$HARVESTER_SCRIPT" stop
        sleep 2
        bash "$HARVESTER_SCRIPT" start
        log "Restart after zombie detection completed"
        exit 0
    fi
fi

log "OK: AIS harvester running (PID $pid), log age ${age:-0}s"
