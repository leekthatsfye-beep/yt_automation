"""
health_svc.py — System health scanning service.

Scans the filesystem for data integrity issues, auto-patches safe problems,
and persists results to health_scan_log.json.

Runs every 60 minutes via the periodic loop in main.py.
"""

from __future__ import annotations

import json
import logging
import shutil
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from app.backend.config import ROOT, HEALTH_SCAN_LOG
from app.backend.services.beat_svc import safe_stem

logger = logging.getLogger(__name__)

SCAN_HISTORY_MAX = 48  # Keep ~48 hours of hourly scans


# ── JSON helpers ─────────────────────────────────────────────────────────


def _load_json(path: Path) -> dict[str, Any]:
    """Load a JSON file, returning empty dict on any error."""
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def _save_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(json.dumps(data, indent=2))


def load_scan_result() -> dict[str, Any]:
    """Load the last scan result from disk."""
    return _load_json(HEALTH_SCAN_LOG)


# ── Full scan ────────────────────────────────────────────────────────────


async def run_full_scan(
    beats_dir: Path,
    metadata_dir: Path,
    output_dir: Path,
    listings_dir: Path,
    uploads_log_path: Path,
    auto_patch: bool = True,
) -> dict[str, Any]:
    """
    Execute a full system health scan.

    Checks 8 categories, auto-patches safe issues, computes a health score,
    and persists results to HEALTH_SCAN_LOG.
    """
    start = time.monotonic()
    issues: dict[str, Any] = {}
    total_issues = 0
    auto_fixes = 0

    # ── 1. Collect all beat stems from audio files ────────────────────
    audio_files = list(beats_dir.glob("*.mp3")) + list(beats_dir.glob("*.wav"))
    all_stems = {safe_stem(f.name) for f in audio_files}

    # ── 2. Missing metadata ──────────────────────────────────────────
    missing_meta: list[dict[str, Any]] = []
    metadata_dir.mkdir(parents=True, exist_ok=True)
    for stem in sorted(all_stems):
        meta_path = metadata_dir / f"{stem}.json"
        if not meta_path.exists():
            fixed = False
            if auto_patch:
                try:
                    default_meta = {
                        "title": stem.replace("_", " ").title(),
                        "artist": "BiggKutt8",
                        "description": "",
                        "tags": ["type beat", "trap beat", "free beat"],
                    }
                    meta_path.write_text(json.dumps(default_meta, indent=2))
                    fixed = True
                    auto_fixes += 1
                    logger.info("Auto-patched missing metadata: %s", stem)
                except Exception as e:
                    logger.error("Auto-patch metadata failed for %s: %s", stem, e)
            missing_meta.append({"stem": stem, "auto_fixed": fixed})
            total_issues += 1
    issues["missing_metadata"] = missing_meta

    # ── 3. Orphaned metadata ─────────────────────────────────────────
    orphaned_meta: list[dict[str, Any]] = []
    if metadata_dir.exists():
        for meta_file in sorted(metadata_dir.glob("*.json")):
            stem = meta_file.stem
            if stem not in all_stems:
                orphaned_meta.append({
                    "stem": stem,
                    "file": str(meta_file.relative_to(ROOT)),
                })
                total_issues += 1
    issues["orphaned_metadata"] = orphaned_meta

    # ── 4. Orphaned listings ─────────────────────────────────────────
    orphaned_listings: list[dict[str, Any]] = []
    if listings_dir.exists():
        for listing_file in sorted(listings_dir.glob("*.json")):
            stem = listing_file.stem
            if stem not in all_stems:
                orphaned_listings.append({
                    "stem": stem,
                    "file": str(listing_file.relative_to(ROOT)),
                })
                total_issues += 1
    issues["orphaned_listings"] = orphaned_listings

    # ── 5. Invalid JSON ──────────────────────────────────────────────
    invalid_json: list[dict[str, Any]] = []
    for scan_dir in [metadata_dir, listings_dir]:
        if not scan_dir.exists():
            continue
        for json_file in sorted(scan_dir.glob("*.json")):
            try:
                json.loads(json_file.read_text())
            except json.JSONDecodeError as e:
                invalid_json.append({
                    "file": str(json_file.relative_to(ROOT)),
                    "error": str(e)[:120],
                })
                total_issues += 1
            except Exception:
                pass  # Permission errors etc — skip
    issues["invalid_json"] = invalid_json

    # ── 6. Missing renders ───────────────────────────────────────────
    missing_renders: list[dict[str, Any]] = []
    for stem in sorted(all_stems):
        video_path = output_dir / f"{stem}.mp4"
        if not video_path.exists():
            missing_renders.append({"stem": stem})
            total_issues += 1
    issues["missing_renders"] = missing_renders

    # ── 7. Stale upload log entries ──────────────────────────────────
    stale_uploads: list[dict[str, Any]] = []
    uploads_log = _load_json(uploads_log_path)
    for stem in sorted(uploads_log.keys()):
        if stem not in all_stems:
            stale_uploads.append({
                "stem": stem,
                "videoId": uploads_log[stem].get("videoId", ""),
            })
            total_issues += 1
    issues["stale_uploads"] = stale_uploads

    # ── 8. Integration health ────────────────────────────────────────
    integration_status = await _check_integrations()
    issues["integration_health"] = integration_status

    # ── 9. Disk space ────────────────────────────────────────────────
    disk = shutil.disk_usage(str(ROOT))
    free_gb = round(disk.free / (1024**3), 1)
    total_gb = round(disk.total / (1024**3), 1)
    used_pct = round((disk.used / disk.total) * 100, 1)
    disk_warning = used_pct > 90
    if disk_warning:
        total_issues += 1
    issues["disk_space"] = {
        "total_gb": total_gb,
        "free_gb": free_gb,
        "used_pct": used_pct,
        "warning": disk_warning,
    }

    # ── Calculate health score and level ─────────────────────────────
    # Use capped deductions so large numbers of expected items (like
    # missing renders) don't tank the score unreasonably.
    total_beats = len(all_stems) or 1
    render_pct = len(missing_renders) / total_beats  # 0.0–1.0

    deductions = (
        min(len(missing_meta) * 1, 10)        # Cap: 10pts max for missing metadata
        + min(len(orphaned_meta) * 0.5, 5)    # Cap: 5pts max
        + min(len(orphaned_listings) * 0.5, 5)  # Cap: 5pts max
        + len(invalid_json) * 3                # No cap: corrupt JSON is serious
        + render_pct * 15                      # 0–15pts based on % unrendered
        + min(len(stale_uploads) * 0.5, 5)     # Cap: 5pts max
        + sum(
            1
            for v in integration_status.values()
            if isinstance(v, dict) and not v.get("connected")
        )
        * 2
        + (10 if disk_warning else 0)
    )
    health_score = max(0, min(100, round(100 - deductions)))

    if health_score >= 80:
        health_level = "green"
    elif health_score >= 50:
        health_level = "yellow"
    else:
        health_level = "red"

    elapsed_ms = round((time.monotonic() - start) * 1000)

    # ── Build result ─────────────────────────────────────────────────
    now_iso = datetime.now(timezone.utc).isoformat()
    result: dict[str, Any] = {
        "last_scan_at": now_iso,
        "scan_duration_ms": elapsed_ms,
        "health_score": health_score,
        "health_level": health_level,
        "total_issues": total_issues,
        "auto_fixes_applied": auto_fixes,
        "issues": issues,
    }

    # Append to scan history (keep last N entries)
    existing = _load_json(HEALTH_SCAN_LOG)
    history = existing.get("scan_history", [])
    history.insert(0, {
        "at": now_iso,
        "score": health_score,
        "issues": total_issues,
        "fixes": auto_fixes,
    })
    result["scan_history"] = history[:SCAN_HISTORY_MAX]

    # Persist
    _save_json(HEALTH_SCAN_LOG, result)

    return result


