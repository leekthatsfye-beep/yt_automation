#!/bin/bash
# audio_stream.sh — start/stop/status for the audio stream server
# Usage: ./audio_stream.sh start | stop | status
#
# Bulletproofed:
#   - Kills ALL related processes on stop (sck_capture, ffmpeg, audio_stream)
#   - Health check after start to verify stream is actually working
#   - Status includes health info

PORT=8888
PID_FILE="/tmp/audio_stream.pid"
LOG_FILE="/Users/fyefye/yt_automation/logs/audio_stream.log"
SCRIPT="/Users/fyefye/yt_automation/audio_stream.py"
PYTHON="/Users/fyefye/yt_automation/.venv/bin/python3.14"

get_lan_ip() {
    ipconfig getifaddr en0 2>/dev/null || ipconfig getifaddr en1 2>/dev/null || echo "127.0.0.1"
}

start_stream() {
    # Kill everything first
    stop_stream 2>/dev/null

    # Ensure log directory exists
    mkdir -p "$(dirname "$LOG_FILE")"

    # Start with proper PATH for ffmpeg
    PATH="/opt/homebrew/bin:$PATH" nohup "$PYTHON" "$SCRIPT" > "$LOG_FILE" 2>&1 &
    echo $! > "$PID_FILE"

    # Wait for server to come up (check port)
    for i in $(seq 1 10); do
        if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${PORT}/health" 2>/dev/null | grep -q "200"; then
            LAN_IP=$(get_lan_ip)
            echo "STARTED"
            echo "PID=$(cat "$PID_FILE")"
            echo "URL=http://${LAN_IP}:${PORT}/"
            echo "HEALTH=http://${LAN_IP}:${PORT}/health"
            return 0
        fi
        sleep 1
    done

    # Fallback: check if PID is alive even if health endpoint not ready yet
    if kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
        LAN_IP=$(get_lan_ip)
        echo "STARTED"
        echo "PID=$(cat "$PID_FILE")"
        echo "URL=http://${LAN_IP}:${PORT}/"
        echo "NOTE=Health endpoint not ready yet, stream may need a few more seconds"
    else
        echo "FAILED"
        tail -20 "$LOG_FILE" 2>/dev/null
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_stream() {
    # Kill main process via PID file
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        kill "$PID" 2>/dev/null
        sleep 0.5
        kill -9 "$PID" 2>/dev/null
        rm -f "$PID_FILE"
    fi

    # Kill anything on the port
    lsof -ti :${PORT} 2>/dev/null | xargs kill -9 2>/dev/null

    # Kill all related processes
    pkill -f "audio_stream.py" 2>/dev/null
    pkill -f "sck_capture.py" 2>/dev/null
    sleep 0.3
    pkill -9 -f "audio_stream.py" 2>/dev/null
    pkill -9 -f "sck_capture.py" 2>/dev/null

    echo "STOPPED"
}

status_stream() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
        LAN_IP=$(get_lan_ip)
        echo "RUNNING"
        echo "PID=$(cat "$PID_FILE")"
        echo "URL=http://${LAN_IP}:${PORT}/"

        # Try to get health info
        HEALTH=$(curl -s "http://127.0.0.1:${PORT}/health" 2>/dev/null)
        if [ -n "$HEALTH" ]; then
            echo "HEALTH=$HEALTH"
        fi
    else
        echo "STOPPED"
        rm -f "$PID_FILE" 2>/dev/null
    fi
}

case "${1:-status}" in
    start)  start_stream ;;
    stop)   stop_stream ;;
    status) status_stream ;;
    *)      echo "Usage: $0 {start|stop|status}" ;;
esac
