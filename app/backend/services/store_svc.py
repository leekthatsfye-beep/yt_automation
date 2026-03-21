"""
Beat store service — manages Airbit & BeatStars credentials, per-beat listings,
and upload orchestration via platform adapters.

Credentials stored in app_settings.json (same pattern as Suno/Replicate keys).
Per-beat listings stored in listings/{stem}.json.
"""

from __future__ import annotations

import json
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.backend.config import APP_SETTINGS, LISTINGS_DIR
from app.backend.services.beat_svc import safe_stem

logger = logging.getLogger(__name__)

VALID_PLATFORMS = ("airbit", "beatstars")

DEFAULT_PRICING = {
    "basic_license": 29.99,
    "premium_license": 49.99,
    "exclusive_license": 299.99,
    "currency": "USD",
}

GENRES = [
    "Hip-Hop/Rap",
    "Trap",
    "R&B/Soul",
    "Pop",
    "EDM/Electronic",
    "Drill",
    "Lo-Fi",
    "Afrobeats",
    "Reggaeton",
    "Rock",
    "Jazz",
    "Gospel",
    "Country",
    "Other",
]

MOODS = [
    "Dark",
    "Chill",
    "Energetic",
    "Sad",
    "Happy",
    "Aggressive",
    "Melodic",
    "Bouncy",
    "Atmospheric",
    "Uplifting",
    "Emotional",
    "Hard",
]

KEYS = [
    "C Major", "C Minor", "C# Major", "C# Minor",
    "D Major", "D Minor", "D# Major", "D# Minor",
    "E Major", "E Minor",
    "F Major", "F Minor", "F# Major", "F# Minor",
    "G Major", "G Minor", "G# Major", "G# Minor",
    "A Major", "A Minor", "A# Major", "A# Minor",
    "B Major", "B Minor",
]


# ── Helpers ──────────────────────────────────────────────────────────────


