"""
/api/stores — Airbit & BeatStars store management endpoints.

Manages store credentials, per-beat listings, default pricing,
and uploads to external beat-selling platforms.
"""

from __future__ import annotations

import asyncio
import logging
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.services.beat_svc import safe_stem
from app.backend.services import store_svc
from app.backend.ws import manager, tracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/stores", tags=["stores"])


# ── Request models ───────────────────────────────────────────────────────


class StoreCredentialsRequest(BaseModel):
    email: str = ""
    api_key: str = ""
    store_url: str = ""


class PricingRequest(BaseModel):
    basic_license: float = 29.99
    premium_license: float = 49.99
    exclusive_license: float = 299.99
    currency: str = "USD"


class ListingRequest(BaseModel):
    title: str = ""
    description: str = ""
    tags: list[str] = []
    bpm: int = 0
    key: str = ""
    genre: str = ""
    mood: str = ""
    pricing: Optional[dict[str, float]] = None
    platforms: Optional[dict[str, Any]] = None


class BulkUploadRequest(BaseModel):
    stems: list[str]


# ── Credential Endpoints ────────────────────────────────────────────────


@router.get("/credentials/{platform}")
async def get_credentials(platform: str, user: UserContext = Depends(get_current_user)):
    """Get store connection status (secrets are masked)."""
    if platform not in store_svc.VALID_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

    creds = store_svc.get_store_credentials(platform)
    if not creds:
        return {"connected": False, "email": "", "store_url": "", "platform": platform}

    return {
        "connected": True,
        "email": creds.get("email", ""),
        "api_key_set": bool(creds.get("api_key")),
        "store_url": creds.get("store_url", ""),
        "connected_at": creds.get("connected_at"),
        "platform": platform,
    }


@router.post("/credentials/{platform}")
async def save_credentials(
    platform: str,
    req: StoreCredentialsRequest,
    user: UserContext = Depends(get_current_user),
):
    """Save store credentials."""
    if platform not in store_svc.VALID_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

    if not req.api_key and not req.email:
        raise HTTPException(status_code=400, detail="Email or API key required")

    store_svc.save_store_credentials(platform, req.model_dump())
    return {"status": "saved", "platform": platform}


@router.delete("/credentials/{platform}")
async def disconnect_store(platform: str, user: UserContext = Depends(get_current_user)):
    """Disconnect a store (remove credentials)."""
    if platform not in store_svc.VALID_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

    store_svc.remove_store_credentials(platform)
    return {"status": "disconnected", "platform": platform}


# ── Pricing Endpoints ───────────────────────────────────────────────────


@router.get("/pricing")
async def get_pricing(user: UserContext = Depends(get_current_user)):
    """Get default pricing configuration."""
    return store_svc.get_default_pricing()


@router.put("/pricing")
async def update_pricing(req: PricingRequest, user: UserContext = Depends(get_current_user)):
    """Update default pricing."""
    store_svc.save_default_pricing(req.model_dump())
    return {"status": "saved", "pricing": store_svc.get_default_pricing()}


# ── Listing Endpoints ───────────────────────────────────────────────────


@router.get("/listings")
async def get_all_listings(user: UserContext = Depends(get_current_user)):
    """Get all beat listings with platform status."""
    paths = get_user_paths(user)
    listings = store_svc.get_all_listings(
        paths.listings_dir,
        paths.metadata_dir,
        paths.beats_dir,
    )

    # Enrich with store upload log data
    upload_log = store_svc.load_store_uploads(paths.store_uploads_log)
    for listing in listings:
        stem = listing.get("stem", "")
        if stem in upload_log:
            for platform in store_svc.VALID_PLATFORMS:
                if platform in upload_log[stem]:
                    entry = upload_log[stem][platform]
                    listing["platforms"][platform] = {
                        "listed": True,
                        "listing_id": entry.get("listing_id"),
                        "uploaded_at": entry.get("uploaded_at"),
                        "url": entry.get("url"),
                    }

    return {
        "listings": listings,
        "total": len(listings),
        "genres": store_svc.GENRES,
        "moods": store_svc.MOODS,
        "keys": store_svc.KEYS,
    }


