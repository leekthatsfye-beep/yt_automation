#!/usr/bin/env python3
"""
YT Automation Demo Bot — Let producers try beat analysis + SEO generation.

Generic branding only ("YT Automation"). No personal logos or channel links.

Usage:
    python demo_bot.py

Requires DEMO_BOT_TOKEN in .env
"""

from __future__ import annotations

import json
import logging
import os
import re
import tempfile
import warnings
from datetime import datetime, timedelta
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
import librosa  # noqa: E402

from telegram import InlineKeyboardButton, InlineKeyboardMarkup, Update
from telegram.ext import (
    ApplicationBuilder,
    CallbackQueryHandler,
    CommandHandler,
    ContextTypes,
    MessageHandler,
    filters,
)

# ── Paths ───────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
ASSETS_DIR = ROOT / "demo_assets"
USAGE_FILE = ROOT / "demo_usage.json"

FREE_LIMIT = 3  # free analyses per user

# ── Logging ─────────────────────────────────────────────────────────────────

logging.basicConfig(
    format="%(asctime)s [DEMO] %(message)s",
    level=logging.INFO,
)
log = logging.getLogger(__name__)

# ── Load .env ───────────────────────────────────────────────────────────────


def load_env():
    env_path = ROOT / ".env"
    if env_path.exists():
        for line in env_path.read_text().splitlines():
            line = line.strip()
            if not line or line.startswith("#") or "=" not in line:
                continue
            k, v = line.split("=", 1)
            os.environ.setdefault(k.strip(), v.strip().strip('"').strip("'"))


load_env()
BOT_TOKEN = os.environ.get("DEMO_BOT_TOKEN", "")
CONTACT_HANDLE = os.environ.get("DEMO_CONTACT", "@leekthatsfy3")

# ── BPM / Key Detection (from analyze_beats.py) ────────────────────────────

MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                           2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                           2.54, 4.75, 3.98, 2.69, 3.34, 3.17])
NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F",
              "F#", "G", "G#", "A", "A#", "B"]


def detect_bpm(y: np.ndarray, sr: int) -> int:
    _, y_perc = librosa.effects.hpss(y)
    onset_env = librosa.onset.onset_strength(y=y_perc, sr=sr, aggregate=np.median)
    tempo = librosa.feature.tempo(onset_envelope=onset_env, sr=sr)[0]
    candidates = [tempo]
    if tempo < 90:
        candidates.append(tempo * 2)
    if tempo > 160:
        candidates.append(tempo / 2)
    if tempo < 70:
        candidates.append(tempo * 3)
    candidates = [c for c in candidates if 60 <= c <= 200]
    if candidates:
        tempo = min(candidates, key=lambda t: abs(t - 130))
    return int(round(float(tempo)))


def detect_key(y: np.ndarray, sr: int) -> str:
    y_harm, _ = librosa.effects.hpss(y)
    chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr, bins_per_octave=36)
    chroma_median = np.median(chroma, axis=1)
    best_score = -np.inf
    best_key = "C Major"
    for i in range(12):
        score_major = np.corrcoef(chroma_median, np.roll(MAJOR_PROFILE, i))[0, 1]
        score_minor = np.corrcoef(chroma_median, np.roll(MINOR_PROFILE, i))[0, 1]
        if score_major > best_score:
            best_score = score_major
            best_key = f"{NOTE_NAMES[i]} Major"
        if score_minor > best_score:
            best_score = score_minor
            best_key = f"{NOTE_NAMES[i]} Minor"
    return best_key


# ── SEO Tag Generation (from seo_metadata.py) ──────────────────────────────

_BPM_VIBE = {
    (0,   79):  "emotional",
    (80,  109): "melodic",
    (110, 129): "trap",
    (130, 149): "hard",
    (150, 169): "dark",
    (170, 999): "drill",
}

