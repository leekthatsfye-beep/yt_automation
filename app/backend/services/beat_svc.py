"""
Beat service — reads the filesystem to build beat metadata dicts.
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
import re
import subprocess
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.backend.config import (
    BEATS_DIR,
    METADATA_DIR,
    OUTPUT_DIR,
    UPLOADS_LOG,
    SOCIAL_LOG,
    PYTHON,
    ROOT,
)

logger = logging.getLogger(__name__)


# ── helpers ──────────────────────────────────────────────────────────────

def safe_stem(filename: str) -> str:
    """
    Normalize a filename into a canonical stem.
    Mirrors safe_stem() in render.py / seo_metadata.py:
      - lowercase
      - strip punctuation except underscores
      - spaces/hyphens → underscores
      - strip leading/trailing underscores
    """
    s = Path(filename).stem.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s.strip("_")


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file, returning empty dict on any error."""
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def _audio_files(beats_dir: Path = BEATS_DIR) -> list[Path]:
    """Return all .mp3/.wav files in beats/ sorted by mtime descending."""
    files = list(beats_dir.glob("*.mp3")) + list(beats_dir.glob("*.wav"))
    files.sort(key=lambda p: p.stat().st_mtime, reverse=True)
    return files


# ── public API ───────────────────────────────────────────────────────────

def list_beats(
    beats_dir: Path = BEATS_DIR,
    metadata_dir: Path = METADATA_DIR,
    output_dir: Path = OUTPUT_DIR,
    uploads_log_path: Path = UPLOADS_LOG,
    social_log_path: Path = SOCIAL_LOG,
) -> list[dict[str, Any]]:
    """
    Return a list of beat dicts with full metadata, render status,
    upload status, and file info.  Sorted by modified date (newest first).
    """
    uploads_log = _load_json(uploads_log_path)
    social_log = _load_json(social_log_path)

    beats: list[dict[str, Any]] = []

    for audio_path in _audio_files(beats_dir):
        stem = safe_stem(audio_path.name)
        beat = _build_beat_dict(
            audio_path, stem, uploads_log, social_log,
            metadata_dir=metadata_dir, output_dir=output_dir,
        )
        beats.append(beat)

    return beats


def get_beat(
    stem: str,
    beats_dir: Path = BEATS_DIR,
    metadata_dir: Path = METADATA_DIR,
    output_dir: Path = OUTPUT_DIR,
    uploads_log_path: Path = UPLOADS_LOG,
    social_log_path: Path = SOCIAL_LOG,
) -> dict[str, Any] | None:
    """Return a single beat dict by stem, or None if not found."""
    uploads_log = _load_json(uploads_log_path)
    social_log = _load_json(social_log_path)

    for audio_path in _audio_files(beats_dir):
        if safe_stem(audio_path.name) == stem:
            return _build_beat_dict(
                audio_path, stem, uploads_log, social_log,
                metadata_dir=metadata_dir, output_dir=output_dir,
            )

    return None


async def analyze_beat(
    stem: str,
    metadata_dir: Path = METADATA_DIR,
) -> dict[str, Any]:
    """
    Run analyze_beats.py --only <stem> as a subprocess.
    Returns {"bpm": int|null, "key": str|null}.
    """
    cmd = [PYTHON, str(ROOT / "analyze_beats.py"), "--force", "--only", stem]
    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
        cwd=str(ROOT),
    )
    stdout, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error("analyze_beats.py failed: %s", stderr.decode())
        raise RuntimeError(f"Analysis failed: {stderr.decode()}")

    meta_path = metadata_dir / f"{stem}.json"
    meta = _load_json(meta_path)
    return {
        "bpm": meta.get("bpm"),
        "key": meta.get("key"),
    }


# ── internal ─────────────────────────────────────────────────────────────

def _build_beat_dict(
    audio_path: Path,
    stem: str,
    uploads_log: dict[str, Any],
    social_log: dict[str, Any],
    metadata_dir: Path = METADATA_DIR,
    output_dir: Path = OUTPUT_DIR,
) -> dict[str, Any]:
    """Assemble a full beat dict from filesystem data."""
    stat = audio_path.stat()

    # Metadata JSON
    meta_path = metadata_dir / f"{stem}.json"
    meta = _load_json(meta_path)

    # Render status
    video_path = output_dir / f"{stem}.mp4"
    thumb_path = output_dir / f"{stem}_thumb.jpg"
    rendered = video_path.exists()
    has_thumbnail = thumb_path.exists()

    # YouTube upload status
    yt_entry = uploads_log.get(stem)
    uploaded = yt_entry is not None

    # Social upload status
    social_entry = social_log.get(stem)

    beat: dict[str, Any] = {
        "stem": stem,
        "filename": audio_path.name,
        "title": meta.get("title", stem.replace("_", " ").title()),
        "beat_name": meta.get("beat_name", stem.replace("_", " ").title()),
        "artist": meta.get("artist", ""),
        "description": meta.get("description", ""),
        "tags": meta.get("tags", []),
        "bpm": meta.get("bpm"),
        "key": meta.get("key"),
        "rendered": rendered,
        "has_thumbnail": has_thumbnail,
        "uploaded": uploaded,
        "lane": meta.get("lane"),
        "seo_artist": meta.get("seo_artist", ""),
        "file_size": stat.st_size,
        "modified": datetime.fromtimestamp(stat.st_mtime, tz=timezone.utc).isoformat(),
    }

    if yt_entry:
        beat["youtube"] = {
            "videoId": yt_entry.get("videoId"),
            "url": yt_entry.get("url"),
            "uploadedAt": yt_entry.get("uploadedAt"),
            "title": yt_entry.get("title"),
            "publishAt": yt_entry.get("publishAt"),
        }

    if social_entry:
        beat["social"] = social_entry

    return beat
