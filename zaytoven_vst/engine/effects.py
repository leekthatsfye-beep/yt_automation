"""FY3 Zaytoven Collection — Audio effects processors."""

import numpy as np
from scipy import signal as sig


def reverb(
    audio: np.ndarray,
    sr: int = 48000,
    room_size: float = 0.5,
    damping: float = 0.5,
    wet: float = 0.3,
) -> np.ndarray:
    """
    Dense stereo reverb — 8 comb filters + 4 allpass for lush, professional tail.
    room_size: 0-1, damping: 0-1, wet: 0-1 mix.
    """
    if wet <= 0:
        return audio

    # 8 comb filter delays (scaled for 48kHz) — spread for density
    base_delays = [1557, 1617, 1491, 1422, 1277, 1356, 1188, 1116]
    sr_ratio = sr / 44100.0
    delays = [int(d * sr_ratio * (0.5 + room_size)) for d in base_delays]

    # 4 allpass delays for diffusion
    ap_delays = [int(d * sr_ratio) for d in [225, 556, 441, 341]]

    feedback = 0.72 + room_size * 0.23  # 0.72 - 0.95
    damp = damping * 0.4

    n = len(audio)
    tail = int(sr * room_size * 3)  # longer reverb tail
    padded = np.pad(audio, (0, tail))
    total = len(padded)

    # Parallel comb filters with damping
    comb_out = np.zeros(total)
    for delay in delays:
        buf = np.zeros(total)
        filt_state = 0.0
        for i in range(total):
            if i >= delay:
                filt_state = buf[i - delay] * (1 - damp) + filt_state * damp
                buf[i] = padded[i] + filt_state * feedback
            else:
                buf[i] = padded[i]
        comb_out += buf / len(delays)

    # Series allpass filters for diffusion
    out = comb_out
    for delay in ap_delays:
        buf = np.zeros(total)
        g = 0.5
        for i in range(total):
            if i >= delay:
                buf[i] = -g * out[i] + out[i - delay] + g * buf[i - delay]
            else:
                buf[i] = out[i]
        out = buf

    # Trim and mix — preserve natural tail length
    out_len = min(n + int(sr * 1.0), total)
    out = out[:out_len]
    dry = np.pad(audio, (0, max(0, out_len - n)))
    mixed = dry[:out_len] * (1 - wet) + out[:out_len] * wet

    return mixed[:n]


def chorus(
    audio: np.ndarray,
    sr: int = 48000,
    rate: float = 1.5,
    depth: float = 0.003,
    mix: float = 0.3,
) -> np.ndarray:
    """
    Chorus effect with smooth interpolated delay line.
    rate: LFO Hz, depth: max delay in seconds, mix: wet/dry.
    """
    if mix <= 0:
        return audio

    n = len(audio)
    max_delay = depth * sr
    t = np.arange(n) / sr

    # Two LFOs slightly offset for richer modulation
    lfo1 = (np.sin(2 * np.pi * rate * t) + 1) / 2
    lfo2 = (np.sin(2 * np.pi * rate * 1.12 * t + 0.7) + 1) / 2

    wet_signal = np.zeros(n)
    for i in range(n):
        # Voice 1
        delay1 = lfo1[i] * max_delay + max_delay * 0.5
        idx1 = i - delay1
        if idx1 >= 0 and idx1 < n - 1:
            i_floor = int(idx1)
            frac = idx1 - i_floor
            wet_signal[i] += audio[i_floor] * (1 - frac) + audio[min(i_floor + 1, n - 1)] * frac
        # Voice 2
        delay2 = lfo2[i] * max_delay + max_delay * 0.5
        idx2 = i - delay2
        if idx2 >= 0 and idx2 < n - 1:
            i_floor = int(idx2)
            frac = idx2 - i_floor
            wet_signal[i] += audio[i_floor] * (1 - frac) + audio[min(i_floor + 1, n - 1)] * frac

    wet_signal *= 0.5  # average the two voices

    return audio * (1 - mix) + wet_signal * mix


