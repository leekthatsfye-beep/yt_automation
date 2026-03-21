"""
upload.py

Uploads rendered beat videos to YouTube using the YouTube Data API v3.

Usage examples:
    python upload.py
    python upload.py --only "army,master_plan"
    python upload.py --privacy unlisted
    python upload.py --dry-run

    # Schedule a single video at a specific time
    python upload.py --only "army" --schedule-at "2026-02-18T18:00:00-05:00"

    # Schedule a batch starting at a time, one per day (default 1440 min)
    python upload.py --schedule-start "2026-02-18T18:00:00-05:00"

    # Schedule a batch every 2 days
    python upload.py --schedule-start "2026-02-18T18:00:00-05:00" --every-minutes 2880

    # Dry run shows computed schedule without uploading
    python upload.py --schedule-start "2026-02-18T18:00:00-05:00" --dry-run
"""

import argparse
import json
import re
import sys
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from googleapiclient.http import MediaFileUpload

from youtube_auth import get_youtube_service

ROOT           = Path(__file__).resolve().parent
OUT_DIR        = ROOT / "output"
META_DIR       = ROOT / "metadata"
LOG_FILE       = ROOT / "uploads_log.json"
STORE_LOG      = ROOT / "store_uploads_log.json"
LANES_CFG      = ROOT / "lanes_config.json"

def _replace_purchase_link(stem: str, desc: str) -> str:
    """Rewrite description to Format A with real store link."""
    store_data = {}
    if STORE_LOG.exists():
        try:
            store_data = json.loads(STORE_LOG.read_text())
        except Exception:
            pass
    lanes_cfg = {}
    if LANES_CFG.exists():
        try:
            lanes_cfg = json.loads(LANES_CFG.read_text())
        except Exception:
            pass
    store_profile = lanes_cfg.get("store_profile_url", "")
    producer = lanes_cfg.get("producer", "leekthatsfy3")

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

    # Full rewrite to Format A
    return f"Purchase / Download\n{purchase_link}\n\nprod. {producer}"


CATEGORY_MUSIC = "10"
MADE_FOR_KIDS  = False
CHUNK_SIZE     = 1024 * 1024   # 1 MB resumable upload chunks (faster than 256 KB)


def p(msg: str):
    """Print with immediate flush so bot's async pipe sees it instantly."""
    print(msg, flush=True)


# ── Helpers ───────────────────────────────────────────────────────────────────

def load_log() -> dict:
    if LOG_FILE.exists():
        with open(LOG_FILE) as f:
            return json.load(f)
    return {}


def save_log(log: dict):
    with open(LOG_FILE, "w") as f:
        json.dump(log, f, indent=2)


def all_stems() -> list[str]:
    """Return stems for every mp4 in output/ that also has a metadata file."""
    stems = []
    for mp4 in sorted(OUT_DIR.glob("*.mp4")):
        stem = mp4.stem
        if stem.endswith("_lit") or stem.endswith("_thumb"):
            continue   # skip LIT renders and thumb files — not for upload
        if (META_DIR / f"{stem}.json").exists():
            stems.append(stem)
    return stems


def sync_deleted(youtube=None) -> list[str]:
    """Check YouTube for deleted/missing videos and remove them from uploads_log.

    Returns list of stems that were removed from the log.
    If youtube client is None, authenticates automatically.
    """
    log = load_log()
    if not log:
        return []

    if youtube is None:
        youtube = get_youtube_service()

    # Batch check all video IDs (API allows up to 50 per request)
    video_ids = {entry["videoId"]: stem for stem, entry in log.items() if "videoId" in entry}
    if not video_ids:
        return []

    removed = []
    id_list = list(video_ids.keys())

    for i in range(0, len(id_list), 50):
        batch = id_list[i:i+50]
        try:
            resp = youtube.videos().list(
                part="id,status",
                id=",".join(batch),
            ).execute()
            found_ids = {item["id"] for item in resp.get("items", [])}

            for vid_id in batch:
                if vid_id not in found_ids:
                    stem = video_ids[vid_id]
                    removed.append(stem)
                    p(f"[SYNC] Removed '{stem}' — video {vid_id} no longer on YouTube")
        except Exception as e:
            p(f"[WARN] sync_deleted batch check failed: {e}")

    if removed:
        for stem in removed:
            log.pop(stem, None)
        save_log(log)
        p(f"[SYNC] Cleaned {len(removed)} deleted video(s) from uploads_log.json")

    return removed


def load_meta(stem: str) -> dict:
    with open(META_DIR / f"{stem}.json") as f:
        return json.load(f)


def parse_rfc3339(ts: str) -> datetime:
    """Parse an RFC3339 timestamp into a timezone-aware datetime."""
    try:
        return datetime.fromisoformat(ts)
    except ValueError:
        raise argparse.ArgumentTypeError(
            f"Invalid RFC3339 timestamp: {ts!r}\n"
            "  Expected format: 2026-02-18T18:00:00-05:00"
        )


