"""
fix_short_descriptions.py — Update all today's Shorts with correct description:
  - Correct Airbit purchase link (from store_uploads_log)
  - Link to full YouTube video (from uploads_log)
"""
import json, sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).parent))

from social_upload import _build_purchase_desc, load_social_log
from youtube_auth import get_youtube_service

ROOT        = Path(__file__).parent
UPLOADS_LOG = ROOT / "uploads_log.json"

uploads_data = json.loads(UPLOADS_LOG.read_text())
social       = load_social_log()
youtube      = get_youtube_service()

# All shorts uploaded today
targets = [
    (stem, info["youtube_shorts"]["videoId"])
    for stem, info in social.items()
    if info.get("youtube_shorts", {}).get("status") == "ok"
    and info["youtube_shorts"].get("uploadedAt", "").startswith("2026-04-02")
]

print(f"Updating {len(targets)} shorts...")

ok = 0
for stem, video_id in targets:
    purchase_desc  = _build_purchase_desc(stem)
    full_video_url = uploads_data.get(stem, {}).get("url", "")
    full_video_line = f"\n\n🎵 Full video:\n{full_video_url}" if full_video_url else ""
    new_desc = f"{purchase_desc}{full_video_line}\n\n#Shorts #TypeBeat".strip()[:5000]

    try:
        # Fetch current snippet (need categoryId + title to update)
        current = youtube.videos().list(part="snippet", id=video_id).execute()
        items = current.get("items", [])
        if not items:
            print(f"  [SKIP] {stem} — video not found on YouTube")
            continue
        snippet = items[0]["snippet"]
        snippet["description"] = new_desc

        youtube.videos().update(
            part="snippet",
            body={"id": video_id, "snippet": snippet}
        ).execute()
        print(f"  [OK] {stem} — updated")
        ok += 1
    except Exception as e:
        print(f"  [ERR] {stem}: {e}")

print(f"\nDone. {ok}/{len(targets)} updated.")
