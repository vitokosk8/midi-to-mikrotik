# midi-to-mikrotik

Convierte archivos MIDI en scripts RouterOS (`.rsc`) que reproducen la
melodía en el **beeper** de las RouterBOARD MikroTik, usando los comandos
nativos `:beep` y `:delay`.

Escrito en Python puro + [`mido`](https://github.com/mido/mido) — sin
dependencias de compilación ni librerías externas de audio.

```
:beep frequency=659 length=235ms;
:delay 250ms;
:beep frequency=622 length=235ms;
:delay 250ms;
```

## Por qué

Ya existe [midi_to_mikrotik_converter](https://github.com/altucor/midi_to_mikrotik_converter)
de altucor (C++), y en el [foro de MikroTik](https://forum.mikrotik.com/t/some-music/95593)
hay varios scripts hechos a mano. Este proyecto hace lo mismo pero en Python
puro, calculando las frecuencias directamente (afinación estándar A440) en
vez de reconstruir tablas de notas dentro del propio script RouterOS —
así el `.rsc` final queda más corto y fácil de leer.

## Instalación

```bash
git clone https://github.com/<tu-usuario>/midi-to-mikrotik.git
cd midi-to-mikrotik
pip install -r requirements.txt
```

## Uso

```bash
python3 midi_to_mikrotik.py melodia.mid -o melodia.rsc
```

En el router:

```
/import file=melodia.rsc
```

(o pega el contenido directamente en el terminal, o dentro de un
`/system script`).

### Inspeccionar las pistas antes de convertir

El beeper es **monofónico**: solo suena una nota a la vez. La mayoría de
MIDI tienen varias pistas (melodía, bajo, batería...), así que conviene
elegir solo la que interesa:

```bash
python3 midi_to_mikrotik.py melodia.mid --list-tracks
```

```
Archivo: melodia.mid  |  ticks_per_beat=480  |  duración=124.3s
  Pista 0: 'Piano melodía'  -  212 notas
  Pista 1: 'Bajo'           -  98 notas
  Pista 2: 'Batería'        -  340 notas
```

```bash
python3 midi_to_mikrotik.py melodia.mid --tracks 0 -o melodia.rsc
```

### Opciones

| Opción              | Descripción                                                                                    |
|----------------------|-------------------------------------------------------------------------------------------------|
| `-o, --output`       | Archivo `.rsc` de salida                                                                        |
| `--tracks 0,2`       | Incluir solo esas pistas del MIDI                                                               |
| `--channels 0,1`     | Incluir solo esos canales MIDI (útil para excluir batería, normalmente en canal 9)               |
| `-t, --transpose N`  | Transponer N semitonos (ej. `-12` para bajar una octava)                                        |
| `--fine-tune HZ`     | Corrección fina de frecuencia en Hz, por si tu beeper suena algo desafinado                      |
| `--speed X`          | `0.5` = el doble de rápido · `2.0` = la mitad de velocidad                                      |
| `--staccato MS`      | Milisegundos de silencio entre notas consecutivas, para articulación (default `15`)              |
| `--voice`            | Cómo resolver acordes/polifonía: `highest` (default), `lowest`, `loudest`, `last`               |
| `--comments`         | Añade comentarios con nombre de nota (`C4`, `A#3`...) y frecuencia en el `.rsc`                  |
| `--list-tracks`      | Solo lista las pistas del MIDI y termina                                                        |

## Ejemplo

En [`examples/`](examples/) hay un MIDI de prueba y su `.rsc` generado:

```bash
python3 midi_to_mikrotik.py examples/fur_elise_test.mid -o out.rsc --comments
```

## Cómo funciona

1. **Lectura del MIDI** — con `mido`, convierte los ticks de cada pista a
   segundos usando el mapa de tempo real del archivo.
2. **Reducción a monofónico** — cuando hay notas simultáneas (acordes,
   varias pistas solapadas), se elige una sola nota por instante según
   `--voice` (por defecto, la más aguda — normalmente la melodía).
3. **Cálculo de frecuencia** — `freq = 440 * 2^((nota-69)/12)` (afinación
   estándar A440), redondeado a Hz entero.
4. **Generación del script** — cada nota se traduce a un par
   `:beep` + `:delay`; los silencios del MIDI, a `:delay` solo.

## Notas / limitaciones

- No todas las RouterBOARD tienen beeper físico (p. ej. el RB4011 no lo
  tiene).
- El beeper solo reproduce una nota a la vez — no hay polifonía real en
  el hardware, así que acordes se simplifican a una sola voz.
- Probado en RB951 (MikroTourette).

## Créditos / inspiración

- [altucor/midi_to_mikrotik_converter](https://github.com/altucor/midi_to_mikrotik_converter)
- Hilo del foro MikroTik ["Some Music"](https://forum.mikrotik.com/t/some-music/95593)
  (MikroTourette, MxW y otros)

## Licencia

MIT — ver [LICENSE](LICENSE).
