"""
/api/health — System health scan endpoints.

Provides:
- GET  /api/health/status   — last scan result
- POST /api/health/scan     — trigger immediate scan (background task)
"""

from __future__ import annotations

import asyncio
import logging

from fastapi import APIRouter, Depends

from app.backend.deps import get_current_user, require_admin, UserContext, get_user_paths
from app.backend.services import health_svc
from app.backend.ws import manager, tracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/health", tags=["health"])


@router.get("/status")
async def get_health_status(user: UserContext = Depends(get_current_user)):
    """Return the most recent scan result from disk."""
    result = health_svc.load_scan_result()
    if not result:
        return {
            "last_scan_at": None,
            "health_score": None,
            "health_level": "unknown",
            "total_issues": 0,
            "auto_fixes_applied": 0,
        }
    return result


@router.post("/scan")
async def trigger_scan(user: UserContext = Depends(require_admin)):
    """Trigger an immediate health scan (admin only). Runs as background task."""
    paths = get_user_paths(user)
    task_id = tracker.create("system", "health_scan", "System Health Scan")

    asyncio.create_task(
        _run_scan_task(task_id, paths, user.username)
    )

    return {"status": "started", "task_id": task_id}


async def _run_scan_task(task_id: str, paths, username: str):
    """Background task: run full scan with WebSocket progress."""
    try:
        await manager.send_progress(
            task_id, "health_scan", 10, "Scanning filesystem...", username=username
        )
        tracker.update(task_id, 10, "Scanning filesystem...")

        result = await health_svc.run_full_scan(
            beats_dir=paths.beats_dir,
            metadata_dir=paths.metadata_dir,
            output_dir=paths.output_dir,
            listings_dir=paths.listings_dir,
            uploads_log_path=paths.uploads_log,
        )

        tracker.update(task_id, 100, f"Score: {result['health_score']}")
        tracker.complete(task_id)

        # Broadcast so dashboard widget updates in real-time
        await manager.broadcast(
            {
                "type": "health_scan_complete",
                "health_score": result["health_score"],
                "health_level": result["health_level"],
                "total_issues": result["total_issues"],
                "auto_fixes_applied": result["auto_fixes_applied"],
                "last_scan_at": result["last_scan_at"],
            },
            username=username,
        )

        await manager.send_progress(
            task_id, "health_scan", 100, "Scan complete", username=username
        )

    except Exception as e:
        logger.error("Health scan failed: %s", e)
        tracker.fail(task_id, str(e)[:200])
        await manager.send_progress(
            task_id, "health_scan", 0, str(e)[:200], username=username
        )
