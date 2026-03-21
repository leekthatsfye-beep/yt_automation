"""
AI Thumbnail Generator using Replicate Flux models.

Genre-aware thumbnail backgrounds for YouTube beat videos.
Uses Replicate REST API directly (no SDK — works on Python 3.14).
Same pattern proven in yulan_bot/ai_designer.py.
"""

from __future__ import annotations

import io
import json
import logging
import os
import time
from pathlib import Path

import requests
from PIL import Image

from app.backend.config import ROOT, OUTPUT_DIR, METADATA_DIR, APP_SETTINGS

log = logging.getLogger(__name__)

REPLICATE_API = "https://api.replicate.com/v1"

# Models
FLUX_SCHNELL = "black-forest-labs/flux-schnell"  # Fast preview (~3-5s)
FLUX_DEV = "black-forest-labs/flux-dev"  # High quality (~15-20s)

# FY3 logo stamps (same as render.py)
THUMB_STAMP = ROOT / "brand" / "fy3_hp_stamp.png"
THUMB_STAMP_PINK = ROOT / "brand" / "fy3_hp_stamp_pink.png"

# ── Genre Prompt Templates ────────────────────────────────────────────────

GENRE_PROMPTS: dict[str, str] = {
    "trap": (
        "Dark moody cinematic scene, purple and red neon glow reflecting off "
        "wet city streets, downtown skyline silhouettes in background, "
        "thick atmospheric smoke and haze, dramatic low-angle lighting, "
        "urban nightlife atmosphere, trap music visual aesthetic"
    ),
    "drill": (
        "Gritty urban scene, monochrome concrete textures with harsh blue and red "
        "accent lighting, street photography composition, chain-link fences and "
        "brick walls, raw documentary feel, midnight city atmosphere, "
        "UK drill music visual aesthetic"
    ),
    "rnb": (
        "Warm golden hour atmosphere, smooth gradient sunset sky in amber and rose, "
        "soft bokeh light orbs floating, intimate silhouette composition, "
        "velvet and satin texture vibes, romantic cinematic mood, "
        "R&B soul music visual aesthetic"
    ),
    "lofi": (
        "Cozy anime-inspired room scene, pastel color palette, soft window light "
        "streaming through curtains onto a desk with plants and headphones, "
        "warm lo-fi study aesthetic, pixel art vibes, peaceful night scene, "
        "lo-fi chill beats visual aesthetic"
    ),
    "boombap": (
        "90s golden era hip-hop scene, colorful graffiti brick wall, boombox and "
        "vinyl records, warm film grain vintage texture, Timberlands and Kangol hats "
        "era, NYC subway tile aesthetic, classic boom bap visual style"
    ),
    "afrobeats": (
        "Vibrant tropical sunset with bold warm color palette, geometric African patterns "
        "and textile motifs, golden hour beach scene, palm silhouettes, rich orange "
        "magenta and teal color harmony, festive Afrobeats visual aesthetic"
    ),
    "hyperpop": (
        "Maximalist digital chaos, glitchy neon pixel art, Y2K chrome holographic textures, "
        "vaporwave grid landscapes, oversaturated hot pink and electric blue, "
        "distorted CRT monitor effects, hyperpop rage visual aesthetic"
    ),
    "gospel": (
        "Heavenly divine atmosphere, golden light rays streaming through volumetric clouds, "
        "warm ethereal glow, majestic sky scene at sunrise, soft lens flare effects, "
        "sacred peaceful composition, gospel spiritual music visual aesthetic"
    ),
    "dark": (
        "Ultra dark horror-inspired scene, deep shadows with distorted red and black, "
        "thick fog and mist rolling through abandoned space, eerie silhouettes, "
        "crimson accent lighting piercing darkness, phonk drift visual aesthetic"
    ),
    "pop": (
        "Clean modern studio scene, bright gradient background in pastel to vibrant tones, "
        "geometric abstract shapes floating, polished professional lighting with soft shadows, "
        "minimalist composition with bold accent colors, pop commercial visual aesthetic"
    ),
}

THUMBNAIL_SUFFIX = (
    ", cinematic YouTube thumbnail background, ultra-wide 16:9 aspect ratio, "
    "1920x1080, high resolution, atmospheric depth, no text, no words, no letters, "
    "no people, no faces, no figures, dramatic lighting, professional color grading"
)


# ── API Helpers ───────────────────────────────────────────────────────────