def _load_json(path: Path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


# ── Credential Management ───────────────────────────────────────────────


def get_store_credentials(platform: str) -> dict[str, Any] | None:
    """Read store credentials from app_settings.json."""
    if platform not in VALID_PLATFORMS:
        return None
    data = _load_json(APP_SETTINGS)
    stores = data.get("stores", {})
    creds = stores.get(platform)
    if creds and (creds.get("api_key") or creds.get("email")):
        return creds
    return None


def save_store_credentials(platform: str, credentials: dict[str, str]) -> None:
    """Save store credentials to app_settings.json."""
    if platform not in VALID_PLATFORMS:
        raise ValueError(f"Invalid platform: {platform}")
    data = _load_json(APP_SETTINGS)
    if "stores" not in data:
        data["stores"] = {}
    data["stores"][platform] = {
        "email": credentials.get("email", ""),
        "api_key": credentials.get("api_key", ""),
        "store_url": credentials.get("store_url", ""),
        "connected_at": datetime.now(timezone.utc).isoformat(),
    }
    _save_json(APP_SETTINGS, data)
    logger.info("Store credentials saved for %s", platform)


def remove_store_credentials(platform: str) -> None:
    """Remove store credentials from app_settings.json."""
    if platform not in VALID_PLATFORMS:
        return
    data = _load_json(APP_SETTINGS)
    stores = data.get("stores", {})
    if platform in stores:
        del stores[platform]
        data["stores"] = stores
        _save_json(APP_SETTINGS, data)
        logger.info("Store credentials removed for %s", platform)


def get_default_pricing() -> dict[str, Any]:
    """Read default pricing from app_settings.json."""
    data = _load_json(APP_SETTINGS)
    stores = data.get("stores", {})
    return stores.get("default_pricing", dict(DEFAULT_PRICING))


def save_default_pricing(pricing: dict[str, Any]) -> None:
    """Save default pricing to app_settings.json."""
    data = _load_json(APP_SETTINGS)
    if "stores" not in data:
        data["stores"] = {}
    clean = {
        "basic_license": max(0, float(pricing.get("basic_license", 29.99))),
        "premium_license": max(0, float(pricing.get("premium_license", 49.99))),
        "exclusive_license": max(0, float(pricing.get("exclusive_license", 299.99))),
        "currency": str(pricing.get("currency", "USD"))[:3].upper(),
    }
    data["stores"]["default_pricing"] = clean
    _save_json(APP_SETTINGS, data)
    logger.info("Default pricing saved: %s", clean)


# ── Listing Management ───────────────────────────────────────────────────


def _empty_listing(stem: str) -> dict[str, Any]:
    """Return a blank listing scaffold."""
    return {
        "stem": stem,
        "title": stem.replace("_", " ").title(),
        "description": "",
        "tags": [],
        "bpm": 0,
        "key": "",
        "genre": "",
        "mood": "",
        "pricing": dict(DEFAULT_PRICING),
        "platforms": {
            "airbit": {"listed": False, "listing_id": None, "uploaded_at": None},
            "beatstars": {"listed": False, "listing_id": None, "uploaded_at": None},
        },
    }


def get_listing(listings_dir: Path, metadata_dir: Path, stem: str) -> dict[str, Any]:
    """Load listing for a stem, auto-populating from metadata if new."""
    listing_path = listings_dir / f"{stem}.json"
    if listing_path.exists():
        listing = _load_json(listing_path)
        listing["stem"] = stem
        return listing

    # Auto-populate from beat metadata
    listing = _empty_listing(stem)
    meta_path = metadata_dir / f"{stem}.json"
    if meta_path.exists():
        meta = _load_json(meta_path)
        if meta.get("title"):
            listing["title"] = meta["title"]
        if meta.get("tags"):
            listing["tags"] = meta["tags"]
        if meta.get("description"):
            listing["description"] = meta["description"]
        if meta.get("artist"):
            listing["artist"] = meta["artist"]

    # Apply default pricing
    pricing = get_default_pricing()
    listing["pricing"] = {
        "basic_license": pricing.get("basic_license", 29.99),
        "premium_license": pricing.get("premium_license", 49.99),
        "exclusive_license": pricing.get("exclusive_license", 299.99),
    }

    return listing


def save_listing(listings_dir: Path, stem: str, data: dict[str, Any]) -> dict[str, Any]:
    """Save listing data for a stem."""
    listings_dir.mkdir(parents=True, exist_ok=True)
    listing_path = listings_dir / f"{stem}.json"

    # Merge with existing if present
    existing = _load_json(listing_path) if listing_path.exists() else {}

    # Update fields
    for key in (
        "title", "description", "tags", "bpm", "key",
        "genre", "mood", "pricing", "platforms",
    ):
        if key in data:
            existing[key] = data[key]

    existing["stem"] = stem
    existing["updated_at"] = datetime.now(timezone.utc).isoformat()

    _save_json(listing_path, existing)
    return existing


def get_all_listings(
    listings_dir: Path,
    metadata_dir: Path,
    beats_dir: Path,
) -> list[dict[str, Any]]:
    """Get listings for all beats (creates auto-populated listings for new beats)."""
    # Collect all beat stems
    audio_files = list(beats_dir.glob("*.mp3")) + list(beats_dir.glob("*.wav"))
    all_stems = sorted({safe_stem(f.name) for f in audio_files})

    results = []
    for stem in all_stems:
        listing = get_listing(listings_dir, metadata_dir, stem)

        # Add beat file info
        audio_file = None
        for ext in ("mp3", "wav"):
            candidates = list(beats_dir.glob(f"*{ext}"))
            for f in candidates:
                if safe_stem(f.name) == stem:
                    audio_file = f
                    break
            if audio_file:
                break

        listing["filename"] = audio_file.name if audio_file else f"{stem}.mp3"
        listing["has_thumbnail"] = (
            (beats_dir.parent / "output" / f"{stem}_thumb.jpg").exists()
            or (beats_dir.parent / "images" / f"{stem}.jpg").exists()
        )

        results.append(listing)

    return results


def delete_listing(listings_dir: Path, stem: str) -> bool:
    """Delete a listing file."""
    listing_path = listings_dir / f"{stem}.json"
    if listing_path.exists():
        listing_path.unlink()
        return True
    return False


# ── Store Upload Log ────────────────────────────────────────────────────


def load_store_uploads(log_path: Path) -> dict[str, Any]:
    """Load the store uploads log, merging in airbit_uploads_log.json entries."""
    from app.backend.config import ROOT

    store_log = _load_json(log_path)

    # Merge entries from airbit_uploads_log.json (written by CLI script)
    airbit_log_path = ROOT / "airbit_uploads_log.json"
    airbit_log = _load_json(airbit_log_path)
    if airbit_log:
        changed = False
        for stem, info in airbit_log.items():
            if stem not in store_log:
                store_log[stem] = {}
            if "airbit" not in store_log[stem]:
                store_log[stem]["airbit"] = {
                    "listing_id": "",
                    "uploaded_at": info.get("uploadedAt", ""),
                    "url": "",
                }
                changed = True
        # Persist merged data so we don't re-merge every request
        if changed:
            _save_json(log_path, store_log)

    return store_log


def record_store_upload(
    log_path: Path,
    stem: str,
    platform: str,
    listing_id: str | None,
    url: str | None,
) -> None:
    """Record a successful upload to a store."""
    log = _load_json(log_path)
    if stem not in log:
        log[stem] = {}
    log[stem][platform] = {
        "listing_id": listing_id,
        "uploaded_at": datetime.now(timezone.utc).isoformat(),
        "url": url,
    }
    _save_json(log_path, log)
    logger.info("Store upload recorded: %s → %s", stem, platform)


# ── Platform Adapters ───────────────────────────────────────────────────
# Each adapter takes listing data + credentials and uploads to the platform.
# These are stubs that will be fleshed out as platform APIs are reverse-engineered
# or official access is granted.


async def upload_to_platform(
    platform: str,
    stem: str,
    listing: dict[str, Any],
    credentials: dict[str, Any],
    audio_path: Path,
    thumbnail_path: Path | None = None,
) -> dict[str, Any]:
    """Dispatch upload to the appropriate platform adapter."""
    if platform == "airbit":
        return await _upload_airbit(stem, listing, credentials, audio_path, thumbnail_path)
    elif platform == "beatstars":
        return await _upload_beatstars(stem, listing, credentials, audio_path, thumbnail_path)
    else:
        raise ValueError(f"Unknown platform: {platform}")


async def _upload_airbit(
    stem: str,
    listing: dict[str, Any],
    credentials: dict[str, Any],
    audio_path: Path,
    thumbnail_path: Path | None = None,
) -> dict[str, Any]:
    """
    Upload a beat to Airbit via Selenium automation (airbit_upload.py).

    Airbit has no public upload API — the old HTTP adapter returned 405.
    This calls the existing airbit_upload.py script which uses
    undetected_chromedriver to automate the web upload form.
    """
    import asyncio

    from app.backend.config import PYTHON, ROOT

    cmd = [str(PYTHON), str(ROOT / "airbit_upload.py"), "--only", stem]
    logger.info("Airbit upload: running %s", " ".join(cmd))

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ROOT),
        )

        stdout_bytes, stderr_bytes = await asyncio.wait_for(
            proc.communicate(), timeout=300,  # 5 min max per beat
        )
        output = stdout_bytes.decode(errors="replace")
        stderr_text = stderr_bytes.decode(errors="replace")

        logger.info("Airbit upload stdout (last 500 chars):\n%s", output[-500:])
        if stderr_text.strip():
            logger.warning("Airbit upload stderr:\n%s", stderr_text[-300:])

        if f"[DONE] {stem}" in output:
            return {
                "success": True,
                "listing_id": "",
                "url": "",
                "platform": "airbit",
            }
        else:
            # Parse failure reason from output
            error = "Upload did not complete"
            for line in output.splitlines():
                if "[FAIL]" in line:
                    error = line.strip()
                    break
            logger.error("Airbit upload failed for %s: %s", stem, error)
            return {
                "success": False,
                "error": error[:300],
                "platform": "airbit",
            }

    except asyncio.TimeoutError:
        logger.error("Airbit upload timed out for %s", stem)
        return {
            "success": False,
            "error": "Upload timed out (5 min limit)",
            "platform": "airbit",
        }
    except Exception as e:
        logger.error("Airbit upload error for %s: %s", stem, e)
        return {
            "success": False,
            "error": f"Upload failed: {str(e)[:200]}",
            "platform": "airbit",
        }


