#!/bin/bash
# acestep_server.sh — start/stop/status for ACE-Step API server
# Usage: ./acestep_server.sh start | stop | status

PORT=8001
PID_FILE="/tmp/acestep.pid"
LOG_FILE="/Users/fyefye/yt_automation/logs/acestep.log"
ACESTEP_DIR="/Users/fyefye/ACE-Step-1.5"

start_server() {
    stop_server 2>/dev/null

    mkdir -p "$(dirname "$LOG_FILE")"

    cd "$ACESTEP_DIR" || exit 1

    ACESTEP_LM_BACKEND=mlx \
    ACESTEP_OFFLOAD_TO_CPU=true \
    ACESTEP_OFFLOAD_DIT_TO_CPU=true \
    ACESTEP_MPS_DECODE_OFFLOAD=true \
    TOKENIZERS_PARALLELISM=false \
    PYTORCH_MPS_HIGH_WATERMARK_RATIO=0.0 \
    PATH="/opt/homebrew/bin:$PATH" \
    nohup uv run acestep-api --host 127.0.0.1 --port "$PORT" > "$LOG_FILE" 2>&1 &

    echo $! > "$PID_FILE"

    # Wait up to 120s for server (model loading takes time)
    echo "Waiting for ACE-Step to load models..."
    for i in $(seq 1 120); do
        if curl -s -o /dev/null -w "%{http_code}" "http://127.0.0.1:${PORT}/health" 2>/dev/null | grep -q "200"; then
            echo "STARTED"
            echo "PID=$(cat "$PID_FILE")"
            echo "URL=http://127.0.0.1:${PORT}"
            echo "DOCS=http://127.0.0.1:${PORT}/docs"
            return 0
        fi
        sleep 1
    done

    if kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
        echo "STARTED (still loading models...)"
        echo "PID=$(cat "$PID_FILE")"
        echo "URL=http://127.0.0.1:${PORT}"
    else
        echo "FAILED"
        tail -20 "$LOG_FILE" 2>/dev/null
        rm -f "$PID_FILE"
        return 1
    fi
}

stop_server() {
    if [ -f "$PID_FILE" ]; then
        PID=$(cat "$PID_FILE")
        kill "$PID" 2>/dev/null
        sleep 1
        kill -9 "$PID" 2>/dev/null
        rm -f "$PID_FILE"
    fi
    pkill -f "acestep-api" 2>/dev/null
    sleep 0.5
    pkill -9 -f "acestep-api" 2>/dev/null
    lsof -ti :${PORT} 2>/dev/null | xargs kill -9 2>/dev/null
    echo "STOPPED"
}

status_server() {
    if [ -f "$PID_FILE" ] && kill -0 "$(cat "$PID_FILE" 2>/dev/null)" 2>/dev/null; then
        HEALTH=$(curl -s "http://127.0.0.1:${PORT}/health" 2>/dev/null)
        if echo "$HEALTH" | grep -q '"ok"'; then
            echo "RUNNING"
        else
            echo "LOADING"
        fi
        echo "PID=$(cat "$PID_FILE")"
        echo "URL=http://127.0.0.1:${PORT}"
    else
        echo "STOPPED"
        rm -f "$PID_FILE" 2>/dev/null
    fi
}

case "${1:-status}" in
    start)  start_server ;;
    stop)   stop_server ;;
    status) status_server ;;
    *)      echo "Usage: $0 {start|stop|status}" ;;
esac
