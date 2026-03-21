"""
/api/integrity — Channel Integrity Manager endpoints.

Run channel audits and get health reports.
"""

from __future__ import annotations

import logging

from fastapi import APIRouter, Depends

from app.backend.deps import require_admin, UserContext, get_user_paths
from app.backend.services import integrity_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/integrity", tags=["integrity"])


@router.get("/audit")
async def run_audit(user: UserContext = Depends(require_admin)):
    """Run a full channel integrity audit.

    Returns Channel Health Report with:
    - Health score (0-100)
    - Issues categorized by severity (high/medium/low)
    - Specific actions to fix each issue
    """
    paths = get_user_paths(user)
    return integrity_svc.run_integrity_audit(
        paths.beats_dir, paths.metadata_dir,
        paths.output_dir, paths.uploads_log,
    )
