"""
/api/organizer — Link Organizer endpoints.

YouTube ↔ Airbit connection dashboard: view link status,
fetch/edit YouTube descriptions, batch-fix purchase links.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.deps import require_admin, UserContext
from app.backend.services import organizer_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/organizer", tags=["organizer"])


# ── Request models ────────────────────────────────────────────────────────

class UpdateDescriptionRequest(BaseModel):
    description: str
    title: str | None = None


# ── Endpoints ─────────────────────────────────────────────────────────────

@router.get("/status")
async def get_link_status(user: UserContext = Depends(require_admin)):
    """
    Full link status for all YouTube uploads.
    Cross-references uploads_log ↔ store_uploads_log ↔ metadata.
    """
    return organizer_svc.get_link_status()


@router.delete("/{stem}")
async def remove_from_list(
    stem: str,
    user: UserContext = Depends(require_admin),
):
    """
    Remove a stem from uploads_log.json only.
    Does NOT delete beat files, rendered media, or metadata.
    """
    result = organizer_svc.remove_from_list(stem)
    if not result.get("success"):
        raise HTTPException(404, result.get("error", "Not found"))
    return result


@router.get("/description/{video_id}")
async def get_youtube_description(
    video_id: str,
    user: UserContext = Depends(require_admin),
):
    """Fetch live YouTube description for a single video."""
    result = organizer_svc.get_youtube_description(video_id)
    if "error" in result and not result.get("title"):
        raise HTTPException(404, result["error"])
    return result


@router.post("/description/{video_id}")
async def update_youtube_description(
    video_id: str,
    req: UpdateDescriptionRequest,
    user: UserContext = Depends(require_admin),
):
    """Update YouTube description (and optionally title) for a video."""
    result = await asyncio.get_event_loop().run_in_executor(
        None,
        lambda: organizer_svc.update_youtube_description(
            video_id, req.description, req.title,
        ),
    )
    if not result.get("success"):
        raise HTTPException(500, result.get("error", "Failed to update"))
    return result


@router.get("/rebuild/{stem}")
async def rebuild_description(
    stem: str,
    user: UserContext = Depends(require_admin),
):
    """
    Preview rebuilt description with correct Airbit link.
    Does NOT push to YouTube — just shows what it would look like.
    """
    result = organizer_svc.rebuild_description(stem)
    if "error" in result:
        raise HTTPException(500, result["error"])
    return result


@router.post("/fix-all")
async def fix_all_links(user: UserContext = Depends(require_admin)):
    """
    Batch fix all missing/profile-only links.
    Rebuilds descriptions with correct Airbit links and pushes to YouTube.
    Runs as background task with per-item WebSocket progress.
    """
    from app.backend.ws import tracker, manager

    task_id = tracker.create("fix-all-links", "fix_links", "Fixing all purchase links")

    async def _run():
        try:
            await manager.send_progress(
                task_id, "fix_links", 5,
                "Scanning for missing/broken links...",
                username=user.username,
            )

            status_data = organizer_svc.get_link_status()
            items_to_fix = [
                item for item in status_data["items"]
                if item["linkStatus"] in ("missing", "profile_only")
            ]
            total = len(items_to_fix)

            if total == 0:
                tracker.update(task_id, 100, "All links are already good!")
                tracker.complete(task_id)
                await manager.send_progress(
                    task_id, "fix_links", 100,
                    "All links are already good!",
                    username=user.username,
                )
                return

            await manager.send_progress(
                task_id, "fix_links", 10,
                f"Found {total} links to fix...",
                username=user.username,
            )

            fixed = 0
            failed = 0
            skipped = 0

            for i, item in enumerate(items_to_fix):
                stem = item["stem"]
                pct = 10 + int(((i + 1) / total) * 85)

                await manager.send_progress(
                    task_id, "fix_links", min(pct, 95),
                    f"Fixing {stem} ({i+1}/{total})...",
                    username=user.username,
                )

                try:
                    result = await asyncio.get_event_loop().run_in_executor(
                        None,
                        lambda s=stem, v=item["videoId"]: organizer_svc.fix_single_link(s, v),
                    )
                    st = result.get("status", "failed")
                    if st == "fixed":
                        fixed += 1
                    elif st == "skipped":
                        skipped += 1
                    else:
                        failed += 1
                except Exception as e:
                    failed += 1
                    logger.error("fix-all: failed on %s: %s", stem, e)

            detail = f"Done: {fixed} fixed"
            if skipped:
                detail += f", {skipped} skipped"
            if failed:
                detail += f", {failed} failed"

            tracker.update(task_id, 100, detail)
            tracker.complete(task_id)
            await manager.send_progress(
                task_id, "fix_links", 100, detail,
                username=user.username,
            )
        except Exception as e:
            logger.error("fix-all-links error: %s", e, exc_info=True)
            tracker.fail(task_id, str(e)[:200])
            await manager.send_progress(
                task_id, "fix_links", 0, str(e)[:200],
                username=user.username,
            )

    asyncio.create_task(_run())

    return {
        "status": "started",
        "task_id": task_id,
        "message": "Fixing all purchase links — progress updates in real time",
    }
