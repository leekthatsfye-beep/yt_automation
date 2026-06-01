"""
social_upload.py

Handles social media uploads (TikTok + Instagram) for the YT automation pipeline.
Converts landscape (1920x1080) videos to portrait (1080x1920) using blur+overlay,
then uploads via official platform APIs.

Usage:
    from social_upload import convert_to_portrait, tiktok_upload, ig_upload
"""
from __future__ import annotations

import json
import logging
import os
import shutil
import subprocess
import time
from datetime import datetime, timezone
from pathlib import Path

import requests

log = logging.getLogger(__name__)

ROOT        = Path(__file__).resolve().parent
OUT_DIR     = ROOT / "output"
META_DIR    = ROOT / "metadata"
BRAND_DIR   = ROOT / "brand"
IMAGES_DIR  = ROOT / "images"
STORE_LOG   = ROOT / "store_uploads_log.json"
LANES_CFG   = ROOT / "lanes_config.json"
UPLOADS_LOG = ROOT / "uploads_log.json"

# Artist folder names (must match images/ subdirectories exactly)
_ARTIST_DIRS: dict[str, str] = {
    "biggkutt8":    "BiggKutt8",
    "ola runt":     "Ola Runt",
    "sexyy red":    "Sexyy Red",
    "sexyyred":     "Sexyy Red",
    "glokk40spazz": "Glokk40Spazz",
    "tezzus":       "Tezzus",
    "diamond":      "Diamond",
    "shawtyrokk":   "ShawtyRokk",
}


def _resolve_artist_clip(stem: str) -> Path | None:
    """
    Return the best video clip for this stem's artist.
    Priority:
      1. images/{stem}.mp4          — per-beat custom clip
      2. images/{ArtistFolder}/*.mp4 — deterministic pick from artist folder
         (uses stem hash so the same stem always gets the same clip)
      3. None — no clip available
    Never falls back to a generic default — always uses the actual artist.
    """
    import hashlib

    per_beat = IMAGES_DIR / f"{stem}.mp4"
    if per_beat.exists():
        return per_beat

    # Load artist from metadata
    mf = META_DIR / f"{stem}.json"
    if not mf.exists():
        return None
    meta = json.loads(mf.read_text())
    artist = meta.get("seo_artist", meta.get("artist", "")).lower().strip()

    folder_name = _ARTIST_DIRS.get(artist) or _ARTIST_DIRS.get(artist.replace(" ", ""))
    if not folder_name:
        return None

    artist_dir = IMAGES_DIR / folder_name
    if not artist_dir.is_dir():
        return None

    clips = sorted(artist_dir.glob("*.mp4"))
    if not clips:
        return None

    # Deterministic selection — same stem always gets same clip
    idx = int(hashlib.md5(stem.encode()).hexdigest(), 16) % len(clips)
    return clips[idx]


def _build_purchase_desc(stem: str) -> str:
    """Build Format A description (Purchase/Download + store link)."""
    store_data = {}
    try:
        if STORE_LOG.exists():
            store_data = json.loads(STORE_LOG.read_text())
    except Exception:
        pass
    lanes_cfg = {}
    try:
        if LANES_CFG.exists():
            lanes_cfg = json.loads(LANES_CFG.read_text())
    except Exception:
        pass
    store_profile = lanes_cfg.get("store_profile_url", "")
    producer = lanes_cfg.get("producer", "leekthatsfy3")

    entry = store_data.get(stem, {})
    airbit_entry = entry.get("airbit", entry) if isinstance(entry, dict) else {}
    beat_url = airbit_entry.get("url", "")

    if beat_url and beat_url != store_profile:
        purchase_link = beat_url
        if store_profile:
            purchase_link += f"\n\nBrowse all beats:\n{store_profile}"
    elif store_profile:
        purchase_link = store_profile
    else:
        purchase_link = "[Link in bio]"

    return f"Purchase / Download\n{purchase_link}\n\nprod. {producer}"
SPIN_LOGO = BRAND_DIR / "fy3_spin.mov"

SOCIAL_LOG_FILE = ROOT / "social_uploads_log.json"

# ── Social uploads log ────────────────────────────────────────────────────────

def load_social_log() -> dict:
    try:
        if SOCIAL_LOG_FILE.exists() and SOCIAL_LOG_FILE.stat().st_size > 0:
            return json.loads(SOCIAL_LOG_FILE.read_text())
    except Exception:
        pass
    return {}


def save_social_log(data: dict):
    SOCIAL_LOG_FILE.write_text(json.dumps(data, indent=2, default=str))


def log_social_upload(stem: str, platform: str, result: dict):
    data = load_social_log()
    if stem not in data:
        data[stem] = {}
    result["uploadedAt"] = datetime.now(timezone.utc).isoformat()
    data[stem][platform] = result
    save_social_log(data)


def _get_full_video_url(stem: str) -> str:
    """Return the full YouTube video URL for a stem, or empty string if not uploaded yet."""
    try:
        if UPLOADS_LOG.exists():
            data = json.loads(UPLOADS_LOG.read_text())
            return data.get(stem, {}).get("url", "")
    except Exception:
        pass
    return ""


def _build_short_desc(stem: str) -> str:
    """
    Build a clean YouTube Shorts description with:
      - Beat title
      - Purchase / lease link (beat-specific Airbit URL)
      - Full YouTube video link (or placeholder if not uploaded yet)
      - Producer tag
      - Hashtags
    """
    # Load metadata for title
    meta = {}
    try:
        meta_path = META_DIR / f"{stem}.json"
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
    except Exception:
        pass

    title = meta.get("title", stem.replace("_", " ").title())

    # Load store/lanes config
    store_data = {}
    lanes_cfg = {}
    try:
        if STORE_LOG.exists():
            store_data = json.loads(STORE_LOG.read_text())
    except Exception:
        pass
    try:
        if LANES_CFG.exists():
            lanes_cfg = json.loads(LANES_CFG.read_text())
    except Exception:
        pass

    store_profile = lanes_cfg.get("store_profile_url", "")
    producer      = lanes_cfg.get("producer", "leekthatsfy3")

    entry       = store_data.get(stem, {})
    airbit_entry = entry.get("airbit", entry) if isinstance(entry, dict) else {}
    beat_url    = airbit_entry.get("url", "")

    purchase_link = beat_url if beat_url else store_profile or "[Link in bio]"

    # Full long-form video URL
    full_video_url = _get_full_video_url(stem)
    if full_video_url:
        full_video_section = f"🎵 Full beat:\n{full_video_url}"
    else:
        full_video_section = "🎵 Full beat dropping soon — follow so you don't miss it"

    # Hashtags from metadata tags (top 5 most relevant)
    raw_tags = meta.get("tags", [])[:5]
    hashtags = " ".join(
        "#" + t.replace(" ", "").replace("-", "") for t in raw_tags if t
    )
    if not hashtags:
        hashtags = "#TypeBeat #Shorts"
    else:
        hashtags = f"#Shorts #TypeBeat {hashtags}"

    desc = (
        f"{title}\n"
        f"\n"
        f"🛒 Purchase / Lease this beat:\n"
        f"{purchase_link}\n"
        f"\n"
        f"{full_video_section}\n"
        f"\n"
        f"prod. {producer}\n"
        f"\n"
        f"{hashtags}"
    )
    return desc.strip()[:5000]


def patch_short_description(stem: str, youtube=None) -> bool:
    """
    After a long-form video is uploaded, call this to update the YouTube Short's
    description with the real full video link.

    Called automatically by upload.py after each successful upload.
    Returns True if updated, False if no short exists or update failed.
    """
    social_data = load_social_log()
    short_entry = social_data.get(stem, {}).get("youtube_shorts", {})
    video_id = short_entry.get("videoId", "")

    if not video_id:
        return False  # No short uploaded for this stem

    full_url = _get_full_video_url(stem)
    if not full_url:
        return False  # Long-form not in log yet

    try:
        if youtube is None:
            from upload import get_youtube_service
            youtube = get_youtube_service()

        # Fetch current snippet to preserve all fields
        resp = youtube.videos().list(part="snippet", id=video_id).execute()
        items = resp.get("items", [])
        if not items:
            log.warning("[PATCH] Short %s not found on YouTube (deleted?)", video_id)
            return False

        snippet = items[0]["snippet"]
        new_desc = _build_short_desc(stem)

        if full_url in snippet.get("description", ""):
            log.info("[PATCH] Short %s already has full video link — skipping", stem)
            return False

        snippet["description"] = new_desc
        youtube.videos().update(
            part="snippet",
            body={"id": video_id, "snippet": snippet},
        ).execute()
        log.info("[PATCH] Updated short description for %s with full video link", stem)
        return True

    except Exception as e:
        log.warning("[PATCH] Failed to update short description for %s: %s", stem, e)
        return False


