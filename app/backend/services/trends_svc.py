"""
Trend Discovery Engine — scan real YouTube data to recommend next uploads.

Uses the YouTube Data API v3 to measure actual type beat demand:
- Search "[Artist] type beat" → count recent uploads (supply)
- Pull view counts on those videos (demand)
- Compute demand/supply ratio to find underserved niches
- Cross-reference with channel upload history for saturation

Supports Male/Female demographic filtering for separate scans.
Runs a full scan daily, caches results to disk.
"""

from __future__ import annotations

import json
import logging
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── Artist universe — all artists we track, split by gender ──────────────

ARTIST_CLUSTERS: dict[str, list[str]] = {
    "Glokk40Spaz": ["OsamaSon", "Ken Carson", "Destroy Lonely", "Yeat", "Playboi Carti", "Ola Runt"],
    "BiggKutt8": ["Jettt4", "BlizzyBoiSauce", "J1", "Spinback Bihh", "Swift Jitt", "Kickkone", "Foogiano", "KuttEm Reese", "Big Scarr"],
    "Sexyy Red": ["GloRilla", "Sukihana", "Latto", "Cardi B", "City Girls", "Megan Thee Stallion", "Ice Spice"],
    "GloRilla": ["Sexyy Red", "Megan Thee Stallion", "Latto", "Cardi B", "Ice Spice", "Sukihana"],
    "Babyxsosa": ["Sexyy Red", "Ice Spice", "GloRilla", "Coi Leray", "Flo Milli", "Doechii"],
    "Sukihana": ["Sexyy Red", "GloRilla", "City Girls", "Megan Thee Stallion", "Latto", "Cardi B"],
    "OsamaSon": ["Glokk40Spaz", "Ken Carson", "Destroy Lonely", "Yeat", "Homixide Gang"],
    "Foogiano": ["BiggKutt8", "Pooh Shiesty", "Big Scarr", "EST Gee", "Moneybagg Yo"],
}

# ── Gender classification ────────────────────────────────────────────────

FEMALE_ARTISTS: set[str] = {
    "Sexyy Red", "GloRilla", "Sukihana", "Latto", "Cardi B", "City Girls",
    "Megan Thee Stallion", "Ice Spice", "Babyxsosa", "Coi Leray",
    "Flo Milli", "Doechii",
}

MALE_ARTISTS: set[str] = {
    "Glokk40Spaz", "OsamaSon", "Ken Carson", "Destroy Lonely", "Yeat",
    "Playboi Carti", "Ola Runt", "BiggKutt8", "Jettt4", "BlizzyBoiSauce",
    "J1", "Spinback Bihh", "Swift Jitt", "Kickkone", "Foogiano",
    "KuttEm Reese", "Big Scarr", "Pooh Shiesty", "EST Gee",
    "Moneybagg Yo", "Homixide Gang",
}

# All artists to scan — primary lanes + cluster members
ALL_ARTISTS: list[str] = sorted(set(
    list(ARTIST_CLUSTERS.keys()) +
    [a for cluster in ARTIST_CLUSTERS.values() for a in cluster]
))

# ── Cache config ──────────────────────────────────────────────────────────

CACHE_FILE = Path(__file__).resolve().parent.parent.parent.parent / "trend_cache.json"
CACHE_MAX_AGE_HOURS = 12  # Re-scan after 12 hours


def _load_cache() -> dict:
    try:
        if CACHE_FILE.exists():
            return json.loads(CACHE_FILE.read_text())
    except Exception:
        pass
    return {}


def _save_cache(data: dict) -> None:
    try:
        CACHE_FILE.write_text(json.dumps(data, indent=2))
    except Exception as e:
        logger.error("Failed to save trend cache: %s", e)


def _cache_is_fresh() -> bool:
    cache = _load_cache()
    ts = cache.get("scanned_at")
    if not ts:
        return False
    try:
        scanned = datetime.fromisoformat(ts)
        age = datetime.now(timezone.utc) - scanned
        return age.total_seconds() < CACHE_MAX_AGE_HOURS * 3600
    except Exception:
        return False


# ── YouTube API scanning ──────────────────────────────────────────────────

