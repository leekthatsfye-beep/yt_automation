"""FY3 Zaytoven Collection — Lead instrument model.

Supports: organ_lead, synth_lead, whistle, bright, detuned, portamento
Cutting lead sounds for melodies — from clean organ leads to fat
detuned super-saws and pure whistle tones.
"""

import numpy as np

from engine.oscillators import sine, sawtooth, square, triangle, pulse, noise, supersaw
from engine.envelope import adsr, adsr_exp, percussive, lfo
from engine.filters import lowpass, highpass, bandpass
from engine.effects import reverb, chorus, delay_effect, saturate, eq_3band, compress
from engine.utils import midi_to_freq, normalize, mix_signals, detune_unison


class Lead:
    """Lead synthesizer for melodic lines and hooks."""

    TYPES = ('organ_lead', 'synth_lead', 'whistle', 'bright', 'detuned', 'portamento', 'supersaw')

    def __init__(self, sr: int = 48000):
        self.sr = sr

    DEFAULTS = {
        'lead_type': 'organ_lead',
        'voices': 3,
        'detune_cents': 8,
        'filter_cutoff': 5000,
        'filter_resonance': 0.15,
        'vibrato_rate': 5.0,
        'vibrato_depth': 0.01,
        'attack': 0.01,
        'sustain': 0.8,
        'release': 0.15,
        'reverb_wet': 0.2,
    }

    def render(self, note: int, duration: float, params: dict | None = None) -> np.ndarray:
        """
        Render a single lead note.

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
        lead_type = p['lead_type']
        n_samples = int(sr * duration)

        if lead_type == 'organ_lead':
            signal = self._render_organ_lead(freq, duration, p, sr)
        elif lead_type == 'synth_lead':
            signal = self._render_synth_lead(freq, duration, p, sr)
        elif lead_type == 'whistle':
            signal = self._render_whistle(freq, duration, p, sr)
        elif lead_type == 'bright':
            signal = self._render_bright(freq, duration, p, sr)
        elif lead_type == 'detuned':
            signal = self._render_detuned(freq, duration, p, sr)
        elif lead_type == 'portamento':
            signal = self._render_portamento(freq, duration, p, sr)
        elif lead_type == 'supersaw':
            signal = self._render_supersaw(freq, duration, p, sr)
        else:
            signal = self._render_organ_lead(freq, duration, p, sr)

        signal = signal[:n_samples]

        # ── Reverb ──────────────────────────────────────────────────────
        if p['reverb_wet'] > 0:
            room = {'organ_lead': 0.3, 'synth_lead': 0.35, 'whistle': 0.5,
                     'bright': 0.3, 'detuned': 0.4, 'portamento': 0.45,
                     'supersaw': 0.35}.get(lead_type, 0.35)
            signal = reverb(signal, sr=sr, room_size=room, damping=0.4, wet=p['reverb_wet'])

        signal = normalize(signal, 0.9)
        return signal

    # ── Helper: vibrato phase accumulation ──────────────────────────────

    def _vibrato_sine(self, freq, duration, p, sr, delay_onset=True):
        """Generate a sine with vibrato via phase accumulation.

        Enhanced with realistic delayed-onset vibrato: real synth players
        start a note clean and gradually add vibrato as the note sustains.
        Uses a smooth S-curve onset for natural feel, with both pitch
        and subtle amplitude components.

        Returns (signal, phase) so harmonics can share the same phase.
        """
        n_samples = int(sr * duration)
        t = np.arange(n_samples) / sr

        vib_rate = p['vibrato_rate']
        vib_depth = p['vibrato_depth']

        # Delayed vibrato onset — smooth S-curve for natural player feel
        if delay_onset:
            # Delay time: at least 0.1s or 3x attack for realistic player behavior
            onset_time = max(p['attack'] * 3, 0.1)
            # Smooth S-curve onset (smoother than linear ramp)
            onset_progress = np.clip((t - onset_time * 0.3) / onset_time, 0, 1)
            vib_onset = onset_progress * onset_progress * (3 - 2 * onset_progress)  # smoothstep
        else:
            vib_onset = np.ones(n_samples)

        # Pitch vibrato
        vib = np.sin(2 * np.pi * vib_rate * t) * vib_depth * vib_onset
        inst_freq = freq * (1 + vib)
        phase = np.cumsum(2 * np.pi * inst_freq / sr)

        signal = np.sin(phase)

        # Subtle amplitude vibrato component (real vibrato has both pitch and amplitude)
        amp_vib = 1.0 + np.sin(2 * np.pi * vib_rate * t + 0.5) * vib_depth * 0.15 * vib_onset
        signal *= amp_vib

        return signal, phase

    # ── Organ Lead ──────────────────────────────────────────────────────

    def _render_organ_lead(self, freq, duration, p, sr):
        """Organ lead: 2-3 drawbar organ with brighter settings for cutting through."""
        n_samples = int(sr * duration)

        tone, phase = self._vibrato_sine(freq, duration, p, sr)

        # Drawbar simulation: fundamental (8') + 2nd harmonic (4') + 3rd (2 2/3')
        h2 = np.sin(2 * phase) * 0.55   # 4' drawbar — prominent
        h3 = np.sin(3 * phase) * 0.25   # 2 2/3' drawbar
        h4 = np.sin(4 * phase) * 0.10   # 2' drawbar — for brightness

        raw = tone + h2 + h3 + h4

        # Fast organ-style envelope
        env = adsr_exp(
            attack=max(p['attack'], 0.005),
            decay=0.08,
            sustain=max(p['sustain'], 0.85),
            release=p['release'],
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Key click
        click = noise(duration, sr, color='white') * 0.03
        from engine.envelope import percussive
        click_env = percussive(attack=0.001, decay=0.01, duration=duration, sr=sr, curve=20.0)
        click = click[:len(click_env)] * click_env
        raw = raw + click[:len(raw)]

        # Slight tube overdrive for that organ character
        raw = saturate(raw, drive=0.10, sat_type='tube')

        # Filter — keep it bright for lead duty
        raw = lowpass(raw, min(p['filter_cutoff'], 6000), sr=sr, resonance=p['filter_resonance'])
        raw = highpass(raw, 80, sr=sr)

        # Organ EQ: cut lows, boost mids for presence
        raw = eq_3band(raw, sr=sr, low_gain_db=-2, mid_gain_db=2, high_gain_db=1)

        return raw

    # ── Synth Lead ──────────────────────────────────────────────────────

    def _render_synth_lead(self, freq, duration, p, sr):
        """Synth lead: saw/pulse with filter, slight detune for fatness."""
        n_voices = max(2, min(int(p['voices']), 4))
        detune = p['detune_cents']

        # Detuned sawtooth unison
        saw_stack = detune_unison(sawtooth, freq, n_voices, detune, duration, sr)

        # Layer a pulse wave for body
        pulse_layer = pulse(freq, 0.45, duration, sr) * 0.2

        raw = saw_stack + pulse_layer[:len(saw_stack)]

        # Apply vibrato as amplitude modulation (subtle)
        vib = lfo(rate=p['vibrato_rate'], depth=p['vibrato_depth'] * 0.5,
                   shape='sine', duration=duration, sr=sr)
        raw = raw[:len(vib)] * (1 + vib)

        env = adsr_exp(
            attack=max(p['attack'], 0.005),
            decay=0.1,
            sustain=p['sustain'],
            release=p['release'],
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Resonant filter
        raw = lowpass(raw, p['filter_cutoff'], sr=sr, resonance=max(p['filter_resonance'], 0.2))

        # Slight saturation for analog feel
        raw = saturate(raw, drive=0.06, sat_type='tape')

        raw = highpass(raw, 70, sr=sr)

        # Gentle compression
        raw = compress(raw, threshold_db=-10, ratio=2.5, attack_ms=5, release_ms=50, sr=sr)

        return raw

    # ── Whistle ─────────────────────────────────────────────────────────

    def _render_whistle(self, freq, duration, p, sr):
        """Whistle: pure sine with vibrato — simple, clean, expressive."""
        n_samples = int(sr * duration)

        # More prominent vibrato for whistle character
        vib_depth = max(p['vibrato_depth'], 0.015)
        vib_params = {**p, 'vibrato_depth': vib_depth}
        tone, phase = self._vibrato_sine(freq, duration, vib_params, sr)

        # Very subtle 2nd harmonic
        h2 = np.sin(2 * phase) * 0.04

        raw = tone + h2

        # Soft breath noise
        breath = noise(duration, sr, color='pink') * 0.025
        breath = bandpass(breath, 2000, 8000, sr=sr)

        raw = raw + breath[:len(raw)]

        # Smooth envelope
        env = adsr_exp(
            attack=max(p['attack'], 0.03),
            decay=0.1,
            sustain=max(p['sustain'], 0.9),
            release=max(p['release'], 0.1),
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Clean filter — just remove extreme highs
        raw = lowpass(raw, min(p['filter_cutoff'], 8000), sr=sr)
        raw = highpass(raw, 150, sr=sr)

        return raw

    # ── Bright Lead ─────────────────────────────────────────────────────

    def _render_bright(self, freq, duration, p, sr):
        """Bright: square wave + high harmonics, resonant filter for cutting leads."""
        n_samples = int(sr * duration)

        # Square wave as base — rich in odd harmonics
        raw = square(freq, duration, sr)

        # Add a detuned square for width
        detune = p['detune_cents']
        if detune > 0:
            f_up = freq * (2 ** (detune / 1200))
            f_dn = freq * (2 ** (-detune / 1200))
            raw2 = square(f_up, duration, sr) * 0.35
            raw3 = square(f_dn, duration, sr) * 0.35
            raw = raw + raw2[:len(raw)] + raw3[:len(raw)]

        # Vibrato
        vib = lfo(rate=p['vibrato_rate'], depth=p['vibrato_depth'] * 0.3,
                   shape='sine', duration=duration, sr=sr)
        raw = raw[:len(vib)] * (1 + vib)

        env = adsr_exp(
            attack=max(p['attack'], 0.003),
            decay=0.1,
            sustain=p['sustain'],
            release=p['release'],
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Resonant filter — bright and cutting
        cutoff = max(p['filter_cutoff'], 3000)
        raw = lowpass(raw, cutoff, sr=sr, resonance=max(p['filter_resonance'], 0.3))

        # Boost highs for presence
        raw = eq_3band(raw, sr=sr, low_gain_db=-1, mid_gain_db=1, high_gain_db=3)

        raw = highpass(raw, 80, sr=sr)
        return raw

    # ── Detuned Lead (Super-saw style) ──────────────────────────────────

    def _render_detuned(self, freq, duration, p, sr):
        """Detuned: multiple unison voices, heavy detune for super-saw type."""
        n_voices = max(5, min(int(p['voices']), 7))
        detune = max(p['detune_cents'], 20)  # heavier detune for this type

        # Big unison sawtooth stack
        saw_stack = detune_unison(sawtooth, freq, n_voices, detune, duration, sr)

        # Add a centered sine for fundamental anchor
        anchor = sine(freq, duration, sr) * 0.15

        raw = saw_stack + anchor[:len(saw_stack)]

        # Vibrato
        vib = lfo(rate=p['vibrato_rate'], depth=p['vibrato_depth'] * 0.3,
                   shape='sine', duration=duration, sr=sr)
        raw = raw[:len(vib)] * (1 + vib)

        env = adsr_exp(
            attack=max(p['attack'], 0.008),
            decay=0.15,
            sustain=p['sustain'],
            release=p['release'],
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Filter
        raw = lowpass(raw, p['filter_cutoff'], sr=sr, resonance=p['filter_resonance'])

        # Chorus for extra width on top of the natural chorus from detuning
        raw = chorus(raw, sr=sr, rate=0.7, depth=0.003, mix=0.15)

        # Compression to tame the big stack
        raw = compress(raw, threshold_db=-8, ratio=3.0, attack_ms=5, release_ms=60, sr=sr)

        raw = highpass(raw, 70, sr=sr)
        return raw

    # ── Portamento Lead ─────────────────────────────────────────────────

    def _render_portamento(self, freq, duration, p, sr):
        """Portamento: smooth glide character with pitch swell at onset.

        Enhanced with:
        - Configurable glide time and range
        - Richer resonant filter sweep during glide
        - More harmonics for fuller lead character
        """
        n_samples = int(sr * duration)
        t = np.arange(n_samples) / sr

        # Pitch glide: configurable range and time
        glide_semitones = p.get('glide_semitones', 2.0)
        glide_time = p.get('glide_time', 0.08)
        glide_samples = int(sr * glide_time)
        pitch_env = np.ones(n_samples)
        if glide_samples > 0:
            # Smooth exponential glide
            glide_curve = 1 - np.exp(-6 * np.linspace(0, 1, glide_samples))
            start_ratio = 2 ** (-glide_semitones / 12)
            pitch_env[:glide_samples] = start_ratio + (1 - start_ratio) * glide_curve

        # Generate with phase accumulation for smooth pitch changes
        inst_freq = freq * pitch_env

        # Add vibrato after glide settles (delayed onset)
        onset_progress = np.clip((t - glide_time) / max(p['attack'] * 3, 0.1), 0, 1)
        vib_onset = onset_progress * onset_progress * (3 - 2 * onset_progress)  # smoothstep
        vib = np.sin(2 * np.pi * p['vibrato_rate'] * t) * p['vibrato_depth'] * vib_onset
        inst_freq = inst_freq * (1 + vib)

        phase = np.cumsum(2 * np.pi * inst_freq / sr)

        # Richer sawtooth via additive (5 harmonics for fuller lead character)
        raw = np.sin(phase)
        raw += np.sin(2 * phase) * 0.4
        raw += np.sin(3 * phase) * 0.2
        if freq * 4 < sr / 2:
            raw += np.sin(4 * phase) * 0.1
        if freq * 5 < sr / 2:
            raw += np.sin(5 * phase) * 0.05

        # Slight detune layer for width
        detune = p['detune_cents']
        if detune > 0:
            f2 = freq * (2 ** (detune / 1200))
            inst_freq2 = f2 * pitch_env * (1 + vib)
            phase2 = np.cumsum(2 * np.pi * inst_freq2 / sr)
            layer2 = np.sin(phase2) * 0.3
            raw = raw + layer2[:len(raw)]

        env = adsr_exp(
            attack=max(p['attack'], 0.01),
            decay=0.12,
            sustain=p['sustain'],
            release=p['release'],
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # --- Resonant filter sweep during glide ---
        # Filter opens during glide, then settles
        base_cutoff = p['filter_cutoff']
        sweep_start = min(base_cutoff * 2.5, sr * 0.45)
        cutoff_env = np.ones(n_samples) * base_cutoff
        if glide_samples > 0 and glide_samples < n_samples:
            sweep_curve = np.exp(-4 * np.linspace(0, 1, glide_samples))
            cutoff_env[:glide_samples] = base_cutoff + (sweep_start - base_cutoff) * sweep_curve

        # Apply in blocks
        block_size = sr // 40
        out = np.zeros(n_samples)
        for start_i in range(0, n_samples, block_size):
            end_i = min(start_i + block_size, n_samples)
            mid = (start_i + end_i) // 2
            cf = np.clip(cutoff_env[min(mid, n_samples - 1)], 30, sr * 0.45)
            block = raw[start_i:end_i]
            padded = np.pad(block, (0, max(0, 512 - len(block))))
            out[start_i:end_i] = lowpass(padded, cf, sr=sr, resonance=max(p['filter_resonance'], 0.25))[:len(block)]
        raw = out

        # Tape saturation for smoothness
        raw = saturate(raw, drive=0.07, sat_type='tape')

        raw = highpass(raw, 70, sr=sr)
        return raw

    # ── Supersaw Lead ────────────────────────────────────────────────

    def _render_supersaw(self, freq, duration, p, sr):
        """Supersaw lead: 7-voice detuned sawtooth oscillator (Omnisphere-style).

        Massive, wall-of-sound lead using the supersaw oscillator with
        resonant filter, compression, and optional vibrato.
        """
        n_samples = int(sr * duration)

        # Use the supersaw oscillator for massive sound
        spread = min(p['detune_cents'] / 50.0, 1.0)  # map detune to spread
        raw = supersaw(freq, duration, sr, n_voices=7, spread=max(spread, 0.3))

        # Add sub-octave sine anchor for weight
        sub = sine(freq / 2, duration, sr) * 0.1
        raw = raw + sub[:len(raw)]

        # Vibrato with delayed onset
        vib = lfo(rate=p['vibrato_rate'], depth=p['vibrato_depth'] * 0.3,
                   shape='sine', duration=duration, sr=sr)
        # Delayed onset
        t = np.arange(n_samples) / sr
        onset_progress = np.clip((t - 0.15) / 0.2, 0, 1)
        vib_onset = onset_progress * onset_progress * (3 - 2 * onset_progress)
        raw = raw[:len(vib)] * (1 + vib * vib_onset[:len(vib)])

        env = adsr_exp(
            attack=max(p['attack'], 0.008),
            decay=0.15,
            sustain=p['sustain'],
            release=p['release'],
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Resonant filter for character
        raw = lowpass(raw, p['filter_cutoff'], sr=sr,
                      resonance=max(p['filter_resonance'], 0.2))

        # Chorus for even more width
        raw = chorus(raw, sr=sr, rate=0.6, depth=0.004, mix=0.12)

        # Compression to tame the massive stack
        raw = compress(raw, threshold_db=-8, ratio=3.5, attack_ms=3, release_ms=50, sr=sr)

        # Slight saturation for analog warmth
        raw = saturate(raw, drive=0.05, sat_type='tape')

        raw = highpass(raw, 65, sr=sr)
        return raw
