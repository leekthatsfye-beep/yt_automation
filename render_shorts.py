"""
render_shorts.py

Batch-renders 9:16 portrait Shorts for every beat that has a rendered MP4
but is missing its _9x16.mp4.  Idempotent — skips existing files.

Usage:
    python render_shorts.py                # render all missing
    python render_shorts.py --only "army,glo_man"   # specific beats
    python render_shorts.py --force        # re-render even if exists
    python render_shorts.py --dry-run      # show what would be rendered
"""

from __future__ import annotations

import argparse
import sys
import time
from pathlib import Path

ROOT    = Path(__file__).resolve().parent
OUT_DIR = ROOT / "output"

sys.path.insert(0, str(ROOT))


def p(msg: str) -> None:
    print(msg, flush=True)


def get_stems_needing_shorts(only: list[str] | None = None, force: bool = False) -> list[str]:
    """Return stems that have an MP4 but are missing a _9x16.mp4."""
    stems = []
    for mp4 in sorted(OUT_DIR.glob("*.mp4")):
        stem = mp4.stem
        # Skip non-beat files
        if any(stem.endswith(s) for s in ("_9x16", "_lit", "_backup")):
            continue
        if "_thumb" in stem:
            continue
        # Filter to --only list if given
        if only and stem not in only:
            continue
        short_path = OUT_DIR / f"{stem}_9x16.mp4"
        if short_path.exists() and not force:
            continue
        stems.append(stem)
    return stems


def render_short(stem: str) -> bool:
    """Convert a single beat MP4 to 9:16. Returns True on success."""
    from social_upload import convert_to_portrait
    try:
        path = convert_to_portrait(stem)
        if path and path.exists():
            size_mb = path.stat().st_size / 1024 / 1024
            p(f"  [OK] {stem}_9x16.mp4  ({size_mb:.1f} MB)")
            return True
        else:
            p(f"  [FAIL] {stem} — convert_to_portrait returned None")
            return False
    except Exception as e:
        p(f"  [ERR] {stem} — {e}")
        return False


def main() -> None:
    parser = argparse.ArgumentParser(description="Batch render 9:16 Shorts")
    parser.add_argument("--only", type=str, default="",
                        help="Comma-separated stems to process")
    parser.add_argument("--force", action="store_true",
                        help="Re-render even if _9x16.mp4 already exists")
    parser.add_argument("--dry-run", action="store_true",
                        help="Show what would be rendered without doing it")
    args = parser.parse_args()

    only = [s.strip() for s in args.only.split(",") if s.strip()] if args.only else None
    stems = get_stems_needing_shorts(only=only, force=args.force)

    if not stems:
        p("✅ All beats already have 9x16 Shorts rendered.")
        return

    p(f"🎬 Rendering {len(stems)} Shorts{'  (DRY RUN)' if args.dry_run else ''}...")
    p("")

    ok = fail = 0
    t0 = time.time()

    for i, stem in enumerate(stems, 1):
        p(f"[{i}/{len(stems)}] {stem}")
        if args.dry_run:
            p(f"  [DRY RUN] would render {stem}_9x16.mp4")
            ok += 1
            continue
        if render_short(stem):
            ok += 1
        else:
            fail += 1

    elapsed = time.time() - t0
    p("")
    p(f"━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━━")
    p(f"  Done in {elapsed:.0f}s — ✅ {ok} rendered  ❌ {fail} failed")
    if fail:
        p(f"  Run again or check logs for failed items.")


if __name__ == "__main__":
    main()
