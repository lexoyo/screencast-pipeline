"""The Shotcut project: the edit itself, and what melt-7 plays to render the video.

One track per shot type, on purpose. A Size/Position/Rotate filter sits on the track head,
so reframing the close-up means adjusting one filter rather than thirty clips — the wide
shot once, the close-up once, for the whole project. The camera correction measured by the
`measure` stage sits there too, for the same reason.

The video used to be rendered by ffmpeg, with the project a sketch beside it: same cuts, but
none of the corrections, no fades, no blur behind the list cards. Opening it in Shotcut
showed a different video from final.mp4. The project now carries all of it and IS the
render — one description of the edit, so the two cannot disagree. Compared on a 21-minute
episode, the ffmpeg concatenation also drifted half a second by the end; melt does not.

Everything is laid out in FRAMES, not seconds. MLT reads a playlist entry's `out` as the
last frame played, inclusive: writing the end time there made every entry one frame too
long, and thirty entries drifted a second against the export.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from math import gcd
from pathlib import Path
from xml.sax.saxutils import escape

from .episode import Episode
from .shell import ffprobe_dimensions, ffprobe_duration, log, loudness_lufs
from .shell import run as run_tool
from .slideplan import SlidePlan
from .sync import camera_offset
from .timecode import mlt_timecode
from .timeline import Edl

# The overlays fade in and out over this long, like compose.overlay_graph's default.
OVERLAY_FADE = 0.25


def display_aspect(width: int, height: int) -> tuple[int, int]:
    """The frame's aspect as MLT wants it, reduced.

    It used to be written 16:9 whatever the frame was. A 16:10 project then opened in
    Shotcut with every clip squeezed sideways, because MLT believes the profile over the
    pixels.
    """
    divisor = gcd(width, height)
    return width // divisor, height // divisor


def cover_rect(source: tuple[int, int] | None, out_w: int, out_h: int,
               zoom: float = 1.0) -> str:
    """The qtblend rect that frames a source the way ffmpeg's `fill` filter does.

    qtblend has no aspect-preserving mode — it stretches whatever it is given into the
    rect. ffmpeg's `fill` instead scales the source up until it covers the frame and crops the
    overflow. Writing the frame itself as the rect therefore made the two disagree the day
    the camera stopped sharing the frame's aspect: Shotcut showed the speaker 11% wider
    than final.mp4 did. Enlarging the rect past the frame edges reproduces the crop, since
    what falls outside is not drawn.
    """
    if not source or source[0] <= 0 or source[1] <= 0:
        scale = zoom  # nothing measurable: the old behaviour, the frame itself
        width, height = out_w * scale, out_h * scale
    else:
        cover = max(out_w / source[0], out_h / source[1]) * zoom
        width, height = source[0] * cover, source[1] * cover
    return f"{(out_w - width) / 2:.0f} {(out_h - height) / 2:.0f} {width:.0f} {height:.0f} 1"


def cover_scale(source: tuple[int, int] | None, out_w: int, out_h: int,
                zoom: float = 1.0) -> float:
    """How many output pixels one source pixel becomes, once framed by cover_rect."""
    if not source or source[0] <= 0 or source[1] <= 0:
        return zoom
    return max(out_w / source[0], out_h / source[1]) * zoom


# ---------------------------------------------------------------------------- filters


def _prop(name: str, value) -> str:
    return f'<property name="{name}">{escape(str(value))}</property>'


def _filter(service: str, props: dict[str, object] | None = None) -> str:
    body = "".join(_prop(k, v) for k, v in (props or {}).items())
    return f'<filter>{_prop("mlt_service", service)}{body}</filter>'


def _size_position(rect: str) -> str:
    return _filter("qtblend", {"rect": rect})


# ffmpeg lets some filters take their options by position. MLT's avfilter bridge only
# knows them by name (`av.<option>`), so the positions are named here — only for the
# filters the pipeline actually writes positionally.
POSITIONAL = {
    "unsharp": ("luma_msize_x", "luma_msize_y", "luma_amount",
                "chroma_msize_x", "chroma_msize_y", "chroma_amount"),
    "highpass": ("f",),
}


def parse_chain(chain: str) -> list[tuple[str, dict[str, str]]]:
    """An ffmpeg filter chain -> [(filter, {option: value})].

    Only the plain `a=b:c=d,e=f` shape measure.py writes: no quoting, no labels. That is
    enough to carry params.json into the project, and anything fancier there would have
    to be taught to this function on purpose.
    """
    out: list[tuple[str, dict[str, str]]] = []
    for part in filter(None, (p.strip() for p in chain.split(","))):
        name, _, args = part.partition("=")
        options: dict[str, str] = {}
        names = POSITIONAL.get(name, ())
        for index, arg in enumerate(filter(None, args.split(":"))):
            key, sep, value = arg.partition("=")
            if sep:
                options[key] = value
            elif index < len(names):
                options[names[index]] = key
            else:
                raise ValueError(f"cannot name positional option {index} of {name!r}")
        out.append((name, options))
    return out


def av_filters(chain: str) -> list[str]:
    """ffmpeg filters as MLT avfilter.* services, options unchanged.

    The correction is measured with ffmpeg and runs as the same libavfilter code in MLT, so
    it applies identically — and Shotcut keeps the filters it has no panel for.
    """
    return [
        _filter(f"avfilter.{name}", {f"av.{k}": v for k, v in options.items()})
        for name, options in parse_chain(chain)
    ]


def audio_filters(chain: str) -> list[str]:
    """The voice chain of params.json, with loudnorm translated.

    avfilter.loudnorm is accepted by MLT and does NOTHING: measured on this rush, the
    level came out of melt exactly as it went in, -18.9 LUFS with 0 dBFS peaks, where
    ffmpeg gave -15.9 and -1.5. Its 192 kHz internal resampling does not survive MLT's
    frame-sized audio blocks. So it is rebuilt from MLT's own services:

    - when loudnorm could stay linear (the measured peak, once raised, still fits under
      the ceiling), it is a constant gain — `volume` with the gain loudnorm would apply;
    - otherwise ffmpeg itself falls back to dynamic normalisation, and so does this:
      `dynamic_loudness`, Shotcut's "Normalize: One Pass", aiming at the same target.

    The window is 10 s, not the 3 s default. Measured on the first five minutes of the
    2026-09-23 take against the ffmpeg render (-16.0 LUFS, LRA 5.9): 3 s pumps the pauses
    up and lands at -15.2 LUFS; 10 s gives -15.9, LRA 6.6. A plain constant gain gave
    -16.6 and LRA 7.4 — ffmpeg's dynamic mode compresses, and a gain does not.

    Either way an `alimiter` at the true-peak ceiling follows, standing in for the one
    built into loudnorm.
    """
    out: list[str] = []
    for name, options in parse_chain(chain):
        if name != "loudnorm":
            out.append(_filter(f"avfilter.{name}", {f"av.{k}": v for k, v in options.items()}))
            continue
        target = float(options.get("I", -16))
        ceiling = float(options.get("TP", -1.5))
        measured_i = options.get("measured_I")
        measured_tp = options.get("measured_TP")
        linear = options.get("linear", "true") in ("true", "1")
        gain = target - float(measured_i) if measured_i is not None else None
        if linear and gain is not None and measured_tp is not None \
                and float(measured_tp) + gain <= ceiling:
            out.append(_filter("volume", {"level": f"{gain:.2f}"}))
        else:
            out.append(_filter("dynamic_loudness", {"target_loudness": target, "window": 10}))
        out.append(_filter("avfilter.alimiter", {
            "av.limit": f"{10 ** (ceiling / 20):.4f}",
            "av.level": 0,  # no auto-level: the limiter only catches peaks
        }))
    return out


def _list_filters(blur_px: float) -> list[str]:
    """What a list card does to the picture behind it — compose.overlay_graph's blur+dim.

    Applied to the clip rather than on top of the composite, because a filter in MLT
    belongs to a producer. The blur therefore runs on the source, before the framing
    scales it: `blur_px` is the output-pixel sigma divided by that scale, so the blur
    looks the same size as in the export.
    """
    from .compose import LIST_BLUR, LIST_DARKEN, LIST_DESATURATE

    return [
        _filter("avfilter.gblur", {"av.sigma": f"{LIST_BLUR / blur_px:.2f}"}),
        _filter("avfilter.eq", {"av.brightness": LIST_DARKEN,
                                "av.saturation": LIST_DESATURATE}),
    ]


def _fade_filter(length: int, fade: int) -> str:
    """An alpha fade in and out, as compose.overlay_graph does with fade=...:alpha=1.

    `brightness` with `level` held at 1 and `alpha` keyframed touches only the alpha
    channel: letting the level follow would darken the card as it fades, which the
    export does not do.
    """
    fade = max(1, min(fade, length // 2))
    last = length - 1
    return _filter("brightness", {
        "level": 1,
        "alpha": f"0=0;{fade}=1;{max(fade, last - fade)}=1;{last}=0",
    })


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


def _music_fade(length: int, fps: int) -> str:
    """music.mix_filter's afade in and out, as a keyframed volume level."""
    from .music import FADE_IN, FADE_OUT

    last = length - 1
    fade_in = min(round(FADE_IN * fps), last)
    fade_out = max(fade_in, last - round(FADE_OUT * fps))
    return _filter("volume", {"level": f"0=-60;{fade_in}=0;{fade_out}=0;{last}=-60"})


