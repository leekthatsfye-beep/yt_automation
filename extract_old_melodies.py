#!/usr/bin/env python3
"""
Download old beats from YouTube and extract stems + MIDI using Demucs.

Phase 1: Lil Double 0 era (Dec 2021 - Jun 2022)
Future:  --era 2020 for Foogiano/Ola Runt/etc.

Usage:
    python extract_old_melodies.py --dry-run            # preview
    python extract_old_melodies.py --download-only      # just download
    python extract_old_melodies.py --separate-only      # just Demucs
    python extract_old_melodies.py --only "GREEN_LIGHT" # specific beats
    python extract_old_melodies.py --no-midi            # skip MIDI
    python extract_old_melodies.py --format wav         # WAV instead of FLAC
    python extract_old_melodies.py --era double0        # Lil Double 0 (default)
    python extract_old_melodies.py --era 2020           # 2020 era (future)
"""

import argparse
import json
import os
import re
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parent
sys.path.insert(0, str(ROOT))

VENV_BIN = ROOT / ".venv" / "bin"
DEMUCS_VENV_BIN = ROOT / ".venv_demucs" / "bin"
DEMUCS_PYTHON = DEMUCS_VENV_BIN / "python3.11"
YT_DLP = VENV_BIN / "yt-dlp"

OUTPUT_BASE = Path.home() / "Documents" / "old_beat_stems"
DOWNLOADS_DIR = OUTPUT_BASE / "downloads"
STEMS_DIR = OUTPUT_BASE / "stems"

UPLOADS_LOG = ROOT / "uploads_log.json"


def p(msg):
    print(msg, flush=True)


def sanitize_name(title: str) -> str:
    """Convert YouTube title to a clean folder name."""
    # Remove common prefixes
    t = title
    for prefix in ["*Free*", "*FREE*", "*FYE*", "*fye*", "(FREE)", "(Free)", "(free)"]:
        t = t.replace(prefix, "")

    # Extract the beat name from common patterns
    # Pattern: @lildouble00 Type Beat "NAME" or Type Beat - NAME
    m = re.search(r'["\u201c]([^"\u201d]+)["\u201d]', t)
    if m:
        beat_name = m.group(1).strip()
    else:
        m = re.search(r'(?:Type Beat|type beat)\s*[-–—]\s*(.+?)(?:\s*[@!]|$)', t)
        if m:
            beat_name = m.group(1).strip().rstrip("! ")
        else:
            beat_name = t.strip()

    # Clean up
    beat_name = re.sub(r'@\S+', '', beat_name)  # remove @mentions
    beat_name = re.sub(r'[^\w\s-]', '', beat_name)  # remove special chars
    beat_name = re.sub(r'\s+', '_', beat_name.strip())  # spaces to underscores
    beat_name = beat_name.strip('_')

    if not beat_name:
        beat_name = re.sub(r'[^\w]', '_', title[:40]).strip('_')

    return beat_name


