"""
/api/compress — Social video compression endpoints.

Provides:
- GET  /api/compress/status/{stem}  — file sizes for all variants
- POST /api/compress/{stem}         — compress single video
- POST /api/compress/bulk           — compress multiple videos
"""

from __future__ import annotations

import asyncio
import logging
from typing import Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.services import compress_svc
from app.backend.ws import manager, tracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/compress", tags=["compress"])


class BulkCompressRequest(BaseModel):
    stems: list[str]
    portrait: bool = False


# ── GET /status/{stem} ─────────────────────────────────────────────────────


@router.get("/status/{stem}")
async def get_compress_status(stem: str, user: UserContext = Depends(get_current_user)):
    """Return file sizes for all variants of a beat."""
    paths = get_user_paths(user)
    sizes = compress_svc.get_file_sizes(stem, paths.output_dir)
    status = compress_svc.needs_compression(stem, paths.output_dir)
    return {
        "stem": stem,
        "sizes": sizes,
        "compression_status": status,
    }


# ── POST /{stem} ───────────────────────────────────────────────────────────


@router.post("/{stem}")
async def compress_beat(
    stem: str,
    portrait: bool = False,
    user: UserContext = Depends(get_current_user),
):
    """Compress a single beat video for social upload. Runs as background task."""
    paths = get_user_paths(user)
    variant = "portrait" if portrait else "landscape"

    # Validate source exists
    if portrait:
        source = paths.output_dir / f"{stem}_9x16.mp4"
    else:
        source = paths.output_dir / f"{stem}.mp4"

    if not source.exists():
        raise HTTPException(
            status_code=404,
            detail=f"Source video not found: {source.name}",
        )

    task_id = tracker.create(stem, "compress", f"Compress {stem} ({variant})")

    asyncio.create_task(
        _run_compress_task(task_id, stem, paths.output_dir, portrait, user.username)
    )

    return {"status": "started", "task_id": task_id, "variant": variant}


# ── POST /bulk ─────────────────────────────────────────────────────────────


@router.post("/bulk")
async def compress_bulk(
    body: BulkCompressRequest,
    user: UserContext = Depends(get_current_user),
):
    """Compress multiple beat videos. Each runs as a sequential background task."""
    paths = get_user_paths(user)
    portrait = body.portrait

    # Validate all stems have source videos
    valid_stems: list[str] = []
    skipped: list[dict[str, str]] = []

    for stem in body.stems:
        if portrait:
            source = paths.output_dir / f"{stem}_9x16.mp4"
        else:
            source = paths.output_dir / f"{stem}.mp4"

        if source.exists():
            valid_stems.append(stem)
        else:
            skipped.append({"stem": stem, "reason": f"Source not found: {source.name}"})

    if not valid_stems:
        raise HTTPException(status_code=404, detail="No valid source videos found")

    task_id = tracker.create(
        "bulk", "compress_bulk", f"Bulk compress {len(valid_stems)} videos"
    )

    asyncio.create_task(
        _run_bulk_compress_task(task_id, valid_stems, paths.output_dir, portrait, user.username)
    )

    return {
        "status": "started",
        "task_id": task_id,
        "count": len(valid_stems),
        "skipped": skipped,
    }


# ── Background tasks ──────────────────────────────────────────────────────


async def _run_compress_task(
    task_id: str,
    stem: str,
    output_dir: Any,
    portrait: bool,
    username: str,
):
    """Background task: compress a single video with WebSocket progress."""
    variant = "portrait" if portrait else "landscape"
    try:
        await manager.send_progress(
            task_id, "compress", 5, f"Starting {variant} compression...", username=username
        )
        tracker.update(task_id, 5, f"Starting {variant} compression...")

        async def on_progress(pct: int, detail: str):
            # Map ffmpeg 0-100 to task 10-95
            mapped = 10 + int(pct * 0.85)
            tracker.update(task_id, mapped, detail)
            await manager.send_progress(
                task_id, "compress", mapped, detail, username=username
            )

        result = await compress_svc.compress_stem(
            stem, output_dir, portrait=portrait, on_progress=on_progress
        )

        detail = (
            f"Done: {result['size_before_mb']}MB → {result['size_after_mb']}MB "
            f"({result['reduction_pct']}% smaller)"
        )
        tracker.update(task_id, 100, detail)
        tracker.complete(task_id)

        await manager.send_progress(
            task_id, "compress", 100, detail, username=username
        )

        # Broadcast completion for UI updates
        await manager.broadcast(
            {
                "type": "compress_complete",
                "stem": stem,
                "variant": variant,
                **result,
            },
            username=username,
        )

    except Exception as e:
        logger.error("Compression failed for %s: %s", stem, e)
        tracker.fail(task_id, str(e)[:200])
        await manager.send_progress(
            task_id, "compress", 0, str(e)[:200], username=username
        )


async def _run_bulk_compress_task(
    task_id: str,
    stems: list[str],
    output_dir: Any,
    portrait: bool,
    username: str,
):
    """Background task: compress multiple videos sequentially with progress."""
    total = len(stems)
    completed = 0
    failed: list[dict[str, str]] = []
    total_saved = 0

    try:
        for i, stem in enumerate(stems):
            base_pct = int((i / total) * 100)
            step_pct = int(100 / total)

            tracker.update(
                task_id, base_pct,
                f"Compressing {i+1}/{total}: {stem}..."
            )
            await manager.send_progress(
                task_id, "compress_bulk", base_pct,
                f"Compressing {i+1}/{total}: {stem}...",
                username=username,
            )

            try:
                async def on_progress(pct: int, detail: str, _base=base_pct, _step=step_pct):
                    mapped = _base + int(pct / 100 * _step)
                    await manager.send_progress(
                        task_id, "compress_bulk", mapped, detail, username=username
                    )

                result = await compress_svc.compress_stem(
                    stem, output_dir, portrait=portrait, on_progress=on_progress
                )
                completed += 1
                total_saved += result["size_before"] - result["size_after"]

            except Exception as e:
                logger.error("Bulk compress failed for %s: %s", stem, e)
                failed.append({"stem": stem, "error": str(e)[:200]})

        saved_mb = round(total_saved / (1024 * 1024), 1)
        detail = f"Done: {completed}/{total} compressed, {saved_mb}MB saved"
        if failed:
            detail += f", {len(failed)} failed"

        tracker.update(task_id, 100, detail)
        tracker.complete(task_id)

        await manager.send_progress(
            task_id, "compress_bulk", 100, detail, username=username
        )
        await manager.broadcast(
            {
                "type": "compress_bulk_complete",
                "completed": completed,
                "failed": len(failed),
                "total_saved_mb": saved_mb,
            },
            username=username,
        )

    except Exception as e:
        logger.error("Bulk compression task failed: %s", e)
        tracker.fail(task_id, str(e)[:200])
        await manager.send_progress(
            task_id, "compress_bulk", 0, str(e)[:200], username=username
        )