# ---------------------------------------------------------------------------- timeline


@dataclass(frozen=True)
class Clip:
    """One stretch of one source, placed on one track of the final timeline, in frames."""

    track: str          # ecran | large | serre | audio
    source: str         # the producer it reads: screen_v, face_v, face_lead, screen_a, face_a
    src_in: int         # first frame read inside the source
    at: int             # where it lands on the final timeline
    length: int
    window: int | None = None  # the list card it plays behind, if any

    @property
    def end(self) -> int:
        return self.at + self.length


def _frame(seconds: float, fps: int) -> int:
    return round(seconds * fps)


def body_clips(kept, *, fps: int, offset: float, has_face: bool, mic_from_face: bool,
               body_offset: float = 0.0, gap_after: int | None = None,
               gap_length: float = 0.0) -> list[Clip]:
    """Where every kept segment lands, per track, end to end in the order of the edit.

    Positions are rounded from the running time in seconds rather than summed from rounded
    lengths, so a long edit never drifts from the float timestamps the slide plan uses.
    """
    clips: list[Clip] = []
    cursor = body_offset
    for index, seg in enumerate(kept):
        at = _frame(cursor, fps)
        length = _frame(cursor + seg.duration, fps) - at
        cursor += seg.duration
        if length > 0:
            if seg.scene == "ecran" or not has_face:
                # `face` absent on a screen-only shoot: a stale EDL naming a camera shot
                # must still show the screen.
                clips.append(Clip("ecran", "screen_v", _frame(seg.start, fps), at, length))
            else:
                # Opening words: the camera was not recording yet. Its first frame is
                # frozen for the lead-in; face_lead is that frozen frame.
                lead = min(length, _frame(max(0.0, offset - seg.start), fps))
                if lead:
                    clips.append(Clip(seg.scene, "face_lead", 0, at, lead))
                if length > lead:
                    clips.append(Clip(seg.scene, "face_v",
                                      _frame(max(0.0, seg.start - offset), fps),
                                      at + lead, length - lead))
            # MIC_SOURCE=face reads the camera's audio at SCREEN timestamps, as the old
            # ffmpeg render did — kept as is, though it ignores the camera offset.
            clips.append(Clip("audio", "face_a" if mic_from_face else "screen_a",
                              _frame(seg.start, fps), at, length))
        if gap_after is not None and index == gap_after:
            cursor += gap_length  # the intro card plays here, on the slide track
    return clips


