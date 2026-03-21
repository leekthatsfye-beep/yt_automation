"""
youtube_manager.py

Channel-wide YouTube catalog manager for FY3.
Connects to YouTube Data API v3 to scan, validate, fix, and report on
every video in the channel.

Usage (CLI):
    python youtube_manager.py                      # full scan + report (no fixes)
    python youtube_manager.py --fix                 # scan + auto-fix problems
    python youtube_manager.py --report-only         # just print the health report
    python youtube_manager.py --scan-only           # scan + dump issues JSON
    python youtube_manager.py --dry-run --fix       # show what would be fixed

Can also be imported:
    from youtube_manager import (
        scan_channel,
        fix_metadata,
        generate_tags,
        generate_report,
        run_daily_scan,
    )
"""

from __future__ import annotations

import argparse
import json
import logging
import re
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from youtube_auth import get_youtube_service

# ── Paths ────────────────────────────────────────────────────────────────────

ROOT               = Path(__file__).resolve().parent
META_DIR           = ROOT / "metadata"
UPLOADS_LOG        = ROOT / "uploads_log.json"
STORE_LOG          = ROOT / "store_uploads_log.json"
LANES_CFG_PATH     = ROOT / "lanes_config.json"
HEALTH_REPORT_PATH = ROOT / "channel_health_report.json"

# ── Logging ──────────────────────────────────────────────────────────────────

logger = logging.getLogger("youtube_manager")


def p(msg: str):
    """Print with flush for real-time subprocess output."""
    print(msg, flush=True)


# ── Config helpers ───────────────────────────────────────────────────────────

def _load_json(path: Path) -> dict:
    try:
        if path.exists():
            return json.loads(path.read_text())
    except Exception:
        pass
    return {}


def _load_lanes_config() -> dict:
    return _load_json(LANES_CFG_PATH)


def _get_store_profile_url() -> str:
    cfg = _load_lanes_config()
    return cfg.get("store_profile_url", "")


def _get_producer() -> str:
    cfg = _load_lanes_config()
    return cfg.get("producer", "leekthatsfy3")


# ── Duration helpers ─────────────────────────────────────────────────────────

_DURATION_RE = re.compile(r"PT(?:(\d+)H)?(?:(\d+)M)?(?:(\d+)S)?")


def _parse_duration_seconds(iso_dur: str) -> int:
    """Parse ISO 8601 duration (e.g. PT3M45S) → total seconds."""
    m = _DURATION_RE.match(iso_dur or "")
    if not m:
        return 0
    h, mn, s = (int(g) if g else 0 for g in m.groups())
    return h * 3600 + mn * 60 + s


def is_short(video: dict[str, Any]) -> bool:
    """Determine if a video is a YouTube Short (≤60 seconds)."""
    dur = _parse_duration_seconds(video.get("duration", ""))
    return 0 < dur <= 60


# ── YouTube API helpers ──────────────────────────────────────────────────────

def _fetch_all_channel_videos(youtube) -> list[dict[str, Any]]:
    """Fetch every video on the authenticated channel via YouTube Data API.

    Uses channels.list → contentDetails.relatedPlaylists.uploads to get the
    uploads playlist, then paginates through playlistItems, then batch-fetches
    full video details (snippet + status + statistics) 50 at a time.
    """
    # Step 1: Get the uploads playlist ID
    ch_resp = youtube.channels().list(
        part="contentDetails",
        mine=True,
    ).execute()

    items = ch_resp.get("items", [])
    if not items:
        raise RuntimeError("No channel found for authenticated account")

    uploads_playlist = items[0]["contentDetails"]["relatedPlaylists"]["uploads"]
    p(f"[SCAN] Uploads playlist: {uploads_playlist}")

    # Step 2: Page through all playlist items to collect video IDs
    video_ids: list[str] = []
    next_page = None

    while True:
        pl_resp = youtube.playlistItems().list(
            part="contentDetails",
            playlistId=uploads_playlist,
            maxResults=50,
            pageToken=next_page,
        ).execute()

        for item in pl_resp.get("items", []):
            vid = item["contentDetails"]["videoId"]
            video_ids.append(vid)

        next_page = pl_resp.get("nextPageToken")
        if not next_page:
            break

    p(f"[SCAN] Found {len(video_ids)} video(s) on channel")

    # Step 3: Batch-fetch full details 50 at a time
    videos: list[dict[str, Any]] = []

    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        v_resp = youtube.videos().list(
            part="snippet,status,statistics,contentDetails",
            id=",".join(batch),
        ).execute()

        for v in v_resp.get("items", []):
            snippet = v.get("snippet", {})
            status = v.get("status", {})
            stats = v.get("statistics", {})

            videos.append({
                "video_id":    v["id"],
                "title":       snippet.get("title", ""),
                "description": snippet.get("description", ""),
                "tags":        snippet.get("tags", []),
                "category_id": snippet.get("categoryId", ""),
                "published_at": snippet.get("publishedAt", ""),
                "privacy":     status.get("privacyStatus", ""),
                "upload_status": status.get("uploadStatus", ""),
                "license":     status.get("license", ""),
                "view_count":  int(stats.get("viewCount", 0)),
                "like_count":  int(stats.get("likeCount", 0)),
                "comment_count": int(stats.get("commentCount", 0)),
                "duration":    v.get("contentDetails", {}).get("duration", ""),
            })

        # Be polite to quota
        if i + 50 < len(video_ids):
            time.sleep(0.5)

    return videos


