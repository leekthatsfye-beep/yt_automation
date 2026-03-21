"""
content_scheduler.py

Daily content orchestrator for FY3.
Schedules 6 pieces of content per day (3 Beat Videos + 3 YouTube Shorts)
by calling into the existing upload and social_upload pipelines.

Does NOT modify render.py, upload.py, social_upload.py, or schedule.py.
Reads existing metadata JSON files without changing their schema.
Stores its own state in content_schedule_log.json (new file, self-contained).

Usage (CLI):
    python content_scheduler.py                        # plan today (no execution)
    python content_scheduler.py --execute              # plan + queue uploads
    python content_scheduler.py --dry-run              # show what would happen
    python content_scheduler.py --status               # show scheduler state
    python content_scheduler.py --generate-short army  # generate Short for one beat
    python content_scheduler.py --date 2026-03-15      # plan for a specific date

Importable:
    from content_scheduler import run_daily_schedule, get_scheduler_status
"""

from __future__ import annotations

import argparse
import json
import logging
import random
import re
import subprocess
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any

# ── Paths (read-only references to existing project structure) ───────────────

ROOT        = Path(__file__).resolve().parent
BEATS_DIR   = ROOT / "beats"
META_DIR    = ROOT / "metadata"
OUT_DIR     = ROOT / "output"
LANES_CFG   = ROOT / "lanes_config.json"
UPLOADS_LOG = ROOT / "uploads_log.json"

# Scheduler's own state file — does not touch any existing log
SCHEDULE_LOG = ROOT / "content_schedule_log.json"

# ── Logging ──────────────────────────────────────────────────────────────────

logger = logging.getLogger("content_scheduler")

LOG_DIR = ROOT / "logs"
LOG_DIR.mkdir(exist_ok=True)
_file_handler = logging.FileHandler(LOG_DIR / "content_scheduler.log")
_file_handler.setFormatter(logging.Formatter("%(asctime)s  %(levelname)-8s  %(message)s"))
logger.addHandler(_file_handler)
logger.setLevel(logging.INFO)


def p(msg: str):
    """Print + log simultaneously so subprocess pipes and log file both see it."""
    print(msg, flush=True)
    logger.info(msg)


# ── Timezone ─────────────────────────────────────────────────────────────────

try:
    from zoneinfo import ZoneInfo
    EST = ZoneInfo("America/New_York")
except ImportError:
    EST = timezone(timedelta(hours=-5))  # type: ignore[assignment]

# ── JSON helpers ─────────────────────────────────────────────────────────────


def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def _save_json(path: Path, data: dict):
    path.write_text(json.dumps(data, indent=2, default=str))


def _safe_stem(name: str) -> str:
    """Normalize a filename to its stem (same logic as render.py)."""
    s = name.rsplit(".", 1)[0].strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s.strip("_")


# ══════════════════════════════════════════════════════════════════════════════
#  SETTINGS — fully configurable, no code edits needed
# ══════════════════════════════════════════════════════════════════════════════

DEFAULT_SETTINGS: dict[str, Any] = {
    # 6 daily slots: beat → short pairs, one per lane
    "slots": [
        {"time": "09:00", "type": "beat",  "lane": "breakfast", "label": "Morning Beat"},
        {"time": "11:30", "type": "short", "lane": "breakfast", "label": "Morning Short"},
        {"time": "14:00", "type": "beat",  "lane": "lunch",     "label": "Afternoon Beat"},
        {"time": "16:30", "type": "short", "lane": "lunch",     "label": "Afternoon Short"},
        {"time": "19:30", "type": "beat",  "lane": "dinner",    "label": "Evening Beat"},
        {"time": "22:00", "type": "short", "lane": "dinner",    "label": "Evening Short"},
    ],
    "beats_per_day": 3,
    "shorts_per_day": 3,
}


def load_settings() -> dict[str, Any]:
    """Load scheduler settings.  Persisted settings override defaults."""
    log = _load_json(SCHEDULE_LOG)
    saved = log.get("settings", {})
    merged = {**DEFAULT_SETTINGS, **saved}
    # Always keep the default slot structure unless explicitly overridden
    if "slots" not in saved:
        merged["slots"] = DEFAULT_SETTINGS["slots"]
    return merged


def save_settings(settings: dict[str, Any]):
    """Persist settings into the schedule log (non-destructive merge)."""
    log = _load_json(SCHEDULE_LOG)
    log["settings"] = settings
    _save_json(SCHEDULE_LOG, log)


