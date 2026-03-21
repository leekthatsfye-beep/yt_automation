"""
Suno AI music generation service — wraps sunoapi.org REST API.

API docs: https://sunoapi.org
Base URL: https://apibox.erweima.ai
Auth: Bearer token (user provides their own API key)
"""

from __future__ import annotations

import asyncio
import json
import logging
import uuid
import datetime
from pathlib import Path
from typing import Any

import aiohttp

from app.backend.config import SUNO_API_BASE, STUDIO_DIR, STUDIO_PROJECTS, APP_SETTINGS

logger = logging.getLogger(__name__)

STUDIO_DIR.mkdir(exist_ok=True)

MAX_DOWNLOAD_BYTES = 120 * 1024 * 1024  # 120 MB safety cap


# ── Custom Errors ─────────────────────────────────────────────────────────


class SunoAPIError(Exception):
    """Generic Suno API error."""

    def __init__(self, message: str, status_code: int = 0):
        super().__init__(message)
        self.status_code = status_code


class SunoAuthError(SunoAPIError):
    """Invalid or missing API key."""

    def __init__(self, message: str = "Invalid or missing Suno API key"):
        super().__init__(message, 401)


class SunoRateLimitError(SunoAPIError):
    """Rate limited by Suno API."""

    def __init__(self, message: str = "Rate limited — try again later"):
        super().__init__(message, 429)


# ── API Key Management ────────────────────────────────────────────────────


def get_api_key() -> str:
    """Read Suno API key from server-side settings file."""
    try:
        if APP_SETTINGS.exists():
            data = json.loads(APP_SETTINGS.read_text())
            return data.get("suno_api_key", "")
    except Exception:
        pass
    return ""


def save_api_key(key: str) -> None:
    """Save Suno API key to server-side settings file."""
    data: dict[str, Any] = {}
    try:
        if APP_SETTINGS.exists():
            data = json.loads(APP_SETTINGS.read_text())
    except Exception:
        pass
    data["suno_api_key"] = key
    APP_SETTINGS.write_text(json.dumps(data, indent=2))
    logger.info("Suno API key saved")


# ── Suno Client ───────────────────────────────────────────────────────────


class SunoClient:
    """Async client for the sunoapi.org Suno proxy."""

    def __init__(self, api_key: str):
        self.api_key = api_key
        self.base_url = SUNO_API_BASE
        self._session: aiohttp.ClientSession | None = None

    async def _get_session(self) -> aiohttp.ClientSession:
        if self._session is None or self._session.closed:
            timeout = aiohttp.ClientTimeout(total=60)
            self._session = aiohttp.ClientSession(
                timeout=timeout,
                headers={
                    "Authorization": f"Bearer {self.api_key}",
                    "Content-Type": "application/json",
                },
            )
        return self._session

    async def close(self) -> None:
        if self._session and not self._session.closed:
            await self._session.close()

    async def _request(
        self,
        method: str,
        path: str,
        json_data: dict | None = None,
        params: dict | None = None,
        max_retries: int = 3,
    ) -> dict[str, Any]:
        """Make an API request with retry logic."""
        session = await self._get_session()
        url = f"{self.base_url}{path}"
        last_error: Exception | None = None

        for attempt in range(max_retries):
            try:
                async with session.request(
                    method, url, json=json_data, params=params
                ) as resp:
                    body = await resp.json()

                    if resp.status == 401:
                        raise SunoAuthError()
                    if resp.status == 429:
                        raise SunoRateLimitError()
                    if resp.status >= 500:
                        raise SunoAPIError(
                            f"Server error: {resp.status}", resp.status
                        )
                    if resp.status >= 400:
                        msg = body.get("message", body.get("error", f"HTTP {resp.status}"))
                        raise SunoAPIError(f"API error: {msg}", resp.status)

                    return body

            except (SunoAuthError, SunoRateLimitError):
                raise
            except SunoAPIError as e:
                last_error = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))
            except (aiohttp.ClientError, asyncio.TimeoutError) as e:
                last_error = e
                if attempt < max_retries - 1:
                    await asyncio.sleep(2 * (attempt + 1))

        raise SunoAPIError(f"Request failed after {max_retries} retries: {last_error}")

    # ── Generation ────────────────────────────────────────────────────

    async def generate(
        self,
        prompt: str,
        style: str = "",
        title: str = "",
        instrumental: bool = True,
        model: str = "V4",
        custom_mode: bool = True,
    ) -> dict[str, Any]:
        """
        Start a generation task.
        Returns {"task_id": str, ...}
        """
        payload: dict[str, Any] = {
            "prompt": prompt,
            "customMode": custom_mode,
            "instrumental": instrumental,
            "model": model,
        }
        if custom_mode:
            payload["style"] = style
            payload["title"] = title

        result = await self._request("POST", "/api/v1/generate", json_data=payload)
        logger.info(f"Suno generation started: {result}")
        return result

    async def check_status(self, task_id: str) -> dict[str, Any]:
        """
        Check generation status.
        Returns task info with audio URLs when complete.
        """
        result = await self._request(
            "GET",
            "/api/v1/generate/record-info",
            params={"taskId": task_id},
        )
        return result

    async def get_credits(self) -> dict[str, Any]:
        """Get remaining Suno credits."""
        result = await self._request("GET", "/api/v1/generate/credit")
        return result

    async def extend(
        self,
        audio_id: str,
        prompt: str = "",
        style: str = "",
        title: str = "",
        continue_at: float = 0,
    ) -> dict[str, Any]:
        """Extend/continue a generated track."""
        payload = {
            "audioId": audio_id,
            "prompt": prompt,
            "style": style,
            "title": title,
            "continueAt": continue_at,
        }
        result = await self._request("POST", "/api/v1/generate/extend", json_data=payload)
        return result


