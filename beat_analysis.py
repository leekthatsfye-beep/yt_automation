#!/usr/bin/env python3
"""
beat_analysis.py — accurate BPM + musical-key detector (numpy-only, no librosa).

Why this exists:
    librosa depends on numba, which has no Python 3.14 wheel, so the old
    render_lit analyzer silently fell back to "120 BPM / C Minor". This module
    needs only ffmpeg (already installed) to decode audio and numpy (already
    installed) to analyze it — so it runs anywhere the render pipeline runs.

Method:
    BPM  : STFT magnitude -> spectral-flux onset envelope -> autocorrelation,
           peak picked in 60-200 BPM range, octave-folded toward ~130.
    KEY  : FFT chromagram (12 pitch classes) -> Krumhansl-Schmuckler major/minor
           profile correlation, best of 24 candidate keys.

CLI:
    python beat_analysis.py --only pandamonium      # analyze + write metadata
    python beat_analysis.py --only a,b,c            # several
    python beat_analysis.py                         # all beats/*.mp3,*.wav
    python beat_analysis.py --only pandamonium --print   # just print, no write
    python beat_analysis.py --force                 # re-analyze even if metadata has bpm/key

Programmatic:
    from beat_analysis import analyze
    info = analyze(Path("beats/pandamonium.mp3"))   # {bpm, key, duration}
"""
from __future__ import annotations

import argparse
import json
import subprocess
import sys
from pathlib import Path

import numpy as np

ROOT = Path(__file__).resolve().parent
BEATS_DIR = ROOT / "beats"
META_DIR = ROOT / "metadata"

NOTES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]
# Krumhansl-Schmuckler key profiles
KS_MAJOR = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09, 2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
KS_MINOR = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53, 2.54, 4.75, 3.98, 2.69, 3.34, 3.17])


def load_audio(path: Path, sr: int = 22050) -> tuple[np.ndarray, int]:
    """Decode any audio file to mono float32 at `sr` via ffmpeg pipe."""
    cmd = [
        "ffmpeg", "-v", "quiet", "-i", str(path),
        "-ac", "1", "-ar", str(sr), "-f", "f32le", "-",
    ]
    proc = subprocess.run(cmd, capture_output=True)
    if proc.returncode != 0 or not proc.stdout:
        raise RuntimeError(f"ffmpeg failed to decode {path.name}")
    y = np.frombuffer(proc.stdout, dtype=np.float32).astype(np.float64)
    # peak-normalize for stable analysis
    peak = np.max(np.abs(y)) if y.size else 0.0
    if peak > 0:
        y = y / peak
    return y, sr


def _stft_mag(y: np.ndarray, n_fft: int, hop: int) -> np.ndarray:
    """Magnitude STFT -> (n_freq, n_frames). Vectorized framing, Hann window."""
    if len(y) < n_fft:
        y = np.pad(y, (0, n_fft - len(y)))
    win = np.hanning(n_fft)
    n_frames = 1 + (len(y) - n_fft) // hop
    idx = np.arange(n_fft)[None, :] + hop * np.arange(n_frames)[:, None]
    frames = y[idx] * win
    spec = np.fft.rfft(frames, axis=1)
    return np.abs(spec).T  # (freq, time)


def detect_bpm(y: np.ndarray, sr: int, hop: int = 512, n_fft: int = 2048) -> int:
    """Spectral-flux onset envelope -> autocorrelation tempo estimate."""
    S = _stft_mag(y, n_fft, hop)
    # spectral flux onset strength (positive energy increases per frame)
    flux = np.maximum(0.0, np.diff(S, axis=1)).sum(axis=0)
    if flux.size < 4:
        return 0
    flux = flux - flux.mean()
    # autocorrelation of onset envelope
    ac = np.correlate(flux, flux, mode="full")[flux.size - 1:]
    fps = sr / hop  # onset frames per second
    min_bpm, max_bpm = 60, 200
    min_lag = max(1, int(fps * 60 / max_bpm))
    max_lag = min(len(ac) - 1, int(fps * 60 / min_bpm))
    if max_lag <= min_lag:
        return 0
    seg = ac[min_lag:max_lag + 1]
    lag = min_lag + int(np.argmax(seg))
    bpm = 60.0 * fps / lag
    # octave-fold toward ~130 (typical type-beat range), same heuristic as old librosa path
    for mult in (2.0, 0.5, 3.0, 1.0 / 3.0):
        alt = bpm * mult
        if 60 <= alt <= 200 and abs(alt - 130) < abs(bpm - 130):
            bpm = alt
    return int(round(bpm))


