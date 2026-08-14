"""
make_playlists.py — create & populate artist playlists on LEEKTHATSFY3 channel

Playlists created:
  - Tezzus Type Beats
  - Diamond Type Beats
  - ShawtyRokk Type Beats
  - Pz Type Beats          (only if >0 beats)
  - ØWAY Type Beats        (all beats — every artist is ØWAY)

Usage:
  python make_playlists.py           # create + populate
  python make_playlists.py --dry-run # preview only, no API calls
"""

import argparse
import json
import re
import sys
from pathlib import Path

from googleapiclient.errors import HttpError

ROOT        = Path(__file__).resolve().parent
UPLOADS_LOG = ROOT / "uploads_log.json"
PLAYLISTS_LOG = ROOT / "playlists_log.json"

# Artist detection: order matters (most specific first)
ARTIST_PATTERNS = [
    ("ShawtyRokk", re.compile(r"shawtyrokk|shawtyyrokk", re.I)),
    ("Diamond",    re.compile(r"diamond", re.I)),
    ("Tezzus",     re.compile(r"tezzus", re.I)),
    ("Pz",         re.compile(r"\bpz\b", re.I)),
    ("Young Thug", re.compile(r"young thug", re.I)),
]

# All ØWAY-lane artists — every beat on this channel qualifies
OWAY_ARTISTS = {"Diamond", "Tezzus", "ShawtyRokk", "Pz"}

PLAYLIST_DEFS = {
    "Tezzus":     "Tezzus Type Beats | leekthatsfye",
    "Diamond":    "Diamond Type Beats | leekthatsfye",
    "ShawtyRokk": "ShawtyRokk Type Beats | leekthatsfye",
    "Pz":         "Pz Type Beats | leekthatsfye",
    "OWAY":       "ØWAY Type Beats | leekthatsfye",
}

PLAYLIST_DESCRIPTIONS = {
    "Tezzus":     "Free Tezzus type beats produced by leekthatsfye. ØWAY.",
    "Diamond":    "Free Diamond type beats produced by leekthatsfye. ØWAY.",
    "ShawtyRokk": "Free ShawtyRokk type beats produced by leekthatsfye. ØWAY.",
    "Pz":         "Free Pz type beats produced by leekthatsfye. ØWAY.",
    "OWAY":       "Free ØWAY type beats produced by leekthatsfye. Diamond, Tezzus, ShawtyRokk and the whole crew.",
}


def get_artists_for_video(title: str) -> set:
    found = set()
    for name, pattern in ARTIST_PATTERNS:
        if pattern.search(title):
            found.add(name)
    return found


def load_videos() -> list[dict]:
    log = json.loads(UPLOADS_LOG.read_text())
    videos = []
    for stem, data in log.items():
        vid_id = data.get("videoId") or data.get("video_id") or data.get("id")
        title  = data.get("title", "")
        if vid_id and title:
            artists = get_artists_for_video(title)
            videos.append({"stem": stem, "id": vid_id, "title": title, "artists": artists})
    return videos


def load_playlists_log() -> dict:
    if PLAYLISTS_LOG.exists():
        return json.loads(PLAYLISTS_LOG.read_text())
    return {}


def save_playlists_log(data: dict):
    PLAYLISTS_LOG.write_text(json.dumps(data, indent=2))


def get_or_create_playlist(youtube, key: str, title: str, description: str,
                            existing: dict, dry_run: bool) -> str | None:
    if key in existing:
        pid = existing[key]["playlist_id"]
        print(f"  [EXIST] {title}  →  {pid}")
        return pid

    if dry_run:
        print(f"  [DRY]   would create: {title}")
        return f"DRY_{key}"

    resp = youtube.playlists().insert(
        part="snippet,status",
        body={
            "snippet": {
                "title": title,
                "description": description,
                "defaultLanguage": "en",
            },
            "status": {"privacyStatus": "public"},
        },
    ).execute()
    pid = resp["id"]
    print(f"  [NEW]   {title}  →  {pid}")
    return pid


def fetch_playlist_video_ids(youtube, playlist_id: str) -> set:
    """Read what's ACTUALLY in the playlist. 1 quota unit per 50 items.

    Authoritative: the local log drifts (and used to get wiped), and each blind
    playlistItems.insert costs 50 units, so reconciling first is ~50x cheaper
    than re-adding a video that is already there.
    """
    ids, token = set(), None
    while True:
        resp = youtube.playlistItems().list(
            part="contentDetails", playlistId=playlist_id,
            maxResults=50, pageToken=token,
        ).execute()
        for item in resp.get("items", []):
            vid = item.get("contentDetails", {}).get("videoId")
            if vid:
                ids.add(vid)
        token = resp.get("nextPageToken")
        if not token:
            return ids


