"""
render_lit.py

Beat-synced LIT video renderer with:
  - Doom-style cellular automaton flame overlay
  - LeekThatsFye branding subtitle always visible
  - 808 bass hit → eq brightness flash
  - Hi-hat roll → hue rotation
  - Optional zoom pulse on bass hits (fire intensity only)
  - Orange color grade (colorchannelmixer)

Output: output/{stem}_lit.mp4  (never conflicts with regular renders)

Signals (compatible with bot's run_render_live parser):
    [RENDER] stem     — starting
    [DONE]   stem     — success
    [FAIL]   stem: X  — error
    [SKIP]   stem     — already exists (unless --force)
    [COMPLETE] N/M    — all done

Usage:
    python render_lit.py --only army --intensity medium
    python render_lit.py --intensity fire
    python render_lit.py --only "army,hood_legend" --intensity fire --force
"""

from __future__ import annotations

import argparse
import json
import math
import struct
import subprocess
import sys
import tempfile
import warnings
from pathlib import Path

import numpy as np
import yaml

warnings.filterwarnings("ignore")

# PIL imports — all from Pillow
from PIL import Image, ImageDraw, ImageFilter, ImageFont

# ── Paths ─────────────────────────────────────────────────────────────────────

ROOT       = Path(__file__).resolve().parent
BEATS_DIR  = ROOT / "beats"
META_DIR   = ROOT / "metadata"
IMAGES_DIR = ROOT / "images"
OUT_DIR    = ROOT / "output"

# ── Constants ─────────────────────────────────────────────────────────────────

FONT_THEME   = "/System/Library/Fonts/Supplemental/DIN Condensed Bold.ttf"  # primary LTF font
FONT_IMPACT  = "/System/Library/Fonts/Supplemental/Impact.ttf"
FONT_SFPRO   = "/Library/Fonts/SF-Pro-Rounded-Black.otf"
FONT_BOLD    = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
FONT_REGULAR = "/System/Library/Fonts/Supplemental/Arial.ttf"

FLAME_DURATION = 15.0   # seconds — looped by ffmpeg
FLASH_HOLD     = 0.08   # seconds each flash lasts
HUE_HOLD       = 0.05   # seconds each hue event lasts
MAX_BASS_EXPR  = 80     # cap so ffmpeg cmdline stays sane
MAX_HIHAT_EXPR = 60

# Intensity presets
INTENSITY_PARAMS = {
    "subtle": dict(flash_strength=0.3, hue_degrees=15, zoom_amount=0.0,  flame_opacity=0.40),
    "medium": dict(flash_strength=0.5, hue_degrees=25, zoom_amount=0.0,  flame_opacity=0.65),
    "fire":   dict(flash_strength=0.7, hue_degrees=40, zoom_amount=0.08, flame_opacity=0.85),
}

# ── Flush helper ──────────────────────────────────────────────────────────────

def p(msg: str):
    """Print with immediate flush so bot's async pipe sees it instantly."""
    print(msg, flush=True)


# ── Config ────────────────────────────────────────────────────────────────────

def load_config() -> dict:
    cfg_path = ROOT / "config.yaml"
    with open(cfg_path) as f:
        return yaml.safe_load(f) or {}


# ── Stem helpers ──────────────────────────────────────────────────────────────

def safe_stem(path: Path) -> str:
    import re
    s = path.stem.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s.strip("_")


def resolve_clip(stem: str, seo_artist: str | None = None) -> Path | None:
    """Return the best visualizer clip for this stem, or None.

    Checks artist subfolders first, then falls back to flat images/.
    """
    candidates = []
    if seo_artist:
        candidates.append(IMAGES_DIR / seo_artist / f"{stem}.mp4")
        candidates.append(IMAGES_DIR / seo_artist / "default_visual.mp4")
    candidates.append(IMAGES_DIR / f"{stem}.mp4")
    candidates.append(IMAGES_DIR / "default_visual.mp4")
    for candidate in candidates:
        if candidate.exists():
            return candidate
    return None


