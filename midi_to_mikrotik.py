#!/usr/bin/env python3
"""
midi_to_mikrotik.py
====================
Converts a MIDI file into a RouterOS script (.rsc) that plays the melody
using the native ":beep" command of the MikroTik RouterBOARD beeper.

Only uses the standard library + `mido` (pip install mido).

Example of the generated output (RouterOS-compatible format):

    :beep frequency=698 length=167ms;
    :delay 177ms;

Basic usage:
    python3 midi_to_mikrotik.py song.mid -o song.rsc

See all options with:
    python3 midi_to_mikrotik.py -h
"""

import argparse
import sys
from dataclasses import dataclass

try:
    import mido
except ImportError:
    sys.exit(
        "Missing library 'mido'. Install it with:\n"
        "    pip install mido --break-system-packages\n"
    )


# --------------------------------------------------------------------------
# MIDI note -> frequency conversion utilities
# --------------------------------------------------------------------------

def midi_note_to_freq(note: int, transpose: int = 0, fine_tune_hz: float = 0.0) -> int:
    """Converts a MIDI note number (0-127) to a frequency in Hz.

    Uses standard A440 tuning (note 69 = A4 = 440Hz).
    RouterOS accepts 'frequency' as an integer (Hz), so we round it.
    """
    note = note + transpose
    freq = 440.0 * (2.0 ** ((note - 69) / 12.0))
    freq += fine_tune_hz
    return max(1, round(freq))


# --------------------------------------------------------------------------
# Internal data structures
# --------------------------------------------------------------------------

@dataclass
class NoteEvent:
    start: float   # seconds, absolute
    end: float     # seconds, absolute
    note: int      # MIDI note number
    velocity: int
    channel: int
    track_idx: int


@dataclass
class BeepSegment:
    """A time span: either a note is sounding (note != None) or it's silence."""
    start: float
    end: float
    note: int | None


# --------------------------------------------------------------------------
# Step 1: read the MIDI file and build note events with absolute times (s)
# --------------------------------------------------------------------------

def load_note_events(path: str, tracks_filter=None, channels_filter=None) -> list[NoteEvent]:
    mid = mido.MidiFile(path)
    events: list[NoteEvent] = []

    for track_idx, track in enumerate(mid.tracks):
        if tracks_filter is not None and track_idx not in tracks_filter:
            continue

        abs_time = 0.0
        tempo = 500000  # microseconds per quarter note (120 BPM), MIDI default
        active: dict[tuple, tuple] = {}  # (note, channel) -> (start_time, velocity)

        for msg in track:
            abs_time += mido.tick2second(msg.time, mid.ticks_per_beat, tempo)

            if msg.type == "set_tempo":
                tempo = msg.tempo
                continue

            if msg.type == "note_on" and msg.velocity > 0:
                if channels_filter is not None and msg.channel not in channels_filter:
                    continue
                active[(msg.note, msg.channel)] = (abs_time, msg.velocity)

            elif msg.type == "note_off" or (msg.type == "note_on" and msg.velocity == 0):
                key = (msg.note, msg.channel)
                if key in active:
                    start, vel = active.pop(key)
                    if abs_time > start:
                        events.append(
                            NoteEvent(start, abs_time, msg.note, vel, msg.channel, track_idx)
                        )

    events.sort(key=lambda e: e.start)
    return events


# --------------------------------------------------------------------------
# Step 2: the beeper is monophonic (only one note at a time).
# We reduce polyphony: at each instant, the highest active note sounds
# (usually the main melody). This is the same approach used by
# midi_to_mikrotik_converter (a single "voice" at a time).
# --------------------------------------------------------------------------

def reduce_to_monophonic(events: list[NoteEvent], voice: str = "highest") -> list[BeepSegment]:
    if not events:
        return []

    # Build a timeline of changes (note on / note off)
    time_points = sorted({e.start for e in events} | {e.end for e in events})

    segments: list[BeepSegment] = []
    for i in range(len(time_points) - 1):
        t0, t1 = time_points[i], time_points[i + 1]
        if t1 - t0 <= 0:
            continue
        mid_t = (t0 + t1) / 2
        active = [e for e in events if e.start <= mid_t < e.end]

        if not active:
            note = None
        elif voice == "highest":
            note = max(active, key=lambda e: e.note).note
        elif voice == "lowest":
            note = min(active, key=lambda e: e.note).note
        elif voice == "loudest":
            note = max(active, key=lambda e: e.velocity).note
        else:  # "last" -> most recently started note (useful for melodic lines)
            note = max(active, key=lambda e: e.start).note

        segments.append(BeepSegment(t0, t1, note))

    # Merge consecutive segments with the same note (or the same silence)
    merged: list[BeepSegment] = []
    for seg in segments:
        if merged and merged[-1].note == seg.note and abs(merged[-1].end - seg.start) < 1e-6:
            merged[-1] = BeepSegment(merged[-1].start, seg.end, seg.note)
        else:
            merged.append(seg)

    return merged


# --------------------------------------------------------------------------
# Step 3: generate the RouterOS script
# --------------------------------------------------------------------------

