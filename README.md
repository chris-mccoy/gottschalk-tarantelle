# Gottschalk: Grande Tarantelle, Op. 67 (Espadero's solo-piano arrangement)

https://github.com/user-attachments/assets/8343a67a-f7a6-4181-a260-b849b4440ee4

An expressive MIDI performance, decoded from the braille transcription of the score. The piece is Nicolás Ruiz
Espadero's transcription for piano alone, Boston: Oliver Ditson, 1874.

| File | What it is |
|---|---|
| `espadero.brf` | The score in North American ASCII music braille, bar-over-bar: Hu Haipeng's transcription for the Braille Orchestra and Open Braille Music projects ([IMSLP #933069](https://imslp.org/wiki/Grande_Tarantelle%2C_Op.67_%28Gottschalk%2C_Louis_Moreau%29), CC BY-SA 4.0) |
| `brf.py` | Reads the braille into timed notes (the subset of the BANA Music Braille Code the file uses); prints the decoded notes bar by bar |
| `perform.py` | Turns the notes into the performance: tempo, rubato, dynamics, voicing, articulation, pedal |
| `render.swift` | Plays a MIDI file through the macOS sampler, offline, into an `.m4a` |
| `gottschalk-tarantelle-espadero.mid` | The performance |
| `gottschalk-tarantelle-espadero.m4a` | The performance as audio |
| `LICENSE-MIT` | The MIT license, for the code |
| `LICENSE-CC-BY-SA-4.0` | Creative Commons Attribution-ShareAlike 4.0 International, for the braille, the performances and the rest |

The Python needs only the standard library (3.11 or later); `render.swift` needs macOS and
Swift (the Xcode command-line tools).

```
python3 perform.py espadero.brf -o gottschalk-tarantelle-espadero.mid
swift render.swift gottschalk-tarantelle-espadero.mid gottschalk-tarantelle-espadero.m4a
python3 brf.py espadero.brf 1 12      # the decoded notes of bars 1-12
```

`perform.py --report` prints the tempo, loudness and markings of every bar; `--tempo` sets the
dotted-quarter tempo (158), `--no-repeats` skips the two repeats.

## Listening

For a better piano, open the `.mid` in GarageBand: **File › Open**, or drag it into an empty
project. When GarageBand asks *Also import tempo information?*, click **Import Tempo**: the
rubato lives in the tempo map, and without it the piece plays metronomically. If the track
does not come up as a piano, pick **Piano › Steinway Grand Piano** in the Library. Bars and
key changes line up with the score, so it reads correctly in a DAW or notation program too.

`render.swift` cannot use GarageBand's Steinway itself: it is an EXS24 instrument over one
consolidated `.caf`, which `AVAudioUnitSampler` will not load (error -10868).

## The notes

The braille gives every pitch and duration exactly, so no optical reading of the 1874 scan was
needed. The decoder handles the code as this file uses it: octave marks and BANA's rules for
unmarked octaves, intervals read down in the right hand and up in the left, interval doubling
(`--`), full- and part-measure in-accord, measure and part-measure repeats (whose extent comes
from the bar's length), 16th-note grouping, triplets and quintuplets, stem signs, grace and
cue-size notes, cautionary accidentals (in parentheses in print, `,'` … `,'` in the braille),
ties, slurs, fingered tremolos, hand changes within a line, first and second
endings, and key changes. Every voice of all 539 bars (and the two second endings) adds up to
exactly 6/8.

Bars were compared with the Ditson print (IMSLP #07731) in every section. Six places in the
braille differ from the print and are corrected in `brf.py` (`CORRECTIONS`):

| Bars | Braille | Print |
|---|---|---|
| 2, 3, 5, 440, 444, 446 | Left-hand A major chord as A2 C♯3 E3 | A2 E3 C♯4 (the tenth needs an octave mark the braille lacks) |
| 489 | A stray `5k` after the third note | Nothing; without it the bar is exactly 6/8 |

The braille leaves out the print's *ossia* and *Facilité* staves, so they are not played. The
cue-size notes the score marks *avec les petites notes ad lib.* (bars 309–322) are played,
softly.

## The performance

Everything beyond the notes is an interpretation layered over the score's own markings:

- **Tempo**: *Tempo di Tarantella* at ♩. = 158, with a light lilt on each beat. Each four-bar
  phrase presses forward a little and eases at its cadence. The music broadens into double bars
  and key changes and takes a breath after them. *animando* presses about 7% into its climax,
  rides it, then settles. *dolce* and *pesante* are a shade slower. *Più mosso* (bar 498) is
  about 11% faster to the end. Fermatas are held about twice their length, and the last line is
  broad.
- **Dynamics**: the printed levels, *fp*, *sf*/*rfz*, *cresc.*/*dim.* (ramping to the next
  printed level) and hairpins (as swells). Where the print gives none, the orchestral *Tutti*
  enters at least *f*, and an unmarked *Solo* after it steps down to *f*. On top of that, the
  melody grows as it rises above its surroundings, beat 1 of each bar (and beat 2, less) is
  stressed, and eight-bar arcs give it shape. *legg.*, *scherz.* and *scintillante* are lighter;
  *martellato*, *pesante* and *con impeto* heavier.
- **Voicing**: the top of each right-hand chord is louder, inner notes recede, and the bass
  is firm.
- **Chords**: no chord lands all at once. Each hand places its chord separately, the left
  hand usually a few milliseconds ahead. Within a hand the notes fan out, mostly from the bottom
  up, over about 10 ms for an octave to 20–40 ms for a big chord, wider the more notes and the
  wider the stretch. The melody note leads in the right hand and the bass in the left. A chord
  never fans out over more than a third of the time to that hand's next one, so fast repeated
  chords stay crisp. Printed arpeggios roll from the bottom at about 30 ms a note.
- **Touch**: staccato and staccatissimo are short, slurs and held stems legato, accents,
  marcato and tenuto as printed, and unmarked notes slightly detached.
- **Pedal**: as the braille marks it, each *Ped.* lifting and catching again just after the
  beat.
- **Ornaments**: grace notes come just before the beat, and the final D1–D2 tremolo is played
  out in sixteenths.
- **Variation**: the timing wanders slowly by a few milliseconds, and velocities and releases
  vary a little from note to note. The randomness is seeded, so every build is the same.
- **Repeats**: both are taken (bars 141–172 and 391–422), with their first and second endings:
  603 bars, about 7½ minutes.

## License

The code (`brf.py`, `perform.py`, `render.swift`) is under the [MIT license](LICENSE-MIT).

The braille transcription in `espadero.brf` is by Hu Haipeng, for the Braille Orchestra and
Open Braille Music projects ([brailleorch.org](http://www.brailleorch.org)), published on
[IMSLP](https://imslp.org/wiki/Grande_Tarantelle%2C_Op.67_%28Gottschalk%2C_Louis_Moreau%29)
(#933069) under the Creative Commons Attribution-ShareAlike 4.0 license. The MIDI and audio
performances are adaptations of it, and they and the rest of the repository (this README
included) are shared under the same license: [CC BY-SA 4.0](LICENSE-CC-BY-SA-4.0). The Ditson
print of 1874 that the transcription follows, and Gottschalk's and Espadero's music, are in
the public domain.
