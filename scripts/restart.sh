#!/bin/bash
# FY3 — Safe restart of all services
# Usage: ./scripts/restart.sh [backend|frontend|tunnel|all]
#
# This script:
# 1. Validates code before restarting (catches import/build errors)
# 2. Gracefully stops services
# 3. Rebuilds frontend + syncs static assets for standalone mode
# 4. Restarts via LaunchAgents
# 5. Waits and verifies services are healthy

set -e

ROOT="/Users/fyefye/yt_automation"
PYTHON="$ROOT/.venv/bin/python3.14"
FRONTEND="$ROOT/app/frontend"
STANDALONE="$FRONTEND/.next/standalone"
TARGET="${1:-all}"

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[0;33m'
NC='\033[0m'

log() { echo -e "${GREEN}[FY3]${NC} $*"; }
warn() { echo -e "${YELLOW}[FY3]${NC} $*"; }
fail() { echo -e "${RED}[FY3]${NC} $*"; }

cd "$ROOT"

# ── Backend restart ──
restart_backend() {
    log "Validating backend imports..."
    if ! $PYTHON -c "from app.backend.main import app" 2>&1; then
        fail "Backend imports FAILED. Fix the error before restarting."
        return 1
    fi
    log "Backend imports OK"

    log "Restarting backend..."
    launchctl unload ~/Library/LaunchAgents/com.fy3.backend.plist 2>/dev/null || true
    sleep 2
    launchctl load ~/Library/LaunchAgents/com.fy3.backend.plist

    # Wait for health
    for i in $(seq 1 15); do
        if curl -sf http://localhost:8000/docs >/dev/null 2>&1; then
            log "Backend is healthy (port 8000) ✓"
            return 0
        fi
        sleep 1
    done
    fail "Backend did not start within 15s — check logs/backend.log"
    return 1
}

# ── Frontend restart ──
restart_frontend() {
    log "Building frontend..."
    cd "$FRONTEND"
    if ! npx next build 2>&1 | tail -10; then
        fail "Frontend build FAILED. Fix the error before restarting."
        return 1
    fi
    log "Build OK"

    # Sync static + public into standalone dir (per Next.js docs)
    if [ -d "$STANDALONE" ]; then
        log "Syncing static assets to standalone..."
        mkdir -p "$STANDALONE/.next/static"
        cp -R "$FRONTEND/.next/static/." "$STANDALONE/.next/static/" 2>/dev/null || true
        if [ -d "$FRONTEND/public" ]; then
            mkdir -p "$STANDALONE/public"
            cp -R "$FRONTEND/public/." "$STANDALONE/public/" 2>/dev/null || true
        fi
        log "Static assets synced"
    else
        fail "Standalone build dir missing after build!"
        return 1
    fi

    log "Restarting frontend..."
    launchctl unload ~/Library/LaunchAgents/com.fy3.frontend.plist 2>/dev/null || true
    sleep 2
    launchctl load ~/Library/LaunchAgents/com.fy3.frontend.plist

    cd "$ROOT"

    # Wait for health
    for i in $(seq 1 25); do
        if curl -sf http://localhost:3000/ >/dev/null 2>&1; then
            log "Frontend is healthy (port 3000) ✓"
            return 0
        fi
        sleep 1
    done
    fail "Frontend did not start within 25s — check logs/frontend.log"
    return 1
}

# ── Tunnel restart ──
restart_tunnel() {
    log "Restarting Cloudflare tunnel..."
    launchctl unload ~/Library/LaunchAgents/com.fy3.tunnel.plist 2>/dev/null || true
    sleep 2
    launchctl load ~/Library/LaunchAgents/com.fy3.tunnel.plist

    # Wait for tunnel to connect
    for i in $(seq 1 20); do
        if pgrep -q cloudflared 2>/dev/null; then
            log "Cloudflare tunnel is running (fy3studio.com) ✓"
            return 0
        fi
        sleep 1
    done
    fail "Tunnel did not start within 20s — check logs/tunnel.log"
    return 1
}

# ── Status check ──
check_status() {
    echo ""
    log "=== Service Status ==="

    if curl -sf http://localhost:8000/docs >/dev/null 2>&1; then
        log "Backend  : ✓ running (port 8000)"
    else
        fail "Backend  : ✗ DOWN"
    fi

    if curl -sf http://localhost:3000/ >/dev/null 2>&1; then
        log "Frontend : ✓ running (port 3000)"
    else
        fail "Frontend : ✗ DOWN"
    fi

    if pgrep -q cloudflared 2>/dev/null; then
        log "Tunnel   : ✓ running (fy3studio.com)"
    else
        fail "Tunnel   : ✗ DOWN"
    fi
    echo ""
}

case "$TARGET" in
    backend)
        restart_backend
        ;;
    frontend)
        restart_frontend
        ;;
    tunnel)
        restart_tunnel
        ;;
    all)
        log "=== Full restart ==="
        restart_backend
        restart_frontend
        restart_tunnel
        check_status
        log "=== All services running ==="
        ;;
    status)
        check_status
        ;;
    *)
        echo "Usage: $0 [backend|frontend|tunnel|all|status]"
        exit 1
        ;;
esac