# ── Artist detection ─────────────────────────────────────────────────────────

_TYPE_BEAT_RE = re.compile(
    r'^(.+?)\s+[Tt]ype\s+[Bb]eat',
    re.IGNORECASE,
)

# Dual artist: require whitespace around the "x" separator so "Sexyy" isn't split
_DUAL_ARTIST_RE = re.compile(
    r'^(.+?)\s+[xX×]\s+(.+?)\s+[Tt]ype\s+[Bb]eat',
    re.IGNORECASE,
)


def detect_artist(title: str) -> str | None:
    """Extract artist name from a 'Type Beat' title.

    Handles:
      - "Glokk40Spaz Type Beat – Midnight Run" → "Glokk40Spaz"
      - "BiggKutt8 x Glokk40Spaz Type Beat - Army" → "BiggKutt8"
      - "Sexyy Red Type Beat 2026" → "Sexyy Red"
    """
    # Try dual artist first
    m = _DUAL_ARTIST_RE.match(title)
    if m:
        return m.group(1).strip().strip('"').strip("'")

    m = _TYPE_BEAT_RE.match(title)
    if m:
        return m.group(1).strip().strip('"').strip("'")

    return None


def detect_all_artists(title: str) -> list[str]:
    """Extract all artist names from the title."""
    m = _DUAL_ARTIST_RE.match(title)
    if m:
        return [m.group(1).strip().strip('"'), m.group(2).strip().strip('"')]

    m = _TYPE_BEAT_RE.match(title)
    if m:
        return [m.group(1).strip().strip('"')]

    return []


# ── SEO tag generator ────────────────────────────────────────────────────────

def generate_tags(artist: str, beat_name: str = "", year: int = 2026) -> list[str]:
    """Generate SEO-optimized tags for a beat video.

    Args:
        artist: Primary artist name (e.g. "Glokk40Spaz")
        beat_name: Optional beat name for beat-specific tags
        year: Year for time-relevant tags

    Returns:
        List of 15-25 SEO tags
    """
    tags = []

    # Primary artist tags
    tags.extend([
        f"{artist} type beat",
        f"{artist} instrumental",
        f"{artist} type beat {year}",
        f"{artist} type beat free",
        f"{artist} beat",
        f"type beat {artist}",
    ])

    # Beat name tags
    if beat_name:
        clean = beat_name.strip('"').strip("'")
        tags.extend([
            f"{artist} type beat {clean}",
            f"{clean} type beat",
            f"{clean} instrumental",
        ])

    # Generic SEO tags
    tags.extend([
        "type beat",
        f"type beat {year}",
        "rap instrumental",
        "trap beat",
        "trap instrumental",
        "hip hop instrumental",
        f"rap beat {year}",
        "free type beat",
        "beats for sale",
        "buy beats online",
    ])

    # Deduplicate case-insensitively while preserving order
    seen: set[str] = set()
    unique: list[str] = []
    for t in tags:
        low = t.lower()
        if low not in seen:
            seen.add(low)
            unique.append(t)

    return unique


# ── Channel scan ─────────────────────────────────────────────────────────────

