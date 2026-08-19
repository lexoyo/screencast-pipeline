"""Measure the actual rush, then derive the corrections from what was measured.

The point of this stage is that nothing is hardcoded. A shoot in a dim room at dusk and
one under a lamp need different corrections, and guessing them once and freezing them in
config.env would be wrong for every shoot but the one it was tuned on.
"""

from __future__ import annotations

import json
import re

from .episode import Episode
from .shell import ffmpeg, log

# Applied before loudnorm on every shoot: an 80 Hz high-pass kills desk rumble and
# handling noise, afftdn tracks the noise floor instead of gating at a fixed threshold.
DENOISE = "highpass=f=80,afftdn=nf=-25:tn=1"


def _parse_loudnorm(text: str) -> dict[str, str]:
    """Pull the JSON block loudnorm prints to stderr on its measurement pass."""
    blocks = re.findall(r"\{[^{}]+\}", text, re.S)
    if not blocks:
        return {}
    try:
        return json.loads(blocks[-1])
    except json.JSONDecodeError:
        return {}


def _mean_metric(text: str, key: str, fallback: float) -> float:
    """Average one signalstats metric over the sampled frames."""
    values = [
        float(line.split("=")[1]) for line in text.splitlines() if key in line and "=" in line
    ]
    return sum(values) / len(values) if values else fallback


def audio_filter(cfg, measured: dict[str, str]) -> str:
    """Two-pass loudnorm: feed back what pass one measured so pass two is linear.

    Without the measured_* values loudnorm runs in dynamic mode, which pumps the level
    around during quiet passages. With them it applies a single constant gain — which is
    what you want for a voice that was recorded at a steady distance from the mic.
    """
    target = f"loudnorm=I={cfg.audio_lufs}:TP={cfg.audio_tp}:LRA={cfg.audio_lra}"
    if not measured:
        return f"{DENOISE},{target}"
    return (
        f"{DENOISE},{target}"
        f":measured_I={measured['input_i']}"
        f":measured_TP={measured['input_tp']}"
        f":measured_LRA={measured['input_lra']}"
        f":measured_thresh={measured['input_thresh']}"
        f":offset={measured['target_offset']}"
        f":linear=true"
    )


def video_filter(cfg, luma: float, saturation: float) -> str:
    """Lift the webcam image toward the target brightness, within safe bounds.

    Both corrections are clamped: past +/-0.3 brightness the image goes milky, and past
    1.35 saturation skin tones turn orange. Hitting a clamp means the room itself is the
    problem — that is worth saying out loud rather than papering over.
    """
    brightness = max(-0.3, min(0.3, (cfg.face_luma_target - luma) / 255.0))
    sat_gain = max(1.0, min(1.35, 70.0 / saturation)) if saturation > 1 else 1.1
    return (
        f"eq=brightness={brightness:.3f}:contrast=1.06"
        f":saturation={sat_gain:.2f}:gamma=1.02,unsharp=3:3:0.3"
    )


def run(ep: Episode) -> None:
    cfg = ep.cfg
    ep.need(ep.mic, "the rush carrying the microphone")
    ep.need(ep.face, "the clean webcam rush")

    log("measure loudness (loudnorm pass 1)")
    proc = ffmpeg(
        [
            "-i",
            ep.mic,
            "-map",
            "0:a:0",
            "-af",
            f"loudnorm=I={cfg.audio_lufs}:TP={cfg.audio_tp}:LRA={cfg.audio_lra}:print_format=json",
            "-f",
            "null",
            "-",
        ],
        allow_fail=True,
        quiet=False,
    )
    measured = _parse_loudnorm(proc.stderr or "")

    log("measure face luma/saturation (signalstats)")
    stats_file = ep.work / "vstats.txt"
    ffmpeg(
        [
            "-i",
            ep.face,
            "-vf",
            f"signalstats,metadata=print:file={stats_file}",
            "-t",
            "20",
            "-r",
            "1",
            "-an",
            "-f",
            "null",
            "-",
        ],
        allow_fail=True,
    )
    stats_text = stats_file.read_text() if stats_file.is_file() else ""
    luma = _mean_metric(stats_text, "YAVG=", 120.0)
    saturation = _mean_metric(stats_text, "SATAVG=", 60.0)

    af = audio_filter(cfg, measured)
    vf = video_filter(cfg, luma, saturation)
    ep.params.write_text(
        json.dumps(
            {
                "audio_filter": af,
                "video_filter": vf,
                "measured": {"luma": round(luma, 1), "sat": round(saturation, 1)},
            },
            indent=2,
        )
    )
    log(f"measured luma={luma:.0f} sat={saturation:.0f}")
    if luma < 100:
        log("  ⚠ the room is underexposed — a lamp facing you beats any filter")
    if saturation < 10:
        log("  ⚠ saturation is very low; the correction is at its ceiling")

    # Whisper transcribes this normalized, denoised copy — clearer speech, better words.
    # Silence detection deliberately does NOT use it: normalizing lifts quiet gaps above
    # the detection threshold and they stop looking like silence at all.
    log("render normalized mic for transcription")
    ffmpeg(["-i", ep.mic, "-map", "0:a:0", "-af", af, "-ac", "1", "-ar", "16000", ep.mic16])