def fmt_local(dt: datetime) -> str:
    """Human-readable local representation of a datetime."""
    return dt.strftime("%Y-%m-%d %H:%M %Z") if dt.tzname() else dt.isoformat()


def print_summary(items: list[dict], privacy: str, dry_run: bool):
    label = "DRY RUN — would upload" if dry_run else "Will upload"
    scheduled = any(item.get("publish_at") for item in items)
    privacy_label = "private + scheduled" if scheduled else privacy

    p(f"\n{'─'*60}")
    p(f"  {label} {len(items)} video(s)  [privacy: {privacy_label}]")
    p(f"{'─'*60}")
    for i, item in enumerate(items, 1):
        thumb_label = item["thumb"].name if item["thumb"] else "none"
        p(f"  {i:>2}. {item['title']}")
        p(f"      stem      : {item['stem']}")
        p(f"      video     : {item['mp4'].name}")
        p(f"      thumbnail : {thumb_label}")
        if item.get("publish_at"):
            p(f"      publish   : {fmt_local(item['publish_at'])}")
    p(f"{'─'*60}")


def print_upload_confirmation(item: dict, video_id: str, url: str):
    """Print a clear, detailed confirmation after each successful upload/schedule."""
    p(f"")
    p(f"  {'='*50}")
    if item.get("publish_at"):
        p(f"  SCHEDULED & LOCKED IN")
    else:
        p(f"  UPLOAD CONFIRMED")
    p(f"  {'='*50}")
    p(f"  Beat:      {item['stem']}")
    p(f"  Title:     {item['title']}")
    p(f"  Video ID:  {video_id}")
    p(f"  URL:       {url}")
    if item.get("publish_at"):
        p(f"  Status:    Private (auto-publishes at scheduled time)")
        p(f"  Goes Live: {fmt_local(item['publish_at'])}")
        p(f"  Privacy:   Will switch to PUBLIC automatically")
    else:
        p(f"  Status:    {item.get('privacy', 'public').upper()}")
        p(f"  Live Now:  {'Yes' if item.get('privacy', 'public') == 'public' else 'No'}")
    if item.get("_thumb_uploaded"):
        p(f"  Thumbnail: Uploaded")
    elif item.get("thumb"):
        p(f"  Thumbnail: FAILED (YouTube will auto-generate)")
    else:
        p(f"  Thumbnail: None (YouTube will auto-generate)")
    p(f"  Logged:    uploads_log.json (saved)")
    p(f"  {'='*50}")


# ── Upload ────────────────────────────────────────────────────────────────────

def _sanitize_tags(raw_tags: list) -> list:
    """
    Sanitize tags to comply with YouTube Data API v3 requirements.
    Rules enforced:
      - Each tag must be a non-empty string
      - Strip leading/trailing whitespace
      - Remove tags containing commas (YouTube treats comma as delimiter)
      - Remove control characters and non-printable characters
      - Remove tags with < > & characters (cause invalidTags)
      - Truncate each tag to 30 chars max
      - Total sum of all tag lengths must not exceed 500 chars
      - No duplicate tags (case-insensitive)
    """
    seen = set()
    clean = []
    total = 0

    for t in raw_tags:
        if not isinstance(t, str):
            continue
        # Strip whitespace
        t = t.strip()
        if not t:
            continue
        # Remove control chars and non-printable
        t = re.sub(r'[\x00-\x1f\x7f-\x9f]', '', t).strip()
        if not t:
            continue
        # Remove tags with illegal chars YouTube rejects
        if re.search(r'[<>&",]', t):
            # Try stripping the chars instead of dropping the whole tag
            t = re.sub(r'[<>&",]', '', t).strip()
            if not t:
                continue
        # Truncate to 30 chars
        t = t[:30].strip()
        if not t:
            continue
        # Deduplicate case-insensitively
        lower = t.lower()
        if lower in seen:
            continue
        seen.add(lower)
        # Enforce 450-char total (YouTube rejects near 500 with commas counted)
        if total + len(t) > 450:
            break
        clean.append(t)
        total += len(t)

    return clean


def _is_quota_exceeded(exc: Exception) -> bool:
    """Check if an exception is a YouTube API quota-exceeded error."""
    s = str(exc).lower()
    return "quotaexceeded" in s or ("403" in s and "quota" in s)


