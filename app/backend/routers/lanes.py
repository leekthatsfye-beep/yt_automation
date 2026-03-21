"""
/api/lanes — Artist lanes configuration endpoints.
Read/write lanes_config.json + assign beats to lanes.
"""

from __future__ import annotations

import json
import logging
from typing import Any, Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.config import ROOT, METADATA_DIR
from app.backend.deps import require_admin, UserContext, get_user_paths
from app.backend.services.beat_svc import list_beats, safe_stem
from app.backend.services import schedule_svc

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/lanes", tags=["lanes"])

LANES_CONFIG = ROOT / "lanes_config.json"


def _load_config() -> dict[str, Any]:
    try:
        if LANES_CONFIG.exists():
            return json.loads(LANES_CONFIG.read_text())
    except Exception:
        pass
    return {}


def _save_config(cfg: dict[str, Any]) -> None:
    LANES_CONFIG.write_text(json.dumps(cfg, indent=2, ensure_ascii=False))


# ── GET /api/lanes — full lanes config ──

@router.get("")
async def get_lanes_config(user: UserContext = Depends(require_admin)):
    """Return the full lanes configuration."""
    cfg = _load_config()
    return cfg


# ── GET /api/lanes/summary — lane summaries with beat counts ──

@router.get("/summary")
async def get_lanes_summary(user: UserContext = Depends(require_admin)):
    """
    Return a summary of each lane with beat counts and today's artist.
    """
    cfg = _load_config()
    paths = get_user_paths(user)
    beats = list_beats(
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )

    lanes = cfg.get("lanes", {})
    daily_schedule = cfg.get("daily_schedule", {})
    summaries = []

    for lane_id, lane_data in lanes.items():
        # Count beats assigned to this lane
        lane_beats = [b for b in beats if _get_beat_lane(b["stem"], paths.metadata_dir) == lane_id]
        rendered_count = sum(1 for b in lane_beats if b.get("rendered"))
        uploaded_count = sum(1 for b in lane_beats if b.get("uploaded"))

        # Find schedule slot
        slot_key = f"{lane_id}_slot"
        slot = daily_schedule.get(slot_key, {})

        summaries.append({
            "id": lane_id,
            "label": lane_data.get("label", lane_id.title()),
            "strategy": lane_data.get("strategy", ""),
            "artists": lane_data.get("artists", []),
            "schedule_mode": lane_data.get("schedule_mode", "fixed"),
            "rotation_order": lane_data.get("rotation_order", []),
            "slot_time": slot.get("time_est", ""),
            "beat_count": len(lane_beats),
            "rendered_count": rendered_count,
            "uploaded_count": uploaded_count,
        })

    # Unassigned beats
    assigned_stems = set()
    for lane_id in lanes:
        for b in beats:
            if _get_beat_lane(b["stem"], paths.metadata_dir) == lane_id:
                assigned_stems.add(b["stem"])

    unassigned = [b for b in beats if b["stem"] not in assigned_stems]

    return {
        "lanes": summaries,
        "unassigned_count": len(unassigned),
        "total_beats": len(beats),
        "dual_combos": cfg.get("dual_combos", []),
    }


def _get_beat_lane(stem: str, metadata_dir=METADATA_DIR) -> str | None:
    """Read lane from a beat's metadata JSON."""
    meta_path = metadata_dir / f"{stem}.json"
    try:
        if meta_path.exists():
            meta = json.loads(meta_path.read_text())
            return meta.get("lane")
    except Exception:
        pass
    return None


# ── GET /api/lanes/beats — beats grouped by lane ──

