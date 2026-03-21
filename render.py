from __future__ import annotations
"""
render.py

Renders beat audio files (MP3/WAV) from beats/ into MP4 videos in output/.
Each beat gets a thumbnail (output/{stem}_thumb.jpg) and a video (output/{stem}.mp4).

Usage examples:
    python render.py                    # render all beats
    python render.py --only "army,hood_legend"
    python render.py --clip visual_2    # override visualizer clip for all
    python render.py --dry-run          # show what would be rendered

Signals parsed by the Telegram bot:
    [RENDER] stem      — starting this beat
    [DONE]   stem      — beat finished successfully
    [FAIL]   stem: msg — beat failed (batch continues)
    [SKIP]   stem      — already rendered, skipped
    [COMPLETE] N/M     — all done
"""

import argparse
import hashlib
import json
import random
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT       = Path(__file__).resolve().parent
BEATS_DIR  = ROOT / "beats"
META_DIR   = ROOT / "metadata"
IMAGES_DIR = ROOT / "images"
SHARED_CLIPS_DIR = Path.home() / "Shared_Clips"
OUT_DIR    = ROOT / "output"
BRAND_DIR  = ROOT / "brand"

WATERMARK   = BRAND_DIR / "fy3_watermark.png"    # semi-transparent for video overlay
THUMB_STAMP = BRAND_DIR / "fy3_hp_stamp.png"     # Harry Potter FY3 logo for thumbnails
SPIN_LOGO   = BRAND_DIR / "fy3_spin.mov"         # spinning HP-font logo (bottom-center)

# Pink variants for female artists (Sexyy Red, etc.)
THUMB_STAMP_PINK = BRAND_DIR / "fy3_hp_stamp_pink.png"
SPIN_LOGO_PINK   = BRAND_DIR / "fy3_spin_pink.mov"

# Artists that use the pink logo variant
PINK_LOGO_ARTISTS = {"Sexyy Red", "GloRilla", "Megan Thee Stallion", "Latto",
                     "City Girls", "Ice Spice", "Cardi B", "Nicki Minaj",
                     "Doechii", "Flo Milli", "Sukihana"}


def get_brand_assets(seo_artist: str | None = None) -> tuple[Path, Path]:
    """Return (spin_logo, thumb_stamp) — pink for female artists, gold otherwise."""
    if seo_artist and seo_artist in PINK_LOGO_ARTISTS:
        spin = SPIN_LOGO_PINK if SPIN_LOGO_PINK.exists() else SPIN_LOGO
        stamp = THUMB_STAMP_PINK if THUMB_STAMP_PINK.exists() else THUMB_STAMP
        return spin, stamp
    return SPIN_LOGO, THUMB_STAMP


# ── Flush helper ──────────────────────────────────────────────────────────────

def p(msg: str):
    """Print with immediate flush so the bot's async pipe sees it instantly."""
    print(msg, flush=True)


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    cfg_path = ROOT / "config.yaml"
    with open(cfg_path) as f:
        return yaml.safe_load(f) or {}


# ── Stem helpers ──────────────────────────────────────────────────────────────

def safe_stem(path: Path) -> str:
    """Normalize a filename to a safe stem: lowercase, underscores, no punctuation."""
    s = path.stem.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s.strip("_")


def ensure_audio_safe_name(audio_file: Path) -> Path:
    """Rename the audio file on disk to its safe-stem name if needed."""
    stem     = safe_stem(audio_file)
    new_name = stem + audio_file.suffix.lower()
    new_path = audio_file.with_name(new_name)
    if new_path != audio_file:
        p(f"  [RENAME] {audio_file.name} → {new_path.name}")
        audio_file.rename(new_path)
    return new_path


# ── ffmpeg helpers ────────────────────────────────────────────────────────────

def run(cmd: list):
    """Run a subprocess command. Raises RuntimeError on non-zero exit (no crash on exception)."""
    result = subprocess.run(cmd, check=False)
    if result.returncode != 0:
        raise RuntimeError(f"ffmpeg exited with code {result.returncode}")