def upload_video(youtube, item: dict) -> str:
    """
    Upload the video file and return the YouTube video ID.

    Privacy logic:
    - If publish_at is set: privacyStatus="private" + publishAt timestamp
      (YouTube requires private for scheduled videos)
    - Otherwise: use the privacy arg passed in via item["privacy"]
    """
    meta       = item["meta"]
    publish_at = item.get("publish_at")

    video_status = {
        "selfDeclaredMadeForKids": MADE_FOR_KIDS,
    }

    if publish_at:
        video_status["privacyStatus"] = "private"
        video_status["publishAt"]     = publish_at.isoformat()
    else:
        # Per-beat privacy set via /studio overrides the CLI --privacy flag
        per_beat = meta.get("privacy", "")
        video_status["privacyStatus"] = (
            per_beat if per_beat in ("public", "unlisted", "private")
            else item["privacy"]
        )

    raw_title = meta.get("title") or item["stem"]
    # YouTube: title max 100 chars, no < > characters
    yt_title = raw_title.replace("<", "").replace(">", "").strip()[:100]

    raw_desc = meta.get("description", "") or ""
    # Auto-replace old description formats with Format A (purchase link)
    if "AIRBIT_LINK_HERE" in raw_desc or "[Link in bio]" in raw_desc or "Listen freely" in raw_desc:
        raw_desc = _replace_purchase_link(item["stem"], raw_desc)
    # YouTube: description max 5000 chars
    yt_desc = raw_desc[:5000]

    yt_tags = _sanitize_tags(meta.get("tags", []) or [])

    body = {
        "snippet": {
            "title":       yt_title,
            "description": yt_desc,
            "tags":        yt_tags,
            "categoryId":  CATEGORY_MUSIC,
        },
        "status": video_status,
    }

    media = MediaFileUpload(
        str(item["mp4"]),
        mimetype="video/mp4",
        resumable=True,
        chunksize=CHUNK_SIZE,
    )

    if yt_title != raw_title:
        p(f"  [WARN] Title truncated to 100 chars: {yt_title!r}")
    p(f"  Uploading...")

    def _do_upload(upload_body):
        req  = youtube.videos().insert(part="snippet,status", body=upload_body, media_body=media)
        resp = None
        while resp is None:
            chunk_status, resp = req.next_chunk()
            if chunk_status:
                pct = int(chunk_status.progress() * 100)
                p(f"  [PROGRESS] {pct}%")
        return resp

    try:
        response = _do_upload(body)
    except Exception as e:
        err_str = str(e)
        # Auto-retry without tags if YouTube rejects them
        if "invalidTags" in err_str or "invalid video keywords" in err_str.lower():
            p(f"  [WARN] Tags rejected by YouTube (invalidTags) — retrying without tags")
            body_no_tags = {**body, "snippet": {**body["snippet"], "tags": []}}
            # Re-create media upload (stream already consumed)
            media2 = MediaFileUpload(
                str(item["mp4"]),
                mimetype="video/mp4",
                resumable=True,
                chunksize=CHUNK_SIZE,
            )
            req2  = youtube.videos().insert(part="snippet,status", body=body_no_tags, media_body=media2)
            resp2 = None
            while resp2 is None:
                chunk_status2, resp2 = req2.next_chunk()
                if chunk_status2:
                    pct = int(chunk_status2.progress() * 100)
                    p(f"  [PROGRESS] {pct}%")
            response = resp2
        else:
            raise

    p(f"  Upload complete.")

    return response["id"]


def upload_thumbnail(youtube, video_id: str, thumb_path: Path):
    media = MediaFileUpload(str(thumb_path), mimetype="image/jpeg", resumable=False)
    youtube.thumbnails().set(videoId=video_id, media_body=media).execute()
    p(f"  Thumbnail uploaded ✓")


# ── Update existing videos ───────────────────────────────────────────────────

def update_video_metadata(youtube, video_id: str, meta: dict):
    """Update title, description, and tags on an existing YouTube video."""
    raw_title = (meta.get("title") or "").replace("<", "").replace(">", "").strip()[:100]
    raw_desc  = (meta.get("description") or "")[:5000]
    yt_tags   = _sanitize_tags(meta.get("tags", []) or [])

    # YouTube update API is stricter on tag budget than insert —
    # enforce 450 char total (sum of lengths) as safe ceiling
    trimmed = []
    char_total = 0
    for t in yt_tags:
        if char_total + len(t) > 450:
            break
        trimmed.append(t)
        char_total += len(t)
    yt_tags = trimmed

    body = {
        "id": video_id,
        "snippet": {
            "title":       raw_title,
            "description": raw_desc,
            "tags":        yt_tags,
            "categoryId":  CATEGORY_MUSIC,
        },
    }
    try:
        youtube.videos().update(part="snippet", body=body).execute()
    except Exception as e:
        if "invalidTags" in str(e) or "invalid video keywords" in str(e).lower():
            p(f"  [WARN] Tags rejected — retrying without tags")
            body["snippet"]["tags"] = []
            youtube.videos().update(part="snippet", body=body).execute()
        else:
            raise
    p(f"  [UPDATE] {video_id}: {raw_title}")


def reschedule_video(youtube, video_id: str, publish_at: datetime):
    """Update the publishAt time on an existing scheduled (private) video."""
    body = {
        "id": video_id,
        "status": {
            "privacyStatus": "private",
            "publishAt":     publish_at.isoformat(),
        },
    }
    youtube.videos().update(part="status", body=body).execute()
    p(f"  [RESCHED] {video_id} → {fmt_local(publish_at)}")


