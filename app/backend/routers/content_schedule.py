"""
/api/content-schedule — Content Scheduler endpoints.

Orchestrates daily 6-slot content plans (3 beats + 3 Shorts).
Calls content_scheduler.py — does NOT modify upload.py or render.py.
"""

from __future__ import annotations

import asyncio
import json
import logging
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from app.backend.config import PYTHON, ROOT
from app.backend.deps import require_admin, UserContext
from app.backend.ws import manager, tracker

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/api/content-schedule", tags=["content-schedule"])

SCHEDULE_LOG = ROOT / "content_schedule_log.json"


def _load_json(path):
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


# ── GET /status ──────────────────────────────────────────────────────────────

@router.get("/status")
async def scheduler_status(user: UserContext = Depends(require_admin)):
    """Current scheduler state: buffer, clusters, history."""
    import sys
    sys.path.insert(0, str(ROOT))
    from content_scheduler import get_scheduler_status
    return get_scheduler_status()


# ── GET /plan ────────────────────────────────────────────────────────────────

@router.get("/plan")
async def get_plan(
    date: Optional[str] = None,
    user: UserContext = Depends(require_admin),
):
    """Preview a daily plan without executing.  ?date=2026-03-15"""
    import sys
    from datetime import datetime

    sys.path.insert(0, str(ROOT))
    from content_scheduler import plan_daily_content, make_beat_title, EST

    target = None
    if date:
        try:
            target = datetime.strptime(date, "%Y-%m-%d").replace(tzinfo=EST)
        except ValueError:
            raise HTTPException(400, f"Bad date format: {date}")

    plan = plan_daily_content(target_date=target)

    # Apply slot overrides (user-picked beats)
    log = _load_json(SCHEDULE_LOG)
    overrides = log.get("slot_overrides", {})
    meta_dir = ROOT / "metadata"
    out_dir = ROOT / "output"

    if overrides:
        for idx_str, stem in overrides.items():
            idx = int(idx_str)
            if idx < 0 or idx >= len(plan.get("slots", [])):
                continue
            # Verify stem still valid
            if not (meta_dir / f"{stem}.json").exists():
                continue
            if not (out_dir / f"{stem}.mp4").exists():
                continue

            slot = plan["slots"][idx]
            meta = _load_json(meta_dir / f"{stem}.json")
            artist = slot.get("artist", meta.get("seo_artist", meta.get("artist", "")))

            slot["stem"] = stem
            slot["status"] = "planned"
            slot["override"] = True
            if slot["type"] == "beat":
                slot["title"] = make_beat_title(stem, artist)
            elif slot["type"] == "short":
                slot["has_short_video"] = (out_dir / f"{stem}_9x16.mp4").exists()

    return plan


# ── POST /execute ────────────────────────────────────────────────────────────

class ExecuteRequest(BaseModel):
    dry_run: bool = False
    date: Optional[str] = None


@router.post("/execute")
async def execute_schedule(req: ExecuteRequest, user: UserContext = Depends(require_admin)):
    """Execute (or dry-run) the daily content plan as a background task."""

    task_id = tracker.create("content", "content_schedule",
                             "Daily content schedule" if not req.dry_run else "Dry run")
    await manager.send_progress(task_id, "content_schedule", 0,
                                "Starting content scheduler...", username=user.username)

    cmd = [PYTHON, str(ROOT / "content_scheduler.py")]
    if req.dry_run:
        cmd.append("--dry-run")
    else:
        cmd.append("--execute")
    if req.date:
        cmd.extend(["--date", req.date])

    async def _run():
        try:
            proc = await asyncio.create_subprocess_exec(
                *cmd,
                stdout=asyncio.subprocess.PIPE,
                stderr=asyncio.subprocess.PIPE,
                cwd=str(ROOT),
            )
            pct = 5
            while True:
                line = await proc.stdout.readline()
                if not line:
                    break
                text = line.decode(errors="replace").strip()
                if not text:
                    continue
                logger.info("content_scheduler: %s", text)

                if "Beat scheduled" in text:
                    pct = min(pct + 15, 85)
                elif "Short created" in text or "Short uploaded" in text:
                    pct = min(pct + 10, 90)
                elif "Result:" in text:
                    pct = 95

                tracker.update(task_id, pct, text)
                await manager.send_progress(task_id, "content_schedule", pct,
                                            text, username=user.username)

            await proc.wait()
            stderr_text = (await proc.stderr.read()).decode(errors="replace")

            if proc.returncode != 0:
                logger.error("content_scheduler failed: %s", stderr_text[:500])
                tracker.fail(task_id, f"Error: {stderr_text[:200]}")
                await manager.send_progress(task_id, "content_schedule", pct,
                                            f"Error: {stderr_text[:200]}",
                                            username=user.username)
                return

            tracker.complete(task_id)
            await manager.send_progress(task_id, "content_schedule", 100,
                                        "Schedule complete!", username=user.username)
        except Exception as e:
            logger.error("Content schedule task error: %s", e)
            tracker.fail(task_id, str(e)[:200])

    asyncio.create_task(_run())
    return {"taskId": task_id, "status": "started"}


