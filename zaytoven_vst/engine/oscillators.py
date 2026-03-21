"""FY3 Zaytoven Collection — Oscillator waveform generators."""

import numpy as np


def sine(freq: float, duration: float, sr: int = 48000) -> np.ndarray:
    """Pure sine wave."""
    t = np.arange(int(sr * duration)) / sr
    return np.sin(2 * np.pi * freq * t)


def sawtooth(freq: float, duration: float, sr: int = 48000) -> np.ndarray:
    """Band-limited sawtooth via additive synthesis (avoids aliasing)."""
    t = np.arange(int(sr * duration)) / sr
    n_harmonics = min(int(sr / (2 * freq)), 128)
    out = np.zeros_like(t)
    for k in range(1, n_harmonics + 1):
        out += ((-1) ** (k + 1)) * np.sin(2 * np.pi * k * freq * t) / k
    return out * (2 / np.pi)


def square(freq: float, duration: float, sr: int = 48000) -> np.ndarray:
    """Band-limited square wave (odd harmonics only)."""
    t = np.arange(int(sr * duration)) / sr
    n_harmonics = min(int(sr / (2 * freq)), 128)
    out = np.zeros_like(t)
    for k in range(1, n_harmonics + 1, 2):
        out += np.sin(2 * np.pi * k * freq * t) / k
    return out * (4 / np.pi)


def triangle(freq: float, duration: float, sr: int = 48000) -> np.ndarray:
    """Band-limited triangle wave."""
    t = np.arange(int(sr * duration)) / sr
    n_harmonics = min(int(sr / (2 * freq)), 128)
    out = np.zeros_like(t)
    for k in range(0, n_harmonics):
        n = 2 * k + 1
        out += ((-1) ** k) * np.sin(2 * np.pi * n * freq * t) / (n * n)
    return out * (8 / (np.pi ** 2))


def pulse(freq: float, duty: float, duration: float, sr: int = 48000) -> np.ndarray:
    """Pulse wave with variable duty cycle (0.0-1.0)."""
    t = np.arange(int(sr * duration)) / sr
    phase = (freq * t) % 1.0
    return np.where(phase < duty, 1.0, -1.0).astype(np.float64)


def noise(duration: float, sr: int = 48000, color: str = "white") -> np.ndarray:
    """Noise generator. color: 'white', 'pink', 'brown'."""
    n_samples = int(sr * duration)
    white = np.random.randn(n_samples)

    if color == "white":
        return white

    if color == "pink":
        # Voss-McCartney approximation for pink noise
        b = [0.99886, 0.99332, 0.96900, 0.86650, 0.55000, -0.76160, 0.11541]
        pink = np.zeros(n_samples)
        state = np.zeros(7)
        for i in range(n_samples):
            w = white[i]
            for j in range(7):
                state[j] = state[j] * b[j] + w * 0.3
            pink[i] = np.sum(state) + w * 0.5362
        mx = np.max(np.abs(pink))
        return pink / mx if mx > 0 else pink

    if color == "brown":
        brown = np.cumsum(white)
        brown -= np.mean(brown)
        mx = np.max(np.abs(brown))
        return brown / mx if mx > 0 else brown

    return white


def fm_oscillator(
    carrier_freq: float,
    mod_freq: float,
    mod_index: float,
    duration: float,
    sr: int = 48000,
    mod_envelope: np.ndarray | None = None,
    feedback: float = 0.0,
) -> np.ndarray:
    """FM synthesis oscillator with optional feedback.

    mod_index controls brightness, feedback adds self-modulation for richer harmonics.
    """
    n = int(sr * duration)
    t = np.arange(n) / sr
    if mod_envelope is not None:
        env = np.interp(
            np.linspace(0, 1, n),
            np.linspace(0, 1, len(mod_envelope)),
            mod_envelope,
        )
    else:
        env = np.ones(n)

    if feedback > 0:
        # Feedback FM — sample-by-sample for self-modulation
        out = np.zeros(n)
        phase_c = 0.0
        phase_m = 0.0
        prev_out = 0.0
        dt = 1.0 / sr
        for i in range(n):
            mod = mod_index * env[i] * np.sin(phase_m + feedback * prev_out)
            prev_out = np.sin(phase_c + mod)
            out[i] = prev_out
            phase_c += 2 * np.pi * carrier_freq * dt
            phase_m += 2 * np.pi * mod_freq * dt
        return out
    else:
        modulator = mod_index * env * np.sin(2 * np.pi * mod_freq * t)
        return np.sin(2 * np.pi * carrier_freq * t + modulator)


def harmonic_stack(
    freq: float,
    harmonics: list[float],
    amplitudes: list[float],
    duration: float,
    sr: int = 48000,
    detune_cents: float = 0.0,
) -> np.ndarray:
    """Additive synthesis: sum of harmonics at given amplitude ratios.

    detune_cents: if > 0, adds subtle random detuning per partial for analog character.
    """
    t = np.arange(int(sr * duration)) / sr
    out = np.zeros_like(t)
    for i, (h, a) in enumerate(zip(harmonics, amplitudes)):
        f = freq * h
        if f < sr / 2:  # Nyquist limit
            # Add subtle per-partial detuning for analog warmth
            if detune_cents > 0:
                drift = np.random.uniform(-detune_cents, detune_cents)
                f *= 2 ** (drift / 1200)
            out += a * np.sin(2 * np.pi * f * t)
    return out