def do_update(args):
    """Handle --update mode: push local metadata to YouTube for already-uploaded videos."""
    log = load_log()

    if args.only:
        stems = [s.strip() for s in args.only.split(",")]
    else:
        stems = list(log.keys())

    # Filter to stems that are actually in the upload log
    update_items = []
    for stem in stems:
        if stem not in log:
            p(f"[SKIP] {stem}: not in uploads_log.json (not uploaded yet)")
            continue
        meta_path = META_DIR / f"{stem}.json"
        if not meta_path.exists():
            p(f"[ERROR] {stem}: metadata/{stem}.json not found")
            continue
        meta = load_meta(stem)
        update_items.append({
            "stem":     stem,
            "videoId":  log[stem]["videoId"],
            "meta":     meta,
        })

    if not update_items:
        p("Nothing to update.")
        return

    p(f"\n{'─'*60}")
    p(f"  Will update metadata on {len(update_items)} video(s)")
    p(f"{'─'*60}")
    for i, item in enumerate(update_items, 1):
        p(f"  {i:>2}. {item['meta'].get('title', item['stem'])}")
        p(f"      videoId: {item['videoId']}")
    p(f"{'─'*60}")

    if args.dry_run:
        p("[DRY RUN] No changes made.")
        return

    # Authenticate
    p("Authenticating with YouTube...")
    try:
        youtube = get_youtube_service()
    except Exception as e:
        p(f"[ERROR] Auth failed: {e}")
        sys.exit(1)
    p("Authenticated ✓")

    updated = 0
    for idx, item in enumerate(update_items, 1):
        p(f"[UPDATE] {item['stem']} ({idx}/{len(update_items)})")
        try:
            update_video_metadata(youtube, item["videoId"], item["meta"])
            # Update the title in the log too
            log[item["stem"]]["title"] = item["meta"].get("title", item["stem"])
            save_log(log)
            updated += 1
        except Exception as e:
            p(f"  [FAIL] {item['stem']}: {e}")

    p(f"[COMPLETE] {updated}/{len(update_items)} video(s) updated.")


def do_sync_links(args):
    """Handle --sync-links: scrape Airbit store, match beats, update YouTube descriptions."""
    from airbit_upload import sync_store_links

    # Step 1: Scrape Airbit and update store_uploads_log.json
    p("\n[STEP 1] Scraping Airbit store for per-beat URLs...")
    matches = sync_store_links()
    if not matches:
        p("[ERROR] No beats matched. Make sure beats are listed on Airbit.")
        return

    # Step 2: Now run fix-descriptions to push the updated URLs to YouTube
    p(f"\n[STEP 2] Updating YouTube descriptions with {len(matches)} beat-specific links...")
    do_fix_descriptions(args)


def _needs_description_fix(desc: str, stem: str = "", store_data: dict = None) -> bool:
    """Check if a description needs to be replaced with the new Format A."""
    if not desc:
        return True
    # Old placeholder
    if "AIRBIT_LINK_HERE" in desc:
        return True
    # Old bot format with [Link in bio]
    if "[Link in bio]" in desc:
        return True
    # Old bot format with long blurb
    if "uploaded consistently" in desc or "Listen freely" in desc:
        return True
    # Missing store URL entirely
    if "infinity.airbit.com" not in desc and "airbit.com" not in desc:
        return True
    # Has the general store URL but a specific beat URL is now available
    if stem and store_data:
        entry = store_data.get(stem, {})
        airbit_entry = entry.get("airbit", entry) if isinstance(entry, dict) else {}
        beat_url = airbit_entry.get("url", "")
        if beat_url and "/beats/" in beat_url and beat_url not in desc:
            return True
    return False


def _build_new_description(stem: str, store_data: dict, store_profile: str, producer: str) -> str:
    """Build the Format A description for a beat."""
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


