"""
unlist_non_beat_shorts.py

Batch-unlist non-beat YouTube Shorts identified in non_beat_shorts.json.

Each videos.update(part="status") costs 50 quota units.
YouTube daily quota = 10,000 units → max ~200 updates per day.

Usage:
    python unlist_non_beat_shorts.py              # unlist all (up to 195/run for safety)
    python unlist_non_beat_shorts.py --dry-run    # preview only
    python unlist_non_beat_shorts.py --limit 50   # first 50 only
"""

from __future__ import annotations

import json
import sys
import time
import argparse
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

from youtube_auth import get_youtube_service


def main():
    ap = argparse.ArgumentParser(description="Unlist non-beat YouTube Shorts")
    ap.add_argument("--dry-run", action="store_true", help="Preview without making changes")
    ap.add_argument("--limit", type=int, default=195,
                    help="Max videos to unlist per run (default 195, keeps under 10K quota)")
    ap.add_argument("--delay", type=float, default=1.0,
                    help="Seconds between API calls (default 1.0)")
    args = ap.parse_args()

    # Load the list
    shorts_file = ROOT / "non_beat_shorts.json"
    if not shorts_file.exists():
        print("ERROR: non_beat_shorts.json not found")
        sys.exit(1)

    shorts = json.loads(shorts_file.read_text())
    print(f"\nFound {len(shorts)} non-beat shorts to unlist")

    # Load progress log (skip already-unlisted)
    progress_file = ROOT / "unlist_progress.json"
    already_done = set()
    if progress_file.exists():
        progress = json.loads(progress_file.read_text())
        already_done = set(progress.get("unlisted", []))
        print(f"Already unlisted: {len(already_done)} (skipping)")

    # Filter to remaining
    remaining = [s for s in shorts if s["video_id"] not in already_done]
    to_process = remaining[:args.limit]

    print(f"Will unlist: {len(to_process)} videos this run")
    if args.dry_run:
        print("\n=== DRY RUN — no changes will be made ===\n")
        for i, s in enumerate(to_process, 1):
            print(f"  {i:3d}. [{s['video_id']}] {s['title'][:60]}  ({s['views']} views)")
        print(f"\n--- {len(to_process)} videos would be unlisted ---")
        return

    # Authenticate
    print("\nAuthenticating with YouTube API...")
    youtube = get_youtube_service()
    print("Authenticated ✓\n")

    unlisted_ids = list(already_done)
    failed = []
    quota_hit = False

    for i, s in enumerate(to_process, 1):
        vid = s["video_id"]
        title = s["title"][:55]

        try:
            body = {
                "id": vid,
                "status": {
                    "privacyStatus": "unlisted",
                },
            }
            youtube.videos().update(part="status", body=body).execute()

            unlisted_ids.append(vid)
            print(f"  [{i}/{len(to_process)}] ✓ Unlisted: {title}")

            # Save progress after each successful update
            progress_file.write_text(json.dumps({
                "unlisted": unlisted_ids,
                "failed": failed,
                "last_run": datetime.now(timezone.utc).isoformat(),
                "total_unlisted": len(unlisted_ids),
            }, indent=2))

            if i < len(to_process):
                time.sleep(args.delay)

        except Exception as e:
            err_str = str(e).lower()
            if "quotaexceeded" in err_str or ("403" in err_str and "quota" in err_str):
                print(f"\n  ⚠ QUOTA EXCEEDED after {i-1} updates. Remaining will resume next run.")
                quota_hit = True
                break
            else:
                print(f"  [{i}/{len(to_process)}] ✗ FAILED: {title} — {str(e)[:100]}")
                failed.append({"video_id": vid, "error": str(e)[:200]})
                time.sleep(args.delay)

    # Final save
    progress_file.write_text(json.dumps({
        "unlisted": unlisted_ids,
        "failed": failed,
        "last_run": datetime.now(timezone.utc).isoformat(),
        "total_unlisted": len(unlisted_ids),
        "quota_hit": quota_hit,
    }, indent=2))

    print(f"\n{'=' * 50}")
    print(f"  Unlisted this run:  {len(unlisted_ids) - len(already_done)}")
    print(f"  Total unlisted:     {len(unlisted_ids)}")
    print(f"  Failed:             {len(failed)}")
    print(f"  Remaining:          {len(remaining) - len(to_process) + len(failed)}")
    if quota_hit:
        print(f"  ⚠ Quota hit — run again tomorrow for remaining")
    print(f"{'=' * 50}\n")


if __name__ == "__main__":
    main()
