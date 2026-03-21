#!/bin/bash
# ============================================================
#  quota_reset_batch.sh
#  Run after YouTube API quota resets (midnight Pacific / 3 AM ET)
#  Handles: delete duplicate, fix thumbnails, upload batch 1 + 2
# ============================================================

set -e
cd /Users/fyefye/yt_automation
PYTHON="/Users/fyefye/yt_automation/.venv/bin/python3.14"

echo "============================================"
echo "  YouTube Quota Reset Batch Runner"
echo "  Started: $(date)"
echo "============================================"
echo ""

# ── Step 1: Delete remaining duplicate Beatspink Pussy ──
echo "── Step 1: Deleting duplicate Beatspink Pussy (yeEa3jQfz9M) ──"
$PYTHON -c "
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
import json

with open('token.json') as f:
    td = json.load(f)
creds = Credentials(token=td['token'], refresh_token=td['refresh_token'],
    token_uri=td['token_uri'], client_id=td['client_id'],
    client_secret=td['client_secret'], scopes=td['scopes'])
yt = build('youtube', 'v3', credentials=creds)
try:
    yt.videos().delete(id='yeEa3jQfz9M').execute()
    print('Deleted yeEa3jQfz9M')
except Exception as e:
    print(f'Failed: {e}')
"
echo ""

# ── Step 2: Retry thumbnails for drake and pop ──
echo "── Step 2: Retrying thumbnails for drake (sQ4_Q68-FQ8) and pop (_vu0D-ZTLjc) ──"
$PYTHON -c "
from google.oauth2.credentials import Credentials
from googleapiclient.discovery import build
from googleapiclient.http import MediaFileUpload
import json

with open('token.json') as f:
    td = json.load(f)
creds = Credentials(token=td['token'], refresh_token=td['refresh_token'],
    token_uri=td['token_uri'], client_id=td['client_id'],
    client_secret=td['client_secret'], scopes=td['scopes'])
yt = build('youtube', 'v3', credentials=creds)

thumbs = [
    ('drake', 'sQ4_Q68-FQ8', 'output/drake_thumb.jpg'),
    ('pop', '_vu0D-ZTLjc', 'output/pop_thumb.jpg'),
]
for name, vid_id, thumb_path in thumbs:
    try:
        media = MediaFileUpload(thumb_path, mimetype='image/jpeg')
        yt.thumbnails().set(videoId=vid_id, media_body=media).execute()
        print(f'Thumbnail set for {name} ({vid_id})')
    except Exception as e:
        print(f'Thumbnail failed for {name}: {e}')
"
echo ""

# ── Step 3: Upload remaining batch 1 (3 Sexyy Red beats) ──
echo "── Step 3: Uploading remaining batch 1 beats ──"

echo "  guard_up_139 -> Mar 16, 6 PM ET"
$PYTHON upload.py --only "guard_up_139" --schedule-at "2026-03-16T18:00:00-05:00"
echo ""

echo "  mormon_152 -> Mar 17, 6 PM ET"
$PYTHON upload.py --only "mormon_152" --schedule-at "2026-03-17T18:00:00-05:00"
echo ""

echo "  black_fade_126 -> Mar 18, 6 PM ET"
$PYTHON upload.py --only "black_fade_126" --schedule-at "2026-03-18T18:00:00-05:00"
echo ""

# ── Step 4: Upload batch 2 — BiggKutt8 (11 AM ET) ──
echo "── Step 4: Uploading batch 2 — BiggKutt8 at 11 AM ET ──"

echo "  no_gamez_115 -> Mar 19"
$PYTHON upload.py --only "no_gamez_115" --schedule-at "2026-03-19T11:00:00-05:00"

echo "  south_beach -> Mar 20"
$PYTHON upload.py --only "south_beach" --schedule-at "2026-03-20T11:00:00-05:00"

echo "  ocean_drive -> Mar 21"
$PYTHON upload.py --only "ocean_drive" --schedule-at "2026-03-21T11:00:00-05:00"

echo "  voices -> Mar 22"
$PYTHON upload.py --only "voices" --schedule-at "2026-03-22T11:00:00-05:00"