def scan_channel(youtube=None) -> dict[str, Any]:
    """Scan every video on the channel and detect metadata problems.

    Returns a dict with:
        - videos: list of video dicts with issues attached
        - issues: aggregated issue list
        - summary: counts by issue type
    """
    if youtube is None:
        p("[AUTH] Authenticating with YouTube...")
        youtube = get_youtube_service()
        p("[AUTH] Authenticated ✓")

    videos = _fetch_all_channel_videos(youtube)
    store_data = _load_json(STORE_LOG)
    store_profile = _get_store_profile_url()
    uploads_log = _load_json(UPLOADS_LOG)

    # Build reverse lookup: videoId → stem
    vid_to_stem: dict[str, str] = {}
    for stem, entry in uploads_log.items():
        vid = entry.get("videoId", "")
        if vid:
            vid_to_stem[vid] = stem

    all_issues: list[dict[str, Any]] = []
    flagged_videos: list[dict[str, Any]] = []

    for video in videos:
        vid_issues: list[dict[str, str]] = []
        vid_id = video["video_id"]
        title = video["title"]
        desc = video["description"]
        tags = video["tags"]
        stem = vid_to_stem.get(vid_id, "")

        # ── Check 1: Missing purchase link ────────────────────────────
        has_purchase = (
            "airbit.com" in desc.lower()
            or "beatstars.com" in desc.lower()
            or "Purchase" in desc
        )
        if not has_purchase:
            issue = {
                "video_id": vid_id,
                "stem": stem,
                "title": title,
                "type": "missing_purchase_link",
                "severity": "high",
                "message": "Description missing purchase/store link",
                "auto_fixable": True,
            }
            vid_issues.append(issue)
            all_issues.append(issue)

        # ── Check 2: Title format (must contain "Type Beat") ──────────
        if "type beat" not in title.lower():
            issue = {
                "video_id": vid_id,
                "stem": stem,
                "title": title,
                "type": "weak_title",
                "severity": "medium",
                "message": f"Title missing 'Type Beat': {title}",
                "auto_fixable": False,  # needs artist assignment
            }
            vid_issues.append(issue)
            all_issues.append(issue)

        # ── Check 3: Missing / insufficient tags ─────────────────────
        if not tags:
            issue = {
                "video_id": vid_id,
                "stem": stem,
                "title": title,
                "type": "missing_tags",
                "severity": "high",
                "message": "Video has zero tags",
                "auto_fixable": True,
            }
            vid_issues.append(issue)
            all_issues.append(issue)
        elif len(tags) < 5:
            issue = {
                "video_id": vid_id,
                "stem": stem,
                "title": title,
                "type": "low_tags",
                "severity": "medium",
                "message": f"Only {len(tags)} tags (need 5+)",
                "auto_fixable": True,
            }
            vid_issues.append(issue)
            all_issues.append(issue)

        # ── Check 4: Missing producer credit ──────────────────────────
        producer = _get_producer()
        if producer.lower() not in desc.lower() and "prod." not in desc.lower():
            issue = {
                "video_id": vid_id,
                "stem": stem,
                "title": title,
                "type": "missing_producer_credit",
                "severity": "low",
                "message": "Description missing producer credit",
                "auto_fixable": True,
            }
            vid_issues.append(issue)
            all_issues.append(issue)

        # ── Check 5: Stale purchase link (general store but specific available)
        if stem and store_data:
            entry = store_data.get(stem, {})
            airbit_entry = entry.get("airbit", entry) if isinstance(entry, dict) else {}
            beat_url = airbit_entry.get("url", "")
            if beat_url and "/beats/" in beat_url and beat_url not in desc:
                if has_purchase:  # has a link, but it's the general one
                    issue = {
                        "video_id": vid_id,
                        "stem": stem,
                        "title": title,
                        "type": "stale_purchase_link",
                        "severity": "medium",
                        "message": "Has general store link but specific beat link available",
                        "auto_fixable": True,
                    }
                    vid_issues.append(issue)
                    all_issues.append(issue)

        # ── Check 6: Description contains "free" devaluing the beat ───
        desc_lower = desc.lower()
        if "free download" in desc_lower or "free beat" in desc_lower:
            issue = {
                "video_id": vid_id,
                "stem": stem,
                "title": title,
                "type": "free_language",
                "severity": "low",
                "message": "Description uses 'free' language (devalues beats)",
                "auto_fixable": False,
            }
            vid_issues.append(issue)
            all_issues.append(issue)

        # ── Check 7: Category not set to Music (10) ──────────────────
        if video.get("category_id") != "10":
            issue = {
                "video_id": vid_id,
                "stem": stem,
                "title": title,
                "type": "wrong_category",
                "severity": "low",
                "message": f"Category is {video.get('category_id', '?')}, should be 10 (Music)",
                "auto_fixable": True,
            }
            vid_issues.append(issue)
            all_issues.append(issue)

        video["stem"] = stem
        video["issues"] = vid_issues
        video["issue_count"] = len(vid_issues)

        if vid_issues:
            flagged_videos.append(video)

    # Build summary
    issue_types: dict[str, int] = {}
    for issue in all_issues:
        t = issue["type"]
        issue_types[t] = issue_types.get(t, 0) + 1

    summary = {
        "total_videos": len(videos),
        "flagged_videos": len(flagged_videos),
        "clean_videos": len(videos) - len(flagged_videos),
        "total_issues": len(all_issues),
        "auto_fixable": sum(1 for i in all_issues if i.get("auto_fixable")),
        "by_type": issue_types,
        "by_severity": {
            "high": sum(1 for i in all_issues if i["severity"] == "high"),
            "medium": sum(1 for i in all_issues if i["severity"] == "medium"),
            "low": sum(1 for i in all_issues if i["severity"] == "low"),
        },
    }

    return {
        "videos": videos,
        "flagged_videos": flagged_videos,
        "issues": all_issues,
        "summary": summary,
        "scanned_at": datetime.now(timezone.utc).isoformat(),
    }


