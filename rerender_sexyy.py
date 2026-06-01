"""
Re-render all Sexyy Red beats that had flagged clips (promo_4/5/6, ftb_leather).
Only re-renders the full video + short. Skips thumbnail (still image, unaffected).
"""
import json, subprocess, hashlib, sys
from pathlib import Path

ROOT        = Path(__file__).resolve().parent
RENDERS_DIR = ROOT / "output" / "renders"
SHORTS_DIR  = ROOT / "output" / "renders" / "shorts"
BEATS_DIR   = ROOT / "beats"
IMAGES_DIR  = ROOT / "images"
SEXYY_DIR   = IMAGES_DIR / "Sexyy Red"
THUMBS_DIR  = ROOT / "output" / "thumbs"

FLAGGED = {"visual_ftb_leather.mp4","visual_promo_4.mp4","visual_promo_5.mp4","visual_promo_6.mp4"}

safe_clips = sorted([f for f in SEXYY_DIR.iterdir() if f.suffix == '.mp4'])

def resolve_clip(stem):
    idx = int(hashlib.md5(stem.encode()).hexdigest(), 16) % len(safe_clips)
    return safe_clips[idx]

# All Sexyy Red stems that had flagged clips
log = json.loads((ROOT / "uploads_log.json").read_text())

# Old clip list (10 clips before deletion)
old_clips = [
    "visual_counting_money.mp4","visual_ftb_leather.mp4","visual_money_greensuit.mp4",
    "visual_pink_haze.mp4","visual_promo_2.mp4","visual_promo_3.mp4",
    "visual_promo_4.mp4","visual_promo_5.mp4","visual_promo_6.mp4","visual_redhair_black.mp4"
]

needs_rerender = []
for stem, d in log.items():
    meta_path = ROOT / "metadata" / f"{stem}.json"
    if not meta_path.exists(): continue
    meta = json.loads(meta_path.read_text())
    artist = meta.get("seo_artist","").lower()
    if "sexyy" not in artist: continue
    idx_old = int(hashlib.md5(stem.encode()).hexdigest(), 16) % len(old_clips)
    if old_clips[idx_old] in FLAGGED:
        needs_rerender.append(stem)

print(f"Re-rendering {len(needs_rerender)} Sexyy Red beats with clean clips...")
print()