# ── POST /generate-short/{stem} ─────────────────────────────────────────────

@router.post("/generate-short/{stem}")
async def gen_short(stem: str, user: UserContext = Depends(require_admin)):
    """Generate a 9:16 Short for one beat (calls social_upload.convert_to_portrait)."""
    import sys
    sys.path.insert(0, str(ROOT))
    from content_scheduler import generate_short

    path = generate_short(stem, force=True)
    if path and path.exists():
        return {"stem": stem, "short_path": str(path), "status": "ok"}
    raise HTTPException(500, f"Short generation failed for {stem}")


# ── PUT /settings ────────────────────────────────────────────────────────────

class SettingsUpdate(BaseModel):
    slots: Optional[list[dict]] = None
    beats_per_day: Optional[int] = None
    shorts_per_day: Optional[int] = None


@router.put("/settings")
async def update_settings(req: SettingsUpdate, user: UserContext = Depends(require_admin)):
    """Update scheduler settings (times, beats_per_day, etc.)."""
    import sys
    sys.path.insert(0, str(ROOT))
    from content_scheduler import load_settings, save_settings

    current = load_settings()
    if req.slots is not None:
        current["slots"] = req.slots
    if req.beats_per_day is not None:
        current["beats_per_day"] = max(1, min(10, req.beats_per_day))
    if req.shorts_per_day is not None:
        current["shorts_per_day"] = max(0, min(10, req.shorts_per_day))
    save_settings(current)
    return current


# ── Lane Optimizer endpoints ─────────────────────────────────────────────────

@router.get("/optimizer")
async def get_optimizer_report(user: UserContext = Depends(require_admin)):
    """Get lane optimization report: scores, rankings, analytics data."""
    import sys
    sys.path.insert(0, str(ROOT))
    from lane_optimizer import get_optimization_report
    return get_optimization_report()


@router.post("/optimizer/refresh")
async def refresh_optimizer(user: UserContext = Depends(require_admin)):
    """Rebuild analytics.json from uploads log + metadata."""
    import sys
    sys.path.insert(0, str(ROOT))
    from lane_optimizer import refresh_analytics_from_logs, get_optimization_report

    stats = refresh_analytics_from_logs()
    report = get_optimization_report()
    return {
        "refreshed": bool(stats),
        "lanes_updated": len(stats),
        **report,
    }


class UpdateAnalyticsRequest(BaseModel):
    analytics: dict


@router.put("/optimizer/analytics")
async def update_analytics(
    req: UpdateAnalyticsRequest,
    user: UserContext = Depends(require_admin),
):
    """Manually update analytics.json with custom data."""
    import sys
    sys.path.insert(0, str(ROOT))
    from lane_optimizer import save_analytics, get_optimization_report

    save_analytics(req.analytics)
    return get_optimization_report()


# ── Cluster editing (writes to lanes_config.json) ────────────────────────────

class UpdateClusterRequest(BaseModel):
    artists: list[str]