def _get_youtube_service():
    """Get authenticated YouTube API client using existing OAuth credentials."""
    from google.auth.transport.requests import Request
    from google.oauth2.credentials import Credentials
    from googleapiclient.discovery import build

    root = Path(__file__).resolve().parent.parent.parent.parent
    token_file = root / "token.json"
    scopes = [
        "https://www.googleapis.com/auth/youtube.readonly",
    ]

    if not token_file.exists():
        raise FileNotFoundError(
            "token.json not found — run upload.py once to authenticate with YouTube"
        )

    creds = Credentials.from_authorized_user_file(str(token_file), scopes)

    if creds and creds.expired and creds.refresh_token:
        creds.refresh(Request())
        with open(token_file, "w") as f:
            f.write(creds.to_json())

    return build("youtube", "v3", credentials=creds)


def _scan_artist_youtube(youtube, artist: str, days: int = 7) -> dict[str, Any]:
    """
    Search YouTube for '[Artist] type beat' and measure demand + supply.

    Returns:
        {
            "artist": str,
            "gender": "male" | "female",
            "views_7d": int,
            "uploads_7d": int,
            "avg_views": int,
            "top_video_views": int,
            "demand_score": float,
        }
    """
    query = f"{artist} type beat"
    after = (datetime.now(timezone.utc) - timedelta(days=days)).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Classify gender
    gender = "female" if artist in FEMALE_ARTISTS else "male"

    try:
        # Search for recent type beat uploads
        search_resp = youtube.search().list(
            q=query,
            type="video",
            part="id",
            publishedAfter=after,
            order="viewCount",
            maxResults=20,
        ).execute()

        video_ids = [item["id"]["videoId"] for item in search_resp.get("items", [])]
        total_results = search_resp.get("pageInfo", {}).get("totalResults", 0)

        if not video_ids:
            return {
                "artist": artist,
                "gender": gender,
                "views_7d": 0,
                "uploads_7d": 0,
                "avg_views": 0,
                "top_video_views": 0,
                "demand_score": 0,
            }

        # Get view counts for those videos
        stats_resp = youtube.videos().list(
            id=",".join(video_ids),
            part="statistics",
        ).execute()

        views = []
        for item in stats_resp.get("items", []):
            v = int(item["statistics"].get("viewCount", 0))
            views.append(v)

        total_views = sum(views)
        avg_views = total_views // len(views) if views else 0
        top_views = max(views) if views else 0

        return {
            "artist": artist,
            "gender": gender,
            "views_7d": total_views,
            "uploads_7d": min(total_results, 500),  # cap at reasonable number
            "avg_views": avg_views,
            "top_video_views": top_views,
            "demand_score": 0,  # computed later after normalization
        }

    except Exception as e:
        logger.warning("YouTube scan failed for %s: %s", artist, e)
        return {
            "artist": artist,
            "gender": gender,
            "views_7d": 0,
            "uploads_7d": 0,
            "avg_views": 0,
            "top_video_views": 0,
            "demand_score": 0,
            "error": str(e),
        }


def _normalize_scores(artist_data: list[dict]) -> list[dict]:
    """Normalize raw YouTube data into 0-100 demand scores."""
    if not artist_data:
        return artist_data

    # Find max values for normalization
    max_views = max((d["views_7d"] for d in artist_data), default=1) or 1
    max_avg = max((d["avg_views"] for d in artist_data), default=1) or 1

    for d in artist_data:
        # Demand signal: total views (40%) + avg views per video (30%)
        view_score = (d["views_7d"] / max_views) * 40
        avg_score = (d["avg_views"] / max_avg) * 30

        # Supply penalty: more uploads = more competition = lower opportunity
        # Fewer uploads with high views = golden opportunity
        uploads = d["uploads_7d"]
        if uploads == 0:
            supply_bonus = 0  # No data
        elif uploads < 10:
            supply_bonus = 20  # Low competition
        elif uploads < 30:
            supply_bonus = 10  # Moderate competition
        else:
            supply_bonus = 0  # Saturated

        # Demand/supply ratio bonus
        if uploads > 0 and d["avg_views"] > 0:
            ratio = d["avg_views"] / uploads
            ratio_bonus = min(10, ratio / 100)  # Cap at 10 points
        else:
            ratio_bonus = 0

        d["demand_score"] = round(min(100, view_score + avg_score + supply_bonus + ratio_bonus))

    return artist_data