# ── Video conversion: landscape → portrait (9:16) ────────────────────────────

# Platform duration limits (seconds).  IG is strictest → use as universal trim.
PLATFORM_MAX_DURATION = {
    "instagram": 90,
    "tiktok": 600,
    "youtube_shorts": 180,
}
# Trim point — 1s buffer under IG limit for codec padding.
SOCIAL_MAX_DURATION = 60

# Always compress social videos for fast upload.  IG's resumable upload
# silently rejects files > ~20 MB (returns ProcessingFailedError 400).
# Social platforms re-encode anyway so visual quality loss is negligible.
SOCIAL_TARGET_SIZE_MB = 50  # compress when portrait would exceed this size (MB)
# Social platforms re-encode anyway, so quality loss from compression is negligible.
# IG video_url approach (via main tunnel) has no size limit.
# Resumable upload fallback has ~10 MB undocumented limit — video_url is primary.


def find_808_drop(audio_path: Path, search_limit: float = 30.0) -> float:
    """
    Detect the first 808/bass drop in the audio and return its timestamp (seconds).

    Strategy: STFT-based bass energy (30-150 Hz) to find where sub-bass first
    sustains above threshold for a full bar — indicating the drop vs a quiet intro.

    - If bass is strong from bar 1 (no quiet intro), returns 0.0
    - If there's a quiet intro, returns the timestamp of the first sustained drop
    - Falls back to 0.0 if detection fails

    Only looks at first `search_limit` seconds to avoid mid-song breakdowns.
    """
    try:
        import numpy as np
        import librosa

        hop = 512
        y, sr = librosa.load(str(audio_path), sr=None, mono=True,
                             offset=0.0, duration=search_limit)

        # STFT-based bass energy (30-150 Hz band)
        D = np.abs(librosa.stft(y, n_fft=2048, hop_length=hop))
        freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
        bass_mask = (freqs >= 30) & (freqs <= 150)
        bass_energy = D[bass_mask, :].mean(axis=0)
        times = librosa.frames_to_time(np.arange(len(bass_energy)), sr=sr, hop_length=hop)

        if bass_energy.max() == 0:
            log.info("[DROP] No bass energy found, starting at t=0")
            return 0.0

        # Normalize energy to 0-1
        bass_norm = bass_energy / bass_energy.max()

        # Smooth over ~0.25s window to reduce noise
        smooth_frames = max(1, int(0.25 * sr / hop))
        kernel = np.ones(smooth_frames) / smooth_frames
        bass_smooth = np.convolve(bass_norm, kernel, mode='same')

        # Threshold: 25% of peak = "bass is present"
        THRESHOLD = 0.25
        # Sustain requirement: bass above threshold for at least 1.5s continuously
        SUSTAIN_FRAMES = int(1.5 * sr / hop)

        # Check if bass is already sustained from the start
        # If first 2s average is above threshold → no intro, start at 0
        first_2s_frames = int(2.0 * sr / hop)
        if bass_smooth[:first_2s_frames].mean() >= THRESHOLD:
            log.info("[DROP] Bass present from start — short starts at t=0")
            return 0.0

        # Find first frame where bass sustains above threshold for SUSTAIN_FRAMES
        above = bass_smooth >= THRESHOLD
        count = 0
        for i, val in enumerate(above):
            if val:
                count += 1
                if count >= SUSTAIN_FRAMES:
                    drop_frame = i - count + 1
                    drop_t = max(0.0, float(times[drop_frame]))
                    # Round to nearest beat boundary (0.1s granularity)
                    drop_t = round(drop_t, 1)
                    log.info("[DROP] First sustained 808 drop at %.2fs", drop_t)
                    return drop_t
            else:
                count = 0

        log.info("[DROP] No sustained bass cluster found, starting at t=0")
        return 0.0

    except Exception as exc:
        log.warning("[DROP] Detection failed (%s), starting at t=0", exc)
        return 0.0


def _get_duration(path: Path) -> float:
    """Get media duration in seconds via ffprobe."""
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


HOOK_FONT_PATH   = "/System/Library/Fonts/Supplemental/Arial Bold.ttf"
HOOK_FONT_SIZE   = 62    # px — readable on phone at arm's length
HOOK_DURATION    = 3.5   # seconds the opening hook text is visible
END_PROMPT_START = 3     # seconds before end to show the comment prompt
HOOK_W, HOOK_H   = 1080, 1920  # must match portrait dimensions


# Hook openers — rotates daily so returning viewers never see the same one twice
_HOOK_TEMPLATES = [
    "Bro who's going crazy on this? ↓",
    "This beat needs a collab. DROP a name ↓",
    "Tell me the rapper that turns this into a hit ↓",
    "Be honest... who bodied a beat like this? ↓",
    "POV: your favorite rapper just dropped this ↓",
    "Which rapper do you immediately hear on this? ↓",
    "This one got LEVELS. Who you putting on it? ↓",
    "Nobody makes beats like this anymore ↓",
    "The right rapper on this = instant hit. Who is it? ↓",
    "I made this for one specific rapper. Guess who ↓",
    "Whoever raps on this is going to the TOP ↓",
    "This beat has been waiting for the right artist ↓",
    "Stop scrolling. Who do you hear on this? ↓",
    "This is going on somebody's album. Who? ↓",
    "Name ONE rapper built for a beat like this ↓",
    "If this don't make you think of a rapper idk what will ↓",
    "Which artist would go stupid on this? ↓",
    "This beat is TOO cold to be sitting like this ↓",
    "A top artist needs to hear this. Tag em ↓",
    "Streets been needing a beat like this. Who's on it? ↓",
    "I already know exactly who fits this. Do you? ↓",
    "This goes HARD. Who's the first rapper in your head? ↓",
    "Somebody's bout to blow up off a beat like this ↓",
    "Drop the name of whoever lives in your head rent free ↓",
    "Tezzus x Diamond dropped different with this one ↓",
    "If you know Tezzus you already know this goes hard ↓",
    "Diamond on the beat = automatic vibe. Who's rapping? ↓",
    "Tezzus x Diamond cooked this. Who finishes it? ↓",
    "ShawtyRøkk type beat and it's already a problem ↓",
    "If you know ShawtyRøkk you already know this is cold ↓",
    "Krossed Ø Gang energy. Who's getting on this? ↓",
    "ShawtyRøkk cooked this vibe. Who finishes it? ↓",
]

# End-of-video comment prompts — also rotates daily
_END_PROMPTS = [
    "You heard it first. Who's getting on this? ↓",
    "Still waiting for the right rapper. Tag em ↓",
    "This beat deserves bars. Who you got? ↓",
    "Drop a name and I might send the lease ↓",
    "Comment the artist and I'll tag them ↓",
    "Who goes crazy over beats like this? ↓",
    "Real ones know who needs this beat ↓",
    "If this ain't a hit I don't know what is. Who's on it? ↓",
    "The label should be calling RIGHT NOW. Who? ↓",
    "One rapper. This beat. Instant classic. Name em ↓",
    "I'm sending this to whoever you say ↓",
    "Drop the artist you'd sign to this ↓",
    "Lease or exclusive? Comment who you want on this ↓",
    "Somebody in the comments always knows. Who is it? ↓",
    "This beat won't be free forever. Who needs it? ↓",
    "Comment and I'll personally send it to your pick ↓",
    "The right collab on this = a million streams easy ↓",
    "Who's sleeping on a beat like this? Wake em up ↓",
    "Tag the rapper. I'll do the rest ↓",
    "Drop the name. Let's make it happen ↓",
    "Which rapper would go 0 to 100 on this? ↓",
    "They need to hear this TODAY. Who? ↓",
    "Somebody's next single sounds exactly like this ↓",
    "The comments already know. Prove it ↓",
]


def _pick_hook(stem: str, templates: list) -> str:
    """
    Pick a hook that changes daily — same stem gets a different hook each day.
    Uses stem hash + day-of-year so no two consecutive days repeat.
    Guarantees all hooks cycle through before any repeats (round-robin per stem).
    """
    from datetime import date
    day_of_year = date.today().timetuple().tm_yday
    stem_hash   = sum(ord(c) for c in stem)
    # Offset by day so each new day shifts the entire rotation
    idx = (stem_hash + day_of_year) % len(templates)
    return templates[idx]


