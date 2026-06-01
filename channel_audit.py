"""
channel_audit.py

Audits your YouTube channel and local pipeline for issues before they go live.

Checks:
  1. Duplicate titles in uploads_log.json
  2. Same beat uploaded twice (different stems, same title)
  3. Multiple videos scheduled for the same date/time
  4. Videos with long silence at the end (dead audio)
  5. Rendered videos that are much shorter/longer than the source beat
  6. Beats in beats/ that have no metadata
  7. Beats in beats/ that have been rendered but not uploaded
  8. Orphaned uploads (in log but video deleted from YouTube)
  9. Title/metadata artist mismatch (wrong artist tagged)
 10. Output files with no corresponding beat file

Usage:
    python channel_audit.py              # full audit
    python channel_audit.py --fix        # auto-fix what can be fixed silently
    python channel_audit.py --yt         # also check YouTube for deleted videos (uses quota)
"""

import argparse
import json
import os
import subprocess
import sys
from collections import defaultdict
from datetime import datetime, timezone
from pathlib import Path

ROOT       = Path(__file__).resolve().parent
BEATS_DIR  = ROOT / "beats"
OUTPUT_DIR = ROOT / "output"
META_DIR   = ROOT / "metadata"
LOG_FILE   = ROOT / "uploads_log.json"

RED    = "\033[91m"
YELLOW = "\033[93m"
GREEN  = "\033[92m"
CYAN   = "\033[96m"
BOLD   = "\033[1m"
RESET  = "\033[0m"

issues   = []
warnings = []
ok       = []

def issue(msg):
    issues.append(msg)
    print(f"  {RED}✗ {msg}{RESET}")

def warn(msg):
    warnings.append(msg)
    print(f"  {YELLOW}⚠ {msg}{RESET}")

def good(msg):
    ok.append(msg)

def section(title):
    print(f"\n{BOLD}{CYAN}{'─'*50}{RESET}")
    print(f"{BOLD}{CYAN}  {title}{RESET}")
    print(f"{BOLD}{CYAN}{'─'*50}{RESET}")

def get_audio_duration(path: Path) -> float:
    """Return duration in seconds via ffprobe."""
    result = subprocess.run(
        ["ffprobe", "-v", "quiet", "-show_entries", "format=duration",
         "-of", "csv=p=0", str(path)],
        capture_output=True, text=True
    )
    try:
        return float(result.stdout.strip())
    except ValueError:
        return 0.0

def get_silence_end(path: Path) -> float | None:
    """Return timestamp where silence starts (i.e. where beat content ends). None if no silence."""
    result = subprocess.run(
        ["ffmpeg", "-i", str(path), "-af", "silencedetect=noise=-50dB:d=1", "-f", "null", "-"],
        capture_output=True, text=True
    )
    output = result.stderr
    silence_starts = []
    for line in output.splitlines():
        if "silence_start" in line:
            try:
                val = float(line.split("silence_start:")[1].strip().split()[0])
                silence_starts.append(val)
            except Exception:
                pass
    # Return the first silence start if it's not near the end (more than 20s before end)
    total = get_audio_duration(path)
    if silence_starts:
        first = silence_starts[0]
        wasted = total - first
        if wasted > 20:
            return first
    return None


def load_log():
    if LOG_FILE.exists():
        return json.loads(LOG_FILE.read_text())
    return {}


def safe_stem(filename: str) -> str:
    import re
    s = Path(filename).stem
    s = s.lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    s = s.strip("_")
    return s


# ─────────────────────────────────────────────
# CHECK 1: Duplicate titles in uploads_log
# ─────────────────────────────────────────────
def check_duplicate_titles(log):
    section("CHECK 1 · Duplicate Titles in Uploads Log")
    title_map = defaultdict(list)
    for stem, data in log.items():
        title = data.get("title", "").strip()
        if title:
            title_map[title].append(stem)
    found = False
    for title, stems in title_map.items():
        if len(stems) > 1:
            issue(f"Duplicate title: \"{title}\" → stems: {stems}")
            found = True
    if not found:
        good("No duplicate titles")
        print(f"  {GREEN}✓ No duplicate titles{RESET}")


