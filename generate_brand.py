#!/usr/bin/env python3
"""
FY3 Brand Logo Generator
========================
Takes the existing FY3! logo and creates professional variants:
  1. Clean logo on black (profile pic / avatar)
  2. Fire glow edition (main brand logo)
  3. Neon glow edition (alternate)
  4. Watermark (semi-transparent, for video overlays)
  5. YouTube banner (2560x1440)
  6. Thumbnail watermark (small corner stamp)

Uses the existing FYE.png (red bubbly "FY3!" with transparency).
"""
import os, sys, math, random
from pathlib import Path

# ── paths ───────────────────────────────────────────────────────────
SRC_LOGO   = Path.home() / "Documents" / "FYE.png"
OUT_DIR    = Path(__file__).resolve().parent / "brand"
OUT_DIR.mkdir(exist_ok=True)

from PIL import Image, ImageDraw, ImageFont, ImageFilter, ImageEnhance, ImageChops
import numpy as np

random.seed(42)  # reproducible embers


# ════════════════════════════════════════════════════════════════════
#  HELPERS
# ════════════════════════════════════════════════════════════════════

def _load_logo(size: int = 800) -> Image.Image:
    """Load FYE.png, crop to content, resize to fit within `size`."""
    logo = Image.open(SRC_LOGO).convert("RGBA")
    bbox = logo.getbbox()
    if bbox:
        logo = logo.crop(bbox)
    logo.thumbnail((size, size), Image.LANCZOS)
    return logo


def _make_glow(logo: Image.Image, color: tuple, radius: int, opacity: float = 1.0) -> Image.Image:
    """
    Create a clean glow layer: solid color, shaped by logo alpha, gaussian blurred.
    Much brighter than the old _colorize approach.
    """
    w, h = logo.size
    # extract alpha channel as luminance mask
    alpha = np.array(logo)[:, :, 3].astype(np.float32) / 255.0

    # build solid color layer at full brightness
    layer = np.zeros((h, w, 4), dtype=np.float32)
    layer[:, :, 0] = color[0]
    layer[:, :, 1] = color[1]
    layer[:, :, 2] = color[2]
    layer[:, :, 3] = alpha * 255.0 * opacity

    glow_img = Image.fromarray(layer.astype(np.uint8), "RGBA")

    # blur multiple passes for soft spread
    for _ in range(4):
        glow_img = glow_img.filter(ImageFilter.GaussianBlur(radius))

    return glow_img


def _fire_gradient_logo(logo: Image.Image) -> Image.Image:
    """Apply a bright fire gradient (yellow top → orange mid → red bottom) masked to logo shape."""
    w, h = logo.size
    alpha = np.array(logo)[:, :, 3]

    arr = np.zeros((h, w, 4), dtype=np.uint8)
    for y in range(h):
        t = y / max(h - 1, 1)  # 0=top, 1=bottom
        if t < 0.25:
            # bright yellow
            r, g, b = 255, 255, int(100 + 155 * (1 - t / 0.25))
        elif t < 0.5:
            # yellow → bright orange
            frac = (t - 0.25) / 0.25
            r, g, b = 255, int(255 - 120 * frac), int(100 * (1 - frac))
        elif t < 0.75:
            # orange → red
            frac = (t - 0.5) / 0.25
            r, g, b = 255, int(135 - 100 * frac), 0
        else:
            # red → deep red
            frac = (t - 0.75) / 0.25
            r = int(255 - 60 * frac)
            g, b = int(35 * (1 - frac)), 0
        arr[y, :] = [r, g, b, 255]

    arr[:, :, 3] = alpha
    return Image.fromarray(arr, "RGBA")


