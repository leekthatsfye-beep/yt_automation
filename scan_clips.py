"""
scan_clips.py — Pre-upload NSFW/safety scanner for video clips.

Extracts frames from every MP4 in a folder, runs NudeNet on each frame,
scores the clip, and flags/quarantines anything above threshold.

Usage:
    python scan_clips.py                          # scans all images/ subfolders
    python scan_clips.py "images/Sexyy Red/"      # scan specific folder
    python scan_clips.py --quarantine             # auto-move flagged clips

Outputs a report and optionally moves risky clips to flagged/ subfolder.
"""

import sys, json, shutil, subprocess, tempfile
from pathlib import Path
from collections import defaultdict

ROOT = Path(__file__).resolve().parent

# ── Labels NudeNet considers RISKY for YouTube ──────────────────────────────
# YouTube age-restricts: nudity, sexual content, explicit dancing
RISKY_LABELS = {
    "FEMALE_BREAST_EXPOSED",
    "FEMALE_GENITALIA_EXPOSED",
    "MALE_GENITALIA_EXPOSED",
    "ANUS_EXPOSED",
    "BUTTOCKS_EXPOSED",
    "FEMALE_BREAST_COVERED",      # borderline — bikini tops etc
    "BELLY_EXPOSED",              # midriff (usually fine, low weight)
}

# These alone won't get you age-restricted
SAFE_LABELS = {
    "FACE_FEMALE", "FACE_MALE",
    "BELLY_COVERED", "FEET_COVERED", "FEET_EXPOSED",
    "ARMPITS_COVERED", "ARMPITS_EXPOSED",
    "MALE_BREAST_EXPOSED",
}

# Score weights — higher = more dangerous
WEIGHTS = {
    "FEMALE_BREAST_EXPOSED":    1.0,
    "FEMALE_GENITALIA_EXPOSED": 1.0,
    "MALE_GENITALIA_EXPOSED":   1.0,
    "ANUS_EXPOSED":             1.0,
    "BUTTOCKS_EXPOSED":         0.8,
    "FEMALE_BREAST_COVERED":    0.3,
    "BELLY_EXPOSED":            0.1,
}

# Clip is FLAGGED if avg risk score across frames > this
FLAG_THRESHOLD   = 0.15   # conservative — errs on side of caution
WARN_THRESHOLD   = 0.05   # worth a manual look

# Sample 1 frame every N seconds
FRAME_INTERVAL_S = 3


def extract_frames(clip_path: Path, interval: int = FRAME_INTERVAL_S) -> list[Path]:
    """Extract frames from video at regular intervals into a temp dir."""
    tmpdir = Path(tempfile.mkdtemp())
    cmd = [
        "ffmpeg", "-i", str(clip_path),
        "-vf", f"fps=1/{interval}",
        "-q:v", "2",
        str(tmpdir / "frame_%04d.jpg"),
        "-hide_banner", "-loglevel", "error"
    ]
    subprocess.run(cmd, check=True)
    return sorted(tmpdir.glob("*.jpg"))


def score_frame(detector, frame_path: Path) -> tuple[float, list[str]]:
    """Return (risk_score, [detected_labels]) for a single frame."""
    detections = detector.detect(str(frame_path))
    risk = 0.0
    labels = []
    for d in detections:
        label = d.get("class", "")
        conf  = d.get("score", 0.0)
        labels.append(f"{label}({conf:.2f})")
        w = WEIGHTS.get(label, 0.0)
        risk += w * conf
    return risk, labels