def _render_hook_overlay(stem: str, effective_duration: float, out_dir: Path) -> tuple[Path, Path]:
    """
    Render two PNG overlays using Pillow (fallback for ffmpeg builds without libfreetype):
      • hook_open_{stem}.png  — opening hook text (white bold, black pill background)
      • hook_end_{stem}.png   — end comment prompt (same style)
    Returns (open_png_path, end_png_path).
    """
    from PIL import Image, ImageDraw, ImageFont

    W, H = HOOK_W, HOOK_H
    font_size = HOOK_FONT_SIZE
    try:
        font = ImageFont.truetype(HOOK_FONT_PATH, font_size)
    except OSError:
        font = ImageFont.load_default()

    # Use NotoColorEmoji for emoji rendering if available, fall back to Arial Bold
    emoji_font_path = "/System/Library/Fonts/Apple Color Emoji.ttc"
    try:
        emoji_font = ImageFont.truetype(emoji_font_path, font_size)
    except OSError:
        emoji_font = font

    def _wrap_text(text: str, max_width: int) -> list[str]:
        """Split text into lines that fit within max_width pixels."""
        words = text.split()
        lines: list[str] = []
        current = ""
        dummy_img = Image.new("RGBA", (1, 1))
        dummy_draw = ImageDraw.Draw(dummy_img)
        for word in words:
            test = (current + " " + word).strip()
            bbox = dummy_draw.textbbox((0, 0), test, font=font)
            if bbox[2] - bbox[0] <= max_width:
                current = test
            else:
                if current:
                    lines.append(current)
                current = word
        if current:
            lines.append(current)
        return lines

    MAX_TEXT_W = W - 80  # 40px margin each side

    def _make_overlay(text: str, y_frac: float) -> Image.Image:
        img = Image.new("RGBA", (W, H), (0, 0, 0, 0))  # fully transparent
        draw = ImageDraw.Draw(img)

        # Strip emoji from main text, draw them separately using emoji font
        # Simple approach: render full text with main font, emoji will show as boxes
        # but we remove them and add the arrow as ASCII
        clean_text = text.replace("👇", "↓").strip()  # replace emoji with renderable arrow

        lines = _wrap_text(clean_text, MAX_TEXT_W)
        line_height = font_size + 10
        total_h = len(lines) * line_height
        y_center = int(H * y_frac) - total_h // 2

        # Measure widest line for background
        max_tw = max(
            (draw.textbbox((0, 0), ln, font=font)[2] -
             draw.textbbox((0, 0), ln, font=font)[0])
            for ln in lines
        )

        pad_x, pad_y = 28, 16
        bg_x0 = (W - max_tw) // 2 - pad_x
        bg_y0 = y_center - pad_y
        bg_x1 = (W + max_tw) // 2 + pad_x
        bg_y1 = y_center + total_h + pad_y
        draw.rounded_rectangle([bg_x0, bg_y0, bg_x1, bg_y1], radius=18,
                                fill=(0, 0, 0, 165))

        for i, line in enumerate(lines):
            bbox = draw.textbbox((0, 0), line, font=font)
            tw = bbox[2] - bbox[0]
            x = (W - tw) // 2
            y = y_center + i * line_height
            # Shadow
            draw.text((x + 2, y + 2), line, font=font, fill=(0, 0, 0, 200))
            # Main white text
            draw.text((x, y), line, font=font, fill=(255, 255, 255, 255))
        return img

    open_text = _pick_hook(stem, _HOOK_TEMPLATES)
    end_text  = _pick_hook(stem, _END_PROMPTS)

    open_img = _make_overlay(open_text, y_frac=0.20)   # top-fifth of screen
    end_img  = _make_overlay(end_text,  y_frac=0.80)   # bottom-fifth of screen

    open_path = out_dir / f"_hook_open_{stem}.png"
    end_path  = out_dir / f"_hook_end_{stem}.png"
    open_img.save(str(open_path))
    end_img.save(str(end_path))
    return open_path, end_path