_TAG_ARTISTS_BY_VIBE = {
    "emotional": [
        "Rod Wave", "Polo G", "Lil Durk", "NBA YoungBoy", "NoCap",
        "Lil Tjay", "Morray", "Toosii", "YNW Melly", "Lil Poppa",
        "Kevin Gates", "Lil Baby", "EST Gee", "Big Sean", "J Cole",
    ],
    "melodic": [
        "Drake", "Gunna", "Future", "A Boogie wit da Hoodie", "Lil Tjay",
        "Don Toliver", "The Weeknd", "6LACK", "Bryson Tiller", "Summer Walker",
        "Giveon", "Brent Faiyaz", "SZA", "Khalid", "Daniel Caesar",
    ],
    "trap": [
        "Travis Scott", "Young Thug", "Lil Uzi Vert", "Playboi Carti", "Metro Boomin",
        "Gunna", "Lil Baby", "Future", "21 Savage", "Offset",
        "Quavo", "Kodak Black", "Lil Keed", "Lil Gotit", "Lil Durk",
    ],
    "hard": [
        "21 Savage", "Moneybagg Yo", "42 Dugg", "Kodak Black", "Lil Baby",
        "Lil Durk", "EST Gee", "Mozzy", "Boosie Badazz", "Kevin Gates",
        "Dave East", "G Herbo", "Fredo Bang", "Rylo Rodriguez", "Lil Reese",
    ],
    "dark": [
        "Rod Wave", "NBA YoungBoy", "Lil Durk", "EST Gee", "Polo G",
        "Kevin Gates", "Mozzy", "Rylo Rodriguez", "Lil Poppa", "NoCap",
        "G Herbo", "Fredo Bang", "Quando Rondo", "Lil Reese", "Lil Baby",
    ],
    "drill": [
        "Pop Smoke", "Fivio Foreign", "Sheff G", "Lil Tjay", "Kay Flock",
        "Bizzy Banks", "Coi Leray", "Central Cee", "Digga D", "Unknown T",
        "Dave", "Headie One", "Loski", "Tion Wayne", "M Huncho",
    ],
}

_VIBE_LABELS = {
    "emotional": "Emotional / Melodic",
    "melodic":   "Melodic R&B",
    "trap":      "Hard Trap",
    "hard":      "Street / Hard",
    "dark":      "Dark Melodic",
    "drill":     "UK Drill",
}


def _vibe_from_bpm(bpm: int, key: str = "") -> str:
    vibe = "trap"
    for (lo, hi), v in _BPM_VIBE.items():
        if lo <= bpm <= hi:
            vibe = v
            break
    if "Minor" in key and vibe in ("melodic", "trap"):
        vibe = "dark"
    elif "Major" in key and vibe == "emotional":
        vibe = "melodic"
    return vibe


def build_demo_tags(title: str, bpm: int, key: str) -> list[str]:
    """Generate SEO tags for demo (generic producer name)."""
    vibe = _vibe_from_bpm(bpm, key)
    artists = list(_TAG_ARTISTS_BY_VIBE.get(vibe, _TAG_ARTISTS_BY_VIBE["trap"]))

    candidates = [
        f"{title} type beat",
        f"{title} beat",
        f"{title} instrumental",
    ]

    for a in artists[:8]:
        candidates.append(f"{a} type beat")
        candidates.append(f"free {a} type beat")

    candidates += [
        f"{bpm} bpm beat",
        f"{bpm} bpm type beat",
        f"{key} beat",
        f"{vibe} type beat",
        f"{vibe} instrumental",
        "type beat", "free type beat", "rap instrumental",
        "trap beat", "trap instrumental", "free beat",
        "2026 type beat", "free rap beat", "hip hop instrumental",
        "new type beat 2026", "beats for sale",
    ]

    seen = set()
    tags = []
    char_budget = 490
    total_chars = 0
    for t in candidates:
        t_clean = t.strip()[:30]
        t_lower = t_clean.lower()
        if t_lower in seen:
            continue
        if total_chars + len(t_clean) + 1 > char_budget or len(tags) >= 30:
            break
        seen.add(t_lower)
        tags.append(t_clean)
        total_chars += len(t_clean) + 1

    return tags


def build_demo_description(title: str) -> str:
    """Generic YouTube description for demo preview."""
    return f"""{title} Type Beat | Free Instrumental 2026

Original beat produced and uploaded via YT Automation.
All instrumentals available for artists, creators, and listeners.

Listen freely
License beats: [Link in bio]
New uploads weekly.

#typebeat #freebeat #instrumental #trapbeat #{title.lower().replace(' ', '')}""".strip()


