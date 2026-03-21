"""
/api/jobs — Background Job Queue endpoints.

Submit pipeline work that runs in the background even after closing the browser.
Jobs persist to disk (jobs_queue.json) and survive server restarts.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.deps import require_admin, UserContext
from app.backend.services import jobs_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/jobs", tags=["jobs"])


# ── Request models ─────────────────────────────────────────────────────────

class SubmitPipelineRequest(BaseModel):
    """Submit a batch of pipeline steps to run in background."""
    steps: list[str]  # e.g. ["seo", "render", "upload"]
    stems: list[str]  # beat stems to process
    params: dict = {}  # extra params like {"privacy": "unlisted"}


class SubmitSingleRequest(BaseModel):
    """Submit a single job."""
    type: str  # e.g. "render", "upload", "seo"
    stems: list[str] = []
    params: dict = {}
    label: str = ""


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("")
async def get_all_jobs(user: UserContext = Depends(require_admin)):
    """Get all jobs with status summary."""
    return jobs_svc.get_queue_status()


@router.get("/{job_id}")
async def get_job(job_id: str, user: UserContext = Depends(require_admin)):
    """Get a single job by ID."""
    job = jobs_svc.get_job(job_id)
    if not job:
        raise HTTPException(404, "Job not found")
    return job


@router.post("/submit")
async def submit_pipeline(
    req: SubmitPipelineRequest,
    user: UserContext = Depends(require_admin),
):
    """
    Submit a pipeline batch to run in background.

    Creates one job per step, all executed sequentially.
    Jobs persist to disk and continue running even if you close the browser.

    Example:
        POST /api/jobs/submit
        {"steps": ["seo", "render", "upload"], "stems": ["army", "hood_legend"], "params": {"privacy": "unlisted"}}
    """
    if not req.steps:
        raise HTTPException(400, "At least one step is required")
    if not req.stems:
        raise HTTPException(400, "At least one stem is required")

    # Validate step types
    valid_steps = {"seo", "render", "upload", "convert", "compress", "shorts",
                   "tiktok", "instagram", "airbit", "beatstars", "thumbnail",
                   "schedule", "social"}
    invalid = set(req.steps) - valid_steps
    if invalid:
        raise HTTPException(400, f"Invalid step(s): {', '.join(invalid)}")

    job_ids = jobs_svc.add_pipeline_jobs(req.steps, req.stems, req.params)

    return {
        "submitted": len(job_ids),
        "job_ids": job_ids,
        "steps": req.steps,
        "stems_count": len(req.stems),
        "message": f"Pipeline submitted: {len(req.steps)} steps for {len(req.stems)} beats. Jobs will run in background.",
    }


@router.post("/submit-single")
async def submit_single_job(
    req: SubmitSingleRequest,
    user: UserContext = Depends(require_admin),
):
    """Submit a single background job."""
    valid_types = {"seo", "render", "upload", "convert", "compress", "shorts",
                   "tiktok", "instagram", "airbit", "beatstars", "thumbnail",
                   "schedule", "social"}
    if req.type not in valid_types:
        raise HTTPException(400, f"Invalid job type: {req.type}")

    job_id = jobs_svc.add_job(req.type, req.stems, req.params, req.label)

    return {
        "job_id": job_id,
        "type": req.type,
        "stems_count": len(req.stems),
        "message": f"Job submitted: {req.type}. Will run in background.",
    }


@router.post("/{job_id}/cancel")
async def cancel_job(job_id: str, user: UserContext = Depends(require_admin)):
    """Cancel a queued or running job."""
    success = jobs_svc.cancel_job(job_id)
    if not success:
        raise HTTPException(400, "Job not found or already completed")
    return {"cancelled": True, "job_id": job_id}


@router.post("/clear")
async def clear_completed(user: UserContext = Depends(require_admin)):
    """Clear all completed/failed/cancelled jobs from history."""
    removed = jobs_svc.clear_completed()
    return {"cleared": removed, "message": f"Removed {removed} completed jobs"}