def is_portrait(clip_path: Path) -> bool:
    """Return True if the video clip is taller than it is wide."""
    try:
        r = subprocess.run(
            [
                "ffprobe", "-v", "quiet",
                "-print_format", "json",
                "-show_streams",
                str(clip_path),
            ],
            capture_output=True,
            text=True,
            timeout=15,
        )
        streams = json.loads(r.stdout).get("streams", [])
        for s in streams:
            if s.get("codec_type") == "video":
                return int(s.get("height", 0)) > int(s.get("width", 0))
    except Exception:
        pass
    return False


# ── Anti-Content-ID filters ──────────────────────────────────────────────────

# Directories whose clips are original content — skip anti-CID
ORIGINAL_CONTENT_DIRS = {"BiggKutt8"}

# Filename prefixes that are original/safe content — skip anti-CID
_SAFE_PREFIXES = ("default",)


def needs_anti_cid(clip_path: Path) -> bool:
    """Return True if the clip likely contains copyrighted artist content.

    Safe (skip anti-CID):
      - Clips in ORIGINAL_CONTENT_DIRS (e.g. BiggKutt8/)
      - Clips with safe prefixes (default_visual.mp4, default.mp4)

    Gets anti-CID (all others):
      - bg_*.mp4 clips in root (downloaded from artists' socials)
      - Clips in artist subfolders (Sexyy Red/, etc.)
      - Any other non-default clips
    """
    name = clip_path.stem.lower()

    # Safe prefixes — original content
    if any(name.startswith(p) for p in _SAFE_PREFIXES):
        return False

    # Original content directories
    if clip_path.parent != IMAGES_DIR and clip_path.parent.name in ORIGINAL_CONTENT_DIRS:
        return False

    # Everything else gets anti-CID (bg_*, artist subfolders, etc.)
    return True


def build_anti_cid_filters(cfg: dict) -> str:
    """Build a comma-separated ffmpeg filter fragment for anti-Content-ID.

    Returns empty string if disabled or cfg is empty.
    Handles: hflip, color grading (eq + hue), vignette, noise.
    Speed and zoom are handled separately since they interact with the
    existing scale/crop/split logic in render_video_from_clip().
    """
    if not cfg or not cfg.get("enabled", False):
        return ""

    parts = []

    # 1. Horizontal flip (mirror) — most effective single technique
    if cfg.get("hflip", True):
        parts.append("hflip")

    # 2. Color grading — changes histogram so color-based matching fails
    eq_parts = []
    brightness = cfg.get("brightness", 0)
    if brightness:
        eq_parts.append(f"brightness={brightness}")
    saturation = cfg.get("saturation", 1.0)
    if saturation != 1.0:
        eq_parts.append(f"saturation={saturation}")
    if eq_parts:
        parts.append(f"eq={':'.join(eq_parts)}")

    hue = cfg.get("hue_shift", 0)
    if hue:
        parts.append(f"hue=h={hue}")

    # 3. Vignette — darkens edges, changes frame-wide pixel values
    if cfg.get("vignette", False):
        parts.append("vignette=PI/4")

    # 4. Temporal noise — changes every pixel every frame, invisible at YT bitrate
    noise = cfg.get("noise", 0)
    if noise > 0:
        parts.append(f"noise=alls={noise}:allf=t")

    return ",".join(parts)


def get_zoom_dimensions(width: int, height: int, zoom: float) -> tuple[int, int]:
    """Return intermediate scale dimensions for anti-CID zoom.

    E.g. zoom=1.07 on 1920x1080 → 2056x1156 (rounded to even for yuv420p).
    """
    if zoom <= 1.0:
        return width, height
    zw = int(width * zoom)
    zh = int(height * zoom)
    # Ensure even dimensions for yuv420p compatibility
    zw += zw % 2
    zh += zh % 2
    return zw, zh


# ── Thumbnail ─────────────────────────────────────────────────────────────────

