"""
/api/status — Dashboard status endpoint.
/api/queue  — Pipeline queue state (active + pending + completed tasks).
"""

from __future__ import annotations

import json
import logging
import time
from typing import Any

from fastapi import APIRouter, Depends, HTTPException

from app.backend.config import ROOT
from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.services.beat_svc import safe_stem
from app.backend.ws import tracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api", tags=["system"])


def _load_json(path) -> dict[str, Any]:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        return {}
    return {}


@router.get("/status")
async def get_status(user: UserContext = Depends(get_current_user)):
    """
    Return dashboard-level counts:
    - total beats
    - rendered count
    - uploaded to YouTube count
    - uploaded to social count
    - pending renders
    - recent activity (last 5 YouTube uploads)
    """
    paths = get_user_paths(user)

    # Collect all beat stems
    audio_files = list(paths.beats_dir.glob("*.mp3")) + list(paths.beats_dir.glob("*.wav"))
    all_stems = {safe_stem(f.name) for f in audio_files}
    total = len(all_stems)

    # Rendered count
    rendered_stems = set()
    for stem in all_stems:
        if (paths.output_dir / f"{stem}.mp4").exists():
            rendered_stems.add(stem)
    rendered = len(rendered_stems)

    # YouTube uploads
    uploads_log = _load_json(paths.uploads_log)
    uploaded_yt = sum(1 for s in all_stems if s in uploads_log)

    # Social uploads
    social_log = _load_json(paths.social_log)
    uploaded_social = sum(1 for s in all_stems if s in social_log)

    # Pending renders = total beats minus rendered
    pending_renders = total - rendered

    # Recent activity: last 5 uploads sorted by uploadedAt descending
    recent: list[dict[str, Any]] = []
    for stem, entry in uploads_log.items():
        recent.append(
            {
                "stem": stem,
                "title": entry.get("title", stem),
                "videoId": entry.get("videoId"),
                "url": entry.get("url"),
                "uploadedAt": entry.get("uploadedAt"),
                "publishAt": entry.get("publishAt"),
            }
        )
    recent.sort(key=lambda x: x.get("uploadedAt", ""), reverse=True)
    recent = recent[:5]

    return {
        "total_beats": total,
        "rendered": rendered,
        "uploaded_yt": uploaded_yt,
        "uploaded_social": uploaded_social,
        "pending_renders": pending_renders,
        "recent_activity": recent,
    }


# ── Queue ────────────────────────────────────────────────────────────────

def _format_task(t: dict[str, Any]) -> dict[str, Any]:
    """Format a tracker task for the frontend."""
    started = t.get("startedAt")
    return {
        "id": t["id"],
        "type": t["type"],
        "stem": t.get("stem", ""),
        "title": t.get("title", t.get("stem", "")),
        "status": t["status"],
        "progress": t["progress"],
        "detail": t.get("detail", ""),
        "startedAt": (
            time.strftime("%Y-%m-%dT%H:%M:%SZ", time.gmtime(started))
            if started else None
        ),
    }


@router.get("/queue")
async def get_queue(user: UserContext = Depends(get_current_user)):
    """
    Return full queue state:
    - active: currently running tasks (from in-memory tracker)
    - pending: beats that still need render or upload (derived from filesystem)
    - completed: recently finished tasks (from in-memory tracker)
    """
    paths = get_user_paths(user)

    # Prune old completed tasks
    tracker.prune(max_age_hours=24)

    # Active tasks from tracker
    active = [_format_task(t) for t in tracker.get_active()]

    # Completed tasks from tracker
    completed = [_format_task(t) for t in tracker.get_completed(limit=20)]

    # Derive pending work from filesystem
    audio_files = list(paths.beats_dir.glob("*.mp3")) + list(paths.beats_dir.glob("*.wav"))
    all_stems = {safe_stem(f.name) for f in audio_files}

    # Stems currently being processed
    active_stems = {t["stem"] for t in tracker.get_active()}

    # Uploads log
    uploads_log = _load_json(paths.uploads_log)

    pending: list[dict[str, Any]] = []
    for stem in sorted(all_stems):
        if stem in active_stems:
            continue
        video_exists = (paths.output_dir / f"{stem}.mp4").exists()
        if not video_exists:
            pending.append({
                "id": f"pending_render_{stem}",
                "type": "render",
                "stem": stem,
                "title": stem.replace("_", " ").title(),
                "status": "queued",
                "progress": 0,
                "detail": "",
                "startedAt": None,
            })
        elif stem not in uploads_log:
            pending.append({
                "id": f"pending_upload_{stem}",
                "type": "upload",
                "stem": stem,
                "title": stem.replace("_", " ").title(),
                "status": "queued",
                "progress": 0,
                "detail": "",
                "startedAt": None,
            })

    return {
        "active": active,
        "pending": pending,
        "completed": completed,
    }


@router.delete("/queue/{task_id}")
async def cancel_task(task_id: str, user: UserContext = Depends(get_current_user)):
    """Cancel a running task."""
    if tracker.cancel(task_id):
        return {"status": "cancelled", "taskId": task_id}
    raise HTTPException(status_code=404, detail="Task not found or not running")


# ── Integrations ──────────────────────────────────────────────────────────