# ─────────────────────────────────────────────
# CHECK 2: Same publish date used twice
# ─────────────────────────────────────────────
def check_schedule_conflicts(log):
    section("CHECK 2 · Schedule Conflicts (Same Publish Date)")
    date_map = defaultdict(list)
    for stem, data in log.items():
        publish_at = data.get("publishAt", "")
        if publish_at:
            # Normalize to date only (YYYY-MM-DD)
            date_key = publish_at[:10]
            date_map[date_key].append((stem, data.get("title", "")))
    found = False
    for date, entries in sorted(date_map.items()):
        # 3 videos/day is intentional (3 artist lanes). Flag only if 4+ on same day.
        if len(entries) > 3:
            issue(f"{len(entries)} videos on {date} (more than 3-per-day limit):")
            for stem, title in entries:
                print(f"      → {stem}: {title}")
            found = True
        elif len(entries) == 3:
            good(f"3 videos on {date} — normal")
        elif len(entries) == 2:
            good(f"2 videos on {date} — normal")
    if not found:
        good("No schedule conflicts")
        print(f"  {GREEN}✓ No schedule conflicts (3/day cadence looks clean){RESET}")


# ─────────────────────────────────────────────
# CHECK 3: Silent tail in rendered MP4s
# ─────────────────────────────────────────────
def check_silent_tails():
    section("CHECK 3 · Silent Tails in Rendered Videos (Dead Audio)")
    mp4s = list(OUTPUT_DIR.glob("*.mp4"))
    if not mp4s:
        print(f"  {YELLOW}⚠ No rendered MP4s found in output/{RESET}")
        return
    found = False
    for mp4 in sorted(mp4s):
        silence_start = get_silence_end(mp4)
        if silence_start is not None:
            total = get_audio_duration(mp4)
            wasted = total - silence_start
            mins = int(silence_start // 60)
            secs = int(silence_start % 60)
            issue(f"{mp4.name}: beat ends at {mins}:{secs:02d}, {wasted:.0f}s of silence after")
            found = True
    if not found:
        good("No silent tails")
        print(f"  {GREEN}✓ No silent tails detected{RESET}")


# ─────────────────────────────────────────────
# CHECK 4: Duration mismatch (MP4 vs source beat)
# ─────────────────────────────────────────────
def check_duration_mismatches():
    section("CHECK 4 · Duration Mismatches (Rendered vs Source Beat)")
    found = False
    for beat_file in sorted(BEATS_DIR.glob("*.mp3")) :
        stem = safe_stem(beat_file.name)
        mp4 = OUTPUT_DIR / f"{stem}.mp4"
        if not mp4.exists():
            continue
        beat_dur = get_audio_duration(beat_file)
        mp4_dur  = get_audio_duration(mp4)
        if beat_dur < 10:
            continue
        diff = abs(mp4_dur - beat_dur)
        # Allow up to 5 seconds difference
        if diff > 5:
            issue(f"{stem}: beat={beat_dur:.0f}s, video={mp4_dur:.0f}s (diff={diff:.0f}s)")
            found = True
    if not found:
        good("No duration mismatches")
        print(f"  {GREEN}✓ All durations match{RESET}")


# ─────────────────────────────────────────────
# CHECK 5: Beats without metadata
# ─────────────────────────────────────────────
def check_missing_metadata():
    section("CHECK 5 · Beats Without Metadata")
    found = False
    for beat_file in sorted(BEATS_DIR.glob("*.mp3")):
        stem = safe_stem(beat_file.name)
        meta = META_DIR / f"{stem}.json"
        if not meta.exists():
            warn(f"{stem}: no metadata file (run seo_metadata.py)")
            found = True
    if not found:
        good("All beats have metadata")
        print(f"  {GREEN}✓ All beats have metadata{RESET}")


# ─────────────────────────────────────────────
# CHECK 6: Rendered but not uploaded
# ─────────────────────────────────────────────
def check_rendered_not_uploaded(log):
    section("CHECK 6 · Rendered Videos Not Yet Uploaded")
    found = False
    for mp4 in sorted(OUTPUT_DIR.glob("*.mp4")):
        stem = mp4.stem
        # Skip temp clip files and portrait variants — these are render artifacts
        if "_tmp_clip" in stem or stem.endswith("_9x16"):
            continue
        if stem not in log:
            warn(f"{stem}: rendered but not in uploads_log.json")
            found = True
    if not found:
        good("All rendered videos uploaded")
        print(f"  {GREEN}✓ All rendered videos are uploaded{RESET}")


# ─────────────────────────────────────────────
# CHECK 7: Upcoming scheduled videos (next 7 days)
# ─────────────────────────────────────────────
def check_upcoming_schedule(log):
    section("CHECK 7 · Upcoming Scheduled Videos (Next 14 Days)")
    now = datetime.now(timezone.utc)
    upcoming = []
    for stem, data in log.items():
        publish_at = data.get("publishAt", "")
        if not publish_at:
            continue
        try:
            dt = datetime.fromisoformat(publish_at)
            if dt.tzinfo is None:
                dt = dt.replace(tzinfo=timezone.utc)
            delta = (dt - now).total_seconds()
            if 0 < delta < 14 * 86400:
                upcoming.append((dt, stem, data.get("title", "")))
        except Exception:
            continue
    upcoming.sort()
    if not upcoming:
        print(f"  {YELLOW}⚠ No videos scheduled in the next 14 days{RESET}")
    else:
        for dt, stem, title in upcoming:
            local = dt.strftime("%a %b %d @ %I:%M %p UTC")
            print(f"  {GREEN}→ {local}{RESET}  {title}")


# ─────────────────────────────────────────────
# CHECK 8: Videos in log with no local beat file
# ─────────────────────────────────────────────
def check_orphaned_log_entries(log):
    section("CHECK 8 · Uploads With No Local Beat File")
    beat_stems = set()
    for f in BEATS_DIR.glob("*.mp3"):
        beat_stems.add(safe_stem(f.name))
    for f in BEATS_DIR.glob("*.wav"):
        beat_stems.add(safe_stem(f.name))

    found = False
    for stem in sorted(log.keys()):
        if stem not in beat_stems:
            warn(f"{stem}: in uploads_log but no local beat file (collab/old beat?)")
            found = True
    if not found:
        good("All uploads have local beat files")
        print(f"  {GREEN}✓ All uploads have local beat files{RESET}")


# ─────────────────────────────────────────────
# OPTIONAL: Check YouTube for deleted videos
# ─────────────────────────────────────────────
def check_youtube_deleted(log):
    section("CHECK 9 · YouTube Deleted Video Check (API)")
    try:
        sys.path.insert(0, str(ROOT))
        from youtube_auth import get_youtube_service
        youtube = get_youtube_service()
    except Exception as e:
        warn(f"Could not connect to YouTube API: {e}")
        return

    video_ids = {data["videoId"]: stem for stem, data in log.items() if "videoId" in data}
    ids = list(video_ids.keys())
    chunks = [ids[i:i+50] for i in range(0, len(ids), 50)]

    deleted = []
    for chunk in chunks:
        resp = youtube.videos().list(part="id,status", id=",".join(chunk)).execute()
        found_ids = {item["id"] for item in resp.get("items", [])}
        for vid_id in chunk:
            if vid_id not in found_ids:
                stem = video_ids[vid_id]
                deleted.append((stem, vid_id))

    if deleted:
        for stem, vid_id in deleted:
            issue(f"{stem} ({vid_id}): video deleted from YouTube but still in uploads_log.json")
        print(f"\n  Run: python upload.py --sync-deleted  to clean these up")
    else:
        good("No deleted videos")
        print(f"  {GREEN}✓ All logged videos exist on YouTube{RESET}")


# ─────────────────────────────────────────────
# CHECK 11: Age restrictions & Copyright/Content ID
# ─────────────────────────────────────────────
def check_age_and_copyright(log):
    """
    Pulls contentDetails + status for every video in uploads_log.json (50 at a time).
    Flags:
      - Age-restricted videos (ytRating = ytAgeRestricted)
      - Region-blocked videos (regionRestriction.blocked list)
      - Content ID / copyright issues:
          * uploadStatus != "processed"  (stuck / failed / rejected)
          * rejectionReason present      (e.g. "copyright", "duplicate")
          * failureReason present
          * embeddable = False           (often set by Content ID)
          * madeForKids = True           (COPPA flag — kills engagement)
    Prints a clean table and flags anything actionable.
    """
    section("CHECK 11 · Age Restrictions & Copyright / Content ID Issues (API)")
    try:
        sys.path.insert(0, str(ROOT))
        from youtube_auth import get_youtube_service
        youtube = get_youtube_service()
    except Exception as e:
        warn(f"Could not connect to YouTube API: {e}")
        return

    video_ids = {data["videoId"]: (stem, data.get("title", stem))
                 for stem, data in log.items() if "videoId" in data}
    ids   = list(video_ids.keys())
    chunks = [ids[i:i+50] for i in range(0, len(ids), 50)]

    age_restricted   = []
    copyright_issues = []
    region_blocked   = []
    kids_flagged     = []
    not_embeddable   = []
    not_processed    = []
    clean            = 0

    for chunk in chunks:
        resp = youtube.videos().list(
            part="id,status,contentDetails",
            id=",".join(chunk)
        ).execute()

        found_map = {item["id"]: item for item in resp.get("items", [])}

        for vid_id in chunk:
            stem, title = video_ids[vid_id]
            item = found_map.get(vid_id)
            if not item:
                continue  # deleted — check_youtube_deleted handles this

            status  = item.get("status", {})
            content = item.get("contentDetails", {})
            rating  = content.get("contentRating", {})
            region  = content.get("regionRestriction", {})
            url     = f"https://www.youtube.com/watch?v={vid_id}"

            flagged = False

            # Age restriction
            if rating.get("ytRating") == "ytAgeRestricted":
                age_restricted.append((stem, title, url))
                issue(f"AGE-RESTRICTED: \"{title}\"")
                print(f"        → {url}")
                flagged = True

            # Upload status / rejection
            upload_status   = status.get("uploadStatus", "")
            rejection       = status.get("rejectionReason", "")
            failure         = status.get("failureReason", "")
            if upload_status not in ("processed", "uploaded", ""):
                not_processed.append((stem, title, url, upload_status))
                issue(f"UPLOAD STATUS [{upload_status}]: \"{title}\"")
                print(f"        → {url}")
                flagged = True
            if rejection:
                copyright_issues.append((stem, title, url, f"rejected:{rejection}"))
                issue(f"REJECTED [{rejection}]: \"{title}\"")
                print(f"        → {url}")
                flagged = True
            if failure:
                copyright_issues.append((stem, title, url, f"failed:{failure}"))
                issue(f"FAILED [{failure}]: \"{title}\"")
                print(f"        → {url}")
                flagged = True

            # Not embeddable (Content ID lock-down or manual)
            if status.get("embeddable") is False:
                not_embeddable.append((stem, title, url))
                warn(f"NOT EMBEDDABLE (possible Content ID): \"{title}\"")
                print(f"        → {url}")
                flagged = True

            # Region blocked
            blocked_regions = region.get("blocked", [])
            if blocked_regions:
                # Flag if US is blocked (kills most revenue)
                us_blocked = "US" in blocked_regions
                label = f"US+{len(blocked_regions)-1} more" if us_blocked else f"{len(blocked_regions)} regions"
                region_blocked.append((stem, title, url, blocked_regions))
                if us_blocked:
                    issue(f"REGION BLOCKED [{label}]: \"{title}\"")
                else:
                    warn(f"REGION BLOCKED [{label}]: \"{title}\"")
                print(f"        → {url}  blocked: {', '.join(blocked_regions[:5])}")
                flagged = True

            # Made for kids (COPPA — disables comments, notifications, recommendations)
            if status.get("madeForKids") is True:
                kids_flagged.append((stem, title, url))
                warn(f"MADE FOR KIDS (disables comments/notifs): \"{title}\"")
                print(f"        → {url}")
                flagged = True

            if not flagged:
                clean += 1

    total = len(ids)
    print(f"\n  Checked {total} videos:")
    print(f"  {GREEN}✓ Clean: {clean}{RESET}")
    if age_restricted:
        print(f"  {RED}✗ Age-restricted: {len(age_restricted)}{RESET}")
    if copyright_issues:
        print(f"  {RED}✗ Copyright/rejected: {len(copyright_issues)}{RESET}")
    if not_embeddable:
        print(f"  {YELLOW}⚠ Not embeddable: {len(not_embeddable)}{RESET}")
    if region_blocked:
        print(f"  {YELLOW}⚠ Region-blocked: {len(region_blocked)}{RESET}")
    if kids_flagged:
        print(f"  {YELLOW}⚠ Made-for-kids: {len(kids_flagged)}{RESET}")
    if not_processed:
        print(f"  {RED}✗ Bad upload status: {len(not_processed)}{RESET}")

    if not (age_restricted or copyright_issues or not_embeddable
            or region_blocked or kids_flagged or not_processed):
        good("No age/copyright issues")
        print(f"\n  {GREEN}✓ All {total} videos are clean — no age restrictions or copyright flags{RESET}")


# ─────────────────────────────────────────────
# OPTIONAL: Scan entire channel for duplicate titles
# ─────────────────────────────────────────────
def check_channel_duplicates_yt():
    section("CHECK 10 · Channel-Wide Duplicate Titles (API)")
    try:
        sys.path.insert(0, str(ROOT))
        from youtube_auth import get_youtube_service
        youtube = get_youtube_service()
    except Exception as e:
        warn(f"Could not connect to YouTube API: {e}")
        return

    # Get the channel's uploads playlist ID
    chan_resp = youtube.channels().list(part="contentDetails", mine=True).execute()
    uploads_playlist = (
        chan_resp["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]
        if chan_resp.get("items") else None
    )
    if not uploads_playlist:
        warn("Could not find uploads playlist — skipping duplicate check")
        return

    # Page through the uploads playlist to get all video IDs
    all_vid_ids = []
    next_page = None
    while True:
        kwargs = dict(part="snippet", playlistId=uploads_playlist, maxResults=50)
        if next_page:
            kwargs["pageToken"] = next_page
        resp = youtube.playlistItems().list(**kwargs).execute()
        for item in resp.get("items", []):
            vid_id = item["snippet"]["resourceId"].get("videoId", "")
            if vid_id:
                all_vid_ids.append(vid_id)
        next_page = resp.get("nextPageToken")
        if not next_page:
            break

    # Fetch snippet + status in chunks of 50
    all_videos = []
    for i in range(0, len(all_vid_ids), 50):
        chunk = all_vid_ids[i:i+50]
        vresp = youtube.videos().list(part="snippet,status", id=",".join(chunk)).execute()
        for item in vresp.get("items", []):
            vid_id = item["id"]
            title  = item["snippet"].get("title", "")
            status = item["status"].get("privacyStatus", "")
            pub_at = item["snippet"].get("publishedAt", "")
            all_videos.append((vid_id, title, status, pub_at))

    print(f"  Scanned {len(all_videos)} videos on channel")

    # Find duplicate titles
    title_map = defaultdict(list)
    for vid_id, title, status, pub_at in all_videos:
        title_map[title.strip()].append((vid_id, status, pub_at))

    found = False
    for title, entries in title_map.items():
        if len(entries) > 1:
            issue(f"Duplicate title on channel: \"{title}\"")
            for vid_id, status, pub_at in entries:
                url = f"https://www.youtube.com/watch?v={vid_id}"
                print(f"      → {url}  [{status}]  published: {pub_at[:10]}")
            found = True

    if not found:
        good("No channel-wide duplicates")
        print(f"  {GREEN}✓ No duplicate titles found across entire channel{RESET}")


# ─────────────────────────────────────────────
# SUMMARY
# ─────────────────────────────────────────────
def print_summary():
    print(f"\n{BOLD}{'═'*50}{RESET}")
    print(f"{BOLD}  AUDIT SUMMARY{RESET}")
    print(f"{'═'*50}")
    if issues:
        print(f"  {RED}{BOLD}✗ {len(issues)} issue(s) need attention:{RESET}")
        for i in issues:
            print(f"    {RED}• {i}{RESET}")
    else:
        print(f"  {GREEN}{BOLD}✓ No critical issues found!{RESET}")

    if warnings:
        print(f"\n  {YELLOW}⚠ {len(warnings)} warning(s):{RESET}")
        for w in warnings[:10]:
            print(f"    {YELLOW}• {w}{RESET}")
        if len(warnings) > 10:
            print(f"    {YELLOW}... and {len(warnings)-10} more{RESET}")
    print()


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Audit YT automation channel health")
    parser.add_argument("--yt",       action="store_true", help="Check YouTube for deleted videos (uses API quota)")
    parser.add_argument("--silence",  action="store_true", help="Run silence detection on all MP4s (slow)")
    parser.add_argument("--duration", action="store_true", help="Run duration mismatch check (slow)")
    parser.add_argument("--full",     action="store_true", help="Run all checks including slow ones")
    args = parser.parse_args()

    print(f"\n{BOLD}{'═'*50}{RESET}")
    print(f"{BOLD}  FY3 CHANNEL AUDIT{RESET}")
    print(f"  {datetime.now().strftime('%Y-%m-%d %H:%M')}")
    print(f"{'═'*50}{RESET}")

    log = load_log()
    print(f"\n  Loaded {len(log)} uploads from uploads_log.json")

    check_duplicate_titles(log)
    check_schedule_conflicts(log)
    check_missing_metadata()
    check_rendered_not_uploaded(log)
    check_orphaned_log_entries(log)
    check_upcoming_schedule(log)

    if args.silence or args.full:
        check_silent_tails()
    else:
        section("CHECK 3 · Silent Tails  [skipped — run with --silence or --full]")
        print(f"  {YELLOW}⚠ Skipped (slow). Use --silence to enable{RESET}")

    if args.duration or args.full:
        check_duration_mismatches()
    else:
        section("CHECK 4 · Duration Mismatches  [skipped — run with --duration or --full]")
        print(f"  {YELLOW}⚠ Skipped (slow). Use --duration to enable{RESET}")

    if args.yt or args.full:
        check_youtube_deleted(log)
        check_channel_duplicates_yt()
        check_age_and_copyright(log)
    else:
        section("CHECK 9 · YouTube Deleted Videos  [skipped — run with --yt]")
        print(f"  {YELLOW}⚠ Skipped (uses API quota). Use --yt to enable{RESET}")
        section("CHECK 10 · Channel-Wide Duplicates  [skipped — run with --yt]")
        print(f"  {YELLOW}⚠ Skipped (uses API quota). Use --yt to enable{RESET}")
        section("CHECK 11 · Age Restrictions & Copyright  [skipped — run with --yt]")
        print(f"  {YELLOW}⚠ Skipped (uses API quota). Use --yt to enable{RESET}")

    print_summary()
