#!/usr/bin/env python3
"""
FY3 Zaytoven Collection — Preset Generator
============================================
Generates all 1000 WAV presets from preset definitions.
Run: python3.14 zaytoven_vst/generate.py

Output:
  zaytoven_vst/output/FY3_Zaytoven_Organs/Early_Era_2005-2010/FY3_ORG_001_Trap_House_Church.wav
  zaytoven_vst/output/FY3_preset_catalog.json
"""

import json
import os
import sys
import time
import traceback
import numpy as np

# Add parent dir so engine/ imports work
sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from engine.organ import Organ
from engine.piano import Piano
from engine.bells import Bell
from engine.flute import Flute
from engine.strings import Strings
from engine.pads import Pad
from engine.bass import Bass
from engine.leads import Lead
from engine.keys import Keys
from engine.vocals import Vocals
from engine.oscillators import noise, sine
from engine.envelope import percussive, adsr
from engine.filters import lowpass, highpass, bandpass, filter_sweep
from engine.effects import reverb, delay_effect, saturate, eq_3band
from engine.utils import (
    normalize, stereo_spread, export_wav, safe_filename,
    fade_both, mix_signals, midi_to_freq,
)

# ─── Import all preset banks ─────────────────────────────────────────────────
from presets.organs import ORGAN_PRESETS
from presets.pianos import PIANO_PRESETS
from presets.bells import BELL_PRESETS
from presets.flutes import FLUTE_PRESETS
from presets.strings import STRING_PRESETS
from presets.pads import PAD_PRESETS
from presets.bass import BASS_PRESETS
from presets.leads import LEAD_PRESETS
from presets.keys import KEYS_PRESETS
from presets.fx import FX_PRESETS
from presets.vocals import VOCAL_PRESETS

# ─── Constants ────────────────────────────────────────────────────────────────
SR = 48000
OUTPUT_DIR = os.path.join(os.path.dirname(os.path.abspath(__file__)), "output")

# Category → subfolder name
CATEGORY_FOLDERS = {
    "Organs": "FY3_Zaytoven_Organs",
    "Pianos": "FY3_Zaytoven_Pianos",
    "Bells": "FY3_Zaytoven_Bells",
    "Flutes": "FY3_Zaytoven_Flutes",
    "Strings": "FY3_Zaytoven_Strings",
    "Pads": "FY3_Zaytoven_Pads",
    "Bass": "FY3_Zaytoven_Bass",
    "Leads": "FY3_Zaytoven_Leads",
    "Keys": "FY3_Zaytoven_Keys",
    "FX": "FY3_Zaytoven_FX",
    "Vocals": "FY3_Zaytoven_Vocals",
}

# Era → subfolder name
ERA_FOLDERS = {
    "Early (2005-2010)": "Early_Era_2005-2010",
    "Peak (2010-2016)": "Peak_Era_2010-2016",
    "Modern (2016+)": "Modern_Era_2016-Now",
    "All Eras": "All_Eras",
}

# ─── Instrument instances ────────────────────────────────────────────────────
organ = Organ(sr=SR)
piano = Piano(sr=SR)
bell = Bell(sr=SR)
flute = Flute(sr=SR)
strings = Strings(sr=SR)
pad = Pad(sr=SR)
bass = Bass(sr=SR)
lead = Lead(sr=SR)
keys = Keys(sr=SR)
vocals = Vocals(sr=SR)


def render_fx(note: int, duration: float, params: dict) -> np.ndarray:
    """Render FX/texture presets using raw engine components."""
    fx_type = params.get("fx_type", "riser")
    n = int(SR * duration)

    if fx_type == "riser":
        return _render_riser(duration, params)
    elif fx_type == "impact":
        return _render_impact(duration, params)
    elif fx_type == "texture":
        return _render_texture(duration, params)
    else:
        return _render_riser(duration, params)


