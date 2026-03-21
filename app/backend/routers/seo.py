"""
/api/seo — SEO metadata endpoints.
Wraps seo_metadata.py subprocess + direct metadata JSON read/write.
"""

from __future__ import annotations

import asyncio
import json
import logging

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.config import PYTHON, ROOT
from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.services.beat_svc import get_beat, list_beats

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/seo", tags=["seo"])


class MetadataUpdate(BaseModel):
    title: str | None = None
    description: str | None = None
    tags: list[str] | None = None
    artist: str | None = None
    seo_artist: str | None = None


@router.get("/{stem}")
async def get_metadata(stem: str, user: UserContext = Depends(get_current_user)):
    """Get SEO metadata for a beat."""
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

    meta_path = paths.metadata_dir / f"{stem}.json"
    if not meta_path.exists():
        return {
            "stem": stem,
            "metadata": {
                "title": stem.replace("_", " ").title(),
                "artist": "",
                "description": "",
                "tags": [],
            },
            "has_metadata": False,
        }

    try:
        meta = json.loads(meta_path.read_text())
    except Exception:
        meta = {}

    return {
        "stem": stem,
        "metadata": meta,
        "has_metadata": True,
    }


@router.put("/{stem}")
async def update_metadata(
    stem: str,
    req: MetadataUpdate,
    user: UserContext = Depends(get_current_user),
):
    """Update SEO metadata for a beat (partial update — only provided fields)."""
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
    if req.description is not None:
        meta["description"] = req.description
    if req.tags is not None:
        meta["tags"] = req.tags
    if req.artist is not None:
        meta["artist"] = req.artist
    if req.seo_artist is not None:
        meta["seo_artist"] = req.seo_artist

    with open(meta_path, "w") as f:
        json.dump(meta, f, indent=2)

    logger.info("Updated metadata for %s", stem)
    return {
        "stem": stem,
        "metadata": meta,
        "message": f"Metadata updated for {stem}",
    }


@router.post("/{stem}/generate")
async def generate_seo(stem: str, user: UserContext = Depends(get_current_user)):
    """
    Generate SEO metadata for a single beat via seo_metadata.py subprocess.
    Uses --force to regenerate even if metadata exists.
    """
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

    cmd = [
        PYTHON,
        str(ROOT / "seo_metadata.py"),
        "--only", stem,
        "--force",
    ]

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
        "output": stdout_text.strip(),
        "message": f"SEO metadata generated for {stem}",
    }


@router.post("/generate-all")
async def generate_all_seo(user: UserContext = Depends(get_current_user)):
    """
    Generate SEO metadata for ALL beats that are missing metadata.
    Uses seo_metadata.py without --force (only creates missing).
    """
    cmd = [
        PYTHON,
        str(ROOT / "seo_metadata.py"),
    ]

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
        "output": stdout_text.strip(),
        "message": f"SEO generation complete: {created} created, {updated} updated, {skipped} skipped",
    }
