"""Find the quiet gaps, on the raw audio.

Two deliberate choices here, both learned the hard way:

- It runs on the RAW mic, never on the normalized copy. Normalizing lifts a quiet gap
  above the detection threshold, and the silence stops registering as one.
- It measures rather than asks the model. Whisper's timestamps interpolate across long
  pauses — it stretches tokens over the gap — so a silence is simply invisible in the
  transcript. It has to be measured from the signal.
"""

from __future__ import annotations

import json
import re

from .episode import Episode
from .shell import ffmpeg, log

_START = re.compile(r"silence_start: ([-\d.]+)")
_END = re.compile(r"silence_end: ([-\d.]+)")


def parse_silencedetect(text: str) -> list[dict[str, float]]:
    """Pair up silencedetect's start/end lines.

    A silence still open when the file ends produces a start with no end; zip drops it,
    which is what we want — trailing silence is handled by the cut, not by this list.
    """
    starts = [float(v) for v in _START.findall(text)]
    ends = [float(v) for v in _END.findall(text)]
    return [{"start": s, "end": e} for s, e in zip(starts, ends, strict=False)]


def run(ep: Episode) -> None:
    cfg = ep.cfg
    ep.need(ep.mic, "the rush carrying the microphone")
    log(f"silencedetect noise={cfg.silence_db} d={cfg.silence_min} (raw audio)")
    proc = ffmpeg(
        [
            "-i",
            ep.mic,
            "-map",
            "0:a:0",
            "-af",
            f"silencedetect=noise={cfg.silence_db}:d={cfg.silence_min}",
            "-f",
            "null",
            "-",
        ],
        allow_fail=True,
        quiet=False,
    )
    found = parse_silencedetect(proc.stderr or "")
    ep.silences.write_text(json.dumps(found, indent=2))
    log(f"silences: {len(found)}")
    if not found:
        log("  (none — you speak without pausing; the cut will come from false starts)")
