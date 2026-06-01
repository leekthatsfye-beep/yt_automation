"""
fetch_press_photos.py
─────────────────────
Auto-fetches fresh artist press photos from Google Images and saves them
into the correct artist folder under images/artist_photos/.

Quality filters applied:
  - Minimum resolution: 800×600
  - Landscape or square only (no ultra-tall portrait crops)
  - No obvious black bars (>10% of width/height)
  - JPEG/PNG only
  - Deduplication by perceptual hash — won't re-download near-identical images

Usage:
    python fetch_press_photos.py --artist "Glokk40Spazz" --count 10
    python fetch_press_photos.py --artist "Sexyy Red" --count 8
    python fetch_press_photos.py --all --count 10   # top up every artist

The script uses the SerpApi Google Images endpoint (free tier: 100 searches/mo).
Set SERPAPI_KEY in .env or export it as an env var.
If no API key is set, falls back to direct Google Images scraping via requests.
"""

import argparse
import hashlib
import io
import json
import os
import re
import time
from pathlib import Path

import requests
from PIL import Image

# ── Config ────────────────────────────────────────────────────────────────────

ROOT = Path(__file__).resolve().parent
ARTIST_PHOTOS = ROOT / "images" / "artist_photos"

# Maps seo_artist → (folder, search query)
ARTIST_CONFIG = {
    "Glokk40Spazz": {
        "folder": "Glokk40Spazz",
        "instagram": "glokk40spazz",
        "queries": [
            "Glokk40Spazz Chicago rapper press photo",
            "Glokk40Spazz photoshoot",
        ],
    },
    "Sexyy Red": {
        "folder": "SexyyRed",
        "instagram": "sexyyred",
        "queries": [
            "Sexyy Red rapper press photo",
            "Sexyy Red photoshoot",
        ],
    },
    "BiggKutt8": {
        "folder": "BiggKutt8",
        "instagram": "biggkutt8",
        "queries": [
            "BiggKutt8 rapper photo",
            "BiggKutt8 press photo",
        ],
    },
    "Ola Runt": {
        "folder": "OlaRunt",
        "instagram": "olarunt",
        "queries": [
            "Ola Runt Atlanta rapper photo",
            "Ola Runt press photo",
        ],
    },
    "Tezzus": {
        "folder": "Tezzus",
        "instagram": "tezzus",
        "queries": [
            "Tezzus Atlanta rapper photo",
            "Tezzus ATL rap artist photoshoot",
        ],
    },
    "Foogiano": {
        "folder": "Foogiano",
        "instagram": "foogiano",
        "queries": [
            "Foogiano rapper solo photo",
            "Foogiano alone photoshoot",
        ],
    },
    "Nine Vicious": {
        "folder": "NineVicious",
        "instagram": "ninevicious2",
        "queries": [
            "Nine Vicious rapper photo",
            "Nine Vicious rap artist photo",
        ],
    },
    "Diamond": {
        "folder": "Diamond",
        "instagram": "elleadorediamant",
        "queries": [
            "diamond* rapper YSL Atlanta solo photo",
            "Misonn Scott rapper Atlanta solo",
        ],
    },
    "Che": {
        "folder": "Che",
        "instagram": "praiseche",
        "queries": [
            "Che rapper praiseche Atlanta solo press photo",
            "Che rapper Rest in Bass press photo",
        ],
    },
    "Molly Santana": {
        "folder": "MollySantana",
        "instagram": "mollysantana",
        "queries": [
            "Molly Santana rapper press photo",
            "Molly Santana rap artist photo",
        ],
    },
    "BK The Rula": {
        "folder": "BKTheRula",
        "instagram": "bktherula",
        "queries": [
            "BK The Rula rapper press photo",
            "BKTheRula rap artist photo",
        ],
    },
}

# Domains that mostly serve album art, thumbnails, flyers — skip them
_SKIP_DOMAINS = {
    "i.scdn.co", "spotify.com",           # Spotify album art
    "i.pinimg.com", "pinterest.com",       # Pinterest thumbnails
    "last.fm", "lastfm.freetls.fastly.net",# Last.fm album art
    "genius.com",                          # Genius thumbnails
    "allmusic.com",                        # AllMusic thumbnails
    "tiktok.com",                          # TikTok (blocked anyway)
    "ytimg.com", "youtube.com",            # YouTube thumbnails
    "discogs.com",                         # Discogs album art
    "amazon.com", "media-amazon.com",      # Amazon album art
    "soundcloud.com",                      # SoundCloud
}

MIN_W, MIN_H = 800, 600          # minimum resolution
MAX_ASPECT_RATIO = 0.9           # skip ultra-portrait (h/w > this is fine, but w/h must be > 0.6)
BLACK_BAR_THRESHOLD = 0.12       # reject if >12% of width/height is black bars
PHASH_BITS = 8                   # perceptual hash size (8 → 64-bit hash)
PHASH_DISTANCE = 5               # max hamming distance for "duplicate"

