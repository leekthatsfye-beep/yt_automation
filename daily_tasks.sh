#!/bin/bash
# daily_tasks.sh — runs after YouTube quota resets (midnight Pacific = 3am EST)
# Cron: 5 3 * * * /Users/fyefye/yt_automation/daily_tasks.sh >> /Users/fyefye/yt_automation/daily_tasks.log 2>&1

cd /Users/fyefye/yt_automation
source .venv/bin/activate

echo "=== $(date) — Daily tasks starting ==="

# 1. Pin purchase comments on any videos not yet pinned
echo "[1/2] Pinning purchase comments..."
python3 pin_short_comments.py
echo ""

# 2. Upload fire_man short (if not yet in shorts log)
echo "[2/2] Uploading fire_man short (if needed)..."
python3 -c "
import json, sys
from pathlib import Path
slog = json.loads(Path('shorts_uploads_log.json').read_text())
if 'fire_man' in slog and slog['fire_man'].get('videoId'):
    print('  [SKIP] fire_man short already uploaded')
    sys.exit(0)

# Upload it
import time
from googleapiclient.http import MediaFileUpload
from youtube_auth import get_youtube_service

youtube = get_youtube_service()
ROOT = Path('.')
short_path = ROOT / 'output' / 'renders' / 'shorts' / 'fire_man_9x16.mp4'
thumb_path = ROOT / 'output' / 'thumbs' / 'fire_man_thumb.jpg'
meta = json.loads((ROOT / 'metadata' / 'fire_man.json').read_text())

body = {
    'snippet': {
        'title': f'{meta[\"title\"]} #Shorts'[:100],
        'description': meta.get('description', ''),
        'tags': meta.get('tags', []) + ['shorts', 'typebeat'],
        'categoryId': '10',
    },
    'status': {'privacyStatus': 'public', 'selfDeclaredMadeForKids': False},
}

media = MediaFileUpload(str(short_path), mimetype='video/mp4', resumable=True)
req = youtube.videos().insert(part='snippet,status', body=body, media_body=media)
resp = None
while resp is None:
    _, resp = req.next_chunk()
vid_id = resp['id']
print(f'  ✓ fire_man short uploaded: https://youtu.be/{vid_id}')

if thumb_path.exists():
    try:
        youtube.thumbnails().set(videoId=vid_id, media_body=MediaFileUpload(str(thumb_path))).execute()
    except: pass

slog['fire_man'] = {'videoId': vid_id, 'url': f'https://youtu.be/{vid_id}',
    'uploadedAt': str(time.time()), 'title': body['snippet']['title'], 'privacy': 'public'}
Path('shorts_uploads_log.json').write_text(json.dumps(slog, indent=2))
"

echo "=== $(date) — Daily tasks done ==="
