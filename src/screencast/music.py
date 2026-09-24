"""Music under the slides, generated locally by sonorita-cli.

Scripted end to end — no model decides anything here. A vibe, a seed, a duration, and the
same shoot always produces the same music.

Three things this module is careful about:

**Music only where nobody speaks.** Music plays under the intro and outro cards and
nowhere else (see plan_beds). Most sonorita vibes come with sung lyrics, and here that is
the point: nobody is speaking under a card, and a sung line is what makes a signature
memorable — so they sing the video's own title.

**A dedicated track per card.** The generator has a hard floor of 30 seconds (below it, it
silently clamps: "durée 8s hors plage [30;210] → bornée à 30s"). We cannot ask for the four
seconds a card lasts. What we can do is generate a track *for that card* and keep its
opening, which is a real beginning — an attack, a setup — where a six-second slice taken
from the middle of a two-minute track has no musical reason to land well.

**The music overruns the slide.** It starts before the card appears and keeps going after
it leaves, fading at both ends. That overlap is what makes a transition feel carried rather
than stapled on: cutting music exactly on the picture announces the edit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass, replace
from pathlib import Path
from string import Template

from .shell import ToolError, log, run
from .slideplan import SlidePlan

PROMPTS = Path(__file__).resolve().parent / "music_prompts"

VIBE_INTRO = "Screencast Intro"
VIBE_OUTRO = "Screencast Outro"

# The generator clamps anything outside this range, so asking for less is pointless.
MIN_DURATION = 30
MAX_DURATION = 210

# How far the music extends past the slide on each side. Lead-in shorter than the tail:
# arriving late sounds like a mistake, leaving late sounds intentional.
LEAD_IN = 0.6
TAIL = 1.4
FADE_IN = 0.5
FADE_OUT = 1.2


@dataclass(frozen=True)
class Bed:
    """One stretch of music: where it plays, what it reads, and at what gain."""

    start: float
    end: float
    track: Path
    source_offset: float
    gain_db: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def seed_for(name: str) -> int:
    """A stable seed derived from the episode name.

    Re-running the pipeline on the same shoot must give the same music: a rerun after a
    tweak should differ only in what was tweaked.
    """
    return int(hashlib.sha256(name.encode()).hexdigest()[:8], 16)


def write_prompts(target: Path, lyrics: dict[str, str]) -> Path:
    """Copy the vibe prompts into `target`, substituting the sung lines.

    The intro and outro prompts carry a `$lyrics` placeholder: what gets sung is the
    video's own title and sign-off, which is why the prompt files cannot simply be used
    where they sit.
    """
    target.mkdir(parents=True, exist_ok=True)
    for source in sorted(PROMPTS.glob("*.md")):
        text = source.read_text()
        key = "intro" if "intro" in source.stem else "outro" if "outro" in source.stem else ""
        rendered = Template(text).safe_substitute(lyrics=lyrics.get(key, "")) if key else text
        (target / source.name).write_text(rendered)
    return target


def generate(ep, vibe: str, seconds: int, *, out_dir: Path, prompts: Path) -> Path:
    """Generate one track, or reuse the one already there.

    Regenerating on every run would burn a GPU minute and, worse, change the music of a
    video that was only re-rendered.
    """
    existing = sorted(out_dir.glob("*.mp3"))
    if existing:
        return existing[0]

    out_dir.mkdir(parents=True, exist_ok=True)
    seconds = max(MIN_DURATION, min(MAX_DURATION, seconds))
    seed = seed_for(f"{ep.root.name}/{vibe}")
    log(f"music: « {vibe} », {seconds}s, seed {seed}")
    try:
        run([
            ep.cfg.sonorita_bin, "--prompts-dir", prompts, "generate",
            "--vibe", vibe, "-n", "1",
            "--duration", str(seconds), "--seed", str(seed),
            "-o", out_dir,
        ], capture=True)
    except ToolError as exc:
        raise ToolError(f"sonorita-cli failed: {exc}") from exc

    produced = sorted(out_dir.glob("*.mp3"))
    if not produced:
        raise ToolError(f"sonorita-cli reported success but produced no track for {vibe}")
    return produced[0]


def _merge(spans: list[tuple[float, float]]) -> list[tuple[float, float]]:
    """Widen each span by the overrun, then merge those that end up touching.

    Two fades crossing each other sound like a mistake; one continuous stretch sounds like
    a decision.
    """
    if not spans:
        return []
    widened = sorted((max(0.0, s - LEAD_IN), e + TAIL) for s, e in spans)
    merged = [list(widened[0])]
    for start, end in widened[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])
    return [(a, b) for a, b in merged]


def with_gains(beds: list[Bed], speech_lufs: float, measure) -> list[Bed]:
    """Set each bed's gain from the loudness of the stretch it actually plays.

    The level is a TARGET, not a gain. A generated track's own loudness varies from one
    run to the next, so a fixed multiplier gives a different result every time: 0.45 on
    the first real track landed the intro at -27.7 LUFS against a body at -16, i.e.
    inaudible. Every bed plays under a card, where nobody is speaking, so each one targets
    the speech level itself: the music should feel as loud as the voice it replaces.

    Per stretch, not per file: a track's average says little about the six seconds used
    under a card. Measuring the whole file put the first real intro at -23 LUFS against a
    target of -16.
    """
    out: list[Bed] = []
    for bed in beds:
        measured = measure(bed.track, bed.source_offset, bed.duration)
        gain = 0.0 if measured is None else speech_lufs - measured
        out.append(replace(bed, gain_db=gain))
    return out


def plan_beds(layout: SlidePlan, tracks: dict[str, Path]) -> list[Bed]:
    """Where music plays: under the cards, and nowhere else.

    Every bed starts at 0 dB; with_gains sets the level once the tracks can be measured.
    """
    beds: list[Bed] = []

    for card in layout.cards:
        track = tracks.get(card.kind)
        if not track:
            continue
        start = max(0.0, card.start - LEAD_IN)
        beds.append(
            Bed(start=start, end=card.end + TAIL, track=track,
                source_offset=0.0, gain_db=0.0)
        )

    # No bed under the speech. It used to play at -18 LUFS below the voice, which Alex put
    # plainly after watching two finished videos: the only music you notice is the intro,
    # and that is because it is the only one not competing with a voice. Music nobody hears
    # is not doing its job — and it cost a GPU generation per video. Silence under speech
    # also makes the blocking moments land harder, which is the whole point of a jingle.
    return sorted(beds, key=lambda b: b.start)


def build_tracks(ep, layout: SlidePlan, intro_lyrics: str, outro_lyrics: str) -> dict[str, Path]:
    """Generate the tracks this video needs — and only those."""
    root = ep.work / "music"
    prompts = write_prompts(root / "prompts", {"intro": intro_lyrics, "outro": outro_lyrics})
    tracks: dict[str, Path] = {}

    kinds = {card.kind for card in layout.cards}
    if "intro" in kinds:
        tracks["intro"] = generate(ep, VIBE_INTRO, MIN_DURATION,
                                   out_dir=root / "intro", prompts=prompts)
    if "outro" in kinds:
        tracks["outro"] = generate(ep, VIBE_OUTRO, MIN_DURATION,
                                   out_dir=root / "outro", prompts=prompts)
    # No bed track: see plan_beds. One generation less per video, too.
    return tracks

