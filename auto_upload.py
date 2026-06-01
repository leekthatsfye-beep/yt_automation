"""
auto_upload.py
──────────────
Watches the output/ folder and automatically uploads to YouTube whenever
3 or more rendered beats are ready (rendered but not yet uploaded).

Usage:
    # Check once and upload if 3+ are ready (use in cron or after render)
    python3 auto_upload.py

    # Watch continuously, checking every 60 seconds
    python3 auto_upload.py --watch

    # Override the threshold (e.g. upload after every 1 new beat)
    python3 auto_upload.py --threshold 1

    # Dry run — show what would be uploaded
    python3 auto_upload.py --dry-run

How it integrates:
    render.py already writes output/{stem}.mp4 + output/{stem}_thumb.jpg.
    upload.py reads uploads_log.json and skips already-uploaded stems.
    This script bridges them: finds stems with .mp4 but no uploads_log entry,
    and calls upload.py when enough accumulate.
"""

import argparse
import json
import subprocess
import sys
import time
from pathlib import Path

ROOT = Path(__file__).resolve().parent
OUTPUT = ROOT / "output"
UPLOADS_LOG = ROOT / "uploads_log.json"
PYTHON = sys.executable

DEFAULT_THRESHOLD = 3  # upload after this many pending beats


def get_pending_stems() -> list[str]:
    """Return stems that have a rendered .mp4 but no entry in uploads_log.json."""
    # Load already-uploaded stems
    uploaded = set()
    if UPLOADS_LOG.exists():
        try:
            log = json.loads(UPLOADS_LOG.read_text())
            uploaded = set(log.keys())
        except Exception:
            pass

    # Find rendered stems
    pending = []
    for mp4 in sorted(OUTPUT.glob("*.mp4")):
        stem = mp4.stem
        if stem not in uploaded:
            pending.append(stem)

    return pending


def run_upload(stems: list[str], dry_run: bool = False) -> bool:
    """Call upload.py for the given stems. Returns True on success."""
    stems_str = ",".join(stems)
    cmd = [PYTHON, "upload.py", "--only", stems_str]
    if dry_run:
        cmd.append("--dry-run")

    print(f"\n[AUTO-UPLOAD] Triggering upload for: {stems_str}")
    print(f"  Command: {' '.join(cmd)}")

    if dry_run:
        print("  [DRY RUN] — not actually uploading")
        return True

    result = subprocess.run(cmd, cwd=ROOT)
    return result.returncode == 0


def check_and_upload(threshold: int, dry_run: bool) -> int:
    """Check for pending beats. Upload if threshold is met. Returns count uploaded."""
    pending = get_pending_stems()
    print(f"[AUTO-UPLOAD] Pending (rendered, not uploaded): {len(pending)}")

    if not pending:
        print("  Nothing to upload.")
        return 0

    for s in pending:
        print(f"  - {s}")

    if len(pending) < threshold:
        print(f"  Threshold not met ({len(pending)}/{threshold}). Waiting for more beats.")
        return 0

    # Upload all pending
    success = run_upload(pending, dry_run=dry_run)
    if success:
        print(f"  [OK] Upload complete for {len(pending)} beats.")
        return len(pending)
    else:
        print("  [ERROR] Upload failed — check output above.")
        return 0


def main():
    parser = argparse.ArgumentParser(description="Auto-upload when N beats are ready")
    parser.add_argument("--threshold", type=int, default=DEFAULT_THRESHOLD,
                        help=f"Upload after this many pending beats (default: {DEFAULT_THRESHOLD})")
    parser.add_argument("--watch", action="store_true",
                        help="Keep running, check every 60 seconds")
    parser.add_argument("--interval", type=int, default=60,
                        help="Check interval in seconds when watching (default: 60)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be uploaded without doing it")
    args = parser.parse_args()

    if args.watch:
        print(f"[AUTO-UPLOAD] Watching for {args.threshold}+ pending beats (interval: {args.interval}s)")
        print("  Press Ctrl+C to stop.\n")
        while True:
            try:
                check_and_upload(args.threshold, args.dry_run)
                time.sleep(args.interval)
            except KeyboardInterrupt:
                print("\n[AUTO-UPLOAD] Stopped.")
                break
    else:
        check_and_upload(args.threshold, args.dry_run)


if __name__ == "__main__":
    main()
