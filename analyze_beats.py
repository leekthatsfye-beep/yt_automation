"""
analyze_beats.py

Detects BPM and musical key for every beat in beats/ and writes the results
into the corresponding metadata/{stem}.json file.

Fields added:
    "bpm": 140          (integer, nearest whole BPM)
    "key": "F# Minor"   (standard musical key)

With --dj flag, also extracts deep audio features for AI DJ classification:
    "dj_features": {
        "spectral_centroid": 0.35,
        "spectral_rolloff": 0.65,
        "rms_mean": 0.08,
        "rms_std": 0.03,
        "zcr_mean": 0.05,
        "mfcc": [float, ...],  // 13 coefficients
        "spectral_contrast": [float, ...],  // 7 bands
        "onset_rate": 7.5,
        "bass_energy_ratio": 0.48,
        "bounce_factor": 0.35,
        "brightness_norm": 0.42,
        "key_mode": "minor"
    }

Improvements over basic librosa:
- BPM: uses percussive separation + tempo prior centered on 120-170 BPM
  (typical trap range) to avoid 2x/0.5x octave errors
- Key: uses harmonic separation before chroma so drums don't skew the result
  Uses NNLS chroma (chroma_cqt) + median aggregation for stability

Skips beats that already have both bpm and key set unless --force is used.
Never overwrites title, artist, description, or tags.

Usage:
    python analyze_beats.py             # analyze all beats missing bpm/key
    python analyze_beats.py --force     # re-analyze everything
    python analyze_beats.py --only "army,master_plan"
    python analyze_beats.py --dj        # extract deep DJ features
    python analyze_beats.py --dj --only "army" --force
"""

import argparse
import json
import re
import warnings
from pathlib import Path

import numpy as np

warnings.filterwarnings("ignore")
import librosa  # noqa: E402

ROOT     = Path(__file__).resolve().parent
BEATS    = ROOT / "beats"
METADATA = ROOT / "metadata"

# Krumhansl-Schmuckler key profiles
MAJOR_PROFILE = np.array([6.35, 2.23, 3.48, 2.33, 4.38, 4.09,
                           2.52, 5.19, 2.39, 3.66, 2.29, 2.88])
MINOR_PROFILE = np.array([6.33, 2.68, 3.52, 5.38, 2.60, 3.53,
                           2.54, 4.75, 3.98, 2.69, 3.34, 3.17])

NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F",
              "F#", "G", "G#", "A", "A#", "B"]

# Typical BPM range for trap/rap beats
BPM_MIN = 60
BPM_MAX = 200


def safe_stem(p: Path) -> str:
    s = p.stem.strip().lower()
    s = re.sub(r"[^\w\s-]", "", s)
    s = re.sub(r"[\s-]+", "_", s)
    return s.strip("_")


def detect_bpm(y: np.ndarray, sr: int) -> int:
    """
    Accurate BPM detection for trap/rap beats.
    - Separates percussive component so the beat tracker locks onto drums
    - Uses tempogram + autocorrelation to find the dominant tempo
    - Snaps result into a musically sensible range (60-200 BPM)
    - Corrects 2x/0.5x octave errors by checking if doubling/halving
      lands closer to the 120-160 trap sweet spot
    """
    # Percussive separation — drums drive the tempo
    _, y_perc = librosa.effects.hpss(y)

    # Compute onset envelope from percussive signal
    onset_env = librosa.onset.onset_strength(y=y_perc, sr=sr, aggregate=np.median)

    # Tempogram-based tempo estimate (more robust than beat_track alone)
    tempo = librosa.feature.tempo(onset_envelope=onset_env, sr=sr)[0]

    # Octave correction: if tempo is suspiciously low or high,
    # try doubling/halving and pick whichever is closest to 130 BPM (trap center)
    def distance_to_sweet_spot(t):
        return abs(t - 130)

    candidates = [tempo]
    if tempo < 90:
        candidates.append(tempo * 2)
    if tempo > 160:
        candidates.append(tempo / 2)
    if tempo < 70:
        candidates.append(tempo * 3)

    # Keep only candidates in valid range
    candidates = [c for c in candidates if BPM_MIN <= c <= BPM_MAX]
    if candidates:
        tempo = min(candidates, key=distance_to_sweet_spot)

    return int(round(float(tempo)))