echo "  control -> Mar 23"
$PYTHON upload.py --only "control" --schedule-at "2026-03-23T11:00:00-05:00"

echo "  ana -> Mar 24"
$PYTHON upload.py --only "ana" --schedule-at "2026-03-24T11:00:00-05:00"

# At this point we'll likely hit quota again (6 uploads = 9600 units)
# The rest will need to wait for the NEXT day's quota reset

echo ""
echo "============================================"
echo "  QUOTA CHECK: 6 uploads = ~9,600 units"
echo "  Daily quota = 10,000 units"
echo "  Remaining uploads will need next day's quota"
echo "============================================"
echo ""

echo "  late_night -> Mar 25"
$PYTHON upload.py --only "late_night" --schedule-at "2026-03-25T11:00:00-05:00" || echo "  [QUOTA HIT] late_night deferred"

echo "  wait_on_me -> Mar 26"
$PYTHON upload.py --only "wait_on_me" --schedule-at "2026-03-26T11:00:00-05:00" || echo "  [QUOTA HIT] wait_on_me deferred"

echo "  never_came -> Mar 27"
$PYTHON upload.py --only "never_came" --schedule-at "2026-03-27T11:00:00-05:00" || echo "  [QUOTA HIT] never_came deferred"

echo "  all_of_you -> Mar 28"
$PYTHON upload.py --only "all_of_you" --schedule-at "2026-03-28T11:00:00-05:00" || echo "  [QUOTA HIT] all_of_you deferred"

echo ""

# ── Step 5: Upload batch 2 — Sexyy Red (6 PM ET) ──
echo "── Step 5: Uploading batch 2 — Sexyy Red at 6 PM ET ──"

echo "  rager_boy_146 -> Mar 19"
$PYTHON upload.py --only "rager_boy_146" --schedule-at "2026-03-19T18:00:00-05:00" || echo "  [QUOTA HIT] rager_boy_146 deferred"

echo "  papi -> Mar 20"
$PYTHON upload.py --only "papi" --schedule-at "2026-03-20T18:00:00-05:00" || echo "  [QUOTA HIT] papi deferred"

echo "  back -> Mar 21"
$PYTHON upload.py --only "back" --schedule-at "2026-03-21T18:00:00-05:00" || echo "  [QUOTA HIT] back deferred"

echo "  my_fault -> Mar 22"
$PYTHON upload.py --only "my_fault" --schedule-at "2026-03-22T18:00:00-05:00" || echo "  [QUOTA HIT] my_fault deferred"

echo "  picky -> Mar 23"
$PYTHON upload.py --only "picky" --schedule-at "2026-03-23T18:00:00-05:00" || echo "  [QUOTA HIT] picky deferred"

echo "  real_right -> Mar 24"
$PYTHON upload.py --only "real_right" --schedule-at "2026-03-24T18:00:00-05:00" || echo "  [QUOTA HIT] real_right deferred"

echo "  wut_u_on -> Mar 25"
$PYTHON upload.py --only "wut_u_on" --schedule-at "2026-03-25T18:00:00-05:00" || echo "  [QUOTA HIT] wut_u_on deferred"

echo "  kiss_my_ass -> Mar 26"
$PYTHON upload.py --only "kiss_my_ass" --schedule-at "2026-03-26T18:00:00-05:00" || echo "  [QUOTA HIT] kiss_my_ass deferred"

echo "  twerk -> Mar 27"
$PYTHON upload.py --only "twerk" --schedule-at "2026-03-27T18:00:00-05:00" || echo "  [QUOTA HIT] twerk deferred"

echo "  go_gooo -> Mar 28"
$PYTHON upload.py --only "go_gooo" --schedule-at "2026-03-28T18:00:00-05:00" || echo "  [QUOTA HIT] go_gooo deferred"

echo ""
echo "============================================"
echo "  Batch complete: $(date)"
echo "  Any [QUOTA HIT] items need re-running tomorrow"
echo "  Re-run with: bash quota_reset_batch.sh"
echo "  (upload.py skips already-uploaded stems automatically)"
echo "============================================"
