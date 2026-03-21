"""FY3 Zaytoven Collection — Utility functions."""

import numpy as np
import soundfile as sf
import os


SAMPLE_RATE = 48000


def midi_to_freq(note: int) -> float:
    """Convert MIDI note number to frequency. 60 = C4 = 261.63 Hz."""
    return 440.0 * (2.0 ** ((note - 69) / 12.0))


def normalize(audio: np.ndarray, peak: float = 0.95) -> np.ndarray:
    """Normalize audio to peak amplitude."""
    mx = np.max(np.abs(audio))
    if mx > 0:
        return audio * (peak / mx)
    return audio


def fade_in(audio: np.ndarray, duration: float = 0.005, sr: int = 44100) -> np.ndarray:
    """Apply fade-in to avoid click."""
    n = min(int(sr * duration), len(audio))
    fade = np.linspace(0, 1, n)
    out = audio.copy()
    out[:n] *= fade
    return out


def fade_out(audio: np.ndarray, duration: float = 0.02, sr: int = 44100) -> np.ndarray:
    """Apply fade-out to avoid click."""
    n = min(int(sr * duration), len(audio))
    fade = np.linspace(1, 0, n)
    out = audio.copy()
    out[-n:] *= fade
    return out


def fade_both(audio: np.ndarray, fade_in_ms: float = 5, fade_out_ms: float = 20, sr: int = 44100) -> np.ndarray:
    """Apply both fade-in and fade-out."""
    out = fade_in(audio, fade_in_ms / 1000, sr)
    return fade_out(out, fade_out_ms / 1000, sr)


def to_stereo(mono: np.ndarray) -> np.ndarray:
    """Convert mono to stereo (duplicate channels)."""
    return np.column_stack([mono, mono])


def stereo_spread(mono: np.ndarray, width: float = 0.3, sr: int = 44100) -> np.ndarray:
    """
    Create stereo from mono using Haas effect (slight delay on one channel).
    width: 0-1, controls delay amount (0 = mono, 1 = max spread ~15ms).
    """
    delay_samples = int(width * 0.015 * sr)  # max 15ms delay
    if delay_samples <= 0:
        return to_stereo(mono)

    left = mono
    right = np.pad(mono, (delay_samples, 0))[:len(mono)]
    return np.column_stack([left, right])


def mix_signals(*signals: np.ndarray, levels: list[float] | None = None) -> np.ndarray:
    """Mix multiple signals together at given levels."""
    if not signals:
        return np.array([])

    max_len = max(len(s) for s in signals)
    if levels is None:
        levels = [1.0 / len(signals)] * len(signals)

    out = np.zeros(max_len)
    for sig, level in zip(signals, levels):
        padded = np.pad(sig, (0, max_len - len(sig)))
        out += padded * level

    return out


def detune_unison(
    osc_func,
    freq: float,
    n_voices: int = 3,
    detune_cents: float = 10,
    duration: float = 3.0,
    sr: int = 44100,
) -> np.ndarray:
    """
    Generate unison voices with slight detuning for richness.
    """
    voices = []
    for i in range(n_voices):
        offset = (i - (n_voices - 1) / 2) * detune_cents
        f = freq * (2 ** (offset / 1200))
        voices.append(osc_func(f, duration, sr))

    return mix_signals(*voices)


def export_wav(
    audio: np.ndarray,
    filepath: str,
    sr: int = 48000,
    bit_depth: int = 24,
) -> None:
    """Export audio as WAV file."""
    os.makedirs(os.path.dirname(filepath), exist_ok=True)

    # Ensure stereo
    if audio.ndim == 1:
        audio = to_stereo(audio)

    # Normalize
    audio = normalize(audio, 0.95)

    # Apply fades
    for ch in range(audio.shape[1]):
        audio[:, ch] = fade_both(audio[:, ch], 3, 30, sr)

    subtype = f"PCM_{bit_depth}"
    sf.write(filepath, audio, sr, subtype=subtype)


def safe_filename(name: str) -> str:
    """Sanitize string for use as filename."""
    keep = set("abcdefghijklmnopqrstuvwxyzABCDEFGHIJKLMNOPQRSTUVWXYZ0123456789_- ")
    cleaned = "".join(c if c in keep else "_" for c in name)
    return "_".join(cleaned.split())  # collapse spaces to underscores