def convert_to_portrait(
    stem: str,
    force: bool = False,
    progress_cb: "Callable[[float], None] | None" = None,
) -> Path:
    """
    Build a 1080x1920 portrait short directly from the artist's video clip
    + the original beat audio. Never uses the full landscape render as source —
    that avoids the still-image problem when zoompan was used.

    Video source priority:
      1. images/{stem}.mp4         — per-beat custom clip
      2. images/{ArtistFolder}/*.mp4 — artist clip (deterministic by stem hash)
      3. output/{stem}.mp4         — full render fallback (last resort)

    Adds two retention hooks burned into the video.
    Returns path to the 9:16 file: output/{stem}_9x16.mp4
    Idempotent: skips if output exists unless force=True.
    """
    shorts_dir = OUT_DIR / "renders" / "shorts"
    shorts_dir.mkdir(parents=True, exist_ok=True)
    dst = shorts_dir / f"{stem}_9x16.mp4"

    # Resolve video clip source — prefer artist clip over full render
    clip_src = _resolve_artist_clip(stem)
    if clip_src is None:
        # Fallback: use the renders folder or output root
        clip_src = OUT_DIR / "renders" / f"{stem}.mp4"
        if not clip_src.exists():
            clip_src = OUT_DIR / f"{stem}.mp4"
    if not clip_src.exists():
        raise FileNotFoundError(f"No video source found for: {stem}")

    # Always use the original beat audio for cleanest sound
    beat_audio: Path | None = None
    for ext in (".mp3", ".wav"):
        # Check flat root first, then search subfolders
        candidate = ROOT / "beats" / f"{stem}{ext}"
        if candidate.exists():
            beat_audio = candidate
            break
        matches = list((ROOT / "beats").rglob(f"{stem}{ext}"))
        if matches:
            beat_audio = matches[0]
            break

    log.info("[SHORT] %s — video: %s | audio: %s", stem, clip_src.name,
             beat_audio.name if beat_audio else "from clip")

    # For output duration calculation use beat audio length if available
    src = OUT_DIR / f"{stem}.mp4"  # kept for duration reference only

    if dst.exists() and not force:
        log.info("[SKIP] 9x16 already exists: %s", dst.name)
        if progress_cb:
            progress_cb(100.0)
        return dst

    W, H = 1080, 1920
    # Fast blur: scale down to 1/8 then back up (10x faster than boxblur)
    BW, BH = W // 8, H // 8  # 135 × 240
    has_spin = SPIN_LOGO.exists()

    # ── 808 drop detection — use beat audio for cleanest signal ────────
    if beat_audio:
        drop_ss = find_808_drop(beat_audio)
    elif src.exists():
        drop_ss = find_808_drop(src)
    else:
        drop_ss = 0.0
    log.info("[DROP] Short will start at %.2fs (808 drop)", drop_ss)

    # ── Duration from beat audio (or clip src as fallback) ─────────────
    audio_ref = beat_audio or src
    src_duration = _get_duration(audio_ref) if audio_ref.exists() else _get_duration(clip_src)
    src_size_mb  = clip_src.stat().st_size / (1024 * 1024)

    # Available content after the drop
    available_duration = src_duration - drop_ss

    # Trim if over the social max (89s — safe for all platforms including IG)
    needs_trim = available_duration > SOCIAL_MAX_DURATION
    trim_to = SOCIAL_MAX_DURATION if needs_trim else 0
    effective_duration = trim_to if needs_trim else available_duration

    # ── Replay tension: cut 0.2s before the bar resolves ───────────────
    EARLY_CUT = 0.2
    if effective_duration > 5.0:
        effective_duration = round(effective_duration - EARLY_CUT, 3)
        if needs_trim:
            trim_to = effective_duration

    # Compress if source is large
    needs_compress = src_size_mb > SOCIAL_TARGET_SIZE_MB

    log.info(
        "Portrait prep: %.1fs src, drop@%.2fs, effective=%.1fs (%.1f MB), trim=%s, compress=%s",
        src_duration, drop_ss, effective_duration, src_size_mb,
        f"{trim_to}s" if needs_trim else "no",
        "yes" if needs_compress else "no",
    )

    # Audio fade-out: always apply to the last 3s for clean loop/replay tension
    fade_dur = 3
    fade_start = max(0.0, effective_duration - fade_dur)

    # Pick encoding quality
    if needs_compress:
        v_preset, v_crf = "medium", "24"
        v_extra = ["-maxrate", "4M", "-bufsize", "8M"]
        a_bitrate = "128k"
    else:
        v_preset, v_crf = "fast", "20"
        v_extra = []
        a_bitrate = "192k"

    # Render hook PNG overlays via Pillow (no libfreetype needed)
    hook_open_png, hook_end_png = _render_hook_overlay(stem, effective_duration, OUT_DIR)
    end_start = max(0.0, effective_duration - END_PROMPT_START)

    def _hook_overlay_filters(base_idx: int, pre_label: str) -> tuple[str, list]:
        oi, ei = base_idx, base_idx + 1
        f1 = (f"[{pre_label}][{oi}:v]overlay=0:0:"
              f"enable='between(t,0,{HOOK_DURATION})'[v1]")
        f2 = (f"[v1][{ei}:v]overlay=0:0:"
              f"enable='between(t,{end_start:.2f},{effective_duration:.2f})',"
              f"format=yuv420p[out]")
        return f"{f1};{f2}", ["-i", str(hook_open_png), "-i", str(hook_end_png)]

    # -ss seek on video clip; audio always starts from drop_ss offset
    ss_args = ["-ss", f"{drop_ss:.3f}"] if drop_ss > 0 else []
    # For separate audio input: seek offset applied via -ss before audio -i
    audio_ss_args = ["-ss", f"{drop_ss:.3f}"] if (drop_ss > 0 and beat_audio) else []

    # Input index accounting:
    # [0] = video clip_src  (with -ss seek OR -stream_loop -1)
    # [1] = beat_audio      (separate audio, only if beat_audio exists)
    # [1 or 2] = SPIN_LOGO  (if has_spin)
    # hook PNGs after that

    if beat_audio:
        # Separate video + audio inputs — cleanest approach
        audio_input_args = [*audio_ss_args, "-i", str(beat_audio)]
        audio_idx = 1
        spin_idx  = 2
    else:
        # Audio comes from the clip itself
        audio_input_args = []
        audio_idx = 0
        spin_idx  = 1

    af_filter    = f"afade=t=out:st={fade_start:.3f}:d={fade_dur}"
    audio_label  = f"{audio_idx}:a"
    audio_chain  = f"[{audio_label}]{af_filter}[aout]"
    audio_map    = "[aout]"

    bg_filter = (
        f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
        f"crop={W}:{H},scale={BW}:{BH},scale={W}:{H},"
        f"format=yuv420p[bg]"
    )
    fg_filter = f"[0:v]scale={W}:-2,format=yuv420p[fg]"
    ov_filter = "[bg][fg]overlay=(W-w)/2:(H-h)/2[composed]"

    if has_spin:
        spin_filter = f"[composed][{spin_idx}:v]overlay=(W-w)/2:H-h-20,format=yuv420p[spun]"
        hook_chain, hook_inputs = _hook_overlay_filters(base_idx=spin_idx + 1, pre_label="spun")
        vf = f"{bg_filter};{fg_filter};{ov_filter};{spin_filter};{hook_chain};{audio_chain}"
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", *ss_args, "-i", str(clip_src),
            *audio_input_args,
            "-stream_loop", "-1", "-i", str(SPIN_LOGO),
            *hook_inputs,
            "-filter_complex", vf,
            "-map", "[out]", "-map", audio_map,
            "-r", "30",
            "-c:v", "libx264", "-preset", v_preset, "-crf", v_crf,
            *v_extra, "-threads", "0",
            "-c:a", "aac", "-b:a", a_bitrate,
            "-movflags", "+faststart",
            "-shortest",
        ]
    else:
        hook_chain, hook_inputs = _hook_overlay_filters(base_idx=spin_idx, pre_label="composed")
        vf = f"{bg_filter};{fg_filter};{ov_filter};{hook_chain};{audio_chain}"
        cmd = [
            "ffmpeg", "-y",
            "-stream_loop", "-1", *ss_args, "-i", str(clip_src),
            *audio_input_args,
            *hook_inputs,
            "-filter_complex", vf,
            "-map", "[out]", "-map", audio_map,
            "-r", "30",
            "-c:v", "libx264", "-preset", v_preset, "-crf", v_crf,
            *v_extra, "-threads", "0",
            "-c:a", "aac", "-b:a", a_bitrate,
            "-movflags", "+faststart",
            "-shortest",
        ]

    cmd.extend(["-t", f"{effective_duration:.3f}"])
    cmd.extend(["-progress", "pipe:1", str(dst)])

    log.info("Converting to portrait: %s → %s", clip_src.name, dst.name)
    duration = _get_duration(audio_ref) if audio_ref.exists() else _get_duration(clip_src)

    # Write stderr to a temp file to avoid deadlock:
    # ffmpeg writes heavily to stderr; if it fills the pipe buffer (~64 KB)
    # while we only read stdout, both processes block → deadlock.
    import tempfile as _tf
    stderr_file = _tf.NamedTemporaryFile(
        mode="w+", suffix=".log", prefix="ffmpeg_9x16_", delete=False
    )

    proc = subprocess.Popen(
        cmd, stdout=subprocess.PIPE, stderr=stderr_file, text=True,
        bufsize=1,  # line-buffered for real-time progress
    )

    # Instant visual feedback before ffmpeg starts outputting
    if progress_cb:
        progress_cb(1.0)

    try:
        # Read progress lines from stdout in real time
        while proc.poll() is None:
            line = proc.stdout.readline()
            if not line:
                continue
            if line.startswith("out_time_us=") and duration > 0 and progress_cb:
                try:
                    us = int(line.split("=", 1)[1].strip())
                    pct = min(99.0, (us / 1_000_000) / duration * 100)
                    progress_cb(pct)
                except (ValueError, ZeroDivisionError):
                    pass

        # Process finished — drain any remaining stdout
        proc.wait(timeout=10)

        if proc.returncode != 0:
            # Read stderr from the temp file for diagnostics
            stderr_file.seek(0)
            stderr_text = stderr_file.read()
            stderr_file.close()
            os.unlink(stderr_file.name)
            if dst.exists():
                dst.unlink()
            raise RuntimeError(
                f"ffmpeg 9x16 conversion failed (rc={proc.returncode}): "
                f"{stderr_text[-500:] if stderr_text else 'no stderr'}"
            )
        else:
            stderr_file.close()
            os.unlink(stderr_file.name)
    except subprocess.TimeoutExpired:
        proc.kill()
        proc.wait()
        stderr_file.close()
        os.unlink(stderr_file.name)
        if dst.exists():
            dst.unlink()
        raise RuntimeError("ffmpeg conversion timed out during cleanup")
    except Exception:
        proc.kill()
        proc.wait()
        stderr_file.close()
        try:
            os.unlink(stderr_file.name)
        except OSError:
            pass
        if dst.exists():
            dst.unlink()
        raise

    # Clean up temp hook PNG overlays
    for _p in (hook_open_png, hook_end_png):
        try:
            _p.unlink(missing_ok=True)
        except OSError:
            pass

    if progress_cb:
        progress_cb(100.0)

    log.info("Portrait conversion done: %s (%.1f MB)",
             dst.name, dst.stat().st_size / 1_048_576)
    return dst


# ── Caption builder ───────────────────────────────────────────────────────────

def build_social_caption(stem: str) -> str:
    """
    Build a social media caption from metadata.
    Clean format — no hashtags (better for IG Explore reach).
    """
    meta_path = META_DIR / f"{stem}.json"
    title = stem.replace("_", " ").title()

    try:
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            title = meta.get("title", title)
    except Exception:
        pass

    caption = f"{title} \U0001f525\U0001f3b5"  # fire + music note emojis

    return caption


# ── TikTok upload ─────────────────────────────────────────────────────────────

def _tt_get_token_with_retry() -> str:
    """Get TikTok access token, refreshing on failure. Returns token string."""
    from tiktok_auth import get_access_token, refresh_access_token, is_token_valid, load_token

    try:
        return get_access_token()
    except Exception:
        pass

    # Force refresh
    try:
        return refresh_access_token()
    except Exception as e:
        raise RuntimeError(
            f"TikTok auth failed: {e}. Run /tiktok to reconnect."
        ) from e


