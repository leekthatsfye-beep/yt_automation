"""
Authenticated file serving — replaces StaticFiles mounts.

Serves files from the correct user directory based on JWT auth.
Includes path traversal protection.

Also provides a public signed-URL endpoint for external services
(e.g. Instagram Graph API) to fetch media without JWT auth.
"""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import logging
import mimetypes
import time
from pathlib import Path

from fastapi import APIRouter, Depends, HTTPException, Query
from fastapi.responses import FileResponse

from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.auth import SECRET_KEY
from app.backend.config import ROOT, OUTPUT_DIR

logger = logging.getLogger(__name__)

# ── Thumbnail cache directory ──────────────────────────────────────────────
THUMB_CACHE_DIR = ROOT / ".thumb_cache"
THUMB_CACHE_DIR.mkdir(exist_ok=True)

router = APIRouter(prefix="/files", tags=["files"])

# ── Public signed-URL helpers ──────────────────────────────────────────────
# Used by social_upload.py to give IG a fetchable video_url via the main
# Cloudflare tunnel.  Token is HMAC-SHA256(filename + expiry, SECRET_KEY).
# Links expire after SIGNED_URL_TTL seconds.

SIGNED_URL_TTL = 600  # 10 minutes — plenty for IG to fetch


def create_signed_url(filename: str, base_url: str = "https://fy3studio.com") -> str:
    """Generate a time-limited public URL for a file in output/."""
    expires = int(time.time()) + SIGNED_URL_TTL
    sig = hmac.new(
        SECRET_KEY.encode(), f"{filename}:{expires}".encode(), hashlib.sha256
    ).hexdigest()[:32]
    return f"{base_url}/files/public/{filename}?expires={expires}&sig={sig}"


def _verify_signature(filename: str, expires: int, sig: str) -> bool:
    expected = hmac.new(
        SECRET_KEY.encode(), f"{filename}:{expires}".encode(), hashlib.sha256
    ).hexdigest()[:32]
    return hmac.compare_digest(sig, expected) and time.time() < expires


