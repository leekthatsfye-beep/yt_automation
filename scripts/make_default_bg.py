"""
make_default_bg.py — generate images/default.jpg, a clean 1920x1080 branded
background (dark radial-ish gradient + centered FY3 logo). Used as the
still-image fallback in render.py when no visualizer clip is available.

Usage:
    python scripts/make_default_bg.py [path_to_logo.png]
"""
from __future__ import annotations

import sys
from pathlib import Path

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
OUT = ROOT / "images" / "default.jpg"
W, H = 1920, 1080

DEFAULT_LOGO = Path.home() / "Downloads" / "fy3_logo_transparent.png"


def make_gradient(w: int, h: int) -> Image.Image:
    """Vertical dark gradient: near-black top -> deep charcoal center -> black bottom."""
    base = Image.new("RGB", (w, h), (0, 0, 0))
    draw = ImageDraw.Draw(base)
    cy = h / 2
    for y in range(h):
        # distance from center, 0 at middle -> 1 at edges
        d = abs(y - cy) / cy
        v = int(28 * (1 - d))  # brightest ~28 at center, 0 at edges
        draw.line([(0, y), (w, y)], fill=(v, v, v + 4))
    return base


def main() -> None:
    logo_path = Path(sys.argv[1]) if len(sys.argv) > 1 else DEFAULT_LOGO
    bg = make_gradient(W, H)

    if logo_path.exists():
        logo = Image.open(logo_path).convert("RGBA")
        # Scale logo to ~38% of frame width
        target_w = int(W * 0.38)
        ratio = target_w / logo.width
        logo = logo.resize((target_w, int(logo.height * ratio)), Image.LANCZOS)
        x = (W - logo.width) // 2
        y = (H - logo.height) // 2
        bg.paste(logo, (x, y), logo)
        print(f"[OK] logo composited from {logo_path.name}")
    else:
        print(f"[WARN] logo not found at {logo_path} — plain gradient only")

    OUT.parent.mkdir(parents=True, exist_ok=True)
    bg.save(OUT, "JPEG", quality=92)
    print(f"[DONE] wrote {OUT}  ({W}x{H})")


if __name__ == "__main__":
    main()
