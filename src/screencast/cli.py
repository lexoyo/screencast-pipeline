"""The command line: one binary, a few verbs.

    screencast new                 latest OBS recording -> full deliverable
    screencast new <rush.mkv>      that recording, when it is not the latest
    screencast run <stage> <ep>    a single stage, when iterating
    screencast doctor              resolved config + which tools are missing

`new` is the one you use after a shoot. The rest exist because a full run takes minutes
and you should not have to re-transcribe five minutes of audio to test a render.
"""

from __future__ import annotations

import argparse
import os
import sys
from pathlib import Path
from shutil import which

from . import (
    cuts,
    measure,
    montage,
    publish,
    qc,
    render,
    shotcut,
    silences,
    slideplan,
    subtitles,
    timeline,
    transcribe,
)
from .channel import ChannelError
from .channel import load as load_channel
from .config import ConfigError, describe, load
from .episode import Episode, MissingInput
from .shell import ToolError, log, set_log_file
from .timeline import TimelineError

PROMPTS = Path(__file__).resolve().parent / "prompts"
# The project root is wherever the `screencast` executable sits — two levels up from this
# module under the src/ layout. Counting parents is brittle, so config.env is looked up
# rather than assumed: see default_config_path().
PROJECT_ROOT = Path(__file__).resolve().parents[2]
RECORDINGS = Path(os.environ.get("REC_DIR", Path.home() / "Videos" / "Screencasts"))
CONTAINERS = (".mkv", ".mp4", ".mov")

CHANNEL = None  # set from --channel before any stage runs

STAGES = (
    "measure",
    "transcribe",
    "silences",
    "montage",
    "render",
    "shotcut",
    "subtitles",
    "publish",
    "qc",
)

# Every external binary the harness drives, and what stops working without it.
TOOLS = {
    "ffmpeg": "everything — measuring, cutting, rendering",
    "ffprobe": "reading durations",
    "melt-7": "rendering the Shotcut project (optional; Shotcut itself does not need it)",
}


def default_config_path() -> Path:
    """Where to find config.env, in order of precedence.

    It is a user file, not a package resource: you edit it, you do not ship it. So the
    working directory wins over the project root — that way a second machine, or a test
    shoot with different settings, needs no flag.
    """
    from os import environ

    if environ.get("SCREENCAST_CONFIG"):
        return Path(environ["SCREENCAST_CONFIG"]).expanduser()
    here = Path.cwd() / "config.env"
    return here if here.is_file() else PROJECT_ROOT / "config.env"


def _newest_recording(folder: Path) -> Path | None:
    """Most recent recording in a folder, whatever container OBS was set to."""
    candidates = [p for p in folder.glob("*") if p.is_file() and p.suffix.lower() in CONTAINERS]
    return max(candidates, key=lambda p: p.stat().st_mtime, default=None)


def _plan(ep: Episode):
    """Load the edit decision list, make its cuts safe, persist what survives.

    Sanitising happens here rather than in the montage stage so that re-running a render
    picks up a fix without paying for another model call.
    """
    import json

    plan = timeline.load(ep.edl)
    silences = json.loads(ep.silences.read_text()) if ep.silences.is_file() else []
    plan, notes = cuts.sanitize(plan, silences)
    for note in notes:
        log(f"  cut check: {note}")
    stats = cuts.report(plan, silences)
    log(
        f"cuts: {stats['cuts']} kept after checks, {stats['seconds_cut']:.0f}s removed "
        f"({stats['share']:.0%} of the take)"
    )
    if stats["share"] > 0.25:
        log("  ⚠ more than a quarter of the take was cut — worth watching before publishing")
    timeline.write_kept(ep.kept, plan.kept)
    return plan