def make_thumbnail(clip_path: Path, out_path: Path,
                   width: int = 1920, height: int = 1080,
                   seek: float = 3.0,
                   stamp_path: Path | None = None,
                   anti_cid_cfg: dict | None = None) -> bool:
    """
    Extract a single still frame from clip_path and save as a full-res JPEG thumbnail.
    No text overlay — pure clean still shot from the video.
    When anti_cid_cfg is provided, applies hflip + color grading to match the video.
    Returns True on success, False on failure.
    """
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        # Build thumbnail filter chain
        vf_parts = [
            f"scale={width}:{height}:force_original_aspect_ratio=increase",
            f"crop={width}:{height}",
        ]
        # Apply anti-CID visual transforms to thumbnail to match video
        acfg = anti_cid_cfg or {}
        if acfg.get("enabled", False):
            if acfg.get("hflip", True):
                vf_parts.append("hflip")
            eq_parts = []
            brightness = acfg.get("brightness", 0)
            if brightness:
                eq_parts.append(f"brightness={brightness}")
            saturation = acfg.get("saturation", 1.0)
            if saturation != 1.0:
                eq_parts.append(f"saturation={saturation}")
            if eq_parts:
                vf_parts.append(f"eq={':'.join(eq_parts)}")
            hue = acfg.get("hue_shift", 0)
            if hue:
                vf_parts.append(f"hue=h={hue}")
            if acfg.get("vignette", False):
                vf_parts.append("vignette=PI/4")

        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss",      str(seek),
                "-i",       str(clip_path),
                "-vframes", "1",
                "-vf",      ",".join(vf_parts),
                "-q:v",     "2",
                str(out_path),
            ],
            capture_output=True,
            timeout=30,
        )
        ok = result.returncode == 0 and out_path.exists()
        # stamp Harry Potter FY3 logo — bottom-center
        actual_stamp = stamp_path or THUMB_STAMP
        if ok and actual_stamp.exists():
            try:
                from PIL import Image
                thumb = Image.open(out_path).convert("RGBA")
                stamp = Image.open(actual_stamp).convert("RGBA")
                # position: bottom-center with 20px padding from bottom
                x = (thumb.width - stamp.width) // 2
                y = thumb.height - stamp.height - 20
                thumb.paste(stamp, (x, y), stamp)
                thumb.convert("RGB").save(out_path, "JPEG", quality=95)
            except Exception:
                pass  # stamp failed — thumbnail still usable without it
        return ok
    except Exception:
        return False


# ── Video renderers ───────────────────────────────────────────────────────────

def render_video(audio_path: Path, bg_path: Path, out_mp4: Path,
                 width: int, height: int, fps: int,
                 spin_logo: Path | None = None):
    """Still-image path: zoompan (1.0 → 1.12×) over audio duration, with spinning FY3 logo."""
    spin = spin_logo or SPIN_LOGO
    has_spin = spin.exists()
    if has_spin:
        vf = (
            f"[0:v]zoompan=z='min(zoom+0.0004,1.12)':d=1:x='iw/2-(iw/zoom/2)'"
            f":y='ih/2-(ih/zoom/2)':s={width}x{height},format=yuva420p[vid];"
            f"[vid][2:v]overlay=(W-w)/2:H-h-20,format=yuv420p"
        )
        run([
            "ffmpeg", "-y",
            "-loop", "1",        "-i", str(bg_path),
            "-i",                      str(audio_path),
            "-stream_loop", "-1", "-i", str(spin),
            "-filter_complex", vf,
            "-r",    str(fps),
            "-c:v",  "libx264", "-preset", "veryfast", "-crf", "21",
            "-threads", "0",
            "-c:a",  "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-shortest",
            str(out_mp4),
        ])
    else:
        run([
            "ffmpeg", "-y",
            "-loop", "1", "-i", str(bg_path),
            "-i",          str(audio_path),
            "-vf",
            (
                f"zoompan=z='min(zoom+0.0004,1.12)':d=1:x='iw/2-(iw/zoom/2)'"
                f":y='ih/2-(ih/zoom/2)':s={width}x{height},format=yuv420p"
            ),
            "-r",    str(fps),
            "-c:v",  "libx264", "-preset", "veryfast", "-crf", "21",
            "-threads", "0",
            "-c:a",  "aac", "-b:a", "192k",
            "-movflags", "+faststart",
            "-shortest",
            str(out_mp4),
        ])