def delay_effect(
    audio: np.ndarray,
    sr: int = 44100,
    time_ms: float = 250,
    feedback: float = 0.3,
    mix: float = 0.25,
) -> np.ndarray:
    """Echo/delay effect."""
    if mix <= 0:
        return audio

    delay_samples = int(sr * time_ms / 1000)
    n = len(audio)
    out = audio.copy()

    for i in range(delay_samples, n):
        out[i] += out[i - delay_samples] * feedback

    return audio * (1 - mix) + out * mix


def saturate(
    audio: np.ndarray,
    drive: float = 0.3,
    sat_type: str = "soft",
) -> np.ndarray:
    """
    Saturation/distortion.
    drive: 0-1 (0 = clean, 1 = heavy).
    sat_type: 'soft' (tanh), 'tube' (asymmetric), 'tape' (gentle).
    """
    if drive <= 0:
        return audio

    gain = 1 + drive * 10

    if sat_type == "soft":
        return np.tanh(audio * gain) / np.tanh(gain)
    elif sat_type == "tube":
        # Asymmetric clipping (more even harmonics)
        x = audio * gain
        pos = np.where(x >= 0, np.tanh(x), 0)
        neg = np.where(x < 0, np.tanh(x * 0.7) * 1.2, 0)
        out = pos + neg
        mx = np.max(np.abs(out))
        return out / mx if mx > 0 else out
    elif sat_type == "tape":
        x = audio * (1 + drive * 3)
        return x / (1 + np.abs(x))
    else:
        return np.tanh(audio * gain) / np.tanh(gain)


def eq_3band(
    audio: np.ndarray,
    sr: int = 44100,
    low_gain_db: float = 0,
    mid_gain_db: float = 0,
    high_gain_db: float = 0,
    low_freq: float = 300,
    high_freq: float = 3000,
) -> np.ndarray:
    """Simple 3-band EQ using crossover filters."""
    nyq = sr / 2
    low_freq = min(low_freq, nyq * 0.9)
    high_freq = min(high_freq, nyq * 0.9)

    # Split into 3 bands
    b_lo, a_lo = sig.butter(2, low_freq / nyq, btype="low")
    b_hi, a_hi = sig.butter(2, high_freq / nyq, btype="high")

    low_band = sig.lfilter(b_lo, a_lo, audio)
    high_band = sig.lfilter(b_hi, a_hi, audio)
    mid_band = audio - low_band - high_band

    # Apply gains
    low_gain = 10 ** (low_gain_db / 20)
    mid_gain = 10 ** (mid_gain_db / 20)
    high_gain = 10 ** (high_gain_db / 20)

    return low_band * low_gain + mid_band * mid_gain + high_band * high_gain


def compress(
    audio: np.ndarray,
    threshold_db: float = -12,
    ratio: float = 4.0,
    attack_ms: float = 5,
    release_ms: float = 50,
    sr: int = 44100,
) -> np.ndarray:
    """Simple compressor."""
    threshold = 10 ** (threshold_db / 20)
    attack_coeff = np.exp(-1 / (sr * attack_ms / 1000))
    release_coeff = np.exp(-1 / (sr * release_ms / 1000))

    envelope = np.zeros(len(audio))
    env = 0.0

    for i in range(len(audio)):
        level = abs(audio[i])
        if level > env:
            env = attack_coeff * env + (1 - attack_coeff) * level
        else:
            env = release_coeff * env + (1 - release_coeff) * level
        envelope[i] = env

    gain = np.ones(len(audio))
    above = envelope > threshold
    gain[above] = threshold * (envelope[above] / threshold) ** (1 / ratio - 1)

    # Makeup gain
    out = audio * gain
    mx = np.max(np.abs(out))
    if mx > 0:
        out *= 0.9 / mx

    return out


def tremolo(
    audio: np.ndarray,
    sr: int = 44100,
    rate: float = 5.0,
    depth: float = 0.5,
) -> np.ndarray:
    """Amplitude modulation (tremolo)."""
    t = np.arange(len(audio)) / sr
    mod = 1 - depth * (1 + np.sin(2 * np.pi * rate * t)) / 2
    return audio * mod


