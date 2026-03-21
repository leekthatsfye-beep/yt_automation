"""
/api/schedule — Upload scheduling and queue management.

Manages the upload queue and schedule settings.
Available to all authenticated users.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.config import PYTHON, ROOT
from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.services import schedule_svc
from app.backend.services.beat_svc import get_beat
from app.backend.ws import manager, tracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/schedule", tags=["schedule"])


# ── Request models ───────────────────────────────────────────────────────

class AddToQueueRequest(BaseModel):
    stems: list[str]
    priority: int = 0


class ReorderQueueRequest(BaseModel):
    stems: list[str]


class UpdateSettingsRequest(BaseModel):
    daily_yt_count: Optional[int] = None
    yt_times_est: Optional[list[str]] = None
    buffer_warning_days: Optional[int] = None
    autopilot_enabled: Optional[bool] = None


class LaunchRequest(BaseModel):
    count: int = 4  # How many to schedule from queue
    start_date: str | None = None  # Optional start date "YYYY-MM-DD" (defaults to today)


class RescheduleRequest(BaseModel):
    video_id: str
    stem: str
    new_time: str  # ISO datetime string


# ── Endpoints ────────────────────────────────────────────────────────────

@router.get("")
async def get_schedule(user: UserContext = Depends(get_current_user)):
    """Get full schedule state: queue, settings, computed slots, buffer days."""
    paths = get_user_paths(user)
    return schedule_svc.get_full_schedule(uploads_log_path=paths.uploads_log)


@router.post("/queue")
async def add_to_queue(
    req: AddToQueueRequest,
    user: UserContext = Depends(get_current_user),
):
    """Add stems to the upload queue."""
    paths = get_user_paths(user)
    result = schedule_svc.add_to_queue(
        stems=req.stems,
        priority=req.priority,
        uploads_log_path=paths.uploads_log,
    )
    return result


@router.delete("/queue/{stem}")
async def remove_from_queue(
    stem: str,
    user: UserContext = Depends(get_current_user),
):
    """Remove a stem from the upload queue."""
    result = schedule_svc.remove_from_queue(stem)
    return result


@router.put("/queue/reorder")
async def reorder_queue(
    req: ReorderQueueRequest,
    user: UserContext = Depends(get_current_user),
):
    """Reorder the upload queue."""
    result = schedule_svc.reorder_queue(req.stems)
    return result


@router.get("/preview")
async def preview_slots(
    count: int = 14,
    user: UserContext = Depends(get_current_user),
):
    """Preview the next N scheduled time slots."""
    slots = schedule_svc.get_next_slots(n=count)
    buffer = schedule_svc.get_buffer_days()
    return {"slots": slots, "buffer_days": buffer}


@router.post("/launch")
async def launch_schedule(
    req: LaunchRequest,
    user: UserContext = Depends(get_current_user),
):
    """
    Schedule the next N queued beats for upload at their computed time slots.
    Actually triggers upload.py --schedule-at for each one.
    """
    paths = get_user_paths(user)
    slots = schedule_svc.get_next_slots(n=req.count, start_date=req.start_date)

    results = []
    for slot in slots:
        stem = slot.get("stem")
        if not stem:
            continue  # Empty slot

        scheduled_at = slot["slot"]

        # Verify beat exists and is rendered
        beat = get_beat(
            stem,
            beats_dir=paths.beats_dir,
            metadata_dir=paths.metadata_dir,
            output_dir=paths.output_dir,
            uploads_log_path=paths.uploads_log,
            social_log_path=paths.social_log,
        )
        if not beat or not beat.get("rendered"):
            results.append({
                "stem": stem,
                "status": "skipped",
                "reason": "Not found or not rendered",
            })
            continue

        # Create tracker task
        task_id = tracker.create(stem, "upload", beat.get("title", stem))
        await manager.send_progress(
            task_id, "upload", 0,
            f"Scheduling {stem} for {slot.get('slot_est', scheduled_at)}...",
            username=user.username,
        )

        # Run upload.py with --schedule-at
        cmd = [
            PYTHON,
            str(ROOT / "upload.py"),
            "--only", stem,
            "--schedule-at", scheduled_at,
        ]

        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ROOT),
            )

            pct = 10
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if not text:
                    continue

                logger.info("schedule upload.py: %s", text)

                if "Uploading" in text:
                    pct = 40
                    tracker.update(task_id, pct, f"Uploading {stem}...")
                    await manager.send_progress(
                        task_id, "upload", pct,
                        f"Uploading {stem}...",
                        username=user.username,
                    )
                elif "Upload complete" in text or "SUCCESS" in text.upper():
                    pct = 90
                    tracker.update(task_id, pct, "Scheduled!")
                    await manager.send_progress(
                        task_id, "upload", pct, "Scheduled!",
                        username=user.username,
                    )
                elif "Scheduled" in text:
                    pct = 90
                    tracker.update(task_id, pct, text)
                    await manager.send_progress(
                        task_id, "upload", pct, text,
                        username=user.username,
                    )

            await proc.wait()
            stderr_text = (await proc.stderr.read()).decode(errors="replace")

            if proc.returncode != 0:
                logger.error("schedule upload failed for %s: %s", stem, stderr_text)
                tracker.fail(task_id, f"Error: {stderr_text[:200]}")
                await manager.send_progress(
                    task_id, "upload", pct,
                    f"Error: {stderr_text[:200]}",
                    username=user.username,
                )
                results.append({
                    "stem": stem,
                    "status": "error",
                    "reason": stderr_text[:200],
                })
                continue

            tracker.complete(task_id)
            await manager.send_progress(
                task_id, "upload", 100, "Scheduled!",
                username=user.username,
            )

            # Remove from queue on success
            schedule_svc.remove_from_queue(stem)

            # Read upload info
            upload_info = {}
            try:
                if paths.uploads_log.exists():
                    log = json.loads(paths.uploads_log.read_text())
                    upload_info = log.get(stem, {})
            except Exception:
                pass

            results.append({
                "stem": stem,
                "status": "scheduled",
                "scheduledAt": scheduled_at,
                "slot_est": slot.get("slot_est"),
                "videoId": upload_info.get("videoId"),
                "url": upload_info.get("url"),
            })

        except Exception as e:
            logger.error("Failed to schedule %s: %s", stem, e)
            results.append({
                "stem": stem,
                "status": "error",
                "reason": str(e)[:200],
            })

    return {
        "results": results,
        "scheduled": sum(1 for r in results if r["status"] == "scheduled"),
        "errors": sum(1 for r in results if r["status"] == "error"),
        "skipped": sum(1 for r in results if r["status"] == "skipped"),
    }


@router.put("/settings")
async def update_settings(
    req: UpdateSettingsRequest,
    user: UserContext = Depends(get_current_user),
):
    """Update schedule settings."""
    updates = {}
    if req.daily_yt_count is not None:
        updates["daily_yt_count"] = max(1, min(10, req.daily_yt_count))
    if req.yt_times_est is not None:
        # Validate time format
        valid_times = []
        for t in req.yt_times_est:
            try:
                parts = t.split(":")
                h, m = int(parts[0]), int(parts[1])
                if 0 <= h <= 23 and 0 <= m <= 59:
                    valid_times.append(f"{h:02d}:{m:02d}")
            except (ValueError, IndexError):
                continue
        if valid_times:
            updates["yt_times_est"] = sorted(valid_times)
    if req.buffer_warning_days is not None:
        updates["buffer_warning_days"] = max(1, min(30, req.buffer_warning_days))
    if req.autopilot_enabled is not None:
        updates["autopilot_enabled"] = req.autopilot_enabled

    result = schedule_svc.update_settings(updates)
    return result


# ── YouTube Scheduled Uploads Management ──────────────────────────────────

@router.get("/youtube-scheduled")
async def get_youtube_scheduled(
    user: UserContext = Depends(get_current_user),
):
    """
    Return YouTube uploads that have a future publishAt time.
    These are videos already uploaded to YouTube as private, waiting to go live.
    """
    from datetime import datetime, timezone

    paths = get_user_paths(user)
    uploads: list[dict] = []

    try:
        if paths.uploads_log.exists():
            log = json.loads(paths.uploads_log.read_text())
            now = datetime.now(timezone.utc)

            for stem, info in log.items():
                publish_at = info.get("publishAt")
                if not publish_at:
                    continue

                # Parse the publishAt time
                try:
                    dt = datetime.fromisoformat(publish_at)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                uploads.append({
                    "stem": stem,
                    "videoId": info.get("videoId", ""),
                    "url": info.get("url", ""),
                    "title": info.get("title", stem),
                    "uploadedAt": info.get("uploadedAt", ""),
                    "publishAt": publish_at,
                    "isPast": dt <= now,
                })

            # Sort: future first (by publish time), then past
            uploads.sort(key=lambda u: (u["isPast"], u["publishAt"]))

    except Exception as e:
        logger.error("Failed to read scheduled uploads: %s", e)

    return {"uploads": uploads, "count": len(uploads)}


@router.post("/reschedule")
async def reschedule_video(
    req: RescheduleRequest,
    user: UserContext = Depends(get_current_user),
):
    """
    Update the publishAt time on an existing scheduled YouTube video.
    Also updates the local uploads_log.json to match.
    """
    import sys
    from datetime import datetime, timezone

    paths = get_user_paths(user)

    # Validate new time
    try:
        new_dt = datetime.fromisoformat(req.new_time)
        if new_dt.tzinfo is None:
            try:
                from zoneinfo import ZoneInfo
            except ImportError:
                from backports.zoneinfo import ZoneInfo  # type: ignore
            new_dt = new_dt.replace(tzinfo=ZoneInfo("America/New_York"))
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Invalid datetime: {e}")

    if new_dt <= datetime.now(timezone.utc):
        raise HTTPException(status_code=400, detail="New time must be in the future")

    # Run the reschedule via YouTube API in an executor
    def _do_reschedule():
        sys.path.insert(0, str(ROOT))
        from youtube_auth import get_youtube_service
        from upload import reschedule_video as yt_reschedule

        youtube = get_youtube_service()
        yt_reschedule(youtube, req.video_id, new_dt)

        # Update local log
        try:
            if paths.uploads_log.exists():
                log_data = json.loads(paths.uploads_log.read_text())
                if req.stem in log_data:
                    log_data[req.stem]["publishAt"] = new_dt.isoformat()
                    paths.uploads_log.write_text(
                        json.dumps(log_data, indent=2, ensure_ascii=False, default=str)
                    )
        except Exception as e:
            logger.error("Failed to update uploads_log: %s", e)

    try:
        loop = asyncio.get_event_loop()
        await loop.run_in_executor(None, _do_reschedule)

        return {
            "status": "ok",
            "stem": req.stem,
            "videoId": req.video_id,
            "newPublishAt": new_dt.isoformat(),
        }

    except Exception as e:
        logger.error("Failed to reschedule %s: %s", req.video_id, e)
        raise HTTPException(status_code=500, detail=f"Failed to reschedule: {str(e)[:200]}")
