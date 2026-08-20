"""Check the URLs before they ship in a description nobody proof-reads.

The model is told to leave a URL empty rather than guess one, but "sure of it" is not the
same as "still there": a project moves, a repo is renamed, a domain lapses. A dead link in
a YouTube description is seen by everyone and fixed by no one.

Two failures are not the same thing, and that distinction is the whole module. A 404 means
the page is gone — drop the URL, keep the name, since knowing what to search for is most of
the value. A 403 usually means the site refuses robots: openai.com answers 403 to anything
that is not a browser while being perfectly alive. Dropping those would strip the
description of its most ordinary links, so they are kept and reported.
"""

from __future__ import annotations

import re
import urllib.error
import urllib.request
from concurrent.futures import ThreadPoolExecutor
from dataclasses import dataclass

TIMEOUT = 8
WORKERS = 8

# Bot-hostile answers, not dead pages. A site that turns away a script still works for a
# viewer clicking the link, which is the only thing that matters here.
PROTECTED = {401, 403, 405, 406, 418, 429, 503}

# Sent because a bare urllib User-Agent is refused far more often than a browser one. The
# point is to learn whether a person clicking the link would land somewhere.
AGENT = (
    "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/128.0 Safari/537.36"
)

MARKDOWN_LINK = re.compile(r"\[([^\]]+)\]\((https?://[^)\s]+)\)")


@dataclass(frozen=True)
class Result:
    url: str
    status: str  # "ok" | "protégé" | "mort" | "injoignable"
    detail: str = ""

    @property
    def usable(self) -> bool:
        """Whether the URL still belongs in a public description."""
        return self.status in ("ok", "protégé")


def _fetch(url: str) -> int:
    """HTTP status for a URL. HEAD first, GET on refusal — some servers only answer GET."""
    for method in ("HEAD", "GET"):
        request = urllib.request.Request(url, method=method, headers={"User-Agent": AGENT})
        try:
            with urllib.request.urlopen(request, timeout=TIMEOUT) as response:
                return response.status
        except urllib.error.HTTPError as exc:
            if method == "GET" or exc.code not in (400, 405, 501):
                return exc.code
    return 0


def classify(url: str, status: int) -> Result:
    if 200 <= status < 400:
        return Result(url, "ok", str(status))
    if status in PROTECTED:
        return Result(url, "protégé", f"{status} — refuse les robots, à ouvrir à la main")
    if status:
        return Result(url, "mort", str(status))
    return Result(url, "injoignable", "pas de réponse")


def check(url: str, fetch=_fetch) -> Result:
    """Check one URL. `fetch` is injectable so the tests never touch the network."""
    if not url.strip():
        return Result(url, "ok", "vide")
    try:
        return classify(url, fetch(url))
    except (urllib.error.URLError, OSError, ValueError) as exc:
        return Result(url, "injoignable", type(exc).__name__)


def check_all(urls: list[str], fetch=_fetch) -> dict[str, Result]:
    """Check a batch concurrently — a dozen links one after another is half a minute."""
    unique = [u for u in dict.fromkeys(urls) if u.strip()]
    if not unique:
        return {}
    with ThreadPoolExecutor(max_workers=WORKERS) as pool:
        return {r.url: r for r in pool.map(lambda u: check(u, fetch), unique)}


def prune(links: list[dict], results: dict[str, Result]) -> list[dict]:
    """Blank out the URLs that are gone, keeping the names they were attached to."""
    out = []
    for item in links:
        url = (item.get("url") or "").strip()
        result = results.get(url)
        if url and result and not result.usable:
            item = {**item, "url": ""}
        out.append(item)
    return out


def unlink_dead(markdown: str, results: dict[str, Result]) -> str:
    """Turn `[name](dead-url)` back into plain `name` in the readable document.

    The document carries its links inline, so pruning `links.json` alone would leave the
    dead ones live in the very text a reader clicks.
    """
    def replace(match: re.Match[str]) -> str:
        result = results.get(match.group(2))
        return match.group(1) if result and not result.usable else match.group(0)

    return MARKDOWN_LINK.sub(replace, markdown)


def urls_in(markdown: str) -> list[str]:
    return [match.group(2) for match in MARKDOWN_LINK.finditer(markdown)]


def report(results: dict[str, Result]) -> list[str]:
    """One line per link worth mentioning. Silence when everything is fine."""
    lines = []
    for result in results.values():
        if result.status != "ok":
            lines.append(f"  {result.status:12s} {result.url}  ({result.detail})")
    return lines
