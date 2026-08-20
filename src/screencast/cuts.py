"""Make the model's cuts safe before they reach the render.

The model decides *what* to remove from the text. It is bad at deciding *where* to place
the boundary, for a reason that is not its fault: whisper's timestamps are off by tens of
milliseconds, and it stretches a word across the pause that follows it rather than leaving
a gap. Both failure modes were observed on a real shoot:

  "c'est un peu toutes les — toutes les plateformes"
      The repeat is real and worth cutting. But the cut started at 41.32 s, which is
      exactly where "peu" ends and "toutes" begins — zero margin. The tail of "peu" was
      shaved off and it came out as "c'est un p-".

  "on va dans votre store et on tape Jan"
      The model dropped 46.92-48.32 s giving the reason "silence". There was no silence:
      silencedetect found 67 of them in that video and none there, and the signal peaks at
      -7.9 dB. Whisper had dated the word "et" as lasting 1.4 seconds — stretched over the
      pause after it — and the model read that as a gap. A real word was deleted.

So: keep the model's judgement about meaning, refuse its arithmetic about time.
"""

from __future__ import annotations

from collections.abc import Sequence
from dataclasses import replace
from typing import Any

from .timeline import Edl, Span

# Reasons the model may legitimately give for removing SPEECH. "silence" is deliberately
# absent: gaps are measured from the signal, never inferred from a transcript. "fumble"
# covers a stretch where the speaker gets stuck — it exists so an editorial cut never has
# to disguise itself as a technical one, which is exactly what went wrong before.
SPOKEN_REASONS = ("filler", "falsestart", "repeat", "fumble")


def _overlap(a_start: float, a_end: float, b_start: float, b_end: float) -> float:
    return max(0.0, min(a_end, b_end) - max(a_start, b_start))


def snap_to_silence(
    start: float, end: float, silences: Sequence[dict[str, float]], reach: float
) -> tuple[float, float]:
    """Move each boundary onto a nearby measured silence, if there is one.

    A cut that lands inside a real gap is inaudible, whatever the timestamp error. This is
    the good case and it costs nothing, so it is tried before padding.
    """
    for gap in silences:
        if abs(gap["end"] - start) <= reach:
            start = gap["end"]
        if abs(gap["start"] - end) <= reach:
            end = gap["start"]
    return start, end


def pad_inwards(start: float, end: float, pad: float) -> tuple[float, float] | None:
    """Shrink a cut by `pad` on each side, or drop it if nothing survives.

    Shrinking rather than growing, on purpose: leaving a sliver of hesitation in is a small
    blemish, clipping the attack of the next word is an obvious defect. When in doubt, cut
    less.
    """
    start, end = start + pad, end - pad
    return (start, end) if end - start > 0.05 else None


def has_measured_silence(
    start: float, end: float, silences: Sequence[dict[str, float]], ratio: float = 0.5
) -> bool:
    """Is this span actually quiet, according to the signal?

    Used to refuse a cut the model justified as a silence when nothing was measured there.
    """
    covered = sum(_overlap(start, end, gap["start"], gap["end"]) for gap in silences)
    span = end - start
    return span > 0 and covered / span >= ratio


def sanitize(
    plan: Edl,
    silences: Sequence[dict[str, float]],
    *,
    pad: float = 0.07,
    snap_reach: float = 0.25,
) -> tuple[Edl, list[str]]:
    """Return the plan with every cut made safe, and the list of what was changed.

    The notes are logged: a cut being silently rewritten is how you end up debugging the
    render instead of the decision.
    """
    notes: list[str] = []
    timeline: list[Span] = []

    for span in plan.timeline:
        if not span.drop:
            timeline.append(span)
            continue

        # The model is not allowed to invent silences — those come from the signal.
        if span.reason not in SPOKEN_REASONS and not has_measured_silence(
            span.start, span.end, silences
        ):
            notes.append(
                f"kept {span.start:.2f}-{span.end:.2f}: reason {span.reason!r} but no "
                f"silence was measured there — refusing to delete audible speech"
            )
            timeline.append(replace(span, drop=False, reason="kept:unmeasured-silence"))
            continue

        start, end = snap_to_silence(span.start, span.end, silences, snap_reach)
        snapped = (start, end) != (span.start, span.end)
        if not snapped:
            padded = pad_inwards(start, end, pad)
            if padded is None:
                notes.append(
                    f"kept {span.start:.2f}-{span.end:.2f}: too short to cut safely "
                    f"({span.end - span.start:.2f}s, margin needs {2 * pad:.2f}s)"
                )
                timeline.append(replace(span, drop=False, reason=f"kept:too-short/{span.reason}"))
                continue
            start, end = padded

        timeline.append(replace(span, start=start, end=end))

    return replace(plan, timeline=_reflow(timeline)), notes


def _reflow(timeline: list[Span]) -> list[Span]:
    """Close the holes left by shrinking a cut, so the timeline stays contiguous.

    Time removed from a cut has to go back to a neighbour, otherwise the render skips it
    and the padding achieves the opposite of what it is for.
    """
    if not timeline:
        return timeline
    out = [timeline[0]]
    for span in timeline[1:]:
        previous = out[-1]
        if span.start > previous.end:
            # the gap belongs to whichever neighbour is kept; prefer extending the kept one
            if not previous.drop:
                out[-1] = replace(previous, end=span.start)
            else:
                span = replace(span, start=previous.end)
        out.append(span)
    return out


def report(plan: Edl, silences: Sequence[dict[str, float]]) -> dict[str, Any]:
    """Numbers worth logging after sanitising: how much was removed, and why."""
    dropped = [s for s in plan.timeline if s.drop]
    total = plan.timeline[-1].end if plan.timeline else 0.0
    cut = sum(s.duration for s in dropped)
    by_reason: dict[str, float] = {}
    for span in dropped:
        by_reason[span.reason] = by_reason.get(span.reason, 0.0) + span.duration
    return {
        "cuts": len(dropped),
        "seconds_cut": cut,
        "share": cut / total if total else 0.0,
        "by_reason": by_reason,
    }
