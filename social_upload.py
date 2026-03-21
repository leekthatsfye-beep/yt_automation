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

ROOT      = Path(__file__).resolve().parent
OUT_DIR   = ROOT / "output"
META_DIR  = ROOT / "metadata"
BRAND_DIR = ROOT / "brand"
STORE_LOG = ROOT / "store_uploads_log.json"
LANES_CFG = ROOT / "lanes_config.json"


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


# ── Video conversion: landscape → portrait (9:16) ────────────────────────────

# Platform duration limits (seconds).  IG is strictest → use as universal trim.
PLATFORM_MAX_DURATION = {
    "instagram": 90,
    "tiktok": 600,
    "youtube_shorts": 180,
}
# Trim point — 1s buffer under IG limit for codec padding.
SOCIAL_MAX_DURATION = 89

# Always compress social videos for fast upload.  IG's resumable upload
# silently rejects files > ~20 MB (returns ProcessingFailedError 400).
# Social platforms re-encode anyway so visual quality loss is negligible.
SOCIAL_TARGET_SIZE_MB = 50  # compress when portrait would exceed this size (MB)
# Social platforms re-encode anyway, so quality loss from compression is negligible.
# IG video_url approach (via main tunnel) has no size limit.
# Resumable upload fallback has ~10 MB undocumented limit — video_url is primary.

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


def convert_to_portrait(
    stem: str,
    force: bool = False,
    progress_cb: "Callable[[float], None] | None" = None,
) -> Path:
    """
    Convert a 1920x1080 landscape video to 1080x1920 portrait using
    downscale/upscale blur + centered overlay.

    Uses fast scale-down/up trick instead of boxblur for ~10x speedup.
    Optionally reports real-time progress via progress_cb(pct: 0-100).

    Returns path to the 9:16 file: output/{stem}_9x16.mp4
    Idempotent: skips if output exists unless force=True.
    """
    src = OUT_DIR / f"{stem}.mp4"
    dst = OUT_DIR / f"{stem}_9x16.mp4"

    if not src.exists():
        raise FileNotFoundError(f"Source video not found: {src}")

    if dst.exists() and not force:
        log.info("[SKIP] 9x16 already exists: %s", dst.name)
        if progress_cb:
            progress_cb(100.0)
        return dst

    W, H = 1080, 1920
    # Fast blur: scale down to 1/8 then back up (10x faster than boxblur)
    BW, BH = W // 8, H // 8  # 135 × 240
    has_spin = SPIN_LOGO.exists()

    # ── Trim + compress decisions ──────────────────────────────────────
    src_duration = _get_duration(src)
    src_size_mb = src.stat().st_size / (1024 * 1024)

    # Trim if over the social max (89s — safe for all platforms including IG)
    needs_trim = src_duration > SOCIAL_MAX_DURATION
    trim_to = SOCIAL_MAX_DURATION if needs_trim else 0
    effective_duration = trim_to if needs_trim else src_duration

    # Compress if source is large
    needs_compress = src_size_mb > SOCIAL_TARGET_SIZE_MB

    log.info(
        "Portrait prep: %.1fs (%.1f MB), trim=%s, compress=%s",
        src_duration, src_size_mb,
        f"{trim_to}s" if needs_trim else "no",
        "yes" if needs_compress else "no",
    )

    # Audio filter: fade-out if trimming, passthrough otherwise
    fade_dur = 3
    af_filter = (
        f"afade=t=out:st={trim_to - fade_dur}:d={fade_dur}"
        if needs_trim else ""
    )

    # Pick encoding quality
    if needs_compress:
        v_preset, v_crf = "medium", "24"
        v_extra = ["-maxrate", "4M", "-bufsize", "8M"]
        a_bitrate = "128k"
    else:
        v_preset, v_crf = "fast", "20"
        v_extra = []
        a_bitrate = "192k"

    # Audio fade must go inside -filter_complex (can't mix -af with -filter_complex)
    audio_chain = f"[0:a]{af_filter}[aout]" if af_filter else ""

    if has_spin:
        bg_filter = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},scale={BW}:{BH},scale={W}:{H},"
            f"format=yuv420p[bg]"
        )
        fg_filter = f"[0:v]scale={W}:-2,format=yuva420p[fg]"
        ov_filter = "[bg][fg]overlay=(W-w)/2:(H-h)/2[comp]"
        spin_filter = "[comp][1:v]overlay=(W-w)/2:H-h-20,format=yuv420p[out]"
        vf = f"{bg_filter};{fg_filter};{ov_filter};{spin_filter}"
        if audio_chain:
            vf = f"{vf};{audio_chain}"
        audio_map = "[aout]" if af_filter else "0:a:0"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(src),
            "-stream_loop", "-1", "-i", str(SPIN_LOGO),
            "-filter_complex", vf,
            "-map", "[out]", "-map", audio_map,
            "-r", "30",
            "-c:v", "libx264", "-preset", v_preset, "-crf", v_crf,
            *v_extra,
            "-threads", "0",
            "-c:a", "aac", "-b:a", a_bitrate,
            "-movflags", "+faststart",
            "-shortest",
        ]
    else:
        bg_filter = (
            f"[0:v]scale={W}:{H}:force_original_aspect_ratio=increase,"
            f"crop={W}:{H},scale={BW}:{BH},scale={W}:{H},"
            f"format=yuv420p[bg]"
        )
        fg_filter = f"[0:v]scale={W}:-2,format=yuv420p[fg]"
        ov_filter = "[bg][fg]overlay=(W-w)/2:(H-h)/2,format=yuv420p[out]"
        vf = f"{bg_filter};{fg_filter};{ov_filter}"
        if audio_chain:
            vf = f"{vf};{audio_chain}"
        audio_map = "[aout]" if af_filter else "0:a:0"
        cmd = [
            "ffmpeg", "-y",
            "-i", str(src),
            "-filter_complex", vf,
            "-map", "[out]", "-map", audio_map,
            "-r", "30",
            "-c:v", "libx264", "-preset", v_preset, "-crf", v_crf,
            *v_extra,
            "-threads", "0",
            "-c:a", "aac", "-b:a", a_bitrate,
            "-movflags", "+faststart",
        ]

    # Trim to social max duration
    if needs_trim:
        cmd.extend(["-t", str(trim_to)])

    # Add progress reporting and output path
    cmd.extend(["-progress", "pipe:1", str(dst)])

    log.info("Converting to portrait: %s → %s", src.name, dst.name)
    duration = _get_duration(src)

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
) -> dict:
    """
    Upload a portrait (9:16) video as a YouTube Short.

    Expects output/{stem}_9x16.mp4 to already exist (bot converts beforehand).
    Duration must be ≤180s for Shorts eligibility (YouTube allows up to 3 min since Oct 2024).

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

    raw_desc = meta.get("description", "") or ""
    # Auto-replace old description formats with real store link
    if "AIRBIT_LINK_HERE" in raw_desc or "[Link in bio]" in raw_desc or "Listen freely" in raw_desc:
        raw_desc = _build_purchase_desc(stem)
    yt_desc = f"{raw_desc}\n\n#Shorts #TypeBeat".strip()[:5000]

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

    body = {
        "snippet": {
            "title": yt_title,
            "description": yt_desc,
            "tags": yt_tags,
            "categoryId": SHORTS_CATEGORY_MUSIC,
        },
        "status": {
            "privacyStatus": privacy if privacy in ("public", "unlisted", "private") else "public",
            "selfDeclaredMadeForKids": False,
        },
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
