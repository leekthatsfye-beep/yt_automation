#!/usr/bin/env python3
"""
FY3 Spinning Logo Generator
============================
Creates a vintage game-studio-style spinning gold "FY3 !" logo
in Harry Potter font. Outputs a loopable transparent MOV overlay
for the bottom-center of beat videos.

The spin cycle:
  - Logo starts facing camera
  - Rotates 360° around Y-axis (3D perspective warp)
  - Gold metallic gradient + glow
  - ~3 second loop at 30fps = 90 frames

Output: brand/fy3_spin.mov (ProRes 4444 with alpha)
        brand/fy3_spin_preview.gif (for quick preview)
"""
import math, shutil, subprocess, sys
from pathlib import Path

from PIL import Image, ImageDraw, ImageFont, ImageFilter
import numpy as np

ROOT     = Path(__file__).resolve().parent
BRAND    = ROOT / "brand"
FRAMES   = BRAND / "spin_frames"
FONT     = Path.home() / "Library" / "Fonts" / "HarryP.ttf"
OUT_MOV  = BRAND / "fy3_spin.mov"
OUT_GIF  = BRAND / "fy3_spin_preview.gif"

# ── Config ──────────────────────────────────────────────────────────
CANVAS_W, CANVAS_H = 800, 280   # size of the overlay strip
FONT_SIZE          = 220
FPS                = 30
DURATION_SEC       = 3.0         # one full rotation
NUM_FRAMES         = int(FPS * DURATION_SEC)  # 90

# Gold palette
GOLD_LIGHT  = (255, 223, 100)
GOLD_MID    = (218, 165, 32)
GOLD_DARK   = (139, 101, 8)
GLOW_COLOR  = (255, 200, 50)


def _render_flat_logo() -> Image.Image:
    """Render the flat FY3 ! text — the ! is stretched taller past the 3."""
    font = ImageFont.truetype(str(FONT), FONT_SIZE)
    bang_font = ImageFont.truetype(str(FONT), int(FONT_SIZE * 1.35))  # ! is 35% taller

    tmp = Image.new("RGBA", (1, 1))
    d = ImageDraw.Draw(tmp)

    # measure "FY3 " and "!" separately
    bbox_main = d.textbbox((0, 0), "FY3 ", font=font)
    bbox_bang = d.textbbox((0, 0), "!", font=bang_font)
    main_w = bbox_main[2] - bbox_main[0]
    main_h = bbox_main[3] - bbox_main[1]
    bang_w = bbox_bang[2] - bbox_bang[0]
    bang_h = bbox_bang[3] - bbox_bang[1]

    pad = 40
    total_w = main_w + bang_w + pad * 2
    total_h = max(main_h, bang_h) + pad * 2
    img = Image.new("RGBA", (total_w, total_h), (0, 0, 0, 0))

    # vertical center for main text
    main_y = pad + (total_h - pad * 2 - main_h) // 2
    main_ox = -bbox_main[0]

    # ! aligned to bottom of main text, stretching upward past it
    bang_y = pad + (total_h - pad * 2 - main_h) // 2 + main_h - bang_h
    bang_ox = -bbox_bang[0]

    def _draw_text(draw_obj, x_off, y_off, color):
        draw_obj.text((pad + main_ox + x_off, main_y + y_off), "FY3 ", fill=color, font=font)
        draw_obj.text((pad + main_ox + main_w + bang_ox + x_off, bang_y + y_off), "!", fill=color, font=bang_font)

    draw = ImageDraw.Draw(img)
    # shadow layer
    _draw_text(draw, 3, 3, GOLD_DARK + (200,))
    # mid layer
    _draw_text(draw, 1, 1, GOLD_MID + (255,))
    # bright top
    _draw_text(draw, 0, 0, GOLD_LIGHT + (255,))

    return img