# ══════════════════════════════════════════════════════════════════════════════
#  CLUSTER / LANE SYSTEM  (reads lanes_config.json — never writes to it)
# ══════════════════════════════════════════════════════════════════════════════

def _load_clusters() -> dict[str, list[str]]:
    """Read artist clusters from the existing lanes_config.json."""
    cfg = _load_json(LANES_CFG)
    lanes = cfg.get("lanes", {})

    clusters: dict[str, list[str]] = {}
    for key, data in lanes.items():
        artists = list(dict.fromkeys(
            data.get("artists", []) + data.get("rotation_order", [])
        ))
        if artists:
            clusters[key] = artists

    if not clusters:
        clusters = {
            "breakfast": ["Glokk40Spaz"],
            "lunch":     ["BiggKutt8"],
            "dinner":    ["Sexyy Red", "GloRilla", "Babyxsosa", "Sukihana"],
        }
    return clusters


def select_artist(lane: str, clusters: dict[str, list[str]] | None = None) -> str:
    if clusters is None:
        clusters = _load_clusters()
    pool = clusters.get(lane, [])
    if not pool:
        pool = [a for v in clusters.values() for a in v]
    return random.choice(pool) if pool else "BiggKutt8"


# ══════════════════════════════════════════════════════════════════════════════
#  BEAT SELECTION  (reads uploads_log.json and metadata/ — never writes)
# ══════════════════════════════════════════════════════════════════════════════

def _uploaded_stems() -> set[str]:
    return set(_load_json(UPLOADS_LOG).keys())


def _already_scheduled_stems() -> set[str]:
    log = _load_json(SCHEDULE_LOG)
    return set(log.get("scheduled_stems", []))


def _detect_lane(title: str, stem: str, hour: int, clusters: dict[str, list[str]]) -> str:
    """Best-effort lane detection: metadata → artist match → time-of-day."""
    # 1. Check metadata lane first
    meta = _load_json(META_DIR / f"{stem}.json")
    lane_from_meta = meta.get("lane", "")
    if lane_from_meta and lane_from_meta in clusters:
        return lane_from_meta

    # 2. Match artist name in title against cluster artists
    title_lower = title.lower()
    for lane, artists in clusters.items():
        for artist in artists:
            if artist.lower() in title_lower:
                return lane

    # 3. Fall back to time-of-day mapping
    if hour < 12:
        return "breakfast"
    elif hour < 17:
        return "lunch"
    else:
        return "dinner"


def get_youtube_scheduled_for_date(target: datetime | None = None) -> list[dict[str, Any]]:
    """Return YouTube-scheduled uploads whose publishAt falls on *target* date (EST).

    Each entry: {stem, title, time, url, videoId, publishAt, lane}
    Sorted by scheduled time.
    """
    if target is None:
        target = datetime.now(EST)

    target_str = target.strftime("%Y-%m-%d")
    uploads = _load_json(UPLOADS_LOG)
    clusters = _load_clusters()
    result: list[dict[str, Any]] = []

    for stem, info in uploads.items():
        pa = info.get("publishAt")
        if not pa:
            continue
        try:
            # Parse and convert to EST so date comparison and hour detection
            # work correctly regardless of whether publishAt is in UTC or EST.
            dt_raw = datetime.fromisoformat(pa)
            dt = dt_raw.astimezone(EST)
            if dt.strftime("%Y-%m-%d") != target_str:
                continue
            title = info.get("title", stem.replace("_", " ").title())
            result.append({
                "stem": stem,
                "title": title,
                "time": dt.strftime("%H:%M"),
                "time_est": dt.strftime("%-I:%M %p"),
                "url": info.get("url", ""),
                "videoId": info.get("videoId", ""),
                "publishAt": pa,
                "lane": _detect_lane(title, stem, dt.hour, clusters),
            })
        except (ValueError, TypeError):
            continue

    result.sort(key=lambda r: r["time"])
    return result


def get_rendered_unuploaded() -> list[str]:
    """Stems that have a rendered MP4 + metadata but are not yet uploaded."""
    uploaded = _uploaded_stems()
    scheduled = _already_scheduled_stems()

    ready: list[str] = []
    for mp4 in sorted(OUT_DIR.glob("*.mp4")):
        stem = mp4.stem
        if stem.endswith(("_9x16", "_thumb", "_lit")):
            continue
        if stem in uploaded or stem in scheduled:
            continue
        if (META_DIR / f"{stem}.json").exists():
            ready.append(stem)
    return ready