def split_windows(clips: list[Clip], windows: list[tuple[int, int]]) -> list[Clip]:
    """Cut the picture clips at the list cards' edges, and tag what plays behind them.

    The export blurs the composite for exactly the card's span; a producer filter can only
    blur a whole clip, so the clips are cut to that span first.
    """
    out: list[Clip] = []
    for clip in clips:
        if clip.track == "audio":
            out.append(clip)
            continue
        pieces = [clip]
        for number, (start, end) in enumerate(windows):
            next_pieces: list[Clip] = []
            for piece in pieces:
                lo, hi = max(piece.at, start), min(piece.end, end)
                if piece.window is not None or lo >= hi:
                    next_pieces.append(piece)
                    continue
                if lo > piece.at:
                    next_pieces.append(replace(piece, length=lo - piece.at))
                next_pieces.append(replace(
                    piece, at=lo, length=hi - lo, window=number,
                    src_in=piece.src_in + (0 if piece.source == "face_lead" else lo - piece.at),
                ))
                if hi < piece.end:
                    next_pieces.append(replace(
                        piece, at=hi, length=piece.end - hi,
                        src_in=piece.src_in + (0 if piece.source == "face_lead" else hi - piece.at),
                    ))
            pieces = next_pieces
        out.extend(pieces)
    return out


