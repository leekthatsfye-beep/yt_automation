"""FY3 Zaytoven Collection — Piano instrument models.

Covers grand piano, Rhodes electric piano, Wurlitzer, upright piano,
and felt piano. Each type uses a different synthesis technique to
capture its characteristic timbre.
"""

import numpy as np

from engine.oscillators import sine, fm_oscillator, harmonic_stack, noise
from engine.envelope import adsr, adsr_exp, percussive, lfo
from engine.filters import lowpass, highpass, bandpass
from engine.effects import reverb, chorus, delay_effect, saturate, eq_3band, compress, tremolo
from engine.utils import midi_to_freq, normalize, stereo_spread, mix_signals


# Piano string harmonic amplitudes by register
# Lower notes have richer harmonics; higher notes are more sinusoidal
def _piano_harmonic_profile(freq: float, brightness: float, n_harmonics: int = 24) -> tuple:
    """Generate harmonic ratios and amplitudes for piano strings.

    Real piano strings have inharmonicity — higher partials are
    progressively sharper than integer multiples of the fundamental.
    The inharmonicity coefficient B depends on string stiffness.
    Enhanced with more realistic spectral modeling.
    """
    harmonics = []
    amplitudes = []

    # Inharmonicity: more realistic values based on frequency register
    # Real piano B ranges from ~0.00005 (bass) to ~0.012 (treble)
    if freq < 100:
        B = 0.0002
    elif freq < 200:
        B = 0.0004
    elif freq < 400:
        B = 0.001
    elif freq < 800:
        B = 0.002
    elif freq < 1500:
        B = 0.005
    else:
        B = 0.01

    for n in range(1, n_harmonics + 1):
        # Inharmonic partial frequency: f_n = n * f0 * sqrt(1 + B * n^2)
        ratio = n * np.sqrt(1 + B * n * n)
        harmonics.append(ratio)

        # More sophisticated amplitude rolloff
        # Lower notes have richer harmonics, higher notes simpler
        rolloff = 1.0 + (1.0 - brightness) * 2.0
        amp = 1.0 / (n ** rolloff)

        # Piano has strong odd harmonics (string struck at ~1/7 length)
        # This creates a dip at the 7th harmonic and emphasis on odds
        if n % 2 == 1:
            amp *= 1.2

        # Hammer position suppresses certain partials
        # Piano hammer strikes at ~1/7-1/9 of string length
        hammer_pos = 7.0
        if abs(n % hammer_pos) < 0.5:
            amp *= 0.4  # suppress at hammer node

        # Very high partials decay faster
        if n > 12:
            amp *= 0.6

        amplitudes.append(amp)

    return harmonics, amplitudes


