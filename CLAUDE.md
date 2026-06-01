# CLAUDE.md

This file provides guidance to Claude Code (claude.ai/code) when working with code in this repository.

## Project Purpose

YouTube automation pipeline that converts audio beats (MP3/WAV) into rendered MP4 videos with thumbnails, then uploads them to YouTube with optional scheduled publishing.

## Running the Pipeline

```bash
source .venv/bin/activate

python render.py          # render all beats in beats/
python batch_ten.py       # render the hand-picked 10-video batch
python seo_metadata.py    # generate SEO metadata for any beats missing it
python upload.py          # upload all rendered videos to YouTube
```

`run_all.py` and `upload_youtube.py` are empty stubs — ignore them.

## System Dependencies

- **ffmpeg** must be in `$PATH` — used for video encoding
- **Font path** in `config.yaml` is macOS-specific: `/System/Library/Fonts/Supplemental/Arial.ttf`

## Architecture

### Pipeline Flow (render.py)

```
beats/*.{mp3,wav}
    → safe_stem() normalizes filename
    → ensure_audio_safe_name() renames file on disk if needed
    → load metadata from metadata/{stem}.json (auto-created if missing)
    → pick background image: images/{stem}.jpg → images/default.jpg
    → pick video clip:       images/{stem}.mp4 → images/default_visual.mp4 → None
    → make_thumbnail() → output/{stem}_thumb.jpg  (always uses jpg background)
    → render_video_from_clip() or render_video() → output/{stem}.mp4
```

All steps are **idempotent**: existing output files are skipped with `[SKIP]`.

### Video Background Priority

`render.py` and `batch_ten.py` both follow this resolution order:

1. `images/{stem}.mp4` — per-beat custom clip
2. `images/default_visual.mp4` — shared default visualizer (currently clip 1: landscape 720×406)
3. Still image fallback (`images/{stem}.jpg` or `images/default.jpg`) — only if no clip exists

Portrait clips (taller than wide) get **blurred background + centered overlay** (Option A).
Landscape clips get **scale-to-fill + crop** — no blur needed.

Available visualizer clips in `images/`:

| File | Resolution | Duration | Orientation |
|---|---|---|---|
| `default_visual.mp4` | 720×406 | 46s | Landscape |
| `visual_2.mp4` | 720×1280 | 64s | Portrait |
| `visual_3.mp4` | 720×1280 | 40s | Portrait |
| `visual_4.mp4` | 720×1280 | 70s | Portrait |

### Video Encoding

- **Still image path**: `libx264 + AAC 192k`, zoompan filter (1.0× → 1.12× zoom over duration), 1920×1080@30fps yuv420p
- **Video clip path**: `libx264 -preset slow -crf 18 + AAC 192k`, `-stream_loop -1` loops clip, `-shortest` stops at audio end

### Metadata JSON Schema

Each beat requires `metadata/{stem}.json`. Auto-created with defaults if missing:

```json
{
  "title": "Beat Title",
  "artist": "BiggKutt8",
  "description": "",
  "tags": ["type beat", "trap beat", ...]
}
```

`seo_metadata.py` generates richer metadata with SEO artist tags and a description template. It never overwrites existing files.

The stem is derived from the audio filename after sanitization: spaces → underscores, punctuation stripped, lowercase. Example: `"Hood Legend !.mp3"` → stem `"hood_legend"` → `metadata/hood_legend.json`.

### config.yaml Structure

```yaml
render:
  image_default: "images/default.jpg"   # fallback background (must exist)
  font_path: "/System/Library/Fonts/Supplemental/Arial.ttf"  # required
  width: 1920
  height: 1080
  fps: 30
```

`font_path` is required and raises `KeyError` if absent. `image_default` raises `FileNotFoundError` if missing.

## YouTube Upload

### First-time setup

1. Download `client_secret.json` from Google Cloud Console → APIs & Services → Credentials → OAuth 2.0 Client ID (Desktop app) → Download JSON. Place it in the project root.
2. Run any upload command — browser opens once for Google sign-in, then `token.json` handles auth silently.

### upload.py usage