def is_portrait(clip_path: Path) -> bool:
    """Return True if clip is taller than wide."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_streams", str(clip_path)],
            capture_output=True, text=True, timeout=15,
        )
        for s in json.loads(r.stdout).get("streams", []):
            if s.get("codec_type") == "video":
                return int(s.get("height", 0)) > int(s.get("width", 0))
    except Exception:
        pass
    return False


def get_audio_duration(audio_path: Path) -> float:
    """Return audio duration in seconds via ffprobe."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-print_format", "json",
             "-show_format", str(audio_path)],
            capture_output=True, text=True, timeout=30,
        )
        return float(json.loads(r.stdout).get("format", {}).get("duration", 120))
    except Exception:
        return 120.0


# ── Beat Analysis ─────────────────────────────────────────────────────────────

def analyze_beats_detailed(audio_path: Path, stem: str) -> dict:
    """
    Returns:
        bpm          : int
        key          : str
        beat_times   : list[float]
        bass_times   : list[float]   (808 hits)
        hihat_times  : list[float]
        duration     : float

    Cached to /tmp/{stem}_beatdata.json.
    Falls back to safe defaults on ANY error so render always proceeds.
    """
    cache_path = Path(tempfile.gettempdir()) / f"{stem}_beatdata.json"
    if cache_path.exists():
        try:
            data = json.loads(cache_path.read_text())
            p(f"  [ANALYSIS] Loaded from cache")
            return data
        except Exception:
            pass

    safe_default = {
        "bpm": 120, "key": "C Minor",
        "beat_times": [], "bass_times": [], "hihat_times": [],
        "duration": get_audio_duration(audio_path),
    }

    try:
        import librosa
        from scipy.signal import butter, filtfilt

        p(f"  [ANALYSIS] Loading audio...")
        try:
            y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
        except MemoryError:
            p(f"  [WARN] MemoryError loading audio — using defaults")
            return safe_default

        duration = float(len(y)) / sr

        # ── Beat grid ─────────────────────────────────────────────────────────
        try:
            y_harm, y_perc = librosa.effects.hpss(y)
            onset_env = librosa.onset.onset_strength(y=y_perc, sr=sr, aggregate=np.median)
            tempo_arr, beat_frames = librosa.beat.beat_track(
                onset_envelope=onset_env, sr=sr, units="frames"
            )
            # tempo_arr may be a 0-d array, 1-element array, or scalar
            tempo_val = np.atleast_1d(tempo_arr)[0]
            tempo = float(tempo_val)
            # Octave correction toward 130 BPM (trap center)
            for mult in [2.0, 0.5, 3.0]:
                alt = tempo * mult
                if 60 <= alt <= 200 and abs(alt - 130) < abs(tempo - 130):
                    tempo = alt
            bpm = int(round(tempo))
            beat_times = librosa.frames_to_time(beat_frames, sr=sr).tolist()
        except Exception as e:
            p(f"  [WARN] Beat tracking failed: {e}")
            bpm = 120
            beat_times = []

        # ── Musical key ───────────────────────────────────────────────────────
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
        except Exception as e:
            p(f"  [WARN] Key detection failed: {e}")
            key = "C Minor"

        # ── 808 / bass detection (low-pass < 200 Hz) ─────────────────────────
        try:
            def butter_filter(data, cutoff, fs, btype, order=5):
                nyq = fs / 2
                fc = cutoff / nyq
                fc = min(max(fc, 0.001), 0.999)
                b, a = butter(order, fc, btype=btype)
                return filtfilt(b, a, data)

            y_bass = butter_filter(y, 200, sr, "low")
            bass_frames = librosa.onset.onset_detect(
                y=y_bass, sr=sr, delta=0.4, wait=10, units="time"
            )
            bass_times = [float(t) for t in bass_frames]
        except Exception as e:
            p(f"  [WARN] Bass detection failed: {e}")
            bass_times = []

        # ── Hi-hat detection (high-pass > 6000 Hz) ───────────────────────────
        try:
            y_hihat = butter_filter(y, 6000, sr, "high")
            hihat_frames = librosa.onset.onset_detect(
                y=y_hihat, sr=sr, delta=0.15, wait=4, units="time"
            )
            hihat_times = [float(t) for t in hihat_frames[:MAX_HIHAT_EXPR]]
        except Exception as e:
            p(f"  [WARN] Hi-hat detection failed: {e}")
            hihat_times = []

        result = {
            "bpm":        bpm,
            "key":        key,
            "beat_times": beat_times,
            "bass_times": bass_times[:MAX_BASS_EXPR],
            "hihat_times":hihat_times,
            "duration":   duration,
        }

        try:
            cache_path.write_text(json.dumps(result))
        except Exception:
            pass

        p(f"  [ANALYSIS] {bpm} BPM | {key} | "
          f"{len(bass_times)} bass | {len(hihat_times)} hihats")
        return result

    except ImportError:
        p(f"  [WARN] librosa/scipy not available — using defaults")
        return safe_default
    except Exception as e:
        p(f"  [WARN] Analysis error: {e} — using defaults")
        return safe_default


