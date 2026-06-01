"""
update_shorts_descriptions.py

Bulk-updates the description (and tags) of all existing YouTube Shorts in
social_uploads_log.json to include:
  - Purchase / download link (per-beat Airbit URL or store profile URL)
  - Link to the full long-form YouTube video (from uploads_log.json)
  - #Shorts #TypeBeat hashtags

Usage:
    python update_shorts_descriptions.py            # update all 57 shorts
    python update_shorts_descriptions.py --dry-run  # preview without touching YouTube
    python update_shorts_descriptions.py --stem adx # update a single short
"""
from __future__ import annotations

import argparse
import json
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent

SOCIAL_LOG   = ROOT / "social_uploads_log.json"
UPLOADS_LOG  = ROOT / "uploads_log.json"
STORE_LOG    = ROOT / "store_uploads_log.json"
LANES_CFG    = ROOT / "lanes_config.json"
META_DIR     = ROOT / "metadata"


# ── helpers (mirrors social_upload.py logic) ──────────────────────────────────

def _build_purchase_desc(stem: str) -> str:
    store_data = {}
    try:
        if STORE_LOG.exists():
            store_data = json.loads(STORE_LOG.read_text())
    except Exception:
        pass
    lanes_cfg = {}
    try:
        if LANES_CFG.exists():
            lanes_cfg = json.loads(LANES_CFG.read_text())
    except Exception:
        pass
    store_profile = lanes_cfg.get("store_profile_url", "")
    producer = lanes_cfg.get("producer", "leekthatsfy3")

    entry = store_data.get(stem, {})
    airbit_entry = entry.get("airbit", entry) if isinstance(entry, dict) else {}
    beat_url = airbit_entry.get("url", "")

    if beat_url and beat_url != store_profile:
        purchase_link = beat_url
        if store_profile:
            purchase_link += f"\n\nBrowse all beats:\n{store_profile}"
    elif store_profile:
        purchase_link = store_profile
    else:
        purchase_link = "[Link in bio]"

    return f"Purchase / Download\n{purchase_link}\n\nprod. {producer}"


def _build_description(stem: str, uploads_data: dict) -> str:
    purchase_desc = _build_purchase_desc(stem)
    full_video_url = uploads_data.get(stem, {}).get("url", "")
    full_video_line = f"\n\n🎵 Full video:\n{full_video_url}" if full_video_url else ""
    return f"{purchase_desc}{full_video_line}\n\n#Shorts #TypeBeat".strip()[:5000]


def _get_tags(stem: str) -> list[str]:
    meta_path = META_DIR / f"{stem}.json"
    try:
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            tags = meta.get("tags", []) or []
            return [t.replace("<", "").replace(">", "").strip()[:30]
                    for t in tags if t and len(t.strip()) > 0]
    except Exception:
        pass
    return []


def _get_title(stem: str) -> str | None:
    """Return the existing Short's title (we keep it unchanged)."""
    meta_path = META_DIR / f"{stem}.json"
    try:
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            raw = meta.get("title") or stem.replace("_", " ").title()
            return f"{raw} #Shorts".replace("<", "").replace(">", "").strip()[:100]
    except Exception:
        pass
    return None


# ── main ─────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Bulk-update YouTube Shorts descriptions")
    parser.add_argument("--dry-run", action="store_true", help="Preview only, no API calls")
    parser.add_argument("--stem", help="Update a single stem only")
    args = parser.parse_args()

    # Load logs
    social_log = {}
    if SOCIAL_LOG.exists():
        social_log = json.loads(SOCIAL_LOG.read_text())

    uploads_data = {}
    if UPLOADS_LOG.exists():
        uploads_data = json.loads(UPLOADS_LOG.read_text())

    # Build list of (stem, videoId) to update
    targets: list[tuple[str, str]] = []
    for stem, platforms in social_log.items():
        if args.stem and stem != args.stem:
            continue
        ys = platforms.get("youtube_shorts")
        if not ys:
            continue
        vid = ys.get("videoId")
        if not vid:
            continue
        targets.append((stem, vid))

    if not targets:
        print("No YouTube Shorts found to update.")
        sys.exit(0)

    print(f"Found {len(targets)} YouTube Shorts to update")
    if args.dry_run:
        print("--- DRY RUN (no API calls) ---")

    # Auth
    if not args.dry_run:
        try:
            from youtube_auth import get_youtube_service
            youtube = get_youtube_service()
        except Exception as e:
            print(f"ERROR: YouTube auth failed: {e}")
            sys.exit(1)

    ok = 0
    fail = 0
    skipped = 0

    for stem, video_id in targets:
        new_desc = _build_description(stem, uploads_data)
        tags = _get_tags(stem)
        title = _get_title(stem)

        full_video_url = uploads_data.get(stem, {}).get("url", "—none—")

        if args.dry_run:
            print(f"\n[DRY RUN] {stem} ({video_id})")
            print(f"  Full video: {full_video_url}")
            print(f"  Tags: {tags[:3]}...")
            print(f"  Desc (first 120 chars): {new_desc[:120]!r}")
            continue

        # We need the current snippet to avoid overwriting categoryId, etc.
        try:
            resp = youtube.videos().list(
                part="snippet",
                id=video_id,
            ).execute()

            items = resp.get("items", [])
            if not items:
                print(f"  [{stem}] SKIP — video not found on YouTube (may be deleted)")
                skipped += 1
                continue

            snippet = items[0]["snippet"]

            # Patch description (keep title, channelId, categoryId, etc.)
            snippet["description"] = new_desc
            if tags:
                snippet["tags"] = tags
            if title:
                snippet["title"] = title

            youtube.videos().update(
                part="snippet",
                body={
                    "id": video_id,
                    "snippet": snippet,
                },
            ).execute()

            print(f"  ✓ {stem} ({video_id}) updated — full video: {full_video_url}")
            ok += 1

        except Exception as e:
            print(f"  ✗ {stem} ({video_id}) FAILED: {e}")
            fail += 1

        # Stay under YouTube quota (avoid 403 rate-limit errors)
        time.sleep(0.5)

    if not args.dry_run:
        print(f"\nDone — {ok} updated, {fail} failed, {skipped} skipped")


if __name__ == "__main__":
    main()
