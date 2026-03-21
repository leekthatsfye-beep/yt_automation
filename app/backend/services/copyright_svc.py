"""
Copyright protection service — scans video clips and audio for copyright risk.

Three detection layers:
1. Perceptual hash (pHash) — fingerprints video frames, matches against flagged DB
2. Instagram source detection — checks MP4 metadata for IG markers
3. Audio fingerprinting — extracts audio hash from clips, matches against flagged DB

Risk levels: safe | caution | danger | flagged (manual)
"""

from __future__ import annotations

import asyncio
import hashlib
import io
import json
import logging
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from PIL import Image
import imagehash

from app.backend.config import ROOT, IMAGES_DIR, METADATA_DIR

logger = logging.getLogger(__name__)

DB_PATH = ROOT / "copyright_db.json"

# pHash hamming distance thresholds
DANGER_THRESHOLD = 10   # Very similar — almost certainly the same clip
CAUTION_THRESHOLD = 18  # Somewhat similar — worth manual review

# Instagram resolution signatures (width x height)
_IG_RESOLUTIONS = {
    (1080, 1350),  # IG portrait post
    (1080, 1920),  # IG Reels / Stories
    (1080, 1080),  # IG square post
    (720, 1280),   # IG Reels (lower quality)
    (750, 1334),   # IG Stories (iPhone)
}

# Instagram metadata markers in MP4 atom/tags
_IG_MARKERS = [
    "instagram",
    "com.instagram",
    "ig_",
    "fbcdn",
    "scontent",
    "Lavf58",   # Common IG re-encoder
    "Lavf59",
    "Lavf60",
]

# Video extensions to scan
_VIDEO_EXTS = {".mp4", ".mov"}

# Artist content detection — clips from known artist folders/filenames are
# almost certainly copyrighted content (downloaded from IG, YouTube, etc.)
# These clips WILL get copyright claims if used on YouTube.
_COPYRIGHTED_ARTIST_MARKERS = [
    "sexyy red", "sexyyred", "central cee", "centralcee",
    "nicki minaj", "nickiminaj", "cardi b", "cardib",
    "megan thee stallion", "megantheestallion",
    "ice spice", "icespice", "glorilla",
    "lil baby", "lilbaby", "lil durk", "lildurk",
    "future", "young thug", "youngthug",
    "21 savage", "21savage", "gunna",
    "drake", "travis scott", "travisscott",
    "playboi carti", "playboicarti",
    "rod wave", "rodwave", "nba youngboy", "nbayoungboy",
    "moneybagg yo", "moneybaggyo",
    "kodak black", "kodakblack",
    "polo g", "polog",
    "lil uzi vert", "liluzivert",
    "pop smoke", "popsmoke",
    "jack harlow", "jackharlow",
    "dababy", "da baby",
    "migos", "quavo", "takeoff", "offset",
]


# ── DB helpers ─────────────────────────────────────────────────────────────


def _load_db() -> dict[str, Any]:
    """Load copyright database from disk."""
    if DB_PATH.exists():
        try:
            return json.loads(DB_PATH.read_text())
        except Exception as e:
            logger.error("Failed to load copyright DB: %s", e)
    return {"flagged": {}, "scan_results": {}}


def _save_db(db: dict[str, Any]) -> None:
    """Write copyright database to disk (crash-safe)."""
    try:
        tmp = DB_PATH.with_suffix(".tmp")
        tmp.write_text(json.dumps(db, indent=2, ensure_ascii=False))
        tmp.replace(DB_PATH)
    except Exception as e:
        logger.error("Failed to save copyright DB: %s", e)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


# ── Perceptual hashing ────────────────────────────────────────────────────


def _extract_frames(clip_path: Path, interval: float = 2.0, max_frames: int = 15) -> list[Image.Image]:
    """Extract frames from a video clip at regular intervals using ffmpeg."""
    frames: list[Image.Image] = []
    try:
        # Get duration first
        probe = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", str(clip_path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        duration = float(json.loads(probe.stdout).get("format", {}).get("duration", 0))
        if duration <= 0:
            return frames

        # Calculate timestamps
        timestamps = []
        t = 0.0
        while t < duration and len(timestamps) < max_frames:
            timestamps.append(t)
            t += interval

        for ts in timestamps:
            result = subprocess.run(
                [
                    "ffmpeg", "-y", "-ss", f"{ts:.2f}",
                    "-i", str(clip_path),
                    "-vframes", "1",
                    "-f", "image2pipe",
                    "-vcodec", "png",
                    "-",
                ],
                capture_output=True, timeout=10,
            )
            if result.returncode == 0 and result.stdout:
                try:
                    img = Image.open(io.BytesIO(result.stdout))
                    frames.append(img)
                except Exception:
                    pass
    except Exception as e:
        logger.warning("Frame extraction failed for %s: %s", clip_path.name, e)
    return frames