def render_video_from_clip(audio_path: Path, clip_path: Path, out_mp4: Path,
                            width: int, height: int, fps: int,
                            spin_logo: Path | None = None,
                            anti_cid_cfg: dict | None = None):
    """
    Clip path with spinning FY3 logo overlay (bottom-center).
      Portrait  → blurred full-frame bg + centred overlay (Option A).
      Landscape → scale-to-fill + crop (no blur needed).

    anti_cid_cfg: dict from config.yaml 'anti_cid' section. When enabled,
    applies visual transforms (mirror, zoom, color shift, speed, noise) to
    defeat YouTube Content ID visual fingerprinting on music video clips.
    """
    portrait = is_portrait(clip_path)
    spin = spin_logo or SPIN_LOGO
    has_spin = spin.exists()

    # ── Anti-CID setup ────────────────────────────────────────────────────
    acfg = anti_cid_cfg or {}
    enabled = acfg.get("enabled", False)
    anti_cid = build_anti_cid_filters(acfg)       # hflip,eq,hue,vignette,noise
    acf = f",{anti_cid}" if anti_cid else ""       # comma-prefixed for chaining

    # Zoom: enlarge then crop back (shifts pixel sampling grid)
    zoom = acfg.get("zoom", 1.0) if enabled else 1.0
    zw, zh = get_zoom_dimensions(width, height, zoom)

    # Speed: change playback rate (defeats temporal fingerprinting)
    speed = acfg.get("speed", 1.0) if enabled else 1.0
    speed_setpts = f"setpts=PTS/{speed}," if speed != 1.0 else ""

    if enabled and anti_cid:
        p(f"  [ANTI-CID] {anti_cid} | zoom={zoom} speed={speed}")

    if portrait:
        # Portrait: blurred full-frame bg + centered foreground overlay
        # Speed is applied at the start via split so both bg and fg get it.
        # Anti-CID filters (hflip, color, noise) applied to fg only —
        # bg is already unrecognizable due to boxblur.

        # Foreground zoom: scale slightly taller, crop back to exact height
        fg_h = int(height * zoom) if zoom > 1.0 else height
        fg_crop = f",crop=iw:{height}" if zoom > 1.0 else ""

        if speed != 1.0:
            # Need split because [0:v] is consumed by both bg and fg chains
            pre = f"[0:v]setpts=PTS/{speed},split=2[src1][src2];"
            bg_src, fg_src = "[src1]", "[src2]"
        else:
            pre = ""
            bg_src, fg_src = "[0:v]", "[0:v]"

        bg_filter = (
            f"{bg_src}scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=20:20,format=yuva420p[bg]"
        )
        fg_filter = (
            f"{fg_src}scale=-2:{fg_h}{fg_crop}{acf},format=yuva420p[fg]"
        )

        if has_spin:
            ov_filter = f"[bg][fg]overlay=(W-w)/2:(H-h)/2[comp]"
            spin_filter = f"[comp][2:v]overlay=(W-w)/2:H-h-20,format=yuv420p[out]"
            vf = f"{pre}{bg_filter};{fg_filter};{ov_filter};{spin_filter}"
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1", "-i", str(clip_path),
                "-i",                       str(audio_path),
                "-stream_loop", "-1", "-i", str(spin),
                "-filter_complex", vf,
                "-map", "[out]",
                "-map", "1:a:0",
                "-r",    str(fps),
                "-c:v",  "libx264", "-preset", "veryfast", "-crf", "21",
                "-threads", "0",
                "-c:a",  "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                "-shortest",
                str(out_mp4),
            ]
        else:
            ov_filter = f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[out]"
            vf = f"{pre}{bg_filter};{fg_filter};{ov_filter}"
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1", "-i", str(clip_path),
                "-i",                       str(audio_path),
                "-filter_complex", vf,
                "-map", "[out]",
                "-map", "1:a:0",
                "-r",    str(fps),
                "-c:v",  "libx264", "-preset", "veryfast", "-crf", "21",
                "-threads", "0",
                "-c:a",  "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                "-shortest",
                str(out_mp4),
            ]
    else:
        # Landscape: scale-to-fill + crop
        # Anti-CID: zoom via larger scale target, speed via setpts prefix,
        # remaining filters (hflip, color, noise) appended after crop.

        if has_spin:
            vf = (
                f"[0:v]{speed_setpts}scale={zw}:{zh}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}{acf},format=yuva420p[vid];"
                f"[vid][2:v]overlay=(W-w)/2:H-h-20,format=yuv420p[out]"
            )
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1", "-i", str(clip_path),
                "-i",                       str(audio_path),
                "-stream_loop", "-1", "-i", str(spin),
                "-filter_complex", vf,
                "-map",  "[out]",
                "-map",  "1:a:0",
                "-r",    str(fps),
                "-c:v",  "libx264", "-preset", "veryfast", "-crf", "21",
                "-threads", "0",
                "-c:a",  "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                "-shortest",
                str(out_mp4),
            ]
        else:
            vf = (
                f"{speed_setpts}scale={zw}:{zh}:force_original_aspect_ratio=increase,"
                f"crop={width}:{height}{acf},format=yuv420p"
            )
            cmd = [
                "ffmpeg", "-y",
                "-stream_loop", "-1", "-i", str(clip_path),
                "-i",                       str(audio_path),
                "-map",  "0:v:0",
                "-map",  "1:a:0",
                "-vf",   vf,
                "-r",    str(fps),
                "-c:v",  "libx264", "-preset", "veryfast", "-crf", "21",
                "-threads", "0",
                "-c:a",  "aac", "-b:a", "192k",
                "-movflags", "+faststart",
                "-shortest",
                str(out_mp4),
            ]

    run(cmd)