def producer_id(clip: Clip) -> str:
    """A clip behind a list card needs its own producer, since that is where filters go."""
    return clip.source if clip.window is None else f"{clip.source}_{clip.track}_list{clip.window}"


def _tc(frame: int, fps: int) -> str:
    return mlt_timecode(frame / fps)


def _entry(producer: str, src_in: int, length: int, fps: int) -> str:
    # `out` is the last frame PLAYED: in + length - 1.
    return (f'    <entry producer="{producer}" in="{_tc(src_in, fps)}" '
            f'out="{_tc(src_in + length - 1, fps)}"/>')


def _blank(length: int, fps: int) -> str:
    return f'    <blank length="{_tc(length, fps)}"/>'


def _track_rows(clips: list[Clip], fps: int) -> list[str]:
    rows: list[str] = []
    cursor = 0
    for clip in sorted(clips, key=lambda c: c.at):
        if clip.at > cursor:
            rows.append(_blank(clip.at - cursor, fps))
        rows.append(_entry(producer_id(clip), clip.src_in, clip.length, fps))
        cursor = clip.end
    return rows


# ---------------------------------------------------------------------------- slides, music


def _slide_producers(images: list[Path], fades: list[int | None], fps: int) -> str:
    """One producer per slide image.

    `qimage` is MLT's still-image service and it honours the alpha channel, which is what
    lets an overlay sit on top of the picture in Shotcut exactly as it does in the export.
    This is the whole reason the slides are PNGs rather than an ffmpeg drawtext: a filter
    cannot be imported into a project, an image can.

    `fades[i]` is the overlay's length in frames when it fades (overlays), None for a card,
    which cuts in and out like the concatenated segment it is in the export.
    """
    hour = 3600 * fps
    rows = []
    for index, (image, fade_len) in enumerate(zip(images, fades, strict=True)):
        fade = _fade_filter(fade_len, round(OVERLAY_FADE * fps)) if fade_len else ""
        rows.append(
            f'  <producer id="slide{index}" out="{_tc(hour - 1, fps)}">'
            f'{_prop("length", _tc(hour, fps))}{_prop("resource", image)}'
            f'{_prop("mlt_service", "qimage")}{fade}</producer>'
        )
    return "\n".join(rows)


def _slide_track(entries: list[tuple[int, float, float]], fps: int = 30) -> list[str]:
    """Lay slides on their own track, separated by blanks.

    Entries are (producer index, start, end) in FINAL seconds — the same numbers the
    slide plan uses, so every slide lands where the plan put it.
    """
    rows: list[str] = []
    cursor = 0
    for index, start, end in sorted(entries, key=lambda e: e[1]):
        at, stop = _frame(start, fps), _frame(end, fps)
        if at < cursor:  # never overlap the previous slide by a rounding frame
            at = cursor
        if stop <= at:
            continue
        if at > cursor:
            rows.append(_blank(at - cursor, fps))
        rows.append(_entry(f"slide{index}", 0, stop - at, fps))
        cursor = stop
    return rows


def hold_last_card(entries: list[tuple[int, float, float]], cards: int, video_end: int,
                   music_end: int, fps: int) -> list[tuple[int, float, float]]:
    """Stretch the card that closes the video until the music under it has faded out.

    `entries` are (producer index, start, end) with the cards first (indexes below
    `cards`). Only a card ending the video is held — an overlay never is, it would cover
    the body.
    """
    if music_end <= video_end:
        return entries
    out = list(entries)
    for i, (index, start, end) in enumerate(out):
        if index < cards and _frame(end, fps) >= video_end:
            out[i] = (index, start, music_end / fps)
    return out


def _music_producers(beds, fps: int = 30) -> str:
    """One producer per bed, audio only, each carrying its own level and fades.

    Not one per file. Two beds can read the same track at very different levels — the
    music under a card sits at speech level, the bed under speech 18 dB below it — and in
    MLT a filter attaches to a producer, never to a playlist entry. One producer per bed is
    what lets each stretch keep the level the render gave it.
    """
    hour = 3600 * fps
    return "\n".join(
        f'  <producer id="music{index}" out="{_tc(hour - 1, fps)}">'
        f'<property name="length">{_tc(hour, fps)}</property>'
        f'<property name="resource">{bed.track}</property>'
        f'<property name="mlt_service">avformat-novalidate</property>'
        f'<property name="video_index">-1</property>'
        f"{_volume_filter(bed.gain_db)}"
        f"{_music_fade(max(2, _frame(bed.end, fps) - _frame(bed.start, fps)), fps)}"
        "</producer>"
        for index, bed in enumerate(beds)
    )


