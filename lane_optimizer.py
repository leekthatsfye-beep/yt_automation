"""
lane_optimizer.py

Analytics-driven lane prioritization for FY3 content scheduling.
Ranks artist clusters by performance score so the scheduler can
allocate premium time slots to the best-performing lanes.

Integration:
    from lane_optimizer import get_lane_priority

    priority = get_lane_priority()
    # → ["lunch", "breakfast", "dinner"]  (ranked best → worst)

Does NOT modify content_scheduler.py or any existing module.
content_scheduler.py calls get_lane_priority() to inform its slot assignment.

Data source:
    analytics.json — per-lane performance metrics.
    Falls back to default cluster rotation if the file is missing or empty.

Usage (CLI):
    python lane_optimizer.py                # print ranked lanes
    python lane_optimizer.py --refresh      # recalculate from uploads_log
    python lane_optimizer.py --verbose      # show full score breakdown
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger("lane_optimizer")

ROOT           = Path(__file__).resolve().parent
ANALYTICS_FILE = ROOT / "analytics.json"
LANES_CFG      = ROOT / "lanes_config.json"
UPLOADS_LOG    = ROOT / "uploads_log.json"
META_DIR       = ROOT / "metadata"


# ── JSON helpers ─────────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def _save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2, default=str))


# ── Default cluster order (fallback when no analytics exist) ─────────────────

def _default_lane_order() -> list[str]:
    """Read lanes_config.json and return lane keys in config order."""
    cfg = _load_json(LANES_CFG)
    lanes = cfg.get("lanes", {})
    if lanes:
        return list(lanes.keys())
    return ["breakfast", "lunch", "dinner"]


# ── Analytics data ───────────────────────────────────────────────────────────

def load_analytics() -> dict[str, dict[str, Any]]:
    """Load analytics.json — per-lane performance data.

    Expected format:
    {
        "breakfast": {"videos": 24, "views": 3200, "ctr": 6.4},
        "lunch":     {"videos": 18, "views": 4100, "ctr": 7.2},
        "dinner":    {"videos": 20, "views": 2900, "ctr": 5.8}
    }
    """
    return _load_json(ANALYTICS_FILE)


def save_analytics(data: dict[str, dict[str, Any]]):
    """Persist analytics.json."""
    _save_json(ANALYTICS_FILE, data)


# ── Scoring ──────────────────────────────────────────────────────────────────

def calculate_lane_score(lane_data: dict[str, Any]) -> float:
    """Calculate lane priority score.

    Formula:  score = (views / videos) * CTR

    Higher score = lane gets priority time slots.
    """
    videos = lane_data.get("videos", 0)
    views  = lane_data.get("views", 0)
    ctr    = lane_data.get("ctr", 0)

    if videos <= 0 or views <= 0:
        return 0.0

    avg_views = views / videos
    score = avg_views * ctr
    return round(score, 2)


def get_lane_scores() -> dict[str, float]:
    """Calculate score for every lane.

    Returns {lane_name: score} sorted best-first.
    """
    analytics = load_analytics()
    if not analytics:
        return {}

    scores: dict[str, float] = {}
    for lane, data in analytics.items():
        scores[lane] = calculate_lane_score(data)

    # Sort descending
    return dict(sorted(scores.items(), key=lambda x: x[1], reverse=True))


# ── Public API ───────────────────────────────────────────────────────────────

def get_lane_priority() -> list[str]:
    """Return lanes ranked by performance score (best first).

    This is the main function content_scheduler.py calls.

    Failsafe: if analytics.json is missing or empty, returns the default
    cluster rotation order from lanes_config.json.
    """
    analytics = load_analytics()

    if not analytics:
        logger.info("No analytics data — using default lane rotation")
        return _default_lane_order()

    scored: list[tuple[str, float]] = []
    for lane, data in analytics.items():
        score = calculate_lane_score(data)
        scored.append((lane, score))

    # Sort by score descending
    scored.sort(key=lambda x: x[1], reverse=True)

    ranked = [lane for lane, _ in scored]

    # Ensure all known lanes are included (even if not in analytics)
    all_lanes = _default_lane_order()
    for lane in all_lanes:
        if lane not in ranked:
            ranked.append(lane)

    return ranked


def get_optimization_report() -> dict[str, Any]:
    """Full optimization report for the frontend / logging.

    Returns:
    {
        "ranked_lanes": ["lunch", "breakfast", "dinner"],
        "scores": {"lunch": 1640.0, "breakfast": 853.33, "dinner": 841.0},
        "analytics": {... raw data ...},
        "has_data": True,
        "optimized_at": "2026-03-09T..."
    }
    """
    analytics = load_analytics()
    scores    = get_lane_scores()
    ranked    = get_lane_priority()

    return {
        "ranked_lanes":  ranked,
        "scores":        scores,
        "analytics":     analytics,
        "has_data":      bool(analytics),
        "optimized_at":  datetime.now(timezone.utc).isoformat(),
    }


# ── Analytics refresh (build from uploads log + metadata) ────────────────────

def refresh_analytics_from_logs() -> dict[str, dict[str, Any]]:
    """Rebuild analytics.json from uploads_log.json + metadata.

    Counts videos per lane and uses any view/CTR data available.
    This is a lightweight rebuild — full view data comes from YouTube API.
    """
    uploads = _load_json(UPLOADS_LOG)
    if not uploads:
        logger.warning("No uploads_log.json data — cannot refresh analytics")
        return {}

    lane_stats: dict[str, dict[str, Any]] = {}

    for stem, info in uploads.items():
        # Determine lane from metadata
        meta = _load_json(META_DIR / f"{stem}.json")
        lane = meta.get("lane", "")

        # If no lane tag, try to infer from artist
        if not lane:
            artist = (meta.get("artist", "") or "").lower()
            cfg = _load_json(LANES_CFG)
            lanes_cfg = cfg.get("lanes", {})
            for lane_key, lane_data in lanes_cfg.items():
                lane_artists = [a.lower() for a in lane_data.get("artists", [])]
                if artist in lane_artists:
                    lane = lane_key
                    break

        if not lane:
            lane = "unassigned"

        if lane not in lane_stats:
            lane_stats[lane] = {"videos": 0, "views": 0, "ctr": 0.0}

        lane_stats[lane]["videos"] += 1

        # Pull view count if available (from YouTube API data)
        views = info.get("views", 0) or info.get("viewCount", 0)
        lane_stats[lane]["views"] += int(views)

    # Calculate average CTR per lane (if we have impression data)
    for lane, stats in lane_stats.items():
        impressions = stats.get("impressions", 0)
        if impressions > 0 and stats["views"] > 0:
            stats["ctr"] = round((stats["views"] / impressions) * 100, 1)
        elif stats["videos"] > 0:
            # Estimate CTR from views-per-video ratio
            avg_views = stats["views"] / stats["videos"]
            if avg_views > 200:
                stats["ctr"] = 8.0
            elif avg_views > 100:
                stats["ctr"] = 6.5
            elif avg_views > 50:
                stats["ctr"] = 5.0
            else:
                stats["ctr"] = 3.5

    # Remove "unassigned" from saved analytics (not a real lane)
    lane_stats.pop("unassigned", None)

    save_analytics(lane_stats)
    logger.info("Analytics refreshed: %s", {k: v["videos"] for k, v in lane_stats.items()})
    return lane_stats


# ── Pretty print ─────────────────────────────────────────────────────────────

def _print_optimization(verbose: bool = False):
    """Print daily optimization results."""
    report = get_optimization_report()

    print()
    print("=" * 50)
    print("  Lane Optimization Results")
    print("=" * 50)

    for i, lane in enumerate(report["ranked_lanes"], 1):
        score = report["scores"].get(lane, 0)
        print(f"  {i}. {lane}" + (f"  (score: {score})" if verbose else ""))

    if verbose and report["analytics"]:
        print()
        print("  Analytics breakdown:")
        for lane, data in report["analytics"].items():
            print(f"    {lane}: {data.get('videos', 0)} videos, "
                  f"{data.get('views', 0)} views, "
                  f"{data.get('ctr', 0)}% CTR")

    if not report["has_data"]:
        print()
        print("  ⚠  No analytics data — using default rotation")
        print("  Run: python lane_optimizer.py --refresh")

    print("=" * 50)
    print()


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    import argparse
    ap = argparse.ArgumentParser(description="FY3 Lane Optimizer")
    ap.add_argument("--refresh", action="store_true",
                    help="Rebuild analytics.json from uploads log")
    ap.add_argument("--verbose", "-v", action="store_true",
                    help="Show full score breakdown")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.refresh:
        stats = refresh_analytics_from_logs()
        if stats:
            print(f"Analytics refreshed: {len(stats)} lanes")
        else:
            print("No data to refresh")

    _print_optimization(verbose=args.verbose)


if __name__ == "__main__":
    main()
