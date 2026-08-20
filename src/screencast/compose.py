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

from . import slides
from .episode import Episode
from .shell import ffmpeg, log
from .slideplan import Card, Overlay, SlidePlan

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
        slides.render(card.kind, card.values, ep.slidedir / f"card{index:02d}.png")
        for index, card in enumerate(layout.cards)
    ]
    overlays = [
        slides.render(overlay.kind, _overlay_values(overlay), ep.slidedir / f"overlay{index:02d}.png")
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


def render_card(ep: Episode, card: Card, index: int, *, audio: Path | None = None) -> Path:
    """Turn a card into a video segment, silent unless music is supplied."""
    cfg = ep.cfg
    image = slides.render(card.kind, card.values, ep.slidedir / f"card{index:02d}.png")
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
        # deliberate card. The alpha ramps in and out inside the overlay's own window.
        alpha = (
            f"format=rgba,fade=t=in:st={overlay.start}:d={fade}:alpha=1,"
            f"fade=t=out:st={max(overlay.start, overlay.end - fade)}:d={fade}:alpha=1"
        )
        faded = f"ov{index}"
        chain.append(f"[{index + 1}:v]{alpha},setpts=PTS-STARTPTS+{overlay.start}/TB[{faded}]")
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
        inputs += ["-i", image]

    log(f"compositing {len(rendered)} overlays")
    ffmpeg(
        inputs
        + [
            "-filter_complex", overlay_graph(rendered),
            "-map", "[out]", "-map", "0:a?",
            "-c:v", "libx264", "-preset", "veryfast", "-crf", str(ep.cfg.draft_crf),
            "-pix_fmt", "yuv420p", "-c:a", "copy",
            out,
        ]
    )
    return out
