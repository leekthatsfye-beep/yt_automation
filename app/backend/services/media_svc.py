"""
Media service — browse, upload, and assign media (clips & images) to beats.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import shutil
from pathlib import Path
from typing import Any

from app.backend.config import PYTHON

logger = logging.getLogger(__name__)

# Files to skip when browsing images/
_SKIP_FILES = {
    "beatscan_header.png",
    "start_header.png",
    ".DS_Store",
    "Thumbs.db",
}

ALLOWED_VIDEO_EXT = {".mp4", ".mov"}
ALLOWED_IMAGE_EXT = {".jpg", ".jpeg", ".png"}
ALLOWED_EXT = ALLOWED_VIDEO_EXT | ALLOWED_IMAGE_EXT

# Auto-compress thresholds
VIDEO_SIZE_THRESHOLD = 100 * 1024 * 1024  # 100 MB
VIDEO_MAX_DIMENSION = 1920
IMAGE_SIZE_THRESHOLD = 5 * 1024 * 1024  # 5 MB
IMAGE_MAX_DIMENSION = 1920


# ── ffprobe helpers ──────────────────────────────────────────────────────


async def _ffprobe_json(path: Path) -> dict[str, Any] | None:
    """Run ffprobe and return parsed JSON output."""
    try:
        proc = await asyncio.create_subprocess_exec(
            "ffprobe", "-v", "quiet", "-print_format", "json",
            "-show_format", "-show_streams", str(path),
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
        )
        stdout, _ = await proc.communicate()
        if proc.returncode != 0:
            return None
        return json.loads(stdout.decode())
    except Exception as e:
        logger.warning("ffprobe failed for %s: %s", path, e)
        return None


async def _get_video_info(path: Path) -> dict[str, Any]:
    """Get resolution, duration, orientation for a video file."""
    info = await _ffprobe_json(path)
    if not info:
        return {"resolution": "unknown", "duration": 0, "orientation": "unknown"}

    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":
            w = stream.get("width", 0)
            h = stream.get("height", 0)
            dur = float(info.get("format", {}).get("duration", 0))
            orientation = "portrait" if h > w else "landscape"
            return {
                "width": w,
                "height": h,
                "resolution": f"{w}x{h}",
                "duration": round(dur, 1),
                "orientation": orientation,
            }

    return {"resolution": "unknown", "duration": 0, "orientation": "unknown"}


async def _get_image_info(path: Path) -> dict[str, Any]:
    """Get resolution for an image file via ffprobe."""
    info = await _ffprobe_json(path)
    if not info:
        return {"resolution": "unknown"}

    for stream in info.get("streams", []):
        if stream.get("codec_type") == "video":  # ffprobe treats images as video streams
            w = stream.get("width", 0)
            h = stream.get("height", 0)
            return {"width": w, "height": h, "resolution": f"{w}x{h}"}

    return {"resolution": "unknown"}


# ── Browse media ─────────────────────────────────────────────────────────


async def _scan_dir(
    base_dir: Path,
    source: str,
    clips: list[dict],
    images: list[dict],
    seen_names: set[str],
) -> None:
    """Scan a single directory tree, appending clips/images to the lists."""
    if not base_dir.exists():
        return

    for root, _dirs, files in os.walk(base_dir):
        root_path = Path(root)
        for fname in sorted(files):
            if fname in _SKIP_FILES or fname.startswith("."):
                continue

            fpath = root_path / fname
            ext = fpath.suffix.lower()
            if ext not in ALLOWED_EXT:
                continue

            # Deduplicate by filename (images/ wins over shared)
            if fname in seen_names:
                continue
            seen_names.add(fname)

            rel_path = str(fpath.relative_to(base_dir))
            size_mb = round(fpath.stat().st_size / (1024 * 1024), 1)

            # Determine folder (empty string for root)
            folder = str(root_path.relative_to(base_dir))
            if folder == ".":
                folder = ""

            if ext in ALLOWED_VIDEO_EXT:
                info = await _get_video_info(fpath)
                clips.append({
                    "path": rel_path,
                    "name": fpath.name,
                    "folder": folder,
                    "size_mb": size_mb,
                    "source": source,
                    **info,
                })
            elif ext in ALLOWED_IMAGE_EXT:
                info = await _get_image_info(fpath)
                images.append({
                    "path": rel_path,
                    "name": fpath.name,
                    "folder": folder,
                    "size_mb": size_mb,
                    "source": source,
                    **info,
                })


async def browse_media(
    images_dir: Path,
    shared_clips_dir: Path | None = None,
) -> dict[str, list[dict]]:
    """Scan images/ and optionally ~/Shared_Clips for available clips and images."""
    clips: list[dict] = []
    images: list[dict] = []
    seen_names: set[str] = set()

    # Primary source — images/ folder (wins duplicates)
    await _scan_dir(images_dir, "library", clips, images, seen_names)

    # Secondary source — ~/Shared_Clips (only new filenames added)
    if shared_clips_dir:
        await _scan_dir(shared_clips_dir, "shared", clips, images, seen_names)

    return {"clips": clips, "images": images}


# ── Upload + auto-compress ───────────────────────────────────────────────


async def compress_upload(temp_path: Path, final_path: Path) -> bool:
    """
    Auto-compress an uploaded file if it exceeds size/resolution thresholds.
    Returns True if compression was performed, False if file was used as-is.
    """
    ext = temp_path.suffix.lower()

    if ext in ALLOWED_VIDEO_EXT:
        info = await _get_video_info(temp_path)
        file_size = temp_path.stat().st_size
        w = info.get("width", 0)
        h = info.get("height", 0)

        needs_compress = (
            file_size > VIDEO_SIZE_THRESHOLD
            or w > VIDEO_MAX_DIMENSION
            or h > VIDEO_MAX_DIMENSION
        )

        if needs_compress:
            logger.info(
                "Auto-compressing upload: %s (%.1fMB, %dx%d)",
                temp_path.name, file_size / (1024 * 1024), w, h,
            )
            # Scale to max 1920px on longest side, CRF 23
            scale_filter = (
                f"scale='min({VIDEO_MAX_DIMENSION},iw)':'min({VIDEO_MAX_DIMENSION},ih)'"
                f":force_original_aspect_ratio=decrease"
            )
            cmd = [
                "ffmpeg", "-y", "-i", str(temp_path),
                "-vf", scale_filter,
                "-c:v", "libx264", "-preset", "fast", "-crf", "23",
                "-c:a", "aac", "-b:a", "128k",
                "-movflags", "+faststart",
                str(final_path),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                temp_path.unlink(missing_ok=True)
                return True
            else:
                logger.warning("Video compression failed, using original")

        # No compression needed or compression failed — move as-is
        shutil.move(str(temp_path), str(final_path))
        return False

    elif ext in ALLOWED_IMAGE_EXT:
        file_size = temp_path.stat().st_size
        info = await _get_image_info(temp_path)
        w = info.get("width", 0)
        h = info.get("height", 0)

        needs_compress = (
            file_size > IMAGE_SIZE_THRESHOLD
            or w > IMAGE_MAX_DIMENSION
            or h > IMAGE_MAX_DIMENSION
        )

        if needs_compress:
            logger.info(
                "Auto-compressing image: %s (%.1fMB, %dx%d)",
                temp_path.name, file_size / (1024 * 1024), w, h,
            )
            scale_filter = (
                f"scale='min({IMAGE_MAX_DIMENSION},iw)':'min({IMAGE_MAX_DIMENSION},ih)'"
                f":force_original_aspect_ratio=decrease"
            )
            cmd = [
                "ffmpeg", "-y", "-i", str(temp_path),
                "-vf", scale_filter,
                "-q:v", "2",  # JPEG quality ~85
                str(final_path),
            ]
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
            )
            await proc.communicate()
            if proc.returncode == 0:
                temp_path.unlink(missing_ok=True)
                return True
            else:
                logger.warning("Image compression failed, using original")

        shutil.move(str(temp_path), str(final_path))
        return False

    else:
        shutil.move(str(temp_path), str(final_path))
        return False


async def save_upload(
    file_content: bytes,
    filename: str,
    images_dir: Path,
    subfolder: str | None = None,
) -> dict[str, Any]:
    """Save an uploaded media file, auto-compressing if too large."""
    ext = Path(filename).suffix.lower()
    if ext not in ALLOWED_EXT:
        raise ValueError(f"Unsupported file type: {ext}")

    # Determine target directory
    target_dir = images_dir / subfolder if subfolder else images_dir
    target_dir.mkdir(parents=True, exist_ok=True)

    # Clean filename
    safe_name = filename.replace(" ", "_")
    final_path = target_dir / safe_name
    temp_path = target_dir / f"_tmp_{safe_name}"

    # Write temp file
    temp_path.write_bytes(file_content)

    try:
        compressed = await compress_upload(temp_path, final_path)
    except Exception:
        temp_path.unlink(missing_ok=True)
        raise

    rel_path = str(final_path.relative_to(images_dir))
    size_mb = round(final_path.stat().st_size / (1024 * 1024), 1)

    # Get metadata
    if ext in ALLOWED_VIDEO_EXT:
        info = await _get_video_info(final_path)
        media_type = "clip"
    else:
        info = await _get_image_info(final_path)
        media_type = "image"

    return {
        "path": rel_path,
        "name": final_path.name,
        "type": media_type,
        "size_mb": size_mb,
        "compressed": compressed,
        **info,
    }


# ── Media assignment ─────────────────────────────────────────────────────


def get_assignment(stem: str, metadata_dir: Path) -> dict[str, Any]:
    """Read media assignment from metadata/{stem}.json."""
    meta_path = metadata_dir / f"{stem}.json"
    if not meta_path.exists():
        return {"stem": stem, "clip": None, "image": None, "source": "auto"}

    try:
        meta = json.loads(meta_path.read_text())
        media = meta.get("media", {})
        clip = media.get("clip")
        image = media.get("image")
        source = "manual" if clip or image else "auto"
        return {"stem": stem, "clip": clip, "image": image, "source": source}
    except Exception:
        return {"stem": stem, "clip": None, "image": None, "source": "auto"}


def set_assignment(
    stem: str,
    metadata_dir: Path,
    clip: str | None = None,
    image: str | None = None,
) -> dict[str, Any]:
    """Write media assignment into metadata/{stem}.json."""
    meta_path = metadata_dir / f"{stem}.json"

    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
    else:
        meta = {"title": stem, "artist": "BiggKutt8", "description": "", "tags": []}

    if clip or image:
        meta["media"] = {"clip": clip, "image": image}
    else:
        meta.pop("media", None)

    meta_path.write_text(json.dumps(meta, indent=2))

    source = "manual" if clip or image else "auto"
    return {"stem": stem, "clip": clip, "image": image, "source": source, "status": "saved"}


# ── Delete media ─────────────────────────────────────────────────────────


def get_beats_using_media(filename: str, metadata_dir: Path) -> list[str]:
    """Find all beat stems that have this file assigned as their clip or image."""
    stems: list[str] = []
    if not metadata_dir.exists():
        return stems
    for meta_path in sorted(metadata_dir.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text())
            media = meta.get("media", {})
            if media.get("clip") == filename or media.get("image") == filename:
                stems.append(meta_path.stem)
        except Exception:
            pass
    return stems


def delete_media(filename: str, images_dir: Path, metadata_dir: Path) -> dict[str, Any]:
    """
    Delete a media file and clean up all beat assignments that reference it.
    Also removes from copyright DB.
    """
    file_path = images_dir / filename
    removed_items: list[str] = []
    affected_beats: list[str] = []

    # Delete the actual file
    if file_path.exists():
        file_path.unlink()
        removed_items.append(f"File: {filename}")
        logger.info("Deleted media file: %s", filename)
    else:
        raise FileNotFoundError(f"Media file not found: {filename}")

    # Clean up beat assignments
    affected = get_beats_using_media(filename, metadata_dir)
    for stem in affected:
        meta_path = metadata_dir / f"{stem}.json"
        try:
            meta = json.loads(meta_path.read_text())
            media = meta.get("media", {})
            changed = False
            if media.get("clip") == filename:
                media["clip"] = None
                changed = True
            if media.get("image") == filename:
                media["image"] = None
                changed = True
            if changed:
                if not media.get("clip") and not media.get("image"):
                    meta.pop("media", None)
                else:
                    meta["media"] = media
                meta_path.write_text(json.dumps(meta, indent=2))
                affected_beats.append(stem)
                removed_items.append(f"Assignment cleared: {stem}")
        except Exception as e:
            logger.warning("Failed to clear assignment for %s: %s", stem, e)

    # Remove from copyright DB
    try:
        from app.backend.services.copyright_svc import remove_from_db
        remove_from_db(filename)
        removed_items.append("Copyright DB entry")
    except Exception:
        pass

    return {
        "filename": filename,
        "removed": removed_items,
        "affected_beats": affected_beats,
    }


async def get_media_detail(
    filename: str,
    images_dir: Path,
    metadata_dir: Path,
) -> dict[str, Any]:
    """Get full details for a single media file."""
    file_path = images_dir / filename
    if not file_path.exists():
        raise FileNotFoundError(f"Media file not found: {filename}")

    ext = file_path.suffix.lower()
    size_mb = round(file_path.stat().st_size / (1024 * 1024), 1)
    modified = file_path.stat().st_mtime

    if ext in ALLOWED_VIDEO_EXT:
        info = await _get_video_info(file_path)
        media_type = "clip"
    elif ext in ALLOWED_IMAGE_EXT:
        info = await _get_image_info(file_path)
        media_type = "image"
    else:
        info = {}
        media_type = "unknown"

    # Find which beats use this file
    used_by = get_beats_using_media(filename, metadata_dir)

    # Get copyright status
    try:
        from app.backend.services.copyright_svc import get_clip_status
        copyright_status = get_clip_status(filename)
    except Exception:
        copyright_status = {"risk": "unknown", "reasons": []}

    return {
        "filename": filename,
        "type": media_type,
        "size_mb": size_mb,
        "modified": modified,
        "used_by": used_by,
        "copyright": copyright_status,
        **info,
    }