@router.get("/beats")
async def get_beats_by_lane(user: UserContext = Depends(require_admin)):
    """Return beats grouped by lane assignment."""
    paths = get_user_paths(user)
    beats = list_beats(
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )

    cfg = _load_config()
    lane_ids = list(cfg.get("lanes", {}).keys())

    grouped: dict[str, list[dict]] = {lid: [] for lid in lane_ids}
    grouped["unassigned"] = []

    for beat in beats:
        lane = _get_beat_lane(beat["stem"], paths.metadata_dir)
        # Add lane + artist info from metadata
        meta_path = paths.metadata_dir / f"{beat['stem']}.json"
        seo_artist = ""
        seo_artist2 = ""
        try:
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                seo_artist = meta.get("seo_artist", "")
                seo_artist2 = meta.get("seo_artist2", "")
        except Exception:
            pass

        beat_info = {
            "stem": beat["stem"],
            "title": beat.get("title", ""),
            "beat_name": beat.get("beat_name", ""),
            "rendered": beat.get("rendered", False),
            "uploaded": beat.get("uploaded", False),
            "seo_artist": seo_artist,
            "seo_artist2": seo_artist2,
            "lane": lane,
            "audio": beat.get("filename", ""),
        }

        if lane and lane in grouped:
            grouped[lane].append(beat_info)
        else:
            grouped["unassigned"].append(beat_info)

    return grouped


# ── POST /api/lanes/assign — assign beats to a lane ──

class AssignRequest(BaseModel):
    stems: list[str]
    lane: str
    artist: Optional[str] = None
    dual: bool = False


@router.post("/assign")
async def assign_beats_to_lane(
    req: AssignRequest,
    user: UserContext = Depends(require_admin),
):
    """
    Assign one or more beats to a lane.
    Updates metadata JSON for each beat with lane + seo_artist.
    Optionally generates dual-artist combo.
    """
    cfg = _load_config()
    lanes = cfg.get("lanes", {})

    if req.lane not in lanes:
        raise HTTPException(400, f"Unknown lane: {req.lane}")

    paths = get_user_paths(user)
    lane_data = lanes[req.lane]

    # Resolve artist
    artist = req.artist
    if not artist:
        if lane_data.get("schedule_mode") == "fixed":
            artist = lane_data.get("slot_artist", "")
        elif lane_data.get("schedule_mode") == "rotation":
            rotation = lane_data.get("rotation_order", lane_data.get("artists", []))
            if rotation:
                artist = rotation[0]

    updated = []
    for stem in req.stems:
        meta_path = paths.metadata_dir / f"{stem}.json"
        meta: dict[str, Any] = {}
        try:
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
        except Exception:
            pass

        meta["lane"] = req.lane
        if artist:
            meta["seo_artist"] = artist

        # Dual combo
        if req.dual and artist:
            combos = cfg.get("dual_combos", [])
            partners = []
            for combo in combos:
                if artist in combo:
                    p = combo[0] if combo[1] == artist else combo[1]
                    partners.append(p)
            if partners:
                import random
                meta["seo_artist2"] = random.choice(partners)

        meta_path.parent.mkdir(exist_ok=True)
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        updated.append(stem)

    return {"updated": updated, "lane": req.lane, "artist": artist}


# ── POST /api/lanes/unassign — remove lane assignment ──

class UnassignRequest(BaseModel):
    stems: list[str]


@router.post("/unassign")
async def unassign_beats(
    req: UnassignRequest,
    user: UserContext = Depends(require_admin),
):
    """Remove lane assignment from beats."""
    paths = get_user_paths(user)
    updated = []

    for stem in req.stems:
        meta_path = paths.metadata_dir / f"{stem}.json"
        try:
            if meta_path.exists():
                meta = json.loads(meta_path.read_text())
                meta.pop("lane", None)
                meta.pop("seo_artist", None)
                meta.pop("seo_artist2", None)
                meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
                updated.append(stem)
        except Exception as e:
            logger.warning("Failed to unassign %s: %s", stem, e)

    return {"updated": updated}


# ── POST /api/lanes/unassign-all — clear ALL lane assignments ──