# ── Thumbnail photo resolution ────────────────────────────────────────────────

# Map seo_artist → subfolder name under images/ containing curated photos
ARTIST_THUMB_DIRS: dict[str, str] = {
    "Sexyy Red": "sr_thumbs",
}

_thumb_photo_usage: dict[str, int] = {}  # track rotation of thumbnail photos


def resolve_thumb_photo(stem: str, seo_artist: str | None = None) -> Path | None:
    """
    Return a curated artist photo for the thumbnail, or None to fall back
    to video-frame extraction.  Rotates through available photos using
    the same least-used + deterministic-hash logic as clip rotation.
    """
    if not seo_artist:
        return None
    folder_name = ARTIST_THUMB_DIRS.get(seo_artist)
    if not folder_name:
        return None
    photo_dir = IMAGES_DIR / folder_name
    if not photo_dir.is_dir():
        return None
    photos = sorted(photo_dir.glob("*.jpg")) + sorted(photo_dir.glob("*.png"))
    if not photos:
        return None
    # Least-used rotation (deterministic by stem)
    seed = int(hashlib.md5(stem.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)
    min_usage = min(_thumb_photo_usage.get(str(p), 0) for p in photos)
    least_used = [p for p in photos if _thumb_photo_usage.get(str(p), 0) == min_usage]
    rng.shuffle(least_used)
    chosen = least_used[0]
    _thumb_photo_usage[str(chosen)] = _thumb_photo_usage.get(str(chosen), 0) + 1
    return chosen


def make_thumbnail_from_photo(photo_path: Path, out_path: Path,
                              width: int = 1920, height: int = 1080,
                              stamp_path: Path | None = None) -> bool:
    """
    Create a thumbnail from a curated artist photo (JPG/PNG).
    Scale-to-fill + center-crop to target resolution, then overlay brand stamp.
    """
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-i",       str(photo_path),
                "-vframes", "1",
                "-vf",      f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
                "-q:v",     "2",
                str(out_path),
            ],
            capture_output=True,
            timeout=30,
        )
        ok = result.returncode == 0 and out_path.exists()
        # Overlay brand stamp — bottom-center
        actual_stamp = stamp_path or THUMB_STAMP
        if ok and actual_stamp.exists():
            try:
                from PIL import Image
                thumb = Image.open(out_path).convert("RGBA")
                stamp = Image.open(actual_stamp).convert("RGBA")
                x = (thumb.width - stamp.width) // 2
                y = thumb.height - stamp.height - 20
                thumb.paste(stamp, (x, y), stamp)
                thumb.convert("RGB").save(out_path, "JPEG", quality=95)
            except Exception:
                pass
        return ok
    except Exception:
        return False


