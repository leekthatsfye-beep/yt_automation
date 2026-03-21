"""
/api/trends — Trend Discovery Engine endpoints.

Scan YouTube for real type beat demand data, analyze channel gaps,
and recommend next uploads. Supports Male/Female demographic filtering.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, Query

from app.backend.deps import require_admin, UserContext, get_user_paths
from app.backend.config import ROOT
from app.backend.services import trends_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/trends", tags=["trends"])


@router.get("/recommend")
async def recommend_uploads(
    count: int = Query(10, ge=1, le=30),
    gender: Optional[str] = Query(None, pattern="^(male|female)$"),
    user: UserContext = Depends(require_admin),
):
    """Get recommended next uploads combining YouTube data + channel analysis.

    Optional gender filter: ?gender=male or ?gender=female
    """
    paths = get_user_paths(user)
    lanes_config_path = ROOT / "lanes_config.json"
    return trends_svc.recommend_uploads(
        paths.uploads_log, lanes_config_path,
        count=count, gender=gender,
    )


@router.post("/scan")
async def run_scan(
    gender: Optional[str] = Query(None, pattern="^(male|female)$"),
    user: UserContext = Depends(require_admin),
):
    """
    Run a full YouTube trend scan for tracked artists.
    Optional gender filter to scan only male or female artists.

    Takes ~15-60 seconds depending on artist count.
    Quota cost: ~100 units per artist.
    Results are cached to disk and used by /recommend.
    """
    result = await trends_svc.run_full_scan(gender=gender)
    return result


@router.get("/scan/status")
async def scan_status():
    """Check if cached scan data exists and when it was last run."""
    cache = trends_svc._load_cache()
    scanned_at = cache.get("scanned_at")
    total = cache.get("total_scanned", 0)
    source = cache.get("source", "none")
    errors = cache.get("errors", 0)

    return {
        "has_data": bool(scanned_at),
        "scanned_at": scanned_at,
        "total_scanned": total,
        "errors": errors,
        "source": source,
        "cache_fresh": trends_svc._cache_is_fresh(),
        "scanned_at_male": cache.get("scanned_at_male"),
        "scanned_at_female": cache.get("scanned_at_female"),
        "male_count": len(cache.get("artists_male", [])),
        "female_count": len(cache.get("artists_female", [])),
    }


@router.get("/genders")
async def get_gender_classification():
    """Get artists classified by gender."""
    return trends_svc.get_gender_classification()


@router.get("/analyze")
async def analyze_channel(user: UserContext = Depends(require_admin)):
    """Analyze channel upload distribution and identify gaps."""
    paths = get_user_paths(user)
    return trends_svc.analyze_channel(paths.uploads_log)


@router.get("/clusters")
async def get_clusters():
    """Get artist cluster mappings."""
    return {"clusters": trends_svc.get_artist_clusters()}
