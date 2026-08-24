"""The readable transcript: prose, section titles, and the links to what was mentioned.

A deliverable in its own right, not a by-product of the subtitles. A `.srt` is read three
lines at a time over a moving picture; this is read on its own, so it gets paragraphs,
punctuation and links — none of which belong in a subtitle, where a `[text](url)` would sit
unreadable over the video.

Links are only ever *proposed* here. The model is told to leave a URL empty rather than
guess one, and what it returns is a draft: nobody checks a description before publishing,
so a confidently wrong link would ship.
"""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from pathlib import Path

from . import links as links_mod
from .episode import Episode
from .parsing import extract_json_object, strip_code_fences
from .shell import brain, log

CUE = re.compile(
    r"(\d+)\s*\n(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*-->\s*(\d{2}):(\d{2}):(\d{2}),(\d{3})\s*\n(.*?)(?=\n\s*\n|\Z)",
    re.S,
)


@dataclass(frozen=True)
class Cue:
    index: int
    start: float
    end: float
    text: str


def parse_srt(text: str) -> list[Cue]:
    """Read an .srt into cues. Tolerant: a malformed block is skipped, not fatal."""
    cues: list[Cue] = []
    for match in CUE.finditer(text.replace("\r", "")):
        index, h1, m1, s1, ms1, h2, m2, s2, ms2, body = match.groups()
        cues.append(
            Cue(
                index=int(index),
                start=int(h1) * 3600 + int(m1) * 60 + int(s1) + int(ms1) / 1000,
                end=int(h2) * 3600 + int(m2) * 60 + int(s2) + int(ms2) / 1000,
                text=" ".join(line.strip() for line in body.strip().splitlines()),
            )
        )
    return cues


def links_section(links: list[dict], label: str = "Projets mentionnés") -> str:
    """The block appended to the YouTube description.

    Timestamped, so a viewer can jump to where a tool was shown; and a link with no URL is
    still listed by name, because knowing what to search for is most of the value.
    """
    if not links:
        return ""
    lines = [f"━━━ {label.upper()} ━━━"]
    for item in sorted(links, key=lambda x: x.get("at", 0)):
        at = int(item.get("at", 0))
        stamp = f"{at // 60}:{at % 60:02d}"
        name = item.get("name", "").strip()
        url = item.get("url", "").strip()
        lines.append(f"{stamp}  {name}" + (f"  {url}" if url else ""))
    return "\n".join(lines)


def build(ep: Episode, prompts_dir: Path, title: str, language: str) -> dict:
    """Ask the model for the document and the links, from the finished subtitles."""
    subtitles = sorted(ep.subs_dir.glob(f"{language}.srt")) or sorted(ep.subs_dir.glob("*.srt"))
    if not subtitles:
        raise FileNotFoundError("no subtitles to build a transcript from")

    cues = parse_srt(subtitles[0].read_text())
    payload = {
        "language": language,
        "title": title,
        "cues": [
            {"i": c.index, "start": round(c.start, 2), "end": round(c.end, 2), "text": c.text}
            for c in cues
        ],
    }
    prompt = (prompts_dir / "transcript.md").read_text()
    full = f"{prompt}\n\n## DATA\n{json.dumps(payload, ensure_ascii=False)}"
    (ep.work / "transcript_prompt.txt").write_text(full)

    log(f"transcript: {len(cues)} cues → document + links")
    answer = brain(ep.cfg.claude_bin, full)
    (ep.work / "transcript_raw.txt").write_text(answer)
    return json.loads(extract_json_object(strip_code_fences(answer)))


def verify_links(data: dict) -> dict:
    """Check every proposed URL, drop the dead ones from both the list and the document.

    "Sure of it" is not "still there": a project moves, a repo is renamed, a domain lapses.
    Nobody proof-reads a description before publishing, so the check happens here rather
    than in someone's head.
    """
    proposed = data.get("links") or []
    markdown = data.get("markdown", "")
    urls = [x["url"] for x in proposed if x.get("url")] + links_mod.urls_in(markdown)
    if not urls:
        return data

    results = links_mod.check_all(urls)
    dead = [r for r in results.values() if not r.usable]
    log(f"liens : {len(results)} vérifiés, {len(dead)} écarté(s)")
    for line in links_mod.report(results):
        log(line)

    return {
        **data,
        "links": links_mod.prune(proposed, results),
        "markdown": links_mod.unlink_dead(markdown, results),
    }


def write(ep: Episode, data: dict, language: str) -> Path:
    """Save the document next to the video."""
    out = ep.deliverable / f"transcript.{language}.md"
    out.parent.mkdir(parents=True, exist_ok=True)
    out.write_text(data.get("markdown", "").strip() + "\n")

    links = data.get("links") or []
    named = [x for x in links if x.get("name")]
    without_url = [x["name"] for x in named if not x.get("url")]
    log(f"transcript -> {out.name}  ({len(named)} projets mentionnés)")
    if without_url:
        # Said rather than hidden: the model was told to leave a URL empty rather than
        # invent one, and these are the ones to fill in by hand before publishing.
        log(f"  sans URL, à compléter : {', '.join(without_url)}")
    return out
