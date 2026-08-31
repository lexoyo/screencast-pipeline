"""Proof-read the copy before it is published. Nothing here uploads anything.

Two passes, because they catch different things.

**Mechanical checks** are the platform's own rules — a title over 100 characters, a chapter
list YouTube will silently ignore, tags past the 500-character budget. These are exact, so
a script does them: a model asked to count characters will guess, and be wrong politely.

**An editorial pass** is a separate `claude -p` process reading the copy as a viewer would.
Separate on purpose (media-agent rule #2): the metadata was written by a model, and a model
proof-reading its own output agrees with itself. A different process, given only the copy
and no memory of writing it, disagrees when there is something to disagree with.

A failing check never blocks anything. It reports, and Alex decides — that call is his.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from pathlib import Path

from . import lang
from .parsing import extract_json_object, strip_code_fences

# `run` is this module's stage function, so the shell one is renamed on import
from .shell import brain, log
from .timecode import youtube_timecode

# YouTube's own limits, as the upload form enforces them.
TITLE_MAX = 100
DESCRIPTION_MAX = 5000
TAGS_MAX = 500
CHAPTER_MIN_COUNT = 3
CHAPTER_MIN_SECONDS = 10


@dataclass(frozen=True)
class Issue:
    severity: str  # "bloquant" | "à revoir" | "remarque"
    where: str
    what: str
    fix: str = ""


def check_title(title: str) -> list[Issue]:
    issues = []
    if not title.strip():
        issues.append(Issue("bloquant", "titre", "vide"))
    elif len(title) > TITLE_MAX:
        issues.append(Issue(
            "bloquant", "titre", f"{len(title)} caractères, le maximum est {TITLE_MAX}",
            "YouTube refuse l'envoi tel quel",
        ))
    elif len(title) > 70:
        issues.append(Issue(
            "remarque", "titre", f"{len(title)} caractères",
            "au-delà de ~70 il est coupé dans les résultats de recherche",
        ))
    return issues


def check_description(description: str) -> list[Issue]:
    if len(description) > DESCRIPTION_MAX:
        return [Issue(
            "bloquant", "description",
            f"{len(description)} caractères, le maximum est {DESCRIPTION_MAX}",
        )]
    if not description.strip():
        return [Issue("à revoir", "description", "vide")]
    return []


def check_tags(tags: list[str]) -> list[Issue]:
    total = len(", ".join(tags))
    if total > TAGS_MAX:
        return [Issue(
            "bloquant", "tags", f"{total} caractères au total, le maximum est {TAGS_MAX}",
            "les derniers seront perdus",
        )]
    return []


def check_chapters(rows: list[tuple[float, str]], duration: float = 0.0) -> list[Issue]:
    """The rules YouTube applies silently: break one and the whole list disappears."""
    issues: list[Issue] = []
    if not rows:
        return [Issue("à revoir", "chapitres", "aucun chapitre")]
    if rows[0][0] != 0:
        issues.append(Issue(
            "bloquant", "chapitres", f"le premier est à {youtube_timecode(rows[0][0])}, pas à 0:00",
            "sans un chapitre à 0:00 YouTube ignore toute la liste",
        ))
    if len(rows) < CHAPTER_MIN_COUNT:
        issues.append(Issue(
            "bloquant", "chapitres", f"{len(rows)} chapitres, il en faut au moins {CHAPTER_MIN_COUNT}",
            "en dessous, la liste n'est pas affichée",
        ))
    for (at, label), (next_at, _) in zip(rows, rows[1:], strict=False):
        if next_at - at < CHAPTER_MIN_SECONDS:
            issues.append(Issue(
                "bloquant", "chapitres",
                f"« {label} » dure {next_at - at:.0f}s, le minimum est {CHAPTER_MIN_SECONDS}s",
            ))
    if duration and rows[-1][0] >= duration:
        issues.append(Issue(
            "bloquant", "chapitres",
            f"« {rows[-1][1]} » commence à {youtube_timecode(rows[-1][0])}, après la fin",
        ))
    for at, label in rows:
        if not label.strip():
            issues.append(Issue("à revoir", "chapitres", f"libellé vide à {youtube_timecode(at)}"))
    return issues


def check_links(links: list[dict]) -> list[Issue]:
    missing = [x.get("name", "?") for x in links if x.get("name") and not x.get("url")]
    if missing:
        return [Issue(
            "à revoir", "liens", f"sans URL : {', '.join(missing)}",
            "à compléter à la main, ou à retirer de la description",
        )]
    return []


def mechanical(title: str, description: str, tags: list[str],
               rows: list[tuple[float, str]], links: list[dict],
               duration: float = 0.0) -> list[Issue]:
    """Every exact check, in one call."""
    return [
        *check_title(title),
        *check_description(description),
        *check_tags(tags),
        *check_chapters(rows, duration),
        *check_links(links),
    ]


def editorial(claude_bin: str, prompts_dir: Path, payload: dict, work: Path) -> list[Issue]:
    """A separate process reads the copy. Never this one — that is the point."""
    prompt = (prompts_dir / "qc.md").read_text()
    full = f"{prompt}\n\n## DATA\n{json.dumps(payload, ensure_ascii=False)}"
    (work / "qc_prompt.txt").write_text(full)
    try:
        answer = brain(claude_bin, full, work, "qc")
        (work / "qc_raw.txt").write_text(answer)
        data = json.loads(extract_json_object(strip_code_fences(answer)))
    except Exception as exc:  # noqa: BLE001 — no review must not cost the deliverable
        log(f"⚠ QC éditorial indisponible: {exc}")
        return []
    return [
        Issue(
            severity=item.get("severity", "remarque"),
            where=item.get("where", "?"),
            what=item.get("what", ""),
            fix=item.get("fix", ""),
        )
        for item in (data.get("issues") or [])
    ]


ORDER = {"bloquant": 0, "à revoir": 1, "remarque": 2}


def report(issues: list[Issue], title: str) -> str:
    """The QC note that ships with the deliverable."""
    lines = [f"# QC — {title}", ""]
    if not issues:
        lines += ["Rien à signaler : limites YouTube respectées, relecture éditoriale sans remarque.", ""]
        return "\n".join(lines)

    counts = {level: sum(1 for i in issues if i.severity == level) for level in ORDER}
    summary = ", ".join(f"{n} {level}" for level, n in counts.items() if n)
    lines += [f"{len(issues)} point(s) : {summary}.", ""]
    for level in ORDER:
        found = [i for i in issues if i.severity == level]
        if not found:
            continue
        lines += [f"## {level.capitalize()}", ""]
        for issue in found:
            lines.append(f"- **{issue.where}** — {issue.what}")
            if issue.fix:
                lines.append(f"  - {issue.fix}")
        lines.append("")
    return "\n".join(lines)


def blocking(issues: list[Issue]) -> list[Issue]:
    return [i for i in issues if i.severity == "bloquant"]


TRANSCRIPT_BUDGET = 40_000


def run(ep, plan, prompts_dir: Path) -> None:
    """The last stage: proof-read what will be public, write the note, say what it found."""
    from .publish import chapter_rows
    from .shell import ffprobe_duration
    from .timeline import load_kept

    deliverable = ep.deliverable
    if not deliverable.is_dir():
        log("⚠ QC: pas de livrable à relire")
        return

    meta = plan.metadata
    rows = chapter_rows(plan, load_kept(ep.kept))
    links_file = ep.work / "links.json"
    links = json.loads(links_file.read_text()) if links_file.is_file() else []
    duration = ffprobe_duration(deliverable / "final.mp4")

    issues = mechanical(meta.title, meta.description, list(meta.tags), rows, links, duration)

    spoken = lang.resolve(ep.language(), plan.language)
    translated_file = ep.work / f"meta_{lang.target(spoken)}.json"
    transcripts = sorted(deliverable.glob("transcript.*.md"))
    excerpt = transcripts[0].read_text()[:TRANSCRIPT_BUDGET] if transcripts else ""
    log("QC: relecture par un process séparé (règle #2)")
    issues += editorial(
        ep.cfg.claude_bin,
        prompts_dir,
        {
            "title": meta.title,
            "description": meta.description,
            "tags": list(meta.tags),
            "chapters": [{"at": youtube_timecode(at), "label": label} for at, label in rows],
            "translation": (
                json.loads(translated_file.read_text()) if translated_file.is_file() else None
            ),
            "transcript_excerpt": excerpt,
            "duration_seconds": round(duration),
        },
        ep.work,
    )

    (deliverable / "QC.md").write_text(report(issues, meta.title))
    stoppers = blocking(issues)
    if not issues:
        log("QC: rien à signaler")
    else:
        log(f"QC: {len(issues)} point(s), dont {len(stoppers)} bloquant(s) -> QC.md")
        for issue in issues[:8]:
            log(f"  {issue.severity:10s} {issue.where}: {issue.what}")
    if stoppers:
        log("  ⚠ à corriger avant de publier — rien n'est envoyé nulle part de toute façon")