# ── ffmpeg Expression Builders ────────────────────────────────────────────────

def build_flash_expr(bass_times: list[float], strength: float,
                     hold: float = FLASH_HOLD) -> str:
    """eq brightness= expression: flash +strength for hold seconds at each bass hit."""
    if not bass_times:
        return "0"
    terms = "+".join(
        f"between(t,{t:.3f},{t + hold:.3f})*{strength:.2f}"
        for t in bass_times[:MAX_BASS_EXPR]
    )
    return f"min({terms}, {strength:.2f})"


def build_hue_expr(hihat_times: list[float], degrees: float,
                   hold: float = HUE_HOLD) -> str:
    """hue h= expression: rotate hue by degrees for hold seconds at each hihat."""
    if not hihat_times:
        return "0"
    terms = "+".join(
        f"between(t,{t:.3f},{t + hold:.3f})*{degrees:.1f}"
        for t in hihat_times[:MAX_HIHAT_EXPR]
    )
    return f"min({terms}, {degrees:.1f})"


def build_zoompan_expr(bass_times: list[float], zoom_amount: float,
                        fps: int = 30) -> str | None:
    """
    zoompan z= expression: zoom in by zoom_amount for ~6 frames at each bass hit.
    Returns None if zoom_amount == 0 (disabled).
    """
    if zoom_amount == 0.0 or not bass_times:
        return None
    # Convert time → frame number thresholds
    terms = "+".join(
        f"between(on,{int(t * fps)},{int(t * fps) + 5})*{zoom_amount:.3f}"
        for t in bass_times[:MAX_BASS_EXPR]
    )
    return f"1.0+min({terms}, {zoom_amount:.3f})"


# ── PIL Asset Generators ──────────────────────────────────────────────────────

def _best_font(size: int, bold: bool = False) -> ImageFont.FreeTypeFont:
    """Load theme font (DIN Condensed Bold) → SF Pro Rounded Black → Impact → Arial fallbacks."""
    paths = [FONT_THEME, FONT_SFPRO, FONT_IMPACT, FONT_BOLD if bold else FONT_REGULAR, FONT_REGULAR]
    for path in paths:
        try:
            return ImageFont.truetype(path, size)
        except Exception:
            continue
    return ImageFont.load_default()


def generate_ltf_overlay(out_path: Path, width: int = 1920, height: int = 1080):
    """
    Static RGBA PNG: 'LTF' in DIN Condensed Bold 220pt with 3-layer blue flame glow.
      Layer 1: deep navy/indigo GaussianBlur(12) outer glow
      Layer 2: electric blue GaussianBlur(6) mid glow
      Layer 3: icy white-blue sharp core
    Positioned: horizontally centered, 60px from bottom.
    Bulletproof: falls back gracefully on any PIL error.
    """
    try:
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        font   = _best_font(220)
        text   = "LTF"

        # Measure text
        tmp_draw = ImageDraw.Draw(canvas)
        bbox = tmp_draw.textbbox((0, 0), text, font=font)
        tw = bbox[2] - bbox[0]
        th = bbox[3] - bbox[1]
        tx = (width - tw) // 2
        ty = height - th - 60

        def make_text_layer(color, size_adj=0):
            layer = Image.new("RGBA", (width, height), (0, 0, 0, 0))
            d = ImageDraw.Draw(layer)
            f = _best_font(220 + size_adj) if size_adj else font
            d.text((tx, ty), text, font=f, fill=color)
            return layer

        # Layer 1: deep indigo outer glow + heavy blur
        shadow = make_text_layer((30, 0, 160, 255))
        shadow = shadow.filter(ImageFilter.GaussianBlur(14))

        # Layer 2: electric blue mid glow + medium blur
        mid = make_text_layer((0, 120, 255, 230))
        mid = mid.filter(ImageFilter.GaussianBlur(6))

        # Layer 3: icy cyan-white sharp core
        core = make_text_layer((180, 240, 255, 255))

        # Composite all layers
        result = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        result = Image.alpha_composite(result, shadow)
        result = Image.alpha_composite(result, mid)
        result = Image.alpha_composite(result, core)

        out_path.parent.mkdir(parents=True, exist_ok=True)
        result.save(str(out_path), "PNG")
        return True
    except Exception as e:
        p(f"  [WARN] LTF overlay generation failed: {e}")
        # Fallback: blank transparent PNG
        try:
            Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(str(out_path), "PNG")
        except Exception:
            pass
        return False


