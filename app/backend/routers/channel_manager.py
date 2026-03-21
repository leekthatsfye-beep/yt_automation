"""
/api/channel — YouTube Channel Manager endpoints.

Scan the channel, detect metadata issues, auto-fix, and generate reports.
Wraps youtube_manager.py for API access.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.config import PYTHON, ROOT, HEALTH_SCAN_LOG
from app.backend.deps import require_admin, UserContext, get_user_paths
from app.backend.ws import manager, tracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/channel", tags=["channel-manager"])

REPORT_PATH = ROOT / "channel_health_report.json"


def _load_json(path):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


# ── GET /report — Latest saved report ────────────────────────────────────────

@router.get("/report")
async def get_channel_report(user: UserContext = Depends(require_admin)):
    """Return the latest saved channel health report."""
    data = _load_json(REPORT_PATH)
    if not data:
        return {"report": None, "message": "No channel scan has been run yet"}
    return {"report": data}


# ── POST /scan — Trigger a channel scan ──────────────────────────────────────

class ScanRequest(BaseModel):
    fix: bool = False
    dry_run: bool = False


@router.post("/scan")
async def trigger_channel_scan(req: ScanRequest, user: UserContext = Depends(require_admin)):
    """Trigger a full channel scan (runs as background task).

    - fix=false (default): scan only, no changes
    - fix=true: scan + auto-fix detected issues
    - dry_run=true: show what would be fixed without applying
    """
    task_label = "Channel scan" if not req.fix else "Channel scan + fix"
    task_id = tracker.create("channel", "channel_scan", task_label)
    await manager.send_progress(task_id, "channel_scan", 0, "Starting channel scan...", username=user.username)

    cmd = [
        PYTHON,
        str(ROOT / "youtube_manager.py"),
    ]
    if req.fix:
        cmd.append("--fix")
    if req.dry_run:
        cmd.append("--dry-run")

    async def _run():
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ROOT),
            )

            pct = 5
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if not text:
                    continue

                logger.info("youtube_manager: %s", text)

                if "[SCAN] Found" in text:
                    pct = 30
                    tracker.update(task_id, pct, text)
                    await manager.send_progress(task_id, "channel_scan", pct, text, username=user.username)
                elif "[DAILY] Scan complete" in text:
                    pct = 60
                    tracker.update(task_id, pct, text)
                    await manager.send_progress(task_id, "channel_scan", pct, text, username=user.username)
                elif "[FIX]" in text:
                    pct = min(pct + 2, 90)
                    tracker.update(task_id, pct, text)
                    await manager.send_progress(task_id, "channel_scan", pct, text, username=user.username)
                elif "[DAILY] Report saved" in text:
                    pct = 95
                    tracker.update(task_id, pct, text)
                    await manager.send_progress(task_id, "channel_scan", pct, text, username=user.username)

            await proc.wait()
            stderr_text = (await proc.stderr.read()).decode(errors="replace")

            if proc.returncode != 0:
                logger.error("youtube_manager failed: %s", stderr_text[:500])
                tracker.fail(task_id, f"Error: {stderr_text[:200]}")
                await manager.send_progress(task_id, "channel_scan", pct, f"Error: {stderr_text[:200]}", username=user.username)
                return

            tracker.complete(task_id)
            await manager.send_progress(task_id, "channel_scan", 100, "Channel scan complete!", username=user.username)

            # Broadcast report to all clients
            report = _load_json(REPORT_PATH)
            if report:
                await manager.broadcast({
                    "type": "channel_scan_complete",
                    "health_score": report.get("channel_health_score", 0),
                    "health_level": report.get("health_level", ""),
                    "total_issues": report.get("issues", {}).get("total", 0),
                    "fixes_applied": report.get("fixes", {}).get("applied", 0),
                })

        except Exception as e:
            logger.error("Channel scan task error: %s", e)
            tracker.fail(task_id, str(e)[:200])
            await manager.send_progress(task_id, "channel_scan", 0, f"Error: {e}", username=user.username)

    asyncio.create_task(_run())

    return {
        "taskId": task_id,
        "status": "started",
        "message": task_label,
    }


# ── GET /issues — Get current issues list ────────────────────────────────────

@router.get("/issues")
async def get_channel_issues(
    severity: Optional[str] = None,
    issue_type: Optional[str] = None,
    user: UserContext = Depends(require_admin),
):
    """Return issues from the latest scan report.

    Optional filters:
        severity: "high", "medium", or "low"
        issue_type: e.g. "missing_purchase_link", "weak_title"
    """
    report = _load_json(REPORT_PATH)
    if not report:
        return {"issues": [], "total": 0, "message": "No scan data available"}

    # The report stores aggregate counts, not individual issues.
    # For detailed issues we need to re-read from a scan.
    # Return the summary for now.
    return {
        "scanned_at": report.get("scanned_at", ""),
        "health_score": report.get("channel_health_score", 0),
        "health_level": report.get("health_level", ""),
        "issues_summary": report.get("issues", {}),
        "fixes": report.get("fixes", {}),
        "top_videos": report.get("top_videos", []),
        "overview": report.get("overview", {}),
    }


# ── GET /quota — Show API quota usage estimate ───────────────────────────────

@router.get("/quota")
async def get_quota_estimate(user: UserContext = Depends(require_admin)):
    """Estimate daily YouTube API quota usage.

    YouTube Data API v3 quota: 10,000 units/day
    - channels.list = 1 unit
    - playlistItems.list = 1 unit per page
    - videos.list = 1 unit per page (50 videos)
    - videos.update = 50 units each
    - videos.insert (upload) = 1600 units each
    """
    report = _load_json(REPORT_PATH)
    total_vids = report.get("overview", {}).get("total_videos", 0)

    # Estimate scan cost
    scan_pages = max(1, (total_vids + 49) // 50)
    scan_cost = 1 + scan_pages + scan_pages  # channels.list + playlistItems + videos.list

    # Estimate fix cost
    fixable = report.get("issues", {}).get("auto_fixable", 0)
    fix_cost = fixable * 50  # videos.update = 50 units each

    return {
        "daily_quota": 10000,
        "scan_cost_estimate": scan_cost,
        "fix_cost_estimate": fix_cost,
        "total_if_scan_and_fix": scan_cost + fix_cost,
        "remaining_for_uploads": 10000 - scan_cost - fix_cost,
        "upload_cost_each": 1600,
        "safe_uploads_remaining": max(0, (10000 - scan_cost - fix_cost) // 1600),
        "total_videos": total_vids,
        "auto_fixable_issues": fixable,
    }
