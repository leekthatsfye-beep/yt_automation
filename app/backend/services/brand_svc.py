"""
Brand Builder Service — generate producer logos and manage brand assets.

Generates text-based logos using FFmpeg (text overlays with effects),
and manages brand assets like thumbnails stamps, watermarks, and intros.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

logger = logging.getLogger(__name__)

BRAND_PRESETS = {
    "gold_metallic": {
        "label": "Gold Metallic",
        "font_color": "#FFD700",
        "border_color": "#B8860B",
        "shadow_color": "#8B6914",
        "bg_color": "black",
        "glow": True,
    },
    "ice_white": {
        "label": "Ice White",
        "font_color": "#FFFFFF",
        "border_color": "#E0E0E0",
        "shadow_color": "#808080",
        "bg_color": "black",
        "glow": True,
    },
    "neon_purple": {
        "label": "Neon Purple",
        "font_color": "#8B5CF6",
        "border_color": "#7C3AED",
        "shadow_color": "#6D28D9",
        "bg_color": "black",
        "glow": True,
    },
    "blood_red": {
        "label": "Blood Red",
        "font_color": "#DC2626",
        "border_color": "#991B1B",
        "shadow_color": "#7F1D1D",
        "bg_color": "black",
        "glow": True,
    },
    "clean_minimal": {
        "label": "Clean Minimal",
        "font_color": "#FFFFFF",
        "border_color": "#FFFFFF",
        "shadow_color": "#333333",
        "bg_color": "#111111",
        "glow": False,
    },
    "emerald": {
        "label": "Emerald",
        "font_color": "#10B981",
        "border_color": "#059669",
        "shadow_color": "#047857",
        "bg_color": "black",
        "glow": True,
    },
}

# Font paths for macOS
_FONT_PATHS = [
    "/System/Library/Fonts/Supplemental/Impact.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial.ttf",
    "/System/Library/Fonts/Helvetica.ttc",
]


def _find_font() -> str:
    for p in _FONT_PATHS:
        if Path(p).exists():
            return p
    return "Arial"


async def generate_logo(
    text: str,
    preset: str,
    brand_dir: Path,
    width: int = 1200,
    height: int = 400,
    font_size: int = 120,
) -> dict[str, Any]:
    """Generate a text-based logo image using FFmpeg.

    Returns path to the generated logo file.
    """
    brand_dir.mkdir(parents=True, exist_ok=True)
    style = BRAND_PRESETS.get(preset, BRAND_PRESETS["gold_metallic"])
    font = _find_font()

    safe_name = text.lower().replace(" ", "_").replace("!", "")
    output_path = brand_dir / f"logo_{safe_name}_{preset}.png"

    # Build FFmpeg drawtext filter
    # Layer 1: Shadow
    shadow = (
        f"drawtext=text='{text}':fontfile='{font}':fontsize={font_size}"
        f":fontcolor={style['shadow_color']}:x=(w-text_w)/2+4:y=(h-text_h)/2+4"
    )
    # Layer 2: Border/outline
    border = (
        f"drawtext=text='{text}':fontfile='{font}':fontsize={font_size}"
        f":fontcolor={style['border_color']}:borderw=3:bordercolor={style['border_color']}"
        f":x=(w-text_w)/2:y=(h-text_h)/2"
    )
    # Layer 3: Main text
    main = (
        f"drawtext=text='{text}':fontfile='{font}':fontsize={font_size}"
        f":fontcolor={style['font_color']}:x=(w-text_w)/2:y=(h-text_h)/2"
    )

    filtergraph = f"{shadow},{border},{main}"

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c={style['bg_color']}:s={width}x{height}:d=1",
        "-vf", filtergraph,
        "-frames:v", "1",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    _, stderr = await proc.communicate()

    if proc.returncode != 0:
        logger.error("Logo generation failed: %s", stderr.decode()[-500:])
        return {"success": False, "error": "FFmpeg logo generation failed"}

    size_kb = round(output_path.stat().st_size / 1024, 1)

    return {
        "success": True,
        "path": str(output_path.relative_to(brand_dir.parent)),
        "filename": output_path.name,
        "preset": preset,
        "preset_label": style["label"],
        "text": text,
        "size_kb": size_kb,
        "dimensions": f"{width}x{height}",
    }


async def generate_thumb_stamp(
    text: str,
    brand_dir: Path,
    font_color: str = "#FFFFFF",
    size: int = 200,
) -> dict[str, Any]:
    """Generate a small corner stamp for thumbnails."""
    brand_dir.mkdir(parents=True, exist_ok=True)
    font = _find_font()
    safe_name = text.lower().replace(" ", "_").replace("!", "")
    output_path = brand_dir / f"{safe_name}_thumb_stamp.png"

    filtergraph = (
        f"drawtext=text='{text}':fontfile='{font}':fontsize=48"
        f":fontcolor={font_color}:borderw=2:bordercolor=black"
        f":x=(w-text_w)/2:y=(h-text_h)/2"
    )

    cmd = [
        "ffmpeg", "-y",
        "-f", "lavfi",
        "-i", f"color=c=black@0.0:s={size}x{size}:d=1",
        "-vf", filtergraph,
        "-frames:v", "1",
        str(output_path),
    ]

    proc = await asyncio.create_subprocess_exec(
        *cmd,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )
    await proc.communicate()

    if proc.returncode != 0:
        return {"success": False, "error": "Stamp generation failed"}

    return {
        "success": True,
        "path": str(output_path.relative_to(brand_dir.parent)),
        "filename": output_path.name,
        "text": text,
    }


def list_brand_assets(brand_dir: Path) -> dict[str, Any]:
    """List all brand assets in the brand directory."""
    if not brand_dir.exists():
        return {"assets": [], "total": 0}

    assets: list[dict] = []
    for f in sorted(brand_dir.iterdir()):
        if f.name.startswith("."):
            continue
        ext = f.suffix.lower()
        if ext not in {".png", ".jpg", ".jpeg", ".mov", ".mp4", ".gif"}:
            continue

        asset_type = "logo" if "logo" in f.name else "stamp" if "stamp" in f.name else "spin" if "spin" in f.name else "asset"
        assets.append({
            "filename": f.name,
            "path": str(f.relative_to(brand_dir.parent)),
            "type": asset_type,
            "size_kb": round(f.stat().st_size / 1024, 1),
            "ext": ext,
        })

    return {"assets": assets, "total": len(assets)}


def get_presets() -> list[dict[str, str]]:
    """Return available logo presets."""
    return [
        {"id": k, "label": v["label"], "font_color": v["font_color"], "bg_color": v["bg_color"]}
        for k, v in BRAND_PRESETS.items()
    ]