def do_fix_descriptions(args):
    """Handle --fix-descriptions: rewrite all descriptions to Format A + push to YouTube."""
    log = load_log()

    # Load store data for per-beat URLs
    store_data = {}
    if STORE_LOG.exists():
        try:
            store_data = json.loads(STORE_LOG.read_text())
        except Exception:
            pass

    # Load lanes config for store profile URL
    lanes_cfg = {}
    if LANES_CFG.exists():
        try:
            lanes_cfg = json.loads(LANES_CFG.read_text())
        except Exception:
            pass
    store_profile = lanes_cfg.get("store_profile_url", "")
    producer = lanes_cfg.get("producer", "leekthatsfy3")

    if args.only:
        stems = [s.strip() for s in args.only.split(",")]
    else:
        stems = list(log.keys())

    fixed_items = []
    for stem in stems:
        meta_path = META_DIR / f"{stem}.json"
        if not meta_path.exists():
            continue
        meta = load_meta(stem)
        desc = meta.get("description", "")

        if not _needs_description_fix(desc, stem=stem, store_data=store_data):
            continue

        new_desc = _build_new_description(stem, store_data, store_profile, producer)
        meta["description"] = new_desc

        video_id = log.get(stem, {}).get("videoId", "")
        fixed_items.append({
            "stem": stem,
            "videoId": video_id,
            "meta": meta,
            "meta_path": meta_path,
            "old_desc": desc[:60],
        })

    if not fixed_items:
        p("All descriptions are already up to date.")
        return

    p(f"\n{'─'*60}")
    p(f"  Will fix descriptions on {len(fixed_items)} beat(s)")
    p(f"  New format: Purchase / Download → {store_profile or '[Link in bio]'}")
    p(f"{'─'*60}")
    for i, item in enumerate(fixed_items[:10], 1):
        p(f"  {i:>2}. {item['stem']}")
        p(f"      was: {item['old_desc']}...")
    if len(fixed_items) > 10:
        p(f"  ... and {len(fixed_items) - 10} more")
    p(f"{'─'*60}")

    if args.dry_run:
        p("[DRY RUN] No changes made.")
        return

    # Step 1: Update all metadata JSON files
    for item in fixed_items:
        meta_path = item["meta_path"]
        meta_path.write_text(json.dumps(item["meta"], indent=2))
    p(f"  [+] Updated {len(fixed_items)} metadata/*.json files")

    # Step 2: Push to YouTube (only for videos that are uploaded)
    yt_items = [item for item in fixed_items if item["videoId"]]
    if not yt_items:
        p("  No YouTube videos to update (beats not yet uploaded).")
        return

    p(f"\n  Pushing {len(yt_items)} updated descriptions to YouTube...")
    p("  Authenticating with YouTube...")
    try:
        youtube = get_youtube_service()
    except Exception as e:
        p(f"  [ERROR] Auth failed: {e}")
        p("  Metadata files were updated — run 'upload.py --update' later to push to YouTube.")
        return
    p("  Authenticated ✓")

    updated = 0
    for idx, item in enumerate(yt_items, 1):
        p(f"  [FIX] {item['stem']} ({idx}/{len(yt_items)})")
        try:
            update_video_metadata(youtube, item["videoId"], item["meta"])
            updated += 1
        except Exception as e:
            p(f"    [FAIL] {item['stem']}: {e}")
        # Small delay to avoid rate limits
        if idx < len(yt_items):
            time.sleep(1)

    p(f"\n[COMPLETE] {updated}/{len(yt_items)} YouTube descriptions updated.")


def do_reschedule(args):
    """Handle --reschedule mode: read schedule from a JSON file and update publishAt times."""
    schedule_path = Path(args.reschedule)
    if not schedule_path.exists():
        p(f"[ERROR] Schedule file not found: {schedule_path}")
        sys.exit(1)

    with open(schedule_path) as f:
        schedule = json.load(f)

    # schedule format: {"stem": "2026-02-27T11:00:00-05:00", ...}
    log = load_log()

    resched_items = []
    for stem, publish_str in schedule.items():
        if stem not in log:
            p(f"[SKIP] {stem}: not in uploads_log.json")
            continue
        publish_at = parse_rfc3339(publish_str)
        resched_items.append({
            "stem":       stem,
            "videoId":    log[stem]["videoId"],
            "publish_at": publish_at,
        })

    if not resched_items:
        p("Nothing to reschedule.")
        return

    p(f"\n{'─'*60}")
    p(f"  Will reschedule {len(resched_items)} video(s)")
    p(f"{'─'*60}")
    for i, item in enumerate(resched_items, 1):
        old_time = log[item["stem"]].get("publishAt", "none")
        p(f"  {i:>2}. {item['stem']}")
        p(f"      old: {old_time}")
        p(f"      new: {fmt_local(item['publish_at'])}")
    p(f"{'─'*60}")

    if args.dry_run:
        p("[DRY RUN] No changes made.")
        return

    # Authenticate
    p("Authenticating with YouTube...")
    try:
        youtube = get_youtube_service()
    except Exception as e:
        p(f"[ERROR] Auth failed: {e}")
        sys.exit(1)
    p("Authenticated ✓")

    rescheduled = 0
    for idx, item in enumerate(resched_items, 1):
        p(f"[RESCHED] {item['stem']} ({idx}/{len(resched_items)})")
        try:
            reschedule_video(youtube, item["videoId"], item["publish_at"])
            log[item["stem"]]["publishAt"] = item["publish_at"].isoformat()
            save_log(log)
            rescheduled += 1
        except Exception as e:
            p(f"  [FAIL] {item['stem']}: {e}")

    p(f"[COMPLETE] {rescheduled}/{len(resched_items)} video(s) rescheduled.")


# ── Delete existing videos ───────────────────────────────────────────────────