def _render_riser(duration: float, params: dict) -> np.ndarray:
    """Filtered noise sweep upward."""
    n = int(SR * duration)
    color = params.get("noise_color", "white")
    sweep_range = params.get("sweep_range", [200, 12000])

    # Generate noise
    sig = noise(duration, SR, color)

    # Sweep filter upward
    sig = filter_sweep(sig, sweep_range[0], sweep_range[1], SR, 2, "low")

    # Volume ramp
    ramp = np.linspace(0.1, 1.0, n)
    sig = sig[:n] * ramp

    # Effects
    dist = params.get("distortion", 0)
    if dist > 0:
        sig = saturate(sig, dist, "soft")

    rev_wet = params.get("reverb_wet", 0.4)
    rev_size = params.get("reverb_size", 0.6)
    if rev_wet > 0:
        sig = reverb(sig, SR, rev_size, 0.5, rev_wet)

    # Stereo
    width = params.get("stereo_width", 0.6)
    audio = stereo_spread(sig, width, SR)

    return audio[:, 0] if audio.ndim > 1 else audio


def _render_impact(duration: float, params: dict) -> np.ndarray:
    """Layered transient hit."""
    n = int(SR * duration)
    decay_time = params.get("decay_time", 0.5)
    layer_count = params.get("layer_count", 3)

    # Sub boom
    freq = 40 + np.random.rand() * 20
    sub = sine(freq, duration, SR)
    sub_env = percussive(0.001, decay_time, duration, SR, 6)
    sub *= sub_env * 0.7

    # Noise burst
    burst = noise(duration, SR, "white")
    burst = bandpass(burst, 500, 8000, SR)
    burst_env = percussive(0.0005, decay_time * 0.3, duration, SR, 10)
    burst *= burst_env * 0.3

    # Click transient
    click = noise(duration, SR, "white")
    click = highpass(click, 4000, SR)
    click_env = percussive(0.0002, 0.01, duration, SR, 20)
    click *= click_env * 0.2

    sig = sub + burst + click

    # Effects
    dist = params.get("distortion", 0)
    if dist > 0:
        sig = saturate(sig, dist, "tube")

    rev_wet = params.get("reverb_wet", 0.3)
    rev_size = params.get("reverb_size", 0.7)
    if rev_wet > 0:
        sig = reverb(sig, SR, rev_size, 0.4, rev_wet)

    width = params.get("stereo_width", 0.5)
    audio = stereo_spread(sig, width, SR)

    return audio[:, 0] if audio.ndim > 1 else audio


def _render_texture(duration: float, params: dict) -> np.ndarray:
    """Ambient noise/drone bed."""
    n = int(SR * duration)
    color = params.get("noise_color", "pink")
    attack = params.get("attack_time", 2.0)

    # Noise base
    sig = noise(duration, SR, color)

    # Slow envelope
    env = adsr(attack, 1.0, 0.6, 2.0, duration, SR)
    sig *= env

    # Low-pass for warmth
    sig = lowpass(sig, 3000, SR, order=3)

    # Subtle movement with filter sweep
    sig = filter_sweep(sig, 800, 3000, SR, 2, "low")

    # Effects
    rev_wet = params.get("reverb_wet", 0.6)
    rev_size = params.get("reverb_size", 0.8)
    if rev_wet > 0:
        sig = reverb(sig, SR, rev_size, 0.6, rev_wet)

    dly_mix = params.get("delay_mix", 0)
    dly_ms = params.get("delay_ms", 400)
    if dly_mix > 0:
        sig = delay_effect(sig, SR, dly_ms, 0.4, dly_mix)

    width = params.get("stereo_width", 0.8)
    audio = stereo_spread(sig, width, SR)

    return audio[:, 0] if audio.ndim > 1 else audio


# ─── Category → renderer mapping ─────────────────────────────────────────────
RENDERERS = {
    "Organs": lambda note, dur, p: organ.render(note, dur, p),
    "Pianos": lambda note, dur, p: piano.render(note, dur, p),
    "Bells": lambda note, dur, p: bell.render(note, dur, p),
    "Flutes": lambda note, dur, p: flute.render(note, dur, p),
    "Strings": lambda note, dur, p: strings.render(note, dur, p),
    "Pads": lambda note, dur, p: pad.render(note, dur, p),
    "Bass": lambda note, dur, p: bass.render(note, dur, p),
    "Leads": lambda note, dur, p: lead.render(note, dur, p),
    "Keys": lambda note, dur, p: keys.render(note, dur, p),
    "FX": render_fx,
    "Vocals": lambda note, dur, p: vocals.render(note, dur, p),
}

