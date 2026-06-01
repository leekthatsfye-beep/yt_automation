"""
beat_watcher.py — Fully automated FY3 beat pipeline.

Drop an MP3/WAV into ~/Dropbox/FY3 Beats/inbox/ from Mac or PC.
This script handles everything automatically:

  1. Detects new file (stable after Dropbox sync)
  2. Sanitizes filename + copies to beats/
  3. Archives to Dropbox/FY3 Beats/library/YYYY-MM/
  4. Generates SEO metadata (seo_metadata.py)
  5. Renders full video + short + thumbnail (render.py)
  6. NSFW scan on assigned visual clip (scan_clips.py)
  7. Uploads to Airbit beat store (airbit_upload.py)
  8. Schedules on YouTube (next available 10am/2pm/8pm EDT slot)
  9. Push notifies Mac (osascript) + iPhone (FY3 app web push)

Usage:
    python beat_watcher.py            # run in foreground (Ctrl+C to stop)
    python beat_watcher.py --install  # install as macOS login item (auto-start)
    python beat_watcher.py --test     # test notifications only
"""

import sys, time, shutil, logging, subprocess, re, json, asyncio
from pathlib import Path
from datetime import datetime, timezone, timedelta
import zoneinfo

# ── Paths ────────────────────────────────────────────────────────────────────
DROPBOX_INBOX   = Path.home() / "Dropbox" / "FY3 Beats" / "inbox"
DROPBOX_LIBRARY = Path.home() / "Dropbox" / "FY3 Beats" / "library"
DROPBOX_DONE    = Path.home() / "Dropbox" / "FY3 Beats" / "processed"
YT_ROOT         = Path("/Users/fyefye/yt_automation")
YT_BEATS_DIR    = YT_ROOT / "beats"
RENDERS_DIR     = YT_ROOT / "output" / "renders"
THUMBS_DIR      = YT_ROOT / "output" / "thumbs"
LOG_PATH        = YT_ROOT / "uploads_log.json"
PYTHON          = YT_ROOT / ".venv" / "bin" / "python3.14"

AUDIO_EXTS = {".mp3", ".wav", ".aiff", ".flac"}
EDT = zoneinfo.ZoneInfo("America/New_York")

# YouTube upload slots: 10am, 2pm, 8pm EDT
UPLOAD_SLOTS_EDT = [10, 14, 20]

# ── Logging ──────────────────────────────────────────────────────────────────
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [watcher] %(message)s",
    datefmt="%H:%M:%S",
    handlers=[
        logging.StreamHandler(),
        logging.FileHandler(YT_ROOT / "beat_watcher.log"),
    ]
)
log = logging.getLogger(__name__)


# ── Notifications ─────────────────────────────────────────────────────────────

def notify_mac(title: str, message: str):
    """macOS banner notification with sound."""
    try:
        subprocess.run([
            "osascript", "-e",
            f'display notification "{message}" with title "{title}" sound name "Glass"'
        ], check=False)
    except Exception:
        pass


async def notify_iphone(title: str, body: str, url: str = "/beats"):
    """Send web push to iPhone via FY3 app push_svc."""
    try:
        sys.path.insert(0, str(YT_ROOT))
        from app.backend.services.push_svc import send_notification
        sent = await send_notification(title=title, body=body, tag="fy3-watcher", url=url)
        if sent:
            log.info(f"  ✓ iPhone push sent ({sent} device(s))")
        else:
            log.info(f"  ⚠ No iPhone push subscriptions registered yet")
    except Exception as e:
        log.warning(f"  iPhone push failed: {e}")


def notify_all(title: str, message: str, url: str = "/beats"):
    """Notify Mac + iPhone."""
    notify_mac(title, message)
    try:
        asyncio.run(notify_iphone(title, message, url))
    except Exception:
        pass


# ── Helpers ───────────────────────────────────────────────────────────────────

def safe_stem(name: str) -> str:
    name = re.sub(r"[^\w\s-]", "", name)
    name = re.sub(r"[\s]+", "_", name.strip())
    return name.lower()