@router.post("/unassign-all")
async def unassign_all_beats(
    user: UserContext = Depends(require_admin),
):
    """Remove lane assignment from ALL beats across all lanes."""
    paths = get_user_paths(user)
    updated = []

    for meta_path in sorted(paths.metadata_dir.glob("*.json")):
        try:
            meta = json.loads(meta_path.read_text())
            if "lane" in meta:
                meta.pop("lane", None)
                meta.pop("seo_artist", None)
                meta.pop("seo_artist2", None)
                meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
                updated.append(meta_path.stem)
        except Exception as e:
            logger.warning("Failed to unassign %s: %s", meta_path.stem, e)

    return {"updated": updated, "count": len(updated)}


# ── POST /api/lanes/regenerate-seo — regenerate SEO for assigned beats ──

class RegenSeoRequest(BaseModel):
    lane: Optional[str] = None  # None = all lanes
    stems: Optional[list[str]] = None  # None = all beats in lane


@router.post("/regenerate-seo")
async def regenerate_lane_seo(
    req: RegenSeoRequest,
    user: UserContext = Depends(require_admin),
):
    """
    Regenerate SEO metadata (title, description, tags) for beats in a lane
    using the lanes_config templates.
    """
    import sys
    sys.path.insert(0, str(ROOT))
    from seo_metadata import build_metadata

    paths = get_user_paths(user)
    cfg = _load_config()
    lanes = cfg.get("lanes", {})

    target_lanes = [req.lane] if req.lane else list(lanes.keys())
    regenerated = []

    beats = list_beats(
        beats_dir=paths.beats_dir,
        metadata_dir=paths.metadata_dir,
        output_dir=paths.output_dir,
        uploads_log_path=paths.uploads_log,
        social_log_path=paths.social_log,
    )

    for beat in beats:
        stem = beat["stem"]
        if req.stems and stem not in req.stems:
            continue

        lane = _get_beat_lane(stem, paths.metadata_dir)
        if lane not in target_lanes:
            continue

        meta_path = paths.metadata_dir / f"{stem}.json"
        existing = {}
        try:
            if meta_path.exists():
                existing = json.loads(meta_path.read_text())
        except Exception:
            pass

        artist = existing.get("seo_artist")
        dual = bool(existing.get("seo_artist2"))

        meta = build_metadata(stem, existing, lane=lane, artist=artist, dual=dual)
        meta_path.write_text(json.dumps(meta, indent=2, ensure_ascii=False))
        regenerated.append(stem)

    return {"regenerated": regenerated, "count": len(regenerated)}


# ── PUT /api/lanes/{lane_id}/artists — update artists for a lane ──

class UpdateArtistsRequest(BaseModel):
    artists: list[str]
    schedule_mode: Optional[str] = None  # "fixed" or "rotation"
    slot_artist: Optional[str] = None
    rotation_order: Optional[list[str]] = None
    strategy: Optional[str] = None


