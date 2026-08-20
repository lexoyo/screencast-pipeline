"""The edit decision list: what the brain decided, in typed form.

Loading, computing and writing are three separate functions here. In the old code one
function did all three — `load_kept()` read the EDL *and* wrote segments_kept.json as a
side effect, and both the draft and the mlt stage called it, so the file was written
twice. Identical writes hide that kind of bug until the day they aren't identical.
"""

from __future__ import annotations

import json
from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

SCENES = ("ecran", "large", "serre")

# The brain used to emit these names; old EDLs on disk still have them.
LEGACY_SCENES = {"screencast": "ecran", "face": "large"}


class TimelineError(Exception):
    """The EDL is missing, malformed, or decides nothing."""


@dataclass(frozen=True)
class ListItem:
    """A spoken enumeration point, punctuated on screen."""

    n: str
    label: str

    @classmethod
    def parse(cls, data: Any) -> ListItem | None:
        if not isinstance(data, dict):
            return None
        n = str(data.get("n", "")).strip()
        label = str(data.get("label", "")).strip()
        return cls(n=n, label=label) if (n or label) else None


@dataclass(frozen=True)
class Chapter:
    at: float
    label: str


@dataclass(frozen=True)
class Tool:
    """A project named out loud, and where it was first named.

    Comes from the montage pass rather than from the transcript one, even though the
    transcript already lists the same projects for the description. The reason is order:
    the transcript is built from the FINISHED subtitles, which only exist after the render
    — far too late to put anything on screen. The brain reading the rush for the edit is
    the first moment these are known.

    `at` is a source timestamp, like a chapter's: the cut has not happened yet.
    """

    at: float
    name: str
    what: str = ""
    url: str = ""


@dataclass(frozen=True)
class Bookend:
    """The intro or outro card: a real segment, with music, that lengthens the video.

    Optional on purpose. A take with no title worth showing should not get an empty card,
    and the model is told to omit it rather than invent one.
    """

    title: str
    subtitle: str = ""

    @classmethod
    def parse(cls, data: Any) -> Bookend | None:
        if not isinstance(data, dict):
            return None
        title = str(data.get("title", "")).strip()
        subtitle = str(data.get("subtitle") or data.get("cta") or "").strip()
        return cls(title=title, subtitle=subtitle) if title else None


@dataclass(frozen=True)
class Metadata:
    title: str = ""
    description: str = ""
    tags: list[str] = field(default_factory=list)
    chapters: list[Chapter] = field(default_factory=list)
    intro: Bookend | None = None
    outro: Bookend | None = None
    tools: list[Tool] = field(default_factory=list)
    jingle: dict[str, str] = field(default_factory=dict)
    """The lines SUNG over the intro and outro cards, keyed "intro" / "outro".

    Separate from what is displayed, because they answer to different constraints: the
    card is read, the jingle is heard and has to scan. Above all it must be specific to
    THIS video — the same sung line on every episode stops being a signature and becomes a
    corporate jingle."""


@dataclass(frozen=True)
class Span:
    """One stretch of the source, kept or dropped."""

    start: float
    end: float
    drop: bool
    scene: str
    reason: str = ""
    list_item: ListItem | None = None
    plan: bool = False
    """True on the segment where the speaker announces the programme out loud.

    The programme overlay lasts exactly as long as that sentence — it accompanies what is
    being said instead of imposing itself, which is why nothing is shown at all when the
    speaker never announces one."""

    @property
    def duration(self) -> float:
        return self.end - self.start


@dataclass(frozen=True)
class KeptSegment:
    """A surviving span, with where it lands in the edited video."""

    start: float
    end: float
    scene: str
    final_start: float
    list_item: ListItem | None = None
    plan: bool = False

    @property
    def duration(self) -> float:
        return self.end - self.start

    @property
    def final_end(self) -> float:
        return self.final_start + self.duration

    def as_dict(self) -> dict[str, Any]:
        return {
            "start": self.start,
            "end": self.end,
            "dur": self.duration,
            "scene": self.scene,
            "list_item": (
                {"n": self.list_item.n, "label": self.list_item.label} if self.list_item else None
            ),
            "plan": self.plan,
            "final_start": self.final_start,
            "final_end": self.final_end,
        }


