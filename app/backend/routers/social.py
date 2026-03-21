"""
/api/social — Instagram, TikTok & YouTube Shorts upload endpoints (admin only).
Wraps social_upload.py (ig_upload, tiktok_upload, youtube_shorts_upload).

Uploads run as background tasks and stream progress via WebSocket.
The POST returns immediately with a task_id — no more proxy timeouts.

Also includes /auth/* endpoints for self-service platform connection management.
"""

from __future__ import annotations

import asyncio
import json
import logging
import sys
import threading
from typing import Optional, Any

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.config import ROOT, OUTPUT_DIR, SOCIAL_LOG
from app.backend.deps import require_admin, UserContext, get_user_paths
from app.backend.services.beat_svc import get_beat
from app.backend.services import compress_svc
from app.backend.ws import manager, tracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/social", tags=["social"])


class SocialPostRequest(BaseModel):
    caption: Optional[str] = None
    privacy: Optional[str] = "unlisted"  # YouTube Shorts privacy


class AuthCodeRequest(BaseModel):
    code: str


class SchedulePostRequest(BaseModel):
    stem: str
    platforms: list[str]  # ["instagram", "tiktok", "youtube_shorts"]
    caption: Optional[str] = None
    privacy: str = "public"
    scheduled_at: str  # ISO datetime string


# ── Auth state (module-level, single-user app) ──────────────────────────
_yt_auth_active = False


# ── Background upload helpers ─────────────────────────────────────────


async def _run_ig_upload(
    stem: str, caption: str | None, task_id: str, user: UserContext
):
    """Background task: upload to Instagram and broadcast progress via WS."""
    await manager.send_progress(
        task_id, "ig_upload", 0, "Starting Instagram upload...", username=user.username
    )

    progress: dict = {}

    def _do_ig():
        import sys

        sys.path.insert(0, str(ROOT))
        from social_upload import ig_upload

        return ig_upload(stem=stem, caption=caption, progress=progress)

    try:

        async def _track():
            last_pct = -1
            while True:
                await asyncio.sleep(1)
                pct = progress.get("pct", 0)
                phase = progress.get("phase", "")
                detail = progress.get("detail", "")
                if pct != last_pct:
                    tracker.update(task_id, pct, detail)
                    await manager.send_progress(
                        task_id,
                        "ig_upload",
                        pct,
                        detail,
                        username=user.username,
                    )
                    last_pct = pct
                if phase in ("done", "error"):
                    break

        track_task = asyncio.create_task(_track())

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _do_ig)

        track_task.cancel()
        try:
            await track_task
        except asyncio.CancelledError:
            pass

    except Exception as e:
        logger.error("Instagram upload failed for %s: %s", stem, e)
        tracker.fail(task_id, str(e)[:200])
        await manager.send_progress(
            task_id,
            "ig_upload",
            0,
            f"Error: {str(e)[:200]}",
            username=user.username,
        )
        return

    status = result.get("status", "unknown")
    if status == "error":
        error_msg = result.get("error", "Unknown error")
        tracker.fail(task_id, error_msg[:200])
        await manager.send_progress(
            task_id,
            "ig_upload",
            0,
            f"Error: {error_msg[:200]}",
            username=user.username,
        )
        return

    tracker.complete(task_id)
    await manager.send_progress(
        task_id,
        "ig_upload",
        100,
        "Instagram upload complete!",
        username=user.username,
    )