def _tt_init_upload(access_token: str, caption: str, file_size: int) -> dict:
    """Initialize TikTok upload. Returns init_data dict or raises with clear error."""
    import math

    init_url = "https://open.tiktokapis.com/v2/post/publish/video/init/"
    headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }

    # TikTok chunk rules: min 5MB, max 64MB per chunk; files < 5MB upload as-is
    # total_chunk_count = floor(video_size / chunk_size) — last chunk absorbs remainder
    MAX_CHUNK = 10 * 1024 * 1024   # 10 MB — conservative, well within 64MB limit
    if file_size <= 5 * 1024 * 1024:
        chunk_size = file_size
        total_chunks = 1
    else:
        chunk_size = MAX_CHUNK
        total_chunks = file_size // chunk_size  # floor — last chunk is bigger

    log.info("TikTok init: file_size=%d, chunk_size=%d, total_chunks=%d",
             file_size, chunk_size, total_chunks)

    init_body = {
        "post_info": {
            "title": caption[:150],  # TikTok title max ~150 chars
            "privacy_level": "SELF_ONLY",  # unaudited apps must use SELF_ONLY
            "disable_duet": False,
            "disable_comment": False,
            "disable_stitch": False,
        },
        "source_info": {
            "source": "FILE_UPLOAD",
            "video_size": file_size,
            "chunk_size": chunk_size,
            "total_chunk_count": total_chunks,
        },
    }

    resp = requests.post(init_url, headers=headers, json=init_body, timeout=30)

    # Parse response even on HTTP errors for better error messages
    try:
        data = resp.json()
    except Exception:
        data = {}

    if resp.status_code == 401:
        err_msg = data.get("error", {}).get("message", "access_token_invalid")
        raise RuntimeError(
            f"TikTok 401 Unauthorized: {err_msg}. "
            "Token may be expired or missing video.publish scope. "
            "Delete tiktok_token.json and run /tiktok to re-authorize."
        )

    if resp.status_code == 403:
        err_msg = data.get("error", {}).get("message", "forbidden")
        raise RuntimeError(
            f"TikTok 403 Forbidden: {err_msg}. "
            "Your app may not have Content Posting API access."
        )

    if resp.status_code == 429:
        raise RuntimeError(
            "TikTok 429 Rate Limited. Wait a few minutes and try again."
        )

    resp.raise_for_status()

    err_code = data.get("error", {}).get("code", "")
    if err_code and err_code != "ok":
        err = data.get("error", {})
        raise RuntimeError(
            f"TikTok init failed: {err.get('code')} - {err.get('message')}"
        )

    if "data" not in data or "upload_url" not in data.get("data", {}):
        raise RuntimeError(
            f"TikTok init returned unexpected data: {str(data)[:300]}"
        )

    return data