# ─── All presets combined ─────────────────────────────────────────────────────
ALL_PRESETS = (
    ORGAN_PRESETS
    + PIANO_PRESETS
    + BELL_PRESETS
    + FLUTE_PRESETS
    + STRING_PRESETS
    + PAD_PRESETS
    + BASS_PRESETS
    + LEAD_PRESETS
    + KEYS_PRESETS
    + FX_PRESETS
    + VOCAL_PRESETS
)


def build_filepath(preset: dict) -> str:
    """Build output WAV filepath from preset metadata."""
    category = preset["category"]
    era = preset.get("era", "All Eras")
    preset_id = preset["id"]
    name = safe_filename(preset["name"])

    cat_folder = CATEGORY_FOLDERS.get(category, f"FY3_Zaytoven_{category}")
    era_folder = ERA_FOLDERS.get(era, "All_Eras")

    filename = f"{preset_id}_{name}.wav"
    return os.path.join(OUTPUT_DIR, cat_folder, era_folder, filename)


# Category-specific mastering profiles — preserves tonal character per category
# instead of flattening everything with identical processing
WARMTH_PROFILES = {
    "Organs":  {"tape": 0.06, "exciter": 0.12, "exciter_freq": 3000, "eq": (2.0, 0.0, 0.5),  "comp_thresh": -14, "comp_ratio": 1.6},
    "Pianos":  {"tape": 0.04, "exciter": 0.08, "exciter_freq": 4000, "eq": (1.0, 0.0, 0.8),  "comp_thresh": -12, "comp_ratio": 2.0},
    "Bells":   {"tape": 0.03, "exciter": 0.15, "exciter_freq": 5000, "eq": (-1.0, 0.0, 2.0), "comp_thresh": -10, "comp_ratio": 1.5},
    "Flutes":  {"tape": 0.03, "exciter": 0.06, "exciter_freq": 4500, "eq": (-1.0, 0.5, 0.5), "comp_thresh": -14, "comp_ratio": 1.5},
    "Strings": {"tape": 0.05, "exciter": 0.10, "exciter_freq": 3000, "eq": (1.0, 0.5, 0.3),  "comp_thresh": -16, "comp_ratio": 1.8},
    "Pads":    {"tape": 0.05, "exciter": 0.08, "exciter_freq": 2500, "eq": (1.5, 0.0, 0.3),  "comp_thresh": -18, "comp_ratio": 1.5},
    "Bass":    {"tape": 0.08, "exciter": 0.05, "exciter_freq": 2000, "eq": (3.0, -0.5, -1.0),"comp_thresh": -12, "comp_ratio": 2.5},
    "Leads":   {"tape": 0.06, "exciter": 0.18, "exciter_freq": 4000, "eq": (0.0, 1.0, 1.5),  "comp_thresh": -14, "comp_ratio": 2.0},
    "Keys":    {"tape": 0.04, "exciter": 0.10, "exciter_freq": 3500, "eq": (0.5, 0.0, 1.0),  "comp_thresh": -14, "comp_ratio": 1.8},
    "FX":      {"tape": 0.02, "exciter": 0.05, "exciter_freq": 5000, "eq": (0.0, 0.0, 0.5),  "comp_thresh": -10, "comp_ratio": 1.3},
    "Vocals":  {"tape": 0.04, "exciter": 0.15, "exciter_freq": 3000, "eq": (-1.0, 1.5, 1.0), "comp_thresh": -16, "comp_ratio": 2.0},
}

# Default profile for unknown categories — balanced neutral settings
_WARMTH_DEFAULT = {"tape": 0.05, "exciter": 0.10, "exciter_freq": 3500, "eq": (1.0, 0.0, 0.8), "comp_thresh": -14, "comp_ratio": 1.8}