def identify_beats(era: str) -> list:
    """Fetch channel videos and filter to the requested era."""
    from youtube_auth import get_youtube_service

    yt = get_youtube_service()
    ch = yt.channels().list(part="contentDetails", mine=True).execute()
    uploads_id = ch["items"][0]["contentDetails"]["relatedPlaylists"]["uploads"]

    # Paginate all videos
    all_items = []
    next_token = None
    while True:
        pl = yt.playlistItems().list(
            part="snippet,contentDetails",
            playlistId=uploads_id,
            maxResults=50,
            pageToken=next_token,
        ).execute()
        all_items.extend(pl["items"])
        next_token = pl.get("nextPageToken")
        if not next_token:
            break

    # Deduplicate
    seen = set()
    unique = []
    for v in all_items:
        vid = v["contentDetails"]["videoId"]
        if vid not in seen:
            seen.add(vid)
            unique.append(v)

    # Get stats
    video_ids = [v["contentDetails"]["videoId"] for v in unique]
    all_stats = {}
    for i in range(0, len(video_ids), 50):
        batch = video_ids[i : i + 50]
        r = yt.videos().list(
            part="statistics,snippet,status", id=",".join(batch)
        ).execute()
        for item in r["items"]:
            all_stats[item["id"]] = item

    # Load uploads log to skip local beats
    logged_ids = set()
    if UPLOADS_LOG.exists():
        with open(UPLOADS_LOG) as f:
            ulog = json.load(f)
        logged_ids = set(v.get("videoId", "") for v in ulog.values())

    # Filter by era
    beats = []
    for v in unique:
        vid = v["contentDetails"]["videoId"]
        if vid not in all_stats:
            continue
        if vid in logged_ids:
            continue

        s = all_stats[vid]
        title = s["snippet"]["title"]
        title_lower = title.lower()
        views = int(s["statistics"].get("viewCount", 0))
        pub = s["snippet"]["publishedAt"][:10]
        privacy = s["status"].get("privacyStatus", "public")

        # Skip snippets and non-beat content
        if "snippet" in title_lower and "type beat" not in title_lower:
            continue

        matched = False

        if era == "double0":
            # Lil Double 0 era
            if any(
                kw in title_lower
                for kw in ["lildouble00", "lildouble", "lil double 0", "lil double"]
            ):
                matched = True

        elif era == "2020":
            # 2020 era (future expansion)
            if pub.startswith("2020") and any(
                kw in title_lower
                for kw in ["type beat", "(free)", "instrumental"]
            ):
                matched = True

        elif era == "all":
            # Everything pre-2025 that looks like a beat
            if pub < "2025-01-01" and any(
                kw in title_lower
                for kw in [
                    "type beat", "(free)", "*free*", "*fye*",
                    "instrumental", "lildouble", "lil double",
                ]
            ):
                if not any(
                    skip in title_lower
                    for skip in [
                        "kook", "kooking", "making songz", "reaction",
                        "prank", "interview", "bodycam", "terrified",
                        "interrogat", "hellcat", "beef patty",
                    ]
                ):
                    matched = True

        if matched:
            name = sanitize_name(title)
            beats.append({
                "id": vid,
                "title": title,
                "name": name,
                "views": views,
                "pub": pub,
                "privacy": privacy,
                "url": f"https://www.youtube.com/watch?v={vid}",
            })

    # Sort by date
    beats.sort(key=lambda x: x["pub"])
    return beats


def download_audio(beat: dict) -> Path:
    """Download audio from YouTube using yt-dlp."""
    out_dir = DOWNLOADS_DIR
    out_dir.mkdir(parents=True, exist_ok=True)

    # Use clean filename based on beat name
    clean_name = beat["name"]
    out_path = out_dir / f"{clean_name}.wav"

    # Check if already downloaded (clean name or any file in old subfolder)
    if out_path.exists():
        return out_path

    # Also check old subfolder structure
    old_dir = out_dir / clean_name
    if old_dir.is_dir():
        existing = list(old_dir.glob("*.wav")) + list(old_dir.glob("*.mp3"))
        if existing:
            # Move to clean name
            import shutil
            shutil.copy2(existing[0], out_path)
            return out_path

    out_template = str(out_dir / f"{clean_name}.%(ext)s")
    cmd = [
        str(YT_DLP),
        "-x",
        "--audio-format", "wav",
        "--audio-quality", "0",
        "-o", out_template,
        "--no-playlist",
        beat["url"],
    ]

    result = subprocess.run(cmd, capture_output=True, text=True, timeout=120)
    if result.returncode != 0:
        raise RuntimeError(f"yt-dlp failed: {result.stderr[:200]}")

    if not out_path.exists():
        # yt-dlp may have used a slightly different name
        candidates = list(out_dir.glob(f"{clean_name}*.*"))
        if candidates:
            candidates[0].rename(out_path)
        else:
            raise RuntimeError(f"No audio file found after download")

    return out_path