async def upload_airbit_bulk(
    stems: list[str],
    progress_callback=None,
) -> dict[str, dict[str, Any]]:
    """
    Upload multiple beats to Airbit in a single browser session.

    Uses airbit_upload.py --only "stem1,stem2,..." which opens Chrome once
    and uploads beats sequentially with rate limiting.

    Returns {stem: result_dict} for each stem.
    """
    import asyncio

    from app.backend.config import PYTHON, ROOT

    stems_str = ",".join(stems)
    cmd = [str(PYTHON), str(ROOT / "airbit_upload.py"), "--only", stems_str]
    logger.info("Airbit bulk upload: %d beats", len(stems))

    results: dict[str, dict[str, Any]] = {}

    try:
        proc = await asyncio.create_subprocess_exec(
            *cmd,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE,
            cwd=str(ROOT),
        )

        # Read stdout line-by-line for real-time progress
        while True:
            line_bytes = await proc.stdout.readline()
            if not line_bytes:
                break
            line = line_bytes.decode(errors="replace").strip()
            if not line:
                continue

            logger.info("airbit_upload: %s", line)

            # Parse progress signals
            if line.startswith("[UPLOAD] "):
                # Format: [UPLOAD] stem (idx/total)
                parts = line[9:].split(" (")
                current_stem = parts[0].strip()
                if progress_callback:
                    idx_info = parts[1].rstrip(")") if len(parts) > 1 else ""
                    await progress_callback(current_stem, "uploading", idx_info)

            elif line.startswith("[DONE] "):
                done_stem = line[7:].strip()
                results[done_stem] = {
                    "success": True,
                    "listing_id": "",
                    "url": "",
                    "platform": "airbit",
                }
                if progress_callback:
                    await progress_callback(done_stem, "done", "")

            elif line.startswith("[FAIL] "):
                fail_parts = line[7:].split(":", 1)
                fail_stem = fail_parts[0].strip()
                fail_reason = fail_parts[1].strip() if len(fail_parts) > 1 else "Upload failed"
                results[fail_stem] = {
                    "success": False,
                    "error": fail_reason[:300],
                    "platform": "airbit",
                }
                if progress_callback:
                    await progress_callback(fail_stem, "failed", fail_reason)

        await proc.wait()

        # Mark any stems that didn't get a result
        for stem in stems:
            if stem not in results:
                results[stem] = {
                    "success": False,
                    "error": "No result — browser may have crashed",
                    "platform": "airbit",
                }

    except Exception as e:
        logger.error("Airbit bulk upload error: %s", e, exc_info=True)
        for stem in stems:
            if stem not in results:
                results[stem] = {
                    "success": False,
                    "error": f"Bulk upload error: {str(e)[:200]}",
                    "platform": "airbit",
                }

    return results


