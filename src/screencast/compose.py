"""Put the slides onto the rendered video.

Two operations, deliberately separate from the segment rendering:

- a **card** becomes a video segment of its own, concatenated with the body;
- an **overlay** is composited onto the assembled video in a single pass.

Overlays are applied after concatenation rather than during segment rendering, because an
overlay's timing belongs to the finished timeline: one that starts near a cut would
otherwise have to be split across two segments and stitched back, and the arithmetic for
that is exactly the kind that goes wrong silently.
"""

from __future__ import annotations

from pathlib import Path

from . import music, slides
from .episode import Episode
from .shell import ffmpeg, ffprobe_duration, log, loudness_lufs
from .slideplan import DEFAULT_THEME, Card, Overlay, SlidePlan

# What a list card does to the picture behind it. The blur is what makes the text readable
# and shifts attention onto it; without it the card competes with a moving shot.
LIST_BLUR = 26
LIST_DARKEN = -0.14
LIST_DESATURATE = 0.55


def render_all(ep: Episode, layout: SlidePlan) -> tuple[list[Path], list[Path]]:
    """Render every slide once, for both consumers.

    The rendered video and the Shotcut project must show the same images: two renderers
    would drift, and the whole point of the project file is that it matches what was
    exported.
    """
    ep.slidedir.mkdir(parents=True, exist_ok=True)
    cards = [
        slides.render(card.kind, card.values, ep.slidedir / f"card{index:02d}.png",
                      theme=layout.theme)
        for index, card in enumerate(layout.cards)
    ]
    overlays = [
        slides.render(overlay.kind, _overlay_values(overlay),
                      ep.slidedir / f"overlay{index:02d}.png", theme=layout.theme)
        for index, overlay in enumerate(layout.overlays)
    ]
    return cards, overlays


def _overlay_values(overlay: Overlay) -> dict[str, str]:
    """Turn a programme's list of points into the markup its template expects."""
    values = dict(overlay.values)
    if overlay.kind == "plan":
        points = values.pop("chapters", [])
        values["items"] = slides.list_items(
            [(f"{n:02d}", label) for n, label in enumerate(points, start=1)]
        )
    return values


def render_card(ep: Episode, card: Card, index: int, *, audio: Path | None = None,
                theme: str = DEFAULT_THEME) -> Path:
    """Turn a card into a video segment, silent unless music is supplied."""
    cfg = ep.cfg
    image = slides.render(card.kind, card.values, ep.slidedir / f"card{index:02d}.png",
                          theme=theme)
    out = ep.segdir / f"card{index:02d}.mp4"

    args: list[str | Path] = ["-loop", "1", "-t", str(card.duration), "-i", image]
    if audio and audio.is_file():
        args += ["-i", audio]
    else:
        args += ["-f", "lavfi", "-t", str(card.duration), "-i", "anullsrc=cl=stereo:r=48000"]

    ffmpeg(
        args
        + [
            "-vf",
            f"scale={cfg.out_w}:{cfg.out_h},fps={cfg.out_fps},format=yuv420p",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(cfg.draft_crf),
            "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            "-shortest",
            out,
        ]
    )
    return out


