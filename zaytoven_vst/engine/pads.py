"""FY3 Zaytoven Collection — Pad instrument model.

Supports: warm, choir, dark, atmospheric, evolving, digital
Pads use multiple detuned oscillators with very slow attacks, rich
filtering, and lush effects for sustained textural backdrops.
"""

import numpy as np

from engine.oscillators import sawtooth, sine, triangle, noise, harmonic_stack, wavetable_morph, sub_oscillator, supersaw
from engine.envelope import adsr, adsr_exp, lfo
from engine.filters import lowpass, highpass, bandpass, filter_sweep
from engine.effects import reverb, chorus, delay_effect, saturate, eq_3band, compress
from engine.utils import midi_to_freq, normalize, stereo_spread, mix_signals, detune_unison


class Pad:
    """Pad synthesizer for sustained, textural backgrounds."""

    TYPES = ('warm', 'choir', 'dark', 'atmospheric', 'evolving', 'digital')

    def __init__(self, sr: int = 48000):
        self.sr = sr

    DEFAULTS = {
        'pad_type': 'warm',
        'voices': 5,
        'detune_cents': 15,
        'filter_cutoff': 3000,
        'filter_lfo_rate': 0.1,
        'filter_lfo_depth': 0.3,
        'attack': 0.8,
        'release': 1.0,
        'reverb_wet': 0.45,
        'chorus_mix': 0.25,
        'saturation': 0.0,
    }

    def render(self, note: int, duration: float, params: dict | None = None) -> np.ndarray:
        """
        Render a single pad note.

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
        pad_type = p['pad_type']
        n_samples = int(sr * duration)

        if pad_type == 'warm':
            signal = self._render_warm(freq, duration, p, sr)
        elif pad_type == 'choir':
            signal = self._render_choir(freq, duration, p, sr)
        elif pad_type == 'dark':
            signal = self._render_dark(freq, duration, p, sr)
        elif pad_type == 'atmospheric':
            signal = self._render_atmospheric(freq, duration, p, sr)
        elif pad_type == 'evolving':
            signal = self._render_evolving(freq, duration, p, sr)
        elif pad_type == 'digital':
            signal = self._render_digital(freq, duration, p, sr)
        else:
            signal = self._render_warm(freq, duration, p, sr)

        signal = signal[:n_samples]

        # ── Saturation ──────────────────────────────────────────────────
        if p['saturation'] > 0:
            signal = saturate(signal, drive=p['saturation'] * 0.3, sat_type='tape')

        # ── Chorus ──────────────────────────────────────────────────────
        if p['chorus_mix'] > 0:
            rate = 0.6 if pad_type in ('warm', 'dark') else 1.0
            signal = chorus(signal, sr=sr, rate=rate, depth=0.005, mix=p['chorus_mix'])

        # ── Reverb ──────────────────────────────────────────────────────
        if p['reverb_wet'] > 0:
            room = {'warm': 0.55, 'choir': 0.65, 'dark': 0.5,
                     'atmospheric': 0.85, 'evolving': 0.7, 'digital': 0.4}.get(pad_type, 0.6)
            signal = reverb(signal, sr=sr, room_size=room, damping=0.5, wet=p['reverb_wet'])

        signal = normalize(signal, 0.9)
        return signal

    # ── Warm pad ────────────────────────────────────────────────────────

    def _render_warm(self, freq, duration, p, sr):
        """Warm pad: detuned saw+sine, heavy low-pass, warm saturation.

        Enhanced with:
        - Up to 9 voices for supersaw-style thickness
        - Sub-oscillator layer for weight
        - Better filter modulation with triangle LFO shape
        """
        n_voices = max(3, min(int(p['voices']), 9))
        detune = p['detune_cents']

        # Mix of sawtooth and sine unison — now up to 9 voices
        saw_stack = detune_unison(sawtooth, freq, n_voices, detune, duration, sr)
        sine_body = detune_unison(sine, freq, max(n_voices - 2, 2), detune * 0.5, duration, sr)

        raw = saw_stack * 0.6 + sine_body[:len(saw_stack)] * 0.4

        # Sub-oscillator for weight and depth
        sub = sub_oscillator(freq, duration, sr, shape='sine', octave=1)
        raw = raw + sub[:len(raw)] * 0.2

        # Very slow attack pad envelope
        env = adsr_exp(
            attack=max(p['attack'], 0.5),
            decay=0.3,
            sustain=0.85,
            release=max(p['release'], 0.6),
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Heavy low-pass with LFO modulation for movement
        base_cutoff = min(p['filter_cutoff'], 2800)
        lfo_rate = p.get('filter_lfo_rate', 0.1)
        lfo_depth = p.get('filter_lfo_depth', 0.3)

        if lfo_depth > 0 and lfo_rate > 0:
            # Triangle LFO for smoother filter movement
            n_samples = len(raw)
            t = np.arange(n_samples) / sr
            tri_lfo = lfo(rate=lfo_rate, depth=lfo_depth, shape='triangle',
                          duration=duration, sr=sr)
            cutoff_mod = base_cutoff * (1 + tri_lfo[:n_samples] * 0.3)
            cutoff_mod = np.clip(cutoff_mod, 100, sr * 0.45)
            # Apply in blocks
            block_size = sr // 20
            out = np.zeros(n_samples)
            for start in range(0, n_samples, block_size):
                end = min(start + block_size, n_samples)
                mid = (start + end) // 2
                cf = cutoff_mod[min(mid, n_samples - 1)]
                block = raw[start:end]
                padded = np.pad(block, (0, max(0, 1024 - len(block))))
                out[start:end] = lowpass(padded, cf, sr=sr, resonance=0.1)[:len(block)]
            raw = out
        else:
            raw = lowpass(raw, base_cutoff, sr=sr, resonance=0.1)

        # Warm tape saturation
        raw = saturate(raw, drive=0.08, sat_type='tape')

        # Boost lows, cut highs
        raw = eq_3band(raw, sr=sr, low_gain_db=2, mid_gain_db=0, high_gain_db=-3)
        raw = highpass(raw, 50, sr=sr)

        return raw

    # ── Choir pad ───────────────────────────────────────────────────────

    def _render_choir(self, freq, duration, p, sr):
        """Choir pad: formant-filtered noise + sine harmonics for vowel sounds."""
        n_samples = int(sr * duration)

        # Harmonic base: fundamental + octave + 5th
        harmonics = [1.0, 2.0, 3.0, 4.0, 5.0]
        amplitudes = [1.0, 0.5, 0.35, 0.15, 0.08]
        tone = harmonic_stack(freq, harmonics, amplitudes, duration, sr)

        # Formant filtering to create vowel-like character
        # Cycle through formant sets for "ooh" / "aah" feel
        formant_freqs = [
            (730, 1090, 2440),   # "ah"
            (300, 870, 2240),    # "oo"
        ]
        formant_signals = []
        for formants in formant_freqs:
            formed = np.zeros(n_samples)
            for fc in formants:
                bw = fc * 0.15  # bandwidth proportional to center freq
                low = max(fc - bw, 30)
                high = min(fc + bw, 20000)
                formed += bandpass(tone[:n_samples], low, high, sr=sr) * 0.5
            formant_signals.append(formed)

        # Crossfade between formants using slow LFO
        formant_lfo = lfo(rate=0.08, depth=1.0, shape='sine', duration=duration, sr=sr)
        crossfade = (formant_lfo[:n_samples] + 1) / 2  # 0..1
        raw = formant_signals[0] * (1 - crossfade) + formant_signals[1] * crossfade

        # Add breathy noise layer
        breath = noise(duration, sr, color='pink') * 0.06
        breath = bandpass(breath, 1000, 5000, sr=sr)

        raw = raw + breath[:len(raw)]

        # Slow envelope
        env = adsr_exp(
            attack=max(p['attack'], 0.6),
            decay=0.4,
            sustain=0.8,
            release=max(p['release'], 0.8),
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Gentle filtering
        raw = lowpass(raw, min(p['filter_cutoff'], 5000), sr=sr)
        raw = highpass(raw, 100, sr=sr)

        return raw

    # ── Dark pad ────────────────────────────────────────────────────────

    def _render_dark(self, freq, duration, p, sr):
        """Dark pad: heavily low-passed, sub-heavy, ominous."""
        n_voices = max(3, min(int(p['voices']), 6))
        detune = p['detune_cents'] * 1.3

        # Sawtooth + triangle layered
        saw_stack = detune_unison(sawtooth, freq, n_voices, detune, duration, sr)
        tri_layer = detune_unison(triangle, freq, max(n_voices - 1, 2),
                                  detune * 0.8, duration, sr)

        raw = saw_stack * 0.55 + tri_layer[:len(saw_stack)] * 0.45

        # Sub-octave for weight
        sub = sine(freq / 2, duration, sr) * 0.3
        raw = raw + sub[:len(raw)]

        env = adsr_exp(
            attack=max(p['attack'], 0.7),
            decay=0.5,
            sustain=0.85,
            release=max(p['release'], 1.0),
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Very heavy low-pass
        cutoff = min(p['filter_cutoff'], 1500)
        raw = lowpass(raw, cutoff, sr=sr, resonance=0.15)

        # Dark EQ
        raw = eq_3band(raw, sr=sr, low_gain_db=3, mid_gain_db=-1, high_gain_db=-5)
        raw = highpass(raw, 30, sr=sr)

        return raw

    # ── Atmospheric pad ─────────────────────────────────────────────────

    def _render_atmospheric(self, freq, duration, p, sr):
        """Atmospheric pad: heavy reverb + delay, ethereal texture.

        Enhanced with shimmer effect: pitch-shifted reverb tail that
        creates an otherworldly, crystalline quality.
        """
        n_voices = max(4, min(int(p['voices']), 9))
        detune = max(p['detune_cents'], 18)

        # Sine + triangle unison for pure ethereal tone
        sine_stack = detune_unison(sine, freq, n_voices, detune, duration, sr)
        tri_stack = detune_unison(triangle, freq, max(n_voices - 2, 2),
                                  detune * 0.7, duration, sr)

        raw = sine_stack * 0.6 + tri_stack[:len(sine_stack)] * 0.4

        # Sub-oscillator for depth
        sub = sub_oscillator(freq, duration, sr, shape='sine', octave=1)
        raw = raw + sub[:len(raw)] * 0.1

        # Ethereal noise texture
        air = noise(duration, sr, color='pink') * 0.04
        air = bandpass(air, 3000, 10000, sr=sr)
        raw = raw + air[:len(raw)]

        env = adsr_exp(
            attack=max(p['attack'], 1.0),
            decay=0.5,
            sustain=0.9,
            release=max(p['release'], 1.5),
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        raw = lowpass(raw, p['filter_cutoff'], sr=sr)

        # --- Shimmer effect: pitch-shifted reverb tail ---
        # Create an octave-up copy, reverb it heavily, blend quietly
        n_samples = len(raw)
        t = np.arange(n_samples) / sr
        shimmer_freq = freq * 2  # octave up
        if shimmer_freq < sr / 2:
            shimmer_tone = sine(shimmer_freq, duration, sr)
            # Add a fifth above too for crystalline quality
            fifth_freq = freq * 3
            if fifth_freq < sr / 2:
                shimmer_tone = shimmer_tone + sine(fifth_freq, duration, sr) * 0.4
            shimmer_tone = shimmer_tone[:n_samples]
            # Apply very slow envelope with long decay
            shimmer_env = adsr_exp(attack=1.5, decay=0.5, sustain=0.6,
                                   release=2.0, duration=duration, sr=sr)
            shimmer_tone = shimmer_tone[:len(shimmer_env)] * shimmer_env
            # Heavy reverb on shimmer
            shimmer_tone = reverb(shimmer_tone, sr=sr, room_size=0.9,
                                   damping=0.3, wet=0.8)
            raw = raw + shimmer_tone[:len(raw)] * 0.06

        # Delay for spaciousness
        raw = delay_effect(raw, sr=sr, time_ms=400, feedback=0.35, mix=0.2)

        raw = highpass(raw, 60, sr=sr)
        return raw

    # ── Evolving pad ────────────────────────────────────────────────────

    def _render_evolving(self, freq, duration, p, sr):
        """Evolving pad: filter cutoff modulated by slow LFO with wavetable morphing.

        Enhanced with wavetable morphing: the oscillator waveform itself
        evolves over time, blending from sine through triangle and saw to
        square, creating organic timbral evolution.
        """
        n_voices = max(4, min(int(p['voices']), 9))
        detune = p['detune_cents']
        n_samples = int(sr * duration)

        # --- Wavetable morphing: morph parameter sweeps over duration ---
        # Process in segments with different morph values
        n_segments = 8
        segment_len = n_samples // n_segments
        raw = np.zeros(n_samples)

        for seg in range(n_segments):
            start = seg * segment_len
            end = min(start + segment_len, n_samples)
            seg_duration = (end - start) / sr

            # Morph value sweeps from 0 (sine) to 1 (square) and back
            morph = 0.5 + 0.5 * np.sin(2 * np.pi * seg / n_segments)

            # Create morphed wavetable voices with detuning
            seg_signal = np.zeros(end - start)
            for i in range(n_voices):
                offset = (i - (n_voices - 1) / 2) * (detune / max(n_voices - 1, 1))
                f = freq * (2 ** (offset / 1200))
                voice = wavetable_morph(f, seg_duration, sr, morph=morph)
                seg_signal = seg_signal + voice[:len(seg_signal)]
            seg_signal /= n_voices

            # Crossfade between segments for smooth transitions
            fade_len = min(int(sr * 0.05), len(seg_signal) // 4)
            if seg > 0 and fade_len > 0:
                seg_signal[:fade_len] *= np.linspace(0, 1, fade_len)
            if seg < n_segments - 1 and fade_len > 0:
                seg_signal[-fade_len:] *= np.linspace(1, 0, fade_len)

            raw[start:end] += seg_signal[:end - start]

        # Add a sine fundamental for pitch anchor
        sine_layer = sine(freq, duration, sr) * 0.15
        raw = raw + sine_layer[:len(raw)]

        # Sub-oscillator for weight
        sub = sub_oscillator(freq, duration, sr, shape='sine', octave=1)
        raw = raw + sub[:len(raw)] * 0.15

        env = adsr_exp(
            attack=max(p['attack'], 0.6),
            decay=0.3,
            sustain=0.85,
            release=max(p['release'], 0.8),
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Evolving filter sweep driven by LFO
        lfo_rate = p['filter_lfo_rate']
        lfo_depth = p['filter_lfo_depth']
        base_cutoff = p['filter_cutoff']

        # Calculate sweep range from LFO depth
        low_cutoff = base_cutoff * (1 - lfo_depth * 0.6)
        high_cutoff = base_cutoff * (1 + lfo_depth * 0.4)
        low_cutoff = max(low_cutoff, 200)
        high_cutoff = min(high_cutoff, 18000)

        # Use multiple sweep cycles for evolving movement
        n_samples = len(raw)
        t = np.arange(n_samples) / sr
        lfo_wave = np.sin(2 * np.pi * lfo_rate * t)
        # Map LFO to cutoff range
        cutoff_curve = low_cutoff + (high_cutoff - low_cutoff) * (lfo_wave + 1) / 2

        # Process in blocks with varying cutoff
        block_size = sr // 20
        out = np.zeros(n_samples)
        for start in range(0, n_samples, block_size):
            end = min(start + block_size, n_samples)
            mid = (start + end) // 2
            cf = np.clip(cutoff_curve[min(mid, n_samples - 1)], 30, sr * 0.45)
            block = raw[start:end]
            out[start:end] = lowpass(np.pad(block, (0, max(0, 1024 - len(block)))),
                                     cf, sr=sr)[:len(block)]

        raw = out
        raw = highpass(raw, 50, sr=sr)

        return raw

    # ── Digital pad ─────────────────────────────────────────────────────

    def _render_digital(self, freq, duration, p, sr):
        """Digital pad: clean, precise, modern — less analog warmth."""
        n_voices = max(2, min(int(p['voices']), 5))
        detune = p['detune_cents'] * 0.7  # tighter tuning for digital precision

        # Triangle + sine for clean digital character
        tri_stack = detune_unison(triangle, freq, n_voices, detune, duration, sr)
        sine_layer = sine(freq, duration, sr) * 0.3
        # Add a 5th harmonic for sparkle
        fifth = sine(freq * 3, duration, sr) * 0.06

        raw = tri_stack + sine_layer[:len(tri_stack)] + fifth[:len(tri_stack)]

        env = adsr_exp(
            attack=max(p['attack'], 0.3),
            decay=0.2,
            sustain=0.9,
            release=max(p['release'], 0.5),
            duration=duration,
            sr=sr,
        )
        raw = raw[:len(env)] * env

        # Clean filter
        raw = lowpass(raw, min(p['filter_cutoff'], 6000), sr=sr, resonance=0.05)

        # Gentle compression for even level
        raw = compress(raw, threshold_db=-8, ratio=2.0, attack_ms=15, release_ms=80, sr=sr)

        raw = highpass(raw, 60, sr=sr)
        return raw
