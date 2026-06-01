#!/usr/bin/env python3
"""
audit_airbit_audio.py
---------------------
Detects beats on Airbit that are playing the wrong audio.

Strategy:
  1. Fetch all beats from Airbit API (name, alias, http URL)
  2. For each beat that has a matching local MP3 in beats/:
     - Download first 10 seconds of Airbit CDN audio
     - Download first 10 seconds of local MP3
     - Compare RMS energy profile (tempo, onset pattern)
     - Flag as MISMATCH if they don't match
  3. Print a report of mismatches

Usage:
    python audit_airbit_audio.py              # audit all matched beats
    python audit_airbit_audio.py --only army  # single beat
    python audit_airbit_audio.py --limit 20   # first N beats only
    python audit_airbit_audio.py --fast       # skip download, just match filenames

Requires: librosa, requests, numpy
"""
import argparse
import json
import re
import sys
import tempfile
import time
import urllib.request
from pathlib import Path

import numpy as np
import requests

ROOT       = Path(__file__).resolve().parent
BEATS_DIR  = ROOT / "beats"
META_DIR   = ROOT / "metadata"
AIRBIT_USER_ID = 455547
AIRBIT_BASE    = "https://api.airbit.com"
STORE_BASE     = "https://leekthatsfy3.infinity.airbit.com"
PAGE_SIZE      = 50

HEADERS = {
    "User-Agent": "Mozilla/5.0",
    "Accept": "application/json",
    "Referer": f"{STORE_BASE}/",
    "Origin": STORE_BASE,
}


def safe_stem(name: str) -> str:
    s = name.lower()
    s = re.sub(r"[^\w\s]", "", s)
    s = re.sub(r"\s+", "_", s.strip())
    return s


def fetch_all_beats() -> list[dict]:
    beats, page = [], 1
    while True:
        r = requests.get(
            f"{AIRBIT_BASE}/users/{AIRBIT_USER_ID}/beats",
            params={"limit": PAGE_SIZE, "page": page, "expand": "tags"},
            headers=HEADERS, timeout=20,
        )
        r.raise_for_status()
        data  = r.json()
        items = data.get("items", [])
        beats.extend(items)
        print(f"  Fetched page {page}: {len(items)} beats ({len(beats)} total)")
        if len(items) < PAGE_SIZE:
            break
        page += 1
        time.sleep(0.3)
    return beats


def build_stem_map(beats: list[dict]) -> dict[str, dict]:
    """Return {stem -> beat} for all name variants."""
    m = {}
    for b in beats:
        full_stem = safe_stem(b["name"])
        if full_stem not in m:
            m[full_stem] = b
        short_name = re.sub(r'^.*?type beat\s*-\s*"?', "", b["name"], flags=re.IGNORECASE).strip('" ')
        if short_name and short_name.lower() != b["name"].lower():
            short_stem = safe_stem(short_name)
            if short_stem and short_stem not in m:
                m[short_stem] = b
    return m


def fingerprint(audio_path: Path, duration: float = 10.0) -> np.ndarray | None:
    """Extract a simple tempo+onset fingerprint from the first `duration` seconds."""
    try:
        import librosa
        y, sr = librosa.load(str(audio_path), duration=duration, sr=22050, mono=True)
        # Compute onset strength envelope (captures drum pattern / energy shape)
        onset_env = librosa.onset.onset_strength(y=y, sr=sr)
        # Normalize to unit vector
        norm = np.linalg.norm(onset_env)
        if norm > 0:
            onset_env /= norm
        return onset_env
    except Exception as e:
        print(f"  ⚠ fingerprint error: {e}")
        return None


def compare(fp1: np.ndarray, fp2: np.ndarray) -> float:
    """Cosine similarity between two fingerprints (1.0 = identical)."""
    min_len = min(len(fp1), len(fp2))
    if min_len == 0:
        return 0.0
    a, b = fp1[:min_len], fp2[:min_len]
    dot  = np.dot(a, b)
    norm = np.linalg.norm(a) * np.linalg.norm(b)
    return float(dot / norm) if norm > 0 else 0.0


def download_sample(url: str, dest: Path, seconds: int = 12) -> bool:
    """Download first N seconds of audio via ffmpeg from URL."""
    import subprocess
    try:
        result = subprocess.run(
            ["ffmpeg", "-y", "-ss", "0", "-t", str(seconds),
             "-i", url, "-q:a", "9", "-acodec", "libmp3lame", str(dest)],
            capture_output=True, timeout=30,
        )
        return dest.exists() and dest.stat().st_size > 0
    except Exception as e:
        print(f"  ⚠ download error: {e}")
        return False


