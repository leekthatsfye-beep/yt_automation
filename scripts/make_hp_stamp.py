#!/usr/bin/env python3
"""
make_hp_stamp.py
================
Rebuilds brand/fy3_hp_stamp.png — the static FY3! "Harry P" stamp that
render_lit.py's make_thumbnail() composites bottom-center on the still
thumbnail. (The video itself uses the animated fy3_spin_frames_clean logo.)

Source: the transparent gold FY3! logo. We add a soft dark drop shadow +
outer glow so the gold reads on both light and dark thumbnail areas.

Run:  .venv\\Scripts\\python.exe scripts\\make_hp_stamp.py
"""
from pathlib import Path
from PIL import Image, ImageFilter

ROOT      = Path(__file__).resolve().parent.parent
OUT       = ROOT / "brand" / "fy3_hp_stamp.png"

# Source logo candidates, first that exists wins.
SOURCES = [
    Path.home() / "Downloads" / "fy3_logo_transparent.png",
    ROOT / "brand" / "fy3_spin_frames_clean" / "f_0000.png",
]

TARGET_W = 240   # logo width on the 1920-wide thumbnail (~12.5%, matches reference)
PAD      = 32    # transparent padding around so shadow/glow isn't clipped


def load_logo() -> Image.Image:
    for src in SOURCES:
        if src.exists():
            logo = Image.open(src).convert("RGBA")
            bbox = logo.getbbox()
            if bbox:
                logo = logo.crop(bbox)
            return logo
    raise FileNotFoundError(
        "No source logo found. Looked in:\n  " + "\n  ".join(str(s) for s in SOURCES)
    )


def main():
    logo = load_logo()
    # scale to target width, keep aspect
    w, h = logo.size
    new_w = TARGET_W
    new_h = int(h * new_w / w)
    logo = logo.resize((new_w, new_h), Image.LANCZOS)

    canvas_w = new_w + PAD * 2
    canvas_h = new_h + PAD * 2
    canvas = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    # --- shadow layer: black silhouette from logo alpha, blurred ---
    alpha = logo.split()[3]
    shadow = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    black = Image.new("RGBA", logo.size, (0, 0, 0, 255))
    # soft wide glow (legibility halo)
    glow = shadow.copy()
    glow.paste(black, (PAD, PAD), alpha)
    glow = glow.filter(ImageFilter.GaussianBlur(7))
    # tighter drop shadow, offset down a touch
    drop = shadow.copy()
    drop.paste(black, (PAD, PAD + 3), alpha)
    drop = drop.filter(ImageFilter.GaussianBlur(3))

    canvas = Image.alpha_composite(canvas, glow)
    canvas = Image.alpha_composite(canvas, drop)
    # --- sharp gold logo on top ---
    canvas.alpha_composite(logo, (PAD, PAD))

    OUT.parent.mkdir(parents=True, exist_ok=True)
    canvas.save(OUT, "PNG")
    print(f"[OK] {OUT}  ({canvas_w}x{canvas_h})")


if __name__ == "__main__":
    main()
