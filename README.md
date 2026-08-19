# screencast

A harness that turns a raw OBS screencast into a publishable video: it cuts the false
starts, alternates three shots, writes the subtitles in two languages, drafts the
metadata, and hands you an editable Shotcut project — from one command.

Everything runs **on your machine**. The only thing that ever leaves it is the
transcript text, sent to a model to decide the edit. The rushes stay home.

```bash
cp config.env.example config.env    # first time only
./screencast doctor                 # check the toolchain
./screencast new                    # after a shoot: everything, end to end
```

---

## What it does

You record **two frame-synced files** in one OBS take:

| File | What |
|---|---|
| `<name>.mkv` | the screen, with your webcam baked into a corner, plus your mic |
| `cam/<name> cam.mkv` | the clean full-frame webcam (via the Source Record filter) |

`./screencast new` picks up the newest pair and produces `<name>_montage/deliverable/`:

| File | What |
|---|---|
| `final.mp4` | the edited video — this is what you publish |
| `project.mlt` | an editable 3-track Shotcut project |
| `final.<lang>.srt` | subtitles, native + translation |
| `metadata.txt` | title, description, tags, timestamped chapters |

Nothing is uploaded. Ever. You publish by hand.

## The eight stages

| Stage | Tool | Decides / produces |
|---|---|---|
| `measure` | ffmpeg | audio and image corrections, **measured on this rush, not hardcoded** |
| `transcribe` | whisper.cpp | transcript with word-level timings |
| `silences` | ffmpeg | the quiet gaps, from the signal |
| `montage` | a model | the edit: cuts, shots, chapters, metadata — **from the text alone** |
| `render` | ffmpeg | `final.mp4` |
| `shotcut` | — | `project.mlt` |
| `subtitles` | whisper.cpp + a model | native `.srt` + translation |
| `publish` | — | packages the deliverable; **gated, uploads nothing** |

Run one at a time while iterating — a full run takes minutes, and you should not have to
re-transcribe five minutes of audio to test a render:

```bash
./screencast run render <episode_dir>
```

## The montage is decided from the words, never from the image

The model reads the transcript and assigns every surviving stretch to one of three shots:

- **`ecran`** — the screen with your face in a corner, when you are driving the UI
- **`large`** — the wide shot of you: intro, narration, transitions
- **`serre`** — a tight close-up, for one short punchy line

It also drops fillers, false starts and repeats. Since the decision is textual, **clear
narration is what makes the shots switch** — say what you are doing on screen, and it
follows. You do not change how you film.

## Two outputs, on purpose

`final.mp4` is a deterministic ffmpeg render — ship it. `project.mlt` carries **one track
per shot type**, with a Size/Position/Rotate filter on each track head, so reframing the
close-up means adjusting one filter rather than thirty clips. Both rushes must stay where
they are: the project references them by path.

## Shooting notes, learned the hard way

**Record in MKV.** An MP4 is only readable once its index is written on close: a crash
mid-take loses the whole file, where an MKV stays readable to the last written frame.

**Put the mic alone on audio track 1.** OBS routes every source to all six tracks by
default, so desktop audio lands mixed into your voice — and a mix does not unmix. The
harness reads track 1 and applies *speech*-tuned processing to it.

**Enlarge your terminal font.** A 1440p screen rendered to 1080p shrinks everything by a
quarter; text that is comfortable while you record is unreadable on a phone.

**Light your face.** The correction is clamped on purpose — past a point it turns skin
orange. A lamp facing you beats any filter, and `measure` tells you when it is needed.

## The code

Python, **standard library only, deliberately**: this has to still work in two years on a
reinstalled machine, and every dependency is one more thing that can break on the day of a
shoot. The external binaries it drives are the only requirement, and `doctor` checks them.

Nothing is installed — `./screencast` puts `src/` on the import path and runs.

```bash
uvx pytest        # 47 tests, well under a second
ruff check .
ruff format .
```

Tests cover the pure functions: timecodes, chapter remapping, config parsing, cleanup of
model output. Those are the ones that fail **silently** — a wrong timecode crashes
nothing, it just puts the chapters in the wrong place and nobody notices until the video
is public. Anything that shells out to ffmpeg is verified by running the harness on a real
rush, never by mocking a subprocess.

## License

Private. © Alex Hoyau.