def generate_routeros_script(
    segments: list[BeepSegment],
    transpose: int = 0,
    fine_tune_hz: float = 0.0,
    staccato_ms: int = 15,
    speed: float = 1.0,
    min_len_ms: int = 20,
    add_comments: bool = False,
    title: str = "",
) -> str:
    """speed: duration multiplier (1.0 = original, 0.5 = twice as fast, 2.0 = half speed)."""
    lines = []
    if title:
        lines.append(f"# {title}")
    lines.append("# Generated with midi_to_mikrotik.py")
    lines.append("#")

    for seg in segments:
        dur_ms = round((seg.end - seg.start) * 1000 * speed)
        if dur_ms <= 0:
            continue

        if seg.note is None:
            # Silence: delay only
            lines.append(f":delay {dur_ms}ms;")
            continue

        freq = midi_note_to_freq(seg.note, transpose, fine_tune_hz)
        beep_len = max(1, dur_ms - staccato_ms)

        if beep_len < min_len_ms:
            # Note too short after staccato: play it without a gap
            beep_len = dur_ms

        if add_comments:
            note_name = midi_note_name(seg.note + transpose)
            lines.append(f"# {note_name} ({freq} Hz)")

        lines.append(f":beep frequency={freq} length={beep_len}ms;")
        lines.append(f":delay {dur_ms}ms;")

    return "\n".join(lines) + "\n"


_NOTE_NAMES = ["C", "C#", "D", "D#", "E", "F", "F#", "G", "G#", "A", "A#", "B"]


def midi_note_name(note: int) -> str:
    octave = note // 12 - 1
    name = _NOTE_NAMES[note % 12]
    return f"{name}{octave}"


# --------------------------------------------------------------------------
# CLI
# --------------------------------------------------------------------------

def parse_int_list(s: str) -> set[int]:
    return {int(x) for x in s.split(",") if x.strip() != ""}


def main():
    parser = argparse.ArgumentParser(
        description="Converts a MIDI file into a RouterOS script (.rsc) "
                    "for the MikroTik RouterBOARD beeper."
    )
    parser.add_argument("input", help="Input MIDI file (.mid)")
    parser.add_argument("-o", "--output", default=None,
                         help="Output .rsc file (default: same name as the input)")
    parser.add_argument("-t", "--transpose", type=int, default=0,
                         help="Semitones to transpose (e.g. -12 drops an octave)")
    parser.add_argument("--fine-tune", type=float, default=0.0,
                         help="Fine frequency adjustment in Hz (e.g. -5.3)")
    parser.add_argument("--speed", type=float, default=1.0,
                         help="Duration multiplier: 0.5=twice as fast, 2.0=half speed (default 1.0)")
    parser.add_argument("--staccato", type=int, default=15,
                         help="Milliseconds of silence between consecutive notes, for articulation (default 15)")
    parser.add_argument("--voice", choices=["highest", "lowest", "loudest", "last"], default="highest",
                         help="How to pick which note sounds when several overlap (default: highest = top melody)")
    parser.add_argument("--tracks", type=str, default=None,
                         help="List of track indices to include, e.g. '0,2' (default: all)")
    parser.add_argument("--channels", type=str, default=None,
                         help="List of MIDI channels to include 0-15, e.g. '0,1' (default: all; excludes the "
                              "percussion channel 9 only if you specify it explicitly)")
    parser.add_argument("--comments", action="store_true",
                         help="Add comments with the note name and frequency")
    parser.add_argument("--list-tracks", action="store_true",
                         help="Just list the MIDI's tracks (name, number of events) and exit, without generating anything")
    args = parser.parse_args()

    if args.list_tracks:
        mid = mido.MidiFile(args.input)
        print(f"File: {args.input}  |  ticks_per_beat={mid.ticks_per_beat}  |  duration={mid.length:.1f}s")
        for i, track in enumerate(mid.tracks):
            n_notes = sum(1 for m in track if m.type == "note_on" and m.velocity > 0)
            name = track.name or "(unnamed)"
            print(f"  Track {i}: '{name}'  -  {n_notes} notes")
        return

    tracks_filter = parse_int_list(args.tracks) if args.tracks else None
    channels_filter = parse_int_list(args.channels) if args.channels else None

    events = load_note_events(args.input, tracks_filter, channels_filter)
    if not events:
        sys.exit("No notes found in the file (check --tracks / --channels).")

    segments = reduce_to_monophonic(events, voice=args.voice)

    script = generate_routeros_script(
        segments,
        transpose=args.transpose,
        fine_tune_hz=args.fine_tune,
        staccato_ms=args.staccato,
        speed=args.speed,
        add_comments=args.comments,
        title=args.input,
    )

    out_path = args.output or (args.input.rsplit(".", 1)[0] + ".rsc")
    with open(out_path, "w", encoding="utf-8") as f:
        f.write(script)

    n_beeps = script.count(":beep")
    print(f"OK: {n_beeps} notes written to '{out_path}'")


if __name__ == "__main__":
    main()
