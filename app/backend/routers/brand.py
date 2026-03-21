"""
/api/brand — Brand Builder endpoints.

Generate logos, manage brand assets, and create thumbnail stamps.
"""

from __future__ import annotations

import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.deps import get_current_user, UserContext, get_user_paths
from app.backend.services import brand_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/brand", tags=["brand"])


class LogoRequest(BaseModel):
    text: str
    preset: str = "gold_metallic"
    width: int = 1200
    height: int = 400
    font_size: int = 120


class StampRequest(BaseModel):
    text: str
    font_color: str = "#FFFFFF"
    size: int = 200


@router.get("/assets")
async def list_assets(user: UserContext = Depends(get_current_user)):
    """List all brand assets (logos, stamps, intros)."""
    paths = get_user_paths(user)
    return brand_svc.list_brand_assets(paths.brand_dir)


@router.get("/presets")
async def get_presets():
    """Get available logo style presets."""
    return {"presets": brand_svc.get_presets()}


@router.post("/generate-logo")
async def generate_logo(
    body: LogoRequest,
    user: UserContext = Depends(get_current_user),
):
    """Generate a text-based logo with the selected style preset."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Logo text is required")
    if len(body.text) > 30:
        raise HTTPException(status_code=400, detail="Logo text too long (max 30 chars)")

    paths = get_user_paths(user)
    result = await brand_svc.generate_logo(
        text=body.text.strip(),
        preset=body.preset,
        brand_dir=paths.brand_dir,
        width=body.width,
        height=body.height,
        font_size=body.font_size,
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Logo generation failed"))

    return result


@router.post("/generate-stamp")
async def generate_stamp(
    body: StampRequest,
    user: UserContext = Depends(get_current_user),
):
    """Generate a thumbnail corner stamp."""
    if not body.text.strip():
        raise HTTPException(status_code=400, detail="Stamp text is required")

    paths = get_user_paths(user)
    result = await brand_svc.generate_thumb_stamp(
        text=body.text.strip(),
        brand_dir=paths.brand_dir,
        font_color=body.font_color,
        size=body.size,
    )

    if not result.get("success"):
        raise HTTPException(status_code=500, detail=result.get("error", "Stamp generation failed"))

    return result
