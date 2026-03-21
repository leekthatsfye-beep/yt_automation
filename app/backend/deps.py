"""
FastAPI dependency injection for authentication and per-user path resolution.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from fastapi import Depends, HTTPException, Header, Query

from app.backend.auth import decode_token, PRODUCERS_DIR
from app.backend.config import (
    ROOT,
    BEATS_DIR,
    METADATA_DIR,
    OUTPUT_DIR,
    IMAGES_DIR,
    BRAND_DIR,
    UPLOADS_LOG,
    SOCIAL_LOG,
    STUDIO_DIR,
    STUDIO_PROJECTS,
    LISTINGS_DIR,
    STORE_UPLOADS_LOG,
    SHARED_CLIPS_DIR,
)


@dataclass
class UserContext:
    username: str
    role: str  # "admin" | "producer"


@dataclass
class UserPaths:
    """Resolved filesystem paths for the current user."""
    beats_dir: Path
    metadata_dir: Path
    output_dir: Path
    images_dir: Path
    brand_dir: Path
    uploads_log: Path
    social_log: Path
    studio_dir: Path
    studio_projects: Path
    listings_dir: Path
    store_uploads_log: Path
    shared_clips_dir: Path


async def get_current_user(
    authorization: str | None = Header(None),
    token: str | None = Query(None, alias="token"),
) -> UserContext:
    """Validate JWT from Authorization header or ?token= query param.

    The query-param path is needed for <video src="...?token=xxx"> streaming,
    because the browser's native media player cannot send custom headers.
    """
    jwt_token: str | None = None

    # Prefer Authorization header
    if authorization and authorization.startswith("Bearer "):
        jwt_token = authorization.split(" ", 1)[1]
    # Fall back to ?token= query param (for video streaming)
    elif token:
        jwt_token = token

    if not jwt_token:
        raise HTTPException(status_code=401, detail="Not authenticated")

    payload = decode_token(jwt_token)
    if not payload:
        raise HTTPException(status_code=401, detail="Invalid or expired token")

    return UserContext(
        username=payload["sub"],
        role=payload.get("role", "producer"),
    )


async def require_admin(
    user: UserContext = Depends(get_current_user),
) -> UserContext:
    """Require admin role. Raises 403 if not admin."""
    if user.role != "admin":
        raise HTTPException(status_code=403, detail="Admin access required")
    return user


def get_user_paths(user: UserContext) -> UserPaths:
    """Resolve filesystem paths based on user role.

    Admin → project root directories (existing data).
    Producer → producers/{username}/ subdirectories.
    """
    if user.role == "admin":
        return UserPaths(
            beats_dir=BEATS_DIR,
            metadata_dir=METADATA_DIR,
            output_dir=OUTPUT_DIR,
            images_dir=IMAGES_DIR,
            brand_dir=BRAND_DIR,
            uploads_log=UPLOADS_LOG,
            social_log=SOCIAL_LOG,
            studio_dir=STUDIO_DIR,
            studio_projects=STUDIO_PROJECTS,
            listings_dir=LISTINGS_DIR,
            store_uploads_log=STORE_UPLOADS_LOG,
            shared_clips_dir=SHARED_CLIPS_DIR,
        )

    base = PRODUCERS_DIR / user.username
    return UserPaths(
        beats_dir=base / "beats",
        metadata_dir=base / "metadata",
        output_dir=base / "output",
        images_dir=base / "images",
        brand_dir=BRAND_DIR,
        uploads_log=base / "uploads_log.json",
        social_log=base / "social_uploads_log.json",
        studio_dir=base / "studio",
        studio_projects=base / "studio" / "projects.json",
        listings_dir=base / "listings",
        store_uploads_log=base / "store_uploads_log.json",
        shared_clips_dir=SHARED_CLIPS_DIR,
    )
