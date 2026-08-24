"""Package the deliverable. Uploads nothing, ever.

This stage is gated by media-agent rule #1: pushing a video to YouTube or PeerTube is an
external action and needs Alex's explicit go-ahead each time. What it produces is a folder
where everything is ready and named so nothing has to be hunted for.
"""

from __future__ import annotations

import json
from pathlib import Path

from . import upload
from .episode import Episode
from .parsing import extract_json_object, strip_code_fences

# `run` is this module's stage function, so the shell one is renamed on import
from .shell import log
from .shell import brain
from .timecode import remap_to_final, youtube_timecode
from .timeline import Edl, load_kept
from .transcript import links_section


def chapter_rows(plan: Edl, kept: list[dict]) -> list[tuple[float, str]]:
    """Chapter markers projected onto the edited timeline.

    The brain places them on SOURCE timestamps, and the cut removed time before most of
    them, so every marker has to move. YouTube also insists the list starts at 0:00 —
    without that first marker it ignores the whole set.
    """
    rows = [(remap_to_final(ch.at, kept), ch.label) for ch in plan.metadata.chapters]
    rows.sort(key=lambda row: row[0])
    if not rows or rows[0][0] >= 1:
        rows.insert(0, (0.0, "Intro"))
    return rows


def metadata_text(plan: Edl, rows: list[tuple[float, str]], links: list[dict] | None = None) -> str:
    meta = plan.metadata
    lines = [meta.title, "", meta.description, ""]
    block = links_section(links or [])
    if block:
        lines += [block, ""]
    lines += ["Tags: " + ", ".join(meta.tags), "", "Chapters:"]
    lines += [f"{youtube_timecode(at)} {label}" for at, label in rows]
    return "\n".join(lines) + "\n"


def translate_metadata(ep: Episode, prompts_dir: Path, plan: Edl,
                       rows: list[tuple[float, str]]) -> dict | None:
    """Title, description, tags and chapter labels in English.

    YouTube takes a translated title and description per language, and a viewer landing
    from an English search reads those rather than the subtitles. Cached in work/, because
    re-packaging a deliverable should not cost another model call — nor produce a second,
    slightly different translation of a video already published under the first.
    """
    cache = ep.work / "meta_en.json"
    if cache.is_file():
        return json.loads(cache.read_text())

    meta = plan.metadata
    payload = {
        "title": meta.title,
        "description": meta.description,
        "tags": list(meta.tags),
        "chapters": [label for _, label in rows],
    }
    prompt = (prompts_dir / "metadata-translate.md").read_text()
    full = f"{prompt}\n\n## DATA\n{json.dumps(payload, ensure_ascii=False)}"

    log("metadata: translate to English")
    try:
        answer = brain(ep.cfg.claude_bin, full, ep.work, "metadonnees-en")
        data = json.loads(extract_json_object(strip_code_fences(answer)))
    except Exception as exc:  # noqa: BLE001 — no English metadata must not cost the deliverable
        log(f"⚠ metadata EN skipped: {exc}")
        return None

    labels = data.get("chapters") or []
    if len(labels) != len(rows):
        # Chapters are matched to timestamps by position; a short list would shift them all.
        log(f"⚠ metadata EN: {len(labels)} chapitres traduits pour {len(rows)} — chapitres FR gardés")
        data["chapters"] = [label for _, label in rows]
    cache.write_text(json.dumps(data, ensure_ascii=False, indent=2))
    return data


def english_metadata_text(data: dict, rows: list[tuple[float, str]],
                          links: list[dict] | None = None) -> str:
    """The same file as metadata.txt, in English, so it can be pasted as-is."""
    lines = [data.get("title", ""), "", data.get("description", ""), ""]
    block = links_section(links or [], label="Projects mentioned")
    if block:
        lines += [block, ""]
    lines += ["Tags: " + ", ".join(data.get("tags") or []), "", "Chapters:"]
    lines += [
        f"{youtube_timecode(at)} {label}"
        for (at, _), label in zip(rows, data.get("chapters") or [], strict=False)
    ]
    return "\n".join(lines) + "\n"


def run(ep: Episode, plan: Edl, prompts_dir: Path | None = None) -> None:
    ep.need(ep.draft, "run the draft stage first")
    kept = load_kept(ep.kept)
    deliverable = ep.deliverable
    deliverable.mkdir(parents=True, exist_ok=True)

    rows = chapter_rows(plan, kept)
    links_file = ep.work / "links.json"
    links = json.loads(links_file.read_text()) if links_file.is_file() else []
    (deliverable / "metadata.txt").write_text(metadata_text(plan, rows, links))

    # The channel is FR first, EN second: the subtitles were already translated, and a
    # viewer arriving from an English search reads the title and description, not the srt.
    english = translate_metadata(ep, prompts_dir, plan, rows) if prompts_dir else None
    if english:
        (deliverable / "metadata.en.txt").write_text(english_metadata_text(english, rows, links))

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
            language=plan.language,
        )
    )

    log("-" * 65)
    log(f"LIVRABLE: {deliverable}")
    log("  final.mp4      vidéo montée HD")
    log("  final.*.srt    sous-titres (natif + traduction) — chargés seuls par VLC/mpv")
    log("  metadata.txt   titre / description / tags / chapitres")
    log("  metadata.en.txt  les mêmes, en anglais (YouTube les accepte par langue)")
    log("  project.mlt    projet Shotcut éditable (pointe vers les rushes du dossier parent)")
    log("  transcript.*.md  le transcript rédigé, liens vérifiés (fr + en)")
    log("  UPLOAD.md      la marche à suivre pour publier, pas à pas")
    log("Aucun upload — tu publies à la main. QC metadata par subagent (règle #2).")
