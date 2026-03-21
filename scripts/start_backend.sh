#!/bin/bash
# FY3 Backend — bulletproof FastAPI server
# Used by LaunchAgent com.fy3.backend
#
# Bulletproof guarantees:
# 1. Always kills stale processes on the port
# 2. Validates Python + imports before starting
# 3. Catches import errors and logs them clearly
# 4. Uvicorn hardened with WS keepalive + graceful shutdown

set -e
export PATH="/Users/fyefye/yt_automation/.venv/bin:/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

ROOT="/Users/fyefye/yt_automation"
PYTHON="$ROOT/.venv/bin/python3.14"
PORT=8000
LOG="$ROOT/logs/backend.log"

cd "$ROOT"
mkdir -p "$ROOT/logs"

log() { echo "[FY3-BE] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

# ── Kill any stale process on port ──
STALE_PID=$(lsof -ti tcp:$PORT 2>/dev/null || true)
if [ -n "$STALE_PID" ]; then
    log "Killing stale process on port $PORT (PID: $STALE_PID)"
    kill -9 $STALE_PID 2>/dev/null || true
    sleep 1
fi

# ── Wait for port to be free (max 10s) ──
for i in $(seq 1 10); do
    if ! lsof -ti tcp:$PORT >/dev/null 2>&1; then
        break
    fi
    log "Port $PORT still in use, waiting... ($i/10)"
    sleep 1
done

# ── Validate imports before starting ──
# This catches syntax errors, missing modules, bad router imports
# so the server doesn't crash-loop with a broken import
log "Validating backend imports..."
if ! $PYTHON -c "from app.backend.main import app" 2>>"$LOG"; then
    log "FATAL: Backend imports failed! Check logs. Server will NOT start."
    log "Fix the import error, then: launchctl unload/load ~/Library/LaunchAgents/com.fy3.backend.plist"
    # Sleep to prevent LaunchAgent crash-loop (ThrottleInterval only helps so much)
    sleep 60
    exit 1
fi
log "Imports OK"

log "Starting backend server on port $PORT"
exec $PYTHON -m uvicorn \
    app.backend.main:app \
    --host 0.0.0.0 \
    --port $PORT \
    --ws-ping-interval 30 \
    --ws-ping-timeout 120 \
    --timeout-keep-alive 120 \
    --timeout-graceful-shutdown 10 \
    --log-level info
