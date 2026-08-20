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

# Only one overlay can be on screen at a time. When two want the same moment, the more
# specific one wins: the programme is announced once in a video and cannot be moved, a
# list point belongs to the sentence that states it, and a chapter title is a signpost
# that can wait. Observed on a real take: the model tagged one segment as BOTH the
# programme announcement and a list point, which drew a panel and a blurred card on top
# of each other.
OVERLAY_PRIORITY = {"plan": 3, "list": 2, "chapter": 1}

# A list card recalls a point announced earlier. Too soon after the programme panel and it
# only repeats what is still fresh — the viewer read it seconds ago and now the speaker is
# hidden behind it for nothing. Far enough away and it does its job: bringing back a promise
# made minutes ago.
LIST_CARD_MIN_GAP = 30.0

# A chapter band right after the intro card, or right after the programme panel, says again
# what was just said. Both were observed on the first real take: chapter one landed four
# seconds after the intro, chapter two the very second the panel left.
CHAPTER_MIN_GAP = 8.0
# Intro and outro carry music and have to breathe. Matches the pilot's calibration.
INTRO_SECONDS = 4.0
OUTRO_SECONDS = 4.0
# A list card hides the speaker, so it is capped rather than lasting the whole segment.
LIST_CARD_SECONDS = 3.5


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
    list_card_seconds: float = LIST_CARD_SECONDS,
    list_card_min_gap: float = LIST_CARD_MIN_GAP,
    chapter_min_gap: float = CHAPTER_MIN_GAP,
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
                    # The territory, not the name. This is the most-read zone of the
                    # video, and the channel is already carried by the handle on every
                    # chapter band. Falls back to the name for a channel with no kicker.
                    "kicker": channel.get("kicker") or channel.get("name", ""),
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
                    # A property of the channel, not of the episode. Letting the model
                    # write it produced a different call to action every video — which
                    # makes attribution impossible, and produced "écrivez-moi" with no
                    # address at all. The clickable link belongs in the description, where
                    # it can be tracked per video; the card only says the sentence.
                    # Empty channel cta = no line, which beats a random one.
                    "cta": channel.get("cta", ""),
                    "handle": channel.get("handle", ""),
                },
                start=body_offset + body_duration,
                duration=outro_seconds,
            )
        )

    # --- programme: exactly as long as the sentence announcing it
    programme_end: float | None = None
    for seg in kept:
        if not seg.plan or not meta.chapters:
            continue
        start = body_offset + seg.final_start
        programme_end = body_offset + seg.final_end
        overlays.append(
            Overlay(
                kind="plan",
                values={
                    "kicker": channel.get("programme_label", "Au programme"),
                    # The panel lists the CHAPTERS, and a band later repeats one of those
                    # exact labels. One list, seen twice: promising "Installer Jan" and
                    # captioning the same passage "Installation" reads as two different
                    # things to anyone who noticed the first.
                    "chapters": [c.label for c in meta.chapters],
                },
                start=start,
                end=programme_end,
            )
        )
        break  # one programme per video, whatever the model tagged

    # --- chapter bands, except where a card already announced the same chapter
    carded = {
        _point_label(seg.list_item, [c.label for c in meta.chapters])
        for seg in kept
        if seg.list_item
    }
    for chapter in meta.chapters:
        if chapter.label in carded:
            # The full-screen card already named this chapter, louder. A band repeating the
            # same words seconds later is pure noise — observed at 4:50 and 4:56 on a real
            # take, both reading "Gérer les modèles".
            continue
        # remap_to_final already projects a source second onto the cut body; an intro
        # simply pushes that body back, so the slides only add a constant. Nothing about
        # the remapping itself changes.
        start = body_offset + remap_to_final(chapter.at, kept)
        if start < body_offset + chapter_min_gap:
            continue  # too close behind the intro card
        if programme_end is not None and abs(start - programme_end) < chapter_min_gap:
            continue  # butting against the programme panel
        overlays.append(
            Overlay(
                kind="chapter",
                values={"title": chapter.label, "handle": channel.get("handle", "")},
                start=start,
                end=min(start + chapter_overlay, body_offset + body_duration),
            )
        )

    # --- list cards, where each announced point actually BEGINS (not where it was
    # announced: the card recalls the promise, it does not echo the sentence just spoken)
    for seg in kept:
        if not seg.list_item:
            continue
        start = body_offset + seg.final_start
        if programme_end is not None and start - programme_end < list_card_min_gap:
            continue
        overlays.append(
            Overlay(
                kind="list",
                values={
                    "number": _two_digits(seg.list_item.n),
                    "label": _point_label(seg.list_item, [c.label for c in meta.chapters]),
                },
                start=start,
                end=min(start + list_card_seconds, body_offset + body_duration),
            )
        )

    overlays = resolve_conflicts(overlays)
    return SlidePlan(
        cards=cards,
        overlays=overlays,
        body_offset=body_offset,
        total_added=sum(card.duration for card in cards),
    )


