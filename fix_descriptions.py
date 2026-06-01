"""
Run this to push the clean description format to all YouTube videos.
Quota resets at midnight Pacific — run after 12am PT.
"""
import json, time, sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))
from youtube_auth import get_youtube_service_with_fallback
yt = get_youtube_service_with_fallback()

uploads_log = json.loads((ROOT / 'uploads_log.json').read_text())
store_log = json.loads((ROOT / 'store_uploads_log.json').read_text())

STORE_BEATS = 'https://leekthatsfy3.infinity.airbit.com/beats'
ARTIST_COUPONS = {
    'sexyy red':    'SEXYY',
    'biggkutt8':    'BIGGKUTT',
    'glokk40spazz': 'GLOKKFYE',
    'ola runt':     'OLARUNT',
    'shawtyrokk':   'SHAWTYROKK',
}

def build_description(stem, title):
    entry = store_log.get(stem, {})
    airbit = entry.get('airbit', entry) if isinstance(entry, dict) else {}
    beat_url = airbit.get('url', '') or STORE_BEATS

    coupon = next((code for artist, code in ARTIST_COUPONS.items() if artist in title.lower()), None)

    lines = [
        f"🎵 Purchase / Download\n{beat_url}",
        f"🛒 Browse All Beats\n{STORE_BEATS}",
        "━━━━━━━━━━━━━━━━━━━━━━━━━",
        "📦 BUNDLE DEALS AVAILABLE\nContact us for bundle pricing on multiple leases",
    ]
    coupon_lines = []
    if coupon:
        coupon_lines.append(f"🎟️ USE CODE [{coupon}] FOR 15% OFF")
    coupon_lines.append("🎟️ NEW CUSTOMERS: Code [FY3NEW] for 20% off")
    lines.append("\n".join(coupon_lines))
    lines.append("━━━━━━━━━━━━━━━━━━━━━━━━━")
    lines.append("prod. leekthatsfy3\n© 2026 LeekThatsFy3. Unauthorized use is prohibited.")

    return "\n\n".join(lines)

all_ids = [info['videoId'] for info in uploads_log.values() if info.get('videoId')]
print(f"Updating {len(all_ids)} videos...")
ok = fail = 0

for i in range(0, len(all_ids), 50):
    chunk = all_ids[i:i+50]
    resp = yt.videos().list(part='snippet', id=','.join(chunk)).execute()
    for item in resp['items']:
        vid_id = item['id']
        snippet = item['snippet']
        title = snippet.get('title', '')
        stem = next((s for s, info in uploads_log.items() if info.get('videoId') == vid_id), None)
        if not stem:
            continue
        try:
            snippet['description'] = build_description(stem, title)
            yt.videos().update(part='snippet', body={'id': vid_id, 'snippet': snippet}).execute()
            print(f"  ✓ {title[:60]}")
            ok += 1
            time.sleep(0.3)
        except Exception as e:
            print(f"  ✗ {title[:50]}: {e}")
            fail += 1

print(f"\nDone! ✓ {ok}  ✗ {fail}")
