"""The command line: one binary, a few verbs.

    screencast new                 latest OBS recording -> full deliverable
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

from . import (
    cuts,
    measure,
    montage,
    publish,
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
        publish.run(ep, _plan(ep))
    else:
        raise ValueError(f"unknown stage: {name}")


def cmd_new(args, cfg) -> int:
    """Pair the newest screen recording with the newest camera file, then run everything."""
    screen = Path(args.screen).resolve() if args.screen else _newest_recording(RECORDINGS)
    if not screen or not screen.is_file():
        print(f"no screen recording found in {RECORDINGS}", file=sys.stderr)
        return 1
    camera = _newest_recording(RECORDINGS / "cam")
    if not camera:
        print(f"no camera file found in {RECORDINGS / 'cam'}", file=sys.stderr)
        print(
            "  the OBS Source Record filter is what produces it — see docs/setup-obs.sh",
            file=sys.stderr,
        )
        return 1

    root = RECORDINGS / f"{screen.stem}_montage"
    root.mkdir(parents=True, exist_ok=True)
    # Symlinks rather than copies: the rushes are the master, and a 800 MB duplicate per
    # episode is not worth it. The container is kept so nothing has to guess later.
    for link, target in (
        (root / f"screen{screen.suffix}", screen),
        (root / f"face{camera.suffix}", camera),
    ):
        if link.is_symlink() or link.exists():
            link.unlink()
        link.symlink_to(target)

    cfg = cfg.__class__(
        **{
            **cfg.__dict__,
            "screen_file": f"screen{screen.suffix}",
            "face_file": f"face{camera.suffix}",
        }
    )
    print(f"écran  : {screen}")
    print(f"caméra : {camera}")
    print(f"montage: {root}")
    print("-" * 60)
    return _run_pipeline(root, cfg, STAGES)


def cmd_run(args, cfg) -> int:
    return _run_pipeline(
        Path(args.episode).resolve(), cfg, STAGES if args.stage == "all" else (args.stage,)
    )


def _run_pipeline(root: Path, cfg, stages) -> int:
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
    from shutil import which

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
    for tool in (cfg.claude_bin, cfg.sonorita_bin):
        found = which(tool)
        print(f"  {'✓' if found else '✗'} {tool:12s} {found or 'MISSING'}")
        missing += not found
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
    sub = parser.add_subparsers(dest="command", required=True)

    new = sub.add_parser("new", help="latest recording -> full deliverable")
    new.add_argument("screen", nargs="?", help="a specific screen recording")
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
        cfg = load(Path(args.config) if args.config else default_config_path())
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
