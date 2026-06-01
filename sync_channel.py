"""
sync_channel.py — Syncs uploads_log.json with live YouTube channel data.

Run this before any upload or scheduling decision to ensure the log
reflects reality. Updates publishAt, privacy status, and view counts.

Usage:
    python sync_channel.py              # sync and show summary
    python sync_channel.py --scheduled  # show only scheduled videos
    python sync_channel.py --last       # show last scheduled slot
"""
from __future__ import annotations

import argparse
import json
from datetime import datetime, timezone
from pathlib import Path

ROOT      = Path(__file__).resolve().parent
LOG_PATH  = ROOT / "uploads_log.json"


def sync(verbose: bool = True) -> dict:
    from youtube_auth import get_youtube_service

    youtube = get_youtube_service()

    # ── Pull all channel videos ───────────────────────────────────────
    channels = youtube.channels().list(part="contentDetails,statistics", mine=True).execute()
    uploads_id = channels["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    items = []
    next_page = None
    while True:
        resp = youtube.playlistItems().list(
            part="snippet", playlistId=uploads_id,
            maxResults=50, pageToken=next_page
        ).execute()
        items.extend(resp["items"])
        next_page = resp.get("nextPageToken")
        if not next_page:
            break

    if verbose:
        print(f"[SYNC] Found {len(items)} videos on channel")

    # ── Get status + stats for all videos ────────────────────────────
    ids = [v["snippet"]["resourceId"]["videoId"] for v in items]
    yt_data: dict[str, dict] = {}

    for i in range(0, len(ids), 50):
        batch = ids[i:i+50]
        resp = youtube.videos().list(
            part="snippet,status,statistics", id=",".join(batch)
        ).execute()
        for item in resp["items"]:
            vid_id = item["id"]
            yt_data[vid_id] = {
                "title":       item["snippet"]["title"],
                "publishedAt": item["snippet"]["publishedAt"],
                "privacy":     item["status"]["privacyStatus"],
                "publishAt":   item["status"].get("publishAt", ""),
                "views":       int(item["statistics"].get("viewCount", 0)),
                "likes":       int(item["statistics"].get("likeCount", 0)),
            }

    # ── Load local log ────────────────────────────────────────────────
    log = json.loads(LOG_PATH.read_text()) if LOG_PATH.exists() else {}

    # ── Build reverse map: videoId → stem ────────────────────────────
    vid_to_stem = {d.get("videoId", ""): stem for stem, d in log.items() if d.get("videoId")}

    # ── Update log entries from YouTube truth ─────────────────────────
    # NOTE: YouTube Data API has a known limitation where scheduled/private
    # videos don't always return their publishAt via the API even though
    # YouTube Studio shows them correctly. We trust the API for:
    #   - confirmed publishAt (API returned it = definitely scheduled)
    #   - privacy = public (definitely live)
    # We DO NOT clear publishAt from our log if the API returns empty —
    # that could just be the API hiding it, not the video being unscheduled.
    updated = 0
    for vid_id, yt in yt_data.items():
        stem = vid_to_stem.get(vid_id)
        if not stem:
            continue  # not in our log — old content, skip

        entry = log[stem]

        # Only update publishAt if API actually returned one (trust API positives only)
        if yt["publishAt"]:
            if entry.get("publishAt") != yt["publishAt"]:
                entry["publishAt"] = yt["publishAt"]
                updated += 1

        # If video is confirmed public, remove publishAt (it's live)
        if yt["privacy"] == "public" and "publishAt" in entry:
            del entry["publishAt"]
            updated += 1

        # Always sync these
        entry["title"]   = yt["title"]
        entry["privacy"] = yt["privacy"]
        entry["views"]   = yt["views"]
        entry["likes"]   = yt["likes"]

    # ── Save updated log ──────────────────────────────────────────────
    LOG_PATH.write_text(json.dumps(log, indent=2))

    if verbose:
        print(f"[SYNC] Updated {updated} entries")

    # ── Build schedule summary ────────────────────────────────────────
    scheduled = []
    for stem, d in log.items():
        if d.get("publishAt"):
            scheduled.append((d["publishAt"], stem, d.get("title", ""), d.get("videoId", "")))
    scheduled.sort()

    live = [(d.get("publishedAt",""), stem, d.get("title",""), d.get("views",0))
            for stem, d in log.items()
            if d.get("privacy") == "public"]
    live.sort(reverse=True)

    return {
        "scheduled": scheduled,
        "live":      live,
        "log":       log,
        "last_slot": scheduled[-1][0] if scheduled else None,
    }


def main():
    parser = argparse.ArgumentParser(description="Sync uploads_log.json with YouTube")
    parser.add_argument("--scheduled", action="store_true", help="Show scheduled videos only")
    parser.add_argument("--last",      action="store_true", help="Show last scheduled slot only")
    args = parser.parse_args()

    result = sync(verbose=True)
    scheduled = result["scheduled"]
    live      = result["live"]

    if args.last:
        if scheduled:
            pub, stem, title, vid = scheduled[-1]
            print(f"\nLast scheduled slot: {pub[:16]}  {title}")
        else:
            print("\nNothing scheduled.")
        return

    if args.scheduled or not args.last:
        print(f"\n{'─'*60}")
        print(f"  SCHEDULED ({len(scheduled)} videos)")
        print(f"{'─'*60}")
        for pub, stem, title, vid in scheduled:
            print(f"  {pub[:16]}  {title[:52]}")

        print(f"\n{'─'*60}")
        print(f"  LAST 5 LIVE")
        print(f"{'─'*60}")
        for pub, stem, title, views in live[:5]:
            print(f"  {pub[:10]}  {views:>6} views  {title[:45]}")

        print(f"\n  ✓ Next open slot: after {scheduled[-1][0][:16] if scheduled else 'now'}")


if __name__ == "__main__":
    main()
