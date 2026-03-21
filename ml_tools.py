#!/usr/bin/env python3.11
"""
ml_tools.py — Stem separation (demucs) + MIDI extraction (basic-pitch).

Runs under Python 3.11 venv (.venv_ml) because PyTorch ML tools
don't support Python 3.14 yet.

Usage:
    python3.11 ml_tools.py stems  <input.mp3> <output_dir>
    python3.11 ml_tools.py midi   <input.mp3> <output.mid>
    python3.11 ml_tools.py both   <input.mp3> <output_dir>

stems: Separates into drums.wav, bass.wav, vocals.wav, other.wav
midi:  Extracts MIDI notes from audio
both:  Stems first, then MIDI from each stem

Bulletproofed:
  - Input validation (file exists, readable, non-zero)
  - MPS/CPU device fallback with graceful degradation
  - Memory cleanup after GPU operations
  - Proper error messages with stack traces
  - Heartbeat progress output for watchdog detection
  - Handles mono/stereo/multi-channel audio
  - Handles all sample rates (auto-resamples)
"""
import sys
import os
import gc
import json
import time
import signal
import traceback
import argparse
from pathlib import Path


# ── Timeout handler ──────────────────────────────────────────────────────────
class TimeoutError(Exception):
    pass

def _timeout_handler(signum, frame):
    raise TimeoutError("Operation timed out")


# ── Validation ───────────────────────────────────────────────────────────────
def _validate_input(input_path: str) -> Path:
    """Validate input audio file exists, is readable, and non-empty."""
    p = Path(input_path)
    if not p.exists():
        raise FileNotFoundError(f"Input file not found: {input_path}")
    if not p.is_file():
        raise ValueError(f"Not a file: {input_path}")
    size = p.stat().st_size
    if size == 0:
        raise ValueError(f"Input file is empty (0 bytes): {input_path}")
    if size < 100:
        raise ValueError(f"Input file too small ({size} bytes), likely corrupt: {input_path}")
    # Check extension
    ext = p.suffix.lower()
    supported = {".mp3", ".wav", ".flac", ".ogg", ".m4a", ".aac", ".wma", ".aiff"}
    if ext not in supported:
        print(f"[warn] Unusual extension '{ext}' — will attempt to load anyway", flush=True)
    return p


def _cleanup_gpu():
    """Release GPU memory after processing."""
    try:
        import torch
        if torch.backends.mps.is_available():
            # Force MPS to release memory
            torch.mps.empty_cache()
            torch.mps.synchronize()
        if torch.cuda.is_available():
            torch.cuda.empty_cache()
    except Exception:
        pass
    gc.collect()


