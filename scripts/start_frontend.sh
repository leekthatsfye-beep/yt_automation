#!/bin/bash
# FY3 Frontend — bulletproof Next.js standalone production server
# Used by LaunchAgent com.fy3.frontend
#
# Bulletproof guarantees:
# 1. Always kills stale processes on the port
# 2. ALWAYS rebuilds if source is newer than the build
# 3. Falls back to existing build if rebuild fails
# 4. Copies static assets into standalone dir after build
# 5. Uses standalone server.js (required for output: "standalone")
# 6. Backend health gate — waits for backend before starting

set -e
export PATH="/opt/homebrew/bin:/usr/local/bin:/usr/bin:/bin"
export NODE_ENV=production

ROOT="/Users/fyefye/yt_automation"
FRONTEND="$ROOT/app/frontend"
PORT=3000
LOG="$ROOT/logs/frontend.log"
STANDALONE="$FRONTEND/.next/standalone"

cd "$FRONTEND"
mkdir -p "$ROOT/logs"

log() { echo "[FY3-FE] $(date '+%Y-%m-%d %H:%M:%S') $*" | tee -a "$LOG"; }

# ── Wait for backend (max 30s) ──
log "Waiting for backend on port 8000..."
for i in $(seq 1 30); do
    if curl -sf http://localhost:8000/docs >/dev/null 2>&1; then
        log "Backend is up"
        break
    fi
    if [ "$i" -eq 30 ]; then
        log "WARNING: Backend not responding after 30s — starting frontend anyway"
    fi
    sleep 1
done

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

# ── Smart rebuild: check if source is newer than build ──
BUILD_ID="$FRONTEND/.next/BUILD_ID"
NEEDS_BUILD=false

if [ ! -f "$BUILD_ID" ]; then
    log "No build found — building..."
    NEEDS_BUILD=true
else
    # Check if any source file is newer than the build
    BUILD_TIME=$(stat -f %m "$BUILD_ID" 2>/dev/null || echo 0)
    # Check key source directories + config for changes
    NEWEST_SRC=$(find "$FRONTEND/src" "$FRONTEND/next.config.ts" "$FRONTEND/tailwind.config.ts" "$FRONTEND/package.json" \
        -name '*.tsx' -o -name '*.ts' -o -name '*.css' -o -name '*.json' 2>/dev/null \
        | xargs stat -f %m 2>/dev/null | sort -rn | head -1)
    if [ -n "$NEWEST_SRC" ] && [ "$NEWEST_SRC" -gt "$BUILD_TIME" ]; then
        log "Source files changed since last build — rebuilding..."
        NEEDS_BUILD=true
    fi
fi

if [ "$NEEDS_BUILD" = true ]; then
    log "Building frontend..."
    if npx next build 2>&1 | tee -a "$LOG"; then
        log "Build succeeded"
    else
        log "WARNING: Build failed!"
        if [ -f "$BUILD_ID" ]; then
            log "Falling back to previous build"
        else
            log "FATAL: No build available. Frontend will NOT start."
            sleep 60
            exit 1
        fi
    fi
fi

# ── Copy static + public assets into standalone dir ──
# Per Next.js docs: "You should copy .next/static to standalone/.next/static"
# and "public to standalone/public"
# See: https://nextjs.org/docs/app/api-reference/config/next-config-js/output
if [ -d "$STANDALONE" ]; then
    log "Syncing static assets to standalone..."

    # .next/static → standalone/.next/static (JS/CSS chunks, build assets)
    mkdir -p "$STANDALONE/.next/static"
    cp -R "$FRONTEND/.next/static/." "$STANDALONE/.next/static/" 2>/dev/null || true

    # public → standalone/public (manifest, icons, fonts, favicon, etc.)
    if [ -d "$FRONTEND/public" ]; then
        mkdir -p "$STANDALONE/public"
        cp -R "$FRONTEND/public/." "$STANDALONE/public/" 2>/dev/null || true
    fi

    log "Static assets synced"
else
    log "FATAL: Standalone build directory missing! Rebuild required."
    sleep 60
    exit 1
fi

# ── Verify standalone server.js exists ──
if [ ! -f "$STANDALONE/server.js" ]; then
    log "FATAL: server.js not found in standalone build."
    sleep 60
    exit 1
fi

# ── Start the standalone server ──
# server.js must run from the standalone root.
# It uses process.chdir(__dirname) and resolves the app via the nested structure.
# PORT env var tells it which port to listen on.
log "Starting standalone server on port $PORT"
cd "$STANDALONE"
export PORT
export HOSTNAME="0.0.0.0"
exec node server.js
