"""FY3 Zaytoven Collection — Flute instrument model.

Supports: pan, wooden, synth, ethnic, airy, choir_flute
Each type shapes harmonics, breath noise, vibrato, and filtering differently
to produce a musically distinct flute character.
"""

import numpy as np

from engine.oscillators import sine, noise, harmonic_stack, triangle
from engine.envelope import adsr, adsr_exp, lfo
from engine.filters import lowpass, highpass, bandpass, filter_sweep
from engine.effects import reverb, chorus, delay_effect, saturate, eq_3band
from engine.utils import midi_to_freq, normalize, stereo_spread, mix_signals


class Flute:
    """Flute synthesizer with breath modelling, vibrato, and multiple types."""

    TYPES = ('pan', 'wooden', 'synth', 'ethnic', 'airy', 'choir_flute')

    def __init__(self, sr: int = 48000):
        self.sr = sr

    DEFAULTS = {
        'flute_type': 'pan',
        'breath_amount': 0.15,
        'vibrato_rate': 5.0,
        'vibrato_depth': 0.012,
        'vibrato_delay': 0.2,
        'brightness': 0.5,
        'attack': 0.08,
        'decay': 0.15,
        'sustain': 0.75,
        'release': 0.25,
        'decay_time': 2.0,
        'reverb_wet': 0.3,
        'reverb_size': 0.4,
        'chorus_mix': 0.0,
        'delay_mix': 0.0,
        'delay_ms': 300,
        'eq_low': -1,
        'eq_mid': 0,
        'eq_high': 1,
        'stereo_width': 0.3,
    }

    def render(self, note: int, duration: float, params: dict | None = None) -> np.ndarray:
        """
        Render a single flute note.

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
        flute_type = p['flute_type']

        # ── Amplitude envelope (shaped by decay_time) ─────────────────
        decay_time = p['decay_time']
        env_decay = decay_time * 0.3
        env_sustain = np.clip(0.5 + decay_time * 0.15, 0.3, 0.95)
        env_release = decay_time * 0.2
        env = adsr_exp(
            attack=p['attack'],
            decay=env_decay,
            sustain=env_sustain,
            release=env_release,
            duration=duration,
            sr=sr,
        )

        # ── Vibrato LFO (modulates pitch) ──────────────────────────────
        vib_rate = p['vibrato_rate']
        vib_depth = p['vibrato_depth']

        # Delayed vibrato: ramp in over vibrato_delay so the onset is clean
        t = np.arange(int(sr * duration)) / sr
        vib_delay = max(p['vibrato_delay'], 0.01)
        vib_onset = np.clip(t / vib_delay, 0, 1)
        vib_lfo = np.sin(2 * np.pi * vib_rate * t) * vib_depth * vib_onset
        # Instantaneous frequency with vibrato
        inst_freq = freq * (1 + vib_lfo)
        # Phase accumulation for vibrato-modulated fundamental
        phase = np.cumsum(2 * np.pi * inst_freq / sr)
        fundamental = np.sin(phase)

        # ── Harmonics ───────────────────────────────────────────────────
        # Flutes have weak even harmonics; we add octave (2x) and 5th (3x)
        # with reduced amplitude, plus a gentle 4th harmonic for colour.
        h2 = np.sin(2 * phase)
        h3 = np.sin(3 * phase)
        h4 = np.sin(4 * phase)

        if flute_type == 'pan':
            # Pan flute: airy, mostly fundamental, very soft upper harmonics
            tone = fundamental + 0.12 * h2 + 0.06 * h3 + 0.02 * h4
            breath_bw = (800, 4000)

        elif flute_type == 'wooden':
            # Wooden flute: warmer, stronger 2nd harmonic, mellow
            tone = fundamental + 0.25 * h2 + 0.10 * h3 + 0.04 * h4
            breath_bw = (600, 3500)

        elif flute_type == 'synth':
            # Synth flute: cleaner, more precise, slight triangle character
            tri_component = triangle(freq, duration, sr) * 0.15
            tone = fundamental + 0.08 * h2 + 0.04 * h3 + tri_component
            breath_bw = (1000, 6000)

        elif flute_type == 'ethnic':
            # Ethnic flute (bansuri / ney inspired): rich harmonics, breathy
            tone = fundamental + 0.30 * h2 + 0.18 * h3 + 0.08 * h4
            # Add slight pitch instability for organic feel
            wobble = lfo(rate=0.7, depth=0.003, shape='triangle', duration=duration, sr=sr)
            tone *= (1 + wobble)
            breath_bw = (500, 5000)

        elif flute_type == 'airy':
            # Airy flute: lots of breath, ethereal
            tone = fundamental + 0.06 * h2 + 0.02 * h3
            breath_bw = (400, 8000)

        elif flute_type == 'choir_flute':
            # Choir flute: multiple detuned flute voices (ensemble)
            voices = []
            detune_spread = [0, -8, 8, -15, 15]  # cents
            for i, dc in enumerate(detune_spread[:3]):
                f = freq * (2 ** (dc / 1200))
                ph = np.cumsum(2 * np.pi * f * (1 + vib_lfo * (1 + 0.1 * i)) / sr)
                v = np.sin(ph) + 0.10 * np.sin(2 * ph)
                voices.append(v)
            tone = mix_signals(*voices)
            breath_bw = (600, 5000)

        else:
            # Fallback to pan flute
            tone = fundamental + 0.12 * h2 + 0.06 * h3
            breath_bw = (800, 4000)

        # ── Breath noise component ──────────────────────────────────────
        breath_amt = p['breath_amount']
        breath_raw = noise(duration, sr, color='pink')
        breath_filtered = bandpass(breath_raw, breath_bw[0], breath_bw[1], sr=sr)

        # Shape breath noise with a slightly different envelope (faster attack)
        breath_env = adsr_exp(
            attack=max(p['attack'] * 0.6, 0.005),
            decay=p['decay'] * 0.8,
            sustain=p['sustain'] * 0.6,
            release=p['release'] * 0.7,
            duration=duration,
            sr=sr,
        )
        breath = breath_filtered * breath_env * breath_amt

        # ── Mix tone + breath ───────────────────────────────────────────
        n_samples = int(sr * duration)
        tone = tone[:n_samples]
        breath = breath[:n_samples]
        signal = tone * (1 - breath_amt * 0.3) + breath

        # Apply main amplitude envelope
        signal = signal * env[:n_samples]

        # ── Brightness (low-pass filter) ────────────────────────────────
        brightness = p['brightness']
        cutoff = 1500 + brightness * 8000  # range 1500 - 9500 Hz
        signal = lowpass(signal, cutoff, sr=sr)

        # ── High-pass to remove sub rumble ──────────────────────────────
        signal = highpass(signal, 120, sr=sr)

        # ── Type-specific post-processing ───────────────────────────────
        if flute_type == 'ethnic':
            # Gentle tape saturation for warmth
            signal = saturate(signal, drive=0.08, sat_type='tape')

        # ── Chorus (param-driven, applies to all types if mix > 0) ────
        chorus_mix = p['chorus_mix']
        if chorus_mix > 0:
            signal = chorus(signal, sr=sr, rate=1.0, depth=0.003, mix=chorus_mix)

        # ── EQ shaping (param-driven) ─────────────────────────────────
        signal = eq_3band(signal, sr=sr,
                          low_gain_db=p['eq_low'],
                          mid_gain_db=p['eq_mid'],
                          high_gain_db=p['eq_high'])

        # ── Effects chain ───────────────────────────────────────────────
        if p['delay_mix'] > 0:
            signal = delay_effect(signal, sr=sr, time_ms=p['delay_ms'],
                                  feedback=0.25, mix=p['delay_mix'])

        if p['reverb_wet'] > 0:
            signal = reverb(signal, sr=sr, room_size=p['reverb_size'],
                            damping=0.4, wet=p['reverb_wet'])

        # ── Stereo width (extract left channel for mono export) ───────
        if p['stereo_width'] > 0:
            stereo = stereo_spread(signal, width=p['stereo_width'], sr=sr)
            signal = stereo[:, 0]

        # ── Normalize ───────────────────────────────────────────────────
        signal = normalize(signal, 0.9)

        return signal
