"""
audit_playlists.py — verify every ØWAY playlist against uploads_log.json.

Checks per playlist:
  DUPES    same video appearing more than once (make_playlists.py used to
           re-add the whole catalog every night — see commit 3c68937)
  MISSING  a beat that belongs in this playlist but isn't in it
  STRAY    an entry whose title doesn't match the playlist's artist
  DEAD     an entry whose video is deleted/private

Read-only by default (playlistItems.list = 1 unit per 50 items).
  --fix        remove duplicate entries (50 units each) + add missing (50 each)
  --fix-dupes  duplicates only
  --fix-missing add missing only
  --max-ops N  hard cap on write calls so a run can't drain the daily quota

Usage:
  python scripts/audit_playlists.py
  python scripts/audit_playlists.py --fix --max-ops 40
"""

import argparse
import json
import sys
from collections import defaultdict
from pathlib import Path

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from googleapiclient.errors import HttpError          # noqa: E402

from make_playlists import (                          # noqa: E402
    PLAYLIST_DEFS,
    get_artists_for_video,
    load_videos,
)

PLAYLISTS_LOG = ROOT / "playlists_log.json"
UNIT_COST_WRITE = 50


def fetch_items(youtube, playlist_id: str) -> list[dict]:
    """Every entry with its playlistItem id (needed to delete a specific copy)."""
    items, token = [], None
    while True:
        resp = youtube.playlistItems().list(
            part="snippet,contentDetails,status",
            playlistId=playlist_id, maxResults=50, pageToken=token,
        ).execute()
        for it in resp.get("items", []):
            items.append({
                "item_id": it["id"],
                "video_id": it.get("contentDetails", {}).get("videoId", ""),
                "title": it.get("snippet", {}).get("title", ""),
                "privacy": it.get("status", {}).get("privacyStatus", ""),
                "position": it.get("snippet", {}).get("position", -1),
            })
        token = resp.get("nextPageToken")
        if not token:
            return items


def audit(youtube, key: str, pid: str, expected: list[dict]) -> dict:
    items = fetch_items(youtube, pid)
    expected_ids = {v["id"] for v in expected}
    titles = {v["id"]: v["title"] for v in expected}

    by_video = defaultdict(list)
    for it in items:
        by_video[it["video_id"]].append(it)

    # keep the earliest copy of each video, flag the rest
    dupes = []
    for vid, copies in by_video.items():
        if len(copies) > 1:
            copies.sort(key=lambda c: c["position"])
            dupes.extend(copies[1:])

    missing = [v for v in expected if v["id"] not in by_video]
    dead = [it for it in items
            if it["title"] in ("Deleted video", "Private video")
            or it["privacy"] == "private"]
    stray = []
    if key != "OWAY":
        for vid, copies in by_video.items():
            if vid in expected_ids:
                continue
            t = copies[0]["title"]
            if t in ("Deleted video", "Private video"):
                continue
            stray.append(copies[0])

    return {
        "key": key, "pid": pid, "items": items, "unique": len(by_video),
        "expected": len(expected_ids), "dupes": dupes, "missing": missing,
        "dead": dead, "stray": stray, "titles": titles,
    }


def main() -> None:
    ap = argparse.ArgumentParser()
    ap.add_argument("--fix", action="store_true", help="remove dupes and add missing")
    ap.add_argument("--fix-dupes", action="store_true")
    ap.add_argument("--fix-missing", action="store_true")
    ap.add_argument("--max-ops", type=int, default=60,
                    help="max write calls this run (50 units each)")
    args = ap.parse_args()
    do_dupes = args.fix or args.fix_dupes
    do_missing = args.fix or args.fix_missing

    from youtube_auth import get_youtube_service_with_fallback
    youtube = get_youtube_service_with_fallback()

    log = json.loads(PLAYLISTS_LOG.read_text())
    videos = load_videos()

    reports, ops = [], 0
    for key, entry in log.items():
        pid = entry.get("playlist_id")
        if not pid:
            continue
        expected = [v for v in videos if key == "OWAY" or key in v["artists"]]
        try:
            rep = audit(youtube, key, pid, expected)
        except HttpError as e:
            print(f"  [{key}] read failed: {str(e)[:80]}")
            continue
        reports.append(rep)

        title = PLAYLIST_DEFS.get(key, key)
        flag = "OK" if not (rep["dupes"] or rep["missing"] or rep["stray"] or rep["dead"]) else "ISSUES"
        print(f"\n  [{key}] {title}")
        print(f"      {len(rep['items'])} entries / {rep['unique']} unique "
              f"/ {rep['expected']} expected   → {flag}")
        if rep["dupes"]:
            worst = defaultdict(int)
            for d in rep["dupes"]:
                worst[d["title"][:50]] += 1
            print(f"      DUPES   {len(rep['dupes'])} extra copies "
                  f"({len(worst)} videos affected)")
            for t, n in sorted(worst.items(), key=lambda kv: -kv[1])[:3]:
                print(f"                x{n + 1}  {t}")
        if rep["missing"]:
            print(f"      MISSING {len(rep['missing'])}")
            for v in rep["missing"][:5]:
                print(f"                {v['title'][:60]}")
        if rep["stray"]:
            print(f"      STRAY   {len(rep['stray'])}")
            for s in rep["stray"][:5]:
                print(f"                {s['title'][:60]}")
        if rep["dead"]:
            print(f"      DEAD    {len(rep['dead'])} deleted/private entries")

    total_dupes = sum(len(r["dupes"]) for r in reports)
    total_missing = sum(len(r["missing"]) for r in reports)
    print(f"\n  {'─' * 60}")
    print(f"  TOTAL: {total_dupes} duplicate entries, {total_missing} missing.")
    if not (do_dupes or do_missing):
        cost = (total_dupes + total_missing) * UNIT_COST_WRITE
        print(f"  Cleanup would cost ~{cost:,} quota units "
              f"({total_dupes + total_missing} write calls).")
        print("  Re-run with --fix (add --max-ops N to spread across days).")
        return

    print(f"\n  Fixing (cap {args.max_ops} write calls)...")
    for rep in reports:
        if do_dupes:
            for d in rep["dupes"]:
                if ops >= args.max_ops:
                    print(f"  [CAP] reached {args.max_ops} ops — stopping.")
                    return
                try:
                    youtube.playlistItems().delete(id=d["item_id"]).execute()
                    ops += 1
                    print(f"      [DEL] {rep['key']}: {d['title'][:50]}")
                except HttpError as e:
                    if "quotaExceeded" in str(e):
                        print(f"  [QUOTA] exhausted after {ops} ops — resume tomorrow.")
                        return
                    print(f"      [WARN] {str(e)[:70]}")
        if do_missing:
            for v in rep["missing"]:
                if ops >= args.max_ops:
                    print(f"  [CAP] reached {args.max_ops} ops — stopping.")
                    return
                try:
                    youtube.playlistItems().insert(
                        part="snippet",
                        body={"snippet": {
                            "playlistId": rep["pid"],
                            "resourceId": {"kind": "youtube#video", "videoId": v["id"]},
                        }},
                    ).execute()
                    ops += 1
                    print(f"      [ADD] {rep['key']}: {v['title'][:50]}")
                except HttpError as e:
                    if "quotaExceeded" in str(e):
                        print(f"  [QUOTA] exhausted after {ops} ops — resume tomorrow.")
                        return
                    print(f"      [WARN] {str(e)[:70]}")
    print(f"\n  Done — {ops} write calls (~{ops * UNIT_COST_WRITE:,} units).")


if __name__ == "__main__":
    main()