def run_stage(name: str, ep: Episode) -> None:
    if name == "measure":
        measure.run(ep)
    elif name == "transcribe":
        transcribe.run_stage(ep)
    elif name == "silences":
        silences.run(ep)
    elif name == "montage":
        montage.run_stage(ep, PROMPTS)
    elif name == "render":
        plan = _plan(ep)
        render.run(ep, plan, slideplan.build(plan, plan.kept, channel=CHANNEL.as_values()))
    elif name == "shotcut":
        plan = _plan(ep)
        shotcut.run(ep, plan, slideplan.build(plan, plan.kept, channel=CHANNEL.as_values()))
    elif name == "subtitles":
        try:
            title = timeline.load(ep.edl).metadata.title
        except TimelineError:
            title = ""
        subtitles.run_stage(ep, PROMPTS, title)
    elif name == "publish":
        plan = _plan(ep)
        publish.run(ep, plan, PROMPTS,
                    slideplan.build(plan, plan.kept, channel=CHANNEL.as_values()))
    elif name == "qc":
        plan = _plan(ep)
        qc.run(ep, plan, PROMPTS,
               slideplan.build(plan, plan.kept, channel=CHANNEL.as_values()))
    else:
        raise ValueError(f"unknown stage: {name}")


def _closest_camera(screen: Path) -> Path | None:
    """The camera rush written closest in time to this screen rush.

    Not "the newest": re-running an older episode is normal — `new <an older take>` — and
    the newest camera file then belongs to a different day. Closest in time is the same
    answer as newest for a fresh shoot, and the right one for an old take.
    """
    folder = RECORDINGS / "cam"
    if not folder.is_dir():
        return None
    files = [p for p in folder.iterdir() if p.is_file() and p.suffix.lower() in CONTAINERS]
    if not files:
        return None
    when = screen.stat().st_mtime
    return min(files, key=lambda p: abs(p.stat().st_mtime - when))


PAIRING_WINDOW = 300.0
"""How far apart two rushes may be written and still be the same take, in seconds.

OBS closes both files within seconds of each other. The camera folder, however, keeps
every past shoot, so "the newest camera file" is only the right one when it was written
alongside this screen rush — otherwise it belongs to another day, and pairing them would
put someone else's six minutes of face onto this video without a word.
"""


def cmd_new(args, cfg) -> int:
    """Pair the newest screen recording with the camera file of the same take, then run."""
    screen = Path(args.screen).resolve() if args.screen else _newest_recording(RECORDINGS)
    if not screen or not screen.is_file():
        print(f"no screen recording found in {RECORDINGS}", file=sys.stderr)
        return 1

    camera: Path | None = None
    if args.cam:
        camera = Path(args.cam).resolve()
        if not camera.is_file():
            print(f"no such camera file: {camera}", file=sys.stderr)
            return 1
        if camera.suffix.lower() not in CONTAINERS:
            # The automatic path filters on container; --cam used not to, and a symlinked
            # text file passed every check until ffmpeg met it, ten minutes and one model
            # call into the run.
            print(f"not a video file: {camera.name} ({', '.join(CONTAINERS)})", file=sys.stderr)
            return 1
    elif not args.no_cam:
        candidate = _closest_camera(screen)
        if candidate:
            apart = abs(candidate.stat().st_mtime - screen.stat().st_mtime)
            if apart <= PAIRING_WINDOW:
                camera = candidate
            else:
                # Neither guess is safe here: pairing them makes a video out of two
                # different shoots, and dropping the camera silently turns a normal take
                # into a screen-only one. So it stops and asks.
                print(f"the closest camera file is {apart / 60:.1f} min from the screen rush,",
                      file=sys.stderr)
                print("so they are probably not the same take:", file=sys.stderr)
                print(f"  screen : {screen}", file=sys.stderr)
                print(f"  camera : {candidate}", file=sys.stderr)
                print("  --cam <file> to pair another one, --no-cam to shoot screen-only",
                      file=sys.stderr)
                return 1
        else:
            print(f"no camera file in {RECORDINGS / 'cam'} — screen-only shoot")
            print("  (the OBS Source Record filter is what produces one)")

    root = RECORDINGS / f"{screen.stem}_montage"
    root.mkdir(parents=True, exist_ok=True)
    # Symlinks rather than copies: the rushes are the master, and a 800 MB duplicate per
    # episode is not worth it. The container is kept so nothing has to guess later.
    links = [(root / f"screen{screen.suffix}", screen)]
    if camera:
        links.append((root / f"face{camera.suffix}", camera))
    for link, target in links:
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)

    # Recorded, so a later `run` on this episode can tell "shot without a camera" from
    # "the camera rush is missing" — the second must stop, the first must not.
    marker = root / ".screen-only"
    if camera and marker.is_file():
        marker.unlink()
    elif not camera:
        marker.write_text("no camera rush for this shoot\n")

    overrides = {"screen_file": f"screen{screen.suffix}"}
    if camera:
        overrides["face_file"] = f"face{camera.suffix}"
    cfg = cfg.__class__(**{**cfg.__dict__, **overrides})
    print(f"écran  : {screen}")
    print(f"caméra : {camera if camera else '— aucune, tournage écran seul'}")
    print(f"montage: {root}")
    print("-" * 60)
    return _run_pipeline(root, cfg, STAGES)


