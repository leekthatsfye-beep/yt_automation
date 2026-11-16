"""
fy3mentary_tiktok.py — FY3M3NTARY TikTok duration optimization pipeline.

Duration strategy (28-day experiment vs current baseline):
  40%  short discovery clips  : 15–59 seconds
  60%  extended stories       : 65–90 seconds
  +    long-form              : 90–180 seconds only when story genuinely needs it

Production requirements enforced here:
  - Opening hook overlay at t=0 within first 2 seconds (title card)
  - FY3M3NTARY branding stamp (bottom-center)
  - Documentary-specific captions (not beat captions)
  - Never artificially stretch a clip to hit a duration target
  - Clips are classified by their natural duration — no trimming to fit a bucket

Clip source: fy3mentary/clips/{stem}.mp4
Metadata:   fy3mentary/metadata/{stem}.json
Output:     fy3mentary/output/{stem}_tt.mp4

Usage:
    python fy3mentary_tiktok.py --status           # show queue + ratio health
    python fy3mentary_tiktok.py --prepare          # render all unprocessed clips
    python fy3mentary_tiktok.py --prepare STEM     # render one clip
    python fy3mentary_tiktok.py --post             # post next clip (respects ratio)
    python fy3mentary_tiktok.py --post --now       # post immediately
    python fy3mentary_tiktok.py --post --dry-run   # preview caption + clip selection
    python fy3mentary_tiktok.py --log-metrics      # prompt to enter TikTok analytics
"""
from __future__ import annotations

import argparse
import json
import logging
import os
import random
import re
import subprocess
import sys
import time
from datetime import date, datetime, timezone
from pathlib import Path
from typing import Optional

log = logging.getLogger(__name__)
logging.basicConfig(level=logging.INFO, format="[%(levelname)s] %(message)s")

ROOT         = Path(__file__).resolve().parent
FY3M_DIR     = ROOT / "fy3mentary"
CLIPS_DIR    = FY3M_DIR / "clips"
META_DIR     = FY3M_DIR / "metadata"
OUT_DIR      = FY3M_DIR / "output"
EXP_DIR      = FY3M_DIR / "experiment"
BRAND_DIR    = ROOT / "brand"

UPLOAD_LOG   = FY3M_DIR / "tiktok_log.json"
QUEUE_LOG    = FY3M_DIR / "queue.json"

# ── Duration buckets ──────────────────────────────────────────────────────────

DISCOVERY_MIN, DISCOVERY_MAX = 15, 59    # short discovery
STORY_MIN,     STORY_MAX     = 65, 90    # extended story
LONGFORM_MIN,  LONGFORM_MAX  = 90, 180   # long-form (story-driven only)

# Target ratio: 40% discovery, 60% story/long-form over rolling window
DISCOVERY_TARGET_RATIO = 0.40
STORY_TARGET_RATIO     = 0.60
RATIO_WINDOW           = 10   # look at last N posts to assess ratio health


def classify_duration(seconds: float) -> Optional[str]:
    """
    Classify a clip's natural duration into a bucket.
    Returns None if the duration falls outside all supported ranges.
    Never forces a clip into a bucket it doesn't fit.
    """
    if DISCOVERY_MIN <= seconds <= DISCOVERY_MAX:
        return "discovery"
    if STORY_MIN < seconds <= STORY_MAX:
        return "story"
    if STORY_MAX < seconds <= LONGFORM_MAX:
        return "longform"
    if seconds < DISCOVERY_MIN:
        return None   # too short — skip
    if seconds > LONGFORM_MAX:
        return None   # too long — needs editing first
    return None


# ── Branding ──────────────────────────────────────────────────────────────────

FY3M_STAMP_CANDIDATES = [
    BRAND_DIR / "fy3mentary_stamp.png",    # preferred FY3M3NTARY-specific stamp
    BRAND_DIR / "fy3_hp_stamp.png",        # fallback: existing FY3 gold HP stamp
    BRAND_DIR / "fy3_thumb_stamp.png",     # last resort: red circle stamp
]

HOOK_FONT_CANDIDATES = [
    "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
    "C:/Windows/Fonts/arialbd.ttf",
]

HOOK_FONT_SIZE = 58   # px — readable at arm's length on phone
HOOK_BG_ALPHA  = 180  # 0–255 pill background opacity


def _get_stamp() -> Optional[Path]:
    for p in FY3M_STAMP_CANDIDATES:
        if p.exists():
            return p
    return None


