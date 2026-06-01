"""
Upload the 9 remaining NextBatch beats that didn't complete in batch3.
Schedule: May 1-4 at 10am/2pm/8pm EDT
"""
import json, sys, time
from pathlib import Path
from datetime import datetime, timezone

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

RENDERS_DIR = ROOT / "output" / "renders"
THUMBS_DIR  = ROOT / "output" / "thumbs"
LOG_PATH    = ROOT / "uploads_log.json"

BEATS = [
    ("schmell_me",        "2026-05-01T14:00:00Z"),
    ("sauce_165",         "2026-05-01T18:00:00Z"),
    ("screeet",           "2026-05-02T00:00:00Z"),
    ("super_smash_hoez",  "2026-05-02T14:00:00Z"),
    ("steamer",           "2026-05-02T18:00:00Z"),
    ("stayed_down",       "2026-05-03T00:00:00Z"),
    ("time",              "2026-05-03T14:00:00Z"),
    ("rio",               "2026-05-03T18:00:00Z"),
    ("shake_ya_ass_ho3",  "2026-05-04T00:00:00Z"),
]

def upload_one(youtube, stem, publish_at, meta, mp4_path, thumb_path):
    body = {
        "snippet": {
            "title":       meta["title"],
            "description": meta.get("description", ""),
            "tags":        meta.get("tags", []),
            "categoryId":  "10",
        },
        "status": {
            "privacyStatus": "private",
            "publishAt":     publish_at,
            "selfDeclaredMadeForKids": False,
        },
    }

    from googleapiclient.http import MediaFileUpload
    media = MediaFileUpload(str(mp4_path), mimetype="video/mp4", resumable=True)
    req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

    resp = None
    while resp is None:
        status, resp = req.next_chunk()
        if status:
            pct = int(status.resumable_progress / status.total_size * 100)
            print(f"  [{stem}] uploading... {pct}%", end="\r")

    vid_id = resp["id"]
    print(f"  [{stem}] ✓ uploaded  https://youtu.be/{vid_id}")

    # Set thumbnail — don't let failure kill the whole upload
    if thumb_path and thumb_path.exists():
        try:
            youtube.thumbnails().set(videoId=vid_id, media_body=MediaFileUpload(str(thumb_path))).execute()
            print(f"  [{stem}] ✓ thumbnail set")
        except Exception as te:
            print(f"  [{stem}] ⚠ thumbnail failed (set it manually): {te}")

    return vid_id

def main():
    from youtube_auth import get_youtube_service
    youtube = get_youtube_service()

    log = json.loads(LOG_PATH.read_text())

    for stem, publish_at in BEATS:
        # Skip if already uploaded
        if stem in log and log[stem].get("videoId"):
            print(f"[SKIP] {stem} already uploaded: {log[stem]['videoId']}")
            continue

        mp4_path   = RENDERS_DIR / f"{stem}.mp4"
        thumb_path = THUMBS_DIR / f"{stem}_thumb.jpg"

        if not mp4_path.exists():
            print(f"[ERROR] No render for {stem} at {mp4_path}")
            continue

        meta_path = ROOT / "metadata" / f"{stem}.json"
        if not meta_path.exists():
            print(f"[ERROR] No metadata for {stem}")
            continue
        meta = json.loads(meta_path.read_text())

        print(f"\n[UPLOADING] {stem} → scheduled {publish_at}")

        try:
            vid_id = upload_one(youtube, stem, publish_at, meta, mp4_path, thumb_path)

            # Save to log immediately — even if thumbnail failed
            log = json.loads(LOG_PATH.read_text())  # re-read to avoid clobbering
            log[stem] = log.get(stem, {})
            log[stem].update({
                "videoId":    vid_id,
                "url":        f"https://youtu.be/{vid_id}",
                "uploadedAt": datetime.now(timezone.utc).isoformat(),
                "title":      meta["title"],
                "publishAt":  publish_at,
                "privacy":    "private",
            })
            LOG_PATH.write_text(json.dumps(log, indent=2))
            print(f"  [{stem}] ✓ log saved")

        except Exception as e:
            print(f"  [{stem}] ERROR: {e}")
            import traceback; traceback.print_exc()
            # If quota exceeded, stop — no point hammering
            if "quotaExceeded" in str(e):
                print("\n⛔ Quota exceeded — rerun after midnight Pacific time (quota resets daily)")
                break

        time.sleep(2)

    print("\n\nDone! Summary:")
    log = json.loads(LOG_PATH.read_text())
    for stem, _ in BEATS:
        vid = log.get(stem, {}).get("videoId", "MISSING")
        pub = log.get(stem, {}).get("publishAt", "")[:16]
        print(f"  {stem}: {vid}  {pub}")

if __name__ == "__main__":
    main()