# ── Stem separation ─────────────────────────────────────────────────────────
def separate_stems(input_path: str, output_dir: str, timeout_s: int = 300) -> dict:
    """Separate audio into stems using demucs HTDemucs.

    Returns dict with stem paths + elapsed_s, e.g.:
        {"drums": "/path/drums.wav", "bass": "...", "other": "...",
         "vocals": "...", "elapsed_s": 15.2}
    """
    import torch
    import torchaudio
    from demucs.pretrained import get_model
    from demucs.apply import apply_model

    inp = _validate_input(input_path)
    os.makedirs(output_dir, exist_ok=True)
    start = time.time()

    # Set timeout
    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout_s)

    try:
        # ── Load model ───────────────────────────────────────────────────
        print(f"[stems] Loading HTDemucs model...", flush=True)
        model = get_model("htdemucs")

        # ── Device selection with fallback ───────────────────────────────
        device = "cpu"
        if torch.backends.mps.is_available():
            try:
                # Quick smoke test — some MPS ops can fail
                _test = torch.zeros(1, device="mps")
                del _test
                torch.mps.empty_cache()
                device = "mps"
            except Exception as e:
                print(f"[stems] MPS test failed ({e}), using CPU", flush=True)

        print(f"[stems] Using device: {device}", flush=True)
        model.to(device)

        # ── Load audio ───────────────────────────────────────────────────
        print(f"[stems] Loading audio: {inp} ({inp.stat().st_size / 1024:.0f} KB)", flush=True)
        try:
            wav, sr = torchaudio.load(str(inp))
        except Exception as e:
            # Fallback: try ffmpeg decode via subprocess
            print(f"[stems] torchaudio.load failed ({e}), trying ffmpeg fallback...", flush=True)
            import subprocess
            import tempfile
            tmp_wav = tempfile.mktemp(suffix=".wav")
            subprocess.run(
                ["ffmpeg", "-y", "-i", str(inp), "-ar", "44100", "-ac", "2", tmp_wav],
                capture_output=True, timeout=60,
            )
            wav, sr = torchaudio.load(tmp_wav)
            os.unlink(tmp_wav)

        print(f"[stems] Audio: {wav.shape[0]}ch, {sr}Hz, {wav.shape[1]/sr:.1f}s", flush=True)

        # ── Resample if needed (demucs expects 44100) ────────────────────
        if sr != model.samplerate:
            print(f"[stems] Resampling {sr} → {model.samplerate}", flush=True)
            wav = torchaudio.functional.resample(wav, sr, model.samplerate)

        # ── Ensure stereo ────────────────────────────────────────────────
        if wav.shape[0] == 1:
            wav = wav.repeat(2, 1)
        elif wav.shape[0] > 2:
            # Multi-channel: take first two
            wav = wav[:2]

        # ── Normalize ────────────────────────────────────────────────────
        print(f"[stems] Separating stems...", flush=True)
        ref = wav.mean(0)
        ref_std = ref.std()
        # Prevent division by zero on silent audio
        if ref_std < 1e-8:
            print("[stems] Warning: audio appears silent, using minimal normalization", flush=True)
            ref_std = torch.tensor(1.0)
        wav_norm = (wav - ref.mean()) / ref_std

        # ── Run separation ───────────────────────────────────────────────
        try:
            sources = apply_model(
                model,
                wav_norm.unsqueeze(0).to(device),
                split=True,
                device=device,
                progress=True,
            )
        except RuntimeError as e:
            err_msg = str(e).lower()
            if "mps" in err_msg or "out of memory" in err_msg or "metal" in err_msg:
                print(f"[stems] MPS failed ({e}), falling back to CPU...", flush=True)
                model.to("cpu")
                device = "cpu"
                sources = apply_model(
                    model,
                    wav_norm.unsqueeze(0),
                    split=True,
                    device="cpu",
                    progress=True,
                )
            else:
                raise

        # ── Denormalize ──────────────────────────────────────────────────
        sources = sources * ref_std + ref.mean()

        # ── Save stems ───────────────────────────────────────────────────
        stem_names = model.sources  # ['drums', 'bass', 'other', 'vocals']
        result = {}
        for i, name in enumerate(stem_names):
            stem_path = os.path.join(output_dir, f"{name}.wav")
            stem_data = sources[0, i].cpu()
            torchaudio.save(stem_path, stem_data, model.samplerate)
            fsize = Path(stem_path).stat().st_size
            result[name] = stem_path
            print(f"[stems] Saved {name}: {stem_path} ({fsize/1024:.0f} KB)", flush=True)

        elapsed = time.time() - start
        result["elapsed_s"] = round(elapsed, 1)
        print(f"[stems] Done in {elapsed:.1f}s", flush=True)
        return result

    finally:
        # Cancel alarm and restore handler
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        # Free GPU memory
        _cleanup_gpu()


