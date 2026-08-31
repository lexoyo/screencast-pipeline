"""Emit an editable Shotcut project alongside the rendered draft.

One track per shot type, on purpose. A Size/Position/Rotate filter sits on the track head,
so reframing the close-up means adjusting one filter rather than thirty clips — the wide
shot once, the close-up once, for the whole project.
"""

from __future__ import annotations

from pathlib import Path

from .episode import Episode
from .shell import ffprobe_duration, log, loudness_lufs
from .slideplan import SlidePlan
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


def _slide_producers(images: list[Path]) -> str:
    """One producer per slide image.

    `qimage` is MLT's still-image service and it honours the alpha channel, which is what
    lets an overlay sit on top of the picture in Shotcut exactly as it does in the export.
    This is the whole reason the slides are PNGs rather than an ffmpeg drawtext: a filter
    cannot be imported into a project, an image can.
    """
    return "\n".join(
        f'  <producer id="slide{index}" out="{tc(3600)}">'
        f'<property name="length">{tc(3600)}</property>'
        f'<property name="resource">{image}</property>'
        f'<property name="mlt_service">qimage</property></producer>'
        for index, image in enumerate(images)
    )


def _slide_track(entries: list[tuple[int, float, float]]) -> list[str]:
    """Lay slides on their own track, separated by blanks.

    Entries are (producer index, start, end) in FINAL seconds — the same numbers the
    renderer used, so the project and the export agree.
    """
    rows: list[str] = []
    cursor = 0.0
    for index, start, end in sorted(entries, key=lambda e: e[1]):
        if start > cursor:
            rows.append(_blank(start - cursor))
        rows.append(f'    <entry producer="slide{index}" in="{tc(0)}" out="{tc(end - start)}"/>')
        cursor = end
    return rows


def _music_producers(beds) -> str:
    """One producer per bed, audio only, each carrying its own level.

    Not one per file. Two beds can read the same track at very different levels — the
    music under a card sits at speech level, the bed under speech 18 dB below it — and in
    MLT a filter attaches to a producer, never to a playlist entry. One producer per bed is
    what lets each stretch keep the level the render gave it.
    """
    return "\n".join(
        f'  <producer id="music{index}" out="{tc(3600)}">'
        f'<property name="length">{tc(3600)}</property>'
        f'<property name="resource">{bed.track}</property>'
        f'<property name="mlt_service">avformat-novalidate</property>'
        f'<property name="video_index">-1</property>'
        f"{_volume_filter(bed.gain_db)}</producer>"
        for index, bed in enumerate(beds)
    )


def _music_track(beds) -> list[str]:
    """Music on its own playlist, so it can be levelled or muted without touching the voice.

    Each entry reads its own slice of its own track: `in`/`out` are positions INSIDE the
    music file, the blanks before them place it on the timeline. `beds` must already be in
    timeline order — the entry at position i refers to the producer built from bed i.
    """
    rows: list[str] = []
    cursor = 0.0
    for index, bed in enumerate(beds):
        if bed.start > cursor:
            rows.append(_blank(bed.start - cursor))
        rows.append(
            f'    <entry producer="music{index}" '
            f'in="{tc(bed.source_offset)}" out="{tc(bed.source_offset + bed.duration)}"/>'
        )
        cursor = bed.end
    return rows


def _volume_filter(db: float) -> str:
    """MLT wants decibels, and a bed's gain is already expressed in them.

    It used to convert from a linear level here, from a `Bed.volume` that stopped existing
    when levels moved to measured LUFS. The project silently kept the old call until a real
    episode with music hit it.
    """
    return (
        '<filter><property name="mlt_service">volume</property>'
        f'<property name="level">{db:.1f}</property></filter>'
    )