def _compute_phashes(clip_path: Path) -> list[str]:
    """Compute perceptual hashes for frames of a video clip."""
    frames = _extract_frames(clip_path)
    hashes = []
    for frame in frames:
        try:
            h = imagehash.phash(frame, hash_size=16)
            hashes.append(str(h))
        except Exception:
            pass
    return hashes


def _compare_phashes(hashes_a: list[str], hashes_b: list[str]) -> int:
    """
    Compare two sets of perceptual hashes.
    Returns the minimum hamming distance found (lower = more similar).
    """
    if not hashes_a or not hashes_b:
        return 999

    min_dist = 999
    for ha_str in hashes_a:
        try:
            ha = imagehash.hex_to_hash(ha_str)
        except Exception:
            continue
        for hb_str in hashes_b:
            try:
                hb = imagehash.hex_to_hash(hb_str)
                dist = ha - hb
                min_dist = min(min_dist, dist)
            except Exception:
                continue
    return min_dist


# ── Instagram source detection ────────────────────────────────────────────


def _check_ig_metadata(clip_path: Path) -> list[str]:
    """Check MP4 metadata for Instagram source markers."""
    reasons: list[str] = []
    try:
        result = subprocess.run(
            [
                "ffprobe", "-v", "quiet", "-print_format", "json",
                "-show_format", "-show_streams", str(clip_path),
            ],
            capture_output=True, text=True, timeout=15,
        )
        if result.returncode != 0:
            return reasons

        data = json.loads(result.stdout)
        raw = result.stdout.lower()

        # Check for IG markers in raw JSON output
        for marker in _IG_MARKERS:
            if marker.lower() in raw:
                reasons.append(f"Instagram metadata detected: '{marker}'")
                break

        # Check resolution signatures
        for stream in data.get("streams", []):
            if stream.get("codec_type") == "video":
                w = stream.get("width", 0)
                h = stream.get("height", 0)
                if (w, h) in _IG_RESOLUTIONS:
                    reasons.append(f"Instagram resolution signature: {w}x{h}")
                break

        # Check format tags for handler/encoder info
        tags = data.get("format", {}).get("tags", {})
        for key, val in tags.items():
            val_lower = str(val).lower()
            if any(m.lower() in val_lower for m in _IG_MARKERS):
                reasons.append(f"Instagram source in metadata tag: {key}={val}")
                break

    except Exception as e:
        logger.warning("IG metadata check failed for %s: %s", clip_path.name, e)
    return reasons


# ── Artist content detection ──────────────────────────────────────────────


def _check_artist_content(clip_path: Path, images_dir: Path | None = None) -> list[str]:
    """Check if the clip is in an artist-named folder or has artist name in filename.

    Clips downloaded from artists' social media WILL get copyright claims on YouTube.
    This is the most reliable detection method — if the folder is named after an artist,
    the content is almost certainly copyrighted.
    """
    reasons: list[str] = []

    # Get relative path from images dir to check folder structure
    base = images_dir or IMAGES_DIR
    try:
        rel = clip_path.resolve().relative_to(base.resolve())
        rel_str = str(rel).lower()
    except ValueError:
        rel_str = clip_path.name.lower()

    # Check if clip is in an artist subfolder (most reliable signal)
    # e.g. "Sexyy Red/visual_twerk.mp4" → the folder name is an artist
    parent_folder = clip_path.parent.name.lower()
    if parent_folder and parent_folder != base.name.lower():
        # It's in a subfolder — that subfolder name is likely an artist
        for marker in _COPYRIGHTED_ARTIST_MARKERS:
            if marker in parent_folder:
                artist_name = clip_path.parent.name  # Original case
                reasons.append(
                    f"In artist folder '{artist_name}' — content likely copyrighted"
                )
                break

    # Also check the filename itself for artist names
    fname_lower = clip_path.stem.lower()
    for marker in _COPYRIGHTED_ARTIST_MARKERS:
        if marker in fname_lower or marker.replace(" ", "_") in fname_lower:
            reasons.append(f"Filename contains artist name '{marker}'")
            break

    return reasons