def scan_clip(detector, clip_path: Path) -> dict:
    """Scan a single clip. Returns result dict."""
    print(f"  Scanning {clip_path.name}...", end=" ", flush=True)

    frames = extract_frames(clip_path)
    if not frames:
        print("no frames extracted")
        return {"clip": clip_path.name, "verdict": "ERROR", "score": 0, "frames": 0}

    frame_scores = []
    worst_frame  = None
    worst_score  = 0.0
    worst_labels = []

    for f in frames:
        score, labels = score_frame(detector, f)
        frame_scores.append(score)
        if score > worst_score:
            worst_score  = score
            worst_frame  = f.name
            worst_labels = labels
        f.unlink()  # cleanup
    f.parent.rmdir() if f.parent.exists() and not list(f.parent.iterdir()) else None

    avg_score = sum(frame_scores) / len(frame_scores) if frame_scores else 0
    max_score = max(frame_scores) if frame_scores else 0

    if avg_score >= FLAG_THRESHOLD or max_score >= 0.6:
        verdict = "🚨 FLAG"
    elif avg_score >= WARN_THRESHOLD:
        verdict = "⚠️  WARN"
    else:
        verdict = "✅ SAFE"

    print(f"{verdict}  avg={avg_score:.3f}  max={max_score:.3f}  ({len(frames)} frames)")

    if worst_labels:
        print(f"    worst frame: {worst_frame} → {', '.join(worst_labels[:5])}")

    return {
        "clip":         clip_path.name,
        "verdict":      verdict.strip(),
        "avg_score":    round(avg_score, 4),
        "max_score":    round(max_score, 4),
        "frames":       len(frames),
        "worst_frame":  worst_frame,
        "worst_labels": worst_labels,
    }


def scan_folder(folder: Path, quarantine: bool = False) -> list[dict]:
    from nudenet import NudeDetector
    detector = NudeDetector()

    clips = sorted(folder.glob("*.mp4"))
    if not clips:
        print(f"No MP4s found in {folder}")
        return []

    print(f"\n{'='*60}")
    print(f"Scanning {len(clips)} clips in {folder.name}/")
    print(f"{'='*60}\n")

    results = []
    flagged = []

    for clip in clips:
        result = scan_clip(detector, clip)
        results.append(result)
        if result["verdict"].startswith("🚨"):
            flagged.append(clip)

    # Summary
    print(f"\n{'='*60}")
    print(f"RESULTS: {folder.name}/")
    print(f"{'='*60}")
    for r in results:
        print(f"  {r['verdict']:<12} {r['clip']:<40} avg={r['avg_score']:.3f}")

    if flagged:
        print(f"\n🚨 {len(flagged)} clips flagged:")
        for c in flagged:
            print(f"  → {c.name}")

        if quarantine:
            q_dir = folder / "flagged"
            q_dir.mkdir(exist_ok=True)
            for c in flagged:
                dest = q_dir / c.name
                shutil.move(str(c), str(dest))
                print(f"  Moved to flagged/: {c.name}")
    else:
        print("\n✅ All clips safe!")

    return results


def main():
    import argparse
    parser = argparse.ArgumentParser(description="Scan video clips for NSFW content")
    parser.add_argument("folder", nargs="?", default=None,
                        help="Folder to scan (default: all artist subfolders in images/)")
    parser.add_argument("--quarantine", action="store_true",
                        help="Auto-move flagged clips to flagged/ subfolder")
    parser.add_argument("--report", default=None,
                        help="Save JSON report to this path")
    args = parser.parse_args()

    all_results = {}

    if args.folder:
        folder = Path(args.folder)
        results = scan_folder(folder, quarantine=args.quarantine)
        all_results[str(folder)] = results
    else:
        # Scan all artist subfolders in images/
        images_dir = ROOT / "images"
        subfolders = [d for d in images_dir.iterdir() if d.is_dir() and list(d.glob("*.mp4"))]
        if not subfolders:
            print("No artist clip folders found in images/")
            return
        for folder in sorted(subfolders):
            results = scan_folder(folder, quarantine=args.quarantine)
            all_results[str(folder)] = results

    if args.report:
        Path(args.report).write_text(json.dumps(all_results, indent=2))
        print(f"\nReport saved to {args.report}")

    # Final verdict across everything
    total   = sum(len(v) for v in all_results.values())
    flagged = sum(1 for v in all_results.values() for r in v if r["verdict"].startswith("🚨"))
    warned  = sum(1 for v in all_results.values() for r in v if r["verdict"].startswith("⚠️"))
    print(f"\n{'='*60}")
    print(f"OVERALL: {total} clips | 🚨 {flagged} flagged | ⚠️  {warned} warnings")
    print(f"{'='*60}")


if __name__ == "__main__":
    main()