async def _run_tiktok_upload(
    stem: str, caption: str | None, task_id: str, user: UserContext
):
    """Background task: upload to TikTok and broadcast progress via WS."""
    await manager.send_progress(
        task_id,
        "tiktok_upload",
        0,
        "Starting TikTok upload...",
        username=user.username,
    )

    progress: dict = {}

    def _do_tiktok():
        import sys

        sys.path.insert(0, str(ROOT))
        from social_upload import tiktok_upload

        return tiktok_upload(stem=stem, caption=caption, progress=progress)

    try:

        async def _track():
            last_pct = -1
            while True:
                await asyncio.sleep(1)
                pct = progress.get("pct", 0)
                phase = progress.get("phase", "")
                detail = progress.get("detail", "")
                if pct != last_pct:
                    tracker.update(task_id, pct, detail)
                    await manager.send_progress(
                        task_id,
                        "tiktok_upload",
                        pct,
                        detail,
                        username=user.username,
                    )
                    last_pct = pct
                if phase in ("done", "failed"):
                    break

        track_task = asyncio.create_task(_track())

        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _do_tiktok)

        track_task.cancel()
        try:
            await track_task
        except asyncio.CancelledError:
            pass

    except Exception as e:
        logger.error("TikTok upload failed for %s: %s", stem, e)
        tracker.fail(task_id, str(e)[:200])
        await manager.send_progress(
            task_id,
            "tiktok_upload",
            0,
            f"Error: {str(e)[:200]}",
            username=user.username,
        )
        return

    status = result.get("status", "unknown")
    if status in ("error", "failed"):
        error_msg = result.get("error", "Unknown error")
        tracker.fail(task_id, error_msg[:200])
        await manager.send_progress(
            task_id,
            "tiktok_upload",
            0,
            f"Error: {error_msg[:200]}",
            username=user.username,
        )
        return

    tracker.complete(task_id)
    await manager.send_progress(
        task_id,
        "tiktok_upload",
        100,
        "TikTok upload complete!",
        username=user.username,
    )


# ── Endpoints ─────────────────────────────────────────────────────────


@router.post("/ig/{stem}")
async def post_to_instagram(
    stem: str,
    req: SocialPostRequest,
    user: UserContext = Depends(require_admin),
):
    """
    Start an Instagram Reel upload in the background.
    Returns immediately with a task_id; progress streams via WebSocket.
    """
    paths = get_user_paths(user)
    beat = get_beat(
        stem,
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )
    if beat is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")

    if not beat["rendered"]:
        raise HTTPException(
            status_code=400,
            detail=f"Beat '{stem}' has not been rendered yet",
        )

    video_path = paths.output_dir / f"{stem}.mp4"
    if not video_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Rendered video not found: {stem}.mp4",
        )

    task_id = tracker.create(stem, "social", f"IG: {beat.get('title', stem)}")
    asyncio.create_task(_run_ig_upload(stem, req.caption, task_id, user))

    return {
        "status": "started",
        "task_id": task_id,
        "stem": stem,
        "platform": "instagram",
        "message": f"Instagram upload started for {stem}",
    }


@router.post("/tiktok/{stem}")
async def post_to_tiktok(
    stem: str,
    req: SocialPostRequest,
    user: UserContext = Depends(require_admin),
):
    """
    Start a TikTok upload in the background.
    Returns immediately with a task_id; progress streams via WebSocket.
    """
    paths = get_user_paths(user)
    beat = get_beat(
        stem,
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )
    if beat is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")

    if not beat["rendered"]:
        raise HTTPException(
            status_code=400,
            detail=f"Beat '{stem}' has not been rendered yet",
        )

    video_path = paths.output_dir / f"{stem}.mp4"
    if not video_path.exists():
        raise HTTPException(
            status_code=400,
            detail=f"Rendered video not found: {stem}.mp4",
        )

    task_id = tracker.create(stem, "social", f"TT: {beat.get('title', stem)}")
    asyncio.create_task(_run_tiktok_upload(stem, req.caption, task_id, user))

    return {
        "status": "started",
        "task_id": task_id,
        "stem": stem,
        "platform": "tiktok",
        "message": f"TikTok upload started for {stem}",
    }


# ── YouTube Shorts background upload ──────────────────────────────────