# ── MIDI extraction ──────────────────────────────────────────────────────────
def extract_midi(input_path: str, output_path: str, timeout_s: int = 120) -> dict:
    """Extract MIDI from audio using Spotify basic-pitch.

    Returns dict with midi_path, num_notes, elapsed_s.
    """
    # Suppress noisy warnings before importing basic_pitch
    import warnings
    warnings.filterwarnings("ignore", message=".*pkg_resources.*")
    warnings.filterwarnings("ignore", message=".*tflite.*")
    warnings.filterwarnings("ignore", message=".*onnxruntime.*")
    warnings.filterwarnings("ignore", message=".*Tensorflow.*")
    warnings.filterwarnings("ignore", message=".*scikit-learn.*")
    warnings.filterwarnings("ignore", message=".*coremltools.*")

    from basic_pitch.inference import predict
    from basic_pitch import ICASSP_2022_MODEL_PATH

    inp = _validate_input(input_path)
    start = time.time()

    # Set timeout
    old_handler = signal.signal(signal.SIGALRM, _timeout_handler)
    signal.alarm(timeout_s)

    try:
        print(f"[midi] Extracting MIDI from: {inp} ({inp.stat().st_size / 1024:.0f} KB)", flush=True)

        model_output, midi_data, note_events = predict(
            str(inp),
            model_or_model_path=ICASSP_2022_MODEL_PATH,
            onset_threshold=0.5,
            frame_threshold=0.3,
            minimum_note_length=58.0,
            melodia_trick=True,
            midi_tempo=120.0,
        )

        os.makedirs(os.path.dirname(output_path) or ".", exist_ok=True)
        midi_data.write(output_path)

        # Verify output
        out_size = Path(output_path).stat().st_size
        if out_size == 0:
            raise RuntimeError("MIDI file is empty (0 bytes)")

        elapsed = time.time() - start
        result = {
            "midi_path": output_path,
            "num_notes": len(note_events),
            "elapsed_s": round(elapsed, 1),
        }
        print(f"[midi] Saved {len(note_events)} notes to {output_path} ({elapsed:.1f}s)", flush=True)
        return result

    finally:
        signal.alarm(0)
        signal.signal(signal.SIGALRM, old_handler)
        gc.collect()


# ── Both (stems + MIDI) ─────────────────────────────────────────────────────
def process_both(input_path: str, output_dir: str) -> dict:
    """Separate stems, then extract MIDI from each melodic stem."""
    os.makedirs(output_dir, exist_ok=True)

    # Step 1: Separate stems
    stems_dir = os.path.join(output_dir, "stems")
    stems_result = separate_stems(input_path, stems_dir)

    # Step 2: Extract MIDI from melodic stems (skip drums — they're percussive)
    midi_dir = os.path.join(output_dir, "midi")
    os.makedirs(midi_dir, exist_ok=True)

    midi_results = {}
    for stem_name in ["bass", "other", "vocals"]:
        stem_path = stems_result.get(stem_name)
        if stem_path and os.path.exists(stem_path):
            midi_path = os.path.join(midi_dir, f"{stem_name}.mid")
            try:
                midi_results[stem_name] = extract_midi(stem_path, midi_path)
            except Exception as e:
                print(f"[midi] Failed for {stem_name}: {e}", flush=True)
                midi_results[stem_name] = {"error": str(e)}

    return {
        "stems": stems_result,
        "midi": midi_results,
    }


# ── Main ─────────────────────────────────────────────────────────────────────
def main():
    parser = argparse.ArgumentParser(description="ML audio tools (demucs + basic-pitch)")
    parser.add_argument("mode", choices=["stems", "midi", "both"])
    parser.add_argument("input", help="Input audio file")
    parser.add_argument("output", help="Output dir (stems/both) or .mid file (midi)")
    args = parser.parse_args()

    try:
        if args.mode == "stems":
            result = separate_stems(args.input, args.output)
        elif args.mode == "midi":
            result = extract_midi(args.input, args.output)
        elif args.mode == "both":
            result = process_both(args.input, args.output)

        # Print JSON result for the caller to parse
        print(f"\n__RESULT__{json.dumps(result)}__END__", flush=True)

    except TimeoutError:
        print(f"\n__ERROR__Operation timed out__END__", flush=True)
        sys.exit(2)
    except FileNotFoundError as e:
        print(f"\n__ERROR__File not found: {e}__END__", flush=True)
        sys.exit(3)
    except Exception as e:
        tb = traceback.format_exc()
        print(f"\n__ERROR__{type(e).__name__}: {e}__END__", flush=True)
        print(f"[traceback]\n{tb}", file=sys.stderr, flush=True)
        sys.exit(1)


if __name__ == "__main__":
    main()