def _particle_embers(w: int, h: int, count: int = 200, zone: str = "full") -> Image.Image:
    """Draw bright fire ember particles. zone='upper' biases upward."""
    canvas = Image.new("RGBA", (w, h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(canvas)
    for _ in range(count):
        x = random.randint(int(w * 0.15), int(w * 0.85))
        if zone == "upper":
            y = random.randint(0, int(h * 0.55))
        else:
            y = random.randint(int(h * 0.1), int(h * 0.8))
        size = random.randint(2, 6)
        # bright orange-yellow palette
        r = random.randint(230, 255)
        g = random.randint(120, 240)
        b = random.randint(0, 60)
        alpha = random.randint(150, 255)
        draw.ellipse([x, y, x + size, y + size], fill=(r, g, b, alpha))
    canvas = canvas.filter(ImageFilter.GaussianBlur(2))
    return canvas


def _center_paste(bg: Image.Image, fg: Image.Image, y_offset: int = 0) -> Image.Image:
    """Paste fg centered on bg."""
    result = bg.copy()
    x = (bg.width - fg.width) // 2
    y = (bg.height - fg.height) // 2 + y_offset
    result.paste(fg, (x, y), fg)
    return result


def _additive_composite(bg: Image.Image, layer: Image.Image) -> Image.Image:
    """Screen/additive blend — brightens the background where layer is bright."""
    bg_arr = np.array(bg, dtype=np.float32)
    ly_arr = np.array(layer, dtype=np.float32)

    # premultiply layer by its own alpha
    la = ly_arr[:, :, 3:4] / 255.0
    ly_rgb = ly_arr[:, :, :3] * la

    # screen blend: result = bg + layer - (bg * layer / 255)
    bg_rgb = bg_arr[:, :, :3]
    out_rgb = bg_rgb + ly_rgb - (bg_rgb * ly_rgb / 255.0)
    out_rgb = np.clip(out_rgb, 0, 255)

    bg_arr[:, :, :3] = out_rgb
    return Image.fromarray(bg_arr.astype(np.uint8), "RGBA")


# ════════════════════════════════════════════════════════════════════
#  1. CLEAN ON BLACK
# ════════════════════════════════════════════════════════════════════

def gen_clean(size: int = 1024):
    """Clean FY3! logo centered on black with subtle red glow."""
    logo = _load_logo(int(size * 0.7))
    bg = Image.new("RGBA", (size, size), (5, 0, 0, 255))

    # subtle red glow behind
    glow = _make_glow(logo, (180, 0, 0), radius=25, opacity=0.6)
    bg_glow = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    bg_glow = _center_paste(bg_glow, glow)
    bg = _additive_composite(bg, bg_glow)

    result = _center_paste(bg, logo)
    out = OUT_DIR / "fy3_clean.png"
    result.save(out, "PNG")
    print(f"  [1] Clean on black → {out}")
    return result


# ════════════════════════════════════════════════════════════════════
#  2. FIRE GLOW EDITION
# ════════════════════════════════════════════════════════════════════

def gen_fire(size: int = 1024):
    """FY3! with bright fire glow, embers, and fire gradient text."""
    logo = _load_logo(int(size * 0.65))

    bg = Image.new("RGBA", (size, size), (8, 1, 0, 255))

    # LAYER 1: massive soft red-orange outer glow (very wide spread)
    glow_far = _make_glow(logo, (200, 40, 0), radius=50, opacity=1.0)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    layer = _center_paste(layer, glow_far)
    bg = _additive_composite(bg, layer)

    # LAYER 2: medium orange glow
    glow_mid = _make_glow(logo, (255, 120, 0), radius=25, opacity=1.0)
    layer2 = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    layer2 = _center_paste(layer2, glow_mid)
    bg = _additive_composite(bg, layer2)

    # LAYER 3: tight bright yellow glow (hot core)
    glow_hot = _make_glow(logo, (255, 230, 50), radius=10, opacity=0.9)
    layer3 = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    layer3 = _center_paste(layer3, glow_hot)
    bg = _additive_composite(bg, layer3)

    # embers rising above
    embers = _particle_embers(size, size, count=200, zone="upper")
    bg = _additive_composite(bg, embers)

    # THE LOGO — fire gradient fill (yellow top → red bottom)
    fire_logo = _fire_gradient_logo(logo)
    result = _center_paste(bg, fire_logo)

    # light edge vignette (just corners, don't darken center)
    vignette = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    vdraw = ImageDraw.Draw(vignette)
    cx, cy = size // 2, size // 2
    max_r = int(size * 0.72)
    for r in range(max_r, int(max_r * 0.6), -1):
        t = 1.0 - (r / max_r)
        alpha = int(min(120, t * t * 200))
        vdraw.ellipse([cx - r, cy - r, cx + r, cy + r], fill=(0, 0, 0, alpha))
    result = Image.alpha_composite(result, vignette)

    out = OUT_DIR / "fy3_fire.png"
    result.save(out, "PNG")
    print(f"  [2] Fire glow edition → {out}")
    return result


# ════════════════════════════════════════════════════════════════════
#  3. NEON GLOW EDITION
# ════════════════════════════════════════════════════════════════════

def gen_neon(size: int = 1024):
    """FY3! with electric neon red + pink glow on dark background."""
    logo = _load_logo(int(size * 0.65))
    bg = Image.new("RGBA", (size, size), (5, 0, 8, 255))

    # wide hot pink glow
    glow1 = _make_glow(logo, (255, 0, 100), radius=40, opacity=1.0)
    layer = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    layer = _center_paste(layer, glow1)
    bg = _additive_composite(bg, layer)

    # medium magenta glow
    glow2 = _make_glow(logo, (255, 50, 200), radius=18, opacity=0.8)
    layer2 = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    layer2 = _center_paste(layer2, glow2)
    bg = _additive_composite(bg, layer2)

    # tight white-pink core
    glow3 = _make_glow(logo, (255, 200, 230), radius=6, opacity=0.7)
    layer3 = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    layer3 = _center_paste(layer3, glow3)
    bg = _additive_composite(bg, layer3)

    # paste original red logo on top (sharp and vivid)
    result = _center_paste(bg, logo)

    out = OUT_DIR / "fy3_neon.png"
    result.save(out, "PNG")
    print(f"  [3] Neon glow edition → {out}")
    return result


# ════════════════════════════════════════════════════════════════════
#  4. WATERMARK (semi-transparent for video overlays)
# ════════════════════════════════════════════════════════════════════

def gen_watermark(size: int = 400):
    """Semi-transparent white FY3! for corner watermark."""
    logo = _load_logo(size)
    arr = np.array(logo, dtype=np.float32)
    # make white, keep shape
    mask = arr[:, :, 3] > 30
    arr[mask, 0] = 255
    arr[mask, 1] = 255
    arr[mask, 2] = 255
    arr[:, :, 3] *= 0.35
    result = Image.fromarray(arr.astype(np.uint8), "RGBA")
    out = OUT_DIR / "fy3_watermark.png"
    result.save(out, "PNG")
    print(f"  [4] Watermark (35% opacity) → {out}")
    return result


# ════════════════════════════════════════════════════════════════════
#  5. YOUTUBE BANNER (2560x1440)
# ════════════════════════════════════════════════════════════════════

def gen_banner():
    """YouTube channel banner with centered FY3! and fire atmosphere."""
    W, H = 2560, 1440
    logo = _load_logo(550)

    bg = Image.new("RGBA", (W, H), (8, 1, 0, 255))

    # radial gradient center hotspot
    grad = np.zeros((H, W, 4), dtype=np.uint8)
    cx, cy = W // 2, H // 2 - 50
    for y in range(H):
        for x in range(0, W, 4):  # skip every 4 for speed
            d = math.sqrt((x - cx) ** 2 + ((y - cy) * 1.5) ** 2) / (W * 0.4)
            if d < 1.0:
                brightness = int(40 * (1 - d))
                grad[y, x:x+4] = [brightness, int(brightness * 0.2), 0, 80]
    bg = Image.alpha_composite(bg, Image.fromarray(grad, "RGBA"))

    # fire glows
    glow1 = _make_glow(logo, (200, 40, 0), radius=60, opacity=1.0)
    l1 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    l1 = _center_paste(l1, glow1, y_offset=-50)
    bg = _additive_composite(bg, l1)

    glow2 = _make_glow(logo, (255, 140, 0), radius=30, opacity=0.9)
    l2 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    l2 = _center_paste(l2, glow2, y_offset=-50)
    bg = _additive_composite(bg, l2)

    glow3 = _make_glow(logo, (255, 230, 50), radius=12, opacity=0.7)
    l3 = Image.new("RGBA", (W, H), (0, 0, 0, 0))
    l3 = _center_paste(l3, glow3, y_offset=-50)
    bg = _additive_composite(bg, l3)

    # embers
    embers = _particle_embers(W, H, count=400, zone="upper")
    bg = _additive_composite(bg, embers)

    # fire gradient logo
    fire_logo = _fire_gradient_logo(logo)
    result = _center_paste(bg, fire_logo, y_offset=-50)

    # tagline
    try:
        font = ImageFont.truetype("/Users/fyefye/Library/Fonts/sofachrome rg.ttf", 48)
    except Exception:
        try:
            font = ImageFont.truetype("/Library/Fonts/SF-Pro-Display-Bold.otf", 48)
        except Exception:
            font = ImageFont.load_default()

    draw = ImageDraw.Draw(result)
    tagline = "@LEEKTHATSFYE"
    bbox = draw.textbbox((0, 0), tagline, font=font)
    tw = bbox[2] - bbox[0]
    tx = (W - tw) // 2
    ty = H // 2 + 280

    # glow behind text
    for dx in range(-3, 4):
        for dy in range(-3, 4):
            draw.text((tx + dx, ty + dy), tagline, fill=(255, 60, 0, 60), font=font)
    draw.text((tx, ty), tagline, fill=(255, 255, 255, 240), font=font)

    out = OUT_DIR / "fy3_banner.png"
    result.save(out, "PNG")
    print(f"  [5] YouTube banner (2560x1440) → {out}")
    return result


# ════════════════════════════════════════════════════════════════════
#  6. THUMBNAIL STAMP (small corner badge)
# ════════════════════════════════════════════════════════════════════

def gen_thumb_stamp():
    """Small FY3! stamp for thumbnail corners (200x200)."""
    logo = _load_logo(150)
    canvas = Image.new("RGBA", (200, 200), (0, 0, 0, 0))

    # dark semi-transparent circle
    draw = ImageDraw.Draw(canvas)
    draw.ellipse([5, 5, 195, 195], fill=(0, 0, 0, 160))

    # orange glow
    glow = _make_glow(logo, (255, 100, 0), radius=10, opacity=0.8)
    g_sized = Image.new("RGBA", (200, 200), (0, 0, 0, 0))
    g_sized = _center_paste(g_sized, glow)
    canvas = _additive_composite(canvas, g_sized)

    # sharp logo on top
    canvas = _center_paste(canvas, logo)

    out = OUT_DIR / "fy3_thumb_stamp.png"
    canvas.save(out, "PNG")
    print(f"  [6] Thumbnail stamp (200x200) → {out}")
    return canvas


# ════════════════════════════════════════════════════════════════════
#  MAIN
# ════════════════════════════════════════════════════════════════════

if __name__ == "__main__":
    print(f"\nFY3 Brand Generator")
    print(f"Source logo: {SRC_LOGO}")
    print(f"Output dir:  {OUT_DIR}\n")

    if not SRC_LOGO.exists():
        print(f"ERROR: Source logo not found at {SRC_LOGO}")
        sys.exit(1)

    gen_clean()
    gen_fire()
    gen_neon()
    gen_watermark()
    gen_banner()
    gen_thumb_stamp()

    print(f"\nDone! All assets saved to {OUT_DIR}/")
