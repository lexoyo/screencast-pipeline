"""The one stage that asks a model to decide something.

It gets the transcript text and nothing else — no video, no audio. The rushes never leave
the machine; what goes out is the words that were spoken, and that is a deliberate limit,
not an implementation detail.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import lang
from . import timeline as timeline_mod
from .episode import Episode
from .parsing import extract_json_object, strip_code_fences
from .shell import brain, ffprobe_duration, log


def build_input(ep: Episode) -> dict:
    """Everything the model needs to decide the edit, in one object."""
    duration = ffprobe_duration(ep.face if ep.has_face else ep.screen)
    return {
        "segments": json.loads(ep.segments.read_text()),
        "silences": json.loads(ep.silences.read_text()) if ep.silences.is_file() else [],
        "words": json.loads(ep.words.read_text()) if ep.words.is_file() else [],
        "duration": duration,
    }


def force_screen_only(data: dict) -> dict:
    """Pin every segment to the screen shot, for a shoot with no camera rush."""
    for segment in data.get("timeline", []):
        segment["scene"] = "ecran"
    return data


def parse_answer(raw: str) -> dict:
    """Turn the model's answer into an EDL dict, tolerating fences and preamble."""
    return json.loads(extract_json_object(strip_code_fences(raw)))


LANGUAGE_NOTE = """## THE SPOKEN LANGUAGE OF THIS SHOOT IS {NAME} ({CODE})

EVERY piece of text you write is in {NAME}, with no exception: the title, the description,
the tags, the chapter labels, the intro and outro cards, and the sung jingle lines. The
cards are burnt into the picture — a card in another language than the audio cannot be
fixed without re-rendering the video.
"""

SCREEN_ONLY_NOTE = """## NO CAMERA ON THIS SHOOT

There is no camera rush: the only shot available is `ecran`. Set `"scene": "ecran"` on
every segment. Everything else — the cuts, the chapters, the metadata — is unchanged.
"""


def run_stage(ep: Episode, prompts_dir: Path) -> None:
    ep.need_face()
    ep.need(ep.segments, "run the transcribe stage first")

    payload = build_input(ep)
    prompt = (prompts_dir / "montage.md").read_text()
    # The harness knows the language; montage.md only says "the spoken language" and lets
    # the model infer it. On an English shoot it produced English metadata and French
    # cards in the same answer — and cards are burnt into the picture.
    spoken = lang.spoken(ep.language())
    prompt = LANGUAGE_NOTE.replace("{NAME}", lang.name(spoken)).replace("{CODE}", spoken) + prompt
    if not ep.has_face:
        # Prepended, not appended: montage.md ends on "Output the JSON object and nothing
        # else", and that instruction is worth keeping as the last thing the model reads.
        prompt = f"{SCREEN_ONLY_NOTE}\n{prompt}"
    ep.brain_prompt.write_text(f"{prompt}\n\n## DATA\n{json.dumps(payload)}")

    log(f"montage brain: {ep.cfg.claude_bin} (transcript text only leaves the machine)")
    answer = brain(ep.cfg.claude_bin, ep.brain_prompt.read_text(), ep.work, "montage")
    ep.brain_raw.write_text(answer)

    data = parse_answer(answer)
    if not ep.has_face:
        # Asked in the prompt, enforced here: a stray "serre" would send the render to a
        # camera file that does not exist, and the failure would surface ten minutes in.
        data = force_screen_only(data)
    ep.edl.write_text(json.dumps(data, indent=2))

    parsed = timeline_mod.parse(data)
    problems = timeline_mod.check(parsed, payload["duration"])
    if problems:
        # The answer stays on disk: the point is to look at what the model actually said,
        # and to be able to try another one without re-transcribing anything.
        raise timeline_mod.TimelineError(
            "the montage brain returned an incoherent timeline:\n  - "
            + "\n  - ".join(problems)
            + f"\nits answer is in {ep.brain_raw}. Another model in BRAIN_MODEL, or "
            "`screencast run montage` again, is the way out."
        )

    dropped = [span for span in parsed.timeline if span.drop]
    cut_seconds = sum(span.duration for span in dropped)
    log(
        f"edl: {len(parsed.timeline)} spans, {len(dropped)} dropped "
        f"({cut_seconds:.0f}s), title={parsed.metadata.title!r}"
    )