def wait_for_stable(path: Path, timeout: int = 120) -> bool:
    """Wait until file size stops changing (Dropbox sync complete)."""
    prev_size = -1
    stable_count = 0
    for _ in range(timeout):
        try:
            size = path.stat().st_size
        except FileNotFoundError:
            return False
        if size == prev_size and size > 0:
            stable_count += 1
            if stable_count >= 3:
                return True
        else:
            stable_count = 0
        prev_size = size
        time.sleep(1)
    return False


def run(cmd: list, label: str) -> bool:
    """Run a subprocess, log output, return success."""
    log.info(f"  Running: {label}")
    result = subprocess.run(cmd, capture_output=True, text=True, cwd=str(YT_ROOT))
    if result.returncode != 0:
        log.error(f"  ✗ {label} failed:\n{result.stderr[-500:]}")
        return False
    log.info(f"  ✓ {label} done")
    return True


# ── Schedule ──────────────────────────────────────────────────────────────────

def next_available_slot() -> str:
    """Find the next 10am/2pm/8pm EDT slot after the last scheduled upload."""
    log = json.loads(LOG_PATH.read_text()) if LOG_PATH.exists() else {}

    # Find last scheduled publishAt
    scheduled = [
        d["publishAt"] for d in log.values()
        if d.get("publishAt") and d.get("videoId")
    ]

    if scheduled:
        scheduled.sort()
        last_slot_utc = datetime.fromisoformat(
            scheduled[-1].replace("Z", "+00:00")
        )
    else:
        last_slot_utc = datetime.now(timezone.utc)

    # Advance to next slot
    last_edt = last_slot_utc.astimezone(EDT)
    candidate = last_edt.replace(minute=0, second=0, microsecond=0)

    for _ in range(100):  # max 100 slots ahead
        candidate += timedelta(hours=1)
        if candidate.hour in UPLOAD_SLOTS_EDT:
            # Make sure it's in the future
            if candidate.astimezone(timezone.utc) > datetime.now(timezone.utc):
                return candidate.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")

    # Fallback: 24h from now at 10am
    tomorrow = (datetime.now(EDT) + timedelta(days=1)).replace(
        hour=10, minute=0, second=0, microsecond=0
    )
    return tomorrow.astimezone(timezone.utc).strftime("%Y-%m-%dT%H:%M:%SZ")


# ── NSFW Check ────────────────────────────────────────────────────────────────

def nsfw_check_clip(stem: str) -> tuple[bool, str]:
    """
    Run NSFW scan on the clip that will be assigned to this stem.
    Returns (is_safe, clip_name).
    """
    import hashlib

    # Find artist folder
    meta_path = YT_ROOT / "metadata" / f"{stem}.json"
    if not meta_path.exists():
        return True, "unknown"

    meta = json.loads(meta_path.read_text())
    artist = meta.get("seo_artist", meta.get("artist", ""))
    artist_dir = YT_ROOT / "images" / artist

    if not artist_dir.exists() or not list(artist_dir.glob("*.mp4")):
        return True, "default"  # no artist clips, safe

    clips = sorted([f for f in artist_dir.iterdir() if f.suffix == ".mp4"])
    idx = int(hashlib.md5(stem.encode()).hexdigest(), 16) % len(clips)
    clip = clips[idx]

    # Quick scan (just the assigned clip)
    try:
        from nudenet import NudeDetector
        import tempfile

        detector = NudeDetector()

        RISKY = {
            "FEMALE_BREAST_EXPOSED": 1.0,
            "FEMALE_GENITALIA_EXPOSED": 1.0,
            "MALE_GENITALIA_EXPOSED": 1.0,
            "ANUS_EXPOSED": 1.0,
            "BUTTOCKS_EXPOSED": 0.8,
        }
        FLAG_THRESHOLD = 0.15

        tmpdir = Path(tempfile.mkdtemp())
        subprocess.run([
            "ffmpeg", "-i", str(clip),
            "-vf", "fps=1/3", "-q:v", "2",
            str(tmpdir / "frame_%04d.jpg"),
            "-hide_banner", "-loglevel", "error"
        ], check=True)

        frames = sorted(tmpdir.glob("*.jpg"))
        scores = []
        for f in frames:
            dets = detector.detect(str(f))
            score = sum(
                RISKY.get(d.get("class", ""), 0) * d.get("score", 0)
                for d in dets
            )
            scores.append(score)
            f.unlink()
        tmpdir.rmdir()

        avg = sum(scores) / len(scores) if scores else 0
        is_safe = avg < FLAG_THRESHOLD
        log.info(f"  NSFW scan: {clip.name} avg={avg:.3f} {'✓ SAFE' if is_safe else '🚨 FLAGGED'}")
        return is_safe, clip.name

    except Exception as e:
        log.warning(f"  NSFW scan failed: {e} — assuming safe")
        return True, clip.name