async def _upload_beatstars(
    stem: str,
    listing: dict[str, Any],
    credentials: dict[str, Any],
    audio_path: Path,
    thumbnail_path: Path | None = None,
) -> dict[str, Any]:
    """
    Upload a beat to BeatStars.

    BeatStars has no official API. This adapter uses known internal endpoints
    discovered from community tools. When official API becomes available,
    update this function.
    """
    import aiohttp

    api_key = credentials.get("api_key", "")
    if not api_key:
        raise ValueError("BeatStars API key / session token not configured")

    # Build upload payload matching BeatStars' internal format
    form = aiohttp.FormData()
    form.add_field("name", listing.get("title", stem))
    form.add_field("description", listing.get("description", ""))
    form.add_field("bpm", str(listing.get("bpm", 0)))
    form.add_field("key", listing.get("key", ""))
    form.add_field("genre_name", listing.get("genre", ""))
    form.add_field("mood", listing.get("mood", ""))
    form.add_field("type", "beat")

    tags = listing.get("tags", [])
    if tags:
        for tag in tags[:10]:  # BeatStars limits tags
            form.add_field("tags[]", tag)

    pricing = listing.get("pricing", {})
    form.add_field("basic_price", str(pricing.get("basic_license", 29.99)))
    form.add_field("premium_price", str(pricing.get("premium_license", 49.99)))
    form.add_field("exclusive_price", str(pricing.get("exclusive_license", 299.99)))

    # Audio file
    form.add_field(
        "file",
        open(audio_path, "rb"),
        filename=audio_path.name,
        content_type="audio/mpeg",
    )

    # Thumbnail if available
    if thumbnail_path and thumbnail_path.exists():
        form.add_field(
            "artwork",
            open(thumbnail_path, "rb"),
            filename=thumbnail_path.name,
            content_type="image/jpeg",
        )

    headers = {
        "Authorization": f"Bearer {api_key}",
    }

    try:
        async with aiohttp.ClientSession() as session:
            async with session.post(
                "https://main.beatstars.com/api/v2/tracks",
                data=form,
                headers=headers,
                timeout=aiohttp.ClientTimeout(total=120),
            ) as resp:
                if resp.status in (200, 201):
                    result = await resp.json()
                    return {
                        "success": True,
                        "listing_id": str(result.get("id", result.get("track_id", ""))),
                        "url": result.get("url", result.get("track_url", "")),
                        "platform": "beatstars",
                    }
                else:
                    text = await resp.text()
                    logger.error("BeatStars upload failed (%d): %s", resp.status, text[:200])
                    return {
                        "success": False,
                        "error": f"BeatStars API returned {resp.status}",
                        "platform": "beatstars",
                    }
    except Exception as e:
        logger.error("BeatStars upload error: %s", e)
        return {
            "success": False,
            "error": f"Upload failed: {str(e)}",
            "platform": "beatstars",
        }