for i, stem in enumerate(needs_rerender, 1):
    clip = resolve_clip(stem)
    print(f"[{i}/{len(needs_rerender)}] {stem} → {clip.name}")

    # Find beat audio
    beat_path = None
    for ext in ('.mp3', '.wav'):
        p = BEATS_DIR / f"{stem}{ext}"
        if p.exists():
            beat_path = p
            break
    if not beat_path:
        print(f"  ⚠ No beat file found, skipping")
        continue

    out_mp4 = RENDERS_DIR / f"{stem}.mp4"
    out_short = SHORTS_DIR / f"{stem}_short.mp4"

    # Delete old renders
    out_mp4.unlink(missing_ok=True)
    out_short.unlink(missing_ok=True)

    # --- Re-render full video ---
    import subprocess as sp
    # Get audio duration
    dur_cmd = ["ffprobe","-v","quiet","-show_entries","format=duration",
                "-of","default=noprint_wrappers=1:nokey=1", str(beat_path)]
    dur = float(sp.check_output(dur_cmd).decode().strip())

    # Get clip orientation
    probe = sp.check_output(["ffprobe","-v","quiet","-select_streams","v:0",
        "-show_entries","stream=width,height","-of","json", str(clip)]).decode()
    info = json.loads(probe)["streams"][0]
    cw, ch = info["width"], info["height"]
    portrait = ch > cw

    if portrait:
        # Blurred background + centered overlay
        vf = (
            f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
            f"crop=1920:1080,boxblur=20:5[bg];"
            f"[0:v]scale=-2:1080[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2"
        )
    else:
        # Landscape: scale-fill crop
        vf = "scale=1920:1080:force_original_aspect_ratio=increase,crop=1920:1080"

    # Overlay spinning logo
    spin_path = ROOT / "brand" / "fy3_spin.mov"
    spin_overlay = ""
    if spin_path.exists():
        if portrait:
            spin_overlay = f";[v1][1:v]overlay=(W-w)/2:H-h-20[v2]"
            map_v = "[v2]"
            inputs_extra = ["-stream_loop","-1","-i",str(spin_path)]
        else:
            spin_overlay = f";[tmp][1:v]overlay=(W-w)/2:H-h-20[v2]"
            map_v = "[v2]"
            inputs_extra = ["-stream_loop","-1","-i",str(spin_path)]
    else:
        map_v = "[v1]" if portrait else "[tmp]"
        inputs_extra = []

    if portrait:
        full_vf = (
            f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
            f"crop=1920:1080,boxblur=20:5[bg];"
            f"[0:v]scale=-2:1080[fg];"
            f"[bg][fg]overlay=(W-w)/2:(H-h)/2[v1]"
            + spin_overlay
        )
    else:
        full_vf = (
            f"[0:v]scale=1920:1080:force_original_aspect_ratio=increase,"
            f"crop=1920:1080[tmp]"
            + spin_overlay
        )

    cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(clip),
        "-i", str(beat_path),
    ] + inputs_extra + [
        "-filter_complex", full_vf,
        "-map", map_v,
        "-map", "1:a",
        "-c:v", "libx264", "-preset", "slow", "-crf", "18",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(dur),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_mp4)
    ]
    result = sp.run(cmd, capture_output=True, text=True)
    if result.returncode != 0:
        print(f"  ✗ Full render FAILED: {result.stderr[-300:]}")
    else:
        print(f"  ✓ Full render done")

    # --- Re-render short (60s portrait) ---
    # Detect first beat drop for seek offset
    try:
        import numpy as np
        import librosa
        y, sr = librosa.load(str(beat_path), sr=None, mono=True)
        y_bass = librosa.effects.preemphasis(y, coef=-0.97)
        from scipy.signal import butter, filtfilt
        b, a = butter(4, [30/(sr/2), 150/(sr/2)], btype='band')
        bass = filtfilt(b, a, y)
        onsets = librosa.onset.onset_detect(y=bass, sr=sr, units='time', backtrack=True)
        drop_t = 0.0
        if len(onsets) > 3:
            for j in range(len(onsets)-2):
                if onsets[j+1]-onsets[j] < 1.0 and onsets[j+2]-onsets[j+1] < 1.0:
                    drop_t = float(onsets[j])
                    break
    except Exception:
        drop_t = 0.0

    short_dur = min(60.0, dur - drop_t)
    if short_dur < 15:
        drop_t = 0.0
        short_dur = min(60.0, dur)

    # Portrait output 1080x1920
    short_vf = (
        f"[0:v]scale=1080:1920:force_original_aspect_ratio=increase,"
        f"crop=1080:1920[tmp]"
    )
    if spin_path.exists():
        short_vf += f";[tmp][1:v]overlay=(W-w)/2:H-h-20[vout]"
        short_map = "[vout]"
        short_extra = ["-stream_loop","-1","-i",str(spin_path)]
    else:
        short_map = "[tmp]"
        short_extra = []

    short_cmd = [
        "ffmpeg", "-y",
        "-stream_loop", "-1", "-i", str(clip),
        "-ss", str(drop_t), "-i", str(beat_path),
    ] + short_extra + [
        "-filter_complex", short_vf,
        "-map", short_map,
        "-map", "1:a",
        "-c:v", "libx264", "-preset", "fast", "-crf", "22",
        "-c:a", "aac", "-b:a", "192k",
        "-t", str(short_dur),
        "-pix_fmt", "yuv420p",
        "-movflags", "+faststart",
        str(out_short)
    ]
    result2 = sp.run(short_cmd, capture_output=True, text=True)
    if result2.returncode != 0:
        print(f"  ✗ Short FAILED: {result2.stderr[-200:]}")
    else:
        sz = out_short.stat().st_size // (1024*1024)
        print(f"  ✓ Short done ({sz}MB, {short_dur:.0f}s from t={drop_t:.1f}s)")

    print()

print("All done!")