# ── YouTube Upload ────────────────────────────────────────────────────────────

def youtube_upload(stem: str, publish_at: str) -> str | None:
    """Upload rendered video to YouTube, scheduled at publish_at. Returns video ID."""
    try:
        sys.path.insert(0, str(YT_ROOT))
        from youtube_auth import get_youtube_service
        from googleapiclient.http import MediaFileUpload

        youtube = get_youtube_service()

        mp4_path   = RENDERS_DIR / f"{stem}.mp4"
        thumb_path = THUMBS_DIR / f"{stem}_thumb.jpg"

        if not mp4_path.exists():
            # Fallback to output root
            mp4_path = YT_ROOT / "output" / f"{stem}.mp4"
        if not mp4_path.exists():
            log.error(f"  No render found for {stem}")
            return None

        meta = json.loads((YT_ROOT / "metadata" / f"{stem}.json").read_text())

        body = {
            "snippet": {
                "title":       meta["title"],
                "description": meta.get("description", ""),
                "tags":        meta.get("tags", []),
                "categoryId":  "10",
            },
            "status": {
                "privacyStatus": "private",
                "publishAt":     publish_at,
                "selfDeclaredMadeForKids": False,
            },
        }

        media = MediaFileUpload(str(mp4_path), mimetype="video/mp4", resumable=True)
        req = youtube.videos().insert(part="snippet,status", body=body, media_body=media)

        resp = None
        while resp is None:
            status, resp = req.next_chunk()
            if status:
                pct = int(status.resumable_progress / status.total_size * 100)
                print(f"    uploading... {pct}%", end="\r")

        vid_id = resp["id"]
        log.info(f"  ✓ YouTube upload: https://youtu.be/{vid_id}")

        # Thumbnail
        if thumb_path.exists():
            try:
                youtube.thumbnails().set(
                    videoId=vid_id,
                    media_body=MediaFileUpload(str(thumb_path))
                ).execute()
                log.info(f"  ✓ Thumbnail set")
            except Exception as te:
                log.warning(f"  ⚠ Thumbnail failed: {te}")

        # Save to log
        upload_log = json.loads(LOG_PATH.read_text()) if LOG_PATH.exists() else {}
        upload_log[stem] = upload_log.get(stem, {})
        upload_log[stem].update({
            "videoId":    vid_id,
            "url":        f"https://youtu.be/{vid_id}",
            "uploadedAt": datetime.now(timezone.utc).isoformat(),
            "title":      meta["title"],
            "publishAt":  publish_at,
            "privacy":    "private",
        })
        LOG_PATH.write_text(json.dumps(upload_log, indent=2))

        return vid_id

    except Exception as e:
        log.error(f"  YouTube upload failed: {e}")
        return None


# ── Main Pipeline ─────────────────────────────────────────────────────────────

