"""The slides and the music, shared by the Shotcut project that renders the video.

The images are drawn once, at the output frame, and the project points at them: what
Shotcut shows when the project is opened is what was exported.
"""

from __future__ import annotations

from pathlib import Path

from . import music, slides
from .episode import Episode
from .slideplan import Overlay, SlidePlan

# What a list card does to the picture behind it. The blur is what makes the text readable
# and shifts attention onto it; without it the card competes with a moving shot.
LIST_BLUR = 26
LIST_DARKEN = -0.14
LIST_DESATURATE = 0.55


def render_all(ep: Episode, layout: SlidePlan) -> tuple[list[Path], list[Path]]:
    """Render every slide once, as PNGs the Shotcut project points at.
    """
    ep.slidedir.mkdir(parents=True, exist_ok=True)
    # Drawn straight at the output frame: an overlay is composited pixel for pixel, so a
    # card rendered at another size would be either misaligned or resampled.
    frame = {"width": ep.cfg.out_w, "height": ep.cfg.out_h}
    cards = [
        slides.render(card.kind, card.values, ep.slidedir / f"card{index:02d}.png",
                      theme=layout.theme, **frame)
        for index, card in enumerate(layout.cards)
    ]
    overlays = [
        slides.render(overlay.kind, _overlay_values(overlay),
                      ep.slidedir / f"overlay{index:02d}.png", theme=layout.theme, **frame)
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


def generate_music(ep: Episode, layout: SlidePlan, plan_meta) -> dict[str, Path]:
    """The tracks under the cards, generated before the project that points at them."""
    # The sung lines come from `jingle`; the card titles are the fallback for an EDL
    # produced before that field existed.
    return music.build_tracks(
        ep,
        layout,
        intro_lyrics=plan_meta.jingle.get("intro")
        or (plan_meta.intro.title if plan_meta.intro else ""),
        outro_lyrics=plan_meta.jingle.get("outro")
        or (plan_meta.outro.title if plan_meta.outro else ""),
    )