def build(ep: Episode, plan: Edl, layout: SlidePlan | None = None) -> str:
    cfg = ep.cfg
    kept = plan.kept
    screen = ep.screen.resolve()
    screen_dur = ffprobe_duration(screen)
    face = ep.face.resolve() if ep.has_face else None
    face_dur = ffprobe_duration(face) if face else screen_dur
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

    # An intro card pushes the body back. In the project that is a blank of the same
    # length on every existing track, so the body sits where the export puts it.
    # It is a LEADING blank only when the card opens the video; since the card now lands
    # after the spoken summary, the blank is inserted at that point instead — otherwise
    # the project drifts out of sync with final.mp4 by the length of the card.
    body_offset = layout.body_offset if layout else 0.0
    intro_card = next((c for c in layout.cards if c.kind == "intro"), None) if layout else None
    gap_after = intro_card.after_index if intro_card else None
    gap_length = intro_card.duration if intro_card else 0.0
    if body_offset > 0:
        for track in (track_ecran, track_large, track_serre, track_audio):
            track.append(_blank(body_offset))

    for index, seg in enumerate(kept):
        cam_start = max(0.0, seg.start - offset)
        cam_end = seg.end - offset
        lead = max(0.0, offset - seg.start)
        face_clip = ([_blank(lead)] if lead > 0 else []) + [_entry("face_v", cam_start, cam_end)]

        track_ecran.append(
            _entry("screen_v", seg.start, seg.end) if seg.scene == "ecran" else _blank(seg.duration)
        )
        # `face` is None on a screen-only shoot: the camera tracks stay in the project for
        # the track indexes below, but nothing may reference a producer that plays black —
        # a stale EDL would otherwise put ten seconds of black over the screen in Shotcut
        # while final.mp4 shows the screen.
        wide = face_clip if (face and seg.scene == "large") else [_blank(seg.duration)]
        close = face_clip if (face and seg.scene == "serre") else [_blank(seg.duration)]
        track_large.extend(wide)
        track_serre.extend(close)
        track_audio.append(_entry("screen_a", seg.start, seg.end))

        if gap_after is not None and index == gap_after:
            # The intro card plays here: the video tracks hold nothing, the card is on the
            # slide track and its music on the music track.
            for track in (track_ecran, track_large, track_serre, track_audio):
                track.append(_blank(gap_length))

    # --- slides: cards and overlays share one track, in final-timeline order
    slide_images: list[Path] = []
    slide_entries: list[tuple[int, float, float]] = []
    if layout:
        from . import compose

        cards, overlays = compose.render_all(ep, layout)
        for image, card in zip(cards, layout.cards, strict=True):
            slide_entries.append((len(slide_images), card.start, card.end))
            slide_images.append(image)
        for image, overlay in zip(overlays, layout.overlays, strict=True):
            slide_entries.append((len(slide_images), overlay.start, overlay.end))
            slide_images.append(image)

    # --- music: its own playlist, so it can be levelled or muted without touching the voice
    music_beds = []
    if layout and (layout.cards or layout.overlays):
        from . import music as music_mod

        found = sorted((ep.work / "music").glob("*/*.mp3"))
        by_kind = {path.parent.name: path for path in found}
        if by_kind:
            bed_dur = ffprobe_duration(by_kind["bed"]) if "bed" in by_kind else 0.0
            # Same measurement as the render: without it every bed would sit at 0 dB and
            # the project would not sound like the video it comes with.
            music_beds = music_mod.with_gains(
                music_mod.plan_beds(layout, by_kind, bed_dur),
                by_kind,
                cfg.audio_lufs,
                loudness_lufs,
            )
            music_beds.sort(key=lambda bed: bed.start)

    track_music = _music_track(music_beds) if music_beds else []
    music_producers = _music_producers(music_beds) if music_beds else ""
    music_playlist = (
        f'  <playlist id="track_music">\n{chr(10).join(track_music)}\n  </playlist>'
        if track_music
        else ""
    )
    music_track_ref = '    <track producer="track_music" hide="video"/>' if track_music else ""

    track_slides = _slide_track(slide_entries)
    slide_producers = _slide_producers(slide_images)
    slides_playlist = (
        f'  <playlist id="track_slides">\n{chr(10).join(track_slides)}\n  </playlist>'
        if track_slides
        else ""
    )
    slides_track_ref = '    <track producer="track_slides"/>' if track_slides else ""
    slides_transition = (
        '    <transition mlt_service="frei0r.cairoblend">'
        '<property name="a_track">0</property><property name="b_track">4</property>'
        "</transition>"
        if track_slides
        else ""
    )

    # The wide and close-up tracks stay in the project even when there is no camera: they
    # are empty, and keeping them means the track indexes in the transitions below are the
    # same in both cases. Their producer then has to resolve to something — a black colour
    # clip rather than a path to a file that is not there, which Shotcut would refuse to
    # open.
    face_producer = (
        f'<chain id="face_v" out="{tc(face_dur)}"><property name="length">{tc(face_dur)}</property>'
        f'<property name="resource">{face}</property>'
        '<property name="mlt_service">avformat-novalidate</property>'
        '<property name="audio_index">-1</property></chain>'
        if face
        else f'<producer id="face_v" out="{tc(face_dur)}"><property name="length">{tc(face_dur)}</property>'
        '<property name="mlt_service">color</property><property name="resource">0</property></producer>'
    )

    nl = "\n"
    return f"""<?xml version="1.0" encoding="utf-8"?>
<mlt LC_NUMERIC="C" version="7.40.0" title="screencast">
  <profile description="HD 1080p {cfg.out_fps} fps" width="{cfg.out_w}" height="{cfg.out_h}" progressive="1"
    sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="16" display_aspect_den="9"
    frame_rate_num="{cfg.out_fps}" frame_rate_den="1" colorspace="709"/>
  <producer id="black" out="{tc(total)}"><property name="length">{tc(total)}</property><property name="mlt_service">color</property><property name="resource">0</property></producer>
  <chain id="screen_v" out="{tc(screen_dur)}"><property name="length">{tc(screen_dur)}</property><property name="resource">{screen}</property><property name="mlt_service">avformat-novalidate</property><property name="audio_index">-1</property></chain>
  {face_producer}
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
{slide_producers}
{music_producers}
  <playlist id="track_audio">
{nl.join(track_audio)}
  </playlist>
{slides_playlist}
{music_playlist}
  <tractor id="main">
    <track producer="black"/>
    <track producer="track_ecran"/>
    <track producer="track_large"/>
    <track producer="track_serre"/>
{slides_track_ref}
    <track producer="track_audio" hide="video"/>
{music_track_ref}
    <transition mlt_service="frei0r.cairoblend"><property name="a_track">0</property><property name="b_track">1</property></transition>
    <transition mlt_service="frei0r.cairoblend"><property name="a_track">0</property><property name="b_track">2</property></transition>
    <transition mlt_service="frei0r.cairoblend"><property name="a_track">0</property><property name="b_track">3</property></transition>
{slides_transition}
    <transition mlt_service="mix"><property name="a_track">0</property><property name="b_track">{5 if track_slides else 4}</property><property name="always_active">1</property><property name="sum">1</property></transition>
{f'    <transition mlt_service="mix"><property name="a_track">0</property><property name="b_track">{(6 if track_slides else 5)}</property><property name="always_active">1</property><property name="sum">1</property></transition>' if track_music else ""}
  </tractor>
</mlt>
"""


def run(ep: Episode, plan: Edl, layout: SlidePlan | None = None) -> None:
    log("emit Shotcut project")
    ep.project.write_text(build(ep, plan, layout))
    log(f"project -> {ep.project}")
    log("  3 video tracks: ecran / large / serre, plus slides, mic and music on their own")
    log("  with the 'Size Position Rotate' filter — serre already carries the zoom.")
