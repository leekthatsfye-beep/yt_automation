"""
/api/dj — AI DJ endpoints for intelligent beat-to-artist classification.

Provides analyze, results, apply, reject, override, and profiles endpoints.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, BackgroundTasks
from pydantic import BaseModel

from app.backend.deps import require_admin, UserContext, get_user_paths
from app.backend.ws import manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/dj", tags=["dj"])


# ── Request Models ──────────────────────────────────────────────────────

class AnalyzeRequest(BaseModel):
    stems: Optional[list[str]] = None  # None = all unclassified
    force: bool = False                # re-analyze already classified


class ApplyRequest(BaseModel):
    assignments: list[dict]  # [{"stem": "...", "artist": "...", "lane": "..."}]


class RejectRequest(BaseModel):
    stems: list[str]


class OverrideRequest(BaseModel):
    stem: str
    artist: str
    lane: str


# ── GET /results — cached classification results ────────────────────────

@router.get("/results")
async def get_results(user: UserContext = Depends(require_admin)):
    """Return cached DJ classification results."""
    from app.backend.services import dj_svc
    return dj_svc.load_results()


# ── GET /profiles — artist sonic profiles ───────────────────────────────

@router.get("/profiles")
async def get_profiles(user: UserContext = Depends(require_admin)):
    """Return artist sonic profiles used for classification."""
    from app.backend.services import dj_svc
    return dj_svc.load_profiles()


# ── POST /analyze — run DJ analysis ─────────────────────────────────────

@router.post("/analyze")
async def analyze_beats(
    req: AnalyzeRequest,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(require_admin),
):
    """
    Analyze beats for artist classification.
    Runs in background with WebSocket progress updates.
    """
    paths = get_user_paths(user)

    async def run_analysis():
        async def progress_cb(pct: int, detail: str):
            await manager.send_progress(
                task_id="dj_analyze",
                phase="dj_analyze",
                pct=pct,
                detail=detail,
                username=user.username,
            )

        from app.backend.services import dj_svc
        await dj_svc.analyze_batch(
            stems=req.stems,
            metadata_dir=paths.metadata_dir,
            force=req.force,
            progress_callback=progress_cb,
        )

    background_tasks.add_task(run_analysis)

    return {
        "ok": True,
        "message": f"DJ analysis started for {'all beats' if not req.stems else f'{len(req.stems)} beats'}",
    }


# ── POST /apply — apply approved classifications ────────────────────────

@router.post("/apply")
async def apply_classifications(
    req: ApplyRequest,
    user: UserContext = Depends(require_admin),
):
    """Apply approved DJ classifications to beat metadata + regenerate SEO."""
    paths = get_user_paths(user)
    from app.backend.services import dj_svc

    applied = []
    errors = []

    for assignment in req.assignments:
        stem = assignment.get("stem", "")
        artist = assignment.get("artist", "")
        lane = assignment.get("lane", "")

        if not stem or not artist:
            errors.append(f"Missing stem or artist: {assignment}")
            continue

        success = dj_svc.apply_classification(stem, artist, lane, paths.metadata_dir)
        if success:
            applied.append(stem)
        else:
            errors.append(f"Failed to apply: {stem}")

    return {
        "ok": True,
        "applied": applied,
        "errors": errors,
    }


# ── POST /reject — reject classifications ───────────────────────────────

@router.post("/reject")
async def reject_classifications(
    req: RejectRequest,
    user: UserContext = Depends(require_admin),
):
    """Mark classifications as rejected."""
    from app.backend.services import dj_svc

    rejected = []
    for stem in req.stems:
        if dj_svc.reject_classification(stem):
            rejected.append(stem)

    return {"ok": True, "rejected": rejected}


# ── POST /override — override with user choice ──────────────────────────

@router.post("/override")
async def override_classification(
    req: OverrideRequest,
    user: UserContext = Depends(require_admin),
):
    """Override a classification with a user-chosen artist."""
    paths = get_user_paths(user)
    from app.backend.services import dj_svc

    success = dj_svc.override_classification(
        req.stem, req.artist, req.lane, paths.metadata_dir
    )
    if not success:
        raise HTTPException(400, f"Failed to override: {req.stem}")

    return {"ok": True, "stem": req.stem, "artist": req.artist, "lane": req.lane}