def get_api_key() -> str:
    """Get Replicate API token from environment or app settings."""
    token = os.environ.get("REPLICATE_API_TOKEN", "")
    if token:
        return token
    # Check app_settings.json
    try:
        if APP_SETTINGS.exists():
            settings = json.loads(APP_SETTINGS.read_text())
            token = settings.get("replicate_api_token", "")
    except Exception:
        pass
    return token


def save_api_key(key: str) -> None:
    """Save Replicate API token to app_settings.json."""
    settings: dict = {}
    try:
        if APP_SETTINGS.exists():
            settings = json.loads(APP_SETTINGS.read_text())
    except Exception:
        pass
    settings["replicate_api_token"] = key
    APP_SETTINGS.write_text(json.dumps(settings, indent=2))
    log.info("Saved Replicate API key to %s", APP_SETTINGS)


def _headers() -> dict:
    return {
        "Authorization": f"Bearer {get_api_key()}",
        "Content-Type": "application/json",
        "Prefer": "wait",
    }


def _create_prediction(model: str, inputs: dict) -> dict | None:
    """Create a Replicate prediction for an official model."""
    url = f"{REPLICATE_API}/models/{model}/predictions"
    try:
        resp = requests.post(url, headers=_headers(), json={"input": inputs}, timeout=30)
        resp.raise_for_status()
        return resp.json()
    except requests.exceptions.HTTPError as e:
        log.error("Replicate API error for %s: %s — %s", model, e, resp.text)
        return None
    except Exception as e:
        log.error("Replicate request failed for %s: %s", model, e)
        return None


def _poll_prediction(data: dict, max_seconds: int = 120) -> list | str | None:
    """Poll a Replicate prediction until completion."""
    output = data.get("output")
    status = data.get("status")

    if output and status == "succeeded":
        return output
    if status in ("failed", "canceled"):
        log.error("Prediction %s: %s", status, data.get("error"))
        return None

    get_url = data.get("urls", {}).get("get", "")
    if not get_url:
        get_url = f"{REPLICATE_API}/predictions/{data.get('id', '')}"

    for _ in range(max_seconds):
        time.sleep(1.5)
        try:
            poll = requests.get(get_url, headers=_headers(), timeout=15)
            poll.raise_for_status()
            poll_data = poll.json()
            status = poll_data.get("status")
            if status == "succeeded":
                return poll_data.get("output")
            elif status in ("failed", "canceled"):
                log.error("Prediction %s: %s", status, poll_data.get("error"))
                return None
        except Exception as e:
            log.error("Poll error: %s", e)
            return None

    log.error("Prediction timed out after %ds", max_seconds)
    return None


def _download_image(url: str) -> Image.Image | None:
    """Download an image from a URL."""
    try:
        resp = requests.get(url, timeout=60)
        resp.raise_for_status()
        return Image.open(io.BytesIO(resp.content)).convert("RGB")
    except Exception as e:
        log.error("Image download failed: %s", e)
        return None


# ── Core Functions ────────────────────────────────────────────────────────

def generate_thumbnail_image(
    genre: str,
    custom_prompt: str | None = None,
    quality: str = "preview",
    seed: int | None = None,
) -> dict | None:
    """
    Generate a single AI thumbnail background.

    Args:
        genre: Key from GENRE_PROMPTS
        custom_prompt: Optional additional style direction
        quality: "preview" (flux-schnell) or "final" (flux-dev)
        seed: Optional seed for reproducibility

    Returns:
        {"url": str, "prompt": str, "seed": int} or None on failure
    """
    if not get_api_key():
        log.error("REPLICATE_API_TOKEN not configured")
        return None

    base_prompt = GENRE_PROMPTS.get(genre, GENRE_PROMPTS["trap"])
    full_prompt = base_prompt
    if custom_prompt:
        full_prompt = f"{custom_prompt}, {base_prompt}"
    full_prompt += THUMBNAIL_SUFFIX

    model = FLUX_SCHNELL if quality == "preview" else FLUX_DEV
    inputs: dict = {
        "prompt": full_prompt,
        "aspect_ratio": "16:9",
        "output_format": "jpg",
        "output_quality": 95,
    }

    if quality == "preview":
        inputs["num_inference_steps"] = 4
    else:
        inputs["num_inference_steps"] = 28
        inputs["guidance"] = 3.5

    if seed is not None:
        inputs["seed"] = seed

    log.info("Generating %s thumbnail: genre=%s model=%s", quality, genre, model)
    data = _create_prediction(model, inputs)
    if not data:
        return None

    output = _poll_prediction(data)
    if not output:
        return None

    img_url = output[0] if isinstance(output, list) else str(output)
    result_seed = data.get("input", {}).get("seed") or seed

    return {
        "url": img_url,
        "prompt": full_prompt,
        "seed": result_seed,
        "genre": genre,
        "quality": quality,
    }


