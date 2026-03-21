"""
Social media schedule service — persistent scheduling for IG, TikTok, and YT Shorts.

Stores scheduled posts in social_schedule.json.  The job_runner checks every
30 seconds for due posts and executes them using the existing upload functions.
"""

from __future__ import annotations

import json
import logging
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.backend.config import ROOT, SOCIAL_LOG
from app.backend.services.beat_svc import _load_json

logger = logging.getLogger(__name__)

SCHEDULE_FILE = ROOT / "social_schedule.json"

VALID_PLATFORMS = {"instagram", "tiktok", "youtube_shorts"}


# ── Helpers ────────────────────────────────────────────────────────────────

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _parse_dt(s: str) -> datetime:
    """Parse an ISO datetime string to a timezone-aware datetime."""
    dt = datetime.fromisoformat(s)
    if dt.tzinfo is None:
        # Assume EST if no timezone provided
        try:
            from zoneinfo import ZoneInfo
        except ImportError:
            from backports.zoneinfo import ZoneInfo  # type: ignore
        dt = dt.replace(tzinfo=ZoneInfo("America/New_York"))
    return dt


# ── Persistence ────────────────────────────────────────────────────────────

def load() -> list[dict[str, Any]]:
    """Read all scheduled posts from disk."""
    try:
        if SCHEDULE_FILE.exists():
            data = json.loads(SCHEDULE_FILE.read_text())
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.error("Failed to load social schedule: %s", e)
    return []


def save(data: list[dict[str, Any]]) -> None:
    """Write schedule to disk (crash-safe atomic write)."""
    try:
        tmp = SCHEDULE_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(data, indent=2, ensure_ascii=False, default=str))
        tmp.replace(SCHEDULE_FILE)
    except Exception as e:
        logger.error("Failed to save social schedule: %s", e)


# ── Public API ─────────────────────────────────────────────────────────────

def get_posted_platforms(
    stem: str,
    social_log_path: Path = SOCIAL_LOG,
) -> list[str]:
    """Return list of platforms a stem has already been successfully posted to."""
    log = _load_json(social_log_path)
    entry = log.get(stem, {})
    if not isinstance(entry, dict):
        return []
    return [
        platform for platform, info in entry.items()
        if isinstance(info, dict) and info.get("status") == "ok"
    ]


def add(
    stem: str,
    platforms: list[str],
    caption: str | None = None,
    privacy: str = "public",
    scheduled_at: str = "",
    social_log_path: Path = SOCIAL_LOG,
) -> dict[str, Any]:
    """
    Add a scheduled social post.  Returns the new entry.

    platforms: subset of {"instagram", "tiktok", "youtube_shorts"}
    scheduled_at: ISO datetime string (with or without timezone)

    The entry includes an `already_posted` list noting which platforms
    were previously posted — the scheduler still allows re-posting, but
    the UI uses this for visibility.
    """
    # Validate platforms
    platforms = [p for p in platforms if p in VALID_PLATFORMS]
    if not platforms:
        raise ValueError("No valid platforms specified")

    # Validate scheduled_at
    if not scheduled_at:
        raise ValueError("scheduled_at is required")
    dt = _parse_dt(scheduled_at)
    if dt <= datetime.now(timezone.utc):
        raise ValueError("scheduled_at must be in the future")

    # Check which platforms are already posted
    already_posted = [
        p for p in platforms
        if p in get_posted_platforms(stem, social_log_path)
    ]

    entry = {
        "id": f"ss_{uuid.uuid4().hex[:10]}",
        "stem": stem,
        "platforms": platforms,
        "caption": caption or "",
        "privacy": privacy,
        "scheduled_at": scheduled_at,
        "created_at": _now_iso(),
        "status": "pending",
        "results": {},
        "already_posted": already_posted,
    }

    data = load()
    data.append(entry)
    save(data)
    logger.info(
        "Social post scheduled: %s → %s at %s%s",
        stem, ", ".join(platforms), scheduled_at,
        f" (already posted: {', '.join(already_posted)})" if already_posted else "",
    )
    return entry


def cancel(post_id: str) -> bool:
    """Cancel a pending scheduled post. Returns True if found and cancelled."""
    data = load()
    for post in data:
        if post["id"] == post_id and post["status"] == "pending":
            post["status"] = "cancelled"
            save(data)
            logger.info("Social post cancelled: %s", post_id)
            return True
    return False


def get_due() -> list[dict[str, Any]]:
    """Return all pending posts whose scheduled_at is in the past (due now)."""
    now = datetime.now(timezone.utc)
    due = []
    for post in load():
        if post["status"] != "pending":
            continue
        try:
            dt = _parse_dt(post["scheduled_at"])
            if dt <= now:
                due.append(post)
        except Exception:
            continue
    return due


def get_all() -> list[dict[str, Any]]:
    """Return all scheduled posts (for UI display), newest first."""
    data = load()
    data.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return data


def get_pending_count() -> int:
    """Return count of pending posts."""
    return sum(1 for p in load() if p["status"] == "pending")


def update(post_id: str, **updates: Any) -> None:
    """Update fields on a scheduled post in-place and save."""
    data = load()
    for post in data:
        if post["id"] == post_id:
            post.update(updates)
            break
    save(data)


def clear_old(days: int = 7) -> int:
    """Remove done/failed/cancelled posts older than N days."""
    from datetime import timedelta

    cutoff = datetime.now(timezone.utc) - timedelta(days=days)
    data = load()
    before = len(data)
    data = [
        p for p in data
        if p["status"] in ("pending", "running")
        or _parse_dt(p.get("created_at", _now_iso())) > cutoff
    ]
    save(data)
    removed = before - len(data)
    if removed:
        logger.info("Cleared %d old scheduled posts", removed)
    return removed
