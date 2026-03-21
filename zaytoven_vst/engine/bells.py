"""FY3 Zaytoven Collection — Bell / Chime instrument models.

FM synthesis-based bells covering music box, glockenspiel, tubular
chimes, crystal bells, church bells, and synth bells. Each type
uses different carrier:modulator ratios and decay characteristics
to produce authentic inharmonic bell spectra.
"""

import numpy as np

from engine.oscillators import sine, fm_oscillator, harmonic_stack, noise
from engine.envelope import adsr, adsr_exp, percussive, lfo
from engine.filters import lowpass, highpass, bandpass
from engine.effects import reverb, chorus, delay_effect, saturate, eq_3band, compress, tremolo
from engine.utils import midi_to_freq, normalize, stereo_spread, mix_signals


# Bell type presets: carrier:modulator ratio, mod index, decay curve, brightness
BELL_PRESETS = {
    "music_box": {
        "pairs": [(1.0, 1.0, 2.5)],       # (carrier_ratio, mod_ratio, mod_index)
        "decay_curve": 8.0,
        "brightness_cutoff": 8000,
        "attack": 0.001,
        "base_decay": 1.5,
    },
    "glockenspiel": {
        "pairs": [(1.0, 3.5, 3.0)],
        "decay_curve": 6.0,
        "brightness_cutoff": 12000,
        "attack": 0.0005,
        "base_decay": 2.5,
    },
    "tubular": {
        "pairs": [(1.0, 2.76, 2.5), (1.0, 4.07, 1.0)],
        "decay_curve": 2.5,
        "brightness_cutoff": 6000,
        "attack": 0.001,
        "base_decay": 6.0,
    },
    "crystal": {
        "pairs": [(1.0, 1.0, 1.5), (1.0, 2.0, 1.0), (1.0, 3.5, 0.5)],
        "decay_curve": 4.0,
        "brightness_cutoff": 14000,
        "attack": 0.001,
        "base_decay": 3.0,
    },
    "church_bell": {
        # Church bells have very complex inharmonic partials
        # These ratios approximate the minor-third bell spectrum
        "pairs": [
            (1.0, 2.0, 3.5),       # prime + hum note
            (1.0, 3.0, 2.0),       # tierce (minor third partial)
            (1.0, 4.07, 1.5),      # quint
            (1.0, 5.19, 1.0),      # nominal
        ],
        "decay_curve": 1.5,
        "brightness_cutoff": 5000,
        "attack": 0.002,
        "base_decay": 10.0,
    },
    "synth_bell": {
        "pairs": [(1.0, 1.4, 3.0)],
        "decay_curve": 3.5,
        "brightness_cutoff": 10000,
        "attack": 0.001,
        "base_decay": 3.0,
    },
}


