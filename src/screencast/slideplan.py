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
# A tool panel sits below the others: it is useful, but a chapter or a list card marks a
# structural moment, and two panels at once is one too many.
OVERLAY_PRIORITY = {"identity": 5, "plan": 4, "list": 3, "chapter": 2, "tool": 1}

# A list card recalls a point announced earlier. Too soon after the programme panel and it
# only repeats what is still fresh — the viewer read it seconds ago and now the speaker is
# hidden behind it for nothing. Far enough away and it does its job: bringing back a promise
# made minutes ago.
LIST_CARD_MIN_GAP = 30.0
TOOL_SECONDS = 3.5
TOOL_MIN_GAP = 12.0
# Not at 0:00: a caption over the very first frame reads as a title card. Broadcast waits
# for the person to be talking, then names them.
IDENTITY_AT = 2.0
IDENTITY_SECONDS = 4.5

# A chapter band right after the intro card, or right after the programme panel, says again
# what was just said. Both were observed on the first real take: chapter one landed four
# seconds after the intro, chapter two the very second the panel left.
CHAPTER_MIN_GAP = 8.0
# Intro and outro carry music and have to breathe. Matches the pilot's calibration.
INTRO_SECONDS = 6.0
OUTRO_SECONDS = 4.0
# A list card hides the speaker, so it is capped rather than lasting the whole segment.
LIST_CARD_SECONDS = 3.5


DEFAULT_THEME = "alexhoyau"


