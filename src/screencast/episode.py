"""Every path the pipeline touches, named once.

Before this, filenames like "work/edl.json" were spelled out at a dozen call sites across
shell and Python. A typo in one of them produced a missing-file error pointing at the
wrong stage. Now the layout is declared here and nowhere else.
"""

from __future__ import annotations

from dataclasses import dataclass, replace
from pathlib import Path

from .config import Config
from .shell import ffprobe_dimensions, log

CONTAINERS = (".mkv", ".mp4", ".mov", ".webm")


class MissingInput(Exception):
    """A file a stage needs isn't there — usually an earlier stage that never ran."""


@dataclass(frozen=True)
class Episode:
    """One shoot: its rushes, its working files, its deliverable."""

    root: Path
    cfg: Config

    # ---- inputs (symlinked next to the rushes when the episode is created)
    def _rush(self, configured: str, stem: str) -> Path:
        """Find a rush by stem, whatever container OBS was set to.

        The episode folder holds exactly one screen.* and one face.*, so the extension is
        discoverable and must never have to be repeated on the command line. It used to:
        a run would stop dead on "missing input: face.mkv" when the file was face.mp4, and
        the configured name only ever held a default nobody had reason to keep current.
        """
        exact = self.root / configured
        if exact.exists():
            return exact
        found = sorted(p for p in self.root.glob(f"{stem}.*") if p.suffix.lower() in CONTAINERS)
        return found[0] if found else exact

    @property
    def screen(self) -> Path:
        return self._rush(self.cfg.screen_file, "screen")

    @property
    def face(self) -> Path:
        return self._rush(self.cfg.face_file, "face")

    @property
    def screen_only(self) -> Path:
        """Marker written when the episode is created without a camera rush."""
        return self.root / ".screen-only"

    @property
    def has_face(self) -> bool:
        """Whether this shoot has a clean camera rush at all.

        A documentation screencast often has none: no camera, or the OBS Source Record
        filter was off. Everything the camera feeds — the wide and close-up shots, the
        face correction, the startup offset — then has nothing to work from, and the video
        is one continuous `ecran` shot. That is a normal shoot, not a failure: the screen
        rush already carries the webcam in a corner, baked in by OBS.
        """
        return not self.screen_only.is_file() and self.face.is_file()

    def need_face(self) -> None:
        """Stop unless the camera situation is the one this episode was created with.

        A missing camera file answers "is there a camera?" with "no" exactly as a
        screen-only shoot does — and those are not the same thing. One is a decision, taken
        once and recorded here; the other is a rush that was moved or archived, a drive
        that is not mounted, a Source Record filter left off. Without this distinction a
        normal two-camera shoot whose rush went missing would render as a screen-only video
        and report success, the failure showing up as one line in a long log.
        """
        if self.screen_only.is_file():
            return
        self.need(self.face, "the clean webcam rush — or re-create the episode with --no-cam")

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
        if self.cfg.forced_lang:
            return self.cfg.forced_lang
        if self.lang_file.is_file():
            return self.lang_file.read_text().strip() or default
        return default


def _even(value: float) -> int:
    """Round to an even number: libx264 with yuv420p refuses odd dimensions."""
    return max(2, int(round(value / 2)) * 2)


def open_episode(root: Path, cfg: Config) -> Episode:
    """The episode, with its output frame resolved against the screen rush.

    OUT_W and OUT_H are empty by default, which means "whatever the rush is". A screencast
    reads its own sharpness: rendering a 2560x1600 capture at its native size means the
    interface is never resampled at all, and — the reason this exists — nothing is cropped
    away to force a shape the rush never had.

    Setting one axis pins it and derives the other from the rush's ratio; setting both is
    an explicit override, the old behaviour. A shoot with no screen rush keeps 1920x1080,
    because there is nothing to measure and a stage that needs the file will say so with a
    better message than a probe failure here.
    """
    ep = Episode(root=root, cfg=cfg)
    if cfg.out_w and cfg.out_h:
        return ep

    dims = ffprobe_dimensions(ep.screen) if ep.screen.is_file() else None
    if dims is None:
        # Falling back per-axis would mix two shapes: OUT_W="1000" with an unreadable rush
        # used to take 1080 from the other default and render an almost square frame. 16:9
        # is the assumption this code exists to remove, but it is at least a whole one, and
        # it is what every episode before this change was rendered at.
        rush_w, rush_h = 1920, 1080
        log("frame: the screen rush could not be measured, assuming 16:9")
    else:
        rush_w, rush_h = dims
    if cfg.out_w:
        width, height = cfg.out_w, _even(cfg.out_w * rush_h / rush_w)
    elif cfg.out_h:
        width, height = _even(cfg.out_h * rush_w / rush_h), cfg.out_h
    else:
        width, height = _even(rush_w), _even(rush_h)

    # The camera is framed to the same rect, so a rush that disagrees with the screen is
    # cropped left and right. That is a deliberate trade — the screen is what a screencast
    # is about — but it is said out loud, because a silent crop is the whole reason this
    # function exists.
    cam = ffprobe_dimensions(ep.face) if ep.has_face and ep.face.is_file() else None
    log(f"frame: {width}x{height} (screen rush {rush_w}x{rush_h})")
    if cam and cam[0] * height != cam[1] * width:
        # `max`, not `min`: force_original_aspect_ratio=increase scales until the source
        # COVERS the frame and crops the overflow. Taking the smaller factor describes a
        # letterbox instead, and names the wrong axis — a 16:9 camera in a 16:10 frame
        # loses its sides, not its top.
        cover = max(width / cam[0], height / cam[1])
        lost_w = 1 - width / (cam[0] * cover)
        lost_h = 1 - height / (cam[1] * cover)
        axis = "left and right" if lost_w > lost_h else "top and bottom"
        log(f"  camera rush is {cam[0]}x{cam[1]}: it is cropped {axis}, "
            f"{max(lost_w, lost_h) / 2:.0%} off each side")
    return replace(ep, cfg=replace(cfg, out_w=width, out_h=height))