def do_delete(args):
    """Handle --delete mode: delete videos from YouTube and remove from uploads_log.json."""
    log = load_log()

    if args.only:
        stems = [s.strip() for s in args.only.split(",")]
    else:
        p("[ERROR] --delete requires --only to specify which stems to delete.")
        sys.exit(1)

    # Filter to stems that are actually in the upload log
    delete_items = []
    for stem in stems:
        if stem not in log:
            p(f"[SKIP] {stem}: not in uploads_log.json (nothing to delete)")
            continue
        delete_items.append({
            "stem":    stem,
            "videoId": log[stem]["videoId"],
            "title":   log[stem].get("title", stem),
        })

    if not delete_items:
        p("Nothing to delete.")
        return

    p(f"\n{'─'*60}")
    p(f"  Will DELETE {len(delete_items)} video(s) from YouTube")
    p(f"{'─'*60}")
    for i, item in enumerate(delete_items, 1):
        p(f"  {i:>2}. {item['title']}")
        p(f"      videoId: {item['videoId']}")
    p(f"{'─'*60}")

    if args.dry_run:
        p("[DRY RUN] No videos deleted.")
        return

    # Authenticate
    p("Authenticating with YouTube...")
    try:
        youtube = get_youtube_service()
    except Exception as e:
        p(f"[ERROR] Auth failed: {e}")
        sys.exit(1)
    p("Authenticated ✓")

    deleted = 0
    for idx, item in enumerate(delete_items, 1):
        p(f"[DELETE] {item['stem']} ({idx}/{len(delete_items)})")
        try:
            youtube.videos().delete(id=item["videoId"]).execute()
            log.pop(item["stem"], None)
            save_log(log)
            p(f"  [DONE] Deleted {item['videoId']} ({item['title']})")
            deleted += 1
        except Exception as e:
            p(f"  [FAIL] {item['stem']}: {e}")

    p(f"[COMPLETE] {deleted}/{len(delete_items)} video(s) deleted from YouTube.")


