"""Subtitles, transcribed from the EDITED video rather than the rush.

Transcribing the final cut is what keeps the cues aligned: the rush transcript has
timestamps from before ~50 seconds were removed, and shifting them by hand would drift.
Whisper listening to the finished video simply gets it right.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import transcript as transcript_mod
from .episode import Episode
from .parsing import clean_srt
from .shell import brain, ffmpeg, log, run
from .transcribe import whisper_json


def run_stage(ep: Episode, prompts_dir: Path, title: str = "") -> None:
    cfg = ep.cfg
    ep.need(ep.draft, "run the draft stage first")
    ep.subs_dir.mkdir(parents=True, exist_ok=True)

    source_lang = ep.language()
    final_wav = ep.work / "final16.wav"
    ffmpeg(["-i", ep.draft, "-map", "0:a:0", "-ac", "1", "-ar", "16000", final_wav])

    log(f"subtitles: transcribe final cut (lang={source_lang})")
    whisper_json(ep, final_wav, ep.work / "subs_native", word_timings=False, srt=True)

    if source_lang == "auto":
        source_lang = "en"
    native = ep.subs_dir / f"{source_lang}.srt"
    native.write_text((ep.work / "subs_native.srt").read_text())
    log(f"native subs -> subs/{source_lang}.srt")

    target = "fr" if source_lang == "en" else "en"
    log(f"translate subtitles {source_lang} -> {target}")
    template = (prompts_dir / "translate.md").read_text()
    prompt = (
        template.replace("{SRC}", source_lang)
        .replace("{DST}", target)
        .replace("{SRT}", native.read_text())
    )
    (ep.work / "tr_full.txt").write_text(prompt)

    answer = brain(cfg.claude_bin, prompt, ep.work, "sous-titres")
    (ep.work / "tr_raw.srt").write_text(answer)
    (ep.subs_dir / f"{target}.srt").write_text(clean_srt(answer))
    log(f"subs -> subs/{source_lang}.srt + subs/{target}.srt")

    # The readable document is built from the FINISHED subtitles, so its timestamps match
    # the published video rather than the rush.
    try:
        data = transcript_mod.build(ep, prompts_dir, title=title, language=source_lang)
        data = transcript_mod.verify_links(data)
        transcript_mod.write(ep, data, source_lang)
        (ep.work / "links.json").write_text(json.dumps(data.get("links") or [], indent=2))
    except Exception as exc:  # noqa: BLE001 — a missing document must not cost the render
        log(f"⚠ transcript skipped: {exc}")

    # Same document in the other language, built from the subtitles just translated. Its
    # links were already checked on the native pass, so they are only pruned here.
    try:
        data = transcript_mod.build(ep, prompts_dir, title=title, language=target)
        data = transcript_mod.verify_links(data)
        transcript_mod.write(ep, data, target)
    except Exception as exc:  # noqa: BLE001
        log(f"⚠ transcript {target} skipped: {exc}")