def cmd_run(args, cfg) -> int:
    return _run_pipeline(
        Path(args.episode).resolve(), cfg, STAGES if args.stage == "all" else (args.stage,)
    )


def check_tools(cfg) -> list[str]:
    """What is missing before anything is computed, in the order it would be needed.

    `doctor` has always been able to say this; a `run` never asked. So a missing whisper
    surfaced as a traceback after a minute of audio work, and a missing sonorita-cli would
    have surfaced after the transcription, the model call and the render — the expensive
    three — were already paid for.
    """
    missing: list[str] = []
    if not cfg.whisper_bin.exists():
        missing.append(f"whisper: {cfg.whisper_bin}")
    if not cfg.whisper_model.exists():
        missing.append(f"whisper model: {cfg.whisper_model}")
    if not which(cfg.claude_bin) and not Path(cfg.claude_bin).is_file():
        missing.append(f"the montage brain: {cfg.claude_bin}")
    if cfg.music and not which(cfg.sonorita_bin):
        missing.append(f"sonorita-cli: {cfg.sonorita_bin} (or run with --no-music)")
    return missing


def _run_pipeline(root: Path, cfg, stages) -> int:
    missing = check_tools(cfg)
    if missing:
        print("missing before anything can run:", file=sys.stderr)
        for item in missing:
            print(f"  ✗ {item}", file=sys.stderr)
        return 1

    ep = Episode(root=root, cfg=cfg)
    ep.ensure_dirs()

    # One run per episode. Two concurrent runs write the same transcript and the same
    # segment files, and the result is silently wrong rather than loudly broken.
    lock = ep.work / "running.pid"
    if lock.is_file():
        pid = lock.read_text().strip()
        if pid.isdigit() and Path(f"/proc/{pid}").exists():
            print(f"another run is already working on this episode (pid {pid})", file=sys.stderr)
            print(f"  wait for it, or remove {lock} if it is stale", file=sys.stderr)
            return 1
    lock.write_text(str(os.getpid()))

    set_log_file(ep.log_file)
    try:
        for name in stages:
            run_stage(name, ep)
    except (MissingInput, TimelineError, ToolError, ConfigError) as exc:
        log(f"STOPPED: {exc}")
        return 1
    finally:
        lock.unlink(missing_ok=True)
    return 0


def cmd_plan(args, cfg) -> int:
    """Show where the slides land, without rendering anything."""
    ep = Episode(root=Path(args.episode).resolve(), cfg=cfg)
    ep.ensure_dirs()
    set_log_file(ep.log_file)
    try:
        plan = _plan(ep)
    except (TimelineError, MissingInput) as exc:
        print(exc, file=sys.stderr)
        return 1
    kept = plan.kept
    layout = slideplan.build(plan, kept, channel=CHANNEL.as_values())
    print()
    print(slideplan.describe(layout, sum(seg.duration for seg in kept)))
    return 0



