"""Render the edited video with ffmpeg, one segment at a time then concatenated.

Segment-by-segment rather than one giant filtergraph: a four-minute rush produces around
thirty segments, and a single graph that long is both unreadable and impossible to debug
when one clip is wrong. Rendering them separately also means a failure names the segment.
"""

from __future__ import annotations

import json

from .episode import Episode
from .layout import escape_filter_path, wrap
from .shell import ffmpeg, log
from .sync import camera_offset
from .timeline import Edl, KeptSegment, ListItem


def list_card_filter(item: ListItem, ep: Episode, index: int) -> str:
    """Blur the shot, dim it, and stamp the number huge with its label underneath.

    The label goes through a FILE, never through `text=`: an apostrophe or a colon in a
    French sentence breaks the filtergraph, and both are everywhere in spoken French.
    """
    cfg = ep.cfg
    if not item or (not item.n and not item.label):
        return ""

    alpha = f":alpha='min(1,t/{cfg.list_fade})'" if cfg.list_fade > 0 else ""
    parts = [f",gblur=sigma={cfg.list_blur},eq=brightness={cfg.list_darken}:saturation=0.55"]

    if item.n:
        number = f"{int(item.n):02d}." if item.n.isdigit() else item.n
        parts.append(
            f",drawtext=fontfile={cfg.list_font}:text='{number}':fontcolor=white"
            f":fontsize={int(cfg.out_h * 0.176)}:x=(w-text_w)/2:y={int(cfg.out_h * 0.23)}{alpha}"
        )
    if item.label:
        label_file = ep.segdir / f"label{index:04d}.txt"
        label_file.write_text("\n".join(wrap(item.label)) + "\n")
        parts.append(
            f",drawtext=fontfile={cfg.list_font}:textfile={escape_filter_path(str(label_file))}"
            f":text_align=T+C:fontcolor=white:fontsize={int(cfg.out_h * 0.076)}"
            f":line_spacing={int(cfg.out_h * 0.017)}"
            f":x=(w-text_w)/2:y={int(cfg.out_h * 0.433)}{alpha}"
        )
    return "".join(parts)


def _segment_graph(ep: Episode, seg: KeptSegment, index: int, params: dict, offset: float) -> str:
    """The filtergraph for one segment: pick the source, correct it, frame it."""
    cfg = ep.cfg
    fill = f"scale={cfg.out_w}:{cfg.out_h}:force_original_aspect_ratio=increase,crop={cfg.out_w}:{cfg.out_h}"
    mic = "0:a" if not cfg.mic_from_face else "1:a"
    card = list_card_filter(seg.list_item, ep, index) if seg.list_item else ""
    audio = f"[{mic}]atrim={seg.start}:{seg.end},asetpts=PTS-STARTPTS,{params['audio_filter']}[a]"

    if seg.scene == "ecran":
        # screen.mkv already carries the webcam in a corner, baked in by OBS
        video = (
            f"[0:v]trim={seg.start}:{seg.end},setpts=PTS-STARTPTS,{fill}{card},fps={cfg.out_fps}[v]"
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
        f"{fill}{zoom}{tpad}{card},fps={cfg.out_fps}[v]"
    )
    return f"{video};{audio}"


def run(ep: Episode, plan: Edl) -> None:
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

    ep.concat_list.write_text("\n".join(parts) + "\n")
    ffmpeg(
        [
            "-f",
            "concat",
            "-safe",
            "0",
            "-i",
            ep.concat_list,
            "-c",
            "copy",
            "-movflags",
            "+faststart",
            ep.draft,
        ]
    )
    log(f"draft -> {ep.draft}")
