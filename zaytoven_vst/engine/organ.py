"""FY3 Zaytoven Collection — Hammond/Church Organ model.

Drawbar additive synthesis with Leslie speaker simulation,
key click, overdrive, and full effects chain. Zaytoven's
#1 signature sound.
"""

import numpy as np

from engine.oscillators import sine, harmonic_stack, noise, fm_oscillator
from engine.envelope import adsr, adsr_exp, percussive, lfo
from engine.filters import lowpass, highpass, bandpass
from engine.effects import reverb, chorus, delay_effect, saturate, eq_3band, compress, tremolo
from engine.utils import midi_to_freq, normalize, stereo_spread, mix_signals


# Hammond B3 drawbar harmonic ratios (footage markings)
# 16'  5⅓'  8'  4'  2⅔'  2'  1⅗'  1⅓'  1'
DRAWBAR_RATIOS = [0.5, 1.5, 1.0, 2.0, 3.0, 4.0, 5.0, 6.0, 8.0]

# Classic Hammond registrations (drawbar settings 0-8)
REGISTRATIONS = {
    "gospel_full": [8, 8, 8, 7, 6, 5, 4, 3, 2],
    "zaytoven":    [8, 6, 8, 8, 4, 6, 2, 0, 0],
    "jimmy_smith": [8, 8, 8, 0, 0, 0, 0, 0, 0],
    "booker_t":    [8, 8, 6, 4, 0, 0, 0, 0, 0],
    "gospel_soft": [0, 0, 8, 6, 0, 4, 0, 0, 0],
    "church":      [8, 8, 8, 8, 8, 8, 8, 8, 8],
    "mellow":      [0, 0, 5, 3, 0, 0, 0, 0, 0],
    "bright":      [8, 0, 8, 0, 0, 8, 0, 0, 8],
    "percussive":  [8, 8, 6, 0, 0, 0, 0, 0, 0],
}