async def _run_shorts_upload(
    stem: str, privacy: str, task_id: str, user: UserContext
):
    """Background task: upload to YouTube Shorts and broadcast progress via WS."""
    await manager.send_progress(
        task_id, "shorts_upload", 0, "Starting YouTube Shorts upload...", username=user.username
    )

    progress: dict = {}

    def _do_shorts():
        import sys
        sys.path.insert(0, str(ROOT))
        from social_upload import youtube_shorts_upload
        return youtube_shorts_upload(stem=stem, privacy=privacy, progress=progress)

    try:
        async def _track():
            last_pct = -1
            while True:
                await asyncio.sleep(1)
                pct = progress.get("pct", 0)
                phase = progress.get("phase", "")
                detail = progress.get("detail", "")
                if pct != last_pct:
                    tracker.update(task_id, pct, detail)
                    await manager.send_progress(
                        task_id, "shorts_upload", pct, detail, username=user.username
                    )
                    last_pct = pct
                if phase in ("done", "failed"):
                    break

        track_task = asyncio.create_task(_track())
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _do_shorts)
        track_task.cancel()
        try:
            await track_task
        except asyncio.CancelledError:
            pass

    except Exception as e:
        logger.error("YouTube Shorts upload failed for %s: %s", stem, e)
        tracker.fail(task_id, str(e)[:200])
        await manager.send_progress(
            task_id, "shorts_upload", 0, f"Error: {str(e)[:200]}", username=user.username
        )
        return

    status = result.get("status", "unknown")
    if status == "error":
        error_msg = result.get("error", "Unknown error")
        tracker.fail(task_id, error_msg[:200])
        await manager.send_progress(
            task_id, "shorts_upload", 0, f"Error: {error_msg[:200]}", username=user.username
        )
        return

    tracker.complete(task_id)
    await manager.send_progress(
        task_id, "shorts_upload", 100, "YouTube Short published!", username=user.username
    )


@router.post("/shorts/{stem}")
async def post_to_youtube_shorts(
    stem: str,
    req: SocialPostRequest,
    user: UserContext = Depends(require_admin),
):
    """
    Start a YouTube Shorts upload in the background.
    Uses the 9:16 portrait video. Returns immediately with a task_id.
    """
    paths = get_user_paths(user)
    beat = get_beat(
        stem,
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )
    if beat is None:
        raise HTTPException(status_code=404, detail=f"Beat '{stem}' not found")

    if not beat["rendered"]:
        raise HTTPException(
            status_code=400,
            detail=f"Beat '{stem}' has not been rendered yet",
        )

    # Portrait conversion happens automatically inside youtube_shorts_upload()
    # No need to check for _9x16.mp4 here — it will be created on-the-fly

    privacy = req.privacy if req.privacy in ("public", "unlisted", "private") else "unlisted"
    task_id = tracker.create(stem, "social", f"YT Short: {beat.get('title', stem)}")
    asyncio.create_task(_run_shorts_upload(stem, privacy, task_id, user))

    return {
        "status": "started",
        "task_id": task_id,
        "stem": stem,
        "platform": "youtube_shorts",
        "message": f"YouTube Shorts upload started for {stem}",
    }


# ── TikTok video check ────────────────────────────────────────────────


@router.get("/tiktok-video/{stem}")
async def check_tiktok_video(
    stem: str,
    user: UserContext = Depends(require_admin),
):
    """
    Check if a 9:16 TikTok-ready video exists for a beat.
    Returns download URL and file size.
    """
    paths = get_user_paths(user)

    # Prefer 9x16 variant, fall back to standard video
    video_9x16 = paths.output_dir / f"{stem}_9x16.mp4"
    video_std = paths.output_dir / f"{stem}.mp4"

    if video_9x16.exists():
        size_mb = round(video_9x16.stat().st_size / (1024 * 1024), 1)
        return {
            "available": True,
            "format": "9x16",
            "filename": f"{stem}_9x16.mp4",
            "download_url": f"/files/download/output/{stem}_9x16.mp4",
            "size_mb": size_mb,
        }
    elif video_std.exists():
        size_mb = round(video_std.stat().st_size / (1024 * 1024), 1)
        return {
            "available": True,
            "format": "16x9",
            "filename": f"{stem}.mp4",
            "download_url": f"/files/download/output/{stem}.mp4",
            "size_mb": size_mb,
        }

    return {"available": False}