@router.put("/{lane_id}/artists")
async def update_lane_artists(
    lane_id: str,
    req: UpdateArtistsRequest,
    user: UserContext = Depends(require_admin),
):
    """
    Update the artists assigned to a lane.
    Also updates schedule_mode, slot_artist, rotation_order, strategy.
    Syncs artist_groups and daily_schedule automatically.
    """
    cfg = _load_config()
    lanes = cfg.get("lanes", {})

    if lane_id not in lanes:
        raise HTTPException(400, f"Unknown lane: {lane_id}")

    lane_data = lanes[lane_id]

    # Update artists
    lane_data["artists"] = req.artists

    # Update mode + related fields
    if req.schedule_mode:
        lane_data["schedule_mode"] = req.schedule_mode
    if req.slot_artist is not None:
        lane_data["slot_artist"] = req.slot_artist
    if req.rotation_order is not None:
        lane_data["rotation_order"] = req.rotation_order
    if req.strategy is not None:
        lane_data["strategy"] = req.strategy

    # Auto-fix: if switching to fixed but no slot_artist, use first artist
    if lane_data.get("schedule_mode") == "fixed" and not lane_data.get("slot_artist") and req.artists:
        lane_data["slot_artist"] = req.artists[0]

    # Auto-fix: if switching to rotation but no rotation_order, use artists list
    if lane_data.get("schedule_mode") == "rotation" and not lane_data.get("rotation_order"):
        lane_data["rotation_order"] = list(req.artists)

    lanes[lane_id] = lane_data
    cfg["lanes"] = lanes

    # Sync artist_groups
    groups = cfg.get("artist_groups", {})
    # Map lane_id → group key
    group_key_map = {
        "breakfast": "BreakfastArtists",
        "lunch": "LunchArtists",
        "dinner": "DinnerArtists",
    }
    group_key = group_key_map.get(lane_id)
    if group_key:
        groups[group_key] = req.artists
        cfg["artist_groups"] = groups

    # Sync daily_schedule
    schedule = cfg.get("daily_schedule", {})
    slot_key = f"{lane_id}_slot"
    if slot_key in schedule:
        if lane_data.get("schedule_mode") == "fixed":
            schedule[slot_key]["artist"] = lane_data.get("slot_artist", req.artists[0] if req.artists else "")
        elif lane_data.get("schedule_mode") == "rotation":
            schedule[slot_key]["rotation"] = lane_data.get("rotation_order", req.artists)
    cfg["daily_schedule"] = schedule

    _save_config(cfg)

    return {
        "lane_id": lane_id,
        "artists": req.artists,
        "schedule_mode": lane_data.get("schedule_mode"),
        "slot_artist": lane_data.get("slot_artist"),
        "rotation_order": lane_data.get("rotation_order"),
    }


# ── POST /api/lanes/{lane_id}/artists/add — add artist to lane ──

class AddArtistRequest(BaseModel):
    artist: str


@router.post("/{lane_id}/artists/add")
async def add_artist_to_lane(
    lane_id: str,
    req: AddArtistRequest,
    user: UserContext = Depends(require_admin),
):
    """Add a single artist to a lane's artist list."""
    cfg = _load_config()
    lanes = cfg.get("lanes", {})

    if lane_id not in lanes:
        raise HTTPException(400, f"Unknown lane: {lane_id}")

    artists = lanes[lane_id].get("artists", [])
    if req.artist in artists:
        return {"message": f"{req.artist} already in {lane_id}", "artists": artists}

    artists.append(req.artist)
    lanes[lane_id]["artists"] = artists

    # Also update rotation_order if in rotation mode
    if lanes[lane_id].get("schedule_mode") == "rotation":
        rotation = lanes[lane_id].get("rotation_order", [])
        if req.artist not in rotation:
            rotation.append(req.artist)
            lanes[lane_id]["rotation_order"] = rotation

    cfg["lanes"] = lanes
    _save_config(cfg)

    return {"artists": artists, "added": req.artist, "lane_id": lane_id}


# ── POST /api/lanes/{lane_id}/artists/remove — remove artist from lane ──

class RemoveArtistRequest(BaseModel):
    artist: str


@router.post("/{lane_id}/artists/remove")
async def remove_artist_from_lane(
    lane_id: str,
    req: RemoveArtistRequest,
    user: UserContext = Depends(require_admin),
):
    """Remove a single artist from a lane."""
    cfg = _load_config()
    lanes = cfg.get("lanes", {})

    if lane_id not in lanes:
        raise HTTPException(400, f"Unknown lane: {lane_id}")

    artists = lanes[lane_id].get("artists", [])
    if req.artist not in artists:
        return {"message": f"{req.artist} not in {lane_id}", "artists": artists}

    artists.remove(req.artist)
    lanes[lane_id]["artists"] = artists

    # Also update rotation_order
    if lanes[lane_id].get("schedule_mode") == "rotation":
        rotation = lanes[lane_id].get("rotation_order", [])
        if req.artist in rotation:
            rotation.remove(req.artist)
            lanes[lane_id]["rotation_order"] = rotation

    # If removed artist was slot_artist, pick first remaining
    if lanes[lane_id].get("slot_artist") == req.artist:
        lanes[lane_id]["slot_artist"] = artists[0] if artists else ""

    cfg["lanes"] = lanes
    _save_config(cfg)

    return {"artists": artists, "removed": req.artist, "lane_id": lane_id}


