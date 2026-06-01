"""
pin_short_comments.py

Pins a purchase comment on every uploaded beat video (full videos + shorts).
Comment format:
  🔥 Purchase / Download:
  https://leekthatsfy3.infinity.airbit.com/beats/{slug}

Reads from uploads_log.json + shorts_uploads_log.json + metadata/{stem}.json.
Skips videos that already have a pinned comment (tracked in pinned_comments.json).

Usage:
    python pin_short_comments.py              # pin all missing
    python pin_short_comments.py --dry-run    # preview without posting
    python pin_short_comments.py --stem lick  # single video by stem
    python pin_short_comments.py --shorts-only
    python pin_short_comments.py --full-only
"""

import argparse
import json
import re
import time
from pathlib import Path

ROOT       = Path(__file__).resolve().parent
LOG_PATH   = ROOT / "uploads_log.json"
SLOG_PATH  = ROOT / "shorts_uploads_log.json"
META_DIR   = ROOT / "metadata"
PINNED_LOG = ROOT / "pinned_comments.json"


def get_airbit_link(stem: str) -> str | None:
    """Extract the per-beat Airbit purchase link from metadata description.
    Handles malformed URLs where the path got duplicated — always returns
    the clean base URL: https://leekthatsfy3.infinity.airbit.com/beats/{slug}
    """
    meta_path = META_DIR / f"{stem}.json"
    if meta_path.exists():
        meta = json.loads(meta_path.read_text())
        desc = meta.get("description", "")
        for line in desc.split("\n"):
            line = line.strip()
            if "airbit.com/beats/" in line and line.startswith("http"):
                base_m = re.match(r"https://[^/]+", line)
                if not base_m:
                    continue
                base = base_m.group(0)
                # The URL may be malformed with duplicated path segments.
                # Strategy: take the last non-empty path component after any /beats/ prefix.
                # e.g. /beats/aibeats/ai              → ai
                # e.g. /beats/foo-beats/foo           → foo
                # e.g. /beats/foo/beats/foobeats/foo  → foo
                # e.g. /beats/lick                    → lick
                path = line[len(base):]  # everything after domain
                # Remove query params / fragments
                path = re.split(r"[?#]", path)[0].rstrip("/")
                # Split on / and get the last non-empty component
                parts = [p for p in path.split("/") if p]
                if parts:
                    slug = parts[-1]
                    return f"{base}/beats/{slug}"
    # Fallback: slugify stem
    slug = re.sub(r"[^a-z0-9\-]", "-", stem.replace("_", "-")).strip("-")
    return f"https://leekthatsfy3.infinity.airbit.com/beats/{slug}"


def pin_comment(youtube, video_id: str, text: str) -> str:
    """Post a comment and pin it. Returns the comment thread ID."""
    resp = youtube.commentThreads().insert(
        part="snippet",
        body={
            "snippet": {
                "videoId": video_id,
                "topLevelComment": {
                    "snippet": {"textOriginal": text}
                },
            }
        },
    ).execute()
    return resp["id"]


def build_work_list(log: dict, slog: dict, shorts_only: bool, full_only: bool) -> list[tuple[str, str, str]]:
    """Return list of (stem, video_id, label) tuples."""
    work = []

    if not shorts_only:
        for stem, d in log.items():
            vid = d.get("videoId")
            if vid:
                work.append((stem, vid, "full"))

    if not full_only:
        for stem, d in slog.items():
            vid = d.get("videoId")
            if vid:
                work.append((stem, vid, "short"))

    # Deduplicate by video_id (same video can't appear twice)
    seen_ids = set()
    deduped = []
    for item in work:
        if item[1] not in seen_ids:
            seen_ids.add(item[1])
            deduped.append(item)

    return sorted(deduped, key=lambda x: x[0])


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run",     action="store_true", help="Preview without posting")
    parser.add_argument("--stem",        help="Pin on a single stem only")
    parser.add_argument("--shorts-only", action="store_true")
    parser.add_argument("--full-only",   action="store_true")
    args = parser.parse_args()

    from youtube_auth import get_youtube_service
    youtube = get_youtube_service()

    log    = json.loads(LOG_PATH.read_text())  if LOG_PATH.exists()  else {}
    slog   = json.loads(SLOG_PATH.read_text()) if SLOG_PATH.exists() else {}
    pinned = json.loads(PINNED_LOG.read_text()) if PINNED_LOG.exists() else {}

    work = build_work_list(log, slog, args.shorts_only, args.full_only)

    if args.stem:
        work = [(s, v, l) for s, v, l in work if s == args.stem]

    print(f"Total videos to process: {len(work)}")
    ok = skip = fail = 0

    for stem, video_id, label in work:
        pin_key = f"{stem}_{label}"

        if pin_key in pinned and pinned[pin_key].get("commentId"):
            print(f"[SKIP] {stem} ({label}) — already pinned")
            skip += 1
            continue

        link = get_airbit_link(stem)
        if not link:
            print(f"[MISS] {stem} — no Airbit link")
            continue

        comment_text = f"🔥 Purchase / Download:\n{link}"

        if args.dry_run:
            print(f"[DRY ] {stem} ({label}) → {video_id}")
            print(f"       {comment_text}")
            ok += 1
            continue

        try:
            comment_id = pin_comment(youtube, video_id, comment_text)
            print(f"[PIN ] {stem} ({label}) → comment {comment_id}")
            pinned[pin_key] = {
                "stem":      stem,
                "videoId":   video_id,
                "label":     label,
                "commentId": comment_id,
                "text":      comment_text,
            }
            PINNED_LOG.write_text(json.dumps(pinned, indent=2))
            ok += 1
            time.sleep(1.5)

        except Exception as e:
            err = str(e)
            if "commentsDisabled" in err or "disabled comments" in err.lower():
                print(f"[SKIP] {stem} ({label}) — comments disabled")
                skip += 1
            elif "quotaExceeded" in err:
                print(f"\n⚠ Quota exceeded after {ok} pins — run again tomorrow to continue.")
                break
            elif "videoNotFound" in err or "forbidden" in err.lower():
                print(f"[SKIP] {stem} ({label}) — video not accessible")
                skip += 1
            else:
                print(f"[FAIL] {stem} ({label}): {err}")
                fail += 1

    print(f"\nDone — ✅ pinned: {ok}  ⏭ skipped: {skip}  ❌ failed: {fail}")


if __name__ == "__main__":
    main()
