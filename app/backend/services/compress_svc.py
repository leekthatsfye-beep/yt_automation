"""
compress_svc.py — Social-optimized video compression engine.

Produces smaller upload-ready variants of rendered videos using ffmpeg.
Social platforms (IG, TikTok, YouTube Shorts) re-encode everything anyway,
so uploading massive files wastes bandwidth for zero quality gain.

Preset: libx264 -preset medium -crf 24 -maxrate 4M -bufsize 8M -b:a 128k
Target: ~60-70% size reduction with no visible quality loss on phone screens.
"""

from __future__ import annotations

import asyncio
import logging
import os
import re
import time
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

# ── FFmpeg social preset ───────────────────────────────────────────────────

SOCIAL_PRESET = {
    "video_codec": "libx264",
    "preset": "medium",
    "crf": "24",
    "maxrate": "4M",
    "bufsize": "8M",
    "audio_codec": "aac",
    "audio_bitrate": "128k",
}

# Regex to parse ffmpeg progress: "time=00:02:31.45"
RE_TIME = re.compile(r"time=(\d+):(\d+):(\d+(?:\.\d+)?)")
# Regex to parse duration: "Duration: 00:03:15.20"
RE_DURATION = re.compile(r"Duration:\s*(\d+):(\d+):(\d+(?:\.\d+)?)")


def _time_to_seconds(h: str, m: str, s: str) -> float:
    return int(h) * 3600 + int(m) * 60 + float(s)


# ── Path helpers ───────────────────────────────────────────────────────────


def get_social_path(stem: str, output_dir: Path, portrait: bool = False) -> Path:
    """Return the expected social-compressed file path for a stem."""
    suffix = "_social_9x16" if portrait else "_social"
    return output_dir / f"{stem}{suffix}.mp4"


def get_all_variants(stem: str, output_dir: Path) -> dict[str, Path]:
    """Return paths for all possible video variants of a stem."""
    return {
        "original": output_dir / f"{stem}.mp4",
        "portrait": output_dir / f"{stem}_9x16.mp4",
        "social": output_dir / f"{stem}_social.mp4",
        "social_portrait": output_dir / f"{stem}_social_9x16.mp4",
    }


def get_file_sizes(stem: str, output_dir: Path) -> dict[str, Any]:
    """Return file sizes (in bytes) for all variants. Missing files → None."""
    variants = get_all_variants(stem, output_dir)
    sizes: dict[str, Any] = {}
    for key, path in variants.items():
        if path.exists():
            size = path.stat().st_size
            sizes[key] = {
                "path": str(path.name),
                "size": size,
                "size_mb": round(size / (1024 * 1024), 1),
            }
        else:
            sizes[key] = None
    return sizes


def needs_compression(stem: str, output_dir: Path) -> dict[str, Any]:
    """
    Check which social variants are missing or stale.

    Returns dict with 'landscape' and 'portrait' keys, each containing:
    - needed: bool — True if compression should run
    - reason: str — why it's needed (or "up to date")
    - source: str|None — source file to compress from
    """
    result: dict[str, Any] = {}

    # Landscape
    original = output_dir / f"{stem}.mp4"
    social = get_social_path(stem, output_dir, portrait=False)
    if not original.exists():
        result["landscape"] = {"needed": False, "reason": "No original render", "source": None}
    elif not social.exists():
        result["landscape"] = {"needed": True, "reason": "Social variant missing", "source": str(original.name)}
    elif social.stat().st_mtime < original.stat().st_mtime:
        result["landscape"] = {"needed": True, "reason": "Social variant stale", "source": str(original.name)}
    else:
        result["landscape"] = {"needed": False, "reason": "Up to date", "source": None}

    # Portrait
    portrait_src = output_dir / f"{stem}_9x16.mp4"
    social_portrait = get_social_path(stem, output_dir, portrait=True)
    if not portrait_src.exists():
        result["portrait"] = {"needed": False, "reason": "No portrait render", "source": None}
    elif not social_portrait.exists():
        result["portrait"] = {"needed": True, "reason": "Social variant missing", "source": str(portrait_src.name)}
    elif social_portrait.stat().st_mtime < portrait_src.stat().st_mtime:
        result["portrait"] = {"needed": True, "reason": "Social variant stale", "source": str(portrait_src.name)}
    else:
        result["portrait"] = {"needed": False, "reason": "Up to date", "source": None}

    return result


