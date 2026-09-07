# midi-to-mikrotik

Converts MIDI files into RouterOS scripts (`.rsc`) that play the melody
on the **beeper** of MikroTik RouterBOARD devices, using the native
`:beep` and `:delay` commands.

Written in pure Python + [`mido`](https://github.com/mido/mido) — no
compiled dependencies or external audio libraries required.

```
:beep frequency=659 length=235ms;
:delay 250ms;
:beep frequency=622 length=235ms;
:delay 250ms;
```

## Why

There's already [midi_to_mikrotik_converter](https://github.com/altucor/midi_to_mikrotik_converter)
by altucor (C++), and the [MikroTik forum](https://forum.mikrotik.com/t/some-music/95593)
has several hand-written scripts. This project does the same thing in
pure Python, computing frequencies directly (standard A440 tuning)
instead of rebuilding note tables inside the RouterOS script itself —
so the final `.rsc` file ends up shorter and easier to read.

## Installation

```bash
git clone https://github.com/<your-username>/midi-to-mikrotik.git
cd midi-to-mikrotik
pip install -r requirements.txt
```

## Usage

```bash
python3 midi_to_mikrotik.py song.mid -o song.rsc
```

On the router:

```
/import file=song.rsc
```

(or paste the contents directly into the terminal, or inside a
`/system script`).

### Inspecting tracks before converting

The beeper is **monophonic**: it can only play one note at a time. Most
MIDI files have several tracks (melody, bass, drums...), so it's worth
picking only the one you want:

```bash
python3 midi_to_mikrotik.py song.mid --list-tracks
```

```
File: song.mid  |  ticks_per_beat=480  |  duration=124.3s
  Track 0: 'Piano melody'  -  212 notes
  Track 1: 'Bass'          -  98 notes
  Track 2: 'Drums'         -  340 notes
```

```bash
python3 midi_to_mikrotik.py song.mid --tracks 0 -o song.rsc
```

### Options

| Option               | Description                                                                                      |
|----------------------|----------------------------------------------------------------------------------------------------|
| `-o, --output`       | Output `.rsc` file                                                                                  |
| `--tracks 0,2`       | Include only these MIDI tracks                                                                      |
| `--channels 0,1`     | Include only these MIDI channels (useful for excluding drums, usually on channel 9)                 |
| `-t, --transpose N`  | Transpose by N semitones (e.g. `-12` to drop an octave)                                             |
| `--fine-tune HZ`     | Fine frequency correction in Hz, in case your beeper sounds slightly out of tune                    |
| `--speed X`          | `0.5` = twice as fast · `2.0` = half speed                                                          |
| `--staccato MS`      | Milliseconds of silence between consecutive notes, for articulation (default `15`)                  |
| `--voice`            | How to resolve chords/polyphony: `highest` (default), `lowest`, `loudest`, `last`                   |
| `--comments`         | Add comments with the note name (`C4`, `A#3`...) and frequency in the `.rsc`                        |
| `--list-tracks`      | Just list the MIDI's tracks and exit                                                                |

## Example

[`examples/`](examples/) contains a test MIDI and its generated `.rsc`:

```bash
python3 midi_to_mikrotik.py examples/fur_elise_test.mid -o out.rsc --comments
```

## How it works

1. **Reading the MIDI file** — using `mido`, converts each track's ticks
   to seconds using the file's actual tempo map.
2. **Reducing to monophonic** — when there are simultaneous notes
   (chords, overlapping tracks), a single note is chosen per instant
   based on `--voice` (default: the highest one — usually the melody).
3. **Frequency calculation** — `freq = 440 * 2^((note-69)/12)` (standard
   A440 tuning), rounded to an integer Hz value.
4. **Script generation** — each note becomes a `:beep` + `:delay` pair;
   silences in the MIDI become a `:delay` alone.

## Notes / limitations

- Not every RouterBOARD has a physical beeper (e.g. the RB4011 doesn't
  have one).
- The beeper only plays one note at a time — there's no real polyphony
  in the hardware, so chords get simplified to a single voice.
- Tested on an RB951 (MikroTourette).

## Credits / inspiration

- [altucor/midi_to_mikrotik_converter](https://github.com/altucor/midi_to_mikrotik_converter)
- MikroTik forum thread ["Some Music"](https://forum.mikrotik.com/t/some-music/95593)
  (MikroTourette, MxW, and others)

## License

MIT — see [LICENSE](LICENSE).