def separate_stems(audio_path: Path, beat_name: str, fmt: str = "flac") -> Path:
    """Run Demucs on downloaded audio to separate stems."""
    stems_dir = STEMS_DIR / beat_name
    check_file = stems_dir / f"other.{fmt}"

    if check_file.exists():
        p(f"    [SKIP] stems already exist")
        return stems_dir

    stems_dir.mkdir(parents=True, exist_ok=True)

    # Write a small separation script that the demucs venv runs
    sep_script = f'''
import sys
import torch
import numpy as np
import soundfile as sf
from pathlib import Path
from demucs.pretrained import get_model
from demucs.apply import apply_model

audio_path = Path("{audio_path}")
stems_dir = Path("{stems_dir}")
fmt = "{fmt}"

device = "mps" if torch.backends.mps.is_available() else "cpu"
print(f"  Device: {{device}}", flush=True)

print("  Loading htdemucs_ft model...", flush=True)
model = get_model("htdemucs_ft")
model.to(device)
model.eval()

print(f"  Loading audio: {{audio_path.name}}", flush=True)
# Use soundfile to load (avoids torchaudio/torchcodec issues)
data, sr = sf.read(str(audio_path), dtype="float32")

# data is (samples, channels) — transpose to (channels, samples)
if data.ndim == 1:
    wav = torch.from_numpy(data).unsqueeze(0).repeat(2, 1)
else:
    wav = torch.from_numpy(data.T)

# Resample if needed
if sr != model.samplerate:
    import torchaudio
    wav = torchaudio.functional.resample(wav, sr, model.samplerate)
    sr = model.samplerate

# Ensure stereo
if wav.shape[0] == 1:
    wav = wav.repeat(2, 1)
elif wav.shape[0] > 2:
    wav = wav[:2]

wav = wav.unsqueeze(0).to(device)

print("  Running Demucs separation (shifts=2, overlap=0.25)...", flush=True)
with torch.no_grad():
    sources = apply_model(model, wav, device=device, shifts=2, overlap=0.25)

# Sources order: drums, bass, other, vocals
names = ["drums", "bass", "other", "vocals"]
for i, name in enumerate(names):
    stem = sources[0, i].cpu()
    out_path = stems_dir / f"{{name}}.{{fmt}}"
    sf.write(str(out_path), stem.numpy().T, sr, format="FLAC" if fmt == "flac" else "WAV")
    print(f"    ✅ {{name}}.{{fmt}}", flush=True)

print("  Stems complete ✓", flush=True)
'''

    result = subprocess.run(
        [str(DEMUCS_PYTHON), "-c", sep_script],
        capture_output=True, text=True, timeout=1800,  # 30 min per beat
    )

    if result.stdout:
        for line in result.stdout.strip().split("\n"):
            p(line)

    if result.returncode != 0:
        p(f"    ❌ Demucs failed: {result.stderr[:300]}")
        raise RuntimeError(f"Demucs failed for {beat_name}")

    return stems_dir


def export_midi(stems_dir: Path, beat_name: str):
    """Run basic-pitch on ALL stems to generate MIDI for every part."""
    # Map stem files to their MIDI output names
    stem_midi_map = {
        "other": "melody",      # melody/synths/keys
        "drums": "drums",       # drum pattern
        "bass": "bass",         # 808s/bass line
        "vocals": "vocals",     # vocal chops/tags
    }

    for stem_name, midi_name in stem_midi_map.items():
        stem_file = None
        for ext in ["flac", "wav"]:
            candidate = stems_dir / f"{stem_name}.{ext}"
            if candidate.exists():
                stem_file = candidate
                break

        if not stem_file:
            continue

        midi_path = stems_dir / f"{midi_name}.mid"
        if midi_path.exists():
            p(f"    [SKIP] {midi_name}.mid already exists")
            continue

        midi_script = f'''
import warnings
warnings.filterwarnings("ignore")
import os
os.environ["TF_CPP_MIN_LOG_LEVEL"] = "3"

from basic_pitch.inference import predict_and_save, Model
from basic_pitch import ICASSP_2022_MODEL_PATH
from pathlib import Path

predict_and_save(
    [Path("{stem_file}")],
    Path("{stems_dir}"),
    save_midi=True,
    sonify_midi=False,
    save_model_outputs=False,
    save_notes=False,
    model_or_model_path=ICASSP_2022_MODEL_PATH,
    midi_tempo=120.0,
)

# Rename output to {midi_name}.mid
import glob
midi_files = glob.glob(str(Path("{stems_dir}") / "{stem_name}_basic_pitch.mid"))
if midi_files:
    Path(midi_files[0]).rename(Path("{stems_dir}") / "{midi_name}.mid")
    print("    ✅ {midi_name}.mid", flush=True)
else:
    midi_files = glob.glob(str(Path("{stems_dir}") / "*.mid"))
    # Find any new .mid that isn't already named
    existing = {{"{midi_name}.mid"}}
    for f in glob.glob(str(Path("{stems_dir}") / "*.mid")):
        fname = Path(f).name
        if fname not in existing and "_basic_pitch" in fname:
            Path(f).rename(Path("{stems_dir}") / "{midi_name}.mid")
            print("    ✅ {midi_name}.mid (renamed)", flush=True)
            break
    else:
        print("    ⚠️ No MIDI generated for {midi_name}", flush=True)
'''

        result = subprocess.run(
            [str(DEMUCS_PYTHON), "-c", midi_script],
            capture_output=True, text=True, timeout=300,
        )

        if result.stdout:
            for line in result.stdout.strip().split("\n"):
                if line.strip().startswith("✅") or line.strip().startswith("⚠️") or line.strip().startswith("[SKIP]"):
                    p(line)

        if result.returncode != 0:
            p(f"    ⚠️ MIDI export failed for {midi_name}: {result.stderr[:200]}")