```bash
# Upload everything not yet in uploads_log.json
python upload.py

# Preview without uploading
python upload.py --dry-run

# Specific beats only
python upload.py --only "army,hood_legend,master_plan"

# Upload as unlisted
python upload.py --privacy unlisted

# Schedule a single video
python upload.py --only "army" --schedule-at "2026-02-20T18:00:00-05:00"

# Schedule a full batch, one per day
python upload.py --schedule-start "2026-02-20T18:00:00-05:00" --every-minutes 1440

# Re-upload something already logged
python upload.py --only "army" --skip-uploaded false
```

Scheduled uploads are always set to `privacyStatus=private` with `publishAt` — YouTube requires this. `--privacy` is ignored when scheduling.

`uploads_log.json` in the project root records every upload: `stem → {videoId, url, uploadedAt, title, publishAt?}`. Written after each successful upload so Ctrl+C never loses progress.

## Adding a New Beat

1. Drop the audio file into `beats/`
2. Run `python seo_metadata.py` to generate metadata (or create `metadata/{stem}.json` manually)
3. Optionally add `images/{stem}.jpg` for a custom thumbnail background
4. Optionally add `images/{stem}.mp4` for a per-beat visualizer clip
5. Run `python render_lit.py` to render (render.py was deleted — use render_lit.py now)
6. Run `python upload.py` to upload

## IMPORTANT — Session Memory (Read Every Session)

**render.py is DELETED** — the active render script is `render_lit.py`. Always use that.

**Python virtualenv** — there is no `.venv`. Use `.venv_ml` for render scripts:
```bash
/Users/fyefye/yt_automation/.venv_ml/bin/python3 render_lit.py
```

**Active artists / thumbnail photo sources:**
- **ADX (ShawtyRøkk x Tezzus)** — thumbnail photo: `~/Dropbox/Shawtyrokk/IMG_9674.jpg` (Miami street, white jacket, dreads, "MIAMI NOW OPEN" sign). Currently copied to `images/adx.jpg`.
- All press photos for Shawtyrokk are in `~/Dropbox/Shawtyrokk/` (IMG_9662 through IMG_9674 + MP4s).

**FY3 Harry Potter lightning logo** — `brand/fy3_hp_stamp.png` is the gold HP-style "FY3 !" logo that goes on EVERY thumbnail, bottom-center, 20px from the bottom. This is the actual brand logo used across all thumbnails. Fallback: `brand/fy3_thumb_stamp.png` (red circular stamp). The `make_thumbnail()` function in `batch_ten.py` now stamps it automatically. "harry potter" or "FY3 logo" in user messages = this stamp.

**FY3 DVD bouncing logo** — `render_lit.py` now generates an "FY3" text logo that bounces corner-to-corner like a DVD screensaver on all rendered videos. This is ALWAYS on by default. The logo PNG is cached in `/tmp/render_lit_assets/fy3_logo.png`. NOTE: the DVD bounce uses a plain generated text logo; for the actual brand logo in videos, use `brand/fy3_hp_stamp.png` or the `.mov` files in `brand/` (fy3_dvd_gold.mov, fy3_dvd_pink.mov).

**Thumbnail generation** — `make_thumbnail()` is in `batch_ten.py`. To regenerate a single thumbnail without a full render:
```python
# Quick one-off thumbnail (run from project root with .venv_ml python):
from pathlib import Path
from PIL import Image, ImageDraw, ImageFont
import json

stem = "adx"  # change this
# NO TEXT on thumbnails — clean photo + FY3 stamp only
bg = Image.open(f"images/{stem}.jpg").convert("RGB").resize((1920, 1080))
stamp = Image.open("brand/fy3_hp_stamp.png").convert("RGBA")
bg_rgba = bg.convert("RGBA")
x = (bg_rgba.width - stamp.width) // 2
bg_rgba.paste(stamp, (x, bg_rgba.height - stamp.height - 20), stamp)
bg_rgba.convert("RGB").save(f"output/{stem}_thumb.jpg", "JPEG", quality=95)
```

**Upload thumbnail to YouTube** — after regenerating a thumb, update it via the YouTube API (needs `token.json` auth). Check `upload.py` for the `thumbnails().set()` method.

**Artist folders** — visualizer clips may be in `images/{artist}/` subfolders (e.g., `images/BiggKutt8/visual_2.mp4`). `render_lit.py` checks artist subfolder via `seo_artist` field in metadata JSON.

**Copyright note** — the user mentioned the visual UI is copyrighted. Avoid using third-party visual assets. The Doom fire, LTF glow, and FY3 DVD logo in `render_lit.py` are all procedurally generated — no third-party assets.
