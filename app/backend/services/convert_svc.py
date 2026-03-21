"""
Dimension conversion service — convert rendered 16:9 videos to social media presets.

Presets:
  9x16  → 1080x1920  (TikTok, Reels, Shorts)
  4x5   → 1080x1350  (IG Feed)
  1x1   → 1080x1080  (IG Square, X/Twitter)

Uses the same fast-blur technique as social_upload.py:
  Scale down to 1/8 then back up = blur (10x faster than boxblur).
"""

from __future__ import annotations

import asyncio
import json
import logging
import os
from pathlib import Path
from typing import Any, Callable, Awaitable

logger = logging.getLogger(__name__)

# ── Preset definitions ───────────────────────────────────────────────────

DIMENSION_PRESETS: dict[str, dict[str, Any]] = {
    "9x16": {
        "width": 1080,
        "height": 1920,
        "suffix": "_9x16",
        "label": "9:16 Portrait",
        "platforms": ["TikTok", "Reels", "Shorts"],
    },
    "4x5": {
        "width": 1080,
        "height": 1350,
        "suffix": "_4x5",
        "label": "4:5 Feed",
        "platforms": ["Instagram Feed"],
    },
    "1x1": {
        "width": 1080,
        "height": 1080,
        "suffix": "_1x1",
        "label": "1:1 Square",
        "platforms": ["Instagram Square", "X/Twitter"],
    },
}

ProgressCallback = Callable[[int, str], Awaitable[None]] | None


# ── ffprobe helpers ──────────────────────────────────────────────────────


async def _get_duration(path: Path) -> float:
    """Get video duration in seconds via ffprobe."""
    proc = await asyncio.create_subprocess_exec(
        "ffprobe", "-v", "quiet", "-print_format", "json",
        "-show_format", str(path),
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    stdout, _ = await proc.communicate()
    if proc.returncode != 0:
        return 0.0
    data = json.loads(stdout.decode())
    return float(data.get("format", {}).get("duration", 0))


# ── Core conversion ─────────────────────────────────────────────────────


async def convert_dimension(
    source: Path,
    output: Path,
    width: int,
    height: int,
    brand_dir: Path | None = None,
    progress_cb: ProgressCallback = None,
) -> dict[str, Any]:
    """
    Convert a 16:9 video to a target dimension using blur-bg + centered overlay.
    Optionally overlays spinning FY3 logo at bottom-center.
    """
    bw, bh = width // 8, height // 8  # Blur dimensions (1/8 scale)

    # Build filter chain
    # Background: scale to fill → crop → scale down 1/8 → scale back up (fast blur)
    bg = (
        f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
        f"crop={width}:{height},"
        f"scale={bw}:{bh},scale={width}:{height},"
        f"format=yuv420p[bg]"
    )

    # Foreground: scale to fit width, preserve aspect
    fg = f"[0:v]scale={width}:-2,format=yuva420p[fg]"

    # Check for spinning logo
    spin_logo = None
    if brand_dir:
        logo_path = brand_dir / "fy3_spin.mov"
        if logo_path.exists():
            spin_logo = logo_path

    if spin_logo:
        overlay = "[bg][fg]overlay=(W-w)/2:(H-h)/2[comp]"
        logo_overlay = f"[comp][1:v]overlay=(W-w)/2:H-h-20,format=yuv420p[out]"
        filter_complex = f"{bg};{fg};{overlay};{logo_overlay}"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(source),
            "-stream_loop", "-1", "-i", str(spin_logo),
            "-filter_complex", filter_complex,
            "-map", "[out]", "-map", "0:a:0",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-r", "30",
            "-shortest",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            str(output),
        ]
    else:
        overlay = "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[out]"
        filter_complex = f"{bg};{fg};{overlay}"

        cmd = [
            "ffmpeg", "-y",
            "-i", str(source),
            "-filter_complex", filter_complex,
            "-map", "[out]", "-map", "0:a:0",
            "-c:v", "libx264", "-preset", "fast", "-crf", "20",
            "-c:a", "aac", "-b:a", "192k",
            "-r", "30",
            "-movflags", "+faststart",
            "-progress", "pipe:1",
            str(output),
        ]

    duration = await _get_duration(source)

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    # Parse progress from ffmpeg -progress pipe:1
    while True:
        line = await proc.stdout.readline()
        if not line:
            break
        text = line.decode(errors="replace").strip()
        if text.startswith("out_time_us=") and duration > 0 and progress_cb:
            try:
                us = int(text.split("=")[1])
                pct = min(99, int((us / 1_000_000) / duration * 100))
                await progress_cb(pct, f"Encoding... {pct}%")
            except (ValueError, ZeroDivisionError):
                pass

    await proc.wait()
    stderr_text = (await proc.stderr.read()).decode(errors="replace")

    if proc.returncode != 0:
        logger.error("Conversion failed: %s", stderr_text[:500])
        raise RuntimeError(f"ffmpeg failed: {stderr_text[:200]}")

    if not output.exists():
        raise RuntimeError(f"Output file not created: {output}")

    size_mb = round(output.stat().st_size / (1024 * 1024), 1)

    return {
        "output": str(output),
        "width": width,
        "height": height,
        "size_mb": size_mb,
    }


# ── Status check ─────────────────────────────────────────────────────────


def get_dimension_status(stem: str, output_dir: Path) -> dict[str, Any]:
    """Return which dimension presets exist for a stem, with file sizes."""
    result: dict[str, Any] = {"stem": stem}

    # Original
    orig = output_dir / f"{stem}.mp4"
    if orig.exists():
        result["original"] = {
            "exists": True,
            "size_mb": round(orig.stat().st_size / (1024 * 1024), 1),
        }
    else:
        result["original"] = {"exists": False}

    # Each preset
    for key, preset in DIMENSION_PRESETS.items():
        path = output_dir / f"{stem}{preset['suffix']}.mp4"
        if path.exists():
            result[key] = {
                "exists": True,
                "size_mb": round(path.stat().st_size / (1024 * 1024), 1),
                "label": preset["label"],
                "platforms": preset["platforms"],
            }
        else:
            result[key] = {
                "exists": False,
                "label": preset["label"],
                "platforms": preset["platforms"],
            }

    return result