# ── Auto-fix system ─────────────────────────────────────────────────────────

def _build_fixed_description(stem: str) -> str:
    """Build the standard Format A description for a beat."""
    store_data = _load_json(STORE_LOG)
    store_profile = _get_store_profile_url()
    producer = _get_producer()

    entry = store_data.get(stem, {})
    airbit_entry = entry.get("airbit", entry) if isinstance(entry, dict) else {}
    beat_url = airbit_entry.get("url", "")

    if beat_url and beat_url != store_profile:
        purchase_link = beat_url
        if store_profile:
            purchase_link += f"\n\nBrowse all beats:\n{store_profile}"
    elif store_profile:
        purchase_link = store_profile
    else:
        purchase_link = "[Link in bio]"

    return f"Purchase / Download\n{purchase_link}\n\nprod. {producer}"


def _sanitize_tags(raw_tags: list) -> list[str]:
    """Sanitize tags for YouTube API compliance."""
    seen: set[str] = set()
    clean: list[str] = []
    total = 0

    for t in raw_tags:
        if not isinstance(t, str):
            continue
        t = t.strip()
        if not t:
            continue
        t = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', t).strip()
        if not t:
            continue
        if re.search(r'[<>&",]', t):
            t = re.sub(r'[<>&",]', '', t).strip()
            if not t:
                continue
        t = t[:30].strip()
        if not t:
            continue
        lower = t.lower()
        if lower in seen:
            continue
        seen.add(lower)
        if total + len(t) > 450:
            break
        clean.append(t)
        total += len(t)

    return clean


