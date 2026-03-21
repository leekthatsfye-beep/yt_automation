"""
/api/store-sync — Beat Store Sync endpoints.

Compare YouTube catalog vs beat stores (Airbit, BeatStars)
and find sync gaps, missing listings, metadata mismatches.
"""

from __future__ import annotations

import logging
import sys
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel

from app.backend.deps import require_admin, UserContext, get_user_paths
from app.backend.services import airbit_sync_svc, store_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/store-sync", tags=["store-sync"])

# Use venv Python for subprocess calls that need packages like
# undetected-chromedriver, selenium, etc. sys.executable may point
# to homebrew Python which doesn't have these installed.
_PROJECT_ROOT = Path(__file__).resolve().parent.parent.parent.parent
_VENV_PYTHON = str(_PROJECT_ROOT / ".venv" / "bin" / "python3.14")
if not Path(_VENV_PYTHON).exists():
    _VENV_PYTHON = sys.executable  # fallback


# ── Request models ─────────────────────────────────────────────────────────

class BulkListRequest(BaseModel):
    stems: list[str]
    platform: str


# ── Endpoints ──────────────────────────────────────────────────────────────

@router.get("/scan")
async def full_sync_scan(
    platform: Optional[str] = Query(None, pattern="^(airbit|beatstars)$"),
    user: UserContext = Depends(require_admin),
):
    """
    Full sync scan — compares YouTube uploads vs store listings.

    Returns per-beat breakdown with platform status, metadata sync status,
    and actionable categories (missing_from_store, needs_update, etc.).

    Optional: filter to a single platform with ?platform=airbit
    """
    paths = get_user_paths(user)
    return airbit_sync_svc.sync_scan(
        paths.uploads_log,
        paths.store_uploads_log,
        paths.beats_dir,
        paths.metadata_dir,
        platform=platform,
    )


@router.get("/status")
async def quick_sync_status(user: UserContext = Depends(require_admin)):
    """
    Lightweight sync status — just counts, no beat details.
    Use this for dashboard widgets and sidebar badges.
    """
    paths = get_user_paths(user)
    return airbit_sync_svc.sync_status(
        paths.uploads_log,
        paths.store_uploads_log,
        paths.beats_dir,
    )


@router.get("/missing/{platform}")
async def get_missing_from_platform(
    platform: str,
    user: UserContext = Depends(require_admin),
):
    """
    Get beats on YouTube but NOT listed on a specific platform.
    These are the ones you should upload to the store.
    """
    if platform not in airbit_sync_svc.PLATFORMS:
        raise HTTPException(400, f"Invalid platform: {platform}")

    paths = get_user_paths(user)
    missing = airbit_sync_svc.get_missing_from_platform(
        paths.uploads_log,
        paths.store_uploads_log,
        paths.beats_dir,
        paths.metadata_dir,
        platform,
    )
    return {
        "platform": platform,
        "platform_info": airbit_sync_svc.PLATFORM_INFO[platform],
        "missing": missing,
        "count": len(missing),
    }


@router.get("/needs-update")
async def get_needs_update(user: UserContext = Depends(require_admin)):
    """
    Get beats with metadata mismatches between YouTube and store.
    """
    paths = get_user_paths(user)
    needs = airbit_sync_svc.get_needs_update(
        paths.uploads_log,
        paths.store_uploads_log,
        paths.beats_dir,
        paths.metadata_dir,
    )
    return {"needs_update": needs, "count": len(needs)}


@router.get("/platforms")
async def get_platforms(user: UserContext = Depends(require_admin)):
    """
    Get available platforms with connection status and stats.
    """
    paths = get_user_paths(user)

    platforms = []
    for p_id in airbit_sync_svc.PLATFORMS:
        info = dict(airbit_sync_svc.PLATFORM_INFO[p_id])
        info["id"] = p_id

        # Connection status
        creds = store_svc.get_store_credentials(p_id)
        info["connected"] = creds is not None
        info["email"] = creds.get("email", "") if creds else ""
        info["api_key_set"] = bool(creds.get("api_key")) if creds else False
        info["store_url"] = creds.get("store_url", "") if creds else ""

        platforms.append(info)

    # Get pricing
    pricing = store_svc.get_default_pricing()

    return {"platforms": platforms, "pricing": pricing}


@router.get("/upload-tasks")
async def get_upload_tasks(user: UserContext = Depends(require_admin)):
    """
    Get active and recent store upload tasks.
    Used by frontend to poll upload progress when WebSocket is unavailable.
    """
    from app.backend.ws import tracker

    active = tracker.get_active()
    completed = tracker.get_completed(limit=50)

    # Filter to store-related tasks (uploads, sync, fix-titles)
    store_types = {"store_upload", "sync_links", "fix_titles"}
    active_store = [t for t in active if t.get("type") in store_types]
    completed_store = [t for t in completed if t.get("type") in store_types]

    total_active = len(active_store)
    total_done = sum(1 for t in completed_store if t.get("status") == "done")
    total_failed = sum(1 for t in completed_store if t.get("status") == "failed")

    return {
        "active": active_store,
        "completed": completed_store,
        "summary": {
            "uploading": total_active,
            "done": total_done,
            "failed": total_failed,
        },
    }


