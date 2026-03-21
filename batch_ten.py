"""
batch_ten.py

Renders exactly 10 videos using a hand-picked selection of beats and
a rotating set of 4 visualizer clips. Skips any output that already exists.
Does not modify render.py or any other existing files.

Beat → Clip assignment
──────────────────────
 1. army.mp3                  → visual_2.mp4  (portrait, 64s)
 2. hood legend !.mp3         → visual_3.mp4  (portrait, 40s)
 3. master plan !.mp3         → default_visual.mp4  (landscape, 46s)
 4. paul walker !.mp3         → visual_4.mp4  (portrait, 70s)
 5. weapons 150 !.mp3         → visual_2.mp4  (portrait, 64s)
 6. game time !.mp3           → default_visual.mp4  (landscape, 46s)
 7. king fy3!.mp3             → visual_3.mp4  (portrait, 40s)
 8. meineliebe !.mp3          → visual_4.mp4  (portrait, 70s)
 9. time !.mp3                → default_visual.mp4  (landscape, 46s)
10. going down ! 168.mp3      → visual_2.mp4  (portrait, 64s)
"""

import json
import re
import subprocess
from pathlib import Path

import yaml
from PIL import Image, ImageDraw, ImageFont

ROOT = Path(__file__).resolve().parent
BEATS_DIR  = ROOT / "beats"
META_DIR   = ROOT / "metadata"
IMAGES_DIR = ROOT / "images"
OUT_DIR    = ROOT / "output"

# ── Beat → clip assignments ───────────────────────────────────────────────────
BATCH = [
    ("army.mp3",               "BiggKutt8/visual_2.mp4"),
    ("hood legend !.mp3",      "BiggKutt8/visual_3.mp4"),
    ("master plan !.mp3",      "BiggKutt8/default_visual.mp4"),
    ("paul walker !.mp3",      "BiggKutt8/visual_4.mp4"),
    ("weapons 150 !.mp3",      "BiggKutt8/visual_2.mp4"),
    ("game time !.mp3",        "BiggKutt8/default_visual.mp4"),
    ("king fy3!.mp3",          "BiggKutt8/visual_3.mp4"),
    ("meineliebe !.mp3",       "BiggKutt8/visual_4.mp4"),
    ("time !.mp3",             "BiggKutt8/default_visual.mp4"),
    ("going down ! 168.mp3",   "BiggKutt8/visual_2.mp4"),
]

# ── Helpers (mirror render.py — no import dependency) ────────────────────────

def run(cmd):
    subprocess.run(cmd, check=True)


def load_config():
    cfg_path = ROOT / "config.yaml"
    with open(cfg_path) as f:
        return yaml.safe_load(f) or {}


def safe_stem(p: Path) -> str:
    s = p.stem.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s.strip("_")


def ensure_audio_safe_name(audio_file: Path) -> Path:
    stem = safe_stem(audio_file)
    new_name = stem + audio_file.suffix.lower()
    new_path = audio_file.with_name(new_name)
    if new_path != audio_file:
        print(f"  [RENAME] {audio_file.name} → {new_path.name}")
        audio_file.rename(new_path)
    return new_path


def make_thumbnail(title, bg_path, out_path, font_path):
    img  = Image.open(bg_path).convert("RGB")
    draw = ImageDraw.Draw(img)
    font = ImageFont.truetype(font_path, 72)
    margin = 80
    max_w  = img.size[0] - 2 * margin
    words  = title.split()
    lines, line = [], ""
    for w in words:
        test = (line + " " + w).strip()
        if draw.textlength(test, font=font) <= max_w:
            line = test
        else:
            if line:
                lines.append(line)
            line = w
    if line:
        lines.append(line)
    y = 140
    for ln in lines[:3]:
        draw.text((margin + 3, y + 3), ln, font=font, fill=(0, 0, 0))
        draw.text((margin,     y),     ln, font=font, fill=(255, 255, 255))
        y += 90
    out_path.parent.mkdir(parents=True, exist_ok=True)
    img.save(out_path, "JPEG", quality=92)