def master_warmth(audio: np.ndarray, sr: int, category: str = "") -> np.ndarray:
    """Master bus analog warmth — category-aware for professional sheen.

    Uses per-category profiles (WARMTH_PROFILES) so that dark presets stay dark,
    bright presets stay bright, and punchy bass doesn't get the same exciter
    settings as airy bells.

    Enhanced Omnisphere-quality master chain:
    1. Subtle analog drift for organic character
    2. Tape saturation for analog warmth (category-tuned)
    3. Harmonic exciter for presence and air (category-tuned)
    4. Stereo width enhancement
    5. 3-band EQ shaped per category
    6. Bus compression with category-appropriate dynamics
    7. Final limiter for consistent levels

    Simulates running through a professional analog mixing chain:
    high-end console, tape machine, and mastering-grade dynamics.
    """
    from engine.effects import compress, harmonic_exciter, analog_warmth

    # Select category-specific mastering profile
    profile = WARMTH_PROFILES.get(category, _WARMTH_DEFAULT)

    n = len(audio)

    # 1. Subtle analog drift — slow pitch/time variation for organic feel
    # This prevents the "too perfect" digital quality
    t = np.arange(n) / sr
    drift_rate = np.random.uniform(0.02, 0.08)
    drift_amount = 0.08  # reduced from 0.15 — less aggressive drift
    drift_lfo = np.sin(2 * np.pi * drift_rate * t + np.random.uniform(0, 6.28))
    drift_samples = drift_lfo * drift_amount
    read_pos = np.arange(n, dtype=np.float64) + drift_samples
    read_pos = np.clip(read_pos, 0, n - 1)
    idx_floor = np.floor(read_pos).astype(int)
    idx_ceil = np.minimum(idx_floor + 1, n - 1)
    frac = read_pos - idx_floor
    audio = audio[idx_floor] * (1 - frac) + audio[idx_ceil] * frac

    # 2. Tape saturation — drive amount varies by category
    audio = saturate(audio, drive=profile["tape"], sat_type='tape')

    # 3. Harmonic exciter — amount and frequency tuned per category
    audio = harmonic_exciter(audio, sr=sr, amount=profile["exciter"],
                             frequency=float(profile["exciter_freq"]))

    # 4. Stereo width enhancement (subtle, preserves mono character)
    from engine.effects import stereo_widener
    audio = stereo_widener(audio, sr=sr, width=1.08)  # reduced from 1.15

    # 5. 3-band EQ shaped per category
    audio = eq_3band(audio, sr,
                     low_gain_db=profile["eq"][0],
                     mid_gain_db=profile["eq"][1],
                     high_gain_db=profile["eq"][2])

    # 6. Bus compression with category-appropriate dynamics
    audio = compress(audio, threshold_db=profile["comp_thresh"],
                     ratio=profile["comp_ratio"],
                     attack_ms=20, release_ms=120, sr=sr)

    # 7. Final soft limiter to prevent any overs
    peak = np.max(np.abs(audio))
    if peak > 0.95:
        audio = audio * (0.95 / peak)

    return audio


def render_preset(preset: dict) -> str:
    """Render a single preset to WAV. Returns filepath."""
    category = preset["category"]
    note = preset.get("note", 60)
    duration = preset.get("duration", 5.0)
    params = preset.get("params", {})

    renderer = RENDERERS.get(category)
    if renderer is None:
        raise ValueError(f"Unknown category: {category}")

    # Render audio
    audio = renderer(note, duration, params)

    # Build path and export
    filepath = build_filepath(preset)
    # Apply master analog warmth chain to every preset
    audio = master_warmth(audio, SR, category=category)
    export_wav(audio, filepath, SR, 24)

    return filepath


def build_catalog(presets: list, results: dict) -> dict:
    """Build the catalog JSON."""
    catalog = {
        "pack_name": "FY3 Zaytoven Collection",
        "brand": "FY3",
        "total_presets": len(presets),
        "categories": {
            "Organs": sum(1 for p in presets if p["category"] == "Organs"),
            "Pianos": sum(1 for p in presets if p["category"] == "Pianos"),
            "Bells": sum(1 for p in presets if p["category"] == "Bells"),
            "Flutes": sum(1 for p in presets if p["category"] == "Flutes"),
            "Strings": sum(1 for p in presets if p["category"] == "Strings"),
            "Pads": sum(1 for p in presets if p["category"] == "Pads"),
            "Bass": sum(1 for p in presets if p["category"] == "Bass"),
            "Leads": sum(1 for p in presets if p["category"] == "Leads"),
            "Keys": sum(1 for p in presets if p["category"] == "Keys"),
            "FX": sum(1 for p in presets if p["category"] == "FX"),
            "Vocals": sum(1 for p in presets if p["category"] == "Vocals"),
        },
        "presets": [],
    }

    for preset in presets:
        pid = preset["id"]
        entry = {
            "id": pid,
            "name": preset["name"],
            "filename": os.path.basename(results.get(pid, "")),
            "category": preset["category"],
            "era": preset.get("era", "All Eras"),
            "inspiration": preset.get("inspiration", ""),
            "instrument_breakdown": preset.get("instrument_breakdown", ""),
            "note": preset.get("note", 60),
            "duration": preset.get("duration", 5.0),
            "status": "rendered" if pid in results else "failed",
        }
        catalog["presets"].append(entry)

    return catalog