def resolve_conflicts(overlays: list[Overlay]) -> list[Overlay]:
    """Keep one overlay on screen at a time, highest priority first.

    A lower-priority overlay that merely starts too early is trimmed rather than dropped —
    a chapter title pushed a second later still does its job. One that would be left with
    almost nothing is dropped instead: a half-second flash reads as a glitch.
    """
    ordered = sorted(overlays, key=lambda o: (-OVERLAY_PRIORITY.get(o.kind, 0), o.start))
    kept: list[Overlay] = []
    for candidate in ordered:
        start, end = candidate.start, candidate.end
        for existing in kept:
            if start < existing.end and end > existing.start:
                if start >= existing.start:
                    start = existing.end          # push it after the one already there
                else:
                    end = existing.start          # or stop it before
        if end - start >= 1.0:
            kept.append(Overlay(candidate.kind, candidate.values, start, end))
    return sorted(kept, key=lambda o: o.start)


def _point_label(item, chapters: list[str]) -> str:
    """The wording of a point, taken from the chapter list.

    A card carries a number; the words live with the chapters and nowhere else, so the
    panel, the band and the card can never say three different things about one passage.
    """
    if item.n.isdigit():
        index = int(item.n) - 1
        if 0 <= index < len(chapters):
            return chapters[index]
    return item.label


def _two_digits(value: str) -> str:
    return f"{int(value):02d}" if value.isdigit() else value


def describe(plan: SlidePlan, body_duration: float) -> str:
    """A readable timeline of where every slide lands — what `screencast plan` prints.

    Worth having as its own view: placement bugs are invisible in a JSON dump and obvious
    on a timeline, and checking them by rendering ten minutes of video is no way to work.
    """
    total = body_duration + plan.total_added
    lines = [
        f"durée finale : {_mmss(total)}  "
        f"(corps {_mmss(body_duration)} + {plan.total_added:.0f}s de cartons)",
        "",
    ]

    events: list[tuple[float, str]] = []
    for card in plan.cards:
        events.append((card.start, f"┏━ {card.kind.upper():8s} {_mmss(card.start)} → "
                                   f"{_mmss(card.end)}   « {card.values.get('title','')} »"))
    for overlay in plan.overlays:
        label = overlay.values.get("title") or overlay.values.get("label") or ""
        if overlay.kind == "plan":
            label = " · ".join(overlay.values.get("chapters", []))[:60]
        events.append((
            overlay.start,
            f"│  {overlay.kind:8s} {_mmss(overlay.start)} → {_mmss(overlay.end)} "
            f"({overlay.duration:.1f}s)  « {label} »",
        ))

    for _, line in sorted(events, key=lambda e: e[0]):
        lines.append(line)
    return "\n".join(lines)


def _mmss(seconds: float) -> str:
    total = int(seconds)
    return f"{total // 60}:{total % 60:02d}"