def _music_track(beds, fps: int = 30) -> list[str]:
    """Music on its own playlist, so it can be levelled or muted without touching the voice.

    Each entry reads its own slice of its own track: `in`/`out` are positions INSIDE the
    music file, the blanks before them place it on the timeline. `beds` must already be in
    timeline order — the entry at position i refers to the producer built from bed i.
    """
    rows: list[str] = []
    cursor = 0
    for index, bed in enumerate(beds):
        at, stop = max(cursor, _frame(bed.start, fps)), _frame(bed.end, fps)
        if stop <= at:
            continue
        if at > cursor:
            rows.append(_blank(at - cursor, fps))
        rows.append(_entry(f"music{index}", _frame(bed.source_offset, fps), stop - at, fps))
        cursor = stop
    return rows


# ---------------------------------------------------------------------------- the project


def _chain(pid: str, resource: Path, length: int, fps: int, *, audio: bool,
           filters: list[str] = ()) -> str:
    """An avformat producer reading only the picture, or only the sound, of a rush."""
    only = '<property name="audio_index">-1</property>' if not audio else \
        '<property name="video_index">-1</property>'
    return (
        f'  <chain id="{pid}" out="{_tc(length - 1, fps)}">{_prop("length", _tc(length, fps))}'
        f'{_prop("resource", resource)}{_prop("mlt_service", "avformat-novalidate")}{only}'
        f'{"".join(filters)}</chain>'
    )