# ── Integration health check ────────────────────────────────────────────


async def _check_integrations() -> dict[str, Any]:
    """Check integration health — mirrors system.py get_integrations_status logic."""
    import sys

    sys.path.insert(0, str(ROOT))
    status: dict[str, Any] = {}

    # YouTube
    yt_token_file = ROOT / "token.json"
    try:
        if yt_token_file.exists():
            from google.oauth2.credentials import Credentials

            creds = Credentials.from_authorized_user_file(str(yt_token_file))
            if creds.valid:
                status["youtube"] = {"connected": True, "detail": "Connected"}
            elif creds.expired and creds.refresh_token:
                status["youtube"] = {
                    "connected": False,
                    "detail": "Token expired (auto-refreshable)",
                }
            else:
                status["youtube"] = {"connected": False, "detail": "Token invalid"}
        else:
            status["youtube"] = {"connected": False, "detail": "Not connected"}
    except Exception:
        status["youtube"] = {"connected": False, "detail": "Check failed"}

    # Suno
    try:
        from app.backend.services.suno_svc import get_api_key

        suno_key = get_api_key()
        status["suno"] = {
            "connected": bool(suno_key),
            "detail": "API key configured" if suno_key else "API key not set",
        }
    except Exception:
        status["suno"] = {"connected": False, "detail": "Check failed"}

    # Replicate
    try:
        from app.backend.services.thumbnail_ai_svc import get_api_key as get_replicate_key

        replicate_key = get_replicate_key()
        status["replicate"] = {
            "connected": bool(replicate_key),
            "detail": "API key configured" if replicate_key else "API key not set",
        }
    except Exception:
        status["replicate"] = {"connected": False, "detail": "Check failed"}

    # Store credentials
    try:
        from app.backend.services.store_svc import get_store_credentials

        for platform in ("airbit", "beatstars"):
            creds = get_store_credentials(platform)
            status[platform] = {
                "connected": bool(creds and creds.get("api_key")),
                "detail": "Connected"
                if creds and creds.get("api_key")
                else "Not connected",
            }
    except Exception:
        for platform in ("airbit", "beatstars"):
            status[platform] = {"connected": False, "detail": "Check failed"}

    return status