def _load_font(size: int):
    from PIL import ImageFont
    for path in HOOK_FONT_CANDIDATES:
        try:
            return ImageFont.truetype(path, size)
        except OSError:
            continue
    try:
        return ImageFont.load_default(size=size)
    except TypeError:
        return ImageFont.load_default()


def _render_hook_png(text: str, out_path: Path, canvas_w: int = 1080, canvas_h: int = 1920):
    """
    Render an opening hook title card as a transparent PNG overlay.
    White bold text on a semi-transparent black pill, top of frame.
    """
    from PIL import Image, ImageDraw

    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))
    draw = ImageDraw.Draw(img)
    font = _load_font(HOOK_FONT_SIZE)

    # Measure text
    bbox = draw.textbbox((0, 0), text, font=font)
    tw, th = bbox[2] - bbox[0], bbox[3] - bbox[1]

    pad_x, pad_y = 32, 20
    pill_w = tw + pad_x * 2
    pill_h = th + pad_y * 2
    pill_x = (canvas_w - pill_w) // 2
    pill_y = 80   # top zone — above subject's head

    # Draw pill background
    draw.rounded_rectangle(
        [pill_x, pill_y, pill_x + pill_w, pill_y + pill_h],
        radius=pill_h // 2,
        fill=(0, 0, 0, HOOK_BG_ALPHA),
    )

    # Draw text
    text_x = pill_x + pad_x
    text_y = pill_y + pad_y
    draw.text((text_x, text_y), text, fill=(255, 255, 255, 255), font=font)

    img.save(str(out_path))


def _render_branding_png(out_path: Path, canvas_w: int = 1080, canvas_h: int = 1920):
    """
    Render FY3M3NTARY channel branding as a transparent PNG overlay.
    Uses existing stamp if available, otherwise generates text-based branding.
    """
    from PIL import Image, ImageDraw, ImageFont

    img = Image.new("RGBA", (canvas_w, canvas_h), (0, 0, 0, 0))

    stamp = _get_stamp()
    if stamp:
        s = Image.open(str(stamp)).convert("RGBA")
        # Scale stamp to max 300px wide, preserve aspect
        max_w = 300
        ratio = max_w / s.width if s.width > max_w else 1.0
        new_w = int(s.width * ratio)
        new_h = int(s.height * ratio)
        s = s.resize((new_w, new_h), Image.LANCZOS)
        x = (canvas_w - new_w) // 2
        y = canvas_h - new_h - 20
        img.paste(s, (x, y), s)
    else:
        # Text-based fallback branding
        draw = ImageDraw.Draw(img)
        font = _load_font(36)
        label = "FY3M3NTARY"
        bbox = draw.textbbox((0, 0), label, font=font)
        tw = bbox[2] - bbox[0]
        x = (canvas_w - tw) // 2
        y = canvas_h - 60
        draw.text((x + 2, y + 2), label, fill=(0, 0, 0, 180), font=font)  # shadow
        draw.text((x, y), label, fill=(212, 175, 55, 230), font=font)     # gold

    img.save(str(out_path))


# ── ffprobe duration ──────────────────────────────────────────────────────────

def get_duration(path: Path) -> float:
    try:
        r = subprocess.run(
            ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
             "-of", "csv=p=0", str(path)],
            capture_output=True, text=True, timeout=10,
        )
        return float(r.stdout.strip())
    except Exception:
        return 0.0


# ── Metadata helpers ──────────────────────────────────────────────────────────

def load_meta(stem: str) -> dict:
    mp = META_DIR / f"{stem}.json"
    if mp.exists():
        try:
            return json.loads(mp.read_text())
        except Exception:
            pass
    return {}


def save_meta(stem: str, data: dict):
    META_DIR.mkdir(parents=True, exist_ok=True)
    (META_DIR / f"{stem}.json").write_text(json.dumps(data, indent=2))


def auto_meta(stem: str, duration_s: float, bucket: str) -> dict:
    """Create a minimal metadata scaffold for a new clip."""
    return {
        "title":      stem.replace("_", " ").title(),
        "hook":       "",           # fill in manually — strong hook required
        "tags":       ["fy3mentary", "documentary", "hiphop"],
        "saga":       "",           # active saga name if applicable
        "bucket":     bucket,
        "duration_s": round(duration_s, 2),
        "notes":      "",
    }


# ── Upload log ────────────────────────────────────────────────────────────────

