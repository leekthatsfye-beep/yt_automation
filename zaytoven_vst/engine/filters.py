"""FY3 Zaytoven Collection — Digital filters (Butterworth IIR)."""

import numpy as np
from scipy import signal as sig


def lowpass(
    audio: np.ndarray,
    cutoff: float,
    sr: int = 48000,
    order: int = 4,
    resonance: float = 0.0,
) -> np.ndarray:
    """
    Butterworth low-pass filter.

    resonance 0-1 adds a peak at cutoff (simulates analog filter resonance).
    """
    nyq = sr / 2
    cutoff = min(cutoff, nyq * 0.95)
    if cutoff <= 20:
        return np.zeros_like(audio)

    b, a = sig.butter(order, cutoff / nyq, btype="low")
    out = sig.lfilter(b, a, audio)

    if resonance > 0:
        # Add resonant peak via narrow bandpass
        bw = max(cutoff * 0.05, 20)
        lo = max(cutoff - bw, 20) / nyq
        hi = min(cutoff + bw, nyq * 0.95) / nyq
        if lo < hi:
            bp_b, bp_a = sig.butter(2, [lo, hi], btype="band")
            peak = sig.lfilter(bp_b, bp_a, audio)
            out = out + peak * resonance * 3

    return out


def highpass(
    audio: np.ndarray,
    cutoff: float,
    sr: int = 48000,
    order: int = 4,
) -> np.ndarray:
    """Butterworth high-pass filter."""
    nyq = sr / 2
    cutoff = max(cutoff, 10)
    cutoff = min(cutoff, nyq * 0.95)
    b, a = sig.butter(order, cutoff / nyq, btype="high")
    return sig.lfilter(b, a, audio)


def bandpass(
    audio: np.ndarray,
    low: float,
    high: float,
    sr: int = 48000,
    order: int = 4,
) -> np.ndarray:
    """Butterworth band-pass filter."""
    nyq = sr / 2
    low = max(low, 10) / nyq
    high = min(high, nyq * 0.95) / nyq
    if low >= high:
        return audio
    b, a = sig.butter(order, [low, high], btype="band")
    return sig.lfilter(b, a, audio)


def notch(
    audio: np.ndarray,
    freq: float,
    q: float = 30.0,
    sr: int = 48000,
) -> np.ndarray:
    """Notch filter to remove a specific frequency."""
    nyq = sr / 2
    w0 = freq / nyq
    if w0 >= 1.0 or w0 <= 0:
        return audio
    b, a = sig.iirnotch(w0, q)
    return sig.lfilter(b, a, audio)


def filter_sweep(
    audio: np.ndarray,
    start_cutoff: float,
    end_cutoff: float,
    sr: int = 48000,
    order: int = 2,
    ftype: str = "low",
) -> np.ndarray:
    """
    Time-varying filter sweep (cutoff changes linearly over duration).
    Processes audio in overlapping blocks for smooth sweep.
    """
    n = len(audio)
    block_size = sr // 20  # 50ms blocks
    out = np.zeros(n)
    cutoffs = np.linspace(start_cutoff, end_cutoff, n // block_size + 1)
    nyq = sr / 2

    for i, start in enumerate(range(0, n, block_size)):
        end = min(start + block_size, n)
        block = audio[start:end]
        cf = np.clip(cutoffs[min(i, len(cutoffs) - 1)], 20, nyq * 0.95)
        b, a = sig.butter(order, cf / nyq, btype=ftype)
        out[start:end] = sig.lfilter(b, a, block)

    return out