def generate_brand_overlay(out_path: Path, width: int = 1920, height: int = 1080):
    """
    Static RGBA PNG: 'LeekThatsFye' in Arial Bold 72pt.
    White text + orange drop shadow.
    Positioned: centered, 20px from bottom.
    Bulletproof: transparent fallback on error.
    """
    try:
        canvas = Image.new("RGBA", (width, height), (0, 0, 0, 0))
        font   = _best_font(72, bold=True)
        text   = "LeekThatsFye"
        draw   = ImageDraw.Draw(canvas)

        bbox = draw.textbbox((0, 0), text, font=font)
        tw   = bbox[2] - bbox[0]
        th   = bbox[3] - bbox[1]
        tx   = (width - tw) // 2
        ty   = height - th - 20

        # Electric blue drop shadow
        draw.text((tx + 3, ty + 3), text, font=font, fill=(0, 100, 255, 200))
        # Icy white text
        draw.text((tx, ty), text, font=font, fill=(220, 240, 255, 235))

        out_path.parent.mkdir(parents=True, exist_ok=True)
        canvas.save(str(out_path), "PNG")
        return True
    except Exception as e:
        p(f"  [WARN] Brand overlay generation failed: {e}")
        try:
            Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(str(out_path), "PNG")
        except Exception:
            pass
        return False


# ── Doom Fire Generator ───────────────────────────────────────────────────────

def generate_flame_video(out_path: Path,
                          width: int = 1920, height: int = 1080,
                          fps: int = 30, loop_duration: float = FLAME_DURATION):
    """
    Doom-style cellular automaton fire effect piped to ffmpeg.
    Blue flame palette: black → deep indigo → electric blue → cyan → icy white.
    Generates a loopable RGBA video at quarter-resolution, then scaled to full in ffmpeg.
    Fully numpy-vectorized — no Python loops over pixels.
    Bulletproof: solid blue fallback video if generation fails.
    """
    # Work at quarter resolution for speed; ffmpeg scales to full
    fw = width // 4
    fh = height // 4
    n_frames = int(fps * loop_duration)

    # Blue flame palette (256 entries): black → deep indigo → electric blue → cyan → white
    palette = np.zeros((256, 4), dtype=np.uint8)
    for i in range(256):
        t = i / 255.0
        if t < 0.25:
            # Black → deep indigo
            t2 = t * 4
            r = int(t2 * 20)
            g = 0
            b = int(t2 * 120)
            a = int(t2 * 200)
        elif t < 0.5:
            # Deep indigo → electric blue
            t2 = (t - 0.25) * 4
            r = int(20 + t2 * 10)
            g = int(t2 * 60)
            b = int(120 + t2 * 135)
            a = int(200 + t2 * 40)
        elif t < 0.75:
            # Electric blue → bright cyan
            t2 = (t - 0.5) * 4
            r = int(30 * (1 - t2))
            g = int(60 + t2 * 170)
            b = 255
            a = int(240 + t2 * 10)
        else:
            # Cyan → icy white
            t2 = (t - 0.75) * 4
            r = int(t2 * 220)
            g = int(230 + t2 * 25)
            b = 255
            a = 255
        palette[i] = [r, g, b, a]

    # Fire grid — float32 for smooth decay
    fire = np.zeros((fh, fw), dtype=np.float32)
    # Seed: bottom 3 rows = full intensity
    fire[-3:, :] = 255.0

    # Start ffmpeg pipe
    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pixel_format", "rgba",
        "-video_size", f"{fw}x{fh}",
        "-framerate", str(fps),
        "-i", "pipe:0",
        "-vf", f"scale={width}:{height}:flags=lanczos",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuva420p",
        str(out_path),
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        rng = np.random.default_rng(42)

        for frame_i in range(n_frames):
            # Vectorized Doom fire step
            # For each cell (y, x): new[y,x] = avg of below neighbors - decay
            below = np.roll(fire, -1, axis=0)  # shift up
            left  = np.roll(below, -1, axis=1)
            right = np.roll(below,  1, axis=1)
            avg   = (fire + below + left + right) / 4.0
            decay = rng.integers(0, 13, size=(fh, fw)).astype(np.float32)
            fire  = np.clip(avg - decay, 0, 255)
            # Re-seed bottom rows every frame
            fire[-3:, :] = 255.0

            # Map intensity → RGBA via palette lookup
            idx    = fire.astype(np.uint8)
            frame  = palette[idx]   # shape (fh, fw, 4)
            try:
                proc.stdin.write(frame.tobytes())
            except BrokenPipeError:
                break

        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.wait(timeout=60)

        if proc.returncode == 0 and out_path.exists():
            p(f"  [FLAME] Generated {n_frames} frames → {out_path.name}")
            return True
        else:
            raise RuntimeError(f"ffmpeg exited {proc.returncode}")

    except Exception as e:
        p(f"  [WARN] Flame generation failed: {e} — using solid blue fallback")
        # Fallback: solid semi-transparent blue video
        try:
            fallback_cmd = [
                "ffmpeg", "-y",
                "-f", "lavfi",
                "-i", f"color=c=0x0044FF@0.7:size={width}x{height}:rate={fps}",
                "-t", str(loop_duration),
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-pix_fmt", "yuva420p",
                str(out_path),
            ]
            subprocess.run(fallback_cmd, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=60)
            return True
        except Exception as e2:
            p(f"  [WARN] Flame fallback also failed: {e2}")
            return False


