"""The vocabulary Whisper does not know, and what to do about it.

Whisper transcribes French speech well and proper nouns badly: on a real take it wrote
"Cloudcode" for "Claude Code" and "Djann" for "Jan". On a channel about software, those
names are the subject of every video, and they end up in chapter titles — which are burnt
into slides, where a fix costs a re-render.

So the glossary is applied at BOTH ends:

- as `--prompt` to whisper, with `--carry-initial-prompt` so it is repeated across the
  whole file rather than biasing only the opening minute. This is free and fixes most of it
  before anything downstream sees the words;
- as a substitution pass afterwards, for what still slipped through.

The file is one entry per line, growing one shoot at a time:

    Claude Code = Cloudcode, cloud code
    Jan = Djann, Jann

The right-hand side matters more than it looks. Normalising case, accents and spacing
catches "hugging face" -> "Hugging Face", but "Cloudcode" and "Claude Code" normalise to
"cloudcode" and "claudecode": different words. Phonetic mistakes cannot be guessed, only
recorded — so the day a name comes out mangled, it gets added as an alias.
"""

from __future__ import annotations

import re
import unicodedata
from pathlib import Path

DEFAULT = Path(__file__).resolve().parent / "glossary.txt"


def parse(text: str) -> dict[str, list[str]]:
    """Canonical spelling -> its known mis-transcriptions."""
    entries: dict[str, list[str]] = {}
    for raw in text.splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        canonical, _, aliases = line.partition("=")
        canonical = canonical.strip()
        if not canonical:
            continue
        entries[canonical] = [a.strip() for a in aliases.split(",") if a.strip()]
    return entries


def load(path: Path | None = None) -> dict[str, list[str]]:
    path = path or DEFAULT
    return parse(path.read_text()) if path.is_file() else {}


def as_prompt(terms: dict[str, list[str]] | list[str], limit: int = 220) -> str:
    """The initial prompt handed to whisper.

    A prompt, not a list: whisper conditions on it as if it were the text preceding the
    audio, so a sentence primes the decoder better than comma-separated tokens. Kept short
    because it is prepended to every window — the flag that repeats it is what makes it
    work at minute nine, and a long prompt would eat the context that transcription needs.
    """
    if not terms:
        return ""
    # Only the canonical spellings: priming whisper with the mistakes would teach it those.
    names = list(terms) if isinstance(terms, dict) else terms
    prompt = "On parle ici de " + ", ".join(names) + "."
    return prompt[:limit]


def _normalise(text: str) -> str:
    """Lowercase, unaccented, spaces and punctuation removed.

    So that "Claude code", "cloud-code" and "Cloudcode" all collapse to the same key: the
    mistakes worth catching are exactly the ones that differ by a space, a hyphen or a
    capital.
    """
    stripped = unicodedata.normalize("NFD", text.lower())
    stripped = "".join(c for c in stripped if unicodedata.category(c) != "Mn")
    return re.sub(r"[^a-z0-9]", "", stripped)


def corrections(terms: dict[str, list[str]]) -> dict[str, str]:
    """Map every normalised form — canonical and alias alike — to the canonical spelling."""
    table: dict[str, str] = {}
    for canonical, aliases in terms.items():
        for form in (canonical, *aliases):
            key = _normalise(form)
            if key:
                table[key] = canonical
    return table


def fix(text: str, terms: dict[str, list[str]]) -> tuple[str, list[tuple[str, str]]]:
    """Replace mis-transcribed terms, and report what was changed.

    Only whole words and short runs of words are considered, up to the longest term in the
    glossary: "Claude Code" has to be caught as a pair, "Cloudcode" as one token. Casing
    and punctuation around the match are left alone.

    Returns the corrected text and the list of (before, after) pairs — silent substitution
    in a transcript is how you end up with a subtitle nobody can trace back to the audio.
    """
    if not terms:
        return text, []
    table = corrections(terms)
    longest = max(len(form.split()) for forms in
                  ([c, *a] for c, a in terms.items()) for form in forms)
    changed: list[tuple[str, str]] = []

    tokens = re.split(r"(\W+)", text)
    words = [i for i, token in enumerate(tokens) if token and token.isalnum()]

    index = 0
    while index < len(words):
        for size in range(min(longest, len(words) - index), 0, -1):
            span = words[index : index + size]
            phrase = "".join(tokens[span[0] : span[-1] + 1])
            canonical = table.get(_normalise(phrase))
            if canonical and phrase != canonical:
                changed.append((phrase, canonical))
                tokens[span[0]] = canonical
                for position in range(span[0] + 1, span[-1] + 1):
                    tokens[position] = ""
                index += size
                break
            if canonical:
                index += size
                break
        else:
            index += 1

    return "".join(tokens), changed