def select_beat(lane: str, exclude: set[str] | None = None) -> str | None:
    """Pick a beat for a lane.  Prefers lane-tagged beats, else any available."""
    if exclude is None:
        exclude = set()
    ready = get_rendered_unuploaded()

    # First pass: lane-tagged beats
    for stem in ready:
        if stem in exclude:
            continue
        meta = _load_json(META_DIR / f"{stem}.json")
        if meta.get("lane") == lane:
            return stem

    # Second pass: any unuploaded rendered beat
    for stem in ready:
        if stem in exclude:
            continue
        return stem

    return None


# ══════════════════════════════════════════════════════════════════════════════
#  TITLE GENERATION  (reads lanes_config.json templates — never writes)
# ══════════════════════════════════════════════════════════════════════════════

def _beat_name(stem: str) -> str:
    meta = _load_json(META_DIR / f"{stem}.json")
    return meta.get("beat_name", "") or stem.replace("_", " ").title()


def make_beat_title(stem: str, artist: str) -> str:
    """Full video title:  Artist Type Beat – "Beat Name" """
    cfg = _load_json(LANES_CFG)
    tpl = cfg.get("title_template", {}).get("single", '{artist} Type Beat - "{beat_name}"')
    return tpl.replace("{artist}", artist).replace("{beat_name}", _beat_name(stem))


def make_short_title(artist: str) -> str:
    """Shorts use a simple title — no beat name."""
    return f"{artist} Type Beat"


# ══════════════════════════════════════════════════════════════════════════════
#  SHORT GENERATION  (calls social_upload.convert_to_portrait — never modifies it)
# ══════════════════════════════════════════════════════════════════════════════

def generate_short(stem: str, force: bool = False) -> Path | None:
    """Create a 9:16 portrait Short by calling the existing converter.

    Returns the path to the Short video or None on failure.
    """
    short_path = OUT_DIR / f"{stem}_9x16.mp4"
    if short_path.exists() and not force:
        p(f"[Scheduler] Short already exists: {short_path.name}")
        return short_path

    if not (OUT_DIR / f"{stem}.mp4").exists():
        p(f"[Scheduler] ERROR — source video missing: {stem}.mp4")
        return None

    p(f"[Scheduler] Generating Short for {stem}...")
    try:
        # Import the existing converter without modifying it
        sys.path.insert(0, str(ROOT))
        from social_upload import convert_to_portrait  # type: ignore[import-untyped]
        result = convert_to_portrait(stem, force=force)
        if result.exists():
            p(f"[Scheduler] Short created for {stem}")
            return result
    except Exception as exc:
        p(f"[Scheduler] Short generation failed for {stem}: {exc}")
    return None


# ══════════════════════════════════════════════════════════════════════════════
#  DAILY PLANNER
# ══════════════════════════════════════════════════════════════════════════════