def load_upload_log() -> dict:
    try:
        if UPLOAD_LOG.exists():
            return json.loads(UPLOAD_LOG.read_text())
    except Exception:
        pass
    return {}


def save_upload_log(data: dict):
    UPLOAD_LOG.write_text(json.dumps(data, indent=2, default=str))


# ── Queue log ─────────────────────────────────────────────────────────────────

def load_queue() -> dict:
    try:
        if QUEUE_LOG.exists():
            return json.loads(QUEUE_LOG.read_text())
    except Exception:
        pass
    return {"pending": [], "skip": []}


def save_queue(data: dict):
    QUEUE_LOG.write_text(json.dumps(data, indent=2, default=str))


# ── Ratio health ──────────────────────────────────────────────────────────────

def ratio_health(upload_log: dict) -> tuple[float, float, str]:
    """
    Look at the last RATIO_WINDOW uploads and return:
    (discovery_ratio, story_ratio, next_recommended_bucket)
    """
    recent = sorted(
        upload_log.values(),
        key=lambda e: e.get("posted_at", ""),
        reverse=True,
    )[:RATIO_WINDOW]

    if not recent:
        return 0.0, 0.0, "discovery"

    discovery = sum(1 for e in recent if e.get("bucket") == "discovery")
    story     = sum(1 for e in recent if e.get("bucket") in ("story", "longform"))
    total     = len(recent)

    dr = discovery / total
    sr = story / total

    # Recommend whichever bucket is most behind target
    if dr < DISCOVERY_TARGET_RATIO:
        return dr, sr, "discovery"
    return dr, sr, "story"


# ── Caption builder ───────────────────────────────────────────────────────────

_DOC_HOOKS = [
    "They never told you this part 👇",
    "The story doesn't start where you think it does 👇",
    "This is what actually happened 👇",
    "Nobody's talking about what came before this 👇",
    "Here's what the blogs missed 👇",
    "This is bigger than the beef 👇",
    "Watch from the beginning — it changes everything 👇",
    "The timeline tells a different story 👇",
    "Pay attention to who's NOT talking about this 👇",
    "The real story got buried 👇",
    "Context changes everything. Watch this 👇",
    "This was hidden in plain sight 👇",
    "Before you have an opinion — watch this first 👇",
    "Part of a bigger saga nobody's documenting 👇",
    "FY3M3NTARY goes where other channels don't 👇",
    "We document what others skip over 👇",
    "Still unfolding. Here's where it started 👇",
    "Every saga has a beginning. This is it 👇",
    "Drop a 🎬 if you want the full documentary 👇",
    "This whole arc is on the channel 👇",
]

_DOC_HASHTAGS_BASE = [
    "#fy3mentary", "#documentary", "#hiphop", "#hiphopnews",
    "#streetdoc", "#hiphophistory", "#fyp",
]


def _pick_hook_text(stem: str, meta: dict) -> str:
    """
    Pick opening hook text. Priority:
    1. hook field in metadata (editorial — strongest)
    2. title field formatted as a hook
    3. rotating generic doc hook
    """
    hook = meta.get("hook", "").strip()
    if hook:
        return hook

    title = meta.get("title", "").strip()
    if title:
        return title

    day = date.today().timetuple().tm_yday
    stem_hash = sum(ord(c) for c in stem)
    return _DOC_HOOKS[(stem_hash + day) % len(_DOC_HOOKS)]


def build_caption(stem: str) -> str:
    """
    Build a TikTok caption for a FY3M3NTARY documentary clip.
    - Hook line (from metadata or rotating)
    - Title
    - Saga tag if applicable
    - Hashtags
    """
    meta = load_meta(stem)
    title  = meta.get("title", stem.replace("_", " ").title())
    saga   = meta.get("saga", "").strip()
    bucket = meta.get("bucket", "")
    extra_tags = meta.get("tags", [])

    hook_line = _DOC_HOOKS[
        (sum(ord(c) for c in stem) + date.today().timetuple().tm_yday) % len(_DOC_HOOKS)
    ]

    tags = list(_DOC_HASHTAGS_BASE)
    for t in extra_tags:
        tag = "#" + re.sub(r"[^a-zA-Z0-9]", "", t)
        if tag not in tags:
            tags.append(tag)

    saga_line = f"\n#{re.sub(r'[^a-zA-Z0-9]', '', saga)}Saga" if saga else ""
    duration_cue = " [extended cut]" if bucket in ("story", "longform") else ""

    caption = (
        f"{hook_line}\n\n"
        f"{title}{duration_cue}"
        f"{saga_line}\n\n"
        f"{' '.join(tags[:8])} #documentary"
    )
    return caption.strip()[:2200]