def generate_preview_grid(
    genre: str,
    custom_prompt: str | None = None,
    count: int = 4,
) -> list[dict]:
    """
    Generate multiple preview thumbnails for a genre.
    Uses flux-schnell for speed. Returns list of {url, prompt, seed, id}.
    """
    results: list[dict] = []
    import random

    for i in range(count):
        seed = random.randint(1, 999999)
        result = generate_thumbnail_image(
            genre=genre,
            custom_prompt=custom_prompt,
            quality="preview",
            seed=seed,
        )
        if result:
            result["id"] = f"preview_{i}"
            results.append(result)

    return results


def stamp_and_save(
    img: Image.Image,
    stem: str,
    output_dir: Path | None = None,
    use_pink_stamp: bool = False,
) -> Path:
    """
    Resize image to 1920×1080, stamp FY3 logo, save as thumbnail JPEG.

    Reusable helper for AI-generated, custom-uploaded, and rendered thumbnails.

    Args:
        img: PIL Image (any size/mode)
        stem: Beat stem name
        output_dir: Where to save (default: project output/)
        use_pink_stamp: Use pink stamp variant for female artists

    Returns:
        Path to saved thumbnail
    """
    out = output_dir or OUTPUT_DIR
    out.mkdir(parents=True, exist_ok=True)
    thumb_path = out / f"{stem}_thumb.jpg"

    # Resize to 1920×1080 if needed
    if img.size != (1920, 1080):
        img = img.resize((1920, 1080), Image.LANCZOS)

    # Stamp FY3 logo — bottom-center with 20px padding
    stamp_file = THUMB_STAMP_PINK if use_pink_stamp else THUMB_STAMP
    if stamp_file.exists():
        try:
            img_rgba = img.convert("RGBA")
            stamp = Image.open(stamp_file).convert("RGBA")
            x = (img_rgba.width - stamp.width) // 2
            y = img_rgba.height - stamp.height - 20
            img_rgba.paste(stamp, (x, y), stamp)
            img = img_rgba.convert("RGB")
        except Exception as e:
            log.warning("Stamp overlay failed (thumbnail still usable): %s", e)

    # Save
    img.save(thumb_path, "JPEG", quality=95)
    log.info("Thumbnail saved: %s", thumb_path)
    return thumb_path


def apply_thumbnail(
    stem: str,
    image_url: str,
    output_dir: Path | None = None,
    metadata_dir: Path | None = None,
    use_pink_stamp: bool = False,
) -> Path | None:
    """
    Download AI-generated image, stamp FY3 logo, save as thumbnail.

    Args:
        stem: Beat stem name
        image_url: URL of the AI-generated image
        output_dir: Where to save (default: project output/)
        metadata_dir: Where to update metadata (default: project metadata/)
        use_pink_stamp: Use pink stamp variant

    Returns:
        Path to saved thumbnail, or None on failure
    """
    meta = metadata_dir or METADATA_DIR

    # Download image
    img = _download_image(image_url)
    if not img:
        return None

    # Stamp + save using shared helper
    thumb_path = stamp_and_save(img, stem, output_dir, use_pink_stamp)

    # Update metadata with AI thumbnail info
    try:
        meta_path = meta / f"{stem}.json"
        if meta_path.exists():
            meta_data = json.loads(meta_path.read_text())
        else:
            meta_data = {}
        meta_data["ai_thumbnail"] = {
            "source_url": image_url,
            "generated_at": time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime()),
        }
        meta_path.write_text(json.dumps(meta_data, indent=2))
    except Exception as e:
        log.warning("Failed to update metadata: %s", e)

    return thumb_path


def get_available_genres() -> list[dict]:
    """Return list of available genre categories with labels."""
    labels = {
        "trap": "Trap",
        "drill": "Drill",
        "rnb": "R&B / Soul",
        "lofi": "Lo-fi / Chill",
        "boombap": "Boom Bap",
        "afrobeats": "Afrobeats",
        "hyperpop": "Hyperpop / Rage",
        "gospel": "Gospel / Spiritual",
        "dark": "Dark / Phonk",
        "pop": "Pop / Commercial",
    }
    return [
        {"id": key, "label": labels[key]}
        for key in GENRE_PROMPTS
    ]
