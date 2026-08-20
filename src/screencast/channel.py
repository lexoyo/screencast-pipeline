"""Who the video belongs to: the name, the handle, the wording, the theme.

Separate from config.env, which holds *how* the harness works — paths, codecs, thresholds.
This holds *whose* video it is. A second channel means a second file here, not an edit in
the code, and nothing about the pipeline changes when a channel is renamed.
"""

from __future__ import annotations

import json
from dataclasses import asdict, dataclass
from pathlib import Path

CHANNELS = Path(__file__).resolve().parent / "channels"


class ChannelError(Exception):
    """No such channel, or its file cannot be read."""


@dataclass(frozen=True)
class Channel:
    """The identity that appears on the slides."""

    name: str
    handle: str = ""
    theme: str = "alexhoyau"
    programme_label: str = "Au programme"
    kicker: str = ""
    """The line above the title on the intro card — the channel's territory, not its name.

    It is the most-read zone of the video, and the name is already carried by the handle on
    every chapter band. Empty falls back to the name."""

    outro_title: str = ""
    """The last line of the video — the channel's promise, not the episode's subject.

    The model used to write it from the episode, which gave "Des LLM en local" on a video
    about Jan: a fine summary and a poor last word, since the closing frame is what a
    viewer carries away about the CHANNEL. Alex is about to publish on web design, Silex
    and WordPress too. Empty falls back to whatever the episode proposed."""

    cta: str = ""
    """The single line on the outro card, identical across every video.

    A property of the channel and not of the episode: a call to action rewritten each time
    makes attribution impossible. No URL here — the clickable link belongs in the
    description, where it can be tracked per video. Empty = no line at all."""

    logo: str = ""
    """Path to a logo image, relative to the channel file. Empty = no logo."""

    def as_values(self) -> dict[str, str]:
        return {k: v for k, v in asdict(self).items() if isinstance(v, str)}


def load(name: str) -> Channel:
    """Read a channel definition by name.

    Kept as plain JSON rather than another .env: this is data a human edits once in a
    while, and a mistyped key should say so rather than silently fall back to a default.
    """
    path = CHANNELS / f"{name}.json"
    if not path.is_file():
        available = ", ".join(sorted(p.stem for p in CHANNELS.glob("*.json"))) or "none"
        raise ChannelError(f"no channel named {name!r} (available: {available})")
    try:
        data = json.loads(path.read_text())
    except json.JSONDecodeError as exc:
        raise ChannelError(f"{path} is not valid JSON: {exc}") from exc

    known = {f for f in Channel.__dataclass_fields__}
    unknown = set(data) - known
    if unknown:
        raise ChannelError(
            f"{path}: unknown field(s) {', '.join(sorted(unknown))} — known: {', '.join(sorted(known))}"
        )
    if not data.get("name"):
        raise ChannelError(f"{path}: 'name' is required")
    return Channel(**data)
