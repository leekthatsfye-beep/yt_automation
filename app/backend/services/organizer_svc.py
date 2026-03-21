"""
organizer_svc.py — Link Organizer service.

Cross-references YouTube uploads ↔ Airbit listings to show link status,
and provides YouTube description fetching/updating capabilities.
"""

from __future__ import annotations

import json
import logging
from pathlib import Path

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent.parent
UPLOADS_LOG = ROOT / "uploads_log.json"
STORE_LOG = ROOT / "store_uploads_log.json"
LANES_CFG = ROOT / "lanes_config.json"
METADATA_DIR = ROOT / "metadata"


def _load_json(path: Path) -> dict:
    """Safely load a JSON file, returning {} on any error."""
    if not path.exists():
        return {}
    try:
        return json.loads(path.read_text())
    except Exception:
        return {}


def _get_store_profile_url() -> str:
    """Get the store profile URL from lanes_config.json."""
    cfg = _load_json(LANES_CFG)
    return cfg.get("store_profile_url", "")


def remove_from_list(stem: str) -> dict:
    """
    Remove a stem from uploads_log.json only.
    Does NOT delete beat files, rendered media, or metadata.
    Used when a video was removed from YouTube but the log entry remains.
    """
    uploads = _load_json(UPLOADS_LOG)
    if stem not in uploads:
        return {"success": False, "error": f"'{stem}' not found in uploads log"}

    del uploads[stem]
    try:
        UPLOADS_LOG.write_text(json.dumps(uploads, indent=2))
        logger.info("[ORGANIZER] Removed '%s' from uploads_log.json", stem)
        return {"success": True, "removed": stem}
    except Exception as e:
        logger.error("Failed to write uploads_log.json: %s", e)
        return {"success": False, "error": str(e)}


def get_link_status() -> dict:
    """
    Cross-reference uploads_log.json ↔ store_uploads_log.json ↔ metadata
    to build a unified view of every YouTube video's link status.

    Returns:
      {
        "items": [...],
        "totals": { "total": N, "linked": N, "profile_only": N, "missing": N }
      }
    """
    uploads = _load_json(UPLOADS_LOG)
    store_data = _load_json(STORE_LOG)
    store_profile = _get_store_profile_url()

    items = []

    for stem, yt_entry in uploads.items():
        if not isinstance(yt_entry, dict):
            continue

        video_id = yt_entry.get("videoId", "")
        youtube_url = yt_entry.get("url", "")
        title = yt_entry.get("title", stem)
        uploaded_at = yt_entry.get("uploadedAt", "")
        publish_at = yt_entry.get("publishAt")

        # Airbit data
        store_entry = store_data.get(stem, {})
        airbit_entry = store_entry.get("airbit", store_entry) if isinstance(store_entry, dict) else {}
        airbit_url = airbit_entry.get("url", "") if isinstance(airbit_entry, dict) else ""
        listing_id = airbit_entry.get("listing_id", "") if isinstance(airbit_entry, dict) else ""

        # Metadata
        meta_path = METADATA_DIR / f"{stem}.json"
        meta = _load_json(meta_path)
        seo_artist = meta.get("seo_artist", meta.get("artist", ""))
        lane = meta.get("lane", "")

        # Determine link status
        if airbit_url and airbit_url != store_profile and listing_id:
            status = "linked"
        elif airbit_url and (airbit_url == store_profile or not listing_id):
            status = "profile_only"
        else:
            status = "missing"

        items.append({
            "stem": stem,
            "title": title,
            "videoId": video_id,
            "youtubeUrl": youtube_url,
            "uploadedAt": uploaded_at,
            "publishAt": publish_at,
            "airbitUrl": airbit_url,
            "listingId": listing_id,
            "seoArtist": seo_artist,
            "lane": lane,
            "linkStatus": status,
        })

    # Sort: missing first, then profile_only, then linked
    status_order = {"missing": 0, "profile_only": 1, "linked": 2}
    items.sort(key=lambda x: (status_order.get(x["linkStatus"], 99), x["stem"]))

    totals = {
        "total": len(items),
        "linked": sum(1 for i in items if i["linkStatus"] == "linked"),
        "profile_only": sum(1 for i in items if i["linkStatus"] == "profile_only"),
        "missing": sum(1 for i in items if i["linkStatus"] == "missing"),
    }

    return {"items": items, "totals": totals}


