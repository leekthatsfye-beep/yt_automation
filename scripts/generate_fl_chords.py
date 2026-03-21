#!/usr/bin/env python3
"""Generate MIDI chord pack files for FL Studio Piano Roll."""

from midiutil import MIDIFile
import os

OUTPUT_DIR = os.path.expanduser(
    "~/Documents/Image-Line/FL Studio/Presets/Scores"
)


def create_midi(filename, progressions, bars_per_prog=4, bpm=140):
    """
    Create a MIDI file with chord progressions.

    progressions: list of lists of chords
        Each chord is a list of MIDI note numbers.
        Each progression is 4 chords (1 bar each in 4/4).
    """
    total_bars = sum(bars_per_prog for _ in progressions)
    midi = MIDIFile(1)  # 1 track
    track = 0
    channel = 0
    midi.addTempo(track, 0, bpm)
    midi.addTrackName(track, 0, filename.replace('.mid', ''))

    bar_offset = 0
    for prog in progressions:
        beats_per_chord = bars_per_prog // len(prog) * 4  # beats (quarter notes)
        for ci, chord in enumerate(prog):
            start_beat = bar_offset + ci * beats_per_chord
            for note in chord:
                midi.addNote(
                    track, channel, note,
                    time=start_beat,
                    duration=beats_per_chord,
                    volume=90
                )
        bar_offset += bars_per_prog * 4  # advance by total beats in this progression

    path = os.path.join(OUTPUT_DIR, filename)
    with open(path, 'wb') as f:
        midi.writeFile(f)
    print(f"  Created: {path}")


def main():
    os.makedirs(OUTPUT_DIR, exist_ok=True)

    # ── FY3 trap chords.mid ──
    # Key of Am (A3 = 57), common trap progressions
    # Each chord: root + intervals as MIDI notes
    print("Creating FY3 trap chords.mid...")
    create_midi("FY3 trap chords.mid", [
        # i - VI - III - VII  (Am - F - C - G)
        [
            [57, 60, 64],      # Am (A3, C4, E4)
            [53, 57, 60],      # F  (F3, A3, C4)
            [48, 52, 55],      # C  (C3, E3, G3)
            [55, 59, 62],      # G  (G3, B3, D4)
        ],
        # i - iv - VI - V  (Am - Dm - F - E)
        [
            [57, 60, 64],      # Am
            [50, 53, 57],      # Dm (D3, F3, A3)
            [53, 57, 60],      # F
            [52, 56, 59],      # E  (E3, G#3, B3)
        ],
        # i - III - VII - iv  (Am - C - G - Dm)
        [
            [57, 60, 64],      # Am
            [48, 52, 55],      # C
            [55, 59, 62],      # G
            [50, 53, 57],      # Dm
        ],
        # i - VI - iv - V  (Am - F - Dm - E)
        [
            [57, 60, 64],      # Am
            [53, 57, 60],      # F
            [50, 53, 57],      # Dm
            [52, 56, 59],      # E
        ],
    ])

    # ── FY3 dark chords.mid ──
    print("Creating FY3 dark chords.mid...")
    create_midi("FY3 dark chords.mid", [
        # i - bII - V - i  (Am - Bb - E - Am) — Phrygian dark
        [
            [57, 60, 64],      # Am
            [46, 50, 53],      # Bb (Bb2, D3, F3)
            [52, 56, 59],      # E
            [45, 48, 52],      # Am (A2, C3, E3) low voicing
        ],
        # i - iv - bVI - V  (Am - Dm - F - E) — evil minor
        [
            [57, 60, 64],      # Am
            [50, 53, 57],      # Dm
            [41, 45, 48],      # F  (F2, A2, C3) low voicing
            [52, 56, 59],      # E
        ],
        # i - v - bVI - bVII  (Am - Em - F - G) — cinematic dark
        [
            [57, 60, 64],      # Am
            [52, 55, 59],      # Em (E3, G3, B3)
            [53, 57, 60],      # F
            [55, 59, 62],      # G
        ],
    ])

    # ── FY3 melodic chords.mid ──
    print("Creating FY3 melodic chords.mid...")
    create_midi("FY3 melodic chords.mid", [
        # I - V - vi - IV  (C - G - Am - F) — pop/emotional
        [
            [48, 52, 55],      # C  (C3, E3, G3)
            [55, 59, 62],      # G  (G3, B3, D4)
            [57, 60, 64],      # Am (A3, C4, E4)
            [53, 57, 60],      # F  (F3, A3, C4)
        ],
        # vi - IV - I - V  (Am - F - C - G) — sad beautiful
        [
            [57, 60, 64],      # Am
            [53, 57, 60],      # F
            [48, 52, 55],      # C
            [55, 59, 62],      # G
        ],
        # i - III - iv - VI  (Am - C - Dm - F) — Lil Durk / Rod Wave feel
        [
            [57, 60, 64],      # Am
            [48, 52, 55],      # C
            [50, 53, 57],      # Dm
            [53, 57, 60],      # F
        ],
    ])

    print("\nDone! All chord packs installed to FL Studio Scores folder.")
    print("In FL Studio: Browser → Packs/Presets → Scores → look for 'FY3' files")


if __name__ == "__main__":
    main()