# ── Clip preparation (render TikTok version) ──────────────────────────────────

def prepare_clip(stem: str, force: bool = False) -> Optional[Path]:
    """
    Take a raw clip from fy3mentary/clips/{stem}.mp4 and produce
    fy3mentary/output/{stem}_tt.mp4 with:
      - FY3M3NTARY branding stamp (bottom-center, every frame)
      - Opening hook title card (first 3s overlay)
      - No duration change — natural length preserved
      - 9:16 portrait if source is landscape (blur+center), passthrough if already portrait

    Returns output path on success, None on failure.
    """
    from PIL import Image

    src = CLIPS_DIR / f"{stem}.mp4"
    if not src.exists():
        log.error("[PREP] Source clip not found: %s", src)
        return None

    out = OUT_DIR / f"{stem}_tt.mp4"
    if out.exists() and not force:
        log.info("[SKIP] Already prepared: %s", out)
        return out

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    duration_s = get_duration(src)
    if duration_s <= 0:
        log.error("[PREP] Could not read duration: %s", src)
        return None

    bucket = classify_duration(duration_s)
    if bucket is None:
        log.warning(
            "[PREP] %s is %.1fs — outside all supported buckets (need 15–180s). "
            "Edit before preparing.", stem, duration_s
        )
        return None

    meta = load_meta(stem)
    if not meta:
        meta = auto_meta(stem, duration_s, bucket)
        save_meta(stem, meta)
        log.info("[META] Auto-created metadata for %s — set 'hook' field for best results", stem)

    # Probe input dimensions
    dim_r = subprocess.run(
        ["ffprobe", "-v", "quiet", "-select_streams", "v:0",
         "-show_entries", "stream=width,height", "-of", "csv=p=0", str(src)],
        capture_output=True, text=True, timeout=10,
    )
    try:
        w_str, h_str = dim_r.stdout.strip().split(",")
        src_w, src_h = int(w_str), int(h_str)
    except ValueError:
        src_w, src_h = 0, 0

    is_portrait = src_h > src_w
    out_w, out_h = 1080, 1920

    # Render hook overlay PNG
    hook_text = _pick_hook_text(stem, meta)
    hook_png  = OUT_DIR / f"_hook_{stem}.png"
    brand_png = OUT_DIR / f"_brand_{stem}.png"

    try:
        _render_hook_png(hook_text, hook_png, out_w, out_h)
        _render_branding_png(brand_png, out_w, out_h)
    except Exception as e:
        log.error("[PREP] Overlay render failed: %s", e)
        return None

    # Build ffmpeg filtergraph
    # Input 0: source video+audio
    # Input 1: hook overlay PNG (shown for first 3s)
    # Input 2: branding overlay PNG (always visible)

    hook_duration = min(3.0, duration_s * 0.15)  # 3s or 15% of clip, whichever shorter

    if is_portrait and src_w == out_w and src_h == out_h:
        # Already 1080×1920 — passthrough scale
        video_filter = "[0:v]scale=1080:1920,setsar=1[base]"
    elif is_portrait:
        # Portrait but wrong size — scale to fit
        video_filter = (
            f"[0:v]scale={out_w}:{out_h}:force_original_aspect_ratio=decrease,"
            f"pad={out_w}:{out_h}:(ow-iw)/2:(oh-ih)/2:black,setsar=1[base]"
        )
    else:
        # Landscape → blur+center for portrait frame
        video_filter = (
            f"[0:v]split[a][b];"
            f"[a]scale={out_w}:{out_h}:force_original_aspect_ratio=increase,"
            f"crop={out_w}:{out_h},boxblur=20:5[bg];"
            f"[b]scale=-2:{out_h}[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2,setsar=1[base]"
        )

    overlay_filter = (
        f"{video_filter};"
        f"[base][1:v]overlay=0:0:enable='between(t,0,{hook_duration:.2f})'[with_hook];"
        f"[with_hook][2:v]overlay=0:0[out]"
    )

    cmd = [
        "ffmpeg", "-y",
        "-i", str(src),
        "-i", str(hook_png),
        "-i", str(brand_png),
        "-filter_complex", overlay_filter,
        "-map", "[out]",
        "-map", "0:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "23",
        "-c:a", "aac", "-b:a", "128k",
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out),
    ]

    log.info("[PREP] Rendering %s (%.1fs, %s)...", stem, duration_s, bucket)
    result = subprocess.run(cmd, capture_output=True, text=True, timeout=600)

    # Cleanup temp PNGs
    for p in [hook_png, brand_png]:
        try:
            p.unlink()
        except Exception:
            pass

    if result.returncode != 0:
        log.error("[PREP] ffmpeg failed:\n%s", result.stderr[-2000:])
        return None

    # Update metadata with confirmed duration + bucket
    meta["bucket"]     = bucket
    meta["duration_s"] = round(duration_s, 2)
    save_meta(stem, meta)

    log.info("[PREP] Done: %s → %s (bucket=%s)", stem, out.name, bucket)
    return out


