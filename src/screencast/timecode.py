"""Time conversions and chapter remapping.

These are the functions that break silently: a wrong timecode doesn't crash anything, it
just puts the chapter markers in the wrong place and nobody notices until the video is
published. Hence the tests in tests/test_timecode.py.
"""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any


def mlt_timecode(seconds: float) -> str:
    """Seconds -> HH:MM:SS.mmm, the format MLT wants in a .mlt project."""
    seconds = max(0.0, float(seconds))
    hours = int(seconds // 3600)
    minutes = int((seconds % 3600) // 60)
    rest = seconds - hours * 3600 - minutes * 60
    return f"{hours:02d}:{minutes:02d}:{rest:06.3f}"


def srt_timecode(seconds: float) -> str:
    """Seconds -> HH:MM:SS,mmm, the format an .srt cue wants (comma, not dot)."""
    return mlt_timecode(seconds).replace(".", ",")


def youtube_timecode(seconds: float) -> str:
    """Seconds -> the M:SS / H:MM:SS form YouTube parses as a chapter marker.

    YouTube is picky here: a leading zero on the hour, or an hour segment on a video
    shorter than an hour, and the chapter is silently ignored.
    """
    total = int(seconds)
    hours, rest = divmod(total, 3600)
    minutes, secs = divmod(rest, 60)
    if hours:
        return f"{hours}:{minutes:02d}:{secs:02d}"
    return f"{minutes}:{secs:02d}"


def remap_to_final(at: float, kept: Sequence[Any]) -> float:
    """Project a source timestamp onto the edited timeline.

    `kept` holds the segments that survived the cut, each carrying its source span
    (start/end) and where it landed in the final video (final_start/final_end).

    A chapter marker can fall inside a segment that was cut — the brain places markers on
    source timestamps, and a false start right at a topic change is exactly the kind of
    thing it removes. When that happens we snap forward to the start of the next surviving
    segment rather than backward, so the chapter opens on the new topic instead of ending
    the previous one.
    """
    if not kept:
        return 0.0
    for seg in kept:
        if seg.start <= at < seg.end:
            return seg.final_start + (at - seg.start)
    later = [seg for seg in kept if seg.start >= at]
    if later:
        return later[0].final_start
    return kept[-1].final_end