def cmd_doctor(args, cfg) -> int:

    print("configuration:")
    print(describe(cfg))
    print("\ntools:")
    missing = 0
    for tool, why in TOOLS.items():
        found = which(tool)
        print(f"  {'✓' if found else '✗'} {tool:12s} {found or 'MISSING — ' + why}")
        missing += not found
    for label, path in (("whisper", cfg.whisper_bin), ("whisper model", cfg.whisper_model)):
        ok = path.exists()
        print(f"  {'✓' if ok else '✗'} {label:12s} {path}")
        missing += not ok
    found = which(cfg.claude_bin)
    print(f"  {'✓' if found else '✗'} {cfg.claude_bin:12s} {found or 'MISSING'}")
    missing += not found
    # Only a problem when music is on: with MUSIC="off" the harness never calls it, and a
    # ✗ on a tool nobody needs is how a checklist stops being read.
    found = which(cfg.sonorita_bin)
    state = found or ("MISSING" if cfg.music else "not needed (MUSIC=off)")
    print(f"  {'✓' if found or not cfg.music else '✗'} {cfg.sonorita_bin:12s} {state}")
    missing += cfg.music and not found
    print(f"\nrecordings: {RECORDINGS}")
    return 1 if missing else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(
        prog="screencast",
        description="Turn an OBS screencast into a publishable video.",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__,
    )
    parser.add_argument(
        "--config", default=None, help="defaults to ./config.env, then the project root"
    )
    parser.add_argument(
        "--channel", default="alexhoyau", help="whose video this is (see src/screencast/channels)"
    )
    # config.env holds the language of the usual channel, and a shoot in another one is a
    # one-off: editing the file for a single episode is how you forget to edit it back and
    # transcribe the next take in the wrong language. `auto` hands the choice to whisper.
    parser.add_argument(
        "--no-music", action="store_true",
        help="skip the music under the cards (sonorita-cli is then not needed)",
    )
    parser.add_argument(
        "--lang", default=None, metavar="CODE",
        help="spoken language for this run ('en', 'fr', 'auto') — overrides FORCE_LANG",
    )
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="latest recording -> full deliverable")
    new.add_argument("screen", nargs="?", help="a specific screen recording")
    cam_choice = new.add_mutually_exclusive_group()
    cam_choice.add_argument("--cam", default=None, metavar="FILE",
                            help="the camera rush of this take (default: the closest in time)")
    cam_choice.add_argument("--no-cam", action="store_true",
                            help="screen-only shoot: every shot is the screen")
    new.set_defaults(func=cmd_new)

    one = sub.add_parser("run", help="a single stage on an existing episode")
    one.add_argument("stage", choices=(*STAGES, "all"))
    one.add_argument("episode")
    one.set_defaults(func=cmd_run)

    lay = sub.add_parser("plan", help="show where the slides land, render nothing")
    lay.add_argument("episode")
    lay.set_defaults(func=cmd_plan)

    doc = sub.add_parser("doctor", help="show config and check the toolchain")
    doc.set_defaults(func=cmd_doctor)

    args = parser.parse_args(argv)
    try:
        overrides: dict[str, str] = {}
        if args.lang:
            overrides["FORCE_LANG"] = args.lang
        if args.no_music:
            overrides["MUSIC"] = "off"
        cfg = load(
            Path(args.config) if args.config else default_config_path(),
            overrides=overrides or None,
        )
    except ConfigError as exc:
        print(f"config: {exc}", file=sys.stderr)
        return 2
    global CHANNEL
    try:
        CHANNEL = load_channel(args.channel)
    except ChannelError as exc:
        print(f"channel: {exc}", file=sys.stderr)
        return 2
    return args.func(args, cfg)