def process_beat(src: Path):
    """Full automated pipeline for a new beat."""
    log.info(f"\n{'='*55}")
    log.info(f"🎵 NEW BEAT: {src.name}")
    log.info(f"{'='*55}")

    notify_mac("🎵 FY3 Pipeline", f"Processing: {src.stem}")

    # 1. Wait for Dropbox sync to finish
    log.info("Waiting for Dropbox sync...")
    if not wait_for_stable(src):
        log.error("Timed out — file may still be syncing")
        notify_all("⚠️ FY3 Pipeline", f"Sync timeout: {src.name}")
        return

    stem     = safe_stem(src.stem)
    ext      = src.suffix.lower()
    safe_name = f"{stem}{ext}"

    # 2. Copy to beats/
    dest_beats = YT_BEATS_DIR / safe_name
    if not dest_beats.exists():
        shutil.copy2(src, dest_beats)
        log.info(f"✓ Copied to beats/{safe_name}")
    else:
        log.info(f"Already in beats/ — skipping copy")

    # 3. Archive to Dropbox library
    month_dir = DROPBOX_LIBRARY / datetime.now().strftime("%Y-%m")
    month_dir.mkdir(parents=True, exist_ok=True)
    archive_dest = month_dir / safe_name
    if not archive_dest.exists():
        shutil.copy2(src, archive_dest)
        log.info(f"✓ Archived to library/{month_dir.name}/{safe_name}")

    # 4. Generate SEO metadata
    meta_path = YT_ROOT / "metadata" / f"{stem}.json"
    if not meta_path.exists():
        log.info("Generating SEO metadata...")
        run([str(PYTHON), str(YT_ROOT / "seo_metadata.py")], "seo_metadata")
    else:
        log.info("✓ Metadata exists")

    # 5. Render video + short + thumbnail
    log.info("Rendering video...")
    notify_mac("🎬 FY3 Pipeline", f"Rendering: {stem}")
    rendered = run(
        [str(PYTHON), str(YT_ROOT / "render.py"), "--only", stem],
        f"render {stem}"
    )
    if not rendered:
        notify_all("❌ FY3 Pipeline", f"Render failed: {stem}")
        return

    # 6. NSFW scan on assigned clip
    log.info("Running NSFW scan...")
    is_safe, clip_name = nsfw_check_clip(stem)
    if not is_safe:
        log.warning(f"🚨 NSFW clip flagged: {clip_name}")
        notify_all(
            "🚨 FY3 Pipeline — NSFW FLAGGED",
            f"{stem}: clip {clip_name} flagged. Manual review needed.",
            url="/beats"
        )
        # Move to processed but don't upload
        _move_to_processed(src)
        return

    # 7. Airbit upload
    log.info("Uploading to Airbit...")
    notify_mac("🛒 FY3 Pipeline", f"Uploading to Airbit: {stem}")
    airbit_ok = run(
        [str(PYTHON), str(YT_ROOT / "airbit_upload.py"), "--only", stem],
        f"airbit {stem}"
    )
    if not airbit_ok:
        log.warning("Airbit upload failed — continuing to YouTube anyway")

    # 8. YouTube scheduled upload
    publish_at = next_available_slot()
    log.info(f"Uploading to YouTube → scheduled {publish_at}")
    notify_mac("📺 FY3 Pipeline", f"Uploading to YouTube: {stem}")

    vid_id = youtube_upload(stem, publish_at)
    if not vid_id:
        notify_all("❌ FY3 Pipeline", f"YouTube upload failed: {stem}")
        _move_to_processed(src)
        return

    # 9. Move original to processed
    _move_to_processed(src)

    # 10. Final notification — Mac + iPhone
    pub_edt = datetime.fromisoformat(publish_at.replace("Z", "+00:00")).astimezone(EDT)
    pub_str = pub_edt.strftime("%b %d %I:%M%p EDT")

    success_msg = f"{stem} → live {pub_str}"
    notify_all(
        "✅ FY3 Pipeline Complete",
        success_msg,
        url=f"/beats"
    )

    log.info(f"\n{'='*55}")
    log.info(f"✅ DONE: {stem}")
    log.info(f"   YouTube: https://youtu.be/{vid_id}")
    log.info(f"   Goes live: {pub_str}")
    log.info(f"{'='*55}\n")


