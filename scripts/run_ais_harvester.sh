#!/bin/bash
# AIS Stream harvester management script
# Manages the persistent WebSocket connection to aisstream.io
#
# Usage:
#   ./run_ais_harvester.sh start    - Start the harvester (background)
#   ./run_ais_harvester.sh stop     - Stop the harvester
#   ./run_ais_harvester.sh restart  - Restart the harvester
#   ./run_ais_harvester.sh status   - Check if running

LOG_DIR="/var/log/marine-fishing"
LOG_FILE="$LOG_DIR/ais_harvester.log"
PID_FILE="/tmp/ais_harvester.pid"
MAX_LOG_SIZE=52428800  # 50MB

mkdir -p "$LOG_DIR"

rotate_log() {
    if [ -f "$LOG_FILE" ] && [ "$(stat -f%z "$LOG_FILE" 2>/dev/null || stat -c%s "$LOG_FILE" 2>/dev/null)" -gt "$MAX_LOG_SIZE" ]; then
        mv "$LOG_FILE" "$LOG_FILE.1"
        [ -f "$LOG_FILE.2" ] && rm -f "$LOG_FILE.2"
        [ -f "$LOG_FILE.1" ] && mv "$LOG_FILE.1" "$LOG_FILE.2" 2>/dev/null
    fi
}

start_harvester() {
    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "AIS harvester already running (PID $pid)"
            exit 0
        fi
        rm -f "$PID_FILE"
    fi

    rotate_log

    cd /opt/marine-fishing
    source api/venv/bin/activate
    source api/.env 2>/dev/null

    echo "$(date -Iseconds) - Starting AIS Stream harvester" >> "$LOG_FILE"
    nohup env PYTHONPATH=/opt/marine-fishing python -m harvesters.ais_harvester >> "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"
    echo "AIS harvester started (PID $!)"
}

stop_harvester() {
    if [ ! -f "$PID_FILE" ]; then
        echo "AIS harvester not running (no PID file)"
        exit 0
    fi

    pid=$(cat "$PID_FILE")
    if kill -0 "$pid" 2>/dev/null; then
        echo "Stopping AIS harvester (PID $pid)..."
        kill -TERM "$pid"
        # Wait up to 10 seconds for graceful shutdown
        for i in $(seq 1 10); do
            if ! kill -0 "$pid" 2>/dev/null; then
                break
            fi
            sleep 1
        done
        # Force kill if still running
        if kill -0 "$pid" 2>/dev/null; then
            kill -9 "$pid"
        fi
        echo "AIS harvester stopped"
    else
        echo "AIS harvester not running (stale PID file)"
    fi
    rm -f "$PID_FILE"
}

status_harvester() {
    if [ -f "$PID_FILE" ]; then
        pid=$(cat "$PID_FILE")
        if kill -0 "$pid" 2>/dev/null; then
            echo "AIS harvester is running (PID $pid)"
            exit 0
        else
            echo "AIS harvester is not running (stale PID file)"
            rm -f "$PID_FILE"
            exit 1
        fi
    else
        echo "AIS harvester is not running"
        exit 1
    fi
}

case "${1:-start}" in
    start)
        start_harvester
        ;;
    stop)
        stop_harvester
        ;;
    restart)
        stop_harvester
        start_harvester
        ;;
    status)
        status_harvester
        ;;
    *)
        echo "Usage: $0 {start|stop|restart|status}"
        exit 1
        ;;
esac
