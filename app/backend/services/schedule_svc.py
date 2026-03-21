"""
Schedule service — manages the upload queue and scheduling slots.

Shares upload_queue.json with the Telegram bot for unified state.
"""

from __future__ import annotations

import json
import logging
import math
from datetime import datetime, timedelta, timezone, tzinfo
from pathlib import Path
from typing import Any

from app.backend.config import ROOT, UPLOADS_LOG
from app.backend.services.beat_svc import safe_stem, _load_json

logger = logging.getLogger(__name__)

# US Eastern timezone (EST/EDT)
try:
    from zoneinfo import ZoneInfo
    EST = ZoneInfo("America/New_York")
except ImportError:
    # Python < 3.9 fallback
    EST = timezone(timedelta(hours=-5))

QUEUE_FILE = ROOT / "upload_queue.json"

QUEUE_DEFAULTS: dict[str, Any] = {
    "queue": [],
    "settings": {
        "daily_yt_count": 2,
        "yt_times_est": ["11:00", "18:00"],
        "buffer_warning_days": 7,
        "autopilot_enabled": True,
    },
}


def load_queue() -> dict[str, Any]:
    """Load upload_queue.json, merging with defaults."""
    data = _load_json(QUEUE_FILE)
    if not data:
        data = {}
    # Merge defaults
    result = {**QUEUE_DEFAULTS, **data}
    result["settings"] = {**QUEUE_DEFAULTS["settings"], **data.get("settings", {})}
    if not isinstance(result["queue"], list):
        result["queue"] = []
    return result


def save_queue(data: dict[str, Any]) -> None:
    """Persist upload_queue.json to disk."""
    QUEUE_FILE.write_text(json.dumps(data, indent=2))


def get_uploaded_stems(uploads_log_path: Path = UPLOADS_LOG) -> set[str]:
    """Return set of stems already uploaded to YouTube."""
    log = _load_json(uploads_log_path)
    return set(log.keys())


def add_to_queue(
    stems: list[str],
    priority: int = 0,
    uploads_log_path: Path = UPLOADS_LOG,
) -> dict[str, Any]:
    """Add stems to the queue, skipping duplicates and already-uploaded."""
    data = load_queue()
    queue: list[dict[str, Any]] = data["queue"]
    existing = {entry["stem"] for entry in queue}
    uploaded = get_uploaded_stems(uploads_log_path)

    added = []
    skipped = []
    for stem in stems:
        if stem in existing:
            skipped.append(stem)
            continue
        if stem in uploaded:
            skipped.append(stem)
            continue
        queue.append({
            "stem": stem,
            "added_at": datetime.now(timezone.utc).isoformat(),
            "priority": priority,
        })
        existing.add(stem)
        added.append(stem)

    data["queue"] = queue
    save_queue(data)
    return {"added": added, "skipped": skipped, "queue_length": len(queue)}


def remove_from_queue(stem: str) -> dict[str, Any]:
    """Remove a stem from the queue."""
    data = load_queue()
    before = len(data["queue"])
    data["queue"] = [e for e in data["queue"] if e["stem"] != stem]
    after = len(data["queue"])
    save_queue(data)
    return {"removed": before > after, "queue_length": after}


def reorder_queue(stems: list[str]) -> dict[str, Any]:
    """Replace queue order entirely. Stems not in the list are dropped."""
    data = load_queue()
    # Build lookup of existing entries
    lookup = {e["stem"]: e for e in data["queue"]}
    new_queue = []
    for stem in stems:
        if stem in lookup:
            new_queue.append(lookup[stem])
        else:
            # New stem added during reorder
            new_queue.append({
                "stem": stem,
                "added_at": datetime.now(timezone.utc).isoformat(),
                "priority": 0,
            })
    data["queue"] = new_queue
    save_queue(data)
    return {"queue_length": len(new_queue)}


def get_next_slots(n: int = 14, start_date: str | None = None) -> list[dict[str, str]]:
    """
    Compute the next N scheduled time slots based on settings.
    Returns list of {"slot": ISO datetime, "stem": stem or null}.

    Args:
        n: Number of slots to generate
        start_date: Optional "YYYY-MM-DD" to start from (defaults to today)
    """
    data = load_queue()
    settings = data["settings"]
    queue = data["queue"]

    times_est = settings.get("yt_times_est", ["11:00", "18:00"])
    daily_count = settings.get("daily_yt_count", 2)

    # Sort queue by priority (lower = higher priority), then FIFO
    sorted_queue = sorted(queue, key=lambda e: (e.get("priority", 0), e.get("added_at", "")))

    now = datetime.now(EST)

    # If start_date provided, use it as the starting point
    if start_date:
        try:
            from datetime import date as _date
            parts = start_date.split("-")
            start = _date(int(parts[0]), int(parts[1]), int(parts[2]))
            # Create a datetime at start of that day so all slots for that day are included
            now = datetime(start.year, start.month, start.day, 0, 0, 0, tzinfo=EST)
        except (ValueError, IndexError):
            pass  # Fall back to current time

    slots: list[dict[str, str]] = []
    stem_idx = 0

    # Generate slots day by day
    day_offset = 0
    while len(slots) < n:
        day = now.date() + timedelta(days=day_offset)

        for time_str in sorted(times_est):
            if len(slots) >= n:
                break

            try:
                hour, minute = map(int, time_str.split(":"))
            except (ValueError, AttributeError):
                continue

            slot_dt = datetime(
                day.year, day.month, day.day,
                hour, minute, 0,
                tzinfo=EST,
            )

            # Skip past slots
            if slot_dt <= now:
                continue

            # Convert to UTC ISO for YouTube
            slot_utc = slot_dt.astimezone(timezone.utc).isoformat()

            stem = None
            if stem_idx < len(sorted_queue):
                stem = sorted_queue[stem_idx]["stem"]
                stem_idx += 1

            slots.append({
                "slot": slot_utc,
                "slot_est": slot_dt.strftime("%Y-%m-%d %-I:%M %p"),
                "stem": stem,
            })

        day_offset += 1
        if day_offset > 365:
            break  # safety

    return slots


def get_buffer_days() -> float:
    """Calculate how many days of content are queued."""
    data = load_queue()
    queue_len = len(data["queue"])
    daily = data["settings"].get("daily_yt_count", 2)
    if daily <= 0:
        return 0
    return round(queue_len / daily, 1)


def update_settings(new_settings: dict[str, Any]) -> dict[str, Any]:
    """Update schedule settings (partial update)."""
    data = load_queue()
    for key, value in new_settings.items():
        if key in QUEUE_DEFAULTS["settings"]:
            data["settings"][key] = value
    save_queue(data)
    return data["settings"]


def get_full_schedule(uploads_log_path: Path = UPLOADS_LOG) -> dict[str, Any]:
    """Return full schedule state: queue, settings, slots, buffer."""
    data = load_queue()
    slots = get_next_slots(14)
    buffer = get_buffer_days()

    return {
        "queue": data["queue"],
        "settings": data["settings"],
        "slots": slots,
        "buffer_days": buffer,
        "queue_length": len(data["queue"]),
    }