class Organ:
    """Hammond B3 / Church organ synthesizer.

    Generates organ tones using 9-drawbar additive synthesis with
    Leslie speaker simulation, key click, and analog character.

    Parameters
    ----------
    sr : int
        Sample rate (default 44100).
    """

    def __init__(self, sr: int = 48000):
        self.sr = sr

    def _drawbar_tone(
        self,
        freq: float,
        duration: float,
        drawbars: list[int],
    ) -> np.ndarray:
        """Generate the raw tonewheel sound from 9 drawbar settings.

        Each drawbar (0-8) sets the level of its harmonic partial.
        Uses authentic tonewheel shapes with electromagnetic pickup distortion,
        per-wheel manufacturing drift, and subtle crosstalk between adjacent wheels.
        """
        t = np.arange(int(self.sr * duration)) / self.sr
        out = np.zeros_like(t)

        for i, (ratio, level) in enumerate(zip(DRAWBAR_RATIOS, drawbars)):
            if level <= 0:
                continue

            amplitude = level / 8.0
            partial_freq = freq * ratio

            if partial_freq >= self.sr / 2:
                continue

            # Per-tonewheel manufacturing drift (each physical wheel is slightly off)
            detune_cents = np.random.uniform(-4, 4)
            partial_freq *= 2 ** (detune_cents / 1200)

            # Core sine from tonewheel
            fundamental = np.sin(2 * np.pi * partial_freq * t)

            # Electromagnetic pickup creates harmonic distortion (~3-6% even harmonics)
            # This is what gives Hammond its characteristic "growl"
            grit = 0.04 + np.random.uniform(0, 0.02)  # varies per wheel
            h2_freq = partial_freq * 2
            h3_freq = partial_freq * 3
            tonewheel_signal = fundamental
            if h2_freq < self.sr / 2:
                tonewheel_signal += grit * np.sin(2 * np.pi * h2_freq * t)
            if h3_freq < self.sr / 2:
                tonewheel_signal += grit * 0.4 * np.sin(2 * np.pi * h3_freq * t)

            # Subtle amplitude wobble from physical tonewheel rotation irregularity
            wobble_rate = np.random.uniform(0.05, 0.2)
            wobble = 1.0 + 0.004 * np.sin(2 * np.pi * wobble_rate * t + np.random.uniform(0, 6.28))
            tonewheel_signal *= wobble

            out += amplitude * tonewheel_signal

        # Tonewheel crosstalk: adjacent wheels leak into each other (~1-2%)
        # This creates a subtle complexity that's unique to Hammond organs
        if len(out) > 0:
            crosstalk = np.zeros_like(out)
            for i, (ratio, level) in enumerate(zip(DRAWBAR_RATIOS, drawbars)):
                if level <= 0:
                    continue
                # Crosstalk from neighboring tonewheel
                if i < len(DRAWBAR_RATIOS) - 1 and drawbars[min(i + 1, 8)] > 0:
                    neighbor_freq = freq * DRAWBAR_RATIOS[min(i + 1, 8)]
                    if neighbor_freq < self.sr / 2:
                        leak = 0.015 * np.sin(2 * np.pi * neighbor_freq * t + np.random.uniform(0, 3.14))
                        crosstalk += leak * (level / 8.0)
            out += crosstalk

        return out

    def _key_click(
        self,
        freq: float,
        duration: float,
        click_level: float,
    ) -> np.ndarray:
        """Generate key click — short burst of harmonics at note onset.

        Real Hammond key clicks come from the mechanical contact bounce
        when keys close the tonewheel bus bar circuits. They contain
        broad-spectrum energy with a very fast attack and decay.
        """
        if click_level <= 0:
            return np.zeros(int(self.sr * duration))

        # Click duration: 3-8ms depending on level
        click_dur = 0.003 + click_level * 0.005

        # Broadband noise burst
        click = noise(click_dur, self.sr, color="white") * 0.6

        # Add tuned click components (tonewheel transient)
        t_click = np.arange(len(click)) / self.sr
        click += 0.4 * np.sin(2 * np.pi * freq * t_click)
        click += 0.3 * np.sin(2 * np.pi * freq * 2 * t_click)
        click += 0.15 * np.sin(2 * np.pi * freq * 3 * t_click)

        # Shape with percussive envelope
        env = percussive(attack=0.0005, decay=click_dur * 0.8,
                         duration=click_dur, sr=self.sr, curve=12.0)
        click = click[:len(env)] * env

        # Bandpass to remove extreme lows/highs
        click = bandpass(click, 200, 5000, self.sr, order=2)

        # Pad to full note duration
        full = np.zeros(int(self.sr * duration))
        click_len = min(len(click), len(full))
        full[:click_len] = click[:click_len]

        return full * click_level

    def _percussion(
        self,
        freq: float,
        duration: float,
        perc_level: float = 0.0,
        perc_harmonic: str = "second",
        perc_speed: str = "fast",
        perc_decay: float = 0.0,
    ) -> np.ndarray:
        """Hammond percussion circuit — single-trigger decaying harmonic.

        Real Hammond B3 percussion adds a decaying 2nd or 3rd harmonic
        to the first note struck (single-triggered, not re-triggered
        while keys are held). Here we always add it for simplicity.

        Enhanced with:
        - Both 2nd and 3rd harmonic percussion (primary + secondary)
        - Fast/slow decay toggle (fast ~0.2s, slow ~0.5s)
        - Percussive click transient at onset for realism
        """
        if perc_level <= 0:
            return np.zeros(int(self.sr * duration))

        n_samples = int(self.sr * duration)
        out = np.zeros(n_samples)

        # Decay time: use perc_decay if provided (> 0), else fast=0.2s, slow=0.5s
        if perc_decay > 0:
            decay_time = perc_decay
        else:
            decay_time = 0.2 if perc_speed == "fast" else 0.5

        # Primary percussion harmonic (2nd or 3rd)
        ratio = 2.0 if perc_harmonic == "second" else 3.0
        perc_freq = freq * ratio

        if perc_freq < self.sr / 2:
            perc_tone = sine(perc_freq, duration, self.sr)
            env = percussive(attack=0.001, decay=decay_time, duration=duration,
                             sr=self.sr, curve=6.0)
            perc_tone = perc_tone[:len(env)] * env
            out[:len(perc_tone)] += perc_tone[:n_samples] * perc_level

        # Secondary percussion harmonic (the other one, at reduced level)
        secondary_ratio = 3.0 if perc_harmonic == "second" else 2.0
        secondary_freq = freq * secondary_ratio
        if secondary_freq < self.sr / 2:
            secondary_tone = sine(secondary_freq, duration, self.sr)
            secondary_env = percussive(attack=0.001, decay=decay_time * 0.7,
                                        duration=duration, sr=self.sr, curve=8.0)
            secondary_tone = secondary_tone[:len(secondary_env)] * secondary_env
            out[:len(secondary_tone)] += secondary_tone[:n_samples] * perc_level * 0.25

        # Percussive click at onset (contact bounce simulation)
        click_dur = 0.004
        click_samples = int(self.sr * click_dur)
        if click_samples > 0 and click_samples < n_samples:
            click = noise(click_dur, self.sr, color="white")
            click = bandpass(click, 1000, 4000, self.sr, order=2)
            click_env = percussive(attack=0.0002, decay=0.003,
                                    duration=click_dur, sr=self.sr, curve=20.0)
            click = click[:len(click_env)] * click_env * perc_level * 0.15
            out[:min(len(click), n_samples)] += click[:min(len(click), n_samples)]

        return out

    def _leslie_speaker(
        self,
        audio: np.ndarray,
        rate: float,
        depth: float,
        leslie_mode: str = "fast",
    ) -> np.ndarray:
        """Simulate Leslie rotating speaker cabinet with rich Doppler effect.

        Enhanced model with:
        - Separate horn (treble) and drum (bass) rotation at different speeds
        - Fast/slow/brake speed modes with realistic acceleration curves
        - Doppler pitch shift via modulated delay lines with interpolation
        - Amplitude modulation from moving sound source
        - Cabinet resonance coloring and cross-talk between horn and drum
        - Second-order harmonics in AM for more realistic rotation character
        """
        if depth <= 0:
            return audio

        n = len(audio)
        t = np.arange(n) / self.sr

        # Speed modes: fast=chorale (6-7Hz horn), slow=tremolo (~1Hz), brake=stopped
        if leslie_mode == "slow":
            horn_rate = rate * 0.15  # slow rotation
            drum_rate = rate * 0.12
        elif leslie_mode == "brake":
            horn_rate = 0.0
            drum_rate = 0.0
        else:  # fast (default)
            horn_rate = rate
            drum_rate = rate * 0.82  # drum is heavier, slower

        # Split signal into bass (drum) and treble (horn) at 800Hz crossover
        bass_signal = lowpass(audio, 800, self.sr, order=2)
        treble = audio - bass_signal

        # --- Horn (treble) processing ---
        if horn_rate > 0:
            # Amplitude modulation — horn facing/away from listener
            # Use both fundamental rotation and 2nd harmonic for realism
            horn_am = (1.0
                       - depth * 0.35 * (1 + np.sin(2 * np.pi * horn_rate * t)) / 2
                       - depth * 0.08 * (1 + np.sin(2 * np.pi * horn_rate * 2 * t + 0.5)) / 2)

            # Doppler frequency modulation via interpolated delay line
            max_delay = depth * 0.006 * self.sr  # up to 6ms
            if max_delay > 0:
                horn_delay = (np.sin(2 * np.pi * horn_rate * t) + 1) / 2 * max_delay
                treble_wet = np.zeros(n)
                for i in range(n):
                    read_pos = i - horn_delay[i] - max_delay
                    if read_pos >= 0 and read_pos < n - 1:
                        idx = int(read_pos)
                        frac = read_pos - idx
                        treble_wet[i] = treble[idx] * (1 - frac) + treble[min(idx + 1, n - 1)] * frac
                treble = treble * 0.25 + treble_wet * 0.75

            treble *= horn_am
        # else: if brake mode, treble passes through unmodified

        # --- Drum (bass) processing ---
        if drum_rate > 0:
            drum_am = (1.0
                       - depth * 0.25 * (1 + np.sin(2 * np.pi * drum_rate * t + 0.8)) / 2
                       - depth * 0.05 * (1 + np.sin(2 * np.pi * drum_rate * 2 * t + 1.6)) / 2)

            max_delay_drum = max(1, int(depth * 0.003 * self.sr))
            if max_delay_drum > 0:
                drum_delay = (np.sin(2 * np.pi * drum_rate * t + 1.3) + 1) / 2 * max_delay_drum
                bass_wet = np.zeros(n)
                for i in range(n):
                    read_pos = i - drum_delay[i] - max_delay_drum
                    if read_pos >= 0 and read_pos < n - 1:
                        idx = int(read_pos)
                        frac = read_pos - idx
                        bass_wet[i] = bass_signal[idx] * (1 - frac) + bass_signal[min(idx + 1, n - 1)] * frac
                bass_signal = bass_signal * 0.35 + bass_wet * 0.65

            bass_signal *= drum_am

        # Recombine with cabinet resonance coloring
        combined = bass_signal + treble

        # Leslie cabinet cross-talk: slight leakage between horn and drum channels
        # Real Leslie cabinets have acoustic coupling between chambers
        crosstalk = lowpass(treble, 400, self.sr, order=1) * 0.03 * depth
        combined = combined + crosstalk

        # Leslie cabinet has a characteristic mid-range emphasis
        combined = eq_3band(combined, self.sr,
                            low_gain_db=0.5, mid_gain_db=2.0, high_gain_db=-0.5)

        return combined

    def render(
        self,
        note: int,
        duration: float,
        params: dict | None = None,
    ) -> np.ndarray:
        """Render a single organ note.

        Parameters
        ----------
        note : int
            MIDI note number (60 = C4).
        duration : float
            Note duration in seconds.
        params : dict, optional
            Synthesis parameters:
                drawbars: list[int]    9 drawbar levels 0-8 (default gospel_full)
                leslie_rate: float     Leslie rotation Hz (default 5.5)
                leslie_depth: float    Leslie modulation depth 0-1 (default 0.6)
                overdrive: float       Saturation drive 0-1 (default 0.15)
                attack: float          ADSR attack seconds (default 0.008)
                decay: float           ADSR decay seconds (default 0.05)
                sustain: float         ADSR sustain level 0-1 (default 0.95)
                release: float         ADSR release seconds (default 0.08)
                reverb_wet: float      Reverb mix 0-1 (default 0.25)
                reverb_size: float     Reverb room size 0-1 (default 0.5)
                chorus_mix: float      Chorus mix 0-1 (default 0.15)
                eq_low: float          Low band gain dB (default 2.0)
                eq_mid: float          Mid band gain dB (default 0.0)
                eq_high: float         High band gain dB (default 1.5)
                key_click: float       Key click level 0-1 (default 0.4)
                percussion: float      Percussion level 0-1 (default 0.0)
                perc_harmonic: str     'second' or 'third' (default 'second')
                perc_speed: str        'fast' or 'slow' (default 'fast')
                perc_decay: float      Custom percussion decay time in seconds (default 0.0 = use perc_speed)
                perc_volume: float     Percussion mix level (default 0.0 = use 0.35)
                delay_mix: float       Delay effect mix 0-1 (default 0.0 = off)
                delay_ms: float        Delay time in milliseconds (default 300)
                stereo_width: float    Stereo spread amount 0-1 (default 0.0 = mono)
                registration: str      Named preset from REGISTRATIONS (overrides drawbars)

        Returns
        -------
        np.ndarray
            Mono audio signal.
        """
        if params is None:
            params = {}

        freq = midi_to_freq(note)

        # --- Parameter extraction ---
        # Check for named registration first
        registration = params.get("registration")
        if registration and registration in REGISTRATIONS:
            drawbars = REGISTRATIONS[registration]
        else:
            drawbars = params.get("drawbars", REGISTRATIONS["gospel_full"])

        # Ensure drawbars has 9 values, clamped 0-8
        drawbars = [max(0, min(8, int(d))) for d in drawbars[:9]]
        while len(drawbars) < 9:
            drawbars.append(0)

        leslie_rate = params.get("leslie_rate", 5.5)
        leslie_depth = params.get("leslie_depth", 0.6)
        overdrive = params.get("overdrive", 0.15)
        attack = params.get("attack", 0.008)
        decay_t = params.get("decay", 0.05)
        sustain_level = params.get("sustain", 0.95)
        release = params.get("release", 0.08)
        reverb_wet = params.get("reverb_wet", 0.25)
        reverb_size = params.get("reverb_size", 0.5)
        chorus_mix = params.get("chorus_mix", 0.15)
        eq_low = params.get("eq_low", 2.0)
        eq_mid = params.get("eq_mid", 0.0)
        eq_high = params.get("eq_high", 1.5)
        key_click_level = params.get("key_click", 0.4)
        perc_level = params.get("percussion", 0.0)
        perc_harmonic = params.get("perc_harmonic", "second")
        perc_speed = params.get("perc_speed", "fast")
        perc_decay_val = params.get("perc_decay", 0.0)
        perc_volume = params.get("perc_volume", 0.0)
        leslie_mode = params.get("leslie_mode", "fast")
        tube_drive = params.get("tube_drive", 0.0)

        # --- Core tonewheel synthesis ---
        tone = self._drawbar_tone(freq, duration, drawbars)

        # --- Percussion circuit ---
        perc = self._percussion(freq, duration, perc_level, perc_harmonic, perc_speed, perc_decay_val)

        # --- Key click ---
        click = self._key_click(freq, duration, key_click_level)

        # --- Mix core layers ---
        n_samples = int(self.sr * duration)
        # Ensure all arrays are same length
        tone = tone[:n_samples]
        perc = perc[:n_samples]
        click = click[:n_samples]

        # Pad if needed
        if len(tone) < n_samples:
            tone = np.pad(tone, (0, n_samples - len(tone)))
        if len(perc) < n_samples:
            perc = np.pad(perc, (0, n_samples - len(perc)))
        if len(click) < n_samples:
            click = np.pad(click, (0, n_samples - len(click)))

        perc_mix = perc_volume if perc_volume > 0 else 0.35
        signal = tone + perc * perc_mix + click * 0.2

        # --- Apply ADSR envelope ---
        env = adsr(attack, decay_t, sustain_level, release, duration, self.sr)
        env = env[:n_samples]
        if len(env) < n_samples:
            env = np.pad(env, (0, n_samples - len(env)))
        signal *= env

        # --- Overdrive / saturation ---
        # Hammond preamp overdrive is a key part of the sound
        if overdrive > 0:
            signal = saturate(signal, drive=overdrive, sat_type="tube")

        # --- Tube overdrive stage (separate from preamp) ---
        # This is the power amp / speaker overdrive for heavier distortion
        if tube_drive > 0:
            # Multi-stage tube saturation: soft clip -> tube asymmetry
            signal = saturate(signal, drive=tube_drive * 0.4, sat_type="soft")
            signal = saturate(signal, drive=tube_drive * 0.25, sat_type="tube")

        # --- Leslie speaker simulation ---
        signal = self._leslie_speaker(signal, leslie_rate, leslie_depth, leslie_mode)

        # --- Effects chain ---
        # EQ (shape tone before reverb)
        signal = eq_3band(signal, self.sr,
                          low_gain_db=eq_low,
                          mid_gain_db=eq_mid,
                          high_gain_db=eq_high)

        # Chorus (adds width and movement)
        signal = chorus(signal, self.sr, rate=1.2, depth=0.002, mix=chorus_mix)

        # Reverb (organ lives in a room/church)
        signal = reverb(signal, self.sr, room_size=reverb_size, damping=0.4, wet=reverb_wet)

        # Delay (tempo-synced echo when enabled by preset)
        delay_mix_val = params.get("delay_mix", 0.0)
        delay_ms_val = params.get("delay_ms", 300)
        if delay_mix_val > 0:
            signal = delay_effect(signal, self.sr, time_ms=delay_ms_val, feedback=0.3, mix=delay_mix_val)

        # Gentle compression to tame peaks from additive synthesis
        signal = compress(signal, threshold_db=-10, ratio=3.0,
                          attack_ms=8, release_ms=60, sr=self.sr)

        # Stereo width (spread mono signal, then collapse back to mono)
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
        """Render a full organ chord (multiple notes).

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