def plan_daily_content(target_date: datetime | None = None) -> dict[str, Any]:
    """Build a plan for one day: which beats go in which slots.

    Does NOT execute anything — pure read-only planning.
    Uses lane_optimizer.get_lane_priority() to order slots by performance
    when analytics data is available.
    """
    if target_date is None:
        target_date = datetime.now(EST)

    settings = load_settings()
    clusters = _load_clusters()
    used: set[str] = set()
    lane_beat_map: dict[str, dict[str, str]] = {}  # lane → {stem, artist}
    plan_slots: list[dict[str, Any]] = []

    # Get lane priority from optimizer (falls back to default order if no data)
    lane_priority: list[str] = []
    try:
        from lane_optimizer import get_lane_priority
        lane_priority = get_lane_priority()
        p(f"[Scheduler] Lane priority: {' → '.join(lane_priority)}")
    except Exception as exc:
        logger.debug("Lane optimizer unavailable: %s", exc)

    # Reorder slots so higher-priority lanes get earlier time slots
    slot_defs = list(settings["slots"])
    if lane_priority and len(lane_priority) >= 2:
        # Group beat/short pairs by lane
        lane_pairs: dict[str, list[dict]] = {}
        for sd in slot_defs:
            lane_pairs.setdefault(sd["lane"], []).append(sd)

        # Sort lanes by priority (best-performing first)
        sorted_lanes = sorted(
            lane_pairs.keys(),
            key=lambda l: lane_priority.index(l) if l in lane_priority else 999,
        )

        # Collect the time slots in order and reassign lanes
        beat_times  = sorted(sd["time"] for sd in slot_defs if sd["type"] == "beat")
        short_times = sorted(sd["time"] for sd in slot_defs if sd["type"] == "short")

        # Lane display names fixed to time-of-day: breakfast=morning, lunch=afternoon, dinner=evening
        fixed_lane_names = ["breakfast", "lunch", "dinner"]

        reordered: list[dict] = []
        for i, lane in enumerate(sorted_lanes):
            if i < len(beat_times):
                pair = lane_pairs[lane]
                beat_def  = next((s for s in pair if s["type"] == "beat"), None)
                short_def = next((s for s in pair if s["type"] == "short"), None)
                # Keep source_lane for artist selection, set display lane to match time
                display_lane = fixed_lane_names[i] if i < len(fixed_lane_names) else lane
                if beat_def:
                    reordered.append({**beat_def, "time": beat_times[i],
                                      "source_lane": lane, "lane": display_lane})
                if short_def and i < len(short_times):
                    reordered.append({**short_def, "time": short_times[i],
                                      "source_lane": lane, "lane": display_lane})

        if len(reordered) == len(slot_defs):
            # Regenerate labels based on the NEW time slots
            for sd in reordered:
                h = int(sd["time"].split(":")[0])
                period = "Morning" if h < 12 else "Afternoon" if h < 17 else "Evening"
                kind = "Beat" if sd["type"] == "beat" else "Short"
                sd["label"] = f"{period} {kind}"
            slot_defs = sorted(reordered, key=lambda s: s["time"])

    for slot_def in slot_defs:
        lane      = slot_def.get("source_lane", slot_def["lane"])  # use source for selection
        display_lane = slot_def["lane"]  # use display lane for UI
        slot_type = slot_def["type"]
        hour, minute = map(int, slot_def["time"].split(":"))

        slot_dt  = datetime(target_date.year, target_date.month, target_date.day,
                            hour, minute, 0, tzinfo=EST)
        slot_utc = slot_dt.astimezone(timezone.utc).isoformat()
        slot_est = slot_dt.strftime("%Y-%m-%d %-I:%M %p")

        base = {
            "slot": slot_utc, "slot_est": slot_est,
            "time": slot_def["time"], "type": slot_type,
            "lane": display_lane, "label": slot_def["label"],
        }

        if slot_type == "beat":
            stem   = select_beat(lane, exclude=used)
            artist = select_artist(lane, clusters)
            if stem:
                used.add(stem)
                title = make_beat_title(stem, artist)
                lane_beat_map[lane] = {"stem": stem, "artist": artist}
                plan_slots.append({**base, "stem": stem, "artist": artist,
                                   "title": title, "status": "planned"})
            else:
                plan_slots.append({**base, "stem": None, "artist": select_artist(lane, clusters),
                                   "title": None, "status": "no_beats_available"})

        elif slot_type == "short":
            info   = lane_beat_map.get(lane, {})
            stem   = info.get("stem")
            artist = info.get("artist") or select_artist(lane, clusters)
            if stem:
                plan_slots.append({
                    **base, "stem": stem, "artist": artist,
                    "title": make_short_title(artist),
                    "has_short_video": (OUT_DIR / f"{stem}_9x16.mp4").exists(),
                    "status": "planned",
                })
            else:
                plan_slots.append({**base, "stem": None, "artist": artist,
                                   "title": None, "has_short_video": False,
                                   "status": "no_beats_available"})

    beats_ok  = sum(1 for s in plan_slots if s["type"] == "beat"  and s["stem"])
    shorts_ok = sum(1 for s in plan_slots if s["type"] == "short" and s["stem"])
    shorts_rdy = sum(1 for s in plan_slots if s["type"] == "short" and s.get("has_short_video"))

    # Include YouTube-scheduled uploads for this date
    yt_scheduled = get_youtube_scheduled_for_date(target_date)

    return {
        "date": target_date.strftime("%Y-%m-%d"),
        "slots": plan_slots,
        "youtube_scheduled": yt_scheduled,
        "summary": {
            "total_slots": len(plan_slots),
            "beats_planned": beats_ok,
            "shorts_planned": shorts_ok,
            "shorts_ready": shorts_rdy,
            "shorts_need_generation": shorts_ok - shorts_rdy,
            "youtube_on_date": len(yt_scheduled),
        },
        "clusters": clusters,
        "lane_priority": lane_priority,
        "planned_at": datetime.now(timezone.utc).isoformat(),
    }


