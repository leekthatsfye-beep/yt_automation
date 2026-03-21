"""
/api/beats — CRUD endpoints for beat management + SEO metadata.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, UploadFile, File
from pydantic import BaseModel

from app.backend.config import PYTHON, ROOT
from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.services.beat_svc import list_beats, get_beat, safe_stem, analyze_beat
from app.backend.services.thumbnail_ai_svc import (
    generate_thumbnail_image,
    generate_preview_grid,
    apply_thumbnail,
    stamp_and_save,
    get_available_genres,
    get_api_key as get_replicate_key,
    save_api_key as save_replicate_key,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/beats", tags=["beats"])


class MetadataUpdate(BaseModel):
    title: str | None = None
    beat_name: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    artist: str | None = None


class ThumbnailGenRequest(BaseModel):
    genre: str
    customPrompt: str | None = None
    quality: str = "preview"  # "preview" or "final"


class ThumbnailGridRequest(BaseModel):
    genre: str
    customPrompt: str | None = None


class ThumbnailApplyRequest(BaseModel):
    imageUrl: str


@router.get("")
async def get_all_beats(user: UserContext = Depends(get_current_user)):
    """List all beats with full metadata, render/upload status."""
    paths = get_user_paths(user)
    return list_beats(
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )


# Static routes MUST come before /{stem} to avoid being swallowed
@router.post("/upload")
async def upload_beat(
    file: UploadFile = File(...),
    user: UserContext = Depends(get_current_user),
):
    """
    Upload an audio file (MP3/WAV) into beats/.
    Auto-generates a metadata stub in metadata/.
    """
    if not file.filename:
        raise HTTPException(status_code=400, detail="No filename provided")

    ext = Path(file.filename).suffix.lower()
    if ext not in (".mp3", ".wav"):
        raise HTTPException(status_code=400, detail="Only .mp3 and .wav files are accepted")

    paths = get_user_paths(user)

    # Save uploaded file
    paths.beats_dir.mkdir(parents=True, exist_ok=True)
    dest = paths.beats_dir / file.filename
    with open(dest, "wb") as f:
        content = await file.read()
        f.write(content)

    # Generate metadata stub
    stem = safe_stem(file.filename)
    paths.metadata_dir.mkdir(parents=True, exist_ok=True)
    meta_path = paths.metadata_dir / f"{stem}.json"

    if not meta_path.exists():
        meta = {
            "title": stem.replace("_", " ").title(),
            "artist": "",
            "description": "",
            "tags": [],
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

    logger.info("Uploaded beat: %s -> stem=%s (user=%s)", file.filename, stem, user.username)
    return {
        "stem": stem,
        "filename": file.filename,
        "message": f"Beat uploaded successfully as '{file.filename}'",
    }


@router.post("/generate-all-seo")
async def generate_all_seo(user: UserContext = Depends(get_current_user)):
    """Generate SEO metadata for all beats missing metadata."""
    cmd = [PYTHON, str(ROOT / "seo_metadata.py")]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(ROOT),
    )

    stdout, stderr = await proc.communicate()
    stdout_text = stdout.decode(errors="replace")
    stderr_text = stderr.decode(errors="replace")

    if proc.returncode != 0:
        logger.error("seo_metadata.py (all) failed: %s", stderr_text)
        raise HTTPException(
            status_code=500,
            detail=f"Bulk SEO generation failed: {stderr_text[:500]}",
        )

    lines = stdout_text.strip().split("\n") if stdout_text.strip() else []
    created = sum(1 for l in lines if "[META]" in l)
    skipped = sum(1 for l in lines if "[SKIP]" in l)
    updated = sum(1 for l in lines if "[UPDATE]" in l)

    logger.info("Bulk SEO: %d created, %d updated, %d skipped", created, updated, skipped)
    return {
        "created": created,
        "updated": updated,
        "skipped": skipped,
        "message": f"SEO generation complete: {created} created, {updated} updated, {skipped} skipped",
    }


# ── AI Thumbnail endpoints ─────────────────────────────────────────────

class ReplicateKeyRequest(BaseModel):
    key: str


@router.get("/ai-thumbnail/genres")
async def get_thumbnail_genres(user: UserContext = Depends(get_current_user)):
    """Return available genre categories for AI thumbnail generation."""
    return {
        "genres": get_available_genres(),
        "configured": bool(get_replicate_key()),
    }


@router.post("/ai-thumbnail/api-key")
async def set_replicate_api_key(
    req: ReplicateKeyRequest,
    user: UserContext = Depends(get_current_user),
):
    """Save Replicate API token to app_settings.json."""
    save_replicate_key(req.key)
    return {"status": "saved", "message": "Replicate API key saved successfully"}


@router.post("/{stem}/ai-thumbnail")
async def generate_ai_thumbnail(
    stem: str,
    req: ThumbnailGenRequest,
    user: UserContext = Depends(get_current_user),
):
    """Generate a single AI thumbnail for a beat."""
    paths = get_user_paths(user)
    beat = get_beat(
        stem,
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )
    if beat is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")

    if not get_replicate_key():
        raise HTTPException(
            status_code=400,
            detail="REPLICATE_API_TOKEN not configured. Add it in Settings → Integrations.",
        )

    loop = asyncio.get_event_loop()
    result = await loop.run_in_executor(
        None,
        lambda: generate_thumbnail_image(
            genre=req.genre,
            custom_prompt=req.customPrompt,
            quality=req.quality,
        ),
    )

    if not result:
        raise HTTPException(status_code=500, detail="Thumbnail generation failed")

    return result


@router.post("/{stem}/ai-thumbnail/grid")
async def generate_ai_thumbnail_grid(
    stem: str,
    req: ThumbnailGridRequest,
    user: UserContext = Depends(get_current_user),
):
    """Generate 4 preview thumbnails for a beat to choose from."""
    paths = get_user_paths(user)
    beat = get_beat(
        stem,
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )
    if beat is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")

    if not get_replicate_key():
        raise HTTPException(
            status_code=400,
            detail="REPLICATE_API_TOKEN not configured. Add it in Settings → Integrations.",
        )

    loop = asyncio.get_event_loop()
    results = await loop.run_in_executor(
        None,
        lambda: generate_preview_grid(
            genre=req.genre,
            custom_prompt=req.customPrompt,
        ),
    )

    if not results:
        raise HTTPException(status_code=500, detail="Preview generation failed")

    return {"images": results}


@router.post("/{stem}/ai-thumbnail/apply")
async def apply_ai_thumbnail(
    stem: str,
    req: ThumbnailApplyRequest,
    user: UserContext = Depends(get_current_user),
):
    """Download chosen AI thumbnail, stamp FY3 logo, save as beat thumbnail."""
    paths = get_user_paths(user)
    beat = get_beat(
        stem,
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )
    if beat is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")

    loop = asyncio.get_event_loop()
    thumb_path = await loop.run_in_executor(
        None,
        lambda: apply_thumbnail(
            stem=stem,
            image_url=req.imageUrl,
            output_dir=paths.output_dir,
            metadata_dir=paths.metadata_dir,
        ),
    )

    if not thumb_path:
        raise HTTPException(status_code=500, detail="Failed to save thumbnail")

    return {
        "saved": True,
        "path": str(thumb_path.name),
        "message": f"AI thumbnail saved for {stem}",
    }


# Artists that use the pink logo variant (same as render.py)
PINK_LOGO_ARTISTS = {
    "Sexyy Red", "GloRilla", "Megan Thee Stallion", "Latto",
    "City Girls", "Ice Spice", "Cardi B", "Nicki Minaj",
    "Doechii", "Flo Milli", "Sukihana",
}


@router.post("/{stem}/upload-thumbnail")
async def upload_thumbnail(
    stem: str,
    file: UploadFile = File(...),
    user: UserContext = Depends(get_current_user),
):
    """Upload a custom thumbnail image. Stamps FY3 logo and saves as beat thumbnail."""
    from PIL import Image
    import io
    import time

    paths = get_user_paths(user)
    beat = get_beat(
        stem,
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )
    if beat is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")

    # Validate content type
    ct = file.content_type or ""
    if not ct.startswith("image/"):
        raise HTTPException(status_code=400, detail="File must be an image (JPEG or PNG)")

    # Read file (limit 20MB)
    data = await file.read()
    if len(data) > 20 * 1024 * 1024:
        raise HTTPException(status_code=400, detail="Image must be under 20MB")

    # Open with PIL
    try:
        img = Image.open(io.BytesIO(data))
        img.load()  # Force decode to catch corrupt files
    except Exception:
        raise HTTPException(status_code=400, detail="Invalid image file")

    # Auto-detect pink stamp from beat's seo_artist
    seo_artist = beat.get("seo_artist", "")
    use_pink = seo_artist in PINK_LOGO_ARTISTS

    # Stamp and save (runs in executor to avoid blocking)
    loop = asyncio.get_event_loop()
    thumb_path = await loop.run_in_executor(
        None,
        lambda: stamp_and_save(
            img=img,
            stem=stem,
            output_dir=paths.output_dir,
            use_pink_stamp=use_pink,
        ),
    )

    # Update metadata with custom thumbnail info
    try:
        meta_path = paths.metadata_dir / f"{stem}.json"
        if meta_path.exists():
            meta_data = json.loads(meta_path.read_text())
        else:
            meta_data = {}
        meta_data["custom_thumbnail"] = {
            "uploaded_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
            "original_filename": file.filename or "unknown",
            "source": "user_upload",
        }
        meta_path.write_text(json.dumps(meta_data, indent=2))
    except Exception as e:
        logger.warning("Failed to update metadata for custom thumbnail: %s", e)

    return {
        "ok": True,
        "stem": stem,
        "thumbnail": f"{stem}_thumb.jpg",
        "message": f"Custom thumbnail saved for {stem}",
    }


@router.get("/{stem}")
async def get_single_beat(stem: str, user: UserContext = Depends(get_current_user)):
    """Return a single beat with all metadata."""
    paths = get_user_paths(user)
    beat = get_beat(
        stem,
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )
    if beat is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")
    return beat


@router.put("/{stem}/metadata")
async def update_metadata(
    stem: str,
    req: MetadataUpdate,
    user: UserContext = Depends(get_current_user),
):
    """Update SEO metadata for a beat (partial update)."""
    paths = get_user_paths(user)
    beat = get_beat(
        stem,
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )
    if beat is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")

    paths.metadata_dir.mkdir(parents=True, exist_ok=True)
    meta_path = paths.metadata_dir / f"{stem}.json"

    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            meta = {}
    else:
        meta = {
            "title": stem.replace("_", " ").title(),
            "artist": "",
            "description": "",
            "tags": [],
        }

    if req.title is not None:
        meta["title"] = req.title
    if req.beat_name is not None:
        meta["beat_name"] = req.beat_name
    if req.description is not None:
        meta["description"] = req.description
    if req.tags is not None:
        meta["tags"] = req.tags
    if req.artist is not None:
        meta["artist"] = req.artist

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    # Sync beat_name to store listings if they exist
    synced_stores: list[str] = []
    if req.beat_name is not None:
        try:
            listings_dir = paths.listings_dir if hasattr(paths, "listings_dir") else None
            if listings_dir and listings_dir.exists():
                for listing_file in listings_dir.glob("*.json"):
                    try:
                        listing = json.loads(listing_file.read_text())
                        if listing.get("stem") == stem:
                            listing["title"] = req.beat_name
                            listing_file.write_text(json.dumps(listing, indent=2))
                            synced_stores.append(listing_file.stem)
                    except Exception:
                        continue
        except Exception as e:
            logger.warning("Store listing sync failed for %s: %s", stem, e)

    logger.info("Updated metadata for %s (stores synced: %s)", stem, synced_stores)
    return {
        "stem": stem,
        "metadata": meta,
        "synced_stores": synced_stores,
        "message": f"Metadata updated for {stem}",
    }


@router.post("/{stem}/generate-seo")
async def generate_seo(stem: str, user: UserContext = Depends(get_current_user)):
    """Generate SEO metadata for a single beat via seo_metadata.py."""
    paths = get_user_paths(user)
    beat = get_beat(
        stem,
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )
    if beat is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")

    cmd = [PYTHON, str(ROOT / "seo_metadata.py"), "--only", stem, "--force"]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(ROOT),
    )

    stdout, stderr = await proc.communicate()
    stderr_text = stderr.decode(errors="replace")

    if proc.returncode != 0:
        logger.error("seo_metadata.py failed for %s: %s", stem, stderr_text)
        raise HTTPException(
            status_code=500,
            detail=f"SEO generation failed: {stderr_text[:500]}",
        )

    meta_path = paths.metadata_dir / f"{stem}.json"
    meta = {}
    if meta_path.exists():
        try:
            meta = json.loads(meta_path.read_text())
        except Exception:
            pass

    logger.info("Generated SEO for %s", stem)
    return {
        "stem": stem,
        "metadata": meta,
        "message": f"SEO metadata generated for {stem}",
    }


@router.delete("/{stem}")
async def delete_beat(stem: str, user: UserContext = Depends(get_current_user)):
    """
    Delete a beat and all associated files:
    audio, metadata, rendered video, thumbnail,
    and log entries (uploads_log, social_uploads_log).
    """
    paths = get_user_paths(user)
    audio_path = _find_audio(stem, paths.beats_dir)
    if audio_path is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")

    removed: list[str] = []

    # Remove audio
    audio_path.unlink()
    removed.append(str(audio_path.name))

    # Remove metadata
    meta_path = paths.metadata_dir / f"{stem}.json"
    if meta_path.exists():
        meta_path.unlink()
        removed.append(str(meta_path.name))

    # Remove rendered video
    video_path = paths.output_dir / f"{stem}.mp4"
    if video_path.exists():
        video_path.unlink()
        removed.append(str(video_path.name))

    # Remove 9x16 variant if exists
    video_9x16 = paths.output_dir / f"{stem}_9x16.mp4"
    if video_9x16.exists():
        video_9x16.unlink()
        removed.append(str(video_9x16.name))

    # Remove thumbnail
    thumb_path = paths.output_dir / f"{stem}_thumb.jpg"
    if thumb_path.exists():
        thumb_path.unlink()
        removed.append(str(thumb_path.name))

    # Clean up uploads_log.json (YouTube history)
    try:
        if paths.uploads_log.exists():
            log = json.loads(paths.uploads_log.read_text())
            if stem in log:
                del log[stem]
                paths.uploads_log.write_text(json.dumps(log, indent=2))
                removed.append("uploads_log entry")
    except Exception as e:
        logger.warning("Failed to clean uploads_log for %s: %s", stem, e)

    # Clean up social_uploads_log.json (IG/TikTok history)
    try:
        if paths.social_log.exists():
            log = json.loads(paths.social_log.read_text())
            if stem in log:
                del log[stem]
                paths.social_log.write_text(json.dumps(log, indent=2))
                removed.append("social_log entry")
    except Exception as e:
        logger.warning("Failed to clean social_log for %s: %s", stem, e)

    logger.info("Deleted beat '%s': removed %s", stem, removed)
    return {"stem": stem, "removed": removed}


@router.post("/{stem}/analyze")
async def analyze_beat_endpoint(stem: str, user: UserContext = Depends(get_current_user)):
    """
    Run BPM/key analysis on a beat via analyze_beats.py subprocess.
    Updates the metadata JSON and returns {bpm, key}.
    """
    paths = get_user_paths(user)
    audio_path = _find_audio(stem, paths.beats_dir)
    if audio_path is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")

    try:
        result = await analyze_beat(stem, metadata_dir=paths.metadata_dir)
    except RuntimeError as exc:
        raise HTTPException(status_code=500, detail=str(exc))

    return {"stem": stem, **result}


# ── helpers ──────────────────────────────────────────────────────────────

def _find_audio(stem: str, beats_dir: Path) -> Path | None:
    """Find the audio file for a given stem."""
    for ext in ("*.mp3", "*.wav"):
        for p in beats_dir.glob(ext):
            if safe_stem(p.name) == stem:
                return p
    return None
