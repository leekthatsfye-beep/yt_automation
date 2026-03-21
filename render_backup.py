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
import json
import re
import subprocess
import sys
from pathlib import Path

import yaml

ROOT       = Path(__file__).resolve().parent
BEATS_DIR  = ROOT / "beats"
META_DIR   = ROOT / "metadata"
IMAGES_DIR = ROOT / "images"
OUT_DIR    = ROOT / "output"


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


# ── Thumbnail ─────────────────────────────────────────────────────────────────

def make_thumbnail(clip_path: Path, out_path: Path,
                   width: int = 1920, height: int = 1080,
                   seek: float = 3.0) -> bool:
    """
    Extract a single still frame from clip_path and save as a full-res JPEG thumbnail.
    No text overlay — pure clean still shot from the video.
    Returns True on success, False on failure.
    """
    try:
        out_path.parent.mkdir(parents=True, exist_ok=True)
        result = subprocess.run(
            [
                "ffmpeg", "-y",
                "-ss",      str(seek),
                "-i",       str(clip_path),
                "-vframes", "1",
                "-vf",      f"scale={width}:{height}:force_original_aspect_ratio=increase,crop={width}:{height}",
                "-q:v",     "2",
                str(out_path),
            ],
            capture_output=True,
            timeout=30,
        )
        return result.returncode == 0 and out_path.exists()
    except Exception:
        return False


# ── Video renderers ───────────────────────────────────────────────────────────

def render_video(audio_path: Path, bg_path: Path, out_mp4: Path,
                 width: int, height: int, fps: int):
    """Still-image path: zoompan (1.0 → 1.12×) over audio duration."""
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
        "-c:v",  "libx264",
        "-c:a",  "aac", "-b:a", "192k",
        "-shortest",
        str(out_mp4),
    ])


def render_video_from_clip(audio_path: Path, clip_path: Path, out_mp4: Path,
                            width: int, height: int, fps: int):
    """
    Clip path.
      Portrait  → blurred full-frame bg + centred overlay (Option A).
      Landscape → scale-to-fill + crop (no blur needed).
    """
    portrait = is_portrait(clip_path)

    if portrait:
        bg_filter = (
            f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},boxblur=20:20,format=yuv420p[bg]"
        )
        fg_filter = f"[0:v]scale=-2:{height},format=yuv420p[fg]"
        ov_filter = f"[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[out]"
        vf        = f"{bg_filter};{fg_filter};{ov_filter}"

        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", str(clip_path),
            "-i",                       str(audio_path),
            "-filter_complex", vf,
            "-map", "[out]",
            "-map", "1:a:0",
            "-r",    str(fps),
            "-c:v",  "libx264", "-preset", "slow", "-crf", "18",
            "-c:a",  "aac", "-b:a", "192k",
            "-shortest",
            str(out_mp4),
        ]
    else:
        vf = (
            f"scale={width}:{height}:force_original_aspect_ratio=increase,"
            f"crop={width}:{height},format=yuv420p"
        )
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", "-i", str(clip_path),
            "-i",                       str(audio_path),
            "-map",  "0:v:0",
            "-map",  "1:a:0",
            "-vf",   vf,
            "-r",    str(fps),
            "-c:v",  "libx264", "-preset", "slow", "-crf", "18",
            "-c:a",  "aac", "-b:a", "192k",
            "-shortest",
            str(out_mp4),
        ]

    run(cmd)


# ── Clip resolution ───────────────────────────────────────────────────────────

def resolve_clip(stem: str, override: str | None) -> Path | None:
    """
    Return the visualizer clip to use for this stem, or None for still-image path.
    Priority:
      1. --clip override
      2. images/{stem}.mp4
      3. images/default_visual.mp4
      4. None (still image fallback)
    """
    if override:
        p_override = IMAGES_DIR / override
        if not p_override.suffix:
            p_override = p_override.with_suffix(".mp4")
        if p_override.exists():
            return p_override
        p(f"  [WARN] --clip {override} not found — falling back to default")

    per_beat = IMAGES_DIR / f"{stem}.mp4"
    if per_beat.exists():
        return per_beat

    default_clip = IMAGES_DIR / "default_visual.mp4"
    if default_clip.exists():
        return default_clip

    return None


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
            # Thumbnail — pure still shot from the clip, no text overlay
            if not thumb_path.exists():
                clip_for_thumb = resolve_clip(stem, args.clip)

                if clip_for_thumb:
                    # Extract frame at 3s — clean still shot from the video
                    ok = make_thumbnail(clip_for_thumb, thumb_path, width, height, seek=3.0)
                    if ok:
                        p(f"  [THUMB] {thumb_path.name}")
                    else:
                        p(f"  [THUMB] frame extract failed — skipped")
                else:
                    p(f"  [THUMB] skipped — no clip available")

            # Resolve clip
            clip = resolve_clip(stem, args.clip)

            if clip:
                p(f"  [CLIP]  {clip.name}  ({'portrait' if is_portrait(clip) else 'landscape'})")
                render_video_from_clip(audio_file, clip, mp4_path, width, height, fps)
            else:
                bg_img = IMAGES_DIR / f"{stem}.jpg"
                if not bg_img.exists():
                    default_jpg = ROOT / "images" / "default.jpg"
                    bg_img = default_jpg if default_jpg.exists() else None
                if bg_img and bg_img.exists():
                    p(f"  [IMG]   {bg_img.name}  (still image + zoompan)")
                    render_video(audio_file, bg_img, mp4_path, width, height, fps)
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