def render_video_from_clip(audio_path, clip_path, out_mp4, width, height, fps,
                            portrait: bool):
    """
    Landscape clip  → scale-to-fill + crop, no blur needed.
    Portrait clip   → blurred full-frame bg + centered overlay (Option A).
    """
    if portrait:
        # Background: stretch + blur to fill frame
        bg  = (f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
               f"crop={width}:{height},boxblur=20:20,format=yuv420p[bg]")
        # Foreground: scale so height = 1080, keep aspect
        fg  = (f"[0:v]scale=-2:{height},format=yuv420p[fg]")
        # Overlay centered
        ov  = f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[out]"
        vf  = f"{bg};{fg};{ov}"
        map_flag = ["-map", "[out]"]
    else:
        vf       = (f"scale={width}:{height}:force_original_aspect_ratio=increase,"
                    f"crop={width}:{height},format=yuv420p")
        map_flag = ["-map", "0:v:0"]

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(clip_path),
        "-i", str(audio_path),
        *map_flag,
        "-map", "1:a:0",
        "-filter_complex" if portrait else "-vf", vf,
        "-r", str(fps),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-threads", "0",
        "-c:a", "aac", "-b:a", "192k",
        "-movflags", "+faststart",
        "-shortest",
        str(out_mp4),
    ]
    run(cmd)


# ── Main ─────────────────────────────────────────────────────────────────────

def main():
    cfg        = load_config()
    render_cfg = cfg.get("render", {})
    font_path  = render_cfg.get("font_path")
    if not font_path:
        raise KeyError("config.yaml missing render.font_path")
    w   = int(render_cfg.get("width",  1920))
    h   = int(render_cfg.get("height", 1080))
    fps = int(render_cfg.get("fps",    30))

    default_img = ROOT / render_cfg.get("image_default", "images/default.jpg")
    if not default_img.exists():
        raise FileNotFoundError(f"Default image not found: {default_img}")

    OUT_DIR.mkdir(exist_ok=True)
    META_DIR.mkdir(exist_ok=True)

    print(f"\n{'─'*54}")
    print(f"  batch_ten.py — rendering 10 videos")
    print(f"{'─'*54}\n")

    for idx, (beat_filename, clip_filename) in enumerate(BATCH, 1):
        raw_path  = BEATS_DIR / beat_filename
        clip_path = IMAGES_DIR / clip_filename

        if not raw_path.exists():
            print(f"[{idx:02d}] MISSING beat: {beat_filename} — skipping")
            continue
        if not clip_path.exists():
            print(f"[{idx:02d}] MISSING clip: {clip_filename} — skipping")
            continue

        audio_file = ensure_audio_safe_name(raw_path)
        stem       = safe_stem(audio_file)

        # Metadata
        meta_path = META_DIR / f"{stem}.json"
        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
        else:
            meta = {
                "title":       stem.replace("_", " ").title(),
                "artist":      "LeekThatsFye",
                "description": "",
                "tags":        [],
            }
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)
            print(f"  [META] Created {meta_path.name}")

        title      = meta.get("title", stem)
        mp4_path   = OUT_DIR / f"{stem}.mp4"
        thumb_path = OUT_DIR / f"{stem}_thumb.jpg"

        # Thumbnail (still uses jpg background)
        img = IMAGES_DIR / f"{stem}.jpg"
        if not img.exists():
            img = default_img
        if not thumb_path.exists():
            make_thumbnail(title, img, thumb_path, str(font_path))

        # Determine if clip is portrait (h > w)
        is_portrait = not clip_filename.endswith("default_visual.mp4")

        if mp4_path.exists():
            print(f"[SKIP] {stem}", flush=True)
        else:
            print(f"[RENDER] {stem}", flush=True)
            print(f"       beat  : {audio_file.name}")
            print(f"       clip  : {clip_filename}  ({'portrait' if is_portrait else 'landscape'})")
            try:
                render_video_from_clip(audio_file, clip_path, mp4_path,
                                       w, h, fps, portrait=is_portrait)
                if mp4_path.exists() and mp4_path.stat().st_size > 100_000:
                    print(f"[DONE] {stem}", flush=True)
                else:
                    raise RuntimeError("Output file missing or too small after render")
            except Exception as _exc:
                print(f"[FAIL] {stem}: {_exc}", flush=True)
                # Clean up partial/corrupt output so it re-renders next time
                if mp4_path.exists() and mp4_path.stat().st_size < 100_000:
                    mp4_path.unlink(missing_ok=True)
                continue  # next beat — never abort the whole batch

    print(f"\n{'─'*54}")
    print("  Done.")
    print(f"{'─'*54}\n")


if __name__ == "__main__":
    main()
