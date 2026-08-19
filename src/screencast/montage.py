"""The one stage that asks a model to decide something.

It gets the transcript text and nothing else — no video, no audio. The rushes never leave
the machine; what goes out is the words that were spoken, and that is a deliberate limit,
not an implementation detail.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import timeline as timeline_mod
from .episode import Episode
from .parsing import extract_json_object, strip_code_fences
from .shell import ffprobe_duration, log, run


def build_input(ep: Episode) -> dict:
    """Everything the model needs to decide the edit, in one object."""
    duration = ffprobe_duration(ep.face)
    return {
        "segments": json.loads(ep.segments.read_text()),
        "silences": json.loads(ep.silences.read_text()) if ep.silences.is_file() else [],
        "words": json.loads(ep.words.read_text()) if ep.words.is_file() else [],
        "duration": duration,
    }


def parse_answer(raw: str) -> dict:
    """Turn the model's answer into an EDL dict, tolerating fences and preamble."""
    return json.loads(extract_json_object(strip_code_fences(raw)))


def run_stage(ep: Episode, prompts_dir: Path) -> None:
    ep.need(ep.face, "the clean webcam rush")
    ep.need(ep.segments, "run the transcribe stage first")

    payload = build_input(ep)
    prompt = (prompts_dir / "montage.md").read_text()
    ep.brain_prompt.write_text(f"{prompt}\n\n## DATA\n{json.dumps(payload)}")

    log(f"montage brain: {ep.cfg.claude_bin} (transcript text only leaves the machine)")
    proc = run([ep.cfg.claude_bin, "-p"], stdin_text=ep.brain_prompt.read_text())
    ep.brain_raw.write_text(proc.stdout)

    data = parse_answer(proc.stdout)
    ep.edl.write_text(json.dumps(data, indent=2))

    parsed = timeline_mod.parse(data)
    dropped = [span for span in parsed.timeline if span.drop]
    cut_seconds = sum(span.duration for span in dropped)
    log(
        f"edl: {len(parsed.timeline)} spans, {len(dropped)} dropped "
        f"({cut_seconds:.0f}s), title={parsed.metadata.title!r}"
    )