# ══════════════════════════════════════════════════════════════════════════════
#  EXECUTOR  — calls upload.py and social_upload via subprocess / import
# ══════════════════════════════════════════════════════════════════════════════

def _venv_python() -> str:
    """Return the .venv python so subprocesses use the right interpreter."""
    venv = ROOT / ".venv" / "bin" / "python3.14"
    return str(venv) if venv.exists() else sys.executable


def _schedule_beat_upload(stem: str, schedule_time: str) -> dict[str, Any]:
    """Call upload.py --only <stem> --schedule-at <time> as a subprocess.

    Returns {"ok": True} or {"ok": False, "error": "..."}.
    """
    cmd = [_venv_python(), str(ROOT / "upload.py"),
           "--only", stem, "--schedule-at", schedule_time]
    try:
        proc = subprocess.run(cmd, capture_output=True, text=True,
                              cwd=str(ROOT), timeout=300)
        if proc.returncode == 0:
            return {"ok": True, "stdout": proc.stdout[-300:]}
        return {"ok": False, "error": proc.stderr[:300]}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def _upload_short(stem: str) -> dict[str, Any]:
    """Upload a Short by importing the existing youtube_shorts_upload function.

    Returns {"ok": True, "videoId": "..."} or {"ok": False, "error": "..."}.
    """
    try:
        sys.path.insert(0, str(ROOT))
        from social_upload import youtube_shorts_upload  # type: ignore[import-untyped]
        result = youtube_shorts_upload(stem, privacy="public")
        if result.get("status") == "ok":
            return {"ok": True, "videoId": result.get("videoId", "")}
        return {"ok": False, "error": result.get("error", "unknown")}
    except Exception as exc:
        return {"ok": False, "error": str(exc)[:300]}


