"""Every path the pipeline touches, named once.

Before this, filenames like "work/edl.json" were spelled out at a dozen call sites across
shell and Python. A typo in one of them produced a missing-file error pointing at the
wrong stage. Now the layout is declared here and nowhere else.
"""

from __future__ import annotations

from dataclasses import dataclass
from pathlib import Path

from .config import Config


class MissingInput(Exception):
    """A file a stage needs isn't there — usually an earlier stage that never ran."""


@dataclass(frozen=True)
class Episode:
    """One shoot: its rushes, its working files, its deliverable."""

    root: Path
    cfg: Config

    # ---- inputs (symlinked next to the rushes by nouvelle-video.sh)
    @property
    def screen(self) -> Path:
        return self.root / self.cfg.screen_file

    @property
    def face(self) -> Path:
        return self.root / self.cfg.face_file

    @property
    def mic(self) -> Path:
        """Whichever rush carries the microphone track."""
        return self.face if self.cfg.mic_from_face else self.screen

    # ---- working directory
    @property
    def work(self) -> Path:
        return self.root / "work"

    @property
    def segdir(self) -> Path:
        return self.work / "seg"

    @property
    def slidedir(self) -> Path:
        return self.work / "slides"

    # ---- working files
    @property
    def log_file(self) -> Path:
        return self.work / "log.md"

    @property
    def mic16(self) -> Path:
        """Normalized 16 kHz mono mic — what whisper transcribes."""
        return self.work / "mic16.wav"

    @property
    def params(self) -> Path:
        return self.work / "params.json"

    @property
    def transcript_json(self) -> Path:
        return self.work / "transcript.json"

    @property
    def segments(self) -> Path:
        return self.work / "segments.json"

    @property
    def words(self) -> Path:
        return self.work / "words.json"

    @property
    def lang_file(self) -> Path:
        return self.work / "lang.txt"

    @property
    def silences(self) -> Path:
        return self.work / "silences.json"

    @property
    def brain_prompt(self) -> Path:
        return self.work / "brain_prompt.txt"

    @property
    def brain_raw(self) -> Path:
        return self.work / "edl_raw.txt"

    @property
    def edl(self) -> Path:
        return self.work / "edl.json"

    @property
    def kept(self) -> Path:
        return self.work / "segments_kept.json"

    @property
    def draft(self) -> Path:
        return self.work / "draft.mp4"

    @property
    def concat_list(self) -> Path:
        return self.work / "concat.txt"

    @property
    def project(self) -> Path:
        return self.root / "project.mlt"

    @property
    def subs_dir(self) -> Path:
        return self.root / "subs"

    # ---- deliverable
    @property
    def deliverable(self) -> Path:
        return self.root / "deliverable"

    def ensure_dirs(self) -> None:
        self.work.mkdir(parents=True, exist_ok=True)

    def need(self, path: Path, hint: str = "") -> Path:
        if not path.is_file():
            suffix = f" — {hint}" if hint else ""
            raise MissingInput(f"missing input: {path}{suffix}")
        return path

    def language(self, default: str = "auto") -> str:
        if self.cfg.force_lang:
            return self.cfg.force_lang
        if self.lang_file.is_file():
            return self.lang_file.read_text().strip() or default
        return default