def _safe_serve(base_dir, filename: str) -> FileResponse:
    """Serve a file with path traversal protection."""
    file_path = (base_dir / filename).resolve()

    # Prevent path traversal (e.g. ../../../etc/passwd)
    if not str(file_path).startswith(str(base_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")

    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Guess content type
    content_type, _ = mimetypes.guess_type(str(file_path))

    return FileResponse(
        str(file_path),
        media_type=content_type,
    )


@router.get("/output/{filename:path}")
async def serve_output(
    filename: str,
    user: UserContext = Depends(get_current_user),
):
    """Serve rendered videos and thumbnails."""
    paths = get_user_paths(user)
    return _safe_serve(paths.output_dir, filename)


@router.get("/beats/{filename:path}")
async def serve_beat(
    filename: str,
    user: UserContext = Depends(get_current_user),
):
    """Serve audio files."""
    paths = get_user_paths(user)
    return _safe_serve(paths.beats_dir, filename)


@router.get("/studio/{filename:path}")
async def serve_studio(
    filename: str,
    user: UserContext = Depends(get_current_user),
):
    """Serve Suno-generated audio."""
    paths = get_user_paths(user)
    return _safe_serve(paths.studio_dir, filename)


@router.get("/images/{filename:path}")
async def serve_image(
    filename: str,
    user: UserContext = Depends(get_current_user),
):
    """Serve media files (clips and images) from images/ directory."""
    paths = get_user_paths(user)
    return _safe_serve(paths.images_dir, filename)


@router.get("/shared-clips/{filename:path}")
async def serve_shared_clip(
    filename: str,
    user: UserContext = Depends(get_current_user),
):
    """Serve media files from ~/Shared_Clips directory."""
    paths = get_user_paths(user)
    return _safe_serve(paths.shared_clips_dir, filename)


@router.get("/thumbnail/{filename:path}")
async def serve_thumbnail(
    filename: str,
    user: UserContext = Depends(get_current_user),
):
    """Extract and serve a thumbnail frame from a video clip.

    Uses ffmpeg to grab a frame at 1 second, cached to .thumb_cache/.
    Returns a JPEG image.
    """
    paths = get_user_paths(user)
    video_path = (paths.images_dir / filename).resolve()

    # Security: prevent path traversal
    if not str(video_path).startswith(str(paths.images_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    if not video_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    # Only allow video files
    ext = video_path.suffix.lower()
    if ext not in (".mp4", ".mov"):
        raise HTTPException(status_code=400, detail="Not a video file")

    # Cache key: hash of path + mtime for cache invalidation
    mtime = str(int(video_path.stat().st_mtime))
    cache_key = hashlib.md5(f"{filename}:{mtime}".encode()).hexdigest()
    thumb_path = THUMB_CACHE_DIR / f"{cache_key}.jpg"

    if not thumb_path.exists():
        # Extract a frame at t=1s using ffmpeg
        try:
            proc = await asyncio.create_subprocess_exec(
                "ffmpeg", "-y",
                "-ss", "1",
                "-i", str(video_path),
                "-vframes", "1",
                "-vf", "scale=480:-2",
                "-q:v", "4",
                str(thumb_path),
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await asyncio.wait_for(proc.communicate(), timeout=15)
            if proc.returncode != 0 or not thumb_path.exists():
                # Try at t=0 as fallback
                proc2 = await asyncio.create_subprocess_exec(
                    "ffmpeg", "-y",
                    "-i", str(video_path),
                    "-vframes", "1",
                    "-vf", "scale=480:-2",
                    "-q:v", "4",
                    str(thumb_path),
                    stdout=asyncio.subprocess.PIPE,
                    stderr=asyncio.subprocess.PIPE,
                )
                await asyncio.wait_for(proc2.communicate(), timeout=15)
        except Exception as e:
            logger.warning("Thumbnail extraction failed for %s: %s", filename, e)
            raise HTTPException(status_code=500, detail="Thumbnail extraction failed")

    if not thumb_path.exists():
        raise HTTPException(status_code=500, detail="Thumbnail extraction failed")

    return FileResponse(str(thumb_path), media_type="image/jpeg")


@router.get("/download/output/{filename:path}")
async def download_output(
    filename: str,
    user: UserContext = Depends(get_current_user),
):
    """Download a rendered video as attachment (triggers browser download)."""
    paths = get_user_paths(user)
    file_path = (paths.output_dir / filename).resolve()

    if not str(file_path).startswith(str(paths.output_dir.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    content_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(
        str(file_path),
        media_type=content_type or "application/octet-stream",
        headers={"Content-Disposition": f'attachment; filename="{file_path.name}"'},
    )


# ── Public signed endpoint (no JWT required) ──────────────────────────────
# Used by social_upload.py so IG Graph API can fetch the video via video_url.

@router.get("/public/{filename:path}")
async def serve_public_media(
    filename: str,
    expires: int = Query(...),
    sig: str = Query(...),
):
    """
    Serve a file from output/ without JWT auth.
    Requires a valid HMAC signature + unexpired timestamp.
    Only allows video files — no directory traversal.
    """
    # Validate signature
    if not _verify_signature(filename, expires, sig):
        raise HTTPException(status_code=403, detail="Invalid or expired link")

    # Only allow safe filenames (no path traversal)
    if "/" in filename or ".." in filename:
        raise HTTPException(status_code=403, detail="Invalid filename")

    # Only allow video files
    if not filename.endswith((".mp4", ".mov")):
        raise HTTPException(status_code=403, detail="Only video files allowed")

    file_path = (OUTPUT_DIR / filename).resolve()
    if not str(file_path).startswith(str(OUTPUT_DIR.resolve())):
        raise HTTPException(status_code=403, detail="Access denied")
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found")

    content_type, _ = mimetypes.guess_type(str(file_path))
    return FileResponse(str(file_path), media_type=content_type or "video/mp4")