def get_youtube_description(video_id: str) -> dict:
    """
    Fetch the live description and title from YouTube for a single video.

    Returns: { "title": "...", "description": "...", "tags": [...] }
    """
    from youtube_auth import get_youtube_service

    try:
        youtube = get_youtube_service()
        response = youtube.videos().list(
            part="snippet",
            id=video_id,
        ).execute()

        items = response.get("items", [])
        if not items:
            return {"error": f"Video {video_id} not found", "title": "", "description": "", "tags": []}

        snippet = items[0].get("snippet", {})
        return {
            "title": snippet.get("title", ""),
            "description": snippet.get("description", ""),
            "tags": snippet.get("tags", []),
        }
    except Exception as e:
        logger.error("Failed to fetch YouTube description for %s: %s", video_id, e)
        return {"error": str(e), "title": "", "description": "", "tags": []}


def update_youtube_description(video_id: str, new_description: str, title: str | None = None) -> dict:
    """
    Update the description (and optionally title) on YouTube.
    Wraps the same logic as upload.py's update_video_metadata().

    Returns: { "success": True/False, "error": "..." }
    """
    from youtube_auth import get_youtube_service

    try:
        youtube = get_youtube_service()

        # First fetch current snippet to preserve existing title/tags if not provided
        response = youtube.videos().list(
            part="snippet",
            id=video_id,
        ).execute()

        items = response.get("items", [])
        if not items:
            return {"success": False, "error": f"Video {video_id} not found"}

        snippet = items[0]["snippet"]
        current_title = snippet.get("title", "")
        current_tags = snippet.get("tags", [])
        category_id = snippet.get("categoryId", "10")

        # Build update body
        body = {
            "id": video_id,
            "snippet": {
                "title": (title or current_title).replace("<", "").replace(">", "").strip()[:100],
                "description": new_description[:5000],
                "tags": current_tags,
                "categoryId": category_id,
            },
        }

        try:
            youtube.videos().update(part="snippet", body=body).execute()
        except Exception as e:
            if "invalidTags" in str(e) or "invalid video keywords" in str(e).lower():
                logger.warning("Tags rejected for %s, retrying without tags", video_id)
                body["snippet"]["tags"] = []
                youtube.videos().update(part="snippet", body=body).execute()
            else:
                raise

        logger.info("[ORGANIZER] Updated description for %s", video_id)
        return {"success": True}

    except Exception as e:
        logger.error("Failed to update YouTube description for %s: %s", video_id, e)
        return {"success": False, "error": str(e)}


def rebuild_description(stem: str) -> dict:
    """
    Generate the 'correct' description for a beat using seo_metadata.py logic.
    Returns the rebuilt text so user can preview before applying.

    Returns: { "description": "...", "purchaseLink": "..." }
    """
    import sys
    sys.path.insert(0, str(ROOT))

    try:
        from seo_metadata import build_description, _get_purchase_link

        meta_path = METADATA_DIR / f"{stem}.json"
        meta = _load_json(meta_path)

        description = build_description(stem, meta)
        purchase_link = _get_purchase_link(stem)

        return {
            "description": description,
            "purchaseLink": purchase_link,
        }
    except Exception as e:
        logger.error("Failed to rebuild description for %s: %s", stem, e)
        return {"description": "", "purchaseLink": "", "error": str(e)}


def fix_single_link(stem: str, video_id: str) -> dict:
    """
    Fix a single video's YouTube description with the correct Airbit link.
    Called per-item by the router for granular progress.

    After a successful fix, marks the stem as 'description_fixed' in
    store_uploads_log.json so the status list reflects the update.

    Returns: { "status": "fixed"|"skipped"|"failed", "reason"?: "..." }
    """
    import sys
    sys.path.insert(0, str(ROOT))

    from youtube_auth import get_youtube_service
    from seo_metadata import build_description, _get_purchase_link

    if not video_id:
        return {"status": "skipped", "reason": "No videoId"}

    try:
        meta_path = METADATA_DIR / f"{stem}.json"
        meta = _load_json(meta_path)
        new_desc = build_description(stem, meta)
        purchase_link = _get_purchase_link(stem)

        youtube = get_youtube_service()

        # Fetch current snippet
        response = youtube.videos().list(part="snippet", id=video_id).execute()
        yt_items = response.get("items", [])
        if not yt_items:
            return {"status": "skipped", "reason": "Video not found on YouTube"}

        snippet = yt_items[0]["snippet"]
        body = {
            "id": video_id,
            "snippet": {
                "title": snippet.get("title", ""),
                "description": new_desc[:5000],
                "tags": snippet.get("tags", []),
                "categoryId": snippet.get("categoryId", "10"),
            },
        }

        try:
            youtube.videos().update(part="snippet", body=body).execute()
        except Exception as e:
            if "invalidTags" in str(e) or "invalid video keywords" in str(e).lower():
                body["snippet"]["tags"] = []
                youtube.videos().update(part="snippet", body=body).execute()
            else:
                raise

        # Mark as description-fixed in store_uploads_log so status list updates
        _mark_description_fixed(stem, purchase_link)

        logger.info("[ORGANIZER] Fixed description for %s (%s)", stem, video_id)
        return {"status": "fixed"}

    except Exception as e:
        logger.error("[ORGANIZER] Failed to fix %s: %s", stem, e)
        return {"status": "failed", "reason": str(e)[:200]}