# ── Audio fingerprinting (simple hash-based) ──────────────────────────────


def _compute_audio_hash(clip_path: Path) -> str | None:
    """
    Extract audio from a clip and compute a content hash.
    Uses ffmpeg to decode audio to raw PCM, then SHA-256.
    """
    try:
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i", str(clip_path),
                "-vn",          # no video
                "-ac", "1",     # mono
                "-ar", "8000",  # 8kHz (low — for fingerprinting, not quality)
                "-f", "s16le",  # raw PCM
                "-t", "30",     # first 30 seconds only
                "-",
            ],
            capture_output=True, timeout=30,
        )
        if result.returncode == 0 and result.stdout:
            return hashlib.sha256(result.stdout).hexdigest()
    except Exception as e:
        logger.warning("Audio hash failed for %s: %s", clip_path.name, e)
    return None


# ── Main scan functions ───────────────────────────────────────────────────


async def scan_clip(clip_path: Path, images_dir: Path | None = None) -> dict[str, Any]:
    """
    Scan a single video clip for copyright risk.
    Returns: {risk, reasons[], phashes[], audio_hash}
    """
    loop = asyncio.get_event_loop()
    name = clip_path.name
    reasons: list[str] = []
    risk = "safe"

    db = _load_db()
    flagged = db.get("flagged", {})

    # 1. Check if manually flagged (check both filename and relative path)
    base_dir = images_dir or IMAGES_DIR
    try:
        rel_path = str(clip_path.resolve().relative_to(base_dir.resolve()))
    except ValueError:
        rel_path = name

    for key in [name, rel_path]:
        if key in flagged:
            return {
                "filename": name,
                "risk": "flagged",
                "reasons": flagged[key].get("reasons", ["Manually flagged"]),
                "phashes": flagged[key].get("phashes", []),
                "audio_hash": flagged[key].get("audio_hash"),
            }

    # 2. Artist content detection (fast — path/filename check)
    artist_reasons = _check_artist_content(clip_path, base_dir)
    if artist_reasons:
        reasons.extend(artist_reasons)
        risk = "danger"  # Artist content = will get claimed on YouTube

    # 3. Instagram source detection (fast — metadata only)
    ig_reasons = await loop.run_in_executor(None, _check_ig_metadata, clip_path)
    reasons.extend(ig_reasons)
    if ig_reasons and risk != "danger":
        risk = "caution"

    # 4. Perceptual hash comparison against flagged DB
    phashes = await loop.run_in_executor(None, _compute_phashes, clip_path)

    for flagged_name, flagged_data in flagged.items():
        flagged_hashes = flagged_data.get("phashes", [])
        if not flagged_hashes:
            continue
        dist = _compare_phashes(phashes, flagged_hashes)
        if dist < DANGER_THRESHOLD:
            risk = "danger"
            reasons.append(f"Visually similar to flagged clip '{flagged_name}' (distance: {dist})")
        elif dist < CAUTION_THRESHOLD:
            if risk != "danger":
                risk = "caution"
            reasons.append(f"Partial visual match with flagged clip '{flagged_name}' (distance: {dist})")

    # 5. Audio fingerprint comparison against flagged DB
    audio_hash = await loop.run_in_executor(None, _compute_audio_hash, clip_path)
    if audio_hash:
        for flagged_name, flagged_data in flagged.items():
            if flagged_data.get("audio_hash") == audio_hash:
                risk = "danger"
                reasons.append(f"Audio matches flagged clip '{flagged_name}'")

    # Store scan result — use both filename and relative path as keys
    result = {
        "filename": name,
        "risk": risk,
        "reasons": reasons,
        "phashes": phashes,
        "audio_hash": audio_hash,
        "scanned_at": _now_iso(),
    }

    scan_entry = {
        "risk": risk,
        "reasons": reasons,
        "scanned_at": result["scanned_at"],
    }
    db["scan_results"][name] = scan_entry
    if rel_path != name:
        db["scan_results"][rel_path] = scan_entry
    _save_db(db)

    return result