@router.post("/sync-links")
async def sync_purchase_links(
    user: UserContext = Depends(require_admin),
):
    """
    Scrape Airbit Infinity Store for per-beat listing URLs,
    match them to local stems, update store_uploads_log.json,
    then rewrite YouTube descriptions with specific purchase links.

    Runs as a background task (Selenium scraping takes ~30s).
    """
    import asyncio
    import re
    import subprocess
    from app.backend.ws import tracker, manager

    task_id = tracker.create("sync-links", "sync_links", "Syncing Airbit purchase links")

    project_root = str(_PROJECT_ROOT)

    async def _run_sync():
        try:
            await manager.send_progress(
                task_id, "sync_links", 10,
                "Scraping Airbit store for beat URLs...",
                username=user.username,
            )

            # Run the blocking Selenium scrape in a thread
            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    [_VENV_PYTHON, "airbit_upload.py", "--sync-links"],
                    capture_output=True, text=True, cwd=project_root,
                    timeout=180,
                ),
            )

            output = result.stdout + result.stderr
            match_count = 0
            m = re.search(r"Matched (\d+)/", output)
            if m:
                match_count = int(m.group(1))

            tracker.update(task_id, 50, f"Matched {match_count} beats, updating descriptions...")
            await manager.send_progress(
                task_id, "sync_links", 50,
                f"Matched {match_count} beats, updating YouTube descriptions...",
                username=user.username,
            )

            # Now run fix-descriptions to push to YouTube
            result2 = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    [_VENV_PYTHON, "upload.py", "--fix-descriptions"],
                    capture_output=True, text=True, cwd=project_root,
                    timeout=300,
                ),
            )

            output2 = result2.stdout + result2.stderr
            yt_updated = 0
            m = re.search(r"(\d+)/\d+ YouTube descriptions updated", output2)
            if m:
                yt_updated = int(m.group(1))

            detail = f"Synced {match_count} beat links"
            if yt_updated:
                detail += f", updated {yt_updated} YouTube descriptions"

            tracker.update(task_id, 100, detail)
            tracker.complete(task_id)
            await manager.send_progress(
                task_id, "sync_links", 100, detail,
                username=user.username,
            )

        except Exception as e:
            logger.error("sync-links error: %s", e, exc_info=True)
            tracker.fail(task_id, str(e)[:200])
            await manager.send_progress(
                task_id, "sync_links", 0, str(e)[:200],
                username=user.username,
            )

    asyncio.create_task(_run_sync())

    return {
        "status": "started",
        "task_id": task_id,
        "message": "Syncing Airbit purchase links — this takes about a minute",
    }


@router.post("/fix-titles")
async def fix_airbit_titles(
    user: UserContext = Depends(require_admin),
):
    """
    Rename beats on Airbit that have 'Type Beat' in their title.
    Changes 'BiggKutt8 Type Beat - "Army"' to just 'Army'.
    Runs as a background task (Selenium automation).
    """
    import asyncio
    import re
    import subprocess
    from app.backend.ws import tracker, manager

    task_id = tracker.create("fix-titles", "fix_titles", "Fixing Airbit beat titles")

    project_root = str(Path(__file__).resolve().parent.parent.parent.parent)

    async def _run_fix():
        try:
            await manager.send_progress(
                task_id, "fix_titles", 10,
                "Opening Airbit beats management...",
                username=user.username,
            )

            result = await asyncio.get_event_loop().run_in_executor(
                None,
                lambda: subprocess.run(
                    [_VENV_PYTHON, "airbit_upload.py", "--fix-titles"],
                    capture_output=True, text=True, cwd=project_root,
                    timeout=300,
                ),
            )

            output = result.stdout + result.stderr
            m = re.search(r"Renamed (\d+) beat", output)
            count = int(m.group(1)) if m else 0

            detail = f"Renamed {count} beat(s) — titles now use beat name only"
            tracker.update(task_id, 100, detail)
            tracker.complete(task_id)
            await manager.send_progress(
                task_id, "fix_titles", 100, detail,
                username=user.username,
            )

        except Exception as e:
            logger.error("fix-titles error: %s", e, exc_info=True)
            tracker.fail(task_id, str(e)[:200])
            await manager.send_progress(
                task_id, "fix_titles", 0, str(e)[:200],
                username=user.username,
            )

    asyncio.create_task(_run_fix())

    return {
        "status": "started",
        "task_id": task_id,
        "message": "Fixing Airbit titles — removing 'Type Beat' prefix",
    }


