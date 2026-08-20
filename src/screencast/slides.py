"""Render the slides: fill an HTML template, screenshot it with Chromium.

The templates are fixed. They are written once and never regenerated — a model fills in
values, it never produces markup. That is what keeps one video looking like the next, and
what makes it impossible for a bad generation to emit broken HTML into a render.

Chromium rather than Playwright, deliberately: Fedora already ships it, it screenshots a
1920x1080 page with transparency in under a second, and the alternative would drag Node,
npm and a second 150 MB browser into a project that has no dependencies at all. There is
nothing to wait for in a static page, which is the only thing Playwright would buy us.
"""

from __future__ import annotations

import html
import subprocess
from dataclasses import dataclass
from pathlib import Path
from string import Template

from .shell import ToolError, require

HERE = Path(__file__).resolve().parent
TEMPLATES = HERE / "templates"
THEMES = HERE / "themes"

# Overlays sit on top of the picture and need an alpha channel. Full-frame slides paint
# their own background, so the flag is harmless there and we pass it uniformly.
TRANSPARENT = "00000000"


class SlideError(Exception):
    """A template is missing, or the browser refused to render it."""


@dataclass(frozen=True)
class Slide:
    """One rendered still, and how it is meant to be used.

    `overlay` decides everything downstream: an overlay is composited over the shot and
    adds no time, a full-frame slide is a segment of its own and lengthens the video.
    """

    kind: str
    path: Path
    overlay: bool
    duration: float


def _chromium() -> str:
    for candidate in ("chromium-browser", "chromium", "chromium-headless-shell"):
        try:
            return require(candidate)
        except ToolError:
            continue
    raise SlideError(
        "chromium not found — it renders the slides. `dnf install chromium`, "
        "or run ./scripts/install.sh --check"
    )


def fill(template: str, theme: str, values: dict[str, str]) -> str:
    """Substitute $placeholders, leaving CSS braces alone.

    string.Template rather than str.format precisely because of those braces: a stylesheet
    is mostly `{` and `}`, and format() would choke on every rule. Missing keys become
    empty strings so a template with an optional subtitle still renders.
    """
    base = (TEMPLATES / "_base.css").read_text()
    filled = {key: html.escape(str(value)) for key, value in values.items()}
    # `items` is markup we generated ourselves (the <li> list), so it must not be escaped
    if "items" in values:
        filled["items"] = str(values["items"])
    return Template(template).safe_substitute(theme=theme, base=base, **filled)


def list_items(entries: list[tuple[str, str]]) -> str:
    """Build the <li> rows of the programme slide from (number, label) pairs."""
    return "".join(
        f'<li><span class="n">{html.escape(n)}</span>{html.escape(label)}</li>'
        for n, label in entries
    )


def render(
    kind: str,
    values: dict[str, str],
    out: Path,
    *,
    theme: str = "alexhoyau",
    width: int = 1920,
    height: int = 1080,
) -> Path:
    """Fill the `kind` template and screenshot it to `out`."""
    template_path = TEMPLATES / f"{kind}.html"
    theme_path = THEMES / f"{theme}.css"
    if not template_path.is_file():
        raise SlideError(f"no template for {kind!r} (looked in {TEMPLATES})")
    if not theme_path.is_file():
        raise SlideError(f"no theme named {theme!r} (looked in {THEMES})")

    out.parent.mkdir(parents=True, exist_ok=True)
    page = out.with_suffix(".html")
    page.write_text(fill(template_path.read_text(), theme_path.read_text(), values))

    proc = subprocess.run(
        [
            _chromium(),
            "--headless",
            "--disable-gpu",
            "--no-sandbox",
            "--hide-scrollbars",
            f"--default-background-color={TRANSPARENT}",
            f"--window-size={width},{height}",
            f"--screenshot={out}",
            page.as_uri(),
        ],
        capture_output=True,
        text=True,
    )
    if not out.is_file():
        tail = (proc.stderr or "").strip().splitlines()[-8:]
        raise SlideError(f"chromium produced no image for {kind}:\n  " + "\n  ".join(tail))
    return out