class Bell:
    """FM synthesis bell / chime instrument.

    Produces a range of bell timbres from delicate music box to
    massive church bells, all based on FM synthesis with carefully
    chosen carrier:modulator ratios that create the inharmonic
    spectra characteristic of struck metal.

    Parameters
    ----------
    sr : int
        Sample rate (default 44100).
    """

    def __init__(self, sr: int = 48000):
        self.sr = sr

    def _fm_bell_pair(
        self,
        freq: float,
        duration: float,
        carrier_ratio: float,
        mod_ratio: float,
        mod_index: float,
        decay_curve: float,
        attack: float,
    ) -> np.ndarray:
        """Generate a single FM carrier-modulator bell partial.

        The key to bell sounds in FM synthesis is that the modulation
        index decays over time — the tone starts bright and complex,
        then simplifies as it dies away, just like a real struck bell.

        Enhanced with:
        - Higher modulation index support for more metallic tones
        - Slight detuning of modulator for bell chorusing
        - Secondary feedback modulation for richer partials
        """
        n_samples = int(self.sr * duration)
        t = np.arange(n_samples) / self.sr

        carrier_freq = freq * carrier_ratio
        mod_freq = freq * mod_ratio

        # Nyquist check
        if carrier_freq >= self.sr / 2 or mod_freq >= self.sr / 2:
            return np.zeros(n_samples)

        # Slight detuning of modulator for bell chorusing (each pair is unique)
        mod_detune_cents = np.random.uniform(-3, 3)
        mod_freq_detuned = mod_freq * (2 ** (mod_detune_cents / 1200))

        # Modulation envelope: decays exponentially (bell gets purer over time)
        # Support higher mod_index values for more metallic tones
        effective_index = min(mod_index, 12.0)  # cap to prevent aliasing
        mod_env = effective_index * np.exp(-decay_curve * 0.5 * t)

        # Core FM synthesis with detuned modulator
        modulator = mod_env * np.sin(2 * np.pi * mod_freq_detuned * t)

        # Secondary subtle feedback modulation for richer upper partials
        feedback_amt = min(mod_index * 0.05, 0.3)  # scales with mod_index
        if feedback_amt > 0:
            feedback_env = feedback_amt * np.exp(-decay_curve * 0.8 * t)
            tone = np.zeros(n_samples)
            phase_c = 0.0
            phase_m = 0.0
            prev = 0.0
            dt = 1.0 / self.sr
            for i in range(n_samples):
                mod = mod_env[i] * np.sin(phase_m + feedback_env[i] * prev)
                prev = np.sin(phase_c + mod)
                tone[i] = prev
                phase_c += 2 * np.pi * carrier_freq * dt
                phase_m += 2 * np.pi * mod_freq_detuned * dt
        else:
            tone = np.sin(2 * np.pi * carrier_freq * t + modulator)

        return tone

    def _strike_transient(
        self,
        freq: float,
        duration: float,
        bell_type: str,
        brightness: float,
    ) -> np.ndarray:
        """Generate the initial strike/mallet transient.

        Different bell types have different mallet characteristics:
        - Music box: tiny pin pluck, very sharp
        - Glockenspiel: hard mallet, bright click
        - Tubular: soft-ish mallet, more thud
        - Church bell: heavy clapper, low thump
        """
        n_samples = int(self.sr * duration)

        if bell_type == "music_box":
            # Pin mechanism: very short, bright click
            transient_dur = 0.002
            click = noise(transient_dur, self.sr, color="white")
            click = highpass(click, 2000, self.sr, order=2)
            env = percussive(attack=0.0001, decay=0.0015,
                             duration=transient_dur, sr=self.sr, curve=20.0)
            click = click[:len(env)] * env * brightness

        elif bell_type == "glockenspiel":
            # Hard plastic/brass mallet
            transient_dur = 0.004
            click = noise(transient_dur, self.sr, color="white")
            click = bandpass(click, 1000, 8000, self.sr, order=2)
            env = percussive(attack=0.0002, decay=0.003,
                             duration=transient_dur, sr=self.sr, curve=15.0)
            click = click[:len(env)] * env * brightness

        elif bell_type == "tubular":
            # Padded hammer strike
            transient_dur = 0.008
            click = noise(transient_dur, self.sr, color="pink")
            click = bandpass(click, 200, 3000, self.sr, order=2)
            env = percussive(attack=0.001, decay=0.006,
                             duration=transient_dur, sr=self.sr, curve=8.0)
            click = click[:len(env)] * env * brightness * 0.7

        elif bell_type == "church_bell":
            # Heavy clapper thud
            transient_dur = 0.015
            click = noise(transient_dur, self.sr, color="brown")
            click = lowpass(click, 2000, self.sr, order=2)
            # Add tuned low thump
            t_click = np.arange(len(click)) / self.sr
            click += 0.5 * np.sin(2 * np.pi * freq * 0.5 * t_click)
            env = percussive(attack=0.002, decay=0.012,
                             duration=transient_dur, sr=self.sr, curve=5.0)
            click = click[:len(env)] * env * brightness * 0.5

        elif bell_type == "crystal":
            # Light glass-like tap
            transient_dur = 0.003
            click = noise(transient_dur, self.sr, color="white")
            click = highpass(click, 3000, self.sr, order=2)
            env = percussive(attack=0.0001, decay=0.002,
                             duration=transient_dur, sr=self.sr, curve=18.0)
            click = click[:len(env)] * env * brightness * 0.6

        else:  # synth_bell
            # Richer digital onset with tuned transient component
            transient_dur = 0.005
            click = noise(transient_dur, self.sr, color="white")
            click = bandpass(click, 1000, 8000, self.sr, order=2)
            # Add a tuned click at the bell's frequency for pitch clarity
            t_click = np.arange(len(click)) / self.sr
            click += 0.3 * np.sin(2 * np.pi * freq * 2 * t_click) * brightness
            env = percussive(attack=0.0002, decay=0.004,
                             duration=transient_dur, sr=self.sr, curve=12.0)
            click = click[:len(env)] * env * brightness * 0.5

        # Pad to full duration
        full = np.zeros(n_samples)
        click_len = min(len(click), n_samples)
        full[:click_len] = click[:click_len]

        return full

    def _shimmer_layer(
        self,
        freq: float,
        duration: float,
        shimmer: float,
    ) -> np.ndarray:
        """Add ethereal shimmer via detuned high partials with slow beating.

        Enhanced with shimmer delay: the shimmer partials are processed
        through a short delay with feedback to create a sparkling,
        cascading tail effect on bell decays.

        Shimmer creates the "sparkle" or "singing" quality that makes
        bells sound alive. Multiple slightly detuned copies of upper
        partials create slow amplitude beating patterns.
        """
        if shimmer <= 0:
            return np.zeros(int(self.sr * duration))

        n_samples = int(self.sr * duration)
        t = np.arange(n_samples) / self.sr
        shimmer_tone = np.zeros(n_samples)

        # Create detuned copies of upper partials with more pairs for richness
        partial_ratios = [3.0, 4.0, 5.0, 7.0, 9.0, 11.0]
        for ratio in partial_ratios:
            partial_freq = freq * ratio
            if partial_freq >= self.sr / 2:
                continue

            # Three detuned copies for richer beating patterns
            detune_hz = shimmer * 2.5  # wider beating
            f1 = partial_freq - detune_hz / 2
            f2 = partial_freq
            f3 = partial_freq + detune_hz / 2

            amp = 0.12 / ratio  # amplitude decreases for higher partials

            if f1 > 0 and f3 < self.sr / 2:
                p1 = np.sin(2 * np.pi * f1 * t)
                p2 = np.sin(2 * np.pi * f2 * t) * 0.7  # center slightly quieter
                p3 = np.sin(2 * np.pi * f3 * t)
                shimmer_tone += (p1 + p2 + p3) * amp

        # Shimmer fades in slightly and decays slowly
        env = percussive(attack=0.05, decay=duration * 0.7,
                         duration=duration, sr=self.sr, curve=1.8)
        shimmer_tone *= env * shimmer

        # --- Shimmer delay: short rhythmic echoes on the shimmer tail ---
        # Creates a sparkling, cascading effect
        delay_time_ms = 120 + shimmer * 80  # 120-200ms
        delay_samples = int(self.sr * delay_time_ms / 1000)
        feedback = 0.25 * shimmer
        if delay_samples > 0 and delay_samples < n_samples:
            delayed = shimmer_tone.copy()
            for tap in range(3):  # 3 delay taps
                offset = delay_samples * (tap + 1)
                if offset < n_samples:
                    gain = feedback ** (tap + 1)
                    delayed[offset:] += shimmer_tone[:n_samples - offset] * gain
            shimmer_tone = delayed

        return shimmer_tone

    def render(
        self,
        note: int,
        duration: float,
        params: dict | None = None,
    ) -> np.ndarray:
        """Render a single bell note.

        Parameters
        ----------
        note : int
            MIDI note number (60 = C4).
        duration : float
            Note duration in seconds.
        params : dict, optional
            Synthesis parameters:
                bell_type: str       'music_box', 'glockenspiel', 'tubular',
                                     'crystal', 'church_bell', 'synth_bell'
                                     (default 'music_box')
                mod_index: float     FM modulation index 0-10 (overrides preset)
                mod_ratio: float     FM mod frequency ratio (overrides preset)
                brightness: float    Tonal brightness 0-1 (default 0.7)
                decay_time: float    Decay time in seconds (default from preset)
                shimmer: float       Detuned shimmer amount 0-1 (default 0.3)
                reverb_wet: float    Reverb mix 0-1 (default 0.4)
                reverb_size: float   Reverb room size 0-1 (not used directly,
                                     mapped internally)
                delay_mix: float     Delay effect mix 0-1 (default 0.15)
                delay_ms: float      Delay time ms (default 300)
                eq_low: float        Low band gain dB (default -2.0)
                eq_mid: float        Mid band gain dB (default 0.0)
                eq_high: float       High band gain dB (default 3.0)

        Returns
        -------
        np.ndarray
            Mono audio signal.
        """
        if params is None:
            params = {}

        freq = midi_to_freq(note)

        # --- Parameter extraction ---
        bell_type = params.get("bell_type", "music_box")
        brightness = params.get("brightness", 0.7)
        shimmer_amount = params.get("shimmer", 0.3)
        reverb_wet = params.get("reverb_wet", 0.4)
        reverb_size = params.get("reverb_size", 0.5)
        delay_mix = params.get("delay_mix", 0.15)
        delay_ms = params.get("delay_ms", 300)
        eq_low = params.get("eq_low", -2.0)
        eq_mid = params.get("eq_mid", 0.0)
        eq_high = params.get("eq_high", 3.0)

        # Get preset for this bell type
        preset = BELL_PRESETS.get(bell_type, BELL_PRESETS["music_box"])

        # Allow parameter overrides
        custom_mod_index = params.get("mod_index")
        custom_mod_ratio = params.get("mod_ratio")
        decay_time = params.get("decay_time", preset["base_decay"])
        attack_time = preset["attack"]
        decay_curve = preset["decay_curve"]
        brightness_cutoff = preset["brightness_cutoff"]

        n_samples = int(self.sr * duration)

        # --- Generate FM bell partials ---
        fm_layers = []
        for pair in preset["pairs"]:
            c_ratio, m_ratio, m_index = pair

            # Apply overrides if provided
            if custom_mod_ratio is not None:
                m_ratio = custom_mod_ratio
            if custom_mod_index is not None:
                m_index = custom_mod_index

            # Scale mod index by brightness
            effective_index = m_index * (0.3 + brightness * 0.7)

            partial = self._fm_bell_pair(
                freq, duration,
                carrier_ratio=c_ratio,
                mod_ratio=m_ratio,
                mod_index=effective_index,
                decay_curve=decay_curve,
                attack=attack_time,
            )
            fm_layers.append(partial)

        # Mix FM layers — first layer is loudest
        if fm_layers:
            weights = []
            for i in range(len(fm_layers)):
                w = 1.0 / (1 + i * 0.5)  # first=1.0, second=0.67, third=0.5, etc.
                weights.append(w)
            total_weight = sum(weights)
            weights = [w / total_weight for w in weights]
            signal = mix_signals(*fm_layers, levels=weights)
        else:
            signal = np.zeros(n_samples)

        # --- Add fundamental sine for body ---
        # Pure fundamental gives the bell its perceived pitch clarity
        fundamental = sine(freq, duration, self.sr)
        fund_env = percussive(attack=attack_time, decay=decay_time,
                              duration=duration, sr=self.sr, curve=decay_curve * 0.6)
        fundamental = fundamental[:len(fund_env)] * fund_env

        # --- Overall amplitude envelope ---
        env = percussive(attack=attack_time, decay=decay_time,
                         duration=duration, sr=self.sr, curve=decay_curve)
        signal = signal[:len(env)] * env

        # --- Mix fundamental with FM partials ---
        # More fundamental for lower-pitched bells, more FM for higher
        fund_mix = np.clip(0.4 - (freq - 261) / 2000, 0.15, 0.5)
        signal = mix_signals(signal, fundamental,
                             levels=[1.0 - fund_mix, fund_mix])

        # --- Strike transient ---
        transient = self._strike_transient(freq, duration, bell_type, brightness)
        signal = signal[:n_samples]
        transient = transient[:n_samples]
        if len(signal) < n_samples:
            signal = np.pad(signal, (0, n_samples - len(signal)))
        if len(transient) < n_samples:
            transient = np.pad(transient, (0, n_samples - len(transient)))

        signal = signal + transient * 0.12

        # --- Shimmer layer ---
        shimmer = self._shimmer_layer(freq, duration, shimmer_amount)
        shimmer = shimmer[:n_samples]
        if len(shimmer) < n_samples:
            shimmer = np.pad(shimmer, (0, n_samples - len(shimmer)))

        signal = signal + shimmer * 0.15

        # --- Brightness filter ---
        # Roll off highs based on brightness parameter
        cutoff = brightness_cutoff * (0.3 + brightness * 0.7)
        signal = lowpass(signal, cutoff, self.sr, order=2)

        # --- Effects chain ---
        # EQ (bells typically need high-end sparkle)
        signal = eq_3band(signal, self.sr,
                          low_gain_db=eq_low,
                          mid_gain_db=eq_mid,
                          high_gain_db=eq_high)

        # Delay (bells sound great with rhythmic echoes)
        if delay_mix > 0:
            signal = delay_effect(signal, self.sr,
                                  time_ms=delay_ms,
                                  feedback=0.3,
                                  mix=delay_mix)

        # Reverb (bells live in reverberant spaces)
        if reverb_wet > 0:
            # Map reverb_size to room size — bells need more reverb
            room = 0.3 + reverb_size * 0.6
            signal = reverb(signal, self.sr, room_size=room,
                            damping=0.35, wet=reverb_wet)

        return normalize(signal, 0.9)

    def render_chord(
        self,
        notes: list[int],
        duration: float,
        params: dict | None = None,
    ) -> np.ndarray:
        """Render a bell chord (multiple notes).

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

    def render_arpeggio(
        self,
        notes: list[int],
        note_duration: float,
        spacing: float,
        params: dict | None = None,
    ) -> np.ndarray:
        """Render an arpeggiated bell sequence.

        Bell arpeggios are a signature sound in many Zaytoven productions.
        Each note rings over into the next, creating a shimmering cascade.

        Parameters
        ----------
        notes : list[int]
            MIDI note numbers to arpeggiate.
        note_duration : float
            Duration of each individual note in seconds.
        spacing : float
            Time between note onsets in seconds.
        params : dict, optional
            Same as render().

        Returns
        -------
        np.ndarray
            Mono audio signal.
        """
        total_duration = spacing * (len(notes) - 1) + note_duration
        n_samples = int(self.sr * total_duration)
        output = np.zeros(n_samples)

        for i, note in enumerate(notes):
            rendered = self.render(note, note_duration, params)
            start_sample = int(i * spacing * self.sr)
            end_sample = min(start_sample + len(rendered), n_samples)
            copy_len = end_sample - start_sample
            output[start_sample:end_sample] += rendered[:copy_len]

        return normalize(output, 0.9)