# ── Queue management ──────────────────────────────────────────────────────────

def build_queue() -> list[dict]:
    """
    Scan fy3mentary/output/ for prepared clips not yet posted.
    Returns list of {stem, bucket, duration_s, out_path} sorted by filename.
    """
    upload_log = load_upload_log()
    posted_stems = set(upload_log.keys())

    items = []
    for f in sorted(OUT_DIR.glob("*_tt.mp4")):
        stem = f.stem.replace("_tt", "")
        if stem in posted_stems:
            continue
        duration_s = get_duration(f)
        bucket = classify_duration(duration_s) or "unknown"
        # Pull bucket from metadata if available (more reliable than re-classifying output)
        meta = load_meta(stem)
        if meta.get("bucket"):
            bucket = meta["bucket"]
        items.append({
            "stem":       stem,
            "bucket":     bucket,
            "duration_s": round(duration_s, 2),
            "out_path":   str(f),
        })
    return items


def pick_next_clip(queue: list[dict], upload_log: dict) -> Optional[dict]:
    """
    Pick the next clip to post, enforcing the 40/60 ratio.
    If ratio is healthy, defaults to story bucket (higher Creator Rewards eligibility).
    Never picks a clip that doesn't genuinely fit its bucket.
    """
    if not queue:
        return None

    _, _, recommended = ratio_health(upload_log)

    # Separate by bucket
    discovery = [c for c in queue if c["bucket"] == "discovery"]
    story     = [c for c in queue if c["bucket"] in ("story", "longform")]

    if recommended == "discovery" and discovery:
        return discovery[0]
    if story:
        return story[0]
    if discovery:
        return discovery[0]
    return queue[0]


# ── TikTok upload (reuses browser automation from tiktok_auto.py) ─────────────

def post_to_tiktok(clip: dict, caption: str, dry_run: bool = False) -> bool:
    """
    Upload a prepared clip to TikTok.
    Reuses the upload_to_tiktok() function from tiktok_auto.py.
    """
    from tiktok_auto import upload_to_tiktok
    return upload_to_tiktok(Path(clip["out_path"]), caption, dry_run=dry_run)


# ── Analytics experiment ──────────────────────────────────────────────────────

EXPERIMENT_LOG = EXP_DIR / "experiment_log.json"
EXPERIMENT_DAYS = 28
EXPERIMENT_START_KEY = "experiment_start"


def load_experiment() -> dict:
    try:
        if EXPERIMENT_LOG.exists():
            return json.loads(EXPERIMENT_LOG.read_text())
    except Exception:
        pass
    return {}


def save_experiment(data: dict):
    EXP_DIR.mkdir(parents=True, exist_ok=True)
    EXPERIMENT_LOG.write_text(json.dumps(data, indent=2, default=str))


def record_upload_in_experiment(stem: str, bucket: str, duration_s: float):
    """Log an upload to the experiment tracker."""
    exp = load_experiment()

    if EXPERIMENT_START_KEY not in exp:
        exp[EXPERIMENT_START_KEY] = date.today().isoformat()
        log.info("[EXP] 28-day experiment started: %s", exp[EXPERIMENT_START_KEY])

    exp[stem] = {
        "bucket":     bucket,
        "duration_s": round(duration_s, 2),
        "posted_on":  date.today().isoformat(),
        "metrics":    {},
    }
    save_experiment(exp)