# ── Public API ────────────────────────────────────────────────────────────

async def run_full_scan(
    artists: list[str] | None = None,
    gender: str | None = None,
) -> dict[str, Any]:
    """
    Run a full YouTube trend scan for tracked artists.
    Optionally filter by gender ("male" or "female").

    Quota cost: ~1 search (100 units) + 1 videos.list (1 unit) per artist.
    For 30 artists: ~3,030 units out of 10,000 daily quota.
    """
    scan_artists = artists or ALL_ARTISTS

    # Filter by gender if specified
    if gender == "female":
        scan_artists = [a for a in scan_artists if a in FEMALE_ARTISTS]
    elif gender == "male":
        scan_artists = [a for a in scan_artists if a in MALE_ARTISTS]

    logger.info("Starting trend scan for %d artists (gender=%s)...", len(scan_artists), gender or "all")

    try:
        youtube = _get_youtube_service()
    except Exception as e:
        logger.error("Failed to get YouTube service: %s", e)
        return {"error": str(e), "artists": [], "scanned_at": None}

    results = []
    scanned = 0
    errors = 0

    for artist in scan_artists:
        data = _scan_artist_youtube(youtube, artist, days=7)
        results.append(data)
        scanned += 1

        if "error" in data:
            errors += 1

        # Small delay to avoid hammering the API
        time.sleep(0.3)

        if scanned % 10 == 0:
            logger.info("Scanned %d/%d artists...", scanned, len(scan_artists))

    # Normalize scores
    results = _normalize_scores(results)

    # Sort by demand score
    results.sort(key=lambda x: x["demand_score"], reverse=True)

    scan_result = {
        "artists": results,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
        "total_scanned": scanned,
        "errors": errors,
        "source": "youtube_data_api",
        "gender_filter": gender,
    }

    # Merge with existing cache instead of replacing
    existing_cache = _load_cache()
    if gender:
        # Save gender-specific results alongside full results
        existing_cache[f"artists_{gender}"] = results
        existing_cache[f"scanned_at_{gender}"] = scan_result["scanned_at"]
        existing_cache[f"total_scanned_{gender}"] = scanned
    else:
        # Full scan — save everything, also split by gender for tabs
        existing_cache["artists"] = results
        existing_cache["scanned_at"] = scan_result["scanned_at"]
        existing_cache["total_scanned"] = scanned
        existing_cache["errors"] = errors
        existing_cache["source"] = "youtube_data_api"
        # Auto-split by gender
        existing_cache["artists_male"] = [a for a in results if a.get("gender") == "male"]
        existing_cache["artists_female"] = [a for a in results if a.get("gender") == "female"]
        existing_cache["scanned_at_male"] = scan_result["scanned_at"]
        existing_cache["scanned_at_female"] = scan_result["scanned_at"]

    _save_cache(existing_cache)
    logger.info("Trend scan complete: %d artists, %d errors (gender=%s)", scanned, errors, gender or "all")

    return scan_result


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def _count_uploads_by_artist(uploads_log: dict) -> dict[str, int]:
    """Count how many videos exist per artist from upload titles."""
    counts: dict[str, int] = {}
    for stem, info in uploads_log.items():
        title = info.get("title", "")
        if "Type Beat" in title:
            artist = title.replace(" Type Beat", "").strip()
            counts[artist] = counts.get(artist, 0) + 1
    return counts


def get_artist_clusters() -> dict[str, list[str]]:
    """Return all artist clusters."""
    return dict(ARTIST_CLUSTERS)


def get_gender_classification() -> dict[str, list[str]]:
    """Return artists classified by gender."""
    return {
        "male": sorted(MALE_ARTISTS),
        "female": sorted(FEMALE_ARTISTS),
    }


def analyze_channel(uploads_log_path: Path) -> dict[str, Any]:
    """Analyze channel upload distribution."""
    uploads_log = _load_json(uploads_log_path)
    artist_counts = _count_uploads_by_artist(uploads_log)
    total = len(uploads_log)

    return {
        "total_uploads": total,
        "artist_distribution": artist_counts,
    }