def analog_warmth(
    audio: np.ndarray,
    sr: int = 48000,
    warmth: float = 0.5,
) -> np.ndarray:
    """Apply analog warmth — subtle harmonic excitation + tape character.

    Enhanced simulation of analog signal path with:
    - Tape saturation with more aggressive character
    - Subtle random pitch drift (slow LFO, +/-0.5 cents) for analog wobble
    - Gentle tape hiss noise floor
    - Harmonic excitation (2nd + 3rd harmonics)
    - High-frequency rolloff

    warmth: 0-1 intensity.
    """
    if warmth <= 0:
        return audio

    n = len(audio)
    t = np.arange(n) / sr

    # 1. More aggressive tape saturation character
    warm = saturate(audio, drive=warmth * 0.12, sat_type='tape')

    # 2. Subtle harmonic exciter — add 2nd and 3rd harmonic content
    # Simulates tube/transformer coloration
    squared = audio * audio * np.sign(audio) * warmth * 0.04
    cubed = audio * audio * audio * warmth * 0.02
    warm = warm + squared + cubed

    # 3. Subtle random pitch drift via slow LFO (+/-0.5 cents over time)
    # This simulates tape speed fluctuation and analog oscillator drift
    drift_rate = np.random.uniform(0.03, 0.12)  # very slow LFO
    drift_cents = 0.5 * warmth
    drift_lfo = drift_cents * np.sin(2 * np.pi * drift_rate * t + np.random.uniform(0, 6.28))
    # Apply pitch drift as a very subtle time-domain shift via interpolation
    drift_samples = drift_lfo * sr / (1200 * 440)  # convert cents to sample offset
    read_pos = np.arange(n, dtype=np.float64) + drift_samples
    read_pos = np.clip(read_pos, 0, n - 1)
    idx_floor = np.floor(read_pos).astype(int)
    idx_ceil = np.minimum(idx_floor + 1, n - 1)
    frac = read_pos - idx_floor
    warm = warm[idx_floor] * (1 - frac) + warm[idx_ceil] * frac

    # 4. Gentle tape hiss layer (very quiet noise floor for analog character)
    hiss_level = warmth * 0.003  # very subtle
    hiss = np.random.randn(n) * hiss_level
    # Shape hiss to upper-mid range like real tape
    nyq = sr / 2
    if 2000 < nyq and 12000 < nyq:
        b_hi, a_hi = sig.butter(1, 2000 / nyq, btype='high')
        hiss = sig.lfilter(b_hi, a_hi, hiss)
        b_lo, a_lo = sig.butter(1, min(12000, nyq * 0.95) / nyq, btype='low')
        hiss = sig.lfilter(b_lo, a_lo, hiss)
    warm = warm + hiss

    # 5. Very gentle high-shelf rolloff (analog circuits roll off above ~16kHz)
    if 16000 < nyq:
        b, a = sig.butter(1, 16000 / nyq, btype='low')
        warm = sig.lfilter(b, a, warm)

    return warm


def stereo_widener(
    audio: np.ndarray,
    sr: int = 48000,
    width: float = 1.5,
) -> np.ndarray:
    """Mid-side stereo widener.

    Separates signal into mid (center) and side (stereo) components,
    then adjusts the balance to widen or narrow the stereo image.

    For mono input, creates pseudo-stereo using a short delay and returns
    the widened mono signal (mid channel).

    audio: mono or stereo (N,2) array.
    width: 1.0 = no change, >1.0 = wider, <1.0 = narrower, 0 = full mono.
    """
    width = max(0.0, min(3.0, width))

    if audio.ndim == 1:
        # Mono input: create pseudo-stereo via Haas effect (short delay)
        n = len(audio)
        delay_samples = int(sr * 0.0003 * width)  # 0.3ms per unit of width
        if delay_samples <= 0:
            return audio

        # Create a delayed copy with slight filtering
        delayed = np.zeros(n)
        if delay_samples < n:
            delayed[delay_samples:] = audio[:n - delay_samples]
        # Slight high-shelf boost on delayed copy for spatial cues
        nyq = sr / 2
        if 3000 < nyq:
            b, a = sig.butter(1, 3000 / nyq, btype='high')
            side_component = sig.lfilter(b, a, delayed) * 0.15 * (width - 1.0)
        else:
            side_component = delayed * 0.1 * (width - 1.0)

        return audio + side_component

    # Stereo input: mid-side processing
    left = audio[:, 0]
    right = audio[:, 1]

    mid = (left + right) * 0.5
    side = (left - right) * 0.5

    # Adjust side level relative to mid
    side *= width

    new_left = mid + side
    new_right = mid - side

    result = np.column_stack([new_left, new_right])
    return result