HEADERS = {
    "User-Agent": (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
        "AppleWebKit/537.36 (KHTML, like Gecko) "
        "Chrome/124.0.0.0 Safari/537.36"
    ),
    "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8",
    "Accept-Language": "en-US,en;q=0.5",
    "Referer": "https://www.google.com/",
}


# ── Perceptual hash ────────────────────────────────────────────────────────────

def _phash(img: Image.Image, hash_size: int = PHASH_BITS) -> int:
    """Compute a simple difference hash (dHash) for near-duplicate detection."""
    img = img.convert("L").resize((hash_size + 1, hash_size), Image.LANCZOS)
    pixels = list(img.getdata())
    diff = []
    for row in range(hash_size):
        for col in range(hash_size):
            px_l = pixels[row * (hash_size + 1) + col]
            px_r = pixels[row * (hash_size + 1) + col + 1]
            diff.append(1 if px_l > px_r else 0)
    return int("".join(map(str, diff)), 2)


def _hamming(a: int, b: int) -> int:
    return bin(a ^ b).count("1")


def _load_existing_hashes(folder: Path) -> list[int]:
    hashes = []
    for f in folder.iterdir():
        if f.suffix.lower() in (".jpg", ".jpeg", ".png"):
            try:
                hashes.append(_phash(Image.open(f)))
            except Exception:
                pass
    return hashes


def _is_duplicate(new_hash: int, existing: list[int]) -> bool:
    return any(_hamming(new_hash, h) <= PHASH_DISTANCE for h in existing)


# ── Quality checks ─────────────────────────────────────────────────────────────

def _detect_black_bars(img: Image.Image) -> bool:
    """Return True if image has significant black bars on any side."""
    try:
        import numpy as np
        arr = __import__("numpy").array(img.convert("RGB"))
        H, W = arr.shape[:2]
        row_means = arr.mean(axis=(1, 2))
        col_means = arr.mean(axis=(0, 2))
        content_rows = __import__("numpy").where(row_means > 20)[0]
        content_cols = __import__("numpy").where(col_means > 20)[0]
        if len(content_rows) == 0 or len(content_cols) == 0:
            return True
        top_bar = content_rows[0] / H
        bottom_bar = (H - 1 - content_rows[-1]) / H
        left_bar = content_cols[0] / W
        right_bar = (W - 1 - content_cols[-1]) / W
        return any(b > BLACK_BAR_THRESHOLD for b in [top_bar, bottom_bar, left_bar, right_bar])
    except Exception:
        return False


_FACE_CASCADE = None

def _get_face_cascade():
    global _FACE_CASCADE
    if _FACE_CASCADE is None:
        import cv2
        cascade_path = cv2.data.haarcascades + "haarcascade_frontalface_default.xml"
        _FACE_CASCADE = cv2.CascadeClassifier(cascade_path)
    return _FACE_CASCADE


def _count_faces(img: Image.Image) -> int:
    """Return number of faces detected. 0 = no face, 1 = solo, 2+ = group."""
    try:
        import cv2
        import numpy as np
        thumb = img.convert("RGB").resize((640, 360), Image.LANCZOS)
        gray = cv2.cvtColor(np.array(thumb), cv2.COLOR_RGB2GRAY)
        cascade = _get_face_cascade()
        faces = cascade.detectMultiScale(
            gray,
            scaleFactor=1.1,
            minNeighbors=4,
            minSize=(30, 30),
        )
        return len(faces)
    except Exception:
        return 1  # if detection fails, assume solo and allow


def _has_face(img: Image.Image) -> bool:
    return _count_faces(img) > 0


def _passes_quality(img: Image.Image) -> tuple[bool, str]:
    """Return (ok, reason). Filters out low-res, ultra-portrait, black-bar, no-face, and group images."""
    w, h = img.size
    if w < MIN_W or h < MIN_H:
        return False, f"too small ({w}x{h})"
    if w / h < 0.5:
        return False, f"too portrait ({w}x{h})"
    if _detect_black_bars(img):
        return False, "black bars detected"
    n = _count_faces(img)
    if n == 0:
        return False, "no face detected (likely album art or flyer)"
    if n > 1:
        return False, f"group photo ({n} faces detected)"
    return True, "ok"


# ── Image search backends ──────────────────────────────────────────────────────