@router.get("/listings/{stem}")
async def get_listing(stem: str, user: UserContext = Depends(get_current_user)):
    """Get a single listing (auto-populated from metadata if new)."""
    paths = get_user_paths(user)
    listing = store_svc.get_listing(paths.listings_dir, paths.metadata_dir, stem)

    # Enrich with upload log
    upload_log = store_svc.load_store_uploads(paths.store_uploads_log)
    if stem in upload_log:
        for platform in store_svc.VALID_PLATFORMS:
            if platform in upload_log[stem]:
                entry = upload_log[stem][platform]
                listing["platforms"][platform] = {
                    "listed": True,
                    "listing_id": entry.get("listing_id"),
                    "uploaded_at": entry.get("uploaded_at"),
                    "url": entry.get("url"),
                }

    return listing


@router.put("/listings/{stem}")
async def update_listing(
    stem: str,
    req: ListingRequest,
    user: UserContext = Depends(get_current_user),
):
    """Save/update a listing."""
    paths = get_user_paths(user)
    data = req.model_dump(exclude_none=True)
    listing = store_svc.save_listing(paths.listings_dir, stem, data)
    return listing


# ── Upload Endpoints ────────────────────────────────────────────────────


@router.post("/upload/{platform}/{stem}")
async def upload_to_store(
    platform: str,
    stem: str,
    user: UserContext = Depends(get_current_user),
):
    """Upload a single beat to a platform (runs as background task)."""
    if platform not in store_svc.VALID_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

    creds = store_svc.get_store_credentials(platform)
    if not creds:
        raise HTTPException(status_code=400, detail=f"{platform.title()} not connected")

    paths = get_user_paths(user)

    # Find the audio file
    audio_path = _find_audio(paths.beats_dir, stem)
    if not audio_path:
        raise HTTPException(status_code=404, detail=f"Audio file not found for {stem}")

    # Get the listing
    listing = store_svc.get_listing(paths.listings_dir, paths.metadata_dir, stem)

    # Find thumbnail
    thumb_path = _find_thumbnail(paths.output_dir, paths.beats_dir.parent / "images", stem)

    # Create background task
    task_id = tracker.create(stem, "store_upload", f"{platform.title()}: {listing.get('title', stem)}")

    asyncio.create_task(
        _run_store_upload(
            platform, stem, listing, creds, audio_path, thumb_path,
            task_id, paths.store_uploads_log, paths.listings_dir, user,
        )
    )

    return {"status": "started", "task_id": task_id, "platform": platform}


@router.post("/upload/{platform}/bulk")
async def bulk_upload_to_store(
    platform: str,
    req: BulkUploadRequest,
    user: UserContext = Depends(get_current_user),
):
    """Upload multiple beats to a platform."""
    if platform not in store_svc.VALID_PLATFORMS:
        raise HTTPException(status_code=400, detail=f"Invalid platform: {platform}")

    creds = store_svc.get_store_credentials(platform)
    if not creds:
        raise HTTPException(status_code=400, detail=f"{platform.title()} not connected")

    paths = get_user_paths(user)

    # Airbit uses Selenium — must run as a single browser session, not concurrent tasks
    if platform == "airbit":
        # Create one tracker task per stem for UI progress
        task_ids: dict[str, str] = {}
        for stem in req.stems:
            listing = store_svc.get_listing(paths.listings_dir, paths.metadata_dir, stem)
            tid = tracker.create(stem, "store_upload", f"Airbit: {listing.get('title', stem)}")
            task_ids[stem] = tid

        # Launch single background task for the entire batch
        asyncio.create_task(
            _run_airbit_bulk_upload(req.stems, task_ids, paths, user)
        )

        return {
            "status": "started",
            "tasks": [{"stem": s, "task_id": t} for s, t in task_ids.items()],
            "count": len(task_ids),
        }

    # Other platforms (BeatStars, etc.) — concurrent tasks
    tasks = []
    for stem in req.stems:
        audio_path = _find_audio(paths.beats_dir, stem)
        if not audio_path:
            continue

        listing = store_svc.get_listing(paths.listings_dir, paths.metadata_dir, stem)
        thumb_path = _find_thumbnail(paths.output_dir, paths.beats_dir.parent / "images", stem)

        task_id = tracker.create(stem, "store_upload", f"{platform.title()}: {listing.get('title', stem)}")
        asyncio.create_task(
            _run_store_upload(
                platform, stem, listing, creds, audio_path, thumb_path,
                task_id, paths.store_uploads_log, paths.listings_dir, user,
            )
        )
        tasks.append({"stem": stem, "task_id": task_id})

    return {"status": "started", "tasks": tasks, "count": len(tasks)}