def _apply_y_rotation(img: Image.Image, angle_deg: float) -> Image.Image:
    """
    Simulate Y-axis 3D rotation using perspective transform.
    angle_deg: 0=facing, 90=edge-on, 180=back, 270=edge-on, 360=facing
    """
    w, h = img.size
    angle = math.radians(angle_deg % 360)

    # horizontal scale factor from cosine (1.0 at front, 0 at edge)
    cos_a = math.cos(angle)
    scale_x = abs(cos_a)

    # at edge-on (scale ~0), return tiny sliver
    if scale_x < 0.05:
        result = Image.new("RGBA", (w, h), (0, 0, 0, 0))
        # draw a thin gold line as the edge
        draw = ImageDraw.Draw(result)
        cx = w // 2
        draw.line([(cx, 10), (cx, h - 10)], fill=GOLD_DARK + (180,), width=3)
        return result

    # perspective skew factor
    sin_a = math.sin(angle)
    skew = sin_a * 0.15  # perspective intensity

    # new width after foreshortening
    new_w = max(int(w * scale_x), 4)

    # compute perspective transform coefficients
    # map source corners to destination with perspective
    src_w, src_h = w, h

    # destination corners (centered in original canvas)
    cx = w / 2
    left = cx - new_w / 2
    right = cx + new_w / 2

    # top/bottom perspective offset (creates the 3D tilt)
    top_offset = skew * h * 0.3
    bot_offset = -top_offset

    # four corners: TL, TR, BR, BL in destination
    dst = [
        (left,  top_offset),           # TL
        (right, -top_offset),          # TR
        (right, h + top_offset),       # BR
        (left,  h - top_offset),       # BL
    ]

    # source corners
    src = [
        (0, 0),
        (src_w, 0),
        (src_w, src_h),
        (0, src_h),
    ]

    # compute perspective transform matrix from 4 point pairs
    coeffs = _find_perspective_coeffs(dst, src)
    result = img.transform((w, h), Image.PERSPECTIVE, coeffs, Image.BICUBIC,
                           fillcolor=(0, 0, 0, 0))

    # if we're seeing the "back" (90-270), dim it slightly
    if 90 < (angle_deg % 360) < 270:
        arr = np.array(result, dtype=np.float32)
        arr[:, :, :3] *= 0.6
        result = Image.fromarray(arr.astype(np.uint8), "RGBA")

    return result


def _find_perspective_coeffs(dst, src):
    """Find coefficients for PIL perspective transform from 4 point pairs."""
    matrix = []
    for s, d in zip(src, dst):
        matrix.append([d[0], d[1], 1, 0, 0, 0, -s[0]*d[0], -s[0]*d[1]])
        matrix.append([0, 0, 0, d[0], d[1], 1, -s[1]*d[0], -s[1]*d[1]])
    A = np.matrix(matrix, dtype=np.float64)
    B = np.array([s for pair in src for s in pair]).reshape(8)
    res = np.dot(np.linalg.inv(A.T * A) * A.T, B)
    return np.array(res).reshape(8).tolist()


def _add_glow(frame: Image.Image) -> Image.Image:
    """Add a bright multi-layer gold glow behind the logo."""
    arr = np.array(frame)
    alpha = arr[:, :, 3].astype(np.float32) / 255.0

    canvas = Image.new("RGBA", frame.size, (0, 0, 0, 0))

    # LAYER 1: wide warm orange outer glow
    outer = np.zeros_like(arr, dtype=np.float32)
    outer[:, :, 0] = 255 * alpha
    outer[:, :, 1] = 150 * alpha
    outer[:, :, 2] = 0
    outer[:, :, 3] = alpha * 220
    outer_img = Image.fromarray(outer.astype(np.uint8), "RGBA")
    for _ in range(5):
        outer_img = outer_img.filter(ImageFilter.GaussianBlur(12))
    canvas = Image.alpha_composite(canvas, outer_img)

    # LAYER 2: medium gold glow
    mid = np.zeros_like(arr, dtype=np.float32)
    mid[:, :, 0] = GLOW_COLOR[0] * alpha
    mid[:, :, 1] = GLOW_COLOR[1] * alpha
    mid[:, :, 2] = GLOW_COLOR[2] * alpha
    mid[:, :, 3] = alpha * 240
    mid_img = Image.fromarray(mid.astype(np.uint8), "RGBA")
    for _ in range(3):
        mid_img = mid_img.filter(ImageFilter.GaussianBlur(6))
    canvas = Image.alpha_composite(canvas, mid_img)

    # LAYER 3: tight white-gold hot inner glow
    inner = np.zeros_like(arr, dtype=np.float32)
    inner[:, :, 0] = 255 * alpha
    inner[:, :, 1] = 245 * alpha
    inner[:, :, 2] = 180 * alpha
    inner[:, :, 3] = alpha * 180
    inner_img = Image.fromarray(inner.astype(np.uint8), "RGBA")
    for _ in range(2):
        inner_img = inner_img.filter(ImageFilter.GaussianBlur(3))
    canvas = Image.alpha_composite(canvas, inner_img)

    # sharp logo on top
    canvas = Image.alpha_composite(canvas, frame)
    return canvas