def _ddg_images(query: str, max_results: int = 60) -> list[str]:
    """DuckDuckGo Images — no API key. Uses ddgs package."""
    try:
        from ddgs import DDGS
        with DDGS() as ddgs:
            results = list(ddgs.images(query, max_results=max_results, size="Large"))
        return [r["image"] for r in results if "image" in r]
    except Exception:
        pass
    # Fallback to old package name
    try:
        from duckduckgo_search import DDGS as DDGS2
        with DDGS2() as ddgs:
            results = list(ddgs.images(query, max_results=max_results, size="Large"))
        return [r["image"] for r in results if "image" in r]
    except Exception as e:
        print(f"  [DDG] Failed: {e}")
        return []


def _bing_images(query: str, max_results: int = 60) -> list[str]:
    """Bing Image Search scraper — no API key required."""
    encoded = requests.utils.quote(query)
    url = f"https://www.bing.com/images/search?q={encoded}&form=HDRSC2&first=1&tsc=ImageHoverTitle"
    try:
        r = requests.get(url, headers=HEADERS, timeout=15)
        r.raise_for_status()
    except Exception as e:
        print(f"  [BING] Request failed: {e}")
        return []

    urls = []
    # Bing embeds image URLs in murl= params
    for m in re.finditer(r'murl&quot;:&quot;(https?://[^&"]+\.(?:jpg|jpeg|png))&quot;', r.text):
        urls.append(m.group(1))
    # Also try imgurl pattern
    for m in re.finditer(r'"imgurl":"(https?://[^"]+\.(?:jpg|jpeg|png))"', r.text):
        urls.append(m.group(1))

    seen = set()
    out = []
    for u in urls:
        if u not in seen:
            seen.add(u)
            out.append(u)
    return out[:max_results]


# ── SerpApi fallback ───────────────────────────────────────────────────────────

def _serpapi_images(query: str, api_key: str, max_results: int = 40) -> list[str]:
    """Use SerpApi Google Images endpoint for more reliable results."""
    params = {
        "engine": "google_images",
        "q": query,
        "api_key": api_key,
        "num": max_results,
        "tbs": "isz:l",  # large images only
    }
    try:
        r = requests.get("https://serpapi.com/search", params=params, timeout=20)
        r.raise_for_status()
        data = r.json()
        return [item["original"] for item in data.get("images_results", []) if "original" in item]
    except Exception as e:
        print(f"  [SERPAPI] Failed: {e}")
        return []


# ── Download + save ────────────────────────────────────────────────────────────

def _next_filename(folder: Path, prefix: str) -> Path:
    """Generate next sequential filename like press_42.jpg (re-scans each call)."""
    existing = list(folder.glob("*.jpg")) + list(folder.glob("*.jpeg")) + list(folder.glob("*.png"))
    nums = []
    for f in existing:
        m = re.search(r"(\d+)", f.stem)
        if m:
            nums.append(int(m.group(1)))
    next_num = (max(nums) + 1) if nums else 1
    # Ensure no collision (shouldn't happen but be safe)
    candidate = folder / f"{prefix}_{next_num}.jpg"
    while candidate.exists():
        next_num += 1
        candidate = folder / f"{prefix}_{next_num}.jpg"
    return candidate


def _url_domain(url: str) -> str:
    try:
        from urllib.parse import urlparse
        return urlparse(url).netloc.lower().lstrip("www.")
    except Exception:
        return ""


def _instagram_images(handle: str, max_results: int = 30) -> list[str]:
    """Search for photos from an artist's Instagram profile via DDG/Bing image search.

    Queries 'site:instagram.com @handle' to pull images that were posted by
    that specific account. Returns image URLs for the caller to download.
    No API key required.
    """
    queries = [
        f'site:instagram.com "{handle}" photo',
        f'"{handle}" instagram rapper photo',
    ]
    urls: list[str] = []
    seen: set[str] = set()
    for q in queries:
        for u in _ddg_images(q, max_results=max_results) + _bing_images(q, max_results=max_results):
            if u not in seen:
                seen.add(u)
                urls.append(u)
        if len(urls) >= max_results:
            break
    return urls[:max_results]