def overlay_graph(overlays: list[tuple[Overlay, Path]], fade: float = 0.25) -> str:
    """Build the filtergraph that lays every overlay onto the assembled video.

    One chain, one encode. A list card also blurs and dims what is behind it — both are
    timeline-enabled filters, so they switch on for exactly the card's span.
    """
    if not overlays:
        return ""
    chain: list[str] = []
    current = "0:v"

    # blur and dim first, so the card is drawn over an already-quietened picture
    for index, (overlay, _) in enumerate(overlays):
        if overlay.kind != "list":
            continue
        window = f"between(t,{overlay.start},{overlay.end})"
        label = f"blur{index}"
        chain.append(
            f"[{current}]gblur=sigma={LIST_BLUR}:enable='{window}',"
            f"eq=brightness={LIST_DARKEN}:saturation={LIST_DESATURATE}:enable='{window}'[{label}]"
        )
        current = label

    for index, (overlay, _) in enumerate(overlays):
        # A hard cut on a text panel reads as a glitch; a quarter-second fade reads as a
        # deliberate card.
        #
        # The fade times are ABSOLUTE, which only works because each PNG is fed with
        # `-loop 1` and therefore runs alongside the video from second zero. Without the
        # loop a PNG is a single frame at t=0: `fade=t=in:st=29` would never be reached,
        # the alpha would stay at zero, and the overlay would be fully transparent — which
        # is exactly what shipped once. Every overlay was invisible in a six-minute render
        # and nothing in the logs said so.
        alpha = (
            f"format=rgba,fade=t=in:st={overlay.start}:d={fade}:alpha=1,"
            f"fade=t=out:st={max(overlay.start, overlay.end - fade)}:d={fade}:alpha=1"
        )
        faded = f"ov{index}"
        chain.append(f"[{index + 1}:v]{alpha}[{faded}]")
        label = f"v{index}"
        chain.append(
            f"[{current}][{faded}]overlay=0:0:enable='between(t,{overlay.start},{overlay.end})'"
            f"[{label}]"
        )
        current = label

    return ";".join(chain) + f";[{current}]null[out]"


def apply_overlays(ep: Episode, source: Path, layout: SlidePlan, out: Path) -> Path:
    """Composite every overlay onto `source`, in one encode."""
    if not layout.overlays:
        if source != out:
            out.write_bytes(source.read_bytes())
        return out

    _, images = render_all(ep, layout)
    rendered = list(zip(layout.overlays, images, strict=True))

    inputs: list[str | Path] = ["-i", source]
    for _, image in rendered:
        inputs += ["-loop", "1", "-i", image]  # see overlay_graph: the loop is what makes
        # the absolute fade times reachable

    log(f"compositing {len(rendered)} overlays")
    ffmpeg(
        inputs
        + [
            "-filter_complex", overlay_graph(rendered),
            "-map", "[out]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(ep.cfg.draft_crf),
            "-pix_fmt", "yuv420p", "-c:a", "copy",
            "-shortest",  # the looped PNGs are endless; the video decides the length
            out,
        ]
    )
    return out


def apply_music(ep: Episode, source: Path, layout: SlidePlan, plan_meta, out: Path) -> Path:
    """Mix the generated tracks under the video.

    Music is the normal case, so a failure here STOPS the run. This used to be the
    opposite — the absence was logged and the render shipped silent — and that is the
    wrong trade: a video that was meant to have music and quietly does not is a video that
    gets published before anyone notices. Not wanting music is a decision, and it is taken
    with MUSIC="off" in config.env or `--no-music`, which skips this step entirely.
    """
    if not ep.cfg.music:
        log("music disabled (--no-music)")
        if source != out:
            out.write_bytes(source.read_bytes())
        return out

    # The sung lines come from `jingle`; the card titles are the fallback for an EDL
    # produced before that field existed.
    tracks = music.build_tracks(
        ep,
        layout,
        intro_lyrics=plan_meta.jingle.get("intro")
        or (plan_meta.intro.title if plan_meta.intro else ""),
        outro_lyrics=plan_meta.jingle.get("outro")
        or (plan_meta.outro.title if plan_meta.outro else ""),
    )

    bed_duration = ffprobe_duration(tracks["bed"]) if "bed" in tracks else 0.0
    beds = music.with_gains(
        music.plan_beds(layout, tracks, bed_duration),
        tracks,
        ep.cfg.audio_lufs,
        loudness_lufs,
    )
    if not beds:
        if source != out:
            out.write_bytes(source.read_bytes())
        return out

    inputs: list[str | Path] = ["-i", source]
    for bed in beds:
        inputs += ["-i", bed.track]

    log(f"music: mixing {len(beds)} beds")
    ffmpeg(
        inputs
        + [
            "-filter_complex", music.mix_filter(beds),
            "-map", "0:v", "-map", "[aout]",
            "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-ar", "48000", "-ac", "2",
            out,
        ]
    )
    return out
