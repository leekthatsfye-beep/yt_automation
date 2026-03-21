#!/bin/bash
# FY3 Watchdog — auto-heals dead services + detects silent failures
# Runs every 2 minutes via LaunchAgent
#
# Layer 1: Port-level health (is the process alive?)
# Layer 2: Chunk-level health (are JS bundles serving correctly?)
# Layer 3: Memory leak detection (is the process consuming too much RAM?)
# Layer 4: Stale build detection (are source files newer than the build?)

export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"

ROOT="/Users/fyefye/yt_automation"
FRONTEND="$ROOT/app/frontend"
LOG="$ROOT/logs/watchdog.log"
mkdir -p "$ROOT/logs"

log() { echo "[FY3-WD] $(date '+%Y-%m-%d %H:%M:%S') $*" >> "$LOG"; }

# Max memory in KB before we consider it a leak (1.5 GB)
MAX_MEM_KB=1572864

FIXED=0

restart_frontend() {
    local reason="$1"
    log "Frontend RESTART — reason: $reason"
    launchctl unload ~/Library/LaunchAgents/com.fy3.frontend.plist 2>/dev/null || true
    sleep 2
    # Kill anything lingering on port 3000
    lsof -ti tcp:3000 | xargs kill -9 2>/dev/null || true
    sleep 1
    launchctl load ~/Library/LaunchAgents/com.fy3.frontend.plist 2>/dev/null || true

    # Frontend may rebuild — wait up to 90s
    for i in $(seq 1 45); do
        if curl -sf --max-time 3 http://localhost:3000/ >/dev/null 2>&1; then
            log "Frontend RECOVERED after $((i * 2))s"
            FIXED=$((FIXED + 1))
            return 0
        fi
        sleep 2
    done
    log "Frontend FAILED to recover — check logs/frontend.log"
    return 1
}

# ── Check backend (port 8000) ──
if ! curl -sf --max-time 5 http://localhost:8000/docs >/dev/null 2>&1; then
    log "Backend DOWN — restarting..."
    launchctl unload ~/Library/LaunchAgents/com.fy3.backend.plist 2>/dev/null || true
    sleep 2
    launchctl load ~/Library/LaunchAgents/com.fy3.backend.plist

    for i in $(seq 1 15); do
        if curl -sf --max-time 3 http://localhost:8000/docs >/dev/null 2>&1; then
            log "Backend RECOVERED after ${i}s"
            FIXED=$((FIXED + 1))
            break
        fi
        sleep 1
    done

    if ! curl -sf --max-time 3 http://localhost:8000/docs >/dev/null 2>&1; then
        log "Backend FAILED to recover — check logs/backend.log"
    fi
fi

# ── Check frontend — Layer 1: Port health ──
if ! curl -sf --max-time 5 http://localhost:3000/ >/dev/null 2>&1; then
    restart_frontend "port 3000 not responding"
else
    # ── Layer 2: Chunk corruption detection ──
    # The white-screen bug: HTML serves 200 but JS chunks return 500
    # Sample 3 random JS chunks from the page — if ANY return non-200, the build is corrupt
    CHUNK_URLS=$(curl -s --max-time 5 http://localhost:3000/ 2>/dev/null | grep -o '/_next/static/chunks/[a-zA-Z0-9_.-]*\.js' | head -5)
    CHUNK_FAIL=0
    CHUNK_CHECKED=0
    for chunk in $CHUNK_URLS; do
        STATUS=$(curl -s -o /dev/null -w "%{http_code}" --max-time 5 "http://localhost:3000${chunk}" 2>/dev/null)
        CHUNK_CHECKED=$((CHUNK_CHECKED + 1))
        if [ "$STATUS" != "200" ]; then
            CHUNK_FAIL=$((CHUNK_FAIL + 1))
            log "Chunk CORRUPT: $chunk returned HTTP $STATUS"
        fi
    done

    if [ "$CHUNK_FAIL" -gt 0 ]; then
        log "Chunk corruption detected ($CHUNK_FAIL/$CHUNK_CHECKED failed) — rebuilding..."
        # Clear the build cache so start_frontend.sh does a clean rebuild
        rm -rf "$FRONTEND/.next/cache" 2>/dev/null
        restart_frontend "chunk corruption ($CHUNK_FAIL chunks returning non-200)"
    fi

    # ── Layer 3: Memory leak detection ──
    FE_PID=$(lsof -ti tcp:3000 2>/dev/null | head -1)
    if [ -n "$FE_PID" ]; then
        # Get RSS in KB (macOS ps reports in KB)
        RSS_KB=$(ps -o rss= -p "$FE_PID" 2>/dev/null | tr -d ' ')
        if [ -n "$RSS_KB" ] && [ "$RSS_KB" -gt "$MAX_MEM_KB" ]; then
            RSS_MB=$((RSS_KB / 1024))
            log "Frontend memory leak: PID $FE_PID using ${RSS_MB}MB (limit: $((MAX_MEM_KB / 1024))MB)"
            restart_frontend "memory leak (${RSS_MB}MB)"
        fi
    fi

    # ── Layer 4: Stale build detection ──
    # If source files are newer than the build, trigger rebuild
    BUILD_ID="$FRONTEND/.next/BUILD_ID"
    if [ -f "$BUILD_ID" ]; then
        BUILD_TIME=$(stat -f %m "$BUILD_ID" 2>/dev/null || echo 0)
        NEWEST_SRC=$(find "$FRONTEND/src" "$FRONTEND/next.config.ts" "$FRONTEND/tailwind.config.ts" \
            -name '*.tsx' -o -name '*.ts' -o -name '*.css' 2>/dev/null \
            | xargs stat -f %m 2>/dev/null | sort -rn | head -1)
        if [ -n "$NEWEST_SRC" ] && [ "$NEWEST_SRC" -gt "$BUILD_TIME" ]; then
            log "Stale build detected — source newer than build, triggering rebuild..."
            restart_frontend "stale build (source newer than BUILD_ID)"
        fi
    fi
fi

# ── Check tunnel ──
if ! pgrep -q cloudflared 2>/dev/null; then
    log "Tunnel DOWN — restarting..."
    launchctl unload ~/Library/LaunchAgents/com.fy3.tunnel.plist 2>/dev/null || true
    sleep 2
    launchctl load ~/Library/LaunchAgents/com.fy3.tunnel.plist

    for i in $(seq 1 15); do
        if pgrep -q cloudflared 2>/dev/null; then
            log "Tunnel RECOVERED after ${i}s"
            FIXED=$((FIXED + 1))
            break
        fi
        sleep 1
    done

    if ! pgrep -q cloudflared 2>/dev/null; then
        log "Tunnel FAILED to recover — check logs/tunnel.log"
    fi
fi

# Only log if something was fixed (keep log clean)
if [ "$FIXED" -gt 0 ]; then
    log "Watchdog fixed $FIXED service(s)"
fi

# Trim watchdog log (keep last 500 lines)
if [ -f "$LOG" ] && [ "$(wc -l < "$LOG")" -gt 1000 ]; then
    tail -500 "$LOG" > "$LOG.tmp" && mv "$LOG.tmp" "$LOG"
fi
