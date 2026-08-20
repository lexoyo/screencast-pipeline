"""Emit an editable Shotcut project alongside the rendered draft.

One track per shot type, on purpose. A Size/Position/Rotate filter sits on the track head,
so reframing the close-up means adjusting one filter rather than thirty clips — the wide
shot once, the close-up once, for the whole project.
"""

from __future__ import annotations

from .episode import Episode
from .shell import ffprobe_duration, log
from .sync import camera_offset
from .timecode import mlt_timecode as tc
from .timeline import Edl


def _entry(producer: str, start: float, end: float) -> str:
    return f'    <entry producer="{producer}" in="{tc(start)}" out="{tc(end)}"/>'


def _blank(duration: float) -> str:
    return f'    <blank length="{tc(duration)}"/>'


def _size_position(rect: str) -> str:
    return (
        '<filter><property name="mlt_service">qtblend</property>'
        f'<property name="rect">{rect}</property></filter>'
    )


def build(ep: Episode, plan: Edl) -> str:
    cfg = ep.cfg
    kept = plan.kept
    screen = ep.screen.resolve()
    face = ep.face.resolve()
    screen_dur = ffprobe_duration(screen)
    face_dur = ffprobe_duration(face)
    offset = camera_offset(ep)
    total = sum(seg.duration for seg in kept)

    full_frame = f"0 0 {cfg.out_w} {cfg.out_h} 1"
    zoom_x = -(cfg.zoom_scale - 1) / 2 * cfg.out_w
    zoom_y = -(cfg.zoom_scale - 1) / 2 * cfg.out_h
    zoom_rect = (
        f"{zoom_x:.0f} {zoom_y:.0f} "
        f"{cfg.zoom_scale * cfg.out_w:.0f} {cfg.zoom_scale * cfg.out_h:.0f} 1"
    )

    # Each track holds an entry where it is the active shot, and a blank everywhere else,
    # so the three tracks stay aligned on the same timeline.
    track_ecran: list[str] = []
    track_large: list[str] = []
    track_serre: list[str] = []
    track_audio: list[str] = []
    for seg in kept:
        cam_start = max(0.0, seg.start - offset)
        cam_end = seg.end - offset
        lead = max(0.0, offset - seg.start)
        face_clip = ([_blank(lead)] if lead > 0 else []) + [_entry("face_v", cam_start, cam_end)]

        track_ecran.append(
            _entry("screen_v", seg.start, seg.end) if seg.scene == "ecran" else _blank(seg.duration)
        )
        track_large.extend(face_clip if seg.scene == "large" else [_blank(seg.duration)])
        track_serre.extend(face_clip if seg.scene == "serre" else [_blank(seg.duration)])
        track_audio.append(_entry("screen_a", seg.start, seg.end))

    nl = "\n"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<mlt LC_NUMERIC="C" version="7.40.0" title="screencast">
  <profile description="HD 1080p {cfg.out_fps} fps" width="{cfg.out_w}" height="{cfg.out_h}" progressive="1"
    sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="16" display_aspect_den="9"
    frame_rate_num="{cfg.out_fps}" frame_rate_den="1" colorspace="709"/>
  <producer id="black" out="{tc(total)}"><property name="length">{tc(total)}</property><property name="mlt_service">color</property><property name="resource">0</property></producer>
  <chain id="screen_v" out="{tc(screen_dur)}"><property name="length">{tc(screen_dur)}</property><property name="resource">{screen}</property><property name="mlt_service">avformat-novalidate</property><property name="audio_index">-1</property></chain>
  <chain id="face_v" out="{tc(face_dur)}"><property name="length">{tc(face_dur)}</property><property name="resource">{face}</property><property name="mlt_service">avformat-novalidate</property><property name="audio_index">-1</property></chain>
  <chain id="screen_a" out="{tc(screen_dur)}"><property name="length">{tc(screen_dur)}</property><property name="resource">{screen}</property><property name="mlt_service">avformat-novalidate</property><property name="video_index">-1</property></chain>
  <playlist id="track_ecran">
{nl.join(track_ecran)}
  </playlist>
  <playlist id="track_large">
{nl.join(track_large)}
    {_size_position(full_frame)}
  </playlist>
  <playlist id="track_serre">
{nl.join(track_serre)}
    {_size_position(zoom_rect)}
  </playlist>
  <playlist id="track_audio">
{nl.join(track_audio)}
  </playlist>
  <tractor id="main">
    <track producer="black"/>
    <track producer="track_ecran"/>
    <track producer="track_large"/>
    <track producer="track_serre"/>
    <track producer="track_audio" hide="video"/>
    <transition mlt_service="frei0r.cairoblend"><property name="a_track">0</property><property name="b_track">1</property></transition>
    <transition mlt_service="frei0r.cairoblend"><property name="a_track">0</property><property name="b_track">2</property></transition>
    <transition mlt_service="frei0r.cairoblend"><property name="a_track">0</property><property name="b_track">3</property></transition>
    <transition mlt_service="mix"><property name="a_track">0</property><property name="b_track">4</property><property name="always_active">1</property><property name="sum">1</property></transition>
  </tractor>
</mlt>
"""


def run(ep: Episode, plan: Edl) -> None:
    log("emit Shotcut project")
    ep.project.write_text(build(ep, plan))
    log(f"project -> {ep.project}")
    log("  3 video tracks: ecran / large / serre (+ mic). Reframe once per track head")
    log("  with the 'Size Position Rotate' filter — serre already carries the zoom.")
