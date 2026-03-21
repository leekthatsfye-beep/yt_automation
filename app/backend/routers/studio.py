"""
/api/studio — Suno AI music generation endpoints.
"""

from __future__ import annotations

import asyncio
import json
import logging
import shutil
from pathlib import Path
from typing import Any

from fastapi import APIRouter, BackgroundTasks, Depends, HTTPException
from pydantic import BaseModel

from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.services.beat_svc import safe_stem
from app.backend.services.suno_svc import (
    SunoClient,
    SunoAPIError,
    SunoAuthError,
    SunoRateLimitError,
    get_api_key,
    save_api_key,
    download_track,
    load_projects,
    get_project,
    create_project,
    update_project,
    delete_project,
)
from app.backend.ws import manager

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/studio", tags=["studio"])


# ── Request / Response Models ─────────────────────────────────────────────


class GenerateRequest(BaseModel):
    prompt: str
    style: str = ""
    title: str = ""
    instrumental: bool = True
    model: str = "V4"


class ExtendRequest(BaseModel):
    audio_id: str
    prompt: str = ""
    style: str = ""
    title: str = ""
    continue_at: float = 0


class SaveToBeatsRequest(BaseModel):
    project_id: str
    track_index: int = 0
    filename: str = ""


class ApiKeyRequest(BaseModel):
    key: str


# ── Helper ────────────────────────────────────────────────────────────────


def _get_client() -> SunoClient:
    """Create a SunoClient with the stored API key."""
    key = get_api_key()
    if not key:
        raise HTTPException(
            status_code=400,
            detail="Suno API key not configured. Set it in Settings.",
        )
    return SunoClient(key)


async def _broadcast_studio(data: dict[str, Any], username: str | None = None) -> None:
    """Broadcast a studio event via WebSocket."""
    await manager.broadcast({"type": "studio", **data}, username=username)


# ── Endpoints ─────────────────────────────────────────────────────────────


@router.get("/api-key/status")
async def api_key_status(user: UserContext = Depends(get_current_user)):
    """Check if a Suno API key is configured (does not return the key)."""
    key = get_api_key()
    return {"configured": bool(key)}


@router.post("/api-key")
async def set_api_key(req: ApiKeyRequest, user: UserContext = Depends(get_current_user)):
    """Save the Suno API key to server-side storage."""
    if not req.key or len(req.key) < 10:
        raise HTTPException(status_code=400, detail="Invalid API key")
    save_api_key(req.key)
    return {"status": "saved", "message": "Suno API key saved successfully"}


@router.get("/status")
async def studio_status(user: UserContext = Depends(get_current_user)):
    """Check Suno connection by verifying credits."""
    key = get_api_key()
    if not key:
        return {"online": False, "detail": "API key not configured", "credits": None}

    try:
        client = SunoClient(key)
        credits = await client.get_credits()
        await client.close()
        return {
            "online": True,
            "detail": "Connected to Suno AI",
            "credits": credits.get("data"),
        }
    except SunoAuthError:
        return {"online": False, "detail": "Invalid API key", "credits": None}
    except Exception as e:
        return {"online": False, "detail": str(e), "credits": None}


@router.get("/credits")
async def studio_credits(user: UserContext = Depends(get_current_user)):
    """Get remaining Suno credits."""
    client = _get_client()
    try:
        result = await client.get_credits()
        await client.close()
        return result.get("data", result)
    except SunoAuthError:
        raise HTTPException(status_code=401, detail="Invalid Suno API key")
    except SunoAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.get("/projects")
async def list_studio_projects(user: UserContext = Depends(get_current_user)):
    """List all projects, newest first."""
    return {"projects": load_projects()}