def execute_daily_plan(
    plan: dict[str, Any] | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Walk the plan slots and call the existing pipelines for each one.

    • Beat slots  → upload.py --schedule-at (existing upload pipeline)
    • Short slots → social_upload.youtube_shorts_upload (existing Shorts pipeline)

    On any failure the slot is skipped and the pipeline continues.
    """
    if plan is None:
        plan = plan_daily_content()

    log_data    = _load_json(SCHEDULE_LOG)
    sched_stems = set(log_data.get("scheduled_stems", []))
    results: list[dict[str, Any]] = []

    for slot in plan["slots"]:
        stem = slot.get("stem")
        if not stem:
            results.append({**slot, "execution": "skipped", "reason": "No beat available"})
            continue

        # ── Beat slot ─────────────────────────────────────────────────
        if slot["type"] == "beat":
            p(f"[Scheduler] Beat scheduled: {slot['artist']} – {_beat_name(stem)}")
            p(f"[Scheduler] Upload scheduled for {slot['time']}")

            if dry_run:
                results.append({**slot, "execution": "dry_run"})
                continue

            # Verify source video exists (rendered by the existing render.py)
            if not (OUT_DIR / f"{stem}.mp4").exists():
                reason = f"{stem}.mp4 not rendered — run render.py first"
                p(f"[Scheduler] SKIP — {reason}")
                results.append({**slot, "execution": "skipped", "reason": reason})
                continue

            res = _schedule_beat_upload(stem, slot["slot"])
            if res["ok"]:
                sched_stems.add(stem)
                p(f"[Scheduler] {stem} queued for {slot['time']} ✓")
                results.append({**slot, "execution": "scheduled"})
            else:
                p(f"[Scheduler] ERROR scheduling {stem}: {res['error']}")
                results.append({**slot, "execution": "error", "reason": res["error"]})

        # ── Short slot ────────────────────────────────────────────────
        elif slot["type"] == "short":
            p(f"[Scheduler] Short created for {_beat_name(stem)}")

            if dry_run:
                results.append({**slot, "execution": "dry_run"})
                continue

            # Generate 9:16 if it doesn't exist
            short_path = generate_short(stem)
            if not short_path:
                p(f"[Scheduler] SKIP Short — generation failed for {stem}")
                results.append({**slot, "execution": "error",
                                "reason": "Short generation failed"})
                continue

            res = _upload_short(stem)
            if res["ok"]:
                p(f"[Scheduler] Short uploaded for {stem} ✓")
                results.append({**slot, "execution": "uploaded",
                                "video_id": res.get("videoId", "")})
            else:
                p(f"[Scheduler] ERROR uploading Short {stem}: {res['error']}")
                results.append({**slot, "execution": "error", "reason": res["error"]})

        # Respect API rate limits
        if not dry_run:
            time.sleep(2)

    # ── Persist scheduler state (own log only) ────────────────────────
    if not dry_run:
        log_data["scheduled_stems"] = sorted(sched_stems)
        log_data["last_execution"]  = datetime.now(timezone.utc).isoformat()
        log_data["last_plan_date"]  = plan.get("date", "")

        history = log_data.get("execution_history", [])
        history.append({
            "date": plan.get("date", ""),
            "executed_at": datetime.now(timezone.utc).isoformat(),
            "beats_scheduled": sum(1 for r in results
                                   if r["type"] == "beat" and r["execution"] == "scheduled"),
            "shorts_uploaded": sum(1 for r in results
                                   if r["type"] == "short" and r["execution"] == "uploaded"),
            "errors": sum(1 for r in results if r["execution"] == "error"),
        })
        log_data["execution_history"] = history[-30:]
        _save_json(SCHEDULE_LOG, log_data)

    return {
        "plan": plan,
        "results": results,
        "summary": {
            "beats_scheduled": sum(1 for r in results
                                   if r["type"] == "beat" and r["execution"] == "scheduled"),
            "shorts_uploaded": sum(1 for r in results
                                   if r["type"] == "short" and r["execution"] == "uploaded"),
            "dry_run_count":   sum(1 for r in results if r["execution"] == "dry_run"),
            "errors":          sum(1 for r in results if r["execution"] == "error"),
            "skipped":         sum(1 for r in results if r["execution"] == "skipped"),
        },
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PUBLIC ENTRY POINT
# ══════════════════════════════════════════════════════════════════════════════

def run_daily_schedule(
    target_date: datetime | None = None,
    dry_run: bool = False,
) -> dict[str, Any]:
    """Build the next day's schedule and queue tasks through the existing pipelines.

    This is the single main function the backend / cron should call.
    """
    plan   = plan_daily_content(target_date=target_date)
    result = execute_daily_plan(plan=plan, dry_run=dry_run)
    return result


# ══════════════════════════════════════════════════════════════════════════════
#  STATUS  (read-only introspection for the frontend)
# ══════════════════════════════════════════════════════════════════════════════

def get_scheduler_status() -> dict[str, Any]:
    """Comprehensive status payload for the frontend dashboard."""
    sched_log   = _load_json(SCHEDULE_LOG)
    uploads_log = _load_json(UPLOADS_LOG)
    clusters    = _load_clusters()
    settings    = load_settings()

    rendered = get_rendered_unuploaded()
    bpd      = settings.get("beats_per_day", 3)

    lane_counts: dict[str, int] = {}
    for stem in rendered:
        meta = _load_json(META_DIR / f"{stem}.json")
        lane_counts[meta.get("lane", "unassigned")] = lane_counts.get(
            meta.get("lane", "unassigned"), 0) + 1

    shorts_ready = sum(1 for s in rendered if (OUT_DIR / f"{s}_9x16.mp4").exists())

    # Get lane optimizer data (safe — never crashes status endpoint)
    optimizer_data: dict[str, Any] = {}
    try:
        from lane_optimizer import get_optimization_report
        optimizer_data = get_optimization_report()
    except Exception:
        optimizer_data = {"ranked_lanes": list(clusters.keys()), "scores": {}, "has_data": False}

    return {
        "total_beats":       len(list(BEATS_DIR.glob("*.mp3")) + list(BEATS_DIR.glob("*.wav"))),
        "total_uploaded":    len(uploads_log),
        "rendered_ready":    len(rendered),
        "shorts_ready":      shorts_ready,
        "shorts_needed":     len(rendered) - shorts_ready,
        "buffer_days":       round(len(rendered) / bpd, 1) if bpd else 0,
        "beats_per_day":     bpd,
        "beats_by_lane":     lane_counts,
        "clusters":          clusters,
        "settings":          settings,
        "last_execution":    sched_log.get("last_execution", ""),
        "last_plan_date":    sched_log.get("last_plan_date", ""),
        "execution_history": sched_log.get("execution_history", [])[-7:],
        "scheduled_pending": len(sched_log.get("scheduled_stems", [])),
        "optimizer":         optimizer_data,
    }


# ══════════════════════════════════════════════════════════════════════════════
#  PRETTY PRINTERS
# ══════════════════════════════════════════════════════════════════════════════

def _print_plan(plan: dict[str, Any]):
    p("")
    p("=" * 62)
    p(f"  DAILY CONTENT PLAN — {plan['date']}")
    p("=" * 62)
    for s in plan["slots"]:
        icon = "\U0001f3b5" if s["type"] == "beat" else "\U0001f4f1"
        p(f"  {s['time']}  {icon}  [{s['lane'].upper():9s}]  {s['label']}")
        if s.get("stem"):
            p(f"           {s['artist']} — {_beat_name(s['stem'])}")
        else:
            p(f"           (no beats available)")
        p("")
    sm = plan["summary"]
    p(f"  Beats: {sm['beats_planned']}/3  |  Shorts: {sm['shorts_planned']}/3"
      f"  |  Shorts ready: {sm['shorts_ready']}")
    p("=" * 62)


def _print_status(st: dict[str, Any]):
    p("")
    p("=" * 62)
    p("  CONTENT SCHEDULER STATUS")
    p("=" * 62)
    p(f"  Total beats:         {st['total_beats']}")
    p(f"  Uploaded:            {st['total_uploaded']}")
    p(f"  Rendered & ready:    {st['rendered_ready']}")
    p(f"  Buffer:              {st['buffer_days']} days ({st['beats_per_day']}/day)")
    p(f"  Shorts ready:        {st['shorts_ready']}")
    p(f"  Shorts needed:       {st['shorts_needed']}")
    p(f"  Pending scheduled:   {st['scheduled_pending']}")
    if st["beats_by_lane"]:
        p("  Beats by lane:")
        for lane, cnt in sorted(st["beats_by_lane"].items()):
            p(f"    {lane:15s}  {cnt}")
    if st["clusters"]:
        p("  Clusters:")
        for lane, artists in st["clusters"].items():
            p(f"    {lane:15s}  {', '.join(artists)}")
    if st.get("last_execution"):
        p(f"  Last run: {st['last_execution'][:19]}")
    if st.get("execution_history"):
        p("  Recent:")
        for e in st["execution_history"][-5:]:
            p(f"    {e['date']}  beats={e.get('beats_scheduled',0)}"
              f"  shorts={e.get('shorts_uploaded',0)}  err={e.get('errors',0)}")
    p("=" * 62)


# ══════════════════════════════════════════════════════════════════════════════
#  CLI
# ══════════════════════════════════════════════════════════════════════════════

def main():
    ap = argparse.ArgumentParser(description="FY3 Content Scheduler")
    ap.add_argument("--execute",  action="store_true", help="Plan + execute uploads")
    ap.add_argument("--dry-run",  action="store_true", help="Plan + show without executing")
    ap.add_argument("--status",   action="store_true", help="Print scheduler status")
    ap.add_argument("--generate-short", metavar="STEM", help="Generate Short for one beat")
    ap.add_argument("--date",     metavar="YYYY-MM-DD", help="Target date (default: today)")
    args = ap.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.status:
        _print_status(get_scheduler_status())
        return

    if args.generate_short:
        path = generate_short(args.generate_short, force=True)
        sys.exit(0 if path else 1)

    target = None
    if args.date:
        try:
            target = datetime.strptime(args.date, "%Y-%m-%d").replace(tzinfo=EST)
        except ValueError:
            p(f"[ERROR] Bad date: {args.date}")
            sys.exit(1)

    plan = plan_daily_content(target_date=target)
    _print_plan(plan)

    if args.execute or args.dry_run:
        res = execute_daily_plan(plan=plan, dry_run=args.dry_run)
        sm  = res["summary"]
        p(f"\nResult: {sm['beats_scheduled']} beats, {sm['shorts_uploaded']} shorts, "
          f"{sm['errors']} errors, {sm['skipped']} skipped")
        if args.dry_run:
            p("[DRY RUN] No changes were made.")


if __name__ == "__main__":
    main()
