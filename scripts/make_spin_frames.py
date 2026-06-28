#!/usr/bin/env python3
"""
make_spin_frames.py  —  Windows-side rebuild of the FY3 spinning-logo frames.

render_lit.py reads pre-rendered transparent PNG frames from
    brand/fy3_spin_frames_clean/f_*.png
(those were gitignored, so they never came over from the Mac).

This rebuilds them by reusing the EXACT render functions from the original
generate_spinning_logo.py (_render_flat_logo / _apply_y_rotation / _add_glow),
so the pixels match the Mac. The only change is the font path: the Mac used
~/Library/Fonts/HarryP.ttf; here we use the project-local HarryP.ttf.

Output: brand/fy3_spin_frames_clean/f_0000.png .. f_0089.png  (90 frames, 3s @30fps loop)

Usage (from C:\\yt_automation):
    .venv\\Scripts\\python.exe scripts\\make_spin_frames.py
"""
import sys
from pathlib import Path

from PIL import Image

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

import generate_spinning_logo as gsl  # the original Mac generator

# Point the generator at the project-local HarryP.ttf (same font, Windows path).
FONT_LOCAL = ROOT / "HarryP.ttf"
if not FONT_LOCAL.exists():
    sys.exit(f"ERROR: {FONT_LOCAL} not found. Drop HarryP.ttf in {ROOT}.")
gsl.FONT = FONT_LOCAL

OUT_DIR = ROOT / "brand" / "fy3_spin_frames_clean"


def main():
    print("FY3 spin-frame rebuild (Windows)")
    print(f"  Font:   {gsl.FONT}")
    print(f"  Frames: {gsl.NUM_FRAMES} @ {gsl.FPS}fps = {gsl.DURATION_SEC}s loop")
    print(f"  Canvas: {gsl.CANVAS_W}x{gsl.CANVAS_H}")
    print(f"  Out:    {OUT_DIR}\n")

    OUT_DIR.mkdir(parents=True, exist_ok=True)
    # clear any stale frames so frame count stays exact
    for old in OUT_DIR.glob("f_*.png"):
        old.unlink()

    # --- identical setup to generate_spinning_logo.generate() ---
    flat_logo = gsl._render_flat_logo()

    logo_scale = (gsl.CANVAS_H - 20) / flat_logo.height
    logo_w = int(flat_logo.width * logo_scale)
    logo_h = int(flat_logo.height * logo_scale)
    flat_logo = flat_logo.resize((logo_w, logo_h), Image.LANCZOS)

    padded = Image.new("RGBA", (gsl.CANVAS_W, gsl.CANVAS_H), (0, 0, 0, 0))
    px = (gsl.CANVAS_W - logo_w) // 2
    py = (gsl.CANVAS_H - logo_h) // 2
    padded.paste(flat_logo, (px, py), flat_logo)

    for i in range(gsl.NUM_FRAMES):
        angle = (i / gsl.NUM_FRAMES) * 360.0
        rotated = gsl._apply_y_rotation(padded, angle)
        frame = gsl._add_glow(rotated)
        frame.save(OUT_DIR / f"f_{i:04d}.png", "PNG")
        if (i + 1) % 15 == 0:
            print(f"  Frame {i+1}/{gsl.NUM_FRAMES}")

    print(f"\n  Done — {gsl.NUM_FRAMES} frames in {OUT_DIR}")


if __name__ == "__main__":
    main()