# ── Download Helper ───────────────────────────────────────────────────────


async def download_track(url: str, dest_path: Path) -> int:
    """
    Download an audio file from Suno CDN to local disk.
    Returns file size in bytes.
    """
    timeout = aiohttp.ClientTimeout(total=120, sock_read=60)
    async with aiohttp.ClientSession(timeout=timeout) as session:
        async with session.get(url) as resp:
            if resp.status != 200:
                raise SunoAPIError(f"Download failed: HTTP {resp.status}")

            total = 0
            dest_path.parent.mkdir(parents=True, exist_ok=True)

            with open(dest_path, "wb") as f:
                async for chunk in resp.content.iter_chunked(64 * 1024):
                    total += len(chunk)
                    if total > MAX_DOWNLOAD_BYTES:
                        raise SunoAPIError("Download exceeds 120MB safety cap")
                    f.write(chunk)

            logger.info(f"Downloaded: {dest_path.name} ({total:,} bytes)")
            return total


# ── Project Persistence ───────────────────────────────────────────────────


def _read_projects_file() -> list[dict[str, Any]]:
    """Read projects from JSON file."""
    try:
        if STUDIO_PROJECTS.exists():
            data = json.loads(STUDIO_PROJECTS.read_text())
            if isinstance(data, list):
                return data
    except Exception as e:
        logger.warning(f"Error reading projects file: {e}")
    return []


def _write_projects_file(projects: list[dict[str, Any]]) -> None:
    """Write projects to JSON file."""
    STUDIO_PROJECTS.parent.mkdir(parents=True, exist_ok=True)
    STUDIO_PROJECTS.write_text(json.dumps(projects, indent=2))


def load_projects() -> list[dict[str, Any]]:
    """Load all projects, newest first."""
    projects = _read_projects_file()
    projects.sort(key=lambda p: p.get("created_at", ""), reverse=True)
    return projects


def get_project(project_id: str) -> dict[str, Any] | None:
    """Get a single project by ID."""
    for p in _read_projects_file():
        if p.get("id") == project_id:
            return p
    return None


def create_project(
    title: str,
    prompt: str,
    style: str,
    instrumental: bool,
    model: str,
) -> dict[str, Any]:
    """Create a new project entry."""
    now = datetime.datetime.now(datetime.timezone.utc).isoformat()
    project: dict[str, Any] = {
        "id": str(uuid.uuid4())[:8],
        "title": title or "Untitled",
        "prompt": prompt,
        "style": style,
        "instrumental": instrumental,
        "model": model,
        "status": "pending",
        "suno_task_id": None,
        "tracks": [],
        "created_at": now,
        "updated_at": now,
    }
    projects = _read_projects_file()
    projects.append(project)
    _write_projects_file(projects)
    return project


def update_project(project_id: str, updates: dict[str, Any]) -> dict[str, Any] | None:
    """Update an existing project."""
    projects = _read_projects_file()
    for i, p in enumerate(projects):
        if p.get("id") == project_id:
            updates["updated_at"] = datetime.datetime.now(datetime.timezone.utc).isoformat()
            projects[i] = {**p, **updates}
            _write_projects_file(projects)
            return projects[i]
    return None


def delete_project(project_id: str) -> bool:
    """Delete a project and its local audio files."""
    projects = _read_projects_file()
    found = None
    for i, p in enumerate(projects):
        if p.get("id") == project_id:
            found = i
            break

    if found is None:
        return False

    project = projects.pop(found)

    # Delete local audio files
    for track in project.get("tracks", []):
        local = track.get("local_path")
        if local:
            path = Path(local)
            if path.exists():
                try:
                    path.unlink()
                    logger.info(f"Deleted audio file: {path}")
                except Exception as e:
                    logger.warning(f"Failed to delete {path}: {e}")

    _write_projects_file(projects)
    logger.info(f"Deleted project: {project_id}")
    return True