def main():
    print("=" * 70)
    print("  FY3 Zaytoven Collection — Preset Generator")
    print("=" * 70)
    print(f"\n  Total presets to render: {len(ALL_PRESETS)}")
    print(f"  Output directory: {OUTPUT_DIR}")
    print(f"  Sample rate: {SR} Hz | Bit depth: 24-bit | Format: WAV stereo")
    print()

    # Verify counts
    counts = {}
    for p in ALL_PRESETS:
        cat = p["category"]
        counts[cat] = counts.get(cat, 0) + 1

    for cat, count in sorted(counts.items()):
        print(f"    {cat:12s}: {count:4d} presets")
    print(f"    {'TOTAL':12s}: {len(ALL_PRESETS):4d} presets")
    print()

    # Create output directories
    for cat_folder in CATEGORY_FOLDERS.values():
        for era_folder in ERA_FOLDERS.values():
            os.makedirs(os.path.join(OUTPUT_DIR, cat_folder, era_folder), exist_ok=True)

    # Render all presets
    results = {}
    errors = []
    start_time = time.time()

    for i, preset in enumerate(ALL_PRESETS, 1):
        pid = preset["id"]
        name = preset["name"]
        cat = preset["category"]

        try:
            filepath = render_preset(preset)
            results[pid] = filepath
            elapsed = time.time() - start_time
            rate = i / elapsed if elapsed > 0 else 0
            eta = (len(ALL_PRESETS) - i) / rate if rate > 0 else 0

            print(f"  [{i:4d}/{len(ALL_PRESETS)}] ✓ {pid} — {name}")

            # Progress every 50
            if i % 50 == 0:
                print(f"\n  --- Progress: {i}/{len(ALL_PRESETS)} "
                      f"({100*i/len(ALL_PRESETS):.1f}%) | "
                      f"Elapsed: {elapsed:.0f}s | "
                      f"ETA: {eta:.0f}s ---\n")

        except Exception as e:
            errors.append((pid, name, str(e)))
            print(f"  [{i:4d}/{len(ALL_PRESETS)}] ✗ {pid} — {name} — ERROR: {e}")
            traceback.print_exc()

    # Summary
    total_time = time.time() - start_time
    print("\n" + "=" * 70)
    print("  GENERATION COMPLETE")
    print("=" * 70)
    print(f"\n  Rendered: {len(results)}/{len(ALL_PRESETS)} presets")
    print(f"  Errors:   {len(errors)}")
    print(f"  Time:     {total_time:.1f}s ({total_time/60:.1f} minutes)")
    print(f"  Rate:     {len(results)/total_time:.1f} presets/second")

    if errors:
        print(f"\n  Failed presets:")
        for pid, name, err in errors:
            print(f"    {pid} — {name}: {err}")

    # Write catalog
    catalog = build_catalog(ALL_PRESETS, results)
    catalog_path = os.path.join(OUTPUT_DIR, "FY3_preset_catalog.json")
    os.makedirs(OUTPUT_DIR, exist_ok=True)
    with open(catalog_path, "w") as f:
        json.dump(catalog, f, indent=2)
    print(f"\n  Catalog: {catalog_path}")

    # Disk usage
    total_bytes = 0
    for root, dirs, files in os.walk(OUTPUT_DIR):
        for fn in files:
            if fn.endswith(".wav"):
                total_bytes += os.path.getsize(os.path.join(root, fn))

    print(f"  Total WAV size: {total_bytes / (1024**3):.2f} GB")
    print(f"\n  FY3 Zaytoven Collection ready! 🎹🔥")
    print("=" * 70)


if __name__ == "__main__":
    main()