# ── History ───────────────────────────────────────────────────────────


# ── Social Schedule endpoints ──────────────────────────────────────────────


@router.get("/schedule")
async def get_schedule(user: UserContext = Depends(require_admin)):
    """Return all scheduled social posts."""
    from app.backend.services import social_schedule_svc
    return {"posts": social_schedule_svc.get_all(), "pending": social_schedule_svc.get_pending_count()}


@router.post("/schedule")
async def create_scheduled_post(
    req: SchedulePostRequest,
    user: UserContext = Depends(require_admin),
):
    """Schedule a social media post for a future time."""
    # Verify beat exists and is rendered
    paths = get_user_paths(user)
    beat = get_beat(
        req.stem,
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )
    if beat is None:
        raise HTTPException(status_code=404, detail=f"Beat '{req.stem}' not found")
    if not beat["rendered"]:
        raise HTTPException(status_code=400, detail=f"Beat '{req.stem}' must be rendered first")

    from app.backend.services import social_schedule_svc
    try:
        entry = social_schedule_svc.add(
            stem=req.stem,
            platforms=req.platforms,
            caption=req.caption,
            privacy=req.privacy,
            scheduled_at=req.scheduled_at,
            social_log_path=paths.social_log,
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))

    return {"status": "scheduled", "post": entry}


@router.delete("/schedule/{post_id}")
async def cancel_scheduled_post(
    post_id: str,
    user: UserContext = Depends(require_admin),
):
    """Cancel a pending scheduled post."""
    from app.backend.services import social_schedule_svc
    if social_schedule_svc.cancel(post_id):
        return {"status": "cancelled", "id": post_id}
    raise HTTPException(status_code=404, detail="Post not found or not cancellable")


@router.get("/history")
async def get_social_history(user: UserContext = Depends(require_admin)):
    """
    Return all social media uploads from social_uploads_log.json.
    Admin only.
    """
    paths = get_user_paths(user)
    posts: list[dict[str, Any]] = []
    try:
        if paths.social_log.exists():
            log = json.loads(paths.social_log.read_text())
            for stem, platforms in log.items():
                if not isinstance(platforms, dict):
                    continue
                for platform, data in platforms.items():
                    if not isinstance(data, dict):
                        continue
                    posts.append({
                        "id": f"{stem}_{platform}",
                        "stem": stem,
                        "platform": platform,
                        "status": data.get("status", "ok"),
                        "uploadedAt": data.get("uploadedAt", ""),
                        "media_id": data.get("media_id"),
                        "publish_id": data.get("publish_id"),
                        "videoId": data.get("videoId"),
                        "url": data.get("url"),
                    })
            posts.sort(key=lambda x: x.get("uploadedAt", ""), reverse=True)
    except Exception as e:
        logger.error("Failed to read social uploads log: %s", e)

    return {"posts": posts, "count": len(posts)}


# ── Auth Management ──────────────────────────────────────────────────────
# Self-service platform connection: producers connect once, tokens auto-refresh.
# If a token is revoked or expires beyond recovery, the UI shows "Reconnect".


