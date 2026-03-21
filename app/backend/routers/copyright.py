"""
/api/copyright — Copyright protection endpoints.
Scan clips for risk, flag/unflag, view status.
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.services import copyright_svc
from app.backend.ws import manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/copyright", tags=["copyright"])

# Track background scan task
_scan_task: asyncio.Task | None = None


class FlagRequest(BaseModel):
    reason: str = ""


async def _run_background_scan(images_dir):
    """Background scan task — sends progress via WebSocket, then sends completion."""
    global _scan_task
    try:
        results = await copyright_svc.scan_all(images_dir=images_dir, ws_manager=manager)

        summary = {
            "total": len(results),
            "safe": sum(1 for r in results if r["risk"] == "safe"),
            "caution": sum(1 for r in results if r["risk"] == "caution"),
            "danger": sum(1 for r in results if r["risk"] == "danger"),
            "flagged": sum(1 for r in results if r["risk"] == "flagged"),
        }

        # Broadcast scan complete to UI
        await manager.broadcast({
            "type": "copyright_scan_complete",
            "summary": summary,
        })

        logger.info("Copyright scan complete: %s", summary)
    except Exception as e:
        logger.error("Background copyright scan failed: %s", e)
        await manager.broadcast({
            "type": "copyright_scan_error",
            "error": str(e)[:200],
        })
    finally:
        _scan_task = None


@router.get("/scan")
async def scan_all_clips(user: UserContext = Depends(get_current_user)):
    """Start a copyright scan of all video clips in images/.

    The scan runs in the background — progress and completion are sent via WebSocket.
    Returns immediately with status info.
    """
    global _scan_task

    if _scan_task and not _scan_task.done():
        return {"status": "already_running", "message": "A scan is already in progress"}

    paths = get_user_paths(user)
    _scan_task = asyncio.create_task(_run_background_scan(paths.images_dir))

    return {"status": "started", "message": "Copyright scan started. Progress will be sent via WebSocket."}


@router.post("/scan/{filename:path}")
async def scan_single_clip(filename: str, user: UserContext = Depends(get_current_user)):
    """Scan a single clip for copyright risk. Filename can include subfolder path."""
    paths = get_user_paths(user)
    clip_path = paths.images_dir / filename
    if not clip_path.exists():
        raise HTTPException(status_code=404, detail=f"Clip not found: {filename}")

    result = await copyright_svc.scan_clip(clip_path, images_dir=paths.images_dir)
    return result


@router.post("/flag/{filename:path}")
async def flag_clip(filename: str, body: FlagRequest, user: UserContext = Depends(get_current_user)):
    """Manually flag a clip as copyrighted. Computes and stores hashes for future matching."""
    paths = get_user_paths(user)
    try:
        result = await copyright_svc.flag_clip(filename, body.reason, images_dir=paths.images_dir)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Clip not found: {filename}")


@router.delete("/flag/{filename:path}")
async def unflag_clip(filename: str, user: UserContext = Depends(get_current_user)):
    """Remove manual copyright flag from a clip."""
    removed = copyright_svc.unflag_clip(filename)
    if not removed:
        raise HTTPException(status_code=404, detail=f"Clip not flagged: {filename}")
    return {"filename": filename, "status": "unflagged"}


@router.get("/flags")
async def get_all_flags(user: UserContext = Depends(get_current_user)):
    """Get all copyright flags and scan results."""
    return copyright_svc.get_flags()


@router.get("/status/{filename:path}")
async def get_clip_status(filename: str, user: UserContext = Depends(get_current_user)):
    """Get copyright risk level for a single clip."""
    return copyright_svc.get_clip_status(filename)
