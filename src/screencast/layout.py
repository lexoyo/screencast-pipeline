"""Text as it appears on screen: line breaks, and escaping for the ffmpeg filtergraph."""

from __future__ import annotations


def wrap(text: str, width: int = 24) -> list[str]:
    """Break a label into lines of at most `width` characters, on word boundaries.

    A word longer than `width` gets its own line rather than being cut: a truncated URL
    or command name on screen is worse than a line that overflows slightly.
    """
    lines: list[str] = []
    current = ""
    for word in text.split():
        if current and len(current) + 1 + len(word) > width:
            lines.append(current)
            current = word
        else:
            current = f"{current} {word}".strip()
    if current:
        lines.append(current)
    return lines


def escape_filter_path(path: str) -> str:
    """Escape a path for use inside an ffmpeg filtergraph.

    A path crosses two parsers on its way in — the filtergraph splits on `:` and `,`,
    then the option parser reads quotes — so every special character needs escaping
    twice. This is why on-screen labels are passed via `textfile=` and never `text=`:
    a French sentence with an apostrophe would otherwise break the graph.
    """
    return path.replace("\\", "\\\\").replace(":", "\\\\:").replace("'", "\\\\'")
