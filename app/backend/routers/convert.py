"""
/api/convert — Social media dimension conversion endpoints.

Convert rendered 16:9 videos to platform-specific aspect ratios:
  9x16 (TikTok/Reels/Shorts), 4x5 (IG Feed), 1x1 (IG Square/X).

All conversions run as background tasks with WebSocket progress.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.services import convert_svc
from app.backend.ws import manager, tracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/convert", tags=["convert"])


class ConvertRequest(BaseModel):
    presets: list[str]  # e.g. ["9x16", "4x5", "1x1"]


class BulkConvertRequest(BaseModel):
    stems: list[str]
    presets: list[str]


# ── GET /presets ─────────────────────────────────────────────────────────


@router.get("/presets")
async def list_presets(user: UserContext = Depends(get_current_user)):
    """List available dimension conversion presets."""
    return {
        key: {
            "width": p["width"],
            "height": p["height"],
            "label": p["label"],
            "platforms": p["platforms"],
        }
        for key, p in convert_svc.DIMENSION_PRESETS.items()
    }


# ── GET /status/{stem} ──────────────────────────────────────────────────


@router.get("/status/{stem}")
async def get_status(stem: str, user: UserContext = Depends(get_current_user)):
    """Check which dimension variants exist for a beat."""
    paths = get_user_paths(user)
    return convert_svc.get_dimension_status(stem, paths.output_dir)


# ── POST /{stem} ─────────────────────────────────────────────────────────


@router.post("/{stem}")
async def convert_beat(
    stem: str,
    body: ConvertRequest,
    user: UserContext = Depends(get_current_user),
):
    """Convert a rendered beat to one or more social media dimension presets."""
    paths = get_user_paths(user)
    source = paths.output_dir / f"{stem}.mp4"

    if not source.exists():
        raise HTTPException(status_code=404, detail=f"Rendered video not found: {stem}.mp4")

    # Validate presets
    valid_presets = []
    for p in body.presets:
        if p not in convert_svc.DIMENSION_PRESETS:
            raise HTTPException(status_code=400, detail=f"Invalid preset: {p}")
        valid_presets.append(p)

    if not valid_presets:
        raise HTTPException(status_code=400, detail="No valid presets provided")

    task_id = tracker.create(stem, "convert", f"Convert {stem} ({len(valid_presets)} presets)")

    asyncio.create_task(
        _run_convert_task(task_id, stem, paths.output_dir, paths.brand_dir, valid_presets, user.username)
    )

    return {
        "status": "started",
        "task_id": task_id,
        "stem": stem,
        "presets": valid_presets,
    }


# ── POST /bulk ───────────────────────────────────────────────────────────


@router.post("/bulk")
async def convert_bulk(
    body: BulkConvertRequest,
    user: UserContext = Depends(get_current_user),
):
    """Batch convert multiple beats to social media dimensions."""
    paths = get_user_paths(user)

    # Validate presets
    for p in body.presets:
        if p not in convert_svc.DIMENSION_PRESETS:
            raise HTTPException(status_code=400, detail=f"Invalid preset: {p}")

    # Validate stems
    valid_stems = []
    skipped = []
    for stem in body.stems:
        source = paths.output_dir / f"{stem}.mp4"
        if source.exists():
            valid_stems.append(stem)
        else:
            skipped.append({"stem": stem, "reason": "Rendered video not found"})

    if not valid_stems:
        raise HTTPException(status_code=404, detail="No valid rendered videos found")

    task_id = tracker.create(
        "bulk", "convert_bulk",
        f"Convert {len(valid_stems)} beats × {len(body.presets)} presets"
    )

    asyncio.create_task(
        _run_bulk_convert_task(
            task_id, valid_stems, paths.output_dir, paths.brand_dir,
            body.presets, user.username,
        )
    )

    return {
        "status": "started",
        "task_id": task_id,
        "count": len(valid_stems),
        "presets": body.presets,
        "skipped": skipped,
    }


# ── Background tasks ────────────────────────────────────────────────────


async def _run_convert_task(
    task_id: str,
    stem: str,
    output_dir,
    brand_dir,
    presets: list[str],
    username: str,
):
    """Background: convert a single beat to multiple presets sequentially."""
    total = len(presets)
    completed_presets = []

    try:
        for i, preset_key in enumerate(presets):
            preset = convert_svc.DIMENSION_PRESETS[preset_key]
            source = output_dir / f"{stem}.mp4"
            output = output_dir / f"{stem}{preset['suffix']}.mp4"

            base_pct = int((i / total) * 100)
            step_pct = int(100 / total)

            detail = f"Converting {preset['label']} ({i+1}/{total})..."
            tracker.update(task_id, base_pct, detail)
            await manager.send_progress(
                task_id, "convert", base_pct, detail, username=username,
            )

            async def on_progress(pct: int, detail: str, _base=base_pct, _step=step_pct):
                mapped = _base + int(pct / 100 * _step)
                await manager.send_progress(
                    task_id, "convert", mapped, detail, username=username,
                )

            result = await convert_svc.convert_dimension(
                source=source,
                output=output,
                width=preset["width"],
                height=preset["height"],
                brand_dir=brand_dir,
                progress_cb=on_progress,
            )

            completed_presets.append(preset_key)
            logger.info("Converted %s to %s: %.1fMB", stem, preset_key, result["size_mb"])

        detail = f"Done: {len(completed_presets)}/{total} presets converted"
        tracker.update(task_id, 100, detail)
        tracker.complete(task_id)

        await manager.send_progress(task_id, "convert", 100, detail, username=username)
        await manager.broadcast({
            "type": "convert_complete",
            "stem": stem,
            "presets_completed": completed_presets,
        }, username=username)

    except Exception as e:
        logger.error("Conversion failed for %s: %s", stem, e)
        tracker.fail(task_id, str(e)[:200])
        await manager.send_progress(task_id, "convert", 0, str(e)[:200], username=username)


async def _run_bulk_convert_task(
    task_id: str,
    stems: list[str],
    output_dir,
    brand_dir,
    presets: list[str],
    username: str,
):
    """Background: convert multiple beats to multiple presets."""
    total_ops = len(stems) * len(presets)
    completed = 0
    failed = []

    try:
        for si, stem in enumerate(stems):
            for pi, preset_key in enumerate(presets):
                preset = convert_svc.DIMENSION_PRESETS[preset_key]
                source = output_dir / f"{stem}.mp4"
                output = output_dir / f"{stem}{preset['suffix']}.mp4"

                op_idx = si * len(presets) + pi
                base_pct = int((op_idx / total_ops) * 100)

                detail = f"{stem} → {preset['label']} ({op_idx+1}/{total_ops})"
                tracker.update(task_id, base_pct, detail)
                await manager.send_progress(
                    task_id, "convert_bulk", base_pct, detail, username=username,
                )

                try:
                    await convert_svc.convert_dimension(
                        source=source,
                        output=output,
                        width=preset["width"],
                        height=preset["height"],
                        brand_dir=brand_dir,
                    )
                    completed += 1
                except Exception as e:
                    logger.error("Bulk convert failed %s/%s: %s", stem, preset_key, e)
                    failed.append({"stem": stem, "preset": preset_key, "error": str(e)[:200]})

        detail = f"Done: {completed}/{total_ops} conversions"
        if failed:
            detail += f", {len(failed)} failed"

        tracker.update(task_id, 100, detail)
        tracker.complete(task_id)
        await manager.send_progress(task_id, "convert_bulk", 100, detail, username=username)
        await manager.broadcast({
            "type": "convert_bulk_complete",
            "completed": completed,
            "failed": len(failed),
            "total": total_ops,
        }, username=username)

    except Exception as e:
        logger.error("Bulk conversion task failed: %s", e)
        tracker.fail(task_id, str(e)[:200])
        await manager.send_progress(task_id, "convert_bulk", 0, str(e)[:200], username=username)
