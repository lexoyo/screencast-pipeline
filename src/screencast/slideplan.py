"""Decide where every slide goes on the edited timeline.

Two kinds, and the distinction drives everything downstream:

- **cards** (intro, outro) are segments of their own. They ADD time, so everything after
  them shifts. That is a constant added on top of the existing remapping, not a different
  remapping: `remap_to_final` keeps doing its job untouched.
- **overlays** (programme, chapter, list point) are composited over the picture and add
  nothing. They ride on the shot underneath, so the speaker stays visible and the running
  time is untouched.

Positions are computed here, once, so that the renderer, the Shotcut project and the
chapter list all read the same numbers instead of each deriving their own.
"""

from __future__ import annotations

from dataclasses import dataclass, field

from .timecode import remap_to_final
from .timeline import Edl, KeptSegment

# A chapter overlay confirms what is being said; three seconds is a glance, not a read.
CHAPTER_OVERLAY = 3.0
# Intro and outro carry music and have to breathe. Matches the pilot's calibration.
INTRO_SECONDS = 4.0
OUTRO_SECONDS = 4.0


@dataclass(frozen=True)
class Card:
    """A full-frame slide occupying its own stretch of the timeline."""

    kind: str
    values: dict[str, str]
    start: float
    duration: float

    @property
    def end(self) -> float:
        return self.start + self.duration


@dataclass(frozen=True)
class Overlay:
    """A transparent slide composited over whatever shot is underneath."""

    kind: str
    values: dict[str, str]
    start: float
    end: float

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class SlidePlan:
    cards: list[Card] = field(default_factory=list)
    overlays: list[Overlay] = field(default_factory=list)
    body_offset: float = 0.0
    """How much the body was pushed back by an intro — every chapter shifts by this."""

    total_added: float = 0.0

    def chapter_time(self, final_seconds: float) -> float:
        """Where a body timestamp lands once the cards are in place."""
        return final_seconds + self.body_offset


def build(
    plan: Edl,
    kept: list[KeptSegment],
    *,
    channel: dict[str, str] | None = None,
    intro_seconds: float = INTRO_SECONDS,
    outro_seconds: float = OUTRO_SECONDS,
    chapter_overlay: float = CHAPTER_OVERLAY,
) -> SlidePlan:
    """Lay out the slides over an already-cut timeline."""
    channel = channel or {}
    meta = plan.metadata
    cards: list[Card] = []
    overlays: list[Overlay] = []

    body_offset = 0.0
    if meta.intro:
        cards.append(
            Card(
                kind="intro",
                values={
                    "kicker": channel.get("name", ""),
                    "title": meta.intro.title,
                    "subtitle": meta.intro.subtitle,
                },
                start=0.0,
                duration=intro_seconds,
            )
        )
        body_offset = intro_seconds

    body_duration = sum(seg.duration for seg in kept)

    if meta.outro:
        cards.append(
            Card(
                kind="outro",
                values={
                    "title": meta.outro.title,
                    "cta": meta.outro.subtitle,
                    "handle": channel.get("handle", ""),
                },
                start=body_offset + body_duration,
                duration=outro_seconds,
            )
        )

    # --- programme: exactly as long as the sentence announcing it
    for seg in kept:
        if not seg.plan or not meta.chapters:
            continue
        overlays.append(
            Overlay(
                kind="plan",
                values={
                    "kicker": channel.get("programme_label", "Au programme"),
                    "chapters": [c.label for c in meta.chapters],
                },
                start=body_offset + seg.final_start,
                end=body_offset + seg.final_end,
            )
        )
        break  # one programme per video, whatever the model tagged

    # --- chapter titles, at the remapped position of each marker
    for index, chapter in enumerate(meta.chapters, start=1):
        # remap_to_final already projects a source second onto the cut body; an intro
        # simply pushes that body back, so the slides only add a constant. Nothing about
        # the remapping itself changes.
        start = body_offset + remap_to_final(chapter.at, kept)
        overlays.append(
            Overlay(
                kind="chapter",
                values={"number": f"{index:02d}", "title": chapter.label},
                start=start,
                end=min(start + chapter_overlay, body_offset + body_duration),
            )
        )

    # --- spoken enumeration points, for the length of the segment that announces them
    for seg in kept:
        if not seg.list_item:
            continue
        overlays.append(
            Overlay(
                kind="list",
                values={
                    "number": _two_digits(seg.list_item.n),
                    "label": seg.list_item.label,
                },
                start=body_offset + seg.final_start,
                end=body_offset + seg.final_end,
            )
        )

    overlays.sort(key=lambda o: o.start)
    return SlidePlan(
        cards=cards,
        overlays=overlays,
        body_offset=body_offset,
        total_added=sum(card.duration for card in cards),
    )


def _two_digits(value: str) -> str:
    return f"{int(value):02d}" if value.isdigit() else value