def detect_key(y: np.ndarray, sr: int, n_fft: int = 4096, hop: int = 2048) -> str:
    """FFT chromagram -> Krumhansl-Schmuckler correlation over 24 keys."""
    S = _stft_mag(y, n_fft, hop)
    freqs = np.fft.rfftfreq(n_fft, 1.0 / sr)
    mag = S.mean(axis=1)  # average magnitude spectrum
    chroma = np.zeros(12)
    lo, hi = 55.0, 5000.0  # A1 .. ~D#8, the musically meaningful band
    for i, f in enumerate(freqs):
        if f < lo or f > hi:
            continue
        midi = 69 + 12 * np.log2(f / 440.0)
        pc = int(round(midi)) % 12
        chroma[pc] += mag[i]
    if chroma.sum() <= 0:
        return "C Minor"
    chroma = chroma / chroma.sum()
    best_score, best_key = -np.inf, "C Minor"
    for i in range(12):
        for prof, qual in ((KS_MAJOR, "Major"), (KS_MINOR, "Minor")):
            score = np.corrcoef(chroma, np.roll(prof, i))[0, 1]
            if score > best_score:
                best_score, best_key = score, f"{NOTES[i]} {qual}"
    return best_key


def analyze(path: Path, sr: int = 22050) -> dict:
    """Return {bpm, key, duration} for an audio file."""
    y, sr = load_audio(path, sr)
    duration = float(len(y)) / sr if sr else 0.0
    return {
        "bpm": detect_bpm(y, sr),
        "key": detect_key(y, sr),
        "duration": round(duration, 2),
    }


# ── metadata wiring ──────────────────────────────────────────────────────────

def write_to_metadata(stem: str, info: dict) -> None:
    """Merge bpm/key/duration into metadata/{stem}.json, preserving other fields."""
    META_DIR.mkdir(exist_ok=True)
    mp = META_DIR / f"{stem}.json"
    meta = {}
    if mp.exists():
        try:
            meta = json.loads(mp.read_text(encoding="utf-8"))
        except Exception:
            meta = {}
    meta["bpm"] = info["bpm"]
    meta["key"] = info["key"]
    meta["duration"] = info["duration"]
    mp.write_text(json.dumps(meta, indent=2, ensure_ascii=False), encoding="utf-8")


def ensure_bpm_key(stem: str, audio_path: Path | None = None, force: bool = False) -> dict:
    """Used by the pipeline: analyze + write bpm/key only if missing (or force)."""
    mp = META_DIR / f"{stem}.json"
    if mp.exists() and not force:
        try:
            m = json.loads(mp.read_text(encoding="utf-8"))
            if m.get("bpm") and m.get("key"):
                return {"bpm": m["bpm"], "key": m["key"], "duration": m.get("duration", 0)}
        except Exception:
            pass
    if audio_path is None:
        for ext in (".mp3", ".wav"):
            cand = BEATS_DIR / f"{stem}{ext}"
            if cand.exists():
                audio_path = cand
                break
    if audio_path is None or not audio_path.exists():
        raise FileNotFoundError(f"No audio for stem '{stem}' in {BEATS_DIR}")
    info = analyze(audio_path)
    write_to_metadata(stem, info)
    return info


def main():
    ap = argparse.ArgumentParser(description="Accurate BPM + key detector (numpy-only).")
    ap.add_argument("--only", type=str, default="", help="Comma-separated stems.")
    ap.add_argument("--force", action="store_true", help="Re-analyze even if bpm/key already set.")
    ap.add_argument("--print", dest="print_only", action="store_true", help="Print only, don't write metadata.")
    args = ap.parse_args()

    if args.only.strip():
        stems = [s.strip() for s in args.only.split(",") if s.strip()]
    else:
        stems = sorted({f.stem for f in BEATS_DIR.glob("*") if f.suffix.lower() in (".mp3", ".wav")})

    if not stems:
        print("No beats found in beats/.")
        sys.exit(0)

    for stem in stems:
        audio = None
        for ext in (".mp3", ".wav"):
            c = BEATS_DIR / f"{stem}{ext}"
            if c.exists():
                audio = c
                break
        if audio is None:
            print(f"[SKIP] {stem}: no audio in beats/")
            continue
        try:
            info = analyze(audio)
            tag = ""
            if not args.print_only:
                write_to_metadata(stem, info)
                tag = "  -> metadata"
            print(f"[OK] {stem}: {info['bpm']} BPM | {info['key']} | {info['duration']}s{tag}")
        except Exception as e:
            print(f"[FAIL] {stem}: {e}")


if __name__ == "__main__":
    main()
