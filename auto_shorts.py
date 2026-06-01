"""
auto_shorts.py — Render 9:16 + upload YouTube Short for every upcoming scheduled beat.

Short drops 1 hour after its beat. Skips beats that already have a Short uploaded.
Run: python auto_shorts.py [--dry-run] [--limit N]
"""
import argparse
import json
import sys
from datetime import datetime, timedelta, timezone
from pathlib import Path

try:
    from zoneinfo import ZoneInfo
    EST = ZoneInfo("America/New_York")
except ImportError:
    EST = timezone(timedelta(hours=-5))

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from social_upload import convert_to_portrait, youtube_shorts_upload, load_social_log

UPLOADS_LOG = ROOT / "uploads_log.json"
OUT_DIR     = ROOT / "output"
SHORT_DELAY = timedelta(hours=1)  # short drops 1h after beat

def main():
    ap = argparse.ArgumentParser()
    ap.add_argument("--dry-run", action="store_true")
    ap.add_argument("--limit", type=int, default=0, help="Max shorts to upload (0=all)")
    args = ap.parse_args()

    uploads = json.loads(UPLOADS_LOG.read_text())
    social  = load_social_log()
    now     = datetime.now(EST)

    # Build list of upcoming beats sorted by publish time
    upcoming = []
    for stem, info in uploads.items():
        pa = info.get("publishAt")
        if not pa:
            continue
        try:
            dt = datetime.fromisoformat(pa).astimezone(EST)
            if dt <= now:
                continue  # already live, skip
        except (ValueError, TypeError):
            continue

        # Skip if Short already uploaded
        if social.get(stem, {}).get("youtube_shorts", {}).get("status") == "ok":
            print(f"[SKIP] {stem} — Short already on YouTube")
            continue

        # Skip if 9x16 source video doesn't exist and beat video doesn't exist either
        if not (OUT_DIR / f"{stem}.mp4").exists():
            print(f"[SKIP] {stem} — no rendered video")
            continue

        short_time = dt + SHORT_DELAY
        upcoming.append((dt, short_time, stem, info.get("title", stem)))

    upcoming.sort(key=lambda x: x[0])

    if not upcoming:
        print("Nothing to do — all upcoming beats already have Shorts.")
        return

    print(f"Found {len(upcoming)} beats needing Shorts.")
    if args.limit:
        upcoming = upcoming[:args.limit]
        print(f"Processing first {args.limit}.")

    print()

    done = 0
    for beat_dt, short_dt, stem, title in upcoming:
        beat_str  = beat_dt.strftime("%a %m/%d %I:%M%p")
        short_str = short_dt.strftime("%a %m/%d %I:%M%p")
        print(f"{'[DRY]' if args.dry_run else '[GO] '} {stem}")
        print(f"       Beat:  {beat_str}")
        print(f"       Short: {short_str} EST")

        if args.dry_run:
            print()
            continue

        # Step 1 — render 9x16
        nine_path = OUT_DIR / f"{stem}_9x16.mp4"
        if nine_path.exists():
            print(f"       9x16 already exists, skipping render")
        else:
            print(f"       Rendering 9x16...")
            try:
                convert_to_portrait(stem)
                print(f"       ✓ Rendered")
            except Exception as e:
                print(f"       ✗ Render failed: {e}")
                print()
                continue

        # Step 2 — upload as scheduled Short
        print(f"       Uploading Short scheduled for {short_str}...")
        progress = {}
        try:
            result = youtube_shorts_upload(stem, publish_at=short_dt, progress=progress)
            if result.get("status") == "ok":
                print(f"       ✓ Uploaded: {result.get('url')}")
                done += 1
            else:
                print(f"       ✗ Upload failed: {result.get('error')}")
        except Exception as e:
            print(f"       ✗ Exception: {e}")
        print()

    print(f"Done. {done}/{len(upcoming)} Shorts uploaded.")

if __name__ == "__main__":
    main()