@dataclass(frozen=True)
class Edl:
    language: str
    metadata: Metadata
    timeline: list[Span]

    @property
    def kept(self) -> list[KeptSegment]:
        """The surviving spans, laid end to end on the edited timeline."""
        out: list[KeptSegment] = []
        cursor = 0.0
        for span in self.timeline:
            if span.drop or span.duration <= 0:
                continue
            out.append(
                KeptSegment(
                    start=span.start,
                    end=span.end,
                    scene=span.scene,
                    final_start=cursor,
                    list_item=span.list_item,
                    plan=span.plan,
                )
            )
            cursor += span.duration
        return out

    @property
    def final_duration(self) -> float:
        return sum(span.duration for span in self.timeline if not span.drop)


def _normalize_scene(value: Any) -> str:
    scene = str(value or "large")
    scene = LEGACY_SCENES.get(scene, scene)
    return scene if scene in SCENES else "large"


def parse(data: dict[str, Any]) -> Edl:
    meta_raw = data.get("metadata") or {}
    chapters = [
        Chapter(at=float(c["at"]), label=str(c.get("label", "")))
        for c in meta_raw.get("chapters") or []
        if "at" in c
    ]
    tools = [
        Tool(
            at=float(t["at"]),
            name=str(t.get("name", "")).strip(),
            what=str(t.get("what", "")).strip(),
            url=str(t.get("url", "")).strip(),
        )
        for t in meta_raw.get("tools") or []
        if "at" in t and str(t.get("name", "")).strip()
    ]
    metadata = Metadata(
        title=str(meta_raw.get("title", "")),
        description=str(meta_raw.get("description", "")),
        tags=[str(t) for t in meta_raw.get("tags") or []],
        chapters=sorted(chapters, key=lambda c: c.at),
        tools=sorted(tools, key=lambda t: t.at),
        intro=Bookend.parse(meta_raw.get("intro")),
        outro=Bookend.parse(meta_raw.get("outro")),
        jingle={
            key: str(value).strip()
            for key, value in (meta_raw.get("jingle") or {}).items()
            if str(value).strip()
        },
    )
    timeline = [
        Span(
            start=float(item["start"]),
            end=float(item["end"]),
            drop=bool(item.get("drop", False)),
            scene=_normalize_scene(item.get("scene")),
            reason=str(item.get("reason", "")),
            list_item=ListItem.parse(item.get("list_item")),
            plan=bool(item.get("plan", False)),
        )
        for item in data.get("timeline") or []
        if "start" in item and "end" in item
    ]
    if not timeline:
        raise TimelineError("EDL has an empty timeline — the brain decided nothing")
    return Edl(language=str(data.get("language", "auto")), metadata=metadata, timeline=timeline)


def load(path: Path) -> Edl:
    if not path.is_file():
        raise TimelineError(f"{path} not found — run the brain stage first")
    try:
        return parse(json.loads(path.read_text()))
    except json.JSONDecodeError as exc:
        raise TimelineError(f"{path} is not valid JSON: {exc}") from exc


def write_kept(path: Path, kept: list[KeptSegment]) -> None:
    """Persist the computed segments — the publish stage reads them back to remap chapters."""
    path.write_text(json.dumps([k.as_dict() for k in kept], indent=2))


def load_kept(path: Path) -> list[KeptSegment]:
    """Read back what the render stage computed, as the same type it wrote."""
    if not path.is_file():
        raise TimelineError(f"{path} not found — run the render stage first")
    return [
        KeptSegment(
            start=row["start"],
            end=row["end"],
            scene=row.get("scene", "large"),
            final_start=row["final_start"],
            list_item=ListItem.parse(row.get("list_item")),
            plan=bool(row.get("plan", False)),
        )
        for row in json.loads(path.read_text())
    ]