def add_to_playlist(youtube, playlist_id: str, video_id: str,
                    video_title: str, dry_run: bool):
    if dry_run:
        print(f"      [DRY] add  {video_title[:60]}")
        return
    youtube.playlistItems().insert(
        part="snippet",
        body={
            "snippet": {
                "playlistId": playlist_id,
                "resourceId": {"kind": "youtube#video", "videoId": video_id},
            }
        },
    ).execute()
    print(f"      [ADD] {video_title[:60]}")


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true")
    args = parser.parse_args()

    youtube = None
    if not args.dry_run:
        from youtube_auth import get_youtube_service_with_fallback
        youtube = get_youtube_service_with_fallback()

    videos = load_videos()
    existing = load_playlists_log()

    # Figure out which artist keys actually have beats
    artist_video_map: dict[str, list] = {k: [] for k in PLAYLIST_DEFS}
    for v in videos:
        for artist in v["artists"]:
            if artist in artist_video_map:
                artist_video_map[artist].append(v)
        # ØWAY = all beats
        artist_video_map["OWAY"].append(v)

    # Remove artist playlists with 0 beats
    keys_to_create = [k for k, vids in artist_video_map.items() if vids]

    print(f"\n{'='*55}")
    print(f"  Creating {len(keys_to_create)} playlists")
    print(f"{'='*55}")

    playlist_ids: dict[str, str] = {}
    for key in keys_to_create:
        pid = get_or_create_playlist(
            youtube, key,
            PLAYLIST_DEFS[key], PLAYLIST_DESCRIPTIONS[key],
            existing, args.dry_run,
        )
        playlist_ids[key] = pid
        if not args.dry_run:
            # setdefault+update, NOT assignment — a plain assignment here wiped
            # added_video_ids before the populate loop could read it, so every
            # run re-added the entire catalog at 50 quota units per video.
            entry = existing.setdefault(key, {})
            entry["playlist_id"] = pid
            entry["title"] = PLAYLIST_DEFS[key]

    print(f"\n{'='*55}")
    print(f"  Populating playlists")
    print(f"{'='*55}")

    added_total = 0
    for key, vids in artist_video_map.items():
        if not vids or key not in playlist_ids:
            continue
        pid = playlist_ids[key]
        already_added = set(existing.get(key, {}).get("added_video_ids", []))
        if not args.dry_run:
            # Reconcile against the live playlist (cheap) instead of trusting
            # the local log — self-heals drift and never double-adds.
            try:
                live = fetch_playlist_video_ids(youtube, pid)
                already_added |= live
            except HttpError as e:
                if "quotaExceeded" in str(e):
                    print(f"\n  [QUOTA] exhausted while reading {key} — stopping here.")
                    save_playlists_log(existing)
                    break
                raise

        print(f"\n  [{key}]  {len(vids)} beats  →  playlist {pid}")
        newly_added, skipped = [], 0
        quota_hit = False
        for v in vids:
            if v["id"] in already_added:
                skipped += 1
                continue
            try:
                add_to_playlist(youtube, pid, v["id"], v["title"], args.dry_run)
            except HttpError as e:
                if "quotaExceeded" in str(e):
                    print(f"      [QUOTA] exhausted — {len(newly_added)} added, stopping.")
                    quota_hit = True
                    break
                raise
            newly_added.append(v["id"])

        if skipped:
            print(f"      [SKIP] {skipped} already in playlist")
        added_total += len(newly_added)

        if not args.dry_run:
            # Save after EVERY playlist so a quota abort keeps its progress.
            existing.setdefault(key, {})["added_video_ids"] = sorted(
                already_added | set(newly_added)
            )
            save_playlists_log(existing)
        if quota_hit:
            break

    if not args.dry_run:
        save_playlists_log(existing)
        print(f"\n  Added {added_total} new playlist entries "
              f"(~{added_total * 50 + len(keys_to_create)} quota units).")

    print(f"\n{'='*55}")
    print("  Done.")
    for key, pid in playlist_ids.items():
        count = len(artist_video_map.get(key, []))
        print(f"  {PLAYLIST_DEFS[key]:<45} {count} beats")
    print(f"{'='*55}\n")


if __name__ == "__main__":
    main()
