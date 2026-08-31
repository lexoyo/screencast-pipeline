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

## On a fresh machine

Fedora, from nothing to a working setup:

```bash
git clone git@github.com:lexoyo/screencast-pipeline.git ~/_/screencast-pipeline
cd ~/_/screencast-pipeline
./scripts/install.sh --check        # says what is missing, changes nothing
./scripts/install.sh                # installs it, after confirmation
cp config.env.example config.env
./scripts/setup-obs.sh              # the two-output OBS scene
./screencast doctor
```

`install.sh` handles ffmpeg (with the H.264 fix), OBS, Shotcut, Chromium, and builds
whisper.cpp — **with CUDA when an NVIDIA card is present**, which is worth doing: 16
minutes of audio take 5 min 41 s on this CPU and 46 s on the GPU. It reads the card's own
compute capability rather than assuming one, and installs the gcc compat package when the
system compiler is newer than nvcc accepts.

**Two things it deliberately does not install**, because neither is ours to package:

| | |
|---|---|
| `claude` | the model that decides the edit — install and authenticate it yourself |
| `sonorita-cli` | the music under the cards — separate RPM. Without it, the video is simply made without music, and says so |

**Chromium is never touched**: it ships with Fedora, it renders the slides, and pulling a
second copy would add Node and 150 MB for a job `chromium-browser --headless` does in
under a second.

Everything else that matters is in this repository and comes back with the clone: the
prompts (`src/screencast/prompts/`), the music prompts, the slide templates and channel
theme, the glossary of words whisper gets wrong, and `config.env.example` — which is kept
key-for-key in step with a working `config.env`, so copying it is enough.

What does **not** come back, by design: the rushes, the models (re-downloaded by
`install.sh`, ~2 GB), and any browser session used to publish.

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
| `metadata.<lang>.txt` | the same, translated, for the platform's per-language fields |

Nothing is uploaded. Ever. You publish by hand.

## Shooting for someone else, or in another language

Two flags, both optional, both per run — nothing to edit and remember to edit back:

```bash
./screencast --channel silex --lang en new    # a Silex documentation screencast
```

`--channel` picks the identity painted on the cards: the name, the handle, the wording,
the theme. One JSON file per channel in `src/screencast/channels/`, with its palette in
`src/screencast/themes/`. `alexhoyau` is the default; `silex` shoots the official
documentation, on the docs' own colours.

## A shoot with no camera

The camera rush feeds the wide and close-up shots. A documentation screencast usually
wants neither — the screen already carries the webcam in a corner, baked in by OBS — so it
is optional:

```bash
./screencast --no-cam new
./screencast --cam "/path/to/that take cam.mkv" new   # pair a specific one
```

Without a camera every segment is the screen shot, the face correction is skipped, and the
Shotcut project keeps its empty wide/close-up tracks so the timeline reads the same.

Shooting without a camera is **recorded in the episode**, so a later `run` can tell it
apart from a camera rush that went missing — an archived file or an unmounted drive stops
the run instead of quietly producing a screen-only video.

`new` pairs the screen rush with the camera file **closest to it in time**, and only when
the two were written within five minutes of each other. Further apart, they are almost
certainly different takes — the camera folder keeps every past shoot — so it stops and
asks rather than putting another day's face onto this video.

`--lang` sets the spoken language for that run, overriding `FORCE_LANG` from config.env
(`auto` hands the choice back to whisper). It decides more than transcription: the
deliverable always ships the spoken language **plus one translation** — subtitles,
transcript and metadata — and which one that is follows from it. FR shoots translate to
EN, EN shoots to FR.

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

## Another model than Claude

Every model call goes through one setting, `CLAUDE_BIN`: the pipeline pipes the prompt to
that command's stdin and reads the answer back from stdout. Anything honouring that
contract can do the job. `scripts/brain.sh` is one such thing — same interface, served by
**opencode** (so, OpenRouter) instead of Claude:

```sh
# config.env
CLAUDE_BIN="$HOME/_/screencast-pipeline/scripts/brain.sh"
```

The model is chosen right below it, as `BRAIN_MODEL` — `config.env` ships a few named
and priced, one per commented line. **Left commented, the model you picked in opencode's
TUI is the one that answers**, and the episode's log names it, so choosing there and
reading here stay in agreement. The environment wins over the file, to try one out for a single
run:

```sh
BRAIN_MODEL=openrouter/z-ai/glm-5.2 ./screencast run <ep>
```

The id is `provider/model` — the `openrouter/` prefix included. Without it opencode
answers `Unexpected server error`, which names nothing; the wrapper turns that into a
sentence saying what the id should look like.

Three details the wrapper exists for. It declares, in that same throwaway directory, an
opencode agent with **no tools at all** — the one thing that makes this work. `opencode
run` otherwise starts an *agent*, and a model in an agent harness behaves like one: the
first montage attempt came back as "I'll analyse this transcript carefully…" and then
handed control back, waiting to use tools it had no use for, having written no JSON. With
no tools, answering is all that is left. It runs in an **empty directory**, so the brain
sees the prompt on stdin and nothing else — no `AGENTS.md`, no episode files. And it reads
`--format json`, so the coloured `> build · …` banner opencode prints never ends up inside
a `.srt`. The privacy line does not move: the rushes stay here, the
transcript text is what goes out — to OpenRouter now rather than to Anthropic.

Every call announces itself — the model that actually answered (read back from opencode's
own events, not from what we asked for), the size of the prompt, the tokens read and
written, the cost, the elapsed time. Those lines land in the terminal *and* in the
episode's `work/log.md`, so a montage is traceable to the model that decided it.
Set `BRAIN_LOG` to a directory and each call also leaves a folder behind: the prompt as
sent, the answer as received, the provider's raw event stream, and a `meta.txt`. That is
what lets you replay one prompt through two models and compare, rather than remember.

**The five calls**, if you are choosing a model: the montage EDL (the demanding one —
around 50k tokens of transcript in, structured JSON out), the subtitle translation, the
transcript document and its links, the English metadata, and the editorial QC pass. The
last two are short and forgiving; the montage is where a weak model breaks first. Measured
through GLM-5.2 on a 16-minute episode, the QC pass answers in 9 s.

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

[MIT](LICENSE). © 2026 Alex Hoyau.
