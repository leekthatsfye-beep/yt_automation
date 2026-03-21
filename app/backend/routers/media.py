"""
/api/media — Media browsing, uploading, and beat assignment endpoints.

Browse available clips/images, upload new media from device (iOS Photos/Files),
and assign specific clips or images to beats before rendering.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File, Form
from pydantic import BaseModel

from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.services import media_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/media", tags=["media"])


class AssignmentRequest(BaseModel):
    clip: Optional[str] = None
    image: Optional[str] = None


# ── GET /artists ─────────────────────────────────────────────────────────


@router.get("/artists")
async def list_artists(user: UserContext = Depends(get_current_user)):
    """List available artist visual folders from images/ directory."""
    paths = get_user_paths(user)
    artists = []
    if paths.images_dir.is_dir():
        for p in sorted(paths.images_dir.iterdir()):
            if p.is_dir() and not p.name.startswith(".") and not p.name.endswith("_thumbs"):
                # Count clips in folder
                clips = list(p.glob("*.mp4"))
                artists.append({
                    "name": p.name,
                    "clips": len(clips),
                    "images": len(list(p.glob("*.jpg"))) + len(list(p.glob("*.png"))),
                })
    return {"artists": artists}


# ── GET /browse ──────────────────────────────────────────────────────────


@router.get("/browse")
async def browse_media(user: UserContext = Depends(get_current_user)):
    """List all available clips and images from images/ and ~/Shared_Clips."""
    paths = get_user_paths(user)
    result = await media_svc.browse_media(paths.images_dir, paths.shared_clips_dir)
    return result


# ── POST /upload ─────────────────────────────────────────────────────────


@router.post("/upload")
async def upload_media(
    file: UploadFile = File(...),
    subfolder: Optional[str] = Form(None),
    user: UserContext = Depends(get_current_user),
):
    """
    Upload a media file (image or video clip) to images/.
    On iOS, <input type="file" accept="image/*,video/*"> opens Photos/Files picker.
    Large files are auto-compressed (videos >100MB or >1920px, images >5MB).
    """
    paths = get_user_paths(user)

    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    try:
        content = await file.read()
    except Exception as e:
        raise HTTPException(status_code=400, detail=f"Failed to read file: {e}")

    try:
        result = await media_svc.save_upload(
            file_content=content,
            filename=file.filename,
            images_dir=paths.images_dir,
            subfolder=subfolder,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        logger.error("Upload failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Upload failed: {e}")

    return result


# ── GET /{stem}/assignment ───────────────────────────────────────────────


@router.get("/{stem}/assignment")
async def get_assignment(stem: str, user: UserContext = Depends(get_current_user)):
    """Get current media assignment for a beat."""
    paths = get_user_paths(user)
    return media_svc.get_assignment(stem, paths.metadata_dir)


# ── PUT /{stem}/assignment ───────────────────────────────────────────────


@router.put("/{stem}/assignment")
async def set_assignment(
    stem: str,
    body: AssignmentRequest,
    user: UserContext = Depends(get_current_user),
):
    """Assign a clip or image to a beat for rendering."""
    paths = get_user_paths(user)

    def _find_media(filename: str) -> bool:
        """Check if file exists in images/ or shared clips."""
        if (paths.images_dir / filename).exists():
            return True
        if paths.shared_clips_dir and (paths.shared_clips_dir / filename).exists():
            return True
        return False

    # Validate clip exists if provided
    if body.clip and not _find_media(body.clip):
        raise HTTPException(status_code=404, detail=f"Clip not found: {body.clip}")

    # Validate image exists if provided
    if body.image and not _find_media(body.image):
        raise HTTPException(status_code=404, detail=f"Image not found: {body.image}")

    result = media_svc.set_assignment(
        stem=stem,
        metadata_dir=paths.metadata_dir,
        clip=body.clip,
        image=body.image,
    )
    return result


# ── GET /detail/{filename:path} ──────────────────────────────────────────


@router.get("/detail/{filename:path}")
async def get_media_detail(filename: str, user: UserContext = Depends(get_current_user)):
    """Get full details for a single media file including copyright status and beat usage.
    Filename can include subfolder path (e.g. 'Sexyy Red/visual_yacht_party.mp4').
    """
    paths = get_user_paths(user)
    try:
        return await media_svc.get_media_detail(filename, paths.images_dir, paths.metadata_dir)
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Media file not found: {filename}")


# ── DELETE /{filename:path} ──────────────────────────────────────────────


@router.delete("/{filename:path}")
async def delete_media(filename: str, user: UserContext = Depends(get_current_user)):
    """Delete a media file and clean up all beat assignments that reference it.
    Filename can include subfolder path.
    """
    paths = get_user_paths(user)
    try:
        result = media_svc.delete_media(filename, paths.images_dir, paths.metadata_dir)
        return result
    except FileNotFoundError:
        raise HTTPException(status_code=404, detail=f"Media file not found: {filename}")