class Piano:
    """Multi-type piano synthesizer.

    Supports grand piano, Rhodes, Wurlitzer, upright, and felt piano.
    Each type uses the synthesis technique most appropriate to its
    real-world sound generation mechanism.

    Parameters
    ----------
    sr : int
        Sample rate (default 44100).
    """

    def __init__(self, sr: int = 48000):
        self.sr = sr

    def _hammer_noise(
        self,
        freq: float,
        duration: float,
        hardness: float,
    ) -> np.ndarray:
        """Generate hammer impact noise with multiple stages and felt absorption.

        Real piano hammers create a complex multi-stage transient:
        1. Initial felt compression (very short, soft) with absorption model
        2. String excitation burst (broader spectrum)
        3. Soundboard impulse response (resonant coloring)
        4. Felt absorption: softer hammers absorb more high-frequency energy

        Enhanced with felt absorption model — hardness controls how much
        high-frequency energy the felt absorbs during contact. Soft felt
        creates a muffled, warm attack; hard felt creates a bright, percussive one.
        """
        contact_time = 0.003 + (1.0 - hardness) * 0.005
        n_samples = int(self.sr * duration)

        # Stage 1: Felt compression — very short, filtered noise
        # Enhanced: felt absorption reduces HF content for softer hammers
        felt_dur = contact_time * 0.4
        felt = noise(felt_dur, self.sr, color="pink")
        # Felt absorption model: softer hammers roll off more highs
        felt_cutoff = 800 + hardness * 5200  # range: 800Hz (soft) to 6000Hz (hard)
        felt = lowpass(felt, felt_cutoff, self.sr, order=2)
        # Add secondary felt resonance for complex attack
        felt_resonance = noise(felt_dur, self.sr, color="brown")
        felt_resonance = bandpass(felt_resonance, 200, 1200, self.sr, order=2)
        felt = felt + felt_resonance * (1.0 - hardness) * 0.3

        # Stage 2: String excitation — broader spectrum burst
        excite_dur = contact_time * 0.8
        excite = noise(excite_dur, self.sr, color="white")
        excite_cutoff = 2500 + hardness * 10000
        excite = lowpass(excite, excite_cutoff, self.sr, order=2)

        # Add tuned component — hammer excites string modes
        t_excite = np.arange(len(excite)) / self.sr
        excite += 0.35 * np.sin(2 * np.pi * freq * t_excite) * hardness
        excite += 0.15 * np.sin(2 * np.pi * freq * 2 * t_excite) * hardness
        excite += 0.08 * np.sin(2 * np.pi * freq * 3 * t_excite) * hardness
        # Additional higher partials for hard hammers
        if hardness > 0.5 and freq * 5 < self.sr / 2:
            excite += 0.04 * np.sin(2 * np.pi * freq * 5 * t_excite) * (hardness - 0.5) * 2
        if hardness > 0.6 and freq * 7 < self.sr / 2:
            excite += 0.02 * np.sin(2 * np.pi * freq * 7 * t_excite) * (hardness - 0.6) * 2.5

        # Stage 3: Soundboard thump — low-frequency resonance
        thump_dur = 0.008
        thump = noise(thump_dur, self.sr, color="brown")
        thump = lowpass(thump, 400, self.sr, order=2)

        # Combine stages with envelopes
        felt_env = percussive(attack=0.0002, decay=felt_dur * 0.8,
                             duration=felt_dur, sr=self.sr, curve=18.0)
        felt = felt[:len(felt_env)] * felt_env * 0.3

        excite_env = percussive(attack=0.0003, decay=contact_time,
                               duration=excite_dur, sr=self.sr, curve=12.0)
        excite = excite[:len(excite_env)] * excite_env * 0.6

        thump_env = percussive(attack=0.0005, decay=0.006,
                              duration=thump_dur, sr=self.sr, curve=10.0)
        thump = thump[:len(thump_env)] * thump_env * 0.25

        # Assemble into full-length buffer
        full = np.zeros(n_samples)
        felt_len = min(len(felt), n_samples)
        full[:felt_len] += felt[:felt_len]
        excite_len = min(len(excite), n_samples)
        full[:excite_len] += excite[:excite_len]
        thump_len = min(len(thump), n_samples)
        full[:thump_len] += thump[:thump_len]

        return full

    def _string_resonance(
        self,
        freq: float,
        duration: float,
        brightness: float,
        decay_time: float,
        detune_cents: float,
        sustain_pedal: float = 0.0,
    ) -> np.ndarray:
        """Generate piano string vibration with sympathetic resonance.

        Uses additive synthesis with inharmonic partials and subtle
        detuning between string pairs (most piano notes have 2-3
        strings tuned very slightly apart for richness).

        Enhanced with:
        - Sympathetic string resonance between harmonics (other strings vibrate)
        - Sustain pedal resonance simulation (all undamped strings ring)
        - Richer undamped harmonic tail
        """
        n_harmonics = min(24, int(self.sr / (2 * freq)))
        harmonics, amplitudes = _piano_harmonic_profile(freq, brightness, n_harmonics)

        n_samples = int(self.sr * duration)
        t = np.arange(n_samples) / self.sr

        # String 1: reference pitch
        string1 = np.zeros(n_samples)
        for h, a in zip(harmonics, amplitudes):
            partial_freq = freq * h
            if partial_freq >= self.sr / 2:
                break
            string1 += a * np.sin(2 * np.pi * partial_freq * t)

        # String 2: slightly detuned (piano strings are never perfectly in tune)
        freq2 = freq * (2 ** (detune_cents / 1200))
        string2 = np.zeros(n_samples)
        for h, a in zip(harmonics, amplitudes):
            partial_freq = freq2 * h
            if partial_freq >= self.sr / 2:
                break
            string2 += a * np.sin(2 * np.pi * partial_freq * t + np.random.uniform(0, 0.3))

        # String 3 (for middle register notes, 3 strings per note)
        if 200 < freq < 2000:
            freq3 = freq * (2 ** (-detune_cents * 0.7 / 1200))
            string3 = np.zeros(n_samples)
            for h, a in zip(harmonics, amplitudes):
                partial_freq = freq3 * h
                if partial_freq >= self.sr / 2:
                    break
                string3 += a * np.sin(2 * np.pi * partial_freq * t + np.random.uniform(0, 0.5))
            combined = (string1 * 0.36 + string2 * 0.34 + string3 * 0.30)
        else:
            combined = (string1 * 0.52 + string2 * 0.48)

        # --- Sympathetic string resonance ---
        # When a string vibrates, other strings whose harmonics align
        # will also resonate sympathetically. This adds a subtle halo of
        # pitched resonance that gives grand pianos their rich, complex tail.
        sympathetic = np.zeros(n_samples)
        # Octave resonance (strongest sympathetic coupling)
        octave_freq = freq * 2
        if octave_freq < self.sr / 2:
            sympathetic += np.sin(2 * np.pi * octave_freq * t) * 0.015
        # Perfect fifth resonance
        fifth_freq = freq * 1.5
        if fifth_freq < self.sr / 2:
            sympathetic += np.sin(2 * np.pi * fifth_freq * t) * 0.008
        # Sub-octave resonance
        sub_freq = freq / 2
        if sub_freq > 20:
            sympathetic += np.sin(2 * np.pi * sub_freq * t) * 0.01
        # Sympathetic resonance has delayed onset and slow decay
        if np.max(np.abs(sympathetic)) > 0:
            sym_env = percussive(attack=0.05, decay=decay_time * 1.5,
                                 duration=duration, sr=self.sr, curve=2.0)
            sympathetic = sympathetic[:len(sym_env)] * sym_env
            combined = combined + sympathetic[:n_samples]

        # --- Sustain pedal resonance ---
        # When sustain pedal is down, all undamped strings resonate freely
        # creating a wash of pitched resonance from the entire piano frame
        if sustain_pedal > 0:
            pedal_resonance = np.zeros(n_samples)
            # Multiple sympathetic strings ring when pedal is down
            # Create a subtle cloud of harmonically related pitches
            pedal_partials = [0.5, 1.0, 1.5, 2.0, 3.0, 4.0, 5.0, 6.0]
            for ratio in pedal_partials:
                p_freq = freq * ratio
                if p_freq < self.sr / 2 and p_freq > 30:
                    # Slight random detuning for each sympathetic string
                    p_detune = np.random.uniform(-3, 3)
                    p_freq *= 2 ** (p_detune / 1200)
                    amp = 0.008 / max(ratio, 1.0)
                    pedal_resonance += np.sin(2 * np.pi * p_freq * t) * amp

            # Pedal resonance has very slow attack and long decay
            pedal_env = percussive(attack=0.1, decay=decay_time * 2.0,
                                   duration=duration, sr=self.sr, curve=1.8)
            pedal_resonance = pedal_resonance[:len(pedal_env)] * pedal_env
            # Low-pass to simulate soundboard filtering of sympathetic vibrations
            pedal_resonance = lowpass(pedal_resonance, 4000, self.sr, order=1)
            combined = combined + pedal_resonance[:n_samples] * sustain_pedal

        # Apply decay envelope — piano notes decay exponentially
        # Lower notes decay slower, higher notes faster
        freq_factor = np.clip(200 / max(freq, 50), 0.3, 3.0)
        effective_decay = decay_time * freq_factor

        # --- Richer undamped harmonic tail ---
        # Real piano strings have two decay phases: initial fast decay
        # and a longer "aftersound" tail from the duplex scaling
        env_main = percussive(attack=0.001, decay=effective_decay,
                              duration=duration, sr=self.sr, curve=3.5)
        # Long, quiet tail (duplex/undamped section of string)
        env_tail = percussive(attack=0.05, decay=effective_decay * 2.5,
                              duration=duration, sr=self.sr, curve=1.5)
        # Blend: main envelope dominates, tail adds the lingering resonance
        env = env_main * 0.92 + env_tail * 0.08
        combined *= env[:n_samples]

        return combined

    def _render_grand(
        self,
        freq: float,
        duration: float,
        brightness: float,
        hammer_hardness: float,
        decay_time: float,
        detune_cents: float,
        sustain_pedal: float = 0.0,
    ) -> np.ndarray:
        """Grand piano: rich harmonics, hammer noise, long sustain."""
        # String vibration
        strings = self._string_resonance(freq, duration, brightness,
                                         decay_time, detune_cents, sustain_pedal)

        # Hammer impact
        hammer = self._hammer_noise(freq, duration, hammer_hardness)

        # Soundboard resonance: adds low-end warmth
        # The soundboard amplifies lower partials
        soundboard = lowpass(strings, 600, self.sr, order=1) * 0.15
        soundboard_env = percussive(attack=0.005, decay=decay_time * 0.7,
                                    duration=duration, sr=self.sr, curve=2.5)
        n = min(len(soundboard), len(soundboard_env))
        soundboard[:n] *= soundboard_env[:n]

        return mix_signals(strings, hammer, soundboard,
                           levels=[0.75, 0.15, 0.10])

    def _render_upright(
        self,
        freq: float,
        duration: float,
        brightness: float,
        hammer_hardness: float,
        decay_time: float,
        detune_cents: float,
        sustain_pedal: float = 0.0,
    ) -> np.ndarray:
        """Upright piano: more inharmonicity, slightly muffled, honky-tonk character."""
        # More detuning between strings for upright "honky" character
        strings = self._string_resonance(freq, duration,
                                         brightness * 0.85,
                                         decay_time * 0.8,
                                         detune_cents * 2.5,
                                         sustain_pedal * 0.7)

        hammer = self._hammer_noise(freq, duration, hammer_hardness * 0.8)

        # Upright has less soundboard resonance, more boxy midrange
        boxiness = bandpass(strings, 300, 2500, self.sr, order=2) * 0.12

        return mix_signals(strings, hammer, boxiness,
                           levels=[0.75, 0.12, 0.13])

    def _render_felt(
        self,
        freq: float,
        duration: float,
        brightness: float,
        decay_time: float,
        detune_cents: float,
    ) -> np.ndarray:
        """Felt piano: heavily damped, soft attack, intimate lo-fi character."""
        # Very low brightness for muffled tone
        strings = self._string_resonance(freq, duration,
                                         brightness * 0.4,
                                         decay_time * 1.2,
                                         detune_cents * 1.5)

        # Heavy low-pass filtering (felt strip dampens high frequencies)
        strings = lowpass(strings, 1200 + brightness * 2000, self.sr, order=3)

        # Soft attack envelope (no hammer percussiveness)
        n_samples = int(self.sr * duration)
        soft_attack = adsr_exp(attack=0.02, decay=0.1, sustain=0.8,
                               release=0.3, duration=duration, sr=self.sr)
        soft_attack = soft_attack[:n_samples]
        if len(strings) > len(soft_attack):
            strings = strings[:len(soft_attack)]
        elif len(soft_attack) > len(strings):
            soft_attack = soft_attack[:len(strings)]
        strings *= soft_attack

        # Add very subtle tape-style saturation for warmth
        strings = saturate(strings, drive=0.05, sat_type="tape")

        return strings

    def _render_rhodes(
        self,
        freq: float,
        duration: float,
        brightness: float,
        decay_time: float,
        mod_index: float = 0.0,
    ) -> np.ndarray:
        """Rhodes electric piano: FM synthesis with decaying modulation index.

        The Rhodes sound comes from a hammer striking a tine (thin metal
        rod) next to a tonebar. The tine vibration is picked up
        electromagnetically. The characteristic "bark" at onset comes
        from the tine's initial complex vibration settling into a
        simpler mode — perfectly modeled by FM with decaying mod index.
        """
        n_samples = int(self.sr * duration)
        t = np.arange(n_samples) / self.sr

        # FM parameters: carrier at fundamental, modulator at 1:1 ratio
        carrier_freq = freq
        mod_freq = freq  # 1:1 ratio is classic Rhodes

        # Modulation index decays over time — creates the "bark" attack
        # Higher brightness = more initial mod index = more bark
        peak_mod_index = 1.5 + brightness * 4.0
        # Scale by preset mod_index if provided (> 0)
        if mod_index > 0:
            peak_mod_index *= (0.5 + mod_index)
        mod_decay_rate = 4.0 + brightness * 3.0

        mod_envelope = peak_mod_index * np.exp(-mod_decay_rate * t)

        # Core FM tone
        modulator = mod_envelope * np.sin(2 * np.pi * mod_freq * t)
        tone = np.sin(2 * np.pi * carrier_freq * t + modulator)

        # Add second FM layer at 1:2 ratio for upper-register shimmer
        if freq > 300:
            mod2_envelope = (peak_mod_index * 0.3) * np.exp(-(mod_decay_rate * 1.5) * t)
            modulator2 = mod2_envelope * np.sin(2 * np.pi * freq * 2 * t)
            tone2 = np.sin(2 * np.pi * carrier_freq * t + modulator2) * 0.2
            tone = tone * 0.85 + tone2

        # Add subtle bell-like partial (characteristic of real Rhodes)
        bell_partial = sine(freq * 4, duration, self.sr)
        bell_env = percussive(attack=0.001, decay=0.15,
                              duration=duration, sr=self.sr, curve=10.0)
        bell_partial = bell_partial[:len(bell_env)] * bell_env * 0.06

        tone[:len(bell_partial)] += bell_partial[:len(tone)]

        # Tine envelope: fast attack, long sustain with slow decay
        freq_factor = np.clip(300 / max(freq, 80), 0.4, 2.5)
        env = percussive(attack=0.001, decay=decay_time * freq_factor,
                         duration=duration, sr=self.sr, curve=2.5)
        tone *= env

        return tone

    def _render_wurlitzer(
        self,
        freq: float,
        duration: float,
        brightness: float,
        decay_time: float,
        mod_index: float = 0.0,
    ) -> np.ndarray:
        """Wurlitzer electric piano: reed-based FM with more bite than Rhodes.

        The Wurlitzer uses a steel reed struck by a hammer. The sound
        is more nasal and reedy than Rhodes, with a distinctive
        "growl" in the midrange. Uses asymmetric FM for the reed
        characteristic.
        """
        n_samples = int(self.sr * duration)
        t = np.arange(n_samples) / self.sr

        # Wurlitzer FM: carrier at fundamental, mod at ~1:1 but with
        # additional 1:3 ratio for reed overtones
        carrier_freq = freq
        mod_freq_1 = freq * 1.0  # fundamental ratio
        mod_freq_2 = freq * 3.0  # reed overtone ratio

        # Modulation index — more aggressive than Rhodes
        peak_mod = 2.0 + brightness * 5.0
        # Scale by preset mod_index if provided (> 0)
        if mod_index > 0:
            peak_mod *= (0.5 + mod_index)
        mod_decay = 5.0 + brightness * 4.0

        mod_env = peak_mod * np.exp(-mod_decay * t)
        mod_env_2 = (peak_mod * 0.4) * np.exp(-(mod_decay * 1.8) * t)

        # Two-operator FM
        modulator = (mod_env * np.sin(2 * np.pi * mod_freq_1 * t) +
                     mod_env_2 * np.sin(2 * np.pi * mod_freq_2 * t))
        tone = np.sin(2 * np.pi * carrier_freq * t + modulator)

        # Add reed buzz: mild distortion that increases with velocity
        tone = saturate(tone, drive=0.08 + brightness * 0.12, sat_type="tube")

        # Wurlitzer has a boxier, more nasal quality than Rhodes
        tone = bandpass(tone, 200, 4000 + brightness * 3000, self.sr, order=2)

        # Envelope: faster decay than Rhodes
        freq_factor = np.clip(250 / max(freq, 80), 0.4, 2.0)
        env = percussive(attack=0.001, decay=decay_time * freq_factor * 0.7,
                         duration=duration, sr=self.sr, curve=3.0)
        tone *= env

        return tone

    def render(
        self,
        note: int,
        duration: float,
        params: dict | None = None,
    ) -> np.ndarray:
        """Render a single piano note.

        Parameters
        ----------
        note : int
            MIDI note number (60 = C4).
        duration : float
            Note duration in seconds.
        params : dict, optional
            Synthesis parameters:
                piano_type: str        'grand', 'rhodes', 'wurlitzer',
                                       'upright', 'felt' (default 'grand')
                brightness: float      Tonal brightness 0-1 (default 0.6)
                hammer_hardness: float Hammer hardness 0-1 (default 0.5)
                decay_time: float      Decay time in seconds (default 4.0)
                attack: float          Not used for acoustic (used for felt)
                release: float         Release time seconds (default 0.3)
                reverb_wet: float      Reverb mix 0-1 (default 0.2)
                reverb_size: float     Reverb room size 0-1 (default 0.4)
                chorus_mix: float      Chorus mix 0-1 (default 0.0)
                eq_low: float          Low band gain dB (default 1.0)
                eq_mid: float          Mid band gain dB (default 0.0)
                eq_high: float         High band gain dB (default 0.5)
                detune: float          String detuning — fraction (<1 maps
                                       to cents via *30) or cents (>=1)
                                       (default 4.0 cents). Also reads
                                       legacy key "detune_cents".
                mod_index: float       FM modulation index scaler for
                                       Rhodes/Wurlitzer (default 0.0,
                                       >0 scales peak_mod by 0.5+val)
                resonance: float       Body resonance — bandpass boost
                                       around fundamental 0-1 (default 0.0)
                delay_mix: float       Delay effect mix 0-1 (default 0.0)
                delay_ms: int          Delay time in ms (default 300)
                stereo_width: float    Stereo spread amount 0-1 (default 0.0)

        Returns
        -------
        np.ndarray
            Mono audio signal.
        """
        if params is None:
            params = {}

        freq = midi_to_freq(note)

        # --- Parameter extraction ---
        piano_type = params.get("piano_type", "grand")
        brightness = params.get("brightness", 0.6)
        hammer_hardness = params.get("hammer_hardness", 0.5)
        decay_time = params.get("decay_time", 4.0)
        release = params.get("release", 0.3)
        reverb_wet = params.get("reverb_wet", 0.2)
        reverb_size = params.get("reverb_size", 0.4)
        chorus_mix = params.get("chorus_mix", 0.0)
        eq_low = params.get("eq_low", 1.0)
        eq_mid = params.get("eq_mid", 0.0)
        eq_high = params.get("eq_high", 0.5)
        detune_raw = params.get("detune", params.get("detune_cents", 4.0))
        # Presets pass detune as a fraction (0.0-0.99); convert to cents
        # Values >= 1.0 are already in cents (backward compat)
        detune_cents = detune_raw * 30.0 if detune_raw < 1.0 else detune_raw
        sustain_pedal = params.get("sustain_pedal", 0.0)
        mod_index = params.get("mod_index", 0.0)
        resonance = params.get("resonance", 0.0)

        # --- Generate base tone by type ---
        if piano_type == "grand":
            signal = self._render_grand(freq, duration, brightness,
                                        hammer_hardness, decay_time,
                                        detune_cents, sustain_pedal)
        elif piano_type == "upright":
            signal = self._render_upright(freq, duration, brightness,
                                          hammer_hardness, decay_time,
                                          detune_cents, sustain_pedal)
        elif piano_type == "felt":
            signal = self._render_felt(freq, duration, brightness,
                                       decay_time, detune_cents)
        elif piano_type == "rhodes":
            signal = self._render_rhodes(freq, duration, brightness,
                                         decay_time, mod_index=mod_index)
            # Rhodes gets default chorus and tremolo
            if chorus_mix <= 0:
                chorus_mix = 0.2
        elif piano_type == "wurlitzer":
            signal = self._render_wurlitzer(freq, duration, brightness,
                                            decay_time, mod_index=mod_index)
        else:
            # Fallback to grand
            signal = self._render_grand(freq, duration, brightness,
                                        hammer_hardness, decay_time,
                                        detune_cents)

        # --- Body resonance ---
        # Boost a narrow band around the fundamental for body emphasis
        if resonance > 0:
            reso_band = bandpass(signal, freq * 0.8, freq * 2.5, self.sr, order=2)
            signal = signal + reso_band * resonance * 0.3

        # --- Release envelope ---
        # Apply additional release fade at end of note
        n_samples = len(signal)
        release_samples = min(int(self.sr * release), n_samples // 3)
        if release_samples > 0:
            release_env = np.ones(n_samples)
            release_env[-release_samples:] = np.linspace(1, 0, release_samples)
            signal *= release_env

        # --- Effects chain ---
        # EQ
        signal = eq_3band(signal, self.sr,
                          low_gain_db=eq_low,
                          mid_gain_db=eq_mid,
                          high_gain_db=eq_high)

        # Chorus (mainly for Rhodes/Wurlitzer)
        if chorus_mix > 0:
            signal = chorus(signal, self.sr, rate=1.0, depth=0.002, mix=chorus_mix)

        # Reverb
        if reverb_wet > 0:
            signal = reverb(signal, self.sr, room_size=reverb_size,
                            damping=0.5, wet=reverb_wet)

        # Delay
        delay_mix_val = params.get("delay_mix", 0.0)
        delay_ms_val = params.get("delay_ms", 300)
        if delay_mix_val > 0:
            signal = delay_effect(signal, self.sr, time_ms=delay_ms_val,
                                  feedback=0.3, mix=delay_mix_val)

        # Light compression for consistency
        signal = compress(signal, threshold_db=-12, ratio=2.5,
                          attack_ms=10, release_ms=80, sr=self.sr)

        # Stereo width processing (engine returns mono, so take first channel)
        stereo_width = params.get("stereo_width", 0.0)
        if stereo_width > 0:
            signal = stereo_spread(signal, stereo_width, self.sr)
            if signal.ndim > 1:
                signal = signal[:, 0]

        return normalize(signal, 0.9)

    def render_chord(
        self,
        notes: list[int],
        duration: float,
        params: dict | None = None,
    ) -> np.ndarray:
        """Render a piano chord (multiple notes).

        Parameters
        ----------
        notes : list[int]
            List of MIDI note numbers.
        duration : float
            Chord duration in seconds.
        params : dict, optional
            Same as render().

        Returns
        -------
        np.ndarray
            Mono audio signal with all notes mixed.
        """
        voices = []
        for note in notes:
            voices.append(self.render(note, duration, params))

        if not voices:
            return np.zeros(int(self.sr * duration))

        return normalize(mix_signals(*voices), 0.9)
