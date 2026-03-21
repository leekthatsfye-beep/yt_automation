"""
/api/revival — Catalog Revival Engine endpoints.

Scan for old videos with revival potential and get recommended actions.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends, Query

from app.backend.deps import require_admin, UserContext, get_user_paths
from app.backend.services import revival_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/revival", tags=["revival"])


@router.get("/scan")
async def scan_candidates(
    min_age: int = Query(0, ge=0),
    max_age: int = Query(99999, ge=1),
    user: UserContext = Depends(require_admin),
):
    """Scan entire YouTube library for revival candidates and optimization opportunities."""
    paths = get_user_paths(user)
    return revival_svc.scan_revival_candidates(
        paths.uploads_log, paths.metadata_dir,
        min_age_days=min_age, max_age_days=max_age,
    )


@router.get("/{stem}")
async def get_revival_actions(
    stem: str,
    user: UserContext = Depends(require_admin),
):
    """Get revival actions for a specific beat."""
    paths = get_user_paths(user)
    return revival_svc.get_revival_actions(stem, paths.uploads_log, paths.metadata_dir)