@dataclass(frozen=True)
class Card:
    """A full-frame slide occupying its own stretch of the timeline."""

    kind: str
    values: dict[str, str]
    start: float
    duration: float
    after_index: int | None = None
    """Which kept segment this card follows in the concat, or None for first/last.

    The intro no longer opens the video: it lands after the spoken summary, which is a
    position in the middle of the body. The renderer needs the segment index, not just a
    timestamp, because it assembles a list of files."""

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
    theme: str = DEFAULT_THEME
    """The channel's palette, carried here because the plan is what the renderers read.

    It used to stop at the channel file: `slides.render` has always taken a `theme`, and
    nothing ever passed one, so every channel rendered in the default palette. Invisible
    while there was one channel whose name happened to be the default — the first Silex
    video came out in the personal channel's navy, with the Silex wording on it."""

    body_offset: float = 0.0
    """How much the body was pushed back by an intro — every chapter shifts by this."""

    total_added: float = 0.0

    intro_at: float | None = None
    """Where the intro card was inserted into the body, if there is one."""

    intro_duration: float = 0.0

    def chapter_time(self, final_seconds: float) -> float:
        """Where a body timestamp lands once the cards are in place.

        The intro card no longer sits at 0:00, so `body_offset` alone stopped being the
        answer: a card inserted mid-body pushes back only what follows it. The published
        chapter list was computed without this and every chapter after the card was early
        by its length — six seconds, enough for a viewer to land before the sentence that
        names the chapter.
        """
        if self.intro_at is not None and final_seconds >= self.intro_at:
            return final_seconds + self.intro_duration + self.body_offset
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

    body_duration = sum(seg.duration for seg in kept)

    # --- where the intro card goes.
    #
    # Not at 0:00 any more. A title card before the first word is a toll gate: the viewer
    # clicked to see the thing, not the branding, and the 30-second retention figure feeds
    # the recommendations. Alex's own shape is hook, then spoken summary, then part one —
    # so the card lands right after the summary, where his voice stops anyway. The jingle
    # becomes a breath between the promise and the content, and it is the only music left
    # in the video that plays alone.
    #
    # The summary segment is already known: it is the one the brain tagged `plan`, the
    # same one that drives the programme panel. Nothing new to ask the model.
    summary_index = next((i for i, seg in enumerate(kept) if seg.plan and meta.chapters), None)
    insert_at = kept[summary_index].final_end if summary_index is not None else 0.0

    def shift(t: float, *, ends: bool = False) -> float:
        """A body timestamp projected onto the final timeline.

        `ends=True` for the end of something that stops exactly where the card begins —
        the summary panel does, and without this it would be pushed past the card and
        stay on screen over it.
        """
        if not meta.intro:
            return t
        crossed = t > insert_at if ends else t >= insert_at
        return t + intro_seconds if crossed else t

    body_offset = intro_seconds if (meta.intro and insert_at == 0.0) else 0.0
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
                start=insert_at,
                duration=intro_seconds,
                after_index=summary_index,
            )
        )

    if meta.outro:
        cards.append(
            Card(
                kind="outro",
                values={
                    "title": channel.get("outro_title") or meta.outro.title,
                    # A property of the channel, not of the episode. Letting the model
                    # write it produced a different call to action every video — which
                    # makes attribution impossible, and produced "écrivez-moi" with no
                    # address at all. The clickable link belongs in the description, where
                    # it can be tracked per video; the card only says the sentence.
                    # Empty channel cta = no line, which beats a random one.
                    "cta": channel.get("cta", ""),
                    "handle": channel.get("handle", ""),
                },
                start=shift(body_duration),
                duration=outro_seconds,
            )
        )

    # --- programme: exactly as long as the sentence announcing it
    programme_end: float | None = None
    for seg in kept:
        if not seg.plan or not meta.chapters:
            continue
        start = shift(seg.final_start)
        programme_end = shift(seg.final_end, ends=True)
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
        start = shift(remap_to_final(chapter.at, kept))
        if start < shift(0.0) + chapter_min_gap:
            continue  # too close behind the intro card
        if programme_end is not None and abs(start - programme_end) < chapter_min_gap:
            continue  # butting against the programme panel
        overlays.append(
            Overlay(
                kind="chapter",
                values={"title": chapter.label, "handle": channel.get("handle", "")},
                start=start,
                end=min(start + chapter_overlay, shift(body_duration)),
            )
        )

    # --- list cards, where each announced point actually BEGINS (not where it was
    # announced: the card recalls the promise, it does not echo the sentence just spoken)
    for seg in kept:
        if not seg.list_item:
            continue
        start = shift(seg.final_start)
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
                end=min(start + list_card_seconds, shift(body_duration)),
            )
        )

    # --- identity band: who is talking, in the opening seconds.
    # The intro card moved after the spoken summary, so for the first minute nothing said
    # whose channel this was. Putting content first was the point; leaving identity
    # nowhere was not.
    if channel.get("name") and body_duration > IDENTITY_AT + IDENTITY_SECONDS:
        overlays.append(
            Overlay(
                kind="identity",
                values={
                    "name": channel.get("name", ""),
                    "kicker": channel.get("kicker", ""),
                    "handle": channel.get("handle", ""),
                },
                start=shift(IDENTITY_AT),
                end=shift(IDENTITY_AT + IDENTITY_SECONDS),
            )
        )

    # --- tool panels: the name, what it is, and the URL, when a project is first named.
    # The only panel carrying something the viewer cannot get from the audio.
    last_tool = -TOOL_MIN_GAP
    spoken = [(seg.start, seg.end) for seg in kept]
    for tool in meta.tools:
        if not any(a <= tool.at < b for a, b in spoken):
            # Named in a stretch that was cut. remap_to_final would pin it to the edge of
            # the cut, putting the panel on screen at a moment the name is never spoken.
            continue
        start = shift(remap_to_final(tool.at, kept))
        if start < shift(0.0) or start >= shift(body_duration) - TOOL_SECONDS:
            continue  # named in a stretch that was cut, or too close to the end
        if start - last_tool < TOOL_MIN_GAP:
            # Alex names five projects in one breath at 6:23. Stacking five panels there
            # would be a slideshow, not an annotation.
            continue
        overlays.append(
            Overlay(
                kind="tool",
                values={"name": tool.name, "what": tool.what, "url": _short_url(tool.url)},
                start=start,
                end=min(start + TOOL_SECONDS, shift(body_duration)),
            )
        )
        last_tool = start

    overlays = resolve_conflicts(overlays)
    return SlidePlan(
        cards=cards,
        overlays=overlays,
        theme=(channel or {}).get("theme") or DEFAULT_THEME,
        body_offset=body_offset,
        intro_at=insert_at if (meta.intro and insert_at > 0.0) else None,
        intro_duration=intro_seconds if meta.intro else 0.0,
        total_added=sum(card.duration for card in cards),
    )


# A band carries three pieces of text to read; a chapter title is one line seen in a
# glance. Squeezed below this it flashes rather than informs, and is dropped instead.
READABLE = {"tool": 2.5, "identity": 2.5}


def _readable(kind: str) -> float:
    return READABLE.get(kind, 1.0)


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
        if end - start >= _readable(candidate.kind):
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


def _short_url(url: str) -> str:
    """`https://fedoraproject.org/` -> `fedoraproject.org`.

    Nobody types the scheme, and on a band that must hold one line it costs eight
    characters of the description for no information at all.
    """
    return url.removeprefix("https://").removeprefix("http://").removeprefix("www.").rstrip("/")


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
        label = (overlay.values.get("title") or overlay.values.get("label")
                 or overlay.values.get("name") or "")
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