def _mark_description_fixed(stem: str, purchase_link: str) -> None:
    """
    After pushing a fixed description to YouTube, update store_uploads_log.json
    so the organizer status list reflects the change.

    If the beat already has a full listing URL, leave it alone.
    If it only had the profile URL or nothing, record that the description
    was fixed with whatever link was available.
    """
    from datetime import datetime, timezone

    store_data = _load_json(STORE_LOG)
    store_profile = _get_store_profile_url()
    entry = store_data.get(stem, {})
    airbit = entry.get("airbit", {}) if isinstance(entry, dict) else {}

    existing_url = airbit.get("url", "") if isinstance(airbit, dict) else ""
    existing_lid = airbit.get("listing_id", "") if isinstance(airbit, dict) else ""

    # If already fully linked, nothing to update
    if existing_url and existing_url != store_profile and existing_lid:
        return

    # Update the entry to reflect the fix
    now = datetime.now(timezone.utc).isoformat()
    store_data[stem] = {
        "airbit": {
            "url": purchase_link or store_profile,
            "listing_id": existing_lid or "",
            "uploaded_at": airbit.get("uploaded_at", now) if isinstance(airbit, dict) else now,
            "description_fixed_at": now,
        }
    }

    try:
        STORE_LOG.write_text(json.dumps(store_data, indent=2))
    except Exception as e:
        logger.error("Failed to update store_uploads_log for %s: %s", stem, e)


def fix_all_links() -> dict:
    """
    Batch fix all videos that have missing or profile-only links.
    Rebuilds descriptions with correct Airbit links and pushes to YouTube.

    Returns: { "fixed": N, "failed": N, "skipped": N, "details": [...] }
    """
    import sys
    sys.path.insert(0, str(ROOT))

    from youtube_auth import get_youtube_service
    from seo_metadata import build_description

    uploads = _load_json(UPLOADS_LOG)
    status_data = get_link_status()
    items_to_fix = [
        item for item in status_data["items"]
        if item["linkStatus"] in ("missing", "profile_only")
    ]

    if not items_to_fix:
        return {"fixed": 0, "failed": 0, "skipped": 0, "details": []}

    try:
        youtube = get_youtube_service()
    except Exception as e:
        return {"fixed": 0, "failed": 0, "skipped": 0, "details": [], "error": str(e)}

    results = []
    fixed = 0
    failed = 0
    skipped = 0

    for item in items_to_fix:
        stem = item["stem"]
        video_id = item["videoId"]

        if not video_id:
            skipped += 1
            results.append({"stem": stem, "status": "skipped", "reason": "No videoId"})
            continue

        try:
            meta_path = METADATA_DIR / f"{stem}.json"
            meta = _load_json(meta_path)
            new_desc = build_description(stem, meta)

            # Fetch current snippet
            response = youtube.videos().list(part="snippet", id=video_id).execute()
            yt_items = response.get("items", [])
            if not yt_items:
                skipped += 1
                results.append({"stem": stem, "status": "skipped", "reason": "Video not found on YouTube"})
                continue

            snippet = yt_items[0]["snippet"]
            body = {
                "id": video_id,
                "snippet": {
                    "title": snippet.get("title", ""),
                    "description": new_desc[:5000],
                    "tags": snippet.get("tags", []),
                    "categoryId": snippet.get("categoryId", "10"),
                },
            }

            try:
                youtube.videos().update(part="snippet", body=body).execute()
            except Exception as e:
                if "invalidTags" in str(e) or "invalid video keywords" in str(e).lower():
                    body["snippet"]["tags"] = []
                    youtube.videos().update(part="snippet", body=body).execute()
                else:
                    raise

            fixed += 1
            results.append({"stem": stem, "status": "fixed"})
            logger.info("[ORGANIZER] Fixed description for %s (%s)", stem, video_id)

        except Exception as e:
            failed += 1
            results.append({"stem": stem, "status": "failed", "error": str(e)[:200]})
            logger.error("[ORGANIZER] Failed to fix %s: %s", stem, e)

    return {"fixed": fixed, "failed": failed, "skipped": skipped, "details": results}