async def scan_all(images_dir: Path | None = None, ws_manager=None) -> list[dict[str, Any]]:
    """Scan all video clips in images/ directory (including subdirectories)."""
    import os

    scan_dir = images_dir or IMAGES_DIR
    results: list[dict[str, Any]] = []
    clips: list[Path] = []

    # Walk subdirectories to find all video clips
    for root, _dirs, files in os.walk(scan_dir):
        root_path = Path(root)
        for fname in files:
            fpath = root_path / fname
            if fpath.is_file() and fpath.suffix.lower() in _VIDEO_EXTS:
                clips.append(fpath)

    logger.info("Copyright scan: %d clips to scan", len(clips))

    for i, clip in enumerate(sorted(clips, key=lambda f: f.name)):
        try:
            result = await scan_clip(clip, images_dir=scan_dir)
            results.append(result)
            logger.info("Scanned %s: %s (%s)", clip.name, result["risk"], ", ".join(result["reasons"]) or "clean")
        except Exception as e:
            logger.error("Scan failed for %s: %s", clip.name, e)
            results.append({
                "filename": clip.name,
                "risk": "safe",
                "reasons": [f"Scan error: {str(e)[:100]}"],
            })

        # Send progress via WebSocket if available
        if ws_manager:
            try:
                await ws_manager.broadcast({
                    "type": "copyright_scan_progress",
                    "current": i + 1,
                    "total": len(clips),
                    "filename": clip.name,
                    "risk": results[-1].get("risk", "safe"),
                })
            except Exception:
                pass

    return results


# ── Flag management ───────────────────────────────────────────────────────


async def flag_clip(filename: str, reason: str = "", images_dir: Path | None = None) -> dict[str, Any]:
    """
    Manually flag a clip as copyrighted.
    Computes pHash + audio hash and stores in DB for future matching.
    """
    clip_path = (images_dir or IMAGES_DIR) / filename
    if not clip_path.exists():
        raise FileNotFoundError(f"Clip not found: {filename}")

    loop = asyncio.get_event_loop()

    # Compute hashes for future matching
    phashes = await loop.run_in_executor(None, _compute_phashes, clip_path)
    audio_hash = await loop.run_in_executor(None, _compute_audio_hash, clip_path)

    db = _load_db()
    db["flagged"][filename] = {
        "risk": "flagged",
        "reasons": [reason] if reason else ["Manually flagged by user"],
        "flagged_at": _now_iso(),
        "phashes": phashes,
        "audio_hash": audio_hash,
    }

    # Also update scan_results to reflect the flag
    db["scan_results"][filename] = {
        "risk": "flagged",
        "reasons": db["flagged"][filename]["reasons"],
        "scanned_at": _now_iso(),
    }

    _save_db(db)

    logger.info("Flagged clip: %s (phashes: %d, audio_hash: %s)", filename, len(phashes), bool(audio_hash))

    return {
        "filename": filename,
        "risk": "flagged",
        "reasons": db["flagged"][filename]["reasons"],
        "phashes_count": len(phashes),
        "has_audio_hash": audio_hash is not None,
    }


def unflag_clip(filename: str) -> bool:
    """Remove manual flag from a clip."""
    db = _load_db()
    removed = False

    if filename in db["flagged"]:
        del db["flagged"][filename]
        removed = True

    if filename in db["scan_results"]:
        del db["scan_results"][filename]

    if removed:
        _save_db(db)
        logger.info("Unflagged clip: %s", filename)

    return removed


def get_flags() -> dict[str, Any]:
    """Get all flags and scan results."""
    return _load_db()


def get_clip_status(filename: str) -> dict[str, Any]:
    """Get copyright status for a single clip."""
    db = _load_db()

    # Check manual flags first
    if filename in db.get("flagged", {}):
        entry = db["flagged"][filename]
        return {
            "filename": filename,
            "risk": "flagged",
            "reasons": entry.get("reasons", []),
            "flagged_at": entry.get("flagged_at"),
        }

    # Check scan results
    if filename in db.get("scan_results", {}):
        entry = db["scan_results"][filename]
        return {
            "filename": filename,
            "risk": entry.get("risk", "safe"),
            "reasons": entry.get("reasons", []),
            "scanned_at": entry.get("scanned_at"),
        }

    # Not scanned yet
    return {
        "filename": filename,
        "risk": "unknown",
        "reasons": [],
    }


def remove_from_db(filename: str) -> None:
    """Remove a clip from the copyright DB entirely (used when deleting files)."""
    db = _load_db()
    changed = False
    if filename in db.get("flagged", {}):
        del db["flagged"][filename]
        changed = True
    if filename in db.get("scan_results", {}):
        del db["scan_results"][filename]
        changed = True
    if changed:
        _save_db(db)