# ── Compression engine ─────────────────────────────────────────────────────


async def compress_for_social(
    input_path: Path,
    output_path: Path,
    on_progress: Any | None = None,
) -> dict[str, Any]:
    """
    Compress a video for social upload using optimized ffmpeg settings.

    Args:
        input_path:  Source video (original render or portrait variant).
        output_path: Destination for compressed variant.
        on_progress: Optional async callback(pct: int, detail: str).

    Returns:
        dict with output, size_before, size_after, reduction_pct, duration_ms
    """
    if not input_path.exists():
        raise FileNotFoundError(f"Source video not found: {input_path}")

    output_path.parent.mkdir(parents=True, exist_ok=True)

    size_before = input_path.stat().st_size

    # Build ffmpeg command
    cmd = [
        "ffmpeg",
        "-y",  # overwrite
        "-i", str(input_path),
        "-c:v", SOCIAL_PRESET["video_codec"],
        "-preset", SOCIAL_PRESET["preset"],
        "-crf", SOCIAL_PRESET["crf"],
        "-maxrate", SOCIAL_PRESET["maxrate"],
        "-bufsize", SOCIAL_PRESET["bufsize"],
        "-c:a", SOCIAL_PRESET["audio_codec"],
        "-b:a", SOCIAL_PRESET["audio_bitrate"],
        "-movflags", "+faststart",
        str(output_path),
    ]

    logger.info("Compressing: %s → %s", input_path.name, output_path.name)
    start = time.monotonic()

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Parse stderr for progress (ffmpeg writes progress to stderr)
    duration_secs: float | None = None
    assert proc.stderr is not None

    while True:
        line = await proc.stderr.readline()
        if not line:
            break
        text = line.decode(errors="replace").strip()

        # Get total duration (appears early in output)
        if duration_secs is None:
            m = RE_DURATION.search(text)
            if m:
                duration_secs = _time_to_seconds(m.group(1), m.group(2), m.group(3))

        # Parse time= progress
        m = RE_TIME.search(text)
        if m and duration_secs and duration_secs > 0:
            current = _time_to_seconds(m.group(1), m.group(2), m.group(3))
            pct = min(95, int((current / duration_secs) * 100))
            if on_progress:
                await on_progress(pct, f"Encoding... {pct}%")

    await proc.wait()

    elapsed_ms = round((time.monotonic() - start) * 1000)

    if proc.returncode != 0:
        # Read any remaining stderr
        remaining = await proc.stderr.read() if proc.stderr else b""
        err_text = remaining.decode(errors="replace")[:500]
        logger.error("Compression failed for %s: %s", input_path.name, err_text)
        # Clean up partial output
        if output_path.exists():
            output_path.unlink()
        raise RuntimeError(f"ffmpeg failed (code {proc.returncode}): {err_text}")

    if not output_path.exists():
        raise RuntimeError(f"Output file not created: {output_path}")

    size_after = output_path.stat().st_size
    reduction_pct = round((1 - size_after / size_before) * 100, 1) if size_before > 0 else 0

    logger.info(
        "Compressed %s: %.1fMB → %.1fMB (%.1f%% smaller) in %dms",
        input_path.name,
        size_before / (1024 * 1024),
        size_after / (1024 * 1024),
        reduction_pct,
        elapsed_ms,
    )

    if on_progress:
        await on_progress(100, "Compression complete")

    return {
        "output": str(output_path.name),
        "size_before": size_before,
        "size_after": size_after,
        "size_before_mb": round(size_before / (1024 * 1024), 1),
        "size_after_mb": round(size_after / (1024 * 1024), 1),
        "reduction_pct": reduction_pct,
        "duration_ms": elapsed_ms,
    }


async def compress_stem(
    stem: str,
    output_dir: Path,
    portrait: bool = False,
    on_progress: Any | None = None,
) -> dict[str, Any]:
    """
    Compress a stem's video for social upload.

    Automatically picks the right source (landscape or portrait) and
    generates the appropriate social variant.
    """
    if portrait:
        source = output_dir / f"{stem}_9x16.mp4"
    else:
        source = output_dir / f"{stem}.mp4"

    dest = get_social_path(stem, output_dir, portrait=portrait)
    return await compress_for_social(source, dest, on_progress=on_progress)