@router.put("/clusters/{lane}")
async def update_cluster(
    lane: str,
    req: UpdateClusterRequest,
    user: UserContext = Depends(require_admin),
):
    """Update the artist list for a lane cluster."""
    lanes_cfg = ROOT / "lanes_config.json"
    cfg = _load_json(lanes_cfg)
    lanes = cfg.get("lanes", {})

    if lane not in lanes:
        raise HTTPException(400, f"Unknown lane: {lane}")

    # Update artists list
    lanes[lane]["artists"] = req.artists

    # If rotation lane, also update rotation_order
    if lanes[lane].get("schedule_mode") == "rotation":
        lanes[lane]["rotation_order"] = req.artists

    # If fixed lane with a single artist, update slot_artist
    if lanes[lane].get("schedule_mode") == "fixed" and req.artists:
        lanes[lane]["slot_artist"] = req.artists[0]

    # Sync artist_groups
    group_map = {"breakfast": "BreakfastArtists", "lunch": "LunchArtists", "dinner": "DinnerArtists"}
    group_key = group_map.get(lane)
    if group_key and "artist_groups" in cfg:
        cfg["artist_groups"][group_key] = req.artists

    # Sync daily_schedule
    slot_map = {"breakfast": "breakfast_slot", "lunch": "lunch_slot", "dinner": "dinner_slot"}
    slot_key = slot_map.get(lane)
    if slot_key and slot_key in cfg.get("daily_schedule", {}):
        ds = cfg["daily_schedule"][slot_key]
        if "rotation" in ds:
            ds["rotation"] = req.artists
        elif "artist" in ds:
            ds["artist"] = req.artists[0] if req.artists else ""

    cfg["lanes"] = lanes
    lanes_cfg.write_text(json.dumps(cfg, indent=2))

    return {"lane": lane, "artists": req.artists, "status": "ok"}


# ── Slot override — pick specific beats per slot ─────────────────────────────

class SlotOverrideRequest(BaseModel):
    slot_index: int
    stem: Optional[str] = None  # None = clear override (back to auto)


@router.put("/plan/slot")
async def override_slot_beat(req: SlotOverrideRequest, user: UserContext = Depends(require_admin)):
    """Override which beat goes into a specific slot.  Pass stem=null to clear."""
    log = _load_json(SCHEDULE_LOG)
    overrides = log.get("slot_overrides", {})

    key = str(req.slot_index)
    if req.stem:
        # Verify the beat exists
        meta_path = ROOT / "metadata" / f"{req.stem}.json"
        output_path = ROOT / "output" / f"{req.stem}.mp4"
        if not meta_path.exists():
            raise HTTPException(400, f"No metadata for stem: {req.stem}")
        if not output_path.exists():
            raise HTTPException(400, f"No rendered video for stem: {req.stem}")
        overrides[key] = req.stem
    else:
        overrides.pop(key, None)

    log["slot_overrides"] = overrides
    SCHEDULE_LOG.write_text(json.dumps(log, indent=2, default=str))
    return {"slot_index": req.slot_index, "stem": req.stem, "status": "ok"}


@router.delete("/plan/overrides")
async def clear_all_overrides(user: UserContext = Depends(require_admin)):
    """Clear all slot overrides — plan goes back to fully automatic."""
    log = _load_json(SCHEDULE_LOG)
    log.pop("slot_overrides", None)
    SCHEDULE_LOG.write_text(json.dumps(log, indent=2, default=str))
    return {"status": "cleared"}


@router.get("/available-beats")
async def get_available_beats(user: UserContext = Depends(require_admin)):
    """Return ALL rendered beats for the picker (includes uploaded ones too)."""
    meta_dir = ROOT / "metadata"
    out_dir = ROOT / "output"
    beats_dir = ROOT / "beats"
    beats = []
    for mp4 in sorted(out_dir.glob("*.mp4")):
        stem = mp4.stem
        if stem.endswith(("_9x16", "_thumb", "_lit")):
            continue
        meta_path = meta_dir / f"{stem}.json"
        if not meta_path.exists():
            continue
        meta = _load_json(meta_path)
        # Find the audio file for preview
        audio_file = None
        for ext in (".mp3", ".wav"):
            candidates = list(beats_dir.glob(f"*{ext}"))
            for c in candidates:
                import re
                s = c.stem.strip().lower()
                s = re.sub(r"[^\w\s-]", "", s)
                s = re.sub(r"[\s-]+", "_", s).strip("_")
                if s == stem:
                    audio_file = c.name
                    break
            if audio_file:
                break
        beats.append({
            "stem": stem,
            "name": meta.get("beat_name", "") or stem.replace("_", " ").title(),
            "artist": meta.get("seo_artist", meta.get("artist", "")),
            "lane": meta.get("lane", ""),
            "audio": audio_file,
        })
    return {"beats": beats}
