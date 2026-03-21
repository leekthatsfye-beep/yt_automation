"""
/api/analytics — Aggregated analytics for the dashboard (admin only).

Combines beat counts, upload history, upload-per-day stats,
YouTube performance data, and social distribution.
"""

from __future__ import annotations

import json
import logging
from collections import defaultdict
from typing import Any

from fastapi import APIRouter, Depends

from app.backend.deps import require_admin, UserContext, get_user_paths
from app.backend.services.beat_svc import safe_stem

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/analytics", tags=["analytics"])


def _load_json(path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        return {}
    return {}


@router.get("")
async def get_analytics(user: UserContext = Depends(require_admin)):
    """
    Return full analytics payload (admin only):
    - summary: total beats, rendered, uploaded counts
    - uploads: full YouTube upload history (all entries, newest first)
    - daily_counts: { "YYYY-MM-DD": count } for calendar heatmap
    - social_distribution: counts per platform
    - schedule_health: buffer days + queue length
    """
    paths = get_user_paths(user)

    # Beat stems
    audio_files = list(paths.beats_dir.glob("*.mp3")) + list(paths.beats_dir.glob("*.wav"))
    all_stems = {safe_stem(f.name) for f in audio_files}
    total = len(all_stems)

    # Rendered
    rendered = sum(1 for s in all_stems if (paths.output_dir / f"{s}.mp4").exists())

    # YouTube uploads
    uploads_log = _load_json(paths.uploads_log)
    uploaded_yt = sum(1 for s in all_stems if s in uploads_log)

    # Social uploads
    social_log = _load_json(paths.social_log)
    uploaded_social = sum(1 for s in all_stems if s in social_log)

    # Build full upload list
    uploads: list[dict[str, Any]] = []
    daily: dict[str, int] = defaultdict(int)

    for stem, entry in uploads_log.items():
        uploaded_at = entry.get("uploadedAt", "")
        uploads.append({
            "stem": stem,
            "title": entry.get("title", stem),
            "videoId": entry.get("videoId"),
            "url": entry.get("url"),
            "uploadedAt": uploaded_at,
            "publishAt": entry.get("publishAt"),
        })
        if uploaded_at:
            day_key = uploaded_at[:10]
            daily[day_key] += 1

    uploads.sort(key=lambda x: x.get("uploadedAt", ""), reverse=True)

    # Social distribution counts
    social_counts = {
        "youtube": uploaded_yt,
        "youtube_shorts": 0,
        "instagram": 0,
        "tiktok": 0,
    }
    for _stem, entry in social_log.items():
        if isinstance(entry, dict):
            for platform in ["youtube_shorts", "instagram", "tiktok"]:
                if entry.get(platform):
                    social_counts[platform] += 1

    # Schedule health
    schedule_health: dict[str, Any] = {}
    try:
        from app.backend.services import schedule_svc
        buffer = schedule_svc.get_buffer_days()
        full = schedule_svc.get_full_schedule(uploads_log_path=paths.uploads_log)
        schedule_health = {
            "buffer_days": round(buffer, 1),
            "queue_length": full.get("queue_length", 0),
        }
    except Exception as e:
        logger.debug("Schedule health unavailable: %s", e)

    return {
        "summary": {
            "total_beats": total,
            "rendered": rendered,
            "uploaded_yt": uploaded_yt,
            "uploaded_social": uploaded_social,
            "pending_renders": total - rendered,
        },
        "uploads": uploads,
        "daily_counts": dict(daily),
        "social_distribution": social_counts,
        "schedule_health": schedule_health,
    }


@router.get("/youtube-stats")
async def get_youtube_stats(user: UserContext = Depends(require_admin)):
    """Pull real YouTube video statistics (cached 6h)."""
    paths = get_user_paths(user)
    from app.backend.services import analytics_svc
    return await analytics_svc.fetch_youtube_stats(paths.uploads_log)


@router.post("/youtube-stats/refresh")
async def refresh_youtube_stats(user: UserContext = Depends(require_admin)):
    """Force refresh YouTube stats (bypass cache)."""
    paths = get_user_paths(user)
    from app.backend.services import analytics_svc
    analytics_svc.clear_cache()
    return await analytics_svc.fetch_youtube_stats(paths.uploads_log)


@router.get("/artist-performance")
async def get_artist_performance(user: UserContext = Depends(require_admin)):
    """Performance breakdown by seo_artist."""
    paths = get_user_paths(user)
    from app.backend.services import analytics_svc
    stats = await analytics_svc.fetch_youtube_stats(paths.uploads_log)
    return analytics_svc.compute_artist_performance(stats, paths.metadata_dir)