@router.get("/integrations/status")
async def get_integrations_status(user: UserContext = Depends(get_current_user)):
    """
    Check live connection status for YouTube, Instagram, TikTok, and Suno.
    For detailed social auth with reconnect flow, use /api/social/auth/status.
    """
    import sys
    sys.path.insert(0, str(ROOT))
    status: dict[str, Any] = {}

    # YouTube: validate token
    yt_token_file = ROOT / "token.json"
    try:
        if yt_token_file.exists():
            from google.oauth2.credentials import Credentials
            from google.auth.transport.requests import Request

            creds = Credentials.from_authorized_user_file(str(yt_token_file))
            if creds.valid:
                status["youtube"] = {"connected": True, "detail": "Connected"}
            elif creds.expired and creds.refresh_token:
                try:
                    creds.refresh(Request())
                    yt_token_file.write_text(creds.to_json())
                    status["youtube"] = {"connected": True, "detail": "Token refreshed"}
                except Exception:
                    status["youtube"] = {"connected": False, "detail": "Token expired"}
            else:
                status["youtube"] = {"connected": False, "detail": "Token invalid"}
        else:
            status["youtube"] = {"connected": False, "detail": "Not connected"}
    except Exception:
        status["youtube"] = {"connected": False, "detail": "Not connected"}

    # Instagram: check token validity
    try:
        from ig_auth import is_token_valid as ig_valid, load_token as ig_load

        ig_tok = ig_load()
        if ig_tok and ig_valid():
            status["instagram"] = {"connected": True, "detail": "Connected"}
        elif ig_tok and ig_tok.get("access_token"):
            status["instagram"] = {"connected": False, "detail": "Token expired"}
        else:
            status["instagram"] = {"connected": False, "detail": "Not connected"}
    except Exception:
        status["instagram"] = {"connected": False, "detail": "Not connected"}

    # TikTok: check token validity
    try:
        from tiktok_auth import is_token_valid as tt_valid, load_token as tt_load

        tt_tok = tt_load()
        if tt_tok and tt_valid():
            status["tiktok"] = {"connected": True, "detail": "Connected"}
        elif tt_tok and tt_tok.get("access_token"):
            status["tiktok"] = {"connected": False, "detail": "Token expired"}
        else:
            status["tiktok"] = {"connected": False, "detail": "Not connected"}
    except Exception:
        status["tiktok"] = {"connected": False, "detail": "Not connected"}

    # Suno: check if API key is configured
    from app.backend.services.suno_svc import get_api_key
    suno_key = get_api_key()
    status["suno"] = {
        "connected": bool(suno_key),
        "detail": "API key configured" if suno_key else "API key not set",
    }

    # Replicate (AI Thumbnails): check if API key is configured
    from app.backend.services.thumbnail_ai_svc import get_api_key as get_replicate_key
    replicate_key = get_replicate_key()
    status["replicate"] = {
        "connected": bool(replicate_key),
        "detail": "API key configured" if replicate_key else "API key not set",
    }

    # Airbit: check if store credentials are configured
    from app.backend.services.store_svc import get_store_credentials
    ab_creds = get_store_credentials("airbit")
    if ab_creds and ab_creds.get("api_key"):
        status["airbit"] = {
            "connected": True,
            "detail": ab_creds.get("store_url") or ab_creds.get("email", "Connected"),
        }
    else:
        status["airbit"] = {"connected": False, "detail": "Not connected"}

    # BeatStars: check if store credentials are configured
    bs_creds = get_store_credentials("beatstars")
    if bs_creds and bs_creds.get("api_key"):
        status["beatstars"] = {
            "connected": True,
            "detail": bs_creds.get("store_url") or bs_creds.get("email", "Connected"),
        }
    else:
        status["beatstars"] = {"connected": False, "detail": "Not connected"}

    return status


# ── Push Notifications ─────────────────────────────────────────────────


@router.get("/push/vapid-key")
async def get_vapid_key(user: UserContext = Depends(get_current_user)):
    """Return the VAPID public key for push subscription."""
    from app.backend.services.push_svc import get_vapid_public_key
    key = get_vapid_public_key()
    if not key:
        raise HTTPException(500, "VAPID keys not configured")
    return {"publicKey": key}


@router.post("/push/subscribe")
async def push_subscribe(
    subscription: dict,
    user: UserContext = Depends(get_current_user),
):
    """Register a push notification subscription."""
    from app.backend.services.push_svc import add_subscription
    is_new = add_subscription(subscription)
    return {"status": "subscribed", "new": is_new}


@router.post("/push/unsubscribe")
async def push_unsubscribe(
    body: dict,
    user: UserContext = Depends(get_current_user),
):
    """Remove a push notification subscription."""
    from app.backend.services.push_svc import remove_subscription
    endpoint = body.get("endpoint", "")
    removed = remove_subscription(endpoint)
    return {"status": "unsubscribed" if removed else "not_found"}


@router.post("/push/test")
async def push_test(user: UserContext = Depends(get_current_user)):
    """Send a test push notification."""
    from app.backend.services.push_svc import send_notification
    sent = await send_notification(
        title="FY3 Notifications",
        body="Push notifications are working!",
        tag="fy3-test",
        url="/",
    )
    return {"sent": sent}