def tiktok_upload(stem: str, caption: str | None = None, progress: dict | None = None) -> dict:
    """
    Upload a video to TikTok via Content Posting API.
    Bulletproof: auto-refreshes token on 401, retries init once, clear error messages.

    progress (optional): mutable dict for live status updates, keys:
        phase   — "init" | "uploading" | "processing" | "done" | "failed"
        pct     — 0-100 int
        detail  — human-readable status string
        chunk   — current chunk index (0-based)
        chunks  — total chunks

    Returns dict with status and metadata.
    """
    if progress is None:
        progress = {}
    progress.update(phase="init", pct=0, detail="Initializing...", chunk=0, chunks=0)

    access_token = _tt_get_token_with_retry()

    # Ensure 9:16 version exists (auto-trims + auto-compresses in one pass)
    portrait = convert_to_portrait(stem)

    if caption is None:
        caption = build_social_caption(stem)

    file_size = portrait.stat().st_size
    log.info("TikTok upload [%s]: %s (%.1f MB)", stem, portrait.name, file_size / 1024 / 1024)

    # Step 1: Initialize upload (retry once with refreshed token on 401)
    try:
        init_data = _tt_init_upload(access_token, caption, file_size)
    except RuntimeError as e:
        if "401" in str(e) or "access_token" in str(e).lower():
            log.warning("TikTok init 401 for %s, refreshing token and retrying...", stem)
            from tiktok_auth import refresh_access_token
            try:
                access_token = refresh_access_token()
            except Exception as re:
                raise RuntimeError(
                    f"TikTok token refresh failed: {re}. "
                    "Delete tiktok_token.json and run /tiktok to re-authorize."
                ) from re
            init_data = _tt_init_upload(access_token, caption, file_size)
        else:
            raise

    upload_url = init_data["data"]["upload_url"]
    publish_id = init_data["data"]["publish_id"]
    log.info("TikTok upload [%s]: init OK, publish_id=%s", stem, publish_id)

    # Step 2: Upload video file in chunks
    MAX_CHUNK = 10 * 1024 * 1024   # must match init
    if file_size <= 5 * 1024 * 1024:
        chunk_size = file_size
    else:
        chunk_size = MAX_CHUNK
    total_chunks = max(1, file_size // chunk_size)  # floor — last chunk absorbs remainder

    progress.update(phase="uploading", pct=0, detail="Uploading chunks...",
                    chunk=0, chunks=total_chunks)

    with open(portrait, "rb") as f:
        for chunk_idx in range(total_chunks):
            offset = chunk_idx * chunk_size
            # Last chunk reads everything remaining (may be > chunk_size)
            if chunk_idx == total_chunks - 1:
                chunk_data = f.read()  # read all remaining bytes
            else:
                chunk_data = f.read(chunk_size)
            actual_len = len(chunk_data)
            end_byte = offset + actual_len - 1

            chunk_headers = {
                "Content-Range": f"bytes {offset}-{end_byte}/{file_size}",
                "Content-Type": "video/mp4",
            }

            try:
                upload_resp = requests.put(
                    upload_url, headers=chunk_headers, data=chunk_data, timeout=120
                )
                # 200/201 = final chunk done, 206 = partial accepted
                if upload_resp.status_code not in (200, 201, 206):
                    upload_resp.raise_for_status()
                log.info(
                    "TikTok upload [%s]: chunk %d/%d uploaded (%d bytes, HTTP %d)",
                    stem, chunk_idx + 1, total_chunks, actual_len, upload_resp.status_code,
                )
                # Update progress after each chunk
                upload_pct = int(((chunk_idx + 1) / total_chunks) * 70)  # 0-70% for upload
                progress.update(
                    phase="uploading", pct=upload_pct,
                    detail=f"Chunk {chunk_idx + 1}/{total_chunks}",
                    chunk=chunk_idx + 1, chunks=total_chunks,
                )
            except requests.exceptions.Timeout:
                progress.update(phase="failed", detail="Upload timed out")
                raise RuntimeError(
                    f"TikTok upload timed out on chunk {chunk_idx + 1}/{total_chunks} "
                    f"for {stem} ({file_size / 1024 / 1024:.0f} MB)."
                )
            except requests.exceptions.RequestException as e:
                progress.update(phase="failed", detail=f"Chunk {chunk_idx + 1} failed")
                raise RuntimeError(
                    f"TikTok upload failed on chunk {chunk_idx + 1}/{total_chunks} "
                    f"for {stem}: {e}"
                )

    log.info("TikTok upload [%s]: all %d chunks uploaded (%d bytes total)", stem, total_chunks, file_size)
    progress.update(phase="processing", pct=75, detail="Processing on TikTok...")

    # Step 3: Poll for publish status (up to ~120 seconds)
    status_url = "https://open.tiktokapis.com/v2/post/publish/status/fetch/"
    auth_headers = {
        "Authorization": f"Bearer {access_token}",
        "Content-Type": "application/json; charset=UTF-8",
    }
    status_body = {"publish_id": publish_id}
    final_status = "pending"

    for attempt in range(40):  # poll up to ~120 seconds
        time.sleep(3)
        try:
            st_resp = requests.post(
                status_url, headers=auth_headers, json=status_body, timeout=15
            )
        except Exception as e:
            log.warning("TikTok status poll %d failed for %s: %s", attempt, stem, e)
            continue

        if st_resp.status_code != 200:
            log.warning("TikTok status poll %d returned %d for %s", attempt, st_resp.status_code, stem)
            continue

        try:
            st_data = st_resp.json()
        except Exception:
            continue

        pub_status = st_data.get("data", {}).get("status", "")
        log.info("TikTok upload [%s]: poll %d status=%s", stem, attempt + 1, pub_status)

        # Progress: 75-95% during processing polls
        poll_pct = min(95, 75 + int((attempt / 40) * 20))
        status_label = pub_status.replace("_", " ").title() if pub_status else "Processing"
        progress.update(phase="processing", pct=poll_pct, detail=status_label)

        if pub_status == "PUBLISH_COMPLETE":
            final_status = "ok"
            progress.update(phase="done", pct=100, detail="Published!")
            log.info("TikTok upload [%s]: PUBLISHED!", stem)
            break
        elif pub_status in ("FAILED", "PUBLISH_FAILED"):
            err_msg = st_data.get("data", {}).get("fail_reason", "unknown")
            progress.update(phase="failed", pct=0, detail=f"Failed: {err_msg}")
            raise RuntimeError(f"TikTok publish failed for {stem}: {err_msg}")
        # else PROCESSING_UPLOAD / PROCESSING_DOWNLOAD — keep waiting

    if final_status != "ok":
        log.warning("TikTok upload [%s]: still processing after 120s (status=%s)", stem, final_status)
        progress.update(phase="processing", pct=95, detail="Still processing...")

    result = {
        "platform": "tiktok",
        "status": final_status,
        "publish_id": publish_id,
    }
    log_social_upload(stem, "tiktok", result)
    return result


# ── YouTube Shorts upload ─────────────────────────────────────────────────────

SHORTS_CHUNK_SIZE = 1024 * 1024  # 1 MB resumable chunks (same as upload.py)
SHORTS_CATEGORY_MUSIC = "10"


def youtube_shorts_upload(
    stem: str,
    privacy: str = "public",
    progress: dict | None = None,
    publish_at=None,  # datetime | None — if set, schedules Short (overrides privacy → private)
) -> dict:
    """
    Upload a portrait (9:16) video as a YouTube Short.

    Expects output/{stem}_9x16.mp4 to already exist (bot converts beforehand).
    Duration must be ≤180s for Shorts eligibility (YouTube allows up to 3 min since Oct 2024).

    publish_at (optional): datetime with tzinfo — schedules the Short for that time.
        When set, privacyStatus is forced to "private" (YouTube requirement).

    progress (optional): mutable dict for live status updates, keys:
        phase   — "init" | "uploading" | "thumbnail" | "done" | "failed"
        pct     — 0-100 int
        detail  — human-readable status string

    Returns dict: {"status": "ok", "videoId": "...", "url": "..."} or
                  {"status": "error", "error": "..."}
    """
    from googleapiclient.http import MediaFileUpload
    from youtube_auth import get_youtube_service

    if progress is None:
        progress = {}
    progress.update(phase="init", pct=0, detail="Initializing...")

    # Auto-convert to portrait if needed (same as IG upload)
    progress.update(phase="init", pct=2, detail="Checking portrait video...")
    portrait = convert_to_portrait(stem)
    if not portrait.exists():
        progress.update(phase="failed", pct=0, detail="Portrait conversion failed")
        return {"status": "error", "error": f"Portrait video not found: {portrait}"}

    # Duration check — Shorts can be up to 3 min (180s) since Oct 2024
    duration = _get_duration(portrait)
    if duration > 180:
        progress.update(phase="failed", pct=0, detail=f"Too long ({duration:.0f}s)")
        return {"status": "error", "error": f"Video is {duration:.0f}s — Shorts must be ≤3 min"}

    # Load metadata
    meta = {}
    meta_path = META_DIR / f"{stem}.json"
    try:
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
    except Exception:
        pass

    raw_title = meta.get("title") or stem.replace("_", " ").title()
    # Append #Shorts — YouTube uses this to classify as a Short
    yt_title = f"{raw_title} #Shorts".replace("<", "").replace(">", "").strip()[:100]

    # Build clean description: beat title + purchase link + full video link + hashtags
    yt_desc = _build_short_desc(stem)

    yt_tags = meta.get("tags", []) or []
    # Sanitize tags (max 30 chars each, no angle brackets)
    yt_tags = [t.replace("<", "").replace(">", "").strip()[:30]
               for t in yt_tags if t and len(t.strip()) > 0]

    progress.update(phase="init", pct=5, detail="Authenticating...")

    try:
        youtube = get_youtube_service()
    except Exception as e:
        progress.update(phase="failed", pct=0, detail="YouTube auth failed")
        return {"status": "error", "error": f"YouTube auth failed: {e}"}

    # Scheduling: force private + publishAt (YouTube requirement)
    effective_privacy = privacy if privacy in ("public", "unlisted", "private") else "public"
    status_block: dict = {
        "privacyStatus": "private" if publish_at else effective_privacy,
        "selfDeclaredMadeForKids": False,
    }
    if publish_at:
        from datetime import timezone as _tz
        if publish_at.tzinfo is None:
            publish_at = publish_at.replace(tzinfo=_tz.utc)
        status_block["publishAt"] = publish_at.isoformat()

    body = {
        "snippet": {
            "title": yt_title,
            "description": yt_desc,
            "tags": yt_tags,
            "categoryId": SHORTS_CATEGORY_MUSIC,
        },
        "status": status_block,
    }

    media = MediaFileUpload(
        str(portrait), mimetype="video/mp4",
        resumable=True, chunksize=SHORTS_CHUNK_SIZE,
    )

    progress.update(phase="uploading", pct=10, detail="Starting upload...")

    try:
        req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)
        resp = None
        while resp is None:
            chunk_status, resp = req.next_chunk()
            if chunk_status:
                pct = int(chunk_status.progress() * 70) + 10  # 10-80%
                progress.update(phase="uploading", pct=pct,
                                detail=f"Uploading {int(chunk_status.progress() * 100)}%")
    except Exception as e:
        err_str = str(e)
        err_lower = err_str.lower()
        # Quota exceeded — bubble up immediately, no retry
        if "quotaexceeded" in err_lower or ("403" in err_str and "quota" in err_lower):
            progress.update(phase="failed", pct=0, detail="YouTube quota exceeded")
            return {"status": "error", "error": f"quotaExceeded: {e}", "quota_exceeded": True}
        # Auto-retry without tags if YouTube rejects them
        if "invalidTags" in err_str or "invalid video keywords" in err_lower:
            log.warning("YouTube Shorts: tags rejected for %s, retrying without tags", stem)
            body_no_tags = {**body, "snippet": {**body["snippet"], "tags": []}}
            media2 = MediaFileUpload(
                str(portrait), mimetype="video/mp4",
                resumable=True, chunksize=SHORTS_CHUNK_SIZE,
            )
            try:
                req2 = youtube.videos().insert(part="snippet,status", body=body_no_tags, media_body=media2)
                resp = None
                while resp is None:
                    chunk_status, resp = req2.next_chunk()
                    if chunk_status:
                        pct = int(chunk_status.progress() * 70) + 10
                        progress.update(phase="uploading", pct=pct,
                                        detail=f"Uploading {int(chunk_status.progress() * 100)}%")
            except Exception as e2:
                e2_lower = str(e2).lower()
                if "quotaexceeded" in e2_lower or ("403" in str(e2) and "quota" in e2_lower):
                    progress.update(phase="failed", pct=0, detail="YouTube quota exceeded")
                    return {"status": "error", "error": f"quotaExceeded: {e2}", "quota_exceeded": True}
                progress.update(phase="failed", pct=0, detail=str(e2)[:100])
                return {"status": "error", "error": f"YouTube upload failed: {e2}"}
        else:
            progress.update(phase="failed", pct=0, detail=str(e)[:100])
            return {"status": "error", "error": f"YouTube upload failed: {e}"}

    video_id = resp["id"]
    log.info("YouTube Shorts upload [%s]: video_id=%s", stem, video_id)
    progress.update(phase="thumbnail", pct=85, detail="Uploading thumbnail...")

    # Upload thumbnail if available
    thumb = OUT_DIR / f"{stem}_thumb.jpg"
    if thumb.exists():
        try:
            thumb_media = MediaFileUpload(str(thumb), mimetype="image/jpeg", resumable=False)
            youtube.thumbnails().set(videoId=video_id, media_body=thumb_media).execute()
            log.info("YouTube Shorts [%s]: thumbnail uploaded", stem)
        except Exception as e:
            log.warning("YouTube Shorts [%s]: thumbnail upload failed: %s", stem, e)

    progress.update(phase="done", pct=100, detail="Published!")

    result = {
        "platform": "youtube_shorts",
        "status": "ok",
        "videoId": video_id,
        "url": f"https://youtube.com/shorts/{video_id}",
    }
    log_social_upload(stem, "youtube_shorts", result)
    log.info("YouTube Shorts upload [%s]: DONE — %s", stem, result["url"])
    return result


# ── Instagram upload ──────────────────────────────────────────────────────────

