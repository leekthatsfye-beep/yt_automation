"""
/api/youtube — YouTube upload endpoints.
Wraps upload.py subprocess.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.config import PYTHON, ROOT
from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.services.beat_svc import get_beat
from app.backend.ws import manager, tracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/youtube", tags=["youtube"])


class UploadRequest(BaseModel):
    privacy: str = "public"
    scheduleAt: Optional[str] = None


@router.post("/upload/{stem}")
async def upload_beat(stem: str, req: UploadRequest, user: UserContext = Depends(get_current_user)):
    """
    Upload a rendered beat to YouTube via upload.py subprocess.
    """
    paths = get_user_paths(user)
    beat = get_beat(
        stem,
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )
    if beat is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")

    if not beat["rendered"]:
        raise HTTPException(
            status_code=400,
            detail=f"Beat '{stem}' has not been rendered yet",
        )

    if beat.get("uploaded"):
        raise HTTPException(
            status_code=409,
            detail=f"Beat '{stem}' is already uploaded to YouTube",
        )

    video_path = paths.output_dir / f"{stem}.mp4"
    if not video_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Rendered video not found: {stem}.mp4",
        )

    task_id = tracker.create(stem, "upload", beat.get("title", stem))
    await manager.send_progress(task_id, "upload", 0, "Starting upload...", username=user.username)

    cmd = [
        PYTHON,
        str(ROOT / "upload.py"),
        "--only", stem,
    ]

    if req.scheduleAt:
        cmd.extend(["--schedule-at", req.scheduleAt])
    else:
        cmd.extend(["--privacy", req.privacy])

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

        logger.info("upload.py: %s", text)

        if "Uploading" in text:
            pct = 30
            tracker.update(task_id, pct, "Uploading to YouTube...")
            await manager.send_progress(task_id, "upload", pct, "Uploading to YouTube...", username=user.username)
        elif "Upload complete" in text or "SUCCESS" in text.upper():
            pct = 90
            tracker.update(task_id, pct, "Upload complete!")
            await manager.send_progress(task_id, "upload", pct, "Upload complete!", username=user.username)
        elif "Scheduled" in text:
            pct = 90
            tracker.update(task_id, pct, text)
            await manager.send_progress(task_id, "upload", pct, text, username=user.username)

    await proc.wait()
    stderr_text = (await proc.stderr.read()).decode(errors="replace")

    if proc.returncode != 0:
        logger.error("upload.py failed for %s: %s", stem, stderr_text)
        tracker.fail(task_id, f"Error: {stderr_text[:200]}")
        await manager.send_progress(task_id, "upload", pct, f"Error: {stderr_text[:200]}", username=user.username)
        raise HTTPException(
            status_code=500,
            detail=f"Upload failed: {stderr_text[:500]}",
        )

    tracker.complete(task_id)
    await manager.send_progress(task_id, "upload", 100, "Complete!", username=user.username)

    # Read uploads_log to get the video URL
    upload_info = {}
    try:
        if paths.uploads_log.exists():
            log = json.loads(paths.uploads_log.read_text())
            upload_info = log.get(stem, {})
    except Exception:
        pass

    return {
        "stem": stem,
        "taskId": task_id,
        "status": "complete",
        "videoId": upload_info.get("videoId"),
        "url": upload_info.get("url"),
        "publishAt": upload_info.get("publishAt"),
        "message": f"Successfully uploaded {stem}",
    }


@router.get("/uploads")
async def list_uploads(user: UserContext = Depends(get_current_user)):
    """Return all YouTube upload history from uploads_log.json."""
    paths = get_user_paths(user)
    try:
        if paths.uploads_log.exists():
            log = json.loads(paths.uploads_log.read_text())
            uploads = []
            for stem, entry in log.items():
                uploads.append({
                    "stem": stem,
                    "videoId": entry.get("videoId"),
                    "url": entry.get("url"),
                    "uploadedAt": entry.get("uploadedAt"),
                    "title": entry.get("title"),
                    "publishAt": entry.get("publishAt"),
                })
            uploads.sort(
                key=lambda x: x.get("uploadedAt", ""), reverse=True
            )
            return {"uploads": uploads, "count": len(uploads)}
    except Exception as e:
        logger.error("Failed to read uploads log: %s", e)

    return {"uploads": [], "count": 0}