# ── Main ──────────────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(description="Upload beat videos to YouTube.")
    parser.add_argument(
        "--only", type=str, default=None,
        help="Comma-separated stems to upload (e.g. army,master_plan)"
    )
    parser.add_argument(
        "--privacy", type=str, default="public",
        choices=["public", "unlisted", "private"],
        help="Privacy status (ignored when --schedule-at or --schedule-start is used)"
    )
    parser.add_argument(
        "--skip-uploaded", dest="skip_uploaded",
        type=lambda x: x.lower() != "false", default=True,
        help="Skip stems already in uploads_log.json (default: true)"
    )
    parser.add_argument(
        "--dry-run", action="store_true",
        help="Print what would be uploaded / scheduled without calling the API"
    )
    parser.add_argument(
        "--sync", action="store_true",
        help="Sync uploads_log.json with YouTube — remove entries for deleted videos, then exit"
    )
    parser.add_argument(
        "--update", action="store_true",
        help="Update metadata (title/desc/tags) on already-uploaded videos from local JSON files"
    )
    parser.add_argument(
        "--reschedule", type=str, default=None, metavar="JSON_FILE",
        help="Reschedule videos using a JSON file mapping stem → new publishAt time"
    )
    parser.add_argument(
        "--delete", action="store_true",
        help="Delete videos from YouTube and remove from uploads_log.json (use with --only)"
    )
    parser.add_argument(
        "--fix-descriptions", dest="fix_descriptions", action="store_true",
        help="Rewrite all descriptions to Format A (Purchase/Download + store link) and push to YouTube"
    )
    parser.add_argument(
        "--sync-links", dest="sync_links", action="store_true",
        help="Scrape Airbit store for per-beat URLs, match to YouTube uploads, update descriptions"
    )
    # ── Scheduling ────────────────────────────────────────────────────────────
    sched = parser.add_mutually_exclusive_group()
    sched.add_argument(
        "--schedule-at", dest="schedule_at", type=str, default=None,
        metavar="RFC3339",
        help="Schedule a single video to publish at this time (e.g. 2026-02-18T18:00:00-05:00)"
    )
    sched.add_argument(
        "--schedule-start", dest="schedule_start", type=str, default=None,
        metavar="RFC3339",
        help="Schedule a batch: first video at this time, rest spaced by --every-minutes"
    )
    parser.add_argument(
        "--every-minutes", dest="every_minutes", type=int, default=1440,
        metavar="N",
        help="Minutes between each scheduled video when using --schedule-start (default: 1440 = 1 day)"
    )

    # ── Quota / rate limiting ─────────────────────────────────────────────────
    parser.add_argument(
        "--max-per-run", dest="max_per_run", type=int, default=6,
        metavar="N",
        help="Max videos to upload in this run (default: 6, matches YouTube daily quota of ~6 uploads)"
    )
    parser.add_argument(
        "--upload-delay", dest="upload_delay", type=int, default=3,
        metavar="SEC",
        help="Seconds to wait between uploads to avoid rate limiting (default: 3)"
    )
    args = parser.parse_args()

    # ── Validate / parse schedule args ───────────────────────────────────────
    schedule_at    = parse_rfc3339(args.schedule_at)    if args.schedule_at    else None
    schedule_start = parse_rfc3339(args.schedule_start) if args.schedule_start else None

    # ── Update mode: push local metadata to YouTube ─────────────────────
    if args.update:
        do_update(args)
        return

    # ── Sync links: scrape Airbit → match → update YouTube descriptions ──
    if args.sync_links:
        do_sync_links(args)
        return

    # ── Fix descriptions: replace AIRBIT_LINK_HERE with real store links ──
    if args.fix_descriptions:
        do_fix_descriptions(args)
        return

    # ── Reschedule mode: update publishAt times ──────────────────────────
    if args.reschedule:
        do_reschedule(args)
        return

    # ── Delete mode: remove videos from YouTube ──────────────────────────
    if args.delete:
        do_delete(args)
        return

    # ── Sync-only mode ─────────────────────────────────────────────────────
    if args.sync:
        p("Authenticating with YouTube...")
        try:
            youtube = get_youtube_service()
        except Exception as e:
            p(f"[ERROR] Auth failed: {e}")
            sys.exit(1)
        p("Authenticated ✓")
        removed = sync_deleted(youtube)
        if not removed:
            p("[SYNC] All logged videos still exist on YouTube ✓")
        return

    if schedule_at and args.only:
        stems_for_at = [s.strip() for s in args.only.split(",")]
        if len(stems_for_at) > 1:
            parser.error("--schedule-at schedules exactly one time; use --only with a single stem, "
                         "or use --schedule-start for batches")

    # ── Build stem list ───────────────────────────────────────────────────────
    requested = (
        [s.strip() for s in args.only.split(",")]
        if args.only
        else all_stems()
    )

    log     = load_log()
    items   = []
    skipped = []
    errors  = []

    for i, stem in enumerate(requested):
        if args.skip_uploaded and stem in log:
            skipped.append(stem)
            continue

        mp4 = OUT_DIR / f"{stem}.mp4"
        if not mp4.exists():
            errors.append(f"{stem}: video file output/{stem}.mp4 not found — run /render first")
            continue

        meta_path = META_DIR / f"{stem}.json"
        if not meta_path.exists():
            errors.append(f"{stem}: metadata/{stem}.json not found — run /seo first")
            continue

        # Validate title isn't empty after stripping
        try:
            _m = json.loads(meta_path.read_text())
            _t = (_m.get("title") or stem).replace("<", "").replace(">", "").strip()
            if not _t:
                errors.append(f"{stem}: title is empty in metadata — fix with /tools fixmeta {stem}")
                continue
        except json.JSONDecodeError as _je:
            errors.append(f"{stem}: metadata JSON is corrupt ({_je}) — fix with /tools fixmeta {stem}")
            continue

        # Auto-fill missing description/tags using seo_metadata
        try:
            _m = json.loads(meta_path.read_text())
            _changed = False
            if not (_m.get("description") or "").strip():
                from seo_metadata import build_description
                _m["description"] = build_description(stem, _m)
                _changed = True
            if not _m.get("tags") or len(_m.get("tags", [])) < 3:
                from seo_metadata import build_tags
                _m["tags"] = build_tags(stem, _m)
                _changed = True
            if _changed:
                meta_path.write_text(json.dumps(_m, indent=2))
                p(f"  [META] Auto-filled description/tags for {stem}")
        except Exception as _ef:
            p(f"  [WARN] Could not auto-fill metadata for {stem}: {_ef}")

        meta  = load_meta(stem)
        thumb = OUT_DIR / f"{stem}_thumb.jpg"

        # Compute publish_at for this item
        if schedule_at:
            publish_at = schedule_at
        elif schedule_start:
            publish_at = schedule_start + timedelta(minutes=args.every_minutes * i)
        else:
            publish_at = None

        items.append({
            "stem":       stem,
            "mp4":        mp4,
            "thumb":      thumb if thumb.exists() else None,
            "meta":       meta,
            "title":      meta.get("title", stem),
            "privacy":    args.privacy,
            "publish_at": publish_at,
        })

    # ── Report skipped / errors ───────────────────────────────────────────────
    if skipped:
        p(f"[SKIP] Already uploaded ({len(skipped)}): {', '.join(skipped)}")
    for err in errors:
        p(f"[ERROR] {err}")

    if not items:
        p("Nothing to upload.")
        return

    # Derive effective privacy label for summary
    effective_privacy = "private (scheduled)" if any(it.get("publish_at") for it in items) else args.privacy
    print_summary(items, effective_privacy, args.dry_run)

    if args.dry_run:
        return

    # ── Authenticate ──────────────────────────────────────────────────────────
    p("Authenticating with YouTube...")
    try:
        youtube = get_youtube_service()
    except FileNotFoundError as e:
        p(f"[ERROR] {e}")
        sys.exit(1)
    except Exception as e:
        p(f"[ERROR] Auth failed: {e}")
        sys.exit(1)
    p("Authenticated ✓")

    # ── Sync: remove deleted videos from log ─────────────────────────────────
    try:
        removed = sync_deleted(youtube)
        if removed:
            # Re-check if any previously skipped stems are now uploadable
            log = load_log()
            for stem in removed:
                if stem in [s["stem"] for s in items]:
                    continue  # already queued
                mp4 = OUT_DIR / f"{stem}.mp4"
                meta_path = META_DIR / f"{stem}.json"
                if mp4.exists() and meta_path.exists():
                    meta = load_meta(stem)
                    items.append({
                        "stem": stem, "mp4": mp4,
                        "thumb": (OUT_DIR / f"{stem}_thumb.jpg") if (OUT_DIR / f"{stem}_thumb.jpg").exists() else None,
                        "meta": meta, "title": meta.get("title", stem),
                        "privacy": args.privacy, "publish_at": None,
                    })
                    p(f"[SYNC] Re-queued '{stem}' for upload (was deleted from YouTube)")
    except Exception as e:
        p(f"[WARN] Sync check failed (non-fatal): {e}")

    # ── Upload loop ───────────────────────────────────────────────────────────
    uploaded = 0
    failed   = 0
    quota_hit = False
    try:
        for idx, item in enumerate(items, 1):
            # ── Quota gate: stop if we've hit the per-run limit ──
            if uploaded >= args.max_per_run:
                remaining = len(items) - idx + 1
                p(f"[QUOTA] Reached {args.max_per_run}-upload limit. "
                  f"{remaining} video(s) remaining — resume tomorrow.")
                quota_hit = True
                break

            p(f"[UPLOAD] {item['stem']} ({idx}/{len(items)})")  # bot parses stem + (idx/total)
            p(f"  Title: {item['title']}")
            if item.get("publish_at"):
                p(f"  Scheduled: {fmt_local(item['publish_at'])}")

            try:
                video_id = upload_video(youtube, item)
                url      = f"https://www.youtube.com/watch?v={video_id}"

                thumb_ok = False
                if item["thumb"]:
                    try:
                        upload_thumbnail(youtube, video_id, item["thumb"])
                        thumb_ok = True
                    except Exception as te:
                        p(f"  [WARN] Thumbnail failed (video still uploaded): {te}")

                log[item["stem"]] = {
                    "videoId":    video_id,
                    "url":        url,
                    "uploadedAt": datetime.now(timezone.utc).isoformat(),
                    "title":      item["title"],
                    **({"publishAt": item["publish_at"].isoformat()} if item.get("publish_at") else {}),
                }
                save_log(log)
                uploaded += 1

                # Show detailed confirmation
                item["_thumb_uploaded"] = thumb_ok
                print_upload_confirmation(item, video_id, url)
                # Signal for Telegram bot parsing
                p(f"[DONE] {item['stem']} → {url}")

                # Inter-upload delay (skip after last upload)
                if idx < len(items) and uploaded < args.max_per_run:
                    time.sleep(args.upload_delay)

            except Exception as e:
                if _is_quota_exceeded(e):
                    p(f"  [FAIL] {item['stem']}: YouTube quota exceeded")
                    remaining = len(items) - idx
                    p(f"[QUOTA] Daily quota exceeded after {uploaded} upload(s). "
                      f"{remaining} video(s) remaining. Quota resets at midnight Pacific Time.")
                    quota_hit = True
                    break
                p(f"  [FAIL] {item['stem']}: {e}")
                failed += 1
                # Continue with next video — don't let one failure kill the batch

    except KeyboardInterrupt:
        p("\n[INTERRUPTED] Progress saved to uploads_log.json")
        sys.exit(0)

    # ── Final batch summary ──
    remaining = len(items) - uploaded - failed
    p(f"\n{'='*60}")
    if quota_hit:
        p(f"  QUOTA LIMIT REACHED")
    else:
        p(f"  BATCH COMPLETE")
    p(f"{'='*60}")
    p(f"  Uploaded:  {uploaded}/{len(items)}")
    p(f"  Failed:    {failed}")
    if quota_hit:
        p(f"  Remaining: {remaining} (resume on next run)")
        p(f"  Quota resets: midnight Pacific Time")

    # Show schedule summary if any were scheduled
    scheduled_items = [it for it in items if it.get("publish_at") and it["stem"] in log]
    if scheduled_items:
        p(f"\n  --- SCHEDULED RELEASES ---")
        for si in sorted(scheduled_items, key=lambda x: x["publish_at"]):
            entry = log.get(si["stem"], {})
            vid = entry.get("videoId", "?")
            p(f"  {fmt_local(si['publish_at']):>25}  {si['title']}")
            p(f"  {'':>25}  {entry.get('url', '?')}")
        p(f"\n  All {len(scheduled_items)} scheduled video(s) are LOCKED IN.")
        p(f"  YouTube will auto-publish them at the times above.")
        p(f"  Status: private until publish time, then switches to public.")
    else:
        live_items = [it for it in items if it["stem"] in log]
        if live_items:
            p(f"\n  All {len(live_items)} video(s) are LIVE on YouTube now.")

    p(f"\n  Log: {LOG_FILE}")
    p(f"{'='*60}")

    # Signal for bot parsing
    if quota_hit:
        p(f"[COMPLETE] {uploaded} uploaded, quota limit reached, {remaining} remaining")
    else:
        p(f"[COMPLETE] {uploaded}/{len(items)} uploaded")


if __name__ == "__main__":
    main()
