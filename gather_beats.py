"""
gather_beats.py

Pulls audio (.mp3/.wav) from the source folders listed in beat_sources.json
into beats\\, ready for render.py. Sources can be local folders or Dropbox
folders (online-only Dropbox files are downloaded on copy).

- Dedupes by the SAME safe-stem rule render.py uses, so a beat already in
  beats\\ (under any spelling) is never copied twice.
- With skip_already_rendered, beats already turned into output\\{stem}.mp4
  are skipped too.
- Never deletes or modifies the source files — only copies.

Usage:
    python gather_beats.py --dry-run          # show what WOULD be copied (recommended first)
    python gather_beats.py                     # copy new beats from all enabled sources
    python gather_beats.py --source local_organized   # only one named source
    python gather_beats.py --limit 25          # copy at most N (handy for a test batch)
"""
from __future__ import annotations

import argparse
import json
import re
import shutil
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
BEATS_DIR = ROOT / "beats"
OUT_DIR = ROOT / "output"
CONFIG = ROOT / "beat_sources.json"

AUDIO_EXTS = (".mp3", ".wav")


def safe_stem(path: Path) -> str:
    """Normalize a filename to a safe stem — identical to render.py."""
    s = path.stem.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s.strip("_")


def load_config() -> dict:
    if not CONFIG.exists():
        print(f"[ERROR] {CONFIG.name} not found.")
        sys.exit(1)
    try:
        return json.loads(CONFIG.read_text(encoding="utf-8"))
    except Exception as exc:
        print(f"[ERROR] could not parse {CONFIG.name}: {exc}")
        sys.exit(1)


def existing_stems() -> set[str]:
    """Stems already present in beats\\ (so we never copy a duplicate)."""
    stems = set()
    if BEATS_DIR.is_dir():
        for f in BEATS_DIR.iterdir():
            if f.suffix.lower() in AUDIO_EXTS:
                stems.add(safe_stem(f))
    return stems


def rendered_stems() -> set[str]:
    """Stems that already have a finished render in output\\."""
    stems = set()
    if OUT_DIR.is_dir():
        for f in OUT_DIR.glob("*.mp4"):
            stems.add(safe_stem(f))
    return stems


def iter_audio(folder: Path, recurse: bool):
    globber = folder.rglob if recurse else folder.glob
    for ext in AUDIO_EXTS:
        yield from globber(f"*{ext}")


def main() -> None:
    ap = argparse.ArgumentParser(description="Gather beats from configured sources into beats\\.")
    ap.add_argument("--dry-run", action="store_true", help="List what would be copied; copy nothing.")
    ap.add_argument("--source", type=str, default=None, help="Only pull from this named source.")
    ap.add_argument("--limit", type=int, default=None, help="Copy at most N new beats.")
    ap.add_argument("--match", type=str, default=None,
                    help="Only pull beats whose name contains one of these (comma-separated). "
                         "e.g. --match \"army,hood legend,paul walker\"")
    args = ap.parse_args()

    cfg = load_config()
    BEATS_DIR.mkdir(parents=True, exist_ok=True)

    skip_rendered = bool(cfg.get("skip_already_rendered", True))
    have = existing_stems()
    done = rendered_stems() if skip_rendered else set()

    # Optional name filter — only pull beats matching one of these terms.
    match_terms = None
    if args.match:
        match_terms = [t.strip().lower() for t in args.match.split(",") if t.strip()]

    sources = [s for s in cfg.get("sources", []) if s.get("enabled", True)]
    if args.source:
        sources = [s for s in sources if s.get("name") == args.source]
        if not sources:
            print(f"[ERROR] no enabled source named '{args.source}'")
            sys.exit(1)

    print(f"\n{'-'*56}")
    print(f"  gather_beats.py {'(DRY RUN)' if args.dry_run else ''}")
    print(f"  {len(have)} beats already in beats\\, {len(done)} already rendered")
    print(f"{'-'*56}\n")

    copied = skipped = 0
    seen_this_run: set[str] = set()

    def limit_reached() -> bool:
        return args.limit is not None and copied >= args.limit

    for src in sources:
        if limit_reached():
            break
        folder = Path(src["path"])
        name = src.get("name", folder.name)
        if not folder.is_dir():
            print(f"[MISS] source '{name}' not found: {folder}")
            continue

        print(f"[SRC] {name}  ({folder})")
        for audio in iter_audio(folder, src.get("recurse", True)):
            stem = safe_stem(audio)
            # Name filter: skip anything that doesn't match a requested term.
            if match_terms is not None:
                hay = f"{audio.name.lower()} {stem}"
                if not any(term in hay for term in match_terms):
                    continue
            if stem in have or stem in seen_this_run:
                skipped += 1
                continue
            if skip_rendered and stem in done:
                skipped += 1
                continue

            if limit_reached():
                print(f"  [LIMIT] reached {args.limit} — stopping.")
                break

            dest = BEATS_DIR / (stem + audio.suffix.lower())
            if args.dry_run:
                print(f"  [WOULD COPY] {audio.name}  ->  beats\\{dest.name}")
            else:
                try:
                    shutil.copy2(audio, dest)
                    print(f"  [COPY] {audio.name}  ->  beats\\{dest.name}")
                except Exception as exc:
                    print(f"  [FAIL] {audio.name}: {exc}")
                    continue
            seen_this_run.add(stem)
            copied += 1

    print(f"\n{'-'*56}")
    verb = "would copy" if args.dry_run else "copied"
    print(f"[DONE] {verb} {copied} new beat(s)  |  {skipped} already present/rendered")
    print(f"{'-'*56}")


if __name__ == "__main__":
    main()