@router.post("/bulk-list")
async def bulk_list_on_platform(
    req: BulkListRequest,
    user: UserContext = Depends(require_admin),
):
    """
    Bulk upload/list beats on a platform.
    For Airbit: runs as a single Selenium browser session (background task).
    For others: kicks off store upload for each stem.
    """
    import asyncio
    from app.backend.ws import tracker, manager

    if req.platform not in airbit_sync_svc.PLATFORMS:
        raise HTTPException(400, f"Invalid platform: {req.platform}")

    creds = store_svc.get_store_credentials(req.platform)
    if not creds:
        raise HTTPException(400, f"{req.platform.title()} not connected. Add API credentials first.")

    paths = get_user_paths(user)

    # ── Airbit: single browser session, sequential uploads ──
    if req.platform == "airbit":
        task_ids: dict[str, str] = {}
        for stem in req.stems:
            listing = store_svc.get_listing(paths.listings_dir, paths.metadata_dir, stem)
            tid = tracker.create(stem, "store_upload", f"Airbit: {listing.get('title', stem)}")
            task_ids[stem] = tid

        async def _run_airbit_bulk():
            async def _progress(stem: str, status: str, info: str):
                tid = task_ids.get(stem)
                if not tid:
                    return
                if status == "uploading":
                    tracker.update(tid, 30, f"Uploading to Airbit... ({info})")
                    await manager.send_progress(
                        tid, "store_upload", 30,
                        f"Uploading to Airbit... ({info})",
                        username=user.username,
                    )
                elif status == "done":
                    tracker.update(tid, 100, "Listed on Airbit")
                    tracker.complete(tid)
                    await manager.send_progress(
                        tid, "store_upload", 100,
                        "Successfully listed on Airbit",
                        username=user.username,
                    )
                    store_svc.record_store_upload(
                        paths.store_uploads_log, stem, "airbit", "", "",
                    )
                elif status == "failed":
                    tracker.fail(tid, info)
                    await manager.send_progress(
                        tid, "store_upload", 0, info,
                        username=user.username,
                    )

            try:
                for stem, tid in task_ids.items():
                    await manager.send_progress(
                        tid, "store_upload", 5,
                        "Queued for Airbit upload...",
                        username=user.username,
                    )

                results = await store_svc.upload_airbit_bulk(
                    req.stems, progress_callback=_progress,
                )

                for stem, result in results.items():
                    tid = task_ids.get(stem)
                    if not tid:
                        continue
                    if result.get("success") and not tracker.is_complete(tid):
                        tracker.complete(tid)
                        store_svc.record_store_upload(
                            paths.store_uploads_log, stem, "airbit", "", "",
                        )
                    elif not result.get("success") and not tracker.is_complete(tid):
                        error = result.get("error", "Failed")
                        tracker.fail(tid, error)
                        await manager.send_progress(
                            tid, "store_upload", 0, error,
                            username=user.username,
                        )

            except Exception as e:
                logger.error("Airbit bulk list error: %s", e, exc_info=True)
                for stem, tid in task_ids.items():
                    if not tracker.is_complete(tid):
                        tracker.fail(tid, str(e)[:200])
                        await manager.send_progress(
                            tid, "store_upload", 0, str(e)[:200],
                            username=user.username,
                        )

        asyncio.create_task(_run_airbit_bulk())

        return {
            "platform": req.platform,
            "results": [{"stem": s, "status": "started", "task_id": t} for s, t in task_ids.items()],
            "listed": 0,
            "failed": 0,
            "total": len(req.stems),
            "async": True,
        }

    # ── Other platforms: per-beat sequential uploads ──
    results = []

    for stem in req.stems:
        # Check audio exists
        audio_path = None
        for ext in ("mp3", "wav"):
            for f in paths.beats_dir.glob(f"*.{ext}"):
                from app.backend.services.beat_svc import safe_stem as _ss
                if _ss(f.name) == stem:
                    audio_path = f
                    break
            if audio_path:
                break

        if not audio_path:
            results.append({"stem": stem, "status": "skipped", "reason": "Audio not found"})
            continue

        # Get listing
        listing = store_svc.get_listing(paths.listings_dir, paths.metadata_dir, stem)

        # Find thumbnail
        thumb = paths.output_dir / f"{stem}_thumb.jpg"
        if not thumb.exists():
            thumb = paths.beats_dir.parent / "images" / f"{stem}.jpg"
        thumb_path = thumb if thumb.exists() else None

        try:
            task_id = tracker.create(stem, "store_upload", f"{req.platform.title()}: {listing.get('title', stem)}")
            await manager.send_progress(task_id, "store_upload", 10, f"Uploading to {req.platform.title()}...", username=user.username)

            result = await store_svc.upload_to_platform(
                req.platform, stem, listing, creds, audio_path, thumb_path,
            )

            if result.get("success"):
                store_svc.record_store_upload(
                    paths.store_uploads_log, stem, req.platform,
                    result.get("listing_id"), result.get("url"),
                )
                tracker.complete(task_id)
                results.append({"stem": stem, "status": "listed", "url": result.get("url", "")})
            else:
                tracker.fail(task_id, result.get("error", "Failed"))
                results.append({"stem": stem, "status": "failed", "error": result.get("error", "")})

        except Exception as e:
            logger.error("Bulk list error for %s: %s", stem, e)
            results.append({"stem": stem, "status": "error", "error": str(e)[:200]})

    listed = sum(1 for r in results if r["status"] == "listed")
    failed = sum(1 for r in results if r["status"] in ("failed", "error"))

    return {
        "platform": req.platform,
        "results": results,
        "listed": listed,
        "failed": failed,
        "total": len(req.stems),
    }