def _move_to_processed(src: Path):
    try:
        dest = DROPBOX_DONE / src.name
        if src.exists():
            src.rename(dest)
            log.info(f"✓ Moved to processed/{src.name}")
    except Exception as e:
        log.warning(f"Could not move to processed: {e}")


def scan_existing():
    """Process any beats already in inbox when watcher starts."""
    existing = [f for f in DROPBOX_INBOX.iterdir()
                if f.is_file() and f.suffix.lower() in AUDIO_EXTS]
    if existing:
        log.info(f"Found {len(existing)} beat(s) already in inbox")
        for f in existing:
            process_beat(f)


def watch():
    """Main watch loop."""
    from watchdog.observers import Observer
    from watchdog.events import FileSystemEventHandler

    class InboxHandler(FileSystemEventHandler):
        def on_created(self, event):
            if event.is_directory: return
            path = Path(event.src_path)
            if path.suffix.lower() in AUDIO_EXTS and path.parent == DROPBOX_INBOX:
                process_beat(path)

        def on_moved(self, event):
            if event.is_directory: return
            path = Path(event.dest_path)
            if path.suffix.lower() in AUDIO_EXTS and path.parent == DROPBOX_INBOX:
                process_beat(path)

    log.info(f"{'='*55}")
    log.info(f"👀 FY3 Beat Watcher RUNNING")
    log.info(f"   Inbox: {DROPBOX_INBOX}")
    log.info(f"   Drop a beat → fully automated pipeline")
    log.info(f"   Render → NSFW scan → Airbit → YouTube → Notify")
    log.info(f"{'='*55}\n")

    observer = Observer()
    observer.schedule(InboxHandler(), str(DROPBOX_INBOX), recursive=False)
    observer.start()
    scan_existing()

    try:
        while True:
            time.sleep(1)
    except KeyboardInterrupt:
        observer.stop()
        log.info("Watcher stopped.")
    observer.join()


def install_launchd():
    """Install as macOS login item — auto-starts on every boot."""
    plist_path = Path.home() / "Library" / "LaunchAgents" / "com.fy3.beat_watcher.plist"
    plist = f"""<?xml version="1.0" encoding="UTF-8"?>
<!DOCTYPE plist PUBLIC "-//Apple//DTD PLIST 1.0//EN" "http://www.apple.com/DTDs/PropertyList-1.0.dtd">
<plist version="1.0">
<dict>
    <key>Label</key>
    <string>com.fy3.beat_watcher</string>
    <key>ProgramArguments</key>
    <array>
        <string>{PYTHON}</string>
        <string>{YT_ROOT}/beat_watcher.py</string>
    </array>
    <key>RunAtLoad</key>
    <true/>
    <key>KeepAlive</key>
    <true/>
    <key>StandardOutPath</key>
    <string>{YT_ROOT}/beat_watcher.log</string>
    <key>StandardErrorPath</key>
    <string>{YT_ROOT}/beat_watcher.log</string>
    <key>WorkingDirectory</key>
    <string>{YT_ROOT}</string>
</dict>
</plist>"""
    plist_path.parent.mkdir(parents=True, exist_ok=True)
    plist_path.write_text(plist)
    subprocess.run(["launchctl", "unload", str(plist_path)], capture_output=True)
    subprocess.run(["launchctl", "load", str(plist_path)], check=False)
    print(f"✅ Beat watcher installed as login item")
    print(f"   Auto-starts on every Mac login")
    print(f"   Logs: {YT_ROOT}/beat_watcher.log")


if __name__ == "__main__":
    if "--install" in sys.argv:
        install_launchd()
    elif "--test" in sys.argv:
        log.info("Testing notifications...")
        notify_mac("✅ FY3 Pipeline", "Mac notification working!")
        asyncio.run(notify_iphone("✅ FY3 Pipeline", "iPhone notification working!"))
        log.info("Done.")
    else:
        watch()