def harmonic_exciter(
    audio: np.ndarray,
    sr: int = 48000,
    amount: float = 0.3,
    frequency: float = 3000.0,
) -> np.ndarray:
    """Harmonic exciter for presence and air.

    Generates upper harmonics from the signal above a given frequency
    and blends them back in. This adds the "air" and "sparkle" that
    makes sounds feel present and expensive, like Omnisphere's exciter.

    amount: exciter intensity 0-1.
    frequency: high-pass cutoff for the exciter input (Hz).
    """
    if amount <= 0:
        return audio

    n = len(audio)
    nyq = sr / 2
    if frequency >= nyq * 0.95:
        return audio

    # 1. Extract high-frequency content
    b, a = sig.butter(2, frequency / nyq, btype='high')
    highs = sig.lfilter(b, a, audio)

    # 2. Generate harmonics through waveshaping (soft distortion of highs only)
    # Second harmonic (even) — warm presence
    h2 = highs * highs * np.sign(highs)
    # Third harmonic (odd) — bright air
    h3 = highs * highs * highs

    # 3. Mix harmonics
    excited = h2 * 0.6 + h3 * 0.4

    # 4. High-pass the result to keep only the new upper content
    hp_freq = min(frequency * 1.5, nyq * 0.9)
    b2, a2 = sig.butter(2, hp_freq / nyq, btype='high')
    excited = sig.lfilter(b2, a2, excited)

    # 5. Normalize excited signal and blend
    mx = np.max(np.abs(excited))
    if mx > 0:
        excited /= mx

    return audio + excited * amount * 0.15


def multiband_compress(
    audio: np.ndarray,
    sr: int = 48000,
    low_threshold_db: float = -12.0,
    mid_threshold_db: float = -10.0,
    high_threshold_db: float = -14.0,
    low_ratio: float = 3.0,
    mid_ratio: float = 2.5,
    high_ratio: float = 4.0,
    low_freq: float = 250.0,
    high_freq: float = 4000.0,
) -> np.ndarray:
    """3-band multiband compressor for balanced dynamics.

    Splits the signal into low, mid, and high bands, compresses each
    independently, then recombines. This prevents bass from pumping
    the highs and gives Omnisphere-style polished dynamics.

    low_freq: crossover between low and mid bands (Hz).
    high_freq: crossover between mid and high bands (Hz).
    """
    nyq = sr / 2
    low_freq = min(low_freq, nyq * 0.9)
    high_freq = min(high_freq, nyq * 0.9)

    if low_freq >= high_freq:
        return compress(audio, threshold_db=mid_threshold_db, ratio=mid_ratio, sr=sr)

    # Split into 3 bands
    b_lo, a_lo = sig.butter(3, low_freq / nyq, btype='low')
    b_hi, a_hi = sig.butter(3, high_freq / nyq, btype='high')

    low_band = sig.lfilter(b_lo, a_lo, audio)
    high_band = sig.lfilter(b_hi, a_hi, audio)
    mid_band = audio - low_band - high_band

    # Compress each band independently
    low_comp = compress(low_band, threshold_db=low_threshold_db,
                        ratio=low_ratio, attack_ms=10, release_ms=80, sr=sr)
    mid_comp = compress(mid_band, threshold_db=mid_threshold_db,
                        ratio=mid_ratio, attack_ms=5, release_ms=50, sr=sr)
    high_comp = compress(high_band, threshold_db=high_threshold_db,
                         ratio=high_ratio, attack_ms=2, release_ms=40, sr=sr)

    # Recombine
    return low_comp + mid_comp + high_comp
