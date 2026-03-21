"""FY3 Zaytoven Collection — Bass instrument model.

Supports: 808_sub, 808_dist, organ_bass, synth_bass, pluck_bass, deep_sub
Covers the full range of trap/hip-hop bass sounds from clean sub-bass
to distorted 808s, punchy synth bass, and organ bass.
"""

import numpy as np

from engine.oscillators import sine, sawtooth, square, pulse, noise
from engine.envelope import adsr, adsr_exp, percussive, lfo
from engine.filters import lowpass, highpass, bandpass
from engine.effects import reverb, saturate, eq_3band, compress
from engine.utils import midi_to_freq, normalize, mix_signals


class Bass:
    """Bass synthesizer covering 808s, organ bass, synth bass, and more."""

    def __init__(self, sr: int = 48000):
        self.sr = sr

    TYPES = ('808_sub', '808_dist', 'organ_bass', 'synth_bass', 'pluck_bass', 'deep_sub')

    DEFAULTS = {
        'bass_type': '808_sub',
        'pitch_drop': 2.0,
        'decay_time': 2.0,
        'filter_cutoff': 800,
        'distortion': 0.0,
        'attack': 0.005,
        'sustain': 0.7,
        'release': 0.3,
        'eq_low': 0,
        'eq_mid': 0,
    }

    def render(self, note: int, duration: float, params: dict | None = None) -> np.ndarray:
        """
        Render a single bass note.

        Args:
            note: MIDI note number (60 = C4).
            duration: Length in seconds.
            params: Dict of synthesis parameters (see DEFAULTS).

        Returns:
            Mono float64 numpy array.
        """
        p = {**self.DEFAULTS, **(params or {})}
        sr = self.sr
        freq = midi_to_freq(note)
        bass_type = p['bass_type']
        n_samples = int(sr * duration)

        if bass_type == '808_sub':
            signal = self._render_808_sub(freq, duration, p, sr)
        elif bass_type == '808_dist':
            signal = self._render_808_dist(freq, duration, p, sr)
        elif bass_type == 'organ_bass':
            signal = self._render_organ_bass(freq, duration, p, sr)
        elif bass_type == 'synth_bass':
            signal = self._render_synth_bass(freq, duration, p, sr)
        elif bass_type == 'pluck_bass':
            signal = self._render_pluck_bass(freq, duration, p, sr)
        elif bass_type == 'deep_sub':
            signal = self._render_deep_sub(freq, duration, p, sr)
        else:
            signal = self._render_808_sub(freq, duration, p, sr)

        signal = signal[:n_samples]

        # ── EQ ──────────────────────────────────────────────────────────
        if p['eq_low'] != 0 or p['eq_mid'] != 0:
            signal = eq_3band(
                signal, sr=sr,
                low_gain_db=p['eq_low'],
                mid_gain_db=p['eq_mid'],
                high_gain_db=-2,  # always cut highs on bass
            )

        signal = normalize(signal, 0.92)
        return signal

    # ── 808 Sub ─────────────────────────────────────────────────────────

    def _render_808_sub(self, freq, duration, p, sr):
        """808 sub: pure sine at fundamental, long decay, pitch envelope.

        Enhanced with:
        - Sub-harmonic generation (octave below fundamental for earth-shaking lows)
        - Better harmonic series (2nd, 3rd, 4th) with harmonic saturation model
        - Longer, cleaner sub tail with less distortion artifacts
        """
        n_samples = int(sr * duration)
        t = np.arange(n_samples) / sr

        # Pitch envelope: slight pitch drop at onset (the classic 808 slide)
        pitch_drop = p['pitch_drop']  # in semitones
        drop_time = 0.12  # 120ms pitch slide — longer for that classic 808 swoop
        pitch_env = np.ones(n_samples)
        drop_samples = int(sr * drop_time)
        if pitch_drop > 0 and drop_samples > 0:
            # Two-stage pitch drop: fast initial + slow settle (like real TR-808)
            drop_curve = 0.7 * np.exp(-12 * np.linspace(0, 1, drop_samples)) + \
                         0.3 * np.exp(-4 * np.linspace(0, 1, drop_samples))
            pitch_env[:drop_samples] = 1 + (2 ** (pitch_drop / 12) - 1) * drop_curve

        # Generate sine with pitch envelope via phase accumulation
        inst_freq = freq * pitch_env
        phase = np.cumsum(2 * np.pi * inst_freq / sr)
        raw = np.sin(phase)

        # Long exponential decay — use gentler curve for cleaner sub tail
        decay_time = max(p['decay_time'], 0.5)
        env = percussive(
            attack=max(p['attack'], 0.002),
            decay=decay_time,
            duration=duration,
            sr=sr,
            curve=2.8,  # gentler curve = longer, cleaner tail
        )
        raw = raw * env[:len(raw)]

        # --- Sub-harmonic generation (octave below fundamental) ---
        # Adds earth-shaking low end for big speaker systems
        sub_freq = freq / 2
        if sub_freq >= 15:  # only if audible
            sub_phase = np.cumsum(2 * np.pi * sub_freq * pitch_env / sr)
            sub_osc = np.sin(sub_phase)
            sub_env = percussive(attack=0.005, decay=decay_time * 1.3,
                                 duration=duration, sr=sr, curve=2.5)
            sub_osc = sub_osc[:len(sub_env)] * sub_env
            raw = raw + sub_osc[:len(raw)] * 0.12

        # --- Better harmonic series with saturation model ---
        # 2nd harmonic: warm presence
        h2 = np.sin(2 * phase) * 0.08
        h2_env = percussive(attack=0.002, decay=decay_time * 0.6,
                            duration=duration, sr=sr, curve=4.0)
        raw = raw + h2[:len(raw)] * h2_env[:len(raw)]

        # 3rd harmonic: adds body on smaller speakers
        if freq * 3 < sr / 2:
            h3 = np.sin(3 * phase) * 0.035
            h3_env = percussive(attack=0.002, decay=decay_time * 0.4,
                                duration=duration, sr=sr, curve=5.0)
            raw = raw + h3[:len(raw)] * h3_env[:len(raw)]

        # 4th harmonic: subtle upper presence
        if freq * 4 < sr / 2:
            h4 = np.sin(4 * phase) * 0.015
            h4_env = percussive(attack=0.002, decay=decay_time * 0.3,
                                duration=duration, sr=sr, curve=6.0)
            raw = raw + h4[:len(raw)] * h4_env[:len(raw)]

        # Gentle tape saturation for analog warmth (kept subtle for clean sub)
        raw = saturate(raw, drive=0.04, sat_type='tape')

        # Keep it clean and subby
        raw = lowpass(raw, min(p['filter_cutoff'], 600), sr=sr)
        raw = highpass(raw, 18, sr=sr)  # lower HPF for sub-harmonic

        return raw

    # ── 808 Distorted ───────────────────────────────────────────────────

    def _render_808_dist(self, freq, duration, p, sr):
        """808 distorted: 808 sub + heavy saturation/distortion for that gritty sound.

        Enhanced with:
        - Multi-stage saturation chain: soft clip -> tube -> tape (each stage
          adds different harmonic character)
        - Sub-harmonic generation preserved through distortion
        - Better harmonic series feeding the saturation
        - Parallel clean sub blended under the distortion for weight
        """
        n_samples = int(sr * duration)
        t = np.arange(n_samples) / sr

        # Pitch envelope
        pitch_drop = p['pitch_drop']
        drop_time = 0.06
        pitch_env = np.ones(n_samples)
        drop_samples = int(sr * drop_time)
        if pitch_drop > 0 and drop_samples > 0:
            drop_curve = np.exp(-8 * np.linspace(0, 1, drop_samples))
            pitch_env[:drop_samples] = 1 + (2 ** (pitch_drop / 12) - 1) * drop_curve

        inst_freq = freq * pitch_env
        phase = np.cumsum(2 * np.pi * inst_freq / sr)
        raw = np.sin(phase)

        # Rich harmonic content feeding the saturation stages
        raw = raw + 0.2 * np.sin(2 * phase)
        if freq * 3 < sr / 2:
            raw = raw + 0.08 * np.sin(3 * phase)
        if freq * 4 < sr / 2:
            raw = raw + 0.04 * np.sin(4 * phase)

        # Long decay
        decay_time = max(p['decay_time'], 0.5)
        env = percussive(
            attack=max(p['attack'], 0.002),
            decay=decay_time,
            duration=duration,
            sr=sr,
            curve=3.0,
        )
        raw = raw * env[:len(raw)]

        # --- Parallel clean sub for weight ---
        # Keep a clean sub-bass underneath all the distortion
        clean_sub = np.sin(phase) * 0.3
        clean_sub = clean_sub[:len(env)] * env[:len(clean_sub)]
        clean_sub = lowpass(clean_sub, 120, sr=sr)

        # --- Multi-stage saturation (soft clip -> tube -> tape) ---
        dist_amount = max(p['distortion'], 0.5)  # minimum 0.5 for gritty character
        # Stage 1: Soft clip — symmetric, adds odd harmonics (3rd, 5th, 7th)
        raw = saturate(raw, drive=dist_amount * 0.55, sat_type='soft')
        # Stage 2: Tube — asymmetric, adds even harmonics (2nd, 4th) for warmth
        raw = saturate(raw, drive=dist_amount * 0.35, sat_type='tube')
        # Stage 3: Tape — gentle compression and high-frequency rolloff
        raw = saturate(raw, drive=dist_amount * 0.2, sat_type='tape')

        # Blend clean sub back in under the distortion
        raw = raw + clean_sub[:len(raw)]

        # Filter to shape the distortion
        cutoff = min(p['filter_cutoff'], 2500)
        raw = lowpass(raw, cutoff, sr=sr, resonance=0.15)

        # Compression to keep distorted 808 punchy and even
        raw = compress(raw, threshold_db=-8, ratio=4.0, attack_ms=2, release_ms=40, sr=sr)

        raw = highpass(raw, 22, sr=sr)
        return raw

    # ── Organ Bass ──────────────────────────────────────────────────────

    def _render_organ_bass(self, freq, duration, p, sr):
        """Organ bass: low drawbar organ with fundamental + sub-octave, slight overdrive."""
        n_samples = int(sr * duration)

        # Drawbar simulation — fundamental + sub-octave + slight 3rd harmonic
        fundamental = sine(freq, duration, sr)
        sub = sine(freq / 2, duration, sr) * 0.65
        third_harmonic = sine(freq * 3, duration, sr) * 0.08
        # Slight 2nd harmonic for warmth
        second_harmonic = sine(freq * 2, duration, sr) * 0.12

        raw = fundamental + sub[:len(fundamental)] + third_harmonic[:len(fundamental)] + second_harmonic[:len(fundamental)]

        # Organ-like envelope: fast attack, sustained
        env = adsr_exp(
            attack=max(p['attack'], 0.008),
            decay=0.1,
            sustain=max(p['sustain'], 0.85),
            release=p['release'],
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Slight key click at onset
        click = noise(duration, sr, color='white') * 0.04
        click_env = percussive(attack=0.001, decay=0.015, duration=duration, sr=sr, curve=20.0)
        click = click[:len(click_env)] * click_env
        raw = raw + click[:len(raw)]

        # Slight overdrive for that organ grit
        overdrive = max(p['distortion'], 0.12)
        raw = saturate(raw, drive=overdrive, sat_type='tube')

        # Filter — organ bass is warm but not too dark
        raw = lowpass(raw, min(p['filter_cutoff'], 2000), sr=sr)
        raw = highpass(raw, 30, sr=sr)

        # Gentle EQ boost in low-mids
        raw = eq_3band(raw, sr=sr, low_gain_db=1, mid_gain_db=2, high_gain_db=-2)

        return raw

    # ── Synth Bass ──────────────────────────────────────────────────────

    def _render_synth_bass(self, freq, duration, p, sr):
        """Synth bass: filtered sawtooth, punchy attack, Moog-style resonant filter.

        Enhanced with Moog-style resonant filter sweep: the filter cutoff
        sweeps from a bright initial value down to the sustained cutoff,
        with high resonance for that classic squelchy character.
        """
        n_samples = int(sr * duration)
        t = np.arange(n_samples) / sr

        # Punchy sawtooth
        raw = sawtooth(freq, duration, sr)

        # Add a sub sine layer for weight
        sub = sine(freq, duration, sr) * 0.3
        raw = raw + sub[:len(raw)]

        # Punchy envelope with fast attack
        env = adsr_exp(
            attack=max(p['attack'], 0.003),
            decay=0.15,
            sustain=p['sustain'],
            release=p['release'],
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # --- Moog-style resonant filter sweep ---
        # Filter cutoff sweeps from bright initial value to sustained cutoff
        # with high resonance for that classic squelchy bass character
        base_cutoff = min(p['filter_cutoff'], 1800)
        sweep_start = min(base_cutoff * 4, sr * 0.45)  # bright initial cutoff
        sweep_time = 0.15  # 150ms sweep time
        resonance = 0.55  # high resonance for Moog squelch

        # Calculate sweep envelope
        sweep_samples = int(sr * sweep_time)
        cutoff_env = np.ones(n_samples) * base_cutoff
        if sweep_samples > 0 and sweep_samples < n_samples:
            sweep_curve = np.exp(-6 * np.linspace(0, 1, sweep_samples))
            cutoff_env[:sweep_samples] = base_cutoff + (sweep_start - base_cutoff) * sweep_curve

        # Apply sweep in blocks for time-varying filter
        block_size = sr // 50  # 20ms blocks
        out = np.zeros(n_samples)
        for start in range(0, n_samples, block_size):
            end = min(start + block_size, n_samples)
            mid = (start + end) // 2
            cf = np.clip(cutoff_env[min(mid, n_samples - 1)], 30, sr * 0.45)
            block = raw[start:end]
            padded = np.pad(block, (0, max(0, 512 - len(block))))
            out[start:end] = lowpass(padded, cf, sr=sr, resonance=resonance)[:len(block)]

        raw = out

        # Slight saturation for fatness
        if p['distortion'] > 0:
            raw = saturate(raw, drive=p['distortion'] * 0.4, sat_type='soft')

        raw = highpass(raw, 30, sr=sr)

        # Compression for punch
        raw = compress(raw, threshold_db=-10, ratio=3.0, attack_ms=3, release_ms=50, sr=sr)

        return raw

    # ── Pluck Bass ──────────────────────────────────────────────────────

    def _render_pluck_bass(self, freq, duration, p, sr):
        """Pluck bass: fast attack/decay, filtered pulse wave — snappy and percussive."""
        n_samples = int(sr * duration)

        # Pulse wave for hollow character
        raw = pulse(freq, 0.35, duration, sr)

        # Add sine fundamental for body
        body = sine(freq, duration, sr) * 0.4
        raw = raw + body[:len(raw)]

        # Percussive envelope — short and snappy
        pluck_decay = min(p['decay_time'] * 0.4, 0.5)
        env = percussive(
            attack=0.002,
            decay=pluck_decay,
            duration=duration,
            sr=sr,
            curve=5.0,
        )
        raw = raw[:len(env)] * env

        # Filter envelope — opens briefly at onset then closes
        raw_len = len(raw)
        # Quick filter sweep from bright to dark
        filter_env = percussive(attack=0.002, decay=0.08, duration=duration, sr=sr, curve=8.0)
        cutoff_max = min(p['filter_cutoff'] * 2, 4000)
        cutoff_min = 300
        # Block-based filter with envelope
        block_size = sr // 40
        out = np.zeros(raw_len)
        for start in range(0, raw_len, block_size):
            end = min(start + block_size, raw_len)
            mid = (start + end) // 2
            env_val = filter_env[min(mid, len(filter_env) - 1)]
            cf = cutoff_min + (cutoff_max - cutoff_min) * env_val
            cf = max(cf, 80)
            block = raw[start:end]
            padded = np.pad(block, (0, max(0, 512 - len(block))))
            out[start:end] = lowpass(padded, cf, sr=sr)[:len(block)]

        raw = out

        # Subtle click transient
        click = noise(duration, sr, color='white') * 0.05
        click_env = percussive(attack=0.001, decay=0.01, duration=duration, sr=sr, curve=25.0)
        click = click[:len(click_env)] * click_env
        raw = raw + click[:len(raw)]

        raw = highpass(raw, 35, sr=sr)
        return raw

    # ── Deep Sub ────────────────────────────────────────────────────────

    def _render_deep_sub(self, freq, duration, p, sr):
        """Deep sub: very clean sub-bass sine, minimal harmonics."""
        n_samples = int(sr * duration)

        # Pure sine — as clean as possible
        raw = sine(freq, duration, sr)

        # Very subtle 2nd harmonic just to give it presence on small speakers
        h2 = sine(freq * 2, duration, sr) * 0.04
        raw = raw + h2[:len(raw)]

        # Smooth envelope
        env = adsr_exp(
            attack=max(p['attack'], 0.01),
            decay=0.2,
            sustain=max(p['sustain'], 0.9),
            release=max(p['release'], 0.4),
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Very low cutoff to keep only the sub
        cutoff = min(p['filter_cutoff'], 350)
        raw = lowpass(raw, cutoff, sr=sr)

        # Remove rumble below hearing threshold
        raw = highpass(raw, 20, sr=sr)

        # Light compression to keep it even
        raw = compress(raw, threshold_db=-6, ratio=2.0, attack_ms=10, release_ms=60, sr=sr)

        return raw
