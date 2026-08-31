"""The deliverable's two languages: the one spoken, and the one it is translated into.

Every video ships in the spoken language plus one translation — subtitles, metadata,
transcript. Which language that second one is was decided in three places at once, each
carrying its own copy of `"fr" if spoken == "en" else "en"`. Three copies is how a video
ends up with English subtitles under a French description.

The pair is deliberately not configurable. A channel that one day needs a third language
needs a list of targets and a loop, not another guess at what the second one should be.
"""

from __future__ import annotations

NAMES = {
    "en": "English",
    "fr": "French",
    "es": "Spanish",
    "de": "German",
    "it": "Italian",
    "pt": "Portuguese",
    "nl": "Dutch",
}

FALLBACK = "en"
"""What an undetected language is treated as.

Whisper writes "auto" when it will not commit, and a subtitle file has to be named
something. English is the safer bet for a channel that publishes docs.
"""


def spoken(language: str) -> str:
    """The spoken language, with "auto" and "" resolved to something usable."""
    return language if language and language != "auto" else FALLBACK


def resolve(harness: str, edl: str) -> str:
    """The spoken language, preferring what the harness knows to what the model said.

    Two sources answer this question. The harness one — FORCE_LANG, `--lang`, or the code
    whisper detected and wrote to lang.txt — is measured. The model's, the `language` field
    of the EDL, is asked for in a prompt and validated nowhere: it comes back absent or
    "auto" often enough, and an English default on a French shoot inverts the whole
    deliverable (English headings on a French description, UPLOAD.md naming the wrong
    subtitle file as primary). So the harness wins, and the model only fills a blank.
    """
    for candidate in (harness, edl):
        if candidate and candidate != "auto":
            return candidate
    return FALLBACK


def target(language: str) -> str:
    """The language the deliverable is translated INTO."""
    return "fr" if spoken(language) == "en" else "en"


def name(code: str) -> str:
    """The language's English name, for a prompt that has to say it in a sentence."""
    return NAMES.get(code, code)


def links_label(code: str) -> str:
    """Heading of the links block in a description, in the language of that description."""
    return "Projects mentioned" if code == "en" else "Projets mentionnés"