def tonewheel(
    freq: float,
    duration: float,
    sr: int = 48000,
    grit: float = 0.04,
) -> np.ndarray:
    """Authentic Hammond tonewheel generator.

    Real tonewheels aren't pure sines — they have slight distortion from
    the electromagnetic pickup creating 2nd/3rd harmonic content, plus
    manufacturing imperfections causing level/phase drift.

    grit: amount of tonewheel harmonic distortion (0-0.2).
    """
    n = int(sr * duration)
    t = np.arange(n) / sr

    # Slight random frequency drift (manufacturing imprecision)
    drift_cents = np.random.uniform(-2, 2)
    actual_freq = freq * (2 ** (drift_cents / 1200))

    # Core sine
    fundamental = np.sin(2 * np.pi * actual_freq * t)

    # Electromagnetic pickup distortion creates even harmonics
    if actual_freq * 2 < sr / 2:
        h2 = np.sin(2 * np.pi * actual_freq * 2 * t) * grit
    else:
        h2 = 0

    if actual_freq * 3 < sr / 2:
        h3 = np.sin(2 * np.pi * actual_freq * 3 * t) * grit * 0.5
    else:
        h3 = 0

    # Subtle amplitude fluctuation (tonewheel wobble)
    wobble_rate = np.random.uniform(0.05, 0.15)
    wobble = 1.0 + 0.003 * np.sin(2 * np.pi * wobble_rate * t)

    return (fundamental + h2 + h3) * wobble


def supersaw(
    freq: float,
    duration: float,
    sr: int = 48000,
    n_voices: int = 7,
    spread: float = 0.5,
) -> np.ndarray:
    """7-voice detuned supersaw oscillator (Omnisphere-style).

    Creates the classic supersaw sound by layering multiple sawtooth oscillators
    with progressive detuning. The center voice is at exact pitch, with voices
    spread symmetrically above and below.

    n_voices: number of detuned voices (default 7).
    spread: detune spread 0-1 (0 = unison, 1 = wide ~50 cents total).
    """
    n_voices = max(1, min(n_voices, 15))
    n_samples = int(sr * duration)
    t = np.arange(n_samples) / sr
    out = np.zeros(n_samples)

    # Maximum total detune in cents at spread=1.0
    max_detune_cents = 50.0 * spread

    for i in range(n_voices):
        # Spread voices symmetrically around center
        if n_voices == 1:
            offset_cents = 0.0
        else:
            offset_cents = (i - (n_voices - 1) / 2) * (max_detune_cents / (n_voices - 1))

        voice_freq = freq * (2 ** (offset_cents / 1200))

        # Slight per-voice random phase offset for analog character
        phase_offset = np.random.uniform(0, 2 * np.pi)

        # Band-limited sawtooth via additive synthesis
        n_harmonics = min(int(sr / (2 * voice_freq)), 128)
        voice = np.zeros(n_samples)
        for k in range(1, n_harmonics + 1):
            voice += ((-1) ** (k + 1)) * np.sin(2 * np.pi * k * voice_freq * t + phase_offset * k) / k
        voice *= (2 / np.pi)

        # Center voice is slightly louder
        if i == n_voices // 2:
            voice *= 1.2

        out += voice

    # Normalize by voice count to prevent clipping
    out /= np.sqrt(n_voices)
    return out


def wavetable_morph(
    freq: float,
    duration: float,
    sr: int = 48000,
    morph: float = 0.5,
) -> np.ndarray:
    """Wavetable morphing oscillator: blends between sine, triangle, saw, and square.

    morph: 0.0 = pure sine, 0.33 = triangle, 0.67 = sawtooth, 1.0 = square.
    Values between these points crossfade smoothly between adjacent waveforms.
    """
    morph = np.clip(morph, 0.0, 1.0)

    # Generate all four waveforms
    wave_sine = sine(freq, duration, sr)
    wave_tri = triangle(freq, duration, sr)
    wave_saw = sawtooth(freq, duration, sr)
    wave_sq = square(freq, duration, sr)

    n = min(len(wave_sine), len(wave_tri), len(wave_saw), len(wave_sq))
    wave_sine = wave_sine[:n]
    wave_tri = wave_tri[:n]
    wave_saw = wave_saw[:n]
    wave_sq = wave_sq[:n]

    # Three crossfade regions:
    # 0.0-0.33: sine -> triangle
    # 0.33-0.67: triangle -> sawtooth
    # 0.67-1.0: sawtooth -> square
    if morph <= 1 / 3:
        t = morph * 3  # 0..1
        return wave_sine * (1 - t) + wave_tri * t
    elif morph <= 2 / 3:
        t = (morph - 1 / 3) * 3  # 0..1
        return wave_tri * (1 - t) + wave_saw * t
    else:
        t = (morph - 2 / 3) * 3  # 0..1
        return wave_saw * (1 - t) + wave_sq * t


def sub_oscillator(
    freq: float,
    duration: float,
    sr: int = 48000,
    shape: str = "sine",
    octave: int = 1,
) -> np.ndarray:
    """Sub-octave oscillator for adding weight and low-end.

    Generates a pure tone one or two octaves below the fundamental.
    shape: 'sine' (clean sub) or 'triangle' (slightly brighter sub).
    octave: 1 = one octave down, 2 = two octaves down.
    """
    sub_freq = freq / (2 ** max(1, min(octave, 2)))

    # Clamp to audible range
    if sub_freq < 15:
        return np.zeros(int(sr * duration))

    if shape == "triangle":
        return triangle(sub_freq, duration, sr)
    else:
        return sine(sub_freq, duration, sr)