def main():
    parser = argparse.ArgumentParser()
    parser.add_argument("--only",  help="Comma-separated stems to audit")
    parser.add_argument("--limit", type=int, default=0, help="Max beats to audit")
    parser.add_argument("--fast",  action="store_true", help="Filename-only check (no audio download)")
    parser.add_argument("--threshold", type=float, default=0.70, help="Similarity threshold (default 0.70)")
    args = parser.parse_args()

    only_set = {s.strip() for s in args.only.split(",")} if args.only else None

    print("=" * 60)
    print("  Airbit Audio Audit")
    print("=" * 60)

    print("\n[1/3] Fetching beats from Airbit …")
    beats    = fetch_all_beats()
    stem_map = build_stem_map(beats)
    print(f"  ✓ {len(beats)} beats on Airbit, {len(stem_map)} stems mapped")

    print("\n[2/3] Matching local beats to Airbit listings …")
    work: list[tuple[str, Path, dict]] = []  # (stem, local_mp3, airbit_beat)
    for mp3 in sorted(BEATS_DIR.glob("*.mp3")):
        stem = mp3.stem
        if only_set and stem not in only_set:
            continue
        ab_beat = stem_map.get(stem)
        if not ab_beat:
            continue
        work.append((stem, mp3, ab_beat))
    for wav in sorted(BEATS_DIR.glob("*.wav")):
        stem = wav.stem
        if only_set and stem not in only_set:
            continue
        if any(s == stem for s, _, _ in work):
            continue
        ab_beat = stem_map.get(stem)
        if not ab_beat:
            continue
        work.append((stem, wav, ab_beat))

    if args.limit:
        work = work[: args.limit]

    print(f"  ✓ {len(work)} local beats matched to Airbit listings")

    if args.fast:
        print("\n[FAST MODE] Checking Airbit filenames vs local stems …")
        mismatches = []
        for stem, local_path, ab_beat in work:
            cdn_filename = ab_beat.get("filename", "")
            ab_name      = ab_beat.get("name", "")
            # The CDN filename encodes the beat name — check if stem words appear
            fn_lower = cdn_filename.lower()
            stem_words = stem.replace("_", "-").lower()
            if stem_words not in fn_lower and safe_stem(ab_name) != stem:
                mismatches.append((stem, ab_beat, cdn_filename))
                print(f"  ⚠ SUSPECT  {stem:40s} → Airbit: '{ab_name}' | file: {cdn_filename}")
        print(f"\nSuspect listings: {len(mismatches)}")
        return

    print("\n[3/3] Comparing audio fingerprints …")
    ok = mismatch = error = 0
    mismatch_list = []

    with tempfile.TemporaryDirectory() as tmpdir:
        tmp = Path(tmpdir)
        for i, (stem, local_path, ab_beat) in enumerate(work, 1):
            cdn_url = ab_beat.get("http", "")
            ab_name = ab_beat.get("name", "")
            if not cdn_url:
                print(f"  [{i}/{len(work)}] {stem}: no CDN URL — skip")
                error += 1
                continue

            print(f"  [{i}/{len(work)}] {stem} …", end="", flush=True)

            # Download CDN sample
            cdn_sample = tmp / f"{stem}_cdn.mp3"
            if not download_sample(cdn_url, cdn_sample):
                print(f" ⚠ CDN download failed")
                error += 1
                continue

            # Fingerprint both
            fp_local = fingerprint(local_path)
            fp_cdn   = fingerprint(cdn_sample)

            if fp_local is None or fp_cdn is None:
                print(f" ⚠ fingerprint failed")
                error += 1
                continue

            sim = compare(fp_local, fp_cdn)

            if sim >= args.threshold:
                print(f" ✓  {sim:.3f}")
                ok += 1
            else:
                print(f" ❌ MISMATCH {sim:.3f}  (Airbit: '{ab_name}')")
                mismatch += 1
                mismatch_list.append({
                    "stem":       stem,
                    "local_file": str(local_path.name),
                    "airbit_name": ab_name,
                    "airbit_alias": ab_beat.get("alias"),
                    "airbit_file": ab_beat.get("filename"),
                    "cdn_url":    cdn_url,
                    "similarity": round(sim, 4),
                })

    print(f"\n{'='*60}")
    print(f"  Results: ✓ {ok} match  ❌ {mismatch} mismatch  ⚠ {error} error")
    print(f"{'='*60}")
    if mismatch_list:
        print("\nMISMATCHED BEATS:")
        for m in mismatch_list:
            print(f"  {m['stem']:40s} → Airbit listing: '{m['airbit_name']}'")
            print(f"    Airbit file: {m['airbit_file']}")
            print(f"    Similarity:  {m['similarity']}")
        out = ROOT / "airbit_mismatches.json"
        out.write_text(json.dumps(mismatch_list, indent=2))
        print(f"\nSaved to {out}")
    else:
        print("No mismatches found.")


if __name__ == "__main__":
    main()