# ── Thumbnail Generation (PIL only, no ffmpeg) ─────────────────────────────

def generate_thumbnail(title: str, bpm: int, key: str) -> Path:
    """Create a demo thumbnail image with watermark."""
    from PIL import Image, ImageDraw, ImageFont

    W, H = 1280, 720
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    # Dark gradient background
    for y in range(H):
        r = int(15 + (25 - 15) * y / H)
        g = int(15 + (20 - 15) * y / H)
        b = int(30 + (50 - 30) * y / H)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    # Try to load a nice font, fall back to default
    font_large = None
    font_med = None
    font_small = None
    font_paths = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
        "C:\\Windows\\Fonts\\arialbd.ttf",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            font_large = ImageFont.truetype(fp, 72)
            font_med = ImageFont.truetype(fp, 36)
            font_small = ImageFont.truetype(fp, 24)
            break

    if not font_large:
        font_large = ImageFont.load_default()
        font_med = font_large
        font_small = font_large

    # Accent line
    draw.rectangle([(80, 200), (W - 80, 204)], fill=(255, 120, 50))

    # Beat title
    draw.text((W // 2, 280), title.upper(), fill=(255, 255, 255),
              font=font_large, anchor="mm")

    # BPM + Key info
    info_text = f"{bpm} BPM  |  {key}"
    draw.text((W // 2, 370), info_text, fill=(200, 200, 200),
              font=font_med, anchor="mm")

    # "TYPE BEAT" subtitle
    draw.text((W // 2, 430), "TYPE BEAT | FREE INSTRUMENTAL",
              fill=(255, 120, 50), font=font_med, anchor="mm")

    # Watermark
    draw.text((W // 2, 650), "YT AUTOMATION DEMO",
              fill=(100, 100, 100), font=font_small, anchor="mm")

    # Top bar
    draw.rectangle([(0, 0), (W, 5)], fill=(255, 120, 50))

    out_path = Path(tempfile.mktemp(suffix=".jpg"))
    img.save(out_path, "JPEG", quality=90)
    return out_path


# ── Header Image ────────────────────────────────────────────────────────────

def ensure_header_image() -> Path:
    """Generate the 'YT Automation' header image if it doesn't exist."""
    header_path = ASSETS_DIR / "yt_auto_header.png"
    if header_path.exists():
        return header_path

    from PIL import Image, ImageDraw, ImageFont

    ASSETS_DIR.mkdir(parents=True, exist_ok=True)

    W, H = 800, 400
    img = Image.new("RGB", (W, H))
    draw = ImageDraw.Draw(img)

    # Dark gradient
    for y in range(H):
        r = int(10 + (20 - 10) * y / H)
        g = int(10 + (15 - 10) * y / H)
        b = int(25 + (45 - 25) * y / H)
        draw.line([(0, y), (W, y)], fill=(r, g, b))

    font_title = None
    font_sub = None
    font_paths = [
        "/System/Library/Fonts/Supplemental/Arial Bold.ttf",
        "/System/Library/Fonts/Supplemental/Arial.ttf",
        "/usr/share/fonts/truetype/dejavu/DejaVuSans-Bold.ttf",
    ]
    for fp in font_paths:
        if Path(fp).exists():
            font_title = ImageFont.truetype(fp, 56)
            font_sub = ImageFont.truetype(fp, 22)
            break

    if not font_title:
        font_title = ImageFont.load_default()
        font_sub = font_title

    # Accent bars
    draw.rectangle([(0, 0), (W, 6)], fill=(255, 120, 50))
    draw.rectangle([(0, H - 6), (W, H)], fill=(255, 120, 50))

    # Title
    draw.text((W // 2, H // 2 - 30), "YT AUTOMATION",
              fill=(255, 255, 255), font=font_title, anchor="mm")

    # Subtitle
    draw.text((W // 2, H // 2 + 40), "Beat Upload Automation for Producers",
              fill=(180, 180, 180), font=font_sub, anchor="mm")

    img.save(header_path, "PNG")
    log.info(f"Generated header image: {header_path}")
    return header_path


# ── Usage Tracking ──────────────────────────────────────────────────────────

def _load_usage() -> dict:
    if USAGE_FILE.exists():
        try:
            return json.loads(USAGE_FILE.read_text())
        except Exception:
            pass
    return {}


def _save_usage(data: dict):
    USAGE_FILE.write_text(json.dumps(data, indent=2))


def get_user_count(user_id: int) -> int:
    usage = _load_usage()
    return usage.get(str(user_id), {}).get("count", 0)


def increment_user(user_id: int):
    usage = _load_usage()
    key = str(user_id)
    if key not in usage:
        usage[key] = {"count": 0, "first_use": datetime.now().isoformat()}
    usage[key]["count"] += 1
    usage[key]["last_use"] = datetime.now().isoformat()
    _save_usage(usage)


def total_users() -> int:
    return len(_load_usage())


# ── Telegram Helpers ────────────────────────────────────────────────────────

def esc(text: str) -> str:
    """Escape MarkdownV2 special characters."""
    for ch in r"\_*[]()~`>#+-=|{}.!":
        text = text.replace(ch, f"\\{ch}")
    return text


def safe_stem(filename: str) -> str:
    s = Path(filename).stem.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s.strip("_")


# ── Command Handlers ────────────────────────────────────────────────────────

async def cmd_start(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """Welcome message with header image."""
    header = ensure_header_image()

    caption = (
        "*YT Automation* \u2014 Beat Upload Bot for Producers\n\n"
        "Drop a beat, get back:\n"
        "\u2022 BPM \\+ Key detection\n"
        "\u2022 30 SEO\\-optimized YouTube tags\n"
        "\u2022 Full YouTube description\n"
        "\u2022 Sample thumbnail\n"
        "\u2022 Upload schedule preview\n\n"
        f"*{FREE_LIMIT} free analyses* \\| then upgrade for full automation\\.\n\n"
        "Just send me an audio file \\(MP3 or WAV\\) to get started\\!"
    )

    with open(header, "rb") as f:
        await update.message.reply_photo(
            photo=f,
            caption=caption,
            parse_mode="MarkdownV2",
        )


async def cmd_help(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "*Commands:*\n\n"
        "/start \\- Welcome \\+ how it works\n"
        "/demo \\- How to analyze a beat\n"
        "/pricing \\- See pricing tiers\n"
        "/results \\- See real channel stats\n"
        "/help \\- This message\n\n"
        "Or just *send an audio file* \\(MP3/WAV\\) and I'll analyze it\\!"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def cmd_demo(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    uses = get_user_count(update.effective_user.id)
    remaining = max(0, FREE_LIMIT - uses)

    text = (
        "*How to use:*\n\n"
        "1\\. Send me any beat \\(MP3 or WAV\\)\n"
        "2\\. I'll detect BPM, key, and vibe\n"
        "3\\. Generate 30 SEO tags \\+ YouTube description\n"
        "4\\. Create a sample thumbnail\n"
        "5\\. Show your upload schedule preview\n\n"
        f"You have *{remaining}* free analyses remaining\\."
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


async def cmd_pricing(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "*YT Automation \\- Pricing*\n\n"
        "*Demo* \\- Free\n"
        f"\u2022 {FREE_LIMIT} beat analyses\n"
        "\u2022 SEO tags \\+ description preview\n"
        "\u2022 Sample thumbnails\n\n"
        "*Starter* \\- $49/mo\n"
        "\u2022 Full Telegram bot on your machine\n"
        "\u2022 Auto\\-render HD videos\n"
        "\u2022 Auto\\-upload to YouTube\n"
        "\u2022 Smart scheduling \\(algorithm\\-friendly\\)\n"
        "\u2022 SEO metadata generation\n"
        "\u2022 Custom thumbnails\n"
        "\u2022 Up to 30 beats/month\n\n"
        "*Pro* \\- $99/mo\n"
        "\u2022 Everything in Starter\n"
        "\u2022 Unlimited beats\n"
        "\u2022 Stem extraction \\+ MIDI export\n"
        "\u2022 TikTok / IG / Shorts auto\\-posting\n"
        "\u2022 Channel analytics\n"
        "\u2022 Priority support\n\n"
        "*Setup* \\- $299 one\\-time\n"
        "\u2022 Full system installed on your machine\n"
        "\u2022 1 month Pro included\n"
        "\u2022 Personalized setup \\+ walkthrough\n"
    )

    keyboard = InlineKeyboardMarkup([
        [InlineKeyboardButton("Get Started", url=f"https://t.me/{CONTACT_HANDLE.lstrip('@')}")],
    ])

    await update.message.reply_text(text, parse_mode="MarkdownV2", reply_markup=keyboard)


async def cmd_results(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    text = (
        "*Real Results from YT Automation*\n\n"
        "\U0001f4ca *Channel Stats \\(one producer\\):*\n"
        "\u2022 5,960\\+ subscribers\n"
        "\u2022 1,449,174 total views\n"
        "\u2022 650\\+ videos uploaded\n"
        "\u2022 60 scheduled uploads in under 1 hour\n"
        "\u2022 Channel running on complete autopilot\n\n"
        "\u23f1 *Time Saved:*\n"
        "\u2022 Manual: 30 min/beat \\u00d7 100 beats \\= 50 hours\n"
        "\u2022 With bot: 100 beats in under 2 hours\n"
        "\u2022 That's *48 hours saved* per batch\n\n"
        "\U0001f525 *The bot handles:*\n"
        "\u2022 Video rendering with custom visuals\n"
        "\u2022 SEO\\-optimized titles, tags, descriptions\n"
        "\u2022 Custom branded thumbnails\n"
        "\u2022 Smart upload scheduling\n"
        "\u2022 Duplicate detection \\+ channel cleanup\n"
        "\u2022 Stem extraction \\+ MIDI for old beats"
    )
    await update.message.reply_text(text, parse_mode="MarkdownV2")


# ── Audio File Handler (the main demo experience) ──────────────────────────

async def handle_audio(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    """When user sends an audio file, analyze it and show results."""
    user_id = update.effective_user.id
    uses = get_user_count(user_id)

    if uses >= FREE_LIMIT:
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Get Full Access",
                                  url=f"https://t.me/{CONTACT_HANDLE.lstrip('@')}")],
        ])
        await update.message.reply_text(
            f"You've used all {FREE_LIMIT} free analyses\\!\n\n"
            "Ready to automate your whole channel? "
            "Get the full version \\-\\- render, upload, schedule, "
            "all from your phone\\.",
            parse_mode="MarkdownV2",
            reply_markup=keyboard,
        )
        return

    # Get the file
    doc = update.message.document or update.message.audio
    if not doc:
        await update.message.reply_text("Send me an MP3 or WAV file to analyze!")
        return

    fname = doc.file_name or "beat.mp3"
    ext = Path(fname).suffix.lower()
    if ext not in (".mp3", ".wav", ".m4a", ".flac", ".ogg"):
        await update.message.reply_text(
            "Please send an audio file \\(MP3, WAV, M4A, FLAC, or OGG\\)\\.",
            parse_mode="MarkdownV2",
        )
        return

    # Status message
    status = await update.message.reply_text("Analyzing your beat...")

    try:
        # Download
        tg_file = await doc.get_file()
        tmp = Path(tempfile.mktemp(suffix=ext))
        await tg_file.download_to_drive(tmp)

        # Analyze
        await status.edit_text("Detecting BPM and key...")
        y, sr = librosa.load(str(tmp), sr=22050, mono=True)
        bpm = detect_bpm(y, sr)
        key = detect_key(y, sr)

        # Duration
        duration = librosa.get_duration(y=y, sr=sr)
        dur_str = f"{int(duration // 60)}:{int(duration % 60):02d}"

        # Generate SEO
        await status.edit_text("Generating SEO metadata...")
        stem = safe_stem(fname)
        title = stem.replace("_", " ").title()
        vibe = _vibe_from_bpm(bpm, key)
        vibe_label = _VIBE_LABELS.get(vibe, vibe.title())
        tags = build_demo_tags(title, bpm, key)
        desc = build_demo_description(title)

        # Generate thumbnail
        await status.edit_text("Creating thumbnail...")
        thumb_path = generate_thumbnail(title, bpm, key)

        # Build schedule preview
        today = datetime.now()
        sched_lines = []
        for i in range(7):
            d = today + timedelta(days=i + 1)
            sched_lines.append(f"  {d.strftime('%b %d')} @ 11:00 AM")

        # Increment usage
        increment_user(user_id)
        remaining = FREE_LIMIT - (uses + 1)

        # Delete status
        await status.delete()

        # Send analysis
        analysis = (
            f"*BEAT ANALYSIS*\n\n"
            f"*Title:*  {esc(title)}\n"
            f"*BPM:*    {bpm}\n"
            f"*Key:*    {esc(key)}\n"
            f"*Vibe:*   {esc(vibe_label)}\n"
            f"*Length:*  {esc(dur_str)}\n\n"
            f"{'\\-' * 30}\n\n"
            f"*SEO TAGS \\({len(tags)}\\):*\n"
            f"{esc(', '.join(tags[:15]))}\n"
            f"_\\.\\.\\. and {len(tags) - 15} more_\n\n"
            f"{'\\-' * 30}\n\n"
            f"*YOUTUBE DESCRIPTION:*\n"
            f"```\n{desc}\n```\n\n"
            f"{'\\-' * 30}\n\n"
            f"*UPLOAD SCHEDULE PREVIEW:*\n"
            f"_If you uploaded 30 beats today:_\n"
        )
        for sl in sched_lines:
            analysis += f"`{sl}`\n"
        analysis += (
            f"`  ...`\n"
            f"`  {(today + timedelta(days=30)).strftime('%b %d')} @ 11:00 AM`\n"
            f"\n_\\= 30 days of content, hands\\-free_\n\n"
        )

        if remaining > 0:
            analysis += f"_{remaining} free analyses remaining_"
        else:
            analysis += "_This was your last free analysis\\!_"

        await update.message.reply_text(analysis, parse_mode="MarkdownV2")

        # Send thumbnail
        keyboard = InlineKeyboardMarkup([
            [InlineKeyboardButton("Get Full Access",
                                  url=f"https://t.me/{CONTACT_HANDLE.lstrip('@')}")],
        ])

        with open(thumb_path, "rb") as f:
            await update.message.reply_photo(
                photo=f,
                caption=(
                    "Sample thumbnail \\(demo\\)\\. "
                    "Full version renders HD videos with custom visuals\\!"
                ),
                parse_mode="MarkdownV2",
                reply_markup=keyboard,
            )

        # Cleanup
        tmp.unlink(missing_ok=True)
        thumb_path.unlink(missing_ok=True)

    except Exception as e:
        log.error(f"Analysis error: {e}", exc_info=True)
        try:
            await status.edit_text(f"Sorry, something went wrong analyzing your beat. Try again!")
        except Exception:
            pass


# ── Callback Handler ────────────────────────────────────────────────────────

async def handle_callback(update: Update, ctx: ContextTypes.DEFAULT_TYPE):
    query = update.callback_query
    await query.answer()


# ── Main ────────────────────────────────────────────────────────────────────

def main():
    if not BOT_TOKEN:
        print("ERROR: Set DEMO_BOT_TOKEN in .env")
        print("  1. Message @BotFather on Telegram")
        print("  2. Create a new bot (name: 'YT Automation Demo')")
        print("  3. Copy the token")
        print("  4. Add to .env: DEMO_BOT_TOKEN=your_token_here")
        return

    # Generate header on startup
    ensure_header_image()

    log.info("Starting YT Automation Demo Bot...")
    log.info(f"Total users so far: {total_users()}")

    app = ApplicationBuilder().token(BOT_TOKEN).build()

    # Commands
    app.add_handler(CommandHandler("start", cmd_start))
    app.add_handler(CommandHandler("help", cmd_help))
    app.add_handler(CommandHandler("demo", cmd_demo))
    app.add_handler(CommandHandler("pricing", cmd_pricing))
    app.add_handler(CommandHandler("results", cmd_results))

    # Audio files
    app.add_handler(MessageHandler(
        filters.Document.ALL | filters.AUDIO, handle_audio
    ))

    # Callbacks
    app.add_handler(CallbackQueryHandler(handle_callback))

    log.info("Bot is running! Send /start to test.")
    app.run_polling(drop_pending_updates=True)


if __name__ == "__main__":
    main()