def fetch_for_artist(artist: str, target_count: int = 10, serpapi_key: str = "") -> int:
    """Download up to target_count new photos for the artist. Returns number saved."""
    cfg = ARTIST_CONFIG.get(artist)
    if not cfg:
        print(f"[ERROR] Unknown artist: {artist}")
        return 0

    folder = ARTIST_PHOTOS / cfg["folder"]
    folder.mkdir(parents=True, exist_ok=True)
    queries = cfg.get("queries", [])
    ig_handle = cfg.get("instagram", "")

    print(f"\n[{artist}]")
    print(f"  Folder: {folder}")

    # Count existing
    existing_photos = [f for f in folder.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png")]
    print(f"  Existing photos: {len(existing_photos)}")

    # Load existing hashes for dedup
    existing_hashes = _load_existing_hashes(folder)

    prefix = cfg["folder"].lower().replace(" ", "")
    saved = 0

    # ── Image search: IG-targeted queries first, then general web ────────────
    web_urls: list[str] = []
    seen_urls: set[str] = set()

    # IG-targeted queries (site:instagram.com) go first — higher chance of
    # finding actual artist photos vs press shots / album art
    if ig_handle:
        ig_queries = _instagram_images(ig_handle, max_results=60)
        for u in ig_queries:
            if u not in seen_urls:
                seen_urls.add(u)
                web_urls.append(u)

    # General press photo queries
    for query in queries:
        batch: list[str] = []
        if serpapi_key:
            batch = _serpapi_images(query, serpapi_key, max_results=40)
        if not batch:
            batch = _ddg_images(query, max_results=40)
        if not batch:
            batch = _bing_images(query, max_results=40)
        for u in batch:
            if u not in seen_urls:
                seen_urls.add(u)
                web_urls.append(u)

    if saved < target_count:
        need = target_count - saved
        print(f"  Need {need} more — searching ...")

        # Domain filter
        filtered_web = [u for u in web_urls if not any(d in _url_domain(u) for d in _SKIP_DOMAINS)]
        print(f"  Web candidates: {len(filtered_web)}")

        for url in filtered_web:
            if saved >= target_count:
                break
            try:
                resp = requests.get(url, headers=HEADERS, timeout=10, stream=True)
                resp.raise_for_status()
                img = Image.open(io.BytesIO(resp.content))
                if img.mode not in ("RGB",):
                    img = img.convert("RGB")

                ok, reason = _passes_quality(img)
                if not ok:
                    print(f"  [SKIP] {url[:70]}... — {reason}")
                    continue

                ph = _phash(img)
                if _is_duplicate(ph, existing_hashes):
                    print(f"  [DUP]  {url[:70]}...")
                    continue

                out_path = _next_filename(folder, f"{prefix}_press")
                img.save(str(out_path), "JPEG", quality=92)
                existing_hashes.append(ph)
                saved += 1
                print(f"  [SAVED] {out_path.name}  ({img.width}x{img.height})  [web]")
                time.sleep(0.3)
            except Exception as e:
                print(f"  [ERR]  {url[:60]}... — {e}")
                continue

    print(f"  → {saved} new photos saved for {artist}")
    return saved


def approve_for_artist(artist: str) -> int:
    """Move all remaining staged photos into the main artist folder."""
    cfg = ARTIST_CONFIG.get(artist)
    if not cfg:
        print(f"[ERROR] Unknown artist: {artist}")
        return 0

    folder = ARTIST_PHOTOS / cfg["folder"]
    staging = folder / "_staging"
    prefix = cfg["folder"].lower().replace(" ", "")

    if not staging.exists():
        print(f"  No staging folder found for {artist}")
        return 0

    candidates = sorted([f for f in staging.iterdir() if f.suffix.lower() in (".jpg", ".jpeg", ".png")])
    if not candidates:
        print(f"  No staged photos found for {artist}")
        return 0

    moved = 0
    for src in candidates:
        dst = _next_filename(folder, f"{prefix}_press")
        src.rename(dst)
        print(f"  [APPROVED] {src.name} → {dst.name}")
        moved += 1

    print(f"  → {moved} photos approved for {artist}")
    # Clean up empty staging dir
    try:
        staging.rmdir()
    except Exception:
        pass
    return moved


# ── CLI ────────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Fetch fresh press photos for beat thumbnails")
    parser.add_argument("--artist", help="Artist name (e.g. 'Glokk40Spazz')")
    parser.add_argument("--all", action="store_true", help="Top up all configured artists")
    parser.add_argument("--count", type=int, default=10, help="Target number of new photos to download")
    parser.add_argument("--approve", metavar="ARTIST", help="Move staged photos into main folder for artist")
    args = parser.parse_args()

    # Load SERPAPI_KEY from env or .env file
    serpapi_key = os.environ.get("SERPAPI_KEY", "")
    env_file = ROOT / ".env"
    if not serpapi_key and env_file.exists():
        for line in env_file.read_text().splitlines():
            if line.startswith("SERPAPI_KEY="):
                serpapi_key = line.split("=", 1)[1].strip().strip('"')
                break

    if serpapi_key:
        print("[INFO] Using SerpApi for image search")
    else:
        print("[INFO] Using DuckDuckGo Images (no API key needed)")

    if args.approve:
        approve_for_artist(args.approve)
    elif args.all:
        total = 0
        for artist in ARTIST_CONFIG:
            total += fetch_for_artist(artist, args.count, serpapi_key)
        print(f"\nTotal candidates staged: {total}")
    elif args.artist:
        fetch_for_artist(args.artist, args.count, serpapi_key)
    else:
        parser.print_help()


if __name__ == "__main__":
    main()