# ── Clip resolution ───────────────────────────────────────────────────────────

_clip_usage: dict[str, int] = {}  # track how many times each clip is assigned


def _collect_clips(*dirs: Path) -> list[Path]:
    """Collect all .mp4 clips from multiple directories, deduped by filename."""
    seen: set[str] = set()
    clips: list[Path] = []
    for d in dirs:
        if d and d.is_dir():
            for c in sorted(d.glob("*.mp4")):
                if c.name not in seen:
                    seen.add(c.name)
                    clips.append(c)
    return clips


def resolve_clip(stem: str, override: str | None, seo_artist: str | None = None) -> Path | None:
    """
    Return the visualizer clip to use for this stem, or None for still-image path.
    Searches both images/ (primary) and ~/Shared_Clips (secondary).
    Priority:
      1. --clip override (may be relative like "BiggKutt8/visual_2.mp4" or bare "visual_2.mp4")
      2. images/{seo_artist}/{stem}.mp4  (per-beat in artist folder)
      3. images/{stem}.mp4               (per-beat in root — backward compat)
      4. ~/Shared_Clips/{stem}.mp4       (per-beat from shared folder)
      5. Rotate through ALL clips in images/{seo_artist}/ — pick the least-used clip
         (deterministic by stem hash so thumb + video get the same clip)
      6. Rotate through ALL clips in images/ root + ~/Shared_Clips (merged pool)
      7. None (still image fallback)
    """
    shared = SHARED_CLIPS_DIR if SHARED_CLIPS_DIR.is_dir() else None

    if override:
        # Try as relative path under images/ (e.g. "BiggKutt8/visual_2.mp4")
        p_override = IMAGES_DIR / override
        if not p_override.suffix:
            p_override = p_override.with_suffix(".mp4")
        if p_override.exists():
            return p_override
        # Try in shared folder
        if shared:
            p_shared = shared / override
            if not p_shared.suffix:
                p_shared = p_shared.with_suffix(".mp4")
            if p_shared.exists():
                return p_shared
        # Try bare filename in artist subfolder
        if seo_artist:
            p_artist = IMAGES_DIR / seo_artist / override
            if not p_artist.suffix:
                p_artist = p_artist.with_suffix(".mp4")
            if p_artist.exists():
                return p_artist
        p(f"  [WARN] --clip {override} not found — falling back to default")

    # Per-beat clip in artist subfolder
    if seo_artist:
        per_beat_artist = IMAGES_DIR / seo_artist / f"{stem}.mp4"
        if per_beat_artist.exists():
            return per_beat_artist

    # Per-beat clip in root (backward compat)
    per_beat = IMAGES_DIR / f"{stem}.mp4"
    if per_beat.exists():
        return per_beat

    # Per-beat clip in shared folder
    if shared:
        per_beat_shared = shared / f"{stem}.mp4"
        if per_beat_shared.exists():
            return per_beat_shared

    # Rotate through ALL available clips in artist folder
    if seo_artist:
        artist_dir = IMAGES_DIR / seo_artist
        if artist_dir.is_dir():
            clips = sorted(artist_dir.glob("*.mp4"))
            if clips:
                chosen = _pick_least_used(clips, stem)
                if chosen:
                    return chosen

    # Rotate through ALL clips in images/ root + shared folder (merged pool)
    all_clips = _collect_clips(IMAGES_DIR, shared)
    if all_clips:
        chosen = _pick_least_used(all_clips, stem)
        if chosen:
            return chosen

    return None


