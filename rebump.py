"""
rebump.py

Re-upload helper — bumps a beat to a new stem (e.g. starvin → starvin_v2)
so it can be re-uploaded to YouTube without touching old data.

What it creates per stem:
  beats/{new}.mp3           — copy of original audio (new filename)
  output/{new}.mp4          — copy of existing rendered video
  output/{new}_thumb.jpg    — copy of existing thumbnail
  metadata/{new}.json       — copy of metadata with title slightly varied

What it NEVER touches:
  uploads_log.json
  output/{old}.mp4 / output/{old}_thumb.jpg
  metadata/{old}.json
  beats/{old}*.mp3

Usage:
    python rebump.py --auto                         # bump all colliding root beats/
    python rebump.py --only "starvin,walk_ups"      # explicit stems
    python rebump.py --auto --dry-run               # preview only
    python rebump.py --only "starvin" --version 3   # force _v3
"""

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT      = Path(__file__).resolve().parent
BEATS_DIR = ROOT / "beats"
META_DIR  = ROOT / "metadata"
OUT_DIR   = ROOT / "output"
LOG_FILE  = ROOT / "uploads_log.json"


# ── safe_stem: verbatim copy from render_lit.py ───────────────────────────

def safe_stem(path: Path) -> str:
    s = path.stem.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s.strip("_")


# ── Title variation ────────────────────────────────────────────────────────

def tweak_title(title: str, version_num: int) -> str:
    """Append ' !' to distinguish re-uploads without cluttering the title."""
    _ = version_num  # unused
    return f"{title} !"


# ── Core helpers ───────────────────────────────────────────────────────────

def load_log() -> dict:
    if LOG_FILE.exists():
        try:
            return json.loads(LOG_FILE.read_text())
        except Exception:
            return {}
    return {}


def find_next_version(base_stem: str, log: dict) -> str:
    """Return the lowest _vN suffix (N ≥ 2) not already in uploads_log."""
    for n in range(2, 100):
        candidate = f"{base_stem}_v{n}"
        if candidate not in log:
            return candidate
    raise RuntimeError(f"Could not find a free version for '{base_stem}' (tried v2–v99)")


def find_audio_for_stem(stem: str) -> Path | None:
    """Return the first root-level beats/ file whose safe_stem matches."""
    for f in sorted(BEATS_DIR.iterdir()):
        if f.is_dir():
            continue
        if f.suffix.lower() not in (".mp3", ".wav"):
            continue
        if safe_stem(f) == stem:
            return f
    return None


# ── Main bump logic ────────────────────────────────────────────────────────

def bump_stem(
    old_stem: str,
    log: dict,
    force_version: int | None = None,
    dry_run: bool = False,
) -> dict:
    """
    Copy all pipeline assets from old_stem to new_stem.

    Returns:
        {
            "old_stem":  str,
            "new_stem":  str | None,
            "actions":   list[str],
            "errors":    list[str],
        }
    """
    result: dict = {
        "old_stem": old_stem,
        "new_stem": None,
        "actions": [],
        "errors": [],
    }

    # ── Determine new stem ─────────────────────────────────────────────────
    if force_version is not None:
        new_stem = f"{old_stem}_v{force_version}"
        if new_stem in log:
            result["errors"].append(
                f"'{new_stem}' is already in uploads_log.json — choose a different version"
            )
            return result
    else:
        new_stem = find_next_version(old_stem, log)
    result["new_stem"] = new_stem

    version_num = int(new_stem.rsplit("_v", 1)[1])

    def do_copy(src: Path, dst: Path, label: str):
        result["actions"].append(f"COPY  {label}")
        if not dry_run:
            shutil.copy2(str(src), str(dst))

    # ── 1. Audio ──────────────────────────────────────────────────────────
    old_audio = find_audio_for_stem(old_stem)
    if old_audio:
        new_audio = BEATS_DIR / f"{new_stem}{old_audio.suffix.lower()}"
        do_copy(old_audio, new_audio, f"beats/{old_audio.name}  →  beats/{new_audio.name}")
    else:
        result["errors"].append(
            f"No audio file in beats/ maps to stem '{old_stem}' — audio copy skipped"
        )

    # ── 2. Rendered MP4 ───────────────────────────────────────────────────
    old_mp4 = OUT_DIR / f"{old_stem}.mp4"
    if old_mp4.exists():
        new_mp4 = OUT_DIR / f"{new_stem}.mp4"
        do_copy(old_mp4, new_mp4, f"output/{old_stem}.mp4  →  output/{new_stem}.mp4")
    else:
        result["errors"].append(
            f"output/{old_stem}.mp4 not found — MP4 copy skipped (run render_lit.py first?)"
        )

    # ── 3. Thumbnail ──────────────────────────────────────────────────────
    old_thumb = OUT_DIR / f"{old_stem}_thumb.jpg"
    if old_thumb.exists():
        new_thumb = OUT_DIR / f"{new_stem}_thumb.jpg"
        do_copy(old_thumb, new_thumb,
                f"output/{old_stem}_thumb.jpg  →  output/{new_stem}_thumb.jpg")
    else:
        result["errors"].append(
            f"output/{old_stem}_thumb.jpg not found — thumbnail copy skipped"
        )

    # ── 4. Metadata JSON ──────────────────────────────────────────────────
    old_meta_path = META_DIR / f"{old_stem}.json"
    if old_meta_path.exists():
        try:
            meta = json.loads(old_meta_path.read_text())
        except Exception as e:
            result["errors"].append(f"metadata/{old_stem}.json is corrupt: {e}")
            meta = {}

        original_title = meta.get("title", old_stem)
        meta["title"] = tweak_title(original_title, version_num)

        new_meta_path = META_DIR / f"{new_stem}.json"
        result["actions"].append(
            f"CREATE metadata/{new_stem}.json  (title: {meta['title']!r})"
        )
        if not dry_run:
            new_meta_path.write_text(json.dumps(meta, indent=2))
    else:
        result["errors"].append(
            f"metadata/{old_stem}.json not found — metadata creation skipped"
        )

    return result