# ── LTF Flash Video ───────────────────────────────────────────────────────────

def generate_ltf_flash_video(out_path: Path, ltf_png: Path,
                              beat_times: list[float], duration: float,
                              width: int = 1920, height: int = 1080, fps: int = 30):
    """
    Animated RGBA video: LTF text pulses bright on each beat, dim otherwise.
    Uses per-frame alpha modulation via numpy.
    base_alpha=0.35 (always slightly visible), flash_alpha=1.0 (on beat).
    Flash envelope: fades over 8 frames.
    Bulletproof: blank transparent video if PNG missing or any error.
    """
    n_frames = int(math.ceil(duration * fps))
    FLASH_FRAMES = 8   # frames the flash envelope lasts

    # Build per-frame alpha array
    alpha_arr = np.full(n_frames, 0.35, dtype=np.float32)
    if beat_times:
        for bt in beat_times:
            center = int(bt * fps)
            for offset in range(FLASH_FRAMES):
                fi = center + offset
                if 0 <= fi < n_frames:
                    strength = (FLASH_FRAMES - offset) / FLASH_FRAMES
                    alpha_arr[fi] = max(alpha_arr[fi], strength)

    # Try to load LTF overlay
    try:
        if ltf_png.exists():
            ltf_img = Image.open(str(ltf_png)).convert("RGBA")
            if ltf_img.size != (width, height):
                ltf_img = ltf_img.resize((width, height), Image.LANCZOS)
        else:
            raise FileNotFoundError("LTF PNG missing")
    except Exception as e:
        p(f"  [WARN] LTF flash video using blank (no PNG): {e}")
        ltf_img = Image.new("RGBA", (width, height), (0, 0, 0, 0))

    # Extract channels
    ltf_arr = np.array(ltf_img, dtype=np.float32)   # (H, W, 4)
    rgb      = ltf_arr[:, :, :3]
    base_a   = ltf_arr[:, :, 3:4]  # keep dims for broadcast

    cmd = [
        "ffmpeg", "-y",
        "-f", "rawvideo",
        "-pixel_format", "rgba",
        "-video_size", f"{width}x{height}",
        "-framerate", str(fps),
        "-i", "pipe:0",
        "-c:v", "libx264",
        "-preset", "fast",
        "-crf", "20",
        "-pix_fmt", "yuva420p",
        str(out_path),
    ]

    try:
        proc = subprocess.Popen(
            cmd,
            stdin=subprocess.PIPE,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
        )

        for fi in range(n_frames):
            a_scale  = float(alpha_arr[fi])
            new_a    = np.clip(base_a * a_scale, 0, 255).astype(np.uint8)
            frame    = np.concatenate([rgb.astype(np.uint8), new_a], axis=2)
            try:
                proc.stdin.write(frame.tobytes())
            except BrokenPipeError:
                break

        try:
            proc.stdin.close()
        except Exception:
            pass
        proc.wait(timeout=120)

        if proc.returncode == 0 and out_path.exists():
            p(f"  [LTF-VID] Generated {n_frames} frames → {out_path.name}")
            return True
        else:
            raise RuntimeError(f"ffmpeg exited {proc.returncode}")

    except Exception as e:
        p(f"  [WARN] LTF flash video failed: {e} — using blank")
        try:
            Image.new("RGBA", (width, height), (0, 0, 0, 0)).save(
                str(out_path.with_suffix(".png")), "PNG"
            )
            blank_cmd = [
                "ffmpeg", "-y",
                "-loop", "1",
                "-i", str(out_path.with_suffix(".png")),
                "-t", str(duration),
                "-c:v", "libx264", "-preset", "fast", "-crf", "20",
                "-pix_fmt", "yuva420p",
                str(out_path),
            ]
            subprocess.run(blank_cmd, check=True,
                           stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL,
                           timeout=120)
            return True
        except Exception as e2:
            p(f"  [WARN] LTF flash fallback failed: {e2}")
            return False


