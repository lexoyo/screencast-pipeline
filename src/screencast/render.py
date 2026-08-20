"""Render the edited video with ffmpeg, one segment at a time then concatenated.

Segment-by-segment rather than one giant filtergraph: a four-minute rush produces around
thirty segments, and a single graph that long is both unreadable and impossible to debug
when one clip is wrong. Rendering them separately also means a failure names the segment.
"""

from __future__ import annotations

import json

from . import compose
from .episode import Episode
from .shell import ffmpeg, log
from .slideplan import SlidePlan
from .sync import camera_offset
from .timeline import Edl, KeptSegment


def _segment_graph(ep: Episode, seg: KeptSegment, index: int, params: dict, offset: float) -> str:
    """The filtergraph for one segment: pick the source, correct it, frame it."""
    cfg = ep.cfg
    fill = f"scale={cfg.out_w}:{cfg.out_h}:force_original_aspect_ratio=increase,crop={cfg.out_w}:{cfg.out_h}"
    mic = "0:a" if not cfg.mic_from_face else "1:a"
    audio = f"[{mic}]atrim={seg.start}:{seg.end},asetpts=PTS-STARTPTS,{params['audio_filter']}[a]"

    if seg.scene == "ecran":
        # screen.mkv already carries the webcam in a corner, baked in by OBS
        video = (
            f"[0:v]trim={seg.start}:{seg.end},setpts=PTS-STARTPTS,{fill},fps={cfg.out_fps}[v]"
        )
        return f"{video};{audio}"

    # large / serre come from the camera file, shifted by the startup offset
    cam_start = seg.start - offset
    lead = -cam_start if cam_start < 0 else 0.0
    cam_start = max(0.0, cam_start)
    cam_end = seg.end - offset
    zoom = (
        f",crop={cfg.out_w}/{cfg.zoom_scale}:{cfg.out_h}/{cfg.zoom_scale}"
        f",scale={cfg.out_w}:{cfg.out_h}"
        if seg.scene == "serre"
        else ""
    )
    # Opening words: the camera wasn't recording yet, so freeze its first frame for the
    # lead-in rather than dropping the audio — the greeting is never sacrificed.
    tpad = f",tpad=start_duration={lead}:start_mode=clone" if lead > 0 else ""
    video = (
        f"[1:v]trim={cam_start}:{cam_end},setpts=PTS-STARTPTS,{params['video_filter']},"
        f"{fill}{zoom}{tpad},fps={cfg.out_fps}[v]"
    )
    return f"{video};{audio}"


def run(ep: Episode, plan: Edl, layout: SlidePlan | None = None) -> None:
    cfg = ep.cfg
    ep.need(ep.screen, "the screen rush")
    ep.need(ep.face, "the clean webcam rush")
    kept = plan.kept
    if not kept:
        raise ValueError("the EDL keeps no segments — nothing to render")

    params = json.loads(ep.params.read_text())
    ep.segdir.mkdir(parents=True, exist_ok=True)
    offset = camera_offset(ep)

    parts: list[str] = []
    for index, seg in enumerate(kept):
        out = ep.segdir / f"seg{index:04d}.mp4"
        log(f"  seg {index + 1}/{len(kept)}  {seg.scene}  {seg.start:.2f}-{seg.end:.2f}s")
        ffmpeg(
            [
                "-i",
                ep.screen,
                "-i",
                ep.face,
                "-filter_complex",
                _segment_graph(ep, seg, index, params, offset),
                "-map",
                "[v]",
                "-map",
                "[a]",
                "-c:v",
                "libx264",
                "-preset",
                "veryfast",
                "-crf",
                str(cfg.draft_crf),
                "-pix_fmt",
                "yuv420p",
                "-r",
                str(cfg.out_fps),
                "-c:a",
                "aac",
                "-b:a",
                "192k",
                "-ar",
                "48000",
                "-ac",
                "2",
                out,
            ]
        )
        parts.append(f"file '{out.as_posix()}'")

    # Cards bracket the body: intro first, outro last. They are segments like any other,
    # which is why they lengthen the video where an overlay does not.
    if layout:
        ep.slidedir.mkdir(parents=True, exist_ok=True)
        intro = [c for c in layout.cards if c.kind == "intro"]
        outro = [c for c in layout.cards if c.kind != "intro"]
        # The card index is its position in layout.cards, never its position in the
        # timeline: the two disagreed and the outro was rendered twice, once as card01 and
        # once as card28, from the same values.
        for card in intro:
            path = compose.render_card(ep, card, layout.cards.index(card))
            log(f"  card {card.kind} ({card.duration:.0f}s)")
            parts.insert(0, f"file '{path.as_posix()}'")
        for card in outro:
            path = compose.render_card(ep, card, layout.cards.index(card))
            log(f"  card {card.kind} ({card.duration:.0f}s)")
            parts.append(f"file '{path.as_posix()}'")

    ep.concat_list.write_text("\n".join(parts) + "\n")
    assembled = ep.work / "assembled.mp4" if layout and layout.overlays else ep.draft
    ffmpeg(
        [
            "-f", "concat", "-safe", "0", "-i", ep.concat_list,
            "-c", "copy", "-movflags", "+faststart", assembled,
        ]
    )
    if layout and layout.overlays:
        compose.apply_overlays(ep, assembled, layout, ep.draft)

    # Music last, on the finished picture: it is copied through, so a music failure never
    # costs a re-encode of the video.
    if layout and (layout.cards or layout.overlays):
        with_music = ep.work / "with_music.mp4"
        compose.apply_music(ep, ep.draft, layout, plan.metadata, with_music)
        if with_music.is_file():
            ep.draft.unlink(missing_ok=True)
            with_music.rename(ep.draft)
    log(f"draft -> {ep.draft}")