def log_metrics(stem: str, metrics: dict):
    """
    Store TikTok analytics for a posted clip.
    metrics keys: views, avg_watch_s, pct_watched, completion_rate,
                  followers_gained, foryou_pct
    """
    exp = load_experiment()
    if stem not in exp:
        log.warning("[EXP] %s not in experiment log — add it via record_upload_in_experiment first", stem)
        return
    exp[stem]["metrics"] = {**exp[stem].get("metrics", {}), **metrics}
    exp[stem]["metrics_updated"] = datetime.now(timezone.utc).isoformat()
    save_experiment(exp)
    log.info("[EXP] Metrics saved for %s", stem)


def experiment_report() -> str:
    """
    Generate a 28-day experiment comparison report.
    Returns a formatted string — does not auto-replace strategy.
    """
    exp = load_experiment()
    start_str = exp.get(EXPERIMENT_START_KEY)

    clips = {k: v for k, v in exp.items() if k != EXPERIMENT_START_KEY and isinstance(v, dict)}
    if not clips:
        return "No clips in experiment yet."

    # Group by bucket
    buckets: dict[str, list[dict]] = {"discovery": [], "story": [], "longform": []}
    for stem, data in clips.items():
        b = data.get("bucket", "unknown")
        if b in buckets:
            buckets[b].append(data)

    def avg(vals):
        v = [x for x in vals if x is not None]
        return sum(v) / len(v) if v else None

    def fmt(val, unit=""):
        if val is None:
            return "—"
        return f"{val:.1f}{unit}"

    lines = [
        "=" * 60,
        "FY3M3NTARY — 28-Day TikTok Duration Experiment",
        f"Started: {start_str or 'unknown'}",
        "=" * 60,
        "",
    ]

    for bucket_name, items in buckets.items():
        measured = [d for d in items if d.get("metrics")]
        lines.append(f"── {bucket_name.upper()} ({len(items)} clips, {len(measured)} with metrics) ──")
        if not measured:
            lines.append("  No analytics logged yet.\n")
            continue

        m_list = [d["metrics"] for d in measured]
        lines += [
            f"  Avg views            : {fmt(avg([m.get('views') for m in m_list]))}",
            f"  Avg watch duration   : {fmt(avg([m.get('avg_watch_s') for m in m_list]), 's')}",
            f"  Avg % watched        : {fmt(avg([m.get('pct_watched') for m in m_list]), '%')}",
            f"  Avg completion rate  : {fmt(avg([m.get('completion_rate') for m in m_list]), '%')}",
            f"  Followers / 1k views : {fmt(avg([m.get('followers_gained') for m in m_list]))}",
            f"  FYP traffic %        : {fmt(avg([m.get('foryou_pct') for m in m_list]), '%')}",
            "",
        ]

    # Days remaining
    if start_str:
        try:
            started = date.fromisoformat(start_str)
            elapsed = (date.today() - started).days
            remaining = max(0, EXPERIMENT_DAYS - elapsed)
            lines.append(f"Experiment: Day {elapsed}/{EXPERIMENT_DAYS} — {remaining} days remaining")
        except Exception:
            pass

    lines += [
        "",
        "NOTE: Do not replace current strategy until 28 days complete",
        "      and performance data clearly supports the change.",
        "=" * 60,
    ]
    return "\n".join(lines)


# ── Status ────────────────────────────────────────────────────────────────────

def cmd_status():
    upload_log = load_upload_log()
    queue      = build_queue()
    dr, sr, next_bucket = ratio_health(upload_log)

    total_posted = len(upload_log)
    disc_posted  = sum(1 for e in upload_log.values() if e.get("bucket") == "discovery")
    story_posted = sum(1 for e in upload_log.values() if e.get("bucket") in ("story", "longform"))

    print("=" * 55)
    print("FY3M3NTARY TikTok — Pipeline Status")
    print("=" * 55)
    print(f"\nPosted total : {total_posted}")
    print(f"  Discovery  : {disc_posted}  ({dr*100:.0f}%  target {DISCOVERY_TARGET_RATIO*100:.0f}%)")
    print(f"  Story/Long : {story_posted}  ({sr*100:.0f}%  target {STORY_TARGET_RATIO*100:.0f}%)")
    print(f"\nNext recommended bucket: {next_bucket.upper()}")

    print(f"\nQueue ({len(queue)} clips ready to post):")
    if not queue:
        print("  (empty — run --prepare to process clips from fy3mentary/clips/)")
    else:
        for c in queue[:10]:
            hook_set = "✓" if load_meta(c["stem"]).get("hook") else "✗ no hook"
            print(f"  {c['stem']:<30} {c['duration_s']:.1f}s  [{c['bucket']}]  hook:{hook_set}")
        if len(queue) > 10:
            print(f"  ... and {len(queue)-10} more")

    print(f"\nRaw clips in fy3mentary/clips/: {len(list(CLIPS_DIR.glob('*.mp4')))}")
    print("=" * 55)