def generate():
    """Generate all frames and compile into video."""
    print(f"FY3 Spinning Logo Generator")
    print(f"  Frames: {NUM_FRAMES} @ {FPS}fps = {DURATION_SEC}s loop")
    print(f"  Canvas: {CANVAS_W}x{CANVAS_H}")
    print(f"  Font:   {FONT}\n")

    # clean frame dir
    if FRAMES.exists():
        shutil.rmtree(FRAMES)
    FRAMES.mkdir(parents=True)

    flat_logo = _render_flat_logo()

    # resize to fit canvas height
    logo_scale = (CANVAS_H - 20) / flat_logo.height
    logo_w = int(flat_logo.width * logo_scale)
    logo_h = int(flat_logo.height * logo_scale)
    flat_logo = flat_logo.resize((logo_w, logo_h), Image.LANCZOS)

    # pad to canvas size (centered)
    padded = Image.new("RGBA", (CANVAS_W, CANVAS_H), (0, 0, 0, 0))
    px = (CANVAS_W - logo_w) // 2
    py = (CANVAS_H - logo_h) // 2
    padded.paste(flat_logo, (px, py), flat_logo)

    gif_frames = []

    for i in range(NUM_FRAMES):
        angle = (i / NUM_FRAMES) * 360.0

        # apply 3D Y-rotation
        rotated = _apply_y_rotation(padded, angle)

        # add glow
        frame = _add_glow(rotated)

        # save frame
        frame_path = FRAMES / f"frame_{i:04d}.png"
        frame.save(frame_path, "PNG")

        # collect for gif (every 2nd frame for smaller file)
        if i % 2 == 0:
            gif_frames.append(frame.copy())

        if (i + 1) % 15 == 0:
            print(f"  Frame {i+1}/{NUM_FRAMES}")

    print(f"\n  All {NUM_FRAMES} frames rendered.")

    # ── Compile to MOV with alpha (ProRes 4444) ──────────────────
    print(f"\n  Compiling → {OUT_MOV.name}")
    cmd = [
        "ffmpeg", "-y",
        "-framerate", str(FPS),
        "-i", str(FRAMES / "frame_%04d.png"),
        "-c:v", "prores_ks",
        "-profile:v", "4",      # 4444 with alpha
        "-pix_fmt", "yuva444p10le",
        "-an",
        str(OUT_MOV),
    ]
    r = subprocess.run(cmd, capture_output=True)
    if r.returncode == 0:
        print(f"  OK → {OUT_MOV}")
    else:
        print(f"  WARN: ProRes failed, trying PNG codec fallback...")
        # fallback: MOV with PNG codec (lossless alpha)
        cmd2 = [
            "ffmpeg", "-y",
            "-framerate", str(FPS),
            "-i", str(FRAMES / "frame_%04d.png"),
            "-c:v", "png",
            "-an",
            str(OUT_MOV),
        ]
        r2 = subprocess.run(cmd2, capture_output=True)
        if r2.returncode == 0:
            print(f"  OK (PNG codec) → {OUT_MOV}")
        else:
            print(f"  FAIL: {r2.stderr.decode()[-200:]}")

    # ── Also save preview GIF ──────────────────────────────────
    print(f"  Saving preview GIF → {OUT_GIF.name}")
    gif_frames[0].save(
        OUT_GIF,
        save_all=True,
        append_images=gif_frames[1:],
        duration=int(1000 / FPS * 2),  # 2x because every other frame
        loop=0,
        disposal=2,
    )
    print(f"  OK → {OUT_GIF}")

    # ── Clean up frames ────────────────────────────────────────
    shutil.rmtree(FRAMES)
    print(f"\n  Done! Files in {BRAND}/")


if __name__ == "__main__":
    generate()
