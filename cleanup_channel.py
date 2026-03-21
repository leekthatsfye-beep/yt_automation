#!/usr/bin/env python3
"""
One-time channel cleanup: delete duplicate/junk videos and fix schedule collisions.
Usage:
    python cleanup_channel.py --dry-run   # preview
    python cleanup_channel.py             # execute
"""

import argparse
import json
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
from youtube_auth import get_youtube_service

# ── Videos to DELETE ─────────────────────────────────────────────────────────

# 19 "Kooking A Chuckyy x BabyCheifdoit" spam
KOOKING_CHUCKYY = [
    "3O-A00Ycw8U", "RQTCTm_PKes", "w2JLJE0JxAc", "JxB59mWob3s",
    "5zefiRUNLLY", "eb7H2iVRHzE", "-9_mKddHnkM", "h7-WNT4rzLs",
    "lFJWiLg4Jec", "-dzTSKiYwbU", "TO_Z_6gBmR0", "RZ2J4PK-uQA",
    "sSA5CcLQQro", "WUS239ROawE", "QcmSZX-vyWI", "2BtEyUUvpjE",
    "C6bUDS3kSS0", "3po6CBJJw2M", "8EA0ZSCxNZI",
]

# 4 "kook up BLOODHOUNDQ50"
KOOKUP_BLOODHOUND = ["cbuxn23kMJw", "bMh2Fvp34aY", "GlIZZ2SjOQ8", "V7b1Wm1cW5I"]

# 13 "kook up!" generic
KOOKUP_GENERIC = [
    "-fk2UkotdLc", "2TJRUj4VHb8", "qUhgvr7y1P0", "qBCdDin9I6s",
    "aCHCN5LDGBM", "8SPDo90dRio", "ZhQnQja6XHM", "15NB2ZwXafY",
    "oKSsKfxbPxw", "Lk5FpWfqAuo", "YmAUMq4H200", "bBTZmNELe60",
    "m04-OzDxiUU",
]

# 1 "KOOK !"
KOOKUP_SINGLE = ["du5LzylvyhY"]

# Duplicate beat uploads
DUPLICATE_MASSACRE = ["OSS7WLbCaLM"]       # keep YyKDMEtVNIQ
DUPLICATE_SHORTS = ["QbjBEYLVaMg", "pAlTMkORhl4"]  # Adx Short, Bnb Short

# Old beat dupes — we'll determine which to delete dynamically
OLD_DUPE_GROUPS = {
    "MAKING SONGZ": ["LAPibHtW_7o", "VFtoCZb_oKc"],
    "Luh Tyler fat Rackz": [],   # filled dynamically
    "HotBoii WONT STOP": [],     # filled dynamically
    "Ola Runt BLATT": [],        # filled dynamically
}

# ── Schedule fix ─────────────────────────────────────────────────────────────

FAST_CAR_VIDEO_ID = "uT8eNyo3lu0"
FAST_CAR_NEW_PUBLISH = "2026-03-11T16:00:00Z"  # was 2026-03-07T16:00:00Z

UPLOADS_LOG = Path(__file__).resolve().parent / "uploads_log.json"


def p(msg):
    print(msg)


def resolve_old_dupes(yt):
    """Find old beat duplicates and pick which to delete (lower views)."""
    # Luh Tyler "fat Rackz"
    dupe_groups_to_check = {
        "Luh Tyler fat Rackz": "luh tyler.*fat rackz",
        "HotBoii WONT STOP": "hotboii.*wont stop",
        "Ola Runt BLATT": "ola runt.*blatt",
    }

    to_delete = []

    for label, pattern in dupe_groups_to_check.items():
        import re
        # Search channel for these
        results = yt.search().list(
            part="snippet", forMine=True, type="video",
            q=label, maxResults=10
        ).execute()

        video_ids = [r["id"]["videoId"] for r in results.get("items", [])]
        if len(video_ids) < 2:
            continue

        # Get view counts
        stats = yt.videos().list(
            part="statistics,snippet", id=",".join(video_ids)
        ).execute()

        matches = []
        for item in stats["items"]:
            title = item["snippet"]["title"].lower()
            if re.search(pattern, title, re.IGNORECASE):
                views = int(item["statistics"].get("viewCount", 0))
                matches.append((item["id"], views, item["snippet"]["title"]))

        if len(matches) >= 2:
            matches.sort(key=lambda x: x[1], reverse=True)
            # Delete all but the highest
            for vid_id, views, title in matches[1:]:
                to_delete.append((vid_id, f"{label} dupe ({views} views): {title}"))

    return to_delete