def fix_metadata(video: dict[str, Any], youtube=None, dry_run: bool = False) -> dict[str, Any]:
    """Auto-fix metadata problems on a single video.

    Fixes applied:
      - Missing purchase link → append standard purchase block
      - Missing/low tags → generate SEO tags from title artist
      - Missing producer credit → included in description rewrite
      - Wrong category → set to 10 (Music)
      - Stale purchase link → rewrite description with specific beat URL

    Args:
        video: Video dict from scan_channel() with issues attached
        youtube: Authenticated YouTube service (required unless dry_run)
        dry_run: If True, compute fixes but don't push to YouTube

    Returns:
        Dict with fix results
    """
    issues = video.get("issues", [])
    if not issues:
        return {"video_id": video["video_id"], "fixes": [], "status": "clean"}

    vid_id = video["video_id"]
    stem = video.get("stem", "")
    title = video["title"]
    current_desc = video["description"]
    current_tags = list(video.get("tags", []))

    fixes: list[str] = []
    new_desc = current_desc
    new_tags = current_tags
    new_category = video.get("category_id", "10")

    issue_types = {i["type"] for i in issues if i.get("auto_fixable")}

    # Fix description (purchase link + producer credit + stale link)
    needs_desc_fix = issue_types & {
        "missing_purchase_link",
        "missing_producer_credit",
        "stale_purchase_link",
    }
    if needs_desc_fix:
        if stem:
            new_desc = _build_fixed_description(stem)
            fixes.append("rewrote description with purchase link + producer credit")
        else:
            # No stem match — append purchase block to existing description
            store_profile = _get_store_profile_url()
            producer = _get_producer()
            if store_profile and store_profile not in current_desc:
                append_block = f"\n\nPurchase:\n{store_profile}\n\nprod. {producer}"
                new_desc = current_desc.rstrip() + append_block
                fixes.append("appended purchase link + producer credit")

    # Fix tags
    if issue_types & {"missing_tags", "low_tags"}:
        artist = detect_artist(title)
        if artist:
            # Extract beat name from title
            beat_name = ""
            for sep in ["–", "-", "—", "|"]:
                if sep in title:
                    beat_name = title.split(sep, 1)[1].strip().strip('"').strip("'")
                    break

            generated = generate_tags(artist, beat_name=beat_name)
            # Merge: keep existing + add new
            merged = list(current_tags) + [t for t in generated if t.lower() not in {x.lower() for x in current_tags}]
            new_tags = _sanitize_tags(merged)
            fixes.append(f"generated {len(new_tags)} SEO tags from artist '{artist}'")
        else:
            # No artist detected, add generic tags
            generic = [
                "type beat", "trap beat", "rap instrumental",
                "hip hop instrumental", "beats for sale",
                "trap instrumental", "type beat 2026",
            ]
            merged = list(current_tags) + [t for t in generic if t.lower() not in {x.lower() for x in current_tags}]
            new_tags = _sanitize_tags(merged)
            fixes.append(f"added {len(new_tags) - len(current_tags)} generic tags")

    # Fix category
    if "wrong_category" in issue_types:
        new_category = "10"
        fixes.append("set category to Music (10)")

    if not fixes:
        return {"video_id": vid_id, "fixes": [], "status": "no_auto_fixes"}

    result = {
        "video_id": vid_id,
        "stem": stem,
        "title": title,
        "fixes": fixes,
        "status": "dry_run" if dry_run else "pending",
    }

    if dry_run:
        p(f"  [DRY] {vid_id}: {', '.join(fixes)}")
        return result

    # Push to YouTube
    if youtube is None:
        raise ValueError("youtube service required for non-dry-run fixes")

    body: dict[str, Any] = {
        "id": vid_id,
        "snippet": {
            "title": title,
            "description": new_desc[:5000],
            "tags": new_tags,
            "categoryId": new_category,
        },
    }

    try:
        youtube.videos().update(part="snippet", body=body).execute()
        result["status"] = "fixed"
        p(f"  [FIX] {vid_id}: {', '.join(fixes)}")
    except Exception as e:
        err_str = str(e)
        if "invalidTags" in err_str:
            # Retry without tags
            body["snippet"]["tags"] = []
            try:
                youtube.videos().update(part="snippet", body=body).execute()
                result["status"] = "fixed"
                result["fixes"].append("(tags stripped due to API rejection)")
                p(f"  [FIX] {vid_id}: {', '.join(result['fixes'])}")
            except Exception as e2:
                result["status"] = "error"
                result["error"] = str(e2)
                p(f"  [ERR] {vid_id}: {e2}")
        else:
            result["status"] = "error"
            result["error"] = err_str
            p(f"  [ERR] {vid_id}: {e}")

    # Also update local metadata if we have a stem
    if stem and result["status"] == "fixed":
        meta_path = META_DIR / f"{stem}.json"
        if meta_path.exists():
            try:
                meta = json.loads(meta_path.read_text())
                if needs_desc_fix:
                    meta["description"] = new_desc
                if issue_types & {"missing_tags", "low_tags"}:
                    meta["tags"] = new_tags
                meta_path.write_text(json.dumps(meta, indent=2))
            except Exception:
                pass

    return result


# ── Channel health report ────────────────────────────────────────────────────

