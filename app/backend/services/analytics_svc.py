"""
Analytics service — Real YouTube performance data with caching.

Pulls viewCount, likeCount, commentCount for every uploaded video via
YouTube Data API v3.  Results cached in youtube_stats_cache.json with
a 6-hour TTL.  Quota cost: ~10 units for ~500 videos (batches of 50).
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

ROOT = Path(__file__).resolve().parent.parent.parent.parent
STATS_CACHE = ROOT / "youtube_stats_cache.json"
CACHE_TTL_HOURS = 6


# ── Cache helpers ───────────────────────────────────────────────────────

def _load_cache() -> dict:
    try:
        if STATS_CACHE.exists():
            return json.loads(STATS_CACHE.read_text())
    except Exception:
        pass
    return {}


def _cache_is_fresh() -> bool:
    cache = _load_cache()
    ts = cache.get("fetched_at")
    if not ts:
        return False
    try:
        fetched = datetime.fromisoformat(ts)
        age = datetime.now(timezone.utc) - fetched
        return age.total_seconds() < CACHE_TTL_HOURS * 3600
    except Exception:
        return False


def clear_cache() -> None:
    """Remove the stats cache file to force a refresh."""
    STATS_CACHE.unlink(missing_ok=True)


# ── YouTube API ─────────────────────────────────────────────────────────

def _get_youtube_service():
    """Reuse the YouTube auth pattern from trends_svc."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    token_file = ROOT / "token.json"
    scopes = ["https://www.googleapis.com/auth/youtube.readonly"]

    if not token_file.exists():
        raise FileNotFoundError(
            "token.json not found — run upload.py once to authenticate"
        )

    creds = Credentials.from_authorized_user_file(str(token_file), scopes)
    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


# ── Core fetch ──────────────────────────────────────────────────────────

async def fetch_youtube_stats(uploads_log_path: Path) -> dict[str, Any]:
    """
    Pull viewCount / likeCount / commentCount for every uploaded video.
    Returns cached data if within TTL.
    """
    if _cache_is_fresh():
        return _load_cache()

    uploads_log: dict[str, Any] = {}
    try:
        if uploads_log_path.exists():
            uploads_log = json.loads(uploads_log_path.read_text())
    except Exception:
        pass

    # Map videoId → stem for reverse lookup
    vid_to_stem: dict[str, dict] = {}
    for stem, entry in uploads_log.items():
        vid = entry.get("videoId")
        if vid:
            vid_to_stem[vid] = {
                "stem": stem,
                "title": entry.get("title", stem),
                "url": entry.get("url", ""),
                "uploadedAt": entry.get("uploadedAt", ""),
                "publishAt": entry.get("publishAt"),
            }

    video_ids = list(vid_to_stem.keys())
    if not video_ids:
        empty = {
            "fetched_at": datetime.now(timezone.utc).isoformat(),
            "video_count": 0,
            "totals": {"views": 0, "likes": 0, "comments": 0},
            "averages": {"views_per_video": 0, "likes_per_video": 0},
            "top_videos": [],
            "per_video": {},
        }
        return empty

    try:
        youtube = _get_youtube_service()
    except Exception as e:
        logger.error("YouTube auth failed: %s", e)
        return {"error": str(e), "fetched_at": None}

    # Fetch in batches of 50 (API limit)
    all_stats: dict[str, dict] = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        try:
            resp = youtube.videos().list(
                id=",".join(batch),
                part="statistics",
            ).execute()
            for item in resp.get("items", []):
                vid = item["id"]
                stats = item.get("statistics", {})
                all_stats[vid] = {
                    "viewCount": int(stats.get("viewCount", 0)),
                    "likeCount": int(stats.get("likeCount", 0)),
                    "commentCount": int(stats.get("commentCount", 0)),
                }
        except Exception as e:
            logger.warning("YouTube stats batch failed: %s", e)

    # Aggregates
    total_views = sum(s["viewCount"] for s in all_stats.values())
    total_likes = sum(s["likeCount"] for s in all_stats.values())
    total_comments = sum(s["commentCount"] for s in all_stats.values())
    video_count = len(all_stats)

    # Top 20 videos by views
    top_sorted = sorted(
        all_stats.items(),
        key=lambda x: x[1]["viewCount"],
        reverse=True,
    )[:20]

    top_videos = []
    for vid, stats in top_sorted:
        info = vid_to_stem.get(vid, {"stem": "unknown", "title": vid})
        top_videos.append({
            **info,
            "videoId": vid,
            **stats,
        })

    # Per-video stats keyed by stem
    per_video: dict[str, dict] = {}
    for vid, stats in all_stats.items():
        info = vid_to_stem.get(vid, {})
        stem = info.get("stem", vid)
        per_video[stem] = stats

    result = {
        "fetched_at": datetime.now(timezone.utc).isoformat(),
        "video_count": video_count,
        "totals": {
            "views": total_views,
            "likes": total_likes,
            "comments": total_comments,
        },
        "averages": {
            "views_per_video": total_views // max(video_count, 1),
            "likes_per_video": total_likes // max(video_count, 1),
        },
        "top_videos": top_videos,
        "per_video": per_video,
    }

    # Save cache
    try:
        STATS_CACHE.write_text(json.dumps(result, indent=2))
    except Exception as e:
        logger.error("Failed to write stats cache: %s", e)

    return result


# ── Artist performance breakdown ────────────────────────────────────────

def compute_artist_performance(
    stats: dict[str, Any],
    metadata_dir: Path,
) -> list[dict[str, Any]]:
    """
    Group video performance by seo_artist from metadata.
    Returns sorted list of artist performance objects.
    """
    per_video = stats.get("per_video", {})
    if not per_video:
        return []

    # Build stem → seo_artist mapping
    artist_stats: dict[str, dict] = defaultdict(
        lambda: {"artist": "", "videos": 0, "total_views": 0, "total_likes": 0, "total_comments": 0}
    )

    for stem, video_stats in per_video.items():
        meta_path = metadata_dir / f"{stem}.json"
        seo_artist = "Unknown"
        try:
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                seo_artist = meta.get("seo_artist") or meta.get("artist", "Unknown")
        except Exception:
            pass

        bucket = artist_stats[seo_artist]
        bucket["artist"] = seo_artist
        bucket["videos"] += 1
        bucket["total_views"] += video_stats.get("viewCount", 0)
        bucket["total_likes"] += video_stats.get("likeCount", 0)
        bucket["total_comments"] += video_stats.get("commentCount", 0)

    # Compute averages and sort by total views
    result = []
    for data in artist_stats.values():
        count = data["videos"]
        result.append({
            "artist": data["artist"],
            "videos": count,
            "total_views": data["total_views"],
            "avg_views": data["total_views"] // max(count, 1),
            "total_likes": data["total_likes"],
            "avg_likes": data["total_likes"] // max(count, 1),
            "total_comments": data["total_comments"],
        })

    result.sort(key=lambda x: x["total_views"], reverse=True)
    return result