def _pick_least_used(clips: list[Path], stem: str) -> Path | None:
    """
    Pick the least-used clip from a list. Uses stem hash for deterministic
    selection (so thumbnail and video get the same clip), but favours
    clips that have been used the fewest times overall.
    """
    if not clips:
        return None

    # Sort by usage count (ascending), then by a stem-based hash for stable tie-breaking
    seed = int(hashlib.md5(stem.encode()).hexdigest()[:8], 16)
    rng = random.Random(seed)

    # Group by usage count
    min_usage = min(_clip_usage.get(str(c), 0) for c in clips)
    least_used = [c for c in clips if _clip_usage.get(str(c), 0) == min_usage]

    # Deterministic shuffle based on stem
    rng.shuffle(least_used)
    chosen = least_used[0]

    # Track usage
    _clip_usage[str(chosen)] = _clip_usage.get(str(chosen), 0) + 1
    return chosen


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Render beat audio files into MP4 videos.")
    parser.add_argument(
        "--only", type=str, default=None,
        help="Comma-separated stems to render (e.g. army,hood_legend)"
    )
    parser.add_argument(
        "--clip", type=str, default=None,
        metavar="CLIP",
        help="Override visualizer clip for all beats (e.g. visual_2 or visual_2.mp4)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be rendered without calling ffmpeg"
    )
    parser.add_argument("--force", action="store_true", help="Overwrite existing renders")
    args = parser.parse_args()

    # ── Load config ───────────────────────────────────────────────────────────
    cfg        = load_config()
    render_cfg = cfg.get("render", {})

    width  = int(render_cfg.get("width",  1920))
    height = int(render_cfg.get("height", 1080))
    fps    = int(render_cfg.get("fps",    30))

    OUT_DIR.mkdir(exist_ok=True)
    META_DIR.mkdir(exist_ok=True)

    # ── Build file list ───────────────────────────────────────────────────────
    if args.only:
        requested_stems = [s.strip() for s in args.only.split(",")]
        audio_files = []
        for stem in requested_stems:
            # Try both mp3 and wav
            for ext in (".mp3", ".wav"):
                candidate = BEATS_DIR / f"{stem}{ext}"
                if candidate.exists():
                    audio_files.append(candidate)
                    break
            else:
                # Try with original name (already-renamed files)
                found = list(BEATS_DIR.glob(f"{stem}.*"))
                found = [f for f in found if f.suffix.lower() in (".mp3", ".wav")]
                if found:
                    audio_files.append(found[0])
                else:
                    p(f"[ERROR] Beat not found for stem: {stem}")
    else:
        audio_files = sorted(
            f for f in BEATS_DIR.iterdir()
            if f.suffix.lower() in (".mp3", ".wav")
        )

    if not audio_files:
        p("No audio files to render.")
        sys.exit(0)

    p(f"\n{'─'*56}")
    p(f"  render.py — {len(audio_files)} beat(s) queued")
    if args.dry_run:
        p(f"  DRY RUN — no ffmpeg calls will be made")
    p(f"{'─'*56}\n")

    done_count = 0
    fail_count = 0
    skip_count = 0

    for audio_raw in audio_files:
        # ── Normalize filename ─────────────────────────────────────────────
        try:
            audio_file = ensure_audio_safe_name(audio_raw)
        except Exception as exc:
            p(f"[FAIL] {audio_raw.stem}: rename error: {exc}")
            fail_count += 1
            continue

        stem = safe_stem(audio_file)

        # ── Metadata ───────────────────────────────────────────────────────
        meta_path = META_DIR / f"{stem}.json"
        if meta_path.exists():
            try:
                with open(meta_path) as f:
                    meta = json.load(f)
            except Exception:
                meta = {}
        else:
            meta = {
                "title":       stem.replace("_", " ").title(),
                "artist":      "LeekThatsFye",
                "description": "",
                "tags":        [],
            }
            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)
            p(f"  [META] Created {meta_path.name}")

        title      = meta.get("title", stem.replace("_", " ").title())
        seo_artist = meta.get("seo_artist")
        mp4_path   = OUT_DIR / f"{stem}.mp4"
        thumb_path = OUT_DIR / f"{stem}_thumb.jpg"

        # ── Skip if already rendered ───────────────────────────────────────
        if mp4_path.exists() and not args.force:
            p(f"[SKIP] {stem}")
            skip_count += 1
            continue
        if mp4_path.exists() and args.force:
            p(f"[OVERWRITE] {stem} -- removing old render")
            mp4_path.unlink()
            if thumb_path.exists():
                thumb_path.unlink()

        p(f"[RENDER] {stem}")

        if args.dry_run:
            p(f"  [DRY] would render: {stem}.mp4")
            done_count += 1
            continue

        # ── Per-beat try/except — one failure never kills the batch ────────
        try:
            # Resolve brand assets (pink for female artists, gold otherwise)
            spin, stamp = get_brand_assets(seo_artist)

            # Thumbnail — curated artist photo preferred, video frame fallback
            if not thumb_path.exists():
                thumb_photo = resolve_thumb_photo(stem, seo_artist)
                if thumb_photo:
                    ok = make_thumbnail_from_photo(thumb_photo, thumb_path, width, height,
                                                   stamp_path=stamp)
                    if ok:
                        p(f"  [THUMB] {thumb_path.name}  (photo: {thumb_photo.name})")
                    else:
                        p(f"  [THUMB] photo composite failed — skipped")
                else:
                    clip_for_thumb = resolve_clip(stem, args.clip, seo_artist=seo_artist)
                    if clip_for_thumb:
                        thumb_acfg = cfg.get("anti_cid", {}) if needs_anti_cid(clip_for_thumb) else {}
                        ok = make_thumbnail(clip_for_thumb, thumb_path, width, height,
                                            seek=3.0, stamp_path=stamp,
                                            anti_cid_cfg=thumb_acfg)
                        if ok:
                            p(f"  [THUMB] {thumb_path.name}")
                        else:
                            p(f"  [THUMB] frame extract failed — skipped")
                    else:
                        p(f"  [THUMB] skipped — no clip or photo available")

            # Resolve clip
            clip = resolve_clip(stem, args.clip, seo_artist=seo_artist)

            if clip:
                p(f"  [CLIP]  {clip.name}  ({'portrait' if is_portrait(clip) else 'landscape'})")
                # Apply anti-CID only to non-original clips (e.g. Sexyy Red footage)
                acfg = cfg.get("anti_cid", {}) if needs_anti_cid(clip) else {}
                render_video_from_clip(audio_file, clip, mp4_path, width, height, fps,
                                       spin_logo=spin, anti_cid_cfg=acfg)
            else:
                bg_img = IMAGES_DIR / f"{stem}.jpg"
                if not bg_img.exists():
                    default_jpg = ROOT / "images" / "default.jpg"
                    bg_img = default_jpg if default_jpg.exists() else None
                if bg_img and bg_img.exists():
                    p(f"  [IMG]   {bg_img.name}  (still image + zoompan)")
                    render_video(audio_file, bg_img, mp4_path, width, height, fps,
                                 spin_logo=spin)
                else:
                    raise RuntimeError(
                        "No video clip and no background image found — "
                        "add images/default_visual.mp4 or images/default.jpg"
                    )

            p(f"[DONE] {stem}")
            done_count += 1

        except Exception as exc:
            p(f"[FAIL] {stem}: {exc}")
            fail_count += 1
            # Clean up partial output so a re-run will retry this beat
            if mp4_path.exists() and not args.force:
                try:
                    mp4_path.unlink()
                except Exception:
                    pass
            continue

    # ── Summary ───────────────────────────────────────────────────────────────
    p(f"\n{'─'*56}")
    p(f"[COMPLETE] {done_count}/{len(audio_files)} rendered  |  {skip_count} skipped  |  {fail_count} failed")
    p(f"{'─'*56}")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
