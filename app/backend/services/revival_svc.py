"""
Catalog Revival Engine — find old videos with revival potential.

Scans the YouTube upload history to identify beats that could regain
traffic with updated thumbnails, tags, or playlist placement.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def scan_revival_candidates(
    uploads_log_path: Path,
    metadata_dir: Path,
    min_age_days: int = 0,
    max_age_days: int = 99999,
) -> dict[str, Any]:
    """Scan ENTIRE YouTube beat library for revival candidates.

    Covers every uploaded video by default (min_age=0, no max cap).
    Each video is checked for metadata issues, missing purchase links,
    stale thumbnails, and optimization opportunities.
    """
    uploads_log = _load_json(uploads_log_path)
    now = datetime.now(timezone.utc)

    candidates: list[dict[str, Any]] = []
    too_new: int = 0
    too_old: int = 0
    no_video_id: int = 0

    for stem, info in uploads_log.items():
        video_id = info.get("videoId")
        if not video_id:
            no_video_id += 1
            continue

        uploaded_at = info.get("uploadedAt", "")
        if not uploaded_at:
            continue

        try:
            dt = datetime.fromisoformat(uploaded_at.replace("Z", "+00:00"))
        except (ValueError, TypeError):
            continue

        age_days = (now - dt).days

        if age_days < min_age_days:
            too_new += 1
            continue
        if age_days > max_age_days:
            too_old += 1
            continue

        # Load metadata to check quality
        meta_path = metadata_dir / f"{stem}.json"
        meta = _load_json(meta_path) if meta_path.exists() else {}

        issues: list[str] = []
        actions: list[str] = []

        # Check title format
        title = info.get("title", "")
        if "Type Beat" not in title:
            issues.append("missing_type_beat_title")
            actions.append("update title to Artist Type Beat format")

        # Check tags
        tags = meta.get("tags", [])
        if len(tags) < 5:
            issues.append("low_tag_count")
            actions.append("update tags with current SEO profile")
        elif any("free" in t.lower() for t in tags):
            issues.append("contains_free_tags")
            actions.append("remove free tags from metadata")

        # Check description
        desc = meta.get("description", "")
        if "AIRBIT_LINK" not in desc and "airbit" not in desc.lower():
            issues.append("missing_purchase_link")
            actions.append("update description with purchase link")
        if "prod." not in desc.lower():
            issues.append("missing_producer_credit")
            actions.append("add producer credit to description")

        # Check for lane assignment
        if not meta.get("lane"):
            issues.append("no_lane_assigned")
            actions.append("assign to artist lane")

        # Check SEO artist
        if not meta.get("seo_artist"):
            issues.append("no_seo_artist")
            actions.append("assign SEO artist for tag optimization")

        # Always recommend thumbnail refresh for old videos
        if age_days > 365:
            actions.append("refresh thumbnail")
        actions.append("add to playlist")

        # Revival priority score
        priority = 50
        priority += len(issues) * 10  # More issues = higher priority
        if age_days > 365:
            priority += 10  # Older videos get slight boost
        if "missing_purchase_link" in issues:
            priority += 15  # Missing purchase link is high priority
        priority = min(100, priority)

        candidates.append({
            "stem": stem,
            "title": title,
            "videoId": video_id,
            "url": info.get("url", f"https://youtube.com/watch?v={video_id}"),
            "uploadedAt": uploaded_at,
            "age_days": age_days,
            "issues": issues,
            "actions": actions,
            "priority": priority,
            "lane": meta.get("lane"),
            "seo_artist": meta.get("seo_artist"),
        })

    # Sort by priority (highest first)
    candidates.sort(key=lambda x: x["priority"], reverse=True)

    return {
        "candidates": candidates,
        "summary": {
            "total_scanned": len(uploads_log),
            "revival_candidates": len(candidates),
            "skipped_too_new": too_new,
            "skipped_too_old": too_old,
            "skipped_no_video_id": no_video_id,
            "avg_priority": round(sum(c["priority"] for c in candidates) / max(len(candidates), 1)),
        },
    }


def get_revival_actions(
    stem: str,
    uploads_log_path: Path,
    metadata_dir: Path,
) -> dict[str, Any]:
    """Get specific revival actions for a single beat."""
    result = scan_revival_candidates(uploads_log_path, metadata_dir, min_age_days=0)
    for c in result["candidates"]:
        if c["stem"] == stem:
            return c
    return {"stem": stem, "issues": [], "actions": [], "priority": 0, "message": "Not found in upload log"}
