"""FY3 Zaytoven Collection — Strings instrument model.

Supports: orchestral, synth, pizzicato, chamber, dark, cinematic
Uses detuned unison voices, filtering, and lush effects to create
everything from intimate chamber strings to wide cinematic pads.
"""

import numpy as np

from engine.oscillators import sawtooth, sine, pulse, noise
from engine.envelope import adsr, adsr_exp, percussive, lfo
from engine.filters import lowpass, highpass, bandpass, filter_sweep
from engine.effects import reverb, chorus, delay_effect, saturate, eq_3band, compress, tremolo
from engine.utils import midi_to_freq, normalize, stereo_spread, mix_signals, detune_unison


class Strings:
    """String ensemble synthesizer with multiple articulations and types."""

    TYPES = ('orchestral', 'synth', 'pizzicato', 'chamber', 'dark', 'cinematic')

    def __init__(self, sr: int = 48000):
        self.sr = sr

    DEFAULTS = {
        'string_type': 'orchestral',
        'voices': 5,
        'detune_cents': 12,
        'filter_cutoff': 4000,
        'filter_resonance': 0.1,
        'attack': 0.35,
        'decay': 0.2,
        'sustain': 0.8,
        'release': 0.5,
        'reverb_wet': 0.35,
        'chorus_mix': 0.2,
        'eq_low': 0,
        'eq_mid': 0,
        'eq_high': 0,
        'bow_pressure': 0.5,
        'tremolo_rate': 0.0,
        'tremolo_depth': 0.0,
    }

    def render(self, note: int, duration: float, params: dict | None = None) -> np.ndarray:
        """
        Render a single string note.

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
        stype = p['string_type']
        n_samples = int(sr * duration)

        # ── Type-specific defaults ──────────────────────────────────────
        if stype == 'orchestral':
            signal = self._render_orchestral(freq, duration, p, sr)
        elif stype == 'synth':
            signal = self._render_synth(freq, duration, p, sr)
        elif stype == 'pizzicato':
            signal = self._render_pizzicato(freq, duration, p, sr)
        elif stype == 'chamber':
            signal = self._render_chamber(freq, duration, p, sr)
        elif stype == 'dark':
            signal = self._render_dark(freq, duration, p, sr)
        elif stype == 'cinematic':
            signal = self._render_cinematic(freq, duration, p, sr)
        else:
            signal = self._render_orchestral(freq, duration, p, sr)

        signal = signal[:n_samples]

        # ── EQ ──────────────────────────────────────────────────────────
        if p['eq_low'] != 0 or p['eq_mid'] != 0 or p['eq_high'] != 0:
            signal = eq_3band(
                signal, sr=sr,
                low_gain_db=p['eq_low'],
                mid_gain_db=p['eq_mid'],
                high_gain_db=p['eq_high'],
            )

        # ── Tremolo (orchestral tremolo option) ─────────────────────────
        trem_rate = p.get('tremolo_rate', 0.0)
        trem_depth = p.get('tremolo_depth', 0.0)
        if trem_rate > 0 and trem_depth > 0:
            signal = tremolo(signal, sr=sr, rate=trem_rate, depth=trem_depth)

        # ── Effects chain ───────────────────────────────────────────────
        if p['chorus_mix'] > 0 and stype != 'pizzicato':
            signal = chorus(signal, sr=sr, rate=0.8, depth=0.004, mix=p['chorus_mix'])

        if p['reverb_wet'] > 0:
            room = {'orchestral': 0.6, 'cinematic': 0.8, 'chamber': 0.35,
                     'dark': 0.55, 'synth': 0.4, 'pizzicato': 0.3}.get(stype, 0.5)
            signal = reverb(signal, sr=sr, room_size=room, damping=0.45, wet=p['reverb_wet'])

        signal = normalize(signal, 0.9)
        return signal

    # ── Orchestral strings ──────────────────────────────────────────────

    def _render_orchestral(self, freq, duration, p, sr):
        """Full orchestral strings: multiple detuned saws + slow attack + LP filter.

        Enhanced with:
        - Bow pressure simulation (more harmonics at higher pressure)
        - Richer rosin noise with narrower bandpass filtering
        - Per-voice panning offsets for wider stereo field
        """
        n_voices = max(3, min(int(p['voices']), 7))
        detune = p['detune_cents']
        bow_pressure = p.get('bow_pressure', 0.5)

        # Build unison voices from sawtooth with per-voice panning
        voices = []
        for i in range(n_voices):
            offset = (i - (n_voices - 1) / 2) * (detune / max(n_voices - 1, 1))
            f = freq * (2 ** (offset / 1200))
            v = sawtooth(f, duration, sr)

            # Bow pressure: higher pressure adds more high harmonics
            # Simulate by mixing in square wave (odd harmonics) at high pressure
            if bow_pressure > 0.5:
                from engine.oscillators import square as sq_wave
                pressure_factor = (bow_pressure - 0.5) * 2  # 0..1
                sq_component = sq_wave(f, duration, sr)
                # Blend sawtooth with square for more harmonic density
                v = v * (1 - pressure_factor * 0.3) + sq_component[:len(v)] * pressure_factor * 0.3

            # Per-voice stereo offset: alternate voices slightly left/right
            # Apply as slight amplitude variation to create width in mono
            pan_offset = (i - (n_voices - 1) / 2) / max(n_voices - 1, 1)
            # Create subtle delay-based width (even in mono output)
            delay_samples = int(abs(pan_offset) * 0.001 * sr)  # up to 1ms
            if delay_samples > 0 and delay_samples < len(v):
                delayed = np.zeros_like(v)
                delayed[delay_samples:] = v[:len(v) - delay_samples]
                v = v * 0.7 + delayed * 0.3

            voices.append(v)
        raw = mix_signals(*voices)

        # Slow orchestral attack
        env = adsr_exp(
            attack=max(p['attack'], 0.2),
            decay=p['decay'],
            sustain=p['sustain'],
            release=p['release'],
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Low-pass filter — bow pressure affects brightness
        # Higher pressure = brighter cutoff
        pressure_cutoff = p['filter_cutoff'] * (0.8 + bow_pressure * 0.4)
        raw = lowpass(raw, pressure_cutoff, sr=sr, resonance=p['filter_resonance'])

        # Richer rosin noise with tighter bandpass filtering
        # Real rosin noise is concentrated in the 2-6kHz range with peaks
        rosin = noise(duration, sr, color='pink') * 0.02 * (0.5 + bow_pressure * 0.5)
        # Primary rosin band (scratchy character)
        rosin_main = bandpass(rosin, 2000, 5000, sr=sr)
        # Secondary rosin peak (higher presence)
        rosin_hi = bandpass(rosin, 5000, 8000, sr=sr) * 0.4
        rosin_combined = rosin_main + rosin_hi[:len(rosin_main)]
        rosin_env = adsr_exp(attack=0.3, decay=0.2, sustain=0.5, release=0.3,
                             duration=duration, sr=sr)
        raw = raw + rosin_combined[:len(raw)] * rosin_env[:len(raw)]

        # Gentle high-pass to remove sub rumble
        raw = highpass(raw, 80, sr=sr)

        return raw

    # ── Synth strings ───────────────────────────────────────────────────

    def _render_synth(self, freq, duration, p, sr):
        """Synth strings: saw + pulse layered, resonant filter, punchy."""
        n_voices = max(2, min(int(p['voices']), 5))
        detune = p['detune_cents']

        # Sawtooth unison
        saw_stack = detune_unison(sawtooth, freq, n_voices, detune, duration, sr)
        # Pulse layer for hollow richness
        pulse_layer = pulse(freq, 0.4, duration, sr) * 0.3

        raw = saw_stack + pulse_layer[:len(saw_stack)]

        env = adsr_exp(
            attack=max(p['attack'], 0.02),
            decay=p['decay'],
            sustain=p['sustain'],
            release=p['release'],
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Resonant low-pass
        raw = lowpass(raw, p['filter_cutoff'], sr=sr, resonance=max(p['filter_resonance'], 0.3))

        # Subtle saturation for analog warmth
        raw = saturate(raw, drive=0.06, sat_type='tape')
        raw = highpass(raw, 60, sr=sr)

        return raw

    # ── Pizzicato ───────────────────────────────────────────────────────

    def _render_pizzicato(self, freq, duration, p, sr):
        """Pizzicato: short percussive pluck with fast attack and quick decay."""
        # Use percussive envelope regardless of ADSR params
        pluck_decay = min(duration * 0.8, 0.6)
        env = percussive(attack=0.002, decay=pluck_decay, duration=duration, sr=sr, curve=6.0)

        # Bright sawtooth for pluck transient
        raw = sawtooth(freq, duration, sr)
        # Add a sine body
        body = sine(freq, duration, sr) * 0.5
        raw = raw + body[:len(raw)]

        raw = raw[:len(env)] * env

        # Filter sweep: bright at onset, darkens quickly
        raw = filter_sweep(raw, start_cutoff=8000, end_cutoff=1200, sr=sr, ftype='low')

        # Pluck noise transient
        click = noise(duration, sr, color='white') * 0.08
        click_env = percussive(attack=0.001, decay=0.03, duration=duration, sr=sr, curve=15.0)
        click = click[:len(click_env)] * click_env
        raw = raw + click[:len(raw)]

        raw = highpass(raw, 100, sr=sr)
        return raw

    # ── Chamber ─────────────────────────────────────────────────────────

    def _render_chamber(self, freq, duration, p, sr):
        """Chamber strings: fewer voices, drier, intimate."""
        n_voices = min(int(p['voices']), 3)  # cap at 3 for intimate sound
        detune = p['detune_cents'] * 0.6  # less detune = tighter

        voices = []
        for i in range(n_voices):
            offset = (i - (n_voices - 1) / 2) * (detune / max(n_voices - 1, 1))
            f = freq * (2 ** (offset / 1200))
            v = sawtooth(f, duration, sr)
            voices.append(v)
        raw = mix_signals(*voices)

        # Moderate attack
        env = adsr_exp(
            attack=max(p['attack'], 0.12),
            decay=p['decay'],
            sustain=p['sustain'] * 0.85,
            release=p['release'] * 0.7,
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Tighter filter — less bright than orchestral
        cutoff = min(p['filter_cutoff'], 3500)
        raw = lowpass(raw, cutoff, sr=sr, resonance=p['filter_resonance'])

        # Subtle bow noise
        bow = noise(duration, sr, color='pink') * 0.01
        bow = bandpass(bow, 2000, 5000, sr=sr)
        bow_env = adsr_exp(attack=0.15, decay=0.15, sustain=0.3, release=0.2,
                           duration=duration, sr=sr)
        raw = raw + bow[:len(raw)] * bow_env[:len(raw)]

        raw = highpass(raw, 100, sr=sr)
        return raw

    # ── Dark strings ────────────────────────────────────────────────────

    def _render_dark(self, freq, duration, p, sr):
        """Dark strings: heavily low-passed, sub-heavy, brooding."""
        n_voices = max(3, min(int(p['voices']), 6))
        detune = p['detune_cents'] * 1.2  # wider detune for murkiness

        voices = []
        for i in range(n_voices):
            offset = (i - (n_voices - 1) / 2) * (detune / max(n_voices - 1, 1))
            f = freq * (2 ** (offset / 1200))
            v = sawtooth(f, duration, sr)
            voices.append(v)
        raw = mix_signals(*voices)

        # Add sub-octave sine for weight
        sub = sine(freq / 2, duration, sr) * 0.25
        raw = raw + sub[:len(raw)]

        env = adsr_exp(
            attack=max(p['attack'], 0.4),
            decay=p['decay'] * 1.5,
            sustain=p['sustain'],
            release=p['release'] * 1.3,
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Heavy low-pass — dark and muffled
        cutoff = min(p['filter_cutoff'], 2000)
        raw = lowpass(raw, cutoff, sr=sr, resonance=p['filter_resonance'])

        # Gentle saturation for grit
        raw = saturate(raw, drive=0.10, sat_type='tube')

        raw = highpass(raw, 40, sr=sr)
        return raw

    # ── Cinematic strings ───────────────────────────────────────────────

    def _render_cinematic(self, freq, duration, p, sr):
        """Cinematic: wide stereo, lush, heavy reverb, dramatic."""
        n_voices = max(5, min(int(p['voices']), 7))
        detune = max(p['detune_cents'], 15)  # wide for grandeur

        voices = []
        for i in range(n_voices):
            offset = (i - (n_voices - 1) / 2) * (detune / max(n_voices - 1, 1))
            f = freq * (2 ** (offset / 1200))
            v = sawtooth(f, duration, sr)
            voices.append(v)
        raw = mix_signals(*voices)

        # Add octave layer for brightness
        octave = sine(freq * 2, duration, sr) * 0.08
        raw = raw + octave[:len(raw)]

        # Very slow attack for dramatic swells
        env = adsr_exp(
            attack=max(p['attack'], 0.6),
            decay=p['decay'],
            sustain=p['sustain'],
            release=max(p['release'], 0.8),
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Warm low-pass with slight resonance
        raw = lowpass(raw, p['filter_cutoff'], sr=sr, resonance=max(p['filter_resonance'], 0.15))

        # Subtle filter movement (slow sweep up during note)
        filter_lfo = lfo(rate=0.15, depth=0.2, shape='triangle', duration=duration, sr=sr)
        n = len(raw)
        modulated_cutoff_start = p['filter_cutoff'] * 0.8
        modulated_cutoff_end = p['filter_cutoff'] * 1.1
        raw = filter_sweep(raw, modulated_cutoff_start, modulated_cutoff_end, sr=sr, ftype='low')

        # Tape warmth
        raw = saturate(raw, drive=0.04, sat_type='tape')

        # Gentle compression to glue it together
        raw = compress(raw, threshold_db=-10, ratio=2.5, attack_ms=20, release_ms=100, sr=sr)

        raw = highpass(raw, 60, sr=sr)
        return raw