def detect_key(y: np.ndarray, sr: int) -> str:
    """
    Accurate key detection using harmonic/percussive separation.
    - Isolates harmonic content (melodic, chords) before chroma analysis
    - Uses median aggregation instead of mean (more robust to noise)
    - Krumhansl-Schmuckler profiles for major/minor matching
    """
    # Harmonic separation removes drums/noise that pollute chroma
    y_harm, _ = librosa.effects.hpss(y)

    # CQT-based chroma on harmonic signal
    chroma = librosa.feature.chroma_cqt(y=y_harm, sr=sr, bins_per_octave=36)

    # Median aggregation is more stable than mean against outliers
    chroma_median = np.median(chroma, axis=1)

    best_score = -np.inf
    best_key   = "C Major"

    for i in range(12):
        score_major = np.corrcoef(chroma_median, np.roll(MAJOR_PROFILE, i))[0, 1]
        score_minor = np.corrcoef(chroma_median, np.roll(MINOR_PROFILE, i))[0, 1]

        if score_major > best_score:
            best_score = score_major
            best_key   = f"{NOTE_NAMES[i]} Major"

        if score_minor > best_score:
            best_score = score_minor
            best_key   = f"{NOTE_NAMES[i]} Minor"

    return best_key


def extract_dj_features(y: np.ndarray, sr: int, key_str: str) -> dict:
    """
    Deep audio feature extraction for AI DJ classification.
    Returns a dict of normalized features that describe the beat's sonic character.
    """
    duration = librosa.get_duration(y=y, sr=sr)

    # ── Spectral features ──
    centroid = librosa.feature.spectral_centroid(y=y, sr=sr)[0]
    rolloff = librosa.feature.spectral_rolloff(y=y, sr=sr, roll_percent=0.85)[0]
    # Normalize centroid to 0-1 range (typical range 500-8000 Hz)
    centroid_mean = float(np.mean(centroid))
    brightness_norm = min(1.0, max(0.0, (centroid_mean - 500) / 7500))
    rolloff_mean = float(np.mean(rolloff))
    rolloff_norm = min(1.0, max(0.0, (rolloff_mean - 1000) / 10000))

    # ── Energy ──
    rms = librosa.feature.rms(y=y)[0]
    rms_mean = float(np.mean(rms))
    rms_std = float(np.std(rms))

    # ── Zero crossing rate (noisiness/percussiveness) ──
    zcr = librosa.feature.zero_crossing_rate(y)[0]
    zcr_mean = float(np.mean(zcr))

    # ── MFCCs (timbral fingerprint) ──
    mfcc = librosa.feature.mfcc(y=y, sr=sr, n_mfcc=13)
    mfcc_means = [float(np.mean(mfcc[i])) for i in range(13)]

    # ── Spectral contrast (harmonic vs noise in 7 freq bands) ──
    contrast = librosa.feature.spectral_contrast(y=y, sr=sr, n_bands=6)
    contrast_means = [float(np.mean(contrast[i])) for i in range(contrast.shape[0])]

    # ── Onset density (onsets per second) ──
    _, y_perc = librosa.effects.hpss(y)
    onset_frames = librosa.onset.onset_detect(y=y_perc, sr=sr, backtrack=True)
    onset_rate = len(onset_frames) / max(duration, 1.0)

    # ── Bass energy ratio (20-150 Hz vs total) ──
    # Use STFT and frequency masking
    S = np.abs(librosa.stft(y, n_fft=2048))
    freqs = librosa.fft_frequencies(sr=sr, n_fft=2048)
    bass_mask = (freqs >= 20) & (freqs <= 150)
    total_energy = float(np.sum(S ** 2))
    bass_energy = float(np.sum(S[bass_mask] ** 2))
    bass_ratio = bass_energy / max(total_energy, 1e-10)

    # ── Bounce factor (rhythmic periodicity via onset autocorrelation) ──
    onset_env = librosa.onset.onset_strength(y=y_perc, sr=sr)
    # Autocorrelation of onset envelope
    ac = np.correlate(onset_env, onset_env, mode="full")
    ac = ac[len(ac)//2:]  # positive lags only
    if len(ac) > 1:
        ac = ac / (ac[0] + 1e-10)  # normalize
        # Find peaks in autocorrelation (strong periodicity = high bounce)
        # Look for peaks between 0.3s and 1.5s (corresponds to typical bounce tempos)
        hop_length = 512
        min_lag = int(0.3 * sr / hop_length)
        max_lag = int(1.5 * sr / hop_length)
        if max_lag < len(ac):
            ac_segment = ac[min_lag:max_lag]
            bounce_factor = float(np.max(ac_segment)) if len(ac_segment) > 0 else 0.0
        else:
            bounce_factor = 0.0
    else:
        bounce_factor = 0.0

    bounce_factor = min(1.0, max(0.0, bounce_factor))

    # ── Key mode ──
    key_mode = "minor" if "Minor" in key_str else "major"

    return {
        "spectral_centroid": round(centroid_mean, 2),
        "spectral_rolloff": round(rolloff_mean, 2),
        "brightness_norm": round(brightness_norm, 4),
        "rolloff_norm": round(rolloff_norm, 4),
        "rms_mean": round(rms_mean, 6),
        "rms_std": round(rms_std, 6),
        "zcr_mean": round(zcr_mean, 6),
        "mfcc": [round(v, 4) for v in mfcc_means],
        "spectral_contrast": [round(v, 4) for v in contrast_means],
        "onset_rate": round(onset_rate, 2),
        "bass_energy_ratio": round(bass_ratio, 4),
        "bounce_factor": round(bounce_factor, 4),
        "key_mode": key_mode,
        "duration": round(duration, 1),
    }


def analyze(audio_path: Path, dj: bool = False) -> dict:
    """Load audio, return {'bpm': int, 'key': str, 'dj_features'?: dict}."""
    # Resample to 22050 Hz — librosa's native rate, best accuracy
    y, sr = librosa.load(str(audio_path), sr=22050, mono=True)
    result = {
        "bpm": detect_bpm(y, sr),
        "key": detect_key(y, sr),
    }
    if dj:
        result["dj_features"] = extract_dj_features(y, sr, result["key"])
    return result


def main():
    parser = argparse.ArgumentParser(description="Detect BPM and key for all beats.")
    parser.add_argument("--force", action="store_true",
                        help="Re-analyze beats that already have bpm/key set")
    parser.add_argument("--only", type=str, default=None,
                        help="Comma-separated stems to analyze (e.g. army,master_plan)")
    parser.add_argument("--dj", action="store_true",
                        help="Extract deep audio features for AI DJ classification")
    args = parser.parse_args()

    only_stems = {s.strip() for s in args.only.split(",")} if args.only else None

    audio_files = sorted(list(BEATS.glob("*.mp3")) + list(BEATS.glob("*.wav")))
    if not audio_files:
        print("[INFO] No audio files found in beats/")
        return

    METADATA.mkdir(exist_ok=True)

    mode_label = "DJ features" if args.dj else "BPM/key"
    skip_key = "dj_features" if args.dj else "bpm"

    analyzed = 0
    skipped  = 0
    errors   = 0

    for audio_path in audio_files:
        stem = safe_stem(audio_path)

        if only_stems and stem not in only_stems:
            continue

        meta_path = METADATA / f"{stem}.json"

        if meta_path.exists():
            with open(meta_path) as f:
                meta = json.load(f)
        else:
            meta = {
                "title":       stem.replace("_", " ").title(),
                "artist":      "LeekThatsFye",
                "description": "",
                "tags":        [],
            }

        # Skip check
        if not args.force:
            if args.dj and "dj_features" in meta:
                print(f"[SKIP] {stem}  (dj_features exist)")
                skipped += 1
                continue
            elif not args.dj and "bpm" in meta and "key" in meta:
                print(f"[SKIP] {stem}  (bpm={meta['bpm']}, key={meta['key']})")
                skipped += 1
                continue

        label = "[DJ]" if args.dj else "[ANALYZE]"
        print(f"{label} {stem} ...", end="", flush=True)
        try:
            result = analyze(audio_path, dj=args.dj)
            meta["bpm"] = result["bpm"]
            meta["key"] = result["key"]

            if args.dj and "dj_features" in result:
                meta["dj_features"] = result["dj_features"]

            with open(meta_path, "w") as f:
                json.dump(meta, f, indent=2)

            extra = ""
            if args.dj and "dj_features" in result:
                feats = result["dj_features"]
                extra = (
                    f"  | bright={feats['brightness_norm']:.2f}"
                    f"  bass={feats['bass_energy_ratio']:.2f}"
                    f"  bounce={feats['bounce_factor']:.2f}"
                    f"  onset={feats['onset_rate']:.1f}/s"
                )

            print(f"  {result['bpm']} BPM  |  {result['key']}{extra}")
            analyzed += 1
        except Exception as e:
            print(f"  ERROR: {e}")
            errors += 1

    print(f"\n{'─'*40}")
    print(f"  {mode_label}: Analyzed={analyzed}  Skipped={skipped}  Errors={errors}")
    print(f"{'─'*40}")


if __name__ == "__main__":
    main()