def build(ep: Episode, plan: Edl, layout: SlidePlan | None = None) -> str:
    cfg = ep.cfg
    fps = cfg.out_fps
    kept = plan.kept
    screen = ep.screen.resolve()
    screen_dur = ffprobe_duration(screen)
    face = ep.face.resolve() if ep.has_face else None
    face_dur = ffprobe_duration(face) if face else screen_dur
    offset = camera_offset(ep)
    params = json.loads(ep.params.read_text()) if ep.params.is_file() else {}

    dar_w, dar_h = display_aspect(cfg.out_w, cfg.out_h)
    cam = ffprobe_dimensions(face) if face else None
    scr = ffprobe_dimensions(screen)

    # --- the body, in frames, cut where the list cards blur it
    intro_card = next((c for c in layout.cards if c.kind == "intro"), None) if layout else None
    clips = body_clips(
        kept, fps=fps, offset=offset, has_face=bool(face), mic_from_face=cfg.mic_from_face,
        body_offset=layout.body_offset if layout else 0.0,
        gap_after=intro_card.after_index if intro_card else None,
        gap_length=intro_card.duration if intro_card else 0.0,
    )
    windows = [
        (_frame(o.start, fps), _frame(o.end, fps))
        for o in (layout.overlays if layout else []) if o.kind == "list"
    ]
    clips = split_windows(clips, windows)

    # How much the framing enlarges each track's source: the list blur is scaled by it.
    scales = {
        "ecran": cover_scale(scr, cfg.out_w, cfg.out_h),
        "large": cover_scale(cam, cfg.out_w, cfg.out_h),
        "serre": cover_scale(cam, cfg.out_w, cfg.out_h, zoom=cfg.zoom_scale),
    }

    screen_len = max(1, _frame(screen_dur, fps))
    face_len = max(1, _frame(face_dur, fps))
    producers: dict[str, str] = {}

    def base(source: str, pid: str, extra: list[str]) -> str:
        if source == "screen_v":
            return _chain(pid, screen, screen_len, fps, audio=False, filters=extra)
        if source == "screen_a":
            return _chain(pid, screen, screen_len, fps, audio=True, filters=extra)
        if source == "face_a":
            return _chain(pid, face, face_len, fps, audio=True, filters=extra)
        if source == "face_lead":
            # A still of the camera's first frame, for the words said before it started.
            freeze = _filter("freeze", {"frame": 0, "freeze_after": 1})
            return _chain(pid, face, face_len, fps, audio=False, filters=[freeze, *extra])
        return _chain(pid, face, face_len, fps, audio=False, filters=extra)

    for clip in clips:
        pid = producer_id(clip)
        if pid not in producers:
            extra = _list_filters(scales[clip.track]) if clip.window is not None else []
            producers[pid] = base(clip.source, pid, extra)
    # The track heads below need these to exist even when no clip uses them.
    if face is None:
        # The wide and close-up tracks stay in the project even when there is no camera,
        # so the track indexes in the transitions are the same in both cases.
        producers.setdefault("face_v", f'  <producer id="face_v" out="{_tc(face_len - 1, fps)}">'
                             f'{_prop("length", _tc(face_len, fps))}'
                             f'{_prop("mlt_service", "color")}{_prop("resource", "0")}</producer>')

    by_track = {name: [c for c in clips if c.track == name]
                for name in ("ecran", "large", "serre", "audio")}

    # --- slides: cards and overlays share one track, in final-timeline order
    slide_images: list[Path] = []
    slide_fades: list[int | None] = []
    slide_entries: list[tuple[int, float, float]] = []
    if layout:
        from . import compose

        cards, overlays = compose.render_all(ep, layout)
        for image, card in zip(cards, layout.cards, strict=True):
            slide_entries.append((len(slide_images), card.start, card.end))
            slide_images.append(image)
            slide_fades.append(None)
        for image, overlay in zip(overlays, layout.overlays, strict=True):
            slide_entries.append((len(slide_images), overlay.start, overlay.end))
            slide_images.append(image)
            slide_fades.append(_frame(overlay.end, fps) - _frame(overlay.start, fps))

    # --- music: its own playlist, so it can be levelled or muted without touching the voice
    music_beds = []
    if cfg.music and layout and (layout.cards or layout.overlays):
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

    # The black background runs under everything, cards included: the outro plays past
    # the body, and a tractor ends with its longest track.
    ends = [c.end for c in clips] + [_frame(e, fps) for _, _, e in slide_entries]
    total = max(ends, default=1)
    # The outro's music runs 1.4 s past the card (music.TAIL). The ffmpeg render mixes it
    # onto a picture that has already ended, so a player holds the outro's last frame while
    # it fades; here the tractor would run on into 1.4 s of black instead. Holding the last
    # card to the end of the music is what the export looks like.
    music_end = max((_frame(bed.end, fps) for bed in music_beds), default=0)
    slide_entries = hold_last_card(slide_entries, len(layout.cards) if layout else 0,
                                   total, music_end, fps)
    total = max(total, music_end)

    nl = "\n"
    track_music = _music_track(music_beds, fps) if music_beds else []
    music_block = (
        f"{_music_producers(music_beds, fps)}\n"
        f'  <playlist id="track_music">\n{nl.join(track_music)}\n  </playlist>'
        if track_music else ""
    )
    track_slides = _slide_track(slide_entries, fps)
    slides_block = (
        f"{_slide_producers(slide_images, slide_fades, fps)}\n"
        f'  <playlist id="track_slides">\n{nl.join(track_slides)}\n  </playlist>'
        if track_slides else ""
    )

    # Track heads: the framing, and the correction measured on the camera. Correction
    # first, so it works on the camera's own pixels.
    correction = av_filters(params.get("video_filter", "")) if face else []
    screen_head = (
        [_size_position(cover_rect(scr, cfg.out_w, cfg.out_h))]
        if scr and scr != (cfg.out_w, cfg.out_h) else []
    )
    large_head = [*correction, _size_position(cover_rect(cam, cfg.out_w, cfg.out_h))]
    serre_head = [*correction,
                  _size_position(cover_rect(cam, cfg.out_w, cfg.out_h, zoom=cfg.zoom_scale))]
    voice_head = audio_filters(params.get("audio_filter", ""))

    def playlist(pid: str, rows: list[str], head: list[str]) -> str:
        heads = "".join(f"\n    {f}" for f in head)
        return f'  <playlist id="{pid}">\n{nl.join(rows)}{heads}\n  </playlist>'

    audio_index = 5 if track_slides else 4
    tracks = [
        '    <track producer="black"/>',
        '    <track producer="track_ecran"/>',
        '    <track producer="track_large"/>',
        '    <track producer="track_serre"/>',
        *(['    <track producer="track_slides"/>'] if track_slides else []),
        '    <track producer="track_audio" hide="video"/>',
        *(['    <track producer="track_music" hide="video"/>'] if track_music else []),
    ]

    def blend(b: int) -> str:
        return ('    <transition mlt_service="frei0r.cairoblend">'
                f'{_prop("a_track", 0)}{_prop("b_track", b)}</transition>')

    def mix(b: int) -> str:
        return ('    <transition mlt_service="mix">'
                f'{_prop("a_track", 0)}{_prop("b_track", b)}'
                f'{_prop("always_active", 1)}{_prop("sum", 1)}</transition>')

    transitions = [blend(1), blend(2), blend(3)]
    if track_slides:
        transitions.append(blend(4))
    transitions.append(mix(audio_index))
    if track_music:
        transitions.append(mix(audio_index + 1))

    return f"""<?xml version="1.0" encoding="utf-8"?>
<mlt LC_NUMERIC="C" version="7.40.0" title="screencast">
  <profile description="{cfg.out_h}p {fps} fps" width="{cfg.out_w}" height="{cfg.out_h}" progressive="1"
    sample_aspect_num="1" sample_aspect_den="1" display_aspect_num="{dar_w}" display_aspect_den="{dar_h}"
    frame_rate_num="{fps}" frame_rate_den="1" colorspace="709"/>
  <producer id="black" out="{_tc(total - 1, fps)}">{_prop("length", _tc(total, fps))}{_prop("mlt_service", "color")}{_prop("resource", "0")}</producer>
{nl.join(producers.values())}
{playlist("track_ecran", _track_rows(by_track["ecran"], fps), screen_head)}
{playlist("track_large", _track_rows(by_track["large"], fps), large_head)}
{playlist("track_serre", _track_rows(by_track["serre"], fps), serre_head)}
{playlist("track_audio", _track_rows(by_track["audio"], fps), voice_head)}
{slides_block}
{music_block}
  <tractor id="main">
{nl.join(tracks)}
{nl.join(transitions)}
  </tractor>
</mlt>
"""