# ── Entry point ────────────────────────────────────────────────────────────

def main():
    parser = argparse.ArgumentParser(
        description="Bump colliding beat stems to new versions for re-upload.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  python rebump.py --auto
  python rebump.py --only "starvin,walk_ups,raw_asf,6"
  python rebump.py --auto --dry-run
  python rebump.py --only "starvin" --version 3
""",
    )
    parser.add_argument("--auto", action="store_true",
                        help="Auto-detect all root beats/ whose stem is already in uploads_log.json")
    parser.add_argument("--only", type=str, default=None,
                        help="Comma-separated old stems to bump")
    parser.add_argument("--version", type=int, default=None,
                        help="Force a specific version number (single stem only)")
    parser.add_argument("--dry-run", action="store_true",
                        help="Print what would happen without writing any files")
    args = parser.parse_args()

    if not args.auto and not args.only:
        parser.error("Provide --auto or --only <stems>")
    if args.version and args.only and len(args.only.split(",")) > 1:
        parser.error("--version can only be used with a single stem in --only")

    log = load_log()

    # ── Build stem list ────────────────────────────────────────────────────
    if args.only:
        requested = [s.strip() for s in args.only.split(",") if s.strip()]
    else:
        seen: set[str] = set()
        requested = []
        for f in sorted(BEATS_DIR.iterdir()):
            if f.is_dir() or f.suffix.lower() not in (".mp3", ".wav"):
                continue
            stem = safe_stem(f)
            if stem in log and stem not in seen:
                requested.append(stem)
                seen.add(stem)
        if not requested:
            print("No collisions found — all root beats/ files have fresh stems.")
            sys.exit(0)

    # ── Warn about non-colliding stems when using --only ──────────────────
    if args.only:
        for stem in requested:
            if stem not in log:
                print(f"[WARN] '{stem}' is not in uploads_log.json — no collision detected. "
                      f"You can upload it directly: python upload.py --only {stem}")

    # ── Process ────────────────────────────────────────────────────────────
    mode_label = "[DRY RUN] " if args.dry_run else ""
    print(f"\n{'─'*62}")
    print(f"  rebump.py  |  {mode_label}{len(requested)} stem(s)")
    print(f"{'─'*62}\n")

    results = []
    for stem in requested:
        r = bump_stem(stem, log, force_version=args.version, dry_run=args.dry_run)
        results.append(r)

    # ── Report ─────────────────────────────────────────────────────────────
    success_count = 0
    for r in results:
        new = r["new_stem"] or "???"
        print(f"  {r['old_stem']}  →  {new}")
        for action in r["actions"]:
            prefix = "[DRY] " if args.dry_run else ""
            print(f"    {prefix}+ {action}")
        for err in r["errors"]:
            print(f"    [WARN] {err}")
        if not r["errors"]:
            success_count += 1
        print()

    print(f"{'─'*62}")
    if args.dry_run:
        print("  [DRY RUN] No files written. Remove --dry-run to execute.")
    else:
        print(f"  Done: {success_count}/{len(results)} bump(s) complete.")
        good = [r["new_stem"] for r in results if r["new_stem"] and not r["errors"]]
        if good:
            stems_csv = ",".join(good)
            print(f"\n  Next step — upload:")
            print(f"    python upload.py --only \"{stems_csv}\"")
    print(f"{'─'*62}\n")


if __name__ == "__main__":
    main()