def main():
    parser = argparse.ArgumentParser(
        description="Download old beats from YouTube and extract stems + MIDI"
    )
    parser.add_argument("--dry-run", action="store_true",
                        help="Preview without downloading or processing")
    parser.add_argument("--download-only", action="store_true",
                        help="Only download audio, skip Demucs and MIDI")
    parser.add_argument("--separate-only", action="store_true",
                        help="Only run Demucs on already-downloaded audio")
    parser.add_argument("--no-midi", action="store_true",
                        help="Skip MIDI export")
    parser.add_argument("--era", default="double0",
                        choices=["double0", "2020", "all"],
                        help="Which era to process (default: double0)")
    parser.add_argument("--only", type=str, default=None,
                        help="Comma-separated beat names to process")
    parser.add_argument("--format", default="flac", choices=["flac", "wav"],
                        help="Stem output format (default: flac)")
    args = parser.parse_args()

    # Create output dirs
    DOWNLOADS_DIR.mkdir(parents=True, exist_ok=True)
    STEMS_DIR.mkdir(parents=True, exist_ok=True)

    p(f"\n{'='*60}")
    p(f"  Old Beat Melody Extraction — {args.era.upper()} era")
    p(f"{'='*60}\n")

    # Identify beats
    p("Scanning YouTube channel...")
    beats = identify_beats(args.era)

    # Filter by --only
    if args.only:
        only_names = set(n.strip().upper() for n in args.only.split(","))
        beats = [b for b in beats if b["name"].upper() in only_names
                 or any(n in b["name"].upper() for n in only_names)]

    p(f"Found {len(beats)} beats to process\n")

    if not beats:
        p("No beats found matching criteria.")
        return

    # Display list
    p(f"{'#':>3} {'Beat Name':<35} {'Views':>7} {'Date':>12} {'Title'}")
    p("-" * 100)
    for i, b in enumerate(beats, 1):
        p(f"{i:>3} {b['name']:<35} {b['views']:>7} {b['pub']:>12} {b['title'][:45]}")

    if args.dry_run:
        p(f"\n{'='*60}")
        p(f"  DRY RUN — {len(beats)} beats found")
        p(f"  Estimated download: ~{len(beats) * 5}MB")
        p(f"  Estimated stems: ~{len(beats) * 70}MB ({args.format.upper()})")
        p(f"  Output: {OUTPUT_BASE}")
        p(f"{'='*60}")
        return

    # Process each beat
    success = 0
    failed = 0

    for i, beat in enumerate(beats, 1):
        p(f"\n[{i}/{len(beats)}] {beat['name']} ({beat['views']} views)")

        try:
            # Step 1: Download
            if not args.separate_only:
                p(f"  📥 Downloading...")
                audio_path = download_audio(beat)
                p(f"    ✅ {audio_path.name}")
            else:
                # Find existing download (flat file or old subfolder)
                flat = DOWNLOADS_DIR / f"{beat['name']}.wav"
                if flat.exists():
                    audio_path = flat
                else:
                    dl_dir = DOWNLOADS_DIR / beat["name"]
                    existing = list(dl_dir.glob("*.wav")) + list(dl_dir.glob("*.mp3")) if dl_dir.is_dir() else []
                    if not existing:
                        p(f"    ⚠️ No downloaded audio found, skipping")
                        failed += 1
                        continue
                    audio_path = existing[0]

            if args.download_only:
                success += 1
                continue

            # Step 2: Separate stems
            p(f"  🎵 Separating stems...")
            stems_out = separate_stems(audio_path, beat["name"], args.format)

            # Step 3: MIDI
            if not args.no_midi:
                p(f"  🎹 Exporting MIDI...")
                export_midi(stems_out, beat["name"])

            success += 1

        except KeyboardInterrupt:
            p(f"\n⚠️ Interrupted! Progress saved (idempotent).")
            break
        except Exception as e:
            p(f"  ❌ Failed: {e}")
            failed += 1

    # Summary
    p(f"\n{'='*60}")
    p(f"  Done: {success} processed, {failed} failed")
    p(f"  Output: {OUTPUT_BASE}")
    p(f"{'='*60}")


if __name__ == "__main__":
    main()