def run(ep: Episode, plan: Edl, layout: SlidePlan | None = None) -> None:
    log("emit Shotcut project")
    ep.project.write_text(build(ep, plan, layout))
    log(f"project -> {ep.project}")
    log("  3 video tracks: ecran / large / serre, plus slides, mic and music on their own")
    log("  with the 'Size Position Rotate' filter — serre already carries the zoom.")


# ---------------------------------------------------------------------------- melt render


def melt_command(ep: Episode, project: Path, out: Path, *,
                 start: float | None = None, end: float | None = None) -> list[str | Path]:
    """melt-7 rendering `project`: x264 veryfast at DRAFT_CRF, yuv420p, OUT_FPS.

    `real_time=-1`: one rendering thread, frames in order. Parallel frame rendering
    (Shotcut's default export) hands consecutive audio blocks to different threads, and
    the voice chain — noise reduction, levelling — carries state from one block to the
    next. x264 still uses every core.
    """
    cfg = ep.cfg
    cmd: list[str | Path] = [cfg.melt_bin, "-quiet", project]
    if start is not None:
        cmd.append(f"in={_frame(start, cfg.out_fps)}")
    if end is not None:
        cmd.append(f"out={_frame(end, cfg.out_fps) - 1}")
    # The audio leaves melt LOSSLESS, in a Matroska: master.py normalises it and encodes it
    # once. An AAC here would be encoded twice, and its overshoot measured as program.
    cmd += [
        "-consumer", f"avformat:{out}", "f=matroska",
        "vcodec=libx264", "preset=veryfast", f"crf={cfg.draft_crf}", "pix_fmt=yuv420p",
        "acodec=pcm_f32le", "ar=48000", "channels=2",
        "real_time=-1", "terminate_on_pause=1",
    ]
    return cmd


def render(ep: Episode, plan: Edl, layout: SlidePlan | None = None, *,
           project: Path | None = None, out: Path | None = None) -> Path:
    """The `render` stage: write the project, play it, master the sound.

    The music has to exist before the project is written, since the project only points
    at it.
    """
    project = project or ep.project
    out = out or ep.draft
    if ep.cfg.music and layout and layout.cards:
        from . import compose

        compose.generate_music(ep, layout, plan.metadata)
    project.write_text(build(ep, plan, layout))
    log(f"project -> {project}")
    from . import master

    mix = out.with_name(out.stem + ".melt.mkv")
    partial = out.with_name(out.stem + ".part" + out.suffix)
    log(f"melt -> {mix}")
    run_tool(melt_command(ep, project, mix), passthrough_stderr=True)
    master.master(ep, mix, partial)
    partial.replace(out)  # a killed render never leaves a half file under the real name
    mix.unlink()
    log(f"draft -> {out}")
    return out
