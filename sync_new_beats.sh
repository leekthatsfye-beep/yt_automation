#!/bin/bash
# sync_new_beats.sh — Keeps Dropbox/FY3 Beats/NEW BEATS updated weekly
# Only includes beats that have an FLP project file (i.e., beats you made)

TYPBEATS="/Users/fyefye/Library/CloudStorage/Dropbox/FY3 Beats/Type Beats"
DEST="/Users/fyefye/Library/CloudStorage/Dropbox/FY3 Beats/NEW BEATS"

mkdir -p "$DEST"

# Clear old contents
rm -f "$DEST"/*.mp3

# Copy MP3s that have an FLP in the same directory
find "$TYPBEATS" -name "*.flp" 2>/dev/null | while read flp; do
  dir=$(dirname "$flp")
  find "$dir" -name "*.mp3" ! -path "*/Samples/*" ! -path "*Tag*" 2>/dev/null | head -1 | while read mp3; do
    cp "$mp3" "$DEST/"
  done
done

COUNT=$(ls "$DEST"/*.mp3 2>/dev/null | wc -l | tr -d ' ')
echo "[$(date '+%Y-%m-%d %H:%M')] NEW BEATS synced: $COUNT beats" >> /Users/fyefye/yt_automation/sync_new_beats.log
