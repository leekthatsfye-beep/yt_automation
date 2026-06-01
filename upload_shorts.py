"""Upload all NextBatch shorts scheduled to match full video publish times."""
import json, sys, time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

LOG_PATH      = ROOT / "uploads_log.json"
SHORTS_LOG    = ROOT / "shorts_uploads_log.json"
RENDERS_DIR   = ROOT / "output" / "renders" / "shorts"
OLD_SHORTS    = ROOT / "output" / "shorts"
THUMBS_DIR    = ROOT / "output" / "thumbs"
META_DIR      = ROOT / "metadata"

# All NextBatch stems with their scheduled publish times (same as full video)
def get_schedule():
    log = json.loads(LOG_PATH.read_text())
    schedule = []
    for stem, d in log.items():
        pub = d.get('publishAt','')
        if not pub or pub < '2026-04-17': continue
        if not d.get('videoId'): continue
        schedule.append((pub, stem, d.get('title','')))
    schedule.sort()
    return schedule

def find_short(stem):
    for d in [RENDERS_DIR, OLD_SHORTS]:
        p = d / f"{stem}_9x16.mp4"
        if p.exists(): return p
    return None

def upload_short(youtube, stem, publish_at, meta, short_path, thumb_path):
    from googleapiclient.http import MediaFileUpload

    raw_title = meta.get('title', stem)
    yt_title  = f"{raw_title} #Shorts"[:100]
    yt_desc   = meta.get('description', '')

    body = {
        "snippet": {
            "title":       yt_title,
            "description": yt_desc,
            "tags":        meta.get('tags', []) + ['shorts', 'typebeat'],
            "categoryId":  "10",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt":     publish_at,
            "selfDeclaredMadeForKids": False,
        },
    }

    media = MediaFileUpload(str(short_path), mimetype="video/mp4", resumable=True)
    req   = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            pct = int(status.resumable_progress / status.total_size * 100)
            print(f"  [{stem}] {pct}%", end="\r")

    vid_id = resp["id"]
    print(f"  [{stem}] ✓ https://youtu.be/{vid_id}")

    # Thumbnail
    if thumb_path and thumb_path.exists():
        try:
            youtube.thumbnails().set(
                videoId=vid_id,
                media_body=MediaFileUpload(str(thumb_path))
            ).execute()
        except Exception as te:
            print(f"  [{stem}] ⚠ thumb failed: {te}")

    return vid_id

def main():
    from youtube_auth import get_youtube_service
    youtube = get_youtube_service()

    shorts_log = json.loads(SHORTS_LOG.read_text()) if SHORTS_LOG.exists() else {}
    schedule   = get_schedule()

    print(f"Uploading {len(schedule)} shorts...")

    for pub, stem, title in schedule:
        # Skip already uploaded
        if stem in shorts_log and shorts_log[stem].get('videoId'):
            print(f"[SKIP] {stem}")
            continue

        short_path = find_short(stem)
        if not short_path:
            print(f"[MISS] {stem} — no short file")
            continue

        meta_path = META_DIR / f"{stem}.json"
        if not meta_path.exists():
            print(f"[MISS] {stem} — no metadata")
            continue
        meta = json.loads(meta_path.read_text())

        thumb_path = THUMBS_DIR / f"{stem}_thumb.jpg"
        print(f"\n[SHORT] {stem} → {pub[:16]}")

        try:
            vid_id = upload_short(youtube, stem, pub, meta, short_path, thumb_path)

            shorts_log = json.loads(SHORTS_LOG.read_text()) if SHORTS_LOG.exists() else {}
            shorts_log[stem] = {
                "videoId":    vid_id,
                "url":        f"https://youtu.be/{vid_id}",
                "uploadedAt": datetime.now(timezone.utc).isoformat(),
                "title":      f"{meta.get('title','')} #Shorts",
                "publishAt":  pub,
            }
            SHORTS_LOG.write_text(json.dumps(shorts_log, indent=2))

        except Exception as e:
            print(f"  [{stem}] ERROR: {e}")
            if "quotaExceeded" in str(e):
                print("\n⛔ Quota hit — rerun tomorrow")
                break

        time.sleep(2)

    print("\n=== DONE ===")
    sl = json.loads(SHORTS_LOG.read_text()) if SHORTS_LOG.exists() else {}
    uploaded = sum(1 for d in sl.values() if d.get('videoId'))
    print(f"Shorts uploaded: {uploaded}/{len(schedule)}")

if __name__ == "__main__":
    main()