def _ig_api_request(
    method: str,
    url: str,
    *,
    max_retries: int = 3,
    retry_statuses: tuple = (429, 500, 502, 503, 504),
    **kwargs,
) -> requests.Response:
    """
    Wrapper for requests with retry + exponential backoff.
    Retries on connection errors, timeouts, and transient HTTP statuses.
    Does NOT retry on 400 (bad request / auth) — those are permanent failures.
    """
    last_exc = None
    for attempt in range(max_retries):
        try:
            resp = getattr(requests, method)(url, **kwargs)
            if resp.status_code not in retry_statuses:
                return resp
            # Retryable HTTP status
            wait = min(2 ** attempt * 3, 30)
            log.warning(
                "IG API %d on %s %s (attempt %d/%d), retrying in %ds",
                resp.status_code, method.upper(), url[:80], attempt + 1, max_retries, wait,
            )
            time.sleep(wait)
            last_exc = RuntimeError(f"HTTP {resp.status_code}")
        except requests.exceptions.Timeout as e:
            wait = min(2 ** attempt * 5, 60)
            log.warning(
                "IG API timeout on %s %s (attempt %d/%d), retrying in %ds",
                method.upper(), url[:80], attempt + 1, max_retries, wait,
            )
            time.sleep(wait)
            last_exc = e
        except requests.exceptions.ConnectionError as e:
            wait = min(2 ** attempt * 5, 60)
            log.warning(
                "IG API connection error on %s %s (attempt %d/%d), retrying in %ds: %s",
                method.upper(), url[:80], attempt + 1, max_retries, wait, e,
            )
            time.sleep(wait)
            last_exc = e
        except requests.exceptions.RequestException as e:
            # Non-retryable request error — bail immediately
            raise
    # All retries exhausted
    if isinstance(last_exc, Exception):
        raise last_exc
    raise RuntimeError(f"IG API failed after {max_retries} retries")


def _serve_file_via_tunnel(file_path: Path, timeout: int = 600) -> str:
    """
    Serve a single file via Cloudflare Quick Tunnel (no config needed).
    Returns a public https:// URL that IG can fetch the video from.
    Spins up a local HTTP server + cloudflared tunnel, waits for the URL.
    """
    import re
    import socket
    import threading
    from http.server import HTTPServer, SimpleHTTPRequestHandler

    # Clean up any previous tunnel first
    _cleanup_tunnel()

    # Kill stale quick-tunnel processes (NOT the main app tunnel)
    # Quick tunnels use "--url http://127.0.0.1:PORT" — main tunnel uses "--config"
    port = 18931
    try:
        result = subprocess.run(
            ["pkill", "-f", "cloudflared tunnel --url"],
            capture_output=True, text=True, timeout=5,
        )
        if result.returncode == 0:
            log.info("Killed stale quick-tunnel processes")
            time.sleep(0.3)  # brief pause for port release
    except Exception:
        pass

    # Verify port is available, if not try alternate
    for candidate_port in (port, 18932, 18933, 18934, 18935):
        try:
            sock = socket.socket(socket.AF_INET, socket.SOCK_STREAM)
            sock.setsockopt(socket.SOL_SOCKET, socket.SO_REUSEADDR, 1)
            sock.bind(("127.0.0.1", candidate_port))
            sock.close()
            port = candidate_port
            break
        except OSError:
            continue
    else:
        raise RuntimeError("All tunnel ports (18931-18935) are in use")

    # Spin up a minimal HTTP server that serves ONLY this one file
    serve_dir = file_path.parent
    serve_name = file_path.name

    class SingleFileHandler(SimpleHTTPRequestHandler):
        def __init__(self, *args, **kwargs):
            super().__init__(*args, directory=str(serve_dir), **kwargs)

        def do_GET(self):
            # Only serve the exact file we want
            if self.path.lstrip("/").split("?")[0] == serve_name:
                super().do_GET()
            else:
                self.send_error(404)

        def log_message(self, format, *args):
            pass  # Silence HTTP logs

    server = HTTPServer(("127.0.0.1", port), SingleFileHandler)
    server_thread = threading.Thread(target=server.serve_forever, daemon=True)
    server_thread.start()

    # Start cloudflared quick tunnel (use full path for LaunchAgent compatibility)
    # Retry up to 3 times — Cloudflare's quick tunnel API can return transient errors
    # (e.g. "failed to parse quick Tunnel ID: invalid UUID length: 0")
    cloudflared_bin = shutil.which("cloudflared") or "/opt/homebrew/bin/cloudflared"
    log.info("Using cloudflared binary: %s (exists=%s)", cloudflared_bin,
             Path(cloudflared_bin).exists() if cloudflared_bin else False)
    # Build clean env — LaunchAgent has minimal env, ensure HOME/PATH/TMPDIR are set
    cf_env = dict(os.environ)
    cf_env.setdefault("HOME", str(Path.home()))
    cf_env.setdefault("TMPDIR", "/tmp")
    cf_env.setdefault("PATH", "/usr/local/bin:/usr/bin:/bin:/opt/homebrew/bin")
    cf_env["NO_AUTOUPDATE"] = "true"

    tunnel_url = None
    proc = None
    cf_stderr_path = Path("/tmp/cloudflared_stderr.log")
    MAX_CF_ATTEMPTS = 4

    for cf_attempt in range(MAX_CF_ATTEMPTS):
        if cf_attempt > 0:
            log.info("Retrying cloudflared (attempt %d/%d)...", cf_attempt + 1, MAX_CF_ATTEMPTS)
            time.sleep(2)

        # Write stderr to temp file so we can capture it even if process dies fast
        cf_stderr_file = open(cf_stderr_path, "w")
        proc = subprocess.Popen(
            [cloudflared_bin, "tunnel", "--url", f"http://127.0.0.1:{port}",
             "--no-autoupdate", "--protocol", "http2"],
            stdout=subprocess.PIPE, stderr=cf_stderr_file, text=True,
            env=cf_env,
        )

        # Parse the tunnel URL from cloudflared stderr — poll fast (0.2s)
        start = time.time()
        last_pos = 0
        while time.time() - start < 12:
            if proc.poll() is not None:
                cf_stderr_file.flush()
                cf_stderr_file.close()
                stderr_content = cf_stderr_path.read_text()
                log.warning("cloudflared exited (attempt %d, rc=%d): %s",
                          cf_attempt + 1, proc.returncode, stderr_content[:500])
                break
            time.sleep(0.2)
            try:
                content = cf_stderr_path.read_text()
            except Exception:
                continue
            new_content = content[last_pos:]
            last_pos = len(content)
            if not new_content:
                continue
            match = re.search(r"(https://[a-z0-9]+-[a-z0-9-]+\.trycloudflare\.com)", new_content)
            if match:
                tunnel_url = match.group(1)
                log.info("Tunnel URL captured in %.1fs (attempt %d): %s",
                         time.time() - start, cf_attempt + 1, tunnel_url)
                break

        if tunnel_url:
            break
        try:
            proc.kill()
            proc.wait(timeout=2)
        except Exception:
            pass

    if not tunnel_url:
        server.shutdown()
        raise RuntimeError(f"Cloudflare tunnel failed after {MAX_CF_ATTEMPTS} attempts")

    video_url = f"{tunnel_url}/{serve_name}"
    log.info("Tunnel serving %s at %s", serve_name, video_url)

    # Store cleanup references so caller can shut down later
    _serve_file_via_tunnel._proc = proc
    _serve_file_via_tunnel._server = server
    _serve_file_via_tunnel._port = port

    return video_url


def _cleanup_tunnel():
    """Shut down the cloudflared tunnel and HTTP server."""
    try:
        proc = getattr(_serve_file_via_tunnel, "_proc", None)
        if proc:
            proc.kill()
            proc.wait(timeout=5)
            _serve_file_via_tunnel._proc = None
    except Exception:
        pass
    try:
        server = getattr(_serve_file_via_tunnel, "_server", None)
        if server:
            server.shutdown()
            _serve_file_via_tunnel._server = None
    except Exception:
        pass


