"""
render_lit.py

Clean beat video renderer:
  - Still photo background: images/{stem}.jpg → images/default.jpg
  - FY3 HP logo spinning at bottom-center (fy3_spin.mov looped)
  - No video clips, no overlays, no effects — copyright-safe

Output: output/{stem}.mp4

Signals (compatible with bot's run_render_live parser):
    [RENDER] stem     — starting
    [DONE]   stem     — success
    [FAIL]   stem: X  — error
    [SKIP]   stem     — already exists (unless --force)
    [COMPLETE] N/M    — all done

Usage:
    python render_lit.py
    python render_lit.py --only army
    python render_lit.py --only "army,hood_legend" --force
"""

from __future__ import annotations

import argparse
import json
import os
import subprocess
import sys
import tempfile
import warnings
from concurrent.futures import ProcessPoolExecutor, TimeoutError as FuturesTimeout
from pathlib import Path

import yaml

warnings.filterwarnings("ignore")

from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ── Paths ──────────────────────────────────────────────────────────────────────

ROOT       = Path(__file__).resolve().parent
BEATS_DIR  = ROOT / "beats"
META_DIR   = ROOT / "metadata"
IMAGES_DIR = ROOT / "images"
OUT_DIR    = ROOT / "output"

# ── Fonts ──────────────────────────────────────────────────────────────────────

FONT_THEME   = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"
FONT_IMPACT  = "/System/Library/Fonts/Supplemental/Impact.ttf"
FONT_SFPRO   = "/Library/Fonts/SF-Pro-Rounded-Black.otf"
FONT_BOLD    = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"


def p(msg: str):
    print(msg, flush=True)


# ── Config ─────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    with open(ROOT / "config.yaml") as f:
        return yaml.safe_load(f) or {}


# ── Stem helpers ───────────────────────────────────────────────────────────────

def safe_stem(path: Path) -> str:
    import re
    s = path.stem.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s.strip("_")


