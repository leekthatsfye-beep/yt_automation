"""FY3 Zaytoven Collection — ADSR Envelope and LFO generators."""

import numpy as np


def adsr(
    attack: float = 0.01,
    decay: float = 0.1,
    sustain: float = 0.7,
    release: float = 0.3,
    duration: float = 3.0,
    sr: int = 44100,
) -> np.ndarray:
    """
    Generate ADSR envelope.

    attack/decay/release in seconds, sustain is level 0.0-1.0.
    Total length = duration (sustain fills the middle).
    """
    total = int(sr * duration)
    a_samples = int(sr * min(attack, duration * 0.3))
    d_samples = int(sr * min(decay, duration * 0.3))
    r_samples = int(sr * min(release, duration * 0.4))
    s_samples = max(0, total - a_samples - d_samples - r_samples)

    # Attack: 0 → 1
    a = np.linspace(0, 1, a_samples, endpoint=False) if a_samples > 0 else np.array([])

    # Decay: 1 → sustain
    d = np.linspace(1, sustain, d_samples, endpoint=False) if d_samples > 0 else np.array([])

    # Sustain: hold at sustain level
    s = np.full(s_samples, sustain) if s_samples > 0 else np.array([])

    # Release: sustain → 0
    r = np.linspace(sustain, 0, r_samples) if r_samples > 0 else np.array([])

    env = np.concatenate([a, d, s, r])

    # Pad or trim to exact duration
    if len(env) < total:
        env = np.pad(env, (0, total - len(env)), constant_values=0)
    else:
        env = env[:total]

    return env


def adsr_exp(
    attack: float = 0.01,
    decay: float = 0.1,
    sustain: float = 0.7,
    release: float = 0.3,
    duration: float = 3.0,
    sr: int = 44100,
) -> np.ndarray:
    """Exponential ADSR — more natural sounding decay/release curves."""
    total = int(sr * duration)
    a_samples = max(1, int(sr * min(attack, duration * 0.3)))
    d_samples = max(1, int(sr * min(decay, duration * 0.3)))
    r_samples = max(1, int(sr * min(release, duration * 0.4)))
    s_samples = max(0, total - a_samples - d_samples - r_samples)

    # Attack: exponential rise
    a = 1 - np.exp(-5 * np.linspace(0, 1, a_samples))

    # Decay: exponential fall to sustain
    d = sustain + (1 - sustain) * np.exp(-5 * np.linspace(0, 1, d_samples))

    # Sustain
    s = np.full(s_samples, sustain)

    # Release: exponential fall to 0
    r = sustain * np.exp(-5 * np.linspace(0, 1, r_samples))

    env = np.concatenate([a, d, s, r])
    if len(env) < total:
        env = np.pad(env, (0, total - len(env)), constant_values=0)
    return env[:total]


def lfo(
    rate: float = 5.0,
    depth: float = 1.0,
    shape: str = "sine",
    duration: float = 3.0,
    sr: int = 44100,
) -> np.ndarray:
    """
    Low-frequency oscillator for modulation.

    rate: Hz, depth: 0-1 amplitude, shape: sine/triangle/square
    Returns values centered around 0, range [-depth, +depth].
    """
    t = np.arange(int(sr * duration)) / sr

    if shape == "sine":
        out = np.sin(2 * np.pi * rate * t)
    elif shape == "triangle":
        out = 2 * np.abs(2 * ((rate * t) % 1) - 1) - 1
    elif shape == "square":
        out = np.sign(np.sin(2 * np.pi * rate * t))
    else:
        out = np.sin(2 * np.pi * rate * t)

    return out * depth


def percussive(
    attack: float = 0.001,
    decay: float = 1.0,
    duration: float = 3.0,
    sr: int = 44100,
    curve: float = 5.0,
) -> np.ndarray:
    """Fast attack + exponential decay. Good for bells, plucks, percussion."""
    total = int(sr * duration)
    a_samples = max(1, int(sr * attack))
    d_samples = total - a_samples

    a = np.linspace(0, 1, a_samples, endpoint=False)
    d = np.exp(-curve * np.linspace(0, 1, d_samples) * (duration / decay))

    env = np.concatenate([a, d])
    return env[:total]