def ig_upload(stem: str, caption: str | None = None, progress: dict | None = None) -> dict:
    """
    Upload a video as an Instagram Reel via Graph API.
    Uses resumable upload (direct binary POST) for reliable, fast uploads.

    progress: optional shared dict for live status updates to the caller.
        Keys set by this function:
        - "phase": "uploading" | "processing" | "publishing" | "done" | "error"
        - "poll": current poll number (during processing)
        - "max_polls": total poll limit
        - "pct": estimated progress 0-100
        - "detail": human-readable status string

    Returns dict with status and metadata.
    """
    def _prog(phase: str, pct: int = 0, detail: str = "", **kw):
        if progress is not None:
            progress["phase"] = phase
            progress["pct"] = pct
            progress["detail"] = detail
            progress.update(kw)
    from ig_auth import get_access_token

    access_token, ig_user_id = get_access_token()

    # Warn if token looks like IG-native (not Facebook Page token)
    if access_token.startswith("IGAA"):
        log.warning(
            "IG token starts with IGAA (Instagram-native). "
            "Content Publishing requires a Facebook Page token (EAAI...). "
            "Run /ig_setup to re-authorize through Facebook."
        )

    # Ensure 9:16 version exists (auto-trims + auto-compresses in one pass)
    portrait = convert_to_portrait(stem)

    if caption is None:
        caption = build_social_caption(stem)

    file_size = portrait.stat().st_size
    file_size_mb = file_size / 1_048_576
    graph = "https://graph.facebook.com/v25.0"

    # ── Strategy: video_url via main Cloudflare tunnel (primary).
    # Uses a signed public URL so IG can fetch the file from fy3studio.com.
    # Falls back to resumable binary upload if video_url fails.
    container_id = None

    create_url = f"{graph}/{ig_user_id}/media"

    # ── Attempt 1: video_url via main tunnel ──────────────────────────
    # Generate a signed public URL (10-min TTL, HMAC-verified)
    from app.backend.routers.files import create_signed_url
    public_url = create_signed_url(portrait.name)
    _prog("uploading", 5, "Creating IG container...")
    log.info("IG upload [%s]: video_url approach (%.1f MB) via %s", stem, file_size_mb, public_url[:80])

    # Verify the URL is reachable before giving it to IG
    try:
        check = requests.head(public_url, timeout=10, allow_redirects=True)
        url_ok = check.status_code == 200
    except Exception:
        url_ok = False

    if url_ok:
        create_params = {
            "media_type": "REELS",
            "caption": caption,
            "video_url": public_url,
            "access_token": access_token,
        }
        resp = _ig_api_request("post", create_url, params=create_params, timeout=30, max_retries=3)
        if resp.status_code == 200:
            create_data = resp.json()
            container_id = create_data.get("id")
            if container_id:
                log.info("IG upload [%s]: container %s created via video_url", stem, container_id)
                _prog("processing", 15, "IG is fetching the video...")
            else:
                log.warning("IG upload [%s]: video_url response missing id: %s", stem, resp.text[:300])
        else:
            log.warning("IG upload [%s]: video_url container failed (%d), trying resumable...",
                        stem, resp.status_code)
    else:
        log.warning("IG upload [%s]: signed URL not reachable, trying resumable upload...", stem)

    # ── Attempt 2: resumable binary upload (fallback) ─────────────────
    if not container_id:
        _prog("uploading", 5, f"Uploading {file_size_mb:.0f} MB to Instagram...")
        log.info("IG upload [%s]: resumable upload (%.1f MB)...", stem, file_size_mb)

        create_params = {
            "media_type": "REELS",
            "caption": caption,
            "upload_type": "resumable",
            "access_token": access_token,
        }
        resp = _ig_api_request("post", create_url, params=create_params, timeout=30, max_retries=3)
        if resp.status_code != 200:
            err_body = ""
            try:
                err_body = resp.json()
            except Exception:
                err_body = resp.text[:500]
            log.error("IG container creation failed (%d): %s", resp.status_code, err_body)
            if resp.status_code == 400 and access_token.startswith("IGAA"):
                raise RuntimeError(
                    "IG token invalid for publishing. Your token is Instagram-native (IGAA) "
                    "but Reels publishing needs a Facebook Page token. Run /ig_setup to fix."
                )
            resp.raise_for_status()

        create_data = resp.json()
        container_id = create_data.get("id")
        upload_uri = create_data.get("uri")
        if not container_id or not upload_uri:
            raise RuntimeError(f"IG container creation failed: {json.dumps(create_data)}")

        log.info("IG upload [%s]: container %s, uploading binary...", stem, container_id)
        _prog("uploading", 10, f"Uploading {file_size_mb:.0f} MB...")

        upload_headers = {
            "Authorization": f"OAuth {access_token}",
            "offset": "0",
            "file_size": str(file_size),
        }
        with open(portrait, "rb") as fh:
            upload_resp = requests.post(
                upload_uri, headers=upload_headers, data=fh, timeout=600,
            )
        resp_body = None
        try:
            resp_body = upload_resp.json()
        except Exception:
            pass
        log.info("IG upload [%s]: upload status=%d resp=%s",
                 stem, upload_resp.status_code,
                 json.dumps(resp_body)[:500] if resp_body else upload_resp.text[:500])
        if upload_resp.status_code >= 400:
            log.error("IG resumable upload failed (%d): %s",
                     upload_resp.status_code, resp_body or upload_resp.text[:500])
            raise RuntimeError(
                f"IG video upload failed ({upload_resp.status_code}): "
                f"{json.dumps(resp_body) if resp_body else upload_resp.text[:300]}"
            )

    _prog("processing", 20, "Waiting for IG to process...", poll=0, max_polls=80)
    log.info("IG upload [%s]: waiting for processing...", stem)

    try:
        # ── Step 3: Wait for container to finish processing ──
        # Keep tunnel alive while IG fetches the video
        # 80 polls × progressive backoff = up to ~7 minutes
        status_url = f"{graph}/{container_id}"
        max_polls = 80
        consecutive_errors = 0

        for attempt in range(max_polls):
            if attempt < 20:
                poll_wait = 3
            elif attempt < 40:
                poll_wait = 5
            else:
                poll_wait = 8
            time.sleep(poll_wait)
            # Update progress: 20-90% mapped across polls
            _pct = 20 + int((attempt / max_polls) * 70)
            _prog("processing", _pct, f"Processing... (poll {attempt + 1})",
                  poll=attempt + 1, max_polls=max_polls)

            try:
                st_resp = requests.get(
                    status_url,
                    params={"fields": "status_code,status", "access_token": access_token},
                    timeout=20,
                )
            except (requests.exceptions.Timeout, requests.exceptions.ConnectionError) as e:
                consecutive_errors += 1
                log.warning("IG poll error (attempt %d, consecutive=%d): %s", attempt + 1, consecutive_errors, e)
                if consecutive_errors >= 5:
                    raise RuntimeError(
                        f"IG processing poll failed {consecutive_errors} times in a row: {e}"
                    )
                continue

            if st_resp.status_code != 200:
                consecutive_errors += 1
                log.warning("IG poll HTTP %d (attempt %d)", st_resp.status_code, attempt + 1)
                if consecutive_errors >= 5:
                    raise RuntimeError(
                        f"IG processing poll returned {st_resp.status_code} five times in a row"
                    )
                continue

            consecutive_errors = 0
            st_data = st_resp.json()
            status_code = st_data.get("status_code", "")

            if status_code == "FINISHED":
                log.info("IG upload [%s]: processing finished (poll %d)", stem, attempt + 1)
                break
            elif status_code == "ERROR":
                err_desc = st_data.get("status", "Unknown processing error")
                raise RuntimeError(f"IG processing failed: {err_desc}")
            if attempt % 10 == 9:
                log.info("IG upload [%s]: still processing (poll %d/%d)...", stem, attempt + 1, max_polls)
        else:
            raise RuntimeError(
                f"IG processing timed out after {max_polls} polls (~7 min). "
                f"Container {container_id} may still be processing — try /ig again later."
            )

        # ── Step 4: Publish the container (with retry) ──
        _prog("publishing", 92, "Publishing to Reels...")
        publish_url = f"{graph}/{ig_user_id}/media_publish"
        publish_params = {
            "creation_id": container_id,
            "access_token": access_token,
        }
        log.info("IG upload [%s]: publishing container %s...", stem, container_id)
        pub_resp = _ig_api_request("post", publish_url, params=publish_params, timeout=60, max_retries=3)
        if pub_resp.status_code != 200:
            err_body = ""
            try:
                err_body = pub_resp.json()
            except Exception:
                err_body = pub_resp.text[:500]
            log.error("IG publish failed (%d): %s", pub_resp.status_code, err_body)
            pub_resp.raise_for_status()
        pub_data = pub_resp.json()

        media_id = pub_data.get("id")
        if not media_id:
            raise RuntimeError(f"IG publish failed: {json.dumps(pub_data)}")

        log.info("IG upload [%s]: published! media_id=%s", stem, media_id)
        _prog("done", 100, "Published!")
        result = {
            "platform": "instagram",
            "status": "ok",
            "media_id": media_id,
            "container_id": container_id,
        }
        log_social_upload(stem, "instagram", result)
        return result

    finally:
        pass  # No tunnel cleanup needed — uses main Cloudflare tunnel
