"""
Persistent background job queue — survives server restarts.

Jobs are stored in jobs_queue.json on disk.  The job_runner.py
background loop picks them up and executes them sequentially.
"""

from __future__ import annotations

import json
import logging
import time
import uuid
from pathlib import Path
from typing import Any, Optional

from app.backend.config import ROOT

logger = logging.getLogger(__name__)

JOBS_FILE = ROOT / "jobs_queue.json"


# ── Job helpers ────────────────────────────────────────────────────────────

def _now_iso() -> str:
    from datetime import datetime, timezone
    return datetime.now(timezone.utc).isoformat()


def load_jobs() -> list[dict[str, Any]]:
    """Read all jobs from disk."""
    try:
        if JOBS_FILE.exists():
            data = json.loads(JOBS_FILE.read_text())
            if isinstance(data, list):
                return data
            # Migrate if someone stored a dict with "jobs" key
            if isinstance(data, dict) and "jobs" in data:
                return data["jobs"]
    except Exception as e:
        logger.error("Failed to load jobs: %s", e)
    return []


def save_jobs(jobs: list[dict[str, Any]]) -> None:
    """Write jobs list to disk (crash-safe)."""
    try:
        tmp = JOBS_FILE.with_suffix(".tmp")
        tmp.write_text(json.dumps(jobs, indent=2, ensure_ascii=False))
        tmp.replace(JOBS_FILE)
    except Exception as e:
        logger.error("Failed to save jobs: %s", e)


def _make_job(
    job_type: str,
    stems: list[str],
    params: dict[str, Any] | None = None,
    label: str = "",
) -> dict[str, Any]:
    """Create a single job dict."""
    return {
        "id": f"job_{uuid.uuid4().hex[:10]}",
        "type": job_type,
        "stems": stems,
        "params": params or {},
        "label": label or f"{job_type} ({len(stems)} beat{'s' if len(stems) != 1 else ''})",
        "status": "queued",
        "progress": 0,
        "detail": "",
        "created_at": _now_iso(),
        "started_at": None,
        "finished_at": None,
        "error": None,
        "result": None,
    }


# ── Public API ─────────────────────────────────────────────────────────────

def add_job(
    job_type: str,
    stems: list[str],
    params: dict[str, Any] | None = None,
    label: str = "",
) -> str:
    """Add a single job to the queue.  Returns the job ID."""
    jobs = load_jobs()
    job = _make_job(job_type, stems, params, label)
    jobs.append(job)
    save_jobs(jobs)
    logger.info("Job added: %s (%s, %d stems)", job["id"], job_type, len(stems))
    return job["id"]


def add_pipeline_jobs(
    steps: list[str],
    stems: list[str],
    params: dict[str, Any] | None = None,
) -> list[str]:
    """
    Create one job per pipeline step, all sharing the same stems/params.
    Returns list of job IDs in execution order.
    """
    jobs = load_jobs()
    ids: list[str] = []

    step_labels = {
        "seo": "Generate SEO",
        "render": "Render 16:9",
        "upload": "Upload YouTube",
        "convert": "Convert 9:16",
        "compress": "Compress",
        "shorts": "YouTube Shorts",
        "tiktok": "TikTok",
        "instagram": "Instagram Reel",
        "airbit": "Upload Airbit",
        "beatstars": "Upload BeatStars",
        "thumbnail": "AI Thumbnails",
        "schedule": "Schedule Upload",
        "social": "Social Upload",
    }

    for step in steps:
        label = step_labels.get(step, step.title())
        job = _make_job(step, stems, params, f"{label} ({len(stems)} beats)")
        jobs.append(job)
        ids.append(job["id"])

    save_jobs(jobs)
    logger.info("Pipeline submitted: %d steps, %d stems", len(steps), len(stems))
    return ids


def get_job(job_id: str) -> dict[str, Any] | None:
    """Get a single job by ID."""
    for job in load_jobs():
        if job["id"] == job_id:
            return job
    return None


def cancel_job(job_id: str) -> bool:
    """Cancel a queued or running job."""
    jobs = load_jobs()
    for job in jobs:
        if job["id"] == job_id and job["status"] in ("queued", "running"):
            job["status"] = "cancelled"
            job["finished_at"] = _now_iso()
            job["detail"] = "Cancelled by user"
            save_jobs(jobs)
            logger.info("Job cancelled: %s", job_id)
            return True
    return False


def get_queue_status() -> dict[str, Any]:
    """Return summary + full job list."""
    jobs = load_jobs()
    queued = [j for j in jobs if j["status"] == "queued"]
    running = [j for j in jobs if j["status"] == "running"]
    done = [j for j in jobs if j["status"] == "done"]
    failed = [j for j in jobs if j["status"] == "failed"]
    cancelled = [j for j in jobs if j["status"] == "cancelled"]

    return {
        "queued": len(queued),
        "running": len(running),
        "done": len(done),
        "failed": len(failed),
        "cancelled": len(cancelled),
        "total": len(jobs),
        "jobs": jobs,
    }


def clear_completed() -> int:
    """Remove done/failed/cancelled jobs.  Returns count removed."""
    jobs = load_jobs()
    before = len(jobs)
    jobs = [j for j in jobs if j["status"] in ("queued", "running")]
    save_jobs(jobs)
    removed = before - len(jobs)
    logger.info("Cleared %d completed jobs", removed)
    return removed


def next_queued() -> dict[str, Any] | None:
    """Return the first job with status='queued', or None."""
    for job in load_jobs():
        if job["status"] == "queued":
            return job
    return None


def update_job(job_id: str, **updates: Any) -> None:
    """Update fields on a job in-place and save."""
    jobs = load_jobs()
    for job in jobs:
        if job["id"] == job_id:
            job.update(updates)
            break
    save_jobs(jobs)


def recover_stale_running() -> int:
    """
    On startup, reset any jobs stuck in 'running' back to 'queued'.
    This handles the case where the server crashed mid-job.
    """
    jobs = load_jobs()
    recovered = 0
    for job in jobs:
        if job["status"] == "running":
            job["status"] = "queued"
            job["started_at"] = None
            job["progress"] = 0
            job["detail"] = "Recovered after restart"
            recovered += 1
    if recovered:
        save_jobs(jobs)
        logger.info("Recovered %d stale running jobs", recovered)
    return recovered
