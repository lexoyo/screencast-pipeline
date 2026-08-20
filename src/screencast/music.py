"""Music under the slides, generated locally by sonorita-cli.

Scripted end to end — no model decides anything here. A station, a seed, a duration, and
the same video always produces the same music.

Two things this module is careful about:

**Instrumental only.** Most sonorita vibes come with sung lyrics, in English. Under a card
that leads into speech, a voice singing over the speaker is unusable. The default vibe is
one whose lyric variation is literally `[instrumental]` and whose prompt says "no vocals".

**The music overruns the slide.** It starts before the card appears and keeps going after
it leaves, fading at both ends. That overlap is what makes a transition feel carried
rather than stapled on: cutting music exactly on the picture announces the edit.
"""

from __future__ import annotations

import hashlib
from dataclasses import dataclass
from pathlib import Path

from .shell import ToolError, log, run
from .slideplan import SlidePlan

# Instrumental by construction — see the module docstring.
DEFAULT_VIBE = "Jazz Guitar Solo"

# sonorita refuses anything outside this range: past it the generation drifts in quality.
MIN_DURATION = 30
MAX_DURATION = 210

# How far the music extends past the slide on each side, and how long it takes to get
# there. Lead-in slightly shorter than the tail: arriving late feels like a mistake,
# leaving late feels intentional.
LEAD_IN = 0.6
TAIL = 1.4
FADE_IN = 0.5
FADE_OUT = 1.2

# Under speech. The pilot settled on 0.15 and it holds up: audible, never competing.
VOLUME = 0.15


@dataclass(frozen=True)
class Bed:
    """One stretch of music, with the slide it accompanies."""

    start: float
    end: float
    source_offset: float

    @property
    def duration(self) -> float:
        return self.end - self.start


def seed_for(name: str) -> int:
    """A stable seed derived from the episode name.

    Re-running the pipeline on the same shoot must produce the same music: a rerun after a
    tweak should differ only in what was tweaked.
    """
    digest = hashlib.sha256(name.encode()).hexdigest()
    return int(digest[:8], 16)


def beds_for(layout: SlidePlan, track_duration: float) -> list[Bed]:
    """Where music plays, and which part of the track each moment uses.

    Every slide gets a bed, overrunning on both sides. Beds that end up overlapping are
    merged: two fades crossing each other sound like a mistake, one continuous stretch
    sounds like a decision.
    """
    spans = [(card.start, card.end) for card in layout.cards]
    spans += [(overlay.start, overlay.end) for overlay in layout.overlays]
    if not spans:
        return []

    widened = sorted((start - LEAD_IN, end + TAIL) for start, end in spans)
    merged: list[list[float]] = [list(widened[0])]
    for start, end in widened[1:]:
        if start <= merged[-1][1]:
            merged[-1][1] = max(merged[-1][1], end)
        else:
            merged.append([start, end])

    beds: list[Bed] = []
    cursor = 0.0
    for start, end in merged:
        start = max(0.0, start)
        length = end - start
        # Walk through the track rather than always replaying its opening, so a video with
        # ten slides does not repeat the same four bars ten times.
        if cursor + length > track_duration:
            cursor = 0.0
        beds.append(Bed(start=start, end=end, source_offset=cursor))
        cursor += length
    return beds


def generate(
    ep, *, vibe: str = DEFAULT_VIBE, duration: int = 120, seed: int | None = None
) -> Path:
    """Generate the track for this episode, or reuse the one already there.

    Regenerating on every run would waste a GPU minute and, worse, change the music of a
    video that was only re-rendered.
    """
    out_dir = ep.work / "music"
    existing = sorted(out_dir.glob("*.mp3"))
    if existing:
        log(f"music: reusing {existing[0].name}")
        return existing[0]

    out_dir.mkdir(parents=True, exist_ok=True)
    duration = max(MIN_DURATION, min(MAX_DURATION, duration))
    seed = seed if seed is not None else seed_for(ep.root.name)
    log(f"music: generating {duration}s of « {vibe} » (seed {seed})")
    try:
        run([
            ep.cfg.sonorita_bin, "generate",
            "--vibe", vibe,
            "-n", "1",
            "--duration", str(duration),
            "--seed", str(seed),
            "-o", out_dir,
        ], capture=True)
    except ToolError as exc:
        raise ToolError(
            f"sonorita-cli failed ({exc}). The cards will be silent — "
            f"set MUSIC=off in config.env to stop trying."
        ) from exc

    produced = sorted(out_dir.glob("*.mp3"))
    if not produced:
        raise ToolError("sonorita-cli reported success but produced no track")
    return produced[0]


def mix_filter(beds: list[Bed], input_index: int = 1) -> tuple[str, str]:
    """Filtergraph laying every bed onto a silent bed of the full length, then mixing.

    Returns (graph, output label). Each bed is cut from the track, faded, attenuated and
    delayed to its position; the whole lot is mixed with the speech that is already there.
    """
    if not beds:
        return "", ""
    parts: list[str] = []
    labels: list[str] = []
    for index, bed in enumerate(beds):
        label = f"m{index}"
        fade_out_at = max(0.0, bed.duration - FADE_OUT)
        parts.append(
            f"[{input_index}:a]atrim={bed.source_offset}:{bed.source_offset + bed.duration},"
            f"asetpts=PTS-STARTPTS,"
            f"afade=t=in:st=0:d={FADE_IN},afade=t=out:st={fade_out_at}:d={FADE_OUT},"
            f"volume={VOLUME},"
            f"adelay={int(bed.start * 1000)}|{int(bed.start * 1000)}[{label}]"
        )
        labels.append(f"[{label}]")
    joined = "".join(labels)
    parts.append(f"[0:a]{joined}amix=inputs={len(beds) + 1}:normalize=0:dropout_transition=0[aout]")
    return ";".join(parts), "[aout]"