def generate_report(scan_result: dict[str, Any], fix_results: list[dict] | None = None) -> dict[str, Any]:
    """Generate a channel health report from scan results.

    Args:
        scan_result: Output from scan_channel()
        fix_results: Optional list of fix results from fix_metadata()

    Returns:
        Structured health report dict
    """
    summary = scan_result["summary"]
    videos = scan_result["videos"]

    # Calculate health score
    total = max(summary["total_videos"], 1)
    sev = summary["by_severity"]
    penalty = sev["high"] * 5 + sev["medium"] * 2 + sev["low"] * 0.5
    max_penalty = total * 5
    health_score = max(0, int(100 - (penalty / max(max_penalty, 1)) * 100))

    # Top performing videos
    top_views = sorted(videos, key=lambda v: v.get("view_count", 0), reverse=True)[:10]

    # Total channel stats
    total_views = sum(v.get("view_count", 0) for v in videos)
    total_likes = sum(v.get("like_count", 0) for v in videos)

    # Beats vs Shorts breakdown (by duration: ≤60s = Short)
    shorts_list = [v for v in videos if is_short(v)]
    beats_list  = [v for v in videos if not is_short(v)]
    shorts_count = len(shorts_list)
    beats_count  = len(beats_list)
    shorts_views = sum(v.get("view_count", 0) for v in shorts_list)
    beats_views  = sum(v.get("view_count", 0) for v in beats_list)
    shorts_likes = sum(v.get("like_count", 0) for v in shorts_list)
    beats_likes  = sum(v.get("like_count", 0) for v in beats_list)

    # Count fixes applied
    fixes_applied = 0
    fixes_failed = 0
    if fix_results:
        fixes_applied = sum(1 for r in fix_results if r.get("status") == "fixed")
        fixes_failed = sum(1 for r in fix_results if r.get("status") == "error")

    report = {
        "channel_health_score": health_score,
        "health_level": (
            "excellent" if health_score >= 90
            else "good" if health_score >= 75
            else "warning" if health_score >= 50
            else "critical"
        ),
        "scanned_at": scan_result.get("scanned_at", ""),
        "overview": {
            "total_videos": summary["total_videos"],
            "total_views": total_views,
            "total_likes": total_likes,
            "clean_videos": summary["clean_videos"],
            "flagged_videos": summary["flagged_videos"],
            "beats_count": beats_count,
            "shorts_count": shorts_count,
            "beats_views": beats_views,
            "shorts_views": shorts_views,
            "beats_likes": beats_likes,
            "shorts_likes": shorts_likes,
        },
        "issues": {
            "total": summary["total_issues"],
            "high_severity": sev["high"],
            "medium_severity": sev["medium"],
            "low_severity": sev["low"],
            "auto_fixable": summary["auto_fixable"],
            "by_type": summary["by_type"],
        },
        "fixes": {
            "applied": fixes_applied,
            "failed": fixes_failed,
            "remaining": summary["total_issues"] - fixes_applied,
        },
        "top_videos": [
            {
                "title": v["title"],
                "video_id": v["video_id"],
                "views": v.get("view_count", 0),
                "likes": v.get("like_count", 0),
            }
            for v in top_views
        ],
    }

    return report


def print_report(report: dict[str, Any]):
    """Pretty-print a channel health report to stdout."""
    p("")
    p("=" * 60)
    p("  CHANNEL HEALTH REPORT")
    p("=" * 60)
    p("")

    ov = report["overview"]
    iss = report["issues"]
    fx = report["fixes"]
    score = report["channel_health_score"]
    level = report["health_level"].upper()

    p(f"  Health Score:       {score}/100  ({level})")
    p(f"  Scanned At:        {report['scanned_at'][:19]}")
    p("")
    p(f"  Videos scanned:    {ov['total_videos']}")
    p(f"    Beats:           {ov.get('beats_count', '?')}")
    p(f"    Shorts:          {ov.get('shorts_count', '?')}")
    p(f"  Total views:       {ov['total_views']:,}")
    p(f"    Beats views:     {ov.get('beats_views', 0):,}")
    p(f"    Shorts views:    {ov.get('shorts_views', 0):,}")
    p(f"  Total likes:       {ov['total_likes']:,}")
    p(f"  Clean videos:      {ov['clean_videos']}")
    p(f"  Flagged videos:    {ov['flagged_videos']}")
    p("")
    p("  ISSUES")
    p("  " + "-" * 40)
    p(f"  Missing purchase links:  {iss['by_type'].get('missing_purchase_link', 0)}")
    p(f"  Weak titles:             {iss['by_type'].get('weak_title', 0)}")
    p(f"  Missing tags:            {iss['by_type'].get('missing_tags', 0)}")
    p(f"  Low tag count:           {iss['by_type'].get('low_tags', 0)}")
    p(f"  Missing producer credit: {iss['by_type'].get('missing_producer_credit', 0)}")
    p(f"  Stale purchase links:    {iss['by_type'].get('stale_purchase_link', 0)}")
    p(f"  Wrong category:          {iss['by_type'].get('wrong_category', 0)}")
    p(f"  Free language:           {iss['by_type'].get('free_language', 0)}")
    p("")

    if fx["applied"] or fx["failed"]:
        p("  FIXES")
        p("  " + "-" * 40)
        p(f"  Applied:    {fx['applied']}")
        p(f"  Failed:     {fx['failed']}")
        p(f"  Remaining:  {fx['remaining']}")
        p("")

    if report.get("top_videos"):
        p("  TOP VIDEOS")
        p("  " + "-" * 40)
        for i, tv in enumerate(report["top_videos"][:5], 1):
            p(f"  {i}. {tv['title'][:50]}")
            p(f"     {tv['views']:,} views · {tv['likes']:,} likes")
        p("")

    p("=" * 60)


