"""Reading what a language model actually returned, rather than what it was asked for.

Prompts ask for raw JSON or a raw SRT and the model complies almost always — almost being
the operative word. A stray ```json fence or a polite sentence before the payload turns a
seven-minute run into a parse error, so every model answer goes through here first.
"""

from __future__ import annotations


def strip_code_fences(text: str) -> str:
    """Remove markdown fence lines, keeping everything between them."""
    return "\n".join(
        line for line in text.replace("\r", "").splitlines() if not line.lstrip().startswith("```")
    )


def extract_json_object(text: str) -> str:
    """Pull the first balanced {...} out of a model answer.

    Brace counting rather than a regex, because the payload contains nested objects. A
    truncated answer raises instead of half-parsing: a silently incomplete edit decision
    list would render a video missing its last third.
    """
    start = text.find("{")
    if start < 0:
        raise ValueError("no JSON object found in model output")
    depth = 0
    for index in range(start, len(text)):
        char = text[index]
        if char == "{":
            depth += 1
        elif char == "}":
            depth -= 1
            if depth == 0:
                return text[start : index + 1]
    raise ValueError("unbalanced JSON object in model output")


def clean_srt(raw: str) -> str:
    """Strip anything the model said before the first cue.

    An SRT starts with a cue index — a bare number on its own line. Everything before it
    is preamble ("Here is the translation:") and has to go, or the player rejects the
    whole file rather than skipping the bad part.
    """
    lines = strip_code_fences(raw).split("\n")
    first = next((i for i, line in enumerate(lines) if line.strip().isdigit()), 0)
    return "\n".join(lines[first:]).strip() + "\n"