# ── Main Render ───────────────────────────────────────────────────────────────

def render_lit_video(audio_path: Path, clip_path: Path | None,
                     out_mp4: Path,
                     flame_vid: Path,
                     beat_data: dict, params: dict,
                     width: int = 1920, height: int = 1080, fps: int = 30):
    """
    Builds and runs the ffmpeg command with full filter_complex.

    Inputs:
      [0] = visualizer clip  (-stream_loop -1)   OR still image (-loop 1)
      [1] = audio
      [2] = flame overlay    (-stream_loop -1)

    Portrait filter_complex (clip is portrait):
      [0:v] scale+crop+blur → [bg]
      [bg][flame_scaled] blend=screen → [bg_flame]
      [0:v] scale=-2:H → [fg]
      [bg_flame][fg] overlay center → [base]
      [base] eq(brightness flash) → [flashed]
      [flashed] hue(rotation) → [hued]
      [hued] → zoompan or format=yuv420p → [out]

    Landscape / still image: similar but without blur/bg/fg split.
    """
    flash_str  = params["flash_strength"]
    hue_deg    = params["hue_degrees"]
    zoom_amt   = params["zoom_amount"]
    flame_op   = params["flame_opacity"]

    bass_times  = beat_data.get("bass_times",  [])
    hihat_times = beat_data.get("hihat_times", [])
    beat_times  = beat_data.get("beat_times",  [])
    duration    = beat_data.get("duration",     120.0)

    flash_expr  = build_flash_expr(bass_times, flash_str)
    hue_expr    = build_hue_expr(hihat_times, hue_deg)
    zoom_expr   = build_zoompan_expr(bass_times, zoom_amt, fps)

    # ── Input args ────────────────────────────────────────────────────────────
    if clip_path:
        input0 = ["-stream_loop", "-1", "-i", str(clip_path)]
    else:
        # Still image fallback — use default.jpg or create solid color
        default_jpg = ROOT / "images" / "default.jpg"
        if not default_jpg.exists():
            default_jpg = IMAGES_DIR / "default_visual.mp4"
        if default_jpg.exists():
            if str(default_jpg).endswith(".mp4"):
                input0 = ["-stream_loop", "-1", "-i", str(default_jpg)]
            else:
                input0 = ["-loop", "1", "-i", str(default_jpg)]
        else:
            # Last resort: generate black frame via lavfi
            input0 = ["-f", "lavfi", "-i",
                      f"color=c=black:size={width}x{height}:rate={fps}"]

    flame_input  = ["-stream_loop", "-1", "-i", str(flame_vid)]

    # ── filter_complex ────────────────────────────────────────────────────────
    portrait = clip_path and is_portrait(clip_path)

    if portrait:
        # Background: stretch + blur
        bg  = (f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
               f"crop={width}:{height},boxblur=20:20,format=yuva420p[bg]")
        # Flame: scale to frame size
        fl  = f"[2:v]scale={width}:{height},format=yuva420p[fl]"
        # Blend flame onto blurred bg (screen mode)
        bfl = f"[bg][fl]blend=all_mode=screen:all_opacity={flame_op:.2f}[bg_flame]"
        # Foreground: scale portrait clip centered
        fg  = f"[0:v]scale=-2:{height},format=yuva420p[fg]"
        # Overlay fg onto blurred+flame bg
        ov  = f"[bg_flame][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[base]"
        # Flash on bass
        fl2 = f"[base]eq=brightness='{flash_expr}'[flashed]"
        # Hue rotate on hihats
        hu  = f"[flashed]hue=h='{hue_expr}'[hued]"

        if zoom_expr:
            zo  = (f"[hued]zoompan=z='{zoom_expr}':"
                   f"d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                   f"s={width}x{height},format=yuv420p[out]")
            fc  = ";".join([bg, fl, bfl, fg, ov, fl2, hu, zo])
            map_out = "[out]"
        else:
            hu_final = f"[base]eq=brightness='{flash_expr}',hue=h='{hue_expr}',format=yuv420p[out]"
            fc  = ";".join([bg, fl, bfl, fg, ov, hu_final])
            map_out = "[out]"

    else:
        # Landscape or still image
        sc  = (f"[0:v]scale={width}:{height}:force_original_aspect_ratio=increase,"
               f"crop={width}:{height},format=yuva420p[sc]")
        fl  = f"[2:v]scale={width}:{height},format=yuva420p[fl]"
        bfl = f"[sc][fl]blend=all_mode=screen:all_opacity={flame_op:.2f}[sc_flame]"
        fl2 = f"[sc_flame]eq=brightness='{flash_expr}',format=yuv420p[flashed]"
        hu  = f"[flashed]hue=h='{hue_expr}'[hued]"

        if zoom_expr:
            zo  = (f"[hued]zoompan=z='{zoom_expr}':"
                   f"d=1:x='iw/2-(iw/zoom/2)':y='ih/2-(ih/zoom/2)':"
                   f"s={width}x{height},format=yuv420p[out]")
            fc  = ";".join([sc, fl, bfl, fl2, hu, zo])
            map_out = "[out]"
        else:
            hu_final = f"[sc_flame]eq=brightness='{flash_expr}',hue=h='{hue_expr}',format=yuv420p[out]"
            fc  = ";".join([sc, fl, bfl, hu_final])
            map_out = "[out]"

    cmd = [
        "ffmpeg", "-y",
        *input0,
        "-i", str(audio_path),
        *flame_input,
        "-filter_complex", fc,
        "-map", map_out,
        "-map", "1:a:0",
        "-r", str(fps),
        "-c:v", "libx264", "-preset", "veryfast", "-crf", "21",
        "-threads", "0",
        "-c:a", "aac", "-b:a", "192k",
        "-shortest",
        str(out_mp4),
    ]

    result = subprocess.run(
        cmd,
        check=False,
        stdout=subprocess.DEVNULL,
        stderr=subprocess.PIPE,
        timeout=600,
        text=True,
    )

    if result.returncode != 0:
        # Extract last meaningful error line from stderr
        lines = [l.strip() for l in (result.stderr or "").splitlines() if l.strip()]
        err_summary = lines[-1] if lines else "unknown ffmpeg error"
        raise RuntimeError(err_summary)


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Beat-synced LIT video renderer.")
    parser.add_argument(
        "--only", type=str, default="",
        help="Comma-separated stems (e.g. army,hood_legend). Default: all beats."
    )
    parser.add_argument(
        "--intensity", type=str, default="medium",
        choices=["subtle", "medium", "fire"],
        help="Effect intensity (default: medium)"
    )
    parser.add_argument(
        "--force", action="store_true",
        help="Overwrite existing _lit renders"
    )
    args = parser.parse_args()

    params = INTENSITY_PARAMS[args.intensity]
    p(f"\n{'─'*60}")
    p(f"  render_lit.py  |  intensity: {args.intensity}")
    p(f"{'─'*60}\n")

    # ── Load config ───────────────────────────────────────────────────────────
    cfg        = load_config()
    render_cfg = cfg.get("render", {})
    width  = int(render_cfg.get("width",  1920))
    height = int(render_cfg.get("height", 1080))
    fps    = int(render_cfg.get("fps",    30))

    OUT_DIR.mkdir(exist_ok=True)

    # ── Build stem list ───────────────────────────────────────────────────────
    if args.only.strip():
        stems = [s.strip() for s in args.only.split(",") if s.strip()]
    else:
        stems = []
        for audio_file in sorted(BEATS_DIR.iterdir()):
            if audio_file.suffix.lower() in (".mp3", ".wav"):
                stems.append(safe_stem(audio_file))

    if not stems:
        p("No beats found. Drop MP3/WAV files into beats/ and try again.")
        sys.exit(0)

    # Validate inputs before starting any render
    valid_stems = []
    for stem in stems:
        found = False
        for ext in (".mp3", ".wav"):
            candidate = BEATS_DIR / f"{stem}{ext}"
            if candidate.exists():
                valid_stems.append((stem, candidate))
                found = True
                break
        if not found:
            p(f"[FAIL] {stem}: beats/{stem}.mp3 not found — skipping")

    if not valid_stems:
        p("Nothing to render.")
        sys.exit(0)

    # ── Pre-generate shared assets ────────────────────────────────────────────
    tmp_dir = Path(tempfile.gettempdir()) / "render_lit_assets"
    tmp_dir.mkdir(exist_ok=True)

    flame_vid = tmp_dir / "flame.mp4"

    p("[ASSETS] Generating overlays and flame...")

    if not flame_vid.exists():
        p("  Generating flame video...")
        generate_flame_video(flame_vid, width, height, fps, FLAME_DURATION)
    else:
        p("  Flame video cached")

    # Verify flame video exists (fallback may have failed)
    if not flame_vid.exists():
        p("[WARN] Flame video missing — renders will proceed without flame overlay")

    # ── Per-beat render loop ──────────────────────────────────────────────────
    done_count = 0
    fail_count = 0
    skip_count = 0
    total = len(valid_stems)

    for stem, audio_path in valid_stems:
        out_mp4 = OUT_DIR / f"{stem}_lit.mp4"

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
            beat_data = analyze_beats_detailed(audio_path, stem)
            duration  = beat_data.get("duration", get_audio_duration(audio_path))

            # 2. Use solid color flame fallback if flame_vid missing
            active_flame = flame_vid
            if not active_flame.exists():
                active_flame = tmp_dir / "flame_fallback.mp4"
                if not active_flame.exists():
                    subprocess.run([
                        "ffmpeg", "-y", "-f", "lavfi",
                        "-i", f"color=c=0x0044FF@0.5:size=480x270:rate={fps}",
                        "-t", str(FLAME_DURATION),
                        "-c:v", "libx264", "-preset", "ultrafast",
                        "-pix_fmt", "yuva420p", str(active_flame)
                    ], check=False, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)

            # 3. Resolve clip (check artist subfolder via seo_artist from metadata)
            _seo_artist = None
            _meta_path = META_DIR / f"{stem}.json"
            if _meta_path.exists():
                try:
                    _seo_artist = json.loads(_meta_path.read_text()).get("seo_artist")
                except Exception:
                    pass
            clip = resolve_clip(stem, seo_artist=_seo_artist)

            # 4. Render
            p(f"  Rendering LIT video{' (portrait)' if clip and is_portrait(clip) else ''}...")
            render_lit_video(
                audio_path  = audio_path,
                clip_path   = clip,
                out_mp4     = out_mp4,
                flame_vid   = active_flame,
                beat_data   = beat_data,
                params      = params,
                width       = width,
                height      = height,
                fps         = fps,
            )

            if out_mp4.exists():
                size_mb = out_mp4.stat().st_size / 1_048_576
                p(f"[DONE] {stem}  ({size_mb:.1f} MB)")
                done_count += 1
            else:
                raise RuntimeError("Output file not created")

        except subprocess.TimeoutExpired:
            p(f"[FAIL] {stem}: ffmpeg timed out (>10 min)")
            fail_count += 1
            if out_mp4.exists():
                try:
                    out_mp4.unlink()
                except Exception:
                    pass

        except Exception as exc:
            p(f"[FAIL] {stem}: {exc}")
            fail_count += 1
            if out_mp4.exists():
                try:
                    out_mp4.unlink()
                except Exception:
                    pass

    p(f"\n{'─'*60}")
    p(f"[COMPLETE] {done_count}/{total} rendered  |  "
      f"{skip_count} skipped  |  {fail_count} failed")
    p(f"{'─'*60}")
    sys.stdout.flush()


if __name__ == "__main__":
    main()
