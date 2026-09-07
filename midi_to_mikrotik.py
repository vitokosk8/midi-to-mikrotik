#!/usr/bin/env python3
"""
midi_to_mikrotik.py
====================
Convierte un archivo MIDI en un script RouterOS (.rsc) que reproduce
la melodía usando el comando nativo ":beep" del beeper de las RouterBOARD.

Solo usa la librería estándar + `mido` (pip install mido).

Ejemplo de salida generado (formato compatible con RouterOS):

    :beep frequency=698 length=167ms;
    :delay 177ms;

Uso básico:
    python3 midi_to_mikrotik.py melodia.mid -o melodia.rsc

Ver todas las opciones con:
    python3 midi_to_mikrotik.py -h
"""

import argparse
import sys
from dataclasses import dataclass

try:
    import mido
except ImportError:
    sys.exit(
        "Falta la librería 'mido'. Instálala con:\n"
        "    pip install mido --break-system-packages\n"
    )


# --------------------------------------------------------------------------
# Utilidades de conversión nota MIDI -> frecuencia
# --------------------------------------------------------------------------

def midi_note_to_freq(note: int, transpose: int = 0, fine_tune_hz: float = 0.0) -> int:
    """Convierte un número de nota MIDI (0-127) a frecuencia en Hz.

    Usa afinación estándar A440 (nota 69 = A4 = 440Hz).
    RouterOS acepta 'frequency' como entero (Hz), así que redondeamos.
    """
    note = note + transpose
    freq = 440.0 * (2.0 ** ((note - 69) / 12.0))
    freq += fine_tune_hz
    return max(1, round(freq))


# --------------------------------------------------------------------------
# Estructuras internas
# --------------------------------------------------------------------------

@dataclass
class NoteEvent:
    start: float   # segundos, absolutos
    end: float     # segundos, absolutos
    note: int      # número de nota MIDI
    velocity: int
    channel: int
    track_idx: int


@dataclass
class BeepSegment:
    """Un tramo de tiempo: o bien suena una nota (note != None) o es silencio."""
    start: float
    end: float
    note: int | None


# --------------------------------------------------------------------------
# Paso 1: leer el MIDI y construir eventos de nota con tiempos absolutos (s)
# --------------------------------------------------------------------------

def load_note_events(path: str, tracks_filter=None, channels_filter=None) -> list[NoteEvent]:
    mid = mido.MidiFile(path)
    events: list[NoteEvent] = []

    for track_idx, track in enumerate(mid.tracks):
        if tracks_filter is not None and track_idx not in tracks_filter:
            continue

        abs_time = 0.0
        tempo = 500000  # microsegundos por negra (120 BPM), valor por defecto MIDI
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
# Paso 2: el beeper es monofónico (una sola nota a la vez).
# Reducimos la polifonía: en cada instante suena la nota más aguda activa
# (normalmente la melodía principal). Esto es lo mismo que hace
# midi_to_mikrotik_converter (una sola "voz" a la vez).
# --------------------------------------------------------------------------

def reduce_to_monophonic(events: list[NoteEvent], voice: str = "highest") -> list[BeepSegment]:
    if not events:
        return []

    # Construimos una línea de tiempo de cambios (note on / note off)
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
        else:  # "first" -> nota que empezó más recientemente (útil para líneas melódicas)
            note = max(active, key=lambda e: e.start).note

        segments.append(BeepSegment(t0, t1, note))

    # Fusionar segmentos consecutivos con la misma nota (o mismo silencio)
    merged: list[BeepSegment] = []
    for seg in segments:
        if merged and merged[-1].note == seg.note and abs(merged[-1].end - seg.start) < 1e-6:
            merged[-1] = BeepSegment(merged[-1].start, seg.end, seg.note)
        else:
            merged.append(seg)

    return merged


# --------------------------------------------------------------------------
# Paso 3: generar el script RouterOS
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
    """speed: multiplicador de duración (1.0 = original, 0.5 = doble de rápido, 2.0 = mitad)."""
    lines = []
    if title:
        lines.append(f"# {title}")
    lines.append("# Generado con midi_to_mikrotik.py")
    lines.append("#")

    for seg in segments:
        dur_ms = round((seg.end - seg.start) * 1000 * speed)
        if dur_ms <= 0:
            continue

        if seg.note is None:
            # Silencio: solo delay
            lines.append(f":delay {dur_ms}ms;")
            continue

        freq = midi_note_to_freq(seg.note, transpose, fine_tune_hz)
        beep_len = max(1, dur_ms - staccato_ms)

        if beep_len < min_len_ms:
            # Nota demasiado corta tras el staccato: se toca sin separación
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
        description="Convierte un archivo MIDI en un script RouterOS (.rsc) "
                    "para el beeper de las RouterBOARD MikroTik."
    )
    parser.add_argument("input", help="Archivo MIDI de entrada (.mid)")
    parser.add_argument("-o", "--output", default=None,
                         help="Archivo .rsc de salida (por defecto: mismo nombre que el input)")
    parser.add_argument("-t", "--transpose", type=int, default=0,
                         help="Semitonos a transponer (ej: -12 baja una octava)")
    parser.add_argument("--fine-tune", type=float, default=0.0,
                         help="Ajuste fino de frecuencia en Hz (ej: -5.3)")
    parser.add_argument("--speed", type=float, default=1.0,
                         help="Multiplicador de duración: 0.5=doble de rápido, 2.0=mitad de velocidad (default 1.0)")
    parser.add_argument("--staccato", type=int, default=15,
                         help="Milisegundos de silencio entre notas consecutivas, para articulación (default 15)")
    parser.add_argument("--voice", choices=["highest", "lowest", "loudest", "last"], default="highest",
                         help="Cómo elegir qué nota suena cuando hay varias simultáneas (default: highest = melodía aguda)")
    parser.add_argument("--tracks", type=str, default=None,
                         help="Lista de índices de pistas a incluir, ej: '0,2' (por defecto: todas)")
    parser.add_argument("--channels", type=str, default=None,
                         help="Lista de canales MIDI a incluir 0-15, ej: '0,1' (por defecto: todos, excluye percusión canal 9 automáticamente si se especifica)")
    parser.add_argument("--comments", action="store_true",
                         help="Añadir comentarios con el nombre de la nota y frecuencia")
    parser.add_argument("--list-tracks", action="store_true",
                         help="Solo lista las pistas del MIDI (nombre, nº de eventos) y termina, sin generar nada")
    args = parser.parse_args()

    if args.list_tracks:
        mid = mido.MidiFile(args.input)
        print(f"Archivo: {args.input}  |  ticks_per_beat={mid.ticks_per_beat}  |  duración={mid.length:.1f}s")
        for i, track in enumerate(mid.tracks):
            n_notes = sum(1 for m in track if m.type == "note_on" and m.velocity > 0)
            name = track.name or "(sin nombre)"
            print(f"  Pista {i}: '{name}'  -  {n_notes} notas")
        return

    tracks_filter = parse_int_list(args.tracks) if args.tracks else None
    channels_filter = parse_int_list(args.channels) if args.channels else None

    events = load_note_events(args.input, tracks_filter, channels_filter)
    if not events:
        sys.exit("No se encontraron notas en el archivo (revisa --tracks / --channels).")

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
    print(f"OK: {n_beeps} notas escritas en '{out_path}'")


if __name__ == "__main__":
    main()
