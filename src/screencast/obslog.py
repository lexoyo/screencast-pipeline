"""Read the real start times of the two recordings out of the OBS log.

Why this exists: the camera file is written by the Source Record filter, a *separate*
output. It starts a moment after the main recording and stops a moment before it — and
neither delay is the same. Deriving the offset from the difference in file durations
therefore adds the two together, and lands nowhere near the truth:

    screen starts   01:20:57.454
    camera starts   01:20:57.642    <- the offset: 188 ms
    camera stops    01:31:58.321
    screen stops    01:31:58.842    <- the camera stopped 521 ms early

    difference of durations = 188 + 521 = 709 ms, i.e. almost four times the real offset.

Measured on a real shoot: the pipeline was shifting the face shots by 733 ms where 188 was
needed. Lip sync is perceptible from about 45 ms, so it was twelve times over the line.

OBS writes both timestamps to its log every single session, so we read them rather than
guess. The duration difference stays as a fallback, but a loud one — never applied
silently, because a silent 500 ms error is exactly what took a whole shoot to notice.
"""

from __future__ import annotations

import re
from datetime import timedelta
from pathlib import Path

DEFAULT_LOG_DIR = Path.home() / ".config" / "obs-studio" / "logs"

# 01:20:57.454: [ffmpeg muxer: 'simple_file_output'] Writing file '/path/to/screen.mkv'...
_LINE = re.compile(r"^(\d{2}):(\d{2}):(\d{2})\.(\d{3}):\s+(.*)$")
_WRITING = re.compile(r"Writing (?:Hybrid MP4/MOV )?file '([^']+)'")
_SOURCE_RECORD = "Source Record"


class OffsetUnknown(Exception):
    """No OBS log could tell us when the two recordings started."""


def _seconds(hh: str, mm: str, ss: str, ms: str) -> float:
    return int(hh) * 3600 + int(mm) * 60 + int(ss) + int(ms) / 1000


def parse_log(text: str, screen_name: str) -> float:
    """Seconds between the start of the screen recording and the start of the camera one.

    `screen_name` is matched on the file name alone: the log records the path OBS wrote
    to, which is not where the episode folder symlinks it from.

    A session log can hold several takes — a false start, then the real one — so we anchor
    on the line naming this screen file and take the next Source Record start after it.
    """
    events: list[tuple[float, str, str]] = []
    for line in text.splitlines():
        stamp = _LINE.match(line)
        if not stamp:
            continue
        hh, mm, ss, ms, rest = stamp.groups()
        writing = _WRITING.search(rest)
        if writing:
            events.append((_seconds(hh, mm, ss, ms), rest, Path(writing.group(1)).name))

    screen_index = next((i for i, (_, _, name) in enumerate(events) if name == screen_name), None)
    if screen_index is None:
        raise OffsetUnknown(f"no 'Writing file' line for {screen_name}")

    # Ordered by position in the file, never by clock value: an evening session runs past
    # midnight and 23:54 would otherwise compare as "later" than 01:20.
    camera = next(
        (at for at, rest, _ in events[screen_index + 1 :] if _SOURCE_RECORD in rest), None
    )
    if camera is None:
        raise OffsetUnknown(f"no Source Record output started after {screen_name}")

    offset = camera - events[screen_index][0]
    if offset < 0:  # the take itself straddled midnight
        offset += timedelta(days=1).total_seconds()
    if offset > 60:
        raise OffsetUnknown(
            f"implausible offset of {offset:.0f}s between the two outputs — log misread"
        )
    return offset


def find_offset(screen: Path, log_dir: Path | None = None) -> float:
    """Look through the OBS logs for the session that produced this recording.

    Newest first: the log we want is almost always the most recent one, and scanning stops
    as soon as a log names the file.
    """
    folder = log_dir or DEFAULT_LOG_DIR
    if not folder.is_dir():
        raise OffsetUnknown(f"no OBS log directory at {folder}")

    logs = sorted(folder.glob("*.txt"), key=lambda p: p.stat().st_mtime, reverse=True)
    name = screen.resolve().name
    for log in logs:
        try:
            text = log.read_text(errors="replace")
        except OSError:
            continue
        if name not in text:
            continue
        return parse_log(text, name)
    raise OffsetUnknown(f"no OBS log mentions {name}")