def main():
    parser = argparse.ArgumentParser(description="Clean up YouTube channel")
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview actions without executing")
    args = parser.parse_args()

    yt = get_youtube_service()

    # Build full delete list
    all_deletes = []

    for vid in KOOKING_CHUCKYY:
        all_deletes.append((vid, "Kooking Chuckyy spam"))
    for vid in KOOKUP_BLOODHOUND:
        all_deletes.append((vid, "Kook up BLOODHOUNDQ50"))
    for vid in KOOKUP_GENERIC:
        all_deletes.append((vid, "kook up! generic"))
    for vid in KOOKUP_SINGLE:
        all_deletes.append((vid, "KOOK !"))
    for vid in DUPLICATE_MASSACRE:
        all_deletes.append((vid, "Duplicate Massacre 147"))
    for vid in DUPLICATE_SHORTS:
        all_deletes.append((vid, "Duplicate Short"))

    # MAKING SONGZ — delete lower views
    try:
        ms_stats = yt.videos().list(
            part="statistics", id=",".join(OLD_DUPE_GROUPS["MAKING SONGZ"])
        ).execute()
        ms_items = [(i["id"], int(i["statistics"].get("viewCount", 0)))
                     for i in ms_stats["items"]]
        ms_items.sort(key=lambda x: x[1], reverse=True)
        for vid_id, views in ms_items[1:]:
            all_deletes.append((vid_id, f"MAKING SONGZ dupe ({views} views)"))
    except Exception as e:
        p(f"⚠️ Could not resolve MAKING SONGZ dupes: {e}")

    # Old beat dupes
    try:
        old_dupes = resolve_old_dupes(yt)
        all_deletes.extend(old_dupes)
    except Exception as e:
        p(f"⚠️ Could not resolve old beat dupes: {e}")

    # ── Summary ──────────────────────────────────────────────────────────
    mode = "DRY RUN" if args.dry_run else "EXECUTING"
    p(f"\n{'='*60}")
    p(f"  YouTube Channel Cleanup — {mode}")
    p(f"{'='*60}\n")

    p(f"Videos to DELETE: {len(all_deletes)}")
    for vid, reason in all_deletes:
        p(f"  🗑  {vid} — {reason}")

    p(f"\nSchedule fix:")
    p(f"  📅 Fast Car ({FAST_CAR_VIDEO_ID}): → {FAST_CAR_NEW_PUBLISH}")

    if args.dry_run:
        p(f"\n{'='*60}")
        p(f"  DRY RUN — no changes made")
        p(f"  Run without --dry-run to execute")
        p(f"{'='*60}")
        return

    # ── Execute deletions ────────────────────────────────────────────────
    deleted = 0
    failed = 0

    for vid, reason in all_deletes:
        try:
            yt.videos().delete(id=vid).execute()
            p(f"  ✅ Deleted {vid} — {reason}")
            deleted += 1
        except Exception as e:
            err = str(e)
            if "videoNotFound" in err or "404" in err:
                p(f"  ⚠️ Already gone: {vid} — {reason}")
                deleted += 1  # count as success
            else:
                p(f"  ❌ Failed {vid}: {e}")
                failed += 1

    # ── Reschedule Fast Car ──────────────────────────────────────────────
    try:
        yt.videos().update(
            part="status",
            body={
                "id": FAST_CAR_VIDEO_ID,
                "status": {
                    "privacyStatus": "private",
                    "publishAt": FAST_CAR_NEW_PUBLISH,
                }
            }
        ).execute()
        p(f"\n  ✅ Fast Car rescheduled to {FAST_CAR_NEW_PUBLISH}")

        # Update uploads_log.json
        if UPLOADS_LOG.exists():
            with open(UPLOADS_LOG) as f:
                log = json.load(f)
            if "fast_car" in log:
                log["fast_car"]["publishAt"] = "2026-03-11T11:00:00-05:00"
                with open(UPLOADS_LOG, "w") as f:
                    json.dump(log, f, indent=2)
                p(f"  ✅ uploads_log.json updated")
    except Exception as e:
        p(f"  ❌ Failed to reschedule Fast Car: {e}")

    # ── Summary ──────────────────────────────────────────────────────────
    p(f"\n{'='*60}")
    p(f"  Cleanup complete: {deleted} deleted, {failed} failed")
    p(f"  Fast Car rescheduled to March 11")
    p(f"{'='*60}")


if __name__ == "__main__":
    main()