# ── GET /api/lanes/schedule-preview — upcoming schedule merged with lanes ──

@router.get("/schedule-preview")
async def get_schedule_preview(user: UserContext = Depends(require_admin)):
    """
    Return the next 7 days of scheduled slots merged with lane data,
    plus buffer/queue info and YouTube-scheduled uploads.
    Consolidates data from schedule_svc + uploads_log so the frontend
    only needs one call.
    """
    from datetime import datetime, timezone

    paths = get_user_paths(user)

    # Get schedule data
    full_schedule = schedule_svc.get_full_schedule(uploads_log_path=paths.uploads_log)
    slots = schedule_svc.get_next_slots(n=21)  # ~7 days × 3 slots/day
    buffer_days = schedule_svc.get_buffer_days()

    # Get YouTube-scheduled uploads (future publishAt)
    youtube_scheduled: list[dict] = []
    try:
        if paths.uploads_log.exists():
            log = json.loads(paths.uploads_log.read_text())
            now = datetime.now(timezone.utc)

            for stem, info in log.items():
                publish_at = info.get("publishAt")
                if not publish_at:
                    continue
                try:
                    dt = datetime.fromisoformat(publish_at)
                    if dt.tzinfo is None:
                        dt = dt.replace(tzinfo=timezone.utc)
                except Exception:
                    continue

                youtube_scheduled.append({
                    "stem": stem,
                    "videoId": info.get("videoId", ""),
                    "url": info.get("url", ""),
                    "title": info.get("title", stem),
                    "uploadedAt": info.get("uploadedAt", ""),
                    "publishAt": publish_at,
                    "isPast": dt <= now,
                })

            youtube_scheduled.sort(key=lambda u: (u["isPast"], u["publishAt"]))
    except Exception as e:
        logger.error("Failed to read YouTube scheduled: %s", e)

    # Get lane config for lane labels/colors
    cfg = _load_config()
    lanes_cfg = cfg.get("lanes", {})
    daily_schedule = cfg.get("daily_schedule", {})

    # Map slot times to lanes
    lane_slot_map: dict[str, str] = {}
    for lane_id in lanes_cfg:
        slot_key = f"{lane_id}_slot"
        slot_data = daily_schedule.get(slot_key, {})
        time_est = slot_data.get("time_est", "")
        if time_est:
            lane_slot_map[time_est] = lane_id

    # Enrich slots with lane info
    enriched_slots = []
    for slot in slots:
        slot_est = slot.get("slot_est", "")
        # Extract time from slot_est (format: "2026-03-15 11:00 AM")
        lane_id = None
        for time_str, lid in lane_slot_map.items():
            # Convert 24h time to check against slot
            try:
                h, m = map(int, time_str.split(":"))
                # Check if this slot's time matches
                if slot_est and f"{h % 12 or 12}:{m:02d}" in slot_est:
                    am_pm = "AM" if h < 12 else "PM"
                    if am_pm in slot_est:
                        lane_id = lid
                        break
            except Exception:
                continue

        lane_data = lanes_cfg.get(lane_id, {}) if lane_id else {}
        enriched_slots.append({
            **slot,
            "lane": lane_id,
            "lane_label": lane_data.get("label", ""),
            "lane_artist": lane_data.get("slot_artist", ""),
        })

    settings = full_schedule.get("settings", {})

    return {
        "slots": enriched_slots,
        "buffer_days": buffer_days,
        "queue_length": full_schedule.get("queue_length", 0),
        "queue": full_schedule.get("queue", []),
        "youtube_scheduled": youtube_scheduled,
        "settings": settings,
    }
