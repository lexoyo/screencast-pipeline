"""The last audio pass of the melt render: loudness to the config target, peaks under it.

melt makes the picture and the mix. Its levelling cannot hit the delivery target on its
own: MLT's `dynamic_loudness` is not loudnorm (the 23/09 take came out at -15.8 LUFS
against -16), and its limiter counts SAMPLES — between two samples, and again once AAC
has encoded them, the waveform rose to +1.5 dBFS on that same take.

So the mix leaves melt with lossless audio, and ffmpeg does what the ffmpeg path does:
two-pass loudnorm (measure, then apply the measurement with linear=true) to AUDIO_LUFS /
AUDIO_TP / AUDIO_LRA. The picture is copied, never re-encoded — the pass costs seconds.

Then the result is MEASURED, after AAC, with ebur128's true-peak meter. AAC can push a
peak back over a ceiling loudnorm had respected; when it does, the pass is redone with the
ceiling lowered by the overshoot. A render that still overshoots stops the run rather than
shipping hot.
"""

from __future__ import annotations

import re
import time
from pathlib import Path

from .shell import ToolError, ffmpeg, log, run

# How much lower the next attempt aims, beyond the measured overshoot: AAC's own error is
# not exactly repeatable from one encode to the next.
MARGIN = 0.3
ATTEMPTS = 4


def parse_loudnorm(text: str) -> dict[str, str]:
    """The JSON block loudnorm prints on its measurement pass."""
    import json

    blocks = re.findall(r"\{[^{}]+\}", text, re.S)
    if not blocks:
        return {}
    try:
        return json.loads(blocks[-1])
    except json.JSONDecodeError:
        return {}


def loudnorm_filter(lufs: float, tp: float, lra: float, measured: dict[str, str]) -> str:
    """The second pass: loudnorm fed what the first one measured.

    With the measurements it applies one constant gain when that gain fits under the
    ceiling, and falls back to its own dynamic mode otherwise — the same decision the
    ffmpeg path makes in measure.audio_filter.
    """
    target = f"loudnorm=I={lufs}:TP={tp:.2f}:LRA={lra}"
    if not measured:
        return target
    return (
        f"{target}"
        f":measured_I={measured['input_i']}"
        f":measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}"
        f":measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}"
        ":linear=true"
    )


def parse_ebur128(text: str) -> dict[str, float]:
    """Integrated loudness, loudness range and true peak from ebur128's summary."""
    summary = text[text.rfind("Summary:"):] if "Summary:" in text else text
    out: dict[str, float] = {}
    for key, pattern in (("I", r"I:\s+(-?[\d.]+|-inf) LUFS"),
                         ("LRA", r"LRA:\s+(-?[\d.]+) LU\b"),
                         ("TP", r"True peak:\s+Peak:\s+(-?[\d.]+|-inf) dBFS")):
        found = re.search(pattern, summary, re.S)
        if found:
            out[key] = float(found.group(1))
    return out


def measure(path: Path) -> dict[str, float]:
    """I / LRA / true peak of a finished file, as a player will decode it."""
    proc = run(["ffmpeg", "-hide_banner", "-nostats", "-i", path, "-map", "0:a:0",
                "-af", "ebur128=framelog=quiet:peak=true", "-f", "null", "-"],
               capture=True, allow_fail=True)
    return parse_ebur128(proc.stderr or "")


def next_ceiling(ceiling: float, target_tp: float, measured_tp: float) -> float:
    """Where to aim next when the encoded file peaked at `measured_tp`."""
    return ceiling - (measured_tp - target_tp) - MARGIN


def master(ep, source: Path, out: Path) -> dict[str, float]:
    """Loudness-normalise `source`'s audio into `out`, picture copied. Returns the measure."""
    cfg = ep.cfg
    started = time.monotonic()
    log("master: measure (loudnorm pass 1)")
    proc = ffmpeg(
        ["-i", source, "-map", "0:a:0",
         "-af", f"loudnorm=I={cfg.audio_lufs}:TP={cfg.audio_tp}:LRA={cfg.audio_lra}"
                ":print_format=json",
         "-f", "null", "-"],
        allow_fail=True, quiet=False,
    )
    measured = parse_loudnorm(proc.stderr or "")
    if not measured:
        raise ToolError("master: loudnorm printed no measurement")

    ceiling = cfg.audio_tp
    result: dict[str, float] = {}
    for attempt in range(1, ATTEMPTS + 1):
        ffmpeg([
            "-i", source, "-map", "0:v:0", "-map", "0:a:0",
            "-af", loudnorm_filter(cfg.audio_lufs, ceiling, cfg.audio_lra, measured),
            "-c:v", "copy",
            # loudnorm works at 192 kHz internally and outputs at that rate
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-movflags", "+faststart", out,
        ])
        result = measure(out)
        tp = result.get("TP", float("inf"))
        log(f"master: pass {attempt} ceiling {ceiling:.2f} -> I {result.get('I')} LUFS, "
            f"LRA {result.get('LRA')} LU, true peak {tp} dBTP")
        if tp <= cfg.audio_tp:
            break
        ceiling = next_ceiling(ceiling, cfg.audio_tp, tp)
    else:
        raise ToolError(f"master: true peak still {result.get('TP')} dBTP after {ATTEMPTS} "
                        f"passes, over the {cfg.audio_tp} ceiling")
    log(f"master: {time.monotonic() - started:.0f} s")
    return result
