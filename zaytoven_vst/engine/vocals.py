"""FY3 Zaytoven Collection — Vocal synthesizer instrument model.

Supports: vocal_chop, vocal_pad, choir, adlib, vocal_rise, vocal_drone
Renders vocal textures, chops, pads, choir stacks, and ad-lib effects
using formant synthesis (bandpass filter banks simulating vowel sounds),
breathy noise layers, and pitched oscillator sources.
"""

import numpy as np

from engine.oscillators import sine, sawtooth, pulse, noise, harmonic_stack
from engine.envelope import adsr, adsr_exp, percussive, lfo
from engine.filters import lowpass, highpass, bandpass, filter_sweep
from engine.effects import reverb, chorus, delay_effect, saturate, eq_3band, compress
from engine.utils import midi_to_freq, normalize, mix_signals, detune_unison


# ── Formant frequency tables (F1, F2, F3) for each vowel ─────────────
_FORMANTS = {
    'ah': [730, 1090, 2440],
    'ooh': [300, 870, 2240],
    'ee': [270, 2290, 3010],
    'oh': [570, 840, 2410],
    'eh': [530, 1840, 2480],
}

# Approximate bandwidths for each formant (proportional to center freq)
_FORMANT_BW_RATIO = 0.12


class Vocals:
    """Vocal synthesizer for chops, pads, choirs, ad-libs, risers, and drones."""

    TYPES = (
        'vocal_chop', 'vocal_pad', 'choir',
        'adlib', 'vocal_rise', 'vocal_drone',
    )

    def __init__(self, sr: int = 48000):
        self.sr = sr

    DEFAULTS = {
        'vocal_type': 'vocal_chop',
        'vowel': 'ah',
        'formant_shift': 0,
        'breathiness': 0.3,
        'vibrato_rate': 5.0,
        'vibrato_depth': 0.02,
        'n_voices': 1,
        'detune_cents': 10,
        'reverb_wet': 0.3,
        'reverb_size': 0.5,
        'delay_mix': 0.0,
        'delay_ms': 300,
        'distortion': 0.0,
        'eq_low': 0,
        'eq_mid': 0,
        'eq_high': 0,
        'stereo_width': 0.3,
    }

    def render(self, note: int, duration: float, params: dict | None = None) -> np.ndarray:
        """
        Render a single vocal note.

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
        vtype = p['vocal_type']
        n_samples = int(sr * duration)

        if vtype == 'vocal_chop':
            signal = self._render_vocal_chop(freq, duration, p, sr)
        elif vtype == 'vocal_pad':
            signal = self._render_vocal_pad(freq, duration, p, sr)
        elif vtype == 'choir':
            signal = self._render_choir(freq, duration, p, sr)
        elif vtype == 'adlib':
            signal = self._render_adlib(freq, duration, p, sr)
        elif vtype == 'vocal_rise':
            signal = self._render_vocal_rise(freq, duration, p, sr)
        elif vtype == 'vocal_drone':
            signal = self._render_vocal_drone(freq, duration, p, sr)
        else:
            signal = self._render_vocal_chop(freq, duration, p, sr)

        signal = signal[:n_samples]

        # ── Distortion ─────────────────────────────────────────────────
        if p['distortion'] > 0:
            signal = saturate(signal, drive=p['distortion'] * 0.4, sat_type='tape')

        # ── EQ ─────────────────────────────────────────────────────────
        if p['eq_low'] != 0 or p['eq_mid'] != 0 or p['eq_high'] != 0:
            signal = eq_3band(
                signal, sr=sr,
                low_gain_db=p['eq_low'],
                mid_gain_db=p['eq_mid'],
                high_gain_db=p['eq_high'],
            )

        # ── Delay ──────────────────────────────────────────────────────
        if p['delay_mix'] > 0:
            signal = delay_effect(
                signal, sr=sr,
                time_ms=p['delay_ms'],
                feedback=0.3,
                mix=p['delay_mix'],
            )

        # ── Reverb ─────────────────────────────────────────────────────
        if p['reverb_wet'] > 0:
            signal = reverb(
                signal, sr=sr,
                room_size=p['reverb_size'],
                damping=0.45,
                wet=p['reverb_wet'],
            )

        signal = normalize(signal, 0.92)
        return signal

    # ── Formant helpers ───────────────────────────────────────────────

    def _get_formants(self, vowel: str, shift_semitones: float) -> list[float]:
        """Return formant frequencies for the given vowel, shifted by semitones."""
        base = _FORMANTS.get(vowel, _FORMANTS['ah'])
        ratio = 2 ** (shift_semitones / 12)
        return [f * ratio for f in base]

    def _apply_formants(
        self,
        source: np.ndarray,
        formant_freqs: list[float],
        sr: int,
    ) -> np.ndarray:
        """
        Apply formant filtering to a source signal.

        Each formant is a bandpass filter centered on the formant frequency.
        The outputs are summed with decreasing amplitude for higher formants.
        Enhanced with wider bandwidth for smoother, more natural formants.
        """
        n = len(source)
        out = np.zeros(n)
        nyq = sr / 2
        # Amplitude weights: F1 strongest, F2 moderate, F3 presence
        weights = [1.0, 0.7, 0.45]

        for i, fc in enumerate(formant_freqs):
            if fc >= nyq * 0.95:
                continue
            # Wider bandwidth for smoother formant character
            bw = max(fc * _FORMANT_BW_RATIO * 1.3, 50)
            low = max(fc - bw, 20)
            high = min(fc + bw, nyq * 0.95)
            if low >= high:
                continue
            weight = weights[i] if i < len(weights) else 0.3
            out += bandpass(source, low, high, sr=sr) * weight

        return out

    def _crossfade_formants(
        self,
        source: np.ndarray,
        formants_a: list[float],
        formants_b: list[float],
        sr: int,
        crossfade_time: float = 0.5,
    ) -> np.ndarray:
        """Smoothly crossfade between two vowel formant sets.

        Instead of abrupt switching, this creates a smooth transition
        between vowel shapes by interpolating the formant filtering
        over a configurable crossfade time. Creates natural-sounding
        vowel transitions like real vocal formant movement.
        """
        n = len(source)
        n_blocks = max(1, int(crossfade_time * 20))  # 50ms blocks
        block_size = n // max(n_blocks, 1)

        out = np.zeros(n)

        for bi in range(n_blocks):
            start = bi * block_size
            end = min(start + block_size, n)
            if start >= n:
                break

            progress = bi / max(n_blocks - 1, 1)

            # Interpolate formant frequencies
            interp_formants = []
            for fa, fb in zip(formants_a, formants_b):
                interp_formants.append(fa + (fb - fa) * progress)

            block = source[start:end]
            padded = np.pad(block, (0, max(0, 1024 - len(block))))

            block_formed = self._apply_formants(padded, interp_formants, sr)
            out[start:end] = block_formed[:end - start]

        return out

    def _make_source(
        self,
        freq: float,
        duration: float,
        breathiness: float,
        sr: int,
        waveform: str = 'pulse',
    ) -> np.ndarray:
        """
        Generate the raw excitation source for vocal synthesis.

        Enhanced with richer breathiness using multiple filtered noise layers:
        - Lower breath band (300-2000Hz): chest resonance
        - Mid breath band (2000-5000Hz): oral cavity air
        - High breath band (5000-10000Hz): sibilance/aspiration

        Blends a pitched waveform with these breath layers for more
        realistic vocal aspiration quality.
        """
        n_samples = int(sr * duration)

        # Pitched component (glottal pulses)
        if waveform == 'pulse':
            pitched = pulse(freq, 0.35, duration, sr)
        elif waveform == 'sawtooth':
            pitched = sawtooth(freq, duration, sr)
        elif waveform == 'sine':
            pitched = sine(freq, duration, sr)
        else:
            pitched = pulse(freq, 0.35, duration, sr)

        pitched = pitched[:n_samples]

        # Multi-layer breathiness for more realistic vocal aspiration
        breathiness = np.clip(breathiness, 0.0, 1.0)

        # Layer 1: Chest breath (lower, warm)
        breath_low = noise(duration, sr, color='pink')
        breath_low = bandpass(breath_low, 300, 2000, sr=sr)
        breath_low = breath_low[:n_samples] * 0.5

        # Layer 2: Oral cavity air (mid, the main breath character)
        breath_mid = noise(duration, sr, color='pink')
        breath_mid = bandpass(breath_mid, 2000, 5000, sr=sr)
        breath_mid = breath_mid[:n_samples] * 0.7

        # Layer 3: Aspiration/sibilance (high, airy)
        breath_hi = noise(duration, sr, color='white')
        breath_hi = bandpass(breath_hi, 5000, min(10000, sr * 0.45), sr=sr)
        breath_hi = breath_hi[:n_samples] * 0.3

        # Combine breath layers
        breath = breath_low + breath_mid + breath_hi

        # Mix pitched and breathy components
        source = pitched * (1 - breathiness) + breath * breathiness

        return source

    def _apply_vibrato(
        self,
        signal: np.ndarray,
        freq: float,
        rate: float,
        depth: float,
        sr: int,
    ) -> np.ndarray:
        """
        Apply vocal vibrato with both pitch and amplitude components.

        Real vocal vibrato involves:
        1. Periodic pitch fluctuation (primary component)
        2. Periodic amplitude fluctuation (secondary, slightly out of phase)
        3. Slight irregularity in both rate and depth

        This creates a much more realistic and expressive vibrato
        than pure pitch modulation alone.
        """
        if depth <= 0 or rate <= 0:
            return signal

        n = len(signal)
        t = np.arange(n) / sr

        # Add slight irregularity to rate for natural feel
        rate_wobble = np.sin(2 * np.pi * 0.3 * t) * rate * 0.05
        effective_rate = rate + rate_wobble

        # 1. Pitch vibrato via resampling interpolation
        max_shift_samples = depth * freq / sr * n * 0.001
        max_shift_samples = min(max_shift_samples, sr * 0.003)

        # Phase accumulation for slightly varying rate
        vibrato_phase = np.cumsum(2 * np.pi * effective_rate / sr)
        vibrato_lfo = np.sin(vibrato_phase) * max_shift_samples
        read_positions = np.arange(n, dtype=np.float64) + vibrato_lfo

        # Clamp to valid range
        read_positions = np.clip(read_positions, 0, n - 1)

        # Linear interpolation
        idx_floor = np.floor(read_positions).astype(int)
        idx_ceil = np.minimum(idx_floor + 1, n - 1)
        frac = read_positions - idx_floor

        pitched = signal[idx_floor] * (1 - frac) + signal[idx_ceil] * frac

        # 2. Amplitude vibrato (slightly out of phase with pitch)
        # Real vocal vibrato has correlated amplitude variation
        amp_lfo = 1.0 + np.sin(vibrato_phase + 0.8) * depth * 0.08
        pitched *= amp_lfo

        return pitched

    # ── Vocal Chop ───────────────────────────────────────────────────

    def _render_vocal_chop(self, freq, duration, p, sr):
        """
        Vocal chop: short vocal-like timbre using formant synthesis.

        Fast attack, moderate decay — designed for rhythmic chop patterns.
        Uses pulse wave + noise source through formant filter bank.
        """
        n_samples = int(sr * duration)
        formants = self._get_formants(p['vowel'], p['formant_shift'])

        # Source: pulse wave with moderate breathiness
        source = self._make_source(freq, duration, p['breathiness'], sr, 'pulse')

        # Apply formant filtering
        raw = self._apply_formants(source, formants, sr)

        # Add a touch of direct sine for pitch clarity
        pitch_body = sine(freq, duration, sr) * 0.15
        raw = raw + pitch_body[:len(raw)]

        # Percussive envelope — short and punchy for chop character
        chop_decay = min(duration * 0.7, 0.8)
        env = percussive(
            attack=0.005,
            decay=chop_decay,
            duration=duration,
            sr=sr,
            curve=4.0,
        )
        raw = raw[:len(env)] * env

        # Vibrato (subtle for chops)
        vib_depth = p['vibrato_depth'] * 0.5  # less vibrato on chops
        raw = self._apply_vibrato(raw, freq, p['vibrato_rate'], vib_depth, sr)

        # Shape: cut sub rumble, gentle top boost for presence
        raw = highpass(raw, 120, sr=sr)
        raw = lowpass(raw, 8000, sr=sr)

        return raw

    # ── Vocal Pad ────────────────────────────────────────────────────

    def _render_vocal_pad(self, freq, duration, p, sr):
        """
        Vocal pad: sustained vocal texture using filtered noise + formant resonances.

        Slow attack, long sustain — designed for harmonic backgrounds.
        Blends pitched source with heavy breath for airy, pad-like character.
        """
        n_samples = int(sr * duration)
        formants = self._get_formants(p['vowel'], p['formant_shift'])

        # Heavier breathiness for pad texture
        pad_breath = max(p['breathiness'], 0.45)
        source = self._make_source(freq, duration, pad_breath, sr, 'sawtooth')

        # Apply formant filtering
        raw = self._apply_formants(source, formants, sr)

        # Add warm sine body at fundamental
        body = sine(freq, duration, sr) * 0.2
        raw = raw + body[:len(raw)]

        # Sub-octave for weight (very subtle)
        sub = sine(freq / 2, duration, sr) * 0.06
        raw = raw + sub[:len(raw)]

        # Slow pad envelope
        env = adsr_exp(
            attack=max(0.6, duration * 0.15),
            decay=0.4,
            sustain=0.8,
            release=max(0.5, duration * 0.12),
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Vibrato
        raw = self._apply_vibrato(raw, freq, p['vibrato_rate'], p['vibrato_depth'], sr)

        # Warm filtering
        raw = lowpass(raw, 6000, sr=sr, resonance=0.08)
        raw = highpass(raw, 80, sr=sr)

        # Gentle chorus for width
        raw = chorus(raw, sr=sr, rate=0.5, depth=0.006, mix=0.2)

        return raw

    # ── Choir ────────────────────────────────────────────────────────

    def _render_choir(self, freq, duration, p, sr):
        """
        Choir stack: multiple detuned voices with formant filtering and breath.

        Combines several unison voices, each formant-filtered, with a shared
        breathy noise layer for realistic choral texture.
        """
        n_samples = int(sr * duration)
        n_voices = max(3, min(int(p['n_voices']), 8))
        detune = p['detune_cents']
        formants = self._get_formants(p['vowel'], p['formant_shift'])

        # Build detuned choir voices
        choir_voices = []
        for i in range(n_voices):
            offset = (i - (n_voices - 1) / 2) * (detune / max(n_voices - 1, 1))
            voice_freq = freq * (2 ** (offset / 1200))

            # Alternate source waveforms across voices for richness
            if i % 3 == 0:
                src = self._make_source(voice_freq, duration, p['breathiness'], sr, 'pulse')
            elif i % 3 == 1:
                src = self._make_source(voice_freq, duration, p['breathiness'], sr, 'sawtooth')
            else:
                src = self._make_source(voice_freq, duration, p['breathiness'] * 1.3, sr, 'sine')

            # Apply formants to each voice
            formed = self._apply_formants(src, formants, sr)
            choir_voices.append(formed)

        raw = mix_signals(*choir_voices)

        # Shared breathy noise layer (choir breath)
        breath = noise(duration, sr, color='pink') * 0.08
        breath = bandpass(breath, 1500, 7000, sr=sr)
        breath_env = adsr_exp(
            attack=0.5, decay=0.3, sustain=0.4, release=0.5,
            duration=duration, sr=sr,
        )
        raw = raw + breath[:len(raw)] * breath_env[:len(raw)]

        # Slow choral envelope
        env = adsr_exp(
            attack=max(0.4, duration * 0.1),
            decay=0.3,
            sustain=0.85,
            release=max(0.6, duration * 0.1),
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Vibrato — slightly slower and deeper for choir feel
        raw = self._apply_vibrato(
            raw, freq,
            rate=p['vibrato_rate'] * 0.8,
            depth=p['vibrato_depth'] * 1.4,
            sr=sr,
        )

        # Gentle filtering
        raw = lowpass(raw, 7000, sr=sr, resonance=0.06)
        raw = highpass(raw, 100, sr=sr)

        # Chorus for additional width and shimmer
        raw = chorus(raw, sr=sr, rate=0.4, depth=0.005, mix=0.18)

        return raw

    # ── Ad-lib ───────────────────────────────────────────────────────

    def _render_adlib(self, freq, duration, p, sr):
        """
        Ad-lib: short percussive vocal stab/texture (like "hey!", "what!", "skrrt").

        Very fast attack, short decay, bright formants, transient emphasis.
        Designed for punctuation hits and rhythmic accents.
        """
        n_samples = int(sr * duration)
        formants = self._get_formants(p['vowel'], p['formant_shift'])

        # Bright source with low breathiness for sharp attack
        adlib_breath = min(p['breathiness'], 0.25)
        source = self._make_source(freq, duration, adlib_breath, sr, 'pulse')

        # Apply formants
        raw = self._apply_formants(source, formants, sr)

        # --- Better consonant simulation ---
        # Two-stage consonant: initial plosive burst + fricative tail
        # Stage 1: Plosive burst (like "t", "k" — very short broadband)
        plosive = noise(duration, sr, color='white') * 0.25
        plosive_env = percussive(
            attack=0.0005,
            decay=0.008,
            duration=duration,
            sr=sr,
            curve=25.0,
        )
        plosive = plosive[:len(plosive_env)] * plosive_env
        plosive = bandpass(plosive, 3000, min(12000, sr * 0.45), sr=sr)

        # Stage 2: Fricative tail (like "s", "sh" — slightly longer)
        fricative = noise(duration, sr, color='white') * 0.12
        fric_env = percussive(
            attack=0.003,
            decay=0.03,
            duration=duration,
            sr=sr,
            curve=12.0,
        )
        fricative = fricative[:len(fric_env)] * fric_env
        fricative = bandpass(fricative, 4000, min(10000, sr * 0.45), sr=sr)

        raw = raw + plosive[:len(raw)] + fricative[:len(raw)]

        # Very short percussive envelope
        adlib_decay = min(duration * 0.6, 0.25)
        env = percussive(
            attack=0.002,
            decay=adlib_decay,
            duration=duration,
            sr=sr,
            curve=6.0,
        )
        raw = raw[:len(env)] * env

        # Pitch bend down at onset for "hey" style attack
        n = len(raw)
        bend_samples = min(int(sr * 0.04), n)  # 40ms pitch bend
        if bend_samples > 0:
            bend_env = np.ones(n)
            bend_curve = np.exp(-10 * np.linspace(0, 1, bend_samples))
            # Slight upward pitch at onset that drops to target
            bend_env[:bend_samples] = 1 + 0.15 * bend_curve
            t = np.arange(n) / sr
            phase = np.cumsum(2 * np.pi * freq * bend_env / sr)
            pitched_body = np.sin(phase) * 0.12
            raw = raw + pitched_body

        # Bright and present
        raw = highpass(raw, 200, sr=sr)
        raw = lowpass(raw, 10000, sr=sr)

        # Slight compression for punch
        raw = compress(raw, threshold_db=-8, ratio=4.0, attack_ms=1, release_ms=30, sr=sr)

        return raw

    # ── Vocal Rise ───────────────────────────────────────────────────

    def _render_vocal_rise(self, freq, duration, p, sr):
        """
        Vocal riser/swell: filtered noise with rising formants and volume.

        Creates a building tension effect. Formant frequencies sweep upward
        over the duration while amplitude rises to a peak.
        """
        n_samples = int(sr * duration)
        formants = self._get_formants(p['vowel'], p['formant_shift'])

        # Source: heavy breath/noise with subtle pitch
        rise_breath = max(p['breathiness'], 0.55)
        source = self._make_source(freq, duration, rise_breath, sr, 'sawtooth')

        # Rising formant sweep — process in blocks with formants that shift up
        block_size = sr // 20  # 50ms blocks
        out = np.zeros(n_samples)
        n_blocks = n_samples // block_size + 1

        for bi in range(n_blocks):
            start = bi * block_size
            end = min(start + block_size, n_samples)
            if start >= n_samples:
                break

            # Progress ratio 0..1 through the rise
            progress = bi / max(n_blocks - 1, 1)

            # Formants shift upward over time (up to +6 semitones)
            shift_ratio = 2 ** (progress * 6 / 12)
            shifted_formants = [f * shift_ratio for f in formants]

            block = source[start:end]
            # Pad block for filter stability
            padded = np.pad(block, (0, max(0, 1024 - len(block))))

            block_formed = np.zeros(len(padded))
            nyq = sr / 2
            weights = [1.0, 0.7, 0.45]
            for fi, fc in enumerate(shifted_formants):
                if fc >= nyq * 0.95:
                    continue
                bw = max(fc * _FORMANT_BW_RATIO, 40)
                low = max(fc - bw, 20)
                high = min(fc + bw, nyq * 0.95)
                if low >= high:
                    continue
                w = weights[fi] if fi < len(weights) else 0.3
                block_formed += bandpass(padded, low, high, sr=sr) * w

            out[start:end] = block_formed[:end - start]

        raw = out

        # Rising amplitude envelope — builds from near-silence to peak
        rise_env = np.linspace(0, 1, n_samples) ** 1.8  # convex rise curve
        # Sharp cut at the end (the "drop")
        cutoff_samples = max(int(sr * 0.02), 1)
        if cutoff_samples < n_samples:
            rise_env[-cutoff_samples:] *= np.linspace(1, 0, cutoff_samples)
        raw = raw * rise_env

        # Add a rising sine sweep for pitched tension
        t = np.arange(n_samples) / sr
        sweep_freq = np.linspace(freq * 0.5, freq * 2, n_samples)
        phase = np.cumsum(2 * np.pi * sweep_freq / sr)
        sweep_tone = np.sin(phase) * 0.15 * rise_env
        raw = raw + sweep_tone

        # Filtering
        raw = highpass(raw, 100, sr=sr)
        raw = lowpass(raw, 12000, sr=sr)

        return raw

    # ── Vocal Drone ──────────────────────────────────────────────────

    def _render_vocal_drone(self, freq, duration, p, sr):
        """
        Vocal drone: sustained drone with vocal character and evolving formants.

        Uses a rich harmonic source with slow formant crossfading between
        two vowel shapes, creating an organic, shifting vocal texture.
        """
        n_samples = int(sr * duration)

        # Rich harmonic source
        harmonics = [1.0, 2.0, 3.0, 4.0, 5.0, 6.0]
        amplitudes = [1.0, 0.55, 0.35, 0.2, 0.12, 0.07]
        tone = harmonic_stack(freq, harmonics, amplitudes, duration, sr)
        tone = tone[:n_samples]

        # Blend with breathy noise
        breath = noise(duration, sr, color='pink') * p['breathiness'] * 0.6
        breath = bandpass(breath, 200, 6000, sr=sr)
        source = tone + breath[:len(tone)]

        # Two vowel shapes to crossfade between
        vowel_a = p['vowel']
        # Pick a contrasting vowel for crossfade target
        _vowel_pairs = {
            'ah': 'ooh', 'ooh': 'ah', 'ee': 'oh',
            'oh': 'ee', 'eh': 'ah',
        }
        vowel_b = _vowel_pairs.get(vowel_a, 'ooh')

        formants_a = self._get_formants(vowel_a, p['formant_shift'])
        formants_b = self._get_formants(vowel_b, p['formant_shift'])

        # Smooth formant crossfade between vowel shapes
        # Uses interpolated formant frequencies for natural vowel transitions
        raw = self._crossfade_formants(source, formants_a, formants_b, sr,
                                        crossfade_time=duration)

        # Drone envelope — very slow attack, full sustain, slow release
        env = adsr_exp(
            attack=max(1.0, duration * 0.1),
            decay=0.5,
            sustain=0.9,
            release=max(0.8, duration * 0.08),
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Vibrato
        raw = self._apply_vibrato(raw, freq, p['vibrato_rate'], p['vibrato_depth'], sr)

        # Subtle filter movement
        raw = filter_sweep(
            raw,
            start_cutoff=3000,
            end_cutoff=5000,
            sr=sr,
            ftype='low',
        )
        raw = highpass(raw, 60, sr=sr)

        # Gentle tape saturation for warmth
        raw = saturate(raw, drive=0.06, sat_type='tape')

        # Chorus for organic width
        raw = chorus(raw, sr=sr, rate=0.3, depth=0.005, mix=0.15)

        return raw