def get_audio_duration(audio_path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(audio_path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(json.loads(r.stdout).get("format", {}).get("duration", 120))
    except Exception:
        return 120.0


# ── Beat Analysis ──────────────────────────────────────────────────────────────

def _do_librosa_analysis(audio_path_str: str) -> dict:
    """Top-level picklable function — all librosa work runs here in a subprocess."""
    import librosa
    import numpy as np
    from scipy.signal import butter, filtfilt

    y, sr = librosa.load(audio_path_str, sr=22050, mono=True)
    duration = float(len(y)) / sr

    # Beat grid
    try:
        y_harm, y_perc = librosa.effects.hpss(y)
        onset_env = librosa.onset.onset_strength(y=y_perc, sr=sr, aggregate=np.median)
        tempo_arr, beat_frames = librosa.beat.beat_track(
            onset_envelope=onset_env, sr=sr, units="frames"
        )
        tempo = float(np.atleast_1d(tempo_arr)[0])
        for mult in [2.0, 0.5, 3.0]:
            alt = tempo * mult
            if 60 <= alt <= 200 and abs(alt - 130) < abs(tempo - 130):
                tempo = alt
        bpm = int(round(tempo))
        beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
    except Exception:
        y_harm = y
        bpm = 120
        beat_times = []

    # Musical key
    try:
        chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr, bins_per_octave=36)
        chroma_med = np.median(chroma, axis=1)
        MAJOR = np.array([6.35,2.23,3.48,2.33,4.38,4.09,2.52,5.19,2.39,3.66,2.29,2.88])
        MINOR = np.array([6.33,2.68,3.52,5.38,2.60,3.53,2.54,4.75,3.98,2.69,3.34,3.17])
        NOTES = ["C","C#","D","D#","E","F","F#","G","G#","A","A#","B"]
        best_score, best_key = -np.inf, "C Minor"
        for i in range(12):
            sm = np.corrcoef(chroma_med, np.roll(MAJOR, i))[0, 1]
            si = np.corrcoef(chroma_med, np.roll(MINOR, i))[0, 1]
            if sm > best_score:
                best_score, best_key = sm, f"{NOTES[i]} Major"
            if si > best_score:
                best_score, best_key = si, f"{NOTES[i]} Minor"
        key = best_key
    except Exception:
        key = "C Minor"

    return {
        "bpm":        bpm,
        "key":        key,
        "beat_times": beat_times,
        "duration":   duration,
    }


def analyze_beats_detailed(audio_path: Path, stem: str) -> dict:
    """
    Returns bpm, key, beat_times, duration.
    Cached to /tmp/{stem}_beatdata.json.
    Runs librosa in a subprocess with 90s hard timeout — never hangs the render.
    Falls back to safe defaults on any error.
    """
    cache_path = Path(tempfile.gettempdir()) / f"{stem}_beatdata.json"
    if cache_path.exists():
        try:
            p(f"  [ANALYSIS] Loaded from cache")
            return json.loads(cache_path.read_text())
        except Exception:
            pass

    safe_default = {
        "bpm": 120, "key": "C Minor",
        "beat_times": [],
        "duration": get_audio_duration(audio_path),
    }

    p(f"  [ANALYSIS] Loading audio (90s timeout)...")
    try:
        with ProcessPoolExecutor(max_workers=1) as ex:
            future = ex.submit(_do_librosa_analysis, str(audio_path))
            result = future.result(timeout=90)
        try:
            cache_path.write_text(json.dumps(result))
        except Exception:
            pass
        p(f"  [ANALYSIS] {result['bpm']} BPM | {result['key']}")
        return result
    except FuturesTimeout:
        p(f"  [WARN] Beat analysis timed out (>90s) — using defaults")
    except ImportError:
        p(f"  [WARN] librosa/scipy not available — using defaults")
    except Exception as e:
        p(f"  [WARN] Analysis error: {e} — using defaults")
    return safe_default


# ── Font helper ────────────────────────────────────────────────────────────────

def _best_font(size: int) -> ImageFont.FreeTypeFont:
    for path in [FONT_THEME, FONT_SFPRO, FONT_IMPACT, FONT_BOLD, FONT_REGULAR]:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


# ── Thumbnail ──────────────────────────────────────────────────────────────────

def make_thumbnail(photo_path: Path, out_path: Path,
                   width: int = 1920, height: int = 1080,
                   portrait_crop: float = 0.40):
    """
    Photo scaled to fill 1920×1080 + FY3 HP stamp bottom-center.
    Idempotent — skips if already exists.
    """
    if out_path.exists():
        p(f"  [THUMB] already exists, skipping")
        return

    stamp_path = ROOT / "brand" / "fy3_hp_stamp.png"
    if not stamp_path.exists():
        stamp_path = ROOT / "brand" / "fy3_thumb_stamp.png"

    try:
        img = Image.open(photo_path).convert("RGB")
        img_ratio    = img.width / img.height
        target_ratio = width / height
        # Scale-to-fill: no bars, no blur — crop excess
        if img_ratio > target_ratio:
            # Wider than target — scale to height, crop sides
            new_h, new_w = height, int(img_ratio * height)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            left = (new_w - width) // 2
            img = img.crop((left, 0, left + width, height))
        else:
            # Taller than target (portrait) — scale to width, crop bottom
            # Shift crop up slightly to preserve head at top
            new_w, new_h = width, int(width / img_ratio)
            img = img.resize((new_w, new_h), Image.LANCZOS)
            top = max(0, int((new_h - height) * portrait_crop))
            img = img.crop((0, top, width, top + height))

        if stamp_path.exists():
            img_rgba = img.convert("RGBA")
            stamp    = Image.open(stamp_path).convert("RGBA")
            x = (width - stamp.width) // 2
            y = height - stamp.height - 20
            img_rgba.paste(stamp, (x, y), stamp)
            img = img_rgba.convert("RGB")

        out_path.parent.mkdir(parents=True, exist_ok=True)
        img.save(str(out_path), "JPEG", quality=92)
        p(f"  [THUMB] {out_path.name}")
    except Exception as e:
        p(f"  [WARN] Thumbnail failed: {e}")


# ── Main Render ────────────────────────────────────────────────────────────────

def render_lit_video(audio_path: Path, photo_path: Path,
                     out_mp4: Path,
                     fy3_spin_path: Path | None = None,
                     width: int = 1920, height: int = 1080, fps: int = 30,
                     portrait_crop: float = 0.40):
    """
    Still photo background + looped FY3 spinning logo composited in Python (PIL),
    piped to ffmpeg. No ffmpeg overlay filter = no black bar ever.
    """
    from PIL import Image as PILImage
    import io

    # ── Prepare background ──────────────────────────────────────────────────
    bg_src = PILImage.open(str(photo_path)).convert("RGB")
    bg_w, bg_h = bg_src.size
    bg_ratio = bg_w / bg_h
    target_ratio = width / height
    if bg_ratio > target_ratio:
        new_h, new_w = height, int(bg_ratio * height)
    else:
        new_w, new_h = width, int(width / bg_ratio)
    bg_src = bg_src.resize((new_w, new_h), PILImage.LANCZOS)
    if bg_ratio > target_ratio:
        left = (new_w - width) // 2
        bg_src = bg_src.crop((left, 0, left + width, height))
    else:
        top = max(0, int((new_h - height) * portrait_crop))
        bg_src = bg_src.crop((0, top, width, top + height))
    bg_rgba = bg_src.convert("RGBA")

    # ── Load spin logo frames — direct from PNG folder, no video decode ────
    spin_frames = []
    if fy3_spin_path and fy3_spin_path.exists():
        frame_files = sorted(fy3_spin_path.glob("f_*.png"))
        for ff in frame_files:
            spin_frames.append(PILImage.open(str(ff)).convert("RGBA"))

    # ── Get audio duration ──────────────────────────────────────────────────
    probe = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(audio_path)],
        capture_output=True, text=True
    )
    duration = float(probe.stdout.strip())
    total_frames = int(duration * fps)

    # ── Pipe composited frames to ffmpeg ────────────────────────────────────
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo", "-vcodec", "rawvideo",
        "-s", f"{width}x{height}", "-pix_fmt", "rgb24",
        "-r", str(fps), "-i", "pipe:0",
        "-i", str(audio_path),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "18",
        "-pix_fmt", "yuv420p",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_mp4),
    ]

    # ffmpeg stderr → temp file, NOT a pipe. On Windows the 64KB stderr pipe
    # buffer fills with ffmpeg's progress output, ffmpeg blocks, stops reading
    # stdin, and the frame-write loop below deadlocks. A file has no such limit.
    err_log = tempfile.TemporaryFile()
    proc = subprocess.Popen(cmd, stdin=subprocess.PIPE, stderr=err_log)

    n_spin = len(spin_frames)
    for i in range(total_frames):
        frame = bg_rgba.copy()
        if n_spin > 0:
            spin_frame = spin_frames[i % n_spin]
            # Scale spin logo to reasonable size
            sw = min(spin_frame.width, width // 2)
            sh = int(spin_frame.height * sw / spin_frame.width)
            if sw != spin_frame.width:
                spin_frame = spin_frame.resize((sw, sh), PILImage.LANCZOS)
            # Lower-third, horizontally centered — keeps the logo clear of the
            # subject's face (faces sit high in most portrait crops).
            x = (width - sw) // 2
            y = height - sh - 70
            frame.alpha_composite(spin_frame, (x, y))
        proc.stdin.write(frame.convert("RGB").tobytes())

    proc.stdin.close()
    proc.wait()

    if proc.returncode != 0:
        err_log.seek(0)
        err = err_log.read().decode(errors="replace")
        err_log.close()
        lines = [l.strip() for l in err.splitlines() if l.strip()]
        raise RuntimeError(lines[-1] if lines else "unknown ffmpeg error")
    err_log.close()


# ── Main ───────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Beat video renderer.")
    parser.add_argument("--only",  type=str, default="",
                        help="Comma-separated stems (e.g. army,hood_legend). Default: all.")
    parser.add_argument("--force", action="store_true",
                        help="Overwrite existing renders.")
    args = parser.parse_args()

    p(f"\n{'─'*60}")
    p(f"  render_lit.py")
    p(f"{'─'*60}\n")

    cfg        = load_config()
    render_cfg = cfg.get("render", {})
    width  = int(render_cfg.get("width",  1920))
    height = int(render_cfg.get("height", 1080))
    fps    = int(render_cfg.get("fps",    30))

    OUT_DIR.mkdir(exist_ok=True)

    # Build stem list
    if args.only.strip():
        stems = [s.strip() for s in args.only.split(",") if s.strip()]
    else:
        stems = [safe_stem(f) for f in sorted(BEATS_DIR.iterdir())
                 if f.suffix.lower() in (".mp3", ".wav")]

    if not stems:
        p("No beats found. Drop MP3/WAV files into beats/ and try again.")
        sys.exit(0)

    # Validate — find audio file for each stem
    valid_stems = []
    for stem in stems:
        for ext in (".mp3", ".wav"):
            candidate = BEATS_DIR / f"{stem}{ext}"
            if candidate.exists():
                valid_stems.append((stem, candidate))
                break
        else:
            p(f"[FAIL] {stem}: beats/{stem}.mp3 not found — skipping")

    if not valid_stems:
        p("Nothing to render.")
        sys.exit(0)

    # FY3 spinning logo — load direct from pre-generated transparent PNGs (no video decode)
    fy3_spin = ROOT / "brand" / "fy3_spin_frames_clean"
    if fy3_spin.exists() and list(fy3_spin.glob("f_*.png")):
        p(f"[ASSETS] FY3 spinning logo: {fy3_spin.name}/ ({len(list(fy3_spin.glob('f_*.png')))} frames)")
    else:
        fy3_spin = None
        p("[WARN] brand/fy3_spin_frames_clean not found — rendering without logo")

    done_count = fail_count = skip_count = 0
    total = len(valid_stems)

    for stem, audio_path in valid_stems:
        out_mp4 = OUT_DIR / f"{stem}.mp4"

        if out_mp4.exists() and not args.force:
            p(f"[SKIP] {stem}")
            skip_count += 1
            continue

        if out_mp4.exists() and args.force:
            try:
                out_mp4.unlink()
            except Exception:
                pass

        p(f"[RENDER] {stem}")

        try:
            # 1. Analyze beats
            p(f"  Analyzing beats...")
            analyze_beats_detailed(audio_path, stem)

            # 2. Resolve photo
            photo = IMAGES_DIR / f"{stem}.jpg"
            if not photo.exists():
                photo = IMAGES_DIR / "default.jpg"
            if not photo.exists():
                raise FileNotFoundError(
                    f"No photo: images/{stem}.jpg or images/default.jpg")

            # 3. Thumbnail — read optional thumb_crop from metadata
            _meta_crop = 0.40
            try:
                import json as _json
                _mp = META_DIR / f"{stem}.json"
                if _mp.exists():
                    _meta_crop = float(_json.loads(_mp.read_text()).get("thumb_crop", 0.40))
            except Exception:
                pass
            make_thumbnail(photo, OUT_DIR / f"{stem}_thumb.jpg", width, height,
                           portrait_crop=_meta_crop)

            # 4. Render (fall back to no-spin if spin overlay fails)
            p(f"  Rendering ({photo.name})...")
            try:
                render_lit_video(
                    audio_path    = audio_path,
                    photo_path    = photo,
                    out_mp4       = out_mp4,
                    fy3_spin_path = fy3_spin,
                    width         = width,
                    height        = height,
                    fps           = fps,
                    portrait_crop = _meta_crop,
                )
            except Exception as _spin_err:
                if fy3_spin:
                    p(f"  [WARN] Spin overlay failed ({_spin_err}), retrying without logo...")
                    render_lit_video(
                        audio_path    = audio_path,
                        photo_path    = photo,
                        out_mp4       = out_mp4,
                        fy3_spin_path = None,
                        width         = width,
                        height        = height,
                        fps           = fps,
                        portrait_crop = _meta_crop,
                    )
                else:
                    raise

            if out_mp4.exists():
                size_mb = out_mp4.stat().st_size / 1_048_576
                p(f"[DONE] {stem}  ({size_mb:.1f} MB)")
                done_count += 1
                # Auto-preview — best effort, platform-aware, NEVER fatal.
                # (Mac used `open -a QuickTime`; on Windows that raised WinError 2,
                #  which the except below caught and then DELETED the good render.)
                try:
                    if sys.platform == "darwin":
                        subprocess.Popen(["open", "-a", "QuickTime Player", str(out_mp4)])
                    elif sys.platform == "win32":
                        os.startfile(str(out_mp4))  # type: ignore[attr-defined]
                    else:
                        subprocess.Popen(["xdg-open", str(out_mp4)])
                except Exception:
                    pass
            else:
                raise RuntimeError("Output file not created")

        except subprocess.TimeoutExpired:
            p(f"[FAIL] {stem}: ffmpeg timed out (>20 min)")
            fail_count += 1
            out_mp4.unlink(missing_ok=True)

        except Exception as exc:
            p(f"[FAIL] {stem}: {exc}")
            fail_count += 1
            out_mp4.unlink(missing_ok=True)

    p(f"\n{'─'*60}")
    p(f"[COMPLETE] {done_count}/{total} rendered  |  "
      f"{skip_count} skipped  |  {fail_count} failed")
    p(f"{'─'*60}")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