# ── CLI ───────────────────────────────────────────────────────────────────────

def main():
    ap = argparse.ArgumentParser(description="FY3M3NTARY TikTok duration pipeline")
    ap.add_argument("--status",       action="store_true", help="Show queue + ratio health")
    ap.add_argument("--prepare",      nargs="?", const="__all__", metavar="STEM",
                    help="Render TikTok version of one clip or all unprocessed clips")
    ap.add_argument("--post",         action="store_true", help="Post next clip to TikTok")
    ap.add_argument("--now",          action="store_true", help="With --post: ignore schedule")
    ap.add_argument("--dry-run",      action="store_true", help="Preview without posting")
    ap.add_argument("--log-metrics",  metavar="STEM",
                    help="Interactively log TikTok analytics for a posted clip")
    ap.add_argument("--report",       action="store_true", help="Print 28-day experiment report")
    ap.add_argument("--force",        action="store_true", help="With --prepare: re-render existing")
    args = ap.parse_args()

    if args.status:
        cmd_status()
        return

    if args.prepare is not None:
        if args.prepare == "__all__":
            clips = sorted(CLIPS_DIR.glob("*.mp4"))
            if not clips:
                print(f"No clips found in {CLIPS_DIR}")
                return
            upload_log = load_upload_log()
            done = 0
            for src in clips:
                stem = src.stem
                if stem in upload_log and not args.force:
                    log.info("[SKIP] %s already posted", stem)
                    continue
                out = OUT_DIR / f"{stem}_tt.mp4"
                if out.exists() and not args.force:
                    log.info("[SKIP] %s already prepared", stem)
                    continue
                result = prepare_clip(stem, force=args.force)
                if result:
                    done += 1
            print(f"\nPrepared {done} clip(s).")
        else:
            prepare_clip(args.prepare, force=args.force)
        return

    if args.post:
        upload_log = load_upload_log()
        queue      = build_queue()

        if not queue:
            print("No prepared clips in queue. Run --prepare first.")
            return

        clip    = pick_next_clip(queue, upload_log)
        caption = build_caption(clip["stem"])

        print(f"\nNext up: {clip['stem']}")
        print(f"  Bucket   : {clip['bucket']}")
        print(f"  Duration : {clip['duration_s']:.1f}s")
        print(f"  File     : {clip['out_path']}")
        print(f"\nCaption:\n{caption}\n")

        if args.dry_run:
            print("[DRY RUN] No upload.")
            return

        success = post_to_tiktok(clip, caption, dry_run=False)
        if success:
            today = date.today().isoformat()
            upload_log[clip["stem"]] = {
                "bucket":    clip["bucket"],
                "duration_s": clip["duration_s"],
                "caption":   caption,
                "posted_at": datetime.now(timezone.utc).isoformat(),
                "file":      clip["out_path"],
            }
            save_upload_log(upload_log)
            record_upload_in_experiment(clip["stem"], clip["bucket"], clip["duration_s"])
            print(f"[DONE] {clip['stem']} posted ✓")
        else:
            print(f"[FAIL] Upload failed for {clip['stem']}")
        return

    if args.log_metrics:
        stem = args.log_metrics
        print(f"Logging TikTok analytics for: {stem}")
        print("Enter values (press Enter to skip):\n")

        def prompt_float(label: str) -> Optional[float]:
            val = input(f"  {label}: ").strip()
            try:
                return float(val) if val else None
            except ValueError:
                return None

        metrics = {
            "views":             prompt_float("Views"),
            "avg_watch_s":       prompt_float("Avg watch duration (seconds)"),
            "pct_watched":       prompt_float("% watched (0–100)"),
            "completion_rate":   prompt_float("Completion rate % (0–100)"),
            "followers_gained":  prompt_float("Followers gained"),
            "foryou_pct":        prompt_float("For You traffic % (0–100)"),
        }
        metrics = {k: v for k, v in metrics.items() if v is not None}
        log_metrics(stem, metrics)
        return

    if args.report:
        print(experiment_report())
        return

    ap.print_help()


if __name__ == "__main__":
    main()
