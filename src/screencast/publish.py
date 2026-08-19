"""Package the deliverable. Uploads nothing, ever.

This stage is gated by media-agent rule #1: pushing a video to YouTube or PeerTube is an
external action and needs Alex's explicit go-ahead each time. What it produces is a folder
where everything is ready and named so nothing has to be hunted for.
"""

from __future__ import annotations

from .episode import Episode
from .shell import log
from .timecode import remap_to_final, youtube_timecode
from .timeline import Edl, load_kept


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


def metadata_text(plan: Edl, rows: list[tuple[float, str]]) -> str:
    meta = plan.metadata
    lines = [
        meta.title,
        "",
        meta.description,
        "",
        "Tags: " + ", ".join(meta.tags),
        "",
        "Chapters:",
    ]
    lines += [f"{youtube_timecode(at)} {label}" for at, label in rows]
    return "\n".join(lines) + "\n"


def run(ep: Episode, plan: Edl) -> None:
    ep.need(ep.draft, "run the draft stage first")
    kept = load_kept(ep.kept)
    deliverable = ep.deliverable
    deliverable.mkdir(parents=True, exist_ok=True)

    rows = chapter_rows(plan, kept)
    (deliverable / "metadata.txt").write_text(metadata_text(plan, rows))

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

    log("-" * 65)
    log(f"LIVRABLE: {deliverable}")
    log("  final.mp4      vidéo montée HD")
    log("  final.*.srt    sous-titres (natif + traduction) — chargés seuls par VLC/mpv")
    log("  metadata.txt   titre / description / tags / chapitres")
    log("  project.mlt    projet Shotcut éditable (pointe vers les rushes du dossier parent)")
    log("Aucun upload — tu publies à la main. QC metadata par subagent (règle #2).")