def _check_auth_status() -> dict[str, Any]:
    """
    Check live auth status for YouTube, Instagram, and TikTok.
    Runs synchronously (called via run_in_executor).
    Attempts auto-refresh for expired tokens before reporting disconnected.
    """
    sys.path.insert(0, str(ROOT))
    result: dict[str, Any] = {}

    # ── YouTube ──
    yt_token_file = ROOT / "token.json"
    try:
        if yt_token_file.exists():
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request

            scopes = [
                "https://www.googleapis.com/auth/youtube",
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.readonly",
            ]
            creds = Credentials.from_authorized_user_file(str(yt_token_file), scopes)
            if creds.valid:
                result["youtube"] = {
                    "connected": True,
                    "detail": "Connected",
                    "needs_reconnect": False,
                }
            elif creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    yt_token_file.write_text(creds.to_json())
                    result["youtube"] = {
                        "connected": True,
                        "detail": "Token auto-refreshed",
                        "needs_reconnect": False,
                    }
                except Exception:
                    result["youtube"] = {
                        "connected": False,
                        "detail": "Token expired — reconnect required",
                        "needs_reconnect": True,
                    }
            else:
                result["youtube"] = {
                    "connected": False,
                    "detail": "Token invalid — reconnect required",
                    "needs_reconnect": True,
                }
        else:
            result["youtube"] = {
                "connected": False,
                "detail": "Not connected",
                "needs_reconnect": True,
            }
    except Exception as e:
        result["youtube"] = {
            "connected": False,
            "detail": f"Error: {str(e)[:80]}",
            "needs_reconnect": True,
        }

    # ── Instagram ──
    try:
        from ig_auth import is_token_valid as ig_valid, load_token as ig_load

        ig_tok = ig_load()
        if ig_tok and ig_valid():
            result["instagram"] = {
                "connected": True,
                "detail": "Connected",
                "needs_reconnect": False,
            }
        elif ig_tok and ig_tok.get("access_token"):
            # Try auto-refresh
            try:
                from ig_auth import refresh_long_token

                refresh_long_token()
                result["instagram"] = {
                    "connected": True,
                    "detail": "Token auto-refreshed",
                    "needs_reconnect": False,
                }
            except Exception:
                result["instagram"] = {
                    "connected": False,
                    "detail": "Token expired — reconnect required",
                    "needs_reconnect": True,
                }
        else:
            result["instagram"] = {
                "connected": False,
                "detail": "Not connected",
                "needs_reconnect": True,
            }
    except Exception as e:
        err = str(e)
        if "IG_APP_ID" in err or "IG_APP_SECRET" in err:
            result["instagram"] = {
                "connected": False,
                "detail": "API keys not configured in .env",
                "needs_reconnect": True,
            }
        else:
            result["instagram"] = {
                "connected": False,
                "detail": f"Error: {err[:80]}",
                "needs_reconnect": True,
            }

    # ── TikTok ──
    try:
        from tiktok_auth import (
            is_token_valid as tt_valid,
            load_token as tt_load,
        )

        tt_tok = tt_load()
        if tt_tok and tt_valid():
            result["tiktok"] = {
                "connected": True,
                "detail": "Connected",
                "needs_reconnect": False,
            }
        elif tt_tok and tt_tok.get("refresh_token"):
            try:
                from tiktok_auth import refresh_access_token as tt_refresh

                tt_refresh()
                result["tiktok"] = {
                    "connected": True,
                    "detail": "Token auto-refreshed",
                    "needs_reconnect": False,
                }
            except Exception:
                result["tiktok"] = {
                    "connected": False,
                    "detail": "Token expired — reconnect required",
                    "needs_reconnect": True,
                }
        else:
            result["tiktok"] = {
                "connected": False,
                "detail": "Not connected",
                "needs_reconnect": True,
            }
    except Exception as e:
        err = str(e)
        if "TIKTOK_CLIENT_KEY" in err or "TIKTOK_CLIENT_SECRET" in err:
            result["tiktok"] = {
                "connected": False,
                "detail": "API keys not configured in .env",
                "needs_reconnect": True,
            }
        else:
            result["tiktok"] = {
                "connected": False,
                "detail": f"Error: {err[:80]}",
                "needs_reconnect": True,
            }

    return result


@router.get("/auth/status")
async def auth_status(user: UserContext = Depends(require_admin)):
    """
    Check authentication status for all social platforms.
    Auto-refreshes tokens when possible. Returns needs_reconnect=true
    when manual re-authorization is required.
    """
    loop = asyncio.get_event_loop()
    return await loop.run_in_executor(None, _check_auth_status)


# ── YouTube Connect ──────────────────────────────────────────────────────