# ── Airbit Bulk Upload ────────────────────────────────────────────────


async def _run_airbit_bulk_upload(
    stems: list[str],
    task_ids: dict[str, str],
    paths,
    user,
):
    """
    Background task: run airbit_upload.py once with all stems.
    Parses stdout signals to update per-beat progress via WebSocket.
    """
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
            # Record in store uploads log
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
        # Mark all as started
        for stem, tid in task_ids.items():
            await manager.send_progress(
                tid, "store_upload", 5,
                "Queued for Airbit upload...",
                username=user.username,
            )

        results = await store_svc.upload_airbit_bulk(stems, progress_callback=_progress)

        # Handle any stems that didn't get a callback
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
        logger.error("Airbit bulk upload error: %s", e, exc_info=True)
        for stem, tid in task_ids.items():
            if not tracker.is_complete(tid):
                tracker.fail(tid, str(e)[:200])
                await manager.send_progress(
                    tid, "store_upload", 0, str(e)[:200],
                    username=user.username,
                )


# ── Helper Functions ────────────────────────────────────────────────────


def _find_audio(beats_dir, stem: str):
    """Find the audio file for a stem."""
    for ext in ("mp3", "wav"):
        for f in beats_dir.glob(f"*.{ext}"):
            if safe_stem(f.name) == stem:
                return f
    return None


def _find_thumbnail(output_dir, images_dir, stem: str):
    """Find thumbnail for a stem."""
    thumb = output_dir / f"{stem}_thumb.jpg"
    if thumb.exists():
        return thumb
    img = images_dir / f"{stem}.jpg"
    if img.exists():
        return img
    return None


async def _run_store_upload(
    platform: str,
    stem: str,
    listing: dict,
    credentials: dict,
    audio_path,
    thumbnail_path,
    task_id: str,
    store_uploads_log,
    listings_dir,
    user: UserContext,
):
    """Background task: upload beat to store with progress tracking."""
    try:
        await manager.send_progress(
            task_id, "store_upload", 10,
            f"Uploading to {platform.title()}...",
            username=user.username,
        )

        tracker.update(task_id, 10, f"Uploading to {platform.title()}...")

        result = await store_svc.upload_to_platform(
            platform, stem, listing, credentials, audio_path, thumbnail_path,
        )

        if result.get("success"):
            # Record in upload log
            store_svc.record_store_upload(
                store_uploads_log,
                stem,
                platform,
                result.get("listing_id"),
                result.get("url"),
            )

            # Update listing platform status
            listing["platforms"][platform] = {
                "listed": True,
                "listing_id": result.get("listing_id"),
                "uploaded_at": result.get("uploaded_at"),
                "url": result.get("url"),
            }
            store_svc.save_listing(listings_dir, stem, listing)

            tracker.update(task_id, 100, f"Listed on {platform.title()}")
            tracker.complete(task_id)
            await manager.send_progress(
                task_id, "store_upload", 100,
                f"Successfully listed on {platform.title()}",
                username=user.username,
            )
        else:
            error = result.get("error", "Upload failed")
            tracker.update(task_id, 0, error)
            tracker.fail(task_id, error)
            await manager.send_progress(
                task_id, "store_upload", 0, error, username=user.username,
            )

    except Exception as e:
        logger.error("Store upload error: %s %s → %s", platform, stem, e)
        tracker.update(task_id, 0, str(e))
        tracker.fail(task_id, str(e))
        await manager.send_progress(
            task_id, "store_upload", 0, str(e), username=user.username,
        )
