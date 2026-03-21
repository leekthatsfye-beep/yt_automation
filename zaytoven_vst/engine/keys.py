"""FY3 Zaytoven Collection — Keys instrument model (clavinet, vibes, marimba, etc.)."""

import numpy as np
from engine.oscillators import sine, pulse, fm_oscillator, noise, harmonic_stack
from engine.envelope import adsr, adsr_exp, percussive, lfo
from engine.filters import lowpass, highpass, bandpass
from engine.effects import reverb, chorus, delay_effect, saturate, eq_3band, compress, tremolo as tremolo_effect
from engine.utils import midi_to_freq, normalize, stereo_spread, mix_signals


class Keys:
    """Multi-type keyboard instrument: clavinet, vibraphone, marimba, harpsichord, celesta."""

    def __init__(self, sr: int = 48000):
        self.sr = sr

    def render(self, note: int, duration: float, params: dict) -> np.ndarray:
        freq = midi_to_freq(note)
        key_type = params.get("key_type", "clavinet")

        if key_type == "clavinet":
            audio = self._render_clavinet(freq, duration, params)
        elif key_type == "vibraphone":
            audio = self._render_vibraphone(freq, duration, params)
        elif key_type == "marimba":
            audio = self._render_marimba(freq, duration, params)
        elif key_type == "harpsichord":
            audio = self._render_harpsichord(freq, duration, params)
        elif key_type == "celesta":
            audio = self._render_celesta(freq, duration, params)
        else:
            audio = self._render_clavinet(freq, duration, params)

        # Apply effects chain
        audio = self._apply_effects(audio, params)
        return normalize(audio)

    def _render_clavinet(self, freq: float, duration: float, params: dict) -> np.ndarray:
        """Clavinet D6 — funky, bright, plucky.

        Enhanced with pickup selection simulation:
        - 'both': both pickups (default, full frequency range)
        - 'neck': neck pickup only (warmer, more fundamental)
        - 'bridge': bridge pickup only (brighter, more harmonics)
        Each pickup position emphasizes different parts of the string's spectrum.
        """
        brightness = params.get("brightness", 0.7)
        pickup = params.get("pickup", "both")
        n = int(self.sr * duration)

        # Pulse wave with variable duty for that nasal clavinet tone
        duty = 0.3 + brightness * 0.2
        body = pulse(freq, duty, duration, self.sr)

        # Add harmonics for richness
        h2 = sine(freq * 2, duration, self.sr) * 0.3
        h3 = sine(freq * 3, duration, self.sr) * 0.15 * brightness
        h4 = sine(freq * 4, duration, self.sr) * 0.08 * brightness
        h5 = sine(freq * 5, duration, self.sr) * 0.04 * brightness if freq * 5 < self.sr / 2 else np.zeros(n)

        signal = body * 0.6 + h2 + h3 + h4[:len(body)] + h5[:len(body)]

        # Percussive envelope — fast attack, medium decay
        decay_time = params.get("decay_time", 1.5)
        env = percussive(attack=0.001, decay=decay_time, duration=duration, sr=self.sr, curve=4.0)
        signal *= env

        # Pick noise (string pluck transient)
        pick = noise(duration, self.sr, "white")
        pick = bandpass(pick, 1000, 8000, self.sr)
        pick_env = percussive(attack=0.0005, decay=0.02, duration=duration, sr=self.sr, curve=15)
        signal += pick * pick_env * 0.15

        # --- Pickup selection affects filtering ---
        if pickup == "neck":
            # Neck pickup: warmer, emphasizes fundamentals
            cutoff = 1500 + brightness * 3000
            signal = lowpass(signal, cutoff, self.sr, order=2, resonance=0.15)
            signal = eq_3band(signal, self.sr, low_gain_db=2, mid_gain_db=0, high_gain_db=-2)
        elif pickup == "bridge":
            # Bridge pickup: brighter, emphasizes harmonics
            cutoff = 3000 + brightness * 8000
            signal = lowpass(signal, cutoff, self.sr, order=2, resonance=0.3)
            signal = eq_3band(signal, self.sr, low_gain_db=-1, mid_gain_db=1, high_gain_db=3)
        else:
            # Both pickups: full range
            cutoff = 2000 + brightness * 6000
            signal = lowpass(signal, cutoff, self.sr, order=2, resonance=0.2)

        # Saturation for bite
        dist = params.get("distortion", 0.15)
        if dist > 0:
            signal = saturate(signal, dist, "tube")

        return signal

    def _render_vibraphone(self, freq: float, duration: float, params: dict) -> np.ndarray:
        """Vibraphone — warm, sustained, with motor-driven vibrato.

        Enhanced with realistic motor vibrato simulation:
        - Motor speed affects both amplitude and subtle pitch modulation
        - Spinning disc creates periodic opening/closing of resonator tubes
        - Motor can be on/off (motor_on parameter)
        - Richer harmonic content from metal bar resonance
        """
        n = int(self.sr * duration)
        t = np.arange(n) / self.sr

        # FM synthesis for metallic bar tone
        mod_idx = params.get("mod_index", 2.0)
        carrier = fm_oscillator(freq, freq * 4, mod_idx, duration, self.sr,
                                percussive(0.001, 2.0, duration, self.sr, 3))
        # Fundamental reinforcement
        fund = sine(freq, duration, self.sr) * 0.5
        # Octave partial
        oct = sine(freq * 2, duration, self.sr) * 0.15
        # Add 3rd partial for richer bar tone
        third = sine(freq * 3, duration, self.sr) * 0.06 if freq * 3 < self.sr / 2 else np.zeros(n)

        signal = carrier * 0.5 + fund + oct + third[:len(fund)]

        # Percussive with long sustain
        decay_time = params.get("decay_time", 3.0)
        env = percussive(attack=0.001, decay=decay_time, duration=duration, sr=self.sr, curve=2.5)
        signal *= env

        # --- Motor-driven vibrato ---
        motor_on = params.get("motor_on", True)
        if motor_on:
            vib_rate = params.get("vibrato_rate", 4.5)
            vib_depth = params.get("vibrato_depth", 0.15)

            # Real vibraphone motor spins discs that open/close resonator tubes
            # This creates both amplitude modulation (primary) and subtle
            # pitch/timbre modulation (secondary)

            # Primary: amplitude modulation from resonator opening/closing
            motor_am = 1.0 - vib_depth * (1 + np.sin(2 * np.pi * vib_rate * t)) / 2

            # Secondary: subtle pitch modulation from standing wave interaction
            pitch_mod = np.sin(2 * np.pi * vib_rate * t + 0.3) * 0.002 * vib_depth
            # Apply pitch mod via phase accumulation
            pitch_signal = np.sin(np.cumsum(2 * np.pi * freq * (1 + pitch_mod) / self.sr))
            signal = signal * motor_am * 0.85 + pitch_signal * env[:len(pitch_signal)] * 0.15

            # Motor also creates subtle spectral modulation
            # (higher harmonics modulate more than lower ones)
            spectral_mod = 1.0 - vib_depth * 0.3 * (1 + np.sin(2 * np.pi * vib_rate * 2 * t + 1.0)) / 2
            signal *= spectral_mod

        # Mallet noise (richer transient)
        mallet = noise(duration, self.sr, "white")
        mallet = bandpass(mallet, 2000, 8000, self.sr)
        mallet_env = percussive(0.0005, 0.008, duration, self.sr, 18)
        # Add tuned mallet component for pitch clarity
        mallet_tuned = sine(freq * 4, duration, self.sr) * 0.03
        mallet_tuned = mallet_tuned[:len(mallet_env)] * mallet_env
        signal += mallet * mallet_env * 0.08 + mallet_tuned[:len(signal)]

        return signal

    def _render_marimba(self, freq: float, duration: float, params: dict) -> np.ndarray:
        """Marimba — wooden, warm, fast decay.

        Enhanced with dead stroke option: when the mallet is pressed into
        the bar after striking, it stops the vibration abruptly, creating
        a very short, percussive 'thunk' sound used in rhythmic playing.
        """
        dead_stroke = params.get("dead_stroke", False)

        # FM for wooden bar tone
        mod_idx = params.get("mod_index", 1.5)
        carrier = fm_oscillator(freq, freq * 3.98, mod_idx, duration, self.sr,
                                percussive(0.001, 0.3, duration, self.sr, 8))

        # Strong fundamental
        fund = sine(freq, duration, self.sr) * 0.7
        # 4th harmonic for wood character
        h4 = sine(freq * 4, duration, self.sr) * 0.1
        # Add subtle 2nd harmonic for warmth
        h2 = sine(freq * 2, duration, self.sr) * 0.08

        signal = carrier * 0.3 + fund + h4 + h2[:len(fund)]

        # Decay envelope — dead stroke is much shorter
        if dead_stroke:
            decay_time = min(params.get("decay_time", 0.8), 0.08)  # very short
            env = percussive(attack=0.001, decay=decay_time, duration=duration,
                             sr=self.sr, curve=12.0)  # steep curve
        else:
            decay_time = params.get("decay_time", 0.8)
            env = percussive(attack=0.001, decay=decay_time, duration=duration,
                             sr=self.sr, curve=5.0)
        signal *= env

        # Wood thunk transient (more prominent in dead stroke)
        thunk = noise(duration, self.sr, "pink")
        thunk = bandpass(thunk, 500, 3000, self.sr)
        thunk_level = 0.2 if dead_stroke else 0.12
        thunk_env = percussive(0.0003, 0.008, duration, self.sr, 18)
        signal += thunk * thunk_env * thunk_level

        # Low-pass for warmth
        cutoff = params.get("filter_cutoff", 4000)
        signal = lowpass(signal, cutoff, self.sr, order=3)

        return signal

    def _render_harpsichord(self, freq: float, duration: float, params: dict) -> np.ndarray:
        """Harpsichord — bright, metallic, plucked string."""
        brightness = params.get("brightness", 0.8)

        # Rich harmonic content — sawtooth-like
        harmonics = list(range(1, 16))
        amps = [1.0 / (h ** 0.5) * (brightness ** (h * 0.1)) for h in harmonics]
        signal = harmonic_stack(freq, [float(h) for h in harmonics], amps, duration, self.sr)

        # Fast pluck envelope
        decay_time = params.get("decay_time", 1.2)
        env = percussive(attack=0.0005, decay=decay_time, duration=duration, sr=self.sr, curve=4.5)
        signal *= env

        # Pluck transient (quill attack)
        pluck = noise(duration, self.sr, "white")
        pluck = highpass(pluck, 3000, self.sr, 3)
        pluck_env = percussive(0.0002, 0.003, duration, self.sr, 25)
        signal += pluck * pluck_env * 0.2

        # Characteristic bright filter
        cutoff = 3000 + brightness * 5000
        signal = lowpass(signal, cutoff, self.sr, order=2)

        return signal

    def _render_celesta(self, freq: float, duration: float, params: dict) -> np.ndarray:
        """Celesta — delicate, bell-like piano."""
        # FM for bell-like quality
        mod_idx = params.get("mod_index", 2.5)
        bell = fm_oscillator(freq, freq * 2, mod_idx, duration, self.sr,
                             percussive(0.001, 1.5, duration, self.sr, 4))

        # Pure fundamental
        fund = sine(freq, duration, self.sr) * 0.4
        # Upper shimmer
        shimmer = sine(freq * 3, duration, self.sr) * 0.1

        signal = bell * 0.5 + fund + shimmer

        # Medium percussive decay
        decay_time = params.get("decay_time", 2.0)
        env = percussive(attack=0.001, decay=decay_time, duration=duration, sr=self.sr, curve=3.5)
        signal *= env

        # Hammer strike
        strike = noise(duration, self.sr, "white")
        strike = bandpass(strike, 3000, 10000, self.sr)
        strike_env = percussive(0.0003, 0.004, duration, self.sr, 20)
        signal += strike * strike_env * 0.06

        return signal

    def _apply_effects(self, audio: np.ndarray, params: dict) -> np.ndarray:
        """Apply effects chain.

        Enhanced with tremolo and phaser options for Rhodes and other keys.
        """
        key_type = params.get("key_type", "clavinet")

        # --- Tremolo (especially for Rhodes) ---
        trem_rate = params.get("tremolo_rate", 0.0)
        trem_depth = params.get("tremolo_depth", 0.0)
        if trem_rate > 0 and trem_depth > 0:
            audio = tremolo_effect(audio, self.sr, rate=trem_rate, depth=trem_depth)

        # --- Phaser (for Rhodes and Wurlitzer) ---
        phaser_rate = params.get("phaser_rate", 0.0)
        phaser_depth = params.get("phaser_depth", 0.0)
        if phaser_rate > 0 and phaser_depth > 0:
            # Simple phaser simulation using allpass filtering with LFO
            n = len(audio)
            t = np.arange(n) / self.sr
            from scipy import signal as sig
            phaser_out = audio.copy()

            # 4-stage allpass phaser
            for stage in range(4):
                # LFO modulates the allpass center frequency
                lfo_val = lfo(rate=phaser_rate, depth=phaser_depth,
                              shape='sine', duration=len(audio) / self.sr, sr=self.sr)
                center_freq = 500 + 2000 * (lfo_val[:n] + 1) / 2 * (stage + 1) * 0.25
                # Process in blocks
                block_size = self.sr // 30
                for start in range(0, n, block_size):
                    end = min(start + block_size, n)
                    mid = (start + end) // 2
                    cf = np.clip(center_freq[min(mid, n - 1)], 50, self.sr * 0.45)
                    # Simple allpass approximation
                    nyq = self.sr / 2
                    wn = cf / nyq
                    wn = np.clip(wn, 0.01, 0.99)
                    b_ap, a_ap = sig.butter(1, wn, btype='low')
                    block = phaser_out[start:end]
                    if len(block) > 3:
                        filtered = sig.lfilter(b_ap, a_ap, block)
                        phaser_out[start:end] = block - filtered * phaser_depth

            # Mix phaser with dry signal
            audio = audio * 0.6 + phaser_out * 0.4

        # EQ
        eq_lo = params.get("eq_low", 0)
        eq_mid = params.get("eq_mid", 0)
        eq_hi = params.get("eq_high", 0)
        if eq_lo != 0 or eq_mid != 0 or eq_hi != 0:
            audio = eq_3band(audio, self.sr, eq_lo, eq_mid, eq_hi)

        # Chorus
        ch_mix = params.get("chorus_mix", 0)
        if ch_mix > 0:
            audio = chorus(audio, self.sr, rate=1.8, depth=0.003, mix=ch_mix)

        # Reverb
        rev_wet = params.get("reverb_wet", 0.2)
        rev_size = params.get("reverb_size", 0.4)
        if rev_wet > 0:
            audio = reverb(audio, self.sr, rev_size, 0.5, rev_wet)

        # Delay
        dly_mix = params.get("delay_mix", 0)
        dly_ms = params.get("delay_ms", 250)
        if dly_mix > 0:
            audio = delay_effect(audio, self.sr, dly_ms, 0.3, dly_mix)

        # Stereo spread
        width = params.get("stereo_width", 0.25)
        audio = stereo_spread(audio, width, self.sr)

        return audio[:, 0] if audio.ndim > 1 else audio  # return mono for further processing