@router.post("/auth/youtube/connect")
async def youtube_connect(user: UserContext = Depends(require_admin)):
    """
    Start YouTube OAuth flow. Opens a browser window for Google sign-in.
    The flow handles its own callback on a random localhost port.
    Token is saved automatically on completion.
    """
    global _yt_auth_active

    if _yt_auth_active:
        return {
            "status": "active",
            "message": "YouTube sign-in already in progress. Check your browser.",
        }

    client_secret = ROOT / "client_secret.json"
    yt_token = ROOT / "token.json"

    if not client_secret.exists():
        raise HTTPException(
            400,
            "Missing client_secret.json — download from Google Cloud Console "
            "> APIs & Services > Credentials > OAuth 2.0 Client IDs",
        )

    # Remove old token to force fresh consent
    if yt_token.exists():
        yt_token.unlink()
        logger.info("Removed old YouTube token for fresh auth")

    def _do_yt_auth():
        global _yt_auth_active
        _yt_auth_active = True
        try:
            sys.path.insert(0, str(ROOT))
            from google_auth_oauthlib.flow import InstalledAppFlow

            scopes = [
                "https://www.googleapis.com/auth/youtube",
                "https://www.googleapis.com/auth/youtube.upload",
                "https://www.googleapis.com/auth/youtube.readonly",
            ]
            flow = InstalledAppFlow.from_client_secrets_file(
                str(client_secret), scopes
            )
            creds = flow.run_local_server(
                port=0, open_browser=True, timeout_seconds=300
            )
            yt_token.write_text(creds.to_json())
            logger.info("YouTube OAuth completed successfully")
        except Exception as e:
            logger.error("YouTube OAuth failed: %s", e)
        finally:
            _yt_auth_active = False

    threading.Thread(target=_do_yt_auth, daemon=True).start()

    return {
        "status": "started",
        "message": (
            "Google sign-in opened in your browser. "
            "Complete the authorization, then come back here."
        ),
    }


# ── Instagram Connect ────────────────────────────────────────────────────


@router.get("/auth/instagram/url")
async def instagram_auth_url(user: UserContext = Depends(require_admin)):
    """Get the Facebook/Instagram OAuth authorization URL."""
    sys.path.insert(0, str(ROOT))
    try:
        from ig_auth import get_auth_url

        return {"auth_url": get_auth_url()}
    except Exception as e:
        raise HTTPException(400, f"Failed to generate IG auth URL: {str(e)[:200]}")


@router.post("/auth/instagram/exchange")
async def instagram_exchange(
    req: AuthCodeRequest, user: UserContext = Depends(require_admin)
):
    """Exchange Instagram/Facebook authorization code for access token."""
    sys.path.insert(0, str(ROOT))

    def _do_exchange():
        from ig_auth import exchange_code

        return exchange_code(req.code.strip())

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _do_exchange)
        return {
            "status": "connected",
            "ig_user_id": result.get("ig_user_id"),
            "detail": "Instagram connected successfully",
        }
    except Exception as e:
        raise HTTPException(400, f"Instagram auth failed: {str(e)[:200]}")


# ── TikTok Connect ───────────────────────────────────────────────────────


@router.get("/auth/tiktok/url")
async def tiktok_auth_url(user: UserContext = Depends(require_admin)):
    """Get the TikTok OAuth authorization URL."""
    sys.path.insert(0, str(ROOT))
    try:
        from tiktok_auth import get_auth_url

        return {"auth_url": get_auth_url()}
    except Exception as e:
        raise HTTPException(400, f"Failed to generate TikTok auth URL: {str(e)[:200]}")


@router.post("/auth/tiktok/exchange")
async def tiktok_exchange(
    req: AuthCodeRequest, user: UserContext = Depends(require_admin)
):
    """Exchange TikTok authorization code for access token."""
    sys.path.insert(0, str(ROOT))

    def _do_exchange():
        from tiktok_auth import exchange_code

        return exchange_code(req.code.strip())

    try:
        loop = asyncio.get_event_loop()
        result = await loop.run_in_executor(None, _do_exchange)
        return {
            "status": "connected",
            "open_id": result.get("open_id"),
            "detail": "TikTok connected successfully",
        }
    except Exception as e:
        raise HTTPException(400, f"TikTok auth failed: {str(e)[:200]}")