# ── Daily scan (scheduler entry point) ───────────────────────────────────────

def run_daily_scan(auto_fix: bool = True, dry_run: bool = False) -> dict[str, Any]:
    """Run a full daily channel scan, optionally auto-fix issues, and save report.

    This is the main entry point for scheduled/cron usage.

    Args:
        auto_fix: Whether to auto-fix detected issues
        dry_run: If True, compute fixes but don't push to YouTube

    Returns:
        The channel health report dict
    """
    start = time.time()

    p("[DAILY] Starting channel scan...")
    youtube = get_youtube_service()

    # Scan
    scan_result = scan_channel(youtube=youtube)
    p(f"[DAILY] Scan complete: {scan_result['summary']['total_videos']} videos, "
      f"{scan_result['summary']['total_issues']} issues")

    # Fix
    fix_results: list[dict] = []
    if auto_fix and scan_result["flagged_videos"]:
        fixable = [v for v in scan_result["flagged_videos"]
                   if any(i.get("auto_fixable") for i in v.get("issues", []))]
        p(f"[DAILY] Auto-fixing {len(fixable)} video(s)...")

        for i, video in enumerate(fixable, 1):
            p(f"  [{i}/{len(fixable)}] {video['title'][:50]}...")
            result = fix_metadata(video, youtube=youtube, dry_run=dry_run)
            fix_results.append(result)

            # Rate limit: 1 update per second
            if i < len(fixable):
                time.sleep(1)

    # Report
    report = generate_report(scan_result, fix_results)
    elapsed = time.time() - start
    report["scan_duration_seconds"] = round(elapsed, 1)

    # Save report
    try:
        HEALTH_REPORT_PATH.write_text(json.dumps(report, indent=2))
        p(f"[DAILY] Report saved to {HEALTH_REPORT_PATH.name}")
    except Exception as e:
        p(f"[WARN] Failed to save report: {e}")

    # Print
    print_report(report)

    return report


# ── CLI ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="FY3 YouTube Channel Manager")
    parser.add_argument("--fix", action="store_true", help="Auto-fix detected issues")
    parser.add_argument("--dry-run", action="store_true", help="Show fixes without applying")
    parser.add_argument("--report-only", action="store_true", help="Load last report and print")
    parser.add_argument("--scan-only", action="store_true", help="Scan and dump issues (no fix)")
    args = parser.parse_args()

    logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")

    if args.report_only:
        data = _load_json(HEALTH_REPORT_PATH)
        if not data:
            p("[ERROR] No saved report found. Run a scan first.")
            sys.exit(1)
        print_report(data)
        return

    if args.scan_only:
        result = run_daily_scan(auto_fix=False)
        # Dump flagged videos as JSON to stdout for piping
        issues_out = {
            "scanned_at": result.get("scanned_at", ""),
            "total_videos": result["overview"]["total_videos"],
            "total_issues": result["issues"]["total"],
            "issues_by_type": result["issues"]["by_type"],
        }
        p("\n" + json.dumps(issues_out, indent=2))
        return

    report = run_daily_scan(auto_fix=args.fix, dry_run=args.dry_run)

    if args.dry_run:
        p("\n[DRY RUN] No changes were made.")


if __name__ == "__main__":
    main()
