#!/bin/bash
# FY3 Cloudflare Tunnel — auto-start script
# Starts cloudflared quick tunnel and saves the public URL

LOG_DIR="/Users/fyefye/yt_automation/logs"
URL_FILE="/Users/fyefye/yt_automation/tunnel_url.txt"
TUNNEL_LOG="$LOG_DIR/tunnel.log"
PORT=3000

mkdir -p "$LOG_DIR"

# Kill any existing tunnel
pkill -f "cloudflared tunnel" 2>/dev/null
sleep 1

echo "[$(date)] Starting Cloudflare tunnel on port $PORT..." >> "$TUNNEL_LOG"

# Start cloudflared and capture output to extract URL
/opt/homebrew/bin/cloudflared tunnel --url "http://localhost:$PORT" 2>&1 | while IFS= read -r line; do
  echo "$line" >> "$TUNNEL_LOG"
  # Extract the tunnel URL when it appears
  if echo "$line" | grep -qoE 'https://[a-z0-9-]+\.trycloudflare\.com'; then
    URL=$(echo "$line" | grep -oE 'https://[a-z0-9-]+\.trycloudflare\.com')
    echo "$URL" > "$URL_FILE"
    echo "[$(date)] Tunnel URL: $URL" >> "$TUNNEL_LOG"
  fi
done
