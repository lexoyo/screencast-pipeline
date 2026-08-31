"""Transcription with whisper.cpp, entirely on this machine.

Two things come out of here: sentence-ish segments, which the brain reads to decide the
edit, and word-level timings, which let it cut a false start mid-sentence instead of only
at segment boundaries.
"""

from __future__ import annotations

import json
from pathlib import Path
from typing import Any

from . import glossary
from .episode import Episode
from .shell import ffmpeg, log, run


def segments_from_whisper(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Flatten whisper's JSON into {i, start, end, text}, seconds rather than milliseconds."""
    return [
        {
            "i": index,
            "start": seg["offsets"]["from"] / 1000,
            "end": seg["offsets"]["to"] / 1000,
            "text": seg.get("text", ""),
        }
        for index, seg in enumerate(data.get("transcription", []))
    ]


def words_from_whisper(data: dict[str, Any]) -> list[dict[str, Any]]:
    """Regroup whisper's tokens into words with their own timings.

    whisper.cpp emits sub-word tokens; a leading space is what marks the start of a new
    word, so tokens are glued to the previous word until one arrives with that space.
    Special markers like [_BEG_] are skipped.
    """
    words: list[dict[str, Any]] = []
    current: dict[str, Any] | None = None
    for seg in data.get("transcription", []):
        for token in seg.get("tokens", []):
            text = token.get("text", "")
            if not text.strip() or text.strip().startswith("[_"):
                continue
            offsets = token.get("offsets", {})
            if offsets.get("from") is None:
                continue
            start = round(offsets["from"] / 1000, 2)
            end = round(offsets["to"] / 1000, 2)
            if text.startswith(" ") or current is None:
                if current:
                    words.append(current)
                current = {"start": start, "end": end, "text": text.strip()}
            else:
                current["text"] += text.strip()
                current["end"] = end
    if current:
        words.append(current)
    return words


def whisper_json(
    ep: Episode, audio: Path, out_stem: Path, *, word_timings: bool, srt: bool = False
) -> None:
    """Invoke whisper-cli. `-ml 70` keeps segments near sentence length.

    Shorter segments give the brain finer granularity: it can drop a trailing incomplete
    clause without taking the whole paragraph with it.
    """
    cfg = ep.cfg
    lang = cfg.forced_lang or "auto"
    cmd: list[str | Path] = [
        cfg.whisper_bin,
        "-m",
        cfg.whisper_model,
        "-f",
        audio,
        "-l",
        lang,
        "-of",
        out_stem,
    ]
    # Prime the decoder with the names it gets wrong. `--carry-initial-prompt` repeats the
    # prompt on every window: without it the glossary only biases the opening minute, and a
    # name spoken at minute nine comes out mangled exactly as before.
    # ep.language() and not cfg.forced_lang: on the subtitle pass the language whisper
    # detected is already written to lang.txt, and priming that take in another language is
    # exactly what this argument exists to prevent.
    prompt = glossary.as_prompt(glossary.load(), language=ep.language())
    if prompt:
        cmd += ["--prompt", prompt, "--carry-initial-prompt"]
    if word_timings:
        cmd += ["-ojf", "-dtw", cfg.whisper_dtw_model, "-ml", "70"]
    if srt:
        cmd += ["-osrt"]
    run(cmd, capture=True)


def run_stage(ep: Episode) -> None:
    cfg = ep.cfg
    if not ep.mic16.is_file():
        # measure normally produces this; extract a raw copy if someone ran stages out of order
        ep.need(ep.mic, "the rush carrying the microphone")
        log("extract raw mic 16k (measure did not run first)")
        ffmpeg(["-i", ep.mic, "-map", "0:a:0", "-ac", "1", "-ar", "16000", ep.mic16])

    lang = cfg.forced_lang or "auto"
    log(f"whisper ({cfg.whisper_dtw_model}) lang={lang} on normalized audio")
    whisper_json(ep, ep.mic16, ep.work / "transcript", word_timings=True)

    data = json.loads(ep.transcript_json.read_text())
    segments = segments_from_whisper(data)
    words = words_from_whisper(data)

    # Second pass, for what the prompt did not catch. Corrections are logged rather than
    # applied silently: a word in a transcript that nobody can trace back to the audio is
    # worse than the mistake it replaced.
    terms = glossary.load()
    fixed_total: list[tuple[str, str]] = []
    for item in (*segments, *words):
        item["text"], changed = glossary.fix(item["text"], terms)
        fixed_total += changed
    if fixed_total:
        counted: dict[tuple[str, str], int] = {}
        for pair in fixed_total:
            counted[pair] = counted.get(pair, 0) + 1
        log(f"glossary: {len(fixed_total)} corrections")
        for (before, after), count in sorted(counted.items(), key=lambda kv: -kv[1]):
            log(f"  {before!r} → {after!r} ×{count}")
    ep.segments.write_text(json.dumps(segments, indent=2))
    ep.words.write_text(json.dumps(words))

    detected = cfg.forced_lang or data.get("result", {}).get("language") or "auto"
    ep.lang_file.write_text(f"{detected}\n")
    log(f"language={detected}  segments={len(segments)}  words={len(words)}")