@router.get("/projects/{project_id}")
async def get_studio_project(project_id: str, user: UserContext = Depends(get_current_user)):
    """Get a single project."""
    project = get_project(project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")
    return project


@router.delete("/projects/{project_id}")
async def delete_studio_project(project_id: str, user: UserContext = Depends(get_current_user)):
    """Delete a project and its local files."""
    if not delete_project(project_id):
        raise HTTPException(status_code=404, detail="Project not found")
    return {"status": "deleted", "project_id": project_id}


@router.post("/generate")
async def start_generation(
    req: GenerateRequest,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user),
):
    """
    Start Suno generation. Runs in background and returns immediately.
    """
    client = _get_client()
    paths = get_user_paths(user)
    username = user.username

    project = create_project(
        title=req.title,
        prompt=req.prompt,
        style=req.style,
        instrumental=req.instrumental,
        model=req.model,
    )
    project_id = project["id"]

    async def run_generation():
        try:
            update_project(project_id, {"status": "generating"})
            await _broadcast_studio({
                "project_id": project_id,
                "status": "generating",
                "progress": 0,
            }, username=username)

            result = await client.generate(
                prompt=req.prompt,
                style=req.style,
                title=req.title,
                instrumental=req.instrumental,
                model=req.model,
            )

            task_id = None
            if isinstance(result, dict):
                task_id = result.get("data", {}).get("taskId") or result.get("taskId")
            if not task_id:
                raise SunoAPIError(f"No task ID in response: {result}")

            update_project(project_id, {"suno_task_id": task_id})

            await _broadcast_studio({
                "project_id": project_id,
                "status": "generating",
                "progress": 10,
                "suno_task_id": task_id,
            }, username=username)

            tracks: list[dict[str, Any]] = []
            for attempt in range(60):
                await asyncio.sleep(5)

                try:
                    status_result = await client.check_status(task_id)
                except Exception as e:
                    logger.warning(f"Poll attempt {attempt} failed: {e}")
                    continue

                data = status_result.get("data", status_result)
                progress = min(10 + (attempt * 1.5), 90)
                await _broadcast_studio({
                    "project_id": project_id,
                    "status": "generating",
                    "progress": int(progress),
                }, username=username)

                records = []
                if isinstance(data, dict):
                    records = data.get("response", []) or data.get("records", [])
                    if isinstance(data.get("data"), list):
                        records = data["data"]
                elif isinstance(data, list):
                    records = data

                all_complete = True
                for record in records:
                    audio_url = record.get("audio_url") or record.get("audioUrl")
                    status_val = record.get("status", "")

                    if status_val == "streaming" or (not audio_url and status_val != "error"):
                        all_complete = False
                        continue

                    if audio_url and audio_url not in [t.get("audio_url") for t in tracks]:
                        suno_id = record.get("id", record.get("song_id", ""))
                        track_title = record.get("title", f"Track {len(tracks) + 1}")
                        duration = record.get("duration", 0)

                        tracks.append({
                            "suno_id": suno_id,
                            "audio_url": audio_url,
                            "local_path": "",
                            "duration": duration,
                            "title": track_title,
                        })

                if all_complete and tracks:
                    break

            if not tracks:
                update_project(project_id, {
                    "status": "failed",
                    "error": "Generation timed out or produced no audio",
                })
                await _broadcast_studio({
                    "project_id": project_id,
                    "status": "failed",
                    "error": "No audio produced",
                }, username=username)
                await client.close()
                return

            await _broadcast_studio({
                "project_id": project_id,
                "status": "downloading",
                "progress": 90,
            }, username=username)

            studio_dir = paths.studio_dir
            studio_dir.mkdir(parents=True, exist_ok=True)

            for i, track in enumerate(tracks):
                audio_url = track["audio_url"]
                if not audio_url:
                    continue

                suno_id = track["suno_id"] or f"track_{i}"
                ext = ".mp3"
                if ".wav" in audio_url:
                    ext = ".wav"
                elif ".m4a" in audio_url:
                    ext = ".m4a"

                dest = studio_dir / f"{suno_id}{ext}"
                try:
                    await download_track(audio_url, dest)
                    tracks[i]["local_path"] = str(dest)
                except Exception as e:
                    logger.error(f"Download failed for track {i}: {e}")

            update_project(project_id, {
                "status": "complete",
                "tracks": tracks,
            })
            await _broadcast_studio({
                "project_id": project_id,
                "status": "complete",
                "progress": 100,
                "tracks": tracks,
            }, username=username)
            logger.info(f"Generation complete: {project_id} — {len(tracks)} tracks")

        except SunoAuthError:
            update_project(project_id, {
                "status": "failed",
                "error": "Invalid Suno API key",
            })
            await _broadcast_studio({
                "project_id": project_id,
                "status": "failed",
                "error": "Invalid API key",
            }, username=username)
        except Exception as e:
            logger.error(f"Generation failed for {project_id}: {e}")
            update_project(project_id, {
                "status": "failed",
                "error": str(e),
            })
            await _broadcast_studio({
                "project_id": project_id,
                "status": "failed",
                "error": str(e),
            }, username=username)
        finally:
            await client.close()

    background_tasks.add_task(run_generation)

    return {
        "project_id": project_id,
        "status": "generating",
        "message": f"Generating '{req.title or 'Untitled'}'...",
    }