def recommend_uploads(
    uploads_log_path: Path,
    lanes_config_path: Path,
    count: int = 10,
    gender: str | None = None,
) -> dict[str, Any]:
    """
    Generate recommendations by combining:
    1. Real YouTube trend data (if available from cache)
    2. Channel upload history (saturation)
    3. Lane relevance
    4. Optional gender filter

    If no YouTube scan data exists, falls back to channel-only analysis.
    """
    uploads_log = _load_json(uploads_log_path)
    lanes_cfg = _load_json(lanes_config_path)
    artist_counts = _count_uploads_by_artist(uploads_log)
    total = len(uploads_log)

    # Get lane artists for relevance
    lane_artists = set()
    for lane_data in lanes_cfg.get("lanes", {}).values():
        for a in lane_data.get("artists", []):
            lane_artists.add(a)
    for primary, cluster in ARTIST_CLUSTERS.items():
        if primary in lane_artists:
            for a in cluster:
                lane_artists.add(a)

    # Try to use cached YouTube scan data
    cache = _load_cache()

    # Use gender-specific cache if available
    if gender and f"artists_{gender}" in cache:
        yt_artists = cache[f"artists_{gender}"]
        scanned_at = cache.get(f"scanned_at_{gender}")
    else:
        yt_artists = cache.get("artists", [])
        scanned_at = cache.get("scanned_at")

    yt_data = {d["artist"]: d for d in yt_artists}
    has_yt_data = bool(yt_data)

    producer = lanes_cfg.get("producer", "leekthatsfy3")

    # Filter artist list by gender if specified
    target_artists = ALL_ARTISTS
    if gender == "female":
        target_artists = [a for a in ALL_ARTISTS if a in FEMALE_ARTISTS]
    elif gender == "male":
        target_artists = [a for a in ALL_ARTISTS if a in MALE_ARTISTS]

    # Build recommendations
    candidates = []
    for artist in target_artists:
        yt = yt_data.get(artist, {})
        channel_count = artist_counts.get(artist, 0)

        # Base score from YouTube data (0-100) or fallback
        if has_yt_data and yt.get("demand_score", 0) > 0:
            base_score = yt["demand_score"]
        else:
            # Fallback: rough estimate based on cluster position
            base_score = 50  # neutral

        # Channel saturation penalty
        if total > 0:
            saturation = min(channel_count / max(total, 1), 0.5)
            saturation_penalty = int(saturation * 25)
        else:
            saturation_penalty = 0

        # New artist bonus
        new_bonus = 10 if channel_count == 0 else (5 if channel_count < 5 else 0)

        # Lane relevance bonus
        lane_bonus = 5 if artist in lane_artists else 0

        final_score = max(0, min(100, base_score - saturation_penalty + new_bonus + lane_bonus))

        # Build reason string
        reasons = []
        if has_yt_data and yt.get("views_7d", 0) > 0:
            views_k = yt["views_7d"] / 1000
            reasons.append(f"{views_k:.0f}K views this week")
            reasons.append(f"{yt.get('uploads_7d', 0)} new uploads")
        if channel_count == 0:
            reasons.append("New for your channel")
        elif channel_count < 5:
            reasons.append("Low saturation")
        elif saturation_penalty > 10:
            reasons.append("High saturation")
        if artist in lane_artists:
            reasons.append("In your lanes")

        artist_gender = "female" if artist in FEMALE_ARTISTS else "male"

        candidates.append({
            "title": f"{artist} Type Beat",
            "artist": artist,
            "gender": artist_gender,
            "seo_score": final_score,
            "reason": " · ".join(reasons) if reasons else "—",
            "niche_relevant": artist in lane_artists,
            "channel_uploads": channel_count,
            "views_7d": yt.get("views_7d", 0),
            "uploads_7d": yt.get("uploads_7d", 0),
            "avg_views": yt.get("avg_views", 0),
            "description": f"Purchase / Download\nAIRBIT_LINK_HERE\n\nprod. {producer}",
            "cluster": ARTIST_CLUSTERS.get(artist, []),
        })

    candidates.sort(key=lambda x: x["seo_score"], reverse=True)
    top = candidates[:count]

    return {
        "recommended_uploads": top,
        "analysis": {
            "total_channel_uploads": total,
            "unique_artists": len(artist_counts),
            "top_artist": max(artist_counts, key=artist_counts.get) if artist_counts else None,
        },
        "data_source": "youtube" if has_yt_data else "fallback",
        "last_scan": scanned_at,
        "gender_filter": gender,
    }
