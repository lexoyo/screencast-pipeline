"""Package the deliverable. Uploads nothing, ever.

This stage is gated by media-agent rule #1: pushing a video to YouTube or PeerTube is an
external action and needs Alex's explicit go-ahead each time. What it produces is a folder
where everything is ready and named so nothing has to be hunted for.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import lang, upload
from .episode import Episode
from .parsing import extract_json_object, strip_code_fences

# `run` is this module's stage function, so the shell one is renamed on import
from .shell import brain, log
from .timecode import remap_to_final, youtube_timecode
from .timeline import Edl, load_kept
from .transcript import links_section

FALLBACK_SPOKEN = lang.FALLBACK


def chapter_rows(plan: Edl, kept: list[dict], layout=None) -> list[tuple[float, str]]:
    """Chapter markers projected onto the edited timeline.

    The brain places them on SOURCE timestamps, and the cut removed time before most of
    them, so every marker has to move. YouTube also insists the list starts at 0:00 —
    without that first marker it ignores the whole set.
    """
    # remap_to_final answers "where in the CUT body", the layout answers "and where once
    # the cards are in". Without the second, every chapter after the intro card is early by
    # its length, and the timestamps in the description miss the sentence they name.
    def place(at: float) -> float:
        body = remap_to_final(at, kept)
        return layout.chapter_time(body) if layout else body

    rows = [(place(ch.at), ch.label) for ch in plan.metadata.chapters]
    rows.sort(key=lambda row: row[0])
    if not rows or rows[0][0] >= 1:
        rows.insert(0, (0.0, "Intro"))
    return rows


def metadata_text(plan: Edl, rows: list[tuple[float, str]], links: list[dict] | None = None,
                  spoken: str = FALLBACK_SPOKEN) -> str:
    meta = plan.metadata
    lines = [meta.title, "", meta.description, ""]
    block = links_section(links or [], label=lang.links_label(spoken))
    if block:
        lines += [block, ""]
    lines += ["Tags: " + ", ".join(meta.tags), "", "Chapters:"]
    lines += [f"{youtube_timecode(at)} {label}" for at, label in rows]
    return "\n".join(lines) + "\n"


def translate_metadata(ep: Episode, prompts_dir: Path, plan: Edl,
                       rows: list[tuple[float, str]], target: str) -> dict | None:
    """Title, description, tags and chapter labels in the deliverable's other language.

    YouTube and PeerTube both take a translated title and description per language, and a
    viewer landing from a search in that language reads those rather than the subtitles.
    Cached in work/, because re-packaging a deliverable should not cost another model call
    — nor produce a second, slightly different translation of a video already published
    under the first.
    """
    cache = ep.work / f"meta_{target}.json"
    if cache.is_file():
        return json.loads(cache.read_text())

    meta = plan.metadata
    payload = {
        "title": meta.title,
        "description": meta.description,
        "tags": list(meta.tags),
        "chapters": [label for _, label in rows],
    }
    prompt = (prompts_dir / "metadata-translate.md").read_text().replace("{DST}", lang.name(target))
    full = f"{prompt}\n\n## DATA\n{json.dumps(payload, ensure_ascii=False)}"

    log(f"metadata: translate to {lang.name(target)}")
    try:
        answer = brain(ep.cfg.claude_bin, full, ep.work, f"metadonnees-{target}")
        data = json.loads(extract_json_object(strip_code_fences(answer)))
    except Exception as exc:  # noqa: BLE001 — a missing translation must not cost the deliverable
        log(f"⚠ metadata {target.upper()} skipped: {exc}")
        return None

    labels = data.get("chapters") or []
    if len(labels) != len(rows):
        # Chapters are matched to timestamps by position; a short list would shift them all.
        log(f"⚠ metadata {target.upper()}: {len(labels)} chapitres traduits pour "
            f"{len(rows)} — chapitres d'origine gardés")
        data["chapters"] = [label for _, label in rows]
    cache.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return data


def translated_metadata_text(data: dict, rows: list[tuple[float, str]],
                             links: list[dict] | None = None, target: str = "en") -> str:
    """The same file as metadata.txt, translated, so it can be pasted as-is."""
    lines = [data.get("title", ""), "", data.get("description", ""), ""]
    block = links_section(links or [], label=lang.links_label(target))
    if block:
        lines += [block, ""]
    lines += ["Tags: " + ", ".join(data.get("tags") or []), "", "Chapters:"]
    lines += [
        f"{youtube_timecode(at)} {label}"
        for (at, _), label in zip(rows, data.get("chapters") or [], strict=False)
    ]
    return "\n".join(lines) + "\n"


def run(ep: Episode, plan: Edl, prompts_dir: Path | None = None, layout=None) -> None:
    ep.need(ep.draft, "run the draft stage first")
    kept = load_kept(ep.kept)
    deliverable = ep.deliverable
    deliverable.mkdir(parents=True, exist_ok=True)

    rows = chapter_rows(plan, kept, layout)
    links_file = ep.work / "links.json"
    links = json.loads(links_file.read_text()) if links_file.is_file() else []
    # What was actually spoken, according to the harness rather than the montage model.
    spoken = lang.resolve(ep.language(), plan.language)
    (deliverable / "metadata.txt").write_text(metadata_text(plan, rows, links, spoken))

    # Two languages per deliverable, the spoken one and its translation: the subtitles were
    # already translated, and a viewer arriving from a search in the other language reads
    # the title and description, not the srt. Which language that is depends on the video —
    # the personal channel shoots FR, the Silex docs shoot EN.
    target = lang.target(spoken)
    # A previous run may have shipped the other pair (--lang is meant to change between
    # runs on the same episode): a stale metadata.<lang>.txt would otherwise stay in the
    # deliverable and be the one UPLOAD.md points at.
    for stale in deliverable.glob("metadata.*.txt"):
        if stale.name != f"metadata.{target}.txt":
            stale.unlink()
    translated = translate_metadata(ep, prompts_dir, plan, rows, target) if prompts_dir else None
    translated_name = ""
    if translated:
        translated_name = f"metadata.{target}.txt"
        (deliverable / translated_name).write_text(
            translated_metadata_text(translated, rows, links, target)
        )

    for document in sorted(ep.deliverable.glob("transcript.*.md")):
        document.touch()  # already written by the subtitles stage; kept in the deliverable

    (deliverable / "final.mp4").write_bytes(ep.draft.read_bytes())

    # Sidecar naming: VLC and mpv load a subtitle named after the video file on their own,
    # so they ship as final.<lang>.srt rather than in a subs/ subfolder. YouTube never
    # looks at the filename — you pick the language when uploading — so this costs nothing
    # on the platform side and saves a step on every local playback.
    for existing in deliverable.glob("final.*.srt"):
        existing.unlink()
    for srt in sorted(ep.subs_dir.glob("*.srt")):
        (deliverable / f"final.{srt.name}").write_text(srt.read_text())

    if ep.project.is_file():
        (deliverable / "project.mlt").write_text(ep.project.read_text())

    (deliverable / "UPLOAD.md").write_text(
        upload.build(
            deliverable,
            title=plan.metadata.title,
            chapters=[(youtube_timecode(at), label) for at, label in rows],
            language=spoken,
            translated=translated_name,
        )
    )

    log("-" * 65)
    log(f"LIVRABLE: {deliverable}")
    log("  final.mp4      vidéo montée HD")
    log("  final.*.srt    sous-titres (natif + traduction) — chargés seuls par VLC/mpv")
    log("  metadata.txt   titre / description / tags / chapitres")
    if translated_name:
        log(f"  {translated_name}  les mêmes, traduits (YouTube et PeerTube les acceptent par langue)")
    log("  project.mlt    projet Shotcut éditable (pointe vers les rushes du dossier parent)")
    log("  transcript.*.md  le transcript rédigé, liens vérifiés (fr + en)")
    log("  UPLOAD.md      la marche à suivre pour publier, pas à pas")
    log("Aucun upload — tu publies à la main. QC metadata par subagent (règle #2).")