@router.get("/tasks/{task_id}")
async def get_task_status(task_id: str, user: UserContext = Depends(get_current_user)):
    """Poll generation status by Suno task ID."""
    client = _get_client()
    try:
        result = await client.check_status(task_id)
        await client.close()
        return result
    except SunoAPIError as e:
        raise HTTPException(status_code=502, detail=str(e))


@router.post("/extend")
async def extend_track(
    req: ExtendRequest,
    background_tasks: BackgroundTasks,
    user: UserContext = Depends(get_current_user),
):
    """Extend/continue a generated track."""
    client = _get_client()
    username = user.username

    async def run_extend():
        try:
            result = await client.extend(
                audio_id=req.audio_id,
                prompt=req.prompt,
                style=req.style,
                title=req.title,
                continue_at=req.continue_at,
            )
            logger.info(f"Extend started: {result}")
            await _broadcast_studio({
                "status": "extend_started",
                "audio_id": req.audio_id,
                "result": result,
            }, username=username)
        except Exception as e:
            logger.error(f"Extend failed: {e}")
            await _broadcast_studio({
                "status": "extend_failed",
                "audio_id": req.audio_id,
                "error": str(e),
            }, username=username)
        finally:
            await client.close()

    background_tasks.add_task(run_extend)
    return {"status": "extending", "audio_id": req.audio_id}


@router.post("/save-to-beats")
async def save_track_to_beats(
    req: SaveToBeatsRequest,
    user: UserContext = Depends(get_current_user),
):
    """Copy a generated track from studio/ to beats/ and create metadata."""
    paths = get_user_paths(user)

    project = get_project(req.project_id)
    if not project:
        raise HTTPException(status_code=404, detail="Project not found")

    tracks = project.get("tracks", [])
    if req.track_index >= len(tracks):
        raise HTTPException(status_code=400, detail="Invalid track index")

    track = tracks[req.track_index]
    local_path = track.get("local_path")
    if not local_path:
        raise HTTPException(status_code=400, detail="Track has no local file")

    src = Path(local_path) if not isinstance(local_path, Path) else local_path
    if not src.exists():
        raise HTTPException(status_code=404, detail="Local audio file not found")

    # Determine destination filename
    filename = req.filename
    if not filename:
        stem = safe_stem(project.get("title", "untitled"))
        ext = src.suffix or ".mp3"
        filename = f"{stem}{ext}"

    paths.beats_dir.mkdir(parents=True, exist_ok=True)
    dest = paths.beats_dir / filename
    shutil.copy2(str(src), str(dest))

    # Create metadata stub
    stem = safe_stem(filename)
    paths.metadata_dir.mkdir(parents=True, exist_ok=True)
    meta_path = paths.metadata_dir / f"{stem}.json"
    if not meta_path.exists():
        meta = {
            "title": project.get("title", stem.replace("_", " ").title()),
            "artist": "",
            "description": "",
            "tags": ["suno", "ai generated", project.get("style", "")],
        }
        with open(meta_path, "w") as f:
            json.dump(meta, f, indent=2)

    logger.info("Saved studio track to beats: %s -> %s (user=%s)", src.name, stem, user.username)
    return {
        "stem": stem,
        "filename": filename,
        "message": f"Track saved to beats as '{filename}'",
    }
